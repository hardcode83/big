# Tasks: shell-topbar-overflow-360

Orden pensado para que el árbol quede sano al final de cada sección: la coherencia del
`ThemeSwitcher` (§2) entra **antes** de que nada duplique instancias (§4), y la guarda medida (§6)
llega cuando ya hay algo que medir. Las cifras de `design.md` (D0, D1, D7) son predicciones: §1 y
§7 son las que las confirman o las corrigen.

## 1. Línea base medida

- [x] 1.1 Levantar el stack de este worktree con `make up PORT_OFFSET=<n>` y medir las **seis**
  composiciones a 360×780 en un navegador real (`/` con `MarketingNav`, `/login`,
  `/guest/[token]`, `/welcome`, `/dashboard`, `/tech`, `/cleaner`), registrando
  `document.documentElement.scrollWidth` y `clientWidth` de cada una. Anotar el resultado en
  `design.md` §D0 si contradice su tabla aritmética (`PublicShell` en `/` se predice roto;
  `/login`, `/guest` y `/welcome` se predicen con holgura fina). Esto fija el «antes» que R1.4
  compara y cumple el mandato de R1.2 sobre las cuatro composiciones nunca medidas. Entrar y
  navegar **por clic** (la sesión vive en memoria) y usar `el.click()` en el DOM para esquivar el
  overlay de `next dev`; si la página se sirve pero no responde, caer al `npm run build` +
  `next start` que documenta `sdd/project.md` en vez de aparcar la medición. [R1.2, R1.4]

  **Medido el 2026-08-31** con `PORT_OFFSET=60` y `next dev` (la app hidrata; entrada por clic con
  los tres roles). Resultado y su tabla completa en `design.md` §D0 → «Medición real (tarea 1.1)»:
  las tres shells autenticadas desbordan (`/dashboard` 457/345, `/tech` 445/345, `/cleaner`
  465/345) y las **cuatro** restantes cumplen R1.1 hoy, incluida `/` — cuya predicción de D0
  («desborda ~421») era falsa, porque los slots `start`/`center` llevan `min-w-0` y se comprimen
  en vez de empujar la fila. Cifra de partida de la suite, para 7.1: **187 ficheros, 1942 tests**,
  todos en verde con `--maxWorkers=2`.

## 2. Coherencia del `ThemeSwitcher` entre instancias (D9) <!-- panel: PASS 2026-08-31 -->

Va primero porque §4 duplica ese control en el DOM y sin esto se entregaría un `aria-pressed` que
miente en un caso alcanzable.

- [x] 2.1 Leer `frontend/test/theme-client-state.test.ts` **antes de escribir el hook** (sus cuatro
  aserciones y el `MAY_NAME_THEME`), para diseñar contra la guarda y no descubrirla cuando falle.
  Comprobado que el mecanismo elegido no la dispara: sin `localStorage`/`sessionStorage`, sin
  `matchMedia`, sin lectura de `document.cookie`, sin store. [R4.4]
- [x] 2.2 `frontend/lib/theme/use-theme-preference.ts` **(nuevo)** + `use-theme-preference.test.ts`
  **(nuevo)**: hook de cliente `useThemePreference(initial: Theme | null): Theme | "system"` con
  `useSyncExternalStore` sobre un `MutationObserver` acotado al atributo `data-theme` de
  `document.documentElement`; `getServerSnapshot` devuelve el `initial` del servidor. Tests: dos
  suscriptores ven el mismo valor tras mutar el atributo; borrar el atributo da `"system"`; el
  observer se desuscribe al desmontar. [R4.4]

  Dos correcciones al escribirlo, las dos anotadas en `design.md` §D9: el fichero de test es
  `.test.tsx` (monta un componente, así que lleva JSX) y **cada mutación del atributo va en un
  `act` asíncrono** — el `MutationObserver` entrega su callback en un microtask, así que un `act`
  síncrono vuelve antes de que React se haya enterado. `initial` alimenta `getServerSnapshot`, que
  no se ejecuta en un `render` de cliente: los tests ponen el atributo junto al prop, que es el par
  que emite el servidor.
- [x] 2.3 `frontend/features/shell/components/theme-switcher.tsx`: `choice` deja de derivarse de
  `requested ?? choiceOf(initial)` y pasa por el hook; `requested` se queda **solo** como
  disparador del efecto que escribe cookie + atributo, sin cambiar esa secuencia ni sacarla del
  efecto. Caso nuevo en `theme-switcher.test.tsx`: dos instancias montadas, clic en una,
  `aria-pressed` coincide en las dos sin navegación ni recarga. [R4.4]

  **Un defecto encontrado al implementarlo y arreglado aquí** (`design.md` §D9): al dejar de
  derivar `choice` de `requested`, un clic repitiendo el valor que esta instancia ya había pedido
  deja de cambiar el estado y el efecto no vuelve a correr — alcanzable con dos instancias (pide
  «oscuro» aquí, «claro» en la otra, «oscuro» aquí otra vez) y silencioso. `requested` pasa a ser
  `{ choice }`, un objeto nuevo por clic. Tiene su caso, y se comprobó que **falla** contra la
  versión con el valor desnudo.

  **Hallazgo del panel de QA, aceptado y arreglado en la ronda de correcciones**: ningún test
  alcanzaba `getServerSnapshot`, así que perder el prop `initial` pasaba las 39 pruebas del alcance
  reintroduciendo el parpadeo del control. Cerrado con seis casos de `renderToString` (y una
  hidratación con `hydrateRoot`), detalle en `design.md` §D9 punto 4. Alcance de la sección:
  **45 pruebas en verde** (7 + 26 + 12).
- [x] 2.4 `frontend/test/theme-client-state.test.ts`: añadir `lib/theme/use-theme-preference.ts` y
  su test al `MAY_NAME_THEME` **con su razón escrita** (es el mecanismo del tema, no estado de
  cliente), y verificar que la aserción «the switcher receives the theme from the server and never
  reads it on the client» sigue pasando contra el `theme-switcher.tsx` nuevo. Ejecutar el fichero
  entero, no solo el caso nuevo. [R4.4]

## 3. Etiquetas y el desplegable de preferencias (D2, D8) <!-- panel: PASS 2026-08-31 -->

- [x] 3.1 `frontend/locales/es/navigation.json` y `frontend/locales/en/navigation.json`: dos claves
  nuevas `topbarPreferences.trigger` («Preferencias» / «Preferences») y `topbarPreferences.title`,
  **añadidas al final del objeto y sin reordenar nada** (coordinación del proposal con
  `guest-portal-messaging` y `blocked-transition-response-ids`). Nada de texto incrustado en el
  componente. [R2.4]
- [x] 3.2 `frontend/features/shell/components/topbar-overflow-sheet.tsx` **(nuevo, `"use client"`)**:
  disparador `Button size="icon" className="tap-target"` con el icono `Settings2` de `lucide-react`
  (`aria-hidden`) y `aria-label` desde `navigation:topbarPreferences.trigger`; `Sheet`
  `side="bottom"` con `closeLabel={t("closeMenu")}` y `SheetTitle` desde
  `topbarPreferences.title`, alojando `ThemeSwitcher initial={initial}`, un `Separator` y
  `LocaleSwitcher`. Acepta `className` para que §4 le pase `sm:hidden`. No usar
  `EllipsisVertical`: el «…» ya significa «más destinos» en `more-menu.tsx`. [R2.1, R2.2, R2.4,
  R3.1]
- [x] 3.3 `frontend/features/shell/components/topbar-overflow-sheet.test.tsx` **(nuevo)**: el
  disparador abre el desplegable; dentro están el `role="group"` «Tema» y el botón de idioma con
  **el mismo nombre accesible** que en la barra completa; `Escape` cierra y devuelve el foco al
  disparador; el disparador lleva `tap-target`. [R2.1, R2.2, R3.1]

  15 casos. Dos cosas que la implementación enseñó y quedan fijadas en el fichero: (1) mientras el
  `Sheet` está abierto, Radix marca `aria-hidden` todo lo que queda fuera del diálogo, así que el
  disparador **desaparece del árbol de accesibilidad** — la primera versión del test lo volvía a
  buscar por rol y fallaba con «Unable to find role="button"», que era el componente portándose
  bien. Se captura la referencia una vez, y ese `aria-hidden` gana caso propio porque es lo que
  impide que las dos instancias del `ThemeSwitcher` sean dos paradas alcanzables mientras el
  desplegable está abierto (apoya R4.2). (2) El chequeo `axe` se acota al diálogo: sobre todo el
  documento salta `region` contra el portal de los tooltips, que es una regla de estructura de
  landmarks y este es un test de componente sin landmarks — los landmarks se afirman en los tests
  de shell.

  Adelantado de 4.6 para no dejar el árbol en rojo entre secciones: `topbar-overflow-sheet.tsx` y
  su test ya están en el `MAY_NAME_THEME` de `test/theme-client-state.test.ts`, con su razón
  escrita (es `"use client"`, así que no puede apoyarse en «un Server Component no puede tener
  estado de cliente»: lo que la exime es que no guarda estado de tema ninguno).

  **Contención de host durante el panel de esta sección**, anotado porque afecta a lo que el panel
  pudo comprobar y no a lo que la sección hace: la máquina llegó a 34 contenedores y 6,5 de los
  7,65 GiB de Docker, con seis stacks de otras sesiones vivos. El revisor de QA no consiguió
  completar ninguna ejecución de vitest (3 × «Timeout waiting for worker», 2 × exit 137, 1 × fallo
  de `exec`) y el de i18n confirmó 13 de 15 casos antes de que lo mataran. La verificación válida es
  la medición propia hecha antes de que subiera la contención, con estos mismos ficheros ya en su
  estado final: `test/theme-client-state.test.ts` + `topbar-overflow-sheet.test.tsx` → **22 en
  verde** (7 + 15), más `typecheck` y `lint` limpios y `catalog-parity` 18/18. QA además reimplementó
  la lógica de la guarda en Node y en Python fuera de Docker y obtuvo cero infractores en las dos,
  lo que explica sus dos «fallos» como artefactos de contención. Para bajar la presión se pararon
  `worker` y `beat` **de este stack** (no del de nadie); hay que volver a levantarlos si algo
  necesita Celery.

## 4. Composición responsive del `Topbar` (D0, D3, D4, D5, D7) <!-- panel: PASS 2026-08-31 -->

**Verificación de la sección** (2026-08-31): alcance propio **9 ficheros, 101 pruebas en verde**
(`test/theme-client-state.test.ts`, los cuatro de shell, `topbar-overflow-sheet.test.tsx`,
`theme-switcher.test.tsx`, `locale-switcher.test.tsx`, `use-theme-preference.test.tsx`),
`typecheck` y `lint` limpios. Panel **7/7 PASS** con 0 hallazgos, y la puerta cerrada de
`scripts/reviewer_panel.py --phase run` en 0.

**Dónde se corrió, porque no es donde dice `sdd/project.md`**: la contención de host que dejó
parada esta sección seguía igual (35 contenedores, siete stacks vivos de otras sesiones, ~600 MiB
libres en la VM de Docker; `vitest` dentro del contenedor muere con 137 u OOM en todos los
intentos). En vez de parar el stack de nadie, se instalaron las dependencias **en el host**
(`npm ci` en `frontend/`, `node_modules/` está en `.gitignore`, y el volumen con nombre
`frontend_node_modules` tapa esa ruta dentro del contenedor, así que el entorno de Docker queda
intacto). La suite pasa de no arrancar a 8 s.

**Una divergencia host/contenedor que hay que conocer y que NO es de este change**: en el host
(Node 25) falla `features/dashboard/state/use-timeline-property-store.test.ts` con
`expected [ 'getItem', 'setItem', … ] to deeply equal []`. La causa está localizada:
`frontend/test/setup.ts` instala un `localStorage` de mentira —un objeto plano— cuando el `Storage`
de jsdom no es usable, y `Object.keys()` sobre ese objeto plano devuelve sus seis métodos propios.
El fichero está en `features/dashboard/`, que este change no toca, y en el contenedor (Node 22)
pasa. Consecuencia práctica: **7.1 se certifica en el contenedor**, no con esta cifra de host
(189 ficheros, 1976 pruebas, ese único fallo).

**Un caso límite que el panel levantó y conviene no perder** (lo vieron por separado el arquitecto
y QA, y los dos concluyeron lo mismo): `TopbarPreferences` pasa `sm:hidden` **solo al disparador**
del `Sheet`; el `SheetContent` va en un portal a `body` y no lleva media query. Así que si alguien
abre el desplegable a 360 px y **ensancha la ventana por encima de 640 px sin cerrarlo**, se ven a
la vez la rama ancha y el contenido del desplegable. R4.2 **no** se rompe, y por un mecanismo que
§3 ya fijó con un caso propio (`topbar-overflow-sheet.test.tsx:202-226`): el `Sheet` es un diálogo
modal, así que Radix marca `aria-hidden` todo lo que queda fuera y atrapa el foco mientras está
abierto, independientemente del ancho — la tecnología asistiva sigue viendo **una** instancia. Lo
que queda es cosmético (dos juegos de controles a la vista) más el retorno de foco a un disparador
que para entonces es `display:none`. Se comprueba en el navegador en **7.7**, que ya hacía ese
mismo gesto de ensanchar.

- [x] 4.1 `frontend/features/shell/components/topbar-preferences.tsx` **(nuevo, Server Component)**:
  rama ancha `<div className="hidden items-center gap-2 sm:flex">` con `ThemeSwitcher` +
  `Separator` + `LocaleSwitcher`, y `<TopbarOverflowSheet initial={initial} className="sm:hidden" />`.
  La selección es **solo** por media query de Tailwind (`display:none`); prohibido `invisible`,
  `opacity-0` o `sr-only`, que esconden a la vista pero no al lector de pantalla. Sin
  `"use client"`. [R1.1, R2.1, R4.1, R4.2, R4.3]
- [x] 4.2 `frontend/features/shell/components/authenticated-topbar-actions.tsx` **(nuevo, Server
  Component)**: `TopbarPreferences initial={theme}` + `NotificationBell profile` + `UserMenu`, que
  sustituye al fragmento hoy triplicado. El `UserMenu` no se toca: su `AlertDialog` y la secuencia
  `logout → router.replace("/") → router.refresh()` siguen intactas por construcción. [R2.1, R2.3,
  R4.3]
- [x] 4.3 `frontend/features/shell/components/topbar.tsx`: añadir `min-w-0` al `<div>` del slot
  `end` (para que el `truncate max-w-48` del `UserMenu` deje de ser inerte dentro del flex) y
  cambiar el `end` por defecto a `<TopbarPreferences initial={theme} />`, que es lo que arregla
  `PublicShell` y `GuestShell` (D0). `Brand` **no** se toca. [R1.1, R4.1, R4.3]
- [x] 4.4 `workspace-shell.tsx`, `cleaner-shell.tsx`, `technician-shell.tsx`: el `end` pasa a
  `<AuthenticatedTopbarActions profile={PROFILE} theme={theme} />` y se van los cinco imports de
  controles de cada fichero. [R1.1, R2.1]
- [x] 4.5 Absorber la ambigüedad que jsdom introduce (riesgo declarado en `design.md`, el punto de
  fricción más probable): en `workspace-shell.test.tsx`, `public-shell.test.tsx`,
  `field-public-guest-shell.test.tsx` y `shell-frame.test.tsx`, las consultas por nombre accesible
  que hoy asumen **una** instancia de `ThemeSwitcher`/`LocaleSwitcher` (p. ej.
  `getByRole("group", { name: "Tema" })`, `getByRole("button", { name: "Cambiar idioma a English" })`)
  pasan a acotarse con `within(...)` sobre la rama ancha. Si el chequeo `axe` marca el nombre
  duplicado —jsdom no aplica el `display:none` de una media query—, acotar la aserción a la rama
  visible; que R4.2 se cumpla de verdad lo demuestra la guarda medida de §6, no jsdom. [R1.4,
  R4.2]

  **No hizo falta tocar nada, y está medido, no supuesto** (2026-08-31): los cuatro ficheros pasan
  intactos, **31 pruebas en verde**, sin un solo `within(...)` nuevo. El riesgo que `design.md`
  llamaba «el punto de fricción más probable» partía de una premisa cierta —jsdom no aplica media
  queries— y una conclusión falsa: Radix **desmonta el contenido del `Sheet` mientras está
  cerrado** (`components/ui/sheet.tsx` no lleva `forceMount`), y cerrado es como se renderiza en un
  test. Así que en el DOM hay **una sola** instancia de cada control, la de la rama ancha.

  La prueba no es que pasen, es *por qué* pasan: `workspace-shell.test.tsx:161,165` consulta
  `screen.getByRole("button", { name: "Cambiar idioma a English" })` y
  `screen.getByRole("group", { name: "Tema" })` **sin acotar**, y `getByRole` lanza si encuentra
  más de un elemento — de haber dos instancias, esos dos casos serían los primeros en caer. Los
  tres chequeos `axe` (`workspace-shell.test.tsx:188`, `field-public-guest-shell.test.tsx:81,166`)
  tampoco marcan nombre duplicado. `shell-frame.test.tsx` no monta el `Topbar` real (recibe un
  `<div data-testid="topbar" />`), así que no podía verse afectado en ningún caso.

  Las dos filas de la tabla de riesgos de `design.md` quedan corregidas con este resultado, y la
  fila de «Tests — shells» de la tabla de ficheros afectados pasa a «sin cambios».
- [x] 4.6 `frontend/test/theme-client-state.test.ts`: la aserción
  `expect(topbar).toMatch(/<ThemeSwitcher\s+initial=\{theme\}/)` **deja de ser cierta** con 4.3, así
  que pasa a exigir `<TopbarPreferences initial={theme}` en `topbar.tsx` y
  `<ThemeSwitcher initial={initial}` en `topbar-preferences.tsx`, conservando lo que la aserción
  protege (que el valor viene del servidor y que `topbar.tsx` sigue sin `"use client"`). Añadir al
  `MAY_NAME_THEME`, con su razón, los ficheros nuevos que nombran el tema
  (`topbar-preferences.tsx`, `topbar-overflow-sheet.tsx`, `authenticated-topbar-actions.tsx` y sus
  tests). [R4.3, R4.4]

## 5. Guarda estructural: la forma del arreglo (D6, complemento)

- [x] 5.1 `frontend/test/topbar-overflow.test.ts` **(nuevo)**, siguiendo el patrón de
  `test/theme-client-state.test.ts` — forma exacta y ficheros en alcance, no una lista de nombres
  prohibidos que se sortea renombrando. Afirma que: (1) `workspace-shell.tsx`,
  `cleaner-shell.tsx`, `technician-shell.tsx` y `app/(authenticated)/layout.tsx` no montan
  `ThemeSwitcher`/`LocaleSwitcher` directamente, sino a través de `AuthenticatedTopbarActions` /
  `TopbarPreferences`; (2) `topbar-preferences.tsx` esconde su rama ancha con `hidden`/`sm:hidden`
  y **no** con `invisible`, `opacity-0` ni `sr-only`; (3) el disparador de
  `topbar-overflow-sheet.tsx` lleva `tap-target`; (4) cada ruta de su lista de alcance existe, para
  que la lista no pueda podrirse. Es complemento de la guarda medida, no sustituto: no mide anchos.
  [R3.1, R4.2, R5.2]

## 6. Guarda medida en navegador real (D6, OQ-1) <!-- panel: PASS 2026-08-31 -->

Esta sección es la que saca al change de su `size: S`, y OQ-1 lo dio por asumido.

**Verificación de la sección** (2026-08-31): `npm run test:layout` **77 pruebas en verde**
(7 composiciones × 4 anchos × 2 mediciones, más 7 × 3 anchos estrechos midiendo dentro del
desplegable), `npm test` **190 ficheros / 1985 pruebas** con el único rojo
preexistente de Node 25 que la §4 ya documentó (`use-timeline-property-store.test.ts`, fichero que
este change no toca), `typecheck` y `lint` limpios. Cifra de partida de 1.1: 187/1942 — los
ficheros y pruebas de más son los de las secciones 2-6.

**Dónde se corrió**: en el host, con el stack de Docker de este worktree **parado**, que es la
condición que `BLOCKED.md` §2 midió como necesaria para que la cifra sea estable (con el contenedor
vivo, su bind-mount reinstala `frontend/node_modules` bajo los pies del proceso del host, y un
fichero que no recolecta desaparece del total en vez de contar como rojo). Los 40 contenedores de
otras sesiones siguen vivos y no se tocó ninguno.

**Tres cosas que el navegador real exige y jsdom perdonaba**, todas en el arnés y ninguna en el
producto — están escritas con su razón en el propio fichero de test:

1. `vi.mock("@/lib/auth", …)` tiene que **extender el módulo real** (`importOriginal`), no
   sustituirlo. Un enlazador de ES modules de verdad rechaza importar un nombre que el mock no
   define, y el barril exporta once; jsdom nunca se enteró porque las shells solo usan `useAuth`.
   El fichero no llegaba ni a importarse: `does not provide an export named 'clearSessionPresent'`.
2. El mock de `next/link` necesita `__esModule: true`. Vite pre-empaqueta `next/link` como
   CommonJS, así que el import por defecto pasa por el ayudante de interop, que sin esa marca
   entrega el objeto del módulo entero — React lo reporta desde dentro de `NavLink` como
   «Element type is invalid … got: object», y con él caían `WorkspaceShell` y `/`.
3. Chromium no tiene `process`. `lib/config/public.ts` lee `process.env.NEXT_PUBLIC_*`, que Next
   incrusta en el build y Vite no, así que el proyecto `browser` lleva su propio `setupFiles`
   (`test/browser-setup.ts`) con un `process.env` vacío. No se reutiliza `test/setup.ts` porque su
   cuerpo entero es un polyfill de `localStorage` para un jsdom que no lo trae, y Chromium sí.

- [x] 6.1 `frontend/package.json`: dos `devDependencies` (`@vitest/browser`, `playwright`) y script
  `test:layout`; `frontend/vitest.config.ts` pasa a declarar **dos proyectos** (`node` sobre jsdom,
  `browser` sobre Chromium) para que el `npm test` de hoy no arrastre el navegador. Instalar el
  binario con `npm exec --no -- playwright install --with-deps chromium` (la tarea decía `npx`;
  corregido tras el panel, ver el hallazgo 2 abajo) (el contenedor es `node:22-slim`, así
  que instala limpio). Si aparece algún fichero suelto nuevo en la raíz de `frontend/`, actualizar
  la aserción `looseRootFiles()` de `test/color-tokens.test.ts`, que la pina exactamente. [R5.1]

  **Cuatro dependencias, no dos, y la razón de cada una de las dos de más**: Vitest 4 movió el
  proveedor a su propio paquete, así que «la bandera playwright» que D6 nombra se escribe hoy
  `@vitest/browser` + `@vitest/browser-playwright` + `playwright`; y 6.2 necesita
  `@tailwindcss/cli`, que es «la CLI de Tailwind» de D6 y que no estaba instalada (el proyecto solo
  tenía `@tailwindcss/postcss`). **Efecto colateral que conviene saber**:
  `@vitest/browser-playwright@4.1.11` pide `vitest@4.1.11` exacto, así que el lockfile sube
  `vitest` de 4.1.10 a 4.1.11 — un parche, dentro del `^4.1.10` que `package.json` ya declaraba, y
  la suite de 190 ficheros pasa igual con él.

  `looseRootFiles()` **no cambia**: no se añadió ningún fichero a la raíz de `frontend/`. La
  configuración de los dos proyectos vive dentro del `vitest.config.ts` que ya estaba listado, y el
  `setupFiles` del proyecto de navegador es `test/browser-setup.ts`. Verificado corriendo
  `test/color-tokens.test.ts`, no razonándolo.

  `npm test` pasa a ser `vitest run --project node`. Es la forma explícita: con `projects`, Vitest
  corre **todos** por defecto, así que sin el `--project` el `npm test` de siempre —y el
  `npm test -- --run features/provenance` del job `provenance-contract`— arrastrarían Chromium.
- [x] 6.2 Paso previo que compila `frontend/app/globals.css` con la CLI de Tailwind al artefacto que
  el test de navegador importa, encadenado desde `test:layout` y con la salida ignorada en git y
  **fuera de la raíz suelta** de `frontend/`. Sin este paso la guarda mide un DOM sin estilos y
  pasa siempre — el modo de fallo silencioso que R5.2 nombra por su nombre. [R5.1, R5.2]

  `npm run build:layout-css` → `test/artifacts/globals.css` (55,7 KB, 208 ms), encadenado con `&&`
  desde `test:layout` de forma visible en el `package.json` en vez de por el gancho `pre` de npm,
  que haría invisible el eslabón del que depende que esto mida algo. `frontend/.gitignore` ignora
  `test/artifacts/` con su razón escrita.

  **Por qué bajo `test/` y no en la raíz**: `test/color-tokens.test.ts` pina la lista exacta de
  ficheros sueltos de la raíz de `frontend/` y su extensión escaneada incluye `.css`, así que un
  CSS compilado ahí rompía esa aserción; y su recorrido de fuentes solo entra en `app`,
  `components`, `features` y `lib`, así que `test/` queda además fuera del escaneo de literales de
  color — que una hoja compilada de Tailwind haría fallar por construcción.

  Comprobado que el artefacto lleva de verdad las utilidades de las que depende la medición, no solo
  que se genera: `.hidden`, `.h-14`, `.tap-target`, `.max-w-48`, `.min-w-0`, `.truncate`, y
  `.sm\:flex` / `.sm\:hidden` **dentro de su media query**.
- [x] 6.3 `frontend/features/shell/components/topbar-overflow.browser.test.tsx` **(nuevo)**: las
  **seis** composiciones a 360×780 en Chromium, reutilizando los mocks de `next/navigation`,
  `@/lib/auth` y `next/headers` que ya usa `workspace-shell.test.tsx` (sin servidor, sin base
  sembrada, sin login). Afirma `document.documentElement.scrollWidth <= clientWidth` y el mensaje
  de fallo **nombra la composición concreta y el ancho medido**, no un fallo genérico. [R1.1, R1.2,
  R5.1, R5.3]

  **Siete, no seis.** Las seis de R1.1 más la variante de `PublicShell` con `MarketingNav`, que es
  la ruta `/`: es la superficie pública con menos sitio (su `Topbar` lleva el slot `center` que las
  otras públicas no), es la fila que D0 predijo mal y que 1.1 midió en 345/345 —sin holgura
  ninguna— y R1.4 prohíbe que este change empeore una composición que ya cumplía. Medir
  `PublicShell` solo en su configuración holgada dejaba fuera justo esa regresión.

  R5.3 se cumple **por la forma de la aserción**, no por un comentario: la función devuelve una
  frase (`"CleanerShell (/cleaner) @ 360px viewport: OVERFLOWS by 121px (scrollWidth 481 >
  clientWidth 360)"`) y el test afirma sobre la frase. Un `toBeLessThanOrEqual` habría impreso
  `481 <= 360` y nada más — ni qué pantalla ni a qué ancho. Se comprueba en 6.5 leyendo el fallo
  real, no razonándolo.
- [x] 6.4 Cubrir el rango, no el punto: el mismo fichero mide además 640 px (donde vuelve la
  disposición completa) y al menos dos anchos intermedios del tramo 360→640. [R1.3]

  360, **420**, **520** y 640 × 7 composiciones = 28 casos, que cubren el tramo por sus dos
  extremos y por dos puntos intermedios.

  Cuando se escribió esto, los dos intermedios se eligieron «a cada lado de los ~547 px que D7
  predice». **La tarea 7.5 midió 664 px**, así que 420 y 520 quedan los dos por debajo, en la rama
  estrecha. No cambia lo que estos casos valen —lo que cazan es un ancho donde no cabe ninguna de
  las dos ramas, y el 640 sigue siendo el primero de la ancha— pero la justificación de su elección
  ya no se sostiene, y se deja dicho en vez de corregida hacia atrás.
- [x] 6.5 **Validar la guarda al revés antes de darla por buena**: comprobar que falla contra la
  composición de hoy (revirtiendo temporalmente 4.3/4.4 en el árbol de trabajo, sin commitear) y
  que el mensaje del fallo identifica la composición. Sin esta demostración la tarea no está hecha
  — es el riesgo «la guarda mide sin CSS y pasa siempre» de `design.md`. [R5.1, R5.2]

  **Hecho, y con las cifras delante.** Se copiaron los cuatro ficheros al scratchpad, se
  restauraron sus versiones de `HEAD` (`git show HEAD:<ruta> > <ruta>`, sin `checkout`, sin `stash`
  y sin commitear) y se volvió a correr `test:layout`:

  | | con el arreglo | revertidos 4.3/4.4 |
  |---|---|---|
  | Resultado | 28 en verde | **6 en rojo**, 22 en verde |
  | `WorkspaceShell` @360 | cabe | `OVERFLOWS by 121px (scrollWidth 481 > clientWidth 360)` |
  | `TechnicianShell` @360 | cabe | `OVERFLOWS by 121px (481 > 360)` |
  | `CleanerShell` @360 | cabe | `OVERFLOWS by 121px (481 > 360)` |
  | Las tres @420 | caben | `OVERFLOWS by 61px (481 > 420)` |
  | Las tres @520 y @640 | caben | caben (481 < 520) |

  Tres cosas que esto demuestra y que ninguna lectura del código demostraba: que el CSS **se está
  aplicando** (sin estilos no habría 481 px de nada), que las que fallan son **exactamente** las
  tres shells que 4.4 arregla y ninguna de las cuatro que ya cumplían, y que el mensaje nombra la
  composición y los dos anchos. Los 481 px coinciden con el defecto que 1.1 midió contra la app
  levantada (457/445/465 sobre `clientWidth` 345); la diferencia es que aquí las tres comparten
  contenido y el correo del mock es más largo a propósito, para que el `truncate max-w-48` del
  `UserMenu` y el `min-w-0` de 4.3 estén de verdad bajo prueba.

  Los cuatro ficheros se restauraron desde las copias y `test:layout` volvió a 28 en verde.
- [x] 6.6 `.github/workflows/frontend-tests.yml`: paso nuevo en el job `frontend-tests` que instala
  Chromium y corre `npm run test:layout`, con su `id` y `continue-on-error: true` como los tres
  pasos vecinos, más su fila en la tabla de «Consolidar resultados» y en la condición de salida.
  Medir el coste real que añade al job (hoy ~1m30-2m15) y anotarlo; si duele, el precedente de
  partirlo está escrito en `backend-tests.yml`. [R5.1]

  Paso `id: layout` entre `tests` y `lint`, con las tres cosas que piden sus vecinos:
  `continue-on-error: true`, su fila en la tabla del `GITHUB_STEP_SUMMARY` y su término en el `if`
  de salida — que es lo que hace que el check falle de verdad pese al `continue-on-error`.

  **Coste, medido donde se puede medir y declarado como lo que es.** En local: 0,3 s de compilar el
  CSS y ~8 s de Vitest, ~13 s de reloj para el paso entero. Lo que domina es el binario: 178,7 MiB
  de descarga más las dependencias de sistema del `--with-deps`. Sobre un job de ~1m30-2m15 eso
  puede acercarse a duplicarlo. **La cifra de CI no se inventa aquí**: se lee de la primera
  ejecución del Pull Request, y las dos salidas si duele quedan escritas en el propio workflow —
  cachear `~/.cache/ms-playwright` por versión de `playwright`, o partir el job como hizo
  `ci-backend-tests-conditional-gate` en `backend-tests.yml`.
- [x] 6.7 `README.md` de la raíz: la sección de tests menciona el script nuevo `test:layout` y su
  requisito de binario de navegador, porque el README describe el sistema *actual*
  (`steering/documentation.md`). Sin endpoint, variable de entorno, diagrama ni contrato OpenAPI
  afectados en este change.

  En «Verificación del frontend»: la línea del script en el bloque de comandos, y debajo el párrafo
  que explica **por qué son dos proyectos y no dos formas de correr lo mismo** (jsdom no hace
  layout, así que `scrollWidth` es 0 y una medición ahí no mediría nada), más el
  `npm exec --no -- playwright install --with-deps chromium` que `test:layout` necesita y `npm test` no.
  Confirmado que el change no toca endpoints, `.env.example`, diagramas ni el contrato OpenAPI.
- [x] 6.8 **Añadida durante la ejecución de §6, con el usuario, tras una desviación** (regla 4 del
  flujo: parar, acordar el arreglo, poner los documentos al día). La primera versión verde de la
  guarda encontró que el arreglo de §4 satisface R1.1 **encogiendo un control**, que es
  exactamente lo que R3.2 prohíbe. [R3.1, R3.2, R3.3, R5.1]

  **El hallazgo, medido en Chromium sobre el árbol ya arreglado y con las siete composiciones
  dando «fits»**: la campana de notificaciones renderiza **42×44** en `/dashboard`, **22×44** en
  `/tech` y **25×44** en `/cleaner`. El mismo punto **antes** del change (revertidos 4.3/4.4): la
  fila desborda (`scrollWidth` 481) y la campana mide **44×44**. O sea que el change cambiaba una
  violación de R1 por una de R3.

  **Causa, localizada y no supuesta**: `min-w-0` en el slot `end` (tarea 4.3) permite que el slot
  encoja por debajo de su contenido; a partir de ahí, un control conserva su tamaño solo si declara
  un suelo. Cuatro de los cinco llevan `tap-target` (`min-width: 44px`); `NotificationBell` llevaba
  solo `size="icon"` (`h-11 w-11`), que fija una anchura de partida, no un mínimo — y `min-width:
  auto` de un ítem flex resuelve al min-content de su contenido, el icono de 16 px. El defecto
  estaba latente desde siempre: antes del `min-w-0` nada podía comprimir la campana.

  **Arreglo**: `tap-target` en el `Button` de `features/notifications/components/notification-bell.tsx`
  — una clase, la misma que ya llevan sus cuatro hermanos, la que `design-system-tokens.md:31`
  designa para esto. Sin cambio de disposición.

  **Y el arreglo que importa más, en la guarda**: R1.1 se satisface de dos maneras —reagrupando o
  encogiendo— y `scrollWidth <= clientWidth` lee **exactamente igual** en las dos. Los 28 casos de
  6.3/6.4 daban verde con la campana a 22 px. `topbar-overflow.browser.test.tsx` gana un segundo
  bloque de 28 casos que afirma el suelo de 44×44 sobre lo **renderizado**: mide
  `getBoundingClientRect()` de cada `button`/`a` visible de la cabecera (filtrando por
  `offsetParent !== null`, que es lo que descarta la rama que la media query esconde) y nombra en
  el fallo el control y su tamaño medido. Es una afirmación distinta de la que ya hacen
  `topbar-overflow-sheet.test.tsx` y `theme-switcher.test.tsx`: esas pinan que el control **lleva
  la clase**, y un control puede llevarla y estar aplastado por su padre flex.

  **Validado al revés, como 6.5**: quitando el `tap-target` de la campana, el bloque nuevo da
  **8 casos en rojo** y los nombra —
  `«Notificaciones, Sin notificaciones nuevas» 22×44` en `/tech` @360,
  `25×44` en `/cleaner` @360, `42×44` en `/dashboard` @360— y también a 420, 520 y **640**, donde
  la rama ancha monta tres controles más y aprieta todavía más. Con el `tap-target` puesto, las 56
  en verde.

  **Documentos puestos al día** (regla 4): `design.md` §D5 con la corrección y sus cifras,
  `proposal.md` en la fila de `NotificationBell` de su tabla de suelos —que derivaba los 44 px de
  `size="icon"`, que es justo la derivación falsa—, y los dos comentarios del código que repetían
  la frase «none of the controls may shrink» (`topbar.tsx`, `topbar-overflow-sheet.tsx`).

  **Lo que esto le hace a `BLOCKED.md` §1**: aquella decisión aceptó H1 y H2 porque «los caza por
  construcción la guarda medida de la sección 6». Sigue siendo cierto y ahora por partida doble —
  una utilidad `@utility` propia que declarase `display` (H2) o un segundo alias del import (H1)
  dejarían visible la rama ancha a 360 px, y eso ahora se ve tanto en el ancho de la raíz como en
  el suelo de 44 px de los controles que aparecerían duplicados.

### Panel de la sección 6 y su ronda de arreglos (2026-08-31)

Siete revisores en paralelo. **Cinco PASS sin hallazgos** (arquitectura, documentación, tenancy,
CI/CD, i18n) y **dos FAIL con tres hallazgos entre los dos**, todos con referente y todos
aceptados. El panel se quedó a medias una vez —el proceso salió mientras corrían— y se reanudó
desde las transcripciones con el árbol verificado intacto.

Dos cosas que los revisores confirmaron y conviene no volver a re-derivar: **i18n** cerró la duda
que D0 dejaba abierta («una traducción más larga en `en` se los come») midiendo que el único texto
visible del topbar que cambia con el idioma es el enlace del landing, y que el `es` («Iniciar
sesión», 15) es **más largo** que el `en` («Sign in», 7) — medir en español es la elección
conservadora, no una laguna. Y **QA** validó la guarda con una mutación propia
(`hidden`→`invisible` en la rama ancha), que la puso en rojo con 5 casos nombrando composición y
ancho, incluidos dos a 420 px — o sea que el barrido de rango de 6.4 está vivo, no decorativo.

**Hallazgo 1 (QA, `FAIL`) — R3.1 tenía una cláusula sin verificar.** «incluidos los controles que
pasen al desplegable». El bloque de 44×44 acotaba a `document.querySelector("header")` y el
fichero no abría el desplegable en ningún caso; y aunque lo abriera, `SheetContent` sale por un
portal de Radix colgado de `document.body` (`components/ui/sheet.tsx`), así que **nunca** está
dentro del `<header>`. Los cuatro controles que R3.1 manda ahí —los tres del tema y el de idioma—
no los medía nadie: `topbar-overflow-sheet.test.tsx` solo comprueba que **llevan la clase**
`tap-target`, y su propio comentario atribuía la medición a la guarda de §6, que no la hacía.

  *Arreglo*: bloque nuevo de 21 casos (7 composiciones × 360/420/520; a 640 el disparador es
  `sm:hidden` y los controles viven en la rama ancha, que el bloque de cabecera ya mide). Abre el
  desplegable, espera al diálogo y acota a `[role="dialog"]`. Y los dos comentarios de
  `topbar-overflow-sheet.test.tsx` que decían algo falso quedan corregidos.

  *Validado en las dos direcciones*, porque la primera mutación no bastaba: quitar `tap-target` de
  `theme-switcher.tsx` **no** lo pone en rojo, y no es un fallo de la guarda — dentro del
  desplegable no hay compresión, así que el `h-11 w-11` de `size="icon"` ya da 44×44 por sí solo.
  Se comprobó primero que el bloque mide de verdad (registra `Claro=44x44 Oscuro=44x44 Seguir al
  sistema=44x44 Cambiar idioma a English=44x44` en las tres shells autenticadas) y luego con una
  mutación que sí encoge (`className="size-8"`), que lo pone en rojo nombrando
  `«Claro» 32×32, «Oscuro» 32×32, «Seguir al sistema» 32×32` en los tres anchos.

  **Y encontró un segundo defecto, que se anota y no se arregla aquí.** El botón de cierre del
  `Sheet` mide **16×16**: es `SheetPrimitive.Close`, un icono `X` sin relleno, compartido por las
  **seis** superficies que montan un `Sheet` (el menú «Más», el buzón de notificaciones, la barra
  lateral, dos diálogos del panel y este desplegable) y con ese tamaño desde antes de este change.
  No es «un control que pasa al desplegable» sino la cromo del propio `Sheet`, y darle superficie
  táctil real cambia visualmente seis pantallas — que es exactamente lo que el «Out of scope» del
  proposal manda anotar en vez de arreglar. Queda **exento por nombre**, no en silencio: el
  primitivo gana un `data-slot="sheet-close"` (completa el juego que ese fichero ya usa, sin
  cambio visual) y la guarda exime ese selector con su razón escrita, de modo que la exención no
  puede extenderse a un segundo control por accidente — el mismo patrón que el mapa `EXCEPTIONS`
  de `test/color-tokens.test.ts`. **Candidato a change futuro**: dar 44×44 al cierre de `Sheet`.

**Hallazgo 2 (seguridad, `LOW`) — `npx` podía ejecutar un `playwright` sin fijar.** `npx` descarga
el paquete del registro cuando no está en `node_modules`, y `package.json` es contenido que
controla el PR sobre un disparador `pull_request:` sin filtros de rutas. Un PR que quitara
`playwright` del manifiesto convertía el paso en «baja la versión del día y ejecútala con
`--with-deps`», bajo el sudo sin contraseña del runner. *Arreglo*: `npm exec --no -- playwright
install …`, que se niega a instalar nada — usa el binario que dejó `npm ci` desde el lockfile, o
falla. Verificado en local: resuelve `1.62.1`, el que fija el lockfile.

  **Ronda 2, y la parte que casi se queda fuera**: el mismo revisor volvió a mirar y encontró que
  el arreglo se había parado en la línea ejecutable — la prescripción que produjo el defecto seguía
  escrita con `npx` en **cuatro** sitios más (`design.md` D6, el `README.md`, y dos veces en este
  fichero). D6 es el que releerá el próximo change que toque Playwright — las variantes de caché o
  de partir el job que el propio D6 propone, o la suite E2E de `hardening-release`—, así que
  dejarlo ahí era reintroducir el fallo por copia. Corregidos los cuatro, y el porqué queda escrito
  en D6 y en el README en vez de solo en el workflow. El README pasa a enseñar **el mismo comando
  que corre CI**: en un portátil la diferencia es solo que no te instala a la espalda una versión
  distinta de la fijada, pero dos formas del mismo comando es justo lo que hace que la floja acabe
  copiada a un sitio donde importa.

**Hallazgo 3 (seguridad, `LOW`) — D6 declaraba dos dependencias y el diff añade cuatro**, y la
mitad no declarada es por donde entra el único paquete nuevo con script de instalación que corre
en Linux (`@parcel/watcher@2.5.1`, transitivo de `@tailwindcss/cli`, ejecutado en el `npm ci` de
CI). *Arreglo*: D6 enumera ahora las cuatro con su razón y nombra ese transitivo como aceptado,
con el radio acotado que el propio revisor verificó — `permissions: contents: read`,
`persist-credentials: false` y `pull_request:` (no `pull_request_target:`), así que una ejecución
desde un fork no ve secretos. La tabla de «Changes by area» queda corregida con ella.

Lo que el revisor de seguridad comprobó y cerró sin hallazgo, para no repetirlo: las 46 entradas
nuevas del lockfile llevan todas `integrity` y `resolved` en `registry.npmjs.org`; el `process`
shim no puede filtrar valores reales (instala un env **vacío** y Vite solo expone `VITE_*`, que no
casa con ningún `NEXT_PUBLIC_*`); el CSS compilado no contiene nada sensible y es función pura de
las fuentes commiteadas (regenerarlo da un fichero idéntico); y `screenshotFailures: false` se
verificó empíricamente con `git status --porcelain` antes y después de una pasada, no leyendo la
bandera.

## 7. Verification

- [x] 7.1 Suite frontend completa en verde: `docker compose exec -T frontend npm test`, con los
  `docker compose cp` que `sdd/project.md` documenta para los dos `ENOENT` de worktree
  (`features/provenance/workflow-contract.test.ts`, `lib/config/build-identity-contract.test.ts`).
  Comparar contra la cifra de ficheros/tests **medida al empezar**, no contra ningún número
  escrito en documentación.

  **Verde el 2026-09-01 dentro del contenedor**: **190 ficheros, 1985 pruebas, 0 en rojo**, con los
  nueve `docker compose cp` puestos antes (el stack llevaba levantado desde §6, así que los dos
  `ENOENT` de worktree estaban de vuelta). Contra la cifra de partida que midió 1.1 —**187 ficheros,
  1942 tests**— este change suma 3 ficheros y 43 pruebas. Y confirma el diagnóstico que §6 dejó
  abierto: el único rojo del host
  (`features/dashboard/state/use-timeline-property-store.test.ts`) **desaparece aquí**, que es la
  prueba de que era artefacto del Node v25 del host y no un defecto.
- [x] 7.2 `docker compose exec -T frontend npm run lint` y `docker compose exec -T frontend npm run typecheck`
  en verde.

  Los dos limpios el 2026-09-01, sin una sola línea de salida más allá del banner de npm.
- [x] 7.3 `docker compose exec -T frontend npm run test:layout` en verde, y con 6.5 ya demostrado.

  **77 pruebas en verde en Chromium dentro del contenedor** el 2026-09-01. Chromium instalado ahí
  con `npm exec --no -- playwright install --with-deps chromium` —el comando que D6 fija tras la
  corrección del panel de seguridad— y `node:22-slim` lo instaló limpio, como D6 predecía. La
  validación al revés de 6.5 ya estaba hecha en su sección; esta tarea solo pedía el verde.
- [x] 7.4 Pasada en navegador real a 360×780 sobre las **seis** composiciones, repitiendo la
  medición de 1.1: `scrollWidth <= clientWidth` en todas, y ninguna que estuviera sana antes ha
  empeorado. Sin avisos de hidratación en consola (el `getServerSnapshot` de 2.2 es lo que podría
  producirlos). Los únicos errores tolerados son el handshake del WebSocket de HMR y el
  `favicon.ico` 404. [R1.1, R1.2, R1.4, R4.4]

  **Medido el 2026-09-01**, Chromium a 360×780 dentro del contenedor contra `http://localhost:3000`
  (desde dentro es el propio origen de `next dev`, así que el bloqueo de origen cruzado que
  `sdd/project.md` documenta no aparece; la app hidrata y se entra por clic con los tres roles).
  Las **siete** composiciones dan `scrollWidth == clientWidth == 360`:

  | Composición | Ruta | antes (1.1) | ahora | Veredicto |
  |---|---|---|---|---|
  | `PublicShell` + `MarketingNav` | `/` | 345/345 cabe | 360/360 | sigue cumpliendo |
  | `PublicShell` | `/login` | 360/360 cabe | 360/360 | sigue cumpliendo |
  | `GuestShell` | `/guest/[token]` | 360/360 cabe | 360/360 | sigue cumpliendo |
  | `(authenticated)` | `/welcome` | 360/360 cabe | 360/360 | sigue cumpliendo |
  | `WorkspaceShell` | `/dashboard` | **457**/345 desborda | 360/360 | **arreglada** (−97) |
  | `TechnicianShell` | `/tech` | **445**/345 desborda | 360/360 | **arreglada** (−85) |
  | `CleanerShell` | `/cleaner` | **465**/345 desborda | 360/360 | **arreglada** (−105) |

  Las tres arregladas pasan de `clientWidth` 345 a 360 porque su barra de desplazamiento vertical de
  15 px desaparece: liberar el `end` acorta la página lo suficiente. R1.4 queda cumplido — ninguna
  de las cuatro que ya cumplían R1.1 ha empeorado.

  **Consola**: cero menciones de hidratación en las siete (buscadas por `hydrat|did not match`), así
  que el `getServerSnapshot` de 2.2 no produce ninguna. Lo único que sale es (a) un aviso de
  `next dev` sobre `scroll-behavior: smooth` en `<html>`, preexistente y ajeno a este change, y
  (b) un 404 a `/api/v1/guest/info/<token>`, que es **mi** token inventado para alcanzar la
  `GuestShell`, no un defecto de la app. Ni handshake de HMR ni `favicon.ico` esta vez.
- [x] 7.5 Barrido 360→640 en el navegador, confirmando o corrigiendo los ~547 px que D7 predice
  para la composición más cara (`/tech`). Si la disposición completa no cabe a 640, subir el
  breakpoint a `md` y **decirlo en el registro del change**, no cambiarlo en silencio (OQ-2).
  [R1.3]

  **Barrido hecho el 2026-09-01, y la predicción de D7 se corrige: son 664 px, no ~547.** La tabla y
  el razonamiento completos están en `design.md` §D7 → «Medición real (tarea 7.5)». En resumen:

  - **Ningún ancho desborda.** 360→640 de 4 en 4 px sobre las **siete** composiciones (71 anchos
    cada una) y 360→700 de 1 en 1 sobre `/tech` (341 anchos): `scrollWidth <= clientWidth` en todos.
    R1.3 cumplido.
  - **El traspaso cae en 640 exactamente**: disparador del `Sheet` en 360..639, disposición ancha
    desde 640. Cero anchos con las dos ramas a la vez y cero con ninguna.
  - **`md` no se sube, y por qué**: la disposición ancha necesita 664 px sin comprimir, pero a
    640 px cumple R1.1 y los seis controles están a su tamaño completo (ninguno bajo 44×44). Lo
    único que cede son 12 px de texto que **ya trunca por diseño** (`PageTitle` y el email del
    `UserMenu`); a 664 px son 4 px y desde 700 px cero. La condición de OQ-2 —«la disposición
    completa no cabe»— no se cumple, así que el breakpoint se queda en `sm` y la alternativa `md`
    queda escrita en D7 con su precio, en vez de aplicada en silencio.
- [x] 7.6 Comprobación manual de R2 y R3 en el navegador a 360 px: los cinco controles siguen
  alcanzables (tema e idioma dentro del desplegable), el `UserMenu` conserva su confirmación de
  cierre de sesión, ninguna superficie táctil baja de 44×44 px medidos, y el `Sheet` inferior no
  tapa el contenido. [R2.1, R2.2, R2.3, R3.1, R3.2, R3.3]

  **Comprobado el 2026-09-01 sobre `/tech` a 360×780.** Los cinco controles están y son
  alcanzables: en la barra, `Preferencias` 44×44, `Notificaciones, 1 sin leer` 44×44 y
  `Menú de usuario` 68×44; dentro del `Sheet`, los tres botones de tema (`Claro`, `Oscuro`,
  `Seguir al sistema`) a 44×44 y `Cambiar idioma a English` a 44×44, con el `role="group"`
  «Tema» completo. Ninguna superficie táctil por debajo de 44×44 (R3.1, R3.2) ni con el
  desplegable cerrado ni abierto.

  El `Sheet` inferior ocupa **137 px de los 780** del viewport (`y` 643→780): es un cajón, no una
  pantalla completa, y con él abierto sigue sin haber desbordamiento horizontal (360/360). R3.3
  cumplido.

  **Una excepción, ya conocida y no de este change**: el botón de cierre del propio `Sheet`
  (`Cerrar menú`) mide 16×16. Es la `X` de `components/ui/sheet.tsx`, presente en las seis
  superficies que montan un `Sheet` desde antes de este change; §6 ya la midió, decidió que no es
  «un control que pasa al desplegable» sino chrome de la primitiva, y la exentó por
  `data-slot="sheet-close"` en la guarda medida, dejándola anotada como candidata a change futuro.
  Ese razonamiento está escrito en el propio `sheet.tsx`. Esta tarea lo confirma, no lo reabre.

  R2.3: el `UserMenu` no se toca en este change y conserva su disparador propio en la barra a
  360 px, con su nombre accesible «Menú de usuario» y su confirmación de cierre de sesión intacta
  (`user-menu.tsx` no aparece en el diff).
- [x] 7.7 Comprobación manual de R4.4 en el navegador: cambiar el tema desde el desplegable a
  360 px, ensanchar la ventana por encima de 640 px **sin navegar ni recargar**, y ver que el
  botón `aria-pressed` de la barra ancha es el que corresponde. [R4.4]

  Añadido tras el panel de §4: hacer ese mismo gesto **dejando el desplegable abierto**, que es el
  caso límite que el arquitecto y QA levantaron. Comprobar las tres cosas: (1) que el árbol de
  accesibilidad sigue enseñando **una sola** instancia de cada control —lo debe garantizar el
  `aria-hidden` del diálogo modal—, (2) qué se ve en pantalla, y (3) dónde acaba el foco al cerrar,
  porque el disparador es `display:none` a ese ancho. Si (2) o (3) resultan feos, se anota como
  candidato a change futuro: R4.2 se cumple, así que no es alcance de este. [R4.2, R4.4]

  **El gesto normal, verificado el 2026-09-01**: a 360 px, `data-theme` sin fijar; se abre el
  desplegable, se pulsa `Oscuro` → `data-theme="dark"`; se cierra con `Escape`; se ensancha a
  800 px **sin navegar ni recargar** → la barra ancha muestra exactamente **un** botón con
  `aria-pressed="true"`, y es `Oscuro`. `data-theme` sobrevive al cambio de ancho. R4.4 cumplido:
  el hook de 2.2 hace que las instancias coincidan por construcción.

  **El caso límite del panel, con el desplegable abierto**, las tres cosas que pedía:

  1. **Árbol de accesibilidad: una sola instancia**, sí. Con el `Sheet` abierto a 360 px el árbol
     enseña un único `role="group"` «Tema» (el del cajón) y **cero** disparadores `Preferencias`;
     al ensanchar a 800 px sigue enseñando uno de cada. El mecanismo medido no es `aria-modal`
     —Radix no lo pone en este contenido— sino el `aria-hidden="true"` que el diálogo escribe en
     **los hermanos** de `document.body`, y ahí queda la barra entera. R4.2 se cumple a los dos
     anchos y en la transición.
  2. **En pantalla sí se pintan dos.** A 800 px con el cajón abierto hay dos grupos «Tema»
     visibles: el de la barra ancha (`y` 6, 136×44, con un ancestro `aria-hidden="true"`) y el del
     cajón (`y` 712, 136×44). Es duplicación **visual**, no de accesibilidad. Sin desbordamiento
     (800/800). Anotado como candidato a change futuro, que es lo que esta tarea manda: R4.2 se
     cumple, así que no es alcance de este.
  3. **El foco se va a `<body>` al cerrar.** Con el disparador en `display:none` a 800 px, Radix no
     tiene dónde devolverlo. Es el punto feo que el arquitecto anticipó; mismo trato que (2):
     anotado como candidato a change futuro, no arreglado aquí.

  Los dos candidatos se cierran con lo mismo —cerrar el `Sheet` cuando la media query deja de
  aplicar—, y eso es un `useSyncExternalStore` sobre `matchMedia`, o sea detección de viewport en
  JavaScript, que es exactamente lo que **R4.1 prohíbe** a este change. Por eso son un change
  aparte y no una ronda de arreglo de este.
- [x] 7.8 Comprobación manual de R4.2 con la tecnología asistiva del navegador (árbol de
  accesibilidad): en 360 px y en 800 px hay **una sola** instancia de cada control, sin nombres
  accesibles duplicados ni paradas de tabulación repetidas. [R4.2]

  **Verificado el 2026-09-01** sobre `/tech`, contando por rol y nombre accesible (que es lo que
  respeta `display:none` y `aria-hidden`, no el DOM):

  | Nombre accesible | @360 px | @800 px |
  |---|---|---|
  | `Preferencias` (disparador) | 1 | 0 |
  | `role="group"` «Tema» | 0 | 1 |
  | `Claro` / `Oscuro` / `Seguir al sistema` | 0 / 0 / 0 | 1 / 1 / 1 |
  | `Cambiar idioma a English` | 0 | 1 |

  Ni un solo nombre duplicado, y ninguna rama presente en los dos sitios: es el `display:none` de
  `hidden` / `sm:hidden` haciendo lo que D3 dice que hace.

  **Paradas de tabulación**, recorridas con `Tab`: 12 a 360 px (`Saltar al contenido`,
  `Preferencias`, `Notificaciones, 1 sin leer`, `Menú de usuario`, y de ahí al contenido) y 15 a
  800 px (`Saltar al contenido`, `Claro`, `Oscuro`, `Seguir al sistema`,
  `Cambiar idioma a English`, `Notificaciones…`, `Menú de usuario`, …). Cero paradas repetidas para
  un control de la cabecera a cualquiera de los dos anchos.
