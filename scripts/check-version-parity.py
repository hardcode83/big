#!/usr/bin/env python3
"""Check the single public product version across the repository."""

import json
import os
import sys
import tomllib
from pathlib import Path


ROOT = Path(os.environ.get("CHECK_VERSION_ROOT", Path(__file__).resolve().parents[1]))


def read_version(path: Path, loader) -> str:
    try:
        value = loader(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{path.relative_to(ROOT)}: cannot read version ({exc})") from exc
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path.relative_to(ROOT)}: version is empty")
    return value.strip()


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def load_pyproject(path: Path) -> str:
    with path.open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def load_package(path: Path) -> str:
    return json.loads(path.read_text(encoding="utf-8"))["version"]


def main() -> int:
    paths = {
        "VERSION": (ROOT / "VERSION", load_text),
        "backend/pyproject.toml": (ROOT / "backend/pyproject.toml", load_pyproject),
        "frontend/package.json": (ROOT / "frontend/package.json", load_package),
    }
    values: dict[str, str] = {}
    errors: list[str] = []
    for label, (path, loader) in paths.items():
        try:
            values[label] = read_version(path, loader)
        except ValueError as exc:
            errors.append(str(exc))
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    if len(set(values.values())) != 1:
        print("error: version parity mismatch:", file=sys.stderr)
        for label, value in values.items():
            print(f"  {label}: {value}", file=sys.stderr)
        return 1
    print(f"version parity: {next(iter(values.values()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
