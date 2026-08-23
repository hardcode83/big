"""The anonymous signed serving route, built once for every consumer (`incident-photos` D5).

**This is the highest-risk surface the application has and the file is written accordingly.**
`api-ingress-routing` left `/api/v1` reachable from the internet through the Cloudflare tunnel,
and the route this factory builds carries no `require(...)`: it is anonymous on purpose,
because an `<img src>` sends no `Authorization` header and a signed URL that only works from
`fetch` is a signed URL that works for nothing. The signature **is** the credential — it covers
the whole storage key, which begins with `tenants/{tenant_id}/`, so presenting a valid one
proves the caller was handed a URL minted for this object of this tenant.

Each consumer gets a router of its own rather than three more lines in its authenticated
router, for two reasons that are the same reason twice: the path is not under the domain's
resource prefix, and everything in those files hangs off `AUTHENTICATED_RESPONSES` and a
permission dependency. An anonymous endpoint sharing a router with a dozen authorised ones is
one copied decorator away from either claiming a `401` it cannot return or, far worse, from an
authorised sibling inheriting nothing.

**Why a factory rather than two copies.** Everything below is identical for any consumer except
the prefix, the tag, the operation's name and the log event: the constant `403` body, the
`nosniff` stamp, the `Cache-Control` derived from what is left of the signature, and the shape
of each answer. Two copies of a security argument are two places it can diverge, and this one is
~200 lines of prose whose whole value is being true. `cleaning` was its only consumer until
`incident-photos` became the second.

Four properties of this module are not stylistic and must survive any edit:

1. **The `403` body is a constant.** See `_SIGNATURE_REFUSED`.
2. **The `Content-Type` comes only from `content_type_for_extension`, and every response *this
   module builds* — the bytes and all three refusals — carries `X-Content-Type-Options:
   nosniff`**. See `_respond`, which is the single exit of this module and the only place here
   that stamps it. The requests that never reach the router — a `photo_id` that is not a UUID or
   a missing `exp`/`sig`, both answered `422` by the global `RequestValidationError` handler,
   and a wrong method answered `405` by Starlette — carry the header too, because
   `app/core/response_headers.py` stamps every response the application emits
   (`backend-response-hardening` R1). That is a posture of the whole backend, so it is not this
   module's to describe.

   **`_respond` keeps its own stamp anyway, and that is deliberate** (that change's D5). This
   is the single exit of an anonymous route, reachable from the internet, returning bytes chosen
   by whoever uploaded the object — the one place where `nosniff` is not hygiene but half of the
   stored-XSS defence whose other half is `content_type_for_extension`
   (`app/integrations/domain/storage.py`). Deleting the line would make that defence depend on
   the mounting order of two `add_middleware` calls. The global middleware writes the header
   rather than appending it, so the response still carries exactly one value.
3. **No response outlives the signature that bought it.** See `_object_response`.
4. **Nothing in the response depends on anything the client sent** other than which bytes come
   back — no echoed id, no file name, no key.
"""

import logging
import uuid
from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from app.auth.api.dependencies import now_utc
from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.core.openapi import ErrorEnvelope
from app.integrations.application.signed_serving import ServeSignedObjectUseCase
from app.integrations.domain.storage import (
    SIGNED_URL_TTL_SECONDS,
    InvalidSignatureError,
    LocalFileReadUnsupportedError,
    StorageWriteError,
)

logger = logging.getLogger(__name__)

_ResponseT = TypeVar("_ResponseT", bound=Response)

_SIGNATURE_REFUSED = error_envelope(
    ErrorCode.FORBIDDEN, "The signed URL is not valid for this photo"
)

_NO_LOCAL_SERVING = error_envelope(
    ErrorCode.NOT_FOUND, "This photo is not served by this endpoint"
)

_STORE_UNAVAILABLE = error_envelope(
    ErrorCode.BAD_GATEWAY, "The photo could not be read from storage"
)

_NOSNIFF = "nosniff"

_REFUSAL_CACHE_CONTROL = "no-store"

_SERVE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
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


def build_signed_media_router(
    *,
    prefix: str,
    tag: str,
    operation_name: str,
    summary: str,
    description: str,
    log_event: str,
    use_case_dep: Callable[..., Any],
) -> APIRouter:
    """An `APIRouter` with the one anonymous `GET /{photo_id}` route, wired to `use_case_dep`.

    `operation_name` becomes the route's `name`, which is what FastAPI derives `operationId`
    from. It is a parameter rather than the inner function's `__name__` because that id is part
    of the **published contract** (`backend/openapi.json`, and the frontend artefact generated
    from it): a factory whose inner function is called `serve_signed_object` would silently
    rename `cleaning`'s operation on the day this extraction landed.

    `summary`, `description` and `tag` are the consumer's for the same reason — they are
    published — while the response descriptions in `_SERVE_RESPONSES` are shared, because both
    consumers serve photos and the prose is true of both.

    `log_event` is the structured log name for the two lines this route emits. It is a
    parameter so a refused signature on an incident photo and one on a cleaning photo are
    distinguishable in the log, which is the one place they *should* be told apart.

    `use_case_dep` is a FastAPI dependency returning a `ServeSignedObjectUseCase` built over
    the consumer's own `UnscopedObjectLocationQuery`. That indirection is the whole coupling
    between this module and either domain.
    """
    router = APIRouter(prefix=prefix, tags=[tag])

    @router.get(
        "/{photo_id}",
        name=operation_name,
        response_class=Response,
        responses=_SERVE_RESPONSES,
        summary=summary,
        description=description,
    )
    async def serve_signed_object(
        photo_id: uuid.UUID,
        exp: Annotated[int, Query(description="POSIX expiry the signature covers.")],
        sig: Annotated[str, Query(description="Hex HMAC of the object's key and `exp`.")],
        use_case: Annotated[ServeSignedObjectUseCase, Depends(use_case_dep)],
    ) -> Response:
        """Resolve the object, verify the signature against the key from the database, serve.

        The order lives in `ServeSignedObjectUseCase` and is its whole point; what lives here
        is the shape of each answer.

        `exp` and `sig` are **required**, so a request without them is FastAPI's `422`
        (rewritten to the PRD §23 envelope). That is not an oracle: it is a fact about the
        request, identical for an object that exists and one that does not.

        The clock is read **once**, here, and used for two things that must agree: verifying
        the signature and sizing the `Cache-Control` of the answer. Two readings could disagree
        about when this request happened and hand out a `max-age` that outlives the credential.
        """
        now = now_utc()
        try:
            served = await use_case.execute(
                object_id=photo_id, expiry=exp, signature=sig, now=now
            )
        except InvalidSignatureError as exc:
            logger.info(
                f"{log_event}.photo_url_refused",
                extra={"photo_id": str(photo_id), "reason": str(exc)},
            )
            return _refusal(403, _SIGNATURE_REFUSED)
        except LocalFileReadUnsupportedError:
            return _refusal(404, _NO_LOCAL_SERVING)
        except StorageWriteError as exc:
            logger.error(
                f"{log_event}.photo_object_unreadable",
                extra={"photo_id": str(photo_id), "reason": str(exc)},
            )
            return _refusal(502, _STORE_UNAVAILABLE)

        return _object_response(
            served.content, served.content_type, seconds_left=exp - int(now.timestamp())
        )

    return router


def _respond(response: _ResponseT, *, cache_control: str) -> _ResponseT:
    """**The single exit of this module.** Every answer is stamped here, or it is a bug.

    `nosniff` used to be handed to `Response(headers=...)` in the bytes path alone, which meant
    the docstring ("the two headers cannot come apart") described the `200` and nothing else:
    the three `JSONResponse` refusals went out bare. The header is not a property of the happy
    path, it is a property of the route, so it is applied where the route has exactly one
    narrow place to apply it — and the three refusals construct through `_refusal`, so there is
    no `JSONResponse(...)` left in this file to forget it next time.
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


def _object_response(content: bytes, content_type: str, *, seconds_left: int) -> Response:
    """The one place bytes leave this module, so the headers cannot come apart.

    `media_type` is `ServedObject.content_type`, which the use case took from
    `content_type_for_extension` and from nothing else. Building a `Response` anywhere else in
    this file would be the way one of the headers gets forgotten.

    **`private, max-age=<what is left of the signature>`, and the choice is the point.** Until
    `cleaning-photos-storage` closed it, the bytes went out with no `Cache-Control` at all, so
    the 3600 s expiry that `verify_signed_key` enforces was a fact known only to this
    application: every cache on the path was free to apply its own heuristics to a `200` with
    no directives — and `api-ingress-routing` puts a Cloudflare tunnel, which is exactly a
    shared cache, on that path. Its cache key includes the query string, so `sig` and `exp`
    keep one tenant's URL from ever hitting another's entry; what is lost without a directive
    is not isolation but the **deadline** — stored bytes can be replayed to anyone
    re-presenting that same URL after the signature it carries has died, and this route is
    anonymous, so re-presenting it is all it takes.

    So the two candidates were `no-store` and this, and the object being immutable is what
    decides between them. The key ends in a UUID minted at upload and nothing ever rewrites it,
    so a cached copy can never be *stale* — the only thing wrong with keeping it is keeping it
    too long, which is a `max-age` and not a prohibition. `no-store` would answer a risk this
    response does not carry and would charge for it in the one place caching earns its keep: a
    cleaner or a technician on mobile data whose screen repaints the same thumbnails, which is
    the whole reason the browser should hold them.

    `private` is what addresses the actual hole: it instructs *shared* caches not to store the
    response, so a tunnel that honours it keeps nothing, while the browser — a private cache,
    and the same principal the URL was minted for — may. `max-age` then bounds even that copy
    to what remains of the signature, so the cached photo and the credential that bought it
    expire together and the browser must come back for a fresh URL. Serving from a private
    cache is not a bypass of anything: whoever holds the copy already received these bytes.

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
