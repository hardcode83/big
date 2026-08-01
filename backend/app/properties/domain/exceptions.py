class PropertyDomainError(Exception):
    """Base error for pure property-domain decisions."""


class AmbiguousPropertyExternalIdError(PropertyDomainError):
    """Two properties of one tenant share a `pms_external_id` (design D16).

    Exists so the port can keep its `Property | None` contract while still failing
    closed: the ambiguity is a domain outcome the PMS sync has to report per row (R3.4),
    and letting SQLAlchemy's `MultipleResultsFound` escape instead would force
    `application/` to catch an infrastructure exception — which the dependency rule of
    `steering/backend-architecture.md` forbids and `tests/test_layering.py` enforces.

    Not resolved by a tie-break the way `Guest.find_by_email` is (design D8): two guests
    with one address are the same person seen twice, while two properties with one
    external id are two different flats, and picking either would attach a booking — and
    a guest — to the wrong home.
    """

    def __init__(self, message: str = "Ambiguous pms_external_id", **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class InvalidStateTransitionError(PropertyDomainError):
    def __init__(self, message: str = "Invalid state transition", **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class NoOperationalStateChangeError(PropertyDomainError):
    def __init__(self, message: str = "The requested operation does not change operational state", **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class InvalidTransitionInputError(PropertyDomainError):
    def __init__(self, message: str, **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class TransitionScopeMismatchError(PropertyDomainError):
    def __init__(self, message: str = "Transition context does not match property scope", **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class IncompatibleTransitionContextError(PropertyDomainError):
    def __init__(self, message: str, **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class TransitionEvidenceError(PropertyDomainError):
    def __init__(self, message: str = "Unable to construct transition evidence", **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)
