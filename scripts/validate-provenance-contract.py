#!/usr/bin/env python3
"""Validate producer values against the canonical provenance contract."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))
from app.provenance.contract import _CONTRACT, validate_contract_values  # noqa: E402


def validate(values: dict[str, str]) -> list[str]:
    return validate_contract_values(values, allow_partial_absence=True)


def self_test() -> None:
    valid = {
        "APP_PROVENANCE_REPOSITORY_URL": "https://github.com/example/project",
        "APP_PROVENANCE_PULL_REQUEST_NUMBER": "42",
        "APP_PROVENANCE_COMMIT_SHA": "a" * 40,
        "APP_PROVENANCE_ACTIONS_RUN_ID": "123456",
    }
    assert validate(valid) == []
    assert validate({**valid, "APP_PROVENANCE_PULL_REQUEST_NUMBER": ""}) == []
    assert validate({**valid, "APP_PROVENANCE_REPOSITORY_URL": "https://gitlab.com/example/project"})
    assert validate({**valid, "APP_PROVENANCE_REPOSITORY_URL": "https://github.com/example/project?query=private"})
    assert validate({**valid, "APP_PROVENANCE_COMMIT_SHA": "A" * 40})
    assert validate({**valid, "APP_PROVENANCE_ACTIONS_RUN_ID": "0"})
    print("provenance contract self-test: ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    problems = validate(
        {field["environment"]: os.environ.get(field["environment"], "") for field in _CONTRACT["fields"]}
    )
    if problems:
        for problem in problems:
            print(f"::error::{problem}", file=sys.stderr)
        return 1
    print("provenance contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
