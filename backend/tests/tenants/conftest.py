"""Fixtures for the tenant API tests.

Re-registers the fixtures of `tests/auth/conftest.py` for this package rather than re-seeding
them: two tenants with a user per role is exactly what the authorisation matrix (R7.2) and the
isolation tests (R7.9) need, and a second copy would let the two drift. Same approach
`tests/reservations/conftest.py` takes, and for the same reason.
"""

from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    api,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)
