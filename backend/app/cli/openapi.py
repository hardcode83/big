"""Writes the OpenAPI contract to `backend/openapi.json`.

Run with `make openapi`, or `python -m app.cli.openapi` inside the container.
`--check` regenerates and compares instead of writing; that is what CI runs.

Both modes go through the same `_document()` here on purpose (R2.4): a workflow that
reimplemented the serialisation would drift from the command developers run, and the
check would then fail for a reason no one can reproduce locally.

Needs no database, Redis or network (R1.3): it imports the application and serialises
its schema. `Settings` requires exactly one variable to import — `jwt_secret_key`, with
a 32-character floor — and neither `database_url` nor `redis_url` opens a connection on
import, so CI generates a throwaway key rather than holding a real one (R1.4, rule 8 of
`steering/security.md`).

What this command is NOT: a safety net against incompatible API changes. Regenerating
after a rename leaves it green. It keeps the committed file truthful so the contract
diff shows up in the Pull Request that causes it; catching an incompatible change is the
frontend's typecheck against the derived types, in `frontend-ci`.
"""

import difflib
import json
import sys
from pathlib import Path
from typing import Any

from app.core.openapi import build_openapi
from app.main import create_app

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "openapi.json"

REGENERATE_HINT = "make openapi  (or: python -m app.cli.openapi)"


def serialise(schema: dict[str, Any]) -> str:
    """The one serialisation, byte-stable across runs (R1.2).

    `sort_keys` is what makes the output independent of the insertion order FastAPI and
    Pydantic happen to produce, which is the difference between a check that means
    something and a flaky one. `indent=2` keeps one key per line so the diff is readable
    in review (R1.5), and the trailing newline keeps the file POSIX-clean.

    Takes the schema rather than building it so the tests can push a document that *does*
    vary with configuration through the same code path, and prove the comparison detects
    it. Asserting only that today's document is stable proves nothing about the check.
    """
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _document() -> str:
    """The contract as it must appear on disk."""
    return serialise(build_openapi(create_app()))


def _committed() -> str | None:
    if not CONTRACT_PATH.exists():
        return None
    return CONTRACT_PATH.read_text(encoding="utf-8")


def write() -> None:
    CONTRACT_PATH.write_text(_document(), encoding="utf-8")


def check() -> int:
    """0 when the committed file matches the code, 1 otherwise (R2.1, R2.2)."""
    generated = _document()
    committed = _committed()

    if committed == generated:
        return 0

    if committed is None:
        print(
            f"openapi: {CONTRACT_PATH.name} is missing — run: {REGENERATE_HINT}",
            file=sys.stderr,
        )
        return 1

    diff = difflib.unified_diff(
        committed.splitlines(keepends=True),
        generated.splitlines(keepends=True),
        fromfile=f"{CONTRACT_PATH.name} (committed)",
        tofile=f"{CONTRACT_PATH.name} (generated from the code)",
    )
    sys.stderr.writelines(diff)
    print(
        f"\nopenapi: the committed contract no longer matches the code. "
        f"Regenerate it and commit the result: {REGENERATE_HINT}",
        file=sys.stderr,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv

    if arguments == ["--check"]:
        return check()

    if arguments:
        print(f"openapi: unexpected arguments {arguments}", file=sys.stderr)
        print("openapi: usage: python -m app.cli.openapi [--check]", file=sys.stderr)
        return 2

    write()
    print(f"openapi: wrote {CONTRACT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
