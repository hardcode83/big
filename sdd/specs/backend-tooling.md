# Tooling estático del backend

## Purpose

Análisis estático de tipos del backend con Pyright, ejecutable de forma reproducible
desde el propio proyecto (mismo comando en local y en Docker) sin depender de estado
instalado fuera del proyecto ni de descargas de red no verificadas. Cubre cómo se
declara y bloquea la herramienta, cómo arranca dentro del contenedor de desarrollo, el
comando soportado y cómo se interpreta su resultado.

## Requirements

### Herramienta declarada y bloqueada

- Pyright se declara en el único grupo `[dependency-groups].dev` de
  `backend/pyproject.toml` con una restricción de versión explícita compatible con
  Python 3.12 (`pyright>=1.1.390`), nunca en `[project].dependencies`.
- El runtime Node que Pyright necesita se provee con el paquete `nodejs-wheel`
  (`nodejs-wheel>=22.13.0`), también en el grupo `dev`, de modo que el binario `node`
  quede fijado por el lockfile.
- WHEN se ejecuta `uv sync --frozen` desde `backend`, THE SYSTEM SHALL instalar Pyright y
  su runtime Node desde `backend/pyproject.toml` y `backend/uv.lock`, sin usar `uvx` ni
  descargas implícitas.
- `backend/uv.lock` fija con `sha256` tanto Pyright (1.1.411) como `nodejs-wheel` y
  `nodejs-wheel-binaries` (24.19.0, con wheels `manylinux_2_28_{x86_64,aarch64}` entre
  otros). Aunque Pyright declara `nodeenv` como dependencia, esa vía de descarga de red no
  se alcanza: Pyright usa el `nodejs-wheel` importable por defecto.
- IF Pyright ejecuta su análisis, THEN THE SYSTEM SHALL usar el `node` fijado por el
  lockfile en `/app/.venv/bin`, sin descargar Node vía `nodeenv` ni ningún otro canal de
  red no verificado.

### Runtime Docker de desarrollo

- WHEN se construye la stage `dev` de `backend/devops/Dockerfile`, THE SYSTEM SHALL
  instalar `libatomic1` —dependencia nativa del binario Node— con `apt-get`,
  `--no-install-recommends`, eliminando `/var/lib/apt/lists/*` en la misma capa.
- La stage `dev` fija `ENV PYRIGHT_PYTHON_GLOBAL_NODE=1` como salvaguarda explícita para
  usar el `node` del `PATH` (el del lockfile en `/app/.venv/bin`) aunque cambie la
  estrategia por defecto de Pyright.
- THE SYSTEM SHALL mantener Pyright, `nodejs-wheel` y `libatomic1` **fuera** de la imagen
  `prod`: la stage `prod` parte de un `python:3.12-slim` propio y sólo copia del `builder`,
  que ejecuta `uv sync --frozen --no-dev --no-editable`; no hereda la capa `dev`.

### Comando canónico reproducible

- El comando soportado es `uv run pyright .` con directorio de trabajo `backend` (que es
  el `WORKDIR /app` real del servicio Docker y el `working-directory: backend` de CI); su
  forma Docker equivalente es `docker compose run --rm backend uv run pyright .`.
- WHEN se prepara el entorno para el análisis, THE SYSTEM SHALL usar `uv sync --frozen`
  como única preparación de dependencias.
- `uvx pyright` **no** es el camino soportado: descarga fuera del lockfile y no es
  reproducible. El comando reproducible está documentado en `sdd/project.md`.

### Resultado: findings frente a fallo de arranque

- El análisis se considera **ejecutado** sólo cuando el proceso `pyright` ha arrancado y
  devuelve su código de salida normal: cero si no hay findings, distinto de cero si los
  hay.
- WHEN se evalúa el resultado, THE SYSTEM SHALL conservar el código de salida y el informe,
  distinguiendo un fallo real de tipos (proceso arrancado que reporta findings) de un fallo
  de instalación o runtime.
- IF `uv` no resuelve el entorno, el ejecutable falta, el launcher lanza una excepción o
  hay un error de carga como `libatomic.so.1`, THEN THE SYSTEM SHALL clasificarlo como
  **tooling incapaz de arrancar**, no como findings. Un preflight explícito
  (`command -v pyright`, `uv run pyright --version`) debe pasar antes de atribuir el código
  de salida a tipos.
- Los findings de tipos existentes están fuera del alcance de esta capacidad: se miden como
  baseline y su corrección es un cambio aparte, sin suppressions globales ni relajación de
  configuración para forzar un resultado verde.

### Relación con CI

- Esta capacidad **no** introduce un gate obligatorio de Pyright en CI: el comando queda
  documentado y reproducible, y la decisión de convertirlo en check obligatorio es una
  política aparte (ver `sdd/specs/backend-ci.md` §Estado). El workflow
  `.github/workflows/backend-tests.yml` no lo ejecuta.

## Key files

- `backend/pyproject.toml` — Pyright y `nodejs-wheel` en `[dependency-groups].dev`.
- `backend/uv.lock` — resolución bloqueada con hash de Pyright y del runtime Node.
- `backend/devops/Dockerfile` — `libatomic1` y `PYRIGHT_PYTHON_GLOBAL_NODE=1` sólo en la
  stage `dev`; `prod` sin tooling de desarrollo.
- `sdd/project.md` §Commands — comando reproducible soportado y `uvx pyright` como camino
  no soportado.
- `sdd/specs/backend-ci.md` — estado del typecheck respecto a CI (no obligatorio).
