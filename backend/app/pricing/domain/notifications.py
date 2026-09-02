"""The notification a price recommendation produces (R4, design D4/D10; `notification-channel-routing`
R2, R4).

A pure builder, calqued on `app/cleaning/domain/notifications.py` and
`app/maintenance/domain/notifications.py`, so the **content** of what gets written is testable
without a session and lives next to the rule that shapes it — rule 11 of
`sdd/steering/security.md`, whose contract for `notification_logs.subject`/`body` was fixed
by `celery-jobs`. This module does not derive a new contract; it complies with the one that
exists: the body carries **ids and a type**, never the content of another row.

That last point is sharper here than in the sibling modules. `pricing` owns two columns of the
rule-11 census — `price_recommendations.explanation`, a rendered sentence, and the recommended
price itself, which is a number about a tenant's commercial position. Neither is interpolated
here, and neither can be: there is no parameter through which a caller could pass one.

**New in `notification-writers-gap`.** `revenue-pricing` shipped the generator writing a
`TimelineEvent` and an `AuditLog` and nothing that reaches a person, which is why
`PRICE_RECOMMENDATION` was one of the orphaned types the proposal's census found — declared in
the enum since `celery-jobs`, written by nobody.

**Channel + contact (notification-channel-routing R2, R4, design D2, D3).** The builder
accepts `channel: NotificationChannel = IN_APP` and `contact: str | None = None` as
**optional** kwargs. `recipient_contact` derives from `contact` when given, otherwise
falls back to the legacy parameter. The dispatcher in
`notifications/application/channel_dispatch.py` is the function that calls this builder
once per resolved channel.
"""

import uuid
from datetime import datetime

from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)

#: `related_type` for a row that points at `properties`.
#:
#: The pair points at the **property**, not at a `PriceRecommendation`, and that is R4.1's
#: shape rather than a convenience: the notification is about "this property has new
#: recommendations waiting", one per property and execution. Pointing at a recommendation
#: would give the row the identity of one of the sixty dates in the horizon — and writing one
#: per recommendation is exactly what R4.2 forbids, at sixty rows on a property's first run.
RELATED_TYPE_PROPERTY = "property"


def price_recommendation_notification(
    *,
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    recipient_id: uuid.UUID,
    recipient_contact: str = "",
    now: datetime,
    channel: NotificationChannel = NotificationChannel.IN_APP,
    contact: str | None = None,
) -> NotificationLog:
    """What the owner or manager is told when new recommendations are waiting (R4.1).

    **No `sla_deadline_at`, and no parameter to give it one** (R4.6, design D10). Here the
    reason is not the usual one: it is that nobody has defined how long a price may go
    undecided. A deadline invented to fill the gap would produce a breach candidate against a
    type `escalation_for` returns `None` for — a row marked breached that escalates to nobody.

    Subject and body are a constant plus one identifier. Nothing here reads the recommended
    price, the rendered `explanation`, or even the property's name: the recipient opens the
    queue to see them, where the tenant's own authorisation applies.
    """
    return NotificationLog(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        recipient_user_id=recipient_id,
        recipient_contact=contact if contact is not None else recipient_contact,
        channel=channel,
        notification_type=NotificationType.PRICE_RECOMMENDATION.value,
        created_at=now,
        updated_at=now,
        subject="New price recommendations",
        body=(
            f"New price recommendations are waiting for your decision. "
            f"Property {property_id}."
        ),
        status=NotificationStatus.PENDING,
        related_type=RELATED_TYPE_PROPERTY,
        related_id=property_id,
    )