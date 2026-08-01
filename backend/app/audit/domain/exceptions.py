"""Errors of the audit domain.

`AuditContractError` is a programming error, not something a client can provoke: reaching
it means a caller tried to record a rule-3 value, a field twice, or a value JSONB cannot
store. It must surface as a 500 and be fixed, never be handled into a 4xx — which is why
it is not an `AppError`. Same reasoning as `app/core/tenancy.py::CrossTenantWriteError`.
"""


class AuditDomainError(Exception):
    """Base for audit domain errors."""


class AuditContractError(AuditDomainError):
    """A change set was built in a way rule 11 of steering/security.md forbids."""
