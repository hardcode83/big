# Design: whatsapp-cloud-adapter

## Context

**Outbound today**: `MockWhatsAppAdapter` (`backend/app/notifications/infrastructure/adapters.py`)
implements `NotificationAdapter` and is the sole registrant for `NotificationChannel.WHATSAPP` in
`adapter_registry()`. `messaging/infrastructure/channels.py`'s `DelegatingOutboundAdapter` wraps
the *same instance type* for `ConversationChannel.WHATSAPP`, translating `NotificationResult` into
`ChannelSendResult` via `_translate`. Both call sites only ever see `recipient_contact`,
`subject`/`content`, and the channel enum — no timestamp, no conversation.

**Inbound today**: nothing. The only precedent for "an anonymous external caller creates a
`Conversation` and feeds `ProcessInboundGuestMessageUseCase`" is the guest portal:
`PostPortalGuestMessageUseCase` (`backend/app/messaging/application/portal.py`) calls
`ConversationRepository.ensure_portal(...)` — an `INSERT ... ON CONFLICT DO NOTHING` keyed on
`(tenant_id, reservation_id)` for `channel = PORTAL` — then hands the content to the pipeline.
`ProcessInboundGuestMessageUseCase.execute()` itself takes an existing `conversation_id`; it never
creates one. `InboundMessageActor` (`messaging/domain/value_objects.py`) currently accepts exactly
one of `user_id` (a manager) or `token_hash` (the portal link's digest) — nothing that fits "a
phone number we haven't authenticated with a token".

**Webhook precedent**: `reservations-webhooks` built the only anonymous-ingress pattern the repo
has — `POST /api/v1/webhooks/{provider}/{webhook_token}` (`app/integrations/api/webhooks_router.py`),
backed by `WebhookEndpointModel` (one row per tenant+provider, `token_hash` + Fernet-encrypted
`header_secret`) and `ReceiveWebhookUseCase` (`app/integrations/application/webhooks.py`). Two
things about it don't transfer directly:

1. `WebhookEndpointModel.provider` is typed `Mapped[PMSProvider]` against the **native Postgres
   enum** `pms_provider` (`MOCK`/`CHANNEX`/`BEDS24`), and `ReceiveWebhookUseCase._resolve` parses
   the route's `{provider}` segment with `PMSProvider(provider.strip().upper())`. WhatsApp is not
   a PMS.
2. The whole design is built around "the body is a notice, never trust it, re-read via API" —
   `ReceiveWebhookUseCase` docstring: "Deliberately does no outbound call and no re-read: rule
   12(d) requires the API traffic to be decoupled from the request volume, so this path only
   writes a row. The re-read is the job's, coalesced across the batch." A WhatsApp/Twilio webhook
   body **is** the message — there is nothing to re-read, and batching it every 60 s (the
   `process_webhook_events` cadence, chosen specifically to cap PMS API calls per
   `sdd/steering/security.md` rule 12(d)) would add up to a minute of latency to what is supposed
   to read as a live chat.

The primitives underneath (`app/integrations/domain/webhook_auth.py`:
`generate_webhook_token`/`generate_header_secret`/`hash_webhook_token`/`secrets_match`) are pure
stdlib (`hmac`, `hashlib`, `secrets`) with no PMS in them, and `tests/test_layering.py` only
forbids a `domain/` module from importing an **outer layer** of any domain — a `domain/` → other
domain's `domain/` import is not restricted. They are reusable by import, not by copy.

## Decisions

### D1 — Outbound adapter stays in `notifications/infrastructure/`, real client behind the same port

**Chosen:** replace `MockWhatsAppAdapter` in place with a real adapter (`WhatsAppCloudAdapter`,
same module) implementing `NotificationAdapter` with the identical signature. `adapter_registry()`
and `outbound_registry()` keep pointing at one shared instance, unchanged. Provider selection
(`WHATSAPP_PROVIDER=mock|meta`) is read inside `adapter_registry()` itself
(`app/notifications/infrastructure/adapters.py`), which is what keeps `adapter_registry()`
argument-free for its existing callers (`scheduler/tasks.py`, `auth/api/dependencies.py`) —
there is no `EMAIL_PROVIDER` setting to mirror; `ConsoleEmailAdapter` has no provider gate at
all today, which is exactly why this switch is a new pattern here, not a precedent being
followed. `mock` keeps constructing today's class so nothing changes for a deployment with no
credentials.

**Superseded 2026-09-02, before any implementation landed (git tree was clean when the switch was
requested — this is a design amendment, not a rollback of shipped code).** Original text chose
Twilio first with Meta as a later swap; **the user redirected to Meta Cloud API as the sole
provider of this change**, because Meta's *customer service window* — free-form messaging is free
of charge for 24h from the customer's last message, and a business-initiated message outside it
must be a paid, pre-approved template — is exactly the mechanism R2/D2 already models, whereas
Twilio's WhatsApp Sandbox is a shared number across all sandbox accounts during development (see
Risks, below) and adds no equivalent free-window benefit of its own. Meta's Cloud API also
provides, in development, a **test phone number with up to 5 unverified recipient numbers** with
no WhatsApp Business Account (WABA) review required — the same "provable end-to-end before
production approval" property the Sandbox was chosen for, without the shared-number caveat.

**Confirmed with the user**: implement against **Meta Cloud API** only, and everything
Meta-specific — its API shape (Graph API, Bearer token, JSON body), its webhook verification
handshake, its payload format — stays entirely inside the adapter/infrastructure surface, so a
later addition of Twilio (or another provider) touches only `notifications/infrastructure/` and
`messaging/infrastructure/` (D9), never `domain/` or `application/`. `WhatsAppCloudAdapter` is the
concrete Meta Graph API client now; its class name and the port it implements are already
provider-neutral (`NotificationAdapter`), so nothing about the public contract needs to change on
a future Twilio addition — only a new class plus a `WHATSAPP_PROVIDER=twilio` branch.

Rejected: a new adapter class under `app/integrations/` — WhatsApp is a notification/messaging
channel in this codebase's own taxonomy (`notifications/infrastructure/adapters.py` already hosts
`ConsoleEmailAdapter`), not a PMS integration; moving it would fight the existing organisation for
no benefit and would separate it from `adapter_registry()`, the one place provider selection for
this taxonomy now lives.

**Addendum, 2026-09-02, following from the D3/D3a supersession (one shared Meta App, one phone
number per tenant): the "from" number can no longer be a single global constant either.** Once
a guest can be messaging any of several tenant-owned numbers, a reply has to leave from the
*same* number the guest wrote to — Meta will not deliver a business-initiated-looking reply sent
from a `phone_number_id` the guest's session window wasn't opened with. `NotificationAdapter.send`
and `OutboundMessagePort.send` each gain one more optional kwarg, `phone_number_id: str | None =
None` (same shape and same reasoning as `last_inbound_at`/`template_id`): `WhatsAppCloudAdapter`
uses it when given, and falls back to the constructor's default (`settings.whatsapp_phone_number_id`,
section 1's global value, untouched) when `None`. The messaging-side call site passes
`conversation.business_phone_number` (D4, new field, populated from the inbound message that
created the conversation); the notifications-side call site (proactive staff notifications, no
guest conversation behind them) passes nothing and gets the platform default — staff messages
don't carry the same per-guest-session constraint a guest reply does. This is a small, optional
widening of an already-widened signature, not a rework of section 1's adapter: the constructor,
the class, and every existing call site that doesn't pass the new kwarg keep working exactly as
built.

Rejected (superseded): Twilio WhatsApp Sandbox as the first provider. Reasonable on its own terms
— zero WABA review to start testing — but Meta gets the same "test without business verification"
property via its own test-number allowance, and additionally gives the free customer-initiated
window R2 needs natively, rather than as a Twilio-Sandbox-independent design concern. Twilio
remains a valid future addition behind the same port (D9); nothing in this change forecloses it.

### D2 — 24-hour window check lives in the adapter, not the call sites

**Chosen:** `WhatsAppCloudAdapter.send()` decides the window itself, by taking one more optional
keyword the port already has room for: `NotificationAdapter.send` and `OutboundMessagePort.send`
both accept `**`-free explicit keyword args today, so this widens both signatures with
`last_inbound_at: datetime | None = None` (default `None`, so every other adapter is unaffected).
**Resolved 2026-09-02, before section 2 was implemented (confirmed with the user)**:
`DelegatingOutboundAdapter` (channels.py) does **not** read `Conversation.last_message_at` —
that field records any message (guest, AI reply, or manager reply alike), and Meta's real
customer-service window is strictly "since the customer's last message". Using
`last_message_at` as-is would let a manager's manual reply or the AI's own previous reply
silently reopen the free-text window without the guest having said anything, which is a real
delivery-policy violation risk, not just an internal accounting nicety. Instead,
`MessageRepository` (`messaging/domain/repositories.py`) gains a fifth method,
`last_guest_message_at(tenant_id, conversation_id) -> datetime | None`, returning the
`created_at` of the most recent `Message` with `sender_type == MessageSenderType.GUEST` in that
conversation (mirrors the existing `sender_type == MessageSenderType.GUEST` filter precedent in
`SqlAlchemyMessageRepository`, e.g. `count_unresolved_guest_messages_with_intent`).
`DelegatingOutboundAdapter` takes a `MessageRepository` as a new constructor dependency and
calls this method to resolve `last_inbound_at` for the `WHATSAPP` channel only — `MANUAL`/
`PORTAL`/`PHONE_TRANSCRIPT`/`EMAIL` sends don't need it, since only WhatsApp has a provider-side
session window. `outbound_registry()` gains the dependency it needs to pass through.

`dispatch_and_persist` (notifications) always passes `None`, because a `NotificationLog` row has
no guest conversation to read a timestamp from, so every notifications-side WhatsApp send is
treated as outside the window by construction. That is correct: today nothing tracks a
staff/system WhatsApp thread's last inbound message.

Rejected: keep reading `Conversation.last_message_at` and document the gap as a known
limitation. Rejected because the failure mode is not cosmetic — it can make the adapter send a
free-text message Meta's API may reject (or silently not deliver, if Meta enforces the window
server-side) whenever a manager or the AI has spoken more recently than the guest, which is
exactly backwards from what R2 exists to prevent (reporting a message as sent when the provider
would in fact block it).

Inside the window (or `last_inbound_at is None` and free text is explicitly requested — see D2's
call convention below), the adapter sends free text. Outside it, the caller must instead pass a
`template_id` (a new optional kwarg); with neither a fresh-enough `last_inbound_at` nor a
`template_id`, the adapter returns `NotificationResult.failure` /
`ChannelSendResult.failure` with a new closed-enum value (`OUTSIDE_SESSION_WINDOW` /
equivalent `ChannelErrorCode`) rather than attempting a free-text send the provider would silently
drop.

Rejected: checking the window in `application/` (`ProcessInboundGuestMessageUseCase._reply`, and
wherever proactive `notifications` dispatch calls `send`). It would have to be duplicated at every
call site and re-derive "is this a WhatsApp send" each time; the adapter already refuses a blank
recipient the same way (R1 of `access-notifications` design D8), so a second precondition of the
same shape belongs next to the first.

### D3 — Inbound routing is a phone-number-to-tenant mapping, not a per-tenant webhook endpoint

**Superseded 2026-09-02, after section 4 was implemented and reviewed but before sections 5-8
were built** — the architecture reviewer of section 4's panel caught a real contradiction the
original D3/D3a/D8 text carried: it modeled WhatsApp's inbound webhook on
`reservations-webhooks`' `WebhookEndpointModel` — one row per tenant, each with its own route
token and its own signing secret — but **Meta does not support a webhook URL per tenant**. A
Meta App has exactly one webhook subscription (one URL, one verify token, one app secret) for
its whole WhatsApp Business Account, however many phone numbers hang off it. Twilio's console
does let you point different numbers at different URLs, which is where the original per-tenant
model came from — it does not transfer to Meta. Confirmed with the user: AutoHostAI runs **one
shared Meta App** for the whole platform (matching what section 1 already built —
`WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_APP_SECRET`/`WHATSAPP_PHONE_NUMBER_ID` are global `Settings`
values, not per-tenant credentials), with **one dedicated phone number per tenant** under that
shared App. Inbound tenant resolution therefore cannot be "read a token from the route" (there is
only one route); it has to be "read `phone_number_id` from the payload's delivery metadata and
look it up" — and that is safe under R4.1 for the same reason the route token was: `metadata.
phone_number_id` is Meta's own delivery envelope, not guest-supplied message content, so reading
it is not "trusting the body" in the sense R4.1 forbids.

**Chosen:**

- `messaging/infrastructure/models.py`: `WhatsAppPhoneNumberModel` — one row per tenant,
  `tenant_id` (unique) and `phone_number_id` (unique, indexed — this is the lookup key every
  inbound message resolves through), plus `display_phone_number` (human-readable, operator-facing
  only, never used for resolution) and timestamps. **No secret of any kind lives on this row**:
  there is nothing per-tenant left to protect here once the signing secret and the route are both
  shared platform-wide (see D3a). This replaces the `WhatsAppWebhookEndpointModel`/`token_hash`/
  `signing_secret_encrypted` shape the original D3 described.
- `messaging/domain/whatsapp_webhook.py` (already built, section 4): re-exports `secrets_match`
  from `app.integrations.domain.webhook_auth` — still needed, for the shared HMAC comparison
  (D3a). `generate_webhook_token`/`hash_webhook_token` are **no longer consumed by this change**
  (nothing mints a per-tenant route token anymore) and must be dropped from this module's
  re-exports — R1.1's own precedent in this codebase is that a method with no consumer does not
  ship. Flagged as a follow-up correction to section 4's already-merged work.
- A new router, `messaging/api/whatsapp_webhook_router.py`, anonymous, at a **single fixed route**
  `POST /api/v1/webhooks/whatsapp` (no path segment — there is nothing tenant-specific left to put
  in it). Still a sibling of `webhooks_router.py` under `/webhooks/`, for the same readability
  reason the original D3 gave.
- Provisioning becomes phone-number-to-tenant association, not secret minting — see D8 below.

Rejected (unchanged from the original D3): extend `PMSProvider` with a `WHATSAPP` member and reuse
`webhook_endpoints`/`webhooks_router.py` wholesale, or generalise them into a provider-agnostic
mechanism now. Both reasons the original text gave still hold and are not affected by this
supersession — the model is different, but so is the target it would have polluted.

### D3a — Real provider signature, not rule 12(a)'s static-header fallback — and why rule 12(b) doesn't bind Meta either

**Chosen:** rule 12's "cabecera estática" mechanism exists because "ninguno de los once
proveedores [PMS] evaluados firma sus webhooks" — a premise that is false for WhatsApp. **Meta**
signs with `X-Hub-Signature-256` (HMAC-SHA256 over the raw request body, the **single, global**
app secret as key — `settings.whatsapp_app_secret`, the same value section 1 already declared,
Fernet-encryption not applicable to it since it lives in the environment under rule 8, not in the
database under rule 3). The receiving use case verifies the real signature in constant time
(`hmac.compare_digest`, same primitive family as `secrets_match`) instead of comparing a
system-generated header value. (Twilio's `X-Twilio-Signature` — HMAC-SHA1 over the callback URL
plus sorted form params — is documented here only as the mechanism a future Twilio addition would
implement behind the same port; nothing in this change reads it.)

**Superseded 2026-09-02 (same supersession as D3): there is no per-tenant signing secret.**
The original text had `WhatsAppWebhookEndpointModel.signing_secret_encrypted` store "the Meta app
secret" per tenant — which was never actually mintable by us (Meta issues the app secret when the
operator creates the Meta App; we cannot generate a value for Meta to sign with) and, once the
one-shared-App topology was confirmed, is also simply the wrong shape: there is exactly one app
secret for the whole platform, already in `Settings`, not one per tenant to store and decrypt per
request.

**And that supersession changes what rule 12(b) requires here.** Rule 12's own scope line reads
"aplica a **cualquier webhook entrante sin firma**" — it is a rule about unsigned webhooks by its
own text, not a universal webhook rule. Meta's webhook carries a real, cryptographically strong
signature, so the rule's premise (an anonymous write with no proof of origin) does not hold for
it in the first place — the original D3a already used this to skip 12(a)'s literal mechanism;
the same reading extends to 12(b)'s "ruta no adivinable por tenant". The route token's job in the
PMS design was to be the *other* half of a two-factor defence ("si el secreto se filtra queda la
ruta, y si la ruta se adivina queda el secreto") for a provider that could not itself prove
authorship. Meta's HMAC signature already proves authorship on its own — nobody without the
shared app secret can forge a valid request, regardless of what route they hit — so a second,
route-shaped factor adds no defence a single fixed route doesn't already have. Rejected once more:
minting a per-tenant route token anyway "for defence in depth" — there is nothing left it would
defend that the signature doesn't already cover, and it would resurrect exactly the "one URL per
tenant" assumption Meta's API doesn't support (D3).

**The one-time webhook verification GET, unaffected by this supersession.** Meta requires the
receiving URL to answer a `GET` handshake once, when the webhook is first registered (and again
on any resubscription) in the Meta App dashboard: the request carries `hub.mode=subscribe`,
`hub.verify_token=<value we chose>` and `hub.challenge=<random string>` as query params, and the
endpoint must echo back `hub.challenge` as plain text — but **only** if `hub.verify_token` matches
a secret we configured (`WHATSAPP_WEBHOOK_VERIFY_TOKEN`, a rule-8 value, no default, already
global — this was never per-tenant even before the supersession, since there is only one Meta App
dashboard registration). This is a Meta-specific addition to `whatsapp_webhook_router.py`
(section 7): a `GET` handler on the **same single fixed route** as the `POST` receiver. Getting
this wrong (mismatched or missing token) means Meta's dashboard refuses to save the webhook
subscription at all — a hard configuration-time failure, not a runtime security gap.

Rejected: rule 12(a)'s literal mechanism (mint our own static header value, ask the operator to
paste it into Meta's console). Meta supports real HMAC verification, and `steering/security.md`'s
own trigger list says to "validar firma HMAC cuando el provider lo soporte" — this is the case
that condition was written for but until now never applied, because every provider measured so
far failed it.

### D9 — Inbound provider specifics behind a port too, symmetric to D1

**Chosen:** the receiving side needs the same isolation D1 gives the sending side. Meta's inbound
webhook is a nested JSON body — `entry[].changes[].value.messages[]`, each with `from` (sender's
phone, no `whatsapp:` prefix unlike Twilio's), `id` (the provider message id), `timestamp` (Unix
seconds, string), `type`/`text.body`, and `value.metadata.phone_number_id` (which business number
received it) — signed over the raw bytes with `X-Hub-Signature-256` (D3a). None of that may leak
into `messaging/application/` or `messaging/domain/`. A new port,
`WhatsAppInboundProviderAdapter` (`messaging/domain/ports.py`), declares exactly two methods:

```python
class WhatsAppInboundProviderAdapter(Protocol):
    def verify_signature(
        self, *, raw_body: bytes, headers: Mapping[str, str], secret: str, url: str
    ) -> bool: ...
    def parse(self, *, raw_body: bytes, headers: Mapping[str, str]) -> InboundWhatsAppMessage: ...
```

`InboundWhatsAppMessage` (a frozen value object in `messaging/domain/value_objects.py`) carries
`sender_phone`, `provider_message_id`, `text`, `received_at`, `business_phone_number` — the only
shape the receiving use case and `PostWhatsAppInboundMessageUseCase` ever see. `MetaInboundAdapter`
implements it now (`messaging/infrastructure/whatsapp_providers.py`); a `TwilioInboundAdapter` in
the same module — parsing `application/x-www-form-urlencoded` fields `From`/`To`/`Body`/
`MessageSid`, verifying `X-Twilio-Signature` — is the entire cost of a future Twilio addition, not
built in this change. The same `WHATSAPP_PROVIDER` switch that selects the outbound adapter in D1
selects this one too — one config value, one adapter instance today, wired together in
`messaging/api/dependencies.py`.

Rejected: verify and parse inline in the receiving use case (`ReceiveWhatsAppWebhookUseCase`),
branching on `endpoint.provider`. This is exactly the leak the user asked to avoid: adding a
second provider would mean editing `application/`, and every test of the receiving pipeline would
need to know both providers' payload shapes instead of testing against one small port.

### D4 — Conversation resolution: `ensure_whatsapp`, keyed by guest and property

**Chosen:** `ConversationRepository` gains `ensure_whatsapp(tenant_id, *, guest_id, property_id,
reservation_id, language, business_phone_number, now)`, structurally parallel to `ensure_portal`
(same `INSERT ... ON CONFLICT DO NOTHING` shape) but with a **new partial unique index** on
`(tenant_id, guest_id, property_id)` where `channel = WHATSAPP`, not on `reservation_id`. **Per
guest and per property, confirmed with the user**: a guest who has stayed at two of the tenant's
properties gets one thread per property rather than one lifetime thread, which is closer to how a
manager reads a conversation (a message about property B shouldn't surface property A's
unrelated history).

**Superseded 2026-09-02, discovered mid-implementation of section 5 (before section 5 was
reviewed) and confirmed with the user**: the text originally here said "`property_id` can still
be `None`" for R4.3's unresolved-match row. That was never actually true — `Conversation.
__post_init__` (design D19, `guest-portal-messaging`, already shipped and archived) hard-refuses
a `None` `property_id`, precisely because `TimelineEventFactory` (`app/timeline/domain/
services.py`, a service shared by other domains — `cleaning`, `maintenance` — not owned by
`messaging`) requires a non-null `property_id` UUID to construct any timeline event, and R4.1/
R4.4/R4.5/R5.2 all mandate one. The original design text asserted an entity capability that was
never built. **Resolution: every tenant designates a default property when provisioning its
WhatsApp number (D8/section 6, `WhatsAppPhoneNumberModel.default_property_id`)**, and
`ensure_whatsapp` uses it whenever R4.3 (zero guest matches) or R4.4 (ambiguous match) apply — a
message that can't be attached to a specific stay still lands on a real property, satisfying
D19's invariant, `TimelineEventFactory`'s requirement, and the manager's expectation of finding
it somewhere (now under the tenant's default property, reassignable by hand from there instead of
appearing in no property's inbox at all). `guest_id` remains genuinely `None` for R4.3 (there is
no guest to name), and the `NULL`-never-equals-`NULL` behavior of the partial unique index now
applies only to that column: a never-yet-matched sender gets a fresh row per message until a
guest resolves — the same accepted limitation the original text described, just correctly scoped
to `guest_id` instead of `property_id`, which is now always populated.

Rejected: relaxing `Conversation.__post_init__`'s `property_id` check for `WHATSAPP` and making
`TimelineEventFactory`'s four mandatory events conditional on it. Closest to the original design
text, but reopens an already-shipped, already-archived change's invariant and touches a service
shared by domains this change has no reason to touch — a materially larger and riskier blast
radius than a single new nullable-by-default column on this change's own new table.

Rejected: register the message without ever creating a `Conversation` row for the unresolved
cases, surfaced by some other, lighter mechanism. Avoids touching `Conversation`/`TimelineEvent`
entirely, but that mechanism does not exist yet and would need its own design — real scope this
change did not budget for, to solve a problem the default-property column solves already.

**`business_phone_number` addendum, 2026-09-02** (follows from D1's addendum): `Conversation`
(`messaging/domain/entities.py`) gains a `business_phone_number: str | None` field, set once at
`ensure_whatsapp()` time from the inbound message's `InboundWhatsAppMessage.business_phone_number`
(section 4) and never changed after — a reply always leaves from the number the thread was opened
on, even if the tenant's configured number in `WhatsAppPhoneNumberModel` (D3) is later changed;
retargeting an existing thread to a new number is out of scope, a follow-up if it ever matters.
`None` for every non-`WHATSAPP` channel (`ensure_portal` and friends don't set it).

Rejected: `(tenant_id, guest_id)` only (one thread per guest for life). Simpler key, but mixes
conversation history across unrelated stays at different properties — rejected by the user.

Rejected: reuse `ensure_portal`'s key shape (per `reservation_id`). Breaks whenever `reservation_id`
is `None` (R4.3's no-match case) or a returning guest's phone doesn't resolve to the reservation
that later turns out relevant — an `INSERT` with a `NULL` in a partial unique index's key column
can't dedupe against a later row that does have one.

### D5 — Phone → guest/tenant resolution: new query, normalised E.164, no cross-tenant search

**Chosen:** `GuestRepository` (domain port) gains `find_by_phone(tenant_id, phone: str) ->
list[GuestSummary]` (plural — see R4.4), added to both the port
(`guests/domain/repositories.py`) and its SQLAlchemy implementation, with a new index
`ix_guests_tenant_id_phone` (mirrors the existing `ix_guests_tenant_id_email`). The webhook
handler normalises the sender's number to E.164 before querying (`phonenumbers` is not currently
a dependency; a hand-rolled normaliser is enough for the two markets in scope). The search is
**always scoped to the tenant `WhatsAppPhoneNumberModel` already resolved from `phone_number_id`**
(R4.1, D3) — there is no cross-tenant phone lookup, by construction, because the query takes
`tenant_id` as a required parameter and the repository is tenant-scoped like every other read in
this codebase.

For "which reservation", a new `ReservationRepository.find_active_for_guest(tenant_id, guest_id,
*, on_date)` returns reservations for that guest whose stay window, **widened by 2 days on each
side** (confirmed with the user — covers early-arrival/late-checkout questions without treating
every past guest as indefinitely "active"), contains `on_date`: `check_in_date - 2 days <= on_date
<= check_out_date + 2 days`. The 2-day figure is a named constant
(`RESERVATION_MATCH_GRACE_DAYS`), not hard-coded inline, so a later change can retune it without
hunting for the literal. Zero matches (no active reservation for that guest) and two-or-more
matches (guest or reservation) both fall back to the tenant's default property (D4 supersession,
above) rather than `property_id=None` — `Conversation.property_id` cannot be `None` (D19), so
`reservation_id=None` (no specific stay to attach) with `property_id=<the tenant's default>` is
what makes the manager see an unattached-to-a-stay-but-real WhatsApp thread instead of a crash.
Two or more matches (guest or reservation): R4.4, escalate rather than guess — surfaced as a
`ConversationEscalationStatus` set directly rather than run through the AI classifier, since
there is nothing to classify yet.

Rejected: matching without tenant scoping and disambiguating by "most recent reservation across
tenants" — would let one guest's message leak into a conversation of a tenant they never booked
with if the same phone number happens to exist in two tenants' guest tables (a real risk once
this is more than 2 properties under one owner).

### D6 — `InboundMessageActor` gains a third identity: `resolved_phone`

**Chosen:** widen the frozen dataclass to three optional fields with an "exactly one" invariant
(`user_id` / `token_hash` / `resolved_phone`), following the same pattern its own docstring
already uses to justify the second one ("Widening from a required `user_id` to a choice loosens
one invariant and tightens another"). `resolved_phone` carries the E.164 number the webhook
authenticated by — not a token, so no digest-shape check applies to it, but it is still traceable
in `audit_logs.actor_*` the same way `token_hash` is today.

Rejected: reuse `token_hash` for this, storing a hash of the phone number. It would silently
change what that field means everywhere it is already checked (`is_guest_token_digest`), and an
auditor reading `actor_token_hash` on a `WHATSAPP`-channel row would reasonably assume it is a
portal link, which it is not.

### D7 — Inbound processing dispatches immediately, not on the 60 s beat cadence

**Chosen:** `receive_whatsapp_webhook`'s use case (mirroring `ReceiveWebhookUseCase.authenticate`
+ `record`) authenticates, then dispatches a Celery task (`process_inbound_whatsapp_message.delay(
event_id)`) **immediately** after the row commits — not through `process_webhook_events`'s 60 s
beat tick. Rule 12(d)'s decoupling requirement is about capping *outbound API calls triggered by
webhook volume* (the PMS re-read that can exhaust a rate-limited account); there is no re-read
here — the payload already carries the message — so the concern the 60 s cadence exists to
address does not apply. The one outbound call a message produces (the AI's reply, D2) is
one-per-inbound-message by construction, not fan-out, so nothing about it scales with an
attacker's request volume the way a re-read would.

Rejected: route through `process_webhook_events`/60 s cadence for consistency with
`reservations-webhooks`. Would add up to 60 s of latency to every guest message before the AI
even sees it, which contradicts `ProcessInboundGuestMessageUseCase`'s own stated design ("the
product promise is that they get an answer" — currently synchronous *inside the request* for the
portal). A WhatsApp reply cannot be synchronous inside the webhook's HTTP response (the response
must be fast and content-free, same as the PMS receiver), but it does not have to wait a full
cadence either.

### D8 — Provisioning: associate a `phone_number_id` with a tenant, not mint a secret

**Superseded 2026-09-02, same supersession as D3/D3a.** The original text modeled this on
`CreateWebhookEndpointUseCase`/`RotateWebhookEndpointUseCase` — "mint both secrets, return them
once" — which cannot work for Meta: there is no secret left for this endpoint to mint (D3a),
only an association between a tenant and the `phone_number_id` the operator already obtained from
Meta's own dashboard when they added that number to the shared App.

**Chosen:** `messaging/application/whatsapp_provisioning.py` gets
`AssociateWhatsAppPhoneNumberUseCase` (create-or-replace the tenant's row in
`WhatsAppPhoneNumberModel`, D3) and `ReleaseWhatsAppPhoneNumberUseCase` (the "rotate" equivalent —
detach a number, e.g. because it changed tenant or is being decommissioned). Both take
`phone_number_id` as an operator-supplied input (never generated by us — it comes from Meta's
dashboard, same as `WHATSAPP_PHONE_NUMBER_ID` did for the platform-wide send path in section 1),
enforce the uniqueness constraint (R6.2: one tenant per number) as a database-level check, not a
prior read, and audit the association/release (rule 9) — there is no value to keep secret here,
so no rule-12(a) "return once" exception applies; a `GET` on the tenant's own settings can safely
show its currently-associated `phone_number_id` back, unlike a webhook secret. Exposed under the
existing `integrations` router's sibling pattern: `POST /api/v1/messaging/whatsapp-phone-number`
and its `/release` (or a single `PUT`-shaped endpoint that both creates and reassigns — the
implementer decides which reads more naturally against `MANAGE_TENANT_SETTINGS`'s existing REST
shape in this codebase), permission `MANAGE_TENANT_SETTINGS` (same as the PMS one).

**`default_property_id` addendum, 2026-09-02** (D4 supersession, discovered mid-implementation of
section 5): `AssociateWhatsAppPhoneNumberUseCase` also takes a required `default_property_id:
uuid.UUID` — one of the tenant's own properties, validated to belong to that tenant the same way
every other property-scoped write in this codebase validates ownership before accepting an id.
`WhatsAppPhoneNumberModel` gains the matching `default_property_id` column (FK to `properties`,
`NOT NULL`). `ensure_whatsapp` (D4) falls back to this value whenever it cannot resolve a specific
stay's property (R4.3's zero-match case, R4.4's ambiguous-match cases) — `Conversation.
property_id` can never be `None` (D19), so provisioning must supply a real fallback before section
5's resolution logic has anywhere to land an unresolved message. `ReleaseWhatsAppPhoneNumberUseCase`
does not need a symmetric field — releasing a number does not touch conversations already created
under it.

Rejected (unchanged reasoning from the original D8, still applies to *why this is an endpoint at
all* rather than a CLI): a CLI run against production is a worse way to let an operator confirm
"yes, this number belongs to this tenant" than an authenticated, audited API response — though
the original's *specific* justification ("the operator has to see the plaintext secret once") no
longer applies, since there is no secret; the general "self-service beats CLI for a
tenant-scoped admin action" reasoning still does.

## Changes by area

| Area | Files | Change |
|---|---|---|
| `notifications/infrastructure/` | `adapters.py` | `MockWhatsAppAdapter` → `WhatsAppCloudAdapter` (real client + `mock` mode); `NotificationAdapter.send` gains `last_inbound_at`, `template_id`, `phone_number_id` kwargs (last one is a follow-up to already-reviewed section 1, D1 addendum) |
| `notifications/domain/` | `results.py` | New `NotificationErrorCode.OUTSIDE_SESSION_WINDOW` (or similar) |
| `notifications/infrastructure/` | `adapters.py` | `adapter_registry()` reads `WHATSAPP_PROVIDER`/credentials, constructs the real adapter |
| `messaging/infrastructure/` | `channels.py` | `DelegatingOutboundAdapter` resolves `last_inbound_at` via `MessageRepository.last_guest_message_at` (new constructor dependency) and passes `template_id` through; `OutboundMessagePort.send` signature widened; `outbound_registry()` gains the `MessageRepository` dependency |
| `messaging/domain/` | `repositories.py` | New `MessageRepository.last_guest_message_at(tenant_id, conversation_id) -> datetime \| None` (D2) |
| `messaging/infrastructure/` | `repositories.py` | `SqlAlchemyMessageRepository.last_guest_message_at` implementation |
| `messaging/domain/` | `value_objects.py` | `InboundMessageActor` gains `resolved_phone` (D6); `ChannelErrorCode` gains the window failure |
| `messaging/domain/` | `entities.py` | `Conversation` gains `business_phone_number: str \| None` (D4 addendum), set once by `ensure_whatsapp` |
| `messaging/domain/` | new `whatsapp_webhook.py` | Re-exports `secrets_match` only (D3 supersession — `generate_webhook_token`/`hash_webhook_token` are unused now and must be dropped from section 4's already-built module) |
| `messaging/domain/` | `ports.py` | New `WhatsAppInboundProviderAdapter` protocol (D9) |
| `messaging/domain/` | `value_objects.py` | New `InboundWhatsAppMessage` value object (D9) |
| `messaging/domain/` | `repositories.py` | `ConversationRepository.ensure_whatsapp(...)` (D4) |
| `messaging/infrastructure/` | new `whatsapp_providers.py` | `MetaInboundAdapter` implementing `WhatsAppInboundProviderAdapter` (D9); `TwilioInboundAdapter` is future work |
| `messaging/infrastructure/` | `models.py`, `repositories.py` | `WhatsAppPhoneNumberModel` (D3, supersedes `WhatsAppWebhookEndpointModel`); `ensure_whatsapp` impl + new partial unique index on `(tenant_id, guest_id, property_id)` |
| `messaging/application/` | new `whatsapp_inbound.py` | `PostWhatsAppInboundMessageUseCase` (mirrors `PostPortalGuestMessageUseCase`), identity resolution (D5), escalation on ambiguity |
| `messaging/application/` | new `whatsapp_provisioning.py` | Associate/release phone-number-to-tenant use cases (D8, supersedes the original create/rotate-secret shape) |
| `messaging/api/` | new `whatsapp_webhook_router.py`, `whatsapp_webhook_schemas.py` | Anonymous receiver route (`POST`), single fixed path, no per-tenant segment (D3); Meta's one-time verification handshake (`GET`, D3a); provisioning request/response schemas |
| `messaging/api/` | `router.py` (authenticated) or new file | Provisioning endpoints (D8) |
| `messaging/api/` | `dependencies.py` | Wire `WHATSAPP_PROVIDER` to both the outbound adapter (D1) and `WhatsAppInboundProviderAdapter` (D9) |
| `guests/domain/`, `guests/infrastructure/` | `repositories.py` (both) | `find_by_phone` |
| `guests/infrastructure/` | `models.py` | New index `ix_guests_tenant_id_phone` |
| `reservations/domain/`, `reservations/infrastructure/` | `repositories.py` (both) | `find_active_for_guest` |
| `core/` | `config.py` | `WHATSAPP_PROVIDER`, `WHATSAPP_*` credential settings (no defaults, per rule 8); correct the two existing "already reserved" claims (adapter docstring + `config.py:253`) |
| `.env.example` | — | New `WHATSAPP_*` names, per R1.3 |
| `worker.py`, new task module | — | `process_inbound_whatsapp_message` task (D7), no beat entry |
| Alembic | new migration | `whatsapp_phone_numbers` table; `ix_guests_tenant_id_phone`; partial unique index for `ensure_whatsapp` |
| Alembic | new migration | `whatsapp_inbound_events` table (D7, R3.3-R3.5) |

## Data & interfaces

- **New table** `whatsapp_phone_numbers` (D3, supersedes the original `whatsapp_webhook_endpoints`
  shape): `id`, `tenant_id` (unique — one number per tenant for now), `phone_number_id` (unique,
  indexed — the inbound resolution key), `display_phone_number` (operator-facing only, never used
  for resolution), `default_property_id` (FK to `properties`, `NOT NULL` — D8 addendum, where an
  unresolved R4.3/R4.4 message lands), timestamps. No secret column of any kind — the signing
  secret and the route are both platform-wide now (D3a), not per-tenant.
- **New table** `whatsapp_inbound_events` (D7, R3.3-R3.5): `id`, `tenant_id` (FK to `tenants`,
  **nullable** — mirrors `webhook_events`' precedent: R3.3 as amended routes a validly-signed
  delivery for an unmapped `phone_number_id` here rather than discarding it, and with no tenant
  resolved there is no `tenant_id` to write; the table sits outside `TenantScopedMixin` for this
  reason, and both the receiving route and the dispatched worker read it from an unmarked
  session, same as `find_by_phone_number_id`), `default_property_id` (FK to `properties`,
  `ondelete="RESTRICT"`, nullable in step with `tenant_id`, copied from `whatsapp_phone_numbers`
  on a successful resolution), `phone_number_id` (indexed — the value an operator looks a stuck,
  unmapped delivery up by; never used to resolve a tenant, only `whatsapp_phone_numbers
  .phone_number_id` is), `provider_message_id` (unique, indexed — Meta's `wamid…`, the
  schema-level guarantee behind R3.5: a redelivery on any non-2xx cannot become a second message
  in the guest's thread), `sender_phone`, `message_text` (a cleartext sink per rule 11 of
  `steering/security.md`, bounded by `MAX_MESSAGE_CONTENT_LENGTH` — the same ceiling
  `messages.content` meets), `received_at` (Meta's own timestamp, distinct from `created_at`),
  `processed_at` (nullable, `NULL` until the dispatched task flips it inside the same transaction
  as the work — the claim column that makes a Celery redelivery of the same task a no-op),
  timestamps.
- **New route** `POST /api/v1/webhooks/whatsapp` — anonymous, single fixed path (no per-tenant
  segment, D3), `202`/`403`/`429`/`413` — and `GET /api/v1/webhooks/whatsapp` — Meta's one-time
  verification handshake (D3a): echoes `hub.challenge` as plain text only when `hub.verify_token`
  matches `WHATSAPP_WEBHOOK_VERIFY_TOKEN`, else `403` with an empty body. The indistinguishable-
  failure posture (R3.3) covers signature-verification failures; a validly-signed payload for an
  unmapped `phone_number_id` is a distinct, non-adversarial case (R3.3, amended) handled like R4.3.
- **New routes** `POST /api/v1/messaging/whatsapp-phone-number`, `POST
  /api/v1/messaging/whatsapp-phone-number/release` — authenticated, `MANAGE_TENANT_SETTINGS`. No
  secret is returned by either — there is nothing to reveal once (D8 supersession); a subsequent
  `GET` may safely show the tenant's current `phone_number_id`.
- **Widened port signatures**: `NotificationAdapter.send(..., last_inbound_at: datetime | None =
  None, template_id: str | None = None, phone_number_id: str | None = None)`;
  `OutboundMessagePort.send(..., last_inbound_at: datetime | None = None, template_id: str | None
  = None, tenant_id: uuid.UUID, phone_number_id: str | None = None)` — `phone_number_id` is D1's
  addendum (per-tenant "from" number); `tenant_id` is new versus `NotificationAdapter` and
  required (no default): resolving `last_inbound_at` from `MessageRepository.last_guest_message_at`
  (D2) is a tenant-scoped query per rule 1 of `steering/security.md`, and the port's existing
  params carry no tenant context. The one call site (`messaging/application/use_cases.py`'s
  AI-reply use case) already holds `tenant_id` in scope, so this is a pass-through, not new
  plumbing; the other three `OutboundMessagePort` implementers (`PanelOutboundAdapter`,
  `PortalOutboundAdapter`, `InboundOnlyAdapter`) accept and ignore both new kwargs, same as they
  already ignore `channel`/`language`.
- **Env vars** (`.env.example`, no defaults): `WHATSAPP_PROVIDER` (`mock`/`meta` — `twilio` is a
  valid future value, not accepted today), `WHATSAPP_ACCESS_TOKEN` (Graph API bearer token,
  system-user token in production), `WHATSAPP_PHONE_NUMBER_ID` (the business number's Graph API
  identifier, distinct from the human-readable phone number — used in the send URL path), and
  `WHATSAPP_APP_SECRET` (HMAC key for `X-Hub-Signature-256`, D3a) for the **outbound** side and the
  signature check; `WHATSAPP_WEBHOOK_VERIFY_TOKEN` (D3a's one-time `GET` handshake secret) is
  separate from `signing_secret_encrypted` because it authenticates a **configuration-time** call
  from Meta's dashboard, not a per-message signature — it is a single system-wide value in
  `Settings`, not a per-tenant row, since Meta's dashboard verification is done once per WABA app,
  not per tenant webhook URL registration in this MVP's single-app topology.
- **New enum** `NotificationErrorCode.OUTSIDE_SESSION_WINDOW` and matching
  `ChannelErrorCode.OUTSIDE_SESSION_WINDOW`.

## Risks & mitigations

- **Meta's development test number is shared the same way Twilio Sandbox was: one test number,
  up to 5 allow-listed recipient phone numbers, no WABA business verification.** Superseded
  2026-09-02, so read this against the shipped topology and not the original one: there is no
  per-tenant URL token any more (R3.1 amended — one fixed route, D3/D3a), but each tenant still
  gets its own `WHATSAPP_PHONE_NUMBER_ID` via section 6's provisioning row, so multiple tenants
  can each test against their own number if more than one needs to. True multi-number,
  multi-tenant production behaviour (separate business-verified numbers per tenant) is still not
  exercised in dev. Mitigation: unchanged in substance from the original Twilio-era text — treat
  test-number testing as single/few-tenant validation; the multi-tenant claim rests on the
  per-tenant `phone_number_id`-to-tenant resolution (R4.1, section 6) being exercised in tests, not
  on having tested it against many live numbers.
- **One shared `WHATSAPP_APP_SECRET` authenticates inbound deliveries for every tenant at once
  (D3/D3a supersession, 2026-09-02) — a risk this design did not record when the per-tenant
  topology was dropped.** Unlike `reservations-webhooks`, where each tenant's own per-tenant
  secret bounds a leak to that one tenant, a leak of this single App-wide secret lets an attacker
  forge a validly-signed delivery for *every* tenant's `phone_number_id` at once — HMAC
  verification (R3.2) would pass for all of them, because there is only the one key to check
  against. This is the cost of Meta's own constraint, not a choice this design made freely: Meta
  allows exactly one webhook URL and one App secret per App, never one per tenant (the discovery
  that drove D3/D3a in the first place), so the alternative was not "keep it per-tenant" but "have
  no WhatsApp integration at all". Mitigation: `WHATSAPP_APP_SECRET` is a rule-8 credential (name
  only in `.env.example`, real value only in the deployment's secret store) with no
  application-level rotation support yet — rotating it today means updating the Meta App
  dashboard and the deployment's secret in lockstep, with an unavoidable window where in-flight
  deliveries signed with the old secret are rejected. A follow-up change owns building that
  rotation path if the blast radius above proves unacceptable; recorded here so the next author
  does not have to rediscover it.
- **Meta's one-time webhook verification `GET` handshake (D3a) is a new failure mode Twilio never
  had.** If `WHATSAPP_WEBHOOK_VERIFY_TOKEN` is missing or wrong when an operator (re)registers the
  webhook URL in the Meta App dashboard, Meta refuses to save the subscription — no inbound
  messages arrive, silently, until someone checks the dashboard's own error message. Mitigation:
  this is a configuration-time failure caught at setup, not a runtime security gap; document the
  handshake in the operator-facing provisioning flow (R6, D8) so it is not discovered by an absent
  first message.
- **No approved WhatsApp Business template exists yet.** Every currently-mocked proactive
  notification (`CLEANING_TASK_ASSIGNED` etc.) will start failing with
  `OUTSIDE_SESSION_WINDOW` the moment the real adapter is live, unless a template is submitted
  and approved before this ships (external dependency, unpredictable turnaround — Meta's
  approval process is not in this team's control). Mitigation: proposal already scopes this out;
  D2 makes the failure explicit and typed rather than silent, which is the honest MVP behaviour
  (same taste as the `PUSH` adapter gap and `InboundOnlyAdapter`).
- **Phone number normalisation is a real source of false negatives/positives.** A hand-rolled
  E.164 normaliser can misparse an unusual national format and either miss a real guest match or
  (worse) collide two different numbers. Mitigation: keep the normaliser narrow (Spain +
  whichever countries the pilot guests actually use) and fail closed to "no match" (R4.3) rather
  than guessing a normalisation.
- **A guest with no property resolved yet (R4.3) gets one new `Conversation` row per message**,
  since `property_id IS NULL` never dedupes against another `NULL` row under the chosen partial
  unique index (D4). Acceptable for a rare, operator-visible edge case; if it turns out common in
  practice (e.g. a guest writing before any reservation exists), a follow-up change can key the
  unresolved case on `guest_id` alone instead.

## Open questions

None outstanding — the four raised during the original design were resolved with the user at the
design gate (2026-09-02) and are recorded inline above: accept the `OUTSIDE_SESSION_WINDOW`
failure rather than submit a template (D2/Risks); `ensure_whatsapp` keyed per guest **and**
property (D4); a 2-day grace window on `find_active_for_guest` (D5). The fourth — provider choice
— was **superseded same-day, before any implementation existed**: the user redirected from
"Twilio first, Meta later" to **Meta Cloud API as the sole provider**, recorded in D1/D3a/D9 above.
Provider specifics stay isolated behind D1 (outbound)/D9 (inbound) exactly as originally decided,
so a future Twilio addition still touches only `infrastructure/` — the isolation goal didn't
change, only which provider is real today and which is the placeholder behind the port.

A fifth item surfaced during section 2's implementation planning and was resolved the same way,
before any section-2 code existed: D2 originally left "`DelegatingOutboundAdapter` resolves
`last_inbound_at` from `Conversation.last_message_at`... but that field records any message, not
the guest's last one" as an unresolved "see the open question below" that this section never
actually answered. Resolved 2026-09-02 (confirmed with the user): add
`MessageRepository.last_guest_message_at`, a guest-specific query, rather than accept the
`last_message_at` approximation — recorded inline in D2 above.
