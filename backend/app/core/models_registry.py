"""Imports every domain's ORM models, so the mapper registry is always complete.

Three separate places used to keep their own copy of this list — `alembic/env.py`,
`tests/conftest.py`, and (missing entirely) the application itself. That last gap
mattered: `tenant_scoped_classes()` in `app/core/db.py` derives the global tenant
filter (design D16) from `Base.registry.mappers` and memoises the result on first
use, so any model module not yet imported was simply absent from the net. The
filter looked complete in the test process, where conftest imports everything, and
silently covered fewer tables in the running app.

Import this module — never a hand-written list — wherever the full metadata is
needed. Adding a domain means adding one line here and nowhere else.
"""

import app.access.infrastructure.models  # noqa: F401
import app.auth.infrastructure.models  # noqa: F401
import app.cleaning.infrastructure.models  # noqa: F401
import app.guests.infrastructure.models  # noqa: F401
import app.maintenance.infrastructure.models  # noqa: F401
import app.messaging.infrastructure.models  # noqa: F401
import app.properties.infrastructure.models  # noqa: F401
import app.reservations.infrastructure.models  # noqa: F401
import app.tenants.infrastructure.models  # noqa: F401
import app.timeline.infrastructure.models  # noqa: F401

DOMAIN_MODEL_MODULES = (
    "app.access.infrastructure.models",
    "app.auth.infrastructure.models",
    "app.cleaning.infrastructure.models",
    "app.guests.infrastructure.models",
    "app.maintenance.infrastructure.models",
    "app.messaging.infrastructure.models",
    "app.properties.infrastructure.models",
    "app.reservations.infrastructure.models",
    "app.tenants.infrastructure.models",
    "app.timeline.infrastructure.models",
)
