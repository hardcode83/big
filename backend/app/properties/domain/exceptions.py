class PropertyDomainError(Exception):
    """Base error for pure property-domain decisions."""


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
