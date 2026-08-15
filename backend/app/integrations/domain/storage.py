"""File storage ports, their signing scheme and their image allowlist (change
`cleaning-photos-storage`, design D1/D3/D5/D6).

Lives in `app/integrations/` rather than in `app/cleaning/` because storage is a shared
capability, not a detail of cleaning: `maintenance` (incident photos) and `revenue`
(`expenses.receipt_storage_key`) are already named as its next consumers, and hanging it off
`cleaning/` would force them to import from another business domain. `steering/backend.md`
says it literally — "adapters externos compartidos en `app/integrations/`" (design D2).

**Two ports, not one, and that is the deliberate shape** (design D1). `FileStoragePort` has
`put`, `signed_url` and `delete`; reading bytes back through the application is a SEPARATE
port, `LocalFileReadPort`, that only the `LOCAL` adapter implements. With `S3` the browser
goes straight to the provider with a presigned URL, so nobody reads bytes through us and an
`open()` on the common port would have an implementer that exists in order to fail — the
Liskov violation `steering/backend-architecture.md` names explicitly and that ADR 0006
decision 3 already rejected once for the PMS.

The precedent copied here, down to the mechanism, is `PMSMessagingPort` and
`PMSAdapterFactory.messaging_for` in this same package (`domain/ports.py`): it is the
**factory** that refuses, with a typed error, rather than a method that exists to raise. See
`FileStorageFactory.read_for` below.

And three methods, not fifteen: R1.1 requires every declared method to have a real caller in
this change (`put` and `signed_url` from the upload and listing use cases, `delete` from the
compensating delete of design D4). A port sized for everything storage could eventually do is
the "`StorageAdapter` gigante con 15 métodos" that the same steering document uses as *its*
example of an Interface Segregation failure.

Everything in this module that is not a Protocol is a **pure function**: no clock, no disk, no
network. `verify_signed_key` takes `now` as an argument for that reason — the caller owns time,
which is what lets expiry be tested without sleeping.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.tenants.domain.enums import StorageType

# --- Errors ---------------------------------------------------------------------------


class StorageWriteError(RuntimeError):
    """The storage backend refused or failed the operation.

    Deliberately **one** error rather than a taxonomy per backend failure, for the reason
    `PmsUnavailableError` already wrote down: from the caller's side there is a single
    decision to make — this object did not get written, report it — and R1.5 turns that into a
    `502` in the PRD §23 envelope. The provider's own message lands in the text.

    It also covers a key that resolves **outside** the storage root (task 1.4): that operation
    is refused before touching disk, which is a refusal of the same kind. It is named on the
    write error rather than getting a fourth error type because the design fixes the error
    contract at three, and because a traversal key can only reach an adapter through a bug —
    the key is derived by `storage_key_for_photo` below and never from client input (D3).
    """


class LocalFileReadUnsupportedError(RuntimeError):
    """This tenant's storage is `S3`, so no `LocalFileReadPort` can be built.

    Raised by `FileStorageFactory.read_for`, exactly as `PMSAdapterFactory.messaging_for`
    raises `PMSMessagingUnsupportedError`, and for the same reason: the capability does not
    exist for this backend, which is a permanent property of the backend and not a transient
    failure. With `S3` the browser fetches the object directly from the provider, so serving
    bytes through the application is not "unavailable", it is meaningless.

    An exception rather than a `None` return, and that choice is measured, not aesthetic:
    **CI runs no type checker** (`app/core/db.py` says so outright), so a
    `LocalFileReadPort | None` would be verified by nothing and would surface as an
    `AttributeError` on `NoneType` at request time.
    """


class InvalidSignatureError(RuntimeError):
    """A signed storage URL did not verify: wrong signature, expired, or tampered with.

    **One error for all three cases on purpose** (R3.4): the local serving endpoint answers
    `403` identically for an invalid signature, an expired one and a photo that does not
    exist, so distinguishing them here would invite a caller to distinguish them there and
    turn the endpoint into an existence oracle over the storage keyspace.
    """


# --- Image type detection (design D5) -------------------------------------------------


@dataclass(frozen=True)
class ImageType:
    """An accepted image format: what it is called, and what its bytes start with.

    `extension` is what ends up in the storage key (D3), so it comes from the CONTENT and
    never from the file name the client sent.
    """

    mime: str
    extension: str
    #: (offset, expected bytes) pairs, all of which must match. A tuple rather than a single
    #: prefix because WebP is a RIFF container: the four bytes that identify it sit at offset
    #: 8, behind a length field that varies per file.
    signature: tuple[tuple[int, bytes], ...]

    def matches(self, head: bytes) -> bool:
        return all(head[at : at + len(part)] == part for at, part in self.signature)


#: The single place where the accepted image formats live (design D5). Widening the allowlist
#: is one line here, which is the whole point of keeping it in one constant.
#:
#: Detected from the bytes and **never** from the `Content-Type` the client declares (R2.4
#: asks for the real MIME; rule 6 of `steering/security.md` requires validating it).
#:
#: No new dependency, on purpose: `python-magic` would drag `libmagic` into the image,
#: `filetype` is a dependency with its own CVE surface for fifteen lines, and `imghdr` was
#: **removed from the standard library in Python 3.13** while this project declares 3.12+.
#:
#: Named consequence: **HEIC/HEIF is out**, and that is the iPhone camera's native format.
#: It is a product decision (design Q1), not an oversight — adding it means `ftyp` magic bytes
#: plus deciding whether to transcode, because Chrome and Firefox do not render it.
ACCEPTED_IMAGE_TYPES: tuple[ImageType, ...] = (
    ImageType(mime="image/jpeg", extension="jpg", signature=((0, b"\xff\xd8\xff"),)),
    ImageType(mime="image/png", extension="png", signature=((0, b"\x89PNG\r\n\x1a\n"),)),
    ImageType(mime="image/webp", extension="webp", signature=((0, b"RIFF"), (8, b"WEBP"))),
)

#: How many bytes an adapter has to read before it can decide. Derived from the allowlist so
#: that adding a format with a longer or deeper signature cannot leave this behind.
MAGIC_BYTES_LENGTH: int = max(
    at + len(part) for image in ACCEPTED_IMAGE_TYPES for at, part in image.signature
)


def detect_image_type(head: bytes) -> ImageType | None:
    """The image format these leading bytes really are, or `None` if it is not an accepted one.

    Pure. `None` rather than an exception because "this file is not an image we accept" is an
    answer the caller turns into a `422`, not a failure of the detection.

    A short read is simply not a match: a file shorter than the signature cannot be one, and
    slicing past the end of `bytes` yields a shorter slice, never an error — so an empty file
    and a two-byte file both fall through to `None` without a special case.
    """
    for image in ACCEPTED_IMAGE_TYPES:
        if image.matches(head):
            return image
    return None


#: extension → MIME, **derived from `ACCEPTED_IMAGE_TYPES` and never written out by hand**. A
#: second table would be a second source of truth, and the day the allowlist widened by one line
#: (which design D5 is built to make cheap) the two would silently disagree — with the serving
#: side, the one that talks to a browser, holding the stale half.
CONTENT_TYPE_BY_EXTENSION: dict[str, str] = {
    image.extension: image.mime for image in ACCEPTED_IMAGE_TYPES
}


def content_type_for_extension(extension: str) -> str:
    """The `Content-Type` to serve an object with, from the extension inside its storage key.

    **This is the only admitted source of the served `Content-Type`** (design D7). The MIME
    detected on upload (`detect_image_type`) is not persisted anywhere — with `LOCAL` it
    survives only inside the key's extension (D3) — so the serving route of D7 has exactly one
    honest way to answer, and this is it. Deriving the header from anything else, or omitting it
    and letting Starlette guess, turns a polyglot that starts with `FF D8 FF` and carries HTML
    into **stored XSS on the API's own origin**: `api-ingress-routing` left `/api/v1` reachable
    from the internet through the Cloudflare tunnel, and D7's route is anonymous by design.

    **The response of that route must also carry `X-Content-Type-Options: nosniff`**, and that
    is not optional: a correct `Content-Type` still lets a browser content-sniff its way to
    another interpretation. The header is the half of the defence that lives at the route; this
    function is the half that lives here. (Implementing the route is task 4.3, not this one.)

    Raises `ValueError` on an extension the allowlist does not declare, rather than returning
    `None`. Same choice, and same reason, as `storage_key_for_photo` above: `detect_image_type`
    returns `None` because "not an image we accept" is a real answer about untrusted BYTES,
    while an unknown extension here can only come from a key this system built — a bug. A `None`
    return would invite the route to fall back to a default or to sniffing, which is precisely
    the failure this function exists to prevent.
    """
    try:
        return CONTENT_TYPE_BY_EXTENSION[extension]
    except KeyError:
        raise ValueError(
            f"extension {extension!r} has no accepted MIME type; it must be one of "
            f"{sorted(CONTENT_TYPE_BY_EXTENSION)}"
        ) from None


# --- Storage keys (design D3) ---------------------------------------------------------

ACCEPTED_EXTENSIONS: frozenset[str] = frozenset(image.extension for image in ACCEPTED_IMAGE_TYPES)


def storage_key_for_photo(
    *, tenant_id: uuid.UUID, task_id: uuid.UUID, photo_id: uuid.UUID, extension: str
) -> str:
    """`tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.{ext}` — and nothing else.

    Pure, and every component is a UUID this system generated. **The file name the client
    sent does not touch the key at any point** (design D3): it is untrusted input, and the
    only safe way to treat it is not to use it. Sanitising it would be a blacklist, and
    blacklists of path fragments fail; it also buys nothing, because the original name is not
    shown anywhere.

    `tenant_id` comes first so two tenants cannot collide on one object — not through a UUID
    collision on the task and not through a repeated `photo_type` (R1.4) — and so an S3 prefix
    is directly scopeable per tenant the day that matters.

    `extension` must be one an accepted image type declares: it is derived from the detected
    MIME (D5), so anything else means a caller invented one.
    """
    if extension not in ACCEPTED_EXTENSIONS:
        raise ValueError(
            f"extension {extension!r} is not one of the accepted image extensions "
            f"{sorted(ACCEPTED_EXTENSIONS)}; it must come from detect_image_type()"
        )
    return f"tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.{extension}"


# --- Signed URLs (design D6) ----------------------------------------------------------

#: Rule 5 of `steering/security.md`, and R3.1: photos travel by signed URL with a 3600 s
#: expiry, never as an internal path.
#:
#: A **ceiling**, not just a default. It was only a default argument until the section 1 panel:
#: `signed_url(expires_in=...)` took whatever it was handed and `verify_signed_key` accepted any
#: `expiry` the signature covered, so a future consumer — D2 names `maintenance` and `revenue` —
#: could mint an effectively permanent anonymous URL over a photo and nothing would refuse it.
#: `clamp_expires_in` applies it at signing time and `verify_signed_key` applies it again at
#: verification, which is the half that matters: it invalidates an over-long URL even if
#: something managed to sign one.
SIGNED_URL_TTL_SECONDS = 3600

#: Version prefix of the signed payload. It is INSIDE the signature, so bumping it invalidates
#: every URL issued under the old scheme by construction — which is what makes rotating the
#: scheme a decision rather than a surprise.
#:
#: `v2` because the payload encoding changed (see `sign_storage_key`): `v1` concatenated
#: `v1|{key}|{expiry}`, `v2` length-prefixes the key. Nothing has reached production, so no live
#: URL is being invalidated — the bump is here because a payload format change without one is
#: the habit that eventually rotates a scheme by accident.
SIGNATURE_VERSION = "v2"

#: HKDF `info`, the domain separation label. Signing a photo URL can never produce or verify a
#: JWT, because the two keys are different by derivation even though one secret feeds both.
SIGNING_KEY_INFO = b"autohostai/cleaning-photo-url/v1"

#: Length of the derived key, in bytes. 32 = the block the HMAC-SHA256 below consumes.
SIGNING_KEY_BYTES = 32

#: Hex characters kept from the digest. 32 hex characters are 128 bits, which is far past
#: forgery range and keeps the URL readable in a log line.
SIGNATURE_LENGTH = 32


def _hkdf_sha256(ikm: bytes, *, info: bytes, length: int) -> bytes:
    """RFC 5869 HKDF over SHA-256, in the ten lines it takes.

    Written out rather than pulled from `cryptography` because `domain/` is pure Python by the
    dependency rule, and because extract-then-expand is exactly two HMACs.

    The salt is empty, which RFC 5869 §2.2 defines as a string of HashLen zeros — and an empty
    HMAC key is padded to the block size with zeros, so the two are the same value. There is
    no salt to store and none to rotate: the domain separation is carried by `info`.
    """
    prk = hmac.new(b"", ikm, hashlib.sha256).digest()
    okm = b""
    block = b""
    counter = 1
    while len(okm) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        okm += block
        counter += 1
    return okm[:length]


def derive_signing_key(secret: str) -> bytes:
    """The URL signing key, derived from `JWT_SECRET_KEY` by HKDF (design D6).

    Derived and **not reused**: the same key for two purposes means that if a signing oracle
    ever leaks, it contaminates authentication. Derivation gives that separation without
    introducing a secret that would have to be provisioned in Terraform, in the secret vault, in
    `docker-compose` and in `.env.example` — which is the trade design Q2 records, with the
    versioned payload prefix (`SIGNATURE_VERSION`, currently `v2`) left in place so a dedicated
    `MEDIA_SIGNING_KEY` can replace this without invalidating anything by surprise.

    Pure: same secret in, same key out, no I/O. It is cheap enough to call per request, and
    callers that do not want to are free to hold the result.
    """
    return _hkdf_sha256(secret.encode("utf-8"), info=SIGNING_KEY_INFO, length=SIGNING_KEY_BYTES)


def clamp_expires_in(expires_in: int) -> int:
    """`expires_in`, cut down to `SIGNED_URL_TTL_SECONDS` if it asks for more (R3.1, rule 5).

    **Clamped rather than refused, and that asymmetry is deliberate.** An over-long TTL is a
    policy question with one right answer — the ceiling — and the caller that asked for a day
    still wants a working URL, so raising would turn a policy into an outage on a path (photo
    listing) whose whole job is to hand out URLs. There is nothing for the caller to decide, so
    there is nothing to report to it. The signature the caller gets back is simply the longest
    one this system issues.

    A **non-positive** TTL is refused, because there the two directions are not alike: it mints
    a URL that is dead the instant it exists, which no caller can want and which would surface
    as an unexplained `403` at the browser rather than anywhere near the bug. Clamping it up to
    something would be inventing an intent; the caller has one.

    Pure, and applied at the point of signing by both adapters. It is not the whole defence:
    `verify_signed_key` re-applies the ceiling, which is what makes an over-long URL useless
    even if something contrives to sign one without coming through here.
    """
    if not isinstance(expires_in, int) or isinstance(expires_in, bool):
        raise TypeError(f"expires_in must be an int, got {type(expires_in).__name__}")
    if expires_in <= 0:
        raise ValueError(f"expires_in must be positive, got {expires_in}")
    return min(expires_in, SIGNED_URL_TTL_SECONDS)


def sign_storage_key(*, signing_key: bytes, key: str, expiry: int) -> str:
    """`HMAC-SHA256(k, "v2|" + len(key) + "|" + key + "|" + expiry)`, truncated (design D6).

    The signed payload covers the **whole** storage key, which begins with the tenant id (D3),
    so there is no way to pivot a valid signature onto another tenant's object without the
    secret. It covers the expiry too, so moving the deadline invalidates it.

    **The key's length is prefixed so the encoding is unambiguous by construction**, not by
    discipline of the caller. `v1` was `v1|{key}|{expiry}` with nothing checking that `key`
    carried no `|`; it happened to be injective only because `expiry` is type-checked to an
    `int` and therefore cannot contain the delimiter — a property of a *neighbouring* guard,
    holding up a security argument two fields away. The length prefix makes the field boundary
    explicit, so the payload stays unambiguous whatever those fields later become. Rejecting
    keys containing `|` was the alternative and was not taken: it is a blacklist over caller
    input, and D2 already names `maintenance` and `revenue` as the next signers with keys built
    some other way — a primitive that is safe only for keys it approves of is the shape this
    fix exists to remove.

    `expiry` is a POSIX timestamp in seconds and is rendered by the caller-independent `str()`
    of an `int`; the type is checked because a `float` would render as `1.7e+09` on some
    inputs and produce a signature that never verifies again.
    """
    if not isinstance(expiry, int) or isinstance(expiry, bool):
        raise TypeError(f"expiry must be an int POSIX timestamp, got {type(expiry).__name__}")
    payload = f"{SIGNATURE_VERSION}|{len(key)}|{key}|{expiry}".encode("utf-8")
    return hmac.new(signing_key, payload, hashlib.sha256).hexdigest()[:SIGNATURE_LENGTH]


def verify_signed_key(
    *, signing_key: bytes, key: str, expiry: int, signature: str, now: int
) -> None:
    """Raise `InvalidSignatureError` unless this signature is this key's and still valid.

    Returns `None` on success rather than a bool: a bool invites `if verify(...)` written
    without the `if`, and a verification whose result can be ignored is not one.

    Compared with `hmac.compare_digest` (R3.5) so the comparison takes the same time whatever
    the mismatch — a byte-by-byte `==` leaks the position of the first wrong character, which
    is enough to forge a signature one character at a time.

    **Pure, and `now` is a parameter** (task 1.3): the caller owns the clock, which is what
    lets expiry be tested without sleeping an hour and what keeps this module free of I/O.

    **The TTL ceiling is enforced HERE too, and that is the important half** (R3.1, rule 5 of
    `steering/security.md`). Clamping at signing time only binds callers that go through
    `clamp_expires_in`; refusing an `expiry` further than `SIGNED_URL_TTL_SECONDS` from `now`
    binds the URL itself, so an over-long one does not work even if something managed to sign
    it. Without this, 3600 s would be a default argument rather than an invariant — which is
    exactly what the section 1 panel found.

    One error for all failure modes, deliberately — see `InvalidSignatureError`.
    """
    expected = sign_storage_key(signing_key=signing_key, key=key, expiry=expiry)
    # Both sides encoded, never compared as `str`: `compare_digest` raises `TypeError` on a
    # non-ASCII `str`, and the signature arrives from a query string, so a request with one
    # accented character would crash the endpoint instead of getting its 403.
    if not hmac.compare_digest(expected.encode("utf-8"), signature.encode("utf-8")):
        raise InvalidSignatureError("signature does not match")
    if expiry <= now:
        raise InvalidSignatureError("signature has expired")
    if expiry - now > SIGNED_URL_TTL_SECONDS:
        raise InvalidSignatureError("signature outlives the maximum signed-URL lifetime")


# --- Ports ----------------------------------------------------------------------------


class FileStoragePort(Protocol):
    """Write an object, hand out a signed URL for it, delete it. Three methods (R1.1).

    Every one has a real caller in this change: `put` and `signed_url` from the upload and
    listing use cases, `delete` from the compensating delete of design D4 — the storage write
    happens before the row is inserted, and a failed commit removes the object so no
    `CleaningPhoto` row can ever point at something that is not there (R1.5).

    **Reading bytes back is not here.** That is `LocalFileReadPort`, and the split is the
    whole of design D1; see this module's docstring.

    Substitutability is a requirement, not a nicety (SOLID's L, spelled out in
    `steering/backend-architecture.md`): `LocalFileStorage` and `S3FileStorage` raise the same
    error (`StorageWriteError`) for the same class of failure and return the same shapes, so a
    use case tested against one behaves the same against the other. `tests/integrations/
    test_s3_file_storage.py` pins that as a contract test over both.
    """

    async def put(self, key: str, content: bytes, *, content_type: str) -> None:
        """Store `content` at `key`, overwriting whatever was there.

        `content_type` is the **detected** MIME (`detect_image_type`), never the one the
        client declared, and it is what a browser will be told when it fetches the object.

        Raises `StorageWriteError` if the backend refused or failed.
        """
        ...

    def signed_url(self, key: str, *, expires_in: int = SIGNED_URL_TTL_SECONDS) -> str:
        """A URL that grants read access to `key` for `expires_in` seconds.

        `expires_in` is **capped at `SIGNED_URL_TTL_SECONDS`** by every implementation, through
        `clamp_expires_in` — asking for more gets the ceiling, not an error, and a non-positive
        value is refused. R3.1 is an invariant of this port, not a default argument of it.

        **Synchronous on purpose**: both implementations compute an HMAC and neither talks to
        the network — `generate_presigned_url` is local arithmetic in botocore too. Declaring
        it `async` would promise an I/O boundary that does not exist and would make every
        caller await something that never yields.
        """
        ...

    async def delete(self, key: str) -> None:
        """Remove the object at `key`. Deleting something that is not there is not an error.

        Idempotent by contract, because its caller is the compensating delete of a failed
        transaction (D4) and that path must not fail a second time on the way out.
        """
        ...


class LocalFileReadPort(Protocol):
    """Read an object's bytes back through the application. **Only `LOCAL` implements it.**

    Separate from `FileStoragePort` for the reason design D1 gives and the PMS split
    established first (`PMSMessagingPort` in `domain/ports.py`): with `S3` the browser fetches
    the object straight from the provider using the presigned URL, so no code path reads bytes
    through us. Putting `read` on the common port would give `S3FileStorage` a method whose
    only possible body is `raise NotImplementedError`, which is the substitution failure
    `steering/backend-architecture.md` forbids by name.

    It is `FileStorageFactory.read_for` that refuses for an `S3` tenant, with
    `LocalFileReadUnsupportedError`, before anything is instantiated.

    Its caller arrives with the anonymous signed serving route of design D7
    (`GET /api/v1/cleaning-photos/{photo_id}`), which is what makes `LOCAL` satisfy rule 5 of
    `steering/security.md`: a disk path is not a signed URL.
    """

    async def read(self, key: str) -> bytes:
        """The stored bytes. Raises `StorageWriteError` if the object cannot be read."""
        ...


class FileStorageFactory(Protocol):
    """Resolves a tenant's adapters from its `TenantConfig.storage_type` (R1.2).

    The use cases depend on THIS, never on a concrete adapter — which is what keeps
    `application/` free of `boto3` and what `tests/test_layering.py` enforces by refusing an
    `infrastructure/` import from `application/`. No use case ever learns which backend is
    active (R1.2).

    Two methods rather than one `resolve` returning both ports, and that is the Interface
    Segregation point with a cost attached: an upload never needs the read port, and asking
    for one on an `S3` tenant is an error — so a caller that does not need it must not be made
    to handle that error.

    The implementation lives in `infrastructure/storage/__init__.py`, not here, because it has
    to import the concrete adapters and `domain/` may not (`tests/test_layering.py`). Same
    split as `PMSAdapterFactory` (port in `domain/ports.py`) and `SqlAlchemyPMSAdapterFactory`
    (implementation in `infrastructure/pms_factory.py`).
    """

    def storage_for(self, storage_type: StorageType) -> FileStoragePort:
        """The write/URL adapter for this storage type."""
        ...

    def read_for(self, storage_type: StorageType) -> LocalFileReadPort:
        """The local read adapter, or `LocalFileReadUnsupportedError` when the tenant is `S3`.

        **This is the refusal point of design D1.** The error comes from the factory — which
        knows the tenant's backend and can answer before building anything — rather than from
        a port method that exists in order to raise. It is the same mechanism as
        `PMSAdapterFactory.messaging_for`, chosen for the same reason.
        """
        ...
