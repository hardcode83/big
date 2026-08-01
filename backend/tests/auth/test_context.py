"""RequestContext is the only carrier of the effective tenant (R4.1, design D6)."""

import dataclasses
import uuid

import pytest

from app.auth.domain.context import RequestContext
from app.auth.domain.enums import UserRole


def _context(**overrides) -> RequestContext:
    values = {
        "user_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "role": UserRole.PROPERTY_MANAGER,
    }
    values.update(overrides)
    return RequestContext(**values)


def test_context_is_immutable() -> None:
    context = _context()

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.tenant_id = uuid.uuid4()  # type: ignore[misc]


def test_context_rejects_non_uuid_identifiers() -> None:
    with pytest.raises(ValueError):
        _context(user_id="not-a-uuid")

    with pytest.raises(ValueError):
        _context(tenant_id="not-a-uuid")


def test_context_rejects_a_role_outside_the_enum() -> None:
    with pytest.raises(ValueError):
        _context(role="ADMIN")


def test_context_keeps_what_it_was_given() -> None:
    user_id, tenant_id = uuid.uuid4(), uuid.uuid4()

    context = RequestContext(user_id=user_id, tenant_id=tenant_id, role=UserRole.CLEANER)

    assert (context.user_id, context.tenant_id, context.role) == (
        user_id,
        tenant_id,
        UserRole.CLEANER,
    )
