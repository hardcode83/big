"""Meta's half of the inbound webhook, and the only place in `messaging` that knows its shape
(`whatsapp-cloud-adapter` R3.2, R4.1; design D9, D3a).

`MetaInboundAdapter` is the one implementer of `WhatsAppInboundProviderAdapter` this change
ships. Everything provider-specific lives here and nowhere else: the name of the signature
header, the algorithm behind it, and the four-level nest Meta calls a webhook body
(`entry[].changes[].value.messages[]`, with `metadata.phone_number_id` off to one side). D9's
requirement is literal — "none of that may leak into `messaging/application/` or
`messaging/domain/`" — so what leaves this module is a `bool` and an `InboundWhatsAppMessage`.

**Nothing here logs a phone number, a message id or a word the guest wrote.** Rule 11 of
`sdd/steering/security.md` governs this input more than any other in the system: it is
unauthenticated text from the open internet, addressed to a route with no session, and the
natural `logger.warning("bad body: %s", raw_body)` would put the guest's message into every
log aggregator the deployment has. The one log line this module emits counts messages.

**No `settings` import, deliberately.** `verify_signature` takes `secret: str` because the
port declares it that way (D9), so the app secret arrives already resolved — and already
decrypted, if the deployment stores it encrypted — from the layer entitled to read it. That
is what lets a per-tenant credential replace the system-wide `WHATSAPP_APP_SECRET` later
without touching this file, and it keeps this adapter testable with a literal key.
"""

import hashlib
import hmac
import json
import logging
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from app.messaging.domain.exceptions import NoInboundMessageError
from app.messaging.domain.value_objects import InboundWhatsAppMessage
from app.messaging.domain.whatsapp_webhook import secrets_match

logger = logging.getLogger(__name__)

#: The header Meta signs the raw body with (design D3a). Canonical spelling; the lookup below
#: is case-insensitive anyway, because HTTP header names are.
SIGNATURE_HEADER = "X-Hub-Signature-256"

#: Meta's header value is `sha256=<hex digest>`. The algorithm travels *in* the header, so it
#: is checked rather than assumed: a body signed with anything else — including a future
#: `sha1=`, which Meta's older `X-Hub-Signature` used and which is broken — is not a signature
#: this adapter accepts.
SIGNATURE_ALGORITHM = "sha256"

#: 64: a SHA-256 digest is 32 bytes, and hex is two characters per byte. A presented value of
#: any other length cannot be a digest, so it is refused before an HMAC is computed.
_DIGEST_HEX_LENGTH = hashlib.sha256().digest_size * 2


def _header(headers: Mapping[str, str], name: str) -> str | None:
    """One header, looked up without trusting the caller's capitalisation.

    HTTP header names are case-insensitive, and this mapping arrives from two different kinds
    of caller: Starlette's `Headers` (already case-insensitive — the shape
    `integrations/api/webhooks_router.py` passes as `request.headers.get`) and a plain `dict`
    in a test. The exact-hit branch covers both of those; the scan covers a `dict` spelled
    `x-hub-signature-256`, which is how the header actually arrives over HTTP/2 and what a
    caller building its own mapping from an ASGI scope would produce.

    Doing it here rather than asking section 7's router to normalise means the guarantee is a
    property of the adapter and not of whoever wires it — the same argument
    `InboundMessageActor` records for validating at construction.
    """
    exact = headers.get(name)
    if exact is not None:
        return exact
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _require_mapping(candidate: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(candidate, Mapping):
        raise NoInboundMessageError(
            f"the webhook body's {field} is not an object, so it carries no inbound message"
        )
    return candidate


def _require_non_empty_list(candidate: Any, field: str) -> list[Any]:
    """A list with at least one element, or the one error the port is allowed to raise.

    `entry`, `changes` and `messages` are all lists that Meta sends **empty or absent** in
    perfectly ordinary traffic, so every one of the three gets this treatment. Without it the
    traversal would be `payload["entry"][0]["changes"][0]`, and a status receipt would arrive
    at the caller as a `KeyError` or an `IndexError` — indistinguishable from a bug of ours,
    which is precisely the distinction section 7 has to make to answer `202` rather than `500`.
    """
    if not isinstance(candidate, list) or not candidate:
        raise NoInboundMessageError(
            f"the webhook body's {field} is absent or empty, so it carries no inbound message"
        )
    return candidate


class MetaInboundAdapter:
    """`WhatsAppInboundProviderAdapter` against Meta's WhatsApp Cloud API (D9, D3a).

    Stateless and constructed with no arguments: both methods are pure functions of what they
    are handed. That is what makes it safe for section 7's dependency wiring to build one per
    request or one per process, and it is why there is no credential on `self` — see the module
    docstring.

    Substitutable with a future `TwilioInboundAdapter` by contract: `verify_signature` never
    raises and never answers anything but `True`/`False`, `parse` raises only
    `NoInboundMessageError`. D9 records that such an adapter "is the entire cost of a future
    Twilio addition, not built in this change" — the `url` parameter is what that adapter would
    need and what this one ignores.
    """

    def verify_signature(
        self, *, raw_body: bytes, headers: Mapping[str, str], secret: str, url: str
    ) -> bool:
        """HMAC-SHA256 of `raw_body` under `secret`, against `X-Hub-Signature-256` (R3.2, D3a).

        `url` and every header but the signature are **ignored on purpose, not overlooked**:
        Meta's `X-Hub-Signature-256` is an HMAC over the request body alone. They are in the
        port's signature for provider generality (Twilio signs the callback URL too, D9), and
        an implementation that quietly folded the URL in here would reject every genuine
        request from Meta.

        Every failure path answers `False`. There are five, and none of them raises:

        1. **No signature header.** Rule 12(a) of `steering/security.md` makes a missing
           credential exactly as unauthenticated as a wrong one.
        2. **A header that is not `sha256=<hex>`** — no `=`, or an algorithm this adapter does
           not accept. Meta's superseded `X-Hub-Signature` used SHA-1; a body arriving with
           `sha1=` is refused rather than verified under a broken hash.
        3. **A digest of the wrong length**, refused before any HMAC is computed.
        4. **A blank `secret`.** This one matters most and is the least obvious: an HMAC under
           an empty key is a perfectly valid HMAC that *anybody* can compute, so a deployment
           with `WHATSAPP_APP_SECRET` unset would authenticate the whole internet. It fails
           closed instead.
        5. **A digest computed with another key** — the actual comparison, and the only branch
           that reaches it.

        The comparison is `secrets_match` (re-exported by `domain/whatsapp_webhook.py`), i.e.
        `hmac.compare_digest`, which rule 12(a) requires by name. Never `==`: a
        short-circuiting comparison leaks the length of the matching prefix, and against a
        digest an attacker can vary freely that leak is exploitable byte by byte.

        Hex is compared case-insensitively. `hexdigest()` and Meta both produce lower case, so
        this changes nothing in practice; it is here because the two spellings are the *same
        digest*, and rejecting a valid signature loses a guest's message, which is a worse
        outcome than accepting one whose letters arrived capitalised. Lower-casing a value the
        sender already knows costs nothing in constant-time terms.
        """
        presented = _header(headers, SIGNATURE_HEADER)
        if presented is None:
            return False
        algorithm, separator, digest = presented.strip().partition("=")
        if not separator or algorithm.lower() != SIGNATURE_ALGORITHM:
            return False
        if len(digest) != _DIGEST_HEX_LENGTH:
            return False
        if not secret.strip():
            return False
        expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return secrets_match(expected, digest.lower())

    def parse(
        self, *, raw_body: bytes, headers: Mapping[str, str]
    ) -> InboundWhatsAppMessage:
        """The first inbound text message in the body, or `NoInboundMessageError` (R3.5, R4.1).

        `headers` is accepted and unused: Meta carries no part of the message's shape there.

        **The whole traversal is defensive, and every step raises the same one error.** The
        input is unauthenticated JSON from the open internet — `verify_signature` has said it
        came from Meta, which is not the same as saying it has the fields this expects — and
        it is *also* the shape Meta uses for delivery and read receipts, where `value` carries
        `statuses` instead of `messages`. So "no message here" is ordinary traffic, and it
        arrives as `NoInboundMessageError` rather than as whichever built-in the traversal
        happened to hit first. Section 7 catches it and answers `202`.

        **A message with no `text.body` is also "no message here."** An image, a sticker, a
        location, a reaction: this change's pipeline classifies and answers text
        (`AIAdapter.classify_message` takes `content: str`), so there is nothing for it to
        process and nothing it should invent. It is refused here rather than persisted as an
        empty row.

        **Known limitation, and section 7 owns the consequence**: Meta may batch several
        messages into one webhook, and this returns the **first** one, because D9 fixes the
        port's return type at a single `InboundWhatsAppMessage`. The extras are dropped, and a
        warning counts them (a count, never their content). Handling a batch means widening
        the port, which is a design decision this change did not take.

        `received_at` is Meta's `timestamp` — Unix **seconds**, as a decimal string — read as
        UTC. A `timestamp` that is not an integer is malformed rather than late, so it is the
        same refusal as a missing one; `datetime.fromtimestamp` is given a `tz` explicitly,
        because without it Python would silently apply the container's local zone and produce a
        naive value that `InboundWhatsAppMessage` refuses.
        """
        try:
            payload = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            # `str(error)` from `json` embeds a slice of the document, which for this input is
            # the guest's message. Nothing about the original is carried into the refusal, and
            # `from error` keeps the detail in the traceback rather than in the response body.
            raise NoInboundMessageError(
                "the webhook body is not valid JSON, so it carries no inbound message"
            ) from error

        payload = _require_mapping(payload, "root")
        message, metadata = self._locate_message(payload)

        sender_phone = message.get("from")
        provider_message_id = message.get("id")
        timestamp = message.get("timestamp")
        text = _require_mapping(message.get("text", {}), "messages[].text").get("body")
        business_phone_number = metadata.get("phone_number_id")

        for field, value in (
            ("messages[].from", sender_phone),
            ("messages[].id", provider_message_id),
            ("messages[].timestamp", timestamp),
            ("messages[].text.body", text),
            ("metadata.phone_number_id", business_phone_number),
        ):
            if not isinstance(value, str) or not value.strip():
                raise NoInboundMessageError(
                    f"the webhook body's {field} is missing or not a non-empty string, so it "
                    "carries no inbound message this pipeline can process"
                )

        try:
            received_at = datetime.fromtimestamp(int(str(timestamp)), tz=UTC)
        except (ValueError, OverflowError, OSError) as error:
            raise NoInboundMessageError(
                "the webhook body's messages[].timestamp is not Unix seconds, so the message "
                "cannot be dated"
            ) from error

        return InboundWhatsAppMessage(
            sender_phone=str(sender_phone),
            provider_message_id=str(provider_message_id),
            text=str(text),
            received_at=received_at,
            business_phone_number=str(business_phone_number),
        )

    def _locate_message(
        self, payload: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
        """The first `messages[]` entry and the `metadata` of the `value` it came from.

        The two are returned together because they must come from the **same** `value`: the
        business number that received a message is the one in that change's metadata, and
        pairing a message with another change's metadata would attribute it to the wrong
        number. Nothing downstream could detect that, since `business_phone_number` is
        informational (R4.1) and never checked against anything.

        The `field == "messages"` discriminator Meta also sets on each change is deliberately
        not consulted: `value.messages` being present and non-empty is the same signal, and
        one check that reads the data actually used beats two that can disagree.
        """
        entries = _require_non_empty_list(payload.get("entry"), "entry")
        first_entry = _require_mapping(entries[0], "entry[]")
        changes = _require_non_empty_list(first_entry.get("changes"), "entry[].changes")
        value = _require_mapping(
            _require_mapping(changes[0], "entry[].changes[]").get("value"),
            "entry[].changes[].value",
        )
        # A status/read receipt lands here: `value` has `statuses` and no `messages`.
        messages = _require_non_empty_list(value.get("messages"), "value.messages")
        if len(messages) > 1:
            # A count and nothing else — see the module docstring. This is the known
            # limitation the `parse` docstring records, made visible in operations rather
            # than silent.
            logger.warning(
                "messaging.whatsapp_inbound_batch_truncated",
                extra={"message_count": len(messages)},
            )
        return (
            _require_mapping(messages[0], "value.messages[]"),
            _require_mapping(value.get("metadata"), "value.metadata"),
        )
