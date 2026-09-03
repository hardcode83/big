# Proposal: dashboard-occupancy-series

## Why

El dashboard rediseñado (`docs/design/2026-08-23-stitch-export/dashboard_autohostai_emerald_style/`)
añade sobre las property cards reales un gráfico «Ocupación Semanal» — siete barras `L M X J V S D`
— para el que no existe ninguna serie temporal ni tasa de ocupación en el contrato hoy:
`backend/openapi.json` tiene 76 rutas y ninguna sirve una serie (medido en
`sdd/roadmap/visual-restyle-workspace.md` D4). La decisión D4 de `visual-restyle-workspace`
(Jose, 2026-08-23) excluyó el gráfico de ese restyle por no tener backend y lo registró como
esta entrada de roadmap propia — la segunda de las tres nacidas de esa decisión, junto a
`dashboard-operational-kpis` (ya entregada) y `dashboard-activity-feed`.

A diferencia de las otras dos, esta no es una lectura directa de un dominio existente: hoy
**no hay ninguna noción de "noche ocupada"** en el sistema a nivel de portfolio. Lo más
cercano es `app/pricing/domain/occupancy.py` (`occupancy_pct_for`), que calcula un **único**
porcentaje por propiedad sobre una ventana de 30 días **hacia delante** y cuenta únicamente
reservas (`FREE_STATUSES = {CANCELLED, NO_SHOW}`). El propio texto de la entrada de roadmap
fija una definición más amplia para este gráfico — reserva confirmada, bloqueo del propietario,
fuera de servicio —, así que esta capability no reutiliza `occupancy_pct_for` tal cual: compone
una definición nueva, a nivel de tenant y por día calendario, que la sección Requirements deja
cerrada.

## What changes

Un nuevo endpoint agregado a nivel de tenant en `app/dashboard/` que devuelve, para cada uno de
los siete días de la semana calendario en curso (lunes a domingo, UTC), qué porcentaje de las
viviendas activas del tenant tuvo esa noche ocupada — entendiendo por "ocupada" cualquiera de:
una reserva que cubre esa noche y no está `CANCELLED`/`NO_SHOW`, o la vivienda en estado
`BLOCKED_BY_OWNER` u `OUT_OF_SERVICE` ese día. Sigue el mismo patrón de composición sin
`infrastructure/` propia que ya usan `GetDashboardCardsUseCase` / `GetOperationalKpisUseCase`
(decisión D1 de `dashboard-api`): lee `reservations` (ya expuesto) y añade al puerto
`PropertyStateTransitionRepository` — hoy solo `add`, `applied_clock_triggers` y
`last_for_property` — un lector que traiga el historial de transiciones de todas las viviendas
del tenant que se solapan con la semana, necesario para reconstruir en qué estado estaba cada
vivienda cada día (`properties_state_transitions` guarda `to_state` + `created_at` por
transición, no un rango de fechas).

## Requirements

### R1 — Serie semanal de ocupación por tenant

**As a** manager o propietaria autenticada, **I want** ver qué porcentaje de mi cartera estuvo
ocupada cada día de la semana en curso, **so that** entender de un vistazo la ocupación del
negocio sin recorrer cada vivienda (principio 2 de `steering/product.md`: el dashboard responde
"¿qué pasa?" en <10s).

Acceptance criteria:

1. WHEN se solicita el endpoint de serie de ocupación, THE SYSTEM SHALL devolver exactamente
   siete puntos, uno por día de la semana calendario en curso (ISO, lunes a domingo, UTC),
   ordenados de lunes a domingo.
2. THE SYSTEM SHALL incluir en cada punto la fecha ISO-8601 (`date`), el número de viviendas
   activas del tenant ocupadas ese día (`occupied_properties`) y el total de viviendas activas
   del tenant (`total_properties`).
3. THE SYSTEM SHALL derivar `occupancy_pct` de `occupied_properties / total_properties * 100`
   como valor numérico entre 0 y 100. IF `total_properties` es cero (tenant sin viviendas
   activas), THEN THE SYSTEM SHALL devolver `occupancy_pct: null` para los siete días, nunca
   una división por cero.
4. THE SYSTEM SHALL NOT calcular ningún color ni etiqueta de día de la semana: el frontend
   deriva la etiqueta (`L`, `M`, `X`…) de la fecha ISO, igual que ya hace con el color de
   `operational_state` (PRD §9.1).

`ASSUMPTION`: "semana en curso" —no una ventana de 7 días finalizando hoy, ni configurable— es
la lectura literal de la maqueta, que rotula las siete barras `L M X J V S D` de una semana
calendario. Ni el PRD ni el contrato del frontend definen la ventana.

### R2 — Definición de "noche ocupada"

**As a** operador del sistema, **I want** una definición única y determinista de noche
ocupada, **so that** el gráfico cuente lo mismo que el resto del sistema entiende por
"vivienda no disponible", en vez de inventar un segundo criterio de ocupación.

Acceptance criteria:

1. THE SYSTEM SHALL contar una vivienda como ocupada en un día calendario `D` si se cumple
   **cualquiera** de estas tres condiciones (unión, sin doble conteo):
   - tiene una `Reservation` cuyo rango `[check_in_date, check_out_date)` cubre `D` y cuyo
     `status` no está en `{CANCELLED, NO_SHOW}` — el mismo `FREE_STATUSES` que
     `app/pricing/domain/occupancy.py` ya declara para "noche ocupada" por reserva;
   - estuvo en `PropertyOperationalState.BLOCKED_BY_OWNER` en algún instante de `D`;
   - estuvo en `PropertyOperationalState.OUT_OF_SERVICE` en algún instante de `D`.
2. THE SYSTEM SHALL resolver el estado de una vivienda en un día pasado o en curso
   reconstruyéndolo desde su historial de `PropertyStateTransitionModel` (el `to_state` de la
   transición vigente al final de ese día), nunca desde el `operational_state` actual de la
   fila `properties` — que solo describe el instante presente y daría el mismo estado a los
   siete días de una semana que tuvo dos transiciones.
3. WHERE una vivienda no tiene ninguna transición registrada antes de o durante `D`, THE
   SYSTEM SHALL tratarla como no bloqueada ni fuera de servicio ese día (el alta no es una
   transición, mismo criterio que `GET /properties/{id}/state`).
4. THE SYSTEM SHALL contar los tres orígenes sobre el **mismo día calendario UTC** con el que
   R1 agrega la serie, sin mezclar husos horarios entre el criterio de reservas (por fecha) y
   el de transiciones (por instante).

### R3 — Historial de transiciones de estado, lector nuevo

**As a** desarrollador de esta capability, **I want** un lector que traiga el historial de
transiciones de todas las viviendas de un tenant que se solapan con un rango de fechas,
**so that** R2.2 pueda reconstruir el estado de cada vivienda cada día sin una consulta por
vivienda y por día.

Acceptance criteria:

1. THE SYSTEM SHALL añadir a `PropertyStateTransitionRepository` un método de lectura que
   devuelva, para un `tenant_id` y una ventana `[start, end]`, todas las transiciones
   necesarias para conocer el estado de cada vivienda al principio y a lo largo de esa
   ventana — incluida, si existe, la última transición anterior a `start` (el estado con el
   que la vivienda "entra" a la semana).
2. THE SYSTEM SHALL resolver la serie completa con un **número fijo de consultas**,
   independiente del número de viviendas del tenant, siguiendo la misma regla que
   `sdd/specs/dashboard-api.md` ya impone a la colección de cards («Composición por lotes, sin
   N+1»), y un test SHALL demostrarlo contando las sentencias emitidas.
3. THE SYSTEM SHALL NOT modificar `PropertyStateTransitionRepository.add`, y SHALL mantener el
   nuevo método como puramente de lectura, coherente con que la tabla es un registro de
   auditoría (regla 9 de `steering/security.md`) que ningún lector reescribe.

### R4 — Tenant scoping y redacción por permiso de origen

**As a** operador del sistema, **I want** que el endpoint de serie de ocupación respete el
aislamiento de tenant y el permiso que protege el origen de los datos que agrega, **so that**
ningún rol vea una serie compuesta de dominios que no puede leer y ningún tenant vea la
ocupación de otro.

Acceptance criteria:

1. THE SYSTEM SHALL derivar el `tenant_id` del `RequestContext` autenticado (regla 1 de
   `steering/security.md`), nunca de un parámetro de la petición, y SHALL incluirlo en toda
   query contra `reservations`, `properties` y `property_state_transitions`.
2. THE SYSTEM SHALL declarar `require(Permission.READ_PROPERTIES)` en la ruta, siguiendo el
   patrón ya establecido en `sdd/specs/dashboard-api.md` para las otras rutas de
   `app/dashboard/`.
3. WHERE el rol que llama carece de `Permission.READ_RESERVATIONS`, THE SYSTEM SHALL devolver
   la serie completa como `null` en vez de una serie que solo cuenta bloqueos y fuera de
   servicio: el componente de reservas es el origen mayoritario de "noche ocupada" y una serie
   parcial sin él no es una lectura estrecha de lo mismo, es un número distinto con la misma
   forma — la regla «una proyección puede estrechar, nunca unir» de `dashboard-api.md`.
4. THE SYSTEM SHALL tener un test de aislamiento de tenant que demuestre, sembrando reservas y
   transiciones de un tenant vecino, que la serie de un tenant no cuenta viviendas ni noches
   del otro.

## Out of scope

- El feed de actividad cross-propiedad (`dashboard-activity-feed`) y las tres tarjetas de KPI
  operacionales (`dashboard-operational-kpis`, ya entregada) — son las otras dos entradas
  nacidas de la misma decisión D4, con su propio endpoint y su propio proposal.
- La mitad `[FE]` que consume y pinta el gráfico — queda para cuando la composición visual
  pueda verse contra datos reales (D4 de `visual-restyle-workspace`), igual que se dejó fuera
  en `dashboard-operational-kpis`.
- Series de ocupación por vivienda individual o con ventana configurable (mensual, por rango
  arbitrario) — el alcance es la semana en curso a nivel de tenant, que es lo único que la
  maqueta pide.
- Reutilizar o modificar `occupancy_pct_for` de `app/pricing/domain/occupancy.py` — sirve una
  pregunta distinta (ventana de 30 días hacia delante, por propiedad, solo reservas) y esta
  entrada no lo toca.
- Cambiar `PropertyStateMachine`, sus disparadores o el comportamiento de
  `ReservationStatus` — este change solo lee esas tablas.
- Cachear o materializar la serie — se calcula en cada petición, como el resto de
  `app/dashboard/`.

## Affected specs

- `sdd/specs/dashboard-api.md` — se amplía con el nuevo endpoint de serie de ocupación, su
  contrato, la definición de "noche ocupada" y sus tests de aislamiento, siguiendo la
  estructura ya usada para `/dashboard/properties` y `/dashboard/operational-kpis`.
