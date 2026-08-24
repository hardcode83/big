# Proposal: design-system-tokens

## Why

La identidad visual del producto es hoy un **placeholder declarado por escrito en el
propio código**. `frontend/app/globals.css:3-8`:

> *Base design tokens for the Application Shell and shared states (design D2/D14).
> **Neutral placeholder palette only — no definitive branding or full design system.**
> Foreground/background pairs are chosen to meet WCAG AA contrast. Dark mode follows the
> OS preference; **a future theme change may override it**.*

Y es literalmente neutra: los trece tokens de color son `oklch(L 0 0)` — croma cero, gris
puro. No hay marca, no hay acento, no hay tipografía (la app no carga ninguna fuente) y el
tema oscuro es una `@media (prefers-color-scheme: dark)` que nadie puede vencer.

Existe ya la fuente para cerrarlo: el **export de Stitch del 2026-08-23**
(`docs/design/2026-08-23-stitch-export/`, cuyo `README.md` fija qué es normativo), en el que
`DESIGN.md` es la fuente canónica de tokens — paleta, escala tipográfica, ritmo, radios y
elevación. Este change lo traduce a la capa `@theme` de Tailwind v4.

Es además la entrada de la que dependen `landing-public`, `visual-restyle-workspace` y las
tres entradas de dashboard que salieron del restyle (`needs: design-system-tokens` en las dos
primeras). Nada de eso puede empezar sobre una paleta placeholder.

Análisis previo completo, con las cuatro decisiones ya razonadas:
`sdd/roadmap/design-system-tokens.md`. Fuente de diseño: `docs/design/2026-08-23-stitch-export/DESIGN.md`.

## What changes

Después de este change el frontend tiene **una capa de tokens real y dos temas conmutables**:
`globals.css` deja de declarar una paleta gris bajo una media query y pasa a declarar los
tokens del export —color, tipografía, ritmo, radios, borde— como custom properties expuestas
por `@theme`, definidas en tres bloques (claro por defecto, oscuro por preferencia del
sistema, y ambos vencibles por un atributo en `<html>`). La preferencia del usuario viaja en
la cookie no sensible `autohostai.theme` con tres estados (`light` | `dark` | ausente = seguir
al sistema), se resuelve **en el servidor** en `app/layout.tsx` —el mismo patrón que ya usa el
idioma— y se cambia con un conmutador accesible junto al `LocaleSwitcher`. Inter y JetBrains
Mono entran autohospedadas por `next/font`, nunca por CDN. Y desaparece la última escala cruda
de Tailwind del árbol: las cinco familias de PRD §9.1 —incluido el **gris**, que el export no
define— pasan a tokens semánticos en `lib/ui/status-tone.ts`, y los dos mapas `SEVERITY_COLOR`
duplicados en `features/incidents/` se unifican ahí con ellas.

**No se toca ninguna pantalla, ni el backend, ni el contrato de API.** Lo que cambia de
aspecto lo hace porque consumía los tokens, no porque se haya editado.

## Requirements

### R1 — La capa de tokens, con los dos temas bajo un selector vencible

**As a** desarrolladora del frontend, **I want** que los tokens del export vivan en `@theme`
con los dos temas declarados bajo un selector de atributo, **so that** cualquier pantalla
pueda pintarse con la identidad del producto y el tema pueda decidirse en tiempo de ejecución
y no solo por el sistema operativo.

Acceptance criteria:

1. THE SYSTEM SHALL declarar cada token de color de `DESIGN.md` como custom property CSS y
   exponerlo a Tailwind mediante `@theme`, sin reintroducir un fichero `tailwind.config.js`
   ni `tailwind.config.ts` (su ausencia es una decisión de `frontend-foundation`:
   `components.json` lleva `"tailwind": {"config": ""}` a propósito).
2. THE SYSTEM SHALL definir el conjunto **completo** de tokens semánticos en los dos temas:
   ningún token que exista en un tema falta en el otro.
3. WHERE no hay valor de tema persistido, THE SYSTEM SHALL aplicar el tema claro por defecto
   y el oscuro cuando `prefers-color-scheme: dark`.
4. WHEN el atributo de tema está presente en el elemento raíz, THE SYSTEM SHALL respetarlo
   **en las dos direcciones**, venciendo a `prefers-color-scheme` tanto para forzar claro
   sobre un sistema oscuro como oscuro sobre un sistema claro.
5. THE SYSTEM SHALL hacer que el color de cualquier superficie, texto o borde de la aplicación
   dependa del tema resuelto y no de la media query directamente; ningún consumidor necesita
   una variante `dark:` para expresar su color.
6. IF un par fondo/texto de cualquiera de los dos temas no alcanza el contraste WCAG 2.2 AA
   (4.5:1 texto normal, 3:1 texto grande y elementos de interfaz), THEN THE SYSTEM SHALL
   corregirlo antes de darse por entregado, y la comprobación SHALL quedar registrada con su
   ratio medido por par.

### R2 — La paleta clara, autorizada y no calculada

**As a** Jose (propietario del diseño), **I want** que la paleta clara sea una decisión
aprobada explícitamente y no una inversión mecánica de la oscura, **so that** el tema claro
tenga carácter propio en vez de ser una versión desvaída del oscuro.

El export **es solo oscuro**: sus ~60 tokens describen una sola cosa («Midnight Technical»,
fondos de `#0a0e17` a `#353943`, teal sobre ellos) y las seis maquetas llevan
`<html class="dark">` fijo. Invertir luminancias token a token da una paleta válida en
contraste y muerta en carácter, porque la identidad del diseño *es* la oscuridad.

Acceptance criteria:

1. THE SYSTEM SHALL derivar sus valores de tema claro de una paleta **escrita y aprobada en
   `design.md`** antes de implementarse, no de una transformación automática de los valores
   oscuros.
2. WHERE el export ya contiene valores pensados para fondo claro, THE SYSTEM SHALL usarlos
   como semilla declarada de la propuesta —`inverse-primary` `#006b5f`, `inverse-surface`
   `#dfe2ef`, `inverse-on-surface` `#2c303a`, la familia `on-*-fixed`, y el `#00897b` que la
   maqueta de landing de escritorio usa 20 veces como teal sólido con texto blanco— citando
   para cada token de qué valor del export sale o que es nuevo.
3. IF la paleta clara no queda aprobada, THEN THE SYSTEM SHALL detenerse en la fase de diseño
   y registrar el bloqueo, en vez de inventar valores (alcance alternativo honesto: entregar
   el oscuro y llevar el claro a su propia entrada de roadmap).
4. THE SYSTEM SHALL resolver, y dejar escrito, cuál es el token primario canónico de cada
   tema: `DESIGN.md` se contradice a sí mismo —su frontmatter declara `primary: '#70d8c8'`
   mientras su prosa dice «Primary: A signature Teal (#00897b)»— y las maquetas usan los dos
   (las de espacio de trabajo tiran de `#70d8c8`, la landing de escritorio de `#00897b`).

### R3 — El conmutador: tres estados, cookie, resuelto en el servidor

**As a** usuaria de la aplicación, **I want** poder elegir tema claro u oscuro y también
volver a seguir a mi sistema, **so that** la aplicación se vea como quiero sin depender de la
configuración del sistema operativo y sin parpadear al cargar.

Acceptance criteria:

1. THE SYSTEM SHALL persistir la preferencia en una cookie no sensible `autohostai.theme` con
   los valores `light` y `dark`, siendo la **ausencia** de cookie el tercer estado «seguir al
   sistema»; el nombre SHALL declararse junto a `LOCALE_COOKIE` en `lib/config/constants.ts`
   y la cookie SHALL llevar la misma postura que la de idioma (`path=/`, `samesite=lax`, sin
   dato personal).
2. WHEN se sirve una petición, THE SYSTEM SHALL resolver el tema en el servidor y pintar el
   atributo correspondiente en `<html>` desde `app/layout.tsx`, junto al `lang` que ya se
   resuelve así, de modo que el primer pintado ya sea el tema correcto.
3. THE SYSTEM SHALL NOT guardar el tema en Zustand ni en ningún store de cliente, ni leerlo
   solo en el cliente: el store se hidrata después del primer pintado y la página parpadearía
   del tema equivocado al bueno en cada carga.
4. WHEN la usuaria selecciona un tema, THE SYSTEM SHALL aplicarlo inmediatamente sin recargar
   la página y escribir la cookie, sin que la mutación ocurra durante el render.
5. THE SYSTEM SHALL ofrecer el control como un grupo accesible con nombre traducido: rótulos
   en `locales/es/` y `locales/en/`, nada hardcodeado, estado activo comunicado por
   `aria-pressed`, y área táctil ≥44×44 px.
6. WHEN la usuaria elige «seguir al sistema», THE SYSTEM SHALL borrar la cookie y volver a
   obedecer `prefers-color-scheme`.
7. WHILE se navega entre rutas, THE SYSTEM SHALL conservar el tema resuelto sin destello de
   tema incorrecto.

### R4 — Tipografía: Inter y JetBrains Mono, autohospedadas

**As a** responsable de la app, **I want** las dos familias del export servidas por la propia
aplicación con su escala tipográfica en `@theme`, **so that** el texto tenga la voz del diseño
sin meter un tercero en el camino crítico de una app que sirve datos de tenant.

Acceptance criteria:

1. THE SYSTEM SHALL cargar Inter y JetBrains Mono a través de `next/font` (autohospedadas), y
   SHALL NOT cargar ninguna fuente desde `fonts.googleapis.com` ni desde ningún otro CDN.
2. THE SYSTEM SHALL exponer las dos familias como tokens de `@theme` (interfaz y monoespaciada
   de datos), con una pila de reserva del sistema declarada para cada una.
3. THE SYSTEM SHALL declarar los diez roles tipográficos de `DESIGN.md` —`display-2xl`,
   `display-xl`, `display-lg-mobile`, `headline-lg`, `headline-md`, `body-lg`, `body-medium`,
   `body-base`, `data-mono`, `label-caps`— con su tamaño, peso, interlineado y tracking.
4. WHERE se presenta una métrica o un dato numérico, THE SYSTEM SHALL disponer del rol
   monoespaciado (`data-mono`) como token, sin que este change lo aplique a ninguna pantalla.

### R5 — Ritmo, radios y borde: la geometría del export

**As a** desarrolladora del frontend, **I want** el ritmo de espaciado, los radios y el borde
del export disponibles como tokens, **so that** el restyle de pantallas no tenga que inventar
valores ni reintroducir números sueltos.

Acceptance criteria:

1. THE SYSTEM SHALL declarar en `@theme` la escala de espaciado de `DESIGN.md` sobre su unidad
   base de 4 px (`xs`…`4xl`, gutter y márgenes de móvil y escritorio) y la escala de radios,
   reemplazando el único `--radius` actual sin dejar sin valor a los `--radius-sm/md/lg` que
   hoy se derivan de él. THE SYSTEM SHALL NOT declarar un token de radio para un valor que
   Tailwind ya entrega, porque sería un token sin consumidor (design D2): eso excluye
   `DEFAULT` y `full`, y deja la escala en `sm`, `md`, `lg`, `xl`.

   > **Enmienda de 2026-08-24** (`/sdd:run`, panel de la sección 3, DESIGN-CONFLICT del
   > architect; aprobada por Jose). Este criterio enumeraba los seis pasos del export
   > —`sm`, base, `md`, `lg`, `xl`, `full`— y `full` no es implementable como token: compilando
   > Tailwind v4 se comprueba que `rounded-full` emite `border-radius: calc(infinity * 1px)` y
   > **no lee `var(--radius-full)`**, así que el token no puede alcanzar a la utilidad; y no hay
   > en todo `frontend/` una sola referencia a `rounded-full`, a `var(--radius-full)` ni a la
   > forma arbitraria `rounded-(--radius-full)`. Declararlo era exactamente el antipatrón que D2
   > rechaza por escrito («declarar los 56 nombres × 2 temas fabricaría más de treinta tokens
   > sin consumidor»).
   >
   > La enmienda no pierde nada del diseño: `calc(infinity * 1px)` redondea la esquina por
   > completo, que es lo que el `9999px` del export quiere decir. Y es **el mismo razonamiento
   > que ya se había aceptado para `DEFAULT`** —cuyo `0.25rem` coincide con el `rounded` desnudo
   > y por eso tampoco se declara—, así que tratar los dos igual es lo que hace la regla
   > coherente en vez de una excepción. De ahí la segunda frase del criterio, que generaliza el
   > caso en vez de listar dos excepciones.
2. THE SYSTEM SHALL declarar el borde de 1 px del export como token de color de borde,
   coherente en los dos temas.
3. THE SYSTEM SHALL conservar intactas las utilidades y garantías que ya existen en
   `globals.css`: `tap-target` (44×44 px), `pb-safe`, el indicador de foco visible y el bloque
   `prefers-reduced-motion: reduce` que desactiva animaciones y transiciones.

### R6 — Cero escalas crudas: el gris de §9.1 y los dos mapas de severidad

**As a** mantenedora del frontend, **I want** que ningún componente referencie una escala
cruda de Tailwind para color, **so that** el resultado sea comprobable con un grep en vez de
«se ve bien», y no quede el árbol a medias con unos componentes en tokens nuevos y otros en la
paleta neutra.

Hoy hay 68 usos de escalas crudas en 4 ficheros, y dos de ellos incumplen un `SHALL` vivo.
`sdd/specs/frontend-foundation.md:38` dice: *«THE SYSTEM SHALL keep the badge colour palette
in exactly one place (`lib/ui/status-tone.ts`) and SHALL NOT let a feature restate the
Tailwind classes»*, y sin embargo `features/incidents/components/detail/incident-detail-sections.tsx:8-11`
y `features/incidents/components/list/incidents-view.tsx:13-16` llevan cada uno su propio
`SEVERITY_COLOR` byte a byte idéntico. Peor: **sin ninguna variante `dark:`**, así que hoy esos
badges pintan `bg-gray-100` con `text-gray-700` sobre una página oscura.

Acceptance criteria:

1. THE SYSTEM SHALL definir un token para la familia **gris** de PRD §9.1
   (`BLOCKED_BY_OWNER`, `OUT_OF_SERVICE`), que `DESIGN.md` no define aunque sí define las otras
   cuatro (`state-success` `#10B981`, `state-warning` `#F59E0B`, `state-error` `#EF4444`,
   `state-info` `#38BDF8`).
2. THE SYSTEM SHALL llevar las cinco entradas de `TONE_BADGE_CLASS` al mismo régimen de tokens
   semánticos en que hoy ya está `gray`, sin cambiar qué tono corresponde a qué estado.
3. WHEN un estado operacional no está mapeado, THE SYSTEM SHALL seguir pintándolo con el tono
   gris (`stateColorGroup` mantiene su fallback `?? "gray"`), en los dos temas.
4. THE SYSTEM SHALL unificar los dos mapas `SEVERITY_COLOR` de `features/incidents/` en la
   única tabla de `lib/ui/`, sobre tokens, cumpliendo el `SHALL` de
   `frontend-foundation.md:38`; reutilizar un tono no fusiona vocabularios: la severidad de
   incidencia y los estados de PRD §9.1 significan cosas distintas y solo comparten paleta.
5. WHEN se pinta un badge de severidad con el tema oscuro activo, THE SYSTEM SHALL usar un par
   fondo/texto legible, cerrando el defecto actual.
6. THE SYSTEM SHALL dejar el árbol de `frontend/` sin ninguna referencia a una escala numérica
   de color de Tailwind (`bg-*-100`, `text-*-800`, `dark:bg-*-950`…) en código no de test para
   color de superficie, texto o borde, y esto SHALL ser verificable con un grep cuyo resultado
   quede registrado.
7. THE SYSTEM SHALL actualizar los tests que asertan sobre las clases antiguas
   —`components/property-state-badge.test.tsx` contiene 13 referencias `dark:` y 24 escalas
   crudas—, y la suite de `frontend-ci` (vitest + eslint + `tsc --noEmit`) SHALL quedar en
   verde. A diferencia de la extracción D22 de `pricing-web`, aceptada porque no requería
   editar ningún test, este change **sí** los edita: es coste asumido, no un descuido.

## Out of scope

- **Cualquier pantalla.** Este change toca tokens, `globals.css`, las primitivas de
  `components/ui/` (badge, button, separator, sheet, skeleton, tooltip) y las tablas de tono.
  Si al aplicarlo se ve una pantalla rara, el arreglo es de `visual-restyle-workspace`.
- **Glassmorphism, glows y transiciones de hover.** El export los especifica
  (`backdrop-blur(12px)` sobre superficies al 60-80 %, glows teal a `rgba(0,137,123,0.2)`,
  `translateY(-1px)` en botón primario) y son propiedades de componente, no tokens: van con las
  pantallas, en `visual-restyle-workspace`. Restricción que arrastran: `prefers-reduced-motion:
  reduce` desactiva transiciones, así que ninguna de ellas puede ser la que comunica un estado.
- **Re-mapear iconos a lucide.** El export usa Material Symbols Outlined; el proyecto usa
  lucide con `NavigationIconName` como unión cerrada de 17 nombres resuelta por `icon-map.ts`.
  El re-mapeo es por pantalla y va con ellas; **ningún nombre se añade a esa unión sin una ruta
  que lo use**.
- **La landing pública** (`landing-public`), **el restyle de las pantallas entregadas**
  (`visual-restyle-workspace`) y los tres agregados de dashboard
  (`dashboard-operational-kpis`, `dashboard-occupancy-series`, `dashboard-activity-feed`):
  entradas propias, todas con `needs: design-system-tokens`.
- **Reducir el sidebar de 13 destinos a 6** y **la rejilla con foto de `/properties`**:
  rechazados con motivo escrito en `sdd/roadmap/visual-restyle-workspace.md` D2/D3.
- **Los artefactos del export**: `PropManage AI` como título, `© 2024`, el footer repetido ×4,
  el `<html class="dark">` fijo, las cifras de relleno («500+ propiedades», «99 % satisfacción»).
  Son de las maquetas, no del sistema de diseño; aquí no se copian, así que no se «arreglan».
- **Los datos y features que las maquetas insinúan** (buscador global de la topbar, foto de
  cabecera por propiedad, ★4.9, ingresos MTD): la regla del export es *«se toma el diseño, no
  los datos ni las features»*, y el censo de lo descartado está en
  `docs/design/2026-08-23-stitch-export/README.md`.
- **Backend, contrato de API y regeneración de tipos**: nada de esto cambia.

## Affected specs

- `sdd/specs/design-system-tokens.md` — *(no existe aún — se creará al archivar)*: la capa de
  tokens, los dos temas, el mecanismo de conmutación por cookie y la carga de fuentes.
- `sdd/specs/frontend-foundation.md` — se modifica: la paleta placeholder y el «dark mode
  follows the OS preference» dejan de describir el sistema; la nota de línea 38 sobre la tabla
  única de tonos se amplía con la severidad de incidencias, y las primitivas de
  `components/ui/` pasan a describirse sobre tokens de marca.

## Notas de fase

- **Decisión ya tomada (Jose, 2026-08-23)**: se ofrecen los dos temas con conmutador explícito
  — no solo el oscuro del export.
- **Decisión de esta sesión (2026-08-23)**: la paleta clara se propone en `/sdd:design` para
  aprobación (R2), y los dos mapas `SEVERITY_COLOR` de `features/incidents/` entran en el
  alcance (R6).
- **Para `/sdd:design`**, cuestiones abiertas que este proposal deja planteadas y no resuelve:
  los valores concretos del tema claro (R2.1), el token primario canónico por tema (R2.4), la
  forma exacta del bloque CSS de tres estados y de la variante `dark` de Tailwind v4 (R1.4-R1.5),
  y si el conmutador merece una dependencia externa o repite el patrón de `LocaleSwitcher`
  —que escribe la cookie en un efecto y muta `document.documentElement` (R3.4), sin librería.
