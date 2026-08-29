# Design: notification-writers-gap

## Context

La maquinaria de notificaciones está entera y sólo le faltan escritores. `NotificationLog`
(`backend/app/notifications/domain/entities.py`) se escribe por un único puerto,
`NotificationLogRepository.add` (`notifications/domain/repositories.py`), que hace `flush()`
inmediato; `dispatch_notifications` drena `PENDING → SENT` cada minuto
(`notifications/application/use_cases.py::DispatchPendingNotificationsUseCase`) y
`InAppNotificationAdapter` entrega los `IN_APP` sin salir del proceso. El contenido lo componen
**builders puros** por dominio —`cleaning/domain/notifications.py`,
`maintenance/domain/notifications.py`, `messaging/domain/notifications.py`— y la política de
escalado vive aparte, sin reloj ni sesión, en `notifications/domain/escalation.py`.

Los cinco casos de uso que este change toca ya commitean una transacción cada uno:
`ClassifyIncidentUseCase` (`maintenance/application/use_cases.py:1050`) y
`TriageIncidentUseCase` (`:1332`), `CompleteCleaningTaskUseCase`
(`cleaning/application/use_cases.py:1075`) y `ValidateCleaningTaskUseCase` (`:1132`), y
`GeneratePriceRecommendationsUseCase` (`pricing/application/use_cases.py:391`), que commitea
**una vez por propiedad** dentro de `_price_one_property`. De los cinco, sólo `Triage` tiene ya
los puertos `users` + `notifications` (se los dio `_ApprovalGateMixin`); los otros cuatro no.

Y el patrón de destinatarios está escrito **dos veces**: `guests/application/use_cases.py::_managers`
(managers activos, con caída al owner) y `notifications/application/use_cases.py::_active_holders`
(lo mismo, parametrizado por rol y contando la página truncada en su informe). R5.1 prohíbe
derivar un tercero.

## Decisions

### D1 — Un solo resolvedor de destinatarios, en `app/auth/domain/recipients.py`

**Chosen:** un servicio de dominio nuevo, `RoleRecipients`, que recibe el puerto
`UserRepository` por constructor y expone `managers_or_owners(tenant_id)` y
`active_holders(tenant_id, role)`, devolviendo un `Recipients(users: tuple[User, ...], dropped: int)`
congelado. Vive en `auth` porque la pregunta que contesta es sobre el censo de usuarios —el
agregado y el puerto son de `auth`— y así el módulo no gana ninguna arista nueva hacia fuera:
lo importan `cleaning`, `maintenance`, `pricing`, `guests` y `notifications`, y él no importa a
nadie. Es un `domain/` legítimo: recibe un puerto, no toca sesión ni SQL, y la caída
manager→owner **es una regla**, que `backend-architecture.md` prohíbe alojar en `application/`.

`dropped` existe desde el primer día porque el consumidor que ya la necesita —
`EscalateBreachedSlasUseCase`, que la suma a `EscalationReport.recipients_truncated`— es
precisamente uno de los que hay que absorber, y un helper sin ese dato le obligaría a
quedarse fuera. El log de truncamiento **no** se emite aquí: cada llamante conserva su propia
clave (`scheduler.escalation_recipients_truncated` y las que estrena este change), porque el
nombre del log es del sitio que lo emite.

**Alcance, resuelto en el gate de diseño (2026-08-29, Jose)**: se migran **los dos**
implementadores que ya existen —`guests::_managers` y
`EscalateBreachedSlasUseCase._active_holders`—, además de estrenarlo en los seis escritores
nuevos. Los dos son de comportamiento idéntico al helper (por eso `Recipients` lleva `dropped`),
así que la migración es una refactorización sin cambio observable, y el patrón queda escrito una
sola vez en todo el repo. Coste asumido: toca un caso de uso ya entregado
(`notifications/application/use_cases.py`) y sus tests.

Rejected: `app/notifications/application/recipients.py` — sería el primer import
`application/` → `application/` entre dominios del repo (medido: hoy hay **cero**), y el panel
de arquitectura lo trataría como precedente.
Rejected: `app/core/` — `architecture.md` reserva `core` a infraestructura compartida y dice
expresamente que no aloja entidades ni reglas de negocio.
Rejected: duplicar el patrón en cada módulo — es literalmente lo que R5.1 prohíbe.

### D2 — La idempotencia de R1.3 es un método de lectura nuevo del puerto, no un índice único

**Chosen:** `NotificationLogRepository.exists_for(tenant_id, *, related_type, related_id,
notification_type) -> bool`, con la misma tripleta de argumentos con nombre que
`cancel_sla_deadline` ya usa, y cubierta por el mismo
`ix_notification_logs_related_type_related_id`. `add` hace `flush()`, así que una fila escrita
antes en la misma transacción ya es visible para esta consulta: la deduplicación funciona
igual dentro de una transacción que entre dos.

Rejected: índice único parcial en `notification_logs` — exige migración, y la proposal cierra
el change «sin migración»; además convertiría una segunda clasificación legítima en un error
500 en vez de en un no-op.
Rejected: deducir «ya avisado» de `incidents.ai_classification` o de un `TimelineEvent` — sería
un segundo hecho que puede discrepar del que de verdad importa, que es si la fila existe.

### D3 — El disparo mira la severidad que la incidencia **tiene** tras la mutación, no una transición calculada

**Chosen:** después de `incident.classify(...)` / `incident.set_triage(...)` y de guardar, si
`incident.severity in {CRITICAL, HIGH}` se intenta escribir el aviso de esa severidad, y D2 lo
deduplica. En el camino de clasificación se exige además `incident.status is CLASSIFIED`, que
es exactamente la puerta que R1.5 pide: por debajo del umbral la entidad **no** toca
`severity` (`maintenance/domain/entities.py:369-376`), se queda `OPEN` con su `MEDIUM` por
defecto y sólo escribe `ai_classification`.

Esto es equivalente a «pasa a» y no una aproximación, y se puede afirmar porque se midió:
`severity` tiene **exactamente dos escritores** en todo `backend/app` —`classify` y
`set_triage`— y ninguna vía de alta la fija (`ReportIncidentUseCase` y
`ReportGuestIncidentUseCase` no la aceptan; el campo nace `IncidentSeverity.MEDIUM` en
`entities.py:158`). Una incidencia no puede llegar a `HIGH`/`CRITICAL` sin pasar por uno de los
dos sitios que notifican. R1.4 (subir de `HIGH` a `CRITICAL`) sale gratis: la deduplicación es
por tipo, así que el `CRITICAL` se escribe aunque el `HIGH` ya esté.

Rejected: comparar `previous_severity != incident.severity` — se rompe en el caso que R1.3
nombra: un triage que **confirma** la severidad que el clasificador ya puso no la cambia, y sin
embargo es correcto no avisar; y no cubre el triage que corrige `CRITICAL → CRITICAL` tras un
fallo de escritura. Con D2 la comparación no aporta nada y añade un estado más que mantener.

### D4 — Un builder por tipo, cada uno con su literal en el `NotificationLog(...)`

**Chosen:** seis builders puros, ninguno parametrizado por tipo:
`incident_critical_notification` / `incident_high_notification` en
`maintenance/domain/notifications.py`, `completion_notification` /
`validation_failed_notification` en `cleaning/domain/notifications.py`, y
`price_recommendation_notification` en el fichero nuevo `pricing/domain/notifications.py`. Cada
uno construye su `NotificationLog(...)` con `notification_type=NotificationType.<X>.value`
escrito a mano.

El motivo no es estético: **es lo que hace medible el censo de R6**. Un builder único con
`notification_type=_TYPE_BY_SEVERITY[severity].value` deja el guardián sin literal que leer y
`INCIDENT_CREATED_CRITICAL` e `INCIDENT_CREATED_HIGH` volverían a contarse como huérfanos. La
duplicación de un constructor de quince líneas es el precio de que el censo se pueda comprobar,
y es exactamente la forma que `cleaning/domain/notifications.py` ya tiene (dos constructores
casi gemelos).

Rejected: un builder con `severity: IncidentSeverity` y un mapa — ver arriba.
Rejected: ensanchar el guardián para que resuelva mapas — un guardián que interpreta
indirecciones deja de ser una comprobación de forma y pasa a ser un intérprete parcial de
Python.

### D5 — En `maintenance`, un mixin `_NotifiesSeverity` compartido por clasificación y triage

**Chosen:** un mixin junto a `_ApprovalGateMixin` con un único método
`_notify_severity(tenant_id, incident, now)` que resuelve destinatarios (D1), consulta D2 y
escribe una fila por destinatario. `TriageIncidentUseCase` ya recibe `users` y `notifications`
por `_gate_kwargs`, así que no cambia su firma; `ClassifyIncidentUseCase` los gana, y con ellos
sus tres sitios de construcción (`maintenance/api/dependencies.py:116`,
`scheduler/tasks.py:168`, `cli/seed_demo.py:1243`).

Se escribe **antes** del `await self._uow.commit()` que ambos casos de uso ya tienen, que es
todo lo que R1.6 pide: no hay ventana en la que la incidencia sea crítica y el aviso no exista.

Rejected: un caso de uso «notificar severidad» aparte — necesitaría su propia transacción y
rompería justamente R1.6.

### D6 — En `cleaning`, los dos puertos bajan a `_TaskLifecycleBase`, y su docstring se enmienda

**Chosen:** `notifications` y `users` pasan a ser colaboradores de `_TaskLifecycleBase`, de
modo que `Complete` y `Validate` los tengan. Eso deja obsoleto —y hay que **reescribirlo**, no
dejarlo mintiendo— el párrafo de `_AnswersAnAssignmentBase` que dice «starting, completing and
validating happen after an answer, so their deadline is already closed and they do not get the
port», y su gemelo en `cleaning/api/dependencies.py:129-132`. La razón por la que aquel párrafo
era cierto sigue siéndolo (esas tres operaciones no cierran ningún SLA); lo que cambia es que
ahora tienen otro motivo para necesitar el puerto. `_AnswersAnAssignmentBase` sobrevive como el
sitio donde vive `_close_assignment_sla`.

El destinatario de `CLEANING_FAILED` se resuelve con
`UserRepository.get_active_by_id(tenant_id, task.assigned_cleaner_id)`, no con `get`: una
limpiadora dada de baja no es destinataria, y ese caso se trata **igual que R2.3** (no se
escribe fila, se registra, no se falla la validación) porque para la manager el efecto es el
mismo — nadie va a leer el aviso.

Rejected: dárselos sólo a `Complete` y `Validate` con un tercer mixin — serían tres jerarquías
paralelas sobre la misma base para repartir dos puertos.

### D7 — En `pricing`, la fila se escribe dentro de `_price_one_property`, desde `written.inserted`

**Chosen:** justo antes del `await self._uow.commit()` de `_price_one_property`, y sólo si
`written.inserted` no está vacío. Es la única cifra que la sentencia declara insertada
(`RETURNING xmax = 0`), que es literalmente lo que R4.2 exige; el bucle de timeline que ya
existe cinco líneas más arriba usa el mismo conjunto, así que las dos escrituras cuentan la
misma cosa. Una fila por propiedad y ejecución sale de estar dentro de un método que se ejecuta
una vez por propiedad.

Los destinatarios de R4.4 —**unión** de `PROPERTY_MANAGER` activos y `TENANT_OWNER` activos, no
la caída de R5.1— se resuelven **una vez por ejecución y de forma perezosa**: dos consultas la
primera vez que alguna propiedad crea algo, memorizadas para el resto del barrido. Con un
barrido nocturno de N propiedades, resolverlos por propiedad serían 2N consultas para una
respuesta que no cambia; resolverlos al entrar en `execute` gastaría dos consultas en el caso
normal, en el que en régimen la mayoría de ejecuciones sí crean algo pero un tenant sin reglas
no crea nada. No hay riesgo de arrastre entre transacciones: el puerto devuelve entidades de
dominio, no modelos ORM, así que el `rollback()` de una propiedad fallida no las invalida.

No hace falta deduplicar la unión: `User.role` es un único valor (`auth/domain/entities.py:43`),
así que ningún usuario está en los dos grupos.

Rejected: una fila por recomendación creada — R4.2 la descarta con la cifra (60 el primer día
por propiedad).
Rejected: resolver los destinatarios en `execute` antes del bucle — dos consultas garantizadas
en cada tick de cada tenant, incluidas las ejecuciones que no crean nada.

### D8 — R3 es una línea de `_POLICY`, y el `subject` del escalado no se toca

**Chosen:** en `notifications/domain/escalation.py`, la entrada de `TECHNICIAN_ASSIGNED` pasa a
`notification_type=NotificationType.TECHNICIAN_NO_RESPONSE`, conservando
`recipient_role=PROPERTY_MANAGER` y `reason="technician_assignment_unanswered_no_phone_adapter"`.
Nada más cambia: `escalation_for` sigue devolviendo `None` para el tipo producido (R3.4, por
construcción — no hay entrada para él en el mapa), la rama de `CLEANING_TASK_ASSIGNED` sigue
siendo `SLA_BREACH` (R3.2) y no hay migración de filas viejas (R3.5).

El `subject` de `_escalation_row` sigue siendo la constante `"SLA breach"`, que es un hecho
cierto de la fila —el plazo se incumplió— y el tipo es lo que distingue el caso, que es lo que
R3 pide. **Confirmado en el gate de diseño (2026-08-29, Jose)**: darle un `subject` propio
exigiría un campo más en la dataclass congelada `Escalation` y obligaría a declarar
explícitamente el de la rama de limpieza; la etiqueta que la manager lee la pondrá
`notifications-inbox-web` a partir del tipo.

Rejected: `subject` por escalado en `Escalation` — un campo nuevo en la política pura para una
distinción que el `notification_type` de la fila ya hace.

### D9 — El guardián de R6 mide **dos** formas exactas; la que la proposal enunciaba sobra y falta a la vez

**Chosen:** `backend/tests/notifications/test_writer_census.py`, sobre el AST de todos los
`backend/app/**/*.py` excepto `notifications/domain/enums.py`, contando como escritor de un
tipo:

1. una llamada cuyo *callee* es literalmente `NotificationLog` con
   `notification_type=NotificationType.<X>.value`; **y**
2. una llamada cuyo *callee* es literalmente `Escalation` con
   `notification_type=NotificationType.<X>` (sin `.value`), en
   `notifications/domain/escalation.py`.

Los dos ejes hacen falta y se midió por qué, corriendo el barrido contra el árbol de hoy:

- **La forma que la proposal enunciaba sobra por un lado**: `notification_type=NotificationType.<X>.value`
  aparece también en **cuatro** llamadas a `cancel_sla_deadline`
  (`cleaning/application/use_cases.py:692`, `maintenance/application/use_cases.py:1590`, `:1762`,
  `:1840`), que **borran un plazo** y no escriben nada. Sin fijar el callee, `CLEANING_TASK_ASSIGNED`
  y `TECHNICIAN_ASSIGNED` seguirían contando como escritos aunque desapareciesen sus builders.
- **Y falta por el otro**: `SLA_BREACH` no tiene ningún literal en un `NotificationLog(...)`. Su
  fila la escribe `_escalation_row` con `notification_type=escalation.notification_type.value`,
  y el único sitio donde el tipo aparece escrito es el `_POLICY` de `escalation.py`. Con la
  forma anterior a secas, `SLA_BREACH` —y, tras este change, `TECHNICIAN_NO_RESPONSE`—
  saldrían como huérfanos y la lista de R6.2 tendría seis nombres en vez de cuatro.

Con las dos formas, el censo medido el 2026-08-29 da **siete** escritores
(`CLEANING_TASK_ASSIGNED`, `CLEANING_NO_RESPONSE`, `TECHNICIAN_ASSIGNED`,
`OWNER_APPROVAL_REQUIRED`, `GUEST_ESCALATION`, `PASSWORD_RESET_REQUESTED`, `SLA_BREACH`) y diez
huérfanos, que es exactamente el censo corregido de la proposal. Al cerrar serán trece y cuatro.

R6.3 quedó enmendada en `proposal.md` con esta forma antes de cerrar el gate de diseño, para que
la spec viva no heredase la anterior.

El test declara **dos listas literales** —`WITH_WRITER` y `WITHOUT_WRITER`— y afirma tres cosas:
que su unión es el conjunto de miembros de `NotificationType` (R6.4: un miembro nuevo que no
esté en ninguna rompe), que `WITHOUT_WRITER` es exactamente los cuatro de R6.2, y que el
conjunto medido coincide con `WITH_WRITER` **en las dos direcciones**. Los dos tipos de texto
libre que no son miembros del enum —`INCIDENT_REJECTED` y `LEGAL_REGISTRATION_FAILED`— quedan
fuera por construcción: no hay `NotificationType.<X>` que casar.

Rejected: contar por `grep` de nombres — es el guardián que se sortea escribiendo el nombre en
un comentario, y ya sabemos cómo acaba (`test_free_text_sink_contract.py` lo documenta).

### D10 — Los seis builders nacen sin `sla_deadline_at`, y eso es inalcanzable, no una omisión

**Chosen:** ninguno de los seis builders acepta un parámetro de plazo, así que R5.5 no depende
de que nadie se acuerde: no hay forma de pasarle uno sin cambiar la firma. Es la misma técnica
que `incident_rejection_notification` y `owner_approval_notification` ya usan, y cierra el
efecto que la proposal midió: con `dispatch_notifications` moviendo `PENDING → SENT` cada
minuto, un plazo aquí produciría candidatos reales de incumplimiento contra tipos para los que
`escalation_for` devuelve `None` — filas marcadas como incumplidas sin avisar a nadie.

### D11 — La tabla de la regla 11 gana el fichero nuevo, y sólo ella

**Chosen:** `sdd/steering/security.md` es el **único** sitio donde se declara quién escribe un
sumidero del censo, y `backend/tests/test_rule11_ownership.py` lo hace cumplir barriendo `sdd/`,
`docs/`, `backend/app/` y `backend/tests/`. La fila «`notification_logs.subject`/`body` — el
contrato vivo» enumera hoy `maintenance/domain/notifications.py` y
`cleaning/domain/notifications.py`; hay que **añadirle `pricing/domain/notifications.py`**, que
se atiene al mismo contrato (asunto constante, cuerpo de constante más identificadores) y por
tanto entra en esa misma fila, no en una nueva — «una entrada por contrato, no por módulo».

Las docstrings de los builders nuevos se calcan de las existentes: citan el contrato y declaran
que lo cumplen, y **no** atribuyen propiedad a nadie, que es el segundo eje que dispara el
guardián. `sdd/changes/` está excluido del barrido entero, así que este documento no lo
enciende.

### D12 — Ni contrato HTTP, ni migración, ni frontend

**Chosen:** no hay ruta nueva, ni campo nuevo en ninguna respuesta, ni columna nueva. `POST
/api/v1/price-recommendations/generate` devuelve los mismos contadores. Por tanto
`backend/openapi.json` no se regenera y no hay nada que tocar en `frontend/` ni en `locales/`.
Las etiquetas es/en de los seis tipos nuevos son de `notifications-inbox-web`, como la proposal
ya coordina.

Consecuencia asumida de D5/D6: `app/cli/seed_demo.py` gana los puertos en sus dos helpers y,
con ellos, el seed de demo empieza a **escribir notificaciones** —una incidencia clasificada
como grave y una limpieza completada dejan sus filas—. Es deseable y no accidental: la bandeja
que `notifications-inbox-web` va a construir tendrá algo que enseñar en la demo.

## Changes by area

| Area | Files | Change |
|---|---|---|
| auth (nuevo) | `backend/app/auth/domain/recipients.py` | **Nuevo.** `Recipients` (frozen) y `RoleRecipients` con `managers_or_owners` / `active_holders` (D1) |
| notifications (puerto) | `notifications/domain/repositories.py`, `notifications/infrastructure/repositories.py` | `exists_for(...)` en el `Protocol` y su `SELECT ... LIMIT 1` en el adapter (D2) |
| notifications (política) | `notifications/domain/escalation.py` | La entrada `TECHNICIAN_ASSIGNED` produce `TECHNICIAN_NO_RESPONSE` (R3.1, D8) |
| notifications (consumo) | `notifications/application/use_cases.py` | `_resolve_recipients`/`_active_holders` pasan a delegar en `RoleRecipients`, conservando su log y su contador (D1, y ver OQ1) |
| maintenance | `maintenance/domain/notifications.py` | Dos builders nuevos: `incident_critical_notification`, `incident_high_notification` (D4, D10) |
| maintenance | `maintenance/application/use_cases.py` | Mixin `_NotifiesSeverity`; `ClassifyIncidentUseCase` gana `users`+`notifications`; ambos casos de uso notifican antes de su commit (D3, D5) |
| maintenance (wiring) | `maintenance/api/dependencies.py` | `get_classify_incident_use_case` pasa los dos puertos nuevos |
| cleaning | `cleaning/domain/notifications.py` | Dos builders nuevos: `completion_notification`, `validation_failed_notification` (D4, D10) |
| cleaning | `cleaning/application/use_cases.py` | `notifications`+`users` suben a `_TaskLifecycleBase`; `Complete` y `Validate` notifican antes de su commit; docstring de `_AnswersAnAssignmentBase` enmendada (D6) |
| cleaning (wiring) | `cleaning/api/dependencies.py` | `_lifecycle_kwargs` incluye los dos puertos; se retiran los `notifications=` sueltos de accept/reject/cancel y se corrige el comentario de `get_accept_...` (D6) |
| pricing (nuevo) | `backend/app/pricing/domain/notifications.py` | **Nuevo.** `RELATED_TYPE_PROPERTY` y `price_recommendation_notification` (D4, D10) |
| pricing | `pricing/application/use_cases.py` | `GeneratePriceRecommendationsUseCase` gana `users`+`notifications`; resolución perezosa y memorizada por ejecución; escritura desde `written.inserted` dentro de `_price_one_property` (D7) |
| pricing (wiring) | `pricing/api/dependencies.py`, `scheduler/tasks.py` | Los dos sitios de construcción pasan los puertos nuevos |
| guests | `guests/application/use_cases.py` | `_managers` pasa a ser una llamada a `RoleRecipients.managers_or_owners` (D1) |
| CLI | `app/cli/seed_demo.py` | `_incident_flow_kwargs` y `_cleaning_lifecycle_kwargs` ganan los puertos (D12) |
| tests | `backend/tests/notifications/test_writer_census.py` | **Nuevo.** El guardián de R6 (D9) |
| tests | `backend/tests/notifications/test_escalation.py` | El escalado del técnico ahora es `TECHNICIAN_NO_RESPONSE`; el conjunto «sin escalado» cambia (D8) |
| tests | `tests/maintenance/conftest.py`, `tests/cleaning/*`, `tests/pricing/conftest.py`, `tests/scheduler/*` | Fakes y fixtures que construyen los cinco casos de uso ganan los puertos nuevos |
| steering | `sdd/steering/security.md` | La fila del contrato vivo de `notification_logs.subject`/`body` enumera también `pricing/domain/notifications.py` (D11) |
| archive | `sdd/roadmap.md`, `sdd/roadmap/notification-writers-gap.md` | Encargo a `/sdd:archive`: la entrada y su nota dicen «nueve sin escritor» y son diez; la proposal ya lo corrigió con la medición |

## Data & interfaces

- **Esquema**: sin cambios. Ni columna, ni índice, ni migración. `notification_type` sigue
  siendo `String(100)` de texto libre y `NotificationType` sigue teniendo diecisiete miembros.
- **Puerto** (única superficie nueva):
  ```python
  async def exists_for(
      self, tenant_id: uuid.UUID, *, related_type: str,
      related_id: uuid.UUID, notification_type: str,
  ) -> bool: ...
  ```
- **Filas que nacen**, todas `status=PENDING`, `channel=IN_APP`, sin `sla_deadline_at`:

  | Tipo | `related_type` / `related_id` | Destinatarios |
  |---|---|---|
  | `INCIDENT_CREATED_CRITICAL` | `incident` / incidencia | managers activos → owners (R5.1) |
  | `INCIDENT_CREATED_HIGH` | `incident` / incidencia | managers activos → owners (R5.1) |
  | `CLEANING_COMPLETED` | `cleaning_task` / tarea | managers activos → owners (R5.1) |
  | `CLEANING_FAILED` | `cleaning_task` / tarea | la limpiadora asignada, si está activa (R2.2) |
  | `PRICE_RECOMMENDATION` | `property` / propiedad | managers activos **y** owners activos (R4.4) |
  | `TECHNICIAN_NO_RESPONSE` | `notification_log` / fila incumplida | manager → owner, sin cambios (R3.1) |

- **HTTP**: sin cambios. `backend/openapi.json` no se regenera.
- **Config/env**: nada nuevo.

## Risks & mitigations

- **La deduplicación de R1.3 es comprobar-y-escribir, no una restricción.** Dos escrituras
  concurrentes sobre la misma incidencia y severidad podrían colarse las dos. Mitigación y por
  qué se acepta: el job de clasificación corre bajo `_locked` (un tenant, una ejecución) y el
  triage es una acción humana sobre una fila que el job no está tocando, así que la ventana
  exige que una manager pulse triage en el mismo milisegundo en que el job clasifica esa misma
  incidencia. Cerrarla de verdad es un índice único parcial, y eso es una migración que la
  proposal deja fuera. Queda dicho aquí y no en el código como «imposible».
- **Bajar los puertos a `_TaskLifecycleBase` amplía lo que seis operaciones *pueden* escribir.**
  `Start`, `Accept`, `Reject` y `Cancel` no los necesitan para nada nuevo. Mitigación: la
  docstring de la base dice para qué está cada puerto, y el censo de D9 se pondría rojo si
  alguna de ellas empezase a escribir un tipo sin declararlo.
- **`ClassifyIncidentUseCase` pasa de once a trece colaboradores.** Es mucho, y es el precio de
  que R1.6 se cumpla en la transacción que ya existe. La alternativa (un caso de uso aparte) la
  rompe. Se acepta y se anota: si crece más, lo que toca es extraer el trío
  incidencia+auditoría+timeline, no repartir la notificación.

  **Corregido en `/sdd:run` (panel de la sección 4, 2026-08-29), medido y no recordado**: este
  párrafo decía «de nueve a once» y las dos cifras estaban mal por dos. Nueve es lo que toma
  `_IncidentFlowBase`; `ClassifyIncidentUseCase` ya añadía `classifier` y `configs` **antes** de
  este change, así que partía de once y queda en trece. Medido con `inspect.signature` sobre el
  MRO, no contando a ojo. La decisión no cambia —el coste sigue siendo el que R1.6 justifica y
  la salida si crece sigue siendo la misma—, pero un documento que cuenta mal es el que se cita
  después como si hubiera contado bien. `TriageIncidentUseCase` también queda en trece.
- **El barrido de precios escribe más filas por noche.** Una por propiedad y ejecución, y sólo
  si esa ejecución creó algo. En régimen es una por propiedad y día; el primer día de una
  propiedad, también una. No hay riesgo de volumen.
- **El guardián de D9 lee el AST de todo `backend/app/`.** Un fichero que no parsea lo pone
  rojo con un mensaje confuso. Mitigación: el test nombra fichero y línea en el fallo, y usa el
  mismo idioma que `test_rule11_ownership.py` y `test_layering.py`, que ya barren el árbol
  entero sin problemas.

## Open questions

Ninguna abierta. Las tres que este diseño levantó se resolvieron en el gate del 2026-08-29
(Jose) y viven ya donde les corresponde:

- **OQ1 — alcance de la consolidación del resolvedor de destinatarios** → resuelta en **D1**:
  se migran los dos implementadores existentes además de estrenarlo en los seis escritores
  nuevos.
- **OQ2 — `subject` propio para el escalado del técnico** → resuelta en **D8**: se deja la
  constante `"SLA breach"`; el tipo de la fila es lo que distingue el caso.
- **OQ3 — la forma de R6.3 estaba mal medida** → **enmendada en `proposal.md`**, no sólo aquí:
  R6.3 declara ahora las dos formas de D9 con el *callee* fijado, y deja escrito por qué la
  anterior sobraba (cuatro `cancel_sla_deadline`) y faltaba (`SLA_BREACH` no tiene literal).
  Sin esa enmienda la spec viva habría heredado un `SHALL` falso.
