"""The single source of truth for the `code` of the PRD §23 error envelope.

Every code that can reach a client goes through here: the `code` attributes of
`AppError` subclasses, the `_MAPPING` tables of `app/{auth,properties,reservations,
tenants}/api/errors.py`, the literals of `app/integrations/api/errors.py` and
`_HTTP_STATUS_CODES`.

**A module added to that list must also be added to the guard**, which reflects over the
mappings by import in `tests/test_openapi_contract.py`. `properties` shipped in this
enumeration's blind spot once already: the router existed, emitted codes, and the guard
never looked at it, so a bare literal there would have reached the contract unchallenged.

It exists because `api-contract-export` publishes these values as an `enum` in the
OpenAPI contract (design D11), and a published enum that omits a code the backend
actually returns is worse than no enum at all: the frontend's exhaustive switch would
be exhaustive over the wrong set, with the compiler vouching for it. Before this
registry the codes lived in six places, and the two that a reflection over
`AppError` would have missed — CONFLICT and PAYLOAD_TOO_LARGE — are returned today.

`StrEnum` and not `Enum`: members serialise exactly like the string literals they
replaced, so `error_envelope()` and every existing test keep working untouched.

`tests/test_openapi_contract.py` fails if any of those six places grows a code that
is not a member here.
"""

from enum import StrEnum


class ErrorCode(StrEnum):
    # Generic — `AppError.code` default and the fallback of the domain mappers for an
    # exception nobody mapped (which is a bug, not a client problem).
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # Raised by StarletteHTTPException for a status without a code of its own.
    HTTP_ERROR = "HTTP_ERROR"

    # Request-shaped failures.
    VALIDATION_ERROR = "VALIDATION_ERROR"
    CONFLICT = "CONFLICT"
    PAYLOAD_TOO_LARGE = "PAYLOAD_TOO_LARGE"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"

    # Authentication and authorisation.
    INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
    INVALID_TOKEN = "INVALID_TOKEN"
    FORBIDDEN = "FORBIDDEN"
    RATE_LIMITED = "RATE_LIMITED"
    # The account authenticated fine but still carries a temporary password
    # (`auth-account-recovery` R5.4). Distinct from `FORBIDDEN` on purpose: this one is
    # actionable and self-service — the frontend can send the user straight to the
    # change-password screen instead of showing "you are not allowed", which would be both
    # wrong and a dead end.
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"

    # Absence. Also the answer for a resource of another tenant, which must not reveal
    # that it exists (`steering/security.md` rule 1).
    NOT_FOUND = "NOT_FOUND"

    # A dependency of ours failed, not the caller (`cleaning-photos-storage` R1.5: the file
    # store refused the write). Distinct from `INTERNAL_ERROR` on purpose — the frontend can
    # tell "retrying may work" from "this is our bug", and the two are different messages to
    # show a cleaner standing in a flat with a photo she cannot upload.
    BAD_GATEWAY = "BAD_GATEWAY"
