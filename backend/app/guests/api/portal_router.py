"""The anonymous guest portal (PRD §23; R2.2, R2.3, R2.4; design D1, D5, D6, D7, D16).

**A router of its own, and not more routes on `guests/api/router.py`.** That one carries
`responses=AUTHENTICATED_RESPONSES` and hangs every route off `require(...)`; these are
anonymous by design, because the token in the path *is* the credential. Mixing them would put
an unauthenticated route inside a router whose whole shape says "authenticated" — which
`app/main.py` names as "esconder un endpoint sin autenticar dentro de una forma que dice lo
contrario", and which survives review by looking ordinary. The entries this forces into
`ANONYMOUS_ENDPOINTS` are the visible diff that decision has to pass through — today
`GET /info/{token}`, `GET /checkin/{token}`, `POST /checkin/{token}`,
`POST /incident/{token}` and, since `guest-portal-messaging`, `GET /messages/{token}` and
`POST /messages/{token}`.

**Thin in the exact sense D4 fixes.** What lives here is transport: the two rate limits, the
translation of one domain exception into one constant `404`, and serialisation. The decision
— which token resolves which tenant, whether the window has closed — is
`application/portal.py`, testable with no FastAPI in the way. D4 rejects a dependency that
returns the `GuestSession` for precisely that reason: this file *calls* the authoriser, in
one helper, and decides nothing.

**R2.3 is satisfied by absence.** No route here declares `bearer_scheme`, `AuthenticatedDep`
or `require(...)`, so no code reads `Authorization`. A request carrying a valid JWT and an
invalid path token gets the same `404` as any other — and a rejection that first parsed the
header in order to refuse it would be worse, because it would mean reading the header at all.

**The order of operations is the security contract**, and it comes from the section 5
security panel (recorded in `tasks.md` 6.1):

1. `probe_allowed(ip)` before any **lookup** — this is the limit that makes guessing cost
   something, so it has to bite before the queries a guesser is trying to provoke. Not
   before *everything*, and the difference is measured rather than assumed: on the `POST`,
   FastAPI parses and validates the body while solving dependencies, so a malformed one is
   a `422` that never reaches this function and never spends a budget. That is bounded by
   `MaxBodySizeMiddleware` (D7) and costs no information — the `422` is identical whatever
   the token — but the first version of this list said "before **any** work" and the
   security panel of section 6 measured it false;
2. `authorize(token, now_utc())`;
3. `record_failed_authorisation(ip)` on **every** rejection, awaited before the response —
   charging only some causes would make the throttle itself the distinguisher D5 forbids;
4. `request_allowed(session.token_hash)` only after authorising, with the digest already in
   hand — never by re-hashing the path segment, which would put the cleartext back into
   circulation for nothing.

The body ceiling needs no code here: `MaxBodySizeMiddleware` covers all of `/api/v1/` before
routing (D7), so an oversized body is refused before this module is reached.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import JSONResponse

from app.auth.api.dependencies import get_client_ip, now_utc
from app.core.error_codes import ErrorCode
from app.core.errors import error_envelope
from app.core.openapi import ErrorEnvelope
from app.guests.api.portal_dependencies import (
    get_checkin_status_use_case,
    get_guest_portal_authenticator,
    get_guest_portal_throttle,
    get_post_portal_guest_message_use_case,
    get_read_portal_thread_use_case,
    get_report_guest_incident_use_case,
    get_stay_info_use_case,
    get_submit_guest_checkin_use_case,
)
from app.guests.api.portal_schemas import (
    CheckinStatusResponse,
    CheckinSubmittedResponse,
    GuestMessageResponse,
    GuestThreadResponse,
    IncidentReportedResponse,
    PostGuestMessageRequest,
    ReportIncidentRequest,
    StayInfoResponse,
    SubmitCheckinRequest,
)
from app.guests.application.portal import (
    GetCheckinStatusUseCase,
    GetStayInfoUseCase,
    GuestPortalAuthenticator,
    SubmitGuestCheckinUseCase,
)
from app.guests.application.use_cases import DocumentInput
from app.guests.domain.exceptions import GuestPortalUnauthorised
from app.guests.domain.portal_ports import (
    GuestPortalMessageSubmitter,
    GuestPortalThreadReader,
    GuestSession,
)
from app.guests.infrastructure.portal_throttle import RedisGuestPortalThrottle
from app.maintenance.application.use_cases import ReportGuestIncidentUseCase
from app.messaging.api.schemas import MAX_PAGE, MAX_PER_PAGE

router = APIRouter(prefix="/guest", tags=["guest-portal"])

ClientIpDep = Annotated[str, Depends(get_client_ip)]
ThrottleDep = Annotated[RedisGuestPortalThrottle, Depends(get_guest_portal_throttle)]
AuthenticatorDep = Annotated[
    GuestPortalAuthenticator, Depends(get_guest_portal_authenticator)
]

#: The one answer for every failure (D5, R2.2). One body, built once, and since the routes
#: were centralised on `_unauthorised` there is also exactly **one place that sends it** — so
#: what used to be four call sites that must not drift apart is now a single one they all go
#: through. A `404` that differs by a word is still an oracle.
_NOT_FOUND = error_envelope(ErrorCode.NOT_FOUND, "Not found")
_RATE_LIMITED = error_envelope(ErrorCode.RATE_LIMITED, "Too many requests")

# Declared per endpoint rather than reusing `AUTHENTICATED_RESPONSES` (D16): these routes
# cannot promise a `401` they never return. The three below ARE the contract — D5's uniform
# `404`, R2.4's `429` and D7's `413` — and each is pinned by a test.
#
# **These strings are anonymous-readable**: `/openapi.json` and `/docs` are themselves in
# `ANONYMOUS_ENDPOINTS`, so whatever is written here is published to the same caller D5 is
# defending against. Two consequences the documentation panel of section 6 drew out. The
# `404` gives no list of causes: an enumeration is both a hint and a promise this endpoint
# cannot keep, since a stay that stops resolving mid-request answers the same way. And the
# `429` does not say which budget it came from — that only failed authorisations consume the
# per-IP one is true, useful to us, and exactly the kind of thing to leave in `design.md`
# and `.env.example`, which are not served over HTTP.
_PORTAL_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {
        "model": ErrorEnvelope,
        "description": (
            "This link does not authorise the request. One answer for every cause, with no "
            "list of them: the endpoint never reveals which, so it cannot be used to "
            "discover whether a reservation exists. Treat it as 'ask the host for a new "
            "link', never as a hint about the request body."
        ),
    },
    429: {
        "model": ErrorEnvelope,
        "description": "Rate limited. Retry in a minute.",
    },
    413: {
        "model": ErrorEnvelope,
        "description": "The request body exceeded the ceiling applied to all of /api/v1/.",
    },
}


def _refused(status_code: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=body)


async def _unauthorised(
    throttle: RedisGuestPortalThrottle, client_ip: str
) -> JSONResponse:
    """The one refusal, charged to the per-IP budget, awaited before it is sent.

    Every `GuestPortalUnauthorised` goes through here — the ones `_authorised` raises and the
    later ones a use case can raise once the token has already resolved (a stay that stops
    being reachable mid-request, a `Guest` row that is gone, a claim lost to a concurrent
    submission). The architecture and documentation panels of section 6 found the later ones
    answering without charging anything, while two docstrings claimed "on **every**
    rejection".

    Charging them costs a legitimate bearer part of its own IP budget in a situation that
    should not arise. That is the cheaper side of the trade: an uncharged branch is a branch
    a caller can tell apart by watching what its budget does, which is the distinguisher D5
    forbids, and the branches are exactly the ones that depend on database state an attacker
    might be able to move.
    """
    await throttle.record_failed_authorisation(client_ip)
    return _refused(status.HTTP_404_NOT_FOUND, _NOT_FOUND)


async def _authorised(
    token: str, client_ip: str, throttle: RedisGuestPortalThrottle, authenticator: GuestPortalAuthenticator
) -> GuestSession | JSONResponse:
    """The four steps every portal route shares, in the one order that is safe.

    Returns either the session or the response to send. A helper rather than a FastAPI
    dependency, deliberately: D4 rejects a dependency that returns the `GuestSession`,
    because that would put the authorisation decision in `api/`. This puts the *sequence*
    in one place while leaving the decision in `application/`.

    One place rather than four copies matters more than usual here. Every clause below is a
    constraint from the section 5 security panel, and a route that got the order subtly wrong
    — charged the throttle before authorising, or skipped the failure count on one branch —
    would still return the right status code while reopening the oracle.
    """
    if not await throttle.probe_allowed(client_ip):
        return _refused(status.HTTP_429_TOO_MANY_REQUESTS, _RATE_LIMITED)

    try:
        session = await authenticator.authorize(token, now_utc())
    except GuestPortalUnauthorised:
        # Charged on **every** rejection, and awaited before answering. Counting only some
        # causes would let a caller tell them apart by watching their own budget — which is
        # why the routes route their later refusals through the same helper.
        return await _unauthorised(throttle, client_ip)

    if not await throttle.request_allowed(session.token_hash):
        # Charged only now, to a caller that proved it holds the token, and keyed by the
        # digest the authoriser already resolved.
        return _refused(status.HTTP_429_TOO_MANY_REQUESTS, _RATE_LIMITED)

    return session


@router.get(
    "/info/{token}",
    response_model=StayInfoResponse,
    responses=_PORTAL_RESPONSES,
    summary="The guest's stay information",
    description=(
        "Everything the guest needs in order to arrive: dates and times, the property's "
        "public details, the arrival instructions and the support channel. Never the "
        "reservation's internal notes, its amounts, its external PMS or channel ids, another "
        "guest's data, or any credential — those are not fields of the projection, so no "
        "serialiser can reach them. Never a document number either, not even for the guest "
        "who supplied it."
    ),
)
async def read_stay_info(
    token: str,
    client_ip: ClientIpDep,
    throttle: ThrottleDep,
    authenticator: AuthenticatorDep,
    use_case: Annotated[GetStayInfoUseCase, Depends(get_stay_info_use_case)],
) -> Response:
    session = await _authorised(token, client_ip, throttle, authenticator)
    if isinstance(session, JSONResponse):
        return session

    try:
        info = await use_case.execute(session)
    except GuestPortalUnauthorised:
        return await _unauthorised(throttle, client_ip)
    return JSONResponse(content=StayInfoResponse.from_domain(info).model_dump(mode="json"))


@router.get(
    "/checkin/{token}",
    response_model=CheckinStatusResponse,
    responses=_PORTAL_RESPONSES,
    summary="What the guest still has to provide",
    description=(
        "The names of the fields of PRD §17 that are still missing, plus the document and "
        "legal-registration statuses. **Never the values already supplied** — the guest knows "
        "what they typed, and echoing it back would put personal data in one more response "
        "body for no benefit."
    ),
)
async def read_checkin_status(
    token: str,
    client_ip: ClientIpDep,
    throttle: ThrottleDep,
    authenticator: AuthenticatorDep,
    use_case: Annotated[GetCheckinStatusUseCase, Depends(get_checkin_status_use_case)],
) -> Response:
    session = await _authorised(token, client_ip, throttle, authenticator)
    if isinstance(session, JSONResponse):
        return session

    try:
        result = await use_case.execute(session)
    except GuestPortalUnauthorised:
        return await _unauthorised(throttle, client_ip)
    return JSONResponse(
        content=CheckinStatusResponse.from_domain(result).model_dump(mode="json")
    )


@router.post(
    "/checkin/{token}",
    response_model=CheckinSubmittedResponse,
    responses=_PORTAL_RESPONSES,
    summary="Submit the guest's legal check-in data",
    description=(
        "The six fields of PRD §17 the guest supplies; the two dates are the reservation's "
        "and are neither asked for nor accepted. The document number is encrypted at rest in "
        "the same call and **is not echoed back**. Resending the same form is safe: it "
        "converges on the same state and does not add a second timeline entry, though it "
        "does leave a second audit row — a repeated submission is exactly what a review "
        "would want to see."
    ),
)
async def submit_checkin(
    token: str,
    payload: SubmitCheckinRequest,
    client_ip: ClientIpDep,
    throttle: ThrottleDep,
    authenticator: AuthenticatorDep,
    use_case: Annotated[SubmitGuestCheckinUseCase, Depends(get_submit_guest_checkin_use_case)],
) -> Response:
    session = await _authorised(token, client_ip, throttle, authenticator)
    if isinstance(session, JSONResponse):
        return session

    try:
        result = await use_case.execute(
            session=session,
            document=DocumentInput(
                full_name=payload.full_name,
                nationality=payload.nationality,
                date_of_birth=payload.date_of_birth,
                document_type=payload.document_type,
                document_number=payload.document_number,
                document_expiry_date=payload.document_expiry_date,
            ),
            ip=client_ip or None,
            now=now_utc(),
        )
    except GuestPortalUnauthorised:
        return await _unauthorised(throttle, client_ip)
    return JSONResponse(
        content=CheckinSubmittedResponse.from_domain(result).model_dump(mode="json")
    )


@router.post(
    "/incident/{token}",
    response_model=IncidentReportedResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PORTAL_RESPONSES,
    summary="Report an incident during the stay",
    description=(
        "Opens an incident against the guest's own stay, exactly as any other source would: "
        "`OPEN`, with no category, severity or classification — those belong to the "
        "maintenance flow, and a report made here is indistinguishable to it from any other. "
        "A title and a description, both required; nothing else is accepted. The "
        "acknowledgement is the id, the status and the instant, and that is the only reading "
        "of an incident this surface ever offers: there is no endpoint here to list, read, "
        "modify, assign or resolve one. Retrying creates a second incident — the request is "
        "not deduplicated — so treat a `429` as 'wait', never as 'it did not arrive'."
    ),
)
async def report_incident(
    token: str,
    payload: ReportIncidentRequest,
    client_ip: ClientIpDep,
    throttle: ThrottleDep,
    authenticator: AuthenticatorDep,
    use_case: Annotated[
        ReportGuestIncidentUseCase, Depends(get_report_guest_incident_use_case)
    ],
) -> Response:
    session = await _authorised(token, client_ip, throttle, authenticator)
    if isinstance(session, JSONResponse):
        return session

    # Every identifier comes from the session the authoriser resolved, never from the request
    # (R2.1) — and `ReportIncidentRequest` forbids extra fields, so a body carrying
    # `property_id` or `reservation_id` is a `422` rather than something silently dropped.
    incident = await use_case.execute(
        tenant_id=session.tenant_id,
        property_id=session.property_id,
        reservation_id=session.reservation_id,
        # The digest the authoriser already had in hand. Re-hashing the path segment here
        # would put the cleartext back into circulation for nothing.
        reporter_token_hash=session.token_hash,
        title=payload.title,
        description=payload.description,
        ip=client_ip or None,
        now=now_utc(),
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=IncidentReportedResponse.from_domain(incident).model_dump(mode="json"),
    )


@router.post(
    "/messages/{token}",
    response_model=GuestMessageResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_PORTAL_RESPONSES,
    summary="Write a message to the accommodation",
    description=(
        "Sends one message from the guest and runs the whole messaging pipeline over it: the "
        "language is detected, the intent classified, and either an automatic answer is "
        "written or a person is asked to take over. The stay's thread is created by this "
        "first message and by nothing else. The body carries the text and nothing else — a "
        "sender, a reservation or a conversation id in it is a `422`, never something quietly "
        "ignored — and the acknowledgement is the message as it will appear in the thread. "
        "Retrying sends a second message: the request is not deduplicated, so treat a `429` "
        "as 'wait', never as 'it did not arrive'."
    ),
)
async def post_guest_message(
    token: str,
    payload: PostGuestMessageRequest,
    client_ip: ClientIpDep,
    throttle: ThrottleDep,
    authenticator: AuthenticatorDep,
    submitter: Annotated[
        GuestPortalMessageSubmitter, Depends(get_post_portal_guest_message_use_case)
    ],
) -> Response:
    session = await _authorised(token, client_ip, throttle, authenticator)
    if isinstance(session, JSONResponse):
        return session

    # Every identifier comes from the session the authoriser resolved (R1.3), and
    # `PostGuestMessageRequest` forbids extra fields, so a body naming a tenant, a reservation
    # or a `sender_type` is a `422` rather than something silently dropped.
    #
    # `client_ip` is not one of them: it is the address the request arrived from, which the
    # caller cannot claim, and rule 9 of `steering/security.md` wants it in `actor_ip`. The
    # sibling anonymous route above has always passed it; omitting it here gave the same
    # anonymous actor two different audit trails for the same entity.
    #
    # **What bounds how many `audit_logs` rows a bearer can write is the per-token throttle
    # `_authorised` already charged, and nothing else** (D8). A message classified as an
    # incident opens one, and the pipeline writes an audit row per incident, so this route is
    # the third of the de-facto cases rule 9's own exception describes: the rate limit is the
    # bound. Said here because it is not visible from the pipeline's side.
    message = await submitter.submit(
        session,
        content=payload.content,
        client_ip=client_ip or None,
        now=now_utc(),
    )
    return JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=GuestMessageResponse.from_domain(message).model_dump(mode="json"),
    )


@router.get(
    "/messages/{token}",
    response_model=GuestThreadResponse,
    responses=_PORTAL_RESPONSES,
    summary="The guest's own thread",
    description=(
        "One page of the stay's conversation, oldest first within the page. Every message is "
        "attributed to the guest or to the accommodation and to nothing finer: which member "
        "of staff wrote a reply, and whether it was written automatically, are not fields of "
        "this response. Neither is the reason a conversation is waiting for a person — only "
        "that it is. A stay whose guest has not written yet answers with an empty thread: "
        "reading never opens a conversation. **Without `page` the most recent window is "
        "returned**, since a thread is read from its end; `total`, `page` and `per_page` say "
        "which window it is, and an explicit `page` still reaches the earlier ones."
    ),
)
async def read_guest_thread(
    token: str,
    client_ip: ClientIpDep,
    throttle: ThrottleDep,
    authenticator: AuthenticatorDep,
    reader: Annotated[
        GuestPortalThreadReader, Depends(get_read_portal_thread_use_case)
    ],
    # `None` and not a defaulted `1`: D9 makes the unasked-for window the **last** page, so the
    # use case has to be able to tell "no preference" from "page 1". The bounds are the ones
    # `messaging/api/schemas.py` already declares, imported rather than restated — `page`
    # becomes a SQL OFFSET, and one spelling of a ceiling is how two stay equal.
    page: Annotated[int | None, Query(ge=1, le=MAX_PAGE)] = None,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 50,
) -> Response:
    session = await _authorised(token, client_ip, throttle, authenticator)
    if isinstance(session, JSONResponse):
        return session

    try:
        thread = await reader.read(session, page=page, per_page=per_page)
    except GuestPortalUnauthorised:
        return await _unauthorised(throttle, client_ip)
    return JSONResponse(
        content=GuestThreadResponse.from_domain(thread).model_dump(mode="json")
    )
