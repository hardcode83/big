"""The errors an adapter raises when a tenancy precondition is broken.

One class per precondition, and one class system-wide for each: an
`except CrossTenantWriteError` written against the guests adapter must also catch the
reservations one, and two identically named classes in different modules silently break
that.

Neither is an `AppError`: reaching one means a use case mixed up two tenants, or wired
an unscoped read behind something that marks the session. Both are programming errors,
not something a client can provoke into a 4xx. They must surface as a 500 and be fixed,
never be handled.
"""


class CrossTenantWriteError(RuntimeError):
    def __init__(self, *, entity: str, entity_tenant_id: object, acting_tenant_id: object) -> None:
        super().__init__(
            f"Refusing to write {entity} of tenant {entity_tenant_id} "
            f"while acting for {acting_tenant_id}"
        )


class TenantMarkedSessionError(RuntimeError):
    """An unscoped read was handed a session that already carries a tenant marker.

    Deliberately not a `ValueError`: `bind_session_to_tenant` raises those for its own two
    refusals, and a `pytest.raises(ValueError)` around an unscoped read would pass on
    either.
    """

    def __init__(self, *, read: str, tenant_id: object) -> None:
        super().__init__(
            f"{read} must run on a session that is NOT marked with a tenant, but this one "
            f"is bound to {tenant_id}. The global filter of app/core/db.py would scope the "
            "statement, so the read would silently answer for one tenant instead of the "
            "whole installation. Run it before anything binds the session, or give it a "
            "session that was never marked."
        )
