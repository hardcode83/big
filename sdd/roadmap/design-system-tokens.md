# design-system-tokens

[FE] **la identidad visual del producto**, traducida del export de Stitch del 2026-08-23
(`docs/design/2026-08-23-stitch-export/`, ver su `README.md`) a la capa `@theme` de
Tailwind v4. No toca ninguna pantalla ni el backend. Es la entrada de la que dependen
`landing-public`, `visual-restyle-workspace` y todas las que salieron del restyle.

La premisa está verificada y no hay que volver a comprobarla: **el hueco lo dejó abierto
el propio código, por escrito.** `frontend/app/globals.css:4-8`:

> *Base design tokens for the Application Shell and shared states (design D2/D14).
> **Neutral placeholder palette only — no definitive branding or full design system.**
> Foreground/background pairs are chosen to meet WCAG AA contrast. Dark mode follows the
> OS preference; **a future theme change may override it**.*

Y no hay competencia: grep de `landing`, `marketing`, `design system`, `branding` e
`identidad visual` sobre `sdd/roadmap.md`, `sdd/specs/frontend-foundation.md` y
`sdd/steering/product.md` devuelve **cero** apariciones. Esta entrada no duplica nada.

Es además la entrada que **solo** contiene diseño, y por tanto la que menos discusión de
alcance arrastra: la regla del export es *«de Stitch se toma el diseño, no los datos ni las
features»* (Jose, 2026-08-23), y aquí no hay nada más que tomar. Ni un dato, ni un
endpoint, ni una pantalla. El censo de lo que se descartó del export está en
`docs/design/2026-08-23-stitch-export/README.md`.

## Decisión 1: claro Y oscuro, con conmutador explícito — y la paleta clara hay que autorla

**Decidido por Jose el 2026-08-23: se ofrecen los dos temas.** Eso convierte la parte más
cara de esta entrada en una que el export **no resuelve**, y hay que decirlo sin adornos:

`DESIGN.md` es **solo oscuro**. Sus ~60 tokens describen una sola cosa —«Midnight
Technical»: fondos de `#0a0e17` a `#353943`, teal `#70d8c8` sobre ellos, glassmorphism y
glows— y las seis maquetas llevan `<html class="dark">` fijo. No hay ni un valor para
tema claro en ningún fichero del export.

**Y la paleta clara no es una derivación mecánica.** La identidad del diseño *es* la
oscuridad: el glow teal difuso funciona porque hay negro detrás, y el glassmorphism
(`backdrop-blur(12px)` sobre superficies al 60-80 % de opacidad) lee como cristal apilado
sobre un fondo profundo. Invertir luminancias token a token da una paleta clara válida en
contraste y muerta en carácter. Lo que esta entrada tiene que producir es **una paleta
clara autorizada por Jose**, no una calculada — y si no la hay, el alcance honesto es
entregar el tema oscuro y dejar el claro en su propia entrada, no inventarla.

Esa es la primera pregunta abierta de la entrada, y la que más puede reencuadrarla.

## Decisión 2: la preferencia va en cookie, leída en el servidor — como ya se hace con el idioma

**No hay que inventar el mecanismo: el proyecto ya tiene uno idéntico funcionando.**
`lib/i18n/server.ts` resuelve el idioma por petición desde la cookie no sensible
`autohostai.locale` (`lib/config/constants.ts:15`), y `app/layout.tsx` la usa para pintar
`<html lang={locale}>` en el servidor. Una cookie `autohostai.theme` leída en el mismo
sitio para pintar `<html data-theme=...>` es el mismo patrón, línea por línea.

Por qué **no** las dos alternativas obvias:

- *Zustand*, que `steering/frontend.md` reserva para «estado ligero de UI»: el store es
  cliente y se hidrata después del primer pintado, así que el tema llegaría tarde y la
  página parpadearía del tema equivocado al bueno en cada carga. El idioma no tiene ese
  problema porque ya se resolvió en servidor — y por eso se resolvió así.
- *Solo `prefers-color-scheme`*, que es lo que hay hoy: no es un conmutador. «Ofrecer la
  opción» es poder elegir contra la preferencia del sistema, y eso necesita un tercer
  estado persistido (`light` | `dark` | sin valor = seguir al sistema).

Consecuencia estructural, y es la razón de fondo para no dejarlo en CSS: hoy el tema
oscuro vive en `@media (prefers-color-scheme: dark)` (`globals.css:26-41`), que **no se
puede vencer desde JavaScript**. Los dos temas tienen que redefinirse bajo un selector de
atributo, con la media query como valor por defecto cuando no hay cookie. Es el mismo
patrón de tres bloques que ya se usa en otros sitios del ecosistema y no tiene sorpresas,
pero es un rediseño de `globals.css`, no un añadido.

## Decisión 3: los tokens se traducen a `@theme`, no se copian

**El export es Tailwind v3; el proyecto es v4.** `package.json` fija
`tailwindcss@^4.3.2` y `@tailwindcss/postcss@^4.3.2`, `components.json` tiene
`"tailwind": {"config": ""}` —sin fichero de config, a propósito— y `globals.css` declara
sus tokens con `@import "tailwindcss"` + `@theme inline`. Las maquetas, en cambio, traen
`<script src="https://cdn.tailwindcss.com">` y un objeto `tailwind.config = {darkMode:
"class", theme: {extend: {colors: {...}}}}` en línea.

Así que el bloque de colores del export **no se pega**: cada token pasa a una custom
property y se expone por `@theme`. Es trabajo mecánico y voluminoso, no difícil — pero
nadie debe intentar reintroducir un `tailwind.config.js`, porque su ausencia es una
decisión de `frontend-foundation`, no un descuido.

Dos cosas más del export que **no** son portables y hay que sustituir, no traducir:

- **Iconos.** El export usa Material Symbols Outlined; el proyecto usa lucide
  (`components.json`: `"iconLibrary": "lucide"`) y `features/shell/navigation/route-registry.ts`
  declara `NavigationIconName` como **unión cerrada** de 17 nombres, resuelta a
  componentes por `icon-map.ts`. Cada icono de la maqueta se re-mapea a su equivalente
  lucide; ninguno se añade a esa unión sin ruta que lo use.
- **Fuentes.** El export carga Inter y JetBrains Mono desde `fonts.googleapis.com`. Hoy
  la app **no carga ninguna fuente**: `app/layout.tsx` no usa `next/font` y el texto sale
  con la pila del sistema. Entran las dos por `next/font/local` o `next/font/google`
  autohospedado — nunca por CDN, que añade un tercero al camino crítico de una app que
  sirve datos de tenant.

## Decisión 4: el gris de PRD §9.1, que el export no define

**Hay que cerrarlo aquí y no en el restyle.** PRD §9.1 fija **cinco** familias de color de
estado operacional —verde, azul, amarillo, rojo y **gris** (`BLOCKED_BY_OWNER`,
`OUT_OF_SERVICE`)— y `DESIGN.md` define cuatro: `state-success` `#10B981`,
`state-warning` `#F59E0B`, `state-error` `#EF4444`, `state-info` `#38BDF8`. **No hay
gris.**

No es un detalle cosmético: `components/property-state-badge.tsx:88` hace
`STATE_COLOR_GROUP[state] ?? "gray"`, así que el gris es además el **fallback** de
cualquier estado no mapeado. Dejarlo sin token deja sin color el caso por defecto.

Dónde va el valor, sin ambigüedad: el mapa de clases vive **una sola vez** en
`frontend/lib/ui/status-tone.ts` (`Tone` y `TONE_BADGE_CLASS`), extraído ahí por la
decisión D22 de `pricing-web` justo para que no haya dos tablas de §9.1 en el árbol. Hoy
su entrada `gray` es `"bg-muted text-muted-foreground border-border"` — es decir, ya está
atada a los tokens semánticos y no a una escala de Tailwind, al contrario que las otras
cuatro (`bg-emerald-100 text-emerald-800 …`). El trabajo es llevar las **cuatro**
restantes al mismo régimen de tokens.

**A favor del export, y conviene registrarlo**: la maqueta del dashboard **sí** respeta el
mapeo de §9.1 — pinta `Cleaning scheduled` en ámbar y `Cleaning in progress` en azul, que
es exactamente lo que dicta el PRD. El diseño no contradice la tabla de colores; solo le
falta una fila.

## Fuera de alcance, explícito

- **Cualquier pantalla.** Esta entrada cambia tokens, primitivas de `components/ui/` y la
  carga de fuentes. Si al aplicarla se ve una pantalla rara, el arreglo es de
  `visual-restyle-workspace`.
- **Glassmorphism, glows y transiciones de hover.** El export los especifica
  (`backdrop-blur`, glows teal a `rgba(0,137,123,0.2)`, `translateY(-1px)` en botón
  primario) y son propiedades de componente, no tokens. Van con las pantallas. Con una
  restricción que hay que arrastrar: `globals.css:84-93` desactiva animaciones y
  transiciones bajo `prefers-reduced-motion: reduce`, así que ninguna de esas
  transiciones puede ser la que comunica un estado.
- **Los artefactos del export** (`PropManage AI`, `© 2024`, footer ×4): son de las
  maquetas, no del sistema de diseño. No se «arreglan» aquí porque aquí no se copian.

## Riesgo principal

Es una entrada de radio amplio y valor invisible: toca todos los componentes compartidos
y no entrega ni una pantalla nueva. El riesgo real no es romper algo —la suite de
`frontend-ci` (vitest + eslint + `tsc --noEmit`) cubre el árbol— sino **quedarse a
medias**: unos componentes con tokens nuevos y otros con la paleta neutra, que es un
estado peor que cualquiera de los dos extremos. El criterio de terminado tiene que ser
«ningún consumidor referencia una escala cruda de Tailwind para color de superficie,
texto o borde», comprobable con un grep, no «se ve bien».
