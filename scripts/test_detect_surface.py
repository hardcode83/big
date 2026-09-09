"""Anti-regression suite for the conditional-gate detection surfaces.

`ci-pr-gates-optimization` moved three always-run workflows (`frontend-tests`, `compose-ports`,
`rule11-ownership`) behind `*-detect` jobs. The invariant that keeps that safe —
`detect-surface ⊇ suite input surface`, enforced **always-run** by
`scripts/check-detect-surface.py` as a step of each `*-detect` (design D1.1.a/b/c, proposal
R5.5) — is only worth anything if a green means "it looked at this". These tests fail the day a
future edit reopens the class, covering the four scenarios of R5.5:

    (a) a suite grows its input surface without its detector growing;
    (b) a Compose file the default-discovery guard reads stops being anchored;
    (c) an invariant check is moved out of the always-run detect job into a conditional suite;
    (d) a detector would return `skip` on an input that actually changes the gate's result.

The surface/anchor logic itself lives in `scripts/check-detect-surface.py` (one source of truth);
this file only asserts against it, so the two cannot drift.
"""

import importlib.util
import re
from pathlib import Path

import pytest


_CDS_SPEC = importlib.util.spec_from_file_location(
    "check_detect_surface", Path(__file__).with_name("check-detect-surface.py")
)
cds = importlib.util.module_from_spec(_CDS_SPEC)
assert _CDS_SPEC.loader is not None
_CDS_SPEC.loader.exec_module(cds)

ROOT = cds.REPO_ROOT
WORKFLOWS_DIR = ROOT / ".github" / "workflows"

#: (detector name understood by the CLI, workflow file, detect job name).
DETECTORS = (
    ("rule11", WORKFLOWS_DIR / "rule11-ownership.yml", "rule11-ownership-detect"),
    ("compose", WORKFLOWS_DIR / "compose-ports.yml", "compose-ports-detect"),
    ("frontend", WORKFLOWS_DIR / "frontend-tests.yml", "frontend-tests-detect"),
)


# ── (a) a suite must not out-grow its detector ─────────────────────────────────────────────
# `check()` returns the input-surface paths NOT covered by the detector's anchors. Empty is the
# only green. rule11 has its own copy of this in test_rule11_ownership.py; compose and frontend
# are asserted here so all three detectors are pinned.
@pytest.mark.parametrize("workflow", ["compose", "frontend"])
def test_detect_surface_covers_suite_inputs(workflow):
    uncovered = cds.check(workflow)
    assert uncovered == [], (
        f"{workflow}-detect no ancla parte de la superficie de entrada de su suite: "
        f"{uncovered}. Amplía el `case` del detector (o el gate quedaría fail-open sobre "
        f"esas rutas). NO recortes la superficie para pasar."
    )


# ── (a′) the frontend surface must see non-`.py` scripts, or the guard has a blind spot ─────
# §12: frontend-tests-detect anchors only two *named* `.py` scripts (not `scripts/*` wholesale
# like compose/rule11). If `frontend_surface()` recognised only `scripts/*.py`, a suite step that
# ran a non-`.py` guard under `scripts/` (`bash scripts/foo.sh`, `node scripts/x.mjs`) would slip
# past this always-run check while a PR touching only that file got a green `**OMITIDA**` — the
# exact fail-open §9/§11 exist to close, reopened for the frontend gate alone.
def test_frontend_surface_regex_is_extension_agnostic():
    assert cds._root_script_refs("bash scripts/foo.sh") == ["scripts/foo.sh"]
    assert cds._root_script_refs("node scripts/x.mjs --flag") == ["scripts/x.mjs"]
    # `.py` references still match (superset of the old behaviour).
    assert cds._root_script_refs("python3 scripts/check-version-parity.py") == [
        "scripts/check-version-parity.py"
    ]
    # `.github/scripts/…` is reported by its TRUE path (covered by the `.github/scripts/*` anchor),
    # not stripped to a bare `scripts/...`.
    assert cds._root_script_refs("bash .github/scripts/extract-pr.sh") == [
        ".github/scripts/extract-pr.sh"
    ]


def test_frontend_surface_regex_is_path_prefix_agnostic():
    # F1: a repo-root script reference is a suite input however the path to the root is spelled.
    # The pre-fix lookbehind `(?<![\w./-])` excluded `/`, so it saw only the bare form and went
    # blind on every prefixed spelling — `./scripts/x` is the *idiomatic* one, not the exotic one.
    # Each of these must yield the same repo-root `scripts/...`:
    assert cds._root_script_refs("bash ./scripts/foo.sh") == ["scripts/foo.sh"]
    assert cds._root_script_refs("bash ../scripts/foo.sh") == ["scripts/foo.sh"]
    assert cds._root_script_refs('bash "$GITHUB_WORKSPACE/scripts/foo.sh"') == ["scripts/foo.sh"]
    assert cds._root_script_refs('bash "${GITHUB_WORKSPACE}/scripts/foo.sh"') == ["scripts/foo.sh"]
    assert cds._root_script_refs("( cd frontend && bash ../scripts/foo.sh )") == ["scripts/foo.sh"]
    # A bare directory reference (`pytest scripts/`) resolves to `scripts/` (covered by `scripts/*`).
    assert cds._root_script_refs("pytest scripts/ -q") == ["scripts/"]
    # A real subdirectory prefix is KEPT by its true path (§13-A): `frontend/scripts/x` is a
    # `frontend/**` input covered by `frontend/*` — reported as itself, not stripped to `scripts/x`.
    assert cds._root_script_refs("node frontend/scripts/build.js") == ["frontend/scripts/build.js"]


def test_frontend_surface_regex_is_fail_closed_on_every_root_prefix_spelling():
    # §13 (SEC-medium): the prefix rule was an ALLOW-LIST of virtual prefixes (`./`, `../`, `$VAR/`,
    # `${VAR}/`), so it silently DROPPED several mainstream bash spellings of a root reference — all
    # four below returned `[]` against the pre-fix regex, reopening the §9/§11/§12 fail-open class
    # for the frontend gate (a future suite guard written this way would leave the always-run check
    # green while a PR touching only that guard got a green **OMITIDA**). The rule is now
    # fail-closed: a `scripts/<path>` token is a ROOT reference UNLESS it is a real subdirectory of
    # an already-anchored directory (`frontend/scripts/…`, `.github/scripts/…`).
    # (1) the quote closes *before* the slash:
    assert cds._root_script_refs('bash "$ROOT"/scripts/x.sh') == ["scripts/x.sh"]
    # (2) command substitution, quoted:
    assert cds._root_script_refs(
        'bash "$(git rev-parse --show-toplevel)/scripts/x.sh"'
    ) == ["scripts/x.sh"]
    # (3) the backtick form of the same:
    assert cds._root_script_refs(
        "bash `git rev-parse --show-toplevel`/scripts/x.sh"
    ) == ["scripts/x.sh"]
    # (4) brace expansion with a modifier (`:-`):
    assert cds._root_script_refs('bash "${VAR:-.}/scripts/x.sh"') == ["scripts/x.sh"]
    # A real subdirectory prefix is kept by its true path (covered by frontend/*, .github/scripts/*).
    assert cds._root_script_refs("node frontend/scripts/build.js") == ["frontend/scripts/build.js"]
    assert cds._root_script_refs("bash .github/scripts/extract-pr.sh") == [
        ".github/scripts/extract-pr.sh"
    ]
    # Today's surface stays fully covered.
    assert cds.check("frontend") == []


def test_frontend_surface_keeps_real_directory_segments():
    # §13-A (SEC-medium, root fix): the lineage round-5 (allow-list) → fix-round-1 (virtual allow-list,
    # dropped `lib/scripts/`) → fix-round-1b (fixed-width lookbehind, dropped sibling-suffix
    # `notfrontend/`) → fix-round-2 (whole-segment deny-list, dropped nested `a/frontend/`) was a
    # recurring SILENT DROP: each round tail-stripped a real directory as if it were a path-to-root
    # prefix. The rule now KEEPS every real path segment and reports the reference by its TRUE path,
    # so an un-anchored real directory is surfaced (→ uncovered → red), never dropped. Only recognized
    # VIRTUAL path-to-root prefixes (./  $VAR/  "$X"/  $(…)/  ${…}/  `…`/) are stripped.
    assert cds._root_script_refs("bash lib/scripts/x.sh") == ["lib/scripts/x.sh"]
    assert cds._root_script_refs("bash tools/scripts/x.sh") == ["tools/scripts/x.sh"]
    assert cds._root_script_refs("bash notfrontend/scripts/x.sh") == ["notfrontend/scripts/x.sh"]
    assert cds._root_script_refs("bash sub.github/scripts/x.sh") == ["sub.github/scripts/x.sh"]
    assert cds._root_script_refs("bash a/frontend/scripts/x.sh") == ["a/frontend/scripts/x.sh"]
    assert cds._root_script_refs("bash vendor/.github/scripts/x.sh") == ["vendor/.github/scripts/x.sh"]
    # The two genuinely-anchored siblings are reported by their true path, covered by their anchors:
    assert cds._root_script_refs("node frontend/scripts/build.js") == ["frontend/scripts/build.js"]
    assert cds._root_script_refs("bash .github/scripts/extract-pr.sh") == [
        ".github/scripts/extract-pr.sh"
    ]
    # A word-char boundary prevents a false hit inside a longer token, and today's surface is covered.
    assert cds._root_script_refs("bash myscripts/x.sh") == []
    assert cds.check("frontend") == []


def test_frontend_surface_tolerates_doubled_path_separators():
    # §13-A fix-round (SEC-medium): `_REAL_SEGMENTS` first used `(?:name/)+`, which failed to match a
    # prefix with a DOUBLED separator (`notfrontend//scripts/x.sh`, plausible from a var already
    # ending in `/` or a path-join typo) — the whole real prefix was then dropped and the bare
    # `scripts/x.sh` reported (covered by `scripts/*`), a silent fail-open. `/+` now tolerates the
    # doubled slash and the ref is collapsed to a clean path, so the real directory is still surfaced.
    assert cds._root_script_refs("bash notfrontend//scripts/x.sh") == ["notfrontend/scripts/x.sh"]
    assert cds._root_script_refs("bash a/frontend//scripts/x.sh") == ["a/frontend/scripts/x.sh"]
    assert cds._root_script_refs("bash lib///scripts/x.sh") == ["lib/scripts/x.sh"]
    # A doubled slash after `scripts` is likewise collapsed, not split into a bogus token.
    assert cds._root_script_refs("bash scripts//x.sh") == ["scripts/x.sh"]
    assert cds.check("frontend") == []


def test_frontend_surface_resolves_dot_dot_segments_before_anchoring():
    # §13-A fix-round (SEC-medium): a `..` component glued onto an anchored-prefix directory
    # (`frontend/../notfrontend/scripts/x.sh`) used to be kept verbatim, and since a `case`/fnmatch
    # `*` spans `/`, `frontend/*` matched it → reported covered, while the path actually resolves to
    # an UN-anchored `notfrontend/scripts/x.sh` (silent fail-open). `posixpath.normpath` now resolves
    # `.`/`..` before the anchor comparison, so the true target is surfaced and reported uncovered.
    assert cds._root_script_refs("bash frontend/../notfrontend/scripts/x.sh") == [
        "notfrontend/scripts/x.sh"
    ]
    assert cds._root_script_refs("bash scripts/../lib/scripts/x.sh") == ["lib/scripts/x.sh"]
    assert cds._root_script_refs("bash a/./scripts/x.sh") == ["a/scripts/x.sh"]
    # The resolved `frontend/../notfrontend/...` must NOT be swallowed by the `frontend/*` anchor:
    frontend_anchors = cds.detect_anchors(WORKFLOWS_DIR / "frontend-tests.yml")
    assert cds.uncovered(
        cds._root_script_refs("bash frontend/../notfrontend/scripts/x.sh"), frontend_anchors
    ) == ["notfrontend/scripts/x.sh"]
    assert cds.check("frontend") == []


def test_frontend_detect_anchors_the_whole_scripts_tree():
    # §13-A anchor-shape pin: frontend-tests-detect now anchors `scripts/*` wholesale (like
    # compose/rule11), which is what dissolves the recurring fail-open class — any root `scripts/…`
    # is gated by the `case` on changed paths, independently of the surface parser. The two anchored
    # siblings cover their own subtrees.
    anchors = cds.detect_anchors(WORKFLOWS_DIR / "frontend-tests.yml")
    assert "scripts/*" in anchors, f"frontend-detect debe anclar `scripts/*` en bloque (§13-A): {anchors}"
    assert cds.uncovered(["scripts/foo.sh"], anchors) == []
    assert cds.uncovered(["frontend/scripts/x.ts"], anchors) == []
    assert cds.uncovered([".github/scripts/x.sh"], anchors) == []
    # But an un-anchored real directory is NOT covered → the always-run CLI would go red (fail-closed).
    assert cds.uncovered(["tools/scripts/x.sh"], anchors) == ["tools/scripts/x.sh"]


def test_frontend_surface_end_to_end_resolves_prefixes_and_fails_closed(tmp_path):
    # Drive `frontend_surface()` end-to-end, not just the regex on a string literal. Synthesize a
    # `frontend-tests-suite` job whose steps reference scripts (a) the idiomatic `./scripts/...` and
    # `$VAR/scripts/...` way — resolved to root `scripts/...` — and (b) an UN-ANCHORED real directory
    # (`tools/scripts/...`) reported by its true path. Under §13-A the root refs are covered by the
    # `scripts/*` anchor; the un-anchored real path is the fail-closed demonstration.
    workflow = tmp_path / ".github" / "workflows" / "frontend-tests.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        "jobs:\n"
        "  frontend-tests-suite:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - name: prefixed root guard\n"
        "        run: bash ./scripts/frontend-a11y-guard.sh\n"
        "      - name: var-prefixed root guard\n"
        '        run: bash "$GITHUB_WORKSPACE/scripts/frontend-perf-guard.sh"\n'
        "      - name: gh script (true path)\n"
        "        run: bash .github/scripts/extract-pr.sh --self-test\n"
        "      - name: an UN-ANCHORED real-directory guard\n"
        "        run: bash tools/scripts/frontend-viz-guard.sh\n"
        "      - name: a make target\n"
        "        run: make check-version-parity\n"
        "  frontend-tests:\n"
        "    runs-on: ubuntu-latest\n",
        encoding="utf-8",
    )
    surface = cds.frontend_surface(tmp_path)
    # Virtual path-to-root prefixes resolve to root `scripts/...`:
    assert "scripts/frontend-a11y-guard.sh" in surface, surface
    assert "scripts/frontend-perf-guard.sh" in surface, surface
    # A real subdirectory is reported by its TRUE path, not misread as a root `scripts/...`:
    assert "tools/scripts/frontend-viz-guard.sh" in surface, surface
    assert "scripts/frontend-viz-guard.sh" not in surface, surface
    # `.github/scripts/…` by its true path; `make` contributes `Makefile`:
    assert ".github/scripts/extract-pr.sh" in surface and "Makefile" in surface, surface

    # Fail-closed (D1.1.c): the root guards are covered by `scripts/*`, but the un-anchored
    # `tools/scripts/...` guard is uncovered → the always-run CLI would go red until it is anchored.
    frontend_anchors = cds.detect_anchors(WORKFLOWS_DIR / "frontend-tests.yml")
    uncovered = cds.uncovered(surface, frontend_anchors)
    assert "tools/scripts/frontend-viz-guard.sh" in uncovered, uncovered
    assert "scripts/frontend-a11y-guard.sh" not in uncovered, uncovered


# ── (b) every Compose default-discovery name must be anchored by compose-ports-detect ──────
def _compose_anchors():
    return cds.detect_anchors(WORKFLOWS_DIR / "compose-ports.yml")


def test_full_compose_discovery_family_is_anchored():
    anchors = _compose_anchors()
    # The whole family Docker Compose resolves without `-f`, whether or not the file exists
    # today: the guard runs `docker compose config` under default discovery, so any of these
    # appearing tomorrow becomes an input to the gate.
    for name in cds.COMPOSE_DISCOVERY_FAMILY:
        assert cds.uncovered([name], anchors) == [], (
            f"`{name}` es parte del descubrimiento por defecto de Docker Compose (lo leería "
            f"`docker compose config` sin `-f`) pero ninguna ancla de compose-ports-detect lo "
            f"cubre — un PR que solo lo tocara recibiría un `**OMITIDA**` verde (SEC-1/D1.1.b)."
        )


def test_compose_discovery_guard_proves_the_red():
    # Non-vacuousness: with the `compose.*` half of the family removed from the anchor set, the
    # modern canonical `compose.yaml` (which takes PRECEDENCE over docker-compose.yml) would be
    # uncovered — i.e. the assertion above is really constraining something.
    anchors = _compose_anchors()
    without_compose_star = [a for a in anchors if not a.startswith("compose")]
    assert cds.uncovered(["compose.yaml"], without_compose_star) == ["compose.yaml"], (
        "el guard de descubrimiento no está probando el rojo: `compose.yaml` debería quedar "
        "descubierto si se quitara la mitad `compose.*` de las anclas."
    )


# ── (c) the invariant check must stay always-run, inside the detect job ────────────────────
_STEP_START = re.compile(r"^(\s*)-\s")
_IF_LINE = re.compile(r"^\s*if:")


def _step_block_for(job_lines, needle):
    """The lines of the single `- ...` step within `job_lines` whose body contains `needle`.

    Textual, stdlib-only (no PyYAML on the runner path): find the matching line, walk back to its
    step bullet, forward to the next bullet at the same indent.
    """
    hit = next((i for i, ln in enumerate(job_lines) if needle in ln), None)
    assert hit is not None, f"no se encontró `{needle}` en el job"
    start = hit
    while start >= 0 and not _STEP_START.match(job_lines[start]):
        start -= 1
    assert start >= 0, f"no se encontró el inicio del step de `{needle}`"
    indent = _STEP_START.match(job_lines[start]).group(1)
    end = start + 1
    while end < len(job_lines):
        m = _STEP_START.match(job_lines[end])
        if m and m.group(1) == indent:
            break
        end += 1
    return job_lines[start:end]


@pytest.mark.parametrize("name,path,job", DETECTORS)
def test_surface_check_is_wired_always_run_in_detect_job(name, path, job):
    lines = path.read_text(encoding="utf-8").splitlines()
    job_lines = cds._job_lines(lines, job)
    assert job_lines, f"no se encontró el job `{job}` en {path.name}"
    needle = f"check-detect-surface.py {name}"
    joined = "\n".join(job_lines)
    assert needle in joined, (
        f"`{job}` no invoca `python3 scripts/check-detect-surface.py {name}` — la invariante de "
        f"superficie dejó de correr always-run (SEC-3/D1.1.c)."
    )
    block = _step_block_for(job_lines, needle)
    assert not any(_IF_LINE.match(ln) for ln in block), (
        f"el step de `check-detect-surface.py {name}` en `{job}` tiene un `if:` — debe correr "
        f"SIEMPRE (antes de la decisión de skip), no condicionado."
    )


def test_surface_check_not_only_in_conditional_suite():
    # The enforcement must not live *only* in a conditional `*-suite` job. Assert each detector's
    # invocation is in its detect job (checked above) — here we also guard against someone adding
    # it to the suite and deleting it from detect by re-confirming the detect-job placement holds
    # for all three (parametrized test above already does per-detector; this is the aggregate).
    for name, path, job in DETECTORS:
        lines = path.read_text(encoding="utf-8").splitlines()
        job_lines = cds._job_lines(lines, job)
        assert f"check-detect-surface.py {name}" in "\n".join(job_lines)


# ── (d) a detector must not skip on an input that changes the gate result ──────────────────
def _matches_any(path, anchors):
    return cds.uncovered([path], anchors) == []


def test_gate_altering_inputs_do_not_skip():
    compose_anchors = cds.detect_anchors(WORKFLOWS_DIR / "compose-ports.yml")
    rule11_anchors = cds.detect_anchors(WORKFLOWS_DIR / "rule11-ownership.yml")
    frontend_anchors = cds.detect_anchors(WORKFLOWS_DIR / "frontend-tests.yml")

    # compose.yaml changes what `docker compose config` resolves -> must trigger compose-suite.
    assert _matches_any("compose.yaml", compose_anchors), (
        "`compose.yaml` altera el gate de compose pero no casa ninguna ancla -> el detector haría skip."
    )

    # sdd/adr/x.md would be WALKED by the rule11 guard (under sdd/, not OUT_OF_CENSUS) yet is not
    # anchored -> the detector WOULD skip it; the always-run CLI is what fails the gate. Prove the
    # CLI catches it (the F4 red, generalized): it is reported uncovered.
    assert cds.uncovered(["sdd/adr/example.md"], rule11_anchors) == ["sdd/adr/example.md"], (
        "la invariante always-run no atraparía `sdd/adr/example.md`: el detector haría skip y el "
        "check de superficie no lo marcaría (SEC-3)."
    )

    # No over-trigger: a repo-root README touches none of the three areas.
    for anchors in (compose_anchors, rule11_anchors, frontend_anchors):
        assert not _matches_any("README.md", anchors), (
            "`README.md` (raíz) no debería activar ningún detector (sobre-disparo, contra R7)."
        )


def test_version_parity_regression_is_covered_by_an_always_run_gate():
    # VERSION and backend/pyproject.toml are inputs of `check-version-parity` and are deliberately
    # NOT anchored in frontend-tests-detect (that would drag the frontend suite onto every backend
    # bump). The regression they'd otherwise open (SEC-2) is closed by a dedicated always-run gate.
    frontend_anchors = cds.detect_anchors(WORKFLOWS_DIR / "frontend-tests.yml")
    assert not _matches_any("VERSION", frontend_anchors)
    assert not _matches_any("backend/pyproject.toml", frontend_anchors)

    gate = WORKFLOWS_DIR / "version-parity.yml"
    assert gate.is_file(), "falta el gate always-run `version-parity.yml` (SEC-2)."
    text = gate.read_text(encoding="utf-8")
    # Look at real YAML keys, not header-comment prose (which legitimately says "sin `paths:`").
    code_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]
    code = "\n".join(code_lines)
    assert "make check-version-parity" in code, "version-parity.yml no corre `make check-version-parity`."
    assert re.search(r"^\s*pull_request:", code, re.M), "version-parity.yml no dispara en pull_request."
    # No `paths:` key and no `if:`/detect gate -> it truly runs on every PR.
    assert not re.search(r"^\s*paths:", code, re.M), "version-parity.yml tiene `paths:` — dejaría de ser always-run."
    assert not re.search(r"^\s*if:", code, re.M), "version-parity.yml tiene un `if:` — debe correr siempre, sin gate."
    assert "-detect" not in code, "version-parity.yml no debe referenciar un detect gate — corre siempre."

    # VERSION is really one of the three sources check-version-parity compares.
    parity = (ROOT / "scripts" / "check-version-parity.py").read_text(encoding="utf-8")
    assert '"VERSION"' in parity and "backend/pyproject.toml" in parity and "frontend/package.json" in parity
