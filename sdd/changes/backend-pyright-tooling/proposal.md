# Proposal: backend-pyright-tooling

## Why

El backend declara y ejecuta sus dependencias mediante `uv`, pero el grupo `dev` no
incluye Pyright. Por eso el comando del gate `uv run pyright backend/` falla antes de
analizar el código. Incluso usando `uvx pyright`, el runtime Node empaquetado por Pyright
no puede arrancar en la imagen actual porque falta `libatomic.so.1`.

Este change resuelve únicamente la reproducibilidad del tooling estático global del
backend para desbloquear `revenue-statements` §11.2. No cambia lógica funcional ni toca
el módulo `revenue-statements`.

## What changes

El entorno Docker de desarrollo del backend tendrá Pyright declarado como dependencia
de desarrollo, su lockfile actualizado y la librería de sistema mínima necesaria para
ejecutarlo. El workflow de backend documentará y ejecutará el mismo comando canónico
que el entorno local, de forma que el gate sea reproducible y no dependa de `uvx` ni de
estado instalado fuera del proyecto.

## Requirements

### R1 — Pyright declarado y bloqueado

**As a** mantenedor del backend, **I want** Pyright declarado en el grupo de dependencias
de desarrollo y fijado en `uv.lock`, **so that** todas las ejecuciones usen una versión
resoluble y reproducible.

Acceptance criteria:

1. WHEN se ejecuta `uv sync --frozen` desde `backend`, THE SYSTEM SHALL instalar Pyright
   desde `backend/pyproject.toml` y `backend/uv.lock` sin usar `uvx` ni descargas
   implícitas del comando de análisis.
2. WHEN se inspecciona el grupo `dev`, THE SYSTEM SHALL encontrar una restricción de
   versión explícita para Pyright compatible con Python 3.12.
3. WHEN Pyright ejecuta su análisis, THE SYSTEM SHALL usar un runtime Node provisto y
   fijado por `backend/uv.lock` (con hash), sin descargarlo en tiempo de ejecución vía
   `nodeenv` ni ningún otro canal de red no verificado.

### R2 — Runtime Docker suficiente

**As a** operador del entorno Docker, **I want** la imagen `dev` del backend con la
dependencia nativa requerida por el runtime de Pyright, **so that** el analizador pueda
arrancar dentro del contenedor.

Acceptance criteria:

1. WHEN se construye la stage `dev` de `backend/devops/Dockerfile`, THE SYSTEM SHALL
   instalar `libatomic1` con el gestor de paquetes de la imagen y limpiar los índices
   para no conservar cachés innecesarias.
2. WHEN se ejecuta `uv run pyright .` desde el directorio `backend` (o su forma
   equivalente `docker compose run --rm backend uv run pyright .`, con cwd `/app` =
   backend root, per D3), THE SYSTEM SHALL iniciar Pyright y producir un resultado de
   análisis, sin fallar por herramienta ausente ni por `libatomic.so.1`.
3. THE SYSTEM SHALL mantener la dependencia de Pyright y `libatomic1` fuera de la
   imagen `prod` salvo que una necesidad existente del runtime lo exija.

### R3 — Comando canónico reproducible (local/Docker), preparado para CI

**As a** mantenedor del repositorio, **I want** un único comando de Pyright reproducible
que la verificación local y el entorno Docker compartan, **so that** exista evidencia
comparable y el comando quede listo para una futura decisión de gate en CI.

Este change persigue la reproducibilidad local/Docker del comando; **no** introduce un
nuevo gate obligatorio de Pyright en CI. Convertir el comando en check de CI es una
decisión de política aparte (per D5).

Acceptance criteria:

1. WHEN se ejecuta la verificación estática local o en Docker, THE SYSTEM SHALL usar la
   misma invocación canónica `uv run pyright .` (cwd `backend`) con `uv sync --frozen`
   como única preparación de dependencias, sin depender de `uvx` ni de estado instalado
   fuera del proyecto. THE SYSTEM SHALL dejar `.github/workflows/backend-tests.yml`
   inalterado: este change no añade, ni obligatorio ni informativo, un paso de Pyright a
   CI (per D5).
2. WHEN el comando termina, THE SYSTEM SHALL conservar el código de salida y el informe
   de Pyright, distinguiendo un fallo real de tipos de un fallo de instalación o runtime.
3. THE SYSTEM SHALL conservar sin cambios los comandos y la cobertura existentes de
   Pytest, salvo el cableado mínimo necesario para compartir la preparación del entorno.

### R4 — Documentación y no regresión de alcance

**As a** desarrollador que retoma un worktree, **I want** una instrucción única para
ejecutar el tooling backend, **so that** no tenga que recurrir a mecanismos temporales.

Acceptance criteria:

1. THE SYSTEM SHALL documentar el comando reproducible de Pyright desde el proyecto
   (`uv run pyright .` con cwd `backend`), incluyendo que `uvx pyright` no es el camino
   soportado. (Ruff no existe en el proyecto y queda fuera de este change.)
2. WHEN se revisa el diff del change, THE SYSTEM SHALL no contener modificaciones bajo
   `backend/app/statements/`, `backend/tests/statements/` ni ningún otro código funcional
   de `revenue-statements`.

## Out of scope

- Corregir findings de tipos existentes en el backend; esos findings se medirán y se
  decidirá su tratamiento con la evidencia del primer gate reproducible.
- Cambiar reglas funcionales, entidades, API, migraciones o dependencias de
  `revenue-statements`.
- Sustituir Pyright por MyPy, Ruff o un LSP distinto.
- Hacer que la imagen `prod` ejecute tooling de desarrollo.
- Resolver otros problemas cross-cutting del contenedor o del pipeline que no sean
  necesarios para arrancar Pyright.

## Affected specs

- `sdd/specs/backend-tooling.md` *(no existe aún — se creará al archivar)*.
- `sdd/specs/local-environment.md` (comando soportado y dependencia del entorno Docker).
- `sdd/specs/ci-backend-tests.md` (gate reproducible de calidad estática, si la spec
  existente es la que gobierna el workflow).

