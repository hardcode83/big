# Tasks: backend-pyright-tooling

## 1. Dependencia reproducible de desarrollo

- [x] 1.1 Añadir `pyright` con restricción explícita compatible con Python 3.12 al único grupo `[dependency-groups].dev` de `backend/pyproject.toml`, sin moverlo a `[project].dependencies` ni añadir suppressions/configuración permisiva. [R1]
- [x] 1.2 Regenerar `backend/uv.lock` con uv después de cambiar `backend/pyproject.toml` y comprobar que la resolución bloqueada contiene Pyright y sus dependencias. [R1]
- [x] 1.3 Verificar desde `backend` que `uv sync --frozen` termina correctamente y deja el ejecutable disponible en el entorno `.venv`. [R1]
- [x] 1.4 Añadir `nodejs-wheel` (runtime Node como wheel con hash) al grupo `[dependency-groups].dev` y regenerar `backend/uv.lock`, de modo que el binario `node` que usa Pyright quede fijado por el lockfile y no se descargue vía `nodeenv` en tiempo de ejecución. [R1]

## 2. Runtime Docker de desarrollo <!-- panel: PASS 2026-09-01 -->


- [x] 2.1 En `backend/devops/Dockerfile`, instalar `libatomic1` sólo después de `FROM base AS dev`, usando `--no-install-recommends` y eliminando `/var/lib/apt/lists/*` en la misma capa. [R2]
- [x] 2.2 Comprobar que la stage `prod` sigue partiendo de su propio `python:3.12-slim`, ejecuta `uv sync --frozen --no-dev` y no hereda la capa `dev` ni `libatomic1`. [R2]
- [x] 2.3 Construir las stages `dev` y `prod` del backend y verificar en la imagen `dev` que Pyright puede arrancar y en la imagen `prod` que no existe tooling dev ni la dependencia `libatomic1`. [R2]
- [x] 2.4 En la stage `dev`, fijar `ENV PYRIGHT_PYTHON_GLOBAL_NODE=1` para que Pyright use el `node` del lockfile disponible en `/app/.venv/bin` (en el `PATH`) y no descargue Node vía `nodeenv`. [R2]

### Evidencia reproducible de 2.3 / 2.4 / 1.4 (2026-09-01, tras fijar el runtime Node)

- `docker build --target dev -t autohostai-backend:pyright-nodewheel-dev -f backend/devops/Dockerfile backend`: **PASS** (`uv sync --frozen` instala el grupo `dev` incl. `nodejs-wheel` y `pyright`).
- `docker build --target prod -t autohostai-backend:pyright-nodewheel-prod -f backend/devops/Dockerfile backend`: **PASS**.
- Verificación **offline** en la imagen `dev` (`docker run --rm --network none ...`), que prueba que no hay descarga de red del runtime Node:
  - `command -v node` → `/app/.venv/bin/node`; `node --version` → `v24.19.0` (del wheel `nodejs-wheel` fijado en `uv.lock`).
  - `dpkg -s libatomic1` → `Status: install ok installed`.
  - `uv run --no-sync pyright --version` → `pyright 1.1.411`.
  - `uv run --no-sync pyright app/main.py` → arranca y produce resultado, `exit=0` (`0 errors, 0 warnings, 0 informations`) **con la red desactivada** (D4: tooling arrancó).
  - `ls /root/.cache/pyright-python` → `No such file or directory` (no se creó directorio de descarga de `nodeenv`).
- Exclusión en `prod` (`docker run --rm autohostai-backend:pyright-nodewheel-prod ...`): `command -v pyright` → ausente (`127`); `command -v node` → ausente (`127`); `/app/.venv/bin/node` → ausente; `dpkg -s libatomic1` → ausente (`1`). (R2.3.)
- `backend/uv.lock` fija `nodejs-wheel` 24.19.0 y `nodejs-wheel-binaries` 24.19.0 con `sha256` para los wheels `manylinux_2_28_{x86_64,aarch64}` (runtime Node cubierto por el lockfile). (R1.3.)

## 3. Documentación operativa y límites de CI

- [ ] 3.1 Documentar en el spec/documentación canónica que corresponda al archivar (`sdd/specs/backend-tooling.md` y, si procede, `sdd/specs/local-environment.md` o `sdd/specs/ci-backend-tests.md`) el cwd `backend`, `uv sync --frozen`, el preflight y el comando soportado `uv run pyright .`; dejar `uvx pyright` como camino no soportado. [R3, R4]
- [x] 3.2 Verificar que el change no modifica `.github/workflows/`, no crea un workflow nuevo y conserva intactos los comandos existentes de Pytest (Ruff no existe en el proyecto). [R3]
- [x] 3.3 Verificar que el diff no contiene cambios bajo `backend/app/statements/`, `backend/tests/statements/` ni otros ficheros funcionales de `revenue-statements`. [R4]

## 4. Verification

- [x] 4.1 En el entorno Docker de desarrollo, ejecutar desde el directorio `backend` el flujo `uv sync --frozen`, `command -v pyright` y `uv run pyright --version`; conservar la versión y confirmar que no hay error de instalación/runtime. [R1, R2, R4]
- [x] 4.2 Ejecutar desde `backend` `uv run pyright .` y conservar la salida completa y el código de salida. Marcar el tooling como PASS si Pyright arranca y produce su resultado, aunque reporte findings; marcarlo como fallo de tooling si no llega a arrancar por `uv`, ejecutable ausente, launcher o `libatomic.so.1`. [R2, R3, R4]
- [x] 4.3 Registrar el baseline de findings devuelto por la primera ejecución sin corregir tipos, añadir suppressions, relajar la configuración ni modificar código funcional. [R3, R4]
- [x] 4.4 Ejecutar la suite backend existente con `docker compose run --rm backend uv run pytest -n 2` y confirmar que la introducción del tooling no altera Pytest. [R3]
- [x] 4.5 Verificar con `git diff --check` y una revisión de alcance que sólo se modifican `backend/pyproject.toml`, `backend/uv.lock`, `backend/devops/Dockerfile` y la documentación prevista; no se modifica CI ni `revenue-statements`. [R2, R3, R4]

### Evidencia de verificación §4 (2026-09-01)

- **4.1** (imagen `dev`, `WORKDIR /app` = backend): `uv sync --frozen` → `exit 0`; `command -v pyright` → `/app/.venv/bin/pyright`; `uv run pyright --version` → `pyright 1.1.411`. Sin error de instalación/runtime.
- **4.2** `uv run pyright .` → arranca y produce resultado; `exit 1` (findings, no fallo de arranque) ⇒ **tooling PASS** por D4 (no es `command not found`, launcher ni `libatomic.so.1`).
- **4.3** Baseline (sin corregir tipos ni relajar config): **56 errors, 0 warnings, 0 informations** (161 líneas de salida). Findings de tipos preexistentes, fuera de alcance por D6; no se corrigen en este change.
- **4.4** `docker compose -f docker-compose.yml -f docker-compose.worktree.yml run --rm backend uv run pytest -n 2` → **`9083 passed, 41 skipped` en 688.27s, `exit 0`**. La introducción del tooling no altera Pytest.
- **4.5** `git diff --check` → limpio (sin espacios en blanco erróneos ni marcadores de conflicto). Alcance (`git diff --name-only main`): `backend/devops/Dockerfile`, `backend/pyproject.toml`, `backend/uv.lock`, `sdd/project.md`, `sdd/specs/backend-ci.md`; **sin** `.github/workflows/` ni `revenue-statements`.
