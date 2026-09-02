"""The three ports `messaging` owns beyond persistence (R2.1, R4.6, R6.1; design D6, D12, D14).

All three are small and split by consumer, which is what `steering/backend-architecture.md`
asks for: "puertos pequeños y por rol, no un `StorageAdapter` gigante con 15 métodos si un
caso de uso solo necesita `get_signed_url`. Divide por consumidor real."
"""

import uuid
from datetime import datetime
from typing import Protocol

from app.messaging.domain.enums import ConversationChannel, MessageIntent
from app.messaging.domain.value_objects import (
    ChannelSendResult,
    ConversationContext,
    GeneratedResponse,
    InboundMessageActor,
    MessageClassification,
)


class AIAdapter(Protocol):
    """What a guest's message is about, and what to say back. **Two methods, and no more.**

    R2.1 lists what this port deliberately does not declare, and each has a different reason:

    * `classify_incident` belongs to `maintenance`, which owns `IncidentClassifier` — and
      `sdd/specs/maintenance.md` R2 forbids the crossing **in the opposite direction**, so
      declaring it here would be the same mistake facing the other way.
    * `validate_cleaning_photo` would belong to `cleaning`, which has no such use case yet.
    * `summarize_incident` and `draft_review_response` have no consumer at all (`revenue`
      brings reviews).

    Declaring all six of PRD §13 and leaving four raising `NotImplementedError` was rejected
    in D6: it breaks Liskov exactly as ADR 0006 decision 3 reasoned for `PMSMessagingPort`,
    and `steering/backend-architecture.md` names that case by name.

    `EXTERNAL_DEPENDENCY` (R2.8): the real adapter against a model provider is out of scope.
    `MockAIAdapter` is the only implementer this change ships. A real one implements this same
    port and goes to `app/integrations/`, and the contracts below hold for it because they
    live in the **return types** rather than in this prose.
    """

    async def classify_message(
        self, *, content: str, language: str, context: ConversationContext
    ) -> MessageClassification:
        """Read the guest's message and say what it is about (R2.1).

        `content` is the one free-form string an adapter receives, and it needs it by
        definition. `context` is everything else it gets, and it is a closed value object of
        identifiers and enums — never the message history, never a name — because this object
        goes to something that tomorrow is an external provider with its own logging (D6).

        The returned `confidence` is a `0..1` fraction compared against
        `TenantConfig.ai_confidence_threshold` (R4.2); `MessageClassification` refuses
        anything outside that range, and refuses an `intent` that is not a member of
        `MessageIntent`.

        **The adapter does not decide whether to escalate.** PRD §13 suggests a
        `requires_escalation` flag and D10 rejected it: that would put the policy inside what
        is tomorrow a third party. The policy is `app/messaging/domain/escalation.py`.
        """
        ...

    async def generate_response(
        self, *, intent: MessageIntent, language: str, context: ConversationContext
    ) -> GeneratedResponse:
        """The reply to send, drawn from a closed catalogue (R2.6, R3.3).

        **The adapter must declare, in the value it returns, the closed vocabulary its
        `content` came from** — `GeneratedResponse.vocabulary`, which refuses a `content`
        outside it. That is the *admission condition* rule 11 of `sdd/steering/security.md`
        states for this class of column, and it is checked by the type rather than asked for
        here, because prose on a port does not survive a second implementation.

        It is deliberately not called a guarantee: the same rule records that "un adaptador
        que construya su `vocabulary` **a partir de su propia salida** satisface la
        comprobación trivialmente… es **segunda red y no la garantía**". What closes it is
        that the pipeline **must** compare the value it is about to persist against
        `templates.RESPONSE_VOCABULARY` — the catalogue — and not against whatever this port's
        implementer declared. That is an obligation on the caller; nothing in this port can
        enforce it.

        **Never called for `REFUND_OR_COMPENSATION`, `EMERGENCY` or `UNKNOWN`** (R2.7): those
        escalate instead. The catalogue of `templates.py` has no entry for them either, so a
        caller that steps over the pipeline's branch gets a loud `KeyError` rather than a
        sentence the guest should never have received.

        `language` is the detected language of the message, or the conversation's when
        detection could not decide (R4.8) — resolved by the caller, so this port never has to
        know about the fallback.
        """
        ...


class OutboundMessagePort(Protocol):
    """Getting a reply to the guest, over whichever channel the conversation uses (R6.1).

    The use cases depend on this and never on a concrete adapter, so the day a real channel
    arrives there is one thing to implement and nothing to rewire.
    """

    async def send(
        self,
        *,
        channel: ConversationChannel,
        conversation_id: uuid.UUID,
        recipient_contact: str | None,
        content: str,
        language: str,
    ) -> ChannelSendResult:
        """Attempt delivery. **Returns the outcome; never raises for a delivery failure.**

        The pattern of `NotificationAdapter.send` and its `NotificationResult`, and the reason
        is R6.5: an exception would abort the transaction of R4.7 and take the guest's own
        message down with it, which is precisely the "perder el mensaje en silencio" that
        rule forbids. A value lets the pipeline record the failure in structured form, escalate
        the conversation with `DELIVERY_FAILED`, and still commit.

        `ChannelSendResult` has no string field, so whatever a provider says about the failure
        stays with the adapter and cannot reach `messages.metadata` (D14).

        **`AIRBNB_MSG` and `BOOKING_MSG` are not implementable here** (R6.3): those channels
        exist only through `PMSMessagingPort`, which is still the method-less port
        `pms-provider-resolution` fixed. The registry of `infrastructure/channels.py` has no
        entry for them and the use case raises `PMSChannelUnavailableError` — there is no key
        with which to fall back to a console adapter in silence.
        """
        ...


class IncidentReportingPort(Protocol):
    """Opening a maintenance incident from a conversation, without importing `maintenance` (R4.6).

    The port lives here and `maintenance` supplies the implementer
    (`ReportIncidentFromConversationUseCase`), which is the direction the dependency rule
    wants: `application/` depends on a port of its **own** `domain/`, never on another
    module's use cases. It is the shape `LiveCleaningTaskQuery` uses between `maintenance` and
    `cleaning`. The wiring happens in `messaging/api/dependencies.py`, the one layer entitled
    to know both modules (D12).
    """

    async def report(
        self,
        *,
        tenant_id: uuid.UUID,
        property_id: uuid.UUID,
        reservation_id: uuid.UUID | None,
        title: str,
        description: str,
        actor: InboundMessageActor,
        now: datetime,
    ) -> uuid.UUID:
        """Open the incident and return its id. **Never commits** — the implementer is given a
        `CallerOwnedUnitOfWork` so the single commit stays the pipeline's (D12, R4.7).

        **The incident is not classified here** (R4.6). It is born `OPEN` with
        `ai_classification` unset, which is exactly what the `classify_incidents` job of
        `maintenance` D2 picks up on its next tick. Not one line of `IncidentClassifier` runs
        in this change.

        `actor` is **either** a human or the bearer of a portal link, never both and never
        neither — `InboundMessageActor` refuses the other two shapes (`guest-portal-messaging`
        R4.1, D8). Until that change this parameter was a required `actor_user_id: uuid.UUID`,
        and the prose here said a human is always at the keyboard because the only door into
        this pipeline was `POST /conversations/{id}/messages` with `MANAGE_CONVERSATIONS`.
        `POST /api/v1/guest/messages/{token}` is the second door and there is no user behind
        it.

        **This still needs no new exception to rule 9** of `steering/security.md`, and the
        reason is not that the actor is a person. It is that **no exemption is being taken**:
        rule 9's base obligation names `Incident`, this path writes that `AuditLog` row, and
        the rule nowhere requires the actor be a `User`. The token bearer is named by its
        digest in `actor_guest_token_hash` — the actor `guest-portal-api` established for the
        anonymous surface — and `AuditLogFactory` refuses a row claiming both and a digest
        that is not SHA-256.

        Deliberately **not** argued as "rule 9's exceptions are about writes with no actor, so
        having one puts us outside them". That reading is false about the rule — only its
        fourth and fifth exceptions rest on an absent actor; the first is about a bespoke sink
        for a `SYSTEM` transition, and the second and third are both cadence arguments (the
        third scoped to an anonymous route, whose cadence the rule calls "peor que la de la
        segunda") — and it is a general-sounding criterion of exactly the shape rule 9's
        closing paragraph refuses ("este razonamiento **no es un criterio reutilizable**"). Raised by
        the security panel of section 2, which found that argument here.

        `title` comes from a closed catalogue of constants; `description` is the guest's
        message **verbatim**, with nothing added, removed or paraphrased (D13).

        Which rule-11 contract that lands under is decided in the census (task 8.1), not
        here, and the criterion is quoted whole rather than half: excepción 2 admits "la
        prosa que escribió quien reporta… **porque el valor no es nuestro y no lo hemos ido a
        buscar**", and says of itself that it "**No autoriza a un escritor nuestro**". Both
        halves matter, and the second is the one this path strains — the pipeline does go and
        fetch `messages.content` in order to write it here. What keeps it inside the exception
        is that the value that lands is bit-for-bit the one the guest typed: no template, no
        interpolation, no summary, and no value of rule 3 rendered into it. A future caller
        that wants to write a *derived* description is not covered by any of this and falls
        under the structured form by default.
        """
        ...
