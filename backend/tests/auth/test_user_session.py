"""UserSession invariants behind refresh rotation and reuse detection (R2.1, R2.2)."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.auth.domain.entities import UserSession
from app.auth.domain.enums import SessionRevokedReason

NOW = datetime(2026, 7, 30, 12, 0, tzinfo=UTC)


def _session(**overrides) -> UserSession:
    values = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "family_id": uuid.uuid4(),
        "expires_at": NOW + timedelta(days=7),
    }
    values.update(overrides)
    return UserSession(**values)


def test_a_fresh_session_is_usable() -> None:
    assert _session().is_usable(NOW) is True


def test_an_already_used_session_is_not_usable() -> None:
    # This is exactly the reuse signal of R2.2.
    assert _session(used_at=NOW - timedelta(minutes=1)).is_usable(NOW) is False


def test_a_revoked_session_is_not_usable() -> None:
    session = _session(
        revoked_at=NOW - timedelta(minutes=1),
        revoked_reason=SessionRevokedReason.LOGOUT,
    )

    assert session.is_usable(NOW) is False


def test_an_expired_session_is_not_usable() -> None:
    assert _session(expires_at=NOW - timedelta(seconds=1)).is_usable(NOW) is False


def test_a_session_expiring_exactly_now_is_not_usable() -> None:
    assert _session(expires_at=NOW).is_usable(NOW) is False


def test_expires_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError):
        _session(expires_at=datetime(2026, 8, 6, 12, 0))


def test_is_usable_requires_an_aware_reference_instant() -> None:
    with pytest.raises(ValueError):
        _session().is_usable(datetime(2026, 7, 30, 12, 0))


def test_a_root_session_has_no_parent() -> None:
    assert _session().parent_id is None


def test_a_rotated_child_keeps_the_family_and_points_at_its_parent() -> None:
    parent = _session()

    child = parent.rotate(new_id=uuid.uuid4(), expires_at=NOW + timedelta(days=7), now=NOW)

    assert child.family_id == parent.family_id
    assert child.parent_id == parent.id
    assert child.tenant_id == parent.tenant_id
    assert child.user_id == parent.user_id
    assert parent.used_at == NOW
    assert child.is_usable(NOW) is True


def test_rotating_a_session_twice_is_refused() -> None:
    session = _session()
    session.rotate(new_id=uuid.uuid4(), expires_at=NOW + timedelta(days=7), now=NOW)

    with pytest.raises(ValueError):
        session.rotate(new_id=uuid.uuid4(), expires_at=NOW + timedelta(days=7), now=NOW)


def test_revoking_records_the_reason() -> None:
    session = _session()

    session.revoke(SessionRevokedReason.REUSE_DETECTED, now=NOW)

    assert session.revoked_at == NOW
    assert session.revoked_reason is SessionRevokedReason.REUSE_DETECTED


def test_revoking_twice_keeps_the_first_reason() -> None:
    session = _session()
    session.revoke(SessionRevokedReason.LOGOUT, now=NOW)

    session.revoke(SessionRevokedReason.REUSE_DETECTED, now=NOW + timedelta(minutes=1))

    assert session.revoked_at == NOW
    assert session.revoked_reason is SessionRevokedReason.LOGOUT
