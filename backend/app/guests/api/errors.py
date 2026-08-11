"""Maps guests errors onto the PRD §23 envelope.

Same shape as `app/access/api/errors.py`. `_MAPPING` is exhaustive over
`app/guests/domain/exceptions.py` — every subclass of `GuestDomainError` has a row, and the
fallthrough to `500` exists only for a subclass added without one.

**One handler sits outside that table, and deliberately**: `IntegrityError` is not a domain
error at all, it is a constraint firing underneath the use case. `guest-portal-api` added it
for the single case where a correct, well-formed request can still lose a race
(`uq_guest_access_tokens_live_per_reservation`, design Risks). It is narrowed to that one
constraint by name and re-raises everything else, so the table above remains the only thing
that decides what a *domain* error means.

`404` for a cross-tenant guest is not a convention here, it is the point: the alternative
turns the endpoint into an oracle telling a caller whether an id exists somewhere — about a
person's identity document.
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.guests.domain.exceptions import (
    GuestDocumentMissingError,
    GuestDomainError,
    GuestNotFoundError,
    GuestPortalUnauthorised,
    LegalRegistrationNotReadyError,
    ReservationNotFoundError,
)

_MAPPING: tuple[tuple[type[GuestDomainError], int, ErrorCode], ...] = (
    (GuestNotFoundError, 404, ErrorCode.NOT_FOUND),
    (ReservationNotFoundError, 404, ErrorCode.NOT_FOUND),
    (GuestDocumentMissingError, 404, ErrorCode.NOT_FOUND),
    (LegalRegistrationNotReadyError, 409, ErrorCode.CONFLICT),
    # The net, not the mechanism. Every portal route catches `GuestPortalUnauthorised`
    # itself, because the refusal has to be **charged** to the per-IP budget before it is
    # sent (task 6.1, constraint 2) and a handler cannot do that. But this table declares
    # itself exhaustive, and without this row the one exception whose escape would produce
    # what D5 forbids — a body other than the constant `404` — would fall through to
    # `500 "Unexpected guest error"`. The envelope produced here is byte-for-byte
    # `portal_router._NOT_FOUND`, since `str(GuestPortalUnauthorised())` is "Not found";
    # what it does not do is charge the throttle, which is why it must stay the net.
    (GuestPortalUnauthorised, 404, ErrorCode.NOT_FOUND),
)


def http_error_for(exc: GuestDomainError) -> tuple[int, ErrorCode]:
    for error_class, status, code in _MAPPING:
        if isinstance(exc, error_class):
            return status, code
    return 500, ErrorCode.INTERNAL_ERROR


#: The one constraint an ordinary, correct request can still trip, so the only one worth
#: translating rather than letting surface as a `500` (`guest-portal-api` design Risks).
_LIVE_TOKEN_CONSTRAINT = "uq_guest_access_tokens_live_per_reservation"


def _violated_constraint(exc: IntegrityError) -> str | None:
    """The constraint's **name**, from the driver, never from the message text.

    This is a security boundary, not a style preference. The first version of this handler
    matched `_LIVE_TOKEN_CONSTRAINT` as a substring of `str(exc.orig)`, and the security
    panel of section 4 broke it: asyncpg's message carries Postgres's `DETAIL` line, which
    interpolates the **offending row value** —

        duplicate key value violates unique constraint "uq_probe"
        DETAIL:  Key (x)=(uq_guest_access_tokens_live_per_reservation) already exists.

    — so any caller who could store that string in a column under a unique index (a
    property's `internal_code`, a reservation's `external_pms_id`, both operator-writable)
    could make an unrelated duplicate anywhere in the app answer `409 CONFLICT` with this
    module's "retry" message, for an operation that would never succeed. The constraint name
    is not a secret: it is in the migration and in this file.

    asyncpg exposes the real thing on the exception SQLAlchemy wrapped, so the match is on
    an identifier the database chose rather than on text an attacker can influence.
    """
    cause = getattr(exc.orig, "__cause__", None)
    return getattr(cause, "constraint_name", None)


def register_guest_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(GuestDomainError)
    async def _guest_error(_: Request, exc: GuestDomainError) -> JSONResponse:
        status, code = http_error_for(exc)
        message = str(exc) if status != 500 else "Unexpected guest error"
        return JSONResponse(status_code=status, content=error_envelope(code, message))

    @app.exception_handler(IntegrityError)
    async def _live_token_conflict(_: Request, exc: IntegrityError) -> JSONResponse:
        """Two operators minting a token for one stay at the same time (R1.5, Risks).

        The partial unique index is what makes "never two live tokens" true, and under a
        genuine race one of the two transactions loses it. That is a **conflict**, not a bug:
        the loser's whole transaction rolled back — the revoke-and-create of D14 is one
        transaction precisely so it leaves no half-revoked stay — so retrying mints cleanly.
        A `500` would tell the operator to report an incident for a situation they can simply
        repeat.

        Deliberately narrow: only this constraint is translated, and matched on the name the
        **driver** reports rather than on the message text — see `_violated_constraint` for
        the attack that distinction closes. A blanket `IntegrityError → 409` would hide real
        bugs: a null violation, or one of the two composite foreign keys this change added,
        which mean a caller tried to cross a tenant boundary and must never be told "try
        again".
        """
        if _violated_constraint(exc) != _LIVE_TOKEN_CONSTRAINT:
            raise exc
        return JSONResponse(
            status_code=409,
            content=error_envelope(
                ErrorCode.CONFLICT,
                "Another token was issued for this reservation at the same time. Retry.",
            ),
        )
