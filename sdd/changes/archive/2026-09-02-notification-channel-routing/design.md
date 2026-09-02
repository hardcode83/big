# Design: notification-channel-routing

## Context

`notification_logs` admite los cinco miembros de `NotificationChannel` (`access-notifications.md`
§«La entrega de notificaciones») y los adapters de `EMAIL`, `WHATSAPP`, `CONSOLE` e `IN_APP` ya
están cableados, pero las dos flags que el tenant expone (`TenantConfig.notification_email_enabled`
y `TenantConfig.notification_whatsapp_enabled`,
`backend/app/tenants/domain/entities.py:116-117`) **no las lee nadie**: los 13 literales de canal
que hoy escriben una fila fijan `NotificationChannel.IN_APP` a mano
(`backend/app/cleaning/domain/notifications.py:56,96,139,184`,
`backend/app/maintenance/domain/notifications.py:85,143,183,231,273`,
`backend/app/messaging/domain/notifications.py:62`,
`backend/app/pricing/domain/notifications.py:65`,
`backend/app/notifications/application/use_cases.py:244`,
`backend/app/guests/application/use_cases.py:620`); el único literal `EMAIL` está en
`backend/app/auth/application/recovery.py:157-300`, declarado excepción de `access-notifications.md`.
El inbox (`backend/app/notifications/api/router.py:75-93`) no filtra por canal, así que un aviso
multi-canal se pintaría varias veces. El plazo de SLA hoy vive en una sola fila por aviso y
`cancel_sla_deadline` (`backend/app/notifications/domain/repositories.py:247-273`) casa por
`related_type`/`related_id`/`notification_type` sin tocar el canal, así que sigue cerrando todas las
filas hermanas con una sola llamada. La plantilla del escritor de cada módulo vive ya en su dominio
`domain/notifications.py` con `NotificationType.<X>.value` a mano, y el censo se mide por AST en
`backend/tests/notifications/test_writer_census.py`.

## Decisions

### D1 — El resolutor vive en `notifications/domain/` y es un servicio puro, no un endpoint

**Chosen:** `backend/app/notifications/domain/channel_resolver.py` con una función
`resolve_channels(tenant_config, recipient) -> set[NotificationChannel]` que recibe el `TenantConfig`
y un `RecipientContact` (un dataclass nuevo con `email: str | None` y `phone: str | None`).
Aplica R1.1 (IN_APP siempre, EMAIL si flag, WHATSAPP si flag), R3 (exclusión por contacto
ausente) y R1.5 (config ausente → IN_APP único). Recibe un `TenantConfig` directamente, no el
puerto. **Corregido en la ronda de fixes de `/sdd:review` (el reviewer de arquitectura de
sección 4 lo encontró):** este párrafo decía que el caso "config ausente" lo resolvía el
callante antes de invocar la función, y que los logs no eran del dominio del resolutor — pero
la implementación real, y el párrafo de "Risks & mitigations" más abajo, hacen lo contrario:
`resolve_channels` recibe `tenant_config: TenantConfig | None` y trata `None` como su propio
caso, devolviendo `{IN_APP}` y registrando `notifications.tenant_config_missing` ahí mismo, sin
que el callante tenga que rederivar R1.5. La razón de mantenerlo así (y no como decía este
párrafo) es la que da el rechazo (a) de abajo: si el resolutor no maneja `None`, cada callante
tendría que reimplementar la misma rama defensiva. El resolutor también es el que registra
`notifications.channel_dropped_for_missing_contact` (R3.3) — ver D7, que reasigna esa
responsabilidad al callante en su propio texto y tampoco coincide con el código; ambos son la
misma corrección: los dos logs de R1.5 y R3.3 viven en el resolutor, no en el llamante.

Rejected: (a) inyectar `TenantConfigRepository` dentro del resolutor — mete el dominio puro en
adaptadores, contradice `steering/backend-architecture.md`; (b) método sobre el `User` — confunde
lo que es del tenant (las dos flags) con lo que es del usuario (los contactos), y rompe la
simetría con `RoleRecipients`.

### D2 — El fan-out vive en `notifications/application/`, los builders se quedan puros

**Chosen:** nueva función pública `dispatch_channels(recipient, template, channels,
log_builder)` en `backend/app/notifications/application/channel_dispatch.py` que itera los canales
resueltos y llama al builder del dominio una vez por canal con `(channel, contact)` ajustados al
canal. Los builders existentes de `cleaning/domain/notifications.py`, `maintenance/domain/...`,
etc. **crecen con un parámetro opcional `channel: NotificationChannel` y `contact: str`**; la
`recipient_contact` actual pasa a derivarse del canal que resuelve. El builder fija
`sla_deadline_at` solo cuando el canal pasado es `IN_APP` (R4.1) — si hoy ya lo hace solo para
algunos tipos, eso se mantiene y el resto no se toca.

Rejected: (a) el builder emite N filas en una sola llamada — funde dos responsabilidades (resolver
y construir) y rompe la regla de "una fila por construcción" del censo AST; (b) el fan-out vive en
cada use case de cada módulo — duplica la lógica en `cleaning/`, `maintenance/`, `messaging/`,
`pricing/`, `guests/` y rompe el "mismo resolutor en un solo lugar" de R1.3.

### D3 — Cancel de SLA sigue funcionando sin cambio

**Chosen:** el fan-out fija `sla_deadline_at` **solo en la fila IN_APP** y deja las demás con
`NULL`. `cancel_sla_deadline` filtra por `tenant_id + related_type + related_id +
notification_type` (sin canal) y hace `UPDATE ... SET sla_deadline_at = NULL` sobre todas las
filas que casan, así que en una sola llamada cierra la fila con plazo y deja las otras (que ya
estaban en `NULL`) intactas. `list_sla_breach_candidates` exige `sla_deadline_at IS NOT NULL`, así
que solo la fila IN_APP puede llegar a candidata — y la lista sigue siendo 1:1 con el aviso.

Rejected: (a) extender `cancel_sla_deadline` para filtrar por canal — añadiría un parámetro y un
test por la única fila que lo lleva; (b) pasar el plazo a todas las filas y filtrar después — el
sistema de "plazo muerto" de `cancel_sla_deadline` se complica sin motivo.

### D4 — El inbox filtra a `IN_APP` en el repositorio, no en el router

**Chosen:** `list_for_recipient` y `count_unread` aceptan un nuevo parámetro keyword-only
`channel: NotificationChannel = NotificationChannel.IN_APP` (default perezoso: `IN_APP`). El
router de `backend/app/notifications/api/router.py` deja de fijar filtros en este parámetro y
depende del default. La firma añade el parámetro sin romper a quien lo llama con `None` (no
existe ese uso actualmente; se documenta en el docstring).

Rejected: (a) filtro en el router — el router no debería saber de canales; (b) un repositorio
nuevo `list_in_app_for_recipient` — duplica el shape paginado sin más motivo.

### D5 — La excepción de `auth/application/recovery.py` se mantiene literal

**Chosen:** R6.1 gana una viñeta en `access-notifications.md`: la recuperación de contraseña fija
`NotificationChannel.EMAIL` con `RecipientContact(email=user.email)` directamente, sin pasar por
`dispatch_channels`, e invoca el adapter de `EMAIL` síncronamente — sigue siendo el único camino
que entrega sin pasar por `PENDING`. El censo AST (test_writer_census) lo deja en
`CONSTRUCTION_SITES` con la literal permitida.

Rejected: (a) invocar el resolutor desde la recuperación — añadiría latencia de lectura de
configuración a un camino síncrono de login, y un tenant con la flag apagada dejaría de recibir el
correo de recuperación; (b) cambiar el `EMAIL` de recuperación a un canal derivado de la flag —
rompe el "restablecimiento siempre llega" del PRD §16.

### D6 — El censo AST gana una segunda forma para el fan-out

**Chosen:** el constructor `dispatch_channels` de `notifications/application/channel_dispatch.py`
queda dentro de `CONSTRUCTION_SITES` porque itera el builder y produce N filas. El nuevo guard
**canal-literal** (R2.5) enumera `NotificationChannel.<X>` sobre el AST de `backend/app/` y exige
que la lista blanca sea exactamente estos **trece** sitios — la cifra que la tarea 6.1 fija como
evidencia, y que creció respecto al recuento inicial de este documento porque cada builder
parametrizado y cada default de canal nuevo del fan-out es él mismo un sitio que nombra el enum:
  - `notifications/application/channel_dispatch.py` (resuelve el contacto por canal)
  - `notifications/domain/channel_resolver.py` (devuelve el conjunto resuelto)
  - `auth/application/recovery.py` (R6 declarado)
  - `notifications/infrastructure/adapters.py` (registro de adapters — sin fila)
  - `messaging/infrastructure/channels.py` (canales de conversación, no de `notification_logs`)
  - `cleaning/domain/notifications.py`, `maintenance/domain/notifications.py`,
    `messaging/domain/notifications.py`, `pricing/domain/notifications.py` (los cuatro módulos de
    builders: `channel=IN_APP` es el default del parámetro nuevo, no una asignación de escritor)
  - `notifications/application/use_cases.py` (mismo default, en los casos de uso de la bandeja)
  - `notifications/infrastructure/repositories.py` (mismo default, en la implementación SQL)
  - `notifications/domain/repositories.py` (mismo default, en el `Protocol` del puerto — el tipo
    que el resto del árbol type-checka contra él, no solo su implementación)
  - `tests/notifications/test_channel_literals.py` (el propio guard)

Rejected: (a) un único guard que mide writers + canales — R6.3 ya fija las dos formas del primero
y mezclar lo vuelve opaco; (b) un guard de `grep` — `test_free_text_sink_contract.py` documenta
por qué esto no basta.

### D7 — Exclusiones por contacto ausente se registran con tipo y canal solamente

**Chosen:** cuando el resolutor descarta `WHATSAPP` por teléfono ausente o `EMAIL` por email en
blanco, devuelve el conjunto ya recortado y registra ahí mismo el log de aplicación
`notifications.channel_dropped_for_missing_contact` con `tenant_id`, `notification_type`,
`channel` y `recipient_role` (este último cuando aplique) — nada de `recipient_contact`,
`subject` ni `body`, por regla 11 de `steering/security.md`. **Corregido en la ronda de fixes de
`/sdd:review`:** este párrafo decía que era el caller (`dispatch_channels`) quien registraba el
log; la implementación lo hace en `resolve_channels` mismo, igual que el log de
`tenant_config_missing` de R1.5 (D1, corregido igual) — el resolutor ya tiene los cuatro datos
que el log necesita (los recibe como parámetros para poder resolver) y separar "quién decide la
exclusión" de "quién la registra" en dos módulos distintos no añadía nada que R3.3 pidiera.

Rejected: (a) bajar al canal siguiente — el precedente vinculante es
`messaging/infrastructure/channels.py`, que argumenta por escrito por qué los canales de OTA no
degradan a otro: *«it would show an operator a delivered message the guest never received»*
(R3.5); (b) absorber la exclusión en `dispatch_channels` sin un canal — colapsa el caso "sin
contacto y solo IN_APP" con "todo bien" y pierde la observabilidad de R3.3.

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| Dominio de notificaciones, nuevo | `backend/app/notifications/domain/channel_resolver.py` | Define `RecipientContact` (dataclass frozen), `resolve_channels(tenant_config, recipient) -> frozenset[NotificationChannel]`. Aplica R1.1, R3.1, R3.2. Pura. |
| Aplicación de notificaciones, nuevo | `backend/app/notifications/application/channel_dispatch.py` | Define `dispatch_channels(...)` que itera el conjunto resuelto y delega al builder por canal. Aquí cae la lógica R7.5 del S0 del `BLOCKED.md` del change anterior. |
| Dominio de notificaciones | `backend/app/notifications/domain/repositories.py` | `list_for_recipient` y `count_unread` aceptan `channel: NotificationChannel = IN_APP`. |
| Aplicación de notificaciones | `backend/app/notifications/application/use_cases.py` | `_escalation_row` se elimina del módulo y se reemplaza por `dispatch_channels` para que la fila de escalada salga abanicada. `ListOwnNotificationsUseCase`, `CountUnreadNotificationsUseCase`, `MarkNotificationReadUseCase`, `MarkAllNotificationsReadUseCase` propagan el nuevo `channel=IN_APP` por defecto a la firma. |
| Dominio de limpieza | `backend/app/cleaning/domain/notifications.py` | Builders ganan `channel: NotificationChannel` y `contact: str`; la fila IN_APP lleva el plazo (cuando proceda), las demás `NULL`. |
| Dominio de mantenimiento | `backend/app/maintenance/domain/notifications.py` | Idem. |
| Dominio de mensajería | `backend/app/messaging/domain/notifications.py` | Idem. |
| Dominio de pricing | `backend/app/pricing/domain/notifications.py` | Idem. |
| Aplicación de limpieza | `backend/app/cleaning/application/use_cases.py` | Las llamadas a builders pasan a través de `dispatch_channels`, recibiendo el `TenantConfig` desde `TenantConfigRepository` (ya inyectado para `sla_medium_minutes`). |
| Aplicación de mantenimiento | `backend/app/maintenance/application/use_cases.py` | Idem. |
| Aplicación de mensajería | `backend/app/messaging/application/use_cases.py` | Idem. |
| Aplicación de pricing | `backend/app/pricing/application/use_cases.py` | Idem. |
| Aplicación de guests | `backend/app/guests/application/use_cases.py` | El literal `IN_APP` se reemplaza por `dispatch_channels`; `LEGAL_REGISTRATION_FAILED` (no es miembro del enum) sale de `notification_type` — la fila lleva el texto crudo por la columna `String(100)` y se queda igual. |
| Aplicación de auth (recuperación) | `backend/app/auth/application/recovery.py` | **Sin cambio.** R6 declarado. |
| Workers / use cases que llaman al resolutor | `backend/app/notifications/workers.py`, … | Ningún cambio — los escritores son `use cases` de dominio, los workers siguen llamando a `EscalateBreachedSlasUseCase` y `DispatchPendingNotificationsUseCase` como hoy. |
| Spec EARS | `sdd/specs/access-notifications.md` | §«El censo de escritores» pasa a "una fila por canal resuelto"; §«La bandeja in-app» gana `AND channel = IN_APP`; el censo AST gana un párrafo sobre la nueva forma `dispatch_channels`. |
| Spec EARS | `sdd/specs/notifications-inbox-web.md` | R1 y R2 mencionan que el endpoint `GET /api/v1/notifications` y `unread-count` se acotan por canal — hoy no dice nada del canal. |
| Spec EARS | `sdd/specs/celery-jobs.md` | §«check_sla_breaches» gana un párrafo: solo la fila IN_APP lleva `sla_deadline_at`; `cancel_sla_deadline` sigue cerrando con `related_type`/`related_id`/`notification_type`. |
| Spec EARS | `sdd/specs/auth-tenancy.md` | §«TenantConfig» gana la declaración de `notification_email_enabled` y `notification_whatsapp_enabled` como interruptores de canal del resolutor de `notifications/domain/channel_resolver.py`. |
| Tests nuevos | `backend/tests/notifications/test_channel_resolver.py` | Cubre R1.1, R1.5, R3.1, R3.2: flags on/off, config ausente, contacto ausente por canal, intersección. |
| Tests nuevos | `backend/tests/notifications/test_channel_dispatch.py` | Cubre R2.1, R2.3, R4.1: una fila por canal resuelto, `sla_deadline_at` solo IN_APP, integración con `dispatch_notifications` con un adapter mock por canal. |
| Tests nuevos | `backend/tests/notifications/test_channel_literals.py` | Guard AST de literales `NotificationChannel.<X>` con la lista blanca de D6 — incluye los 5 sitios actuales y rechaza cualquier otro. |
| Tests modificados | `backend/tests/notifications/test_writer_census.py` | `CONSTRUCTION_SITES` crece con `notifications/application/channel_dispatch.py`; la regla "`cancel_sla_deadline` no es un escritor" sigue (sigue siendo un argumento de R6.3, intacto). |
| Tests modificados | `backend/tests/notifications/test_repositories.py` | `list_for_recipient` y `count_unread` con el filtro `channel=IN_APP`; verificar que filtrar por otro canal con el default roto da cero. |
| Tests modificados | `backend/tests/notifications/test_api.py` | `GET /api/v1/notifications` no devuelve filas si se invoca el adapter `WHATSAPP` (caso hipotético) y se reciben 0 filas; invariante R5.4. |

## Data & interfaces

- **Esquema.** Ningún cambio. `notification_logs.channel` ya acepta los cinco miembros del enum;
  `sla_deadline_at` ya es nullable; `recipient_contact` ya existe en `String(255)`. No hace
  falta migración Alembic.
- **Contactos.** El nuevo `RecipientContact` (en `notifications/domain/`) es el dataclass puro que
  el resolutor recibe. Los campos `User.email` y `User.phone` ya están en `auth`; el resolutor
  no toca el `UserRepository` directamente — los llamantes (casos de uso de cada dominio) ya
  tienen el `User` resuelto por `RoleRecipients`.
- **Repositorios.** `TenantConfigRepository` ya existe
  (`backend/app/tenants/domain/repositories.py:43`) y ya está inyectado en los use cases que
  consumen `sla_*_minutes` (cleaning y maintenance lo importan). Las use cases llamadas del
  resolutor **cargan el `TenantConfig` por tenant una vez** (no una vez por destinatario), y lo
  pasan al resolutor. Cuando los destinatarios son varios (caso manager-or-owner de la escalada),
  el `TenantConfig` se lee una vez y se pasa al resolutor por destinatario.
- **Contrato API.** El inbox `GET /api/v1/notifications` no añade ni quita parámetros: el
  acotamiento por `channel = IN_APP` es del repositorio. `notifications-inbox-web` lo documenta
  en R5 sin tocar el DTO.
- **Eventos.** Ninguno nuevo. La `TimelineEvent` y el `AuditLog` no intervienen.
- **Configuración.** Ninguna variable de entorno nueva. Los flags ya están en
  `TenantConfig` desde `domain-foundation-financial`/`tenants-base`.
- **i18n.** Las 17 cadenas de `locales/{es,en}/notifications.json` no cambian.
- **Frontend.** No hay cambios de comportamiento observables para el usuario: la campana sigue
  mostrando el mismo contador (R5.4). El panel no cambia su forma.
- **OpenAPI.** El contrato publicado no cambia — el filtro por canal es interno. Sin embargo
  `make openapi` debe regenerarse igualmente en el mismo commit por `steering/documentation.md`.

## Risks & mitigations

- **Doble conteo en la bandeja.** Si una fila `EMAIL` se le entrega al mismo usuario que la
  `IN_APP`, la bandeja mostraría dos avisos. La mitigación es estructural: el repositorio
  `list_for_recipient` y `count_unread` filtran por `channel = IN_APP` (D4), y el guard
  R5.4 lo afirma en `test_api.py`.
- **Plazo de SLA doble.** Si las dos flags activas hacen que `_escalation_row` produzca N filas
  con `sla_deadline_at`, habría N candidatas a `SLA_BREACH` por el mismo aviso. Mitigación: el
  builder deja `sla_deadline_at = None` para todo canal distinto de `IN_APP` (D3), y
  `test_escalate_slas_atomicity.py` se extiende con un test que abanica ambos flags y verifica
  que las candidatas son una sola (R4.3).
- **`tenant_id` ausente en `tenant_configs`.** Los cinco módulos escritores siempre cargan su
  `TenantConfig` con `TenantConfigRepository.get_or_create`, que **nunca** devuelve `None`:
  crea la fila con los defaults del campo si falta, y esos defaults incluyen
  `notification_email_enabled=True`. Aceptar ese default en el resolutor resolvería un tenant
  sin fila a `{IN_APP, EMAIL}`, no a `{IN_APP}`, contradiciendo R1.5 en el primer aviso de
  cualquier tenant que nunca pasó por el bootstrap. Mitigación: `resolve_channels` tipa su
  parámetro como `tenant_config: TenantConfig | None` y trata `None` como su propio caso — sin
  leer ningún flag, sin `with_defaults(...)` de por medio — devolviendo `{IN_APP}` y
  registrando `notifications.tenant_config_missing` con `tenant_id` y `notification_type`. Hoy
  ningún llamante de producción puede pasar `None` (todos usan `get_or_create`); el parámetro
  queda `Optional` para que el día que un llamante use un `get` que sí pueda fallar —o una
  caché con miss— R1.5 se cumpla sin que ese llamante tenga que rederivarla.
  **Ojo, no confundir con lo siguiente (el reviewer de seguridad de sección 4 y el de QA lo
  encontraron los dos, y merece su propia entrada en vez de leerse como la misma):** que este
  párrafo cierre R1.5 —la fila `tenant_configs` "no recuperable"— no dice nada sobre un tenant
  cuya fila **sí existe**, recién creada por `get_or_create` con los defaults de la entidad. Ese
  tenant resuelve a `{IN_APP, EMAIL}`, no a `{IN_APP}`, porque `notification_email_enabled: bool
  = True` es el default de `TenantConfig` desde `domain-foundation-financial`/`tenants-base` —
  anterior a este change y fuera de su alcance («El único conmutador es el par de flags que el
  tenant ya tiene», proposal.md "What changes"). Antes de este change ese default no producía
  ningún efecto observable porque nadie lo leía; después de este change sí, la primera vez que
  el escritor de un tenant recién creado dispara un aviso. No es una regresión de R1.5 —esa fila
  sí es "recuperable"— sino la primera vez que un default heredado se vuelve consecuente. Se
  acepta sin cambio en este change (cambiar el default de la entidad es una decisión de
  `domain-foundation-financial`/`tenants-base`, no de enrutado de canal, y tocarlo aquí
  arrastraría cualquier otro sitio que ya asuma `True`); queda anotado para que
  `smtp-delivery-adapter` — que ya declara este change como `needs:` — lo revise antes de que el
  adapter deje de ser un mock.
- **Resolutor lee config por destinatario.** Si un aviso sale a N destinatarios del mismo tenant,
  leer `tenant_configs` N veces es trabajo de más. Mitigación: la lectura se hace **una vez por
  caso de uso, antes del loop de destinatarios**, y la `TenantConfig` se pasa a las N llamadas al
  resolutor. Es el mismo patrón que `EscalateBreachedSlasUseCase` ya aplica para `RoleRecipients`
  (ver `backend/app/notifications/application/use_cases.py:108-132`).
- **Tests E2E existentes rotos.** `cleaning/`, `maintenance/`, `messaging/`, `pricing/` y
  `guests/` tienen tests que asumen **una fila** por aviso. Mitigación: los tests de los builders
  siguen construyendo una fila (con `channel=IN_APP`); los tests de las use cases se actualizan
  al patrón `dispatch_channels(...)`. El reviewer de QA en sección 4 los revisará.
- **Falsa promesa de R5.4.** Si `notification_email_enabled` cambia entre el `INSERT` y el
  `GET /notifications`, el contador sigue siendo estable porque ambas filas son del MISMO
  destinatario y la bandeja solo ve IN_APP. No hay deriva observable.

## Open questions

- **Q1. ¿Qué pasa con el deadline del SLA si la fila IN_APP se queda en `PENDING` por un adapter
  caído?** Hoy, `list_sla_breach_candidates` exige `status = SENT`. Si `IN_APP` siempre entrega
  (porque `InAppNotificationAdapter` es un no-op), la fila pasa a `SENT` en el primer tick y
  puede ser candidata. Si por algún motivo la fila no llega a `SENT` antes del plazo, no
  escala — esto ya pasa hoy y no es nuevo. ¿Vale? (asume sí).
- **Q2. Para `User.phone` ausente, ¿excluimos `WHATSAPP` o registramos el aviso vía otro canal?**
  R3.5 cierra la puerta explícitamente a degradar. La pregunta es más bien: ¿queremos un
  contador de "avisos no entregables por contacto ausente" en alguna pantalla? El texto del
  resolutor registra un log (`notifications.channel_dropped_for_missing_contact`) y nada más; el
  tablero (`docs/dashboard.md`) podría leerlo más adelante, pero no se introduce aquí.
- **Q3. ¿El DTO del inbox en backend debe seguir publicando `channel` en la fila?** Sí: la UI
  actual pinta `channel` por compatibilidad de `frontend` (no se ve en la pantalla, pero el
  DTO lo lleva). El cambio no lo elimina. Confirmar que `NotificationPageResponse` no incluye
  `channel` específicamente — `access-notifications.md` §«La bandeja in-app» lo enumera entre
  los campos publicados, así que se conserva.
- **Q4. ¿`notifications/infrastructure/adapters.py` se queda como está?** Sí. Es el registro de
  adapters y `EMAIL`/`CONSOLE`/`WHATSAPP`/`IN_APP` siguen ahí (R6.2). La literal `EMAIL` que
  contiene es legítima y el guard de D6 la declara.
- **Q5. ¿`messaging/infrastructure/channels.py` se queda como está?** Sí. Es la conversación
  con el huésped (PRD §13), no `notification_logs` (R6.3). Las literales `WHATSAPP`/`EMAIL` que
  contiene son del canal de conversación.
