"""The four ports `messaging` owns beyond persistence (R2.1, R4.6, R6.1, `whatsapp-cloud-adapter`
R3.2; design D6, D12, D14, D9).

All four are small and split by consumer, which is what `steering/backend-architecture.md`
asks for: "puertos pequeños y por rol, no un `StorageAdapter` gigante con 15 métodos si un
caso de uso solo necesita `get_signed_url`. Divide por consumidor real."

`WhatsAppInboundProviderAdapter` is the fourth and the newest: `OutboundMessagePort` already
kept the provider out of the sending side, and `whatsapp-cloud-adapter` design D9 records that
"the receiving side needs the same isolation D1 gives the sending side".
"""

import uuid
from collections.abc import Mapping
from datetime import datetime
from typing import Protocol

from app.messaging.domain.enums import ConversationChannel, MessageIntent
from app.messaging.domain.value_objects import (
    ChannelSendResult,
    ConversationContext,
    GeneratedResponse,
    InboundMessageActor,
    InboundWhatsAppMessage,
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
        tenant_id: uuid.UUID,
        last_inbound_at: datetime | None = None,
        template_id: str | None = None,
        phone_number_id: str | None = None,
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

        `tenant_id`, `last_inbound_at` and `template_id` are `whatsapp-cloud-adapter` R2.4,
        design D2 — widened onto every implementer of this port the same way `channel` and
        `language` already are, so `PanelOutboundAdapter`, `PortalOutboundAdapter` and
        `InboundOnlyAdapter` accept and ignore all three, and only `DelegatingOutboundAdapter`
        does anything with them. `tenant_id` has **no default**, unlike the other two: it is
        not optional information about the send, it is the scope `DelegatingOutboundAdapter`
        needs to resolve `last_inbound_at` itself via `MessageRepository.last_guest_message_at`
        for the `WHATSAPP` channel — a query this port cannot answer without knowing which
        tenant's conversation it is.

        `phone_number_id` is `whatsapp-cloud-adapter` task 2.6, design D1 — the same widening
        pattern, and again ignored by every implementer except `DelegatingOutboundAdapter`.
        Unlike `last_inbound_at`, this port cannot resolve it itself: it is
        `Conversation.business_phone_number` (design D4), and this port only ever sees
        `conversation_id`, never the entity. The caller — the use case that already has the
        `Conversation` in scope — supplies it, the same division of labour `tenant_id` uses.
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


class WhatsAppInboundProviderAdapter(Protocol):
    """The provider-shaped half of *receiving* a WhatsApp message (R3.2, R4.1; design D9).

    `OutboundMessagePort` above already keeps Meta's Graph API out of `application/` on the
    sending side. This is the mirror for the receiving side, and design D9 states the reason
    in those terms: Meta's inbound webhook is a nested JSON body — `entry[].changes[].value.
    messages[]`, `X-Hub-Signature-256` over the raw bytes — and "none of that may leak into
    `messaging/application/` or `messaging/domain/`". So the shape of the payload, the name of
    the signature header and the algorithm behind it all live behind these two methods; the
    receiving use case sees only a `bool` and an `InboundWhatsAppMessage`.

    **Exactly two methods, and the split between them is the design rather than tidiness.**
    Authentication must be answerable *without* interpreting the body — the same property
    `ReceiveWebhookUseCase.authenticate` is split out for in `integrations` — because the raw
    bytes are what the signature covers: parsing first and re-serialising would change them,
    and a body that fails authentication must be rejected before anything trusts its contents.
    `verify_signature` therefore takes `raw_body: bytes` and never a parsed `dict`.

    **Both are synchronous.** Neither does I/O: one is an HMAC over bytes already in memory,
    the other a `json.loads`. Declaring them `async` would buy nothing and would force every
    future implementer into a coroutine it has no await inside.

    **Neither method raises to signal "not authentic".** `verify_signature` answers `False`
    for every unauthenticated shape — no header, a malformed header, a header signed with
    another key — which is what makes design D4's indistinguishable answer expressible by the
    caller. `parse` is the one that may raise, and only with `NoInboundMessageError` (see
    `domain/exceptions.py`): Meta posts delivery/read receipts to the very same URL, and a
    body carrying `statuses` instead of `messages` is a routine, foreseen outcome rather than
    a bug — see that error's docstring for what the caller owes it.

    `MetaInboundAdapter` (`messaging/infrastructure/whatsapp_providers.py`) is the only
    implementer this change ships. D9 records what a second one costs: "a `TwilioInboundAdapter`
    … is the entire cost of a future Twilio addition, not built in this change."
    """

    def verify_signature(
        self, *, raw_body: bytes, headers: Mapping[str, str], secret: str, url: str
    ) -> bool:
        """Whether this request really came from the provider, decided in constant time (R3.2).

        `raw_body` is the **exact bytes** that arrived. Not a `dict`, not a re-serialised
        string: the signature covers the byte sequence, and `json.dumps(json.loads(body))`
        is not it — key order, whitespace and unicode escaping all differ, so a re-serialised
        body would fail a signature that is perfectly valid.

        `secret` is passed in already usable — decrypted if it was stored encrypted — rather
        than read from `settings` inside the adapter. That is what keeps the port implementable
        by a per-tenant credential later without changing this signature, and it keeps the one
        place that decrypts a stored secret in the layer entitled to (`app/core/crypto.py`'s
        call sites, obligation 4 of ADR 0006).

        `url` and the rest of `headers` are here for **provider generality, not for Meta**:
        Twilio's `X-Twilio-Signature` is computed over the full callback URL plus the sorted
        POST parameters, so a port that omitted the URL could never host that adapter without
        being rewritten. `MetaInboundAdapter` reads neither — `X-Hub-Signature-256` is an HMAC
        over `raw_body` alone — and ignores them by contract, not by accident.

        **Returns `False` rather than raising, for every failure.** A missing header, a header
        that is not `sha256=<hex>`, a digest of the wrong length, a signature from another
        key: all of them are "no". Rule 12(a) of `steering/security.md` makes a missing
        credential exactly as unauthenticated as a wrong one, and an exception on one of those
        paths and a `False` on the others is precisely how a caller ends up answering two
        distinguishable statuses and handing an anonymous prober an oracle (design D4).

        Constant time is not a preference: rule 12(a) requires `hmac.compare_digest` in those
        words, and a short-circuiting `==` leaks the length of the matching prefix byte by byte.
        """
        ...

    def parse(
        self, *, raw_body: bytes, headers: Mapping[str, str]
    ) -> InboundWhatsAppMessage:
        """The one inbound message this body carries, or `NoInboundMessageError` (R3.5, R4.1).

        **Only ever called on a body that already passed `verify_signature`.** Nothing here
        authenticates anything, and the returned value is provider-supplied data in every
        field — which is why `InboundWhatsAppMessage.business_phone_number` is informational
        only and R4.1 forbids resolving the tenant from it directly: `business_phone_number`
        is looked up against the `phone_number_id`-to-tenant provisioning table (R6, design D3,
        superseded 2026-09-02 — there is no per-tenant route token, Meta allows one fixed
        webhook route per App), never trusted as a tenant identifier on its own, and never any
        other field the sender controls ("no SHALL … desde ningún dato que el cuerpo del
        webhook aporte").

        `headers` is accepted because a provider may carry part of the message's shape there
        (a content type, a webhook version). Meta does not, and `MetaInboundAdapter` ignores it.

        Raises `NoInboundMessageError` when the body is well-formed but carries no inbound
        message — the `statuses` webhook Meta posts to this same URL for a delivery or read
        receipt, an empty `entry`/`changes`/`messages`, or a message with no text body — and
        for a body that is not the JSON object shape at all. It never raises a bare `KeyError`
        or `IndexError`: the caller has to distinguish "nothing to do, acknowledge it" from
        "a bug of ours", and it cannot do that against whichever built-in the traversal
        happened to hit first.
        """
        ...
