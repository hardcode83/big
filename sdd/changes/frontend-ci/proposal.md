# Propuesta: CI del frontend

## Por qué

La suite del frontend solo se ejecuta hoy en máquinas locales: ningún workflow de GitHub Actions invoca Vitest, ESLint ni el typecheck de TypeScript. Esto impide que una afirmación como «la suite del frontend está en verde» sea evidencia reproducible y ya permitió que 27 tests rotos permanecieran sin señal en CI hasta que otro cambio los descubrió accidentalmente. Este cambio nace de la entrada `frontend-ci` de `sdd/roadmap.md` y adopta el mismo encuadre que la capacidad existente descrita en `sdd/specs/backend-ci.md`.

## Qué cambia

Se añadirá un workflow de GitHub Actions dedicado a verificar el frontend en un entorno limpio. En cada Pull Request y push a `main`, instalará las dependencias bloqueadas y ejecutará por separado la suite Vitest, ESLint y el typecheck de TypeScript, respetando las políticas de seguridad y CI del repositorio. El check se ejecutará y reportará, pero no se configurará como obligatorio mientras el plan actual del repositorio no permita protección de rama.

## Requisitos

### R1 — Verificación automática en cambios compartidos

**Como** persona que revisa o integra cambios, **quiero** que las verificaciones del frontend se ejecuten automáticamente, **para que** su resultado sea evidencia reproducible y visible en GitHub.

Criterios de aceptación:

1. WHEN se abre, reabre o actualiza un Pull Request, THE SYSTEM SHALL ejecutar el workflow de CI del frontend.
2. WHEN se hace push a `main`, THE SYSTEM SHALL ejecutar el workflow de CI del frontend.
3. WHEN una ejecución nueva comienza para la misma referencia, THE SYSTEM SHALL cancelar la ejecución anterior que siga en curso.
4. WHEN el cambio no toca rutas bajo `frontend/**`, THE SYSTEM SHALL ejecutar igualmente el workflow, sin filtros de rutas que puedan dejar un check esperado indefinidamente pendiente.
5. WHEN una persona necesita repetir el check manualmente, THE SYSTEM SHALL permitir iniciar el workflow mediante `workflow_dispatch`.

### R2 — Instalación reproducible

**Como** persona desarrolladora, **quiero** que CI reconstruya el entorno desde el lockfile, **para que** detecte dependencias incoherentes y no dependa del estado de una máquina local.

Criterios de aceptación:

1. WHEN comienza el job, THE SYSTEM SHALL usar en un runner limpio de GitHub Actions la versión de Node.js declarada oficialmente para el frontend por la configuración versionada del repositorio (`frontend/devops/Dockerfile`).
2. WHEN se instalan las dependencias del frontend, THE SYSTEM SHALL ejecutar `npm ci` desde `frontend/` usando el `package-lock.json` versionado.
3. IF `package.json` y `package-lock.json` no son coherentes, THEN THE SYSTEM SHALL finalizar el job con error antes de ejecutar las verificaciones.

### R3 — Suite, lint y tipos como checks independientes

**Como** persona que diagnostica un fallo de CI, **quiero** distinguir qué verificación del frontend ha fallado, **para que** el resultado sea accionable sin reproducir primero toda la ejecución en local.

Criterios de aceptación:

1. WHEN las dependencias están instaladas, THE SYSTEM SHALL ejecutar desde `frontend/` el script `test` definido en `frontend/package.json` mediante `npm test` y fallar si Vitest devuelve un resultado no satisfactorio.
2. WHEN las dependencias están instaladas, THE SYSTEM SHALL ejecutar desde `frontend/` el script `lint` definido en `frontend/package.json` mediante `npm run lint` y fallar si ESLint detecta errores.
3. WHEN las dependencias están instaladas, THE SYSTEM SHALL ejecutar desde `frontend/` el script `typecheck` definido en `frontend/package.json` mediante `npm run typecheck` y fallar si `tsc --noEmit` detecta errores de tipos.
4. WHEN GitHub Actions presenta el resultado del job, THE SYSTEM SHALL mostrar resultados diferenciados para tests, lint y typecheck, de forma que la revisión identifique expresamente cuál de las tres verificaciones falló.

### R4 — Ejecución acotada y de mínimo privilegio

**Como** persona responsable del repositorio, **quiero** que el workflow tenga un radio de acción limitado, **para que** una verificación de frontend no obtenga permisos ni consuma tiempo innecesarios.

Criterios de aceptación:

1. WHEN GitHub Actions ejecuta el workflow, THE SYSTEM SHALL conceder únicamente el permiso `contents: read`.
2. WHEN el job supera su límite de tiempo declarado, THE SYSTEM SHALL cancelarlo automáticamente.
3. THE SYSTEM SHALL pinear por SHA de commit cada action de terceros utilizada por el workflow.
4. WHILE el repositorio no disponga de protección de rama compatible, THE SYSTEM SHALL ejecutar y reportar el check sin configurarlo como requisito obligatorio para fusionar.

## Fuera de alcance

- Configurar reglas de protección de rama o convertir el check en obligatorio; depende del plan/capacidades de GitHub del repositorio.
- Ejecutar `npm run build`; los workflows de build existentes ya cubren la construcción y este cambio se limita a Vitest, ESLint y TypeScript.
- Modificar tests, reglas de lint, configuración TypeScript o código de producto para corregir fallos que el nuevo workflow pueda revelar.
- Cambiar los workflows de backend, despliegue, infraestructura o build multiarquitectura.

## Specs afectadas

- `sdd/specs/frontend-ci.md` *(no existe aún — se creará al archivar)*.
