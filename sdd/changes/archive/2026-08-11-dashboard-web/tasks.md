# Tasks: dashboard-web

## 1. Cliente autenticado compartido

- [x] 1.1 Extraer la creación del `ApiClient` autenticado a
  `frontend/lib/api/authenticated-client.ts`, conservando las cabeceras JWT en
  memoria, la recuperación coordinada ante `401` y el único reintento;
  mantener `frontend/lib/auth/auth-provider.tsx` sobre esa factory y cubrir
  login, refresh y logout con sus pruebas existentes o ampliadas [R3.1, R4.2].
- [x] 1.2 Verificar que la factory admite el `apiBaseUrl` configurado y que el
  dashboard puede usar el proxy same-origin por defecto, sin introducir
  secretos, persistencia de sesión ni una segunda política JWT
  [R3.1, R4.2].

## 2. Mapeadores y adapter HTTP

- [x] 2.1 Crear `frontend/features/dashboard/data/http/` y sus pruebas con
  respuestas snake_case basadas exclusivamente en los tipos generados de
  `frontend/lib/api/generated/openapi.d.ts`; comprobar envelopes, nulls,
  fechas, decimales, URLs firmadas y que no se sintetizan campos ausentes ni
  se consultan endpoints fuera de las tres rutas del change [R2.1, R2.2].
- [x] 2.2 Implementar en
  `frontend/features/dashboard/data/http/http-dashboard-source.ts` el método
  `getDashboardCards`, solicitando solo
  `GET /api/v1/dashboard/properties`, mapeando explícitamente cada campo y
  conservando el envelope paginado; probar la ruta, el cliente tipado, el
  mapeo y el orden de `data` [R1.1, R2.1, R2.2].
- [x] 2.3 Implementar `getPropertyDetail` en el mismo adapter, solicitando solo
  `GET /api/v1/properties/{property_id}/dashboard` y mapeando explícitamente
  reserva, huésped, acceso, limpieza, fotos, incidencias, finanzas, notas y
  aprobaciones; probar `null`, listas vacías, importes y URLs proporcionadas
  por backend sin construir URLs de storage [R1.2, R2.1, R2.2, R2.3].
- [x] 2.4 Implementar `getPropertyTimeline`, solicitando solo
  `GET /api/v1/timeline/{property_id}`, convirtiendo explícitamente los
  filtros definidos a `event_type`, `severity`, `actor_type`, `from` y `to`,
  omitiendo los ausentes y conservando el orden y envelope recibidos; probar
  cada filtro y combinaciones sin añadir llamadas al endpoint global ni a
  `/properties/{id}/state` [R1.3, R2.1, R2.2, R3.3].
- [x] 2.5 Propagar sin envolver los errores del `ApiClient`, especialmente
  `ApiError` 404 para detalle y timeline, y añadir pruebas de 401/404/422/5xx
  que confirmen que no se inventa un error de dominio ni se hace retry dentro
  del adapter [R3.1, R3.2].

## 3. Sustitución en el composition point

- [x] 3.1 Cambiar únicamente
  `frontend/features/dashboard/data/index.ts` para construir y devolver
  `HttpDashboardSource` con el cliente autenticado; conservar las firmas
  públicas de `DashboardDataSource`, el mock aislado y la ausencia de llamadas
  al endpoint de estado [R4.1, R4.2].
- [x] 3.2 Mantener y ajustar, solo si fuese necesario,
  `frontend/features/dashboard/data/boundary.test.ts` y las pruebas del
  composition point para demostrar que ningún componente, hook, query key,
  store o locale importa `MockDashboardSource` o el adapter HTTP concreto
  [R4.1, R4.2].

## 4. Consistencia de tipos y documentación interna

- [x] 4.1 Actualizar únicamente los comentarios o tipos de
  `frontend/features/dashboard/data/dto.ts` que sigan describiendo endpoints
  antiguos, manteniendo los DTO públicos y sin añadir capacidades que no
  proporcionen las tres respuestas consumidas [R2.1, R4.2].
- [x] 4.2 Confirmar mediante revisión de imports que la implementación no
  calcula estados, colores, acciones ni traducciones de datos, no genera URLs
  de almacenamiento y no modifica componentes, hooks, query keys, locales ni
  el contrato OpenAPI [R2.3, R4.2].

## 5. Verification

- [x] 5.1 Ejecutar la suite frontend colocada: `cd frontend && npm test`
  [R1, R2, R3, R4].
- [x] 5.2 Ejecutar type-check: `cd frontend && npm run typecheck` [R4.3].
- [x] 5.3 Ejecutar lint: `cd frontend && npm run lint` [R4.3].
- [x] 5.4 Ejecutar build de producción sin backend en ejecución:
  `cd frontend && npm run build` [R4.3].
- [x] 5.5 Revisar el diff final y confirmar que solo existen cambios en el
  adapter HTTP, cliente autenticado compartido, composition point, pruebas y
  documentación/tipos estrictamente necesarios; no ejecutar `/sdd:design` ni
  modificar backend, OpenAPI o requisitos fuera de alcance [R4.2, R4.3].
