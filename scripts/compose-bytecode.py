#!/usr/bin/env python3
"""Guardia de `ci-runner-workspace-pollution` R5: ningún servicio Python del stack local escribe
bytecode en el árbol del repositorio.

`docker-compose.yml` monta el árbol por bind mount en varios servicios. Cuatro de ellos
(`migrate`, `backend`, `worker`, `beat`) ejecutan Python sobre ese árbol montado, y sin
`PYTHONDONTWRITEBYTECODE` el intérprete escribe `__pycache__/*.pyc` **en el host**, propiedad de
quien corra el contenedor — root, porque ninguno de los cuatro declara `user:`. En la VM de CI ese
árbol es el `_work/` persistente de un agente de GitHub Actions, y un `.pyc` de root ahí hace
fallar `actions/checkout` con `EACCES` **antes de cualquier paso propio** — ver
`sdd/changes/ci-runner-workspace-pollution/proposal.md` §Why para el incidente que lo disparó.

Esta guardia no comprueba esos cuatro nombres: deriva de la composición **resuelta** qué
servicios están en alcance (R5.2), para que un quinto servicio Python con el mismo patrón entre
en rojo sin que nadie tenga que añadirlo aquí.

## Qué cuenta como «en alcance» (dos señales, ambas de la composición resuelta)

1. **Es un servicio Python**: su `build.context` resuelve al mismo directorio que `backend/` en
   la raíz del repositorio. Es la señal que ya existe en `docker-compose.yml` — los cuatro
   servicios Python construyen desde `./backend`; `frontend` construye desde `./frontend`. **No**
   se usa el nombre del servicio ni su `command` (que mencionaría `python`/`uv`/`celery` de forma
   frágil): el contexto de build es la única señal estructural que ata «este servicio es la
   imagen de `backend/`» sin adivinar el lenguaje.
2. **Monta el árbol del repositorio en escritura**: al menos una entrada de `volumes` con
   `type: bind`, sin `read_only`, cuya `source` resuelta cae dentro de la raíz del repositorio.
   Un mount `read_only` queda fuera a propósito: el contenedor no puede escribir ahí, así que no
   puede dejar nada de root — es exactamente el caso de los tres bind mounts de solo lectura que
   `backend` ya tiene hoy (los workflows y `.env.example` que monta para sus propios tests).

**Por qué no `frontend` también**, aunque monta `./frontend:/app` en escritura igual que los
cuatro de arriba: `PYTHONDONTWRITEBYTECODE` no significa nada para un proceso Node. La primera
redacción de esta regla (R5.1) no llevaba el calificador «servicio Python» que R1.1 sí llevaba, y
habría exigido la variable también ahí — decisión corregida el 2026-09-14, antes de escribir esta
guardia (`design.md` D8).

## Limitación conocida, deliberada y sin resolver

La señal (1) de arriba es `build.context`. Un servicio que ejecute Python sobre un bind mount en
escritura del árbol sin construir con `context: ./backend` — una imagen publicada
(`image: python:...`) o un `build:` cuyo `context` por defecto no resuelva a `backend/` — queda
fuera de `in_scope_services` **en silencio**, y esta guardia pasa en verde aunque ese servicio sí
deje `__pycache__` root-owned sobre el árbol. Es el residual que el panel de `/sdd:review` del
change `ci-runner-workspace-pollution` señaló (2026-09-14, lente `qa`), documentado aquí y en
`sdd/specs/local-environment.md` §«Guardia de bytecode» en vez de resuelto: ampliar la señal de
alcance o fallar cerrado ante un servicio Python no reconocido es entrada propia de roadmap, no
de este change.

## La invocación, reutilizada de `scripts/compose-ports.py`

`docker compose config` se invoca **siempre** con `--no-interpolate --no-env-resolution`
(`CONFIG_BASE`), nunca a secas: sin las dos banderas, la salida inlina el `.env` entero —
variables que el compose ni menciona—, que es justo lo que prohíbe `sdd/specs/local-environment.md`.
El entorno del hijo es una lista blanca de un solo nombre (`PATH`), por el mismo motivo que
`compose-ports.py` ya documenta: una lista blanca demasiado estrecha falla en rojo, nunca en
verde.

Contrato: sin argumentos, desde la raíz del repositorio. Código **0** cuando todo servicio en
alcance declara la variable con valor no vacío (nombrando y contando lo inspeccionado); distinto
de cero en cualquier otro caso, incluida cualquier rotura de la cadena hacia Compose.
"""

import json
import os
import subprocess
import sys
from dataclasses import dataclass

COMPOSE = ("docker", "compose")
CONFIG_BASE = ("config", "--no-interpolate", "--no-env-resolution", "--format", "json")
VAR = "PYTHONDONTWRITEBYTECODE"
STDERR_LIMIT = 200
MIN_COMPOSE = "2.35.0"  # mismo suelo que compose-ports.py: --no-env-resolution llegó en v2.35.0.


class GuardError(Exception):
    """La cadena se rompió o el dato no tiene la forma esperada: rojo, nunca verde."""


@dataclass(frozen=True)
class Violation:
    service: str
    detail: str


def escape(value: str) -> str:
    """Saneo para pantalla, inyectivo — mismo criterio que `compose-ports.py`."""
    pieces = []
    for char in value:
        if char == "\\":
            pieces.append("\\\\")
        elif char.isprintable():
            pieces.append(char)
        elif ord(char) < 0x100:
            pieces.append(f"\\x{ord(char):02x}")
        else:
            pieces.append(f"\\u{ord(char):04x}")
    return "".join(pieces)


def clean_env() -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", "")}


def summarize(stderr: str) -> str:
    first = next((line for line in stderr.splitlines() if line.strip()), "sin mensaje de error")
    return escape(first[:STDERR_LIMIT].strip())


def capture(command: list[str]) -> str:
    """Invoca un comando ajeno y devuelve su `stdout`, o aborta nombrando por qué no lo hay.

    Lista de argumentos, nunca por shell. El estado de salida se comprueba aparte del contenido
    y antes de mirarlo. `stdout` no se relata nunca en el error; de `stderr` solo su primera
    línea, saneada y acotada — seguro por `CONFIG_BASE` y no por confianza: sin interpolación no
    hay valor del `.env` que esa línea pueda citar.
    """
    try:
        completed = subprocess.run(command, capture_output=True, text=True, env=clean_env())
    except FileNotFoundError as exc:
        raise GuardError(f"`{escape(command[0])}` no está disponible en el `PATH`: {escape(str(exc))}") from exc
    if completed.returncode != 0:
        raise GuardError(
            f"el paso `{escape(' '.join(command))}` terminó con código {completed.returncode}: "
            f"{summarize(completed.stderr)}. Si dice `unknown flag`, tu Docker Compose es "
            f"anterior al mínimo del proyecto ({MIN_COMPOSE})."
        )
    return completed.stdout


def parse_model(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError as exc:
        raise GuardError(
            f"la salida del modelo de Compose no es JSON válido, así que no describe ninguna "
            f"postura: {escape(str(exc))}"
        ) from exc


def services_of(model: object) -> dict[str, object]:
    if not isinstance(model, dict):
        raise GuardError(f"el modelo de Compose no es un objeto, sino {type(model).__name__}")
    if "services" not in model:
        raise GuardError(
            "el modelo de Compose no trae la clave `services`: darlo por vacío daría verde sin "
            "haber comprobado nada"
        )
    services = model["services"]
    if not isinstance(services, dict):
        raise GuardError(f"`services` del modelo no es un objeto, sino {type(services).__name__}")
    return services


def under_root(path: object, root: str) -> bool:
    """`path` (como lo trae el modelo) cae dentro de `root`, ambos ya absolutos y reales."""
    if not isinstance(path, str) or not path:
        return False
    try:
        resolved = os.path.realpath(path)
    except OSError:
        return False
    return resolved == root or resolved.startswith(root + os.sep)


def is_python_service(model: object, backend_dir: str) -> bool:
    """La señal estructural de R5.2: el `build.context` resuelto es el mismo `backend/`.

    Un servicio sin `build` (imagen de terceros: `postgres`, `redis`) no puede ser esto — el
    contexto de build es precisamente lo que ata la imagen a `backend/`, y no hay uno que
    inspeccionar.
    """
    if not isinstance(model, dict):
        return False
    build = model.get("build")
    if not isinstance(build, dict):
        return False
    context = build.get("context")
    if not isinstance(context, str) or not context:
        return False
    try:
        return os.path.realpath(context) == backend_dir
    except OSError:
        return False


def writable_tree_bind(model: object, root: str) -> bool:
    """Al menos un `volumes` de tipo `bind`, sin `read_only`, cuya fuente cae bajo `root`."""
    if not isinstance(model, dict):
        return False
    volumes = model.get("volumes")
    if not isinstance(volumes, list):
        return False
    for entry in volumes:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "bind":
            continue
        if entry.get("read_only"):
            continue
        if under_root(entry.get("source"), root):
            return True
    return False


def declares_var(model: object) -> bool:
    """`PYTHONDONTWRITEBYTECODE` presente con valor no vacío — lo único que CPython exige."""
    if not isinstance(model, dict):
        return False
    environment = model.get("environment")
    if not isinstance(environment, dict):
        return False
    value = environment.get(VAR)
    return isinstance(value, str) and value != ""


def in_scope_services(model: object, root: str) -> dict[str, object]:
    """Los servicios Python con bind mount en escritura del árbol — la definición de R5.2."""
    backend_dir = os.path.realpath(os.path.join(root, "backend"))
    services = services_of(model)
    return {
        name: svc
        for name, svc in services.items()
        if is_python_service(svc, backend_dir) and writable_tree_bind(svc, root)
    }


def violations(scoped: dict[str, object]) -> list[Violation]:
    return [Violation(name, f"{VAR} no declarada o vacía") for name, svc in sorted(scoped.items()) if not declares_var(svc)]


def render(found: list[Violation]) -> str:
    blocks = [
        "\n".join([f"servicio: {escape(v.service)}", f"motivo: {escape(v.detail)}"])
        for v in sorted(found, key=lambda v: v.service)
    ]
    return "\n\n".join([*blocks, f"infracciones: {len(found)}"]) + "\n"


def summary(scoped: dict[str, object]) -> str:
    names = sorted(scoped)
    lines = [f"servicios Python en alcance: {len(names)}"]
    lines.extend(f"servicio: {escape(name)}" for name in names)
    lines.append(f"veredicto: los {len(names)} declaran {VAR} con valor no vacío")
    return "\n".join(lines) + "\n"


def main() -> int:
    root = os.path.realpath(os.getcwd())
    try:
        model = parse_model(capture([*COMPOSE, *CONFIG_BASE]))
        scoped = in_scope_services(model, root)
    except GuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    found = violations(scoped)
    if found:
        print(render(found), end="")
        return 1

    print(summary(scoped), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
