# Tasks: revenue-pricing

Orden pensado para que el sistema siga en pie tras cada sección: primero el dominio puro
(que no toca nada vivo), luego los puertos y adaptadores, luego RBAC/audit, después los casos
de uso, la API, el job y por último steering/documentación y verificación.

`steering/testing.md` manda **TDD en `domain/` con invariante real** — y cita literalmente
«guardrails de pricing». Las tareas de la sección 1 escriben el test antes que el código.
Todos los tests nuevos viven en `backend/tests/pricing/` salvo donde se indique otra cosa.

## 1. Dominio puro: cálculo, guardrails, ocupación y explicación <!-- panel: PASS 2026-08-17 -->


- [x] 1.1 `backend/app/pricing/domain/constants.py` *(nuevo)*: `HORIZON_DAYS = 60` y
      `OCCUPANCY_WINDOW_DAYS = 30`, con el comentario de D18 (son cifras del PRD §8.3/§7.17, no
      palancas de `Settings`; por eso este change no toca `.env.example`). Test en
      `tests/pricing/test_constants.py` que fija los dos valores. [R4.1]
- [x] 1.2 `backend/app/pricing/domain/holidays.py` *(nuevo)*: `SPAIN_NATIONAL_HOLIDAYS:
      frozenset[date]` con los festivos nacionales de España 2025-2027 (PRD §19), sin dependencia
      externa, y el identificador `ES_NATIONAL` como único catálogo admitido (D7). Test
      `tests/pricing/test_holidays.py`: cuenta por año, presencia de las fechas fijas (1-ene,
      1-may, 15-ago, 12-oct, 1-nov, 6/8/25-dic) y de las móviles del año, y que el conjunto es
      inmutable. [R2.6]
- [x] 1.3 **Test primero** `tests/pricing/test_calculator.py` para la cadena de modificadores de
      D3 antes de escribir el calculador: orden día de la semana → anticipación → ocupación →
      temporada → eventos, cada uno multiplicativo; `lead_time_rules` aplicables las de
      `days_before <= r["days_before"]` ganando la de **menor** `days_before`; `occupancy_rules`
      las de `occupancy_pct >= r["occupancy_pct_above"]` ganando la de **mayor**
      `occupancy_pct_above`; temporadas y eventos **todos** los que casen en orden declarado.
      Incluye los tres huecos que cierra D3: rango de temporada anual recurrente **que cruza el
      fin de año** cuando `(end_month, end_day) < (start_month, start_day)`, `event_rule` como
      fecha exacta con año, y `weekday_modifiers` indexado por nombre inglés en minúsculas
      calculado **sin `strftime`** (locale) con clave ausente valiendo 0. [R2.1, R2.2]
- [x] 1.4 `backend/app/pricing/domain/calculator.py` *(nuevo)*: `PriceCalculation`,
      `AppliedModifier(kind, name, modifier_pct, price_after)` y `AppliedGuardrail(kind,
      price_before, price_after, reference, limit_pct)` como value objects congelados, y
      `calculate_price(rule, *, target_date, days_before, occupancy_pct, previous_price)`
      devolviendo el resultado estructurado, no un `Decimal` (D2). Firma sin reloj, sin sesión y
      sin red: R2.5 se satisface por firma. Verde el test de 1.3. [R2.1, R2.2, R2.5]
- [x] 1.5 **Test primero** en `tests/pricing/test_calculator.py` para los guardrails de D4 y luego
      su implementación dentro de `calculate_price`: tope diario `±max_daily_change_pct %` sobre
      `previous_price` **antes** del clamp a `[min_price, max_price]`, de modo que ningún precio
      emitido quede fuera del rango aunque el tope lo permitiera; `previous_price=None` (primer
      día del horizonte) no aplica tope. Casos límite obligatorios por `steering/testing.md`:
      precio por debajo de `min_price`, por encima de `max_price`, salto que excede el tope por
      arriba y por abajo, y los dos guardrails compitiendo a la vez. Cada guardrail que actúa
      deja su `AppliedGuardrail` en la traza. [R3.1, R3.2, R3.3, R3.4]
- [x] 1.6 Blindar la aritmética `Decimal` (R2.4): conversión de los `modifier_pct` de los JSONB
      con `Decimal(str(v))` en un **único** punto de entrada del calculador, nunca
      `Decimal(float)`, y redondeo `ROUND_HALF_UP` a dos decimales **una sola vez**, al final,
      después de los guardrails. Test que recorre `PriceCalculation` completo y asserta
      `type(x) is Decimal` en `base_price`, en cada `price_after` de modificador y guardrail y en
      `recommended_price`, alimentado con `modifier_pct` que llegan como `int` y como `float`
      desde un JSONB real. [R2.4]
- [x] 1.7 `backend/app/pricing/domain/occupancy.py` *(nuevo)*: `occupancy_pct_for` puro sobre las
      entidades `Reservation` — cuenta noches distintas `[check_in_date, check_out_date)`
      intersectadas con la ventana de `OCCUPANCY_WINDOW_DAYS` días naturales siguientes a la fecha
      de ejecución y divide entre 30 (D5). **Ocupado es todo menos `CANCELLED` y `NO_SHOW`**;
      `PENDING` cuenta. Test `tests/pricing/test_occupancy.py`: ventana vacía = 0, ventana llena =
      100, solapes entre reservas contados una vez, reserva que empieza antes o acaba después de
      la ventana recortada al tramo intersecado, y los dos estados excluidos. [R2.3]
- [x] 1.8 `backend/app/pricing/domain/rule_resolution.py` *(nuevo)*: `resolve_rule(rules,
      property_id) -> PricingRule | None` — primero reglas activas con `property_id` igual, si no
      las de `property_id is NULL`, y dentro de cada grupo gana `updated_at` más reciente con `id`
      como desempate final (D6, OQ3). Test `tests/pricing/test_rule_resolution.py`: la regla de
      propiedad gana a la de tenant, sin regla propia cae a la de tenant, sin ninguna devuelve
      `None`, y **el mismo resultado con la lista barajada** (determinismo del desempate).
      [R1.5]
- [x] 1.9 `backend/app/pricing/domain/explanation.py` *(nuevo)*: render en **inglés** del
      `PriceCalculation` con la plantilla cerrada de D13 — precio base, cada modificador con su
      nombre y porcentaje y el precio resultante, cada guardrail que actuó, y el precio final.
      Sin pasar por ningún adaptador de IA (R6.2). Test `tests/pricing/test_explanation.py`:
      cadena exacta del ejemplo de D13, presencia del guardrail que recortó, y determinismo
      (dos renders del mismo cálculo son idénticos). [R6.1, R6.2, R6.4, R3.5]

## 2. Entidades e invariantes de dominio <!-- panel: PASS 2026-08-17 -->


- [x] 2.1 `backend/app/pricing/domain/exceptions.py` *(nuevo)*: jerarquía plana bajo
      `PricingDomainError` — `PricingRuleNotFoundError`, `PriceRecommendationNotFoundError`,
      `InvalidRecommendationTransitionError`, `PricingValidationError` y sus subclases (D15).
- [x] 2.2 **Test primero** en `tests/pricing/test_entities.py` y luego `PricingRule.create` /
      `validate` / `update_details` en `backend/app/pricing/domain/entities.py` (D16): invariantes
      `min_price <= max_price`, `base_price` dentro de `[min_price, max_price]`,
      `max_daily_change_pct` en `[0, 100]`, y el esquema de los cinco JSONB —incluida la forma de
      festivos `{"holidays": "ES_NATIONAL", "modifier_pct": …}` de D7, con `422` si una entrada de
      `event_rules` lleva **las dos formas o ninguna**, y `422` si el identificador de catálogo no
      es `ES_NATIONAL`—. Cada fallo lanza `PricingValidationError` **nombrando el campo**. El
      `name` de temporadas y eventos queda acotado a **100 caracteres** (mitigación del riesgo del
      sumidero de texto, D13). [R1.3, R1.4]
      Tres exigencias más que **añadió el panel de seguridad de la sección 1** (su F3), porque hoy
      el calculador es la única puerta y revienta con `KeyError`/`TypeError`/`InvalidOperation`
      ante un JSONB torcido: (a) cada umbral y cada `modifier_pct` debe ser un **número** JSON, no
      una cadena —`days_before` se compara como `int` desnudo y un `str` lanza `TypeError`—;
      (b) rechazar los no finitos (`NaN`, `Infinity`, exponentes desmedidos); y (c) **un tope al
      número de entradas** de cada uno de los cuatro arrays, porque temporadas y eventos aplican
      *todos* los que casen y N reglas casando son N frases × 60 días en un sumidero de la regla 11.
      **Y un test de la sección 1 caduca aquí**:
      `tests/pricing/test_calculator.py::test_a_non_numeric_lead_time_threshold_cannot_reach_the_name`
      fija hoy el `TypeError` que lanza `days_before <= rule["days_before"]` con una cadena. En
      cuanto el validador exista ese camino deja de ser alcanzable, así que esa aserción se
      sustituye por el `422` — es un acoplamiento previsto, no una regresión. Lo señaló el panel
      de QA de la sección 1 al reverificar sus arreglos.
      **Y el abanico de excepciones se ensanchó**: parsear los umbrales convierte un JSONB torcido
      en `TypeError` **o** `decimal.InvalidOperation` (un `days_before` booleano sobrevive a la
      comparación —`1 <= True` es cierto— y muere en `Decimal("True")`). El validador de esta
      tarea y el borde del job de 5.3/5.4 tienen que atrapar **las dos**, o una sola fila de regla
      mal formada tumba el horizonte de esa propiedad.
- [x] 2.3 **Test primero** en `tests/pricing/test_entities.py` y luego
      `PriceRecommendation.decide` / `mark_applied_external`: solo las tres transiciones legales
      (`RECOMMENDED→APPROVED`, `RECOMMENDED→REJECTED`, `APPROVED→APPLIED_EXTERNAL`); cualquier
      otra lanza `InvalidRecommendationTransitionError` y **deja el estado intacto**. El test
      recorre la matriz completa 5×5 de la máquina de estados, incluidas las inválidas, como exige
      `steering/testing.md` (DoD §28.19), y comprueba que nadie produce ni sale de `DRAFT`.
      [R5.2, R5.3, R5.4]
- [x] 2.4 Fijar `confidence = Decimal("1.00")` en la creación de una recomendación, con el
      comentario en el código que declara que el campo existe para un modo futuro con
      incertidumbre real y no para adornar el determinismo actual (D13). Test que lo asserta.
      [R6.3]

## 3. Puertos, repositorios y lectura de propiedades <!-- panel: PASS 2026-08-17 -->


- [x] 3.1 `backend/app/pricing/domain/repositories.py` *(nuevo)*: puertos `PricingRuleRepository`
      (`add`, `get`, `list` paginado con filtros `property_id`/`active`, `list_active`, `update`)
      y `PriceRecommendationRepository` (`get`, `list` paginado con filtros
      `property_id`/`date_from`/`date_to`/`status`, `list_for_property_range`, `upsert_many`,
      `update`), con los filtros y `Page` al estilo de `maintenance`. Todas las firmas llevan
      `tenant_id` explícito, y **el escritor scopea por ese parámetro, nunca leyendo
      `entity.tenant_id` del objeto que persiste**. Los docstrings declaran la precondición de
      claves foráneas de D9: `property_id` y `pricing_rule_id` ya resueltos dentro del `tenant_id`
      que actúa, porque las FK son globales y la base aceptaría una recomendación del tenant A
      colgada de una propiedad del B — la misma nota que lleva `IncidentRepository.add` en
      `maintenance`. Lo pidió el panel de tenancy de la sección 2. [R1.2, R5.1]
- [x] 3.2 `backend/app/pricing/infrastructure/repositories.py` *(nuevo)*: adaptadores SQLAlchemy
      de los dos puertos. El escritor del horizonte usa `INSERT … ON CONFLICT (property_id, date)
      DO UPDATE` — el `UNIQUE` decide, no una lectura previa (D9). Tests de integración en
      `tests/pricing/test_repositories.py`: paginación, cada filtro, y `upsert_many` ejecutado dos
      veces seguidas dejando el mismo número de filas. [R1.2, R4.2, R5.1]
- [x] 3.3 Test de **aislamiento por tenant** de los dos repositorios en
      `tests/pricing/test_repositories.py` (DoD §28.18): un `get` con `tenant_id` ajeno devuelve
      `None`, un `list` nunca cruza tenants, y el `upsert` no puede pisar una fila de otro tenant.
      Las aserciones de propiedad de las filas corren sobre un `AsyncSession(test_engine)`
      **nunca marcado** — sobre una sesión marcada el listener de `app/core/db.py` reescribe
      incluso un `select` de una sola columna y el test sería tautológico.
      Un caso más, por la precondición de D9: una recomendación cuyo `property_id` o
      `pricing_rule_id` pertenece a otro tenant **no debe poder producirse** — el caso de uso la
      rechaza, porque las FK globales no la rechazan. [R1.2, R1.7, R5.1]
- [x] 3.4 `PropertyRepository.list_by_status(tenant_id, status) -> list[Property]` en
      `backend/app/properties/domain/repositories.py` y su adaptador en
      `backend/app/properties/infrastructure/repositories.py` (D17: el docstring de `list_all` pide
      literalmente un método más estrecho en vez de filtrar en memoria). Test en
      `tests/properties/test_repositories.py`, incluido el filtro por tenant. [R4.1]

## 4. RBAC y AuditLog <!-- panel: PASS 2026-08-17; el bloqueante salió del change: roadmap `audit-changes-repository-guard` -->


- [x] 4.1 `backend/app/auth/domain/policy.py`: cuatro permisos nuevos —`READ_PRICING_RULES`,
      `MANAGE_PRICING_RULES`, `READ_PRICE_RECOMMENDATIONS`, `MANAGE_PRICE_RECOMMENDATIONS`—
      concedidos a `TENANT_OWNER` **y** `PROPERTY_MANAGER`, y a nadie más (ni `CLEANER`, ni
      `TECHNICIAN`, ni `SUPER_ADMIN`). Comentario que deja escrita la divergencia consciente de
      D11: aquí la propietaria también gestiona, porque `min_price`/`max_price`/
      `max_daily_change_pct` son los límites de su propio dinero y PRD §19 Modo 1 dice
      «Manager/owner aprueba manualmente». Test en `tests/auth/` de la matriz rol × permiso.
      [R1.1, R1.2, R5.2]
- [x] 4.2 `backend/app/audit/domain/actions.py` y `value_objects.py`: `ENTITY_PRICING_RULE` y
      `ENTITY_PRICE_RECOMMENDATION`; acciones `PRICING_RULE_CREATED`, `PRICING_RULE_UPDATED`,
      `PRICE_RECOMMENDATION_DECIDED` (una sola para `APPROVED` y `REJECTED`, con el desenlace en
      el diff, precedente de `OWNER_APPROVAL_ANSWERED`) y `PRICE_RECOMMENDATION_APPLIED_EXTERNAL`
      aparte, porque no es una decisión sino un hecho del mundo (D12). `AUDITABLE_FIELDS` gana
      `"PRICING_RULE"` con los doce campos escribibles y `"PRICE_RECOMMENDATION"` con `{"status"}`
      y nada más. Ninguna entrada en la denylist. Tests en `tests/audit/`. [R1.6, R5.2]
- [x] 4.3 Test de contención del sumidero de texto: `ChangeSet` rechaza por construcción cualquier
      campo de `PRICE_RECOMMENDATION` que no sea `status`, de modo que ni la `explanation` ni el
      `name` que teclea la manager pueden llegar a `audit_logs.changes`. Ubícalo junto al test de
      contrato de sumideros libres que ya existe para `maintenance`
      (`tests/maintenance/test_free_text_sink_contract.py`) siguiendo su forma. [R6.1]

## 5. Casos de uso <!-- panel: PASS 2026-08-17 (2.ª ronda: arquitectura PASS, tenancy PASS, QA y seguridad FAIL con 4 hallazgos, todos arreglados y reverificados); las dos decisiones abiertas las resolvió Jose el 2026-08-17 -->

- [x] 5.1 `backend/app/pricing/application/use_cases.py` *(nuevo)*: `_AuditWriter` propio del
      módulo con la disciplina de `maintenance` — **ninguna** de las tres acciones admite
      `actor=None`, porque las tres las ejecuta una persona autenticada (D12). Test que lo
      comprueba. [R1.6, R5.2]
      **Y los nombres de campo del diff salen de `UPDATABLE_RULE_FIELDS`, no del llamante.**
      `REDACT_ONLY_FIELDS` rechaza las cinco columnas JSONB *por nombre de campo*, así que el
      atajo natural cuando una de ellas revienta es reetiquetar: `diff("name", old,
      json.dumps(rule.seasonality_rules))` pasa, porque `name` sí es diffable y `_storable`
      acepta cualquier `str`. Test de que el valor guardado bajo `name` es exactamente
      `rule.name`. Lo dejó anotado el panel de seguridad de la sección 4 como el residuo que su
      arreglo no cierra.
- [x] 5.2 Casos de uso de reglas: `CreatePricingRule`, `ListPricingRules`, `GetPricingRule`,
      `UpdatePricingRule`. Validan por dominio (2.2), operan siempre dentro del `tenant_id` de la
      sesión, escriben `AuditLog` en crear y modificar, y devuelven `PricingRuleNotFoundError`
      —nunca un `403`— cuando el identificador es de otro tenant. Tests en
      `tests/pricing/test_use_cases.py` incluida la mitad de aislamiento por los puertos.
      **Y resuelven el `property_id` del cuerpo con `PropertyRepository.get(tenant_id, …)` antes
      de construir o mutar la entidad, con `422` si no existe en ese tenant** (D20). Es la mitad
      que entra por teclado del ataque que demostró el panel de seguridad de la sección 3: las FK
      son globales, así que una regla del tenant A puede apuntar a una propiedad del B y nada en
      el esquema lo impide. La otra mitad —el horizonte— ya la cierra `upsert_many` por su cuenta.
      Test explícito de que un `property_id` ajeno se rechaza al crear **y** al modificar.
      [R1.1, R1.2, R1.3, R1.4, R1.6, R1.7]
- [x] 5.3 `GeneratePriceRecommendationsUseCase.execute(tenant_id, *, now, property_id=None,
      actor=None)` — el **único** generador, síncrono, compartido por el job y por
      `POST /generate` (D10). Por propiedad: resuelve la regla (1.8), calcula la ocupación una
      sola vez con una consulta de reservas (1.7, D5), recorre el horizonte de `HORIZON_DAYS` en
      **orden ascendente de fecha** encadenando `previous_price` y persiste con `upsert_many`
      dentro de **una transacción por propiedad**. Devuelve `{created, updated, preserved,
      skipped}`. Tests: horizonte de 60 días, orden ascendente, y una propiedad que falla no
      descarta el horizonte ya escrito de las anteriores. [R4.1, R4.5, R2.3, R3.2]
- [x] 5.4 Idempotencia y decisión humana intocable en el generador (D9): existente ausente →
      crear y contar en `created`; `DRAFT`/`RECOMMENDED`/`REJECTED` → actualizar precio,
      `explanation` y `pricing_rule_id`, contar en `updated`, **sin** evento;
      `APPROVED`/`APPLIED_EXTERNAL` → no tocar, contar en `preserved`. Propiedad sin regla activa
      aplicable → contar en `skipped`, sin error y sin dejar el job en fallo. Tests: dos
      ejecuciones seguidas no duplican filas ni fallan contra el `UNIQUE`; una fila `APPROVED`
      sobrevive intacta a la regeneración; `REJECTED` **sí** se regenera (rechazar ayer no apaga
      esa fecha para siempre); tenant entero sin reglas termina en verde. [R4.2, R4.3, R4.6]
      **Y la tabla de estados se aplica en la sentencia, no solo en la lectura previa** (decisión
      de Jose el 2026-08-17, sobre el hallazgo más grave del panel de QA). El predicado del `ON CONFLICT` gana
      `AND status NOT IN ('APPROVED','APPLIED_EXTERNAL')`, porque la lectura previa es rancia por
      construcción y el panel de QA reprodujo una aprobación de `777.00` quedando en `100.00` sin
      rastro en ningún sumidero. Va acoplado con su otra mitad: una fila que el predicado salta no
      vuelve en el `RETURNING`, y esa cuenta corta era el detector de escritura entre tenants, así
      que en ese camino —y solo en ese— el adaptador pregunta cuáles de las claves que faltan son
      suyas y están decididas; esas van a `UpsertOutcome.preserved` y el resto sigue siendo
      `CrossTenantWriteError`. Test de la carrera para los dos estados preservados, y test de que
      las dos copias del conjunto (`PRESERVED_STATUSES` en `application/` y
      `_STATUSES_A_HUMAN_DECIDED` en `infrastructure/`) son iguales.
- [x] 5.5 `previous_price` es el precio **persistido** del día anterior, no el recién calculado
      para él (D4). Test explícito: día N-1 en `APPROVED` a 120 y recálculo que «habría» dado 90 →
      el día N se acota contra 120. [R3.2, R4.3]
      **Corregido el 2026-08-17 por el panel de QA de `/sdd:review`**: esta tarea
      decía «de modo que dos filas contiguas nunca violan el tope diario entre sí», y eso es
      falso. El tope solo se impone hacia delante y R4.3 prohíbe ajustar al vecino preservado,
      así que el par *(recalculado, preservado)* queda sin acotar y **R4.3 gana a R3.2 en ese
      borde**. No se debe cambio de comportamiento: la garantía real es «el día siguiente a uno
      preservado se acota contra el precio que la manager ve», ya escrita en D4. Falta el test de
      la dirección que **no** funciona —`test_use_cases.py` solo cubre *preservado → recalculado*—
      para que el límite quede fijado y no supuesto.
- [x] 5.6 `TimelineEvent PRICE_RECOMMENDATION_CREATED` **solo** en las recomendaciones nuevas,
      nunca en las actualizaciones (D14), con `actor_type=SCHEDULER` desde el job y `USER` desde
      el endpoint, y `metadata` con `recommendation_id`, `date`, `recommended_price` y
      `pricing_rule_id`. Test: primera ejecución sobre una propiedad emite 60 eventos; la segunda,
      solo el de la fecha que entra por el extremo del horizonte. Los títulos ES/EN ya existen en
      `app/timeline/domain/rendering.py`, así que **no hay i18n nueva** — verificado por el panel
      de i18n de la sección 4 en `rendering.py:211-218`, no hace falta volver a mirarlo. [R4.4]
      **Y la otra mitad de «no se propaga» se prueba aquí, sobre el evento construido.**
      `TimelineEventFactory` solo comprueba que `metadata` sea un `dict`: no hay allowlist de
      claves, y `timeline_events` es append-only, así que lo que entre ahí no se puede redactar
      después. El test asserta las **claves exactas** del `metadata` de los dos eventos —las cuatro
      de arriba y ni una más— sobre el evento que el caso de uso construye, no rastreando el
      fuente: `metadata=asdict(recommendation)` o un `{k: v}` de un bucle meterían la
      `explanation` con todas las aserciones en verde. Lo levantó el panel de seguridad de la
      sección 4, cuyo test de fuente (4.3) reconoce por escrito que no alcanza a esas formas.
- [x] 5.7 **La generación por el reloj no escribe `AuditLog`; la que pide una persona, sí**
      (D12, OQ1 estrechada). Test de las dos vías: tras el barrido del job, `audit_logs` no gana
      ninguna fila —ni de recomendación ni de propiedad—; tras `POST /generate`, gana **una fila
      `PRICE_RECOMMENDATIONS_GENERATED` por propiedad repreciada**, sobre `ENTITY_PROPERTY`, con
      `actor_user_id` y `actor_ip`, y **sin diff**. El rastro del job sigue siendo el
      `TimelineEvent` de 5.6 y el informe de la ejecución. La excepción correspondiente en
      `steering/security.md` la escribe la tarea 8.1. [R4.1, R4.5]
      **Estrechado el 2026-08-17** (decisión de Jose sobre el hallazgo bloqueante que levantó el panel de
      seguridad de esta sección). La redacción anterior eximía las dos vías apoyándose en la
      «ausencia de actor» de la cuarta excepción de la regla 9, que es cierta del reloj y falsa
      del endpoint —recibe `user_id` e `ip`, y esta misma sección firma sus filas de timeline
      como `USER` por eso mismo—. Sin la fila, una manager podía reescribir precios sin rastro en
      **ninguno** de los dos sumideros: en un horizonte ya lleno no se inserta nada, así que D14
      no emite timeline, y el camino manual no lleva lock. El test viejo
      (`test_the_generation_writes_no_audit_row_by_either_route`) fijaba la decisión antigua y se
      ha partido en dos; y `tests/audit/test_pricing_vocabulary.py` fijaba la **ausencia** de
      cualquier verbo de generación, así que ahora fija que hay exactamente uno.
- [x] 5.8 `ListPriceRecommendations` y `DecidePriceRecommendation`: filtros por propiedad, rango de
      fechas y estado dentro del tenant; las tres transiciones legales con su `AuditLog`, y
      `TimelineEvent PRICE_UPDATED_EXTERNAL` al pasar a `APPLIED_EXTERNAL` (D14). Test que
      verifica que **ninguna** de las transiciones invoca operación alguna del `PMSAdapter` —doble
      espía sobre el puerto, Modo 1 del PRD §19— y que `current_price` sigue `NULL`.
      [R5.1, R5.2, R5.3, R5.5]

## 6. API: dos routers y las siete rutas <!-- panel: PASS 2026-08-17 (1.ª ronda: arquitectura, i18n, CI/CD, documentación y QA PASS; tenancy y seguridad FAIL por la misma raíz —aserciones de aislamiento tautológicas sobre sesión marcada—, arregladas y reverificadas PASS). El hallazgo del eco de `loc` en el 422 salió del change: roadmap `validation-error-loc-redaction` -->

<!-- Lo que la 1.ª ronda cambió, porque es lo que un lector de esta sección necesita saber y no
     está en el diff: (a) `tests/pricing/test_api_tenant_scoping.py` es nuevo y existe porque las
     aserciones 404 de aislamiento no podían fallar —el listener de `app/core/db.py` filtra por el
     tenant del llamante en cuanto la primera petición autenticada marca la sesión, así que dan el
     404 correcto sea cual sea el `tenant_id` que pasó el router—; traza el valor en 15 métodos de
     puerto y añade una lectura sobre sesión **sin marcar**. (b) El test del `PMSAdapter` pasó a
     recorrer el AST: la versión anterior miraba `vars(module)` y un import dentro de una función
     —la forma que escribiría quien añadiese una llamada al PMS con prisa— se le colaba, con su
     propio docstring afirmando imposibilidad estructural. (c) R5.2 no tenía test de su mitad de
     `AuditLog` a nivel de API, y el de `POST /generate` no comprobaba `actor_ip`, que es la mitad
     que sostiene el estrechamiento de la regla 9. -->


- [x] 6.1 `backend/app/pricing/api/schemas.py` y `api/dependencies.py` *(nuevos)*: modelos de
      request/response de las siete rutas y el cableado de repositorios/`SqlAlchemyUnitOfWork` al
      estilo de `maintenance`. Los esquemas validan tipos y formas, pero **no son la única
      puerta**: la invariante vive en el dominio (D16). [R1.1, R1.4]
- [x] 6.2 `backend/app/pricing/api/errors.py` *(nuevo)*: tabla `_MAPPING` exhaustiva —404
      `NOT_FOUND` para los dos *not found*, 409 `CONFLICT` para
      `InvalidRecommendationTransitionError`, 422 `VALIDATION_ERROR` para
      `PricingValidationError` y subclases (D15)—. **Ningún `ErrorCode` nuevo.** En la **misma
      tarea**: añadir `pricing` a la lista de módulos del docstring de
      `backend/app/core/error_codes.py` y al conjunto de `_MAPPING` importados por
      `backend/tests/test_openapi_contract.py`, que es el punto ciego que ese docstring documenta
      que ya se materializó una vez con `properties`. [R1.7, R5.4]
      **Tres reglas de redacción del cuerpo, que pidió el panel de seguridad de la sección 2**:
      el handler renderiza `str(exc)` **y no lo loguea** —la forma exacta de
      `maintenance/api/errors.py`, porque una copia en el log mete texto libre de la manager en
      los logs de aplicación, y eso sí lo gobiernan las reglas 3 y 4—; ningún mensaje de error
      hace eco de un valor del llamante sin acotar (el interior de `event_rules` es JSONB que
      ningún esquema de request limita, así que un valor grande sería un cuerpo 422 grande); y
      el `404` de los dos *not found* sale de su mensaje constante, sin que ninguna vía pase un
      `message=` propio —el parámetro existe pero nadie debe usarlo, o los dos 404 de R1.7 dejan
      de ser indistinguibles—.
- [x] 6.3 `backend/app/pricing/api/rules_router.py` *(nuevo)*: `GET`/`POST /api/v1/pricing-rules`,
      `GET`/`PATCH /api/v1/pricing-rules/{id}`, cada una tras su `require(Permission.…)` de 4.1,
      **Puerta de D20, y es esta tarea la que la sostiene**: la sección 3 dejó en pie la
      *capacidad* de repuntar una regla a la propiedad de otro tenant —`property_id` está en
      `_MUTABLE_RULE_COLUMNS`— con el guardián viviendo fuera del módulo. Eso solo es seguro
      mientras no haya llamante. Así que **ninguna de estas rutas se monta antes de que 5.2
      resuelva el `property_id` dentro del tenant**, con sus dos tests (crear y modificar). Lo
      condicionó así el panel de seguridad de la sección 3 al reverificar: la puerta son las
      rutas, no los casos de uso.
      con `summary`/`description` y modelos de respuesta anotados para el OpenAPI. `201` + id en
      la creación. Tests de API en `tests/pricing/test_api_rules.py`. [R1.1, R1.2, R1.3, R1.4]
- [x] 6.4 `backend/app/pricing/api/recommendations_router.py` *(nuevo)*:
      `GET /api/v1/price-recommendations`, `POST /api/v1/price-recommendations/generate` (cuerpo
      `{property_id?}`; sin `property_id` barre el tenant entero, OQ4; devuelve `{created,
      updated, preserved, skipped}`) y `PATCH /api/v1/price-recommendations/{id}` (cuerpo
      `{status}`). Tests en `tests/pricing/test_api_recommendations.py`. [R4.5, R5.1, R5.2, R5.3]
- [x] 6.5 `backend/app/main.py`: montaje de los dos routers y registro del handler de errores del
      módulo. [R1.1, R5.1]
- [x] 6.6 `tests/pricing/test_api_authorization.py` al estilo del de `maintenance`: matriz completa
      ruta × rol sobre las siete rutas (403 para `CLEANER`/`TECHNICIAN`, 401 sin token) y
      **404 —no 403—** para un identificador de otro tenant en las cuatro rutas con `{id}`.
      [R1.2, R1.7, R5.1]

## 7. Job diario en el scheduler <!-- panel: PASS 2026-08-18 (tenancy, seguridad, CI/CD PASS; i18n N/A; arquitectura, QA y documentación FAIL en 1.ª ronda, arreglados y reverificados). Los tres hallazgos: (a) el refactor tocaba las seis llamadas vivas de `_guarded`, la misma metralla que D8 rechaza —rehecho como `_guarded_daily`, ahora una sola llamada preexistente cambia; (b) dos tests pasaban en vacío porque la BD de dev no tiene tenants y el cuerpo del job no llegaba a correr nunca —QA lo probó mutando— y se rehicieron como test del bucle con la lista de tenants stubbeada más tests sobre la BD de test; (c) dos copias de la redacción vieja «pertenece a `revenue`», corregida `docs/celery-jobs.md` y aplazada la de `sdd/specs/` a `/sdd:archive`, que es su dueño. En la 2.ª ronda QA levantó que el test del bucle prometía en su nombre `property_id=None` y `actor=None` sin poder comprobarlos: el stub sustituía la función que los pasa. Resuelto stubbeando `GeneratePriceRecommendationsUseCase.execute` en su lugar y añadiendo la comprobación de que el barrido no escribe ni una fila de `AuditLog`; verificado mutando `actor=None` por un actor real, que ahora pone los dos tests en rojo. -->

<!-- Nota de coste: la BD que toca la tarea de Celery en los tests es la de **dev**
     (`settings.database_url`), no la desechable por ejecución, porque `worker_session_factory`
     no pasa por las fixtures. Es una propiedad preexistente de la suite —`test_dispatch_task.py`
     hace lo mismo desde `access-notifications`— y por eso el bucle se prueba con la lista de
     tenants stubbeada. Los paneles de seguridad y CI/CD la revisaron y la dieron por heredada,
     no por introducida aquí. Candidata a change propio: redirigir `settings.database_url` en
     `tests/conftest.py` como ya se hace con `settings.redis_url`. -->


- [x] 7.1 `backend/app/scheduler/schedule.py`: `DailySchedule(hour, lock_ttl)` congelado y
      `DAILY_JOBS = {"generate_price_recommendations": DailySchedule(hour=6,
      lock_ttl=timedelta(hours=3))}`, con `beat_schedule()` derivado de **las dos** tablas y
      siguiendo siendo la única fuente (D8). Actualizar el docstring del módulo y **sustituir la
      nota de las líneas 17-19** que atribuye este job a `revenue` por la razón real por la que
      `send_checkin_reminders` sigue ausente. Dejar escrito que **06:00 es UTC**, porque
      `app/worker.py` fija `celery_app.conf.timezone = "UTC"` a propósito. [R4.1, R4.7]
- [x] 7.2 Tests en `backend/tests/scheduler/test_schedule.py`: las claves de `CADENCES` y
      `DAILY_JOBS` son **disjuntas**; toda tarea registrada en Celery aparece en **exactamente
      una** de las dos; y **ninguna tarea diaria deriva su TTL de `lock_ttl_for`** —que devuelve
      cadencia × 3 y para un job diario serían tres días de bloqueo tras un worker muerto—.
      [R4.7]
- [x] 7.3 `backend/app/scheduler/tasks.py`: tarea `generate_price_recommendations` con el mismo
      mecanismo de lock que el resto (`specs/celery-jobs.md` R1) pero tomando el TTL explícito de
      `DailySchedule`, llamando al caso de uso de 5.3 por tenant dentro del bucle de
      `run_for_every_tenant`, sin `property_id` y con `actor=None`. Test en
      `tests/scheduler/test_generate_price_recommendations.py`: se ejecuta por tenant, respeta el
      lock, y una ejecución repetida es idempotente (forma del `test_repeated_execution.py` ya
      existente). [R4.1, R4.2, R4.7]

## 8. Steering, notas corregidas y documentación <!-- panel: PASS 2026-08-18 (arquitectura y documentación PASS; tenancy N/A; seguridad y QA PASS con un hallazgo no bloqueante cada uno, los dos arreglados). Seguridad: la excepción 5 prometía «un sumidero hecho a medida» y ese sumidero cubre solo las inserciones —un día reprecio no emite timeline y la tabla no tiene `updated_at`, así que de 59 precios reescritos no queda rastro en ninguna tabla—; la frase era literalmente cierta y se leía más ancha de lo que es, así que ahora lo dice. QA: `design.md` seguía diciendo «fila 14» en dos sitios, un ordinal que mi propia nota de 8.2 declaraba falso sin cerrarlo; corregido con el porqué. Arquitectura comprobó contra el código las afirmaciones del README y de `docs/pricing.md` (cuatro capas, nueve tareas de beat, 17 dominios, orden de guardrails, precedencia de reglas, sin migración) y seguridad las seis de la excepción, más la aritmética del censo (22 filas, 18 columnas). -->


- [x] 8.1 `sdd/steering/security.md`: **quinta excepción nombrada de la regla 9** (OQ1, aprobada en
      el gate de `/sdd:design` el 2026-08-16 y **estrechada el 2026-08-17**). Alcance literal y sin
      margen: **solo la generación de recomendaciones por el job del reloj**; **no** exime
      `POST /generate`, **no** exime ninguna decisión humana sobre una recomendación, **no** exime
      nada de `PricingRule` y **no** dice nada sobre otros jobs. Razón escrita: ausencia de actor
      (como la cuarta excepción) más un sumidero hecho a medida (como la primera), y el volumen
      —~120 filas anónimas al día con dos viviendas, 43.800 al año— en la tabla cuyo índice por
      actor existe para otra pregunta. [R4.1]
      **Y la razón hay que escribirla sabiendo por qué se estrechó**: la redacción
      aprobada el 2026-08-16 cubría también el endpoint, y «ausencia de actor» es falsa de él. Las
      excepciones 2 y 3 de la propia regla 9 dicen literalmente que «no exime la lectura con actor
      humano o iniciada por API», así que la entrada no puede insinuar que el camino humano quede
      cubierto. Debe además **nombrar la acción que sí se escribe** —
      `PRICE_RECOMMENDATIONS_GENERATED`, una fila por propiedad, sobre `ENTITY_PROPERTY` — para
      que la regla diga lo que el código hace.
      **Esta tarea es puerta de embarque del change, no su cola.** Hasta que la línea exista en
      `security.md`, el código de la sección 4 cita una excepción que no está escrita —y la regla 9
      es explícita en que «la aprobación en un design no es lo que amplía la regla»: lo es esa
      línea. Es el mismo recorrido que hizo la cuarta excepción por la tarea 9.1b de `maintenance`.
      El comentario de `app/audit/domain/actions.py` **cita** esta entrada y no la reformula, así
      que la formulación normativa —el volumen incluido— vive aquí y en ningún otro sitio. Lo
      condicionó el panel de seguridad de la sección 4.
- [x] 8.2 `sdd/steering/security.md`: **fila 14 del censo de la regla 11** para
      `price_recommendations.explanation`, con excepción propia con la forma de la excepción 3
      —el valor no es nuestro y no lo hemos ido a buscar: lo teclea un usuario autenticado con
      RBAC, sobre el precio de su propia vivienda, acotado a 100 caracteres por 2.2— y la nota
      explícita de que **no se propaga** a `audit_logs.changes` ni a `timeline_events.metadata`
      (OQ2, aprobada en el mismo gate; el test que lo sostiene es 4.3). [R6.1]
      **Y una fila más, que levantó el panel de seguridad de la sección 4: `pricing_rules.name`.**
      Este change es el primer escritor de esa tabla y `name` es texto libre que teclea una
      manager autenticada, y a diferencia de las cinco columnas JSONB es un **escalar**, así que
      `diff()` lo guarda literal en `audit_logs.changes`. Con la nota de que las cinco JSONB
      **sí** son redact-only por `REDACT_ONLY_FIELDS`, de modo que el censo diga lo que el código
      hace y no lo que se esperaba que hiciera. El criterio del censo es «quién escribe la
      columna», y aquí la escribe ella.
      **Pero NO con la forma de la excepción 3** — lo corrigió el panel de seguridad al
      reverificar la sección 5, y una redacción anterior de esta misma tarea decía «va con la
      forma de la excepción 3». La cláusula que define esa excepción es «**no se propaga**», y
      `owner_approvals.response_notes` la cumple porque está **fuera** de `AUDITABLE_FIELDS`, así
      que `ChangeSet` la rechaza por construcción. `name` está **dentro** y `_rule_change_set` lo
      difunde literalmente: copiar esa forma pondría una promesa de no-propagación sobre un valor
      que demostrablemente propaga, que es exactamente la fila del censo que miente. Va con el
      terreno que este módulo ya usa para `properties.access_notes`: la regla 11 gobierna un
      **valor de la regla 3**, y la etiqueta de una regla de precios no lo es. El comentario de
      `app/audit/domain/value_objects.py` ya está corregido en ese sentido.
      **Y hay que tocar la fila 1 del censo, `audit_logs.changes`, no solo añadir filas nuevas.**
      Hoy declara como escritores vivos «`user-management` … y quien audite documentos de huésped»,
      y este change es un escritor vivo más —dos `entity_type`, y uno de ellos mete un escalar de
      texto libre tecleado por la manager—. La regla 11 dice de las columnas vivas que «quien
      escriba después se atiene al que hay, **no deriva uno nuevo**», y este fichero ya sentó el
      precedente al añadir `auth-account-recovery` a la fila de `notification_logs.subject`/`body`
      «porque esta tabla dice quién escribe cada columna **hoy**». Sin esto, el siguiente change
      lee la fila 1, concluye que `ChangeSet` la hace segura y no se enterará de que un escalar
      censado en otra fila aterriza ahí literal.
      **Esta tarea es también puerta de embarque, por la misma razón que 8.1** (panel
      de seguridad de la sección 5). La sección 5 ya dejó vivo el escritor: `_rule_change_set`
      mete `pricing_rules.name` —texto libre que teclea la manager— en `audit_logs.changes`, una
      columna cuya forma en el censo es **estructurada** («el valor no sobrevive en absoluto, ni
      siquiera enmascarado»). La regla 11 dice de las columnas vivas que «quien escriba después se
      atiene al que hay, **no deriva uno nuevo**», así que legitimar la cuarta excepción es
      exactamente el trabajo de esta tarea — y sin la cláusula, el change podía embarcar con el
      escritor vivo y el censo callado. Precedente literal de la regla 11: «una fila del censo que
      miente es peor que una columna sin censar» (la lección de `owner_approvals.response_notes`).

      **⚠ Esta tarea quedó desfasada por dos cosas, y hay que releerla antes de ejecutarla.
      Averiguado el 2026-08-18 al coordinar con la sesión de `rule11-ownership-single-source`,
      antes de escribir nada.**

      1. **La redacción que esta tarea cita ya no es la de `main`.** El árbol de este worktree
         va por detrás: aquí `security.md` dice «Trece columnas», y en `main` dice **«Dieciséis
         columnas, veinte filas»**, con un párrafo nuevo que separa el recuento de columnas del
         de filas (una columna con tres escritores ocupa tres filas). Escribir contra el texto
         de este worktree es corregir una copia muerta. **Rebasar sobre `main` primero** — que
         además hace falta por 8.5, ya que #98 mergeó el 2026-08-17.
      2. **La parte de «tocar la fila 1 del censo» NO se hace — decidido por Jose el
         2026-08-18**, tras plantearle la desviación (regla 4 del flujo: la tarea aprobada
         mandaba lo contrario, así que no se cambia en silencio). El change
         `rule11-ownership-single-source` (en `/sdd:review`, **sin PR y sin mergear**, así que
         el orden no está garantizado) **elimina la lista de escritores vivos de
         `audit_logs.changes`** y la sustituye por el punto de paso: `AuditLogFactory.build` +
         `ChangeSet`. Su R4.1 prohíbe enumerar módulos ahí, precisamente porque esa lista es la
         que nadie actualiza — hoy ya está desfasada en once módulos. Añadir `revenue-pricing`
         sería la copia número trece, la misma semana que llega el change que la abole. Y es
         lo correcto **con cualquiera de las dos versiones del fichero**: pasar por la factoría
         es lo que satisface «se atiene al que hay, no deriva uno nuevo»; ser nombrado, no.
         Lo que sí sigue en pie de esta tarea son las **dos filas nuevas**
         (`price_recommendations.explanation` y `pricing_rules.name`) con su razonamiento, que
         no se solapan con esa sesión.

      **Y tres cosas más que trae esa coordinación:**
      - El numeral del intro es el **único** conflicto real entre las dos sesiones: las dos lo
         tocamos. Con sus 21 filas, estas dos columnas dejan **dieciocho columnas y veintitrés
         filas**. Quien mergee segundo reconcilia esa línea.
      - Su change añade `backend/tests/test_rule11_ownership.py`, que **pone en rojo cualquier
         bloque fuera de `security.md` que nombre una columna del censo y diga quién la
         escribe**. Escanea `sdd/` (sin `sdd/changes/`), `docs/` (sin `docs/adr/`),
         `backend/app/`, `backend/alembic/versions/` y `backend/tests/`. O sea: la frase natural
         para la spec —«`revenue-pricing` es el primer escritor de
         `price_recommendations.explanation`»— va a fallar. Citar la tabla, no reproducir la
         propiedad.
      - Ese test tiene una lista **hardcodeada** de las columnas censadas y de los nombres de
         tabla (`SINK_TERMS`). Si esas filas nuevas no se añaden ahí, las copias de propiedad
         sobre *nuestras* columnas quedan sin detectar — es su residual 3, declarado.

      **Comprobación previa que pidió esa sesión y conviene hacer**: que `name` esté en
      `AUDITABLE_FIELDS["PRICING_RULE"]` (lo está, `app/audit/domain/value_objects.py`), porque
      toda la fila de `pricing_rules.name` se apoya en que `diff()` lo propaga literal.

      **Los dos numerales, con precisión — y no son el mismo caso** (aclarado por esa sesión
      el 2026-08-18, sobre su rama `775ae12`):
      - **Línea ~108**, «**Dieciséis columnas** del esquema son texto o JSON libre…»: esa
        sesión **no la toca**, porque no añade ninguna columna. Nosotros sí añadimos dos, así
        que esa línea es **solo nuestra** y pasa a **dieciocho**. No hay conflicto aquí.
      - **Línea ~110**, «Dieciséis columnas, **veinte filas**»: esa sesión la sube a
        **veintiuna** (parte `notification_logs.subject`/`body`). Nosotros sumamos dos filas.
        **Este es el único conflicto real** entre las dos sesiones. Si la suya ya mergeó:
        veintitrés. Si no: veintidós, y quien mergee segundo suma la que falte.

      **Texto verbatim de la fila 1 después de su change**, para que quien reconcilie tenga
      las dos versiones sin ir a buscarlas (NO hay que escribirlo nosotros — lo trae su
      change; se guarda aquí solo como referencia):

      > \| `audit_logs.changes` \| estructurada \| **`AuditLogFactory.build` + `ChangeSet`**, el
      > punto de paso — no una lista de módulos. Quien pase por ahí no puede derivar un contrato
      > propio: `ChangeSet` rechaza por construcción un `entity_type` sin campos declarados y
      > todo campo fuera de `AUDITABLE_FIELDS`, y para un campo de `REDACTED_FIELDS` la única
      > forma disponible es `redacted()`, que escribe `{"changed": true}`. **Lo que esto no
      > cierra** […]: `AuditLog` es un dataclass mutable y `SqlAlchemyAuditLogRepository.add`
      > copia `changes` tal cual —revalida `actor_guest_token_hash` y no esta columna—, así que
      > quien construya el entity a mano o mute el campo después de `build()` llega a la columna
      > sin pasar por el contrato. Hoy no lo hace nadie: la única construcción en `app/` es
      > `audit/domain/services.py` \|

      Y su change está **FAIL en review con hallazgos abiertos** a 2026-08-18, o sea que esa
      forma todavía puede moverse: una razón más para escribir contra `main` y no contra ella.

      **EJECUTADO el 2026-08-18. Lo que salió distinto de lo planeado, y por qué:**
      - **«Fila 14» no existe.** El censo real de `main` tenía ya 20 filas, así que las dos
        nuevas son la 21 y la 22, y las columnas pasan de dieciséis a dieciocho. El ordinal
        del título de esta tarea (y el de `design.md`, tabla de ficheros afectados) se escribió
        cuando se creía que el censo tenía trece columnas. **Y el número se había filtrado al
        código**: seis sitios —`audit/domain/value_objects.py`, `pricing/api/schemas.py` y
        cuatro tests— decían literalmente «sink 14 of rule 11». Todos corregidos para citar la
        tabla y no una posición: el censo crece y un ordinal caduca en silencio sin dejar de
        sonar preciso. Es la misma lección que la sesión de `rule11-ownership-single-source`
        aplica a la propiedad de las columnas.
      - **`explanation` es excepción 5, no «la forma de la excepción 3».** Las excepciones 3 y
        4 ya estaban tomadas (`messaging-ai` ensanchó la 3 y abrió la 4), y sobre todo: la
        excepción 3 dice de sí misma «**no autoriza a un escritor nuestro**», y `explanation`
        **la escribe nuestra plantilla cerrada**. Lo único que no componemos es el `name` que
        la manager teclea en su regla de temporada o de evento. Así que la excepción se enuncia
        sobre **el valor incrustado** y no sobre la columna, que es lo que la hace cierta.
      - **`pricing_rules.name` va sin excepción**, como ya anticipaba la tarea: se censa porque
        el criterio es quién escribe la columna, y se deja fuera del alcance de la regla 11
        porque esta gobierna valores de la regla 3 y la etiqueta de una regla de precios no lo
        es. La fila dice explícitamente que **sí propaga** a `audit_logs.changes`.
- [x] 8.3 `backend/app/integrations/domain/ports.py` líneas 93-94: corregir la nota de ARI —
      `update_price`, `block_dates` y `get_availability` llegan con **un change de ARI propio,
      cuando exista quien las consuma**, no con `revenue` (D19). Grep por la redacción vieja en
      todo el árbol para que no quede ninguna copia prometiendo lo mismo. [R4.7]
      **Dos copias ya localizadas por el panel de documentación de la sección 7**, ambas de la
      redacción de `schedule.py` y no de la de ARI: `docs/celery-jobs.md:41-43` («pertenece a
      `revenue`»), **ya corregida en la sección 7** porque es documentación publicada y el
      change es dueño del hecho; y `sdd/specs/celery-jobs.md:157-159` («Dos jobs de PRD §8.3 no
      están aquí … → `revenue`»), que **NO se toca aquí**: es spec viva, y la regla 7 del flujo
      reserva `sdd/specs/` a `/sdd:archive`, post-merge. Queda anotada para que ese paso la
      encuentre en vez de descubrirla el siguiente change.
      **Y una tercera, del panel de arquitectura de la sección 8**: `sdd/specs/local-environment.md`
      (~línea 270) habla de «las ocho tareas periódicas». **No es falsa** —ocho siguen siendo las
      periódicas, y la novena va por hora del día— pero queda incompleta ahora que beat despacha
      nueve. Misma regla 7: es spec viva, la toca `/sdd:archive`.
- [x] 8.4 Regenerar **las dos mitades del puente** del contrato (`steering/documentation.md`):
      `make openapi` para `backend/openapi.json`, y el artefacto derivado del frontend
      `frontend/lib/api/generated/openapi.d.ts`. Desde un worktree el comando documentado
      (`cd frontend && npm run api:generate`) **no funciona**: usar la secuencia verificada de
      `sdd/project.md` (`mkdir -p /backend` → `docker compose cp` → `ln -sfn /app /frontend` →
      `npm run api:generate`) y commitear los dos ficheros en el mismo PR. [R1.1, R5.1]
- [x] 8.5 `docs/pricing.md` *(nuevo)* — página de capability orientada a *cómo se usa y se opera*:
      qué es Modo 1 (el sistema recomienda, nunca publica), cómo se escribe una regla y qué
      significa cada uno de los cinco JSONB, cómo referenciar el catálogo `ES_NATIONAL`, cuándo
      corre el job y cómo forzarlo, y cómo se lee una `explanation`. Enlazar a las specs, no
      duplicarlas. Actualizar `README.md` de raíz con el módulo nuevo en la sección Estructura.
      [R6.1]
      **Ojo al orden con `compose-stacks-diagnostic`, que ya tiene PR abierto (#98) y toca el
      mismo `README.md`** (avisado por esa sesión el 2026-08-17). Sus dos puntos de contacto son
      la lista de comandos `make` (~líneas 28-31, una línea nueva) y la sección «Postura de red
      del stack local» (~90-101, reescrita: la redacción vieja enmarcaba los stacks huérfanos
      como colisión de puertos, y eso dejó de ser cierto cuando `worktree-parallel-stack` hizo
      que un worktree enlazado no publique ninguno). Esta tarea inserta en **Estructura**, no en
      la lista de comandos —este change no añade ningún target de `make`—, así que los dos diffs
      son hunks disjuntos y git los mezcla solo. Como #98 va por delante, lo barato es
      **rebasar sobre `main` después de que mergee**, no resolver el conflicto en el PR.
      **Y antes de escribir, comprobar `sdd/project.md`**: su narrativa del stack por worktree
      —que este change cita para el workaround de `api:generate`— describe la misma postura de
      red que #98 reescribe en el README. Si esa redacción cambia, citar la vieja es
      exactamente el fallo de «corregir una afirmación sin grepear la redacción vieja».

## 9. Verification <!-- verificada 2026-08-18, y AUDITADA por el panel de QA de la sección 8, que reprodujo las cifras por su cuenta contra el stack vivo en vez de creérselas: suite 7937/39 skipped, las cuatro guardas 1263, `alembic check` sin operaciones nuevas, `api:check` limpio y `test_the_committed_contract_matches_the_code` en verde. Confirmó también que no quedó residuo de sonda (los tres scripts fuera del contenedor, `tasks.py` sin diff) y cerró la objeción que más importaba sobre 9.5: un barrido que no hubiera tocado nada daría `{created:0, updated:0}`, y el del reloj dio `updated:59, preserved:1` con `audit_logs` en 6→6 — hizo trabajo sin auditar, que es exactamente lo que la excepción 5 promete. -->


- [x] 9.1 Suite completa en verde desde el worktree:
      `docker compose exec backend uv run pytest` (con el stack parado,
      `docker compose run --rm backend uv run pytest`).
- [x] 9.2 `docker compose exec backend uv run pytest tests/test_layering.py
      tests/test_openapi_contract.py tests/test_route_authorization.py
      tests/test_tenant_filter.py` — las cuatro guardas transversales que un módulo nuevo con
      routers puede romper sin que se note en sus propios tests.
- [x] 9.3 `docker compose exec backend uv run alembic check` — confirma que **no hace falta
      migración**: `pricing_rules`, `price_recommendations` y el enum ya están en
      `96d526599bc1_domain_foundation_financial` y este change no toca modelos.
- [x] 9.4 Sin deriva de contrato: `backend/openapi.json` y
      `frontend/lib/api/generated/openapi.d.ts` regenerados y commiteados (8.4); comprobación del
      lado del frontend con `npm run api:check` dentro del contenedor, por la misma razón que 8.4.
- [x] 9.5 Comprobación manual del flujo extremo a extremo contra el stack del worktree (sin
      navegador: solo API, `docker compose exec` y `psql`): crear una regla → `POST
      /price-recommendations/generate` → leer el horizonte de 60 días y su `explanation` →
      aprobar una → marcarla `APPLIED_EXTERNAL` → verificar los dos `TimelineEvent`, los
      `AuditLog` de las decisiones y **la ausencia** de `AuditLog` de la generación → repetir el
      `generate` y confirmar que la aprobada sigue intacta.
