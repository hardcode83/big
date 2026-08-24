# BLOCKED — design-system-tokens

Cola abierta por `/sdd:review` el 2026-08-24. El veredicto fue **FAIL**: la
implementación no queda verificada localmente y `STATE.md` sigue en `ACTIVE`.
Ninguna entrada se resuelve editando este fichero: se resuelve arreglando lo que
describe y volviendo a pasar el panel sobre el arreglo.

## 1. El guard rechaza los tokens tipográficos del propio change

- **fase**: review · **tipo**: deferred
- **qué y por qué**: la comprobación 3 de `frontend/test/color-tokens.test.ts:210-229`
  clasifica como violación las diez utilidades `text-<rol>` de D10. `DECLARED_TOKENS`
  se construye filtrando `--color-*` (`:158-161`), y `NON_COLOR.text`
  (`frontend/test/color-tokens.ts:236`) sólo admite la escala numérica de Tailwind,
  así que `namesAColorToken("text","display-2xl")` devuelve `true` y el nombre no
  está declarado. Hoy está dormido —cero consumidores en `app|components|features|lib`—
  pero el primer consumidor pone el build en rojo con un mensaje que pide declarar un
  token de color que no debe existir. `landing-public` y `visual-restyle-workspace`
  existen justamente para aplicar esos roles. Referente: D10 contra D12/D13.
- **comando de reanudación**: `/sdd:review design-system-tokens`

## 2. Cinco bypasses demostrados del guard de la sección 8

- **fase**: review · **tipo**: deferred
- **qué y por qué**: la sección 8 quedó anotada `FIXED 2026-08-24 sin tercera vuelta`,
  nunca en PASS, y el panel de esta review la auditó a fondo. El grave es
  `[@media(prefers-color-scheme:dark)]:bg-surface`, que pasa las cinco
  comprobaciones (`DARK_VARIANT` no dispara porque la cadena lleva `scheme:dark)`, y
  el lookbehind de `colorUtility()` se satisface con los `:` previos) y **reabre en una
  línea el defecto R1.5/R6.5 que este change existe para cerrar**. Los otros cuatro son
  ceguera latente sin violación viva: `stripCode` borra desde un `/*` dentro de un
  literal de cadena; la regla de `//` borra la línea tras una letra, `}` o `)`;
  `sourceFiles()` sólo lee `.tsx?`, así que ningún `.css`/`.js`/`.jsx`/`.mjs` se
  escanea (un `@apply bg-red-500` en un CSS nuevo es invisible); y `STYLE_COLOR` no ve
  la clave computada `{ ["color"]: "#e11d48" }`. Referente: R1.5, R6.6, D12.
- **comando de reanudación**: `/sdd:review design-system-tokens`

## 3. R6.4 se implementó en otra ubicación y el proposal no se enmendó

- **fase**: review · **tipo**: decision
- **qué y por qué**: R6.4 (`proposal.md:241`) manda unificar los dos `SEVERITY_COLOR`
  «en la única tabla de `lib/ui/`»; la tabla vive en
  `frontend/features/incidents/lib/severity-tone.ts:28`. La sustancia se cumple (las dos
  copias murieron, `TONE_BADGE_CLASS` es la única paleta, y el `SHALL` de
  `sdd/specs/frontend-foundation.md:38` queda satisfecho) y la desviación está razonada
  en `design.md:256-269`, pero el criterio nunca se enmendó. Sin enmienda, la spec que
  se escriba al archivar afirmará como `SHALL` una ubicación que el código no usa.
  Decisión de Jose: enmendar R6.4 a la ubicación real, o mover la tabla a `lib/ui/`.
- **comando de reanudación**: `/sdd:review design-system-tokens`

## 4. Deriva documental: las enmiendas se añadieron en vez de aplicarse

- **fase**: review · **tipo**: deferred
- **qué y por qué**: diez hallazgos del panel comparten una sola causa. Cada enmienda de
  `/sdd:run` se propagó a dos o tres de los cinco sitios donde vive el mismo hecho, y en
  el resto sobrevivió la redacción vieja:
  - `design.md:744` — «11 pasos `--spacing-*`, 5 `--radius-*`»; real: `--spacing` + 3
    pasos con nombre (`globals.css:260-263`) y 4 radios (`:283-286`). Ambas cifras
    describen el estado que rompía `max-w-*` y se revirtió.
  - `tasks.md:173-175` — la tarea 3.4 sigue marcada `[x]` mandando declarar los once
    pasos `--spacing-{xs…4xl}`, y en todo `tasks.md` no hay nota de la segunda enmienda.
    La 3.5 arrastra `--radius-{…,full}` (su retractación sí está en `tasks.md:114-120`).
  - `design.md:752-753` — la fila Guards nombra 3 ficheros; el change entrega 9, y falta
    justo `test/color-tokens.ts` y `test/color-tokens.patterns.test.ts`, que la propia
    enmienda de D12 (`design.md:546-550`) decide crear.
  - `design.md:744-754` — el inventario enumera 19 ficheros; el diff lleva 49 fuera de
    `sdd/`. Ausentes los diez arreglos de D13, los cinco shells, `locale-switcher.tsx` y
    doce módulos de test, es decir las dos ampliaciones de huella que D5 (`:181-184`)
    insistió en decir en voz alta.
  - `frontend/app/layout.tsx:18-21` — el comentario abre afirmando el hecho que D8
    corrigió («la job "Production build"… **ambos** tienen red») y se corrige a sí mismo
    en el párrafo siguiente: la corrección se añadió, no se aplicó. Y la enumeración
    corregida sigue incompleta: falta un cuarto sitio de build,
    `.github/workflows/multiarch-build-check.yml:35-48` (`target: prod`,
    `linux/amd64,linux/arm64`), que atraviesa el mismo `builder` y descarga las fuentes
    dos veces por ejecución. Mismo defecto en `design.md:295`.
  - `frontend/README.md:126` — anuncia los diez roles como «`text-display-2xl` …
    `text-label-sm`»; el token declarado es `--text-label-caps` (`globals.css:231`) y
    `label-sm` no existe en el árbol. Quien siga el README escribe una clase que no
    compila nada, y la comprobación 3 no lo caza porque sólo mira color.
  - `frontend/README.md:132` — describe el guard con **tres** comprobaciones y remata con
    «Lo que no ven:», presentando la lista como exhaustiva; hay cinco
    (`color-tokens.test.ts:189,197,210,231,244`). Las dos omitidas son precisamente la
    cuarta y la quinta de D12, así que el lector queda creyendo que `bg-[#e11d48]` y un
    hex en `style={{…}}` están sin vigilar.
  - `frontend/README.md:118` — «vive **entera** en `app/globals.css`, expuesta por
    `@theme inline`»; `@theme inline` es `:129-166` (color y las dos familias), mientras
    tipografía, ritmo y radios están en un `@theme` llano (`:176-287`), y el propio
    fichero explica por qué. Quien añada un token entra en el bloque equivocado.
  - `frontend/README.md:85` — el inventario de islas de cliente no incluye
    `ThemeSwitcher` y sigue presentando `Topbar` como Server Component llano, cuando los
    cinco shells cambiaron por hacerse `async`.
  - `frontend/README.md:30` — la línea de `lib/` no lista el nuevo `lib/theme/`.
  **Lo estructural, que otra ronda de ediciones no arregla**: recuentos de tokens,
  número de comprobaciones del guard, inventario de ficheros y sitios de build no tienen
  un único hogar; viven a la vez en `proposal.md`, `design.md` (D# y tabla), `tasks.md`
  (cuerpo de tarea y comentario de panel), `frontend/README.md` y comentarios en código.
  Mientras siga así, cada enmienda futura volverá a dejar dos o tres copias atrás.
- **comando de reanudación**: `/sdd:review design-system-tokens`

## 5. Falta el ancla de `docs/<capability>.md` para el archivado

- **fase**: review · **tipo**: decision
- **qué y por qué**: `sdd/steering/documentation.md:18` obliga, al archivar un change que
  introduce una capability de cara a usuarios, a crear o actualizar
  `docs/<capability>.md`. El change entrega un control de usuario —selector de tema de
  tres estados en la topbar de los cinco shells, con rótulos ES/EN y cookie
  `autohostai.theme`—, el mismo criterio que dio página a `docs/frontend-auth-session.md`
  y `docs/app-version-visibility.md`. Pero `tasks.md` §9, la fila Docs de `design.md:754`
  y «Affected specs» del proposal nombran sólo `frontend/README.md`: sin ancla,
  `/sdd:archive` no tiene nada sobre lo que actuar y la obligación se salta en silencio.
  Decisión de Jose: crear la página al archivar, o dejar escrito por qué
  `frontend/README.md` la cubre.
- **comando de reanudación**: `/sdd:review design-system-tokens`

## 6. Clave i18n huérfana y semántica accesible de un control preexistente

- **fase**: review · **tipo**: decision
- **qué y por qué**: dos caras de lo mismo. `81b4faa` rediseñó
  `features/shell/components/locale-switcher.tsx:60-86` de un `role="group"` de dos
  botones con `aria-pressed` a un único botón de acción con tooltip; ningún requisito lo
  autoriza (R3.5 gobierna sólo el control de tema, y `proposal.md:44` dice «No se toca
  ninguna pantalla»), está asumido como coste en `tasks.md:458-468` y nada se rompe, pero
  es creep de alcance sobre la accesibilidad de un control ya entregado. Efecto colateral:
  `localeSwitcher.label` queda sin ningún consumidor en
  `locales/{es,en}/navigation.json:111`, y el test de paridad compara conjuntos de claves,
  así que no distingue muerta de viva. Decisión: borrar la clave y dejar el botón único,
  o restaurar el grupo rotulado.
- **comando de reanudación**: `/sdd:review design-system-tokens`

## 7. Ausencias sin guard y verificaciones que no se ejercitaron

- **fase**: review · **tipo**: deferred
- **qué y por qué**: cuatro de severidad menor, todas con referente.
  - R1.1 exige no reintroducir `tailwind.config.js|ts`; hoy no existe, pero ningún test
    nombra el fichero, así que nada falla si vuelve. Contraste: la ausencia de R5.1 sí
    tiene guard, y el panel verificó por mutación que falla de verdad.
  - Los cinco shells invocan un Server Component asíncrono como función,
    `topbar={await Topbar({ start })}`, en vez de `<Topbar start={start} />`. Funciona y
    la suite está verde, pero pierde identidad de elemento React y se rompe en cuanto
    `Topbar` necesite contexto.
  - R1.4 («vence en las dos direcciones») se apoya en un argumento de especificidad
    escrito en un comentario (`globals.css:9-14`) más una aserción de orden de fichero.
    Un reordenado se caza; una premisa de especificidad equivocada no la caza nada,
    porque ningún navegador renderiza los dos bloques (Playwright sigue «previsto»).
  - La dependencia de red en build que introduce D8 no se ejercita antes de mezclar:
    `multiarch-build-check.yml` está filtrado por `paths` a ficheros que este diff no
    toca, y `deploy-dev.yml` sólo dispara en push a `main`. La primera vez que el stage
    `builder` baje las fuentes bajo QEMU/arm64 será después del merge.
- **comando de reanudación**: `/sdd:review design-system-tokens`

## 8. La rama no sigue la convención `sdd/<feature>`

- **fase**: review · **tipo**: decision
- **qué y por qué**: la rama es `hardcode83/design-system-tokens` (nombre que deja el
  bootstrap del worktree), no `sdd/design-system-tokens`, y no existe rama remota.
  `STATE.md` todavía no registra `head_branch`, así que nada está corrompido —pero
  `mark-ready` grabará como evidencia de merge la rama que esté activa, y `/sdd:ship`
  publicará ese nombre. Renombrar (`git branch -m`) es local, no mueve código y no toca
  el registro de worktrees, que resuelve por ruta. Hacerlo **antes** de
  `mark-local-verified`.
- **comando de reanudación**: `git branch -m sdd/design-system-tokens` y después
  `/sdd:review design-system-tokens`

## 9. La implementación de la sección 11 está en el árbol de trabajo, no en HEAD

- **fase**: review · **tipo**: decision
- **qué y por qué**: HEAD es `c64a4d3` (`chore(sdd): metrics de la fase run de design-system-tokens`),
  el último commit del run-phase. Las once tareas de la sección 11 —los seis arreglos del guard
  (11.1-11.6), las tres decisiones de Jose (11.7 R6.4, 11.8 ancla docs, 11.9 clave huérfana),
  la corrección de la deriva documental (11.10) y la regla de hogares únicos (11.11)— y el
  renombrado de rama (11.13) están **todos en el working tree, sin commitear**: `git status`
  lista 14 ficheros modificados (996 líneas añadidas, 100 borradas) y `BLOCKED.md` mismo es
  untracked. La consecuencia para review es estructural y no negociable:
  - Lanzar el panel sobre HEAD `c64a4d3` certificaría un commit que NO contiene las correcciones
    que cierran las entradas 1-7 de este fichero. El veredicto sería PASS por contenido que
    existe sólo en el árbol de trabajo, y eso es exactamente el patrón que la memoria
    `review-must-check-implementation-is-committed` describe y la regla 4b del skill prohíbe.
  - `mark-local-verified` y `mark-ready` grabarían `implementation_sha = c64a4d3` y la PR se
    mezclaría con ese SHA. Cualquier persona que releyera el merge vería un diff sin las
    correcciones del guard, y la spec que se escribiera al archivar leería los requisitos R1.5,
    R6.5, R6.6 contra un árbol que las incumple.
  - El propio task 11.13 lo dice con claridad: «El renombrado es local, no mueve código y no
    toca el registro de worktrees… `mark-ready` graba como evidencia de merge la rama activa y
    `/sdd:ship` publica ese nombre. El renombrado es local, no mueve código» — el SHA
    certificado es lo único que el merge recordará.
- **comando de reanudación**: hacer commit del working tree (mínimo: un commit para los seis
  arreglos del guard de 11.1-11.6 + el guard de ausencia R1.1; otro para 11.7/11.8/11.9; otro
  para 11.10/11.11 — la separación exacta la decide quien lo commitea), `git add` de
  `BLOCKED.md` y de `sdd/metrics.md` (este último por `metrics-commit-must-precede-anchor`),
  y entonces `/sdd:review design-system-tokens`. El panel corre entonces contra un SHA que
  contiene lo que dice contener, y la cadena de evidencia queda cerrada.
