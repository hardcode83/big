# Tasks: CI del frontend

## 1. Estructura y políticas del workflow

- [x] 1.1 Crear `.github/workflows/frontend-tests.yml` con nombre y job `frontend-tests`, disparadores `pull_request`, push limitado a `main` y `workflow_dispatch`, sin `paths` ni `paths-ignore`; añadir `concurrency.group: frontend-tests-${{ github.ref }}` y `cancel-in-progress: true`. [R1]
- [x] 1.2 Configurar el job en `ubuntu-latest` con `timeout-minutes: 15` y declarar a nivel de workflow únicamente `permissions: contents: read`. [R4]
- [x] 1.3 Añadir `actions/checkout` y `actions/setup-node` con los SHA decididos en el Design, configurar Node `22`, `cache: npm` y `cache-dependency-path: frontend/package-lock.json`; no usar referencias mutables de actions. [R2, R4]

## 2. Instalación y verificaciones diferenciadas

- [x] 2.1 Añadir en `.github/workflows/frontend-tests.yml` una única instalación `npm ci` con `working-directory: frontend`, identificable como paso de instalación y sin cachear `node_modules`. [R2]
- [x] 2.2 Añadir los tres pasos nombrados e identificados `Tests (Vitest)`/`tests`, `Lint (ESLint)`/`lint` y `Typecheck (TypeScript)`/`typecheck`, ejecutando desde `frontend/` exactamente `npm test`, `npm run lint` y `npm run typecheck`; ejecutar los tres tras una instalación satisfactoria y conservar cada `outcome` aunque uno falle. [R3]
- [x] 2.3 Añadir un paso final con `if: always()` que muestre un resumen diferenciado de tests, lint y typecheck y haga fallar el job si la instalación `npm ci` o cualquiera de las tres verificaciones no terminó satisfactoriamente, tratando expresamente las cancelaciones sin ocultar ningún fallo. [R2, R3]

## 3. Verificación

- [x] 3.1 Validar localmente `.github/workflows/frontend-tests.yml`: sintaxis YAML válida y estructura compatible con GitHub Actions según revisión estática; los tres triggers presentes; push acotado a `main`; ninguna clave `paths`/`paths-ignore`; concurrency por referencia con cancelación; timeout de 15 minutos; permiso único `contents: read`; actions pineadas a los SHA del Design; Node `22`; caché ligada a `frontend/package-lock.json`; ausencia de `npm run build`. [R1, R2, R4]
- [x] 3.2 En un entorno limpio con Node 22, verificar la instalación reproducible y la suite completa del frontend: `cd frontend && npm ci`, `npm test`, `npm run lint` y `npm run typecheck`. Si aparece un fallo preexistente, registrarlo como bloqueo/hallazgo separado sin modificar tests, lint, configuración TypeScript ni código de producto en este change. [R2, R3]
- [x] 3.3 Ejecutar `git diff --check` y revisar el diff para confirmar que la implementación solo añade `.github/workflows/frontend-tests.yml`, no modifica los workflows de build/deploy existentes y mantiene `npm run build` fuera de este gate. [R4]

**Gate remoto obligatorio de la fase PR — PENDIENTE:** antes del merge, GitHub Actions debe aceptar el workflow, crear el check `frontend-tests`, ejecutarlo en el Pull Request y finalizar correctamente. Esta comprobación no forma parte del cierre local de `/sdd:run` y no se considera ejecutada todavía.
