# Design: notifications-inbox-web

## Context

El lado servidor de la bandeja existe entero y a medias a la vez. `backend/app/notifications/`
tiene una única ruta (`api/router.py`, `GET /api/v1/notifications`), un caso de uso
(`ListOwnNotificationsUseCase`), un puerto con seis métodos (`domain/repositories.py`) y su
implementación SQLAlchemy (`infrastructure/repositories.py`); `list_for_recipient` ya filtra por
`tenant_id` **y** por `recipient_user_id` y ordena de más nueva a más vieja. Lo que no hay es
columna de lectura: `infrastructure/models.py` declara dieciséis columnas y ninguna se llama
`read_at`, y `api/schemas.py` enumera diez campos a mano —reteniendo a propósito
`recipient_contact`, `last_error`, `sla_deadline_at` y `sla_breached`—.

El lado cliente no existe en absoluto: ningún fichero de `frontend/` menciona la ruta fuera del
`lib/api/generated/openapi.d.ts` generado. Las tres shells autenticadas
(`features/shell/components/{workspace,cleaner,technician}-shell.tsx`) componen hoy el slot `end`
de `Topbar` como `[ThemeSwitcher, Separator, LocaleSwitcher, UserMenu]`, y `UserMenu` ya establece
el precedente de una shell importando el punto de entrada público de otra feature
(`@/features/auth`). El patrón de feature está muy asentado —`features/incidents/` es el molde:
`data/dto.ts`, `data/http/`, `data/index.ts` como único punto de composición, `hooks/query-keys.ts`
sobre `tenantScopedKey`, `hooks/use-*.ts` con `retryPolicy`— y no hay hoy en todo el frontend ni un
solo `refetchInterval` ni un solo `onMutate`: el polling y el optimismo son terreno nuevo.

Dos guardas estructurales acotan lo que se puede tocar sin darse cuenta:
`app/route-coverage.test.ts` exige biyección exacta entre `routeRegistry` y los ficheros `page.tsx`,
y `lib/i18n/catalog-parity.test.ts` exige que cada catálogo del disco esté en `NAMESPACES` y que
`es`/`en` tengan el mismo juego de claves. En el backend,
`backend/tests/test_route_authorization.py` mantiene un snapshot literal de **todas** las rutas
protegidas: una ruta nueva que no aparezca ahí pone la suite en rojo.

## Decisions

### D1 — `read_at` es una columna nullable sin default, y llega con dos índices

**Chosen:** `read_at TIMESTAMPTZ NULL`, sin `server_default` y sin backfill (R1.1), en una migración
Alembic sobre la cabeza actual `d4a7e18c6b93` (`incident_photos`). Se añaden **dos** índices en la
misma migración:

* `ix_notification_logs_tenant_id_recipient_user_id_created_at` sobre
  `(tenant_id, recipient_user_id, created_at DESC)` — hoy **no existe ningún índice por
  destinatario**: `NotificationLogModel.__table_args__` sólo declara
  `(tenant_id, status, sla_deadline_at)` y `(related_type, related_id)`, y `recipient_user_id` es
  una clave ajena, que SQLAlchemy no indexa sola. `list_for_recipient` lleva desde
  `access-notifications` recorriendo la tabla entera del tenant para pintar veinte filas, y este
  change es el primero que le pone usuarios delante.
* `ix_notification_logs_unread` sobre `(tenant_id, recipient_user_id)` **`WHERE read_at IS NULL`** —
  parcial a propósito: el contador de R2 es la única consulta que **cada** usuario conectado lanza
  cada 60 s, y es la única cuyo coste crece sin techo según la bandeja acumula filas ya leídas. Un
  índice parcial sólo contiene lo no leído, que es el conjunto pequeño y el que de verdad se
  consulta.

`ADD COLUMN ... NULL` sin default no reescribe la tabla en PostgreSQL 16, así que la migración no
puede fallar sobre datos poblados (la base de dev tiene filas desde 2026-08-10). `downgrade` borra
los dos índices y la columna.

Rejected: un solo índice compuesto que sirva a las dos consultas — el contador acabaría filtrando
`read_at` en memoria sobre todas las filas del usuario, que es justo lo que el polling hace caro.
Rejected: `read_at` con `server_default = now()` — declararía leídas todas las filas históricas, que
es exactamente la afirmación falsa que R1.1 prohíbe.
Rejected: una tabla `notification_reads` aparte — una relación 1:0..1 con la fila que ya existe, con
su propio aislamiento de tenant que mantener, para guardar un `timestamp`.

### D2 — El acuse es `POST /api/v1/notifications/{notification_id}/read`, y devuelve `204`

**Chosen:** sub-recurso verbal por `POST`, que es la casa: `POST /cleaning-tasks/{id}/accept`,
`/incidents/{id}/en-route`, `/conversations/{id}/escalate`. Sin cuerpo de respuesta (`204`): R5.4 ya
manda invalidar la caché tras el acuse, así que devolver la fila sería un dato que nadie lee y una
segunda forma —divergible— de decir lo que el listado dice. El destinatario sale del JWT
(`authenticated.context.user_id`), nunca de la petición, igual que en la ruta de listado. Permiso
`READ_OWN_NOTIFICATIONS` (A3, `_SELF_SERVICE` en `policy.py`), **sin permiso nuevo**: acusar la
lectura de un aviso propio no es una capacidad distinta de leerlo.

Rejected: `PATCH /api/v1/notifications/{id}` con `{"read": true}` — abre un recurso mutable genérico
sobre una tabla cuyas otras quince columnas no debe tocar nadie desde fuera, y el puerto existente
está deliberadamente troceado en escrituras estrechas (`mark_breached`, `record_attempt`,
`cancel_sla_deadline`) por ese mismo motivo.

### D3 — Idempotencia y `404` salen de un único `UPDATE ... SET read_at = COALESCE(read_at, :now)`

**Chosen:** una sola sentencia, con `WHERE tenant_id = :t AND recipient_user_id = :u AND id = :id`.
`COALESCE` conserva la primera lectura (R1.3: `read_at` es la primera lectura, no la última visita) y
`rowcount == 0` significa **exactamente** «no existe una fila con ese id visible para este usuario de
este tenant» — los tres casos de R1.4 colapsan en el mismo hecho y responden el mismo `404` sin que
el código tenga que elegir entre ellos. Es la misma forma que `auth-account-recovery` usa para el
gasto único de su token.

Rejected: `SELECT` y luego `UPDATE` condicional — dos viajes, una carrera entre ellos, y un código
que *puede* distinguir «de otro» de «ya leída» y por tanto *puede* filtrarlo por descuido.
Rejected: `UPDATE ... WHERE read_at IS NULL` — `rowcount == 0` pasaría a ser ambiguo entre «ya
leída» (que R1.3 manda responder con éxito) y «no es tuya» (que R1.4 manda responder `404`).

### D4 — El contador es su propia ruta, `GET /api/v1/notifications/unread-count`

**Chosen:** una ruta que devuelve `{"unread": <int>}`, resuelta con un `SELECT count(*)` contra el
índice parcial de D1. Independiente del tamaño de página por construcción (R2.2) y con su propia
clave de caché y su propia cadencia, que es lo que permite a la campana refrescarse cada 60 s sin
arrastrar veinte filas por el cable.

Se declara **antes** que cualquier futura ruta `/{notification_id}` en el router, para que el
segmento literal no lo capture un parámetro de ruta el día que exista un detalle. Hoy no existe.

Rejected: un campo `unread_total` en el envelope paginado — acopla el contador al listado (la
campana tendría que pedir una página para saber el número), y engorda el sobre de PRD §23 que R2.3
manda no romper.
Rejected: `GET /api/v1/notifications?unread=true&per_page=1` leyendo `total` — funciona, pero
transporta una fila para no usarla y hace que campana y bandeja compartan familia de clave de
caché, con lo que una invalidación de una toca la otra sin quererlo.

### D5 — Listar sólo lo no leído es un `?unread=true` sobre la ruta que ya existe

**Chosen:** un parámetro de consulta booleano opcional, por defecto ausente (= todas). Añade una
condición `read_at IS NULL` a `list_for_recipient`, que pasa a aceptar `unread: bool | None`. El
envelope, el orden y los topes (`MAX_PAGE`, `MAX_PER_PAGE`) no se tocan (R2.3).

Rejected: una segunda ruta `/notifications/unread` — misma consulta, misma paginación, mismo
envelope, y dos sitios donde arreglar el orden la próxima vez.

### D6 — «Marcar todas» es `POST /api/v1/notifications/read-all`, y responde cuántas movió

**Chosen:** `{"updated": <int>}` desde un `UPDATE ... SET read_at = :now WHERE tenant_id AND
recipient_user_id AND read_at IS NULL`. Nunca da `404`: cero filas es el caso normal de una bandeja
al día, no un error (mismo criterio que `cancel_sla_deadline`, que tampoco falla por no encontrar
nada). Alcance fijo: **todas** las no leídas del usuario del token (R5.2), y deliberadamente **no**
las de la página o el filtro que el cliente esté mirando — un botón que dice «todas» y marca
veinte es peor que no tenerlo.

Rejected: un `POST` con la lista de ids — el cliente sólo conoce la página que tiene cargada, así
que «todas» sería mentira en cuanto la bandeja pasara de una página.

### D7 — El tipo de notificación viaja como `NotificationType | str`, y eso es lo que hace comprobable a R4.1

**Chosen:** `NotificationResponse.notification_type` pasa de `str` a `NotificationType | str`. En el
contrato publicado eso es un `anyOf: [$ref NotificationType, string]`, literalmente cierto: la
columna es `String(100)` libre y admite valores anteriores al enum (R4.3), y a la vez los diecisiete
nombres son un catálogo cerrado que el backend conoce. `openapi-typescript` emite entonces
`components["schemas"]["NotificationType"]` como unión de diecisiete literales, y el catálogo de
copia del frontend se declara `Record<NotificationType, string>` (D14): **si falta un tipo,
`npm run typecheck` falla**, que es un gate de CI.

Ese es el punto entero de la decisión. La alternativa deja R4.1 —«los diecisiete, incluidos los
nueve que hoy no escribe nadie»— defendida por nada más que la atención de quien revise el diff.

`read_at: datetime | None` se publica en la misma respuesta (R2.1). Los cuatro campos retenidos
siguen retenidos: este change no los reabre.

Rejected: declarar la lista de diecisiete a mano en TypeScript — sin origen de verdad, se desvía en
silencio el día que `notification-writers-gap` toque el enum.
Rejected: un test del frontend que lea `backend/app/notifications/domain/enums.py` — es la forma que
ya usan `features/provenance/workflow-contract.test.ts` y `lib/config/build-identity-contract.test.ts`,
y es la forma que da **dos ficheros en rojo por `ENOENT`** en cualquier worktree enlazado
(`sdd/project.md`). No se añade un tercero.
Rejected: tipar el campo como `NotificationType` a secas — rechazaría al serializar una fila con un
valor antiguo, convirtiendo el caso que R4.3 manda tolerar en un `500`.

### D8 — El acuse no escribe `AuditLog` (confirma A2 del proposal)

**Chosen:** nada. La regla 9 de `steering/security.md` enumera Reservation, estados de propiedad,
documentos de Guest, AccessRecord, PricingRule/PriceRecommendation, OwnerApproval, roles de User e
Incident. Leer un aviso propio no está en la lista, no es una operación sobre datos de otro y no
concede permiso alguno. Verificado contra el texto de la regla, no supuesto.

### D9 — La bandeja es un panel `Sheet` colgado de la campana, no una ruta nueva

**Chosen:** la campana abre un `Sheet` (el mismo primitivo que `MoreMenu` ya usa) con el listado
paginado, sus tres estados explícitos (`components/states/`) y el botón de «marcar todas». Ninguna
entrada nueva en `routeRegistry`, ningún `page.tsx` nuevo.

Es la decisión que hace que R3.1 —la campana en las **tres** shells— cueste un componente y no
tres. Una ruta tendría que existir tres veces (`/notifications`, `/cleaner/notifications`,
`/tech/notifications`), porque el `AuthGuard` de cada grupo de rutas admite un juego de roles
distinto y `WorkspaceShell` niega el paso a `CLEANER` y `TECHNICIAN`; y cada una arrastraría su
descriptor, sus claves de breadcrumb, su fila en `REAL_PAGE_ROUTE_IDS` de
`app/route-coverage.test.ts` y su entrada en la frase de `specs/frontend-foundation.md` que hoy
cuenta descriptores. Además, en las shells de campo la ruta sólo sería alcanzable desde la propia
campana, porque `CleanerShell` y `TechnicianShell` no tienen navegación ninguna.

`OverlayAutoCloser` ya cierra los overlays al cambiar el `pathname`, así que un enlace de R6 que
navega deja el panel cerrado sin código propio — con el matiz de que ese cierre pasa por
`useShellUiStore`, así que el panel expone su `open` al store igual que hace `MoreMenu`.

Rejected: tres rutas — arriba.
Rejected: un `Popover` — no existe en `components/ui/` y el requisito es mobile-first, que es
exactamente para lo que `Sheet` está.

Confirmado en el gate: panel.

### D10 — Una feature nueva, `features/notifications/`, montada en el slot `end` de las tres shells

**Chosen:** el molde de `features/incidents/` sin desviarse: `data/dto.ts` (DTOs camelCase),
`data/http/http-notifications-source.ts`, `data/index.ts` como **único** punto de composición,
`hooks/query-keys.ts`, `hooks/use-*.ts`, `lib/` para la copia y los destinos, `index.ts` como
frontera pública. Las tres shells importan `{ NotificationBell } from "@/features/notifications"` y
lo añaden al `end`, que pasa de `[ThemeSwitcher, Separator, LocaleSwitcher, UserMenu]` a
`[ThemeSwitcher, Separator, LocaleSwitcher, NotificationBell, UserMenu]`. `PublicShell` y
`GuestShell` no se tocan (R3.1).

Una shell importando el punto de entrada público de otra feature ya es lo que hace `UserMenu`
(`@/features/auth`), así que la regla de ESLint sobre internos de features se respeta tal cual.

### D11 — El polling vive **sólo** en el contador, y son 60 s

**Chosen:** `refetchInterval: 60_000` y `refetchIntervalInBackground: false` en la query del
contador, y nada de eso en la query del listado, que se refresca al abrirse el panel y al invalidarse
tras un acuse. `dispatch_notifications` corre cada minuto (`CADENCES` en
`backend/app/scheduler/schedule.py`), así que preguntar más a menudo no puede descubrir nada
(R3.3); y una lista que se recarga sola bajo el dedo de quien la está leyendo es un defecto, no una
mejora.

Es el primer `refetchInterval` del repositorio: hasta hoy no hay ninguno.

Rejected: SSE — heredado explícitamente del docstring de la ruta y fuera de alcance por el proposal.
Rejected: pollear también el listado — R5.1 ya obliga a reflejar el acuse sin esperar al ciclo, y eso
lo da la invalidación.

### D12 — Las claves de caché llevan tenant **y** usuario

**Chosen:** `tenantScopedKey(tenantId, "notifications-unread", userId)` y
`tenantScopedKey(tenantId, "notifications-list", userId, filters)`. El `tenantScopedKey` compartido
sólo garantiza el prefijo de tenant, y aquí eso no basta: una manager y una limpiadora comparten
tenant y no comparten bandeja. `purgeSessionCache()` ya limpia el `QueryClient` entero en los cuatro
puntos de cambio de identidad (R3.4), así que esto es la segunda línea, no la primera — y la que
sobrevive a que alguien añada un quinto punto de transición y se olvide de purgar.

Ningún store de Zustand guarda contador ni filas: el único estado de UI propio es el `open` del
panel, que va al `useShellUiStore` existente por lo dicho en D9 (`steering/frontend.md`).

### D13 — El acuse es optimista, con reversión en `onError`

**Chosen:** `onMutate` fija `read_at` en la fila cacheada y decrementa el contador; `onError`
restaura el snapshot y muestra el error traducido (R5.3); `onSettled` invalida el prefijo de las dos
queries (R5.4). Es lo que R5.3 describe literalmente, y el caso es el bueno para el optimismo: el
acuse es idempotente (D3) y sólo puede fallar por red o por `404`, nunca por un conflicto de dominio
que deje la fila en un estado que el cliente no sabría pintar.

Es el primer `onMutate` del repositorio, y el precedente vecino apunta al contrario:
`features/pricing/hooks/use-decide-recommendation.ts` rechaza el optimismo **por escrito**, porque
allí un `409` es un caso normal y un parche optimista habría mentido justo en él. Se cita para dejar
claro que esto es una divergencia razonada y no un despiste. Ver OQ2.

Rejected: sólo invalidar — más simple y coherente con `pricing`, pero deja R5.3 hablando de un
estado optimista que no existiría, y ese requisito tendría entonces que reescribirse en el proposal.

Confirmado en el gate: optimista.

### D14 — Un namespace `notifications` con el catálogo tipado por el enum

**Chosen:** `locales/{es,en}/notifications.json` con un bloque `types.<NOMBRE>` para los diecisiete,
registrado en `NAMESPACES` y en `resources` (lo exige `catalog-parity.test.ts`, que compara contra el
disco). El mapa tipo → clave vive en `features/notifications/lib/notification-copy.ts` como
`Record<NotificationType, string>` (D7), y la lectura es
`catalog[type as NotificationType] ?? "notifications:types.unknown"`, que es el genérico traducido de
R4.3. `subject`/`body` **no se pintan** (R4.2). La fecha se localiza con `Intl.DateTimeFormat(locale,
…)` en un `lib/format.ts` propio de la feature, que es lo que hacen `dashboard` y `pricing`.

### D15 — La tabla de destinos es un fichero, y sólo uno

**Chosen:** `features/notifications/lib/notification-destinations.ts` exporta
`Record<ShellProfile, Partial<Record<string, (id: string) => string>>>` con una única entrada
poblada: `workspace` → `{ incident: id => "/incidents/" + id, conversation: …, reservation: … }`.
`cleaner` y `technician` quedan declarados y **vacíos**, con el motivo escrito al lado: sus páginas
de detalle son `RoutePlaceholder` hasta `cleaner-app` y `tech-app` (R6.2). `cleaning_task` no
aparece: no hay detalle de manager. Sin `related_type`, sin `related_id`, o sin entrada en la tabla,
la fila se pinta sin enlace y sin enseñar el UUID (R6.3).

Que el perfil sea una dimensión de la tabla y no un `if` es lo que hace que R6.4 sea cierta: añadir
el destino de `cleaner-app` es rellenar una casilla.

### D16 — La campana no se pinta sin usuario resuelto

**Chosen:** `NotificationBell` lee `useAuth()` y **devuelve `null`** si `status !== "authenticated"`
o `user === null`, en lugar de lanzar como hace `useIncidents`. No es defensivo por costumbre: en
`app/(field)/cleaner/layout.tsx` y `app/(field)/tech/layout.tsx` el `AuthGuard` está **dentro** de la
shell (`<CleanerShell><AuthGuard …>{children}</AuthGuard></CleanerShell>`), así que el `Topbar` —y
con él la campana— se renderiza mientras la sesión todavía se está resolviendo y también cuando el
guard va a redirigir. Un `throw` ahí tumbaría la shell entera de las dos apps de campo.

### D17 — El SLA no se entera de nada (R1.6)

**Chosen:** ni `list_sla_breach_candidates` ni `escalation_for` ni `check_sla_breaches` mencionan
`read_at`, y no van a mencionarlo. El plazo se cierra por la acción de dominio a través de
`cancel_sla_deadline`, que es donde ya está. Sin implicación de diseño más allá de un test que fije
que leer una notificación no mueve `sla_deadline_at` ni `sla_breached`.

### D18 — `SUPER_ADMIN` queda fuera, y su superficie es una entrada de roadmap propia

**Chosen:** este change no toca el `allow` de ninguna shell, no toca `ROLE_HOME` y no monta la
campana en `app/(authenticated)/layout.tsx`. `SUPER_ADMIN` sigue sin alcanzar ninguna superficie
autenticada, exactamente como antes de este change.

El hecho, medido: `ROLE_PERMISSIONS[UserRole.SUPER_ADMIN]` es `_SELF_SERVICE` **y nada más**
(`backend/app/auth/domain/policy.py`) — `READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`,
`READ_OWN_NOTIFICATIONS`. Meterlo en `WorkspaceShell` le daría la campana rodeada de nueve enlaces
de sidebar que el backend responde con `403`, empezando por el `/dashboard` al que `roleHome` lo
manda, y con el `showProvenance` del footer fallando también porque tampoco tiene
`_BUILD_PROVENANCE_READ`. Y hoy `/welcome` tampoco lo acoge: hace `router.replace(roleHome(role))`,
que es `/dashboard`, que lo rebota a `/login?denied=role`.

Lo que `SUPER_ADMIN` necesita no es un hueco en una shell ajena: es una consola de plataforma —
visibilidad sobre todos los tenants sin pertenecer a ninguno, alta de tenants y de usuarios
(`PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`) que hoy se hace a mano contra la base de datos o
contra la API, y más adelante entrar en un tenant a inspeccionarlo. Eso es una capacidad con su
propio RBAC, su propio aislamiento (un rol que cruza tenants es la excepción exacta a la regla 1 de
`steering/security.md`) y su propia superficie. No cabe en una bandeja de notificaciones, y media
consola es peor que ninguna.

**Encargo a `/sdd:archive`**: añadir a `sdd/roadmap.md` la entrada candidata **`super-admin-console`**
— `[BE+FE]` — consola de plataforma para `SUPER_ADMIN`: shell propia fuera de los tenants, alta y
listado de tenants, alta de usuarios por rol, y la puerta —futura y con su propia decisión de
auditoría— para inspeccionar un tenant desde dentro. Su nota larga en `sdd/roadmap/super-admin-console.md`
con el contenido de este párrafo y el permiso que ya tiene medido.

Rejected: `SUPER_ADMIN` al `allow` de `app/(workspace)/layout.tsx` — arriba.
Rejected: la campana en el topbar de `(authenticated)` y quitar el rebote de `/welcome` — le daría
la bandeja sin `403`, pero convierte `/welcome` en el hogar permanente de un rol para el que fue
escrito como interstitial de un toque, y enmienda R3.1 para adelantar tres pantallas de una consola
que no existe.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Migración | `backend/alembic/versions/<rev>_notifications_read_at.py` (nuevo) | `read_at` + los dos índices de D1, sobre `down_revision = 'd4a7e18c6b93'` |
| Modelo | `backend/app/notifications/infrastructure/models.py` | Columna `read_at`; los dos `Index` en `__table_args__` |
| Dominio | `backend/app/notifications/domain/entities.py` | `read_at: datetime \| None = None` en `NotificationLog` |
| Puerto | `backend/app/notifications/domain/repositories.py` | `list_for_recipient(..., unread: bool \| None)`; `mark_read(tenant_id, user_id, log_id) -> bool`; `count_unread(tenant_id, user_id) -> int`; `mark_all_read(tenant_id, user_id) -> int` |
| Repositorio | `backend/app/notifications/infrastructure/repositories.py` | Las tres consultas nuevas (D3, D4, D6) y la condición `unread` de D5 |
| Casos de uso | `backend/app/notifications/application/use_cases.py` | `MarkNotificationReadUseCase`, `CountUnreadNotificationsUseCase`, `MarkAllNotificationsReadUseCase`; `ListOwnNotificationsUseCase` acepta `unread` |
| Excepciones | `backend/app/notifications/domain/exceptions.py` | `NotificationNotFoundError` para el `404` de D3 |
| API | `backend/app/notifications/api/{router,schemas,dependencies}.py` | Tres rutas nuevas, `read_at` y `NotificationType \| str` en `NotificationResponse`, `UnreadCountResponse`, `MarkAllReadResponse`, y tres proveedores de caso de uso |
| API (errores) | `backend/app/notifications/api/errors.py` (nuevo), `backend/app/main.py` | `NotificationNotFoundError` → `404` en el sobre de PRD §23, con el molde de `app/{timeline,access}/api/errors.py`, y su registro. **Añadido al cuadro en `/sdd:run` (2026-08-29)**: el módulo no tenía `errors.py` porque su única ruta no podía fallar de forma accionable, y D3 exige que los tres casos de R1.4 salgan por un cuerpo idéntico — hacerlo en el router sería lógica en el router, que `steering/backend.md` prohíbe. Es convención del proyecto aplicada, no decisión nueva |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerados en el mismo PR (R2.4) — ojo al rodeo de `sdd/project.md` para hacerlo desde un worktree |
| Tests backend | `backend/tests/notifications/test_api.py`, `test_repositories.py`, nuevo `test_read_isolation.py`; `backend/tests/test_route_authorization.py` | Las tres rutas al snapshot de rutas protegidas; aislamiento de tenant sobre el acuse (R1.5, regla 1) |
| Feature FE | `frontend/features/notifications/**` (nuevo) | `data/{dto.ts,index.ts,http/http-notifications-source.ts}`, `hooks/{query-keys.ts,use-notifications.ts,use-unread-count.ts,use-mark-read.ts,use-mark-all-read.ts}`, `lib/{notification-copy.ts,notification-destinations.ts,format.ts,error-mapping.ts}`, `components/{notification-bell.tsx,notification-inbox-sheet.tsx,notification-row.tsx}`, `index.ts` |
| Shells | `frontend/features/shell/components/{workspace,cleaner,technician}-shell.tsx` | `NotificationBell` en el slot `end`; sus tres tests de shell acompañan |
| Estado de UI | `frontend/features/shell/state/use-shell-ui-store.ts` | Un `open` más para el panel, por el cierre en navegación de D9 |
| i18n | `frontend/locales/{es,en}/notifications.json` (nuevos), `frontend/lib/i18n/resources.ts` | Namespace nuevo + registro en `NAMESPACES` y `resources` |
| Docs | `docs/access-notifications.md`, `README.md` si procede | La bandeja pasa de «se listan, no se acusan» a ciclo cerrado |
| Docs (archivado) | `docs/diagrams/2026-08-23_autohost-er-entidades.png` | Regenerar: `read_at` mueve el recuento de columnas de 425 a 426; **no** es clave ajena, así que entidades y relaciones no se mueven (mismo caso que `eta_at`/`materials` en `tech-cycle-completion`) |
| Specs (archivado) | `sdd/specs/access-notifications.md`, `api-contract.md`, `frontend-foundation.md`, nuevo `notifications-inbox-web.md` | Ver §Data & interfaces |

## Data & interfaces

**Esquema.** Una columna: `notification_logs.read_at TIMESTAMPTZ NULL`. Dos índices:
`ix_notification_logs_tenant_id_recipient_user_id_created_at` y el parcial
`ix_notification_logs_unread ... WHERE read_at IS NULL`. Sin variables de entorno nuevas, sin
configuración nueva, sin eventos nuevos.

**API** (las tres nuevas, todas con `READ_OWN_NOTIFICATIONS` y el destinatario derivado del JWT):

| Método | Ruta | Respuesta |
|---|---|---|
| `GET` | `/api/v1/notifications?page&per_page&unread` | `NotificationPageResponse` (envelope PRD §23 intacto), con `read_at` en cada fila |
| `GET` | `/api/v1/notifications/unread-count` | `{"unread": int}` |
| `POST` | `/api/v1/notifications/{notification_id}/read` | `204`, o `404` para inexistente / de otro usuario / de otro tenant |
| `POST` | `/api/v1/notifications/read-all` | `{"updated": int}` |

**Contrato.** `NotificationResponse.notification_type` pasa de `string` a
`anyOf[NotificationType, string]`, lo que **añade** `components["schemas"]["NotificationType"]` al
contrato publicado (los diecisiete nombres) sin estrechar el valor aceptado. `read_at` es un campo
añadido: por lo que `steering/documentation.md` deja dicho, un campo añadido lo cubren los tests y
no el typecheck, porque TypeScript es estructural.

**Specs a modificar al archivar.** En `access-notifications.md`, el criterio «THE SYSTEM SHALL **no**
ofrecer "marcar como leída" ni añadir una columna `read_at` … El frontend lleva su propio estado
hasta que una entrada de roadmap decida lo contrario» se **sustituye**, y con él la frase «El ciclo
in-app queda a medias a propósito». En `frontend-foundation.md`, la frase que fija el slot `end` como
`[ThemeSwitcher, Separator, LocaleSwitcher, UserMenu]` pasa a cinco elementos. En `api-contract.md`,
las tres rutas y los dos campos.

## Risks & mitigations

* **La regeneración del contrato no funciona tal cual desde un worktree enlazado.** `npm
  run api:generate` y `npm run api:check` fallan porque el contenedor `frontend` sólo monta
  `./frontend`. Mitigación: el rodeo con `docker compose cp` documentado en `sdd/project.md`, usado
  y verificado en `dashboard-api`. Es un coste conocido de R2.4, no un descubrimiento.
* **`npm test` arranca con dos ficheros en rojo ajenos al change** (`ENOENT` en
  `features/provenance/workflow-contract.test.ts` y `lib/config/build-identity-contract.test.ts`).
  Mitigación: los `docker compose cp` de `sdd/project.md`, y **medir** la cifra de partida antes de
  tocar nada en vez de compararla con un número recordado.
* **La campana pone a todos los usuarios conectados a pedir cada 60 s** una consulta que hoy no
  existe. Mitigación: el índice parcial de D1 y que el contador sea un `count(*)` sin filas. El
  riesgo real que quedaba —`list_for_recipient` sin índice por destinatario— lo cierra el otro
  índice, y era anterior a este change.
* **`SUPER_ADMIN` tiene el permiso y no llega a ninguna shell.** Ver la corrección de A3 en Open
  questions: no es un riesgo de este diseño, es una afirmación del proposal que no se sostiene.
* **Un `notification_type` desconocido llega a producción antes que su traducción.** Es el caso que
  R4.3 cubre y D14 implementa con el genérico traducido; el `Record` tipado de D7 impide que el
  hueco lo abra un tipo *conocido*.

## Open questions

Las cuatro se resolvieron en el gate del 2026-08-29. Se conservan con su resolución porque cada una
cambió algo fuera de este documento.

**OQ1 — ¿Panel `Sheet` o pantalla propia? → panel** (D9). Una campana en tres shells y una sola
superficie, contra tres rutas con tres `AuthGuard` distintos, tres descriptores y tres filas en
`app/route-coverage.test.ts`. La pantalla propia, si algún día un manager vive en la bandeja, es una
entrada de roadmap suya.

**OQ2 — ¿Acuse optimista o sólo invalidación? → optimista** (D13). Es lo que R5.3 describe, y el
acuse es idempotente y sólo falla por red o `404`. Diverge del precedente de
`features/pricing/hooks/use-decide-recommendation.ts`, que rechaza el optimismo por escrito porque
allí un `409` es normal; la divergencia queda razonada en D13 para que no se lea como despiste.
R5.3 del proposal **no** se toca: se implementa tal como está escrito.

**OQ3 — `SUPER_ADMIN` → fuera de alcance, con entrada de roadmap propia** (D18). A3 del proposal
afirmaba que «los cinco roles quedan cubiertos por las tres shells»; su primera mitad es cierta (el
permiso vive en `_SELF_SERVICE`) y la segunda es falsa (`roleHome` lo manda a `/dashboard` y el
`AuthGuard` de `app/(workspace)/layout.tsx` lo rebota a `/login?denied=role`; `/welcome` hace el
mismo rebote). **A3 queda enmendado en `proposal.md`** a cuatro roles, con el motivo. Lo que
`SUPER_ADMIN` necesita —consola de plataforma cross-tenant, alta de tenants y usuarios,
inspección de un tenant— sale como candidata `super-admin-console`, encargada a `/sdd:archive` en
D18.

**OQ4 — La nota de roadmap se contradecía → corregida ahora.**
`sdd/roadmap/notifications-inbox-web.md` decía «no necesita … ni una migración» mientras su propio
párrafo final declaraba lo contrario al resolver el punto (1). Arreglado en este mismo árbol.
