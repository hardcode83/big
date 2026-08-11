"""The two primitives the guest portal's opaque token needs (R1.1, R1.2, design D2).

Written before the implementation, as `steering/testing.md` requires for `domain/` with a
real invariant: these are two functions of pure Python and the invariants —
non-guessability and indexability — are exactly what D2 spells out.

Deliberately a near-copy of `tests/integrations/test_webhook_auth.py`. D2 chose to **copy
the shape** of `webhook_auth.py` rather than invent another one, so the tests that pin that
shape are copied too. What is *not* copied is `secrets_match`: this surface has no header
secret to compare, because the token in the path is the whole credential.
"""

import ast
import hashlib
from pathlib import Path

from app.guests.domain.portal_token import (
    TOKEN_ENTROPY_BYTES,
    generate_guest_token,
    hash_guest_token,
)


def test_a_generated_token_carries_at_least_128_bits_of_entropy() -> None:
    """R1.1: "entropía suficiente para que su adivinación no sea viable"."""
    assert TOKEN_ENTROPY_BYTES * 8 >= 128


def test_two_generated_tokens_are_never_equal() -> None:
    """R1.1, the cheap smoke test for "not derived from anything enumerable".

    A thousand draws is not a randomness test — it cannot be, in a unit suite — but it does
    catch the realistic regression, which is someone replacing the CSPRNG with something
    seeded, counted, or derived from the reservation id. A token derived from the stay is
    enumerable, and the whole surface is anonymous.
    """
    assert len({generate_guest_token() for _ in range(1000)}) == 1000


def test_the_token_is_url_safe() -> None:
    """It travels as a path segment of `/api/v1/guest/{action}/{token}` (D1).

    A `/` in it would change the shape of the route, and a `+` or `=` would need escaping —
    including inside the notification link the guest eventually receives.
    """
    for _ in range(100):
        token = generate_guest_token()
        assert "/" not in token
        assert "+" not in token
        assert "=" not in token


def test_hashing_is_deterministic_so_the_lookup_can_be_an_index() -> None:
    """D2: the unsalted hash is what makes the `UNIQUE` lookup on `token_hash` possible.

    That lookup runs **before there is a tenant**, so "exactly one row" has to be an index
    hit rather than a scan the caller narrows afterwards.
    """
    token = generate_guest_token()
    assert hash_guest_token(token) == hash_guest_token(token)


def test_the_hash_is_sha256_hex_and_fits_the_column() -> None:
    """64 hex characters, which is what `guest_access_tokens.token_hash VARCHAR(64)` takes."""
    token = generate_guest_token()
    digest = hash_guest_token(token)
    assert digest == hashlib.sha256(token.encode()).hexdigest()
    assert len(digest) == 64
    assert all(character in "0123456789abcdef" for character in digest)


def test_different_tokens_hash_differently() -> None:
    assert hash_guest_token("a") != hash_guest_token("b")


def test_the_hash_does_not_contain_the_token() -> None:
    """R1.2: a dump of `guest_access_tokens` must not hand over every live stay."""
    token = generate_guest_token()
    assert token not in hash_guest_token(token)


def test_the_module_is_pure_stdlib() -> None:
    """The dependency rule, checked here as well as in `tests/test_layering.py`.

    `test_layering.py` already rejects `sqlalchemy`/`fastapi`/`pydantic` across every
    `domain/` module by glob, so this is not that check repeated. What it adds is the
    positive statement D2 makes about *this* module — "Python puro, calcado de
    `webhook_auth.py`" — so an import of `app.core.config` for a tunable, which the glob
    test would happily allow, fails here instead. The primitives must stay callable from a
    test with nothing booted.
    """
    module_path = (
        Path(__file__).resolve().parents[2] / "app" / "guests" / "domain" / "portal_token.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"hashlib", "secrets"}, (
        f"portal_token.py imports {sorted(imported - {'hashlib', 'secrets'})}; "
        "D2 keeps it pure stdlib so the token primitives need nothing booted"
    )
