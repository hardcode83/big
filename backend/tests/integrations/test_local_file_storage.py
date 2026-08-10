"""`LocalFileStorage` against a real filesystem (task 1.4, R1.3).

Integration tests, not unit ones: the thing being verified is what happens on disk, and the
central assertion — that a key which resolves outside the root never touches it — is only
meaningful against real path resolution.

`tmp_path` stands in for `/app/media/`; the production root is a module constant, pinned by its
own test below.
"""

from pathlib import Path

import pytest

from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    StorageWriteError,
    derive_signing_key,
    verify_signed_key,
)
from app.integrations.infrastructure.storage.local import MEDIA_ROOT, LocalFileStorage

SECRET = "s" * 64
KEY = "tenants/11111111-1111-1111-1111-111111111111/cleaning-tasks/t/p.jpg"
JPEG = b"\xff\xd8\xff\xe0 pretend this is a photo"
NOW = 1_800_000_000


def _storage(root: Path, *, now: float = NOW) -> LocalFileStorage:
    return LocalFileStorage(
        signing_key=derive_signing_key(SECRET), root=root, clock=lambda: now
    )


def test_the_production_root_is_the_mounted_volume() -> None:
    """R1.3: under `/app/media/`, which `docker-compose.yml` mounts as a named volume, and
    never inside the code tree — a bind mount of the repository would put uploaded photos in
    `git status`."""
    assert MEDIA_ROOT == Path("/app/media")


class TestRoundTrip:
    @pytest.mark.asyncio
    async def test_it_writes_reads_and_deletes(self, tmp_path: Path) -> None:
        storage = _storage(tmp_path)

        await storage.put(KEY, JPEG, content_type="image/jpeg")

        assert (tmp_path / KEY).read_bytes() == JPEG
        assert await storage.read(KEY) == JPEG

        await storage.delete(KEY)

        assert not (tmp_path / KEY).exists()

    @pytest.mark.asyncio
    async def test_it_creates_the_intermediate_directories(self, tmp_path: Path) -> None:
        storage = _storage(tmp_path)

        await storage.put(KEY, JPEG, content_type="image/jpeg")

        assert (tmp_path / KEY).parent.is_dir()

    @pytest.mark.asyncio
    async def test_no_partial_file_survives_a_successful_write(self, tmp_path: Path) -> None:
        """The write goes to a neighbour and is `os.replace`d, so a crash cannot leave a
        truncated object for the row inserted afterwards (design D4) to point at."""
        storage = _storage(tmp_path)

        await storage.put(KEY, JPEG, content_type="image/jpeg")

        assert list((tmp_path / KEY).parent.glob("*.part")) == []

    @pytest.mark.asyncio
    async def test_deleting_something_that_is_not_there_is_not_an_error(
        self, tmp_path: Path
    ) -> None:
        """Port contract: the caller is the compensating delete of a failed transaction (D4),
        and that path must not fail a second time on the way out."""
        await _storage(tmp_path).delete(KEY)

    @pytest.mark.asyncio
    async def test_reading_an_absent_object_raises(self, tmp_path: Path) -> None:
        with pytest.raises(StorageWriteError):
            await _storage(tmp_path).read(KEY)


class TestTraversal:
    """Task 1.4: the path is resolved and the RESULT is checked to still be inside the root.

    Each case asserts twice — that the call was refused, and that nothing appeared outside the
    root — because a check that raises after writing is not a check.
    """

    @pytest.mark.parametrize(
        "key",
        [
            "../escaped.jpg",
            "tenants/../../escaped.jpg",
            "a/b/../../../escaped.jpg",
            "/etc/passwd",
            "..",
            ".",
            "",
        ],
    )
    @pytest.mark.asyncio
    async def test_a_key_that_escapes_the_root_is_refused(
        self, tmp_path: Path, key: str
    ) -> None:
        root = tmp_path / "media"
        root.mkdir()
        outside = tmp_path / "escaped.jpg"

        with pytest.raises(StorageWriteError):
            await _storage(root).put(key, JPEG, content_type="image/jpeg")

        assert not outside.exists()

    @pytest.mark.asyncio
    async def test_an_absolute_key_does_not_silently_become_the_root(
        self, tmp_path: Path
    ) -> None:
        """`Path("/media") / "/etc/passwd"` is `/etc/passwd` — that is what `pathlib` does with
        an absolute right-hand side, and it is the reason the check is on the resolved result
        rather than on the input string."""
        root = tmp_path / "media"
        root.mkdir()

        with pytest.raises(StorageWriteError):
            await _storage(root).read("/etc/hostname")

    @pytest.mark.asyncio
    async def test_a_symlink_out_of_the_root_is_refused(self, tmp_path: Path) -> None:
        """A blacklist of `..` would let this through; resolution followed by the containment
        check does not."""
        root = tmp_path / "media"
        root.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        (root / "link").symlink_to(outside)

        with pytest.raises(StorageWriteError):
            await _storage(root).put("link/escaped.jpg", JPEG, content_type="image/jpeg")

        assert not (outside / "escaped.jpg").exists()

    @pytest.mark.asyncio
    async def test_a_nul_byte_is_refused_rather_than_raising_from_the_os(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(StorageWriteError):
            await _storage(tmp_path).put("a\x00b.jpg", JPEG, content_type="image/jpeg")

    @pytest.mark.asyncio
    async def test_deleting_through_a_traversal_key_is_refused(self, tmp_path: Path) -> None:
        root = tmp_path / "media"
        root.mkdir()
        victim = tmp_path / "victim.jpg"
        victim.write_bytes(JPEG)

        with pytest.raises(StorageWriteError):
            await _storage(root).delete("../victim.jpg")

        assert victim.exists()


class TestSignedUrl:
    def test_it_carries_the_expiry_and_a_signature_that_verifies(self, tmp_path: Path) -> None:
        url = _storage(tmp_path).signed_url(KEY)

        path, _, query = url.partition("?")
        parameters = dict(pair.split("=", 1) for pair in query.split("&"))

        assert path.endswith("/p")  # the photo id, not the key
        assert int(parameters["exp"]) == NOW + SIGNED_URL_TTL_SECONDS
        verify_signed_key(
            signing_key=derive_signing_key(SECRET),
            key=KEY,
            expiry=int(parameters["exp"]),
            signature=parameters["sig"],
            now=NOW,
        )

    def test_the_default_expiry_is_the_hour_the_security_rule_asks_for(
        self, tmp_path: Path
    ) -> None:
        """Rule 5 of `steering/security.md` and R3.1."""
        assert SIGNED_URL_TTL_SECONDS == 3600

    def test_the_internal_key_never_appears_in_the_url(self, tmp_path: Path) -> None:
        """R3.2: no internal path in any response. The signature covers the whole key — tenant
        id included (D3) — while the URL shows only the object id."""
        url = _storage(tmp_path).signed_url(KEY)

        assert KEY not in url
        assert "tenants/" not in url
        assert "11111111-1111-1111-1111-111111111111" not in url

    def test_a_shorter_expiry_is_honoured(self, tmp_path: Path) -> None:
        url = _storage(tmp_path).signed_url(KEY, expires_in=60)

        assert f"exp={NOW + 60}" in url

    def test_a_longer_expiry_is_cut_down_to_the_ceiling(self, tmp_path: Path) -> None:
        """R3.1 is an invariant of the port, not a default argument of it: a caller asking for a
        day gets an hour. Without this, a future consumer — design D2 names `maintenance` and
        `revenue` — could mint an effectively permanent anonymous URL over a photo."""
        url = _storage(tmp_path).signed_url(KEY, expires_in=86_400)

        assert f"exp={NOW + SIGNED_URL_TTL_SECONDS}" in url

    def test_the_minted_url_verifies_at_the_moment_it_is_issued(self, tmp_path: Path) -> None:
        """A default-TTL URL sits exactly ON the verification ceiling (`expiry - now == 3600`),
        so an off-by-one in `verify_signed_key` would reject every photo URL the instant it was
        handed out. This is the test that catches that, and it is worth its own case because a
        clamp and a ceiling written independently is exactly how that off-by-one happens."""
        url = _storage(tmp_path).signed_url(KEY, expires_in=SIGNED_URL_TTL_SECONDS * 10)

        _, _, query = url.partition("?")
        parameters = dict(pair.split("=", 1) for pair in query.split("&"))

        verify_signed_key(
            signing_key=derive_signing_key(SECRET),
            key=KEY,
            expiry=int(parameters["exp"]),
            signature=parameters["sig"],
            now=NOW,
        )

    @pytest.mark.parametrize("expires_in", [0, -1])
    def test_a_non_positive_expiry_is_refused(self, tmp_path: Path, expires_in: int) -> None:
        """A URL that is dead the instant it exists is a caller bug, not a policy question —
        and it would surface as an unexplained 403 at a browser rather than near its cause."""
        with pytest.raises(ValueError):
            _storage(tmp_path).signed_url(KEY, expires_in=expires_in)
