"""The row writers of `SqlAlchemyPropertyRepository` (`properties-crud` R2, R3, R5, R7).

Split from `test_repositories.py`, which covers resolution and tenant scoping of the read paths
that existed before `properties-crud`. The writers are what this change adds: `add`,
`update_details`, `set_wifi_password` and the paginated `list`.

Every duplicate case violates the real constraint against real Postgres rather than asserting
that a pre-check fired. That is the point of design D6: a pre-check is exactly what two
concurrent writes defeat, so a test that only exercises one would pass while the guarantee it
claims to cover does not hold.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.crypto import encrypt
from app.core.tenancy import CrossTenantWriteError
from app.properties.domain.entities import Property
from app.properties.domain.enums import PropertyOperationalState, PropertyStatus
from app.properties.domain.exceptions import (
    DuplicateInternalCodeError,
    DuplicatePmsExternalIdError,
    PropertyValidationError,
)
from app.properties.domain.repositories import PropertyFilters
from app.properties.infrastructure.models import PropertyModel
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.tenants.infrastructure.models import TenantModel

_NO_FILTERS = PropertyFilters()


async def _tenant(db_session, name: str) -> TenantModel:
    tenant = TenantModel(name=name, billing_email=f"{name.lower()}@example.com")
    db_session.add(tenant)
    await db_session.flush()
    return tenant


def _entity(
    tenant_id: uuid.UUID,
    *,
    internal_code: str,
    name: str | None = None,
    pms_external_id: str | None = None,
    status: PropertyStatus = PropertyStatus.ACTIVE,
    state: PropertyOperationalState = PropertyOperationalState.VACANT_READY,
) -> Property:
    now = datetime.now(UTC)
    return Property(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name if name is not None else internal_code,
        internal_code=internal_code,
        created_at=now,
        updated_at=now,
        pms_external_id=pms_external_id,
        status=status,
        current_operational_state=state,
    )


async def _stored(db_session, property_id: uuid.UUID) -> PropertyModel:
    row = await db_session.execute(select(PropertyModel).where(PropertyModel.id == property_id))
    return row.scalar_one()


# --- add -----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_add_inserts_the_property_and_leaves_the_state_at_its_default(db_session) -> None:
    """Creation is not a transition: no source state, so the DDL default is what applies (R4)."""
    tenant = await _tenant(db_session, "TenantA")
    entity = _entity(tenant.id, internal_code="REDES11", name="Redes 11")

    await SqlAlchemyPropertyRepository(db_session).add(tenant.id, entity)

    stored = await _stored(db_session, entity.id)
    assert stored.internal_code == "REDES11"
    assert stored.name == "Redes 11"
    assert stored.current_operational_state is PropertyOperationalState.VACANT_READY
    assert stored.status is PropertyStatus.ACTIVE
    assert stored.wifi_password_encrypted is None


@pytest.mark.parametrize(
    "state",
    [
        PropertyOperationalState.OCCUPIED_ESTIMATED,
        PropertyOperationalState.BLOCKED_BY_OWNER,
        PropertyOperationalState.AWAITING_CLEANING,
    ],
)
@pytest.mark.asyncio
async def test_add_refuses_an_entity_that_arrives_in_any_other_state(db_session, state) -> None:
    """R4.2 — and this guard is the ONLY thing enforcing it on this method.

    `update_details` cannot express a state change because its allowlist forbids the key; `add`
    has no such protection, because it takes a whole entity and an entity always carries a state.
    So the rule is checked at runtime here. Without it the port hands any caller a way to land a
    row directly in `OCCUPIED` or `BLOCKED` with no `property_state_transitions` row and no
    `AuditLog` — afterwards indistinguishable from one `PropertyStateMachine` moved, which is
    what rule 9 of `steering/security.md` exists to prevent.

    Parametrised over three unrelated states so the test cannot pass by accident on one enum
    member, and refused rather than silently normalised: a caller that asked for a state has to
    learn it was not honoured.
    """
    tenant = await _tenant(db_session, "TenantA")
    entity = _entity(tenant.id, internal_code="REDES11", state=state)

    with pytest.raises(PropertyValidationError):
        await SqlAlchemyPropertyRepository(db_session).add(tenant.id, entity)


@pytest.mark.asyncio
async def test_add_refuses_to_write_into_another_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    theirs = _entity(tenant_b.id, internal_code="PAJARITOS8")

    with pytest.raises(CrossTenantWriteError):
        await SqlAlchemyPropertyRepository(db_session).add(tenant_a.id, theirs)


@pytest.mark.asyncio
async def test_an_integrity_error_that_is_not_one_of_the_two_duplicates_is_re_raised(
    db_session,
) -> None:
    """R2.6. `_translate_duplicate` recognises two named constraints and must not guess at others.

    A foreign-key violation is the honest third case: it is an `IntegrityError` like the two
    duplicates, but answering `409 CONFLICT` for it would be, in the words of `user-management`,
    "a lie the client cannot act on" — there is no colliding row to rename around. It has to
    surface as the infrastructure error it is, which the router maps to a `500`.

    The violation is provoked against real Postgres by pointing at a tenant that does not exist,
    rather than by mocking the driver: a mocked `IntegrityError` would prove only that the `except`
    branch runs, not that the real constraint name fails to match the two the adapter knows.
    """
    orphan = _entity(uuid.uuid4(), internal_code="NO-SUCH-TENANT")

    with pytest.raises(IntegrityError):
        await SqlAlchemyPropertyRepository(db_session).add(orphan.tenant_id, orphan)


@pytest.mark.asyncio
async def test_a_duplicate_internal_code_is_a_domain_error(db_session) -> None:
    """The constraint decides, not a prior read (design D6)."""
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    await repository.add(tenant.id, _entity(tenant.id, internal_code="REDES11"))

    with pytest.raises(DuplicateInternalCodeError):
        await repository.add(tenant.id, _entity(tenant.id, internal_code="REDES11"))


@pytest.mark.asyncio
async def test_the_same_internal_code_is_free_in_another_tenant(db_session) -> None:
    """`uq_properties_tenant_id_internal_code` is per tenant, and that must stay true."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    repository = SqlAlchemyPropertyRepository(db_session)

    await repository.add(tenant_a.id, _entity(tenant_a.id, internal_code="REDES11"))
    await repository.add(tenant_b.id, _entity(tenant_b.id, internal_code="REDES11"))


@pytest.mark.asyncio
async def test_a_duplicate_pms_external_id_is_a_domain_error(db_session) -> None:
    """The ambiguity `specs/reservations.md` makes the sync reject is refused at the source (D5).

    This is the write path that could otherwise create it, which is the whole reason
    `properties-crud` added the partial unique index.
    """
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    await repository.add(
        tenant.id, _entity(tenant.id, internal_code="REDES11", pms_external_id="PMS-1")
    )

    with pytest.raises(DuplicatePmsExternalIdError):
        await repository.add(
            tenant.id, _entity(tenant.id, internal_code="PAJARITOS8", pms_external_id="PMS-1")
        )


@pytest.mark.asyncio
async def test_two_properties_without_a_pms_external_id_coexist(db_session) -> None:
    """The control case for the index being PARTIAL, and it is not incidental.

    Most properties carry no external id. A TOTAL unique index would technically permit many
    NULLs (Postgres treats them as distinct) but would index every one of them for nothing;
    getting the predicate wrong in the other direction — say `IS NULL` — would make a second
    unmapped property impossible and break the common case outright. So this asserts the half of
    D5 that the duplicate tests cannot see.
    """
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)

    await repository.add(tenant.id, _entity(tenant.id, internal_code="REDES11"))
    await repository.add(tenant.id, _entity(tenant.id, internal_code="PAJARITOS8"))

    assert (await repository.list(tenant.id, filters=_NO_FILTERS, page=1, per_page=10)).total == 2


@pytest.mark.asyncio
async def test_the_same_pms_external_id_is_free_in_another_tenant(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    repository = SqlAlchemyPropertyRepository(db_session)

    await repository.add(
        tenant_a.id, _entity(tenant_a.id, internal_code="REDES11", pms_external_id="PMS-1")
    )
    await repository.add(
        tenant_b.id, _entity(tenant_b.id, internal_code="OTHER", pms_external_id="PMS-1")
    )


@pytest.mark.asyncio
async def test_add_stores_only_ciphertext_for_the_wifi_password(db_session) -> None:
    """The entity has no such field, so this parameter is the only route (design D2)."""
    tenant = await _tenant(db_session, "TenantA")
    entity = _entity(tenant.id, internal_code="REDES11")
    secret = encrypt("la-contrasena-del-wifi")

    await SqlAlchemyPropertyRepository(db_session).add(tenant.id, entity, wifi_secret=secret)

    stored = await _stored(db_session, entity.id)
    assert stored.wifi_password_encrypted == secret.ciphertext
    assert "la-contrasena-del-wifi" not in (stored.wifi_password_encrypted or "")


# --- update_details ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_details_writes_the_named_columns(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    entity = _entity(tenant.id, internal_code="REDES11")
    await repository.add(tenant.id, entity)

    matched = await repository.update_details(
        tenant.id, entity.id, {"city": "Madrid", "max_guests": 4}
    )

    assert matched is True
    stored = await _stored(db_session, entity.id)
    assert stored.city == "Madrid"
    assert stored.max_guests == 4


@pytest.mark.asyncio
async def test_update_details_of_an_unknown_property_matches_nothing(db_session) -> None:
    """Returned rather than raised, so the caller can answer `404` without a prior read."""
    tenant = await _tenant(db_session, "TenantA")

    matched = await SqlAlchemyPropertyRepository(db_session).update_details(
        tenant.id, uuid.uuid4(), {"city": "Madrid"}
    )

    assert matched is False


@pytest.mark.asyncio
async def test_update_details_cannot_reach_another_tenants_property(db_session) -> None:
    """Indistinguishable from "no such property", which is what keeps the `404` honest."""
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    repository = SqlAlchemyPropertyRepository(db_session)
    theirs = _entity(tenant_b.id, internal_code="PAJARITOS8")
    await repository.add(tenant_b.id, theirs)

    matched = await repository.update_details(tenant_a.id, theirs.id, {"city": "Madrid"})

    assert matched is False
    assert (await _stored(db_session, theirs.id)).city is None


@pytest.mark.asyncio
async def test_the_operational_state_is_not_writable_through_update_details(db_session) -> None:
    """Refused, not filtered: a silently dropped key would let a caller believe it wrote (D3).

    This is the assertion that the route around `PropertyStateMachine` is *impossible* rather
    than merely ineffective, which is what `steering/backend.md` and `celery-jobs` R3.6 require.
    """
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    entity = _entity(tenant.id, internal_code="REDES11")
    await repository.add(tenant.id, entity)

    with pytest.raises(PropertyValidationError):
        await repository.update_details(
            tenant.id,
            entity.id,
            {"current_operational_state": PropertyOperationalState.OUT_OF_SERVICE},
        )

    assert (
        await _stored(db_session, entity.id)
    ).current_operational_state is PropertyOperationalState.VACANT_READY


@pytest.mark.asyncio
async def test_an_unknown_field_never_reaches_sql(db_session) -> None:
    """A rejected key is a programming error and surfaces as one, before any statement runs."""
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    entity = _entity(tenant.id, internal_code="REDES11")
    await repository.add(tenant.id, entity)

    with pytest.raises(PropertyValidationError):
        await repository.update_details(tenant.id, entity.id, {"not_a_column": "x"})


@pytest.mark.asyncio
async def test_the_wifi_password_is_not_writable_as_a_plain_column(db_session) -> None:
    """It must go through `set_wifi_password`, which is what encrypts it (R5.2)."""
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    entity = _entity(tenant.id, internal_code="REDES11")
    await repository.add(tenant.id, entity)

    with pytest.raises(PropertyValidationError):
        await repository.update_details(
            tenant.id, entity.id, {"wifi_password_encrypted": "en-claro"}
        )


@pytest.mark.asyncio
async def test_update_details_with_no_changes_is_a_caller_bug(db_session) -> None:
    """"Nothing changed" is decided by the use case, because it also governs the audit row."""
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    entity = _entity(tenant.id, internal_code="REDES11")
    await repository.add(tenant.id, entity)

    with pytest.raises(PropertyValidationError):
        await repository.update_details(tenant.id, entity.id, {})


@pytest.mark.asyncio
async def test_a_patch_onto_a_taken_internal_code_is_a_domain_error(db_session) -> None:
    """A rename collides on the same constraint an insert does."""
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    await repository.add(tenant.id, _entity(tenant.id, internal_code="REDES11"))
    second = _entity(tenant.id, internal_code="PAJARITOS8")
    await repository.add(tenant.id, second)

    with pytest.raises(DuplicateInternalCodeError):
        await repository.update_details(tenant.id, second.id, {"internal_code": "REDES11"})


@pytest.mark.asyncio
async def test_a_patch_onto_a_taken_pms_external_id_is_a_domain_error(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    await repository.add(
        tenant.id, _entity(tenant.id, internal_code="REDES11", pms_external_id="PMS-1")
    )
    second = _entity(tenant.id, internal_code="PAJARITOS8")
    await repository.add(tenant.id, second)

    with pytest.raises(DuplicatePmsExternalIdError):
        await repository.update_details(tenant.id, second.id, {"pms_external_id": "PMS-1"})


# --- set_wifi_password ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_wifi_password_stores_ciphertext_and_never_the_plaintext(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    entity = _entity(tenant.id, internal_code="REDES11")
    await repository.add(tenant.id, entity)
    secret = encrypt("otra-contrasena")

    matched = await repository.set_wifi_password(tenant.id, entity.id, secret)

    assert matched is True
    stored = await _stored(db_session, entity.id)
    assert stored.wifi_password_encrypted == secret.ciphertext
    assert "otra-contrasena" not in (stored.wifi_password_encrypted or "")


@pytest.mark.asyncio
async def test_set_wifi_password_to_none_clears_it(db_session) -> None:
    """Clearing is an operation, not the absence of one — hence `None` and not "if given"."""
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    entity = _entity(tenant.id, internal_code="REDES11")
    await repository.add(tenant.id, entity, wifi_secret=encrypt("la-que-habia"))

    matched = await repository.set_wifi_password(tenant.id, entity.id, None)

    assert matched is True
    assert (await _stored(db_session, entity.id)).wifi_password_encrypted is None


@pytest.mark.asyncio
async def test_set_wifi_password_cannot_reach_another_tenants_property(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    repository = SqlAlchemyPropertyRepository(db_session)
    theirs = _entity(tenant_b.id, internal_code="PAJARITOS8")
    await repository.add(tenant_b.id, theirs)

    matched = await repository.set_wifi_password(tenant_a.id, theirs.id, encrypt("mia"))

    assert matched is False
    assert (await _stored(db_session, theirs.id)).wifi_password_encrypted is None


# --- list ----------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_returns_only_the_tenants_properties(db_session) -> None:
    tenant_a = await _tenant(db_session, "TenantA")
    tenant_b = await _tenant(db_session, "TenantB")
    repository = SqlAlchemyPropertyRepository(db_session)
    mine = _entity(tenant_a.id, internal_code="REDES11")
    await repository.add(tenant_a.id, mine)
    await repository.add(tenant_b.id, _entity(tenant_b.id, internal_code="PAJARITOS8"))

    page = await repository.list(tenant_a.id, filters=_NO_FILTERS, page=1, per_page=10)

    assert page.total == 1
    assert [item.id for item in page.items] == [mine.id]


@pytest.mark.asyncio
async def test_list_counts_the_same_filtered_set_it_returns(db_session) -> None:
    """`total` drives `total_pages`, so a count over a different set would make paging lie."""
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    for index in range(3):
        await repository.add(tenant.id, _entity(tenant.id, internal_code=f"ACTIVE{index}"))
    await repository.add(
        tenant.id, _entity(tenant.id, internal_code="RETIRED", status=PropertyStatus.INACTIVE)
    )

    page = await repository.list(
        tenant.id, filters=PropertyFilters(status=PropertyStatus.ACTIVE), page=1, per_page=2
    )

    assert page.total == 3
    assert len(page.items) == 2


async def _seeded_in_state(
    repository: SqlAlchemyPropertyRepository,
    tenant_id: uuid.UUID,
    *,
    internal_code: str,
    status: PropertyStatus,
    state: PropertyOperationalState,
) -> None:
    """Insert a property and then move it, because that is the only route that exists.

    `add` refuses anything but `VACANT_READY` (R4.2), so a row cannot be born in another state —
    it has to be inserted and then transitioned, and `save` is the sanctioned writer of that
    column. Seeding this way rather than by writing a `PropertyModel` straight into the session
    exercises the real writers instead of bypassing them.

    **It is not the full production path, and the difference matters if you copy this helper**:
    in production `save` is called by `PropertyStateMachine`, which persists a
    `property_state_transitions` row in the same transaction (rule 9 of `steering/security.md`:
    "todo escritor de `current_operational_state` persiste su fila de
    `property_state_transitions` en la misma transacción"). This calls `save` bare, so the rows
    it leaves have no transition history. That is fine for a filtering fixture, which is all
    this is, and wrong for anything asserting on that history.
    """
    entity = _entity(tenant_id, internal_code=internal_code, status=status)
    await repository.add(tenant_id, entity)
    if state is not PropertyOperationalState.VACANT_READY:
        entity.current_operational_state = state
        await repository.save(tenant_id, entity)


@pytest.mark.asyncio
async def test_list_combines_its_filters_with_and(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    await _seeded_in_state(
        repository,
        tenant.id,
        internal_code="MATCH",
        status=PropertyStatus.ACTIVE,
        state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )
    # Matches each filter separately but not both, which is what tells AND from OR.
    await _seeded_in_state(
        repository,
        tenant.id,
        internal_code="STATE_ONLY",
        status=PropertyStatus.INACTIVE,
        state=PropertyOperationalState.OCCUPIED_ESTIMATED,
    )
    await _seeded_in_state(
        repository,
        tenant.id,
        internal_code="STATUS_ONLY",
        status=PropertyStatus.ACTIVE,
        state=PropertyOperationalState.VACANT_READY,
    )

    page = await repository.list(
        tenant.id,
        filters=PropertyFilters(
            status=PropertyStatus.ACTIVE,
            current_operational_state=PropertyOperationalState.OCCUPIED_ESTIMATED,
        ),
        page=1,
        per_page=10,
    )

    assert [item.internal_code for item in page.items] == ["MATCH"]


@pytest.mark.asyncio
async def test_paging_neither_repeats_nor_omits_when_names_collide(db_session) -> None:
    """The tie-break is what makes this true; without `id` the order is undefined.

    Every property here shares one name on purpose: that is the case a single-key sort gets
    wrong, and the failure mode is a client seeing one row twice while never seeing another.
    """
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    for index in range(5):
        await repository.add(
            tenant.id, _entity(tenant.id, internal_code=f"CODE{index}", name="El mismo nombre")
        )

    seen: list[uuid.UUID] = []
    for page_number in (1, 2, 3):
        page = await repository.list(
            tenant.id, filters=_NO_FILTERS, page=page_number, per_page=2
        )
        assert page.total == 5
        seen.extend(item.id for item in page.items)

    assert len(seen) == 5
    assert len(set(seen)) == 5


@pytest.mark.asyncio
async def test_a_page_beyond_the_end_is_empty_and_not_an_error(db_session) -> None:
    tenant = await _tenant(db_session, "TenantA")
    repository = SqlAlchemyPropertyRepository(db_session)
    await repository.add(tenant.id, _entity(tenant.id, internal_code="REDES11"))

    page = await repository.list(tenant.id, filters=_NO_FILTERS, page=9, per_page=10)

    assert page.items == ()
    assert page.total == 1
