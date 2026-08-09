"""Readiness for SES.Hospedajes (R6.3, PRD §17, design D11).

Written before the service (`steering/testing.md`: TDD in `domain/` where there is a real
invariant). **One case per missing field**, because "the eight of PRD §17" is a claim that is
only true if each of the eight is actually checked — a service that forgot `nationality`
would pass a test that only removes `document_number`.
"""

from datetime import date

import pytest

from app.guests.domain.enums import GuestDocumentType, LegalRegistrationStatus
from app.guests.domain.legal_registration import (
    REQUIRED_FIELDS,
    LegalRegistrationSubject,
    missing_fields,
    status_for,
)

CHECK_IN = date(2026, 9, 1)
CHECK_OUT = date(2026, 9, 4)


def _complete(**overrides) -> LegalRegistrationSubject:
    values = {
        "full_name": "Ada Lovelace",
        "nationality": "GB",
        "date_of_birth": date(1815, 12, 10),
        "document_type": GuestDocumentType.PASSPORT,
        "has_document_number": True,
        "document_expiry_date": date(2030, 1, 1),
        "check_in_date": CHECK_IN,
        "check_out_date": CHECK_OUT,
    }
    values.update(overrides)
    return LegalRegistrationSubject(**values)


def test_the_required_fields_are_the_eight_of_prd_17() -> None:
    """Transcribed from the PRD, not derived from the service, so a silent removal fails."""
    assert REQUIRED_FIELDS == (
        "full_name",
        "nationality",
        "date_of_birth",
        "document_type",
        "document_number",
        "document_expiry_date",
        "check_in_date",
        "check_out_date",
    )


def test_a_complete_subject_is_missing_nothing() -> None:
    assert missing_fields(_complete()) == ()


@pytest.mark.parametrize(
    ("field", "absent"),
    [
        ("full_name", {"full_name": None}),
        ("full_name", {"full_name": "   "}),
        ("nationality", {"nationality": None}),
        ("date_of_birth", {"date_of_birth": None}),
        ("document_type", {"document_type": None}),
        ("document_number", {"has_document_number": False}),
        ("document_expiry_date", {"document_expiry_date": None}),
        ("check_in_date", {"check_in_date": None}),
        ("check_out_date", {"check_out_date": None}),
    ],
)
def test_each_of_the_eight_is_actually_checked(field, absent) -> None:
    assert missing_fields(_complete(**absent)) == (field,)


def test_missing_fields_come_back_in_the_prd_order() -> None:
    """An operator reading the list should be able to follow PRD §17 down the page."""
    subject = _complete(nationality=None, has_document_number=False, check_out_date=None)

    assert missing_fields(subject) == (
        "nationality",
        "document_number",
        "check_out_date",
    )


# --- the status transition (R6.3) -------------------------------------------------


def test_a_complete_stay_becomes_ready_to_submit() -> None:
    assert (
        status_for(_complete(), current=LegalRegistrationStatus.PENDING_GUEST_DATA)
        is LegalRegistrationStatus.READY_TO_SUBMIT
    )


def test_an_incomplete_stay_goes_back_to_waiting_for_data() -> None:
    """Both directions: a document that is deleted or corrected out must un-ready the stay."""
    assert (
        status_for(
            _complete(has_document_number=False),
            current=LegalRegistrationStatus.READY_TO_SUBMIT,
        )
        is LegalRegistrationStatus.PENDING_GUEST_DATA
    )


@pytest.mark.parametrize(
    "terminal",
    [
        LegalRegistrationStatus.SUBMITTED,
        LegalRegistrationStatus.FAILED,
        LegalRegistrationStatus.MANUAL_REVIEW,
        LegalRegistrationStatus.NOT_REQUIRED,
    ],
)
def test_a_stay_past_this_question_is_never_recomputed(terminal) -> None:
    """The dangerous case, stated directly.

    Recomputing from field presence would let an edit to a guest — even a correction to their
    phone number, if a future writer widened the trigger — silently undo a filing already made
    with the police. `NOT_REQUIRED` is left alone for a different reason: deciding a stay needs
    reporting is the reconciler's call (PRD §17 step 1), not this function's.
    """
    assert status_for(_complete(), current=terminal) is terminal
    assert status_for(_complete(has_document_number=False), current=terminal) is terminal


def test_the_subject_never_carries_the_document_number() -> None:
    """Design D11: the readiness check knows a number is stored, never what it is.

    Asserted structurally so a future edit that "just passes the value in" fails here rather
    than quietly adding a call site that touches decrypted PII with no audit behind it.
    """
    import dataclasses

    names = {field.name for field in dataclasses.fields(LegalRegistrationSubject)}

    assert "document_number" not in names
    assert "document_number_encrypted" not in names
    assert "has_document_number" in names
