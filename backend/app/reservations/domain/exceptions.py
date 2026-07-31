"""Domain errors of the reservations module (R1, R5, design D6, D9).

Pure Python, exactly like `app/auth/domain/exceptions.py`: no import of
`app.core.errors`, because that module imports FastAPI and pulling it in here would put
the web framework inside `domain/` through the back door — transitively, so
`tests/test_layering.py` would not even catch it. The translation to a status code and
an error code lives in `app/reservations/api/errors.py`, the one declared place for it.

Why these four and not one generic error: each names a business outcome the callers
have to tell apart (422 vs 404 vs 409), and the mapping is then a property of the
outcome instead of a decision retaken in every router.
"""


class ReservationDomainError(Exception):
    """Base error for the reservations domain."""


class ReservationValidationError(ReservationDomainError):
    """An invariant of the aggregate was violated (R1.3) — answered 422."""


class ReservationNotFoundError(ReservationDomainError):
    """The reservation does not exist *within the acting tenant* — answered 404.

    Deliberately the same error whether the id is unknown or belongs to another tenant:
    that indistinguishability IS requirement R5.1 (design D6). A separate "exists but is
    not yours" error would leak the existence of a neighbour's booking through nothing
    more than an exception type.
    """


class PropertyNotFoundError(ReservationDomainError):
    """The referenced property does not exist within the acting tenant (R1.4) — 404."""


class GuestNotFoundError(ReservationDomainError):
    """The `guest_id` being linked does not exist within the acting tenant — 404.

    Same reasoning as `ReservationNotFoundError`: a guest of another tenant must be
    indistinguishable from one that does not exist, or the endpoint becomes a probe for
    which guest ids a neighbour holds (R5.1).
    """


class DuplicateExternalReservationError(ReservationDomainError):
    """Another reservation of this tenant already carries that `external_pms_id` — 409.

    Raised from the `IntegrityError` of `uq_reservations_tenant_id_external_pms_id`
    (design D9), so the constraint stays the authority and a concurrent insert cannot
    slip past a read-then-write check.
    """
