# Draft de spec — `sdd/specs/version-parity.md` (crear)

> Borrador listo para pegar. Lo aplica **`/sdd:archive`** a `sdd/specs/`; `/sdd:run` **no** escribe specs vivas.
> Origen: `ci-pr-gates-optimization`, §11 (SEC-2). Gate nuevo `.github/workflows/version-parity.yml`.

## (a) Estado actual del spec

**No existe.** No hay `sdd/specs/version-parity.md`. Antes de `ci-pr-gates-optimization`, la
comprobación de paridad de versión corría **siempre** dentro de `frontend-tests` (job
`provenance-contract`, señal `version_parity`), sin spec propia. Este change la extrae a un gate
always-run independiente y necesita registrarla como capacidad observable.

## (b) Por qué

`frontend-tests` pasó a ser condicional por área (`frontend-tests-detect`). `make
check-version-parity` (`scripts/check-version-parity.py`) compara la versión de **tres** fuentes
—`VERSION`, `backend/pyproject.toml` (`[project].version`) y `frontend/package.json`
(`.version`)— y era la **única** invocación de esa comprobación en todo CI. Dos de esas fuentes
(`VERSION`, `backend/pyproject.toml`) no las ancla `frontend-tests-detect` (anclarlas arrastraría
la suite de frontend a cada bump de dependencia del backend, contra R7) ni ningún otro gate de
PR. Gatearla tras el detector de frontend la convertía en un **fail-open**: un PR que subiera la
versión solo en `VERSION` o solo en `backend/pyproject.toml`, sin tocar `frontend/**`, recibía un
`**OMITIDA**` verde con la paridad rota, que `deploy-dev` luego horneaba en
`org.opencontainers.image.version` y `NEXT_PUBLIC_APP_VERSION` (design `ci-pr-gates-optimization`
D1.1 SEC-2, proposal R1.8).

## (c) Texto propuesto (nuevo fichero `sdd/specs/version-parity.md`)

# version-parity — paridad de versión canónica, comprobada en cada PR

El workflow `.github/workflows/version-parity.yml` comprueba, en **cada** Pull Request y en cada
push a `main`, que las tres declaraciones de versión del repo coinciden. Es un check independiente
de `frontend-tests`, deliberadamente **always-run** (sin `paths:` ni puerta de área), porque sus
inputs (`VERSION`, `backend/pyproject.toml`) no los cubre ninguna otra puerta y una divergencia de
versión no puede llegar a `main`.

- WHEN se abre/reabre/actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL ejecutar
  `make check-version-parity` y reportar el resultado en el check `version-parity`.
- THE SYSTEM SHALL conseguirlo **sin `paths:` en `on:`** y **sin puerta de área**: el punto entero
  es correr siempre, sobre cualquier diff.
- THE SYSTEM SHALL comparar las tres fuentes `VERSION`, `backend/pyproject.toml` (`[project].version`)
  y `frontend/package.json` (`.version`), y fallar en rojo si no son idénticas.
- THE SYSTEM SHALL ejecutarse con el `python3` del runner (la guardia es stdlib pura: `json`,
  `tomllib`, `pathlib`) — **sin** `uv`, servicios ni secrets.
- THE SYSTEM SHALL mantener la copia de `check-version-parity` dentro de `frontend-tests-suite`
  como comprobación redundante (belt-and-suspenders), igual que `api:check` vive en la suite y en
  `frontend-api-contract.yml`.
- El nombre del JOB `version-parity` es el contexto marcable como required; no se renombra sin
  romper la selección de required checks.
