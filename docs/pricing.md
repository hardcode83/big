# Precios recomendados — cómo se opera

Capability de los changes `revenue-pricing` (backend) y `pricing-web` (la pantalla) — PRD §19,
§7.17, §24, §26.22. Esta página cuenta **cómo se usa y se opera**. El *qué hace*, con sus
criterios EARS, vive en `sdd/specs/revenue-pricing.md`. El contrato HTTP está en
`backend/openapi.json`.

## Lo primero, porque cambia cómo se lee todo lo demás: Modo 1

**El sistema recomienda un precio y no lo publica nunca.** Calcula, explica y espera. Quien
aprueba sube el precio a la OTA **a mano** y luego lo marca como aplicado, que es lo que
significa el estado `APPLIED_EXTERNAL`: no «el sistema lo publicó», sino «una persona confirma
que ya está puesto ahí fuera».

Es el Modo 1 de PRD §19 y es una decisión de producto, no una fase intermedia: no hay ninguna
llamada de escritura al PMS en este módulo, y no la hay ni siquiera latente. `update_price`,
`block_dates` y `get_availability` siguen sin existir en `PMSAdapter` y llegarán con un change
de ARI propio, cuando exista quien las consuma.

```
la manager escribe una regla        POST /api/v1/pricing-rules
        │
        ▼
el reloj genera el horizonte        generate_price_recommendations, diario 06:00 UTC
   (o una persona lo fuerza)        POST /api/v1/price-recommendations/generate
        │
        ▼
60 días de precio propuesto, cada uno con su explanation en texto
        │
        ├── aprobar   ──► APPROVED   ──► la persona lo sube a la OTA a mano
        │                                  └─► marcar APPLIED_EXTERNAL
        └── rechazar  ──► REJECTED   ──► se vuelve a proponer mañana (ver abajo)
```

## Escribir una regla

Una `PricingRule` es un precio base más cinco tablas de modificadores, y todas son opcionales:
una regla con solo `base_price`, `min_price` y `max_price` ya es válida y produce un horizonte
plano.

`property_id` decide el alcance: con un id, la regla es de esa vivienda; **a `null`, es la regla
del tenant** y cubre toda propiedad que no tenga una propia. Cuando ambas existen, gana la de la
vivienda.

### Los cinco JSONB

Los porcentajes son siempre eso, porcentajes: `15` es +15 %, `-10` es un descuento del 10 %.

| Columna | Forma de cada entrada | Qué hace |
|---|---|---|
| `weekday_modifiers` | objeto `{"friday": 20, "saturday": 25}` | Recargo o descuento por día de la semana. Las claves son los siete nombres en inglés y minúscula |
| `lead_time_rules` | `{"days_before": 7, "modifier_pct": -10}` | Por antelación. Aplica **el umbral más ajustado** que la fecha alcanza |
| `occupancy_rules` | `{"occupancy_pct_above": 70, "modifier_pct": 15}` | Por ocupación de los **30 días siguientes** a la ejecución. Igual: el umbral más alto que se supere |
| `seasonality_rules` | `{"name": "Verano", "start_month": 6, "start_day": 15, "end_month": 9, "end_day": 15, "modifier_pct": 30}` | Temporadas por día y mes, sin año. Un rango cuyo final precede al inicio **da la vuelta al año** a propósito: 20 dic → 6 ene es la temporada más obvia que hay |
| `event_rules` | `{"name": "Feria", "date": "2026-05-02", "modifier_pct": 40}` **o** `{"holidays": "ES_NATIONAL", "modifier_pct": 15}` | Fechas sueltas. Una entrada es de una forma o de la otra, nunca de las dos |

Dos avisos que ahorran sorpresas:

- **Temporadas y eventos aplican *todas* las entradas que coincidan**, no solo la primera. Dos
  temporadas solapadas sobre el mismo día multiplican sus dos modificadores.
- Cada array admite **50 entradas como máximo**, y el `name` de una temporada o evento **100
  caracteres**. No es decoración: ese `name` es el único texto de la `explanation` que no
  compone nuestra plantilla, y por eso tiene su propia fila en el censo de sumideros de texto
  libre (regla 11 de `sdd/steering/security.md`).

### El catálogo de festivos

`{"holidays": "ES_NATIONAL", "modifier_pct": 15}` referencia los festivos nacionales de España
2025-2027, embebidos en el código: nueve fechas fijas más el Viernes Santo escrito año a año, en
vez de calcular la Pascua. `ES_NATIONAL` es **el único** identificador aceptado.

Lo que ese catálogo NO es, y conviene saberlo antes de confiarle un calendario:

- **No es el calendario laboral del BOE.** Ese sustituye por comunidad autónoma los festivos que
  caen en domingo, y esa es una decisión por región que este catálogo no puede tomar.
- **No trae festivos autonómicos ni municipales.** Esos van como `event_rules` literales, con su
  fecha y su porcentaje, tal como declara el propio PRD.
- **El porcentaje no lo pone el catálogo**, que solo aporta las fechas. Lo pone la entrada que lo
  referencia — de ahí el `modifier_pct` en la misma línea.

## Cómo sale el precio, y en qué orden

Primero el `base_price`, luego los modificadores en cadena (día de la semana → antelación →
ocupación → temporada → evento), y **los guardrails al final**:

1. el tope de variación diaria `max_daily_change_pct`, medido contra el precio **persistido** del
   día anterior, no contra el que se acaba de calcular;
2. y después `min_price`/`max_price`.

Ese orden importa y es deliberado: los límites van **los últimos**, así que ningún precio emitido
queda nunca fuera del rango aunque el tope diario lo permitiera. El primer día del horizonte no
tiene tope diario, porque no hay día anterior contra el que medirlo.

**Y si ves un salto que el tope diario «no debería» permitir, probablemente no es un fallo.** El
tope sólo se impone hacia delante, y una recomendación que ya aprobaste no se toca al regenerar,
así que el par *(día recalculado, día aprobado)* queda sin acotar entre sí: con base 100 y tope
20%, unos días aprobados a 200/300/120 dejan el horizonte en `[200, 160, 300, 240, 120, 100]`.
Lo mismo pasa en la cabecera del calendario, porque cada ejecución arranca sin referencia. Lo que
sí se garantiza es que el día **siguiente** a uno aprobado se mide contra el precio que tú ves, no
contra uno recalculado por dentro.

## Cuándo corre el job, y cómo forzarlo

Corre **a las 06:00 UTC** —no locales: el worker fija su zona en UTC a propósito y las horas
locales se derivan de la zona de cada propiedad—, una vez por tenant activo, sobre las 60 días
siguientes de cada vivienda activa con regla aplicable. Una vivienda sin regla se omite sin
error y sin dejar el job en fallo.

Para forzarlo sin esperar al reloj, lo normal es el botón **Regenerar ahora** de `/pricing` (ver
abajo). Por API:

```bash
# todo el portfolio del tenant, tal como lo haría el reloj
curl -X POST localhost:8000/api/v1/price-recommendations/generate \
  -H "Authorization: Bearer $TOKEN"

# una sola vivienda
curl -X POST localhost:8000/api/v1/price-recommendations/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"property_id": "<uuid>"}'
```

La respuesta dice cuántas creó, actualizó, preservó y omitió.

**Repetirlo es seguro, y esa es la propiedad de la que depende todo lo demás.** El escritor hace
upsert por `(property_id, date)` y la propia sentencia se niega a tocar una recomendación que ya
está `APPROVED` o `APPLIED_EXTERNAL`. Así que el reloj disparando dos veces, o alguien relanzando
a mano, vuelve a calcular los días sin decidir y deja intactos los decididos. Un `REJECTED`
**sí** se regenera, a propósito: rechazar la propuesta de ayer no es una instrucción de no volver
a proponer nada, y congelarlo apagaría esa fecha para siempre.

Diferencia que importa entre las dos vías: **la generación por el reloj no escribe `AuditLog`**
—no hay persona a la que nombrar— y la que pide alguien **sí**, una fila por vivienda. Es la
quinta excepción nombrada de la regla 9 de `sdd/steering/security.md`, y está acotada
exactamente a eso.

```bash
# ver el despacho y el informe de cada ejecución
docker compose logs -f beat
docker compose logs -f worker
```

## Operar los precios desde `/pricing`

Desde el change `pricing-web` la pantalla existe y es donde se trabaja: **dos pestañas bajo la
misma ruta**, sin subrutas y sin `?tab=` — la pestaña activa no viaja en la URL, así que no hay
enlace que compartir a la de reglas.

**Pestaña «Recomendaciones»** (la que se abre por defecto), la cola de decisión:

- Filtros: vivienda, rango de fechas (`date_from`/`date_to`) y estado. Cambiar cualquiera vuelve
  a la página 1 — si no, te quedarías en una página que el conjunto filtrado ya no tiene.
- Por fila: vivienda, día, precio recomendado, estado y la `explanation` **plegada** en un
  desplegable cerrado. No verás `current_price` (siempre vacío en Modo 1), ni `confidence`
  (siempre `1.00`, el cálculo es determinista), ni fecha de la decisión — el contrato no la
  publica, así que la pantalla no puede inventarla.
- **Los tres movimientos**, con confirmación en dos pasos dentro de la propia fila:
  **Aprobar** y **Rechazar** sobre una fila `RECOMMENDED`, y **Marcar como publicada** sobre una
  ya `APPROVED`. Ese tercer botón es el que cierra el Modo 1: significa «ya subí este precio a la
  OTA a mano», y sin él una fila aprobada no tiene salida. Los demás estados no ofrecen ninguno.
- Mientras una decisión vuela se deshabilitan los botones de **todas** las filas y el de
  regenerar; los filtros siguen usables.
- **Regenerar ahora** dispara la generación sobre la vivienda del filtro activo, o sobre todo el
  portfolio si no hay filtro, y anuncia los cuatro contadores («0 creadas, 60 actualizadas, 0
  conservadas, 1 omitidas»). Corre **en la petición**: no hay progreso que sondear. Ojo con lo que
  ese aviso *no* dice — el contrato no publica un contador `failed`, así que **un barrido con
  agujeros se ve verde**; si sospechas, el log del worker sí nombra la vivienda que falló.

**Pestaña «Reglas»**, en **sólo lectura**: por regla su nombre, el ámbito («Toda la cartera»
cuando no cuelga de una vivienda), si está activa, la banda mínimo/base/máximo, el tope diario y
**cuántas** entradas hay en cada una de las cinco columnas JSONB. Se cuenta el interior, nunca se
pinta: pintarlo sería reimplementar el esquema de PRD §7.17 en el navegador. Para **escribir** una
regla sigue haciendo falta la API (`POST`/`PATCH /api/v1/pricing-rules`) — el formulario tiene
entrada de roadmap propia, y no está aquí porque la norma del proyecto prohíbe pintar el cuerpo
del `422`, así que la pantalla no podría decirte cuál de las cinco columnas rechazó el backend.

Detalles que ahorran un susto:

- **Los importes van sin moneda**, porque ninguna respuesta de pricing lleva `currency`. El
  separador es el del idioma: `120,00` en español y `120.00` en inglés — es el mismo número.
- **El día no se convierte de zona.** Un navegador al oeste de UTC ve la misma noche que el
  backend calculó, no la anterior.
- **`DRAFT` tiene etiqueta pero no lo produce nadie.** Está en el enum por PRD §7.18 y no lo
  escribe ningún camino.
- **A partir de la vivienda 100 los nombres degradan.** El catálogo se pide en una sola página de
  100, así que en una cartera mayor las que se queden fuera aparecen como no encontradas en vez de
  por su nombre.
- **El sidebar no filtra por rol**: un `CLEANER` ve la entrada «Precios» y, al entrar, la pantalla
  le dice que no tiene permiso — no una pantalla en blanco. La propietaria **sí** decide aquí (ver
  «Permisos»), y ésa es la divergencia consciente del patrón habitual.
- **Un `409` al decidir** tiene su propio mensaje, distinto del error genérico: significa que la
  fila ya no está en el estado que la pantalla creía, normalmente porque alguien más la decidió.
  Vuelve a cargar y mira el estado nuevo.

## Leer una `explanation`

Cada recomendación lleva la frase que la justifica, en inglés como el resto de los mensajes de
sistema, compuesta por una plantilla cerrada. **No participa ningún adaptador de IA**: el precio
es determinista por reglas y la IA no calcula nada aquí.

Salida real del renderizador para un viernes de temporada alta con el precio de ayer en 130,00 y
un tope diario del 10 %:

```
Base price 100.00 EUR. Weekday (friday) +20.00% -> 120.00. Season (Verano) +30.00% -> 156.00. Guardrail max_daily_change_pct (+10.00% of 130.00) -> 143.00. Recommended 143.00 EUR.
```

Se lee de izquierda a derecha como la cadena que se aplicó: cada frase dice qué actuó, con qué
porcentaje y con qué precio se quedó, y la última repite el precio final. Cuando un guardrail
recorta, aparece **nombrado por su columna** con su límite y su referencia — que es lo que permite
distinguir «la regla pedía 156,00 y el tope diario lo dejó en 143,00» de «la regla pedía 143,00».

## Permisos

Cuatro, en los dos pares habituales: `READ_PRICING_RULES` / `MANAGE_PRICING_RULES` y
`READ_PRICE_RECOMMENDATIONS` / `MANAGE_PRICE_RECOMMENDATIONS`.

**La propietaria gestiona aquí, y es la divergencia consciente** del patrón «la owner ve, el
manager opera» que siguen los demás módulos: `min_price`, `max_price` y `max_daily_change_pct`
son los límites de su propio dinero, y PRD §19 Modo 1 dice literalmente «Manager/owner aprueba
manualmente y actualiza en OTA». Negárselo dejaría a una propietaria sin manager —la escala de
PRD §1— sin poder poner su propio suelo ni aprobar el precio de su propio piso.

`CLEANER` y `TECHNICIAN` no tienen ninguno de los cuatro.

## Lo que este módulo no hace

- **No publica precios en ninguna OTA ni PMS.** Ver Modo 1 arriba.
- **No hay Modo 2 ni Modo 3** de PRD §19 (auto-aplicar con límites, o pricing con IA).
- **No hay variable de entorno que tocar.** El horizonte de 60 días y la ventana de ocupación de
  30 son cifras del PRD, no palancas de operación: cambiarlas cambia lo que el sistema promete,
  y eso se revisa en un Pull Request, no en un `.env`.
- **No hay migración**: las tablas `pricing_rules`, `price_recommendations` y su enum ya venían
  de `domain-foundation-financial`.

## Referencias

- Criterios EARS: `sdd/specs/revenue-pricing.md` (backend y pantalla)
- Contrato HTTP: `backend/openapi.json`
- Calendario de jobs y su lock: [`docs/celery-jobs.md`](celery-jobs.md)
- Regla 9 (excepción 5) y censo de la regla 11: `sdd/steering/security.md`
