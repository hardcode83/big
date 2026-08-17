# Design: seed-data-demo-extension

## Context

`backend/app/cli/seed_demo.py` (919 líneas) siembra hoy cuentas, propiedades, reservas y la
plantilla de checklist dentro de **una sola transacción**: `apply_plan` (`:355-466`) abre un
`SqlAlchemyUnitOfWork` en `:419`, compone cada caso de uso con `CallerOwnedUnitOfWork()`
(`backend/app/core/unit_of_work.py:41`, cuyo `commit()` no hace nada) y cierra con un único
`await uow.commit()` en `:465`. `_seed_checklist_template` (`:469-508`) es la plantilla canónica de
esa composición: instancia el repositorio SQLAlchemy, comprueba la clave de idempotencia, construye
el caso de uso con el uow del llamante y lo ejecuta.

Lo que este change añade no es «más filas»: es **hacer correr el reloj**. El estado operacional de
una vivienda sólo se mueve por `PropertyStateMachine`
(`backend/app/properties/domain/state_machine.py`), a la que se llega por
`AdvancePropertyStatesUseCase` (`backend/app/properties/application/use_cases.py:105-156`), que
recibe `now` por parámetro y un `provisioner` opcional que crea la `CleaningTask` del checkout
(`ProvisionCleaningTaskUseCase`, `backend/app/cleaning/application/use_cases.py:186`). Las
incidencias se mueven por los diez casos de uso de `maintenance`
(`backend/app/maintenance/application/use_cases.py`), todos sobre `_IncidentFlowBase` (`:525`), y la
limpieza por `Assign`/`Accept`/`Start`/`CompleteChecklistItem`/`UploadCleaningPhoto`/`Complete`
(`:787`, `:672`, `:756`, `:1200`, `:1300`, `:883`).

Tres hechos del código gobiernan casi todo lo que sigue, y ninguno era evidente desde el proposal:

1. `CHECKIN_WINDOW_OPENED` exige que la reserva entre **hoy** (`start.date() != instant.date()` →
   `IncompatibleTransitionContextError`, `state_machine.py:229`).
2. La reserva `DIRECT` del seed nace **`PENDING`** (`CreateReservationCommand` deja `status` en su
   default a propósito, `reservations/application/use_cases.py:48-55`;
   `reservations/domain/entities.py:98`), y las tres precondiciones de reloj exigen `CONFIRMED`.
3. `ReportGuestIncidentUseCase` fija `source=IncidentSource.GUEST` en el constructor de la entidad
   (`maintenance/application/use_cases.py:153`) y exige `reservation_id` y `reporter_token_hash`
   obligatorios (`:137-148`).

## Decisions

### D1 — Una segunda mitad de `apply_plan`, no un comando aparte

**Elegido:** `apply_plan` conserva su forma y gana una fase «avance» después de la actual, dentro de
la misma transacción y la misma función. El comando sigue siendo `make seed-demo` y su contrato de
consola sigue siendo un recuento por entidad.

Rechazado: un `seed-demo-advance` separado — dos transacciones, y «dataset sembrado pero sin avanzar»
es exactamente el estado intermedio que R4.5 prohíbe. Rechazado: un flag `--advance` — nadie querría
la mitad, y un flag que siempre se pasa es ruido.

### D2 — El orden de siembra es el orden cronológico de los hechos, y es el contrato

**Elegido:** la fase de avance replica los hechos en el orden en que habrían ocurrido. Fijarlo no es
estética: `_POLICY` (`state_machine.py:25-76`) es sensible al orden y hay una permutación que
**pierde la mitad del recorrido**.

Las tres estancias de §27 son de **REDES11** (PRD §27 titula la sección «Reservations (seed para
REDES11)»), así que todos los disparadores compiten por la misma vivienda. La secuencia:

| # | Hecho | Instante | Disparador | REDES11 queda en |
|---|---|---|---|---|
| 0 | — | — | — | `VACANT_READY` |
| 1 | La estancia DIRECT se confirma (D4) | hoy | — | `VACANT_READY` |
| 2 | Entra Pedro López | hoy−10 | `CHECKIN_WINDOW_OPENED` | `AWAITING_CHECKIN` |
| 3 | " | hoy−10 | `CHECKIN_TIME_REACHED` | `OCCUPIED_ESTIMATED` |
| 4 | Sale Pedro López | hoy−7 | `CHECKOUT_TIME_REACHED` (+ `CleaningTask`) | `AWAITING_CLEANING` |
| 5 | La estancia DIRECT pasa a `COMPLETED` | hoy−7 | — | `AWAITING_CLEANING` |
| 6 | Se asigna la limpieza — **la asigna el propio aprovisionador del paso 4** | hoy−7 | `CLEANER_ASSIGNED` | `CLEANING_SCHEDULED` |
| 7 | Empieza la limpieza | hoy−7 | `CLEANING_STARTED` | `CLEANING_IN_PROGRESS` |
| 8 | 18 ítems + 6 fotos + cierre | hoy−7 | `CLEANING_COMPLETED` | contextual (§ abajo) |
| 9 | Entra John Smith | hoy−2 | `CHECKIN_WINDOW_OPENED` | `AWAITING_CHECKIN` |
| 10 | " | hoy−2 | `CHECKIN_TIME_REACHED` | `OCCUPIED_ESTIMATED` |
| 11 | La estancia AIRBNB pasa a `CHECKED_IN_ESTIMATED` | hoy−2 | — | `OCCUPIED_ESTIMATED` |
| 12 | Las tres incidencias se crean y se clasifican | hoy | `INCIDENT_HIGH` (sólo la 2) | `MAINTENANCE_REQUIRED` |

**Enmienda del 2026-08-16 al paso 6** (panel de la sección 5, DESIGN-CONFLICT del arquitecto,
resuelto por Jose): el paso ocurre, pero **no lo ejecuta un `AssignCleaningTaskUseCase` del seed**.
Lo hace `ProvisionCleaningTaskUseCase._auto_assign` dentro del paso 4, porque PRD §11 auto-asigna
cuando el tenant tiene exactamente una limpiadora activa —y el dataset de §27 tiene exactamente
una— y `_fire_cleaner_assigned` dispara la transición él mismo. Medido contra la base de datos: al
cerrar la sección 5, REDES11 lleva cuatro filas de `property_state_transitions` y está en
`CLEANING_SCHEDULED`. Consecuencia para la tarea 6.1: el ciclo de la limpieza **empieza en
`accept`**, y lo que hace antes es comprobar que la asignación es la que se espera, fallando en voz
alta si no lo es. Llamar igualmente a `AssignCleaningTaskUseCase` se rechazó por lo que escribiría
de más —un segundo aviso de asignación y una segunda fila de auditoría por ejecución—, y sembrar
una segunda limpiadora para evitar el auto-asignado se rechazó por cambiar el dataset de §27 para
acomodar un paso del plan.

El paso 8 sale por `{READY_FOR_NEXT_GUEST, AWAITING_CHECKIN, VACANT_READY}` (`_POLICY:55`), resuelto
por `ContextualStateResolver`; cualquiera de los tres admite `CHECKIN_WINDOW_OPENED` o encadena
hasta él, así que el paso 9 no depende de cuál salga. **PAJARITOS8** no recibe ningún disparador: no
tiene estancias y su incidencia es `MEDIUM`, que `_severity_trigger` mapea a `None`
(`maintenance/application/use_cases.py:513-522`). Queda `VACANT_READY`.

**La permutación que se rechaza, y por qué se rechaza con nombre**: sembrar las incidencias antes que
las estancias deja REDES11 en `MAINTENANCE_REQUIRED` en el paso 1, y `(MAINTENANCE_REQUIRED,
CHECKIN_WINDOW_OPENED)` **no existe en `_POLICY`** → `InvalidStateTransitionError`, que
`_advance_one` traga como aviso. El dataset acabaría en el mismo estado final con **cinco
transiciones menos** y un timeline vacío: el fallo silencioso perfecto.

Rechazado: sembrar todo con `now` y dejar que el orden lo decida el código — es lo que produce esa
permutación por accidente.

### D3 — El reloj se reproduce pasando un `now` histórico, no adelantando el sistema

**Elegido:** cada llamada a `AdvancePropertyStatesUseCase.execute(...)` recibe el `now` del hecho que
representa, derivado de las mismas fechas ancladas al día del tenant que el seed ya calcula una sola
vez (`seed_demo.py:413`). `now` ya es un parámetro del caso de uso (`properties/application/
use_cases.py:130`) y de todos los de `cleaning` y `maintenance`, así que no hace falta ningún
mecanismo nuevo.

Es **obligatorio**, no una preferencia: con `now = hoy`, `CHECKIN_WINDOW_OPENED` de una estancia que
entró hace diez días levanta `IncompatibleTransitionContextError` (`state_machine.py:229`), y
`CHECKIN_TIME_REACHED` de la estancia pasada exige `utc_instant < utc_end` (`:231`), que hoy es
falso. Sin `now` histórico los pasos 2, 3 y 9 son inalcanzables.

Efecto secundario deseable: `property_state_transitions.created_at` y `timeline_events.created_at`
quedan fechados cuando el hecho ocurrió, así que el timeline de la demo se lee como una cronología y
no como un volcado instantáneo.

Rechazado: relajar la precondición de `CHECKIN_WINDOW_OPENED` — es política de la máquina de estados
y pertenece a `timeline-state-machine`, no a un seed. Rechazado: disparar sólo lo que hoy admite —
timeline truncado, que es justo lo que R4.4 quería evitar.

### D4 — La estancia DIRECT se confirma antes de nada, y eso es un hallazgo del sistema, no del seed

**Elegido:** el primer paso de la fase de avance lleva la reserva DIRECT de `PENDING` a `CONFIRMED`
con `UpdateReservationUseCase`.

Hoy esa estancia nace `PENDING` porque `CreateReservationCommand` no acepta `status` a propósito
(«*una reserva manual que ya está `CANCELLED` no es algo que crear en un paso*»,
`reservations/application/use_cases.py:52-54`), y las cuatro precondiciones de reloj exigen
`CONFIRMED` o `CHECKED_IN_ESTIMATED` (`state_machine.py:229-236`). **Consecuencia que conviene decir
en voz alta: la estancia DIRECT que el seed lleva sembrando desde el 2026-08-12 está en un estado que
el reloj no puede avanzar nunca.** No es un defecto de `seed-data-demo` —nada la avanzaba— pero sí es
la razón de que este paso exista, y va a la spec.

Rechazado: añadir `status` a `CreateReservationCommand` — cambiar el contrato de `POST /reservations`
por conveniencia de un seed. Rechazado: crear la DIRECT por el ingestor como las OTA — la spec viva
declara que cada una entra «por la vía que su canal permite» (`specs/seed-data-demo.md:145`).

### D5 — Un `ReportIncidentUseCase` nuevo en `maintenance`

**Elegido:** `maintenance` gana un caso de uso de alta genérico —`property_id`, `source`, `title`,
`description`, actor— que escribe la entidad, su `AuditLog` y su `TimelineEvent` en una
transacción, calcado de `ReportGuestIncidentUseCase` pero sin sus dos suposiciones.

**Enmienda del 2026-08-16, acordada en el gate del panel de la sección 2** (findings del revisor de
seguridad y del de tenancy, aceptadas por Jose). La firma original llevaba además
`reservation_id` y `reported_by_user_id` opcionales, y ninguno de los tres identificadores se
resolvía dentro del tenant. Eso deja sin cumplir una precondición que el puerto **declara**:
«*`property_id` and `reservation_id` must already have been resolved within `tenant_id`. The
foreign keys of `incidents` are global rather than composite with `tenant_id`, so the database
would accept an incident of tenant A anchored to a property of tenant B, and this port cannot
detect it*» (`maintenance/domain/repositories.py:216-223`), que el creador existente satisface
**estructuralmente** porque sus ids salen de la sesión que resolvió el token — y un caso de uso
abierto a cualquier llamante no tiene nada equivalente. Así que:

- el caso de uso recibe también un `PropertyRepository` y **resuelve `property_id` dentro del
  tenant**, rechazando con `MaintenanceValidationError` lo que no sea suyo — el mismo idioma que
  `AssignIncidentUseCase` ya usa para el técnico, y por el motivo que su comentario da;
- **desaparecen `reservation_id` y `reported_by_user_id`**: arrastraban la misma precondición sin
  cumplir y hoy no tienen ningún llamante. Quien traiga el primero —la alerta de cerradura de
  `messaging-ai`, previsiblemente— añade el parámetro junto con la búsqueda que lo hace seguro.

Se rechazó validar los tres con tres puertos nuevos (el caso de uso pasaría de 4 a 7
dependencias para defender a llamantes que no existen) y se rechazó enunciar la precondición
sólo en el docstring, que es dejar en la confianza justo lo que el panel señaló.

Hace falta porque el creador que existe **no puede** crear las incidencias de §27: fija
`source=GUEST` (`:153`), y `reservation_id` y `reporter_token_hash` son obligatorios (`:137-148`). La
incidencia 3 es `source: CLEANER` y ninguna de las tres cuelga de una reserva en §27.

Rechazado: componer `Incident(...)` + `IncidentRepository.add` desde el CLI. La regla de escritura del
seed lo permitiría («caso de uso, si no entidad y puerto», `specs/seed-data-demo.md:42-44`), pero
duplicaría el `AuditLog` y el `TimelineEvent` que el caso de uso encapsula — y la regla 9 de
`security.md` nombra `Incident` en su enumeración, así que la duplicación no es cosmética. Rechazado:
`POST /incidents` — `maintenance/api/incidents_router.py:11-15` explica por qué no existe y quién lo
traerá; un caso de uso no es una ruta.

**Consecuencia para `messaging-ai`**: ese change necesitará exactamente esta alta (el router lo dice).
Se diseña genérico para que la herede, no para el seed.

### D6 — Los textos de §27 son constantes versionadas, así que el seed no invoca la excepción 2 de la regla 11

**Elegido:** los seis literales (`title` y `description` de las tres incidencias) viven como
constantes del módulo, junto a `_CHECKLIST_ITEMS` y `SEED_PROPERTIES`.

`incidents.title`/`description` son sumideros de texto en claro y su excepción 2 concede «*la prosa
que escribió quien reporta… porque el valor no es nuestro y no lo hemos ido a buscar*», y dice
explícitamente que **no autoriza a un escritor nuestro** (`steering/security.md:146-155`). El seed es
un escritor nuestro. La salida no es pedir una excepción nueva: es no necesitarla, escribiendo
constantes del repositorio en vez de texto compuesto — el mismo movimiento con el que
`auth-account-recovery` escribe en `notification_logs.subject`/`body` sin usar la excepción 1
(`security.md:142`).

Rechazado: ampliar la excepción 2 al seed — concedería a cualquier escritor nuestro futuro lo que hoy
sólo tiene un anónimo, y a cambio de nada.

### D7 — La clasificación va sin actor, y la cuarta excepción de la regla 9 se amplía para nombrar al seed

**Elegido** (OQ1 resuelta en el gate del design, 2026-08-16): `ClassifyIncidentUseCase.execute(actor=None)`,
como el job, **y** una entrada nueva en `steering/security.md` que nombre al comando de seed junto al
job dentro de la cuarta excepción de la regla 9.

`execute` acepta `IncidentActor | None` (`:565-577`) y el actor decide dos cosas: el `TimelineEvent`
sale con actor `AI` si es `None` y con `USER` si no (`_record_timeline`, `:380-383`), y el `AuditLog`
va sin actor o con él. Con `actor=None` la demo enseña lo que la DoD §28.9 pide («*MockAIAdapter
clasifica automáticamente severity y category*») y el timeline no reclama a nadie que no estuvo. Con
un actor humano el timeline diría que la propietaria clasificó tres incidencias que no clasificó.

El problema era normativo: la cuarta excepción de la regla 9 concedía la fila sin actor «*sólo cuando
la ejecuta el job*» (`security.md:65-71`). `_AuditWriter` lo dejaría pasar por construcción —su
conjunto cerrado es por acción, no por ejecutor— así que era exactamente el caso en que el código
permite lo que la regla no concede.

**La ampliación, y por qué se pide por la puerta correcta.** No se pide por parecido con el job: se
pide por la propiedad que la excepción **ya declara como su fundamento** — «*no existe el actor*». El
seed lo cumple literalmente: es un comando de línea de órdenes, no hay persona detrás de la
clasificación y `actor_ip` no tiene petición de la que salir. Y hay precedente exacto en la **segunda
excepción de esta misma regla**, que aceptó ese argumento para un CLI: «*hoy el sync lo lanza una
persona por línea de comandos y el comando no tiene identidad que registrar*» (`security.md:55`).

Lo que la ampliación **no** concede, en la forma que la propia regla exige: sigue cubriendo sólo
`INCIDENT_CLASSIFIED`; una clasificación manual por `POST /incidents/{id}/classify` sigue llevando su
actor; y no dice nada sobre las otras once acciones del flujo ni sobre ningún otro comando — que un
ejecutor sea automático no lo exime, o cualquier CLI se auto-eximiría.

Rechazado: `actor = el TENANT_OWNER` — no toca ninguna regla y miente en el timeline, que es el
artefacto que la demo enseña. Rechazado: no clasificar y dejarlo al job de beat — reintroduce el
dataset inestable que el proposal descartó.

### D8 — Tres actores, cada uno donde su caso de uso lo exige

**Elegido:** la regla «el actor de todo lo que el seed escribe es el `TENANT_OWNER`»
(`specs/seed-data-demo.md:134-141`) se sustituye por «cada escritura lleva el actor que su caso de
uso exige», con el reparto declarado:

| Escritura | Actor | Por qué no puede ser otro |
|---|---|---|
| Todo lo que el seed ya escribe hoy | `TENANT_OWNER` | Sin cambio |
| `UpdateReservationUseCase` (D4, pasos 5 y 11) | `TENANT_OWNER` | `actor_user_id` es sólo para el timeline |
| `AdvancePropertyStatesUseCase` (pasos 2-4, 9-10) | `SYSTEM` | Es lo que hace el scheduler; ver D11 |
| Ciclo de la limpieza (pasos 6-8) | `SEED_CLEANER_EMAIL` | `accept`, `start`, `complete` y la subida exigen que el actor sea **el asignado** (`cleaning/domain/entities.py:200-218`) |
| Alta de incidencias (D5) | `TENANT_OWNER` | Es quien tiene el permiso |
| Clasificación | ninguno | D7 / OQ1 |
| `AssignIncidentUseCase` | `TENANT_OWNER` | Valida que el técnico exista, sea `TECHNICIAN` y esté `ACTIVE`; el actor sólo necesita el permiso |

No es una relajación: es que la regla anterior describía un comando que sólo escribía cosas que el
owner puede escribir. En cuanto el dataset incluye trabajo de campo, un actor único es imposible sin
saltarse invariantes de `cleaning`.

### D9 — Idempotencia: `(property_id, title)` para incidencias, estado terminal para la limpieza

**Elegido:** dos claves nuevas, al mismo nivel de disciplina que las cinco que ya existen
(`specs/seed-data-demo.md:196-213`):

- **Incidencias**: `(property_id, title)` con los títulos literales de §27. `Incident` no tiene
  `external_id`, y el par es estable frente al día de ejecución — que es la propiedad que el resto de
  claves del comando protegen. Si las tres ya existen, la fase de incidencias no hace nada.
- **Limpieza y fotos**: «la `CleaningTask` de la estancia pasada ya está `COMPLETED`». Una sola
  comprobación cubre la tarea, los 18 ítems y las 6 fotos, y es lo que impide que una segunda
  ejecución deje seis objetos huérfanos en el bucket (R3.5).

  **Enmienda del 2026-08-16** (panel de la sección 7, DESIGN-CONFLICT del arquitecto, resuelto por
  Jose): esta clave sólo contemplaba la tarea que **existe**, y hay un caso que no cubría — que no
  haya ninguna. Se resuelve **distinguiendo dos situaciones, y no metiéndolas en el mismo saco**,
  con el dato que el propio disparador de checkout ya devuelve (`AdvanceReport`):

  - si el checkout **acaba de aprovisionar** una tarea y luego no se encuentra, es una anomalía y
    el comando **falla en voz alta** con exit 1 — un dataset que nadie puede explicar;
  - si **no aprovisionó ninguna** —porque la propiedad ni siquiera fue candidata (una re-siembra
    sobre un dataset ya avanzado, o uno cuya estancia pasada alguien borró a mano) o porque el
    tenant no crea limpiezas (`auto_create_cleaning_task` apagado, sin plantilla de checklist)—,
    la fase no hace nada y el comando sigue. Eso es configuración del tenant, y refusarla sería
    que el seed decida algo que no le toca; `ProvisionCleaningTaskUseCase` lo dice de sí mismo:
    «returns `None` for every ordinary reason not to create one and lets the caller count it».
    La señal para el operador son los recuentos: `0 cleaning_tasks, 0 cleaning_photos`.

  Consecuencia para R3.4, que se enmienda con la misma frase: la limpieza cerrada es lo que el
  comando garantiza **cuando el tenant crea limpiezas**, que es el caso de cualquier tenant recién
  bootstrapeado y el de `dev`.
- **Estados**: cada disparador es idempotente por construcción. `AdvancePropertyStatesUseCase`
  selecciona candidatas por estado de origen (`list_by_state`, `:133-135`) y `NoOperationalStateChangeError`
  se traga como «ya estaba ahí» (`:212-213`); `UpdateReservationUseCase` con el valor ya almacenado
  «no escribe nada y no registra nada» (`:258-263`).

Rechazado: una tabla de marcas del seed — inventa estado propio para responder algo que el dataset ya
responde.

### D10 — Las fotos son bytes constantes del módulo, y el fail-fast de `S3` sube a las precondiciones

**Elegido:** seis constantes `bytes` con una imagen JPEG mínima válida, un `ChunkedUpload` de
implementación trivial sobre ellas (el `Protocol` sólo pide `read(size)`), y una precondición nueva
**junto a la de la zona horaria** —dentro de `apply_plan`, tras resolver el tenant y antes de la
primera escritura, porque hay que leer `tenant_configs` y `build_plan` no toca la base de datos, la
misma corrección que la tarea 1.1 hace para R6.1—: si el `storage_type` del tenant es `S3` y falta
`s3_bucket`, `s3_region` o la
credencial que la cadena de boto3 resuelve, aborta con **exit 1** y frase accionable, antes de abrir
la transacción.

**Dos enmiendas del 2026-08-16, del panel de la sección 4** (la primera acordada con Jose):

1. **`s3_endpoint_url` sale de la lista.** Un endpoint vacío es la configuración correcta para AWS
   —«*turning it into `None` is what makes "point at AWS" mean configure nothing*»,
   `cleaning/api/dependencies.py`—, así que exigirlo rechazaría un despliegue que el resto del
   sistema sirve. Razonamiento completo en la enmienda de R3.3.
2. **La pregunta por las credenciales la responde el paquete de almacenamiento**, no el CLI:
   `credentials_are_resolvable()` vive junto a `build_s3_client` en
   `integrations/infrastructure/storage/s3.py`, que es el único módulo que habla con el SDK
   (`steering/architecture.md`: «Todo sistema externo detrás de adapter … El core nunca se acopla a
   un proveedor»). La primera versión importaba `boto3` en `app/cli/seed_demo.py`, que es un segundo
   punto de acoplamiento al proveedor y además hacía que la suite resolviera la cadena de
   credenciales de la máquina; los tests la sustituyen por esa función.

El fail-fast sube porque `storage_for(S3)` levanta `StorageWriteError` y **nunca** cae a `LOCAL`
(`integrations/infrastructure/storage/__init__.py:74-82`): sin esta comprobación, un `dev` a medio
configurar rompería a mitad de la siembra y saldría por el catch-all con exit 2 y «details withheld»
— el mismo defecto que R6.1 arregla para la zona horaria. Coherente con D11 de `seed-data-demo`, que
es donde vive el contrato de configuración.

Rechazado: fotos con contenido real — material de marketing (fuera de alcance del proposal).
Rechazado: saltar las fotos cuando el tenant está en `S3` — la plantilla del propio seed marca las
seis como `required: True` (`seed_demo.py:501-504`), así que sin ellas la limpieza no cierra y en
`dev` no habría nada que enseñar.

### D11 — La transacción sigue siendo una, y las fotos son la única escritura física fuera de ella

**Elegido:** todo lo nuevo se compone con `CallerOwnedUnitOfWork()` y cae bajo el único
`uow.commit()` de `:465`. `AdvancePropertyStatesUseCase` y los de `cleaning`/`maintenance` llaman a
`commit()` sobre el uow que se les inyecte, así que el patrón de `_seed_checklist_template` vale tal
cual.

**La excepción es física y no se puede cerrar aquí**: `UploadCleaningPhotoUseCase` escribe el objeto
en el almacenamiento y sólo lo borra compensatoriamente si **su propio** `commit()` falla
(`cleaning/application/use_cases.py:1425-1436`); bajo `CallerOwnedUnitOfWork` ese commit no ocurre,
así que un fallo posterior revierte las seis filas y deja los seis objetos. El diseño no lo esconde:
la fase de avance recuerda las claves subidas y, al capturar un fallo, **las enumera en la salida**
antes de propagar (R4.6). Enumerar no es limpiar, y esa distinción es la que hace honesta la salida.

**Por qué enumerar claves no choca con la regla 5 de `steering/security.md`** (lo pidió por escrito
el panel de seguridad de la sección 6, y se escribe aquí para que nadie tenga que volver a
derivarlo): la prohibición de exponer rutas internas se acota a sí misma a la **superficie de
respuesta** —«cuerpo de la respuesta, cabeceras, cualquier otro campo»— y dice de sí misma que **no
alcanza a los logs**. Un comando de línea de órdenes no tiene respuesta; su `stderr` es el canal de
diagnóstico del operador, que ya tiene la base de datos y el entorno delante. No se invoca la
excepción nombrada de la URL prefirmada, que es de otra cosa. Y lo que se imprime son sólo
identificadores que generó el propio sistema (`tenants/{tenant_id}/cleaning-tasks/{task_id}/
{photo_id}.{ext}`): ningún nombre de fichero, ningún dato de negocio.

**Y va impreso desde `apply_plan`, no desde `main()`**, que es donde el módulo imprime todo lo
demás: el catch-all de `main()` es una frontera de seguridad que se queda con la clase de la
excepción y nada más, así que una enumeración que esperase a llegar allí sería descartada por ella.

Rechazado: subir las fotos en una transacción propia previa — deja un estado «fotos sin tarea» que es
peor. Rechazado: borrar los objetos nosotros en el `except` — un borrado que también puede fallar,
dentro de un camino de error, y `apply_plan` no tiene dónde reportarlo mejor que la enumeración.

### D12 — El contrato de consola crece en tres recuentos, y ninguno más

**Elegido:** `apply_plan` devuelve y `main()` imprime ocho claves: las cinco de hoy más `incidents`,
`cleaning_tasks` y `cleaning_photos`. Nada de estados ni de transiciones: la spec dice «un recuento
por entidad y nada más» (`:238`), y un estado operacional no es una entidad creada.

`_CONSOLE_COUNTS` y el test que pinea la forma del diccionario
(`tests/cli/test_seed_demo.py:474-535`) se amplían con las tres claves; los dos tests de «todo a
cero» siguen valiendo con ocho.

Rechazado: imprimir el estado final de cada propiedad — útil para depurar y ruido en el contrato;
quien lo quiera lo consulta.

### D13 — Los tres barridos, cada uno donde ya vive su contrato

- **R6.1** (zona horaria): la comprobación sube a la **fase de precondiciones de `apply_plan`** —tras
  resolver el `TenantModel` y antes de `bind_session_to_tenant`, es decir antes de la primera
  escritura— y suma su condición a las de exit 1 de D11. Hoy `ZoneInfo(tenant.timezone)` se evalúa
  ya avanzado `apply_plan` y sale por el catch-all de `main()` con la clase de la excepción y
  «details withheld».

  **Enmendado el 2026-08-17** (panel de `/sdd:review`): la redacción original decía «va a
  `build_plan`», y ahí no puede ir. `build_plan()` **no lee la base de datos** —resuelve el tenant
  `apply_plan`—, así que una comprobación sobre `tenants.timezone` no tiene dónde leer el valor
  desde allí. Es la misma ubicación y la misma razón que D10 da para el fail-fast de `S3`, que
  también necesita `tenant_configs`. El código está bien; lo que estaba obsoleto era esta frase.
- **R6.2** (docstring): dos frases en `integrations/application/ingest.py:1-9` — «All three ingest
  routes … the PMS sync, the CSV import and the demo seed» y «the ONLY difference between the three
  routes». Sin cambio de comportamiento.
- **R6.3** (rama sin test): un test con `ingest` monkeypatcheado devolviendo `skipped=1, errors=()`,
  junto a `test_an_ingest_failure_reaches_the_console_with_its_reasons` (`:205-231`).

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| CLI | `backend/app/cli/seed_demo.py` | Fase de avance tras `apply_plan`; constantes de §27 (textos, fotos); validación de zona horaria y de `S3` en `build_plan`; tres claves de recuento; enumeración de objetos huérfanos al fallar |
| Mantenimiento | `backend/app/maintenance/application/use_cases.py` | **Nuevo** `ReportIncidentUseCase` (D5) |
| Integraciones | `backend/app/integrations/application/ingest.py` | Docstring: dos → tres rutas (D13) |
| Tests | `backend/tests/cli/test_seed_demo.py` | Enmienda de `test_none_of_the_three_is_given_a_status_by_hand` (`:818-848`) y `test_both_properties_are_born_vacant_ready` (`:707-720`); `_CONSOLE_COUNTS` a ocho; secciones nuevas de incidencias, avance de estados y limpieza; el barrido de aislamiento (`:581-673`) crece a `incidents`, `cleaning_tasks` y `cleaning_photos` **sobre sesión sin marcar** |
| Tests | `backend/tests/maintenance/` | Tests del `ReportIncidentUseCase` nuevo |
| Tests | `backend/tests/integrations/` | Test de la rama de `SeedIngestError` sin motivos (D13) |
| Steering | `sdd/steering/security.md` | Ampliación de la **cuarta excepción de la regla 9** para nombrar al comando de seed junto al job (D7 / OQ1). Una entrada, con sus tres «lo que NO concede» |
| Docs | `docs/seed-data-demo.md` (o el que la capacidad tenga), `.env.example` | Sin variables nuevas; sí la nota de que `make seed-demo` depende de red cuando el tenant está en `S3` |

## Data & interfaces

**Esquema: ninguna migración.** Todas las tablas existen (`incidents`, `cleaning_tasks`,
`cleaning_photos`, `property_state_transitions`, `timeline_events`, `audit_logs`) y ninguna columna
cambia.

**Variables de entorno: ninguna nueva.** `S3_BUCKET`/`S3_REGION`/`S3_ENDPOINT_URL` y las credenciales
de boto3 ya existen desde `object-storage-provisioning`; lo que cambia es **cuándo** se exigen (D10).

**Interfaz nueva, una:** `ReportIncidentUseCase` en `maintenance/application/use_cases.py`. Forma
prevista, calcada de su vecino:

```python
class ReportIncidentUseCase:
    def __init__(self, *, incidents: IncidentRepository, properties: PropertyRepository,
                 audit: AuditLogRepository, timeline: TimelineEventRepository,
                 uow: UnitOfWork) -> None: ...

    async def execute(self, *, tenant_id: uuid.UUID, property_id: uuid.UUID,
                      source: IncidentSource, title: str, description: str,
                      actor: IncidentActor, now: datetime) -> Incident: ...
```

(Enmendada el 2026-08-16; el porqué de las cinco dependencias y de los dos parámetros que ya no
están, en D5.)

**Contrato de consola** (D12): ocho recuentos, `users`, `properties`, `guests`, `reservations`,
`checklist_templates`, `incidents`, `cleaning_tasks`, `cleaning_photos`.

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| **`make seed-demo` gana dependencia de red** cuando el tenant está en `S3`. Es un cambio real de la naturaleza del comando | Aceptado en el proposal (decisión 3). Fail-fast en `build_plan` con exit 1 y frase accionable (D10); en `LOCAL` —local y cualquier tenant nuevo— no cambia nada |
| **Objetos huérfanos en el bucket** si la transacción falla tras subir fotos, o si alguien borra la tarea a mano y re-siembra | Enumeración en la salida (D11). Limpiar el bucket queda fuera de alcance, declarado en el proposal |
| **La suite rompe en tres puntos conocidos** | Son enmiendas, no daños colaterales: los dos tests pinean comportamiento que este change cambia a propósito, y el tercero es el contrato de consola. Van nombrados en las tareas |
| **El orden de D2 se rompe en una refactorización** y nadie se entera: el fallo es silencioso (`InvalidStateTransitionError` se traga como aviso) | Un test que afirma la **secuencia completa** de `property_state_transitions` de REDES11 (siete filas, en orden, con sus `from_state`/`to_state`), no sólo el estado final. Es la única forma de que la permutación mala falle en rojo |
| **`ContextualStateResolver` elige un destino distinto** en el paso 8 según lo que vea | Los tres destinos posibles encadenan hasta `AWAITING_CHECKIN` en el paso 9. El test de secuencia acepta el conjunto, no un valor |
| **REDES11 acaba en `MAINTENANCE_REQUIRED`** y la demo abre con la vivienda «no reservable» | No hay alternativa que no contradiga §27: la incidencia 2 es `HIGH` y `INCIDENT_HIGH` va a `MAINTENANCE_REQUIRED` desde los seis estados que lo admiten. Ver OQ2 |
| **Deriva con el clasificador**: si alguien cambia las keywords, el dataset deja de ser el de §27 | R1.3 aborta con exit 1 nombrando la incidencia y ambos valores. El seed no se adapta en silencio |
| **Tiempo de ejecución**: el comando pasa de ~5 escrituras compuestas a ~40 (18 ítems + 6 fotos + 7 disparadores + 3 incidencias + clasificaciones) | Todo en una transacción sobre una sesión ya abierta; los 18 ítems son el grueso. Si molesta, es material de optimización posterior, no de diseño |

## Open questions

**Las tres se resolvieron en el gate del design (2026-08-16).** Se conservan enunciadas porque la
pregunta explica la decisión mejor que la decisión sola, y porque las tres tocan cosas que ningún
test hará evidentes después.

### OQ1 — RESUELTA: ampliar la excepción nombrando al seed

**Decisión: (a).** `actor=None` al clasificar, y `steering/security.md` gana una entrada en la cuarta
excepción de la regla 9 que nombra al comando de seed junto al job. Razonamiento y límites, en D7.
La tarea que escribe esa entrada es parte de este change: **la aprobación en un design no es lo que
amplía la regla — lo es la línea en el steering**, que es literalmente lo que esa misma excepción
dice de sí misma (`security.md:65-66`).

<details>
<summary>El enunciado original</summary>

#### La cuarta excepción de la regla 9 dice «el job»; el seed no es el job

D7 elige `actor=None` para clasificar, que es lo que hace que el timeline de la demo enseñe a la IA
clasificando en vez de a la propietaria. Pero `security.md:65-71` concede la fila de `AuditLog` sin
actor «*sólo cuando la ejecuta el job*», y añade que «*una clasificación manual… lleva su actor como
cualquier otra operación*». El seed no es ninguna de las dos cosas, y `_AuditWriter` no lo distingue
—su conjunto cerrado es por acción— así que el código lo permitiría sin que nada fallase.

La ampliación que pediría, si se aprueba, es de una frase: nombrar al comando de seed junto al job,
con la justificación que la excepción **ya usa** («no existe el actor») reforzada por la segunda
excepción de la misma regla, que ya aceptó exactamente este argumento para un CLI: «*hoy el sync lo
lanza una persona por línea de comandos y el comando no tiene identidad que registrar*»
(`security.md:55`).

Las opciones eran: (a) ampliar la excepción nombrando al seed; (b) clasificar con el `TENANT_OWNER`
como actor y aceptar que el timeline de la demo atribuya a una persona lo que hizo el clasificador;
(c) no clasificar en el seed y dejar que el job de beat lo haga — que reintroduce el dataset
inestable que el proposal descartó.

</details>

### OQ2 — RESUELTA: se acepta `MAINTENANCE_REQUIRED`

**Decisión: (a).** REDES11 abre en `MAINTENANCE_REQUIRED` y no se toca §27. El recorrido completo
—ventana de check-in, ocupada, mantenimiento requerido— **sí queda en el timeline**, que es donde la
demo lo cuenta; el estado operacional es la foto final, no la historia. Consecuencia que la
documentación de la capacidad debe decir con todas las letras, para que nadie lo lea como un defecto
del seed: la demo abre con una vivienda ocupada y no reservable, y eso es correcto.

<details>
<summary>El enunciado original</summary>

#### ¿Es `MAINTENANCE_REQUIRED` el estado con el que queremos que abra la demo?

Con §27 tal cual, REDES11 termina en `MAINTENANCE_REQUIRED`: hay un huésped dentro, una incidencia
`ACCESS`/`HIGH` («huésped bloqueado en la entrada») y un técnico asignado. Es coherente y
probablemente el estado más interesante que la demo puede enseñar — pero **tapa** `OCCUPIED_ESTIMATED`,
que es el estado que §27 pide para la estancia y que el dashboard usa para responder «¿qué pasa?».

No es una elección de diseño: es una consecuencia de la máquina de estados, y la única palanca sería
contradecir §27 bajando la severidad de la incidencia 2. Se plantea porque **es visible para el
producto** y quien decide qué enseña la demo no es el design.

Las opciones eran: (a) aceptarlo tal cual; (b) mover la incidencia 2 a PAJARITOS8, que la deja
`MAINTENANCE_REQUIRED` a ella y a REDES11 ocupada — pero §27 la sitúa en REDES11 explícitamente; (c)
resolver la incidencia 2 al final de la siembra, que devuelve REDES11 a un estado contextual por
`INCIDENT_RESOLVED` — pero entonces su `status` final no es el `ASSIGNED` que §27 pide.

</details>

### OQ3 — RESUELTA: el hueco se nombra y se deja donde está

**Decisión: (a).** Este change no cierra ni ensancha el hueco del `AuditLog` de las transiciones con
actor `USER`: usa los mismos casos de uso que la API ya usa. Cerrarlo en un solo módulo dejaría el
rastro **inconsistente sin hacerlo completo**, porque el hueco es idéntico en `properties`,
`cleaning` y `maintenance`, y `properties` lo decidió al revés con un test que lo dice por su nombre.

Se deja sin abrir entrada de roadmap: el hueco ya está documentado en el sitio donde alguien que lo
toque lo va a leer (`maintenance/application/use_cases.py:497-507`) y registrado en el `proposal.md`
de `maintenance`. Una entrada más no añadiría información, sólo un sitio más que mantener.

<details>
<summary>El enunciado original</summary>

#### El `AuditLog` de las transiciones de estado con actor `USER`

La regla 9 exime del `AuditLog` a una transición de propiedad **sólo** con actor `SYSTEM`. D8 hace
que el seed dispare sus transiciones de reloj como `SYSTEM` —que es lo que hace el scheduler—, así
que queda dentro de la exención. Pero las transiciones que dispara **la clasificación** y **el ciclo
de limpieza** pasan por `_fire_trigger`, que las marca `USER` cuando hay actor
(`maintenance/application/use_cases.py:452-458`).

Eso ya es un hueco conocido y **documentado en el código como pregunta abierta, no como decisión**
(`:497-507`): `properties` decidió lo contrario para todos los actores, con un test que lo dice por
su nombre, y el mixin de `cleaning` tiene el hueco idéntico. Este change **no lo cierra ni lo
ensancha**: usa los mismos casos de uso que la API ya usa.

Cerrarlo tocaría `properties`, `cleaning` y `maintenance` a la vez.

</details>
