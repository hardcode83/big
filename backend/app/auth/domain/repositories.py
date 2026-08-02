"""Filters and page shape of the user listing (R2.1, R2.2, R2.4, design D17).

In `domain/` rather than in the router because `steering/backend.md` says "la lógica nunca
vive en el router": the bounds and the contradiction check belong to whoever asks for a page,
so a future caller — a dashboard aggregate, an export — gets the same answers instead of
silently receiving zero rows or an unhandled driver error.

Same split `reservations` makes between `ReservationFilters`/`Page` and its port.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.auth.domain.enums import UserRole, UserStatus

if TYPE_CHECKING:  # pragma: no cover - import cycle: entities does not need this module
    from app.auth.domain.entities import User

MAX_PER_PAGE = 100
# `page` needs a ceiling as much as `per_page` does: it becomes a SQL OFFSET, and a
# 20-digit page number overflows int8 and comes back as an unhandled driver error instead of
# a 422 in the PRD §23 envelope. Same value and same reason as `reservations` (its R1.2).
MAX_PAGE = 100_000


@dataclass(frozen=True)
class UserFilters:
    """The filters of `GET /api/v1/users` (R2.4), combined with AND.

    Both map onto an existing index — `ix_users_tenant_id_role` and
    `ix_users_tenant_id_status` — so filtering the roster is cheap by construction.
    """

    role: UserRole | None = None
    status: UserStatus | None = None


@dataclass(frozen=True)
class UserPage:
    """One page of users plus the total the client needs for `total_pages` (PRD §23)."""

    items: tuple["User", ...]
    total: int


def validate_pagination(*, page: int, per_page: int) -> None:
    """Raise `ValueError` outside the supported bounds.

    The API layer also declares them with `Query(ge=..., le=...)` so FastAPI answers `422`
    before a use case runs; this is the same rule for every other caller.
    """
    if page < 1 or page > MAX_PAGE:
        raise ValueError(f"page must be between 1 and {MAX_PAGE}")
    if per_page < 1 or per_page > MAX_PER_PAGE:
        raise ValueError(f"per_page must be between 1 and {MAX_PER_PAGE}")


def offset_for(*, page: int, per_page: int) -> int:
    validate_pagination(page=page, per_page=per_page)
    return (page - 1) * per_page
