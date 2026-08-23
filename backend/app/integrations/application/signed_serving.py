"""The anonymous signed serving of a stored object — one implementation, every consumer.

Extracted from `cleaning` by the change `incident-photos` (design D5). What used to be
`ServeLocalCleaningPhotoUseCase` in `app/cleaning/application/use_cases.py` lives here
unchanged in behaviour and parameterised only by which `UnscopedObjectLocationQuery` resolves
the id.

**Why it is shared rather than copied.** This is the most exposed surface the application has:
anonymous by design, reachable from the internet through the Cloudflare tunnel that
`api-ingress-routing` opened, and returning bytes a third party uploaded. The ordering below is
its entire authorisation, and two copies of a security argument are two places it can diverge —
so `cleaning` and `maintenance` share the argument and supply only their own table.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.integrations.domain.storage import (
    FileStorageFactory,
    InvalidSignatureError,
    UnscopedObjectLocationQuery,
    content_type_for_extension,
    verify_signed_key,
)
from app.tenants.domain.repositories import TenantConfigRepository


@dataclass(frozen=True)
class ServedObject:
    """The bytes to answer with, and the `Content-Type` to answer them with.

    `content_type` comes from `content_type_for_extension` and from nowhere else. It is carried
    here rather than left to the route to work out, so the route has nothing to derive and
    nothing to guess.
    """

    content: bytes
    content_type: str


class ServeSignedObjectUseCase:
    """Resolve the object, verify the signature against what resolved, then serve.

    **The order of the three steps is the security property, not an implementation detail**:

    1. **Resolve** `object_id → (storage_key, tenant_id)` through the unscoped query. There is
       no session tenant here — the route is anonymous because an `<img src>` sends no
       `Authorization` header — so this is the only way to learn either fact.
    2. **Verify** the signature against the key that came out of step 1, never against
       anything the client sent. The signature covers the whole key, which begins with
       `tenants/{tenant_id}/`, so a signature that verifies **proves** the caller was handed a
       URL minted for this object of this tenant. That is the entire authorisation of this
       endpoint.
    3. **Serve**, and only now: resolve the tenant's backend and read the bytes.

    Inverting 1 and 2 is impossible (there is nothing to verify against yet). Inverting 2 and 3
    is the failure this ordering exists to prevent, and it has its own test.

    Every refusal in steps 1 and 2 raises the **same** `InvalidSignatureError`, which the route
    turns into one constant `403` body. "No such object", "wrong signature", "expired" and
    "over the TTL ceiling" must be indistinguishable from outside, or this endpoint becomes an
    existence oracle over the object keyspace for a caller with no credentials at all.

    Step 3 answers differently on purpose, and it is not a leak: `LocalFileReadUnsupportedError`
    (an `S3` tenant, no local serving) becomes a `404` and a `StorageWriteError` a `502`, but
    both are only reachable **after** a valid signature, i.e. by someone already holding proof
    that the object exists.

    `now` is passed in like every other use case, and converted to POSIX seconds for
    `verify_signed_key`, which is pure and takes the clock as an argument. One reading,
    converted, rather than two parameters that could disagree about *when* this request
    happened.
    """

    def __init__(
        self,
        *,
        locations: UnscopedObjectLocationQuery,
        configs: TenantConfigRepository,
        storage: FileStorageFactory,
        signing_key: bytes,
    ) -> None:
        self._locations = locations
        self._configs = configs
        self._storage = storage
        self._signing_key = signing_key

    async def execute(
        self,
        *,
        object_id: uuid.UUID,
        expiry: int,
        signature: str,
        now: datetime,
    ) -> ServedObject:
        location = await self._locations.locate_without_tenant_scoping(object_id)
        if location is None:
            # Step 1 failed. Raised as the SAME error a bad signature raises so the route has
            # one thing to catch and one body to answer with. The message is for the log; it
            # does not reach the response.
            #
            # Known and accepted residue: this path skips the HMAC of step 2, so it is
            # marginally faster than a signature that fails to verify. Distinguishing a UUID
            # that exists from one that does not through that difference means measuring
            # microseconds across the internet over a 122-bit keyspace, per candidate id. The
            # body is identical, which is what the requirement asks for.
            raise InvalidSignatureError(f"no object resolves for id {object_id}")

        # Against the key from the DATABASE. Nothing the client sent contributes to it — the
        # URL carries only the object id, its expiry and the signature (the key is kept out of
        # every response, so it could not carry the key even if we wanted it to).
        verify_signed_key(
            signing_key=self._signing_key,
            key=location.storage_key,
            expiry=expiry,
            signature=signature,
            now=int(now.timestamp()),
        )

        # Everything below happens only after a valid signature. `get_or_create` can in
        # principle insert, which would be a write on an anonymous request — in practice never,
        # because the upload that created this object already created the row, and in any case
        # this route never commits, so the flush dies with the request's transaction.
        config = await self._configs.get_or_create(location.tenant_id, now)
        # Raises `LocalFileReadUnsupportedError` for an `S3` tenant, before instantiating
        # anything — design D1's refusal point. There is no local serving for that backend
        # because the browser fetches the object straight from the provider.
        reader = self._storage.read_for(config.storage_type)
        content = await reader.read(location.storage_key)
        return ServedObject(
            content=content,
            # The ONLY admitted source. The MIME detected at upload is not persisted; with
            # `LOCAL` it survives solely inside the key's extension. Deriving it from anything
            # else — or omitting it and letting Starlette sniff — turns a polyglot that starts
            # with `FF D8 FF` and carries HTML into stored XSS on the API's own origin.
            # `extension_of` refuses a key it cannot read rather than falling back to a
            # default, for the same reason.
            content_type=content_type_for_extension(extension_of(location.storage_key)),
        )


def extension_of(storage_key: str) -> str:
    """The extension inside a storage key, with no default and no guess.

    Returns `""` for a key with no extension, which `content_type_for_extension` then refuses
    with a `ValueError` — a 500, correctly, because such a key can only come from a bug of
    ours: every key is built by one of the `storage_key_for_*` functions, which validate the
    extension against the image allowlist before assembling it. Substituting
    `application/octet-stream` here would be exactly the fallback this design forbids.
    """
    _, separator, extension = storage_key.rpartition(".")
    return extension if separator else ""
