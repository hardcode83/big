# Tema visual y capa de tokens del frontend

El frontend expone una capa de tokens de marca (color, tipografía, ritmo y radios) y un conmutador de tema de tres estados alcanzable desde la topbar de los cinco shells —directamente en la barra a partir de 640 px de ancho, y dentro del desplegable «Preferencias» por debajo—. La especificación EARS y las decisiones viven en la propuesta y diseño del change — [`sdd/specs/design-system-tokens.md`](../sdd/specs/design-system-tokens.md) y [`sdd/changes/archive/2026-08-24-design-system-tokens/`](../sdd/changes/archive/2026-08-24-design-system-tokens/). Esta página describe el uso y la operativa.

## Elegir tema

La topbar de cada shell (`workspace`, `cleaner`, `technician`, `public`, `guest`) da acceso a un grupo de tres iconos, a la izquierda del selector de idioma:

- **Sol** — fijar tema claro.
- **Luna** — fijar tema oscuro.
- **Monitor** — seguir al sistema operativo. Borra la cookie y devuelve el control a la preferencia del sistema.

**Dónde están, según el ancho de la pantalla.** A partir de 640 px los tres iconos están en la propia barra, junto al selector de idioma. Por debajo —un móvil de 360 px, por ejemplo— no caben: la barra mostraría desplazamiento horizontal, así que el tema y el idioma se recogen detrás de un botón «Preferencias» (icono de ajustes) que abre un cajón inferior con los dos controles dentro, con los mismos nombres accesibles y el mismo efecto. La campana de notificaciones y el menú de usuario **no** se recogen: muestran estado e identidad, y esconderlos tras un toque quitaría información que ahora se ve de un vistazo. El reparto lo elige el CSS por media query, así que ensanchar la ventana devuelve los controles a la barra sin recargar.

El botón activo se comunica por `aria-pressed` sobre la **preferencia elegida**, no sobre el tema resuelto: si el sistema operativo está en oscuro y el botón activo es «Monitor», la página se pinta oscura pero el botón presionado es «Monitor», porque eso es lo que la usuaria eligió. Cada icono tiene un tooltip con la palabra traducida (un icono solo no distingue «claro» de «sistema»).

La mutación ocurre al pulsar: la cookie y el atributo `data-theme` en `<html>` se actualizan a la vez, sin recargar la página. Elegir «Sistema» borra la cookie (`max-age=0`) y elimina el atributo — los dos a la vez — para que la siguiente navegación obedezca al sistema.

## «Seguir al sistema»

Es el tercer estado, no un valor persistido. La cookie `autohostai.theme` solo contiene `light` o `dark`; su ausencia es «sigue al sistema». Por eso:

- En `localStorage` o en las herramientas de cookies puede verse vacía después de elegir «Sistema».
- En una sesión privada o en un navegador nuevo, el comportamiento por defecto es seguir al sistema.
- Cambiar la preferencia del sistema operativo (modo oscuro del navegador) surte efecto al pulsar «Sistema» o al recargar la página.

## Dónde se guarda

| dato | valor |
|---|---|
| nombre de cookie | `autohostai.theme` |
| valores | `light` \| `dark` |
| ausencia | «sigue al sistema» (tercer estado) |
| `path` | `/` |
| `samesite` | `lax` |
| `max-age` | 1 año (`31536000`) cuando hay valor; `0` para borrar |
| dato personal | ninguno |

La cookie no lleva dato personal y su postura es la misma que la del idioma (`autohostai.locale`): se escribe por una acción de la usuaria, no se usa para tracking.

## Cómo se aplica

El tema se resuelve en el servidor, leyendo la cookie por cada request, y se vuelca en el atributo `data-theme` del elemento `<html>` desde `app/layout.tsx`. El primer HTML que recibe el navegador ya lleva el tema correcto, así que no hay flash del tema equivocado al cargar ni script anti-FOUC. La cookie y el atributo se sincronizan en servidor y en cliente: lo que pone el servidor es lo que se lee, lo que escribe el cliente al pulsar es lo que la siguiente navegación ve.

El tema **no** se guarda en Zustand ni en ningún store de cliente: un store se hidrata después del primer pintado, así que cualquier lectura cliente provocaría un parpadeo. Lo que sí existe es una función pura `resolveTheme()` en `lib/theme/theme.ts` que decide si un valor es válido y devuelve `null` para «sigue al sistema», y un `getServerTheme()` server-only que la usa.

## Cómo se distinguen los dos temas

`app/globals.css` declara la misma colección de tokens en los dos temas. En claro se aplica `:root`; en oscuro se aplica un bloque bajo `@media (prefers-color-scheme: dark)` **acotado con `:root:not([data-theme="light"])`** y, otra vez, un bloque bajo `:root[data-theme="dark"]`. Los dos bloques oscuros son idénticos valor por valor; la duplicación existe para que el atributo venza a la preferencia del sistema en **las dos direcciones** —forzando claro sobre un sistema oscuro igual que oscuro sobre uno claro— sin necesidad de `!important`.

El token primario canónico es `#006b5f` en claro y `#70d8c8` en oscuro. El contraste de cada par declarado (texto, controles y badges sobre las cuatro superficies) lo mide un test, no una tabla, porque una tabla envejece y un test recomputa: `app/globals.contrast.test.ts` parsea los bloques y falla por debajo del umbral de WCAG 2.2 AA.

## Conmutador e idioma

El conmutador de tema y el selector de idioma comparten el mismo slot `end` de la topbar —y el mismo desplegable «Preferencias» cuando la pantalla es estrecha— y siguen el mismo patrón: cookie server-side, atributo en `<html>`, mutación en cliente al pulsar, sin provider ni estado global. El conmutador de idioma es ahora un único botón con tooltip (cambia de ES a EN o al revés), después del rediseño que vino con el change.

## Lo que NO hace

- **No cambia el contrato de API ni el backend.** Ninguna cabecera, ningún endpoint ni ningún DTO dependen del tema.
- **No introduce una clase `.dark` ni `dark:` por componente.** Los consumidores leen tokens, no variantes. Un componente que necesite un color distinto en cada tema no añade `dark:bg-…`: cambia de token.
- **No carga fuentes de un tercero en runtime.** Inter y JetBrains Mono entran vía `next/font`, que las descarga en tiempo de build y las sirve desde el propio origen.
- **No define un valor persistido para «sistema».** Si se ve `autohostai.theme=system` en una cookie, es un cliente o un script fuera de la aplicación.

## Límites y casos borde

- **Recargar la página con cookie puesta**: el servidor lee la cookie y aplica el tema antes del primer HTML, sin parpadeo.
- **Recargar la página sin cookie**: se aplica el tema según `prefers-color-scheme` del navegador.
- **Cambiar la preferencia del sistema operativo con cookie puesta**: el atributo sigue ganando. Para volver a obedecer al sistema, elegir «Monitor».
- **Modo incógnito o primera visita**: cookie ausente, atributo ausente, tema según `prefers-color-scheme` del navegador.
- **Bloqueo de cookies en el navegador**: el conmutador mutará el atributo en la pestaña actual pero la preferencia no sobrevivirá a recargas; el comportamiento de «Monitor» no se ve afectado.

## Verificación rápida

Para comprobar que el mecanismo está vivo:

1. Abrir la topbar — los tres iconos están a la izquierda del selector de idioma, con un tooltip traducido al pasar el ratón. En una ventana de menos de 640 px hay que abrir antes el botón «Preferencias».
2. Pulsar la luna — el fondo de la página cambia a oscuro en el mismo instante, sin recarga; la cookie `autohostai.theme=dark` aparece en las herramientas de cookies; el atributo `data-theme="dark"` aparece en `<html>`.
3. Recargar la página — sigue oscuro, sin flash de claro.
4. Pulsar el monitor — el fondo vuelve al tema del sistema operativo; la cookie se borra; el atributo desaparece.
5. Cambiar la preferencia de tema del sistema operativo — la página cambia con el sistema.
6. Repetir con sol, monitor y los tres navegadores objetivo.
7. Estrechar la ventana por debajo de 640 px — los tres iconos se recogen en «Preferencias»; elegir un tema desde el cajón y volver a ensanchar **sin recargar** deja pulsado el botón correcto en la barra, porque las instancias leen el atributo de `<html>` y no un estado propio.
