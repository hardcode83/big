# Tasks: frontend-auth-session

## 1. Configuración y almacén efímero

- [x] 1.1 Añadir `apiBaseUrl` a `frontend/lib/config/public.ts` con valor por defecto same-origin y actualizar `frontend/lib/config/public.test.tsx` y `frontend/app/providers.test.tsx` para cubrir el snapshot público sin exponer `BACKEND_INTERNAL_URL`. [R3]
- [x] 1.2 Crear `frontend/lib/auth/session-store.ts` y `frontend/lib/auth/session-store.test.ts` con lectura/escritura atómica en memoria de access y refresh JWT, limpieza idempotente y sin APIs de almacenamiento persistente. [R2, R3]
- [x] 1.3 Crear `frontend/lib/auth/index.ts` con la superficie pública de auth y documentar en `frontend/README.md` que reload, cierre de pestaña o nuevo runtime pierden la sesión y requieren login; dejar explícita la ausencia de cookies, BFF, middleware y persistencia. [R2, R4]

## 2. Transporte tipado y coordinación de refresh

- [x] 2.1 Extender `frontend/lib/api/client.ts` para conservar el método/path, saber si la petición envió `Authorization: Bearer`, excluir `login`, `refresh` y `logout`, y limitar la recuperación a un `401` de una petición elegible no reintentada. Mantener la inferencia OpenAPI existente. [R2, R3]
- [x] 2.2 Actualizar `frontend/lib/api/client.test.ts` con casos de petición anónima, petición autenticada elegible, endpoints de auth excluidos, primer retry exitoso, fallo de recuperación y no más de un retry de la petición original. [R2, R3]
- [x] 2.3 Crear `frontend/lib/auth/refresh-coordinator.ts` y `frontend/lib/auth/refresh-coordinator.test.ts` como infraestructura single-flight fuera de React: una operación compartida por pareja de tokens, sustitución atómica tras rotación y limpieza idempotente al fallar. [R2]
- [x] 2.4 Probar en `frontend/lib/auth/refresh-coordinator.test.ts` el fan-out de fallo: todas las requests que esperan el mismo refresh reciben el mismo fallo, ninguna reintenta su request, ninguna inicia un segundo refresh y el estado queda sin tokens. [R2]

## 3. AuthProvider y ciclo de identidad

- [x] 3.1 Crear `frontend/lib/auth/auth-provider.tsx` y su test con el contexto `user/status/login/logout/refresh`, una instancia estable del cliente API y consumo del `refresh-coordinator` sin que React sea propietario del single-flight. [R1, R2, R3]
- [x] 3.2 Implementar en `AuthProvider` el login con `POST /api/v1/auth/login`, escritura temporal de la pareja en memoria y carga posterior de `GET /api/v1/auth/me`; ante fallo de login o `me`, mostrar fallo localizado y limpiar la sesión. [R1]
- [x] 3.3 Implementar logout best-effort con `POST /api/v1/auth/logout`, limpieza local siempre, sin refresh automático de su `401`, y resultado de UI `anonymous`; cubrirlo en el test del provider. [R4]
- [x] 3.4 Integrar `AuthProvider` en `frontend/app/providers.tsx` entre `I18nProvider` y `QueryProvider`, y actualizar `frontend/app/providers.test.tsx` para verificar el orden funcional y que una petición sin sesión no recibe credenciales. [R3]
- [x] 3.5 Cubrir en los tests del provider que un fallo del refresh compartido solo limpia una vez, propaga el resultado a los consumidores, deja el estado `anonymous`/`expired` y no navega individualmente desde cada petición. [R2, R4]

## 4. Login e internacionalización

- [x] 4.1 Añadir `frontend/locales/es/auth.json`, `frontend/locales/en/auth.json` y registrar el namespace `auth` en `frontend/lib/i18n/resources.ts`, con claves para formulario, carga, errores genéricos, refresh, expiración y logout. [R5]
- [x] 4.2 Crear `frontend/features/auth/components/login-form.tsx` y sus tests con campos localizados, envío tipado al provider, estado de carga, error localizado, ausencia de contraseña en logs/estado visible y permanencia en `/login` ante fallo. [R1, R5]
- [x] 4.3 Sustituir el `RoutePlaceholder` de `frontend/app/(public)/login/page.tsx` por el formulario real y actualizar los tests de wiring/shell pública para conservar la ruta pública y su metadata. [R1, R5]
- [x] 4.4 Actualizar `frontend/lib/i18n/catalog-parity.test.ts` y cualquier test de recursos necesario para exigir paridad completa del namespace `auth` en ES/EN. [R5]

## 5. Guards client-side y límites de autorización

- [x] 5.1 Crear `frontend/features/auth/components/auth-guard.tsx` y sus tests para estados loading/authenticated/anonymous, redirección client-side a `/login` con retorno solo a rutas internas seguras y estado localizado durante carga. [R4, R5]
- [x] 5.2 Envolver las superficies operativas mediante los layouts de `frontend/app/(workspace)/layout.tsx` y los layouts de cleaner/technician, sin añadir guard JWT a la shell pública ni al portal guest; cubrir la selección en tests de routing. [R4]
- [x] 5.3 Verificar en tests del guard y provider que `role` y `tenant_id` solo se exponen como contexto para UI/datos y no implementan RBAC, autorización de negocio ni tenant isolation. [R4]
- [x] 5.4 Actualizar comentarios y documentación de `frontend/features/shell/components/public-shell.tsx`, `frontend/README.md` y puntos de integración para explicar que el guard es UX/client-side, no protege HTML server-rendered y no sustituye al backend. [R4]

## 6. Compatibilidad del dashboard

- [x] 6.1 En `frontend/features/dashboard/hooks/use-dashboard-data.ts` sustituir únicamente `DEV_TENANT_ID` por `tenant_id` procedente del contexto de auth y ajustar únicamente su test asociado para el nuevo contexto. Conservar fixtures, estructura del dashboard y comportamiento no conectado. [R3, R4]
- [x] 6.2 Eliminar `DEV_TENANT_ID` de `frontend/lib/config/constants.ts` solo si queda sin referencias tras 6.1; no refactorizar dashboard, no cambiar fixtures y no conectar endpoints reales. [R3]

## 7. Verificación

- [x] 7.1 Ejecutar la suite frontend completa desde `frontend/`: `npm test`. [R1, R2, R3, R4, R5]
- [x] 7.2 Ejecutar lint desde `frontend/`: `npm run lint`, verificando las fronteras `app → features → components/lib` y ausencia de imports prohibidos. [R3, R4]
- [x] 7.3 Ejecutar typecheck desde `frontend/`: `npm run typecheck`, verificando los tipos OpenAPI de login, refresh, logout y me. [R1, R2, R3]
- [x] 7.4 Ejecutar build de producción desde `frontend/`: `npm run build`, confirmando que no se introducen lecturas server-only en Client Components ni dependencias de backend en el shell. [R3, R4]
- [x] 7.5 Revisar con los tests y una inspección final que no existan escrituras de tokens en `localStorage`, `sessionStorage`, IndexedDB o cookies, que no exista `middleware.ts` de autenticación y que el diff no toque `backend/**`, `auth-tenancy` ni el contrato OpenAPI. [R2, R4]
