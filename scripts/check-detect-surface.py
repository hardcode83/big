#!/usr/bin/env python3
"""Always-run invariant: `detect-surface ⊇ suite-input-surface` for a conditional gate.

Three PR gates (`frontend-tests`, `compose-ports`, `rule11-ownership`) were made conditional
on a `*-detect` job: the expensive suite runs only when the detector says the diff touches the
area. That is a saving only while the detector's anchor set is a *superset* of everything the
suite actually consumes. If the suite grows an input the detector does not anchor, a PR that
touches only that input gets a green `**OMITIDA**` without the suite ever running — the
fail-open class §9/§11 of `ci-pr-gates-optimization` exists to close (design D1.1/D1.1.b/D1.1.c,
proposal R1.2/R5.1/R5.2/R5.5).

This module computes, for one named detector, the set of suite-input paths NOT covered by the
on-disk `case "$f" in` anchors of that `*-detect` job, prints each uncovered path, and exits 1
if any (exit 0 otherwise). It is wired **always-run inside each `*-detect` job**, before the
skip decision, so the check runs on the very PR that would open the gap — the temporal
invariant D1.1.c. An incomplete surface aborts the detect job → the consolidator sees
`DETECT_RESULT != success` → **fail-closed** (red), distinct from the fail-open on an ambiguous
diff (which runs the suite).

Pure stdlib (argparse/fnmatch/importlib/re/pathlib/sys): it runs on the runner's `python3`,
with no `uv` and no third-party deps. The anchor-parsing (`detect_anchors`) and the coverage
matcher (`uncovered`) are the single source of truth that `scripts/test_rule11_ownership.py`
and `scripts/test_detect_surface.py` import — one definition of "does this anchor cover this
path", never a second copy that can drift.

Known limitations (frontend surface only — D1.1.c). `frontend_surface()` reads the literal
`run:` text of `frontend-tests-suite`; it does NOT follow indirection:
  - `make <target>` contributes `Makefile` but the recipe body is not resolved, so a *new*
    script a Make target invokes is seen only if the target's own inputs (`Makefile`) or that
    script's path already appears verbatim somewhere the model reads. Today this is covered by
    other means: `check-version-parity.py` (run via `make check-version-parity`) is anchored
    because a human listed it in the `case`, and its always-run gate `version-parity.yml`
    (SEC-2) runs it unconditionally regardless — but the *class* is open for any future Make
    target the frontend suite grows.
  - a local composite action (`uses: ./.github/actions/**`) is not modelled at all; its own
    `run:` steps are outside this parser. `.github/scripts/*` (anchored) is the covered form.
  - a root-script path assembled at runtime out of pieces that never appear literally on the line
    (`d=scripts; bash "$d/x.sh"`, a path read from a file or built in a loop variable) is invisible
    to any textual model. `_root_script_refs` reads the literal `run:` text; write the path literally.
These are residuals, not fail-open holes for the inputs that exist today; anchor those inputs
explicitly (or add them to the surface here) if the suite grows such a reference.

`_root_script_refs` is **fail-closed** (§13, option A): for each `scripts/<tail>` token it strips a
recognized *virtual* path-to-root prefix (`./`, `../`, `$VAR/`, `${VAR:-.}/`, `"$ROOT"/`, `$(…)/`,
`` `…`/ ``) and KEEPS any real directory segment, reporting the reference by its true repo-relative
path (`./scripts/x` → `scripts/x`; `lib/scripts/x` → `lib/scripts/x`; `frontend/scripts/x` →
`frontend/scripts/x`; `.github/scripts/x` → `.github/scripts/x`). There is no frontend/.github
special-casing: each is covered by its own anchor (`frontend/*`, `.github/scripts/*`), and a root
`scripts/…` by `scripts/*` — the anchor added in §13-A that dissolves the fail-open class, since the
detect `case` then gates the whole real `scripts/` tree on the changed paths, independent of this
parser. An unrecognized prefix spelling is not stripped, so the token is kept literally and reported
uncovered if unanchored (over-match → red), never dropped silently.
"""

import argparse
import fnmatch
import importlib.util
import posixpath
import re
import sys
from pathlib import Path

#: One origin: this file lives in `scripts/`, so the repo root is its parent's parent.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: The Docker Compose default-discovery family (D1.1.b). `scripts/compose-ports.py` runs
#: `docker compose config` with NO `-f`, so Compose applies default discovery: the first of
#: `compose.yaml` > `compose.yml` > `docker-compose.yaml` > `docker-compose.yml`, auto-loading
#: any `*.override.{yaml,yml}`. The modern `compose.*` names take precedence over
#: `docker-compose.yml`, so all eight are gate-altering inputs.
COMPOSE_DISCOVERY_FAMILY = (
    "compose.yaml",
    "compose.yml",
    "compose.override.yaml",
    "compose.override.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
    "docker-compose.override.yaml",
    "docker-compose.override.yml",
)


# ── The two shared helpers (single source of truth) ────────────────────────────────────────


def detect_anchors(workflow_path: Path) -> list[str]:
    """Parse the `case "$f" in … )` anchor globs of a workflow's single `*-detect` job.

    Each candidate workflow (`frontend-tests.yml`, `compose-ports.yml`, `rule11-ownership.yml`)
    has exactly one `case "$f" in` statement — the `decide` step of its `*-detect` job. Its
    pattern line is the line right after it: one or more shell-`case`-style globs separated by
    ` | `, closed with a trailing `)`.
    """
    lines = workflow_path.read_text(encoding="utf-8").splitlines()
    case_lines = [i for i, line in enumerate(lines) if line.strip() == 'case "$f" in']
    if len(case_lines) != 1:
        raise ValueError(
            f'expected exactly one `case "$f" in` in {workflow_path}, found {len(case_lines)} '
            "— this parser assumes a single detect job in the workflow file"
        )
    pattern_line = lines[case_lines[0] + 1].strip()
    if not pattern_line.endswith(")"):
        raise ValueError(
            f'expected the anchor line right after `case "$f" in` to end with `)`, got: '
            f"{pattern_line!r}"
        )
    anchors = [token.strip() for token in pattern_line[:-1].split("|")]
    anchors = [a for a in anchors if a]
    if not anchors:
        raise ValueError(f"no anchors parsed from {pattern_line!r}")
    return anchors


def uncovered(relatives, anchors) -> list[str]:
    """`relatives` (repo-relative path strings) not matched by any of `anchors`.

    `fnmatch.fnmatchcase` reproduces shell-`case` `*` semantics (a `*` matches any depth,
    including `/`), which is what the workflow's `case "$f" in` actually evaluates — a
    `pathlib`/`glob` match would be a different, stricter semantics that this invariant must
    not use.
    """
    return sorted(
        {
            relative
            for relative in relatives
            if not any(fnmatch.fnmatchcase(relative, anchor) for anchor in anchors)
        }
    )


# ── Left side: the suite input surface, per detector ───────────────────────────────────────


def _rule11_module():
    """Load `scripts/rule11-ownership.py` (a hyphenated filename) the way its test does."""
    spec = importlib.util.spec_from_file_location(
        "rule11_ownership", Path(__file__).with_name("rule11-ownership.py")
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def rule11_surface() -> list[str]:
    """Every file the rule 11 guard would actually walk.

    `prose_files`/`code_files` walk `SCOPE` with the `OUT_OF_CENSUS` exclusions and the
    authority already applied, so this is exactly the corpus a PR could put out of census —
    the left side of `relevant-SCOPE-walked-surface(rule11) ⊆ detect-anchor-surface(rule11)`.
    """
    module = _rule11_module()
    return [
        relative
        for relative, _ in module.prose_files(module.SCOPE, module.REPO_ROOT)
        + module.code_files(module.SCOPE, module.REPO_ROOT)
    ]


def compose_surface(root: Path = REPO_ROOT) -> list[str]:
    """The compose suite's input surface that EXISTS in the tree.

    The suite runs `make check-compose-ports` (→ `scripts/compose-ports.py`, which resolves the
    Compose default-discovery file) plus `pytest scripts/ -q` (the whole `scripts/` tree). So
    the left side is: the discovery-family files that exist, every path under `scripts/`, and
    `Makefile`. Only existing paths are included — the anti-regression test asserts the whole
    family is anchored regardless of existence; here the left side is what a PR could actually
    touch today, so the CLI exits 0.
    """
    surface: list[str] = []
    for name in COMPOSE_DISCOVERY_FAMILY:
        if (root / name).is_file():
            surface.append(name)
    scripts_dir = root / "scripts"
    if scripts_dir.is_dir():
        for path in sorted(scripts_dir.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue  # transient bytecode, not a suite input
            surface.append(path.relative_to(root).as_posix())
    if (root / "Makefile").is_file():
        surface.append("Makefile")
    return surface


#: Job whose `run:` blocks define the frontend suite's cross-area executable surface.
_FRONTEND_SUITE_JOB = "frontend-tests-suite"

_MAKE_TARGET = re.compile(r"\bmake\s+([A-Za-z0-9_.-]+)")

#: A `scripts/<tail>` token, at a path-component boundary. The lookbehind rejects a mid-token hit
#: (`myscripts/`, `foo.scripts/`) but accepts one preceded by `/` (a directory prefix) or by a
#: non-path boundary (whitespace/`=`/quote/`(`). The leading real path segment, if any, is recovered
#: separately by `_root_script_refs`.
_SCRIPTS_TAIL = re.compile(r"(?<![A-Za-z0-9_.-])scripts/[A-Za-z0-9_./-]*")
#: A recognized VIRTUAL path-to-root prefix at the END of the text before a token — a shell construct
#: that means "from the repo root" and is stripped so the reference resolves to its true repo-relative
#: path: `./`, `../`, `$VAR/`, `${…}/` (modifiers included), `$(…)/`, `` `…`/ ``, `"…"/`, `'…'/`.
_VIRTUAL_PREFIX = re.compile(r"(?:\.\.?|\$\w+|\$\{[^}]*\}|\$\([^)]*\)|`[^`]*`|\"[^\"]*\"|'[^']*')/\Z")
#: The maximal run of REAL path segments at the END of the (post-virtual-strip) text before a token.
#: `/+` (not `/`) tolerates a doubled separator (`a//b/`, from a var that already ends in `/` or a
#: path-join typo) so the whole real prefix is still captured — never dropped for failing to decompose.
#: `.`/`..` components are allowed here and resolved afterward by `posixpath.normpath`.
_REAL_SEGMENTS = re.compile(r"(?:[A-Za-z0-9_.-]+/+)+\Z")


def _root_script_refs(line: str) -> list[str]:
    """Every `scripts/…` reference on `line`, resolved to its true repo-relative path.

    Two hazards this closes:

    1. **Extension-agnostic** (§12). The suite may run a non-`.py` guard under `scripts/` (`bash
       scripts/foo.sh`, `node scripts/x.mjs`); any script name counts, not only `.py`.

    2. **Path-prefix-aware, fail-closed by keeping real segments** (§13, option A). For each
       `scripts/<tail>` token we strip a recognized *virtual* path-to-root prefix (`./`, `$VAR/`,
       `"$ROOT"/`, `$(…)/`, `` `…`/ ``, `${VAR:-.}/`, …) so `./scripts/x` and `"$ROOT"/scripts/x`
       both resolve to `scripts/x` — and then KEEP whatever *real* directory segments remain, so a
       genuine nested path is reported by its true path: `lib/scripts/x` → `lib/scripts/x`,
       `a/frontend/scripts/x` → `a/frontend/scripts/x`, `.github/scripts/x` → `.github/scripts/x`,
       `frontend/scripts/x` → `frontend/scripts/x`. There is NO frontend/.github special-casing:
       `frontend/scripts/…` is covered because `frontend/*` is an anchor, `.github/scripts/…` because
       `.github/scripts/*` is, and a root `scripts/…` because `scripts/*` is (that anchor, added in
       §13-A, is what dissolves the class — the whole real `scripts/` tree is gated by the detect
       `case` on changed paths, independently of this parser).

    Direction of error: OVER-match, never under-match. An unrecognized prefix spelling is NOT stripped,
    so the token is kept as a literal path — if it is not anchored, `check()` reports it and the
    `*-detect` job goes red (a human resolves it), never a green `**OMITIDA**`. Residual (documented,
    no instance in this repo): a `scripts/…` whose path is assembled at runtime from pieces not
    literal on the line (`d=scripts; bash "$d/x.sh"`); write such a path literally.
    """
    refs: list[str] = []
    for match in _SCRIPTS_TAIL.finditer(line):
        prefix = line[: match.start()]
        while (virtual := _VIRTUAL_PREFIX.search(prefix)) is not None:
            prefix = prefix[: virtual.start()]  # strip one virtual path-to-root segment, repeat
        real = _REAL_SEGMENTS.search(prefix)
        ref = (real.group() if real else "") + match.group()
        # Canonicalize: resolve `.`/`..` and collapse repeated `/` so the reported path compares
        # cleanly against the glob anchors — a `frontend/../notfrontend/scripts/x` cannot masquerade
        # as `frontend/*`; it resolves to `notfrontend/scripts/x` and is reported uncovered (red).
        # Preserve a trailing slash so a bare-dir reference (`pytest scripts/`) stays `scripts/`.
        normalized = posixpath.normpath(ref)
        if ref.endswith("/") and not normalized.endswith("/"):
            normalized += "/"
        refs.append(normalized)
    return refs


def _job_lines(lines: list[str], job_name: str) -> list[str]:
    """The lines of one job block (2-space-indented header under `jobs:`) up to the next job."""
    header = re.compile(r"^  [A-Za-z0-9_-]+:\s*$")
    start = None
    for i, line in enumerate(lines):
        if line.rstrip() == f"  {job_name}:":
            start = i
            break
    if start is None:
        raise ValueError(f"job `{job_name}` not found")
    end = len(lines)
    for i in range(start + 1, len(lines)):
        if header.match(lines[i]):
            end = i
            break
    return lines[start + 1 : end]


def _run_texts(job_lines: list[str]) -> list[str]:
    """Every `run:` step's command text within a job block (inline and block-scalar)."""
    texts: list[str] = []
    i = 0
    n = len(job_lines)
    while i < n:
        line = job_lines[i]
        match = re.match(r"^(\s*)run:\s*(.*)$", line)
        if not match:
            i += 1
            continue
        indent = len(match.group(1))
        remainder = match.group(2).strip()
        if remainder in ("", "|", "|-", "|+", ">", ">-", ">+"):
            # Block scalar: collect following lines indented deeper than the `run:` key.
            body: list[str] = []
            j = i + 1
            while j < n:
                nxt = job_lines[j]
                if nxt.strip() == "":
                    body.append("")
                    j += 1
                    continue
                if len(nxt) - len(nxt.lstrip(" ")) > indent:
                    body.append(nxt)
                    j += 1
                    continue
                break
            texts.append("\n".join(body))
            i = j
        else:
            texts.append(remainder)
            i += 1
    return texts


def frontend_surface(root: Path = REPO_ROOT) -> list[str]:
    """Executables the frontend suite runs OUTSIDE `frontend/**`.

    Parsed from the `run:` blocks of `frontend-tests-suite`: every `scripts/…` reference resolved to
    its true repo-relative path by `_root_script_refs` (a root `scripts/…`, a `.github/scripts/…`, or
    a real nested path — all reported by their literal path), plus `Makefile` for each `make <target>`.
    The npm steps run under `working-directory: frontend`, so they are `frontend/**` inputs already
    anchored by `frontend/*` and are not part of this cross-area surface.
    """
    workflow = root / ".github/workflows/frontend-tests.yml"
    lines = workflow.read_text(encoding="utf-8").splitlines()
    job_lines = _job_lines(lines, _FRONTEND_SUITE_JOB)
    surface: set[str] = set()
    for text in _run_texts(job_lines):
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if stripped.startswith("#"):
                continue  # a bash comment line is not an executed reference
            if _MAKE_TARGET.search(raw_line):
                surface.add("Makefile")
            surface.update(_root_script_refs(raw_line))
    return sorted(surface)


# ── The CLI ────────────────────────────────────────────────────────────────────────────────

#: workflow name → (surface function, detect workflow file). One entry per conditional gate.
WORKFLOWS = {
    "rule11": (rule11_surface, REPO_ROOT / ".github/workflows/rule11-ownership.yml"),
    "compose": (compose_surface, REPO_ROOT / ".github/workflows/compose-ports.yml"),
    "frontend": (frontend_surface, REPO_ROOT / ".github/workflows/frontend-tests.yml"),
}


def check(workflow: str) -> list[str]:
    """The suite-input paths of `workflow` not covered by its `*-detect` anchors."""
    surface_fn, workflow_path = WORKFLOWS[workflow]
    return uncovered(surface_fn(), detect_anchors(workflow_path))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Assert detect-surface ⊇ suite-input-surface for a conditional PR gate. "
            "Exit 1 (naming the uncovered paths) if the suite consumes an input the "
            "detector does not anchor."
        )
    )
    parser.add_argument("workflow", choices=sorted(WORKFLOWS), help="which detector to check")
    args = parser.parse_args(argv)

    gaps = check(args.workflow)
    if gaps:
        print(
            f"[{args.workflow}] detect-surface does NOT cover every suite input — a PR touching "
            "only one of these paths would get a green **OMITIDA** without the suite running:",
            file=sys.stderr,
        )
        for path in gaps:
            print(f"  {path}", file=sys.stderr)
        print(
            "Fix: add the missing anchor to the `*-detect` `case \"$f\" in` (or, for rule11, "
            "declare the path OUT_OF_CENSUS in SCOPE if it belongs to the exclusions). Never "
            "shrink the suite input to make this pass.",
            file=sys.stderr,
        )
        return 1

    print(f"[{args.workflow}] OK: detect-surface covers the whole suite input surface.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
