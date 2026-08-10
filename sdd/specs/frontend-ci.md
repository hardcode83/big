# Integración continua del frontend

## Purpose

Esta capacidad verifica en GitHub Actions la calidad del frontend en un entorno limpio y
reproducible. Ejecuta Vitest, ESLint y el typecheck de TypeScript como señales diferenciadas,
sin duplicar la construcción de imágenes ni las responsabilidades de despliegue.

## Requirements

### Disparadores y alcance

- WHEN se abre, reabre o actualiza un Pull Request, THE SYSTEM SHALL ejecutar el workflow
  `frontend-tests`.
- WHEN se hace push a `main`, THE SYSTEM SHALL ejecutar el workflow `frontend-tests`.
- WHEN una persona inicia una ejecución manual, THE SYSTEM SHALL admitir
  `workflow_dispatch`.
- THE SYSTEM SHALL ejecutar el workflow sin filtros `paths` ni `paths-ignore`, aunque el
  cambio no toque `frontend/**`.
- WHEN comienza una ejecución nueva para la misma referencia, THE SYSTEM SHALL cancelar la
  anterior mediante un grupo de concurrencia por referencia.

### Entorno e instalación reproducible

- WHEN comienza el job, THE SYSTEM SHALL ejecutarlo en `ubuntu-latest`, limitarlo a 15
  minutos y conceder únicamente `contents: read`.
- THE SYSTEM SHALL pinear por SHA de commit cada action utilizada y SHALL impedir que
  `actions/checkout` persista credenciales Git para los pasos posteriores.
- WHEN prepara Node.js, THE SYSTEM SHALL seleccionar Node 22, la versión mayor declarada por
  `frontend/devops/Dockerfile`.
- THE SYSTEM SHALL cachear las descargas de npm usando `frontend/package-lock.json` como
  dependencia de la caché, pero SHALL NOT cachear `node_modules`.
- WHEN instala dependencias, THE SYSTEM SHALL ejecutar una única vez `npm ci` desde
  `frontend/`.
- IF `frontend/package.json` y `frontend/package-lock.json` no son coherentes, THEN THE
  SYSTEM SHALL fallar durante la instalación y no ejecutar las verificaciones.

### Verificaciones y diagnóstico

- WHEN la instalación termina satisfactoriamente, THE SYSTEM SHALL ejecutar desde
  `frontend/` los scripts versionados `npm test`, `npm run lint` y `npm run typecheck`.
- WHEN una de las tres verificaciones falla, THE SYSTEM SHALL conservar su resultado y
  continuar con las demás para mostrar todas las señales disponibles en la misma ejecución.
- THE SYSTEM SHALL mostrar en el resumen de GitHub Actions resultados separados para la
  instalación, Vitest, ESLint y el typecheck de TypeScript.
- THE SYSTEM SHALL ejecutar la consolidación final con `if: always()` y SHALL hacer fallar el
  job si la instalación o cualquiera de las tres verificaciones termina con un resultado
  distinto de `success`, incluidas cancelaciones y verificaciones no ejecutadas.
- THE SYSTEM SHALL mantener `npm run build` fuera de este workflow; los workflows de build y
  despliegue conservan esa responsabilidad.

### Estado del check

- WHILE el repositorio no disponga de protección de rama compatible, THE SYSTEM SHALL
  ejecutar y reportar `frontend-tests` sin configurarlo como check obligatorio para fusionar.

### Contrato de identidad y paridad

- THE SYSTEM SHALL execute `make check-version-parity` as a separate CI signal and SHALL fail
  when `VERSION`, `backend/pyproject.toml` and `frontend/package.json` are missing, empty or
  divergent.
- WHEN a Pull Request changes the provenance producer or public consumer, THE SYSTEM SHALL run
  the versioned producer/consumer congruence check, including the rejection of repository URL,
  Pull Request number, full SHA and Actions run ID in the public frontend contract.
- THE SYSTEM SHALL keep `.github/scripts/extract-pr.sh --self-test` and the congruence gate
  executable from a clean checkout with diagnostic failure messages.

## Key files

- `.github/workflows/frontend-tests.yml` — workflow, políticas y consolidación de resultados.
- `frontend/package.json` — scripts de tests, lint y typecheck ejecutados por CI.
- `frontend/package-lock.json` — resolución reproducible y clave de la caché de npm.
- `frontend/devops/Dockerfile` — autoridad versionada para Node 22.
