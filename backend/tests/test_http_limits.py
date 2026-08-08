"""`MaxBodySizeMiddleware` on its own, including the trap the security review found.

The endpoint-level behaviour is covered in `tests/integrations/test_import_hardening.py`; here the
middleware is driven directly, because the failure mode that matters — emitting two
`http.response.start` messages — is invisible through a client and only appears if you watch what
reaches the server. It is not reachable through today's only upload route (FastAPI reads the whole
form before any `send`), but the PRD §16 webhook receiver is coming to the same prefix.
"""

import pytest

from app.core.http_limits import MaxBodySizeMiddleware

LIMIT = 100
PREFIX = "/api/v1/integrations/"


def _scope(path: str = f"{PREFIX}pms/import-csv", *, content_length: str | None = None) -> dict:
    headers = [(b"host", b"test")]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    return {"type": "http", "method": "POST", "path": path, "headers": headers}


class _Recorder:
    """Collects what reaches the server, which is where a double start would show."""

    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.messages.append(message)

    @property
    def starts(self) -> list[int]:
        return [m["status"] for m in self.messages if m["type"] == "http.response.start"]


def _chunks(*bodies: bytes):
    queue = [
        {"type": "http.request", "body": body, "more_body": index < len(bodies) - 1}
        for index, body in enumerate(bodies)
    ]

    async def receive() -> dict:
        return queue.pop(0) if queue else {"type": "http.disconnect"}

    return receive


async def _ok_app(scope, receive, send) -> None:
    while True:
        message = await receive()
        if message["type"] != "http.request" or not message.get("more_body"):
            break
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


def _middleware(app) -> MaxBodySizeMiddleware:
    return MaxBodySizeMiddleware(
        app, path_prefixes=(PREFIX,), max_bytes_provider=lambda _path: LIMIT
    )


@pytest.mark.asyncio
async def test_a_declared_content_length_over_the_limit_is_refused_without_reading_the_body() -> None:
    read = False

    async def receive() -> dict:
        nonlocal read
        read = True
        return {"type": "http.request", "body": b"x" * 200}

    recorder = _Recorder()
    await _middleware(_ok_app)(_scope(content_length="200"), receive, recorder)

    assert recorder.starts == [413]
    assert read is False


@pytest.mark.asyncio
async def test_a_lying_content_length_is_still_caught_while_streaming() -> None:
    recorder = _Recorder()

    await _middleware(_ok_app)(
        _scope(content_length="10"), _chunks(b"x" * 60, b"x" * 60), recorder
    )

    assert recorder.starts == [413]


@pytest.mark.asyncio
async def test_a_body_within_the_limit_passes_through_untouched() -> None:
    recorder = _Recorder()

    await _middleware(_ok_app)(_scope(content_length="10"), _chunks(b"x" * 10), recorder)

    assert recorder.starts == [200]
    assert recorder.messages[-1]["body"] == b"ok"


@pytest.mark.asyncio
async def test_another_path_is_not_measured() -> None:
    recorder = _Recorder()

    await _middleware(_ok_app)(
        _scope("/api/v1/reservations", content_length="9999"), _chunks(b"x" * 500), recorder
    )

    assert recorder.starts == [200]


@pytest.mark.asyncio
async def test_it_never_emits_a_second_response_start() -> None:
    """The trap: an app that answers BEFORE the limit is hit, then keeps reading.

    Forwarding its `200` and then synthesising a `413` produces two `http.response.start`
    messages, which uvicorn turns into a `RuntimeError` and the client sees as a dangling 200 with
    no body.
    """

    async def _answers_then_keeps_reading(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        while True:
            message = await receive()
            if message["type"] != "http.request" or not message.get("more_body"):
                break
        await send({"type": "http.response.body", "body": b"late"})

    recorder = _Recorder()
    await _middleware(_answers_then_keeps_reading)(
        _scope(), _chunks(b"x" * 60, b"x" * 60), recorder
    )

    assert recorder.starts == [200]
    assert len(recorder.starts) == 1


@pytest.mark.asyncio
async def test_a_genuine_application_error_is_not_reported_as_a_size_problem() -> None:
    """The `except Exception` must not swallow an endpoint bug that happens to coincide."""

    async def _broken_app(scope, receive, send) -> None:
        await receive()
        raise RuntimeError("a real bug in the endpoint")

    recorder = _Recorder()

    with pytest.raises(RuntimeError, match="a real bug"):
        await _middleware(_broken_app)(_scope(content_length="10"), _chunks(b"x" * 10), recorder)

    assert recorder.starts == []


@pytest.mark.asyncio
async def test_a_parser_error_caused_by_the_truncated_body_becomes_the_413() -> None:
    """When the body WAS cut short, an exception from the app is this middleware's own doing."""

    async def _chokes_on_truncated_body(scope, receive, send) -> None:
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                raise RuntimeError("unexpected end of form data")

    recorder = _Recorder()
    await _middleware(_chokes_on_truncated_body)(_scope(), _chunks(b"x" * 200), recorder)

    assert recorder.starts == [413]


@pytest.mark.asyncio
async def test_the_limit_can_differ_per_path() -> None:
    """The whole of `/api/v1/` is covered, with uploads on their own, larger ceiling.

    Change `api-ingress-routing`: while the backend listened only on loopback, leaving
    every non-upload path unbounded cost nothing. With `/api/v1` reachable from the
    internet it was an anonymous memory amplifier — measured at 1.016 GiB of RSS from one
    400 MB `POST /api/v1/auth/login`, read by FastAPI **before** the login throttle runs.
    """

    def by_path(path: str) -> int:
        return 10_000 if path.startswith(f"{PREFIX}uploads/") else 100

    middleware = MaxBodySizeMiddleware(
        _ok_app, path_prefixes=(PREFIX,), max_bytes_provider=by_path
    )

    small = _Recorder()
    await middleware(_scope(path=f"{PREFIX}login", content_length="500"), _chunks(b""), small)
    assert small.starts == [413], "a non-upload path takes the small ceiling"

    large = _Recorder()
    await middleware(
        _scope(path=f"{PREFIX}uploads/csv", content_length="500"), _chunks(b"x" * 500), large
    )
    assert large.starts == [200], "an upload path keeps its own, larger ceiling"
