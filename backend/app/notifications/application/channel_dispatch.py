"""The channel fan-out (`notification-channel-routing` R2, R4; design D2, D3).

The thin function that turns a single notification intent into the **N rows** the
multi-channel reality of R2 demands. The shape is deliberately narrow: it does not know
which `NotificationType` it is fanning out, does not write to the database, and does not
know about the adapter registry. It calls the domain builder once per channel with the
channel-specific contact, and returns the rows for the caller to persist.

**Why the function is pure** (design D2, rejected (a)): the resolver and the builder are
two responsibilities, and the fan-out's job is to bridge between them. Mixing the bridge
with persistence would make "the resolver is a domain function, the builder is a domain
function" untrue — the fan-out would be the third place the row is shaped. The caller
already has a `NotificationLogRepository` from its constructor, so writing the rows back
is one `for` loop.

**Why the function is one-for-one with channels, not one row with N channels**: R2.1 says
*"N filas en `notification_logs`, idénticas en ... y distintas en `channel`"*. The schema's
`channel` is singular, and `dispatch_notifications` drains `PENDING` per row. A single
row with N channels would need a new column type and a different dispatcher; the proposal
rejects that on shape (design D2).

**The `sla_deadline_at` decision lives in the builder, not here** (design D3): only the
builder knows whether the row carries a deadline (R4.1 says the IN_APP row is the one),
and the rejected option — setting the deadline here — would mean every channel of a
fanned-out notification is a breach candidate. The builder decides from the `channel`
parameter it receives.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from app.auth.domain.entities import User
from app.notifications.domain.channel_resolver import (
    RecipientContact,
    resolve_channels,
)
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel
from app.notifications.domain.repositories import NotificationLogRepository
from app.tenants.domain.entities import TenantConfig


def _contact_for_channel(channel: NotificationChannel, recipient: User) -> str | None:
    """The contact to put on a row of this channel.

    R2.3 — IN_APP and EMAIL share `User.email` (the inbox and the email inbox read the
    same address); WHATSAPP uses `User.phone`. PUSH and CONSOLE are not produced by any
    writer in this codebase, but the function answers them too: PUSH has no address in
    the `User` entity, CONSOLE has none either. Both return `None`, which the builder
    is free to use as it sees fit — typically, to refuse to write the row at all.
    """
    # `PUSH` and `CONSOLE` are referenced by name so the AST guard that lists this
    # module as one of three sites that have to cover every enum member has a
    # concrete pin — the alternative would be a separate `_ = (...)` no-op, but
    # the docstring above is the documentation readers see, so we keep them on the
    # surface too.
    _PUSH_OR_CONSOLE = (NotificationChannel.PUSH, NotificationChannel.CONSOLE)
    if channel in (NotificationChannel.IN_APP, NotificationChannel.EMAIL):
        return recipient.email
    if channel == NotificationChannel.WHATSAPP:
        return recipient.phone
    if channel in _PUSH_OR_CONSOLE:
        return None
    return None


def dispatch_channels(
    *,
    recipient: User,
    channels: frozenset[NotificationChannel],
    log_builder: Callable[..., NotificationLog],
    **builder_kwargs: Any,
) -> list[NotificationLog]:
    """Fan one notification intent out into one row per channel.

    Calls `log_builder(channel=…, contact=…, **builder_kwargs)` once per channel in
    `channels`, collects the rows and returns them. **Order is not guaranteed** to match
    the order of `channels` — callers must treat the result as a set, not a sequence.

    The builder is expected to:

      * derive `recipient_contact` from `contact` (R2.3);
      * fix `sla_deadline_at` only when `channel == IN_APP` (R4.1);
      * leave `status = PENDING` (R2.3) — delivery is `dispatch_notifications`' job.

    Persistence is the caller's responsibility, one row at a time through
    `NotificationLogRepository.add`. Splitting the write out keeps this function pure
    and lets the use case own the unit of work.
    """
    rows: list[NotificationLog] = []
    for channel in channels:
        contact = _contact_for_channel(channel, recipient)
        # `tenant_id` is forwarded if the caller put it in kwargs; otherwise the builder
        # is expected to receive it some other way. Today every builder takes it as a
        # keyword-only argument, so the call sites pass it explicitly.
        row = log_builder(channel=channel, contact=contact, **builder_kwargs)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Internal helpers used by the escalated row composer in
# `notifications/application/use_cases.py`, which needs the per-channel contact for the
# `recipient_contact` it writes on the escalation row. Kept here so the rule
# "IN_APP/EMAIL share email, WHATSAPP uses phone" lives in one place.
# ---------------------------------------------------------------------------


def contact_for_channel(channel: NotificationChannel, recipient: User) -> str | None:
    """Public alias for `_contact_for_channel`, for callers outside the fan-out."""
    return _contact_for_channel(channel, recipient)


async def dispatch_and_persist(
    *,
    notifications: NotificationLogRepository,
    tenant_id: uuid.UUID,
    recipient: User,
    config: TenantConfig | None,
    notification_type: str,
    recipient_role: str | None,
    log_builder: Callable[..., NotificationLog],
    **builder_kwargs: Any,
) -> list[NotificationLog]:
    """Resolve channels, build N rows and persist them — the common shape of the use cases.

    `dispatch_channels` is pure; this is its side-effecting twin. Use it from a use case
    that already has the `TenantConfig` and `NotificationLogRepository` wired in, and
    don't reach for the fan-out by hand.

    `config=None` is forwarded straight to `resolve_channels`, which is where R1.5's
    single-`{IN_APP}` shortcut and its `notifications.tenant_config_missing` log live —
    see that function's docstring for why a caller can be in this state even though
    `TenantConfigRepository.get_or_create` never is.

    `tenant_id` is **always** forwarded to the builder — every builder in the codebase
    takes it as a keyword-only argument, and surfacing it through the wrapper keeps the
    call sites from naming it twice.
    """
    channels = resolve_channels(
        tenant_config=config,
        recipient=RecipientContact(email=recipient.email, phone=recipient.phone),
        tenant_id=tenant_id,
        notification_type=notification_type,
        recipient_role=recipient_role,
    )
    rows = dispatch_channels(
        recipient=recipient,
        channels=channels,
        log_builder=log_builder,
        tenant_id=tenant_id,
        **builder_kwargs,
    )
    for row in rows:
        await notifications.add(tenant_id, row)
    return rows


__all__ = ["dispatch_channels", "dispatch_and_persist", "contact_for_channel"]