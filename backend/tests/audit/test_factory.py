"""The factory is the only way to build an `AuditLog` (R6.3, R6.5, design D2).

Same role `TimelineEventFactory` plays for `timeline_events`: one place that validates the
vocabulary and the change set, so no use case can write a row that breaks rule 11 or spells
the entity type its own way.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.guests.domain.portal_token import generate_guest_token, hash_guest_token


def utc_now() -> datetime:
    return datetime.now(UTC)


def test_it_builds_an_entry_with_the_actor_and_the_change_set() -> None:
    tenant_id, actor_id, entity_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    entry = AuditLogFactory.build(
        tenant_id=tenant_id,
        action=actions.USER_ROLE_CHANGED,
        entity_type=actions.ENTITY_USER,
        entity_id=entity_id,
        actor_user_id=actor_id,
        actor_ip="203.0.113.7",
        changes=ChangeSet(actions.ENTITY_USER).diff("role", "CLEANER", "TECHNICIAN"),
        now=utc_now(),
    )

    assert entry.tenant_id == tenant_id
    assert entry.actor_user_id == actor_id
    assert entry.actor_ip == "203.0.113.7"
    assert entry.entity_id == entity_id
    assert entry.changes == {"role": {"old": "CLEANER", "new": "TECHNICIAN"}}


def test_it_gives_the_entry_its_own_identity_and_timestamp() -> None:
    now = utc_now()

    entry = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.USER_CREATED,
        entity_type=actions.ENTITY_USER,
        entity_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_ip=None,
        changes=ChangeSet(actions.ENTITY_USER).redacted("password"),
        now=now,
    )

    assert isinstance(entry.id, uuid.UUID)
    assert entry.created_at == now


def test_an_empty_change_set_becomes_a_null_column_not_an_empty_object() -> None:
    """`{}` and NULL both mean "no diff"; storing one of the two keeps queries honest."""
    entry = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.USER_DEACTIVATED,
        entity_type=actions.ENTITY_USER,
        entity_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_ip=None,
        changes=ChangeSet(actions.ENTITY_USER),
        now=utc_now(),
    )

    assert entry.changes is None


@pytest.mark.parametrize("action", ["user.updated", "USER_PROMOTED", "", "  "])
def test_it_rejects_an_action_outside_the_vocabulary(action: str) -> None:
    """§7.25 makes the column free-form text, so the only gate is this one."""
    with pytest.raises(AuditContractError):
        AuditLogFactory.build(
            tenant_id=uuid.uuid4(),
            action=action,
            entity_type=actions.ENTITY_USER,
            entity_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            actor_ip=None,
            changes=ChangeSet(actions.ENTITY_USER),
            now=utc_now(),
        )


# `REVIEW` stands for "a real table that is not in the vocabulary yet"; it replaced
# `OWNER_STATEMENT`, which `revenue-statements` registered (design D7). See the twin
# note in `test_change_set.py`. The history of the placeholder rolls forward through
# `PROPERTY` → `RESERVATION` → `INCIDENT` → `OWNER_APPROVAL` → `PRICING_RULE` →
# `OWNER_STATEMENT` → `REVIEW`. `reviews` is a `domain-foundation-financial` table whose
# first writer will be `revenue-reviews`.
@pytest.mark.parametrize("entity_type", ["User", "users", "REVIEW", ""])
def test_it_rejects_an_entity_type_outside_the_vocabulary(entity_type: str) -> None:
    with pytest.raises(AuditContractError):
        AuditLogFactory.build(
            tenant_id=uuid.uuid4(),
            action=actions.USER_UPDATED,
            entity_type=entity_type,
            entity_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            actor_ip=None,
            changes=ChangeSet(actions.ENTITY_USER),
            now=utc_now(),
        )


def test_it_requires_a_timezone_aware_timestamp() -> None:
    """A naive datetime in a TIMESTAMPTZ column is a silent hour shift."""
    with pytest.raises(AuditContractError):
        AuditLogFactory.build(
            tenant_id=uuid.uuid4(),
            action=actions.USER_UPDATED,
            entity_type=actions.ENTITY_USER,
            entity_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            actor_ip=None,
            changes=ChangeSet(actions.ENTITY_USER),
            now=datetime(2026, 7, 31, 12, 0, 0),  # noqa: DTZ001 — the point of the test
        )


def test_it_accepts_a_system_actor_without_a_user() -> None:
    """`actor_user_id` is nullable in §7.25: a Celery job has no user."""
    entry = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.USER_DEACTIVATED,
        entity_type=actions.ENTITY_USER,
        entity_id=uuid.uuid4(),
        actor_user_id=None,
        actor_ip=None,
        changes=ChangeSet(actions.ENTITY_USER),
        now=utc_now(),
    )

    assert entry.actor_user_id is None


def test_it_rejects_an_actor_ip_longer_than_the_column() -> None:
    """`actor_ip` is VARCHAR(45); a longer value dies at the driver mid-transaction."""
    with pytest.raises(AuditContractError):
        AuditLogFactory.build(
            tenant_id=uuid.uuid4(),
            action=actions.USER_UPDATED,
            entity_type=actions.ENTITY_USER,
            entity_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            actor_ip="x" * 46,
            changes=ChangeSet(actions.ENTITY_USER),
            now=utc_now(),
        )


def test_it_rejects_a_change_set_built_for_another_entity() -> None:
    """The cross-section guard, which had no test (feature-scale QA review).

    No current caller can trigger it — both writers build the `ChangeSet` with the same
    `entity_type` they pass — but it is what protects a third module reusing this factory from
    auditing the right fields against the wrong object: the allowlist of the OTHER entity would
    have vetted them.
    """
    with pytest.raises(AuditContractError) as caught:
        AuditLogFactory.build(
            tenant_id=uuid.uuid4(),
            action=actions.TENANT_UPDATED,
            entity_type=actions.ENTITY_TENANT,
            entity_id=uuid.uuid4(),
            actor_user_id=uuid.uuid4(),
            actor_ip=None,
            changes=ChangeSet(actions.ENTITY_USER).diff("role", "CLEANER", "TECHNICIAN"),
            now=utc_now(),
        )

    assert "USER" in str(caught.value) and "TENANT" in str(caught.value)


def test_a_matching_change_set_is_accepted() -> None:
    """The positive half, so the guard above cannot pass by rejecting everything."""
    entry = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.TENANT_UPDATED,
        entity_type=actions.ENTITY_TENANT,
        entity_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_ip=None,
        changes=ChangeSet(actions.ENTITY_TENANT).diff("name", "MAGNO", "MAGNO SL"),
        now=utc_now(),
    )

    assert entry.changes == {"name": {"old": "MAGNO", "new": "MAGNO SL"}}


# --- The guest-portal actor (`guest-portal-api` R6.1, design D11) ---------------------


def test_it_names_a_guest_portal_actor_by_the_hash_of_their_token() -> None:
    """R6.1: the bearer identified by their non-reversible reference, not left anonymous.

    `actor_user_id` stays NULL because there is no `User` — that identity was excluded from
    the system on purpose (`auth-tenancy`) and the whole point of the portal is that the
    guest never becomes one.
    """
    token_hash = hash_guest_token("some-opaque-token")

    entry = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.GUEST_DOCUMENT_UPDATED,
        entity_type=actions.ENTITY_GUEST,
        entity_id=uuid.uuid4(),
        actor_user_id=None,
        actor_guest_token_hash=token_hash,
        actor_ip="203.0.113.7",
        changes=ChangeSet(actions.ENTITY_GUEST).redacted("document_number_encrypted"),
        now=utc_now(),
    )

    assert entry.actor_guest_token_hash == token_hash
    assert entry.actor_user_id is None
    assert entry.actor_ip == "203.0.113.7"


def test_every_other_writer_leaves_the_guest_actor_column_null() -> None:
    """The column defaults to absent, so no existing caller had to be touched."""
    entry = AuditLogFactory.build(
        tenant_id=uuid.uuid4(),
        action=actions.USER_UPDATED,
        entity_type=actions.ENTITY_USER,
        entity_id=uuid.uuid4(),
        actor_user_id=uuid.uuid4(),
        actor_ip=None,
        changes=ChangeSet(actions.ENTITY_USER),
        now=utc_now(),
    )

    assert entry.actor_guest_token_hash is None


def test_it_rejects_the_cleartext_token_in_place_of_its_hash() -> None:
    """R1.2 and R6.4: the cleartext guest token never reaches `audit_logs`.

    This is the realistic accident, and the one the column type cannot catch: a
    `secrets.token_urlsafe(32)` value is 43 characters, so `String(64)` takes it happily and
    the audit trail would then be a table of live portal credentials. The factory is the
    chokepoint where that stops depending on every writer remembering.
    """
    with pytest.raises(AuditContractError, match="SHA-256"):
        AuditLogFactory.build(
            tenant_id=uuid.uuid4(),
            action=actions.GUEST_DOCUMENT_UPDATED,
            entity_type=actions.ENTITY_GUEST,
            entity_id=uuid.uuid4(),
            actor_user_id=None,
            actor_guest_token_hash=generate_guest_token(),
            actor_ip=None,
            changes=ChangeSet(actions.ENTITY_GUEST),
            now=utc_now(),
        )


@pytest.mark.parametrize(
    "value",
    [
        "",
        "0" * 63,
        "0" * 65,
        "0" * 63 + "z",
        "A" * 64,  # upper case: `hashlib.hexdigest()` never produces it
    ],
)
def test_it_rejects_anything_that_is_not_a_sha256_hex_digest(value: str) -> None:
    with pytest.raises(AuditContractError, match="SHA-256"):
        AuditLogFactory.build(
            tenant_id=uuid.uuid4(),
            action=actions.GUEST_DOCUMENT_UPDATED,
            entity_type=actions.ENTITY_GUEST,
            entity_id=uuid.uuid4(),
            actor_user_id=None,
            actor_guest_token_hash=value,
            actor_ip=None,
            changes=ChangeSet(actions.ENTITY_GUEST),
            now=utc_now(),
        )
