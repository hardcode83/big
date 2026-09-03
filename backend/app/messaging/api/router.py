"""The seven conversation endpoints of PRD §16 (R7.1, R7.2; design D17, D18).

| Route | Permission |
|---|---|
| `GET /conversations` | `READ_CONVERSATIONS` |
| `POST /conversations` | `MANAGE_CONVERSATIONS` |
| `GET /conversations/{id}` | `READ_CONVERSATIONS` |
| `GET /conversations/{id}/messages` | `READ_CONVERSATIONS` |
| `POST /conversations/{id}/messages` | `MANAGE_CONVERSATIONS` |
| `POST /conversations/{id}/escalate` | `MANAGE_CONVERSATIONS` |
| `POST /conversations/{id}/resolve` | `MANAGE_CONVERSATIONS` |

Seven and no more: the PRD declares these, and the inbox of `conversations-inbox` is built against
them. Thin by contract — map Pydantic → use case → Pydantic, and nothing else. Every route
declares its permission with `require(...)`, which `tests/test_route_authorization.py` walks.

**`POST /messages` is one route with two behaviours** (D18), which is the only place this
router comes close to a decision: the body's `sender_type` says which. It is a `Literal`, so
the choice is made by the schema and this module only dispatches on it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.api.dependencies import (
    AuthenticatedRequest,
    get_client_ip,
    now_utc,
    require,
)
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.messaging.api.dependencies import (
    get_associate_whatsapp_phone_number_use_case,
    get_conversation_use_case,
    get_create_conversation_use_case,
    get_escalate_conversation_use_case,
    get_list_conversations_use_case,
    get_list_messages_use_case,
    get_process_inbound_message_use_case,
    get_record_human_reply_use_case,
    get_release_whatsapp_phone_number_use_case,
    get_resolve_conversation_use_case,
)
from app.messaging.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    AssociateWhatsAppPhoneNumberRequest,
    ConversationPageResponse,
    ConversationResponse,
    CreateConversationRequest,
    CreateMessageRequest,
    MessagePageResponse,
    MessageResponse,
    WhatsAppPhoneNumberResponse,
    is_supported_language,
)
from app.messaging.application.use_cases import (
    CreateConversationUseCase,
    EscalateConversationUseCase,
    GetConversationUseCase,
    ListConversationsUseCase,
    ListMessagesUseCase,
    ProcessInboundGuestMessageUseCase,
    RecordHumanReplyUseCase,
    ResolveConversationUseCase,
)
from app.messaging.application.whatsapp_provisioning import (
    AssociateWhatsAppPhoneNumberUseCase,
    ReleaseWhatsAppPhoneNumberUseCase,
)
from app.messaging.domain.enums import ConversationEscalationStatus, ConversationStatus
from app.messaging.domain.exceptions import MessagingValidationError
from app.messaging.domain.repositories import ConversationFilters
from app.messaging.domain.value_objects import InboundMessageActor

router = APIRouter(
    prefix="/conversations", tags=["messaging"], responses=AUTHENTICATED_RESPONSES
)

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_CONVERSATIONS))]
ManageDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_CONVERSATIONS))
]


@router.get(
    "",
    response_model=ConversationPageResponse,
    summary="List the tenant's conversations",
    description=(
        "The inbox. Filtered by `status`, `escalation_status` and `property_id`, paginated "
        "with `page`/`per_page` (PRD §23), and ordered by `last_message_at` descending with "
        "**nulls last** — a conversation created a moment ago and never written to must not "
        "sit above whatever is on fire."
    ),
)
async def list_conversations(
    authenticated: ReadDep,
    use_case: Annotated[ListConversationsUseCase, Depends(get_list_conversations_use_case)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    status_filter: Annotated[ConversationStatus | None, Query(alias="status")] = None,
    escalation_status: ConversationEscalationStatus | None = None,
) -> ConversationPageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        filters=ConversationFilters(
            status=status_filter,
            escalation_status=escalation_status,
            property_id=property_id,
        ),
        page=page,
        per_page=per_page,
    )
    return ConversationPageResponse.from_domain(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=201,
    summary="Open a conversation",
    description=(
        "`property_id` is required (design D19): a conversation without one could not "
        "produce any of the four timeline events this capability declares mandatory. A "
        "conversation opened on `AIRBNB_MSG` or `BOOKING_MSG` is accepted and is **mute by "
        "design** — every send fails until the PMS messaging adapter arrives."
    ),
)
async def create_conversation(
    payload: CreateConversationRequest,
    authenticated: ManageDep,
    use_case: Annotated[CreateConversationUseCase, Depends(get_create_conversation_use_case)],
) -> ConversationResponse:
    if not is_supported_language(payload.language):
        # Answered here as a 422 rather than left to the entity, whose refusal would arrive
        # as a domain error the envelope also renders 422 — same status, but this one names
        # the field the client sent.
        raise MessagingValidationError(
            f"language must be one of the supported locales, got {len(payload.language)} "
            "characters that are not one"
        )
    conversation = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        property_id=payload.property_id,
        channel=payload.channel,
        reservation_id=payload.reservation_id,
        guest_id=payload.guest_id,
        language=payload.language,
        now=now_utc(),
    )
    return ConversationResponse.from_domain(conversation)


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Read one conversation",
    description=(
        "A conversation of another tenant receives the same `404` as one that does not "
        "exist (R1.5)."
    ),
)
async def get_conversation(
    conversation_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetConversationUseCase, Depends(get_conversation_use_case)],
) -> ConversationResponse:
    conversation = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, conversation_id=conversation_id
    )
    return ConversationResponse.from_domain(conversation)


@router.get(
    "/{conversation_id}/messages",
    response_model=MessagePageResponse,
    summary="Read the thread",
    description=(
        "Chronological ascending and paginated (R7.4) — a conversation is read forwards, "
        "unlike the timeline, which is a feed."
    ),
)
async def list_messages(
    conversation_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[ListMessagesUseCase, Depends(get_list_messages_use_case)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 50,
) -> MessagePageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        conversation_id=conversation_id,
        page=page,
        per_page=per_page,
    )
    return MessagePageResponse.from_domain(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
    status_code=201,
    summary="Add a message to a conversation",
    description=(
        "Two behaviours, chosen by `sender_type` (design D18). With `\"GUEST\"` the caller is "
        "transcribing what the guest said and the full pipeline runs: language detection, "
        "classification, escalation policy, and either an automatic reply or a handover to a "
        "person. Omitted, the caller is replying themselves — the `sender_type` is derived "
        "from their role, and replying to a conversation waiting for a person takes it over. "
        "Any other value is a `422`: a client cannot declare that a message was written by "
        "the AI."
    ),
)
async def create_message(
    conversation_id: uuid.UUID,
    payload: CreateMessageRequest,
    authenticated: ManageDep,
    inbound: Annotated[
        ProcessInboundGuestMessageUseCase, Depends(get_process_inbound_message_use_case)
    ],
    human: Annotated[RecordHumanReplyUseCase, Depends(get_record_human_reply_use_case)],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> MessageResponse:
    if payload.sender_type == "GUEST":
        message = await inbound.execute(
            tenant_id=authenticated.context.tenant_id,
            conversation_id=conversation_id,
            content=payload.content,
            # The authenticated door into the pipeline, so the actor is a user
            # (`guest-portal-messaging` D8). The anonymous one builds its actor from the
            # `GuestSession`'s digest instead, in `messaging/application/portal.py`.
            actor=InboundMessageActor(
                user_id=authenticated.context.user_id, ip=client_ip or None
            ),
            now=now_utc(),
        )
    else:
        message = await human.execute(
            tenant_id=authenticated.context.tenant_id,
            conversation_id=conversation_id,
            content=payload.content,
            actor_user_id=authenticated.context.user_id,
            actor_role=authenticated.context.role,
            now=now_utc(),
        )
    return MessageResponse.from_domain(message)


@router.post(
    "/{conversation_id}/escalate",
    response_model=ConversationResponse,
    summary="Escalate a conversation to a person",
    description=(
        "The manual door. A conversation already escalated answers `409`: unlike the "
        "pipeline, where a guest's message must still be processed, here the caller asked "
        "for something that cannot happen."
    ),
)
async def escalate_conversation(
    conversation_id: uuid.UUID,
    authenticated: ManageDep,
    use_case: Annotated[
        EscalateConversationUseCase, Depends(get_escalate_conversation_use_case)
    ],
) -> ConversationResponse:
    conversation = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        conversation_id=conversation_id,
        actor_user_id=authenticated.context.user_id,
        now=now_utc(),
    )
    return ConversationResponse.from_domain(conversation)


@router.post(
    "/{conversation_id}/resolve",
    response_model=ConversationResponse,
    summary="Resolve a conversation",
    description=(
        "Closes the escalation with it when there is one, because no route resolves that "
        "axis on its own and a conversation resolved with its handover left pending would "
        "sit for ever in whatever list asks for pending handovers."
    ),
)
async def resolve_conversation(
    conversation_id: uuid.UUID,
    authenticated: ManageDep,
    use_case: Annotated[
        ResolveConversationUseCase, Depends(get_resolve_conversation_use_case)
    ],
) -> ConversationResponse:
    conversation = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        conversation_id=conversation_id,
        now=now_utc(),
    )
    return ConversationResponse.from_domain(conversation)


# --- WhatsApp number provisioning (section 6, R6.1-R6.3) ------------------------------------
#
# A second router of this module, under `/messaging` rather than `/conversations`: this is not
# a conversation endpoint, it is tenant configuration, the same distinction that gives
# `integrations` its own `/webhook-endpoints` routes next to `/pms/import-csv`. `MANAGE_TENANT_
# SETTINGS` rather than `MANAGE_CONVERSATIONS`, for the same reason `integrations/api/router.py`
# gives its webhook-endpoint routes that permission and not `MANAGE_RESERVATIONS`: deciding who
# may write into the tenant from the internet — here, which number is treated as this tenant's
# — is a configuration act PRD §6 gives to the `TENANT_OWNER` alone.

whatsapp_provisioning_router = APIRouter(
    prefix="/messaging", tags=["messaging"], responses=AUTHENTICATED_RESPONSES
)

TenantSettingsDep = Annotated[
    AuthenticatedRequest, Depends(require(Permission.MANAGE_TENANT_SETTINGS))
]


@whatsapp_provisioning_router.post(
    "/whatsapp-phone-number",
    response_model=WhatsAppPhoneNumberResponse,
    status_code=201,
    summary="Associate a Meta Cloud API phone_number_id with this tenant",
    description=(
        "Create-or-replace (R6.1, R6.3): a tenant with no number yet gets one, a tenant that "
        "already has one gets it replaced. `phone_number_id` is always supplied by the "
        "operator, never generated here — it is Meta's own identifier for a number already "
        "provisioned in the platform's single Meta App. `default_property_id` must be one of "
        "this tenant's own properties, and it is what an inbound message anchors to when it "
        "cannot be resolved to a specific stay (design D8). Refuses with `409` if that "
        "`phone_number_id` is already associated with a different tenant — it is never "
        "silently reassigned (R6.2)."
    ),
)
async def associate_whatsapp_phone_number(
    payload: AssociateWhatsAppPhoneNumberRequest,
    authenticated: TenantSettingsDep,
    use_case: Annotated[
        AssociateWhatsAppPhoneNumberUseCase,
        Depends(get_associate_whatsapp_phone_number_use_case),
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> WhatsAppPhoneNumberResponse:
    association = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip or None,
        phone_number_id=payload.phone_number_id,
        display_phone_number=payload.display_phone_number,
        default_property_id=payload.default_property_id,
        now=now_utc(),
    )
    return WhatsAppPhoneNumberResponse.from_domain(association)


@whatsapp_provisioning_router.post(
    "/whatsapp-phone-number/release",
    status_code=204,
    summary="Retire this tenant's WhatsApp phone_number_id association",
    description=(
        "The equivalent of a webhook endpoint's rotation in this model (R6.3): after this, "
        "the number resolves to no tenant until somebody — this one or another — associates "
        "it again. Conversations already opened under it are untouched. `404` if this tenant "
        "has no association to release."
    ),
)
async def release_whatsapp_phone_number(
    authenticated: TenantSettingsDep,
    use_case: Annotated[
        ReleaseWhatsAppPhoneNumberUseCase, Depends(get_release_whatsapp_phone_number_use_case)
    ],
    client_ip: Annotated[str, Depends(get_client_ip)],
) -> None:
    await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        actor_ip=client_ip or None,
        now=now_utc(),
    )
