# Proposal: frontend-dependency-security

## Why

El árbol de dependencias del frontend contiene vulnerabilidades conocidas que afectan a `next`, `postcss`, `sharp` y `brace-expansion`. El baseline obtenido con `npm audit` el 2026-08-02 registra cuatro paquetes afectados —tres de producción—: `next` es una dependencia directa; `postcss` y `sharp` son transitivas de Next; y `brace-expansion` es transitiva de desarrollo. La remediación debe reducir esa exposición con las actualizaciones mínimas compatibles, sin introducir cambios funcionales ni recurrir a correcciones forzadas.

## What changes

Se analizará cada vulnerabilidad y su ruta de dependencia antes de modificar la resolución del frontend. Se actualizarán únicamente las dependencias directas necesarias y el lockfile con las versiones mínimas compatibles que eliminen las vulnerabilidades corregibles, evitando intervenciones redundantes sobre transitivas que queden resueltas al actualizar Next.js. El resultado conservará compatibilidad con Node 22 y será verificado mediante instalación limpia, audits de dependencias de desarrollo y producción, tests, lint, typecheck y build.

## Requirements

### R1 — Baseline y análisis de vulnerabilidades

**As a** mantenedora del frontend, **I want** conocer cada vulnerabilidad y su ruta en el árbol de dependencias antes de actualizar, **so that** la remediación sea mínima y trazable.

Acceptance criteria:

1. WHEN comienza la remediación, THE SYSTEM SHALL registrar los resultados previos de `npm audit` y `npm audit --omit=dev`, identificando para cada vulnerabilidad el paquete afectado, su severidad, el advisory, el rango vulnerable y si la dependencia es directa o transitiva.
2. WHEN una vulnerabilidad pertenece a una dependencia transitiva, THE SYSTEM SHALL identificar qué dependencia directa introduce esa ruta antes de seleccionar una corrección.
3. WHEN varias vulnerabilidades comparten una misma dependencia directa como origen, THE SYSTEM SHALL analizarlas conjuntamente para evitar actualizaciones transitivas redundantes.
4. WHEN se modifica una dependencia, THE SYSTEM SHALL registrar su versión inicial, su versión final y el motivo de la actualización.

### R2 — Actualización mínima y compatible

**As a** mantenedora del producto, **I want** aplicar la corrección mínima compatible para cada vulnerabilidad, **so that** se reduzca el riesgo de regresión y se preserve el comportamiento existente.

Acceptance criteria:

1. WHEN existe una versión corregida compatible, THE SYSTEM SHALL seleccionar la actualización mínima que saque la resolución del rango vulnerable y mantenga compatibilidad con Node 22.
2. WHEN la actualización de Next.js elimina vulnerabilidades de `postcss`, `sharp` u otras dependencias transitivas, THE SYSTEM SHALL conservar la resolución resultante sin añadir actualizaciones u overrides redundantes.
3. THE SYSTEM SHALL actualizar las dependencias mediante comandos explícitos y SHALL NOT ejecutar `npm audit fix --force`.
4. IF una vulnerabilidad solo puede corregirse mediante un salto mayor o una actualización con riesgo material de regresión, THEN THE SYSTEM SHALL documentar en `design.md` la alternativa, el riesgo y la decisión antes de implementarla.
5. IF una actualización de Next.js modifica comportamiento observable —incluidos SSR, routing, build o renderizado—, THEN THE SYSTEM SHALL identificar explícitamente el efecto y SHALL NOT continuar hasta demostrar que no introduce regresiones funcionales o documentar la incidencia en `design.md`.

### R3 — Resultado de seguridad verificable

**As a** responsable de seguridad, **I want** verificar por separado el árbol completo y el de producción tras la remediación, **so that** quede clara la exposición residual desplegable y de desarrollo.

Acceptance criteria:

1. WHEN termina la actualización, THE SYSTEM SHALL ejecutar de nuevo `npm audit` y `npm audit --omit=dev` sobre el lockfile resultante.
2. WHEN una vulnerabilidad dispone de una corrección compatible, THE SYSTEM SHALL dejar de reportarla en el audit posterior aplicable.
3. IF alguna vulnerabilidad no es corregible dentro de las restricciones del change, THEN THE SYSTEM SHALL documentar su advisory, severidad, ruta de dependencia, exposición, motivo de no corrección y condición para revisarla.
4. WHEN se comparan los audits anterior y posterior, THE SYSTEM SHALL demostrar que todas las vulnerabilidades corregibles han sido eliminadas y que cualquier exposición residual está justificada documentalmente.
5. IF una actualización mínima compatible provoca una regresión demostrable en tests, lint, typecheck o build, THEN THE SYSTEM SHALL revertir únicamente esa actualización y documentar la incidencia en `design.md` antes de continuar.

### R4 — Instalación y gates reproducibles

**As a** desarrolladora del frontend, **I want** que el árbol corregido siga siendo reproducible y pase todos los gates existentes, **so that** la remediación no rompa desarrollo, CI ni despliegue.

Acceptance criteria:

1. WHEN se instala el frontend desde cero con Node 22, THE SYSTEM SHALL completar `npm ci` usando `frontend/package-lock.json` sin modificarlo ni producir errores de compatibilidad.
2. WHEN termina la instalación limpia, THE SYSTEM SHALL completar satisfactoriamente `npm test`, `npm run lint`, `npm run typecheck` y `npm run build`.
3. IF `frontend/package.json` y `frontend/package-lock.json` dejan de ser coherentes, THEN THE SYSTEM SHALL fallar la verificación y no considerar completada la remediación.

### R5 — Invariancia funcional

**As a** usuaria de AutoHostAI, **I want** que la remediación de dependencias sea funcionalmente neutra, **so that** el producto conserve su comportamiento y sus interfaces actuales.

Acceptance criteria:

1. WHEN se revisa el change, THE SYSTEM SHALL mantener sin cambios funcionales los componentes del dashboard, los mocks y los contratos API.
2. THE SYSTEM SHALL NOT añadir, eliminar ni alterar funcionalidad del producto como parte de esta remediación.
3. WHEN se ejecutan los tests y el build existentes, THE SYSTEM SHALL completarlos sin regresiones atribuibles a la actualización de dependencias.

## Out of scope

- Cambios de funcionalidad, UX o comportamiento del producto.
- Modificaciones de componentes del dashboard o de sus estilos responsive.
- Modificaciones de mocks, fixtures o datos de demostración.
- Modificaciones de contratos API, tipos derivados del contrato o integración con backend.
- Upgrades no requeridos para remediar una vulnerabilidad analizada.
- Introducir un gate permanente de `npm audit` en CI; cualquier cambio de política de CI requiere una decisión separada.

## Affected specs

- `sdd/specs/frontend-dependency-security.md` *(no existe aún — se creará al archivar)* — baseline de seguridad del árbol de dependencias, estrategia de remediación y verificaciones reproducibles.
