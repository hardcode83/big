# Bandeja de notificaciones in-app (campana + panel)

## Purpose

La superficie web desde la que un usuario autenticado **lee y acusa** sus propias
notificaciones. Es la mitad de cliente del canal `IN_APP` de PRD §14, cuya mitad de servidor
—las cuatro rutas, la columna `read_at`, sus índices y su semántica— vive en
[`access-notifications.md`](access-notifications.md) §«La bandeja in-app». Sin ella,
`InAppNotificationAdapter` declaraba por escrito que «la fila *es* la entrega» mientras ningún
humano podía llegar a esa fila: toda la comunicación interna del sistema —limpieza asignada,
técnico asignado, incidencia rechazada, aprobación del propietario, escalación de huésped,
incumplimiento de SLA— terminaba en `notification_logs` y solo se leía con SQL.

**No es una ruta.** Es una campana en el `Topbar` de las tres shells autenticadas que abre un
panel `Sheet`. Deliberado: cada grupo de rutas de la app admite un juego de roles distinto en su
`AuthGuard`, así que una pantalla propia costaría tres pantallas y tres registros, mientras que
la campana cuesta un componente montado en tres sitios. Por eso no hay descriptor en
`route-registry.ts`, ni breadcrumb, ni entrada de navegación.

Es una capa de presentación pura: no añade ni relaja regla de negocio ni de acceso alguna, y el
backend sigue siendo la única autoridad sobre qué filas ve cada usuario.

## Requirements

### R1 — La campana, en las tres shells autenticadas

- THE SYSTEM SHALL montar `<NotificationBell profile={…} />` en el slot `end` del `Topbar` de
  `WorkspaceShell`, `CleanerShell` y `TechnicianShell`, entre `LocaleSwitcher` y `UserMenu`, y
  SHALL NOT montarlo en `PublicShell` ni en `GuestShell`, que no llevan JWT.
- THE SYSTEM SHALL reutilizar los slots `start`/`end` que `Topbar` ya expone: la firma del
  componente de chrome **no cambia**, y cada shell añade un elemento al fragmento que ya pasaba.
- IF no hay identidad autenticada resoluble (`useNotificationsIdentity()` devuelve `null`), THEN
  THE SYSTEM SHALL renderizar `null` y SHALL NOT lanzar: en las shells de campo el `AuthGuard`
  vive **dentro** de la shell, así que la campana se monta antes de que haya sesión.
- WHILE el usuario tiene al menos una notificación no leída, THE SYSTEM SHALL pintar el contador
  sobre la campana; IF el contador es cero, THEN THE SYSTEM SHALL pintar la campana sin
  distintivo numérico.
- WHERE el contador supera `MAX_BADGE_COUNT = 99`, THE SYSTEM SHALL pintar `99+`
  (`bell.overflowCount`). El tope es **de presentación**: `GET /notifications/unread-count`
  devuelve la cuenta exacta y el backend no la acota.
- THE SYSTEM SHALL dar al control un nombre accesible traducido que **incluya el número**:
  `«Notificaciones, 3 sin leer»` cuando hay no leídas y `«Notificaciones, Sin notificaciones
  nuevas»` cuando no las hay, con plural i18n (`bell.unreadCount_one`/`_other`). El icono es
  `aria-hidden`, y el distintivo numérico también: el número lo anuncia el `aria-label`, no una
  segunda lectura del badge.

### R2 — El contador se refresca por polling, y solo el contador

- THE SYSTEM SHALL refrescar el contador con `refetchInterval = UNREAD_POLL_INTERVAL_MS = 60_000`
  y `refetchIntervalInBackground: false`. La cadencia hereda la decisión de
  `access-notifications`: `dispatch_notifications` corre cada minuto, así que pedir más a menudo
  no puede descubrir nada nuevo. SSE queda fuera y no se vuelve a decidir aquí.
- THE SYSTEM SHALL NOT poner en polling el **listado**: la campana pregunta un `count(*)`, el
  panel se refresca al abrirse, al paginar y al invalidarse tras un acuse.
- THE SYSTEM SHALL deshabilitar la consulta (`enabled: false`) mientras no haya identidad, bajo
  la clave inerte `["notifications-no-session"]`.
- THE SYSTEM SHALL escopar las claves de TanStack Query por tenant **y por usuario**
  (`tenantScopedKey(tenantId, "notifications-unread", userId)` y
  `(…, "notifications-list", userId[, filters])`), de modo que dos identidades no puedan
  compartir caché por construcción.
- WHEN la identidad autenticada cambia —logout, expiración o cambio de usuario—, THE SYSTEM SHALL
  dejar de mostrar el contador anterior apoyándose en la purga del `QueryClient` que
  [`frontend-auth-session.md`](frontend-auth-session.md) ya declara, y SHALL NOT introducir un
  almacén propio que la sobreviva.

### R3 — El panel: un `Sheet` mobile-first con sus tres estados

- THE SYSTEM SHALL abrir el listado en un `Sheet` con `side="bottom"` y
  `max-h-[80vh] overflow-y-auto`, cuyo disparador es la propia campana.
- THE SYSTEM SHALL guardar el estado abierto/cerrado en el store de UI de la shell
  (`notificationsOpen` / `setNotificationsOpen` en `use-shell-ui-store.ts`) y **no** en estado
  local del componente, y SHALL incluirlo en `closeOverlays()`, de modo que `OverlayAutoCloser` lo
  cierre al navegar como al resto de overlays. Es estado efímero de interfaz: **no se persiste**.
- THE SYSTEM SHALL renderizar exactamente uno de estos estados: **carga** (`LoadingState`),
  **error** (`ErrorState` con reintento real sobre `refetch`), **vacío** (`EmptyState`) o el
  listado, todos con texto traducido y sobre los primitivos compartidos de `components/states/`.
- THE SYSTEM SHALL paginar de veinte en veinte (`PER_PAGE = 20`) con controles «anterior» /
  «siguiente» deshabilitados en los extremos y un indicador `«Página {{page}} de
  {{totalPages}}»`, sobre el envelope paginado de PRD §23. El panel lista **todas** las
  notificaciones: no aplica el filtro `unread` que la ruta ofrece.
- WHEN una mutación de acuse falla, THE SYSTEM SHALL mostrar el error traducido en un
  `role="alert"` dentro del panel, mapeado del `status` HTTP: `401 → errors.session`,
  `403 → errors.forbidden`, `404 → errors.notFound`, resto `errors.generic`.

### R4 — Cada fila se lee en el idioma del usuario, no en el del operador

- THE SYSTEM SHALL componer el texto principal de cada fila desde su `notification_type`
  traducido (`notifications:types.<MIEMBRO>`), y SHALL NOT usar `subject` ni `body`: están
  escritos en inglés, para un operador, y llevan UUID en crudo. El DTO del frontend **ni siquiera
  los transporta**, de modo que pintarlos no es una opción disponible.
- THE SYSTEM SHALL cubrir los **dieciocho** miembros de `NotificationType` en `locales/es` y
  `locales/en` (los diecisiete originales más `REVIEW_RESPONSE_APPROVED`, que `revenue-reviews`
  introduce para avisar al propietario del tenant cuando una respuesta a reseña pasa a
  `APPROVED`). La exhaustividad la garantiza el tipo:
- IF llega un `notification_type` que la interfaz no conoce —la columna es `String(100)` libre y
  admite valores anteriores al enum—, THEN THE SYSTEM SHALL pintar `types.unknown` traducido y
  SHALL NOT romper el renderizado. La búsqueda en la tabla usa `Object.hasOwn`, de modo que un
  valor como `"valueOf"` no resuelva contra el prototipo.
- THE SYSTEM SHALL mostrar la fecha en un `<time dateTime={…}>` formateada con
  `Intl.DateTimeFormat` en el idioma activo (`dateStyle: "medium"`, `timeStyle: "short"`).
- THE SYSTEM SHALL distinguir las no leídas visualmente (punto `bg-primary` y peso de fuente) **y
  para lectores de pantalla** (un `sr-only` «Sin leer» / «Unread»); el punto es `aria-hidden`, y
  las leídas reservan su hueco con un espaciador para que la columna no baile.

### R5 — Acuse optimista, y una guarda de generación de sesión

- WHEN el usuario abre o acusa una fila no leída, THE SYSTEM SHALL invocar
  `POST /notifications/{id}/read` y SHALL reflejar el contador nuevo **sin esperar** al siguiente
  ciclo de polling: `onMutate` cancela las consultas en vuelo de ambas familias, guarda el
  contador y las páginas, sella `readAt` en la fila y decrementa el contador con suelo en cero.
- THE SYSTEM SHALL sellar la fila **solo si estaba sin leer**, y decrementar el contador solo si
  hubo sello: acusar dos veces no puede restar dos.
- THE SYSTEM SHALL ofrecer «marcar todas como leídas» sobre `POST /notifications/read-all`, que
  abarca **todas** las no leídas del usuario y no la página mostrada; el control se pinta solo
  cuando la lista no está vacía y se deshabilita mientras la mutación está en vuelo.
- IF la mutación falla, THEN THE SYSTEM SHALL revertir el estado optimista —contador y páginas— y
  mostrar el error traducido, sin dejar la fila pintada como leída. La reversión del contador
  distingue tres casos: sin parche, no toca nada; con parche y **sin** instantánea previa,
  `resetQueries` sobre la clave exacta (no `removeQueries`, que dejaría a los observadores sin
  apuntar); con instantánea, la restaura.
- WHERE la generación de sesión ha cambiado entre `onMutate` y `onError`, THE SYSTEM SHALL
  **omitir la reversión por completo**: el snapshot pertenece a la sesión saliente y reescribirlo
  repintaría sus filas sobre un `QueryClient` que `purgeSessionCache()` acaba de vaciar. La
  generación vive en `lib/auth/session-store.ts` y se mueve en los dos escritores de tokens; el
  listener de sesión expirada llama ahora a `clearSessionTokens()` para que también se mueva en la
  purga por `401`.
- THE SYSTEM SHALL invalidar ambas familias de claves —contador y listado— en `onSettled`, tanto
  en éxito como en fallo, y SHALL NOT duplicar el estado del servidor en un store de Zustand
  (`steering/frontend.md`). Las mutaciones no reintentan (`retry: false`).

### R6 — Enlazar solo donde hay destino vivo

- THE SYSTEM SHALL declarar los destinos en **un único sitio**
  (`features/notifications/lib/notification-destinations.ts`), indexado por perfil de shell y por
  `related_type`, de modo que añadir un destino cuando entreguen `cleaner-app` o `tech-app` sea una
  entrada más y no una búsqueda por componentes.
- THE SYSTEM SHALL enlazar, en el perfil `workspace`, `incident → /incidents/{id}`,
  `conversation → /conversations/{id}` y `reservation → /reservations/{id}`.
- THE SYSTEM SHALL dejar **vacías** las tablas de `cleaner`, `technician`, `public`, `guest` y
  `authenticated`, y SHALL NOT enlazar `related_type = "cleaning_task"` en ningún perfil: no hay
  página de detalle de manager para una tarea de limpieza, y las de campo siguen siendo
  `RoutePlaceholder`. Es el tipo más frecuente y se pinta sin enlace a propósito.
- IF `related_type` o `related_id` son `null`, o el tipo no está en la tabla del perfil, THEN THE
  SYSTEM SHALL renderizar la fila como `<button>` en vez de `<Link>` y SHALL NOT mostrar el
  identificador en crudo al usuario.
- THE SYSTEM SHALL resolver la tabla con `Object.hasOwn` y SHALL exigir que el `href` construido
  sea una cadena que empiece por `/` antes de navegar: sin esa guarda, una clave heredada del
  prototipo rompería el render de la lista entera.

### R7 — La frontera Server/Client de la shell, partida en dos puertas

- THE SYSTEM SHALL mantener `@/features/shell` como **puerta de cliente**, exportando únicamente
  `PageHeader`, el tipo `ShellProfile` y `useNotificationsPanel`/`NotificationsPanelState`, y SHALL
  publicar las cinco shells y `routeMetadata` por `@/features/shell/server`.
- THE SYSTEM SHALL importar desde `@/features/shell/server` en todos los layouts y páginas de
  `frontend/app/` que componen shells (29 ficheros), lo cual es legal porque la regla de ESLint que
  prohíbe importar internos de otra feature solo alcanza a los ficheros **bajo** `features/`.
- THE SYSTEM SHALL exponer el estado del panel en un módulo `"use client"` propio y estrecho
  (`features/shell/state/use-notifications-panel.ts`), no en el barrel general.

**Por qué existe R7, y qué clase de verificación faltaba.** Un Client Component
(`notification-inbox-sheet.tsx`) importaba `useNotificationsPanel` del barrel general, y ese barrel
reexportaba las cinco shells y `routeMetadata`, que alcanzan `server-only` (las shells vía
`lib/theme/server`; `routeMetadata` vía `lib/metadata/create-route-metadata → lib/i18n/server`).
`tsc --noEmit` quedó limpio y las 1.749 pruebas en verde: **solo `next build` ejecuta esa
comprobación**, y por eso el fallo apareció en el job `provenance-contract` del PR #136 y no antes.
La corrección viajó en su propio commit sobre la rama (`a23308d`), y el guard de CI que impide la
reincidencia llegó justo después (PR #137).

## Estado y deuda conocida

- **El repaso manual del flujo no se ejecutó**, y se aceptó a sabiendas. Un worktree enlazado no
  publica puertos, y `make up PORT_OFFSET=<n>` sirve la página pero **no la hidrata**
  (`sdd/project.md`); arreglar eso habría sido cambiar la configuración de la app para poder
  mirarla, que no es mirarla. Cada pieza del flujo sí tiene test de componente sobre DOM real —la
  campana con su contador y su nombre accesible, los tres estados del panel, la paginación, el
  acuse optimista bajando el contador antes de que responda el servidor, la reversión al fallar,
  «marcar todas» y el enlace a `/incidents/[id]`—. **El riesgo residual que ningún test de DOM
  cierra** es que la campana se vea bien junto a los otros cuatro controles del topbar y que el
  `Sheet` sea usable en un móvil real; se verifica en `dev` tras el despliegue y, si algo falla
  ahí, es ajuste visual y no comportamiento.
- **Dos grietas de semántica en `frontend/lib/auth/`** que esta bandeja destapó por ser el primer
  consumidor de mutaciones optimistas del frontend: `refresh()` purga la caché sin mover la
  generación de sesión (latente hoy, porque ningún `useAuth()` desestructura `refresh`), y limpiar
  tokens al expirar la sesión anula a propósito una guarda de `refresh-coordinator.ts`. No se
  arreglaron aquí porque cambian la semántica de un módulo compartido; tienen entrada de roadmap
  propia, `auth-session-generation-semantics`, con los dos interleavings escritos.
- **El `404` del acuse no está declarado en el contrato publicado**: lo produce el manejador de
  `NotificationDomainError` a nivel de aplicación, que FastAPI no ve. Detalle y alcance en
  [`access-notifications.md`](access-notifications.md) §«La bandeja in-app».

## Key files

- `frontend/features/notifications/index.ts` — barrel público de la feature.
- `frontend/features/notifications/components/` — `notification-bell.tsx` (campana, badge con tope
  99, nombre accesible con el número), `notification-inbox-sheet.tsx` (`Sheet` inferior, cuatro
  estados, paginación, «marcar todas»), `notification-row.tsx` (punto de no leída, copy por tipo,
  `<time>` localizado, `<Link>` o `<button>` según destino).
- `frontend/features/notifications/hooks/` — `use-unread-count.ts` (polling de 60 s),
  `use-notifications.ts` (listado sin polling), `use-mark-read.ts` y `use-mark-all-read.ts`
  (mutaciones optimistas con guarda de generación de sesión), `restore-count.ts` (los tres casos de
  reversión del contador), `query-keys.ts` (claves por tenant **y** usuario).
- `frontend/features/notifications/lib/` — `notification-copy.ts`
  (`Record<NotificationType, string>` exhaustivo por tipo), `notification-destinations.ts` (la
  única tabla de destinos), `error-mapping.ts` (status HTTP → clave i18n), `format.ts` (fecha
  localizada).
- `frontend/features/notifications/data/` — DTO y fuente HTTP sobre el transporte central; consume
  los tipos generados del contrato.
- `frontend/features/shell/index.ts` (puerta de cliente) y `frontend/features/shell/server.ts`
  (puerta de servidor); `frontend/features/shell/state/use-notifications-panel.ts`.
- `frontend/features/shell/components/{workspace,cleaner,technician}-shell.tsx` — el montaje en el
  slot `end` del `Topbar`.
- `frontend/features/shell/state/use-shell-ui-store.ts` — `notificationsOpen` efímero, incluido en
  `closeOverlays()`.
- `frontend/locales/{es,en}/notifications.json` — namespace `notifications` (17 tipos + `unknown`,
  `bell.*`, `panel.*`, `states.*`, `errors.*`), registrado en `frontend/lib/i18n/resources.ts`.
- Mitad de servidor: `backend/app/notifications/` y
  [`access-notifications.md`](access-notifications.md) §«La bandeja in-app».
