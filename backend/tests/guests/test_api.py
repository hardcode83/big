"""Guest documents and the legal registration over HTTP (R6, R7; PRD §17).

The assertions that carry the weight are about **who may see a document number and what
happens when they do**: rule 4 of `steering/security.md` keeps it out of every other surface,
and rule 9 requires a row every time somebody looks.
"""

import logging
import uuid
from datetime import UTC, date, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.audit.infrastructure.models import AuditLogModel
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.api.dependencies import get_password_hasher, get_token_codec
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.auth.infrastructure.token_codec import JwtTokenCodec
from app.core.db import get_db_session
from app.guests.api.dependencies import get_submit_legal_registration_use_case
from app.guests.application.use_cases import SubmitLegalRegistrationUseCase
from app.guests.domain.enums import GuestDocumentStatus, LegalRegistrationStatus
from app.guests.infrastructure.adapters import MockSESHospedajesAdapter
from app.guests.infrastructure.legal import SqlAlchemyLegalRegistrationStayStore
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.guests.infrastructure.models import GuestModel
from app.main import create_app
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.properties.infrastructure.models import PropertyModel
from app.reservations.domain.enums import ReservationStatus
from app.reservations.infrastructure.models import ReservationModel
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.domain.enums import TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository
from tests.auth.conftest import (  # noqa: F401
    TEST_BCRYPT_ROUNDS,
    tenant_a,
    tenant_b,
    users_by_role_a,
    users_by_role_b,
    utc_now,
)

SECRET = "f" * 64
NUMBER = "12345678Z"
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

DOCUMENT = {
    "nationality": "ES",
    "date_of_birth": "1990-05-04",
    "document_type": "DNI",
    "document_number": NUMBER,
    "document_expiry_date": "2032-01-01",
}


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


async def _guest(db_session, tenant, *, name="Ada Lovelace") -> GuestModel:
    guest = GuestModel(tenant_id=tenant.id, full_name=name)
    db_session.add(guest)
    await db_session.flush()
    return guest


async def _stay(db_session, tenant, guest, *, status=LegalRegistrationStatus.PENDING_GUEST_DATA):
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
        guest_id=guest.id,
        channel="DIRECT",
        status=ReservationStatus.CONFIRMED,
        check_in_date=date(2026, 9, 1),
        check_out_date=date(2026, 9, 4),
        nights=3,
        legal_registration_status=status,
    )
    db_session.add(reservation)
    await db_session.flush()
    return reservation


# --- R7.1: storing a document -----------------------------------------------------


@pytest.mark.asyncio
async def test_the_number_is_encrypted_and_never_echoed(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    guest = await _guest(db_session, tenant_a)

    response = await api.patch(
        f"/api/v1/guests/{guest.id}/document",
        json=DOCUMENT,
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 200
    assert response.json()["document_status"] == "PROVIDED"
    # Rule 4: not in the response, and not in cleartext in the column.
    assert NUMBER not in response.text
    await db_session.refresh(guest)
    assert guest.document_number_encrypted is not None
    assert NUMBER not in guest.document_number_encrypted
    assert guest.document_status is GuestDocumentStatus.PROVIDED


@pytest.mark.asyncio
async def test_the_audit_row_records_which_fields_changed_and_no_values(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """Rule 11 over `audit_logs.changes`: `{"changed": true}`, never the number or the DOB."""
    guest = await _guest(db_session, tenant_a)

    await api.patch(
        f"/api/v1/guests/{guest.id}/document",
        json=DOCUMENT,
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    rows = await db_session.execute(
        select(AuditLogModel).where(AuditLogModel.tenant_id == tenant_a.id)
    )
    [entry] = list(rows.scalars())
    assert entry.action == "GUEST_DOCUMENT_UPDATED"
    assert entry.entity_id == guest.id
    assert entry.actor_user_id == users_by_role_a[UserRole.PROPERTY_MANAGER].id
    changes = entry.changes or {}
    assert changes["document_number_encrypted"] == {"changed": True}
    assert changes["date_of_birth"] == {"changed": True}
    assert NUMBER not in str(changes)
    assert "1990-05-04" not in str(changes)


@pytest.mark.asyncio
async def test_naming_a_stay_makes_it_ready_to_submit(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R6.3 — the eight fields of PRD §17 are complete once the document lands."""
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest)

    await api.patch(
        f"/api/v1/guests/{guest.id}/document",
        json=DOCUMENT | {"reservation_id": str(reservation.id)},
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    await db_session.refresh(reservation)
    assert reservation.legal_registration_status is LegalRegistrationStatus.READY_TO_SUBMIT


# --- R7.2, R7.3: reading a document ------------------------------------------------


@pytest.mark.asyncio
async def test_an_authorised_role_reads_the_full_number_and_leaves_a_trail(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    guest = await _guest(db_session, tenant_a)
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    await api.patch(
        f"/api/v1/guests/{guest.id}/document",
        json=DOCUMENT,
        headers=auth_header(api, manager),
    )

    response = await api.get(
        f"/api/v1/guests/{guest.id}/document", headers=auth_header(api, manager)
    )

    assert response.status_code == 200
    assert response.json()["document_number"] == NUMBER
    rows = await db_session.execute(
        select(AuditLogModel).where(
            AuditLogModel.tenant_id == tenant_a.id,
            AuditLogModel.action == "GUEST_DOCUMENT_READ",
        )
    )
    reads = list(rows.scalars())
    assert len(reads) == 1
    assert reads[0].actor_user_id == manager.id


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.CLEANER, UserRole.TECHNICIAN, UserRole.SUPER_ADMIN])
async def test_a_role_without_the_permission_never_sees_a_document(
    api, db_session, tenant_a, users_by_role_a, role
) -> None:
    """PRD §17 names three roles. `SUPER_ADMIN` is one of them in the PRD and is deliberately
    excluded here — see the reasoning in `policy.py`: it holds no in-tenant operational
    permission until `saas-cross-tenant` decides what cross-tenant access means, and identity
    documents are the worst possible place to pre-empt that. Withholding is narrower than the
    PRD's ceiling, so nothing is violated."""
    guest = await _guest(db_session, tenant_a)

    response = await api.get(
        f"/api/v1/guests/{guest.id}/document", headers=auth_header(api, users_by_role_a[role])
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_owner_may_read_but_not_write_a_document(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    guest = await _guest(db_session, tenant_a)
    header = auth_header(api, users_by_role_a[UserRole.TENANT_OWNER])

    write = await api.patch(f"/api/v1/guests/{guest.id}/document", json=DOCUMENT, headers=header)
    # Nothing stored yet, so the read is a 404 rather than a 403 — the permission passed.
    read = await api.get(f"/api/v1/guests/{guest.id}/document", headers=header)

    assert write.status_code == 403
    assert read.status_code == 404


@pytest.mark.asyncio
async def test_a_neighbours_guest_is_the_same_404_as_a_missing_one(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    theirs = await _guest(db_session, tenant_b, name="Grace Hopper")
    header = auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER])

    cross_tenant = await api.get(f"/api/v1/guests/{theirs.id}/document", headers=header)
    nonexistent = await api.get(f"/api/v1/guests/{uuid.uuid4()}/document", headers=header)

    assert cross_tenant.status_code == nonexistent.status_code == 404
    assert cross_tenant.json() == nonexistent.json()


@pytest.mark.asyncio
async def test_a_write_to_a_neighbours_guest_is_also_a_404(
    api, db_session, tenant_a, tenant_b, users_by_role_a
) -> None:
    theirs = await _guest(db_session, tenant_b, name="Grace Hopper")

    response = await api.patch(
        f"/api/v1/guests/{theirs.id}/document",
        json=DOCUMENT,
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404
    await db_session.refresh(theirs)
    assert theirs.document_number_encrypted is None


# --- R6.4, R6.5, R6.6: the submission ----------------------------------------------


@pytest.mark.asyncio
async def test_a_ready_stay_is_submitted(api, db_session, tenant_a, users_by_role_a) -> None:
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest)
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    await api.patch(
        f"/api/v1/guests/{guest.id}/document",
        json=DOCUMENT | {"reservation_id": str(reservation.id)},
        headers=auth_header(api, manager),
    )

    response = await api.post(
        f"/api/v1/reservations/{reservation.id}/legal-registration/submit",
        headers=auth_header(api, manager),
    )

    assert response.status_code == 200
    assert response.json()["legal_registration_status"] == "SUBMITTED"
    await db_session.refresh(reservation)
    assert reservation.legal_registration_status is LegalRegistrationStatus.SUBMITTED


@pytest.mark.asyncio
async def test_a_stay_that_is_not_ready_is_refused(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R6.6 — `409`, and **the adapter is never invoked**: a real one files with the police."""
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest)

    response = await api.post(
        f"/api/v1/reservations/{reservation.id}/legal-registration/submit",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 409
    await db_session.refresh(reservation)
    assert (
        reservation.legal_registration_status is LegalRegistrationStatus.PENDING_GUEST_DATA
    )


@pytest.mark.asyncio
async def test_submitting_twice_is_refused_the_second_time(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """`SUBMITTED` is not `READY_TO_SUBMIT`, so the second call cannot re-file."""
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest)
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    await api.patch(
        f"/api/v1/guests/{guest.id}/document",
        json=DOCUMENT | {"reservation_id": str(reservation.id)},
        headers=auth_header(api, manager),
    )
    path = f"/api/v1/reservations/{reservation.id}/legal-registration/submit"

    assert (await api.post(path, headers=auth_header(api, manager))).status_code == 200
    assert (await api.post(path, headers=auth_header(api, manager))).status_code == 409


@pytest.mark.asyncio
async def test_a_neighbours_reservation_cannot_be_submitted(
    api, db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    theirs_guest = await _guest(db_session, tenant_b, name="Grace Hopper")
    theirs = await _stay(
        db_session, tenant_b, theirs_guest, status=LegalRegistrationStatus.READY_TO_SUBMIT
    )

    response = await api.post(
        f"/api/v1/reservations/{theirs.id}/legal-registration/submit",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 404
    await db_session.refresh(theirs)
    assert theirs.legal_registration_status is LegalRegistrationStatus.READY_TO_SUBMIT


@pytest.mark.asyncio
async def test_a_ready_stay_whose_guest_lost_a_field_is_refused_with_the_reason(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """`READY_TO_SUBMIT` is a stored status; the check runs again at submit time so a partial
    filing is impossible even if the status went stale."""
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(
        db_session, tenant_a, guest, status=LegalRegistrationStatus.READY_TO_SUBMIT
    )

    response = await api.post(
        f"/api/v1/reservations/{reservation.id}/legal-registration/submit",
        headers=auth_header(api, users_by_role_a[UserRole.PROPERTY_MANAGER]),
    )

    assert response.status_code == 409
    assert "document_number" in response.json()["error"]["message"]
    # Field NAMES, never values — there is nothing to leak in the message.
    assert NUMBER not in response.text


async def _submit_with_a_failing_provider(api, db_session, tenant, manager, reservation, guest):
    """Drive R6.5 by swapping in `MockSESHospedajesAdapter(fail=True)`.

    The mock's failure path is triggered by an explicit constructor flag and not by a magic
    value in the data — a magic document number would be a rule somebody hits by accident in
    seed data — so reaching it from an endpoint test means overriding the dependency.
    """
    await api.patch(
        f"/api/v1/guests/{guest.id}/document",
        json=DOCUMENT | {"reservation_id": str(reservation.id)},
        headers=auth_header(api, manager),
    )

    def _failing_use_case():
        return SubmitLegalRegistrationUseCase(
            guests=SqlAlchemyGuestRepository(db_session),
            stays=SqlAlchemyLegalRegistrationStayStore(db_session),
            provider=MockSESHospedajesAdapter(fail=True),
            users=SqlAlchemyUserRepository(db_session),
            timeline=SqlAlchemyTimelineEventRepository(db_session),
            notifications=SqlAlchemyNotificationLogRepository(db_session),
            tenant_configs=SqlAlchemyTenantConfigRepository(db_session),
            audit=SqlAlchemyAuditLogRepository(db_session),
            uow=_FlushOnlyUow(db_session),
        )

    api._transport.app.dependency_overrides[  # type: ignore[attr-defined]
        get_submit_legal_registration_use_case
    ] = _failing_use_case
    return await api.post(
        f"/api/v1/reservations/{reservation.id}/legal-registration/submit",
        headers=auth_header(api, manager),
    )


class _EmptyRoster:
    """A `UserRepository` whose roster is empty, for the one branch the route cannot reach.

    Substituted **only into the use case**, never into authentication: the endpoint keeps the
    real repository, so the acting manager still authenticates normally. That separation is
    what makes this branch testable at all — deactivating the roles for real returns `401`
    before the use case runs, because `SUBMIT_LEGAL_REGISTRATION` reaches `PROPERTY_MANAGER`
    alone and every request revalidates that its actor is ACTIVE.

    Only `list` is implemented, because `RoleRecipients` calls nothing else; anything the use
    case might reach for later fails loudly rather than silently answering `None`.
    """

    def __init__(self) -> None:
        self.calls: list = []

    async def list(self, tenant_id, filters, *, page, per_page):
        from app.auth.domain.repositories import UserPage

        self.calls.append((tenant_id, filters.role, filters.status))
        return UserPage(items=(), total=0)


@pytest.mark.asyncio
async def test_a_failed_filing_with_nobody_to_tell_is_logged_not_swallowed(
    api, db_session, tenant_a, users_by_role_a, caplog
) -> None:
    """R5.2 of `notification-writers-gap`: no rows, but never in silence.

    The "SHALL registrarlo" half of R5.2 was unpinned anywhere in the tree — the section-1
    security panel found this call site discarding the resolved recipient set, and its
    re-review pointed out that the dependency-override seam below reaches the branch without
    faking the auth state that made an API-level attempt return `401`.

    Asserts all three halves at once: the operation does not fail, no row is written, and the
    fact that nobody could be addressed reaches the log.
    """
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest)
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    roster = _EmptyRoster()

    await api.patch(
        f"/api/v1/guests/{guest.id}/document",
        json=DOCUMENT | {"reservation_id": str(reservation.id)},
        headers=auth_header(api, manager),
    )

    def _use_case_with_no_recipients():
        return SubmitLegalRegistrationUseCase(
            guests=SqlAlchemyGuestRepository(db_session),
            stays=SqlAlchemyLegalRegistrationStayStore(db_session),
            provider=MockSESHospedajesAdapter(fail=True),
            users=roster,
            timeline=SqlAlchemyTimelineEventRepository(db_session),
            notifications=SqlAlchemyNotificationLogRepository(db_session),
            tenant_configs=SqlAlchemyTenantConfigRepository(db_session),
            audit=SqlAlchemyAuditLogRepository(db_session),
            uow=_FlushOnlyUow(db_session),
        )

    api._transport.app.dependency_overrides[  # type: ignore[attr-defined]
        get_submit_legal_registration_use_case
    ] = _use_case_with_no_recipients

    with caplog.at_level(logging.ERROR):
        response = await api.post(
            f"/api/v1/reservations/{reservation.id}/legal-registration/submit",
            headers=auth_header(api, manager),
        )

    # R5.2: the operation does not fail over having nobody to tell.
    assert response.status_code == 200
    assert response.json()["legal_registration_status"] == "FAILED"
    await db_session.refresh(reservation)
    assert reservation.legal_registration_status is LegalRegistrationStatus.FAILED

    # Both roles were actually asked before concluding there was nobody — otherwise this
    # test would pass against an implementation that never consulted the owner fallback.
    assert roster.calls == [
        (tenant_a.id, UserRole.PROPERTY_MANAGER, UserStatus.ACTIVE),
        (tenant_a.id, UserRole.TENANT_OWNER, UserStatus.ACTIVE),
    ]

    # No rows, because there was nobody to address.
    rows = await db_session.execute(
        select(NotificationLogModel).where(NotificationLogModel.tenant_id == tenant_a.id)
    )
    assert list(rows.scalars()) == []

    # And the silence is broken. Without this the failed police filing is recorded with
    # nobody told and no trace that nobody was told.
    assert any(
        record.message == "guests.legal_registration_failure_without_recipient"
        for record in caplog.records
    )


class _FlushOnlyUow:
    """The test fixture owns the outer transaction; committing here would end it."""

    def __init__(self, session) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.flush()


@pytest.mark.asyncio
async def test_a_rejected_submission_fails_the_stay_and_alerts_the_managers(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """R6.5, which had **no test at all** until the feature-scale QA panel said so.

    Task 7.7 claimed "tests de los tres caminos" and only two existed: success and the 409.
    `MockSESHospedajesAdapter(fail=True)` was never constructed anywhere, so the whole
    failure branch — status, notification, and the absence of the timeline event — was
    unguarded: a regression writing `LEGAL_REGISTRATION_SUBMITTED` on a failed filing would
    have shipped silently.
    """
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest)
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    response = await _submit_with_a_failing_provider(
        api, db_session, tenant_a, manager, reservation, guest
    )

    assert response.status_code == 200
    assert response.json()["legal_registration_status"] == "FAILED"
    await db_session.refresh(reservation)
    assert reservation.legal_registration_status is LegalRegistrationStatus.FAILED

    # The manager is told — R6.5 says "al manager", not "to whoever pressed the button".
    rows = await db_session.execute(
        select(NotificationLogModel).where(NotificationLogModel.tenant_id == tenant_a.id)
    )
    notifications = list(rows.scalars())
    assert len(notifications) == 1
    assert notifications[0].recipient_user_id == manager.id
    assert notifications[0].notification_type == "LEGAL_REGISTRATION_FAILED"

    # And **no** submission event: the timeline is append-only, so an event here would be a
    # permanent claim that a filing with the police happened.
    events = await db_session.execute(
        select(TimelineEventModel).where(
            TimelineEventModel.tenant_id == tenant_a.id,
            TimelineEventModel.event_type == TimelineEventType.LEGAL_REGISTRATION_SUBMITTED,
        )
    )
    assert list(events.scalars()) == []


@pytest.mark.asyncio
async def test_a_rejected_submission_fans_out_across_the_tenants_enabled_channels(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """notification-channel-routing R1, R2 — the `LEGAL_REGISTRATION_FAILED` writer,
    exercised through the real use case → resolver → `dispatch_and_persist` path, not
    just the pure `channel_dispatch.py` unit tests."""
    from app.notifications.domain.enums import NotificationChannel
    from app.tenants.infrastructure.models import TenantConfigModel

    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest)
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]
    manager.phone = "+34600000004"
    db_session.add(manager)
    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
        )
    ).scalar_one()
    config.notification_email_enabled = True
    config.notification_whatsapp_enabled = True
    await db_session.flush()

    response = await _submit_with_a_failing_provider(
        api, db_session, tenant_a, manager, reservation, guest
    )
    assert response.status_code == 200

    rows = await db_session.execute(
        select(NotificationLogModel).where(NotificationLogModel.tenant_id == tenant_a.id)
    )
    by_channel = {row.channel: row for row in rows.scalars()}
    assert set(by_channel) == {
        NotificationChannel.IN_APP,
        NotificationChannel.EMAIL,
        NotificationChannel.WHATSAPP,
    }
    assert by_channel[NotificationChannel.WHATSAPP].recipient_contact == manager.phone
    assert all(
        row.notification_type == "LEGAL_REGISTRATION_FAILED" for row in by_channel.values()
    )


@pytest.mark.asyncio
async def test_no_notification_carries_the_document(
    api, db_session, tenant_a, users_by_role_a
) -> None:
    """Rule 11 over `notification_logs.subject`/`body`: the exception these two columns carry
    — the first of the rule's two — admits a masked access code, and a document number is not
    one.

    **This test used to be vacuous** and the QA panel proved it: it drove only the success
    path, which queues no notification at all, so the loop below iterated over zero rows and
    could never fail. It now drives the failure path, which is the only one that writes a
    notification — so there is something to assert about.
    """
    guest = await _guest(db_session, tenant_a)
    reservation = await _stay(db_session, tenant_a, guest)
    manager = users_by_role_a[UserRole.PROPERTY_MANAGER]

    await _submit_with_a_failing_provider(
        api, db_session, tenant_a, manager, reservation, guest
    )

    rows = await db_session.execute(
        select(NotificationLogModel).where(NotificationLogModel.tenant_id == tenant_a.id)
    )
    notifications = list(rows.scalars())
    # The assertion that stops this being vacuous again.
    assert notifications, "the failure path must queue a notification to assert about"
    for row in notifications:
        assert NUMBER not in (row.subject or "")
        assert NUMBER not in (row.body or "")
        assert "1990-05-04" not in (row.body or "")
        assert NUMBER not in (row.last_error or "")


@pytest.mark.asyncio
async def test_an_anonymous_request_is_refused(api, db_session, tenant_a) -> None:
    guest = await _guest(db_session, tenant_a)

    assert (await api.get(f"/api/v1/guests/{guest.id}/document")).status_code == 401
    assert (
        await api.patch(f"/api/v1/guests/{guest.id}/document", json=DOCUMENT)
    ).status_code == 401
