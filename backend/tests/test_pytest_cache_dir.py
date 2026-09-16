"""R2.3 (`ci-runner-workspace-pollution`): if the configured `cache_dir` isn't writable, the
suite must still run — pytest degrades to a warning instead of failing. `backend/pyproject.toml`
relies entirely on pytest's own built-in handling for this (no code of ours implements it), and
the only prior evidence was a one-time manual reproduction (tasks.md, section 1, task 1.4:
`docker compose run --rm --no-deps -v .../pytest_cache:ro ...`, run inside the container as
root). This automates that same reproduction so a future pytest upgrade or `cache_dir` change
can't silently regress it without a test going red.

**Why the blocker is a file, not a chmod'd directory.** `migrate`/`backend`/`worker`/`beat` all
run as root (no `user:` in `docker-compose.yml` — see `local-environment` spec), and root ignores
permission bits, so a `chmod 0o500` directory would not actually block a write here — confirmed
by running that version of this test in the real backend container, where it silently could not
force the failure path. A regular *file* where `cache_dir` expects a directory blocks `mkdir`
with `ENOTDIR` unconditionally, root included: it is a structural impossibility, not a permission
check, so it reproduces the same failure pytest's cache plugin has to handle either way.
"""

import subprocess
import sys
import tomllib
from pathlib import Path


def test_configured_cache_dir_resolves_outside_the_repo_tree():
    """R2.1/R1.2 (`ci-runner-workspace-pollution`, round 18, `sdd-qa`): R1's causal setting
    (`PYTHONDONTWRITEBYTECODE`) has a CI guard (`scripts/compose-bytecode.py`, R5) that fails the
    build if it's ever removed — a regression there cannot land silently. R2's causal setting
    (this `cache_dir` value) had no equivalent: nothing previously asserted the configured path
    actually resolves outside the repo, so an edit that moved it back under `backend/` (a
    refactor dropping the `/tmp/` prefix, or a careless merge conflict resolution) would pass
    every existing guard and test, and only surface the next time someone happened to run `git
    status --porcelain` after `make up` — reproducing the exact 2026-09-14 incident this whole
    change exists to prevent, silently. This is deliberately independent of R2.3's test above:
    that one proves pytest degrades gracefully when the configured path is unusable, not that
    the configured path is the RIGHT one.
    """
    pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
    config = tomllib.loads(pyproject_path.read_text())
    cache_dir = config["tool"]["pytest"]["ini_options"]["cache_dir"]

    backend_dir = pyproject_path.parent  # pytest resolves a relative cache_dir against this
    repo_root = backend_dir.parent
    # A relative value (e.g. a regression that dropped the "/tmp/" prefix back to
    # ".pytest_cache") must be resolved against `backend_dir` the same way pytest itself would,
    # not compared as a bare string — otherwise a relative-path regression would silently pass
    # this check (a relative path is never `is_relative_to` an absolute one, regardless of where
    # it actually points).
    resolved = (backend_dir / cache_dir).resolve() if not Path(cache_dir).is_absolute() else Path(cache_dir)
    assert not resolved.is_relative_to(repo_root), (
        f"cache_dir={cache_dir!r} resolves to {resolved} — inside the repo tree ({repo_root}), "
        "which is exactly the pollution R1/R2 exist to prevent"
    )


def test_unwritable_cache_dir_degrades_to_a_warning_instead_of_failing(tmp_path):
    blocker = tmp_path / "not_a_directory"
    blocker.write_text("this is a file, not a directory\n")
    unusable_cache_dir = blocker / "cache"  # mkdir under a file -> ENOTDIR, even as root

    project = tmp_path / "proj"
    project.mkdir()
    (project / "test_trivial.py").write_text("def test_ok():\n    assert True\n")
    (project / "pytest.ini").write_text(f"[pytest]\ncache_dir = {unusable_cache_dir}\n")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(project)],
        capture_output=True,
        text=True,
        timeout=30,
    )

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "1 passed" in combined
    # Not just "it happened to pass" — confirm the failure path was genuinely exercised: pytest's
    # own cache plugin must have hit the unusable path and warned, exactly like the manual
    # reproduction's `PytestCacheWarning: could not create cache path ...`.
    assert "could not create cache path" in combined.lower() or "cachewarning" in combined.lower(), (
        "expected pytest's cache-write-failure warning — if this is missing, the blocker path "
        "did not actually stop the write and this test isn't exercising R2.3"
    )
