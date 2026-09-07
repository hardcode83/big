# pms-ingest-change-events

[BE] **una modificación o cancelación que llega del PMS actualiza la fila en silencio**.

> Hito «MVP operable» 3 — *autoservicio del tenant* (auditoría del 2026-09-04). Va detrás de
> `pms-sync-schedule`, que es lo que convierte este hueco en diario.

**El hecho medido (2026-09-04)**: `ReservationIngestor._ingest_row`
(`backend/app/integrations/application/ingest.py:211-261`) tiene dos caminos. Al **crear**
(:230-261) escribe la reserva y un `TimelineEvent` `RESERVATION_IMPORTED` (:289-320). Al
**actualizar** (:218-228) calcula `changes` sobre los `INGEST_OWNED_FIELDS`
(`reservations/domain/entities.py:63-81`) —que incluyen `status`, `check_in_date`,
`check_out_date`, importes—, aplica `update_details` + `save`, cuenta `updated += 1`, y **no
emite ningún evento**. Una cancelación que llega de Beds24 (el adapter consulta por
`modifiedFrom` y pide explícitamente `cancelled`, `beds24/adapter.py:41-68`) pasa por ahí:
`changes["status"]` (:345-346), fila a `CANCELLED`, timeline mudo. `specs/reservations.md:226-228`
promete que «una reserva no puede acabar `CANCELLED` sin su evento de cancelación» — **sólo para
los caminos de API**. Y `RESERVATION_CANCELLED_BEFORE_CHECKIN`, el trigger que devuelve la
vivienda de `AWAITING_CHECKIN` a `VACANT_READY` (`state_machine.py:39`), lo emite hoy un único
sitio: el procesador de webhooks (`integrations/application/webhooks.py:575`), que reutiliza el
mismo `SyncReservationsFromPmsUseCase` pero con un post-proceso propio.

**Por qué no es cosmético**: el principio 1 de `steering/product.md` —*toda transición genera
TimelineEvent auditable*— y el dashboard del owner (*¿qué pasa y quién tiene la próxima
acción?*) dependen de que un cambio de fechas o una cancelación **se vean**. Hoy una cancelación
por sync deja la reserva cancelada, la vivienda quizá en `AWAITING_CHECKIN` esperando a nadie, y
ni una línea en `/timeline`. Con `pms-sync-schedule` cada 6 h, eso deja de ser un caso de
laboratorio.

**Alcance**: en el camino de actualización del ingestor, emitir eventos por clase de cambio y
disparar la transición de vivienda cuando corresponda, **una sola vez y en el mismo sitio** para
las tres rutas (sync, webhook, CSV) — hoy el webhook lo hace aparte y el sync no lo hace.

**Lo que decide y no es cosmético**:

1. **Qué vocabulario.** `TimelineEventType` tiene `RESERVATION_IMPORTED` y los de cancelación
   del camino de API; comprobar si existen `RESERVATION_MODIFIED`/`RESERVATION_DATES_CHANGED` o
   hay que añadirlos (PRD §7.8 lista el vocabulario; el enum es canónico, `sdd/project.md`
   §Conventions). Recomendación: un evento por **clase** (fechas, estado, importes/ocupantes),
   no por campo, con `description=None` como los otros 14 constructores del árbol
   (`timeline-description-sink-census` explica por qué).
2. **Mover el post-proceso del webhook al ingestor.** `webhooks.py:575` decide
   `RESERVATION_CANCELLED_BEFORE_CHECKIN` a partir del resultado del sync. Si el ingestor emite
   la transición, ese código se retira o se convierte en llamante; dos escritores del mismo
   trigger sobre la misma fila es un doble evento. El design lo decide y el spec de
   `reservations-webhooks` se enmienda.
3. **Cambio de fechas sobre una vivienda ya en `AWAITING_CHECKIN`**: la ventana de check-in se
   abrió para unas fechas que ya no son. No hay trigger «ventana cerrada» en la matriz
   (`transition_enums.py`, 16 triggers). Opciones: declararlo como estancamiento visible en
   `blocked-transitions` (ya existe el mecanismo) o añadir trigger. Recomendación MVP: lo primero,
   con el evento de modificación como pista.
4. **CSV re-importado** también es «modificación»: mismo camino, mismos eventos, actor `USER`.
   Que el design lo pruebe.
5. **Idempotencia**: un sync sin cambios sigue siendo `skipped` sin evento (`ingest.py:66-72`
   es la prueba vigente y no debe romperse).

**Fuera de alcance**: nuevas columnas en `Reservation`; el evento «reserva creada en el PMS» ya
existe (`RESERVATION_IMPORTED`); `CHECKED_IN_ESTIMATED`/`COMPLETED`, que siguen sin escritor
propio (`specs/reservations.md:213-218`) — candidata aparte, `reservation-lifecycle-writers`.

**Verificación**: seed con `MOCK`, modificar a mano la fecha de salida de `SEED-AIRBNB-1` en el
adapter mock (o fixture), `make pms-sync` → `updated: 1`, un evento nuevo en `/timeline` de
REDES11; cancelar `SEED-BOOKING-1` → reserva `CANCELLED`, evento, y REDES11 no se queda en
`AWAITING_CHECKIN` si estaba ahí.
