# Tasks: properties-web

Change de **frontend puro**: ningún fichero de `backend/`, ninguna migración, ningún endpoint. El orden de secciones deja el árbol compilando y la suite verde después de cada una.

> **Antes de correr `npm test` en este worktree**: el contenedor `frontend` monta sólo `./frontend`, así que dos ficheros de test leen por encima de `/app` y fallan con `ENOENT` sin tener nada que ver con este change. Hay que hacer el copiado que documenta `sdd/project.md` (§ Worktree bootstrap) una vez por contenedor. Sin él, la cifra de la suite no es interpretable. Y `npm run api:generate` / `api:check` **no funcionan** en un worktree enlazado — no hacen falta: este change no toca el backend y los tipos ya están generados y commiteados.

## 1. El componente transversal del badge, y la mudanza del panel <!-- panel: PASS 2026-08-22 -->
<!-- Panel: architect PASS · security PASS · qa PASS · i18n PASS · documentation PASS.
     No se lanzaron cicd (el diff no toca .github/ ni infra/) ni tenancy (no toca backend/).
     Dos recomendaciones de QA aplicadas en 1.2: el aserto de clases pasó de pertenencia
     por token a igualdad exacta sobre el vocabulario de color, y el test de exhaustividad
     tautológico (`toBeDefined()` bajo un fallback `?? "gray"`) se reescribió para exigir
     que los cinco grupos sigan alcanzados. Verificado por mutación: cambiar
     CRITICAL_INCIDENT a amber hace fallar 3 tests; añadir una clase sobrante hace fallar 5.
     Antes del arreglo, ambos casos habrían pasado. -->


Va primero porque es lo único que toca código ajeno: si rompe algo, se ve antes de haber construido nada encima.

- [x] 1.1 Crear `frontend/components/property-state-badge.tsx` con `PropertyStateBadge({ state, label })`, llevándose **los dos** mapas desde el panel: el de estado → grupo de color (hoy `features/dashboard/lib/state-color.ts`) y el de grupo → clases Tailwind (hoy `STATE_BADGE_CLASS` en `features/dashboard/components/property-card.tsx:19-27`), **incluido el fallback `?? "gray"`**. Tipar `state` sobre `components["schemas"]["PropertyOperationalState"]` del generado, nunca sobre la unión de `features/dashboard/data/dto.ts`. Copiar las cadenas de clases **carácter a carácter**, variantes `dark:` incluidas. [R4]
- [x] 1.2 Crear `frontend/components/property-state-badge.test.tsx` que fije, para cada uno de los cinco grupos de color, la cadena de clases exacta que el componente aplica, más el caso de un valor no mapeado cayendo a `gray`. **Es la única red que van a tener esos colores**: se verificó que ni `property-card.test.tsx` ni `dashboard-view.test.tsx` assertan sobre ellos. [R4]
- [x] 1.3 Refactorizar `frontend/features/dashboard/components/property-card.tsx` para consumir `PropertyStateBadge`, borrando su `STATE_BADGE_CLASS` local, y retirar `frontend/features/dashboard/lib/state-color.ts` junto con sus importaciones. No añadir nada a `features/dashboard/index.ts`. [R4]
- [x] 1.4 Verificar que `property-card.test.tsx` y `dashboard-view.test.tsx` pasan **sin editar ni una expectativa**. Si alguna hay que tocar, el refactor cambió comportamiento: pararse y revisarlo, no ajustar el test. [R4]

## 2. La capa de datos de la feature

- [ ] 2.1 Crear `frontend/features/properties/data/dto.ts`: DTOs en camelCase para la fila y el sobre de página, **re-exportando** `PropertyStatus` y `PropertyOperationalState` del generado en vez de transcribirlas. Sólo los 22 campos que `PropertyListItemResponse` trae de verdad — nada de `access_notes`, `cleaning_notes`, `emergency_notes` ni contraseña de WiFi, que el contrato no devuelve. [R1, R5]
- [ ] 2.2 Crear `frontend/features/properties/data/dto.test.ts` como test de frontera: un payload de ejemplo con el sobre `{data, total, page, per_page, total_pages}` se traduce a los DTOs, y el test falla si alguien asume un sobre `meta` anidado. [R1]
- [ ] 2.3 Crear `frontend/features/properties/data/http/http-properties-source.ts` contra `lib/api`: `GET /api/v1/properties` con `page`, `per_page` y los dos filtros, **omitiendo** el parámetro cuando el filtro vale «todos». El nombre que viaja por el cable es `status` (en Python el parámetro se llama `status_filter` con `alias="status"`). [R1, R2]
- [ ] 2.4 Crear `frontend/features/properties/data/http/http-properties-source.test.ts`: verifica la query string construida para cada combinación de filtros (ninguno, sólo `status`, sólo estado operativo, los dos) y que la respuesta se mapea a los DTOs. [R1, R2]
- [ ] 2.5 Crear `frontend/features/properties/data/index.ts` con el punto de composición `getPropertiesDataSource()`. **Sin `Mock*Source`**: se va directo a HTTP. [R1]

## 3. Claves de query, hook y mapeo de errores

- [ ] 3.1 Crear `frontend/features/properties/hooks/query-keys.ts` con `propertiesKeys.list(tenantId, filters)` sobre `tenantScopedKey` de `@/lib/query/query-keys`, de modo que toda clave empiece por `['tenant', tenantId, …]`. Construir el objeto de filtros con sus claves en **orden fijo**. [R1, R2]
- [ ] 3.2 Crear `frontend/features/properties/lib/error-mapping.ts` con la unión discriminada `loading | forbidden | not-found | validation | error | ok`: **401 → `loading`** (no parpadear durante la rotación de token) y **404 → error genérico** (una lista no «no existe»). [R3]
- [ ] 3.3 Crear `frontend/features/properties/lib/error-mapping.test.ts` cubriendo los seis casos, con un caso explícito para 401 y otro para 404 que fijen esas dos decisiones contra una regresión. [R3]
- [ ] 3.4 Crear `frontend/features/properties/hooks/use-properties.ts` (TanStack Query v5) usando el `retryPolicy` compartido de `@/lib/api/retry-policy`, que no reintenta 4xx. [R1, R3]
- [ ] 3.5 Crear `frontend/features/properties/hooks/use-properties.test.tsx`: la clave incluye tenant y filtros, dos renders equivalentes producen la misma clave, y un 4xx no se reintenta. [R1, R2, R3]

## 4. La pantalla

- [ ] 4.1 Crear `frontend/features/properties/components/list/properties-filters.tsx`: dos `<select>` controlados —`status` (2 valores) y `current_operational_state` (11)— cada uno con opción «todos». El padre posee el estado; el componente no guarda nada. Calcado de `ReservationsFilters`. [R2]
- [ ] 4.2 Crear `frontend/features/properties/components/list/properties-filters.test.tsx`: cambiar un filtro emite el objeto esperado, y la opción «todos» emite la ausencia del filtro, no una cadena vacía. [R2]
- [ ] 4.3 Crear `frontend/features/properties/components/list/properties-view.tsx`: tabla con las **seis** columnas en orden (nombre con enlace, código interno, ciudad, capacidad, estado operativo vía `PropertyStateBadge`, situación), paginación anterior/siguiente deshabilitada en los extremos, y los estados de `components/states/`. Cambiar cualquier filtro **resetea a la página 1**. Mobile-first. [R1, R2, R3, R4]
- [ ] 4.4 Crear `frontend/features/properties/components/list/properties-view.test.tsx`: una fila por elemento, las seis columnas y ninguna más, el enlace apunta a `/properties/{id}`, los controles de paginación se deshabilitan en primera y última página, cambiar filtro resetea a página 1, y los cinco estados (carga, prohibido, validación, vacío, error) se renderizan. Incluir un caso que fije que **ningún** campo fuera de las seis columnas aparece en el DOM. [R1, R2, R3]
- [ ] 4.5 Crear `frontend/features/properties/index.ts` exportando **sólo** `PropertiesView`. [R1]

## 5. i18n

- [ ] 5.1 Crear `frontend/locales/es/properties.json` y `frontend/locales/en/properties.json`: cabeceras de las seis columnas, etiquetas de los dos filtros y su opción «todos», controles de paginación, las **dos** etiquetas de `status`, el texto accesible del enlace de fila y las copias de prohibido/validación/vacío/error. **Sin** las once etiquetas de estado operativo: se leen del namespace `dashboard`. [R6]
- [ ] 5.2 Registrar el namespace `properties` en `frontend/lib/i18n/resources.ts` en sus **tres** puntos: el `import`, el array de namespaces y las tablas `es` y `en`. Registrarlo es lo que mete el namespace en la red de `catalog-parity.test.ts`; sin esto la paridad ES/EN no se comprueba. [R6]
- [ ] 5.3 Crear `frontend/features/properties/locales/properties-locale.test.ts` calcado de `features/reservations/locales/reservations-locale.test.ts`: **los once** valores de `PropertyOperationalState` y **los dos** de `PropertyStatus` resuelven a una cadena no vacía en ES y en EN. `catalog-parity.test.ts` no cubre esto: compara conjuntos de claves entre idiomas, no cobertura por valor del enum. [R6]
- [ ] 5.4 Verificar que no queda ninguna cadena visible escrita en el código de la feature. [R6]

## 6. Conectar la ruta

- [ ] 6.1 Cambiar `frontend/app/(workspace)/properties/page.tsx` para renderizar `PropertiesView` en vez de `RoutePlaceholder`, dejando `generateMetadata` con `routeMetadata("properties")` como está. No tocar `route-registry.ts` ni `locales/*/navigation.json`: las dos rutas y sus cuatro claves ya existen. [R1]
- [ ] 6.2 Confirmar que ningún componente de la feature usa `dangerouslySetInnerHTML`, de modo que `name`, `internal_code` y la ciudad se rendericen como texto por la interpolación de JSX (D13). [R5]
- [ ] 6.3 Revisar que la feature **no** llama en ningún camino a `GET /api/v1/properties/{id}` ni a `GET /api/v1/properties/{id}/state`. [R5]

## 7. Verification

- [ ] 7.1 Preparar el contenedor para la suite: `make up`, y luego el copiado de nueve ficheros de `sdd/project.md` (§ Worktree bootstrap) para que los dos tests que leen por encima de `/app` no den `ENOENT` ajeno al change.
- [ ] 7.2 Suite completa del frontend en verde: `docker compose exec -T frontend npm test`. Anotar el número de ficheros y de tests, y compararlo con el estado previo al change — «PASS (0) FAIL (0)» es una colección fallida, no un verde.
- [ ] 7.3 Typecheck sin errores: `docker compose exec -T frontend npm run typecheck`.
- [ ] 7.4 Lint sin errores: `docker compose exec -T frontend npm run lint`.
- [ ] 7.5 Comprobación manual del flujo: entrar en `/properties`, ver el listado con datos sembrados, filtrar por situación y por estado operativo, paginar, y entrar en el detalle desde una fila. Verificar que ninguna nota de texto libre ni indicio de contraseña de WiFi aparece en la pantalla ni en las respuestas de red. [R5]

---

**Cobertura de requisitos**: R1 → 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 3.4, 3.5, 4.3, 4.4, 4.5, 6.1 · R2 → 2.3, 2.4, 3.1, 3.5, 4.1, 4.2, 4.3, 4.4 · R3 → 3.2, 3.3, 3.4, 3.5, 4.3, 4.4 · R4 → 1.1, 1.2, 1.3, 1.4, 4.3 · R5 → 2.1, 6.2, 6.3, 7.5 · R6 → 5.1, 5.2, 5.3, 5.4. Los seis quedan cubiertos.
