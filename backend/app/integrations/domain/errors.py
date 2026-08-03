"""Errors the PMS port may raise (design D5).

Before `channex-staging-adapter` the port had **no** error contract: `MockPMSAdapter`
never raises, and `app/integrations/api/errors.py` only covers the CSV file failures. That
was fine while the only implementation was a mock, and stops being fine the moment a real
provider can be unreachable.

Lives in `domain/` rather than beside the Channex adapter so that a caller — today
`cli/pms_sync.py`, tomorrow the Celery job — can catch it without importing
`infrastructure/`, which is the dependency rule `tests/test_layering.py` enforces.
"""


class PmsUnavailableError(RuntimeError):
    """The PMS could not answer: transport failure, auth rejection, throttling or 5xx.

    Deliberately **one** error rather than a hierarchy per status code. From the caller's
    side there is a single decision to make — this sync did not happen, report it and exit
    non-zero — and a taxonomy nobody branches on is the "excepción por código HTTP" that
    `steering/backend-architecture.md` warns about. The provider's own status lands in the
    message, which is where an operator reads it.

    It is NOT raised for "the provider has no such reservation": that is `None` from
    `get_reservation`, because an absent id is an answer, not a failure.
    """
