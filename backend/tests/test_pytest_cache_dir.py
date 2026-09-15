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
