"""One flattening of the application's route tree, shared by the structural guards.

This FastAPI version keeps an included router as a single `_IncludedRouter` object
instead of copying its endpoints into `app.routes`. A guard that walks `app.routes` and
keeps `isinstance(route, APIRoute)` therefore inspects ZERO of the included endpoints
and passes while checking nothing.

The trap has now been hit twice: `test_route_authorization.py` was written against it
after review caught it, and the contract guard of `api-contract-export` was then written
*mirroring that file* — copying its shape but not the walk that makes it work — and
shipped green while inspecting an empty list. So the walk lives here, in one place, and
is imported rather than described for the next author to re-derive.
"""

from fastapi import FastAPI
from fastapi.routing import APIRoute


def flatten_routes(app: FastAPI) -> tuple[list[tuple[str, APIRoute]], list[tuple[str, object]]]:
    """Every `APIRoute` with its fully-prefixed path, plus everything that is not one.

    The second list is not a leftover to discard: a `@app.websocket(...)`, an
    `app.mount(...)` or a plain starlette `Route` is real surface, and a caller that
    drops it silently is guarding a subset it never declared. Each caller decides what
    that surface means for its own check.

    Paths come from the walk, not from `route.path` — an included route only knows its
    own suffix, so `route.path` alone would never match a prefix filter.
    """
    found: list[tuple[str, APIRoute]] = []
    other: list[tuple[str, object]] = []

    def walk(routes, prefix: str) -> None:
        for route in routes:
            inner = getattr(route, "original_router", None)
            path = prefix + str(getattr(route, "path", "?"))
            if inner is not None:
                context = getattr(route, "include_context", None)
                walk(inner.routes, prefix + getattr(context, "prefix", ""))
            elif isinstance(route, APIRoute):
                found.append((path, route))
            else:
                other.append((path, route))

    walk(app.routes, "")
    return found, other
