"""No versioned fixture carries card data (`reservations-webhooks` R4.4, rule 13(c)).

**Reads the FILES, not the function that writes them.** Rule 13(c) says so in those words, and it
says so because of a measured failure: in `channex-staging-adapter` an `expiration_date` was
committed because the suffix `_date` sat on an allowlist and the guard covered only one of the
three fixtures. A test that re-runs `anonymise()` over a payload it just built proves the
anonymiser works; it proves nothing about the bytes that are actually in git.

**Every fixture, discovered by glob rather than listed.** The other half of that failure was
coverage: a named list is a list somebody forgets to extend, and the file that gets forgotten is
the new one — exactly the one nobody has looked at. `test_the_guard_sees_every_versioned_fixture`
keeps the glob honest by failing if it ever matches nothing.

The needles are **derived from the anonymiser** (`scripts/anonymise.py`), never restated here.
Two copies of a denylist diverge at the first unilateral fix, and this one already has a history
of being edited on one side only.

**And the free-text half now derives its matcher too** (`free_text.find_long_digit_runs`), for
exactly the reason the paragraph above gives. It used to carry its own scanner with a closed
`13 <= n <= 19` band; when `reservations-webhooks` section 3 moved the redaction to "13 or more"
— because a PAN followed by another number merges into a run longer than 19 — this file was not
moved with it, so `4111111111111111 1225` in a committed fixture read as a 21-digit run and the
guard reported the file clean. Found by the security panel of that section. The lesson is the
one already written above, arriving a second time by a different door.
"""

import json
from pathlib import Path

import pytest

from app.integrations.infrastructure.free_text import find_long_digit_runs
from tests.integrations.conftest import FIXTURE_ROOT, load_script

anonymise = load_script("anonymise")

FIXTURES = sorted(FIXTURE_ROOT.rglob("*.json"))


def _leaves(value, path="", found=None):
    """Every (path, key, value) leaf in the structure, through dicts and lists alike.

    Lists matter specifically: the `channex-staging-adapter` incident involved a scalar inside a
    list, and a walker that only descends dicts reports a clean bill of health on it.
    """
    found = [] if found is None else found
    if isinstance(value, dict):
        for key, nested in value.items():
            _leaves(nested, f"{path}.{key}", found)
            if not isinstance(nested, (dict, list)):
                found.append((f"{path}.{key}", str(key), nested))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _leaves(item, f"{path}[{index}]", found)
    return found


def test_the_guard_sees_every_versioned_fixture() -> None:
    """The glob is the coverage, so an empty glob is a silently vacuous suite.

    Also asserts both provider directories are present: a fixture tree that lost one would still
    glob non-empty and this file would still be green.
    """
    assert FIXTURES, f"no fixtures found under {FIXTURE_ROOT}"
    directories = {path.parent.name for path in FIXTURES}
    assert {"beds24", "channex"} <= directories, directories


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_fixture_file_carries_a_card_shaped_value(fixture: Path) -> None:
    """R4.4: card-shaped KEYS must hold the anonymiser's placeholder, never a real value.

    Keyed on the value rather than on the key's absence, because the anonymiser replaces in place
    — the same reasoning the receiving boundary uses. A key whose value is already the placeholder
    is the correct state, not a finding.
    """
    payload = json.loads(fixture.read_text())

    offenders = [
        (path, value)
        for path, key, value in _leaves(payload)
        if any(needle in key.lower() for needle in anonymise.CARD_NEEDLES)
        and value not in (None, "", anonymise.PII_PLACEHOLDERS[-1][1])
        and str(value) not in _placeholders()
    ]

    assert offenders == [], f"{fixture}: {offenders}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_fixture_file_carries_a_pan_shaped_digit_run(fixture: Path) -> None:
    """The half a key-based guard cannot see: a PAN in free text, under a harmless key.

    This is the `raw_message` class of failure — the OTA's original message carries the card
    number that the provider parses `guarantee` out of, so the value travels under a key no
    denylist names. Checked on the raw bytes of the file, digits only, ignoring separators.

    The matcher is the runtime's own (`free_text.find_long_digit_runs`) so that what this guard
    calls PAN-shaped and what the receiving boundary redacts cannot drift apart — see the module
    docstring for the time they did.
    """
    raw = fixture.read_text()

    suspicious = find_long_digit_runs(raw)

    assert suspicious == [], f"{fixture}: card-length digit runs {suspicious}"


def test_the_guard_catches_what_it_claims_to() -> None:
    """A guard that has never fired is a guard nobody has tested.

    Same shape as `tests/test_layering.py::test_the_checks_actually_catch_the_escapes_they_claim_to`,
    and needed for the same reason: every assertion above passes trivially against a clean tree, so
    without this the whole file could be checking nothing at all. Both halves are exercised on
    synthetic input — the key-based one and the free-text one — including the separator forms and
    the nested-in-a-list position that defeated the previous guard.
    """
    planted = {
        "data": [{"guarantee": {"card_number": "4111111111111111"}}],
        "attributes": {"raw_message": "<pan>4111 1111 1111 1111</pan>"},
        # The shape that defeated the previous scanner: a PAN with another number stuck to it
        # merges into a 21-digit run, which a closed 13-19 band reads as "too long to be a card".
        "notes": "paid with 4111111111111111 1225",
    }

    card_keys = [
        (path, value)
        for path, key, value in _leaves(planted)
        if any(needle in key.lower() for needle in anonymise.CARD_NEEDLES)
        and str(value) not in _placeholders()
    ]
    assert card_keys, "the key-based half missed a planted card_number inside a list"

    found = find_long_digit_runs(json.dumps(planted))
    assert found, "the free-text half missed a separated PAN under a harmless key"
    assert any(len(run) > 19 for run in found), (
        "the free-text half missed the PAN-plus-expiry merge, which is the shape a closed "
        "13-19 band reads as too long to be a card"
    )

    # And it does not fire on the shapes that are legitimately in these files: a short reference,
    # a year, a price. A guard with false positives gets disabled, which is the same as absent.
    assert not find_long_digit_runs(
        json.dumps({"id": "12345", "year": 2026, "price": "123.45"})
    )


def _placeholders() -> set[str]:
    """Every replacement string the anonymiser can write, derived from its own table."""
    return {placeholder for _, placeholder in anonymise.PII_PLACEHOLDERS}
