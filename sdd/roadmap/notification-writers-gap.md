# notification-writers-gap

[BE] **nueve de los diecisiete tipos de notificación no los escribe nadie**, y uno de los huecos es un
fallo de producto y no una funcionalidad pendiente.

**Censo medido (2026-08-28)**, buscando `notification_type=` sobre `backend/app/`. Con escritor de
producción: `PASSWORD_RESET_REQUESTED` (`auth/application/recovery.py`), `CLEANING_TASK_ASSIGNED` y
`CLEANING_NO_RESPONSE` (`cleaning/domain/notifications.py`), `TECHNICIAN_ASSIGNED`,
`OWNER_APPROVAL_REQUIRED` y el `INCIDENT_REJECTED` que no es de §14 (`maintenance/domain/notifications.py`),
`GUEST_ESCALATION` (`messaging/domain/notifications.py`), `SLA_BREACH` (`notifications/domain/escalation.py`)
y el `LEGAL_REGISTRATION_FAILED` que tampoco es de §14 (`guests/application/use_cases.py`).

**Sin ningún escritor**: `INCIDENT_CREATED_CRITICAL`, `INCIDENT_CREATED_HIGH`, `CLEANING_COMPLETED`,
`CLEANING_FAILED`, `TECHNICIAN_NO_RESPONSE`, `CHECKIN_REMINDER_24H`, `CHECKIN_REMINDER_2H`,
`CHECKOUT_REMINDER`, `LOCK_ALERT`. Existen en `notifications/domain/enums.py`, están cubiertos por
`tests/notifications/test_escalation.py` y no los produce nada.

**El que es un fallo y no una ausencia**: `INCIDENT_CREATED_CRITICAL` / `INCIDENT_CREATED_HIGH`. Hoy hay
tres escritores de incidencias —el portal del huésped (`POST /api/v1/guest/incident/{token}`), la
limpiadora desde su tarea (`POST /cleaning-tasks/{task_id}/incidents`, de `cleaner-incident-report`) y el
seed—, y **ninguno avisa a nadie**: un huésped puede reportar una incidencia crítica y el manager solo se
entera si abre la pantalla. Que exista `classify_incidents` cada cinco minutos no lo tapa: clasificar no es
notificar. Esto es lo que justifica la entrada por sí solo.

**Los tres siguientes por valor**: `CLEANING_COMPLETED` y `CLEANING_FAILED` cierran el lazo del manager
sobre la validación de limpieza (`POST /cleaning-tasks/{id}/complete` y `/validate` ya existen), y
`TECHNICIAN_NO_RESPONSE` es la simétrica de `CLEANING_NO_RESPONSE`, que sí está escrita — la asimetría es la
señal de que falta, no una decisión.

**Fuera de alcance, y con motivo**: los tres recordatorios al huésped (`CHECKIN_REMINDER_24H/2H`,
`CHECKOUT_REMINDER`) van a `guest-scheduled-comms`, porque no son un escritor que falta sino un job que no
existe —`send_checkin_reminders` no tiene código y `scheduler/schedule.py` lo dice por escrito— y porque no
tienen canal al huésped hasta que lo haya. `LOCK_ALERT` no entra: necesita una superficie de importación de
cerraduras que no existe (`maintenance/api/incidents_router.py` lo declara «out of scope for want of an
import surface»); esta entrada **no** la inventa, solo deja constancia de que ese tipo sigue huérfano.

**Lo que decide**: a quién va cada una (el patrón de `_managers` —managers activos, con caída al owner— ya
está en `guests/application/use_cases.py` y en `celery-jobs`, y conviene reusarlo y no derivar un tercero) y
si alguna abre plazo de SLA. Cuidado con lo último: `list_sla_breach_candidates` exige `status = SENT` y
`dispatch_notifications` es quien lo marca, así que un `sla_deadline_at` nuevo produce escalaciones reales
desde el primer minuto — a diferencia de cuando `cleaning` escribió el suyo.

---

**Entregada el 2026-08-30 (PR #138). Dos correcciones al censo de arriba, medidas y no recordadas
— el texto anterior se conserva porque es lo que motivó la entrada, no lo que resultó ser cierto:**

1. **Eran diez sin escritor, no nueve.** El que esta nota omitió es `PRICE_RECOMMENDATION`:
   `revenue-pricing` está archivado y su `GeneratePriceRecommendationsUseCase` escribía
   `TimelineEvent` y `AuditLog` y ninguna notificación, y ninguna otra entrada lo reclamaba. Entró
   en el alcance por decisión de Jose (2026-08-29).
2. **El censo de arriba mezcla los miembros del enum con los dos tipos de texto libre.**
   `INCIDENT_REJECTED` y `LEGAL_REGISTRATION_FAILED` no son miembros de `NotificationType` —viven
   sobre la columna `String(100)`—, así que no cuentan ni entre los diecisiete ni entre los
   huérfanos. Con ellos fuera, el censo de partida era **siete** con escritor y **diez** sin él.

**Lo que quedó al cerrar**: trece tipos con escritor y cuatro sin él —`LOCK_ALERT` y los tres
recordatorios al huésped, ambos grupos fuera de alcance por los motivos que esta nota ya daba—. El
sexto tipo que ganó escritor fue `TECHNICIAN_NO_RESPONSE`, que no se escribió de cero: el escalado
del técnico dejó de emitir `SLA_BREACH` y pasó a emitirlo.

**Y el censo dejó de hacerse a mano**, que es lo que produjo los dos errores de arriba:
`backend/tests/notifications/test_writer_census.py` lo mide sobre el AST de `backend/app/` y falla
si el conjunto difiere de sus listas literales en cualquier dirección, incluido un miembro nuevo
del enum que no aparezca en ninguna. Lo que decidía el último párrafo quedó así: el patrón de
destinatarios se reusó en un servicio de dominio único (`app/auth/domain/recipients.py`) en vez de
derivar otro —eran **tres** copias y no dos, y una de ellas,
`cleaning::_notify_manager_unassigned`, queda fuera de alcance y sigue en pie—, y ninguna de las
seis filas nuevas abre plazo de SLA, exactamente por el riesgo que este párrafo advertía.

Estado vivo en [`sdd/specs/access-notifications.md`](../specs/access-notifications.md) §El censo de
escritores; cómo se opera, en [`docs/access-notifications.md`](../../docs/access-notifications.md).
