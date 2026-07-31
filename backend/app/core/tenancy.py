"""The one error every adapter raises when a write would cross a tenant boundary.

One class, not one per module: an `except CrossTenantWriteError` written against the
guests adapter must also catch the reservations one, and two identically named classes
in different modules silently break that.

Not an `AppError`: reaching it means a use case mixed up two tenants, which is a
programming error, not something a client can provoke into a 4xx. It must surface as a
500 and be fixed, never be handled.
"""


class CrossTenantWriteError(RuntimeError):
    def __init__(self, *, entity: str, entity_tenant_id: object, acting_tenant_id: object) -> None:
        super().__init__(
            f"Refusing to write {entity} of tenant {entity_tenant_id} "
            f"while acting for {acting_tenant_id}"
        )
