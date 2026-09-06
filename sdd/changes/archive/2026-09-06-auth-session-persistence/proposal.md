# Proposal: auth-session-persistence

## Why

La sesión autenticada del frontend **no sobrevive a una pestaña nueva ni a un reload**: el
diseño deliberado de `frontend-auth-session` mantiene access y refresh JWT únicamente en
memoria del runtime JS (`session-store.ts`), de modo que cualquier runtime nuevo empieza
anónimo y obliga a un login manual completo. Esa elección se justificó por seguridad
frente a XSS, pero el coste de UX recae sobre el perfil equivocado para este producto:
managers, cleaners y technicians abren la app varias veces al día, a menudo en más de
una pestaña o dispositivo móvil, y hoy cada apertura es un login manual.

La fuente del problema, verificada en código:
- `backend/app/auth/api/schemas.py:115` — `LoginResponse` devuelve `refresh_token` en el
  body de `POST /auth/login`.
- `backend/app/auth/api/schemas.py:26` — `RefreshRequest` exige `refresh_token` en el
  body de `POST /auth/refresh`.
- `backend/app/auth/api/router.py:86` — el handler de refresh lee de `body.refresh_token`.
- No existe ninguna ruta de `Set-Cookie` ni de lectura de cookie en ninguno de los dos
  endpoints.
- `frontend/lib/auth/session-store.ts` mantiene ambos tokens en memoria y los pierde
  al recargar.
- `sdd/specs/frontend-auth-session.md:31-48` documenta la invariante «solo en memoria»
  como un requisito y descarta explícitamente cookies `httpOnly`/BFF como fuera de
  alcance, sin más razón que el recorte de ese change.

Esta entrada reabre ese recorte: cambia el transporte del refresh token a una cookie
`httpOnly` + `Secure` + `SameSite=Strict` (invisible a JS, inmune al vector de robo que
memoria-pura ya evita) y deja el access token de vida corta donde está hoy. Una pestaña
nueva o un reload dispara un refresh silencioso contra `/auth/refresh` leyendo la
cookie, sin que el frontend toque el refresh token en ningún momento.

Roadmap note: `sdd/roadmap/auth-session-persistence.md` (entrada registrada el
2026-09-04, `needs: frontend-auth-session`, `completes: frontend-auth-session`,
`size: M`, `kind: feature`).

## What changes

- `POST /api/v1/auth/login`: deja de devolver `refresh_token` en el body; emite una
  cookie `httpOnly Secure SameSite=Strict` con nombre `autohostai.session.refresh` y
  `Max-Age` igual a la expiración vigente del refresh token (7 días, según PRD).
  El access token **sigue** viajando en el body porque JS debe leerlo para llevarlo
  a memoria.
- `POST /api/v1/auth/refresh`: deja de aceptar `refresh_token` en el body; lo lee de
  la cookie de request. Devuelve el nuevo access token en el body y rota la cookie
  de refresh (nuevo valor, misma expiración deslizante). Si la cookie está ausente,
  expirada o revocada, devuelve `401` con el mismo contrato que hoy.
- `POST /api/v1/auth/logout`: invalida la familia del refresh token en servidor
  (comportamiento ya existente, ver `auth-tenancy.md`) **y** purga la cookie con
  `Set-Cookie ... Max-Age=0` en la response. El frontend también invoca este
  endpoint en el `logout()`, igual que hoy.
- `frontend/lib/auth/session-store.ts`: el campo `refreshToken` se elimina; solo
  persiste el access token en memoria. `auth-provider.tsx` gana una llamada de
  refresh silencioso al montar (antes de decidir `anonymous` vs `authenticated`),
  para que un reload arranque con un estado breve de carga y resuelva a la sesión
  persistida.
- CORS / dev infra: la cookie cross-origin entre frontend y backend exige
  `Access-Control-Allow-Credentials: true`, `Allow-Origin` con origen explícito
  (no `*`) y `SameSite` coherente con el esquema del request. En dev, los stacks
  de los worktrees usan `PORT_OFFSET` (HTTP) — la bandera `Secure` se aplica
  condicionalmente según el esquema de la request para no romper el login local.
  En prod va por Cloudflare Tunnel (HTTPS), donde `Secure` sí se aplica siempre.
- Tests: `backend/tests/auth/*` y demás tests que hoy llaman a `/auth/login` o
  `/auth/refresh` con `refresh_token` en el body cambian a fijar la cookie en el
  `TestClient` (que ya soporta `cookies=`). **No** se publica un periodo dual
  body+cookie.

## Requirements

### R1 — `/auth/login` emite refresh en cookie httpOnly

**As a** backend de autenticación, **I want** emitir el refresh token en una
cookie `httpOnly Secure SameSite=Strict` en la response de `/auth/login`,
**so that** ningún código JS pueda leerlo ni exfiltrarlo vía XSS, y el
navegador lo envíe automáticamente en cada request al backend.

Acceptance criteria:

1. WHEN `POST /api/v1/auth/login` recibe credenciales válidas, THE SYSTEM SHALL
   responder 200 con `access_token` en el body **y** un header `Set-Cookie` cuyo
   nombre es `autohostai.session.refresh`, con los atributos `HttpOnly`,
   `SameSite=Strict`, `Path=/api/v1/auth`, `Max-Age=604800` (igual a la expiración
   vigente del refresh token) y `Secure` cuando el request entrante usó HTTPS.
2. WHEN la response de `/auth/login` se serializa, THE SYSTEM SHALL NOT incluir
   un campo `refresh_token` en el JSON del body — la transferencia del refresh
   ocurre exclusivamente por la cookie.
3. IF el login falla (credenciales inválidas, throttle, etc.), THEN THE SYSTEM
   SHALL NOT emitir la cookie de refresh.

### R2 — `/auth/refresh` lee de la cookie y la rota

**As a** backend de autenticación, **I want** que `/auth/refresh` obtenga el
refresh token de la cookie de request y emita una cookie rotada en la response,
**so that** cada refresh desliza la expiración y la cookie nunca quede estática.

Acceptance criteria:

1. WHEN `POST /api/v1/auth/refresh` recibe una request con la cookie
   `autohostai.session.refresh` válida y vigente, THE SYSTEM SHALL responder 200
   con un nuevo `access_token` en el body **y** un header `Set-Cookie` que
   reemplaza la cookie con un valor nuevo y la misma `Max-Age=604800` (rotación
   continua de la expiración).
2. IF la cookie está ausente, expirada o revocada, THEN THE SYSTEM SHALL
   responder 401 con el mismo cuerpo de error y cabeceras que el contrato actual
   para «refresh inválido», **sin** emitir `Set-Cookie`.
3. THE SYSTEM SHALL NOT leer un campo `refresh_token` del body de
   `/auth/refresh`; un body con `refresh_token` se ignora silenciosamente y se
   trata como si la cookie estuviera ausente.

### R3 — `/auth/logout` invalida la familia y purga la cookie

**As a** backend de autenticación, **I want** que `/auth/logout` revoque la
familia del refresh token en servidor y purgue la cookie en la response,
**so that** cerrar sesión invalida tanto el estado servidor como el estado del
navegador, sin dejar credenciales persistentes.

Acceptance criteria:

1. WHEN `POST /api/v1/auth/logout` recibe una request con la cookie
   `autohostai.session.refresh`, THE SYSTEM SHALL revocar la familia del refresh
   token asociada (comportamiento ya exigido por `auth-tenancy.md`) **y**
   responder **204** (el contrato de logout ya existente, sin cuerpo) con
   `Set-Cookie: autohostai.session.refresh=; Max-Age=0; Path=/api/v1/auth` que
   sobrescribe la cookie con expiración inmediata — **corregido 2026-09-06**
   (panel de QA, quinta/sexta ronda): esta acceptance criterion decía "200"
   cuando se escribió; `/auth/logout` nunca cambió su código de estado
   existente y el implementador ya lo había señalado como una discrepancia de
   redacción a reconciliar (`tasks.md`), no un cambio de comportamiento.
2. IF no hay cookie o ya fue revocada, THEN THE SYSTEM SHALL responder **204**
   de todos modos (logout idempotente) y SHALL emitir la `Set-Cookie` de purga
   — salvo que el `Origin` de la request esté presente y fuera del allowlist de
   CORS, en cuyo caso SHALL responder **204** sin revocar ni purgar la cookie
   (CSRF, ver `auth-tenancy.md` y design D6c).

### R4 — `session-store` deja de guardar el refresh token

**As a** frontend de autenticación, **I want** que el almacén en memoria solo
contenga el access token, **so that** un reload o pestaña nueva pierda solo el
access — el refresh sigue disponible vía cookie — y el inventario de secretos
en runtime JS quede reducido al mínimo.

Acceptance criteria:

1. THE SYSTEM SHALL mantener el access JWT únicamente en memoria del runtime
   JavaScript actual (estado de React del `AuthProvider`), igual que hoy.
2. THE SYSTEM SHALL NOT escribir el refresh token en `localStorage`,
   `sessionStorage`, IndexedDB, Zustand ni ningún otro almacenamiento
   persistente, ni en memoria del runtime JS.
3. WHEN `clearSessionTokens()` se invoca, THE SYSTEM SHALL purgar el access
   token en memoria, invalidar la query del `QueryClient` singleton (semántica
   ya cubierta por `session-cache-purge.ts`) y emitir una `POST /auth/logout`
   que purga la cookie via R3.

### R5 — Silent refresh al montar el `AuthProvider`

**As a** usuario autenticado, **I want** que al abrir una pestaña nueva o
recargar, la app intente restaurar mi sesión antes de pedirme login,
**so that** no tenga que volver a teclear credenciales para volver a donde
estaba.

Acceptance criteria:

1. WHEN `AuthProvider` se monta en un runtime sin tokens en memoria, THE
   SYSTEM SHALL emitir una `POST /api/v1/auth/refresh` con
   `credentials: 'include'` antes de resolver el estado inicial, exponiendo un
   estado transitorio `loading` mientras la promesa está pendiente.
2. IF la llamada de mount-refresh tiene éxito, THEN THE SYSTEM SHALL poblar
   el access token en memoria, llamar a `GET /api/v1/auth/me`, y resolver al
   estado `authenticated` con `user`, `role` y `tenant_id` devueltos por el
   backend.
3. IF la llamada de mount-refresh falla (401, red), THEN THE SYSTEM SHALL
   resolver al estado `anonymous` sin mostrar error visible — el usuario solo
   verá el formulario de login si navega a una ruta protegida.
4. THE SYSTEM SHALL garantizar que solo se ejecuta **una** llamada de
   mount-refresh por montaje del provider, aunque varios componentes pidan el
   estado de sesión en paralelo.

### R6 — Cada pestaña es independiente; logout es local

**As a** usuario que trabaja con varias pestañas, **I want** que cada pestaña
mantenga su propio access token en memoria y que cerrar sesión en una pestaña
no afecte a las demás hasta que intenten refrescar, **so that** el modelo de
sesión por pestaña que ya existe no se vea alterado por el cambio de
transporte.

Acceptance criteria:

1. WHEN dos pestañas del mismo navegador comparten la cookie de refresh, cada
   pestaña SHALL mantener su propio access token en memoria y SHALL emitir su
   propia `POST /api/v1/auth/refresh` cuando reciba un 401 elegible; la
   coordinación single-flight existente (`refresh-coordinator.ts`) opera
   dentro de la pestaña, no entre pestañas.
2. WHEN una pestaña ejecuta `useLogoutMutation().mutateAsync()`, THE SYSTEM
   SHALL purgar localmente (tokens en memoria, `QueryClient`, cookie de
   presencia `autohostai.session.present`) **y** emitir `POST /auth/logout`
   que purga la cookie `autohostai.session.refresh`; las demás pestañas
   SHALL seguir con su access token en memoria hasta su próximo 401.
3. WHEN otra pestaña intenta refrescar después de que la primera cerró
   sesión, THE SYSTEM SHALL recibir 401 del backend (cookie purgada) y SHALL
   transicionar a `anonymous` en esa pestaña sin afectar a las restantes.

### R7 — Postura CORS y cookie para dev y prod

**As a** entorno de despliegue, **I want** que el backend anuncie CORS con
`Access-Control-Allow-Credentials: true` y un `Allow-Origin` explícito, **so
that** el navegador acepte la cookie de refresh en las peticiones
cross-origin desde el frontend.

Acceptance criteria:

1. WHEN el backend responde a una request cross-origin desde el frontend
   (origen declarado en la allowlist de CORS), THE SYSTEM SHALL incluir
   `Access-Control-Allow-Credentials: true` y SHALL reflejar el `Origin` de
   la request en `Access-Control-Allow-Origin` (nunca `*`).
2. WHEN la response es a una request con esquema HTTPS, THE SYSTEM SHALL
   emitir la cookie con el atributo `Secure`; WHEN la request es HTTP
   (entornos dev con `PORT_OFFSET`), THE SYSTEM SHALL emitir la cookie sin
   `Secure` para que el navegador la acepte y SHALL registrar este matiz en
   el log de la response para auditoría.
3. WHEN el túnel de Cloudflare (`ingress-https-dev`) está en uso, THE SYSTEM
   SHALL emitir `Secure` porque el esquema externo es HTTPS aunque la
   request interna al backend pueda llegar como HTTP; la decisión se basa en
   el header `X-Forwarded-Proto` cuando el proxy de confianza lo aporta.

## Out of scope

- **Las dos grietas de `auth-session-generation-semantics`** (la purga que no
  mueve generación y la guarda del coordinador anulada al expirar): son
  deudas latentes registradas en su propia entrada del roadmap; este change
  las revisa durante el `design.md` por si el nuevo flujo de mount-refresh las
  reabre, pero no las arregla.
- **Rotación de refresh tokens en Redis, throttle, RBAC, tenant isolation**:
  el transporte cambia, la política de seguridad no. Cualquier endurecimiento
  adicional del modelo de sesión va en su propia entrada.
- **Clientes no-browser**: no hay clientes móviles, CLI ni workers que
  consuman `/auth/login` o `/auth/refresh` en este repositorio. Los tests
  que sí lo hacen se actualizan en este mismo change (R7 abajo).
- **La cookie `autohostai.session.present`** que ya usa la raíz `/` para
  decidir landing vs redirect: pertenece a `frontend-auth-session` y no se
  toca. Su dominio y atributos son los definidos allí; la nueva cookie de
  refresh tiene su propio nombre (`autohostai.session.refresh`).
- **Cambio del TTL del access o del refresh token, de la rotación de familia
  o del throttle de Redis**: orthogonal; este change solo cambia el
  transporte.
- **Single-flight cross-tab (BroadcastChannel / SharedWorker)**: el requisito
  R6 fija pestañas independientes explícitamente; cualquier coordinación
 跨 pestaña futura va en su propia entrada.

## Affected specs

- `sdd/specs/frontend-auth-session.md` — modificar la sección «Sesión efímera
  y refresh» para que el refresh token **no** viva en memoria, añadir el
  requisito de mount-refresh silencioso, y reemplazar la frase «THE SYSTEM
  SHALL NOT escribir tokens ni credenciales en … cookies …» por la
  formulación precisa: «THE SYSTEM SHALL NOT escribir tokens ni credenciales
  en `localStorage`, `sessionStorage`, IndexedDB, Zustand u otro
  almacenamiento persistente; el refresh token se transporta exclusivamente
  vía cookie `httpOnly`».
- `sdd/specs/auth-tenancy.md` — modificar la descripción de los endpoints
  `/auth/login`, `/auth/refresh` y `/auth/logout` para reflejar el nuevo
  contrato de transporte, y listar `autohostai.session.refresh` en los
  atributos de cookie que el backend emite.
- `sdd/specs/backend-http-posture.md` — añadir el requisito de
  `Access-Control-Allow-Credentials: true` con `Allow-Origin` explícito y la
  regla `Secure` condicional al esquema (R7).
- `sdd/specs/ingress-https-dev.md` — verificar que la postura HTTPS sobre
  Cloudflare Tunnel es compatible con el atributo `Secure` (esperado: sí,
  vía `X-Forwarded-Proto`); no se modifica, se referencia.
