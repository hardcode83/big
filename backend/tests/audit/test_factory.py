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


# `RESERVATION` stands for "a real table that is not in the vocabulary yet"; it replaced
# `PROPERTY`, which `properties-crud` registered. See the twin note in `test_change_set.py`.
@pytest.mark.parametrize("entity_type", ["User", "users", "RESERVATION", ""])
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
