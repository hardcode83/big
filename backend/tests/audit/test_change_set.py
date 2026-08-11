"""The cleartext-sink contract of rule 11, as a test (R6.1, R6.2, design D3).

Written before `ChangeSet` existed. Its whole reason to be is that rule 11 of
`sdd/steering/security.md` stops depending on every future caller remembering it: the
only way to put a rule-3 value in `audit_logs.changes` has to raise.
"""

import enum
import json
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

import pytest

from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import REDACTED_FIELDS, ChangeSet
from app.auth.domain.enums import UserRole


def test_diff_uses_the_old_new_shape_of_the_prd() -> None:
    changes = ChangeSet("USER").diff("role", "CLEANER", "TECHNICIAN")

    assert changes.as_dict() == {"role": {"old": "CLEANER", "new": "TECHNICIAN"}}


def test_redacted_records_only_that_something_changed() -> None:
    changes = ChangeSet("USER").redacted("password")

    assert changes.as_dict() == {"password": {"changed": True}}


def test_diffs_accumulate_without_mutating_the_previous_value() -> None:
    """Immutable: every constructor returns a new ChangeSet.

    A mutable accumulator shared between two use cases in one request would leak the
    fields of the first into the audit row of the second.
    """
    first = ChangeSet("USER").diff("name", "Ana", "Ana Ruiz")
    second = first.diff("phone", None, "+34600000000")

    assert set(first.as_dict()) == {"name"}
    assert set(second.as_dict()) == {"name", "phone"}


@pytest.mark.parametrize("field", sorted(REDACTED_FIELDS))
def test_diff_refuses_every_field_of_the_denylist(field: str) -> None:
    """Rule 11: the value does not survive, not even masked. Only `redacted` is available."""
    with pytest.raises(AuditContractError) as caught:
        ChangeSet("USER").diff(field, "old-secret", "new-secret")

    assert field in str(caught.value)
    assert "old-secret" not in str(caught.value)
    assert "new-secret" not in str(caught.value)


def test_a_guests_birth_date_cannot_be_recorded_as_a_diff() -> None:
    """Added by `access-notifications` after its feature-scale security panel.

    `document_number_encrypted` was already denylisted and `date_of_birth` was not, so one
    was protected by construction and the other by whoever wrote the next caller remembering
    to use `redacted()`. The module claims the guarantee is structural; for the birth date it
    was not.

    It belongs on the list by the steering's own words — §"Datos sensibles": "PII de huéspedes
    (documento de identidad, **fecha de nacimiento** — requeridos por SES.Hospedajes)".
    """
    with pytest.raises(AuditContractError):
        ChangeSet("GUEST").diff("date_of_birth", None, "1990-05-04")

    assert ChangeSet("GUEST").redacted("date_of_birth").as_dict() == {
        "date_of_birth": {"changed": True}
    }


def test_nationality_is_denylisted_since_a_guest_became_its_writer() -> None:
    """This test asserted the opposite until `guest-portal-api`, and the premise is why.

    `access-notifications` left `nationality` diffable on the grounds that §"Datos sensibles"
    names the document and the birth date and not the nationality, and that a denylist
    quietly covering more than it says is one nobody can reason about. That reasoning held
    **while an operator was the only writer**.

    `guest-portal-api` made `POST /api/v1/guest/checkin/{token}` an anonymous endpoint that
    takes `nationality` and `full_name` from a form nobody authenticates, so both became free
    text chosen by an internet caller landing in a rule-11 sink — the same property that
    disqualified `incidents.title`/`description` in that same change. Its section 2 panel had
    two reviewers demonstrate the gap independently.

    So this is not the denylist growing quietly: it is the same criterion applied after the
    set of writers changed. Nothing is lost, because the caller already recorded it with
    `redacted()`.
    """
    with pytest.raises(AuditContractError):
        ChangeSet("GUEST").diff("nationality", None, "ES")

    assert ChangeSet("GUEST").redacted("nationality").as_dict() == {
        "nationality": {"changed": True}
    }


def test_redacted_is_available_for_a_denylisted_field_of_this_entity() -> None:
    """`password` is the one denylisted field a USER diff legitimately reports (R6.2)."""
    assert ChangeSet("USER").redacted("password").as_dict() == {"password": {"changed": True}}


@pytest.mark.parametrize("field", sorted(REDACTED_FIELDS - {"password"}))
def test_redacted_still_refuses_a_field_this_entity_does_not_have(field: str) -> None:
    """The allowlist applies to `redacted` too.

    `document_number` belongs to `Guest`, not to `User`: whoever audits guest documents
    registers `GUEST` with its own fields and inherits rule 11 there. Letting any entity
    redact any name would make `audit_logs` claim changes to columns the row does not have.
    """
    with pytest.raises(AuditContractError):
        ChangeSet("USER").redacted(field)


def test_a_denylisted_field_is_matched_case_insensitively() -> None:
    """`Password` is the same field as `password` to everyone except a string compare."""
    with pytest.raises(AuditContractError):
        ChangeSet("USER").diff("Password_Hash", "a", "b")


@pytest.mark.parametrize("value", [object(), uuid.uuid4, complex(1, 2), b"bytes"])
def test_diff_rejects_values_jsonb_cannot_store(value: object) -> None:
    with pytest.raises(AuditContractError) as caught:
        ChangeSet("USER").diff("role", "CLEANER", value)

    # The offending key is named, like TimelineEventFactory does with its metadata.
    assert "role" in str(caught.value)


@pytest.mark.parametrize("value", ["CLEANER", 42, 1.5, True, None, ""])
def test_diff_accepts_scalar_values(value: object) -> None:
    assert ChangeSet("USER").diff("name", None, value).as_dict()["name"]["new"] == value


@pytest.mark.parametrize(
    "value",
    [
        {"name": "Ana"},
        ["a", "b"],
        ("a", "b"),
        {1, 2},
        {"nested": {"deeper": "value"}},
    ],
)
def test_diff_refuses_compound_values(value: object) -> None:
    """Even under a legitimate field name, a value must be scalar (security panel, §1)."""
    with pytest.raises(AuditContractError) as caught:
        ChangeSet("USER").diff("name", None, value)

    assert "scalar" in str(caught.value).lower()


# --- the allowlist: an invented field name is refused outright ---------------------


@pytest.mark.parametrize(
    "field", ["profile_patch", "changes", "metadata", "payload", "wifi", "extra", ""]
)
def test_diff_refuses_a_field_that_is_not_a_column_of_the_entity(field: str) -> None:
    """The name is the boundary that actually holds (security re-review, §1).

    Refusing compound VALUES was not enough: `diff("profile_patch", …, json.dumps({...}))`
    smuggles the same payload as a string, and no content inspection wins that race — the
    next encoding is base64, or none. What is decidable is the NAME: an audited field must
    be a real, non-sensitive column of the entity.
    """
    with pytest.raises(AuditContractError) as caught:
        ChangeSet("USER").diff(field, None, "anything")

    assert "auditable" in str(caught.value).lower()


def test_the_serialised_compound_bypass_no_longer_works() -> None:
    """Regression for the exact payload the security re-review reproduced.

    A JSON string under an invented field name: rejected on the name, before its content
    ever matters.
    """
    with pytest.raises(AuditContractError):
        ChangeSet("USER").diff(
            "profile_patch", None, json.dumps({"wifi_password_encrypted": "gAAAA-secret"})
        )


def test_the_original_compound_bypass_no_longer_works() -> None:
    """Regression for the first payload the security panel reproduced (compound value)."""
    with pytest.raises(AuditContractError):
        ChangeSet("USER").diff(
            "profile_patch",
            {"name": "Ana"},
            {"name": "Ana", "wifi_password_encrypted": "gAAAA-secret"},
        )


def test_each_entity_has_its_own_field_allowlist() -> None:
    """A tenant-config field is not auditable on a USER row, and vice versa."""
    assert ChangeSet("TENANT_CONFIG").diff("sla_high_minutes", 15, 30)

    with pytest.raises(AuditContractError):
        ChangeSet("USER").diff("sla_high_minutes", 15, 30)

    with pytest.raises(AuditContractError):
        ChangeSet("TENANT_CONFIG").diff("role", "CLEANER", "TECHNICIAN")


def test_an_unknown_entity_type_cannot_have_a_change_set() -> None:
    """`OWNER_APPROVAL` is the example on purpose: a real table with no audit trail yet.

    The name has now moved three times, and each move is the test working as designed. It
    was `PROPERTY` until `properties-crud` registered it, then `RESERVATION` until
    `access-notifications` registered *that* — for the legal-registration and access
    projections of PRD §17 and §15, not for the module's own mutations, which
    `specs/reservations.md` still records as owed — then `INCIDENT` until `guest-portal-api`
    registered it, because the guest portal is the first thing that persists an `Incident`
    (its design D15, and the reparto rule of `specs/domain-foundation-ops.md:12`).

    `OWNER_APPROVAL` is next in rule 9's enumeration with no writer at all (`maintenance`
    brings it, with the expense-approval flow). Whoever audits it will trip on this line,
    which is the intended behaviour: registering an entity type is a decision, so a test
    asserting the opposite should demand a conscious edit rather than pass silently.
    """
    with pytest.raises(AuditContractError):
        ChangeSet("OWNER_APPROVAL")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_diff_rejects_non_finite_numbers(value: float) -> None:
    """Postgres JSONB has no NaN/Infinity: the INSERT would die at the driver.

    It would die mid-transaction, taking the audited mutation with it — the silent
    failure this module's comments claim to prevent, so it gets an anchor (QA finding, §1).
    """
    with pytest.raises(AuditContractError) as caught:
        ChangeSet("TENANT_CONFIG").diff(
            "owner_approval_threshold_eur", Decimal("100.00"), value
        )

    assert "owner_approval_threshold_eur" in str(caught.value)


def test_an_enum_is_recorded_as_its_value() -> None:
    """Callers hold `UserRole.CLEANER`, not `"CLEANER"` — converting here beats N `str()`s.

    The `type(...) is str` assertions are what make this test anchor the conversion branch.
    Equality alone does not: `UserRole` is a `str`-mixin enum, so `UserRole.CLEANER ==
    "CLEANER"` is True and the assertion would pass even with the `enum.Enum` branch of
    `_storable` deleted — the QA re-review of section 1 proved exactly that. A plain
    `enum.Enum` is checked alongside so the branch is also exercised where the fallback
    could not possibly cover for it.
    """
    recorded = ChangeSet("USER").diff("role", UserRole.CLEANER, UserRole.TECHNICIAN).as_dict()

    assert recorded["role"] == {"old": "CLEANER", "new": "TECHNICIAN"}
    assert type(recorded["role"]["old"]) is str
    assert type(recorded["role"]["new"]) is str


def test_a_plain_enum_is_recorded_as_its_value_too() -> None:
    """Not every enum is a `str` mixin — a non-mixin member is not JSONB-storable at all."""

    class Colour(enum.Enum):
        RED = "RED"

    recorded = ChangeSet("USER").diff("status", None, Colour.RED).as_dict()

    assert recorded["status"]["new"] == "RED"
    assert type(recorded["status"]["new"]) is str


def test_a_decimal_is_recorded_as_its_string_form() -> None:
    """`owner_approval_threshold_eur` is `Numeric(10,2)`: a float would lose precision."""
    recorded = (
        ChangeSet("TENANT_CONFIG")
        .diff("owner_approval_threshold_eur", Decimal("100.00"), Decimal("250.50"))
        .as_dict()
    )

    assert recorded["owner_approval_threshold_eur"] == {"old": "100.00", "new": "250.50"}


def test_dates_and_uuids_are_recorded_in_a_json_safe_form() -> None:
    """No auditable column holds one today, but `_storable` supports both.

    Exercised through a legitimate field name so the conversion branch has an anchor: the
    alternative was leaving it to the first entity that registers a date or id column, and
    discovering then that it never worked.
    """
    identifier = uuid.uuid4()

    recorded = (
        ChangeSet("USER")
        .diff("name", date(2026, 7, 30), date(2026, 7, 31))
        .diff("phone", None, datetime(2026, 7, 31, 10, 30, tzinfo=UTC))
        .diff("email", None, identifier)
        .as_dict()
    )

    assert recorded["name"] == {"old": "2026-07-30", "new": "2026-07-31"}
    assert recorded["phone"]["new"].startswith("2026-07-31T10:30")
    assert recorded["email"]["new"] == str(identifier)


def test_a_bare_time_is_stored_as_its_iso_string() -> None:
    """Added by `properties-crud`, and it was a real `500` before.

    `properties` is the first audited entity with bare `TIME` columns
    (`default_check_in_time`, `default_check_out_time`). `_storable` coerced `datetime` and
    `date` but not `time`, so patching a check-in time raised `AuditContractError` from inside
    the audit write and surfaced as a `500`. It is a scalar like the other two and JSONB stores
    the same ISO string.
    """
    recorded = (
        ChangeSet("PROPERTY")
        .diff("default_check_in_time", time(15, 0), time(16, 30))
        .as_dict()
    )

    assert recorded["default_check_in_time"] == {"old": "15:00:00", "new": "16:30:00"}


def test_an_empty_change_set_is_falsy_so_callers_can_skip_writing() -> None:
    """`PATCH` with nothing to change writes no audit row (design D15)."""
    assert not ChangeSet("USER")
    assert ChangeSet("USER").diff("name", "a", "b")


def test_a_field_cannot_be_recorded_twice() -> None:
    """Two entries for one field would make the audit row ambiguous about the diff."""
    with pytest.raises(AuditContractError):
        ChangeSet("USER").diff("name", "a", "b").diff("name", "b", "c")

    with pytest.raises(AuditContractError):
        ChangeSet("USER").redacted("password").redacted("password")


def test_as_dict_returns_a_copy() -> None:
    """Handing out the internal mapping would let a caller edit an audited diff.

    A shallow copy per entry is enough **because values are scalars** — see
    `_storable`. If compound values were ever allowed back in, this would have to become
    a deep copy (security panel finding 3 of section 1).
    """
    changes = ChangeSet("USER").diff("name", "a", "b")

    mutated = changes.as_dict()
    mutated["name"] = {"old": "tampered", "new": "tampered"}
    mutated["injected"] = {"old": None, "new": None}

    assert changes.as_dict() == {"name": {"old": "a", "new": "b"}}
