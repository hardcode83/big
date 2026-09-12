# Proposal: pms-ingest-change-events

## Why

`sdd/roadmap.md` entry `pms-ingest-change-events` (hito «MVP operable» 3), con su nota en
`sdd/roadmap/pms-ingest-change-events.md`. El hecho medido (2026-09-04) ahí documentado:
`ReservationIngestor._ingest_row` (`backend/app/integrations/application/ingest.py:222-239`)
tiene dos caminos. Al **crear** escribe la reserva y un `TimelineEvent` `RESERVATION_IMPORTED`
(`_record_imported`, :296-327). Al **actualizar** (:229-239) calcula `changes` sobre
`INGEST_OWNED_FIELDS` (`reservations/domain/entities.py:63-81` — incluye `status`,
`check_in_date`, `check_out_date`, importes), llama `existing.update_details(changes, now=now)` y
`save`, cuenta `updated += 1`, y **no emite ningún evento**. Una cancelación que llega de Beds24
(el adapter pide explícitamente `cancelled` vía `modifiedFrom`) pasa por ahí exactamente igual
que un cambio de fechas: fila actualizada, timeline mudo.

`sdd/specs/reservations.md` ("Edición y cancelación") ya promete evidencia de cancelación y de
edición, pero solo para los caminos HTTP (`PATCH`/`DELETE`) — `use_cases.py:294-325` (`PATCH`) y
`:342-376` (`DELETE`/`CancelReservationUseCase`) ya resuelven exactamente este problema para esos
dos escritores: comparan `status` antes/después de `update_details()` y emiten
`TimelineEventType.RESERVATION_CANCELLED` cuando la reserva queda `CANCELLED`,
`RESERVATION_UPDATED` en cualquier otro cambio aplicado, con `metadata={"changed": <dict>}`. Los
tres escritores del camino de ingest — sync periódico (`pms-sync-schedule`, cada 6 h desde hoy),
webhook re-read y CSV — no tienen ese mismo reflejo.

Tampoco es solo el evento de reserva: `RESERVATION_CANCELLED_BEFORE_CHECKIN` (el trigger que
devuelve la vivienda de `AWAITING_CHECKIN` a `VACANT_READY`, `state_machine.py:39`) lo dispara hoy
un único sitio — el procesador de webhooks (`integrations/application/webhooks.py:568-575`), tras
su propio re-read, y solo para ese camino. El sync periódico y el CSV cancelan la reserva sin
disparar nunca esa transición: la vivienda queda esperando a un huésped que ya no llega.

Con `pms-sync-schedule` corriendo cada 6 h, este hueco deja de ser un caso de laboratorio y pasa a
ser diario — es la razón por la que este change va justo detrás en el roadmap (`needs:
pms-sync-schedule`). `steering/product.md` principio 1 (*toda transición genera TimelineEvent
auditable*) y el dashboard del owner dependen de que un cambio de fechas o una cancelación por
PMS **se vean**.

## What changes

El camino de actualización de `ReservationIngestor._ingest_row` gana el mismo reflejo que el
`PATCH`/`DELETE` manual ya tiene: cuando `update_details()` aplica cambios, se emite
`RESERVATION_CANCELLED` (si el estado resultante es `CANCELLED` y no lo era antes) o
`RESERVATION_UPDATED` (en cualquier otro cambio aplicado), con la misma forma de metadata
(`{"changed": <dict>}`) y el mismo `actor_type`/`source` que ya usa `_record_imported` para
`RESERVATION_IMPORTED` — sin inventar vocabulario nuevo, porque `RESERVATION_UPDATED` y
`RESERVATION_CANCELLED` ya existen en `TimelineEventType` y ya resuelven esta selección en el
camino manual. Cuando ese evento representa una cancelación, la transición de vivienda
`RESERVATION_CANCELLED_BEFORE_CHECKIN` se dispara **una sola vez** desde ese mismo punto para las
tres rutas (sync, webhook re-read, CSV) — el `design.md` decide si eso significa mover la llamada
que hoy vive en `webhooks.py:568-575` al ingestor o convertirla en llamante de la misma pieza, pero
en ningún caso quedan dos disparadores independientes para la misma cancelación. Un sync o un
re-read sin cambios reales (`update_details()` devuelve `False`) sigue sin emitir nada — la prueba
de idempotencia vigente (`ingest.py`, fila repetida cuenta `skipped`, no `updated`) no cambia.

## Requirements

### R1 — El camino de actualización del ingest emite evidencia del cambio

**As a** gestora de la propiedad que lee `/timeline`, **I want** que una reserva modificada por
sync PMS, re-read de webhook o reimportación CSV deje un `TimelineEvent`, **so that** un cambio
que no hice yo en la app siga siendo visible.

Acceptance criteria:

1. WHEN `ReservationIngestor._ingest_row` encuentra una reserva existente y
   `existing.update_details(changes, now=now)` aplica al menos un cambio sobre
   `INGEST_OWNED_FIELDS`, THE SYSTEM SHALL registrar un `TimelineEvent` para esa reserva en la
   misma unidad de trabajo, antes de que el informe la cuente como `updated`.
2. WHEN el conjunto de cambios aplicados deja `status` en `CANCELLED` sin que lo estuviera antes
   de aplicar el cambio, THE SYSTEM SHALL usar `TimelineEventType.RESERVATION_CANCELLED`; para
   cualquier otro conjunto de cambios aplicados, THE SYSTEM SHALL usar
   `TimelineEventType.RESERVATION_UPDATED` — la misma regla de selección que
   `use_cases.py:294-319` ya aplica al `PATCH` manual.
3. THE SYSTEM SHALL fijar `actor_type`/`actor_user_id`/`source` del evento emitido a partir de
   los mismos parámetros de `ingest()` que hoy usa `_record_imported` para `RESERVATION_IMPORTED`
   (`PMS_SOURCE`, `WEBHOOK_SOURCE`, `SCHEDULED_SOURCE` con actor `SYSTEM`; `CSV_SOURCE` con actor
   `USER`), sin introducir un actor o un `source` nuevos.
4. THE SYSTEM SHALL registrar en el `metadata` del evento qué campos cambiaron, con la misma
   forma (`{"changed": <dict de update_details>}`) que ya usa el `PATCH` manual.

### R2 — Sin cambio aplicado, sin evento

**As a** operador que vigila el timeline para ver cambios reales, **I want** que un ciclo de sync
o de re-read que no encontró nada nuevo no deje rastro, **so that** el timeline siga siendo
evidencia de cambio y no de sondeo.

Acceptance criteria:

1. WHEN `existing.update_details(changes, now=now)` no aplica ningún cambio (los valores de la
   fila ya coinciden con los de la fuente), THE SYSTEM SHALL mantener la fila contada como
   `skipped`, exactamente como hoy, y THE SYSTEM SHALL NOT registrar ningún `TimelineEvent` para
   esa fila.
2. WHEN dos rutas de ingest (p. ej. sync periódico y re-read de webhook) procesan la misma
   reserva dentro de la misma ventana y la segunda no encuentra nada que la primera no haya
   dejado ya aplicado, THE SYSTEM SHALL apoyarse en la detección de no-op de
   `update_details()` para que la segunda pasada no emita un evento duplicado.

### R3 — La cancelación por ingest libera la vivienda una sola vez, en las tres rutas

**As a** propietaria de la vivienda, **I want** que una cancelación que llega del PMS libere el
calendario de la vivienda igual que una cancelación hecha en la app, **so that**
`AWAITING_CHECKIN` no se quede esperando a un huésped que ya canceló.

Acceptance criteria:

1. WHEN el evento de R1.2 es `RESERVATION_CANCELLED` y la vivienda de esa reserva está en
   `AWAITING_CHECKIN` esperando precisamente esa estancia, THE SYSTEM SHALL disparar
   `PropertyStateTrigger.RESERVATION_CANCELLED_BEFORE_CHECKIN` para esa reserva desde el mismo
   punto que emite R1, para las tres rutas de ingest (sync, webhook re-read, CSV).
2. WHEN esta transición ya se dispara para una cancelación detectada por el camino de ingest, THE
   SYSTEM SHALL NOT disparar una segunda vez la misma transición para la misma cancelación desde
   otro llamante — el disparo que hoy hace `webhooks.py:568-575` tras su propio re-read se
   retira o se convierte en llamante de la misma pieza que R3.1 introduce (lo decide
   `design.md`), pero nunca coexisten dos disparadores independientes escribiendo dos
   `PropertyStateTransition` para una sola cancelación.
3. WHEN la cancelación llega por el sync periódico (`pms-sync-schedule`) o por CSV — las dos
   rutas que hoy no disparan nunca esta transición — THE SYSTEM SHALL dispararla igual que ya lo
   hace hoy el camino de webhook, cerrando el hueco para esas dos rutas específicamente.

### R4 — El CSV reimportado es una ruta de modificación de primera clase

**As a** operador que corrige datos con un CSV reimportado, **I want** que una corrección de
fechas, estado o importes aparezca en el timeline igual que cualquier otra modificación,
**so that** el rastro de auditoría no dependa de por qué puerta entró el cambio.

Acceptance criteria:

1. WHEN una fila CSV coincide por `external_pms_id` con una reserva existente y cambia campos de
   `INGEST_OWNED_FIELDS`, THE SYSTEM SHALL aplicar las reglas de R1 con `actor_type=USER` y
   `source=CSV_SOURCE` — el mismo par que ya usa hoy la llamada a `ingest()` del importador CSV
   para las filas que crea.

### R5 — Un cambio de fechas sobre una vivienda ya en `AWAITING_CHECKIN` deja rastro

**As a** gestora de la propiedad, **I want** que un cambio de fechas de una reserva cuya vivienda
ya está en ventana de check-in quede visible, **so that** no descubra una `AWAITING_CHECKIN`
obsoleta por accidente.

Acceptance criteria:

1. WHEN una modificación por ingest cambia `check_in_date` o `check_out_date` de una reserva cuya
   vivienda está en `AWAITING_CHECKIN` para esa misma estancia, THE SYSTEM SHALL emitir el evento
   de R1 (`RESERVATION_UPDATED`) como evidencia del cambio de fechas.
2. THE SYSTEM SHALL NOT requerir un nuevo `PropertyStateTrigger` para este caso en este change —
   no existe hoy un trigger «ventana cerrada» en `transition_enums.py` y añadir uno queda fuera
   de alcance (ver «Fuera de alcance»).

### R6 — El conteo del informe de ingest no cambia de significado

**As a** desarrollador que depende de `IngestReport`, **I want** que `created`/`updated`/`skipped`
sigan significando exactamente lo mismo que hoy, **so that** el CLI y los tests existentes no se
rompan al añadir eventos.

Acceptance criteria:

1. WHEN este change se despliega, THE SYSTEM SHALL seguir contando una fila como `updated`
   exactamente cuando `update_details()` aplica cambios, y como `skipped` exactamente cuando no
   los aplica — sin cambios respecto a hoy, independientemente de si se emitió un
   `TimelineEvent`.

## Out of scope

- **Nuevas columnas en `Reservation`**: sin cambios de esquema.
- **El evento «reserva creada en el PMS»**: ya existe (`RESERVATION_IMPORTED`); este change solo
  toca el camino de actualización.
- **Un nuevo `PropertyStateTrigger` «ventana de check-in cerrada»**: la nota de roadmap lo deja
  como opción para el MVP y recomienda no añadirlo; R5 se resuelve con el evento como evidencia,
  sin trigger nuevo. Si la verificación muestra que hace falta más que evidencia (p. ej. que
  `blocked-transitions` no recoge el caso), eso es un gap para nombrar en el design o en una
  entrada de roadmap aparte, no algo que este change deba resolver a ciegas.
- **`CHECKED_IN_ESTIMATED`/`COMPLETED` sin escritor propio** (`specs/reservations.md:213-218`):
  candidata aparte del roadmap, `reservation-lifecycle-writers`.
- **Instrumentar el crédito real de Beds24** o **reactivar su cuenta de medición**: fuera de este
  change por completo (pertenece a `beds24-webhook-cutover-measurement`).
- **Mensajería OTA**: pertenece a `beds24-messaging-adapter`.

## Affected specs

- `sdd/specs/ingest.md` — nueva sección de evidencia de timeline para el camino de actualización
  (hoy la spec solo cubre resolución de Guest, atomicidad y alcance de writers).
- `sdd/specs/reservations.md` — la promesa de "Edición y cancelación" (`RESERVATION_CANCELLED`
  sin excepción, evidencia de edición) se extiende de "solo caminos HTTP" a "también los tres
  caminos de ingest".
- `sdd/specs/reservations-webhooks.md` — si el design mueve el disparo de
  `RESERVATION_CANCELLED_BEFORE_CHECKIN` fuera de `webhooks.py`, se documenta ahí quién lo posee
  ahora (hoy esa llamada no está descrita en ninguna spec).
