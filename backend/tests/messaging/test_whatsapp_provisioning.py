"""Associating and releasing a tenant's WhatsApp `phone_number_id` (section 6, R6.1-R6.3, D3/D8).

Drives the two use cases directly, without FastAPI — the same split `test_webhook_provisioning
.py` (`tests/integrations/`) established: what R6 promises (a validated `default_property_id`,
database-enforced global uniqueness on `phone_number_id`, no value to hide behind the audit
row) is a property of the application layer, and testing it through HTTP would only add a way
for the test to pass because a router happened to filter a field. The endpoint's own concerns
(RBAC, status codes, the response shape) live in `test_whatsapp_provisioning_api.py`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.audit.domain.actions import (
    ENTITY_WHATSAPP_PHONE_NUMBER,
    WHATSAPP_PHONE_NUMBER_ASSOCIATED,
    WHATSAPP_PHONE_NUMBER_RELEASED,
)
from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.messaging.application.whatsapp_provisioning import (
    AssociateWhatsAppPhoneNumberUseCase,
    ReleaseWhatsAppPhoneNumberUseCase,
)
from app.messaging.domain.exceptions import (
    MessagingValidationError,
    WhatsAppPhoneNumberAlreadyAssociatedError,
    WhatsAppPhoneNumberNotFoundError,
)
from app.messaging.infrastructure.repositories import (
    SqlAlchemyWhatsAppPhoneNumberRepository,
)
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from tests.messaging.conftest import seed_property, seed_tenant, seed_user

ACTOR_IP = "203.0.113.9"
NOW = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)
#: Strictly after `NOW`, and used for every release call in this file. `AuditLog.created_at`
#: is the `now` a use case is handed (`app/audit/domain/services.py`), not a server-side
#: clock, so an associate and a release both stamped `NOW` produce a genuine tie in
#: `_audit_rows`'s `ORDER BY created_at` — one `ORDER BY` result among ties is not
#: guaranteed by SQL, and it was observed to flip under full-suite load. A release is never
#: earlier than the association it releases, so this also matches reality.
RELEASED_AT = NOW + timedelta(minutes=5)


def _associate_use_case(db_session) -> AssociateWhatsAppPhoneNumberUseCase:
    return AssociateWhatsAppPhoneNumberUseCase(
        phone_numbers=SqlAlchemyWhatsAppPhoneNumberRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )


def _release_use_case(db_session) -> ReleaseWhatsAppPhoneNumberUseCase:
    return ReleaseWhatsAppPhoneNumberUseCase(
        phone_numbers=SqlAlchemyWhatsAppPhoneNumberRepository(db_session),
        audit=SqlAlchemyAuditLogRepository(db_session),
        uow=SqlAlchemyUnitOfWork(db_session),
    )


async def _associate(
    db_session, tenant, actor, property_, *, phone_number_id="15550001", display=None
):
    return await _associate_use_case(db_session).execute(
        tenant_id=tenant.id,
        actor_user_id=actor.id,
        actor_ip=ACTOR_IP,
        phone_number_id=phone_number_id,
        display_phone_number=display,
        default_property_id=property_.id,
        now=NOW,
    )


async def _audit_rows(db_session, tenant_id: uuid.UUID) -> list[AuditLogModel]:
    result = await db_session.execute(
        select(AuditLogModel)
        .where(AuditLogModel.tenant_id == tenant_id)
        .where(AuditLogModel.entity_type == ENTITY_WHATSAPP_PHONE_NUMBER)
        .order_by(AuditLogModel.created_at)
    )
    return list(result.scalars())


@pytest_asyncio.fixture
async def tenant_a(db_session):
    return await seed_tenant(db_session, "TenantA")


@pytest_asyncio.fixture
async def property_a(db_session, tenant_a):
    return await seed_property(db_session, tenant_a, "REDES11")


@pytest_asyncio.fixture
async def actor_a(db_session, tenant_a):
    return await seed_user(db_session, tenant_a, "owner@tenanta.example.com")


@pytest_asyncio.fixture
async def tenant_b(db_session):
    return await seed_tenant(db_session, "TenantB")


@pytest_asyncio.fixture
async def property_b(db_session, tenant_b):
    return await seed_property(db_session, tenant_b, "PAJARITOS8")


@pytest_asyncio.fixture
async def actor_b(db_session, tenant_b):
    return await seed_user(db_session, tenant_b, "owner@tenantb.example.com")


# --- Association (R6.1) --------------------------------------------------------------------


@pytest.mark.asyncio
async def test_associating_a_new_number_stores_it_with_its_default_property(
    db_session, tenant_a, actor_a, property_a
) -> None:
    association = await _associate(
        db_session, tenant_a, actor_a, property_a, phone_number_id="15550001"
    )

    assert association.phone_number_id == "15550001"
    assert association.default_property_id == property_a.id

    stored = await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_for_tenant(
        tenant_a.id
    )
    assert stored is not None
    assert stored.id == association.id
    assert stored.phone_number_id == "15550001"
    assert stored.default_property_id == property_a.id


@pytest.mark.asyncio
async def test_associating_with_a_property_of_another_tenant_is_refused(
    db_session, tenant_a, actor_a, property_b
) -> None:
    """Same pattern `CreateConversationUseCase` uses for a client-supplied `property_id`:
    `properties.get` returns `None` for a foreign property, and that is the one refusal."""
    with pytest.raises(MessagingValidationError):
        await _associate(db_session, tenant_a, actor_a, property_b, phone_number_id="15550001")

    assert (
        await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_for_tenant(tenant_a.id)
    ) is None


@pytest.mark.asyncio
async def test_associating_with_an_unknown_property_is_refused(
    db_session, tenant_a, actor_a
) -> None:
    class _FakeProperty:
        id = uuid.uuid4()

    with pytest.raises(MessagingValidationError):
        await _associate(
            db_session, tenant_a, actor_a, _FakeProperty(), phone_number_id="15550001"
        )


@pytest.mark.asyncio
async def test_re_associating_the_same_tenant_replaces_the_existing_row(
    db_session, tenant_a, actor_a, property_a
) -> None:
    """Create-or-replace (R6.3): one call expresses both outcomes, because there is no secret
    whose lifetime a separate rotate verb would need to protect."""
    first = await _associate(
        db_session, tenant_a, actor_a, property_a, phone_number_id="15550001"
    )

    second = await _associate(
        db_session, tenant_a, actor_a, property_a, phone_number_id="15550002"
    )

    assert second.id == first.id
    assert second.phone_number_id == "15550002"

    stored = await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_for_tenant(
        tenant_a.id
    )
    assert stored is not None
    assert stored.phone_number_id == "15550002"


@pytest.mark.asyncio
async def test_associating_the_same_number_to_a_second_tenant_is_refused_without_touching_the_first(
    db_session, tenant_a, actor_a, property_a, tenant_b, actor_b, property_b
) -> None:
    """R6.2, in its own words: the existing association is never overwritten in silence.

    The uniqueness is enforced at the database, not by a prior read in this use case (design
    D8): `phone_number_id` is genuinely global across tenants.
    """
    # Captured before the rollback below: `AsyncSession.rollback()` expires every ORM object
    # in the session unconditionally, and a plain attribute access on an expired object tries
    # a synchronous reload that is not awaitable from here — so `tenant_a.id` itself would
    # raise `MissingGreenlet` if read after the rollback instead of before it.
    tenant_a_id = tenant_a.id
    tenant_b_id = tenant_b.id

    first = await _associate(
        db_session, tenant_a, actor_a, property_a, phone_number_id="15550001"
    )

    with pytest.raises(WhatsAppPhoneNumberAlreadyAssociatedError):
        await _associate(
            db_session, tenant_b, actor_b, property_b, phone_number_id="15550001"
        )
    # The failed INSERT aborts the DB transaction (Postgres semantics); the use case itself
    # never rolls back because a real request's session is simply discarded after the
    # exception propagates out. Only this shared test session needs it, to keep reading below
    # — same pattern `tests/messaging/test_pipeline_atomicity.py` and others already use.
    await db_session.rollback()

    still_a = await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_for_tenant(
        tenant_a_id
    )
    assert still_a is not None
    assert still_a.id == first.id
    assert still_a.phone_number_id == "15550001"

    assert (
        await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_for_tenant(tenant_b_id)
    ) is None


@pytest.mark.asyncio
async def test_two_tenants_hold_different_numbers_without_conflict(
    db_session, tenant_a, actor_a, property_a, tenant_b, actor_b, property_b
) -> None:
    a = await _associate(db_session, tenant_a, actor_a, property_a, phone_number_id="15550001")
    b = await _associate(db_session, tenant_b, actor_b, property_b, phone_number_id="15550002")

    assert a.phone_number_id != b.phone_number_id


# --- Release (R6.3) -------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_releasing_an_association_removes_it(
    db_session, tenant_a, actor_a, property_a
) -> None:
    await _associate(db_session, tenant_a, actor_a, property_a, phone_number_id="15550001")

    await _release_use_case(db_session).execute(
        tenant_id=tenant_a.id, actor_user_id=actor_a.id, actor_ip=ACTOR_IP, now=RELEASED_AT
    )

    assert (
        await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_for_tenant(tenant_a.id)
    ) is None


@pytest.mark.asyncio
async def test_releasing_frees_the_number_for_another_tenant(
    db_session, tenant_a, actor_a, property_a, tenant_b, actor_b, property_b
) -> None:
    await _associate(db_session, tenant_a, actor_a, property_a, phone_number_id="15550001")
    await _release_use_case(db_session).execute(
        tenant_id=tenant_a.id, actor_user_id=actor_a.id, actor_ip=ACTOR_IP, now=RELEASED_AT
    )

    reassociated = await _associate(
        db_session, tenant_b, actor_b, property_b, phone_number_id="15550001"
    )

    assert reassociated.phone_number_id == "15550001"


@pytest.mark.asyncio
async def test_releasing_with_nothing_to_release_is_refused(
    db_session, tenant_a, actor_a
) -> None:
    with pytest.raises(WhatsAppPhoneNumberNotFoundError):
        await _release_use_case(db_session).execute(
            tenant_id=tenant_a.id, actor_user_id=actor_a.id, actor_ip=ACTOR_IP, now=RELEASED_AT
        )


@pytest.mark.asyncio
async def test_a_tenant_cannot_release_another_tenants_association(
    db_session, tenant_a, actor_a, property_a, tenant_b, actor_b
) -> None:
    await _associate(db_session, tenant_a, actor_a, property_a, phone_number_id="15550001")

    with pytest.raises(WhatsAppPhoneNumberNotFoundError):
        await _release_use_case(db_session).execute(
            tenant_id=tenant_b.id, actor_user_id=actor_b.id, actor_ip=ACTOR_IP, now=RELEASED_AT
        )

    assert (
        await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_for_tenant(tenant_a.id)
    ) is not None


# --- The audit trail (R6.1, R6.3; rule 9, rule 11) ------------------------------------------


@pytest.mark.asyncio
async def test_both_operations_are_audited_with_the_acting_person(
    db_session, tenant_a, actor_a, property_a
) -> None:
    association = await _associate(
        db_session, tenant_a, actor_a, property_a, phone_number_id="15550001"
    )
    await _release_use_case(db_session).execute(
        tenant_id=tenant_a.id, actor_user_id=actor_a.id, actor_ip=ACTOR_IP, now=RELEASED_AT
    )

    rows = await _audit_rows(db_session, tenant_a.id)

    assert [row.action for row in rows] == [
        WHATSAPP_PHONE_NUMBER_ASSOCIATED,
        WHATSAPP_PHONE_NUMBER_RELEASED,
    ]
    for row in rows:
        assert row.entity_id == association.id
        assert row.actor_user_id == actor_a.id
        assert row.actor_ip == ACTOR_IP


@pytest.mark.asyncio
async def test_the_association_diff_carries_the_real_values(
    db_session, tenant_a, actor_a, property_a
) -> None:
    """Rule 11 permits a plain diff here on purpose: there is no secret in this table at all
    (D3/D8), unlike `webhook_endpoints`, where the equivalent row redacts everything."""
    await _associate(db_session, tenant_a, actor_a, property_a, phone_number_id="15550001")

    row = (await _audit_rows(db_session, tenant_a.id))[0]

    assert row.changes["phone_number_id"] == {"old": None, "new": "15550001"}
    assert row.changes["default_property_id"] == {
        "old": None,
        "new": str(property_a.id),
    }


@pytest.mark.asyncio
async def test_the_release_diff_moves_every_field_to_none(
    db_session, tenant_a, actor_a, property_a
) -> None:
    await _associate(db_session, tenant_a, actor_a, property_a, phone_number_id="15550001")
    await _release_use_case(db_session).execute(
        tenant_id=tenant_a.id, actor_user_id=actor_a.id, actor_ip=ACTOR_IP, now=RELEASED_AT
    )

    rows = await _audit_rows(db_session, tenant_a.id)
    release_row = rows[1]

    assert release_row.changes["phone_number_id"] == {"old": "15550001", "new": None}


# --- Tenant resolution (section 7's consumer; `find_by_phone_number_id`) -------------------


@pytest.mark.asyncio
async def test_find_by_phone_number_id_resolves_the_owning_association(
    db_session, tenant_a, actor_a, property_a
) -> None:
    """The read section 7 will call: `phone_number_id` in, the owning association out.

    `db_session` is the same unmarked session every other test in this module already uses
    (`tests/messaging/conftest.py`) — that is exactly the shape `find_by_phone_number_id` is
    built for, since resolving `phone_number_id -> tenant_id` has no tenant to scope by until
    it answers (D3/D8's `require_unmarked_session`, mirroring
    `SqlAlchemyWebhookEndpointRepository.find_by_token_hash` and its own
    `test_an_endpoint_is_stored_and_recovered_by_its_token`).
    """
    association = await _associate(
        db_session, tenant_a, actor_a, property_a, phone_number_id="15550001"
    )

    found = await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_by_phone_number_id(
        "15550001"
    )

    assert found is not None
    assert found.id == association.id
    assert found.tenant_id == tenant_a.id
    assert found.default_property_id == property_a.id


@pytest.mark.asyncio
async def test_find_by_phone_number_id_returns_none_for_an_unassociated_number(
    db_session, tenant_a, actor_a, property_a
) -> None:
    await _associate(db_session, tenant_a, actor_a, property_a, phone_number_id="15550001")

    found = await SqlAlchemyWhatsAppPhoneNumberRepository(db_session).find_by_phone_number_id(
        "99999999"
    )

    assert found is None
