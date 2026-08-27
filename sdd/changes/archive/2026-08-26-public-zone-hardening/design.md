# Design: public-zone-hardening

## Context

Tras el primer deploy de la landing pública (`landing-public`, archivado
2026-08-23) aparecieron cuatro huecos en la UX de la zona pública y de las
shells autenticadas:

- `frontend/features/shell/components/locale-switcher.tsx:51-58` aplica
  `i18n.changeLanguage` + cookie + `<html lang>`, pero **no** re-fetchea el
  segmento. Como `app/(public)/page.tsx`, `LandingView`, `Hero`,
  `MarketingNav`, `FeaturesGrid`, `StatsBand`, `FinalCta`, `LandingFooter` y
  `PublicShell` son Server Components que pintan su texto con `getServerT()`
  (`frontend/lib/i18n/server.ts:43`), el contenido del `<main>` queda en el
  idioma antiguo hasta recargar.
- `app/(public)/login/page.tsx` solo monta `LoginForm`; no hay ningún camino
  visible de vuelta a `/`. El `PublicShell` acepta un slot `marketingNav`
  que la landing usa y el login no.
- El backend expone `POST /api/v1/auth/logout` (`backend/app/auth/api/router.py:94`)
  y `AuthProvider.logout` (`frontend/lib/auth/auth-provider.tsx:119-135`)
  purga tokens, cookie `autohostai.session.present` y caché de TanStack
  Query. **Ningún componente la invoca**: `grep -rn 'useAuth().logout\|logout('`
  sobre `components/`, `features/shell/`, `features/auth/` da cero
  resultados. Consecuencia: la cookie sobrevive un año (`max-age=31536000`
  en `session-presence-cookie.ts:19`) y la raíz `app/page.tsx:35-41`
  redirige a `/dashboard`, donde `AuthGuard` (`features/auth/components/auth-guard.tsx:17`)
  ve `status === "anonymous"` (JWT en memoria, perdido al recargar) y
  manda a `/login?returnTo=/dashboard`.
- `LoginForm.handleSubmit` (`features/auth/components/login-form.tsx:40-52`)
  honra `?returnTo=` pero, sin él, cae a `/dashboard` para cualquier rol.
  `cleaner` y `technician` que abren `autohostai.digitalsec.work` llegan a
  un dashboard que no es el suyo y ven `RoutePlaceholder` en cada ruta.

## Decisions

### D1 — `router.refresh()` tras escribir el cookie de locale

**Chosen:** en `LocaleSwitcher`, tras `document.cookie = …`, llamar a
`router.refresh()` de `next/navigation` dentro del mismo `useEffect`.
Next re-fetchea el segmento actual y re-ejecuta los Server Components del
árbol (`RootLayout`, `PublicShell`, `LandingView`, todas las secciones)
con la cookie nueva. URL, foco y posición de scroll aproximada se
preservan (Next sólo restaura el scroll si el segmento no cambia de URL).

Rejected: `window.location.reload()` — recarga entera, pierde scroll y
scroll-to-anchor `#features`. Rejected: `<Link href={pathname}>` —
necesita conocer la ruta actual y dispara un navigation, no un refresh.
Rejected: `revalidatePath('/')` desde el servidor — el cookie vive en
cliente, así que el server no podría leerlo sin re-entrante HTTP.

**Orden importa** dentro del `useEffect`: `changeLanguage` + cookie +
`router.refresh()` en ese orden, sin `await` ni `Promise.all`. La cookie
está escrita en el `document.cookie` antes de que el refresh emita su
petición, y el navegador la envía en la cabecera del re-fetch.

### D2 — `UserMenu` se monta en el slot `end` del `Topbar`, **no** en el sidebar ni el bottom navigation

**Chosen:** `WorkspaceShell`, `CleanerShell` y `TechnicianShell` pasan un
`end` custom al `Topbar` que sustituye el default (ThemeSwitcher +
LocaleSwitcher) por `[ThemeSwitcher, Separator, LocaleSwitcher, UserMenu]`.
`PublicShell` y `GuestShell` no pasan `end` custom: el logout no aplica
en el portal guest (acceso por token) y en login es ruido visual.

Rejected: meter el logout en el `Sidebar` — el workspace usa sidebar solo
en desktop (`lg:`), en tablet usa drawer y en mobile bottom navigation;
mantener tres sitios sería más caro que un slot `end` que el `Topbar`
ya tiene. Rejected: nuevo shell wrapper por rol — duplicaría el chrome
existente.

### D3 — UserMenu: `DropdownMenu` shadcn con email como trigger y «Cerrar sesión» como ítem

**Chosen:** componente `UserMenu` (`"use client"`) que lee
`useAuth().user.email` y `useAuth().logout`. Trigger: `Button` con
`variant="ghost"` mostrando el email truncado (o un avatar fallback si no
hay avatar aún). Contenido: `DropdownMenuItem` con `LogOut` icon →
«Cerrar sesión». Click → abre un `AlertDialog` shadcn con `variant="destructive"`
que confirma la intención (ver D4).

Rejected: solo botón sin dropdown — el usuario pierde la pista de «quién
está logueado» desde el chrome. Rejected: menú con más opciones
(perfil, preferencias) — fuera de alcance; las preferencias las cubre
`Settings` si llega.

### D4 — Logout pide confirmación con `AlertDialog`

**Chosen:** `UserMenu` controla un `<AlertDialog open={open} onOpenChange={setOpen}>`.
El body dice «Vas a cerrar tu sesión en este dispositivo. Podrás volver a
entrar cuando quieras.» y dos botones: «Cancelar» (default) y «Cerrar
sesión» (destructive). El click en «Cerrar sesión» ejecuta la secuencia
del D5. Texto via `auth.logoutConfirmTitle`, `auth.logoutConfirmBody`,
`auth.logoutConfirmCancel`, `auth.logoutConfirmAction` en `locales/{es,en}/auth.json`.

Rejected: sin confirmación — el patrón SaaS mayoritario, pero en
dispositivos compartidos (un técnico en una tablet de la propiedad) un
tap por error cierra sesión y obliga a re-autenticar, lo cual en un
futuro puede pedir un magic link. El coste es un click más; el beneficio
es no perder trabajo de campo por accidente.

### D5 — Secuencia de logout

`onClick` del botón «Cerrar sesión» del AlertDialog, en `UserMenu`:

```ts
const { logout } = useAuth();
const router = useRouter();
async function handleLogout() {
  setOpen(false);
  await logout();              // POST /auth/logout + purga tokens + cookie + caché
  router.replace("/");          // navegación que sustituye la entrada del history
  router.refresh();            // RootPage re-evalúa la cookie (ausente) → landing
}
```

`router.replace` y no `router.push` para que el botón «atrás» del
navegador no devuelva al usuario a una ruta autenticada sin sesión.
`router.refresh` después para que `app/page.tsx:35` pinte la landing con
la cookie ausente (acaba de ser purgada por `clearSessionPresent()` en
`auth-provider.tsx:131`).

Si `logout()` falla en el servidor (red, 5xx), el `try/catch` de
`auth-provider.tsx:126-127` ya purga el estado local, así que
`router.replace("/")` + `router.refresh()` funcionan igualmente.

### D6 — Redirección por rol desde `LoginForm`, sin HTTP extra

**Chosen:** `LoginForm.handleSubmit` lee `user` de `useAuth()` (ya
poblado por `auth-provider.login()` al hacer `await login(email, password)`,
que llama a `/auth/me` y guarda el resultado) y, si no hay `?returnTo=`,
mapea `user.role` a su ruta con un helper:

```ts
// frontend/features/auth/lib/role-home.ts
const ROLE_HOME: Record<string, string> = {
  TENANT_OWNER: "/dashboard",
  PROPERTY_MANAGER: "/dashboard",
  CLEANER: "/cleaner",
  TECHNICIAN: "/tech",
};
export function roleHome(role: string | undefined): string {
  return role && ROLE_HOME[role] ? ROLE_HOME[role] : "/dashboard";
}
```

Rejected: `useEffect` con `/auth/me` adicional — `auth-provider.login()` ya
lo hace; pedirlo otra vez sería doble latencia. Rejected: TanStack Query
con `me` pre-cargado — añade cache y TTL a una llamada que solo se hace
una vez por sesión. Rejected: tabla en backend (`LOGIN_REDIRECT_BY_ROLE`)
— la necesitamos en cliente para decidir tras `await login()` y el
backend ya devuelve el rol en `/me`; mandarla otra vez es redundante.

Si `LoginForm` recibe un `?returnTo=` válido (mismo origen, ruta que
empieza por `/`), respeta `returnTo` como hoy. Si `/auth/me` falla tras
un login exitoso, cae a `/dashboard` (default del helper) — esto es el
caso R4.3.

### D7 — Claves i18n nuevas

- `locales/{es,en}/auth.json` → `backToLanding`, `logoutConfirmTitle`,
  `logoutConfirmBody`, `logoutConfirmCancel`, `logoutConfirmAction`.
- `locales/{es,en}/navigation.json` → `userMenu.triggerLabel` (ej. «Menú
  de usuario»), `userMenu.logout`.

La regla de `frontend-foundation.md:43` exige que toda clave nueva exista
en `es` y `en` y que el test `frontend/lib/i18n/catalog-parity.test.ts`
falle si falta en uno. Las cinco + dos nuevas se añaden a los dos
catálogos y el test pasa.

### D8 — Back-link en `/login`

`<Link href="/">← {t("auth:backToLanding")}</Link>` debajo del `<Button
type="submit">`. Usa el componente `Link` de `next/link` para que el
router pinte la landing con la cookie `autohostai.session.present`
re-evaluada. No pasa por `MarketingNav`: el `PublicShell` del login no
recibe `marketingNav` y añadirlo solo para este enlace es más invasivo
que un link propio.

## Changes by area

| Area | Files | Change |
|---|---|---|
| i18n shell | `frontend/features/shell/components/locale-switcher.tsx` | D1: añadir `useRouter`, llamar `router.refresh()` tras la cookie. |
| chrome shells | `frontend/features/shell/components/workspace-shell.tsx` · `cleaner-shell.tsx` · `technician-shell.tsx` | D2: pasar un `end` custom al `Topbar` que incluya `<UserMenu />`. |
| nuevo componente | `frontend/features/auth/components/user-menu.tsx` (nuevo) | D3 + D4 + D5: `DropdownMenu` con trigger de email + ítem «Cerrar sesión» → `AlertDialog` → logout → `router.replace("/")` + `router.refresh()`. |
| nuevo helper | `frontend/features/auth/lib/role-home.ts` (nuevo) | D6: `roleHome(role)` con la tabla de mapeo. |
| login | `frontend/features/auth/components/login-form.tsx` | D6 + D8: usar `roleHome(user.role)` cuando no hay `?returnTo=`; añadir `<Link href="/">{t("auth:backToLanding")}</Link>`. |
| i18n catálogos | `frontend/locales/es/auth.json` · `locales/en/auth.json` · `locales/es/navigation.json` · `locales/en/navigation.json` | D7: siete claves nuevas. |
| i18n registry | `frontend/lib/i18n/resources.ts` | Sin cambio: `auth` y `navigation` ya están en `NAMESPACES`. |
| tests | `frontend/features/shell/components/locale-switcher.test.tsx` (existente) | Añadir test que verifica que `router.refresh` se llama tras el click. |
| tests | `frontend/features/auth/components/user-menu.test.tsx` (nuevo) | Cubre dropdown abierto, AlertDialog visible, click en «Cerrar sesión» → logout invocado + navegación. |
| tests | `frontend/features/auth/components/login-form.test.tsx` (existente) | Añadir test para `roleHome` (manager → /dashboard, cleaner → /cleaner, tech → /tech, default → /dashboard, ?returnTo manda). |
| tests | `frontend/features/auth/lib/role-home.test.ts` (nuevo) | Tabla de mapeo exhaustiva. |

## Data & interfaces

**None.** No hay migraciones, no hay cambios de esquema, no hay nuevos
endpoints, no hay nuevas variables de entorno. El cambio es 100 % frontend.

## Risks & mitigations

1. **`router.refresh()` puede perder el ancla `#features`.** Mitigación:
   `R1` de la propuesta ya está escrito asintóticamente («mismo lugar
   aproximado»). Si Playwright de `hardening-release` detecta regresión,
   el swap a `window.location.assign(window.location.pathname)` está
   documentado en el proposal.

2. **El orden cookie → refresh puede no propagarse.** Mitigación: el
   `useEffect` ejecuta `document.cookie = …` (síncrono) y, en la
   siguiente línea síncrona, `router.refresh()`. La petición que emite
   `router.refresh()` se monta sobre el canal HTTP del navegador con la
   cookie ya escrita. El test de `locale-switcher.test.tsx` usa
   `jsdom` con cookies en mismo origen; si el orden se rompe, el test
   falla.

3. **`roleHome` cubre los 4 roles del MVP hoy, pero el catálogo de roles
   puede crecer** (`docs/adr/0006-pms-channel-manager-provider.md`
   introduce `SUPER_ADMIN` para fase SaaS). Mitigación: default a
   `/dashboard` (D6) cubre cualquier rol no mapeado sin romper la UX;
   cuando entre un rol nuevo, basta añadir una línea a `ROLE_HOME`. La
   prueba exhaustiva en `role-home.test.ts` lista explícitamente los
   roles conocidos hoy.

4. **`AlertDialog` de shadcn requiere Radix Portal**; algunos tests
   jsdom sin polyfill de `Element.prototype.scrollTo` fallan al
   montar. Mitigación: el setup de `frontend/test/` ya tiene el polyfill
   (ver `frontend/test/setup.ts` y los demás componentes Radix que se
   prueban en `frontend/components/ui/`). Si no, se añade.

5. **El `AuthProvider.logout` es best-effort en servidor (puede fallar
   la red)**. Mitigación: ya implementada en `auth-provider.tsx:126-127`;
   la limpieza local es incondicional. El test de `user-menu.test.tsx`
   cubre el caso «endpoint 500 → igualmente cierra sesión».

## Open questions

Ninguna abierta. Las tres decisiones que dependían de preferencia
(`D3` forma del menú, `D4` confirmación, mapeo de rol por defecto) ya
están resueltas con el input del usuario en este gate.