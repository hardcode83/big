# Ingesta de reservas y resolución de huéspedes

## Purpose

Esta capacidad importa reservas desde CSV, sincronizaciones PMS y comandos operativos, y las
upserta dentro del tenant indicado. Usa la política compartida de resolución de huéspedes sin
convertirse en una superficie de CRUD o búsqueda de Guests.

## Requirements

### Resolución de Guest durante la ingesta

- WHEN una fila de ingesta aporta `guest_name` o `guest_email`, THE SYSTEM SHALL delegar la
  resolución a `ResolveOrCreateGuest`, conservando el mapeo DTO y los defaults propios de la
  ingesta.
- THE SYSTEM SHALL normalizar el email antes de resolverlo; un email vacío o compuesto solo por
  whitespace SHALL tratarse como ausente y no SHALL crear una identidad compartida por email.
- WHEN una fila aporta un email normalizado que ya existe en el tenant, THE SYSTEM SHALL
  reutilizar el Guest seleccionado por la política determinista compartida y no SHALL actualizar
  sus datos de contacto.
- WHEN una fila no aporta nombre ni email, THE SYSTEM SHALL conservar la reserva guest-less.
  Cuando aporta nombre sin email, SHALL crear un Guest nuevo y no SHALL hacer matching por nombre
  o teléfono.
- THE SYSTEM SHALL mantener `tenant_id` explícito en cada lookup, lock y escritura; una fila de
  un tenant SHALL NOT resolver ni reutilizar Guests de otro tenant.

### Atomicidad y concurrencia

- WHEN dos transacciones del mismo tenant resuelven el mismo email normalizado, THE SYSTEM SHALL
  serializar el segundo lookup y la creación mediante la exclusión transaccional compartida, de
  modo que ambas obtengan el mismo `guest_id`.
- THE SYSTEM SHALL adquirir el lock inmediatamente antes del segundo lookup y la creación,
  omitirlo cuando no hay email y mantenerlo hasta el commit o rollback de la UoW exterior.
- THE SYSTEM SHALL procesar cada lote dentro de la UoW del llamante sin commits intermedios; si
  falla una operación de una fila o del lote, SHALL aplicar el rollback definido por la ingesta y
  no SHALL dejar escrituras parciales de Guest, Reservation o eventos.
- THE SYSTEM SHALL registrar únicamente métricas técnicas de espera del lock, sin email, nombre,
  teléfono, identificadores de Guest ni otra PII.

### Evidencia de timeline en el camino de actualización

- WHEN `ReservationIngestor` encuentra una reserva existente y `update_details()` aplica al
  menos un cambio sobre `INGEST_OWNED_FIELDS`, THE SYSTEM SHALL registrar un `TimelineEvent`
  para esa reserva, en la misma unidad de trabajo, antes de contar la fila como `updated`.
- WHEN el conjunto de cambios aplicados deja `status` en `CANCELLED` sin que lo estuviera antes,
  THE SYSTEM SHALL usar `TimelineEventType.RESERVATION_CANCELLED`; para cualquier otro conjunto
  de cambios aplicados, THE SYSTEM SHALL usar `TimelineEventType.RESERVATION_UPDATED` — la misma
  regla de selección que la edición/cancelación manual vía API.
- THE SYSTEM SHALL fijar `actor_type`/`actor_user_id`/`source` del evento emitido a partir de
  los mismos parámetros de `ingest()` que ya determinan el actor de `RESERVATION_IMPORTED`
  (`SYSTEM` para sync PMS y re-read de webhook, `USER` para CSV reimportado), sin introducir un
  actor o un `source` nuevos.
- THE SYSTEM SHALL registrar en el `metadata` del evento el resultado de `update_details()`
  (`{"changed": <dict>}`) sin recomputar el diff.
- WHEN `update_details()` no aplica ningún cambio (la fila ya coincide con la fuente), THE
  SYSTEM SHALL mantener la fila contada como `skipped` y SHALL NOT registrar ningún
  `TimelineEvent` para ella — el timeline es evidencia de cambio, no de sondeo.
- WHEN el evento emitido es `RESERVATION_CANCELLED` y la vivienda de esa reserva está en
  `AWAITING_CHECKIN` esperando precisamente esa estancia, THE SYSTEM SHALL disparar
  `PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN` para esa reserva una sola vez por
  lote de ingesta, independientemente de cuántas filas del lote cancelaron una reserva.
- THE SYSTEM SHALL NOT disparar dos veces la misma transición de propiedad para la misma
  cancelación: el re-read de webhook conserva su propia llamada a la transición tras su propio
  commit, y la re-evaluación posterior no encuentra candidatos porque la propiedad ya salió de
  `AWAITING_CHECKIN`.
- THE SYSTEM SHALL serializar, mediante un lock transaccional por `(tenant_id,
  external_pms_id)`, la decisión de crear-vs-actualizar de dos transacciones de ingesta
  concurrentes sobre la misma reserva PMS, para que no puedan emitir cada una su propio
  `RESERVATION_CANCELLED`/`PropertyStateTransition` para la misma cancelación.
- THE SYSTEM SHALL seguir contando una fila como `updated` exactamente cuando `update_details()`
  aplica cambios, y como `skipped` exactamente cuando no los aplica, independientemente de si se
  emitió un `TimelineEvent`.

### Alcance de writers

- THE SYSTEM SHALL aplicar esta política a `ReservationIngestor` para las vías PMS y CSV, además
  de sus composition roots operativas, y SHALL mantener fuera el Guest Portal sin email y el
  seed controlado que no pertenece a este writer path.
- THE SYSTEM SHALL mantener el informe de ingesta —creadas, actualizadas, omitidas y errores—
  independiente de la resolución compartida.

La política general de identidad y sus límites de esquema están en
[`domain-foundation-core.md`](domain-foundation-core.md); el contrato HTTP de alta manual está
en [`reservations.md`](reservations.md).

## Key files

- `backend/app/integrations/application/ingest.py` — `ReservationIngestor` y `_link_guest`.
- `backend/app/integrations/domain/dtos.py` — DTO de reserva ingerida.
- `backend/app/guests/application/resolution.py` — resolver compartido.
- `backend/app/guests/infrastructure/postgres_guest_email_exclusion.py` — lock PostgreSQL.
- `backend/app/integrations/domain/ports.py` — `ReservationIngestLock`, `PropertyStateAdvancer`.
- `backend/app/integrations/infrastructure/postgres_reservation_ingest_lock.py` — lock
  PostgreSQL por `(tenant_id, external_pms_id)`.
- `backend/app/integrations/{api,cli}/` — composition roots de CSV y sync PMS.
