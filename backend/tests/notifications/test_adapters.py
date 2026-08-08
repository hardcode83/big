"""Channel adapters (R4.1, R4.5; design D5).

Two things matter beyond "it delivers": the registry must **not** resolve `PUSH`, and no
adapter may put `subject`/`body` into an application log. The second one is not paranoia —
rule 11 of `sdd/steering/security.md` lets a masked access code travel in `body`, and an
app log is not one of the sinks that contract governs.
"""

import logging

import pytest

from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.results import NotificationErrorCode
from app.notifications.infrastructure.adapters import (
    ConsoleEmailAdapter,
    InAppNotificationAdapter,
    MockWhatsAppAdapter,
    adapter_registry,
)

ADAPTERS = [ConsoleEmailAdapter(), MockWhatsAppAdapter(), InAppNotificationAdapter()]


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_adapter_delivers(adapter) -> None:
    result = await adapter.send(
        recipient_contact="someone@example.com",
        subject="Cleaning assigned",
        body="A cleaning task has been assigned to you.",
        channel=NotificationChannel.EMAIL,
    )
    assert result.delivered is True
    assert result.error_code is None


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_blank_recipient_is_a_failure_not_an_exception(adapter) -> None:
    """The port's contract: delivery failures come back as values (`ports.py`).

    All three share it, which is what makes them substitutable for a real adapter
    (`steering/backend-architecture.md`, Liskov).
    """
    result = await adapter.send(
        recipient_contact="   ",
        subject="s",
        body="b",
        channel=NotificationChannel.EMAIL,
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.INVALID_RECIPIENT


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_missing_subject_and_body_do_not_crash(adapter) -> None:
    """`notification_logs.subject`/`body` are both nullable, so the port takes `None`."""
    result = await adapter.send(
        recipient_contact="someone@example.com",
        subject=None,
        body=None,
        channel=NotificationChannel.IN_APP,
    )
    assert result.delivered is True


def test_registry_covers_every_channel_except_push() -> None:
    """R4.5's precondition: `PUSH` must have no adapter, so the dispatcher can skip it."""
    registry = adapter_registry()
    assert set(registry) == {
        NotificationChannel.EMAIL,
        NotificationChannel.CONSOLE,
        NotificationChannel.WHATSAPP,
        NotificationChannel.IN_APP,
    }
    assert NotificationChannel.PUSH not in registry


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS)
async def test_adapter_never_logs_subject_or_body(adapter, caplog) -> None:
    """Rule 11's sink discipline, applied to the one place it is easy to forget.

    `body` here carries the masked access code shape the rule sanctions for
    `notification_logs.body`. That sanction does not extend to an application log, which has
    no retention policy and no tenant scoping — so the content must not appear anywhere in
    the emitted records, message or structured fields alike.
    """
    secret_subject = "Your access code"
    secret_body = "Your door code is ****23. Property 7 Redes."
    with caplog.at_level(logging.DEBUG):
        await adapter.send(
            recipient_contact="someone@example.com",
            subject=secret_subject,
            body=secret_body,
            channel=NotificationChannel.EMAIL,
        )
    emitted = "\n".join(
        record.getMessage() + " " + " ".join(str(value) for value in record.__dict__.values())
        for record in caplog.records
    )
    assert secret_subject not in emitted
    assert secret_body not in emitted
    assert "****23" not in emitted
