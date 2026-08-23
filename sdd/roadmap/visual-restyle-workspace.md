# visual-restyle-workspace

[FE] **aplicar los tokens de `design-system-tokens` a las pantallas ya entregadas**, y
nada más. Ni arquitectura de información, ni datos nuevos, ni endpoints. Diseño de
referencia en `docs/design/2026-08-23-stitch-export/`.

Esta entrada existe separada de `design-system-tokens` por una razón medible: aquella
cambia tokens y primitivas y no entrega pantalla; esta las repinta todas y no cambia ni un
token. Juntas serían un change de radio enorme donde un fallo visual no se sabe si es del
token o del consumidor.

## La regla que gobierna esta entrada

**Del export se toma el diseño — tokens, composición, estilo —, no los datos ni las
features que las maquetas insinúan** (Jose, 2026-08-23). Una maqueta no escribe el
backlog.

Es la regla operativa de este change y no una frase de intención, porque las maquetas
insinúan mucho: un buscador global, fotos de propiedad, una rejilla de cartera,
valoraciones en estrellas, ingresos del mes. Nada de eso entra aquí **y casi nada se
registró como entrada de roadmap**; el censo completo de qué se aprovechó, qué se descartó
y por qué está en `docs/design/2026-08-23-stitch-export/README.md`.

De ahí sale el criterio con el que se resuelve cualquier duda que aparezca implementando:
si la maqueta enseña un dato que el DTO no tiene, **gana el DTO** y la maqueta se adapta.
Nunca al revés, y nunca «lo dejo pendiente de un endpoint».

## Qué pantallas entran

Las 13 rutas de workspace del registro (`features/shell/navigation/route-registry.ts`),
más los tres shells de campo y el portal del huésped. Todas están entregadas y archivadas:
`dashboard-web`, `properties-web`, `reservations-web`, `incidents-web`, `timeline-web`,
`cleaning-manager-view`, `pricing-web`, `guest-portal-web`, `frontend-auth-session`, más
los andamios de `/cleaner` y `/tech`. **Nada aquí es capability nueva.**

## Decisión 1: `reservas_executive_emerald_style` es la implementación de referencia

De las seis maquetas del export es la única hecha **sobre la pantalla real**, y se
demuestra: reproduce el badge de build `0.1.0+2026-08-22.26c37c0` con su enlace «Build
provenance» —que es un artefacto de `app-version-provenance`, no algo que un diseñador
invente—, el conmutador ES/EN, el set exacto de filtros (`Status` / `Check-in` /
`Check-out` / `Clear filters`) y las seis columnas literales de `reservations-web`
(Guest, Property, Stay, Status, Channel, Amount) con su paginación Previous/Next.

Por eso es la referencia: es la única que demuestra que **el diseño cabe en la pantalla
real sin negociar el contrato**. Se implementa primero y las demás la imitan.

**Y de paso documenta dos defectos actuales que no son de diseño.** La maqueta los copió
porque están en la pantalla:

1. La columna **Property** pinta un UUID pelado (`981b5c2e-11a4-401b-8459-a97d88b2c14e`),
   no un nombre de vivienda.
2. La columna **Amount** pinta `EUR` sin cifra en tres de las cuatro filas.

Ninguno de los dos se arregla aquí —esto es un restyle y arreglarlos toca datos—, pero
tampoco se dejan sin registrar: al abrir el `/sdd:new` de esta entrada hay que comprobar si
son bugs vivos o artefactos del seed, y si son vivos, sacarlos a su entrada. Un restyle que
repinta un UUID más bonito no ha mejorado nada.

## Decisión 2: la reducción del sidebar a 6 ítems se RECHAZA

La maqueta dibuja un sidebar plano de seis: `Dashboard · Propiedades · Reservas ·
Analítica · Configuración · Ayuda`. El shell real tiene **13 destinos de workspace en
cuatro grupos** (`operation` / `work` / `revenue` / `administration`), todos de PRD §24.

Adoptar el sidebar de la maqueta significaría **quitar del menú ocho pantallas
entregadas**: timeline, cleaning, incidents, conversations, approvals, pricing, statements
y reviews. Y añadir dos que no existen: «Analítica» y «Ayuda» no están en PRD §24, ni en
`route-registry.ts`, ni tienen ruta, ni claves i18n.

**Eso no es una propuesta de diseño, es que la maqueta no sabía que esas pantallas
existen.** Stitch dibujó un sidebar plausible de seis ítems porque es lo que cabe bien en
un pantallazo. Se rechaza, y queda escrito para que nadie lo reabra como «pero el diseño
decía».

Lo que **sí** se conserva de ese sidebar, porque es mejor que lo que hay y no cuesta IA:
el bloque de marca con «Panel de Control» como bajada, la CTA primaria destacada arriba y
el ítem de ayuda anclado abajo son composición, no navegación. Si Jose quiere de verdad un
nav más plano, es su propia entrada con su propio análisis de qué se agrupa — no un efecto
colateral de un restyle.

## Decisión 3: `/properties` se repinta como tabla; la rejilla con foto NO entra

`propiedades_executive_emerald_style` es la maqueta de menor fidelidad del export y hay que
tratarla como lo que es. Su contenido no es de AutoHostAI: **Villa Azure** en *Marina
District, Nyc* y **Pine Crest Retreat** en *Aspen, CO*, importes en dólares (`$4,250`,
`$8,100`), valoraciones `★4.9` / `★4.7`, `OCUPACIÓN 85%`, `INGRESOS MTD` y una foto de
cabecera por vivienda. Es el relleno genérico de alquiler vacacional de Stitch.

Contra el contrato: `features/properties/data/dto.ts` (`PropertySummaryDto`) **no tiene
ninguno** de esos campos — ni imagen, ni ocupación, ni ingresos, ni valoración. Y la
pantalla entregada es una **tabla de seis columnas** (`Propiedad · Código · Ciudad ·
Capacidad · Estado · Situación`, con tarjetas por fila en móvil desde `properties-view.tsx`).
Solapamiento real entre maqueta y pantalla: **nombre y ciudad**.

Así que aquí `/properties` recibe tokens sobre la tabla que ya tiene, y punto.

**La rejilla de tarjetas con foto no se registra como entrada.** Es otra pantalla, no un
restyle, y para existir necesitaría cuatro cosas que no existen: fotos de propiedad
(dominio nuevo), ocupación por vivienda, ingresos del mes —que ya tiene dueño natural en
`revenue-statements`— y valoraciones —que ya lo tiene en `revenue-reviews`—. Bookear una
pantalla nueva más tres capabilities porque una maqueta de relleno las dibujó es
exactamente lo que la regla de cabecera prohíbe. Si algún día se quiere esa vista, se
justifica por producto y no por este export; queda censada en el README del export para
que la decisión sea recuperable.

Lo que **sí** se aprovecha de esa maqueta, porque es diseño y no datos: la jerarquía
tipográfica del encabezado de página, el tratamiento de las píldoras de estado sobre la
imagen y el patrón de «dato con etiqueta en versalitas + valor en mono» de sus dos
recuadros. Eso se puede llevar a las celdas de la tabla y a las tarjetas de fila del móvil
sin inventar ni un campo.

## Decisión 4: los cuatro bloques agregados del dashboard NO entran

Por decisión de Jose (2026-08-23): lo que no tiene backend no entra en un restyle. La
maqueta del dashboard añade sobre las property cards reales cuatro bloques que **no tienen
endpoint**:

| Bloque de la maqueta | Endpoint que necesitaría | Destino |
|---|---|---|
| 3 tarjetas KPI (Limpiezas Hoy 24 · Check-ins Próximos 18 · Incidencias Abiertas 5, «2 Urgentes») | conteos a nivel de tenant | entrada `dashboard-operational-kpis` |
| Gráfico «Ocupación Semanal» (L–D) | serie temporal de ocupación | entrada `dashboard-occupancy-series` |
| Feed «Actividad Reciente» | timeline a nivel de tenant | entrada `dashboard-activity-feed` |
| Buscador «Buscar reservas, propiedades» | búsqueda | **no registrado** — feature nueva de tamaño L que PRD §24 no pide |

Las tres primeras son entradas por pedido explícito de Jose; el buscador no, y la
diferencia es deliberada. Las tres cuentan datos que el sistema **ya tiene** y no muestra
—limpiezas, check-ins, incidencias, eventos de timeline—, así que son lecturas nuevas de
un dominio entregado. El buscador es una capability nueva de pleno derecho, y que apareciera
en una topbar de Stitch no es una razón para bookearla.

Ninguna de las tres trae consigo su mitad de pantalla: cuando existan, quien las
implemente decide cómo se pintan. Reservar hoy la entrada `[FE]` que las consume sería
comprometer una composición que aún no puede verse contra datos reales.

Medido, no supuesto: `backend/openapi.json` tiene **76 rutas** y de agregados exactamente
tres — `/api/v1/dashboard/properties`, `/api/v1/properties/{property_id}/dashboard` y
`/api/v1/timeline/{property_id}`. Ninguna sirve un conteo de tenant, ninguna una serie, y
no hay ruta de búsqueda.

Un detalle que confirma que las cifras son relleno y no un requisito: con **dos** viviendas
no puede haber 24 limpiezas hoy ni 18 check-ins próximos. Quien implemente esto no debe
tomar esos números como el orden de magnitud a diseñar.

**Lo que sí entra del dashboard**: las property cards, que son la pantalla de verdad. La
maqueta las compone bien y con datos reales de seed (PAJARITOS8, REDES11, María García,
`BOOKING #SEED-B…`, fechas de agosto de 2026), pinta los campos de PRD §9.1 que el DTO
tiene —estado, incidencias abiertas, próxima acción con responsable, reserva, huésped,
fechas— y **respeta los tonos de §9.1**: ámbar en `Cleaning scheduled`, azul en
`Cleaning in progress`. Eso se implementa tal cual.

## Decisión 5: los efectos del export son de componente, y tienen un techo

`DESIGN.md` especifica glassmorphism (`backdrop-blur(12px)` sobre superficies al 60-80 %),
glows teal difusos (`rgba(0,137,123,0.2)`), gradientes de borde superior que aparecen en
hover, y `translateY(-1px)` en el botón primario. Nada de eso existe hoy y todo es de esta
entrada, no de `design-system-tokens`.

Con dos restricciones que ya están escritas en el árbol y no son negociables:

- `globals.css:84-93` anula animaciones y transiciones bajo `prefers-reduced-motion:
  reduce`. Así que **ninguna transición puede ser el único portador de un estado**: si el
  borde-gradiente de hover es lo que indica que una tarjeta es pulsable, para quien pidió
  menos movimiento la tarjeta deja de parecer pulsable.
- `globals.css:78-81` y la utilidad `tap-target` (44×44 px) vienen de la decisión D14 de
  `frontend-foundation` y del hecho de producto de que *«la propietaria opera desde el
  móvil»*. Un rediseño no puede reducir un objetivo táctil por debajo de eso.

## Fuera de alcance, explícito

- Los artefactos del export: `<title>Dashboard - PropManage AI</title>`, `© 2024`, footer
  duplicado ×4. No se portan, así que no se «arreglan».
- Los dos defectos de datos de `/reservations` (UUID en Property, `EUR` sin cifra): se
  investigan y se sacan a entrada propia si están vivos, pero no se arreglan aquí.
- El shell de campo (`/cleaner`, `/tech`) y el portal del huésped: reciben los tokens como
  todo lo demás, pero el export **no trae maqueta** de ninguno de los tres. Su restyle es
  aplicar tokens sin diseño de referencia, y eso hay que decirlo en su design en vez de
  improvisar una identidad para tres superficies que nadie diseñó.

## Riesgo principal

El mismo que su dependencia, un nivel más arriba: es un change con muchísimo diff y
ninguna capability nueva, donde la tentación de «ya que estoy» es máxima —arreglar un
UUID, añadir una columna, mover un ítem de menú—. Cada una de esas es una entrada de
roadmap ya escrita. El criterio de terminado de este change es que **ningún test de
comportamiento haya necesitado edición**: si un test de `features/*` hubo que cambiarlo, se
cambió comportamiento, y eso ya no era un restyle.
