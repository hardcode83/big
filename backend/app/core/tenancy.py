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


class TenantUnmarkedSessionError(RuntimeError):
    """A write whose only tenant predicate comes from the marker got an unmarked session.

    The mirror of `TenantMarkedSessionError`, added by `demo-user`. The asymmetry between the
    two is worth stating: an unscoped read on a marked session answers for **less** than it
    should, which is usually a wrong answer; a marker-scoped write on an unmarked session
    touches **more** than it should, which is data loss across every tenant in the database.
    """

    def __init__(self, *, write: str, tenant_id: object) -> None:
        super().__init__(
            f"{write} must run on a session bound to tenant {tenant_id}, but this one carries "
            "no marker. Its statements take their tenant predicate from the global filter of "
            "app/core/db.py, so unmarked they would apply to EVERY tenant. Call "
            "bind_session_to_tenant first."
        )


class TenantMismatchedSessionError(RuntimeError):
    """A marker-scoped write was asked to act for one tenant on a session bound to another."""

    def __init__(self, *, write: str, marked: object, requested: object) -> None:
        super().__init__(
            f"{write} was asked to act for tenant {requested} on a session bound to {marked}. "
            "The statements that rely on the global filter would hit the marked tenant while "
            "any statement carrying its own explicit clause would hit the requested one, so the "
            "write would be split across two tenants."
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
