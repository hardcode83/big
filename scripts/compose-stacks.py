#!/usr/bin/env python3
"""Diagnóstico de stacks de Compose vivos en la máquina y su procedencia.

Entrada del roadmap: `compose-stacks-diagnostic`. Cruza `docker compose ls -a --format json`
contra `git worktree list --porcelain`, ruta contra ruta, y marca qué proyectos son
**huérfanos** (su directorio de origen está bajo el árbol del repositorio pero ese worktree
ya no está registrado en git). Informa; no actúa.

Lista negra — prohibido en este script, y no es cosmética:

- `docker inspect` sin `--format`: su salida por defecto incluye `.Config.Env`. Sin excepción:
  aquí no hay bandera que acote nada.
- `docker compose config` **sin `--no-interpolate --no-env-resolution`**: en su forma desnuda
  **resuelve e imprime los valores del `.env`** (medido sobre el stack vivo con `JWT_SECRET_KEY`,
  `POSTGRES_PASSWORD` y `ENCRYPTION_KEY` dentro). Acotado por **forma** y no por sujeto en el
  change `compose-ports-guard` (2026-08-18), cuando `scripts/compose-ports.py` necesitó `config`
  como única fuente correcta: con las dos banderas la salida no contiene ningún valor del `.env`
  (medido), y una lista de banderas es comprobable, mientras que «prohibido salvo para este
  script» habría sido una excepción nominal que el siguiente script pediría también. **Este**
  script sigue sin necesitarlo en ninguna forma: hace su trabajo con `docker compose ls`.
- `docker ps --format '{{.Labels}}'` y cualquier atribución por etiquetas de contenedor:
  cualquier contenedor de la máquina las pone con `docker run --label`.
- Cualquier volcado de salida completa de un comando ajeno.

Las dos únicas fuentes son `git worktree list --porcelain` y `docker compose ls -a --format
json`, invocadas una vez cada una con lista de argumentos y nunca por shell.
"""

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


# Las dos únicas fuentes, una invocación cada una. Lista de argumentos, nunca por shell.
WORKTREE_COMMAND = ["git", "worktree", "list", "--porcelain"]
# `-a` incluye los proyectos parados: un huérfano parado retiene exactamente el mismo disco
# (volúmenes e imágenes) que uno corriendo, que es la motivación entera del diagnóstico.
PROJECTS_COMMAND = ["docker", "compose", "ls", "-a", "--format", "json"]

PROJECT_KEYS = ("Name", "Status", "ConfigFiles")

VIVO = "vivo"
HUERFANO = "huérfano"
AJENO = "ajeno"
INDETERMINADO = "indeterminado"


class DiagnosticError(Exception):
    """El dato no se pudo obtener o no tiene la forma esperada: se aborta en voz alta."""


def parse_worktrees(text: str) -> tuple[Path, dict[Path, str | None]]:
    """Parsea `git worktree list --porcelain` y devuelve `(raíz principal, raíces)`.

    Las raíces salen resueltas y mapeadas a su rama, que solo sirve para atribuir en
    pantalla. Un registro que no encaje aborta: una raíz inventada marcaría huérfanos
    falsos, y con la raíz principal vacía la pertenencia al árbol se vuelve universal.
    """
    blocks = [block for block in text.split("\n\n") if block.strip()]
    if not blocks:
        raise DiagnosticError(
            "`git worktree list --porcelain` no devolvió ningún registro: sin la raíz del "
            "repositorio no hay árbol contra el que comparar"
        )
    roots: dict[Path, str | None] = {}
    main_root: Path | None = None
    for block in blocks:
        raw_path: str | None = None
        branch: str | None = None
        is_bare = False
        for line in block.split("\n"):
            if line.startswith("worktree "):
                raw_path = line[len("worktree ") :]
            elif line.startswith("branch refs/heads/"):
                branch = line[len("branch refs/heads/") :]
            elif line == "bare":
                is_bare = True
            # `HEAD`, `locked`, `prunable`, `detached` y las desconocidas no dicen nada
            # sobre la ruta, que es lo único con lo que se clasifica.
        if raw_path is None:
            raise DiagnosticError(
                "registro de `git worktree list --porcelain` sin línea `worktree `: "
                f"{block!r}"
            )
        if not raw_path.startswith("/"):
            raise DiagnosticError(
                f"`git worktree list --porcelain` dio una ruta no absoluta: {raw_path!r}"
            )
        if main_root is None and is_bare:
            raise DiagnosticError(
                "el repositorio es `bare`: no hay árbol de trabajo contra el que comparar"
            )
        root = Path(raw_path).resolve()
        if main_root is None:
            main_root = root
        roots[root] = branch
    assert main_root is not None
    return main_root, roots


def parse_projects(json_text: str) -> list[dict[str, str]]:
    """Parsea `docker compose ls -a --format json`: lista de objetos con las tres claves.

    Cualquier otra forma es un error, nunca «ningún stack»: una lista vacía es un
    inventario vacío legítimo y se distingue del fallo por el código de salida.
    """
    try:
        payload = json.loads(json_text)
    except ValueError as exc:
        raise DiagnosticError(
            f"la salida de `docker compose ls -a --format json` no es JSON válido: {exc}"
        ) from exc
    if not isinstance(payload, list):
        raise DiagnosticError(
            "`docker compose ls -a --format json` no devolvió una lista, sino "
            f"{type(payload).__name__}"
        )
    projects: list[dict[str, str]] = []
    for entry in payload:
        if not isinstance(entry, dict):
            raise DiagnosticError(
                f"`docker compose ls` devolvió un elemento que no es un objeto: {entry!r}"
            )
        missing = [key for key in PROJECT_KEYS if not isinstance(entry.get(key), str)]
        if missing:
            raise DiagnosticError(
                "a un proyecto de `docker compose ls` le faltan claves de texto "
                f"{missing}: {entry!r}"
            )
        projects.append({key: entry[key] for key in PROJECT_KEYS})
    return projects


def project_dir(config_files: str) -> tuple[Path | None, str | None]:
    """Devuelve `(directorio de origen, motivo de ambigüedad)`; exactamente uno es `None`.

    Compose define el directorio del proyecto como el del primer fichero de configuración
    cuando nadie pasa `--project-directory`, y el `Makefile` nunca lo pasa. El campo llega
    unido por comas y una ruta puede contener una coma: esa ambigüedad vive en el lado de
    Docker y aquí se **detecta** exigiendo que todos los fragmentos sean absolutos, nunca se
    adivina reconstruyendo con lo que exista en disco.
    """
    if not config_files:
        return None, "`ConfigFiles` viene vacío: no hay directorio de origen que atribuir"
    fragments = config_files.split(",")
    if not all(fragment.startswith("/") for fragment in fragments):
        return None, (
            "`ConfigFiles` no se puede partir sin ambigüedad —algún fragmento no es una ruta "
            f"absoluta, probablemente por una coma dentro de una ruta—: {config_files!r}"
        )
    # Un NUL no puede formar parte de una ruta y `Path.resolve()` lo convierte en un
    # `ValueError` sin capturar: se detecta aquí para que salga por el camino de ambigüedad
    # y no como traceback. La CLI de Docker no puede colarlo, pero la Engine API sí.
    if any("\x00" in fragment for fragment in fragments):
        return None, (
            "`ConfigFiles` contiene un byte NUL, que no puede formar parte de una ruta: "
            f"{config_files!r}"
        )
    # `.parent` antes de `.resolve()`: un fichero de compose que sea un enlace simbólico
    # sigue perteneciendo al directorio desde el que Compose levantó el proyecto.
    return Path(fragments[0]).parent.resolve(), None


@dataclass(frozen=True)
class Record:
    """Un proyecto ya clasificado. `project` y `status` van **crudos**: se escapan al imprimir."""

    project: str
    status: str
    klass: str
    origin: Path | None = None
    reason: str | None = None
    worktree: Path | None = None
    branch: str | None = None
    on_disk: bool | None = None


def classify(
    project: dict[str, str], roots: dict[Path, str | None], main_root: Path
) -> Record:
    """Clasifica un proyecto con las cuatro reglas de D5, en orden.

    El orden es lo que resuelve el anidamiento: los worktrees de este repositorio viven
    **dentro** del árbol del principal, así que una regla de «prefijo registrado más largo»
    atribuiría un worktree desregistrado al principal y lo daría por vivo. La igualdad exacta
    no, porque cada proyecto tiene su fichero en la raíz de su worktree.

    La existencia en disco se adjunta como dato impreso y **nunca** se usa como criterio:
    `git worktree list` es la fuente de verdad, y el caso habitual es «worktree
    desregistrado con el directorio en pie».
    """
    if not main_root.is_absolute():
        raise DiagnosticError(
            "la raíz del repositorio no es una ruta absoluta "
            f"({str(main_root)!r}): con ella la pertenencia al árbol se vuelve universal y "
            "marcaría de huérfano cualquier stack de la máquina"
        )
    main = main_root.resolve()
    registered = {root.resolve(): branch for root, branch in roots.items()}
    name, status = project["Name"], project["Status"]

    origin, reason = project_dir(project["ConfigFiles"])
    if origin is None:
        return Record(project=name, status=status, klass=INDETERMINADO, reason=reason)
    if origin in registered:
        return Record(
            project=name,
            status=status,
            klass=VIVO,
            origin=origin,
            worktree=origin,
            branch=registered[origin],
        )
    if origin.is_relative_to(main):
        return Record(
            project=name,
            status=status,
            klass=HUERFANO,
            origin=origin,
            on_disk=origin.is_dir(),
        )
    return Record(project=name, status=status, klass=AJENO, origin=origin)


def escape(value: str) -> str:
    """Sanea **solo para pantalla**, con lista blanca de imprimibles y de forma inyectiva.

    `\\\\` para la barra invertida y `\\xNN`/`\\uNNNN`/`\\UNNNNNNNN` —longitud fija, que es lo
    que mantiene la inyectividad— para todo carácter no imprimible: controles C0, C1
    (incluido `\\x9b`, el CSI de un byte) y separadores distintos del espacio. Dos nombres
    distintos nunca se ven iguales, así que un contenedor hostil no puede hacerse pasar por
    otro proyecto. Nunca se aplica antes de clasificar: el veredicto usa el valor crudo.
    """
    pieces = []
    for char in value:
        if char == "\\":
            pieces.append("\\\\")
        elif char.isprintable():
            pieces.append(char)
        elif ord(char) < 0x100:
            pieces.append(f"\\x{ord(char):02x}")
        elif ord(char) <= 0xFFFF:
            pieces.append(f"\\u{ord(char):04x}")
        else:
            pieces.append(f"\\U{ord(char):08x}")
    return "".join(pieces)


CLASS_ORDER = (HUERFANO, INDETERMINADO, VIVO, AJENO)
CLASS_COUNT_LABELS = {
    HUERFANO: "huérfanos",
    INDETERMINADO: "indeterminados",
    VIVO: "vivos",
    AJENO: "ajenos",
}

# Frase fija, sin interpolar nada: el informe no propone ningún comando de derribo con datos
# dentro, porque eso es la trampa de copiar y pegar (`specs/seed-data-demo.md:492` enumera y
# no borra; `specs/backend-ci.md:130` avisa de que un barrido no distingue huérfano de vivo).
CLOSING = (
    "Este informe no actúa: qué stack se baja y qué disco se recupera lo decide y lo "
    "ejecuta una persona."
)


def render(records: list[Record]) -> str:
    """Un bloque por proyecto, una etiqueta y un valor por línea, orden determinista.

    Sin tabla y sin delimitador compuesto: con un campo por línea no hay separador que un
    nombre hostil pueda falsificar para fabricar una fila.
    """
    ordered = sorted(records, key=lambda r: (CLASS_ORDER.index(r.klass), r.project))
    blocks = []
    for record in ordered:
        lines = [
            f"clase: {record.klass}",
            f"proyecto: {escape(record.project)}",
            f"estado: {escape(record.status)}",
        ]
        if record.reason is not None:
            lines.append(f"motivo: {escape(record.reason)}")
        if record.origin is not None:
            lines.append(f"origen: {escape(str(record.origin))}")
        if record.worktree is not None:
            lines.append(f"worktree: {escape(str(record.worktree))}")
        if record.branch is not None:
            lines.append(f"rama: {escape(record.branch)}")
        if record.on_disk is not None:
            lines.append(f"directorio en disco: {'sí' if record.on_disk else 'no'}")
        blocks.append("\n".join(lines))

    if not blocks:
        blocks.append("sin proyectos de Compose en esta máquina")

    counts = [
        f"{CLASS_COUNT_LABELS[klass]}: {sum(1 for r in ordered if r.klass == klass)}"
        for klass in CLASS_ORDER
    ]
    return "\n\n".join([*blocks, "\n".join(counts), CLOSING]) + "\n"


def capture(command: list[str]) -> str:
    """Invoca un comando ajeno y devuelve su salida, o aborta nombrando por qué no la hay."""
    try:
        completed = subprocess.run(command, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise DiagnosticError(f"`{command[0]}` no está disponible en el `PATH`: {exc}") from exc
    if completed.returncode != 0:
        raise DiagnosticError(
            f"`{' '.join(command)}` terminó con código {completed.returncode}: "
            f"{summarize(completed.stderr)}"
        )
    return completed.stdout


def summarize(stderr: str) -> str:
    """Resume el error ajeno: su primera línea, escapada y acotada. Nunca el volcado entero."""
    first = next((line for line in stderr.splitlines() if line.strip()), "sin mensaje de error")
    return escape(first[:200].strip())


def main() -> int:
    """Invoca, encadena e imprime; toda la lógica vive en las funciones puras de arriba.

    Dos regímenes de salida que no se mezclan: **distinto de cero** cuando no se pudo
    *obtener* el dato, y **cero** siempre que el inventario se obtuvo, haya huérfanos o no.
    Es un informe, no una guardia de CI.
    """
    try:
        main_root, roots = parse_worktrees(capture(WORKTREE_COMMAND))
        projects = parse_projects(capture(PROJECTS_COMMAND))
        records = [classify(project, roots, main_root) for project in projects]
    except DiagnosticError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(render(records), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
