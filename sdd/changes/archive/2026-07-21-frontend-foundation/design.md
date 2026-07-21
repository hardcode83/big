# Design: frontend-foundation

## Context

El frontend existente es el scaffold mínimo creado por `local-environment`: Next.js App Router vive directamente en `frontend/app/`, TypeScript ya tiene `strict: true`, Tailwind se carga desde `frontend/app/globals.css` y Vitest + Testing Library prueban la página raíz. `frontend/app/page.tsx` realiza hoy un health check directo al backend; este change lo sustituirá por un Application Shell autónomo que no hará llamadas API. El scaffold usa actualmente Next.js 16.2.10, React 19 y Tailwind 4, pero todavía no contiene shadcn/ui, TanStack Query, Zustand, react-i18next, navegación ni límites por feature.

El diseño implementa exclusivamente R1–R9 del proposal aprobado. Las rutas de negocio serán placeholders sin datos ni workflows; `infra-scaffold`, autenticación, contratos backend y módulos funcionales permanecen fuera de alcance. La implementación continúa bloqueada hasta que `infra-scaffold` esté mergeado en `origin/main`, aunque el diseño puede cerrarse antes.

## Decisions

### D1 — Política de versión estable y compatible

**Chosen:** usar en el momento de implementación una release estable de Next.js que esté en Active LTS o Maintenance LTS, sea `>=14` y sea compatible con React, Tailwind, shadcn/ui y el resto del stack aprobado. Se conservará la versión del scaffold si cumple esas condiciones; cualquier actualización se limitará a la menor variación necesaria, quedará fijada por `package-lock.json` y se validará con build, type-check y tests. No se usarán canales `canary`, APIs experimentales ni convenciones específicas de una release cuando exista una alternativa estable de App Router. Esta política sigue el [Support Policy oficial de Next.js](https://nextjs.org/support-policy) y evita convertir “14+” del PRD en un pin obsoleto.

Rejected: fijar Next.js 14 exactamente — ya no es una base soportada y contradice el “14+” del PRD.

Rejected: actualizar siempre al último major sin evaluar compatibilidad — introduce riesgo innecesario y mezcla una migración con el Application Shell.

### D2 — Estructura por rutas, shell, shared y features

**Chosen:** conservar `frontend/app/` en la raíz, sin migrar a `src/`, y separar cuatro responsabilidades:

- `app/`: composición de rutas y layouts; los `page.tsx` serán adaptadores finos sin lógica de negocio.
- `features/shell/`: composición, navegación, metadatos de ruta y estado UI exclusivo del Application Shell.
- `components/`: primitivas shadcn/ui y estados visuales transversales sin conocimiento de features.
- `lib/`: infraestructura frontend transversal (`api`, `config`, `i18n`, `query`) sin imports desde `app/` ni desde features.

Los módulos funcionales futuros vivirán en `features/<feature>/` y podrán exponer una API pública desde `index.ts`; un feature no importará internals de otro feature. La dirección permitida será `app → features → components/lib`, mientras `components` y `lib` nunca importarán `app` ni features. `features/shell` podrá consumir componentes y librerías compartidas, pero no módulos funcionales futuros. ESLint documentará y hará verificables estas restricciones mediante `no-restricted-imports` y aliases `@/*`.

Rejected: colocar toda la lógica junto a cada ruta en `app/` — mezcla routing con módulos y dificulta reemplazar placeholders progresivamente.

Rejected: crear desde ahora carpetas vacías para cada dominio — simula módulos que todavía no existen y genera ownership ambiguo.

### D3 — Route groups y jerarquía de layouts

**Chosen:** utilizar route groups únicamente para asignar chrome y ownership sin alterar las URLs canónicas del PRD. La jerarquía será:

```text
RootLayout
├── PublicShell
├── WorkspaceShell
├── CleanerShell
├── TechnicianShell
└── GuestShell
```

Los cinco shells son composiciones hermanas: reutilizan primitivas visuales comunes, disponen de navegación propia, no dependen entre sí y no simulan permisos. La autenticación futura podrá seleccionar o proteger la experiencia correspondiente, pero en este change el perfil de shell se deriva exclusivamente del route group estático.

- **WorkspaceShell:** aplicación principal de gestión y coordinación operacional prevista para `TENANT_OWNER` y `PROPERTY_MANAGER`, con futura adaptación para `SUPER_ADMIN` sin diseñar todavía una experiencia específica para ese rol. Contiene dashboard, properties, timeline, reservations, cleaning management, incidents/maintenance management, conversations, approvals, pricing, statements, reviews y settings. “Workspace” es una arquitectura de interfaz, no un rol nuevo del dominio ni una capa de autorización.
- **CleanerShell:** interfaz independiente mobile-first prevista para `CLEANER`. Solo contiene `/cleaner` y `/cleaner/tasks/[id]`, las superficies necesarias para ejecutar tareas de limpieza cuando el módulo funcional exista.
- **TechnicianShell:** interfaz independiente mobile-first prevista para `TECHNICIAN`. El término incluye técnicos externos, profesionales de reparaciones y trabajadores de mantenimiento asignados a incidencias. Solo contiene `/tech` y `/tech/incidents/[id]`; el slug público `/tech` se conserva por PRD, pero nombres de tipos, componentes, perfiles y tests usarán `technician`.
- **PublicShell:** chrome mínimo para `/login` y `/forgot-password`, sin implementar autenticación.
- **GuestShell:** chrome aislado para `/guest/[token]`, sin navegación hacia superficies internas y sin exponer el token.

WorkspaceShell coordina mantenimiento y gestiona incidencias; TechnicianShell permite que el trabajador asignado ejecute el trabajo. No se creará un `MaintenanceShell`: mantenimiento es un dominio funcional coordinado desde Workspace y ejecutado por `TECHNICIAN` desde TechnicianShell.

```text
frontend/app/
├── layout.tsx                         # RootLayout: html/body + AppProviders
├── (workspace)/
│   ├── layout.tsx                     # Workspace ApplicationShell
│   ├── page.tsx                       # / → redirect estable a /dashboard
│   ├── dashboard/page.tsx
│   ├── properties/page.tsx
│   ├── properties/[id]/page.tsx
│   ├── timeline/page.tsx
│   ├── reservations/page.tsx
│   ├── cleaning/page.tsx
│   ├── incidents/page.tsx
│   ├── conversations/page.tsx
│   ├── pricing/page.tsx
│   ├── statements/page.tsx
│   ├── reviews/page.tsx
│   ├── approvals/page.tsx
│   ├── settings/page.tsx
│   └── settings/integrations/page.tsx
├── (public)/
│   ├── layout.tsx                     # PublicShell, sin navegación privada
│   ├── login/page.tsx
│   └── forgot-password/page.tsx
├── (field)/
│   ├── cleaner/layout.tsx             # CleanerShell
│   ├── cleaner/page.tsx
│   ├── cleaner/tasks/[id]/page.tsx
│   ├── tech/layout.tsx                # TechnicianShell; URL PRD permanece /tech
│   ├── tech/page.tsx
│   └── tech/incidents/[id]/page.tsx
└── (guest)/
    ├── guest/[token]/layout.tsx       # GuestShell aislado
    └── guest/[token]/page.tsx
```

`RootLayout` solo establece documento, metadata y providers. El route group `(field)` es una agrupación organizativa sin layout ni shell propio: `cleaner/layout.tsx` y `tech/layout.tsx` instancian CleanerShell y TechnicianShell por separado. Cada shell conserva su chrome durante la navegación interna y cada placeholder sigue siendo una página independiente y un chunk de ruta reemplazable.

**Recomendación documental para una futura revisión del PRD (sin modificar el PRD en este change):** `TECHNICIAN` includes external technicians, repair professionals and maintenance workers assigned to incidents. Esta aclaración no cambia el rol canónico ni sus permisos actuales; explicita la población ya cubierta por el rol.

Rejected: un único layout con condicionales basados en `pathname` — crea una gran frontera cliente y acopla rutas públicas, operativas y por token.

Rejected: múltiples root layouts completos — provocarían recargas completas entre grupos y duplicarían providers globales.

### D4 — Registro de rutas y navegación

**Chosen:** mantener un registro tipado y declarativo en `frontend/features/shell/navigation/route-registry.ts`. Cada descriptor contendrá solamente metadata de shell: identificador estable, patrón de ruta, `href` cuando sea navegable sin parámetros, claves i18n de título/descripción/breadcrumb, nombre de icono, grupo de navegación, orden, estrategia de matching (`exact` o `prefix`) y perfil de shell. No contendrá permisos, endpoints, DTOs, datos, contadores ni estados de negocio.

El registro será la fuente única para sidebar, bottom navigation, menú “Más”, breadcrumbs, active route y contenido del placeholder. Una validación automatizada garantizará que cubre todas las superficies exactas de PRD §24, que no duplica IDs/hrefs y que todas sus claves existen en ES y EN.

Navegación principal workspace, en orden coherente con la prioridad operacional del PRD §30:

1. **Operación:** Dashboard, Timeline, Properties.
2. **Trabajo:** Reservations, Cleaning, Incidents, Conversations, Approvals.
3. **Revenue:** Pricing, Statements, Reviews.
4. **Administración:** Settings.

Cleaner y Technician no aparecen en sidebar, bottom navigation, menú “Más” ni grupos funcionales del Workspace. En este change sus experiencias solo se alcanzan mediante sus URLs canónicas independientes. Un futuro enlace secundario o selector explícito de aplicación podrá añadirse cuando exista sesión/perfil real, pero nunca se modelará como una sección ordinaria de Workspace. `/settings/integrations` y las rutas dinámicas son rutas hijas, no entradas principales. `/guest/[token]` no es navegable sin un token y no aparece en el registro de links, aunque sí en el registro de patrones, metadata y placeholders.

El registro global puede contener todas las rutas para validación, breadcrumbs, metadata y placeholders, pero cada shell obtiene su navegación mediante un selector obligatorio por `ShellProfile`. No existe un selector “all” para renderizado ni navegación cruzada indiscriminada. PublicShell y GuestShell tampoco consumen rutas de los perfiles workspace, cleaner o technician.

Rejected: duplicar arrays de navegación por breakpoint — terminarían divergiendo y harían difícil demostrar paridad entre dispositivos.

Rejected: derivar etiquetas y breadcrumbs de segmentos URL — expone IDs/tokens y produce textos no internacionalizados.

### D5 — Active route, breadcrumbs y navegación contextual

**Chosen:** una isla cliente pequeña leerá `usePathname()` y resolverá el descriptor más específico: primero match exacto y después el prefijo válido más largo, normalizando trailing slash e ignorando query/hash. El link activo usará señal visual y `aria-current="page"`; cuando la ruta activa esté dentro del menú “Más”, ese trigger también aparecerá activo.

Los breadcrumbs se construirán a partir de una cadena explícita de IDs del registro, no a partir del pathname. Se mostrarán en desktop y tablet dentro del topbar; en mobile se mostrará solo el título de página para conservar espacio. Los segmentos dinámicos usarán una etiqueta genérica localizada (“Detalle”) mientras sean placeholders: no mostrarán IDs ni tokens y no intentarán resolver nombres con una API. El feature propietario podrá aportar en el futuro un resolver de etiqueta mediante la API pública del shell.

La navegación contextual será un slot opcional de `PageHeader` para tabs o acciones definidas por el feature propietario. En este change el slot permanecerá vacío en todos los placeholders; no se anticiparán filtros, acciones ni workflows.

Rejected: breadcrumbs con datos falsos o IDs crudos — inventa contenido y puede revelar tokens o identificadores sensibles.

### D6 — Comportamiento responsive de navegación

**Chosen:** las superficies se seleccionarán con media queries de Tailwind, no con detección JavaScript del viewport, usando breakpoints estables: mobile `<768px`, tablet `768–1023px`, desktop `>=1024px`. El mismo registro alimenta todas las variantes dentro de cada perfil. Para WorkspaceShell:

| Viewport | Chrome | Comportamiento |
|---|---|---|
| Desktop | Sidebar + topbar | Sidebar fija, expandida por defecto y reducible a rail de iconos; topbar contiene breadcrumbs, título/contexto y utilidades del shell. |
| Tablet | Sidebar colapsable + topbar | Rail colapsada por defecto; el trigger del topbar abre un panel lateral accesible con navegación completa. |
| Mobile | Topbar + bottom navigation | Sin sidebar; topbar compacta y bottom navigation fija. Destinos directos: Dashboard, Timeline, Cleaning e Incidents; “Más” abre un Sheet con el resto de destinos navegables. |

La bottom navigation tendrá un máximo de cinco elementos para conservar targets táctiles claros. El contenido tendrá padding inferior reservado para que la barra no tape la página y respetará safe-area insets. WorkspaceShell usa los destinos indicados en la tabla. CleanerShell y TechnicianShell son mobile-first: usan topbar y bottom navigation propias en mobile, y sustituyen esa barra por topbar + sidebar compacta de su mismo perfil en tablet/desktop; solo muestran destinos estables navegables de ese shell y nunca inventan un ID para enlazar una ruta dinámica. PublicShell y GuestShell solo usan topbar porque no existe navegación de módulos aplicable a esas superficies.

Rejected: hamburger como única navegación mobile — oculta la estructura operativa prioritaria y aumenta pasos para las superficies principales.

Rejected: renderizado condicional por `window.innerWidth` — causa hydration mismatch y duplica lógica que CSS resuelve mejor.

### D7 — Estado y persistencia del menú

**Chosen:** `frontend/features/shell/state/use-shell-ui-store.ts` será el único store Zustand inicial. Guardará `sidebarCollapsedByProfile`, `tabletNavOpen` y `mobileMoreOpen`; solo el mapa de preferencias de sidebar por `ShellProfile` se persistirá en `localStorage` con una clave versionada (`autohostai.ui.shell.v1`) mediante `persist/partialize`. Los overlays se cerrarán al cambiar de pathname y nunca se persistirán. El estado inicial será determinista; las transiciones visuales se habilitarán tras rehidratación para evitar animaciones o saltos engañosos. Una preferencia de Workspace nunca alterará CleanerShell o TechnicianShell.

El store no guardará locale, ruta activa, sesión, roles, query results, feature flags ni datos de negocio. La ruta activa se deriva del router, el locale pertenece a i18n, la configuración a su provider y el estado remoto a TanStack Query.

Rejected: persistir todo el store — conserva drawers abiertos y dificulta migraciones.

Rejected: usar React Context global para el menú — Zustand ya está aprobado para este tipo de estado UI y ofrece persistencia selectiva sin ampliar el provider tree.

### D8 — Placeholder UX y familia de estados

**Chosen:** crear `ModulePlaceholder` como estado planificado reutilizable sobre una primitiva común `StatePanel`. No será un texto aislado “Coming Soon”. Cada instancia mostrará:

- icono neutral del módulo;
- badge localizado de estado (“En preparación” / “In preparation”);
- título y descripción breve procedentes de claves i18n del registro;
- explicación localizada de que la superficie está prevista pero aún no está disponible;
- ausencia deliberada de fechas, porcentajes, datos, acciones de negocio o falsas promesas.

Será un `section` con heading asociado, no tendrá `role="alert"`, no mostrará reintento y utilizará estilo informativo neutral. Así no se confunde con un fallo. Para rutas dinámicas ignorará el valor del parámetro salvo para completar el routing; nunca lo renderizará ni solicitará datos.

`LoadingState`, `ErrorState`, `EmptyState` y `ModulePlaceholder` compartirán `StatePanel` solo para layout, espaciado e iconografía; conservarán semánticas y APIs distintas:

| Estado | Significado | Semántica/acción |
|---|---|---|
| Loading | Hay una operación pendiente | `aria-busy`, contenido skeleton o status no intrusivo. |
| Error | Una operación falló | Mensaje de error; `role="alert"`; retry solo si existe callback real. |
| Empty | La operación terminó sin resultados | Explicación neutral; acción opcional aportada por un feature real. |
| Planned | El módulo todavía no está implementado | Badge planificado; sin alerta, retry ni acción de negocio. |

Los `loading.tsx` y `error.tsx` de App Router compondrán estos estados conforme a D18; los placeholders renderizarán directamente `ModulePlaceholder` y no simularán carga, error ni Suspense.

Rejected: reutilizar `EmptyState` para módulos pendientes — “sin datos” y “sin implementación” son estados operacionales distintos.

Rejected: mostrar roadmap, ETA o progreso falso — no existe una fuente de verdad para esa información.

### D9 — Server Components, CSR y rendimiento

**Chosen:** layouts y pages serán Server Components por defecto. Solo serán Client Components las islas que requieren interacción o browser APIs: navegación activa, Sheet/Tooltip, selector de idioma, providers cliente y store Zustand. `"use client"` se colocará en el límite más bajo posible; el Application Shell completo no será una frontera cliente.

App Router aportará code splitting por segmentos de ruta. Cada `page.tsx` importará únicamente su placeholder y metadata; el registro de navegación contendrá datos serializables y nombres de icono, no imports de features. Los módulos futuros permanecerán fuera del bundle del shell hasta que su ruta se navegue. `next/dynamic` se reservará para widgets cliente pesados que lo justifiquen en su propio change; no se añadirá lazy loading ceremonial a componentes pequeños.

La renderización inicial será server-rendered. El locale se resolverá en servidor y se pasará a i18n para evitar hydration mismatch. Las rutas futuras podrán elegir SSR, streaming/Suspense, Server Components con fetch o hidratación de TanStack Query por feature sin cambiar el shell, respetando los límites de D18. No se usarán APIs experimentales de cache; cada feature documentará freshness y caching cuando exista un contrato real.

La verificación de performance incluirá `next build`, inspección de chunks por ruta y confirmación de que ninguna ruta placeholder importa módulos de negocio. No se fija un presupuesto numérico sin baseline; la implementación registrará el baseline del shell para que cambios posteriores puedan compararlo.

Rejected: convertir el root layout en Client Component — enviaría JavaScript innecesario y ampliaría el coste de hidratación.

Rejected: forzar CSR global — degrada primera carga, accesibilidad y flexibilidad de renderizado.

### D10 — Composición de providers globales

**Chosen:** `frontend/app/providers.tsx` será una frontera cliente fina, renderizada desde el RootLayout Server Component. El orden será:

```text
RuntimeConfigProvider
└── I18nProvider
    └── QueryProvider
        └── children (incluye Server Components ya renderizados)
```

Zustand no necesita provider. El futuro `AuthProvider` tendrá un slot documentado entre i18n y query, pero no existirá en este change. Cada provider tendrá responsabilidad única, instancia estable por árbol y test aislado. No se añadirán providers de theme, analytics, notifications o feature flags activos porque no forman parte del proposal.

Rejected: un contexto global “AppContext” — mezcla responsabilidades y fuerza rerenders amplios.

### D11 — Estrategia TanStack Query

**Chosen:** instalar TanStack Query v5 y encapsular su creación en `frontend/lib/query/query-client.ts` y `QueryProvider`. El shell creará un `QueryClient` estable por sesión de navegador, pero no declarará ni ejecutará queries. Las features futuras definirán query options y stale times junto a su módulo; las mutations no tendrán retry automático por defecto.

Las query keys multi-tenant seguirán la forma `['tenant', tenantId, resource, ...scope]`. Una factory exigirá `tenantId` para todo recurso tenant-scoped, evitando keys globales accidentales. Hasta que autenticación y contratos backend existan no habrá tenant ID, factories de recursos concretos, prefetch ni dehydrated state. El patrón futuro de SSR será prefetch por route/feature, `dehydrate` en servidor y `HydrationBoundary` local, nunca prefetch global desde el shell.

Rejected: crear query keys y hooks para endpoints del PRD ahora — convertiría una lista de endpoints en contratos frontend inventados.

Rejected: copiar server state a Zustand — contradice steering y crea dos fuentes de verdad.

### D12 — Cliente API sin integración backend

**Chosen:** preparar en `frontend/lib/api/` un transporte central basado en `fetch`, configurable por base URL y con un error técnico común compatible únicamente con el envelope ya definido por PRD §23. Su API será genérica y devolverá `unknown` en la frontera; cada feature futura deberá validar y tipar su contrato. No contendrá rutas, DTOs, mocks, query hooks ni llamadas durante este change.

La construcción del cliente admitirá puntos de extensión explícitos para añadir en el futuro headers de autenticación y manejo de `401`, sin implementar tokens, refresh ni logout. El transporte nunca leerá Zustand. El backend seguirá siendo autoridad de RBAC; ocultar navegación será solo una mejora de UX futura.

Para SSR futuro, la URL interna será server-only. Para requests desde navegador, la integración backend futura deberá inyectar una URL pública saneada mediante runtime config o decidir un proxy same-origin en su propio design. Este change no elige rutas proxy ni modifica Docker/env, porque ambas decisiones pertenecen a la integración backend/infra.

Rejected: generar un SDK desde los endpoints enumerados en el PRD — no existe todavía OpenAPI backend aprobado para esos módulos.

Rejected: exponer `BACKEND_INTERNAL_URL` al cliente — filtra topología interna y no funciona fuera de la red Docker.

### D13 — Internacionalización ES/EN

**Chosen:** usar `i18next` + `react-i18next` con namespaces JSON versionados en `frontend/locales/es/` y `frontend/locales/en/`: `common`, `navigation` y `states`. El registro de rutas y los componentes solo almacenarán claves; ninguna string visible se hardcodeará.

El locale se resolverá por cookie no sensible `autohostai.locale` validada contra `es | en`, con `es` como fallback del producto. El servidor creará una instancia i18next por request, establecerá `<html lang>` y pasará locale/resources al provider cliente. Un control accesible del topbar permitirá cambiar ES/EN, actualizar cookie, i18next y el atributo `lang`; una preferencia autenticada podrá sustituir esa fuente en un change futuro sin cambiar las claves ni las URLs. No se añadirá prefijo `[locale]` porque alteraría todas las rutas canónicas de PRD §24.

Un test de paridad comparará recursivamente las claves ES/EN y fallará por claves ausentes. Los tests no dependerán del texto español por defecto: consultarán roles/nombres localizados o parametrizarán el locale.

Rejected: archivos TS con strings junto a cada componente — dificulta comprobar paridad y reutilizar namespaces.

Rejected: locale en la URL — cambia contratos de navegación ya fijados por el PRD.

### D14 — Accesibilidad WCAG AA

**Chosen:** construir shell y estados sobre HTML semántico y primitivas accesibles de shadcn/ui/Radix, con objetivo WCAG 2.2 nivel AA. Reglas obligatorias:

- landmarks únicos y etiquetados (`header`, `nav`, `main`) y enlace “saltar al contenido”;
- orden DOM coherente y navegación completa por teclado;
- focus visible con contraste suficiente, nunca eliminado;
- `aria-current` para ruta activa, `aria-expanded`/`aria-controls` para navegación colapsable y nombres accesibles para icon-only buttons;
- focus trap, retorno de foco y cierre con Escape en Sheet/drawers;
- targets táctiles mínimos de 44×44 CSS px en bottom navigation;
- contraste AA, información no dependiente solo del color y respeto a `prefers-reduced-motion`;
- breadcrumb con `nav aria-label` y lista ordenada; tokens/IDs no se anuncian;
- iconos decorativos con `aria-hidden`; texto visible o accessible name para toda acción.

La automatización con axe y Testing Library cubrirá violaciones detectables; una comprobación manual de teclado, focus y viewports formará parte de Verification porque ninguna herramienta automática demuestra WCAG completa.

Rejected: añadir ARIA a elementos nativos sin necesidad — puede empeorar la semántica y contradice “ARIA cuando corresponda”.

### D15 — Configuración build-time y runtime

**Chosen:** centralizar la lectura y validación en `frontend/lib/config/`, separando estrictamente:

- `server.ts` (`server-only`): variables privadas/runtime, nunca importable desde Client Components;
- `public.ts`: tipo y allowlist del subconjunto público serializable;
- `runtime-config-provider.tsx`: acceso cliente al snapshot público entregado por servidor;
- `constants.ts`: defaults no sensibles del producto, incluido locale `es`.

El código de aplicación no leerá `process.env` fuera de esta frontera. `NEXT_PUBLIC_APP_ENV`, ya existente, se tratará como configuración pública build-time. `BACKEND_INTERNAL_URL`, ya inyectada por Compose, permanecerá server-only y opcional para el shell: no se leerá ni validará al arrancar hasta que un feature real necesite backend, preservando R8.1. La futura URL pública `BACKEND_URL` ya nombrada en PRD §25 se mapeará a runtime config por el change de integración correspondiente; no se añadirá ahora a `.env.example` ni se expondrá la URL interna.

Las future feature flags se declararán en un registro tipado central, evaluado en servidor, y solo se serializarán booleans explícitamente allowlisted. Este change crea la frontera y documenta el proceso, pero no define nombres, valores ni condicionales de flags.

Rejected: acceder a `process.env` desde componentes — dispersa validación y puede exponer secretos por error.

Rejected: usar exclusivamente `NEXT_PUBLIC_*` para runtime config — Next.js inlinea esos valores en build y dificulta promover la misma imagen entre entornos.

### D16 — Estrategia de testing y verificación

**Chosen:** conservar Vitest + Testing Library y añadir configuración explícita de setup, ESLint flat config compatible con la versión Next elegida y axe-core para checks automatizados de accesibilidad. Los tests se colocarán junto al módulo (`*.test.ts[x]`) y los helpers compartidos en `frontend/test/`.

Cobertura mínima de este change:

1. registro de rutas: cobertura PRD §24, unicidad, orden, claves i18n y perfil obligatorio `workspace | cleaner | technician | public | guest`;
2. aislamiento de navegación: cada shell consume exclusivamente su perfil; Cleaner y Technician no aparecen en sidebar, bottom navigation ni menú “Más” de Workspace;
3. active route: exact, prefijo más largo, nested/dynamic y estado “Más” dentro del perfil correspondiente;
4. navegación: paridad de destinos por shell, `aria-current`, collapse/open/close, Escape, retorno de foco y persistencia selectiva;
5. placeholders y estados: planned/error/empty/loading distinguibles; un placeholder estático no activa `LoadingState`, Suspense ni retry falso;
6. error boundaries: un error de contenido compondrá `ErrorState` y preservará el chrome del shell; el global fallback no mostrará mensaje ni stack del error;
7. metadata: títulos/descripciones ES/EN, template global, `noindex, nofollow` y ausencia de IDs/tokens en rutas dinámicas, especialmente `/guest/[token]`;
8. i18n: render ES/EN, cambio de idioma y paridad de catálogos;
9. config: allowlist pública y ausencia de secretos/URL interna en el snapshot cliente;
10. providers: una instancia estable y shell renderizable sin backend;
11. arquitectura: type-check, lint, tests y production build;
12. responsive: verificación en navegador a 390 px, 768 px y 1280 px del chrome propio de cada shell, accesibilidad a sus destinos y ausencia de overflow; durante `/sdd:run` se usará el navegador Playwright disponible, sin introducir todavía la suite E2E funcional reservada a `hardening-release`.

No se mockearán endpoints ni datos de negocio. Los tests de pages dinámicas usarán parámetros sintácticos opacos únicamente para demostrar routing y comprobar que no se renderizan.

Rejected: snapshots visuales masivos — son frágiles y no demuestran navegación, accesibilidad ni límites arquitectónicos.

### D17 — Extensibilidad para autenticación futura

**Chosen:** preparar puntos de sustitución sin implementar auth:

- `(public)`, `(workspace)`, los segmentos `/cleaner` y `/tech`, y `(guest)` ya separan las superficies que un futuro gate protegerá o seleccionará por experiencia;
- `AppProviders` documenta el slot del futuro `AuthProvider`;
- el cliente API expone composición de request middleware, pero no un middleware/token concreto;
- cada shell filtra el registro por su perfil estático, no por permisos; el futuro auth change podrá seleccionar/proteger shells y derivar visibilidad desde sesión, sin tratarla como autorización;
- ningún token se guarda en localStorage, Zustand, config o cookies por este change.

La decisión concreta entre gate en servidor, middleware/proxy del framework o combinación se tomará con el contrato real de auth y la versión estable de Next en ese change. Este design no la anticipa. RBAC seguirá siempre en backend conforme a `security.md`.

Rejected: guards placeholder o roles ficticios — aparentan seguridad sin backend y amplían el scope.

### D18 — Error Boundaries and Suspense Strategy

**Chosen:** aislar fallos y esperas en el límite más próximo que sea propietario de la operación, preservando el shell siempre que App Router pueda contener el problema en el segmento de contenido.

**Root error handling.** `frontend/app/global-error.tsx` será el último fallback para fallos no recuperables del RootLayout o de sus providers. Como este boundary sustituye el documento completo, renderizará su propio `html/body`, un mensaje comprensible, focus inicial gestionado y una acción real de recuperación (reset/reload). Usará un catálogo mínimo ES/EN que no dependa del provider que pudo fallar. Nunca mostrará `error.message`, stack traces, secretos, URLs internas ni detalles técnicos; el error podrá registrarse en consola en desarrollo, pero la UI será segura en todos los entornos.

**Route and feature error handling.** Cada shell tendrá un `error.tsx` en su segmento propietario: `(workspace)/error.tsx`, `cleaner/error.tsx`, `tech/error.tsx`, `(public)/error.tsx` y `guest/[token]/error.tsx`. Estos boundaries compondrán `ErrorState` dentro del slot de contenido, de modo que topbar/sidebar/bottom navigation del layout padre sigan visibles. Un módulo funcional futuro podrá añadir un `error.tsx` o React Error Boundary más profundo cuando sea propietario de una operación; un fallo contenido no escalará al boundary global. Los errores del propio layout o de un provider, que no pueden ser capturados por el boundary de ese mismo segmento, escalarán al ancestro apropiado.

**Suspense.** Los boundaries se colocarán en el segmento de ruta o feature que posea la operación asíncrona. No existirá un Suspense global alrededor de la aplicación ni del shell. Los layouts mantendrán chrome y navegación estables mientras cambia o carga el contenido. Cada feature futura decidirá granularidad, skeleton, streaming y si usa `loading.tsx` según sus datos reales. Los placeholders estáticos no tendrán `loading.tsx`, promesas artificiales ni Suspense ceremonial.

**State components.** Todo `loading.tsx` futuro compondrá `LoadingState`; todo `error.tsx` compondrá `ErrorState`. `ErrorState` solo mostrará retry si recibe una acción `reset` real. `ModulePlaceholder` permanece separado y nunca se representará mediante loading, error o Suspense.

Rejected: un único error boundary o Suspense en RootLayout — elimina innecesariamente la navegación y convierte toda transición en un estado global.

Rejected: capturar y mostrar mensajes de excepción — puede filtrar detalles internos y produce una UX técnica no localizada.

### D19 — App Router metadata

**Chosen:** centralizar metadata global y de placeholders con helpers tipados que reutilizan claves localizadas del route registry, sin convertir metadata en una estrategia SEO comercial.

`RootLayout` definirá nombre de aplicación `AutoHostAI`, descripción localizada por defecto (“Aplicación operativa de AutoHostAI” / “AutoHostAI operational application”) y un template de título `%s | AutoHostAI`, manteniendo `AutoHostAI` como título default. Cada `page.tsx` placeholder exportará metadata estática o `generateMetadata` mediante `createRouteMetadata(routeId, locale)`. El descriptor aportará `metadataTitleKey` y `metadataDescriptionKey`; el helper resolverá ES/EN con la misma estrategia de locale que D13.

Las rutas dinámicas placeholder usarán únicamente metadata genérica localizada del descriptor (“Property detail”, “Cleaning task”, “Incident detail” o “Guest portal” equivalentes), sin interpolar IDs, tokens ni valores de `params`. `/guest/[token]` no expondrá el token en title, description, Open Graph, canonical, breadcrumbs ni contenido indexable.

Política de indexación y Open Graph:

- WorkspaceShell, CleanerShell, TechnicianShell y GuestShell serán `noindex, nofollow`.
- PublicShell (`/login`, `/forgot-password`) también será `noindex, nofollow`: son utilidades de acceso, no páginas públicas de marketing.
- El default global será no indexable para evitar exposición accidental; un futuro sitio público deberá usar un route group y design propios para optar explícitamente a indexación.
- Open Graph se limitará a nombre, título y descripción genéricos/localizados; no incluirá IDs, tokens, datos de negocio, URL canónica ni imágenes específicas de módulo. Las superficies privadas no se diseñan para social sharing.
- `metadataBase` solo se configurará cuando exista una URL pública autorizada mediante la frontera de D15; no se inventará durante este change.

El registro sirve para metadata aunque una ruta no sea navegable. Tests inspeccionarán metadata resultante para ambos locales, noindex y ausencia de parámetros sensibles.

Rejected: generar metadata desde pathname/params — puede filtrar tokens o IDs y produce títulos no localizados.

Rejected: una estrategia SEO/OG por módulo — las superficies no son contenido público y ese alcance no está aprobado.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dependencies/tooling | `frontend/package.json`, `frontend/package-lock.json`, `frontend/eslint.config.mjs`, `frontend/tsconfig.json`, `frontend/vitest.config.ts`, `frontend/test/setup.ts` | Añadir librerías aprobadas, scripts `lint`/`typecheck`, setup Testing Library/axe y reglas de boundaries; conservar strict mode. |
| Root composition | `frontend/app/layout.tsx`, `frontend/app/providers.tsx`, `frontend/app/globals.css` | Root Server Layout, provider island, tokens CSS mínimos, focus/safe-area/responsive shell; sin design system completo. |
| App Router | `frontend/app/(workspace)/**`, `frontend/app/(public)/**`, `frontend/app/(field)/**`, `frontend/app/(guest)/**`, `frontend/app/global-error.tsx` | Route groups, cinco shells independientes, error boundaries segmentados, metadata y todos los placeholders exactos de PRD §24; `/` redirige a `/dashboard`. |
| Existing health page | `frontend/app/page.tsx`, `frontend/app/page.test.tsx` | Sustituir/eliminar la página de health y sus tests; el shell no llama al backend. |
| Shell feature | `frontend/features/shell/components/**`, `frontend/features/shell/navigation/**`, `frontend/features/shell/state/**` | Primitivas compartidas y Workspace/Cleaner/Technician/Public/Guest shells independientes, navegación filtrada por perfil, route registry, active matching, breadcrumbs y store UI. |
| Shared UI | `frontend/components/ui/**`, `frontend/components/states/**` | Solo primitivas shadcn necesarias y familia StatePanel/Loading/Error/Empty/ModulePlaceholder; fallbacks seguros para boundaries. |
| Metadata | `frontend/lib/metadata/**`, route `page.tsx`/`layout.tsx` | Helper localizado por route ID, template global, Open Graph genérico y política noindex sin IDs/tokens. |
| Query | `frontend/lib/query/query-client.ts`, `frontend/lib/query/query-provider.tsx`, `frontend/lib/query/query-keys.ts` | Provider sin queries y convención tenant-scoped preparada. |
| API transport | `frontend/lib/api/client.ts`, `frontend/lib/api/errors.ts`, `frontend/lib/api/index.ts` | Transporte genérico sin endpoints/DTOs/calls y extensión futura de auth. |
| i18n | `frontend/lib/i18n/**`, `frontend/locales/es/*.json`, `frontend/locales/en/*.json` | Inicialización server/client, cookie locale, namespaces y catálogos completos ES/EN. |
| Config | `frontend/lib/config/**` | Frontera server/public/runtime, allowlist y extensión futura de flags; sin modificar infraestructura. |
| Documentation | `frontend/README.md` | Convenciones, dependency rules, taxonomía de shells, diferencia Workspace maintenance coordination vs Technician execution, recomendación terminológica de `TECHNICIAN`, rutas, providers, errores/Suspense, metadata, state ownership, i18n, config, testing y reemplazo de placeholders. |

Las primitivas shadcn se añadirán como código local solo cuando sean necesarias para shell/estados (Button, Sheet, Tooltip, Separator, Skeleton y Badge). No se inicializará un catálogo completo. Las dependencias runtime esperadas son TanStack Query v5, Zustand, i18next/react-i18next y Lucide; shadcn añadirá únicamente las dependencias Radix/utilidades requeridas por esas primitivas. Todas las versiones se resolverán contra el Next/React estable elegido en D1.

## Data & interfaces

No hay cambios de base de datos, API backend, eventos, DTOs de negocio ni contratos OpenAPI.

Interfaces internas del shell, mostradas solo para cerrar ownership:

```ts
type ShellProfile =
  | "workspace"
  | "cleaner"
  | "technician"
  | "public"
  | "guest";

interface ShellRouteDescriptor {
  id: string;
  pattern: string;
  href?: string;
  titleKey: string;
  descriptionKey: string;
  metadataTitleKey: string;
  metadataDescriptionKey: string;
  breadcrumbKeys: readonly string[];
  icon: NavigationIconName;
  profile: ShellProfile;
  match: "exact" | "prefix";
  navigationGroup?: NavigationGroup;
  order?: number;
}
```

El descriptor contiene solo metadata visual, documental y de routing. No admite `endpoint`, `roles`, payloads, datos ni callbacks de negocio. El perfil interno es `technician`; `tech` solo permanece en `pattern`/`href` porque `/tech` es la URL canónica del PRD. Todo consumidor de navegación debe recibir un `ShellProfile` concreto y filtrar antes de renderizar; no existe consumo indiscriminado del registro completo.

Configuración conocida o reservada:

| Nombre | Visibilidad | Uso en este change |
|---|---|---|
| `NEXT_PUBLIC_APP_ENV` | Pública, build-time, existente | Se lee únicamente a través de config; no controla features. |
| `BACKEND_INTERNAL_URL` | Server-only, runtime, existente | No se consume al renderizar el shell ni se expone al cliente. |
| `BACKEND_URL` | Pública runtime futura, nombrada en PRD §25 | Solo se documenta el mapping futuro; no se añade ni consume. |
| Locale `es/en` | Público, cookie validada + fallback `es` | Controla i18next y `<html lang>`; no contiene datos sensibles. |
| Feature flags | Público solo tras allowlist futura | Registro vacío; no se inventan flags. |

## Requirement coverage

| Requirement | Design decisions |
|---|---|
| R1 — Arquitectura modular/strict/performance | D1, D2, D3, D9, D18, D19 |
| R2 — Base visual responsive/accesible | D6, D14 |
| R3 — Query/Zustand/API | D7, D11, D12 |
| R4 — ES/EN | D13 |
| R5 — Loading/error/empty | D8, D18 |
| R6 — Testing/documentación | D16, D18, D19, Changes by area |
| R7 — Preparación auth | D3, D10, D12, D17 |
| R8 — Application Shell | D3–D8, D18, D19 |
| R9 — Configuración | D15, Data & interfaces |

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| El shell se convierte en un mega Client Component y aumenta el bundle. | Server Components por defecto, islas cliente mínimas, registro serializable y comprobación de chunks en build. |
| Sidebar, bottom nav y breadcrumbs divergen. | Un único route registry, tests de paridad y matching centralizado. |
| Workspace expone por error destinos Cleaner/Technician o un shell consume rutas ajenas. | `ShellProfile` obligatorio, selector sin modo “all” y tests negativos por cada perfil. |
| La terminología “tech” genera un shell ambiguo o un `MaintenanceShell` adicional. | Reservar `/tech` al slug PRD; usar `technician` internamente y documentar que `TECHNICIAN` cubre profesionales de mantenimiento asignados. |
| Los placeholders se confunden con errores o datos vacíos. | `ModulePlaceholder` separado semánticamente, badge planificado, sin alert/retry y tests de estados. |
| Un error de ruta elimina innecesariamente todo el shell. | Boundaries dentro de cada shell, global fallback solo como último recurso y test de persistencia del chrome. |
| Un Suspense global sustituye navegación y contenido a la vez. | Suspense solo en límites propietarios de ruta/feature; ninguno para placeholders estáticos. |
| Metadata de una ruta dinámica filtra un ID o token. | Helper por route ID que ignora params, noindex global y tests específicos de `/guest/[token]`. |
| La persistencia Zustand causa hydration mismatch, mezcla shells o guarda estado indebido. | Estado inicial determinista, preferencias por `ShellProfile`, rehidratación controlada y `partialize` exclusivo para el mapa de sidebar. |
| Las rutas placeholder anticipan contratos o lógica de negocio. | Pages finas, sin feature folders vacíos, sin fetch/mocks/DTOs y lint/import review. |
| Una variable privada llega al browser. | `server-only`, allowlist pública explícita y test que inspecciona el snapshot serializado. |
| El locale cookie fuerza render dinámico del root. | Aceptar SSR por request para consistencia de idioma; mantener features y chunks separados y reevaluar caching solo con datos reales. |
| Upgrade de framework rompe convenciones. | Política LTS, lockfile, APIs estables, build/type-check/tests antes de aceptar una versión. |
| Breakpoints ocultan destinos o tapan contenido. | Registro común, safe-area/padding, verificación browser en tres viewports y navegación solo teclado. |
| La UI placeholder se interpreta como prototipo funcional. | Copia explícita de estado planificado, ausencia de datos/acciones y documentación de reemplazo por feature real. |

## Open questions

Ninguna. El proposal y este design dejan cerradas las decisiones necesarias para `/sdd:tasks`. Las decisiones que requieren contratos reales —auth gate concreto, endpoints/DTOs, caching por recurso, URL pública efectiva y nombres de feature flags— pertenecen expresamente a sus futuros changes y no bloquean la implementación del Application Shell.
