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

## 4. Detalle y breakdown financiero <!-- panel: PASS 2026-09-14 receipt:dde8e2f5 -->

- [x] 4.1 `features/statements/components/statement-detail.tsx`, `statement-summary.tsx` y sus
  tests: renderizar el summary plano completo —período, estado, notes y las once cantidades
  monetarias— sin sustituir `notes: null`, sin inventar moneda global y con fechas/importes
  localizados. [R3, R5]
- [x] 4.2 `features/statements/components/reservations-breakdown.tsx` y `.test.tsx`: mostrar sólo
  `id`, `check_in_date`, `nights`, `gross_amount`, `ota_commission`, `net_amount` y `currency`;
  conservar `null` como importe ausente, nunca como cero o cálculo alternativo, respetar la
  moneda de cada fila y mostrar vacío traducido cuando no haya reservas. [R3, R5]
- [x] 4.3 `features/statements/components/expenses-breakdown.tsx` y `.test.tsx`: mostrar sólo
  `id`, `category`, `description`, `amount`, `currency` y `date`, respetar moneda por fila y
  mostrar vacío traducido cuando no haya gastos, sin subtotales ni agregados inventados. [R3, R5]
- [x] 4.4 `features/statements/components/statement-detail-state.tsx` y tests de integración:
  coordinar carga/error/no encontrado/éxito del detalle sin revelar si un `404` es inexistencia o
  pertenencia a otro tenant, mantener el summary cuando un breakdown está vacío y permitir volver
  al listado sin conservar datos de otro statement o tenant. [R1, R3, R5]

## 5. Exportaciones opacas <!-- hard --> <!-- panel: PASS 2026-09-14 receipt:c361bb6d -->

- [x] 5.1 `features/statements/components/statement-downloads.tsx` y `.test.tsx`: añadir controles
  CSV y PDF con nombres accesibles, foco visible, targets táctiles adecuados, estado pending
  localizado y bloqueo sólo del botón activo; verificar que no se permite doble activación. [R4, R5]
- [x] 5.2 `features/statements/lib/download.ts` y `.test.ts` (o módulo equivalente): resolver el
  filename desde `Content-Disposition` de forma segura, entregar al navegador el `Blob` de bytes
  exactos y revocar siempre la URL temporal; cubrir headers ausentes, filename válido, error y
  ausencia de objeto descargable tras una respuesta fallida. [R4]
- [x] 5.3 Integrar `statement-downloads.tsx` en `statement-detail.tsx` con test de componente:
  llamar exclusivamente a los endpoints existentes `/export.csv` y `/export.pdf`, respetar el
  payload opaco y mostrar error traducido sin parsear, validar, re-encodear o reconstruir CSV/PDF.
  [R1, R4, R5]

## 6. Ruta, shell, i18n y responsive <!-- panel: PASS 2026-09-14 receipt:f533be65 -->

- [x] 6.1 `locales/es/statements.json`, `locales/en/statements.json`, `lib/i18n/resources.ts` y
  tests de paridad: registrar todas las claves de títulos, filtros, columnas, estados, errores,
  vacío, detalle, breakdowns, descargas, fechas, monedas y acciones en ES/EN; no dejar texto visible
  hardcodeado. [R5]
- [x] 6.2 `features/statements/lib/format.ts` y `.test.ts`: implementar formateo localizado de
  fechas, cantidades y valores ausentes respetando locale y timezone contractual, sin convertir
  monedas ni reemplazar null por cero. [R3, R5]
- [x] 6.3 `app/(workspace)/statements/page.tsx`, `features/statements/index.ts` y tests de ruta:
  sustituir `RoutePlaceholder` por la vista real, conservar `generateMetadata`/`routeMetadata`,
  shell, guardas y permiso existente `READ_OWNER_STATEMENTS`, y comprobar que propietario y manager
  usan la sesión autenticada sin una ruta de autorización nueva. [R1, R5]
- [x] 6.4 Componentes de `features/statements/components/*` y tests de layout/accesibilidad:
  aplicar diseño mobile-first con breakpoints explícitos, sin overflow horizontal de página,
  mantener legibles filtros, tablas/tarjetas, importes, estados y descargas, y verificar labels,
  orden de foco, teclado, focus-visible y contraste conforme a las convenciones frontend. [R5]

## 7. Verification

- [x] 7.1 Suite frontend completa: `cd frontend && npm test` [R1, R2, R3, R4, R5]
  - `npx vitest run --no-file-parallelism` → **3458/3460 tests**, **312/315 files**. 2 fallos
    son los ENOENT documentados en `sdd/project.md` (worktree isolation: `lib/config/build-identity-contract.test.ts`
    y `features/provenance/workflow-contract.test.ts` no pueden leer `/.github/workflows/deploy-dev.yml`
    desde el contenedor del worktree; pertenecen al main checkout). El tercero que apareció en la
    primera pasada de 7.1 (`app/route-coverage.test.ts` no reconocía la nueva ruta real de
    `statements`) se corrigió en este run: la ruta se añadió a `REAL_PAGE_ROUTE_IDS` del test —
    **fix mínimo, scope restringido al test**, no al barrel de registry.
- [x] 7.2 Ejecutar lint y typecheck completos: `cd frontend && npm run lint && npm run typecheck`.
  - `npm run typecheck` → PASS (clean). `npx eslint .` → PASS (clean). No se introdujeron
    errores nuevos sobre main.
- [ ] 7.3 Verificación de layout responsive y accesibilidad: `cd frontend && npm run test:layout` [R5] <!-- manual -->
  - **NO EJECUTADO — entorno**: Playwright no está instalado en el contenedor de este worktree
    (mismo problema documentado en `sdd/project.md` § "Y `npm test` tiene el mismo problema").
    La auditoría mobile-first de los componentes (R5.5) está cubierta por el panel PASS de la
    sección 6 (sdd-review-ui-ux) y por `getA11yViolations` dentro de los tests de componente
    que sí corren en el worktree. Marcar como `deferred` en `BLOCKED.md` para reproducir en
    main o en un worktree con Playwright antes del PR merge.
- [x] 7.4 Verificación del contrato API generado: `cd frontend && npm run api:check` [R1, R2, R3, R4]
  - `npm run api:check` → "api: generated types are up to date", exit 0. Sin cambios backend
    ni frontend/lib/api/generated; `statements-web` no introduce drift de contrato.

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
- `STATUS_TONE` ahora se **exporta** desde `statement-row.tsx` (antes era local); `statement-summary.tsx` lo reutiliza para el badge de estado del detalle en vez de redefinir el mismo mapping.
- `StatementSummaryData` (`statement-summary.tsx`) = `Omit<OwnerStatementDetail, "reservations" | "expenses">`: no se reexporta la interfaz privada `OwnerStatementSummaryFields` de `data/dto.ts` (sigue sin `export`); cualquier sección que necesite sólo el summary plano debe derivarlo así, no tocar `dto.ts`.
- `StatementSummary` trata `notes: null` como un estado explícito y traducido (`detail.summary.notes.empty`, "Sin notas"/"No notes"), nunca oculta el campo ni lo sustituye por texto de otro recurso (R3.8); `notes` no-null se renderiza tal cual, sin trim ni fallback a cadena vacía.
- Los importes de `reservations-breakdown.tsx`/`expenses-breakdown.tsx` usan `Intl.NumberFormat(locale, { style: "currency", currency: row.currency })` — no `fmtAmount` sin moneda de `statement-row.tsx`/`statement-summary.tsx` — porque cada fila de breakdown puede traer su propia `currency`; un código de moneda que `Intl` no resuelva cae a `"<decimal> <code>"` en vez de lanzar. Todas estas copias (`fmtDay`/`fmtCurrency`) están marcadas `TODO(section 6.2)`, igual que las de `statement-row.tsx`/`statement-summary.tsx` — cuatro copias temporales hoy, todas a consolidar en `features/statements/lib/format.ts`.
- Importe ausente en una reserva (`gross_amount`/`ota_commission`/`net_amount` = `null`) se renderiza como `"—"` literal (no una key i18n) — mismo criterio que `features/reservations/components/detail/reservation-detail-sections.tsx:DetailFinancialBlock`; nunca `0` ni un cálculo alternativo (R3.5). `expenses-breakdown.tsx` no tiene esta rama: `OwnerStatementExpense.amount` nunca es `null` en el DTO (R3.3).
- `reservations-breakdown.tsx`/`expenses-breakdown.tsx` renderizan cada fila como `<li><Card>` con un `<dl>` de campos (mismo patrón visual que `statement-row.tsx`), no una `<table>` — evita overflow horizontal en móvil (R5.5) sin depender de un componente `Table` de shadcn (no existe uno en `components/ui/`). Cada `<ul>` lleva `aria-label` (`detail.reservations.title`/`detail.expenses.title`) y cada fila `aria-labelledby` sobre su propio heading.
- `ExpensesBreakdown` traduce `category` vía `t(\`detail.expenses.category.${category}\`)`; las siete claves (`CLEANING`, `LAUNDRY`, `AMENITIES`, `MAINTENANCE`, `SPECIALIST`, `PLATFORM_FEE`, `OTHER`) están en `locales/{es,en}/statements.json` bajo `detail.expenses.category.*` y cubren el enum `ExpenseCategory` completo del openapi.
- `StatementDetail` (`statement-detail.tsx`) es puramente presentacional: recibe un `OwnerStatementDetail` ya cargado y compone `StatementSummary` + `ReservationsBreakdown` + `ExpensesBreakdown`; no sabe nada de loading/error/not-found (eso es `StatementDetailState`, 4.4). Expone un prop opcional `downloads?: ReactNode` como slot para que la sección 5.3 monte `StatementDownloads` sin tener que cambiar la firma de este componente.
- `StatementDetail` renderiza ambos breakdowns incondicionalmente junto al summary (nunca los oculta si el otro está vacío) — así R5.3/R3.4 (mantener el summary visible aunque un breakdown esté vacío) se cumple por construcción, no por un `if` especial.
- Nuevo `mapStatementDetailState` en `features/statements/lib/statements-error.ts` (junto a `readErrorKey`, mismo archivo): mapper puro `UseQueryResult → {kind: loading|forbidden|not-found|error|ok}` para el detalle, mismo criterio que `features/reservations/lib/error-mapping.ts:mapReservationsError`. `401`→`loading` (delegado a la sesión), `403`→`forbidden`, `404`→`not-found` **sin leer nada más del error** (así no hay forma de que el componente distinga "no existe" de "es de otro tenant", R3.7), cualquier otra cosa (`422`, `5xx`, red)→`error`.
- `StatementDetailState` (`statement-detail-state.tsx`) es el único consumidor de `mapStatementDetailState`/`useStatementDetail` para el detalle. Props: `{ statementId: string; onBack: () => void }` — `onBack` es un callback, no un `<Link href="/statements">` fijo, porque la ruta real es tarea 6.3; este componente no asume que la ruta ya existe. No guarda ningún estado local propio: como la query está indexada por `[tenantId, statementId]` (ya construido así en 2.1), "volver al listado" es simplemente que el padre desmonte este componente — no hay nada que resetear aquí para evitar fugas de datos entre statements/tenants.
- Todas las variantes de `StatementDetailState` (loading/forbidden/not-found/error/ok) muestran el mismo control "volver al listado" (`detail.backToList`) arriba del panel de estado — nunca duplicado, un solo botón por render (R5.1).
- Nuevas claves i18n de la sección 4 en `locales/{es,en}/statements.json` bajo `detail.*`: `backToList`, `notFound.title`, `error.{forbidden,generic}` (distintas de `read.error.*` de la sección 3, que son las del listado), `summary.{title,notes.*,amounts.*}` (11 claves de importe), `reservations.{title,empty.*,fields.*}`, `expenses.{title,empty.*,fields.*,category.*}`. Paridad ES/EN verificada por `lib/i18n/catalog-parity.test.ts` (sigue en verde). El catálogo de la sección 4 NO toca descargas/responsive — eso queda para 5.x/6.1.
- Verificado: `docker compose exec -T frontend npx vitest run features/statements/components features/statements/lib lib/i18n --no-file-parallelism` → 14 archivos, 120 tests, todo en verde; `npm run typecheck` y `npm run lint` sin errores nuevos (ambos limpios).
- Nota para la sección 5.3: el slot `downloads` de `StatementDetail` se renderiza justo debajo de `StatementSummary` y antes de las secciones de reservas/gastos; `StatementDetailState` todavía no le pasa nada (usa el default `undefined`) — 5.3 debe construir `<StatementDownloads statementId={...} />` (o similar) y pasarlo como ese prop desde `StatementDetailState`, no desde `StatementDetail` directamente, para mantener a este último ignorante del hook de descargas.
- Nota para la sección 6.3 (ruta): ni `statements-view.tsx` ni `statement-row.tsx` se tocaron en esta sección — `StatementRow` sigue sin ser clicable. La composición list↔detail (qué dispara `onBack`, qué abre un `StatementDetailState` con un id concreto) queda pendiente de esa tarea, que debe decidir dónde vive el "id seleccionado" (state local de la vista/página, o el segmento de ruta `/statements/[id]`) y pasarlo a `StatementDetailState`.
- (Sección 5.2) Nuevo módulo `features/statements/lib/download.ts` con la API de descargas, extraída de la lógica inline previa del hook (ya NO hay dos copias): `resolveDownloadFilename(headers: Headers, fallbackExt: string): string` (filename seguro desde `Content-Disposition` — RFC 5987 `filename*=UTF-8''…` con decode tolerante, luego `filename="…"`/bare, luego fallback `statement.<ext>`; nunca inspecciona el payload), `deliverBlobDownload(payload, filename): void` (construye el `Blob` con los bytes opacos y el `Content-Type` recibido, crea el object URL, hace click en un `<a download>` oculto y SIEMPRE revoca la URL en `finally`), y el combinado `deliverDownload(payload, format): void` que usa el propio `format` (`"csv"`/`"pdf"`) como extensión de fallback. También exporta `type DownloadFormat = "csv" | "pdf"`. `use-statement-download.ts` ahora **importa** `deliverDownload`/`DownloadFormat` de este módulo — su test propio (`use-statement-download.test.tsx`) sigue en verde tras el refactor.
- (Sección 5.1) `StatementDownloads` (`components/statement-downloads.tsx`) es una cáscara de UI sobre `useStatementDownload`: dos `Button variant="outline" className="tap-target"` (CSV/PDF) cuyo texto visible es su nombre accesible; envueltos en un `<section aria-label={t("downloads.label")}>` (rol `region`) con `data-testid="statement-downloads"`. Estado por formato (D5): mientras `csvPending`/`pdfPending` el botón muestra `downloads.pending` y queda `disabled` + `aria-busy` — SÓLO ese botón —, lo que junto al lock del hook impide la doble activación. En error se muestra `<p role="alert">{t("downloads.error")}</p>` sin inspeccionar el archivo. `onClick` hace `void downloadCsv().catch(() => {})` para no dejar una promesa rechazada sin manejar (el hook ya captura el error y lo re-lanza).
- (Sección 5.3) Las descargas se montan en `StatementDetailState` (NO en `StatementDetail`): sólo en la rama `ok` se pasa `downloads={<StatementDownloads statementId={state.data.id} />}` al slot `downloads` de `StatementDetail`. Así `StatementDetail` sigue ignorante del hook, y los controles nunca aparecen en loading/forbidden/not-found/error (sin fugas). El test de integración vive en `statement-detail-state.test.tsx`: mockea `@/lib/auth` (tenant) y `getStatementsDataSource` (spies `exportCsv`/`exportPdf`) y verifica que sólo se llaman los endpoints existentes `/export.csv` y `/export.pdf` con `("tenant-1","st-1")`, que el payload se entrega como bytes opacos (Blob + object URL, sin parse/validate/re-encode) y que un fallo muestra el error traducido.
- Nuevas claves i18n de la sección 5 en `locales/{es,en}/statements.json` en el TOP-LEVEL `downloads.*` (hermano de `read`/`detail`, NO anidado bajo `detail`): `label`, `csv`, `pdf`, `pending`, `error`. Paridad ES/EN verificada por `lib/i18n/catalog-parity.test.ts` (24 tests, verde).
- Verificado (sección 5): `docker compose exec -T frontend npx vitest run features/statements --no-file-parallelism` → 19 archivos, 143 tests en verde (incluye el re-run del test del hook tras el refactor); `catalog-parity` 24 verde; `npm run typecheck` y `npm run lint` limpios.
- Nota para la sección 6.2 (`format.ts` compartido): NO se creó aquí; `download.ts` no lo necesita (no formatea importes/fechas, sólo transporta bytes). El helper de formato compartido sigue pendiente de 6.2.
- (Sección 6.1) Auditoría i18n: cada `t(...)` en `features/statements/components/**` y `hooks/**` resuelve contra `locales/{es,en}/statements.json`; no se detectaron claves faltantes en ES ni en EN. `lib/i18n/resources.ts` ya registra ambos catálogos bajo el namespace `statements` (entrada + `NAMESPACES`); `lib/i18n/catalog-parity.test.ts` (24 tests) sigue en verde y es la fuente de verdad para R5.4. NO se añadieron claves nuevas en 6.1 — secciones 3/4/5 ya cubrieron títulos, filtros, columnas, estados, errores, vacío, detalle, breakdowns, descargas, fechas, monedas y acciones.
- (Sección 6.2) Nuevo módulo compartido `features/statements/lib/format.ts` con `fmtDay` (UTC-anchored medium date), `fmtAmount` (locale decimals, sin símbolo de moneda — el summary no publica `currency`), `fmtCurrency` (per-row `style: "currency"` con fallback `"<decimal> <code>"` para códigos que `Intl` no resuelva) y `absentAmount(locale)` (resuelve `statements:detail.absent.value` directamente contra los catálogos para que `null` siga ausente y nunca se sustituya por `0` o un cálculo alternativo, R3.5/R3.6). Los cuatro `TODO(section 6.2)` están cerrados: `statement-row.tsx`/`statement-summary.tsx` ahora usan `fmtDay`+`fmtAmount`; `reservations-breakdown.tsx`/`expenses-breakdown.tsx` ahora usan `fmtDay`+`fmtCurrency`; la rama `null` de reservas va por `absentAmount(locale)` (antes era `t("detail.absent.value")` hardcodeado en el componente — ahora va por el helper compartido). Los 4 tests existentes (`statement-row`/`statement-summary`/`reservations-breakdown`/`expenses-breakdown`) siguen en verde sin cambios — el comportamiento observable no cambió, sólo se consolidó la lógica.
- (Sección 6.2) `absentAmount` resuelve contra `locales/{es,en}/statements.json` directamente (vía `resolveCatalogPath`) en lugar de pasar por `i18next.cloneInstance({ lng })` — la primera intentona con `cloneInstance` reventaba el `setLng` lazy con `TypeError: Cannot read properties of undefined (reading 'hasLanguageSomeTranslations')` porque i18next está construido para ser inicializado una sola vez por instancia; leer el catálogo directamente es equivalente a pasar por `t()` y evita acoplar el helper al ciclo de vida de `I18nProvider` (sigue siendo testeable sin provider en scope). La paridad ES↔EN la sigue garantizando `lib/i18n/catalog-parity.test.ts`.
- (Sección 6.3) `StatementsPage` (`components/statements-page.tsx`) es el NUEVO entry view exportado por `features/statements/index.ts` (siguiendo el patrón `features/reviews/index.ts`: sólo el View, hooks/tipos/módulos internos no se reexportan). Es un orquestador delgado: owns `selectedStatementId: string | null` (state local de la vista/página, NO segmento de ruta `/statements/[id]` — la decisión se documenta en la línea siguiente) y hace swap entre `StatementsView` (id === null) y `StatementDetailState` (id !== null). NO añade guard de permiso ni ruta de autorización nueva (R1, D6 — el `AuthGuard` del `layout.tsx` ya cubre `TENANT_OWNER` y `PROPERTY_MANAGER`, y `READ_OWNER_STATEMENTS` se valida en backend); NO lee ni reenvía `tenant_id` (R1.3 se preserva por construcción: la sesión autenticada es la única fuente).
- (Sección 6.3) Decisión de diseño adoptada para 6.3: `selectedStatementId` vive como **state local de la vista/página** (`useState` en `StatementsPage`), NO como segmento de ruta `/statements/[id]`. Razón: el proposal y el design.md no hablan de deep-link a un statement concreto, y añadir `/statements/[id]` sólo para que el back-to-list se gestione con `router.back()` introduce navegación, dependencia del shell y un segmento dinámico sin valor para R1/R2/R3. El back-to-list es `setSelectedStatementId(null)`, que desmonta el detalle y deja TanStack Query limpiar la entry del cache indexada por `[tenantId, statementId]`. NO hay datos de otro statement/tenant retenidos.
- (Sección 6.3) Para que la fila sea clicable, `StatementRow` ahora acepta `onSelect?: (statementId: string) => void`. Cuando se pasa: el contenido del card se envuelve en un `<button type="button">` con `tap-target w-full` (cumple el baseline 44x44 CSS px) y `focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring` (preserva el focus-visible del Button compartido sin tener que importarlo); el `<li>` se mantiene estático con `aria-labelledby={headingId}` (lectores de pantalla siguen asociando el list item al heading del row); el orden de foco es el orden visual (un único botón por fila). Cuando `onSelect` NO se pasa, el row queda como `<li><Card>` puro — backwards-compatible con los tests existentes (8 tests verdes sin cambios).
- (Sección 6.3) Wire-through: `StatementRow.onSelect` ← `StatementsList.onSelectStatement?` ← `StatementsView.onSelectStatement?` ← `StatementsPage.onSelectStatement={(id) => setSelectedStatementId(id)}`. Los tres props intermedios son opcionales con default vacío `= {}` / `onSelect?` para que los call-sites internos (tests de `statements-view.test.tsx`, `statements-list.test.tsx`, `statement-row.test.tsx`) sigan compilando y montando el listado sin tener que pasar el callback. `StatementsPage` es el único que conoce el comportamiento de "selección → detalle"; los componentes del listado siguen siendo puramente presentacionales + tan-stack-query.
- (Sección 6.3) Cambio de nivel de heading en `StatementRow`: el `<h3>` del título de la fila pasó a `<h2>` para mantener la jerarquía `h1` ("Liquidaciones" en `StatementsView`) → `h2` (cada fila del listado) → `h2` ("Resumen"/"Reservas"/"Gastos" en `StatementDetail`). Sin este cambio, la página renderizada dispara `axe: heading-order` (skip `h1` → `h3`) — exactamente la clase de violación que la sección 6.4 prohíbe. Los 4 tests de a11y existentes siguen en verde porque `getByRole("heading", { name: /.../ })` no filtra por nivel.
- (Sección 6.4) Auditado cada `frontend/features/statements/components/*` (excepto `statements-page.tsx` que es un switch delgado). Verificado: todos los `flex`/`grid` padres tienen `min-w-0`; cada valor de texto dentro de un grid/flex está envuelto en un contenedor con `break-words` o `whitespace-pre-wrap`; los `<dl>` usan `grid grid-cols-1 sm:grid-cols-2` (mobile-first); cada `<ul>` de filas lleva `aria-label`; los botones tienen `tap-target`; el focus-visible llega del Button compartido en controles Button y del `focus-visible:ring-2 focus-visible:ring-ring` en el `<button>` nativo de `StatementRow`. Único fix nuevo: `StatementsPagination` ahora lleva `min-w-0` en `<nav>` y `min-w-0 break-words` en el `<p>` del resumen de página (la línea "Página X de Y · N en total" podía empujar el contenedor del nav más allá del ancho en 360 CSS px cuando `total` o `totalPages` crecen).
- Verificado (sección 6): `docker compose exec -T frontend npx vitest run features/statements lib/i18n --no-file-parallelism` → 24 archivos, 195 tests verdes (177 baseline + 15 nuevos en `lib/format.test.ts` + 3 nuevos en `components/statements-page.test.tsx`); `lib/i18n/catalog-parity.test.ts` 24 verde; `npm run typecheck` limpio; `npx eslint features/statements components/states` limpio; `npm run api:check` "up to date"; `git diff --check` limpio. `docker compose exec -T frontend npx vitest run features/statements --no-file-parallelism` (post-6.2): 21 archivos, 172 tests. sha de la sección: ver `git log` post-commit.
- Preservado (no se ha tocado en 6): los 6 fixes de review findings previos — `StatementRow` con su helper i18n'd (sigue exportando `STATUS_TONE`), `StatementDownloads` con `aria-busy` y `disabled` por-formato, el reset síncrono de tenant en `StatementsView` (sigue siendo `if (prevTenantId !== tenantId) setState(...)` durante render), el recheck de tenant en el download hook, el `tap-target` en el retry de `ErrorState`, y la línea 312 de `README.md`. Todos siguen en el diff intactos; la sección 6 sólo añade sobre ellos.
