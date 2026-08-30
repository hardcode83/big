# AutoHostAI — Frontend

Application Shell del frontend Next.js (App Router, TypeScript strict). Este change entrega la **fundación**: layout, navegación responsive, rutas base y placeholders para todos los módulos del PRD §24. La autenticación se integra como sesión efímera en el runtime del navegador: los JWT viven solo en memoria y los guards son de UX client-side; el backend conserva toda la autoridad.

La sesión se pierde con un reload completo, cierre de pestaña o nuevo runtime y requiere login de nuevo. No se usan cookies de autenticación, `localStorage`, `sessionStorage`, IndexedDB, BFF ni `middleware.ts` de autenticación. Una migración futura a cookies/middleware o sesión server-side requiere un change arquitectónico separado.

## Comandos

```bash
npm run dev         # desarrollo (http://localhost:3000)
npm run typecheck   # tsc --noEmit (strict)
npm run lint        # eslint (incluye fronteras de imports)
npm test            # vitest + Testing Library
npm run build       # build de producción
npm run api:generate # deriva tipos desde ../backend/openapi.json
npm run api:check    # comprueba deriva sin modificar el artefacto
```

La verificación no depende de un backend ni de datos de negocio.

**Baseline del shell** (`next build`, Next 16.2.10 estable): 22 superficies de PRD §24 + redirect raíz, todas server-rendered on demand (la cookie de locale se resuelve por request). El bundle del shell no importa módulos de negocio (el único feature es `features/shell`); los módulos futuros quedan fuera hasta navegar su ruta. Sin APIs canary/experimentales.

## Estructura y reglas de dependencia

```
app/         Composición de rutas y layouts. Los page.tsx son adaptadores finos.
app/api/     La única pieza de servidor: [...path]/route.ts reenvía /api/ al backend.
features/    Módulos por dominio. features/shell/ es el Application Shell.
components/  Primitivas shadcn/ui (components/ui) y estados (components/states).
lib/         Infraestructura transversal: api, config, i18n, query, metadata, theme.
locales/     Catálogos i18n es/ y en/.
test/        Setup y helpers de test.
```

Dirección de dependencias permitida (verificada por ESLint `no-restricted-imports`):

```
app → features → components / lib
```

- `components/` y `lib/` **nunca** importan de `app/` ni de `features/`.
- Un `feature` **no** importa internals de otro feature: solo su API pública `@/features/<nombre>` (index), y usa rutas relativas dentro de sí mismo.
- `app/` compone las capas inferiores libremente.

Los tests están exentos de estas reglas (no son código de producción).

## Taxonomía de shells

Cinco shells hermanos, independientes, seleccionados por route group estático (no por permisos):

| Shell | Perfil | Rutas | Chrome |
|---|---|---|---|
| **WorkspaceShell** | `workspace` | dashboard, properties(+detalle), timeline, reservations, cleaning, incidents, conversations, approvals, pricing, statements, reviews, settings(+integrations) | Desktop: sidebar + topbar · Tablet: drawer colapsable · Mobile: topbar + bottom nav (Dashboard, Timeline, Cleaning, Incidents, Más) |
| **CleanerShell** | `cleaner` | `/cleaner`, `/cleaner/tasks/[id]` | Mobile-first, topbar (destino único → sin bottom nav artificial) |
| **TechnicianShell** | `technician` | `/tech`, `/tech/incidents/[id]` | Mobile-first, topbar (destino único → sin bottom nav artificial) |
| **PublicShell** | `public` | `/login`, `/forgot-password` | Topbar mínima, sin navegación privada |
| **GuestShell** | `guest` | `/guest/[token]` | Chrome aislado, nunca renderiza el token |

**Workspace coordina** mantenimiento y gestiona incidencias; **Technician ejecuta** el trabajo asignado. No existe `MaintenanceShell`.

> **Recomendación documental para una futura revisión del PRD (sin modificar el PRD en este change):**
> `TECHNICIAN` includes external technicians, repair professionals and maintenance workers assigned to incidents.

El slug público `/tech` se conserva por PRD; el perfil, tipos, componentes y tests usan `technician`.

## Navegación por perfil

- Fuente única: `features/shell/navigation/route-registry.ts` (metadata de shell — id, patrón, href, claves i18n, icono, perfil, matching, grupo/orden; **sin** roles, endpoints, datos ni contadores).
- La navegación se selecciona siempre por `ShellProfile` (`select-routes.ts`). **No** existe un selector "all": un shell nunca renderiza rutas de otro perfil.
- Active route y breadcrumbs: `match-route.ts` (exacto → prefijo más largo, normaliza trailing slash/query) y `breadcrumbs.ts` (cadena explícita del registro; nunca segmentos crudos, IDs ni tokens).

## Sustitución de placeholders

Cada ruta renderiza `RoutePlaceholder` (Server Component) → `ModulePlaceholder` (badge "en preparación", sin datos/acciones/ETA). Para convertir un placeholder en módulo real:

1. Crear `features/<módulo>/` con su API pública en `index.ts`.
2. Sustituir el `RoutePlaceholder` del `page.tsx` por el componente real del feature.
3. Definir query options/keys del feature (ver TanStack Query) y sus contratos con backend.
4. Añadir sus estados (`loading.tsx`/`error.tsx`) componiendo `LoadingState`/`ErrorState`.
5. Añadir sus claves i18n en `locales/es` y `locales/en`, y registrar el namespace en `lib/i18n/resources.ts` (import, array `NAMESPACES` y las tablas `es`/`en`).
6. **Registrar la página en `REAL_PAGE_ROUTE_IDS` de `app/route-coverage.test.ts`.** Ese test deduce el `routeId` de cada página leyendo su prop `routeId="…"`, que sólo existe mientras la página es un `RoutePlaceholder`; en cuanto deja de serlo, la página queda «sin cubrir» y el test de páginas huérfanas falla. Es su mecanismo previsto, no un defecto — pero no lo ve ningún test del feature, sólo la suite completa.

## Server / Client Components y rendimiento

- Layouts y pages son **Server Components** por defecto. El shell completo **no** es una frontera cliente: los wrappers de shell (`WorkspaceShell`, …), `ShellFrame`, `Topbar`, `Brand`, `SkipLink`, `PageHeader` y `RoutePlaceholder` son Server Components y resuelven su texto estático en servidor (`getServerT`). `"use client"` se coloca en el límite más bajo posible, solo en las islas interactivas: `Sidebar`/collapse y `TabletNavTrigger` (store Zustand), `BottomNavigation`/`MoreMenu`, `NavLink`, `Breadcrumbs`/`PageTitle` (navegación cliente), `LocaleSwitcher`, `ThemeSwitcher` (escribe la cookie de tema), y `OverlayAutoCloser` (cierre de overlays al navegar).
- **`Topbar` es un Server Component `async`**, porque lee el tema de la cookie por request para montar el `ThemeSwitcher`. Los cinco wrappers de shell que la componen (`WorkspaceShell`, `PublicShell`, `CleanerShell`, `TechnicianShell`, `GuestShell`) son `async` por lo mismo. Sigue sin ser una frontera cliente: lo asíncrono es la lectura, no la interactividad.
- App Router aporta code splitting por ruta. El registro es serializable (nombres de icono, no imports de features), así los módulos futuros quedan fuera del bundle del shell hasta navegar su ruta.
- No se usan APIs experimentales de cache. `next/dynamic` se reserva para widgets cliente pesados en su propio change.
- **Un barrel es una arista de dependencia que ESLint no ve**, y por eso `features/shell` tiene **dos puertas**: `@/features/shell` es la **superficie de cliente** (`PageHeader`, el tipo `ShellProfile`, `useNotificationsPanel`) y `@/features/shell/server` publica las cinco shells y `routeMetadata`, que alcanzan `server-only` (las shells por `lib/theme/server`; `routeMetadata` por `lib/metadata/create-route-metadata` → `lib/i18n/server`). Los layouts y pages de `app/` importan las shells desde `/server`; un Client Component importa **solo** del barrel de cliente. Es legal porque la regla `no-restricted-imports` sobre `@/features/*/**` solo gobierna los ficheros **bajo** `features/`.
- **Esa clase de error solo la detecta `next build`.** Un Client Component que sacaba un hook del barrel general arrastró `server-only` al bundle del navegador con `tsc --noEmit` limpio y la suite entera en verde; el fallo apareció en CI, en el `npm run build` del job `provenance-contract` (PR #136). Si añades un export a un barrel que un Client Component consume, comprueba qué más reexporta ese barrel.

## Providers

`app/providers.tsx` (frontera cliente fina) compone, en orden:

```
RuntimeConfigProvider → I18nProvider → AuthProvider → QueryProvider
```

`AuthProvider` expone identidad y estado React, mientras `lib/auth` conserva los
tokens únicamente en memoria y coordina el refresh single-flight. Los guards de
`workspace`, `cleaner` y `technician` son client-side y solo mejoran la UX; RBAC,
JWT y tenant isolation siguen siendo responsabilidad del backend. La shell pública
y el portal guest no reciben el guard JWT.

Zustand no necesita provider. No se añaden providers de theme/analytics/flags.

## Estado remoto y de interfaz

- **TanStack Query v5** para estado remoto. `lib/query`: `QueryClient` estable por sesión (el shell no declara queries). Query keys multi-tenant: `tenantScopedKey(tenantId, resource, ...scope)` → `['tenant', tenantId, resource, ...]`; `tenantId` es obligatorio (no hay keys globales por accidente).
- **Zustand solo para estado ligero de UI** (`features/shell/state/use-shell-ui-store.ts`): colapso de sidebar por perfil (persistido con clave versionada `autohostai.ui.shell.v1`) y overlays efímeros (no persistidos, se cierran al navegar). **No** se duplica en Zustand estado servido por TanStack Query, ni locale, sesión, roles o datos de negocio.

## Cliente API

`lib/api`: transporte genérico basado en `fetch`, configurable por base URL, con el envelope de error de PRD §23 (`{error:{code,message,details}}`). Sus tipos se derivan exclusivamente de `../backend/openapi.json` mediante el generador fijado `openapi-typescript@6.7.6`; el artefacto versionado vive en `lib/api/generated/openapi.d.ts`. `npm run api:generate` lo regenera y `npm run api:check` falla mostrando la deriva si la salida cambia. El flujo usa Node 22, `npm ci` y normaliza la salida para producir bytes idénticos en macOS, Linux y CI.

El cliente relaciona cada ruta con los métodos HTTP declarados en OpenAPI y tipa sus cuerpos JSON y respuestas de éxito. No contiene endpoints, DTOs escritos a mano, wrappers, repositorios ni servicios de dominio. La integración `frontend-auth-session` usa sus hooks `getHeaders` y `onUnauthorized` para añadir el access token efímero, renovar una sesión elegible tras un `401`, reintentar una vez y excluir los endpoints de autenticación; el login, la sesión en memoria, el logout best-effort y los guards client-side de UX viven en `lib/auth` y `features/auth`. Los errores siguen pasando por `ApiError` y `parseApiError`; nunca se persisten tokens ni se lee Zustand para la sesión.

## Diseño: tokens, temas y tipografía

La capa de color, tipografía, ritmo y radios vive **entera** en `app/globals.css`, en **dos bloques `@theme` distintos**, y la regla que los separa importa al añadir un token: lo que depende del tema va en `@theme inline`, que mapea el token de Tailwind sobre la variable que cada bloque de tema redefine (`--color-surface: var(--surface)`); lo que es literal e igual en los dos temas —tipografía, ritmo, radios— va en un `@theme` llano, que no debe pasar por `:root`. El propio fichero lo explica junto a cada bloque. No hay `tailwind.config.js` ni `.ts` en ninguna de sus extensiones, su ausencia es deliberada (`components.json` lleva `"tailwind": {"config": ""}`) y desde este change hay un test que falla si alguien la reintroduce.

**La paleta de color, en tres bloques** —cuántos tokens son exactamente lo asertan `app/globals.tokens.test.ts` y la comprobación de tokens declarados de `test/color-tokens.test.ts`, que es donde no puede quedarse atrás—: el tema claro en `:root`, y el oscuro **dos veces** — bajo `@media (prefers-color-scheme: dark)` acotado con `:root:not([data-theme="light"])`, y otra vez en `:root[data-theme="dark"]`. Los dos bloques oscuros son idénticos valor por valor y un test de paridad lo vigila; están duplicados para que el atributo pueda vencer a la preferencia del sistema **en las dos direcciones**, forzando claro sobre un sistema oscuro igual que oscuro sobre uno claro.

**El tema se resuelve en el servidor, calcado del idioma.** Cookie `autohostai.theme` (validada contra `light|dark`, sin valor por defecto: su ausencia significa «lo que diga el sistema»), leída por request y volcada en `<html data-theme>`. No hay provider, no hay estado de cliente y no hay script anti-flash: el atributo llega en el HTML del servidor, así que no hay un primer pintado que corregir. El conmutador (`features/shell/components/theme-switcher.tsx`) es una isla de cliente que **escribe** la cookie y nunca lee el tema.

**Ningún componente necesita una variante `dark:`**, y no es estilo sino corrección: el `dark:` de Tailwind sigue a `prefers-color-scheme` y **nunca** a nuestro atributo, así que en una página forzada a oscuro sobre un sistema claro un `dark:` no dispara. El color lo cambia el token, no el variante.

**Tipografía**: `Inter` (texto) y `JetBrains Mono` (código y cifras), cargadas con `next/font/google`, que descarga los ficheros en **tiempo de build** y los sirve desde el propio origen bajo `/_next/static/media/`. No se pide nada a `fonts.googleapis.com` en runtime. Diez roles semánticos, de `text-display-2xl` a `text-label-caps`, cada uno con su interlineado, tracking y peso; los nombres exactos son los `--text-*` del `@theme` llano de `globals.css`.

**Ritmo y radios**: la unidad base es `--spacing: 0.25rem`, o sea la escala numérica de Tailwind (`p-1`, `p-4`, `p-8`) es el ritmo del diseño. Los ocho pasos con nombre del export **no** se declaran: `max-w-*` resuelve contra `--spacing-*` en Tailwind v4, así que declarar `--spacing-md` hacía que `max-w-md` valiera 0.75rem en vez de 28rem y colapsaba cada contenedor de la aplicación. Sobreviven `--spacing-gutter` y los dos márgenes, que no chocan con nada. Los radios son cuatro literales (`sm`/`md`/`lg`/`xl`).

**Contraste**: `app/globals.contrast.test.ts` recalcula desde `globals.css` el ratio de cada par de los dos temas contra WCAG 2.2 AA e **imprime la tabla**; una tabla en markdown envejece en cuanto alguien retoca un hex, y un test que la recompute no puede.

**Dos guards, y conviene saber qué NO cubren.** `test/color-tokens.test.ts` recorre `app/`, `components/`, `features/` y `lib/` —todo `.ts(x)`, `.js(x)`/`.mjs` y, en las hojas de estilo, las clases que nombra un `@apply`— buscando color que no pase por la capa de tokens; la comprobación más interesante es la que exige que la utilidad nombre un token **declarado**, porque es la que encuentra la clase de defecto en que `bg-card` no pintaba nada durante meses. **Cuántas comprobaciones son y qué mira cada una lo dice la cabecera del propio fichero**, que es donde no puede quedarse atrás: aquí decía tres cuando ya eran cinco, y presentaba la lista como exhaustiva. Sus patrones viven en `test/color-tokens.ts` y `test/color-tokens.patterns.test.ts` los recorre desde una tabla, porque un guard que sólo afirma «el árbol está limpio» se pone verde con una regex rota mientras el árbol no ejercite la rotura; cada agujero que ha encontrado una review es una fila de esa tabla. Lo que no ven, declarado y no insinuado: una clase construida dinámicamente (`` `bg-${tono}` ``); que el token **exista** no prueba que sea el **correcto**; y **una hoja de estilos que declare color a pelo** —fuera de un `@apply`— es invisible, incluido un `@media (prefers-color-scheme: dark)` propio, porque de un `.css` sólo se leen las clases que nombra un `@apply` (una hoja no es un componente: pasarle los patrones de clase entera reporta disparates). Hoy no muerde: `app/globals.css` es la única hoja del árbol y es donde la capa de tokens vive por diseño.

## Internacionalización (ES/EN)

`i18next` + `react-i18next`, namespaces `common`, `navigation`, `states` y `auth` en `locales/{es,en}`. **Toda string visible pasa por claves i18n; nada hardcodeado.** El locale se resuelve por cookie `autohostai.locale` (validada contra `es|en`, fallback `es`), server-side por request, y se sincroniza con `<html lang>`. Un test de paridad falla ante claves ausentes en cualquiera de los dos idiomas.

## Estados transversales

`components/states`: `StatePanel` (layout común) con `LoadingState` (`aria-busy`/status), `ErrorState` (`role="alert"`, retry solo con callback real, nunca muestra el error crudo), `EmptyState` (neutral) y `ModulePlaceholder` (planificado). Son server-compatibles y reciben el texto ya localizado por props.

## Error boundaries y Suspense

- `app/global-error.tsx`: último recurso; documento propio, catálogo ES/EN inline (independiente de los providers), foco inicial y recuperación real. Nunca muestra `error.message`, stacks, secretos ni URLs internas.
- `error.tsx` por segmento (workspace/public/cleaner/tech/guest): compone `ErrorState` dentro del slot de contenido, preservando el chrome del shell.
- Los placeholders estáticos **no** añaden `loading.tsx`, Suspense ni promesas artificiales. Un futuro `loading.tsx` debe componer `LoadingState` en el segmento propietario.

## Metadata

`lib/metadata` (builder genérico i18n → Metadata) + `features/shell` `routeMetadata(routeId)` (lookup del registro). Título global `AutoHostAI`, template `%s | AutoHostAI`, descripción localizada, Open Graph genérico. Todas las superficies son `noindex, nofollow`. Las rutas dinámicas usan metadata genérica localizada — nunca interpolan IDs, tokens ni `params` (especialmente `/guest/[token]`). No se configura `metadataBase` sin una URL pública autorizada.

## Configuración

`lib/config`, con frontera estricta (design D15):

- `server.ts` (`server-only`): variables privadas/runtime; nunca importable desde un Client Component.
- `public.ts`: allowlist explícita del subconjunto público serializable (`apiBaseUrl`, `appEnv`, `defaultLocale`, `featureFlags` vacío). `apiBaseUrl` tiene por defecto el valor vacío para usar rutas same-origin a través del proxy existente. Nada se vuelca desde `process.env`.
- `runtime-config-provider.tsx`: acceso cliente al snapshot público.
- `constants.ts`: defaults no sensibles (locale `es`, cookie de locale, cookie de tema y los dos temas admitidos).

El código de aplicación no lee `process.env` fuera de esta frontera. `BACKEND_INTERNAL_URL` permanece server-only y no se consume al renderizar el shell; `apiBaseUrl` no lo expone al navegador. Las feature flags futuras se declararán en el registro tipado central (hoy vacío).

## Testing

Vitest + Testing Library + jest-dom + axe-core. Tests colocados junto al módulo (`*.test.ts[x]`); helpers en `test/`. Cobertura de esta fundación: registro de rutas y cobertura PRD §24, aislamiento de navegación por perfil, active route, estados distinguibles, i18n y paridad de catálogos, config (allowlist/sin secretos), metadata (noindex, sin IDs/tokens), error boundaries y accesibilidad (axe + comprobación manual de teclado/foco/viewports). No se mockean endpoints ni datos de negocio.

La capa de diseño añade cuatro comprobaciones propias, descritas arriba: paridad de los dos bloques oscuros, auditoría de contraste WCAG que imprime su tabla, el guard de tokens de color y la tabla de patrones de ese guard. El contraste no lo cubre axe: `getA11yViolations` desactiva `color-contrast` a propósito, porque jsdom no puede calcularlo con fiabilidad.

## Límites de autenticación frontend

La sesión frontend ya implementa login y refresh efímero, pero mantiene estos límites:

- Los route groups (`(public)`, `(workspace)`, `(field)`, `(guest)`) separan las superficies que el guard client-side protege por experiencia; la autorización efectiva sigue en el backend.
- `AppProviders` monta `AuthProvider` entre i18n y query.
- El cliente API expone composición de headers y recuperación elegible de `401`.
- Cada shell filtra el registro por su perfil estático, no por permisos.
- Ningún token se guarda en localStorage, sessionStorage, IndexedDB, Zustand, config ni cookies.

El backend seguirá siendo la autoridad de RBAC; el frontend solo adaptará la presentación.
