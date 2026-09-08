# Draft de actualización — `sdd/specs/frontend-ci.md`

> Preparado durante `/sdd:run` (sección 6, archive prep). **No se ha tocado el spec vivo.**
> `/sdd:archive ci-pr-gates-optimization` consume este borrador y lo aplica a `sdd/specs/frontend-ci.md`.

## (a) Estado actual del spec

`sdd/specs/frontend-ci.md` describe el estado **anterior** a este change: dos jobs
(`provenance-contract` + `frontend-tests`), sin puerta de área, ejecutando siempre la
verificación completa. Puntos concretos que el archive debe reconciliar con el workflow ya
modificado (`.github/workflows/frontend-tests.yml`, sección "Por qué son tres jobs" en su
cabecera):

- "Disparadores y alcance" (líneas 11-21): no menciona detección de área ni camino corto; dice
  que el workflow se ejecuta "sin filtros `paths` … aunque el cambio no toque `frontend/**`" —
  cierto en el disparador (`on:`, que sigue sin `paths:`), pero ahora dentro del workflow
  **sí** hay una decisión de área que salta la suite.
- "Entorno e instalación reproducible" (líneas 23-36): describe una única instalación con
  `npm ci` "desde `frontend/`" — sigue siendo cierto, pero ahora vive dentro del job
  `frontend-tests-suite`, no en el job único de antes. Falta mención de `frontend-tests-detect`.
- "Verificaciones y diagnóstico" (líneas 38-50): describe las cuatro señales del job único
  (`npm test`, `npm run lint`, `npm run typecheck`, más consolidación). El workflow real ahora
  fusiona nueve/diez señales en `frontend-tests-suite` (versión parity, extractor de PR,
  validador de provenance, `npm ci`, contrato+disclosure de provenance, build+disclosure de
  artefactos públicos, tests Vitest, guarda de layout 360px con Playwright, lint, typecheck) —
  las cinco de provenance más las cuatro de esta sección, en una sola suite. No hay caché de
  Playwright documentada en el spec vigente.
- "Contrato de identidad y paridad" (líneas 57-66): describe las verificaciones de
  `provenance-contract` como si vivieran en un job separado (el que se fusiona ahora en
  `frontend-tests-suite`).
- "Key files" (líneas 68-73): sigue siendo correcto sin cambios.

## (b) Cambios que el archive debe aplicar

1. Reescribir "Disparadores y alcance" para documentar el patrón de tres jobs
   (`frontend-tests-detect` + `frontend-tests-suite` condicional + `frontend-tests`
   consolidador), igual que `backend-ci.md`: `on:` sigue sin `paths:`, el filtrado ocurre
   dentro del workflow, y el check `frontend-tests` se reporta siempre (`if: always()`).
   Documentar las **ocho** anclas del `case` on-disk de `frontend-tests-detect`
   (post-§13-A de `tasks.md`, tabla D1/D1.1 de `design.md`): `frontend/*`,
   `frontend/devops/Dockerfile`, `frontend/package.json`, `frontend/package-lock.json`,
   `scripts/*`, `.github/scripts/*`, `Makefile`, `.github/workflows/frontend-tests.yml`
   (§13-A/`design.md` **D1.1.d**: `frontend-tests-detect` ancla `scripts/*` en bloque —como
   `compose-ports`/`rule11-ownership`—, lo que **supersede** los dos scripts `.py` nombrados
   `scripts/validate-provenance-contract.py`/`scripts/check-version-parity.py`, ya subsumidos;
   disuelve la clase fail-open del parser textual de superficie anclando el árbol entero) — no solo
   `frontend/**` + Dockerfile/lockfile/workflow (ese era el conjunto pre-§9, de 5 anclas, que
   dejaba fuera los tres guards que `frontend-tests-suite` ejecuta y que ningún otro required
   check cubre). Citar el principio de `design.md` **D1.1** (`detect surface ⊇ suite
   dependency surface`): el detect debe anclar tanto el código de guard que la suite EJECUTA
   como el corpus del que es el único gate designado. `frontend-tests-detect` corre además
   `python3 scripts/check-detect-surface.py frontend` como **paso always-run** antes de decidir
   el skip (§11/D1.1.c): si la suite empezara a ejecutar un guard fuera de `frontend/**` sin
   anclarlo, el job `*-detect` falla y el consolidador reporta fail-closed. La paridad de versión
   (`check-version-parity`, cuyos inputs `VERSION`/`backend/pyproject.toml` no ancla el detector
   de frontend) tiene su gate always-run propio `version-parity.yml` (SEC-2/§11), no queda tras
   el detect de frontend.
2. Fusionar "Entorno e instalación reproducible" y "Verificaciones y diagnóstico" en una
   descripción del job `frontend-tests-suite` que documente las **nueve** señales fusionadas
   (las tres de provenance + `npm ci` + las cinco antiguas de `provenance-contract`/
   `frontend-tests`, contando `npm run test:layout` como señal nueva) y el **único** `npm ci`
   por ejecución (antes había dos jobs, cada uno con su propio `npm ci`).
3. Añadir un requisito nuevo sobre la caché de Playwright: clave **exacta**
   (`playwright-${{ hashFiles('frontend/package-lock.json') }}`), **sin `restore-keys:`** —
   decisión deliberada para no restaurar en silencio binarios de un lockfile distinto (riesgo
   de binario desactualizado) — y que el paso de instalación de Playwright
   (`playwright install --with-deps chromium`) corre **siempre**, con o sin cache hit, porque
   las dependencias de sistema no viven en esa cache.
4. Fusionar "Contrato de identidad y paridad" dentro de la descripción de
   `frontend-tests-suite`: las verificaciones de version parity, extractor de PR y validador
   de provenance pasan a ser tres señales más del mismo job, no un job separado.
5. Preservar sin cambios: "Key files", la prohibición de `paths:` en `on:`, `npm run build`
   fuera del workflow, y "Estado del check" (sigue sin ser check obligatorio, mismo motivo de
   plan de GitHub).

## (c) Texto propuesto, listo para pegar

### Reemplazo de "Disparadores y alcance" (líneas 11-21)

```markdown
### Disparadores y alcance

- WHEN se abre, reabre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL
  ejecutar el workflow `frontend-tests`.
- WHEN una persona inicia una ejecución manual, THE SYSTEM SHALL admitir `workflow_dispatch`.
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
  D1.1/D1.1.d: el detect debe ser un superconjunto de la superficie de dependencias de
  `frontend-tests-suite` — tanto el código de guard que la suite ejecuta como el corpus del
  que es el único gate designado; `scripts/*` se ancla en bloque, superseding los dos scripts
  `.py` nombrados): `frontend/*`, `frontend/devops/Dockerfile`,
  `frontend/package.json`, `frontend/package-lock.json`,
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
```

### Reemplazo de "Entorno e instalación reproducible" + "Verificaciones y diagnóstico" (líneas 23-50)

```markdown
### El job de verificación (`frontend-tests-suite`)

- WHEN la detección concluye que el diff toca el frontend, THE SYSTEM SHALL ejecutar
  `frontend-tests-suite` en `ubuntu-latest`, limitado a 15 minutos, con únicamente
  `contents: read`.
- THE SYSTEM SHALL pinear por SHA de commit cada action utilizada y SHALL impedir que
  `actions/checkout` persista credenciales Git para los pasos posteriores.
- WHEN prepara Node.js, THE SYSTEM SHALL seleccionar Node 22, la versión mayor declarada por
  `frontend/devops/Dockerfile`, y SHALL cachear las descargas de npm usando
  `frontend/package-lock.json` como dependencia de la caché, sin cachear `node_modules`.
- WHEN instala dependencias, THE SYSTEM SHALL ejecutar una **única** vez `npm ci` desde
  `frontend/` por ejecución del job (antes de este change, `provenance-contract` y
  `frontend-tests` eran jobs separados y cada uno instalaba por su cuenta).
- IF `frontend/package.json` y `frontend/package-lock.json` no son coherentes, THEN THE SYSTEM
  SHALL fallar durante la instalación y no ejecutar las verificaciones que dependen de ella.
- THE SYSTEM SHALL fusionar en este job las nueve señales que antes se repartían entre
  `provenance-contract` y `frontend-tests`: version parity (`make check-version-parity`),
  autotest del extractor de PR, autotest del validador del contrato de provenance, `npm ci`,
  contrato de API + disclosure de provenance, build de producción + disclosure de artefactos
  públicos, tests (Vitest node), guarda de desbordamiento a 360px (Vitest browser vía
  Playwright/Chromium), lint (ESLint) y typecheck (TypeScript).
- WHEN una de las señales falla, THE SYSTEM SHALL conservar su resultado (`continue-on-error:
  true` por señal) y continuar con las demás, para que el job publique todas las señales
  disponibles en la misma ejecución en lugar de abortar en la primera roja.
- THE SYSTEM SHALL mantener `npm run build` como parte de la señal de disclosure de artefactos
  públicos únicamente (no como paso de despliegue): los workflows de build y despliegue
  conservan esa responsabilidad para producción.

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
```

### Reemplazo de "Contrato de identidad y paridad" (líneas 57-66)

```markdown
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
```

Sin cambios: "Estado del check" (líneas 52-55) y "Key files" (líneas 68-73).
