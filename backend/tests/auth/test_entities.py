import uuid
from datetime import datetime, timezone

from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole, UserStatus


def test_user_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    user = User(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Manager",
        email="manager@example.com",
        password_hash="hashed",
        role=UserRole.PROPERTY_MANAGER,
        created_at=now,
        updated_at=now,
    )

    assert user.status == UserStatus.ACTIVE
    assert user.preferred_language == "es"
    assert user.phone is None
    assert user.last_login_at is None
