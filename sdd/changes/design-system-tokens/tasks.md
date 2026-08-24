# Tasks: design-system-tokens

Todo el change es de `frontend/`. No se toca backend, contrato de API ni tipos
generados (design §Data & interfaces), así que **no** aplica el apaño de
`api:generate` en worktree.

Comandos: el stack de este worktree se levanta con `make up` desde la raíz, y la
suite corre dentro del contenedor (`sdd/project.md` §Commands / §Worktree bootstrap).

## 1. Punto de partida medido

<!-- Punto de partida medido el 2026-08-24 en este worktree (tarea 1.2), no heredado:
     · suite: 123 ficheros, 1130 tests (1092 pasan, 5 skipped). Los 25 fallos de la
       medición son de entorno, no del árbol: 19 «Test timed out in 5000ms», 4
       «[vitest-pool]: Worker forks emitted error» y 1 «Axe is already running»,
       y el conjunto cambia entre ejecuciones — la máquina tiene otros tres stacks
       de worktree corriendo. Ninguna aserción falla.
     · los dos ENOENT de entorno (`features/provenance/workflow-contract.test.ts`,
       `lib/config/build-identity-contract.test.ts`) desaparecen con los
       `docker compose cp` de `sdd/project.md` (tarea 1.1).
     · color crudo: 68 apariciones de escala numérica en 18 líneas de 4 ficheros
       (property-state-badge.test.tsx 24, lib/ui/status-tone.ts 24,
       incidents/…/incident-detail-sections.tsx 10, incidents/…/incidents-view.tsx 10).
     · `dark:`: 25 apariciones en 9 líneas de 2 ficheros
       (property-state-badge.test.tsx 13, lib/ui/status-tone.ts 12).
     Coincide con lo que el design daba por medido. -->

- [x] 1.1 Levantar el stack del worktree (`make up`) y aplicar los `docker compose cp`
      de `sdd/project.md` §Worktree bootstrap, para que los dos ficheros que leen por
      encima de `/app` (`features/provenance/workflow-contract.test.ts`,
      `lib/config/build-identity-contract.test.ts`) dejen de dar `ENOENT`.
      Hecho = `docker compose exec -T frontend npm test` sin esos dos fallos de entorno.
- [x] 1.2 Registrar en el propio commit (mensaje o nota de la sección) la cifra de
      partida real de la suite —ficheros y tests— y el recuento de partida del color
      crudo: `grep -rEn '(bg|text|border|ring|from|via|to|decoration|outline|fill|stroke|shadow|accent|caret|divide|placeholder)-(slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-[0-9]{2,3}' frontend/app frontend/components frontend/features frontend/lib | wc -l`
      y el equivalente para `dark:`. El design dice 68 usos en 4 ficheros y 25 `dark:`;
      se **mide**, no se hereda. [R6.6]

## 2. La capa de color: tres bloques y su test de paridad <!-- panel: PASS 2026-08-24 -->

<!-- Nota de alcance de 2.1, levantada por el panel: `:root` queda con SOLO los 25
     tokens de color, porque es lo que hace que comparar bloques enteros signifique
     algo en el test de paridad. Eso obligó a sacar de `:root` el `--radius: 0.5rem`
     de hoy y a dejar sus tres derivados como literales numéricamente idénticos
     (`0.5rem` / `0.375rem` / `0.25rem` = `0.5rem` menos 0, 2px y 4px), un toque de
     R5.1 que las etiquetas de 2.1 no mencionan. Sin cambio de valor ni de aspecto;
     la escala de cinco pasos del export sigue siendo trabajo de 3.5. Los tokens no
     temáticos (ritmo, tipografía, radios) van a `@theme`, no a `:root`. -->

<!-- Panel de la sección 2 (2026-08-24): architect PASS, i18n PASS, documentation
     PASS, qa PASS, security FAIL con 2 hallazgos, los dos aceptados y arreglados:
       · R1.6 — el `border` claro estaba registrado a 1.32:1 y mide 1.23:1 (1.32 era
         contra `--surface`, no contra `--background`), así que las dos filas del
         mismo par declarado medían pares distintos. Corregido en design.md §D9 y
         §Contraste medido, con nota de por qué se movió la cifra.
       · D1 — el guard estaba anclado en selectores con nombre, así que un cuarto
         bloque añadido después (una clase `.dark`, un `@media … light`) podía
         redeclarar `--background`, ganar por orden y dejarlo verde. Añadida una
         aserción que cuenta: cada token declarado exactamente 3 veces.
     Y dos riesgos residuales que el panel nombró sin poder anclarlos en un `SHALL`
     de la sección, arreglados igualmente porque eran ciertos:
       · deriva correlacionada (el mismo valor equivocado en los DOS bloques oscuros)
         y errata en un valor claro — ninguna es «deriva entre las copias», así que
         ninguna aserción las veía. Cerradas fijando la tabla aprobada de design.md
         §Paleta como valores esperados absolutos, que es además la evidencia de
         R2.1/R2.2.
       · el emparejador de llaves contaba `{`/`}` dentro de comentarios, así que un
         comentario con una llave desbalanceada lo hacía desbordar al bloque
         siguiente y fallar por una razón que no señalaba la causa. Se eliminan los
         comentarios antes de parsear.
     Verificado por mutación que los tres casos antes ciegos ahora fallan y que la
     llave en comentario ya es inocua.

     Segunda ronda: la re-revisión de security cerró el hallazgo de R1.6 y encontró
     dos evasiones MÁS al guard, las dos confirmadas ejecutando, las dos arregladas:
       · el recuento exigía `;` final, y CSS lo hace opcional en la última
         declaración de un bloque. Un bloque de una sola declaración escrito sin él
         repintaba `--background` y el guard seguía verde — y nada del proyecto lo
         atrapa: `lint` es `eslint .`, que no lee `.css`, y no hay
         prettier/stylelint/biome. El terminador pasa a `[;}]`.
       · los 25 alias `--color-*` no se contaban, y son los que leen los
         consumidores (este mismo fichero asserta sobre `var(--color-ring)`,
         `var(--color-border)`, `var(--color-background)`). Un `:root { --color-background: … }`
         posterior repintaba la app dejando los 25 tokens crudos intactos y
         «aprobados». Se cuentan los alias (una vez cada uno) y se exige que haya
         exactamente UN bloque `@theme inline`, porque `THEME_INLINE` lee el primero.
     Verificado con las construcciones literales del revisor: las tres fallan ahora.
     Corregido además `filaña` -> `franja` en design.md D9, errata dentro del texto
     que la primera ronda reescribió. -->

- [x] 2.1 Reescribir el bloque de color de `frontend/app/globals.css` con los **25 tokens**
      de design §Paleta (15 de núcleo + 10 de estado) en los tres bloques exactos de D1
      —`:root` (claro), `@media (prefers-color-scheme: dark) :root:not([data-theme="light"])`,
      y después `:root[data-theme="light"]` / `:root[data-theme="dark"]`— con `color-scheme`
      en cada uno y el orden de fichero que D1 fija. Exponerlos a Tailwind por `@theme inline`
      (`--color-*`), **sin** crear `tailwind.config.{js,ts}` (`components.json` mantiene
      `"tailwind": {"config": ""}`). `border` e `input` quedan separados con los valores de D9.
      [R1.1, R1.3, R1.4, R2.1, R2.2, R2.4, R5.2, R6.1]
- [x] 2.2 Nuevo `frontend/app/globals.tokens.test.ts`: parsea `globals.css`, extrae los tres
      bloques y afirma (a) que declaran el **mismo conjunto de nombres** de token y (b) que
      los dos bloques oscuros declaran **valores idénticos**. Es lo que hace segura la
      duplicación que impone D1. [R1.2]
- [x] 2.3 Verificar en el mismo test —o en uno hermano del fichero— que siguen presentes e
      intactos `@layer base` (incluido `:focus-visible`), el bloque
      `@media (prefers-reduced-motion: reduce)` y las utilidades `tap-target` (44×44) y
      `pb-safe`. Sin esto, R5.3 depende de que nadie los borre por descuido al reescribir
      el fichero. [R5.3]

## 3. Tipografía, ritmo y radios <!-- panel: PASS 2026-08-24 -->

<!-- Panel de la sección 3 (2026-08-24): architect PASS + 1 DESIGN-CONFLICT,
     documentation PASS, qa PASS(1), cicd FAIL(1), security FAIL(1). Todo cerrado.

     DESIGN-CONFLICT — `--radius-full`, resuelto con decisión de Jose: se RETIRA.
     R5.1 enumeraba `full`, pero compilando Tailwind v4 se ve que `rounded-full`
     emite `calc(infinity * 1px)` y no lee `var(--radius-full)`; y no hay en todo
     `frontend/` una referencia a `rounded-full`, `var(--radius-full)` ni
     `rounded-(--radius-full)`. Token con cero consumidores = el antipatrón que D2
     rechaza. Es además el mismo razonamiento ya aceptado para `DEFAULT`, así que
     tratar los dos igual hace la regla coherente. Enmienda bajada a proposal.md
     §R5.1 (no sólo a design.md, para que la spec viva no herede un SHALL falso) y
     a design.md D10. La escala queda en `sm`/`md`/`lg`/`xl`.

     R4.1 — security y qa convergieron, por separado, en el mismo agujero: la mitad
     SHALL NOT no estaba cubierta por nada. Un `@import url("https://fonts.googleapis.com/…")`
     en `globals.css:1` pasaba la suite entera y todos los jobs en verde. Y el
     origen del copy-paste está DENTRO del repo: `docs/design/2026-08-23-stitch-export/*/code.html`
     lleva `preconnect` a googleapis/gstatic en 7 ficheros y carga Material Symbols
     desde Google Fonts sin contrapartida autohospedada en este change. Añadido un
     guard en `globals.tokens.test.ts` por FORMA exacta y LISTA de ficheros fija
     —no por grep del dominio, que tropezaría con `docs/design/` y que además se
     sortea—. Cubre: dominios fuera de comentario, cualquier `https?://`,
     `@import url(`, `@font-face` propio, `<link>`/`preconnect`/`preload`, y
     `assetPrefix` en `next.config.ts`, que era la evasión que ningún grep de
     nombres podía ver (los 13 `src` emitidos son relativos). Verificado con las
     cuatro construcciones: las cuatro fallan.

     cicd — el comentario de `layout.tsx` (citando D8) hablaba del «job Production
     build» de frontend-tests.yml, y ese job no existe: es un PASO del job
     `provenance-contract`. Y son TRES sitios de build, no dos — falta
     `build-frontend` de deploy-dev.yml. Corregido en el comentario y en D8.
     Cerrado de paso el peor caso: el runner self-hosted de la VM no construye,
     sólo hace `docker compose pull`, así que la descarga de fuentes no pasa por ahí.

     security, aceptado con condición escrita en D8 (no es hallazgo): los binarios
     de fuente son el único insumo de build sin lockfile, checksum ni SRI. Se acepta
     —la carga es una fuente, no script— y queda escrito CUÁNDO deja de aceptarse:
     al entrar una CSP con `font-src`, o al exigirse un build reproducible/offline.
     Medido también que `subsets: ["latin"]` NO restringe lo emitido (salen bloques
     `unicode-range` cirílico/griego/vietnamita): cuesta tamaño de imagen, no bytes
     de runtime. Anotado en D8 y en el comentario.

     qa, anotado en D8 y no hallazgo: mapear `--font-mono` hace que la utilidad
     `font-mono` preexistente cambie de aspecto en dos pantallas ya entregadas
     (`reservation-detail-sections.tsx:39`, `version-badge.tsx:93`). Es el cambio
     que el proposal declara esperado, y no es lo que R4.4 prohíbe — R4.4 habla del
     rol `data-mono`, que no se aplica a ninguna pantalla.

     documentation — task 10.4 enmendada: el grep va sobre la salida compilada y
     excluye sourcemaps, porque el comentario que explica que no se pide nada al CDN
     contiene el dominio y los `.map` lo embeben. La regresión la cubre el guard. -->

- [x] 3.1 `frontend/app/layout.tsx`: cargar `Inter` y `JetBrains_Mono` desde
      `next/font/google` (`subsets: ["latin"]`, `display: "swap"`, `variable:
      "--font-inter"` / `"--font-jetbrains-mono"`) y poner sus clases en `<html>`. Ninguna
      referencia a `fonts.googleapis.com` ni a otro CDN en el árbol. [R4.1]
- [x] 3.2 `globals.css`: mapear en `@theme inline` `--font-sans` y `--font-mono` a esas
      variables, cada una con su pila de reserva del sistema declarada. [R4.2, R4.4]
- [x] 3.3 `globals.css`: declarar los **10 roles** de `DESIGN.md` como `--text-<rol>` con sus
      tres modificadores (`--line-height`, `--letter-spacing`, `--font-weight`), convirtiendo
      los px del export a `rem` y dejando el tracking en `em` (D10). La escala numérica por
      defecto de Tailwind (`text-sm`, `text-xs`, `text-lg`) **se conserva**. [R4.3]
- [x] 3.4 `globals.css`: declarar los 11 pasos `--spacing-{xs,sm,md,lg,xl,2xl,3xl,4xl,gutter,
      margin-mobile,margin-desktop}` en rem sobre la unidad de 4 px, junto al `--spacing` base.
      [R5.1]
- [x] 3.5 `globals.css`: sustituir `--radius` y sus tres `calc()` derivados por
      `--radius-{sm,md,lg,xl,full}` con valores literales del export. Comprobar —no dar por
      hecho— que el `rounded` desnudo de Tailwind v4 vale ya `0.25rem` y por tanto el
      `DEFAULT` del export no necesita declararse; dejar el resultado escrito. Asumido y
      aceptado: `rounded-sm` pasa de `0.25rem` a `0.125rem` (botón de cierre de `Sheet`).
      [R5.1]
- [x] 3.6 Extender `globals.tokens.test.ts` (o añadir aserciones) para que los roles
      tipográficos, la escala de ritmo y los radios declarados sean los del export y no un
      subconjunto: cuenta y nombres. [R4.3, R5.1]

## 4. La auditoría de contraste, como test <!-- panel: PASS 2026-08-24 -->

<!-- Panel de la sección 4 (2026-08-24): architect FAIL(1 DESIGN-CONFLICT),
     security FAIL(2 bloqueantes + 5 no bloqueantes), qa FAIL(2). Todo cerrado.

     DESIGN-CONFLICT (architect) — D11 decía «las tres superficies» y la auditoría
     mide cuatro, y la ampliación estaba anotada en OTRA sección. Peor que la
     contradicción: cambié lo que una decisión decidió auto-aprobándomelo, cuando
     D10 lleva «aprobada por Jose». Resuelto con decisión de Jose: se mantienen las
     cuatro superficies y la enmienda baja al PROPIO texto de D11, con firma. La
     distinción que el architect marcó y que vale recordar: la cifra del borde de
     D9 era una corrección numérica (el diseño afirmaba algo falso, no hace falta
     permiso); ampliar el conjunto de superficies cambia el alcance de la decisión,
     y eso sí pasa por la regla de desviación.

     BLOQUEANTE 1 (security, confirmado por qa F1) — `--primary` se aseraba sólo a
     3:1 mientras la app lo usa como TEXTO de tamaño normal. Invisible porque
     `--primary` y `--ring` valen lo mismo, así que el único par que tocaba primary
     era `ring on <surface>` con umbral 3:1. `text-primary` es `text-sm` en cinco
     ficheros entregados, y qa añadió `border border-primary` en
     `property-card.tsx:87`, que es un límite 1.4.11. Demostrado, no teórico: con
     light `--primary: #7c727e` los 7 tests pasaban mientras esos enlaces quedaban
     a 4.07:1 y 3.71:1. Añadidos pares primary-como-texto (4.5:1),
     primary-como-borde (3:1) y el compuesto `hover:bg-primary/90` del Button.

     BLOQUEANTE 2 (security) — la premisa del badge era FALSA en el árbol actual.
     El comentario afirmaba como hecho que `TONE_BADGE_CLASS` pinta
     `bg-state-X/15 text-state-X-text border-state-X/40`, y `status-tone.ts` sigue
     con escalas crudas: eso es trabajo de 7.1. Corregido a futuro explícito, y la
     obligación de fijar el acoplamiento queda escrita EN la tarea 7.1 — si 7.1
     escribe `/20` o `text-state-warning`, las 20 combinaciones seguirían verdes
     midiendo algo que la app no pinta.

     No bloqueantes, todos aceptados y arreglados:
       · comparar redondeado dejaba pasar un fallo real: `#007eb7` sobre blanco
         mide 4.4986 y redondea a «4.50 ok». Las puertas comparan sin redondear;
         el redondeo se queda en el registro, que es para humanos.
       · `themeCount()` era circular — qa lo probó: quitar `--muted` de `SURFACES`
         dejaba tres aserciones EN VERDE, y lo único que lo cazaba era un
         `toHaveLength(40)` hermano, por casualidad de que `badgePairs` itera los
         mismos arrays. `corePairs`, la mitad grande, no tenía recuento propio.
         Sustituido por literales que eligió una persona (48/20/24) más el pin de
         `SURFACES`/`TONES`/`THEMES`.
       · la excepción del borde se registraba en 1 de 4 superficies — la misma
         asimetría que el panel de la sección 2 corrigió en design.md. Ahora itera,
         y con ello sale a la luz que en oscuro `--border` == `--muted` (#262a34),
         o sea ratio 1.00: el borde de una tarjeta sobre `bg-muted` es literalmente
         invisible. D9 lo cubre por decorativo, pero el número está registrado.
       · añadida una aserción de que sólo existen las DOS formas exentas que D9
         declara, porque el total por sí solo permitía migrar un par de un conjunto
         aserido al exento sin mover ninguna cuenta.
       · escrito por qué `--secondary` y `--accent` no son superficies, con los
         números que vencerían si `bg-secondary` se generalizara (3.54 / 2.85 /
         4.32, todos bajo umbral).

     Veredictos que el panel cerró sin cambio de código:
       · 4.99 con +0.49 de holgura: riesgo aceptado, no hallazgo. AA es 4.5 y pasa;
         «SHALL corregirlo» se dispara por incumplimiento, no por margen fino. PERO
         security corrigió el énfasis de mi nota: el margen más fino de la paleta es
         `secondary-foreground` sobre `--secondary` en oscuro, **4.60 (+0.10)**, no
         el 4.99. Corregido en design.md.
       · `compositeOver`: confirmado por ESPECIFICACIÓN (CSS Color 5 interpola con
         alfa premultiplicado; `transparent` es negro transparente a alfa 0, así que
         el resultado des-premultiplica a exactamente C). Y una corrección
         epistémica que vale más que el veredicto: mi justificación era «dos
         derivaciones coinciden», y dos implementaciones del MISMO modelo
         equivocado también coincidirían. Reescrita sobre la especificación.
       · `parseHex(undefined)` lanza, así que una errata de token es fallo duro y
         no un `toEqual([])` vacío que pasa. Cierra la duda de vacuidad.
       · el refactor a `test/css-tokens.ts` no debilitó nada: qa re-corrió las
         siete clases de mutación de la sección 2 y las siete siguen cazándose.

     Verificado con las construcciones literales de los revisores: la mutación de
     security (que pasaba los 7) y el encogimiento de qa (que dejaba 3 en verde)
     ahora fallan; la excepción exenta sigue en verde sin blanquear nada.

     Segunda ronda: la re-revisión dio PASS(0 bloqueantes) y verificó los siete
     hallazgos por mutación, pero encontró tres más, los tres arreglados:
       · N1 — arreglé las puertas para comparar sin redondear y me dejé el
         REGISTRO, que es el artefacto de R1.6. Con `--primary: #247e3c`
         (4.499978:1) el registro imprimía «ok 4.50» sobre un par que la puerta
         rechazaba: respuesta equivocada en el entregable, no detalle cosmético.
         Ahora el veredicto sale del valor exacto y sólo el número se redondea.
       · N2 — `kind` era el eje de blanqueo que los literales de tamaño no ven:
         pasar `foreground` de `text` a `ui` baja su umbral de 4.5 a 3.0, no mueve
         ninguna cuenta, no pone `exempt`, y dejaba los 9 tests en verde. Es el
         agujero del hallazgo 4 un campo más allá. Fijado el reparto text/ui por
         categoría (19/32 en core, 20/0 en badges).
       · N3 — el compuesto `hover:bg-primary/90` que acabo de añadir estaba
         medido en 1 de 4 superficies, reintroduciendo justo la asimetría que el
         hallazgo 5 había quitado. Un Button no está clavado a `--background`: su
         suelo es 5.18 sobre `surface-high`, no el 5.32 que anunciaba. Ahora itera.

     Y una condición que security puso al aceptar el aplazamiento del acoplamiento
     del badge a 7.1, que conviene no perder: **el guard 8.1 NO lo cubre**. 8.1
     falla ante escalas crudas de Tailwind, así que un `/20` o un
     `text-state-warning` pasarían por él mientras `badgePairs` mide un badge que la
     app ya no pinta. Si la sección 7 se descoparra o se partiera a otro change, la
     obligación tiene que viajar con ella o convertirse en tripwire entonces.

     Confirmado también, contra el árbol y no de palabra: `--secondary` y `--accent`
     no necesitan el trato de `--primary` (cero usos desnudos de `text-secondary`,
     `text-accent`, `border-secondary`, `border-accent` ni variantes), y 4.60 es de
     verdad el margen más fino de la paleta — nada por debajo. -->

- [x] 4.1 Nuevo `frontend/app/globals.contrast.test.ts`: parsea los hex de los tres bloques,
      calcula el ratio WCAG de cada par declarado —incluida la composición `color-mix` de los
      badges al 15 % sobre las tres superficies— y falla por debajo de 4.5:1 (texto) y 3:1
      (controles), con las excepciones de D9 (`border`, borde de badge al 40 %) como lista
      explícita y comentada. Su salida **es** el registro por par que pide el requisito; el
      helper `getA11yViolations` de `test/render.tsx` desactiva `color-contrast` a propósito
      y no puede cubrirlo. [R1.6]
- [x] 4.2 Cotejar los números que produce el test contra la tabla §Contraste medido de
      `design.md`. Si algún par no coincide, manda el test: corregir el valor del token, no
      la excepción. [R1.6]

## 5. El tema resuelto en servidor

- [ ] 5.1 `frontend/lib/config/constants.ts`: `THEME_COOKIE = "autohostai.theme"`,
      `SUPPORTED_THEMES`, `type Theme`, `isTheme`, declarados junto a los del idioma y con la
      misma postura de cookie (`path=/`, `samesite=lax`, `max-age=31536000`, sin PII). [R3.1]
- [ ] 5.2 Nuevos `frontend/lib/theme/theme.ts` (`resolveTheme(value) → Theme | null`,
      isomorfo, espejo de `resolveLocale`; `THEME_ATTRIBUTE = "data-theme"`) y
      `frontend/lib/theme/server.ts` (`getServerTheme()`, `import "server-only"`, espejo de
      `getServerLocale`). Test propio que fija la tabla de tres estados de D4, incluido el
      caso «valor basura» → `null`. [R3.1, R3.2]
- [ ] 5.3 `frontend/app/layout.tsx`: `<html lang={locale} data-theme={theme ?? undefined}>`
      con el tema resuelto en servidor, para que el primer pintado ya sea el correcto.
      `undefined` deja el atributo **ausente**, que es el tercer estado. Nada de tema en
      Zustand ni resuelto solo en cliente. [R3.2, R3.3]

## 6. El conmutador

- [ ] 6.1 Nuevo `frontend/features/shell/components/theme-switcher.tsx` (cliente): tres
      botones Claro/Oscuro/Sistema en un `role="group"` con `aria-label` traducido,
      `aria-pressed` sobre la **preferencia elegida** (no el tema resuelto), `tap-target` para
      los 44×44 px, y mutación en `useEffect` con el patrón `requested === null` del
      `LocaleSwitcher`: escribe/borra la cookie y pone/quita
      `document.documentElement.dataset.theme`, sin recargar y sin mutar durante el render.
      «Sistema» borra la cookie (`max-age=0`) y hace `delete dataset.theme`.
      [R3.4, R3.5, R3.6]
- [ ] 6.2 Rótulos `navigation.themeSwitcher.{label,light,dark,system}` en
      `frontend/locales/es/navigation.json` y `frontend/locales/en/navigation.json`, nada
      hardcodeado. El test de paridad de catálogos ya vigente los cubre. [R3.5]
- [ ] 6.3 Nuevo `frontend/features/shell/components/theme-switcher.test.tsx`: cubre las tres
      selecciones (cookie escrita, cookie borrada, atributo puesto y quitado), el
      `aria-pressed` correcto en el primer pintado a partir de la prop del servidor, el área
      táctil y axe. Es la verificación real del conmutador: en este worktree la app **no
      hidrata** con `PORT_OFFSET` (`sdd/project.md`), así que no hay pasada visual posible
      aquí y no se toca `next.config` para conseguirla. [R3.4, R3.5, R3.6]
- [ ] 6.4 `frontend/features/shell/components/topbar.tsx` pasa a `async`, llama a
      `getServerTheme()` y su slot `end` por defecto se vuelve
      `<><ThemeSwitcher …/><LocaleSwitcher /></>`. Los cinco shells lo heredan sin tocarse.
      Verificar antes de cerrar la sección que `shell-frame.test.tsx`,
      `workspace-shell.test.tsx` y `field-public-guest-shell.test.tsx` siguen en verde —son
      la red que detecta si algún camino renderiza `Topbar` desde cliente. [R3.2, R3.7]

## 7. Tonos de estado y severidad de incidencias

- [ ] 7.1 `frontend/lib/ui/status-tone.ts`: las cinco entradas de `TONE_BADGE_CLASS` pasan a
      **una** cadena sin `dark:`, sobre los tokens `state-*` y `state-*-text` con los
      modificadores de opacidad de Tailwind v4 (`bg-state-success/15
      text-state-success-text border-state-success/40`). El tono `gray` pasa a
      `state-neutral`, que es el gris de PRD §9.1 que `DESIGN.md` no define. No cambia qué
      tono corresponde a qué estado. [R6.1, R6.2, R6.5, R1.5]
      **Obligación añadida el 2026-08-24** (panel de la sección 4, security): al
      tokenizar esta tabla hay que **fijar el acoplamiento** que
      `globals.contrast.test.ts` da por supuesto. Esa auditoría modela el badge
      como `bg-state-X/15` + `text-state-X-text` + `border-state-X/40`, pero esos
      valores los toma del diseño (D6), no del código: si aquí se escribe `/20`,
      o `text-state-warning` en vez de `text-state-warning-text`, las 20
      combinaciones de badge del test siguen en verde midiendo algo que la app ya
      no pinta. Así que 7.1 debe **asertar las cadenas reales** de
      `TONE_BADGE_CLASS` contra esas alfas y sufijos —o mejor, derivar los
      números de las cadenas— y quitar el «future tense» del comentario de
      `badgePairs`.
- [ ] 7.2 Nuevo `frontend/features/incidents/lib/severity-tone.ts` con
      `SEVERITY_COLOR_GROUP: Record<IncidentSeverity, Tone>` = `{LOW: "gray", MEDIUM: "blue",
      HIGH: "amber", CRITICAL: "red"}` y `severityColorGroup()` con su `?? "gray"`; los dos
      `SEVERITY_COLOR` duplicados de
      `features/incidents/components/detail/incident-detail-sections.tsx` y
      `components/list/incidents-view.tsx` **desaparecen** y sus consumidores pasan a
      `TONE_BADGE_CLASS[severityColorGroup(s)]`. Test del mapa, con el caso no mapeado.
      Cierra el incumplimiento de `sdd/specs/frontend-foundation.md:38`. [R6.3, R6.4]
      Nota de alcance (D6): esos badges son `<span>` sin `border`, así que **no** se les añade
      ancho de borde aquí — eso sería tocar una pantalla.
- [ ] 7.3 Actualizar `frontend/components/property-state-badge.test.tsx`, único test que fija
      cadenas de clase exactas (13 `dark:` + 24 escalas crudas), a las nuevas cadenas.
      Comprobar de paso que `features/pricing/lib/recommendation-status.test.ts` (solo
      comprueba que la clave existe) y la reexportación de `features/cleaning` siguen en
      verde sin tocarse. [R6.7]

## 8. El guard: cero escalas crudas, cero `dark:`

- [ ] 8.1 Nuevo `frontend/test/color-tokens.test.ts` siguiendo el precedente de
      `test/eslint-boundaries.test.ts`: recorre `app/`, `components/`, `features/` y `lib/` y
      falla si encuentra una escala numérica de color de Tailwind o un `dark:` en código **no
      de test**, con las tres excepciones declaradas y razonadas de D12 (`bg-black/50` del
      scrim de `components/ui/sheet.tsx`; `#555`/`#ccc` inline de `app/global-error.tsx`; los
      `*.test.*`). Hecho = el test pasa **y** su recuento va de la cifra medida en 1.2 a 0.
      [R6.6, R1.5]

## 9. Documentación

- [ ] 9.1 `frontend/README.md`: la descripción de estilos deja de hablar de paleta
      placeholder — sección que describa la capa de tokens, los dos temas, el mecanismo de
      cookie + atributo y las fuentes autohospedadas. Verificar además que el `README.md` de
      la raíz no afirma nada que este change deje falso. [R1.1, R3.1, R4.1]
- [ ] 9.2 Grep de la redacción vieja por todo el árbol (`placeholder palette`, «Neutral
      placeholder», «Dark mode follows the OS preference») para que no sobreviva una copia en
      otro documento. Ninguna doc referencia comportamiento eliminado.

## 10. Verificación

- [ ] 10.1 Suite completa en verde: `docker compose exec -T frontend npm test` — comparada
      contra la cifra de partida de 1.2, no contra un número recordado. [R6.7]
- [ ] 10.2 `docker compose exec -T frontend npm run lint` y
      `docker compose exec -T frontend npm run typecheck` en verde. [R6.7]
- [ ] 10.3 `docker compose exec -T frontend npm run build` en verde — es lo que prueba que
      `next/font` descarga y autohospeda las dos familias en tiempo de build (D8), y el punto
      donde la dependencia de red fallaría ruidosamente. [R4.1]
- [ ] 10.4 Comprobar en el build que no queda **ninguna** petición a `fonts.googleapis.com`
      ni a otro CDN de fuentes. **Enmendado el 2026-08-24** (panel de la sección 3,
      revisores documentation y security): el grep se hace sobre la **salida
      compilada** —`.js`, `.css`, `.html` de `.next`— y **excluye sourcemaps y
      comentarios**, porque el comentario de `layout.tsx` que explica que NO se
      pide nada a ese dominio contiene el dominio, y los `.map` embeben el
      comentario. Un grep ingenuo da un positivo falso y R4.1 habla de peticiones
      en runtime, que es lo que mide el grep estrecho. Lo que hay que comprobar,
      y ya está medido: los `@font-face` emitidos apuntan todos a
      `/_next/static/media/` (origen propio), cero `https?://` en el chunk de CSS,
      cero preloads `as="font"`, cero `<link>` de fuente en el HTML prerenderizado.
      La **regresión** la cubre el guard de R4.1 en `globals.tokens.test.ts`, que
      es lo que convierte esta comprobación de una vez en algo que no se puede
      deshacer sin ponerse en rojo. [R4.1]
- [ ] 10.5 Registrar la salida del guard de 8.1 y del test de contraste de 4.1 como la
      evidencia que piden R6.6 y R1.6 — número final de escalas crudas (0) y ratio por par.
      [R1.6, R6.6]

<!-- R2.3 no se activa: la paleta clara quedó aprobada por Jose el 2026-08-23
     (design.md §Open questions 1), así que el change entrega los dos temas y no
     hay bloqueo que registrar ni alcance alternativo que ejecutar. -->
