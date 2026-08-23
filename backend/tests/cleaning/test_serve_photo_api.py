"""R3.3, R3.4, R6 — `GET /api/v1/cleaning-photos/{photo_id}`, the anonymous route, over ASGI.

**The single most exposed surface this change adds.** `api-ingress-routing` left `/api/v1`
reachable from the internet through the Cloudflare tunnel, and this route carries no token: the
HMAC in its query string is the whole of its authorisation (design D7). So the assertions here
are deliberately paranoid about the two things a status code alone does not show:

* **the refusal body is one constant** (task 4.3b). Four different reasons — wrong signature,
  expired, a signature belonging to another photo, and a photo that does not exist — are
  compared **byte for byte** against each other. `str(exc)` carries three distinct sentences
  through this path, and serialising any of them would make the endpoint an existence oracle
  over the photo keyspace for a caller with no credentials at all. A test on status codes would
  not notice.
* **the response carries `X-Content-Type-Options: nosniff` and a `Content-Type` derived from
  the stored key's extension** (task 4.3c). Without both, a polyglot that opens with `FF D8 FF`
  and carries HTML is stored XSS on the API's own origin. `nosniff` is asserted on **every**
  exit of the route, not only the `200`, because it was on only the `200` while the module
  claimed otherwise.
* **the bytes carry a `Cache-Control` that dies with the signature** (R3.1). The 3600 s expiry
  is enforced by `verify_signed_key` inside this application; without a directive it is
  invisible to the Cloudflare tunnel on the path, which is a shared cache and would be free to
  hold the bytes and replay them to anyone re-presenting an expired URL.

The ordering that makes the whole thing safe (resolve → verify → serve) is pinned one layer
down, in `tests/integrations/test_signed_serving_use_case.py`, where the sequence is
observable. It moved there with the use case itself when `incident-photos` (design D5) made
`maintenance` its second consumer; what stays here is `cleaning`'s route end to end.
"""

import time
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.auth.domain.enums import UserRole, UserStatus
from app.auth.infrastructure.models import UserModel
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.models import CleaningPhotoModel
from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    sign_storage_key,
)
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel
from tests.cleaning.conftest import auth_header, insert_task, signing_key

TASKS = "/api/v1/cleaning-tasks"
PHOTOS = "/api/v1/cleaning-photos"

JPEG = b"\xff\xd8\xff" + b"\x11" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x22" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x33" * 64


async def _insert_cleaner(session, tenant) -> UserModel:
    user = UserModel(
        id=uuid.uuid4(),
        tenant_id=tenant.id,
        name="Limpiadora",
        email=f"cleaner-{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x" * 60,
        role=UserRole.CLEANER,
        status=UserStatus.ACTIVE,
    )
    session.add(user)
    await session.flush()
    return user


@pytest_asyncio.fixture
async def cleaner_a(db_session, tenant_a):
    return await _insert_cleaner(db_session, tenant_a)


@pytest_asyncio.fixture
async def live_task_a(db_session, tenant_a, property_a, template_a, cleaner_a):
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner_a,
    )
    await db_session.flush()
    return task


async def _upload(api, task_id, user, *, content=JPEG, filename="photo.jpg"):
    """Upload through the real endpoint and hand back the signed URL it minted.

    Deliberately not a hand-built URL: what this module tests is that the URL the API *gives*
    a client is the URL the API *honours*, and a fixture that signed its own would prove only
    that the signing function is self-consistent.
    """
    response = await api.post(
        f"{TASKS}/{task_id}/photos",
        data={"photo_type": "kitchen"},
        files={"file": (filename, content, "image/jpeg")},
        headers=auth_header(api, user),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _parts(url: str) -> tuple[str, str, str]:
    """`(photo_id, exp, sig)` out of a minted URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return parsed.path.rsplit("/", 1)[-1], query["exp"][0], query["sig"][0]


def _url(photo_id, exp, sig) -> str:
    return f"{PHOTOS}/{photo_id}?exp={exp}&sig={sig}"


# --- the happy path ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_valid_signature_serves_the_bytes_with_no_token_at_all(
    api, live_task_a, cleaner_a
):
    """R3.3 — and note there is no `Authorization` header anywhere in this request."""
    uploaded = await _upload(api, live_task_a.id, cleaner_a)

    response = await api.get(uploaded["url"])

    assert response.status_code == 200
    assert response.content == JPEG


@pytest.mark.parametrize(
    ("content", "filename", "expected"),
    [
        (JPEG, "photo.jpg", "image/jpeg"),
        (PNG, "photo.jpg", "image/png"),
        (WEBP, "photo.jpg", "image/webp"),
    ],
)
@pytest.mark.asyncio
async def test_the_content_type_is_the_stored_extensions_and_the_response_says_nosniff(
    api, live_task_a, cleaner_a, content, filename, expected
):
    """Task 4.3c, both halves, and neither was checked by anyone before.

    The file name is `.jpg` and the declared type `image/jpeg` in all three cases, so the only
    way to answer `image/png` or `image/webp` is to have derived it from the extension the
    upload chose from the CONTENT (design D3/D5) — which is what
    `content_type_for_extension` is for.
    """
    uploaded = await _upload(api, live_task_a.id, cleaner_a, content=content, filename=filename)

    response = await api.get(uploaded["url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == expected
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_the_url_carries_the_photo_id_and_never_the_storage_key(
    api, db_session, live_task_a, cleaner_a
):
    """R3.2 — the URL is a response too, so the internal key may not be in it either."""
    uploaded = await _upload(api, live_task_a.id, cleaner_a)
    row = await db_session.scalar(
        select(CleaningPhotoModel).where(CleaningPhotoModel.id == uuid.UUID(uploaded["id"]))
    )

    photo_id, _, _ = _parts(uploaded["url"])

    assert photo_id == uploaded["id"]
    assert row.storage_key not in uploaded["url"]
    assert str(live_task_a.tenant_id) not in uploaded["url"]


# --- the refusals, and the one body they all share (task 4.3b) ------------------------


@pytest.mark.asyncio
async def test_a_tampered_signature_is_403(api, live_task_a, cleaner_a):
    uploaded = await _upload(api, live_task_a.id, cleaner_a)
    photo_id, exp, sig = _parts(uploaded["url"])
    tampered = ("0" if sig[0] != "0" else "1") + sig[1:]

    response = await api.get(_url(photo_id, exp, tampered))

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_an_expired_signature_is_403(api, db_session, live_task_a, cleaner_a):
    """Signed correctly, for a deadline that has passed. Rule 5 of `steering/security.md`.

    Built with the app's own signing key rather than by waiting an hour: `verify_signed_key`
    takes the clock as an argument precisely so expiry is testable, and the expiry here is real
    — the signature covers it, so moving it forward would invalidate the signature.
    """
    uploaded = await _upload(api, live_task_a.id, cleaner_a)
    row = await db_session.scalar(
        select(CleaningPhotoModel).where(CleaningPhotoModel.id == uuid.UUID(uploaded["id"]))
    )
    expired = 1_700_000_000
    signature = sign_storage_key(
        signing_key=signing_key(), key=row.storage_key, expiry=expired
    )

    response = await api.get(_url(uploaded["id"], expired, signature))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_a_signature_reaching_past_the_ttl_ceiling_is_403(
    api, db_session, live_task_a, cleaner_a
):
    """The URL itself is bound by the ceiling, not only whoever signed it (design D6)."""
    uploaded = await _upload(api, live_task_a.id, cleaner_a)
    row = await db_session.scalar(
        select(CleaningPhotoModel).where(CleaningPhotoModel.id == uuid.UUID(uploaded["id"]))
    )
    far = int(time.time()) + SIGNED_URL_TTL_SECONDS + 3600
    signature = sign_storage_key(signing_key=signing_key(), key=row.storage_key, expiry=far)

    response = await api.get(_url(uploaded["id"], far, signature))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_signature_of_another_photo_does_not_open_this_one(
    api, live_task_a, cleaner_a
):
    """The signature covers the whole key, so it cannot be moved to a neighbouring object.

    Both photos belong to the same task and the same tenant, which is the *hardest* case for
    this property: the two keys differ only in their last UUID.
    """
    first = await _upload(api, live_task_a.id, cleaner_a)
    second = await _upload(api, live_task_a.id, cleaner_a, content=PNG)
    _, other_exp, other_sig = _parts(second["url"])

    response = await api.get(_url(first["id"], other_exp, other_sig))

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_the_four_refusals_are_the_same_body_byte_for_byte(
    api, db_session, live_task_a, cleaner_a
):
    """Task 4.3b — **the assertion this route exists to be checked by.**

    `InvalidSignatureError` carries three different messages today and this path raises it on a
    fourth occasion. Mapping it the way the house maps every other domain error
    (`errors.py`: `message = str(exc)`) would leave four distinguishable bodies, and an
    unauthenticated caller could then separate "this photo id exists" from "it does not" — and
    through the key, one tenant's objects from another's — by reading the text. Status codes
    are compared too, but the bodies are what matters here.
    """
    uploaded = await _upload(api, live_task_a.id, cleaner_a)
    photo_id, exp, sig = _parts(uploaded["url"])
    row = await db_session.scalar(
        select(CleaningPhotoModel).where(CleaningPhotoModel.id == uuid.UUID(photo_id))
    )

    expired_at = 1_700_000_000
    expired_sig = sign_storage_key(
        signing_key=signing_key(), key=row.storage_key, expiry=expired_at
    )
    other = await _upload(api, live_task_a.id, cleaner_a, content=PNG)
    _, other_exp, other_sig = _parts(other["url"])

    tampered = await api.get(_url(photo_id, exp, "0" * 32))
    expired = await api.get(_url(photo_id, expired_at, expired_sig))
    wrong_photo = await api.get(_url(photo_id, other_exp, other_sig))
    # A photo that does not exist, presented with a signature that is perfectly well formed.
    missing = await api.get(_url(uuid.uuid4(), exp, sig))

    responses = [tampered, expired, wrong_photo, missing]
    assert [r.status_code for r in responses] == [403, 403, 403, 403]
    assert len({r.content for r in responses}) == 1, [r.text for r in responses]
    # And the shared body says nothing about which of the four happened.
    for word in ("expire", "match", "exist", "lifetime", "outlives"):
        assert word not in tampered.text.lower()


@pytest.mark.asyncio
async def test_a_photo_of_another_tenant_is_unreachable_without_its_signature(
    api, db_session, tenant_b, property_b, template_b, live_task_a, cleaner_a
):
    """R6 — knowing the UUID is not access, on the one route that has no session tenant.

    The neighbour's photo row is inserted directly, so the id is known exactly as it would be
    from a leaked log line. Without the signature over its key, the answer is the same constant
    403 an unknown id gets.
    """
    cleaner_b = await _insert_cleaner(db_session, tenant_b)
    task_b = await insert_task(
        db_session,
        tenant_b,
        property_b,
        template_b,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner_b,
    )
    foreign = CleaningPhotoModel(
        id=uuid.uuid4(),
        cleaning_task_id=task_b.id,
        uploaded_by=cleaner_b.id,
        photo_type="kitchen",
        storage_key=f"tenants/{tenant_b.id}/cleaning-tasks/{task_b.id}/{uuid.uuid4()}.jpg",
    )
    db_session.add(foreign)
    await db_session.flush()

    mine = await _upload(api, live_task_a.id, cleaner_a)
    _, exp, sig = _parts(mine["url"])

    stolen = await api.get(_url(foreign.id, exp, sig))
    unknown = await api.get(_url(uuid.uuid4(), exp, sig))

    assert stolen.status_code == 403
    assert stolen.content == unknown.content


# --- the backend that has no local serving --------------------------------------------


@pytest.mark.asyncio
async def test_an_s3_tenant_answers_404(api, db_session, tenant_a, live_task_a, cleaner_a):
    """Task 4.4 — with `storage_type = S3` there is no serving through the application.

    The photo is uploaded while the tenant is still `LOCAL` (an `S3` upload would need a bucket
    this deployment does not configure — design D2b's declared debt), and the configuration is
    flipped afterwards. That is also the honest reproduction of the real case: the column is
    deliberately not writable through the API, so in production it is set before any upload.
    """
    uploaded = await _upload(api, live_task_a.id, cleaner_a)

    config = await db_session.scalar(
        select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
    )
    config.storage_type = StorageType.S3
    await db_session.flush()

    response = await api.get(uploaded["url"])

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


# --- the headers every exit owes, not just the happy one --------------------------------


@pytest.mark.asyncio
async def test_every_refusal_carries_nosniff_too(
    api, db_session, tenant_a, live_task_a, cleaner_a, media_root
):
    """Task 4.3c — the header belongs to the route, and the module's docstring said so.

    It was true of the `200` alone: `_photo_response` passed `headers=_NOSNIFF` while the three
    refusals were bare `JSONResponse`s. All four now leave through `_respond`, and this pins
    every one of the three refusal branches — `403`, the `404` of an `S3` tenant, and the `502`
    of a row whose object is gone — so restoring a bare `JSONResponse` on any of them is red.
    """
    uploaded = await _upload(api, live_task_a.id, cleaner_a)
    photo_id, exp, sig = _parts(uploaded["url"])

    refused = await api.get(_url(photo_id, exp, "0" * 32))

    # 502: the signature is valid, the row is there, the object is not (design D4's forbidden
    # direction). Reached by deleting the object from under it.
    row = await db_session.scalar(
        select(CleaningPhotoModel).where(CleaningPhotoModel.id == uuid.UUID(photo_id))
    )
    (media_root / row.storage_key).unlink()
    unreadable = await api.get(uploaded["url"])

    # 404: the tenant's backend is S3, so nothing is served through the application.
    config = await db_session.scalar(
        select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_a.id)
    )
    config.storage_type = StorageType.S3
    await db_session.flush()
    no_local = await api.get(uploaded["url"])

    assert [refused.status_code, unreadable.status_code, no_local.status_code] == [403, 502, 404]
    for response in (refused, unreadable, no_local):
        assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_the_bytes_are_cacheable_only_privately_and_only_until_the_signature_dies(
    api, live_task_a, cleaner_a
):
    """R3.1 — the expiry the API enforces is now also stated to the caches on the path.

    `private` is the load-bearing token: the Cloudflare tunnel `api-ingress-routing` put in
    front of `/api/v1` is a shared cache, and a `200` with no directives leaves it free to
    store the bytes and replay them to whoever re-presents the URL after `exp` has passed. The
    browser may still keep its copy — the photo is immutable, its key ends in a UUID — but only
    for as long as the signature that bought it is alive.
    """
    uploaded = await _upload(api, live_task_a.id, cleaner_a)
    _, exp, _ = _parts(uploaded["url"])

    response = await api.get(uploaded["url"])

    assert response.status_code == 200
    directives = {d.strip() for d in response.headers["cache-control"].split(",")}
    assert "private" in directives
    assert "public" not in directives
    max_age = next(int(d.removeprefix("max-age=")) for d in directives if d.startswith("max-age="))
    # Alive, capped by the ceiling, and never outliving the signature it was cut from.
    seconds_left = int(exp) - int(time.time())
    assert 0 < max_age <= SIGNED_URL_TTL_SECONDS
    assert max_age <= seconds_left + 1


@pytest.mark.asyncio
async def test_a_refusal_is_never_stored_by_anything(api, live_task_a, cleaner_a):
    """A refusal is a verdict about this instant; a cache replaying it would answer for another.

    Also keeps the `404` of an `S3` tenant out of heuristic caching, which RFC 9111 otherwise
    allows for a response with no directives at all.
    """
    uploaded = await _upload(api, live_task_a.id, cleaner_a)
    photo_id, exp, _ = _parts(uploaded["url"])

    response = await api.get(_url(photo_id, exp, "0" * 32))

    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


# --- the shape of the request itself ---------------------------------------------------


@pytest.mark.asyncio
async def test_a_request_without_exp_or_sig_is_a_422_in_the_envelope(api, live_task_a, cleaner_a):
    """Not a 403: this is a malformed request, and the answer is identical whether or not the
    photo exists, so it is not an oracle either."""
    uploaded = await _upload(api, live_task_a.id, cleaner_a)

    present = await api.get(f"{PHOTOS}/{uploaded['id']}")
    absent = await api.get(f"{PHOTOS}/{uuid.uuid4()}")

    assert present.status_code == absent.status_code == 422
    assert present.json()["error"]["code"] == "VALIDATION_ERROR"
    assert present.content == absent.content
