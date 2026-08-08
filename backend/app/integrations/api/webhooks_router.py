"""The anonymous webhook receiver (`reservations-webhooks` R1, R3; design D1, D4, D5).

**A router of its own, and not another route on `integrations/router.py`.** That one carries
`responses=AUTHENTICATED_RESPONSES` and every route on it declares a permission; this one is
anonymous by design, because rule 12(b) makes the route token itself the credential. Mixing them
would put an unauthenticated route inside a router whose whole shape says "authenticated", which is
the kind of thing that survives review by looking ordinary.

**Thin, in the exact sense D5 fixes.** What lives here is transport and nothing else:

* the two rate limits (D6), which are properly `api/`'s business;
* the translation of the domain's one exception into `404`, and of the throttle's into `429`;
* the `202` with no business body.

What does **not** live here is the decision. Which token resolves which tenant, whether the header
matches, what gets discarded and what gets persisted — all of that is
`application/webhooks.py`, tested without FastAPI in the way. `steering/backend.md` puts it
plainly: "la lógica nunca vive en el router".

The body ceiling is not here either, and needs no code: `MaxBodySizeMiddleware` already covers
`/api/v1/` **before routing**, so an oversized body is refused before this module is reached
(D5, and `tests/integrations/test_webhook_body_ceiling.py`).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.requests import ClientDisconnect

from app.auth.api.dependencies import get_client_ip, now_utc
from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.integrations.api.dependencies import get_receive_webhook_use_case, get_webhook_throttle
from app.integrations.application.webhooks import ReceiveWebhookUseCase
from app.integrations.domain.errors import WebhookAuthenticationError
from app.integrations.domain.webhook_auth import hash_webhook_token
from app.integrations.infrastructure.throttle import RedisWebhookThrottle

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ClientIpDep = Annotated[str, Depends(get_client_ip)]
ThrottleDep = Annotated[RedisWebhookThrottle, Depends(get_webhook_throttle)]
UseCaseDep = Annotated[ReceiveWebhookUseCase, Depends(get_receive_webhook_use_case)]

# The one answer for every authentication outcome (D4). Built once so the four call sites cannot
# drift apart: a `404` that differs by a word is still an oracle.
_NOT_FOUND = error_envelope(ErrorCode.NOT_FOUND, "Not found")
_RATE_LIMITED = error_envelope(ErrorCode.RATE_LIMITED, "Too many requests")

# The literal rather than `status.HTTP_413_*`: Starlette renamed the constant
# (`REQUEST_ENTITY_TOO_LARGE` → `CONTENT_TOO_LARGE`) and deprecated the old spelling, so naming
# either one dates this file to a version. `app/core/http_limits.py` writes the number too.
_PAYLOAD_TOO_LARGE_STATUS = 413


@router.post(
    "/{provider}/{webhook_token}",
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=True,
    summary="Receive a PMS webhook notice",
    description=(
        "Anonymous by design: the route token is the credential (rule 12(b)), paired with the "
        "provider's static header (rule 12(a)). Answers `202` with no body once the notice is "
        "queued, and an indistinguishable `404` for an unknown provider, an unknown token, a "
        "missing header and a wrong one alike. Nothing is re-read from the provider here — that "
        "is the job's work, coalesced across a batch."
    ),
)
async def receive_webhook(
    request: Request,
    provider: str,
    webhook_token: str,
    client_ip: ClientIpDep,
    throttle: ThrottleDep,
    use_case: UseCaseDep,
) -> Response:
    """`202`, `404` or `429`. Never `401`, and never a body that says why.

    Returns a bare `Response` rather than a model: R1.1 asks for "sin cuerpo de negocio", and the
    reason is not tidiness. Anything echoed back — an id, a count, the parsed event type — is a
    signal an anonymous caller can read, and the only caller entitled to detail here is one that
    already holds both secrets.
    """
    if not await throttle.probe_allowed(client_ip):
        # Checked FIRST, before any work: this is the limit that makes guessing cost something
        # (R3.4), so it has to bite before the lookup a guesser is trying to provoke.
        return _refused(status.HTTP_429_TOO_MANY_REQUESTS, _RATE_LIMITED)

    if not await throttle.delivery_allowed(hash_webhook_token(webhook_token)):
        # By token hash, never the token: this value becomes a Redis key, and rule 12(b)'s worth
        # is that the route cannot be recovered from somewhere it was incidentally written down.
        return _refused(status.HTTP_429_TOO_MANY_REQUESTS, _RATE_LIMITED)

    try:
        payload = await _parsed_body(request)
    except ClientDisconnect:
        # The body was cut short — which is what `MaxBodySizeMiddleware` does to a request over
        # the ceiling: it stops feeding the parser and answers `413` itself. Returning here,
        # BEFORE the use case, is what keeps R3.2's "sin escribir ningún `WebhookEvent`" true.
        #
        # Found by test, and it was not theoretical: with a blanket `except` around the parse, a
        # truncated body from an authenticated caller looked exactly like malformed JSON, so the
        # notice was queued with an empty payload while the client was told `413`. A refusal that
        # still writes is worse than either outcome on its own — the operator sees a rejected
        # delivery and a row nobody can explain.
        return _refused(
            _PAYLOAD_TOO_LARGE_STATUS,
            error_envelope(ErrorCode.PAYLOAD_TOO_LARGE, "Payload too large"),
        )

    try:
        await use_case.execute(
            provider=provider,
            token=webhook_token,
            get_header=request.headers.get,
            payload=payload,
            now=now_utc(),
        )
    except WebhookAuthenticationError:
        # The ONLY place a failed authentication is counted (R3.4, D6). Counting every request
        # would collapse the two limits into one and throttle a provider's legitimate traffic for
        # all of its tenants at once.
        await throttle.record_failed_attempt(client_ip)
        return _refused(status.HTTP_404_NOT_FOUND, _NOT_FOUND)

    return Response(status_code=status.HTTP_202_ACCEPTED)


async def _parsed_body(request: Request) -> dict[str, Any]:
    """The body as a JSON object, or `{}`. Propagates `ClientDisconnect`.

    Malformed JSON is **not** a `422` here, and that is deliberate: a `422` would tell an
    unauthenticated caller that it got past the route token, which is the oracle D4 closes. An
    unparseable body from a caller that then fails authentication must look like every other
    failure; one from a caller that authenticates is a real notice with a broken body, and
    recording it with an empty payload keeps it visible for diagnosis instead of dropping it.

    **`ClientDisconnect` is deliberately not caught here**, and the distinction is the whole
    reason this is not one blanket `except`: "the caller sent nonsense" and "the body never
    finished arriving" are different facts, and only the first one may be recorded. Treating them
    alike persisted a notice for a request that was simultaneously being refused with `413`.

    A JSON scalar or array is normalised to `{}` for the same reason `payload` is typed `JSONB`
    holding an object: §7.26 declares a mapping, and `scrub_card_data` walks one.
    """
    try:
        parsed = await request.json()
    except ClientDisconnect:
        raise
    except Exception:  # noqa: BLE001 - every parse failure is the same answer
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _refused(status_code: int, body: dict[str, Any]) -> Response:
    """A refusal carrying the PRD §23 envelope and nothing else."""
    return JSONResponse(status_code=status_code, content=body)
