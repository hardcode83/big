"""The single source of truth for the `code` of the PRD §23 error envelope.

Every code that can reach a client goes through here: the `code` attributes of
`AppError` subclasses, the `_MAPPING` tables of `app/{auth,reservations,tenants}/api/
errors.py`, the literals of `app/integrations/api/errors.py` and `_HTTP_STATUS_CODES`.

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

    # Absence. Also the answer for a resource of another tenant, which must not reveal
    # that it exists (`steering/security.md` rule 1).
    NOT_FOUND = "NOT_FOUND"
