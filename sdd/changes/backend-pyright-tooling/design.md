# Design: backend-pyright-tooling

## Context

El backend construye su imagen de desarrollo desde `backend/devops/Dockerfile`, con
`uv sync --frozen` en la stage `dev`; `docker-compose.yml` monta `./backend` en `/app`
y comparte el volumen `/app/.venv`. `backend/pyproject.toml` sólo tiene actualmente
pytest y sus plugins en el grupo `dev`, por lo que `uv run pyright ...` no encuentra el
comando. Además, el paquete PyPI `pyright` es un wrapper que **no distribuye** el runtime
Node: usa `node` del `PATH` si existe y, si no, lo descarga en la primera ejecución con
`nodeenv` (una descarga de red no cubierta por el lockfile). Ese binario Node prebuilt
necesita `libatomic1`, que la imagen `python:3.12-slim` no incluye.

El workflow `.github/workflows/backend-tests.yml` instala las dependencias desde
`backend` con `uv sync --frozen` y ejecuta la suite con `uv run pytest`; sus checks
obligatorios son de tests, migraciones y wiring de provenance. No hay un gate estático
obligatorio existente. `sdd/steering/backend.md` exige respetar la separación por
capas, `sdd/steering/backend-architecture.md` no introduce una herramienta concreta,
`sdd/steering/infra.md` exige configuración versionada y `sdd/steering/testing.md`
obliga a conservar la suite y sus convenciones.

## Decisions

### D1 — Pyright y su runtime Node como dependencias de desarrollo de uv

**Chosen:** añadir al único grupo `[dependency-groups].dev` de `backend/pyproject.toml`
tanto una restricción de Pyright como el paquete `nodejs-wheel` (que provee el binario
`node` como wheel con hash), y regenerar `backend/uv.lock` con uv. La stage `dev` instala
ese grupo mediante `uv sync --frozen`, así que Pyright y `node` quedan disponibles para
`uv run`, con `node` en `/app/.venv/bin` (dentro del `PATH`). Pyright usa el paquete
`nodejs-wheel` directamente cuando está instalado (su estrategia por defecto), por lo que
no descarga Node con `nodeenv`; además, la stage `dev` fija `PYRIGHT_PYTHON_GLOBAL_NODE=1`
como salvaguarda explícita para usar el `node` del `PATH` si esa estrategia cambiara.

Rejected: usar `uvx pyright` — descarga fuera del lockfile y no es reproducible.

Rejected: declarar Pyright en `[project].dependencies` — contaminaría la imagen `prod`,
que ejecuta `uv sync --frozen --no-dev` y no necesita tooling de análisis.

Rejected: dejar que Pyright descargue Node con `nodeenv` en la primera ejecución — es una
descarga de red no fijada por el lockfile ni verificada por hash, ejecutada dentro del
contenedor dev sobre el árbol fuente montado; contradice la reproducibilidad que persigue
R1. Fijar el runtime Node vía `nodejs-wheel` lo cierra: `uv.lock` fija el binario con
`sha256` para `manylinux_2_28` (x86_64 y aarch64).

La versión concreta de ambos será una restricción compatible con Python 3.12 y quedará
fijada por el lockfile; no se fijará una versión en una imagen ni en un workflow separado.

### D2 — `libatomic1` sólo en la imagen de desarrollo

**Chosen:** instalar `libatomic1` en una capa de la stage `dev`, después de
`FROM base AS dev`, usando `apt-get update` y `apt-get install --no-install-recommends`,
y eliminar `/var/lib/apt/lists/*` en la misma instrucción. Es la dependencia nativa que
el binario Node del wheel `nodejs-wheel` (D1) necesita para cargar. La stage `prod` parte
de un nuevo `python:3.12-slim` y no hereda la stage `dev`, por lo que no incorpora la
librería ni el coste del tooling.

Rejected: añadir `libatomic1` al stage `base` — lo heredarían `builder` y `prod`, aunque
sólo lo necesita el runtime de análisis de desarrollo.

Rejected: ejecutar `uvx` con una imagen auxiliar — mantiene el problema de reproducibilidad
y deja el runtime fuera del entorno declarado por el proyecto.

### D3 — Comando y directorio de análisis

**Chosen:** el contrato operativo será `uv run pyright .` desde el directorio `backend`,
que es el `WORKDIR /app` real del servicio Docker y el `working-directory: backend` que
usa CI. La forma Docker equivalente será `docker compose run --rm backend uv run pyright .`.
El `.` representa el árbol backend dentro del contenedor; no se añadirá un montaje
artificial de la raíz del monorepo sólo para conservar un path relativo que no existe
dentro de `/app`.

Rejected: montar la raíz completa del repositorio en el backend y mantener
`uv run pyright backend/` — cambia el aislamiento actual del servicio y amplía el scope
de un arreglo de tooling.

La discrepancia de path se tratará como parte de la documentación del comando soportado:
la invocación reproducible dentro del proyecto es la anterior, con cwd `backend`.
Esto no modifica `revenue-statements` ni sus documentos.

### D4 — Findings frente a fallo de arranque

**Chosen:** considerar “ejecutado” sólo cuando el proceso `pyright` ha arrancado y
devuelve su código de salida normal (cero si no hay findings; distinto de cero si hay
findings). La salida se conserva íntegra y se etiqueta con el comando, cwd y versión
resuelta desde `uv.lock`.

Un error de `uv` al resolver/crear el entorno, `command not found`, una excepción del
launcher o un error de carga como `libatomic.so.1` se clasifica como **tooling unable to
start**: no se interpreta como findings y no permite cerrar §11.2. La verificación
separará ambos casos con un preflight explícito (`command -v pyright`, `pyright --version`)
y después la ejecución del análisis; el preflight debe pasar antes de atribuir el código
de salida a tipos.

Rejected: convertir cualquier salida no cero en “findings” — ocultaría fallos de
instalación/runtime y repetiría el blocker actual bajo otra etiqueta.

### D5 — CI existente, sin nuevo gate obligatorio

**Chosen:** no modificar `.github/workflows/backend-tests.yml` ni crear un workflow nuevo.
La arquitectura CI actual no exige Pyright/Ruff como checks obligatorios; imponerlo aquí
sería una expansión de política no justificada por `steering/testing.md` ni por el
workflow existente. El mismo comando queda documentado y es ejecutable en CI dentro del
job existente si una futura política lo adopta, pero este change no cambia sus checks ni
su código de salida.

Rejected: añadir un paso bloqueante de Pyright al job `backend-tests-suite` — convertiría
un supuesto de la proposal en una nueva política de merge sin decisión independiente.

Rejected: añadir un paso `continue-on-error` que parezca un gate — ejecutaría análisis sin
autoridad clara y mezclaría evidencia informativa con el resultado obligatorio del job.

### D6 — Findings existentes fuera de alcance

**Chosen:** el primer análisis completo sirve para demostrar que Pyright arranca y para
medir el baseline. Sus errores de tipos se registran como resultado de verificación, no
se corrigen ni se convierten en tareas de este change. Cualquier reducción del baseline
se abrirá como change separado con su propio scope.

Rejected: añadir suppressions globales, relajar la configuración o corregir módulos de
negocio para forzar un resultado verde — falsearía la línea base y convertiría tooling
en refactor funcional.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dependencias backend | `backend/pyproject.toml`, `backend/uv.lock` | Pyright y `nodejs-wheel` (runtime Node) en `[dependency-groups].dev`; resolución bloqueada con uv (Node fijado por hash). |
| Imagen de desarrollo | `backend/devops/Dockerfile` | Instalar `libatomic1` sólo en `dev`; limpiar índices apt; `ENV PYRIGHT_PYTHON_GLOBAL_NODE=1` para usar el `node` del lockfile. |
| Documentación SDD | `sdd/specs/backend-tooling.md` *(al archivar)*, `sdd/specs/local-environment.md` y/o `sdd/specs/ci-backend-tests.md` según el spec canónico existente | Registrar comando, cwd, preflight y clasificación de resultados. |
| CI | Ninguno | Se conserva `.github/workflows/backend-tests.yml` sin nuevo gate obligatorio. |

## Data & interfaces

No hay cambios de API, base de datos, migraciones, variables de entorno ni interfaces
de aplicación. El único contrato nuevo es operativo:

```text
cd backend
uv sync --frozen
command -v pyright
uv run pyright --version
uv run pyright .
```

En Docker se ejecuta el mismo flujo con `docker compose run --rm backend ...`. La salida
de `--version` y la salida completa del análisis constituyen evidencia separada. Un
fallo antes de producir la versión o antes de iniciar el análisis es un fallo de tooling;
un proceso iniciado que reporta archivos y tipos es un resultado de Pyright, aunque tenga
findings y código de salida distinto de cero.

## Risks & mitigations

- **El primer análisis puede revelar muchos findings.** Se conservará el baseline y se
  marcará como fuera de scope; no se cambiarán reglas para ocultarlo.
- **La dependencia nativa puede aumentar la imagen dev.** `libatomic1` y el binario Node
  (`nodejs-wheel`) se limitan a la stage `dev`, usan `--no-install-recommends` / el grupo
  `dev`, y limpian apt; prod permanece independiente.
- **Descarga de un runtime Node no fijado (supply-chain).** El wrapper `pyright` de PyPI
  descargaría Node con `nodeenv` en la primera ejecución si no hubiera `node` en el `PATH`
  — código de terceros sin hash, ejecutado en el contenedor dev sobre el árbol montado.
  Se cierra fijando `nodejs-wheel` en `uv.lock` (Node con `sha256`) y forzando
  `PYRIGHT_PYTHON_GLOBAL_NODE=1`; verificado ejecutando el análisis con la red desactivada.
- **Divergencia entre local y CI.** Ambos usan `uv sync --frozen`, el mismo lockfile y cwd
  `backend`; CI no se modifica hasta que exista una decisión explícita de hacerlo gate.
- **Confusión entre path y entorno.** La documentación fija `/app` como backend root en
  Compose y `working-directory: backend` en CI; no se usa un montaje adicional del repo.
- **Regresión del workflow existente.** No se cambia su suite Pytest, Ruff implícito,
  migraciones, wiring ni sus checks publicados.

## Open questions

Ninguna para pasar a tareas. La eventual corrección de findings de tipos y la decisión
de convertir Pyright en check obligatorio de CI quedan explícitamente fuera de este
change y requieren changes/decisiones separados.

