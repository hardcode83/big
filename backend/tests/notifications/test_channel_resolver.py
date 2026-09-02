"""The pure channel resolver (R1, R3 of `notification-channel-routing`).

The resolver is a **function**, not a service object — the proposal and design D1 say it is
called once per recipient by the use cases of each module, which already have the
`TenantConfig` loaded, so the shape is a free function that returns the resolved set and
side-effects the log for the contact-missing case.

`RecipientContact` is a frozen dataclass, the `tenant_config` is the `TenantConfig` value
object of `app.tenants/domain/entities.py`, and the return is a `frozenset[NotificationChannel]`
— frozen, so a caller cannot mutate it by accident and the function can return the same
singleton for the common `{IN_APP}` case without callers aliasing it.
"""

from __future__ import annotations

import logging
import uuid

import pytest

from app.notifications.domain.channel_resolver import (
    RecipientContact,
    resolve_channels,
)
from app.notifications.domain.enums import NotificationChannel
from app.tenants.domain.entities import TenantConfig
from app.tenants.domain.enums import StorageType


def _tenant_config(
    *,
    email_enabled: bool = True,
    whatsapp_enabled: bool = False,
) -> TenantConfig:
    """Build a TenantConfig with the two flags the resolver reads, defaults per PRD §14."""
    return TenantConfig(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        created_at=_NOW,
        updated_at=_NOW,
        notification_email_enabled=email_enabled,
        notification_whatsapp_enabled=whatsapp_enabled,
        storage_type=StorageType.LOCAL,
    )


def _contact(*, email: str | None = "u@example.com", phone: str | None = "+34000000000") -> RecipientContact:
    return RecipientContact(email=email, phone=phone)


from datetime import datetime, timezone

_NOW = datetime(2026, 8, 31, tzinfo=timezone.utc)


class TestResolveChannels:
    """R1.1 — IN_APP always; +EMAIL if flag; +WHATSAPP if flag."""

    def test_returns_only_in_app_when_both_flags_are_off(self) -> None:
        config = _tenant_config(email_enabled=False, whatsapp_enabled=False)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset({NotificationChannel.IN_APP})

    def test_adds_email_when_email_flag_is_on(self) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=False)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
        )

    def test_adds_whatsapp_when_whatsapp_flag_is_on(self) -> None:
        config = _tenant_config(email_enabled=False, whatsapp_enabled=True)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.WHATSAPP}
        )

    def test_returns_all_three_when_both_flags_are_on_and_contacts_present(self) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset(
            {
                NotificationChannel.IN_APP,
                NotificationChannel.EMAIL,
                NotificationChannel.WHATSAPP,
            }
        )

    def test_in_app_is_always_included_regardless_of_flags(self) -> None:
        # R1.2 — no configuration can silence the inbox.
        config = _tenant_config(email_enabled=False, whatsapp_enabled=False)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert NotificationChannel.IN_APP in resolved


class TestTenantConfigMissing:
    """R1.5 — no recoverable `tenant_configs` row resolves to `{IN_APP}` and logs it.

    `tenant_config=None` is the caller's way of saying "I could not recover a config row" —
    `TenantConfigRepository.get_or_create` never actually returns `None` (it silently
    creates a row with the domain's own defaults, `notification_email_enabled=True`, the
    first time), so accepting that default here would resolve a never-configured tenant to
    `{IN_APP, EMAIL}` instead of what R1.5 asks for. The resolver's `None` branch is what
    keeps that promise regardless of which port method a future caller reaches for.
    """

    def test_none_config_resolves_to_in_app_only(self) -> None:
        tenant_id = uuid.uuid4()
        resolved = resolve_channels(
            tenant_config=None,
            recipient=_contact(),
            tenant_id=tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset({NotificationChannel.IN_APP})

    def test_none_config_resolves_to_in_app_only_even_with_full_contacts(self) -> None:
        # Not a contact-missing case: both email and phone are usable. The exclusion is
        # about the config, not the recipient — proving the two reasons stay independent.
        resolved = resolve_channels(
            tenant_config=None,
            recipient=_contact(email="u@example.com", phone="+34000000000"),
            tenant_id=uuid.uuid4(),
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset({NotificationChannel.IN_APP})

    def test_logs_tenant_config_missing_with_tenant_id_and_type(self, caplog) -> None:
        tenant_id = uuid.uuid4()
        with caplog.at_level(logging.INFO, logger="app.notifications.domain.channel_resolver"):
            resolve_channels(
                tenant_config=None,
                recipient=_contact(),
                tenant_id=tenant_id,
                notification_type="OWNER_APPROVAL_REQUIRED",
                recipient_role="TENANT_OWNER",
            )
        records = [
            r for r in caplog.records if r.message == "notifications.tenant_config_missing"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.tenant_id == str(tenant_id)  # type: ignore[attr-defined]
        assert record.notification_type == "OWNER_APPROVAL_REQUIRED"  # type: ignore[attr-defined]
        # Rule 11 — never log the contact value, subject or body.
        assert not hasattr(record, "recipient_contact")
        assert not hasattr(record, "subject")
        assert not hasattr(record, "body")

    def test_does_not_log_channel_dropped_when_config_is_missing(self, caplog) -> None:
        # The missing-config branch short-circuits before any per-channel logic runs, so
        # it must never also emit the contact-missing log for EMAIL/WHATSAPP.
        with caplog.at_level(logging.INFO, logger="app.notifications.domain.channel_resolver"):
            resolve_channels(
                tenant_config=None,
                recipient=_contact(email=None, phone=None),
                tenant_id=uuid.uuid4(),
                notification_type="CLEANING_TASK_ASSIGNED",
                recipient_role="CLEANER",
            )
        dropped = [
            r for r in caplog.records if r.message == "notifications.channel_dropped_for_missing_contact"
        ]
        assert dropped == []


class TestContactMissingExclusions:
    """R3.1 / R3.2 — drop the channel whose contact is missing; do not degrade."""

    def test_whatsapp_is_dropped_when_phone_is_none(self) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(email="u@example.com", phone=None),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
        )

    def test_whatsapp_is_dropped_when_phone_is_empty_string(self) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(email="u@example.com", phone=""),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
        )

    def test_email_is_dropped_when_email_is_none(self) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(email=None, phone="+34000000000"),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.WHATSAPP}
        )

    def test_email_is_dropped_when_email_is_empty_string(self) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(email="", phone="+34000000000"),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.WHATSAPP}
        )

    def test_both_excluded_yields_only_in_app(self) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(email=None, phone=None),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        assert resolved == frozenset({NotificationChannel.IN_APP})

    def test_no_silent_degradation_when_only_whatsapp_resolves(self) -> None:
        # R3.5 — the resolver does NOT silently swap a missing EMAIL for IN_APP:
        # IN_APP is included by R1, not as a fallback.
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        resolved = resolve_channels(
            tenant_config=config,
            recipient=_contact(email=None, phone=None),
            tenant_id=config.tenant_id,
            notification_type="CLEANING_TASK_ASSIGNED",
            recipient_role="CLEANER",
        )
        # EMAIL is excluded (no email); WHATSAPP is excluded (no phone); IN_APP survives.
        assert resolved == frozenset({NotificationChannel.IN_APP})


class TestContactMissingLogging:
    """R3.3 — log the exclusion with type and channel, nothing else (rule 11)."""

    def test_logs_whatsapp_exclusion_with_type_channel_tenant_id(self, caplog) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        tenant_id = config.tenant_id
        with caplog.at_level(logging.INFO, logger="app.notifications.domain.channel_resolver"):
            resolve_channels(
                tenant_config=config,
                recipient=_contact(email="u@example.com", phone=None),
                tenant_id=tenant_id,
                notification_type="CLEANING_TASK_ASSIGNED",
                recipient_role="CLEANER",
            )
        records = [
            r for r in caplog.records if r.message == "notifications.channel_dropped_for_missing_contact"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.channel == NotificationChannel.WHATSAPP.value  # type: ignore[attr-defined]
        assert record.tenant_id == str(tenant_id)  # type: ignore[attr-defined]
        assert record.notification_type == "CLEANING_TASK_ASSIGNED"  # type: ignore[attr-defined]
        assert record.recipient_role == "CLEANER"  # type: ignore[attr-defined]
        # Rule 11 — never log the contact value, subject or body.
        assert not hasattr(record, "recipient_contact")
        assert not hasattr(record, "subject")
        assert not hasattr(record, "body")

    def test_logs_email_exclusion(self, caplog) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        with caplog.at_level(logging.INFO, logger="app.notifications.domain.channel_resolver"):
            resolve_channels(
                tenant_config=config,
                recipient=_contact(email=None, phone="+34000000000"),
                tenant_id=config.tenant_id,
                notification_type="OWNER_APPROVAL_REQUIRED",
                recipient_role="TENANT_OWNER",
            )
        records = [
            r for r in caplog.records if r.message == "notifications.channel_dropped_for_missing_contact"
        ]
        assert len(records) == 1
        record = records[0]
        assert record.channel == NotificationChannel.EMAIL.value  # type: ignore[attr-defined]
        assert record.notification_type == "OWNER_APPROVAL_REQUIRED"  # type: ignore[attr-defined]

    def test_does_not_log_when_no_exclusion(self, caplog) -> None:
        config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
        with caplog.at_level(logging.INFO, logger="app.notifications.domain.channel_resolver"):
            resolve_channels(
                tenant_config=config,
                recipient=_contact(),
                tenant_id=config.tenant_id,
                notification_type="CLEANING_TASK_ASSIGNED",
                recipient_role="CLEANER",
            )
        records = [
            r for r in caplog.records if r.message == "notifications.channel_dropped_for_missing_contact"
        ]
        assert records == []


@pytest.mark.parametrize(
    "email_enabled,whatsapp_enabled,email,phone,expected",
    [
        # Two flags on, both contacts present → three channels.
        (True, True, "u@e.com", "+34", frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL, NotificationChannel.WHATSAPP}
        )),
        # Two flags on, phone missing → IN_APP + EMAIL.
        (True, True, "u@e.com", None, frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
        )),
        # Two flags on, email missing → IN_APP + WHATSAPP.
        (True, True, None, "+34", frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.WHATSAPP}
        )),
        # Two flags on, both missing → IN_APP only.
        (True, True, None, None, frozenset({NotificationChannel.IN_APP})),
        # Two flags off, contacts irrelevant → IN_APP only.
        (False, False, "u@e.com", "+34", frozenset({NotificationChannel.IN_APP})),
        # Email off, whatsapp on, contacts present → IN_APP + WHATSAPP.
        (False, True, "u@e.com", "+34", frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.WHATSAPP}
        )),
        # Email on, whatsapp off → IN_APP + EMAIL.
        (True, False, "u@e.com", "+34", frozenset(
            {NotificationChannel.IN_APP, NotificationChannel.EMAIL}
        )),
    ],
)
def test_matrix(
    email_enabled: bool,
    whatsapp_enabled: bool,
    email: str | None,
    phone: str | None,
    expected: frozenset[NotificationChannel],
) -> None:
    """The full matrix the proposal says the resolver must cover (R1.1, R3)."""
    config = _tenant_config(
        email_enabled=email_enabled, whatsapp_enabled=whatsapp_enabled
    )
    resolved = resolve_channels(
        tenant_config=config,
        recipient=_contact(email=email, phone=phone),
        tenant_id=config.tenant_id,
        notification_type="CLEANING_TASK_ASSIGNED",
        recipient_role="CLEANER",
    )
    assert resolved == expected


def test_returned_set_is_immutable() -> None:
    """The resolver returns a `frozenset` — a caller must not be able to mutate the resolved set."""
    config = _tenant_config(email_enabled=True, whatsapp_enabled=True)
    resolved = resolve_channels(
        tenant_config=config,
        recipient=_contact(),
        tenant_id=config.tenant_id,
        notification_type="CLEANING_TASK_ASSIGNED",
        recipient_role="CLEANER",
    )
    assert isinstance(resolved, frozenset)
    with pytest.raises(AttributeError):
        resolved.add(NotificationChannel.PUSH)  # type: ignore[attr-defined]


def test_no_imports_from_infrastructure_or_application() -> None:
    """D1 — the resolver is a pure domain module; it does not import FastAPI/SQLAlchemy.

    The test is on the **import statements** rather than on substrings: a docstring can
    name a forbidden module without importing it, and the rule is about dependencies. AST
    walks every `import` / `import from` and rejects names from the forbidden set.
    """
    import ast
    import pathlib

    path = (
        pathlib.Path(__file__).resolve().parents[2]
        / "app"
        / "notifications"
        / "domain"
        / "channel_resolver.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    forbidden = {"sqlalchemy", "fastapi", "pydantic"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in forbidden:
                    offenders.append(f"{alias.name} at line {node.lineno}")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in forbidden:
                offenders.append(f"{module} at line {node.lineno}")
    assert not offenders, (
        "channel_resolver.py must not import infrastructure modules: " + ", ".join(offenders)
    )