"""`S3` file storage: objects in a bucket, read straight from the provider by presigned URL.

`S3` is the **protocol**; which S3-compatible store sits behind it is not decided (design D2b,
and see `S3FileStorage`).

EXTERNAL_DEPENDENCY: no object store account is provisioned for this project, so this adapter
cannot be validated against a real service. What IS validated is the two things that matter and
that a credentialled test would not check any better — the **contract** of `FileStoragePort` and the
**substitutability** SOLID's L demands (`steering/backend-architecture.md`): the contract test
in `tests/integrations/test_s3_file_storage.py` runs the same assertions against this adapter
and `LocalFileStorage`, over a stub client that answers the way botocore does. `LOCAL` is what
the MVP runs on (`TenantConfig.storage_type` defaults to it), which is why that is enough.

Implements `FileStoragePort` and **not** `LocalFileReadPort`, which is the point of design D1:
with `S3` the browser fetches the object directly from the provider using the presigned URL, so
nothing reads bytes through the application. There is no `read` here that raises
`NotImplementedError`; `FileStorageFactory.read_for` refuses for an `S3` tenant instead.
"""

from typing import Any

import anyio.to_thread
import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    StorageWriteError,
    clamp_expires_in,
)

#: Presigned URLs are signed with SigV4 and the client must be told so explicitly for some
#: regions to accept them at all. Pinned rather than left to the environment so a URL minted on
#: one machine verifies on every other.
_CLIENT_CONFIG = Config(signature_version="s3v4")


def build_s3_client(*, region_name: str | None = None, endpoint_url: str | None = None) -> Any:
    """A boto3 S3 client. Separate from the adapter so tests never construct one.

    `endpoint_url` is the seam that makes `S3` mean the protocol rather than AWS (design D2b):
    left at `None` boto3 resolves the AWS endpoint for `region_name`, and set to an OCI Object
    Storage, Cloudflare R2 or MinIO endpoint it talks to that instead, with no change to
    `S3FileStorage`.

    Credentials come from the standard boto3 chain (environment, instance role), which is why
    none of them are settings here: rule 8 of `steering/security.md` keeps secrets out of the
    repository, and the provider's own chain is the mechanism that already does that. Every
    S3-compatible store above authenticates with the same access-key/secret pair, so the chain
    carries over unchanged.
    """
    return boto3.client(
        "s3", region_name=region_name, endpoint_url=endpoint_url, config=_CLIENT_CONFIG
    )


class S3FileStorage:
    """Implements `FileStoragePort` over one bucket of an **S3-compatible** object store.

    **`S3` here is the protocol, not the provider, and the provider is not decided** (design
    D2b). The PRD says so in as many words — *"Producción futura: S3-compatible (Cloudflare R2
    o AWS S3)"* (line 196) — and no ADR, spec or steering doc narrows it further. The class
    name mirrors the value of `StorageType.S3` (`app/tenants/domain/enums.py`) and is kept for
    that reason: renaming it would put the code out of step with the column.

    Two seams keep that choice open, and they are why this is a real commitment rather than a
    comforting sentence:

    * `build_s3_client(*, region_name, endpoint_url)` takes an arbitrary `endpoint_url`, so
      pointing at a non-AWS endpoint is configuration, not a code change.
    * `__init__(*, bucket, client)` **receives** the client instead of constructing one, so
      whatever built it — with whatever endpoint and credentials — is none of this adapter's
      business.

    The natural candidate for this project is **OCI Object Storage**, not AWS: the `dev`
    environment already runs on Oracle Cloud (ADR 0001) and OCI exposes an S3-compatible API,
    so the photos can live where the VM already lives, with no AWS account and no new provider
    to onboard. Cloudflare R2 — which the PRD names first — and MinIO come in through the same
    door.

    The client is injected rather than built here for a second reason too: constructing it
    reads the credential chain, and an adapter that does that in its constructor cannot be
    instantiated in a test without a cloud environment — which is exactly how an
    EXTERNAL_DEPENDENCY ends up untested.

    **Known limitation, accepted:** unlike `LocalFileStorage`, this adapter's signed URL
    exposes the bucket name and the full object key — see `signed_url`.
    """

    def __init__(self, *, bucket: str, client: Any) -> None:
        self._bucket = bucket
        self._client = client

    async def put(self, key: str, content: bytes, *, content_type: str) -> None:
        """`PutObject`, tagged with the **detected** MIME so the browser renders it as an image.

        `content_type` matters here in a way it does not on disk: without it S3 serves
        `binary/octet-stream` and the browser downloads the photo instead of showing it.
        """
        await anyio.to_thread.run_sync(self._put, key, content, content_type)

    def signed_url(self, key: str, *, expires_in: int = SIGNED_URL_TTL_SECONDS) -> str:
        """A presigned `GetObject` URL, valid for `expires_in` seconds (3600 by default, rule 5).

        **This URL contains the bucket name and the full object key, and that is a real
        deviation from `LocalFileStorage`.** `generate_presigned_url` builds an address the
        object store itself will honour, so `tenants/{tenant_id}/cleaning-tasks/{task_id}/
        {photo_id}.jpg` is right there in the path or query, along with the bucket. The `LOCAL`
        adapter publishes only `Path(key).stem` — the photo's UUID — because it points at a
        route of ours that can look the key up; a presigned URL has nobody in the middle to do
        that lookup, which is precisely what makes it presigned.

        Rule 5 of `steering/security.md` ("nunca exponer paths internos") is therefore met only
        in the sense that matters here and is worth stating exactly: the key never appears as a
        **field of an API response** (R3.2), and every segment of it is either a UUID or a
        literal, so it discloses no name, no file the user chose, and no path outside the
        store. What it does disclose is the tenant's UUID — already known to the recipient,
        since it is their own — and the layout of the bucket.

        Closing it properly needs a CDN or a route of ours in front of the bucket, i.e. an
        infrastructure decision this change does not get to make (the provider is not even
        chosen — see the class docstring and design D2b). Rewriting the adapter cannot do it.

        Capped by `clamp_expires_in` before it reaches botocore, for the same reason and by the
        same rule as `LocalFileStorage.signed_url` — and here the cap is the *only* enforcement
        there is: nothing of ours verifies an S3 presigned URL on the way back, the store
        honours whatever `ExpiresIn` it was signed with, and it will happily sign a week.
        Substitutability (SOLID's L) also requires the two adapters to refuse the same inputs.

        Synchronous like the port declares, and honestly so: `generate_presigned_url` signs
        locally and makes no request.
        """
        try:
            return self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": key},
                ExpiresIn=clamp_expires_in(expires_in),
            )
        except (BotoCoreError, ClientError) as error:
            raise StorageWriteError(f"could not sign object URL: {error}") from error

    async def delete(self, key: str) -> None:
        """`DeleteObject`. S3 answers 204 for a key that never existed, so this is idempotent
        without a check — which is what the port's contract requires of the compensating
        delete of design D4."""
        await anyio.to_thread.run_sync(self._delete, key)

    # --- Blocking bodies, run off the event loop ---------------------------------------
    #
    # boto3 is synchronous. Calling it directly from an `async def` would block the loop for
    # the whole round trip to the object store, which on the upload path is the longest call in
    # the request.

    def _put(self, key: str, content: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket, Key=key, Body=content, ContentType=content_type
            )
        except (BotoCoreError, ClientError) as error:
            raise StorageWriteError(f"could not write object: {error}") from error

    def _delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as error:
            raise StorageWriteError(f"could not delete object: {error}") from error
