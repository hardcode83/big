# Sesión de autenticación del frontend

Esta capability conecta el frontend con los endpoints de autenticación del
backend. La especificación EARS y sus decisiones viven en la
[propuesta del change](../sdd/changes/frontend-auth-session/proposal.md); esta
página describe el uso y los límites operativos.

## Uso

1. Abre `/login` e introduce el correo electrónico y la contraseña.
2. Tras un login correcto, el frontend carga `/auth/me` y usa la identidad,
   el rol y el tenant para el contexto de la interfaz.
3. Las superficies de workspace, cleaner y technician redirigen a `/login`
   cuando no hay sesión. La ruta interna de origen se conserva de forma segura.
4. Cerrar sesión llama a `/auth/logout` cuando es posible, elimina la sesión
   local y vuelve a `/` (la raíz re-evalúa la cookie
   `autohostai.session.present`, recién purgada, y renderiza la landing pública).
   El botón vive en el `UserMenu` del topbar de las tres shells autenticadas
   (workspace, cleaner, technician); pedir confirmación con un `AlertDialog`
   evita cierres accidentales en dispositivos compartidos. El portal guest no
   expone el menú porque su acceso es por token en la URL, sin sesión que cerrar.

## Mini-landing post-login (CLEANER / TECHNICIAN)

Después de un login sin `?returnTo=`, los roles `CLEANER` y `TECHNICIAN`
aterrizan en `/welcome?role=<rol>` en lugar de directamente en su shell
(`/cleaner`, `/tech`). El *qué hace* exacto está en la propuesta del
change ([`R2`](../sdd/changes/frontend-auth-role-routing/proposal.md#r2--mini-landing-autenticada-post-login-para-field-users));
esta página es el *cómo se opera* de la interstitial — qué ve el field
user, cómo se enruta y cuándo se dispara.
aterrizan en `/welcome?role=<rol>` en lugar de directamente en su shell
(`/cleaner`, `/tech`). La mini-landing existe para un perfil muy concreto:
**field user en dispositivo compartido, un solo destino útil**. La
interstitial protege contra un toque a destiempo que mande a la persona al
shell equivocado y le da un punto de retorno claro si se logueó con la cuenta
de otra persona.

### Qué ve

- `Brand` + `UserMenu` (slot `end` del topbar, sin sidebar, sin
  `bottomNavigation`, sin footer ni `ThemeSwitcher`/`LocaleSwitcher` —
  viven en `frontend/app/(authenticated)/layout.tsx`).
- Un único `StatePanel` con título `auth.welcome.title`, descripción
  `auth.welcome.body` y un botón cuyo `href` sale de `roleHome(<rol>)` —
  para `CLEANER` es `auth.welcome.cta.CLEANER` ("Ir a mis tareas") y para
  `TECHNICIAN` es `auth.welcome.cta.TECHNICIAN` ("Ir a mis incidencias").
  El `aria-label` está localizado en ambos locales.

### Cómo se enruta

- `LoginForm.handleSubmit` (R2 #1) lee el rol del valor resuelto de
  `login()` — el render-closure `user` aún es `null` durante el await, y
  rutear desde ahí bypassaba la mini-landing (ver el JSDoc de
  `useAuth().login`).
- La página `/welcome` está cubierta por `AuthGuard` **sin** `allow`:
  cualquier usuario autenticado entra, y el `?role` decide el shell. Si
  falta o no coincide con el rol del usuario autenticado, la página
  redirige sin mostrar contenido — un `StatePanel aria-busy` con
  `auth.redirecting` evita el flash en blanco durante el redirect
  (defensa contra URL tampering).

### Quién pasa por ella

| Rol | Sin `?returnTo` | Con `?returnTo` segura | Tras un bounce de `AuthGuard` |
|---|---|---|---|
| `CLEANER` | `/welcome?role=CLEANER` → `/cleaner` | `?returnTo` (validada) | `?denied=role` → `/cleaner` |
| `TECHNICIAN` | `/welcome?role=TECHNICIAN` → `/tech` | `?returnTo` (validada) | `?denied=role` → `/tech` |
| `TENANT_OWNER` / `PROPERTY_MANAGER` | `/dashboard` (sin interstitial) | `?returnTo` (validada) | `?denied=role` → `/dashboard` |

`SUPER_ADMIN` (cuando entre en MVP) no tendrá interstitial hasta que se
defina en `saas-cross-tenant`.

### Quién NO usa `/welcome`

- El portal guest (`/guest/[token]`): es acceso por token, no por login.
- El workspace (`/(workspace)`): va directo a `/dashboard` tras login.
- `AuthGuard` con `allow` específico: si un `CLEANER` pega `/dashboard` en
  la URL, el guard lo expulsa con `?denied=role` (UX-only, RBAC sigue en el
  backend).

## Sesión persistente entre reloads (`auth-session-persistence`)

El access JWT vive únicamente en memoria dentro del runtime del navegador —
eso no cambió. El refresh JWT, en cambio, **ya no vive en memoria ni en
ningún almacenamiento accesible por JavaScript**: viaja como cookie
`HttpOnly` (`autohostai.session.refresh`, ver `docs/auth-tenancy.md` para el
juego completo de atributos), así que un reload completo, el cierre de la
pestaña o un runtime nuevo **no** elimina la sesión mientras la cookie siga
viva (`Max-Age` = `JWT_REFRESH_TOKEN_DAYS`).

Cada runtime nuevo (un reload, una pestaña recién abierta) arranca sin
access token en memoria y lanza un `POST /auth/refresh` silencioso al
montar `AuthProvider` (R5, design D8) — con `credentials: "include"`, sin
esperar ninguna interacción del usuario. Si la cookie sigue siendo válida,
la sesión se restaura sin pasar por el formulario de login; si no, el
estado resuelve a `anonymous` sin error visible, y el usuario solo ve el
login si navega a una ruta protegida (R5.3). Este mount-refresh está
deduplicado a nivel de módulo (D11): dos `AuthProvider` montados en el
mismo tick (StrictMode, dos árboles) comparten una única petición.

Las peticiones autenticadas que reciben `401` pueden ejecutar, además, un
único refresh coordinado y reintentar una vez la petición original —
mecanismo previo a este change, sin cambios. Login, refresh y peticiones
sin bearer quedan fuera de ese mecanismo; logout ya no queda fuera del
todo: su propio `401` (un access token expirado) se recupera igual que el
de cualquier otro endpoint autenticado.

**Aislamiento entre pestañas** (R6): cada pestaña es su propio runtime de
JavaScript, así que el access token y el estado de refresh son
por-pestaña — no hay canal que sincronice un logout o una sesión expirada
entre pestañas salvo el que cada una descubre por su cuenta (su propio
próximo `401`, o su propio próximo mount-refresh).

## Límites de seguridad

- Los guards son client-side y sirven para UX; no protegen HTML server-rendered
  ni sustituyen JWT, RBAC o tenant isolation del backend.
- El access token vive solo en memoria; no se guarda en `localStorage`,
  `sessionStorage`, IndexedDB, Zustand ni ningún almacenamiento persistente. El
  refresh token vive en la cookie `HttpOnly` — el frontend nunca la lee ni la
  pasa por JavaScript en ningún punto (ni en el cuerpo de una petición, ni en
  un store); solo el navegador la adjunta automáticamente.
- El frontend no decide permisos de negocio ni implementa aislamiento de tenant.
- Los errores del backend no se muestran directamente; los estados visibles se
  resuelven mediante el namespace `auth` en ES y EN.
- No hay BFF, middleware de autenticación ni sesión server-side en esta
  capability — el Route Handler de `frontend/app/api/[...path]/route.ts` es un
  proxy de cabeceras (design `auth-session-persistence` D2), no un punto que
  retenga o interprete la sesión.
