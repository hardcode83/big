"""Behaviour of the property endpoints over the real app (R1, R2, R3, R4, R5, R7).

The tests that matter most here are the negative ones: that the wifi password cannot come back
out, that `current_operational_state` cannot go in, and that a neighbour's property is
indistinguishable from one that never existed.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.audit.infrastructure.models import AuditLogModel
from app.auth.domain.enums import UserRole
from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel
from app.timeline.infrastructure.models import TimelineEventModel
from tests.properties.conftest import auth_header

MANAGER = UserRole.PROPERTY_MANAGER

# Written out, never derived from `ROLE_PERMISSIONS`: a table computed from the catalogue would
# agree with any mistake in it. Same sets as `test_authorization.py`, kept as literals on purpose.
READERS = {UserRole.PROPERTY_MANAGER, UserRole.TENANT_OWNER}
MANAGERS = {UserRole.PROPERTY_MANAGER}
ALL_ROLES = list(UserRole)


def _manager(api, users_by_role_a):
    return auth_header(api, users_by_role_a[MANAGER])


async def _create(api, users_by_role_a, create_payload, **overrides):
    return await api.post(
        "/api/v1/properties",
        json=create_payload(**overrides),
        headers=_manager(api, users_by_role_a),
    )


# --- R2: creation ---


@pytest.mark.asyncio
async def test_a_property_is_created_and_starts_vacant_ready(
    api, users_by_role_a, create_payload
) -> None:
    """R4.1: the state is not chosen by the caller, it is the DDL default."""
    response = await _create(api, users_by_role_a, create_payload)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["internal_code"] == "REDES11"
    assert body["current_operational_state"] == "VACANT_READY"
    assert body["status"] == "ACTIVE"
    # Defaults the caller never sent, coming from the schema/DDL rather than from nowhere.
    assert body["country"] == "ES"
    assert body["timezone"] == "Europe/Madrid"
    assert body["default_check_in_time"] == "15:00:00"


@pytest.mark.asyncio
async def test_a_duplicate_internal_code_is_a_409(api, users_by_role_a, create_payload) -> None:
    """R2.5: translated from the named constraint, so it is race-free."""
    assert (await _create(api, users_by_role_a, create_payload)).status_code == 201

    response = await _create(api, users_by_role_a, create_payload)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_a_duplicate_pms_external_id_on_the_same_provider_is_a_409(
    api, users_by_role_a, create_payload
) -> None:
    """R2.7. Both rows leave `pms_provider` unset, so they land in the same index group."""
    assert (
        await _create(api, users_by_role_a, create_payload, pms_external_id="EXT-1")
    ).status_code == 201

    response = await _create(
        api, users_by_role_a, create_payload, internal_code="OTHER", pms_external_id="EXT-1"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_the_same_external_id_is_allowed_on_a_different_provider(
    api, users_by_role_a, create_payload
) -> None:
    """The other half of design D5: a tenant mid-migration is legitimate (ADR 0006 d.7).

    The provider has to be set at INSERT time, which is exactly why `CreatePropertyCommand`
    accepts it — creating both provider-less and moving one afterwards would transiently violate
    the index.
    """
    assert (
        await _create(
            api, users_by_role_a, create_payload, pms_external_id="EXT-1", pms_provider="BEDS24"
        )
    ).status_code == 201

    response = await _create(
        api,
        users_by_role_a,
        create_payload,
        internal_code="OTHER",
        pms_external_id="EXT-1",
        pms_provider="CHANNEX",
    )

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_a_tenant_id_in_the_body_is_rejected(api, users_by_role_a, create_payload) -> None:
    """R2.2: `extra="forbid"` means an injected tenant is a 422, not a silently ignored field."""
    response = await _create(api, users_by_role_a, create_payload, tenant_id=str(uuid.uuid4()))

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_operational_state_cannot_be_set_on_creation(
    api, users_by_role_a, create_payload
) -> None:
    """R4.1: `PropertyStateMachine` owns that column; the schema refuses to carry it."""
    response = await _create(
        api, users_by_role_a, create_payload, current_operational_state="OCCUPIED_ESTIMATED"
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_creating_a_property_writes_no_transition_and_no_timeline_event(
    api, users_by_role_a, create_payload, db_session
) -> None:
    """R4.4: creating is not transitioning.

    There is no `PROPERTY_CREATED` timeline type in `app/timeline/domain/enums.py`, and PRD
    §3.1 attaches the event obligation to a *transition*. A row in either table here would mean
    the create path invented a transition out of nothing.
    """
    assert (await _create(api, users_by_role_a, create_payload)).status_code == 201

    transitions = await db_session.scalar(
        select(func.count()).select_from(PropertyStateTransitionModel)
    )
    events = await db_session.scalar(select(func.count()).select_from(TimelineEventModel))

    assert int(transitions or 0) == 0
    assert int(events or 0) == 0


# --- R5: the secret ---


@pytest.mark.asyncio
async def test_the_wifi_password_is_stored_encrypted_and_never_returned(
    api, users_by_role_a, create_payload, db_session
) -> None:
    """R5.2, R5.4, and task 7.11 — checked on the serialised BODY, not just the schema."""
    plaintext = "una-clave-de-wifi"
    created = await _create(api, users_by_role_a, create_payload, wifi_password=plaintext)
    assert created.status_code == 201, created.text
    property_id = created.json()["id"]

    detail = await api.get(
        f"/api/v1/properties/{property_id}", headers=_manager(api, users_by_role_a)
    )
    listing = await api.get("/api/v1/properties", headers=_manager(api, users_by_role_a))

    for response in (created, detail, listing):
        # On the serialised body, not on the schema: a field added later would slip past a
        # schema-only assertion (task 7.11).
        assert plaintext not in response.text
        assert "wifi_password_encrypted" not in response.text
    assert created.json()["has_wifi_password"] is True
    assert detail.json()["has_wifi_password"] is True

    stored = await db_session.scalar(
        select(PropertyModel.wifi_password_encrypted).where(PropertyModel.id == uuid.UUID(property_id))
    )
    assert stored is not None
    assert stored != plaintext
    # Fernet tokens start with the version byte 0x80, which base64url-encodes to a leading "gAAAA".
    assert stored.startswith("gAAAA")


@pytest.mark.asyncio
async def test_a_property_without_a_wifi_password_reports_the_flag_false(
    api, users_by_role_a, create_payload
) -> None:
    created = await _create(api, users_by_role_a, create_payload)

    assert created.json()["has_wifi_password"] is False


@pytest.mark.asyncio
async def test_no_response_field_is_named_after_the_secret(
    api, users_by_role_a, create_payload
) -> None:
    """The response contract, asserted on keys: neither the value nor the ciphertext column."""
    created = await _create(api, users_by_role_a, create_payload, wifi_password="x")

    keys = set(created.json())
    assert "wifi_password" not in keys
    assert "wifi_password_encrypted" not in keys
    assert "has_wifi_password" in keys


# --- R3: patching ---


@pytest.mark.asyncio
async def test_a_patch_applies_only_the_fields_sent(
    api, users_by_role_a, create_payload
) -> None:
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"city": "Segovia"},
        headers=_manager(api, users_by_role_a),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["city"] == "Segovia"
    assert body["province"] == "Madrid"  # untouched


@pytest.mark.asyncio
async def test_a_null_on_a_not_null_column_is_a_422(
    api, users_by_role_a, create_payload
) -> None:
    """Design D9. `user-management` learned this the hard way with `{"email": null}`."""
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"name": None},
        headers=_manager(api, users_by_role_a),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_a_null_on_a_nullable_column_clears_it(
    api, users_by_role_a, create_payload
) -> None:
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"city": None},
        headers=_manager(api, users_by_role_a),
    )

    assert response.status_code == 200
    assert response.json()["city"] is None


@pytest.mark.asyncio
async def test_the_operational_state_cannot_be_patched(
    api, users_by_role_a, create_payload
) -> None:
    """R4.1 on the update path: absent from the schema AND from the allowlist."""
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"current_operational_state": "AWAITING_CLEANING"},
        headers=_manager(api, users_by_role_a),
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_pms_provider_cannot_be_patched(api, users_by_role_a, create_payload) -> None:
    """It answers `422` rather than a `200` that writes nothing (design D3).

    The field was briefly declared on the request while the allowlist never carried it, so
    `changes()` dropped it and the caller got a `200` for a write that never happened — the exact
    silent discard the adapter refuses for every other key. A manager repointing a property after
    rotating a credential would have been told it worked while the property kept syncing against
    the old provider. The provider is chosen at creation (D5) and the schema now says so.
    """
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"pms_provider": "CHANNEX"},
        headers=_manager(api, users_by_role_a),
    )

    assert response.status_code == 422, response.text
    # And the stored value is untouched, so the 422 is a refusal and not a rollback of a write
    # that partly happened.
    detail = await api.get(
        f"/api/v1/properties/{property_id}", headers=_manager(api, users_by_role_a)
    )
    assert detail.json()["pms_provider"] == create_payload().get("pms_provider")


@pytest.mark.parametrize(
    ("field", "length"),
    [("access_notes", 5001), ("cleaning_notes", 5001), ("wifi_password", 201)],
)
@pytest.mark.asyncio
async def test_a_value_longer_than_its_declared_cap_is_a_422(
    api, users_by_role_a, create_payload, field, length
) -> None:
    """R2.4. These four columns are `String()` with NO width in the DDL, so there is no database
    limit to fall back on — the cap exists only in the schema, and without a test nothing would
    notice if it were dropped. Unbounded, a multi-megabyte note is a successful write.
    """
    response = await _create(api, users_by_role_a, create_payload, **{field: "a" * length})

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_retiring_a_property_is_a_status_patch(
    api, users_by_role_a, create_payload
) -> None:
    """R3.4: there is no DELETE, and the row survives."""
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"status": "INACTIVE"},
        headers=_manager(api, users_by_role_a),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "INACTIVE"

    deleted = await api.delete(
        f"/api/v1/properties/{property_id}", headers=_manager(api, users_by_role_a)
    )
    assert deleted.status_code == 405


@pytest.mark.asyncio
async def test_a_patch_that_changes_nothing_writes_no_audit_row(
    api, users_by_role_a, create_payload, db_session
) -> None:
    """R3.3: `audit_logs` is evidence of change, not of requests."""
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]
    before = await db_session.scalar(select(func.count()).select_from(AuditLogModel))

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"city": "Madrid"},  # the value it already holds
        headers=_manager(api, users_by_role_a),
    )

    assert response.status_code == 200
    after = await db_session.scalar(select(func.count()).select_from(AuditLogModel))
    assert int(after or 0) == int(before or 0)


@pytest.mark.asyncio
async def test_an_empty_patch_body_writes_nothing(
    api, users_by_role_a, create_payload, db_session
) -> None:
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]
    before = await db_session.scalar(select(func.count()).select_from(AuditLogModel))

    response = await api.patch(
        f"/api/v1/properties/{property_id}", json={}, headers=_manager(api, users_by_role_a)
    )

    assert response.status_code == 200
    after = await db_session.scalar(select(func.count()).select_from(AuditLogModel))
    assert int(after or 0) == int(before or 0)


# --- R7: audit ---


@pytest.mark.asyncio
async def test_creating_writes_one_audit_row_without_the_secret(
    api, users_by_role_a, create_payload, db_session
) -> None:
    """R7.2, R7.4: one row per operation, and the password only as "it changed"."""
    plaintext = "clave-secreta"
    created = await _create(api, users_by_role_a, create_payload, wifi_password=plaintext)
    assert created.status_code == 201

    rows = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.entity_type == "PROPERTY")
        )
    ).scalars().all()

    assert len(rows) == 1
    entry = rows[0]
    assert entry.action == "PROPERTY_CREATED"
    assert entry.actor_user_id == users_by_role_a[MANAGER].id
    assert entry.changes["wifi_password_encrypted"] == {"changed": True}
    assert plaintext not in str(entry.changes)


@pytest.mark.asyncio
async def test_free_text_notes_are_audited_only_as_changed(
    api, users_by_role_a, create_payload, db_session
) -> None:
    """R5.5, design D7: an operator can paste a door code into "access notes"."""
    property_id = (await _create(api, users_by_role_a, create_payload)).json()["id"]

    response = await api.patch(
        f"/api/v1/properties/{property_id}",
        json={"access_notes": "el codigo del portal es 4321"},
        headers=_manager(api, users_by_role_a),
    )
    assert response.status_code == 200

    entry = (
        await db_session.execute(
            select(AuditLogModel).where(AuditLogModel.action == "PROPERTY_UPDATED")
        )
    ).scalars().one()

    assert entry.changes["access_notes"] == {"changed": True}
    assert "4321" not in str(entry.changes)


# The "a duplicate leaves no audit row" invariant is asserted in
# `test_property_admin.py::test_a_duplicate_never_reaches_the_audit_writer`, at the use-case
# level with fakes. Over HTTP it cannot be: the failed flush leaves the shared test session in
# `PendingRollbackError`, so the follow-up COUNT cannot run — an artefact of one session per test
# module, where production gives every request its own. Testing the ordering directly is also a
# stronger assertion than inferring it from row counts.


# --- R1 / R7: tenant isolation ---


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_a_neighbours_property_is_a_404_indistinguishable_from_a_missing_one(
    api, users_by_role_a, property_b, role
) -> None:
    """R1.6 and R7.6, for every one of the five roles rather than for the manager alone.

    The neighbour's row really exists, which is what makes this mean something. Both roles that
    hold `READ_PROPERTIES` reach the tenant-scoped lookup, so both must be shown to come back
    empty-handed — a scoping regression that special-cased one of them would otherwise go unseen.
    The three roles without the permission stop at `403`, before the resource is ever read, and
    that is its own guarantee: authorisation cannot depend on whether the row exists.

    Expectations are written out below, never derived from `ROLE_PERMISSIONS`.
    """
    expected = 404 if role in READERS else 403
    headers = auth_header(api, users_by_role_a[role])

    real = await api.get(f"/api/v1/properties/{property_b.id}", headers=headers)
    invented = await api.get(f"/api/v1/properties/{uuid.uuid4()}", headers=headers)

    assert real.status_code == invented.status_code == expected
    assert real.json() == invented.json()


@pytest.mark.parametrize("role", sorted(READERS, key=lambda r: r.value))
@pytest.mark.asyncio
async def test_the_listing_shows_only_the_callers_tenant(
    api, users_by_role_a, create_payload, property_b, role
) -> None:
    """R7.6: both readers, because both can list and both must see one row and not two."""
    assert (
        await _create(api, users_by_role_a, create_payload, internal_code="MINE")
    ).status_code == 201

    listing = await api.get(
        "/api/v1/properties", headers=auth_header(api, users_by_role_a[role])
    )

    body = listing.json()
    # `total` is asserted as well as the page: a count computed over an unscoped statement would
    # leak the neighbour's existence even while the page itself looked correct.
    assert body["total"] == 1
    assert [item["internal_code"] for item in body["data"]] == ["MINE"]


@pytest.mark.parametrize("role", ALL_ROLES)
@pytest.mark.asyncio
async def test_patching_a_neighbours_property_is_a_404(
    api, users_by_role_a, property_b, role
) -> None:
    """R7.6 on the write path. Only the manager may mutate, so everyone else stops at `403`."""
    expected = 404 if role in MANAGERS else 403
    response = await api.patch(
        f"/api/v1/properties/{property_b.id}",
        json={"city": "Segovia"},
        headers=auth_header(api, users_by_role_a[role]),
    )

    assert response.status_code == expected


# --- R1: pagination ---


@pytest.mark.asyncio
async def test_paging_neither_repeats_nor_skips_when_names_collide(
    api, users_by_role_a, create_payload
) -> None:
    """R1.3: the `id` tiebreaker is what makes this hold with four identical names."""
    for index in range(4):
        assert (
            await _create(
                api, users_by_role_a, create_payload, name="Same Name", internal_code=f"C{index}"
            )
        ).status_code == 201

    seen = []
    for page in (1, 2):
        response = await api.get(
            f"/api/v1/properties?page={page}&per_page=2", headers=_manager(api, users_by_role_a)
        )
        assert response.status_code == 200
        seen.extend(item["id"] for item in response.json()["data"])

    assert len(seen) == 4
    assert len(set(seen)) == 4


@pytest.mark.asyncio
async def test_the_page_bounds_are_enforced(api, users_by_role_a) -> None:
    """R1.2: `page` becomes a SQL OFFSET, so an unbounded value is a driver error, not a 422."""
    headers = _manager(api, users_by_role_a)

    assert (await api.get("/api/v1/properties?per_page=101", headers=headers)).status_code == 422
    assert (await api.get("/api/v1/properties?page=100001", headers=headers)).status_code == 422
    assert (await api.get("/api/v1/properties?page=0", headers=headers)).status_code == 422


@pytest.mark.asyncio
async def test_filters_combine_with_and(api, users_by_role_a, create_payload) -> None:
    """R1.4."""
    assert (await _create(api, users_by_role_a, create_payload, internal_code="A")).status_code == 201
    inactive = await _create(
        api, users_by_role_a, create_payload, internal_code="B", status="INACTIVE"
    )
    assert inactive.status_code == 201
    headers = _manager(api, users_by_role_a)

    active_only = await api.get("/api/v1/properties?status=ACTIVE", headers=headers)
    assert [item["internal_code"] for item in active_only.json()["data"]] == ["A"]

    both_filters = await api.get(
        "/api/v1/properties?status=INACTIVE&current_operational_state=VACANT_READY",
        headers=headers,
    )
    assert [item["internal_code"] for item in both_filters.json()["data"]] == ["B"]

    contradictory = await api.get(
        "/api/v1/properties?status=INACTIVE&current_operational_state=AWAITING_CLEANING",
        headers=headers,
    )
    assert contradictory.json()["total"] == 0
