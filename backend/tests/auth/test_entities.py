import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.auth.domain.entities import PasswordResetToken, User
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.exceptions import SelfRoleChangeError, UnassignableRoleError


def _user(**overrides) -> User:
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "name": "Ana",
        "email": "ana@example.com",
        "password_hash": "hashed",
        "role": UserRole.CLEANER,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return User(**values)


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


# --- self-protection (user-management R3.5, design D5/D19) --------------------------


def test_an_actor_cannot_change_their_own_role() -> None:
    """R3.5: a self-demotion leaves the tenant with nobody who can administer it."""
    user = _user(role=UserRole.TENANT_OWNER)

    with pytest.raises(SelfRoleChangeError):
        user.change_role(UserRole.CLEANER, actor_user_id=user.id)

    assert user.role is UserRole.TENANT_OWNER


def test_an_actor_cannot_change_their_own_status() -> None:
    user = _user(role=UserRole.TENANT_OWNER)

    with pytest.raises(SelfRoleChangeError):
        user.change_status(UserStatus.INACTIVE, actor_user_id=user.id)

    assert user.status is UserStatus.ACTIVE


def test_an_actor_cannot_deactivate_themselves() -> None:
    """`DELETE /users/{id}` on oneself is refused too — it is a status change (design D19)."""
    user = _user(role=UserRole.TENANT_OWNER)

    with pytest.raises(SelfRoleChangeError):
        user.deactivate(actor_user_id=user.id)

    assert user.status is UserStatus.ACTIVE


def test_another_actor_can_change_the_role() -> None:
    user = _user(role=UserRole.CLEANER)

    changed = user.change_role(UserRole.TECHNICIAN, actor_user_id=uuid.uuid4())

    assert changed is True
    assert user.role is UserRole.TECHNICIAN


def test_changing_the_role_to_the_same_value_changes_nothing(  # design D15
) -> None:
    """Reports "no change" so the caller writes neither a row nor an audit entry."""
    user = _user(role=UserRole.CLEANER)

    changed = user.change_role(UserRole.CLEANER, actor_user_id=uuid.uuid4())

    assert changed is False


# --- SUPER_ADMIN is not assignable through the API (R1.6) --------------------------


def test_super_admin_cannot_be_granted_by_a_role_change() -> None:
    user = _user(role=UserRole.PROPERTY_MANAGER)

    with pytest.raises(UnassignableRoleError):
        user.change_role(UserRole.SUPER_ADMIN, actor_user_id=uuid.uuid4())

    assert user.role is UserRole.PROPERTY_MANAGER


def test_super_admin_cannot_be_granted_at_creation() -> None:
    with pytest.raises(UnassignableRoleError):
        User.create(
            tenant_id=uuid.uuid4(),
            name="Root",
            email="root@example.com",
            password_hash="hashed",
            role=UserRole.SUPER_ADMIN,
            now=datetime.now(timezone.utc),
        )


def test_a_super_admin_row_that_already_exists_can_still_be_demoted() -> None:
    """The guard is on GRANTING the role, not on holding it.

    The bootstrap cannot create one, so today none exists — but if a future
    `saas-cross-tenant` does, this capability must not be the thing that traps it.
    """
    user = _user(role=UserRole.SUPER_ADMIN)

    changed = user.change_role(UserRole.PROPERTY_MANAGER, actor_user_id=uuid.uuid4())

    assert changed is True
    assert user.role is UserRole.PROPERTY_MANAGER


# --- profile and password ----------------------------------------------------------


def test_update_profile_applies_only_what_it_is_given() -> None:
    user = _user(name="Ana", phone=None, preferred_language="es")

    changed = user.update_profile(name="Ana Ruiz", phone="+34600000000")

    assert changed == {"name", "phone"}
    assert (user.name, user.phone, user.preferred_language) == ("Ana Ruiz", "+34600000000", "es")


def test_update_profile_reports_nothing_when_the_values_are_identical() -> None:
    user = _user(name="Ana")

    assert user.update_profile(name="Ana") == set()


def test_update_profile_can_clear_an_optional_field() -> None:
    user = _user(phone="+34600000000")

    assert user.update_profile(phone=None) == {"phone"}
    assert user.phone is None


def test_set_password_hash_replaces_it() -> None:
    user = _user(password_hash="old")

    user.set_password_hash("new", temporary=False)

    assert user.password_hash == "new"


# --- the temporary-password flag (`auth-account-recovery` R5.1-R5.3, design D5) -----


def test_a_new_user_does_not_have_to_change_its_password_by_default() -> None:
    """The bootstrap path chooses its own passwords, so the default must stay False."""
    assert _user().must_change_password is False


def test_setting_a_temporary_hash_raises_the_flag() -> None:
    user = _user()

    user.set_password_hash("temp-hash", temporary=True)

    assert user.password_hash == "temp-hash"
    assert user.must_change_password is True


def test_setting_a_chosen_hash_clears_the_flag() -> None:
    """R5.3: completing a change or a recovery is what takes the account out of the state."""
    user = _user(must_change_password=True)

    user.set_password_hash("chosen-hash", temporary=False)

    assert user.must_change_password is False


def test_the_hash_and_the_flag_cannot_be_written_apart() -> None:
    """Design D5: one method owns both fields, so no path replaces a password without
    deciding whether it is temporary. `temporary` is keyword-only and has no default."""
    user = _user()

    with pytest.raises(TypeError):
        user.set_password_hash("new")  # type: ignore[call-arg]


def test_create_can_start_an_account_owing_a_password_change() -> None:
    """R5.2: administrative creation hands out a temporary password."""
    now = datetime.now(timezone.utc)

    user = User.create(
        tenant_id=uuid.uuid4(),
        name="Ana",
        email="ana@example.com",
        password_hash="hashed",
        role=UserRole.CLEANER,
        now=now,
        must_change_password=True,
    )

    assert user.must_change_password is True


def test_create_starts_active_with_the_given_role() -> None:
    now = datetime.now(timezone.utc)

    user = User.create(
        tenant_id=uuid.uuid4(),
        name="Ana",
        email="ana@example.com",
        password_hash="hashed",
        role=UserRole.CLEANER,
        now=now,
        phone="+34600000000",
        preferred_language="en",
    )

    assert user.status is UserStatus.ACTIVE
    assert user.role is UserRole.CLEANER
    assert (user.created_at, user.updated_at) == (now, now)
    assert user.last_login_at is None
    assert isinstance(user.id, uuid.UUID)


# --- type guards on the mutators (QA panel of sections 2-6) ------------------------
#
# These have a DIRECT domain test, not only the API test that exercises them through the
# request schema: a regression in the domain would otherwise only be caught if the schema
# layer failed at the same time — or never, for a caller that skips the schema (a CLI, a bulk
# import, a future use case).


def test_change_role_refuses_anything_that_is_not_a_role() -> None:
    """`AttributeError` is not an `AuthDomainError`, so it would surface as an unmapped 500."""
    user = _user(role=UserRole.CLEANER)

    for value in (None, "TECHNICIAN", 3, UserStatus.ACTIVE):
        with pytest.raises(ValueError):
            user.change_role(value, actor_user_id=uuid.uuid4())  # type: ignore[arg-type]

    assert user.role is UserRole.CLEANER


def test_change_status_refuses_anything_that_is_not_a_status() -> None:
    user = _user()

    for value in (None, "ACTIVE", 1, UserRole.CLEANER):
        with pytest.raises(ValueError):
            user.change_status(value, actor_user_id=uuid.uuid4())  # type: ignore[arg-type]

    assert user.status is UserStatus.ACTIVE


@pytest.mark.parametrize("field", ["name", "preferred_language"])
def test_update_profile_refuses_a_none_for_a_non_nullable_field(field: str) -> None:
    """Only `phone` is nullable in `users`; a `None` elsewhere would become the text "None"."""
    user = _user(name="Ana", preferred_language="es")

    with pytest.raises(ValueError):
        user.update_profile(**{field: None})  # type: ignore[arg-type]

    assert getattr(user, field) is not None


# --- email is the login identity, and it has a method like every other field --------


def test_changing_the_email_reports_the_change() -> None:
    user = _user(email="old@example.com")

    assert user.change_email("new@example.com") is True
    assert user.email == "new@example.com"


def test_changing_the_email_to_the_same_value_reports_nothing() -> None:
    """Design D15: the caller writes neither a row nor an audit entry."""
    user = _user(email="same@example.com")

    assert user.change_email("same@example.com") is False


@pytest.mark.parametrize("value", ["", "   "])
def test_the_email_cannot_be_blanked(value: str) -> None:
    user = _user(email="ana@example.com")

    with pytest.raises(ValueError):
        user.change_email(value)

    assert user.email == "ana@example.com"


@pytest.mark.parametrize(
    "value", ["  new@example.com", "NEW@example.com", "New@Example.com  "]
)
def test_the_entity_normalises_the_email_itself(value: str) -> None:
    """ADR 0005 / design D19, and symmetric with `Tenant.update()`'s `_require_email`.

    The first version of `change_email` REJECTED an unnormalised address and justified it with
    an import cycle that does not exist. Normalising here is what makes the entity guarantee
    the invariant instead of demanding it from every caller — and a caller that forgets is
    exactly how two spellings of one identity end up in the database, with the login lookup
    comparing by plain equality against the normalised form.
    """
    user = _user(email="old@example.com")

    assert user.change_email(value) is True
    assert user.email == "new@example.com"


def test_an_unnormalised_form_of_the_current_address_is_not_a_change() -> None:
    """The other half: `ANA@Example.com` is the address it already has, so nothing is written."""
    user = _user(email="ana@example.com")

    assert user.change_email("  ANA@Example.COM  ") is False
    assert user.email == "ana@example.com"


# Fields legitimately fixed after creation, each with the reason it cannot be patched:
#   id, tenant_id  — identity; a repository able to move a row between tenants defeats the
#                    isolation rule (R7.8)
#   created_at     — history
#   updated_at     — owned by the database (`server_default`/`onupdate`)
#   last_login_at  — owned by `touch_last_login`, deliberately narrow (auth-tenancy design D5)
IMMUTABLE_AFTER_CREATION = frozenset(
    {"id", "tenant_id", "created_at", "updated_at", "last_login_at"}
)

# Which method owns each mutable field. The mapping is asserted to be EXHAUSTIVE below.
FIELD_OWNERS = {
    "email": "change_email",
    "role": "change_role",
    "status": "change_status",
    "password_hash": "set_password_hash",
    # Same owner as `password_hash`, and that IS the design (`auth-account-recovery` D5):
    # one method writes both, so the flag cannot drift away from the hash it describes.
    "must_change_password": "set_password_hash",
    "name": "update_profile",
    "phone": "update_profile",
    "preferred_language": "update_profile",
}


def test_every_mutable_field_of_the_user_has_a_method_that_owns_it() -> None:
    """The rule the architecture review invoked, pinned so it guards the NEXT field too.

    `steering/backend-architecture.md`: "No entidades con setters públicos arbitrarios —
    mutación solo vía métodos que protegen invariantes". `email` was the one field the use case
    assigned directly.

    The set under test is **derived from `User.__dataclass_fields__`**, not hand-written: the
    first version of this test iterated a literal dict and only checked that each name existed,
    so a new mutable field added without a method — `must_change_password`, say, which design
    D10 already anticipates — would have kept it green. That vacuity was caught by the
    re-review of the architecture panel, and it is the whole point of the assertion below.
    """
    mutable = set(User.__dataclass_fields__) - IMMUTABLE_AFTER_CREATION
    methods = {name for name in dir(User) if not name.startswith("_")}

    # Exhaustive: a field with no entry here fails, which is what guards the next one added.
    assert mutable == set(FIELD_OWNERS), (
        f"fields with no method that owns their mutation: {sorted(mutable - set(FIELD_OWNERS))}; "
        f"stale entries: {sorted(set(FIELD_OWNERS) - mutable)}"
    )
    for field, method in FIELD_OWNERS.items():
        assert method in methods, f"{field} names {method}, which does not exist on User"


def test_the_immutable_list_only_names_real_fields() -> None:
    """Stops a renamed field from silently becoming "immutable" and escaping the check above."""
    assert IMMUTABLE_AFTER_CREATION <= set(User.__dataclass_fields__)


# --- the recovery token (`auth-account-recovery` R3.1, R3.3, design D1) -------------


def _token(**overrides) -> PasswordResetToken:
    now = datetime.now(timezone.utc)
    values = {
        "id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "token_hash": "a" * 64,
        "expires_at": now + timedelta(minutes=30),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return PasswordResetToken(**values)


def test_a_fresh_token_is_usable() -> None:
    assert _token().is_usable(datetime.now(timezone.utc)) is True


def test_a_used_token_is_not_usable() -> None:
    now = datetime.now(timezone.utc)
    assert _token(used_at=now).is_usable(now) is False


def test_a_revoked_token_is_not_usable() -> None:
    now = datetime.now(timezone.utc)
    assert _token(revoked_at=now).is_usable(now) is False


def test_an_expired_token_is_not_usable() -> None:
    now = datetime.now(timezone.utc)
    assert _token(expires_at=now - timedelta(seconds=1)).is_usable(now) is False


def test_a_token_expiring_exactly_now_is_not_usable() -> None:
    """The bound is strict, matching the `expires_at > :now` of the consuming UPDATE (D1)."""
    now = datetime.now(timezone.utc)
    assert _token(expires_at=now).is_usable(now) is False


def test_a_naive_expiry_is_refused() -> None:
    """Same guard as `UserSession`: a naive datetime compares wrongly against an aware one."""
    with pytest.raises(ValueError):
        _token(expires_at=datetime.now())


def test_a_naive_now_is_refused() -> None:
    with pytest.raises(ValueError):
        _token().is_usable(datetime.now())
