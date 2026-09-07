"""Errors of the platform module (`platform-admin-api` R1.4, R2.3, R3.3, design D2).

`TenantAlreadyExistsError` is re-exported from `app.tenants.domain.exceptions` rather
than duplicated or moved here: section 1 added it there because `TenantRepository.add`
is the only place that raises it, and the handler wired up by section 4 imports it from
this module so the rest of the platform module has a single canonical location.

`TenantNotActiveError` is defined here because `CreateUserInTenantUseCase` (section 3) is
its only raiser — it is the use case's response to a tenant that is missing or that is not
in `TenantStatus.ACTIVE`. The error carries the same 404 response as a non-existent tenant
(R3.3): the caller must not be able to tell the two apart, and the error handler in section
4 maps both to `ErrorCode.NOT_FOUND` with the same message.
"""

from app.tenants.domain.exceptions import TenantAlreadyExistsError

__all__ = [
    "PlatformDomainError",
    "TenantAlreadyExistsError",
    "TenantNotActiveError",
]


class PlatformDomainError(Exception):
    """Base error for the platform module.

    Future exceptions raised by use cases in `app/platform/application/` are expected to
    inherit from this class, so a generic handler in `register_platform_error_handlers`
    can catch them. Section 3 adds `TenantNotActiveError` (mapped explicitly to 404 in
    section 4); the base class is in place for later additions.
    """


class TenantNotActiveError(PlatformDomainError):
    """The tenant in the path does not exist OR is not ACTIVE (R3.3).

    The two cases are not distinguished on purpose: section 4's error handler turns both
    into the same `404 NOT_FOUND` with the same message. A caller that learns whether the
    tenant exists but is suspended has learned something they should not — e.g. that the
    id is valid and only its state blocks them, which would let a probe map the id space.

    Inherits from `PlatformDomainError` so the handler the section wires up can match the
    whole family with one clause when that becomes useful.
    """

    def __init__(self, tenant_id: object | None = None) -> None:
        # `tenant_id` is accepted only so the error message can be informative in logs;
        # it is intentionally NOT exposed on the response.
        super().__init__("Tenant does not exist")
        self.tenant_id = tenant_id
