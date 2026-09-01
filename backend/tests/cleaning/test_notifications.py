"""The two notifications that close the cleaning loop (`notification-writers-gap` R2).

Pure builders, so what gets written is testable without a session — the shape
`app/cleaning/domain/notifications.py` already had for its two assignment constructors, and
which design D4 keeps rather than collapsing into one parameterised builder.

What these pin, beyond the obvious: the contract of rule 11 of `sdd/steering/security.md` for
`notification_logs.subject`/`body` (a constant plus identifiers, never another row's text),
and R5.5's "no deadline" as a property of the **signature** rather than of one call.
"""

import inspect
import uuid
from datetime import UTC, datetime

import pytest

from app.cleaning.domain.notifications import (
    RELATED_TYPE_CLEANING_TASK,
    completion_notification,
    validation_failed_notification,
)
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

NOW = datetime(2026, 8, 29, 10, 0, tzinfo=UTC)

BUILDERS = [completion_notification, validation_failed_notification]


def _call(builder):
    return builder(
        tenant_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        recipient_id=uuid.uuid4(),
        recipient_contact="someone@example.com",
        now=NOW,
    )


@pytest.mark.parametrize("builder", BUILDERS)
def test_it_is_queued_in_app_and_points_at_the_task(builder) -> None:
    """R5.3 — `PENDING` and `IN_APP`: queued work for `dispatch_notifications`.

    The polymorphic pair points at the **cleaning task**, the same pair
    `cancel_sla_deadline` already matches on, so everything notified about one task is
    reachable by one query.
    """
    task_id = uuid.uuid4()
    recipient_id = uuid.uuid4()

    log = builder(
        tenant_id=uuid.uuid4(),
        task_id=task_id,
        property_id=uuid.uuid4(),
        recipient_id=recipient_id,
        recipient_contact="someone@example.com",
        now=NOW,
    )

    assert log.status is NotificationStatus.PENDING
    assert log.channel is NotificationChannel.IN_APP
    assert log.related_type == RELATED_TYPE_CLEANING_TASK
    assert log.related_id == task_id
    assert log.recipient_user_id == recipient_id


def test_the_two_builders_write_their_own_types() -> None:
    """R2.1/R2.2, and the literals section 7's census reads (design D4)."""
    completed = _call(completion_notification)
    failed = _call(validation_failed_notification)

    assert completed.notification_type == NotificationType.CLEANING_COMPLETED.value
    assert failed.notification_type == NotificationType.CLEANING_FAILED.value
    assert completed.subject != failed.subject


@pytest.mark.parametrize("builder", BUILDERS)
def test_it_has_no_sla_deadline(builder) -> None:
    """R5.5 — and neither closes nor opens an SLA.

    A deadline here would be a breach candidate against a type `escalation_for` returns
    `None` for: marked breached, escalating to nobody.
    """
    assert _call(builder).sla_deadline_at is None


@pytest.mark.parametrize("builder", BUILDERS)
def test_it_accepts_exactly_the_identifiers_and_nothing_else(builder) -> None:
    """R5.4 as a property of the signature, which is the only form that holds.

    The free-text test below can only fail if a builder interpolates prose it was **given**.
    That catches a new *required* prose parameter, but not an optional one a caller then
    feeds the task's checklist notes into. Pinning the parameter set makes the caller
    discipline the contract relies on into something the suite enforces — the point the
    section-4 security panel made about the equivalent builders in `maintenance`.
    """
    assert set(inspect.signature(builder).parameters) == {
        "tenant_id",
        "task_id",
        "property_id",
        "recipient_id",
        "recipient_contact",
        "now",
        # `notification-channel-routing` R2/R4 (design D2, D3): the fan-out dispatcher calls
        # every builder once per resolved channel, passing the channel and its contact.
        "channel",
        "contact",
    }


@pytest.mark.parametrize("builder", BUILDERS)
def test_it_carries_no_free_text_from_the_task(builder) -> None:
    """R5.4 / rule 11: a constant plus identifiers, nothing a human typed.

    A cleaning task carries prose in more than one place — checklist notes, the completion
    note, and the reason a manager gives when failing a validation. None of it belongs in a
    column whose read audience is wider than the task's own.
    """
    task_id = uuid.uuid4()
    property_id = uuid.uuid4()
    leaked = [
        "the cleaner wrote a phone number in the checklist note",
        "the manager explained the failure in prose",
    ]

    log = builder(
        tenant_id=uuid.uuid4(),
        task_id=task_id,
        property_id=property_id,
        recipient_id=uuid.uuid4(),
        recipient_contact="someone@example.com",
        now=NOW,
    )

    for value in leaked:
        assert value not in log.body
        assert value not in log.subject
    for token in log.body.replace(",", " ").replace(".", " ").split():
        if len(token) == 36 and "-" in token:
            assert uuid.UUID(token) in {task_id, property_id}
