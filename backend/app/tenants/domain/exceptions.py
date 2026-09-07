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


class TenantAlreadyExistsError(TenantDomainError):
    """A tenant with this name is already persisted (R-2).

    Raised by `TenantRepository.add` when the unique constraint `uq_tenants_name` (added by
    this change's migration `936fef5a01b1_tenants_name_unique.py`) is violated. The
    `IntegrityError` is translated by substring-matching the constraint's name on
    `error.orig` — a sufficient proxy here, because `uq_tenants_name` is the only unique
    constraint this change adds on `tenants` and the only one the migration is allowed to
    add. Any other `IntegrityError` re-raises unmapped, so a future column with its own
    `UNIQUE` reaches the router as `500` rather than a `409` it cannot justify.
    """
