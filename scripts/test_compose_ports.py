"""Suite de `compose-ports.py`.

Obligación de método de este change (R6.3): **la guardia se demuestra en rojo**. Esta misma
comprobación pasó verde cinco veces siendo eludible, así que un test que solo asierta el verde
no prueba nada. El censo de vías de elusión son **nueve** —(a)-(h) de
`sdd/roadmap/compose-ports-guard.md` más la (i) que midió `design.md` D2— y cada una lleva su
caso, marcado con `vía (x)` en el nombre o en el docstring del test.
"""

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "compose_ports",
    Path(__file__).with_name("compose-ports.py"),
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


def model(**services):
    """Un modelo de Compose con los servicios que se le pasen, sin nada más."""
    return {"name": "autohostai", "services": services}


def service(**keys):
    return dict(keys)


def mapping(target, published=None, host_ip=None, mode="ingress", protocol="tcp"):
    """Un mapeo con la forma **medida** con Compose 5.1.1: `published` cadena, `host_ip` ausente.

    Ausente, no `null`: es el dato que corrige a la entrada de roadmap, y por eso el default de
    `host_ip` aquí es no poner la clave. Un `host_ip: null` explícito se escribe a mano en el
    caso que lo prueba.
    """
    entry = {"mode": mode, "protocol": protocol, "target": target}
    if published is not None:
        entry["published"] = published
    if host_ip is not None:
        entry["host_ip"] = host_ip
    return entry


# ── Las seis reglas de decisión, cada una con su caso en rojo ──────────────────────────────
#
# Lista literal y no un `set`/`frozenset`: el id del test tiene que ser estable entre workers,
# porque la suite corre en paralelo en CI (`steering/testing.md`).
RED_CASES = [
    (
        "network_mode-host-sin-ports",
        # vía (b): publica todo sin generar NINGUNA entrada `ports`, así que un bucle sobre
        # `ports` lo trata como conforme. Medido: el servicio sale sin la clave.
        model(postgres=service(network_mode="host")),
        module.NETWORK_MODE,
        "postgres",
    ),
    (
        "network_mode-desconocido",
        model(postgres=service(network_mode="container:otro")),
        module.NETWORK_MODE,
        "postgres",
    ),
    (
        "network_mode-no-hasheable",
        model(postgres=service(network_mode=["host"])),
        module.NETWORK_MODE,
        "postgres",
    ),
    (
        "puerto-extra-en-servicio-exento",
        # vía (c): la exención cubre el par, no el servicio (R3.2).
        model(
            backend=service(
                ports=[mapping(8000, "8000"), mapping(9229, "9229")],
            )
        ),
        module.OFF_LOOPBACK,
        "backend",
    ),
    (
        "mismo-puerto-en-servicio-no-exento",
        # R3.3: la exención cubre el par, no el puerto.
        model(worker=service(ports=[mapping(8000, "8000")])),
        module.OFF_LOOPBACK,
        "worker",
    ),
    (
        "mapeo-interpolado-es-cadena",
        # vía (i), medida en `design.md` D2: con `--no-interpolate` un mapeo que contiene
        # `${...}` NO se normaliza y sale como cadena cruda. Una guardia que asuma objeto
        # revienta con `AttributeError`; una que lo envuelva en `try/except` lo deja pasar.
        model(postgres=service(ports=["${BIND}:5432:5432"])),
        module.NOT_NORMALIZED,
        "postgres",
    ),
    (
        "mapeo-interpolado-solo-el-puerto",
        model(postgres=service(ports=["127.0.0.1:${PGPORT}:5432"])),
        module.NOT_NORMALIZED,
        "postgres",
    ),
    (
        "objeto-sin-published",
        # R5.1: `ports: ["5432"]` y `{target: 6379, mode: ingress}` salen sin `published` ni
        # `host_ip`, y Docker las publica en un puerto EFÍMERO y en todas las interfaces.
        model(redis=service(ports=[mapping(6379)])),
        module.NO_PUBLISHED,
        "redis",
    ),
    (
        "objeto-sin-published-en-servicio-exento",
        # El mismo caso dentro de un servicio exento: sin puerto de host no hay par que
        # eximir, así que la exención no puede alcanzarlo.
        model(backend=service(ports=[mapping(8000)])),
        module.NO_PUBLISHED,
        "backend",
    ),
    (
        "host_ip-ausente",
        model(postgres=service(ports=[mapping(5432, "5432")])),
        module.OFF_LOOPBACK,
        "postgres",
    ),
    (
        "host_ip-null",
        model(postgres=service(ports=[{"target": 5432, "published": "5432", "host_ip": None}])),
        module.OFF_LOOPBACK,
        "postgres",
    ),
    (
        "host_ip-todas-las-interfaces",
        model(postgres=service(ports=[mapping(5432, "5432", "0.0.0.0")])),
        module.OFF_LOOPBACK,
        "postgres",
    ),
    (
        "host_ip-loopback-ipv6",
        # Limitación conocida y deliberada (`design.md`, Risks): `::1` es loopback y por tanto
        # seguro, pero no es la postura escrita. Rojo, y que una persona ensanche la regla a
        # sabiendas. Este test fija el veredicto para que nadie lo «arregle» sin decidirlo.
        model(postgres=service(ports=[mapping(5432, "5432", "::1")])),
        module.OFF_LOOPBACK,
        "postgres",
    ),
    (
        "published-rango",
        # Un rango nunca pertenece a `EXEMPT`, que son pares con un puerto concreto, así que
        # cae por el camino normal sin código propio. (Compose 5.1.1 expande el rango en una
        # entrada por puerto —medido—, pero la regla no depende de que lo haga.)
        model(backend=service(ports=[mapping(8000, "8000-8010")])),
        module.OFF_LOOPBACK,
        "backend",
    ),
    (
        "published-no-es-cadena",
        # Si Compose dejara de dar `published` como cadena, `('backend', 8000)` no está en
        # `EXEMPT` y el mapeo cae al camino normal: rojo. La dirección del fallo es la correcta.
        model(backend=service(ports=[{"target": 8000, "published": 8000}])),
        module.OFF_LOOPBACK,
        "backend",
    ),
    (
        "ports-no-es-lista",
        model(postgres=service(ports={"target": 5432})),
        module.PORTS_NOT_LIST,
        "postgres",
    ),
    (
        "servicio-no-es-objeto",
        model(postgres="alpine"),
        module.SERVICE_NOT_OBJECT,
        "postgres",
    ),
]


@pytest.mark.parametrize(
    ("case", "payload", "rule", "service_name"),
    RED_CASES,
    ids=[case[0] for case in RED_CASES],
)
def test_the_guard_is_red_for(case, payload, rule, service_name):
    found = module.violations(payload)
    assert found, f"{case}: la guardia dio verde sobre un modelo que infringe la postura"
    assert rule in {violation.rule for violation in found}, found
    assert service_name in {violation.service for violation in found}, found


# ── Y el verde, que solo vale sobre lo que de verdad está acotado ──────────────────────────

CONFORMING = model(
    postgres=service(ports=[mapping(5432, "5432", module.LOOPBACK)]),
    redis=service(ports=[mapping(6379, "6379", module.LOOPBACK)]),
    migrate=service(),
    backend=service(ports=[mapping(8000, "8000")]),
    worker=service(),
    beat=service(),
    frontend=service(ports=[mapping(3000, "3000")]),
)


def test_the_repository_posture_is_green():
    """El modelo que este repositorio produce hoy: 7 servicios, 4 mapeos, ninguna infracción."""
    assert module.violations(CONFORMING) == []


@pytest.mark.parametrize("mode", ["bridge", "none"])
def test_the_whitelisted_network_modes_are_green(mode):
    assert module.violations(model(postgres=service(network_mode=mode))) == []


def test_a_service_without_ports_is_green_by_absence():
    assert module.violations(model(worker=service(image="alpine"))) == []


def test_the_two_exempt_pairs_are_green():
    payload = model(
        backend=service(ports=[mapping(8000, "8000")]),
        frontend=service(ports=[mapping(3000, "3000")]),
    )
    assert module.violations(payload) == []


def test_violations_are_ordered_by_service_and_by_declaration():
    """Orden determinista: mismo modelo, misma salida, sea cual sea el orden del diccionario."""
    payload = model(
        redis=service(ports=[mapping(6379, "6379"), mapping(6380, "6380")]),
        beat=service(network_mode="host"),
    )
    found = module.violations(payload)
    assert [(v.service, v.rule) for v in found] == [
        ("beat", module.NETWORK_MODE),
        ("redis", module.OFF_LOOPBACK),
        ("redis", module.OFF_LOOPBACK),
    ]
    assert [v.detail for v in found][1:] == [
        module.dump(mapping(6379, "6379")),
        module.dump(mapping(6380, "6380")),
    ]


def test_a_service_with_both_a_bad_network_mode_and_a_bad_mapping_reports_both():
    payload = model(postgres=service(network_mode="host", ports=[mapping(5432, "5432")]))
    assert {v.rule for v in module.violations(payload)} == {
        module.NETWORK_MODE,
        module.OFF_LOOPBACK,
    }


# ── La forma del modelo: un `config` con éxito que no describe nada es rojo, no vacío ──────


@pytest.mark.parametrize(
    "payload",
    [{}, [], "services", {"services": []}],
    ids=["objeto-vacio", "lista", "cadena", "services-no-objeto"],
)
def test_a_successful_config_that_describes_nothing_is_an_error(payload):
    """vía (h): `config` sale con éxito devolviendo `{}` y un bucle sobre nada da verde."""
    with pytest.raises(module.GuardError):
        module.violations(payload)


def test_an_empty_services_map_yields_no_violations_and_is_caught_by_the_inventory():
    """`{"services": {}}` no es un error de forma: es un inventario que no cuadra.

    La distinción importa porque las dos cosas son rojas por caminos distintos, y confundirlas
    dejaría a `assert_inventory` sin el caso que de verdad tiene que cerrar.
    """
    assert module.violations({"services": {}}) == []


# ── La aserción positiva del inventario (D4, R4.3, R4.4) ───────────────────────────────────

SEVEN = sorted(module.EXPECTED_SERVICES)


def inventory_model(*, extra=None, drop=None, profiles=None):
    """El modelo del repositorio, con las desviaciones que cada caso necesita."""
    services = {name: service() for name in SEVEN}
    if drop is not None:
        del services[drop]
    if extra is not None:
        services[extra] = service()
    if profiles is not None:
        for name, listed in profiles.items():
            services[name] = service(profiles=listed)
    return model(**services)


def test_the_repository_inventory_is_confirmed():
    """El caso verde: los tres conjuntos coinciden y no hay profiles."""
    module.assert_inventory(inventory_model(), set(SEVEN), set())


def test_profiles_are_confirmed_when_the_enumeration_matches():
    payload = inventory_model(profiles={"worker": ["tools"], "beat": ["tools", "extra"]})
    module.assert_inventory(payload, set(SEVEN), {"tools", "extra"})


def test_a_service_hidden_behind_an_inactive_profile_is_red():
    """vía (a): el servicio no llega al modelo pero la enumeración lo lista.

    Es la vía que el censo describe como «un servicio bajo un profile no activo es invisible
    para `config`»: la igualdad con la enumeración es lo que la convierte en rojo.
    """
    payload = inventory_model(drop="beat")
    with pytest.raises(module.GuardError, match="inventario de servicios"):
        module.assert_inventory(payload, set(SEVEN), set())


def test_a_new_undeclared_service_is_red_and_says_where_to_add_it():
    payload = inventory_model(extra="grafana")
    with pytest.raises(module.GuardError) as caught:
        module.assert_inventory(payload, set(SEVEN) | {"grafana"}, set())
    assert "grafana" in str(caught.value)
    assert "EXPECTED_SERVICES" in str(caught.value)


def test_a_renamed_service_is_red_in_both_directions():
    """Un recuento pasaría; la igualdad no. Por eso la aserción no es «al menos N servicios»."""
    payload = inventory_model(drop="redis", extra="valkey")
    with pytest.raises(module.GuardError) as caught:
        module.assert_inventory(payload, (set(SEVEN) - {"redis"}) | {"valkey"}, set())
    message = str(caught.value)
    assert "valkey" in message and "redis" in message


@pytest.mark.parametrize(
    "payload", [{}, {"services": {}}], ids=["objeto-vacio", "services-vacio"]
)
def test_a_successful_config_that_returns_nothing_never_confirms(payload):
    """vía (h): `config` sale con éxito y devuelve `{}` — un bucle sobre nada daría verde."""
    with pytest.raises(module.GuardError):
        module.assert_inventory(payload, set(SEVEN), set())


def test_an_enumeration_that_lists_fewer_services_than_the_model_is_red():
    """El modelo y la enumeración tienen que describir lo mismo, en las dos direcciones."""
    with pytest.raises(module.GuardError, match="enumeración"):
        module.assert_inventory(inventory_model(), set(SEVEN) - {"frontend"}, set())


def test_a_lossy_profile_enumeration_is_contradicted_by_the_model():
    """vía (g)/(e): un nombre de profile partido en dos por la enumeración por líneas.

    El modelo es la fuente **sin pérdida** y audita a la enumeración: `a\\nb` llega entero por
    `json.loads`, mientras que leer la enumeración por líneas lo parte en `a` y `b`. La igualdad
    es lo que hace que la pérdida se note en vez de estrechar la vista en silencio.
    """
    payload = inventory_model(profiles={"worker": ["a\nb"]})
    with pytest.raises(module.GuardError, match="profiles"):
        module.assert_inventory(payload, set(SEVEN), {"a", "b"})


def test_a_profile_with_a_comma_survives_when_it_travels_by_argv():
    """El mismo nombre, enumerado entero: verde. Es el arreglo de (g), no una excepción."""
    payload = inventory_model(profiles={"worker": ["a,b"]})
    module.assert_inventory(payload, set(SEVEN), {"a,b"})


def test_a_profile_the_enumeration_invented_is_red():
    payload = inventory_model()
    with pytest.raises(module.GuardError, match="profiles"):
        module.assert_inventory(payload, set(SEVEN), {"tools"})


@pytest.mark.parametrize(
    "listed",
    ["tools", ["tools", 7], {"a": 1}],
    ids=["no-es-lista", "elemento-no-cadena", "es-objeto"],
)
def test_malformed_profiles_are_an_error_and_never_a_smaller_set(listed):
    payload = inventory_model()
    payload["services"]["worker"] = service(profiles=listed)
    with pytest.raises(module.GuardError, match="lista de cadenas"):
        module.assert_inventory(payload, set(SEVEN), set())


# ── La salida: inyectiva, determinista, y un verde que dice «vio esto» (R2.3) ───────────────


def test_escape_is_injective_on_control_characters():
    assert module.escape("a\x1bb") != module.escape("a\x9bb")
    assert module.escape("a\\x1bb") != module.escape("a\x1bb")
    assert len({module.escape(f"a{chr(code)}b") for code in range(0x20)}) == 0x20


def test_escape_keeps_names_readable_and_marks_odd_separators():
    assert module.escape("postgres") == "postgres"
    assert module.escape("año") == "año"
    assert module.escape("a\xa0b") == "a\\xa0b"
    assert module.escape("a b") == "a b"


def test_a_hostile_service_name_cannot_fabricate_a_block():
    """Un nombre con saltos de línea no puede inventar un bloque ni una etiqueta más.

    La garantía es **por línea**, que es la unidad del formato: el nombre hostil sigue
    conteniendo el texto `servicio: redis`, pero escapado va dentro de una sola línea y ninguna
    línea nueva empieza por una etiqueta. Contar apariciones de la subcadena mediría otra cosa.
    """
    hostile = "postgres\nregla: mapeo-fuera-de-loopback\nservicio: redis"
    output = module.render([module.Violation(hostile, module.NETWORK_MODE, "host")])
    lines = output.splitlines()
    assert sum(1 for line in lines if line.startswith("servicio: ")) == 1
    assert sum(1 for line in lines if line.startswith("regla: ")) == 1
    assert "\\x0a" in output, "el salto de línea del nombre tiene que salir escapado"
    assert "infracciones: 1" in output


def test_a_hostile_service_name_cannot_pass_for_another_service():
    assert module.escape("redis\x00") != module.escape("redis")
    assert module.escape("redis\x1b[2K") != module.escape("redis")


def test_render_uses_one_label_and_one_value_per_line():
    output = module.render(
        [module.Violation("postgres", module.OFF_LOOPBACK, module.dump(mapping(5432, "5432")))]
    )
    block = output.split("\n\n")[0]
    labels = [line.split(": ", 1)[0] for line in block.splitlines()]
    assert labels == ["regla", "servicio", "mapeo", "motivo"]
    assert "postgres" in block


def test_render_is_deterministic_regardless_of_input_order():
    found = module.violations(
        model(
            redis=service(ports=[mapping(6379, "6379")]),
            beat=service(network_mode="host"),
            postgres=service(ports=["${BIND}:5432:5432"]),
        )
    )
    assert module.render(found) == module.render(list(reversed(found)))
    assert "infracciones: 3" in module.render(found)


def test_render_never_prints_a_table_nor_an_escape_sequence():
    found = module.violations(model(postgres=service(ports=[mapping(5432, "5432", "0.0.0.0")])))
    output = module.render(found)
    for delimiter in ("|", "\t", "\x1b"):
        assert delimiter not in output, delimiter


def test_naming_something_that_is_not_a_mapping_is_bounded_and_never_a_dump():
    """R1.7: «ningún volcado de salida ajena», ni por el camino de un valor inesperado.

    Un servicio que no es objeto se nombra, y lo que se nombra es **su valor**. Sin tope, ese
    camino imprimiría una porción arbitraria del modelo; con él, un hallazgo ocupa lo que ocupa
    un hallazgo. Un mapeo normalizado no se recorta nunca, y este test fija las dos cosas.
    """
    found = module.violations(model(postgres=["x" * 5000]))
    assert len(found) == 1
    assert found[0].rule == module.SERVICE_NOT_OBJECT
    assert len(found[0].detail) <= module.DETAIL_LIMIT + len("… (recortado)")
    assert found[0].detail.endswith("… (recortado)")

    short = module.dump(mapping(5432, "5432", module.LOOPBACK))
    assert "recortado" not in short, "un mapeo normal no se recorta"


def test_render_of_no_violations_is_not_a_green_message():
    """`render` cuenta hallazgos; el verde lo escribe `summary`, que es quien nombra lo visto."""
    assert module.render([]) == "infracciones: 0\n"


def test_the_green_names_and_counts_what_it_inspected():
    output = module.summary(CONFORMING, set())
    assert "servicios inspeccionados: 7" in output
    assert "mapeos inspeccionados: 4" in output
    assert "profiles inspeccionados: 0" in output
    for name in SEVEN:
        assert f"servicio: {name}" in output
    assert f"mapeo: postgres {module.LOOPBACK}:5432 -> 5432" in output
    assert "mapeo: backend todas las interfaces:8000 -> 8000 (exento a propósito)" in output


def test_the_green_is_never_empty_and_never_reads_as_having_seen_nothing():
    output = module.summary(CONFORMING, set())
    assert output.strip()
    assert len(output.splitlines()) >= 7 + 4 + 3


def test_the_green_names_the_profiles_it_inspected():
    payload = model(**{name: service() for name in SEVEN})
    payload["services"]["worker"] = service(profiles=["tools", "a,b"])
    output = module.summary(payload, {"tools", "a,b"})
    assert "profiles inspeccionados: 2" in output
    assert "profile: a,b" in output
    assert "profile: tools" in output


def test_the_green_is_deterministic():
    assert module.summary(CONFORMING, {"b", "a"}) == module.summary(CONFORMING, {"a", "b"})


def test_a_hostile_service_name_cannot_fabricate_a_line_in_the_green():
    """Misma garantía por línea en el verde: un servicio no puede fingir ser dos."""
    payload = model(**{"postgres\nservicio: redis": service()})
    output = module.summary(payload, set())
    lines = output.splitlines()
    assert sum(1 for line in lines if line.startswith("servicio: ")) == 1
    assert "servicios inspeccionados: 1" in output


# ── La cadena: cómo se construyen el `argv` y el entorno ────────────────────────────────────
#
# Aquí viven cuatro de las nueve vías —(d), (e), (f), (g)— porque no están en la lógica sino en
# la invocación. Por eso se prueban con un `docker` de mentira en el `PATH` del test y **no**
# mockeando `subprocess.run`, que probaría el mock (D12).

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compose-ports.py"

CONFORMING_MODEL = {
    "name": "autohostai",
    "services": {
        "postgres": service(ports=[mapping(5432, "5432", module.LOOPBACK)]),
        "redis": service(ports=[mapping(6379, "6379", module.LOOPBACK)]),
        "migrate": service(),
        "backend": service(ports=[mapping(8000, "8000")]),
        "worker": service(),
        "beat": service(),
        "frontend": service(ports=[mapping(3000, "3000")]),
    },
}


def plan_for(model_payload=None, listing="", steps=None):
    """El guion del `docker` de mentira: qué contesta a cada uno de los tres pasos.

    Por defecto contesta lo que contestaría el repositorio real y conforme, de modo que cada
    test solo tenga que desviar el paso que le interesa. Los desvíos van en un diccionario
    explícito y **no** por `**kwargs`: con palabras clave, un desvío del paso `profiles`
    chocaba con el parámetro que fija su salida y se perdía en silencio — el test creía estar
    probando un fallo de la enumeración y probaba el camino feliz.
    """
    payload = CONFORMING_MODEL if model_payload is None else model_payload
    listed = "\n".join(payload.get("services", {})) + "\n"
    plan = {
        "profiles": {"stdout": listing, "code": 0, "stderr": ""},
        "services": {"stdout": listed, "code": 0, "stderr": ""},
        "json": {"stdout": json.dumps(payload), "code": 0, "stderr": ""},
    }
    for step, changes in (steps or {}).items():
        plan[step] = {**plan[step], **changes}
    return plan


# El cuerpo del `docker` de mentira. Lo único interpolado es `sys.executable`, que lo da el
# intérprete y no un dato ajeno: el guion y lo que registra viajan por ficheros que el propio
# script lee por su `__file__`. Es la disciplina de «nada se interpola en código ejecutable»
# que `test_compose_stacks.py` ya aplica, y por el mismo motivo — una ruta con una comilla
# dentro cerraría la cadena y ejecutaría lo que viniera detrás.
FAKE_DOCKER = """#!{python}
import json, os, pathlib, sys

here = pathlib.Path(__file__).parent
argv = sys.argv[1:]
with (here / "calls.jsonl").open("a") as fh:
    fh.write(json.dumps({{"argv": argv, "env": dict(os.environ)}}) + "\\n")

plan = json.loads((here / "plan.json").read_text())
if "--profiles" in argv:
    step = plan["profiles"]
elif "--services" in argv:
    step = plan["services"]
else:
    step = plan["json"]
sys.stdout.write(step["stdout"])
sys.stderr.write(step["stderr"])
raise SystemExit(step["code"])
"""


def fake_path(tmp_path, plan=None):
    """Un `PATH` que contiene **solo** un `docker` de mentira gobernado por `plan.json`."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if plan is not None:
        (bin_dir / "plan.json").write_text(json.dumps(plan))
        docker = bin_dir / "docker"
        docker.write_text(FAKE_DOCKER.format(python=sys.executable))
        docker.chmod(0o755)
    return bin_dir


def run_guard(bin_dir, **extra_env):
    """Ejecuta la guardia entera por `subprocess`, con el `PATH` del test y nada más."""
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env={**os.environ, "PATH": str(bin_dir), **extra_env},
        text=True,
        capture_output=True,
    )


def calls(bin_dir):
    recorded = bin_dir / "calls.jsonl"
    if not recorded.exists():
        return []
    return [json.loads(line) for line in recorded.read_text().splitlines() if line.strip()]


def test_the_conforming_repository_model_exits_zero_through_the_whole_chain(tmp_path):
    bin_dir = fake_path(tmp_path, plan_for())
    result = run_guard(bin_dir)
    assert result.returncode == 0, result.stderr
    assert "servicios inspeccionados: 7" in result.stdout
    assert "mapeos inspeccionados: 4" in result.stdout


def test_the_three_invocations_are_chained_in_order_and_all_carry_the_two_flags(tmp_path):
    """R1.5/R1.6/D1: ninguna invocación puede salirse de `CONFIG_BASE`."""
    bin_dir = fake_path(tmp_path, plan_for())
    assert run_guard(bin_dir).returncode == 0
    recorded = [call["argv"] for call in calls(bin_dir)]
    assert len(recorded) == 3
    assert "--profiles" in recorded[0]
    assert "--services" in recorded[1]
    assert recorded[2][-2:] == ["--format", "json"]
    for argv in recorded:
        assert "--no-interpolate" in argv, argv
        assert "--no-env-resolution" in argv, argv
        assert argv[0] == "compose", argv


def test_an_exported_compose_file_never_reaches_the_child(tmp_path):
    """vía (d): el entorno del hijo se construye por lista blanca, no desinfectando (D5).

    La aserción es «nada que la guardia no haya puesto, y ninguno de estos valores», no
    «exactamente `PATH`»: en macOS el propio libc añade `LC_CTYPE` y
    `__CF_USER_TEXT_ENCODING` **por debajo** del `env=` de Python, así que exigir el conjunto
    exacto probaría la plataforma y no la lista blanca. Lo que importa es que ninguna variable
    de Compose ni de Docker sobreviva, y que su valor no aparezca por ninguna otra clave.
    """
    bin_dir = fake_path(tmp_path, plan_for())
    smuggled = {
        "COMPOSE_FILE": "/tmp/otro-compose.yml",
        "COMPOSE_PROFILES": "a,b",
        "COMPOSE_ENV_FILES": "/tmp/otro.env",
        "COMPOSE_PATH_SEPARATOR": ";",
        "DOCKER_HOST": "tcp://otro:2375",
    }
    result = run_guard(bin_dir, **smuggled)
    assert result.returncode == 0, result.stderr

    recorded = calls(bin_dir)
    assert recorded, "el `docker` de mentira no llegó a ejecutarse"
    for call in recorded:
        env = call["env"]
        assert "PATH" in env
        leaked = [key for key in env if key.startswith(("COMPOSE_", "DOCKER_"))]
        assert not leaked, leaked
        for key, value in smuggled.items():
            assert value not in env.values(), f"{key} llegó al hijo bajo otra clave"


def test_no_invocation_passes_file(tmp_path):
    """vía (f): `--file` desactiva la carga automática del override y la lista se queda corta."""
    bin_dir = fake_path(tmp_path, plan_for())
    assert run_guard(bin_dir).returncode == 0
    for call in calls(bin_dir):
        assert "--file" not in call["argv"], call["argv"]
        assert "-f" not in call["argv"], call["argv"]


def test_profiles_travel_one_flag_per_name_and_never_joined_by_commas(tmp_path):
    """vía (g): la coma es un carácter legítimo del dato y unir los nombres pierde uno."""
    payload = json.loads(json.dumps(CONFORMING_MODEL))
    payload["services"]["worker"]["profiles"] = ["a,b"]
    payload["services"]["beat"]["profiles"] = ["tools"]
    bin_dir = fake_path(tmp_path, plan_for(payload, listing="a,b\ntools\n"))

    result = run_guard(bin_dir)
    assert result.returncode == 0, result.stderr + result.stdout

    recorded = [call["argv"] for call in calls(bin_dir)]
    assert "--profile" not in recorded[0], "la enumeración no activa nada"
    for argv in recorded[1:]:
        flagged = [argv[i + 1] for i, arg in enumerate(argv) if arg == "--profile"]
        assert flagged == ["a,b", "tools"], argv
        assert "a,b,tools" not in argv, "los nombres viajaron unidos por comas"


@pytest.mark.parametrize("step", ["profiles", "services", "json"])
def test_a_failing_step_is_red_and_never_swallowed(step, tmp_path):
    """vía (e): estado de salida comprobado **aparte** del contenido, y antes de mirarlo."""
    plan = plan_for(steps={step: {"stdout": "salida que no hay que creerse", "code": 1,
                                  "stderr": "boom"}})
    result = run_guard(fake_path(tmp_path, plan))
    assert result.returncode != 0
    assert "boom" in result.stderr
    assert "servicios inspeccionados" not in result.stdout


def test_a_step_that_writes_to_stdout_and_fails_never_relays_that_stdout(tmp_path):
    """R1.7: `stdout` de Compose no se relata nunca, ni siquiera como diagnóstico de un fallo."""
    marker = "SUPER_SECRET_DEL_ENV"
    plan = plan_for(steps={"json": {"stdout": f'{{"services": {{"x": "{marker}"}}}}',
                                    "code": 1, "stderr": "el paso falló"}})
    result = run_guard(fake_path(tmp_path, plan))
    assert result.returncode != 0
    assert marker not in result.stdout
    assert marker not in result.stderr


def test_only_the_first_line_of_stderr_is_relayed_and_it_is_capped(tmp_path):
    noise = "x" * 500
    plan = plan_for(steps={"profiles": {
        "stdout": "", "code": 1,
        "stderr": f"primera linea {noise}\nsegunda linea\ntercera",
    }})
    result = run_guard(fake_path(tmp_path, plan))
    assert result.returncode != 0
    assert "primera linea" in result.stderr
    assert "segunda linea" not in result.stderr
    assert "tercera" not in result.stderr
    assert "x" * (module.STDERR_LIMIT + 1) not in result.stderr


def test_an_unknown_flag_is_red_and_points_at_the_minimum_compose_version(tmp_path):
    """D6: no hay comparación de versiones; una bandera desconocida ya sale en rojo."""
    plan = plan_for(steps={"profiles": {"stdout": "", "code": 125,
                                       "stderr": "unknown flag: --no-env-resolution"}})
    result = run_guard(fake_path(tmp_path, plan))
    assert result.returncode != 0
    assert "unknown flag" in result.stderr
    assert module.MIN_COMPOSE in result.stderr
    assert "--no-env-resolution" in result.stderr


def test_the_guard_is_red_when_docker_is_absent(tmp_path):
    result = run_guard(fake_path(tmp_path))
    assert result.returncode != 0
    assert "docker" in result.stderr
    assert result.stdout == ""


def test_unparseable_json_is_red_with_its_own_message(tmp_path):
    plan = plan_for(steps={"json": {"stdout": "no soy json", "code": 0, "stderr": ""}})
    result = run_guard(fake_path(tmp_path, plan))
    assert result.returncode != 0
    assert "JSON" in result.stderr
    assert "no soy json" not in result.stderr


def test_a_violation_exits_non_zero_and_names_the_service_and_the_mapping(tmp_path):
    """R2.1 de punta a punta, por el camino real y no sobre la función pura."""
    payload = json.loads(json.dumps(CONFORMING_MODEL))
    payload["services"]["postgres"]["ports"] = [mapping(5432, "5432")]
    result = run_guard(fake_path(tmp_path, plan_for(payload)))
    assert result.returncode != 0
    assert "servicio: postgres" in result.stdout
    assert "5432" in result.stdout
    assert "infracciones: 1" in result.stdout


def test_an_inventory_mismatch_is_red_even_with_no_violations(tmp_path):
    """vía (h) por el camino real: `config` con éxito devolviendo `{}` no es «nada que ver»."""
    result = run_guard(fake_path(tmp_path, plan_for({"services": {}})))
    assert result.returncode != 0
    assert "inventario" in result.stderr


def test_violations_and_an_inventory_mismatch_are_reported_together(tmp_path):
    """Las dos son rojas; verlas juntas ahorra una vuelta a quien añadió el servicio."""
    payload = json.loads(json.dumps(CONFORMING_MODEL))
    payload["services"]["grafana"] = service(ports=[mapping(3001, "3001")])
    result = run_guard(fake_path(tmp_path, plan_for(payload)))
    assert result.returncode != 0
    assert "servicio: grafana" in result.stdout
    assert "EXPECTED_SERVICES" in result.stderr


def test_the_guard_never_invokes_the_shell(tmp_path):
    """Lista de argumentos siempre: `argv[0]` llega tal cual y no por un `-c`."""
    bin_dir = fake_path(tmp_path, plan_for())
    assert run_guard(bin_dir).returncode == 0
    for call in calls(bin_dir):
        assert "-c" not in call["argv"], call["argv"]


# ── Espejo de la lista negra, sobre el propio código de este script (R1.7) ──────────────────


def script_body():
    """El fichero sin su docstring de cabecera, que es donde la lista negra está escrita."""
    source = SCRIPT.read_text()
    header = ast.get_docstring(ast.parse(source))
    assert header is not None, "el script perdió su docstring de cabecera con la lista negra"
    return source.replace(header, "", 1)


def test_config_is_only_ever_invoked_through_config_base():
    """La regla de D1 vigilada por mecanismo y no por buena memoria.

    Es el mismo mecanismo que ya protege a `compose-stacks.py`
    (`test_the_command_blacklist_of_d2_has_not_been_reintroduced`, acotado a **su** fichero,
    así que no hay conflicto). Aquí va por AST y no por texto porque `config_command` es un
    identificador legítimo: lo que se acota es la **cadena** `"config"`, que solo puede
    aparecer una vez y dentro de `CONFIG_BASE`.
    """
    tree = ast.parse(SCRIPT.read_text())
    literals = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == "config"
    ]
    assert len(literals) == 1, (
        f"la cadena `config` aparece {len(literals)} veces en `compose-ports.py`: la "
        "invocación tiene que construirse siempre desde `CONFIG_BASE`, que es lo que "
        "garantiza las dos banderas de D1."
    )

    base = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", None) == "CONFIG_BASE" for t in node.targets)
    )
    assert literals[0] in list(ast.walk(base)), "`config` se invoca fuera de `CONFIG_BASE`"
    flags = [n.value for n in ast.walk(base) if isinstance(n, ast.Constant)]
    assert "--no-interpolate" in flags and "--no-env-resolution" in flags, flags


# Lo que la lista negra prohíbe **como comando**, y por tanto solo puede llegar al script como
# una cadena literal: un elemento de `argv`. Se comprueba sobre las cadenas del AST y no sobre
# el texto del fichero a propósito — el docstring y los comentarios *nombran* estas cosas para
# explicar por qué están prohibidas, y un `grep` sobre el texto convierte esa explicación en un
# falso positivo, que es presión para documentar peor.
BANNED_ARGUMENTS = ("inspect", "2>/dev/null", "-c")


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


@pytest.mark.parametrize("banned", BANNED_ARGUMENTS)
def test_no_banned_argument_can_reach_an_argv(banned):
    """R1.7: `docker inspect` sin `--format` vuelca `.Config.Env`, y `-c` sería invocar un shell."""
    offenders = [value for value in string_literals(ast.parse(SCRIPT.read_text())) if value == banned]
    assert not offenders, (
        f"la cadena `{banned}` aparece como argumento en `compose-ports.py`. Ver la lista negra "
        "del docstring de cabecera: cada entrada tiene su motivo medido."
    )


def test_the_subprocess_call_never_uses_the_shell_nor_copies_the_environment():
    """`shell=True` y `os.environ.copy()` se comprueban en el árbol, no por texto.

    `shell=True` como palabra clave de una llamada, y `os.environ.copy` como acceso a atributo:
    lo segundo es la lista negra de D5 —copiar el entorno y quitar claves es la vía (d)—, y el
    entorno tiene que construirse por lista blanca en `clean_env()`.
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
                "blanca en `clean_env()`, no copiando y quitando claves (D5, vía (d))."
            )


# ── Contra Docker de verdad: la forma de la salida, no el veredicto (D12) ───────────────────


def test_real_compose_output_still_has_the_measured_shape():
    """Es lo que avisará el día que Compose cambie la normalización o renombre un campo.

    No asierta el veredicto —eso lo hace `make check-compose-ports`— sino la **forma** que
    `design.md` midió: `published` como cadena, `host_ip` ausente cuando no se especifica, y
    los cuatro mapeos del repositorio en su sitio.
    """
    if shutil.which("docker") is None:
        pytest.skip("no hay `docker` en el `PATH`")
    completed = subprocess.run(
        module.config_command("--format", "json"),
        cwd=ROOT,
        text=True,
        capture_output=True,
        env=module.clean_env(),
    )
    if completed.returncode != 0:
        pytest.skip(f"`docker compose` no respondió: {completed.stderr.strip()[:120]}")

    services = module.services_of(json.loads(completed.stdout))
    assert set(services) == module.EXPECTED_SERVICES

    entries = [
        (name, entry)
        for name in sorted(services)
        for entry in services[name].get("ports", [])
    ]
    assert len(entries) == 4, entries
    for name, entry in entries:
        assert isinstance(entry, dict), (name, entry)
        assert isinstance(entry["published"], str), (name, entry)
    by_service = dict(entries)
    assert by_service["postgres"]["host_ip"] == module.LOOPBACK
    assert by_service["redis"]["host_ip"] == module.LOOPBACK
    assert "host_ip" not in by_service["backend"], "host_ip ausente, no `null` (R2.2)"
    assert "host_ip" not in by_service["frontend"]


def test_an_interpolated_mapping_really_does_arrive_as_a_raw_string(tmp_path):
    """vía (i) medida contra Docker de verdad, no supuesta: es la premisa entera de D2."""
    if shutil.which("docker") is None:
        pytest.skip("no hay `docker` en el `PATH`")
    (tmp_path / "docker-compose.yml").write_text(
        "services:\n  a:\n    image: alpine\n    ports:\n      - \"${BIND}:5432:5432\"\n"
    )
    completed = subprocess.run(
        module.config_command("--format", "json"),
        cwd=tmp_path,
        text=True,
        capture_output=True,
        env=module.clean_env(),
    )
    if completed.returncode != 0:
        pytest.skip(f"`docker compose` no respondió: {completed.stderr.strip()[:120]}")
    services = module.services_of(json.loads(completed.stdout))
    assert services["a"]["ports"] == ["${BIND}:5432:5432"]
    assert module.violations(json.loads(completed.stdout))[0].rule == module.NOT_NORMALIZED
