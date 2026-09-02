"""Errors of the platform module (`platform-admin-api` R1.4, R2.3, design D2).

`TenantAlreadyExistsError` is re-exported from `app.tenants.domain.exceptions` rather
than duplicated or moved here: section 1 added it there because `TenantRepository.add`
is the only place that raises it, and the handler wired up by section 4 imports it from
this module so the rest of the platform module has a single canonical location.
"""

from app.tenants.domain.exceptions import TenantAlreadyExistsError

__all__ = ["PlatformDomainError", "TenantAlreadyExistsError"]


class PlatformDomainError(Exception):
    """Base error for the platform module.

    Future exceptions raised by use cases in `app/platform/application/` are expected to
    inherit from this class, so a generic handler in `register_platform_error_handlers`
    can catch them. Section 4 only introduces `TenantAlreadyExistsError` (already mapped
    explicitly) — the base class is in place for later additions such as
    `TenantNotActiveError` (section 3).
    """
