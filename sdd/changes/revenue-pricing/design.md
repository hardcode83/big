# Design: revenue-pricing

## Context

`backend/app/pricing/` es hoy uno de los «dominios que todavía son solo estructura de datos»
de `steering/backend-architecture.md`: tiene `domain/entities.py` (dos `dataclass` planos),
`domain/enums.py` (`PriceRecommendationStatus`, cinco valores) e `infrastructure/models.py`
(las dos tablas, con `UNIQUE(property_id, date)` y sin `updated_at` en `price_recommendations`).
No hay `application/`, ni `api/`, ni puertos, ni un solo escritor. Este change le añade las
cuatro capas por primera vez.

Los colaboradores ya existen y son los mismos que usa `maintenance`, el módulo más reciente y
la referencia de forma: `AuditLogFactory`/`ChangeSet` (`app/audit/domain/`),
`TimelineEventFactory` (`app/timeline/domain/services.py`), `SqlAlchemyUnitOfWork`,
`require(Permission.…)` de `app/auth/api/dependencies.py`, y el bucle por tenant de
`app/scheduler/runner.py`. Las dos piezas que hay que **extender** —no solo consumir— son
`app/scheduler/schedule.py`, cuyo `CADENCES` solo sabe expresar intervalos (`timedelta`) y este
job es un `crontab` diario, y `PropertyRepository`, que no tiene un lector por `status`.

Las dos notas que el proposal manda corregir están en `app/scheduler/schedule.py:17-19`
(«`generate_price_recommendations` pertenece a `revenue`») y en
`app/integrations/domain/ports.py:93-94` («`update_price`, `block_dates` y `get_availability`
(ARI, arriving with `revenue`)»).

## Decisions

### D1 — Módulo `pricing` completo, dos agregados, dos routers

**Chosen:** `backend/app/pricing/` gana `domain/` (puertos, excepciones, servicios puros),
`application/use_cases.py`, `infrastructure/repositories.py` y `api/` con **dos routers** —
`rules_router.py` (`/api/v1/pricing-rules`) y `recommendations_router.py`
(`/api/v1/price-recommendations`)—, más `api/dependencies.py`, `api/schemas.py` y
`api/errors.py`. Dos routers y no uno porque son dos agregados con identidad propia,
ciclo de vida distinto y permisos distintos; es exactamente el criterio con que `maintenance`
separó `incidents_router.py` de `approvals_router.py`.

Rejected: un router único `/pricing` — mezcla dos agregados bajo un prefijo que PRD §23 no
declara, y obliga a un solo par de permisos para dos capacidades distintas.

### D2 — El cálculo es una función pura que devuelve un **resultado estructurado**, no un `Decimal`

**Chosen:** `app/pricing/domain/calculator.py` expone

```python
def calculate_price(rule: PricingRule, *, target_date: date, days_before: int,
                    occupancy_pct: Decimal, previous_price: Decimal | None) -> PriceCalculation
```

donde `PriceCalculation` es un value object congelado con `base_price`, la tupla ordenada de
`AppliedModifier(kind, name, modifier_pct, price_after)`, la tupla de `AppliedGuardrail(kind,
price_before, price_after, reference, limit_pct)` y el `recommended_price` final. Sin reloj, sin
base de datos, sin red: satisface R2.5 por firma, no por disciplina.

`reference` y `limit_pct` solo se rellenan para `max_daily_change_pct` —son el precio del día
anterior y el tope porcentual— y quedan a `None` en `min_price`/`max_price`, cuyo límite es el
propio `price_after`. **Se añadieron al implementar la sección 1**: la plantilla de D13 renderiza
literalmente `Guardrail max_daily_change_pct (+20.00% of 110.00) -> 132.00`, y esos dos números no
se pueden recuperar de `price_before`/`price_after`. La alternativa era que el render recompusiera
la división, que es exactamente la segunda copia de la cadena que este mismo D2 existe para
evitar.

El motivo de devolver la traza y no el número: R6.1 exige que la `explanation` liste los
modificadores aplicados **con su nombre y porcentaje** y los guardrails que actuaron. Si la
función devolviera solo el precio, la explicación tendría que recalcular la misma cadena en un
segundo sitio, y las dos podrían divergir sin que ningún test lo notara. El render de la
`explanation` (D13) es una segunda función pura que consume este objeto.

Rejected: devolver `Decimal` y componer la explicación aparte — dos copias de la misma cadena.
Rejected: que la entidad `PriceRecommendation` calcule su propio precio — necesitaría la regla,
la ocupación y el día anterior, que son contexto de la ejecución y no estado del agregado.

### D3 — Semántica exacta de los modificadores, y los tres huecos que el PRD deja

**Chosen:** el orden es literalmente el de PRD §7.17 (R2.1): día de la semana → anticipación →
ocupación → temporada y eventos, cada uno multiplicativo sobre el resultado anterior. Selección
según R2.2: `lead_time_rules` aplicables son las de `days_before <= r["days_before"]` y gana la
de **menor** `days_before`; `occupancy_rules` aplicables son las de `occupancy_pct >=
r["occupancy_pct_above"]` y gana la de **mayor** `occupancy_pct_above`; temporadas y eventos se
aplican **todos** los que casen, en el orden `seasonality_rules` y luego `event_rules`, y dentro
de cada lista en el orden declarado por el tenant — un producto de factores es conmutativo, pero
la `explanation` no lo es, y un orden fijo es lo que la hace reproducible.

Los tres huecos que el PRD no cierra y que este design cierra:

1. **`date_in_range` no está definido en el PRD.** Una `seasonality_rule` es `(start_month,
   start_day, end_month, end_day)` sin año, así que se evalúa como un rango **anual y
   recurrente**, y **cuando `(end_month, end_day) < (start_month, start_day)` el rango cruza el
   fin de año** (p. ej. 20-dic → 6-ene) y casa con las dos mitades. La alternativa —tratarlo
   como rango vacío— haría que la temporada más obvia de todas fuera indeclarable.
2. **Un `event_rule` es una fecha exacta** (`{"date": "2026-08-15"}`), con año, y casa por
   igualdad. Es lo que el ejemplo del PRD muestra y es lo que lo distingue de una temporada.
3. **`weekday_modifiers` se indexa por el nombre en minúsculas del día en inglés**
   (`monday`…`sunday`), como el `date.strftime('%A').lower()` del PRD, pero calculado con
   `calendar.day_name`-equivalente propio y **no** con `strftime`, que depende del locale del
   proceso. Una clave ausente vale 0.

Todo el cálculo opera en `Decimal` y los `modifier_pct` de los JSONB se convierten con
`Decimal(str(value))` en el borde, nunca con `Decimal(float)` (R2.4). El redondeo a dos
decimales (`ROUND_HALF_UP`) ocurre **una sola vez**, al final de `calculate_price`, después de
los guardrails.

Rejected: aplicar todos los `lead_time_rules` que casen — el PRD escoge uno y `min`/`max` son su
criterio explícito.

### D4 — Guardrails: el tope diario mide contra el precio **persistido** del día anterior

**Chosen:** el horizonte se recorre en orden ascendente de fecha (R3.2). Para cada día:
`calculate_price` aplica primero la cadena de modificadores, después el tope diario
`±max_daily_change_pct %` sobre `previous_price`, y **al final** el clamp a
`[min_price, max_price]` (R3.4) — de modo que ningún precio emitido queda nunca fuera del rango
aunque el tope diario lo permitiera. `previous_price=None` el primer día del horizonte (R3.3).

La decisión que el proposal no anticipaba: **`previous_price` es el precio que queda persistido
para el día anterior, no el que se acaba de calcular para él.** Importa porque R4.3 preserva
intactas las recomendaciones en `APPROVED`/`APPLIED_EXTERNAL`: si el día N-1 está aprobado a 120
y el recálculo «habría» dado 90, la curva que ve la manager parte de 120. Encadenar contra un
valor que no está en ninguna fila haría que la propia recomendación emitida violara su tope
diario respecto de la de al lado, que es justo lo que R3.2 existe para evitar.

**Dónde acaba esa garantía, dicho aquí porque el código y la tarea 5.5 la declararon más ancha
de lo que es.** El tope solo se puede imponer **hacia delante**, y R4.3 prohíbe ajustar al
vecino preservado, así que el par *(recalculado, preservado)* queda estructuralmente sin acotar:
**R4.3 gana a R3.2 en ese borde**, a propósito. El panel de QA de `/sdd:review` lo midió — con
base 100, tope 20% y los días +1/+3/+5 aprobados a 200/300/120, los pares persistidos contiguos
salen `160.00 → 300.00` (+87,5%) y `240.00 → 120.00` (−50%), sin ningún clamp en juego. Lo que sí
vale, y es lo que se promete: el día **siguiente** a uno preservado se acota contra el precio que
la manager ve, no contra uno inventado. Una redacción anterior decía «dos filas contiguas nunca
violan el tope diario entre sí», que es falso y era la única afirmación del change que ningún
test cubría en la dirección que falla.

**Y el borde izquierdo del horizonte se repone sin tope cada noche, también a propósito.** Cada
ejecución arranca con `previous_price=None`, así que la fila del día *anterior* al horizonte
—escrita por la ejecución de ayer, y posiblemente `APPROVED`— nunca es referencia. R3.3 lo
sanciona literalmente («primer día del horizonte → no aplicar el tope diario»), y **se lee «no
existe base en este horizonte», no «no existe base»**: la alternativa —encadenar contra la fila
almacenada del día anterior cuando la haya— acopla cada ejecución al resultado de la anterior y
convierte una corrección de regla en un arrastre de sesenta días. El coste, medido por el mismo
panel de QA de `/sdd:review`: un `800.00` aprobado en el día +1 puede quedar junto a un `100.00` recién
escrito en el día +2, un escalón del −87,5% recurrente en la cabecera del calendario. Se declara
como límite conocido y visible, no como descuido.

Rejected: encadenar el primer día contra la fila persistida del día anterior — cierra la
discontinuidad, pero hace que el precio de hoy dependa del de ayer indefinidamente y que un
cambio de regla tarde el horizonte entero en surtir efecto.

Rejected: medir contra el precio publicado en la OTA — no lo conocemos (Modo 1 no llama al PMS,
y `current_price` queda `NULL`).
Rejected: aplicar el clamp antes del tope diario — dejaría emitir precios fuera de
`[min_price, max_price]`, que es el guardrail que PRD §19 declara absoluto.

### D5 — Ocupación: un escalar por propiedad y ejecución, desde `reservations` locales

**Chosen:** `occupancy_pct` se calcula **una vez por propiedad y ejecución** (no por día del
horizonte) como el porcentaje de noches ocupadas en los **30 días naturales siguientes a la
fecha de ejecución**, sobre las reservas locales (R2.3). Es lo que dice PRD §7.17
(«los próximos 30 días» respecto de hoy, no respecto de la fecha valorada) y además hace la
generación de 60 días una sola consulta por propiedad en vez de 60.

Fuente: `ReservationRepository.list_for_properties(tenant_id, property_ids, date_from, date_to)`,
que ya existe desde `celery-jobs` y no lleva filtro de estado por diseño. El cómputo vive en
`domain/occupancy.py` como función pura sobre las entidades: cuenta noches distintas
`[check_in_date, check_out_date)` intersectadas con la ventana, y divide entre 30.

**Qué estado cuenta como ocupado:** todo menos `CANCELLED` y `NO_SHOW`. Incluye `PENDING`, que
es la reserva que el calendario del PMS ya bloquea aunque nadie la haya confirmado; excluir la
cancelada y el no-show es lo único que describe una noche que quedó libre. Se declara aquí
porque el PRD dice «ocupación» sin definirla.

Rejected: `PMSAdapter.get_availability` — fuera de alcance (Modo 1), y las `reservations`
locales ya son la proyección del calendario del PMS.
Rejected: ocupación por fecha valorada — sesenta consultas por propiedad para una señal que el
PRD define respecto de hoy.

### D6 — Resolución de la regla aplicable: propiedad gana al tenant, con desempate determinista

**Chosen:** el repositorio devuelve `list_active(tenant_id)` (todas las reglas con
`active = TRUE`, que en una cartera real son unidades) y la resolución vive en
`domain/rule_resolution.py` como función pura:

```python
def resolve_rule(rules: Sequence[PricingRule], property_id: uuid.UUID) -> PricingRule | None
```

Primero busca reglas activas con `property_id` igual; si no hay ninguna, las de
`property_id is NULL` (R1.5). Dentro de cada grupo, si hay más de una candidata gana la de
`updated_at` más reciente, con `id` como desempate final para que el resultado nunca dependa del
orden de la consulta.

Una función pura y no una consulta SQL porque es una regla de negocio (`steering/backend.md`:
«la lógica nunca vive en el router», y `backend-architecture.md`: «si hay una regla, pertenece a
`domain/`»), y porque el job la aplica N veces sobre la misma lista.

El esquema **no impide** dos reglas activas para la misma propiedad y este change no añade
migración, así que el desempate es real y no teórico. Ver **OQ3**.

Rejected: `resolve_for_property()` en el repositorio con `ORDER BY … LIMIT 1` — pone la regla en
SQL, donde no se puede testear como función pura y donde el job la ejecutaría por propiedad.

### D7 — Festivos nacionales: un catálogo embebido que una `event_rule` referencia por nombre

**Chosen:** `app/pricing/domain/holidays.py` declara `SPAIN_NATIONAL_HOLIDAYS: frozenset[date]`
con los festivos nacionales de España 2025-2027 (PRD §19), como constante y sin dependencia
externa. Una regla lo usa con una **forma nueva y declarada** de `event_rules`:

```json
{"holidays": "ES_NATIONAL", "modifier_pct": 15}
```

Es decir: `event_rules` admite **dos formas**, la del PRD (`{"name", "date", "modifier_pct"}`) y
esta, y una entrada con ambas o con ninguna es `422` (R1.4). El catálogo aporta las fechas, la
regla aporta el `modifier_pct` (R2.6, y el `ASSUMPTION` que el propio proposal declara: el PRD
fija la lista y no el porcentaje). Cuando casa, se aplica una sola vez con el nombre del festivo
como `name` del modificador aplicado.

`"ES_NATIONAL"` es hoy el único identificador admitido y el validador rechaza cualquier otro:
un catálogo abierto invitaría a inventar claves que nadie resuelve.

Rejected: expandir el catálogo a `event_rules` literales al crear la regla — congelaría los
festivos en la fila y una corrección del catálogo no alcanzaría a las reglas ya escritas.
Rejected: una columna nueva en `pricing_rules` — exigiría migración, que el proposal descarta, y
es semánticamente un `event_rule`.

### D8 — El job diario entra como `crontab`, con su propio TTL de lock

**Chosen:** `app/scheduler/schedule.py` gana una segunda tabla junto a `CADENCES`:

```python
@dataclass(frozen=True)
class DailySchedule:
    hour: int
    lock_ttl: timedelta

DAILY_JOBS: dict[str, DailySchedule] = {
    "generate_price_recommendations": DailySchedule(hour=6, lock_ttl=timedelta(hours=3)),
}
```

`beat_schedule()` deriva de **las dos** y sigue siendo la única fuente; un test comprueba que las
claves son disjuntas y que toda tarea registrada en Celery aparece en exactamente una.

Dos cosas que no son cosméticas:

- **El TTL no puede salir de `lock_ttl_for`.** Esa función devuelve `cadencia × 3`, que para un
  job diario son **tres días**: un worker muerto a mitad de ejecución dejaría el job bloqueado
  tres días. Por eso `DailySchedule` lleva su TTL explícito, holgado frente a lo que tarda una
  generación (minutos) y muy por debajo de la siguiente ventana.
- **06:00 es UTC**, porque `app/worker.py` fija `celery_app.conf.timezone = "UTC"` a propósito
  (`celery-jobs` R3.7: el proceso nunca interpreta zonas; las horas locales se derivan de la zona
  de cada propiedad). Para un tenant en Europe/Madrid eso son las 07:00-08:00 locales, y es
  irrelevante para un horizonte de 60 días. Un beat por zona de tenant sería N entradas de
  calendario para no ganar nada.

La nota de `schedule.py:17-19` que atribuye este job a `revenue` se sustituye por la razón real
por la que `send_checkin_reminders` sigue ausente (R4.7).

Rejected: `timedelta(days=1)` en `CADENCES` — dispara 24 h después de arrancar beat, no a las
06:00, y arrastra el TTL de tres días.
Rejected: convertir `CADENCES` en `dict[str, JobSchedule]` — toca las siete tareas vivas y sus
TTL derivados para acomodar la octava.

### D9 — Idempotencia: upsert por `(property_id, date)`, decisión humana intocable, transacción por propiedad

**Chosen:** el caso de uso lee de una vez el horizonte existente
(`list_for_property_range(tenant_id, property_id, date_from, date_to)`), lo indexa por fecha y
para cada día del horizonte decide:

| Estado existente | Acción |
|---|---|
| (no existe) | crear, contar en `created`, emitir `PRICE_RECOMMENDATION_CREATED` |
| `DRAFT`, `RECOMMENDED`, `REJECTED` | actualizar precio, `explanation` y `pricing_rule_id`; contar en `updated`; sin evento |
| `APPROVED`, `APPLIED_EXTERNAL` | **no tocar**; contar en `preserved` (R4.3) |

`REJECTED` se regenera a propósito: rechazar la propuesta de ayer no es una instrucción de no
volver a proponer, y dejarla congelada haría que un rechazo apagara esa fecha para siempre.

El `UNIQUE(property_id, date)` decide, no una lectura previa: el escritor usa
`INSERT … ON CONFLICT (property_id, date) DO UPDATE`, con la lectura previa sirviendo para saber
qué preservar y qué contar, no como control de concurrencia (R4.2).

**Y por eso el guardián de estado vive también en la sentencia** (decisión de Jose el
2026-08-17, sobre el hallazgo más grave del panel de QA). Este mismo párrafo dice que una lectura previa no es control
de concurrencia, y durante la sección 5 lo fue: el predicado del `ON CONFLICT` era solo
`tenant_id`, así que la tabla de arriba se aplicaba **únicamente** en memoria y era rancia por
construcción. El panel de QA de `/sdd:review` lo reprodujo — la manager aprueba el día +1 a
`777.00` a mitad del barrido y el upsert le deja `100.00`; el `status` sobrevive porque no está
en el `set_`, el **precio aprobado no**—, y sin rastro en ninguno de los dos sumideros: la
generación estaba exenta de `AuditLog` (D12) y las actualizaciones no emiten timeline (D14). El
lock del job nunca ayudó: serializa generadores entre sí, jamás contra una persona pulsando
Aprobar. Así que el predicado del `ON CONFLICT` gana
`AND status NOT IN ('APPROVED','APPLIED_EXTERNAL')` y las dos mitades son el mismo conjunto a
propósito, con un test que las fija iguales.

La consecuencia que había que resolver con él, y por la que las dos mitades van juntas: una fila
que el predicado salta **no vuelve en el `RETURNING`**, y esa cuenta corta era ya el detector de
escritura entre tenants. Arreglarlo a lo bruto convertiría un sobrescribir silencioso en una
alarma fatal falsa. Así que cuando la cuenta sale corta —y solo entonces— el adaptador pregunta
por las claves que faltan cuáles son suyas y están decididas: esas van a `UpsertOutcome.preserved`
y el resto sigue siendo `CrossTenantWriteError`. Una consulta más en un camino raro, a cambio de
que R4.3 sea cierto y no probable. El `preserved` del informe pasa a tener dos sumandos que no se
solapan: lo que vio la lectura previa y lo que rechazó la sentencia.

Rejected: dejar la carrera documentada como ventana conocida — es la lectura que el propio R4.3
prohíbe («preservarla intacta»), y no había endpoint todavía, así que arreglarlo aquí no costó
ninguna migración ni ningún cambio de contrato.

**Una transacción por propiedad**, no por tenant: son 60 filas por propiedad, y un fallo en una
propiedad no debe descartar el horizonte ya escrito de las anteriores. El fallo se cuenta en el
informe y el bucle sigue, dentro de la sesión marcada que `run_for_every_tenant` ya abre por
tenant.

**Cuatro precisiones que se añadieron al implementar la sección 5.** Las dos primeras son de
mecanismo; **la tercera y la cuarta sí tocan alcance** y se declaran como tales — una redacción
anterior de este párrafo decía «ambas de mecanismo y ninguna de alcance» y omitía las dos
últimas, que es exactamente la copia desactualizada que el panel de arquitectura de esta sección
levantó:

- **`UnitOfWork` gana `rollback()`** (`app/core/unit_of_work.py`, y su gemela vacía en
  `CallerOwnedUnitOfWork`). Sin ella «el bucle sigue» no es cierto: un fallo dentro del upsert
  deja la sesión inutilizable, así que el commit de la propiedad siguiente fallaría también y
  una sola regla mal formada se llevaría por delante la cartera entera — exactamente lo que esta
  decisión existe para evitar. El puerto es quien puede cerrar la transacción, así que es quien
  puede abandonarla; `application/` no importa SQLAlchemy en ningún caso.
- **El informe lleva un quinto contador, `failed`.** Los cuatro de R4.5 —`created`, `updated`,
  `preserved`, `skipped`— siguen siendo los que reporta el endpoint. `failed` es lo que hace que
  una propiedad caída no se reporte como barrido en verde sobre una cartera con un agujero;
  cada incremento va además al log con el `property_id` que lo causó. `skipped` no vale para
  esto: R4.6 le da un significado exacto —sin regla activa aplicable— y mezclar un fallo ahí
  diría que no había nada que hacer cuando lo que hubo fue un error.
- **Alcance: `POST /generate` sobre una propiedad `INACTIVE` responde `422`, no la cuenta.**
  R4.1 dice «cada propiedad **activa**», así que el barrido pregunta `list_by_status(ACTIVE)` y
  el ámbito nombrado significa lo mismo. La primera implementación la dejaba pasar y la contaba
  en `skipped`; el panel de arquitectura de la sección 5 lo rechazó aplicando el párrafo de
  arriba a su propio autor —dos causas en un solo número es un informe sobre el que nadie puede
  actuar—. Los dos rechazos del ámbito nombrado son distintos a propósito y no filtran nada:
  «desconocida o de otro tenant» comparten un mensaje constante porque R1.7 las necesita
  indistinguibles, mientras que «tuya pero inactiva» es un hecho sobre la cartera **del propio
  llamante**, así que nombrarlo no es un oráculo y sí es la respuesta accionable.
- **Alcance: el `property_id` desconocido del generador responde `422` y no `404`.** Es el
  criterio de D20 —un campo del cuerpo que nombra algo que el tenant no tiene— aplicado a un
  caso de uso que D20 no cubría, porque D20 habla de `CreatePricingRule` y `UpdatePricingRule`.
  Se declara aquí en vez de heredarse en silencio: el `404` de R1.7 es para el identificador del
  path, y el ámbito de una generación viaja en el cuerpo (OQ4).

Y el borde del `try` es **`Exception`**, con `CrossTenantWriteError` re-lanzado antes: la capa
`application/` no puede nombrar las excepciones del driver (nada fuera de `infrastructure/`
importa SQLAlchemy) y el lado del dominio no es más estrecho —una fila de regla anterior al
validador de la tarea 2.2 muere como `TypeError` **o** como `decimal.InvalidOperation`—. El
cruce de tenants se excluye a propósito: todas las propiedades del barrido salen de una consulta
scopeada, así que no es un dato que encoger de hombros sino el evento que la sección 3 hizo
fatal, y contarlo como una propiedad más fallida lo enterraría en una línea de log.

**Precondición de tenant que el esquema no impone, y que los puertos deben declarar.** Las claves
foráneas de `price_recommendations` (`property_id`, `pricing_rule_id`) y de `pricing_rules`
(`property_id`) son **globales, no compuestas con `tenant_id`**, así que la base de datos aceptaría
tan ricamente una recomendación del tenant A anclada a una propiedad del tenant B. Los repositorios
no pueden detectarlo sin una consulta propia. Es exactamente la precondición que
`app/maintenance/domain/repositories.py` escribe en el docstring de `IncidentRepository.add`, y aquí
se hereda igual: **quien llame resuelve `property_id` y `pricing_rule_id` dentro del `tenant_id` que
actúa, antes de persistir**, y los puertos de la tarea 3.1 lo dicen en su docstring en vez de
confiarlo a la memoria. El generador de D10 la cumple por construcción —las propiedades salen de
`list_by_status(tenant_id, …)` y la regla de `list_active(tenant_id)`—; el `POST` de reglas no, y
por eso su caso de uso valida el `property_id` contra el tenant. Lo levantó el panel de tenancy de
la sección 2.

Rejected: borrar y reinsertar el horizonte — perdería el `id` de filas que la manager ya está
mirando y borraría la decisión humana que R4.3 protege.

### D10 — Un solo caso de uso para el job y para `POST /generate`, síncrono

**Chosen:** `GeneratePriceRecommendationsUseCase.execute(tenant_id, *, now, property_id=None,
actor=None)` es el único generador. El job lo llama por tenant sin `property_id` y con
`actor=None`; el endpoint lo llama con el ámbito del cuerpo y con el usuario autenticado
(R4.5), **en la propia petición** y no encolando una tarea.

Síncrono porque el trabajo está acotado por construcción: 60 días × cartera de un tenant
(unidades que alguien gestiona físicamente, PRD §1), con una consulta de reservas y un upsert por
propiedad. Encolar añadiría un identificador de trabajo, un endpoint de consulta de estado y una
respuesta que R4.5 no admite — pide devolver **cuántas creó y cuántas actualizó**, que solo se
sabe al terminar.

Rejected: encolar una tarea Celery y devolver `202` — contradice el contrato de respuesta de
R4.5.

### D11 — RBAC: cuatro permisos nuevos, dos pares lectura/gestión

**Chosen:** en `app/auth/domain/policy.py`:

| Permiso | `TENANT_OWNER` | `PROPERTY_MANAGER` | Resto |
|---|---|---|---|
| `READ_PRICING_RULES` | sí | sí | no |
| `MANAGE_PRICING_RULES` | sí | sí | no |
| `READ_PRICE_RECOMMENDATIONS` | sí | sí | no |
| `MANAGE_PRICE_RECOMMENDATIONS` | sí | sí | no |

Cuatro y no dos, por el mismo criterio con que se partieron los de `reservations`,
`properties` y `cleaning`: leer y mutar son capacidades distintas. Pero, a diferencia de todos
ellos, **aquí la propietaria también gestiona**, y es una divergencia consciente del patrón
«la owner ve, el manager opera»: `min_price`/`max_price`/`max_daily_change_pct` son los límites
de su propio dinero (historia de usuario de R3, «pueda dejar el sistema generando sin
vigilarlo»), y PRD §19 Modo 1 dice literalmente «Manager/owner aprueba manualmente y actualiza
en OTA». Negarle cualquiera de los dos dejaría a una owner sin manager —la escala de PRD §1— sin
poder fijar sus propios topes ni aprobar un precio.

`MANAGE_PRICE_RECOMMENDATIONS` cubre las tres transiciones **y** `POST /generate`: forzar el
recálculo tras tocar una regla es la misma capacidad operativa, y un permiso para un botón no es
algo sobre lo que nadie razone por separado.

`CLEANER` y `TECHNICIAN` no reciben ninguno. `SUPER_ADMIN` tampoco, por el motivo que
`policy.py` ya declara para todos los permisos operativos dentro de un tenant.

Rejected: reutilizar `MANAGE_TENANT_SETTINGS` para las reglas — el precio de una vivienda no es
una preferencia del tenant, y quien configura SLAs no debería heredar la caja de precios.

### D12 — AuditLog: dos entidades, tres acciones, y la generación automática **sin fila**

**Chosen:** `app/audit/domain/actions.py` gana `ENTITY_PRICING_RULE` y
`ENTITY_PRICE_RECOMMENDATION`, y tres acciones:

- `PRICING_RULE_CREATED`, `PRICING_RULE_UPDATED` (R1.6);
- `PRICE_RECOMMENDATION_DECIDED` para `APPROVED` y `REJECTED` — una sola acción con el resultado
  en el diff, exactamente el precedente de `OWNER_APPROVAL_ANSWERED`: el desenlace es un campo
  de la entidad, y partirlo pondría la pregunta «qué se decidió sobre este precio» en dos sitios;
- `PRICE_RECOMMENDATION_APPLIED_EXTERNAL` aparte, porque **no es una decisión sino un hecho del
  mundo**: alguien publicó ese precio fuera del sistema. Un repaso pregunta por esas dos cosas
  por separado.

`AUDITABLE_FIELDS` gana `"PRICING_RULE"` con los doce campos escribibles (`name`, `active`,
`property_id`, `base_price`, `min_price`, `max_price`, `max_daily_change_pct`,
`weekday_modifiers`, `lead_time_rules`, `occupancy_rules`, `seasonality_rules`, `event_rules`) y
`"PRICE_RECOMMENDATION"` con `{"status"}` y nada más. Ninguno es un valor de la regla 3, así que
no hay entradas en la denylist.

Un `_AuditWriter` propio del módulo, con la disciplina de `maintenance`: **ninguna de las tres
acciones admite `actor=None`**, porque las tres las ejecuta una persona autenticada.

**Y la generación por el reloj no escribe `AuditLog`.** Rule 9 de `steering/security.md` nombra
`PricingRule/PriceRecommendation` en su enumeración, así que esto es un recorte de una
obligación vigente y necesita una **quinta excepción nombrada** en esa regla, escrita por una
tarea de este change. La justificación es la **ausencia de actor** de la cuarta excepción, más
la existencia de un sumidero hecho a medida como en la primera: el reloj dispara el job, no hay
persona ni petición de la que sacar `actor_ip`, y una generación de un tenant con dos viviendas
escribiría 120 filas idénticas y anónimas al día —43.800 al año— en la tabla cuyo índice por
actor existe para responder «todo lo que hizo esta persona». Lo que sí queda registrado es el
`TimelineEvent PRICE_RECOMMENDATION_CREATED` de cada recomendación nueva (R4.4) y el informe de
la ejecución.

**Corregido el 2026-08-17 (decisión de Jose): la excepción cubre el reloj
y solo el reloj.** Una redacción anterior de este párrafo —y de OQ1— eximía también
`POST /price-recommendations/generate` con la misma razón, y esa razón es falsa para el
endpoint: `execute(..., actor)` recibe allí un `user_id` **y** un `ip`, y esta misma sección
firma sus filas de timeline como `TimelineActorType.USER` precisamente porque hay una persona.
Las excepciones 2 y 3 de la regla 9 dicen literalmente que «no exime la lectura con actor humano
o iniciada por API». Sin la fila, una `PROPERTY_MANAGER` autenticada podía pulsar generar
repetidamente y reescribir precios sin rastro **en ninguno de los dos sumideros**: en un
horizonte ya lleno no se inserta nada, así que D14 no emite timeline, y el camino manual no
lleva lock. Lo levantó el panel de seguridad de la sección 5.

Así que hay una **cuarta acción**, `PRICE_RECOMMENDATIONS_GENERATED`, **una fila por propiedad
repreciada** y solo por el camino humano. Sobre `ENTITY_PROPERTY`, porque un horizonte son 60
recomendaciones y `AuditLog.entity_id` es un UUID único obligatorio sin columna de ejecución de
la que colgar otra cosa —es el mismo hecho que ya rechazaba «una fila por ejecución» más abajo—.
**Sin diff**: el hecho auditado es «esta persona repreció esta propiedad», y los contadores viven
en la respuesta y en el log, no en un segundo sitio. El mecanismo es que `_AuditWriter` solo se
invoca cuando hay actor, así que la exención del job es una consecuencia y no un caso especial.

Lo que la excepción **no** concede: no exime `POST /generate`, no exime ninguna decisión humana
sobre una recomendación, no exime nada de `PricingRule`, y no dice nada sobre otros jobs.
Ver **OQ1**.

Rejected: una fila por recomendación generada — el volumen descrito, sin un «quién» que aportar.
Rejected: una fila por ejecución — `AuditLog.entity_id` es un UUID único obligatorio y no hay
columna de ejecución; sería prometer un formato que el esquema no admite (rule 9 ya registra
que dos redacciones anteriores lo hicieron).

### D13 — `explanation`: plantilla cerrada, en inglés, y una fila nueva en el censo de la regla 11

**Chosen:** `app/pricing/domain/explanation.py` renderiza el `PriceCalculation` de D2 con una
plantilla fija, en inglés (R6.4, `sdd/project.md` Conventions), sin pasar por ningún adaptador de
IA (R6.2). Forma:

```
Base price 100.00 EUR. Weekday (saturday) +20.00% -> 120.00. Lead time (<=3 days) -10.00% -> 108.00.
Occupancy (>50%) +5.00% -> 113.40. Season (high_summer) +30.00% -> 147.42.
Guardrail max_daily_change_pct (+20.00% of 110.00) -> 132.00. Guardrail max_price -> 130.00.
Recommended 130.00 EUR.
```

`confidence` se fija en `1.00` (R6.3) con un comentario en el código que dice que el campo existe
para un modo futuro con incertidumbre real, no para adornar el determinismo actual.

**`price_recommendations.explanation` pasa a ser el sumidero número catorce de la regla 11**, y
este change es su primer escritor. El único texto que no compone nuestra plantilla es el `name`
que la propia manager escribió en una `seasonality_rule` o una `event_rule` de su tenant. La fila
del censo lo declara con **excepción propia**, con la forma de la excepción 3 (el valor no es
nuestro y no lo hemos ido a buscar: lo teclea un usuario autenticado con RBAC, sobre el precio de
su propia vivienda, acotado a 100 caracteres por R1.4). Como en las excepciones 2 y 3: **no se
propaga** — el `name` no entra en `AUDITABLE_FIELDS["PRICE_RECOMMENDATION"]`, que es solo
`{"status"}`, ni en el `metadata` de ningún `TimelineEvent`, que lleva identificadores y el
precio. Ver **OQ2**.

Rejected: renderizar solo el *tipo* de modificador y omitir el `name` — R6.1 pide el nombre, y
«temporada» sin decir cuál no explica nada a quien tiene que aprobar el precio.
Rejected: declararla «estructurada» sin excepción — sería la promesa que su escritor no cumple,
el error que `security.md` ya registra para `owner_approvals.response_notes`.

### D14 — Timeline: quién emite qué, y con qué actor

**Chosen:** dos emisores, ninguno más.

| Evento | Cuándo | `actor_type` | `metadata` |
|---|---|---|---|
| `PRICE_RECOMMENDATION_CREATED` | recomendación **nueva** (R4.4) | `SCHEDULER` (job) / `USER` (endpoint) | `recommendation_id`, `date`, `recommended_price`, `pricing_rule_id` |
| `PRICE_UPDATED_EXTERNAL` | transición a `APPLIED_EXTERNAL` (R5.3) | `USER` | `recommendation_id`, `date`, `recommended_price` |

Solo las creaciones emiten evento, nunca las actualizaciones: en régimen estacionario el job crea
una sola fecha nueva por propiedad y día (la que entra por el extremo del horizonte) y actualiza
las otras 59, así que el timeline recibe un evento por propiedad y día en lugar de sesenta. La
primera ejecución sobre una propiedad sí emite 60 — es correcto y ocurre una vez.

`TimelineEventFactory` solo admite `actor_user_id` junto a `USER`, así que las dos vías quedan
distinguibles por construcción. Los títulos ES/EN de los dos tipos **ya existen** en
`app/timeline/domain/rendering.py:211-218`: no hace falta i18n nueva.

Rejected: un evento por actualización — ahogaría el timeline de la propiedad, que es «ciudadano
de primera clase» y se lee para saber qué pasó, no para ver un recálculo diario.

### D15 — Errores: tabla exhaustiva en `pricing/api/errors.py`, sin códigos nuevos

**Chosen:** `app/pricing/domain/exceptions.py` con jerarquía plana bajo `PricingDomainError`, y
`app/pricing/api/errors.py` con la tabla exhaustiva al estilo de `maintenance`:

| Excepción | HTTP | `ErrorCode` |
|---|---|---|
| `PricingRuleNotFoundError`, `PriceRecommendationNotFoundError` | 404 | `NOT_FOUND` |
| `InvalidRecommendationTransitionError` | 409 | `CONFLICT` |
| `PricingValidationError` (y subclases) | 422 | `VALIDATION_ERROR` |

**Ningún `ErrorCode` nuevo**: los tres necesarios ya están en `app/core/error_codes.py`, así que
el registro único y el contrato publicado no cambian de forma. `app/main.py` registra el handler
y monta los dos routers; `app/core/error_codes.py` gana `pricing` en la lista de módulos de su
docstring y en la guarda de `tests/test_openapi_contract.py`, que refleja sobre los `_MAPPING`
por import — un módulo con router y sin entrada en la guarda es el punto ciego que ese docstring
documenta que ya se materializó una vez con `properties`.

El `404` de otro tenant (R1.7) sale de que los repositorios devuelven `None` fuera del
`tenant_id`, igual que `reservations` y `maintenance`: el caso de uso nunca pregunta «¿existe en
otro sitio?».

### D16 — La validación de una regla vive en el dominio, no solo en Pydantic

**Chosen:** `PricingRule.validate()` (o una factoría `PricingRule.create`) comprueba en
`domain/` las invariantes de R1.3 y R1.4 —`min_price <= max_price`, `base_price` dentro del
rango, `max_daily_change_pct` en `[0, 100]`, y el esquema de los cinco JSONB, incluida la forma
de festivos de D7— y lanza `PricingValidationError` nombrando el campo que falla. Los esquemas
Pydantic de `api/schemas.py` validan tipos y formas de request, pero **no son la única puerta**:
el `POST /generate` y el job leen reglas escritas antes, y `steering/backend.md` es explícito en
que la lógica no vive en el router.

Es un caso claro de los que `backend-architecture.md` llama «dominio con invariante real» —cita
literalmente «guardrails de pricing» como ejemplo—, así que la ceremonia táctica está
justificada por la invariante que protege.

Rejected: validar solo con Pydantic — deja el job y el CSV/seed de futuro sin red, y pone una
regla de negocio en la capa `api/`.

### D17 — `PropertyRepository.list_by_status`

**Chosen:** el job necesita «cada propiedad activa» (R4.1). `PropertyRepository` tiene hoy
`list_by_state` (estado operacional), `list_all` (todo, sin filtro) y `list` (paginado, para el
endpoint). Se añade `list_by_status(tenant_id, status) -> list[Property]`.

No es una preferencia: el docstring de `list_all` dice literalmente que «un caller que solo
necesita un subconjunto debería añadir un método más estrecho en vez de filtrar éste en
memoria». Se obedece.

Rejected: `list_all` + filtro en el caso de uso — contradice el contrato escrito del puerto.
Rejected: paginar sobre `list()` dentro de un job — pagina para una UI, no para un barrido.

### D18 — Las constantes del horizonte son de dominio, no de `Settings`

**Chosen:** `HORIZON_DAYS = 60` y `OCCUPANCY_WINDOW_DAYS = 30` viven en
`app/pricing/domain/constants.py`. Son cifras del PRD (§8.3 y §7.17), no palancas de operación:
cambiarlas cambia lo que el sistema promete, y eso se revisa en un Pull Request, no en un `.env`.
**Consecuencia: este change no añade ninguna variable de entorno**, así que `.env.example` no se
toca.

Rejected: `Settings.pricing_horizon_days` — invita a que dos entornos calculen horizontes
distintos y a que un test lo baje sin que nadie lo note.

### D19 — Lo que este change deja explícitamente fuera, y las dos notas que corrige

**Chosen:** ninguna llamada al `PMSAdapter` en ningún punto (R5.5, Modo 1), ningún
`PricingDataAdapter` —el adapter de datos de mercado que `steering/architecture.md` enumera
existe para un pricing que este MVP declara non-goal (PRD §29)— y `current_price` se escribe
siempre `NULL`, porque su fuente sería `get_availability`.

Las dos notas que hoy prometen lo contrario quedan corregidas en este mismo change (R4.7):
`app/scheduler/schedule.py:17-19` y `app/integrations/domain/ports.py:93-94`, esta última
diciendo que las tres operaciones ARI llegan con un change de ARI propio cuando exista quien las
consuma, no con `revenue`.

### D20 — El `property_id` que teclea un humano se resuelve dentro del tenant, siempre

**Chosen:** `CreatePricingRule` y `UpdatePricingRule` resuelven el `property_id` del cuerpo con
`PropertyRepository.get(tenant_id, property_id)` **antes** de construir o mutar la entidad, y
responden `422` si no existe en ese tenant. `upsert_many` hace lo propio con las propiedades de
cada horizonte (`_require_properties_of_tenant`).

**Por qué hace falta una decisión y no basta la precondición escrita en D9.** Las FK de
`pricing_rules.property_id` y `price_recommendations.property_id` son globales, no compuestas con
`tenant_id`, y `price_recommendations` lleva `UNIQUE (property_id, date)` **sin tenant**. El panel
de seguridad de la sección 3 demostró que eso no es un detalle de integridad sino un ataque entre
tenants: una fila del tenant A anclada a una propiedad del B es internamente coherente —su
`tenant_id` *es* el de A— así que pasa cualquier comprobación que compare la entidad con el tenant
que actúa. Y el daño no es el sobrescribir que protege el `ON CONFLICT … WHERE`, sino el **primer
insert**, que no encuentra conflicto: A se queda la clave `(P, fecha)` y a partir de ahí todo
upsert de B sobre su propia propiedad-día choca, falla el predicado y **se descarta en silencio y
para siempre**.

Alcance de lo implementado en la sección 3: el puerto de recomendaciones ya lo cierra por su
cuenta con una consulta de pertenencia, y el descarte silencioso pasó a `CrossTenantWriteError`.
Lo que queda para las secciones 5 y 6 es la otra mitad, la que entra por teclado: el `property_id`
de una `PricingRule`.

Rejected: meter `tenant_id` en el `UNIQUE` (o una FK compuesta `(tenant_id, property_id)`) — lo
cierra de verdad y a nivel de esquema, pero es **una migración**, y el proposal declara que este
change no la necesita. Queda anotado como candidato de un change propio; si se hace, la consulta
de pertenencia de `upsert_many` se vuelve redundante y se puede quitar.

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| Dominio pricing | `app/pricing/domain/entities.py` | `PricingRule.create/validate/update_details`; `PriceRecommendation.decide/mark_applied_external` (D16) |
| | `app/pricing/domain/calculator.py` *(nuevo)* | `calculate_price`, `PriceCalculation`, `AppliedModifier`, `AppliedGuardrail`, `season_matches`, `event_match_name` (D2, D3, D4) |
| | `app/pricing/domain/occupancy.py` *(nuevo)* | `occupancy_pct_for` puro sobre reservas (D5) |
| | `app/pricing/domain/rule_resolution.py` *(nuevo)* | `resolve_rule` (D6) |
| | `app/pricing/domain/holidays.py` *(nuevo)* | `SPAIN_NATIONAL_HOLIDAYS` 2025-2027 (D7) |
| | `app/pricing/domain/explanation.py` *(nuevo)* | render en inglés del `PriceCalculation` (D13) |
| | `app/pricing/domain/constants.py` *(nuevo)* | `HORIZON_DAYS`, `OCCUPANCY_WINDOW_DAYS` (D18) |
| | `app/pricing/domain/repositories.py` *(nuevo)* | `PricingRuleRepository`, `PriceRecommendationRepository`, filtros y `Page` |
| | `app/pricing/domain/exceptions.py` *(nuevo)* | jerarquía plana bajo `PricingDomainError` (D15) |
| Aplicación | `app/pricing/application/use_cases.py` *(nuevo)* | 7 casos de uso + `_AuditWriter` propio (D10, D12) |
| Infraestructura | `app/pricing/infrastructure/repositories.py` *(nuevo)* | adaptadores SQLAlchemy, upsert `ON CONFLICT` (D9) |
| API | `app/pricing/api/{rules_router,recommendations_router,schemas,dependencies,errors}.py` *(nuevos)* | las 7 rutas de PRD §23 (D1, D15) |
| Auth | `app/auth/domain/policy.py` | 4 permisos y su reparto por rol (D11) |
| Audit | `app/audit/domain/actions.py`, `value_objects.py` | 2 `entity_type`, 3 acciones, 2 entradas de `AUDITABLE_FIELDS` (D12) |
| Properties | `app/properties/domain/repositories.py`, `infrastructure/repositories.py` | `list_by_status` (D17) |
| Scheduler | `app/scheduler/schedule.py` | `DailySchedule`/`DAILY_JOBS`, `beat_schedule()` derivado de las dos tablas, nota corregida (D8, D19) |
| | `app/scheduler/tasks.py` | tarea `generate_price_recommendations` con `_guarded`-equivalente para TTL explícito |
| Integrations | `app/integrations/domain/ports.py` | nota de ARI corregida (D19) |
| App | `app/main.py`, `app/core/error_codes.py` | montaje de routers y handler; `pricing` en la guarda de contrato (D15) |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados (las dos mitades del puente, `steering/documentation.md`) |
| Steering | `sdd/steering/security.md` | 5.ª excepción de la regla 9 (OQ1) y fila 14 del censo de la regla 11 (OQ2) |
| Docs | `docs/pricing.md` *(nuevo)*, `README.md` | página de capability y módulo nuevo |

## Data & interfaces

**Migración: ninguna.** `pricing_rules`, `price_recommendations` y el enum
`price_recommendation_status` ya están en `96d526599bc1_domain_foundation_financial`.

**Variables de entorno: ninguna** (D18).

**Rutas** (las siete de PRD §23, todas bajo Bearer JWT):

| Método | Ruta | Permiso | Notas |
|---|---|---|---|
| `GET` | `/api/v1/pricing-rules` | `READ_PRICING_RULES` | paginado `?page&per_page`, filtro `?property_id&active` |
| `POST` | `/api/v1/pricing-rules` | `MANAGE_PRICING_RULES` | `201` + id (R1.1) |
| `GET` | `/api/v1/pricing-rules/{id}` | `READ_PRICING_RULES` | `404` fuera del tenant (R1.7) |
| `PATCH` | `/api/v1/pricing-rules/{id}` | `MANAGE_PRICING_RULES` | campos parciales; `422` por R1.3/R1.4 |
| `GET` | `/api/v1/price-recommendations` | `READ_PRICE_RECOMMENDATIONS` | filtros `?property_id&date_from&date_to&status`, paginado |
| `POST` | `/api/v1/price-recommendations/generate` | `MANAGE_PRICE_RECOMMENDATIONS` | cuerpo `{property_id?}`; devuelve `{created, updated, preserved, skipped}` (R4.5) |
| `PATCH` | `/api/v1/price-recommendations/{id}` | `MANAGE_PRICE_RECOMMENDATIONS` | cuerpo `{status}`; solo las tres transiciones legales |

**Máquina de estados de `PriceRecommendation`** (R5.2, R5.3, R5.4). Solo tres transiciones son
legales; cualquier otra es `409` sin tocar el estado:

| Desde | Hasta | Efectos |
|---|---|---|
| `RECOMMENDED` | `APPROVED` | `AuditLog PRICE_RECOMMENDATION_DECIDED` |
| `RECOMMENDED` | `REJECTED` | `AuditLog PRICE_RECOMMENDATION_DECIDED` |
| `APPROVED` | `APPLIED_EXTERNAL` | `AuditLog PRICE_RECOMMENDATION_APPLIED_EXTERNAL` + `TimelineEvent PRICE_UPDATED_EXTERNAL` |

`DRAFT` no lo escribe ni lo acepta nadie: el enum lo declara (PRD §7.18) y ninguna vía de este
change lo produce ni transiciona desde él.

**Cobertura de requisitos**: R1→D1/D6/D11/D12/D15/D16; R2→D2/D3/D5/D7; R3→D4; R4→D8/D9/D10/D17/D19;
R5→D1/D11/D12/D14/D15/D19; R6→D2/D13. Ningún requisito del proposal queda sin implicación de
diseño.

## Risks & mitigations

- **La `explanation` es un sumidero de texto en claro nuevo** (D13). Mitigación: fila propia en
  el censo de la regla 11, `name` acotado a 100 caracteres en la validación de la regla, y
  verificación de que no se propaga a `audit_logs.changes` ni a `timeline_events.metadata` —
  `AUDITABLE_FIELDS["PRICE_RECOMMENDATION"]` es `{"status"}` y `ChangeSet` rechaza por
  construcción cualquier otro campo.
- **Aritmética con `float` filtrándose desde los JSONB.** Los `modifier_pct` llegan como `int` o
  `float` de JSONB. Mitigación: conversión con `Decimal(str(v))` en un único punto de entrada y
  un test que asserta el tipo `Decimal` en cada paso de `PriceCalculation`; R2.4 declara el
  `float` un defecto, así que es material de panel de QA.
- **Coste de la generación**: 60 filas × cartera, cada día. Con la escala del MVP (2 viviendas)
  son 120 upserts y una consulta de reservas por propiedad. Mitigación: ocupación calculada una
  vez por propiedad (D5), lectura del horizonte en una consulta (D9), transacción por propiedad.
  Si una cartera crece, el techo es lineal y visible en el informe de la tarea.
- **Dos reglas activas para la misma propiedad** (D6). Mitigación: desempate determinista y
  documentado; ver OQ3 para si además se rechaza en escritura.
- **El lock de un job diario**. Un TTL mal dimensionado bloquea el job hasta tres días.
  Mitigación: TTL explícito de 3 h en `DailySchedule` (D8) y un test que comprueba que ninguna
  tarea diaria deriva su TTL de `lock_ttl_for`.
- **La guarda de contrato no ve un módulo nuevo.** Mitigación explícita en D15: `pricing` entra
  en la lista de `tests/test_openapi_contract.py` en la misma tarea que crea `api/errors.py`.

## Open questions

Las cuatro se resolvieron en el gate de `/sdd:design` (Jose, 2026-08-16). Quedan escritas con su
alternativa rechazada porque dos de ellas amplían `steering/security.md` y la regla 9 exige que
la ampliación conste con su razón.

**OQ1 — Quinta excepción nombrada de la regla 9 de `steering/security.md`. → APROBADA, y
después ESTRECHADA.** La generación **por el reloj** no escribe `AuditLog` (D12); su rastro es el
`TimelineEvent PRICE_RECOMMENDATION_CREATED` de cada recomendación nueva y el informe de la
ejecución. Rechazado: una fila por recomendación generada — ~120 al día con dos viviendas, todas
anónimas e idénticas, en la tabla cuyo índice por actor existe para otra pregunta.

**Estrechada el 2026-08-17** (Jose, sobre el hallazgo bloqueante del panel de seguridad de la sección 5): la redacción aprobada en el gate del
2026-08-16 eximía también `POST /price-recommendations/generate`, y la razón que daba —«ausencia
de actor»— es verdadera del reloj y falsa del endpoint, que recibe `user_id` e `ip`. El endpoint
escribe ahora una fila `PRICE_RECOMMENDATIONS_GENERATED` por propiedad repreciada (D12).
Rechazado: conservar la exención y reescribir la justificación de la tarea 8.1 — habría que
encontrar una razón que sobreviva a las excepciones 2 y 3 de la propia regla 9, que dicen
literalmente «no exime la lectura con actor humano o iniciada por API». Rechazado también:
cerrarlo por el lado del timeline en vez del `AuditLog` — mueve la pregunta «quién movió este
precio» a una tabla append-only que no lleva `actor_ip`.

**La aprobación en este design no es lo que amplía la regla**: lo es la entrada nueva y nombrada
en `security.md`, que escribe una tarea de este change. Su alcance es el que D12 fija y no crece:
solo la generación por el job, y no exime `POST /generate`, ni ninguna decisión humana sobre una
recomendación, ni nada de `PricingRule`.

**OQ2 — Fila 14 del censo de la regla 11 para `price_recommendations.explanation`, con excepción
propia. → APROBADA.** La `explanation` echa el `name` que la manager teclea en sus reglas de
temporada y evento, bajo la forma de la excepción 3: el valor no es nuestro y no lo hemos ido a
buscar. Rechazado: renderizar solo el tipo de modificador («Season +30%», sin decir cuál), que
cumple R6.1 a medias. La escribe una tarea de este change, igual que OQ1.

**OQ3 — Dos reglas activas para la misma propiedad. → Desempate determinista, sin migración.**
`resolve_rule` gana por `updated_at` más reciente con `id` como desempate final (D6). Rechazado:
un índice único parcial (`WHERE active AND property_id IS NOT NULL`) — cierra la carrera de
verdad, pero es la migración que el proposal declara innecesaria. Rechazado: rechazar en escritura
sin índice — deja la carrera abierta y da la falsa impresión de que el estado es imposible.

**OQ4 — `POST /generate` sin `property_id`. → Permitido, barrido completo del tenant.**
Es lo que R4.5 pide («el ámbito indicado»), y el techo es lineal y visible en la respuesta
`{created, updated, preserved, skipped}` (D10). Rechazado: exigir `property_id` — obligaría a una
llamada por propiedad tras tocar una regla de tenant, que es justo el caso que motiva el endpoint.
