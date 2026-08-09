"""MIME detection by magic bytes (task 1.2, design D5, R2.4).

The rule being protected is that the format comes from the CONTENT: rule 6 of
`steering/security.md` and R2.4 ask for the real MIME, and the `Content-Type` a client declares
is a claim, not evidence. Nothing in `detect_image_type` can even see the declared header.
"""

import pytest

from app.integrations.domain.storage import (
    ACCEPTED_EXTENSIONS,
    ACCEPTED_IMAGE_TYPES,
    CONTENT_TYPE_BY_EXTENSION,
    MAGIC_BYTES_LENGTH,
    content_type_for_extension,
    detect_image_type,
)

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
# `RIFF` + a little-endian length + `WEBP` — the length varies per file, which is why the
# signature is two positioned fragments and not one prefix.
WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 "

# A PDF renamed to `.jpg`: the exact attack R2.4 exists for. The extension and whatever
# `Content-Type` the client sends are both irrelevant here — only these bytes are read.
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"


@pytest.mark.parametrize(
    ("head", "mime", "extension"),
    [
        (JPEG, "image/jpeg", "jpg"),
        (PNG, "image/png", "png"),
        (WEBP, "image/webp", "webp"),
    ],
)
def test_it_recognises_each_accepted_format(head: bytes, mime: str, extension: str) -> None:
    detected = detect_image_type(head)

    assert detected is not None
    assert (detected.mime, detected.extension) == (mime, extension)


def test_a_pdf_disguised_as_a_jpg_is_not_an_image() -> None:
    assert detect_image_type(PDF) is None


def test_an_empty_file_is_not_an_image() -> None:
    assert detect_image_type(b"") is None


def test_a_file_shorter_than_the_longest_signature_is_not_an_image() -> None:
    """A truncated WebP header must not match on its `RIFF` alone.

    Slicing past the end of `bytes` yields a short slice rather than raising, so this is the
    case that would silently pass if `matches` compared lengths instead of contents.
    """
    truncated = WEBP[:6]
    assert len(truncated) < MAGIC_BYTES_LENGTH

    assert detect_image_type(truncated) is None
    assert detect_image_type(b"\xff") is None
    assert detect_image_type(b"RIFF") is None


def test_riff_that_is_not_webp_is_rejected() -> None:
    """A WAV file is a RIFF container too, and its fourth field says `WAVE`."""
    assert detect_image_type(b"RIFF\x24\x00\x00\x00WAVEfmt ") is None


def test_the_allowlist_is_one_constant_and_covers_the_three_declared_formats() -> None:
    """Design D5 keeps the allowlist in a single place so widening it is one line.

    Also pins that HEIC/HEIF is deliberately OUT (design Q1): the day it goes in, this
    assertion is the one that makes the decision explicit instead of incidental.
    """
    assert {image.mime for image in ACCEPTED_IMAGE_TYPES} == {
        "image/jpeg",
        "image/png",
        "image/webp",
    }
    assert MAGIC_BYTES_LENGTH == 12


class TestContentTypeForServing:
    """`content_type_for_extension`: the single admitted source of the served `Content-Type`.

    The detected MIME is not persisted — with `LOCAL` it survives only inside the key's
    extension (D3) — so the anonymous serving route of design D7 has exactly one honest way to
    answer. If it derived the header from anything else, or omitted it and let Starlette guess,
    a polyglot starting with `FF D8 FF` and carrying HTML would be stored XSS on the API's own
    origin, which `api-ingress-routing` left reachable from the internet.
    """

    @pytest.mark.parametrize(
        ("extension", "mime"),
        [("jpg", "image/jpeg"), ("png", "image/png"), ("webp", "image/webp")],
    )
    def test_every_accepted_extension_maps_to_its_mime(self, extension: str, mime: str) -> None:
        assert content_type_for_extension(extension) == mime

    @pytest.mark.parametrize("extension", ["", "exe", "html", "svg", "heic", "JPG", "jpg.html"])
    def test_an_unknown_extension_yields_nothing_servable(self, extension: str) -> None:
        """Raises rather than returning `None`, and that is the point: a `None` would invite the
        route to fall back to a default or to sniffing, which is the exact failure this
        function exists to prevent. Same choice as `storage_key_for_photo`, for the same reason
        — an unknown extension here can only come from a key this system itself built."""
        with pytest.raises(ValueError):
            content_type_for_extension(extension)

    def test_the_serving_table_cannot_drift_from_the_detection_allowlist(self) -> None:
        """One source, not two. Widening the allowlist is one line by design D5; a hand-written
        second table would leave the SERVING side — the one that talks to a browser — holding
        the stale half, which is how `LOCAL` ends up answering `application/octet-stream` for a
        format `S3` serves correctly.

        This assertion is what fails the day someone adds a format to `ACCEPTED_IMAGE_TYPES`
        and the two stop agreeing.
        """
        assert set(CONTENT_TYPE_BY_EXTENSION) == set(ACCEPTED_EXTENSIONS)
        assert CONTENT_TYPE_BY_EXTENSION == {
            image.extension: image.mime for image in ACCEPTED_IMAGE_TYPES
        }
        for image in ACCEPTED_IMAGE_TYPES:
            assert content_type_for_extension(image.extension) == image.mime

    def test_detection_and_serving_agree_on_real_bytes(self) -> None:
        """End to end over the two halves that must never diverge: the MIME detected from the
        bytes at upload is the MIME served from the extension afterwards."""
        for head in (JPEG, PNG, WEBP):
            detected = detect_image_type(head)

            assert detected is not None
            assert content_type_for_extension(detected.extension) == detected.mime

    def test_the_serving_route_must_send_nosniff(self) -> None:
        """A correct `Content-Type` is not the whole defence: a browser can still content-sniff
        its way to another interpretation. The obligation is written into the function's
        docstring because the route (task 4.3) is not built yet, and this pins the docstring so
        the requirement cannot quietly disappear before its implementer reads it."""
        assert "X-Content-Type-Options: nosniff" in (content_type_for_extension.__doc__ or "")


def test_no_third_party_mime_library_is_involved() -> None:
    """`python-magic`, `filetype` and `imghdr` are all rejected by design D5.

    Asserted on the module's own imports rather than on the environment, because a package
    being absent today is not the same as this code refusing to use it.
    """
    import app.integrations.domain.storage as storage

    source = storage.__file__
    assert source is not None
    with open(source, encoding="utf-8") as handle:
        text = handle.read()

    for banned in ("import magic", "import filetype", "import imghdr"):
        assert banned not in text
