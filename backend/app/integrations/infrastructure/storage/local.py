"""`LOCAL` file storage: objects on disk under `/app/media/`, served by signed URL.

Implements **both** ports of `domain/storage.py` — `FileStoragePort` and `LocalFileReadPort` —
because this is the one backend where reading bytes back through the application is a real
operation (design D1). `S3FileStorage` implements only the first.

R1.3 fixes the root at `/app/media/`, which `docker-compose.yml` mounts as a named volume, and
explicitly not inside the code tree: a bind mount of the repository would put uploaded photos
in `git status`.

**Why a signed URL and not a path** (rule 5 of `steering/security.md`, R3.3): a disk path is
not a credential, so `LOCAL` gets its own serving endpoint that verifies the signature and its
expiry before returning bytes. This adapter mints the URL; the endpoint that honours it arrives
with the serving route of design D7.
"""

import os
import time
from collections.abc import Callable
from pathlib import Path

import anyio.to_thread

from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    StorageWriteError,
    clamp_expires_in,
    sign_storage_key,
)

#: R1.3 and PRD §4 §"Almacenamiento de archivos". A module constant rather than a setting: a
#: deployment that could point this somewhere else would be a deployment that could point it at
#: the code tree, and the volume mount is what makes the path meaningful in the first place.
MEDIA_ROOT = Path("/app/media")

#: Where the signed URLs of this adapter point. A constructor parameter with this default
#: rather than a hardcoded string inside `signed_url`, because the port is shared: `maintenance`
#: and `revenue` will serve their own objects from their own routes (design D2), and only the
#: wiring knows which. The route itself is design D7's.
DEFAULT_SIGNED_URL_PREFIX = "/api/v1/cleaning-photos"


class LocalFileStorage:
    """Objects under `root`, addressed by storage key, with HMAC-signed read URLs.

    `signing_key` is the HKDF-derived key from `derive_signing_key`, never `JWT_SECRET_KEY`
    itself (design D6).

    `clock` returns POSIX seconds and exists so a test can fix the expiry without sleeping;
    production leaves it at `time.time`.
    """

    def __init__(
        self,
        *,
        signing_key: bytes,
        root: Path = MEDIA_ROOT,
        url_prefix: str = DEFAULT_SIGNED_URL_PREFIX,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._root = Path(root)
        self._signing_key = signing_key
        self._url_prefix = url_prefix.rstrip("/")
        self._clock = clock

    # --- FileStoragePort ---------------------------------------------------------------

    async def put(self, key: str, content: bytes, *, content_type: str) -> None:
        """Write the object, creating its parent directories.

        `content_type` is accepted and not stored: on disk the extension carries it, and the
        detected MIME travels to the browser from the serving endpoint. The parameter stays in
        the signature because the port declares it and `S3FileStorage` needs it — a narrower
        signature here would break substitutability (SOLID's L).

        Written to a temporary neighbour and then `os.replace`d, which is atomic within a
        filesystem: without it a crash mid-write would leave a truncated object that the row
        inserted afterwards (design D4) would point at, and a half a JPEG is worse than no
        JPEG because nothing reports it.
        """
        path = self._resolve(key)
        await anyio.to_thread.run_sync(self._write, path, content)

    def signed_url(self, key: str, *, expires_in: int = SIGNED_URL_TTL_SECONDS) -> str:
        """`{prefix}/{object id}?exp=…&sig=…`, valid for `expires_in` seconds (capped).

        `expires_in` goes through `clamp_expires_in`, so it can never exceed
        `SIGNED_URL_TTL_SECONDS` however loudly a caller asks — R3.1 and rule 5 of
        `steering/security.md` are an invariant here, not a default. The serving route verifies
        the same ceiling on the way back in, which is what makes it stick.

        The signature covers the **whole storage key**, which begins with the tenant id (D3),
        while the path carries only the object id — so the URL never exposes the internal key
        (R3.2) and a valid signature still cannot be pivoted onto another tenant's object.

        Relative rather than absolute, deliberately: the application does not know the public
        origin it is being served from (behind a Cloudflare tunnel in dev, a bare port in
        local), and inventing one would produce URLs that work in exactly one environment. A
        browser resolves it against the page it is on, which is where the API already is.
        """
        expiry = int(self._clock()) + clamp_expires_in(expires_in)
        signature = sign_storage_key(signing_key=self._signing_key, key=key, expiry=expiry)
        return f"{self._url_prefix}/{Path(key).stem}?exp={expiry}&sig={signature}"

    async def delete(self, key: str) -> None:
        """Remove the object; an object that is not there is not an error (port contract)."""
        path = self._resolve(key)
        await anyio.to_thread.run_sync(self._unlink, path)

    # --- LocalFileReadPort -------------------------------------------------------------

    async def read(self, key: str) -> bytes:
        """The stored bytes, or `StorageWriteError` if there is nothing to read."""
        path = self._resolve(key)
        return await anyio.to_thread.run_sync(self._read, path)

    # --- Path resolution ---------------------------------------------------------------

    def _resolve(self, key: str) -> Path:
        """The absolute path for `key`, **checked to still be inside the root** (task 1.4).

        The check is on the RESULT of resolution, not on the input, and that distinction is
        the whole defence. Rejecting keys that contain `..` is a blacklist, and blacklists of
        path fragments fail — through URL encoding, through an absolute key (`Path("/app/media")
        / "/etc/passwd"` is `/etc/passwd`, because that is what `pathlib` does with an absolute
        right-hand side), and through a symlink that `resolve()` follows out of the tree.
        Comparing the resolved path against the resolved root catches all three with one rule.

        Nothing that reaches here should ever fail this: keys come from
        `storage_key_for_photo`, which builds them from four UUIDs and never from client input
        (D3). It is defence in depth against a future caller that forgets that.
        """
        if not key or "\x00" in key:
            raise StorageWriteError("storage key must be a non-empty string without NUL bytes")
        root = self._root.resolve()
        candidate = (root / key).resolve()
        if candidate == root or not candidate.is_relative_to(root):
            raise StorageWriteError(
                f"storage key resolves outside the storage root and was refused: {key!r}"
            )
        return candidate

    # --- Blocking bodies, run off the event loop ---------------------------------------
    #
    # Disk I/O through `anyio.to_thread`, the same way `BcryptPasswordHasher` keeps hashing off
    # the loop: a 10 MB write is short but real, and the API process serves every other request
    # on the same loop.

    @staticmethod
    def _write(path: Path, content: bytes) -> None:
        partial = path.with_name(path.name + ".part")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(content)
            os.replace(partial, path)
        except OSError as error:
            # Best effort, and it must not raise: the cleanup of a failed write ran into its
            # own `NotADirectoryError` here and replaced the real cause with a traceback from
            # `unlink`, which is how a 502 loses the reason it happened.
            try:
                partial.unlink(missing_ok=True)
            except OSError:
                pass
            raise StorageWriteError(f"could not write object: {error}") from error

    @staticmethod
    def _unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            raise StorageWriteError(f"could not delete object: {error}") from error

    @staticmethod
    def _read(path: Path) -> bytes:
        try:
            return path.read_bytes()
        except OSError as error:
            raise StorageWriteError(f"could not read object: {error}") from error
