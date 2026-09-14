# Tasks: statements-web

Todas las rutas son relativas a `frontend/`. El contrato backend y sus permisos ya existen; este
change no modifica `backend/`, endpoints, migraciones ni `frontend/lib/api/generated/openapi.d.ts`.
Cada sección deja sus módulos compilables y añade tests junto con el comportamiento que introduce.

## 1. Transporte binario y costura de datos

- [x] 1.1 `lib/api/client.ts`, `lib/api/index.ts` y `lib/api/client.test.ts`: extender `ApiClient`
  con una operación tipada para respuestas no JSON que conserve bytes y headers de respuesta,
  mantenga `getHeaders`, `credentials` y la recuperación única de `401`, y use los mismos errores
  normalizados para respuestas no exitosas; cubrir bytes exactos, `Content-Type`,
  `Content-Disposition`, headers adicionales, `401` recuperable y error de descarga. [R1, R4]
- [x] 1.2 `features/statements/data/dto.ts`, `data/statements-source.ts` y
  `data/http/http-statements-source.ts` (nuevos) con sus tests: definir DTOs camelCase separados
  para `OwnerStatementResponse` y `OwnerStatementDetailResponse`, incluyendo summary plano,
  `reservations[]` y `expenses[]`, preservar importes nullable y `notes: null`, y mapear sólo los
  campos contractuales sin calcular subtotales, moneda global ni agregados. [R2, R3]
- [x] 1.3 `features/statements/data/http/http-statements-source.ts` y sus tests: implementar
  listado con `property_id`, `period_start_from`, `period_start_to` y `status`, respetando
  `items`, `total`, `page` y `per_page`; implementar detalle por `statement_id`; implementar CSV y
  PDF como payloads opacos mediante el transporte binario, conservando bytes, `Content-Type`,
  `Content-Disposition`/filename y demás headers sin parsear ni reconstruir archivos. [R1, R2, R3, R4]
- [x] 1.4 `features/statements/data/index.ts` y tests de composición: crear la fuente autenticada
  con `createAuthenticatedClients`, sin aceptar `tenant_id` en filtros ni construirlo desde la UI,
  y reutilizar `features/properties` como única fuente de propiedades para labels y opciones. [R1, R2]

## 2. Estado remoto, claves y directorio de propiedades

- [x] 2.1 `features/statements/hooks/query-keys.ts` y `.test.ts`: definir claves TanStack Query
  acotadas por tenant para listado, detalle y propiedades, normalizar filtros en orden estable y
  canonizar página; demostrar que cambios de tenant no comparten caché ni datos. [R1, R2]
- [x] 2.2 `features/statements/hooks/use-statements-data.ts` y `.test.tsx`: implementar queries
  para listado y detalle con el `retryPolicy` del árbol, y consumir explícitamente
  `useActiveProperties()` junto con su query/caché existente para resolver el directorio completo
  de propiedades activas; no crear una segunda query ni duplicar la fuente de propiedades en
  statements. El detalle sólo se activa con un id seleccionado y el fallo del directorio no
  convierte el listado/detalle en error financiero. [R1, R2, R3, R5]
- [x] 2.3 `features/statements/hooks/use-statement-download.ts` y `.test.tsx`: implementar estado
  independiente para CSV y PDF, deshabilitar sólo el control cuya descarga está pendiente, crear
  `Blob`/URL temporal únicamente tras una respuesta completa y exitosa, usar el filename de la
  respuesta, revocar y limpiar el recurso en éxito o error, y evitar descargas parciales o dobles.
  [R4, R5]

## 3. Listado, filtros y paginación <!-- panel: PASS 2026-09-14 receipt:de8192f8 -->

- [x] 3.1 `features/statements/components/statements-view.tsx` (y un hook/estado auxiliar local
  estrictamente acotado a esta vista, si hace falta) y sus tests: implementar filtros y página como
  estado ligero local de la vista, reiniciarlo al cambiar de tenant y no introducir un store global
  o persistente por conveniencia. Si se reutiliza un patrón scoped existente, mantenerlo limitado a
  esta vista y sin almacenar server state; TanStack Query sigue siendo la única fuente de
  statements y propiedades remotas. Cubrir propiedad, rango de período, estado y navegación de
  página sin inventar `total_pages`. [R1, R2, R5]
- [x] 3.2 `features/statements/components/statements-filters.tsx` y `.test.tsx`: construir filtros
  accesibles para propiedad, período y estado con labels programáticos, opciones del directorio
  completo de propiedades y actualización de página al cambiar filtros; enviar sólo los
  parámetros contractuales, sin `tenant_id`. [R1, R2, R5]
- [x] 3.3 `features/statements/components/statement-row.tsx`, `statements-pagination.tsx` y sus
  tests: mostrar propiedad resuelta, período, estado y resultado neto del resumen; tratar
  `total=0` como listado vacío; respetar `items`, `total`, `page`, `per_page`; probar teclado,
  foco visible, nombres accesibles y navegación sin overflow en viewport móvil. [R2, R5]
- [x] 3.4 `features/statements/components/statements-list.tsx`, `statements-view.tsx` y tests:
  ensamblar queries, filtros, filas y paginación con estados explícitos de loading, error, vacío y
  éxito; distinguir 401/403 del vacío y no renderizar información financiera cuando la sesión no
  está autorizada. [R1, R2, R5]

## 4. Detalle y breakdown financiero

- [ ] 4.1 `features/statements/components/statement-detail.tsx`, `statement-summary.tsx` y sus
  tests: renderizar el summary plano completo —período, estado, notes y las once cantidades
  monetarias— sin sustituir `notes: null`, sin inventar moneda global y con fechas/importes
  localizados. [R3, R5]
- [ ] 4.2 `features/statements/components/reservations-breakdown.tsx` y `.test.tsx`: mostrar sólo
  `id`, `check_in_date`, `nights`, `gross_amount`, `ota_commission`, `net_amount` y `currency`;
  conservar `null` como importe ausente, nunca como cero o cálculo alternativo, respetar la
  moneda de cada fila y mostrar vacío traducido cuando no haya reservas. [R3, R5]
- [ ] 4.3 `features/statements/components/expenses-breakdown.tsx` y `.test.tsx`: mostrar sólo
  `id`, `category`, `description`, `amount`, `currency` y `date`, respetar moneda por fila y
  mostrar vacío traducido cuando no haya gastos, sin subtotales ni agregados inventados. [R3, R5]
- [ ] 4.4 `features/statements/components/statement-detail-state.tsx` y tests de integración:
  coordinar carga/error/no encontrado/éxito del detalle sin revelar si un `404` es inexistencia o
  pertenencia a otro tenant, mantener el summary cuando un breakdown está vacío y permitir volver
  al listado sin conservar datos de otro statement o tenant. [R1, R3, R5]

## 5. Exportaciones opacas <!-- hard -->

- [ ] 5.1 `features/statements/components/statement-downloads.tsx` y `.test.tsx`: añadir controles
  CSV y PDF con nombres accesibles, foco visible, targets táctiles adecuados, estado pending
  localizado y bloqueo sólo del botón activo; verificar que no se permite doble activación. [R4, R5]
- [ ] 5.2 `features/statements/lib/download.ts` y `.test.ts` (o módulo equivalente): resolver el
  filename desde `Content-Disposition` de forma segura, entregar al navegador el `Blob` de bytes
  exactos y revocar siempre la URL temporal; cubrir headers ausentes, filename válido, error y
  ausencia de objeto descargable tras una respuesta fallida. [R4]
- [ ] 5.3 Integrar `statement-downloads.tsx` en `statement-detail.tsx` con test de componente:
  llamar exclusivamente a los endpoints existentes `/export.csv` y `/export.pdf`, respetar el
  payload opaco y mostrar error traducido sin parsear, validar, re-encodear o reconstruir CSV/PDF.
  [R1, R4, R5]

## 6. Ruta, shell, i18n y responsive

- [ ] 6.1 `locales/es/statements.json`, `locales/en/statements.json`, `lib/i18n/resources.ts` y
  tests de paridad: registrar todas las claves de títulos, filtros, columnas, estados, errores,
  vacío, detalle, breakdowns, descargas, fechas, monedas y acciones en ES/EN; no dejar texto visible
  hardcodeado. [R5]
- [ ] 6.2 `features/statements/lib/format.ts` y `.test.ts`: implementar formateo localizado de
  fechas, cantidades y valores ausentes respetando locale y timezone contractual, sin convertir
  monedas ni reemplazar null por cero. [R3, R5]
- [ ] 6.3 `app/(workspace)/statements/page.tsx`, `features/statements/index.ts` y tests de ruta:
  sustituir `RoutePlaceholder` por la vista real, conservar `generateMetadata`/`routeMetadata`,
  shell, guardas y permiso existente `READ_OWNER_STATEMENTS`, y comprobar que propietario y manager
  usan la sesión autenticada sin una ruta de autorización nueva. [R1, R5]
- [ ] 6.4 Componentes de `features/statements/components/*` y tests de layout/accesibilidad:
  aplicar diseño mobile-first con breakpoints explícitos, sin overflow horizontal de página,
  mantener legibles filtros, tablas/tarjetas, importes, estados y descargas, y verificar labels,
  orden de foco, teclado, focus-visible y contraste conforme a las convenciones frontend. [R5]

## 7. Verification

- [ ] 7.1 Suite frontend completa: `cd frontend && npm test` [R1, R2, R3, R4, R5]
- [ ] 7.2 Ejecutar lint y typecheck completos: `cd frontend && npm run lint && npm run typecheck`.
  Si el typecheck equivalente de la base/main actual ya contiene errores preexistentes, medir un
  baseline equivalente y exigir que `statements-web` no introduzca errores nuevos; no corregir
  deuda de tipado ajena al change. Si main está limpio, exigir PASS completo. [R1, R2, R3, R4, R5]
- [ ] 7.3 Verificación de layout responsive y accesibilidad: `cd frontend && npm run test:layout` [R5]
- [ ] 7.4 Verificación del contrato API generado: `cd frontend && npm run api:check` [R1, R2, R3, R4]

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

- `ApiClient.requestBinary()` devuelve `ApiBinaryResponse { bytes: Uint8Array, headers: Headers, status }` por la misma ruta de auth, credentials, recuperación única de 401 y `ApiError` que las peticiones JSON.
- `StatementsDataSource` expone `listStatements`, `getStatement`, `exportCsv` y `exportPdf`; la identidad de tenant es solo argumento de sesión/caché y nunca entra en URL, query ni body.
- `OwnerStatementsPage` conserva `items`, `total`, `page` y `perPage` sin inventar `totalPages`; la fuente HTTP envía `per_page=20` y únicamente los cuatro filtros contractuales.
- `features/statements/data` reexporta el `useActiveProperties` existente; la sección 2 debe consumirlo sin añadir otra petición o caché de propiedades propia de statements.
- Nota correctiva: la afirmación anterior queda superseded; `features/statements/data/index.ts` ya NO reexporta `useActiveProperties`. La sección 2 debe reutilizar la fuente existente de properties sin acoplar la capa data de statements al barrel/UI de properties.
- `statementsKeys` usa `['tenant', tenantId, resource, scope]`; los filtros se emiten en orden fijo y `page` ausente se canoniza a `1`.
- `useStatementsList` y `useStatementDetail` leen el tenant de `useAuth()` y usan `retryPolicy`; el detalle queda disabled sin `statementId`.
- `useStatementPropertyDirectory` consume directamente `@/features/properties`/`useActiveProperties()` y solo deriva un índice local de su resultado; los fallos del catálogo quedan aislados.
- `useStatementDownload` mantiene locks y errores independientes por formato, entrega bytes opacos con el filename/header del response y revoca la URL siempre tras el click.
- SUPERSEDED: la nota anterior que afirmaba que features/statements/data reexporta useActiveProperties ya no describe la implementación vigente. data/index.ts NO reexporta useActiveProperties. Las secciones posteriores deben reutilizar la fuente existente de properties sin acoplar la capa data de statements al barrel/UI de properties.
- `StatementsView` es la única dueña de `filters`/`page` (plain `useState`, sin store); resetea ambos con un `useRef` que guarda el `tenant_id` anterior y compara en un `useEffect` — ningún Zustand ni persistencia.
- `StatementsList` recibe `filters`/`page`/callbacks por props desde `StatementsView` y es quien llama a `useStatementsList`/`useStatementPropertyDirectory`; nunca guarda su propio estado de filtros.
- Cambiar cualquier filtro (`onPropertyIdChange`/`onPeriodStartFromChange`/`onPeriodStartToChange`/`onStatusChange`) pasa siempre por `StatementsView.updateFilters`, que también fija `page` a `1`; `onPageChange` (paginación) no toca los filtros.
- `StatementsPagination` (no `ReviewsPagination`/`PricingPagination` reutilizados) deriva `totalPages = ceil(total/perPage)` sólo para render/enable-disable — nunca lo persiste ni lo añade al DTO; sigue el mismo criterio de "sin inventar `total_pages`" que `data/dto.ts` ya documentaba. Se oculta sólo cuando `total === 0`; con una única página igualmente se muestra con ambos botones deshabilitados (paridad con reviews/pricing).
- `StatementRow`/`StatementsFilters` resuelven/listan propiedades exclusivamente desde `useStatementPropertyDirectory().index`/`.data.data` (el directorio completo), nunca desde `items` de la página actual; identidad de propiedad usa tres estados (resuelta/pendiente/no disponible), igual que `reviews`/`pricing`.
- `features/statements/lib/statements-error.ts` (`readErrorKey`) mapea sólo `403` a `statements:read.error.forbidden`; todo lo demás (incluye `401`, que el `ApiClient` ya resuelve globalmente) cae al genérico `statements:read.error.generic`. `StatementsList` renderiza `ErrorState` antes de comprobar `total === 0`, así que un `403`/error nunca se confunde con la lista vacía ni pinta datos financieros.
- Formateo de fecha/importe de `statement-row.tsx` es una copia local temporal (`fmtDay`/`fmtAmount`, marcadas `TODO(section 6.2)`) idéntica en criterio a `features/pricing/lib/format.ts`/`features/reviews/lib/format.ts` (UTC-anchored, dos decimales, sin símbolo de moneda porque el summary no publica `currency`). La sección 6.2 debe sustituirlas por `features/statements/lib/format.ts` sin duplicar la lógica.
- Namespace i18n `statements` registrado en `lib/i18n/resources.ts` con `locales/{es,en}/statements.json`; sólo cubre las claves que usa la sección 3 (title, list.*, columns.*, status.*, identity.*, filters.*, pagination.*, read.error.*). La sección 6.1 debe completar el catálogo (detalle, breakdowns, descargas) y re-verificar paridad — no se han añadido claves de esas áreas todavía.
- `StatementRow` no es clicable ni navega a detalle (eso es la sección 4): es un `<li>`/`<Card>` estático con `aria-labelledby` sobre el nombre de propiedad; la sección 4 puede envolverlo o añadir un trigger sin tener que rehacer su marcado interno.
- Tono de badge de estado (`STATUS_TONE` en `statement-row.tsx`): `DRAFT`→gray, `READY`→blue, `SENT`→green; decisión propia de esta sección, reutilizable por secciones posteriores si muestran el mismo enum.
