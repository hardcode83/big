"""The `Cache-Control` clamp on the anonymous serving route's bytes (R4.5).

`_object_response` sizes `max-age` from what is left of the signature, and the arithmetic is
`max(0, min(seconds_left, SIGNED_URL_TTL_SECONDS))`. Every consumer's API test pins the
*normal* case end to end (`tests/cleaning/test_serve_photo_api.py`), and the QA panel of
section 1 found that the two **boundaries** were asserted nowhere — verified only by reading
the code and by a one-off probe. This file is that gap closed.

Why the boundaries are worth their own test rather than left to the happy path: both failure
directions are silent and both are wrong in a way a `200` cannot show. A negative `max-age` is
read by caches as *no directive at all*, so a clock skew would quietly restore exactly the
"every cache applies its own heuristics" hole the directive exists to close; an unclamped
`seconds_left` would let a signature that somehow outran the TTL hand out a cache lifetime
longer than the credential that bought it.

`verify_signed_key` should make `seconds_left <= 0` unreachable at this call site — it refuses
an `expiry` at or before `now`. That is the argument for the clamp being defence in depth, not
an argument for leaving it untested: this function must not be the thing that turns someone
else's regression into a cache directive nobody chose.

The private `_object_response` is called directly. That is deliberate: the clamp is pure
arithmetic over one argument, and reaching it through HTTP would require minting a signature
whose expiry is in the past, which is precisely what the layer above refuses.
"""

import pytest

from app.integrations.api.signed_media import _object_response
from app.integrations.domain.storage import SIGNED_URL_TTL_SECONDS

CONTENT = b"\xff\xd8\xff-bytes"
CONTENT_TYPE = "image/jpeg"


@pytest.mark.parametrize(
    ("seconds_left", "expected_max_age"),
    [
        # Below the floor: a clock that disagrees with the verifier must not produce a
        # negative directive, which caches read as no directive.
        (-3600, 0),
        (-1, 0),
        # The floor itself.
        (0, 0),
        # Ordinary values pass through untouched.
        (1, 1),
        (60, 60),
        # The ceiling itself.
        (SIGNED_URL_TTL_SECONDS, SIGNED_URL_TTL_SECONDS),
        # Above the ceiling: no response outlives the maximum signed-URL lifetime, even if
        # something contrived to sign one that did.
        (SIGNED_URL_TTL_SECONDS + 1, SIGNED_URL_TTL_SECONDS),
        (SIGNED_URL_TTL_SECONDS * 24, SIGNED_URL_TTL_SECONDS),
    ],
)
def test_the_max_age_is_clamped_to_the_signatures_remaining_life(
    seconds_left: int, expected_max_age: int
) -> None:
    response = _object_response(CONTENT, CONTENT_TYPE, seconds_left=seconds_left)

    assert response.headers["Cache-Control"] == f"private, max-age={expected_max_age}"


def test_the_bytes_response_is_private_so_no_shared_cache_stores_it() -> None:
    """`private` is the half of the directive that addresses the tunnel on the path.

    Asserted separately from the `max-age` so that deleting it cannot be hidden by a
    parametrised case that only reads the number.
    """
    response = _object_response(CONTENT, CONTENT_TYPE, seconds_left=60)

    assert response.headers["Cache-Control"].startswith("private,")


def test_the_bytes_carry_exactly_one_nosniff_value() -> None:
    """R4.5 asks for `nosniff` with **un solo valor**.

    `_respond` writes the header rather than appending it, so the module's own stamp and the
    global response-header middleware cannot add up to two. `tests/test_response_headers.py`
    pins that over the real HTTP stack; this pins it at the single exit itself.
    """
    response = _object_response(CONTENT, CONTENT_TYPE, seconds_left=60)

    assert response.headers.getlist("X-Content-Type-Options") == ["nosniff"]


def test_the_content_type_is_the_one_the_use_case_derived() -> None:
    """Nothing between `content_type_for_extension` and the wire may reinterpret it."""
    response = _object_response(CONTENT, CONTENT_TYPE, seconds_left=60)

    assert response.headers["Content-Type"] == CONTENT_TYPE
    assert response.body == CONTENT
