# Tasks: dashboard-web-frontend

Frontend-only, solo lectura, sobre fuente de datos mock. Toda ruta bajo
`frontend/`. Cada tarea lleva su test colocado (Vitest + Testing Library + axe);
la sección 7 corre la verificación completa. El sistema queda funcionando tras
cada sección: contrato → mock → acceso → i18n/colores → cards → detalle.

## 1. Contrato de datos (`DashboardDataSource`)

- [x] 1.1 Definir los DTOs que replican el envelope de la API real (PRD §23: data
  envelope, error `{error:{code,message,details}}`, fechas ISO-8601 UTC) para:
  property card (§9.1), lista de propiedades, detalle de propiedad (§9.2) y
  timeline de propiedad (§10) — `features/dashboard/data/dto.ts`. Sin lógica, solo
  tipos. [R3, R4]
- [x] 1.2 Definir la interfaz `DashboardDataSource` (`getDashboardCards()`,
  `getPropertyDetail(id)`, `getPropertyTimeline(id, filters)`) devolviendo los DTOs
  de 1.1, alineada con `GET /api/v1/properties/{id}/dashboard`,
  `GET /api/v1/properties`, `GET /api/v1/properties/{id}`,
  `GET /api/v1/timeline/{property_id}` — `features/dashboard/data/dashboard-source.ts`.
  [R3, R4]

## 2. Fuente mock y punto de composición <!-- panel: PASS 2026-07-31 (R3+R4, consolidado con §3) -->

- [x] 2.1 `MockDashboardSource` implementando la interfaz, con datos fijos y
  coherentes de REDES11 y PAJARITOS8 (estados canónicos del PRD, reservas, huésped,
  limpieza, incidencias, timeline, financiero) aislados en un módulo dedicado
  `features/dashboard/data/mock/` (fixtures separadas de la clase), marcados en
  código con `ASSUMPTION`/deuda. Test: los datos mock satisfacen la forma de los
  DTOs de 1.1. [R3]
- [x] 2.2 Punto único de composición (factoría/provider) que resuelve qué
  implementación de `DashboardDataSource` se usa —
  `features/dashboard/data/index.ts` — devolviendo hoy `MockDashboardSource`, de
  modo que sustituirla por `HttpDashboardSource` no requiera tocar UI ni hooks.
  Documentar en comentario la deuda de swap. [R3]
- [x] 2.3 `tenantId` de dev centralizado y único (`lib/config/constants.ts` o
  `lib/config/public.ts`, allowlisted), marcado `ASSUMPTION` y como punto de
  sustitución por el contexto de sesión de `auth-tenancy`; ningún componente
  hardcodea el tenant. [R3]

## 3. Acceso a datos con TanStack Query <!-- panel: PASS 2026-07-31 (R3+R4, consolidado con §2) -->

- [x] 3.1 Extender la factoría de claves tenant-scoped del shell
  (`lib/query/query-keys.ts`, `['tenant', tenantId, resource, ...scope]`, `tenantId`
  no vacío) con los recursos del dashboard, y crear los hooks `useDashboardCards`,
  `usePropertyDetail`, `usePropertyTimeline` (`features/dashboard/hooks/`) que
  consumen **solo** la interfaz vía el punto de composición de 2.2. Tests: la
  clave incluye el tenant; los hooks no importan `MockDashboardSource` ni sus
  datos. [R4, R3]

## 4. i18n y colores de estado operacional

- [x] 4.1 Catálogos `locales/es/dashboard.json` y `locales/en/dashboard.json` con
  todas las strings visibles de cards y detalle (labels de secciones, estados,
  vacíos, errores, "próxima acción/responsable"), registrar el namespace en la
  init de i18n. Nada hardcodeado. Test de paridad de catálogos es/en (falla si
  falta clave en un locale). [R5]
- [x] 4.2 Mapa estado operacional → color del PRD §9.1
  (`features/dashboard/lib/state-color.ts`), usando los nombres canónicos exactos
  (`VACANT_READY`, `AWAITING_CLEANING`, `CRITICAL_INCIDENT`, `BLOCKED_BY_OWNER`…)
  agrupados verde/azul/amarillo/rojo/gris. Test que cubre los 5 grupos y un estado
  desconocido (fallback gris). [R5]

## 5. Pantalla de property cards (`/dashboard`) <!-- panel: PASS 2026-07-31 (R1+R2, consolidado con §6) -->

- [x] 5.1 Componente presentacional `PropertyCard`
  (`features/dashboard/components/property-card.tsx`) que muestra los campos §9.1
  (código, estado+color de 4.2, reserva actual/próxima, huésped, check-in/out,
  estado de limpieza, nº incidencias abiertas, próxima acción+responsable, tiempo
  del último evento), sin lógica de negocio ni cálculo de estado. Test de render con
  un DTO de ejemplo + axe. [R1, R5]
- [x] 5.2 Convertir `app/(workspace)/dashboard/page.tsx` (hoy placeholder) en la
  pantalla real: consume `useDashboardCards`, renderiza la grilla de `PropertyCard`,
  y aplica los estados transversales `LoadingState`/`ErrorState`/`EmptyState`
  (`components/states/`) sin exponer detalle crudo de error. Tests de los tres
  estados (carga, error con reintento, vacío) contra el mock. [R1]

## 6. Página de detalle de propiedad (`/properties/[id]`) <!-- panel: PASS 2026-07-31 (R1+R2, consolidado con §5) -->

- [x] 6.1 Componentes presentacionales de las secciones de detalle §9.2
  (`features/dashboard/components/detail/`): reserva actual/próxima, datos de
  huésped, estado de acceso, estado de limpieza, incidencias abiertas, resumen
  financiero, notas, aprobaciones pendientes. Sin lógica de negocio. Fotos de última
  limpieza consumen la URL provista por el DTO — nunca construir URL de storage en
  cliente (en mock, URLs placeholder marcadas). Tests de render. [R2]
- [x] 6.2 Vista de timeline de la propiedad
  (`features/dashboard/components/detail/property-timeline.tsx`): orden inmutable,
  entradas en el idioma activo, filtros por tipo/actor con estado ligero en Zustand
  (no duplicar server state). Test de render y filtrado. [R2, R4]
- [x] 6.3 Convertir `app/(workspace)/properties/[id]/page.tsx` (hoy placeholder) en
  la página real: consume `usePropertyDetail` + `usePropertyTimeline`, compone
  timeline (6.2) + secciones (6.1), aplica loading/error/empty y un estado
  "no encontrado" localizado si el id no existe, sin romper el chrome del shell ni
  exponer IDs/tokens en breadcrumbs. Tests: render, id inexistente, error/carga. [R2]

## 7. Verificación

- [x] 7.1 Test de frontera de R3: assert de que componentes y hooks del feature no
  importan `MockDashboardSource` ni el módulo de datos mock directamente (solo la
  interfaz / el punto de composición) — `features/dashboard/data/boundary.test.ts`.
  [R6, R3]
- [x] 7.2 Suite de tests completa pasa: `cd frontend && npm test`. [R6]
- [x] 7.3 Typecheck y lint pasan: `cd frontend && npm run typecheck && npm run lint`.
  [R6]
- [x] 7.4 Build de producción sin backend en ejecución: `cd frontend && npm run build`.
  [R6]
- [x] 7.5 Comprobación manual del flujo: `cd frontend && npm run dev` → `/dashboard`
  muestra las cards de REDES11/PAJARITOS8 con colores de estado, y
  `/properties/redes11` muestra timeline + secciones, todo con datos mock. [R6]
