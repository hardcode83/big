import tomllib
from pathlib import Path


_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def package_version() -> str:
    with _PYPROJECT.open("rb") as handle:
        return str(tomllib.load(handle)["project"]["version"])
