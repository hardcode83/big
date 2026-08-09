# Timeline state machine

## Purpose

Esta capacidad aplica de forma determinista la política de estado operacional de
una propiedad y construye las evidencias correlacionadas para su timeline. Recibe
todo el contexto como datos explícitos y permanece en el dominio: no lee reloj,
base de datos, red ni servicios externos, ni persiste o muta la propiedad.

**Dónde se persisten sus eventos**: el puerto `TimelineEventRepository`
(`app/timeline/domain/repositories.py`) y su adaptador SQLAlchemy los añaden a
`timeline_events`, y los escribe cada capacidad que muta algo — la primera fue
`reservations` (ver `specs/reservations.md`). El puerto expone únicamente `add`, que es la
regla "nunca se editan eventos pasados" expresada en una firma, y rechaza un `metadata` que
la columna `JSONB` no pueda almacenar. Construir el evento sigue siendo exclusivamente
competencia de la fábrica que esta capacidad define.

**Quién la conduce**: desde `celery-jobs` esta política tiene ejecutor. Su
`AdvancePropertyStatesUseCase` (`app/properties/application/use_cases.py`) es el primer y
único escritor de `current_operational_state` y de `property_state_transitions`: pregunta a
`PropertyStateMachine` por cada reserva candidata, y cuando acepta persiste el estado, la
transición y el `TimelineEvent` en una sola transacción con el `correlation_id` que esta
capacidad produce. La política sigue sin tocar reloj, base de datos ni red — lo que cambió es
que ya no evalúa en el vacío (ver `specs/celery-jobs.md`).

**Qué no es una transición de estado de propiedad**: `access-notifications` trajo la máquina de
estados del `AccessRecord` y la del registro legal de la reserva, y ninguna de las dos pasa por
aquí. La regla «un único lugar donde ocurren las transiciones» habla del estado operacional de la
*propiedad*; el ciclo de vida de un acceso o de una presentación ante SES.Hospedajes es de su
entidad, vive en ella y no toca `current_operational_state`. Lo que sí comparten es la fábrica:
sus eventos (`ACCESS_CODE_PENDING`, `ACCESS_CODE_MANUAL_ADDED`, `ACCESS_CODE_CREATED_EXTERNAL`,
`ACCESS_CODE_DELIVERED`, `LEGAL_REGISTRATION_SUBMITTED`) se construyen por ella como cualquier
otro. Revocar y expirar un acceso **no** escriben evento: PRD §15 no declara ninguno y la fila de
`AuditLog` es la que lo registra.

## Requirements

### Estados canónicos y autoridad única

- WHEN se evalúa una solicitud, THE SYSTEM SHALL aceptar y producir únicamente
  los estados de `PropertyOperationalState`.
- WHEN el origen, trigger, destino solicitado o precondición no coincide con la
  matriz de transición aprobada, THE SYSTEM SHALL rechazar la solicitud sin
  modificar entradas ni producir evidencias de éxito.
- WHEN el destino coincide con el estado actual, THE SYSTEM SHALL rechazarlo como
  ausencia de cambio operacional.
- WHEN la solicitud depende del tiempo, THE SYSTEM SHALL recibir un instante de
  referencia explícito.

### Triggers operacionales

- WHEN se soliciten cambios de reservas, limpieza, incidencias, bloqueo,
  fuera-de-servicio, reactivación o desbloqueo, THE SYSTEM SHALL validar el
  trigger semántico, su entidad fuente y sus precondiciones antes de evaluar la
  transición.
- WHEN una operación manual requiera actor, THE SYSTEM SHALL exigir un actor
  `USER` con `user_id` y un motivo no vacío; la autorización RBAC SHALL permanecer
  fuera del dominio.
- WHEN se desbloquee `BLOCKED_BY_OWNER`, THE SYSTEM SHALL exigir destino explícito
  y validar ese destino contra el contexto actual; no SHALL restaurar un estado
  histórico automáticamente.

### Resolución contextual y precedencia

- WHEN se resuelva una incidencia, THE SYSTEM SHALL aplicar exactamente esta
  precedencia: incidencia activa `CRITICAL`, incidencia activa `HIGH`, limpieza
  `IN_PROGRESS`, limpieza `CREATED`/`ASSIGNED`/`ACCEPTED`, reserva activa,
  próxima reserva hoy, próxima reserva futura y, finalmente, `VACANT_READY`.
  **Los dos escalones de limpieza se ejercitan con datos reales desde `cleaning`**
  (2026-08-07): hasta entonces nadie escribía en `cleaning_tasks`, así que la
  precedencia veía siempre «sin limpieza pendiente» y esas dos ramas —y con ellas
  las cinco transiciones de limpieza de la política— nunca se recorrían fuera de
  los tests. El conjunto de estados que cuentan como limpieza viva vive ahora en
  un solo sitio (`LIVE_STATUSES`), y el índice parcial que lo usa se compara con
  él en un test para que no puedan divergir.
- WHEN no exista incidencia `CRITICAL`, THE SYSTEM SHALL producir
  `MAINTENANCE_REQUIRED` si existe una incidencia `HIGH` activa.
- WHEN se valide un destino contextual explícito, THE SYSTEM SHALL rechazarlo si
  no es el estado derivado por la precedencia del contexto entregado.
- WHEN el contexto sea de otro tenant o propiedad, sea incompleto, ambiguo o
  contenga reservas activas incompatibles, THE SYSTEM SHALL producir un error de
  dominio explícito.
- WHEN una limpieza se complete, THE SYSTEM SHALL producir únicamente
  `READY_FOR_NEXT_GUEST`, `AWAITING_CHECKIN` o `VACANT_READY`; una reserva activa
  en ese punto SHALL ser contexto incompatible y no SHALL producir
  `OCCUPIED_ESTIMATED`.
- WHEN un desbloqueo solicite `CLEANING_SCHEDULED`, THE SYSTEM SHALL exigir que la
  precedencia no requiera un estado de incidencia y que exista exactamente una
  tarea `ASSIGNED` o `ACCEPTED`.

### Tiempo local y DST

- WHEN se materialice una hora local con la zona de la propiedad, THE SYSTEM SHALL
  rechazar una hora inexistente durante el salto de primavera.
- WHEN una hora local sea repetida durante el salto de otoño, THE SYSTEM SHALL
  exigir una zona consciente y `fold=0` o `fold=1` para seleccionar explícitamente
  la ocurrencia; no SHALL normalizar silenciosamente.
- WHEN una hora no sea ambigua, THE SYSTEM SHALL evaluarla de forma determinista
  y comparar instantes efectivos en UTC.

### Resultado de transición y timeline

- WHEN una transición sea aceptada, THE SYSTEM SHALL devolver conjuntamente un
  `PropertyStateTransition` y un `TimelineEvent` de tipo
  `PROPERTY_STATE_CHANGED`.
- WHEN se construyan ambas evidencias, THE SYSTEM SHALL conservar tenant,
  propiedad, estados, actor, motivo, instante y `correlation_id` compartidos, y
  SHALL construir metadata independiente sin referencias mutables compartidas.
- IF cualquiera de las dos evidencias no puede construirse, THEN THE SYSTEM SHALL
  fallar de forma all-or-nothing y no SHALL devolver evidencia parcial.
- WHEN se repita una evaluación con entradas idénticas, THE SYSTEM SHALL producir
  el mismo resultado lógico sin mutar la solicitud ni el contexto.

### Factory de eventos

- WHEN `TimelineEventFactory.create` reciba datos, THE SYSTEM SHALL validar en
  runtime UUIDs, enums, campos obligatorios, fecha consciente, metadata y la
  coherencia entre `actor_type` y `actor_user_id`.
- WHEN `TimelineEventFactory.property_state_changed` reciba una transición,
  trigger o evidencia inválida, THE SYSTEM SHALL rechazarla con
  `TimelineEventValidationError`; no SHALL escapar `KeyError`, `ValueError` ni
  errores genéricos de entrada.
- WHEN se acepten datos de timeline, THE SYSTEM SHALL usar los tipos de dominio
  reales y no SHALL convertir strings UUID arbitrarios ni introducir validación de
  infraestructura.

### Pureza y verificación

- WHEN se importe esta capacidad, THE SYSTEM SHALL depender únicamente de código
  de dominio y tipos de contrato existentes; no SHALL importar SQLAlchemy,
  FastAPI, Pydantic, Celery, Redis ni adaptadores externos.
- WHEN se verifique la matriz, THE SYSTEM SHALL cubrir cada relación válida y
  destinos inválidos relevantes, incluidas variantes multidestino, determinismo,
  correlación y ausencia de mutación, mediante tests unitarios sin base de datos ni
  red.

## Key files

- `backend/app/properties/domain/state_machine.py` — autoridad de evaluación y
  matriz de triggers.
- `backend/app/properties/domain/state_resolution.py` — precedencia contextual,
  validación de destinos y política temporal.
- `backend/app/properties/domain/value_objects.py` — solicitudes, actores,
  contexto y resultado correlacionado.
- `backend/app/properties/domain/transition_enums.py` — triggers semánticos.
- `backend/app/timeline/domain/services.py` — `TimelineEventFactory` y eventos de
  cambio de estado.
- `backend/app/timeline/domain/value_objects.py` — contrato de entrada del factory.
- `backend/app/timeline/domain/exceptions.py` — errores estables de validación.
- `backend/tests/properties/` y `backend/tests/timeline/` — verificación unitaria
  exhaustiva de la política y del factory.
