"""How an `IntegrityError` is classified (`guest-portal-api` design Risks, R1.5).

Two things are under test, and the second is the reason this file exists at all.

1. The **positive**: the one constraint a correct, well-formed request can still lose a race
   on becomes a `409` telling the operator to retry, rather than a `500` telling them to
   report an incident for something they can simply repeat.
2. The **negative**, which is a security boundary: no other integrity violation may be
   dressed up as retryable. The first implementation matched the constraint name as a
   substring of the driver's message, and the security panel of section 4 showed that
   asyncpg's message embeds the offending **row value** via Postgres's `DETAIL` line — so a
   caller who could store the constraint's name in any column under a unique index could make
   an unrelated duplicate, anywhere in the application, answer with this module's "retry".
"""

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import IntegrityError

from app.guests.api.errors import _violated_constraint, register_guest_error_handlers
from app.guests.infrastructure.models import GuestAccessTokenModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.models import TenantModel

LIVE_TOKEN_CONSTRAINT = "uq_guest_access_tokens_live_per_reservation"


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


async def _property(db_session, tenant, *, internal_code: str) -> PropertyModel:
    prop = PropertyModel(
        tenant_id=tenant.id,
        name="REDES11",
        internal_code=internal_code,
        pms_external_id=f"PMS-{uuid.uuid4().hex[:6]}",
        max_guests=4,
    )
    db_session.add(prop)
    await db_session.flush()
    return prop


@pytest.mark.asyncio
async def test_the_live_token_clash_is_recognised_by_its_constraint_name(db_session) -> None:
    """The positive half: a genuine race is classified as retryable."""
    tenant = await _tenant(db_session, "clash")
    prop = await _property(db_session, tenant, internal_code=f"C{uuid.uuid4().hex[:6]}")
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        status=ReservationStatus.CONFIRMED,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 1) + timedelta(days=2),
        nights=2,
    )
    db_session.add(reservation)
    await db_session.flush()
    for suffix in ("1", "2"):
        db_session.add(
            GuestAccessTokenModel(
                tenant_id=tenant.id,
                reservation_id=reservation.id,
                token_hash=suffix * 64,
            )
        )

    with pytest.raises(IntegrityError) as caught:
        await db_session.flush()

    assert _violated_constraint(caught.value) == LIVE_TOKEN_CONSTRAINT


@pytest.mark.asyncio
async def test_a_row_value_that_spells_the_constraint_is_not_mistaken_for_it(
    db_session,
) -> None:
    """The attack the security panel of section 4 demonstrated.

    `properties.internal_code` is operator-writable and carries a unique index. Storing the
    live-token constraint's own name in it and re-submitting produces an `IntegrityError`
    whose *message* contains that name — via `DETAIL:  Key (…)=(…) already exists.` — while
    the constraint actually violated is a different one.

    A substring match on the message answered `409 CONFLICT / "retry"` here. Matching the
    driver's reported constraint name answers with the other constraint, so the handler
    re-raises and the caller gets a truthful error instead of an instruction to repeat an
    operation that will never succeed.
    """
    tenant = await _tenant(db_session, "spoof")
    await _property(db_session, tenant, internal_code=LIVE_TOKEN_CONSTRAINT)
    db_session.add(
        PropertyModel(
            tenant_id=tenant.id,
            name="Second",
            internal_code=LIVE_TOKEN_CONSTRAINT,
            pms_external_id=f"PMS-{uuid.uuid4().hex[:6]}",
            max_guests=4,
        )
    )

    with pytest.raises(IntegrityError) as caught:
        await db_session.flush()

    # The message really does carry the bait — this is what the old check matched on.
    assert LIVE_TOKEN_CONSTRAINT in str(caught.value.orig)
    # And the structured identity does not.
    assert _violated_constraint(caught.value) != LIVE_TOKEN_CONSTRAINT
    assert _violated_constraint(caught.value) == "uq_properties_tenant_id_internal_code"


@pytest.mark.asyncio
async def test_a_cross_tenant_foreign_key_is_never_reported_as_retryable(db_session) -> None:
    """The two composite FKs of sections 1 and 3 mean a tenant boundary was crossed.

    Telling that caller to "retry" would be wrong twice over: the operation cannot succeed,
    and the answer would suggest it might.
    """
    tenant_a = await _tenant(db_session, "fk-a")
    tenant_b = await _tenant(db_session, "fk-b")
    prop_b = await _property(db_session, tenant_b, internal_code=f"C{uuid.uuid4().hex[:6]}")
    reservation_b = ReservationModel(
        tenant_id=tenant_b.id,
        property_id=prop_b.id,
        channel="DIRECT",
        status=ReservationStatus.CONFIRMED,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 3),
        nights=2,
    )
    db_session.add(reservation_b)
    await db_session.flush()

    db_session.add(
        GuestAccessTokenModel(
            tenant_id=tenant_a.id,
            reservation_id=reservation_b.id,
            token_hash="f" * 64,
        )
    )

    with pytest.raises(IntegrityError) as caught:
        await db_session.flush()

    assert _violated_constraint(caught.value) == "fk_guest_access_tokens_reservation_within_tenant"
    assert _violated_constraint(caught.value) != LIVE_TOKEN_CONSTRAINT


# --- The handler over HTTP ------------------------------------------------------------
#
# The QA panel of section 4 found this path had no coverage at all, and that the API test
# fixture **cannot** produce it: that client shares one `AsyncSession` across requests, so
# two "concurrent" `POST`s collide inside SQLAlchemy rather than in Postgres, and no genuine
# two-transaction race is reachable.
#
# So the handler is driven directly instead, on a throwaway app whose route raises the very
# `IntegrityError` the database produces. That is not a weaker test — it is the same
# classification code on the same exception objects, with the HTTP result observable. The
# exceptions are real ones caught from Postgres above, not hand-built.


class _Boom(Exception):
    """Carries a real `IntegrityError` into a route, so the handler sees a genuine one."""


@pytest_asyncio.fixture
async def handler_app():
    app = FastAPI()
    register_guest_error_handlers(app)
    holder: dict[str, IntegrityError] = {}

    @app.get("/boom")
    async def _boom() -> None:
        raise holder["error"]

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.holder = holder  # type: ignore[attr-defined]
        yield client


async def _capture_live_token_clash(db_session) -> IntegrityError:
    tenant = await _tenant(db_session, f"http-{uuid.uuid4().hex[:6]}")
    prop = await _property(db_session, tenant, internal_code=f"C{uuid.uuid4().hex[:6]}")
    reservation = ReservationModel(
        tenant_id=tenant.id,
        property_id=prop.id,
        channel="DIRECT",
        status=ReservationStatus.CONFIRMED,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 3),
        nights=2,
    )
    db_session.add(reservation)
    await db_session.flush()
    for suffix in ("7", "8"):
        db_session.add(
            GuestAccessTokenModel(
                tenant_id=tenant.id,
                reservation_id=reservation.id,
                token_hash=suffix * 64,
            )
        )
    with pytest.raises(IntegrityError) as caught:
        await db_session.flush()
    await db_session.rollback()
    return caught.value


@pytest.mark.asyncio
async def test_a_live_token_clash_answers_409_in_the_prd_envelope(
    handler_app, db_session
) -> None:
    """The Risks section's whole point: retryable, and said in the §23 envelope."""
    handler_app.holder["error"] = await _capture_live_token_clash(db_session)

    response = await handler_app.get("/boom")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    assert "Retry" in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_an_unrelated_duplicate_is_not_dressed_up_as_retryable(
    handler_app, db_session
) -> None:
    """The attack, end to end: a row value spelling the constraint must not yield `409`.

    Re-raising leaves it to the server's own handler, which answers `500` — truthful, and
    what an unexpected constraint violation deserves.
    """
    tenant = await _tenant(db_session, f"http-spoof-{uuid.uuid4().hex[:6]}")
    await _property(db_session, tenant, internal_code=LIVE_TOKEN_CONSTRAINT)
    db_session.add(
        PropertyModel(
            tenant_id=tenant.id,
            name="Second",
            internal_code=LIVE_TOKEN_CONSTRAINT,
            pms_external_id=f"PMS-{uuid.uuid4().hex[:6]}",
            max_guests=4,
        )
    )
    with pytest.raises(IntegrityError) as caught:
        await db_session.flush()
    await db_session.rollback()
    handler_app.holder["error"] = caught.value

    response = await handler_app.get("/boom")

    assert response.status_code != 409
    assert "Retry" not in response.text
