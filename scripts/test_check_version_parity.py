import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/check-version-parity.py"


def run_script(root: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=root,
        env={**os.environ, "CHECK_VERSION_ROOT": str(root)},
        text=True,
        capture_output=True,
    )


def test_current_versions_match():
    result = run_script()
    assert result.returncode == 0, result.stderr


def test_missing_version_is_named_and_fails(tmp_path):
    shutil.copy(ROOT / "VERSION", tmp_path / "VERSION")
    (tmp_path / "backend").mkdir()
    shutil.copy(ROOT / "backend/pyproject.toml", tmp_path / "backend/pyproject.toml")
    (tmp_path / "frontend").mkdir()
    package = tmp_path / "frontend/package.json"
    data = json.loads((ROOT / "frontend/package.json").read_text(encoding="utf-8"))
    del data["version"]
    package.write_text(json.dumps(data), encoding="utf-8")
    result = run_script(tmp_path)
    assert result.returncode != 0
    assert "frontend/package.json" in result.stderr
