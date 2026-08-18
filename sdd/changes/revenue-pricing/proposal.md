# Proposal: revenue-pricing

## Why

`pricing_rules` y `price_recommendations` existen como tablas desde
`domain-foundation-financial` (2026-07-31) y **nadie escribe en ellas**: el módulo
`backend/app/pricing/` tiene solo `domain/entities.py`, `domain/enums.py` e
`infrastructure/models.py`. No hay caso de uso, ni repositorio, ni router. Lo mismo pasa
con los dos tipos de `TimelineEvent` que ya están declarados y renderizados
(`PRICE_RECOMMENDATION_CREATED`, `PRICE_UPDATED_EXTERNAL`): nadie los emite.

Es el paso 7 de la prioridad de entrega de `steering/product.md` y el punto §26.22 del PRD,
y el `beat` lo tiene reservado por nombre: `backend/app/scheduler/schedule.py:17` declara
que `generate_price_recommendations` está deliberadamente ausente de `CADENCES` porque
«pertenece a `revenue`». Este change es quien lo trae.

Fuentes: PRD §19 (modos y guardrails), §7.17-7.18 (entidades y fórmula), §8.3 (job diario),
§22 (AuditLog), §23 (las siete rutas), §26.22. Principio 5 de `steering/product.md`:
*pricing determinista por reglas; la IA explica, nunca calcula precios*.

**Procedencia**: la entrada de roadmap `revenue` se partió en tres el 2026-08-16
(`revenue-pricing`, `revenue-statements`, `revenue-reviews`) porque agrupaba PRD §18, §19 y
§20 — tres dominios con módulos, entidades y APIs distintos — y no cabía en un solo change.

## What changes

Después de este change el tenant puede definir reglas de precio por propiedad (o para todo
el tenant), y el sistema genera cada madrugada una recomendación de precio por propiedad y
día para los próximos 60 días, calculada con la fórmula determinista de PRD §7.17, acotada
por sus guardrails, explicada en texto legible y auditada en `TimelineEvent` y `AuditLog`.
El manager consulta esas recomendaciones y las aprueba o rechaza por API; cuando las publica
a mano en la OTA, lo registra. **Modo 1 del PRD §19: el sistema recomienda, nunca publica** —
no se llama al PMS en ningún punto de este flujo.

Dos decisiones tomadas antes de escribir esto, ambas cerrando huecos del PRD:

1. **`max_daily_change_pct` se mide contra el día anterior del mismo horizonte.** PRD §19 lo
   declara guardrail obligatorio, pero la fórmula de §7.17 solo aplica `min_price`/`max_price`
   y nunca lo usa: la contradicción es del PRD, no una omisión de lectura. Acotar contra el
   día anterior es determinista y no necesita conocer el precio publicado en la OTA.
   **Lo que no hace es la curva continua sin excepciones**, y esta frase decía que sí: la
   referencia es el precio **persistido** del día anterior, así que una fila preservada por R4.3
   —y el primer día de cada horizonte— quedan sin acotar contra su vecino. Los dos bordes, con
   sus cifras, en R3.2 y en **D4** de `design.md`.
2. **Las tres operaciones ARI del `PMSAdapter` no entran.**
   `backend/app/integrations/domain/ports.py:93` las reserva («`update_price`, `block_dates` y
   `get_availability`, ARI, arriving with `revenue`»), pero Modo 1 no publica precios, así que
   `update_price` no tendría consumidor, y la ocupación se calcula sobre las reservas locales,
   que ya son la proyección del calendario del PMS. Esa nota queda corregida en este change
   para que no siga prometiendo algo que el MVP no hace (R4.7).

No hace falta migración: las dos tablas y el enum `price_recommendation_status` ya están en
`96d526599bc1_domain_foundation_financial`.

## Requirements

### R1 — Reglas de pricing administrables

**As a** manager, **I want** crear y ajustar reglas de precio por propiedad o para todo el
tenant, **so that** el cálculo de recomendaciones tenga una fuente explícita y revisable.

Acceptance criteria:

1. WHEN un usuario autorizado emite `POST /api/v1/pricing-rules` con una regla válida, THE
   SYSTEM SHALL persistirla en el tenant de la sesión y devolver `201` con su identificador.
2. WHEN emite `GET /api/v1/pricing-rules`, `GET /api/v1/pricing-rules/{id}` o
   `PATCH /api/v1/pricing-rules/{id}`, THE SYSTEM SHALL operar únicamente sobre reglas del
   tenant de la sesión (PRD §23).
3. IF `min_price > max_price`, o `base_price` cae fuera de `[min_price, max_price]`, o
   `max_daily_change_pct` cae fuera de `[0, 100]`, THEN THE SYSTEM SHALL rechazar con `422`
   sin persistir nada.
4. IF `weekday_modifiers` o cualquiera de los cuatro arrays (`lead_time_rules`,
   `occupancy_rules`, `seasonality_rules`, `event_rules`) no respeta el esquema de PRD §7.17,
   THEN THE SYSTEM SHALL rechazar con `422` nombrando el campo que falla.
5. WHERE `property_id` es `NULL`, THE SYSTEM SHALL aplicar la regla a toda propiedad del
   tenant que no tenga una regla propia activa; WHERE una propiedad tiene regla propia activa,
   THE SYSTEM SHALL usar esa y no la del tenant.
6. WHEN se crea o modifica una `PricingRule`, THE SYSTEM SHALL registrar un `AuditLog` con
   actor, entidad y cambio (PRD §22, «cambios en PricingRule y PriceRecommendation»).
7. IF el identificador pedido pertenece a otro tenant, THEN THE SYSTEM SHALL responder `404`
   y no `403`, sin revelar su existencia.

### R2 — Precio recomendado determinista

**As a** propietaria, **I want** que el precio recomendado salga de una fórmula reproducible,
**so that** pueda entenderlo y discutirlo sin depender de una caja negra.

Acceptance criteria:

1. WHEN se calcula el precio de una fecha, THE SYSTEM SHALL aplicar los modificadores en el
   orden de PRD §7.17: día de la semana → anticipación → ocupación → temporada y eventos,
   cada uno multiplicativo sobre el resultado del anterior.
2. WHERE varias `lead_time_rules` aplican, THE SYSTEM SHALL usar la de menor `days_before`;
   WHERE varias `occupancy_rules` aplican, THE SYSTEM SHALL usar la de mayor
   `occupancy_pct_above`; WHERE varias reglas de temporada o evento casan con la fecha, THE
   SYSTEM SHALL aplicarlas todas.
3. THE SYSTEM SHALL calcular la ocupación como el porcentaje de noches ocupadas en los 30 días
   naturales siguientes a la fecha de ejecución, derivado de las `reservations` locales, **sin
   llamar al PMS**.
4. THE SYSTEM SHALL operar en `Decimal` de extremo a extremo y redondear a dos decimales solo
   al final; el uso de `float` en la cadena de cálculo SHALL considerarse un defecto.
5. THE SYSTEM SHALL implementar el cálculo como función pura — sin reloj, sin base de datos,
   sin red — de modo que los mismos argumentos den siempre el mismo resultado.
6. THE SYSTEM SHALL incluir un catálogo embebido de festivos nacionales de España 2025-2027
   (PRD §19) que una regla pueda referenciar aportando su propio `modifier_pct`.
   `ASSUMPTION`: el PRD fija la lista pero no qué modificador le corresponde, así que el
   porcentaje lo pone la regla; los festivos locales de municipio siguen siendo `event_rules`
   manuales, como el propio PRD declara.

### R3 — Guardrails obligatorios

**As a** propietaria, **I want** que ninguna recomendación se salga de mis límites ni dé
saltos bruscos entre días, **so that** pueda dejar el sistema generando sin vigilarlo.

Acceptance criteria:

1. WHEN el precio calculado cae fuera de `[min_price, max_price]`, THE SYSTEM SHALL acotarlo
   al límite correspondiente (PRD §7.17 paso 5, §19).
2. WHEN se genera el horizonte, THE SYSTEM SHALL recorrerlo en orden ascendente de fecha y
   acotar cada precio a ±`max_daily_change_pct` % respecto del **precio persistido para el día
   inmediatamente anterior del mismo horizonte** — el que queda en su fila, que es el que la
   manager ve, y no el que el recálculo «habría» dado para ese día.
   Una redacción anterior decía «el precio **recomendado** del día anterior», y describía una
   garantía más ancha de la que el sistema da: **R4.3 gana a R3.2 en el borde de una fila
   preservada**, a propósito, porque el tope sólo se puede imponer hacia delante y R4.3 prohíbe
   ajustar al vecino ya decidido por una persona. El par *(recalculado, preservado)* queda por
   tanto estructuralmente sin acotar — con base 100, tope 20% y los días +1/+3/+5 aprobados a
   200/300/120, el horizonte emitido es `[200, 160, 300, 240, 120, 100]`, con saltos de +87,5% y
   −50% sin ningún clamp en juego. Es un límite conocido y medido, no un descuido: el porqué, las
   alternativas rechazadas y el segundo borde (el primer día del horizonte se repone sin tope cada
   noche) están en **D4** de `design.md`, y lo fija
   `backend/tests/pricing/test_use_cases.py::test_two_adjacent_persisted_rows_can_break_the_daily_cap_when_one_is_preserved`.
   Lo que sí se promete, y es lo que R3.2 exige: el día **siguiente** a uno preservado se acota
   contra el precio que la manager ve, no contra uno inventado.
3. WHERE la fecha es el primer día del horizonte, THE SYSTEM SHALL no aplicar el tope diario,
   porque no hay base contra la que medirlo.
4. WHEN el tope diario y los límites `min_price`/`max_price` compiten, THE SYSTEM SHALL aplicar
   los límites en último lugar, de modo que ningún precio emitido quede jamás fuera del rango
   aunque el tope diario lo permitiera.
5. WHEN un guardrail recorta el precio, THE SYSTEM SHALL dejar constancia de cuál actuó en la
   `explanation` de esa recomendación (R6).

### R4 — Generación diaria y bajo demanda

**As a** manager, **I want** que las recomendaciones aparezcan solas cada día y poder forzarlas
cuando cambio una regla, **so that** el precio propuesto no dependa de que alguien se acuerde.

Acceptance criteria:

1. WHEN el reloj alcanza las 06:00, THE SYSTEM SHALL generar recomendaciones para los próximos
   60 días de cada propiedad activa con regla aplicable (PRD §8.3).
2. WHEN ya existe una recomendación para `(property_id, date)`, THE SYSTEM SHALL actualizarla
   en lugar de fallar contra el `UNIQUE`, de modo que el job sea idempotente.
3. IF la recomendación existente está en `APPROVED` o `APPLIED_EXTERNAL`, THEN THE SYSTEM SHALL
   preservarla intacta: una decisión humana no se sobrescribe por una regeneración.
4. WHEN se crea una recomendación nueva, THE SYSTEM SHALL emitir un `TimelineEvent` de tipo
   `PRICE_RECOMMENDATION_CREATED` para su propiedad.
5. WHEN un usuario autorizado emite `POST /api/v1/price-recommendations/generate`, THE SYSTEM
   SHALL ejecutar la misma generación sobre el ámbito indicado y devolver cuántas
   recomendaciones creó y cuántas actualizó.
6. WHERE una propiedad no tiene ninguna regla activa aplicable, THE SYSTEM SHALL omitirla sin
   error y sin dejar el job en fallo.
7. THE SYSTEM SHALL registrar el job en `CADENCES` de `backend/app/scheduler/schedule.py` con
   el mismo mecanismo de lock que el resto (`specs/celery-jobs.md` R1), y las dos notas que hoy
   atribuyen este job y las operaciones ARI a `revenue` — `schedule.py:17` y
   `integrations/domain/ports.py:93` — SHALL quedar corregidas en este mismo change.

### R5 — Decisión sobre las recomendaciones

**As a** propietaria, **I want** aprobar o rechazar cada recomendación y anotar cuándo la he
publicado a mano, **so that** el sistema refleje lo que realmente está pasando en la OTA.

Acceptance criteria:

1. WHEN un usuario autorizado emite `GET /api/v1/price-recommendations` filtrando por
   propiedad y rango de fechas, THE SYSTEM SHALL devolver únicamente las de su tenant.
2. WHEN emite `PATCH /api/v1/price-recommendations/{id}` a `APPROVED` o `REJECTED` sobre una
   recomendación en `RECOMMENDED`, THE SYSTEM SHALL aplicar la transición y registrar un
   `AuditLog` con el actor.
3. WHEN emite `PATCH` a `APPLIED_EXTERNAL` sobre una recomendación en `APPROVED`, THE SYSTEM
   SHALL aceptarla y emitir un `TimelineEvent` de tipo `PRICE_UPDATED_EXTERNAL`, que es el
   registro de que un humano publicó ese precio fuera del sistema.
4. IF la transición pedida no es una de las tres anteriores, THEN THE SYSTEM SHALL responder
   `409` y dejar el estado intacto.
5. THE SYSTEM SHALL no invocar ninguna operación del `PMSAdapter` en ninguna de estas
   transiciones (Modo 1 del PRD §19).
   `ASSUMPTION`: `price_recommendations` no tiene `updated_at` — `specs/domain-foundation-financial.md`
   lo declara «solo timestamp de creación», por fidelidad a §7.18 — así que el rastro temporal
   de una aprobación vive en el `AuditLog` y en el `TimelineEvent`, no en la fila.

### R6 — Explicación legible y determinista

**As a** propietaria, **I want** leer por qué se me propone ese precio, **so that** pueda
aprobarlo con criterio en lugar de a ciegas.

Acceptance criteria:

1. WHEN se genera una recomendación, THE SYSTEM SHALL escribir en `explanation` el precio base,
   la lista ordenada de modificadores aplicados con su nombre y porcentaje, y los guardrails que
   hayan actuado.
2. THE SYSTEM SHALL generar `explanation` sin intervención de ningún adaptador de IA
   (`steering/product.md` principio 5; PRD §19: «la IA puede explicar recomendaciones pero NO es
   la fuente de cálculo»).
3. THE SYSTEM SHALL fijar `confidence` en `1.00` mientras el cálculo sea determinista, y
   documentar en el código que el campo existe para un modo futuro con incertidumbre real.
4. THE SYSTEM SHALL redactar `explanation` en inglés, como el resto de mensajes de sistema
   (`sdd/project.md`, Conventions).

## Out of scope

- **Modos 2 y 3 del PRD §19** (aprobación automática, push a la OTA) y con ellos
  `PMSAdapter.update_price`, `block_dates` y `get_availability`: sin consumidor en Modo 1. Van a
  un change de ARI propio, cuando exista quien los use.
- **`current_price` poblado desde el PMS**: queda `NULL` mientras no haya `get_availability`. El
  campo es nullable en §7.18 precisamente por esto.
- **`OwnerApproval`**: su `related_type` es `ENUM('INCIDENT','MAINTENANCE_COST','OTHER')` (§7.19)
  y no admite pricing; la aprobación de un precio viaja por `PriceRecommendation.status`. La
  entidad pertenece a `maintenance`, que ya la usa.
- **Statements, expenses y exports** → `revenue-statements`.
- **Reviews, sentimiento y borradores de respuesta** → `revenue-reviews`.
- **La página `/pricing` de PRD §24** y cualquier UI: este change es backend. La pantalla es una
  entrada de frontend propia.
- **Festivos locales de municipio**: `event_rules` manuales, como declara PRD §19.
- **Pricing por ML o por IA**: non-goal explícito del MVP (PRD §29).

## Affected specs

- `sdd/specs/revenue-pricing.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/celery-jobs.md` — entra el séptimo job programado y cambia la nota que lo
  atribuía a `revenue`.
- `sdd/specs/api-contract.md` — las siete rutas nuevas registran sus códigos de error en el
  registro único.
- `sdd/specs/domain-foundation-financial.md` — `pricing_rules` y `price_recommendations` dejan
  de ser tablas sin escritor.
- `sdd/specs/timeline-state-machine.md` — `PRICE_RECOMMENDATION_CREATED` y
  `PRICE_UPDATED_EXTERNAL` pasan a tener emisor.
