"""Desplazamiento de los puertos publicados del stack local: `make up PORT_OFFSET=<n>`.

Entrada del roadmap: `worktree-port-offset`. Un worktree enlazado levanta su stack **sin
publicar ningún puerto** desde `worktree-parallel-stack` (2026-08-05), y eso costó el navegador:
ni UI ni API alcanzables desde el host, ni desde un móvil de la LAN. Este script devuelve esa
posibilidad **sin** reintroducir el choque, desplazando los cuatro puertos con un solo sumando:
`postgres 5432+n`, `redis 6379+n`, `backend 8000+n`, `frontend 3000+n`.

La decisión de cabecera del diseño (D1) y de la que cuelga todo lo demás: el desplazamiento vive
en un overlay que **Compose no descubre por sí solo** (`.make/docker-compose.offset.yml`, cargado
solo con `-f` explícito). Por eso la guardia de la postura de red —`scripts/compose-ports.py`,
que invoca Compose **desnudo** y sanea el entorno del hijo por lista blanca— no puede verlo, su
`EXEMPT` no se toca y su veredicto sigue siendo función **solo del repositorio**. Queda prohibido
«mejorar» esto renombrando el overlay a `docker-compose.override.yml`, moviéndolo a la raíz o
añadiendo un `-f` al target de la guardia: cualquiera de las tres la deja ciega.

Y por eso mismo el overlay se **genera** con números literales en vez de commitearse con
`${..._HOST_PORT}` (D2): con `--no-interpolate` un mapeo interpolado llega como cadena cruda, así
que solo se podrían comparar plantillas, y la aserción previa a levantar tiene que ser
**numérica**. De paso, ningún `ports` del repositorio queda dependiendo del entorno.

Lista negra heredada literalmente de `compose-ports.py` — prohibido en este script:

- `docker` + `inspect` sin `--format`: su salida por defecto incluye `.Config.Env`.
- `docker compose config` sin `--no-interpolate --no-env-resolution`. Las dos banderas viven en
  `CONFIG_BASE`, que es la única forma de construir la invocación aquí, y hay un test que lo
  comprueba sobre este propio código.
- Cualquier volcado de salida ajena. `stdout` de Compose **no se relata nunca**; de `stderr`,
  solo su primera línea, saneada y acotada.
- `shell=True` y cualquier invocación por shell: lista de argumentos, siempre.

Contrato: se ejecuta desde la raíz del repositorio. **Código 0** cuando el paso pedido salió
bien; **distinto de cero** en cualquier otro caso, incluida cualquier rotura de la cadena. Nunca
se degrada a «publicar lo que salga».
"""

import json
import os
import re
import socket
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

COMPOSE = ("docker", "compose")

CONFIG_BASE = ("config", "--no-interpolate", "--no-env-resolution")

BASE_FILE = "docker-compose.yml"

OFFSET_FILE = Path(".make") / "docker-compose.offset.yml"

LOOPBACK = "127.0.0.1"

ALL_INTERFACES = "0.0.0.0"

MAX_PORT = 65535

MIN_COMPOSE = "2.35.0"

STDERR_LIMIT = 200

DETAIL_LIMIT = 200

# `fullmatch` sobre esta clase, y no `match` sobre `^[0-9]+$`: en Python `$` encaja también
# **antes de un salto de línea final**, así que aquella forma aceptaba `PORT_OFFSET=$'10\n'` en
# contra de lo que R5.1 dice y de lo que promete el docstring de `parse_offset`.
OFFSET_PATTERN = re.compile(r"[0-9]+")


class OffsetError(Exception):
    """El desplazamiento no sirve o la cadena se rompió: rojo, nunca «arranca igual»."""


@dataclass(frozen=True)
class Publication:
    """Un servicio que publica, con la interfaz que le toca. `host_ip` `None` es «todas».

    Es la **sede única** de la aritmética `offset ⇄ puerto` (D4): ni el `Makefile` ni ningún
    otro punto de este script derivan un puerto por su cuenta.
    """

    service: str
    target: int
    host_ip: str | None


# Los cuatro que publican, y solo esos cuatro: `worker`, `beat` y `migrate` no publican nada
# sin desplazamiento y tampoco con él (R2.3). El `host_ip` no es cosmética — `postgres` y
# `redis` acotados a loopback son lo que sostiene la exención de `POSTGRES_PASSWORD` de
# steering/security.md regla 8, y `backend`/`frontend` en todas las interfaces son el motivo
# entero de este change: abrir la app desde un móvil real por la IP de LAN.
SERVICES = (
    Publication("postgres", 5432, LOOPBACK),
    Publication("redis", 6379, LOOPBACK),
    Publication("backend", 8000, None),
    Publication("frontend", 3000, None),
)

PUBLISHING = frozenset(pub.service for pub in SERVICES)

# El techo del desplazamiento sale del mayor de los cuatro puertos base, no de una constante
# escrita a mano: si algún día se añade un servicio que publique más arriba, el techo baja solo.
MAX_OFFSET = MAX_PORT - max(pub.target for pub in SERVICES)


def escape(value: str) -> str:
    """Sanea **solo para pantalla**, con lista blanca de imprimibles y de forma inyectiva.

    Mismo criterio y mismo motivo que en `compose-ports.py`: lo que se nombra —un valor que
    escribió una persona, un nombre de servicio que trae el modelo— es dato ajeno al formato de
    la salida. Longitudes fijas (`\\xNN`/`\\uNNNN`/`\\UNNNNNNNN`) para mantener la inyectividad.
    Nunca se aplica antes de decidir: el veredicto usa el valor crudo.
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

    Acotado a `DETAIL_LIMIT` por la misma razón que en la guardia: sin tope, nombrar algo que no
    es un mapeo —un servicio entero, una clave `ports` que no es lista— imprimiría una porción
    arbitraria del modelo, y «ningún volcado de salida ajena» es la lista negra que se hereda.
    """
    text = json.dumps(value, sort_keys=True, ensure_ascii=False, default=repr)
    if len(text) <= DETAIL_LIMIT:
        return text
    return text[:DETAIL_LIMIT] + "… (recortado)"


# ── Validación y aritmética: la sede única del cálculo (D4, D9) ─────────────────────────────


def parse_offset(raw: str) -> int:
    """Un entero no negativo cuyos cuatro puertos caben en rango, o `OffsetError` (R5.1, R5.2).

    La clase es `^[0-9]+$` y no `str.isdigit()` ni un `int()` a pelo, y la diferencia es real:
    `isdigit()` acepta los dígitos árabes `١٠` e `int()` los convierte a 10, así que un
    desplazamiento que nadie escribió a propósito entraría en silencio. Tampoco se admite signo,
    espacio ni notación hexadecimal — un `+10` o un ` 10` son casi siempre un dedazo.

    El mensaje nombra **el valor recibido**, y en el caso del rango **qué puerto** se sale: el
    síntoma que R5 existe para evitar es «la app no carga».
    """
    if not OFFSET_PATTERN.fullmatch(raw):
        raise OffsetError(
            f"PORT_OFFSET tiene que ser un entero no negativo en decimal, y recibí "
            f"`{escape(raw)}`. Sin signo, sin espacios y sin hexadecimal."
        )
    offset = int(raw)
    for pub in SERVICES:
        published = pub.target + offset
        if published > MAX_PORT:
            raise OffsetError(
                f"PORT_OFFSET={escape(raw)} lleva el puerto de `{pub.service}` a {published}, "
                f"que se sale del rango válido (máximo {MAX_PORT}). El desplazamiento mayor "
                f"que admiten los cuatro puertos es {MAX_OFFSET}."
            )
    return offset


def host_ports(offset: int) -> dict[str, int]:
    """Los cuatro puertos de host para un desplazamiento, con **un solo sumando** (R1.4)."""
    return {pub.service: pub.target + offset for pub in SERVICES}


def mapping_of(pub: Publication, offset: int) -> str:
    """El mapeo tal como se escribe en el overlay: `[<interfaz>:]<host>:<contenedor>`.

    Números **literales**, nunca `${..._HOST_PORT}` (D2). El prefijo de interfaz solo lo llevan
    los que van acotados: sin prefijo, Docker publica en todas las interfaces, que es justo lo
    que `backend` y `frontend` quieren y `postgres` y `redis` no pueden permitirse.
    """
    published = pub.target + offset
    if pub.host_ip is None:
        return f"{published}:{pub.target}"
    return f"{pub.host_ip}:{published}:{pub.target}"


OVERLAY_HEADER = """# GENERADO por `make up PORT_OFFSET=<n>` (scripts/compose-offset.py). No se edita a mano y no
# se versiona: `.gitignore` ignora `.make/` entero. Se reescribe en cada invocación con
# desplazamiento, así que no hay estado que quede viejo — es función pura del desplazamiento.
#
# Por qué vive aquí y no en la raíz, y por qué NO se llama `docker-compose.override.yml`: la
# guardia de la postura de red (`scripts/compose-ports.py`) invoca Compose **desnudo** y decide
# sobre lo que Compose descubre por sí solo. Un overlay que solo se carga con `-f` explícito
# queda fuera de su vista, así que el desplazamiento no puede cambiar su veredicto. Renombrarlo,
# moverlo a la raíz o añadir un `-f` al target de la guardia la dejaría ciega.
#
# `!override` y no `!reset` + lista: la fusión de Compose CONCATENA arrays, así que `!override`
# es lo que SUSTITUYE los mapeos del fichero base. Con él este overlay vale igual en el worktree
# principal y en uno enlazado, sin depender del orden de los `-f`.
services:
"""


def overlay_text(offset: int) -> str:
    """El overlay entero para un desplazamiento. Determinista: mismo `n`, mismos bytes."""
    blocks = [
        f"  {pub.service}:\n    ports: !override [\"{mapping_of(pub, offset)}\"]\n"
        for pub in SERVICES
    ]
    return OVERLAY_HEADER + "\n".join(blocks)


def generate(offset: int, root: Path | None = None) -> Path:
    """Escribe `.make/docker-compose.offset.yml` con los cuatro mapeos literales (R1.1, R1.4).

    Crea `.make/` si falta y **regenera siempre**: el contenido es función pura de `offset`, así
    que un segundo `make up` con el mismo número deja el fichero byte a byte idéntico y Compose
    no recrea nada.
    """
    target = (root or Path(".")) / OFFSET_FILE
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(overlay_text(offset), encoding="utf-8")
    except OSError as exc:
        raise OffsetError(
            f"no se pudo escribir el overlay de desplazamiento en `{escape(str(target))}`: "
            f"{escape(str(exc))}. Sin él no hay desplazamiento que aplicar, y se aborta en rojo "
            "en vez de levantar publicando lo que salga."
        ) from exc
    return target


# ── La cadena: cómo se invoca a Compose ─────────────────────────────────────────────────────


def clean_env() -> dict[str, str]:
    """El entorno del hijo, construido desde cero por **lista blanca**. `PATH` y nada más.

    Copiado literalmente de `compose-ports.py` y por su mismo argumento, que es de **dirección
    de fallo**: una lista blanca demasiado estrecha falla en rojo —Compose no arranca y esto lo
    nombra—, mientras que una lista negra demasiado estrecha falla en verde y se reabre con cada
    variable que Docker añada (`COMPOSE_FILE`, `COMPOSE_PROFILES`, `COMPOSE_ENV_FILES`, y la
    siguiente, que no conocemos).

    Aquí tiene además una consecuencia propia: un `PORT_OFFSET` exportado en la shell **no**
    llega al hijo, así que no puede desplazar nada por la puerta de atrás.
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
    del contenido y **antes** de mirarlo.

    `stdout` no se relata nunca; de `stderr`, solo su primera línea. Relatarla es seguro por las
    banderas de `CONFIG_BASE` y no por confianza: sin interpolación no hay error de
    interpolación que pueda citar un valor del `.env`.
    """
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, env=clean_env()
        )
    except FileNotFoundError as exc:
        raise OffsetError(
            f"`{escape(command[0])}` no está disponible en el `PATH`: {escape(str(exc))}"
        ) from exc
    if completed.returncode != 0:
        raise OffsetError(
            f"el paso `{escape(' '.join(command))}` terminó con código "
            f"{completed.returncode}: {summarize(completed.stderr)}. Si dice `unknown flag`, "
            f"tu Docker Compose es anterior al mínimo del proyecto ({MIN_COMPOSE}, que es "
            "cuando llegó `--no-env-resolution`)."
        )
    return completed.stdout


def config_command(*extra: str) -> list[str]:
    """La única forma de construir la invocación de `config`: prefijo, los dos `-f`, base, extras.

    Los dos `-f` van **explícitos y en este orden**: el primero fija el directorio de proyecto
    (y por tanto el nombre del stack), el segundo aporta el desplazamiento. El overlay de
    worktree **no** entra: con desplazamiento no se carga (D3), y las dos configuraciones solo
    difieren en `ports` (medido en el diseño).
    """
    return [*COMPOSE, "-f", BASE_FILE, "-f", str(OFFSET_FILE), *CONFIG_BASE, *extra]


def parse_model(text: str) -> object:
    """Decodifica el modelo. JSON no parseable es rojo con mensaje propio, nunca «vacío»."""
    try:
        return json.loads(text)
    except ValueError as exc:
        raise OffsetError(
            "la salida del modelo de Compose no es JSON válido, así que no describe ninguna "
            f"postura: {escape(str(exc))}"
        ) from exc


# ── `check`: la aserción de la configuración resuelta (D7, R6.1) ────────────────────────────


ANY_INTERFACE = "todas las interfaces"


def services_of(model: object) -> dict[str, object]:
    """Extrae `services` validando su forma; cualquier sorpresa es `OffsetError`.

    Un `config` que salga con **éxito** devolviendo `{}` no es «ningún servicio»: es un modelo
    sin la clave, y darlo por vacío dejaría pasar un stack que publica lo que le dé la gana.
    """
    if not isinstance(model, dict):
        raise OffsetError(
            f"el modelo de Compose no es un objeto, sino {type(model).__name__}: no hay "
            "servicios que inspeccionar, así que no se puede afirmar qué se publicaría."
        )
    if "services" not in model:
        raise OffsetError(
            "el modelo de Compose no trae la clave `services`, así que no describe ningún "
            "servicio: darlo por vacío daría verde sin haber comprobado nada."
        )
    services = model["services"]
    if not isinstance(services, dict):
        raise OffsetError(
            f"`services` del modelo de Compose no es un objeto, sino {type(services).__name__}"
        )
    return services


def label_of(service: str, entry: object) -> str:
    """Cómo se nombra un mapeo: quién publica, en qué interfaz y hacia qué puerto del contenedor.

    Etiqueta de texto y no una tupla porque es a la vez la clave de la comparación y lo que se
    imprime: así el mensaje de un desajuste nombra exactamente lo que se comparó, sin una
    segunda representación que pueda desincronizarse.

    Un mapeo que no es un objeto —el caso de la interpolación, que con `--no-interpolate` llega
    como cadena cruda— se nombra por su valor crudo, así que nunca puede coincidir con un
    esperado.
    """
    if not isinstance(entry, dict):
        return f"{escape(service)} sin normalizar: {escape(dump(entry))}"
    host = entry.get("host_ip")
    where = escape(host) if isinstance(host, str) else ANY_INTERFACE
    published = entry.get("published")
    published_text = escape(published) if isinstance(published, str) else escape(dump(published))
    return f"{escape(service)} {where}:{published_text} -> {escape(dump(entry.get('target')))}"


def expected_labels(offset: int) -> set[str]:
    """El conjunto **exacto** de mapeos que debe publicar un stack desplazado por `offset`."""
    return {
        f"{pub.service} {pub.host_ip or ANY_INTERFACE}:{pub.target + offset} -> {pub.target}"
        for pub in SERVICES
    }


def observed_labels(model: object) -> set[str]:
    """Todos los mapeos que el modelo declara, vengan del servicio que vengan."""
    services = services_of(model)
    found: set[str] = set()
    for service in sorted(services):
        body = services[service]
        if not isinstance(body, dict):
            raise OffsetError(
                f"el servicio `{escape(service)}` del modelo no es un objeto, así que su "
                f"postura de red no se puede leer: {escape(dump(body))}"
            )
        if "ports" not in body:
            continue
        entries = body["ports"]
        if not isinstance(entries, list):
            raise OffsetError(
                f"la clave `ports` del servicio `{escape(service)}` no es una lista, así que "
                f"no hay mapeos que recorrer: {escape(dump(entries))}"
            )
        found.update(label_of(service, entry) for entry in entries)
    return found


def difference(left: set[str], right: set[str], left_name: str, right_name: str) -> str:
    """Nombra la diferencia en las dos direcciones, ordenada."""
    only_left = sorted(left - right)
    only_right = sorted(right - left)
    parts = []
    if only_left:
        parts.append(f"solo en {left_name}: " + "; ".join(only_left))
    if only_right:
        parts.append(f"solo en {right_name}: " + "; ".join(only_right))
    return ". ".join(parts) + "."


def assert_config(model: object, offset: int) -> None:
    """Las **dos mitades** de la comprobación previa a levantar (D7, R6.1).

    1. El conjunto de mapeos publicados es **exactamente** el esperado para `offset` —igualdad
       y no contención, la misma disciplina que `assert_inventory` de la guardia—. Un
       `!override` que no se aplicó deja los dos mapeos y sale en rojo; un mapeo interpolado
       llega sin normalizar y también; un datastore fuera de `127.0.0.1` no coincide con su
       esperado (R2.1) y `backend`/`frontend` acotados a loopback tampoco (R2.2).
    2. **Ningún otro servicio trae clave `ports`** (R2.3). Es una comprobación aparte y no un
       corolario de la primera: un `ports: []` no produce ninguna entrada, así que pasaría la
       igualdad sin que nadie hubiera decidido qué publica ese servicio.
    """
    observed = observed_labels(model)
    expected = expected_labels(offset)
    if observed != expected:
        raise OffsetError(
            f"la configuración resuelta no publica lo que corresponde a PORT_OFFSET={offset}. "
            + difference(observed, expected, "la configuración", "lo esperado")
            + " Se aborta antes de levantar: un `!override` que no se aplicó, un mapeo que "
            "depende del entorno o un servicio acotado a otra interfaz cambian la postura de "
            "red del stack."
        )

    services = services_of(model)
    intruders = sorted(
        service
        for service, body in services.items()
        if service not in PUBLISHING and isinstance(body, dict) and "ports" in body
    )
    if intruders:
        raise OffsetError(
            "estos servicios traen clave `ports` y no deberían publicar nada: "
            + ", ".join(escape(name) for name in intruders)
            + ". El desplazamiento cubre exactamente cuatro servicios; si uno nuevo tiene que "
            "publicar, añádelo a `SERVICES` en `scripts/compose-offset.py` en el mismo Pull "
            "Request que lo introduce — ese es el momento de decidir en qué interfaz."
        )


def resolved_model() -> object:
    """Invoca `config` sobre base + overlay y devuelve el modelo, o aborta con mensaje propio."""
    if not OFFSET_FILE.exists():
        raise OffsetError(
            f"falta `{OFFSET_FILE}`, que es donde vive el desplazamiento, así que no se puede "
            "comprobar qué se publicaría. Se aborta en rojo en vez de degradar a levantar "
            "publicando lo que salga."
        )
    return parse_model(capture(config_command("--format", "json")))


# ── El sondeo de binds: antes de levantar, no después (D7, R5.3) ────────────────────────────
#
# Dos residuales aceptados a sabiendas, escritos aquí para que no se descubran como un bug:
#
# 1. **TOCTOU.** Entre este sondeo y el bind real de Docker hay una ventana en la que alguien
#    puede ocupar el puerto. Se acepta: el fallo degrada al error de Compose, que nombra el
#    puerto, y el sondeo elimina el caso habitual —el otro stack ya levantado—.
# 2. **Solo IPv4** (Q2, decidido en contra de la recomendación del diseño). Un puerto ocupado
#    únicamente en `::` y libre en `0.0.0.0` atraviesa este sondeo y falla al levantar, con el
#    error de Compose en vez del mensaje propio de R5.3. Es un hueco estrecho —pide un proceso
#    escuchando en IPv6 y no en IPv4 en ese mismo puerto— y ensancharlo es una línea.
#
# Y `SO_REUSEADDR` **no se activa**, que es la tercera decisión y la menos evidente: con él un
# bind puede tener éxito donde Docker fallará, y esa dirección de fallo es la mala. Sin él, un
# puerto en `TIME_WAIT` se reporta ocupado sin estarlo — se aborta de más, nunca de menos.


def occupied(host_ip: str, port: int) -> bool:
    """¿Está ese puerto tomado en esa interfaz? Se responde intentando el bind, en IPv4."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host_ip, port))
        except OSError:
            return True
    return False


def probe(offset: int, excluded: frozenset[int]) -> None:
    """Aborta nombrando **puerto y servicio** si alguno de los cuatro ya está tomado (R5.3).

    `excluded` son los puertos que **este mismo proyecto** ya publica: sin esa exclusión, un
    `make up PORT_OFFSET=10` sobre un stack ya levantado con 10 abortaría contra sí mismo, y
    `up` dejaría de ser idempotente.
    """
    for pub in SERVICES:
        published = pub.target + offset
        if published in excluded:
            continue
        where = pub.host_ip or ALL_INTERFACES
        if occupied(where, published):
            raise OffsetError(
                f"el puerto {published} que `{pub.service}` publicaría en `{where}` ya está "
                "ocupado en esta máquina, así que el stack fallaría a medio levantar. Elige "
                "otro PORT_OFFSET, o baja el stack que lo tiene tomado "
                "(`make compose-stacks` lista los de esta máquina)."
            )


# ── `show`: el desplazamiento se DERIVA del stack vivo (D8, R4.2) ───────────────────────────


def parse_ps(text: str) -> list[dict]:
    """Decodifica `docker compose ps --format json`, en sus **dos** formas.

    Compose 5.1.1 emite una línea por contenedor; versiones anteriores emiten un array. Se
    aceptan las dos porque el suelo del proyecto (2.35.0) cubre ambas. Salida vacía es un stack
    parado, que es un estado normal y no un error.
    """
    stripped = text.strip()
    if not stripped:
        return []
    try:
        decoded = json.loads(stripped)
    except ValueError:
        decoded = None
    if isinstance(decoded, list):
        rows = decoded
    else:
        rows = []
        for line in stripped.splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise OffsetError(
                    "la salida de `docker compose ps` no es JSON válido, así que no describe "
                    f"ningún stack: {escape(str(exc))}"
                ) from exc
    if not all(isinstance(row, dict) for row in rows):
        raise OffsetError(
            "la salida de `docker compose ps` no describe contenedores: alguna entrada no es "
            "un objeto."
        )
    return rows


def live_ports(rows: list[dict]) -> dict[str, list[tuple[str, int, int]]]:
    """Por servicio, los mapeos publicados: `(interfaz, puerto de host, puerto de contenedor)`.

    Solo se cuentan los que traen `PublishedPort`: Compose emite también entradas sin él para
    puertos expuestos que no se publican, y esas no son un mapeo de host.
    """
    found: dict[str, list[tuple[str, int, int]]] = {}
    for row in rows:
        service = row.get("Service")
        if not isinstance(service, str):
            continue
        publishers = row.get("Publishers") or []
        if not isinstance(publishers, list):
            continue
        for entry in publishers:
            if not isinstance(entry, dict):
                continue
            published = entry.get("PublishedPort")
            target = entry.get("TargetPort")
            if not isinstance(published, int) or not published:
                continue
            if not isinstance(target, int):
                continue
            url = entry.get("URL")
            found.setdefault(service, []).append(
                (url if isinstance(url, str) else ALL_INTERFACES, published, target)
            )
    return found


def render_show(rows: list[dict]) -> str:
    """Los cuatro mapeos efectivos y el desplazamiento **derivado**, o por qué no lo hay.

    Se deriva del stack **vivo** y no del overlay generado, y esa es la decisión (D8): el
    fichero describe la última *intención*, mientras que esto describe lo que está corriendo —
    que es verdad incluso si alguien levantó con otro número, y existe también en el principal,
    donde no hay overlay ninguno.

    El stack parado y el stack sin puertos publicados son estados **normales**: se informan y
    salen en verde. Y un desplazamiento incoherente entre servicios se informa como tal, sin
    inventar un número.
    """
    if not rows:
        return (
            "no hay ningún servicio levantado en este directorio, así que no hay puertos que "
            "informar. Levántalo con `make up` (o `make up PORT_OFFSET=<n>`).\n"
        )

    published = live_ports(rows)
    if not published:
        return (
            "el stack está levantado **sin publicar** ningún puerto: es el modo por defecto de "
            "un worktree enlazado, así que no hay UI ni API alcanzables desde el host. Para "
            "publicarlos desplazados: `make up PORT_OFFSET=<n>`.\n"
        )

    lines = []
    offsets = set()
    for pub in SERVICES:
        entries = published.get(pub.service, [])
        if not entries:
            lines.append(f"{pub.service}: sin publicar")
            continue
        for where, host_port, target in sorted(entries):
            lines.append(f"{pub.service}: {escape(where)}:{host_port} -> {target}")
            if target == pub.target:
                offsets.add(host_port - target)

    for service in sorted(set(published) - PUBLISHING):
        for where, host_port, target in sorted(published[service]):
            lines.append(f"{escape(service)}: {escape(where)}:{host_port} -> {target}")

    if len(offsets) == 1:
        lines.append(f"PORT_OFFSET={offsets.pop()}")
    else:
        lines.append(
            "desplazamiento incoherente entre servicios: no hay un solo número que describa "
            "este stack, así que no se inventa ninguno. Vuelve a levantarlo entero con "
            "`make up PORT_OFFSET=<n>`."
        )
    return "\n".join(lines) + "\n"


def live_rows() -> list[dict]:
    """El stack vivo de este directorio. `--format json` es obligatorio por la lista negra."""
    return parse_ps(capture([*COMPOSE, "ps", "--format", "json"]))


def show() -> str:
    return render_show(live_rows())


# ── `announce`: los cuatro puertos efectivos, dichos y no deducidos (R4.1, Q1) ──────────────


def announce(offset: int, worktree: bool) -> str:
    """Qué se va a levantar, en qué modo y en qué puertos. Se imprime **antes** de levantar."""
    where = (
        "worktree enlazado"
        if worktree
        else (
            "worktree principal — desplazar aquí no crea un segundo stack: **mueve** el que ya "
            "hay a los puertos nuevos"
        )
    )
    lines = [f"→ {where}: stack CON puertos publicados, desplazados PORT_OFFSET={offset}"]
    for pub in SERVICES:
        published = pub.target + offset
        interface = pub.host_ip or ALL_INTERFACES
        lines.append(f"   {pub.service}: {interface}:{published} -> {pub.target}")
    lines.append(
        f"   desde un móvil de la LAN: http://<IP de esta máquina>:{3000 + offset} — la IP no "
        "se calcula aquí a propósito, porque resolverla es específico de plataforma y falla de "
        "formas que se leen como un fallo del stack."
    )
    return "\n".join(lines) + "\n"


# ── La interfaz de línea de comandos ────────────────────────────────────────────────────────


def check(offset: int) -> None:
    """Asierta la configuración resuelta y **después** sondea los binds, todo antes de levantar.

    Ese orden es el de D7 y no es indiferente: sondear primero diría «el puerto está libre»
    sobre una configuración que igual no publica lo que creemos.
    """
    assert_config(resolved_model(), offset)
    mine = frozenset(
        host_port
        for entries in live_ports(live_rows()).values()
        for _, host_port, _ in entries
    )
    probe(offset, excluded=mine)


USAGE = (
    "uso: compose-offset.py generate <n> | check <n> | announce <n> [--worktree] | show"
)


def main(argv: list[str]) -> int:
    """Despacha el subcomando. Toda la lógica vive en las funciones de arriba.

    Dos regímenes de salida que no se mezclan: **0** solo si el paso pedido salió bien;
    **distinto de cero** en cualquier otro caso, incluida cualquier rotura de la cadena.
    """
    if not argv:
        print(USAGE, file=sys.stderr)
        return 2
    command, rest = argv[0], argv[1:]
    try:
        if command == "generate" and len(rest) == 1:
            generate(parse_offset(rest[0]))
            return 0
        if command == "check" and len(rest) == 1:
            check(parse_offset(rest[0]))
            return 0
        if command == "announce" and rest and len(rest) <= 2:
            worktree = rest[1:] == ["--worktree"]
            if rest[1:] and not worktree:
                print(USAGE, file=sys.stderr)
                return 2
            print(announce(parse_offset(rest[0]), worktree=worktree), end="")
            return 0
        if command == "show" and not rest:
            print(show(), end="")
            return 0
    except OffsetError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
