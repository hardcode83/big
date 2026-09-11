# Design: reviews-web

## Context

`/reviews` es hoy un placeholder: `frontend/app/(workspace)/reviews/page.tsx` renderiza
`RoutePlaceholder routeId="reviews"` sobre un descriptor de ruta ya registrado
(`features/shell/navigation/route-registry.ts:239-243`, `match: "exact"`, grupo `revenue`)
y con sus claves i18n presentes en los dos locales. El backend está entregado y
congelado (`sdd/specs/revenue-reviews.md`): `frontend/lib/api/generated/openapi.d.ts` ya
declara las siete operaciones de reviews, con `ReviewStatus` de cinco valores,
`ReviewPageResponse` en sobre `{items, page, per_page, total}` **sin `total_pages`**,
`ReviewResponse` **sin `approved_by`/`approved_at`/`updated_at`** en el contrato que la
UI consume, y `ReviewResponseActionRequest` con cuatro valores (`APPROVE`, `IGNORE`,
`MARK_POSTED`, `EDIT`).

El precedente estructural es **`frontend/features/pricing/`** (cola de decisión sobre
una mutación, dos pestañas bajo el mismo descriptor, mappers de error por status HTTP,
feature completa con `data/`+`hooks/`+`lib/`+`state/`+`components/`). El precedente
para el directorio de viviendas es el mismo módulo (`lib/property-directory.ts`), con la
rama `portfolio | pending | unavailable | resolved` que `pricing-web` ya adoptó para
resolver nombres de vivienda en `rules.property_id === null`. El formateo de rating
como `/5` con separador del locale viene de `features/incidents/.../incident-detail-sections.tsx`
(`fmtDecimal`), y el test de contrato de locales derivado de un `Record` exhaustivo, de
`features/properties/locales/properties-locale.test.ts`.

**Una diferencia operativa con pricing-web**: el botón **Marcar como publicada** de
R4.2 lleva contenido en preview (texto del huésped + borrador aprobado) y necesita un
diálogo modal, no una confirmación en línea. `components/ui/alert-dialog.tsx` existe
desde la regeneración de shadcn que siguió a `pricing-web` (lo usan `auth/user-menu.tsx`
para el logout, `manager-incident-actions.tsx` para acciones destructivas y
`authenticated-topbar-actions.tsx`); el in-row confirmation de pricing-web queda para
los otros dos movimientos (`APPROVE`, `IGNORE`), que son pura decisión sin preview.

**Sin diagrama.** Lo que este change añade es plumbing de una feature de frontend y la
mitad humana de un flujo cuyo backend ya está dibujado en `docs/reviews.md`; un dibujo
repetiría la misma máquina de estados sin añadir mecanismo. Los diagramas vivos de
`docs/diagrams/` no quedan obsoletos: no cambia el esquema, ni la arquitectura, ni
ninguna secuencia dibujada.

## Decisions

### D1 — Feature nueva `frontend/features/reviews/`, con la costura de `pricing` y sin `Mock*Source`

**Chosen:** una feature completa con las cinco carpetas del patrón —`data/` (interfaz +
DTO + implementación HTTP), `hooks/` (claves y queries/mutaciones), `lib/` (puro),
`state/` (Zustand), `components/`— y un `index.ts` que exporta sólo `ReviewsView`. La
composición de la fuente de datos vive en `data/index.ts` con
`createAuthenticatedClients`, copiando `features/cleaning/data/index.ts:18-37`. No hay
`MockReviewsSource`: el backend existe desde `revenue-reviews` y no hay UI previa a la
que sostener (mismo argumento que `pricing-web` D1, `reservations-web` e `incidents-web`).

Rejected: colgar la pantalla de `features/pricing` reutilizando sus piezas — acopla dos
capacidades sin relación de dominio (la decisión es de reseña, no de precio) y arrastra
su namespace i18n, que ya está cerrado en cinco estados.

### D2 — El sobre de reviews se normaliza en el boundary a `ReviewsPage<T>`, con `totalPages` calculado ahí

**Chosen:** el mapeador de `data/http/http-reviews-source.ts` traduce `{items, page,
per_page, total}` a `ReviewsPage<T> = { items, total, page, perPage, totalPages }` y
calcula `totalPages = perPage > 0 ? Math.ceil(total / perPage) : 0`. El nombre del tipo
es deliberadamente **distinto** de `PricingPage<T>` (pricing-web D2) y de
`PaginatedResponse` (el sobre §23 de `cleaning`, `properties`, `reservations`), para
que nadie copie un boundary de otra feature y crea que comparte forma. Con `total = 0`
el resultado es `totalPages = 0`, y la vista resuelve ese caso como estado vacío antes de
pintar paginación (R2.3), de modo que «página 1 de 0» no es representable.

Rejected: calcular `totalPages` en la vista — dos vistas lo calcularían dos veces y el
error de `total = 0` se cometería por separado en cada una.
Rejected: reutilizar `PricingPage` renombrando `items` a `data` en el mapeador — oculta
la asimetría real del contrato justo donde hay que verla.

### D3 — Lo que no debe pintarse no cruza el boundary

**Chosen:** los DTO de la feature **omiten** del mapeo: `classification_attempts`
(contador interno del job, irrelevante para la UI), `created_at` y `updated_at` (no se
muestran en pantalla por R6.4), `approved_by`/`approved_at` (no están en el DTO
publicado por el backend), `reservation_id` (no hay ruta de detalle de reserva desde
aquí), y `ai_generated` del borrador (el campo es bitácora de origen, no de estado).
El DTO de borrador omite también `ai_generated` por el mismo motivo.

`content` y `ai_summary` y `recurring_issues` **sí** cruzan el boundary, porque R6.2 los
pinta en el detalle, pero el mapeador deja `content` como `string | null` literal —es
prosa del huésped, sumidero de la regla 11 (excepción 4), y la UI la pinta como texto
plano, D11— sin recombinarla ni traducirla. `draft_content` cruza como `string | null`
con la misma disciplina.

Rejected: llevar todos los campos del DTO y filtrar en el componente — es exactamente la
disciplina que R2.5/R5.4 dicen que no quieren, y sobrevive mal a un cuarto componente.

### D4 — `ReviewAction` como `Extract` de cuatro valores

**Chosen:**
`type ReviewAction = Extract<ReviewResponseActionRequest["action"], "APPROVE" | "IGNORE" | "MARK_POSTED" | "EDIT">`.
La firma de `respondToReview` la toma como parámetro discriminado, así que enviar
cualquier otro string no compila, y un renombrado en el backend rompe el build al
regenerar el contrato en vez de producir un `422` en runtime.

`EDIT` requiere `draftContent: string` y los otros tres no. La firma del hook lo modela
con una unión discriminada:

```ts
type RespondInput =
  | { reviewId: string; action: "APPROVE" }
  | { reviewId: string; action: "IGNORE" }
  | { reviewId: string; action: "MARK_POSTED" }
  | { reviewId: string; action: "EDIT"; draftContent: string };
```

Rejected: aceptar `string` y validar en el hook — mueve a runtime una garantía que el
compilador da gratis.

### D5 — `legalActions(status, role)`: mapa de affordance, no autoridad

**Chosen:** `features/reviews/lib/review-actions.ts` con `legalActions(status, role):
readonly ReviewAction[]`, derivado de dos `Record` exhaustivos. El primer mapa es de
**transición**:

| `status` | acciones legales |
|---|---|
| `NEW` | `[]` (la pipeline aún no ha corrido) |
| `DRAFTED` | `["APPROVE", "IGNORE", "EDIT"]` |
| `APPROVED` | `["MARK_POSTED", "EDIT"]` |
| `POSTED_MANUALLY` | `[]` (terminal, R4.1 del spec) |
| `IGNORED` | `[]` (terminal) |

El segundo mapa es de **rol sobre `EDIT`**: el backend exige `APPROVE_REVIEW` para
`EDIT` también ([specs/revenue-reviews.md R3.5](../specs/revenue-reviews.md)), así que
`legalActions` cruza ambos: `legalActions("DRAFTED", "manager") === ["EDIT"]`,
`legalActions("DRAFTED", "owner") === ["APPROVE", "IGNORE", "EDIT"]`. El segundo mapa
es local de la UI y refleja lo que el espejo de permisos del frontend (D15) declara —
no es autoridad, es la pista de UX.

Sí, duplica la tabla de transiciones del backend. Se declara igual que `pricing-web`
D13 (`legalMoves`): «esta reducción es una comodidad, no la autoridad». El backend
valida antes de mutar y contesta `409`, y esta pantalla tiene copia propia para ese
`409` precisamente porque asume que su mapa puede quedarse atrás. Al ser `Record`
exhaustivo sobre la unión generada, un sexto estado en el backend rompe el build al
regenerar el contrato.

### D6 — Directorio de viviendas propio de la feature, con `portfolio` donde `pricing` lo copió

**Chosen:** `features/reviews/lib/property-directory.ts`, copia **idéntica** del módulo
de pricing (`features/pricing/lib/property-directory.ts`), porque semánticamente es la
misma: aquí también `Review.property_id` siempre es no nulo (es requisito, R1.5 del
spec backend), pero las reseñas se filtran por vivienda y un catálogo que falla deja
las filas con `«Vivno disponible»` en vez de tumbar la pantalla (mismo argumento que
pricing-web D5).

Rejected: importar `@/features/pricing/lib/property-directory` — import profundo a una
feature que no lo exporta en su `index.ts`, y la norma del propio árbol
(`features/cleaning/lib/task-status.ts`) es extraer al **tercer** consumidor, no al
segundo, y menos aún por un camino que cruza features.
Rejected: extraer el módulo a `lib/` compartido — no es el tercer consumidor todavía.

### D7 — Claves de query tenant-scoped, con los filtros normalizados

**Chosen:** `hooks/query-keys.ts` sobre `tenantScopedKey`, con recursos
`"reviews"`, `"review-drafts"` y `"review-properties"` —prefijos propios, sin colisión
con los de `pricing` ni `cleaning`— y cinco entradas: `list(tenantId, filters, page)`,
**`listPrefix(tenantId)`** (para invalidar por prefijo como en pricing-web D7),
`detail(tenantId, reviewId)`, `draft(tenantId, reviewId)`, `properties(tenantId)`. Los
filtros entran por `normalizeReviewFilters`, que emite las claves en **orden fijo**,
omite las ausentes y canoniza `page` — patrón de `features/properties/hooks/query-keys.ts`
y `features/pricing/hooks/query-keys.ts`.

El catálogo de viviendas se cachea aparte del de pricing: una página de 100 filas no
justifica un módulo compartido de catálogo, y la duplicación en memoria es la misma que
ya existe entre `pricing` y `properties`.

### D8 — Tres mutaciones, sin parcheo optimista, invalidando sólo el prefijo de reseñas

**Chosen:** `use-respond-to-review.ts` con la unión discriminada de D4, `retry: false`
y `invalidateQueries({ queryKey: reviewsKeys.listPrefix(tenantId) })` en **`onSettled`**
—también cuando falla—. Ninguna mutación parchea la caché: aprobar saca la fila del
filtro `DRAFTED`, ignorar la saca del filtro de cola, y la respuesta del `PATCH` es una
reseña suelta que no sabe nada de `total` ni de la página; sólo un refetch del prefijo
refleja eso sin enumerar combinaciones de filtro y página (R3.4).

`onSettled` cubre las tres acciones: `APPROVE`, `IGNORE`, `MARK_POSTED`, `EDIT`.
`EDIT` cambia el `draft_content` sin cambiar `status`, así que la fila sigue en el
mismo filtro — pero su contenido en pantalla ha cambiado, y la única forma de reflejar
eso es invalidar el prefijo (los query keys incluyen `id`, no `draft_content`).

Rejected: `onSuccess` en vez de `onSettled` — deja en pantalla una fila que el backend
acaba de rechazar por `409`, que es justo el caso que R3.5 hace visible.

**El hook no recibe su entrada igual que `use-decide-recommendation`** (pricing-web D7).
Aquí todas las acciones reciben `reviewId` + `action` (+ `draftContent` para `EDIT`)
como argumento de `mutate()`, y la vista media lo que entra. La razón de la asimetría
es que aquí no hay generación de borrador bajo demanda (`OUT OF SCOPE` en el proposal),
así que la única mutación a proteger del tenant equivocado es la del UI directamente,
y la vista ya hace el guardia `staleFilters` (D13) sobre los filtros que pintan los
botones — la mutación se dispara sobre una fila ya pintada, no sobre filtros del store.

### D9 — Una sola escritura en vuelo, y quién se deshabilita

**Chosen:** la vista posee la mutación y expone `isBusy = respond.isPending`. Mientras
`isBusy`, se deshabilitan **todos** los botones de decisión y de edición de **todas**
las filas y el botón **Marcar como publicada** del diálogo (R3.3, R4.2). La fila cuya
decisión vuela muestra además su propio texto «Enviando…»
(`respond.variables?.reviewId === row.id`).

Dos razones, ambas del precedente de pricing-web D8: iniciar una segunda mutación
desasocia la primera y se traga su rechazo, que R3.7/R3.8 hacen obligatorio; y hay
**una sola región viva** (`role="status" aria-live="polite"`), de modo que dos escrituras
simultáneas se pisarían el anuncio. Se deshabilita el botón, nunca el `<select>` de un
filtro, para no robar el foco a quien esté navegando con teclado.

### D10 — Copia de error elegida por status HTTP, con rama `409` propia

**Chosen:** `features/reviews/lib/reviews-error.ts`, con la forma de
`features/pricing/lib/pricing-error.ts` —una tabla `Record<number, string>` y un
`?? GENERIC`, eligiendo por `ApiError.status` y **jamás** por `ApiError.message`,
`code` o `details` (R3.6, R5.5)—. Tres tablas, porque los tres caminos no comparten
códigos alcanzables:

| camino | 403 | 404 | 409 | 422 | genérico |
|---|---|---|---|---|---|
| decidir / editar / marcar (`PATCH`) | sí | sí | **sí** | sí | sí |
| crear (`POST`) | sí | — | — | sí | sí |
| leer (listados, detalle) | sí | sí | — | — | sí |

El `409` es el caso propio de esta pantalla —«esa reseña ya no está en el estado que
creías»— y tiene copia distinta del genérico (R3.5). `mapPricingError` no sirve: no
tiene rama `404` (esta pantalla sí, porque `GET /reviews/{id}` puede responderlo si el
detalle se carga tarde).

Sobre el `401`: no lleva rama, mismo criterio que pricing-web D9 — lo resuelve el cliente
HTTP con su refresh de un intento.

### D11 — Texto del huésped y del borrador: literal, nunca marcado

**Chosen:** `content` y `draft_content` se pintan como hijos de texto de un elemento
(`{review.content}`, `{draft.draft_content}`), con etiqueta localizada alrededor y sin
traducir ni parsear (R6.2, R6.3). React escapa por defecto, así que el requisito se
reduce a una prohibición explícita —**ningún `dangerouslySetInnerHTML` en esta
feature**— y a un test que renderiza un `content` con marcado dentro
(`Wifi <b>fatal</b>, never again`) y comprueba que el texto aparece literal y que no se
ha creado ningún elemento.

Es el sumidero de texto libre de la regla 11 de `steering/security.md` por dos partes:
`reviews.content` (prosa del huésped, excepción 4) y `review_response_drafts.draft_content`
(vocabulario cerrado, `REVIEW_DRAFT_TEMPLATES`). La UI no recombina ninguno.

### D12 — Marcar como publicada: `AlertDialog` con preview, no confirmación en línea

**Chosen:** `<AlertDialog>` de `components/ui/alert-dialog.tsx` (existe desde que
`auth/user-menu.tsx` lo importó) con `AlertDialogHeader` (título localizado, copy de R4.1
«ya la he publicado en Airbnb»), `AlertDialogDescription` con el texto del huésped y
el `draft_content` aprobado en preview (sin edición), y `AlertDialogFooter` con un
`AlertDialogCancel` y un `AlertDialogAction` cuya copia localizada dice «Confirmar»
(«Confirm»). Sin la puerta de preview la fila pasa a `POSTED_MANUALLY` sin posibilidad
de deshacer, y `IGNORED`/`POSTED_MANUALLY` son terminales.

El diálogo **no** se monta como elemento de la fila: vive en el estado del **detalle**
de la reseña (`detail-dialog-open: boolean | null` en el store de UI), porque la
confirmación necesita el `content` y el `draft_content` que sólo el detalle carga (R6.1).
Los botones **Aprobar**, **Ignorar** y **Editar borrador** de la fila sí van en línea
(estilo pricing-web D12), porque no necesitan preview: el usuario ve el texto del
borrador en la tarjeta abierta del detalle, no en el diálogo.

Rejected: `ConfirmDialog` propio — `AlertDialog` ya cubre el caso y el precedente
existe; un componente nuevo sin tercer consumidor violaría la norma del árbol.
Rejected: confirmación en línea también para `MARK_POSTED` — el contenido que debe
ver la persona que confirma es `content` + `draft_content`, que no caben en una fila sin
robar altura.

### D13 — Pestañas ARIA hechas a mano, sin dependencia nueva, y sólo el panel activo montado

**Chosen:** `features/reviews/components/reviews-tabs.tsx`: un `role="tablist"` con dos
`<button role="tab">` (`aria-selected`, `aria-controls`, roving `tabIndex`, flechas
izquierda/derecha + Home/End) y un único `role="tabpanel"` con `aria-labelledby`. Se
monta **sólo el panel activo** (render condicional, no `hidden` por CSS), de modo que la
query de la pestaña inactiva no se dispara hasta que alguien la abre (R1.1, R2.1, R5.1);
al volver, la caché de TanStack Query la sirve sin red.

Mismo razonamiento que pricing-web D10: no hay primitiva `Tabs` en `components/ui/`, y
el coste de añadir `@radix-ui/react-tabs` es una dependencia nueva más reinstalación en
todos los stacks (`frontend_node_modules` vive en un volumen de Docker).

Rejected: montar los dos paneles y ocultar uno — dispara las dos queries en la carga,
contra la letra de R2.1/R5.1.

### D14 — Un store de UI con dos rebanadas de filtros independientes

**Chosen:** `state/use-reviews-ui-store.ts` (Zustand), con `tenantId`, `activeTab:
"drafts" | "reviews"`, `detailReviewId: string | null`, y **dos rebanadas separadas**:
`drafts {propertyId, channel, sentiment, ratingMin, ratingMax, dateFrom, dateTo, page}` y
`reviews {propertyId, channel, sentiment, status, ratingMin, ratingMax, dateFrom,
dateTo, page}`. Se heredan las dos invariantes de `use-pricing-ui-store.ts`:
**reset a página 1 vive dentro de cada setter**, y `adoptTenant` devuelve el store
entero a su estado inicial cuando cambia el tenant, para que el `propertyId` de una
sesión no viaje a la siguiente (`steering/security.md` regla 1, lado frontend). La vista
replica el guardia `staleFilters` de `pricing-view.tsx:53`.

**Las dos rebanadas no comparten nada, ni siquiera `propertyId`.** Compartir la página
sería un bug obvio (página 3 de borradores al abrir reseñas); compartir la vivienda es un
bug sutil: la usuaria fija filtros distintos en cada pestaña y la pestaña inactiva
conserva los suyos al volver (R1.3).

`setActiveTab` no toca ninguna rebanada: cada pestaña conserva su página y sus filtros.
`setDetailReviewId` abre el detalle encima de la lista activa, sin cambiar de pestaña;
`setDetailReviewId(null)` lo cierra.

### D15 — El espejo de permisos, acertado para los dos roles

**Chosen:** `frontend/lib/auth/permissions.ts` amplía la unión a
`Permission = ... | "MANAGE_REVIEW_DECISIONS" | "CREATE_REVIEW_UI"`, y concede
`MANAGE_REVIEW_DECISIONS` a `TENANT_OWNER` (aprobar / ignorar / marcar-como-publicada /
editar) y `CREATE_REVIEW_UI` a `PROPERTY_MANAGER` (alta a mano + editar borrador). El
resto de roles sigue con `[]`. Los tres botones de decisión, el de edición, el de
marcar-como-publicada del diálogo y el botón **Añadir reseña** se ocultan tras
`useHasPermission(...)` (R7.4).

El mapa sigue siendo **parcial y declarado como tal** (mismo comentario que `permissions.ts`):
sólo enumera lo que el frontend usa para ocultar. Un espejo que pretendiera ser completo
iría obsoleto en silencio el día que el backend añadiera un permiso.

`lib/auth/permissions.test.tsx` gana los casos simétricos a los de cleaning: `CREATE_REVIEW_UI`
concedida a `PROPERTY_MANAGER` y denegada a los otros cuatro roles; `MANAGE_REVIEW_DECISIONS`
concedida a `TENANT_OWNER` y denegada a los otros cuatro. Y denegada sin usuario.

**Lo que NO hace**: el registro de ruta no lleva roles
(`route-registry.ts:110` «carries only shell metadata»), así que el sidebar enseña
`/reviews` a todo el mundo y un `CLEANER`/`TECHNICIAN` que entre recibirá `403` del
listado. Este diseño lo convierte en la copia localizada de `403` de D10, que es todo
lo que cabe hacer sin espejar también `READ_REVIEWS` y sin dar filtrado por rol al
shell — ninguna de las dos cosas está en el alcance de R7.

### D16 — Paginador propio, porque el de `pricing` está atado a su namespace

**Chosen:** `features/reviews/components/reviews-pagination.tsx`, misma forma que
`features/pricing/components/pricing-pagination.tsx` (presentacional puro: recibe `page`,
`totalPages`, `total`, `onPageChange`, y no toca la red), contra el namespace `reviews`.
La reutilización directa no es posible: `pricing-pagination` llama
`useTranslation("pricing")` en su cuerpo, así que sus textos saldrían del catálogo
equivocado. Un solo componente compartido, parametrizado por namespace, es la extracción
que la norma del árbol reserva para el tercer consumidor.

Se usa en las dos pestañas con `per_page` fijo en 20 (el defecto del backend) y sin
selector de tamaño de página, que ningún requisito pide.

### D17 — El namespace `reviews`, en sus cuatro puntos

**Chosen:** `frontend/locales/es/reviews.json` y `frontend/locales/en/reviews.json`,
registrados en `lib/i18n/resources.ts` en los cuatro sitios: el `import` por locale, la
lista `NAMESPACES`, y la entrada dentro de `resources.es` y `resources.en` (R8.1).
Olvidar uno deja el namespace mudo en un idioma; `catalog-parity.test.ts` sólo empieza a
vigilarlo una vez está en `NAMESPACES`.

Estructura de claves, siguiendo `pricing.json`: `tabs.*`, `detail.*`, `list.*`,
`columns.*`, `status.*` (5), `sentiment.*` (3), `channel.*` (4), `recurringIssue.*` (9),
`identity.*`, `filters.*`, `pagination.*`, `respond.*`, `respond.error.*`, `create.*`,
`create.error.*`, `preview.*`, `markPosted.*`.

**Faltan varias en esa lista, y se añaden aquí en vez de dejarlas como invención sin
registrar** (mismo cuidado que pricing-web D19 con `decide.confirmQuestion.*`):

- **`respond.confirmQuestion.{APPROVE,IGNORE,MARK_POSTED,EDIT}`** — D12/D5: la
  confirmación en línea pregunta *qué* está haciendo la usuaria, no genérico.
- **`recurringIssue.{WIFI,NOISE,CLEANLINESS,ACCESS,COMMUNICATION,LOCATION,VALUE,AMENITIES,OTHER}`**
  — R8.2: las nueve etiquetas del enum `RecurringIssueTag`.
- **`channel.{AIRBNB,BOOKING_COM,DIRECT,OTHER}`** — R8.2: los cuatro valores que el
  diálogo de alta expone (los cuatro miembros del enum `ReviewChannel` que
  `CreateReviewRequest.channel` acepta, todos).
- **`status.{NEW,DRAFTED,APPROVED,POSTED_MANUALLY,IGNORED}`** — R8.2: los cinco
  estados, los cinco.
- **`sentiment.{POSITIVE,NEUTRAL,NEGATIVE}`** — R8.2: los tres sentimientos.

Que sean exhaustivas lo comprueba el test de contrato de locales, derivado de los
enums generados y no transcrito a mano — el patrón de
`features/properties/locales/properties-locale.test.ts` que pricing-web D15 ya adoptó.

### D18 — `fmtRating` y `fmtDecimal` con locale, sin zona, ningún `created_at` en pantalla

**Chosen:** `features/reviews/lib/format.ts` con dos funciones:

- `fmtRating(value: string, locale: string): string` — análoga a `fmtDecimal` de
  pricing-web D14: `Number(value)` **sólo para formatear**,
  `toLocaleString(locale, {minimumFractionDigits: 1, maximumFractionDigits: 1})`, y la
  cadena original si el número no es finito. La etiqueta localizada añade `/5`.
- `fmtDay(isoDay: string, locale: string): string` — `Intl.DateTimeFormat(locale,
  {dateStyle: "medium", **timeZone: "UTC"**})` sobre `new Date(isoDay)`. El
  `timeZone: "UTC"` es la parte que no se puede olvidar y es la razón de que esto sea
  una decisión: `new Date("2026-01-01")` se parsea como medianoche **UTC**, así que
  formatearlo con la zona local del navegador imprime el día anterior al oeste de UTC.
  Misma postura que pricing-web D14.

**No se muestra ningún `created_at` ni `updated_at`** en ninguna de las dos pestañas: el
DTO no los publica en el contrato que la UI consume (ver `ReviewResponse` en
`openapi.d.ts:4522-4563`), y R2.4/R5.2 enumeran los campos y no están en la lista. La
fecha visible es `published_at`, y cuando es `null` (la reseña existe pero el huésped
no la ha publicado en la OTA, que es justamente el caso del alta manual de R5) va em-dash
localizado.

`fmtRating` no se reutiliza de pricing-web: pricing-web formatea decimales de dinero,
reviews-web formatea decimales de estrellas, la unidad y la precisión son distintas. Es
una función de tres líneas y la duplicación está acotada.

### D19 — Regeneración de `openapi.json` en worktree: el workaround documentado

**Chosen:** la regeneración de `backend/openapi.json` (para que el cliente tipado
declare las siete rutas y los cinco enums de `reviews` con la misma forma que
`backend/openapi.json:841-941` ya tiene hoy, y que `frontend/lib/api/generated/openapi.d.ts:2098-4608`
ya refleja) **no se hace en este diff** — el árbol declara que el contenedor `frontend`
monta sólo `./frontend` y el workaround de `sdd/project.md` §Commands (`docker compose cp`)
es costoso de aplicar dentro del change. La regeneración es **manual, fuera del diff**
del run, y se hace antes de abrir el PR, mismo criterio que `pricing-web` aplicó para su
propia regeneración.

Lo que el diff sí hace es **verificar** que el cliente tipado del frontend ya cubre las
siete operaciones: la primera tarea del boundary HTTP compila contra `openapi.d.ts` y
falla en rojo si falta una ruta. Es la misma verificación que pricing-web D21 documentó
como «backend — Nada. Contrato congelado; no hay `make openapi`».

### D20 — La página, y el placeholder que se va

**Chosen:** `app/(workspace)/reviews/page.tsx` conserva su `generateMetadata` desde
`routeMetadata("reviews")` y pasa a renderizar `<ReviewsView />` desde `@/features/reviews`
(R1.4), exactamente como `app/(workspace)/pricing/page.tsx`. No se toca
`route-registry.ts`, ni `locales/{es,en}/navigation.json`, ni se da de alta ningún
descriptor (R1.2). El inventario de `sdd/specs/frontend-foundation.md` pasa de cuatro
placeholders del workspace a tres y de las superficies funcionales a una más — verificado
hoy: cinco páginas con `RoutePlaceholder` en el árbol (`settings`,
`settings-integrations`, `statements`, `reviews`, `forgot-password`), la última del
grupo `(public)` y por tanto fuera del inventario del spec. Eso lo escribe `/sdd:archive`,
no este change.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Ruta | `frontend/app/(workspace)/reviews/page.tsx` | Sustituye `RoutePlaceholder` por `<ReviewsView />`; `generateMetadata` intacto (D20) |
| Datos — contrato | `frontend/features/reviews/data/dto.ts` **(nuevo)** | `ReviewsPage<T>`, `Review`, `ReviewDraft`, `ReviewSummary` (sin usar aquí, pero tipa el shape), `PropertySummary`, `ReviewAction`, filtros (D2, D3, D4) |
| Datos — puerto | `frontend/features/reviews/data/reviews-source.ts` **(nuevo)** | Interfaz `ReviewsDataSource`: `listReviews`, `getReview`, `getDraft`, `createReview`, `respondToReview`, `listProperties` |
| Datos — adaptador | `frontend/features/reviews/data/http/http-reviews-source.ts` **(nuevo)** + `.test.ts` | Mapeo `items`→`ReviewsPage`, `totalPages` calculado, filtros como query, omitir `classification_attempts`/`created_at`/`updated_at`/`reservation_id` (D2, D3) |
| Datos — composición | `frontend/features/reviews/data/index.ts` **(nuevo)** | `getReviewsDataSource()` con `createAuthenticatedClients` (D1) |
| Hooks | `frontend/features/reviews/hooks/query-keys.ts` **(nuevo)** + `.test.ts` | Claves tenant-scoped + `normalizeReviewFilters` + prefijo (D7) |
| Hooks | `frontend/features/reviews/hooks/use-reviews-data.ts` **(nuevo)** + `.test.tsx` | `useReviewsList`, `useReviewDetail`, `useReviewDraft`, `usePropertyDirectory` con `retryPolicy` |
| Hooks | `frontend/features/reviews/hooks/use-respond-to-review.ts` **(nuevo)** + `.test.tsx` | Unión discriminada, `retry: false`, invalidación de prefijo en `onSettled` (D4, D8) |
| Hooks | `frontend/features/reviews/hooks/use-create-review.ts` **(nuevo)** + `.test.tsx` | `retry: false`, invalidación de prefijo en `onSettled` |
| Lib | `frontend/features/reviews/lib/property-directory.ts` **(nuevo)** + `.test.ts` | `portfolio \| pending \| unavailable \| resolved` (D6) |
| Lib | `frontend/features/reviews/lib/reviews-error.ts` **(nuevo)** + `.test.ts` | Tres tablas status→clave, sin leer el cuerpo (D10) |
| Lib | `frontend/features/reviews/lib/review-actions.ts` **(nuevo)** + `.test.ts` | `legalActions()` sobre dos `Record` exhaustivos (D5) |
| Lib | `frontend/features/reviews/lib/format.ts` **(nuevo)** + `.test.ts` | `fmtRating`, `fmtDay` con `timeZone: "UTC"` (D18) |
| Estado | `frontend/features/reviews/state/use-reviews-ui-store.ts` **(nuevo)** + `.test.ts` | Pestaña activa + dos rebanadas de filtros + `detailReviewId` + `adoptTenant` (D14) |
| Componentes | `frontend/features/reviews/components/reviews-view.tsx` **(nuevo)** + `.test.tsx` | Orquesta pestañas, tenant staleness, `isBusy`, abre/cierra detalle (D9, D14) |
| Componentes | `.../reviews-tabs.tsx` **(nuevo)** + `.test.tsx` | `tablist`/`tab`/`tabpanel` con teclado (D13) |
| Componentes | `.../drafts-panel.tsx` **(nuevo)** + `.test.tsx` | Cola de borradores con sus filtros y filas |
| Componentes | `.../reviews-panel.tsx` **(nuevo)** + `.test.tsx` | Listado completo con filtros y filas |
| Componentes | `.../review-filters.tsx` **(nuevo)** + `.test.tsx` | Selectores de vivienda, canal, sentimiento, estado (en reseñas), rating min/max, fechas |
| Componentes | `.../review-row.tsx` **(nuevo)** + `.test.tsx` | Tarjeta compacta: vivienda, canal, rating, sentimiento, fecha; estado sólo en la pestaña Reseñas (D5) |
| Componentes | `.../review-actions.tsx` **(nuevo)** + `.test.tsx` | Botones de decisión/edición por en línea, los cuatro casos de D5 |
| Componentes | `.../review-detail.tsx` **(nuevo)** + `.test.tsx` | Detalle encima del listado, con texto del huésped, borrador, controles y diálogo (D11, D12) |
| Componentes | `.../mark-posted-dialog.tsx` **(nuevo)** + `.test.tsx` | `AlertDialog` con preview de `content` + `draft_content` (D12) |
| Componentes | `.../create-review-dialog.tsx` **(nuevo)** + `.test.tsx` | Diálogo de alta a mano con catálogo, canal, rating, contenido (R5) |
| Componentes | `.../reviews-pagination.tsx` **(nuevo)** + `.test.tsx` | Paginador presentacional puro (D16) |
| Barril | `frontend/features/reviews/index.ts` **(nuevo)** | Exporta sólo `ReviewsView` |
| i18n | `frontend/locales/es/reviews.json`, `frontend/locales/en/reviews.json` **(nuevos)** | Namespace completo (D17) |
| i18n | `frontend/lib/i18n/resources.ts` | Los cuatro puntos de registro (D17, R8.1) |
| i18n | `frontend/features/reviews/locales/reviews-locale.test.ts` **(nuevo)** | Los 5 estados, 3 sentimientos, 4 canales, 9 problemas recurrentes en ES y EN, derivados de los enums (D17, R8.2) |
| Permisos | `frontend/lib/auth/permissions.ts` + `permissions.test.tsx` | `MANAGE_REVIEW_DECISIONS` a `TENANT_OWNER`, `CREATE_REVIEW_UI` a `PROPERTY_MANAGER` (D15, R7) |
| Backend | — | **Nada.** Contrato congelado; no hay `make openapi` ni `npm run api:generate` en este diff (D19) |

## Data & interfaces

**Cambios de esquema, endpoints, eventos o variables de entorno: ninguno.** Este change
es sólo frontend y consume las siete operaciones ya publicadas y versionadas en
`frontend/lib/api/generated/openapi.d.ts:841-1030` (rutas) y `:2098-4608` (esquemas).

Interfaces internas nuevas (todas en `frontend/features/reviews/data/`):

```ts
export interface ReviewsPage<T> {
  items: T[]; total: number; page: number; perPage: number; totalPages: number;
}

export type ReviewStatus = components["schemas"]["ReviewStatus"];
export type ReviewSentiment = components["schemas"]["ReviewSentiment"];
export type ReviewChannel = components["schemas"]["ReviewChannel"];
export type RecurringIssueTag = components["schemas"]["RecurringIssueTag"];
export type ReviewAction = Extract<
  components["schemas"]["ReviewResponseActionRequest"]["action"],
  "APPROVE" | "IGNORE" | "MARK_POSTED" | "EDIT"
>;

/** Sin classification_attempts, sin created_at/updated_at — D3. */
export interface Review {
  id: string;
  propertyId: string;
  reviewerName: string | null;
  rating: string | null;          // decimal como cadena (R6.3)
  content: string | null;         // prosa del huésped, regla 11 excepción 4
  sentiment: ReviewSentiment | null;
  aiSummary: string | null;       // vocabulario cerrado, regla 11
  recurringIssues: RecurringIssueTag[];
  status: ReviewStatus;
  publishedAt: string | null;     // ISO 8601 UTC
  channel: ReviewChannel;
  language: string | null;
  reservationId: string | null;
}

/** Sin ai_generated — D3. */
export interface ReviewDraft {
  reviewId: string;
  draftContent: string | null;    // vocabulario cerrado, regla 11
  language: string | null;
}

export interface ReviewFilters {
  propertyId?: string;
  channel?: ReviewChannel;
  sentiment?: ReviewSentiment | null;
  status?: ReviewStatus;
  ratingMin?: string;             // decimal como cadena
  ratingMax?: string;             // decimal como cadena
  dateFrom?: string;              // YYYY-MM-DD
  dateTo?: string;                // YYYY-MM-DD
}

export interface PropertySummary {
  id: string;
  internalCode: string;
  name: string;
}

export interface CreateReviewInput {
  propertyId: string;
  channel: ReviewChannel;
  reviewerName?: string;
  rating: number;
  content?: string;
  language?: string;
}

export type RespondInput =
  | { reviewId: string; action: "APPROVE" }
  | { reviewId: string; action: "IGNORE" }
  | { reviewId: string; action: "MARK_POSTED" }
  | { reviewId: string; action: "EDIT"; draftContent: string };

export interface ReviewsDataSource {
  listReviews(tenantId: string, filters: ReviewFilters, page: number):
    Promise<ReviewsPage<Review>>;
  getReview(tenantId: string, reviewId: string): Promise<Review>;
  getDraft(tenantId: string, reviewId: string): Promise<ReviewDraft>;
  createReview(tenantId: string, input: CreateReviewInput): Promise<Review>;
  respondToReview(tenantId: string, input: RespondInput): Promise<Review>;
  listProperties(tenantId: string): Promise<PropertySummary[]>;
}
```

El parámetro de query del filtro de estado se envía con el nombre **`status`**, y el
del sentimiento con **`sentiment`**, igual que en el resto de listados del proyecto.

## Cobertura de requisitos

| Req | Dónde se resuelve |
|---|---|
| R1.1 pestaña Borradores por defecto | D13, D14 (`activeTab` inicial `"drafts"`) |
| R1.2 sin descriptor nuevo, `match` intacto, sin claves de navegación | D20 (no se toca `route-registry.ts` ni `navigation.json`) |
| R1.3 pestaña en el store, no en la URL | D14 |
| R1.4 fuera `RoutePlaceholder` | D20 |
| R2.1 query con `status = DRAFTED` y filtros | D2, D7; nombre `status` verificado contra el router |
| R2.2 sobre `items` y `Math.ceil` | D2 |
| R2.3 `total = 0` → vacío, nunca «1 de 0» | D2 (`totalPages = 0`) + guardia de la vista antes del paginador |
| R2.4 campos por fila | `review-row.tsx` |
| R2.5 sin `content` en la fila | D3 (no se pinta en `review-row.tsx`), D11 |
| R3.1 movimientos por estado y por rol | D5 (`legalActions(status, role)`) |
| R3.2 sólo `MARK_POSTED` en `APPROVED` | D5 |
| R3.3 confirmar antes de mutar | D12 (en línea para los tres primeros) + D9 (`isBusy`) |
| R3.4 `retry: false`, sin optimismo, prefijo en `onSettled` | D8 |
| R3.5 copia propia del `409` | D10 |
| R3.6 elegir por status, nunca por el cuerpo | D10 |
| R3.7 el `403` es error | D10 |
| R3.8 texto del borrador y del huésped como texto | D11 |
| R4.1 copy que dice «ya la he publicado» | D12, D17 (`markPostedDialog.*`) |
| R4.2 `AlertDialog` con preview | D12 |
| R4.3 `action = MARK_POSTED` sin `draft_content`, invalida prefijo | D8 (unión discriminada) |
| R5.1 query sin `status` por defecto, selector de estado en cabecera | `reviews-panel.tsx` |
| R5.2 mismo row + `status` localizado | `review-row.tsx` + D17 |
| R5.3 diálogo **Añadir reseña** con los campos del backend | `create-review-dialog.tsx` |
| R5.4 envío + invalidación + cierre | `use-create-review.ts` |
| R5.5 `422` por status, sin leer el cuerpo | D10 |
| R6.1 detalle con `content`, `ai_summary`, `recurring_issues`, `draft_content` | `review-detail.tsx`, D11 |
| R6.2 texto literal, nunca HTML | D11 |
| R6.3 borrador editable en `DRAFTED`/`APPROVED` | `review-detail.tsx`, D5, D8 |
| R6.4 controles según rol | D5, D15 |
| R6.5 sin `classification_attempts`/`created_at`/`updated_at` | D3 (no cruzan el boundary) |
| R7.1 dos permisos nuevos | D15 |
| R7.2 `MANAGE_REVIEW_DECISIONS` a owner, `CREATE_REVIEW_UI` a manager | D15 |
| R7.3 sin conceder a otros roles | D15 (test de `permissions.test.tsx`) |
| R7.4 pista de UX, no autoridad | D15 (`403` sigue siendo error, D10) |
| R8.1 namespace en cuatro puntos | D17 |
| R8.2 etiquetas para 5+3+4+9 valores de enum | D17 |
| R8.3 `rating` como `/5` | D18 (`fmtRating`) |
| R8.4 `published_at` como día UTC | D18 (`fmtDay`) |
| R8.5 nada hardcodeado | D17 + `catalog-parity.test.ts` + test de locales |

## Risks & mitigations

- **El sobre `items` es el error caro de esta entrada.** Un boundary copiado de
  `pricing`/`cleaning` compila contra `data` y falla en runtime. Mitigación: el tipo se
  llama `ReviewsPage` y no `PricingPage` (D2), y el primer test del adaptador HTTP fija
  el nombre del campo y el cálculo de `totalPages`, incluido `total = 0 → 0`.
- **Formatear el día con la zona local imprime el día anterior** al oeste de UTC — un bug
  que no se ve desde Madrid. Mitigación: `timeZone: "UTC"` en `fmtDay` (D18) y un test
  que formatea `"2026-01-01"` con `TZ` simulada al oeste.
- **`npm test` en un worktree enlazado da dos ficheros en rojo que no son de este change**
  (`features/provenance/workflow-contract.test.ts` y
  `lib/config/build-identity-contract.test.ts`, `ENOENT` porque el contenedor sólo monta
  `./frontend`). Mitigación: `sdd/project.md` §Commands documenta los `docker compose cp`
  que los arreglan; la tarea de verificación los ejecuta antes de leer cifras, y **no**
  se interpretan como regresión. Tampoco hace falta `npm run api:check` dentro del diff
  (D19): no hay contrato regenerado por el change.
- **Deploy skew en el enum.** Un sexto `ReviewStatus` llegado por la red antes de
  reconstruir el frontend no tiene etiqueta ni movimientos. Mitigación: `legalActions`
  devuelve `[]` para lo desconocido y la insignia cae a tono neutro; nunca se pinta el
  identificador crudo del enum.
- **Más de 100 viviendas** rompe la resolución de nombres (una sola página de catálogo).
  Mitigación: misma `ASSUMPTION` que `pricing-web` D5, degrada a «identidad no
  disponible» y no a fallo; se anota en el código como `ASSUMPTION`.
- **El `403` del `CLEANER`/`TECHNICIAN` que llega por el sidebar** no se puede evitar
  desde aquí (D15). Mitigación: copia localizada propia de `403` en el camino de
  lectura; el filtrado del sidebar por rol queda como carencia conocida del shell.
- **El navegador se queda en preview con la reseña abierta y la usuaria navega fuera.**
  El detalle vive en el store, no en la URL. Mitigación: al cambiar de pestaña
  (`setActiveTab`) se cierra el detalle (`setDetailReviewId(null)`); al volver, no hay
  detalle abierto. Mismo cuidado que cualquier modal en SPA.

## Open questions

Ninguna abierta. Las dos decisiones que el proposal abrió se resolvieron aquí:

- **OQ1 — confirmación de `MARK_POSTED`** → **D12**: `AlertDialog` con preview de
  `content` + `draft_content`, no en línea. Los otros tres movimientos (`APPROVE`,
  `IGNORE`, `EDIT`) sí van en línea (mismo de pricing-web D12) porque no necesitan
  preview.
- **OQ2 — espejo de permisos** → **D15**: dos permisos nuevos en `permissions.ts`,
  concedidos a un rol cada uno, sin solapamiento. El manager ve **Editar borrador** en
  `DRAFTED`; la owner ve **Aprobar**/**Ignorar**/**Editar borrador** en `DRAFTED` y
  **Marcar como publicada** en `APPROVED`.

Queda **una verificación**, no una decisión: D19 deja la regeneración de `openapi.json`
fuera del diff, pero **antes de abrir el PR** se hace la regeneración manual contra
el contenedor del worktree (workaround de `sdd/project.md` §Commands), y se verifica
que `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` no han cambiado
— si cambian, hay deriva y el PR se reabre antes de review.