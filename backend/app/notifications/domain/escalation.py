"""What a breached SLA escalates to (PRD §14, `celery-jobs` design D11).

Pure policy: no clock, no database, no session. It answers one question — given the type
of a notification whose SLA deadline has passed, what notification should exist now and
who should get it — and the use case does the writing.

**Deliberately sparse, and that is the design.** PRD §14 spells out two escalations and
then writes "etc."; this map implements those two and returns `None` for the other
fourteen. Filling the gap would be inventing product policy in a change whose job is the
scheduler, and R5.6 already says what `None` means: mark the log as breached, record it,
and do not invent a recipient. A type that needs an escalation gets it in the change that
gives it an SLA deadline in the first place.
"""

from dataclasses import dataclass

from app.auth.domain.enums import UserRole
from app.notifications.domain.enums import NotificationType


@dataclass(frozen=True)
class Escalation:
    """The shape of the notification a breach produces.

    `recipient_role` is a role, not a user: who holds it is a question about the tenant's
    roster, which is `EscalateBreachedSlasUseCase`'s to answer (design D17 — one row per
    active holder, falling back to `TENANT_OWNER`). Keeping the id out of here is what
    lets this stay pure.
    """

    notification_type: NotificationType
    recipient_role: UserRole
    reason: str


# PRD §14: "CLEANING_TASK_ASSIGNED → crear nueva notificación al manager, marcar
# sla_breached=TRUE" and "TECHNICIAN_ASSIGNED + CRITICAL → intentar
# PhoneAdapter.call(technician)".
#
# The second one cannot be honoured as written: `steering/architecture.md` lists
# `PhoneAdapter` among the adapters the system will have, and **that one** has never been
# built (`PMSAdapter` has two implementations; `PhoneAdapter` has no port and no
# implementation). It escalates to the manager instead, and the reason says so rather than
# pretending a call was placed. `access-notifications` owns the adapters and can revisit it.
#
# The CRITICAL qualifier of PRD §14 is not evaluated either, and the precise reason
# matters for whoever revisits this: `notification_logs` records a type and no severity,
# so it is unavailable **at this layer** — not unavailable full stop. A later layer can
# reach `incidents.severity` through the polymorphic `related_type`/`related_id` pair, so
# do not re-cite this comment as "impossible". Today both cases collapse to the same
# escalation because nothing needs them apart.
_POLICY: dict[NotificationType, Escalation] = {
    NotificationType.CLEANING_TASK_ASSIGNED: Escalation(
        notification_type=NotificationType.SLA_BREACH,
        recipient_role=UserRole.PROPERTY_MANAGER,
        reason="cleaning_assignment_unanswered",
    ),
    NotificationType.TECHNICIAN_ASSIGNED: Escalation(
        notification_type=NotificationType.SLA_BREACH,
        recipient_role=UserRole.PROPERTY_MANAGER,
        reason="technician_assignment_unanswered_no_phone_adapter",
    ),
}


def escalation_for(notification_type: str) -> Escalation | None:
    """The escalation for a breached notification, or `None` when there is none defined.

    Takes a `str` because that is what the column holds: a row written before
    `NotificationType` existed — or by a future writer that does not know it — must not
    make the job crash. An unrecognised value is simply a type with no escalation, which
    R5.6 already handles.
    """
    try:
        known = NotificationType(notification_type)
    except ValueError:
        return None
    return _POLICY.get(known)
