"""A body-size ceiling that applies BEFORE anything reads the body.

Why this exists, precisely: FastAPI calls `await request.form()` inside its route handler
wrapper *before* it solves dependencies, and Starlette's multipart parser spools file parts to
a `SpooledTemporaryFile` with no size ceiling of its own. So a `settings.csv_import_max_bytes`
check written inside the endpoint — which is where this change had it — runs after the whole
upload is already on the container's disk, and it runs after `require(...)` too, meaning an
**unauthenticated** request could make the backend write arbitrary volumes and then receive a
401. Measured by the security review of this change: a 60 MiB anonymous POST was fully
received before the 401.

Middleware is the only layer that sees the request before the body is touched, so that is where
the limit belongs. It works in two steps, because either one alone is bypassable:

1. `Content-Length`, when declared, is refused up front — no bytes read at all.
2. The streamed body is counted as it arrives and aborted the moment it exceeds the limit,
   which covers a lying or absent `Content-Length` (chunked uploads).

**It covers the whole API, with a different number per prefix.** It did not start that way, and
the history is worth keeping because two separate changes walked into the same hole from
different sides.

It began scoped to the upload paths alone, arguing that "a single global number would either be
too small for a CSV or too large to mean anything for a login". Then:

1. **`cleaning`** found the first exception to the "everything else is a small JSON body"
   premise (security panel of its sections 2-3). `POST /api/v1/cleaning-checklist-templates`
   takes a **client-sized array** — `items` and `required_photos` — so its body is not a small
   fixed object, and its Pydantic caps (`MAX_ITEMS`, `max_length`) only apply once the whole
   body is in memory, which is exactly the "too late" this module exists to fix. Measured: an
   anonymous ~50 MB `POST` to that path was received in full and then answered `401`. Hence
   `JSON_BODY_MAX_BYTES`.
2. **`api-ingress-routing`** found that the premise was not merely incomplete but that the
   conclusion never followed from it: what a login needs is not *no* ceiling, it is a *small*
   one. While the backend listened only on loopback the gap cost nothing; once `/api/v1` became
   reachable from the internet it was an anonymous memory amplifier. Measured by its security
   review: one 400 MB `POST /api/v1/auth/login` through the public path took the container from
   195 MiB to 1.016 GiB of RSS in 2.3 s, before the 10/min login throttle is ever consulted. No
   compose sets a memory limit on `backend`, so the ceiling was the VM's.

Two changes independently reaching for this module is the signal worth reading: **a body ceiling
is a property of every anonymous endpoint, not of the endpoints someone remembered.** So the
mounting covers `API_V1_PREFIX` and the provider takes the path, which is why its signature is
`Callable[[str], int]` and not `Callable[[], int]` — the per-prefix numbers live at the single
mounting in `app/main.py`, where they can be read side by side. Stacking one instance per prefix
was the shape both changes first reached for and it does not work: instances nest, so the
outermost ceiling decides first and a narrower inner one never sees the request.

"""

import json
from collections.abc import Callable, Iterable

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope

TOO_LARGE_CODE = ErrorCode.PAYLOAD_TOO_LARGE

# The ceiling for JSON routes whose body is an array the client sizes. A constant and not a
# setting: unlike a CSV import there is no operational reason to tune it, and a new
# environment variable would be a knob nobody turns.
#
# **1 MiB, and the number is measured against the schema maximum rather than guessed.** A
# first draft said 256 KiB "two orders of magnitude above the largest legitimate template",
# and the security panel of sections 2-3 measured that claim false: the maximal
# schema-valid template (`MAX_ITEMS=200` entries with `MAX_LABEL_LENGTH=200` labels) is
# 87 KB in ASCII but **338 KB** with accented labels and 640 KB with emoji, because
# `json.dumps` escapes non-ASCII by default — and the project's own fixtures say `Baño` and
# `Terraza`, so accented text is the norm here, not an edge case. At 256 KiB the middleware
# and the validator disagreed about what is legal and the client got a size error instead of
# a validation answer.
#
# 1 MiB clears the worst case measured with room to spare and is still ~50× below the 50 MB
# body this exists to refuse. `tests/cleaning/test_templates_api.py` pins both ends: the
# largest schema-valid template is accepted, an oversized one is not.
JSON_BODY_MAX_BYTES = 1024 * 1024


class MaxBodySizeMiddleware:
    """Refuse an oversized body on the given path prefixes with `413`.

    Pure ASGI rather than `BaseHTTPMiddleware`: the latter consumes the request to build a
    `Request` object, which is the very thing being avoided here.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        path_prefixes: Iterable[str],
        max_bytes_provider: Callable[[str], int],
    ) -> None:
        self._app = app
        self._prefixes = tuple(path_prefixes)
        # A callable, not a value: the limit is read per request so a test (or an operator
        # changing configuration) does not have to rebuild the application to change it. It
        # takes the request path because one ceiling does not fit the whole API — see the
        # module docstring.
        self._max_bytes_provider = max_bytes_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith(self._prefixes):
            await self._app(scope, receive, send)
            return

        limit = self._max_bytes_provider(path)
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await _refuse(send, limit)
            return

        received = 0
        exceeded = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    # Stop feeding the parser: it sees a truncated body and raises, and the
                    # response below is what the client gets either way.
                    return {"type": "http.disconnect"}
            return message

        response_started = False
        refused = False

        async def guarded_send(message: Message) -> None:
            nonlocal response_started, refused
            if message["type"] == "http.response.start":
                if exceeded:
                    # The app is answering after the body was cut short: replace its answer with
                    # the 413, once.
                    if not refused:
                        refused = True
                        response_started = True
                        await _refuse(send, limit)
                    return
                response_started = True
            elif exceeded and not response_started:
                # Body without a start we forwarded: nothing to salvage, answer 413 instead.
                if not refused:
                    refused = True
                    response_started = True
                    await _refuse(send, limit)
                return
            elif refused:
                # Already answered 413; drop whatever the app still wants to say.
                return
            await send(message)

        try:
            await self._app(scope, counting_receive, guarded_send)
        except Exception:
            # An exception on a request that ALSO exceeded the limit is almost certainly the parser
            # choking on the truncated body — that is this middleware's own doing, so it answers
            # 413. Anything else propagates: swallowing it would report a genuine endpoint bug as a
            # size problem. Once a response has started there is nothing to replace, so it
            # propagates too and the server closes the connection (the security review's point:
            # never emit a second `http.response.start`).
            if not exceeded or response_started:
                raise
        if exceeded and not response_started:
            await _refuse(send, limit)


async def _refuse(send: Send, limit: int) -> None:
    body = _json_bytes(
        error_envelope(TOO_LARGE_CODE, f"The request body exceeds the {limit} byte limit")
    )
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def _json_bytes(payload: dict) -> bytes:
    return json.dumps(payload).encode()


__all__ = ["MaxBodySizeMiddleware"]
