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

Scoped to the paths that accept uploads rather than applied globally: the rest of the API takes
small JSON bodies, and a single global number would either be too small for a CSV or too large
to mean anything for a login.
"""

import json
from collections.abc import Callable, Iterable

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import error_envelope

TOO_LARGE_CODE = "PAYLOAD_TOO_LARGE"


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
        max_bytes_provider: Callable[[], int],
    ) -> None:
        self._app = app
        self._prefixes = tuple(path_prefixes)
        # A callable, not a value: the limit is read per request so a test (or an operator
        # changing configuration) does not have to rebuild the application to change it.
        self._max_bytes_provider = max_bytes_provider

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith(self._prefixes):
            await self._app(scope, receive, send)
            return

        limit = self._max_bytes_provider()
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

        sent_response = False

        async def guarded_send(message: Message) -> None:
            nonlocal sent_response
            if exceeded and not sent_response:
                sent_response = True
                await _refuse(send, limit)
                return
            if not exceeded:
                await send(message)

        try:
            await self._app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded:
                raise
        if exceeded and not sent_response:
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
