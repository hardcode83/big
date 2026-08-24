# Design: design-system-tokens

## Context

`frontend/app/globals.css` es hoy 13 tokens de color `oklch(L 0 0)` —croma cero— en `:root`,
redeclarados dentro de un `@media (prefers-color-scheme: dark)` que **no se puede vencer**, más
un `@theme inline` que los expone a Tailwind v4, un `@layer base`, el bloque
`prefers-reduced-motion` y las utilidades `tap-target` / `pb-safe`. No hay fichero
`tailwind.config` (decisión de `frontend-foundation`: `components.json` lleva
`"tailwind": {"config": ""}`), no se carga ninguna fuente (`app/layout.tsx` no usa `next/font`)
y no existe token de tipografía, ritmo ni radio más allá de un único `--radius: 0.5rem`.

El idioma ya resuelve por cookie en servidor: `lib/config/constants.ts:15` declara
`LOCALE_COOKIE`, `lib/i18n/server.ts` lo lee con `cookies()` y `app/layout.tsx` pinta
`<html lang={locale}>`. `features/shell/components/locale-switcher.tsx` es el conmutador —
cliente, muta en `useEffect`, escribe la cookie y `document.documentElement.lang`, sin Zustand.
`Topbar` (Server Component) lo monta por defecto en su slot `end`, y **los cinco shells**
(`public`, `workspace`, `cleaner`, `technician`, `guest`) renderizan `Topbar`, así que lo que
entre ahí aparece en toda la app sin tocar ninguna pantalla.

El color crudo está medido: **68 usos de escalas numéricas de Tailwind en exactamente 4
ficheros** —`lib/ui/status-tone.ts` (24), `components/property-state-badge.test.tsx` (24) y los
dos `SEVERITY_COLOR` de `features/incidents/` (10 cada uno)— y **25 apariciones de `dark:`**,
todas en los dos primeros. Los dos `SEVERITY_COLOR` son byte a byte idénticos, incumplen
`sdd/specs/frontend-foundation.md:38` y no llevan variante `dark:`, así que hoy pintan
`bg-gray-100 text-gray-700` sobre página oscura. `components/property-state-badge.test.tsx` es
el **único** test que fija cadenas de clase exactas; `features/pricing/lib/recommendation-status.test.ts`
solo comprueba que la clave existe en `TONE_BADGE_CLASS`, y `features/cleaning` la reexporta.

Fuente canónica de valores: `docs/design/2026-08-23-stitch-export/DESIGN.md` (56 tokens de
color, 10 roles tipográficos, 6 radios, 11 pasos de ritmo). Es **solo oscuro**.

## Decisiones

### D1 — Los tres bloques: claro en `:root`, oscuro dos veces, y un test de paridad que lo vigila

**Elegido:** el patrón de tres bloques con selector de atributo, en este orden exacto:

```css
:root                       { color-scheme: light dark; /* … tokens claros … */ }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { /* … tokens oscuros … */ }
}
:root[data-theme="dark"]    { /* … tokens oscuros, otra vez … */ }
:root[data-theme="light"]   { color-scheme: light; }
:root[data-theme="dark"]    { color-scheme: dark; }
```

Las dos primeras reglas y la tercera tienen **la misma especificidad** —`:root` es una
pseudoclase (0,1,0) y `[data-theme]` un atributo (0,1,0), así que `:root[data-theme="dark"]` y
`:root:not([data-theme="light"])` empatan en (0,2,0)—, de modo que **el orden del fichero es lo
que decide** y el bloque del atributo tiene que ir después de la media query. Con esto R1.4 sale
en las dos direcciones sin `!important`: `data-theme="light"` sobre sistema oscuro excluye la
media query por el `:not(...)` y deja ganar a `:root`; `data-theme="dark"` sobre sistema claro
gana por orden. El `color-scheme` acompaña para que los controles nativos, la barra de scroll y
el fondo del propio navegador sigan al tema resuelto.

El precio es que los valores oscuros se escriben **dos veces**, y ese es exactamente el riesgo
que el roadmap nombra («quedarse a medias»). Se paga con un test —`app/globals.tokens.test.ts`—
que parsea `globals.css`, extrae los tres bloques y afirma que (a) declaran **el mismo conjunto
de nombres** de token y (b) los dos bloques oscuros declaran **valores idénticos**. Eso convierte
R1.2 en una comprobación de CI en vez de una promesa, y hace la duplicación segura en lugar de
frágil.

Rechazado: **`light-dark(claro, oscuro)`** — una sola declaración por token y sin duplicación,
pero su suelo de navegador (Chrome 123 / Safari 17.5 / Firefox 120) está **por encima del target
por defecto de Next 16**, así que un Safari 17.0-17.4 recibiría el token *inválido* y por tanto
sin valor; y su anidamiento dentro del `color-mix(in oklab, …)` que Tailwind v4 genera para los
modificadores de opacidad (`bg-surface/60`) —que es justo lo que `visual-restyle-workspace`
necesita para el glassmorphism— no está verificado aquí.
Rechazado: **`@media` + clase `.dark` estilo shadcn** — obliga a una clase en `<html>` y a un
script inline anti-parpadeo; la cookie leída en servidor (D4) hace ambos innecesarios.
Rechazado: **el «space toggle» de custom properties** (`--dark: initial`) — elimina la
duplicación, pero es ilegible y ningún test lo salvaría de eso.

### D2 — El subconjunto de tokens: 25 nombres, no los 56 del export

**Elegido:** se declaran **25 tokens de color** —15 de núcleo y 10 de estado— y de los **56**
que trae el frontmatter de `DESIGN.md` (contados) el resto se usa como **semilla** de valores, no
como token propio. El export es un volcado del sistema de Material 3
(`surface-tint`, `*-fixed`, `*-fixed-dim`, `inverse-*`, `tertiary-*`) y declarar los 56 nombres × 2
temas fabricaría más de treinta tokens sin consumidor, cada uno con una fila en la auditoría de contraste de
R1.6 y una posibilidad de deriva en el test de paridad de D1. Menos nombres, todos con dueño.

Y los 13 nombres semánticos que ya existen (`background`, `foreground`, `muted`,
`muted-foreground`, `primary`, `primary-foreground`, `secondary`, `secondary-foreground`,
`accent`, `accent-foreground`, `border`, `input`, `ring`) **se conservan y solo cambian de
valor**: renombrarlos obligaría a editar las seis primitivas de `components/ui/` y todas las
pantallas, que es precisamente lo que este change declara fuera de alcance.

Rechazado: portar los 56 tokens tal cual — trazabilidad total, pero R1.2 y R1.6 tendrían que
cubrir tokens que nada pinta.
Rechazado: renombrar a la nomenclatura M3 del export (`on-surface`, `surface-container-low`) —
alineaba los nombres con la fuente y rompía todo el árbol.

### D3 — La paleta clara: `#006b5f` como primario, porque el `#00897b` del export no llega a AA

**Elegido:** la tabla completa de §«Paleta» de abajo, con esta resolución de R2.4: **el token
primario canónico es `#70d8c8` en oscuro y `#006b5f` en claro.**

`DESIGN.md` se contradice —frontmatter `primary: '#70d8c8'`, prosa «a signature Teal
(#00897b)»— y la contradicción se resuelve al ver que son **dos papeles distintos**, no dos
opiniones: `#70d8c8` viene emparejado con `on-primary: #003731`, es decir es el tono claro que
se lee *sobre* fondo oscuro (papel de «primary» en M3 oscuro); `#00897b` es, según la propia
prosa, el relleno sólido con **texto blanco**, que es el papel de «primary» en un tema claro. Las
maquetas usan los dos y cada una en su sitio (`#70d8c8` en las de espacio de trabajo, `#00897b`
20 veces en la landing de escritorio — contado).

Pero **`#00897b` con texto blanco mide 4.32:1**, y el rótulo de un botón es texto normal
(`text-sm font-medium` = 14 px/500), así que **falla el 4.5:1 de WCAG 2.2 AA**. No es una
objeción teórica: es el botón primario de la prosa de `DESIGN.md`. Y el propio export trae el
hermano que sí cumple: `inverse-primary` `#006b5f`, blanco sobre él **6.43:1**, que es
literalmente el token que M3 reserva para «el primario cuando la superficie es clara». Así que la
corrección que exige R1.6 no inventa nada: usa el valor que el export ya tenía para este caso.

`#00897b` sobrevive como el ancla del *glow* teal (`rgba(0,137,123,0.2)`) y como color de texto
grande (4.09:1 ≥ 3:1 para ≥24 px bold), los dos de `visual-restyle-workspace` y `landing-public`;
aquí **no se declara token** porque no tendría consumidor — resuelto así en el gate (OQ3).

Rechazado: `#00897b` como primario claro — es el valor que la prosa nombra, y falla AA por 0.18.
Rechazado: `#00897b` con texto `#003731` en vez de blanco — pasa el contraste y contradice la
prosa del export («with white text») además de leerse apagado.
Rechazado: invertir luminancias del oscuro token a token — lo que R2 y el roadmap D1 prohíben
explícitamente: da contraste válido y carácter muerto.

### D4 — El tema se resuelve en servidor por cookie, calcado del idioma

**Elegido:** `THEME_COOKIE = "autohostai.theme"` declarada junto a `LOCALE_COOKIE` en
`lib/config/constants.ts`; `resolveTheme()` isomorfo en `lib/theme/theme.ts` (espejo de
`resolveLocale`, devuelve `Theme | null`); `getServerTheme()` en `lib/theme/server.ts` (espejo de
`getServerLocale`); `app/layout.tsx` pinta `<html lang={locale} data-theme={theme ?? undefined}>`.
`undefined` deja el atributo **ausente**, que es el tercer estado y el que devuelve el mando a la
media query. Tres estados, sin valor `"system"` persistido: la ausencia *es* el estado.

| cookie `autohostai.theme` | `prefers-color-scheme` | atributo en `<html>` | tema pintado |
|---|---|---|---|
| ausente | light | (ninguno) | claro (`:root`) |
| ausente | dark | (ninguno) | oscuro (media query) |
| `light` | light | `data-theme="light"` | claro |
| `light` | dark | `data-theme="light"` | claro (el `:not()` excluye la media query) |
| `dark` | light | `data-theme="dark"` | oscuro (gana por orden) |
| `dark` | dark | `data-theme="dark"` | oscuro |
| basura | cualquiera | (ninguno) | como «ausente» (`resolveTheme` valida) |

Esa tabla es el contenido entero del mecanismo, así que **no se genera diagrama**: una figura
diría lo mismo con menos precisión y costaría contexto leerla.

Rechazado: Zustand — cliente, se hidrata después del primer pintado, parpadeo garantizado (R3.3).
Rechazado: solo `prefers-color-scheme` — es lo que hay hoy y no es un conmutador.
Rechazado: `next-themes` — resuelve en cliente con un script inline anti-FOUC; añade
dependencia y un `<script>` para un problema que el servidor ya no tiene.

### D5 — El conmutador: tres botones junto al de idioma, y `Topbar` pasa a `async`

**Elegido:** `features/shell/components/theme-switcher.tsx`, cliente, tres botones (Claro /
Oscuro / Sistema) en un `role="group"` con `aria-label` traducido y `aria-pressed` sobre la
**preferencia elegida** (no sobre el tema resuelto), mutando en `useEffect` con el mismo patrón
`requested === null` del `LocaleSwitcher`: escribe/borra la cookie y pone/quita
`document.documentElement.dataset.theme`. Elegir «Sistema» borra la cookie (`max-age=0`) y
`delete dataset.theme` (R3.6).

Para que el botón activo sea correcto **en el primer pintado**, `Topbar` pasa a `async` y llama
a `getServerTheme()`, pasando el valor como prop; su slot `end` por defecto se vuelve
`<><ThemeSwitcher …/><LocaleSwitcher /></>`.

> **Corrección de 2026-08-24 (`/sdd:run`, sección 6).** Esta decisión afirmaba que «los cinco
> shells lo heredan **sin cambiar una línea**», y es falso. La decisión —`Topbar` async— se
> sostiene; la consecuencia predicha no. Los cinco shells montaban `Topbar` como **elemento
> JSX** (`topbar={<Topbar start={start} />}`), y un componente async como elemento no lo puede
> resolver el renderizador de cliente: bajo vitest + Testing Library el chrome entero
> desaparecía y 13 tests de shell fallaban con «Unable to find an accessible element with the
> role banner». No era un artefacto de carga ni un test mal escrito — el renderizador de
> cliente genuinamente no puede renderizar un elemento async.
>
> El arreglo es una línea por shell: `topbar={await Topbar({ start })}`. Es además el patrón que
> este repo ya usaba para los Server Components async —los cinco shells se **llaman y se
> esperan**, no se renderizan como elemento—, así que `Topbar` se alinea con ellos en vez de
> ser la excepción. Verificado: 86/86 tests de shell en verde, `typecheck` limpio y
> `next build` compilando.
>
> Lo que esto cuesta y conviene no maquillar: el change toca cinco ficheros que el diseño daba
> por intactos. No es una pantalla —son contenedores de chrome— así que no invade el «no se toca
> ninguna pantalla» del proposal, pero sí amplía la huella en cinco ficheros y había que
> decirlo.

Área táctil: `Button size="sm"` es `h-9` (36 px), por debajo de los 44 exigidos, así que los
botones llevan la utilidad `tap-target` que ya existe en `globals.css` (R3.5, y R5.3 la conserva).
Rótulos nuevos bajo `navigation.themeSwitcher.{label,light,dark,system}` en `locales/es` y
`locales/en`; el test de paridad de catálogos ya vigente los cubre.

Rechazado: un único botón que cicla los tres estados — menos superficie y no hay forma honesta de
comunicar tres estados con un `aria-pressed`.

> **Revisión de forma de 2026-08-24 (`/sdd:run`, pasada visual; decidida por Jose).** Los tres
> botones se mantienen —el rechazo de arriba sigue en pie, un botón que cicla no puede expresar
> tres estados— pero pasan a ser **de icono**: sol, luna y monitor de `lucide-react`, que ya era
> dependencia. Al verlo en el navegador, tres pastillas de texto junto a las dos del idioma leían
> como cinco botones compitiendo en la topbar.
>
> Lo accesible no se pierde, y esto es la parte que importa: el icono va `aria-hidden`, el nombre
> accesible sale del `aria-label` traducido —de modo que un lector de pantalla anuncia exactamente
> lo mismo que con texto— y un tooltip lleva la misma palabra para quien ve, porque un icono solo
> no distingue «claro» de «sistema». `size="icon"` del `Button` ya son 44×44, y se conserva
> `tap-target` para que la garantía de R3.5 no dependa de la primitiva.
>
> Y **el conmutador de idioma pasa a un botón único** que muestra el locale activo y cambia al
> otro, con un separador entre los dos controles. Eso cambia su semántica accesible a propósito:
> dos botones eran un conjunto de opciones, así que `aria-pressed` decía cuál estaba vigente; uno
> solo es una ACCIÓN, donde `aria-pressed` no significaría nada, y el nombre accesible tiene que
> decir qué hará la pulsación («Cambiar idioma a English») y no qué dice el rótulo. Comprobado
> antes de tocarlo que `sdd/specs/frontend-foundation.md:43` exige «an accessible topbar control
> switches ES/EN» — fija el comportamiento, no el número de botones —, así que un control único no
> contradice la spec viva. Su test se reescribió entero, incluida una aserción de que **no** hereda
> `aria-pressed` por copia.
>
> Coste asumido y dicho: toca `locale-switcher.tsx`, que es un componente preexistente fuera de la
> lista de ficheros que este change declaraba. Es la segunda ampliación de huella de la sección
> —la primera fueron los cinco shells— y las dos salieron de mirar el resultado en vez de sólo
> los tests.
Rechazado: leer el tema en cliente al montar en vez de pasarlo desde servidor — el tema no
parpadearía (lo pone el HTML) pero el *botón activo* sí, un tick después de hidratar.

### D6 — Los badges: 10 tokens y modificadores de opacidad, no 15 tokens literales

**Elegido:** cinco anclas de estado y cinco colores de texto —`state-{success,warning,error,info,neutral}`
y `state-*-text`— y cada entrada de `TONE_BADGE_CLASS` pasa a ser **una** cadena sin `dark:`:

```ts
green: "bg-state-success/15 text-state-success-text border-state-success/40",
```

El fondo y el borde se derivan del ancla con los modificadores de opacidad de Tailwind v4
(`color-mix(in oklab, var(--color-state-success) 15%, transparent)`), así que se componen sobre
el fondo del tema que toque y **los dos temas salen del mismo string**. El texto necesita token
propio porque el ancla no basta: medido, `#10B981` sobre su propio tinte al 15% en claro da
2.3:1. Con `state-*-text` las **30** combinaciones (5 tonos × 3 superficies × 2 temas) pasan AA,
entre 5.40 y 10.02 (tabla abajo).

Esto cierra R6.1 (el gris que `DESIGN.md` no define) tomándolo de la familia slate del propio
export —`state-neutral` = `#94A3B8` (`text-secondary`) en oscuro y `#64748B` (`text-muted`) en
claro— en vez de inventar un tono, y cierra R6.5: el defecto actual era la ausencia de `dark:`,
y aquí no hay `dark:` que falte porque el token es el que cambia.

Nota de alcance sobre el borde: en `features/incidents/` los badges son `<span>` **sin
`border`**, así que la clase de color de borde es inerte ahí hasta que `visual-restyle-workspace`
les ponga la primitiva `Badge`. No se les añade ancho de borde aquí — sería cambiar una pantalla.

Rechazado: 15 tokens literales (surface/text/border × 5 tonos) — auditables por inspección
directa, y 30 valores más que mantener en dos temas por una ganancia que el cálculo de
composición ya da.
Rechazado: usar el ancla también como color de texto (`text-state-success`) — habría sido cero
tokens nuevos; falla en claro en los cinco tonos y en rojo también en oscuro (4.29:1). Medido.

### D7 — `SEVERITY_COLOR` se unifica como mapa enum→tono, no como segunda tabla de clases

**Elegido:** `features/incidents/lib/severity-tone.ts` con
`SEVERITY_COLOR_GROUP: Record<IncidentSeverity, Tone>` = `{LOW: "gray", MEDIUM: "blue",
HIGH: "amber", CRITICAL: "red"}` y `severityColorGroup()` con su `?? "gray"`; los dos componentes
pasan a `TONE_BADGE_CLASS[severityColorGroup(s)]`. Los tonos son exactamente los de hoy, así que
no cambia qué severidad es de qué color.

Es la lectura de R6.4 que respeta el patrón vivo y su propia frase («reutilizar un tono no
fusiona vocabularios»): las **cadenas de clase** viven una sola vez en `lib/ui/status-tone.ts`
—que es lo que `frontend-foundation.md:38` exige— y el mapa enum→tono vive con su enum, igual
que `STATE_COLOR_GROUP` en `components/property-state-badge.tsx` y `STATUS_COLOR_GROUP` en
`features/cleaning/lib/task-status.ts`. `IncidentSeverity` viene del OpenAPI generado, así que
el `Record` da exhaustividad en compilación — algo que el `Record<string, string>` de hoy no da.

Rechazado: mover la tabla de severidad entera a `lib/ui/` — cumpliría la letra de R6.4 y metería
en `lib/ui/` el vocabulario de una feature, que es lo que D22 de `pricing-web` evitó.
Rechazado: dejar los dos mapas y solo añadirles `dark:` — arregla el síntoma y deja el
incumplimiento del `SHALL`.

### D8 — Fuentes por `next/font/google`, autohospedadas

**Elegido:** `Inter` y `JetBrains_Mono` desde `next/font/google` en `app/layout.tsx`, con
`subsets: ["latin"]`, `display: "swap"` y `variable: "--font-inter"` / `"--font-jetbrains-mono"`;
las clases van en `<html>` y `@theme inline` mapea `--font-sans` y `--font-mono` a esas variables
con pila de reserva del sistema. `next/font` **descarga los ficheros en tiempo de build y los
sirve desde `/_next/static`**: en runtime no hay ni una petición a `fonts.googleapis.com`, que es
lo que R4.1 pide.

Lo que sí introduce es una **dependencia de red en `npm run build`**, y el fallo sería ruidoso
(build roto), no silencioso — `next build`, al contrario que `next dev`, trata el fallo de
descarga de `next/font/google` como fatal.

> **Corrección de 2026-08-24 (`/sdd:run`, panel de la sección 3, revisor cicd).** Esta decisión
> decía «la etapa `builder` del `frontend/devops/Dockerfile` y el job «Production build» de
> `.github/workflows/frontend-tests.yml`. Los dos tienen red». Dos inexactitudes, ambas
> comprobadas contra los ficheros:
> 1. **No existe ningún job llamado «Production build».** Es un *paso* —«Production build and
>    public artifact disclosure gate»— dentro del job `provenance-contract`
>    (`frontend-tests.yml:53`, con `npm run build` en la 61). El job `frontend-tests` no
>    construye nunca. Quien buscara ese job miraría el equivocado.
> 2. **Son tres sitios, no dos.** Falta el job `build-frontend` de
>    `.github/workflows/deploy-dev.yml:101`, que construye la imagen vía
>    `docker/build-push-action` con `target: prod` y por tanto atraviesa `builder`.
>
> Lo sustantivo se sostiene y queda además cerrado el peor caso que se temía: los tres corren en
> `ubuntu-latest` (GitHub-hosted) con red y sin `--network=none` ni bandera offline, y **el
> runner self-hosted de la VM de dev no construye el frontend** — su job `deploy`
> (`deploy-dev.yml:149`, `runs-on: [self-hosted, dev]`) sólo hace `docker compose pull` desde
> GHCR, así que la descarga de fuentes no ocurre ahí y no hace falta salida HTTPS a
> `fonts.gstatic.com` en la VM. Tampoco hay `cache-from`/`cache-to` ni `actions/cache` en
> ninguno de los workflows, así que no hay riesgo de que la descarga quede cacheada y rancia.

**`subsets: ["latin"]` no restringe lo que se emite**, medido el 2026-08-24 sobre el build real:
la salida trae 13 ficheros `.woff2` con bloques `unicode-range` de cirílico, griego y vietnamita
además del latino. Cuesta **tamaño de imagen, no bytes de runtime**, porque `unicode-range` es lo
que decide si el navegador descarga la cara. Se deja como está: recortarlo de verdad exige
`next/font/local` con los ejes curados a mano, que es la alternativa rechazada abajo.

**Riesgo de cadena de suministro, aceptado con su condición de salida escrita.** La etapa `deps`
corre `npm ci` contra `package-lock.json`, que lleva un hash `sha512` por paquete; los binarios
de fuente son **el único insumo de build sin entrada de lockfile, sin checksum y sin SRI** — 13
ficheros de un tercero que después se sirven desde nuestro origen. Se acepta porque explotarlo
exige comprometer la infraestructura de Google o la confianza TLS del host de build, y la carga
es una fuente, no script: no hay ejecución de código en nuestro origen ni acceso a sesión o a
datos de tenant. Lo que queda escrito es **cuándo deja de ser aceptable**, para no tener que
volver a razonarlo: (a) el día que entre una CSP con `font-src`, o (b) el día que un build de
imagen deba ser reproducible u offline — y ojo, que (b) ya es medio verdad, porque el mismo
commit produce bytes de fuente distintos con el tiempo y una caída de `gstatic` rompe el build de
imagen **incluido el de un redespliegue de rollback**. La salida es la alternativa rechazada de
abajo, `next/font/local`.

Y una consecuencia de R4.2 que conviene tener escrita porque **sí cambia el aspecto de dos
pantallas ya entregadas**: mapear `--font-mono` hace que la utilidad `font-mono` que Tailwind ya
traía —usada en `features/reservations/components/detail/reservation-detail-sections.tsx:39` y en
`features/shell/components/version-badge.tsx:93`— pase a pintar JetBrains Mono en vez de la
monoespaciada por defecto del navegador. Es exactamente el tipo de cambio que el proposal declara
esperado («Lo que cambia de aspecto lo hace porque consumía los tokens, no porque se haya
editado»), y no es lo que R4.4 prohíbe: R4.4 habla del rol `data-mono`, que este change no aplica
a ninguna pantalla. Verificado además que ningún test importa `app/layout.tsx`: los dos que lo
nombran (`features/provenance/disclosure.test.ts:14` y `workflow-contract.test.ts:242`) lo leen
como **texto** con `readFileSync`, así que `next/font` no entra nunca en vitest y no hace falta
mock.

Rechazado: `next/font/local` con los `.woff2` versionados — build reproducible sin red, y mete
~430 KB de binarios más sus licencias OFL en el repo y obliga a curar ejes y subconjuntos a mano.
Es la salida documentada si el fetch de build llegara a molestar.
Rechazado: `<link>` a Google Fonts — un tercero en el camino crítico de una app con datos de
tenant; R4.1 lo prohíbe.

### D9 — `--border` decorativo y `--input` con contraste, dejan de ser el mismo valor

**Elegido:** hoy `--border` y `--input` tienen el mismo valor. Se separan, porque WCAG 2.2
**1.4.11** exige 3:1 al límite visual de un *componente de interfaz* y no a una línea decorativa:

- `--border` toma el valor que `DESIGN.md` manda explícitamente («Outlines are strictly defined
  at 1px using `#262a34`») → oscuro `#262a34`, claro `#d5dbe8`. Contra `--background` mide
  **1.29:1** en oscuro y **1.23:1** en claro, y se declara conforme: es la franja tonal del export, el contorno de una tarjeta no identifica
  ningún control, y ninguna información depende de verla.
- `--input`, que es el borde de los controles (`border-input` en la variante `outline` de
  `Button`), pasa a oscuro `#879390` —el `outline` del export— y claro `#6b7688`: **5.85:1** y
  **4.06:1** contra su fondo.

Rechazado: subir `--border` a 3:1 — cumpliría un requisito que WCAG no impone y borraría la
estética de hairline que es la mitad del «Midnight Technical».

### D10 — Tipografía, ritmo y radios: px del export → rem, y los radios ya cuadran

**Elegido:** los 10 roles como `--text-<rol>` con sus tres modificadores
(`--text-<rol>--line-height`, `--text-<rol>--letter-spacing`, `--text-<rol>--font-weight`), que es
la API de `@theme` en Tailwind v4 y da una sola utilidad (`text-display-2xl`) que pone tamaño,
interlineado, tracking y peso. **Se convierten los px del export a rem** (56 px → 3.5rem, …) para
que el texto siga el tamaño base del navegador; el tracking en `em` se deja tal cual porque ya es
relativo. La escala numérica por defecto de Tailwind (`text-sm`, `text-xs`, `text-lg`) **se
conserva**: la usan `Badge`, `Button` y media docena de componentes, y los roles del export son
aditivos.

El ritmo entra como `--spacing` base más `--spacing-{gutter,margin-mobile,margin-desktop}`.

> **Corrección de 2026-08-24 (`/sdd:run`, pasada visual; aprobada por Jose).** Esta decisión decía
> `--spacing-{xs,sm,md,lg,xl,2xl,3xl,4xl,gutter,margin-mobile,margin-desktop}`, y los ocho pasos de
> talla **rompían el layout**: Tailwind v4 resuelve `max-w-*` contra el espacio de nombres
> `--spacing-*` cuando esas claves existen, así que `max-w-md` compilaba a
> `max-width: var(--spacing-md)` — 12px en vez de 448px — y colapsaba 8 contenedores en 4 ficheros.
> Verificado en navegador antes y después: el formulario de login pasa de 48px de ancho a 448, y
> sus campos de 26 a 400.
>
> No se pierde nada: la escala numérica de Tailwind sobre 0.25rem **es** el ritmo del export, exacta
> en los ocho pasos (`p-1`,`p-2`,`p-3`,`p-4`,`p-6`,`p-8`,`p-12`,`p-16`). Los tres nombres que no
> colisionan se quedan. Enmienda bajada a `proposal.md` §R5.1, y `globals.tokens.test.ts` aserta
> ahora la AUSENCIA de cualquier `--spacing-<talla>`.
>
> Lección que vale más que el arreglo: **ningún test de este change podía verlo**. Todos comprueban
> que el token está declarado, y estaba declarado exactamente como el diseño pedía. El defecto vivía
> en lo que declararlo provoca en otra utilidad, y eso sólo se ve renderizando. Los cinco revisores
> de la sección 3 tampoco lo vieron, por lo mismo.

Y los radios cuadran casi solos, comprobado contra los `calc()` de hoy: `rounded-md` vale hoy
`0.375rem` y el export dice `md: 0.375rem`; `rounded-lg` vale `0.5rem` y el export dice
`lg: 0.5rem`. **Solo `sm` cambia**, de `0.25rem` a `0.125rem` (lo usa el botón de cierre de
`Sheet` — comprobado que es el único consumidor de `rounded-sm` en el árbol). Se declaran
`--radius-{sm,md,lg,xl}` con valores literales y desaparece `--radius` con sus tres `calc()`
derivados (R5.1).

**Ni `DEFAULT` ni `full` se declaran, por la misma razón dos veces**: Tailwind ya entrega el
valor del export, así que un token no tendría consumidor. Las dos mitades se comprobaron
compilando Tailwind en el contenedor, no dando nada por hecho (tarea 3.5):

- `.rounded` emite `border-radius: 0.25rem` como **literal fijo**, no `var(--radius-DEFAULT)`.
  Es exactamente el `DEFAULT: 0.25rem` del export.
- `.rounded-full` emite `border-radius: calc(infinity * 1px)`, **no** `var(--radius-full)`.
  Redondea la esquina por completo, que es lo que el `9999px` del export quiere decir, y la
  utilidad no puede leer un token aunque exista.

> **Enmienda de 2026-08-24** (panel de la sección 3, DESIGN-CONFLICT del architect; aprobada por
> Jose). R5.1 enumeraba `full` y esta decisión lo declaraba. Se retiró al comprobar que además de
> ser inalcanzable por la utilidad, **no hay en todo `frontend/` una sola referencia** a
> `rounded-full`, a `var(--radius-full)` ni a `rounded-(--radius-full)`: era un token con cero
> consumidores, el antipatrón que D2 rechaza por escrito. La enmienda bajó a `proposal.md` §R5.1,
> que es donde tenía que llegar para que la spec viva no herede un `SHALL` falso.

Para que la ausencia no se reintroduzca por descuido, `globals.tokens.test.ts` afirma las dos
cosas: que los cuatro pasos declarados son exactamente los que tienen consumidor, y que
`--radius-DEFAULT` y `--radius-full` **no** están.

### D11 — La auditoría de contraste es un test, no una tabla de una sola vez

**Elegido:** `app/globals.contrast.test.ts` parsea los valores hexadecimales de los tres bloques
de `globals.css`, calcula el ratio WCAG de cada par declarado (incluida la composición
`color-mix` de los badges al 15 % sobre las **cuatro** superficies —`background`, `surface`,
`surface-high` y `muted`, porque `bg-muted` es un fondo real de este árbol y dejarlo fuera haría
la auditoría más estrecha que la aplicación) y falla por debajo del umbral —4.5:1 texto, 3:1
controles— con las excepciones de D9 declaradas como lista explícita.

> **Enmienda de 2026-08-24 (`/sdd:run`, panel de la sección 4; aprobada por Jose).** Esta
> decisión decía «las **tres** superficies», y la auditoría mide cuatro. La ampliación es un
> superconjunto estricto —nada que pasara antes queda exento— y mueve dos suelos, los dos
> registrados en §Contraste medido: el de texto de badge de 5.40 a **4.99** (sigue pasando AA,
> umbral 4.5) y el de las anclas `state-*` de 4.21 a **3.81** (sigue pasando 3:1). Se enmienda
> **aquí**, en el texto de la decisión, y no sólo como nota en otra sección: quien lea D11 para
> saber qué mide el test tiene que encontrarlo en D11. Y se enmienda con aprobación explícita,
> igual que D10, porque cambia lo que una decisión decidió y no sólo una cifra equivocada como la
> corrección de D9 — que los números sigan pasando no vuelve la ampliación auto-aprobable.

Es la única forma de que R1.6 («la comprobación SHALL quedar registrada con su ratio medido por
par») siga siendo verdad después de este change: el helper `getA11yViolations` de `test/render.tsx`
**desactiva `color-contrast`** a propósito, porque jsdom no compone color, así que axe no puede
cubrirlo. Y una tabla en markdown envejece en cuanto alguien retoca un hex.

Rechazado: la tabla manual en `design.md` como única prueba — es lo que hay abajo, y sirve para
aprobar la paleta, no para defenderla dentro de tres changes.
Rechazado: Playwright con axe sobre la app real — cubriría el color compuesto de verdad, y
`npx playwright test` aún no existe en el proyecto (llega con `hardening-release`).

> **Hallazgo de método, 2026-08-24.** `sdd/project.md` documenta que en un worktree enlazado la app
> **no hidrata** con `PORT_OFFSET`, y eso llevó a este change a dar por imposible cualquier pasada
> visual. Es cierto **sólo para `next dev`**: Next 15+ bloquea las peticiones de desarrollo de
> origen cruzado y el desplazamiento de puerto hace que el origen no cuadre (el síntoma es el
> handshake fallido del WebSocket de HMR). **En producción no existe esa comprobación.** Sirviendo
> el build con `next start` en un contenedor aparte con su propio puerto publicado
> —`docker compose run --rm --no-deps -p 3042:3000 frontend sh -c 'npx next start -p 3000 -H 0.0.0.0'`—
> la app hidrata (`hydrated: true`) y se puede conducir con el MCP de Playwright, que este proyecto
> ya tiene activado.
>
> Con eso se verificó en navegador real lo que los tests no alcanzaban: el conmutador de tema
> respondiendo a un clic (atributo, cookie, fondo y `aria-pressed` cambiando juntos, sin recarga),
> «Sistema» borrando cookie y atributo, y **R3.7 — navegación entre rutas conservando el tema, con
> el atributo llegando ya en el HTML del servidor**, que es el criterio que el panel había dado por
> no verificable aquí. Y es lo que destapó el choque de `--spacing-*` con `max-w-*`.
>
> `sdd/project.md` merece esta corrección al archivar: su párrafo de `PORT_OFFSET` concluye que
> «sirve para alcanzar la API desde el host, no para una pasada visual», y con `next start` sí sirve
> para una pasada visual.

### D12 — Prohibir `dark:` y las escalas crudas con un guard, en vez de redefinir el variante

**Elegido:** un test `test/color-tokens.test.ts` que recorre `app/`, `components/`, `features/` y
`lib/` y falla si encuentra (a) una escala numérica de color de Tailwind
(`(bg|text|border|ring|…)-(slate|…|rose)-\d{2,3}`) o (b) un `dark:`, en código **no de test**,
con una lista de excepciones declaradas. Ese guard es a la vez la implementación de R6.6 y la de
R1.5, y su salida es el registro que R6.6 pide. Sigue el precedente de
`test/eslint-boundaries.test.ts`, que ya usa un test para hacer cumplir una regla de repo.

Excepciones declaradas, las tres únicas del árbol: `bg-black/50` del scrim de
`components/ui/sheet.tsx` (un velo, idéntico en los dos temas, y no es una escala numérica);
`#555` y `#ccc` en estilos inline de `app/global-error.tsx` (sustituye al `layout.tsx` que importa
`globals.css`, así que literalmente no tiene tokens disponibles — la misma razón por la que lleva
su catálogo i18n inline); y los ficheros `*.test.*`, que sí pueden nombrar clases.

Rechazado: redefinir el variante `dark:` con `@custom-variant` para que siga al atributo — el
variante quedaría atado al atributo y **dejaría de disparar** en el caso «sin cookie, sistema
oscuro», que es el más común.
Rechazado: una regla de ESLint — `no-restricted-syntax` sobre literales de clase es frágil con
`cva` y `cn()`; un test que lee ficheros dice exactamente lo que R6.6 quiere contar.

**Enmendado el 2026-08-24** (panel de la sección 7, revisor security): el guard lleva una
**tercera** comprobación, la de D13 — una utilidad de color que nombra un token que el CSS no
declara. Las dos primeras miran lo que sobra; ésta mira lo que falta, y es la única de las tres
que habría visto el `bg-card` de D13.

**Enmendado otra vez el 2026-08-24** (panel de la sección 8: arquitectura, security y QA, los
tres sobre el mismo fichero). La primera versión del guard tenía cuatro agujeros, y el más
grave es que se saltaba con un prefijo de variante: la mirada atrás `(?<![\w:/-])` no *quita*
la variante, **excluye la coincidencia entera**, así que `hover:bg-card` no producía nada. Diez
utilidades distintas del árbol —**19 apariciones**— eran invisibles, y `hover:text-destructive`
—a una tecla del defecto que D13 existe para cazar— daba cero violaciones.

**Corregido el recuento** (panel de la sección 8, arquitectura y QA por separado): la primera
redacción de este párrafo decía «27 apariciones», y 27 es el total de coincidencias nuevas de la
comprobación 3 (387 → 414), no lo que arregló la variante. Se descompone en **19** de la
variante y **8** de `shadow-*`, que entraron por el arreglo de prefijos, un defecto distinto.
Sumar dos bugs en una cifra y presentarla como la de uno es exactamente el desvío que R6.6 pide
evitar cuando exige que el recuento «quede registrado». La cifra de la variante es 19, y el
comentario del propio fichero ya la tenía.

Lo que quedó:

- la variante se **consume** en vez de excluir la coincidencia;
- `from`, `via`, `to` y `shadow` entran en la comprobación 3, que no los conocía aunque
  `RAW_SCALE` sí;
- **cuarta** comprobación, valores arbitrarios y variables CSS: `bg-[#e11d48]` cumple la letra
  de R6.6 —no es una escala numérica— y viola R1.5 de plano. Distingue color de dimensión
  (`text-[0.6875rem]` es un tamaño y no es violación) y falla en cerrado ante lo que no
  reconoce;
- **quinta**, hex en estilo inline. Sin ella la excepción `#555`/`#ccc` de `global-error.tsx`
  era **inerte**: ninguna comprobación emitía nunca un hex, así que `allowed()` no se consultaba
  para uno y la aserción que fija la lista prometía un límite sobre un canal que nadie vigilaba.
  Va anclada al **nombre de la propiedad** CSS, no al `#`, porque el árbol tiene
  `"Booking.com #1234"` — una referencia de reserva que un hex ingenuo lee como `#RGBA`;
- las raíces se **derivan** del listado de `frontend/` menos una lista de exclusión fijada, en
  vez de las cuatro de D12 escritas a mano: un `hooks/` nuevo se escanea el día que aparece, y
  `FILES.length` no se habría movido lo bastante para delatarlo. Hoy resuelven exactamente a las
  cuatro de D12, y una aserción lo fija. **`test/` queda fuera a propósito**: R6.6 acota la
  obligación a «código **no de test**», y al derivar entró un momento y enseñó por qué no debe —
  el módulo de patrones de este guard vive en `test/color-tokens.ts`, y su tabla `NON_COLOR`
  contiene cadenas como `from-font` que leídas como marcado parecen utilidades de color. El
  guard se señaló a sí mismo;
- el fichero de test se reconoce por extensión anclada, no por subcadena, para que un
  `checkout.test.helpers.tsx` no se exima solo por cómo se llama.

**Segunda vuelta del panel, y la razón de extraer los patrones.** Sobre la versión endurecida
el panel encontró **diez agujeros más** entre los tres revisores: variantes tipadas
(`bg-(color:--brand)`), nombres capitalizados (`bg-Card`, que Tailwind compila a nada igual que
`bg-card`), valores arbitrarios con espacio, hex en estilo con comilla simple o plantilla
—nada en este proyecto obliga a comilla doble: no hay prettier ni regla de comillas—, colores
no-hex en estilo (`rgb()`, `rebeccapurple`), la forma de **atributo** JSX (`fill="#abc"`, que es
donde los hex a mano llegan de verdad: SVG en línea), huecos en la lista de propiedades
(`accentColor`, `borderBlockColor`, `backgroundImage`), y dos falsos positivos que habrían roto
la build de alguien: `shadow-2xs` —utilidad real del Tailwind 4.3.2 que este repo fija— y
`text-[0.6875rem/1]`.

Diez agujeros en dos versiones sucesivas, todos invisibles a un test que sólo afirma «el árbol
está limpio». Como lo puso el revisor de arquitectura: el guard «se pondría verde con una regex
rota siempre que el árbol no ejercite la rotura». Así que los patrones se extraen a
`test/color-tokens.ts` y `test/color-tokens.patterns.test.ts` los recorre **desde una tabla**:
66 casos, uno por agujero encontrado, con sus negativos. La corrección del guard deja de
depender de lo que el árbol contenga hoy, y cerrar el siguiente agujero es añadir una fila.

**Límite que el guard no cubre, y se declara en vez de insinuarse**: una clase construida
dinámicamente (`` `bg-${tono}-100` ``, concatenación) no la ve ninguna de las cinco
comprobaciones. Es el mismo punto ciego por el que D12 rechazó la regla de ESLint, y el test lo
hereda. En la práctica hoy no muerde —el proyecto ya usa tablas de consulta
(`TONE_BADGE_CLASS`, `severityColorGroup`) en vez de armar clases— y además Tailwind no extrae
esas clases, así que un desliz degrada a código muerto, no a un color silenciosamente erróneo.

**Segundo límite declarado, por simetría con el anterior** (lo pidió el revisor de QA, y tiene
razón en que declararlo es la mitad del trabajo): el guard comprueba que el token **existe**, no
que sea el **correcto**. Cambiar `text-state-error-text` por `text-state-success-text` en un
mensaje de error deja las cinco comprobaciones en verde, porque ambos tokens están declarados.
Eso es semántica de sitio de llamada y sólo lo cazan aserciones de render; las hay para los
badges de severidad (sección 7), y no para los tres mensajes de error de D13 —`guest-fields.tsx`
no tiene fichero de test siquiera, hueco anterior a este change. Se declara y no se cierra.

### D13 — `bg-card` no pinta nada, y el guard que lo habría visto

**El hallazgo**, del panel de la sección 7: seis ficheros de producción visten sus tarjetas con
`bg-card` —`features/dashboard/components/property-card.tsx:56`,
`features/dashboard/components/detail/property-detail-sections.tsx:23`,
`features/properties/components/list/properties-view.tsx:125`,
`features/cleaning/components/cleaning-task-row.tsx:139`,
`features/pricing/components/rule-row.tsx:69` y
`features/pricing/components/recommendation-row.tsx:89`— y la cadena `card` aparece **cero**
veces en `app/globals.css`. Esas seis superficies no pintan nada: caen al fondo de la página y
la tarjeta se queda sin elevación contra él.

**No es una regresión de este change**: `card` tampoco aparecía en `globals.css` en la base de
la rama (`b5ee09a`), verificado en las dos puntas. Es un defecto que llevaba ahí desde antes y
que la reescritura del bloque de color de la sección 2 ni introdujo ni arregló.

**Elegido:** las seis pasan a `bg-surface`, y el guard de D12 gana la tercera comprobación.
`--surface` ya existe, ya está expuesto en `@theme inline` como `--color-surface`, y es
exactamente el token que el export quería aquí: la fila de §Paleta lo anota
«E `surface-container-low` (DESIGN.md: «Cards use #181b25»)». O sea que el valor correcto para
una tarjeta ya estaba declarado y con el hex del export; lo único que faltaba era que alguien
lo nombrara.

Entra en el alcance porque **R1.5** —«el color de cualquier superficie, texto o borde de la
aplicación dependa del tema resuelto»— es falso mientras seis superficies dependan de nada. Y
el guard hace falta aparte del arreglo: las dos comprobaciones que D12 tenía buscan escalas
crudas y `dark:`, y `bg-card` no es ninguna de las dos, así que la sección 8 habría dado 0 sobre
un árbol con seis superficies sin pintar. Un guard que sólo mira lo que sobra no ve lo que
falta.

Rechazado: declarar `--card` y `--card-foreground` en los dos temas — duplicaría el valor de
`--surface` con otro nombre, subiría el conjunto de D2 de 25 a 27 tokens por nada y obligaría a
medir un par nuevo en §Contraste medido. El token que hacía falta ya estaba.
Rechazado: sólo el guard, con las seis como excepciones declaradas — deja el defecto en pie y
convierte la lista de excepciones de D12, que hoy tiene tres entradas razonadas, en un vertedero.
Rechazado: dejarlo para `visual-restyle-workspace` — es el change que traerá la primitiva
`Card`, pero R1.5 es un criterio de aceptación de **éste**, y seis superficies sin color no lo
cumplen.

**Y no era el único.** Al escribir la tercera comprobación (tarea 8.1) apareció el segundo caso
de la misma clase, que nadie había mirado: `text-destructive` en
`features/auth/components/login-form.tsx:64`,
`features/dashboard/components/detail/property-timeline.tsx:192` y
`features/guest-portal/components/fields/guest-fields.tsx:8`. `--color-destructive` tampoco está
declarado, así que los tres mensajes de error —incluido el `role="alert"` del formulario de
login— heredaban `--foreground`: un error que no parecía un error. Pasan a
`text-state-error-text`, que es el token de texto de error de D6 y ya estaba declarado.

Eso obliga a ensanchar la auditoría de D11: `badgePairs` mide los `state-*-text` sobre su propio
tinte al 15 %, que es el badge, pero texto de error suelto sobre una superficie lisa es **otro
par con otro número**. `corePairs` gana las cinco familias × cuatro superficies (20 pares por
tema, 51 → 71), medidas y en verde: 5.97:1 el peor —`state-warning-text` sobre `muted` en
claro— y 12.89:1 el mejor. Se miden las cinco y no sólo `error` por la razón que el propio
fichero da sobre `--muted`: la auditoría no debe ser más estrecha que lo que la aplicación puede
pintar.

Que el guard encontrara un segundo caso el mismo día que se escribió es el argumento de esta
decisión, no una anécdota: dos defectos de superficie invisible convivían en `main` sin que
ninguna comprobación de «lo que sobra» los viera.

## Paleta

Semilla: `E` = valor literal del export (`DESIGN.md`), con el nombre del token de origen.
`N` = valor nuevo de esta propuesta. Todos los ratios están **medidos**, no estimados.

### Núcleo (15 tokens)

| token | oscuro | de dónde | claro | de dónde |
|---|---|---|---|---|
| `background` | `#0f131c` | E `background`/`surface` | `#eef1f7` | N — hermano claro de E `inverse-surface` |
| `foreground` | `#F8FAFC` | E `text-primary` | `#2c303a` | E `inverse-on-surface` |
| `surface` | `#181b25` | E `surface-container-low` (DESIGN.md: «Cards use #181b25») | `#f8fafd` | N |
| `surface-high` | `#1c2029` | E `surface-container` | `#ffffff` | N |
| `muted` | `#262a34` | E `surface-container-high` | `#e2e7f1` | N |
| `muted-foreground` | `#94A3B8` | E `text-secondary` | `#525b6b` | N — E `text-muted` oscurecido a AA |
| `accent` | `#262a34` | = `muted` (como hoy) | `#e2e7f1` | = `muted` (como hoy) |
| `accent-foreground` | `#F8FAFC` | = `foreground` (como hoy) | `#2c303a` | = `foreground` (como hoy) |
| `primary` | `#70d8c8` | E `primary` | `#006b5f` | E `inverse-primary` (D3) |
| `primary-foreground` | `#003731` | E `on-primary` | `#ffffff` | N |
| `secondary` | `#3e495d` | E `secondary-container` | `#dfe2ef` | E `inverse-surface` |
| `secondary-foreground` | `#aeb9d0` | E `on-secondary-container` | `#2c303a` | E `inverse-on-surface` |
| `border` | `#262a34` | E `surface-container-high` (DESIGN.md: «Outlines … 1px using #262a34») | `#d5dbe8` | N |
| `input` | `#879390` | E `outline` | `#6b7688` | N (D9) |
| `ring` | `#70d8c8` | = `primary` | `#006b5f` | = `primary` |

Las tres superficies son **monótonas en los dos temas**: cada paso se acerca al observador
aclarándose (oscuro `0f131c → 181b25 → 1c2029`; claro `eef1f7 → f8fafd → ffffff`). Esa es la
razón de reducir la rampa M3 de seis pasos del export a tres: seis pasos invertidos dejan de ser
monótonos y el nombre deja de significar lo mismo en cada tema.

### Estado (10 tokens) — la quinta familia de PRD §9.1 incluida

| token | oscuro | claro | de dónde |
|---|---|---|---|
| `state-success` | `#10B981` | `#0f7a58` | E `state-success` / N (misma tinta, a AA) |
| `state-warning` | `#F59E0B` | `#a4600a` | E `state-warning` / N |
| `state-error` | `#EF4444` | `#c92a2a` | E `state-error` / N |
| `state-info` | `#38BDF8` | `#0a72ad` | E `state-info` / N |
| `state-neutral` | `#94A3B8` | `#64748B` | E `text-secondary` / E `text-muted` — **R6.1** |
| `state-success-text` | `#6EE7B7` | `#065f46` | N |
| `state-warning-text` | `#FCD34D` | `#7c4a04` | N |
| `state-error-text` | `#FCA5A5` | `#991b1b` | N |
| `state-info-text` | `#7DD3FC` | `#0b5177` | N |
| `state-neutral-text` | `#CBD5E1` | `#3f4a5a` | N |

Los `state-*` son tokens **gráficos**: rellenos, puntos, bordes, umbral 3:1 (medido 4.21-8.67 en
los dos temas). Los `state-*-text` son los de texto, umbral 4.5:1.

### Contraste medido (R1.6)

Oscuro, texto (umbral 4.5:1): `foreground` sobre las tres superficies **17.76 / 16.42 / 15.58**;
`muted-foreground` **7.25 / 6.70 / 6.36**; `primary-foreground` sobre `primary` **7.76**;
`secondary-foreground` sobre `secondary` **4.60**; `accent-foreground` sobre `accent` **13.72**.
Controles (3:1): `input` **5.85 / 5.40**, `ring` **10.92 / 10.10**.

Claro, texto: `foreground` **11.67 / 12.62 / 13.20**; `muted-foreground` **6.05 / 6.55 / 6.85**;
`primary-foreground` sobre `primary` **6.43**; `secondary-foreground` sobre `secondary` **10.22**;
`accent-foreground` sobre `accent` **10.64**. Controles: `input` **4.06 / 4.39**, `ring`
**5.68 / 6.15**.

Badges, las 30 combinaciones (5 tonos × 3 superficies × 2 temas), texto sobre el ancla compuesta
al 15 %: **oscuro 7.32-10.02**, **claro 5.40-7.46**. Mínimo global **5.40** (ámbar claro sobre
`background`). Cero fallos.

> **Ampliación de 2026-08-24 (`/sdd:run`, tarea 4.1).** Esta tabla mide sobre **tres**
> superficies —`background`, `surface`, `surface-high`— y el test de contraste mide sobre
> **cuatro**, añadiendo `muted`, porque `bg-muted` es un fondo real en este árbol y dejarlo fuera
> haría la auditoría más estrecha que la aplicación. Las 28 cifras de arriba se reproducen
> **exactas** desde `globals.css` (cotejo de la tarea 4.2, cero discrepancias). Lo que cambia al
> añadir la cuarta superficie son los rangos, y en un sitio importa:
>
> | serie | 3 superficies (esta tabla) | 4 superficies (el test) |
> |---|---|---|
> | badges, texto, oscuro | 7.32-10.02 | 6.47-10.02 |
> | badges, texto, claro | 5.40-7.46 | **4.99**-7.46 |
> | borde de badge al 40 % (exento) | 1.37-1.83 | 1.35-1.83 |
> | anclas `state-*` (umbral 3:1) | 4.21-8.67 | 3.81-8.67 |
>
> **Y el margen más fino de la paleta no es éste.** Es `secondary-foreground` sobre `--secondary`
> en oscuro: **4.60**, es decir **+0.10** sobre AA. Ese par sí está aserido, así que una regresión
> se ve; pero si algún change futuro toca `--secondary` o su foreground, ése es el número sin
> holgura, no el 4.99 de abajo. Levantado por el revisor de seguridad en el panel de la sección 4,
> corrigiendo el énfasis de esta misma nota.
>
> **El suelo real de los badges es 4.99, no 5.40**: `state-warning-text` sobre un badge ámbar al 15 % encima de
> `muted`, en claro. Sigue pasando AA —el umbral es 4.5— pero el margen es **+0.49 y no +0.90**,
> la mitad de lo que esta tabla sugería. Se deja escrito porque es exactamente el número que un
> cambio futuro puede tirar sin darse cuenta: oscurecer `muted` un poco en claro, o mover
> `state-warning-text`, pone un badge por debajo de AA, y quien mirara sólo el 5.40 creería tener
> el doble de holgura. El test mide los 40 pares en cada ejecución, así que se enteraría; esta
> nota es para quien lea la tabla y no el test.
>
> Las anclas `state-*` bajan a 3.81 (rojo oscuro sobre `muted`) por la misma razón, y siguen
> sobre su umbral de 3:1. Ninguna combinación falla en ninguno de los dos conjuntos.

Excepciones declaradas y su razón, ya en D9: `border` **contra `--background`** mide 1.29:1
(oscuro) / **1.23:1** (claro) y el borde de badge al 40 % mide 1.37-1.83:1 contra su propia
superficie — líneas decorativas, no
límites de control, y en ningún caso portadoras únicas de información (el badge lleva su rótulo
traducido, así que WCAG 1.4.1 también queda cubierto).

> **Corrección de 2026-08-24 (`/sdd:run`, panel de la sección 2).** Esta tabla decía 1.32:1
> para el `border` claro. El valor real de `#d5dbe8` contra `--background` `#eef1f7` es
> **1.23:1**; 1.33:1 es lo que mide contra `--surface` `#f8fafd` y 1.39:1 contra
> `--surface-high` `#ffffff`. Es decir: la fila oscura se midió contra `--background` y la
> clara contra `--surface`, así que **las dos filas del mismo par declarado describían pares
> distintos**. No mueve ningún umbral —la excepción de D9 se sostiene por su razonamiento, no
> por el número— pero sí el registro que pide R1.6, y `globals.contrast.test.ts` (tarea 4.1)
> tiene que codificar el mismo par en los dos temas. Todas las demás cifras de esta sección se
> recomputaron en la misma pasada y **coinciden exactamente**, incluidas las 30 combinaciones
> de badge (oscuro 7.32-10.02, claro 5.40-7.46, mínimo global 5.40 en ámbar claro sobre
> `background`) y el rango 1.37-1.83 del borde al 40 %.

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| Tokens | `frontend/app/globals.css` | Reescrito: tres bloques de D1, 25 tokens de color × 2 temas, `color-scheme`, 10 roles `--text-*`, 11 pasos `--spacing-*`, 5 `--radius-*`, `--font-sans`/`--font-mono`. Se conservan intactos `@layer base`, `:focus-visible`, `prefers-reduced-motion`, `tap-target`, `pb-safe` (R5.3) |
| Fuentes | `frontend/app/layout.tsx` | `next/font/google` (Inter, JetBrains Mono) + clases en `<html>` + `data-theme` desde `getServerTheme()` |
| Config | `frontend/lib/config/constants.ts` | `THEME_COOKIE`, `Theme`, `isTheme` junto a los del idioma |
| Tema | `frontend/lib/theme/theme.ts`, `frontend/lib/theme/server.ts` (nuevos) | `resolveTheme()` isomorfo; `getServerTheme()` server-only |
| Conmutador | `frontend/features/shell/components/theme-switcher.tsx` (nuevo), `theme-switcher.test.tsx` (nuevo), `topbar.tsx` | Grupo accesible de tres estados; `Topbar` pasa a `async` y lo monta por defecto |
| i18n | `frontend/locales/{es,en}/navigation.json` | `themeSwitcher.{label,light,dark,system}` |
| Tonos | `frontend/lib/ui/status-tone.ts` | Las 5 entradas de `TONE_BADGE_CLASS` pasan a tokens; desaparecen sus 24 escalas crudas y 12 `dark:` |
| Severidad | `frontend/features/incidents/lib/severity-tone.ts` (nuevo), `components/detail/incident-detail-sections.tsx`, `components/list/incidents-view.tsx` | Los dos `SEVERITY_COLOR` mueren; queda un mapa enum→`Tone` |
| Tests | `frontend/components/property-state-badge.test.tsx` | Las cadenas fijadas se actualizan a las nuevas (13 `dark:` + 24 escalas fuera) |
| Guards | `frontend/app/globals.tokens.test.ts`, `globals.contrast.test.ts`, `test/color-tokens.test.ts` (nuevos) | Paridad de los tres bloques (D1), auditoría de contraste (D11), cero escalas crudas y cero `dark:` (D12) |
| Docs | `frontend/README.md` | La sección de estilos deja de describir una paleta placeholder |

## Data & interfaces

Sin cambios de esquema, de contrato de API ni de variables de entorno: no hay que regenerar
`backend/openapi.json` ni `frontend/lib/api/generated/openapi.d.ts` (y por tanto no aplica el
apaño de `api:generate` en worktree que documenta `sdd/project.md`).

Superficie nueva, toda de frontend:

```ts
// lib/config/constants.ts
export const THEME_COOKIE = "autohostai.theme";        // path=/, samesite=lax, sin PII
export const SUPPORTED_THEMES = ["light", "dark"] as const;
export type Theme = (typeof SUPPORTED_THEMES)[number];

// lib/theme/theme.ts        — isomorfo, sin Next ni navegador
export function resolveTheme(value: string | undefined | null): Theme | null;
export const THEME_ATTRIBUTE = "data-theme";

// lib/theme/server.ts       — "server-only"
export async function getServerTheme(): Promise<Theme | null>;

// features/incidents/lib/severity-tone.ts
export function severityColorGroup(severity: IncidentSeverity): Tone;
```

Cookie: `autohostai.theme` = `light` | `dark`, `path=/`, `samesite=lax`, `max-age=31536000`, sin
dato personal — la misma postura que `autohostai.locale`. La **ausencia** es el tercer estado.

## Risks & mitigations

- **Quedarse a medias**, el riesgo que nombra el roadmap. Mitigación: el guard de D12 es el
  criterio de terminado y es un número, no una impresión — 68 usos en 4 ficheros hoy, 0 en código
  no de test al acabar.
- **Deriva entre los dos bloques oscuros** que impone D1. Mitigación: el test de paridad de D1
  compara nombres y valores; sin él la duplicación sería inaceptable.
- **`Topbar` pasa a `async`** y lo renderizan los cinco shells. Es un Server Component en los
  cinco casos, así que es legal; `features/shell/*.test.tsx` (`shell-frame`, `workspace-shell`,
  `field-public-guest-shell`) son la red que lo detecta si algún camino lo renderiza desde
  cliente. Verificar esos tres ficheros antes de cerrar la sección.
- **`rounded-sm` cambia** de 0.25rem a 0.125rem, único cambio geométrico visible del change
  (botón de cierre de `Sheet`). Aceptado: es el valor del export.
- **Cambio visual amplio sin pantalla nueva**: toda la app cambia de aspecto porque consumía los
  tokens. Es el efecto pretendido, no una regresión; lo que se vea raro es de
  `visual-restyle-workspace` (fuera de alcance, dicho en el proposal).
- **Red en tiempo de build** por D8. Mitigación: falla ruidosamente y `next/font/local` es la
  salida documentada.
- **Sin pasada visual desde este worktree**: `sdd/project.md` documenta que con `PORT_OFFSET` la
  página se sirve pero **no hidrata** (medido el 2026-08-23), así que el conmutador no se puede
  probar a mano aquí. La verificación es vitest (`theme-switcher.test.tsx` sobre jsdom, que sí
  cubre cookie + atributo + `aria-pressed`) y, si hace falta ojo humano, el worktree principal o
  `dev`. No se toca `next.config` para poder mirar la app.
- **La suite de partida se mide, no se recuerda**: `sdd/project.md` avisa de que la cifra escrita
  ahí ha estado desfasada, y de los 2 ficheros que dan `ENOENT` en worktree hasta hacer los
  `docker compose cp`. Medir el punto de partida antes de tocar nada.

## Open questions

**Las cinco quedaron resueltas por Jose el 2026-08-23, en el gate de esta fase.** Ninguna
enmienda un requisito del proposal: R2.1 pedía aprobación (dada), R2.4 pedía resolver el
primario canónico (resuelto en D3 como el proposal mandaba) y R4.1 admitía cualquier vía
autohospedada.

1. **Paleta clara: aprobada tal cual.** R2.1 cerrado, R2.3 no se activa: el change entrega los
   dos temas con los valores de §Paleta, sin retoques.
2. **Primario claro: `#006b5f`** (E `inverse-primary`), no el `#00897b` de la prosa del export.
   D3 queda en firme y R2.4 cerrado: `#70d8c8` en oscuro, `#006b5f` en claro.
3. **`#00897b` no se declara como token.** Queda escrito en la spec al archivar y fuera de
   `@theme`, porque hoy no tendría consumidor; lo declarará quien lo use — el glow y los
   titulares grandes son de `visual-restyle-workspace` y `landing-public`.
4. **Fuentes: `next/font/google`.** D8 en firme, con `next/font/local` como salida documentada si
   el fetch en tiempo de build llegara a molestar.
5. **El conmutador va también en `/guest/[token]`**, sin excepción: los cinco shells lo heredan
   del slot `end` de `Topbar`, que el `GuestShell` ya monta para el de idioma.
