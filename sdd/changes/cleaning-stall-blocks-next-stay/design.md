# Design: cleaning-stall-blocks-next-stay

## Context

Las tres piezas que el proposal describe viven en cuatro ficheros y ninguno de ellos hay que
reescribir:

- **La matriz** es `PropertyStateMachine._POLICY` en `backend/app/properties/domain/state_machine.py`,
  con dos ayudas ya construidas que este change reutiliza tal cual: `source_states_for(trigger)`
  (deriva los estados origen de la matriz, sin segunda copia) y `_validate_trigger_preconditions`
  (decide si «la hora ha llegado», por separado de si la transición es legal).
- **La resolución contextual** es `ContextualStateResolver` en
  `backend/app/properties/domain/state_resolution.py`. Tiene **dos** resolvedores y la asimetría
  entre ellos es la clave de todo el change: `after_cleaning_completion` se **niega** con una
  estancia activa, mientras `_contextual_reservation_cleaning` —el que usa `INCIDENT_RESOLVED`—
  sí la resuelve, y devuelve `OCCUPIED_ESTIMATED`. Es decir: el sistema ya sabe calcular el
  estado correcto de REDES11; lo que no tiene es un disparador que lo pida.
- **El job** es `AdvancePropertyStatesUseCase` en
  `backend/app/properties/application/use_cases.py`, con su `AdvanceReport` por cubos, invocado
  por los tres `_clock_task` de `backend/app/scheduler/tasks.py`. Su consulta de candidatas
  (`list_by_state(tenant_id, source_states_for(trigger))`) es exactamente lo que hace invisible
  a la vivienda atascada.
- **El ciclo de la tarea** es `backend/app/cleaning/application/use_cases.py`, cuyo
  `_TaskTransitionMixin._transition` es el único camino por el que una operación de limpieza
  mueve el estado de la vivienda, y `RejectCleaningTaskUseCase` es la plantilla exacta de la
  operación que R3 pide: entidad a estado terminal → transición por la máquina → `AuditLog` →
  un solo `commit`.

Dos hechos del esquema que simplifican el alcance: `CleaningTaskStatus.CANCELLED` **ya existe en
el tipo `cleaning_task_status` de Postgres** (`alembic/versions/a1a72da30f8e_domain_foundation_ops.py:87`)
y `PropertyStateTrigger` **no es columna de ninguna tabla** — se serializa como texto dentro del
JSON de `property_state_transitions.metadata` y de `timeline_events.metadata`, y nada lo vuelve a
leer como enum. Por eso este change **no lleva migración**, ni para estrenar el estado terminal de
R3 ni para retirar el trigger de R4.

Diagrama del nudo y de la salida:
[`docs/diagrams/2026-08-23_autohost-limpieza-atascada.png`](../../../docs/diagrams/2026-08-23_autohost-limpieza-atascada.png).

## Decisions

### D1 — La detección de R1 es una función pura de `properties/domain/`, con dos consumidores

**Chosen:** un módulo nuevo `backend/app/properties/domain/stalls.py` con un value object
`BlockedTransition(property_id, reservation_id, trigger, blocking_state, due_since)` y una función
`detect(property, reservations, now, checkin_window, applied) -> tuple[BlockedTransition, ...]`.
La llaman dos sitios: el job (R1, filtrando por su trigger) y el caso de uso de lectura de R2 (los
tres triggers). Una sola definición de «desajuste» para el recuento y para la pantalla; si
divergieran, el informe y el aviso contarían cosas distintas y nadie lo notaría.

**`applied` es la tercera condición, y sin ella la definición estaba mal** (enmienda del panel de
la sección 3, 2026-08-23, decidida por Jose; R1.1 del proposal queda enmendado en el mismo
commit). Es el conjunto de pares `(reservation_id, trigger)` que **ya constan aplicados** en
`property_state_transitions`, y el desajuste pasa a ser:

```
is_due(reserva, trigger)
  and estado not in source_states_for(trigger)
  and estado not in destination_states_for(trigger)
  and (reserva.id, trigger) not in applied
```

**La tercera condición se añadió en la verificación 7.5, corriendo el flujo real contra el stack**
—y es la única de las cuatro que ninguna prueba unitaria habría encontrado—. Cancelar la limpieza
deja la vivienda en `OCCUPIED_ESTIMATED`, que es exactamente donde `CHECKIN_TIME_REACHED` la
llevaba, pero escribe una transición `CLEANING_CANCELLED` cuyo `source_entity_id` es **la tarea** y
sin `reservation_id`. Así que `applied` no la ve, y con sólo las otras tres condiciones la
colección seguía listando la vivienda que se acababa de arreglar: R2.4 —«deja de mostrarlo sin
intervención manual»— incumplido en producción con la suite en verde.

Por qué la suite no lo vio: los tests simulaban la resolución escribiendo a mano una fila de
transición **con** `reservation_id`, que es algo que el escritor real no escribe nunca. El fixture
y el escritor real guardaban cosas distintas, que es el modo de fallo que ya tiene nombre en este
proyecto. Los tests están corregidos para escribir lo que escribe la cancelación y nada más.

Estar **en el destino** significa que la exigencia del calendario está satisfecha, llegara la
vivienda como llegara, y eso es lo que R2.4 pide. `destination_states_for` se deriva de `_POLICY`
igual que `source_states_for`, y los tres triggers de reloj tienen **un** destino cada uno, fijado
por `test_every_clock_trigger_has_exactly_one_destination` para que el día que alguno gane un
segundo destino alguien tenga que decidir qué significa el atajo en vez de que se degrade solo.

**Y va acotada a la reserva, no al trigger** (decidido por Jose tras el panel de la sección 7, que
lo encontró y lo reprodujo). La primera versión ponía la condición **antes** del bucle de reservas,
y eso enmascaraba un atasco real: con dos estancias solapadas, si a A se le aplicó el check-in la
vivienda queda en `OCCUPIED_ESTIMATED`, y el atajo saltaba el trigger entero, así que B —cuyo
check-in nunca ocurrió— desaparecía del cubo `blocked` y de la colección. El bug que este change
existe para cerrar, reintroducido para el caso solapado, que D8 llama «un estado real, no una
hipótesis».

La razón de fondo: `current_operational_state` es **una** columna, así que «está en el destino» es
un hecho de la **vivienda**, mientras que un atasco es un hecho del par `(reserva, trigger)`. Con
una sola estancia vencida para ese trigger no hay ambigüedad —y ése es el caso de la cancelación
que motivó la condición—; con dos o más la columna no puede decir a cuál se refiere, así que el
atajo se abstiene y cada estancia se juzga por su propia evidencia. Lo fija
`test_the_destination_shortcut_does_not_mask_a_second_stalled_stay`, y se comprobó por medición
que la versión izada devolvía `[]` donde la acotada devuelve B.

Las dos primeras condiciones no describen un atasco: describen **todo lo que está aguas abajo
del trigger**. `is_due` de `CHECKIN_TIME_REACHED` es verdad durante toda la estancia y el de
`CHECKOUT_TIME_REACHED` para siempre después del checkout —contestan «¿llegó ese instante?», no
«¿está esta vivienda esperándolo?»—, y el complemento de los estados origen contiene todos los
estados que una vivienda ocupa *después* de hacer bien esa misma transición. Medido sobre la
implementación literal de la sección 3: `OCCUPIED_ESTIMATED` a mitad de estancia y
`AWAITING_CLEANING` recién salida de un checkout se reportaban las dos como atascadas, así que
`blocked` era el tamaño de la cartera activa y REDES11 no se distinguía de una vivienda sana.

**La evidencia no hay que inventarla**: `property_state_transitions.metadata` ya guarda
`reservation_id` y `trigger` —los escribe `PropertyStateMachine.evaluate`—, así que «¿se aplicó
ya el check-in de *esta* reserva?» se contesta con una lectura. `detect` **sigue siendo puro**:
recibe `applied` como parámetro y no consulta nada; quien lee es el llamante, que ya está en
`application/`. El trigger viaja en ese conjunto como **el texto guardado**, no como enum,
para no reintroducir el camino de lectura que la retirada de D10 depende de que no exista
(`test_no_read_path_rebuilds_a_trigger_from_stored_data`).

Rejected: **una lista de estados bloqueantes por trigger** —enumerar a mano, para cada trigger,
los estados que de verdad lo impiden. Es barata y sin I/O, pero es una segunda copia a mano del
conocimiento de la matriz, exactamente lo que el docstring de `source_states_for` dice que
deriva en silencio; y sigue sin poder distinguir «nunca avanzó» de «avanzó y volvió a esta
fase». · Rejected: **comparar contra el estado que el resolvedor contextual calcularía** — no
detecta REDES11, porque `_contextual_reservation_cleaning` cuenta las tareas vivas primero y
para esa vivienda contesta `CLEANING_IN_PROGRESS`, que es justo donde está atascada.

Rejected: detectarlo dentro de `AdvancePropertyStatesUseCase` y que R2 lo recalcule a su manera —
dos copias de la misma política, el fallo que `clock_triggers.py` ya documenta haber cometido una
vez. · Rejected: un servicio en `application/` — es política pura sin I/O, y `test_layering.py`
premia que viva en `domain/`.

### D2 — Quien decide si la hora ha llegado sigue siendo la máquina: `PropertyStateMachine.is_due`

**Chosen:** un classmethod nuevo `is_due(request) -> bool` que corre `_validate_request` y
`_validate_trigger_preconditions` y devuelve `False` ante `IncompatibleTransitionContextError`,
**sin consultar `_POLICY`**. El desajuste es entonces `is_due(...) and state not in
source_states_for(trigger)` — dos preguntas a la máquina, cero comparaciones de horas propias.
Hace falta porque `evaluate()` mira la matriz **antes** que las precondiciones, así que para un
estado que no es origen contesta `InvalidStateTransitionError` y nunca llega a decir si vencía.

**Enmendado durante `/sdd:run` el 2026-08-23 (panel de la sección 2): la fórmula de dos
preguntas es completa para dos de los tres triggers, y `CHECKIN_WINDOW_OPENED` lleva una
tercera condición.** `detect` le aplica además `clock_triggers.opens_checkin_window`. No es
la comparación propia que este mismo decision rechaza abajo —delega en el helper que ya
existe y ya está probado, el mismo que `AdvancePropertyStatesUseCase` aplica a sus
candidatas— sino precisamente lo que D1 exige: la máquina acepta *cualquier* instante del
**día** de check-in, mientras el job estrecha eso a la última `checkin_window` antes de la
hora. Sin la pinza, `detect` cantaría un atasco horas antes de que el job hubiera intentado
nada, y «una sola definición de desajuste para el recuento y para la pantalla» se rompería
por el otro lado — el informe y la colección volverían a contar cosas distintas.

Se escribe aquí porque el texto original presentaba `is_due(...) and state not in
source_states_for(trigger)` como la definición canónica y cerrada, y con la pinza dentro de
un comentario de `stalls.py` la contradecía sin que nada lo delatase. Los otros dos triggers
—`CHECKIN_TIME_REACHED` y `CHECKOUT_TIME_REACHED`— siguen siendo exactamente dos preguntas.
Lo cubre `test_the_operator_window_gates_the_checkin_window_trigger`, en sus dos lados.

Rejected: reordenar `evaluate()` para validar precondiciones antes de la matriz — cambia la
precedencia de errores de todos los llamantes vivos a cambio de nada. · Rejected: que `stalls.py`
compare `now >= start` por su cuenta — es literalmente el error que el docstring de
`clock_triggers.py` describe («los dos coincidían aquel día y nada los mantenía en sync»).

**Y el orden dentro de `detect` es una garantía de aislamiento, no una preferencia** (hallazgo
del panel de la sección 2). `is_due` va **primero**, porque es quien corre `_validate_request`
y por tanto quien levanta `TransitionScopeMismatchError`; `effective_bounds` no comprueba
ámbito ninguno. Con `effective_bounds` delante —como estaba— una reserva de otro tenant que
*además* tuviera una hora local irresoluble levantaba `IncompatibleTransitionContextError`
desde la aritmética de fechas y se descartaba como dato malo corriente, sin llegar nunca a la
comprobación de ámbito: la guarda sólo era real para las reservas ajenas cuyas fechas
resolvían. Lo fija `test_an_unresolvable_date_cannot_shadow_a_scope_violation`.

### D3 — El cubo nuevo se llama `blocked` y vive **fuera** de `candidates`

**Chosen:** `AdvanceReport` gana `blocked: int`, contando el desajuste **tal como D1 lo define
tras su enmienda** — con la tercera condición incluida, porque sin ella este cubo contaba la
cartera activa. Una vivienda con desajuste incrementa `blocked` y
ningún otro cubo; `candidates` conserva su significado exacto de hoy (viviendas en un estado
origen del trigger), porque una vivienda atascada **no es** candidata y meterla ahí rompería la
precedencia documentada del propio dataclass. Cumple R1.2 por construcción: `not_eligible` sigue
significando «la hora no ha llegado».

Rejected: reutilizar `not_eligible` — es exactamente la confusión que el proposal señala. ·
Rejected: un cubo `stalled` — «blocked» nombra la causa (el estado bloquea la transición) y no una
duración.

### D4 — Cada desajuste deja además una línea de log estructurada, y la ventana es la que ya hay

**Chosen:** `logger.warning("scheduler.blocked_transition", extra={tenant_id, property_id,
reservation_id, trigger, blocking_state, due_since})`, una por desajuste, con la misma forma que
`scheduler.unresolvable_reservation_time` y `scheduler.ambiguous_due_reservation`. Es lo que
satisface «identificando la vivienda, la reserva, el trigger y el estado que lo impide» (R1.1) en
el lado del job; la parte consultable por una persona es D5.

La ventana de detección es **la misma `candidate_window`** de `clock_triggers.py` (30 días atrás,
2 adelante), sin constante nueva: la consulta de reservas es la misma y un segundo horizonte
paralelo sería otra cosa que mantener en sync (R1.4). Se declara en `docs/celery-jobs.md` junto al
que ya está declarado, y con la consecuencia dicha en voz alta: **un atasco de más de 30 días deja
de aparecer**, que es el precio del límite y no un descuido.

Rejected: una ventana propia más ancha para la detección — invita a que el job vea un desajuste
sobre una reserva que su propia consulta de candidatas no habría cargado nunca.

### D5 — R2 se resuelve con una colección propia, derivada en lectura y sin nada persistido

**Chosen:** `GET /api/v1/blocked-transitions`, servida por un `ListBlockedTransitionsUseCase` nuevo
en `properties/application/use_cases.py` que corre `detect` sobre los tres triggers. **Nada se
guarda**: el desajuste se calcula en cada petición a partir del estado y de las reservas, así que
R2.4 («deja de mostrarlo sin intervención manual») sale gratis y no hay ciclo de vida que cerrar —
ni fila que quede abierta cuando el atasco se resuelve por el camino normal.

La paginación es del **resultado, no de la fuente**: se detecta sobre todas las viviendas del
tenant (`PropertyRepository.list_all`, que ya existe y ya usan el job y el seeder) y se pagina la
lista de desajustes, con el sobre de PRD §23. Paginar la fuente reproduciría el bug: una vivienda
atascada en la página 3 volvería a ser invisible. `total` es entonces el número que el operador
quiere: cuántos atascos hay.

**La lectura no escribe, y hubo que añadir un método para que fuera verdad** (panel de la
sección 4, 2026-08-23: lo encontraron el arquitecto y seguridad por separado). El acceso obvio a
la ventana de check-in es `TenantConfigRepository.get_or_create`, y ese **inserta** la fila de
configuración cuando el tenant no la tiene todavía: un `GET` acababa haciendo un `INSERT`, por una
ruta que alcanza un rol sin `MANAGE_TENANT_SETTINGS`. Hoy no sobrevivía porque nada commitea en
esa cadena —una seguridad que deja de ser cierta en silencio—. Se añade
`TenantConfigRepository.checkin_window_hours(tenant_id) -> int`, que lee la columna y cae al
default de la propia entidad, y `test_reading_the_collection_writes_nothing_at_all` pasa a contar
también `tenant_configs`, porque sin esa tabla el nombre del test era falso.

**Devuelve el `int` y no un `TenantConfig`**, corregido en la segunda ronda del mismo panel: el
primer intento devolvía una entidad transitoria de `TenantConfig.with_defaults(...)`, y esa lleva
un `id` recién generado y sellos de tiempo con pinta de reales, así que nada salvo un docstring la
distinguía de una fila persistida. Un `int` no se puede confundir con una fila ni pasar a un
escritor, y no necesita advertencia. De paso deja de ser cierto lo que el docstring anterior
alegaba —Interface Segregation— cuando en realidad **añadía** un tercer método al mismo `Protocol`:
el puerto crecía en vez de estrecharse por consumidor. La lectura tiene sus tres tests contra la
base de datos real en `backend/tests/tenants/test_repositories.py`, aislamiento por tenant
incluido, sobre sesión **sin marcar** — con sesión marcada la red de `with_loader_criteria` los
haría pasar aunque el predicado no existiera. (Medido en el panel: la red **sí** cubre un `select`
de una sola columna, así que en producción esta lectura está protegida por las dos cosas; lo que
el test sobre sesión sin marcar prueba es el predicado a solas, que es el mecanismo autoritativo.)

**Aviso para el siguiente change que toque este puerto**: `TenantConfigRepository` se queda con
tres métodos y esto es el sitio donde pararse. `checkin_window_hours` existe porque un peligro
concreto lo obligó —una escritura en una ruta de lectura—, no porque los accesores escalares sean
buena idea en general. Si hace falta un **segundo** accesor estrecho para otro campo suelto, eso
es la señal para partir el puerto en un lector de solo lectura, no para añadir un cuarto método
escalar.

Rejected: **un bloque en el dashboard** (`PropertyDashboardCard`) — es donde el manager ya mira y
fue la primera opción, pero (a) obligaría a meter `TenantConfigRepository` en un agregado que hoy
no tiene ninguna dependencia de configuración, sólo para leer `checkin_window_hours_before`, (b)
las cards están paginadas sobre la fuente, así que hereda el problema de arriba, y (c) el
dashboard es un agregado de siete dominios de solo lectura y esto es una alerta operacional con su
propio ciclo. Queda como candidato de roadmap una vez exista quien la pinte. · Rejected: una fila
persistida con apertura y cierre — inventa un ciclo de vida que el dato no tiene y añade el modo de
fallo de la fila que nadie cerró, que es la clase de bug que este change está arreglando. ·
Rejected: una ruta bajo `/properties/...` — `dashboard-api` D7 ya documentó que un segmento
literal ahí colisiona con `/properties/{id}` y se resuelve por orden de registro; «una garantía de
contrato no debe depender de eso».

### D6 — El permiso de la colección es `READ_PROPERTIES`, y eso **enmienda R2.1**

**Chosen:** `require(Permission.READ_PROPERTIES)`, decidido en el gate de diseño del 2026-08-23.
Lo ven `PROPERTY_MANAGER` y `TENANT_OWNER`.

R2.1 pedía `MANAGE_CLEANING_TASKS` o `MANAGE_PROPERTIES`, y los dos los tiene exactamente el mismo
rol —`PROPERTY_MANAGER`— y ninguno más (`app/auth/domain/policy.py`, `ROLE_PERMISSIONS`), así que
la disyunción no discriminaba a nadie y dejaba fuera a la propietaria. Se ensancha por dos razones:
la colección **no expone nada que la propietaria no vea ya** en su card del dashboard —el estado
operacional de su vivienda y las fechas de su reserva—, así que R2.3 («la visibilidad no estrena
acceso a datos que el rol no tuviera») sigue cumplida al pie de la letra; y el principio 2 de
`product.md` es también su historia: PRD §1 la describe operando dos viviendas desde el móvil,
a veces sin manager. No estrena permiso ni toca `ROLE_PERMISSIONS`.

**Consecuencia documental**: `proposal.md` R2.1 queda enmendado en el mismo commit que este
documento, para que la spec viva no herede un `SHALL` que el diseño ya cambió.

**De qué depende esta justificación, dicho para que se pueda romper en rojo** (panel de la
sección 4). El cuerpo lleva `reservation_id` y `due_since` sin condición, mientras `app/dashboard`
sí re-comprueba `READ_RESERVATIONS` antes de incluir su bloque de reserva. Verificado: hoy
`TENANT_OWNER` tiene `READ_RESERVATIONS` y el dashboard ya le devuelve el id de la reserva y sus
fechas, así que la frase de arriba es cierta —pero lo es por una coincidencia de
`ROLE_PERMISSIONS`, no por construcción. Se fija con
`test_every_reader_of_this_collection_may_already_read_reservations`: si algún día un rol de tipo
auditoría gana `READ_PROPERTIES` sin `READ_RESERVATIONS`, ese test cae nombrando este decision, que
es el momento en que alguien tiene que decidir. Se prefirió a condicionar los campos por permiso
—lo que el panel proponía— porque eso haría que la forma de la respuesta dependiera del rol para un
rol que todavía no existe, y este decision eligió expresamente no tocar `ROLE_PERMISSIONS`.

Rejected: `MANAGE_PROPERTIES` — literal a R2.1 tal como se escribió, y deja a la propietaria sin
saber que su vivienda está parada, a cambio de no conceder ninguna lectura nueva. · Rejected: un
`require_any(...)` nuevo — maquinaria de RBAC nueva para una disyunción que hoy no separa ningún
rol.

### D7 — R3 estrena el trigger `CLEANING_CANCELLED`, con destino **contextual**

**Chosen:** un miembro nuevo `PropertyStateTrigger.CLEANING_CANCELLED` con tres filas de matriz —
desde `AWAITING_CLEANING`, `CLEANING_SCHEDULED` y `CLEANING_IN_PROGRESS` — y destino resuelto por
un `ContextualStateResolver.after_cleaning_cancellation` nuevo que **delega en
`_contextual_reservation_cleaning`**, el mismo que `INCIDENT_RESOLVED` ya usa. El conjunto
permitido de cada fila es `CONTEXTUAL_STATES - {estado origen, CRITICAL_INCIDENT,
MAINTENANCE_REQUIRED}`, que da **cinco destinos desde `AWAITING_CLEANING`, seis desde
`CLEANING_SCHEDULED` y cinco desde `CLEANING_IN_PROGRESS`** — dieciséis filas declaradas en
total. No son seis por fila: `CLEANING_SCHEDULED` **no** es miembro de `CONTEXTUAL_STATES`, así
que a su fila la resta no le quita el origen y se queda con los seis que las otras dos pierden
por partida doble. La cifra importa porque es la que `test_original_66_policy_candidates_are_
explicitly_classified` fija (59 → 75).

**Corregido durante `/sdd:run` el 2026-08-23 (sección 1).** Este párrafo decía
`CONTEXTUAL_STATES - {estado origen}`, «calcado de las filas de `INCIDENT_RESOLVED`», y las
dos mitades de la frase se contradecían: `INCIDENT_RESOLVED` puede devolver
`CRITICAL_INCIDENT` y `MAINTENANCE_REQUIRED` porque `after_incident_resolution` mira las
incidencias activas **antes** de delegar, y el resolvedor elegido aquí —
`_contextual_reservation_cleaning` con `include_incidents=False`— no las mira nunca. Copiar
el conjunto habría declarado en la matriz dos arcos que ningún contexto puede producir, y
`test_every_declared_policy_relation_is_evaluable` recorre `_POLICY` entera exigiendo que
cada relación declarada sea evaluable: los habría puesto en rojo, que es exactamente para lo
que ese test existe.

Y no se pierde nada: una vivienda en un estado `CLEANING_*` **no puede** tener una incidencia
`HIGH` o `CRITICAL` viva, porque las tres filas `(CLEANING_*, INCIDENT_HIGH|INCIDENT_CRITICAL)`
de la matriz ya se la habrían llevado a `MAINTENANCE_REQUIRED` o `CRITICAL_INCIDENT`. Los dos
destinos retirados son inalcanzables por construcción, no por omisión.

Es lo que desatasca REDES11: sin tarea viva y con la estancia del 19→23 corriendo, ese resolvedor
devuelve `OCCUPIED_ESTIMATED` — el estado que el check-in nunca llegó a escribir.

**Y no es la «fila de conveniencia» que el proposal declara fuera de alcance.** Lo excluido es un
arco fijo `CLEANING_* → estado de check-in`; aquí el destino no está escrito en la matriz, lo
calcula el resolvedor a partir de las reservas y de las tareas reales. La diferencia importa: un
arco fijo mentiría cuando el contexto dijera otra cosa.

Rejected: destino fijo `AWAITING_CLEANING` — es la opción simple y **no arregla nada**:
`AWAITING_CLEANING` no es origen de ningún trigger de check-in, así que la vivienda seguiría
congelada y la limpieza que se asignara después volvería a chocar contra el `409` de
`after_cleaning_completion`. Es el nudo otra vez, un paso más allá. · Rejected: reutilizar
`CLEANER_REJECTED` — su guarda exige `REJECTED` y su semántica es «la limpiadora dijo no», que no
es lo que hace un manager retirando una tarea. · Rejected: relajar `after_cleaning_completion` —
fuera de alcance por el proposal, y correctamente.

### D8 — Lo que hace honesto el estado no es un caso especial del resolvedor: es la tarea de reemplazo

**Chosen:** `CancelCleaningTaskUseCase` crea una **tarea de reemplazo** sin asignar (`CREATED`) en
la misma transacción, *antes* de evaluar la transición, y la mete en el contexto. Así el resolvedor
existente devuelve `AWAITING_CLEANING` por sí solo —cuenta las tareas vivas primero— y no hay que
inventarle una rama. Es literalmente el argumento de `RejectCleaningTaskUseCase` (su design D3:
«la propiedad nunca se queda en `AWAITING_CLEANING` sin nada pendiente»), aplicado al revés: la
tarea pendiente es lo que impide que el sistema declare limpia una vivienda que no lo está.

Dos excepciones al reemplazo, cada una citando un invariante que ya existe y **ninguna** por
conveniencia (más una tercera salida, la del solape, documentada abajo):

1. **Hay una estancia activa en `now`** → no se crea reemplazo. Una limpieza con el huésped dentro
   es imposible por decisión del sistema (`after_cleaning_completion` se niega a cerrarla), así que
   el reemplazo sería una obligación que nadie puede cumplir — y, peor, volvería a congelar la
   vivienda en `AWAITING_CLEANING`, deshaciendo el change. El calendario ya provee: el
   `process_checkouts` del 23 crea la limpieza con `provision_for_checkout`.
2. **Ya hay otra tarea viva de la misma reserva** → no se crea reemplazo, porque
   `uq_cleaning_tasks_live_reservation` lo rechazaría con un `IntegrityError`
   (`DuplicateLiveCleaningTaskError`). Y no hace falta: esa tarea viva es la que el resolvedor va a
   contar.

   **Y es inalcanzable mientras ese índice exista, descubierto al implementarlo (sección 5).** El
   índice es parcial sobre `reservation_id IS NOT NULL AND status IN (vivos)`, así que **no puede
   haber** una segunda tarea viva con esa reserva mientras la nuestra siga viva —y cancelar exige
   que lo esté—; después de cancelar hay exactamente cero. La guarda se queda en el caso de uso
   porque cuesta una consulta y sería lo que salve el día que el índice cambie, pero no es una rama
   viva y conviene no leerla como si lo fuera. Lo que sí es comprobable es el invariante en el que
   se apoya, y eso es lo que fija `test_two_live_tasks_cannot_share_a_reservation`. La mitad
   alcanzable —una tarea **sin** reserva, que no compite por ningún hueco— tiene su propio test.

**Y hay una tercera salida de `_replacement_for`, que no es una excepción de las de arriba**
(panel de la sección 5, hallazgo de seguridad). `has_active_stay` levanta
`IncompatibleTransitionContextError` cuando hay **dos estancias activas solapadas** —un estado real
tras una anomalía de sync del PMS, no una hipótesis—, y esa excepción es un `PropertyDomainError`
que ningún handler mapea: sin capturarla, una cancelación legítima y autorizada salía como **500**
justo en la ruta que esta feature existe para desatascar. Se captura y se devuelve `None`, con lo
que la ejecución llega a `_transition`, cuyo resolvedor se topa con el mismo solape y se niega
igual — y ahí sí está traducido a `PropertyStateBlocksCleaningError`, el `409` de este módulo.

La indirección se apoya en un invariante que conviene decir: `_transition` reconstruye **las mismas
reservas** (mismo `candidate_window(now)`, misma vivienda, sin escrituras en medio) y la tarea del
contexto ya está `CANCELLED`, así que ninguna rama temprana de `_contextual_reservation_cleaning`
la desvía y la segunda llamada a `_active_reservations` es la misma llamada. O levantan las dos, o
no levanta ninguna: no hay entrada que produzca una cancelación *exitosa* con destino equivocado.
Lo fija `test_two_overlapping_stays_answer_a_conflict_not_a_crash`, que además comprueba que no se
escribe ni una fila.

**Y hereda de `_AnswersAnAssignmentBase`, no de `_TaskLifecycleBase` como decía este decision**
(corregido al implementar, sección 5). Cancelar no es responder a una asignación, pero **puede
pasar desde `ASSIGNED`**, donde el plazo de SLA de esa asignación sigue vivo. Sin cerrarlo,
`check_sla_breaches` escalaría al manager por una tarea que ya no existe — una falsa alarma que
introduciría este change, porque cancelar desde `ASSIGNED` es nuevo. Se reutiliza
`_close_assignment_sla`, que ya es idempotente y silencioso cuando no hay nada que cerrar
(`access-notifications`, proposal R5 criterio 3 —su *spec* ordena la misma regla por títulos y no
por R-números, así que la referencia es al proposal archivado—), así que el caso corriente
—cancelar una tarea `IN_PROGRESS`— cuesta un no-op. Lo prueba
`test_cancelling_an_assigned_task_closes_its_assignment_sla`: sin él la rama que **sí** limpia un
plazo vivo sólo se ejercitaba como no-op, y un `notification_type` equivocado habría pasado
inadvertido.

**Dónde acaba el `reason`, que no es donde este design suponía.** *Data & interfaces* dice que
retirar el trabajo de otra persona es lo que un `AuditLog` tiene que poder explicar, y el primer
intento lo metió en el diff auditado. `AUDITABLE_FIELDS` lo rechaza, y con razón: sólo admite
columnas reales y no sensibles de la entidad, y `cleaning_tasks.notes` está fuera a propósito
porque `audit_logs.changes` es un sumidero de la regla 11. El `reason` va entonces a
`property_state_transitions.reason`, que es la columna hecha para esto, y la fila de `AuditLog`
contesta «quién retiró esta tarea y cuándo». **Queda un hueco declarado**: cuando la cancelación no
mueve la vivienda no hay fila de transición, así que en ese caso el motivo sólo vive en la línea de
log `cleaning.cancel_without_state_change`. Es el precio de no meter texto libre en `changes`.

Rejected: un `requires_recleaning: bool` en el cuerpo — traslada al cliente una decisión que el
contexto ya contesta sin ambigüedad, y abre la combinación «recleaning con huésped dentro», que
habría que rechazar con un `409` que nadie entiende. · Rejected: no crear nunca reemplazo — deja
`VACANT_READY` sobre una vivienda a medio limpiar (mentira de estado, contra el principio 1 de
`product.md`) y sin salida, porque `CLEANER_ASSIGNED` sólo sale de `AWAITING_CLEANING`.

### D9 — `cancel` se permite exactamente desde `LIVE_STATUSES`, y la evidencia parcial se conserva

**Chosen:** `CleaningTask.cancel(now, reason)` con `_require_status(LIVE_STATUSES, "cancel")` →
`CANCELLED`. Cualquier otro estado da `InvalidCleaningTransitionError` → `409` sin escribir nada
(R3.4), que es el camino que el mapeo de `cleaning/api/errors.py` ya tiene montado.

`PENDING_REVIEW` queda fuera del conjunto permitido aunque no sea terminal, y conviene decir por
qué en vez de dejarlo como omisión: **nada lo escribe** (`complete()` va directo a `COMPLETED`, y
`LIVE_STATUSES` lo excluye a propósito desde el change `cleaning`), y una tarea que llegara ahí ya
habría resuelto el estado de la vivienda al completarse — no hay nada que desatascar. Es una
divergencia literal de la palabra «terminal» de R3.4, no de su intención, y el `409` lleva el
estado en el mensaje.

**La evidencia parcial se conserva entera** (R3.5): ni los `CleaningChecklistCompletion` ni los
`CleaningPhoto` se borran, y ningún objeto del almacén se toca. Tres razones: las fotos son objetos
que ninguna transacción deshace (`cleaning-photos-storage`), así que un borrado a medias dejaría
filas huérfanas o objetos huérfanos según por dónde fallara; el trabajo que sí se hizo es
precisamente lo que un manager necesita ver para decidir si repetir la limpieza; y borrar
evidencia por cancelar contradice el timeline inmutable del principio 1. La tarea cancelada sigue
siendo consultable con sus ítems y sus fotos por las rutas que ya existen.

### D10 — R4: se **retira** `CLEANING_ASSIGNMENT_EXPIRED`

**Chosen:** eliminar el miembro del enum, su fila de `_POLICY` y su entrada del mapa de estados
esperados de `_validate_trigger_preconditions`, y dejar la decisión escrita en
`sdd/specs/timeline-state-machine.md` (R4.3). Cuatro razones, en orden de peso:

1. **La necesidad operativa ya está cubierta.** Una asignación sin respuesta escala al manager por
   el SLA de `check_sla_breaches` / `EscalateBreachedSlasUseCase`, vivo desde
   `access-notifications`, con el plazo de `TenantConfig.sla_medium_minutes` que R4.2 nombra. El
   trigger no añadiría aviso, añadiría una desasignación automática.
2. **Y esa desasignación es política operativa nueva**, que el change `cleaning` dejó fuera de
   alcance explícitamente («un job de reasignación es política operativa nueva»). Quitarle la tarea
   a una limpiadora que está a punto de aceptar es una decisión de producto, no la reparación de un
   trigger huérfano.
3. **Su guarda ya es incoherente con su nombre**: acepta `{ASSIGNED, ACCEPTED}`, y una tarea
   `ACCEPTED` es precisamente una asignación **respondida**.
4. **D7 entrega la salida humana y auditada** que el trigger intentaba automatizar: un manager con
   `MANAGE_CLEANING_TASKS` cancela la tarea, con motivo, `AuditLog` y `TimelineEvent`. Es mejor
   respuesta que un job silencioso.

Retirarlo no cuesta migración (ver *Context*) y es reversible: si alguna vez gana su política, se
reintroduce con su emisor en el mismo commit, que es la única forma en que debió existir.
Confirmado en el gate de diseño del 2026-08-23.

Rejected: escribirle un emisor ahora — obliga a decidir en este change una política de reasignación
que nadie ha pedido (quitarle la tarea a una limpiadora que aún podría aceptar), y R4.1 admite las
dos salidas.

### D11 — Sin frontend, y con la entrada de roadmap que lo dice

**Chosen:** la entrada de roadmap es `[BE]` y este change entrega **API**, no pantalla. Conviene
decirlo porque la lectura literal de R2 («que no me enteré por un huésped») no se cumple hasta que
algo pinte `GET /api/v1/blocked-transitions`: un manager no lee JSON. Lo que este change garantiza
es que el dato existe, es consultable por el rol correcto y desaparece solo.

**Encargo explícito para `/sdd:archive`** (decidido en el gate del 2026-08-23): al cerrar este
change, añadir a `sdd/roadmap.md` una entrada `[FE]` nueva —`blocked-transitions-web` o el nombre
que encaje con la nomenclatura vigente— que pinte los desajustes donde el manager ya mira (la card
del dashboard o `/cleaning`), con `needs: cleaning-stall-blocks-next-stay` y `kind: feature`. Se
escribe aquí porque ningún gate posterior lo delataría si se olvidase.

Rejected: colar una pantalla mínima en este change — cruza el límite `[BE]` de la entrada y arrastra
i18n y contrato de frontend a un change `kind: tech`. · Rejected: entregar la API sin anotar el
hueco — el dato existiría y nadie lo pintaría, y nada lo recordaría.

### Cobertura de requisitos

Ninguno queda sin implicación de diseño, y se tabula para que `/sdd:tasks` no tenga que
reconstruirlo:

| Criterio | Dónde se resuelve |
|---|---|
| R1.1 el desajuste deja rastro identificándolo | D1 (`detect`) + D4 (log estructurado) |
| R1.2 no es `not_eligible` | D3 |
| R1.3 se detecta aunque no sea candidata | D1, D3 (segunda consulta, por el complemento de estados origen) |
| R1.4 ventana acotada y declarada | D4 (la misma `candidate_window`, dicha en `docs/celery-jobs.md`) |
| R2.1 visible sin leer logs | D5 (ruta) + D6 (permiso, **con enmienda al proposal**) |
| R2.2 incluye el motivo | *Data & interfaces* (`trigger` + `blocking_state` + `due_since`) |
| R2.3 respeta tenant y permisos | D6 (no estrena permiso) + *Risks* (test de aislamiento) |
| R2.4 desaparece sin intervención | D5 (derivado en lectura, nada persistido) |
| R3.1 operación a estado terminal, con `MANAGE_CLEANING_TASKS` | D9 + *Data & interfaces* |
| R3.2 resuelto por la máquina, sin escribir la columna | D7 (trigger + resolvedor contextual) |
| R3.3 `AuditLog` + `TimelineEvent` | *Data & interfaces* (orden de escrituras, un solo `commit`) |
| R3.4 `409` si ya es terminal, sin escribir | D9 |
| R3.5 destino de la evidencia parcial | D9 (se conserva entera, con las tres razones) |
| R4.1 cerrar el trigger de una de las dos formas | D10 (retirada) |
| R4.2 el plazo saldría de `sla_medium_minutes` | Sin efecto: al retirarse no hay plazo que derivar. La necesidad que lo motivaba ya la cubre la escalada de SLA que **usa** ese campo (D10, razón 1) |
| R4.3 dejar constancia en la spec | D10 (`sdd/specs/timeline-state-machine.md`) |

## Changes by area

| Area | Files | Change |
|---|---|---|
| Máquina de estados | `backend/app/properties/domain/transition_enums.py` | `+ CLEANING_CANCELLED`; `- CLEANING_ASSIGNMENT_EXPIRED` (D7, D10) |
| Máquina de estados | `backend/app/properties/domain/state_machine.py` | 3 filas de `_POLICY` para `CLEANING_CANCELLED` con destino contextual; rama en `_destination`; `CLEANING_CANCELLED: {CANCELLED}` en el mapa de estados esperados; `- ` la fila y la entrada de `CLEANING_ASSIGNMENT_EXPIRED`; **nuevo** `is_due()` (D2) |
| Resolución contextual | `backend/app/properties/domain/state_resolution.py` | `+ after_cleaning_cancellation()`, delegando en `_contextual_reservation_cleaning` (D7) |
| Detección (nuevo) | `backend/app/properties/domain/stalls.py` | `BlockedTransition` + `detect()` (D1) |
| Puerto de transiciones | `backend/app/properties/domain/repositories.py`, `infrastructure/repositories.py` | `+ PropertyStateTransitionRepository.applied_clock_triggers()` — la evidencia de `applied` (D1 enmendado). Un **lector** más en un puerto que ya ganó uno en `dashboard-api`: lo que su docstring rechaza es `save`/`update`/`delete`, y esto no es ninguno |
| Job de reloj | `backend/app/properties/application/use_cases.py` | `AdvanceReport.blocked`; segunda consulta por el complemento de estados origen; log `scheduler.blocked_transition` (D3, D4) |
| Lectura de R2 (nuevo) | `backend/app/properties/application/use_cases.py` | `ListBlockedTransitionsUseCase` (D5) |
| Puerto de config | `backend/app/tenants/domain/repositories.py`, `infrastructure/repositories.py` | `+ TenantConfigRepository.checkin_window_hours()` — lectura de una columna con su default, para que «nada se guarda» sea cierto en un `GET` (D5) |
| API de propiedades | `backend/app/properties/api/router.py`, `schemas.py`, `dependencies.py`, `backend/app/main.py` | `GET /api/v1/blocked-transitions` + su sobre paginado (D5, D6). **Router propio** en el mismo módulo: el `router` que ya está tiene `prefix="/properties"`, y colgar de él un segmento literal es exactamente la colisión que D5 rechaza. Se registra en `main.py` como un segundo `include_router`, igual que `dashboard` sirve sus dos prefijos desde un módulo |
| Limpieza — entidad | `backend/app/cleaning/domain/entities.py` | `+ CleaningTask.cancel()` (D9) |
| Limpieza — caso de uso | `backend/app/cleaning/application/use_cases.py` | `+ CancelCleaningTaskUseCase` sobre `_TaskLifecycleBase` (D7, D8) |
| Limpieza — API | `backend/app/cleaning/api/tasks_router.py`, `schemas.py`, `dependencies.py` | `POST /api/v1/cleaning-tasks/{id}/cancel`, `ManageDep` |
| Auditoría | `backend/app/audit/domain/actions.py` | `+ CLEANING_TASK_CANCELLED` (constante y registro exhaustivo) |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerar **las dos mitades** (`steering/documentation.md`) |
| Tests | `backend/tests/properties/test_state_machine.py` | catálogo cerrado de triggers, matriz esperada y guardas: quitar el retirado, añadir el nuevo |
| Tests (nuevos) | `backend/tests/properties/test_stalls.py`, `tests/cleaning/test_cancel_task.py`, `tests/properties/test_blocked_transitions_api.py` | ver *Risks* |
| Docs | `docs/celery-jobs.md`, `docs/cleaning.md`, `docs/properties.md` | cubo `blocked` y su ventana; la cancelación y su evidencia; la colección nueva |
| Diagramas | `docs/diagrams/2026-08-23_autohost-limpieza-atascada.png` | nuevo (el nudo y la salida). Regenerado a **PNG** con `mmdc` en el panel de la sección 5: el primer intento era `.svg` y `steering/documentation.md` nombra `{YYYY-MM-DD}_{slug}.png`, que es además el formato de los otros siete. Ojo si alguien lo reconvierte: sus etiquetas viven en `foreignObject`, así que `rsvg-convert` produce un diagrama **sin una sola etiqueta** —comprobado— y hay que rerenderizar desde el fuente Mermaid, no convertir |
| Specs (al archivar) | `sdd/specs/celery-jobs.md`, `timeline-state-machine.md`, `cleaning.md`, `api-contract.md` | R1/R4, D7/D10, D8/D9, ruta nueva |

**`sdd/specs/dashboard-api.md` no queda afectada**: D5 resolvió R2 fuera del dashboard.

## Data & interfaces

**Migración: ninguna.** Razonado en *Context* — `CANCELLED` ya está en el tipo
`cleaning_task_status` y `PropertyStateTrigger` no es columna de nada.

**`POST /api/v1/cleaning-tasks/{task_id}/cancel`** — `MANAGE_CLEANING_TASKS`.

```
Request:  { "reason": str }            # obligatorio, no vacío
Response: CleaningTaskResponse         # la tarea cancelada
409  tarea no viva (R3.4) · 409  el estado de la vivienda bloquea (PropertyStateBlocksCleaningError)
404  otro tenant · 422  reason vacío
```

`reason` es obligatorio aunque la máquina no lo exija para este trigger (`CLEANING_CANCELLED` no
entra en su conjunto `manual`): retirar el trabajo de otra persona es exactamente lo que un
`AuditLog` tiene que poder explicar seis meses después.

Escrituras de una sola transacción, en este orden: `task.cancel()` → reemplazo si procede (D8) →
`PropertyStateMachine.evaluate` → `property_state_transitions` + `TimelineEvent`
`PROPERTY_STATE_CHANGED` + `properties.current_operational_state` → `AuditLog`
`CLEANING_TASK_CANCELLED` → `commit`. Un `NoOperationalStateChangeError` (cancelar la única tarea
`CREATED` de una vivienda que ya está en `AWAITING_CLEANING`) **no es error**: se cancela la tarea,
la vivienda no se mueve y se registra en el log, como `_fire_cleaner_assigned` ya hace.

**`GET /api/v1/blocked-transitions`** — `READ_PROPERTIES` (D6), sobre paginado de PRD §23.

```
{ "data": [ { "property_id": uuid, "property_code": str, "reservation_id": uuid,
              "trigger": "CHECKIN_TIME_REACHED", "blocking_state": "CLEANING_IN_PROGRESS",
              "due_since": "2026-08-19T14:00:00Z" } ],
  "page": 1, "per_page": 20, "total": 1, "total_pages": 1 }
```

`trigger` y `blocking_state` son los literales canónicos, sin prosa: es el mismo trato que
`dashboard-api` da a `operational_state` («carries no colour: the colour mapping belongs to the
client»), y evita estrenar un catálogo de traducciones para un consumidor que todavía no existe
(D11). `due_since` es el instante que la máquina considera vencido —inicio efectivo, inicio menos
la ventana, o checkout efectivo, según el trigger— y es el número que el operador quiere: para
REDES11, el 19 de agosto.

**Sin variables de entorno nuevas, sin campos de `TenantConfig` nuevos, sin tipos de notificación
nuevos.**

## Risks & mitigations

- **Retirar un miembro de enum deja filas históricas con un valor que el enum ya no tiene.** Está
  acotado y verificado: el único sitio donde `CLEANING_ASSIGNMENT_EXPIRED` puede haberse
  persistido es el JSON de `metadata`, y nada lo deserializa (`PropertyStateTrigger(...)` no se
  construye desde datos en ninguna parte del código de producción). Además, en `dev` hay **cinco
  filas** en `property_state_transitions` y ninguna lo lleva. Mitigación: un test que compruebe que
  ningún camino de lectura convierte `metadata["trigger"]` en enum.
- **`detect` puede contar dos veces el mismo atasco.** Una vivienda con dos reservas solapadas en
  la ventana produciría dos entradas. Mitigación: la clave del value object es
  `(property_id, reservation_id, trigger)` y el job cuenta **viviendas**, no desajustes, en su
  cubo `blocked` — la misma precedencia «un cubo por vivienda» que `AdvanceReport` ya documenta.
- **La consulta de `applied` filtra por `metadata->>'reservation_id'`, que no está indexado.**
  `property_state_transitions` sólo tiene `ix_property_state_transitions_property_id_created_at`, así
  que esta lectura es un escaneo filtrado por tenant. Acotada por construcción —pregunta sólo por
  las reservas de la ventana, que ya están cargadas— y con cinco filas en `dev` es irrelevante;
  se declara aquí en vez de dejarla descubrir, con la palanca escrita: un índice de expresión
  sobre `(tenant_id, (metadata->>'reservation_id'))` si alguna vez pesa.
- **`list_all` en la lectura de R2 no está paginado en origen** (D5). Con 2 viviendas es
  irrelevante; con 200 son dos consultas grandes por petición. Mitigación: declararlo como deuda
  en la spec con la palanca escrita (filtrar por el complemento de estados origen por trigger, como
  hace el job), en vez de dejar que se descubra.
- **Doble camino a `AWAITING_CLEANING`.** Tras D7+D8, `CLEANER_REJECTED` y `CLEANING_CANCELLED`
  llegan al mismo sitio por rutas distintas. Mitigación: el test de matriz de
  `test_state_machine.py` ya recorre `_POLICY` entera, y se le añade el caso de que la cancelación
  con estancia activa **no** cree reemplazo (que es el que protege el arreglo).
- **Cobertura mínima que el change no puede declararse hecho sin ella**: (1) el caso REDES11 de
  extremo a extremo — vivienda en `CLEANING_IN_PROGRESS`, estancia activa, `cancel` →
  `OCCUPIED_ESTIMATED` y sin tarea de reemplazo; (2) `blocked` se incrementa y `not_eligible` **no**
  (R1.2); (3) un desajuste desaparece de la colección en cuanto se resuelve, sin escritura
  (R2.4); (4) aislamiento por tenant en la ruta nueva (regla 1 de `security.md`); (5) `409` sobre
  tarea ya cancelada, sin filas escritas (R3.4); (6) la evidencia parcial sigue ahí después de
  cancelar (R3.5).

## Open questions

Ninguna abierta. Las tres que este diseño levantó se resolvieron en su gate, el **2026-08-23**, y
viven ya donde tienen efecto:

| Pregunta | Resuelta como | Dónde |
|---|---|---|
| ¿Ve la propietaria los desajustes? | Sí — `READ_PROPERTIES`, y **R2.1 del proposal queda enmendado** | D6 + `proposal.md` R2.1 |
| ¿`CLEANING_ASSIGNMENT_EXPIRED` gana emisor o se retira? | Se retira, con la decisión escrita en la spec | D10 |
| ¿Quién pinta los desajustes? | Entrada `[FE]` nueva de roadmap, que crea `/sdd:archive` | D11 |
