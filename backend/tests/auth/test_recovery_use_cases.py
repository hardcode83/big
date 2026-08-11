"""Self-service password change, against in-memory fakes (`auth-account-recovery` R1).

`steering/testing.md` for this layer: fakes of the ports, never the database and never mocks
of SQLAlchemy. What is asserted here is orchestration — what gets written, in what order,
with which audit row, and what happens when a step fails. The SQL is covered by
`test_repositories.py` and the HTTP boundary by `test_recovery_api.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.audit.domain import actions
from app.auth.application.recovery import (
    ChangeOwnPasswordUseCase,
    ConsumePasswordResetUseCase,
    RequestPasswordResetUseCase,
)
from app.auth.domain.entities import PasswordResetToken, User
from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import (
    InvalidCredentialsError,
    InvalidRecoveryTokenError,
    PasswordPolicyError,
    PasswordTooLongError,
    PasswordUnchangedError,
    TooManyAttemptsError,
)
from app.auth.domain.recovery_messages import (
    STORED_RECOVERY_BODY,
    STORED_RECOVERY_SUBJECT,
)
from app.auth.domain.recovery_tokens import hash_recovery_token
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from tests.auth.doubles import (
    CapturingEmailAdapter,
    CountingPasswordHasher,
    FakeAuditLogRepository,
    FakeNotificationLogRepository,
    FakePasswordResetTokenRepository,
    FakeSessionRepository,
    FakeUnitOfWork,
    FakeUserRepository,
    InMemoryLoginThrottle,
    StubPasswordHasher,
    UnlimitedLoginThrottle,
)

TENANT = uuid.uuid4()
IP = "203.0.113.4"
CURRENT = "current-password-ok"
NEW = "a-brand-new-passphrase"


def utc_now() -> datetime:
    return datetime.now(UTC)


def _user(**overrides) -> User:
    now = utc_now()
    values = {
        "id": uuid.uuid4(),
        "tenant_id": TENANT,
        "name": "Ana",
        "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
        # Matches `StubPasswordHasher`, which hashes as f"hashed::{password}".
        "password_hash": f"hashed::{CURRENT}",
        "role": UserRole.CLEANER,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return User(**values)


@pytest.fixture
def ports():
    return {
        "users": FakeUserRepository(),
        "audit": FakeAuditLogRepository(),
        "sessions": FakeSessionRepository(),
        "uow": FakeUnitOfWork(),
        "hasher": StubPasswordHasher(),
        # Real thresholds, not unlimited: R1.8 is about the counter actually biting.
        "throttle": InMemoryLoginThrottle(max_failures=10),
    }


def _use_case(ports) -> ChangeOwnPasswordUseCase:
    return ChangeOwnPasswordUseCase(
        users=ports["users"],
        sessions=ports["sessions"],
        audit=ports["audit"],
        hasher=ports["hasher"],
        throttle=ports["throttle"],
        uow=ports["uow"],
    )


async def _change(ports, user, *, current=CURRENT, new=NEW) -> None:
    await _use_case(ports).execute(
        tenant_id=TENANT,
        user_id=user.id,
        actor_ip=IP,
        current_password=current,
        new_password=new,
        now=utc_now(),
    )


# --- R2: the anonymous request (design D2, D7) --------------------------------------


@pytest.fixture
def request_ports():
    return {
        "users": FakeUserRepository(),
        "tokens": FakePasswordResetTokenRepository(),
        "notifications": FakeNotificationLogRepository(),
        "adapter": CapturingEmailAdapter(),
        "throttle": UnlimitedLoginThrottle(),
        "uow": FakeUnitOfWork(),
    }


def _request_use_case(request_ports, **overrides) -> RequestPasswordResetUseCase:
    from app.notifications.domain.enums import NotificationChannel

    values = {
        "users": request_ports["users"],
        "tokens": request_ports["tokens"],
        "notifications": request_ports["notifications"],
        "adapters": {NotificationChannel.EMAIL: request_ports["adapter"]},
        "throttle": request_ports["throttle"],
        "uow": request_ports["uow"],
        "token_minutes": 30,
        "max_live_tokens": 3,
        # 0 by default in these tests, so the cap behaves as "revoke the oldest" and each
        # test that cares about the grace window opts in explicitly. A non-zero default would
        # make every cap test depend on wall-clock spacing between calls.
        "grace_minutes": 0,
        "frontend_base_url": "https://app.example.test",
    }
    values.update(overrides)
    return RequestPasswordResetUseCase(**values)


async def _ask(request_ports, email, **overrides) -> None:
    await _request_use_case(request_ports, **overrides).execute(
        email=email, client_ip="203.0.113.9", now=utc_now()
    )


@pytest.mark.asyncio
async def test_a_known_address_gets_a_link(request_ports) -> None:
    user = request_ports["users"].seed(_user())

    await _ask(request_ports, user.email)

    assert len(request_ports["adapter"].sent) == 1
    assert len(request_ports["tokens"].tokens) == 1
    assert request_ports["uow"].commits == 1


@pytest.mark.asyncio
async def test_the_sent_body_carries_the_link_and_the_stored_row_does_not(
    request_ports,
) -> None:
    """Design D2's central property, and the hardest constraint of the change (R4.2).

    Rule 11 of `steering/security.md` grants `notification_logs.subject`/`body` exactly one
    exception — the masked form of an access code — and a live recovery link is not it. So
    the text handed to the adapter and the text written to the row are different strings, and
    this asserts BOTH halves against the same generated token.
    """
    user = request_ports["users"].seed(_user())

    await _ask(request_ports, user.email)

    sent = request_ports["adapter"].sent[0]
    _tenant, row = request_ports["notifications"].rows[0]
    token_hash = next(iter(request_ports["tokens"].tokens.values())).token_hash

    assert "/reset-password?token=" in sent["body"]
    assert row.subject == STORED_RECOVERY_SUBJECT
    assert row.body == STORED_RECOVERY_BODY
    assert "token=" not in (row.body or "")
    # Nor the stored hash, which would be as good as the token for anyone who can compute
    # sha256 of a candidate.
    assert token_hash not in (row.body or "")
    assert token_hash not in (row.subject or "")


@pytest.mark.asyncio
async def test_the_cleartext_token_is_never_persisted(request_ports) -> None:
    """R4.1 — the row keeps only the digest."""
    user = request_ports["users"].seed(_user())

    await _ask(request_ports, user.email)

    sent_link = request_ports["adapter"].sent[0]["body"]
    cleartext = sent_link.split("token=")[1].split()[0]
    stored = next(iter(request_ports["tokens"].tokens.values()))

    assert stored.token_hash != cleartext
    assert cleartext not in stored.token_hash
    assert hash_recovery_token(cleartext) == stored.token_hash


@pytest.mark.asyncio
async def test_the_row_is_written_in_a_final_state_and_never_pending(
    request_ports,
) -> None:
    """The detail design D2 says decides correctness.

    `PENDING` is `list_pending`'s queue, so the dispatcher would pick the row up next tick
    and deliver the STORED body — mailing the user a notice with no link in it. The adapter
    has already answered by now, so the final state is also the honest one.
    """
    user = request_ports["users"].seed(_user())

    await _ask(request_ports, user.email)

    _tenant, row = request_ports["notifications"].rows[0]
    assert row.status is NotificationStatus.SENT
    assert row.status is not NotificationStatus.PENDING
    assert row.attempts == 1
    assert row.sent_at is not None


@pytest.mark.asyncio
async def test_an_adapter_failure_is_recorded_as_failed_not_pending(
    request_ports,
) -> None:
    """A failure must not land in the dispatcher's queue either — a retry would deliver the
    linkless stored body. The user asks again instead."""
    request_ports["adapter"] = CapturingEmailAdapter(delivered=False)
    user = request_ports["users"].seed(_user())

    await _ask(request_ports, user.email)

    _tenant, row = request_ports["notifications"].rows[0]
    assert row.status is NotificationStatus.FAILED
    assert row.sent_at is None
    assert row.last_error == "ADAPTER_ERROR"
    # The token was still issued, so the link in the (undelivered) mail would work if it
    # somehow arrived. Failing the other way would strand a user whose provider blipped.
    assert len(request_ports["tokens"].tokens) == 1


@pytest.mark.asyncio
async def test_the_row_carries_no_sla_deadline(request_ports) -> None:
    """R6.2: `escalation_for` returns None for this type and the SLA job leaves it alone —
    there is no promise to miss in a recovery."""
    user = request_ports["users"].seed(_user())

    await _ask(request_ports, user.email)

    _tenant, row = request_ports["notifications"].rows[0]
    assert row.sla_deadline_at is None
    assert row.notification_type == "PASSWORD_RESET_REQUESTED"


@pytest.mark.asyncio
async def test_the_row_names_the_resolved_account(request_ports) -> None:
    """R6.3: the tenant comes from the resolved row, never from the request."""
    user = request_ports["users"].seed(_user())

    await _ask(request_ports, user.email)

    tenant_id, row = request_ports["notifications"].rows[0]
    assert tenant_id == user.tenant_id
    assert row.tenant_id == user.tenant_id
    assert row.recipient_user_id == user.id


@pytest.mark.asyncio
async def test_a_missing_email_adapter_records_why(request_ports) -> None:
    """D2 says a `FAILED` row carries "su `NotificationErrorCode`"; one with `last_error`
    empty did not. `NO_ADAPTER_FOR_CHANNEL` is the code the dispatcher's own
    `_skip_unroutable` already uses for exactly this. Named by the architect panel."""
    user = request_ports["users"].seed(_user())

    await _ask(request_ports, user.email, adapters={})

    _tenant, row = request_ports["notifications"].rows[0]
    assert row.status is NotificationStatus.FAILED
    assert row.last_error == "NO_ADAPTER_FOR_CHANNEL"
    assert row.sent_at is None


@pytest.mark.asyncio
async def test_an_adapter_that_raises_still_answers_and_records(request_ports) -> None:
    """An exception must NOT propagate (security panel of section 6).

    `NotificationAdapter.send` promises never to raise for a delivery failure, so a raise
    means a broken adapter — but letting it through would answer `500` where the address
    resolves and `202` where it does not, a clean enumeration oracle. Unreachable today with
    `ConsoleEmailAdapter`; live the day SMTP lands.
    """

    class ExplodingAdapter:
        async def send(self, **_kwargs):
            raise RuntimeError("smtp: connection reset")

    user = request_ports["users"].seed(_user())

    await _ask(
        request_ports,
        user.email,
        adapters={NotificationChannel.EMAIL: ExplodingAdapter()},
    )

    _tenant, row = request_ports["notifications"].rows[0]
    assert row.status is NotificationStatus.FAILED
    assert row.last_error == "ADAPTER_ERROR"
    # The token still exists, so the flow is recoverable by asking again.
    assert len(request_ports["tokens"].tokens) == 1
    assert request_ports["uow"].commits == 1


@pytest.mark.asyncio
async def test_the_adapters_exception_text_never_reaches_the_row(request_ports) -> None:
    """Rule 11's structured form, enforced by the type: `last_error` takes an enum member,
    so a provider message embedded in an exception has nowhere to travel."""

    class ExplodingAdapter:
        async def send(self, **_kwargs):
            raise RuntimeError("smtp said: user unknown for bob@example.test")

    user = request_ports["users"].seed(_user())

    await _ask(
        request_ports,
        user.email,
        adapters={NotificationChannel.EMAIL: ExplodingAdapter()},
    )

    _tenant, row = request_ports["notifications"].rows[0]
    assert "bob@example.test" not in (row.last_error or "")
    assert "smtp said" not in (row.last_error or "")


@pytest.mark.asyncio
async def test_the_adapters_exception_text_never_reaches_the_log_either(
    request_ports, caplog
) -> None:
    """R2.6 covers the APPLICATION LOG, and that is the sink the first fix leaked into.

    An earlier version used `logger.exception`, so the traceback's final line put the
    recipient in the log — adapter exceptions carry it by construction
    (`SMTPRecipientsRefused` is keyed by recipient). The row was asserted and the log was
    not, which is how it survived one round of review. Named by the security panel of
    section 6.
    """

    class ExplodingAdapter:
        async def send(self, **_kwargs):
            raise RuntimeError("smtp said: user unknown for bob@example.test")

    user = request_ports["users"].seed(_user())

    with caplog.at_level("WARNING"):
        await _ask(
            request_ports,
            user.email,
            adapters={NotificationChannel.EMAIL: ExplodingAdapter()},
        )

    logged = "\n".join(
        record.getMessage() + str(record.__dict__) for record in caplog.records
    )
    assert "bob@example.test" not in logged
    assert "smtp said" not in logged
    assert user.email not in logged
    # What an operator does get: the class name, so a broken adapter is still diagnosable.
    assert "RuntimeError" in logged


# --- R2.2: indistinguishable, and silent ---------------------------------------------


@pytest.mark.asyncio
async def test_an_unknown_address_emits_nothing(request_ports) -> None:
    await _ask(request_ports, "nobody@example.test")

    assert request_ports["adapter"].sent == []
    assert request_ports["tokens"].tokens == {}
    assert request_ports["notifications"].rows == []
    assert request_ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_an_inactive_user_emits_nothing(request_ports) -> None:
    user = request_ports["users"].seed(_user(status=UserStatus.INACTIVE))

    await _ask(request_ports, user.email)

    assert request_ports["adapter"].sent == []
    assert request_ports["notifications"].rows == []


@pytest.mark.asyncio
async def test_a_suspended_user_emits_nothing(request_ports) -> None:
    user = request_ports["users"].seed(_user(status=UserStatus.SUSPENDED))

    await _ask(request_ports, user.email)

    assert request_ports["adapter"].sent == []
    assert request_ports["notifications"].rows == []


@pytest.mark.asyncio
async def test_at_the_cap_the_newest_request_wins_and_the_oldest_link_is_revoked(
    request_ports,
) -> None:
    """R2.5 / design D7 as amended: the cap bounds coexisting links, it does not silence.

    The original behaviour dropped the request at the cap, which let anyone who knew an
    address suppress the real owner's recovery for the token lifetime with no signal to them
    (R2.2) — the capability this change exists to provide. Raised by the security panel of
    section 6, resolved by Jose.
    """
    user = request_ports["users"].seed(_user())
    for _ in range(3):
        await _ask(request_ports, user.email)
    first = min(request_ports["tokens"].tokens.values(), key=lambda t: (t.created_at, t.id))

    await _ask(request_ports, user.email)

    assert len(request_ports["adapter"].sent) == 4, "the legitimate request was dropped"
    assert first.revoked_at is not None, "the oldest link was not retired"
    # `revoked`, not `used`: the two are different facts, and only a consumption sets `used`.
    assert first.used_at is None


@pytest.mark.asyncio
async def test_sequential_requests_never_leave_more_live_links_than_the_cap(
    request_ports,
) -> None:
    """The property the cap buys, stated as it actually holds: **sequentially**.

    Deliberately not "never exceeds the cap" without qualification. The QA panel of section 6
    measured 8 concurrent requests producing 8 live tokens against a cap of 3 — `count_live`
    is a `SELECT count()` and nothing serialises it against the following `INSERT`. Design D7
    records why that is accepted (the per-IP budget is what bounds volume; extra coexisting
    links do not help guess a 256-bit token; and an advisory lock on anonymous surface would
    be a contention point anyone could take). This test asserts the guarantee that is real
    rather than the one that reads better.
    """
    user = request_ports["users"].seed(_user())

    for _ in range(8):
        await _ask(request_ports, user.email)

    now = utc_now()
    live = [t for t in request_ports["tokens"].tokens.values() if t.is_usable(now)]
    assert len(live) == 3


@pytest.mark.asyncio
async def test_a_third_party_cannot_suppress_a_genuine_recovery(request_ports) -> None:
    """The attack the amendment closes, written as the attacker's sequence.

    Someone who knows the address burns the cap; the owner then asks, and must still be sent
    a working link.
    """
    user = request_ports["users"].seed(_user())
    for _ in range(3):  # the attacker
        await _ask(request_ports, user.email)
    sent_before = len(request_ports["adapter"].sent)

    await _ask(request_ports, user.email)  # the owner

    assert len(request_ports["adapter"].sent) == sent_before + 1
    owners_link = request_ports["adapter"].sent[-1]["body"]
    cleartext = owners_link.split("token=")[1].split()[0]
    matching = [
        t
        for t in request_ports["tokens"].tokens.values()
        if t.token_hash == hash_recovery_token(cleartext)
    ]
    assert len(matching) == 1
    assert matching[0].is_usable(utc_now()), "the owner's own link is not usable"


@pytest.mark.asyncio
async def test_within_the_grace_window_nothing_is_revoked_and_nothing_is_sent(
    request_ports,
) -> None:
    """R2.5 / design D7's grace amendment — the property that restores the mail bound.

    Revoking the oldest without a grace removed the only per-account bound on mail volume: a
    per-IP budget cannot bound a per-account total across IPs. With the grace, an account at
    its cap whose links are all fresh sends nothing, so volume is back to `cap` per grace
    window. Raised by the security panel of section 6, resolved by Jose.
    """
    user = request_ports["users"].seed(_user())
    for _ in range(3):
        await _ask(request_ports, user.email, grace_minutes=5)
    assert len(request_ports["adapter"].sent) == 3

    await _ask(request_ports, user.email, grace_minutes=5)

    assert len(request_ports["adapter"].sent) == 3, "mail was sent inside the grace window"
    assert len(request_ports["notifications"].rows) == 3
    now = utc_now()
    assert len([t for t in request_ports["tokens"].tokens.values() if t.is_usable(now)]) == 3


@pytest.mark.asyncio
async def test_the_grace_refusal_is_indistinguishable_from_the_other_refusals(
    request_ports,
) -> None:
    """R2.2 still governs: the reintroduced discard path returns like every other one."""
    user = request_ports["users"].seed(_user())
    for _ in range(3):
        await _ask(request_ports, user.email, grace_minutes=5)

    assert await _request_use_case(request_ports, grace_minutes=5).execute(
        email=user.email, client_ip="203.0.113.9", now=utc_now()
    ) is None


@pytest.mark.asyncio
async def test_the_link_just_sent_to_the_owner_cannot_be_retired(request_ports) -> None:
    """The other half the grace closes: the sustained attacker (finding C).

    Without it, three further requests at ~3/min retired the owner's fresh link about twenty
    seconds after it was mailed — so the owner went from receiving no mail to receiving mail
    whose link no longer worked. Inside the grace, the newest link is unrevokable.
    """
    user = request_ports["users"].seed(_user())
    for _ in range(3):  # the attacker fills the cap
        await _ask(request_ports, user.email, grace_minutes=0)
    await _ask(request_ports, user.email, grace_minutes=0)  # the owner gets a fresh link
    owners_hash = hash_recovery_token(
        request_ports["adapter"].sent[-1]["body"].split("token=")[1].split()[0]
    )

    for _ in range(3):  # the attacker keeps going, now with the grace in force
        await _ask(request_ports, user.email, grace_minutes=5)

    owners_token = next(
        t for t in request_ports["tokens"].tokens.values() if t.token_hash == owners_hash
    )
    assert owners_token.is_usable(utc_now()), "the owner's fresh link was retired"


@pytest.mark.asyncio
async def test_lowering_the_cap_converges_instead_of_stranding_the_account(
    request_ports,
) -> None:
    """`keep_newest` rather than "revoke exactly one": an account left over a lowered cap
    would otherwise stay above it for ever."""
    user = request_ports["users"].seed(_user())
    for _ in range(3):
        await _ask(request_ports, user.email)

    await _ask(request_ports, user.email, max_live_tokens=2)

    now = utc_now()
    live = [t for t in request_ports["tokens"].tokens.values() if t.is_usable(now)]
    assert len(live) == 2


@pytest.mark.asyncio
async def test_every_refused_path_returns_none_like_the_happy_one(request_ports) -> None:
    """R2.2 at the use-case level: the four outcomes are indistinguishable to the caller
    because there is nothing to distinguish — all of them return None."""
    known = request_ports["users"].seed(_user())
    inactive = request_ports["users"].seed(_user(status=UserStatus.INACTIVE))

    assert await _request_use_case(request_ports).execute(
        email=known.email, client_ip="203.0.113.9", now=utc_now()
    ) is None
    assert await _request_use_case(request_ports).execute(
        email=inactive.email, client_ip="203.0.113.9", now=utc_now()
    ) is None
    assert await _request_use_case(request_ports).execute(
        email="nobody@example.test", client_ip="203.0.113.9", now=utc_now()
    ) is None


# --- R2.6 / R4.3: what the log says --------------------------------------------------


@pytest.mark.asyncio
async def test_the_log_records_the_outcome_without_the_address_or_the_token(
    request_ports, caplog
) -> None:
    """R2.6 and R4.3. Neither the email nor the token, in any reversible form."""
    user = request_ports["users"].seed(_user())

    with caplog.at_level("INFO"):
        await _ask(request_ports, user.email)

    logged = "\n".join(
        record.getMessage() + str(getattr(record, "__dict__", {}))
        for record in caplog.records
    )
    cleartext = request_ports["adapter"].sent[0]["body"].split("token=")[1].split()[0]
    token_hash = next(iter(request_ports["tokens"].tokens.values())).token_hash

    assert "auth.password_reset_requested" in logged
    assert user.email not in logged
    assert cleartext not in logged
    assert token_hash not in logged


@pytest.mark.asyncio
async def test_the_log_records_the_unresolved_case_too_without_the_address(
    request_ports, caplog
) -> None:
    """R2.6 asks for the attempt to be logged with its result. The address stays out even
    here, where there is no account to protect — because the absence of an account is itself
    the fact an enumerator wants, and a log is a sink like any other."""
    with caplog.at_level("INFO"):
        await _ask(request_ports, "nobody@example.test")

    logged = "\n".join(
        record.getMessage() + str(getattr(record, "__dict__", {}))
        for record in caplog.records
    )
    assert "auth.password_reset_requested" in logged
    assert "nobody@example.test" not in logged


# --- R3: consuming the token (design D10, D8, D11) ---------------------------------


@pytest.fixture
def consume_ports():
    return {
        "users": FakeUserRepository(),
        "tokens": FakePasswordResetTokenRepository(),
        "sessions": FakeSessionRepository(),
        "audit": FakeAuditLogRepository(),
        "hasher": StubPasswordHasher(),
        "throttle": InMemoryLoginThrottle(max_failures=10),
        "uow": FakeUnitOfWork(),
    }


def _consume_use_case(consume_ports) -> ConsumePasswordResetUseCase:
    return ConsumePasswordResetUseCase(
        users=consume_ports["users"],
        tokens=consume_ports["tokens"],
        sessions=consume_ports["sessions"],
        audit=consume_ports["audit"],
        hasher=consume_ports["hasher"],
        throttle=consume_ports["throttle"],
        uow=consume_ports["uow"],
    )


def _seed_token(consume_ports, user, *, cleartext="link-token-abc", **overrides):
    now = utc_now()
    values = {
        "id": uuid.uuid4(),
        "tenant_id": user.tenant_id,
        "user_id": user.id,
        "token_hash": hash_recovery_token(cleartext),
        "expires_at": now + timedelta(minutes=30),
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    return consume_ports["tokens"].seed(PasswordResetToken(**values))


async def _consume(consume_ports, *, token="link-token-abc", new=NEW) -> None:
    await _consume_use_case(consume_ports).execute(
        token=token, new_password=new, client_ip="203.0.113.9", now=utc_now()
    )


@pytest.mark.asyncio
async def test_a_valid_token_replaces_the_password(consume_ports) -> None:
    user = consume_ports["users"].seed(_user())
    _seed_token(consume_ports, user)

    await _consume(consume_ports)

    assert user.password_hash == f"hashed::{NEW}"
    assert consume_ports["users"].applied[0][2]["password_hash"] == f"hashed::{NEW}"
    assert consume_ports["uow"].commits == 1


@pytest.mark.asyncio
async def test_a_recovered_password_is_never_temporary(consume_ports) -> None:
    """R5.3 — completing R3 is the other way out of the must-change state."""
    user = consume_ports["users"].seed(_user(must_change_password=True))
    _seed_token(consume_ports, user)

    await _consume(consume_ports)

    assert user.must_change_password is False
    assert consume_ports["users"].applied[0][2]["must_change_password"] is False


@pytest.mark.asyncio
async def test_the_token_is_spent_and_cannot_be_reused(consume_ports) -> None:
    """R3.1/R3.2 — a presented link is a spent link."""
    user = consume_ports["users"].seed(_user())
    token = _seed_token(consume_ports, user)

    await _consume(consume_ports)
    assert token.used_at is not None

    with pytest.raises(InvalidRecoveryTokenError):
        await _consume(consume_ports)


@pytest.mark.parametrize(
    "overrides",
    [
        {"used_at": True},
        {"revoked_at": True},
        {"minutes_ago": True},
    ],
    ids=["already-used", "revoked", "expired"],
)
@pytest.mark.asyncio
async def test_every_unusable_token_answers_the_same(consume_ports, overrides) -> None:
    """R3.3 — one indistinguishable error, so the endpoint cannot probe which tokens exist."""
    user = consume_ports["users"].seed(_user())
    now = utc_now()
    kwargs = {}
    if overrides.get("used_at"):
        kwargs["used_at"] = now
    if overrides.get("revoked_at"):
        kwargs["revoked_at"] = now
    if overrides.get("minutes_ago"):
        kwargs["expires_at"] = now - timedelta(minutes=1)
    _seed_token(consume_ports, user, **kwargs)

    with pytest.raises(InvalidRecoveryTokenError):
        await _consume(consume_ports)

    assert consume_ports["users"].applied == []
    assert consume_ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_an_unknown_token_answers_the_same(consume_ports) -> None:
    consume_ports["users"].seed(_user())

    with pytest.raises(InvalidRecoveryTokenError):
        await _consume(consume_ports, token="never-issued")


@pytest.mark.asyncio
async def test_an_inactive_user_answers_the_same_but_the_token_is_still_spent(
    consume_ports,
) -> None:
    """Design D10's accepted consequence, stated as a test.

    Consuming BEFORE validating the account means a token presented against a deactivated
    user is burned. That is the deliberate trade: checking the account first reintroduces the
    read-then-write race R3.2 forbids.
    """
    user = consume_ports["users"].seed(_user(status=UserStatus.INACTIVE))
    token = _seed_token(consume_ports, user)

    with pytest.raises(InvalidRecoveryTokenError):
        await _consume(consume_ports)

    assert token.used_at is not None, "the token survived a presentation"
    assert consume_ports["users"].applied == []
    assert consume_ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_the_policy_is_checked_before_the_token_is_spent(consume_ports) -> None:
    """D10: a weak password must not burn a token, and must not reach bcrypt either."""
    user = consume_ports["users"].seed(_user())
    token = _seed_token(consume_ports, user)

    with pytest.raises(PasswordPolicyError):
        await _consume(consume_ports, new="short")

    assert token.used_at is None, "a weak password burned the token"


@pytest.mark.asyncio
async def test_an_anonymous_caller_without_a_token_pays_no_bcrypt(consume_ports) -> None:
    """The CPU half of D10's ordering, on ANONYMOUS surface.

    Policy first, then the conditional UPDATE, and only then the hash — so somebody with no
    token cannot make the server spend ~250 ms per request.
    """
    counting = CountingPasswordHasher(StubPasswordHasher())
    consume_ports["hasher"] = counting
    consume_ports["users"].seed(_user())

    with pytest.raises(InvalidRecoveryTokenError):
        await _consume(consume_ports, token="never-issued")

    assert counting.expensive_calls == 0


@pytest.mark.asyncio
async def test_every_session_is_revoked(consume_ports) -> None:
    """R3.5(a)."""
    user = consume_ports["users"].seed(_user())
    _seed_token(consume_ports, user)

    await _consume(consume_ports)

    assert consume_ports["sessions"].revocations == [
        (user.tenant_id, user.id, SessionRevokedReason.PASSWORD_RESET)
    ]


@pytest.mark.asyncio
async def test_the_other_live_links_are_invalidated(consume_ports) -> None:
    """R3.5(b) — a recovery leaves no spare credentials behind."""
    user = consume_ports["users"].seed(_user())
    spent = _seed_token(consume_ports, user, cleartext="link-token-abc")
    sibling = _seed_token(consume_ports, user, cleartext="another-live-link")

    await _consume(consume_ports)

    assert sibling.revoked_at is not None
    # The consumed one keeps `used`, not `revoked`: the two are different facts.
    assert spent.used_at is not None
    assert spent.revoked_at is None


@pytest.mark.asyncio
async def test_the_account_lock_is_lifted(consume_ports) -> None:
    """R3.5(c) — ten failures are what usually precede "I lost my password", so without this
    the recovery recovers nothing: the next login is refused for the rest of the lockout."""
    user = consume_ports["users"].seed(_user())
    _seed_token(consume_ports, user)
    consume_ports["throttle"].locked.add(user.id)

    await _consume(consume_ports)

    assert await consume_ports["throttle"].is_account_locked(user.id) is False


@pytest.mark.asyncio
async def test_a_failure_clearing_the_lock_does_not_undo_the_reset(consume_ports) -> None:
    """Design D8: Redis and Postgres share no transaction, so one has to be able to fail
    alone. Clearing after the commit leaves at worst a lock that expires by itself over an
    account already recovered — the benign degradation. A `500` for a reset that landed is
    not."""

    class BrokenThrottle(InMemoryLoginThrottle):
        async def clear_account_lock(self, user_id):
            raise RuntimeError("redis is down")

    consume_ports["throttle"] = BrokenThrottle()
    user = consume_ports["users"].seed(_user())
    _seed_token(consume_ports, user)

    await _consume(consume_ports)

    assert consume_ports["uow"].commits == 1
    assert user.password_hash == f"hashed::{NEW}"


@pytest.mark.asyncio
async def test_it_audits_as_a_recovery_with_the_user_as_actor(consume_ports) -> None:
    """Design D9 — distinguishable from both an administrator's reset and a self-change."""
    user = consume_ports["users"].seed(_user())
    _seed_token(consume_ports, user)

    await _consume(consume_ports)

    _tenant, entry = consume_ports["audit"].entries[0]
    assert entry.action == actions.USER_PASSWORD_RECOVERED
    assert entry.action not in (actions.USER_PASSWORD_RESET, actions.USER_PASSWORD_CHANGED)
    assert entry.actor_user_id == user.id
    assert entry.actor_ip == "203.0.113.9"


@pytest.mark.asyncio
async def test_neither_the_token_nor_the_password_reaches_the_audit_row(
    consume_ports,
) -> None:
    """R4.3."""
    user = consume_ports["users"].seed(_user())
    _seed_token(consume_ports, user)

    await _consume(consume_ports)

    _tenant, entry = consume_ports["audit"].entries[0]
    recorded = str(entry.changes)
    assert "link-token-abc" not in recorded
    assert NEW not in recorded
    assert entry.changes == {"password": {"changed": True}}


@pytest.mark.asyncio
async def test_it_returns_no_session(consume_ports) -> None:
    """R3.6 — possession of a link must not become a session."""
    user = consume_ports["users"].seed(_user())
    _seed_token(consume_ports, user)

    result = await _consume_use_case(consume_ports).execute(
        token="link-token-abc", new_password=NEW, client_ip="203.0.113.9", now=utc_now()
    )

    assert result is None


@pytest.mark.asyncio
async def test_the_ip_budget_is_checked_before_anything(consume_ports) -> None:
    """R3.7 — and before the token is even hashed, so a refused caller costs nothing."""
    consume_ports["throttle"] = InMemoryLoginThrottle(attempts_per_minute=0)
    user = consume_ports["users"].seed(_user())
    token = _seed_token(consume_ports, user)

    with pytest.raises(TooManyAttemptsError):
        await _consume(consume_ports)

    assert token.used_at is None


# --- the happy path (R1.1) ---------------------------------------------------------


@pytest.mark.asyncio
async def test_the_password_is_replaced(ports) -> None:
    user = ports["users"].seed(_user())

    await _change(ports, user)

    assert user.password_hash == f"hashed::{NEW}"
    assert ports["users"].applied[0][2]["password_hash"] == f"hashed::{NEW}"
    assert ports["uow"].commits == 1


@pytest.mark.asyncio
async def test_a_self_chosen_password_is_never_temporary(ports) -> None:
    """R5.3 — completing R1 is one of the two ways out of the must-change state."""
    user = ports["users"].seed(_user(must_change_password=True))

    await _change(ports, user)

    assert user.must_change_password is False
    assert ports["users"].applied[0][2]["must_change_password"] is False


@pytest.mark.asyncio
async def test_the_hash_and_the_flag_are_written_together(ports) -> None:
    """Design D5, and the repository refuses the pair written apart."""
    user = ports["users"].seed(_user())

    await _change(ports, user)

    assert set(ports["users"].applied[0][2]) == {"password_hash", "must_change_password"}


# --- the wrong current password (R1.2) ---------------------------------------------


@pytest.mark.asyncio
async def test_a_wrong_current_password_is_refused(ports) -> None:
    user = ports["users"].seed(_user())

    with pytest.raises(InvalidCredentialsError):
        await _change(ports, user, current="not-the-current-one")


@pytest.mark.asyncio
async def test_a_wrong_current_password_does_not_touch_the_hash(ports) -> None:
    """R1.2 says SHALL NOT modify the hash — checked on the entity AND on the writes."""
    user = ports["users"].seed(_user())

    with pytest.raises(InvalidCredentialsError):
        await _change(ports, user, current="not-the-current-one")

    assert user.password_hash == f"hashed::{CURRENT}"
    assert ports["users"].applied == []
    assert ports["sessions"].revocations == []
    assert ports["audit"].entries == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_a_user_that_no_longer_resolves_answers_like_a_wrong_password(ports) -> None:
    """A token that outlived its account must not be distinguishable from a typo."""
    user = _user()  # deliberately NOT seeded

    with pytest.raises(InvalidCredentialsError):
        await _change(ports, user)


# --- the account lockout (R1.8, design D14) ----------------------------------------


@pytest.mark.asyncio
async def test_a_wrong_current_password_counts_against_the_account(ports) -> None:
    """R1.8: this endpoint verifies a credential, so it must not be the cheap way to guess."""
    user = ports["users"].seed(_user())

    with pytest.raises(InvalidCredentialsError):
        await _change(ports, user, current="wrong")

    assert ports["throttle"].failures[user.id] == 1


@pytest.mark.asyncio
async def test_the_account_locks_after_the_configured_failures(ports) -> None:
    user = ports["users"].seed(_user())

    for _ in range(10):
        with pytest.raises(InvalidCredentialsError):
            await _change(ports, user, current="wrong")

    assert await ports["throttle"].is_account_locked(user.id) is True


@pytest.mark.asyncio
async def test_a_locked_account_is_refused_even_with_the_right_password(ports) -> None:
    user = ports["users"].seed(_user())
    ports["throttle"].locked.add(user.id)

    with pytest.raises(InvalidCredentialsError):
        await _change(ports, user)

    assert ports["users"].applied == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_a_locked_account_is_refused_without_paying_bcrypt(ports) -> None:
    """The half of R1.8 that stops the CPU-exhaustion loop (design D14).

    Past the threshold the request must cost nothing — otherwise the loop keeps holding the
    `CapacityLimiter` that `login` shares, and the lockout would bound the guessing while
    leaving the denial of service intact. Counting hasher calls asserts it deterministically;
    measuring wall time would be flaky.
    """
    counting = CountingPasswordHasher(StubPasswordHasher())
    ports["hasher"] = counting
    user = ports["users"].seed(_user())
    ports["throttle"].locked.add(user.id)

    with pytest.raises(InvalidCredentialsError):
        await _change(ports, user)

    assert counting.expensive_calls == 0


@pytest.mark.asyncio
async def test_a_lockout_is_indistinguishable_from_a_wrong_password(ports) -> None:
    """A distinguishable answer would tell a stolen-token holder they found a real account."""
    locked = ports["users"].seed(_user())
    ports["throttle"].locked.add(locked.id)
    other = ports["users"].seed(_user())

    with pytest.raises(InvalidCredentialsError) as from_lock:
        await _change(ports, locked)
    with pytest.raises(InvalidCredentialsError) as from_wrong:
        await _change(ports, other, current="wrong")

    assert str(from_lock.value) == str(from_wrong.value)


@pytest.mark.asyncio
async def test_a_successful_change_does_not_touch_the_counter(ports) -> None:
    user = ports["users"].seed(_user())

    await _change(ports, user)

    assert user.id not in ports["throttle"].failures
    assert await ports["throttle"].is_account_locked(user.id) is False


@pytest.mark.asyncio
async def test_a_policy_failure_does_not_count_as_a_credential_failure(ports) -> None:
    """The counter is about wrong credentials. A weak new password is the caller's own
    account and their own mistake; counting it would lock people out for typos."""
    user = ports["users"].seed(_user())

    with pytest.raises(PasswordPolicyError):
        await _change(ports, user, new="short")

    assert user.id not in ports["throttle"].failures


# --- an unchanged password (R1.7, design D11) --------------------------------------


@pytest.mark.asyncio
async def test_a_password_identical_to_the_current_one_is_refused(ports) -> None:
    """R1.7: it would revoke every session of the user without rotating anything."""
    user = ports["users"].seed(_user())

    with pytest.raises(PasswordUnchangedError):
        await _change(ports, user, new=CURRENT)

    assert ports["users"].applied == []
    assert ports["sessions"].revocations == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_the_unchanged_check_cannot_be_used_without_the_current_password(
    ports,
) -> None:
    """Order matters: the equality check sits AFTER the verification, so presenting a wrong
    current password answers `InvalidCredentialsError` and never reveals whether the new one
    happened to match what is stored."""
    user = ports["users"].seed(_user())

    with pytest.raises(InvalidCredentialsError):
        await _change(ports, user, current="wrong", new="wrong")


# --- the policy (R1.5) -------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_password_under_the_minimum_is_refused(ports) -> None:
    user = ports["users"].seed(_user())

    with pytest.raises(PasswordPolicyError):
        await _change(ports, user, new="short")

    assert ports["users"].applied == []
    assert ports["uow"].commits == 0


@pytest.mark.asyncio
async def test_a_password_over_the_byte_limit_is_refused(ports) -> None:
    user = ports["users"].seed(_user())

    with pytest.raises(PasswordTooLongError):
        await _change(ports, user, new="€" * 25)

    assert ports["users"].applied == []


@pytest.mark.asyncio
async def test_the_policy_runs_after_the_current_password_is_verified(ports) -> None:
    """A weak new password must not be diagnosable without the current one."""
    user = ports["users"].seed(_user())

    with pytest.raises(InvalidCredentialsError):
        await _change(ports, user, current="wrong", new="short")


# --- session revocation (R1.3) -----------------------------------------------------


@pytest.mark.asyncio
async def test_every_session_of_the_user_is_revoked(ports) -> None:
    """R1.3, including the family that made this very call."""
    user = ports["users"].seed(_user())

    await _change(ports, user)

    assert ports["sessions"].revocations == [
        (TENANT, user.id, SessionRevokedReason.PASSWORD_RESET)
    ]


@pytest.mark.asyncio
async def test_the_revocation_reason_is_password_reset(ports) -> None:
    user = ports["users"].seed(_user())

    await _change(ports, user)

    assert ports["sessions"].revocations[0][2] is SessionRevokedReason.PASSWORD_RESET


# --- the audit row (R4.3, R4.4, design D9) -----------------------------------------


@pytest.mark.asyncio
async def test_it_audits_under_its_own_action(ports) -> None:
    """Design D9: distinguishable from an administrator's reset by `action` alone."""
    user = ports["users"].seed(_user())

    await _change(ports, user)

    _tenant, entry = ports["audit"].entries[0]
    assert entry.action == actions.USER_PASSWORD_CHANGED
    assert entry.action != actions.USER_PASSWORD_RESET


@pytest.mark.asyncio
async def test_the_actor_is_the_user_itself(ports) -> None:
    user = ports["users"].seed(_user())

    await _change(ports, user)

    _tenant, entry = ports["audit"].entries[0]
    assert entry.actor_user_id == user.id
    assert entry.entity_id == user.id
    assert entry.actor_ip == IP


@pytest.mark.asyncio
async def test_neither_password_reaches_the_audit_row(ports) -> None:
    """R4.3 — not the new one, not the presented one, in no reversible or masked form."""
    user = ports["users"].seed(_user())

    await _change(ports, user)

    _tenant, entry = ports["audit"].entries[0]
    recorded = str(entry.changes)
    assert NEW not in recorded
    assert CURRENT not in recorded
    assert f"hashed::{NEW}" not in recorded
    assert entry.changes == {"password": {"changed": True}}


@pytest.mark.asyncio
async def test_leaving_the_temporary_state_is_recorded_as_a_diff(ports) -> None:
    """Design D9: the flag is a boolean of state, so it is auditable as a real diff."""
    user = ports["users"].seed(_user(must_change_password=True))

    await _change(ports, user)

    _tenant, entry = ports["audit"].entries[0]
    assert entry.changes["must_change_password"] == {"old": True, "new": False}


@pytest.mark.asyncio
async def test_an_ordinary_rotation_does_not_record_a_field_that_did_not_change(
    ports,
) -> None:
    user = ports["users"].seed(_user(must_change_password=False))

    await _change(ports, user)

    _tenant, entry = ports["audit"].entries[0]
    assert "must_change_password" not in entry.changes


@pytest.mark.asyncio
async def test_a_failed_audit_write_leaves_the_password_unchanged(ports) -> None:
    """The single-commit contract: the trail and the change stand or fall together."""
    ports["audit"].fail = True
    user = ports["users"].seed(_user())

    with pytest.raises(RuntimeError):
        await _change(ports, user)

    assert ports["uow"].commits == 0
