"""The `AccessRecord` state machine (R2, design D14).

Written before the methods (`steering/testing.md`: TDD in `domain/` where there is a real
invariant). **Every transition, including the invalid ones** — DoD §28.19 asks for exactly
that, and an access record is where it matters: `DELIVERED` is an operator asserting the
guest can get in, and reaching it from `PENDING` would mean asserting it about a code that
was never registered.

The valid moves of design D14:

    PENDING           -> MANUAL_ADDED | CREATED_EXTERNAL | REVOKED
    MANUAL_ADDED      -> DELIVERED | REVOKED | EXPIRED
    CREATED_EXTERNAL  -> DELIVERED | REVOKED | EXPIRED
    DELIVERED         -> REVOKED | EXPIRED
    EXPIRED, REVOKED  -> (terminal)

The defaults test that used to be this file's whole content is kept at the bottom: it
predates the methods and still pins what a freshly reconstructed row looks like.
"""

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.access.domain.entities import AccessRecord
from app.access.domain.enums import AccessCreatedMode, AccessProvider, AccessRecordStatus
from app.access.domain.exceptions import (
    AccessCodeInNotesError,
    AccessCodeRequiredError,
    InvalidAccessTransitionError,
)

NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)


def _record(status: AccessRecordStatus = AccessRecordStatus.PENDING) -> AccessRecord:
    return AccessRecord(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        created_at=NOW,
        updated_at=NOW,
        reservation_id=uuid.uuid4(),
        status=status,
    )


# --- the transitions that carry an operator's intent ------------------------------


def test_registering_a_code_stores_only_its_mask() -> None:
    """R2.2 and design D9: `code_masked` is the only trace, and there is no other column."""
    record = _record()

    record.register_manual_code("481523", notes="taped to the door frame", now=NOW)

    assert record.status is AccessRecordStatus.MANUAL_ADDED
    assert record.code_masked == "****23"
    assert record.created_mode is AccessCreatedMode.MANUAL
    assert record.provider is AccessProvider.MANUAL
    assert record.notes == "taped to the door frame"
    assert record.updated_at == NOW
    # The invariant that makes design D9 true rather than merely intended.
    assert "481523" not in repr(record)
    assert not any(
        isinstance(value, str) and "481523" in value for value in vars(record).values()
    )


def test_an_empty_code_is_refused_rather_than_masked_into_nothing() -> None:
    """`mask_access_code("")` returns `"****"`, which looks exactly like a real mask.

    Storing it would make the record claim a code exists when none does — and `DELIVERED`
    would then be an operator asserting a guest received nothing.
    """
    record = _record()

    with pytest.raises(AccessCodeRequiredError):
        record.register_manual_code("   ", notes=None, now=NOW)

    assert record.status is AccessRecordStatus.PENDING
    assert record.code_masked is None


def test_the_code_pasted_into_the_notes_is_refused() -> None:
    """The leak the masking left open, found by the feature-scale security panel.

    `notes` travels on the SAME request as `code`, is persisted verbatim in
    `access_records.notes` and is served in every listing to every holder of
    `READ_ACCESS_RECORDS`. So the one request that exists in order **not** to store a code
    stored it, one field over — and R2.6 says "en ningún punto".

    This is the only place in the system where both strings are in hand, which is why the
    check is here.
    """
    record = _record()

    with pytest.raises(AccessCodeInNotesError):
        record.register_manual_code(
            "481523", notes="puerta 481523, timbre 2", now=NOW
        )

    assert record.status is AccessRecordStatus.PENDING
    assert record.code_masked is None
    assert record.notes is None


def test_notes_that_do_not_contain_the_code_are_kept() -> None:
    """The check must not make `notes` useless — PRD §15 puts it on the adapter signature."""
    record = _record()

    record.register_manual_code("481523", notes="la llave está con el vecino", now=NOW)

    assert record.notes == "la llave está con el vecino"


def test_marking_external_records_that_the_provider_manages_it() -> None:
    record = _record()

    record.mark_external_managed(notes="GrinPass imported it from the PMS", now=NOW)

    assert record.status is AccessRecordStatus.CREATED_EXTERNAL
    assert record.provider is AccessProvider.EXTERNAL_MANAGED
    assert record.created_mode is AccessCreatedMode.EXTERNAL_PMS_AUTOMATIC
    # No code of ours: PRD §15 says the provider creates and delivers it.
    assert record.code_masked is None


@pytest.mark.parametrize(
    "origin", [AccessRecordStatus.MANUAL_ADDED, AccessRecordStatus.CREATED_EXTERNAL]
)
def test_delivery_is_confirmed_from_either_way_of_having_a_code(origin) -> None:
    record = _record(origin)

    record.mark_delivered(now=NOW)

    assert record.status is AccessRecordStatus.DELIVERED


def test_revoking_records_why_without_touching_the_mask() -> None:
    record = _record()
    record.register_manual_code("481523", notes=None, now=NOW)

    record.revoke(reason="reservation cancelled", now=NOW + timedelta(hours=1))

    assert record.status is AccessRecordStatus.REVOKED
    assert record.updated_at == NOW + timedelta(hours=1)
    # The mask survives: it is the record of what existed.
    assert record.code_masked == "****23"
    assert record.notes is not None and "reservation cancelled" in record.notes


def test_expiring_needs_a_code_to_have_existed() -> None:
    record = _record(AccessRecordStatus.DELIVERED)

    record.expire(now=NOW)

    assert record.status is AccessRecordStatus.EXPIRED


# --- every transition, valid and invalid, one case each (DoD §28.19) --------------

VALID: dict[str, set[AccessRecordStatus]] = {
    "register_manual_code": {AccessRecordStatus.PENDING},
    "mark_external_managed": {AccessRecordStatus.PENDING},
    "mark_delivered": {
        AccessRecordStatus.MANUAL_ADDED,
        AccessRecordStatus.CREATED_EXTERNAL,
    },
    "revoke": {
        AccessRecordStatus.PENDING,
        AccessRecordStatus.MANUAL_ADDED,
        AccessRecordStatus.CREATED_EXTERNAL,
        AccessRecordStatus.DELIVERED,
    },
    "expire": {
        AccessRecordStatus.MANUAL_ADDED,
        AccessRecordStatus.CREATED_EXTERNAL,
        AccessRecordStatus.DELIVERED,
    },
}

EXPECTED_RESULT = {
    "register_manual_code": AccessRecordStatus.MANUAL_ADDED,
    "mark_external_managed": AccessRecordStatus.CREATED_EXTERNAL,
    "mark_delivered": AccessRecordStatus.DELIVERED,
    "revoke": AccessRecordStatus.REVOKED,
    "expire": AccessRecordStatus.EXPIRED,
}


def _invoke(record: AccessRecord, operation: str) -> None:
    if operation == "register_manual_code":
        record.register_manual_code("481523", notes=None, now=NOW)
    elif operation == "mark_external_managed":
        record.mark_external_managed(notes=None, now=NOW)
    elif operation == "mark_delivered":
        record.mark_delivered(now=NOW)
    elif operation == "revoke":
        record.revoke(reason="cancelled", now=NOW)
    else:
        record.expire(now=NOW)


@pytest.mark.parametrize("operation", sorted(VALID))
@pytest.mark.parametrize("origin", list(AccessRecordStatus))
def test_the_whole_transition_matrix(operation: str, origin: AccessRecordStatus) -> None:
    """One case per (operation, starting state) — 30 of them, valid and invalid alike.

    Enumerating rather than listing the refusals by hand is what makes this survive a new
    enum value: adding one to `AccessRecordStatus` adds five cases here automatically, and
    they fail until somebody decides what the new state may do.
    """
    record = _record(origin)

    if origin in VALID[operation]:
        _invoke(record, operation)
        assert record.status is EXPECTED_RESULT[operation]
        return

    with pytest.raises(InvalidAccessTransitionError) as excinfo:
        _invoke(record, operation)

    assert excinfo.value.current == origin.value
    assert record.status is origin


def test_a_terminal_record_refuses_everything() -> None:
    """Stated directly as well as by the matrix, because it is the property that matters:
    a revoked or expired access is history, and history is not edited."""
    for terminal in (AccessRecordStatus.REVOKED, AccessRecordStatus.EXPIRED):
        for operation in VALID:
            record = _record(terminal)
            with pytest.raises(InvalidAccessTransitionError):
                _invoke(record, operation)


# --- what a row reconstructed from the database looks like ------------------------


def test_access_record_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    record = AccessRecord(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )

    assert record.provider == AccessProvider.MANUAL
    assert record.status == AccessRecordStatus.PENDING
    assert record.created_mode == AccessCreatedMode.MANUAL
    assert record.reservation_id is None
