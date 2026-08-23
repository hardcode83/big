"""The two authenticated photo endpoints over HTTP (R2, R3; design D10, D11).

Through the real app, not the use cases: what these add over `test_photo_upload_use_case.py`
and `test_photo_listing_use_case.py` is the half that only exists at this layer — `require(...)`,
the PRD §23 error envelope, the `Form()` coercion of `stage`, the multipart binding, and above
all **the serialised response body**, which is where R3.3 is either kept or broken.

The assertion this file exists for is `test_no_response_of_either_route_carries_the_storage_key`:
it reads the raw bytes of every response rather than the schema's field list, because a field
list is a claim about the code and the bytes are the fact.
"""

import uuid

import pytest
from sqlalchemy import select

from app.integrations.domain.storage import StorageWriteError
from app.maintenance.application.use_cases import UploadIncidentPhotoUseCase
from app.maintenance.api.dependencies import (
    SessionDep,
    StorageFactoryDep,
    get_incident_photo_storage_factory,
    get_upload_incident_photo_use_case,
)
from app.maintenance.domain.enums import IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel, IncidentPhotoModel
from tests.maintenance.conftest import (  # noqa: F401
    api,
    auth_header,
    make_incident,
    world,
)

JPEG = b"\xff\xd8\xff" + b"padding-that-is-not-inspected"
PNG = b"\x89PNG\r\n\x1a\n" + b"more"
PDF = b"%PDF-1.7\nnot an image at all"

pytestmark = pytest.mark.asyncio


async def _in_progress(db_session, world) -> IncidentModel:
    """An incident assigned to `world.technician` and `IN_PROGRESS` — the state that accepts."""
    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    incident.assigned_technician_id = world.technician.id
    await db_session.flush()
    return incident


def _upload_body(content: bytes = JPEG, *, stage: str = "BEFORE", name: str = "x.jpg"):
    return {"files": {"file": (name, content, "image/jpeg")}, "data": {"stage": stage}}


async def _post(api, world, incident, user=None, **kwargs):
    body = _upload_body(**kwargs)
    return await api.post(
        f"/api/v1/incidents/{incident.id}/photos",
        headers=auth_header(api, user or world.technician),
        files=body["files"],
        data=body["data"],
    )


async def _get(api, world, incident, user=None):
    return await api.get(
        f"/api/v1/incidents/{incident.id}/photos",
        headers=auth_header(api, user or world.technician),
    )


# --- the upload (R2) ------------------------------------------------------------------


async def test_the_upload_answers_201_with_the_photo_and_a_url(api, world, db_session):
    """R2.1 — and the row really landed, which a `201` alone does not prove."""
    incident = await _in_progress(db_session, world)

    response = await _post(api, world, incident)

    assert response.status_code == 201
    body = response.json()
    assert body["incident_id"] == str(incident.id)
    assert body["stage"] == "BEFORE"
    assert body["uploaded_by"] == str(world.technician.id)
    assert body["url"]

    rows = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.incident_id == incident.id
            )
        )
    ).scalars().all()
    assert [str(row.id) for row in rows] == [body["id"]]


async def test_the_response_body_enumerates_exactly_six_fields(api, world, db_session):
    """R3.3/D10 — the schema is built by `from_upload`, never dumped from the entity.

    Asserted as an exact key set: a `from_attributes` dump would add `storage_key` and
    `tenant_id`, and this is the test that would go red.
    """
    incident = await _in_progress(db_session, world)

    response = await _post(api, world, incident)

    assert set(response.json()) == {
        "id",
        "incident_id",
        "stage",
        "uploaded_by",
        "created_at",
        "url",
    }


@pytest.mark.parametrize("stage", ["BEFORE", "AFTER"])
async def test_both_stages_are_accepted(api, world, db_session, stage):
    incident = await _in_progress(db_session, world)

    response = await _post(api, world, incident, stage=stage)

    assert response.status_code == 201
    assert response.json()["stage"] == stage


async def test_several_photos_of_the_same_stage_are_accepted(api, world, db_session):
    """R1.4 through HTTP: two angles of one fault, both `201`, two distinct rows."""
    incident = await _in_progress(db_session, world)

    first = await _post(api, world, incident, stage="AFTER")
    second = await _post(api, world, incident, stage="AFTER")

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]


async def test_the_client_file_name_reaches_nothing(api, world, db_session):
    """Design D4/R1.5 — the name is untrusted input and is simply not used.

    A hostile name is used so that if it ever *did* reach the key, the failure would be loud
    rather than cosmetic.
    """
    incident = await _in_progress(db_session, world)

    response = await _post(
        api, world, incident, name="../../etc/passwd\x00.jpg"
    )

    assert response.status_code == 201
    row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(response.json()["id"])
            )
        )
    ).scalar_one()
    assert "etc/passwd" not in row.storage_key
    assert row.storage_key.endswith(".jpg")
    assert row.storage_key.startswith(f"tenants/{world.tenant.id}/incidents/{incident.id}/")


# --- the three distinguishable 409s (R2.4, R2.5, R2.6) --------------------------------


async def test_a_closed_incident_is_a_409(api, world, db_session):
    incident = await make_incident(db_session, world, status=IncidentStatus.RESOLVED)
    incident.assigned_technician_id = world.technician.id
    await db_session.flush()

    response = await _post(api, world, incident)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"


async def test_an_incident_awaiting_the_owner_is_a_409(api, world, db_session):
    incident = await make_incident(
        db_session, world, status=IncidentStatus.AWAITING_OWNER_APPROVAL
    )
    incident.assigned_technician_id = world.technician.id
    await db_session.flush()

    response = await _post(api, world, incident)

    assert response.status_code == 409


async def test_a_step_out_of_order_is_a_409(api, world, db_session):
    incident = await make_incident(db_session, world, status=IncidentStatus.ASSIGNED)
    incident.assigned_technician_id = world.technician.id
    await db_session.flush()

    response = await _post(api, world, incident)

    assert response.status_code == 409


async def test_the_three_409s_carry_three_different_messages(api, world, db_session):
    """R2.4/R2.5/R2.6 and design D6 — "distinguishable" is about the message, not the code.

    All three are `409 CONFLICT`; if the API collapsed them the caller could not tell "wait
    for the owner" from "this incident is closed for ever", which are opposite instructions.
    """
    messages = set()
    for status in (
        IncidentStatus.RESOLVED,
        IncidentStatus.AWAITING_OWNER_APPROVAL,
        IncidentStatus.ASSIGNED,
    ):
        incident = await make_incident(db_session, world, status=status)
        incident.assigned_technician_id = world.technician.id
        await db_session.flush()

        response = await _post(api, world, incident)

        assert response.status_code == 409
        messages.add(response.json()["error"]["message"])

    assert len(messages) == 3


# --- format, stage and size (R2.9, R2.10) ---------------------------------------------


async def test_a_non_image_is_a_422(api, world, db_session):
    """R2.9 — and the declared `Content-Type` is a valid image type, which is the point.

    `_upload_body` always sends `image/jpeg`. Here the bytes are a PDF, so a route that
    trusted the header would answer `201`.
    """
    incident = await _in_progress(db_session, world)

    response = await _post(api, world, incident, content=PDF)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_an_unknown_stage_is_a_422_and_not_a_404(api, world, db_session):
    """R2.10/D11 — the admissible stages are a closed enum, not rows of a template.

    `cleaning` answers `404` for an unknown `photo_type` because that names a row whose
    existence could be probed. Here there is no such row, so `404` would be the wrong answer
    and FastAPI's `422` is both correct and free.
    """
    incident = await _in_progress(db_session, world)

    response = await _post(api, world, incident, stage="SIDEWAYS")

    assert response.status_code == 422


async def test_a_missing_stage_is_a_422(api, world, db_session):
    incident = await _in_progress(db_session, world)

    response = await api.post(
        f"/api/v1/incidents/{incident.id}/photos",
        headers=auth_header(api, world.technician),
        files={"file": ("x.jpg", JPEG, "image/jpeg")},
    )

    assert response.status_code == 422


async def test_a_missing_file_is_a_422(api, world, db_session):
    incident = await _in_progress(db_session, world)

    response = await api.post(
        f"/api/v1/incidents/{incident.id}/photos",
        headers=auth_header(api, world.technician),
        data={"stage": "BEFORE"},
    )

    assert response.status_code == 422


# --- the shared 404 (R2.3, R3.4) ------------------------------------------------------


async def test_an_unknown_incident_is_a_404_on_both_routes(api, world):
    ghost = uuid.uuid4()

    posted = await api.post(
        f"/api/v1/incidents/{ghost}/photos",
        headers=auth_header(api, world.technician),
        files={"file": ("x.jpg", JPEG, "image/jpeg")},
        data={"stage": "BEFORE"},
    )
    listed = await api.get(
        f"/api/v1/incidents/{ghost}/photos",
        headers=auth_header(api, world.technician),
    )

    assert posted.status_code == 404
    assert listed.status_code == 404
    assert posted.json()["error"]["code"] == "NOT_FOUND"


async def test_a_technician_who_is_not_the_assignee_gets_the_same_404(
    api, world, db_session
):
    """R2.3 — byte-identical to the unknown-incident answer, so the route is not a probe.

    **This is row-level scoping, NOT tenant isolation, and it is not evidence for R6.3.** Both
    technicians belong to `world.tenant`; what it demonstrates is that the assignee restriction
    holds inside one tenant. The cross-tenant assertion R6.3 requires lives in section 10's
    `test_photo_isolation.py`, and the section 7-9 tenancy panel asked for this note explicitly
    so that a future reader does not count this test toward that requirement.
    """
    incident = await _in_progress(db_session, world)

    mine = await _post(api, world, incident, user=world.technician)
    theirs = await _post(api, world, incident, user=world.other_technician)
    ghost = await api.post(
        f"/api/v1/incidents/{uuid.uuid4()}/photos",
        headers=auth_header(api, world.other_technician),
        files={"file": ("x.jpg", JPEG, "image/jpeg")},
        data={"stage": "BEFORE"},
    )

    assert mine.status_code == 201
    assert theirs.status_code == 404
    # The whole body, not just the code: R2.3 says indistinguishable.
    assert theirs.json() == ghost.json()


# --- the listing (R3) -----------------------------------------------------------------


async def test_the_listing_is_oldest_first_and_wrapped_in_items(api, world, db_session):
    incident = await _in_progress(db_session, world)
    first = await _post(api, world, incident, stage="BEFORE")
    second = await _post(api, world, incident, stage="AFTER")

    response = await _get(api, world, incident)

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["id"] for item in items] == [first.json()["id"], second.json()["id"]]
    assert [item["stage"] for item in items] == ["BEFORE", "AFTER"]


async def test_an_incident_with_no_photos_lists_an_empty_envelope(api, world, db_session):
    incident = await _in_progress(db_session, world)

    response = await _get(api, world, incident)

    assert response.status_code == 200
    assert response.json() == {"items": []}


async def test_every_listed_photo_carries_a_url(api, world, db_session):
    incident = await _in_progress(db_session, world)
    await _post(api, world, incident)

    response = await _get(api, world, incident)

    assert all(item["url"] for item in response.json()["items"])


# --- R3.3, the assertion this file exists for -----------------------------------------


async def test_no_response_of_either_route_carries_the_storage_key(
    api, world, db_session
):
    """R3.3 — asserted against the **raw bytes** of the response, not the schema's field list.

    A field list is a claim about the code; the bytes are the fact. This is what the security
    panel of `cleaning`'s section 5 asked for at this layer, and the same reasoning applies
    here: the key is the one string the design works to keep private, and the only way to know
    it did not travel is to look at what travelled.

    Both the literal key and its bare UUID stem are searched: the `LOCAL` adapter publishes
    `Path(key).stem`, so the stem legitimately appears inside the signed URL — what must not
    appear is the **path**.
    """
    incident = await _in_progress(db_session, world)
    created = await _post(api, world, incident)
    listed = await _get(api, world, incident)

    row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(created.json()["id"])
            )
        )
    ).scalar_one()

    for response in (created, listed):
        assert row.storage_key not in response.text
        assert "storage_key" not in response.text
        assert "tenants/" not in response.text
        for header in response.headers.values():
            assert row.storage_key not in header


# --- the two dependency-failure paths (R2.8, R5.1) ------------------------------------
#
# Both need a dependency override, which is why they sit apart from the rest: the fixture
# cannot pose "the object store is down" or "the ceiling is 16 bytes" on its own. Both recipes
# are `tests/cleaning/test_photos_api.py`'s, deliberately — the two upload paths are
# near-identical by design and keeping the test shapes aligned is what makes a divergence
# visible.


def _use_case_with_a_tiny_ceiling(
    session: SessionDep, storage: StorageFactoryDep
) -> UploadIncidentPhotoUseCase:
    """The real builder, with only `_max_bytes` reached into.

    Built by calling `get_upload_incident_photo_use_case` so the wiring stays single-sourced —
    a hand-assembled copy here would keep passing after somebody changed which repositories the
    use case takes. Only `_max_bytes` is overridden, which is exactly the one value under test,
    and lowering it here is what keeps the middleware at its real 10 MiB.
    """
    use_case = get_upload_incident_photo_use_case(session, storage)
    use_case._max_bytes = 16
    return use_case


async def test_a_file_over_the_use_cases_ceiling_is_413(api, world, db_session):
    """R5.1's second check, over HTTP.

    The **use case's** ceiling is lowered on its own — the middleware keeps its real 10 MiB — so
    what answers here is unambiguously the streaming counter and not `MaxBodySizeMiddleware`,
    whose per-path ceilings `test_photo_body_limit.py` pins separately.

    Added after the section 7-9 QA panel pointed out that `test_photo_body_limit.py` asserts the
    *resolved ceiling per path* and never observes a real `413` from the route.
    """
    incident = await _in_progress(db_session, world)
    overrides = api.asgi_app.dependency_overrides
    overrides[get_upload_incident_photo_use_case] = _use_case_with_a_tiny_ceiling
    try:
        response = await _post(api, world, incident)
    finally:
        del overrides[get_upload_incident_photo_use_case]

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    assert "16 byte" in response.json()["error"]["message"]


async def test_a_storage_failure_is_a_502_and_leaves_no_row(api, world, db_session):
    """R2.8 — the store refused, so no row exists and the answer is a `502`, not a `500`.

    The distinction the code carries is "retrying may work", not "our bug": a `500` would take
    the `Unexpected maintenance error` branch of the handler and throw away the one thing the
    caller can act on. And design D7's ordering is what makes "no row" true — the object goes
    first, so a failed `put` has nothing to compensate.
    """

    class RefusingStorage:
        async def put(self, key, content, *, content_type):
            raise StorageWriteError("the bucket is on fire")

        def signed_url(self, key, *, expires_in=3600):  # pragma: no cover - never reached
            return ""

        async def delete(self, key):  # pragma: no cover - never reached
            return None

    class RefusingFactory:
        def storage_for(self, storage_type):
            return RefusingStorage()

        def read_for(self, storage_type):  # pragma: no cover - not used by the upload
            raise NotImplementedError

    incident = await _in_progress(db_session, world)
    overrides = api.asgi_app.dependency_overrides
    overrides[get_incident_photo_storage_factory] = RefusingFactory
    try:
        response = await _post(api, world, incident)
    finally:
        del overrides[get_incident_photo_storage_factory]

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "BAD_GATEWAY"
    assert (
        await db_session.scalar(
            select(IncidentPhotoModel.id).where(
                IncidentPhotoModel.incident_id == incident.id
            )
        )
        is None
    )
