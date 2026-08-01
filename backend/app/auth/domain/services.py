"""Domain rules of user administration that span more than one account (R3.6, design D6).

Lives here rather than on `User` because the rule needs the POPULATION: "does this tenant
still have an administrator" is not answerable from one row. Pure on purpose — the caller
supplies the count, so the rule is exhaustively testable without a database, and the only
thing left for the integration test is the locking that makes the count trustworthy.
"""

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.exceptions import LastOwnerError


def assert_tenant_keeps_an_owner(
    *,
    target: User,
    new_role: UserRole | None,
    new_status: UserStatus | None,
    other_active_owners: int,
) -> None:
    """Refuse an operation that would leave the tenant with no ACTIVE `TENANT_OWNER`.

    Evaluated on the **result**, not field by field: a `PATCH` that demotes and deactivates
    in one body has to be judged as a whole, the same way `reservations` revalidates its
    date invariants on the result of the patch.

    `other_active_owners` must EXCLUDE the target — otherwise the target would count itself
    as the owner that survives its own demotion, and the rule would never fire.

    The caller must have taken the tenant lock before counting (design D6): two concurrent
    demotions of two different owners each see the other as active, and without
    serialisation both are allowed through and the tenant ends up with none.
    """
    if other_active_owners < 0:
        raise ValueError("other_active_owners cannot be negative")

    def _is_active_owner(role: UserRole, status: UserStatus) -> bool:
        # SUSPENDED counts as absent, not as a lesser form of present:
        # `SqlAlchemyUserRepository.get_active_by_id` only resolves ACTIVE users, so a
        # suspended owner cannot authenticate and cannot administer anything.
        return role is UserRole.TENANT_OWNER and status is UserStatus.ACTIVE

    was = _is_active_owner(target.role, target.status)
    will_be = _is_active_owner(
        new_role if new_role is not None else target.role,
        new_status if new_status is not None else target.status,
    )

    if was and not will_be and other_active_owners == 0:
        raise LastOwnerError(
            "This would leave the tenant without an active owner, and there is no endpoint "
            "to appoint one from outside it"
        )

