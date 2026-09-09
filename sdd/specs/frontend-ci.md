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
- THE SYSTEM SHALL **reportar siempre un resultado del check `frontend-tests`**, toque el diff
  el frontend o no — mismo invariante que `backend-tests` (`specs/backend-ci.md`): un check
  requerido que no se ejecuta deja el Pull Request bloqueado esperando indefinidamente.
- THE SYSTEM SHALL conseguirlo **sin `paths:` en `on:`**: un filtro a nivel de disparador no
  produce check alguno en los PR que no tocan esas rutas. El filtrado ocurre **dentro** del
  workflow.
- THE SYSTEM SHALL estructurarlo en tres jobs: `frontend-tests-detect` decide el área a partir
  del diff, `frontend-tests-suite` corre la verificación completa **solo si** la detección dice
  que el diff toca el frontend, y `frontend-tests` publica el resultado con `if: always()`.
- THE SYSTEM SHALL anclar en `frontend-tests-detect` las ocho rutas siguientes (`design.md`
  D1.1/D1.1.d del change `ci-pr-gates-optimization`: el detect debe ser un superconjunto de la
  superficie de dependencias de `frontend-tests-suite` — tanto el código de guard que la
  suite ejecuta como el corpus del que es el único gate designado; `scripts/*` se ancla en
  bloque, superseding los dos scripts `.py` nombrados): `frontend/*`,
  `frontend/devops/Dockerfile`, `frontend/package.json`, `frontend/package-lock.json`,
  `scripts/*`, `.github/scripts/*`, `Makefile`, `.github/workflows/frontend-tests.yml`.
- WHEN la detección concluye que el diff **no** toca ninguna de esas ocho rutas, THE SYSTEM
  SHALL saltarse la suite y publicar el check en verde con el motivo.
- IF la detección falla o no puede determinar el área, THEN THE SYSTEM SHALL decidir a favor de
  ejecutar la suite (fail-open), igual que `backend-tests`.
- THE SYSTEM SHALL leer el diff con las rutas sin escapar (`core.quotePath=false`), separadas
  por NUL (`-z`) y sin detección de renombrados (`--no-renames`), comparando cada ruta
  individualmente con `case` — mismas razones que `specs/backend-ci.md` documenta para su
  propio detector.
- WHEN comienza una ejecución nueva para la misma referencia, THE SYSTEM SHALL cancelar la
  anterior mediante un grupo de concurrencia por referencia.

### El job de verificación (`frontend-tests-suite`)

- WHEN la detección concluye que el diff toca el frontend, THE SYSTEM SHALL ejecutar
  `frontend-tests-suite` en el runner self-hosted `[self-hosted, dev]` (migrado desde
  `ubuntu-latest` por `ci-runner-oci`, 2026-09-04; ver `ci-runner-self-hosted.md`), limitarlo
  a 15 minutos y conceder únicamente `contents: read`.
- THE SYSTEM SHALL pinear por SHA de commit cada action utilizada y SHALL impedir que
  `actions/checkout` persista credenciales Git para los pasos posteriores.
- WHEN prepara Node.js, THE SYSTEM SHALL seleccionar Node 22, la versión mayor declarada por
  `frontend/devops/Dockerfile`.
- WHEN prepara `python3`, THE SYSTEM SHALL usar `actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0`
  con `python-version: "3.12"`: el runner self-hosted trae `python3` 3.10 del sistema,
  insuficiente para el `tomllib` que `make check-version-parity` usa (ver
  `ci-runner-self-hosted.md`).
- THE SYSTEM SHALL cachear las descargas de npm usando `frontend/package-lock.json` como
  dependencia de la caché, pero SHALL NOT cachear `node_modules`.
- WHEN instala dependencias, THE SYSTEM SHALL ejecutar una **única** vez `npm ci` desde
  `frontend/` por ejecución del job (antes de este change, `provenance-contract` y
  `frontend-tests` eran jobs separados y cada uno instalaba por su cuenta).
- IF `frontend/package.json` y `frontend/package-lock.json` no son coherentes, THEN THE
  SYSTEM SHALL fallar durante la instalación y no ejecutar las verificaciones que dependen
  de ella.
- THE SYSTEM SHALL fusionar en este job las nueve señales que antes se repartían entre
  `provenance-contract` y `frontend-tests`: version parity (`make check-version-parity`),
  autotest del extractor de PR, autotest del validador del contrato de provenance, `npm ci`,
  contrato de API + disclosure de provenance, build de producción + disclosure de artefactos
  públicos, tests (Vitest node), guarda de desbordamiento a 360px (Vitest browser vía
  Playwright/Chromium), lint (ESLint) y typecheck (TypeScript).
- WHEN una de las señales falla, THE SYSTEM SHALL conservar su resultado
  (`continue-on-error: true` por señal) y continuar con las demás, para que el job publique
  todas las señales disponibles en la misma ejecución en lugar de abortar en la primera roja.
- THE SYSTEM SHALL mantener `npm run build` como parte de la señal de disclosure de
  artefactos públicos únicamente (no como paso de despliegue): los workflows de build y
  despliegue conservan esa responsabilidad para producción.

### Caché del navegador de Playwright

- WHEN el job ejecuta la guarda de layout 360px, THE SYSTEM SHALL restaurar y guardar el
  binario del navegador (`~/.cache/ms-playwright`) con `actions/cache`, usando como clave
  **exacta** `playwright-${{ hashFiles('frontend/package-lock.json') }}`.
- THE SYSTEM SHALL NOT declarar `restore-keys:` para esa caché: una clave sin `restore-keys`
  produce un miss limpio cuando el lockfile cambia, en vez de restaurar en silencio un binario
  de un lockfile distinto (riesgo de binario desactualizado).
- THE SYSTEM SHALL ejecutar `playwright install --with-deps chromium` **siempre**, con
  independencia de si hubo cache hit o miss: las dependencias de sistema del navegador no
  viven en esa caché, solo el binario. La caché ahorra la descarga del binario, no la
  instalación de dependencias de sistema.
- WHEN el cache-restore no reporta hit, THE SYSTEM SHALL guardar la caché tras la ejecución
  (`if: steps.cache-restore.outputs.cache-hit != 'true'`).

### El job consolidador (`frontend-tests`)

- THE SYSTEM SHALL ejecutar `frontend-tests` con `needs: [frontend-tests-detect,
  frontend-tests-suite]` e `if: always()`, y SHALL hacer fallar el check si la detección no
  terminó en `success`, si la suite corrió pero alguna señal no terminó en `success`, o si la
  suite terminó en un resultado distinto de `success`/`skipped`.
- WHEN la suite se saltó porque la detección dijo que el diff no tocaba el frontend, THE
  SYSTEM SHALL publicar el check en verde nombrando explícitamente que no había nada que
  verificar — nunca como si la suite hubiera pasado.
- THE SYSTEM SHALL mostrar en el resumen de GitHub Actions el veredicto, el estado de la
  suite, la decisión de área con su motivo, y una tabla con el resultado de cada señal.

### Estado del check

- WHILE el repositorio no disponga de protección de rama compatible, THE SYSTEM SHALL
  ejecutar y reportar `frontend-tests` sin configurarlo como check obligatorio para fusionar.

### Contrato de identidad y paridad

- Las tres verificaciones de esta subsección son señales de `frontend-tests-suite` (ver
  arriba), no un job separado: `make check-version-parity`, el autotest del extractor de PR y
  el autotest del validador del contrato de provenance.
- THE SYSTEM SHALL execute `make check-version-parity` como señal de `frontend-tests-suite` y
  SHALL fail when `VERSION`, `backend/pyproject.toml` and `frontend/package.json` are missing,
  empty or divergent.
- WHEN a Pull Request changes the provenance producer or public consumer, THE SYSTEM SHALL run
  the versioned producer/consumer congruence check as part of `frontend-tests-suite`, including
  the rejection of repository URL, Pull Request number, full SHA and Actions run ID in the
  public frontend contract.
- THE SYSTEM SHALL keep `.github/scripts/extract-pr.sh --self-test` and the congruence gate
  executable from a clean checkout with diagnostic failure messages.

## Key files

- `.github/workflows/frontend-tests.yml` — workflow, políticas y consolidación de resultados.
- `frontend/package.json` — scripts de tests, lint y typecheck ejecutados por CI.
- `frontend/package-lock.json` — resolución reproducible y clave de la caché de npm.
- `frontend/devops/Dockerfile` — autoridad versionada para Node 22.
