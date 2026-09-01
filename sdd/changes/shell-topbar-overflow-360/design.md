# Design: shell-topbar-overflow-360

## Context

`frontend/features/shell/components/topbar.tsx` es un Server Component con tres slots
(`start`, `center`, `end`) dentro de un `<header className="flex h-14 … justify-between gap-3 … px-4">`.
El slot `end` es el único de los tres sin `min-w-0`, y las tres shells autenticadas
(`workspace-shell.tsx:49-57`, `cleaner-shell.tsx:32-40`, `technician-shell.tsx:32-40`) le pasan
**el mismo fragmento triplicado literalmente**: `[ThemeSwitcher, Separator, LocaleSwitcher,
NotificationBell, UserMenu]`, la composición que `sdd/specs/frontend-foundation.md:25` fija por
escrito. Las otras tres composiciones son `(authenticated)/layout.tsx:34` (`UserMenu` solo),
y `PublicShell`/`GuestShell`, que no pasan `end` y por tanto reciben el default del propio
`Topbar` (`ThemeSwitcher` + `Separator` + `LocaleSwitcher`).

Los controles son islas de cliente ya existentes (`theme-switcher.tsx`, `locale-switcher.tsx`,
`features/notifications/components/notification-bell.tsx`, `features/auth/components/user-menu.tsx`)
y el repo ya tiene el patrón de «dos disposiciones en el DOM, una elegida por media query»:
`workspace-shell.tsx:35-40` monta `Breadcrumbs` con `hidden md:block` y `PageTitle` con
`md:hidden`. También existe ya un contenedor desplegable con la primitiva `Sheet`
(`components/ui/sheet.tsx`, consumida por `more-menu.tsx`).

Lo que **no** existe: infraestructura de navegador. `frontend/package.json` no declara
`@playwright/test` ni `@vitest/browser`, no hay `playwright.config.*` en el árbol, y
`sdd/project.md` describe `npx playwright test` como «previsto — llega con `hardening-release`».
La suite corre en jsdom (`vitest.config.ts`), que no hace *layout*. Ese hueco es toda la
dificultad de R5 y está tratado en D6/OQ-1.

## Decisions

### D0 — Hallazgo previo: `PublicShell` en `/` también desborda; el default del `Topbar` entra en alcance

**Constatado por aritmética antes de decidir nada**, porque el censo del proposal daba
«sin medir» a cuatro composiciones y R1.4 prohíbe romper lo que funcionaba.
El slot `end` **por defecto** (el que reciben `PublicShell` y `GuestShell`) suma
`ThemeSwitcher` 136 + `Separator` 9 + `LocaleSwitcher` 44 + 2 × `gap-2` 16 = **205 px**.
Sobre 360 px:

| Composición | `px-4` | `start` | `center` | `end` | Total | Veredicto |
|---|---|---|---|---|---|---|
| `PublicShell` en `/` (con `MarketingNav`) | 32 | `Brand` ~90 | `Login` ~70 + 12 | 205 + 12 | **~421** | desborda |
| `PublicShell` en `/login`, `/forgot-password` | 32 | `Brand` ~90 | — | 205 + 12 | ~339 | cabe, con 21 px |
| `GuestShell` | 32 | `Brand` ~90 | — | 205 + 12 | ~339 | cabe, con 21 px |
| `(authenticated)` (`/welcome`) | 32 | `Brand` ~90 | — | `UserMenu` ≤192 + 12 | ~326 max | cabe |

`Brand` (`brand.tsx:7`) es un `<span>` sin `truncate` ni `min-w-0`: en un contenedor flex su
`min-width` es `auto`, así que **no encoge** y pina ~90 px de los 360. `TabletNavTrigger` es
`hidden md:inline-flex lg:hidden`, o sea que a 360 px no ocupa nada — por eso `WorkspaceShell`
tiene el `start` más barato de las tres y aun así desborda.

**Consecuencia de diseño:** el arreglo no puede vivir solo en las tres shells autenticadas.
El default del `Topbar` recibe el mismo tratamiento, y los márgenes de 21 px de `/login` y
`/guest/[token]` son demasiado finos para dejarlos como están (una traducción más larga en `en`
se los come). Las seis composiciones pasan por el mismo mecanismo.

Estas cifras son **una predicción, no una medición**: R1.2 sigue exigiendo el navegador real, y
la tarea de verificación las confirma o las corrige.

#### Medición real (tarea 1.1, 2026-08-31) — la predicción de `/` era falsa

Chromium a 360×780 contra el stack de este worktree (`PORT_OFFSET=60`, `next dev`, la app hidrata
y navega por clic), entrando con los tres roles y leyendo
`document.documentElement.scrollWidth` / `clientWidth`:

| Composición | Ruta | `scrollWidth` | `clientWidth` | slot `end` | Veredicto medido | Predicción de arriba |
|---|---|---|---|---|---|---|
| `PublicShell` + `MarketingNav` | `/` | 345 | 345 | 205 | **cabe** | «desborda ~421» — **falsa** |
| `PublicShell` | `/login` | 360 | 360 | 205 | cabe (22 px) | cabe, 21 px — **confirmada** |
| `GuestShell` | `/guest/[token]` | 360 | 360 | 205 | cabe (22 px) | cabe, 21 px — **confirmada** |
| `(authenticated)` | `/welcome` | 360 | 360 | `UserMenu` 152 | cabe | cabe — **confirmada** |
| `WorkspaceShell` | `/dashboard` | **457** | 345 | 429 | **desborda** (+112) | roto — confirmada |
| `TechnicianShell` | `/tech` | **445** | 345 | 417 | **desborda** (+100) | roto — confirmada |
| `CleanerShell` | `/cleaner` | **465** | 345 | 437 | **desborda** (+120) | composición idéntica — confirmada |

(`clientWidth` 345 y no 360 en las tres rotas es la barra de desplazamiento vertical de 15 px que
esas páginas sí tienen; las cuatro que caben son cortas y no la tienen. El desbordamiento se mide
contra `clientWidth`, que es lo que R1.1 dice.)

**Por qué `/` no desborda y la aritmética decía que sí.** La tabla daba por hecho que `Brand`
«no encoge y pina ~90 px», y eso es cierto del `<span>`, no de su contenedor: los slots `start` y
`center` **sí** llevan `min-w-0` (`topbar.tsx:42,44`), así que se comprimen por debajo de su
contenido. Medido en `/`: el contenedor de `Brand` queda en **37 px** con un `scrollWidth` de 89, y
el del `center` en 47 px con 68. El texto se sale de su slot —desbordamiento de tinta, que el
navegador no suma al `scrollWidth` de la raíz— en vez de empujar la fila. Así que el defecto en `/`
existe y es visible (la marca aplastada y solapada con el `MarketingNav`), pero **no** es el que
R1.1 mide, y hoy esa composición cumple el criterio.

Lo que esto cambia y lo que no:

- **No cambia el alcance.** El default del `Topbar` sigue entrando (D0 en su conclusión de diseño),
  y por la razón que sí se midió: los 22 px de holgura de `/login` y `/guest/[token]` son reales y
  siguen siendo demasiado finos, y `/` mejora al liberar los 205 px del `end` en favor del `start`
  y el `center`, que es lo que hoy los aplasta.
- **Cambia el «antes» que R1.4 compara.** `/` , `/login`, `/guest/[token]` y `/welcome` cumplen
  R1.1 hoy: la verificación tiene que dejarlas cumpliéndolo igual, no arreglarlas.
- **La marca aplastada de `/` no es un hallazgo que este change arregle**: es contenido de la
  cabecera, no desbordamiento horizontal, y el proposal manda anotar y no arreglar
  («Tocar el contenido de las pantallas», Out of scope). Queda anotado aquí.

Rechazado: tratar solo `WorkspaceShell`/`CleanerShell`/`TechnicianShell` — dejaría `/` roto y R1.1
nombra las seis composiciones.

### D1 — Reagrupar, no encoger: los dos controles de *preferencia* pasan a un desplegable; los dos de *estado* se quedan en la barra

**Elegido:** por debajo del breakpoint, el slot `end` de las shells autenticadas es
`[disparador del desplegable, NotificationBell, UserMenu]`, y `ThemeSwitcher` + `LocaleSwitcher`
viven dentro del desplegable. Para el default (`PublicShell`/`GuestShell`) el slot `end` estrecho
es solo `[disparador del desplegable]`.

El criterio de reparto es qué información se pierde al esconder el control: la campana **muestra
estado** (el badge de no leídas, `notification-bell.tsx:63-72`) y el `UserMenu` **muestra
identidad** (quién tiene la sesión abierta en un dispositivo compartido, que es la razón escrita
en `user-menu.tsx:31-35`). Esconderlos detrás de un toque destruye información que hoy se ve de
un vistazo. El tema y el idioma no muestran nada: son preferencias que se cambian una vez.

Presupuesto a 360 px con esta disposición:

| Composición estrecha | `px-4` | `start` | `end` | Total | Holgura |
|---|---|---|---|---|---|
| `TechnicianShell` / `CleanerShell` | 32 | `Brand` 90 + `gap-3` 12 + `PageTitle` →0 | 44 + 8 + 44 + 8 + 44 = **148** + `gap-3` 12 | **294** | 66 px para el email |
| `WorkspaceShell` | 32 | `PageTitle` →0 | 148 + 12 | **192** | 168 px para el email |
| `PublicShell` en `/` | 32 | `Brand` 90 + 12 | 44 + 12 | **190** | 170 px para `MarketingNav` |
| `GuestShell` / `(authenticated)` | 32 | `Brand` 90 + 12 | 44 (o `UserMenu`) + 12 | **190** | — |

Ningún control encoge y ninguna superficie táctil baja de 44 px (R3.1, R3.2): el disparador lleva
`tap-target` como los demás.

Rechazado: **meter los cinco controles en el desplegable** — el suelo bajaría a 132 px, pero el
badge de no leídas dejaría de verse en la app de campo, que es donde más importa, y sería un
cambio de producto disfrazado de fix.
Rechazado: **solo `min-w-0` en el slot `end`** — el proposal ya lo descarta con el suelo de 265 px,
y esta medición lo confirma; se añade igualmente por D5, pero no arregla nada por sí solo.
Rechazado: **`flex-wrap` a una segunda línea** — cambia la altura fija `h-14` del header y con ella
el `pb-16` que `ShellFrame` reserva; es rediseño, fuera de alcance.
Rechazado: **`overflow-x-auto` en el slot `end`** — satisface R1 al precio de un scroller interno
sin affordance en móvil, que es peor UX que el defecto que arregla.
Rechazado: **recortar `max-w-48` del `UserMenu`** — R3.2 lo prohíbe explícitamente.

### D2 — El desplegable es un `Sheet` inferior, no un `DropdownMenu`

**Elegido:** `components/ui/sheet.tsx` con `side="bottom"`, la misma primitiva y la misma postura
que `more-menu.tsx` ya usa para el «Más» de la navegación inferior.

`ThemeSwitcher` es un `role="group"` con tres botones `aria-pressed` y `LocaleSwitcher` es un botón
de acción con tooltip. Un `DropdownMenu` de Radix implementa el patrón *menu* (roving tabindex,
hijos `role="menuitem"`): meter ahí botones arbitrarios rompe la semántica de teclado y contradice
R2.2, que exige **el mismo nombre accesible y el mismo efecto** que en la barra. Un `Sheet` es un
diálogo: acepta contenido interactivo cualquiera y trae de fábrica el foco atrapado, el `Escape` y
la devolución del foco que `frontend-foundation.md:28` exige para los cajones.

No añade dependencias: `@radix-ui/react-dialog` ya está en `package.json`.

Rechazado: `DropdownMenu` — semántica de menú incompatible con los controles que tiene que alojar.
Rechazado: `Popover` de Radix — habría que añadir `@radix-ui/react-popover`, y un popover anclado
dentro de un `<header>` de 56 px de alto pide posicionamiento en portal que el `Sheet` ya resuelve.
Rechazado: `<details>/<summary>` nativo (que tendría la virtud de **no duplicar** los controles,
ver D4) — habría que escribir a mano el foco atrapado, el `Escape`, la devolución del foco y el
posicionamiento absoluto, reimplementando mal lo que Radix ya hace bien en el resto del shell.

### D3 — Un solo componente compone las dos disposiciones: `TopbarPreferences` (servidor) + `TopbarOverflowSheet` (cliente)

**Elegido:** dos componentes nuevos en `frontend/features/shell/components/`:

- `topbar-preferences.tsx` — **Server Component**. Renderiza las dos ramas:
  ```tsx
  <div className="hidden items-center gap-2 sm:flex">
    <ThemeSwitcher initial={initial} />
    <Separator orientation="vertical" className="mx-1 h-6" />
    <LocaleSwitcher />
  </div>
  <TopbarOverflowSheet initial={initial} className="sm:hidden" />
  ```
- `topbar-overflow-sheet.tsx` — `"use client"`. El disparador (`Button size="icon"` con
  `tap-target`) y el `SheetContent` con `ThemeSwitcher`, un `Separator` y `LocaleSwitcher`.

Y un tercero, `authenticated-topbar-actions.tsx` (**Server Component**), que compone
`<TopbarPreferences initial={theme} /> <NotificationBell profile={…} /> <UserMenu />` y sustituye
al fragmento hoy triplicado en las tres shells autenticadas. `Topbar` usa `TopbarPreferences` como
su `end` por defecto.

Esto mantiene R4.3: el `Topbar` y las cinco shells siguen siendo Server Components y `"use client"`
queda confinado a la isla nueva, exactamente como `frontend-foundation.md:15` lo describe.
Y de paso mata la triplicación: la composición que la spec fija en su línea 25 pasa a tener **un
solo sitio** donde se escribe, que es lo que hace que la guarda de D6 sea posible.

Rechazado: **cambiar la API de slots del `Topbar`** (de `end: ReactNode` a algo estructurado) —
rompería `(authenticated)/layout.tsx`, `PublicShell` y `GuestShell` sin necesidad, y el slot opaco
es lo que permite que la landing meta su `MarketingNav` en `center`.
Rechazado: **poner la lógica responsive dentro de cada shell** — cuatro copias del mismo par de
ramas, que es el defecto que ya tenemos multiplicado por dos.

### D4 — La selección es `display:none` por media query, con el precio explícito de duplicar dos islas

**Elegido:** las dos ramas conviven en el DOM y las elige Tailwind (`hidden sm:flex` / `sm:hidden`),
que compila a `display: none`. Es el mecanismo que R4.1 exige (media query, nunca detección de
viewport en JS) y el que R4.2 anticipa cuando dice «IF la solución mantiene en el DOM las dos
disposiciones a la vez».

`display: none` saca el subárbol del árbol de accesibilidad **y** del orden de tabulación, así que
en cualquier ancho la tecnología asistiva encuentra una sola instancia de cada control (R4.2).
Queda prohibido resolverlo con `invisible`, `opacity-0` o `sr-only`, que esconden a la vista pero
**no** al lector de pantalla; la guarda de D6 lo pina.

**El precio, dicho entero:** `ThemeSwitcher` se monta dos veces y guarda su estado en local
(`useState` en `theme-switcher.tsx:58`), porque `design-system-tokens.md:23` prohíbe por escrito
guardar el tema en Zustand o en cualquier store de cliente. Consecuencia: si la usuaria cambia el
tema desde el `Sheet` a 360 px y **después ensancha la ventana sin navegar**, la instancia ancha
—que se montó con el `initial` del servidor y nunca vio el clic— pintaría el botón `aria-pressed`
equivocado hasta la siguiente renderización de servidor. La página tiene el tema correcto (el
atributo va en `<html>`); lo que iría desfasado es cuál de los tres botones aparece pulsado.

**Resuelto, no aceptado.** OQ-3 se cerró el 2026-08-31 a favor de arreglarlo en este change: el
mecanismo está en **D9** y el requisito que lo obliga es el nuevo **R4.4** del proposal. Se deja
escrito aquí porque es la consecuencia de esta decisión y no de la de D9.

Sigue aplicándose, y es gratis, el que Radix desmonte el contenido del `Sheet` al cerrarlo: la
instancia del desplegable **nace fresca** en cada apertura, así que las dos solo coexisten mientras
el desplegable está abierto.

`LocaleSwitcher` no tiene el problema: su efecto llama `router.refresh()`
(`locale-switcher.tsx:76`), que re-ejecuta los Server Components y vuelve a sembrar las dos ramas.

Rechazado: **subir el estado del tema a un store compartido** — `sdd/specs/design-system-tokens.md`
lo prohíbe con nombre y motivo (el store hidrata después del primer pintado).
Rechazado: **añadir `router.refresh()` al `ThemeSwitcher`** — cambia el comportamiento de un
componente que pertenece a `design-system-tokens`, y este change es un fix de desbordamiento.

### D5 — `min-w-0` en el slot `end`, y `Brand` sigue sin tocarse

**Elegido:** añadir `min-w-0` al `<div>` del slot `end` en `topbar.tsx:46`, igualándolo a los otros
dos slots. No arregla el desbordamiento por sí solo (D1), pero es lo que permite que el `UserMenu`
—que ya lleva `truncate max-w-48`— realmente encoja cuando el email es largo, en vez de empujar la
fila. Sin él, `min-width: auto` deja el `truncate` inerte dentro del flex.

`Brand` **no** se toca: con la disposición estrecha de D1 sobran 66 px en la composición más
apretada (`/tech`, `/cleaner`), así que no hace falta. Si la medición de R1 lo desmintiera, la
contingencia es `min-w-0 truncate` en el `<span>` de `brand.tsx:7`; se anota aquí para no
improvisarla, no para aplicarla por defecto.

Rechazado: aplicar ya el `truncate` a `Brand` — truncar el nombre del producto en una barra que
después de D1 tiene holgura es empeorar la marca sin ganancia medida.

#### Corrección: «none of them may shrink» era falso, y costó una violación de R3.1 (sección 6, 2026-08-31)

La frase de arriba —«no arregla el desbordamiento por sí solo (D1)»— y la de `topbar.tsx` que la
citaba —«the controls' own floor is ≥265px and none of them may shrink (D1)»— daban por hecho que
los cinco controles tienen suelo propio. **Cuatro lo tienen; uno no.** `ThemeSwitcher`,
`LocaleSwitcher`, el disparador del `Sheet` y el `UserMenu` llevan la utilidad `tap-target`
(`min-width: 44px`), que es lo que un ítem flex no puede encoger por debajo. `NotificationBell`
(`features/notifications/components/notification-bell.tsx`) llevaba solo `size="icon"`, o sea
`h-11 w-11`: eso fija una anchura *de partida*, y `min-width: auto` de un ítem flex resuelve al
tamaño min-content de su contenido — el icono de 16 px.

Consecuencia medida en Chromium por la guarda de §6, sobre el árbol ya arreglado y con las siete
composiciones dando «fits»:

| Composición | raíz a 360 px | campana |
|---|---|---|
| `/dashboard` | 360/360 — cabe | **42×44** |
| `/tech` | 360/360 — cabe | **22×44** |
| `/cleaner` | 360/360 — cabe | **25×44** |

Y el mismo punto **antes** del change (revertidos 4.3/4.4): la fila desborda (`scrollWidth` 481)
y la campana mide **44×44**. Así que el `min-w-0` de esta decisión no dejó el desbordamiento
«sin arreglar por sí solo»: lo **convirtió** en otra cosa — el slot encoge por debajo de su
contenido y el único control sin suelo absorbe la diferencia. Se cambiaba una violación de R1.1
por una de R3.1 («al menos 44 × 44 px en la disposición estrecha») y de R3.2 («SHALL NOT resolver
el desbordamiento reduciendo `tap-target`»), y ninguna prueba de jsdom podía verlo.

**Arreglo**: `tap-target` en el `Button` de `NotificationBell`, que es lo que ya hacen sus cuatro
hermanos y lo que `design-system-tokens.md:31` designa para esto. Una clase, sin cambio de
disposición. No era un fallo de este change solo: la campana nunca tuvo suelo, pero antes del
`min-w-0` nada podía comprimirla, así que el defecto estaba latente y este change lo activó.

**Y una corrección sobre la guarda, más importante que la del componente.** R1.1 se satisface de
dos maneras —reagrupando o encogiendo— y `scrollWidth <= clientWidth` lee exactamente igual en las
dos, así que una guarda de solo anchos **da verde sobre el defecto que acabamos de describir**: sus
28 casos pasaban con la campana a 22 px. La guarda medida de D6 lleva por eso un segundo bloque que
afirma el suelo de 44×44 sobre lo **renderizado**, no sobre los nombres de clase (que es lo que ya
pinan los tests de jsdom, y es otra afirmación distinta). Es la única forma de comprobar R3.1: jsdom
no hace layout, y un control puede llevar la clase y aun así estar aplastado por su padre flex.

### D6 — La guarda de R5 se mide en un navegador real: proyecto `browser` de Vitest, no aserción de jsdom

**Elegido (confirmado por el usuario en OQ-1, 2026-08-31):** un segundo proyecto de Vitest con `@vitest/browser` sobre
Chromium, un único fichero (`frontend/features/shell/components/topbar-overflow.browser.test.tsx`)
y un script propio (`npm run test:layout`), que renderiza las **seis** composiciones a 360×780 y
afirma `document.documentElement.scrollWidth <= clientWidth`, nombrando en el fallo la composición
y el ancho medido (R5.3).

El razonamiento es el que R5.2 pide por escrito. jsdom no hace *layout*: `scrollWidth` es siempre
0, así que una aserción de la suite actual **no mediría nada**, que es justo lo que ese criterio
prohíbe dar por bueno. Y una guarda puramente estructural (leer el fuente y comprobar que las
clases `sm:` están donde toca) puede pinar la *forma* pero no puede nombrar «el ancho medido».

Por qué el modo navegador de Vitest y no una suite E2E de Playwright: los tests de shell que ya
existen (`workspace-shell.test.tsx`) renderizan las shells asíncronas reales con los mismos mocks
de `next/navigation`, `@/lib/auth` y `next/headers`. Cambiar jsdom por Chromium reutiliza ese
arnés entero — **sin servidor, sin base de datos sembrada y sin pasar por el login**, que es la
fricción que `sdd/project.md` documenta y que haría inviable una E2E para tres pantallas
autenticadas. Y respeta el «Out of scope» del proposal: esto no es la suite E2E de
`hardening-release`, es un fichero.

Lo que cuesta, sin adornos:
- **Cuatro `devDependencies` nuevas** (corregido al implementar la sección 6; esta línea decía
  «dos», y el panel de seguridad señaló con razón que la mitad no declarada es justo donde entra
  un paquete con script de instalación):
  - `@vitest/browser` y `playwright` — las dos previstas.
  - `@vitest/browser-playwright` — Vitest 4 sacó el proveedor a su propio paquete, así que «la
    bandera playwright» de esta decisión se escribe hoy con tres nombres, no dos. Pide
    `vitest@4.1.11` exacto, de modo que el lockfile sube `vitest` de 4.1.10 a 4.1.11 — un parche,
    dentro del `^4.1.10` que `package.json` ya declaraba.
  - `@tailwindcss/cli` — «la CLI de Tailwind» que el punto siguiente da por disponible y que el
    proyecto no tenía (solo `@tailwindcss/postcss`).
  - **Lo que arrastran, revisado en vez de heredado**: de las 46 entradas nuevas del lockfile,
    todas con `integrity` y `resolved` en `registry.npmjs.org`, exactamente una es un paquete
    nuevo con `hasInstallScript: true` que corra en Linux: `@parcel/watcher@2.5.1`, transitivo de
    `@tailwindcss/cli`, que se ejecuta durante el `npm ci` de CI. Se acepta: la clase ya existía
    en el árbol (`unrs-resolver` y compañía), y el radio está acotado por las tres posturas que el
    workflow ya tiene escritas — `permissions: contents: read`, `persist-credentials: false` y el
    disparador `pull_request:` (no `pull_request_target:`), así que una ejecución desde un fork no
    ve secretos y lleva un token de solo lectura. (`playwright/node_modules/fsevents` también trae
    script, pero es `os: darwin` y no se instala en el runner.)
- El binario de Chromium: `npm exec --no -- playwright install --with-deps chromium`.
  **`npm exec --no --` y no `npx`**, que es como esta línea decía y como no debe copiarse:
  `npx` se baja el paquete del registro cuando no está en `node_modules`, y en CI el
  manifiesto lo controla el Pull Request sobre un `pull_request:` sin filtros de rutas, así
  que un PR que quitara `playwright` convertiría este paso —el que instala paquetes de
  sistema bajo el sudo sin contraseña del runner— en «baja la versión del día y ejecútala».
  `--no` usa el binario que `npm ci` dejó desde el lockfile, o falla. Corregido tras el panel
  de la sección 6; se deja escrito aquí porque esto es lo que releerá el próximo change que
  toque Playwright (las variantes de caché o de partir el job que este mismo apartado
  propone, o la suite E2E de `hardening-release`). El contenedor del
  frontend es `node:22-slim` (Debian) y el runner de CI es `ubuntu-latest`, así que instala
  limpio en los dos sitios; en Alpine no habría instalado.
- **El CSS tiene que ser real**, o la medición es ficción: un paso previo compila
  `app/globals.css` con la CLI de Tailwind a un fichero que el test importa. Si esto se salta, la
  guarda mide un DOM sin estilos y siempre pasa — el modo exacto de fallo que R5.2 nombra.
- `vitest.config.ts` pasa a declarar dos proyectos (`node`/jsdom y `browser`) para que el
  `npm test` de hoy no arrastre Chromium.
- Un paso nuevo en `.github/workflows/frontend-tests.yml`, en el job `frontend-tests` que ya
  existe, con su fila en la tabla de «Consolidar resultados».

**Además**, y esto sí es barato, una guarda estructural en `frontend/test/topbar-overflow.test.ts`
siguiendo el patrón de `test/theme-client-state.test.ts`: fija la **forma exacta y los ficheros en
alcance**, no una lista de nombres prohibidos que cualquiera sortea renombrando.
Concretamente afirma que (1) los tres ficheros de shell autenticada y `(authenticated)/layout.tsx`
no montan `ThemeSwitcher`/`LocaleSwitcher` directamente, sino a través de
`AuthenticatedTopbarActions`/`TopbarPreferences`; (2) `topbar-preferences.tsx` esconde su rama
ancha con `hidden`/`sm:hidden` y **no** con `invisible`, `opacity-0` ni `sr-only` (R4.2); (3) el
disparador lleva `tap-target` (R3.1). Es complemento, no sustituto: no mide anchos.

Rechazado: **`@playwright/test` contra la app levantada** — exige `make up`, base sembrada y
recorrer el login por clic (la sesión vive en memoria, `sdd/project.md`), y es exactamente la
infraestructura que el proposal deja a `hardening-release`.
Rechazado: **test aritmético de presupuesto en jsdom** (sumar anchos mínimos declarados en una
tabla) — es una aserción sobre números escritos a mano, no sobre la página; se rompe sola en
cuanto alguien cambia un `gap` y no la actualiza, y R5.2 desaconseja precisamente eso.
Rechazado: **aplazar R5 a `hardening-release`** — incumple R5.1 tal y como está escrito; si el
usuario lo prefiere, hay que enmendar el proposal y dejar entrada en `BLOCKED.md` (OQ-1, opción C).

### D7 — Breakpoint: `sm` (640 px)

**Elegido:** la disposición completa vuelve en `sm:` (≥640 px), el token de Tailwind sin
personalizar.

R1.3 exige que no haya desbordamiento en **todo** el rango entre 360 px y el ancho en el que la
barra vuelve a su disposición completa, así que el breakpoint tiene que estar por encima del ancho
que la disposición completa necesita de verdad. Ese ancho es ~547 px en la composición más cara
(`/tech`: 32 + `Brand` 90 + 12 + 12 + `end` 265 con el `UserMenu` a ~180 px de email truncado).
640 deja ~93 px de margen sobre esa cifra; 768 (`md`) sería más holgado pero mandaría a la barra
estrecha tabletas enteras en vertical, donde el espacio sobra.

Elegir `sm` no colisiona con nada: `TabletNavTrigger` aparece en `md` y `Breadcrumbs` sustituye a
`PageTitle` en `md`, así que entre 640 y 767 la barra completa convive con el `start` más barato.

La cifra de 547 px es predicción; la verificación de R1.3 barre el rango 360→640 y la confirma. Si
la medición mostrara que la disposición completa no cabe a 640, el breakpoint sube a `md` — es un
cambio de una clase en un fichero.

Rechazado: `md` (768 px) — barra estrecha en tabletas que tienen sitio de sobra.
Rechazado: un breakpoint a medida (p. ej. `min-[560px]`) — ajusta más fino a costa de introducir
un valor mágico donde el resto del shell usa los tokens de Tailwind.

#### Medición real (tarea 7.5, 2026-09-01) — la cifra son 664 px, no ~547; el breakpoint se queda en `sm`

Chromium contra el stack de este worktree (`PORT_OFFSET=60`), sobre `/tech` autenticada, leyendo el
`<header>` a siete anchos y barriendo además 360→640 de 4 en 4 px (71 anchos) y 360→700 de 1 en 1
(341 anchos). Ningún ancho desborda la raíz: `scrollWidth <= clientWidth` en todos.

**El traspaso de rama cae exactamente donde `sm` lo pone**, y las dos ramas nunca coexisten en el
árbol de accesibilidad: disparador del `Sheet` visible en 360..639, disposición ancha desde 640;
cero anchos con las dos, cero anchos con ninguna.

**Lo que la disposición ancha necesita de verdad son 664 px**, medidos donde nada la comprime
(ventana a 1200 px): `px-4` 32 + slot `start` 215 + slot `end` 417. La predicción de ~547 px de
arriba **era falsa por 117 px**, y por dos motivos que la aritmética no tenía: el slot `end` ancho
mide 417 y no 265 (el `UserMenu` se queda en 152 px, pero el grupo de tema son 136 y el `Separator`
con su `mx-1` suma 17), y el `start` mide 215 y no 102 porque el `PageTitle` de `TechnicianShell`
ocupa sus 112 px cuando puede.

**Y aun así el breakpoint se queda en `sm`**, porque los 664 px no son un suelo duro: a 640 px
—el primer ancho de la rama ancha— la composición cumple R1.1 (`rootOverflow` 0) y **los seis
controles están a su tamaño completo**, ninguno por debajo de 44×44. Lo que cede son 12 px de
**texto que ya trunca por diseño**: el `PageTitle` («Mis incidencias», 112 px de contenido en 100
de caja) y el email del `UserMenu` (140 en 128). A 664 px el recorte es de 4 px y desde 700 px es
cero. Eso no es «la disposición completa no cabe» en el sentido que OQ-2 vigila —que era una barra
rota o controles encogidos—, así que la condición para subir a `md` no se cumple y **no se sube**.

Registrado en vez de silenciado, que es lo que OQ-2 pide: `md` (768 px) **eliminaría** ese recorte
de 12 px, porque 664 ≤ 768. El precio sigue siendo el que D7 rechazó — la barra estrecha en
tabletas enteras en vertical — y el recorte que compra es de 12 px sobre un texto que a 360 px
recorta 71. Si algún día se juzga inaceptable, subir el breakpoint sigue siendo un cambio de una
clase en un fichero.

Un dato para que nadie lo lea como compresión: `NotificationBell` reporta 4 px de desbordamiento de
tinta **a todos los anchos, incluido 1200**. No depende del ancho: es el badge de no leídas, que
está posicionado en absoluto y sobresale de la caja de 44×44 del botón. Preexistente a este change.


### D8 — Etiquetas nuevas: dos claves en `navigation`, añadidas al final y sin reordenar

**Elegido:** `navigation:topbarPreferences.trigger` (nombre accesible del disparador, «Preferencias»
/ «Preferences») y `navigation:topbarPreferences.title` (título del `Sheet`), en
`frontend/locales/es/navigation.json` y `frontend/locales/en/navigation.json`. El `Sheet` reutiliza
la clave existente `navigation:closeMenu` para su botón de cierre, como hace `more-menu.tsx:37`.

El icono del disparador es `Settings2` de `lucide-react`, **no** `EllipsisVertical`: el «…» ya
significa «más destinos» en la navegación inferior (`more-menu.tsx`), y reutilizarlo para
preferencias confundiría dos cosas distintas en la misma pantalla.

La coordinación que el proposal pide se respeta al pie: claves **añadidas** al final del objeto,
cero reordenación, para que el merge con `guest-portal-messaging` y
`blocked-transition-response-ids` sea trivial.

Rechazado: reutilizar `navigation:more` — dice «Más» y aquí significa «Preferencias»; en `en` la
divergencia sería aún más visible.

### D9 — Las dos instancias del `ThemeSwitcher` coinciden porque leen el atributo de `<html>`, no un store

**Elegido:** `aria-pressed` deja de salir de un `useState` por instancia y pasa a derivarse del
atributo `data-theme` de `document.documentElement`, suscrito con
`useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)` sobre un `MutationObserver`
acotado a ese atributo. Un hook nuevo, `frontend/lib/theme/use-theme-preference.ts` (cliente):

```ts
/** La preferencia elegida: `light` | `dark` | `system`. `system` es la AUSENCIA del atributo. */
function useThemePreference(initial: Theme | null): Choice
//  getServerSnapshot → choiceOf(initial)         (primer pintado y hidratación)
//  getSnapshot       → choiceOf(root.dataset.theme ?? null)
//  subscribe         → MutationObserver({ attributes: true, attributeFilter: [THEME_ATTRIBUTE] })
```

Por qué el atributo de `<html>` y no otra cosa: **ya es la autoridad**.
`design-system-tokens.md:22` manda resolver el tema en el servidor y escribir ese atributo desde
`app/layout.tsx` precisamente para que el primer pintado sea correcto, y `theme-switcher.tsx:80-87`
ya lo escribe y lo borra al cambiar la preferencia. Suscribirse a él no inventa una segunda fuente
de verdad: hace que las N instancias montadas lean la que ya existe. Y no es «leerlo solo en el
cliente», que es lo que `:23` prohíbe: `getServerSnapshot` devuelve el `initial` del servidor, así
que la hidratación arranca del valor del servidor y no puede desajustarse — `initial` sale de
`getServerTheme()`, que lee el mismo cookie con el que `app/layout.tsx` escribió el atributo.

El `useState` de `requested` **se queda**, pero cambia de papel: ya no describe qué botón está
pulsado, solo dispara el efecto que escribe el cookie y el atributo. La secuencia pasa a ser
clic → `setRequested` → efecto escribe cookie + atributo → el observer notifica a **todas** las
instancias → `aria-pressed` coincide en las dos. La mutación sigue ocurriendo en un efecto y nunca
durante el render, que es lo que `design-system-tokens.md` exige.

Coste real: un fichero nuevo de ~30 líneas en `lib/theme/` y ~6 líneas menos en
`theme-switcher.tsx`. No añade dependencias (`useSyncExternalStore` es de React) y no toca el
comportamiento visible de un solo `ThemeSwitcher`, que es el caso de hoy.

#### Tres cosas que aparecieron al implementarlo (sección 2, 2026-08-31)

Se anotan aquí porque las tres son consecuencia de esta decisión y ninguna es evidente leyéndola.

1. **`requested` tiene que ser un objeto, no el valor.** «`requested` se queda solo como
   disparador del efecto» es exactamente lo correcto, pero un `useState<Choice>` no *dispara*:
   `setRequested("dark")` cuando ya vale `"dark"` no cambia el estado, así que no hay render ni
   efecto. Con una sola instancia eso era invisible (nada más podía mover el atributo); con dos es
   alcanzable y silencioso — pide «oscuro» en la barra ancha, «claro» en el desplegable, «oscuro»
   otra vez en la ancha, y el documento se queda en «claro» después de un clic que decía lo
   contrario. El estado pasa a ser `{ choice: Choice } | null`, un objeto nuevo por clic. Tiene su
   caso en `theme-switcher.test.tsx`, verificado al revés: falla contra la versión con el valor
   desnudo.
2. **`getServerSnapshot` no se ejecuta en un `render` de cliente.** Sólo lo usan el render de
   servidor y la hidratación, así que una instancia montada reporta **el atributo**, no `initial`.
   No es un agujero —`app/layout.tsx` escribe `data-theme={theme ?? undefined}` desde el mismo
   `getServerTheme()` que produce `initial`, así que en la app siempre coinciden— pero sí obliga a
   que los tests que significan «el servidor dijo X» pongan el atributo junto al prop. `initial`
   presente sin su atributo es un estado que la app no renderiza nunca.
3. **Las mutaciones del atributo en los tests van en un `act` asíncrono**, y la limpieza va en
   `beforeEach` y no en `afterEach`: el `MutationObserver` entrega su callback en un microtask
   (un `act` síncrono vuelve antes), y limpiar el atributo después de un test lo hace con el árbol
   todavía montado, lo que dispara el aviso de `act` de React.
4. **`getServerSnapshot` no lo cubría ningún test, y eso hacía la mitad del mecanismo
   indemostrable** (hallazgo del panel de QA, aceptado). Consecuencia del punto 2: si todo se monta
   en cliente, `getServerSnapshot` se ejecuta **cero** veces, así que las aserciones que *parecían*
   fijar «`initial` manda en el primer pintado» sólo veían a `getSnapshot` leer el atributo que el
   propio test había puesto. Cambiar `useThemePreference(initial)` por
   `useThemePreference(null)` —perder el prop del servidor— pasaba las 39 pruebas del alcance, y en
   un render de servidor real habría sembrado «system» para una visitante con cookie: el parpadeo
   del control que `design-system-tokens.md` evita resolviendo el tema en el servidor. Se cierra con
   `renderToString`, que es lo único que ejecuta `getServerSnapshot`: tres casos en
   `use-theme-preference.test.tsx` (incluida una hidratación con `hydrateRoot` que exige consola
   limpia) y tres en `theme-switcher.test.tsx`, con el atributo puesto **al contrario** del prop
   para que sólo una de las dos fuentes pueda hacerlos pasar. Verificado al revés: con el prop
   perdido, fallan exactamente esos casos y ningún otro.

Rechazado: **un emisor/store a nivel de módulo en `lib/theme/`** — funcionaría, pero «cualquier
store de cliente» está prohibido con esas palabras en `:23`, y discutir si un módulo con
suscriptores cuenta como store es una discusión que no hay que tener cuando el atributo del DOM
sirve igual y es la autoridad designada.
Rechazado: **sondear el cookie** — `document.cookie` no es observable; habría que hacer *polling*.
Rechazado: **`router.refresh()` dentro del `ThemeSwitcher`** (lo que hace `LocaleSwitcher`) — es un
viaje al servidor por un cambio puramente local, y `design-system-tokens.md` pide aplicar el tema
«inmediatamente sin recargar la página».

**Esto reabre `sdd/specs/design-system-tokens.md`**, que el proposal daba por intocada. El SHALL
que gana: la preferencia activa que comunica `aria-pressed` SHALL derivarse del atributo de `<html>`
—sembrada por el valor del servidor en la hidratación— de modo que cualquier número de instancias
montadas del control coincida, sin store de cliente. Hoy la spec describe el `aria-pressed` sin
decir de dónde sale, y por eso una instancia duplicada podía romperlo en silencio. Lo escribe
`/sdd:archive`, como todas las specs vivas.

### D10 — Requisitos sin implicación de diseño

Se enumeran para cumplir el mandato de cubrir todos los requisitos del proposal:

- **R2.3** (el `UserMenu` conserva su `AlertDialog` y la secuencia
  `logout → router.replace("/") → router.refresh()`): sin implicación. D1 deja el `UserMenu` en la
  barra en las dos disposiciones, así que su fichero no se toca. La secuencia pertenece a
  `frontend-auth-session` y sigue intacta por construcción.
- **R3.3** (seguir satisfaciendo `design-system-tokens.md:31`, `:45` y `frontend-foundation.md:28`):
  sin implicación propia. Ningún control cambia de tamaño ni de variante; el único elemento nuevo
  con superficie táctil es el disparador, que nace con `tap-target`.
- **R1.4** (no romper lo que no estaba roto): sin implicación de mecanismo, es una obligación de
  verificación. D0 la convierte en trabajo concreto: las cuatro composiciones «sin medir» se miden
  antes y después.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Shell — contenedor | `frontend/features/shell/components/topbar.tsx` | `min-w-0` en el `<div>` del slot `end` (D5); el `end` por defecto pasa a ser `<TopbarPreferences initial={theme} />` (D0/D3) |
| Shell — nuevos | `frontend/features/shell/components/topbar-preferences.tsx` **(nuevo)** | Server Component; las dos ramas responsive (D3, D4) |
| Shell — nuevos | `frontend/features/shell/components/topbar-overflow-sheet.tsx` **(nuevo)** | `"use client"`; disparador `tap-target` + `Sheet side="bottom"` con `ThemeSwitcher`, `Separator` y `LocaleSwitcher` (D2) |
| Shell — nuevos | `frontend/features/shell/components/authenticated-topbar-actions.tsx` **(nuevo)** | Server Component; `TopbarPreferences` + `NotificationBell` + `UserMenu`, sustituye el fragmento triplicado (D3) |
| Shell — consumidores | `workspace-shell.tsx`, `cleaner-shell.tsx`, `technician-shell.tsx` | El `end` pasa a `<AuthenticatedTopbarActions profile={…} theme={theme} />`; se van los cinco imports de controles de cada uno |
| App | `frontend/app/(authenticated)/layout.tsx` | Sin cambio funcional: sigue con `UserMenu` solo (cabe, D0). Solo entra en el censo de verificación |
| Tema — coherencia | `frontend/lib/theme/use-theme-preference.ts` **(nuevo)** | Hook de cliente: `useSyncExternalStore` + `MutationObserver` sobre el atributo de `<html>`, sembrado con el `initial` del servidor (D9, R4.4) |
| Tema — coherencia | `frontend/features/shell/components/theme-switcher.tsx` | `choice` deja de derivarse de `requested` y pasa por el hook; `requested` queda solo como disparador del efecto que escribe cookie + atributo (D9) |
| Tema — tests | `frontend/features/shell/components/theme-switcher.test.tsx`, `frontend/test/theme-client-state.test.ts` | Caso nuevo: dos instancias montadas, clic en una, `aria-pressed` coincide en las dos (R4.4). La guarda de `test/theme-client-state.test.ts` prohíbe el tema en cualquier store y hay que comprobar que el hook nuevo no la dispara |
| i18n | `frontend/locales/{es,en}/navigation.json` | Dos claves nuevas al final, sin reordenar (D8) |
| Tests — componente | `frontend/features/shell/components/topbar-overflow-sheet.test.tsx` **(nuevo)** | Testing Library: el desplegable abre, los dos controles están dentro con su nombre accesible, `Escape` cierra y devuelve el foco (R2.1, R2.2) |
| Tests — shells | `workspace-shell.test.tsx`, `public-shell.test.tsx`, `field-public-guest-shell.test.tsx`, `shell-frame.test.tsx` | **Sin cambios: medido el 2026-08-31 (tarea 4.5), los cuatro ficheros pasan intactos — 31 pruebas.** La predicción de que harían falta `within(...)` era falsa; el porqué, en la fila corregida de la tabla de riesgos |
| Tests — guarda estructural | `frontend/test/topbar-overflow.test.ts` **(nuevo)** | Forma exacta y ficheros en alcance (D6) |
| Tests — guarda medida | `frontend/features/shell/components/topbar-overflow.browser.test.tsx` **(nuevo)** | Seis composiciones a 360×780 en Chromium (D6) |
| Config de test | `frontend/vitest.config.ts`, `frontend/package.json` | Dos proyectos (`node`, `browser`), scripts `test:layout` y `build:layout-css`, cuatro `devDependencies` (D6) |
| CI | `.github/workflows/frontend-tests.yml` | Paso nuevo en el job `frontend-tests` + fila en el resumen (D6) |
| Specs (los escribe `/sdd:archive`) | `sdd/specs/frontend-foundation.md` | Enmendar el SHALL de la línea 25 (la composición fija gana su disposición estrecha), ampliar el de la línea 23 (los tramos responsive dejan de ser solo del `WorkspaceShell`), y **añadir** la garantía que hoy no existe: ninguna superficie desborda horizontalmente a 360 px |

Y una fila más, que el proposal no preveía:

| Specs (los escribe `/sdd:archive`) | `sdd/specs/design-system-tokens.md` | **Añadir** un SHALL: la preferencia que comunica `aria-pressed` se deriva del atributo de `<html>` —sembrada por el valor del servidor en la hidratación— de modo que cualquier número de instancias montadas del control coincida, sin store de cliente (D9) |

Los 44 px de esa spec (`:31`, `:45`) **no cambian**: R3 los defiende y este diseño los respeta sin
tocarlos. El proposal preveía reabrirla solo si la garantía de 44 px y el arreglo no pudieran
coexistir; D1 demuestra que coexisten con 66 px de holgura en el peor caso. Se reabre por otra
razón —la coherencia entre instancias de D9— y esa decisión la tomó el usuario al cerrar OQ-3, no
el design.

## Data & interfaces

Ninguna. No hay cambios de esquema, de contrato de API, de eventos ni de variables de entorno.
Este change no toca el backend ni `frontend/lib/api/`.

Interfaces internas nuevas (solo TypeScript, dentro de `features/shell/` y `lib/theme/`):

```ts
// topbar-preferences.tsx — Server Component
function TopbarPreferences(props: { initial: Theme | null }): JSX.Element

// topbar-overflow-sheet.tsx — "use client"
function TopbarOverflowSheet(props: { initial: Theme | null; className?: string }): JSX.Element

// authenticated-topbar-actions.tsx — Server Component
function AuthenticatedTopbarActions(props: { profile: ShellProfile; theme: Theme | null }): JSX.Element

// lib/theme/use-theme-preference.ts — "use client" (D9)
function useThemePreference(initial: Theme | null): Theme | "system"
```

`useThemePreference` vive en `lib/theme/` y no en `features/shell/` porque la dirección de
dependencias del proyecto es `app → features → components / lib`: `lib/` no puede importar
`features/`, y el hook es del mecanismo del tema, no del shell. Fichero aparte de
`lib/theme/server.ts`, que es `server-only`.

Ninguno se exporta por las puertas públicas del feature: `features/shell/index.ts` es
**client-safe por contrato** y `features/shell/server.ts` publica solo las cinco shells y
`routeMetadata`. Los tres componentes son internos, consumidos por sus vecinos del mismo
directorio y por `app/(authenticated)/layout.tsx`, que ya hoy hace deep-import legal de
`features/shell/components/` (la regla `no-restricted-imports` solo gobierna ficheros **bajo**
`features/`).

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| ~~**Los tests de shell existentes se vuelven ambiguos.** jsdom ignora las media queries, así que `ThemeSwitcher` y `LocaleSwitcher` aparecerán **dos veces** en el DOM renderizado.~~ **Riesgo descartado por medición (tarea 4.5, 2026-08-31).** | La premisa era cierta —jsdom no aplica media queries— pero la conclusión no: Radix **desmonta el contenido del `Sheet` mientras está cerrado** (`components/ui/sheet.tsx` no usa `forceMount`, y `topbar-overflow-sheet.test.tsx` lo fija con «mounts nothing while closed»). Con el desplegable cerrado —que es como se renderiza en un test— hay **una sola** instancia de cada control en el DOM. Los cuatro ficheros pasan sin tocar: 31 pruebas en verde, y las consultas sin acotar de `workspace-shell.test.tsx:161,165` son la prueba, porque `getByRole` **lanza** si encuentra más de un elemento |
| ~~**El chequeo `axe` de los tests de shell puede marcar el nombre accesible duplicado**, porque jsdom no aplica `display:none` de una media query.~~ **No ocurre, por la misma razón que la fila anterior** (medido en 4.5): con el `Sheet` cerrado no hay segundo nombre que duplicar, y los tres chequeos `axe` de estos ficheros pasan sin acotar. Que R4.2 se cumpla a 360px reales lo sigue demostrando la guarda medida de D6, no jsdom |
| **La guarda de D6 mide sin CSS y pasa siempre.** Es el fallo silencioso que convertiría R5 en teatro. | El paso de compilación de Tailwind es parte de la tarea, y la guarda se valida **al revés primero**: se comprueba que falla contra el `topbar.tsx` de hoy antes de dar por buena la versión que pasa. Sin esa demostración, la tarea no está hecha |
| **Chromium en CI alarga el job.** Hoy tarda ~1m30-2m15 y el propio workflow avisa de que ese margen es su razón de no partirse en tres jobs. | Un solo fichero, un solo navegador, sin servidor: la instalación del binario domina y se cachea con `actions/setup-node` mal, así que se mide el coste real en la verificación y, si duele, la decisión de partir el job tiene precedente escrito (`backend-tests.yml`) |
| **El desplegable tapa contenido en pantallas muy bajas** (un `Sheet` inferior con tres botones de 44 px + título). | `side="bottom"` ya limita la altura al contenido; el contenido son dos filas. Se comprueba en la pasada a 360×780 |
| **Regresión en `/` (landing).** `PublicShell` es la única composición con slot `center`, y es la que peor sale en D0. | Entra explícitamente en el censo de las seis; se mide antes y después (R1.4) |
| **D9 toca un componente de otra spec.** `ThemeSwitcher` pertenece a `design-system-tokens`, y cambiarle de dónde sale `aria-pressed` puede romper `theme-switcher.test.tsx` y la guarda `test/theme-client-state.test.ts`, que prohíbe el tema en cualquier store con una expresión deliberadamente amplia. | La guarda se lee **antes** de escribir el hook, no después de que falle: su propio comentario avisa de que la primera versión era escapable de tres formas y las nombra. Si el hook la dispara, la discusión es si `useSyncExternalStore` sobre el DOM cuenta como store — y D9 elige el atributo de `<html>` precisamente para no tener que tenerla |
| **Desajuste de hidratación en D9.** Si `getServerSnapshot` y la primera lectura del DOM discreparan, React avisaría en consola. | No pueden discrepar: `initial` sale de `getServerTheme()`, que lee el mismo cookie con el que `app/layout.tsx` escribió el atributo. Se comprueba en la pasada de navegador, que es donde un aviso de hidratación se ve |
| **Colisión de merge en `navigation.json`** con `guest-portal-messaging` y `blocked-transition-response-ids`. | D8: claves añadidas, cero reordenación |
| **La verificación en navegador se aparca citando el aviso de `PORT_OFFSET`.** Ya pasó dos veces, una de ellas en `tech-app`. | `sdd/project.md` documenta que el aviso es falso para `next dev` con `PORT_OFFSET` (medido el 2026-08-29) y da la salida escrita (`npm run build` + `next start` en contenedor aparte) para cuando muerde. No vale citarlo para no mirar |

No hay riesgo de migración, de rendimiento en servidor ni de compatibilidad hacia atrás: el cambio
es de composición de marcado en el cliente.

## Open questions

**Las cuatro se resolvieron con el usuario en el gate de `/sdd:design`, el 2026-08-31.** Se dejan
escritas con su respuesta porque las alternativas rechazadas son parte del registro: quien lea esto
en seis meses tiene que poder ver qué se descartó y por qué.

### OQ-1 — ¿Cuánta infraestructura compramos para la guarda de R5? → **(A) proyecto `browser` de Vitest**

R5.1 pide una comprobación automatizada y R5.3 pide que nombre «el ancho medido». Hoy no hay
navegador en la suite, así que había tres salidas y solo una cumple R5 tal y como está escrito.

**Resuelta: (A)**, el mecanismo de D6 — proyecto `browser` de Vitest sobre Chromium, un fichero,
las seis composiciones a 360×780. Con ello el change **crece por encima de su `size: S`**: dos
`devDependencies`, el binario de navegador en CI y en el contenedor de dev, un paso de compilación
de Tailwind y `vitest.config.ts` partido en dos proyectos. Queda asumido, y `/sdd:tasks` lo
dimensiona como sección propia.

Rechazado: **(B) solo la guarda estructural** — barata y honesta sobre lo que hace, pero no detecta
el defecto de R1, solo que alguien deshizo la forma del arreglo; habría exigido enmendar R5.3.
Rechazado: **(C) aplazar a `hardening-release`** — incumple R5.1 tal y como está escrito y dejaría
el defecto sin guarda en el árbol.

La guarda estructural de D6 **no se cae con esta respuesta**: sigue siendo complemento de la medida,
porque pina la forma (nadie monta los controles directamente, la rama ancha se esconde con `hidden`
y no con `sr-only`, el disparador lleva `tap-target`) y eso la medición no lo dice.

### OQ-2 — ¿Breakpoint `sm` (640 px) o `md` (768 px)? → **`sm`**

**Resuelta: `sm` (640 px)**, como recomendaba D7. La disposición completa necesita ~547 px en la
composición más cara (`/tech`), así que quedan ~93 px de margen; y no colisiona con nada, porque
`TabletNavTrigger` aparece en `md` y `Breadcrumbs` sustituye a `PageTitle` en `md`.

Rechazado: `md` (768 px) — barra estrecha en tabletas en vertical, que tienen sitio de sobra.

Los ~547 px son predicción: la verificación de R1.3 barre el rango 360→640 y la confirma. Si la
medición dijera que la disposición completa no cabe a 640, el breakpoint sube a `md` — una clase en
un fichero, y en ese caso hay que decirlo en el registro en vez de cambiarlo en silencio.

**Medido en la tarea 7.5 (2026-09-01): eran 664 px, no ~547 — y `sm` se mantiene igual.** La
predicción se quedó corta por 117 px (el detalle, en §D7 → «Medición real»). Pero la condición que
esta OQ puso para subir a `md` era «la disposición completa no cabe a 640», y a 640 px sí cabe:
la raíz no desborda y los seis controles están a su tamaño completo, ninguno por debajo de 44×44.
Lo único que cede son 12 px de texto que ya trunca por diseño, cero desde 700 px. Así que la
respuesta no cambia, y queda dicho en el registro en vez de en silencio, que es lo que esta OQ
exigía en cualquiera de los dos sentidos.

### OQ-3 — El botón de tema desfasado al ensanchar la ventana → **se arregla aquí**

**Resuelta: arreglarlo en este change**, contra la recomendación de aceptarlo y documentarlo. El
mecanismo está en **D9** (derivar `aria-pressed` del atributo de `<html>` con `useSyncExternalStore`
+ `MutationObserver`, sembrado por el valor del servidor), y tiene dos consecuencias que ya están
propagadas:

1. **`proposal.md` gana R4.4**, que es el requisito que obliga a la coherencia entre instancias.
   Sin bajarlo al proposal, la spec viva habría acabado con un `SHALL` que nadie encargó.
2. **`sdd/specs/design-system-tokens.md` se reabre** para ganar un SHALL — el que dice de dónde sale
   la preferencia activa. El proposal la daba por intocada; su sección «Affected specs» ya está
   corregida, distinguiendo lo que no cambia (los 44 px de `:31` y `:45`) de lo que sí.

Rechazado: **aceptarlo y documentarlo** — era la recomendación del design por coste, no por
corrección; el usuario decidió pagarlo.
Rechazado: **change propio contra `design-system-tokens`** — habría dejado este change entregando
a sabiendas un `aria-pressed` que miente en un caso alcanzable.
Rechazado dentro de D9: un store a nivel de módulo (`:23` lo prohíbe con esas palabras), sondear el
cookie (no es observable) y `router.refresh()` en el `ThemeSwitcher` (viaje al servidor por un
cambio local).

### OQ-4 — ¿Confirmas el reparto de D1? → **sí**

**Resuelta: sí.** La campana y el `UserMenu` se quedan en la barra en las dos disposiciones; el
tema y el idioma pasan al desplegable. Suelo de 148 px en el slot `end` y 66 px de holgura en la
composición más apretada.

Rechazado: **los cinco al desplegable** — daba 132 px de suelo en vez de 148, a cambio de que el
badge de no leídas dejara de verse en la app de campo.

## Roadmap candidates found on the way

Tres cosas que este change midió, decidió no arreglar y deja escritas para que no se pierdan al
archivar. Ninguna es alcance suyo, y las tres tienen su razón.

1. **El `Sheet` abierto sobrevive a su propia media query.** Si se ensancha la ventana por encima de
   640 px con el desplegable de preferencias abierto, en pantalla quedan **dos** juegos visibles de
   los controles de tema e idioma (el del cajón y el de la barra ancha, que acaba de aparecer), y al
   cerrarlo el foco se va a `<body>` porque su disparador es ya `display:none`. Medido en la tarea
   7.7. **R4.2 se cumple igualmente** —el árbol de accesibilidad enseña una sola instancia, porque
   Radix marca `aria-hidden="true"` los hermanos de `document.body`—, así que es un defecto
   cosmético y de gestión de foco, no de accesibilidad.

   Por qué no se arregla aquí: cerrar el `Sheet` cuando la media query deja de aplicar exige
   observar el viewport desde JavaScript (`matchMedia`), y **R4.1 prohíbe exactamente eso** a este
   change («mediante media queries de CSS, nunca mediante detección de viewport en JavaScript»).
   Levantar esa prohibición es una decisión de diseño que merece su propio proposal.

2. **El botón de cierre del `Sheet` mide 16×16.** La `X` de `components/ui/sheet.tsx` es una
   superficie táctil de 16 px en las **seis** superficies que montan un `Sheet`, y lo era desde
   antes de este change. La sección 6 la midió, decidió que es chrome de la primitiva y no «un
   control que pasa al desplegable» (R3.1), y la exentó de la guarda medida por
   `data-slot="sheet-close"` — una exención acotada a ese slot para que no se contagie. Darle un
   objetivo táctil real es un cambio en la primitiva que toca esas seis superficies, no esta.

3. **La marca aplastada en `/`.** `Brand` se comprime a 37 px de caja con 89 px de contenido en la
   landing a 360 px, solapándose con `MarketingNav`. Lo levantó la tarea 1.1 y está en §D0: es
   desbordamiento de tinta dentro de un slot con `min-w-0`, no desbordamiento horizontal de la
   página, así que **no es lo que R1.1 mide** y el proposal lo manda anotar y no arreglar («Tocar el
   contenido de las pantallas», Out of scope). Este change lo mejora de lado —libera los 205 px que
   el slot `end` le robaba— pero no lo resuelve.
