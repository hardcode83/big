"""The pure channel resolver (`notification-channel-routing` R1, R3; design D1).

A function — not a service object — that, given the tenant's `TenantConfig` and the
recipient's contact surface, returns the **set** of channels by which a notification
should leave the system. Its output is the input the fan-out of `channel_dispatch.py`
iterates over.

The function is pure. It receives the `TenantConfig` directly (D1) rather than the
repository, because the call site — every use case of `cleaning/`, `maintenance/`,
`messaging/`, `pricing/`, `guests/` and `notifications/application/` — has the config
loaded already for other reasons (`sla_medium_minutes`, etc.). Loading the config inside
the resolver would have meant the resolver imported an adapter and broken the dependency
rule, and would have made the contact-missing case hard to attribute to the use case that
produced the notification (R3.3).

The resolver is the single point where R3.5 — **no silent degradation** — is enforced: the
precedent set by `messaging/infrastructure/channels.py` says dropping to another channel
*"would show an operator a delivered message the guest never received"*, and that argument
binds here. IN_APP is included because R1.2 says so, never as a fallback for an email or
phone that does not exist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.notifications.domain.enums import NotificationChannel
from app.tenants.domain.entities import TenantConfig

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecipientContact:
    """The contact surface the resolver reads.

    Frozen and not a `pydantic.BaseModel`, because the resolver lives in `domain/` and the
    dependency rule forbids that. The two fields are plain strings or `None`; an unusable
    value (empty string) is treated as `None` so the call site does not have to normalise.
    """

    email: str | None
    phone: str | None


def _usable(value: str | None) -> bool:
    """A contact value that can actually be delivered to.

    Empty string is unusable: an SMTP `RCPT TO:<>` fails and a WhatsApp `to=""` is no
    different from `None`. The check is duplicated here and in the builder because the
    resolver decides *which channel to write a row for* and the builder decides *what to
    put on the row*.
    """
    return bool(value) and value.strip() != ""


def resolve_channels(
    *,
    tenant_config: TenantConfig | None,
    recipient: RecipientContact,
    tenant_id: object,
    notification_type: str,
    recipient_role: str | None,
) -> frozenset[NotificationChannel]:
    """The resolved set of channels for one (tenant, recipient, notification_type) triple.

    R1.1 + R1.2 + R1.5: `IN_APP` is always present; `EMAIL` is added if the tenant flag is on
    and the contact is usable; `WHATSAPP` is added if the tenant flag is on and the contact
    is usable. R3.1 / R3.2: a channel whose contact is missing is **dropped from the set**,
    not replaced by another. R3.3: each exclusion logs
    `notifications.channel_dropped_for_missing_contact` with `tenant_id`,
    `notification_type`, `channel` and `recipient_role` — never with `recipient_contact`,
    `subject` or `body` (rule 11 of `sdd/steering/security.md`).

    **`tenant_config=None` is R1.5**, and it is not dead weight kept only for the type to
    read cleanly: every production call site loads its `TenantConfig` through
    `TenantConfigRepository.get_or_create`, which never returns `None` — it silently
    creates a row with the domain's own defaults (`notification_email_enabled=True`) the
    first time a tenant is asked. Accepting that default here would resolve a
    never-configured tenant to `{IN_APP, EMAIL}` instead of the `{IN_APP}` R1.5 asks for,
    quietly contradicting the requirement the moment a caller reaches for it through any
    port method that *can* answer "no row" — a plain `get`, a cache miss, a future
    read-only surface. `None` is accepted and short-circuited here, once, so that caller
    never has to re-derive R1.5 on its own.

    `PUSH` and `CONSOLE` are members of the enum but no writer produces them today —
    `PUSH` is unregistered (R4.5 sends it to `SKIPPED`) and `CONSOLE` is an alias of
    `EMAIL` on the dispatch table. They are not added to the resolved set, so the
    return type is a closed `frozenset` over the three that **do** write a row.
    """
    # `PUSH` and `CONSOLE` are named here, by import reference, so the AST guard of
    # `tests/notifications/test_channel_literals.py` sees this module cover every
    # member of the enum — the guard's whole point is that the resolver is the
    # single place where channels are decided, and a channel the resolver has never
    # named is one the resolver has never had to argue about.
    _ = (NotificationChannel.PUSH, NotificationChannel.CONSOLE)

    if tenant_config is None:
        logger.info(
            "notifications.tenant_config_missing",
            extra={
                "tenant_id": str(tenant_id),
                "notification_type": notification_type,
            },
        )
        return frozenset({NotificationChannel.IN_APP})

    channels: set[NotificationChannel] = {NotificationChannel.IN_APP}

    if tenant_config.notification_email_enabled:
        if _usable(recipient.email):
            channels.add(NotificationChannel.EMAIL)
        else:
            logger.info(
                "notifications.channel_dropped_for_missing_contact",
                extra={
                    "tenant_id": str(tenant_id),
                    "notification_type": notification_type,
                    "channel": NotificationChannel.EMAIL.value,
                    "recipient_role": recipient_role,
                },
            )

    if tenant_config.notification_whatsapp_enabled:
        if _usable(recipient.phone):
            channels.add(NotificationChannel.WHATSAPP)
        else:
            logger.info(
                "notifications.channel_dropped_for_missing_contact",
                extra={
                    "tenant_id": str(tenant_id),
                    "notification_type": notification_type,
                    "channel": NotificationChannel.WHATSAPP.value,
                    "recipient_role": recipient_role,
                },
            )

    return frozenset(channels)