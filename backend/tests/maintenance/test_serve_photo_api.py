"""`GET /api/v1/incident-photos/{photo_id}` over HTTP — the anonymous route (R4).

The use case's ordering is pinned one layer down, in
`tests/integrations/test_signed_serving_use_case.py`, where the sequence is observable. What
only this layer can show is the **shape of each answer**: the bytes, the headers, and above all
that the four refusals are one constant body.

Three properties are asserted literally rather than by status code, because a status code cannot
distinguish them:

* **the four `403`s are byte-identical** (R4.3). An invalid signature, an expired one, a
  tampered one and a photo that does not exist must be one answer, or an unauthenticated caller
  can use this route as an existence oracle over the photo keyspace.
* **the `Content-Type` comes only from the stored key's extension** (R4.5), so a polyglot that
  starts with `FF D8 FF` and carries HTML cannot be served as HTML.
* **`nosniff` carries exactly one value** (R4.5), even though both this route and the global
  response-header middleware stamp it.

Its own fixture rather than `conftest.py`'s `api`: this route needs three overrides that one does
not have — a session whose tenant marker is cleared per request (the unscoped read refuses a
bound one), a `LOCAL` root inside the test's own directory, and the **same** signing key on both
the factory that signs and the dependency that verifies.
"""

import time
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.integrations.api.dependencies import get_url_signing_key
from app.maintenance.api.dependencies import get_incident_photo_storage_factory
from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    derive_signing_key,
    sign_storage_key,
)
from app.integrations.infrastructure.storage import (
    INCIDENT_PHOTO_URL_PREFIX,
    ConfiguredFileStorageFactory,
)
from app.maintenance.domain.enums import IncidentStatus
from app.maintenance.infrastructure.models import IncidentPhotoModel
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel
from tests.conftest import request_session_override
from tests.maintenance.conftest import SECRET, auth_header, make_incident, world  # noqa: F401

INCIDENTS = "/api/v1/incidents"
PHOTOS = "/api/v1/incident-photos"

JPEG = b"\xff\xd8\xff" + b"\x11" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x22" * 64
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x33" * 64

pytestmark = pytest.mark.asyncio


def _signing_key() -> bytes:
    """The key the fixture signs AND verifies with, so a test can forge or inspect one."""
    return derive_signing_key(SECRET)


@pytest_asyncio.fixture
async def photo_api(db_session, tmp_path):
    from httpx import ASGITransport, AsyncClient

    from app.auth.api.dependencies import get_token_codec
    from app.auth.infrastructure.token_codec import JwtTokenCodec
    from app.core.db import get_db_session
    from app.main import create_app

    app = create_app()
    codec = JwtTokenCodec(secret=SECRET, access_minutes=15, refresh_days=7)

    # The marker an authenticated upload leaves behind would make the anonymous route's
    # `require_unmarked_session` refuse — a sequence production cannot perform, because
    # production opens one session per request.
    app.dependency_overrides[get_db_session] = request_session_override(db_session)
    app.dependency_overrides[get_token_codec] = lambda: codec
    # `LOCAL` rooted in the test's own directory rather than the real `/app/media` volume.
    # `maintenance`'s own factory dependency, carrying its own signed-URL prefix — overriding
    # `cleaning`'s would mint URLs pointing at the wrong route (see `storage_factory_for`).
    app.dependency_overrides[get_incident_photo_storage_factory] = (
        lambda: ConfiguredFileStorageFactory(
            signing_key=_signing_key(),
            local_root=tmp_path / "media",
            url_prefix=INCIDENT_PHOTO_URL_PREFIX,
        )
    )
    # And the SAME key for the serving route, which verifies what the factory above signed.
    # Both halves must be overridden together: leaving this one deriving from
    # `settings.jwt_secret_key` would make every URL in the file fail as a `403` that looks
    # like a broken signing scheme rather than like a broken fixture.
    app.dependency_overrides[get_url_signing_key] = _signing_key

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.codec = codec  # type: ignore[attr-defined]
        # Where this fixture's `LOCAL` adapter writes, so a test can delete what landed on disk
        # and drive the unreadable-object path.
        client.media_root = tmp_path / "media"  # type: ignore[attr-defined]
        yield client


async def _upload(photo_api, world, db_session, *, content=JPEG, name="photo.jpg"):
    """Upload through the real endpoint and hand back the minted URL.

    Deliberately not a hand-built URL: what this file tests is that the URL the API *gives* a
    client is the URL the API *honours*. A fixture that signed its own would prove only that
    the signing function is self-consistent.
    """
    incident = await make_incident(db_session, world, status=IncidentStatus.IN_PROGRESS)
    incident.assigned_technician_id = world.technician.id
    await db_session.flush()

    response = await photo_api.post(
        f"{INCIDENTS}/{incident.id}/photos",
        data={"stage": "BEFORE"},
        files={"file": (name, content, "image/jpeg")},
        headers=auth_header(photo_api, world.technician),
    )
    assert response.status_code == 201, response.text
    return response.json()


def _parts(url: str) -> tuple[str, str, str]:
    """`(photo_id, exp, sig)` out of a minted URL."""
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    return parsed.path.rsplit("/", 1)[-1], query["exp"][0], query["sig"][0]


async def _local(db_session, tenant_id) -> None:
    """Make the tenant `LOCAL`, which is what this route serves."""
    config = (
        await db_session.execute(
            select(TenantConfigModel).where(TenantConfigModel.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if config is None:
        db_session.add(TenantConfigModel(tenant_id=tenant_id, storage_type=StorageType.LOCAL))
    else:
        config.storage_type = StorageType.LOCAL
    await db_session.flush()


# --- the happy path (R4.1, R4.5) ------------------------------------------------------


@pytest.mark.parametrize(
    ("content", "name", "expected_type"),
    [
        (JPEG, "photo.jpg", "image/jpeg"),
        (PNG, "photo.png", "image/png"),
        (WEBP, "photo.webp", "image/webp"),
    ],
)
async def test_the_bytes_come_back_with_the_type_derived_from_the_key(
    photo_api, world, db_session, content, name, expected_type
):
    """R4.5 — the `Content-Type` is derived from the stored key's extension and nothing else.

    The declared upload type is always `image/jpeg` (see `_upload`), so for PNG and WebP the
    served type can only be right if it came from the key rather than from what the client said.
    """
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session, content=content, name=name)

    response = await photo_api.get(photo["url"])

    assert response.status_code == 200
    assert response.content == content
    assert response.headers["content-type"] == expected_type


async def test_the_route_needs_no_authorization_header(photo_api, world, db_session):
    """R4.1 — the whole reason it is anonymous: an `<img src>` sends no header."""
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)

    response = await photo_api.get(photo["url"], headers={})

    assert response.status_code == 200


async def test_the_bytes_carry_nosniff_exactly_once(photo_api, world, db_session):
    """R4.5 — "un solo valor", even though the route and the global middleware both stamp it.

    `_respond` writes rather than appends, so the two cannot add up to two. Asserted with
    `get_list` because a plain lookup would return the first of a duplicated pair and pass.
    """
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)

    response = await photo_api.get(photo["url"])

    assert response.headers.get_list("x-content-type-options") == ["nosniff"]


async def test_the_bytes_carry_a_private_cache_control_bounded_by_the_signature(
    photo_api, world, db_session
):
    """R4.5 — `private, max-age=<what is left of the signature>`."""
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)
    _, exp, _ = _parts(photo["url"])

    response = await photo_api.get(photo["url"])

    cache_control = response.headers["cache-control"]
    assert cache_control.startswith("private, max-age=")
    max_age = int(cache_control.rsplit("=", 1)[1])
    remaining = int(exp) - int(time.time())
    assert 0 < max_age <= SIGNED_URL_TTL_SECONDS
    # Within a couple of seconds of what is actually left, not merely under the ceiling.
    assert abs(max_age - remaining) <= 5


# --- the four refusals, one body (R4.3) -----------------------------------------------


async def test_every_refusal_branch_answers_the_same_body_byte_for_byte(
    photo_api, world, db_session
):
    """**The assertion this file exists for** (R4.3).

    R4.3 names four causes — invalid, expired, tampered, no such photo — and they collapse onto
    **three** branches of `verify_signed_key` plus the resolve step. Every one is driven here,
    and the naming is deliberate because an earlier version of this test got it wrong in a way
    that mattered:

    * `invalid` and `tampered_expiry` are the **same** branch (HMAC mismatch). `verify_signed_key`
      compares the HMAC *first*, and the signed payload covers the expiry — so altering `exp`
      while reusing a `sig` minted for the original never reaches the expiry check. Both are kept
      because they are different *attacks* on one branch, and the earlier version mistook one for
      the other.
    * `expired` needs a signature genuinely minted **over a past expiry**, so the HMAC matches
      and `expiry <= now` is what refuses. That branch was previously untested at this layer: the
      section 7-9 security panel found all three of the old test's cases landing on the mismatch
      branch.
    * `over_the_ceiling` is the third branch — a valid signature reaching past
      `SIGNED_URL_TTL_SECONDS`, refused even though it verifies and has not expired.
    * `absent` is the resolve step: a valid signature naming a photo that does not exist.

    If any of them differed by a single byte, an unauthenticated caller could walk the keyspace
    and learn which photo ids exist.
    """
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)
    photo_id, exp, sig = _parts(photo["url"])
    row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(photo["id"])
            )
        )
    ).scalar_one()
    now = int(time.time())

    def _signed(expiry: int) -> str:
        """A signature that really verifies over this photo's stored key."""
        return sign_storage_key(
            signing_key=_signing_key(), key=row.storage_key, expiry=expiry
        )

    past = now - 60
    beyond = now + SIGNED_URL_TTL_SECONDS + 600

    responses = {
        "invalid": await photo_api.get(
            f"{PHOTOS}/{photo_id}?exp={exp}&sig={'0' * len(sig)}"
        ),
        "tampered_expiry": await photo_api.get(
            f"{PHOTOS}/{photo_id}?exp={int(exp) + 60}&sig={sig}"
        ),
        "expired": await photo_api.get(f"{PHOTOS}/{photo_id}?exp={past}&sig={_signed(past)}"),
        "over_the_ceiling": await photo_api.get(
            f"{PHOTOS}/{photo_id}?exp={beyond}&sig={_signed(beyond)}"
        ),
        "absent": await photo_api.get(f"{PHOTOS}/{uuid.uuid4()}?exp={exp}&sig={sig}"),
    }

    assert {r.status_code for r in responses.values()} == {403}, {
        name: r.status_code for name, r in responses.items()
    }
    assert len({r.content for r in responses.values()}) == 1
    # Headers too: a differing `Cache-Control` or a stray header would be an oracle just as
    # surely as a differing body.
    assert len({r.headers["cache-control"] for r in responses.values()}) == 1


async def test_the_expired_and_over_ceiling_branches_are_really_reached(
    photo_api, world, db_session
):
    """Proof that the two signature-verifying branches above are not just mismatches again.

    A signature minted over a past expiry, and one minted past the TTL ceiling, both **verify**
    — `hmac.compare_digest` succeeds — so the refusal can only come from the expiry checks. This
    test exists because the previous version of the file believed it was exercising those
    branches when every case was landing on the mismatch branch instead.

    Asserted at the pure-function level, where the branch is observable by its message; the
    route deliberately collapses all three into one body, which is why the HTTP test above can
    only assert sameness.
    """
    from app.integrations.domain.storage import InvalidSignatureError, verify_signed_key

    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)
    row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(photo["id"])
            )
        )
    ).scalar_one()
    now = int(time.time())

    for expiry, expected in (
        (now - 60, "expired"),
        (now + SIGNED_URL_TTL_SECONDS + 600, "outlives"),
    ):
        signature = sign_storage_key(
            signing_key=_signing_key(), key=row.storage_key, expiry=expiry
        )
        with pytest.raises(InvalidSignatureError) as raised:
            verify_signed_key(
                signing_key=_signing_key(),
                key=row.storage_key,
                expiry=expiry,
                signature=signature,
                now=now,
            )
        # Not "does not match" — that would mean we were on the mismatch branch again.
        assert expected in str(raised.value)
        assert "does not match" not in str(raised.value)


async def test_every_refusal_carries_nosniff_and_no_store(photo_api, world, db_session):
    """R4.5 — the refusals are stamped too, which is the half an earlier version of the shared
    module got wrong for `cleaning` before it was extracted."""
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)
    photo_id, exp, sig = _parts(photo["url"])

    response = await photo_api.get(f"{PHOTOS}/{photo_id}?exp={exp}&sig={'0' * len(sig)}")

    assert response.status_code == 403
    assert response.headers.get_list("x-content-type-options") == ["nosniff"]
    assert response.headers["cache-control"] == "no-store"


async def test_a_signature_over_another_photos_key_is_refused(
    photo_api, world, db_session
):
    """The pivot the resolve-then-verify ordering forbids.

    This signature is cryptographically perfect — right key, right scheme, future expiry — over
    a **different** photo's storage key. Presenting it against this photo's id must fail,
    because the key the route verifies against comes from the database row and not from the
    request.

    **Two photos of the SAME tenant**, so this exercises the pivot mechanism without being
    cross-tenant evidence. The identical code path refuses a tenant-A signature against a
    tenant-B object — the storage key embeds the tenant and the signature covers the whole key —
    but that case is asserted in section 10, not here.
    """
    await _local(db_session, world.tenant.id)
    mine = await _upload(photo_api, world, db_session)
    theirs = await _upload(photo_api, world, db_session)

    other_row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(theirs["id"])
            )
        )
    ).scalar_one()
    photo_id, exp, _ = _parts(mine["url"])
    forged = sign_storage_key(
        signing_key=_signing_key(), key=other_row.storage_key, expiry=int(exp)
    )

    response = await photo_api.get(f"{PHOTOS}/{photo_id}?exp={exp}&sig={forged}")

    assert response.status_code == 403


async def test_a_missing_signature_is_a_422_and_not_an_oracle(
    photo_api, world, db_session
):
    """`exp` and `sig` are required, so their absence is FastAPI's `422`.

    That is not an oracle: it is a fact about the request, identical for a photo that exists
    and one that does not — which is what this asserts.
    """
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)
    photo_id, _, _ = _parts(photo["url"])

    existing = await photo_api.get(f"{PHOTOS}/{photo_id}")
    absent = await photo_api.get(f"{PHOTOS}/{uuid.uuid4()}")

    assert existing.status_code == absent.status_code == 422
    assert existing.json() == absent.json()


# --- the S3 tenant (R4.4) -------------------------------------------------------------


async def test_an_s3_tenant_answers_404(photo_api, world, db_session):
    """R4.4 — the browser goes straight to the provider, so there is nothing to serve here.

    Reachable only **after** a valid signature, so it is not an oracle: whoever gets this
    already held proof the photo exists.
    """
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)

    config = (
        await db_session.execute(
            select(TenantConfigModel).where(
                TenantConfigModel.tenant_id == world.tenant.id
            )
        )
    ).scalar_one()
    config.storage_type = StorageType.S3
    await db_session.flush()

    response = await photo_api.get(photo["url"])

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


# --- R4.3's other half: the key never appears -----------------------------------------


async def test_no_answer_of_this_route_publishes_the_storage_path(
    photo_api, world, db_session
):
    """Rule 5 of `steering/security.md` — never expose internal paths.

    The `LOCAL` adapter publishes only `Path(key).stem`, so the photo's UUID legitimately
    appears in the URL; the **path** must not appear in any body or header of any answer.

    **This is a leakage-shape property, NOT tenant isolation, and it is not evidence for R6.3.**
    The photo belongs to `world.tenant` and no second tenant exists in this test. Noted at the
    request of the section 7-9 tenancy panel, which found that none of the three routes had a
    genuine cross-tenant test and that tests like this one could be mistaken for one.
    """
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)
    photo_id, exp, sig = _parts(photo["url"])
    row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(photo["id"])
            )
        )
    ).scalar_one()

    served = await photo_api.get(photo["url"])
    refused = await photo_api.get(f"{PHOTOS}/{photo_id}?exp={exp}&sig={'0' * len(sig)}")

    for response in (served, refused):
        assert row.storage_key.encode() not in response.content
        assert b"tenants/" not in response.content
        for value in response.headers.values():
            assert row.storage_key not in value


async def test_an_unreadable_object_is_a_502(photo_api, world, db_session):
    """Task 8.3's last clause — the signature verified but the bytes are gone.

    Reachable only **after** a valid signature, so it is not an oracle: whoever gets this
    already held proof the photo exists. The file is deleted from the fixture's own `LOCAL`
    root, which is what makes `LocalFileReadPort.read` fail the way a partial deploy or a lost
    volume would.

    Added after the section 7-9 QA panel confirmed this clause had no test, and pointed at
    `tests/cleaning/test_serve_photo_api.py` for the recipe.
    """
    await _local(db_session, world.tenant.id)
    photo = await _upload(photo_api, world, db_session)
    row = (
        await db_session.execute(
            select(IncidentPhotoModel).where(
                IncidentPhotoModel.id == uuid.UUID(photo["id"])
            )
        )
    ).scalar_one()

    on_disk = photo_api.media_root / row.storage_key
    assert on_disk.exists(), "the upload should have written the object"
    on_disk.unlink()

    response = await photo_api.get(photo["url"])

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "BAD_GATEWAY"
    # A refusal, so it must not be cached.
    assert response.headers["cache-control"] == "no-store"
    assert response.headers.get_list("x-content-type-options") == ["nosniff"]
