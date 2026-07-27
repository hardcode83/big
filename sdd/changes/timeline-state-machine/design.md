# Design: timeline-state-machine

## Context

`domain-foundation-core` ya aporta las entidades Python puras `Property`,
`PropertyStateTransition`, `Reservation` y `TimelineEvent`, junto con sus enums, en
`backend/app/{properties,reservations,timeline}/domain/`. `domain-foundation-ops`
añade `CleaningTask` e `Incident` en `backend/app/{cleaning,maintenance}/domain/`.
Todas son dataclasses de datos sin servicios de dominio: hoy cualquier consumidor
podría asignar un estado sin validar PRD §8 y no existe una forma común de construir
la evidencia correlacionada exigida por PRD §3.1 y §10.

Este change añade únicamente objetos y servicios Python puros en las capas
`domain/`. No modifica las entidades ni enums existentes, no muta `Property`, no
añade puertos, casos de uso, ORM, migraciones, endpoints, jobs o adapters. La futura
capa de aplicación aplicará el estado aceptado y persistirá `Property`,
`PropertyStateTransition` y `TimelineEvent` en una única transacción; este diseño
solo produce la decisión de dominio completa e indivisible.

## Design objectives

- Hacer de `PropertyStateMachine` la única API de dominio que acepta cambios del
  estado operacional y cubrir exactamente el mapa de PRD §8.1 (R1-R3).
- Resolver de forma determinista los destinos dependientes de reservas, limpiezas,
  incidencias y tiempo explícito, sin reloj global ni lecturas externas (R2-R4).
- Exigir actor, destino y motivo en las operaciones manuales aprobadas sin realizar
  enforcement de RBAC dentro del dominio (R3, R5).
- Devolver juntas las dos evidencias inmutables de una transición aceptada y aplicar
  reglas reutilizables de construcción de `TimelineEvent` (R6).
- Mantener toda dependencia dirigida hacia `domain/`, sin infraestructura, y dejar
  contratos suficientemente concretos para derivar `tasks.md` sin decisiones
  técnicas pendientes (R7).

## Architecture proposed

El diseño mantiene los límites del monolito modular. `properties/domain` es dueño
de la decisión de cambio de estado; `timeline/domain` es dueño de las reglas comunes
de construcción de eventos. Las dependencias son exclusivamente entre módulos de
dominio ya existentes:

```text
caller futuro
    |
    v
PropertyStateMachine
    |-- TransitionPolicy          (mapa explícito PRD §8.1)
    |-- ContextualStateResolver   (PRD §8.2)
    `-- TimelineEventFactory      (reglas comunes del timeline)
             |
             v
PropertyStateChangeResult
    |-- PropertyStateTransition
    `-- TimelineEvent(PROPERTY_STATE_CHANGED)
```

No hay lectura ni escritura lateral en este flujo. Todos los datos entran en un
`PropertyStateChangeRequest`; los servicios devuelven valores o errores de dominio.

## Decisions

### D1 — `PropertyStateMachine` vive en el dominio `properties`

**Chosen:** crear `backend/app/properties/domain/state_machine.py` con un servicio
sin estado `PropertyStateMachine`. Será la única API pública para evaluar cambios de
`Property.current_operational_state`; recibe una solicitud completa, valida y
devuelve `PropertyStateChangeResult` sin mutar ningún objeto de entrada.

La vivienda es el agregado cuyo estado se protege y steering ya asigna la state
machine al dominio `properties`. Un servicio de dominio es apropiado porque la regla
combina `Property`, `Reservation`, `CleaningTask`, `Incident` y timeline y no
pertenece a una sola entidad.

Rejected: añadir `Property.transition_to()` — modificaría una entidad congelada por
la Proposal y la haría depender de otros agregados. Rejected: ubicar la regla en
`application/` — convertiría una invariante de negocio en orquestación.

**Consequences:** no se añade ningún segundo método o tabla de transición. La futura
aplicación deberá invocar este servicio y aplicar exclusivamente su `to_state`; la
dataclass `Property` permanece sin mutación durante la evaluación.

### D2 — Solicitud explícita, inmutable y autosuficiente

**Chosen:** crear en `backend/app/properties/domain/value_objects.py` dataclasses
congeladas para:

- `PropertyStateChangeRequest`: `property`, disparador semántico, contexto,
  `requested_state` opcional, actor, motivo, instante de referencia, identificadores
  de las dos evidencias, `source_entity_id` y `reservation_id` relacionado
  opcionales e identificador de correlación estable opcional.
- `PropertyTransitionContext`: tuplas de `Reservation`, `CleaningTask` e `Incident`.
- `TransitionActor`: `StateTransitionTriggeredBy` y `user_id` opcional.
- `TransitionEvidenceIds`: UUID de `PropertyStateTransition` y de `TimelineEvent`.
- `PropertyStateChangeResult`: las dos evidencias construidas como una unidad.

El instante se recibe como `datetime` consciente de zona. La fecha local y las
horas efectivas se calculan de forma pura usando `Property.timezone`, los defaults de
la propiedad y los overrides de la reserva; no se consulta un reloj global. Los UUID
de evidencia se reciben como entrada para evitar aleatoriedad interna y conservar el
determinismo incluso cuando no existe identificador de correlación.

Rejected: leer reservas o incidencias mediante repositorios — está fuera de alcance
y acoplaría el dominio a puertos innecesarios. Rejected: generar UUID con `uuid4()` o
leer `datetime.now()` dentro del servicio — haría diferente el resultado para la
misma entrada. Rejected: derivar siempre IDs con UUIDv5 — el identificador de
correlación es opcional y no existe una regla de negocio aprobada para convertirlo
en identidad persistida.

**Consequences:** el caller reúne los snapshots y genera los UUID antes de entrar al
dominio. Cambiar actor, contexto, instante o IDs significa cambiar la entrada; una
entrada idéntica produce objetos con exactamente los mismos campos.

### D3 — Disparadores semánticos separados del origen técnico

**Chosen:** crear `backend/app/properties/domain/transition_enums.py` con
`PropertyStateTrigger`. Este enum describe el hecho de negocio que solicita el
cambio; `StateTransitionTriggeredBy` existente conserva su función de indicar el
origen técnico (`SYSTEM`, `USER`, `SCHEDULER`, `WEBHOOK`). No se modifica ningún enum
persistido existente.

Los miembros serán `CHECKIN_WINDOW_OPENED`, `CHECKIN_TIME_REACHED`,
`CHECKOUT_TIME_REACHED`, `RESERVATION_CANCELLED_BEFORE_CHECKIN`,
`CLEANER_ASSIGNED`, `CLEANER_REJECTED`, `CLEANING_ASSIGNMENT_EXPIRED`,
`CLEANING_STARTED`, `CLEANING_COMPLETED`, `INCIDENT_HIGH`,
`INCIDENT_CRITICAL`, `INCIDENT_RESOLVED`, `OWNER_BLOCKED`,
`PROPERTY_MARKED_OUT_OF_SERVICE`, `PROPERTY_REACTIVATED` y
`OWNER_MANAGER_UNBLOCKED`. `INCIDENT_HIGH` e `INCIDENT_CRITICAL` representan tanto
creación como cambio de severidad; el workflow que originó el hecho queda fuera de
este servicio.

Rejected: reutilizar `TimelineEventType` como disparador — mezcla el hecho de entrada
con el evento de salida y no representa todas las condiciones de PRD §8. Rejected:
usar strings libres — impediría cobertura exhaustiva y permitiría variantes.

**Consequences:** futuros módulos traducirán sus hechos al enum común sin duplicar
la política. Añadir un workflow no exige añadir un nuevo disparador si expresa el
mismo hecho operacional.

### D4 — Matriz explícita para transiciones; resolución separada para destinos contextuales

**Chosen:** `PropertyStateMachine` mantiene una matriz declarativa de
`(from_state, trigger, allowed_to_states)`. Los destinos fijos se validan
directamente; `CLEANING_COMPLETED`, `INCIDENT_RESOLVED` y
`OWNER_MANAGER_UNBLOCKED` delegan el destino a reglas contextuales antes de validar
la misma matriz.

| Origen | Disparador | Destino permitido |
|---|---|---|
| `VACANT_READY` | check-in window / owner block / out of service / incident HIGH | `AWAITING_CHECKIN` / `BLOCKED_BY_OWNER` / `OUT_OF_SERVICE` / `MAINTENANCE_REQUIRED` |
| `AWAITING_CHECKIN` | check-in time / incident HIGH / incident CRITICAL / owner block / reservation cancelled | `OCCUPIED_ESTIMATED` / `MAINTENANCE_REQUIRED` / `CRITICAL_INCIDENT` / `BLOCKED_BY_OWNER` / `VACANT_READY` |
| `OCCUPIED_ESTIMATED` | checkout time / incident CRITICAL / incident HIGH | `AWAITING_CLEANING` / `CRITICAL_INCIDENT` / `MAINTENANCE_REQUIRED` |
| `AWAITING_CLEANING` | cleaner assigned / incident CRITICAL / incident HIGH / owner block | `CLEANING_SCHEDULED` / `CRITICAL_INCIDENT` / `MAINTENANCE_REQUIRED` / `BLOCKED_BY_OWNER` |
| `CLEANING_SCHEDULED` | cleaning started / rejected or assignment expired / incident CRITICAL | `CLEANING_IN_PROGRESS` / `AWAITING_CLEANING` / `CRITICAL_INCIDENT` |
| `CLEANING_IN_PROGRESS` | cleaning completed / incident HIGH / incident CRITICAL | `READY_FOR_NEXT_GUEST`, `AWAITING_CHECKIN` o `VACANT_READY` según contexto / `MAINTENANCE_REQUIRED` / `CRITICAL_INCIDENT` |
| `READY_FOR_NEXT_GUEST` | check-in window / incident HIGH / incident CRITICAL / owner block | `AWAITING_CHECKIN` / `MAINTENANCE_REQUIRED` / `CRITICAL_INCIDENT` / `BLOCKED_BY_OWNER` |
| `MAINTENANCE_REQUIRED` | incident resolved / incident CRITICAL / owner block | estado contextual / `CRITICAL_INCIDENT` / `BLOCKED_BY_OWNER` |
| `CRITICAL_INCIDENT` | incident HIGH or resolved / owner block | `MAINTENANCE_REQUIRED` o estado contextual / `BLOCKED_BY_OWNER` |
| `BLOCKED_BY_OWNER` | owner/manager unblock | destino canónico explícito compatible, excepto el mismo estado |
| `OUT_OF_SERVICE` | manual reactivation | `VACANT_READY` |

La matriz reproduce PRD §8.1; pares no declarados y no-ops se rechazan. Si un cálculo
contextual devuelve el estado actual, no existe transición operacional: se devuelve
`NoOperationalStateChangeError` y no se construye `PROPERTY_STATE_CHANGED`. El
workflow propietario podrá registrar su propio evento (por ejemplo,
`INCIDENT_RESOLVED`) mediante las reglas comunes del timeline.

Rejected: un grafo genérico configurable — añade abstracción sin requisito y oculta
condiciones de negocio. Rejected: un `if/elif` independiente en cada módulo consumidor
— crearía autoridades alternativas.

**Consequences:** la matriz es visible, enumerable y permite generar pruebas para
todos los pares válidos e inválidos. Las condiciones permanecen en políticas
nombradas, no embebidas como callbacks configurables.

### D5 — Resolución contextual por precedencia única

**Chosen:** crear `ContextualStateResolver` en
`backend/app/properties/domain/state_resolution.py`. Recibe únicamente el contexto
ya validado, la propiedad y el instante explícito. Para resolución de incidencias
aplica esta precedencia, conforme a R4:

1. alguna incidencia activa `CRITICAL` → `CRITICAL_INCIDENT`;
2. ninguna crítica y alguna activa `HIGH` → `MAINTENANCE_REQUIRED`;
3. limpieza `IN_PROGRESS` → `CLEANING_IN_PROGRESS`;
4. limpieza `CREATED`, `ASSIGNED` o `ACCEPTED` → `AWAITING_CLEANING`;
5. reserva activa dentro de su intervalo efectivo → `OCCUPIED_ESTIMATED`;
6. próxima reserva confirmada entra en la fecha local de referencia →
   `AWAITING_CHECKIN`;
7. próxima reserva confirmada entra después → `READY_FOR_NEXT_GUEST`;
8. ningún contexto anterior → `VACANT_READY`.

Una incidencia está activa si su estado no es `RESOLVED` ni `CANCELLED`. Para la
resolución contextual solo se consideran reservas en estado `CONFIRMED` o
`CHECKED_IN_ESTIMATED`; sus instantes efectivos combinan fechas, overrides y
defaults de `Property` en la zona de la vivienda. La actividad temporal usa el
intervalo semiabierto `[effective_check_in, effective_check_out)`: en
`effective_check_in` la reserva está activa y en `effective_check_out` deja de
estarlo. Para limpieza completada se reutiliza el tramo de reservas de la misma
política, sin la precedencia de incidencias, porque el mapa de PRD §8.1 limita sus
tres destinos a `READY_FOR_NEXT_GUEST`, `AWAITING_CHECKIN` y `VACANT_READY`.

El resolver rechaza contexto que no permita una única respuesta: entidades de otro
tenant o propiedad, fechas sin zona cuando sean necesarias, reservas activas
solapadas o datos temporales incompletos para decidir una condición aplicable. No
selecciona silenciosamente por orden de lista. Para desbloqueo, valida el destino
explícito contra estas mismas condiciones cuando el estado es contextual; los
estados manuales se validan por su regla manual.

Rejected: restaurar el estado anterior desde `PropertyStateTransition` — contradice
la decisión aprobada para `BLOCKED_BY_OWNER` y puede restaurar información obsoleta.
Rejected: elegir la primera reserva/tarea recibida — el orden de colección no es una
regla de negocio y rompería el determinismo.

**Consequences:** la resolución es una función pura reutilizable y testeable. El
caller debe entregar contexto suficiente y coherente; no se toleran resultados
aproximados.

### D6 — Actor validado como dato, RBAC fuera del dominio

**Chosen:** `TransitionActor` contiene el `StateTransitionTriggeredBy` existente y,
cuando el origen es `USER`, un `user_id` obligatorio. El tipo de actor del timeline
se deriva de forma total (`SYSTEM→SYSTEM`, `USER→USER`, `SCHEDULER→SCHEDULER`,
`WEBHOOK→WEBHOOK`) para impedir que las dos evidencias discrepen. El dominio no
recibe permisos ni roles y no comprueba que un usuario sea owner o manager.

Las operaciones manuales de bloqueo, fuera de servicio, reactivación y desbloqueo
requieren origen `USER`, `user_id` y motivo no vacío. El desbloqueo requiere además
`requested_state`. Esto valida la forma de los datos aprobados en R3/R5; el caller es
responsable de RBAC antes de invocar el dominio.

Rejected: pasar `UserRole` o un booleano `is_authorized` — introduciría autorización
en un servicio que no debe conocerla. Rejected: aceptar dos actores independientes
para histórico y timeline — permitiría trazabilidad contradictoria.

**Consequences:** una incidencia reportada por guest o IA puede conservar ese actor
en su evento propietario futuro, pero el cambio de estado usa uno de los cuatro
orígenes representables por `PropertyStateTransition`; no se modifica su esquema.

### D7 — Resultado compuesto y construcción all-or-nothing

**Chosen:** `PropertyStateChangeResult` es una dataclass congelada con exactamente
`transition: PropertyStateTransition` y `timeline_event: TimelineEvent`. El servicio
valida primero toda la solicitud, resuelve y valida el destino, prepara ambos
payloads y solo entonces instancia el resultado. Una excepción en cualquier paso
impide devolver evidencia parcial.

Ambos registros comparten tenant, propiedad, actor lógico, motivo, instante y el
identificador de correlación cuando se proporciona. La correlación se guarda bajo la
clave estable `correlation_id` en el `metadata` de ambos. El timeline añade
`from_state`, `to_state`, `trigger` y `source_entity_id` cuando existe;
`PropertyStateTransition` conserva `trigger`, `source_entity_id` y correlación en
metadata y ya expresa origen y destino en campos propios. El evento usa
`TimelineEventType.PROPERTY_STATE_CHANGED`, severidad `INFO`, título técnico
determinista en inglés y el motivo como descripción. Ese título persistido es
únicamente un fallback técnico; la capa de aplicación/presentación deriva y localiza
el texto visible para el usuario a partir de `event_type` y `metadata`. No se inventa
una política de severidad no aprobada; la urgencia sigue expresada por el estado
destino.

Las entidades existentes son dataclasses mutables y no se cambian por restricción de
alcance. Se tratan como registros write-once: el factory crea diccionarios de
metadata propios y ningún servicio conserva referencias internas ni modifica las
evidencias después de construirlas.

Rejected: devolver primero la transición y publicar el evento después — permitiría
un resultado lógico parcial. Rejected: crear nuevas entidades paralelas — duplicaría
los contratos ya archivados. Rejected: mutar `Property.current_operational_state`
dentro del servicio — mezclaría decisión y aplicación y dificultaría la transacción
futura.

**Consequences:** el resultado es la unidad mínima que la futura aplicación debe
persistir junto con la actualización de `Property`. La atomicidad durable y la
deduplicación siguen fuera de este change.

### D8 — Reglas comunes de timeline en un factory puro

**Chosen:** crear `TimelineEventFactory` en
`backend/app/timeline/domain/services.py` y sus value objects/errores en ese mismo
dominio. El factory valida campos comunes, copia metadata, exige instante con zona y
construye un `TimelineEvent` completo. Expone una operación general para los módulos
futuros y una operación `property_state_changed` usada por la state machine.

Esto satisface R6.6 sin implementar workflows ajenos: reservas, limpieza o
mantenimiento podrán construir sus eventos con las mismas reglas de dominio, pero
decidir cuándo hacerlo seguirá perteneciendo a cada módulo.

Rejected: un `TimelineService` con repositorio — persistencia y orquestación están
fuera de alcance. Rejected: construir `TimelineEvent` directamente en cada módulo —
duplicaría validación, actor, tiempo y metadata.

**Consequences:** el nombre `Factory` deja explícito que aquí solo se construyen
valores; una futura capa de aplicación podrá añadir persistencia sin cambiar esta
API de dominio.

### D9 — Errores explícitos y sin efectos laterales

**Chosen:** crear jerarquías en
`backend/app/properties/domain/exceptions.py` y
`backend/app/timeline/domain/exceptions.py`. Todos los mensajes técnicos estarán en
inglés, conforme a steering.

| Error | Cuándo se produce |
|---|---|
| `InvalidStateTransitionError` | origen, destino o disparador no pertenece a una flecha válida |
| `NoOperationalStateChangeError` | el destino resuelto coincide con el estado actual |
| `InvalidTransitionInputError` | falta actor, motivo, destino manual, IDs o tiempo requerido |
| `TransitionScopeMismatchError` | tenant/property de una entidad de contexto no coincide |
| `IncompatibleTransitionContextError` | el contexto no permite obtener un único estado |
| `TimelineEventValidationError` | no puede construirse un `TimelineEvent` completo y válido |
| `TransitionEvidenceError` | falla la construcción coordinada de las dos evidencias |

Los errores contienen datos estructurados mínimos (`from_state`, `to_state`,
`trigger`, IDs relevantes) y nunca objetos de infraestructura. No se traducen aquí a
códigos HTTP.

Rejected: `ValueError` genérico — impide a futuros casos de uso distinguir entrada,
regla y contexto. Rejected: errores por cada flecha del mapa — multiplicaría clases
sin aportar manejo distinto.

**Consequences:** cada rechazo es verificable y no modifica `Property`, contexto ni
metadata de entrada. La futura aplicación decidirá el mapeo externo de errores.

### D10 — API pública pequeña y sin puertos

**Chosen:** la superficie pública de dominio será:

| API | Entrada | Salida |
|---|---|---|
| `PropertyStateMachine.evaluate` | `PropertyStateChangeRequest` | `PropertyStateChangeResult` o error de dominio |
| `ContextualStateResolver.after_incident_resolution` | propiedad, contexto, instante | `PropertyOperationalState` o error de contexto |
| `ContextualStateResolver.after_cleaning_completion` | propiedad, contexto, instante | `PropertyOperationalState` o error de contexto |
| `ContextualStateResolver.validate_explicit_target` | destino, propiedad, contexto, instante | `None` o error de contexto |
| `TimelineEventFactory.create` | `TimelineEventData` | `TimelineEvent` o error de timeline |
| `TimelineEventFactory.property_state_changed` | datos de transición ya validados | `TimelineEvent` o error de timeline |

`ContextualStateResolver` se expone para tests y para evitar duplicación en futuras
políticas, pero ningún consumidor puede convertir su respuesta en un cambio de
estado sin pasar después por `PropertyStateMachine`.

Rejected: múltiples métodos públicos por disparador (`checkout()`, `block()`, etc.)
— ensancharía la API y duplicaría el pipeline. Rejected: interfaces `Protocol` — no
hay implementación alternativa ni frontera externa que las justifique.

**Consequences:** una única operación controla el cambio de estado; los demás
servicios solo calculan o construyen valores.

### D11 — Verificación TDD sobre matriz y funciones puras

**Chosen:** implementar con tests unitarios puros y sin mocks en
`backend/tests/properties/` y `backend/tests/timeline/`. Fixtures, factories y builders
de test construirán propiedades, reservas, limpiezas, incidencias, actores e
instantes; no serán seed data productivo.

La suite cubrirá:

- cada flecha de la matriz con su contexto mínimo válido;
- el producto cartesiano restante de estados origen/destino/disparador como rechazo,
  incluidos no-ops;
- check-in/checkout con override, default y zona de la vivienda, sin reloj global;
- resolución contextual en cada nivel de precedencia y sus fronteras temporales;
- contexto incompleto, solapado, cross-tenant y cross-property;
- HIGH→CRITICAL, CRITICAL→HIGH y resolución con otras incidencias activas;
- bloqueo, fuera de servicio, reactivación y desbloqueo con actor/destino/motivo
  presentes y ausentes;
- igualdad de resultados para la misma entrada completa y diferencia al cambiar
  estado, entrada, contexto, actor o instante;
- correlación y coherencia de todos los campos de las dos evidencias;
- imposibilidad de recibir una evidencia parcial ante cualquier error;
- reutilización de `TimelineEventFactory` para un evento no asociado a transición;
- imports de los nuevos módulos sin SQLAlchemy, FastAPI, Pydantic, Celery o Redis.

La cobertura objetivo para estos servicios de dominio será al menos 80 %, con
cobertura explícita del 100 % de flechas válidas e inválidas exigida por PRD §28.19.

Rejected: tests de integración con PostgreSQL — este change no toca persistencia.
Rejected: mockear la state machine o el resolver — son las unidades reales que se
deben verificar.

**Consequences:** `tasks.md` deberá ordenar test primero para cada grupo de
invariantes y ejecutar después la suite backend existente para detectar regresiones.

## Domain components and responsibilities

| Component | Responsibility | Must not do |
|---|---|---|
| `PropertyStateMachine` | Orquestar validación, resolución, matriz y resultado compuesto | Mutar entidades, consultar datos, autorizar o persistir |
| `TransitionPolicy` | Contener la matriz exacta y validar origen/disparador/destino | Resolver tiempo o leer contexto externo |
| `ContextualStateResolver` | Calcular y validar estados dependientes de contexto | Aplicar el cambio o producir evidencias |
| `TimelineEventFactory` | Aplicar reglas comunes y construir eventos completos | Decidir workflows o persistir eventos |
| Value objects | Transportar entrada y salida inmutables | Ejecutar I/O o esconder defaults temporales |
| Domain errors | Expresar rechazos verificables | Conocer HTTP, ORM o UI |

## Domain invariants

1. Todo estado recibido o producido pertenece al enum canónico de 11 valores.
2. Ningún cambio aceptado evita `PropertyStateMachine`; el resolver por sí solo no
   cambia estado.
3. Una transición requiere una flecha de PRD §8.1, un disparador compatible y todas
   sus precondiciones.
4. Un no-op nunca produce `PropertyStateTransition` ni
   `PROPERTY_STATE_CHANGED`.
5. Todo tiempo usado en una decisión se deriva del instante explícito y de datos de
   entrada; no existe reloj global.
6. Todo contexto pertenece al mismo tenant y propiedad y permite una única decisión.
7. Toda acción manual requerida lleva actor `USER` identificable y motivo no vacío;
   el dominio no decide permisos.
8. Salir de `BLOCKED_BY_OWNER` exige destino explícito y nunca restaura el estado
   anterior.
9. Una aceptación devuelve exactamente una `PropertyStateTransition` y un
   `TimelineEvent(PROPERTY_STATE_CHANGED)` correlacionados; un rechazo devuelve
   ninguna evidencia.
10. Las entradas y entidades existentes no se mutan.
11. La misma entrada completa produce el mismo resultado lógico y los mismos campos.
12. Persistencia, deduplicación durable y `AuditLog` no forman parte de esta decisión
    de dominio.

## Complete transition flow

1. El caller aplica RBAC y reúne `Property`, contexto, actor, instante, IDs y
   correlación.
2. Construye `PropertyStateChangeRequest`; no hay consulta desde el dominio.
3. `PropertyStateMachine` valida IDs, tiempo, actor, motivo y scope tenant/property.
4. La policy determina si el disparador admite un destino fijo o contextual desde el
   estado actual.
5. `ContextualStateResolver` calcula o valida el destino cuando corresponde.
6. La policy valida la flecha final y rechaza el no-op.
7. Se construye `PropertyStateTransition` con los datos ya validados.
8. `TimelineEventFactory.property_state_changed` construye el evento correlacionado.
9. Solo si ambas construcciones terminan se devuelve
   `PropertyStateChangeResult`; `Property` sigue intacta.
10. Fuera de este change, la futura aplicación aplicará `to_state`, persistirá las
    tres filas atómicamente y deduplicará el identificador de correlación.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Property state domain | `backend/app/properties/domain/state_machine.py` | New — `PropertyStateMachine` y policy de transición |
| Contextual resolution | `backend/app/properties/domain/state_resolution.py` | New — resolución pura de incidencias, limpieza y reservas |
| Property domain contracts | `backend/app/properties/domain/value_objects.py`, `transition_enums.py`, `exceptions.py` | New — solicitud, contexto, actor, IDs, resultado, disparadores y errores |
| Timeline domain | `backend/app/timeline/domain/services.py`, `value_objects.py`, `exceptions.py` | New — factory y validación común de `TimelineEvent` |
| Property domain tests | `backend/tests/properties/test_state_machine.py`, `test_state_resolution.py`, `test_transition_result.py` | New — matriz, contexto, invariantes y resultado compuesto |
| Timeline domain tests | `backend/tests/timeline/test_event_factory.py` | New — construcción común y reutilización |

No se modifica `proposal.md`, ninguna entidad o enum existente, ningún archivo bajo
`infrastructure/`, Alembic, `application/` o `api/`.

## Data & interfaces

No hay cambios de esquema, modelos SQLAlchemy, migraciones, API HTTP, eventos
externos, configuración ni variables de entorno. Los únicos contratos nuevos son
dataclasses/enums/errores Python puros descritos en D2, D3, D7, D9 y D10.

### Domain input contracts

| Contract | Required fields | Optional fields / rules |
|---|---|---|
| `PropertyStateChangeRequest` | `property`, `trigger`, `context`, `actor`, `reference_instant`, `evidence_ids` | `requested_state`, `reason`, `source_entity_id`, `reservation_id`, `correlation_id`; `requested_state` es obligatorio en desbloqueo y, si se proporciona en otro caso, debe coincidir con el destino resuelto |
| `PropertyTransitionContext` | tuplas de `reservations`, `cleaning_tasks`, `incidents` | Las tuplas pueden estar vacías; sus elementos deben corresponder al tenant y propiedad de la solicitud |
| `TransitionActor` | `triggered_by` | `user_id`; obligatorio y no nulo cuando `triggered_by=USER`, ausente para los otros orígenes |
| `TransitionEvidenceIds` | `transition_id`, `timeline_event_id` | Ambos son UUID distintos y se tratan como parte de la entrada determinista |
| `TimelineEventData` | `id`, `tenant_id`, `property_id`, `actor_type`, `event_type`, `title`, `created_at` | `reservation_id`, `actor_user_id`, `severity`, `description`, `metadata`; aplica los defaults de la entidad existente sin leer estado externo |

`PropertyStateChangeResult` contiene únicamente `transition` y `timeline_event`. Los
dos `created_at` reciben `reference_instant`; `reason` y `description` reciben el
mismo motivo; `triggered_by_user_id` y `actor_user_id` reciben el mismo `user_id`
cuando el actor es `USER`. `correlation_id`, si existe, se copia a ambos diccionarios
de metadata sin regenerar su valor y debe ser un string no vacío. `source_entity_id`
identifica la reserva, limpieza o incidencia que causó el disparador; es obligatorio
para esos disparadores, debe existir en el contexto y se omite en acciones manuales.

### Trigger preconditions

| Trigger group | Required domain evidence |
|---|---|
| Check-in window | Reserva fuente `CONFIRMED` cuya entrada corresponde a la fecha local de referencia |
| Check-in time | Reserva fuente `CONFIRMED` o `CHECKED_IN_ESTIMATED` cuyo instante efectivo de entrada ya se alcanzó y cuyo checkout no ha pasado |
| `CHECKOUT_TIME_REACHED` | Reserva fuente en `CONFIRMED` o `CHECKED_IN_ESTIMATED` cuyo `effective_check_out` ya se alcanzó; `CANCELLED`, `COMPLETED` y `NO_SHOW` se excluyen expresamente, de modo que omitir un job anterior de check-in no impida procesar el checkout |
| Reservation cancelled | Reserva fuente `CANCELLED` y referencia anterior a su instante efectivo de check-in |
| Cleaner assigned | `CleaningTask` fuente en `ASSIGNED` |
| Cleaner rejected | `CleaningTask` fuente en `REJECTED` |
| Cleaning assignment expired | `CleaningTask` fuente en `ASSIGNED` o `ACCEPTED`; el caller determina la expiración dentro de su workflow y el dominio solo valida el hecho recibido |
| Cleaning started/completed | `CleaningTask` fuente respectivamente en `IN_PROGRESS` o `COMPLETED` |
| Incident HIGH/CRITICAL | `Incident` fuente activa con la severidad correspondiente; el contexto completo confirma que el destino sigue siendo compatible |
| Incident resolved | `Incident` fuente en `RESOLVED`; el resolver considera las demás incidencias activas |
| Owner block / out of service / reactivation | Actor `USER` y motivo no vacío; origen y destino admitidos por la matriz |
| Owner/manager unblock | Actor `USER`, motivo y `requested_state` explícitos; compatibilidad contextual del destino |

Estas precondiciones validan el hecho ya detectado, no implementan el workflow que
lo detecta. La state machine no calcula ventanas programadas, expiraciones de SLA ni
autorización. Si `reservation_id` se proporciona para el timeline, debe corresponder
a una reserva del mismo contexto y scope; cuando la entidad fuente ya es una reserva,
ambos IDs deben coincidir.

### Requirement coverage

| Requirement | Design coverage |
|---|---|
| R1 | Enum existente reutilizado; validación canónica y ausencia de `DOOR_OPENED` en D3-D4 |
| R2 | Autoridad única, matriz completa, rechazo de no-op y tiempo explícito en D1-D5 |
| R3 | Disparadores comunes y separación de workflows/RBAC en D3, D4 y D6 |
| R4 | Precedencia contextual y errores de incompatibilidad en D5 |
| R5 | Actor, motivo y destino manual explícitos; sin restauración automática en D5-D6 |
| R6 | Resultado compuesto, correlación, determinismo y factory reutilizable en D2, D7-D8 |
| R7 | Solo dominio puro, nuevos archivos y tests unitarios exhaustivos en D1-D11 |

## Risks & mitigations

- **La matriz y sus condiciones pueden divergir:** una única policy declarativa y
  tests generados para todas las flechas y pares no declarados mantienen PRD §8.1
  visible y exhaustivo.
- **Contexto temporal ambiguo en cambios de día o DST:** se exige instante con zona y
  se usa la zona de `Property`; casos de cambio horario y límites exactos forman
  parte de los tests.
- **Entidades de evidencia existentes son mutables:** no pueden congelarse sin romper
  el alcance; el resultado congelado, las copias de metadata y la ausencia de
  mutaciones posteriores reducen el riesgo. Una futura modificación de esas
  entidades requeriría su change propietario.
- **La atomicidad durable no queda garantizada aquí:** el resultado compuesto impide
  éxito lógico parcial; la futura capa de aplicación deberá persistir sus tres
  efectos en una única transacción.
- **State machine adelantada a `auth-tenancy`:** el dominio exige identidad para
  acciones manuales, pero no roles ni permisos. RBAC y tenant isolation de queries
  siguen en sus changes propietarios.
- **Steering requiere `AuditLog` para cambios de estado:** este change no lo
  implementa por decisión aprobada. La salida correlacionada conserva los datos que
  necesitará el change propietario, sin anticipar su persistencia.
- **Un factory genérico de timeline podría crecer prematuramente:** su contrato se
  limita a invariantes ya presentes en `TimelineEvent`; no incorpora workflows,
  repositorios ni tipos de evento nuevos.

## Open questions

None pending — las decisiones de negocio que afectaban alcance, orden, RBAC,
correlación, `AuditLog`, seed data y salida de `BLOCKED_BY_OWNER` están resueltas en
la Proposal aprobada. Este diseño no requiere modificar contratos persistidos; si la
implementación descubriera esa necesidad, R7 exige registrar un bloqueo antes de
continuar.
