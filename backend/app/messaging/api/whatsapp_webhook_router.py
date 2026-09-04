"""The anonymous WhatsApp receiver and Meta's verification handshake (R3.1, R3.3, R3.4, D3a).

**A router of its own, and for the reason `integrations/api/webhooks_router.py` gives for
being one**: `messaging/api/router.py` carries `responses=AUTHENTICATED_RESPONSES` and every
route on it declares a permission. These two are anonymous by design, and putting an
unauthenticated route inside a router whose whole shape says "authenticated" is the kind of
thing that survives review by looking ordinary.

**One fixed path for the whole platform** (R3.1 as amended on 2026-09-02, design D3): Meta
admits a single webhook subscription per App, so there is no per-tenant URL segment to hang a
token on and rule 12(b)'s literal mechanism does not apply. What authenticates a delivery is
Meta's real `X-Hub-Signature-256` over the raw body (D3a), verified against the one global
`WHATSAPP_APP_SECRET`; the tenant is resolved **afterwards**, from the `phone_number_id` the
delivery names, and never from the route or from any field the sender controls (R4.1).

**Thin, in the same sense D5 fixes for its PMS sibling.** What lives here is transport:

* the two rate limits (task 7.3), which are properly `api/`'s business;
* reading the body **once, as raw bytes**, because the body is the credential;
* the translation of the one domain exception into `403`, and of the throttle's into `429`;
* the `202` with no body, whatever the delivery turned out to be.

What does **not** live here is the decision — which tenant a number resolves to, what a
message-less body means, what gets persisted and what gets dispatched. All of that is
`application/webhooks.py`, tested without FastAPI in the way.

**The order of the two limits and the authentication is not cosmetic**, and it is the order
the security panel of `reservations-webhooks` section 2 arrived at after both halves were
wrong once: the per-IP probe budget is checked FIRST, before any work; authentication comes
next; and only a caller that authenticated spends the delivery budget. One difference from
that precedent is forced by Meta and worth naming: authentication there never touches the body,
so the route can refuse before reading it, while here the signature IS over the body — so the
body is read before the credential is checked, bounded by `MaxBodySizeMiddleware`'s ceiling,
which applies to all of `/api/v1/` **before routing** and therefore needs no code here (R3.4,
and `tests/integrations/test_webhook_body_ceiling.py` for the mechanism).
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.requests import ClientDisconnect

from app.auth.api.dependencies import get_client_ip, now_utc
from app.core.config import settings
from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.core.openapi import ErrorEnvelope
from app.integrations.api.dependencies import get_webhook_throttle
from app.integrations.infrastructure.throttle import RedisWebhookThrottle
from app.messaging.api.dependencies import get_receive_whatsapp_webhook_use_case
from app.messaging.application.webhooks import ReceiveWhatsAppWebhookUseCase
from app.messaging.domain.exceptions import WhatsAppWebhookAuthenticationError
from app.messaging.domain.whatsapp_webhook import secrets_match

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

ClientIpDep = Annotated[str, Depends(get_client_ip)]
ThrottleDep = Annotated[RedisWebhookThrottle, Depends(get_webhook_throttle)]
UseCaseDep = Annotated[
    ReceiveWhatsAppWebhookUseCase, Depends(get_receive_whatsapp_webhook_use_case)
]

#: The single path, shared by the receiver and the handshake (R3.1, D3).
WHATSAPP_WEBHOOK_PATH = "/whatsapp"

#: What `delivery_allowed` is keyed on, and the one judgment call the design left open.
#:
#: Its PMS sibling keys that budget on the authenticated endpoint's token hash, so the unit is
#: the tenant (design D6 of `reservations-webhooks`). There is no per-tenant credential here —
#: one Meta App, one subscription, one shared secret — and the only per-tenant identity in the
#: request is `phone_number_id`, which lives inside the body and is therefore not known until
#: after the use case has parsed it, i.e. after the work this budget exists to bound.
#:
#: So the budget is the subscription's, spelled as a constant. Two things make that the right
#: unit rather than a compromise:
#:
#: * what it protects against is a runaway retry loop filling `whatsapp_inbound_events`, and
#:   Meta's retry behaviour is a property of the App, not of one tenant's number;
#: * D6's objection to a shared budget was that an **outsider** could spend a tenant's — or
#:   every tenant's — allowance. Nobody without `WHATSAPP_APP_SECRET` gets this far: the
#:   counter is only ever reached by a caller whose signature verified, and a forged delivery
#:   spends the per-IP probe budget instead.
#:
#: The cost is real and stated rather than hidden: `WEBHOOK_RATE_LIMIT_PER_MINUTE` (120 by
#: default) now bounds inbound guest messages **platform-wide**, so at a scale where two
#: messages a second is plausible it has to be raised, or re-keyed per `phone_number_id` by
#: moving the check behind the parse. At the MVP's 25-50 units it is ample headroom.
WHATSAPP_DELIVERY_BUDGET_KEY = "whatsapp:meta:shared-subscription"

# The one answer for every authentication outcome (R3.3). Built once so the call sites cannot
# drift apart: a `403` that differs by a word is still an oracle.
_FORBIDDEN = error_envelope(ErrorCode.FORBIDDEN, "Forbidden")
_RATE_LIMITED = error_envelope(ErrorCode.RATE_LIMITED, "Too many requests")

# The literal rather than `status.HTTP_413_*`: Starlette renamed the constant
# (`REQUEST_ENTITY_TOO_LARGE` → `CONTENT_TOO_LARGE`) and deprecated the old spelling, so naming
# either one dates this file to a version. `app/core/http_limits.py` writes the number too.
_PAYLOAD_TOO_LARGE_STATUS = 413

_RECEIVER_RESPONSES: dict[int | str, dict[str, Any]] = {
    403: {
        "model": ErrorEnvelope,
        "description": (
            "Not authenticated. Returned identically for a missing `X-Hub-Signature-256`, a "
            "malformed one, a digest computed under another key and a body altered after "
            "signing — the endpoint never reveals which (R3.3). Nothing is written."
        ),
    },
    429: {
        "model": ErrorEnvelope,
        "description": (
            "Rate limited: either the subscription's per-minute delivery budget, or the "
            "stricter per-IP budget that only failed authentications consume."
        ),
    },
    413: {
        "model": ErrorEnvelope,
        "description": "The request body exceeded the ceiling applied to all of /api/v1/.",
    },
}

_HANDSHAKE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        # `content` by hand rather than a `response_model`: the body is `hub.challenge`
        # echoed as plain text, which has no JSON schema. `tests/test_openapi_contract.py`
        # admits exactly this discharge of "declare the shape of what you return".
        "content": {"text/plain": {"schema": {"type": "string"}}},
        "description": (
            "The `hub.challenge` value, echoed verbatim as plain text. Meta accepts the "
            "subscription only on this exact body."
        ),
    },
    403: {
        "description": (
            "The verify token did not match, or was absent. Empty body, and identical for "
            "both — including a request missing `hub.challenge` altogether."
        )
    },
}


@router.get(
    WHATSAPP_WEBHOOK_PATH,
    include_in_schema=True,
    responses=_HANDSHAKE_RESPONSES,
    summary="Answer Meta's webhook verification handshake",
    description=(
        "Meta calls this once, when an operator saves the webhook URL in the App dashboard, "
        "and refuses to save the subscription unless the `hub.challenge` comes back in plain "
        "text. Anonymous by necessity — there is no operator session behind Meta's call — with "
        "`WHATSAPP_WEBHOOK_VERIFY_TOKEN` as the shared secret that authorises it."
    ),
)
async def verify_whatsapp_webhook(
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    """`200` with the challenge as plain text, or an empty `403`. Design D3a.

    **All three parameters are optional, and that is what keeps the failures uniform.** A
    required query parameter would make FastAPI answer `422` for an absent one — a different
    status for "no token" than for "wrong token", which is exactly the oracle R3.3's discipline
    closes. So the handler decides, and every refusal is the same empty `403`: a wrong token, a
    missing token, a missing challenge and a wrong `hub.mode` alike.

    `secrets_match` and not `==`: the same constant-time comparison rule 12(a) requires in
    those words, re-exported for this path by `domain/whatsapp_webhook.py`. It is the one
    primitive that module exists to lend, and using `==` here would be the second copy of a
    comparison that its docstring warns about.

    The configured token is read through `secrets_match` even when it is `None`, normalised to
    `""` — so a deployment that never set the variable answers `403` to everything instead of
    matching an empty query parameter. `Settings` also refuses to boot in that state under
    `meta`; this is the second net.
    """
    expected = settings.whatsapp_webhook_verify_token or ""
    if (
        hub_mode != "subscribe"
        or hub_verify_token is None
        or hub_challenge is None
        or not secrets_match(hub_verify_token, expected)
    ):
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    # `media_type` is what Meta requires: it compares the body byte for byte, and a JSON
    # `"12345"` — quotes included — is not the challenge it sent.
    return PlainTextResponse(hub_challenge, status_code=status.HTTP_200_OK)


@router.post(
    WHATSAPP_WEBHOOK_PATH,
    status_code=status.HTTP_202_ACCEPTED,
    include_in_schema=True,
    responses=_RECEIVER_RESPONSES,
    summary="Receive an inbound WhatsApp message",
    description=(
        "Anonymous by design: Meta's `X-Hub-Signature-256` over the raw body is the "
        "credential (design D3a), verified in constant time against the platform's single "
        "`WHATSAPP_APP_SECRET`. Answers `202` with no body once the delivery is recorded, and "
        "an indistinguishable `403` for a missing, malformed, mis-keyed or stale signature "
        "alike. The message is processed on a queued task, never inside this response."
    ),
)
async def receive_whatsapp_webhook(
    request: Request,
    client_ip: ClientIpDep,
    throttle: ThrottleDep,
    use_case: UseCaseDep,
) -> Response:
    """`202`, `403`, `429` or `413`. Never `401`, and never a body that says why.

    **Every outcome the use case can report answers `202`**, and that is a requirement rather
    than laziness: Meta redelivers on any non-2xx, so a `422` for a delivery receipt would put
    every receipt of our own outbound replies into an infinite retry loop, and a `404` for an
    unprovisioned number would do the same to a guest's message while an operator finished
    setting the number up. The four outcomes are told apart in the log and in the row, which
    are the surfaces an operator has; the response carries no body at all, because anything
    echoed to an anonymous caller is a signal.
    """
    if not await throttle.probe_allowed(client_ip):
        # Checked FIRST, before any work — including before the body is read. This is the
        # limit that makes forging a signature cost something (R3.4), so it has to bite
        # before the work a guesser is trying to provoke.
        return _refused(status.HTTP_429_TOO_MANY_REQUESTS, _RATE_LIMITED)

    try:
        raw_body = await request.body()
    except ClientDisconnect:
        # The body was cut short — which is what `MaxBodySizeMiddleware` does to a request
        # over the ceiling: it stops feeding the reader and answers `413` itself. Returning
        # here, before anything is authenticated or recorded, keeps "nothing written" true for
        # the one refusal that arrives as a truncated stream rather than as a status.
        return _refused(
            _PAYLOAD_TOO_LARGE_STATUS,
            error_envelope(ErrorCode.PAYLOAD_TOO_LARGE, "Payload too large"),
        )

    try:
        # The raw bytes, not `await request.json()`: re-serialising a parsed body changes key
        # order and separators, so a perfectly valid signature would fail. JSON parsing
        # happens inside `record`, and only after this line has returned.
        use_case.authenticate(
            raw_body=raw_body, headers=request.headers, url=str(request.url)
        )
    except WhatsAppWebhookAuthenticationError:
        # The ONLY place a failed authentication is counted (R3.4). Counting every request
        # would collapse the two limits into one and throttle Meta's legitimate traffic for
        # every tenant at once.
        await throttle.record_failed_attempt(client_ip)
        return _refused(status.HTTP_403_FORBIDDEN, _FORBIDDEN)

    # Charged only now, to a caller that proved it holds the App secret. Keyed on the
    # subscription rather than on a tenant — see `WHATSAPP_DELIVERY_BUDGET_KEY` for why that
    # is the honest unit here and what it costs.
    if not await throttle.delivery_allowed(WHATSAPP_DELIVERY_BUDGET_KEY):
        return _refused(status.HTTP_429_TOO_MANY_REQUESTS, _RATE_LIMITED)

    await use_case.record(raw_body=raw_body, headers=request.headers, now=now_utc())
    return Response(status_code=status.HTTP_202_ACCEPTED)


def _refused(status_code: int, body: dict[str, Any]) -> Response:
    """A refusal carrying the PRD §23 envelope and nothing else."""
    return JSONResponse(status_code=status_code, content=body)
