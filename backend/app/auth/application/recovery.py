"""Self-service password change and recovery (`auth-account-recovery` R1, R2, R3).

One use case is one business operation and one transaction, exactly as in `user_admin.py`:
each orchestrates entities and ports and calls `commit()` once. No business rule lives here —
the policy is in `app/auth/domain/password_policy.py`, the token shape in
`recovery_tokens.py`, the two message texts in `recovery_messages.py` — and no `sqlalchemy`
import either, which `tests/test_layering.py` enforces for this layer.
"""

import logging
import uuid
from datetime import datetime, timedelta

from app.audit.domain import actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.auth.domain.entities import PasswordResetToken
from app.auth.domain.enums import SessionRevokedReason, UserStatus
from app.auth.domain.exceptions import (
    InvalidCredentialsError,
    InvalidRecoveryTokenError,
    TooManyAttemptsError,
)
from app.auth.domain.password_policy import (
    assert_password_acceptable,
    assert_password_changed,
)
from app.auth.domain.ports import (
    LoginThrottle,
    PasswordHasher,
    PasswordResetTokenRepository,
    SessionRepository,
    UnitOfWork,
    UserRepository,
)
from app.auth.domain.recovery_messages import (
    STORED_RECOVERY_BODY,
    STORED_RECOVERY_SUBJECT,
    render_recovery_email,
)
from app.auth.domain.recovery_tokens import generate_recovery_token, hash_recovery_token
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import (
    NotificationChannel,
    NotificationStatus,
    NotificationType,
)
from app.notifications.domain.ports import NotificationAdapter
from app.notifications.domain.repositories import NotificationLogRepository
from app.notifications.domain.results import NotificationErrorCode, NotificationResult

logger = logging.getLogger("app.auth")


class _AuditWriter:
    """Builds and appends an audit entry, so no use case constructs one by hand.

    Modelled on `user_admin._AuditWriter` (its design D2) but NOT identical: `entity_type` is
    fixed to `ENTITY_USER` here rather than taken as a parameter, because every operation in
    this module audits a user and a parameter with one possible value is a parameter somebody
    will eventually pass wrongly.

    Duplicated rather than shared across the two modules: `user_admin` owns administration
    and this owns self-service, and a common helper between two callers would be the first
    thread of an `application/common.py` that nothing else needs yet
    (`steering/backend-architecture.md` §"Cuándo simplificar").
    """

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        actor_ip: str | None,
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=actions.ENTITY_USER,
                entity_id=entity_id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=changes,
                now=now,
            ),
        )


class RequestPasswordResetUseCase:
    """Anonymous request for a recovery link (R2, design D2/D7).

    **Every path through `execute` returns None and looks identical from outside.** That is
    R2.2, and it is the whole shape of this class: an unknown address, an inactive user, an
    inactive tenant and an account that already holds its quota of live links all leave
    without emitting a token or writing a row, and the caller cannot tell which happened.
    The alternative is an anonymous user-enumerator exposed to the internet, which is the
    same reasoning `auth-tenancy` used to make the five login failures indistinguishable.
    """

    def __init__(
        self,
        *,
        users: UserRepository,
        tokens: PasswordResetTokenRepository,
        notifications: NotificationLogRepository,
        adapters: "dict[NotificationChannel, NotificationAdapter]",
        throttle: LoginThrottle,
        uow: UnitOfWork,
        token_minutes: int,
        max_live_tokens: int,
        grace_minutes: int,
        frontend_base_url: str,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._notifications = notifications
        self._adapters = adapters
        self._throttle = throttle
        self._uow = uow
        self._token_minutes = token_minutes
        self._max_live_tokens = max_live_tokens
        self._grace_minutes = grace_minutes
        self._frontend_base_url = frontend_base_url

    async def _deliver(
        self, recipient: str, subject: str, body: str
    ) -> NotificationResult:
        """Hand the mail to the `EMAIL` adapter, and ALWAYS come back with a result.

        Two failure shapes are collapsed here on purpose, and both were named by the panels
        of section 6:

        - **No adapter registered for `EMAIL`.** A configuration error in practice — the
          registry always has one — but it gets `NO_ADAPTER_FOR_CHANNEL`, the code the
          dispatcher's own `_skip_unroutable` already uses for exactly this, rather than a
          `FAILED` row with no reason. D2 says a `FAILED` row carries "su
          `NotificationErrorCode`"; one with `last_error=None` did not.
        - **The adapter raised.** `NotificationAdapter.send` promises never to raise for a
          delivery failure, so an exception means the adapter broke its own contract. It is
          still converted to a value HERE, because letting it propagate would answer `500`
          on the path where the address resolves while an unknown address still answers
          `202` — a clean, non-statistical enumeration oracle, and a worse one than the
          latency difference R2.2's risk note already accepts. Today unreachable
          (`ConsoleEmailAdapter` fails by value); the day SMTP lands it is live, so the
          guard goes in now rather than into the handover note.
        """
        adapter = self._adapters.get(NotificationChannel.EMAIL)
        if adapter is None:
            logger.warning(
                "auth.password_reset_no_email_adapter",
                extra={"channel": NotificationChannel.EMAIL.value},
            )
            return NotificationResult.failure(
                NotificationErrorCode.NO_ADAPTER_FOR_CHANNEL
            )
        try:
            return await adapter.send(
                recipient_contact=recipient,
                subject=subject,
                body=body,
                channel=NotificationChannel.EMAIL,
            )
        except Exception as exc:
            # No detail from the exception reaches the row: `last_error` takes a
            # `NotificationErrorCode` and nothing else, which is rule 11's structured form
            # enforced by the type.
            #
            # And **no traceback either**. An earlier version called `logger.exception` here
            # with the note "`exc_info` goes to the log, which is ours" — which inverts R2.6:
            # that requirement constrains our own application log precisely BECAUSE it is
            # ours, and it forbids the email in it. Adapter exceptions on this path carry the
            # recipient by construction — `smtplib.SMTPRecipientsRefused` is keyed by
            # recipient, and server text conventionally echoes the address — so `exc_info`
            # would turn the log into a record of which addresses have accounts, reachable by
            # anyone with log access. The class name and the error code say what an operator
            # needs; a full trace belongs to the adapter, which is the layer that is not
            # holding the address as an argument. Found by the security panel of section 6,
            # in the very fix that closed its previous finding.
            logger.warning(
                "auth.password_reset_adapter_raised",
                extra={"adapter_error": type(exc).__name__},
            )
            return NotificationResult.failure(NotificationErrorCode.ADAPTER_ERROR)

    async def execute(self, *, email: str, client_ip: str, now: datetime) -> None:
        """Emit a link if the address resolves to an account that may have one (R2).

        Returns None in every case except a rate limit, which raises. The router answers the
        same `202` for every non-raising path.
        """
        # R2.4: the SAME per-IP counter `login` and `refresh` use, checked BEFORE the address
        # is resolved. Sharing the bucket is the point — a separate budget would let one
        # caller spend two from the same address, which is exactly the reasoning that put
        # `refresh` in login's counter. Checking it first also means an unresolvable address
        # costs no database work.
        #
        # This is the ONE path that does not answer `202`. It is not an R2.2 leak: `429`
        # describes the caller's own rate, not whether the address exists, and it arrives
        # before anything has been looked up.
        if not await self._throttle.ip_attempt_allowed(client_ip):
            logger.warning("Password reset rate limit exceeded for ip=%s", client_ip)
            raise TooManyAttemptsError("Too many password reset requests")

        user = await self._users.find_by_email_globally(email)
        if user is None or user.status is not UserStatus.ACTIVE:
            # R2.6: the log records the OUTCOME, never the address — not even hashed, which
            # would still correlate two requests for the same person.
            logger.info("auth.password_reset_requested", extra={"resolved": False})
            return

        tenant_active = await self._users.get_active_by_id(user.tenant_id, user.id)
        if tenant_active is None:
            # `get_active_by_id` joins the tenant and requires BOTH to be ACTIVE, so this is
            # how "the tenant is suspended" is detected without a second port. Same silent
            # exit as above.
            logger.info("auth.password_reset_requested", extra={"resolved": False})
            return

        # R2.5 / design D7 (amended in `run`): the cap bounds how many links coexist, and it
        # does so by revoking the OLDEST rather than by dropping the request. Dropping it made
        # the cap a suppression tool — anyone who knew an address could spend three requests
        # and silence the real owner's recovery for the token lifetime, with no signal to them
        # by R2.2, which is exactly the capability this change exists to provide.
        #
        # `keep_newest = cap - 1` because one is about to be issued, so the account lands on
        # the cap and never above it — **sequentially**. This is check-then-act with no lock:
        # the QA panel of section 6 measured 8 concurrent requests producing 8 live tokens
        # against a cap of 3. Accepted, with the reasoning in design D7 ("La cota es
        # «check-then-act»…"): the per-IP budget of R2.4 is what bounds volume, extra
        # coexisting links do not help guess a 256-bit token, and a lock on anonymous surface
        # is a contention point anyone can take. Said here as well as there because a reader
        # of this function alone would otherwise believe the bound is absolute.
        live = await self._tokens.count_live(user.tenant_id, user.id, now)
        revoked = 0
        if live >= self._max_live_tokens:
            revoked = await self._tokens.revoke_oldest_beyond(
                user.tenant_id,
                user.id,
                max(self._max_live_tokens - 1, 0),
                now,
                now - timedelta(minutes=self._grace_minutes),
            )
            if revoked == 0:
                # Every live link is inside the grace window, so nothing may be retired and
                # this request sends nothing (R2.5, design D7's grace amendment). Same silent
                # return as the other refused paths, so R2.2 still holds. This is what keeps
                # per-account mail bounded across IPs — a per-IP budget cannot do it — and it
                # is also what makes the link just mailed to the owner unrevokable while they
                # are reading it.
                logger.info(
                    "auth.password_reset_requested",
                    extra={
                        "resolved": True,
                        "emitted": False,
                        "reason": "all_live_links_within_grace",
                    },
                )
                return

        cleartext, token_hash = generate_recovery_token()
        token = PasswordResetToken(
            id=uuid.uuid4(),
            tenant_id=user.tenant_id,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=now + timedelta(minutes=self._token_minutes),
            created_at=now,
            updated_at=now,
        )
        await self._tokens.add(user.tenant_id, token)

        # Design D2, the hardest constraint of this change. The link is handed to the adapter
        # HERE, inside the request, because it cannot outlive it: writing it to
        # `notification_logs.subject`/`body` is forbidden by rule 11 of
        # `steering/security.md`, and parking it anywhere recoverable is forbidden by R4.1.
        # So what is SENT and what is STORED are two different texts from two different
        # functions, and the stored one takes no argument that could carry a link.
        subject, body = render_recovery_email(
            f"{self._frontend_base_url.rstrip('/')}/reset-password?token={cleartext}"
        )
        result = await self._deliver(user.email, subject, body)

        await self._notifications.add(
            user.tenant_id,
            NotificationLog(
                id=uuid.uuid4(),
                tenant_id=user.tenant_id,
                recipient_user_id=user.id,
                recipient_contact=user.email,
                channel=NotificationChannel.EMAIL,
                notification_type=NotificationType.PASSWORD_RESET_REQUESTED.value,
                created_at=now,
                updated_at=now,
                # The STORED texts: constants, no link, no token (R4.2).
                subject=STORED_RECOVERY_SUBJECT,
                body=STORED_RECOVERY_BODY,
                # Never `PENDING`, and this is the detail that decides correctness (D2):
                # `PENDING` is the dispatcher's queue, so the row would be picked up on the
                # next tick and delivered using the STORED body — mailing the user a notice
                # with no link in it. The adapter has already answered, so the final state is
                # also the honest one.
                status=(
                    NotificationStatus.SENT if result.delivered else NotificationStatus.FAILED
                ),
                attempts=1,
                sent_at=now if result.delivered else None,
                last_error=(
                    None if result.delivered else result.error_code.value  # type: ignore[union-attr]
                ),
                # R6.2: no deadline, so `escalation_for` returns None and the SLA job leaves
                # it alone. There is no promise to miss in a recovery.
                sla_deadline_at=None,
            ),
        )
        await self._uow.commit()
        logger.info(
            "auth.password_reset_requested",
            extra={
                "resolved": True,
                "emitted": True,
                "delivered": result.delivered,
                # How many older links this request retired. Non-zero means the account was at
                # its cap, which is worth seeing in aggregate — it is the signal that somebody
                # is provoking mail against one address.
                "revoked_older": revoked,
            },
        )


class ConsumePasswordResetUseCase:
    """Spend a recovery link and set a new password (R3, design D10/D8/D11).

    Anonymous: the token IS the credential, so there is no context to derive a tenant from —
    it comes out of the row `consume_globally` returns (design D3).
    """

    def __init__(
        self,
        *,
        users: UserRepository,
        tokens: PasswordResetTokenRepository,
        sessions: SessionRepository,
        audit: AuditLogRepository,
        hasher: PasswordHasher,
        throttle: LoginThrottle,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._tokens = tokens
        self._sessions = sessions
        self._audit = _AuditWriter(audit)
        self._hasher = hasher
        self._throttle = throttle
        self._uow = uow

    async def execute(
        self, *, token: str, new_password: str, client_ip: str, now: datetime
    ) -> None:
        """Consume the token, replace the hash, and clear what blocked the account (R3).

        **The order is design D10 and every step earns its place:**

        1. Per-IP budget, before the token is even hashed (R3.7).
        2. The password policy — pure, no I/O. Before the database, so a weak password does
           not burn a token; and before bcrypt, so an anonymous caller with no token cannot
           make us spend 250 ms of CPU. That ordering is what keeps this endpoint from being
           a CPU mill for someone who has nothing.
        3. `consume_globally` — ONE conditional statement (R3.2). Consuming BEFORE validating
           the account means a token presented against a deactivated user is burned. That is
           deliberate (D10): a presented link is a spent link, and checking the account first
           reintroduces the read-then-write race R3.2 forbids.
        4. Load the user. If it does not resolve — inactive user, inactive tenant — the same
           indistinguishable error as every other failure (R3.3).
        5. Write, audit, revoke sessions, invalidate sibling links, commit.
        6. Clear the account lock **after** the commit, and never let its failure undo the
           reset (D8).

        No session tokens come back (R3.6): possession of a link must not become a session
        without presenting a credential. The holder logs in afterwards.
        """
        if not await self._throttle.ip_attempt_allowed(client_ip):
            logger.warning("Password reset consumption rate limit exceeded for ip=%s", client_ip)
            raise TooManyAttemptsError("Too many password reset attempts")

        # Step 2 — pure, and deliberately ahead of everything that costs anything.
        assert_password_acceptable(new_password)

        consumed = await self._tokens.consume_globally(hash_recovery_token(token), now)
        if consumed is None:
            # Unknown, already used, expired or revoked — one error for all of them (R3.3).
            raise InvalidRecoveryTokenError()

        user = await self._users.get_active_by_id(consumed.tenant_id, consumed.user_id)
        if user is None:
            # The account or its tenant stopped being ACTIVE. The token is already spent, and
            # that is the accepted consequence of D10's ordering.
            raise InvalidRecoveryTokenError()

        # R1.7 is NOT applied here, and design D11 says why: there is no current password
        # presented, and finding out would cost a bcrypt `verify` on anonymous surface. The
        # asymmetry is deliberate — what R1.7 prevents is revoking every session without
        # rotating anything, and somebody completing a recovery wants those sessions gone.
        was_temporary = user.must_change_password
        user.set_password_hash(await self._hasher.hash(new_password), temporary=False)

        await self._users.apply_changes(
            consumed.tenant_id,
            consumed.user_id,
            {
                "password_hash": user.password_hash,
                "must_change_password": user.must_change_password,
            },
        )

        changes = ChangeSet(actions.ENTITY_USER).redacted("password")
        if was_temporary:
            changes = changes.diff("must_change_password", True, False)
        await self._audit.record(
            tenant_id=consumed.tenant_id,
            action=actions.USER_PASSWORD_RECOVERED,
            entity_id=user.id,
            # The actor IS the user: they proved possession of a link sent to their own
            # address, and that is the only identity this path has (design D9).
            actor_user_id=user.id,
            actor_ip=client_ip,
            changes=changes,
            now=now,
        )

        await self._sessions.revoke_all_for_user(
            consumed.tenant_id, consumed.user_id, SessionRevokedReason.PASSWORD_RESET, now
        )
        # R3.5(b): the other live links of this account die too, so a recovery does not leave
        # spare credentials behind. `keep_id` is the one just consumed — it is `used`, not
        # `revoked`, and relabelling it would lose the distinction.
        await self._tokens.revoke_other_live(
            consumed.tenant_id, consumed.user_id, consumed.id, now
        )
        await self._uow.commit()

        # R3.5(c), and design D8 decides the ordering. Redis and Postgres share no
        # transaction, so one of the two has to be able to fail alone. Clearing BEFORE the
        # commit would unlock an account whose password never changed; clearing after leaves,
        # at worst, a lock that expires on its own in fifteen minutes over an account that is
        # already recovered. The second is the benign degradation, so the failure is logged
        # and swallowed rather than turned into a `500` for a reset that did land.
        try:
            await self._throttle.clear_account_lock(user.id)
        except Exception:
            logger.warning(
                "auth.password_reset_lock_not_cleared",
                extra={"user_id": str(user.id)},
            )


class ChangeOwnPasswordUseCase:
    """The holder rotates their own credential (R1).

    The subject is never named by the request: it comes from the authenticated context, so
    there is no body field that could point at somebody else (R1.4).
    """

    def __init__(
        self,
        *,
        users: UserRepository,
        sessions: SessionRepository,
        audit: AuditLogRepository,
        hasher: PasswordHasher,
        throttle: LoginThrottle,
        uow: UnitOfWork,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._audit = _AuditWriter(audit)
        self._hasher = hasher
        self._throttle = throttle
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        actor_ip: str | None,
        current_password: str,
        new_password: str,
        now: datetime,
    ) -> None:
        """Replace the caller's own password (R1.1, R1.2, R1.3, R1.5, R1.7).

        The order is deliberate and each step earns its place:

        1. Load the user. Absent means the token outlived the account, which is the same
           `401` a wrong password gets — there is nothing here for an attacker to learn.
        2. Refuse outright if the account is already locked (R1.8, design D14), BEFORE
           spending a bcrypt. That ordering is the whole point: past the threshold the
           request costs nothing, which is what stops a wrong-password loop from holding
           the `CapacityLimiter` that `login` shares.
        3. Verify the CURRENT password before anything else is decided. R1.2 requires the
           hash to be untouched when it is wrong, and doing this first means no later step
           can have written by then. A failure is counted against the SAME per-account
           counter `login` uses (R1.8): this endpoint verifies a credential exactly as
           `login` does, so exempting it would make it the cheaper way to guess — no
           lockout, no counter, no trace.
        4. Refuse a new password identical to the current one (R1.7, design D11), through
           `assert_password_changed` — the rule lives in `domain/` beside its sibling, not
           as an `if` here. It runs AFTER the verification so it cannot be used as an
           oracle: without a correct current password there is no way to reach it.
        5. Only then the policy, then the hash.
        """
        user = await self._users.get_active_by_id(tenant_id, user_id)
        if user is None:
            raise InvalidCredentialsError("Invalid email or password")

        # The same RESPONSE a wrong password gets — code, body and headers — on purpose: a
        # distinguishable "you are locked" would tell the holder of a stolen token that they
        # had found a real account and merely have to wait (R1.8).
        #
        # The LATENCY differs, and that is deliberate rather than overlooked: this branch
        # skips the bcrypt below, which is exactly what stops a wrong-password loop from
        # holding the `CapacityLimiter` that `login` shares. Paying the hash here to level
        # the timing would reopen what D14 exists to close, and the bit it leaks is one the
        # caller gets anyway on noticing the correct password also fails.
        if await self._throttle.is_account_locked(user_id):
            raise InvalidCredentialsError("Invalid email or password")

        if not await self._hasher.verify(current_password, user.password_hash):
            await self._throttle.record_failure(user_id)
            raise InvalidCredentialsError("Invalid email or password")

        assert_password_changed(new_password, current_password)
        assert_password_acceptable(new_password)

        was_temporary = user.must_change_password
        user.set_password_hash(await self._hasher.hash(new_password), temporary=False)

        await self._users.apply_changes(
            tenant_id,
            user_id,
            {
                "password_hash": user.password_hash,
                "must_change_password": user.must_change_password,
            },
        )

        # Neither the password nor its hash: only that it changed (R4.3). `must_change_password`
        # goes in as a real diff and only when it moved, so an ordinary rotation does not record
        # a field that did not change (design D9).
        changes = ChangeSet(actions.ENTITY_USER).redacted("password")
        if was_temporary:
            changes = changes.diff("must_change_password", True, False)
        await self._audit.record(
            tenant_id=tenant_id,
            action=actions.USER_PASSWORD_CHANGED,
            entity_id=user.id,
            actor_user_id=user.id,
            actor_ip=actor_ip,
            changes=changes,
            now=now,
        )

        # EVERY family, including the one that made this call (R1.3). A password change that
        # leaves the previous sessions alive has not rotated the credential, it has added a
        # second one — and the caller is told to log in again, which is the honest outcome.
        await self._sessions.revoke_all_for_user(
            tenant_id, user_id, SessionRevokedReason.PASSWORD_RESET, now
        )
        await self._uow.commit()
