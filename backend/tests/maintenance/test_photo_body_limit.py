"""The body ceiling of the photo upload, and the two ends that bound it (R5, design D9).

`MaxBodySizeMiddleware` resolves its ceiling from the request path, so the whole of R5 is a
property of one `if/elif` chain in `app/main.py`. Three things have to be true of it and each
one fails differently:

* the photo route gets `PHOTO_UPLOAD_MAX_BYTES` (R5.1) — otherwise a legitimate 4 MB photo is
  refused with a `413` and the feature does not work;
* **every other route under `/api/v1/incidents` keeps its own, smaller ceiling** (R5.2) — a
  branch matched on the prefix alone would hand a 10 MiB JSON body to twelve authenticated
  routes that expect kilobytes;
* the pattern is bounded at **both** ends (R5.3) — prefix *and* suffix — which is what keeps
  the two apart.

**R5.2's own wording is corrected here, and design D9 records why.** The proposal said the other
`/api/v1/incidents` routes keep "el techo JSON de 1 MiB", i.e. `JSON_BODY_MAX_BYTES`. They do
not and never did: that branch is selected by the `/cleaning-` prefix, and `/incidents` has
always fallen through to `settings.request_max_bytes`. Both are 1 MiB today, so the *intent* of
R5.2 holds, but the constant is a different one — and asserting the wrong constant would be a
test that passes for the wrong reason and breaks the day the two values diverge.

The provider is exercised directly rather than over HTTP. That is deliberate: sending a 10 MiB
body through `httpx` to prove a ceiling is slow, and it proves the ceiling for one path while
saying nothing about the other thirteen. The function under test *is* the decision.
"""

import pytest

from app.core.config import settings
from app.main import API_V1_PREFIX, create_app

#: Every path the branch has to classify, with the ceiling it must resolve to.
#:
#: The two `/incidents` non-photo entries are the point of the table: they are what a
#: prefix-only pattern would silently widen.
CASES: tuple[tuple[str, str], ...] = (
    # The photo upload itself (R5.1).
    (f"{API_V1_PREFIX}/incidents/2f1c/photos", "photo"),
    # Every other route of the module keeps the fall-through ceiling (R5.2).
    (f"{API_V1_PREFIX}/incidents", "request"),
    (f"{API_V1_PREFIX}/incidents/2f1c", "request"),
    (f"{API_V1_PREFIX}/incidents/2f1c/assign", "request"),
    (f"{API_V1_PREFIX}/incidents/2f1c/resolve", "request"),
    (f"{API_V1_PREFIX}/incidents/2f1c/context", "request"),
    # A path that merely *starts* the same way must not be widened either.
    (f"{API_V1_PREFIX}/incident-photos/2f1c", "request"),
    # `cleaning`'s branch is untouched by this change.
    (f"{API_V1_PREFIX}/cleaning-tasks/2f1c/photos", "photo"),
    (f"{API_V1_PREFIX}/cleaning-tasks/2f1c", "json"),
    # And the CSV importer's, which shares the numeric value but not the branch.
    (f"{API_V1_PREFIX}/integrations/pms/import-csv", "csv"),
)


def _provider():
    """The `max_bytes_provider` the real app mounts, pulled off the middleware stack.

    Read from `create_app()` rather than reimplemented here, so this test cannot pass against a
    copy of the logic while the app runs something else.

    **This reaches into Starlette's `Middleware` representation** (`user_middleware`, and the
    `kwargs` a middleware was mounted with), which is an implementation detail rather than a
    documented API. Accepted, with a canary: `test_the_provider_is_actually_mounted` fails
    loudly and immediately if that shape ever changes, so an upgrade produces an obvious red
    rather than a silent pass over a provider nobody found. Flagged by the section 7-9 QA panel.
    """
    for middleware in create_app().user_middleware:
        kwargs = getattr(middleware, "kwargs", {}) or {}
        if "max_bytes_provider" in kwargs:
            return kwargs["max_bytes_provider"]
    raise AssertionError("no middleware on the app declares a max_bytes_provider")


def _expected(kind: str) -> int:
    from app.core.http_limits import JSON_BODY_MAX_BYTES

    return {
        "photo": settings.photo_upload_max_bytes,
        "request": settings.request_max_bytes,
        "json": JSON_BODY_MAX_BYTES,
        "csv": settings.csv_import_max_bytes,
    }[kind]


def test_the_provider_is_actually_mounted() -> None:
    """Guards the vacuous pass: if the provider could not be found, every case below would
    error rather than silently agree."""
    assert _provider() is not None


@pytest.mark.parametrize(("path", "kind"), CASES)
def test_each_path_resolves_to_its_own_ceiling(path: str, kind: str) -> None:
    assert _provider()(path) == _expected(kind)


def test_the_photo_route_gets_the_photo_ceiling_and_not_the_request_one() -> None:
    """R5.1 — stated on its own because it is the requirement, and because the parametrised
    case above would still pass if both constants happened to be equal."""
    provider = _provider()

    assert provider(f"{API_V1_PREFIX}/incidents/2f1c/photos") == (
        settings.photo_upload_max_bytes
    )
    assert settings.photo_upload_max_bytes > settings.request_max_bytes


def test_the_pattern_is_bounded_at_the_prefix_end() -> None:
    """R5.3 — dropping the `/incidents/` prefix check would widen `/x/photos` everywhere.

    A path ending in `/photos` under a different resource must not get the photo ceiling from
    *this* branch. `cleaning-tasks` gets it from its own, which is why the assertion uses a
    third resource that has no photo route at all.
    """
    provider = _provider()

    assert provider(f"{API_V1_PREFIX}/properties/2f1c/photos") == (
        settings.request_max_bytes
    )


def test_the_pattern_is_bounded_at_the_suffix_end() -> None:
    """R5.3 — dropping the `/photos` suffix check would widen all twelve module routes.

    This is the assertion that fails if someone "simplifies" the branch to the prefix alone,
    and it is the one R5.2 exists for.
    """
    provider = _provider()

    for path in (
        f"{API_V1_PREFIX}/incidents",
        f"{API_V1_PREFIX}/incidents/2f1c",
        f"{API_V1_PREFIX}/incidents/2f1c/cancel",
    ):
        assert provider(path) == settings.request_max_bytes, path


def test_the_branch_is_wider_than_the_route_and_that_is_recorded() -> None:
    """The accepted risk of design D9, asserted so it stays a *known* fact rather than a
    surprise.

    `/api/v1/incidents/photos` and `/api/v1/incidents/a/b/c/photos` match the pattern, admit up
    to 10 MiB, and only then answer `404`/`405`. That is inherited from the cleaning branch and
    written beside it in `app/main.py`. Pinned here because a future reader who discovers it by
    accident should find a test saying it was known, not conclude the pattern is a mistake.
    """
    provider = _provider()

    for path in (
        f"{API_V1_PREFIX}/incidents/photos",
        f"{API_V1_PREFIX}/incidents/a/b/c/photos",
    ):
        assert provider(path) == settings.photo_upload_max_bytes, path
