# pricing-web

[FE] **la pantalla de precios: la cola de recomendaciones con aprobar/rechazar, y las reglas que las producen en modo lectura**, consumiendo `GET /api/v1/price-recommendations`, `PATCH /api/v1/price-recommendations/{id}`, `POST /api/v1/price-recommendations/generate` y `GET /api/v1/pricing-rules`. La ruta ya existe en el shell pero no muestra datos: `frontend/app/(workspace)/pricing/page.tsx` renderiza `RoutePlaceholder routeId="pricing"`. El backend está entregado y archivado (`revenue-pricing`, `changes/archive/2026-08-18-revenue-pricing/`, spec `specs/revenue-pricing.md`), así que el trabajo es la pantalla y no la negociación del contrato.

Es la primera entrada `[FE]` de la sección `revenue` del sidebar, y la primera pantalla de propietario/manager cuyo valor **es** una mutación.

## Decisión 1: una sola ruta `/pricing`, dos pestañas — no dos rutas, no sólo recomendaciones

**Una pestaña «Recomendaciones» (por defecto) y una pestaña «Reglas» dentro de `/pricing`.** Cerrado, no negociable al llegar. Tres razones, todas verificables:

1. **El registro de ruta ya prometió las dos cosas.** `locales/es/navigation.json` dice de `routes.pricing.description`: *«Reglas y recomendaciones de precios.»*, y `locales/en` *«Pricing rules and recommendations.»*. Dejar las reglas fuera de la pantalla contradiría el texto que el shell ya pinta en su propio placeholder y en los metadatos de la página.
2. **Una segunda ruta cuesta trabajo de shell que las pestañas no cuestan.** La entrada `pricing` es `match: "exact"` (`frontend/features/shell/navigation/route-registry.ts:203-215`). Un `/pricing/rules` obligaría a cambiar `pricing` a `match: "prefix"` —como `properties` (`route-registry.ts:105-113`)—, dar de alta un descriptor nuevo imitando `property-detail` (`route-registry.ts:114-122`: sin `href`, sin `navigationGroup`, con `breadcrumbKeys: crumbs("pricing", "pricing-rules")`) y añadir dos claves i18n por locale. Todo eso para una lista de sólo lectura que nadie va a enlazar desde fuera.
3. **Lo que el manager necesita ver primero es la cola de decisión, no la configuración.** El backend ya la ordena así: las recomendaciones salen `date ASC, id ASC` (`backend/app/pricing/infrastructure/repositories.py:352`), así que la página 1 son las noches más próximas — exactamente la cola que hay que decidir. Las reglas salen `created_at DESC` (`repositories.py:237`) y son el porqué de esa cola: contexto, no tarea. Por eso las recomendaciones son la pestaña por defecto y las reglas la segunda.

**La pestaña activa NO va en la URL.** Vive en el store de UI de la feature (Zustand, que `steering/frontend.md` reserva para «estado ligero de UI»). Un `?tab=` sería una segunda fuente de verdad sobre la misma cosa y no compra nada: no hay ningún enlace entrante a la pestaña de reglas.

## Decisión 2: la mutación de decisión entra; el CRUD de reglas no

**Dentro: `PATCH /api/v1/price-recommendations/{recommendation_id}`, con los tres movimientos legales y no más.** Sin ella esta pantalla no tiene nada que demostrar: `revenue-pricing` es el Modo 1 de PRD §19 —*recomienda, no publica*— y quien publica es una persona; una pantalla que sólo pintase precios recomendados sería un informe, no la mitad humana del modo. A diferencia de `reservations-web` e `incidents-web`, aquí el sólo-lectura no es un alcance más pequeño: es un alcance sin producto.

Los tres movimientos son **un solo endpoint y un solo cuerpo** (`{"status": ...}`), así que entran los tres:

- `RECOMMENDED → APPROVED` y `RECOMMENDED → REJECTED` — los dos botones de la cola.
- `APPROVED → APPLIED_EXTERNAL` — un tercer botón que sólo aparece en filas `APPROVED`. Deja de ser opcional en cuanto entran los otros dos: sin él una fila aprobada es un callejón sin salida en pantalla y el hecho que cierra el Modo 1 —«ya subí este precio a la OTA»— es inalcanzable, aunque el backend lo registre con `TimelineEvent PRICE_UPDATED_EXTERNAL` y acción de auditoría propia (`specs/revenue-pricing.md`, sección «Decisión sobre las recomendaciones»). Coste real: un botón, una etiqueta por locale y una confirmación; ni un endpoint ni un hook más.

**Fuera: `POST /api/v1/pricing-rules` y `PATCH /api/v1/pricing-rules/{rule_id}`.** No por simetría con las entradas `[FE]` anteriores, sino por un coste medible: el formulario de una regla arrastra **toda** la validación de PRD §7.17, que el backend hace cumplir en el dominio y no en el esquema de petición (`backend/app/pricing/api/schemas.py:13-18`: las cinco columnas JSONB están tipadas como contenedores «y nada más», porque su interior es regla de negocio). En concreto habría que replicar en el cliente: `min_price ≤ base_price ≤ max_price`, `max_daily_change_pct` en `[0, 100]` y con dos decimales como máximo, `name` no vacío y ≤ 200 caracteres, y el esquema interior **exacto** de cinco columnas JSONB —`weekday_modifiers` con los siete días en inglés minúscula, `lead_time_rules {days_before, modifier_pct}`, `occupancy_rules {occupancy_pct_above, modifier_pct}`, `seasonality_rules` con días validados contra año bisiesto, y `event_rules` en sus **dos** formas y sólo dos—, más el techo de 50 entradas por array y 100 caracteres por nombre de modificador.

Y el remate, que es lo que convierte esto en inviable y no sólo en caro: **el frontend no puede enseñar cuál de las cinco columnas falló.** El `422` de estos endpoints nombra el campo, pero la norma del proyecto prohíbe pintar el cuerpo del backend —`frontend/features/incidents/lib/error-mapping.ts` mapea `422` a una copia localizada genérica y documenta que «the backend's envelope is **not** read, mapped, or exposed»; `frontend/features/cleaning/lib/assign-error.ts` elige por *status* y nunca por `ApiError.message`—. Un formulario de regla sería entonces, o lógica de negocio en el componente (que `steering/frontend.md` prohíbe en «Don'ts»), o un formulario cuyo único feedback es «no se pudo guardar». Ninguna de las dos cosas cabe aquí; el CRUD de reglas es su propia entrada de roadmap.

**La pestaña de reglas usa `GET /api/v1/pricing-rules` y nada más.** `GET /api/v1/pricing-rules/{rule_id}` **no se consume**: devuelve el mismo `PricingRuleResponse` que ya viene en cada `items[]` del listado (`schemas.py:49-93` y `95-108`), así que no hay detalle que pedir. Queda escrito para que nadie salga a buscar una ruta de detalle que no aporta nada.

## Decisión 3: `POST /generate` sí lleva botón

**Sí, un botón «Regenerar ahora» en la pestaña de recomendaciones.** No es un duplicado del job de Celery: es su puerta manual, y así está diseñado. `specs/celery-jobs.md:25-29` y `181-183` confirman que `generate_price_recommendations` existe como job diario a las **06:00 UTC** con lock de TTL 3 h; y `specs/revenue-pricing.md` («Generación diaria y bajo demanda») dice que el endpoint expone **la misma** generación *«de modo que una regla recién editada surta efecto sin esperar a las 06:00»*. Tres consecuencias que hacen el botón baratísimo:

- **Corre sincrónicamente y devuelve el informe** (`recommendations_router.py:117-134`, docstring: `POST /generate` corre *in the request* y no como tarea encolada, porque R4.5 pide contar filas creadas y actualizadas). No hay `202`, ni job id, ni polling, ni pantalla de progreso: una mutación normal que devuelve `GenerationReportResponse` con cuatro enteros —`created`, `updated`, `preserved`, `skipped` (`schemas.py:248-262`)— que se pintan en un aviso y se van.
- **Es la diferencia entre una pantalla vacía y una demostrable.** En un entorno donde `beat` no ha pasado por las 06:00 todavía (o donde las reglas se acaban de sembrar), `GET /price-recommendations` devuelve `total: 0` y el estado vacío es indistinguible de «no hay reglas». El botón es la única forma de que la pantalla se llene sin esperar a mañana.
- **Cuerpo mínimo**: `{"property_id": uuid | null}` (`schemas.py:234-246`); omitido barre la cartera `ACTIVE` del tenant. Se envía el `property_id` del filtro activo si hay uno, y nada si no — sin un segundo selector.

Precauciones que ya se saben y no hay que redescubrir: `retry: false` (una escritura rechazada no se reintenta, precedente `use-assign-cleaning-task.ts` y `use-checkin.ts`), botón deshabilitado mientras vuela, y **el contador `failed` no existe en el contrato publicado** —`specs/revenue-pricing.md` lo dice sin rodeos: *«un barrido con agujeros se ve verde desde la API»*—, así que el aviso de éxito no puede afirmar que todo fue bien, sólo enseñar los cuatro números que llegaron.

## El contrato, verificado

### Recomendaciones — `backend/app/pricing/api/recommendations_router.py`

- **`GET /api/v1/price-recommendations`** (línea 74) acepta `page` (≥1, ≤100000), `per_page` (1..100, por defecto 20), `property_id`, `date_from`, `date_to` y `status`. **Ojo con el nombre**: el parámetro de Python es `status_filter`, con `Query(alias="status")` (líneas 95-97), así que el parámetro de query es literalmente `status` y es lo que ve el cliente tipado.
- **`PATCH /api/v1/price-recommendations/{recommendation_id}`** (línea 164) acepta **un solo campo**: `DecidePriceRecommendationRequest` = `{"status": PriceRecommendationStatus}`, con `extra="forbid"` (`schemas.py:264-276`). Devuelve el `PriceRecommendationResponse` completo. Códigos: `409` si el movimiento no es uno de los tres legales (con el estado intacto, validado **antes** de mutar), `422` si el valor cae fuera del enum, `404` si la recomendación es de otro tenant o no existe.
- **`POST /api/v1/price-recommendations/generate`** (línea 117) → `GenerationReportResponse`.
- **`PriceRecommendationResponse`** (`schemas.py:166-206`): `id`, `property_id`, `pricing_rule_id`, `date` (día ISO, sin hora), `recommended_price`, `current_price`, `confidence`, `status`, `explanation`, `created_at`. **No hay `updated_at`** —`ASSUMPTION` explícita de la spec, fidelidad a PRD §7.18—, así que **la pantalla no puede decir cuándo se aprobó algo**: ese rastro vive en `AuditLog` y en el `TimelineEvent`, y ninguno de los dos está en esta pantalla. Nada de columnas «decidido hace X».
- **Dos campos que NO se pintan, y es una decisión, no un olvido**: `current_price` es **siempre `null`** mientras el Modo 1 no llame al PMS (spec: *«THE SYSTEM SHALL dejar `current_price` en `NULL`»*), así que una columna «precio actual» sería una columna de guiones; y `confidence` está fijado a `1.00` en la propia entidad porque el cálculo es determinista (spec: *«cualquier otro valor sería adorno»*), así que pintarlo sugiere una incertidumbre que no existe. Los dos entran en el DTO del cliente y no en la UI.
- **`explanation` es la razón de existir de la pestaña**: el precio base, cada modificador en orden con su porcentaje firmado, cada guardrail que recortó y el precio final. **Está redactada en inglés**, desde una plantilla cerrada y sin IA (`specs/revenue-pricing.md`, «Explicación legible y determinista»), así que **no se traduce y no se parsea**: se muestra literal, con etiqueta localizada alrededor. Y se renderiza **como texto, nunca como HTML**: es sumidero de texto libre de la regla 11 de `steering/security.md` —el `name` que la manager escribió en una temporada o un evento es la única parte que la plantilla no compone.

### Reglas — `backend/app/pricing/api/rules_router.py`

- **`GET /api/v1/pricing-rules`** (línea 72) acepta `page`, `per_page` (mismos topes), `property_id` y `active` (bool), combinados con AND.
- **`PricingRuleResponse`** (`schemas.py:49-93`): `id`, `property_id` (**anulable**: `null` significa regla de todo el tenant, aplicable a cada vivienda sin regla propia activa), `name`, `active`, `base_price`, `min_price`, `max_price`, `max_daily_change_pct`, las cinco columnas JSONB (`weekday_modifiers` objeto; `lead_time_rules`, `occupancy_rules`, `seasonality_rules`, `event_rules` arrays de objetos), `created_at`, `updated_at`. Ninguna respuesta lleva `tenant_id`, por diseño.
- Las cinco columnas JSONB llegan al cliente tipado como `Record<string, unknown>` / `Record<string, unknown>[]`. La pestaña de reglas **no interpreta su interior**: enseña el nombre, el ámbito (vivienda o todo el tenant), el estado activo, la banda `min`/`base`/`max`, el tope diario y **cuántos** modificadores hay de cada clase. Contar entradas es seguro; renderizar su interior sería reimplementar el esquema de PRD §7.17, que es justo lo que la decisión 2 deja fuera.

### El sobre de paginación NO es el de los demás módulos

Éste es el error caro de esta entrada, y hay que escribirlo en la primera tarea. Los dos listados de pricing devuelven:

```
{ items: [...], total, page, per_page }
```

(`PricingRulePageResponse`, `schemas.py:95-108`; `PriceRecommendationPageResponse`, `schemas.py:208-232`). **`items`, no `data`. Y no hay `total_pages`.** Todo el resto de la API usa el sobre de PRD §23 con `data` **y** `total_pages`: comprobado en `backend/openapi.json` sobre `CleaningTaskPageResponse` y `PropertyPageResponse`, ambos `['data', 'page', 'per_page', 'total', 'total_pages']`, y es la forma que `reservations-web` documentó como «verbatim». Consecuencias concretas:

- El *boundary* de la feature mapea `items`, y un `boundary.test.ts` copiado de reservations fallará por el nombre del campo. Mejor que falle ahí que en la vista.
- **El número de páginas se calcula en el cliente**: `Math.ceil(total / per_page)`, con `total = 0` resuelto como estado vacío y no como «página 1 de 0». El componente `CleaningPagination` (`frontend/features/cleaning/components/cleaning-pagination.tsx`) recibe `page`, `totalPages` y `total` como props y no toca la red, así que se puede reutilizar el patrón tal cual: lo que cambia es quién calcula `totalPages`, no la pieza.

### El cliente tipado ya lo conoce

`frontend/lib/api/generated/openapi.d.ts` declara las cinco operaciones: `/api/v1/price-recommendations` (línea 450), `/api/v1/price-recommendations/{recommendation_id}` (459), `/api/v1/price-recommendations/generate` (468), `/api/v1/pricing-rules` (479) y `/api/v1/pricing-rules/{rule_id}` (493). El fichero se genera desde `backend/openapi.json` y la CI lo verifica: **no hay tipos que escribir a mano ni nada que regenerar**.

## Los enums: cinco estados, y los cinco necesitan etiqueta

`PriceRecommendationStatus` (`backend/app/pricing/domain/enums.py:7-11`) tiene **cinco** valores: `DRAFT`, `RECOMMENDED`, `APPROVED`, `APPLIED_EXTERNAL`, `REJECTED`.

**Los cinco llevan etiqueta en ES y EN, incluido `DRAFT`**, aunque la spec diga literalmente que *«`DRAFT` no lo produce ni lo consume nadie»* (está en el enum porque PRD §7.18 lo declara). La razón es mecánica: el test de contrato de locales del proyecto recorre los valores del enum **leídos de los tipos generados** —precedente exacto en `frontend/features/reservations/locales/reservations-locale.test.ts`, que enumera `components["schemas"]["ReservationStatus"]` y exige etiqueta en los dos locales— así que un `DRAFT` sin traducir sale en rojo. Propuesta de etiquetas (el change puede afinar la redacción, no el conjunto):

| valor | ES | EN |
|---|---|---|
| `DRAFT` | Borrador | Draft |
| `RECOMMENDED` | Recomendado | Recommended |
| `APPROVED` | Aprobado | Approved |
| `APPLIED_EXTERNAL` | Publicado en la OTA | Published externally |
| `REJECTED` | Rechazado | Rejected |

**No hay ningún otro enum implicado.** No existe un «tipo de regla»: el ámbito de una regla es `property_id` nulo o no nulo, y su vigencia es el booleano `active` — los dos necesitan copia localizada (p. ej. «Toda la cartera» / «Whole portfolio», «Activa» / «Active»), pero no son enums y no salen de los tipos generados, así que ningún test los va a reclamar solo. El filtro de estado del listado, además, reutiliza esas mismas cinco etiquetas; y los colores de estado de PRD §9.1 que `steering/frontend.md` exige son de estado **operacional de vivienda**, no de recomendación: aquí no aplican, y el patrón a imitar es el `SEVERITY_COLOR` local de `frontend/features/incidents/components/detail/incident-detail-sections.tsx:7-12`.

## Permisos: quién ve esta pantalla, y por qué es implementable

Cuatro permisos, definidos en `backend/app/auth/domain/policy.py:143-146`, agrupados en dos paquetes que incluyen lectura **y** escritura (`policy.py:230-235`):

- `_PRICING_RULE_MANAGE` = `{READ_PRICING_RULES, MANAGE_PRICING_RULES}`
- `_PRICE_RECOMMENDATION_MANAGE` = `{READ_PRICE_RECOMMENDATIONS, MANAGE_PRICE_RECOMMENDATIONS}`

**`TENANT_OWNER` y `PROPERTY_MANAGER` tienen los cuatro** (`policy.py:293-294` y `324-325`). El comentario de `policy.py:128-142` lo argumenta y avisa de que es una divergencia consciente del patrón «la owner ve, el manager opera»: `min_price`/`max_price` son los límites del dinero de la propietaria, y PRD §19 Modo 1 dice literalmente «Manager/owner aprueba manualmente». Además deja cerrado que **`MANAGE_PRICE_RECOMMENDATIONS` cubre las tres transiciones *y* `POST /generate`**: un solo permiso para los cuatro botones.

`CLEANER` y `TECHNICIAN` no tienen ninguno (`policy.py:327` y `330`). **`SUPER_ADMIN` tampoco**: sólo tiene `_SELF_SERVICE` (`policy.py:262`), así que las cinco rutas le contestan `403`. Esta pantalla es de propietaria y manager, y de nadie más.

Verificación que exige una entrada `[FE]`: **cada operación que la pantalla pinta la puede llamar el rol que la ve.** Listado de recomendaciones (`READ_PRICE_RECOMMENDATIONS`), decisión y regeneración (`MANAGE_PRICE_RECOMMENDATIONS`), listado de reglas (`READ_PRICING_RULES`), catálogo de viviendas para resolver nombres (`READ_PROPERTIES`, que la owner tiene vía `_PROPERTY_READ` y el manager vía `_PROPERTY_MANAGE`): los dos roles pasan en todas. No hay ninguna casilla que la pantalla enseñe y su rol no pueda tocar.

**La trampa concreta**: el espejo de permisos del frontend, `frontend/lib/auth/permissions.ts`, es **deliberadamente parcial** y hoy declara `Permission = "MANAGE_CLEANING_TASKS"` con `TENANT_OWNER: []` y `PROPERTY_MANAGER: ["MANAGE_CLEANING_TASKS"]`. Hay que ampliar la unión con `"MANAGE_PRICE_RECOMMENDATIONS"` y dársela **a los dos roles**. Copiar la forma de cleaning —donde sólo el manager opera— dejaría a la propietaria mirando una cola que no puede decidir, con los botones ocultos por el propio frontend mientras el backend se los concedía. Y la regla de siempre sigue en pie (`steering/frontend.md`: «RBAC del backend decide, el frontend solo oculta»): un `403` se muestra como error, nunca se lee como éxito.

## Dinero: decimal como string, y **sin moneda en el contrato**

Fuente clásica de bug silencioso, cerrada aquí:

- **En las respuestas, todo importe es un `string` decimal**, no un número ni céntimos. `backend/openapi.json` da a `recommended_price`, `current_price`, `confidence`, `base_price`, `min_price`, `max_price` y `max_daily_change_pct` el tipo `string` con `pattern: "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$"`. Vienen de `Decimal` de Pydantic serializado como cadena, y **hay que tratarlos como cadena hasta el último momento**: `Number(...)` sólo para formatear, nunca para calcular ni para comparar. (En las *peticiones* el mismo campo acepta `number | string`, asimetría que se ve en `CreatePricingRuleRequest`; irrelevante aquí porque no se crean reglas.)
- **No hay campo `currency` en ninguna respuesta de pricing.** Contraste verificado: `reservations` sí lo lleva junto a `gross_amount`, y por eso `frontend/features/reservations/components/list/reservations-view.tsx` pinta `{row.grossAmount} {row.currency}`. Aquí no existe esa fuente, así que **se formatea sin símbolo de moneda**, exactamente como decidió `incidents-web` en su R5.5 —`frontend/features/incidents/components/detail/incident-detail-sections.tsx:18-29`, `fmtCost`: `Number(value).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})`, con un test que comprueba que no aparece `€|$|EUR|USD|GBP`—. Ese helper es el patrón a reutilizar, y resuelve la localización: `toLocaleString` con el locale activo da coma decimal en ES y punto en EN sin tabla propia.
- **La única «moneda» del módulo es una constante del backend, y está dentro de la frase**: `backend/app/pricing/domain/explanation.py:30` fija `CURRENCY = "EUR"` y la plantilla escribe `Base price 100.00 EUR. … Recommended 130.00 EUR.` (líneas 86 y 89). No es una configuración de tenant. Así que la pantalla muestra números sin símbolo **y** una explicación en inglés que dice EUR — asimetría real, aceptada a propósito: pintar «EUR» en las columnas sería que el frontend se inventase una moneda que el contrato no le da. La `explanation` es la frase del backend, citada tal cual.
- `date` es un día ISO sin hora (`YYYY-MM-DD`): se formatea con el locale, sin conversión de zona. `created_at` es UTC; el patrón del proyecto para no mentir con zonas es el `fmtUtc` de `incident-detail-sections.tsx:15-17` (recorta a minutos y no convierte).

## Registro de ruta e i18n

- **La ruta ya está registrada y no hay que crear ninguna** (consecuencia directa de la decisión 1): `frontend/features/shell/navigation/route-registry.ts:203-215` — `id: "pricing"`, `pattern: "/pricing"`, `href: "/pricing"`, `icon: "Tag"`, `profile: "workspace"`, `match: "exact"`, `navigationGroup: "revenue"`, `order: 1`.
- **Sus claves i18n existen en los dos locales**: `routes.pricing.title` / `.description` en `frontend/locales/es/navigation.json` («Precios» / «Reglas y recomendaciones de precios.») y en `frontend/locales/en/navigation.json` («Pricing» / «Pricing rules and recommendations.»). El grupo `revenue` también está traducido en ambos («Ingresos» / «Revenue»). **No hace falta tocar `navigation.json`.**
- Si en `/sdd:design` se reabriera la decisión 1 y se optase por una ruta hija, así se registra: descriptor nuevo imitando `property-detail` (`route-registry.ts:114-122`) —sin `href`, sin `navigationGroup`, `match: "exact"`, `breadcrumbKeys: crumbs("pricing", "<nuevo-id>")`—, `pricing` pasando a `match: "prefix"`, y las claves `routes.<nuevo-id>.title` / `.description` en los dos locales. `route-registry.test.ts`, `route-metadata.test.ts` y `breadcrumbs.test.ts` cubren ese registro, así que olvidarse de cualquiera de las piezas sale en rojo y no hay que vigilarlo a mano. Nota útil de `route-registry.test.ts:110`: el registro *«carries only shell metadata — no roles/endpoints/data fields»*, así que **el sidebar no se filtra por rol desde aquí**; ocultar por rol es asunto de `lib/auth/permissions.ts`.
- **Namespace i18n nuevo**: hay que crear `frontend/locales/{es,en}/pricing.json` y registrarlo en `frontend/lib/i18n/resources.ts`, que hoy importa y enumera `reservations`, `incidents` y `cleaning` (líneas 13-18, 28-30, 43-45, 54-56). Son cuatro sitios en el mismo fichero; olvidar uno deja el namespace mudo en un idioma.

## Precedente directo que hay que seguir, no reinventar

`cleaning-manager-view` (archivada el 2026-08-22, `changes/archive/2026-08-22-cleaning-manager-view/`) es el precedente **exacto**: lista paginada + filtros + una mutación + resolución de identidades. Lo que se hereda, pieza por pieza:

- **La mutación**: `frontend/features/cleaning/hooks/use-assign-cleaning-task.ts`. Invalida y **nunca parchea la caché optimistamente**, con `retry: false`, e invalida en **`onSettled`** —también al fallar—, apuntando al *prefijo* de la clave para alcanzar todas las combinaciones de filtro y página sin enumerarlas. Aquí aplica con más fuerza todavía: aprobar una recomendación la saca del filtro `RECOMMENDED`, y sólo refetchear la página que describen los parámetros actuales refleja eso; la respuesta del `PATCH` es una recomendación suelta y no sabe nada de `total` ni de la página.
- **Las claves de query**: `frontend/features/cleaning/hooks/query-keys.ts` sobre `tenantScopedKey` de `@/lib/query/query-keys`, de modo que toda clave empieza por `['tenant', tenantId, ...]` y una clave cruzada de tenant no puede construirse por accidente. Hacen falta `recommendations(tenantId, filters, page)`, **`recommendationsPrefix(tenantId)`** —el objetivo de la invalidación, imitando `tasksPrefix`— y `rules(tenantId, filters, page)`. Las dos mutaciones invalidan **sólo** `recommendationsPrefix`: ni decidir ni generar escriben una regla, así que la clave de reglas no se toca.
- **El error de la mutación**: `frontend/features/cleaning/lib/assign-error.ts` elige la clave de traducción **por status HTTP** y jamás por `ApiError.message` (técnico y en inglés). Para la decisión hay que mapear `403`, `404`, **`409`** y `422`; el `409` es el caso propio de esta pantalla —«esa recomendación ya no está en el estado que creías»— y merece copia propia, no el error genérico. Ojo: `mapIncidentsError` (`frontend/features/incidents/lib/error-mapping.ts`) **no tiene rama `409`**, así que el mapeador de esta feature no puede copiarse sin añadirla.
- **Nombres de vivienda**: las recomendaciones y las reglas sólo traen `property_id` (UUID). El catálogo se pide a `GET /api/v1/properties` con `page: 1, per_page: 100`, tal como hace `frontend/features/cleaning/data/http/http-cleaning-source.ts:126-130`, y se indexa con `buildDirectory` / `resolveIdentity` de `frontend/features/cleaning/lib/directory.ts`, cuyo tipo `Identity` tiene **cuatro** formas a propósito: «sin asignar» (aquí: regla de todo el tenant, `property_id === null`), «catálogo en vuelo», «no está en el catálogo» y «resuelto». Un fallo del catálogo **no** propaga al estado de error de la vista.
- **Filtros y página en Zustand**, no en el servidor ni duplicando server state: `frontend/features/cleaning/state/use-cleaning-filters-store.ts`, con dos invariantes que hay que heredar y no volver a derivar — el **reset a página 1 vive dentro de los setters**, y el store **recuerda de qué tenant son sus filtros** para no arrastrar el `property_id` de una sesión a la siguiente (regla 1 de `steering/security.md`, lado frontend). El mismo store aloja la pestaña activa.
- **La costura de datos**: `data/dto.ts` + `data/http/http-pricing-source.ts` + su test, sin la indirección `Mock*Source` (no hay UI previa que respetar), igual que hicieron `reservations-web` e `incidents-web`.

De `steering/frontend.md` aplican sin excepción: **TanStack Query v5 con clave por recurso + tenant** e invalidación del prefijo tras cada mutación, **Zustand sólo para UI ligera**, mobile-first, y **cada string en `locales/es` y `locales/en`** — las cinco etiquetas de estado, los cuatro contadores del informe de generación, los textos de los tres botones y sus confirmaciones, y las copias de vacío, error y `409`.

## Metadatos propuestos

`needs: revenue-pricing, frontend-auth-session · size: M · kind: feature`

- **`needs: revenue-pricing`** — entrega las cinco operaciones que esto consume. Archivada el 2026-08-18 (`changes/archive/2026-08-18-revenue-pricing/`), y su propia spec deja el hueco declarado: *«**Sin UI.** La página `/pricing` de PRD §24 es una entrada de frontend propia; esta capacidad es sólo backend.»* Dependencia satisfecha.
- **`needs: frontend-auth-session`** — las cinco rutas son del tenant autenticado y quien pone el token es la sesión del frontend. Archivada el 2026-08-08 (`changes/archive/2026-08-08-frontend-auth-session/`). Misma razón que declararon `dashboard-web`, `reservations-web` e `incidents-web`.
- No declara `needs: properties-crud` aunque consuma `GET /api/v1/properties`: ese endpoint ya lo consume el frontend en producción (`http-cleaning-source.ts`), así que la dependencia está absorbida por la línea de frontend ya entregada, igual que `reservations-web` no declaró `api-ingress-routing`. Tampoco declara `dashboard-web` como hizo `cleaning-manager-view`: no reutiliza nada de la feature `dashboard`, sólo piezas de `lib/` y de `features/cleaning`.

**Por qué `M` y no `S`.** `reservations-web` e `incidents-web` fueron `S` siendo **sólo lectura de un recurso**. Aquí hay: dos recursos listados (dos DTO, dos claves, dos mapeos de sobre), **dos hooks de mutación** (decidir y generar) con su invalidación, un mapeo de error con rama `409` que ningún precedente tiene, un catálogo de viviendas con su directorio, una pestaña que conmuta, un namespace i18n nuevo enganchado en cuatro puntos de `resources.ts`, y una ampliación del espejo de permisos del frontend que **hay que acertar para los dos roles**. `cleaning-manager-view` —un recurso, una mutación, sin pestañas y sin namespace nuevo— fue `S` y costó unos 94 USD según `sdd/metrics.md`, frente a los 106 de `reservations-web`; esta entrada es esa más un segundo recurso, una segunda mutación y la conmutación. Cabe en un change, no cabe en una `S`. La `M` es la de `cleaner-app` y `tech-app`, no la de una pantalla de lectura.
