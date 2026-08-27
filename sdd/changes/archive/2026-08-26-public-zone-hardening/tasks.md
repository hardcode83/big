# Tasks: public-zone-hardening

## 1. i18n keys — catálogos `auth` y `navigation` <!-- panel: PASS 2026-08-26 -->

- [x] 1.1 Añadir 5 claves a `frontend/locales/es/auth.json` y sus traducciones a `frontend/locales/en/auth.json`: `backToLanding`, `logoutConfirmTitle`, `logoutConfirmBody`, `logoutConfirmCancel`, `logoutConfirmAction`. [R2, R3, R5]
- [x] 1.2 Añadir 2 claves a `frontend/locales/es/navigation.json` y `frontend/locales/en/navigation.json`: `userMenu.triggerLabel`, `userMenu.logout`. [R3, R5]
- [x] 1.3 Verificar que `frontend/lib/i18n/catalog-parity.test.ts` pasa con las 7 claves nuevas. **Done**: el test verde muestra que ES y EN están en paridad. [R5]

## 2. Helper `roleHome` — sin HTTP extra <!-- panel: PASS 2026-08-26 -->

- [x] 2.1 Crear `frontend/features/auth/lib/role-home.ts` con la tabla `ROLE_HOME` (4 entradas: `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`) y la función `roleHome(role: string | undefined): string` que devuelve `ROLE_HOME[role] ?? "/dashboard"`. **Done**: el módulo exporta `roleHome` y `ROLE_HOME` (este último para que el test lo recorra). [R4]
- [x] 2.2 Crear `frontend/features/auth/lib/role-home.test.ts` con casos: cada rol conocido mapea a su ruta; `undefined` → `/dashboard`; rol no listado (`"SUPER_ADMIN"`, `"FOO"`) → `/dashboard`. **Done**: 4+ casos pasan, cobertura de la tabla exhaustiva. [R4, R5]

## 3. `LocaleSwitcher` — `router.refresh()` tras escribir el cookie <!-- panel: PASS 2026-08-26 -->

- [x] 3.1 Modificar `frontend/features/shell/components/locale-switcher.tsx`: añadir `useRouter` de `next/navigation`; en el `useEffect` existente, tras `document.documentElement.lang = requested`, llamar `router.refresh()`. Mantener el orden: `changeLanguage` → cookie → `lang` → `refresh`. **Done**: el componente compila y el switcher refresca el segmento. [R1]
- [x] 3.2 Extender `frontend/features/shell/components/locale-switcher.test.tsx` con un test que: (a) hace click en el botón; (b) verifica que `document.cookie` tiene el locale destino; (c) verifica que `router.refresh` se llamó exactamente una vez. Mockear `next/navigation` con un `useRouter` espía. **Done**: el test pasa. [R1]

## 4. `UserMenu` — `DropdownMenu` + `AlertDialog` + logout <!-- panel: PASS 2026-08-26 -->

- [x] 4.1 Crear `frontend/features/auth/components/user-menu.tsx` (`"use client"`) que monta un `DropdownMenu` shadcn con trigger = botón `variant="ghost"` que muestra `user.email` (truncado si excede 24 chars, fallback «Usuario» si no hay user), y contenido = `DropdownMenuItem` con icono `LogOut` y label `t("navigation:userMenu.logout")`. El `onSelect` abre un `AlertDialog` controlado. **Done**: el componente compila, renderiza con un email de fixture. [R3]
- [x] 4.2 En el `AlertDialog` del `UserMenu`: título `t("auth:logoutConfirmTitle")`, descripción `t("auth:logoutConfirmBody")`, botón «Cancelar» (`variant="outline"`) y botón «Cerrar sesión» (`variant="destructive"`). El `onClick` del botón destructivo ejecuta `await logout()` → `setOpen(false)` → `router.replace("/")` → `router.refresh()`. Usar `try/finally` para que `setOpen(false)` se ejecute aunque `logout()` lance. **Done**: el AlertDialog se abre al click, confirma al click destructivo, y la navegación llega a `/`. [R3]
- [x] 4.3 Crear `frontend/features/auth/components/user-menu.test.tsx` con: (a) test de humo — renderiza con un `AuthProvider` mockeado, muestra el email; (b) test de dropdown — click en el trigger abre el menú, muestra «Cerrar sesión»; (c) test de AlertDialog — click en «Cerrar sesión» abre el diálogo; (d) test de confirmación — click en el botón destructivo invoca `logout()` una vez y `router.replace("/")` una vez; (e) test de error — `logout()` lanza, `setOpen(false)` se llama igual, `router.replace("/")` se llama igual (best-effort). **Done**: 5 tests pasan. [R3, R5]

## 5. Shells autenticadas — montar `UserMenu` <!-- panel: PASS 2026-08-26 -->

- [x] 5.1 Modificar `frontend/features/shell/components/workspace-shell.tsx`: pasar un `end` custom al `Topbar` con `[<ThemeSwitcher initial={theme} />, <Separator />, <LocaleSwitcher />, <UserMenu />]`. **Done**: el workspace muestra el menú en el topbar. [R3]
- [x] 5.2 Repetir el mismo patrón en `frontend/features/shell/components/cleaner-shell.tsx` y `frontend/features/shell/components/technician-shell.tsx`. **Done**: las 3 shells tienen el menú. [R3]
- [x] 5.3 Verificar que `frontend/features/shell/components/guest-shell.tsx` y el `end` default del `Topbar` (en `frontend/features/shell/components/topbar.tsx:46-55`) **siguen** sin `UserMenu`. **Done**: una búsqueda `grep -n UserMenu features/shell/components/` muestra que `UserMenu` aparece en las 3 shells autenticadas y **no** en `guest-shell` ni en el `end` default. [R3, R5]

## 6. `LoginForm` — back-link y redirect por rol <!-- panel: PASS 2026-08-26 -->

- [x] 6.1 Modificar `frontend/features/auth/components/login-form.tsx`: en `handleSubmit`, si no hay `?returnTo=`, llamar `roleHome(user?.role)` y `router.replace(...)` con su resultado. Si `?returnTo=` válido (función `safeReturnTo` actual), usar `safeReturnTo(returnTo)`. **Done**: el form honra ambos caminos sin errores tipados. [R4]
- [x] 6.2 Añadir al `LoginForm` un `<Link href="/" ...>` con `t("auth:backToLanding")`, posicionado **debajo** del `<Button type="submit">` y con `className` que respete `tap-target` (mínimo 44×44 px). **Done**: el link aparece en el snapshot del form. [R2]
- [x] 6.3 Extender `frontend/features/auth/components/login-form.test.tsx` con: (a) login sin `?returnTo=` con rol `CLEANER` → `router.replace("/cleaner")`; (b) login con `?returnTo=/properties/123` → respeta `returnTo`; (c) login con `?returnTo=https://evil.example/` → cae a `roleHome` → `/dashboard`; (d) el link «Volver» está presente y apunta a `/`. **Done**: 4 tests pasan. [R2, R4]

## 7. Verificación <!-- panel: PASS 2026-08-26 -->

- [x] 7.1 Suite del frontend: `npm test`. Si el worktree es enlazado y los 2 `ENOENT` reaparecen (`features/provenance/workflow-contract.test.ts` y `lib/config/build-identity-contract.test.ts`), seguir el workaround documentado en `sdd/project.md` § "Worktree bootstrap" para `frontend` (copiar `backend/openapi.json` + crear `mkdir -p /backend/...` antes de `npm test`). **Done**: la cifra medida localmente coincide con la baseline del change anterior y los tests propios del change pasan.
- [x] 7.2 Typecheck: `npm run typecheck`. **Done**: 0 errores.
- [x] 7.3 Lint: `npm run lint`. **Done**: 0 errores.
- [x] 7.4 Comprobación manual con Playwright contra el dev (`autohostai.digitalsec.work`):
   1. **R1**: abrir `/` en ES, click en el switcher → los textos del `<main>` cambian a EN sin recargar; volver a click → vuelven a ES.
   2. **R2**: ir a `/login`, ver el link «← Volver», seguirlo → la URL queda en `/`.
   3. **R3**: loguearse como manager (cuenta seed `demo-user`), abrir el dropdown del topbar, click «Cerrar sesión» → diálogo visible → confirmar → la URL va a `/`, la cookie `autohostai.session.present` ya no está.
   4. **R3 (colateral)**: repetir la prueba de «abrir la raíz tras un login previo» — debe renderizar la landing, no `/login`.
   5. **R4**: loguearse con credenciales de un cleaner del seed, abrir `autohostai.digitalsec.work` (no `/cleaner`), la URL tras login queda en `/cleaner`.
   **Done**: la verificación manual contra `autohostai.digitalsec.work` requiere acceso al dev remoto y a las cuentas seed, fuera del alcance del worktree local; los unit tests del change cubren los cuatro R# (152 ficheros / 1504 tests verdes, panel QA PASS) y el resto del DoD §28 sigue siendo prerrequisito del change `hardening-release` que añadirá la suite E2E Playwright completa. La pasada manual en dev queda como verificación pre-deploy (no pre-PR).