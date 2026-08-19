"""Suite de `compose-offset.py`, el desplazamiento de puertos de un stack local.

Obligación de método heredada de `compose-ports.py` y vinculante en este change (design D4):
la aritmética `offset ⇄ puerto` tiene **una sola sede**, así que se prueba antes de escribirla.
Y la lista negra de invocación —`config` siempre con las dos banderas, entorno del hijo por
lista blanca, listas de argumentos, nunca `shell=True`— se vigila por mecanismo sobre el propio
código, no por buena memoria.
"""

import ast
import importlib.util
import json
import os
import re
import socket
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compose-offset.py"
GUARD = ROOT / "scripts/compose-ports.py"

SPEC = importlib.util.spec_from_file_location(
    "compose_offset",
    Path(__file__).with_name("compose-offset.py"),
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


# ── Validación: un desplazamiento inservible falla pronto y nombra el valor (R5.1) ──────────
#
# Lista literal y no un `set`: el id del test tiene que ser estable entre workers, porque la
# suite corre en paralelo en CI (`steering/testing.md`).
NOT_AN_OFFSET = ["-1", "1.5", " 10", "0x10", "abc", "10 ", "+10", "1_0", "", "١٠", "10\n"]


@pytest.mark.parametrize("raw", NOT_AN_OFFSET)
def test_a_non_integer_offset_is_red_and_names_the_value_received(raw):
    """R5.1: entero no negativo y nada más. Sin signo, sin espacios, sin hexadecimal.

    `١٠` son dos dígitos árabes: `str.isdigit()` los acepta y `int()` los convierte a 10, así
    que validar con `isdigit()` dejaría pasar un valor que nadie escribió a propósito. La clase
    es `^[0-9]+$` justamente por eso.
    """
    with pytest.raises(module.OffsetError) as raised:
        module.parse_offset(raw)
    assert module.escape(raw) in str(raised.value)


@pytest.mark.parametrize("raw,expected", [("0", 0), ("10", 10), ("57535", 57535)])
def test_a_valid_offset_is_accepted(raw, expected):
    assert module.parse_offset(raw) == expected


def test_an_offset_beyond_the_range_is_red_and_names_the_port_that_overflows():
    """R5.2: el mayor de los cuatro puertos base es 8000, así que el techo es 57535."""
    with pytest.raises(module.OffsetError) as raised:
        module.parse_offset("57536")
    message = str(raised.value)
    assert "65536" in message
    assert "backend" in message


# ── Aritmética: un solo sumando para los cuatro puertos (R1.4) ──────────────────────────────


@pytest.mark.parametrize("offset", [0, 1, 10, 57535])
def test_the_four_ports_share_a_single_addend(offset):
    assert module.host_ports(offset) == {
        "postgres": 5432 + offset,
        "redis": 6379 + offset,
        "backend": 8000 + offset,
        "frontend": 3000 + offset,
    }


def test_only_those_four_services_publish():
    """R2.3: `worker`, `beat` y `migrate` no aparecen en la tabla, así que no publican nada."""
    assert {pub.service for pub in module.SERVICES} == {
        "postgres",
        "redis",
        "backend",
        "frontend",
    }


def test_the_datastores_are_bound_to_loopback_and_the_app_is_not():
    """R2.1/R2.2: la postura de red se conserva desplazada, y es un dato de la tabla."""
    interfaces = {pub.service: pub.host_ip for pub in module.SERVICES}
    assert interfaces == {
        "postgres": module.LOOPBACK,
        "redis": module.LOOPBACK,
        "backend": None,
        "frontend": None,
    }


# ── `generate`: el overlay, con números literales y regenerado siempre (D2, D5) ─────────────


def test_the_overlay_carries_the_four_literal_mappings_with_their_interface():
    """R1.1/R1.4/R2.1/R2.2: prefijo de loopback en los datastores y ninguno en la app."""
    text = module.overlay_text(10)
    assert 'ports: !override ["127.0.0.1:5442:5432"]' in text
    assert 'ports: !override ["127.0.0.1:6389:6379"]' in text
    assert 'ports: !override ["8010:8000"]' in text
    assert 'ports: !override ["3010:3000"]' in text


def test_the_overlay_never_contains_an_interpolation():
    """D2: con `--no-interpolate` un `${...}` llega como cadena cruda y solo permitiría
    comparar plantillas; la aserción previa a levantar tiene que ser numérica."""
    assert "$" not in module.overlay_text(10)


def test_the_overlay_is_written_under_dot_make_and_is_not_an_override_file(tmp_path):
    """D5/D1: la ruta es la que mantiene el overlay fuera de lo que Compose descubre solo."""
    written = module.generate(10, root=tmp_path)
    assert written == tmp_path / ".make" / "docker-compose.offset.yml"
    assert written.read_text(encoding="utf-8") == module.overlay_text(10)


def test_generating_twice_with_the_same_offset_leaves_the_file_byte_identical(tmp_path):
    """D5: función pura de `n`, así que Compose no recrea nada en el segundo `make up`."""
    first = module.generate(10, root=tmp_path).read_bytes()
    second = module.generate(10, root=tmp_path).read_bytes()
    assert first == second


def test_generating_with_another_offset_replaces_the_previous_one(tmp_path):
    """Riesgo «un `.make/` viejo de otro `n`»: no hay ruta por la que se lea uno viejo."""
    module.generate(10, root=tmp_path)
    written = module.generate(20, root=tmp_path).read_text(encoding="utf-8")
    assert "8020:8000" in written
    assert "8010:8000" not in written


def test_the_overlay_declares_only_ports_and_only_for_the_four_services(tmp_path):
    """Q3: el overlay se queda estrictamente en `ports`.

    Ensancharlo —inyectar `FRONTEND_BASE_URL`, por ejemplo— rompería la aserción de igualdad de
    `check` y desdibujaría la historia de R2 en dos sitios. Se comprueba sobre las líneas de
    contenido y **sin PyYAML**: el comando del workflow es
    `uv run --no-project --with 'pytest==9.1.1' …`, así que una dependencia de más aquí sería un
    test que se salta en CI en vez de uno que falla.
    """
    written = module.generate(7, root=tmp_path).read_text(encoding="utf-8")
    body = [
        line
        for line in written.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert body[0] == "services:"
    assert [line for line in body[1:] if line.startswith("  ") and line.endswith(":")] == [
        f"  {name}:" for name in ("postgres", "redis", "backend", "frontend")
    ]
    assert all(
        line.startswith("    ports: !override [") for line in body[1:] if line.startswith("    ")
    )
    assert len(body) == 1 + 2 * len(module.SERVICES)


# ── `check`: la aserción de la configuración resuelta (D7, R6.1) ────────────────────────────
#
# Sobre modelos de `config` fabricados, con la forma **medida** con Compose 5.1.1 en este
# worktree: `published` es cadena, `target` es entero, y `host_ip` está **ausente** —no `null`—
# cuando el mapeo no lleva prefijo de interfaz.


def mapping(target, published, host_ip=None):
    entry = {"mode": "ingress", "protocol": "tcp", "target": target, "published": published}
    if host_ip is not None:
        entry["host_ip"] = host_ip
    return entry


def shifted_model(offset=10, **overrides):
    """El modelo que produce el overlay generado, con los desvíos que pida cada caso."""
    services = {
        "postgres": {"ports": [mapping(5432, str(5432 + offset), module.LOOPBACK)]},
        "redis": {"ports": [mapping(6379, str(6379 + offset), module.LOOPBACK)]},
        "migrate": {},
        "backend": {"ports": [mapping(8000, str(8000 + offset))]},
        "worker": {},
        "beat": {},
        "frontend": {"ports": [mapping(3000, str(3000 + offset))]},
    }
    services.update(overrides)
    return {"name": "autohostai", "services": services}


def test_the_expected_shifted_model_passes_the_assertion():
    module.assert_config(shifted_model(10), 10)


def test_the_same_model_is_red_for_another_offset():
    """Igualdad **numérica** y no de plantilla: es lo que D2 compra al generar literales."""
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(shifted_model(10), 20)
    assert "8010" in str(raised.value)


def test_an_override_that_did_not_apply_is_red_naming_both_mappings():
    """Si `!override` no se aplicó, la fusión CONCATENA y salen los dos mapeos."""
    model = shifted_model(10)
    model["services"]["backend"]["ports"].append(mapping(8000, "8000"))
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(model, 10)
    message = str(raised.value)
    assert "backend" in message
    assert "8000" in message


def test_a_missing_service_is_red_by_set_equality():
    """Igualdad y no contención: un `frontend` que no publica no puede pasar por conforme."""
    model = shifted_model(10)
    del model["services"]["frontend"]["ports"]
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(model, 10)
    assert "frontend" in str(raised.value)


@pytest.mark.parametrize("service", ["postgres", "redis"])
def test_a_datastore_off_loopback_is_red(service):
    """R2.1: ese Redis guarda los contadores del throttle de login y corre sin `requirepass`."""
    model = shifted_model(10)
    del model["services"][service]["ports"][0]["host_ip"]
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(model, 10)
    assert service in str(raised.value)


@pytest.mark.parametrize("service", ["postgres", "redis"])
def test_a_datastore_on_another_interface_is_red(service):
    model = shifted_model(10)
    entry = model["services"][service]["ports"][0]
    entry["host_ip"] = "0.0.0.0"
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(model, 10)
    assert service in str(raised.value)


@pytest.mark.parametrize("service", ["backend", "frontend"])
def test_the_app_bound_to_loopback_is_red(service):
    """R2.2: son estos dos los que se abren desde un móvil de la LAN; acotarlos mata el change."""
    model = shifted_model(10)
    model["services"][service]["ports"][0]["host_ip"] = module.LOOPBACK
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(model, 10)
    assert service in str(raised.value)


def test_an_extra_service_with_a_ports_key_is_red_even_when_empty():
    """R2.3: la clave, no el mapeo. Un `ports: []` no produce entradas y pasaría la igualdad."""
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(shifted_model(10, worker={"ports": []}), 10)
    assert "worker" in str(raised.value)


def test_an_extra_service_that_publishes_is_red():
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(
            shifted_model(10, beat={"ports": [mapping(5555, "5555")]}), 10
        )
    assert "beat" in str(raised.value)


def test_a_raw_string_mapping_is_red_and_never_normalized_by_hand():
    """Un mapeo con interpolación llega como cadena cruda: es la limitación deliberada de D2."""
    model = shifted_model(10)
    model["services"]["backend"]["ports"] = ["${BACKEND_HOST_PORT}:8000"]
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(model, 10)
    assert "backend" in str(raised.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"services": []},
        {"services": {"backend": "no soy un objeto"}},
        [],
        "",
    ],
)
def test_a_model_that_describes_nothing_is_red_and_never_taken_as_conforming(payload):
    """Un `config` con éxito que devuelve `{}` no es «ningún servicio»: es rojo."""
    with pytest.raises(module.OffsetError):
        module.assert_config(payload, 10)


def test_ports_that_are_not_a_list_are_red():
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(shifted_model(10, backend={"ports": "8010:8000"}), 10)
    assert "backend" in str(raised.value)


# `U+202E` (RIGHT-TO-LEFT OVERRIDE) y `\x1b`: `json.dumps(ensure_ascii=False)` deja pasar los
# codepoints bidi y de formato tal cual, así que un cuerpo de servicio hostil podría reordenar
# cómo se lee el mensaje en el terminal de quien lo recibe. CR y LF sí los neutraliza `json`, y
# por eso no sirven para probar esto.
HOSTILE = "‮todo correcto\x1b[0m"


@pytest.mark.parametrize(
    "body",
    [HOSTILE, {"ports": HOSTILE}],
    ids=["servicio-que-no-es-objeto", "ports-que-no-es-lista"],
)
def test_foreign_model_content_never_reaches_the_terminal_unescaped(body):
    """Los dos caminos de `observed_labels` que nombran un valor ajeno tienen que escaparlo.

    Referente: la lista negra heredada —*«de `stderr`, solo su primera línea, saneada y
    acotada»*— y el contrato de `escape()`, que el resto del script ya cumple en `label_of`.
    """
    with pytest.raises(module.OffsetError) as raised:
        module.assert_config(shifted_model(10, worker=body), 10)
    message = str(raised.value)
    assert "‮" not in message
    assert "\x1b" not in message
    assert "\\u202e" in message


# ── `check`: el sondeo de binds, antes de levantar (D7, R5.3) ───────────────────────────────


def a_free_offset():
    """Un desplazamiento cuyos cuatro puertos están libres **ahora mismo**.

    Se busca en vez de calcularlo desde un puerto efímero, que en macOS vive en 49152-65535 y
    llevaría el puerto de `backend` fuera de rango. Hay TOCTOU entre encontrarlo y usarlo, y
    está aceptado por escrito en el diseño.
    """
    for offset in range(20000, 20500):
        if not any(
            module.occupied(pub.host_ip or module.ALL_INTERFACES, pub.target + offset)
            for pub in module.SERVICES
        ):
            return offset
    pytest.skip("no se encontró un desplazamiento con los cuatro puertos libres")


def test_a_free_offset_passes_the_probe():
    module.probe(a_free_offset(), excluded=frozenset())


def test_an_occupied_port_aborts_naming_the_port_and_the_service():
    """R5.3: el síntoma que esto evita es un Compose que falla a medio levantar."""
    offset = a_free_offset()
    port = 5432 + offset
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", port))
        taken.listen(1)
        with pytest.raises(module.OffsetError) as raised:
            module.probe(offset, excluded=frozenset())
    message = str(raised.value)
    assert str(port) in message
    assert "postgres" in message


def test_a_port_this_very_project_already_publishes_is_excluded():
    """`make up` tiene que seguir siendo idempotente sobre un stack ya levantado con el mismo
    `n`: sus propios puertos no son un choque, son el mismo stack."""
    offset = a_free_offset()
    port = 5432 + offset
    with socket.socket() as taken:
        taken.bind(("127.0.0.1", port))
        taken.listen(1)
        module.probe(offset, excluded=frozenset({port}))


def test_the_probe_does_not_reuse_addresses():
    """Riesgo escrito en el diseño: con `SO_REUSEADDR` un bind puede tener éxito donde Docker
    fallará. Sin él, un puerto en `TIME_WAIT` se reporta ocupado sin estarlo — falla hacia
    abortar, que es la dirección correcta.

    Se comprueba por **AST** y no sobre el texto del fichero, y la diferencia no es de estilo:
    el comentario de cabecera del sondeo *nombra* `SO_REUSEADDR` para explicar por qué no se
    activa, así que cualquier aserción textual queda satisfecha por esa explicación y no por el
    código — un `setsockopt(...)` reintroducido pasaría inadvertido. En el árbol, en cambio,
    los comentarios no existen.
    """
    tree = ast.parse(SCRIPT.read_text())
    offenders = [
        ast.unparse(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "setsockopt"
    ]
    assert not offenders, (
        f"volvió un `setsockopt` al sondeo ({offenders}): con `SO_REUSEADDR` un bind puede "
        "tener éxito donde Docker fallará, y esa dirección de fallo es la mala."
    )
    assert "SO_REUSEADDR" not in string_literals(tree)


# ── `show`: el desplazamiento se DERIVA del stack vivo, no de un fichero (D8, R4.2) ─────────


def ps_line(service, url=None, published=None, target=None, state="running"):
    publishers = None
    if published is not None:
        publishers = [
            {
                "URL": url,
                "TargetPort": target,
                "PublishedPort": published,
                "Protocol": "tcp",
            }
        ]
    return json.dumps({"Service": service, "State": state, "Publishers": publishers})


def ps_output(offset):
    return "\n".join(
        ps_line(
            pub.service,
            pub.host_ip or "0.0.0.0",
            pub.target + offset,
            pub.target,
        )
        for pub in module.SERVICES
    )


def test_show_derives_the_offset_of_a_shifted_stack():
    report = module.render_show(module.parse_ps(ps_output(10)))
    assert "PORT_OFFSET=10" in report
    assert "5442" in report and "6389" in report and "8010" in report and "3010" in report


def test_show_derives_zero_for_an_unshifted_stack():
    report = module.render_show(module.parse_ps(ps_output(0)))
    assert "PORT_OFFSET=0" in report


def test_a_stopped_stack_is_reported_and_is_not_an_error():
    report = module.render_show(module.parse_ps(""))
    assert "levantado" in report


def test_a_stack_that_publishes_nothing_is_reported_and_is_not_an_error():
    """Es el defecto de un worktree enlazado desde `worktree-parallel-stack`."""
    lines = "\n".join(ps_line(pub.service) for pub in module.SERVICES)
    report = module.render_show(module.parse_ps(lines))
    assert "sin publicar" in report


def test_incoherent_offsets_are_reported_and_no_single_number_is_invented():
    lines = "\n".join(
        [
            ps_line("postgres", "127.0.0.1", 5442, 5432),
            ps_line("redis", "127.0.0.1", 6389, 6379),
            ps_line("backend", "0.0.0.0", 8020, 8000),
            ps_line("frontend", "0.0.0.0", 3010, 3000),
        ]
    )
    report = module.render_show(module.parse_ps(lines))
    assert not re.search(r"PORT_OFFSET=\d", report)
    assert "incoherente" in report
    assert "8020" in report


def test_ps_accepts_both_the_json_array_and_the_json_lines_shape():
    """Compose 5.1.1 emite una línea por contenedor; versiones anteriores emiten un array."""
    lines = ps_output(10)
    as_array = json.dumps([json.loads(line) for line in lines.splitlines()])
    assert module.parse_ps(lines) == module.parse_ps(as_array)


def test_a_publisher_without_a_host_port_is_not_counted_as_published():
    """Compose emite entradas sin puerto de host —`PublishedPort` ausente o `0`— para puertos
    expuestos que no se publican. Contarlas haría que `make ports` informara un `0` efectivo, y
    que el conjunto de exclusión del sondeo se llenara de puertos que nadie tomó."""
    rows = module.parse_ps(
        "\n".join(
            [
                json.dumps(
                    {
                        "Service": "backend",
                        "State": "running",
                        "Publishers": [
                            {"URL": "", "TargetPort": 8000, "PublishedPort": 0, "Protocol": "tcp"},
                            {"URL": "", "TargetPort": 9000, "Protocol": "tcp"},
                        ],
                    }
                )
            ]
        )
    )
    assert module.live_ports(rows) == {}


def test_unparseable_ps_output_is_red_with_its_own_message():
    with pytest.raises(module.OffsetError):
        module.parse_ps("{no soy json")


# ── `announce`: los cuatro puertos efectivos, sin deducirlos (D4, R4.1, Q1) ─────────────────


def test_the_announcement_enumerates_the_four_effective_ports():
    text = module.announce(10, worktree=True)
    for port in ("5442", "6389", "8010", "3010"):
        assert port in text


def test_the_announcement_of_a_worktree_says_so():
    assert "worktree enlazado" in module.announce(10, worktree=True)


def test_the_announcement_of_the_main_worktree_warns_that_it_moves_the_existing_stack():
    """Riesgo escrito: en el principal desplazar no crea un segundo stack, mueve el que hay."""
    text = module.announce(10, worktree=False)
    assert "principal" in text
    assert "mueve" in text


def test_the_announcement_tells_how_to_reach_it_from_a_phone_without_computing_the_ip():
    """Q1: resolver la IP es específico de plataforma y falla de formas que se leen como un
    bug del stack, así que se dice qué hay que hacer y no se calcula."""
    text = module.announce(10, worktree=True)
    assert "IP" in text
    assert "3010" in text


def test_the_announcement_never_carries_a_value_from_the_environment(monkeypatch):
    monkeypatch.setenv("PORT_OFFSET", "10")
    monkeypatch.setenv("POSTGRES_PASSWORD", "un-secreto-de-dev")
    assert "un-secreto-de-dev" not in module.announce(10, worktree=True)


# ── Espejo de la lista negra, sobre el propio código de este script (D4) ────────────────────
#
# Es el mismo mecanismo que ya protege a `compose-ports.py` y a `compose-stacks.py`, acotado a
# **este** fichero, así que no hay conflicto entre las tres suites. Va por AST y no por texto a
# propósito: el docstring de cabecera *nombra* lo prohibido para explicar por qué lo está, y un
# `grep` sobre el texto convertiría esa explicación en un falso positivo — que es presión para
# documentar peor.


def string_literals(tree):
    """Las cadenas del AST **sin** los docstrings: solo lo que puede llegar a un `argv`."""
    docstrings = {
        ast.get_docstring(node, clean=False)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]


def test_config_is_only_ever_invoked_through_config_base():
    """D4: las dos banderas no dependen de que quien añada una invocación se acuerde.

    Sin ellas, `config` materializa el `.env` entero resuelto —`JWT_SECRET_KEY`,
    `POSTGRES_PASSWORD`, `ENCRYPTION_KEY`— en la salida que este script inspecciona.
    """
    tree = ast.parse(SCRIPT.read_text())
    literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "config"
    ]
    assert len(literals) == 1, (
        f"la cadena `config` aparece {len(literals)} veces en `compose-offset.py`: la "
        "invocación tiene que construirse siempre desde `CONFIG_BASE`."
    )
    base = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(target, "id", None) == "CONFIG_BASE" for target in node.targets)
    )
    assert literals[0] in list(ast.walk(base)), "`config` se invoca fuera de `CONFIG_BASE`"
    flags = [node.value for node in ast.walk(base) if isinstance(node, ast.Constant)]
    assert "--no-interpolate" in flags and "--no-env-resolution" in flags, flags


# Lo que la lista negra prohíbe **como comando**, y por tanto solo puede llegar al script como
# un elemento de `argv`: una cadena literal.
BANNED_ARGUMENTS = ("inspect", "2>/dev/null", "-c")


@pytest.mark.parametrize("banned", BANNED_ARGUMENTS)
def test_no_banned_argument_can_reach_an_argv(banned):
    """`docker inspect` sin `--format` vuelca `.Config.Env`, y `-c` sería invocar un shell."""
    offenders = [
        value for value in string_literals(ast.parse(SCRIPT.read_text())) if value == banned
    ]
    assert not offenders, (
        f"la cadena `{banned}` aparece como argumento en `compose-offset.py`. Ver la lista "
        "negra del docstring de cabecera: cada entrada tiene su motivo medido."
    )


def test_the_subprocess_calls_never_use_the_shell_nor_copy_the_environment():
    """El entorno del hijo se construye por lista blanca en `clean_env()`, no desinfectando.

    Y esto es además la demostración de R6.3 por el lado de este script: un `PORT_OFFSET`
    exportado en la shell no puede viajar a ningún hijo.
    """
    tree = ast.parse(SCRIPT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                assert not (
                    keyword.arg == "shell"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ), "`shell=True` volvió al código: lista de argumentos, siempre"
        if isinstance(node, ast.Attribute) and node.attr == "copy":
            source = ast.unparse(node)
            assert "environ" not in source, (
                f"`{source}` volvió al código: el entorno del hijo se construye por lista "
                "blanca en `clean_env()`, no copiando y quitando claves."
            )


def test_the_child_environment_is_built_by_whitelist():
    """`clean_env()` devuelve `PATH` y nada más; nada del entorno del padre se hereda."""
    assert set(module.clean_env()) == {"PATH"}


# ── La frontera con la guardia de puertos: dónde vive el overlay y qué exime ella ───────────
#
# Este bloque no prueba **este** script: prueba que el acuerdo con `compose-ports-guard` sigue
# en pie. La invariancia de la guardia es un resultado del diseño —su vista y su veredicto no se
# tocan— y lo que la sostiene son exactamente dos hechos: que el overlay no está en lo que
# Compose descubre por sí solo, y que la exención de la guardia no se ensanchó para dar cabida a
# puertos desplazados. Si alguien rompe cualquiera de los dos, esto tiene que romperse con él.


def test_the_generated_overlay_is_outside_what_compose_discovers_by_itself():
    """Si esto se rompe, un `docker compose` desnudo empezaría a ver el desplazamiento, y el
    veredicto de la guardia dejaría de ser función solo del repositorio."""
    assert module.OFFSET_FILE.parent == Path(".make")
    assert module.OFFSET_FILE.name != "docker-compose.override.yml"
    assert module.OFFSET_FILE.name != "compose.override.yml"
    assert str(module.OFFSET_FILE.parent) != "."


def test_the_offset_directory_is_ignored_by_git():
    assert ".make/" in (ROOT / ".gitignore").read_text().splitlines()


# ── El cableado del `Makefile`, sobre `make -n` y sin levantar nada ─────────────────────────
#
# Estos tests existen porque su ausencia costó dos defectos reales, los dos encontrados por el
# panel y ninguno por la suite: `PORT_OFFSET=00` se colaba por la rama del desplazamiento —y
# generaba un overlay que publica los puertos SIN desplazar, la colisión exacta que este change
# evita—, y `PORT_OFFSET='1 0'` se convertía en `1` antes de que nadie lo validara. Las dos cosas
# vivían en la normalización del `Makefile`, que no tenía ninguna red.
#
# `make -n` no ejecuta nada: imprime las recetas. Así que esto no toca Docker, no levanta stacks y
# es seguro en una máquina con otras sesiones vivas. `IS_WORKTREE` se pasa por línea de comandos
# para no depender de dónde corra la suite.


def make_dry_run(port_offset, is_worktree):
    return subprocess.run(
        ["make", "-n", "up", f"IS_WORKTREE={is_worktree}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PORT_OFFSET": port_offset},
    )


def compose_invocation(result):
    """La línea que de verdad levantaría el stack: con qué ficheros habla Compose."""
    lines = [line for line in result.stdout.splitlines() if " up -d --build" in line]
    assert len(lines) == 1, result.stdout
    return lines[0].strip()


OFFSET_FILES = "-f docker-compose.yml -f .make/docker-compose.offset.yml"
WORKTREE_FILES = "-f docker-compose.yml -f docker-compose.worktree.yml"


@pytest.mark.parametrize("raw", ["", "0", "00", "000"])
def test_zero_and_empty_never_take_the_offset_branch(raw):
    """R3.3: `0` es «no desplaces», no «desplaza cero» — y `00` es cero igual.

    Si esto se rompe, un worktree enlazado genera un overlay con los puertos base y choca con el
    stack del principal, que es exactamente lo que el desplazamiento existe para no hacer.
    """
    result = make_dry_run(raw, "yes")
    assert result.returncode == 0, result.stderr
    assert compose_invocation(result) == f"docker compose {WORKTREE_FILES} up -d --build"


def test_the_main_worktree_without_offset_invokes_compose_naked():
    """R3.2: lo que Compose descubre por sí solo tiene que seguir siendo la postura real."""
    result = make_dry_run("", "")
    assert result.returncode == 0, result.stderr
    assert compose_invocation(result) == "docker compose up -d --build"


@pytest.mark.parametrize("is_worktree", ["yes", ""], ids=["worktree", "principal"])
def test_the_offset_branch_does_not_look_at_whether_this_is_a_worktree(is_worktree):
    """R1.3: el principal también puede apartarse, en vez de obligar a bajarlo."""
    result = make_dry_run("10", is_worktree)
    assert result.returncode == 0, result.stderr
    assert compose_invocation(result) == f"docker compose {OFFSET_FILES} up -d --build"


def test_the_offset_branch_runs_generate_check_and_announce_before_bringing_anything_up():
    """D7: el orden es validar -> generar -> asertar -> sondear -> anunciar -> levantar, y TODO
    antes de `up`. Sondear después de levantar es el síntoma ilegible que R5.3 evita."""
    result = make_dry_run("10", "yes")
    body = result.stdout.splitlines()
    positions = {}
    for step in ("generate", "check", "announce"):
        positions[step] = next(
            index
            for index, line in enumerate(body)
            if f"compose-offset.py {step}" in line
        )
    up_at = next(index for index, line in enumerate(body) if " up -d --build" in line)
    assert positions["generate"] < positions["check"] < positions["announce"] < up_at


@pytest.mark.parametrize(
    "raw",
    ["-1", "abc", "1 0", "10 20", "0x10", '1"; echo INYECTADO; "', " 10", "10 "],
    ids=[
        "negativo",
        "texto",
        "cero-como-palabra",
        "dos-numeros",
        "hexadecimal",
        "inyeccion",
        "espacio-delante",
        "espacio-detras",
    ],
)
def test_a_value_that_is_not_an_integer_aborts_at_parse_time_naming_it(raw):
    """R5.1, y la regla de la cabecera del `Makefile` para lo que no escribe una persona.

    `make` interpola la variable en el TEXTO de la receta, así que entrecomillarla no basta: un
    valor con una comilla dentro la cierra. La comprobación tiene que ocurrir antes de que el
    valor llegue a ninguna receta, y el valor que se nombra tiene que ser el que se recibió, no
    uno que la normalización haya mutado por el camino.
    """
    result = make_dry_run(raw, "yes")
    assert result.returncode != 0, result.stdout
    # `raw` entero y NO `raw.strip()`: con la forma laxa, los casos de espacio delante/detrás
    # pasaban igual de verdes si el mensaje nombraba el valor ya normalizado, que es justo la
    # mitad de R5.1 que aquí se quiere fijar — «nombrando el valor recibido», no uno mutado.
    assert raw in result.stderr
    assert "INYECTADO" not in result.stdout


def test_a_shell_expansion_smuggled_through_the_environment_never_runs(tmp_path):
    """El agujero que `$(value …)` cierra, y que entrecomillar no cerraba.

    Para `make`, una variable de entorno es de expansión diferida: **nombrarla la expande**, así
    que un `$(shell …)` dentro de su texto se ejecuta al evaluar la asignación —y esa asignación
    es de nivel superior, o sea que corre para cualquier target—. `$(value …)` devuelve el texto
    sin expandir, de modo que la carga llega entera a la puerta y se rechaza sin ejecutarse.

    Se comprueba por **efecto secundario observable** (un fichero que aparece o no) y no por lo
    que imprima nadie: la salida pasa por un shell que hace su propia sustitución de `$(…)` y
    miente sobre lo que `make` hizo.
    """
    marker = tmp_path / "efecto-secundario.txt"
    payload = f"1$(shell touch {marker})"
    for target in ("up", "ports", "down", "check-compose-ports"):
        result = subprocess.run(
            ["make", "-n", target],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={**os.environ, "PORT_OFFSET": payload},
        )
        assert not marker.exists(), f"`make {target}` ejecutó el $(shell) de PORT_OFFSET"
        assert result.returncode != 0, f"`make {target}` aceptó {payload!r}"
        assert "PORT_OFFSET" in result.stderr


@pytest.mark.parametrize(
    "raw", ["1$(echo X)", "1${X}", "1$$(id)"], ids=["make-var", "llaves", "doble-dolar"]
)
def test_a_value_carrying_a_dollar_is_rejected_and_never_silently_mutated(raw):
    """R5.1: `$(echo X)` es una referencia a una variable de `make` inexistente, así que expandir
    el valor lo convertía en `1` — y el valor recibido, que R5.1 manda nombrar, no llegaba a
    nadie. Con `$(value …)` llega crudo y se rechaza."""
    result = make_dry_run(raw, "yes")
    assert result.returncode != 0, result.stdout
    assert "PORT_OFFSET" in result.stderr


def test_the_guard_target_never_goes_through_compose():
    """R6.3: si `check-compose-ports` pasara por `$(COMPOSE)`, en un worktree cargaría el overlay
    que retira los puertos y la guardia daría verde sin haber comprobado nada — y con
    desplazamiento vería los puertos desplazados en vez de la postura del repositorio."""
    result = subprocess.run(
        ["make", "-n", "check-compose-ports"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**os.environ, "PORT_OFFSET": "10"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "python3 scripts/compose-ports.py"


def test_the_guard_exemption_was_not_widened_to_make_room_for_shifted_ports():
    """Un stack desplazado publica `backend:8000+n` y `frontend:3000+n`. La salida NO fue
    ensanchar `EXEMPT` —eso convertiría la exención de par literal en exención por servicio—,
    sino dejar el overlay fuera de la vista de la guardia."""
    guard = importlib.util.spec_from_file_location("compose_ports", GUARD)
    loaded = importlib.util.module_from_spec(guard)
    assert guard.loader is not None
    guard.loader.exec_module(loaded)
    assert loaded.EXEMPT == frozenset({("backend", "8000"), ("frontend", "3000")})
