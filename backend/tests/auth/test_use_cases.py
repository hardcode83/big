"""Auth use cases against real repositories and a real JWT codec (R1, R2, R5)."""

import logging
import uuid
from datetime import timedelta

import pytest

from app.auth.application.use_cases import (
    GetCurrentUserUseCase,
    LoginUseCase,
    LogoutUseCase,
    RefreshTokenUseCase,
)
from app.auth.domain.entities import UserSession
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import (
    InvalidCredentialsError,
    InvalidTokenError,
    SessionReuseDetectedError,
    TooManyAttemptsError,
)
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import (
    SqlAlchemySessionRepository,
    SqlAlchemyTenantStatusReader,
    SqlAlchemyUserRepository,
)
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.tenants.domain.enums import TenantStatus
from tests.auth.conftest import PASSWORD, TEST_BCRYPT_ROUNDS, insert_tenant, insert_user, utc_now
from tests.auth.doubles import (
    CountingPasswordHasher,
    InMemoryLoginThrottle,
    UnlimitedLoginThrottle,
)

IP = "198.51.100.7"


class FlushingUnitOfWork:
    """Commits for real; the test database is dropped after each test anyway."""

    def __init__(self, session) -> None:
        self._session = session
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1
        await self._session.commit()


@pytest.fixture
def codec() -> JwtTokenCodec:
    return JwtTokenCodec(secret="s" * 64, access_minutes=15, refresh_days=7)


@pytest.fixture
def hasher() -> BcryptPasswordHasher:
    return BcryptPasswordHasher(rounds=TEST_BCRYPT_ROUNDS)


def _login(db_session, codec, hasher, throttle=None) -> LoginUseCase:
    return LoginUseCase(
        users=SqlAlchemyUserRepository(db_session),
        tenants=SqlAlchemyTenantStatusReader(db_session),
        sessions=SqlAlchemySessionRepository(db_session),
        hasher=hasher,
        tokens=codec,
        throttle=throttle or UnlimitedLoginThrottle(),
        uow=FlushingUnitOfWork(db_session),
    )


def _refresh(db_session, codec) -> RefreshTokenUseCase:
    return RefreshTokenUseCase(
        users=SqlAlchemyUserRepository(db_session),
        sessions=SqlAlchemySessionRepository(db_session),
        tokens=codec,
        uow=FlushingUnitOfWork(db_session),
    )


@pytest.mark.asyncio
async def test_a_correct_login_returns_a_token_pair(db_session, tenant_a, codec, hasher) -> None:
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)

    pair = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )

    assert pair.token_type == "bearer"
    assert pair.expires_in == 900
    access = codec.decode_access(pair.access_token)
    refresh = codec.decode_refresh(pair.refresh_token)
    assert access.user_id == user.id
    assert access.tenant_id == tenant_a.id
    # Both tokens name the same family, which is what lets logout close this session
    # (design D18).
    assert access.family_id == refresh.family_id


@pytest.mark.asyncio
async def test_login_updates_last_login_at(db_session, tenant_a, codec, hasher) -> None:
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    moment = utc_now()

    await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=moment
    )

    reloaded = await SqlAlchemyUserRepository(db_session).get_active_by_id(tenant_a.id, user.id)
    assert reloaded is not None and reloaded.last_login_at == moment


@pytest.mark.asyncio
async def test_login_persists_the_session_row(db_session, tenant_a, codec, hasher) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)

    pair = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )

    claims = codec.decode_refresh(pair.refresh_token)
    # The refresh jti IS the row id (design D5).
    stored = await SqlAlchemySessionRepository(db_session).get(tenant_a.id, claims.token_id)
    assert stored is not None and stored.family_id == claims.family_id


@pytest.mark.asyncio
async def test_login_is_case_insensitive_on_the_address(db_session, tenant_a, codec, hasher) -> None:
    await insert_user(db_session, tenant=tenant_a, email="Owner@Example.com", hasher=hasher)

    pair = await _login(db_session, codec, hasher).execute(
        email="  OWNER@example.COM ", password=PASSWORD, client_ip=IP, now=utc_now()
    )

    assert pair.access_token


@pytest.mark.asyncio
async def test_an_unknown_address_is_refused(db_session, tenant_a, codec, hasher) -> None:
    await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    with pytest.raises(InvalidCredentialsError):
        await _login(db_session, codec, hasher).execute(
            email="nobody@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
        )


@pytest.mark.asyncio
async def test_a_wrong_password_is_refused(db_session, tenant_a, codec, hasher) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)

    with pytest.raises(InvalidCredentialsError):
        await _login(db_session, codec, hasher).execute(
            email="owner@example.com", password="not the password", client_ip=IP, now=utc_now()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [UserStatus.INACTIVE, UserStatus.SUSPENDED])
async def test_a_disabled_user_is_refused_indistinguishably(
    db_session, tenant_a, codec, hasher, status
) -> None:
    # R1.4: the caller must not be able to tell this from a wrong password.
    await insert_user(
        db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher, status=status
    )

    with pytest.raises(InvalidCredentialsError):
        await _login(db_session, codec, hasher).execute(
            email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
        )


@pytest.mark.asyncio
async def test_a_user_of_a_disabled_tenant_is_refused(db_session, codec, hasher) -> None:
    tenant = await insert_tenant(db_session, status=TenantStatus.SUSPENDED)
    await insert_user(db_session, tenant=tenant, email="owner@example.com", hasher=hasher)

    with pytest.raises(InvalidCredentialsError):
        await _login(db_session, codec, hasher).execute(
            email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
        )


@pytest.mark.asyncio
async def test_the_same_address_in_two_tenants_authenticates_nobody(
    db_session, tenant_a, tenant_b, codec, hasher
) -> None:
    """Design D16's ambiguity: it fails closed, it does not pick one."""
    await insert_user(db_session, tenant=tenant_a, email="shared@example.com", hasher=hasher)
    await insert_user(db_session, tenant=tenant_b, email="shared@example.com", hasher=hasher)

    with pytest.raises(InvalidCredentialsError):
        await _login(db_session, codec, hasher).execute(
            email="shared@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
        )


@pytest.mark.asyncio
async def test_the_ip_limit_refuses_before_checking_credentials(
    db_session, tenant_a, codec, hasher
) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    throttle = InMemoryLoginThrottle(attempts_per_minute=1)
    use_case = _login(db_session, codec, hasher, throttle)
    await use_case.execute(email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now())

    with pytest.raises(TooManyAttemptsError):
        await use_case.execute(
            email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
        )


@pytest.mark.asyncio
async def test_consecutive_failures_lock_the_account(db_session, tenant_a, codec, hasher) -> None:
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    throttle = InMemoryLoginThrottle(max_failures=3)
    use_case = _login(db_session, codec, hasher, throttle)

    for _ in range(3):
        with pytest.raises(InvalidCredentialsError):
            await use_case.execute(
                email="owner@example.com", password="wrong", client_ip=IP, now=utc_now()
            )

    assert await throttle.is_account_locked(user.id) is True
    # Even the right password is refused while locked, with the same error (R5.2).
    with pytest.raises(InvalidCredentialsError):
        await use_case.execute(
            email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
        )


@pytest.mark.asyncio
async def test_a_locked_account_does_not_accumulate_further_failures(
    db_session, tenant_a, codec, hasher
) -> None:
    """Otherwise the lock renews on every attempt and R5.2's 15 minutes is not a bound."""
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    throttle = InMemoryLoginThrottle(max_failures=1)
    use_case = _login(db_session, codec, hasher, throttle)
    with pytest.raises(InvalidCredentialsError):
        await use_case.execute(
            email="owner@example.com", password="wrong", client_ip=IP, now=utc_now()
        )
    assert await throttle.is_account_locked(user.id) is True

    for _ in range(5):
        with pytest.raises(InvalidCredentialsError):
            await use_case.execute(
                email="owner@example.com", password="wrong", client_ip=IP, now=utc_now()
            )

    assert throttle.failures.get(user.id, 0) == 0


@pytest.mark.asyncio
async def test_a_successful_login_clears_previous_failures(
    db_session, tenant_a, codec, hasher
) -> None:
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    throttle = InMemoryLoginThrottle(max_failures=3)
    use_case = _login(db_session, codec, hasher, throttle)
    with pytest.raises(InvalidCredentialsError):
        await use_case.execute(
            email="owner@example.com", password="wrong", client_ip=IP, now=utc_now()
        )

    await use_case.execute(email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now())

    assert throttle.failures.get(user.id, 0) == 0


@pytest.mark.asyncio
async def test_the_password_never_reaches_the_log(
    db_session, tenant_a, codec, hasher, caplog
) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    secret = "hunter2-do-not-log-me"

    with caplog.at_level(logging.WARNING, logger="app.auth"):
        with pytest.raises(InvalidCredentialsError):
            await _login(db_session, codec, hasher).execute(
                email="owner@example.com", password=secret, client_ip=IP, now=utc_now()
            )

    assert caplog.records, "a failed attempt must be recorded (R5.5)"
    assert secret not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("email", "password", "setup"),
    [
        ("nobody@example.com", PASSWORD, "none"),
        ("owner@example.com", "wrong password", "none"),
        ("owner@example.com", PASSWORD, "locked"),
        ("shared@example.com", PASSWORD, "ambiguous"),
    ],
    ids=["unknown-address", "wrong-password", "locked-account", "ambiguous-address"],
)
async def test_every_failed_login_spends_the_same_work(
    db_session, tenant_a, tenant_b, codec, hasher, email, password, setup
) -> None:
    """R1.4 is about being indistinguishable, and latency is distinguishable.

    bcrypt is the only expensive step on this path, so a failure that returns without
    it answers in ~2 ms where a real address costs the full configured cost — a 100x
    signal that enumerates users and reveals lockout state, with identical bodies.
    Counted rather than timed, so the assertion is not flaky.
    """
    counting = CountingPasswordHasher(hasher)
    throttle = InMemoryLoginThrottle(max_failures=1)
    if setup == "ambiguous":
        await insert_user(db_session, tenant=tenant_a, email="shared@example.com", hasher=hasher)
        await insert_user(db_session, tenant=tenant_b, email="shared@example.com", hasher=hasher)
    else:
        user = await insert_user(
            db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher
        )
        if setup == "locked":
            await throttle.record_failure(user.id)
    use_case = _login(db_session, codec, counting, throttle)
    counting.expensive_calls = 0

    with pytest.raises(InvalidCredentialsError):
        await use_case.execute(email=email, password=password, client_ip=IP, now=utc_now())

    assert counting.expensive_calls == 1, (
        "every failure path must do exactly one bcrypt-cost operation; "
        f"{setup} did {counting.expensive_calls}"
    )


@pytest.mark.asyncio
async def test_a_successful_login_also_spends_one_unit_of_work(
    db_session, tenant_a, codec, hasher
) -> None:
    counting = CountingPasswordHasher(hasher)
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    use_case = _login(db_session, codec, counting)
    counting.expensive_calls = 0

    await use_case.execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )

    assert counting.expensive_calls == 1


@pytest.mark.asyncio
async def test_refresh_rotates_and_invalidates_the_presented_token(
    db_session, tenant_a, codec, hasher
) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    first = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )

    second = await _refresh(db_session, codec).execute(
        refresh_token=first.refresh_token, now=utc_now()
    )

    assert second.refresh_token != first.refresh_token
    old = codec.decode_refresh(first.refresh_token)
    stored = await SqlAlchemySessionRepository(db_session).get(tenant_a.id, old.token_id)
    assert stored is not None and stored.used_at is not None
    # Used, NOT revoked: `revoked_reason` is reserved for actual revocations, so it
    # stays NULL here. See test_a_rotated_session_is_not_marked_as_revoked.
    assert stored.revoked_at is None


@pytest.mark.asyncio
async def test_reusing_a_refresh_token_revokes_the_whole_family(
    db_session, tenant_a, codec, hasher
) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    first = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )
    second = await _refresh(db_session, codec).execute(
        refresh_token=first.refresh_token, now=utc_now()
    )

    with pytest.raises(SessionReuseDetectedError):
        await _refresh(db_session, codec).execute(
            refresh_token=first.refresh_token, now=utc_now()
        )

    # The legitimate holder's current token goes down too: reuse is treated as theft.
    with pytest.raises(InvalidTokenError):
        await _refresh(db_session, codec).execute(
            refresh_token=second.refresh_token, now=utc_now()
        )


@pytest.mark.asyncio
async def test_a_session_can_only_be_consumed_once(db_session, tenant_a, codec, hasher) -> None:
    """The database decides who rotated, not a read-then-write (R2.1).

    Without the conditional UPDATE, two concurrent presentations of the same refresh
    token both observe `used_at IS NULL` and both rotate — and R2.2's reuse detection
    never fires for either.
    """
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    repo = SqlAlchemySessionRepository(db_session)
    session = UserSession(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        user_id=user.id,
        family_id=uuid.uuid4(),
        expires_at=utc_now() + timedelta(days=7),
    )
    await repo.add(tenant_a.id, session)
    await db_session.flush()
    now = utc_now()

    assert await repo.consume(tenant_a.id, session.id, now) is True
    assert await repo.consume(tenant_a.id, session.id, now) is False


@pytest.mark.asyncio
async def test_only_one_of_two_concurrent_consumers_wins(
    test_engine, db_session, tenant_a, hasher
) -> None:
    """The property `consume()` exists for, exercised with REAL concurrency (R2.1, R2.2).

    The sequential tests around this one prove idempotency, not atomicity: within one
    session and identity map, a naive read-then-write is also idempotent, so replacing
    the conditional UPDATE with `session.get()` + attribute mutation leaves them green.
    That was demonstrated by review. Two separate sessions on separate connections,
    racing under `asyncio.gather`, is what actually distinguishes the two.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)
    session_id, family_id = uuid.uuid4(), uuid.uuid4()
    await SqlAlchemySessionRepository(db_session).add(
        tenant_a.id,
        UserSession(
            id=session_id,
            tenant_id=tenant_a.id,
            user_id=user.id,
            family_id=family_id,
            expires_at=utc_now() + timedelta(days=7),
        ),
    )
    await db_session.commit()
    now = utc_now()

    async def attempt() -> bool:
        # Its own session, so its own connection and transaction — not the identity map
        # the other one is using.
        async with AsyncSession(test_engine, expire_on_commit=False) as own:
            won = await SqlAlchemySessionRepository(own).consume(tenant_a.id, session_id, now)
            await own.commit()
            return won

    results = await asyncio.gather(attempt(), attempt())

    assert sorted(results) == [False, True], (
        f"exactly one caller must consume the session, got {results}"
    )


@pytest.mark.asyncio
async def test_a_revoked_session_cannot_be_consumed(db_session, tenant_a, hasher) -> None:
    """A concurrent revocation must win the tie, not lose it (R2.2).

    `revoked_at IS NULL` has to be part of the conditional UPDATE, not only of the
    caller's in-memory check: the caller reads the row, makes another round trip, and a
    `revoke_family` committed in that window would otherwise be overwritten by a
    successful rotation that inserts a fresh, un-revoked child.
    """
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)
    repo = SqlAlchemySessionRepository(db_session)
    entity = UserSession(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        user_id=user.id,
        family_id=uuid.uuid4(),
        expires_at=utc_now() + timedelta(days=7),
    )
    await repo.add(tenant_a.id, entity)
    await db_session.flush()
    now = utc_now()
    await repo.revoke_family(tenant_a.id, entity.family_id, SessionRevokedReason.LOGOUT, now)

    assert await repo.consume(tenant_a.id, entity.id, now) is False


@pytest.mark.asyncio
async def test_an_expired_session_cannot_be_consumed(db_session, tenant_a, hasher) -> None:
    user = await insert_user(db_session, tenant=tenant_a, hasher=hasher)
    repo = SqlAlchemySessionRepository(db_session)
    entity = UserSession(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        user_id=user.id,
        family_id=uuid.uuid4(),
        expires_at=utc_now() - timedelta(seconds=1),
    )
    await repo.add(tenant_a.id, entity)
    await db_session.flush()

    assert await repo.consume(tenant_a.id, entity.id, utc_now()) is False


@pytest.mark.asyncio
async def test_consuming_will_not_cross_tenants(db_session, tenant_a, tenant_b, hasher) -> None:
    user_b = await insert_user(db_session, tenant=tenant_b, hasher=hasher)
    repo = SqlAlchemySessionRepository(db_session)
    session = UserSession(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        user_id=user_b.id,
        family_id=uuid.uuid4(),
        expires_at=utc_now() + timedelta(days=7),
    )
    await repo.add(tenant_b.id, session)
    await db_session.flush()

    assert await repo.consume(tenant_a.id, session.id, utc_now()) is False


@pytest.mark.asyncio
async def test_losing_the_rotation_race_is_treated_as_reuse(
    db_session, tenant_a, codec, hasher
) -> None:
    """Simulates the other caller winning between our read and our write."""
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    first = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )
    claims = codec.decode_refresh(first.refresh_token)
    repo = SqlAlchemySessionRepository(db_session)
    # Somebody else consumes it first, without going through the use case.
    assert await repo.consume(tenant_a.id, claims.token_id, utc_now()) is True
    await db_session.commit()

    with pytest.raises(SessionReuseDetectedError):
        await _refresh(db_session, codec).execute(
            refresh_token=first.refresh_token, now=utc_now()
        )


@pytest.mark.asyncio
async def test_a_rotated_session_is_not_marked_as_revoked(
    db_session, tenant_a, codec, hasher
) -> None:
    """`revoked_reason` must imply an actual revocation.

    An earlier version assigned `revoked_reason = ROTATED` directly on the entity,
    producing rows with a reason set and `revoked_at` NULL — a trap for any later query
    or audit that filters on the reason expecting genuinely revoked rows.
    """
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    first = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )
    await _refresh(db_session, codec).execute(refresh_token=first.refresh_token, now=utc_now())

    old = codec.decode_refresh(first.refresh_token)
    stored = await SqlAlchemySessionRepository(db_session).get(tenant_a.id, old.token_id)
    assert stored is not None
    assert stored.used_at is not None
    assert stored.revoked_at is None
    assert stored.revoked_reason is None


@pytest.mark.asyncio
async def test_refresh_refuses_an_access_token(db_session, tenant_a, codec, hasher) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    pair = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )

    with pytest.raises(InvalidTokenError):
        await _refresh(db_session, codec).execute(refresh_token=pair.access_token, now=utc_now())


@pytest.mark.asyncio
async def test_refresh_refuses_a_token_whose_session_does_not_exist(
    db_session, tenant_a, codec
) -> None:
    orphan = codec.issue_refresh(
        user_id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        role=UserRole.CLEANER,
        session_id=uuid.uuid4(),
        family_id=uuid.uuid4(),
        now=utc_now(),
    )

    with pytest.raises(InvalidTokenError):
        await _refresh(db_session, codec).execute(refresh_token=orphan, now=utc_now())


@pytest.mark.asyncio
async def test_refresh_refuses_an_expired_session(db_session, tenant_a, codec, hasher) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    pair = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )

    with pytest.raises(InvalidTokenError):
        await _refresh(db_session, codec).execute(
            refresh_token=pair.refresh_token, now=utc_now() + timedelta(days=8)
        )


@pytest.mark.asyncio
async def test_refresh_refuses_a_user_disabled_after_the_token_was_issued(
    db_session, tenant_a, codec, hasher
) -> None:
    """Design D7: revalidated against the database, not trusted from the claims."""
    user = await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    pair = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )
    user.status = UserStatus.SUSPENDED
    await db_session.flush()

    with pytest.raises(InvalidTokenError):
        await _refresh(db_session, codec).execute(
            refresh_token=pair.refresh_token, now=utc_now()
        )


@pytest.mark.asyncio
async def test_logout_ends_the_session_of_the_presented_access_token(
    db_session, tenant_a, codec, hasher
) -> None:
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    pair = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )
    access = codec.decode_access(pair.access_token)

    await LogoutUseCase(
        sessions=SqlAlchemySessionRepository(db_session),
        uow=FlushingUnitOfWork(db_session),
    ).execute(tenant_id=access.tenant_id, family_id=access.family_id, now=utc_now())

    with pytest.raises(InvalidTokenError):
        await _refresh(db_session, codec).execute(
            refresh_token=pair.refresh_token, now=utc_now()
        )


@pytest.mark.asyncio
async def test_an_access_token_survives_logout_until_it_expires(
    db_session, tenant_a, codec, hasher
) -> None:
    """Pins R2.4: there is no access-token revocation list, by decision.

    The window is bounded by the 15-minute lifetime, and this test exists so the
    tradeoff is visible rather than discovered later.
    """
    await insert_user(db_session, tenant=tenant_a, email="owner@example.com", hasher=hasher)
    pair = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )
    access = codec.decode_access(pair.access_token)
    await LogoutUseCase(
        sessions=SqlAlchemySessionRepository(db_session),
        uow=FlushingUnitOfWork(db_session),
    ).execute(tenant_id=access.tenant_id, family_id=access.family_id, now=utc_now())

    assert codec.decode_access(pair.access_token).user_id == access.user_id


@pytest.mark.asyncio
async def test_logout_cannot_close_another_tenants_session(
    db_session, tenant_a, tenant_b, codec, hasher
) -> None:
    await insert_user(db_session, tenant=tenant_b, email="owner@example.com", hasher=hasher)
    pair = await _login(db_session, codec, hasher).execute(
        email="owner@example.com", password=PASSWORD, client_ip=IP, now=utc_now()
    )
    access = codec.decode_access(pair.access_token)

    await LogoutUseCase(
        sessions=SqlAlchemySessionRepository(db_session),
        uow=FlushingUnitOfWork(db_session),
    ).execute(tenant_id=tenant_a.id, family_id=access.family_id, now=utc_now())

    # Tenant B's session is untouched, so its refresh still rotates.
    assert await _refresh(db_session, codec).execute(
        refresh_token=pair.refresh_token, now=utc_now()
    )


@pytest.mark.asyncio
async def test_get_current_user_returns_the_user_without_the_hash_leaking(
    db_session, tenant_a, hasher
) -> None:
    model = await insert_user(db_session, tenant=tenant_a, hasher=hasher)

    user = await GetCurrentUserUseCase(users=SqlAlchemyUserRepository(db_session)).execute(
        tenant_id=tenant_a.id, user_id=model.id
    )

    assert user.id == model.id
    # The entity carries the hash — it is the API schema's job not to expose it (7.1).
    assert user.password_hash


@pytest.mark.asyncio
async def test_get_current_user_refuses_a_cross_tenant_pair(
    db_session, tenant_a, tenant_b, hasher
) -> None:
    model = await insert_user(db_session, tenant=tenant_b, hasher=hasher)

    with pytest.raises(InvalidTokenError):
        await GetCurrentUserUseCase(users=SqlAlchemyUserRepository(db_session)).execute(
            tenant_id=tenant_a.id, user_id=model.id
        )
