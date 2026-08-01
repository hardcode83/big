# Proposal: dashboard-web-frontend

## Why

El dashboard es la UX más crítica del producto (PRD §9): debe responder en <10 s
"¿qué pasa en cada vivienda y quién tiene la próxima acción?". Hoy `/dashboard` y
`/properties/[id]` son solo placeholders "En preparación" del Application Shell
(`frontend-foundation`), y el backend agregado que los alimentará (entrada de
roadmap `dashboard-web`, endpoint `GET /api/v1/properties/{id}/dashboard` del PRD
§23) **todavía no existe**. Este change construye la capa de presentación del
dashboard ya, contra una **fuente de datos mock** (datos fijos de las 2 viviendas
reales REDES11 y PAJARITOS8), para desbloquear el trabajo de FE en paralelo al
backend.

**Desviación de norma, asumida y acotada.** `steering/product.md` principio 3
("adapters mock donde falten credenciales — *nunca maqueta visual*") y
`steering/frontend.md` ("el endpoint/API va primero") reservan los mocks para
servicios **externos** sin credenciales (PMS, IA), no para el backend **propio**
de AutoHostAI. Este change invierte deliberadamente ese orden (FE antes que su
API). Para que no sea una maqueta desechable, el mock vive **detrás de un
contrato tipado** (`DashboardDataSource`) que replica el envelope y los DTOs de
la API real (PRD §23); la UI y los hooks dependen solo de esa interfaz. Cuando
`dashboard-web` (backend) exista, se sustituye la implementación mock por la HTTP
sin tocar la UI. Esto es **deuda técnica explícita** (ver R3 y "Deuda explícita"),
no un TODO suelto.

**Registrado en el roadmap.** Este change tiene su propia entrada en
`sdd/roadmap.md` (insertada justo antes de `dashboard-web`), adelantando el FE
del dashboard contra mocks/fixtures mientras `dashboard-web` (backend agregado)
sigue su orden natural. La entrada `dashboard-web` permanece como el slice de
backend + cableado de la API real.

## What changes

Tras este change existirán dos superficies funcionales del dashboard del
propietario/manager, hoy inexistentes, dentro del WorkspaceShell ya establecido:
la **pantalla de property cards** (`/dashboard`, PRD §9.1) y la **página de
detalle de propiedad** (`/properties/[id]`, PRD §9.2, con el timeline de esa
propiedad y sus secciones de reserva/acceso/limpieza/incidencias/financiero).
Ambas leen datos a través de una **fuente de datos con interfaz tipada**
(`DashboardDataSource`), con una única implementación en este change —
`MockDashboardSource` con datos fijos coherentes de REDES11 y PAJARITOS8 —
consumida vía TanStack Query v5 con claves tenant-scoped, respetando los estados
transversales (loading/error/empty), la i18n ES/EN y los colores de estado
operacional del Application Shell.

## Requirements

### R1 — Pantalla de property cards (`/dashboard`)

**As a** propietaria/manager, **I want** ver de un vistazo el estado de cada
vivienda en `/dashboard`, **so that** entienda en <10 s qué pasa y quién tiene la
próxima acción (PRD §9.1).

Acceptance criteria:

1. WHEN se navega a `/dashboard`, THE SYSTEM SHALL renderizar una property card
   por cada vivienda devuelta por la fuente de datos, cada una mostrando: código
   de propiedad, estado operacional con su color (R5), reserva actual o próxima,
   nombre del huésped si está disponible, check-in/check-out, estado de limpieza,
   número de incidencias abiertas, próxima acción requerida con su responsable, y
   tiempo del último evento.
2. WHILE la fuente de datos está resolviendo la petición, THE SYSTEM SHALL mostrar
   el estado de carga transversal (`LoadingState`, `aria-busy`) del shell, sin
   texto inventado.
3. IF la fuente de datos falla, THEN THE SYSTEM SHALL mostrar `ErrorState`
   (`role="alert"`) con reintento vía la callback real, sin exponer el detalle
   crudo del error.
4. IF la fuente de datos devuelve cero viviendas, THEN THE SYSTEM SHALL mostrar el
   estado vacío (`EmptyState`), distinto de error y de carga.
5. THE SYSTEM SHALL no contener lógica de negocio ni cálculo de estados en los
   componentes: el estado operacional, colores y "próxima acción" provienen tal
   cual de los datos de la fuente (el backend es la fuente de verdad — R3).

### R2 — Página de detalle de propiedad (`/properties/[id]`)

**As a** propietaria/manager, **I want** abrir el detalle de una vivienda,
**so that** vea su timeline y el estado completo en una pantalla (PRD §9.2).

Acceptance criteria:

1. WHEN se navega a `/properties/[id]`, THE SYSTEM SHALL renderizar, para la
   propiedad indicada, el timeline de esa propiedad (filtrable por tipo/actor,
   PRD §10) y las secciones: reserva actual/próxima, datos del huésped, estado de
   acceso, estado de limpieza, incidencias abiertas, resumen financiero, notas y
   aprobaciones pendientes.
2. WHEN se renderizan entradas de timeline, THE SYSTEM SHALL mostrarlas en el
   idioma activo del usuario y en orden inmutable (sin edición de eventos
   pasados), sin exponer IDs ni tokens en migas de pan (respetando la convención
   de breadcrumbs del shell).
3. IF el id solicitado no existe en la fuente de datos, THEN THE SYSTEM SHALL
   mostrar un estado de "no encontrado" localizado, sin romper el chrome del
   shell.
4. WHERE se muestren fotos de última limpieza, THE SYSTEM SHALL consumir la URL
   provista por la fuente de datos y SHALL NOT construir URLs de storage en el
   cliente (convención `frontend.md`); en el mock son URLs de placeholder
   marcadas como tales.
5. THE SYSTEM SHALL aplicar los mismos estados transversales de
   carga/error/vacío de R1 a las secciones de detalle.

### R3 — Fuente de datos tras contrato tipado y sustituible (deuda explícita)

**As a** equipo, **I want** que el mock viva detrás de una interfaz que replica la
API real, **so that** al llegar `dashboard-web` se sustituya sin reescribir la UI.

Acceptance criteria:

1. THE SYSTEM SHALL definir una interfaz `DashboardDataSource` cuyos métodos
   devuelven DTOs que replican el contrato de la API real del PRD §23 (envelope
   de datos, envelope de error `{error:{code,message,details}}`, fechas ISO-8601
   UTC), alineada con `GET /api/v1/properties/{id}/dashboard`,
   `GET /api/v1/properties`, `GET /api/v1/properties/{id}` y
   `GET /api/v1/timeline/{property_id}`.
2. THE SYSTEM SHALL proveer en este change exactamente una implementación de esa
   interfaz, `MockDashboardSource`, con datos fijos y coherentes de REDES11 y
   PAJARITOS8; los componentes y hooks de UI SHALL importar y depender **solo**
   de la interfaz, nunca de la implementación mock ni de sus datos directamente.
3. THE SYSTEM SHALL aislar los datos fijos del mock en un módulo dedicado del
   feature (`features/dashboard/data/`), fuera de los componentes, marcados en
   código con `ASSUMPTION`/deuda; ningún dato de negocio fijo vive en componentes
   compartidos (respetando el límite establecido por `frontend-foundation`).
4. THE SYSTEM SHALL seleccionar la implementación de `DashboardDataSource` en un
   único punto de composición (p. ej. provider/factoría), de modo que sustituir
   el mock por una implementación HTTP no requiera cambios en la UI ni en los
   hooks.
5. WHERE la UI necesite un `tenantId` para las claves de query tenant-scoped y no
   exista aún autenticación, THE SYSTEM SHALL obtenerlo de un valor de dev
   explícito y centralizado (no hardcodeado por componente), marcado como
   `ASSUMPTION` y como punto de sustitución por el contexto de sesión de
   `auth-tenancy`.

### R4 — Acceso a datos vía TanStack Query tenant-scoped

**As a** equipo, **I want** que el consumo de datos siga los patrones del shell,
**so that** el dashboard herede caché, claves por tenant y estados coherentes.

Acceptance criteria:

1. WHEN el dashboard o el detalle consumen datos, THE SYSTEM SHALL enrutarlos por
   TanStack Query v5 con la factoría de claves tenant-scoped del shell
   (`['tenant', tenantId, resource, ...scope]`), con `tenantId` no vacío.
2. THE SYSTEM SHALL limitar Zustand a estado ligero de UI (p. ej. filtros del
   timeline) y SHALL NOT duplicar en stores el server state que gestiona TanStack
   Query.
3. WHEN una implementación HTTP futura reemplace al mock, THE SYSTEM SHALL poder
   enrutar sus peticiones por el transporte centralizado `lib/api` (envelope de
   error §23) sin cambiar las claves de query ni los componentes.

### R5 — i18n ES/EN y colores de estado operacional

**As a** propietaria, **I want** el dashboard en mi idioma con los colores de
estado correctos, **so that** la lectura en <10 s sea inequívoca.

Acceptance criteria:

1. WHEN se renderiza cualquier string visible del dashboard o el detalle, THE
   SYSTEM SHALL resolverlo por claves react-i18next presentes en `locales/es` y
   `locales/en`; ningún string visible queda hardcodeado.
2. THE SYSTEM SHALL mapear cada estado operacional a su color exacto del PRD §9.1
   (verde/azul/amarillo/rojo/gris), usando los nombres canónicos de estado del
   PRD (`VACANT_READY`, `AWAITING_CLEANING`, `CRITICAL_INCIDENT`, …).
3. IF falta una clave de traducción en cualquiera de los dos locales, THEN THE
   SYSTEM SHALL fallar el test automatizado de paridad de catálogos.

### R6 — Verificación sin backend

**As a** equipo, **I want** que el dashboard se verifique sin backend,
**so that** el CI del FE siga siendo autónomo hasta que llegue la API real.

Acceptance criteria:

1. THE SYSTEM SHALL proveer tests colocados (Vitest + Testing Library + jest-dom +
   axe) que cubran el render de cards (R1), el detalle (R2), los estados
   loading/error/empty y la paridad de catálogos i18n, todos contra la fuente de
   datos mock.
2. WHEN se verifica el frontend, THE SYSTEM SHALL pasar type-check, lint, tests y
   build de producción sin depender de un backend en ejecución.
3. THE SYSTEM SHALL incluir un test que verifique la frontera de R3: que los
   componentes/hooks no importan la implementación mock ni sus datos directamente
   (dependen solo de la interfaz).

## Out of scope

- **Backend agregado del dashboard** (endpoint `GET /api/v1/properties/{id}/dashboard`
  y agregación de reserva/limpieza/incidencias/financiero) → entrada de roadmap
  `dashboard-web`. Este change consume su contrato vía mock.
- **Sustitución del mock por la API HTTP real** → se hará al integrar
  `dashboard-web`; queda como deuda explícita (ver abajo), no se implementa aquí.
- **Autenticación / login / RBAC / obtención real de `tenantId`** → `auth-tenancy`.
  Aquí se usa un `tenantId` de dev marcado como `ASSUMPTION`.
- **Otras superficies del PRD §24**: `/properties` (lista), `/timeline` global,
  `/reservations`, `/cleaning`, `/incidents`, `/approvals`, settings, apps de
  limpiadora/técnico y portal huésped. Permanecen como placeholders del shell.
- **Acciones de mutación** (aprobar gastos, aceptar tareas, cambiar estados): el
  dashboard de este change es de **solo lectura**.
- **Realtime / WebSockets** del timeline "en tiempo real" (PRD §9.2): aquí es
  render sobre datos fijos; el streaming llega con el backend.

## Deuda explícita (a resolver con `dashboard-web`)

1. **Sustituir `MockDashboardSource` por `HttpDashboardSource`** contra
   `GET /api/v1/properties/{id}/dashboard` y endpoints §23 asociados, en el único
   punto de composición de R3.4 — sin tocar UI ni hooks.
2. **Sustituir el `tenantId` de dev** (R3.5) por el contexto de sesión real de
   `auth-tenancy`.
3. **Activar el timeline en tiempo real** (streaming/polling) cuando el backend lo
   provea, reemplazando los datos fijos de R2.

Esta deuda queda además registrada en el spec vivo al archivar (ver Affected specs)
y marcada en código como `ASSUMPTION`/deuda, no como TODO suelto.

## Affected specs

- `sdd/specs/dashboard-web-frontend.md` *(no existe aún — se creará al archivar)*
  — describirá la capa de presentación del dashboard, el contrato
  `DashboardDataSource` y la deuda de sustitución del mock.
- `sdd/specs/frontend-foundation.md` — se actualizará para reflejar que
  `/dashboard` y `/properties/[id]` dejan de ser placeholders "En preparación" y
  pasan a ser superficies funcionales (solo lectura, sobre fuente de datos
  sustituible).
