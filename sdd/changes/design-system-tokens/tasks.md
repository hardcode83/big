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

## 3. Tipografía, ritmo y radios

- [ ] 3.1 `frontend/app/layout.tsx`: cargar `Inter` y `JetBrains_Mono` desde
      `next/font/google` (`subsets: ["latin"]`, `display: "swap"`, `variable:
      "--font-inter"` / `"--font-jetbrains-mono"`) y poner sus clases en `<html>`. Ninguna
      referencia a `fonts.googleapis.com` ni a otro CDN en el árbol. [R4.1]
- [ ] 3.2 `globals.css`: mapear en `@theme inline` `--font-sans` y `--font-mono` a esas
      variables, cada una con su pila de reserva del sistema declarada. [R4.2, R4.4]
- [ ] 3.3 `globals.css`: declarar los **10 roles** de `DESIGN.md` como `--text-<rol>` con sus
      tres modificadores (`--line-height`, `--letter-spacing`, `--font-weight`), convirtiendo
      los px del export a `rem` y dejando el tracking en `em` (D10). La escala numérica por
      defecto de Tailwind (`text-sm`, `text-xs`, `text-lg`) **se conserva**. [R4.3]
- [ ] 3.4 `globals.css`: declarar los 11 pasos `--spacing-{xs,sm,md,lg,xl,2xl,3xl,4xl,gutter,
      margin-mobile,margin-desktop}` en rem sobre la unidad de 4 px, junto al `--spacing` base.
      [R5.1]
- [ ] 3.5 `globals.css`: sustituir `--radius` y sus tres `calc()` derivados por
      `--radius-{sm,md,lg,xl,full}` con valores literales del export. Comprobar —no dar por
      hecho— que el `rounded` desnudo de Tailwind v4 vale ya `0.25rem` y por tanto el
      `DEFAULT` del export no necesita declararse; dejar el resultado escrito. Asumido y
      aceptado: `rounded-sm` pasa de `0.25rem` a `0.125rem` (botón de cierre de `Sheet`).
      [R5.1]
- [ ] 3.6 Extender `globals.tokens.test.ts` (o añadir aserciones) para que los roles
      tipográficos, la escala de ritmo y los radios declarados sean los del export y no un
      subconjunto: cuenta y nombres. [R4.3, R5.1]

## 4. La auditoría de contraste, como test

- [ ] 4.1 Nuevo `frontend/app/globals.contrast.test.ts`: parsea los hex de los tres bloques,
      calcula el ratio WCAG de cada par declarado —incluida la composición `color-mix` de los
      badges al 15 % sobre las tres superficies— y falla por debajo de 4.5:1 (texto) y 3:1
      (controles), con las excepciones de D9 (`border`, borde de badge al 40 %) como lista
      explícita y comentada. Su salida **es** el registro por par que pide el requisito; el
      helper `getA11yViolations` de `test/render.tsx` desactiva `color-contrast` a propósito
      y no puede cubrirlo. [R1.6]
- [ ] 4.2 Cotejar los números que produce el test contra la tabla §Contraste medido de
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
      ni a otro CDN de fuentes: grep sobre el árbol y sobre la salida servida. [R4.1]
- [ ] 10.5 Registrar la salida del guard de 8.1 y del test de contraste de 4.1 como la
      evidencia que piden R6.6 y R1.6 — número final de escalas crudas (0) y ratio por par.
      [R1.6, R6.6]

<!-- R2.3 no se activa: la paleta clara quedó aprobada por Jose el 2026-08-23
     (design.md §Open questions 1), así que el change entrega los dos temas y no
     hay bloqueo que registrar ni alcance alternativo que ejecutar. -->
