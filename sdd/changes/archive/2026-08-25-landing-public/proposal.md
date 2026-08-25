# Proposal: landing-public

## Why

Hoy `frontend/app/(workspace)/page.tsx` es un `redirect("/dashboard")` que convierte la raíz de la app en un formulario de login para cualquiera que llegue sin sesión. AutoHostAI no tiene página pública de producto y la necesita para que un visitante anónimo pueda entender de qué va antes de autenticarse. La decisión de Jose del 2026-08-23 —analizada en `sdd/roadmap/landing-public.md`— es lo que abre esta entrada, con dos conflictos conocidos que este proposal resuelve: la landing enmienda el `SHALL` de `specs/frontend-foundation.md:60` (*«Every surface is noindex, nofollow»*) y cambia el punto de entrada de la app, y choca con el principio 3 de `steering/product.md` (*«MVP de calidad producción end-to-end … nunca maqueta visual»*) si la entregamos como apariencia sin sustancia. Diseño de referencia: `docs/design/2026-08-23-stitch-export/landing_page_executive_emerald_style/` (escritorio, 1280 px) y `landing_page_m_vil_estilo_emerald/` (móvil, 390 px), que son la misma página responsive, no dos diseños.

## What changes

Existirá una superficie pública en `/` que se sirve a visitantes anónimos y cede el paso a `/dashboard` cuando hay sesión. Reutiliza `PublicShell` (`features/shell/components/public-shell.tsx`) con el conmutador de idioma como única isla cliente, hereda paleta y tokens del export de Stitch a través de `design-system-tokens`, y compone cinco bloques: hero, cuatro features (Reservas Centralizadas, Limpieza y Mantenimiento, Control de Incidencias, Analítica Avanzada), stats de afirmación de producto (sin cifras), CTA final y footer. Toda la copia vive en `locales/{es,en}/landing.json`; la metadata es específica (título propio, Open Graph propio, `canonical`); la página es la única superficie indexable del árbol. El redirect de `/` se mueve de `(workspace)/page.tsx` a un segmento donde la decisión anónimo/autenticado se toma en el servidor.

## Requirements

### R1 — La raíz muestra la landing al anónimo y sigue llevando al dashboard al autenticado

**As a** visitante anónimo que llega a la raíz de la app, **I want** ver una página pública de producto, **so that** entienda qué es AutoHostAI antes de autenticarse.

Acceptance criteria:

1. WHEN una petición a `/` llega sin sesión activa, THE SYSTEM SHALL servir la landing pública con `200 OK` y el contenido HTML completo, sin redirigir a `/login` ni a `/dashboard`.
2. WHEN una petición a `/` llega con sesión activa, THE SYSTEM SHALL redirigir a `/dashboard` con `307 Temporary Redirect`.
3. THE SYSTEM SHALL mover el `redirect("/dashboard")` que hoy reside en `frontend/app/(workspace)/page.tsx` a un segmento donde la decisión anónimo/autenticado se tome en el servidor; el path `/` no cambia para los consumidores que ya apuntan a él.
4. IF la sesión caduca durante el render de la landing, THEN THE SYSTEM SHALL servir la versión anónima sin error visible al visitante.

### R2 — La landing es la única superficie indexable del árbol

**As a** motor de búsqueda que rastrea el dominio público, **I want** encontrar la landing pública, **so that** los visitantes externos descubran el producto. **As a** mantenedor, **I want** que ninguna pantalla con datos de tenant se vuelva indexable por accidente, **so that** la postura de privacidad no se debilite.

Acceptance criteria:

1. THE SYSTEM SHALL producir metadata específica para la landing: un título propio fuera de la plantilla `%s | AutoHostAI`, una descripción localizada, Open Graph específico —no el genérico del route registry—, `canonical` a su URL absoluta y `robots: { index: true, follow: true }`.
2. THE SYSTEM SHALL mantener `robots: { index: false, follow: false }` para todas las demás superficies del árbol —incluyendo el portal del huésped en `/guest/[token]`, que sigue siendo `noindex/nofollow` sin `canonical` conforme a `specs/guest-portal.md:36`.
3. THE SYSTEM SHALL centralizar la excepción en `lib/metadata/create-route-metadata.ts` declarando la landing como el único caso indexable **por nombre de ruta**, no por un flag genérico que cualquier otra pantalla pueda activar por accidente.
4. WHEN esta entrada se archive, THE SYSTEM SHALL modificar el `SHALL` de `specs/frontend-foundation.md:60` para que rece: *«toda superficie es `noindex, nofollow` salvo la landing pública, que es la única indexable»*, con la misma forma de excepción nombrada, no genérica.

### R3 — La landing se entrega como un único diseño responsive y reutiliza el shell público

**As a** visitante que abre la landing en móvil o escritorio, **I want** ver una página coherente en ambos formatos, **so that** la lectura y la interacción sean equivalentes. **As a** mantenedor, **I want** que la landing no introduzca un shell nuevo ni duplique chrome que ya existe, **so that** la consistencia del producto no se resienta.

Acceptance criteria:

1. THE SYSTEM SHALL implementar la variante responsive como un solo diseño que cubre el escritorio (≥768 px) y el móvil (<768 px), sin rutas separadas por breakpoint.
2. THE SYSTEM SHALL renderizar la landing dentro de `PublicShell` (`features/shell/components/public-shell.tsx`) y ampliar el docstring del componente para declarar que sirve `/` además de `/login` y `/forgot-password`; no se crea un shell nuevo.
3. THE SYSTEM SHALL dibujar la barra de navegación de marketing únicamente con enlaces que tienen destino real —`Login` y anclas internas de la propia página (`#features`)— y SHALL NOT renderizar enlaces a `Pricing`, `Portfolio`, `Team` o `Sign Up` mientras no existan sus páginas correspondientes.

### R4 — La copia vive en `locales/{es,en}/landing.json`, sin hardcoding

**As a** usuario que lee la landing, **I want** que la copia esté en mi idioma y sea localizable a futuro, **so that** la página se mantenga sin tocar componentes.

Acceptance criteria:

1. THE SYSTEM SHALL registrar el namespace `landing` en `locales/es/` y `locales/en/` con todas las cadenas visibles de la página —hero, cuatro features (título y cuerpo cada una), stats, CTA final, footer— y SHALL NOT escribir ninguna de esas cadenas como literal en componentes.
2. THE SYSTEM SHALL cumplir el invariante de `steering/frontend.md` y `steering/documentation.md`: cero strings hardcodeados, y los dos locales con cobertura completa —no hay clave en `es/landing.json` que falte en `en/landing.json`.
3. THE SYSTEM SHALL añadir un test que enumere `Object.keys(es.landing) === Object.keys(en.landing)` para impedir divergencia silenciosa entre los dos catálogos.

### R5 — El bloque de stats publica afirmaciones de producto, no cifras inventadas

**As a** visitante que evalúa la credibilidad de AutoHostAI, **I want** leer afirmaciones verdaderas sobre el producto, **so that** mi confianza no se construya sobre datos falsos.

Acceptance criteria:

1. THE SYSTEM SHALL componer el bloque de stats con dos frases en `JetBrains Mono` (la fuente del export para cifras), sin números ni porcentajes —afirmaciones de producto verificables por la prosa que las rodea, no métricas de tracción.
2. THE SYSTEM SHALL NOT publicar las cifras «500+ Propiedades gestionadas» ni «99% Satisfacción de propietarios» que aparecen en la maqueta de Stitch, porque contradicen `steering/product.md` (dos viviendas en Madrid: REDES11 y PAJARITOS8; SaaS multi-tenant en fase futura) y el principio 3 del mismo steering (*«MVP de calidad producción end-to-end … nunca maqueta visual»*).
3. WHEN esta entrada se archive, THE SYSTEM SHALL documentar en `docs/landing.md` *(no existe aún — se creará al archivar)* el encuadre de las dos afirmaciones elegidas y el motivo de no usar cifras, de forma que un visitante o mantenedor futuro entienda la decisión sin leer el proposal.

### R6 — La landing no toca el contrato de la API ni ninguna pantalla existente

**As a** mantenedor del backend o de cualquier feature ya entregada, **I want** que este change no introduzca endpoints, DTOs ni mutaciones sobre lo entregado, **so that** la superficie de regresión sea nula.

Acceptance criteria:

1. THE SYSTEM SHALL NOT añadir, modificar ni eliminar rutas de la API en `backend/app/`, ni DTOs en `backend/openapi.json`, ni métodos del cliente generado en `frontend/lib/api/generated/openapi.d.ts`. El contrato versionado queda intacto.
2. THE SYSTEM SHALL NOT modificar ninguna pantalla existente —dashboard, propiedades, reservas, incidencias, limpieza, timelines ni pricing permanecen píxel-equivalentes a su estado pre-change en sus rutas respectivas.
3. THE SYSTEM SHALL NOT introducir un endpoint de registro público: `auth-tenancy` no expone alta y un `Sign Up` que no registra a nadie queda fuera de alcance.

## Out of scope

- **Las páginas `Pricing`, `Portfolio`, `Team` y `Sign Up`**: no existen y esta entrada no las crea. Sus enlaces en la barra de marketing no se renderizan hasta que haya adonde ir.
- **La variante `landing_page_mobile_autohostai`** del export de Stitch: copia en inglés y set de features distinto (Gestion Inteligente, Analitica Avanzada, *Secure Infrastructure*); se descarta como página. Se salva únicamente su encuadre (*«instrumentation-grade / mission control»*) si Jose lo quiere como decisión de copia, no de maqueta.
- **El visual restyle de las pantallas ya entregadas** (`/dashboard`, `/properties`, `/reservations`, `/incidents`, `/cleaning`, `/pricing`, `/timeline`): vive en `visual-restyle-workspace`, que `needs: design-system-tokens` y se ejecutará después de este change.
- **Registro público de usuarios**: `auth-tenancy` no expone alta pública y esta entrada no la añade.
- **Páginas legales, política de privacidad, términos de uso**: si la indexación las hace necesarias, son entradas propias y separadas.
- **Amend de `specs/guest-portal.md:36`**: su `noindex/nofollow` sin canonical se mantiene tal cual; R2.2 lo cita como parte del conjunto de superficies noindex que sobreviven a la excepción.

## Affected specs

- `sdd/specs/frontend-foundation.md` — se modifica el `SHALL` de línea 19 (*«redirect `/` to `/dashboard`»*) para que el comportamiento dependa del estado de sesión, y el `SHALL` de línea 60 (*«Every surface is `noindex, nofollow`»*) para declarar la landing como la única excepción nombrada. También se actualiza el inventario de rutas de línea 96 y la lista de ficheros de `specs/local-environment.md:500`.
- `sdd/specs/guest-portal.md` — **no se modifica**. Su `SHALL` de línea 36 (*«genérica, `noindex/nofollow`, sin token ni canonical»*) se mantiene y se cita desde R2.2 como parte de las superficies que siguen siendo noindex tras la excepción.
- `sdd/steering/frontend.md` — **no se modifica**. La regla *«toda string visible pasa por `locales/es/` y `locales/en/`»* ya cubre R4 sin enmienda.
- `sdd/steering/documentation.md` — **no se modifica**. Su regla de *«String de UI nueva → claves en `locales/es/` y `locales/en/`»* ya genera la tarea de i18n.
- `docs/landing.md` *(no existe aún — se creará al archivar)* — página de capability de cara a producto, orientada a cómo se presenta AutoHostAI al visitante, con el encuadre de las dos afirmaciones del bloque de stats y la lista explícita de lo que la landing **no** promete.
