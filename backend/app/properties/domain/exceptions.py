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


class PropertyNotFoundError(PropertyDomainError):
    """No property with that id inside the acting tenant (`properties-crud` R1.6).

    Deliberately does not distinguish "does not exist" from "belongs to another tenant":
    the API answers `404` with an identical body for both, so a caller cannot use the
    difference to enumerate a neighbour's portfolio. `reservations` has its own error of
    the same name for the property it fails to resolve; this one belongs to the endpoints
    that address a property directly.
    """

    def __init__(self, message: str = "Property not found", **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class DuplicateInternalCodeError(PropertyDomainError):
    """`internal_code` already used by another property of the tenant (R2.5).

    Raised from the adapter by translating the violation of
    `uq_properties_tenant_id_internal_code` **by constraint name**, never from a prior
    SELECT: two concurrent creations would both pass a pre-check and one would surface as
    a `500`. Same reasoning `user-management` recorded for `uq_users_lower_email`.
    """

    def __init__(self, message: str = "internal_code already in use", **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class DuplicatePmsExternalIdError(PropertyDomainError):
    """`pms_external_id` already claimed by another property of the tenant (R2.7).

    Two properties sharing one external id are two different homes, so the PMS sync is
    required to fail rather than pick one (`specs/reservations.md`). Enforced by the
    partial unique index `uq_properties_tenant_id_pms_external_id` and translated here,
    which is what makes it race-free — the write path is what could otherwise create the
    state the sync must reject.
    """

    def __init__(self, message: str = "pms_external_id already in use", **details: object) -> None:
        self.details = details
        for key, value in details.items():
            setattr(self, key, value)
        super().__init__(message)


class PropertyValidationError(PropertyDomainError):
    """A property value is rejected by a domain rule rather than by request shape (R2)."""

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
