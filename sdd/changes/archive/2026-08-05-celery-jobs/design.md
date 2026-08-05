# Design: celery-jobs

## Context

`PropertyStateMachine` (`backend/app/properties/domain/state_machine.py`) ya implementa
**exactamente** las tres reglas de elegibilidad que este change necesita: su
`_validate_trigger_preconditions` (líneas 200-216) comprueba, para
`CHECKIN_WINDOW_OPENED`, `CHECKIN_TIME_REACHED` y `CHECKOUT_TIME_REACHED`, el estado de la
reserva y su posición respecto a los límites efectivos que `ContextualStateResolver._effective_bounds`
materializa en la zona de la propiedad. Lo que falta no es política: es **quien la invoca y
quien la persiste**. `backend/app/properties/` tiene `domain/` e `infrastructure/` y nada
más; `PropertyRepository` (`domain/repositories.py`) expone `get`,
`find_by_internal_code` y `find_by_pms_external_id` —**no tiene `save`**— y no existe
ningún repositorio de `PropertyStateTransition` pese a que su modelo sí está mapeado
(`infrastructure/models.py:77-92`).

`backend/app/worker.py` son cinco líneas: `Celery(...)` con broker y backend en
`settings.redis_url`, sin tareas ni `beat_schedule`. El compose de dev y el de deploy
levantan `worker`; ninguno levanta `beat`. `app/core/redis.py` ya expone un cliente
`redis.asyncio` compartido (`get_redis()`), y `redis>=8.0.1` es dependencia de runtime
desde `auth-tenancy`.

El precedente de ejecución fuera del ciclo de petición es
`app/integrations/cli/pms_sync.py`: abre su propia sesión de `async_session_factory`, la
marca con `bind_session_to_tenant`, importa `app.core.models_registry` por su efecto
lateral y compone el caso de uso a mano. Su propio docstring dice que el disparador
natural es Celery beat «cuando llegue `celery-jobs`» — ver OQ2.

## Decisions

### D1 — Puente sync↔async: `asyncio.run()` por ejecución, con engine propio del worker en `NullPool`

**Chosen:** cada tarea Celery es una función síncrona que hace `asyncio.run(_coro())`, y las
corrutinas usan un `worker_session_factory` construido **en el proceso worker** sobre un
engine creado con `poolclass=NullPool`, no el `engine` de módulo de `app/core/db.py`.

El engine de `app/core/db.py:24` se crea al importar, con el pool por defecto. Bajo
`asyncio.run()` repetido, una conexión asyncpg del pool sobrevive al bucle que la abrió y
la siguiente ejecución la reutiliza desde otro bucle: es el fallo *"attached to a different
loop"* contra el que `tests/conftest.py:75-96` ya se defiende exactamente así (NullPool).
Con cuatro tareas y una cadencia mínima de un minuto, el coste de abrir conexión por
ejecución es irrelevante frente al riesgo de reproducir ese fallo en producción.

**Y el mismo razonamiento aplica a Redis, cosa que la primera versión no hizo** (corregido el
2026-08-04 durante la verificación de la sección 9). `app/core/redis.py` cachea un cliente por
proceso, y un cliente de `redis.asyncio` pertenece al bucle que lo abrió: la **segunda** tarea
de cada proceso worker moría con `RuntimeError: Event loop is closed`. Medido en el stack de
dev antes del arreglo — `check_sla_breaches` alternaba éxito y fallo en ticks consecutivos —
y **ningún test lo cazaba**, porque todos ejecutan una sola vez por proceso. El scheduler usa
ahora `worker_redis()`, un cliente por ejecución, y `tests/scheduler/test_repeated_execution.py`
ejecuta dos veces en el mismo proceso, que es la única forma que lo detecta.

Rejected: bucle de eventos persistente por proceso worker con `run_coroutine_threadsafe` —
reutiliza el pool pero añade un hilo y un ciclo de vida propios, y su modo de fallo es el
mismo desajuste bucle/pool que ya nos costó caro.
Rejected: segundo stack síncrono (psycopg + `Session`) para los jobs — duplicaría todos los
repositorios; la regla de dependencia quedaría intacta y el mantenimiento no.

### D2 — Las tareas viven en `app/scheduler/`, y Celery no se importa en ningún dominio

**Chosen:** un paquete de entrega `backend/app/scheduler/` hermano de `app/cli/` —que ya es
el precedente de entrypoint no-dominio— con `schedule.py` (el `beat_schedule`), `tasks.py`
(las cuatro tareas, finas), `runner.py` (puente asyncio + orquestación por tenant) y
`locks.py`. Celery solo se importa en `app/worker.py` y en `app/scheduler/**`.

Las tareas son una **capa de entrega**, el equivalente de `api/` para el reloj: mapean un
disparo a un caso de uso y no contienen reglas. Ponerlas dentro de un dominio obligaría a
elegir uno, y no hay elección honesta: las tres primeras son de `properties` y la de SLA es
de `notifications`. `tests/test_layering.py` gana la aserción que lo fija por glob.

Rejected: `app/properties/infrastructure/tasks.py` — `infrastructure/` es *adaptadores que
implementan puertos del dominio*, y una tarea no implementa ninguno.
Rejected: todo en `app/worker.py` — un módulo que crece sin capas y que además es el
entrypoint del worker.

### D3 — La SQL es un prefiltro grueso; la autoridad de elegibilidad sigue siendo el dominio

**Chosen:** cada job selecciona candidatos con una consulta barata —propiedades del tenant
en los estados de origen del trigger, más sus reservas en una ventana de fechas alrededor
de `now`— y decide la elegibilidad **en Python, llamando a `PropertyStateMachine.evaluate`**
una vez por reserva candidata. Un `IncompatibleTransitionContextError` significa «esta
reserva no es», no un fallo; dos veredictos favorables para una misma propiedad son la
ambigüedad de R3.5.

Reimplementar en SQL la aritmética de `_effective_bounds` (fecha + hora local + zona de la
propiedad + `fold`) sería una segunda copia de la política, en un lenguaje donde la primera
no se puede verificar.

**La ventana es asimétrica, y eso lo corrigió el panel de la sección 3** (2026-08-04). La
primera versión usaba ±2 días simétricos y el revisor de QA encontró el agujero: los dos
triggers de entrada están acotados al **día local** de la reserva, así que 2 días de
adelanto los cubre con holgura para cualquier zona IANA; pero `CHECKOUT_TIME_REACHED`
**no tiene clamp de día** —vence con `now >= fin` y sigue venciendo— así que una caída del
worker de más de dos días dejaba la propiedad en `OCCUPIED_ESTIMATED` **para siempre**,
reportada como `not_eligible` e indistinguible de «no hay nada que hacer». El retraso pasa a
30 días (`CANDIDATE_LOOKBEHIND`), que es un límite operativo real y documentado en
`docs/celery-jobs.md`, no una derivación.

**Y la elegibilidad la decide la máquina, no el job** — también del mismo panel. El primer
borrador preguntaba primero (`status is CONFIRMED`, `start <= now < end`, `now >= fin`) y
solo llamaba a `evaluate` para la que pasaba el filtro, que es exactamente la alternativa
que D10 rechaza: las dos copias coincidían ese día y nada las mantenía sincronizadas.

Rejected: hacer el filtro completo en SQL con `AT TIME ZONE` — duplica la política y
`architecture.md` prohíbe que una transición se decida fuera de `PropertyStateMachine`.
Rejected: cargar todas las reservas del tenant — innecesario, y crece con la historia.

### D4 — El contexto que se pasa a la máquina lleva **solo** la reserva fuente

**Chosen:** `PropertyTransitionContext(reservations=(la_reserva,))`, con `cleaning_tasks` e
`incidents` vacíos.

No es una simplificación: para los tres triggers en alcance la política de
`_POLICY` tiene **destino único y fijo**, así que `_destination` no llama al
`ContextualStateResolver` y el contexto solo se usa para localizar la reserva fuente y
validar su scope. Además los estados de origen (`VACANT_READY`, `READY_FOR_NEXT_GUEST`,
`AWAITING_CHECKIN`, `OCCUPIED_ESTIMATED`) excluyen por construcción los de incidencia. Si un
trigger contextual entrara aquí en el futuro, el contexto tendría que crecer — queda dicho.

Rejected: cargar limpiezas e incidencias «por si acaso» — dos consultas por propiedad y por
ventana que ninguna rama de código lee.

### D5 — Un tenant, una sesión, una transacción; los tenants se enumeran desde una sesión nunca marcada

**Chosen:** `runner.py` abre **una** sesión sin marcar cuyo único uso es
`SELECT id FROM tenants WHERE status = ACTIVE`, la cierra, y después abre **una sesión nueva
por tenant**, la marca con `bind_session_to_tenant` y le entrega el trabajo de ese tenant.
Cada tenant es su propia transacción (`SqlAlchemyUnitOfWork.commit()`).

Es el contrato que `app/core/db.py:132-155` deja escrito: no hay desmarcado, re-marcar
reapunta el filtro a otro tenant, y la vía soportada para leer una tabla no acotada es una
sesión que **nunca** se marcó. `tenants` no lleva `tenant_id`, así que el filtro global no
la toca de todos modos; la sesión separada existe para que no pueda tocarla mañana.

Rejected: una sesión para todo el job filtrando a mano — un olvido apaga el aislamiento para
las 22 clases acotadas, que es precisamente el fallo que el filtro global existe para atrapar.

### D6 — Primer caso de uso de `properties`, y los tres puertos que le faltan

**Chosen:** `app/properties/application/use_cases.py` con
`AdvancePropertyStatesUseCase.execute(tenant_id, trigger, now) -> AdvanceReport`, y las
adiciones mínimas de puertos:

```python
# app/properties/domain/repositories.py
class PropertyRepository(Protocol):
    async def list_by_state(self, tenant_id, states: Collection[PropertyOperationalState]) -> list[Property]: ...
    async def save(self, tenant_id, property: Property) -> None: ...

class PropertyStateTransitionRepository(Protocol):   # nuevo puerto
    async def add(self, tenant_id, transition: PropertyStateTransition) -> None: ...

# app/reservations/domain/repositories.py
class ReservationRepository(Protocol):
    async def list_for_properties(self, tenant_id, property_ids, date_from, date_to) -> list[Reservation]: ...
```

Un solo caso de uso parametrizado por trigger en vez de tres: los tres comparten el bucle
completo —candidatos, contexto, `evaluate`, persistencia, informe— y solo difieren en los
estados de origen y en el criterio de selección de la reserva, que es una tabla de tres
entradas. `add` en el puerto de transiciones y no `save`: una transición es historia, no se
edita, igual que `TimelineEventRepository` solo expone `add`.

Rejected: tres casos de uso — el mismo cuerpo escrito tres veces.
Rejected: que el job escriba `current_operational_state` directamente — lo prohíbe
`backend.md` («no saltarse `PropertyStateMachine`») y R3.4.

### D7 — La ventana de check-in la aplica el job, no el dominio

**Chosen:** `check_checkin_windows` dispara cuando
`now >= inicio_efectivo - TenantConfig.checkin_window_hours_before`, **y** la fecha local de
`now` en la zona de la propiedad coincide ya con la fecha local del inicio.

La precondición del dominio para `CHECKIN_WINDOW_OPENED` es más laxa a propósito —solo exige
reserva `CONFIRMED` que entra **hoy**— porque describe lo que es *legal*, no cuándo conviene
dispararlo. La segunda condición no es redundante: con una hora de entrada temprana y una
ventana amplia, «`now` + ventana» cae en el día anterior y el dominio rechazaría la
transición; el clamp evita pedirle algo que va a rechazar cada cinco minutos.

Rejected: mover `checkin_window_hours_before` al dominio — es configuración operativa por
tenant, y meterla en la política ataría la máquina de estados a `TenantConfig`.
Rejected: ignorar el campo y disparar a medianoche local — dejaría un campo del esquema sin
ningún lector y contradiría PRD §8.3 («entran en ventana check-in»).

### D8 — Horas locales inexistentes o ambiguas: se saltan y se registran; no se normalizan

**Chosen:** `_localize_wall_time` levanta `IncompatibleTransitionContextError` cuando la hora
local de la reserva no existe (salto de primavera) o es ambigua (salto de otoño, porque
`Reservation.check_in_time` es un `TIME` sin zona y el dominio exige `fold` explícito). El job
lo captura por propiedad, lo cuenta aparte de «no elegible» en su informe y sigue.

Es una **limitación operativa real y se documenta como tal**: una reserva cuya hora local cae
en ese hueco no avanza nunca sola y necesita una transición manual. Elegir por ella
contradiría la regla que `timeline-state-machine` ya fijó («no normalizar en silencio»), y el
sitio para resolverlo es la captura del dato, no el reloj.

Rejected: caer a `default_check_in_time` de la propiedad — inventa un dato distinto del que
la reserva declara.
Rejected: desplazar al primer instante válido — normalización silenciosa, prohibida.

### D9 — Exclusión mutua por tarea con un lock de Redis, no por tenant

**Chosen:** cada tarea toma `SET scheduler:lock:<task> <token> NX PX <ttl>` sobre el Redis que
ya existe, con `ttl` = 3 × la cadencia de esa tarea, y lo libera al terminar comparando el
token (borrado condicional, para no liberar el lock de otro). Si no lo obtiene, termina
informando `skipped`, sin fallar.

Cubre las dos formas del problema con un solo mecanismo: una ejecución que se alarga más que
su cadencia (R4.2) y dos `beat` vivos a la vez durante un redespliegue (R1.5). El TTL cierra
el caso del worker muerto a mitad (R4.3).

Rejected: lock por tenant — más granular y más lento de razonar; el trabajo por tenant es de
milisegundos y no hay contención real que ganar.
Rejected: `celery.app.control` / `singleton` de terceros — dependencia nueva para diez líneas.
Rejected: confiar en una sola réplica de `beat` — cierto en el compose actual, y falso
durante cualquier `up -d` que solape contenedores.

### D10 — Los rechazos del dominio son resultado, no error

**Chosen:** el caso de uso trata `NoOperationalStateChangeError` e
`IncompatibleTransitionContextError` como clasificaciones del informe (`already_there`,
`not_eligible`), no como excepciones que suban. Solo un `InvalidTransitionInputError` o un
`TransitionEvidenceError` —que significan «el job construyó mal la petición»— se propagan
como fallo de la tarea.

Es lo que hace idempotente al job sin escribir una sola comprobación de idempotencia: la
máquina ya rechaza el destino igual al origen y la reserva que aún no ha llegado a su hora.

Rejected: comprobar el estado antes de llamar — duplicaría la política fuera de la máquina.

### D11 — SLA: enum de tipos, política de escalado pura, y la fila de escalado en `PENDING`

**Chosen:** tres piezas en `notifications`:

1. `NotificationType` como enum de Python en `domain/enums.py` con los 16 nombres de PRD §14.
   La columna sigue siendo `String(100)`, así que **no hay migración**; el enum es lo que
   permite que la política de escalado sea exhaustiva y verificable.
2. `domain/escalation.py`: función pura `escalation_for(notification_type) -> Escalation | None`
   — sin reloj, sin base de datos.
3. `application/use_cases.py`: `EscalateBreachedSlasUseCase`, que lee los candidatos, y por cada
   uno marca `sla_breached = True` y añade la fila de escalado con
   `status = NotificationStatus.PENDING`, ambas en la misma transacción.

`PENDING` es exactamente la costura con `access-notifications`: esa fila es trabajo encolado
para su emisor, no un envío fallido. `FAILED` mentiría (no se intentó) y `SENT` mentiría más.

El destinatario del escalado es el `PROPERTY_MANAGER` del tenant, resuelto con el listado de
usuarios de `user-management` filtrando por rol; el caso de varios y el de ninguno los cierra
D17. `subject`/`body` se rellenan con una plantilla que **no interpola ningún valor de
la regla 3**, y `last_error` no se escribe aquí; ambas cosas son la regla 11 de
`steering/security.md`, cuyo primer escritor pasa a ser este change y no `access-notifications`
— la tabla del steering se corrige al archivar.

Rejected: `PhoneAdapter.call` para `TECHNICIAN_ASSIGNED` + CRITICAL (PRD §14) — ese puerto no
existe en el código; se escala al manager y queda anotado para `access-notifications`.
Rejected: adelantar aquí el `NotificationAdapter` — es el alcance de otra entrada.

### D12 — Un tenant que falla no arrastra a los demás

**Chosen:** el bucle por tenant envuelve cada iteración en `try/except Exception`, hace
`rollback` de esa sesión, registra el fallo con el `tenant_id` y continúa. La tarea termina
`SUCCESS` con el recuento de tenants fallidos en su informe; solo un fallo *antes* del bucle
(Redis, enumeración de tenants) hace fallar la tarea.

Rejected: `autoretry_for` en la tarea entera — reintentaría también los tenants que ya
funcionaron, y con jobs idempotentes el siguiente tick ya es el reintento natural.

### D13 — `beat` como servicio propio, calendario en código, estado del scheduler no gestionado

**Chosen:** un servicio `beat` en `docker-compose.yml` y en `docker-compose.deploy.yml`
(`celery -A app.worker beat -l info`), misma imagen y mismas dependencias de arranque que
`worker`. El calendario vive en `app/scheduler/schedule.py` y se cablea en `app.worker`. El
fichero de estado del scheduler no se gestiona: si `beat` reinicia y vuelve a disparar antes
de tiempo, D9 y D10 lo hacen inofensivo.

**Corrección 2026-08-05 (revisor de cicd):** esta decisión decía «sistema de ficheros efímero
del contenedor», y eso es cierto **solo en deploy**. En dev el compose bind-montea
`./backend:/app`, así que `/app` del contenedor **es** el árbol del host y beat escribe
`backend/celerybeat-schedule` ahí, donde persiste entre reinicios. Esa premisa falsa es lo que
dejó el fichero fuera del `.gitignore` hasta que la revisión lo encontró — 16 KB de DBM binario
a un `git add -A` de entrar al repositorio. Ahora está ignorado; el comportamiento de beat no
cambia, porque la idempotencia nunca dependió de que el fichero desapareciera.

Healthcheck: `celery -A app.worker inspect ping` no sirve para `beat` (no responde al
protocolo de control), así que el del compose de deploy comprueba que PID 1 sigue siendo
beat —lo que `app-deploy-dev` exige es que el servicio declare uno, y esa spec se actualiza
al archivar. **Con Python, no con `pgrep`**: el revisor de cicd ejecutó la imagen y demostró
que `procps` no está en `python:3.12-slim` ni lo instala la etapa `prod`, así que un
healthcheck con `pgrep` habría salido 127 siempre, dejando a `beat` eternamente *unhealthy* y
tumbando `up -d --wait` —es decir, **todo el deploy**, no solo este servicio.

Rejected: `beat` embebido en el worker (`--beat`) — la propia documentación de Celery lo
desaconseja fuera de desarrollo, y con más de un worker dispararía N veces.
Rejected: cron del host — contradice IaC-first y saca el calendario de la imagen.

### D14 — La medición de R6 se hace con un contador en el listener, no con un profiler

**Chosen:** un test de rendimiento marcado y un script reproducible bajo `backend/scripts/`
que ejecuta el job de cadencia de un minuto sobre un conjunto sembrado, midiendo (a) número
de sentencias ORM interceptadas, (b) número de clases devueltas por `tenant_scoped_classes()`
en esa ejecución y (c) tiempo total dentro del listener. El resultado y el método van a
`docs/celery-jobs.md`.

El número que importa es *coste por sentencia × sentencias por ejecución*, y ese producto se
mide contando, no perfilando. Que la medición registre el número de clases es lo que la hace
comparable dentro de seis meses, cuando sean 30.

### D15 — `AuditLog` de estados: la regla 9 gana una excepción nombrada, no un incumplimiento

**Chosen:** este change **no** escribe `audit_logs` para las transiciones que produce —todas
con actor `SYSTEM`—, y edita la regla 9 de `steering/security.md` para decir que el registro
de auditoría de un cambio de estado de propiedad **con actor `SYSTEM`** es
`property_state_transitions`. (Decisión del usuario, 2026-08-04.)

> **Enmienda 2026-08-05, tras dos rondas del panel de seguridad y la revisión a escala de
> feature.** La redacción original de esta decisión era **incondicional** («el registro de
> auditoría de *estados de propiedad* es `property_state_transitions`») y el texto que se
> llevó al steering acabó siendo bastante más estrecho y más exigente. Como la regla 9 **cita
> esta decisión como su autoridad**, dejar aquí la versión superada significaba que quien
> siguiera la cita leería una exención en blanco. Lo que la regla dice de verdad:
>
> 1. **Acotada al actor `SYSTEM`.** `StateTransitionTriggeredBy` tiene cuatro miembros; solo
>    ese está exento. `USER` y `WEBHOOK` no lo están porque `audit_logs` aporta dos cosas que
>    la tabla de transiciones no tiene —`actor_ip` y el índice por actor que permite pivotar
>    «todo lo que hizo esta persona» a través de entidades— y solo la primera se replica con
>    una columna. `SCHEDULER` tampoco, pese a ser automático: no lo escribe ningún código hoy,
>    y pre-autorizar un actor que nadie ejercita contradice la propia cláusula de ampliación.
> 2. **`estados de propiedad` sigue en la enumeración de la regla 9.** Una versión intermedia
>    lo borró para acotar, con lo que el párrafo de «no está exenta» apuntaba a una obligación
>    inexistente. Es un recorte de la obligación, no su supresión.
> 3. **Dos cláusulas nuevas** que solo aprietan: todo escritor de `current_operational_state`
>    persiste su transición en la misma transacción, y ampliar la excepción exige entrada
>    nombrada aquí aprobada en el design del change que la pida — el razonamiento de arriba
>    **no** es un criterio reutilizable.

Esa tabla no es un sustituto aproximado: guarda `from_state`, `to_state`, `triggered_by`,
`triggered_by_user_id`, `reason`, `created_at` y `metadata`, que es **más** de lo que una fila
genérica de `audit_logs` registraría, y lo hace con el esquema del PRD §7. Con actor `SYSTEM`
la fila genérica no aportaría ningún «quién» que la transición no tenga ya, y dos filas para
el mismo hecho son dos orígenes de verdad que pueden divergir.

**El alcance del cambio de steering es exactamente ese y ni un milímetro más**: la regla 9
sigue exigiendo `AuditLog` para todo lo demás que enumera —Reservation, documentos de Guest,
AccessRecord, PricingRule/PriceRecommendation, OwnerApproval, roles de User, Incident—, y en
particular **no** absuelve a `reservations` de su deuda pendiente. La edición nombra la tabla
y la razón; no introduce el criterio «si hay una tabla específica, no hace falta AuditLog»,
que sería una puerta abierta.

Rejected: escribir además la fila genérica — segundo origen de verdad, cero información nueva.
Rejected: aplazarlo como deuda — dejaría una regla vinculante incumplida a sabiendas cuando la
respuesta correcta es que la regla estaba redactada antes de que existiera su escritor.

### D16 — El sync periódico del PMS **no** entra, y el docstring que lo promete se corrige

**Chosen:** no hay quinto job. `app/integrations/cli/pms_sync.py` sigue siendo la única vía de
sincronización, y su docstring (líneas 1-11) se corrige para que deje de decir que Celery beat
lo programará «cuando llegue `celery-jobs`». (Decisión del usuario, 2026-08-04.)

La cadencia sí está medida —8 créditos por ciclo, techo de un sync cada 24 s, recomendación del
proveedor ~6 h (`specs/pms-beds24-spike.md` §Hallazgos)—, pero está medida **contra Beds24, cuyo
adapter no existe**. Hoy el único selector de proveedor es un flag de operador con `mock` por
defecto, y programar un sync periódico contra el mock no verifica nada mientras mete en la
aplicación una configuración de proveedor que `pms_sync.py:54-66` evita a propósito para no
resucitar el `PMS_PROVIDER` global que ADR 0006 retiró. El job periódico llega con
`pms-beds24-adapter`, que es el dueño de la `PMSAdapterFactory`.

La corrección del docstring **es entregable de este change**, no una nota: dejar en el código
una promesa que esta entrada decidió no cumplir es la clase de mentira que el proyecto ya paga
cara en otros sitios.

Rejected: programarlo con el stopgap actual — sincronizaría el mock y arrastraría configuración
de proveedor a la aplicación.

### D17 — Escalado de SLA: una fila por manager activo; sin ninguno, el owner

**Chosen:** `EscalateBreachedSlasUseCase` resuelve los usuarios activos con rol
`PROPERTY_MANAGER` del tenant y escribe **una fila de escalado por cada uno**. Si no hay
ninguno activo, escala al `TENANT_OWNER`. (Decisión del usuario, 2026-08-04.)

El escalado existe para que alguien actúe; elegir un manager a dedo puede dárselo al que está
de vacaciones. El `TENANT_OWNER` es el destinatario de última instancia porque siempre existe
—`count_active_owners_excluding` de `user-management` protege esa invariante—, así que ningún
tenant pierde el aviso por estar mal configurado.

Consecuencia sobre R5.3 que conviene tener presente: la transacción atómica cubre **la marca
más todas** las filas de escalado de ese `NotificationLog`, no una a una; un fallo a mitad no
puede dejar `sla_breached = TRUE` con la mitad de los managers avisados.

Rejected: una sola fila al manager más antiguo — el aviso depende de que esa persona lo vea.
Rejected: marcar incumplido sin destinatario cuando no hay manager — pierde el aviso en
silencio, que es el fallo que este job existe para evitar.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Scheduler (nuevo) | `backend/app/scheduler/{__init__,schedule,tasks,runner,locks}.py` | Calendario, las 4 tareas, puente asyncio + bucle por tenant, lock Redis |
| Worker | `backend/app/worker.py` | Cablea `beat_schedule` y **importa `app.scheduler.tasks` por su efecto lateral** para registrarlas (no `autodiscover_tasks()`: el import explícito es visible y `test_layering.py` ya acota quién puede importar Celery). `app.core.models_registry` lo importa `runner.py`, que es quien abre sesiones |
| Properties · domain | `app/properties/domain/repositories.py` | `PropertyRepository.list_by_state` + `save`; nuevo `PropertyStateTransitionRepository` |
| Properties · application (nuevo) | `app/properties/application/use_cases.py` | `AdvancePropertyStatesUseCase`, `AdvanceReport` |
| Properties · infra | `app/properties/infrastructure/repositories.py` | Implementa los tres métodos nuevos (traduce `metadata` ↔ `metadata_`) |
| Reservations · domain/infra | `app/reservations/domain/repositories.py`, `infrastructure/repositories.py` | `list_for_properties(tenant_id, property_ids, date_from, date_to)` |
| Notifications · domain (nuevo) | `app/notifications/domain/{enums,escalation,repositories}.py` | `NotificationType`, `escalation_for`, puerto `NotificationLogRepository` |
| Notifications · application/infra (nuevos) | `app/notifications/{application/use_cases,infrastructure/repositories}.py` | `EscalateBreachedSlasUseCase`, adaptador SQLAlchemy |
| Integrations | `app/integrations/cli/pms_sync.py` | Corregir el docstring que promete el sync por beat (D16) — solo el docstring |
| Steering | `sdd/steering/security.md` | Regla 9: `property_state_transitions` es el registro de auditoría de un cambio de estado **con actor `SYSTEM`**; los demás actores escriben `AuditLog` (D15 y su enmienda). Regla 11: señalización de propiedad de los sumideros (tarea 7.6) |
| Compose | `docker-compose.yml`, `docker-compose.deploy.yml` | Servicio `beat` (y healthcheck en el de deploy) |
| Tests | `backend/tests/{properties,notifications,scheduler}/`, `tests/test_layering.py` | Unit de dominio y caso de uso con fakes; integración por tenant; aserción de que Celery no entra en dominios |
| Docs | `docs/celery-jobs.md`, `README.md`, `docs/diagrams/` | Cómo se opera, jobs y cadencias, medición de R6 |

## Data & interfaces

- **Migración Alembic: ninguna.** `property_state_transitions`, `timeline_events` y
  `notification_logs` ya existen con todas las columnas que este change escribe, y
  `NotificationType` es un enum de Python sobre una columna `String(100)`.
- **Variables de entorno nuevas: ninguna.** `REDIS_URL` y `DATABASE_URL` ya están en los dos
  composes y en `.env.example`.
- **API HTTP: sin cambios.** Ningún endpoint nuevo, así que `openapi.json` no se mueve y el
  check de contrato de `api-contract-export` debe seguir en verde sin regenerar.
- **Nombres de tarea** (PRD §8.3, literales): `check_checkin_windows`, `process_checkouts`,
  `mark_occupied_estimated`, `check_sla_breaches`.

| Trigger | Estados de origen | Selección de la reserva |
|---|---|---|
| `CHECKIN_WINDOW_OPENED` | `VACANT_READY`, `READY_FOR_NEXT_GUEST` | `CONFIRMED`, entrada hoy en zona local, dentro de la ventana (D7) |
| `CHECKIN_TIME_REACHED` | `AWAITING_CHECKIN` | `CONFIRMED`/`CHECKED_IN_ESTIMATED` con `inicio ≤ now < fin` |
| `CHECKOUT_TIME_REACHED` | `OCCUPIED_ESTIMATED` | `CONFIRMED`/`CHECKED_IN_ESTIMATED` con `now ≥ fin` |

Si más de una reserva de la misma propiedad cumple el criterio, la propiedad se salta y se
registra como ambigua: `_source_reservation` exige una y solo una, y elegir sería adjudicar
la vivienda a un huésped a dedo.

## Risks & mitigations

- **El coste del filtro global se paga 1 440 veces al día** en `check_sla_breaches`: 22
  clases × un `with_loader_criteria` por sentencia, sin memoizar. Es el riesgo que R6 existe
  para cuantificar; si el número asusta, la salida no es memoizar (`app/core/db.py:55-61`
  explica por qué) sino reducir sentencias por ejecución.
- **NullPool abre una conexión por ejecución** (D1): ~1 440 conexiones/día del job de un
  minuto más las de los de cinco. Despreciable para Postgres, pero se mide en R6 junto al
  resto y queda el bucle persistente como salida documentada si no lo fuera.
- **Redis es infraestructura de corrección, no solo de transporte** desde este change: el lock
  de D9 vive ahí. En el compose de deploy está en la red `private` sin puertos publicados; en
  `docker-compose.yml` se publica `6379:6379` en todas las interfaces del portátil, así que en
  dev local cualquiera en esa red puede soltar el lock. Es dev-local y tiene dueño:
  `local-dev-network-hardening`.
- **`AWAITING_CLEANING` es terminal hasta `cleaning`**: `process_checkouts` deja ahí la
  propiedad y nadie crea la `CleaningTask` que la sacaría. Asumido y anotado en la entrada
  `cleaning` del roadmap.
- **Reservas con hora local inexistente o ambigua no avanzan nunca solas** (D8). Se cuentan
  aparte en el informe para que sean visibles, no un silencio.
- **La suite se encarece**: los tests de integración de estos jobs piden `test_engine`, que es
  *function-scoped* y hace `create_all`/`drop_all` por test. Es exactamente lo que
  `backend-suite-runtime` tiene que atacar; aquí se limita el número de tests que tocan BD y
  se empuja lo posible a unit con fakes, como manda `backend-architecture.md`.
- **Reloj del worker**: todo se calcula con `datetime.now(UTC)` inyectado desde el borde y
  comparando instantes en UTC; ninguna hora local se deriva del reloj del contenedor.
- **Deuda: las claves ajenas de `property_state_transitions` y `notification_logs` no son
  compuestas con `tenant_id`** (anotada tras el panel de la sección 1). Los dos puertos
  declaran la precondición —el llamante resuelve `property_id`, `triggered_by_user_id` y
  `recipient_user_id` dentro del tenant antes de escribir— y las tareas 3.1 y 4.2 la
  pinnean con test, que es el mismo arreglo que `reservations` aplicó a `timeline_events`.
  Convertirlo en imposible exige migración y pertenece a un change de esquema, junto con
  la misma deuda ya registrada para `timeline_events` en `specs/reservations.md`. Se
  registra aquí para tener la paridad con ese precedente, que sí nombraba su deuda.

## Open questions

Ninguna abierta. Las tres que este design levantó se resolvieron con el usuario el
2026-08-04 y están arriba como D15, D16 y D17.
