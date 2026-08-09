"""`S3FileStorage` against the port contract, and both adapters against each other (task 1.5).

EXTERNAL_DEPENDENCY: there is no AWS account behind this project, so nothing here talks to S3.
What is tested is what the design says is testable — the **contract** of `FileStoragePort` and
the **substitutability** SOLID's L requires (`steering/backend-architecture.md`): the last class
in this file runs identical assertions against `S3FileStorage` and `LocalFileStorage`, so a use
case written against one behaves the same against the other.

The stub client answers the way botocore does, including raising `ClientError` — which is the
part a mock that "just works" would hide, and the exact failure the L rule exists to catch.
"""

from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    StorageWriteError,
    derive_signing_key,
)
from app.integrations.infrastructure.storage.local import LocalFileStorage
from app.integrations.infrastructure.storage.s3 import S3FileStorage, build_s3_client

BUCKET = "autohostai-media"
KEY = "tenants/11111111-1111-1111-1111-111111111111/cleaning-tasks/t/p.jpg"
JPEG = b"\xff\xd8\xff\xe0 pretend this is a photo"


class _StubS3Client:
    """Enough of botocore's S3 client for the three calls this adapter makes."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str] = {}
        self.deleted: list[str] = []
        self.signed: list[tuple[str, int]] = []

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> None:
        assert Bucket == BUCKET
        self.objects[Key] = Body
        self.content_types[Key] = ContentType

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        assert Bucket == BUCKET
        self.deleted.append(Key)
        self.objects.pop(Key, None)

    def generate_presigned_url(self, operation: str, *, Params: dict, ExpiresIn: int) -> str:
        assert operation == "get_object"
        assert Params["Bucket"] == BUCKET
        self.signed.append((Params["Key"], ExpiresIn))
        return (
            f"https://{BUCKET}.s3.amazonaws.com/{Params['Key']}"
            f"?X-Amz-Expires={ExpiresIn}&X-Amz-Signature=deadbeef"
        )


class _FailingS3Client:
    """Every call fails the way botocore reports an S3 refusal."""

    _ERROR = ClientError({"Error": {"Code": "AccessDenied", "Message": "denied"}}, "PutObject")

    def put_object(self, **_: object) -> None:
        raise self._ERROR

    def delete_object(self, **_: object) -> None:
        raise self._ERROR

    def generate_presigned_url(self, *_: object, **__: object) -> str:
        raise self._ERROR


class TestTheDependencyLanded:
    def test_boto3_is_installed_as_a_runtime_dependency(self) -> None:
        """Task 1.5 adds it to `backend/pyproject.toml`'s `dependencies`, not to the dev group:
        `devops/Dockerfile`'s prod stage installs with `uv sync --frozen --no-dev`, so a
        dev-group boto3 would be absent from the deployed image while the suite stayed green —
        the trap `httpx` and `cryptography` each fell into once.
        """
        import tomllib

        import boto3  # noqa: F401

        pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
        with open(pyproject, "rb") as handle:
            declared = tomllib.load(handle)["project"]["dependencies"]

        assert any(item.startswith("boto3") for item in declared)

    def test_the_client_builder_does_not_run_at_import_time(self) -> None:
        """Constructing a boto3 client reads the credential chain. The adapter takes its client
        by constructor precisely so it can be instantiated without an AWS environment — which
        is how an EXTERNAL_DEPENDENCY ends up with tests at all."""
        assert callable(build_s3_client)
        S3FileStorage(bucket=BUCKET, client=_StubS3Client())  # no credentials involved


class TestS3Adapter:
    @pytest.mark.asyncio
    async def test_put_stores_the_object_with_the_detected_mime(self) -> None:
        """Without `ContentType` S3 serves `binary/octet-stream` and the browser downloads the
        photo instead of showing it."""
        client = _StubS3Client()

        await S3FileStorage(bucket=BUCKET, client=client).put(
            KEY, JPEG, content_type="image/jpeg"
        )

        assert client.objects[KEY] == JPEG
        assert client.content_types[KEY] == "image/jpeg"

    def test_signed_url_defaults_to_the_hour_the_security_rule_asks_for(self) -> None:
        client = _StubS3Client()

        url = S3FileStorage(bucket=BUCKET, client=client).signed_url(KEY)

        assert client.signed == [(KEY, SIGNED_URL_TTL_SECONDS)]
        assert url.startswith("https://")

    def test_a_shorter_expiry_is_passed_through(self) -> None:
        client = _StubS3Client()

        S3FileStorage(bucket=BUCKET, client=client).signed_url(KEY, expires_in=60)

        assert client.signed == [(KEY, 60)]

    @pytest.mark.asyncio
    async def test_delete_removes_the_object(self) -> None:
        client = _StubS3Client()
        storage = S3FileStorage(bucket=BUCKET, client=client)
        await storage.put(KEY, JPEG, content_type="image/jpeg")

        await storage.delete(KEY)

        assert client.deleted == [KEY]

    @pytest.mark.asyncio
    async def test_deleting_something_that_is_not_there_is_not_an_error(self) -> None:
        """S3 answers 204 for a key that never existed, so the compensating delete of design D4
        does not need a check first."""
        await S3FileStorage(bucket=BUCKET, client=_StubS3Client()).delete("no/such/key.jpg")


class TestSubstitutability:
    """SOLID's L, applied to the two implementations of one port.

    `steering/backend-architecture.md` puts it plainly: the two must be 100% interchangeable —
    same exceptions, same return shapes, same preconditions. These assertions run against both.
    """

    @pytest.fixture(params=["local", "s3"])
    def storage(self, request, tmp_path: Path):
        if request.param == "local":
            return LocalFileStorage(signing_key=derive_signing_key("s" * 64), root=tmp_path)
        return S3FileStorage(bucket=BUCKET, client=_StubS3Client())

    @pytest.fixture(params=["local", "s3"])
    def failing_storage(self, request, tmp_path: Path):
        if request.param == "local":
            # A root that is a FILE: `mkdir(parents=True)` raises `NotADirectoryError`, which
            # is the local equivalent of the backend refusing the write.
            root = tmp_path / "media"
            root.write_bytes(b"not a directory")
            return LocalFileStorage(signing_key=derive_signing_key("s" * 64), root=root)
        return S3FileStorage(bucket=BUCKET, client=_FailingS3Client())

    @pytest.mark.asyncio
    async def test_put_returns_none_and_delete_is_idempotent(self, storage) -> None:
        assert await storage.put(KEY, JPEG, content_type="image/jpeg") is None
        assert await storage.delete(KEY) is None
        assert await storage.delete(KEY) is None

    def test_signed_url_is_synchronous_and_returns_a_string(self, storage) -> None:
        """Synchronous on both sides on purpose: neither implementation talks to the network —
        `generate_presigned_url` signs locally — so declaring it `async` would promise an I/O
        boundary that does not exist."""
        url = storage.signed_url(KEY)

        assert isinstance(url, str)
        assert "exp" in url or "X-Amz-Expires" in url

    @pytest.mark.asyncio
    async def test_a_backend_failure_raises_the_same_error_on_both(
        self, failing_storage
    ) -> None:
        """The assertion that matters most here: R1.5 maps this one error to a `502`, so an
        adapter that raised its provider's own exception type would escape that mapping."""
        with pytest.raises(StorageWriteError):
            await failing_storage.put(KEY, JPEG, content_type="image/jpeg")

        with pytest.raises(StorageWriteError):
            await failing_storage.delete(KEY)
