# Landing pública

Cómo se presenta AutoHostAI al visitante anónimo que llega a `/` y qué promesa
hace —y qué **no** promete— la página que trajo el change `landing-public`. El
*qué hace* (EARS, decisiones de diseño, contratos) vive en
[`sdd/specs/frontend-foundation.md`](../sdd/specs/frontend-foundation.md) y en
[`sdd/changes/archive/2026-08-25-landing-public/`](../sdd/changes/archive/2026-08-25-landing-public/); esta página es
el *cómo se presenta al visitante* y el por qué de cada decisión visible.

## La raíz es la landing, salvo que ya haya sesión

`/` ya no es un `redirect("/dashboard")`. La decisión se toma en el servidor
a partir de la cookie no sensible `autohostai.session.present`:

- presente y `=== "1"` → `307 Temporary Redirect` a `/dashboard`. El usuario
  autenticado conserva la ruta que ya tenía; el `307` (no `301`) deja que una
  cookie obsoleta que se cruce con un logout se autocorrija en la siguiente
  petición.
- ausente o cualquier otro valor → se renderiza la landing dentro de
  `PublicShell` (`features/shell/components/public-shell.tsx`) con
  `MarketingNav` ocupando el slot central de la topbar. No hay guard de auth
  en cliente; el servidor decide y el cliente no necesita saber.

`PublicShell` es el mismo shell que ya servía `/login` y `/forgot-password` —
los tres viven bajo el grupo de rutas `(public)/` y comparten chrome. La
landing solo añade el slot `marketingNav`; las otras dos lo dejan vacío y su
renderizado es byte-equivalente al de antes del change.

## Lo que la página dice — y por qué

La landing tiene cinco bloques en orden: `Hero` → `FeaturesGrid` (con
`<section id="features">` envuelto por el propio grid, ancla del `MarketingNav`)
→ `StatsBand` → `FinalCta` → `LandingFooter`. Toda la copia vive en
`frontend/locales/{es,en}/landing.json` y se resuelve en servidor con
`getServerT()`; ningún string visible es literal en componentes. La barra de
navegación de marketing solo renderiza destinos reales: `Login` y la ancla
interna `#features`. `Pricing`, `Portfolio`, `Team` y `Sign Up` **no se
renderizan** mientras no existan sus páginas.

### Las cuatro features

Las cuatro tarjetas de la rejilla describen, en una frase cada una, una
capacidad real del producto con su prosa que la respalda en otras superficies
de la app:

| tarjeta | capacidad real | prosa de respaldo |
|---|---|---|
| Reservas centralizadas | vista única de estancia + sync con PMS | `specs/reservations.md`, `specs/pms-beds24-adapter.md` |
| Limpieza y mantenimiento | tareas, fotos, recordatorios | `specs/cleaning.md`, `specs/maintenance.md` |
| Control de incidencias | apertura, asignación, cierre trazable | `specs/incident-photos.md` |
| Analítica operativa | tiempo de respuesta, ocupación, costes | `specs/revenue-pricing.md`, `specs/dashboard-api.md` |

Ninguna promete cifras de tracción.

## El bloque de stats: dos frases, no cifras

El export de Stitch proponía «500+ Propiedades gestionadas» y «99% Satisfacción
de propietarios». Esas dos cifras **no aparecen** en la página:

- Contradicen `steering/product.md`: AutoHostAI opera hoy sobre dos viviendas
  en Madrid (REDES11 y PAJARITOS8); el SaaS multi-tenant es una fase futura,
  no una realidad medible.
- Chocan con el principio 3 del mismo steering (*«MVP de calidad producción
  end-to-end … nunca maqueta visual»*): publicar una cifra de tracción que el
  sistema no puede demostrar convierte la página en una maqueta, no en una
  superficie honesta.

Lo que aparece en su lugar son dos frases en `JetBrains Mono` (la fuente del
export para cifras, aquí reutilizada para texto monoespaciado de banda):

1. *«Una consola para tu operación»* — verificable por cada superficie que ya
   existe: `/dashboard`, `/reservations`, `/incidents`, `/cleaning`,
   `/properties`, `/timeline`, `/pricing`.
2. *«Construido sobre la pila que tu equipo ya confía»* — verificable por el
   stack (Next.js + FastAPI + Postgres + Redis + Celery, mismo set que el
   resto del sistema).

Ambas son afirmaciones de producto, no métricas. La decisión está tomada
explícitamente: si en el futuro AutoHostAI tiene números de tracción
verificables (multi-tenant activo, N propiedades reales en producción), se
sustituyen estas dos frases; mientras tanto, una promesa inventada erosiona
la confianza que las cuatro features tratan de construir.

## Lo que la landing no promete

- **No promete alta pública** (`Sign Up`). `auth-tenancy` no expone
  `POST /auth/register` y esta entrada no la añade. El `FinalCta` enlaza a
  `/login`; no hay «Create your account» que no registre a nadie.
- **No promete páginas que no existen.** `Pricing`, `Portfolio`, `Team` y
  `Sign Up` están fuera de alcance (ver *Out of scope* en el proposal). Sus
  enlaces no se renderizan hasta que haya adonde ir.
- **No promete una variante móvil distinta.** El export de Stitch traía dos
  maquetas (`landing_page_executive_emerald_style` y
  `landing_page_m_vil_estilo_emerald`); son el mismo diseño responsive, no dos
  diseños por breakpoint. Se descarta la tercera variante
  `landing_page_mobile_autohostai` (copia en inglés y set de features
  distinto: *Gestion Inteligente*, *Analitica Avanzada*, *Secure
  Infrastructure*); solo se conserva su encuadre (*«instrumentation-grade /
  mission control»*) como decisión de copia, no como maqueta.
- **No relanza la estética de las pantallas ya entregadas.** El visual restyle
  de `/dashboard`, `/properties`, `/reservations`, `/incidents`, `/cleaning`,
  `/pricing` y `/timeline` vive en `visual-restyle-workspace`, que
  `needs: design-system-tokens` y se ejecuta después de este change.
- **No toca el contrato de la API.** Cero endpoints, DTOs o mutaciones
  nuevas; el `openapi.json` versionado y el `frontend/lib/api/generated/openapi.d.ts`
  quedan intactos.
- **No indexa ninguna otra superficie.** La landing es la **única** superficie
  indexable del árbol; `/login`, `/forgot-password`, el portal del huésped y
  todas las pantallas autenticadas siguen siendo `noindex, nofollow` y sin
  `canonical`. La excepción está centralizada por nombre de ruta en
  `lib/metadata/create-route-metadata.ts`.

## SEO y Open Graph

- `robots: { index: true, follow: true }` solo en `/`. El resto del árbol sigue
  siendo `noindex, nofollow` por el `SHALL` de
  `specs/frontend-foundation.md` §«Metadata».
- `metadataBase` y los absolutos de `canonical` y `openGraph.url` se derivan
  de `NEXT_PUBLIC_APP_URL` (entrada nueva del allowlist público en
  `lib/config/public.ts`). Vacía en local y en `.env.example` — la página
  funciona sin ella, solo pierde los absolutos.
- `opengraph-image.tsx` genera la imagen OG en build time con
  `next/og` `ImageResponse`, 1200×630 (la dimensión recomendada de Open
  Graph), una variante por locale (`og-es.png` y `og-en.png`) para que la
  misma imagen no salga en idioma equivocado. El texto es
  `landing:meta.title` de cada catálogo, sobre el emerald primario, en
  Inter — la misma tipografía que publica la página.
- El título, la descripción y la canonical salen de las mismas claves de
  `landing.json` que el cuerpo, para que la SERP card y la página cuenten lo
  mismo.

## Diagnóstico rápido

| síntoma | dónde mirar |
|---|---|
| `curl -I localhost:3000/` devuelve `307` con sesión | la cookie `autohostai.session.present` está en `1`; en dev con `curl`, no la envíes |
| `curl localhost:3000/` no muestra `index, follow` en `<meta name="robots">` | `NEXT_PUBLIC_APP_URL` está vacía y la excepción por ruta no se aplicó — verificar que `lib/metadata/create-route-metadata.ts` resuelve el descriptor `landing` |
| la barra de marketing muestra `Pricing`/`Portfolio`/`Team` | alguien añadió un destino al `MarketingNav` sin su página; revertir a las dos entradas (`Login` + `#features`) hasta que exista adonde ir |
| un string aparece en castellano o inglés sin pasar por `getServerT()` | falla el invariante de `steering/frontend.md` y el test de paridad de catálogos; revisar el `Object.keys(es.landing) === Object.keys(en.landing)` y el catálogo correspondiente |
| la imagen OG sale en el idioma equivocado al compartir | el consumidor (Twitter, LinkedIn, Slack) cachea por URL; usar `?v=<n>` o esperar al siguiente deploy — la generación es por locale en build time |

## Ficheros clave

- `frontend/app/page.tsx` — Server Component que decide anónimo/autenticado.
- `frontend/app/opengraph-image.tsx` — imagen OG por locale, generada en build.
- `frontend/features/landing/` — `LandingView` (composición de las cinco
  secciones), `Hero`, `FeaturesGrid` (con `<section id="features">`),
  `StatsBand`, `FinalCta`, `LandingFooter`, `MarketingNav` (slot de
  `PublicShell`), `lib/types.ts` (shape de los datos de feature/footer).
- `frontend/features/shell/components/public-shell.tsx` — gana el slot
  opcional `marketingNav`, consumido solo por la landing; `/login` y
  `/forgot-password` no lo pasan.
- `frontend/features/shell/navigation/route-registry.ts` — descriptor
  `landing` (`pattern: "/"`, `profile: "public"`, `match: "exact"`).
- `frontend/lib/metadata/create-route-metadata.ts` — centraliza la excepción
  de indexabilidad por nombre de ruta.
- `frontend/lib/config/public.ts` — allowlist del que sale
  `NEXT_PUBLIC_APP_URL`.
- `frontend/locales/{es,en}/landing.json` — toda la copia visible de la
  página.
