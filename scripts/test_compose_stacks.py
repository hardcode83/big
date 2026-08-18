import ast
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


SPEC = importlib.util.spec_from_file_location(
    "compose_stacks",
    Path(__file__).with_name("compose-stacks.py"),
)
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


# Copiado literalmente de `git worktree list --porcelain` en esta máquina el 2026-08-17.
WORKTREE_LIST = """worktree /Users/hardcode/personal/AutoHostAI
HEAD 4ed6849052d6632572f7134e5fcaf9bf957463f5
branch refs/heads/main

worktree /Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+channex-validation-limits
HEAD 0ed7a8ba42f86b22cdafd35739db32aed0a32f85
branch refs/heads/sdd/channex-validation-limits
locked claude session sdd/channex-validation-limits (pid 1334 start Mon Aug 17 06:32:58 2026)

worktree /Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+revenue-pricing
HEAD 6c3feabcbf3538ab9d8d25ca55f4626ec6dc5c61
branch refs/heads/sdd/revenue-pricing
"""


# Copiado literalmente de `docker compose ls -a --format json` en esta máquina el 2026-08-17.
COMPOSE_LS = (
    '[{"Name":"sddrevenue-pricing","Status":"exited(1), running(6)","ConfigFiles":'
    '"/Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+revenue-pricing/'
    'docker-compose.yml,/Users/hardcode/personal/AutoHostAI/.claude/worktrees/'
    'sdd+revenue-pricing/docker-compose.worktree.yml"},'
    '{"Name":"sddrule11-ownership-single-source","Status":"exited(1), running(6)",'
    '"ConfigFiles":"/Users/hardcode/personal/AutoHostAI/.claude/worktrees/'
    'sdd+rule11-ownership-single-source/docker-compose.yml,/Users/hardcode/personal/'
    'AutoHostAI/.claude/worktrees/sdd+rule11-ownership-single-source/'
    'docker-compose.worktree.yml"}]'
)


def test_parse_worktrees_takes_the_first_record_as_main_root():
    main_root, roots = module.parse_worktrees(WORKTREE_LIST)
    assert main_root == Path("/Users/hardcode/personal/AutoHostAI")
    assert list(roots) == [
        Path("/Users/hardcode/personal/AutoHostAI"),
        Path(
            "/Users/hardcode/personal/AutoHostAI/.claude/worktrees/"
            "sdd+channex-validation-limits"
        ),
        Path("/Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+revenue-pricing"),
    ]
    assert roots[Path("/Users/hardcode/personal/AutoHostAI")] == "main"
    assert (
        roots[
            Path("/Users/hardcode/personal/AutoHostAI/.claude/worktrees/sdd+revenue-pricing")
        ]
        == "sdd/revenue-pricing"
    )


def test_parse_worktrees_aborts_on_a_relative_path():
    with pytest.raises(module.DiagnosticError, match="no absoluta"):
        module.parse_worktrees("worktree ../AutoHostAI\nHEAD abc\n")


def test_parse_worktrees_aborts_without_records():
    with pytest.raises(module.DiagnosticError, match="ningún registro"):
        module.parse_worktrees("\n\n")


def test_parse_worktrees_aborts_on_a_record_without_a_worktree_line():
    with pytest.raises(module.DiagnosticError, match="sin línea"):
        module.parse_worktrees(
            "worktree /repo\nHEAD abc\n\nHEAD def\nbranch refs/heads/otra\n"
        )


def test_parse_worktrees_aborts_on_a_bare_repository():
    with pytest.raises(module.DiagnosticError, match="bare"):
        module.parse_worktrees("worktree /repo.git\nbare\n")


def test_parse_projects_accepts_the_measured_output():
    projects = module.parse_projects(COMPOSE_LS)
    assert [project["Name"] for project in projects] == [
        "sddrevenue-pricing",
        "sddrule11-ownership-single-source",
    ]
    assert projects[0]["Status"] == "exited(1), running(6)"
    assert projects[0]["ConfigFiles"].endswith("docker-compose.worktree.yml")


def test_parse_projects_reads_an_empty_inventory_as_empty():
    assert module.parse_projects("[]") == []


def test_parse_projects_aborts_on_unparseable_json():
    with pytest.raises(module.DiagnosticError, match="no es JSON válido"):
        module.parse_projects("not json")


def test_parse_projects_aborts_when_the_payload_is_not_a_list():
    with pytest.raises(module.DiagnosticError, match="no devolvió una lista"):
        module.parse_projects('{"Name":"x","Status":"y","ConfigFiles":"/a/b.yml"}')


def test_parse_projects_aborts_when_a_key_is_missing():
    with pytest.raises(module.DiagnosticError, match="ConfigFiles"):
        module.parse_projects('[{"Name":"x","Status":"y"}]')


def test_project_dir_of_a_single_file():
    assert module.project_dir("/srv/app/docker-compose.yml") == (Path("/srv/app"), None)


def test_project_dir_takes_the_first_of_several_files():
    directory, reason = module.project_dir(
        "/srv/app/docker-compose.yml,/srv/otro/docker-compose.worktree.yml"
    )
    assert directory == Path("/srv/app")
    assert reason is None


def test_project_dir_reports_a_comma_inside_a_path_as_ambiguous():
    directory, reason = module.project_dir("/srv/app,uno/docker-compose.yml")
    assert directory is None
    assert "ambigüedad" in reason


def test_project_dir_reports_an_empty_field_as_ambiguous():
    directory, reason = module.project_dir("")
    assert directory is None
    assert "vacío" in reason


def test_project_dir_reports_a_relative_first_fragment_as_ambiguous():
    directory, reason = module.project_dir("docker-compose.yml")
    assert directory is None
    assert reason is not None


MAIN = Path("/repo")
ROOTS = {MAIN: "main", Path("/repo/.claude/worktrees/sdd+feature"): "sdd/feature"}


def project(name, config_files, status="running(6)"):
    return {"Name": name, "Status": status, "ConfigFiles": config_files}


def test_classify_a_registered_worktree_is_alive_and_attributed():
    record = module.classify(
        project("sddfeature", "/repo/.claude/worktrees/sdd+feature/docker-compose.yml"),
        ROOTS,
        MAIN,
    )
    assert record.klass == module.VIVO
    assert record.worktree == Path("/repo/.claude/worktrees/sdd+feature")
    assert record.branch == "sdd/feature"


def test_classify_an_unregistered_directory_under_the_tree_is_orphan():
    record = module.classify(
        project("sddgone", "/repo/.claude/worktrees/sdd+gone/docker-compose.yml"), ROOTS, MAIN
    )
    assert record.klass == module.HUERFANO
    assert record.origin == Path("/repo/.claude/worktrees/sdd+gone")


def test_classify_a_directory_outside_the_tree_is_foreign():
    record = module.classify(project("otro", "/srv/otro/docker-compose.yml"), ROOTS, MAIN)
    assert record.klass == module.AJENO


def test_classify_an_ambiguous_origin_is_undetermined_and_never_orphan():
    record = module.classify(project("raro", ""), ROOTS, MAIN)
    assert record.klass == module.INDETERMINADO
    assert record.reason is not None
    assert record.origin is None


def test_classify_normalizes_dot_dot_and_symlinks_to_the_same_verdict(tmp_path):
    real = tmp_path / "repo"
    (real / ".claude/worktrees/sdd+feature").mkdir(parents=True)
    link = tmp_path / "enlace"
    link.symlink_to(real)
    roots = {real: "main", real / ".claude/worktrees/sdd+feature": "sdd/feature"}

    through_dots = module.classify(
        project("x", f"{real}/.claude/worktrees/otro/../sdd+feature/docker-compose.yml"),
        roots,
        real,
    )
    through_link = module.classify(
        project("x", f"{link}/.claude/worktrees/sdd+feature/docker-compose.yml"), roots, real
    )
    assert through_dots.klass == through_link.klass == module.VIVO


def test_classify_does_not_touch_disk_to_decide(tmp_path):
    """Un directorio inexistente se clasifica igual: el criterio es git, no `[ -d … ]`."""
    record = module.classify(
        project("sddborrado", f"{tmp_path}/repo/.claude/worktrees/sdd+borrado/docker-compose.yml"),
        {tmp_path / "repo": "main"},
        tmp_path / "repo",
    )
    assert record.klass == module.HUERFANO
    assert record.on_disk is False


def test_classify_nested_worktree_is_orphan_not_attributed_to_the_main_root():
    record = module.classify(
        project("sddfuera", "/repo/.claude/worktrees/sdd+fuera/docker-compose.yml"), ROOTS, MAIN
    )
    assert record.klass == module.HUERFANO
    assert record.worktree is None
    assert record.branch is None


def test_classify_a_subdirectory_of_a_live_worktree_is_orphan_by_design():
    """Límite conocido y aceptado (design.md, Risks): un proyecto levantado desde un
    subdirectorio de un worktree registrado sale `huérfano`, no `vivo`.

    Hoy no puede ocurrir —los únicos ficheros de compose del árbol son los tres de la raíz— y
    el informe imprime el `origen` para que el falso positivo sea legible. Este test fija el
    veredicto para que nadie lo «arregle» con la regla de «prefijo registrado más largo», que
    D5 rechaza porque atribuiría al principal cualquier worktree desregistrado.
    """
    record = module.classify(
        project("sddinfra", "/repo/.claude/worktrees/sdd+feature/infra/docker-compose.yml"),
        ROOTS,
        MAIN,
    )
    assert record.klass == module.HUERFANO


@pytest.mark.parametrize("main_root", [Path(""), Path("repo"), Path("../repo")])
def test_classify_aborts_when_the_main_root_is_not_absolute(main_root):
    with pytest.raises(module.DiagnosticError, match="universal"):
        module.classify(project("x", "/repo/docker-compose.yml"), {}, main_root)


def test_escape_is_injective_on_control_characters():
    assert module.escape("a\x1bb") != module.escape("a\x9bb")
    assert module.escape("a\\x1bb") != module.escape("a\x1bb")
    assert len({module.escape(f"a{chr(code)}b") for code in range(0x20)}) == 0x20


def test_escape_does_not_collapse_distinct_names():
    assert module.escape("autohostai!") != module.escape("autohostai")
    assert module.escape("autohostai!") == "autohostai!"


def test_escape_keeps_accents_readable():
    assert module.escape("/repo/año/sesión") == "/repo/año/sesión"


def test_escape_marks_non_space_separators():
    assert module.escape("a\xa0b") == "a\\xa0b"
    assert module.escape("a b") == "a b"


def records_for_ordering():
    return [
        module.Record(project="zzz", status="running(1)", klass=module.AJENO, origin=Path("/srv")),
        module.Record(
            project="bbb", status="running(1)", klass=module.VIVO, origin=MAIN, worktree=MAIN,
            branch="main",
        ),
        module.Record(
            project="aaa", status="exited(1)", klass=module.HUERFANO, origin=Path("/repo/x"),
            on_disk=True,
        ),
        module.Record(project="ccc", status="running(1)", klass=module.VIVO, origin=MAIN),
        module.Record(
            project="mmm", status="running(1)", klass=module.INDETERMINADO, reason="sin origen"
        ),
    ]


def test_render_orders_orphans_first_then_by_name():
    shuffled = records_for_ordering()
    output = module.render(shuffled)
    order = [line.split(": ", 1)[1] for line in output.splitlines() if line.startswith("proyecto: ")]
    assert order == ["aaa", "mmm", "bbb", "ccc", "zzz"]
    assert module.render(list(reversed(shuffled))) == output


def test_render_never_prints_a_teardown_command_nor_a_table():
    output = module.render(records_for_ordering())
    # Palabra completa: `indeterminado` contiene «rm» y no es un comando de derribo.
    assert re.search(r"\b(down|rm|prune|docker|make)\b", output) is None
    for delimiter in ("|", "\t", "\x1b"):
        assert delimiter not in output, delimiter


def test_render_counts_every_class_and_closes_with_the_fixed_sentence():
    output = module.render(records_for_ordering())
    assert "huérfanos: 1" in output
    assert "vivos: 2" in output
    assert "ajenos: 1" in output
    assert "indeterminados: 1" in output
    assert output.endswith(module.CLOSING + "\n")


def test_render_uses_one_label_and_one_value_per_line():
    output = module.render(
        [
            module.Record(
                project="sddfeature", status="running(6)", klass=module.VIVO,
                origin=MAIN, worktree=MAIN, branch="main",
            )
        ]
    )
    block = output.split("\n\n")[0]
    assert block.splitlines() == [
        "clase: vivo",
        "proyecto: sddfeature",
        "estado: running(6)",
        "origen: /repo",
        "worktree: /repo",
        "rama: main",
    ]


def test_render_of_an_empty_inventory_is_not_an_error():
    output = module.render([])
    assert "sin proyectos de Compose" in output
    assert "huérfanos: 0" in output


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/compose-stacks.py"


def fake_path(tmp_path, docker_body=None, payload=None):
    """Un `PATH` con el `git` de verdad y, si se pide, un `docker` de mentira.

    Se ejercita el script entero por `subprocess`, sin mockear `subprocess.run`: el riesgo
    real es la forma de la salida ajena, y un mock probaría el mock.

    El `payload` va a un fichero aparte y el `docker` de mentira lo lee en Python por su
    propio `__file__`: **nada se interpola en código ejecutable**, ni el payload ni ninguna
    ruta. Es la misma disciplina de D2 que cumple el script («lista de argumentos, nunca por
    shell») aplicada al arnés que lo certifica. Con interpolación en una cadena de shell, un
    checkout cuya ruta llevase una comilla cerraría la cadena y ejecutaría shell arbitrario
    bajo el runner.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").symlink_to(shutil.which("git"))
    if payload is not None:
        (bin_dir / "payload.json").write_text(payload)
        docker = bin_dir / "docker"
        docker.write_text(
            f"#!{sys.executable}\n"
            "import pathlib, sys\n"
            "sys.stdout.write(pathlib.Path(__file__).with_name('payload.json').read_text())\n"
        )
        docker.chmod(0o755)
    elif docker_body is not None:
        # `PATH` sólo contiene `bin_dir`, así que este cuerpo únicamente puede usar builtins
        # de shell (`echo`, `exit`); cualquier binario externo daría `command not found`.
        docker = bin_dir / "docker"
        docker.write_text(f"#!/bin/sh\n{docker_body}\n")
        docker.chmod(0o755)
    return bin_dir


def run_script(bin_dir):
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=ROOT,
        env={**os.environ, "PATH": str(bin_dir)},
        text=True,
        capture_output=True,
    )


def test_main_fails_when_docker_is_absent(tmp_path):
    result = run_script(fake_path(tmp_path))
    assert result.returncode != 0
    assert "docker" in result.stderr
    assert result.stdout == ""


def test_main_fails_when_the_daemon_does_not_answer(tmp_path):
    body = 'echo "Cannot connect to the Docker daemon at unix:///var/run/docker.sock." >&2\nexit 1'
    result = run_script(fake_path(tmp_path, body))
    assert result.returncode != 0
    assert "Cannot connect to the Docker daemon" in result.stderr
    assert result.stdout == ""


def test_main_fails_on_unparseable_json(tmp_path):
    result = run_script(fake_path(tmp_path, payload="no soy json"))
    assert result.returncode != 0
    assert "JSON" in result.stderr


def test_main_fails_when_a_key_is_missing(tmp_path):
    result = run_script(fake_path(tmp_path, payload='[{"Name":"x","Status":"y"}]'))
    assert result.returncode != 0
    assert "ConfigFiles" in result.stderr


def test_main_exits_zero_without_orphans(tmp_path):
    result = run_script(fake_path(tmp_path, payload="[]"))
    assert result.returncode == 0, result.stderr
    assert "huérfanos: 0" in result.stdout


def test_main_exits_zero_with_orphans(tmp_path):
    main_root, _ = module.parse_worktrees(
        subprocess.run(
            module.WORKTREE_COMMAND, cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout
    )
    orphan = main_root / ".claude/worktrees/sdd+desregistrado"
    # `json.dumps`, no f-string: una ruta con `"` o `\` dentro produciría JSON malformado y
    # un fallo engañoso en vez de ejercitar lo que este test dice ejercitar.
    payload = json.dumps(
        [
            {
                "Name": "sdddesregistrado",
                "Status": "exited(1), running(6)",
                "ConfigFiles": (
                    f"{orphan}/docker-compose.yml,{orphan}/docker-compose.worktree.yml"
                ),
            }
        ]
    )
    result = run_script(fake_path(tmp_path, payload=payload))
    assert result.returncode == 0, result.stderr
    assert "clase: huérfano" in result.stdout
    assert "huérfanos: 1" in result.stdout


def test_main_attributes_the_live_worktrees_of_this_repository(tmp_path):
    """El propio worktree desde el que corre la suite sale `vivo` con su rama, no huérfano."""
    main_root, roots = module.parse_worktrees(
        subprocess.run(
            module.WORKTREE_COMMAND, cwd=ROOT, text=True, capture_output=True, check=True
        ).stdout
    )
    payload = json.dumps(
        [
            {
                "Name": "sddaqui",
                "Status": "running(6)",
                "ConfigFiles": f"{ROOT}/docker-compose.yml",
            }
        ]
    )
    result = run_script(fake_path(tmp_path, payload=payload))
    assert result.returncode == 0, result.stderr
    assert "clase: vivo" in result.stdout
    assert f"rama: {roots[ROOT]}" in result.stdout
    assert main_root in roots


# Los comandos que D2 prohíbe. Fuera del docstring de cabecera —que es donde la lista negra
# está escrita— ninguno puede aparecer en el fichero.
BANNED_COMMANDS = ("docker inspect", "compose config", ".Labels", "shell=True")


def test_the_command_blacklist_of_d2_has_not_been_reintroduced():
    """La lista negra viaja con la suite, no con el grep a mano de tasks.md 8.3.

    Sin esto, alguien añade un `docker inspect` de diagnóstico más adelante, la suite sigue
    verde y el filtrado de `.Config.Env` / de los valores del `.env` sólo lo caza acordarse
    de correr un grep. R3.2 pide la garantía, no la buena memoria.
    """
    source = SCRIPT.read_text()
    header = ast.get_docstring(ast.parse(source))
    assert header is not None, "el script perdió su docstring de cabecera con la lista negra"
    body = source.replace(header, "", 1)
    offenders = sorted(pattern for pattern in BANNED_COMMANDS if pattern in body)
    assert not offenders, (
        f"la lista negra de D2 volvió al código de `compose-stacks.py`: {offenders}. "
        "El primero vuelca `.Config.Env` y el segundo resuelve los valores del `.env`."
    )


def test_a_nul_in_config_files_is_ambiguous_and_not_a_traceback():
    """Un NUL sale por el camino de ambigüedad de R1.4, no como `ValueError` sin capturar.

    `Path.resolve()` lo revienta con «embedded null character in path». La CLI de Docker no
    puede colarlo, pero la Engine API sí, por la etiqueta `…project.config_files`.
    """
    origin, reason = module.project_dir("/a\x00b/docker-compose.yml")
    assert origin is None
    assert reason is not None and "NUL" in reason


def test_real_docker_output_still_matches_the_contract():
    """Contra Docker de verdad: es lo que avisa el día que renombren un campo.

    Un mock de `subprocess.run` probaría el mock, y el riesgo real de este script es
    exactamente que la forma de la salida ajena cambie.
    """
    if shutil.which("docker") is None:
        pytest.skip("no hay `docker` en el `PATH`")
    completed = subprocess.run(module.PROJECTS_COMMAND, text=True, capture_output=True)
    if completed.returncode != 0:
        pytest.skip(f"`docker compose ls` no respondió: {completed.stderr.strip()[:120]}")
    module.parse_projects(completed.stdout)
