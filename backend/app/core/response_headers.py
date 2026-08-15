"""`X-Content-Type-Options: nosniff` on every response the application emits.

Why a middleware and not a header per route: before this module the header existed in
exactly ONE response of the whole backend — `_respond` in
`app/cleaning/api/photos_router.py` — and the other 64 operations went out without it.
That is the failure mode this closes: a property decided well on one route and forgotten
on the rest. A middleware is also the only layer that sees the responses no route builds
— the `404` and `405` Starlette raises, the envelope errors of `app/core/errors.py`, and
the `413` that `MaxBodySizeMiddleware._refuse` fabricates on its own.

Two things about this module are mechanical rather than stylistic, and both must survive
any edit:

1. **The mounting position is the mechanism, not tidiness.** `Starlette.add_middleware`
   inserts at position 0 and `build_middleware_stack` wraps the list in reverse, so the
   LAST middleware added ends up OUTERMOST. `create_app()` therefore adds this one after
   `MaxBodySizeMiddleware`, because only from the outside does it see that middleware's
   self-built `413`. The order is not documented as a contract anywhere else on purpose:
   its contract is a test
   (`tests/test_response_headers.py::test_the_check_catches_the_middlewares_in_the_wrong_order`),
   and reordering the two `add_middleware` calls has to fail loudly rather than read fine.

2. **`receive` is passed through untouched.** Only `send` is decorated. Wrapping `receive`
   would sit between the ASGI server and `MaxBodySizeMiddleware`'s accumulating counter,
   which is the half of that module that catches a lying `Content-Length` — see
   `app/core/http_limits.py`.

**Named residue: the `500` of `ServerErrorMiddleware` is NOT covered.** Starlette mounts
that middleware outside every user middleware, so an unhandled exception leaves with its
`PlainTextResponse("Internal Server Error", 500)` without passing through here. Accepted,
by the same criterion `photos_router` used to name its own gap: that body is a compile-time
constant with not one byte controlled by the client, so there is nothing to sniff. Closing
it would mean registering a global `Exception` handler, which changes the `500` body from
`text/plain` to the PRD §23 envelope — a behaviour change no requirement asks for.

**That acceptance is conditional on `debug=False`, and the test file pins it.** Under `debug`,
`ServerErrorMiddleware` answers with an HTML traceback built from the request and the
exception instead of the constant — client-derived bytes, in the one response that escapes
this stamp. `create_app()` never passes `debug`, so the residue is what D3 accepted; wiring
`FastAPI(debug=...)` changes what that residue means and has to fail
`tests/test_response_headers.py::test_the_named_residue_stays_what_d3_accepted`.

The same criterion, and the same limit, covers what is emitted *below* this application
altogether: uvicorn's own answer to a malformed request, and anything the ingress produces
without reaching us. They never enter the ASGI app, so no middleware here can stamp them,
and their bodies are constants too.
"""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

_HEADER = "X-Content-Type-Options"
_VALUE = "nosniff"


class NoSniffMiddleware:
    """Stamp `X-Content-Type-Options: nosniff` on every HTTP response start message.

    Pure ASGI rather than `BaseHTTPMiddleware`, which builds a `Request` and consumes the
    body — the very thing `app/core/http_limits.py` exists to avoid in this stack.
    """

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        async def stamped(message: Message) -> None:
            if message["type"] == "http.response.start":
                # `__setitem__`, never `append` or `setdefault`: it deletes every prior
                # occurrence and writes one. `append` would emit the header twice on the
                # photo route, which already stamps it; `setdefault` would let a route keep
                # a value of its own, and no response of this backend has a legitimate
                # reason to want sniffing.
                # ASGI declares `headers` optional on `http.response.start`, and
                # `MutableHeaders(scope=...)` indexes it without a default. Every sender in
                # this repository emits it — starlette's `Response` always does, and
                # `http_limits._refuse` builds the list explicitly — so this only guards a
                # future hand-rolled response, where the alternative is a `KeyError` that
                # degrades into the very unstamped `500` of the residue above.
                message.setdefault("headers", [])
                MutableHeaders(scope=message)[_HEADER] = _VALUE
            await send(message)

        await self._app(scope, receive, stamped)


__all__ = ["NoSniffMiddleware"]
