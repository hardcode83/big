"""Unit contract for the shared guest resolver (R1, R2, R5; design D1, D4, D5)."""

import uuid
from collections.abc import Collection, Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from inspect import Parameter, signature

import pytest

from app.guests.application.resolution import ManualGuestIdentityInput, ResolveOrCreateGuest
from app.guests.domain.entities import Guest
from app.guests.domain.value_objects import GuestSummary


class FakeGuestEmailExclusion:
    def __init__(self) -> None:
        self.acquired: list[tuple[uuid.UUID, str]] = []

    async def acquire(self, tenant_id: uuid.UUID, normalized_email: str) -> None:
        self.acquired.append((tenant_id, normalized_email))

TENANT = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
OTHER_TENANT = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
NOW = datetime(2026, 9, 9, 12, tzinfo=UTC)


def test_resolver_requires_transactional_email_exclusion() -> None:
    exclusion = signature(ResolveOrCreateGuest).parameters["exclusion"]

    assert exclusion.default is Parameter.empty


class FakeGuestRepository:
    """In-memory fake preserving the existing repository's deterministic email contract."""

    def __init__(self, guests: list[Guest] | None = None) -> None:
        self.guests = list(guests or [])
        self.added: list[Guest] = []
        self.email_lookups: list[tuple[uuid.UUID, str]] = []

    async def get(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> GuestSummary | None:
        guest = next(
            (item for item in self.guests if item.tenant_id == tenant_id and item.id == guest_id),
            None,
        )
        return _summary(guest) if guest is not None else None

    async def list_for_ids(
        self, tenant_id: uuid.UUID, guest_ids: Collection[uuid.UUID]
    ) -> Sequence[GuestSummary]:
        return [
            _summary(guest)
            for guest in self.guests
            if guest.tenant_id == tenant_id and guest.id in guest_ids
        ]

    async def find_by_email(self, tenant_id: uuid.UUID, email: str) -> GuestSummary | None:
        self.email_lookups.append((tenant_id, email))
        matches = [
            guest
            for guest in self.guests
            if guest.tenant_id == tenant_id and guest.email == email
        ]
        winner = min(matches, key=lambda guest: (guest.created_at, str(guest.id)), default=None)
        return _summary(winner) if winner is not None else None

    async def find_by_phone(self, tenant_id: uuid.UUID, phone: str) -> list[GuestSummary]:
        return [
            _summary(guest)
            for guest in self.guests
            if guest.tenant_id == tenant_id and guest.phone == phone
        ]

    async def add(self, tenant_id: uuid.UUID, guest: Guest) -> None:
        assert guest.tenant_id == tenant_id
        self.guests.append(guest)
        self.added.append(guest)

    async def get_full(self, tenant_id: uuid.UUID, guest_id: uuid.UUID) -> Guest | None:
        return next(
            (item for item in self.guests if item.tenant_id == tenant_id and item.id == guest_id),
            None,
        )

    async def save_document(self, tenant_id: uuid.UUID, guest: Guest) -> None:
        raise AssertionError("the resolver must never update a guest")


def _guest(
    *,
    guest_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID = TENANT,
    full_name: str = "Existing Guest",
    email: str | None = "guest@example.com",
    phone: str | None = "+34611111111",
    preferred_language: str = "es",
    created_at: datetime = NOW,
) -> Guest:
    return Guest(
        id=guest_id or uuid.uuid4(),
        tenant_id=tenant_id,
        full_name=full_name,
        created_at=created_at,
        updated_at=created_at,
        email=email,
        phone=phone,
        preferred_language=preferred_language,
    )


def _summary(guest: Guest) -> GuestSummary:
    return GuestSummary(
        id=guest.id,
        full_name=guest.full_name,
        email=guest.email,
        phone=guest.phone,
        preferred_language=guest.preferred_language,
        document_status=guest.document_status,
        legal_registration_status=guest.legal_registration_status,
    )


@pytest.mark.asyncio
async def test_reuses_by_normalised_email_without_creating() -> None:
    existing = _guest()
    repository = FakeGuestRepository([existing])
    exclusion = FakeGuestEmailExclusion()

    resolved_id = await ResolveOrCreateGuest(repository, exclusion).execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(
            full_name="Different Name", email="  GUEST@Example.COM  "
        ),
        now=NOW,
    )

    assert resolved_id == existing.id
    assert repository.email_lookups == [(TENANT, "guest@example.com")]
    assert repository.added == []


@pytest.mark.asyncio
async def test_creates_with_canonical_contact_data_when_email_does_not_match() -> None:
    repository = FakeGuestRepository()
    exclusion = FakeGuestEmailExclusion()

    resolved_id = await ResolveOrCreateGuest(repository, exclusion).execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(
            full_name="  Marta Reyes  ",
            email="  Marta@Example.COM ",
            phone="612 345 678",
            preferred_language="en",
        ),
        now=NOW,
    )

    assert len(repository.added) == 1
    created = repository.added[0]
    assert created.id == resolved_id
    assert created.tenant_id == TENANT
    assert created.full_name == "Marta Reyes"
    assert created.email == "marta@example.com"
    assert created.phone == "+34612345678"
    assert created.preferred_language == "en"
    assert created.created_at == created.updated_at == NOW


@pytest.mark.asyncio
async def test_absent_or_blank_email_always_creates_without_an_email_lookup() -> None:
    repository = FakeGuestRepository()
    resolver = ResolveOrCreateGuest(repository, FakeGuestEmailExclusion())

    first = await resolver.execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(full_name="First", email=None),
        now=NOW,
    )
    second = await resolver.execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(full_name="Second", email="   "),
        now=NOW,
    )

    assert first != second
    assert repository.email_lookups == []
    assert [guest.email for guest in repository.added] == [None, None]


@pytest.mark.asyncio
async def test_does_not_match_by_name_or_phone_without_email() -> None:
    existing = _guest(email=None, full_name="Same Person", phone="+34612345678")
    repository = FakeGuestRepository([existing])

    resolved_id = await ResolveOrCreateGuest(repository, FakeGuestEmailExclusion()).execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(full_name="Same Person", phone="612345678"),
        now=NOW,
    )

    assert resolved_id != existing.id
    assert len(repository.guests) == 2
    assert repository.email_lookups == []


@pytest.mark.asyncio
async def test_reuse_preserves_every_field_of_the_existing_guest() -> None:
    existing = _guest(
        full_name="Original Name",
        phone="+34611111111",
        preferred_language="es",
    )
    snapshot = replace(existing)
    repository = FakeGuestRepository([existing])

    await ResolveOrCreateGuest(repository, FakeGuestEmailExclusion()).execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(
            full_name="Replacement Name",
            email="guest@example.com",
            phone="699999999",
            preferred_language="en",
        ),
        now=NOW + timedelta(days=1),
    )

    assert repository.guests == [snapshot]
    assert repository.added == []


@pytest.mark.asyncio
async def test_historical_duplicates_use_created_at_then_id_without_merge() -> None:
    lower_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    higher_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    same_oldest_time = NOW - timedelta(days=2)
    duplicates = [
        _guest(guest_id=uuid.uuid4(), created_at=NOW - timedelta(days=1)),
        _guest(guest_id=higher_id, created_at=same_oldest_time),
        _guest(guest_id=lower_id, created_at=same_oldest_time),
    ]
    repository = FakeGuestRepository(duplicates)

    resolved_id = await ResolveOrCreateGuest(repository, FakeGuestEmailExclusion()).execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(full_name="Incoming", email="GUEST@example.com"),
        now=NOW,
    )

    assert resolved_id == lower_id
    assert repository.guests == duplicates
    assert repository.added == []


@pytest.mark.asyncio
async def test_same_email_in_another_tenant_is_not_reused() -> None:
    foreign = _guest(tenant_id=OTHER_TENANT)
    repository = FakeGuestRepository([foreign])

    resolved_id = await ResolveOrCreateGuest(repository, FakeGuestEmailExclusion()).execute(
        tenant_id=TENANT,
        identity=ManualGuestIdentityInput(full_name="Mine", email="guest@example.com"),
        now=NOW,
    )

    assert resolved_id != foreign.id
    assert repository.added[0].tenant_id == TENANT
