# Precio recomendado por reglas (Modo 1)

## Purpose

Esta capacidad propone un precio por vivienda y día para los próximos 60 días, calculado con
una fórmula determinista sobre reglas que la manager escribe, acotado por sus guardrails y
acompañado de la explicación en texto de cómo se ha llegado a él. Cada madrugada se regenera
el horizonte entero; la manager aprueba o rechaza cada día y, cuando sube el precio a la OTA
a mano, lo anota.

Es el **Modo 1 de PRD §19: el sistema recomienda y nunca publica**. No hay una sola llamada al
PMS en todo el flujo — ni para leer el precio vigente ni para escribir el propuesto — y la IA
no participa en el cálculo ni en la redacción (`steering/product.md` principio 5). Es también
quien da a `pricing` sus capas `application/` y `api/`: hasta este change las dos tablas
existían sin ningún escritor.

Cómo se opera: [`docs/pricing.md`](../../docs/pricing.md).

## Requirements

### Reglas de pricing administrables

- WHEN un usuario con `MANAGE_PRICING_RULES` emite `POST /api/v1/pricing-rules` con una regla
  válida, THE SYSTEM SHALL persistirla en el tenant de la sesión y devolver `201` con la regla
  almacenada, cuyo `id` es lo que toman las otras tres rutas.
- THE SYSTEM SHALL operar `GET /api/v1/pricing-rules`, `GET /api/v1/pricing-rules/{rule_id}` y
  `PATCH /api/v1/pricing-rules/{rule_id}` únicamente sobre reglas del tenant de la sesión.
- WHERE `property_id` es `NULL`, THE SYSTEM SHALL aplicar la regla a toda vivienda del tenant
  que no tenga regla propia activa; WHERE la vivienda tiene regla propia activa, THE SYSTEM
  SHALL usar esa.
- WHEN dos reglas activas compiten en el mismo ámbito, THE SYSTEM SHALL elegir la de
  `updated_at` más reciente, desempatando por `id`. Nada en el esquema impide el empate, y sin
  el desempate dos ejecuciones del mismo job podrían tarifar el mismo día distinto.
- THE SYSTEM SHALL resolver qué regla aplica en una **función pura** del dominio
  (`resolve_rule`) y no en un `ORDER BY … LIMIT 1` del repositorio, de modo que el job
  resuelva N viviendas contra una única lista ya cargada en vez de emitir una consulta por
  vivienda.
- IF `min_price > max_price`, o `base_price` cae fuera de `[min_price, max_price]`, o
  `max_daily_change_pct` cae fuera de `[0, 100]` o lleva más de dos decimales, o `name` está
  vacío o pasa de 200 caracteres, THEN THE SYSTEM SHALL rechazar con `422` **nombrando el campo
  que falla** y sin persistir nada.
- IF `weekday_modifiers` o cualquiera de los cuatro arrays no respeta su esquema, THEN THE
  SYSTEM SHALL rechazar con `422` nombrando la columna. El conjunto de claves de cada entrada
  ha de ser **exactamente** uno de los admitidos, así que una entrada con claves de más, de
  menos o de dos formas mezcladas se rechaza:
  - `weekday_modifiers`: objeto cuyas claves son nombres de día en inglés minúscula
    (`monday`…`sunday`) y cuyos valores son porcentajes.
  - `lead_time_rules`: `{days_before, modifier_pct}`, con `days_before` entero `>= 0`.
  - `occupancy_rules`: `{occupancy_pct_above, modifier_pct}`, con el umbral en `[0, 100]`.
  - `seasonality_rules`: `{name, start_month, start_day, end_month, end_day, modifier_pct}`,
    con los días validados contra un año bisiesto para que el 29 de febrero siga siendo
    declarable.
  - `event_rules`: **dos formas** y sólo dos — la literal `{name, date, modifier_pct}` con
    fecha ISO 8601 completa, y la de catálogo `{holidays, modifier_pct}`.
- THE SYSTEM SHALL admitir como máximo 50 entradas por array y 100 caracteres por nombre de
  modificador.
- THE SYSTEM SHALL **no hacer eco del valor del llamante** en ningún mensaje de estos `422`:
  las cinco columnas son JSONB de interior libre que ningún esquema de petición acota, así que
  un valor devuelto haría el cuerpo del error tan grande como lo que se envió. Los mensajes
  nombran el **conjunto admitido** — los siete días, los catálogos válidos, el formato de
  fecha — que es lo que los hace accionables. Incluye la clave desconocida de un objeto y el
  `str(ValueError)` de una fecha mal formada, que citaría la cadena entera.
- WHEN un `PATCH` llega, THE SYSTEM SHALL validar la regla **completa** y no sólo los campos
  entrantes, porque subir `min_price` hay que juzgarlo contra el `max_price` ya guardado.
- IF la validación rechaza un `PATCH`, THEN THE SYSTEM SHALL restaurar la entidad desde una
  instantánea previa, de modo que ni sus campos ni su `updated_at` se muevan.
- WHEN un `PATCH` no mueve ningún campo, THE SYSTEM SHALL no tocar `updated_at` ni escribir
  fila de auditoría alguna.
- IF el `rule_id` pedido no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL responder
  `404` con **el mismo cuerpo constante en los dos casos**, sin revelar su existencia. Un `404`
  cuyo cuerpo distinguiera «desconocido» de «de otro» sería un oráculo de enumeración.
- IF el `property_id` del cuerpo no nombra una vivienda del tenant, THEN THE SYSTEM SHALL
  responder `422` y no `404`: es un campo del cuerpo que nombra algo que no está, no un recurso
  ausente en la ruta.
- WHEN se crea o modifica una regla, THE SYSTEM SHALL registrar un `AuditLog`
  (`PRICING_RULE_CREATED` / `PRICING_RULE_UPDATED`) con actor, IP y el diff de los campos que
  se movieron.
- THE SYSTEM SHALL hacer llegar las cinco columnas JSONB al rastro de auditoría **sólo** como
  `{"changed": true}`, por estar en `REDACT_ONLY_FIELDS`: cargan el `name` que la manager
  escribe en una temporada o un evento, y ese texto no debe propagarse a un segundo sumidero.
  `name` de la regla **sí** se audita literalmente — es su etiqueta, un escalar acotado, y
  renombrar «Madrid base» a «Madrid verano» es exactamente lo que un rastro debe mostrar.

### Precio recomendado determinista

- WHEN se calcula el precio de una fecha, THE SYSTEM SHALL aplicar los modificadores en el
  orden de PRD §7.17 — **día de la semana → anticipación → ocupación → temporada → eventos** —
  cada uno multiplicativo sobre el resultado del anterior (`precio × (1 + pct/100)`).
- WHERE varias `lead_time_rules` aplican (`days_before <= umbral`), THE SYSTEM SHALL usar la de
  **menor** `days_before`; WHERE varias `occupancy_rules` aplican
  (`ocupación >= occupancy_pct_above`), THE SYSTEM SHALL usar la de **mayor**
  `occupancy_pct_above`; WHERE varias reglas de temporada o de evento casan, THE SYSTEM SHALL
  aplicarlas **todas**, en el orden en que están declaradas. Un producto de factores conmuta,
  pero la explicación no, y el orden fijo es lo que la hace reproducible.
- THE SYSTEM SHALL indexar el día de la semana por `date.weekday()` y no por `strftime('%A')`,
  que sigue el locale del proceso que ejecute el job.
- WHERE una `seasonality_rule` tiene el fin antes del inicio, THE SYSTEM SHALL leer el rango
  como **anual recurrente que cruza el fin de año** — 20 dic a 6 ene — y casar las dos mitades.
  Leerlo como rango vacío haría indeclarable la temporada más obvia que hay.
- THE SYSTEM SHALL calcular la ocupación como el porcentaje de noches ocupadas en la ventana
  semiabierta `[fecha_ejecución + 1, fecha_ejecución + 31)`, derivada de las `reservations`
  locales y **sin llamar al PMS**: las reservas locales ya son la proyección del calendario del
  PMS.
- THE SYSTEM SHALL contar una estancia como las noches `[check_in_date, check_out_date)` — el
  día de salida no es noche — y contar una sola vez las noches compartidas por reservas
  solapadas.
- THE SYSTEM SHALL tratar como **libre** sólo `CANCELLED` y `NO_SHOW`; todo lo demás cuenta
  como ocupado, `PENDING` incluido, porque es una noche que el calendario del PMS ya bloquea.
- THE SYSTEM SHALL leer la ocupación **una vez por vivienda y ejecución**, no una por día del
  horizonte: PRD §7.17 la define respecto de *hoy*, no de la fecha que se tarifa.
- THE SYSTEM SHALL operar en `Decimal` de extremo a extremo, entrando todo número de JSONB por
  `Decimal(str(v))` y nunca por `Decimal(v)`, que tomaría un `float` literalmente y arrastraría
  su ruido por cada multiplicación posterior.
- THE SYSTEM SHALL redondear **una sola vez** en toda la cadena, a dos decimales y
  `ROUND_HALF_UP`, sobre `recommended_price` y después de los guardrails.
- THE SYSTEM SHALL implementar el cálculo como **función pura** — sin reloj, sin sesión, sin
  red — de modo que la reproducibilidad se sostenga por la firma y no por disciplina.
- THE SYSTEM SHALL devolver del cálculo el **rastro** y no sólo el precio: el precio base, cada
  modificador aplicado con su nombre y porcentaje, y cada guardrail que recortó. Reconstruir esa
  cadena en un segundo sitio es cómo dos renderizados del mismo precio se separan sin que ningún
  test lo note.
- THE SYSTEM SHALL incluir un catálogo embebido de festivos **nacionales** de España para
  2025-2027: nueve fechas fijas más el Viernes Santo, diez por año, escrito año a año y no
  computado, para que sea una constante que un test fija y no un algoritmo que deriva.
- THE SYSTEM SHALL aceptar `ES_NATIONAL` como **único** identificador de catálogo que una
  `event_rule` puede referenciar. `ASSUMPTION`: el PRD fija la lista de festivos pero no qué
  modificador merece cada uno, así que el catálogo aporta las fechas y el porcentaje lo pone la
  regla que lo referencia. Los festivos **locales de municipio** siguen siendo `event_rules`
  manuales, como declara PRD §19, y el catálogo **no** es el calendario laboral del BOE: ese
  sustituye festivos en domingo por comunidad autónoma, una decisión por región que este
  catálogo no puede tomar.

### Guardrails obligatorios

- WHEN se genera el horizonte, THE SYSTEM SHALL recorrerlo en **orden ascendente de fecha** y
  acotar cada precio a ±`max_daily_change_pct` % respecto del **precio persistido del día
  inmediatamente anterior** — el que queda en su fila y la manager ve, no el que un recálculo
  «habría» dado para ese día.
- WHERE la fecha es el primer día del horizonte, THE SYSTEM SHALL no aplicar el tope diario,
  porque no hay base contra la que medirlo.
- THE SYSTEM SHALL medir el tope sobre el **valor absoluto** de `max_daily_change_pct`: un
  negativo invertiría la banda —techo por debajo del suelo— y convertiría una subida modesta en
  una caída fuerte. El validador acota la columna a `[0, 100]`, pero guarda la API y no esta
  función.
- WHEN el precio calculado cae fuera de `[min_price, max_price]`, THE SYSTEM SHALL acotarlo al
  límite correspondiente.
- THE SYSTEM SHALL aplicar **el tope diario primero y los límites absolutos al final**, de modo
  que ningún precio emitido quede jamás fuera de `[min_price, max_price]` aunque el tope diario
  lo permitiera.
- WHEN un guardrail recorta el precio, THE SYSTEM SHALL dejar constancia en la `explanation` de
  cuál actuó; WHERE ninguno recortó, THE SYSTEM SHALL no mencionarlo.
- THE SYSTEM SHALL registrar en el rastro del tope diario **contra qué midió** — el precio del
  día anterior y el porcentaje —, que no se puede recuperar del par
  `precio_antes`/`precio_después`.

### Generación diaria y bajo demanda

- WHEN el reloj alcanza las **06:00 UTC**, THE SYSTEM SHALL generar el horizonte de 60 días
  —`[fecha_ejecución + 1, fecha_ejecución + 61)`— de cada vivienda `ACTIVE` con regla activa
  aplicable, para cada tenant activo.
- THE SYSTEM SHALL ejecutar el job bajo el mismo mecanismo de lock que el resto
  (`specs/celery-jobs.md`), con un TTL **declarado explícitamente** de 3 h y no derivado de una
  cadencia; perder el lock es `skipped` y no un fallo.
- THE SYSTEM SHALL exponer la **misma** generación en
  `POST /api/v1/price-recommendations/generate`, de modo que una regla recién editada surta
  efecto sin esperar a las 06:00. WHERE el cuerpo nombra un `property_id`, THE SYSTEM SHALL
  limitarse a esa vivienda; WHERE se omite, THE SYSTEM SHALL barrer la cartera activa del
  tenant.
- THE SYSTEM SHALL ejecutar esa generación de forma **sincrónica**: el trabajo está acotado por
  construcción — 60 días por una cartera que alguien gestiona físicamente— y R4.5 pide contar
  cuántas filas creó y actualizó, que sólo se sabe al final.
- WHEN ya existe una recomendación para `(property_id, date)`, THE SYSTEM SHALL actualizarla
  mediante `INSERT … ON CONFLICT (property_id, date) DO UPDATE`, de modo que el job sea
  idempotente y dos ejecuciones no puedan fallar una contra otra. THE SYSTEM SHALL derivar
  `created` y `updated` de `RETURNING xmax = 0` — de la **sentencia** y no de un recuento previo,
  que sería una carrera.
- THE SYSTEM SHALL reescribir en el conflicto **sólo** `recommended_price`, `explanation` y
  `pricing_rule_id`, de modo que el `status` y el instante de creación guardados sobrevivan.
- IF la recomendación existente está en `APPROVED` o `APPLIED_EXTERNAL`, THEN THE SYSTEM SHALL
  preservarla intacta: una decisión humana no se sobrescribe por una regeneración.
- THE SYSTEM SHALL hacer cumplir esa preservación **en la propia sentencia**, con un predicado
  sobre el `status` en el `ON CONFLICT … WHERE`, y no sólo con el filtro previo del caso de uso:
  ese filtro lee el horizonte *antes* de que la sentencia corra, así que una aprobación que
  aterrice entremedias quedaría sobrescrita — sin fila de auditoría ni de timeline que lo
  mostrara. Una lectura previa no es control de concurrencia.
- THE SYSTEM SHALL regenerar las filas en `REJECTED`, que siguen `REJECTED` después.
- WHERE una vivienda no tiene ninguna regla activa aplicable, THE SYSTEM SHALL omitirla
  contándola en `skipped`, sin error y sin dejar el job en fallo.
- IF el `property_id` del cuerpo es desconocido, de otro tenant, o no está `ACTIVE`, THEN THE
  SYSTEM SHALL responder `422`. Los dos primeros comparten un mensaje constante; «tuya pero
  inactiva» se nombra, porque es un hecho sobre la cartera **propia** del llamante y por tanto
  no es oráculo, y es la respuesta accionable.
- THE SYSTEM SHALL abrir **una transacción por vivienda** y no una por tenant, de modo que una
  vivienda que falle no descarte los horizontes ya escritos de las anteriores.
- IF una vivienda falla, THEN THE SYSTEM SHALL abandonar su unidad, contarla en `failed`,
  registrarla en el log con su identificador y **seguir** con la siguiente. Sin ese rollback la
  sesión queda inservible y una sola regla mala se llevaría la cartera entera.
- IF abandonar también falla, THEN THE SYSTEM SHALL devolver los contadores con la cola de
  viviendas no visitadas clasificada, en vez de dejar escapar la excepción: un barrido con
  agujeros no puede confundirse con uno verde, y un `execute` que lanza no devuelve contador
  alguno.
- IF la escritura resulta ser de otro tenant, THEN THE SYSTEM SHALL abandonar y **propagar** el
  fallo en vez de contarlo como una vivienda más: es el evento cross-tenant que la seguridad
  hace fatal, y contarlo lo enterraría en una línea de log.
- THE SYSTEM SHALL rechazar por construcción que este generador se componga bajo una unidad de
  trabajo que no pueda abandonar (`CallerOwnedUnitOfWork`, cuyo `rollback()` es vacío a
  propósito): «abandonar y seguir» se convertiría en silencio en «conservar y seguir».
- WHEN se **crea** una recomendación, THE SYSTEM SHALL emitir un `TimelineEvent`
  `PRICE_RECOMMENDATION_CREATED` en su vivienda; WHEN sólo se actualiza, THE SYSTEM SHALL no
  emitirlo. En régimen estacionario eso es **una** fila de timeline por vivienda y día —la que
  entra al final del horizonte— y no sesenta; la primera pasada sobre una vivienda emite 60,
  una vez.
- THE SYSTEM SHALL marcar el evento con actor `SCHEDULER` cuando nadie actúa y `USER` cuando
  hay persona, y THE SYSTEM SHALL construir su `metadata` clave por clave —identificadores,
  fecha y precio, y nada más— y nunca desde la entidad: `timeline_events` es append-only, así
  que volcar la entidad llevaría el texto renderizado de un sumidero de la regla 11 a un
  segundo sumidero irredactable.
- THE SYSTEM SHALL derivar qué filas son creaciones de la **sentencia** y no de la lectura
  previa: en la rama de conflicto la fila guardada conserva su propio `id`, así que un evento
  construido desde la lectura previa apuntaría a ninguna fila — y `timeline_events` es
  append-only, así que el puntero colgado sería permanente.
- THE SYSTEM SHALL devolver de la ruta `created`, `updated`, `preserved` y `skipped`, cuatro
  contadores que no se solapan y cuya suma por vivienda es el horizonte completo.
- THE SYSTEM SHALL **no** escribir `AuditLog` en la ejecución del reloj: no hay persona que
  nombrar ni petición de la que tomar una IP, y un tenant de dos viviendas escribiría ~120 filas
  anónimas al día en la tabla cuyo índice por actor existe para responder otra pregunta. El
  rastro de la pasada nocturna es el `TimelineEvent` de cada recomendación nueva y el informe
  del propio job.
- WHEN la generación la dispara una **persona** autenticada, THE SYSTEM SHALL escribir una fila
  `PRICE_RECOMMENDATIONS_GENERATED` por vivienda, sobre la vivienda y sin diff: una repetición
  sobre un horizonte completo no inserta nada, así que no dejaría fila de timeline y «quién
  movió este precio y cuándo» quedaría sin respuesta.
- IF una única sentencia de upsert llevara dos veces el mismo `(property_id, date)`, THEN THE
  SYSTEM SHALL rechazarla con `422` nombrando la clave duplicada, en vez de dejar que Postgres
  la conteste con un `IntegrityError` que nadie traduce y llegaría como `500`.

### Decisión sobre las recomendaciones

- WHEN un usuario con `READ_PRICE_RECOMMENDATIONS` emite `GET /api/v1/price-recommendations`,
  THE SYSTEM SHALL devolver únicamente las de su tenant, paginadas y filtrables por
  `property_id`, por el rango `date_from`/`date_to` y por `status`, todo combinado con AND.
- THE SYSTEM SHALL admitir **tres movimientos y ninguno más**: `RECOMMENDED → APPROVED`,
  `RECOMMENDED → REJECTED` y `APPROVED → APPLIED_EXTERNAL`.
- IF la transición pedida no es una de las tres, THEN THE SYSTEM SHALL responder `409` y dejar
  el estado intacto, validando **antes** de mutar.
- THE SYSTEM SHALL alojar la máquina de estados en la **entidad** y no en el caso de uso: los
  movimientos legales de una recomendación son una regla de negocio.
- IF el llamante manda un valor fuera del enum, THEN THE SYSTEM SHALL responder `422` — es un
  fallo de forma, distinto de un movimiento ilegal — y IF manda la cadena desnuda de un estado
  que no es decisión, THEN THE SYSTEM SHALL responder `409`.
- THE SYSTEM SHALL dejar `APPLIED_EXTERNAL` inalcanzable desde la operación de decisión: no es
  una decisión sino un hecho del mundo —alguien publicó ese precio fuera del sistema— y tiene
  operación y acción de auditoría propias.
- WHEN se decide una recomendación, THE SYSTEM SHALL registrar `PRICE_RECOMMENDATION_DECIDED`
  con el actor y el diff de `status`, que es toda su superficie auditable; WHEN se marca como
  publicada, THE SYSTEM SHALL registrar `PRICE_RECOMMENDATION_APPLIED_EXTERNAL` **y** emitir un
  `TimelineEvent` `PRICE_UPDATED_EXTERNAL` con tres identificadores y sin texto libre.
- THE SYSTEM SHALL **no invocar ninguna operación del `PMSAdapter`** en ninguna transición, ni
  en el cálculo, ni en la generación. Nada en el módulo importa, sostiene ni llama un
  `PMSAdapter`.
- THE SYSTEM SHALL dejar `current_price` en `NULL`: su fuente sería
  `PMSAdapter.get_availability`, y el Modo 1 no habla con el PMS.
- `ASSUMPTION`: `price_recommendations` tiene `created_at` y **no** `updated_at` —fidelidad a
  PRD §7.18—, así que una transición mueve `status` sin sellar nada y **el rastro temporal de
  una aprobación vive en el `AuditLog` y en el `TimelineEvent`, nunca en la fila**. Quien lea un
  estado aquí y quiera saber *cuándo* cambió tiene que ir a esos dos.

### Explicación legible y determinista

- WHEN se genera una recomendación, THE SYSTEM SHALL escribir en `explanation` el precio base,
  cada modificador aplicado en orden con su nombre y porcentaje firmado, cada guardrail que
  recortó, y el precio final — una frase por elemento. La forma es la que fija
  `tests/pricing/test_explanation.py::test_the_worked_example_of_the_design_renders_exactly`:

  ```
  Base price 100.00 EUR. Weekday (saturday) +20.00% -> 120.00. Lead time (<=3 days) -10.00%
  -> 108.00. Occupancy (>50%) +5.00% -> 113.40. Season (high_summer) +30.00% -> 147.42.
  Guardrail max_daily_change_pct (+20.00% of 110.00) -> 132.00. Guardrail max_price -> 130.00.
  Recommended 130.00 EUR.
  ```

  Los dos guardrails encadenados son el orden de arriba hecho visible: el tope diario recorta a
  132,00 y `max_price` lo baja después a 130,00.
- THE SYSTEM SHALL redactarla en **inglés**, como el resto de mensajes de sistema, desde una
  plantilla cerrada y **sin que ningún adaptador de IA participe**.
- THE SYSTEM SHALL renderizarla como una **segunda función pura sobre el rastro del
  calculador** y no como un segundo recorrido de la regla, de modo que el precio y su
  explicación no puedan separarse.
- THE SYSTEM SHALL tomar el signo del porcentaje de `is_signed()` y no de `>= 0`: un porcentaje
  negativo pequeño cuantiza a `Decimal('-0.00')`, que es `>= 0`, e imprimiría un descuento como
  `+0.00%`.
- THE SYSTEM SHALL fijar `confidence` en `1.00` en la propia entidad y no dejarlo al llamante:
  hoy el precio es función determinista de la regla, así que cualquier otro valor sería adorno.
  La columna existe para un modo futuro cuyo cálculo cargue incertidumbre real.
- THE SYSTEM SHALL tratar `explanation` como sumidero de texto libre de la regla 11: el `name`
  que la manager escribe en una temporada o un evento es la única parte que la plantilla no
  compone, y por eso ese mismo `name` no la sigue hasta `audit_logs`.
- THE SYSTEM SHALL construir el nombre de un modificador desde el umbral **parseado** y nunca
  desde el valor bruto del JSONB, para que ese sumidero no cargue lo que la columna guardase.

### Permisos y aislamiento por tenant

- THE SYSTEM SHALL proteger las siete rutas con cuatro permisos —`READ_PRICING_RULES`,
  `MANAGE_PRICING_RULES`, `READ_PRICE_RECOMMENDATIONS`, `MANAGE_PRICE_RECOMMENDATIONS`— y
  conceder los cuatro **tanto a `TENANT_OWNER` como a `PROPERTY_MANAGER`**.
- THE SYSTEM SHALL cubrir con `MANAGE_PRICE_RECOMMENDATIONS` las tres transiciones **y**
  `POST /generate`.
- THE SYSTEM SHALL resolver el tenant desde la sesión autenticada y nunca desde el cuerpo o la
  query, y THE SYSTEM SHALL comprobar en el repositorio que la entidad en mano pertenece al
  tenant que actúa.
- THE SYSTEM SHALL guardar la reescritura del upsert con un predicado de `tenant_id` en el
  `ON CONFLICT … WHERE`, porque el `UNIQUE` que decide es `(property_id, date)` y no lleva
  tenant. Es una guarda **viva**: nada ata el `tenant_id` de una recomendación al dueño de su
  vivienda. Lo que la hace inalcanzable hoy es la comprobación previa de que las viviendas
  ancla son del tenant — una guarda la fila en mano, la otra la fila ya en la tabla, y las dos
  se quedan.

## Estado y deuda conocida

- **Dos filas persistidas adyacentes pueden romper el tope diario cuando una está preservada**,
  y es un límite conocido y medido, no un descuido. El tope sólo se puede imponer hacia
  delante, y preservar una decisión humana prohíbe ajustar al vecino ya decidido, así que el
  par *(recalculada, preservada)* queda estructuralmente sin acotar. Con base 100, tope 20 % y
  los días +1/+3/+5 aprobados a 200/300/120, el horizonte emitido es
  `[200, 160, 300, 240, 120, 100]`, con saltos de +87,5 % y −50 % sin ningún clamp en juego.
  Lo que sí se garantiza es que el día **siguiente** a uno preservado se acota contra el precio
  que la manager ve. Lo fija
  `tests/pricing/test_use_cases.py::test_two_adjacent_persisted_rows_can_break_the_daily_cap_when_one_is_preserved`.
- **El primer día del horizonte se repone sin tope cada noche**, por el mismo motivo: no hay
  día anterior en el horizonte contra el que medirlo. Es el segundo borde del mismo hueco.
- **Un día que se reprecia no deja rastro de su precio anterior**, y es la consecuencia
  conjunta de tres decisiones correctas por separado: el timeline se emite sólo por
  inserciones, la pasada nocturna no escribe `AuditLog`, y `price_recommendations` no tiene
  `updated_at`. Con `{created: 0, updated: 59, preserved: 1}` —una ejecución cualquiera en
  régimen estacionario— el reloj escribe **cero** filas de auditoría y **cero** de timeline
  para 59 precios reescritos, y el precio viejo se sobrescribe en su fila. Lo único que queda de
  ellos es el informe de esa ejecución en el log del worker, así que **no se puede reconstruir
  por qué el precio de una noche pasó de 143,00 a 156,00**. Consta aquí, y en la regla 11 de
  `steering/security.md`, porque el «sumidero hecho a medida» de esa regla es más estrecho de lo
  que su nombre sugiere.
- **`failed` no está en el contrato publicado.** El caso de uso cuenta un quinto contador, pero
  `POST /generate` devuelve sólo cuatro, así que un llamante **no puede ver que una vivienda
  falló**: eso vive en el log de la aplicación, con el identificador que lo causó. Un barrido
  con agujeros se ve verde desde la API.
- **`DRAFT` no lo produce ni lo consume nadie.** Está en el enum porque PRD §7.18 lo declara,
  y ningún camino de esta capacidad lo escribe ni sale de él.
- **`current_price` queda siempre `NULL`** mientras no exista `get_availability`. La columna es
  nullable en §7.18 precisamente por esto.
- **El catálogo de festivos caduca a fin de 2027.** Es una constante de tres años escrita a
  mano; a partir de 2028 una `event_rule` con `{"holidays": "ES_NATIONAL"}` deja de casar
  ninguna fecha, en silencio y sin error. Quien lo extienda añade años y Viernes Santos a la
  misma constante.
- **No hubo migración.** Las dos tablas y el enum ya estaban en
  `96d526599bc1_domain_foundation_financial`, y esta capacidad no añade ninguna variable de
  entorno: el horizonte y la ventana de ocupación son cifras del PRD, no palancas de
  operación, así que son constantes de módulo y se revisan en un Pull Request.
- **El `422` de validación devuelve el `loc` de Pydantic sin acotar**, y con
  `extra="forbid"` ese `loc` lleva el nombre de la clave desconocida que envió el llamante. No
  es un hueco de esta capacidad —vive en el handler compartido y afecta a todo módulo con
  `extra="forbid"`— pero se midió desde aquí: entrada `validation-error-loc-redaction` del
  roadmap.
- **`audit_logs.changes` se cierra en `ChangeSet` y no en el repositorio**, así que quien
  construya un `AuditLog` a mano escribe lo que quiera. Ningún call site lo hace, así que no
  hay exposición viva; lo levantó el panel de QA de este change y pertenece a `app/audit/`:
  entrada `audit-changes-repository-guard` del roadmap.
- **Sin UI.** La página `/pricing` de PRD §24 es una entrada de frontend propia; esta capacidad
  es sólo backend.
- **Modos 2 y 3 de PRD §19** (aprobación automática, push a la OTA) y con ellos
  `PMSAdapter.update_price`, `block_dates` y `get_availability` van a un change de ARI propio,
  cuando exista quien los consuma.

## Key files

- `backend/app/pricing/domain/calculator.py` — la fórmula de PRD §7.17, los guardrails y el
  rastro (`calculate_price`, `PriceCalculation`).
- `backend/app/pricing/domain/entities.py` — `PricingRule` con todos sus validadores,
  `PriceRecommendation` y su tabla de transiciones.
- `backend/app/pricing/domain/explanation.py` — `render_explanation`, la plantilla cerrada.
- `backend/app/pricing/domain/holidays.py` — el catálogo `ES_NATIONAL` 2025-2027.
- `backend/app/pricing/domain/occupancy.py` — la ventana de 30 días sobre reservas locales.
- `backend/app/pricing/domain/rule_resolution.py` — `resolve_rule`, propia sobre la del tenant.
- `backend/app/pricing/domain/constants.py` — `HORIZON_DAYS`, `OCCUPANCY_WINDOW_DAYS`.
- `backend/app/pricing/domain/{enums,exceptions,repositories}.py` — estados, errores, puertos.
- `backend/app/pricing/application/use_cases.py` — los siete casos de uso, incluido el
  generador compartido por el job y por el endpoint.
- `backend/app/pricing/infrastructure/{models,repositories}.py` — las dos tablas y el
  `ON CONFLICT DO UPDATE` con sus dos predicados de guarda.
- `backend/app/pricing/api/{rules_router,recommendations_router,schemas,dependencies,errors}.py`
  — las siete rutas, sus esquemas y la traducción a los códigos de PRD §23.
- `backend/app/scheduler/{schedule,tasks}.py` — `DAILY_JOBS`, `generate_price_recommendations`
  y `_guarded_daily`.
- `backend/app/auth/domain/policy.py` — los cuatro permisos y sus dos roles.
- `backend/app/audit/domain/{actions,value_objects}.py` — las cinco acciones, los campos
  auditables de `PRICING_RULE` y las cinco columnas `REDACT_ONLY`.
- `backend/tests/pricing/` — 16 ficheros de test; `test_calculator.py`, `test_entities.py` y
  `test_use_cases.py` son los que fijan la fórmula, los validadores y el horizonte.
- `backend/tests/scheduler/test_generate_price_recommendations.py` — el job, su lock y su
  exención de auditoría.
