# Proposal: pricing-web

## Why

`revenue-pricing` entregó y archivó el Modo 1 de PRD §19 —*el sistema recomienda, una
persona publica*— pero sólo su mitad de máquina. Su propia spec deja el hueco escrito:
*«**Sin UI.** La página `/pricing` de PRD §24 es una entrada de frontend propia; esta
capacidad es sólo backend.»* Hoy `frontend/app/(workspace)/pricing/page.tsx` renderiza
`RoutePlaceholder routeId="pricing"`, así que la mitad humana del modo es inalcanzable:
el job `generate_price_recommendations` escribe recomendaciones a las 06:00 UTC y nadie
puede aprobarlas.

Esto la hace distinta de las cinco entradas `[FE]` anteriores. `reservations-web`,
`incidents-web` y `properties-web` fueron pantallas de lectura, y su versión reducida
seguía siendo un producto. Aquí el sólo-lectura no es un alcance más pequeño: **es un
alcance sin producto** — una pantalla que pintase precios recomendados sin poder
decidirlos sería un informe, no el Modo 1. Es la primera pantalla de propietario/manager
cuyo valor *es* una mutación, y la primera entrada `[FE]` de la sección `revenue` del
sidebar.

Fuentes: entrada de roadmap `pricing-web` y su nota `sdd/roadmap/pricing-web.md`
(análisis largo, con el contrato ya verificado contra el código);
`sdd/specs/revenue-pricing.md`; `sdd/specs/celery-jobs.md`; PRD §7.17, §7.18, §19, §24.

## What changes

Después de este change, `/pricing` es una superficie funcional con dos pestañas:
**Recomendaciones** (por defecto) —la cola de decisión, paginada y filtrable, con los tres
movimientos legales y un botón de regeneración bajo demanda— y **Reglas** —el listado en
sólo lectura de las `PricingRule` que producen esa cola, sin entrar en el interior de sus
columnas JSONB—. Aparece la feature `frontend/features/pricing/` completa (costura de
datos, hooks de query y mutación, store de UI, componentes), un namespace i18n `pricing`
en ES y EN, y el espejo de permisos del frontend gana
`MANAGE_PRICE_RECOMMENDATIONS` **para propietaria y manager**. No se toca el backend, ni el
registro de ruta, ni `navigation.json`: las cinco operaciones están archivadas, el
descriptor `pricing` ya existe con `match: "exact"` y sus claves i18n están en los dos
locales.

Fuera de la feature se tocan **dos** cosas más, ambas decididas en `/sdd:design` y sin cambio
de comportamiento:

- **La paleta de tonos de insignia se extrae a `frontend/lib/ui/status-tone.ts`** y la
  consumen los tres consumidores (`components/property-state-badge.tsx`,
  `features/cleaning/lib/task-status.ts` y esta feature). El propio
  `task-status.ts` fijó la norma —extraer *«cuando aparece un tercer consumidor»*— y éste lo
  es; las dos copias vivas son idénticas cadena a cadena, así que el movimiento es mecánico y
  los tests de las dos features entregadas deben pasar sin editarlos (design D22).
- **`frontend/lib/api/client.ts` ensancha el tipo de `query`** a
  `string | number | boolean | null | undefined`, **si y sólo si** `npm run typecheck`
  confirma que el filtro `active` de `GET /api/v1/pricing-rules` (declarado
  `boolean | null`) no compila hoy contra la intersección actual. En runtime ya funciona
  (`appendQuery` hace `String(value)`); esta feature es la primera del árbol que pasa un
  booleano de query (design D20).

## Requirements

### R1 — Una ruta, dos pestañas

**As a** manager o propietaria, **I want** ver en `/pricing` tanto la cola de
recomendaciones como las reglas que la producen, **so that** pueda decidir un precio y
entender de dónde sale sin cambiar de pantalla.

El registro de ruta ya prometió las dos cosas: `routes.pricing.description` dice *«Reglas y
recomendaciones de precios.»* / *«Pricing rules and recommendations.»*.

Acceptance criteria:

1. WHEN una usuaria autorizada abre `/pricing`, THE SYSTEM SHALL renderizar la pestaña
   **Recomendaciones** como pestaña activa inicial, y una pestaña **Reglas** alcanzable
   desde la misma ruta.
2. THE SYSTEM SHALL servir las dos pestañas bajo el descriptor de ruta existente
   (`id: "pricing"`, `pattern: "/pricing"`, `match: "exact"`,
   `features/shell/navigation/route-registry.ts`) **sin** dar de alta ningún descriptor
   nuevo, sin cambiar `match` a `"prefix"` y sin añadir claves a
   `locales/{es,en}/navigation.json`.
3. THE SYSTEM SHALL mantener la pestaña activa en el store de UI de la feature (Zustand),
   y NOT SHALL reflejarla en la URL ni en un parámetro de query.
4. WHEN se abre `/pricing`, THE SYSTEM SHALL dejar de renderizar `RoutePlaceholder` en esa
   ruta.

### R2 — La cola de recomendaciones

**As a** manager, **I want** ver las recomendaciones ordenadas por la noche más próxima,
con filtros y paginación, **so that** pueda trabajar la cola de decisión de arriba abajo.

Acceptance criteria:

1. WHEN se muestra la pestaña Recomendaciones, THE SYSTEM SHALL pedir
   `GET /api/v1/price-recommendations` con `page`, `per_page`, y los filtros activos
   `property_id`, `date_from`, `date_to` y `status` — este último enviado con el nombre de
   query `status` (el parámetro de Python es `status_filter` con `Query(alias="status")`).
2. THE SYSTEM SHALL leer el sobre de paginación de pricing como **`{ items, total, page,
   per_page }`** — `items`, no `data` — y, dado que la respuesta **no** trae `total_pages`,
   THE SYSTEM SHALL calcular el número de páginas en el cliente como
   `Math.ceil(total / per_page)`.
3. IF `total` es `0`, THEN THE SYSTEM SHALL renderizar el estado vacío localizado, y NOT
   SHALL renderizar «página 1 de 0».
4. THE SYSTEM SHALL pintar por fila: vivienda (nombre resuelto), `date`, `recommended_price`,
   `status` y `explanation`.
5. THE SYSTEM SHALL NOT pintar `current_price` (es siempre `null` mientras el Modo 1 no
   llame al PMS) ni `confidence` (fijado a `1.00` porque el cálculo es determinista), aunque
   los dos lleguen en el DTO.
6. Dado que `PriceRecommendationResponse` **no** expone `updated_at`, THE SYSTEM SHALL NOT
   mostrar ninguna marca temporal de decisión («aprobado hace X», «decidido el …»).
7. THE SYSTEM SHALL renderizar `explanation` **como texto y nunca como HTML**, literal y sin
   traducir ni parsear (viene en inglés desde una plantilla cerrada del backend), con
   etiqueta localizada alrededor. Es sumidero de texto libre de la regla 11 de
   `steering/security.md`: el `name` que la manager escribió en una temporada o un evento es
   la única parte que la plantilla no compone.
8. WHEN el nombre de una vivienda no se puede resolver, THE SYSTEM SHALL distinguir en
   pantalla «catálogo en vuelo», «no está en el catálogo» y «resuelto», y un fallo del
   catálogo de viviendas SHALL NOT propagar al estado de error de la vista.

### R3 — La decisión: los tres movimientos legales

**As a** propietaria o manager, **I want** aprobar, rechazar y marcar como publicada una
recomendación, **so that** el Modo 1 se cierre — el sistema recomienda y yo publico.

`PATCH /api/v1/price-recommendations/{recommendation_id}` acepta **un solo campo**
(`{"status": …}`, `extra="forbid"`), así que los tres movimientos son un endpoint y un
cuerpo.

Acceptance criteria:

1. WHEN la fila está en `RECOMMENDED`, THE SYSTEM SHALL ofrecer **Aprobar**
   (`status: "APPROVED"`) y **Rechazar** (`status: "REJECTED"`).
2. WHEN la fila está en `APPROVED`, THE SYSTEM SHALL ofrecer **Marcar como publicada**
   (`status: "APPLIED_EXTERNAL"`), y SHALL NOT ofrecerla en ningún otro estado. Sin este
   tercer botón una fila aprobada es un callejón sin salida y el hecho que cierra el Modo 1
   —«ya subí este precio a la OTA»— es inalcanzable.
3. WHEN una decisión se envía, THE SYSTEM SHALL pedir confirmación antes de mutar y
   deshabilitar el control mientras la petición vuela.
4. THE SYSTEM SHALL configurar la mutación con `retry: false` (una escritura rechazada no se
   reintenta), SHALL NOT parchear la caché de forma optimista, y SHALL invalidar el
   **prefijo** de la clave de recomendaciones en `onSettled` —también cuando falla—, de modo
   que la fila desaparezca del filtro que ya no la contiene sin enumerar combinaciones de
   filtro y página. La respuesta del `PATCH` es una recomendación suelta y no sabe nada de
   `total` ni de la página.
5. THE SYSTEM SHALL invalidar **sólo** el prefijo de recomendaciones: ni decidir ni regenerar
   escriben una regla, así que la clave de reglas no se toca.
6. IF el `PATCH` responde `409` (el movimiento no es uno de los tres legales, con el estado
   intacto), THEN THE SYSTEM SHALL mostrar copia localizada **propia** de ese caso —«esa
   recomendación ya no está en el estado que creías»—, distinta del error genérico.
7. THE SYSTEM SHALL elegir la copia de error por **status HTTP** (`403`, `404`, `409`, `422`,
   genérico) y SHALL NOT leer, mapear ni exponer `ApiError.message` ni el cuerpo del backend.
8. IF cualquier operación responde `403`, THEN THE SYSTEM SHALL mostrarlo como error y SHALL
   NOT tratarlo como éxito.

### R4 — Regenerar ahora

**As a** manager, **I want** disparar la generación sin esperar al job de las 06:00 UTC,
**so that** una regla recién sembrada o editada surta efecto ya y la pantalla no esté vacía
por razones de calendario.

`POST /api/v1/price-recommendations/generate` corre **sincrónicamente en la petición** y
devuelve el informe; no hay `202`, ni job id, ni polling.

Acceptance criteria:

1. WHEN la usuaria pulsa **Regenerar ahora** en la pestaña Recomendaciones, THE SYSTEM SHALL
   llamar a `POST /api/v1/price-recommendations/generate` con
   `{"property_id": <filtro activo> | null}` — el `property_id` del filtro si hay uno, nada
   si no —, sin ofrecer un segundo selector de vivienda.
2. WHEN la generación responde, THE SYSTEM SHALL mostrar los cuatro contadores de
   `GenerationReportResponse` (`created`, `updated`, `preserved`, `skipped`) en un aviso
   localizado, y SHALL invalidar el prefijo de recomendaciones.
3. THE SYSTEM SHALL NOT afirmar que el barrido fue completo o correcto: el contrato publicado
   **no** expone un contador `failed` (*«un barrido con agujeros se ve verde desde la API»*,
   `specs/revenue-pricing.md`), así que el aviso enseña los cuatro números que llegaron y
   nada más.
4. THE SYSTEM SHALL aplicar `retry: false` y deshabilitar el botón mientras la petición vuela.

### R5 — Las reglas, en sólo lectura y sin abrir el JSONB

**As a** propietaria, **I want** ver qué reglas producen estos precios y con qué banda de
mínimo/base/máximo, **so that** pueda aprobar con criterio en vez de a ciegas.

Acceptance criteria:

1. WHEN se muestra la pestaña Reglas, THE SYSTEM SHALL pedir `GET /api/v1/pricing-rules` con
   `page`, `per_page` y los filtros `property_id` y `active`, leyendo el mismo sobre `items`
   de R2.2 y calculando las páginas en el cliente.
2. THE SYSTEM SHALL pintar por regla: `name`, el ámbito, `active`, la banda
   `min_price`/`base_price`/`max_price`, `max_daily_change_pct` y **cuántas** entradas hay en
   cada una de las cinco columnas JSONB.
3. WHERE `property_id` es `null`, THE SYSTEM SHALL presentar la regla como de toda la cartera
   («Toda la cartera» / «Whole portfolio») con copia localizada, no como una vivienda sin
   nombre.
4. THE SYSTEM SHALL NOT interpretar ni renderizar el interior de `weekday_modifiers`,
   `lead_time_rules`, `occupancy_rules`, `seasonality_rules` ni `event_rules`: contar entradas
   es seguro, pintar su interior sería reimplementar el esquema de PRD §7.17 en el cliente.
5. THE SYSTEM SHALL NOT consumir `GET /api/v1/pricing-rules/{rule_id}`: devuelve el mismo
   `PricingRuleResponse` que ya viene en cada `items[]`, así que no hay detalle que pedir.

### R6 — Dinero sin moneda inventada, y los cinco estados con etiqueta

**As a** usuaria en español o inglés, **I want** ver importes y estados legibles en mi idioma,
**so that** la pantalla no me obligue a interpretar cadenas técnicas.

Acceptance criteria:

1. THE SYSTEM SHALL tratar todo importe de la respuesta (`recommended_price`, `base_price`,
   `min_price`, `max_price`, `max_daily_change_pct`) como la **cadena decimal** que el contrato
   declara, usando conversión numérica **sólo para formatear** y nunca para calcular ni
   comparar.
2. Dado que ninguna respuesta de pricing lleva campo `currency`, THE SYSTEM SHALL formatear
   los importes **sin símbolo ni código de moneda**, con el separador decimal del locale
   activo (coma en ES, punto en EN), reutilizando el patrón de
   `features/incidents/.../incident-detail-sections.tsx` (`fmtCost`).
3. THE SYSTEM SHALL formatear `date` como día del locale, sin hora y sin conversión de zona;
   y cualquier `created_at` que se muestre, en UTC recortado a minutos y sin convertir.
4. THE SYSTEM SHALL proveer etiqueta localizada en ES y EN para los **cinco** valores de
   `PriceRecommendationStatus` —`DRAFT`, `RECOMMENDED`, `APPROVED`, `APPLIED_EXTERNAL`,
   `REJECTED`—, incluido `DRAFT` aunque hoy nadie lo produzca ni lo consuma, porque el test de
   contrato de locales enumera el enum desde los tipos generados.
5. THE SYSTEM SHALL crear el namespace `pricing` en `locales/es/` y `locales/en/` y
   registrarlo en `lib/i18n/resources.ts` en sus **cuatro** puntos (el `import` por locale, la
   lista `NAMESPACES`, y la entrada dentro de `resources.es` y `resources.en`).
6. THE SYSTEM SHALL NOT dejar ninguna string visible sin traducción en los dos locales — las
   cinco etiquetas de estado, los cuatro contadores del informe, los textos de los tres
   botones y sus confirmaciones, y las copias de vacío, error y `409`.
7. THE SYSTEM SHALL NOT aplicar los colores de estado operacional de PRD §9.1: son de estado
   de vivienda, no de recomendación.

### R7 — El espejo de permisos, acertado para los dos roles

**As a** propietaria, **I want** que los botones de decisión estén disponibles para mí y no
sólo para el manager, **so that** pueda aprobar los límites del dinero de mi propia vivienda.

`policy.py:128-142` documenta que ésta es una divergencia consciente del patrón «la owner ve,
el manager opera»: `min_price`/`max_price` son los límites del dinero de la propietaria, y PRD
§19 Modo 1 dice «Manager/owner aprueba manualmente».

Acceptance criteria:

1. THE SYSTEM SHALL ampliar la unión `Permission` de `frontend/lib/auth/permissions.ts` con
   `"MANAGE_PRICE_RECOMMENDATIONS"` y concederla en `ROLE_UI_PERMISSIONS` a **`TENANT_OWNER`
   y `PROPERTY_MANAGER`**, que es lo que `policy.py:293-294` y `324-325` les dan en el
   backend.
2. THE SYSTEM SHALL NOT copiar la forma de `MANAGE_CLEANING_TASKS` (`TENANT_OWNER: []`): eso
   dejaría a la propietaria mirando una cola que no puede decidir, con los botones ocultos por
   el propio frontend mientras el backend se los concedía.
3. THE SYSTEM SHALL tratar el espejo como pista de UX y no como autoridad: el RBAC del backend
   decide y el frontend sólo oculta.

## Out of scope

- **El CRUD de reglas** (`POST /api/v1/pricing-rules`, `PATCH /api/v1/pricing-rules/{rule_id}`)
  — su propia entrada de roadmap, ya declarada en la línea de `pricing-web`. No es simetría con
  las entradas `[FE]` anteriores, es un coste medible: el formulario arrastra **toda** la
  validación de PRD §7.17, que el backend hace cumplir en el dominio y no en el esquema de
  petición (las cinco columnas JSONB están tipadas como contenedores «y nada más»). Y el remate
  que lo vuelve inviable: el frontend **no puede enseñar cuál de las cinco columnas falló**,
  porque la norma del proyecto prohíbe pintar el cuerpo del `422`. Un formulario de regla sería
  o lógica de negocio en el componente (prohibida en los «Don'ts» de `steering/frontend.md`) o
  un formulario cuyo único feedback es «no se pudo guardar».
- **`GET /api/v1/pricing-rules/{rule_id}`** — no aporta nada sobre el listado (mismo DTO);
  escrito aquí para que nadie salga a buscar una ruta de detalle que no existe como necesidad.
- **Una ruta hija `/pricing/rules`** — descartada en R1: obligaría a pasar `pricing` a
  `match: "prefix"`, dar de alta un descriptor nuevo y añadir claves i18n por locale, todo para
  una lista de sólo lectura que nadie enlaza desde fuera.
- **La pestaña activa en la URL** (`?tab=`) — segunda fuente de verdad sobre la misma cosa, sin
  enlace entrante que la justifique.
- **Cambios en el backend de pricing**: el contrato está congelado y archivado, y
  `frontend/lib/api/generated/openapi.d.ts` ya declara las cinco operaciones. No hay tipos que
  escribir a mano ni contrato que regenerar.
- **Publicación real del precio en la OTA / ARI**: `APPLIED_EXTERNAL` es el registro humano de
  que alguien lo subió a mano; el Modo 2 de PRD §19 no entra.
- **Historial o auditoría de decisiones en pantalla**: el rastro vive en `AuditLog` y en el
  `TimelineEvent PRICE_UPDATED_EXTERNAL`, y ninguno de los dos tiene superficie aquí (ver
  R2.6).

## Affected specs

- `sdd/specs/revenue-pricing.md` — se amplía con la superficie de frontend que consume las
  cinco operaciones, y se cierra la frase *«Sin UI. La página `/pricing` de PRD §24 es una
  entrada de frontend propia»*, que a partir del merge deja de ser cierta.
- `sdd/specs/frontend-foundation.md` — su inventario de `frontend/app/` pasa de «12 placeholder
  pages plus ten functional surfaces» a **11 placeholders y once superficies funcionales**
  (verificado hoy: 12 páginas con `RoutePlaceholder`, y las diez que la frase enumera). Se
  registra además el namespace `pricing` en la lista de catálogos de traducción.
- `sdd/specs/frontend-auth-session.md` — **no se modifica**: se consume tal cual (tokens en
  memoria, `AuthGuard` sobre la ruta workspace, refresh coordinado por el cliente HTTP).
- `sdd/specs/frontend-api-contract-consumer.md` — **no se modifica**: el cliente tipado ya
  incluye las cinco operaciones de pricing y no hay regeneración en este diff.
- `sdd/specs/celery-jobs.md` — sin cambio de comportamiento; se revisará al archivar si merece
  anotar que `generate_price_recommendations` ya tiene puerta manual con consumidor de frontend.
- `sdd/specs/auth-tenancy.md` — sin cambio de comportamiento del backend; se revisará al
  archivar si el espejo parcial de permisos del frontend merece nota (hoy la nota vive en el
  propio `permissions.ts`).
