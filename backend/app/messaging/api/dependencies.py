"""Wiring for the conversation endpoints: one builder per use case (design D12, D17).

Same shape as `app/maintenance/api/dependencies.py`. The repositories take the session from
`get_db_session` — the one `get_authenticated_request` has already marked with the tenant, so
the listener of `app/core/db.py` scopes ORM reads as well. That is the net; the explicit
`tenant_id` every repository method takes is the mechanism. For `messages` there is no net at
all (R1.2), which is why its adapter joins.

**This is the layer entitled to know two domains** (D12), and it is where the incident port of
`messaging` meets its implementer in `maintenance` — with a `CallerOwnedUnitOfWork`, so the
single commit of R4.7 stays the pipeline's.
"""

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.core.config import settings
from app.core.db import get_db_session
from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.maintenance.application.use_cases import ReportIncidentFromConversationUseCase
from app.maintenance.infrastructure.repositories import SqlAlchemyIncidentRepository
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
from app.messaging.application.webhooks import ReceiveWhatsAppWebhookUseCase
from app.messaging.application.whatsapp_provisioning import (
    AssociateWhatsAppPhoneNumberUseCase,
    ReleaseWhatsAppPhoneNumberUseCase,
)
from app.messaging.domain.ports import WhatsAppInboundProviderAdapter
from app.messaging.infrastructure.ai import MockAIAdapter
from app.messaging.infrastructure.channels import outbound_registry
from app.messaging.infrastructure.whatsapp_providers import MetaInboundAdapter
from app.messaging.infrastructure.repositories import (
    SqlAlchemyConversationRepository,
    SqlAlchemyMessageRepository,
    SqlAlchemyWhatsAppInboundEventRepository,
    SqlAlchemyWhatsAppPhoneNumberRepository,
)
from app.notifications.infrastructure.repositories import (
    SqlAlchemyNotificationLogRepository,
)
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def incident_reporting_port(session: AsyncSession) -> ReportIncidentFromConversationUseCase:
    """`maintenance`'s implementer of `IncidentReportingPort`, with a **caller-owned** boundary.

    This is the whole of D12's transactional half, and it is one argument: handing it
    `SqlAlchemyUnitOfWork` would let the incident, its audit row and its timeline event land
    before the pipeline finished — so a failure afterwards would leave an incident nobody can
    trace back to a message, which is exactly the split `guest-portal-api` created before
    `CallerOwnedUnitOfWork` existed.
    """
    return ReportIncidentFromConversationUseCase(
        incidents=SqlAlchemyIncidentRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=CallerOwnedUnitOfWork(),
    )


def get_process_inbound_message_use_case(
    session: SessionDep,
) -> ProcessInboundGuestMessageUseCase:
    messages = SqlAlchemyMessageRepository(session)
    return ProcessInboundGuestMessageUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        messages=messages,
        # `MockAIAdapter` is the only implementer this change ships (R2.8,
        # `EXTERNAL_DEPENDENCY`). A real provider implements the same port and is swapped in
        # here — the one line that changes.
        ai=MockAIAdapter(),
        # `outbound_registry` needs the same `MessageRepository` instance to resolve
        # `WHATSAPP`'s session window (`whatsapp-cloud-adapter` R2.4, D2) — not a second one.
        channels=outbound_registry(messages),
        incidents=incident_reporting_port(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        users=SqlAlchemyUserRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_record_human_reply_use_case(session: SessionDep) -> RecordHumanReplyUseCase:
    return RecordHumanReplyUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        messages=SqlAlchemyMessageRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_create_conversation_use_case(session: SessionDep) -> CreateConversationUseCase:
    """The property, reservation and guest repositories are not decoration here.

    This is the only route that takes `property_id`/`reservation_id`/`guest_id` **from a
    client**, and the foreign keys of `conversations` are global rather than composite with
    `tenant_id` — so without resolving them within the tenant first, a conversation of tenant A
    can be anchored to a property, a reservation or a guest of tenant B for ever.

    All three go in together because the omission of any one of them is the whole bug: the
    first implementation wired the first two and left `guest_id` unchecked, which the review
    of 2026-08-16 found.
    """
    return CreateConversationUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_list_conversations_use_case(session: SessionDep) -> ListConversationsUseCase:
    return ListConversationsUseCase(
        conversations=SqlAlchemyConversationRepository(session)
    )


def get_conversation_use_case(session: SessionDep) -> GetConversationUseCase:
    return GetConversationUseCase(conversations=SqlAlchemyConversationRepository(session))


def get_list_messages_use_case(session: SessionDep) -> ListMessagesUseCase:
    return ListMessagesUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        messages=SqlAlchemyMessageRepository(session),
    )


def get_escalate_conversation_use_case(
    session: SessionDep,
) -> EscalateConversationUseCase:
    return EscalateConversationUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_resolve_conversation_use_case(
    session: SessionDep,
) -> ResolveConversationUseCase:
    return ResolveConversationUseCase(
        conversations=SqlAlchemyConversationRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_associate_whatsapp_phone_number_use_case(
    session: SessionDep,
) -> AssociateWhatsAppPhoneNumberUseCase:
    return AssociateWhatsAppPhoneNumberUseCase(
        phone_numbers=SqlAlchemyWhatsAppPhoneNumberRepository(session),
        properties=SqlAlchemyPropertyRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_release_whatsapp_phone_number_use_case(
    session: SessionDep,
) -> ReleaseWhatsAppPhoneNumberUseCase:
    return ReleaseWhatsAppPhoneNumberUseCase(
        phone_numbers=SqlAlchemyWhatsAppPhoneNumberRepository(session),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


# --- `whatsapp-cloud-adapter` section 7: the anonymous inbound receiver (D3a, D9) ---------
#
# The composition root for the receiving half, mirroring what `get_receive_webhook_use_case`
# is for the PMS receiver. Two things are chosen here and nowhere else: which provider adapter
# interprets the request, and which secret its signature is verified against.

#: The one value of `settings.whatsapp_provider` that has an inbound door at all.
#:
#: Spelled here rather than imported because `adapter_registry()` and `outbound_registry()`
#: both write the same literal inline (sections 1 and 2); a fourth spelling that pretended to
#: be a shared constant while the other three stayed literals would be worse than a fourth
#: literal. `Settings` already rejects anything outside `{"mock", "meta"}` at boot.
WHATSAPP_META_PROVIDER = "meta"


def get_whatsapp_inbound_provider() -> WhatsAppInboundProviderAdapter:
    """The provider adapter that authenticates and interprets an inbound WhatsApp webhook.

    `MetaInboundAdapter` is the only implementer of the port this change ships (section 4,
    design D9) and it is stateless — no credentials, no session, nothing to cache — so it is
    built per request the same way `get_webhook_throttle` builds its throttle per request.

    **`settings.whatsapp_provider` does not select a *class* here, and that is deliberate.**
    There is no second inbound provider to select, and no "mock inbound adapter" either: a
    mock provider has nothing to receive *from*, so what `mock` mode needs is not a different
    parser but a **closed door**. That is what `whatsapp_signing_secret()` below expresses,
    using a mechanism section 4 already built and tested rather than a class that exists only
    to refuse — see its docstring.
    """
    return MetaInboundAdapter()


def whatsapp_signing_secret() -> str:
    """The HMAC key `MetaInboundAdapter.verify_signature` checks Meta's signature against.

    **This is where `settings.whatsapp_provider` selects** (task 7.1). Under any provider but
    `meta` the platform has no WhatsApp of its own to receive on, so this returns `""` — and
    section 4's adapter answers `False` for a blank or whitespace-only secret, by contract and
    with its own test ("an HMAC under an empty key is one anybody can compute"). The receiving
    route therefore refuses every delivery, uniformly and without writing anything, which is
    exactly R3.3's posture applied to a deployment that never configured WhatsApp.

    The same `""` is returned when `WHATSAPP_APP_SECRET` is unset under `meta`, so a
    half-configured deployment fails closed instead of authenticating the open internet.
    `Settings` also refuses to boot in that state (`_require_app_secret_for_meta`); this is
    the second net, not the plan.

    Read from `settings` per call rather than closed over at import time, for the reason
    `get_webhook_throttle` records: an operator changing configuration does not have to
    rebuild the application, and a test can move it without reimporting.
    """
    if settings.whatsapp_provider != WHATSAPP_META_PROVIDER:
        return ""
    return (settings.whatsapp_app_secret or "").strip()


def get_whatsapp_inbound_dispatcher() -> Callable[[uuid.UUID], None]:
    """The callable `ReceiveWhatsAppWebhookUseCase` hands a committed event id to (design D7).

    **A dependency of its own, not a line inside the use-case builder**, for two reasons that
    both matter:

    * it is the composition root for the one thing `application/` may not import. Celery
      belongs to `app/worker.py` and `app/scheduler/**` and nowhere else
      (`tests/test_layering.py`), so the task arrives here as a function — the same move that
      hands `scrub_card_data` to the PMS receiver;
    * it is overridable in a test the ordinary FastAPI way, so the receiving route can be
      exercised over HTTP without a broker, and the "dispatched only after the commit"
      assertion can watch a spy instead of Redis.

    **The import is inside the function on purpose.** `app.scheduler.whatsapp_tasks` reaches
    `app.worker`, which builds the Celery application and imports `app.scheduler.tasks` for
    its side effect — the whole job graph. Importing that at module scope would drag it into
    every process that touches `messaging`'s wiring, tests included, and would put
    `app.messaging.api` and `app.worker` in an import cycle the moment a job wants a
    messaging use case. Deferred to the one call that needs it, it costs a dictionary lookup.

    `str(event_id)` and not the `UUID`: Celery serialises task arguments as JSON, which has no
    UUID, and the task parses it back. A `UUID` here fails at dispatch time in a worker log
    rather than here.
    """

    def _dispatch(event_id: uuid.UUID) -> None:
        from app.scheduler.whatsapp_tasks import process_inbound_whatsapp_message

        process_inbound_whatsapp_message.delay(str(event_id))

    return _dispatch


DispatchDep = Annotated[Callable[[uuid.UUID], None], Depends(get_whatsapp_inbound_dispatcher)]
ProviderDep = Annotated[
    WhatsAppInboundProviderAdapter, Depends(get_whatsapp_inbound_provider)
]
SigningSecretDep = Annotated[str, Depends(whatsapp_signing_secret)]


def get_receive_whatsapp_webhook_use_case(
    session: SessionDep,
    provider: ProviderDep,
    secret: SigningSecretDep,
    dispatch: DispatchDep,
) -> ReceiveWhatsAppWebhookUseCase:
    """The anonymous receiver, wired to the request's own **unmarked** session.

    Nothing marks it, and that is load-bearing rather than incidental: the route declares no
    authorisation dependency, so `get_authenticated_request` never runs and
    `bind_session_to_tenant` is never called. `find_by_phone_number_id` requires exactly that
    (`require_unmarked_session`), because `phone_number_id` is what resolves the tenant, and
    `whatsapp_inbound_events` needs it too — its `tenant_id` is nullable, and a marked session
    would hide the rows whose tenant is `NULL`.
    """
    return ReceiveWhatsAppWebhookUseCase(
        provider=provider,
        secret=secret,
        phone_numbers=SqlAlchemyWhatsAppPhoneNumberRepository(session),
        events=SqlAlchemyWhatsAppInboundEventRepository(session),
        dispatch=dispatch,
        uow=SqlAlchemyUnitOfWork(session),
    )
