"""The `GUEST_ACCESS_TOKEN` and `INCIDENT` audit contracts (`guest-portal-api` R6.1, R6.4).

Not an optional formality, for the reason `test_webhook_endpoint_vocabulary.py` states:
`AuditLogFactory.build` raises `AuditContractError` for an entity type or action outside the
closed vocabulary, and that exception **aborts the transaction of the operation being
audited** — so a missing entry here does not mean "no audit row", it means the token issue
or the incident creation itself fails.

Design D11 and D15 are what this file pins, including two deliberate absences: there is no
check-in action, and there is no incident action beyond creation.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import AUDITABLE_FIELDS, REDACTED_FIELDS, ChangeSet
from app.guests.domain.portal_token import hash_guest_token


def _now() -> datetime:
    return datetime(2026, 8, 10, 12, 0, tzinfo=UTC)


# --- The token (D11, D14) --------------------------------------------------------------


def test_the_token_entity_type_and_its_two_actions_are_in_the_vocabulary() -> None:
    assert actions.ENTITY_GUEST_ACCESS_TOKEN in actions.ENTITY_TYPES
    assert actions.GUEST_ACCESS_TOKEN_ISSUED in actions.ACTIONS
    assert actions.GUEST_ACCESS_TOKEN_REVOKED in actions.ACTIONS


def test_the_factory_builds_an_issue_row() -> None:
    log = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.GUEST_ACCESS_TOKEN_ISSUED,
        entity_type=actions.ENTITY_GUEST_ACCESS_TOKEN,
        entity_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_ip="203.0.113.7",
        changes=ChangeSet(actions.ENTITY_GUEST_ACCESS_TOKEN).redacted("token_hash"),
        now=_now(),
    )

    assert log.action == "GUEST_ACCESS_TOKEN_ISSUED"
    assert log.entity_type == "GUEST_ACCESS_TOKEN"
    assert log.changes == {"token_hash": {"changed": True}}


def test_the_factory_builds_a_revocation_row() -> None:
    """`revoked_at` is a plain timestamp carrying no secret, so it is a real diff."""
    log = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.GUEST_ACCESS_TOKEN_REVOKED,
        entity_type=actions.ENTITY_GUEST_ACCESS_TOKEN,
        entity_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_ip="203.0.113.7",
        changes=ChangeSet(actions.ENTITY_GUEST_ACCESS_TOKEN).diff(
            "revoked_at", None, _now().isoformat()
        ),
        now=_now(),
    )

    assert log.action == "GUEST_ACCESS_TOKEN_REVOKED"
    assert log.changes == {"revoked_at": {"old": None, "new": _now().isoformat()}}


def test_the_token_hash_can_only_be_recorded_as_redacted() -> None:
    """R6.4 and rule 11: `token_hash` is already denylisted, so `diff()` raises.

    The same reasoning that put it there for `webhook_endpoints` applies with more force
    here: it is the lookup key of a route whose non-guessability is the *entire* credential
    (there is no second header secret on this surface), so an `old`/`new` pair of digests in
    an append-only table would let an insider confirm a stolen token offline.
    """
    assert "token_hash" in REDACTED_FIELDS

    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_GUEST_ACCESS_TOKEN).diff("token_hash", "old", "new")


def test_the_token_is_listed_as_auditable_so_redacted_still_works() -> None:
    """The allowlist/denylist pair, same shape as `PMS_CREDENTIAL.secret_encrypted`.

    Removing `token_hash` from the allowlist would make `redacted()` fail too, and minting a
    portal credential would leave no trace at all.
    """
    assert AUDITABLE_FIELDS["GUEST_ACCESS_TOKEN"] == frozenset({"token_hash", "revoked_at"})


def test_an_invented_token_field_is_refused() -> None:
    """The allowlist is what stops a caller writing an arbitrary payload under a new key."""
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_GUEST_ACCESS_TOKEN).diff("reservation_id", None, "x")


def test_there_is_no_read_action_for_a_guest_access_token() -> None:
    """Pinned to its premise, like the webhook one, and not beyond it.

    Nothing reads this material with a human actor today: the only reader is the anonymous
    authoriser, and auditing that would let an outsider write to `audit_logs` at will — the
    denial-of-service dressed as diligence that rule 9's third named exception describes.
    The day an operator tool reads a token row, it brings its own action and this changes.
    """
    assert not any(
        action.startswith("GUEST_ACCESS_TOKEN") and action.endswith("_READ")
        for action in actions.ACTIONS
    )


# --- The incident (D15) ----------------------------------------------------------------


def test_the_incident_entity_type_and_its_creation_action_are_in_the_vocabulary() -> None:
    assert actions.ENTITY_INCIDENT in actions.ENTITY_TYPES
    assert actions.INCIDENT_CREATED in actions.ACTIONS


def test_the_factory_builds_an_incident_creation_row_for_a_guest_actor() -> None:
    """R6.1: the bearer names themselves by their digest, and there is no `User`."""
    token_hash = hash_guest_token("a-portal-token")
    reservation_id = uuid.uuid4()

    log = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.INCIDENT_CREATED,
        entity_type=actions.ENTITY_INCIDENT,
        entity_id=uuid.uuid4(),
        actor_user_id=None,
        actor_guest_token_hash=token_hash,
        actor_ip="203.0.113.7",
        changes=ChangeSet(actions.ENTITY_INCIDENT)
        .diff("source", None, "GUEST")
        .diff("status", None, "OPEN")
        .diff("reservation_id", None, str(reservation_id)),
        now=_now(),
    )

    assert log.actor_guest_token_hash == token_hash
    assert log.actor_user_id is None
    assert log.changes == {
        "source": {"old": None, "new": "GUEST"},
        "status": {"old": None, "new": "OPEN"},
        "reservation_id": {"old": None, "new": str(reservation_id)},
    }


@pytest.mark.parametrize("field", ["title", "description"])
def test_the_free_text_a_guest_typed_cannot_be_audited(field: str) -> None:
    """D15 and rule 11: `audit_logs.changes` is a cleartext sink.

    `title` and `description` are written from outside by an anonymous caller, so keeping
    them out of the allowlist is what stops a guest choosing what lands in an append-only
    column. The audit row records that an incident was opened, against which stay and in
    what state — never a word the guest wrote.
    """
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_INCIDENT).diff(field, None, "whatever the guest typed")

    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_INCIDENT).redacted(field)


def test_the_incident_allowlist_is_exactly_the_three_structural_fields() -> None:
    assert AUDITABLE_FIELDS["INCIDENT"] == frozenset({"source", "status", "reservation_id"})


def test_there_is_no_incident_action_beyond_creation() -> None:
    """D15: classifying, assigning and resolving belong to `maintenance`.

    Pre-authorising an operation no code performs is what rule 9 refuses to do for
    `SCHEDULER`, and a vocabulary entry with no writer is exactly what `actions.py`'s own
    docstring argues against.
    """
    incident_actions = {
        action for action in actions.ACTIONS if action.startswith("INCIDENT_")
    }

    assert incident_actions == {"INCIDENT_CREATED"}


# --- The guest's name (D10) ------------------------------------------------------------


def test_the_guest_full_name_is_auditable_and_only_as_redacted() -> None:
    """D10: the portal's check-in is the first path that writes `guests.full_name`.

    Auditable so the write leaves a trace, and **denylisted** so `redacted()` is the only
    form that exists — not merely the form the use cases are expected to choose. The
    security and QA reviewers of section 2 each demonstrated that leaving it diffable let
    `diff("full_name", ...)` store the value verbatim, and the value here is free text typed
    by an anonymous caller into `POST /api/v1/guest/checkin/{token}`.
    """
    assert "full_name" in AUDITABLE_FIELDS["GUEST"]
    assert "full_name" in REDACTED_FIELDS

    changes = ChangeSet(actions.ENTITY_GUEST).redacted("full_name")

    assert changes.as_dict() == {"full_name": {"changed": True}}


@pytest.mark.parametrize("field", ["full_name", "nationality"])
def test_the_free_text_of_the_check_in_form_cannot_be_diffed(field: str) -> None:
    """The half that matters, and the one that was missing.

    These are the two fields of PRD §17's eight that are free text rather than a date, an
    enum or an encrypted blob — so they are the two an anonymous caller can fill with
    anything. `audit_logs.changes` is a rule-11 sink, and the guarantee this module claims is
    "by construction, not by care".

    `nationality` was deliberately left diffable by `access-notifications`, on the grounds
    that §"Datos sensibles" does not name it. That held while an operator was the only
    writer; the guest portal is what changed the premise, which is why this change revisits
    it rather than quietly widening a denylist.
    """
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_GUEST).diff(field, "old", "whatever the guest typed")


def test_what_remains_diffable_on_a_guest_is_only_typed_non_text_fields() -> None:
    """The positive half, so the two tests above cannot pass by forbidding everything.

    Without it, `AUDITABLE_FIELDS["GUEST"]` could shrink to just the two denylisted names
    and both would still pass while proving nothing about the rest of the allowlist.

    **Where the guarantee actually lives, stated precisely because the first draft of this
    docstring got it wrong.** `ChangeSet` does *not* check that these four hold real enum
    members or a real date — `_storable` accepts any `str` unconditionally, and the QA
    reviewer of section 2 demonstrated it does. What bounds them is the caller, exactly as
    this module's own `ASSUMPTION` comment says: `app/guests/api/schemas.py` types the
    boundary as Pydantic `date`/enum fields that 422 before the domain is reached, and
    `SetGuestDocumentUseCase` passes `.value` off a real enum instance. So this test pins
    *which* fields stay diffable — a security decision — and not a property of `ChangeSet`.
    Task 6.6 carries the obligation to keep the portal's own schema equally typed.
    """
    diffable = AUDITABLE_FIELDS["GUEST"] - REDACTED_FIELDS

    assert diffable == frozenset(
        {
            "document_type",
            "document_expiry_date",
            "document_status",
            "legal_registration_status",
        }
    )

    changes = ChangeSet(actions.ENTITY_GUEST).diff("document_status", "NOT_PROVIDED", "PROVIDED")

    assert changes.as_dict() == {
        "document_status": {"old": "NOT_PROVIDED", "new": "PROVIDED"}
    }


def test_there_is_no_check_in_action_because_the_operation_is_a_document_update() -> None:
    """D11, asserted as an absence.

    The guest completing their own check-in *is* `GUEST_DOCUMENT_UPDATED` — rule 9's
    "modificación de documentos de Guest" — and who did it is said by the actor, not by a
    second verb. A `GUEST_CHECKIN_SUBMITTED` would split "who touched this guest's document"
    across two actions, which is what the closed vocabulary exists to prevent.
    """
    assert not any("CHECKIN" in action for action in actions.ACTIONS)
    assert actions.GUEST_DOCUMENT_UPDATED in actions.ACTIONS
