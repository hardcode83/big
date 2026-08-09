"""R5 — the photo route gets its own body ceiling, and nothing else under `/cleaning-` does.

Written **before** the branch it checks (task 3.3), and the pairing is the whole point. The
first half alone would go green the lazy way: raising `JSON_BODY_MAX_BYTES`, or widening the
`/cleaning-` branch, makes a 2 MiB photo pass — and simultaneously removes the ceiling from
`POST /cleaning-checklist-templates`, which is the endpoint that took a measured anonymous
~50 MB body read in full before answering `401` (see `app/core/http_limits.py`). So the second
half asserts that sibling is **still** refused, and it is the one that fails if anybody
"fixes" this globally.

Both requests are anonymous on purpose: `MaxBodySizeMiddleware` runs before authentication —
that is the entire reason it exists — so what is being pinned here is the ceiling itself, not
what the endpoint behind it decides afterwards.
"""

import json
import uuid

import pytest

from app.core.error_codes import ErrorCode

# Over the 1 MiB JSON ceiling and comfortably under the 10 MB photo one, so the two halves
# below differ **only** in which branch of the provider their path lands on.
#
# **An absolute number, deliberately not derived from `JSON_BODY_MAX_BYTES`.** It was written
# as `JSON_BODY_MAX_BYTES + 512 * 1024` first, and that made the second test unable to fail at
# the one thing it is here for: raising the constant to 10 MB moved this body to 10.5 MB, still
# above the new ceiling, so `test_the_same_body_is_still_refused_on_every_other_cleaning_route`
# stayed green while the ceiling it guards had been removed. A test that recomputes itself from
# the value it watches cannot watch it.
#
# 2 MiB is chosen against both ends and not by taste: above 1 MiB so the JSON branch refuses it
# today, and low enough that any plausible loosening of the JSON ceiling — the "make the photo
# route work by raising the constant" shortcut this pins — turns the second test red instead of
# sliding under it.
OVERSIZED = 2 * 1024 * 1024


def _photos_path() -> str:
    return f"/api/v1/cleaning-tasks/{uuid.uuid4()}/photos"


@pytest.mark.asyncio
async def test_an_oversized_photo_body_is_not_refused_by_the_middleware(api):
    """R5.1 — 2 MiB reaches the application on the photo route.

    Asserted as "not a 413" rather than as a concrete status because the ceiling is all this
    branch decides: what the route answers once the body is through (401 here, since the
    request carries no token) belongs to the endpoint, not to the middleware.
    """
    response = await api.post(
        _photos_path(),
        content=b"\xff\xd8\xff" + b"\x00" * (OVERSIZED - 3),
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code != 413
    assert ErrorCode.PAYLOAD_TOO_LARGE.value not in response.text


@pytest.mark.asyncio
async def test_the_same_body_is_still_refused_on_every_other_cleaning_route(api):
    """R5.2 — the half that fails if someone raises the ceiling globally.

    `POST /cleaning-checklist-templates` takes a client-sized array, so its body is the one
    the 1 MiB ceiling was measured against. If this stops being a 413, the photo route was
    made to work by removing a ceiling instead of by adding one.
    """
    response = await api.post(
        "/api/v1/cleaning-checklist-templates",
        content=json.dumps({"name": "x" * OVERSIZED}).encode(),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == ErrorCode.PAYLOAD_TOO_LARGE.value


@pytest.mark.asyncio
async def test_a_path_that_merely_ends_in_photos_elsewhere_keeps_the_json_ceiling(api):
    """The branch is `/cleaning-tasks/` **and** a trailing `/photos`, not either one.

    Without this, a branch written as "any cleaning path ending in `/photos`" — or worse, any
    path ending in `/photos` — would hand the wider ceiling to routes nobody sized for it.
    """
    response = await api.post(
        "/api/v1/cleaning-checklist-templates/photos",
        content=b"\x00" * OVERSIZED,
        headers={"content-type": "application/octet-stream"},
    )

    assert response.status_code == 413
