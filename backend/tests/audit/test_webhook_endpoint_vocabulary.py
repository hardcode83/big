"""The `WEBHOOK_ENDPOINT` audit contract (`reservations-webhooks` R2.4, design D12).

Not an optional formality. `AuditLogFactory.build` raises `AuditContractError` for an entity type
or action outside the closed vocabulary, and that exception **aborts the transaction of the
operation being audited** — so a missing entry here does not mean "no audit row", it means the
rotation itself fails. In the shape of `test_change_set_property.py`, which pins the same premise
for `PROPERTY`.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import REDACTED_FIELDS, ChangeSet


def test_the_webhook_endpoint_entity_type_is_part_of_the_closed_vocabulary() -> None:
    """Without this, `AuditLogFactory.build` raises and the rotation it audits rolls back."""
    assert actions.ENTITY_WEBHOOK_ENDPOINT in actions.ENTITY_TYPES
    assert actions.WEBHOOK_ENDPOINT_CREATED in actions.ACTIONS
    assert actions.WEBHOOK_ENDPOINT_ROTATED in actions.ACTIONS


def test_the_factory_builds_a_creation_row() -> None:
    log = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.WEBHOOK_ENDPOINT_CREATED,
        entity_type=actions.ENTITY_WEBHOOK_ENDPOINT,
        entity_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_ip="203.0.113.7",
        changes=ChangeSet(actions.ENTITY_WEBHOOK_ENDPOINT),
        now=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert log.action == "WEBHOOK_ENDPOINT_CREATED"
    assert log.entity_type == "WEBHOOK_ENDPOINT"


def test_the_factory_builds_a_rotation_row() -> None:
    log = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.WEBHOOK_ENDPOINT_ROTATED,
        entity_type=actions.ENTITY_WEBHOOK_ENDPOINT,
        entity_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_ip="203.0.113.7",
        changes=ChangeSet(actions.ENTITY_WEBHOOK_ENDPOINT),
        now=datetime(2026, 8, 8, tzinfo=UTC),
    )

    assert log.action == "WEBHOOK_ENDPOINT_ROTATED"


def test_an_unknown_webhook_action_is_still_refused() -> None:
    """The vocabulary stays closed: adding two entries must not open it in general."""
    with pytest.raises(AuditContractError):
        AuditLogFactory.build(
            tenant_id=uuid.uuid4(),
            action="WEBHOOK_ENDPOINT_DELETED",
            entity_type=actions.ENTITY_WEBHOOK_ENDPOINT,
            entity_id=uuid.uuid4(),
            actor_user_id=None,
            actor_ip=None,
            changes=ChangeSet(actions.ENTITY_WEBHOOK_ENDPOINT),
            now=datetime(2026, 8, 8, tzinfo=UTC),
        )


def test_neither_secret_can_reach_the_changes_column_as_a_value() -> None:
    """Rule 11: the value does not survive at all, not even masked.

    `token_hash` is denylisted too, and that is the half worth pinning: it is already a digest, so
    it reads as harmless — but it is the lookup key for the route whose non-guessability *is* rule
    12(b), and an `old`/`new` pair of digests would leave a permanent record of every route the
    tenant has had, against which a stolen token can be confirmed offline.
    """
    assert "header_secret_encrypted" in REDACTED_FIELDS
    assert "token_hash" in REDACTED_FIELDS


def test_a_rotation_records_that_it_happened_and_nothing_more() -> None:
    """The only reachable shape for either secret, and all a rotation needs."""
    # Chained, because `ChangeSet` is immutable: `redacted()` returns a new set rather than
    # mutating this one, so that one use case's fields cannot leak into the next one's audit row.
    changes = (
        ChangeSet(actions.ENTITY_WEBHOOK_ENDPOINT)
        .redacted("header_secret_encrypted")
        .redacted("token_hash")
    )

    assert changes.as_dict() == {
        "header_secret_encrypted": {"changed": True},
        "token_hash": {"changed": True},
    }


def test_diffing_a_secret_raises_rather_than_recording_it() -> None:
    """`diff()` on a denylisted field raises, which leaves `redacted()` as the only route.

    The intended shape rather than an obstacle, as `pms-provider-resolution` already established
    for `secret_encrypted`.
    """
    changes = ChangeSet(actions.ENTITY_WEBHOOK_ENDPOINT)

    with pytest.raises(AuditContractError):
        changes.diff("header_secret_encrypted", "old-secret", "new-secret")


def test_the_header_name_is_not_a_secret_and_records_its_change() -> None:
    """Nobody has verified what Beds24 actually sends, so a change of header name is an
    operational fact an operator should be able to see (design D3's column, not constant)."""
    changes = ChangeSet(actions.ENTITY_WEBHOOK_ENDPOINT).diff("header_name", "X-Old", "X-New")

    assert changes.as_dict() == {"header_name": {"old": "X-Old", "new": "X-New"}}


def test_there_is_no_read_action_while_the_only_reader_is_anonymous() -> None:
    """The asymmetry with `PMS_CREDENTIAL_READ`, pinned **to its premise** and not beyond it.

    The premise: today the only thing that reads this material is the receiving path — anonymous,
    from the internet, at provider cadence. An audit row per read would let an outsider write to
    `audit_logs` at will, which is a denial-of-service dressed as diligence, and would drown the
    very index (`ix_audit_logs_tenant_id_actor_user_id_created_at`) that rule 9 exists to keep
    answerable.

    **What this test does NOT assert, and an earlier version did**: that a webhook endpoint may
    never have a read action. That over-claimed, and in the one direction rule 9 refuses to
    concede — "Lo que esta excepción NO concede: […] no exime la lectura con actor humano". The
    day a human- or API-initiated read exists (a support command, an operator tool), it brings its
    own `WEBHOOK_ENDPOINT_READ` and this test changes with it. Pinning the absence as permanent
    policy would have made that change look like a regression.

    The exemption itself is **not settled here**: rule 9 says an exception arrives "con una
    entrada nueva y nombrada" in `steering/security.md`, approved in the design of the change that
    asks for it. That is design D15, provisional and queued in `BLOCKED.md` for Jose — a code
    comment is not the channel rule 9 names. Flagged by the security panel of section 1.
    """
    assert not any(
        action.startswith("WEBHOOK_ENDPOINT") and action.endswith("_READ")
        for action in actions.ACTIONS
    )
