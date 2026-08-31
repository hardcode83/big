# Blocked — shell-topbar-overflow-360

## 1. Sección 5: sin anotación `panel: PASS`, por decisión tomada

- **phase**: run (sección 5, «Guarda estructural: la forma del arreglo»)
- **type**: deferred
- **decidido por el usuario (2026-08-31)**: **aceptar H1 y H2 como límites
  documentados** y seguir a la sección 6, en vez de abrir una ronda 3. Los dos
  están escritos con nombre en la cabecera de
  `frontend/test/topbar-overflow.test.ts`, en su bloque «what this guard learned
  about itself», que es donde esta guarda ya registra sus otros agujeros.
- **qué queda**: la sección 5 **no lleva anotación `panel: PASS`** en `tasks.md`
  —el panel cerró en `FAIL`, y anotarla sería falso—, así que `/sdd:review`
  la auditará a escala de feature junto al resto. No hay trabajo de código
  pendiente en la sección.
- **contexto de la decisión**:

  `frontend/test/topbar-overflow.test.ts` está implementado, verificado y con 19
  mutaciones comprobadas (15 rojas, 4 verdes). Seis de los siete revisores dieron
  `PASS`; `sdd-qa` dio `FAIL` en las tres pasadas. Se consumieron las **dos rondas
  de arreglo** que `/sdd:run` permite: la ronda 1 cerró F4–F7 y reabrió F1–F3 por
  otra vía, la ronda 2 cerró G1–G6 pasando de fijar *grafías* a leer *mecanismos*
  (ancestro que decide `display`, recorrido hacia delante del grafo, `style`
  inline, propiedades arbitrarias). Tras la ronda 2 quedaron cuatro hallazgos; los
  dos no bloqueantes (H3, un control que certificaba una paráfrasis de la regla
  real; H4, un comentario que afirmaba algo falso) están arreglados, sin cambio de
  comportamiento y con las 19 mutaciones revalidadas.

  **Quedan dos, ambos clasificados por el propio revisor como «evasión
  deliberada», no como forma que produzca una refactorización de buena fe.** Están
  documentados como límites con nombre en la cabecera del fichero:

  - **H1** — `mountSites()` cuenta un nombre de etiqueta literal. Un *segundo
    alias del mismo import* en un fichero que el recorrido ya alcanza
    (`import { ThemeSwitcher as ThemeToggle } from "./theme-switcher"`, montando
    los dos) son tres montajes reales y dos etiquetas `<ThemeSwitcher` literales.
    Un renombrado puro sí se caza; una adición bajo un segundo nombre, no.
    Cerrarlo: resolver los nombres de binding por fichero a partir de los imports
    que el recorrido ya parsea. Referente R4.2.
  - **H2** — `DISPLAY_UTILITIES` conoce las veintiuna utilidades de Tailwind y
    `[display:…]`, pero no el vocabulario propio del proyecto. `app/globals.css`
    define utilidades (`@utility tap-target`, `@utility pb-safe`); una que
    declarase `display` —`@utility topbar-wide { display: flex; }`, usada como
    `max-sm:topbar-wide`— dejaría la rama ancha visible a 360 px sin que
    `displayTokens` lo viera. Cerrarlo: cosechar del propio `globals.css` (que
    este guard ya lee) toda `@utility` cuyo cuerpo declare `display`. Referente
    R1.1 / R4.2.

  Los dos los caza por construcción la **guarda medida de la sección 6**, que
  observa el ancho renderizado a 360 px en Chromium en vez de la grafía que lo
  produjo — que es exactamente el reparto que D6 fija cuando llama a esta guarda
  «complemento, no sustituto». Esa fue la razón de aceptarlos: ningún guard sobre
  texto fuente puede blindarse contra una evasión deliberada, y cada ronda anterior
  cambió una grafía cerrada por otra escapatoria.

  Si la sección 6 acabara sin entregar la guarda medida, **H1 y H2 dejan de ser
  aceptables** y hay que cerrarlos aquí: H2 son unas seis líneas reutilizando la
  lectura de `globals.css` que el fichero ya hace; H1 exige resolver los nombres de
  binding por fichero a partir de los imports que el recorrido ya parsea.

  **Esa condición está resuelta (2026-08-31)**: la sección 6 entregó la guarda
  medida, con panel 7/7 `PASS` y la puerta cerrada de
  `scripts/reviewer_panel.py --phase run` en 0. Y los caza con más margen del que
  esta decisión suponía, porque la guarda acabó midiendo dos cosas y no una: tanto
  una `@utility` propia que declarase `display` (H2) como un segundo alias del
  import (H1) dejarían visible la rama ancha a 360 px, y eso se ve **tanto** en el
  ancho de la raíz **como** en el suelo de 44 px de los controles que aparecerían
  duplicados. De esta entrada sigue pendiente solo lo otro: la sección 5 no lleva
  anotación `panel: PASS` y `/sdd:review` la auditará a escala de feature.

- **comando para retomar**: `/sdd:review shell-topbar-overflow-360`
