# Proposal: hardening-release

## Why

El roadmap deja `hardening-release` para el final a propósito: cierra los pasos 27-28 de PRD §26 (suite E2E Playwright, docker + README de arranque) y el DoD del MVP (PRD §28), y necesitaba el ciclo operativo completo desde el navegador para tener algo entero que proteger. Ese ciclo ya está cerrado — `reservation-create-web`, `reservation-confirm-web`, `incident-triage-web`, `approvals-web`, `cleaning-task-manage-web` y `sim-advance` están todos archivados — así que esta entrada puede ejecutarse ahora.

`sdd/steering/testing.md` ya declara la obligación (E2E solo en los flujos críticos: login, ciclo de limpieza completo, ciclo de incidencia) y las dos coberturas obligatorias del DoD (`#28.18` aislamiento de tenant por módulo, `#28.19` todas las transiciones de la state machine, incluidas las inválidas). Ninguna de las tres tiene hoy una suite E2E real —no existe `playwright.config.ts` ni un directorio `e2e/`—, y aunque `backend/tests/**/test_isolation.py` y las pruebas de state machine ya existen módulo a módulo, nadie ha verificado que cubran los directorios de dominio de negocio bajo `backend/app/` (18 por conteo directo — ver R5.1) ni las transiciones inválidas como conjunto.

## What changes

Se añade una suite E2E con Playwright (proyecto separado del `test:layout` que ya existe en `frontend/`) que ejercita de extremo a extremo, contra el stack real levantado por `make up`, los tres flujos que `testing.md` marca como críticos: login, el ciclo de limpieza completo (crear/asignar tarea → aceptar → completar checklist → subir fotos → propiedad cambia de estado) y el ciclo de incidencia (crear → clasificar → triar → asignar → aceptar → resolver → aprobación si aplica). Se integra en CI como un workflow nuevo, condicional igual que `backend-tests`/`frontend-tests`. Se audita la cobertura existente de aislamiento de tenant (un módulo por dominio de negocio de los 18 en `backend/app/`) y de transiciones de la state machine (incluidas las que deben rechazarse), documentando el resultado y cerrando cualquier hueco real que aparezca. El README y el `docker compose up` único ya satisfacen DoD `#28.20`; esta entrada solo lo verifica, no lo reconstruye.

## Requirements

### R1 — Infraestructura de la suite E2E

**As a** engineer, **I want** un proyecto Playwright E2E separado y ejecutable contra el stack de `make up`, **so that** los flujos críticos se puedan probar de extremo a extremo sin acoplarse a los tests de componente existentes.

Acceptance criteria:

1. WHEN se ejecuta `npx playwright test` desde `frontend/` (o el comando que la Verification documente), THE SYSTEM SHALL correr un proyecto Playwright distinto de `test:layout`, con su propio `playwright.config.ts` y directorio de specs (`frontend/e2e/` o equivalente), contra el frontend/backend reales servidos por `make up`.
2. WHEN el stack no está levantado, THE SYSTEM SHALL fallar con un mensaje que identifique la causa (no un timeout genérico) — la suite documenta el pre-requisito de `make up` en vez de levantarlo ella misma.
3. WHEN se añade el workflow de CI para esta suite, THE SYSTEM SHALL ejecutarse condicionalmente (mismo patrón que `backend-tests.yml`/`frontend-tests.yml`: se omite y reporta verde con el resumen explícito cuando el diff no toca lo que la suite cubre) y usar el runner self-hosted como el resto de workflows migrados.

### R2 — E2E: flujo de login

**As a** QA engineer, **I want** un test E2E de login real, **so that** una regresión en autenticación por navegador se detecte antes de producción.

Acceptance criteria:

1. WHEN el test navega a `/login`, introduce credenciales válidas de un usuario sembrado y envía el formulario por clic, THE SYSTEM SHALL autenticar y redirigir a `/dashboard`.
2. WHEN el test introduce credenciales inválidas, THE SYSTEM SHALL mostrar el error correspondiente sin redirigir.
3. IF el usuario tiene `must_change_password`, THEN THE SYSTEM SHALL bloquear el acceso a rutas autenticadas salvo `me`/`logout`/`change-password`, y el test lo verifica con al menos una petición representativa.

### R3 — E2E: ciclo de limpieza completo

**As a** QA engineer, **I want** un test E2E del ciclo de limpieza de punta a punta, **so that** el flujo operativo central del producto (checkout → limpieza → propiedad lista) quede protegido.

Acceptance criteria:

1. WHEN una `CleaningTask` existe para una propiedad y el rol `CLEANER` la acepta, completa el checklist y sube las fotos requeridas por categoría desde `/cleaner/tasks/[id]`, THE SYSTEM SHALL marcar la tarea completada y actualizar el estado operacional de la propiedad según corresponda.
2. WHEN el `PROPERTY_MANAGER` reasigna la tarea antes de aceptarla, THE SYSTEM SHALL reflejar el nuevo asignado en `/cleaning`.

### R4 — E2E: ciclo de incidencia

**As a** QA engineer, **I want** un test E2E del ciclo de incidencia de punta a punta, **so that** el flujo de mantenimiento (creación → clasificación → resolución) quede protegido.

Acceptance criteria:

1. WHEN se crea una incidencia y `MockAIAdapter` la clasifica, un manager la tría y asigna a un técnico, y el técnico la acepta y resuelve desde `/tech/incidents/[id]`, THE SYSTEM SHALL cerrar la incidencia con su coste registrado.
2. WHEN la incidencia es `CRITICAL`, THE SYSTEM SHALL reflejar la propiedad en rojo mientras esté abierta, verificado en el dashboard dentro del mismo test.
3. IF el coste supera el umbral configurado del tenant, THEN THE SYSTEM SHALL generar un `OwnerApproval` y el test verifica que aparece en `/approvals` para su respuesta.

### R5 — Auditoría y cierre del DoD §28

**As a** tech lead, **I want** una verificación explícita de que el DoD del MVP está cerrado, **so that** "hardening-release" certifique el estado real en vez de asumirlo.

Acceptance criteria:

1. WHEN se audita `#28.18` (tenant isolation testeado), THE SYSTEM SHALL enumerar los directorios de dominio de negocio bajo `backend/app/` (excluyendo infraestructura compartida: `cli`, `core`, `provenance`, `scheduler`) y, para cada uno con estado propio scopado por tenant, confirmar que existe al menos un test que verifique que el tenant A no ve datos del tenant B — y añadir el test que falte donde el hueco sea real. El recuento de partida es **18** por conteo directo del árbol actual (verificado el 2026-09-13), no los 19 de `README.md:311` ni los 17 de `sdd/steering/architecture.md` (ese último es anterior a la incorporación del dominio `platform`) — la auditoría documenta y corrige la cifra que quede desactualizada en cualquiera de los dos, incluyendo el roster de dominios que `README.md` enumera junto a ella.
2. WHEN se audita `#28.19` (todas las transiciones de la state machine testeadas), THE SYSTEM SHALL enumerar las transiciones válidas e inválidas de `PropertyStateMachine` y confirmar cobertura de test para cada una — y añadir la que falte.
3. WHEN se completa la auditoría, THE SYSTEM SHALL dejar constancia escrita (documento o sección de spec) del resultado ítem por ítem de PRD §28, para que una lectura futura no tenga que re-auditar desde cero.

## Out of scope

- `/settings/integrations` (conexión PMS por UI) — excluido del MVP a propósito, ver `sdd/roadmap/hardening-release.md`.
- Cualquier flujo E2E que no sea login, limpieza o incidencia (reservas, pricing, mensajería, reviews, statements) — `testing.md` los deja fuera de "críticos" a propósito; sus regresiones las cubren los tests de integración/componente existentes.
- Cambios al `docker-compose.yml`/README más allá de verificar que el DoD `#28.20` (`make up` único) sigue cumpliéndose — ya está construido por `local-environment`/`infra-scaffold` y no hace falta reconstruirlo.
- `saas-cross-tenant` (post-MVP, entrada de roadmap separada) y cualquier trabajo de `SUPER_ADMIN` cross-tenant.
- Nuevas capacidades de producto: esta entrada es `[CROSS]`/tech, no añade dominio funcional nuevo.

## Affected specs

- `sdd/specs/e2e-testing.md` (no existe aún — se creará al archivar): infraestructura Playwright E2E y los tres flujos críticos.
- `sdd/specs/backend-tooling.md`: sección de auditoría de cobertura de tenant isolation y state machine, si el hueco real justifica una entrada aquí en vez de en el spec nuevo.
- `sdd/specs/local-environment.md`: referencia cruzada a la verificación de DoD `#28.20`, sin cambio de contrato.
