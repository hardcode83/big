"""The port of the audit log (R6.4, design D2).

Deliberately one method. `audit_logs` is append-only by definition (§7.25 declares
`created_at` and no `updated_at`), so a port with `save`, `delete` or an update would be
offering an operation the domain forbids — R6.6 is enforced by the shape of this interface,
not only by which routes exist.

Reads are not here either: nobody consumes the audit trail yet. When a change needs to list
it, it adds the query it needs rather than inheriting a speculative one.
"""

import uuid
from typing import Protocol

from app.audit.domain.entities import AuditLog


class AuditLogRepository(Protocol):
    async def add(self, tenant_id: uuid.UUID, entry: AuditLog) -> None:
        """Append one entry; refuses an entry belonging to another tenant.

        `tenant_id` is the ACTING tenant, from `RequestContext` — the same contract every
        other port in this codebase follows. No `commit`: the transactional boundary is the
        use case, so the mutation and its audit row live or die together (R6.4).
        """
        ...
