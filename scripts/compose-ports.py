#!/usr/bin/env python3
"""Guardia de la postura de red del stack local: ningún puerto publicado fuera de loopback.

Entrada del roadmap: `compose-ports-guard`. Lee el modelo que Compose normaliza y falla en
rojo, nombrando **servicio y mapeo**, si algún servicio publica un puerto en el host sin
acotarlo a `127.0.0.1`, salvo los dos pares servicio+puerto exentos a propósito
(`backend:8000` y `frontend:3000`, que publican en todas las interfaces porque el proyecto es
mobile-first). Se invoca con `make check-compose-ports` y en cada Pull Request.

La regla de invocación, que es la decisión de cabecera del diseño (D1) y no una preferencia:
`docker compose config` se invoca **siempre** con `--no-interpolate --no-env-resolution`, y
nunca a secas. Las dos banderas viven en `CONFIG_BASE`, que es la única forma de construir la
invocación en este fichero, y hay un test que lo comprueba sobre este propio código. Motivo
medido en esta máquina con Compose 5.1.1:

- Con las dos banderas, en un clon **sin `.env`**, sale con **código 0** y su salida no
  contiene ningún valor del `.env`: las variables quedan literales
  (`JWT_SECRET_KEY: "${JWT_SECRET_KEY:?...}"`).
- Sin ellas, y con un `.env` presente, la salida **inlina el fichero entero** en
  `environment` —también variables que el compose no menciona—, que es lo que prohíbe
  `sdd/specs/local-environment.md`.
- Y hace el veredicto función **solo del repositorio**: con interpolación activada, un
  `BIND=0.0.0.0` en el `.env` de alguien daría rojo en su máquina y verde en CI.

Lista negra heredada de `compose-stacks.py` — prohibido en este script:

- `docker` + `inspect` sin `--format`: su salida por defecto incluye `.Config.Env`.
- `docker compose config` sin las dos banderas de arriba (ver párrafo anterior).
- Cualquier volcado de salida ajena. `stdout` de Compose **no se relata nunca**, ni entero ni
  en fragmentos (R1.7); de `stderr` solo su primera línea, saneada y acotada, que es seguro
  por las dos banderas y no por confianza: sin interpolación no hay error de interpolación
  que pueda citar un valor.
- `shell=True` y cualquier invocación por shell: lista de argumentos, siempre.

Contrato: sin argumentos, se ejecuta desde la raíz del repositorio. **Código 0** cuando no hay
infracción, nombrando y contando lo inspeccionado —servicios, mapeos y profiles—, para que el
verde se lea como «vio esto» y no como «no vio nada». **Distinto de cero** en cualquier otro
caso, incluida cualquier rotura de la cadena.
"""

import json
import os
import subprocess
import sys
from collections.abc import Set as AbstractSet
from dataclasses import dataclass


# `--profile` es bandera global de `docker compose` y va **antes** del subcomando, así que la
# invocación se construye siempre en `config_command()`: prefijo, profiles, y estas banderas.
COMPOSE = ("docker", "compose")

# Las dos banderas de D1 viajan aquí y en ningún otro sitio. Un test sobre este fichero
# comprueba que no hay ninguna otra forma de construir la invocación.
CONFIG_BASE = ("config", "--no-interpolate", "--no-env-resolution")

# El inventario declarado: lo único que ata el modelo inspeccionado a **este** repositorio.
# Va por **igualdad** y no por contención (D4, Q1): un servicio nuevo deja la guardia en rojo
# hasta que alguien lo añada aquí, y ese momento es precisamente cuando hay que decidir qué
# publica. Es la misma disciplina que `docker-compose.worktree.yml` ya impone.
EXPECTED_SERVICES = frozenset(
    {"postgres", "redis", "migrate", "backend", "worker", "beat", "frontend"}
)

# La exención es por par **servicio+puerto**, nunca por servicio ni por puerto (R3, D9): un
# puerto extra en un servicio exento y el mismo puerto en un servicio no exento son rojo sin
# ninguna regla adicional, porque la unidad de decisión *es* el par. `published` llega como
# cadena en el modelo (medido: `'8000'`, no `8000`), así que la comparación es de cadenas.
EXEMPT = frozenset({("backend", "8000"), ("frontend", "3000")})

# Lista blanca y no `!= "host"` (D8): `host` publica todo **sin generar ninguna entrada
# `ports`** (medido), así que un bucle sobre `ports` lo trata como conforme — vía (b) del
# censo. Hoy ningún servicio del repositorio usa `network_mode`, así que el coste de la lista
# blanca es cero y la próxima forma de compartir el espacio de red del host llega en rojo.
SAFE_NETWORK_MODES = frozenset({None, "bridge", "none"})

LOOPBACK = "127.0.0.1"

# El suelo de versión de Compose, **medido** y no estimado: `--no-env-resolution` llegó en
# **v2.35.0** (2025-04-10) por el PR 12665 de `docker/compose`, y no existe en v2.34.0. Solo se
# usa para dar la pista en el mensaje de fallo: no hay lógica de comparación de versiones, D6
# decidió que una bandera desconocida ya sale en rojo por su estado de salida.
MIN_COMPOSE = "2.35.0"

# Cuánto de `stderr` ajeno se relata: su primera línea y hasta aquí. Nunca `stdout`, nunca el
# volcado entero (R1.7). Mismo criterio que `compose-stacks.py`.
STDERR_LIMIT = 200

# Y cuánto del modelo puede nombrar un hallazgo. Un mapeo cabe de sobra; el tope está para que
# nombrar algo que **no** es un mapeo no acabe imprimiendo una porción arbitraria del modelo.
DETAIL_LIMIT = 200


class GuardError(Exception):
    """La cadena se rompió o el dato no tiene la forma esperada: rojo, nunca verde."""


@dataclass(frozen=True)
class Violation:
    """Un hallazgo. `service` y `detail` van **crudos**: se escapan al imprimir."""

    service: str
    rule: str
    detail: str


def config_command(*extra: str, profiles: tuple[str, ...] = ()) -> list[str]:
    """La única forma de construir la invocación: prefijo, profiles, `CONFIG_BASE`, extras.

    Los profiles van por `argv` repetido y **nunca** unidos por comas (D3): la bandera es
    `stringArray` y viaja sin separador, así que no hay representación con pérdida. Un nombre
    de profile con una coma dentro es dato legítimo y Compose no lo restringe.
    """
    argv = list(COMPOSE)
    for profile in profiles:
        argv += ["--profile", profile]
    return [*argv, *CONFIG_BASE, *extra]


# ── Las seis reglas de decisión ────────────────────────────────────────────────────────────
#
# Códigos de regla. Son el dato que la salida imprime y el que los tests aciertan, así que
# cambiarlos es cambiar el contrato de la guardia.
SERVICE_NOT_OBJECT = "servicio-no-es-objeto"
NETWORK_MODE = "network_mode-no-seguro"
PORTS_NOT_LIST = "ports-no-es-lista"
NOT_NORMALIZED = "mapeo-no-normalizado"
NO_PUBLISHED = "mapeo-sin-published"
OFF_LOOPBACK = "mapeo-fuera-de-loopback"

# Etiqueta del tercer campo de cada bloque: una etiqueta y un valor por línea, y la etiqueta
# dice qué se está mirando en vez de un `detalle` genérico.
RULE_LABELS = {
    SERVICE_NOT_OBJECT: "valor",
    NETWORK_MODE: "network_mode",
    PORTS_NOT_LIST: "ports",
    NOT_NORMALIZED: "mapeo",
    NO_PUBLISHED: "mapeo",
    OFF_LOOPBACK: "mapeo",
}

# Por qué cada regla es roja, en una línea. Va en la salida para que el rojo sea accionable sin
# volver a leer el diseño: un rojo que no se puede diagnosticar invita a rerunear a ciegas.
RULE_REASONS = {
    SERVICE_NOT_OBJECT: (
        "un servicio del modelo no es un objeto, así que su postura de red no se puede leer"
    ),
    NETWORK_MODE: (
        "solo se admiten `bridge`, `none` o ausente: `host` comparte el espacio de red del "
        "host y publica todo sin generar ninguna entrada `ports`"
    ),
    PORTS_NOT_LIST: "la clave `ports` no es una lista, así que no hay mapeos que recorrer",
    NOT_NORMALIZED: (
        "Compose no normalizó el mapeo —sale como cadena cruda—, lo que ocurre cuando contiene "
        "una interpolación: un mapeo cuyo valor sale del entorno no es una postura del "
        "repositorio y no se puede aprobar"
    ),
    NO_PUBLISHED: (
        "sin puerto de host no hay par servicio+puerto que eximir, y Docker lo publica en un "
        "puerto efímero y en todas las interfaces"
    ),
    OFF_LOOPBACK: (
        f"se publica en el host sin acotarlo a `{LOOPBACK}`, así que queda alcanzable desde "
        "cualquier host de la red"
    ),
}


def escape(value: str) -> str:
    """Sanea **solo para pantalla**, con lista blanca de imprimibles y de forma inyectiva.

    El mismo criterio que `compose-stacks.py`, y por su mismo motivo: los nombres de servicio y
    de profile son dato ajeno al formato de la salida. `\\\\` para la barra invertida y
    `\\xNN`/`\\uNNNN`/`\\UNNNNNNNN` —longitud fija, que es lo que mantiene la inyectividad— para
    todo carácter no imprimible. Dos nombres distintos nunca se ven iguales, así que un servicio
    con caracteres de control en el nombre no puede fabricar un bloque ni hacerse pasar por
    otro. Nunca se aplica antes de decidir: el veredicto usa el valor crudo.
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


def dump(value: object) -> str:
    """El valor tal como lo trae el modelo, en una línea, determinista y **acotado**.

    `sort_keys` para que dos ejecuciones den el mismo texto, y `default=repr` para que un
    valor que no sea JSON —imposible viniendo de `json.loads`, posible en un test— salga
    nombrado en vez de reventar la guardia.

    Y acotado a `DETAIL_LIMIT`, que es lo que impide que esto se convierta en un volcado. Un
    mapeo normalizado ocupa menos de cien caracteres, así que en la práctica nunca se recorta;
    el recorte existe para el caso en que lo que se nombra **no** es un mapeo, sino un valor
    que Compose no tenía por qué devolver — un servicio entero que no es objeto, una clave
    `ports` que no es lista. Sin el tope, ese camino imprimiría una porción arbitraria del
    modelo, y «ningún volcado de salida ajena» es la lista negra que este script hereda (R1.7).
    """
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=repr)
    if len(text) <= DETAIL_LIMIT:
        return text
    return text[:DETAIL_LIMIT] + "… (recortado)"


def entry_violations(service: str, entry: object) -> list[Violation]:
    """Las reglas 3 a 6 de la decisión por mapeo, en orden y sobre una sola entrada.

    El orden importa y es el del diseño: `published` se comprueba **antes** que la exención,
    porque un objeto sin `published` es infracción incluso en un servicio exento (R5.1) — sin
    puerto de host no hay par que identificar.
    """
    if not isinstance(entry, dict):
        return [Violation(service, NOT_NORMALIZED, dump(entry))]
    if "published" not in entry:
        return [Violation(service, NO_PUBLISHED, dump(entry))]
    published = entry["published"]
    # `isinstance` antes de la pertenencia y no un `try`: un `published` que no sea cadena no
    # puede estar en `EXEMPT` (medido: llega como `'8000'`), así que cae al camino normal y es
    # rojo salvo que esté acotado. El test de contra Docker es quien avisa si la forma cambia.
    if isinstance(published, str) and (service, published) in EXEMPT:
        return []
    if entry.get("host_ip") == LOOPBACK:
        return []
    return [Violation(service, OFF_LOOPBACK, dump(entry))]


def service_violations(service: str, model: object) -> list[Violation]:
    """Las reglas 1 y 2 de la decisión, y después una pasada por cada mapeo declarado."""
    if not isinstance(model, dict):
        return [Violation(service, SERVICE_NOT_OBJECT, dump(model))]

    found: list[Violation] = []
    mode = model.get("network_mode")
    # El `isinstance` va delante para que un valor no hasheable (una lista, un objeto) sea
    # infracción en vez de un `TypeError` sin capturar en la pertenencia al conjunto.
    if not isinstance(mode, (str, type(None))) or mode not in SAFE_NETWORK_MODES:
        found.append(Violation(service, NETWORK_MODE, dump(mode)))

    if "ports" not in model:
        # Ausencia de la clave es conforme, y es la aserción correcta (R5.1): hay formas
        # legales de declarar un mapeo que no producen `published` ni `host_ip`, y esas sí
        # llegan como entradas y caen por las reglas de arriba.
        return found
    entries = model["ports"]
    if not isinstance(entries, list):
        found.append(Violation(service, PORTS_NOT_LIST, dump(entries)))
        return found
    for entry in entries:
        found.extend(entry_violations(service, entry))
    return found


def services_of(model: object) -> dict[str, object]:
    """Extrae `services` del modelo validando su forma; cualquier sorpresa es `GuardError`.

    Un `config` que salga con **éxito** devolviendo `{}` no es «ningún servicio»: es un modelo
    sin la clave, y darlo por vacío es la vía (h) del censo. Aquí se distingue el modelo mal
    formado (rojo con mensaje propio) del inventario que no cuadra (rojo de `assert_inventory`).
    """
    if not isinstance(model, dict):
        raise GuardError(
            f"el modelo de Compose no es un objeto, sino {type(model).__name__}: no hay "
            "servicios que inspeccionar"
        )
    if "services" not in model:
        raise GuardError(
            "el modelo de Compose no trae la clave `services`, así que no describe ningún "
            "servicio: darlo por vacío daría verde sin haber comprobado nada"
        )
    services = model["services"]
    if not isinstance(services, dict):
        raise GuardError(
            f"`services` del modelo de Compose no es un objeto, sino {type(services).__name__}"
        )
    return services


def violations(model: object) -> list[Violation]:
    """Los hallazgos del modelo entero, en orden determinista por servicio y por declaración."""
    services = services_of(model)
    found: list[Violation] = []
    for service in sorted(services):
        found.extend(service_violations(service, services[service]))
    return found


# ── La aserción positiva: dos igualdades antes de dar verde (D4, R4.4) ─────────────────────


def declared_profiles(services: dict[str, object]) -> set[str]:
    """La unión de los `profiles` que traen los servicios del modelo.

    Es la fuente **sin pérdida** de la segunda igualdad: la decodifica `json.loads`, así que un
    nombre con un salto de línea dentro llega entero. Cualquier forma que no sea una lista de
    cadenas es `GuardError` y no un conjunto más pequeño: adivinar aquí sería estrechar en
    silencio la vista de la guardia.
    """
    names: set[str] = set()
    for service, model in sorted(services.items()):
        if not isinstance(model, dict):
            # Se salta, y es seguro **por el orden de `main()`** y no porque no importe: un
            # servicio que no es objeto ya produjo su infracción por la regla 1, y `main()`
            # calcula los hallazgos antes de llegar aquí, así que la ejecución no puede acabar
            # en verde. Un valor que no es objeto tampoco puede declarar `profiles`.
            continue
        if "profiles" not in model:
            continue
        listed = model["profiles"]
        if not isinstance(listed, list) or not all(
            isinstance(name, str) for name in listed
        ):
            raise GuardError(
                f"los `profiles` del servicio `{escape(service)}` no son una lista de cadenas, "
                f"así que no se puede afirmar qué profiles se han inspeccionado: {dump(listed)}"
            )
        names.update(listed)
    return names


def assert_inventory(
    model: object, services_listed: AbstractSet[str], profiles_listed: AbstractSet[str]
) -> None:
    """Afirma en positivo lo que se ha visto, y falla si no lo puede confirmar (R4.4).

    Dos igualdades, y la segunda es la que cierra la clase entera del problema:

    1. Los servicios del modelo son **exactamente** `EXPECTED_SERVICES`, y **exactamente** los
       que devolvió la enumeración. Por igualdad y no por contención (Q1): un servicio nuevo
       deja la guardia en rojo hasta que alguien lo añada, y ese momento es cuando hay que
       decidir qué publica.
    2. La unión de los `profiles` del modelo es **igual** al conjunto que devolvió la
       enumeración de profiles. Aquí **la fuente sin pérdida audita a la fuente con pérdida**:
       el modelo lo decodifica `json.loads`, la enumeración llega por líneas y un nombre con un
       salto de línea dentro se parte en dos. Al exigir que coincidan, un profile que la
       enumeración no supo leer no llega a activarse, su servicio no aparece en el modelo, la
       unión no coincide y la guardia falla — vías (e), (g) y (h) del censo a la vez.

    Un `config` que salga con **éxito** devolviendo `{}` da conjunto de servicios vacío, que no
    es igual al inventario declarado: rojo. Eso es la inversión que pide el diagnóstico del
    roadmap — una aserción positiva en lugar de tres guardas negativas.
    """
    services = services_of(model)
    present = set(services)

    if present != EXPECTED_SERVICES:
        raise GuardError(
            "el inventario de servicios no cuadra con el que esta guardia declara. "
            f"{difference(present, EXPECTED_SERVICES, 'el modelo', 'EXPECTED_SERVICES')} "
            "Si el servicio es nuevo y legítimo, añádelo a `EXPECTED_SERVICES` en "
            "`scripts/compose-ports.py` en el mismo Pull Request que lo introduce: ese es el "
            "momento de decidir qué publica."
        )
    if present != services_listed:
        raise GuardError(
            "la enumeración de servicios y el modelo no describen lo mismo, así que la vista "
            "de la guardia podría ser más estrecha que la del stack. "
            f"{difference(present, services_listed, 'el modelo', 'la enumeración')}"
        )

    union = declared_profiles(services)
    if union != profiles_listed:
        raise GuardError(
            "los profiles del modelo y los enumerados por Compose no coinciden, así que no se "
            "puede afirmar que se hayan inspeccionado los servicios de todos los profiles. "
            f"{difference(union, profiles_listed, 'el modelo', 'la enumeración')}"
        )


def difference(
    left: AbstractSet[str], right: AbstractSet[str], left_name: str, right_name: str
) -> str:
    """Nombra la diferencia en las dos direcciones, ordenada y escapada."""
    only_left = sorted(left - right)
    only_right = sorted(right - left)
    parts = []
    if only_left:
        parts.append(
            f"solo en {left_name}: " + ", ".join(escape(name) for name in only_left)
        )
    if only_right:
        parts.append(
            f"solo en {right_name}: " + ", ".join(escape(name) for name in only_right)
        )
    return "; ".join(parts) + "."


# ── La salida ──────────────────────────────────────────────────────────────────────────────
#
# Una etiqueta y un valor por línea, un bloque por hallazgo, orden determinista. Sin tabla y
# sin delimitador compuesto: con un campo por línea no hay separador que un nombre de servicio
# hostil pueda falsificar para fabricar un bloque. Es el criterio de `compose-stacks.py`, y por
# su mismo motivo — los nombres de servicio y de profile son dato ajeno al formato.
RULE_ORDER = (
    SERVICE_NOT_OBJECT,
    NETWORK_MODE,
    PORTS_NOT_LIST,
    NOT_NORMALIZED,
    NO_PUBLISHED,
    OFF_LOOPBACK,
)

ALL_INTERFACES = "todas las interfaces"


def render(found: list[Violation]) -> str:
    """Los hallazgos, un bloque cada uno, en un orden que no depende del de entrada."""
    ordered = sorted(
        found, key=lambda v: (v.service, RULE_ORDER.index(v.rule), v.detail)
    )
    blocks = [
        "\n".join(
            [
                f"regla: {violation.rule}",
                f"servicio: {escape(violation.service)}",
                f"{RULE_LABELS[violation.rule]}: {escape(violation.detail)}",
                f"motivo: {RULE_REASONS[violation.rule]}",
            ]
        )
        for violation in ordered
    ]
    return "\n\n".join([*blocks, f"infracciones: {len(ordered)}"]) + "\n"


def mapping_label(service: str, entry: object) -> str:
    """Cómo se nombra un mapeo conforme en el verde: quién publica, dónde y hacia dónde."""
    if not isinstance(entry, dict):
        return f"{escape(service)} {escape(dump(entry))}"
    host = entry.get("host_ip")
    where = escape(host) if isinstance(host, str) else ALL_INTERFACES
    published = entry.get("published")
    target = entry.get("target")
    label = f"{escape(service)} {where}:{plain(published)} -> {plain(target)}"
    if isinstance(published, str) and (service, published) in EXEMPT:
        label += " (exento a propósito)"
    return label


def plain(value: object) -> str:
    """Un puerto tal como se lee, sin las comillas de JSON pero igual de saneado.

    `published` llega como cadena y `dump()` la envolvería en comillas, que en el verde se lee
    como si el puerto las llevara. Cualquier otra forma sí pasa por `dump()`, porque entonces
    la forma **es** el dato que interesa ver.
    """
    return escape(value) if isinstance(value, str) else escape(dump(value))


def summary(model: object, profiles: AbstractSet[str]) -> str:
    """El verde: **nombra y cuenta** lo inspeccionado, para que se lea «vio esto».

    No «no vio nada», que es exactamente lo que una guardia eludible imprime. Los tres
    recuentos —servicios, mapeos y profiles— son R2.3, y van con los nombres detrás porque un
    recuento solo no distingue haber mirado siete servicios de haber mirado siete veces uno.
    """
    services = services_of(model)
    lines = [f"servicios inspeccionados: {len(services)}"]
    mappings: list[str] = []
    for service in sorted(services):
        lines.append(f"servicio: {escape(service)}")
        model_of_service = services[service]
        if not isinstance(model_of_service, dict):
            continue
        entries = model_of_service.get("ports")
        if isinstance(entries, list):
            mappings.extend(mapping_label(service, entry) for entry in entries)

    lines.append(f"mapeos inspeccionados: {len(mappings)}")
    lines.extend(f"mapeo: {label}" for label in mappings)

    lines.append(f"profiles inspeccionados: {len(profiles)}")
    lines.extend(f"profile: {escape(name)}" for name in sorted(profiles))

    lines.append(
        f"veredicto: ningún puerto se publica fuera de {LOOPBACK}, salvo los pares exentos a "
        "propósito"
    )
    return "\n".join(lines) + "\n"


# ── La cadena: cómo se invoca a Compose ────────────────────────────────────────────────────


def clean_env() -> dict[str, str]:
    """El entorno del hijo, construido desde cero por **lista blanca** (D5).

    `PATH` y nada más. Medido: con solo `PATH`, la enumeración de servicios devuelve los 7 y
    código 0 — ni `HOME` ni la configuración de Docker hacen falta para esto.

    El argumento es de **dirección de fallo**, y por eso no es una lista negra: una lista
    blanca demasiado estrecha falla en **rojo** —Compose no arranca y la guardia lo nombra—,
    mientras que una lista negra demasiado estrecha falla en **verde**, que es la vía (d) del
    censo, y se reabre con cada variable nueva que Docker añada (`COMPOSE_FILE`,
    `COMPOSE_PATH_SEPARATOR`, `COMPOSE_PROFILES`, `COMPOSE_ENV_FILES`, y la siguiente, que no
    conocemos). Enumerar lo que se conserva es afirmar en positivo.

    Si no hubiera `PATH`, el hijo no se encuentra y sale por el camino de `FileNotFoundError`:
    rojo con mensaje propio, que es la dirección correcta.
    """
    return {"PATH": os.environ.get("PATH", "")}


def summarize(stderr: str) -> str:
    """Resume el error ajeno: su primera línea, escapada y acotada. Nunca el volcado entero."""
    first = next(
        (line for line in stderr.splitlines() if line.strip()), "sin mensaje de error"
    )
    return escape(first[:STDERR_LIMIT].strip())


def capture(command: list[str]) -> str:
    """Invoca un comando ajeno y devuelve su `stdout`, o aborta nombrando por qué no lo hay.

    Lista de argumentos y **nunca** por shell; sin `2>/dev/null` y sin pipes, porque en un pipe
    el estado de salida es el del último comando. El estado de salida se comprueba **aparte**
    del contenido y **antes** de mirarlo (R6.2) — la vía (e) del censo es exactamente eso:
    mientras se medía para el diseño, `config --services 2>&1 | tail -2` imprimió el error de
    interpolación y devolvió `rc=0`.

    En el fallo el mensaje nombra el paso y el código, y relata **solo la primera línea de
    `stderr`**, saneada y acotada. `stdout` no se relata **nunca**, ni entero ni en fragmentos
    (R1.7). Relatar esa línea es seguro por las banderas de `CONFIG_BASE` y no por confianza:
    sin interpolación no hay error de interpolación que pueda citar un valor del `.env`, y sin
    resolución de `env_file` no hay valores en juego.
    """
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, env=clean_env()
        )
    except FileNotFoundError as exc:
        raise GuardError(
            f"`{escape(command[0])}` no está disponible en el `PATH`: {escape(str(exc))}"
        ) from exc
    if completed.returncode != 0:
        raise GuardError(
            f"el paso `{escape(' '.join(command))}` terminó con código "
            f"{completed.returncode}: {summarize(completed.stderr)}. Si dice `unknown flag`, "
            f"tu Docker Compose es anterior al mínimo del proyecto ({MIN_COMPOSE}, que es "
            "cuando llegó `--no-env-resolution`)."
        )
    return completed.stdout


def parse_lines(text: str) -> set[str]:
    """Una enumeración por líneas de Compose: las no vacías, sin ordenar nada.

    Es la fuente **con pérdida** de la que habla D4 — un nombre con un salto de línea dentro se
    parte en dos aquí y no hay forma de notarlo desde este lado. Por eso no se usa sola: la
    aserción de inventario la contrasta contra el modelo, que sí es sin pérdida.
    """
    return {line for line in text.splitlines() if line.strip()}


def parse_model(text: str) -> object:
    """Decodifica el modelo. JSON no parseable es rojo con mensaje propio, nunca «vacío».

    El mensaje relata el error de `json`, que describe la **forma** (posición, token
    inesperado), y no el texto: volcar la salida es lo que R1.7 prohíbe.
    """
    try:
        return json.loads(text)
    except ValueError as exc:
        raise GuardError(
            "la salida del modelo de Compose no es JSON válido, así que no describe ninguna "
            f"postura: {escape(str(exc))}"
        ) from exc


def chain() -> tuple[object, set[str], tuple[str, ...]]:
    """Las tres invocaciones encadenadas, en orden, todas desde `CONFIG_BASE`.

    1. `config --profiles` enumera **todos** los profiles declarados, activos o no.
    2. `config --services` con un `--profile` por nombre, para que ningún servicio quede fuera.
    3. `config --format json`, con los mismos profiles, que es el modelo que se decide.

    Los profiles se ordenan antes de viajar para que el `argv` sea determinista, y van por
    bandera repetida y nunca unidos por comas (D3): la coma es un carácter legítimo de un
    nombre de profile y unirlos es la vía (g).
    """
    profiles = tuple(sorted(parse_lines(capture(config_command("--profiles")))))
    services_listed = parse_lines(
        capture(config_command("--services", profiles=profiles))
    )
    model = parse_model(
        capture(config_command("--format", "json", profiles=profiles))
    )
    return model, services_listed, profiles


def main() -> int:
    """Invoca, encadena, decide e imprime. Toda la lógica vive en las funciones puras.

    Dos regímenes de salida que no se mezclan: **0** solo si la aserción de inventario confirma
    y no hay ningún hallazgo; **distinto de cero** en cualquier otro caso, incluido cualquier
    fallo de la cadena. Nunca se degrada a verde.

    Los hallazgos se imprimen **aunque** el inventario no cuadre, en vez de abortar antes: las
    dos cosas son rojas y verlas juntas ahorra una vuelta al que añadió un servicio con un
    mapeo que además publica de más.
    """
    try:
        model, services_listed, profiles = chain()
        found = violations(model)
    except GuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if found:
        print(render(found), end="")

    try:
        assert_inventory(model, services_listed, set(profiles))
    except GuardError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if found:
        return 1
    print(summary(model, set(profiles)), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
