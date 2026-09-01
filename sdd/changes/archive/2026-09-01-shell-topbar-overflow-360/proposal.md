# Proposal: shell-topbar-overflow-360

## Why

La cabecera compartida desborda a 360 px y arrastra con ella a **todas** las superficies
autenticadas. Medido el 2026-08-29 con Playwright durante la tarea 9.6 de `tech-app`: sobre un
viewport de 360 px la página da `scrollWidth` 433, y el desbordamiento está **entero** en la
cabecera — el contenido de las pantallas no desborda ni un elemento. Se reproduce idéntico en
`/dashboard`, así que no es del técnico: es del `Topbar` que comparten las tres shells
autenticadas.

Duele porque contradice un principio del producto, no solo una métrica. `steering/product.md` dice
que la propietaria «opera desde el móvil» y `steering/frontend.md` manda diseño **mobile-first**;
360 px es el ancho de un móvil corriente, no un caso extremo. Y es también la razón por la que
`R6.3` de `tech-app` se cumple para lo que sus dos pantallas gobiernan y aun así un usuario a
360 px tiene desplazamiento horizontal: la entrada de roadmap la abrió ese change precisamente
porque no podía arreglarlo sin salirse de su alcance.

Entrada de roadmap: `sdd/roadmap.md:249` (`[FE]`, `size: S`, `kind: fix`, sin `needs:`; en la
frontera). No tiene nota `sdd/roadmap/<feature>.md` pese a que su línea acaba en «…» — el detalle
está entero en la propia línea, así que no falta información, solo el sufijo es engañoso.

## What changes

Después de este change, ninguna de las seis composiciones del `Topbar` produce desplazamiento
horizontal a 360 px, y lo consigue **sin quitarle al usuario ningún control y sin encoger ninguna
superficie táctil**: los controles que no caben se reagrupan en un contenedor desplegable en los
anchos estrechos y vuelven a la barra en cuanto hay sitio. La selección entre las dos
disposiciones es por **media query de CSS**, como ya exige `frontend-foundation.md`, y la
comprobación se hace en un navegador real a 360 px, porque una regla de CSS es invisible para
jsdom.

### Dónde está el problema, ya localizado

El slot `end` de `frontend/features/shell/components/topbar.tsx` es un
`<div className="flex items-center gap-2">` que, **a diferencia de los otros dos slots**
(`start` y `center`, ambos `flex min-w-0 items-center gap-3`), no lleva `min-w-0`.

Pero `min-w-0` por sí solo **no puede arreglarlo**, y conviene decirlo aquí para que el design no
empiece por ahí. Las tres shells autenticadas cargan ese slot con cinco controles
(`frontend-foundation.md:25` fija la composición exacta
`[ThemeSwitcher, Separator, LocaleSwitcher, NotificationBell, UserMenu]`) y casi ninguno puede
encoger — el suelo se deriva de sus propias clases:

| Control | Ancho mínimo | De dónde sale |
|---|---|---|
| `ThemeSwitcher` | 136 px | 3 opciones (`light`/`dark`/`system`) × 44 px `tap-target` + 2 × `gap-0.5` |
| `Separator` | 9 px | 1 px + `mx-1` |
| `LocaleSwitcher` | ≥44 px | `tap-target` |
| `NotificationBell` | 44 px **declarados, sin suelo real hasta este change** | `size="icon"` (`h-11 w-11`) fija una anchura de partida, no un mínimo; era el único de los cinco sin `tap-target`, así que como ítem flex encogía hasta su min-content. Medido a 22 px en `/tech` por la guarda de §6 y corregido allí (`design.md` D5) |
| `UserMenu` | ≤192 px | `max-w-48` sobre el email truncado a 24 caracteres |
| separaciones | 32 px | 4 × `gap-2` |

Suman **≥265 px con el `UserMenu` a ancho cero**, y ≥457 px con él en su tope. Sumando el
`px-4` (32 px) de la propia cabecera, el slot `end` reclama ~297 px de los 360 en su mejor caso,
dejando ~63 px para `Brand` + `PageTitle`. El `scrollWidth` 433 medido cae dentro de ese rango
(allí el `UserMenu` no estaba en su tope).

Los 44 px no son negociables: `design-system-tokens.md:31` y `:45` los garantizan por escrito, y
`frontend-foundation.md:28` los exige apuntando a WCAG 2.2 AA. Así que **la salida no es encoger,
es reagrupar**: a 360 px tiene que haber menos cosas en la fila, no cosas más pequeñas.

### El censo de superficies

Seis composiciones montan el mismo `Topbar`. Solo las tres primeras están medidas como rotas:

| Shell | slot `end` | Estado |
|---|---|---|
| `WorkspaceShell` | los cinco controles | **Roto** — medido en `/dashboard` |
| `TechnicianShell` | los cinco controles | **Roto** — medido en `/tech` |
| `CleanerShell` | los cinco controles | Composición idéntica; **sin medir** |
| `(authenticated)` (`/welcome`) | `UserMenu` solo | Sin medir |
| `PublicShell` | default (`Theme` + `Sep` + `Locale`) | Sin medir |
| `GuestShell` | default (`Theme` + `Sep` + `Locale`) | Sin medir |

R1 obliga a medirlas todas antes de declarar nada: tres de ellas nunca se han mirado a 360 px y
`CleanerShell` comparte composición exacta con las dos que están rotas.

## Requirements

### R1 — Ninguna superficie desborda a 360 px

**Como** propietaria o usuaria de campo que opera desde un móvil, **quiero** que la aplicación no
se desplace lateralmente a 360 px de ancho, **para** poder leer y pulsar sin pelearme con la
página.

Criterios de aceptación:

1. WHEN una de las seis composiciones del `Topbar` (`WorkspaceShell`, `TechnicianShell`,
   `CleanerShell`, el grupo `(authenticated)`, `PublicShell`, `GuestShell`) se renderiza en un
   viewport de 360 px de ancho, THE SYSTEM SHALL producir un `document.documentElement.scrollWidth`
   menor o igual que el `clientWidth` del viewport.
2. WHEN se mide el criterio 1, THE SYSTEM SHALL hacerlo en un navegador real, y sobre las seis
   composiciones — incluidas las cuatro que hoy no están medidas.
3. WHILE el ancho del viewport esté entre 360 px y el primer breakpoint en el que la barra vuelve a
   su disposición completa, THE SYSTEM SHALL mantener el criterio 1 en todo el rango, no solo en
   el valor exacto de 360 px.
4. IF alguna de las seis composiciones no desbordaba antes de este change, THEN THE SYSTEM SHALL
   dejarla igualmente sin desbordamiento después (nada de arreglar unas rompiendo otras).

### R2 — Ningún control desaparece

**Como** usuaria en un móvil estrecho, **quiero** seguir teniendo acceso al tema, al idioma, a las
notificaciones y al cierre de sesión, **para** no perder funciones por el tamaño de mi pantalla.

Criterios de aceptación:

1. WHERE la barra adopte su disposición estrecha, THE SYSTEM SHALL mantener alcanzables los cinco
   controles que `frontend-foundation.md:25` fija para las shells autenticadas
   (`ThemeSwitcher`, `LocaleSwitcher`, `NotificationBell`, `UserMenu`, y la separación visual entre
   grupos), sea directamente en la barra o dentro de un contenedor desplegable de la propia barra.
2. WHEN un control se sirva desde el contenedor desplegable, THE SYSTEM SHALL exponerlo con el
   mismo nombre accesible y el mismo efecto que tiene en la barra completa.
3. THE SYSTEM SHALL conservar el `UserMenu` con su confirmación de cierre de sesión
   (`AlertDialog`) intacta: la reagrupación cambia dónde vive el disparador, nunca la secuencia
   `logout → router.replace("/") → router.refresh()`, que pertenece a `frontend-auth-session`.
4. IF la disposición estrecha necesita una etiqueta nueva (el disparador del desplegable, por
   ejemplo), THEN THE SYSTEM SHALL declararla en `frontend/locales/es/` y `frontend/locales/en/`,
   sin texto incrustado en el componente.

### R3 — Las superficies táctiles siguen siendo de 44 px

**Como** usuaria que pulsa con el dedo, **quiero** que los botones no encojan para hacer sitio,
**para** poder acertar a la primera.

Criterios de aceptación:

1. THE SYSTEM SHALL mantener toda superficie táctil de la cabecera en al menos 44 × 44 px en la
   disposición estrecha, incluidos los controles que pasen al desplegable.
2. THE SYSTEM SHALL NOT resolver el desbordamiento reduciendo `tap-target`, cambiando `size="icon"`
   por una variante menor, ni recortando el `max-w-48` del `UserMenu` por debajo de lo que exija su
   propia legibilidad.
3. WHEN el panel de revisión compruebe este change, THE SYSTEM SHALL seguir satisfaciendo las
   garantías escritas en `design-system-tokens.md:31` y `:45` y en `frontend-foundation.md:28`.

### R4 — La disposición la elige el CSS, y el DOM no se duplica de forma observable

**Como** desarrolladora que mantiene el shell, **quiero** que la barra estrecha salga de una media
query y no de una medición en JavaScript, **para** no reintroducir detección de viewport que la
spec ya prohíbe.

Criterios de aceptación:

1. THE SYSTEM SHALL seleccionar entre la disposición completa y la estrecha mediante media queries
   de CSS, nunca mediante detección de viewport en JavaScript — la regla que
   `frontend-foundation.md:23` ya fija para las superficies responsive del shell.
2. IF la solución mantiene en el DOM las dos disposiciones a la vez, THEN THE SYSTEM SHALL
   garantizar que en cualquier ancho la tecnología asistiva encuentre **una sola** instancia de
   cada control: sin nombres accesibles duplicados y sin paradas de tabulación repetidas.
3. THE SYSTEM SHALL mantener el `Topbar` y las shells como Server Components, confinando
   `"use client"` a las islas interactivas que ya lo son (`frontend-foundation.md:15`).
4. WHERE las dos disposiciones coexistan en el DOM y ambas monten el mismo control con estado
   local de preferencia, THE SYSTEM SHALL mantener las dos instancias coherentes: después de un
   cambio de preferencia hecho en cualquiera de ellas, la otra SHALL reflejar la preferencia nueva
   sin requerir navegación ni recarga, y sin guardar la preferencia en Zustand ni en ningún otro
   store de cliente (`design-system-tokens.md:23`). Añadido durante `/sdd:design`: la disposición
   elegida duplica `ThemeSwitcher`, cuyo `aria-pressed` sale hoy de un `useState` por instancia, y
   sin este criterio el botón pulsado de la barra ancha quedaría desfasado tras un cambio de tema
   en la estrecha (OQ-3, resuelta por el usuario el 2026-08-31: se arregla en este change).

### R5 — Queda una guarda que lo detecte la próxima vez

**Como** equipo, **queremos** que este defecto no pueda volver en silencio, **para** no depender de
que alguien repita a mano una medición de Playwright.

Criterios de aceptación:

1. THE SYSTEM SHALL dejar una comprobación automatizada que falle si alguna de las composiciones
   del `Topbar` vuelve a producir desplazamiento horizontal a 360 px.
2. WHERE esa comprobación no pueda vivir en la suite de Testing Library —jsdom no hace *layout* y
   no da `scrollWidth` fiable—, THE SYSTEM SHALL declarar explícitamente dónde vive y cómo se
   ejecuta, en vez de dar por buena una aserción que no mide nada.
3. WHEN la comprobación falle, THE SYSTEM SHALL nombrar la composición concreta que desborda y el
   ancho medido, no un fallo genérico.

## Out of scope

- **Rediseñar la cabecera.** Esto es un `fix` de desbordamiento, no un restyle. La jerarquía
  visual, el orden de los controles y la identidad de la barra se quedan como están; quien quiera
  moverlos tiene `visual-restyle-workspace` (`sdd/roadmap.md:199`), que es donde vive la piel de
  las pantallas ya entregadas.
- **Tocar el contenido de las pantallas.** La medición dice que el desbordamiento está entero en
  la cabecera y que ningún elemento del contenido desborda. Si al medir las seis composiciones
  apareciera un desbordamiento de contenido, es un hallazgo nuevo: se anota, no se arregla aquí.
- **La suite E2E de Playwright como infraestructura.** R5 pide una guarda concreta para este
  defecto, no montar la suite E2E del proyecto — eso es de `hardening-release`
  (`sdd/roadmap.md:252`). Si la guarda necesita andamiaje que no existe, el design decide entre
  construir lo mínimo aquí o declararlo dependencia.
- **`incident-status-tone` y `shared-datetime-formatter`.** Son las otras dos candidatas que
  `tech-app` abrió el mismo día y no tienen nada que ver con el desbordamiento
  (`sdd/roadmap.md:243` y `:245`).
- **Cambiar la composición que `frontend-foundation.md:25` fija.** Este change reagrupa dónde se
  presentan los cinco controles en anchos estrechos; no añade, quita ni reordena controles en la
  disposición completa.

## Affected specs

- `sdd/specs/frontend-foundation.md` — es la spec dueña del `Topbar` y de sus slots. Hay que tocar
  al menos dos SHALL: el de la línea 25, que fija la composición exacta del slot `end` sin decir
  nada de qué pasa cuando no cabe, y el de la línea 23, que enumera los tramos responsive del
  `WorkspaceShell` pero no cubre el `Topbar` compartido por las seis composiciones. Y hay que
  **añadir** la garantía que hoy no existe en ninguna spec: que ninguna superficie desborda
  horizontalmente a 360 px.
- `sdd/specs/design-system-tokens.md` — es la autoridad de los 44 px que R3 defiende (`:31`,
  `:45`), y **ahí no cambia**: el design demostró que la garantía y el arreglo coexisten con 66 px
  de holgura en el peor caso, así que no hubo que reabrirla por ese motivo.

  Sí gana **un SHALL nuevo**, por otro motivo que apareció en `/sdd:design` y que el usuario
  decidió atender aquí (OQ-3, 2026-08-31): la disposición estrecha duplica el `ThemeSwitcher` en
  el DOM, y su `aria-pressed` sale hoy de un `useState` por instancia, así que dos instancias
  montadas se desfasan. R4.4 obliga a que coincidan; el mecanismo elegido es derivar la
  preferencia del atributo de `<html>` —la misma autoridad que esta spec ya designa para el primer
  pintado (`:22`)— en vez de un store, que `:23` prohíbe. La spec tiene que decir eso, porque hoy
  describe el `aria-pressed` sin decir de dónde sale y una futura instancia duplicada volvería a
  romperlo en silencio.

## Coordinación

Hay trabajo en vuelo en otros worktrees. Ninguno declara `frontend/features/shell/` en su alcance,
así que el riesgo de colisión está en los ficheros compartidos, no en los componentes:

- **`tech-app`** (`PR_OPEN`, PR #139) es quien abrió esta entrada. Su §Roadmap candidates nº4
  encargaba a `/sdd:archive` abrir la entrada `[FE]`, y ya está abierta (`sdd/roadmap.md:249`), así
  que **el archive de `tech-app` no debe volver a crearla**. Ese change no toca `features/shell`.
- **R2.4 escribe en `frontend/locales/{es,en}/navigation.json`** si la disposición estrecha
  necesita una etiqueta. Ese fichero lo comparten varios changes en vuelo
  (`guest-portal-messaging`, `blocked-transition-response-ids`), así que conviene añadir claves
  nuevas y no reordenar el fichero, para que el merge sea trivial.

## Verificación: lo que este change no puede dar por hecho

La medición de R1 exige un navegador real a 360 px, y `sdd/project.md` arrastra un aviso —«con
`PORT_OFFSET` la página se sirve pero NO hidrata»— que ya aparcó comprobaciones visuales en más de
un change. El propio `project.md` lo corrige: se midió falso el 2026-08-29 (`PORT_OFFSET=10`, la
app hidrata y es completamente interactiva, conducida con Playwright a 360×780), con la acotación
de `design-system-tokens` de que el fallo es real **solo** para `next dev` con origen cruzado, y
con la salida escrita (`npm run build` + `next start` en un contenedor aparte) para cuando muerde.
Así que **no vale citar ese aviso para no mirar**. Dos filos ya conocidos que cuestan tiempo: la
sesión vive en memoria (hay que entrar y navegar por clic, no recargar cada ruta), y el overlay de
desarrollo de Next intercepta los clics de Playwright (`el.click()` en el DOM lo esquiva).
