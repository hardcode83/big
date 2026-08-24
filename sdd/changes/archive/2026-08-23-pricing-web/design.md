# Design: pricing-web

## Context

`/pricing` es hoy un placeholder: `frontend/app/(workspace)/pricing/page.tsx` renderiza
`RoutePlaceholder routeId="pricing"` sobre un descriptor de ruta ya registrado
(`features/shell/navigation/route-registry.ts:203-215`, `match: "exact"`, grupo `revenue`)
y con sus claves i18n presentes en los dos locales. El backend está entregado y congelado
(`sdd/specs/revenue-pricing.md`): `frontend/lib/api/generated/openapi.d.ts` ya declara las
cinco operaciones de pricing, con `PriceRecommendationStatus` de cinco valores,
`PriceRecommendationPageResponse`/`PricingRulePageResponse` en sobre `{items, total, page,
per_page}` **sin `total_pages`**, `PriceRecommendationResponse` **sin `updated_at`**, y
`DecidePriceRecommendationRequest` con un único campo `status`.

El precedente estructural es `frontend/features/cleaning/` (lista paginada + filtros +
una mutación + resolución de identidades): costura `data/` → `hooks/` → `components/`,
claves de query sobre `tenantScopedKey`, filtros en Zustand con reset a página 1 dentro de
los setters, y mapeo de error por status HTTP. El formateo de dinero sin moneda viene de
`features/incidents/components/detail/incident-detail-sections.tsx` (`fmtCost`), y el test
de contrato de locales derivado de un `Record` exhaustivo, de
`features/properties/locales/properties-locale.test.ts`.

Dos ausencias verificadas en el árbol condicionan el diseño: **no hay primitiva de
pestañas** (`components/ui/` tiene Badge, Button, Separator, Sheet, Skeleton, Tooltip; cero
ocurrencias de `role="tab"`, `aria-selected` o `Tabs` en todo `frontend/`) y **no hay
diálogo de confirmación** (`sheet.tsx` es el cajón de navegación; ningún componente usa
`Dialog` como modal de confirmación).

**Sin diagrama.** Lo que este change añade es plumbing de una feature de frontend y una
tabla de tres transiciones que cabe en una frase (`RECOMMENDED → APPROVED|REJECTED`,
`APPROVED → APPLIED_EXTERNAL`); un dibujo repetiría el texto sin añadir mecanismo. Los
diagramas vivos de `docs/diagrams/` no quedan obsoletos: no cambia el esquema, ni la
arquitectura, ni ninguna secuencia dibujada.

## Decisions

### D1 — Feature nueva `frontend/features/pricing/`, con la costura de `cleaning` y sin `Mock*Source`

**Chosen:** una feature completa con las cinco carpetas del patrón —`data/` (interfaz +
DTO + implementación HTTP), `hooks/` (claves y queries/mutaciones), `lib/` (puro),
`state/` (Zustand), `components/`— y un `index.ts` que exporta sólo `PricingView`. La
composición de la fuente de datos vive en `data/index.ts` con
`createAuthenticatedClients`, copiando `features/cleaning/data/index.ts`, que es lo que
permite a los tests de componente inyectar un doble sin tocar `lib/api`. No hay
`MockPricingSource`: el backend existe desde `revenue-pricing` y no hay UI previa a la que
sostener (mismo argumento que `reservations-web` e `incidents-web`).

Rejected: colgar la pantalla de `features/cleaning` reutilizando sus piezas — acopla dos
capacidades sin relación de dominio y arrastra su namespace i18n.

### D2 — El sobre de pricing se normaliza en el boundary a `PricingPage<T>`, con `totalPages` calculado ahí

**Chosen:** el mapeador de `data/http/http-pricing-source.ts` traduce `{items, total, page,
per_page}` a `PricingPage<T> = { items, total, page, perPage, totalPages }` y calcula
`totalPages = perPage > 0 ? Math.ceil(total / perPage) : 0`. El nombre del tipo es
deliberadamente **distinto** de `PaginatedResponse` (el sobre §23 de `cleaning`,
`properties`, `reservations`), para que nadie copie un boundary de otra feature y crea que
comparte forma. Con `total = 0` el resultado es `totalPages = 0`, y la vista resuelve ese
caso como estado vacío antes de pintar paginación (R2.3), de modo que «página 1 de 0» no es
representable.

Rejected: calcular `totalPages` en la vista — dos vistas lo calcularían dos veces y el
error de `total = 0` se cometería por separado en cada una.
Rejected: reutilizar `PaginatedResponse` renombrando `items` a `data` en el mapeador —
oculta la asimetría real del contrato justo donde hay que verla.

### D3 — Lo que no debe pintarse no cruza el boundary

**Chosen:** los DTO de la feature **omiten** `current_price`, `confidence` y `created_at` de
`PriceRecommendationResponse`, y **no llevan** las cinco columnas JSONB de
`PricingRuleResponse`: el mapeador las sustituye por `modifierCounts` (cinco enteros). Así
R2.5, R2.6 y R5.4 dejan de ser disciplina de quien escribe el componente y pasan a ser
imposibles de violar: el dato no existe en la capa de UI.

El recuento es `countEntries(value)`: `Object.keys(value).length` para `weekday_modifiers`
(que el contrato declara **objeto**), `value.length` para los cuatro arrays, y `0` para
cualquier cosa que no sea lo uno ni lo otro —ventana de deploy skew—. Nunca lee un *valor*
del JSONB, sólo su cardinalidad.

Rejected: llevar los campos al DTO y no renderizarlos — es exactamente la disciplina que
R2.5/R5.4 dicen que no quieren, y sobrevive mal a un cuarto componente.

### D4 — `DecisionStatus` como `Extract` de tres valores

**Chosen:** `type DecisionStatus = Extract<PriceRecommendationStatus, "APPROVED" |
"REJECTED" | "APPLIED_EXTERNAL">`. La firma de `decideRecommendation` la toma, así que
enviar `DRAFT` o `RECOMMENDED` no compila, y un renombrado en el backend rompe el build al
regenerar el contrato en vez de producir un `422` en runtime.

Rejected: aceptar `PriceRecommendationStatus` y validar en el hook — mueve a runtime una
garantía que el compilador da gratis.

### D5 — Directorio de viviendas propio de la feature, con `portfolio` donde `cleaning` tiene `unassigned`

**Chosen:** `features/pricing/lib/property-directory.ts`, copia adaptada de
`features/cleaning/lib/directory.ts`, con la unión de cuatro formas
`portfolio | pending | unavailable | resolved`. La adaptación no es cosmética: en `cleaning`
un id nulo significa «sin asignar», y aquí `PricingRule.property_id === null` significa
**«toda la cartera»** (R5.3), que es una afirmación positiva y no una ausencia. Las
recomendaciones nunca traen `property_id` nulo, así que sólo las reglas alcanzan esa rama.
El fallo del catálogo se queda en `unavailable` y **no** propaga al `ErrorState` de la vista
(R2.8), igual que en el original.

El catálogo se pide a `GET /api/v1/properties` con `page: 1, per_page: 100`, como
`http-cleaning-source.ts:126-130`, y hereda su `ASSUMPTION`: a partir de la vivienda 100 la
identidad degrada a «no disponible».

Rejected: importar `@/features/cleaning/lib/directory` — import profundo a una feature que
no lo exporta en su `index.ts`, y semántica distinta en la rama del id nulo.
Rejected: extraer el módulo a `lib/` compartido — la norma que el propio árbol escribe
(`features/cleaning/lib/task-status.ts`) es extraer al **tercer** consumidor, y éste es el
segundo.

### D6 — Claves de query tenant-scoped, con los filtros normalizados

**Chosen:** `hooks/query-keys.ts` sobre `tenantScopedKey`, con recursos
`"pricing-recommendations"`, `"pricing-rules"` y `"pricing-properties"` —prefijos propios,
sin colisión con los de `cleaning`—, y cuatro entradas:
`recommendations(tenantId, filters, page)`, **`recommendationsPrefix(tenantId)`**,
`rules(tenantId, filters, page)` y `properties(tenantId)`. Los filtros entran por
`normalizeRecommendationFilters` / `normalizeRuleFilters`, que emiten las claves en **orden
fijo**, omiten las ausentes y canonizan `page` — el patrón de
`features/properties/hooks/query-keys.ts`, más estricto que el literal suelto de `cleaning`,
porque TanStack Query hashea la clave estructuralmente y dos objetos equivalentes con otro
orden serían dos entradas de caché.

El catálogo de viviendas se cachea aparte del de `cleaning` (dos copias en memoria de la
misma lista). Es lo que ya hace `cleaning` frente a `features/properties`, y el coste —una
página de 100 filas— no justifica un módulo compartido de catálogo en este change.

### D7 — Dos mutaciones, sin parcheo optimista, invalidando sólo el prefijo de recomendaciones

**Chosen:** `use-decide-recommendation.ts` y `use-generate-recommendations.ts`, ambos con
`retry: false` y con `invalidateQueries({ queryKey: pricingKeys.recommendationsPrefix(tenantId) })`
en **`onSettled`** —también cuando fallan—, siguiendo `use-assign-cleaning-task.ts`.
Ninguno parchea la caché: aprobar saca la fila del filtro `RECOMMENDED`, y la respuesta del
`PATCH` es una recomendación suelta que no sabe nada de `total` ni de la página; sólo un
refetch del prefijo refleja eso sin enumerar combinaciones de filtro y página (R3.4).

`generate` invalida el **mismo** prefijo y también en `onSettled`: un barrido que devuelve
error puede haber escrito filas antes de fallar, y el contrato no permite distinguirlo.
Ninguna de las dos toca `pricingKeys.rules` (R3.5): ni decidir ni regenerar escriben una
regla.

Rejected: `onSuccess` en vez de `onSettled` — deja en pantalla una fila que el backend acaba
de rechazar por `409`, que es justo el caso que R3.6 hace visible.

**Las dos mutaciones no reciben su entrada igual, y eso decide quién las protege del tenant
equivocado** (enmienda del gate de `/sdd:run` del 2026-08-23, a raíz de un `DESIGN-CONFLICT` del
arquitecto). `use-decide-recommendation` recibe `{recommendationId, status}` en `mutate()`, así
que sólo depende de `PricingDataSource` y la vista media todo lo que entra. `use-generate-
recommendations` **no recibe nada**: lee `recommendations.propertyId` del store directamente,
que es lo que vuelve estructural el «sin ofrecer un segundo selector de vivienda» de R4.1 —no
hay parámetro por el que colar otro alcance, y en particular no el `propertyId` de la pestaña de
reglas—. El precio de esa elección es que el guardia `staleFilters` de D11, que vive en la vista,
**no la cubre**: la vista filtra lo que entra en sus *queries*, y esta mutación no pasa por ahí.
Por eso el hook lleva su propio guardia, `filtersTenantId === tenantId ? (propertyId ?? null) :
null`, evaluado en el momento del `mutate()` contra el `tenant_id` vivo de `useAuth()` y no
dependiente de que el efecto `adoptTenant` ya haya corrido.

De modo que **la comprobación de tenant obsoleto vive en dos sitios, a propósito**: en
`pricing-view.tsx` para las lecturas (D11) y en `use-generate-recommendations.ts` para esta
escritura. Quien implemente la tarea 7.9 no debe suponer que la mutación está desprotegida ni
retirarle el guardia por parecer duplicado: cubren caminos distintos.

### D8 — Una sola escritura en vuelo, y quién se deshabilita

**Chosen:** la vista posee las dos mutaciones y expone `isBusy = decide.isPending ||
generate.isPending`. Mientras `isBusy`, se deshabilitan **todos** los botones de confirmación
de decisión de todas las filas y el de regenerar (R3.3, R4.4). La fila cuya decisión vuela
muestra además su propio texto «Enviando…» (`decide.variables?.recommendationId === row.id`).

Dos razones, ambas del precedente: iniciar una segunda mutación desasocia la primera y se
traga su rechazo, que R3.6/R3.8 hacen obligatorio; y hay **una sola región viva**
(`role="status" aria-live="polite"`, design D11 de `cleaning-manager-view`), de modo que dos
escrituras simultáneas se pisarían el anuncio. Se deshabilita el botón, nunca el `<select>`
de un filtro, para no robar el foco a quien esté navegando con teclado.

### D9 — Copia de error elegida por status HTTP, con rama `409` propia

**Chosen:** `features/pricing/lib/pricing-error.ts`, con la forma de
`features/cleaning/lib/assign-error.ts` —una tabla `Record<number, string>` y un
`?? GENERIC`, eligiendo por `ApiError.status` y **jamás** por `ApiError.message`, `code` o
`details` (R3.7)—. Tres tablas, porque los tres caminos no comparten códigos alcanzables:

| camino | 403 | 404 | 409 | 422 | genérico |
|---|---|---|---|---|---|
| decidir (`PATCH`) | sí | sí | **sí** | sí | sí |
| regenerar (`POST /generate`) | sí | — | — | sí | sí |
| leer (listados) | sí | — | — | — | sí |

El `409` es el caso propio de esta pantalla —«esa recomendación ya no está en el estado que
creías»— y tiene copia distinta del genérico (R3.6). `mapIncidentsError`
(`features/incidents/lib/error-mapping.ts`) **no** sirve: no tiene rama `409`.

Sobre el `401`: no lleva rama, igual que `assign-error.ts`. Lo resuelve el cliente HTTP con
su refresh de un intento y, si no recupera, la expiración de sesión; una copia propia aquí
competiría con esa redirección.

**Añadido sobre la letra de R2**: el camino de lectura distingue `403` del error genérico.
Es una string más por locale y evita que un `CLEANER` que llegue a `/pricing` (ver D17) vea
«vuelve a intentarlo en unos segundos» ante algo que no va a cambiar reintentando.

### D10 — Pestañas ARIA hechas a mano, sin dependencia nueva, y sólo el panel activo montado

**Chosen:** `features/pricing/components/pricing-tabs.tsx`: un `role="tablist"` con dos
`<button role="tab">` (`aria-selected`, `aria-controls`, roving `tabIndex`, flechas
izquierda/derecha + Home/End) y un único `role="tabpanel"` con `aria-labelledby`. Se monta
**sólo el panel activo** (render condicional, no `hidden` por CSS), de modo que la query de
la pestaña inactiva no se dispara hasta que alguien la abre (R2.1, R5.1); al volver, la
caché de TanStack Query la sirve sin red.

Es la misma postura que el árbol ya tomó con `<select>` nativo en `cleaning-filters.tsx`
(«no hay primitiva `Select` en `components/ui/`»): resolver con la plataforma antes que con
una dependencia. Y el coste de la alternativa no es sólo el paquete: `node_modules` vive en
un volumen de Docker (`frontend_node_modules`), así que añadir una dependencia obliga a
reinstalar en el stack de cada worktree vivo.

Vive en la feature y no en `components/ui/` por la norma del propio árbol (extraer al tercer
consumidor); hoy sería el primero.

Rejected: `@radix-ui/react-tabs` + primitiva shadcn — dependencia nueva y reinstalación en
todos los stacks para ~50 líneas de patrón estándar.
Rejected: dos botones con `aria-pressed` y sin semántica de pestaña — R1.1 pide pestañas, y
un lector de pantalla no anunciaría «pestaña 1 de 2».
Rejected: montar los dos paneles y ocultar uno — dispara las dos queries en la carga, contra
la letra de R2.1/R5.1.

### D11 — Un store de UI con dos rebanadas de filtros independientes

**Chosen:** `state/use-pricing-ui-store.ts` (Zustand), con `tenantId`, `activeTab:
"recommendations" | "rules"` y **dos rebanadas separadas**: `recommendations {propertyId,
dateFrom, dateTo, status, page}` y `rules {propertyId, active, page}`. Se heredan las dos
invariantes de `use-cleaning-filters-store.ts`: el **reset a página 1 vive dentro de cada
setter**, y `adoptTenant` devuelve el store entero a su estado inicial cuando cambia el
tenant, para que el `propertyId` de una sesión no viaje a la siguiente
(`steering/security.md` regla 1, lado frontend). La vista replica el guardia `staleFilters`
de `cleaning-view.tsx`, que cubre el primer render —antes de que el efecto adopte el
tenant— para que la primera petición no salga con el filtro de la sesión anterior.

**Las dos rebanadas no comparten nada, ni siquiera `propertyId`.** Compartir la página sería
un bug obvio (página 3 de recomendaciones al abrir reglas); compartir la vivienda es un bug
sutil y peor: R4.1 manda enviar a `POST /generate` «el `property_id` del filtro activo», y
si ese filtro lo hubiera fijado por última vez la pestaña de reglas, una regeneración
barrería en silencio un alcance distinto del que la usuaria está mirando.

`setActiveTab` no toca ninguna rebanada: cada pestaña conserva su página y sus filtros.

Rejected: la pestaña activa en `?tab=` — descartado ya en el proposal (segunda fuente de
verdad, sin enlace entrante).
Rejected: dos stores — la propiedad de tenant y su reset tendrían que coordinarse entre los
dos, y esa coordinación es exactamente lo que la regla 1 no quiere repartida.

### D12 — Confirmación en dos pasos dentro de la fila, sin modal

**Chosen:** el grupo de botones de la fila conmuta a una pregunta en línea:
«¿Aprobar este precio? [Confirmar] [Cancelar]», con el estado (`pendingMove: DecisionStatus
| null`) local a la fila. La confirmación es lo que dispara la mutación (R3.3). El texto de
la pregunta es distinto por movimiento, así que la usuaria confirma *qué* está haciendo y no
un genérico «¿seguro?».

No hay `AlertDialog` en el árbol y `window.confirm` queda descartado —bloquea el hilo, no
pasa por i18next del mismo modo que el resto de la UI, y obliga a stubbearlo en cada test—.
La forma en línea es la misma que ya usa `assign-cleaner-control.tsx` (elegir y luego
confirmar) y funciona en móvil sin trampa de foco que construir.

Al confirmar, el par de botones se sustituye por el texto de envío; al asentarse la
mutación, la fila desaparece o cambia de estado por la invalidación de D7.

Rejected: construir un `AlertDialog` sobre `@radix-ui/react-dialog` (ya presente vía
`sheet.tsx`) — superficie nueva compartida, con trampa de foco y `aria-modal` que verificar,
para un change que no la necesita en ningún otro sitio.

### D13 — `legalMoves(status)`: mapa de affordance, no autoridad

**Chosen:** `features/pricing/lib/decision-moves.ts` con
`legalMoves(status): readonly DecisionStatus[]`, derivado de un
`Record<PriceRecommendationStatus, readonly DecisionStatus[]>` exhaustivo:
`RECOMMENDED → ["APPROVED", "REJECTED"]`, `APPROVED → ["APPLIED_EXTERNAL"]`, y `DRAFT`,
`APPLIED_EXTERNAL`, `REJECTED → []` (R3.1, R3.2). Una fila sin movimientos no pinta botones.

Sí, duplica la tabla de transiciones del backend. Se declara igual que `cleaning` declara el
suyo («esta reducción es una comodidad, no la autoridad»): el backend valida antes de mutar
y contesta `409`, y esta pantalla tiene copia propia para ese `409` precisamente porque
asume que su mapa puede quedarse atrás. Al ser un `Record` exhaustivo sobre la unión
generada, un sexto estado en el backend rompe el build al regenerar el contrato.

### D14 — Dinero como cadena, día en UTC, y ningún `created_at` en pantalla

**Chosen:** `features/pricing/lib/format.ts` con dos funciones:

- `fmtDecimal(value: string, locale: string): string` — el `fmtCost` de
  `incident-detail-sections.tsx:18-29`: `Number(value)` **sólo para formatear**,
  `toLocaleString(locale, {minimumFractionDigits: 2, maximumFractionDigits: 2})`, y la
  cadena original si el número no es finito. Sin símbolo ni código de moneda (R6.1, R6.2):
  ninguna respuesta de pricing trae `currency`. Ninguna comparación ni aritmética toca estos
  valores en el cliente.

  **El `locale` es un parámetro, y ahí esta decisión se separa de `fmtCost`** (enmienda
  acordada en el gate de `/sdd:run` del 2026-08-23). La redacción original de D14 decía
  «literalmente» y fijaba `toLocaleString(undefined, …)`; `undefined` es el locale del
  *runtime*, no el de i18next, de modo que una usuaria con el navegador en inglés que elige
  español en la aplicación vería `1,234.50` en una pantalla por lo demás en español — contra
  la letra de R6.2, «con el separador decimal del locale activo». Además hacía **inescribible**
  el test que la propia tarea 3.1 exige («separador decimal de ES vs EN»): sin argumento no hay
  dos locales que comparar dentro de un proceso. Los llamantes pasan `i18n.language`, que es
  exactamente lo que `cleaning-task-row.tsx` ya hace para sus fechas, y así `fmtDecimal` y
  `fmtDay` comparten firma. `fmtCost` de `incidents` conserva su `undefined` y no se toca: es
  el mismo defecto latente en una feature entregada, y arreglarlo allí queda fuera del alcance
  de este change (candidato a change futuro).
- `fmtDay(isoDay: string, locale: string): string` — `Intl.DateTimeFormat(locale,
  {dateStyle: "medium", **timeZone: "UTC"**})` sobre `new Date(isoDay)`.

El `timeZone: "UTC"` es la parte que no se puede olvidar y es la razón de que esto sea una
decisión: `new Date("2026-08-23")` se parsea como medianoche **UTC**, así que formatearlo con
la zona local del navegador imprime el día anterior en cualquier zona al oeste de UTC. R6.3
pide «sin conversión de zona», y ésta es la forma de cumplirlo sin trocear la cadena a mano.

`max_daily_change_pct` se formatea con `fmtDecimal` y su etiqueta localizada lleva el `%`;
el número no lo lleva incrustado.

**No se muestra ningún `created_at`** en ninguna de las dos pestañas: R2.4 y R5.2 enumeran
los campos y no está en ninguna de las dos listas, y R2.6 prohíbe marcas temporales de
decisión. La segunda mitad de R6.3 («cualquier `created_at` que se muestre…») queda por
tanto sin implicación en este diseño, y no se escribe un `fmtUtc` que nadie llama.

### D15 — Las cinco etiquetas de estado, derivadas de un `Record` exhaustivo

**Chosen:** `features/pricing/lib/recommendation-status.ts` declara
`RECOMMENDATION_STATUS_ORDER` a partir de las claves de un `Record<PriceRecommendationStatus,
…>` exhaustivo, en el orden canónico de PRD §7.18 (`DRAFT`, `RECOMMENDED`, `APPROVED`,
`APPLIED_EXTERNAL`, `REJECTED`). Esa constante alimenta tres consumidores: el desplegable del
filtro de estado, la insignia de la fila, y el test de contrato de locales.

El tono de la insignia sale de `RECOMMENDATION_STATUS_TONE`, un
`Record<PriceRecommendationStatus, Tone>` en este mismo módulo, y las clases del tono vienen
del módulo compartido que crea D22 — no de una copia local.

El test se escribe con el patrón de `features/properties/locales/properties-locale.test.ts`,
no con el de `reservations`: aquél deriva la lista de un `Record` tipado y por tanto el
compilador la mantiene completa; el de `reservations` transcribe un array a mano, que valida
las traducciones contra sí mismo y daría verde a un estado que la lista se dejase. Con el
`Record`, R6.4 —incluido `DRAFT`, que nadie produce— queda garantizado por construcción.

`catalog-parity.test.ts` recorre `NAMESPACES` y compara los conjuntos de claves ES/EN, así
que una clave presente en un idioma y ausente en el otro sale en rojo sola en cuanto el
namespace esté registrado (D19). Lo que ese test **no** sabe es si hay una clave por valor de
enum; para eso está el de arriba.

### D16 — `explanation`: texto literal, nunca marcado

**Chosen:** se pinta como hijo de texto de un elemento (`{recommendation.explanation}`), con
etiqueta localizada alrededor y sin traducir ni parsear (R2.7). React escapa por defecto, así
que el requisito se reduce a una prohibición explícita —**ningún `dangerouslySetInnerHTML`
en esta feature**— y a un test que renderiza una `explanation` con marcado dentro
(`Season (<b>x</b>) +10.00%`) y comprueba que el texto aparece literal y que no se ha creado
ningún elemento.

Es el sumidero de texto libre de la regla 11 de `steering/security.md` por una parte concreta:
el `name` que la manager escribió en una temporada o un evento es lo único de la frase que la
plantilla del backend no compone. Conviene que conste que la regla 11 gobierna **columnas y
sus escritores**, no el renderizado; esta decisión es su lectura en el frontend, no una cita
de una cláusula que exista allí.

La frase es larga —el ejemplo canónico de la spec ocupa cuatro líneas— y la pantalla es
mobile-first, así que va **plegada dentro de un `<details>`** con un `<summary>` localizado
(«Ver el cálculo» / «Show the calculation»), cerrado por defecto (D23).

### D17 — El espejo de permisos, y lo que este change no arregla

**Chosen:** `frontend/lib/auth/permissions.ts` amplía la unión a
`Permission = "MANAGE_CLEANING_TASKS" | "MANAGE_PRICE_RECOMMENDATIONS"` y concede la nueva a
**`TENANT_OWNER` y `PROPERTY_MANAGER`** (R7.1), que es lo que `policy.py:293-294` y `324-325`
les dan. `SUPER_ADMIN`, `CLEANER` y `TECHNICIAN` siguen con `[]`. Los tres botones de decisión
y el de regenerar se ocultan tras `useHasPermission("MANAGE_PRICE_RECOMMENDATIONS")`, como
`cleaning-task-row.tsx` hace con el suyo. El mapa sigue siendo **parcial y declarado como
tal**: sólo enumera lo que el frontend usa para ocultar (R7.3).

`lib/auth/permissions.test.tsx` gana los casos simétricos a los de cleaning: concedida a los
dos roles, denegada a los otros tres, y denegada sin usuario.

**Lo que NO hace, y hay que decirlo**: el registro de ruta no lleva roles
(`route-registry.test.ts:110`: «carries only shell metadata»), así que el sidebar enseña
`/pricing` a todo el mundo y un `CLEANER` que entre recibirá `403` del listado. Este diseño lo
convierte en la copia localizada de `403` de D9 en vez de un error genérico, que es todo lo
que cabe hacer sin espejar también `READ_PRICE_RECOMMENDATIONS` y sin dar filtrado por rol al
shell — ninguna de las dos cosas está en el alcance de R7, y la segunda es una capacidad del
shell, no de esta pantalla.

### D18 — Paginador propio, porque el de `cleaning` está atado a su namespace

**Chosen:** `features/pricing/components/pricing-pagination.tsx`, misma forma que
`CleaningPagination` (presentacional puro: recibe `page`, `totalPages`, `total`,
`onPageChange`, y no toca la red), contra el namespace `pricing`. La reutilización directa no
es posible: `CleaningPagination` llama `useTranslation("cleaning")` en su cuerpo, así que sus
textos saldrían del catálogo equivocado. Un solo componente compartido, parametrizado por
namespace, es la extracción que la norma del árbol reserva para el tercer consumidor.

Se usa en las dos pestañas con `per_page` fijo en 20 (el defecto del backend) y sin selector
de tamaño de página, que ninguna requisito pide.

### D19 — El namespace `pricing`, en sus cuatro puntos

**Chosen:** `frontend/locales/es/pricing.json` y `frontend/locales/en/pricing.json`,
registrados en `lib/i18n/resources.ts` en los cuatro sitios: el `import` por locale, la lista
`NAMESPACES`, y la entrada dentro de `resources.es` y `resources.en` (R6.5). Olvidar uno deja
el namespace mudo en un idioma; `catalog-parity.test.ts` sólo empieza a vigilarlo una vez
está en `NAMESPACES`.

Estructura de claves, siguiendo `cleaning.json`: `tabs.*`, `separator`,
`recommendations.{list,columns,empty,error}.*`, `status.{DRAFT,…}`, `identity.*`,
`filters.*`, `pagination.*`, `decide.{approve,reject,markPublished,confirm,cancel,sending,
success}`, `decide.error.{forbidden,notFound,conflict,invalid,generic}`,
`generate.{button,sending,report}`, `generate.error.*`, `rules.{list,columns,scope,empty,
error}.*`, `read.error.{forbidden,generic}`.

Falta una en esa lista, y se añade aquí en vez de dejarla como invención sin registrar
(enmienda del gate de `/sdd:run` del 2026-08-23, señalada por el panel de i18n):
**`decide.confirmQuestion.{APPROVED,REJECTED,APPLIED_EXTERNAL}`**. La pide D12, que no quiere un
«¿seguro?» genérico sino que la usuaria confirme *qué* está haciendo, y por tanto necesita una
pregunta distinta por movimiento —«¿Aprobar este precio?», «¿Rechazar este precio?», «¿Marcar
este precio como publicado?»—. Que sean tres y distintas lo comprueba el test de contrato de
locales, derivado de `DecisionStatus` y no transcrito.

**El aviso del informe de generación no puede afirmar que el barrido fue completo** (R4.3):
la copia enseña los cuatro contadores y ni una palabra de éxito o corrección —«Generación
ejecutada: {{created}} creadas, {{updated}} actualizadas, {{preserved}} conservadas,
{{skipped}} omitidas.» / «Generation ran: …»—, porque el contrato no expone `failed` y «un
barrido con agujeros se ve verde desde la API».

### D20 — El filtro `active` obliga a mirar el tipo de `query` del cliente compartido

**Chosen:** `GET /api/v1/pricing-rules` declara `active?: boolean | null`, pero
`RequestOptions.query` de `lib/api/client.ts:84` está tipado
`Record<string, string | number | null | undefined>` y el argumento real es la **intersección**
de ese `Record` con el `QueryFor<…>` de la operación — de modo que un `boolean` no satisface
al primero y un `string` no satisface al segundo. Ninguna llamada del árbol pasa hoy un
booleano de query, así que esta feature es la primera que lo toca. En runtime no hay problema:
`appendQuery` hace `String(value)` y FastAPI parsea `true`/`false`.

El arreglo es ensanchar el tipo compartido a
`Record<string, string | number | boolean | null | undefined>` y añadir a
`lib/api/client.test.ts` el caso de que un booleano se serializa como `active=true`. Es una
línea de infraestructura compartida, sin cambio de comportamiento.

**Se verifica antes de tocar nada**: la primera tarea que use el filtro corre
`npm run typecheck`; si compila sin el ensanchado, el ensanchado no se hace. Se escribe aquí
porque descubrirlo en mitad de la tarea del boundary parece un bug de la feature y no lo es.

Rejected: castear en el punto de llamada — mete un `as unknown as` en la costura de datos por
un límite del tipo, no del contrato.
Rejected: quitar el filtro `active` — es requisito (R5.1).

### D21 — La página, y el placeholder que se va

**Chosen:** `app/(workspace)/pricing/page.tsx` conserva su `generateMetadata` desde
`routeMetadata("pricing")` y pasa a renderizar `<PricingView />` desde `@/features/pricing`
(R1.4), exactamente como `app/(workspace)/cleaning/page.tsx`. No se toca
`route-registry.ts`, ni `locales/{es,en}/navigation.json`, ni se da de alta ningún descriptor
(R1.2). El inventario de `sdd/specs/frontend-foundation.md` pasa de 12 placeholders a 11 y de
diez superficies funcionales a once — verificado hoy: 12 páginas con `RoutePlaceholder` en el
árbol. Eso lo escribe `/sdd:archive`, no este change.

### D22 — La paleta de tonos se extrae a un módulo compartido (resuelve OQ1)

**Chosen:** `frontend/lib/ui/status-tone.ts` **(nuevo)** con
`export type Tone = "green" | "blue" | "amber" | "red" | "gray"` y
`export const TONE_BADGE_CLASS: Record<Tone, string>`, y los tres consumidores lo importan.

**Antes hay que corregir dónde está hoy la segunda copia, porque el árbol miente sobre ella.**
El comentario de `features/cleaning/lib/task-status.ts` dice que su mapa es copia del
`STATE_BADGE_CLASS` de `features/dashboard/components/property-card.tsx` — y ahí ya no está:
`properties-web` (design D2) lo movió a `frontend/components/property-state-badge.tsx`, donde
vive **privado al módulo** (no se exporta) junto a `StateColorGroup`, que sí. Así que las
copias del mapa grupo → clases Tailwind son exactamente dos, y están **idénticas cadena a
cadena** (comprobado con las dos declaraciones enfrentadas: las cinco claves y los cinco
valores coinciden). Este change es el tercer consumidor, que es el disparador que
`task-status.ts` escribió para sí mismo.

El movimiento, y por qué no rompe nada:

- `components/property-state-badge.tsx` borra su `STATE_BADGE_CLASS` privado e importa
  `TONE_BADGE_CLASS`; `StateColorGroup` se queda como alias de `Tone`, porque lo consumen
  `property-state-badge.test.tsx` y la feature `properties`.
- `features/cleaning/lib/task-status.ts` borra el valor y **conserva el nombre**
  (`export const STATUS_BADGE_CLASS = TONE_BADGE_CLASS`), con `StatusColorGroup` como alias de
  `Tone`, de modo que `cleaning-task-row.tsx` y `task-status.test.ts` siguen compilando sin
  tocarlos. Su comentario obsoleto se corrige en el mismo movimiento.
- `property-state-badge.test.tsx` no se toca: su `EXPECTED_CLASS` es una expectativa local de
  las cadenas renderizadas y no depende de dónde viva el mapa.

**Sin cambio de comportamiento**, y ésa es la condición: los tests de `cleaning`,
`property-state-badge` y `properties` deben pasar sin editarlos. Si alguno cambia, la
extracción no fue equivalente y se revierte.

El tono **por estado de recomendación** es local a `features/pricing` y no se comparte: es la
lectura de esta feature sobre el ciclo de una recomendación, no una paleta.
`RECOMMENDATION_STATUS_TONE`: `DRAFT → gray`, `RECOMMENDED → amber` (espera decisión),
`APPROVED → blue` (decidida, pendiente de publicar), `APPLIED_EXTERNAL → green` (cerrada),
`REJECTED → red`. Nada de esto son los colores de PRD §9.1, que son de estado operacional de
vivienda y viven en `PropertyStateBadge` (R6.7); es la misma reutilización de paleta que
`cleaning` ya declara como `ASSUMPTION`, y se anota igual.

Rejected: tercera copia local — cero riesgo, y deja la norma incumplida justo cuando se
dispara.
Rejected: insignia sin color — cumple la letra de R6.7, pero una cola de decisión sin
distinción visual de estado deja de leerse como una cola.
Rejected: importar `STATE_BADGE_CLASS` desde `property-state-badge.tsx` — es privado al
módulo, y exportarlo desde un componente de insignia de *vivienda* para que lo use pricing
sería peor acoplamiento que el módulo compartido.

### D23 — La `explanation` va plegada en un `<details>` (resuelve OQ2)

**Chosen:** `<details>` con `<summary>` localizado, cerrado por defecto, dentro de la tarjeta
de la fila. Nativo del navegador: teclado, `aria-expanded` y el anuncio de plegado/desplegado
los da la plataforma, sin estado propio, sin dependencia y sin trampa de foco.

La fila queda legible de un vistazo —vivienda, día, precio, estado, controles— y el porqué
está a un clic para quien lo quiera. El `<summary>` es la «etiqueta localizada alrededor» que
R2.7 pide, y el contenido sigue siendo la frase literal en inglés, como hijo de texto (D16).

Rejected: siempre desplegada — cuatro líneas más por fila, y la cola deja de leerse de arriba
abajo, que es su razón de ser.
Rejected: truncar con «ver más» propio — reimplementa `<details>` con más código y peor
accesibilidad.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Ruta | `frontend/app/(workspace)/pricing/page.tsx` | Sustituye `RoutePlaceholder` por `<PricingView />`; `generateMetadata` intacto (D21) |
| Datos — contrato | `frontend/features/pricing/data/dto.ts` **(nuevo)** | `PricingPage<T>`, `PriceRecommendation`, `PricingRule` (con `modifierCounts`), `GenerationReport`, `PropertySummary`, `DecisionStatus`, filtros (D2, D3, D4) |
| Datos — puerto | `frontend/features/pricing/data/pricing-source.ts` **(nuevo)** | Interfaz `PricingDataSource`: `listRecommendations`, `listRules`, `listProperties`, `decideRecommendation`, `generateRecommendations` |
| Datos — adaptador | `frontend/features/pricing/data/http/http-pricing-source.ts` **(nuevo)** + `.test.ts` | Mapeo `items`→`PricingPage`, `totalPages` calculado, `status`/`date_from`/`date_to` como query, `countEntries` de los cinco JSONB (D2, D3, D20) |
| Datos — composición | `frontend/features/pricing/data/index.ts` **(nuevo)** | `getPricingDataSource()` con `createAuthenticatedClients` (D1) |
| Hooks | `frontend/features/pricing/hooks/query-keys.ts` **(nuevo)** + `.test.ts` | Claves tenant-scoped + normalizadores de filtros (D6) |
| Hooks | `frontend/features/pricing/hooks/use-pricing-data.ts` **(nuevo)** + `.test.tsx` | `useRecommendations`, `usePricingRules`, `usePropertyDirectory` con `retryPolicy` |
| Hooks | `frontend/features/pricing/hooks/use-decide-recommendation.ts` **(nuevo)** + `.test.tsx` | `retry: false`, invalidación de prefijo en `onSettled` (D7) |
| Hooks | `frontend/features/pricing/hooks/use-generate-recommendations.ts` **(nuevo)** + `.test.tsx` | Ídem, cuerpo `{property_id}` leído del store, **con guardia de tenant obsoleto propio** (D7, D11, R4.1) |
| Lib | `frontend/features/pricing/lib/property-directory.ts` **(nuevo)** + `.test.ts` | `portfolio \| pending \| unavailable \| resolved` (D5) |
| Lib | `frontend/features/pricing/lib/pricing-error.ts` **(nuevo)** + `.test.ts` | Tres tablas status→clave, sin leer el cuerpo (D9) |
| Lib | `frontend/features/pricing/lib/decision-moves.ts` **(nuevo)** + `.test.ts` | `legalMoves()` sobre `Record` exhaustivo (D13) |
| Lib | `frontend/features/pricing/lib/recommendation-status.ts` **(nuevo)** | Orden canónico y `RECOMMENDATION_STATUS_TONE` (D15, D22) |
| Paleta compartida | `frontend/lib/ui/status-tone.ts` **(nuevo)** | `Tone` + `TONE_BADGE_CLASS`, extraídos de las dos copias idénticas (D22) |
| Paleta compartida | `frontend/components/property-state-badge.tsx` | Borra su `STATE_BADGE_CLASS` privado e importa el compartido; `StateColorGroup` queda como alias (D22) |
| Paleta compartida | `frontend/features/cleaning/lib/task-status.ts` | Ídem, conservando el nombre `STATUS_BADGE_CLASS`; se corrige su comentario obsoleto sobre `property-card.tsx` (D22) |
| Lib | `frontend/features/pricing/lib/format.ts` **(nuevo)** + `.test.ts` | `fmtDecimal`, `fmtDay` con `timeZone: "UTC"` (D14) |
| Estado | `frontend/features/pricing/state/use-pricing-ui-store.ts` **(nuevo)** + `.test.ts` | Pestaña activa + dos rebanadas de filtros + `adoptTenant` (D11) |
| Componentes | `frontend/features/pricing/components/pricing-view.tsx` **(nuevo)** + `.test.tsx` | Orquesta pestañas, tenant staleness **de las lecturas** (la escritura de `generate` lleva el suyo, D7), `isBusy` (D8, D10) |
| Componentes | `.../pricing-tabs.tsx` **(nuevo)** + `.test.tsx` | `tablist`/`tab`/`tabpanel` con teclado (D10) |
| Componentes | `.../recommendations-panel.tsx` **(nuevo)** + `.test.tsx` | Filtros, regenerar, región viva única, lista, paginación |
| Componentes | `.../recommendation-filters.tsx` **(nuevo)** + `.test.tsx` | Vivienda, rango de fechas (`<input type="date">`), estado |
| Componentes | `.../recommendation-row.tsx` **(nuevo)** + `.test.tsx` | Tarjeta: vivienda, `date`, precio, estado, `explanation` en `<details>`, controles (D16, D23) |
| Componentes | `.../decision-controls.tsx` **(nuevo)** + `.test.tsx` | Los tres movimientos con confirmación en dos pasos (D12, D13) |
| Componentes | `.../rules-panel.tsx`, `.../rule-filters.tsx`, `.../rule-row.tsx` **(nuevos)** + tests | Listado de reglas, filtros `property_id`/`active`, ámbito «toda la cartera» (D5, R5) |
| Componentes | `.../pricing-pagination.tsx` **(nuevo)** + `.test.tsx` | Copia contra el namespace `pricing` (D18) |
| Barril | `frontend/features/pricing/index.ts` **(nuevo)** | Exporta sólo `PricingView` |
| i18n | `frontend/locales/es/pricing.json`, `frontend/locales/en/pricing.json` **(nuevos)** | Namespace completo (D19) |
| i18n | `frontend/lib/i18n/resources.ts` | Los cuatro puntos de registro (D19, R6.5) |
| i18n | `frontend/features/pricing/locales/pricing-locale.test.ts` **(nuevo)** | Los cinco estados en ES y EN, derivados del `Record` (D15, R6.4) |
| Permisos | `frontend/lib/auth/permissions.ts` + `permissions.test.tsx` | `MANAGE_PRICE_RECOMMENDATIONS` a `TENANT_OWNER` y `PROPERTY_MANAGER` (D17, R7) |
| Cliente HTTP | `frontend/lib/api/client.ts` + `client.test.ts` | **Condicional** (D20): ensanchar `query` a `boolean` si `typecheck` lo exige |
| Backend | — | **Nada.** Contrato congelado; no hay `make openapi` ni `npm run api:generate` en este diff |

## Data & interfaces

**Cambios de esquema, endpoints, eventos o variables de entorno: ninguno.** Este change es
sólo frontend y consume cinco operaciones ya publicadas y versionadas en
`frontend/lib/api/generated/openapi.d.ts`. No hay regeneración de contrato, así que el
workflow `frontend-api-contract` no tiene deriva que detectar.

Interfaces internas nuevas (todas en `frontend/features/pricing/data/`):

```ts
export interface PricingPage<T> {
  items: T[]; total: number; page: number; perPage: number; totalPages: number;
}

export type PriceRecommendationStatus = components["schemas"]["PriceRecommendationStatus"];
export type DecisionStatus =
  Extract<PriceRecommendationStatus, "APPROVED" | "REJECTED" | "APPLIED_EXTERNAL">;

/** Sin current_price, sin confidence, sin created_at — D3. */
export interface PriceRecommendation {
  id: string; propertyId: string; pricingRuleId: string;
  date: string;                 // YYYY-MM-DD
  recommendedPrice: string;     // decimal como cadena
  status: PriceRecommendationStatus;
  explanation: string;          // inglés, literal, texto (D16)
}

export interface ModifierCounts {
  weekday: number; leadTime: number; occupancy: number; seasonality: number; event: number;
}

/** Sin el interior de los cinco JSONB — D3. */
export interface PricingRule {
  id: string; propertyId: string | null; name: string; active: boolean;
  basePrice: string; minPrice: string; maxPrice: string; maxDailyChangePct: string;
  modifierCounts: ModifierCounts;
}

export interface GenerationReport {
  created: number; updated: number; preserved: number; skipped: number;
}

export interface RecommendationFilters {
  propertyId?: string; dateFrom?: string; dateTo?: string;
  status?: PriceRecommendationStatus;
}
export interface PricingRuleFilters { propertyId?: string; active?: boolean }

export interface PricingDataSource {
  listRecommendations(tenantId: string, filters: RecommendationFilters, page: number):
    Promise<PricingPage<PriceRecommendation>>;
  listRules(tenantId: string, filters: PricingRuleFilters, page: number):
    Promise<PricingPage<PricingRule>>;
  listProperties(tenantId: string): Promise<PropertySummary[]>;
  decideRecommendation(tenantId: string, recommendationId: string, status: DecisionStatus):
    Promise<PriceRecommendation>;
  generateRecommendations(tenantId: string, propertyId: string | null):
    Promise<GenerationReport>;
}
```

El parámetro de query del filtro de estado se envía con el nombre **`status`** (el parámetro
de Python es `status_filter` con `Query(alias="status")`, `recommendations_router.py:95-97`),
que es además cómo lo declara el cliente tipado.

## Cobertura de requisitos

| Req | Dónde se resuelve |
|---|---|
| R1.1 pestaña Recomendaciones por defecto | D10, D11 (`activeTab` inicial `"recommendations"`) |
| R1.2 sin descriptor nuevo, `match` intacto, sin claves de navegación | D21 (no se toca `route-registry.ts` ni `navigation.json`) |
| R1.3 pestaña en el store, no en la URL | D11 |
| R1.4 fuera `RoutePlaceholder` | D21 |
| R2.1 query con filtros y paginación | D2, D6; nombre `status` verificado contra el router |
| R2.2 sobre `items` y `Math.ceil` | D2 |
| R2.3 `total = 0` → vacío, nunca «1 de 0» | D2 (`totalPages = 0`) + guardia de la vista antes del paginador |
| R2.4 campos por fila | `recommendation-row.tsx` |
| R2.5 sin `current_price` ni `confidence` | D3 (no cruzan el boundary) |
| R2.6 sin marca temporal de decisión | D3, D14 (no hay `created_at` en el DTO ni en pantalla) |
| R2.7 `explanation` como texto | D16, D23 |
| R2.8 tres formas de identidad, catálogo que no tumba la vista | D5 |
| R3.1 / R3.2 movimientos por estado | D13 |
| R3.3 confirmación y control deshabilitado | D12, D8 |
| R3.4 `retry: false`, sin optimismo, prefijo en `onSettled` | D7 |
| R3.5 sólo el prefijo de recomendaciones | D7 |
| R3.6 copia propia del `409` | D9 |
| R3.7 elegir por status, nunca por el cuerpo | D9 |
| R3.8 el `403` es error | D9 (tabla de decidir) |
| R4.1 cuerpo con el `property_id` del filtro activo | D7, D11 (por eso las rebanadas no comparten filtro) |
| R4.2 cuatro contadores + invalidación | D7, D19 |
| R4.3 sin afirmar barrido completo | D19 (redacción fijada) |
| R4.4 `retry: false` y botón deshabilitado | D7, D8 |
| R5.1 listado de reglas con `property_id` y `active` | D2, D6, D20 |
| R5.2 campos por regla y recuentos | D3 (`modifierCounts`) |
| R5.3 «Toda la cartera» | D5 (`portfolio`) |
| R5.4 sin interpretar el JSONB | D3 (`countEntries` no lee valores) |
| R5.5 sin `GET /pricing-rules/{id}` | La interfaz `PricingDataSource` no declara el método |
| R6.1 / R6.2 decimal como cadena, sin moneda | D14 |
| R6.3 `date` sin zona; `created_at` no se muestra | D14 |
| R6.4 cinco etiquetas | D15 |
| R6.5 namespace en cuatro puntos | D19 |
| R6.6 nada sin traducir | D19 + `catalog-parity.test.ts` + test de locales |
| R6.7 sin los colores de PRD §9.1 | D15, D22 (paleta propia por ciclo de recomendación, `ASSUMPTION` anotada) |
| R7.1 permiso a los dos roles | D17 |
| R7.2 no copiar la forma de cleaning | D17 (test explícito de que `TENANT_OWNER` la tiene) |
| R7.3 pista de UX, no autoridad | D17 (`403` sigue siendo error, D9) |

## Risks & mitigations

- **El sobre `items` es el error caro de esta entrada.** Un boundary copiado de
  `reservations`/`cleaning` compila contra `data` y falla en runtime. Mitigación: el tipo se
  llama `PricingPage` y no `PaginatedResponse` (D2), y el primer test del adaptador HTTP fija
  el nombre del campo y el cálculo de `totalPages`, incluido `total = 0 → 0`.
- **Formatear el día con la zona local imprime el día anterior** al oeste de UTC — un bug que
  no se ve desde Madrid. Mitigación: `timeZone: "UTC"` en `fmtDay` (D14) y un test que
  formatea `"2026-01-01"` con `TZ` simulada al oeste.
- **`npm test` en un worktree enlazado da dos ficheros en rojo que no son de este change**
  (`features/provenance/workflow-contract.test.ts` y
  `lib/config/build-identity-contract.test.ts`, `ENOENT` porque el contenedor sólo monta
  `./frontend`). Mitigación: `sdd/project.md` documenta los `docker compose cp` que los
  arreglan; la tarea de verificación los ejecuta antes de leer cifras, y **no** se
  interpretan como regresión. Tampoco hace falta `npm run api:check`: no hay contrato
  regenerado.
- **Deploy skew en el enum.** Un sexto `PriceRecommendationStatus` llegado por la red antes
  de reconstruir el frontend no tiene etiqueta ni movimientos. Mitigación: `legalMoves`
  devuelve `[]` para lo desconocido y la insignia cae a tono neutro; nunca se pinta el
  identificador crudo del enum.
- **Más de 100 viviendas** rompe la resolución de nombres (una sola página de catálogo).
  Mitigación: es la misma `ASSUMPTION` que `cleaning` ya declara, degrada a «identidad no
  disponible» y no a fallo; se anota en el código como `ASSUMPTION`.
- **El botón de regenerar corre sincrónicamente en la petición** y barre hasta 60 días por
  vivienda. Con la cartera del MVP (dos viviendas) es inmediato; con una cartera grande puede
  tardar y no hay `202` ni polling que ofrecer. Mitigación: botón deshabilitado con texto de
  progreso mientras vuela (D8); si algún día molesta, es un cambio del backend y no de esta
  pantalla.
- **El `403` del `CLEANER` que llega por el sidebar** no se puede evitar desde aquí (D17).
  Mitigación: copia localizada propia de `403` en el camino de lectura; el filtrado del
  sidebar por rol queda como carencia conocida del shell.

## Open questions

Ninguna abierta. Las dos que este diseño planteó se resolvieron en el gate del 2026-08-23 y
bajaron a decisiones:

- **OQ1 — paleta de tonos** → **D22**: se extrae `frontend/lib/ui/status-tone.ts` y la
  consumen los tres, honrando el disparador del «tercer consumidor» que el propio árbol
  escribió. De paso se corrige el comentario de `task-status.ts`, que sigue apuntando a
  `features/dashboard/components/property-card.tsx` cuando la segunda copia se mudó a
  `components/property-state-badge.tsx` con `properties-web`.
- **OQ2 — presentación de la `explanation`** → **D23**: plegada en un `<details>` con
  `<summary>` localizado, cerrado por defecto.

Queda **una verificación**, no una decisión: D20 hace el ensanchado de
`RequestOptions.query` en `lib/api/client.ts` condicional a que `npm run typecheck` confirme
que el `boolean` del filtro `active` no compila hoy. Si compila, el ensanchado no se hace. Es
la primera cosa que comprueba la tarea del boundary de reglas.
