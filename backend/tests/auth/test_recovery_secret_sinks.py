"""The recovery token and the password reach NO sink (R4.1, R4.2, R4.3, R4.5).

R4.5 asks for this file by name: the contract of rule 11 of `steering/security.md` "lo hereda
el change que primero escribe en cada una, con su propio test", and here the new writer is
this change. So the whole R2→R3 flow runs against real Postgres and real repositories, and
then **every sink is read back and searched** for the two secrets:

1. `password_reset_tokens` — the row must not permit reconstructing the token (R4.1).
2. `notification_logs.subject` / `body` — rule 11's one exception is the masked `****XX` of an
   access code, and a live recovery link is not that (R4.2).
3. `audit_logs.changes` — structured form only (R4.3).
4. The application log (R4.3, R2.6).
5. Every API response body along the way (R4.3).

**Searched with the real generated values**, never with a literal: a test that greps for
`"secret"` proves nothing about a token that is 43 characters of base64. And searched for
fragments too, because half a token is still a lead.

And searched for **two** tokens, not one: the seeded token that R3 consumes and the token the
R2 call emits, captured through the `emitted_token` fixture. Sinks 2 and 4 are written by the
R2 path, so checking them against the seeded token alone left them blind to the only token that
path can leak.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.recovery_tokens import generate_recovery_token
from app.auth.infrastructure.models import PasswordResetTokenModel
from app.notifications.infrastructure.models import NotificationLogModel
from tests.auth.conftest import PASSWORD, insert_user

NEW_PASSWORD = "a-brand-new-recovered-passphrase"

# Long enough that a coincidental match is not credible, short enough that a partial leak is
# still caught. A token is 43 url-safe characters, so this slides 36 windows over it.
FRAGMENT = 8


def _fragments(secret: str) -> list[str]:
    return [secret[i : i + FRAGMENT] for i in range(len(secret) - FRAGMENT + 1)]


def _assert_absent(haystack: str, secret: str, *, sink: str) -> None:
    assert secret not in haystack, f"{sink} contains the secret verbatim"
    for fragment in _fragments(secret):
        assert fragment not in haystack, f"{sink} contains the fragment {fragment!r}"


async def _seed_link(db_session, tenant):
    """A token whose cleartext the test knows.

    The production flow deliberately makes the cleartext unobservable — it exists only inside
    the request that mails it (design D2) — which is the very property under test. So the
    token is seeded here instead, with a real `generate_recovery_token()` value.
    """
    user = await insert_user(db_session, tenant=tenant)
    cleartext, token_hash = generate_recovery_token()
    db_session.add(
        PasswordResetTokenModel(
            tenant_id=tenant.id,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )
    await db_session.flush()
    return user, cleartext


def test_the_detector_detects() -> None:
    """R4.5 asks for these criteria to be RED before they are believed.

    They are green, so the honest equivalent is to prove the instrument works: plant each
    kind of leak this file searches for and confirm `_assert_absent` refuses it. Without
    this, five absence assertions could all be passing because the search is broken — which
    is the failure mode this change has already hit twice with structural guards elsewhere.
    """
    secret, _ = generate_recovery_token()

    # A clean sink passes.
    _assert_absent("nothing to see here", secret, sink="control")

    # The whole secret is caught.
    with pytest.raises(AssertionError, match="verbatim"):
        _assert_absent(f"body with {secret} in it", secret, sink="planted")

    # And so is a fragment, because half a token is still a lead.
    with pytest.raises(AssertionError, match="fragment"):
        _assert_absent(f"body with {secret[:12]} in it", secret, sink="planted fragment")

    # A fragment shorter than the window is genuinely not searched for, and that is a
    # deliberate limit rather than an oversight: at 4 characters of base64 a coincidental
    # match in ordinary JSON is likely, and a test that cries wolf gets deleted.
    _assert_absent(f"body with {secret[:4]} in it", secret, sink="below the window")


@pytest.fixture
def emitted_token(monkeypatch):
    """The cleartext the R2 writer actually produces, captured as it is produced.

    Design D2 makes it unobservable on purpose — it exists only inside the request that mails
    it — and that is why this fixture exists rather than a second `_seed_link`. Without it the
    sink searches below run against the SEEDED token only, and the two sinks the *writer*
    touches (`notification_logs`, the application log) would stay green even if
    `RequestPasswordResetUseCase` wrote `render_recovery_email`'s output straight into the row.
    The review panel found exactly that gap.

    Patched where `recovery.py` looked the name up, not where it is defined: it imported the
    function, so rebinding the domain module would leave the use case pointing at the original.
    """
    captured: list[str] = []
    real = generate_recovery_token

    def capturing() -> tuple[str, str]:
        cleartext, token_hash = real()
        captured.append(cleartext)
        return cleartext, token_hash

    monkeypatch.setattr(
        "app.auth.application.recovery.generate_recovery_token", capturing
    )
    return captured


def test_the_capture_captures(emitted_token) -> None:
    """The guard on the fixture: an empty list would make every check that uses it vacuous.

    Calling the patched name the way the use case does must land a value in the list, and the
    value must be the one the caller received.
    """
    from app.auth.application import recovery

    cleartext, token_hash = recovery.generate_recovery_token()

    assert emitted_token == [cleartext]
    assert token_hash != cleartext


@pytest.mark.asyncio
async def test_the_token_reaches_no_sink_across_the_whole_flow(
    api, db_session, tenant_a, caplog, emitted_token
) -> None:
    """R4.1, R4.2, R4.3 in one pass over the flow R2→R3."""
    user, cleartext = await _seed_link(db_session, tenant_a)
    responses: list[str] = []

    with caplog.at_level("DEBUG"):
        responses.append((await api.post(
            "/api/v1/auth/forgot-password", json={"email": user.email}
        )).text)
        responses.append((await api.post(
            "/api/v1/auth/reset-password",
            json={"token": cleartext, "new_password": NEW_PASSWORD},
        )).text)
        responses.append((await api.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": NEW_PASSWORD},
        )).text)

    # BOTH secrets, and that is the point: the seeded one is what R3 consumes, the emitted one
    # is what R2 wrote. Sinks 2 and 4 belong to the writer, so searching them for the seeded
    # token alone would prove nothing about the token that actually travelled.
    assert emitted_token, "forgot-password issued no token, so half of this test is vacuous"
    secrets = [cleartext, *emitted_token]

    # 1. the token table
    rows = (await db_session.execute(select(PasswordResetTokenModel))).scalars().all()
    assert rows, "the flow wrote no token row, so this test proves nothing"
    haystack = "\n".join(f"{r.token_hash}{r.id}{r.user_id}" for r in rows)
    for secret in secrets:
        _assert_absent(haystack, secret, sink="password_reset_tokens")

    # 2. notification_logs.subject / body — rule 11's columns
    logs = (await db_session.execute(select(NotificationLogModel))).scalars().all()
    haystack = "\n".join(
        f"{r.subject or ''}\n{r.body or ''}\n{r.last_error or ''}" for r in logs
    )
    for secret in secrets:
        _assert_absent(haystack, secret, sink="notification_logs")

    # 3. audit_logs.changes
    audits = (await db_session.execute(select(AuditLogModel))).scalars().all()
    assert audits, "the recovery wrote no audit row (R4.4), so sink 3 is untested"
    haystack = "\n".join(str(r.changes) for r in audits)
    for secret in secrets:
        _assert_absent(haystack, secret, sink="audit_logs.changes")

    # 4. the application log
    assert caplog.records, (
        "nothing was logged during the flow, so sink 4 would pass on an empty haystack"
    )
    logged = "\n".join(
        record.getMessage() + str(record.__dict__) for record in caplog.records
    )
    for secret in secrets:
        _assert_absent(logged, secret, sink="the application log")

    # 5. every response body
    haystack = "\n".join(responses)
    for secret in secrets:
        _assert_absent(haystack, secret, sink="an API response")


@pytest.mark.asyncio
async def test_neither_password_reaches_any_sink(api, db_session, tenant_a, caplog) -> None:
    """R4.3 — the new password AND the one presented, in no reversible or masked form.

    The stored bcrypt hash is not a leak: it is the point of storing a hash. What must not
    appear anywhere is the cleartext.
    """
    user, cleartext = await _seed_link(db_session, tenant_a)
    responses: list[str] = []

    with caplog.at_level("DEBUG"):
        responses.append((await api.post(
            "/api/v1/auth/reset-password",
            json={"token": cleartext, "new_password": NEW_PASSWORD},
        )).text)
        # And the R1 path, whose body carries BOTH passwords.
        logged_in = (await api.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": NEW_PASSWORD},
        )).json()
        responses.append((await api.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": NEW_PASSWORD,
                "new_password": "a-third-distinct-passphrase",
            },
            headers={"Authorization": f"Bearer {logged_in['access_token']}"},
        )).text)

    sinks = []
    sinks += [
        f"{r.token_hash}" for r in (await db_session.execute(select(PasswordResetTokenModel))).scalars().all()
    ]
    sinks += [
        f"{r.subject or ''}{r.body or ''}{r.last_error or ''}"
        for r in (await db_session.execute(select(NotificationLogModel))).scalars().all()
    ]
    sinks += [
        str(r.changes) for r in (await db_session.execute(select(AuditLogModel))).scalars().all()
    ]
    sinks += [record.getMessage() + str(record.__dict__) for record in caplog.records]
    sinks += responses
    haystack = "\n".join(sinks)

    for secret in (NEW_PASSWORD, "a-third-distinct-passphrase", PASSWORD):
        _assert_absent(haystack, secret, sink="one of the five sinks")


@pytest.mark.asyncio
async def test_the_audit_row_records_the_recovery_without_carrying_it(
    api, db_session, tenant_a
) -> None:
    """R4.4 — the trail must exist, or the absence tests above pass vacuously."""
    from app.audit.domain import actions

    user, cleartext = await _seed_link(db_session, tenant_a)

    await api.post(
        "/api/v1/auth/reset-password",
        json={"token": cleartext, "new_password": NEW_PASSWORD},
    )

    row = (
        await db_session.execute(
            select(AuditLogModel).where(
                AuditLogModel.action == actions.USER_PASSWORD_RECOVERED
            )
        )
    ).scalar_one()
    assert row.entity_id == user.id
    assert row.actor_user_id == user.id
    assert row.changes == {"password": {"changed": True}}


@pytest.mark.asyncio
async def test_the_flow_really_ran(api, db_session, tenant_a) -> None:
    """The guard against the whole file being vacuous.

    Every test above asserts an ABSENCE, and absences pass when nothing happened. This one
    asserts the flow's observable effects, so a broken endpoint cannot make the sink tests
    green by doing nothing at all.
    """
    user, cleartext = await _seed_link(db_session, tenant_a)

    forgot = await api.post("/api/v1/auth/forgot-password", json={"email": user.email})
    reset = await api.post(
        "/api/v1/auth/reset-password",
        json={"token": cleartext, "new_password": NEW_PASSWORD},
    )

    assert forgot.status_code == 202
    assert reset.status_code == 204
    assert (
        await api.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": NEW_PASSWORD},
        )
    ).status_code == 200
    # And the notification row the R2 call wrote really exists, so sink 2 had something in it.
    assert (
        await db_session.execute(
            select(NotificationLogModel).where(
                NotificationLogModel.notification_type == "PASSWORD_RESET_REQUESTED"
            )
        )
    ).scalars().all()
