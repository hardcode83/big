# Tasks: reviews-web

Todas las rutas son relativas a `frontend/`. Ninguna tarea toca `backend/`: el contrato
está congelado y `lib/api/generated/openapi.d.ts` ya declara las siete operaciones de
reviews (design D19).

Cada tarea trae su test (regla de `steering/testing.md`). El orden mantiene el árbol
compilando y la suite verde después de cada sección: la sección 1 es una refactorización
sin cambio de comportamiento (permisos + namespace), las secciones 2-6 añaden módulos
aislados que nadie importa todavía, y `/reviews` sólo deja de ser placeholder en la
sección 8.

## 1. Permisos y catálogo i18n (prerrequisito, sin cambio de comportamiento)

- [ ] 1.1 `lib/auth/permissions.ts`: ampliar la unión `Permission` con
  `"MANAGE_REVIEW_DECISIONS"` y `"CREATE_REVIEW_UI"`, y conceder en
  `ROLE_UI_PERMISSIONS`: `MANAGE_REVIEW_DECISIONS` a `TENANT_OWNER`,
  `CREATE_REVIEW_UI` a `PROPERTY_MANAGER`. `SUPER_ADMIN`, `CLEANER` y `TECHNICIAN`
  siguen con `[]`. Mantener el comentario que dice que el mapa es parcial y sólo
  sirve para ocultar. `lib/auth/permissions.test.tsx` gana los casos simétricos a
  los de `MANAGE_PRICE_RECOMMENDATIONS`: `MANAGE_REVIEW_DECISIONS` concedida a
  `TENANT_OWNER` y denegada a los otros cuatro roles; `CREATE_REVIEW_UI` concedida a
  `PROPERTY_MANAGER` y denegada a los otros cuatro; ambas denegadas sin usuario. [R7.1, R7.2, R7.3]

- [ ] 1.2 `locales/es/reviews.json` y `locales/en/reviews.json` (nuevos): estructura
  completa de D17 — `tabs.*`, `detail.*`, `list.*`, `columns.*`,
  `status.{NEW,DRAFTED,APPROVED,POSTED_MANUALLY,IGNORED}`,
  `sentiment.{POSITIVE,NEUTRAL,NEGATIVE}`,
  `channel.{AIRBNB,BOOKING,GOOGLE,MANUAL,OTHER}`,
  `recurringIssue.{WIFI,NOISE,CLEANLINESS,ACCESS,COMMUNICATION,LOCATION,VALUE,AMENITIES,OTHER}`,
  `identity.*`, `filters.*`, `pagination.*`, `respond.*`,
  `respond.confirmQuestion.{APPROVE,IGNORE,MARK_POSTED,EDIT}`,
  `respond.error.*`, `create.*`, `create.error.*`, `preview.*`, `markPosted.*`. Las
  copias de error son las cuatro de D10 (`forbidden`, `notFound`, `conflict`,
  `invalid`, `generic`) por camino. La copia de `markPosted.dialog.body` no afirma
  que el sistema publicó — habla de la acción humana (R4.1). [R8.1, R8.5]

- [ ] 1.3 `lib/i18n/resources.ts`: registrar `reviews` en los **cuatro** puntos —
  el `import` por locale, la lista `NAMESPACES`, y la entrada dentro de `resources.es`
  y `resources.en`. Verificar que `catalog-parity.test.ts` (o el test que vigila el
  cuarto punto tras pricing-web) cubre el namespace nuevo. [R8.1]

## 2. Costura de datos de la feature

- [ ] 2.1 `features/reviews/data/dto.ts` (nuevo): `ReviewsPage<T>` (`items`, `total`,
  `page`, `perPage`, `totalPages`), `ReviewStatus` / `ReviewSentiment` /
  `ReviewChannel` / `RecurringIssueTag` desde `components["schemas"]`, `ReviewAction`
  como `Extract<…, "APPROVE" | "IGNORE" | "MARK_POSTED" | "EDIT">`, `Review` **sin**
  `classification_attempts`, `created_at`, `updated_at`, `reservation_id`,
  `approved_by`, `approved_at` (D3, ninguno se pinta), `ReviewDraft` **sin**
  `ai_generated`, `approved_at`, `approved_by`, `created_at`, `edits_count` (D3,
  tampoco se pintan — y `draftContent: string` no `string | null`, porque el
  DTO publicado `ReviewDraftResponse.draft_content` es `string` requerido),
  `ReviewFilters`, `PropertySummary`, `CreateReviewInput`, `RespondInput`
  (unión discriminada de D4). El nombre `ReviewsPage` es deliberadamente
  distinto de `PricingPage` y de `PaginatedResponse`. [R2.4, R2.5, R5.2, R6.3, R6.5]

- [ ] 2.2 `features/reviews/data/reviews-source.ts` (nuevo): interfaz
  `ReviewsDataSource` con `listReviews`, `getReview`, `getDraft`, `createReview`,
  `respondToReview`, `listProperties`. **No declarar** `listSummary` ni
  `regenerateDraft` (fuera de alcance, proposal «Out of scope»). [R5, R6]

- [ ] 2.3 `features/reviews/data/http/http-reviews-source.ts` (nuevo) + `.test.ts`:
  mapeo `{items,page,per_page,total}` → `ReviewsPage<T>` con `totalPages = perPage >
  0 ? Math.ceil(total / perPage) : 0`; filtros `property_id`, `channel`, `sentiment`,
  `status`, `rating_min`, `rating_max`, `date_from`, `date_to` enviados como query
  con esos nombres exactos; el mapeador **descarta** `classification_attempts`,
  `created_at`, `updated_at`, `reservation_id` y deja el resto. Tests: el campo se
  llama `items` y no `data`, `total = 0 → totalPages = 0`, `per_page = 0 → 0`, los
  nombres de query son los correctos, y los campos descartados no cruzan el
  boundary. [R2.1, R2.2, R2.4, R5.1, R6.5]

- [ ] 2.4 `features/reviews/data/http/http-reviews-source.ts`: `getReview` pide
  `GET /api/v1/reviews/{id}` y devuelve `Review`; `getDraft` pide
  `GET /api/v1/reviews/{id}/response` y devuelve `ReviewDraft` (404 si la reseña
  está `IGNORED`, indistinguible del 404 de inexistente, R5.4 del spec);
  `createReview` hace `POST /api/v1/reviews` con cuerpo de `CreateReviewInput`
  (`property_id`, `channel`, `reviewer_name?`, `rating`, `content?`, `language?`);
  `respondToReview` hace `PATCH /api/v1/reviews/{id}/response` con cuerpo
  discriminado por `action` (`{action}` para `APPROVE`/`IGNORE`/`MARK_POSTED`,
  `{action, draft_content}` para `EDIT`); `listProperties` pide `GET /api/v1/properties`
  con `page: 1, per_page: 100`, con el `ASSUMPTION` anotado en el código. Tests del
  cuerpo exacto de las dos escrituras y del 404 indistinguible del draft. [R3.1, R3.3, R4.3, R5.3, R5.4, R6.1, R6.3]

- [ ] 2.5 `features/reviews/data/index.ts` (nuevo): `getReviewsDataSource()` con
  `createAuthenticatedClients`, copiando la forma de `features/cleaning/data/index.ts`
  para que los tests de componente puedan inyectar un doble. Sin
  `MockReviewsSource`. [R2.1, R5.1]

## 3. Módulos puros de la feature

- [ ] 3.1 `features/reviews/lib/format.ts` (nuevo) + `.test.ts`: `fmtRating(value:
  string, locale: string)` con `Number(value)` **sólo para formatear**, un decimal
  fijo y la cadena original si el número no es finito, **sin** `/5` incrustado (la
  etiqueta localizada lo añade); `fmtDay(isoDay, locale)` con `Intl.DateTimeFormat(locale,
  { dateStyle: "medium", timeZone: "UTC" })`. Los llamantes pasan `i18n.language`.
  Tests: separador decimal de ES vs EN, cadena no numérica devuelta tal cual, y
  `"2026-01-01"` formateado con `TZ` simulada al oeste de UTC sigue dando el día 1.
  No se escribe `fmtUtc`: ningún `created_at`/`updated_at` se muestra (D3 los
  descarta en el boundary). [R6.3, R8.3, R8.4]

- [ ] 3.2 `features/reviews/lib/review-actions.ts` (nuevo) + `.test.ts`:
  `legalActions(status, role): readonly ReviewAction[]` sobre dos `Record`
  exhaustivos — el primero `Record<ReviewStatus, readonly ReviewAction[]>` con las
  cinco entradas de D5 (`NEW → []`, `DRAFTED → [APPROVE, IGNORE, EDIT]`,
  `APPROVED → [MARK_POSTED]` —el borrador queda bloqueado tras aprobar,
  `ReviewResponseDraft.edit()` rechaza con `ReviewValidationError` cuando
  `approved_at` está fijado, spec R3.6—, `POSTED_MANUALLY → []`, `IGNORED → []`),
  y el segundo `Record<Role, readonly ReviewAction[]>` que cruza con el primero
  (manager sólo `EDIT`, owner `APPROVE + IGNORE + EDIT`). Tests: los cinco
  estados, los dos roles, y un estado desconocido (deploy skew) devuelve `[]`.
  Comentar que es affordance y no autoridad: el backend valida y contesta `409`. [R3.1, R3.2, R6.4]

- [ ] 3.3 `features/reviews/lib/reviews-error.ts` (nuevo) + `.test.ts`: tres tablas
  `Record<number, string>` con `?? GENERIC`, eligiendo por `ApiError.status` —
  responder/editar (`403`, `404`, **`409`**, `422`, genérico), crear (`403`, `422`,
  genérico), leer (`403`, `404`, genérico). Sin rama `401` (lo resuelve el cliente
  HTTP). Tests: el `409` da una clave distinta del genérico, el `404` del camino de
  lectura da una clave distinta del genérico, y **ninguna** de las tres funciones
  lee `message`, `code` ni `details`. [R3.5, R3.6, R3.7, R5.5]

- [ ] 3.4 `features/reviews/lib/property-directory.ts` (nuevo) + `.test.ts`: unión
  de cuatro formas `portfolio | pending | unavailable | resolved`, copia adaptada de
  `features/pricing/lib/property-directory.ts` (D6). En esta pantalla `property_id`
  nunca es `null` (R1.5 del spec backend), pero se conserva la forma del módulo de
  pricing por simetría y porque el catálogo de viviendas se sigue pidiendo igual.
  El fallo del catálogo resuelve a `unavailable` y **no** propaga a error de vista.
  Tests de las cuatro ramas. [R2.8, R5.3]

## 4. Store de UI

- [ ] 4.1 `features/reviews/state/use-reviews-ui-store.ts` (nuevo) + `.test.ts`:
  Zustand con `tenantId`, `activeTab: "drafts" | "reviews"` (inicial `"drafts"`),
  `detailReviewId: string | null`, y **dos rebanadas independientes** —
  `drafts {propertyId, channel, sentiment, ratingMin, ratingMax, dateFrom, dateTo,
  page}` y `reviews {propertyId, channel, sentiment, status, ratingMin, ratingMax,
  dateFrom, dateTo, page}`. El reset a página 1 vive **dentro de cada setter**;
  `adoptTenant` devuelve el store entero al estado inicial al cambiar de tenant;
  `setActiveTab` no toca ninguna rebanada; `setActiveTab` cierra el detalle
  (`setDetailReviewId(null)`). Tests: reset a página 1 por setter, las dos
  rebanadas no comparten `propertyId` ni `page`, cambiar de pestaña conserva
  filtros y página de cada una y cierra el detalle, `adoptTenant` con otro tenant
  borra el `propertyId` anterior. [R1.1, R1.3, R2.1, R5.1]

## 5. Hooks de query y mutación

- [ ] 5.1 `features/reviews/hooks/query-keys.ts` (nuevo) + `.test.ts`: sobre
  `tenantScopedKey`, recursos `"reviews"`, `"review-drafts"`, `"review-properties"`,
  y las entradas `list(tenantId, filters, page)`, **`listPrefix(tenantId)`** (para
  invalidar por prefijo), `detail(tenantId, reviewId)`, `draft(tenantId, reviewId)`,
  `properties(tenantId)`. `normalizeReviewFilters` emite en **orden fijo**, omite las
  ausentes y canoniza `page`. Tests: dos objetos de filtro equivalentes con otro
  orden dan la misma clave, y `listPrefix` es prefijo de `list` para cualquier filtro
  y página. [R2.1, R3.4, R5.1]

- [ ] 5.2 `features/reviews/hooks/use-reviews-data.ts` (nuevo) + `.test.tsx`:
  `useReviewsList(filters, page)`, `useReviewDetail(reviewId)`,
  `useReviewDraft(reviewId)`, `usePropertyDirectory()` con la `retryPolicy` del
  árbol. El detalle y el borrador son **dos queries independientes** que el detalle
  dispara en paralelo (R6.1); el detalle se monta sólo cuando `detailReviewId` no es
  `null`. El fallo del catálogo no marca error en las otras queries. [R2.1, R2.8, R5.1, R6.1]

- [ ] 5.3 `features/reviews/hooks/use-respond-to-review.ts` (nuevo) + `.test.tsx`:
  unión discriminada `RespondInput` (D4), `retry: false`, **sin** parcheo optimista,
  con `invalidateQueries({ queryKey: reviewsKeys.listPrefix(tenantId) })` en
  **`onSettled`**. La mutación no recibe el `tenantId` por argumento, lo lee de
  `useAuth()`. Tests: la invalidación ocurre también cuando el `PATCH` falla, las
  cuatro acciones envían el cuerpo correcto (sin `draft_content` para los tres
  primeros, con `draft_content` para `EDIT`), y un `EDIT` con `draft_content`
  vacío falla en el sitio de uso (`draftContent.trim().length === 0` →
  `TypeError`, sin red). [R3.3, R3.4, R3.5, R4.3]

- [ ] 5.4 `features/reviews/hooks/use-create-review.ts` (nuevo) + `.test.tsx`:
  `retry: false`, cuerpo `CreateReviewInput` (de `data/dto.ts`), misma invalidación
  de prefijo en `onSettled`. Tests: el cuerpo tiene los nombres correctos
  (`property_id` snake_case, no `propertyId`), y la invalidación ocurre también al
  fallar. [R5.3, R5.4]

## 6. Componentes

- [ ] 6.1 `features/reviews/components/reviews-pagination.tsx` (nuevo) +
  `.test.tsx`: presentacional puro (`page`, `totalPages`, `total`, `onPageChange`),
  contra `useTranslation("reviews")`, sin tocar la red y sin selector de tamaño de
  página. Test de que con `totalPages = 0` no se renderiza. [R2.3]

- [ ] 6.2 `features/reviews/components/reviews-tabs.tsx` (nuevo) + `.test.tsx`:
  `role="tablist"` con dos `<button role="tab">` (`aria-selected`, `aria-controls`,
  roving `tabIndex`, flechas izquierda/derecha + Home/End) y un único
  `role="tabpanel"` con `aria-labelledby`. Se monta **sólo el panel activo**
  (render condicional, no `hidden` por CSS), de modo que la query de la pestaña
  inactiva no se dispara hasta que alguien la abre (R2.1, R5.1). Tests: teclado
  completo, y el panel inactivo no está en el DOM. [R1.1]

- [ ] 6.3 `features/reviews/components/review-filters.tsx` (nuevo) + `.test.tsx`:
  selectores de vivienda (desde el catálogo), canal, sentimiento, estado (sólo en
  la pestaña Reseñas), rating `min`/`max` con `<input type="number">`, rango de
  fechas con `<input type="date">`. Nunca se deshabilitan mientras vuela una
  escritura. La etiqueta de rating lleva `/5`. [R2.1, R5.1, R6.4]

- [ ] 6.4 `features/reviews/components/review-row.tsx` (nuevo) + `.test.tsx`:
  tarjeta compacta con vivienda (las cuatro formas de D6/3.4), `channel` localizado,
  `rating` con `fmtRating`, `sentiment` localizado, `publishedAt` con `fmtDay` (em-dash
  si es `null`). La pestaña Borradores NO pinta `status` (siempre es `DRAFTED`); la
  pestaña Reseñas sí, con insignia localizada. Tests: no aparece `content` ni
  `aiSummary` ni `recurringIssues` (van al detalle, D11/R2.5), y un `publishedAt`
  `null` se pinta como em-dash. [R2.4, R2.5, R6.3, R6.4]

- [ ] 6.5 `features/reviews/components/review-actions.tsx` (nuevo) + `.test.tsx`:
  botones de decisión/edición en línea según `legalActions(status, role)`, con
  confirmación en dos pasos dentro de la fila («¿Aprobar esta reseña?
  [Confirmar] [Cancelar]», `pendingAction` local a la fila, texto distinto por
  acción). **No** incluye **Marcar como publicada** — ese vive en el detalle y
  abre el `AlertDialog` de 6.7. Deshabilitado mientras `isBusy`, con texto
  «Enviando…» en la fila cuya decisión vuela. Oculto tras
  `useHasPermission("MANAGE_REVIEW_DECISIONS")` cuando no hay acciones para el
  rol. Tests: `DRAFTED` ofrece tres botones al owner (sólo **Editar borrador** al
  manager), `APPROVED` no ofrece nada en la fila ni **Editar borrador** (el
  draft queda bloqueado tras aprobar, R3.3; el owner usa el detalle para **Marcar
  como publicada**), y sin confirmar no se llama a la mutación. [R3.1, R3.2, R3.3, R6.4, R7.4]

- [ ] 6.6 `features/reviews/components/review-detail.tsx` (nuevo) + `.test.tsx`:
  monta encima del listado (overlay, no ruta hija). Pinta, en este orden: el
  nombre del huésped si existe, `content` como texto literal (etiqueta «Texto del
  huésped»), `rating`, `channel`, `publishedAt`, `sentiment` localizado,
  `aiSummary` etiquetado como «Resumen automático», `recurringIssues` como
  etiquetas localizadas, y `draft_content` etiquetado como «Borrador propuesto» —
  **como texto, nunca como HTML**, con un test que pasa `content` y
  `draft_content` con marcado dentro y comprueba que se ven literal y no se crea
  ningún elemento. Cuando el rol es owner y la fila está en `APPROVED`, muestra el
  botón **Marcar como publicada** que abre el diálogo de 6.7. Editar borrador en
  línea (mismo patrón que 6.5). Tests: ningún `dangerouslySetInnerHTML` en la
  feature, `aiSummary` siempre etiquetado (R6.2), y el botón **Marcar como
  publicada** sólo aparece para owner en `APPROVED`. [R3.3, R3.8, R4.1, R6.1, R6.2, R6.3, R6.4]

- [ ] 6.7 `features/reviews/components/mark-posted-dialog.tsx` (nuevo) +
  `.test.tsx`: `AlertDialog` de `components/ui/alert-dialog.tsx` con preview de
  `content` (texto del huésped) y `draft_content` (borrador aprobado) en
  `AlertDialogDescription`, sin edición. `AlertDialogAction` localizado envía la
  mutación. Cierre sólo por el botón primario. Tests: el preview contiene los dos
  textos, la acción sólo dispara la mutación con `action = MARK_POSTED` (sin
  `draft_content`), y cerrar con `Cancel` no llama a la mutación. [R3.3, R4.1, R4.2, R4.3, R6.4]

- [ ] 6.8 `features/reviews/components/create-review-dialog.tsx` (nuevo) +
  `.test.tsx`: diálogo de alta a mano con `property_id` (selector del catálogo de
  viviendas), `channel` (selector cerrado con los **cinco** valores del enum
  `ReviewChannel`: `AIRBNB`, `BOOKING`, `GOOGLE`, `MANUAL`, `OTHER`), un
  `<input>` opcional para `reviewer_name` (máximo 200 caracteres), selector
  `1.0`..`5.0` con paso `0.5` para `rating`, `<textarea>` opcional para `content`
  (máximo 4000 caracteres), `<select>` opcional para `language`. La validación de
  cliente refleja la del backend (R5.1) y **no** añade restricciones que el backend
  no impone. `AlertDialogAction` deshabilitado hasta que `property_id` y `channel`
  estén fijados. Tests: la validación bloquea envío si falta lo obligatorio, el
  cuerpo tiene los nombres correctos (`property_id` snake_case), y el éxito cierra
  el diálogo. [R5.3, R5.4, R5.5]

- [ ] 6.9 `features/reviews/components/drafts-panel.tsx` (nuevo) + `.test.tsx`:
  cabecera con **Añadir reseña** (oculto sin `CREATE_REVIEW_UI`, abre 6.8), filtros
  de la pestaña Borradores (siempre con `status = DRAFTED` aplicado, no como
  selector), **una sola** región viva `role="status" aria-live="polite"` para
  errores, lista de filas (`review-row.tsx` + `review-actions.tsx`), y paginación
  sólo cuando `total > 0`. Con `total = 0` renderiza el estado vacío localizado
  («No hay borradores pendientes.») y **nunca** «página 1 de 0». Tests: el
  estado vacío, el `409` mostrando su copia propia distinta del genérico, y el
  botón **Añadir reseña** oculto sin permiso. [R2.3, R3.5, R5.3]

- [ ] 6.10 `features/reviews/components/reviews-panel.tsx` (nuevo) + `.test.tsx`:
  cabecera con **Añadir reseña** (mismo botón que 6.9), filtros de la pestaña
  Reseñas (incluye selector de `status` que en Borradores no aparece), lista de
  filas (misma fila + acciones que 6.9, pero `review-actions.tsx` aplica la matriz
  completa de D5 sobre el `status` actual), paginación. Mismos estados vacío y de
  error que 6.9, con claves localizadas propias (`reviews.list.empty.*`,
  `reviews.list.error.*`). Tests: el selector de `status` funciona, y el estado
  vacío no muestra paginación. [R2.3, R5.1, R5.2]

- [ ] 6.11 `features/reviews/components/reviews-view.tsx` (nuevo) + `.test.tsx`:
  orquesta las dos pestañas, posee la mutación `respondToReview` y expone `isBusy =
  respond.isPending`. Replica el guardia `staleFilters` de `pricing-view.tsx` para
  que la primera petición no salga con el filtro de la sesión anterior (R1.3). Al
  abrir una fila (`setDetailReviewId(row.id)`) monta el detalle encima del
  listado. Al cambiar de pestaña se cierra el detalle (`setDetailReviewId(null)`).
  Mientras `isBusy`, los controles de **todas** las filas y del diálogo de **Marcar
  como publicada** están deshabilitados; los `<select>` de filtro no. Tests: la
  pestaña activa inicial es Borradores, abrir una fila dispara las dos queries
  (detalle + borrador), el guardia `staleFilters` impide la primera petición con
  filtro de la sesión anterior, y cambiar de pestaña cierra el detalle. [R1.1, R1.3, R3.3, R4.3]

- [ ] 6.12 `features/reviews/index.ts` (nuevo): exporta **sólo** `ReviewsView`. [R1.1]

## 7. i18n — contrato de locales

- [ ] 7.1 `features/reviews/locales/reviews-locale.test.ts` (nuevo): con el patrón
  de `features/properties/locales/properties-locale.test.ts` (lista derivada del
  `Record` tipado sobre los enums generados, no transcrita a mano), comprobar que
  los **cinco** valores de `ReviewStatus` (incluido `NEW`), los **tres** de
  `ReviewSentiment`, los **cinco** de `ReviewChannel` (`AIRBNB`, `BOOKING`,
  `GOOGLE`, `MANUAL`, `OTHER`), y los **nueve** de `RecurringIssueTag` tienen
  etiqueta en ES y EN, y que las copias de `respond.confirmQuestion` existen
  para las cuatro acciones. [R8.2, R8.5]

## 8. Ruta final

- [ ] 8.1 `app/(workspace)/reviews/page.tsx`: sustituir `RoutePlaceholder` por
  `<ReviewsView />` desde `@/features/reviews`, conservando `generateMetadata` desde
  `routeMetadata("reviews")`. **No tocar** `features/shell/navigation/route-registry.ts`
  ni `locales/{es,en}/navigation.json`, no dar de alta descriptores y no cambiar
  `match` a `"prefix"`. Verificar con `git diff --name-only` que ninguno de esos
  ficheros aparece. [R1.2, R1.4]

## 9. Verification

Antes de leer cualquier cifra de `npm test`, correr los `docker compose cp` que
`sdd/project.md` §Commands documenta para un worktree enlazado: sin ellos
`features/provenance/workflow-contract.test.ts` y
`lib/config/build-identity-contract.test.ts` fallan con `ENOENT` por causas del
entorno y **no** son regresión de este change.

- [ ] 9.1 Suite completa verde: `docker compose exec -T frontend npm test`. Comparar
  el recuento con la **línea base medida** del worktree antes de empezar (no con la
  cifra escrita en `sdd/project.md`, que está obsoleta), y no aceptar un
  «PASS (0) FAIL (0)» como verde. **La cifra de referencia se mide, no se recuerda**
  — `pricing-web` 2026-08-23 descubrió al hacerlo que la cifra de `sdd/project.md`
  era de varios changes atrás. Reportar la medición real en el `metrics.md` del
  change. — *Línea base medida al inicio de la sección 9*: __ ficheros, __ tests.

- [ ] 9.2 Typecheck y lint: `docker compose exec -T frontend npm run typecheck` y
  `docker compose exec -T frontend npm run lint`. — Ambos limpios.

- [ ] 9.3 **No** correr `npm run api:check`: este diff no regenera el contrato y el
  comando no funciona tal cual en un worktree enlazado (D19). Confirmar con
  `git diff --name-only` que ni `backend/openapi.json` ni
  `frontend/lib/api/generated/openapi.d.ts` aparecen. — **Confirmado**: no aparecen,
  ni tampoco `route-registry.ts` ni `navigation.json` (R1.2).

- [ ] 9.4 **Antes de abrir el PR** se hace la regeneración manual de
  `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` fuera del diff
  (workaround de `sdd/project.md` §Commands). Se commitea aparte y se reabre el PR
  antes de review si hay deriva. — *Hecho*: ver commit de regeneración al pie del
  PR.

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->