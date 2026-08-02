"""Errors of the tenants domain."""


class TenantDomainError(Exception):
    """Base error for the tenants domain."""


class TenantNotFoundError(TenantDomainError):
    """The tenant asked for is not the one the token names (R7.1, design D12).

    Answers `404`, exactly like an id that does not exist: a caller must not be able to tell
    that another tenant exists by asking for it. Reached before any query, since the check is a
    comparison against the token's tenant.
    """


class TenantValidationError(TenantDomainError):
    """A configuration value is outside what the schema or the domain accepts (R5.5)."""
