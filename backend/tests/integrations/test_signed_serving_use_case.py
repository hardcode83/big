"""`ServeSignedObjectUseCase`: **the order is the guarantee**.

The anonymous serving route resolves the object's row *without a tenant*, rebuilds the storage
key from it, and only **then** verifies the signature. That ordering is the entire security
argument of the endpoint — the signature covers the whole key, which begins with
`tenants/{tenant_id}/`, so a signature that verifies proves the caller was handed a URL minted
for that object of that tenant — and an implementation that got it backwards would still pass
every status-code assertion in the routes' API tests.

So every fake here writes into one shared `journal`, and the tests assert on the sequence, not
only on the outcome.

The other thing only a fake can pin: that the key fed to the verifier is the one from the
database and not one the caller could influence.
`test_a_signature_over_the_key_the_caller_wishes_for_is_refused` builds a signature that is
cryptographically perfect over a *different* key and watches it fail.

**This file moved here from `tests/cleaning/test_serve_photo_use_case.py`** when the change
`incident-photos` extracted the use case out of `cleaning` (design D5). The assertions are the
ones that guarded `cleaning`'s route, unchanged: they now guard the one implementation both
`cleaning` and `maintenance` mount, which is the whole point of extracting it. Each consumer's
own API test still pins its route end to end.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.integrations.application.signed_serving import ServeSignedObjectUseCase
from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    InvalidSignatureError,
    LocalFileReadUnsupportedError,
    ObjectLocation,
    StorageWriteError,
    derive_signing_key,
    sign_storage_key,
)
from app.tenants.domain.enums import StorageType

NOW = datetime(2026, 8, 9, 10, 0, tzinfo=UTC)
NOW_POSIX = int(NOW.timestamp())
TENANT = uuid.uuid4()
TASK = uuid.uuid4()
PHOTO = uuid.uuid4()
KEY = f"tenants/{TENANT}/cleaning-tasks/{TASK}/{PHOTO}.jpg"
BYTES = b"\xff\xd8\xff-these-are-the-object-bytes"

SIGNING_KEY = derive_signing_key("a-secret-that-is-long-enough-to-be-plausible")


# --- fakes, all writing into one journal ----------------------------------------------


class FakeLocationQuery:
    def __init__(self, journal: list[str], location: ObjectLocation | None) -> None:
        self._journal = journal
        self._location = location
        self.asked: list[uuid.UUID] = []

    async def locate_without_tenant_scoping(self, object_id):
        self._journal.append("locate")
        self.asked.append(object_id)
        return self._location


class FakeConfigRepository:
    def __init__(self, journal: list[str], storage_type: StorageType) -> None:
        self._journal = journal
        self._storage_type = storage_type
        self.asked: list[uuid.UUID] = []

    async def get_or_create(self, tenant_id, now):
        self._journal.append("config")
        self.asked.append(tenant_id)

        class _Config:
            storage_type = self._storage_type

        return _Config()


class FakeReader:
    def __init__(self, journal: list[str], *, fail: bool = False) -> None:
        self._journal = journal
        self._fail = fail
        self.read_keys: list[str] = []

    async def read(self, key):
        self._journal.append("read")
        self.read_keys.append(key)
        if self._fail:
            raise StorageWriteError("the object is not on disk")
        return BYTES


class FakeStorageFactory:
    def __init__(
        self, journal: list[str], reader: FakeReader, *, local: bool = True
    ) -> None:
        self._journal = journal
        self._reader = reader
        self._local = local

    def read_for(self, storage_type):
        self._journal.append("read_for")
        if not self._local:
            raise LocalFileReadUnsupportedError(
                f"storage_type {storage_type.value} serves objects from the provider"
            )
        return self._reader


def _build(
    *,
    location: ObjectLocation | None = ObjectLocation(
        storage_key=KEY, tenant_id=TENANT
    ),
    storage_type: StorageType = StorageType.LOCAL,
    local: bool = True,
    read_fails: bool = False,
):
    journal: list[str] = []
    locations = FakeLocationQuery(journal, location)
    configs = FakeConfigRepository(journal, storage_type)
    reader = FakeReader(journal, fail=read_fails)
    factory = FakeStorageFactory(journal, reader, local=local)
    use_case = ServeSignedObjectUseCase(
        locations=locations,
        configs=configs,
        storage=factory,
        signing_key=SIGNING_KEY,
    )
    return use_case, journal, locations, configs, reader


def _valid(key: str = KEY, *, expiry: int | None = None) -> tuple[int, str]:
    expiry = expiry if expiry is not None else NOW_POSIX + SIGNED_URL_TTL_SECONDS
    return expiry, sign_storage_key(signing_key=SIGNING_KEY, key=key, expiry=expiry)


async def _serve(use_case, expiry, signature, *, object_id=PHOTO, now=NOW):
    return await use_case.execute(
        object_id=object_id, expiry=expiry, signature=signature, now=now
    )


# --- the order, which is the point of this file ---------------------------------------


@pytest.mark.asyncio
async def test_the_order_is_resolve_then_verify_then_serve():
    """Asserted as a sequence, not inferred from a status code."""
    use_case, journal, locations, configs, reader = _build()
    expiry, signature = _valid()

    served = await _serve(use_case, expiry, signature)

    assert journal == ["locate", "config", "read_for", "read"]
    assert locations.asked == [PHOTO]
    # The tenant used to resolve the backend came out of step 1, not out of the request.
    assert configs.asked == [TENANT]
    # And the bytes were read from the key that came out of step 1 too.
    assert reader.read_keys == [KEY]
    assert served.content == BYTES


@pytest.mark.asyncio
async def test_a_bad_signature_stops_before_anything_is_served():
    """The inverted implementation this file exists to catch would read first and check after.

    `journal` ends at `locate`: no tenant configuration was read and no adapter was built, so
    nothing about the object left the process.
    """
    use_case, journal, _, _, reader = _build()

    with pytest.raises(InvalidSignatureError):
        await _serve(use_case, NOW_POSIX + 60, "0" * 32)

    assert journal == ["locate"]
    assert reader.read_keys == []


@pytest.mark.asyncio
async def test_a_signature_over_the_key_the_caller_wishes_for_is_refused():
    """The key is the row's, never the request's — the whole reason step 1 comes first.

    This signature is cryptographically perfect: the right secret, the right scheme, an expiry
    in the future. It just covers a key belonging to **another tenant**, which is the pivot the
    ordering forbids. Nothing about the request tells the use case which key to use, so there
    is no field through which this could ever be accepted.
    """
    use_case, journal, _, _, reader = _build()
    foreign_key = f"tenants/{uuid.uuid4()}/cleaning-tasks/{TASK}/{PHOTO}.jpg"
    expiry, signature = _valid(foreign_key)

    with pytest.raises(InvalidSignatureError):
        await _serve(use_case, expiry, signature)

    assert journal == ["locate"]
    assert reader.read_keys == []


@pytest.mark.asyncio
async def test_an_object_that_does_not_exist_raises_the_same_error_as_a_bad_signature():
    """One error type, so the route has one body to answer with."""
    use_case, journal, _, _, _ = _build(location=None)
    expiry, signature = _valid()

    with pytest.raises(InvalidSignatureError):
        await _serve(use_case, expiry, signature)

    assert journal == ["locate"]


@pytest.mark.asyncio
async def test_an_expired_signature_is_refused():
    use_case, journal, _, _, _ = _build()
    expiry, signature = _valid(expiry=NOW_POSIX - 1)

    with pytest.raises(InvalidSignatureError):
        await _serve(use_case, expiry, signature)

    assert journal == ["locate"]


@pytest.mark.asyncio
async def test_a_signature_reaching_past_the_ttl_ceiling_is_refused():
    """The ceiling binds the URL, not only the signer. A well-formed signature over `now + 1 day` still does not work."""
    use_case, _, _, _, _ = _build()
    expiry, signature = _valid(expiry=NOW_POSIX + SIGNED_URL_TTL_SECONDS + 60)

    with pytest.raises(InvalidSignatureError):
        await _serve(use_case, expiry, signature)


@pytest.mark.asyncio
async def test_the_clock_comes_from_the_caller():
    """A URL that verifies now stops verifying an hour and a second later, without sleeping."""
    use_case, _, _, _, _ = _build()
    expiry, signature = _valid()

    await _serve(use_case, expiry, signature)

    with pytest.raises(InvalidSignatureError):
        await _serve(
            use_case,
            expiry,
            signature,
            now=NOW + timedelta(seconds=SIGNED_URL_TTL_SECONDS + 1),
        )


# --- what happens after a valid signature ---------------------------------------------


@pytest.mark.asyncio
async def test_an_s3_tenant_has_no_local_serving():
    """The factory refuses, and only ever after the signature has been accepted."""
    use_case, journal, _, _, _ = _build(storage_type=StorageType.S3, local=False)
    expiry, signature = _valid()

    with pytest.raises(LocalFileReadUnsupportedError):
        await _serve(use_case, expiry, signature)

    assert journal == ["locate", "config", "read_for"]


@pytest.mark.asyncio
async def test_an_unreadable_object_surfaces_as_a_storage_error():
    """The forbidden direction: a row pointing at an object that is not there."""
    use_case, _, _, _, _ = _build(read_fails=True)
    expiry, signature = _valid()

    with pytest.raises(StorageWriteError):
        await _serve(use_case, expiry, signature)


@pytest.mark.parametrize(
    ("extension", "expected"),
    [("jpg", "image/jpeg"), ("png", "image/png"), ("webp", "image/webp")],
)
@pytest.mark.asyncio
async def test_the_content_type_comes_from_the_keys_extension(extension, expected):
    """`content_type_for_extension` and nothing else, for every accepted format."""
    key = f"tenants/{TENANT}/cleaning-tasks/{TASK}/{PHOTO}.{extension}"
    use_case, _, _, _, _ = _build(
        location=ObjectLocation(storage_key=key, tenant_id=TENANT)
    )
    expiry, signature = _valid(key)

    served = await _serve(use_case, expiry, signature)

    assert served.content_type == expected


@pytest.mark.asyncio
async def test_a_key_without_a_usable_extension_is_refused_rather_than_guessed():
    """No `application/octet-stream` fallback and no sniffing.

    Only reachable through a corrupted row, so a `ValueError` (a 500) is the right answer: it
    is our bug, not the caller's, and the alternative is serving bytes with a type nobody
    derived.
    """
    key = f"tenants/{TENANT}/cleaning-tasks/{TASK}/{PHOTO}"
    use_case, _, _, _, _ = _build(
        location=ObjectLocation(storage_key=key, tenant_id=TENANT)
    )
    expiry, signature = _valid(key)

    with pytest.raises(ValueError, match="no accepted MIME type"):
        await _serve(use_case, expiry, signature)
