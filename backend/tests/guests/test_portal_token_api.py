"""Minting and revoking the guest's portal token over HTTP (R1.1, R1.4, R1.5, R6.1; D14).

The assertions that carry the weight are about **the one secret this codebase is allowed to
return**: rule 3(a) of `steering/security.md` permits it once at creation and never on a later
read, so the tests that matter most are the ones proving there *is* no later read.
"""

import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.models import AuditLogModel
from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.domain.enums import UserRole
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.guests.domain.portal_token import hash_guest_token
from app.guests.infrastructure.models import GuestAccessTokenModel
from app.main import create_app
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from tests.route_walk import flatten_routes
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "f" * 64


@pytest_asyncio.fixture
async def api(db_session):
    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    async def _session_override():
        yield db_session

    app.dependency_overrides[get_db_session] = _session_override
    app.dependency_overrides[get_token_codec] = lambda: codec
    app.dependency_overrides[get_password_hasher] = lambda: BcryptPasswordHasher(
        rounds=TEST_BCRYPT_ROUNDS
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        # Exposed so a test can enumerate the real routing table rather than a list somebody
        # remembered to keep current — see `test_no_later_read_returns_the_token`.
        client.fastapi_app = app  # type: ignore[attr-defined]
        yield client


def auth_header(client, user: UserModel) -> dict[str, str]:
    token = client.codec.issue_access(  # type: ignore[attr-defined]
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        family_id=uuid.uuid4(),
        now=utc_now(),
    )
    return {"Authorization": f"Bearer {token}"}


async def _stay(db_session, tenant) -> ReservationModel:
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="REDES11",
        internal_code=f"C{uuid.uuid4().hex[:6]}",
        pms_external_id=f"PMS-{uuid.uuid4().hex[:6]}",
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        # The **enum** and not the string `"DIRECT"` that most fixtures in this suite use, and
        # this is the one file where the difference bites. `test_no_later_read_returns_the_token`
        # walks every `GET` the application exposes, so it is the only test that drives another
        # domain's serialiser over this row — and `dashboard-api`'s reservation block reads
        # `reservation.channel.value`, which is an `AttributeError` when the object still holds
        # the raw string the fixture assigned. SQLAlchemy coerces on the way back from the
        # database, so nothing outside a fresh identity map ever sees the string; the sweep does,
        # because it never reloads. Found when `main` merged the dashboard in.
        channel=ReservationChannel.DIRECT,
        status=ReservationStatus.CONFIRMED,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 4),
        nights=3,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


def _path(reservation) -> str:
    return f"/api/v1/reservations/{reservation.id}/guest-access-token"


# --- Issuing (R1.1, D14, rule 3(a)) ---------------------------------------------------


@pytest.mark.asyncio
async def test_the_token_comes_back_in_clear_exactly_once(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """Rule 3(a)'s named exception, and the whole reason the route exists.

    Both halves in one test because they are one contract: the operator receives a usable
    value, and what the database keeps is only its digest. Either alone would be misleading.
    """
    reservation = await _stay(db_session, tenant_a)

    response = await api.post(
        _path(reservation),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 201
    token = response.json()["token"]
    assert token
    stored = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).scalar_one()
    assert stored.token_hash == hash_guest_token(token)
    assert token not in stored.token_hash


@pytest.mark.asyncio
async def test_no_later_read_returns_the_token(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """The half of rule 3(a) that is easy to state and easy to lose (D14, D2).

    "Nunca en una lectura posterior" holds here because there is **no read at all** —
    `GuestAccessTokenRepository` declares none, so no route can grow one by accident.

    **Every `GET` the app exposes is walked**, not a list I remembered to write. The QA panel
    of section 4 caught the earlier version doing something weaker: it checked three paths,
    one of which was the token route itself, which has no `GET` handler and therefore
    answered `405` — a leg that could never have contained the token, dressed up as
    coverage. Enumerating the router is what makes the claim mean something, and it is what
    will catch the *next* change adding a reservation endpoint that serialises too much.

    Via `tests/route_walk.py`, and that matters: this FastAPI keeps an included router as one
    object rather than copying its endpoints into `app.routes`, so the obvious walk inspects
    **zero** included routes and passes while checking nothing. That module exists because
    the trap had already been hit twice; the first draft of this test made it three.
    """
    reservation = await _stay(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    token = (await api.post(_path(reservation), headers=header)).json()["token"]

    routes, _ = flatten_routes(api.fastapi_app)  # type: ignore[attr-defined]
    readable = {path for path, route in routes if "GET" in route.methods}

    # The guard, and it names the paths rather than counting them. A count was the first
    # attempt and the QA panel of section 4 showed it was theatre: seven unrelated `GET`s
    # (`/auth/me`, `/users`, `/properties`, …) already satisfy any small floor, so a
    # regression that dropped the two reservation paths from the walk would still pass.
    # These two are the ones that could plausibly serialise a stay's token.
    assert {"/api/v1/reservations", "/api/v1/reservations/{reservation_id}"} <= readable

    walked = 0
    for path in readable:
        if not path.startswith("/api/v1"):
            continue
        # Only routes whose parameters this stay can fill; anything else would 404/422 for
        # reasons that say nothing about the token.
        concrete = path.replace("{reservation_id}", str(reservation.id))
        if "{" in concrete:
            continue
        walked += 1
        assert token not in (await api.get(concrete, headers=header)).text

    # And the walk still has to be non-empty — the failure mode `route_walk.py` was
    # extracted to stop, which the first draft of this test reproduced.
    assert walked >= 5


@pytest.mark.asyncio
async def test_reissuing_replaces_the_previous_token(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R1.5's "sustituirlo de manera explícita", end to end.

    Two live tokens would be the failure; so would a second `POST` failing on the partial
    unique index. The route has to do the revoke-and-create of D14 for both to be avoided.
    """
    reservation = await _stay(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    first = (await api.post(_path(reservation), headers=header)).json()["token"]
    second_response = await api.post(_path(reservation), headers=header)

    assert second_response.status_code == 201
    second = second_response.json()["token"]
    assert second != first

    rows = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).scalars().all()
    live = [row for row in rows if row.revoked_at is None]
    assert len(rows) == 2
    assert len(live) == 1
    assert live[0].token_hash == hash_guest_token(second)


@pytest.mark.asyncio
async def test_issuing_writes_an_audit_row_without_the_token(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R6.1 and R6.4: minting a credential is audited, and the value is not in the row."""
    reservation = await _stay(db_session, tenant_a)
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    token = (
        await api.post(_path(reservation), headers=auth_header(api, manager))
    ).json()["token"]

    entry = (
        await db_session.execute(
            select(AuditLogModel).where(
                AuditLogModel.action == "GUEST_ACCESS_TOKEN_ISSUED"
            )
        )
    ).scalar_one()
    assert entry.entity_type == "GUEST_ACCESS_TOKEN"
    assert entry.actor_user_id == manager.id
    assert entry.changes == {"token_hash": {"changed": True}}
    assert token not in str(entry.changes)
    assert hash_guest_token(token) not in str(entry.changes)


# --- Revoking (R1.4, D14) -------------------------------------------------------------


@pytest.mark.asyncio
async def test_revoking_stops_the_token_being_live(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    reservation = await _stay(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    await api.post(_path(reservation), headers=header)

    response = await api.delete(_path(reservation), headers=header)

    assert response.status_code == 204
    stored = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).scalar_one()
    assert stored.revoked_at is not None


@pytest.mark.asyncio
async def test_revoking_twice_answers_the_same_and_keeps_the_first_instant(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """Idempotent, and the timestamp is why it matters (R1.4).

    `revoked_at` records *when* access was withdrawn. A second call overwriting it would
    quietly rewrite the answer in the row that exists to give it.
    """
    reservation = await _stay(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    await api.post(_path(reservation), headers=header)
    await api.delete(_path(reservation), headers=header)
    stored = (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == reservation.id
            )
        )
    ).scalar_one()
    first_instant = stored.revoked_at

    second = await api.delete(_path(reservation), headers=header)

    assert second.status_code == 204
    await db_session.refresh(stored)
    assert stored.revoked_at == first_instant


@pytest.mark.asyncio
async def test_revoking_a_stay_that_never_had_a_token_is_not_an_error(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """`204` either way, deliberately (D5's reasoning applied to the operator route).

    Answering differently would tell the caller whether a stay currently has a live token —
    a fact they can learn no other way, since nothing reads the token back. The operator's
    intent, "this link must stop working", is satisfied regardless.
    """
    reservation = await _stay(db_session, tenant_a)

    response = await api.delete(
        _path(reservation),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 204
    assert (
        await db_session.execute(
            select(AuditLogModel).where(
                AuditLogModel.action == "GUEST_ACCESS_TOKEN_REVOKED"
            )
        )
    ).first() is None


@pytest.mark.asyncio
async def test_revoking_writes_an_audit_row_pointing_at_the_token(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R6.1, and the reason the repository returns the id rather than a count.

    Both audit rows name the same `entity_id`, so
    `ix_audit_logs_tenant_id_entity_type_entity_id` answers "everything that happened to this
    credential". Pointing one of the two at the reservation would mix two kinds of id under
    one `entity_type`.
    """
    reservation = await _stay(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])
    await api.post(_path(reservation), headers=header)
    await api.delete(_path(reservation), headers=header)

    rows = {
        entry.action: entry
        for entry in (
            await db_session.execute(
                select(AuditLogModel).where(
                    AuditLogModel.entity_type == "GUEST_ACCESS_TOKEN"
                )
            )
        ).scalars()
    }

    assert set(rows) == {"GUEST_ACCESS_TOKEN_ISSUED", "GUEST_ACCESS_TOKEN_REVOKED"}
    assert (
        rows["GUEST_ACCESS_TOKEN_ISSUED"].entity_id
        == rows["GUEST_ACCESS_TOKEN_REVOKED"].entity_id
    )


# --- RBAC and tenant isolation (R1.4, R2.5, D14) --------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.CLEANER, UserRole.TECHNICIAN])
async def test_a_role_without_the_permission_is_refused(
    api, db_session, tenant_a, users_by_role_a, role: UserRole
) -> None:
    """D14 gives this to the two administrative roles only.

    Minting one of these hands out a link whose bearer can submit the guest's identity
    document, so being physically at the property is not a reason to hold it.
    """
    reservation = await _stay(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[role])

    assert (await api.post(_path(reservation), headers=header)).status_code == 403
    assert (await api.delete(_path(reservation), headers=header)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.TENANT_OWNER, UserRole.PROPERTY_MANAGER])
async def test_both_administrative_roles_may_mint(
    api, db_session, tenant_a, users_by_role_a, role: UserRole
) -> None:
    """The positive half. The owner is included on purpose: in a tenant with no manager she
    would otherwise have no way to let a guest check in at all (PRD §1's scale)."""
    reservation = await _stay(db_session, tenant_a)

    response = await api.post(_path(reservation), headers=auth_header(api, users_by_role_a[role]))

    assert response.status_code == 201


@pytest.mark.asyncio
async def test_an_operator_cannot_mint_for_another_tenants_stay(
    api, db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    """R2.5, and `404` rather than `403` — the same oracle argument the document routes make.

    A `403` would confirm the reservation exists somewhere, which is a fact about another
    operator's business.
    """
    foreign = await _stay(db_session, tenant_b)

    response = await api.post(
        _path(foreign),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404
    assert (
        await db_session.execute(
            select(GuestAccessTokenModel).where(
                GuestAccessTokenModel.reservation_id == foreign.id
            )
        )
    ).first() is None


@pytest.mark.asyncio
async def test_an_operator_cannot_revoke_another_tenants_token(
    api, db_session, test_engine, tenant_a, tenant_b, users_by_role_a
) -> None:
    """R2.5. The foreign token is planted directly rather than minted through the API.

    Not squeamishness about setup: `bind_session_to_tenant` is deliberately one-way
    (`app/core/db.py`), and this test's client shares one session across requests, so
    authenticating as tenant B and then as tenant A would fail inside the harness for a
    reason that has nothing to do with the behaviour under test. Planting the row keeps the
    assertion honest — a live token of another tenant, and a revoke that must not touch it.
    """
    foreign = await _stay(db_session, tenant_b)
    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant_b.id,
            reservation_id=foreign.id,
            token_hash=hash_guest_token("belongs to b"),
        )
    )
    # Committed, not merely flushed: the assertion below reads it back from a **second**
    # session, which cannot see another transaction's uncommitted rows.
    await db_session.commit()

    response = await api.delete(
        _path(foreign),
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404

    # Read the planted token back through a session that was **never marked**, which is the
    # route `bind_session_to_tenant`'s own docstring prescribes for unmarked data. The
    # obvious alternative — asserting on `db_session` — cannot work: the request bound it to
    # tenant A, so the global filter hides tenant B's row.
    #
    # The tenancy panel of section 4 asked for this shape and was right to. An earlier
    # version asserted only that no revocation audit row existed, and that could not
    # discriminate: the request `404`s at the reservation gate, so
    # `revoke_live_for_reservation` is never reached and the audit row could not exist
    # whether or not the repository still filtered by tenant. Reading the row directly is
    # what actually exercises that filter as a second line of defence.
    async with AsyncSession(test_engine, expire_on_commit=False) as unmarked:
        survivor = (
            await unmarked.execute(
                select(GuestAccessTokenModel).where(
                    GuestAccessTokenModel.reservation_id == foreign.id
                )
            )
        ).scalar_one()
        assert survivor.revoked_at is None


@pytest.mark.asyncio
async def test_a_reservation_that_does_not_exist_answers_the_same_404(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """The other half of the oracle argument: absent and someone else's look identical."""
    response = await api.post(
        f"/api/v1/reservations/{uuid.uuid4()}/guest-access-token",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_the_routes_require_authentication_at_all(api, db_session, tenant_a) -> None:
    """Unlike the portal's anonymous routes, these two are ordinary authenticated endpoints.

    Said without a count on purpose: the portal had four when this was written and has six since
    `guest-portal-messaging`. What distinguishes these two is that they require a JWT at all,
    which no number expresses.
    """
    reservation = await _stay(db_session, tenant_a)

    assert (await api.post(_path(reservation))).status_code == 401
    assert (await api.delete(_path(reservation))).status_code == 401
