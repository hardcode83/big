"""Channel adapters (R4.1, R4.5; design D5).

Two things matter beyond "it delivers": the registry must **not** resolve `PUSH`, and no
adapter may put `subject`/`body` into an application log. The second one is not paranoia —
rule 11 of `sdd/steering/security.md` lets a masked access code travel in `body`, and an
app log is not one of the sinks that contract governs.
"""

import logging
import smtplib
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.exceptions import SMTPConfigurationError
from app.notifications.domain.results import NotificationErrorCode
from app.notifications.infrastructure.adapters import (
    ConsoleEmailAdapter,
    InAppNotificationAdapter,
    MockWhatsAppAdapter,
    SMTPEmailAdapter,
    adapter_registry,
)

ADAPTERS = [ConsoleEmailAdapter(), MockWhatsAppAdapter(), InAppNotificationAdapter()]


@pytest.fixture
def smtp_settings(monkeypatch):
    """A fully-configured relay, so `SMTPEmailAdapter` is selectable and constructible.

    Individual tests override one field to `""`/`0` to exercise R2.2's fail-fast branch.
    """
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "relay-user")
    monkeypatch.setattr(settings, "smtp_password", "relay-pass")
    monkeypatch.setattr(settings, "smtp_from_email", "noreply@example.com")
    monkeypatch.setattr(settings, "smtp_use_tls", True)
    return settings


@pytest.fixture
def mock_smtp_client(monkeypatch):
    """Replaces `smtplib.SMTP` with a context-manager double — no real network.

    Returns the `MagicMock` standing in for the connected client, so a test can make
    `send_message`/`login` raise to exercise the D4 exception mapping.
    """
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(smtplib, "SMTP", constructor)
    return client


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
@pytest.mark.parametrize("adapter", ADAPTERS + [SMTPEmailAdapter()])
async def test_adapter_never_logs_subject_or_body(
    adapter, caplog, smtp_settings, mock_smtp_client
) -> None:
    """Rule 11's sink discipline, applied to the one place it is easy to forget.

    `body` here carries the masked access code shape the rule sanctions for
    `notification_logs.body`. That sanction does not extend to an application log, which has
    no retention policy and no tenant scoping — so the content must not appear anywhere in
    the emitted records, message or structured fields alike. `smtp_settings`/
    `mock_smtp_client` are inert for the non-SMTP adapters and are what lets `SMTPEmailAdapter`
    join this parametrization without a real network call (R1.4, R3.1).
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


@pytest.mark.asyncio
@pytest.mark.parametrize("adapter", ADAPTERS + [SMTPEmailAdapter()])
async def test_adapter_never_logs_the_recipient_address(
    adapter, caplog, smtp_settings, mock_smtp_client
) -> None:
    """Found by the security panel of sections 1-2, and it is the same rule as above.

    Every argument against logging the body applies to the address: no retention policy, no
    tenant scoping, no audit. Today it is a staff email; from R2 onwards these channels carry
    the guest's access instructions, so it is the guest's. A line per delivery would be a
    per-tenant contact directory written by the component that had just refused to log the
    message.
    """
    address = "guest-7f3a@example.com"
    with caplog.at_level(logging.DEBUG):
        await adapter.send(
            recipient_contact=address,
            subject="Your access code",
            body="Your door code is ****23.",
            channel=NotificationChannel.EMAIL,
        )
    emitted = "\n".join(
        record.getMessage() + " " + " ".join(str(value) for value in record.__dict__.values())
        for record in caplog.records
    )
    assert address not in emitted


@pytest.mark.asyncio
async def test_smtp_adapter_2xx_is_ok(smtp_settings, mock_smtp_client) -> None:
    """R1.3: the relay accepting the message (no exception from `send_message`) is `ok()`."""
    adapter = SMTPEmailAdapter()
    result = await adapter.send(
        recipient_contact="guest@example.com",
        subject="Password reset",
        body="Use this link to reset your password.",
        channel=NotificationChannel.EMAIL,
    )
    assert result.delivered is True
    assert result.error_code is None
    mock_smtp_client.send_message.assert_called_once()
    mock_smtp_client.starttls.assert_called_once()
    mock_smtp_client.login.assert_called_once_with("relay-user", "relay-pass")


@pytest.mark.asyncio
async def test_smtp_adapter_skips_login_without_username(
    smtp_settings, mock_smtp_client, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "smtp_username", "")
    adapter = SMTPEmailAdapter()
    result = await adapter.send(
        recipient_contact="guest@example.com",
        subject="s",
        body="b",
        channel=NotificationChannel.EMAIL,
    )
    assert result.delivered is True
    mock_smtp_client.login.assert_not_called()


@pytest.mark.asyncio
async def test_smtp_adapter_blank_recipient_never_contacts_relay(
    smtp_settings, mock_smtp_client
) -> None:
    """R1.2: same precondition as `ConsoleEmailAdapter`/`MockWhatsAppAdapter`."""
    adapter = SMTPEmailAdapter()
    result = await adapter.send(
        recipient_contact="   ",
        subject="s",
        body="b",
        channel=NotificationChannel.EMAIL,
    )
    assert result.delivered is False
    assert result.error_code is NotificationErrorCode.INVALID_RECIPIENT
    mock_smtp_client.send_message.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "raised, expected_code",
    [
        (
            smtplib.SMTPRecipientsRefused({"guest@example.com": (550, b"unknown")}),
            NotificationErrorCode.INVALID_RECIPIENT,
        ),
        (
            smtplib.SMTPSenderRefused(550, b"denied", "noreply@example.com"),
            NotificationErrorCode.INVALID_RECIPIENT,
        ),
        (TimeoutError("timed out"), NotificationErrorCode.TIMEOUT),
        (smtplib.SMTPAuthenticationError(535, b"bad credentials"), NotificationErrorCode.ADAPTER_ERROR),
        (smtplib.SMTPConnectError(111, b"connection refused"), NotificationErrorCode.ADAPTER_ERROR),
        (smtplib.SMTPServerDisconnected("disconnected"), NotificationErrorCode.ADAPTER_ERROR),
        (OSError("network unreachable"), NotificationErrorCode.ADAPTER_ERROR),
    ],
)
async def test_smtp_adapter_maps_exceptions_to_error_codes(
    smtp_settings, mock_smtp_client, raised, expected_code
) -> None:
    """D4's exception → `NotificationErrorCode` table, and never a raise (R3.1)."""
    mock_smtp_client.send_message.side_effect = raised
    adapter = SMTPEmailAdapter()
    result = await adapter.send(
        recipient_contact="guest@example.com",
        subject="s",
        body="b",
        channel=NotificationChannel.EMAIL,
    )
    assert result.delivered is False
    assert result.error_code is expected_code


def test_registry_returns_console_adapter_when_smtp_host_empty(monkeypatch) -> None:
    """R2.1: no relay configured, no behaviour change."""
    monkeypatch.setattr(settings, "smtp_host", "")
    registry = adapter_registry()
    assert isinstance(registry[NotificationChannel.EMAIL], ConsoleEmailAdapter)
    assert registry[NotificationChannel.EMAIL] is registry[NotificationChannel.CONSOLE]


def test_registry_returns_smtp_adapter_when_fully_configured(smtp_settings) -> None:
    """R1.1/R2.1: a fully-configured relay switches EMAIL/CONSOLE to the real adapter."""
    registry = adapter_registry()
    assert isinstance(registry[NotificationChannel.EMAIL], SMTPEmailAdapter)
    assert registry[NotificationChannel.EMAIL] is registry[NotificationChannel.CONSOLE]


@pytest.mark.parametrize(
    "missing_field",
    ["smtp_port", "smtp_from_email", "smtp_username", "smtp_password"],
)
def test_registry_raises_on_partial_smtp_config(smtp_settings, monkeypatch, missing_field) -> None:
    """R2.2/R2.3: a half-configured relay fails loud, naming the missing field."""
    empty_value = 0 if missing_field == "smtp_port" else ""
    monkeypatch.setattr(settings, missing_field, empty_value)
    with pytest.raises(SMTPConfigurationError) as excinfo:
        adapter_registry()
    assert missing_field in str(excinfo.value)


def test_registry_refuses_tls_disabled_with_credentials(smtp_settings, monkeypatch) -> None:
    """Security panel finding (sections 1-4): `smtp_use_tls=False` with credentials set
    would put `SMTP_PASSWORD` and the mail itself on the wire in cleartext, since
    `client.login` is gated on username being set, not on TLS. Refused rather than trusted
    to an operator, same fail-loud shape as the four field checks above."""
    monkeypatch.setattr(settings, "smtp_use_tls", False)
    with pytest.raises(SMTPConfigurationError) as excinfo:
        adapter_registry()
    assert "smtp_use_tls" in str(excinfo.value)
