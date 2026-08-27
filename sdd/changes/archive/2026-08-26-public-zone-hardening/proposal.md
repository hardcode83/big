# Proposal: public-zone-hardening

## Why

Después de desplegar la landing-zone pública en `autohostai.digitalsec.work`, el
uso real destapó cuatro bugs de UX que el `landing-public` archivado no cubría
— el switcher ES/EN no refresca los Server Components, no hay botón de logout
en la UI, la raíz redirige a `/login` mientras la cookie `autohostai.session.present`
sobreviva, y `cleaner`/`technician` no saben dónde aterrizar tras login. Son
cinco síntomas en una sola causa: la zona pública y las shells autenticadas
trataron la sesión y el locale como cosas del navegador, sin un camino de salida
ni de entrada claro para cada rol. La fix es local (no toca el contrato de la
API), pero conviene empaquetarla porque comparten chrome y porque dos de ellas
son prerequisito de un eventual E2E Playwright (`hardening-release`).

**Seed**: el diagnóstico completo —con captura del `curl -I`, snapshot de
Playwright y archivos citados— vive en el thread que abrió esta entrada; no se
versiona aquí porque `proposal.md` cita el código, no lo reproduce.

## What changes

Tras este change existirá:

- un `LocaleSwitcher` que tras cambiar el idioma refresca el segmento actual
  (`router.refresh()`) para que los Server Components de la landing se
  re-pinten con el nuevo cookie;
- un enlace «← Volver a la landing» en `/login`, por debajo del botón de
  submit, con su clave i18n en `es` y `en`;
- un `UserMenu` cliente en `WorkspaceShell`, `CleanerShell` y `TechnicianShell`
  con la acción «Cerrar sesión» que invoca `useAuth().logout()`, navega a `/`
  y refresca el segmento para que `RootPage` re-evalúe la cookie;
- un redirect por rol en `LoginForm`: si no hay `?returnTo=`, el form llama
  a `/auth/me` y envía a `/dashboard` (manager), `/cleaner` (cleaner) o
  `/tech` (technician) según el rol devuelto.

Las cuatro viven en frontend; el backend ya expone `POST /api/v1/auth/logout`
y `GET /api/v1/auth/me` con los permisos necesarios.

## Requirements

### R1 — El switcher ES/EN refresca los Server Components de la landing

**As a** visitante anónimo de `/`, **I want** que el conmutador de idioma
cambie el contenido visible sin tener que recargar la pestaña, **so that**
la landing se sienta localizada en todo momento.

Acceptance criteria:

1. WHEN el visitante hace click en `LocaleSwitcher` desde `/`, THE SYSTEM
   SHALL cambiar el cookie `autohostai.locale` al idioma destino y revalidar
   el segmento actual del router (`router.refresh()`) de manera que los
   `getServerT()` de `LandingView`, `Hero`, `MarketingNav`, `FeaturesGrid`,
   `StatsBand`, `FinalCta` y `LandingFooter` se ejecuten con el nuevo locale.
2. WHEN el segmento se revalida, THE SYSTEM SHALL pintar los textos del
   `<main>` en el idioma destino sin que el visitante tenga que pulsar
   recargar.
3. WHILE la cookie `autohostai.locale` cambia, THE SYSTEM SHALL mantener el
   foco y la posición de scroll del visitante en el mismo lugar aproximado
   donde estaba antes del click (no perder el ancla `#features` si era el
   destino).
4. IF el visitante está en una ruta que NO es Server Component pura (p. ej.
   `/dashboard`), THE SYSTEM SHALL seguir invocando `i18n.changeLanguage`
   en el cliente para que los strings viajen sin recarga, igual que hoy.

### R2 — `/login` expone un enlace para volver a la landing

**As a** visitante que ha llegado a `/login` y decide no autenticarse, **I
want** un enlace visible que me devuelva a `/`, **so that** no tenga que
editar la URL a mano ni usar el botón «atrás» del navegador.

Acceptance criteria:

1. WHEN `/login` se renderiza, THE SYSTEM SHALL mostrar bajo el botón de
   submit un enlace con texto localizado (clave `backToLanding` en
   `locales/{es,en}/auth.json`) que apunta a `/`.
2. WHEN el visitante activa el enlace, THE SYSTEM SHALL navegar a `/` y
   re-evaluar `RootPage` para que la cookie `autohostai.session.present`
   decida el destino (landing si ausente, `/dashboard` si presente).
3. THE SYSTEM SHALL cumplir `steering/frontend.md` (toda string visible pasa
   por `locales/es/` y `locales/en/`; nada hardcodeado).

### R3 — Hay un botón «Cerrar sesión» invocable en workspace, cleaner y tech

**As a** usuario autenticado de cualquier rol (manager, cleaner, technician),
**I want** un control visible en el chrome de mi app que cierre mi sesión,
**so that** pueda terminar la sesión en un dispositivo compartido o tras
terminar la jornada, y para que la cookie `autohostai.session.present` no
sobreviva un año a un login abandonado.

Acceptance criteria:

1. THE SYSTEM SHALL exponer un `UserMenu` cliente que monte `WorkspaceShell`,
   `CleanerShell` y `TechnicianShell` (no `GuestShell`, que vive de token en
   la URL) y que ofrezca la acción «Cerrar sesión» localizada
   (`navigation.logout` o clave homóloga en `locales/{es,en}/`).
2. WHEN el usuario activa «Cerrar sesión», THE SYSTEM SHALL invocar
   `useAuth().logout()` —que ya llama a `POST /api/v1/auth/logout`, purga
   la caché de TanStack Query, limpia los tokens y la cookie
   `autohostai.session.present` y vuelve `status` a `anonymous`—, navegar a
   `/` con `router.replace` y refrescar el segmento (`router.refresh()`)
   para que `RootPage` re-evalúe la cookie.
3. WHEN el endpoint `/auth/logout` falla (red, 5xx), THE SYSTEM SHALL
   igualmente descartar tokens, cookie y caché en el cliente (el logout es
   best-effort del lado servidor —el comportamiento ya está implementado en
   `frontend/lib/auth/auth-provider.tsx:119-135`).
4. THE SYSTEM SHALL seguir la regla 7 de `steering/security.md` (refresh
   rotation) sin cambio: el logout revoca la familia del refresh token en
   backend; los access tokens ya emitidos siguen hasta su expiración, lo
   cual es deliberado y ya está documentado en el endpoint.
5. THE SYSTEM SHALL resolver R2 colateralmente: al ofrecer logout, la cookie
   «promesa de sesión» deja de sobrevivir un año, y el síntoma «abrir la
   raíz me lleva a `/login`» deja de ocurrir (la raíz vuelve a la landing
   tras un logout real).

### R4 — `LoginForm` redirige por rol cuando no hay `?returnTo=`

**As a** cleaner o technician que llega al `autohostai.digitalsec.work`
genérico, **I want** que tras autenticarme la app me lleve a mi app
(`/cleaner` o `/tech`), **so that** no tenga que saber una URL concreta y
pueda usar el dominio raíz como punto de entrada universal.

Acceptance criteria:

1. WHEN el `LoginForm` recibe un submit válido y la URL **no** trae
   `?returnTo=`, THE SYSTEM SHALL llamar a `GET /api/v1/auth/me`, leer el
   rol y redirigir a `/dashboard` (manager), `/cleaner` (cleaner) o
   `/tech` (technician) según corresponda.
2. WHEN la URL trae `?returnTo=` válido (mismo origen, ruta que empieza por
   `/`), THE SYSTEM SHALL respetar `returnTo` como hace hoy
   (`frontend/features/auth/components/login-form.tsx:11-30`).
3. IF la llamada a `/auth/me` falla tras un login exitoso, THE SYSTEM SHALL
   caer a `/dashboard` (comportamiento por defecto) en lugar de dejar al
   usuario en `/login` con error silencioso.
4. THE SYSTEM SHALL no cambiar el comportamiento del `AuthGuard` que envuelve
   `/cleaner` y `/tech`: hoy acepta a cualquier usuario autenticado y la
   separación por rol vive en el sidebar/backend. Endurecer el guard es
   trabajo de otro change (ver Out of scope).

### R5 — No regresión: las shells de guest no cambian y el i18n sigue siendo bidireccional

**As a** mantenedor del proyecto, **I want** que este change no altere el
comportamiento del portal `/guest/[token]` ni rompa el catálogo ES/EN
existente, **so that** los changes que ya pasaron review (`landing-public`,
`frontend-foundation`, `frontend-auth-session`) sigan verdes.

Acceptance criteria:

1. THE SYSTEM SHALL no añadir UI de logout en `GuestShell` (el guest no
   tiene sesión que cerrar; su acceso es por token en la URL).
2. THE SYSTEM SHALL añadir dos claves nuevas — `auth.backToLanding` y
   `navigation.logout` (o equivalentes acordados con `steering/frontend.md`)
   — en `locales/es/auth.json`, `locales/en/auth.json` y, si la acción vive
   en el chrome, en `locales/{es,en}/navigation.json`. Ningún otro locale
   se modifica.
3. THE SYSTEM SHALL respetar la regla de `sdd/steering/i18n` (revisor
   `sdd-review-i18n`): toda string nueva aparece en `es` y `en`, y no se
   introduce texto hardcodeado en componentes.

## Out of scope

- **Endurecer `AuthGuard` con role-based routing**: hoy cualquier usuario
  autenticado entra a `/cleaner` o `/tech`; el backend ya discrimina por
  permisos. Acotar el guard a rol pertenece a otro change (candidato natural
  en `cleaner-app` / `tech-app`), porque obliga a revisar el `Sidebar` para
  no esconder rutas a quien no debería verlas y a tocar el flujo de
  invitaciones. Aquí solo redirigimos a la app del rol tras login; no
  negamos el acceso si alguien llega con la URL directa.
- **Mini-landing autenticada por rol**: una pantalla post-login con CTA a
  `/cleaner` o `/tech` para usuarios de campo. Es más amable con móviles de
  un solo uso, pero requiere un componente nuevo y un routing intermedio.
  Queda como evolución de R4, no como parte de este change.
- **Reescribir `LocaleSwitcher` para soportar más de dos idiomas**: el
  problema del refresh de Server Components es estructural y se reproduce con
  N idiomas, pero el proyecto solo soporta ES/EN hoy
  (`SUPPORTED_LOCALES` en `frontend/lib/config/constants.ts`). Si entra un
  tercero, el componente tendrá que pasar a ser un `Select` o un menú, y eso
  es otra conversación.
- **Server-side `RootPage` que distinga «cookie stale pero JWT revocado»**:
  la cookie `autohostai.session.present` no tiene sentido hoy sin un JWT en
  memoria. Una defensa en profundidad obligaría a `RootPage` a hablar con
  el backend en cada visita, lo que rompe el modelo «server decide sin
  red». R3 ya elimina el caso real (logout borra la cookie); el resto es
  cosmética.
- **Migrar `auth-provider.tsx:logout` a TanStack Query mutation**: hoy
  llama al cliente HTTP de `lib/api/authenticated-client`. Mudar a una
  mutation cacheable tiene sentido, pero es refactor de organización, no de
  comportamiento, y entra en `frontend-refactor` si llega.

## Affected specs

- `sdd/specs/frontend-foundation.md` — i18n y locale switcher (R1, R5).
- `sdd/specs/frontend-auth-session.md` — sesión, `markSessionPresent` /
  `clearSessionPresent`, y rol del `AuthProvider.logout` (R3).
- `sdd/specs/auth-tenancy.md` — contrato de `/auth/logout` y `/auth/me`
  referenciado por R3 y R4 (sin modificación, sólo se cita).
- *(no existe aún — se creará al archivar)* `sdd/specs/public-zone-ux.md`
  si la combinación de R1+R2+R3 merece una spec propia por su encuadre de
  «camino de entrada/salida de la app pública». Decisión de Marta en
  archive; aquí se deja nombrada para no perder el rastro.

## Notes

- **Asunciones explícitas**:
  - `ASSUMPTION`: el conmutador actual de un solo botón sigue siendo el
    deseado; no se introduce un `Select` ni dos botones. Está alineado con
    `frontend-foundation.md:43` y el comentario de `LocaleSwitcher`
    (2026-08-24).
  - `ASSUMPTION`: el redirect por rol se calcula contra el rol declarado
    por `/auth/me`, no contra permisos efectivos. Coincide con el modelo
    del `Sidebar` (perfiles `workspace` | `cleaner` | `technician`) y con
    el `ShellProfile` del registro de rutas
    (`frontend/features/shell/navigation/route-registry.ts`).
- **Riesgos conocidos**:
  - `router.refresh()` re-fetchea el segmento pero no garantiza que el
    scroll se preserve en todos los navegadores; el criterio 3 de R1 es
    asintótico. Si Playwright en `hardening-release` detecta regresión,
    se sustituye por `window.location.assign(window.location.pathname)` y
    se documenta.
  - `router.refresh()` con un Server Component que lee cookies justo
    después de escribirlas puede ganarle al navegador si el `document.cookie`
    no se ha propagado al canal HTTP. La regla es: cookie primero, refresh
    después, en el mismo `useEffect` (secuencial, no en paralelo). El test
    de R1 lo cubre.
