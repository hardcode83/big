"""`GET /incidents/{incident_id}/context` over HTTP (R1, R2.5, R4, R5; design D4, D9, D10).

Everything here is asserted on the **serialised body**, not on the entity or the read model.
That is the whole point of the file: `tests/maintenance/test_incident_context_read_model.py`
pins the dataclass, and a projection that is right and a schema that dumps something else would
satisfy it. What a client actually receives is only visible here.

**On the tenant-isolation cases.** The cross-tenant `404` is asserted here for the shape of the
answer — R4.4's "cuerpo idéntico en los cuatro casos" is a property of the HTTP envelope and
nowhere else. It is deliberately **not** the proof that the isolation mechanism works: the `api`
fixture hands every request the same session, and an authenticated request marks it with the
caller's tenant, so `app/core/db.py`'s listener would filter a cross-tenant read even if the
explicit `tenant_id` filter were deleted.

That proof lives in `tests/maintenance/test_incident_context_use_case.py`, on the **unmarked**
session — and it is worth saying *which* test proves *which* crossing, because the obvious one
proves less than it looks:

* The **property** crossing (an incident of tenant A pointing at a property of tenant B, which is
  the case R4.6 names) is proved by `test_a_dangling_property_is_a_not_found_and_never_a_partial_answer`.
* The **incident** crossing is proved only by
  `test_the_incident_level_tenant_filter_is_load_bearing_on_its_own`, whose contrived shape is the
  point: every simpler arrangement is masked by a clause that refuses first — either the property
  lookup failing anyway, or `restrict_to_technician_id` not matching. Both maskings were measured
  by deleting the filter behind a monkeypatch, not argued from reading. Raised by the QA panel of
  sections 4-5.
"""

import uuid

import pytest

from app.maintenance.domain.enums import IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel
from app.properties.infrastructure.models import PropertyModel
from app.tenants.infrastructure.models import TenantModel
from tests.maintenance.conftest import (  # noqa: F401
    NOW,
    _user,
    api,
    auth_header,
    flow,
    make_incident,
    world,
)

pytestmark = pytest.mark.asyncio

INCIDENTS = "/api/v1/incidents"

#: The eleven fields of design D4, written out rather than derived from the dataclass: a set
#: computed from `IncidentContext.__dataclass_fields__` would agree with any mistake in it, and
#: this is the contract a client is written against.
CONTEXT_FIELDS = {
    "property_name",
    "property_internal_code",
    "address_line1",
    "address_line2",
    "city",
    "province",
    "postal_code",
    "country",
    "timezone",
    "access_notes",
    "assignment_note",
}

ACCESS_NOTES = "El código del portal es 4821."
ASSIGNMENT_NOTE = "El ascensor está averiado, sube andando."


async def _fill_property(db_session, world) -> None:
    prop = await db_session.get(PropertyModel, world.property.id)
    prop.address_line1 = "Calle de Redes 11"
    prop.address_line2 = "3º B"
    prop.city = "Madrid"
    prop.province = "Madrid"
    prop.postal_code = "28004"
    prop.access_notes = ACCESS_NOTES
    prop.cleaning_notes = "Aspira debajo del sofá."
    prop.emergency_notes = "Fontanero: 600 000 000."
    prop.wifi_name = "REDES11"
    await db_session.flush()


async def _assigned(api, world, db_session, *, note: str | None = ASSIGNMENT_NOTE):
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)
    body: dict = {"technician_id": str(world.technician.id)}
    if note is not None:
        body["assignment_note"] = note
    response = await api.post(
        f"{INCIDENTS}/{incident.id}/assign",
        json=body,
        headers=auth_header(api, world.manager),
    )
    assert response.status_code == 200
    return incident


def _context(incident_id) -> str:
    return f"{INCIDENTS}/{incident_id}/context"


# --- What the body carries (R1.1-R1.4) ---------------------------------------------------


async def test_the_assigned_technician_gets_exactly_the_eleven_fields(
    api, world, db_session
) -> None:
    """R1.1, R1.2, R1.4, R2.1, R3.3 — the **exact** key set, so a field added later is a
    deliberate act that reddens a test rather than a shape change a client discovers."""
    await _fill_property(db_session, world)
    incident = await _assigned(api, world, db_session)

    response = await api.get(_context(incident.id), headers=auth_header(api, world.technician))

    assert response.status_code == 200
    body = response.json()
    assert set(body) == CONTEXT_FIELDS
    assert body["property_name"] == "Redes 11"
    assert body["property_internal_code"] == "REDES11"
    assert body["address_line1"] == "Calle de Redes 11"
    assert body["city"] == "Madrid"
    assert body["country"] == "ES"
    assert body["timezone"] == "Europe/Madrid"
    assert body["access_notes"] == ACCESS_NOTES
    assert body["assignment_note"] == ASSIGNMENT_NOTE


async def test_a_null_column_travels_as_null_with_its_key(api, world, db_session) -> None:
    """R1.3 — the key does not vanish.

    No `exclude_none` anywhere in `backend/app`, so this is inherited pydantic behaviour rather
    than something the schema states — which is exactly why it is asserted against the body
    instead of being assumed. A client that has to tell "not informed" from "field removed"
    cannot do it if the key disappears.
    """
    incident = await _assigned(api, world, db_session, note=None)

    body = (
        await api.get(_context(incident.id), headers=auth_header(api, world.technician))
    ).json()

    assert set(body) == CONTEXT_FIELDS
    for nullable in (
        "address_line1",
        "address_line2",
        "city",
        "province",
        "postal_code",
        "access_notes",
        "assignment_note",
    ):
        assert nullable in body
        assert body[nullable] is None


ALWAYS_PRESENT = {"property_name", "property_internal_code", "country", "timezone"}
NULLABLE = CONTEXT_FIELDS - ALWAYS_PRESENT


async def test_the_operation_description_agrees_with_the_schema_about_nullability() -> None:
    """D10(b) — the description has to say what each `null` means, and be right about which
    fields can be one.

    This exists because the first version of that sentence said "every field can be `null`",
    which is false for four of the eleven: `property_name`, `property_internal_code`, `country`
    and `timezone` are `str` and not `str | None`. Prose about a contract drifts from the
    contract; the fix is not a better sentence but a test that fails when the two disagree.

    Both directions are asserted: the schema's actual optionality, and that the published
    description names each field on the side it belongs to. A description that named none of
    them would satisfy a one-directional check.
    """
    from typing import get_args

    from app.maintenance.api.schemas import IncidentContextResponse

    optional = {
        name
        for name, field in IncidentContextResponse.model_fields.items()
        if type(None) in get_args(field.annotation)
    }
    assert optional == NULLABLE
    assert set(IncidentContextResponse.model_fields) - optional == ALWAYS_PRESENT

    description = _published_description()
    head, marker, tail = description.partition(" are always present.")
    assert marker, "the description no longer makes the always-present claim at all"

    # Which SIDE of that sentence each field is named on, not merely that it is named
    # somewhere: naming all eleven in one list would satisfy a weaker check while saying
    # nothing true.
    for field in ALWAYS_PRESENT:
        assert f"`{field}`" in head, f"{field} is always present; the description does not say so"
        assert f"`{field}`" not in tail.split("can be `null`")[0], (
            f"{field} is listed among the nullable fields and it is not one"
        )
    for field in NULLABLE:
        assert f"`{field}`" in tail, f"{field} can be null; the description does not say so"
        assert f"`{field}`" not in head, (
            f"{field} is listed as always present and it is nullable"
        )


def _published_description() -> str:
    """The `description` as it reaches `backend/openapi.json`, not as the decorator wrote it.

    Read from the generated schema rather than from the route object, because the published
    contract is what D10 is about and what the frontend's types are derived from — and because
    the routers are nested inside included routers, so walking `app.routes` by name finds
    nothing.
    """
    from app.main import create_app

    schema = create_app().openapi()
    operation = schema["paths"]["/api/v1/incidents/{incident_id}/context"]["get"]
    return operation["description"]


# --- What the body never carries (R2.5, R5.2, R5.3, R5.4) --------------------------------


@pytest.mark.parametrize(
    "forbidden",
    [
        # R2.5, R5.2 — rule 3 grants no form for a WiFi password, and the derived flag is not
        # asked for by any requirement either.
        "wifi_password",
        "wifi_password_encrypted",
        "has_wifi_password",
        "wifi_name",
        # R5.2 — the two other free-text notes of `properties`, which this change deliberately
        # does not give a new reader (design D12). They ARE set on the fixture property, so this
        # would catch a `Property` dumped through `from_attributes`.
        "cleaning_notes",
        "emergency_notes",
        # R5.3 — no field of any reservation. PRD §12 does not ask for the booking here.
        "gross_amount",
        "ota_commission",
        "net_amount",
        "payment_status",
        "channel",
        "guest_id",
        "special_requests",
        "internal_notes",
        "reservation_id",
        # R5.4 — what `maintenance` R8 already keeps out of the incident contract.
        "reported_by_guest_token",
        "reported_by_user_id",
        "ai_classification",
        # And the identifiers a projection has no reason to publish.
        "id",
        "property_id",
        "tenant_id",
        "assigned_technician_id",
    ],
)
async def test_the_body_never_carries(api, world, db_session, forbidden: str) -> None:
    await _fill_property(db_session, world)
    incident = await _assigned(api, world, db_session)
    stored = await db_session.get(IncidentModel, incident.id)
    stored.reported_by_guest_token = "digest-of-a-portal-token"
    stored.ai_classification = {"category": "WATER", "confidence": "0.9"}
    await db_session.flush()

    body = (
        await api.get(_context(incident.id), headers=auth_header(api, world.technician))
    ).json()

    assert forbidden not in body


async def test_the_wifi_password_does_not_appear_under_any_key(
    api, world, db_session
) -> None:
    """The complement of the key-name check above: a value scan, so a password renamed into an
    innocent key would still be caught."""
    prop = await db_session.get(PropertyModel, world.property.id)
    prop.wifi_password_encrypted = "gAAAAABsecret-ciphertext"
    await db_session.flush()
    incident = await _assigned(api, world, db_session)

    raw = (
        await api.get(_context(incident.id), headers=auth_header(api, world.technician))
    ).text

    assert "gAAAAABsecret-ciphertext" not in raw


# --- Who reaches it, and the four identical refusals (R4) --------------------------------


@pytest.mark.parametrize("who", ["manager", "owner"])
async def test_a_manager_and_an_owner_reach_any_incident_of_their_tenant(
    api, world, db_session, who: str
) -> None:
    """R4.3 — driven on an incident assigned to somebody else, which is the only shape in which
    the absence of the technician restriction is visible."""
    await _fill_property(db_session, world)
    incident = await _assigned(api, world, db_session)
    user = world.manager if who == "manager" else world.owner

    response = await api.get(_context(incident.id), headers=auth_header(api, user))

    assert response.status_code == 200
    assert response.json()["access_notes"] == ACCESS_NOTES


async def test_the_four_refusals_are_one_indistinguishable_answer(
    api, world, db_session
) -> None:
    """R4.4 — an unknown incident, another tenant's, another technician's, and one whose
    property does not resolve inside the tenant, all answered identically.

    Asserted as one test over the four rather than four tests, because **sameness** is the
    requirement: four separate assertions of `404` would let the bodies drift apart into
    something a caller could use to tell "it exists and is not yours" from "it does not exist".
    """
    neighbour = TenantModel(name="TenantB", billing_email="b@example.com")
    db_session.add(neighbour)
    await db_session.flush()
    theirs_property = PropertyModel(
        tenant_id=neighbour.id, name="Otra", internal_code="OTRA"
    )
    db_session.add(theirs_property)
    await db_session.flush()
    theirs_incident = await make_incident(db_session, world)
    theirs_incident.tenant_id = neighbour.id
    theirs_incident.property_id = theirs_property.id
    await db_session.flush()

    mine = await _assigned(api, world, db_session)
    dangling = await _assigned(api, world, db_session)
    stored = await db_session.get(IncidentModel, dangling.id)
    stored.property_id = theirs_property.id
    await db_session.flush()

    technician = auth_header(api, world.technician)
    other = auth_header(api, world.other_technician)

    answers = [
        await api.get(_context(uuid.uuid4()), headers=technician),
        await api.get(_context(theirs_incident.id), headers=technician),
        await api.get(_context(mine.id), headers=other),
        await api.get(_context(dangling.id), headers=technician),
    ]

    for answer in answers:
        assert answer.status_code == 404
        assert answer.json()["error"]["code"] == "NOT_FOUND"
    bodies = {answer.text for answer in answers}
    assert len(bodies) == 1, bodies


async def test_a_cleaner_is_refused_before_the_database(api, world, db_session) -> None:
    """R4.1, R4.7 — `require(READ_INCIDENTS)` at the door, and `CLEANER` does not hold it.

    A `403` and not a `404`: the permission check runs before anything is loaded, so the answer
    cannot depend on whether the incident exists. That is not a leak — it says nothing about
    this incident, only about this role.
    """
    incident = await _assigned(api, world, db_session)
    cleaner = await _user(db_session, world.tenant, "CLEANER")

    response = await api.get(_context(incident.id), headers=auth_header(api, cleaner))

    assert response.status_code == 403


async def test_an_anonymous_caller_and_a_guest_token_reach_nothing(
    api, world, db_session
) -> None:
    """R4.7 — a bearer of a portal link is not an `AuthenticatedRequest`; `require(...)` only
    accepts the user JWT, so the token is simply not a credential here."""
    incident = await _assigned(api, world, db_session)

    assert (await api.get(_context(incident.id))).status_code == 401
    assert (
        await api.get(
            _context(incident.id),
            headers={"Authorization": "Bearer a-guest-portal-token-not-a-jwt"},
        )
    ).status_code == 401


# --- The route accepts nothing from the caller but the id (R4.5) -------------------------


async def test_the_route_accepts_no_tenant_id_and_no_scope_parameter(
    api, world, db_session
) -> None:
    """R4.5 and R4.2 — there is no parameter to widen, which is stronger than one that is
    ignored: a query string cannot be omitted into a wider scope if it never existed.

    An unknown query parameter is silently dropped by FastAPI rather than rejected, so what is
    asserted is that it changes **nothing** — the technician still sees only their own incident.
    """
    mine = await _assigned(api, world, db_session)
    other = await _assigned(api, world, db_session)
    stored = await db_session.get(IncidentModel, other.id)
    stored.assigned_technician_id = world.other_technician.id
    await db_session.flush()
    technician = auth_header(api, world.technician)

    widened = await api.get(
        _context(other.id),
        params={
            "tenant_id": str(uuid.uuid4()),
            "assigned_technician_id": str(world.other_technician.id),
        },
        headers=technician,
    )
    own = await api.get(_context(mine.id), headers=technician)

    assert widened.status_code == 404
    assert own.status_code == 200
