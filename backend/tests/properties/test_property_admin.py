"""Use cases of property administration, against in-memory fakes of their ports.

`steering/testing.md` puts `application/` here: unit tests with fakes of the ports, not the real
database and not mocks of SQLAlchemy. That is what lets these assert things the HTTP tests
structurally cannot — the ORDER of the calls, and what happens when a port raises.
"""

import uuid
from datetime import UTC, datetime, time

import pytest

from app.audit.domain.entities import AuditLog
from app.core.encrypted_secret import EncryptedSecret
from app.properties.application.property_admin import (
    CreatePropertyCommand,
    CreatePropertyUseCase,
    UpdatePropertyUseCase,
)
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.exceptions import (
    DuplicateInternalCodeError,
    PropertyNotFoundError,
)
from app.properties.domain.repositories import Page, PropertyFilters

NOW = datetime(2026, 8, 8, 10, 0, tzinfo=UTC)
TENANT = uuid.uuid4()
ACTOR = uuid.uuid4()


class FakeAuditRepository:
    def __init__(self) -> None:
        self.entries: list[AuditLog] = []

    async def add(self, tenant_id: uuid.UUID, entry: AuditLog) -> None:
        self.entries.append(entry)


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class FakePropertyRepository:
    """Records the calls in order, so a test can assert the sequence and not just the effects."""

    def __init__(self, *, stored: Property | None = None, add_error: Exception | None = None):
        self.calls: list[str] = []
        self.stored = stored
        self.add_error = add_error
        self.added: tuple[Property, EncryptedSecret | None] | None = None
        self.updated: dict[str, object] | None = None
        self.wifi_secret_set: EncryptedSecret | None = None
        self.wifi_calls = 0

    async def add(self, tenant_id, property, *, wifi_secret=None) -> None:
        self.calls.append("add")
        if self.add_error is not None:
            raise self.add_error
        self.added = (property, wifi_secret)
        self.stored = property

    async def get(self, tenant_id, property_id):
        self.calls.append("get")
        return self.stored

    async def update_details(self, tenant_id, property_id, changes) -> bool:
        self.calls.append("update_details")
        self.updated = dict(changes)
        return True

    async def set_wifi_password(self, tenant_id, property_id, secret) -> bool:
        self.calls.append("set_wifi_password")
        self.wifi_calls += 1
        self.wifi_secret_set = secret
        return True

    async def list(self, tenant_id, *, filters: PropertyFilters, page, per_page) -> Page:
        self.calls.append("list")
        return Page(items=(), total=0)


def _property(**overrides) -> Property:
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=TENANT,
        name="Redes 11",
        internal_code="REDES11",
        created_at=NOW,
        updated_at=NOW,
        city="Madrid",
        max_guests=4,
        status=PropertyStatus.ACTIVE,
        current_operational_state=PropertyOperationalState.VACANT_READY,
    )
    defaults.update(overrides)
    return Property(**defaults)  # type: ignore[arg-type]


def _command(**overrides) -> CreatePropertyCommand:
    defaults = dict(name="Redes 11", internal_code="REDES11")
    defaults.update(overrides)
    return CreatePropertyCommand(**defaults)  # type: ignore[arg-type]


# --- R2, R7.5: the insert precedes the audit row ---


@pytest.mark.asyncio
async def test_the_insert_happens_before_the_audit_row_is_written() -> None:
    """R7.5. The order is the guarantee, so the order is what is asserted."""
    properties = FakePropertyRepository()
    audit = FakeAuditRepository()
    uow = FakeUnitOfWork()

    await CreatePropertyUseCase(properties=properties, audit=audit, uow=uow).execute(
        tenant_id=TENANT, actor_user_id=ACTOR, actor_ip="10.0.0.1", command=_command(), now=NOW
    )

    assert properties.calls[0] == "add"
    assert len(audit.entries) == 1
    assert uow.commits == 1


@pytest.mark.asyncio
async def test_a_duplicate_never_reaches_the_audit_writer() -> None:
    """A `409` must leave no trace of a creation that did not happen (design D6).

    This is the assertion the HTTP-level test cannot make: there, the failed flush poisons the
    shared session and the follow-up count cannot run.
    """
    properties = FakePropertyRepository(add_error=DuplicateInternalCodeError("taken"))
    audit = FakeAuditRepository()
    uow = FakeUnitOfWork()

    with pytest.raises(DuplicateInternalCodeError):
        await CreatePropertyUseCase(properties=properties, audit=audit, uow=uow).execute(
            tenant_id=TENANT, actor_user_id=ACTOR, actor_ip=None, command=_command(), now=NOW
        )

    assert audit.entries == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_the_wifi_password_reaches_the_port_only_as_ciphertext() -> None:
    """R5.2, design D1/D2: the port's parameter is typed, so plaintext cannot get through."""
    properties = FakePropertyRepository()

    await CreatePropertyUseCase(
        properties=properties, audit=FakeAuditRepository(), uow=FakeUnitOfWork()
    ).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        command=_command(wifi_password="clave-en-claro"),
        now=NOW,
    )

    assert properties.added is not None
    _, secret = properties.added
    assert isinstance(secret, EncryptedSecret)
    assert secret.ciphertext != "clave-en-claro"


@pytest.mark.asyncio
async def test_the_secret_is_audited_only_as_changed() -> None:
    """R7.4: `{"changed": true}`, never the value and never a masked form."""
    audit = FakeAuditRepository()

    await CreatePropertyUseCase(
        properties=FakePropertyRepository(), audit=audit, uow=FakeUnitOfWork()
    ).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        command=_command(wifi_password="clave-en-claro"),
        now=NOW,
    )

    changes = audit.entries[0].changes or {}
    assert changes["wifi_password_encrypted"] == {"changed": True}
    assert "clave-en-claro" not in str(changes)


@pytest.mark.asyncio
async def test_a_property_is_created_in_vacant_ready_without_being_asked() -> None:
    """R4.1: the command has no way to name a state, so the entity default is what is inserted."""
    properties = FakePropertyRepository()

    await CreatePropertyUseCase(
        properties=properties, audit=FakeAuditRepository(), uow=FakeUnitOfWork()
    ).execute(
        tenant_id=TENANT, actor_user_id=ACTOR, actor_ip=None, command=_command(), now=NOW
    )

    assert properties.added is not None
    created, _ = properties.added
    assert created.current_operational_state is PropertyOperationalState.VACANT_READY
    assert not hasattr(_command(), "current_operational_state")


# --- R3, R4: the update path ---


@pytest.mark.asyncio
async def test_a_patch_that_changes_nothing_writes_nothing() -> None:
    """R3.3: `written` decides both the persistence and the audit row."""
    stored = _property(city="Madrid")
    properties = FakePropertyRepository(stored=stored)
    audit = FakeAuditRepository()
    uow = FakeUnitOfWork()

    result = await UpdatePropertyUseCase(
        properties=properties, audit=audit, uow=uow
    ).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        property_id=stored.id,
        changes={"city": "Madrid"},
        now=NOW,
    )

    assert result is stored
    assert "update_details" not in properties.calls
    assert audit.entries == []
    assert uow.commits == 0


@pytest.mark.asyncio
async def test_only_the_changed_fields_are_persisted() -> None:
    stored = _property(city="Madrid", max_guests=4)
    properties = FakePropertyRepository(stored=stored)

    await UpdatePropertyUseCase(
        properties=properties, audit=FakeAuditRepository(), uow=FakeUnitOfWork()
    ).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        property_id=stored.id,
        changes={"city": "Segovia", "max_guests": 4},
        now=NOW,
    )

    assert properties.updated == {"city": "Segovia"}


@pytest.mark.asyncio
async def test_a_missing_property_is_not_found_before_anything_is_written() -> None:
    properties = FakePropertyRepository(stored=None)
    audit = FakeAuditRepository()

    with pytest.raises(PropertyNotFoundError):
        await UpdatePropertyUseCase(
            properties=properties, audit=audit, uow=FakeUnitOfWork()
        ).execute(
            tenant_id=TENANT,
            actor_user_id=ACTOR,
            actor_ip=None,
            property_id=uuid.uuid4(),
            changes={"city": "Segovia"},
            now=NOW,
        )

    assert "update_details" not in properties.calls
    assert audit.entries == []


@pytest.mark.asyncio
async def test_sending_the_wifi_password_always_counts_as_a_change() -> None:
    """The documented consequence of design D1: there is no reader, so no-op cannot be detected."""
    stored = _property()
    properties = FakePropertyRepository(stored=stored)
    audit = FakeAuditRepository()

    await UpdatePropertyUseCase(
        properties=properties, audit=audit, uow=FakeUnitOfWork()
    ).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        property_id=stored.id,
        changes={"wifi_password": "otra-clave"},
        now=NOW,
    )

    assert properties.wifi_calls == 1
    assert isinstance(properties.wifi_secret_set, EncryptedSecret)
    assert (audit.entries[0].changes or {})["wifi_password_encrypted"] == {"changed": True}


@pytest.mark.asyncio
async def test_clearing_the_wifi_password_passes_none_to_the_port() -> None:
    stored = _property()
    properties = FakePropertyRepository(stored=stored)

    await UpdatePropertyUseCase(
        properties=properties, audit=FakeAuditRepository(), uow=FakeUnitOfWork()
    ).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        property_id=stored.id,
        changes={"wifi_password": None},
        now=NOW,
    )

    assert properties.wifi_calls == 1
    assert properties.wifi_secret_set is None


@pytest.mark.asyncio
async def test_a_non_patchable_field_never_reaches_the_port() -> None:
    """R4.2. Even if a caller smuggles it past the schema, the use case filters on the allowlist.

    Two layers for one rule, on purpose: the schema turns it into a `422` that names the field,
    and this makes the write structurally impossible if the schema ever changes.
    """
    stored = _property()
    properties = FakePropertyRepository(stored=stored)

    result = await UpdatePropertyUseCase(
        properties=properties, audit=FakeAuditRepository(), uow=FakeUnitOfWork()
    ).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        property_id=stored.id,
        changes={"current_operational_state": PropertyOperationalState.AWAITING_CLEANING},
        now=NOW,
    )

    assert result is stored
    assert "update_details" not in properties.calls


@pytest.mark.asyncio
async def test_the_free_text_notes_are_recorded_only_as_changed() -> None:
    """Design D7: `audit_logs.changes` is a plaintext sink under rule 11."""
    stored = _property(access_notes=None)
    properties = FakePropertyRepository(stored=stored)
    audit = FakeAuditRepository()

    await UpdatePropertyUseCase(properties=properties, audit=audit, uow=FakeUnitOfWork()).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        property_id=stored.id,
        changes={"access_notes": "codigo del portal 4321", "city": "Segovia"},
        now=NOW,
    )

    changes = audit.entries[0].changes or {}
    assert changes["access_notes"] == {"changed": True}
    assert "4321" not in str(changes)
    # A non-sensitive field in the same operation still records its before/after — one row, all
    # the fields, per `app/audit/domain/actions.py`.
    assert changes["city"] == {"old": "Madrid", "new": "Segovia"}


@pytest.mark.asyncio
async def test_times_survive_the_audit_serialisation() -> None:
    """`_storable` accepts scalars only, and a `time` has to come back as a string not a crash."""
    stored = _property(default_check_in_time=time(15, 0))
    audit = FakeAuditRepository()

    await UpdatePropertyUseCase(
        properties=FakePropertyRepository(stored=stored), audit=audit, uow=FakeUnitOfWork()
    ).execute(
        tenant_id=TENANT,
        actor_user_id=ACTOR,
        actor_ip=None,
        property_id=stored.id,
        changes={"default_check_in_time": time(16, 30)},
        now=NOW,
    )

    assert (audit.entries[0].changes or {})["default_check_in_time"]["new"] == "16:30:00"
