"""Errors the PMS port may raise (design D5).

Before `channex-staging-adapter` the port had **no** error contract: `MockPMSAdapter`
never raises, and `app/integrations/api/errors.py` only covers the CSV file failures. That
was fine while the only implementation was a mock, and stops being fine the moment a real
provider can be unreachable.

Lives in `domain/` rather than beside the Channex adapter so that a caller — today
`cli/pms_sync.py`, tomorrow the Celery job — can catch it without importing
`infrastructure/`, which is the dependency rule `tests/test_layering.py` enforces.
"""

import uuid


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


class PMSMessagingUnsupportedError(RuntimeError):
    """This property's provider has no messaging API, so no `PMSMessagingPort` can be built.

    Raised by `PMSAdapterFactory.messaging_for`, answering the question ADR 0006
    decision 7 leaves open (how the factory composes with the port split of decision 3). An
    exception rather than a `None` return, for a measured reason: **CI runs no type checker**
    (`app/core/db.py` says so outright), so a `PMSMessagingPort | None` would be verified by
    nothing and would surface as `AttributeError: 'NoneType' object has no attribute
    'send_message'` at the worst possible moment.

    `PMSAdapterFactory.supports_messaging` is the way to ask when the answer should not be an
    exception, and is pure — reading the provider and never the credentials — so that planning
    work decrypts nothing, because decrypting is an audited act (R4.2).

    Not a `PmsUnavailableError`: the provider is perfectly reachable. The capability does not
    exist, which is a permanent property of the provider and not a transient failure, and the
    two demand opposite responses — one is retried, the other never is.
    """


class MissingPmsCredentialError(RuntimeError):
    """A property names a provider whose credentials are not stored.

    Loud on purpose, and it must never degrade to the mock. `specs/reservations.md` already
    fixed that reasoning for `CHANNEX_API_KEY`: a silent fallback would report "created 0",
    which is indistinguishable from a PMS that genuinely had nothing.

    The message is composed **here**, from the three identifiers a person needs, rather than by
    each raiser. An earlier draft was a bare `RuntimeError` whose docstring promised it carried
    "never any fragment of a stored secret" — a guarantee nothing enforced. R3.5 forbids a
    decrypted credential in any error message.

    **And the first attempt at enforcing it did not.** Its parameters were typed `object` and
    interpolated with `str()`, so passing the credential row where the code wanted its scope —
    the plausible slip, since `scope` is a field *of* that row — rendered every field of a frozen
    dataclass, refresh token included. The security panel reproduced exactly that. So the
    constructor now **rejects** what it cannot safely render: scalars only, checked at runtime,
    because a type annotation is enforced by nothing here (CI runs no type checker).

    Callers pass `provider.value` / `scope.value` for enums. That is deliberate friction: making
    the caller unwrap is what keeps a whole entity from arriving.
    """

    def __init__(self, *, property_id: uuid.UUID, provider: str, scope: str) -> None:
        for name, value in (("provider", provider), ("scope", scope)):
            # Not `isinstance(value, str)` alone: a `str`-mixin enum member IS a str, and its
            # `str()` is version-dependent ("PMSProvider.BEDS24" on some, "BEDS24" on others).
            # Requiring the exact type makes the rendered message stable and the caller explicit.
            if type(value) is not str:
                raise TypeError(
                    f"{name} must be a plain str (pass .value for an enum), "
                    f"got {type(value).__name__}"
                )
        if not isinstance(property_id, uuid.UUID):
            raise TypeError(
                f"property_id must be a UUID, got {type(property_id).__name__}"
            )

        self.property_id = property_id
        self.provider = provider
        self.scope = scope
        super().__init__(
            f"no {scope} credential stored for provider {provider} "
            f"of property {property_id}"
        )
