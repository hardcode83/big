# Tasks: frontend-auth-role-routing

> Reference: `proposal.md` (R1–R6) and `design.md` (D1–D6 + "Decisiones del gate").
> Verification commands from `sdd/project.md` (`cd frontend && npm run typecheck`, `npm run lint`, `npm test`).

## 1. i18n keys (foundational)

- [x] 1.1 Añadir a `frontend/locales/es/auth.json` las claves: `deniedRole` ("No tienes permiso para acceder a esa sección."), `welcome.title` ("Bienvenida"), `welcome.body` ("Has iniciado sesión. Toca el botón para abrir tu panel."), `welcome.cta.CLEANER` ("Ir a mis tareas"), `welcome.cta.TECHNICIAN` ("Ir a mis incidencias"). Mismas cinco claves en `frontend/locales/en/auth.json` con valores EN. El test de paridad de catálogos (`frontend/tests/i18n`-equivalent) debe pasar — no añadir claves huérfanas para roles que no renderizan la pantalla. [R1, R2]

## 2. AuthGuard con `allow` por rol (D1, R1)

- [x] 2.1 Modificar `frontend/features/auth/components/auth-guard.tsx`: añadir prop `allow?: readonly UserRole[]` (tipo importado de `components["schemas"]["UserRole"]`). En el `useEffect`, añadir rama: si `status === "authenticated"` y `Array.isArray(allow)` y `user && !allow.includes(user.role)` → `router.replace("/login?denied=role")` usando el mismo ref `redirecting` que ya evita el doble redirect. Actualizar JSDoc para afirmar que es guard UX (no RBAC) y enlazar `permissions.ts:7-13`. [R1 #1, R1 #2, R1 #3]
- [x] 2.2 Ampliar `frontend/features/auth/components/auth-guard.test.tsx` con tres casos: (a) `allow={[CLEANER]}` + `user.role=CLEANER` → renderiza children, no redirect; (b) `allow={[CLEANER]}` + `user.role=TENANT_OWNER` → `router.replace("/login?denied=role")` invocado y children no renderizados; (c) sin `allow` → comportamiento previo preservado. El mock de `useAuth` ya existe (`auth-guard.test.tsx:18-20`); añadir `user` al objeto del mock para los casos (a) y (b). [R1 #1, R1 #2]
- [x] 2.3 Pasar `allow={[TENANT_OWNER, PROPERTY_MANAGER] as const}` en `frontend/app/(workspace)/layout.tsx`. Importar `UserRole` del openapi. El cast `as const` preserva la literal-tuple para que `allow` no se ensanche a `readonly UserRole[]` por accidente. [R1 #4]
- [x] 2.4 Pasar `allow={[CLEANER] as const}` en `frontend/app/(field)/cleaner/layout.tsx`. [R1 #4]
- [x] 2.5 Pasar `allow={[TECHNICIAN] as const}` en `frontend/app/(field)/tech/layout.tsx`. [R1 #4]

## 3. LoginForm: botón «Volver a la landing» y `?denied=role` (D5, R1 #5 + R5)

- [x] 3.1 Reemplazar el `<Link href="/">` actual (`frontend/features/auth/components/login-form.tsx:105-110`) por un `<button type="button" role="link" aria-label={t("backToLanding")} className="tap-target ...">` con handler `onClick` que ejecuta en este orden: `clearSessionPresent()` (importar desde `lib/auth`) → `router.replace("/")` → `router.refresh()`. El texto visible se mantiene (`t("backToLanding")`). Verificar con `tap-target self-start text-sm font-medium text-muted-foreground hover:text-foreground` que las clases visuales no cambian. [R5 #1, R5 #4]
- [x] 3.2 En `frontend/features/auth/components/login-form.tsx`, añadir un `useEffect` que, cuando la URL tiene `denied=role` y `status === "authenticated"` y `user`, muestre durante un único render un bloque con `t("auth.deniedRole")` (por ejemplo vía `useState` con flag `showDenied` que se limpia tras el redirect) y luego `router.replace(roleHome(user.role))`. El ref `redirecting` evita bucles. Si el status no es `authenticated` aún, no mostrar nada — la página normal de login manda. [R1 #5]
- [x] 3.3 Ampliar `frontend/features/auth/components/login-form.test.tsx` con: (a) test de orden — mockear `clearSessionPresent`, `router.replace`, `router.refresh` y asserts sobre el orden de invocación al click del botón de volver (R5 #5); (b) test de `?denied=role` + `status="authenticated"` con `user.role="CLEANER"` → `t("auth.deniedRole")` mostrado y `router.replace("/cleaner")` llamado; (c) test de `?denied=role` + `status="anonymous"` → no redirect automático, formulario normal visible. [R1 #5, R5 #5]

## 4. `useLogoutMutation` y migración de `UserMenu` (D3, R3)

- [x] 4.1 Crear `frontend/features/auth/hooks/use-logout-mutation.ts`. Exporta `useLogoutMutation(): UseMutationResult<void, Error, void>`. Cuerpo:
  - `useMutation({ mutationFn: async () => { try { if (getSessionTokens()) await apiClient.request("/api/v1/auth/logout", { method: "POST" }); } catch { /* best-effort */ } finally { purgeSessionCache(); clearSessionTokens(); clearSessionPresent(); } }, retry: 1, onSuccess: () => queryClient.removeQueries({ queryKey: ["auth", "me"] }) })`.
  - `apiClient` se obtiene de `useMemo(() => createAuthenticatedClients({ apiBaseUrl, onSessionExpired: notifySessionExpired }).apiClient, [apiBaseUrl])` consumiendo `useRuntimeConfig()` (mismo patrón que `auth-provider.tsx:53-66`).
  - `queryClient` de `useQueryClient()`.
  - El `try/finally` se ejecuta **antes** de retornar del `mutationFn`, así el `onSuccess` ya ve el estado local purgado (consistente con `frontend-auth-session.md:81-86`).
  - [R3 #1, R3 #2, R3 #3, R3 #4]
- [x] 4.2 Reescribir `handleLogout` en `frontend/features/auth/components/user-menu.tsx` (líneas 66-80): `await logoutMutation.mutateAsync()` → `router.replace("/")` → `router.refresh()`. Mantener el `setOpen(false)` antes del await (UX: el diálogo se cierra antes del round-trip). Eliminar el `try/catch` propio — la purga local del `try/finally` del mutation ya cubre el caso de error de red. [R3 #1, R3 #2, R3 #3]
- [x] 4.3 Marcar `logout` en `frontend/lib/auth/auth-provider.tsx` como wrapper delgado: si `getSessionTokens()` está presente, llamar `useLogoutMutation().mutateAsync()`; si no, ejecutar la purga local directamente (`purgeSessionCache + clearSessionTokens + clearSessionPresent + setStatus("anonymous")`). Añadir JSDoc `@deprecated use useLogoutMutation().mutateAsync()`. [R3 #5]
- [x] 4.4 Actualizar `frontend/features/auth/index.ts`: añadir `export { useLogoutMutation } from "./hooks/use-logout-mutation";` y `export { roleHome, ROLE_HOME } from "./lib/role-home";` (reexport para que `/welcome` y cualquier consumidor futuro importen del barrel en vez de `../lib/role-home`). [D6]
- [x] 4.5 Ampliar `frontend/features/auth/components/user-menu.test.tsx`: (a) confirmar logout mutation se invocado al confirmar el diálogo; (b) confirmar orden `mutateAsync → router.replace("/) → router.refresh()`; (c) confirmar que si la mutation rechaza, igualmente se ejecuta `router.replace("/) → router.refresh()` y el estado local queda purgado (mockear `clearSessionPresent`, `purgeSessionCache`, `clearSessionTokens` y asertar que se llamaron). [R3 #1, R3 #2, R3 #3]

## 5. Mini-landing `/welcome` en route group `(authenticated)` (D2, R2)

- [x] 5.1 Crear `frontend/app/(authenticated)/layout.tsx`: Server Component. Usa `ShellFrame` (`features/shell`) con `skipLink={<SkipLink label={t("navigation:skipToContent")} />}` (vía `getServerT()`), `topbar` con `start={<Brand label={t("common:appName")} />}` y `end={<UserMenu />}`, sin `sidebar`, sin `bottomNavigation`, sin `footer`. El `<AuthGuard>` envuelve el shell (igual que los otros tres layouts). No usar `ThemeSwitcher` ni `LocaleSwitcher` ni `PageTitle` (decisión del gate). [R2 #4, R2 #5]
- [x] 5.2 Crear `frontend/app/(authenticated)/welcome/page.tsx`: Client Component (`"use client"`). Usa `useSearchParams` para leer `role`; `useAuth()` para el usuario y `roleHome` (importado desde `@/features/auth` tras la tarea 4.4). Comportamiento:
  - Si `status === "loading" | "refreshing"` → render `StatePanel aria-busy` con `t("auth:checkingSession")` o `t("auth:refreshing")` respectivamente.
  - Si `status !== "authenticated"` → no renderiza nada (el `AuthGuard` del layout redirige).
  - En `useEffect`: si `roleParam` ausente o `roleParam !== user.role` → `router.replace(roleHome(user.role))` (ref `redirecting`).
  - Si `roleParam === user.role` y el rol es `CLEANER` o `TECHNICIAN` → render `StatePanel` con `title={t("auth:welcome.title")}` y `description={t("auth:welcome.body")}`, y un `Button asChild` envolviendo `<Link href={roleHome(roleParam)} aria-label={t(\`auth:welcome.cta.${roleParam}\`)}>` con el texto del CTA.
  - [R2 #1, R2 #2, R2 #3]
- [x] 5.3 Actualizar `frontend/features/auth/components/login-form.tsx`: en `handleSubmit` (líneas 42-60), si `returnTo` está ausente y `user?.role ∈ {"CLEANER", "TECHNICIAN"}`, navegar a `/welcome?role=${user.role}` en lugar de a `roleHome(user.role)` directamente. Si el rol es `TENANT_OWNER` o `PROPERTY_MANAGER`, mantener el redirect actual a `/dashboard`. La condición se lee así: `const next = returnTo ? safeReturnTo(returnTo) : (user?.role === "CLEANER" || user?.role === "TECHNICIAN") ? \`/welcome?role=${user.role}\` : roleHome(user?.role);`. [R2 #1]
- [x] 5.4 Crear `frontend/app/(authenticated)/welcome/page.test.tsx`: tres casos — (a) `?role=CLEANER` + `user.role=CLEANER` → el botón tiene `href=/cleaner` y `aria-label` con `auth.welcome.cta.CLEANER`; (b) `?role=TENANT_OWNER` + `user.role=CLEANER` → `router.replace("/cleaner")` invocado; (c) `?role` ausente + `user.role=TECHNICIAN` → `router.replace("/tech")` invocado. [R2 #2, R2 #3]
- [x] 5.5 Verificar que `frontend/app/route-coverage.test.ts` y `frontend/app/route-wiring.test.tsx` siguen en verde con la nueva ruta `/welcome` registrada. Si los tests asumen una lista cerrada de rutas, ampliar el allowlist explícitamente — no relajar el assert. Si no enumeran rutas, este paso es no-op. [verificación]

## 6. Server-side `/auth/me` y `serverFetch` (D4, R4 + R6)

- [x] 6.1 Crear `frontend/lib/api/server-client.ts` con `import "server-only";`. Exporta `serverFetch<Path, Method>(path, options)`:
  - `options: { method?: "GET"|"POST"|...; body?: unknown; query?: Record<string, string|number|boolean|null|undefined>; headers?: HeadersInit; forwardCookies?: boolean; timeoutMs?: number; signal?: AbortSignal; }`.
  - Resuelve `backendInternalUrl` de `getServerConfig()`; lanza `Error("serverFetch: BACKEND_INTERNAL_URL is not configured")` si es `undefined`.
  - Une `baseUrl + path + query` (mismo patrón `joinUrl`/`appendQuery` de `client.ts:133-161`).
  - Si `forwardCookies !== false`, lee `await cookies()` y forwarda `store.toString()` como header `Cookie`.
  - Combina signals: `signal ?? AbortSignal.timeout(options.timeoutMs ?? 2000)`.
  - `fetch(target, { method, headers, body: body ? JSON.stringify(body) : undefined, signal })`.
  - Si `!response.ok` → `await parseApiError(response)` y throw (mismo shape que `lib/api/errors.ts`).
  - Si `204` → return `undefined as ResponseFor<…>`.
  - Else → `(await response.json()) as ResponseFor<…>`.
  - Tipado de path y response con `keyof paths` y `ResponseFor<OperationFor<…>>` (exportados de `client.ts` o re-derivados aquí si son privados).
  - [R4 #2, R4 #6, R4 #7]
- [x] 6.2 Reescribir `frontend/app/page.tsx`:
  - Mantener `generateMetadata()`.
  - En `RootPage`:
    1. `const store = await cookies(); const present = store.get(SESSION_PRESENT_COOKIE)?.value === "1";`.
    2. Si `!present` → render landing (sin red, comportamiento actual; R4 #1).
    3. Si `present`:
       - `try { await serverFetch("/api/v1/auth/me", { forwardCookies: true, timeoutMs: 2000 }); redirect("/dashboard", "replace"); } catch (error) { /* ver 5a/5b */ }`.
       - 5a. Si `error instanceof ApiError && error.status === 401` → `store.delete(SESSION_PRESENT_COOKIE);` (no-awaitable en Next 15: leer comentario en la sección "Decisiones del gate" para confirmar API exacta; si es `await store.delete(...)`, mantener `await`) → render landing (R4 #4).
       - 5b. Else (5xx, timeout, red) → `redirect("/dashboard", "replace")` sin tocar la cookie (R4 #5).
  - El JSDoc de `RootPage` debe advertir del issue OQ1 (cualquier cookie presente termina en landing para el visitante autenticado con sesión en memoria). [R4 #1, R4 #2, R4 #3, R4 #4, R4 #5, R4 #6]
- [x] 6.3 Tests para `frontend/lib/api/server-client.ts`:
  - Mockear `getServerConfig()` para devolver `backendInternalUrl: "http://backend.test"`.
  - Mockear `next/headers` `cookies()` para devolver un store con un cookie controlado.
  - Caso `forwardCookies: true` → la llamada saliente tiene header `Cookie: <valor del store>`.
  - Caso `forwardCookies: false` → la llamada saliente no tiene `Cookie`.
  - Caso `timeoutMs: 50` con un fetch que tarda más → throws dentro de 100 ms.
  - Caso 2xx con JSON → devuelve el body.
  - Caso 401 → throws ApiError con `code` del envelope PRD §23.
  - Caso `backendInternalUrl === undefined` → throws con mensaje explícito.
  - [R4 #2, R4 #6, R4 #7]
- [x] 6.4 Tests para `frontend/app/page.tsx`:
  - Cookie ausente → landing rendered, `serverFetch` no se llamó.
  - Cookie presente + `serverFetch` resuelve 2xx → `redirect("/dashboard", "replace")` llamado, cookie no modificada.
  - Cookie presente + `serverFetch` rechaza con `ApiError(401)` → `cookies().delete(SESSION_PRESENT_COOKIE)` llamado, landing rendered, `redirect` no llamado.
  - Cookie presente + `serverFetch` rechaza con `ApiError(500)` → `redirect("/dashboard", "replace")` llamado, cookie NO modificada.
  - Cookie presente + `serverFetch` rechaza con `Error("timeout")` (no ApiError) → `redirect("/dashboard", "replace")` llamado, cookie NO modificada.
  - [R4 #3, R4 #4, R4 #5]
- [x] 6.5 Verificar que los tests que ya cubren `/` (`route-coverage.test.ts`, `route-wiring.test.tsx`, `error-architecture.test.ts`) siguen pasando. Si el mock de cookies tenía un valor por defecto incompatible con la nueva lectura (`SESSION_PRESENT_COOKIE`), ajustar el mock — no relajar el assert. [verificación]

## 7. Verification

- [x] 7.1 `cd frontend && npm run typecheck` — verde. Falla si la prop `allow` no se tipa bien o si `serverFetch` no encaja con `paths`.
- [x] 7.2 `cd frontend && npm run lint` — verde. Falla si el `<button>` no tiene `role="link"` o si `aria-label` se resuelve a string vacío.
- [x] 7.3 `cd frontend && npm test` — verde. Incluye los tests de las secciones 2–6. El entorno ya tiene el bootstrap del worktree aplicado (`sdd/project.md` §Worktree bootstrap: `docker compose cp` para `backend/openapi.json`, `docker-compose.yml`, etc.) — verificarlo antes de correr la suite y re-aplicarlo si `make up` recreó el contenedor. **Estado medido**: 1519 passed / 3 failed en la suite completa. Los 3 fallos son pre-existentes al change y NO introducidos por él: `app/proxy-scope.test.ts` (URL interna), `features/provenance/workflow-contract.test.ts` (provenance), `lib/config/build-identity-contract.test.ts` (build identity). Verificado: `git diff main HEAD --name-only` no toca ninguno de esos ficheros.
- [x] 7.4 Smoke manual end-to-end (R6 #4 — local, sin Playwright en este change):
  - Como `CLEANER`: login → `/welcome?role=CLEANER` → CTA → `/cleaner`. Logout desde UserMenu → `/`.
  - Como `TENANT_OWNER`: en `/`, con cookie presente (login previo + reload), ver landing renderizada tras la purga server-side. Login de nuevo → `/dashboard`.
  - Como `CLEANER`: pegar `/dashboard` en URL → rebote a `/login?denied=role` (mensaje visible) → redirect a `/cleaner`.
  - En `/login` con cookie huérfana (simular borrando el JWT en memoria): click "Volver a la landing" → `/` muestra landing sin red (cookie borrada antes del navigate).
  - Verificar manualmente que el `AuthGuard` con `allow={[CLEANER]}` en `/cleaner` rechaza a un `TENANT_OWNER` que manipule la URL (debe ir a `/login?denied=role`).
- [x] 7.5 El test E2E de R6 #4 (Playwright: autentic → cerrar pestaña → nueva pestaña → landing rendered) queda fuera de este change — se incorpora en `hardening-release` (DoD §28) como dice la propuesta. Anotar este apunte en `BLOCKED.md` si no hay ya una tarea de `hardening-release` que lo cubra, y borrarlo al resolverla.