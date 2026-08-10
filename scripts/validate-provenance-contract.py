#!/usr/bin/env python3
"""Validate producer values against the canonical provenance contract."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path


CONTRACT = json.loads(
    (Path(__file__).with_name("provenance-contract.json")).read_text(encoding="utf-8")
)


def validate(values: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for field in CONTRACT["fields"]:
        name = field["name"]
        value = values.get(field["environment"], "").strip()
        # An empty producer value is the supported absence case. The backend's
        # atomic schema turns any incomplete combination into provenance=null.
        if not value:
            continue
        pattern = field.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            problems.append(f"{name}: value does not match the canonical format")
            continue
        minimum = field.get("minimum")
        if minimum is not None:
            try:
                number = int(value)
            except ValueError:
                problems.append(f"{name}: value is not an integer")
                continue
            if number < minimum:
                problems.append(f"{name}: value must be >= {minimum}")
    return problems


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
        {field["environment"]: os.environ.get(field["environment"], "") for field in CONTRACT["fields"]}
    )
    if problems:
        for problem in problems:
            print(f"::error::{problem}", file=sys.stderr)
        return 1
    print("provenance contract: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
