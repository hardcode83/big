"""`GET /api/v1/cleaning-photos/{photo_id}` — the anonymous signed serving route (design D7).

**This is the highest-risk surface in this change and the file is written accordingly.**
`api-ingress-routing` left `/api/v1` reachable from the internet through the Cloudflare tunnel,
and this route carries no `require(...)`: it is anonymous on purpose, because an `<img src>`
sends no `Authorization` header and a signed URL that only works from `fetch` is a signed URL
that works for nothing. The signature **is** the credential — it covers the whole storage key,
which begins with `tenants/{tenant_id}/` (D3), so presenting a valid one proves the caller was
handed a URL minted for this photo of this tenant.

It is a router of its own rather than three more lines in `tasks_router.py` for two reasons
that are the same reason twice: the path is not under `/cleaning-tasks/`, and everything in
that file hangs off `AUTHENTICATED_RESPONSES` and a permission dependency. An anonymous
endpoint sharing a router with twelve authorised ones is one copied decorator away from either
claiming a `401` it cannot return or, far worse, from an authorised sibling inheriting nothing.

Four properties of this module are not stylistic and must survive any edit:

1. **The `403` body is a constant** (task 4.3b). See `_SIGNATURE_REFUSED`.
2. **The `Content-Type` comes only from `content_type_for_extension`, and every response *this
   module builds* — the bytes and all three refusals — carries `X-Content-Type-Options:
   nosniff`** (task 4.3c). See `_respond`, which is the single exit of this module and the only
   place that stamps it. The promise stops at the four exits below, and deliberately: a request
   that never reaches this router — a `photo_id` that is not a UUID, or a missing `exp`/`sig`,
   both answered `422` by the global `RequestValidationError` handler in `app/core/errors.py`,
   and a wrong method answered `405` by Starlette — goes out without the header. Neither
   reflects attacker input today (the handler prunes each error to `loc`/`type`/`msg`), so
   nothing is sniffable there now. Closing that gap means a response header middleware, which
   is a posture decision for the whole backend — the twelve authenticated routes have no
   `nosniff` either — and no requirement of this change asks for one; it is tracked as a
   separate candidate rather than smuggled in here.
3. **No response outlives the signature that bought it.** See `_photo_response`.
4. **Nothing in the response depends on anything the client sent** other than which bytes come
   back — no echoed id, no file name, no key.
"""

import logging
import uuid
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from app.auth.api.dependencies import now_utc
from app.cleaning.api.dependencies import get_serve_local_cleaning_photo_use_case
from app.cleaning.application.use_cases import ServeLocalCleaningPhotoUseCase
from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.core.openapi import ErrorEnvelope
from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    InvalidSignatureError,
    LocalFileReadUnsupportedError,
    StorageWriteError,
)

logger = logging.getLogger(__name__)

#: So `_respond` gives back what it was handed — a `Response` for the bytes, a `JSONResponse`
#: for a refusal — instead of widening both to `Response` and losing the distinction.
_ResponseT = TypeVar("_ResponseT", bound=Response)

router = APIRouter(prefix="/cleaning-photos", tags=["cleaning"])

#: The **entire** body of every refusal on this route, precomputed once so it cannot vary.
#:
#: Task 4.3b, and it is a correction of the house pattern rather than a deviation from it.
#: `app/cleaning/api/errors.py` maps domain errors with `message = str(exc)`, which is right
#: everywhere it is used — those routes are authenticated, and a caller who already holds a
#: token for the tenant learns nothing from a precise message. Here it would be a disaster:
#: `InvalidSignatureError` carries three distinct messages ("signature does not match",
#: "signature has expired", "signature outlives the maximum signed-URL lifetime") while its
#: whole documented contract is indistinguishability, and this use case raises a fourth
#: occasion — "no such photo". Serialising `str(exc)` would let anyone on the internet, with no
#: credentials at all, separate "this photo id exists" from "it does not" by reading the
#: message: an existence oracle over the photo keyspace, and through the key, over the tenant
#: keyspace behind it.
#:
#: So the four cases answer with THIS object and nothing else. The three messages survive in
#: the log line of `serve_cleaning_photo`, where they are useful and where no attacker reads
#: them. `tests/cleaning/test_serve_photo_api.py` compares the bodies byte for byte, which is
#: the only assertion that would survive somebody "helpfully" restoring `str(exc)`.
_SIGNATURE_REFUSED = error_envelope(
    ErrorCode.FORBIDDEN, "The signed URL is not valid for this photo"
)

#: An `S3` tenant has no local serving: the browser fetches the object straight from the
#: provider with its presigned URL, so this route has nothing to do (design D1's `read_for`
#: refusal). A `404` and not a `501`, because from the client's side the resource genuinely is
#: not here. Only reachable **after** a valid signature, so it discloses nothing.
_NO_LOCAL_SERVING = error_envelope(
    ErrorCode.NOT_FOUND, "This photo is not served by this endpoint"
)

#: The object is gone from the store while its row still points at it — the failure design D4
#: forbids by writing the object first. A `502` for the same reason the upload uses one: the
#: dependency failed, not the caller. Also only reachable after a valid signature.
_STORE_UNAVAILABLE = error_envelope(
    ErrorCode.BAD_GATEWAY, "The photo could not be read from storage"
)

#: `Content-Type` is set from `ServedPhoto.content_type` per response; this is the half of the
#: defence that is the same for every one of them (task 4.3c, and `content_type_for_extension`
#: says so in its own docstring). A correct `Content-Type` is not enough on its own — a browser
#: will still content-sniff its way to another interpretation — and a polyglot that opens with
#: `FF D8 FF` and carries HTML would then execute as **stored XSS on the API's own origin**.
#:
#: It rides on **every** answer this module gives, not only the `200`. The refusals are JSON, so
#: sniffing them into HTML needs a browser to ignore `application/json` — but the header costs
#: nothing, and "it only matters on the happy path" is precisely the reasoning that let it drift
#: off three of the four exits in the first place. `_respond` is now the single place it is
#: applied, so the header is a property of the module rather than of one code path.
_NOSNIFF = "nosniff"

#: The refusals must never be reused by anything (`_respond`). Every one of them is a verdict
#: about *this* request at *this* instant — a `403` is "the signature is not valid **now**", and
#: a cache that replayed it would keep refusing a URL that has since become valid, or the other
#: way round. `no-store` and not `no-cache`: there is nothing worth revalidating in a constant
#: error envelope, and the smallest correct instruction is the one that cannot be got wrong.
_REFUSAL_CACHE_CONTROL = "no-store"

# Declared so the published contract lists what this route can answer. Same criterion as
# `_PHOTO_UPLOAD_RESPONSES` in `tasks_router.py`: every entry is a real branch below.
#
# There is no `401`: this route is anonymous and claiming one would be a lie. There is no
# router-level `AUTHENTICATED_RESPONSES` for the same reason.
_SERVE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        # No `model`: the body is image bytes, not JSON. The media types are the image
        # allowlist of `ACCEPTED_IMAGE_TYPES` — the same one `content_type_for_extension`
        # answers from, so the contract cannot drift from what the route actually sends.
        "content": {"image/jpeg": {}, "image/png": {}, "image/webp": {}},
        "description": (
            "The photo's bytes, with the `Content-Type` derived from the stored object's "
            "extension, `X-Content-Type-Options: nosniff`, and a `Cache-Control` of "
            "`private, max-age=<what is left of the signature>` so no shared cache keeps the "
            "bytes and no browser keeps them past the URL's expiry."
        ),
    },
    403: {
        "model": ErrorEnvelope,
        "description": (
            "The signature is missing, wrong, expired, tampered with, or names a photo that "
            "does not exist. **All five answer with the same body**, deliberately: telling "
            "them apart would make this endpoint an existence oracle for an unauthenticated "
            "caller."
        ),
    },
    404: {
        "model": ErrorEnvelope,
        "description": (
            "The photo's tenant stores objects in `S3`, where the browser fetches them "
            "directly from the provider, so there is nothing for this endpoint to serve."
        ),
    },
    502: {
        "model": ErrorEnvelope,
        "description": "The signature was valid but the object could not be read back.",
    },
}


@router.get(
    "/{photo_id}",
    response_class=Response,
    responses=_SERVE_RESPONSES,
    summary="Serve a cleaning photo by signed URL",
    description=(
        "**Anonymous by design** (`steering/security.md` rule 5): photos travel as signed "
        "URLs, and a browser fetching an `<img src>` sends no `Authorization` header. The "
        "`exp` and `sig` query parameters are the credential — `sig` is an HMAC over the "
        "object's internal key and `exp`, so it cannot be moved to another photo, another "
        "tenant or a later deadline.\n\n"
        "Only tenants whose `storage_type` is `LOCAL` are served here; an `S3` tenant's URLs "
        "point straight at the object store and this route answers `404` for them."
    ),
)
async def serve_cleaning_photo(
    photo_id: uuid.UUID,
    exp: Annotated[int, Query(description="POSIX expiry the signature covers.")],
    sig: Annotated[str, Query(description="Hex HMAC of the object's key and `exp`.")],
    use_case: Annotated[
        ServeLocalCleaningPhotoUseCase, Depends(get_serve_local_cleaning_photo_use_case)
    ],
) -> Response:
    """Resolve the photo, verify the signature against the key from the database, then serve.

    The order lives in `ServeLocalCleaningPhotoUseCase` and is its whole point; what lives here
    is the shape of each answer.

    `exp` and `sig` are **required**, so a request without them is FastAPI's `422` (rewritten
    to the PRD §23 envelope). That is not an oracle: it is a fact about the request, identical
    for a photo that exists and one that does not.

    The clock is read **once**, here, and used for two things that must agree: verifying the
    signature and sizing the `Cache-Control` of the answer. Two readings could disagree about
    when this request happened and hand out a `max-age` that outlives the credential.
    """
    now = now_utc()
    try:
        served = await use_case.execute(photo_id=photo_id, expiry=exp, signature=sig, now=now)
    except InvalidSignatureError as exc:
        # The three signature messages and the "no such photo" one end HERE, in the log, and
        # go no further (4.3b). This is the only place they are useful.
        logger.info(
            "cleaning.photo_url_refused",
            extra={"photo_id": str(photo_id), "reason": str(exc)},
        )
        return _refusal(403, _SIGNATURE_REFUSED)
    except LocalFileReadUnsupportedError:
        return _refusal(404, _NO_LOCAL_SERVING)
    except StorageWriteError as exc:
        # A valid signature over a row whose object is missing — design D4's forbidden
        # direction. Loud, because it means the store and the database disagree.
        logger.error(
            "cleaning.photo_object_unreadable",
            extra={"photo_id": str(photo_id), "reason": str(exc)},
        )
        return _refusal(502, _STORE_UNAVAILABLE)

    return _photo_response(
        served.content, served.content_type, seconds_left=exp - int(now.timestamp())
    )


def _respond(response: _ResponseT, *, cache_control: str) -> _ResponseT:
    """**The single exit of this module.** Every answer is stamped here, or it is a bug.

    `nosniff` used to be handed to `Response(headers=...)` in `_photo_response` alone, which
    meant the module's own docstring ("the two headers cannot come apart") described the `200`
    and nothing else: the three `JSONResponse` refusals went out bare. The header is not a
    property of the happy path, it is a property of the route, so it is applied where the route
    has exactly one narrow place to apply it — and the three refusals now construct through
    `_refusal`, so there is no `JSONResponse(...)` left in this file to forget it next time.
    """
    response.headers["X-Content-Type-Options"] = _NOSNIFF
    response.headers["Cache-Control"] = cache_control
    return response


def _refusal(status_code: int, body: dict[str, Any]) -> JSONResponse:
    """The one place a refusal leaves this module. `body` is always one of the constants above."""
    return _respond(
        JSONResponse(status_code=status_code, content=body),
        cache_control=_REFUSAL_CACHE_CONTROL,
    )


def _photo_response(content: bytes, content_type: str, *, seconds_left: int) -> Response:
    """The one place bytes leave this module, so the headers cannot come apart.

    `media_type` is `ServedPhoto.content_type`, which the use case took from
    `content_type_for_extension` and from nothing else. Building a `Response` anywhere else in
    this file would be the way one of the headers gets forgotten.

    **`private, max-age=<what is left of the signature>`, and the choice is the point** (R3.1).
    Until now the bytes went out with no `Cache-Control` at all, so the 3600 s expiry that
    `verify_signed_key` enforces was a fact known only to this application: every cache on the
    path was free to apply its own heuristics to a `200` with no directives — and
    `api-ingress-routing` puts a Cloudflare tunnel, which is exactly a shared cache, on that
    path. Its cache key includes the query string, so `sig` and `exp` keep one tenant's URL from
    ever hitting another's entry; what is lost without a directive is not isolation but the
    **deadline** — stored bytes can be replayed to anyone re-presenting that same URL after the
    signature it carries has died, and this route is anonymous, so re-presenting it is all it
    takes.

    So the two candidates were `no-store` and this, and the object being immutable is what
    decides between them. The key ends in a UUID minted at upload (D3) and nothing ever
    rewrites it, so a cached copy can never be *stale* — the only thing wrong with keeping it is
    keeping it too long, which is a `max-age` and not a prohibition. `no-store` would answer a
    risk this response does not carry and would charge for it in the one place caching earns its
    keep: a cleaner on mobile data whose task screen repaints the same thumbnails, which is the
    whole reason the browser should hold them.

    `private` is what addresses the actual hole: it instructs *shared* caches not to store the
    response, so a tunnel that honours it keeps nothing, while the browser — a private cache,
    and the same principal the URL was minted for — may. `max-age` then bounds even that copy to
    what remains of the signature, so the cached photo and the credential that bought it expire
    together and the browser must come back for a fresh URL. Serving from a private cache is
    not a bypass of anything: whoever holds the copy already received these bytes.

    The residue, written down because a header cannot enforce it: `private` is a directive, not
    a prohibition. A shared cache configured to ignore the origin's directives — a Cloudflare
    *Cache Everything* rule, say — stores the response anyway, and then the deadline lives only
    in `max-age`, which such a rule can also override with an edge TTL. Today no cache rule is
    configured on this path, so the directive is honoured; if one is ever added, this comment
    is **not** the argument that the bytes are safe, and the deadline has to be re-established
    at the edge (bypass the cache for this path, or scope the rule so it cannot catch it).

    `seconds_left` is `exp - now` at the instant the signature verified, so it is `> 0` and
    `<= SIGNED_URL_TTL_SECONDS` by construction. It is clamped anyway rather than trusted: this
    function must not be the thing that turns a clock the caller got wrong into a negative
    `max-age` (which caches read as "no directive") or an unbounded one.
    """
    max_age = max(0, min(seconds_left, SIGNED_URL_TTL_SECONDS))
    return _respond(
        Response(content=content, media_type=content_type),
        cache_control=f"private, max-age={max_age}",
    )
