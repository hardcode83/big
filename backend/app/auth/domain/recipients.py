"""Who on a tenant hears about something — asked once, answered once (R5.1, design D1).

**Why this lives in `auth` and not next to any of its callers.** The question it answers is
about the tenant's roster: the aggregate is `User` and the port is `UserRepository`, both of
which are `auth`'s. Putting it here means `cleaning`, `maintenance`, `pricing`, `guests` and
`notifications` import *inwards* to a domain they already depend on, and this module imports
nothing from any of them. The rejected alternatives are recorded in design D1, and the
sharpest one is worth repeating: a home under `notifications/application/` would have been
the first `application/` → `application/` import between domains in the repo.

It is a legitimate `domain/` service and not a repository helper: it receives a port, touches
no session and no SQL, and the manager→owner fallback **is a business rule** —
`steering/backend-architecture.md` is explicit that a rule does not belong in `application/`.

**The truncation log is deliberately not emitted here.** Each caller keeps its own key
(`scheduler.escalation_recipients_truncated` and the ones this change adds), because the name
of a log belongs to the site that emits it: the same "we notified a subset" event means
something different in the nightly scheduler than in a cleaning completion. So this returns
`dropped` as a number and lets the caller say it.
"""

import uuid
from dataclasses import dataclass

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.ports import UserRepository
from app.auth.domain.repositories import UserFilters


@dataclass(frozen=True)
class Recipients:
    """The people to write to, and how many the page left behind.

    `dropped` is not decoration and not a later addition: `EscalateBreachedSlasUseCase`
    already folds it into `EscalationReport.recipients_truncated`, so a helper without it
    could not have absorbed that caller — which was the whole point of writing this one
    (design D1). A subset silently notified is the failure mode that counter exists for.

    Frozen because a resolved recipient list is an answer, not a working buffer: a caller
    that could append to it would be inventing a recipient the roster never returned.
    """

    users: tuple[User, ...]
    dropped: int = 0


class RoleRecipients:
    """The two recipient questions this codebase asks, and no third one.

    `managers_or_owners` is the pattern `celery-jobs` fixed and R5.1 makes binding: every
    active `PROPERTY_MANAGER`, or — when the tenant has none — every active `TENANT_OWNER`.
    `active_holders` is its parameterised half, for the caller that already knows the role it
    wants (the escalation policy names one) or that needs the **union** rather than the
    fallback (R4.4's price recommendation, where the owner approves and must not be dropped
    merely because a manager exists).
    """

    #: A tenant's roster is small (PRD §1: two flats and a handful of people) and the roles
    #: that receive notifications are the administrative ones, so one page is the whole
    #: answer. The same bound and the same reasoning as the two implementations this
    #: replaces, kept as a class attribute so a caller can assert against it instead of
    #: rediscovering the number.
    MAX_RECIPIENTS = 100

    def __init__(self, *, users: UserRepository) -> None:
        self._users = users

    async def managers_or_owners(self, tenant_id: uuid.UUID) -> Recipients:
        """Active managers, falling back to active owners (R5.1).

        The fallback is not defensive padding: `TENANT_OWNER` always exists — the invariant
        `count_active_owners_excluding` of `user-management` protects — so a tenant that has
        not hired a manager still gets told, instead of losing the notification.

        Returning empty is a real outcome (R5.2) rather than an error, because what it means
        is the caller's to decide: the escalation job leaves the breach unmarked so an
        operator is forced to fix the roster, while the writers this change adds skip the row
        and log. Raising here would take that choice away from every one of them.
        """
        holders = await self.active_holders(tenant_id, UserRole.PROPERTY_MANAGER)
        if holders.users:
            return holders
        # The count from the empty primary page is kept: a page that returned nothing dropped
        # nothing, so this only ever carries the fallback's own truncation forward.
        fallback = await self.active_holders(tenant_id, UserRole.TENANT_OWNER)
        return Recipients(
            users=fallback.users, dropped=holders.dropped + fallback.dropped
        )

    async def active_holders(self, tenant_id: uuid.UUID, role: UserRole) -> Recipients:
        """One page of the tenant's ACTIVE holders of `role`, counting what it left out.

        Both the primary role and the owner fallback come through here, which is the fix the
        escalation job needed: when they were two inline queries only the first counted its
        truncation, so a tenant with more than one page of owners and no manager notified a
        subset with the counter still at zero.
        """
        page = await self._users.list(
            tenant_id,
            UserFilters(role=role, status=UserStatus.ACTIVE),
            page=1,
            per_page=self.MAX_RECIPIENTS,
        )
        return Recipients(
            users=tuple(page.items), dropped=max(page.total - len(page.items), 0)
        )
