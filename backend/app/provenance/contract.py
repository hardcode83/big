"""Canonical provenance contract shared by runtime and repository tooling."""

from __future__ import annotations

import json
import re
from pathlib import Path


_CONTRACT = json.loads(
    (Path(__file__).with_name("provenance-contract.json")).read_text(encoding="utf-8")
)
FIELDS = {field["environment"]: field for field in _CONTRACT["fields"]}


def validate_contract_values(
    values: dict[str, str], *, allow_partial_absence: bool = False
) -> list[str]:
    problems: list[str] = []
    for environment, field in FIELDS.items():
        value = values.get(environment, "").strip()
        if not value:
            if allow_partial_absence:
                continue
            problems.append(f"{environment}: missing")
            continue
        pattern = field.get("pattern")
        if pattern and re.fullmatch(pattern, value) is None:
            problems.append(f"{environment}: invalid format")
            continue
        minimum = field.get("minimum")
        if minimum is not None:
            try:
                number = int(value)
            except ValueError:
                problems.append(f"{environment}: not an integer")
                continue
            if number < minimum:
                problems.append(f"{environment}: below minimum")
    return problems
