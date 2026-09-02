"""What a breached SLA escalates to (PRD §14, `celery-jobs` design D11).

Pure policy: no clock, no database, no session. It answers one question — given the type
of a notification whose SLA deadline has passed, what notification should exist now and
who should get it — and the use case does the writing.

**Deliberately sparse, and that is the design.** PRD §14 spells out two escalations and
then writes "etc."; this map implements those two and returns `None` for every other
member — including `TECHNICIAN_NO_RESPONSE`, which one of them now produces. Filling the
gap would be inventing product policy in a change whose job is the scheduler, and R5.6
already says what `None` means: mark the log as breached, record it, and do not invent a
recipient. A type that needs an escalation gets it in the change that
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

    `sla_minutes` is `None` for notifications that are not SLA-tracked (the catalog has
    them so a future SLA on the same type is intentional, not accidental). The breach
    job never reads a `None` entry because the candidate's own SLA deadline is what
    puts a row on the candidates list in the first place — so a `None` here is a
    documentation entry, not a path the job will ever exercise. Added when
    `REVIEW_RESPONSE_APPROVED` joined the catalog (design D9 of
    `sdd/changes/revenue-reviews/`).
    """

    notification_type: NotificationType
    recipient_role: UserRole
    reason: str
    sla_minutes: int | None = None


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
# **What the technician branch produces changed in `notification-writers-gap` (its R3).** It
# used to write `SLA_BREACH`, the same type the cleaning branch writes, so a manager reading
# the row could not tell an unanswered technician assignment from any other missed deadline
# without opening the breached row it points at. It now writes `TECHNICIAN_NO_RESPONSE`,
# which is the name PRD §14 already had for this and which nothing was writing. Only the
# type moved: the recipient, the reason and the `subject` of the row `_escalation_row`
# composes are untouched (R3.1, R3.3, design D8), and the cleaning branch stays `SLA_BREACH`
# because `sdd/specs/cleaning.md` fixes it that way (R3.2).
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
        # R3.4 holds by construction and not by an omission somebody could later fill in:
        # there is no `_POLICY` entry for `TECHNICIAN_NO_RESPONSE`, so `escalation_for`
        # returns `None` for what this produces and an escalation cannot escalate itself.
        #
        # And it survives someone adding that entry, which is the stronger guarantee and
        # the one worth writing down (found by the section-3 security panel): the row
        # `_escalation_row` composes is `PENDING` with **no** `sla_deadline_at`, while
        # `list_sla_breach_candidates` requires `SENT` *and* a deadline already past. An
        # escalation therefore cannot become a candidate for its own escalation, so the
        # per-minute job cannot write rows off its own output without someone also giving
        # this row a deadline and a delivery.
        notification_type=NotificationType.TECHNICIAN_NO_RESPONSE,
        recipient_role=UserRole.PROPERTY_MANAGER,
        reason="technician_assignment_unanswered_no_phone_adapter",
    ),
    # `REVIEW_RESPONSE_APPROVED` joins the catalog with `sla_minutes=None`: it is
    # not SLA-tracked (R6.2 says "notificación", not "notificación con plazo"), so
    # the breach job never produces a candidate for it. The entry exists so the
    # `_POLICY` catalog is closed against the `NotificationType` enum — a future
    # adding an SLA on this type is then an explicit decision, not a silently
    # missing row. The recipients are resolved by the writer (`reviews`'s
    # `ApproveReviewUseCase`) via `RoleRecipients.managers_or_owners`, exactly as
    # `maintenance` and `cleaning` already do.
    NotificationType.REVIEW_RESPONSE_APPROVED: Escalation(
        notification_type=NotificationType.REVIEW_RESPONSE_APPROVED,
        recipient_role=UserRole.PROPERTY_MANAGER,
        reason="review_response_approved_no_sla",
        sla_minutes=None,
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
