# Paridad de versión canónica — comprobada en cada Pull Request

## Purpose

El workflow `.github/workflows/version-parity.yml` comprueba, en **cada** Pull Request y en
cada push a `main`, que las tres declaraciones de versión del repositorio coinciden. Es un
check independiente de `frontend-tests`, deliberadamente **always-run** (sin `paths:` ni puerta
de área), porque sus inputs (`VERSION`, `backend/pyproject.toml`) no los cubre ninguna otra
puerta y una divergencia de versión no puede llegar a `main`.

`frontend-tests` pasó a ser condicional por área en el change `ci-pr-gates-optimization`
(`frontend-tests-detect`). Antes de ese change, `make check-version-parity` corría siempre
dentro de `frontend-tests`, pero ahora —al saltarse la suite cuando el diff no toca el
frontend— un PR que subiera la versión solo en `VERSION` o en `backend/pyproject.toml` quedaría
sin verificar hasta `deploy-dev`, que la hornearía en `org.opencontainers.image.version` y
`NEXT_PUBLIC_APP_VERSION`. Este gate existe para cerrar esa ventana.

## Requirements

- WHEN se abre, reabre o actualiza un Pull Request, o se hace push a `main`, THE SYSTEM SHALL
  ejecutar `make check-version-parity` y reportar el resultado en el check `version-parity`.
- THE SYSTEM SHALL conseguirlo **sin `paths:` en `on:`** y **sin puerta de área**: el punto
  entero es correr siempre, sobre cualquier diff.
- THE SYSTEM SHALL comparar las tres fuentes `VERSION`, `backend/pyproject.toml`
  (`[project].version`) y `frontend/package.json` (`.version`), y fallar en rojo si no son
  idénticas.
- THE SYSTEM SHALL ejecutarse con el `python3` del runner (la guardia es stdlib pura: `json`,
  `tomllib`, `pathlib`) — **sin** `uv`, servicios ni secrets.
- THE SYSTEM SHALL mantener la copia de `check-version-parity` dentro de `frontend-tests-suite`
  como comprobación redundante (belt-and-suspenders), igual que `api:check` vive en la suite y
  en `frontend-api-contract.yml`.
- WHILE el repositorio no disponga de protección de rama compatible, THE SYSTEM SHALL
  ejecutar y reportar `version-parity` sin configurarlo como check obligatorio para fusionar —
  mismo motivo de plan de GitHub que el resto de workflows (`specs/backend-ci.md` §Estado).
- El nombre del JOB `version-parity` es el contexto marcable como required; no se renombra sin
  romper la selección de required checks.

## Key files

- `.github/workflows/version-parity.yml`.
- `scripts/check-version-parity.py` — guard stdlib puro que compara las tres fuentes.
- `VERSION`, `backend/pyproject.toml`, `frontend/package.json` — las tres fuentes
  comparadas.