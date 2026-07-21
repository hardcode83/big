# Proposal: frontend-foundation

## Ownership

- **Propietaria del change:** Marta.
- **Coordinación:** las dependencias de este change ya están mergeadas en `origin/main`: `infra-scaffold` (que entrega `infra/`: IaC/CI-CD; archivado el 2026-07-15) y `local-environment` (que entrega el scaffold Next.js: `package.json`, `next.config`, Vitest, además de Compose y Dockerfile de orquestación). Este change no duplica, anticipa ni modifica ese trabajo.

## Why

AutoHostAI necesita un Application Shell completo, coherente y verificable sobre el que construir progresivamente todas sus interfaces funcionales. Este contenedor debe entregar desde el inicio la estructura visual común, la navegación y las rutas base de la aplicación, y permitir priorizar la visibilidad del estado operacional indicada en la [sección 30 del PRD](../../../docs/AutoHostAI_PRD_v5_Claude.md#30-instrucción-final-para-claude) —dashboard y estado, timeline y después los flujos operativos— por encima del orden literal de construcción de la sección 26, sin implementar todavía esas funcionalidades.

El change construye ese Application Shell y su fundación técnica conforme al stack de la [sección 4](../../../docs/AutoHostAI_PRD_v5_Claude.md#4-stack-tecnológico), las superficies previstas en la [sección 24](../../../docs/AutoHostAI_PRD_v5_Claude.md#24-frontend--páginas) y los steering documents aplicables. El resultado será una aplicación Next.js ejecutable y preparada para recibir módulos funcionales sin contener lógica de negocio, workflows ni integraciones backend. Se construye sobre el scaffold Next.js entregado por `local-environment` (ver `sdd/specs/local-environment.md`); esa dependencia, junto con `infra-scaffold`, ya está integrada en `origin/main`, por lo que no existe bloqueo remoto activo.

## What changes

Se construirá el Application Shell ejecutable del frontend Next.js App Router: layout principal, sistema de navegación responsive, estructura visual común, rutas base y placeholders para todos los módulos funcionales previstos en el PRD. Los placeholders mostrarán únicamente un estado informativo de funcionalidad pendiente y no contendrán lógica de negocio, workflows, llamadas API ni contratos inventados.

El shell se apoyará en la fundación técnica ya definida: TypeScript strict, organización modular por dominios o features, Tailwind CSS, shadcn/ui, TanStack Query v5, Zustand limitado al estado ligero de interfaz, internacionalización ES/EN, un cliente API centralizado preparado para uso futuro, convenciones compartidas para estados de carga/error/vacío, estrategia de testing y documentación de convenciones. La arquitectura quedará preparada para incorporar autenticación en un change posterior, pero no implementará login, sesión, JWT ni RBAC.

## Dependencies and coordination constraints

- **Dependencias de implementación (ya resueltas):** el scaffold Next.js sobre el que se construye (`package.json`, `next.config`, Vitest, más Compose y Dockerfile de orquestación) lo entregó `local-environment` (commit `6d2cfdf`; `sdd/specs/local-environment.md` líneas 41/53), mientras que `infra-scaffold` entrega `infra/` (IaC/CI-CD), ortogonal al frontend. Ambos changes están mergeados en `origin/main`, por lo que no existe bloqueo remoto activo; la verificación del gate (tarea 1.1) debe confirmar esa integración contra `origin/main`, sin aceptar como prueba artefactos exclusivamente locales.
- **Límite de ownership:** este change no crea ni modifica monorepo, Docker, Compose, Makefile, CI/CD, IaC ni ningún otro artefacto de infraestructura propiedad del trabajo de Jose Ignacio.
- **Contratos backend:** cada módulo funcional futuro dependerá de contratos API definidos por backend. Esta fundación no inventa endpoints, DTOs, payloads ni reglas de negocio para adelantarlos.
- **Gates SDD:** esta propuesta requiere revisión y aprobación antes de ejecutar `/sdd:design`, `/sdd:tasks` o `/sdd:run`.

## Requirements

### R1 — Arquitectura frontend modular y estricta

**As a** desarrolladora frontend, **I want** una arquitectura base de Next.js App Router organizada por dominios o features y validada con TypeScript strict, **so that** los módulos operativos futuros puedan evolucionar con límites claros y tipos seguros.

Acceptance criteria:

1. WHEN se implemente la fundación después de desbloquearse su dependencia de infraestructura, THE SYSTEM SHALL usar Next.js 14+ con App Router y TypeScript en modo `strict`.
2. WHEN se documente la estructura del frontend, THE SYSTEM SHALL definir límites explícitos entre rutas, features o dominios, componentes compartidos, acceso a API, estado de interfaz, internacionalización y utilidades.
3. WHEN se añada en el futuro una superficie de dashboard, property detail, timeline, cleaning, incidents, conversations, pricing, statements, cleaner o tech, THE SYSTEM SHALL disponer de una ubicación modular prevista sin requerir lógica de negocio en componentes compartidos.
4. IF una validación de tipos detecta un error, THEN THE SYSTEM SHALL fallar el comando de verificación definido para el frontend.
5. WHEN future functional modules are added, THE SYSTEM SHALL support route-level lazy loading, code splitting, bundle optimization, and rendering strategies compatible with App Router without requiring a shell-wide architectural rewrite.

### R2 — Base visual responsive y mobile-first

**As a** usuaria operativa que trabaja principalmente desde el móvil, **I want** una base de layout responsive y componentes UI consistentes, **so that** las interfaces futuras sean utilizables en pantallas pequeñas desde su origen.

Acceptance criteria:

1. WHEN se implemente el layout base, THE SYSTEM SHALL aplicar una estrategia mobile-first y demostrar adaptación al menos en viewports móvil y escritorio sin desbordamiento horizontal no intencionado.
2. WHEN se creen primitivas visuales compartidas, THE SYSTEM SHALL usar Tailwind CSS y shadcn/ui como base.
3. WHEN se revise el alcance implementado, THE SYSTEM SHALL contener únicamente el shell, su navegación, primitivas técnicas genéricas y placeholders informativos, sin property cards ni vistas funcionales de módulos de negocio.
4. IF una decisión pertenece a identidad visual definitiva o a un design system completo, THEN THE SYSTEM SHALL dejarla fuera de este change.
5. WHEN a user operates the Application Shell using only a keyboard, THE SYSTEM SHALL provide a logical navigation order and visible focus for every interactive element.
6. WHEN a reusable component requires semantic information that native HTML does not provide, THE SYSTEM SHALL expose the appropriate ARIA attributes.
7. WHEN shared layout or navigation components are implemented, THE SYSTEM SHALL be architected to meet WCAG AA accessibility requirements.

### R3 — Estado remoto, estado de interfaz y acceso a API

**As a** desarrolladora de módulos frontend, **I want** fronteras inequívocas para datos remotos, estado local de interfaz y comunicación HTTP, **so that** no se duplique estado ni se acople la UI a contratos dispersos.

Acceptance criteria:

1. WHEN un módulo futuro consuma datos remotos, THE SYSTEM SHALL hacerlo mediante TanStack Query v5 y una convención documentada de query keys por recurso y tenant.
2. WHEN se necesite estado global ligero de interfaz, THE SYSTEM SHALL permitir Zustand únicamente para estado de UI y SHALL NOT duplicar en sus stores datos gestionados por TanStack Query.
3. WHEN a future functional module performs an HTTP request, THE SYSTEM SHALL route it through the centralized API client prepared by this change; the Application Shell itself SHALL NOT perform backend calls.
4. IF un contrato de backend todavía no está definido, THEN THE SYSTEM SHALL abstenerse de inventar endpoints, DTOs o payloads y SHALL documentar la dependencia correspondiente.
5. WHEN se verifique la fundación, THE SYSTEM SHALL NOT contener mocks de negocio embebidos en componentes.

### R4 — Internacionalización ES/EN desde la base

**As a** usuaria de AutoHostAI, **I want** que la interfaz soporte español e inglés de forma consistente, **so that** cada módulo futuro pueda presentar contenido en mi idioma sin retrabajo estructural.

Acceptance criteria:

1. WHEN se renderice cualquier string visible incluida en la fundación, THE SYSTEM SHALL resolverla mediante react-i18next y claves de traducción.
2. WHEN se añada una clave visible, THE SYSTEM SHALL incluir valores correspondientes en los catálogos ES y EN.
3. IF falta una traducción requerida en cualquiera de los dos idiomas, THEN THE SYSTEM SHALL detectarlo mediante una verificación automatizada o test documentado.
4. WHEN se documente una feature futura, THE SYSTEM SHALL indicar que no se permiten strings visibles hardcodeados en componentes.

### R5 — Estados transversales de interfaz

**As a** usuaria, **I want** respuestas coherentes durante cargas, fallos y ausencia de datos, **so that** siempre entienda el estado de la interfaz y la acción disponible.

Acceptance criteria:

1. WHEN una vista espere datos remotos, THE SYSTEM SHALL ofrecer una convención reutilizable y accesible para representar el estado de loading.
2. WHEN una operación remota falle, THE SYSTEM SHALL ofrecer una convención reutilizable para mostrar un error comprensible y, WHERE la operación sea reintentable, una acción de reintento.
3. WHEN una consulta válida no devuelva elementos, THE SYSTEM SHALL ofrecer una convención de empty state diferenciada del error y de la carga.
4. WHEN se prueben estas convenciones, THE SYSTEM SHALL verificar que loading, error y empty sean estados mutuamente distinguibles y no dependan de datos de negocio inventados.

### R6 — Estrategia de testing y documentación frontend

**As a** equipo de desarrollo, **I want** una estrategia de testing y convenciones frontend documentadas, **so that** los siguientes changes se implementen y revisen de forma uniforme.

Acceptance criteria:

1. WHEN se implemente la fundación, THE SYSTEM SHALL proporcionar una configuración de tests frontend compatible con Testing Library para componentes con comportamiento y con el runner adoptado por el scaffold integrado.
2. WHEN se verifique el layout y las primitivas transversales, THE SYSTEM SHALL incluir tests de comportamiento para los casos relevantes de responsive layout, internacionalización y estados loading/error/empty.
3. WHEN una persona contribuya al frontend, THE SYSTEM SHALL disponer de documentación versionada sobre estructura modular, dependencias permitidas, estado remoto, uso limitado de Zustand, cliente API, i18n, estilos, testing y criterios para componentes compartidos.
4. WHEN se ejecute la verificación documentada del frontend, THE SYSTEM SHALL ejecutar al menos type-check, lint y tests sin depender de un backend funcional ni de datos de negocio ficticios.

### R7 — Preparación para autenticación futura sin implementarla

**As a** desarrolladora del futuro módulo de autenticación, **I want** puntos de extensión claros en la fundación, **so that** login, sesión y protección de rutas puedan añadirse posteriormente sin reestructurar toda la aplicación.

Acceptance criteria:

1. WHEN se documente la arquitectura, THE SYSTEM SHALL identificar dónde se integrarán en el futuro el contexto de sesión, el transporte autenticado y la protección de rutas.
2. WHEN se revise este change, THE SYSTEM SHALL NOT incluir pantalla o flujo de login, emisión o refresh de JWT, persistencia de tokens, autorización RBAC ni guards funcionales.
3. IF una decisión de autenticación depende del contrato de backend, THEN THE SYSTEM SHALL diferirla al change de autenticación correspondiente y registrar esa dependencia sin inventar comportamiento.
4. WHEN se incorpore autenticación en el futuro, THE SYSTEM SHALL mantener al backend como autoridad de RBAC; el frontend solo podrá adaptar la presentación.

### R8 — Application Shell

**As a** user of AutoHostAI, **I want** a complete and responsive Application Shell, **so that** I can navigate the product structure while functional modules are delivered progressively.

Acceptance criteria:

1. WHEN the frontend application starts, THE SYSTEM SHALL render the complete Application Shell without requiring a functional backend.
2. WHEN a user navigates the shell, THE SYSTEM SHALL provide primary navigation to the module surfaces defined in PRD section 24.
3. WHEN the shell is displayed on desktop, THE SYSTEM SHALL provide a sidebar and a topbar.
4. WHEN the shell is displayed on tablet, THE SYSTEM SHALL provide a collapsible sidebar.
5. WHEN the shell is displayed on mobile, THE SYSTEM SHALL provide a topbar and bottom navigation.
6. WHEN a user opens any route defined in PRD section 24 whose module is not implemented, THE SYSTEM SHALL render a localized "Coming Soon" state or equivalent within the common visual structure.
7. WHEN a placeholder route is inspected or tested, THE SYSTEM SHALL NOT contain business logic, workflows, backend integrations, API calls, invented contracts, or business mock data.
8. WHEN navigation changes between desktop, tablet, and mobile layouts, THE SYSTEM SHALL preserve access to the applicable primary destinations without defining their final visual design.

### R9 — Configuration strategy

**As a** frontend developer, **I want** a consistent configuration strategy, **so that** environment-dependent behavior can be introduced later without scattering configuration across the Application Shell.

Acceptance criteria:

1. WHEN the frontend conventions are documented, THE SYSTEM SHALL define a single strategy for build-time environment variables and runtime configuration, including ownership, validation, and access boundaries.
2. WHEN backend integration is implemented in a future change, THE SYSTEM SHALL obtain the backend base URL through the defined configuration boundary rather than hardcoded values.
3. WHEN language configuration is introduced or resolved, THE SYSTEM SHALL use the defined configuration boundary and remain compatible with the ES/EN internationalization requirement.
4. WHEN feature flags are introduced in a future change, THE SYSTEM SHALL use the defined configuration boundary rather than ad hoc conditionals distributed across components.
5. WHEN this change is reviewed, THE SYSTEM SHALL document these extension points without activating feature flags, performing backend calls, or inventing configuration contracts not established by their owning changes.

## Out of scope

- Crear o modificar el monorepo, Docker, Docker Compose, Makefile, IaC, CI/CD o cualquier parte de `infra-scaffold`.
- Re-crear o re-inicializar desde cero el scaffold Next.js (`package.json`, `next.config`, Vitest, Compose, Dockerfile) que ya entregó `local-environment`; este change se construye sobre ese scaffold ya integrado en `origin/main`.
- Implementar login, recuperación de contraseña, sesión, JWT, refresh de tokens, RBAC o protección efectiva de rutas.
- Implementar dashboard funcional, property cards, property detail funcional o timeline.
- Implementar módulos o interfaces funcionales de limpieza, incidencias/mantenimiento, conversaciones, pricing, statements, reservas, accesos, reviews, approvals o settings; sus rutas y placeholders dentro del shell sí forman parte de este change.
- Implementar workflows de las apps mobile-first de limpiadora o técnico; su navegación, layout y rutas placeholder sí forman parte del Application Shell.
- Integrar el frontend con el backend o realizar llamadas API.
- Inventar endpoints, contratos API, DTOs, payloads o reglas de validación que todavía no hayan sido definidos por backend.
- Crear mocks, fixtures o datos de negocio dentro de componentes de producción.
- Introducir un design system completo, branding definitivo o un rediseño visual final.
- Ejecutar diseño, desglose de tareas o implementación antes de la aprobación explícita de esta propuesta.

## Affected specs

- `sdd/specs/frontend-foundation.md` *(no existe aún — se creará al archivar)*
