"""The notification a price recommendation produces (`notification-writers-gap` R4).

A pure builder, like its siblings in `cleaning` and `maintenance`, so what gets written is
testable without a session. `pricing` had no `domain/notifications.py` before this change:
`revenue-pricing` shipped `GeneratePriceRecommendationsUseCase` writing a `TimelineEvent` and
an `AuditLog` and nothing that reaches a person, which is why `PRICE_RECOMMENDATION` was the
tenth orphan the proposal's census found.
"""

import inspect
import uuid
from datetime import UTC, datetime

import pytest

from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.pricing.domain.notifications import (
    RELATED_TYPE_PROPERTY,
    price_recommendation_notification,
)

NOW = datetime(2026, 8, 29, 3, 0, tzinfo=UTC)


def _call(**overrides):
    kwargs = dict(
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        recipient_id=uuid.uuid4(),
        recipient_contact="owner@example.com",
        now=NOW,
    )
    kwargs.update(overrides)
    return price_recommendation_notification(**kwargs)


def test_it_points_at_the_property_not_the_recommendation() -> None:
    """R4.1 — one row per property and execution, so the pair names the property.

    Pointing at a recommendation would make the row's identity that of one of the sixty
    dates, and R4.2 exists precisely to stop sixty rows being written.
    """
    property_id = uuid.uuid4()

    log = _call(property_id=property_id)

    assert log.related_type == RELATED_TYPE_PROPERTY
    assert log.related_id == property_id
    assert log.notification_type == NotificationType.PRICE_RECOMMENDATION.value


def test_it_is_queued_in_app() -> None:
    """R5.3 — `PENDING` and `IN_APP`, delivered by `dispatch_notifications` and not here."""
    log = _call()

    assert log.status is NotificationStatus.PENDING
    assert log.channel is NotificationChannel.IN_APP


def test_it_has_no_sla_deadline() -> None:
    """R4.6, and it is a stated decision rather than an omission: nobody has defined in how
    long a price must be decided, so there is no deadline to give it."""
    assert _call().sla_deadline_at is None


def test_it_accepts_exactly_the_identifiers_and_nothing_else() -> None:
    """R5.4/R4.6 as a property of the signature.

    No deadline can be passed because there is no parameter for one, and no price,
    explanation or property name can be passed either — the same shape the section-4 security
    panel asked for on the `maintenance` builders, so that caller discipline is enforced by
    the signature rather than hoped for.
    """
    assert set(inspect.signature(price_recommendation_notification).parameters) == {
        "tenant_id",
        "property_id",
        "recipient_id",
        "recipient_contact",
        "now",
        # `notification-channel-routing` R2/R4 (design D2, D3): the fan-out dispatcher calls
        # the builder once per resolved channel, passing the channel and its contact.
        "channel",
        "contact",
    }


def test_it_carries_neither_a_price_nor_an_explanation() -> None:
    """R5.4 / rule 11 of `steering/security.md`.

    `price_recommendations.explanation` is a rendered sentence and one of the two columns
    `revenue-pricing` put in the rule-11 census; the recommended price is a number about a
    tenant's commercial position. Neither belongs in a column whose read audience is wider
    than the recommendation's own screen.
    """
    property_id = uuid.uuid4()

    log = _call(property_id=property_id)

    assert "€" not in log.body
    assert "EUR" not in log.body
    for token in log.body.replace(",", " ").replace(".", " ").split():
        # The only variable token is the property id; no digits leak in as a price.
        if len(token) == 36 and "-" in token:
            assert uuid.UUID(token) == property_id
        else:
            assert not token.isdigit()
