"""Suite de `compose-bytecode.py` (`ci-runner-workspace-pollution` R5).

El caso que distingue a esta guardia de una lista de nombres (R5.4): un servicio Python **nuevo**,
que no está mencionado en ningún sitio de este fichero de test ni del guard, entra en rojo si no
declara la variable — porque el alcance sale de `build.context` + bind mount en escritura, no de
comprobar `migrate`/`backend`/`worker`/`beat` por nombre.
"""

import importlib.util
import os
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "compose_bytecode",
    Path(__file__).with_name("compose-bytecode.py"),
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)

ROOT = "/repo"
BACKEND = f"{ROOT}/backend"
FRONTEND = f"{ROOT}/frontend"


def model(**services):
    return {"services": services}


def python_service(*, env=None, source=BACKEND, read_only=False, target="/app"):
    """Un servicio Python: `build.context` == `backend/`, bind mount en escritura de esa fuente."""
    svc = {
        "build": {"context": BACKEND},
        "volumes": [
            {"type": "bind", "source": source, "target": target, **({"read_only": True} if read_only else {})}
        ],
    }
    if env is not None:
        svc["environment"] = env
    return svc


def node_service(*, env=None, source=FRONTEND, read_only=False):
    """Un servicio no-Python con el mismo patrón de bind mount en escritura (caso `frontend`)."""
    svc = {
        "build": {"context": FRONTEND},
        "volumes": [{"type": "bind", "source": source, "target": "/app", **({"read_only": True} if read_only else {})}],
    }
    if env is not None:
        svc["environment"] = env
    return svc


# ── real=os.path.realpath se usa dentro del módulo; estos fixtures ya son rutas absolutas sin
# symlinks que resolver, así que no hace falta monkeypatchear realpath para los casos normales.


def scope(m):
    return module.in_scope_services(m, ROOT)


# ── R5.2: derivación desde la composición resuelta, no una lista de nombres ────────────────


def test_a_new_python_service_not_named_anywhere_here_is_in_scope():
    """El caso literal de R5.4: `mailer-worker` no aparece en ningún nombre de este fichero ni
    del guard, y aun así entra en alcance y falla si no declara la variable."""
    m = model(**{"mailer-worker": python_service(env={})})
    scoped = scope(m)
    assert set(scoped) == {"mailer-worker"}
    assert module.violations(scoped) == [module.Violation("mailer-worker", f"{module.VAR} no declarada o vacía")]


def test_all_four_real_services_are_in_scope_when_they_match_the_real_shape():
    m = model(
        migrate=python_service(env={"PYTHONDONTWRITEBYTECODE": "1"}),
        backend=python_service(env={"PYTHONDONTWRITEBYTECODE": "1"}),
        worker=python_service(env={"PYTHONDONTWRITEBYTECODE": "1"}),
        beat=python_service(env={"PYTHONDONTWRITEBYTECODE": "1"}),
        frontend=node_service(),
    )
    scoped = scope(m)
    assert set(scoped) == {"migrate", "backend", "worker", "beat"}
    assert module.violations(scoped) == []


# ── El caso que motivó la enmienda de R5.1/D8: frontend queda fuera ────────────────────────


def test_a_node_service_with_a_writable_tree_bind_mount_is_never_in_scope():
    """`frontend` monta su árbol en escritura igual que los cuatro Python — y no entra, porque
    su `build.context` no es `backend/`. Sin variable declarada y aun así no es una infracción."""
    m = model(frontend=node_service(env=None))
    assert scope(m) == {}


# ── Read-only queda fuera: no puede escribir nada, así que no puede contaminar ──────────────


def test_a_read_only_bind_mount_of_the_tree_is_never_in_scope():
    m = model(other=python_service(read_only=True, env=None))
    assert scope(m) == {}


# ── Sin bind mount del árbol: no hay nada que montar en escritura ──────────────────────────


def test_a_python_service_with_no_bind_mount_at_all_is_not_in_scope():
    svc = {"build": {"context": BACKEND}}
    assert scope(model(worker=svc)) == {}


def test_a_python_service_whose_bind_source_is_outside_the_tree_is_not_in_scope():
    svc = python_service(source="/somewhere/else", env=None)
    assert scope(model(worker=svc)) == {}


# ── Servicios sin `build` (imágenes de terceros): postgres, redis ──────────────────────────


def test_a_service_without_build_like_postgres_is_never_in_scope():
    svc = {"volumes": [{"type": "bind", "source": BACKEND, "target": "/x"}]}
    assert scope(model(postgres=svc)) == {}


# ── Limitación conocida y documentada (docstring del guard + local-environment.md §«Guardia de
# bytecode»): un servicio Python vía `image:`, sin `build.context`, escapa el alcance ───────


def test_a_python_image_based_service_without_build_context_escapes_scope_as_documented():
    """El hueco exacto que documentan el docstring del guard y la spec: `image: python:...`,
    sin `build`, monta el árbol en escritura y no declara la variable — y aun así queda fuera
    de alcance, porque la señal (1) es `build.context`, no el lenguaje real del proceso. Este
    test no verifica que el guard esté bien: fija el hueco documentado contra un ensanche o
    estrechamiento silencioso de la señal, para que quien la toque lo haga a sabiendas."""
    svc = {
        "image": "python:3.12-slim",
        "volumes": [{"type": "bind", "source": BACKEND, "target": "/app"}],
    }
    m = model(**{"mailer-worker-2": svc})
    scoped = scope(m)
    assert scoped == {}
    assert module.violations(scoped) == []


# ── La variable: presente y no vacía, nada más (semántica real de CPython) ─────────────────


def test_missing_var_is_a_violation():
    m = model(worker=python_service(env={}))
    assert module.violations(scope(m)) == [module.Violation("worker", f"{module.VAR} no declarada o vacía")]


def test_empty_string_var_is_a_violation():
    m = model(worker=python_service(env={"PYTHONDONTWRITEBYTECODE": ""}))
    assert module.violations(scope(m)) == [module.Violation("worker", f"{module.VAR} no declarada o vacía")]


def test_any_non_empty_value_satisfies_it_not_only_the_literal_one():
    """CPython no exige `"1"` concretamente: cualquier cadena no vacía activa el ajuste."""
    m = model(worker=python_service(env={"PYTHONDONTWRITEBYTECODE": "true"}))
    assert module.violations(scope(m)) == []


def test_no_environment_key_at_all_is_a_violation():
    m = model(worker=python_service(env=None))
    assert module.violations(scope(m)) == [module.Violation("worker", f"{module.VAR} no declarada o vacía")]


# ── Todo conforme pasa sin intervención (R5.3, R5.4 en su forma positiva) ───────────────────


def test_all_conforming_services_produce_no_violations():
    m = model(
        migrate=python_service(env={"PYTHONDONTWRITEBYTECODE": "1"}),
        backend=python_service(env={"PYTHONDONTWRITEBYTECODE": "1"}),
    )
    assert module.violations(scope(m)) == []


# ── Determinismo y salida acotada ────────────────────────────────────────────────────────


def test_render_is_deterministic_regardless_of_dict_order():
    a = module.violations({"zeta": python_service(env=None), "alpha": python_service(env=None)})
    b = module.violations({"alpha": python_service(env=None), "zeta": python_service(env=None)})
    assert module.render(a) == module.render(b)


def test_render_names_every_violation_and_counts_them():
    found = [module.Violation("a", "x"), module.Violation("b", "y")]
    out = module.render(found)
    assert "servicio: a" in out
    assert "servicio: b" in out
    assert "infracciones: 2" in out


def test_summary_is_not_empty_and_names_what_it_saw():
    m = model(migrate=python_service(env={"PYTHONDONTWRITEBYTECODE": "1"}))
    out = module.summary(scope(m))
    assert "migrate" in out
    assert out.strip() != ""


# ── Integración real contra el compose del repo (marcada, como `compose-ports.py`) ──────────


@pytest.mark.skipif(
    os.environ.get("CI") is None and not Path("docker-compose.yml").exists(),
    reason="requiere estar en la raíz del repositorio con Docker disponible",
)
def test_real_repo_compose_has_exactly_the_four_python_services_in_scope():
    import subprocess

    completed = subprocess.run(
        ["docker", "compose", "config", "--no-interpolate", "--no-env-resolution", "--format", "json"],
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.skip(f"`docker compose` no respondió: {completed.stderr.strip()[:120]}")
    import json

    m = json.loads(completed.stdout)
    scoped = module.in_scope_services(m, os.path.realpath(os.getcwd()))
    assert set(scoped) == {"migrate", "backend", "worker", "beat"}
    assert module.violations(scoped) == []
