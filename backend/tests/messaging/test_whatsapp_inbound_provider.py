"""The inbound provider port and Meta's adapter for it (R3.1, R3.2, R3.5, R4.1; design D9, D3a).

Three things are asserted here, and the middle one is why this file is long:

1. **The port's shape**, the way `test_ports.py` pins the other three: two methods, both
   synchronous, both keyword-only, and `MetaInboundAdapter`'s signatures identical to them.
   A port's absences are a decision, and absences rot silently.
2. **Every path through `verify_signature` answers `False` rather than raising**, and the one
   that answers `True` does so over the *raw bytes*. This is the authentication of an
   anonymous, internet-facing route: a path that raises where it should say "no" is how a
   caller ends up returning two distinguishable statuses (design D4), and a path that says
   "yes" on a body it did not really verify is the whole vulnerability.
3. **Every malformed body reaches the caller as `NoInboundMessageError`**, never as a
   `KeyError`, an `IndexError` or a `TypeError` — because Meta posts delivery receipts to this
   same URL, so "no message here" is ordinary traffic that section 7 answers `202` to, and it
   cannot tell that apart from a bug of ours if the traversal leaks whichever built-in it hit.

The signatures in this file are computed with `hmac` rather than hard-coded, which is the only
way a signature test can be true of the *body it accompanies*: a literal digest would keep
passing after the payload beside it changed.
"""

import ast
import dataclasses
import hashlib
import hmac
import inspect
import json
import textwrap
from datetime import UTC, datetime
from typing import Any

import pytest

from app.messaging.domain.exceptions import (
    MessagingDomainError,
    NoInboundMessageError,
)
from app.messaging.domain.ports import WhatsAppInboundProviderAdapter
from app.messaging.domain.value_objects import InboundWhatsAppMessage
from app.messaging.domain.whatsapp_webhook import secrets_match
from app.messaging.infrastructure.whatsapp_providers import (
    SIGNATURE_HEADER,
    MetaInboundAdapter,
)

APP_SECRET = "an-app-secret-from-metas-dashboard"
CALLBACK_URL = "https://api.example.com/api/v1/webhooks/whatsapp/opaque-token"

SENDER_PHONE = "34600111222"
PROVIDER_MESSAGE_ID = "wamid.HBgLMzQ2MDAxMTEyMjIVAgASGBQzQTVGMkQ0RjZDN0E4QjlEMEUxRgA="
GUEST_TEXT = "Hola, tengo una pregunta sobre el check-in"
TIMESTAMP_SECONDS = 1699999999
PHONE_NUMBER_ID = "1234567890"
DISPLAY_PHONE_NUMBER = "15551234567"


def message_payload(**overrides: Any) -> dict[str, Any]:
    """One `messages[]` entry as Meta actually sends it (design D9)."""
    message: dict[str, Any] = {
        "from": SENDER_PHONE,
        "id": PROVIDER_MESSAGE_ID,
        "timestamp": str(TIMESTAMP_SECONDS),
        "type": "text",
        "text": {"body": GUEST_TEXT},
    }
    message.update(overrides)
    return message


def webhook_payload(
    *, messages: list[Any] | None = None, **value_overrides: Any
) -> dict[str, Any]:
    """A whole `whatsapp_business_account` webhook, four levels deep, as in design D9."""
    value: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "metadata": {
            "display_phone_number": DISPLAY_PHONE_NUMBER,
            "phone_number_id": PHONE_NUMBER_ID,
        },
        "contacts": [{"profile": {"name": "Ada"}, "wa_id": SENDER_PHONE}],
        "messages": [message_payload()] if messages is None else messages,
    }
    value.update(value_overrides)
    return {
        "object": "whatsapp_business_account",
        "entry": [{"id": "WABA_ID", "changes": [{"value": value, "field": "messages"}]}],
    }


def raw(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload).encode()


def signature_for(body: bytes, secret: str = APP_SECRET) -> str:
    """`sha256=<hex>`, computed the way Meta computes it (design D3a)."""
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def headers_for(body: bytes, secret: str = APP_SECRET) -> dict[str, str]:
    return {"Content-Type": "application/json", SIGNATURE_HEADER: signature_for(body, secret)}


@pytest.fixture
def adapter() -> MetaInboundAdapter:
    return MetaInboundAdapter()


# --- 4.1 the port's shape ------------------------------------------------------------------


def declared_methods(protocol: type) -> set[str]:
    """Every public method reachable on the protocol, `Protocol` itself discounted.

    `dir()` and not `vars()`, for the reason `test_ports.py` records at length: `vars` sees
    only this class body, so a method inherited from another `Protocol` base would be
    invisible here while being perfectly callable.
    """
    inherited = set(dir(type("_Bare", (), {}))) | set(dir(object))
    return {
        name
        for name in dir(protocol)
        if not name.startswith("_") and name not in inherited
    }


def test_the_inbound_provider_port_declares_exactly_two_methods() -> None:
    """D9 declares "exactly two methods", and the absence of a third is the decision.

    A `fetch_media`, a `send_read_receipt` or an `acknowledge` would each drag a second Graph
    API call — and a credential — behind a port whose whole purpose is that the provider stops
    here.
    """
    assert declared_methods(WhatsAppInboundProviderAdapter) == {"verify_signature", "parse"}


def test_neither_port_method_is_a_coroutine() -> None:
    """One is an HMAC over bytes in memory, the other a `json.loads`; neither does I/O.

    Pinned because `async` is the reflex in this codebase's ports, and a coroutine here would
    force every implementer into an `await` it has nothing to await on.
    """
    for name in ("verify_signature", "parse"):
        method = getattr(WhatsAppInboundProviderAdapter, name)
        assert not inspect.iscoroutinefunction(method)


@pytest.mark.parametrize(
    ("method_name", "expected_parameters"),
    [
        ("verify_signature", ["raw_body", "headers", "secret", "url"]),
        ("parse", ["raw_body", "headers"]),
    ],
)
def test_every_port_argument_is_keyword_only(
    method_name: str, expected_parameters: list[str]
) -> None:
    """The house style, and here it also stops `verify_signature(body, headers, url, secret)`
    from being written by positional accident — swapping the last two would verify a signature
    against the URL as the key and answer `False` for every genuine request."""
    signature = inspect.signature(getattr(WhatsAppInboundProviderAdapter, method_name))
    parameters = [name for name in signature.parameters if name != "self"]
    assert parameters == expected_parameters
    for name in parameters:
        assert signature.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_the_meta_adapter_signatures_are_the_ports_signatures() -> None:
    """Liskov, checked rather than hoped for: pyright sees this, the suite would not.

    `MetaInboundAdapter` is wired in as a `WhatsAppInboundProviderAdapter` by section 7, so a
    renamed or reordered keyword here is a `TypeError` at the first real webhook and nowhere
    earlier.
    """
    for name in ("verify_signature", "parse"):
        assert inspect.signature(getattr(MetaInboundAdapter, name)) == inspect.signature(
            getattr(WhatsAppInboundProviderAdapter, name)
        )


def test_the_meta_adapter_needs_no_construction_arguments(
    adapter: MetaInboundAdapter,
) -> None:
    """Stateless, and carrying no credential: the secret arrives per call (D9)."""
    assert not [
        name for name in vars(adapter) if not name.startswith("__")
    ], "the adapter holds state, so a credential could be captured on it"


# --- 4.3 the domain-side webhook primitives ------------------------------------------------


def test_the_comparison_primitive_is_the_original_and_not_a_reimplementation() -> None:
    """R3.1/R3.2: one comparison — re-exported, never restated.

    Identity and not merely equal behaviour, because that is the property that matters: a
    second copy of the comparison is how one of them later ends up as `==`.
    """
    from app.integrations.domain import webhook_auth

    assert secrets_match is webhook_auth.secrets_match


def test_the_module_re_exports_exactly_the_one_primitive_the_whatsapp_path_uses() -> None:
    """`generate_header_secret` is deliberately absent (design D3a).

    The WhatsApp route authenticates with Meta's real signature, so a per-tenant header secret
    re-exported next to `secrets_match` would be a second, weaker door onto the same route.
    `generate_webhook_token`/`hash_webhook_token` were dropped 2026-09-02 (design D3, task
    4.6): the topology moved to one shared Meta App with a single fixed webhook route, tenant
    resolved by a `phone_number_id`-to-tenant lookup instead of a per-tenant route token, so
    neither had a consumer left.
    """
    from app.messaging.domain import whatsapp_webhook

    assert sorted(whatsapp_webhook.__all__) == ["secrets_match"]
    assert not hasattr(whatsapp_webhook, "generate_header_secret")
    assert not hasattr(whatsapp_webhook, "generate_webhook_token")
    assert not hasattr(whatsapp_webhook, "hash_webhook_token")


# --- 4.4 verify_signature: the accepting path ----------------------------------------------


def test_a_signature_meta_really_computed_is_accepted(adapter: MetaInboundAdapter) -> None:
    body = raw(webhook_payload())
    assert (
        adapter.verify_signature(
            raw_body=body,
            headers=headers_for(body),
            secret=APP_SECRET,
            url=CALLBACK_URL,
        )
        is True
    )


def test_the_answer_does_not_depend_on_the_url(adapter: MetaInboundAdapter) -> None:
    """R3.2/D9: `url` is in the port for Twilio's future signature, and Meta's does not use it.

    An implementation that folded the URL into the HMAC would reject every genuine request
    from Meta, and the mistake would look like a credential problem.
    """
    body = raw(webhook_payload())
    headers = headers_for(body)
    answers = {
        adapter.verify_signature(
            raw_body=body, headers=headers, secret=APP_SECRET, url=candidate
        )
        for candidate in (CALLBACK_URL, "http://other.example/x", "", "not a url at all")
    }
    assert answers == {True}


def test_the_other_headers_do_not_change_the_answer(adapter: MetaInboundAdapter) -> None:
    body = raw(webhook_payload())
    headers = headers_for(body) | {
        "X-Hub-Signature": "sha1=" + "0" * 40,
        "User-Agent": "facebookplatform/1.0",
    }
    assert (
        adapter.verify_signature(
            raw_body=body, headers=headers, secret=APP_SECRET, url=CALLBACK_URL
        )
        is True
    )


@pytest.mark.parametrize(
    "header_name",
    ["X-Hub-Signature-256", "x-hub-signature-256", "X-HUB-SIGNATURE-256"],
)
def test_the_signature_header_is_found_whatever_its_capitalisation(
    adapter: MetaInboundAdapter, header_name: str
) -> None:
    """HTTP header names are case-insensitive, and the mapping reaches this adapter from two
    kinds of caller: Starlette's own case-insensitive `Headers`, and a plain `dict` built by
    section 7 or by a test. Lower case is what actually travels over HTTP/2.

    Guaranteed by the adapter rather than by whoever wires it, so section 7's router cannot
    break authentication by handing over a differently-spelled dict.
    """
    body = raw(webhook_payload())
    headers = {header_name: signature_for(body)}
    assert (
        adapter.verify_signature(
            raw_body=body, headers=headers, secret=APP_SECRET, url=CALLBACK_URL
        )
        is True
    )


def test_a_hex_digest_in_upper_case_is_the_same_digest(
    adapter: MetaInboundAdapter,
) -> None:
    """Hex is case-insensitive as a *value*, and rejecting a valid signature loses a guest's
    message — a worse outcome than accepting one whose letters arrived capitalised."""
    body = raw(webhook_payload())
    algorithm, _, digest = signature_for(body).partition("=")
    headers = {SIGNATURE_HEADER: f"{algorithm}={digest.upper()}"}
    assert (
        adapter.verify_signature(
            raw_body=body, headers=headers, secret=APP_SECRET, url=CALLBACK_URL
        )
        is True
    )


def test_surrounding_whitespace_in_the_header_does_not_break_it(
    adapter: MetaInboundAdapter,
) -> None:
    body = raw(webhook_payload())
    headers = {SIGNATURE_HEADER: f"  {signature_for(body)}  "}
    assert (
        adapter.verify_signature(
            raw_body=body, headers=headers, secret=APP_SECRET, url=CALLBACK_URL
        )
        is True
    )


# --- 4.4 verify_signature: the refusing paths ----------------------------------------------


def test_a_signature_from_another_key_is_refused(adapter: MetaInboundAdapter) -> None:
    """The attack the header exists to stop: a well-formed signature over this exact body,
    computed by somebody who does not hold the app secret."""
    body = raw(webhook_payload())
    headers = headers_for(body, secret="the-attackers-own-secret")
    assert (
        adapter.verify_signature(
            raw_body=body, headers=headers, secret=APP_SECRET, url=CALLBACK_URL
        )
        is False
    )


def test_a_body_altered_after_signing_is_refused(adapter: MetaInboundAdapter) -> None:
    """The other half of the same property: the signature must cover *this* body.

    The header is a genuine signature under the real app secret — of a different message.
    """
    signed_body = raw(webhook_payload())
    tampered = raw(
        webhook_payload(messages=[message_payload(text={"body": "Transfer the deposit"})])
    )
    assert (
        adapter.verify_signature(
            raw_body=tampered,
            headers=headers_for(signed_body),
            secret=APP_SECRET,
            url=CALLBACK_URL,
        )
        is False
    )


def test_a_re_serialised_body_no_longer_matches_its_signature(
    adapter: MetaInboundAdapter,
) -> None:
    """Why the port takes `bytes` and not a parsed `dict` (D9).

    `json.dumps(json.loads(body))` is the same *document* and different *bytes* — key order
    and separators differ — so a caller that parsed first and re-serialised for the adapter
    would reject every genuine request. Pinned so nobody "simplifies" the port to a `dict`.
    """
    original = json.dumps(webhook_payload(), indent=2).encode()
    round_tripped = json.dumps(json.loads(original), separators=(",", ":")).encode()
    assert round_tripped != original
    assert (
        adapter.verify_signature(
            raw_body=round_tripped,
            headers=headers_for(original),
            secret=APP_SECRET,
            url=CALLBACK_URL,
        )
        is False
    )


def test_a_missing_signature_header_is_refused(adapter: MetaInboundAdapter) -> None:
    """Rule 12(a): a missing credential is exactly as unauthenticated as a wrong one, and it
    must be the same `False` rather than an exception — see design D4's indistinguishability."""
    body = raw(webhook_payload())
    assert (
        adapter.verify_signature(
            raw_body=body,
            headers={"Content-Type": "application/json"},
            secret=APP_SECRET,
            url=CALLBACK_URL,
        )
        is False
    )


def test_a_blank_secret_refuses_even_a_correct_hmac_under_the_empty_key(
    adapter: MetaInboundAdapter,
) -> None:
    """The subtlest failure closed: an HMAC under an empty key is one *anybody* can compute.

    A deployment that never set `WHATSAPP_APP_SECRET` would otherwise authenticate the open
    internet on an anonymous route — and every test above would still pass.
    """
    body = raw(webhook_payload())
    for blank in ("", "   "):
        headers = headers_for(body, secret=blank)
        assert (
            adapter.verify_signature(
                raw_body=body, headers=headers, secret=blank, url=CALLBACK_URL
            )
            is False
        )


@pytest.mark.parametrize(
    ("case", "header_value"),
    [
        ("no separator at all", "0" * 64),
        ("no algorithm", "=" + "0" * 64),
        ("the superseded sha1 of the older header", "sha1=" + "0" * 40),
        ("an algorithm nobody signs with", "md5=" + "0" * 32),
        ("a digest one character short", "sha256=" + "0" * 63),
        ("a digest one character long", "sha256=" + "0" * 65),
        ("an empty digest", "sha256="),
        ("a base64 digest instead of hex", "sha256=Zm9vYmFyYmF6"),
        ("non-hex characters of the right length", "sha256=" + "z" * 64),
        ("non-ascii characters of the right length", "sha256=" + "ñ" * 64),
        ("the word itself", "sha256=sha256"),
        ("nothing", ""),
        ("only whitespace", "   "),
    ],
)
def test_a_malformed_signature_header_is_refused_and_never_raises(
    adapter: MetaInboundAdapter, case: str, header_value: str
) -> None:
    """Every one of these is `False`, and none of them is an exception.

    The non-ASCII row is not decoration: `hmac.compare_digest` rejects a non-ASCII `str`
    outright, so an implementation that skipped the encode `secrets_match` does would raise
    here — a crash on an anonymous route, where the answer should have been "no".
    """
    body = raw(webhook_payload())
    assert (
        adapter.verify_signature(
            raw_body=body,
            headers={SIGNATURE_HEADER: header_value},
            secret=APP_SECRET,
            url=CALLBACK_URL,
        )
        is False
    ), case


def test_the_algorithm_in_the_header_is_checked_and_not_assumed(
    adapter: MetaInboundAdapter,
) -> None:
    """A digest that IS the correct HMAC-SHA256, announced under another algorithm.

    The length rows in the table above cannot reach this: a real `sha1=` digest is 40
    characters and a real `md5=` is 32, so both die on the length check whatever the
    algorithm check does. This one is 64 characters and correct, so the *only* thing that can
    refuse it is reading the algorithm — and reading it is what stops Meta's superseded
    `X-Hub-Signature` (SHA-1) from being accepted as if it were the SHA-256 one, which is the
    header confusion design D3a picked the newer header to avoid.
    """
    body = raw(webhook_payload())
    _, _, digest = signature_for(body).partition("=")
    assert len(digest) == 64
    for algorithm in ("sha1", "md5", "sha512", "none", "SHA1"):
        assert (
            adapter.verify_signature(
                raw_body=body,
                headers={SIGNATURE_HEADER: f"{algorithm}={digest}"},
                secret=APP_SECRET,
                url=CALLBACK_URL,
            )
            is False
        ), algorithm


def test_a_wrong_digest_of_exactly_the_right_shape_is_refused(
    adapter: MetaInboundAdapter,
) -> None:
    """The interesting negative: 64 hex characters, so only the content differs — the case a
    length check alone would wave through."""
    body = raw(webhook_payload())
    _, _, digest = signature_for(body).partition("=")
    flipped = ("1" if digest[0] == "0" else "0") + digest[1:]
    assert len(flipped) == len(digest)
    assert (
        adapter.verify_signature(
            raw_body=body,
            headers={SIGNATURE_HEADER: f"sha256={flipped}"},
            secret=APP_SECRET,
            url=CALLBACK_URL,
        )
        is False
    )


def test_an_empty_body_with_its_own_valid_signature_is_still_authentic(
    adapter: MetaInboundAdapter,
) -> None:
    """Authentication and interpretation are separate steps (D9's two methods).

    `verify_signature` says who sent the bytes; `parse` says whether they mean anything. An
    adapter that refused an empty body *here* would be answering the second question in the
    first method, and section 7 could no longer tell "not from Meta" (404) from "from Meta,
    nothing to do" (202).
    """
    assert (
        adapter.verify_signature(
            raw_body=b"",
            headers=headers_for(b""),
            secret=APP_SECRET,
            url=CALLBACK_URL,
        )
        is True
    )
    with pytest.raises(NoInboundMessageError):
        adapter.parse(raw_body=b"", headers={})


# --- 4.4 verify_signature: constant time ---------------------------------------------------


def _equality_comparisons(function: object) -> list[ast.Compare]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(function)))  # type: ignore[arg-type]
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops)
    ]


def test_the_verdict_is_returned_by_the_one_constant_time_comparison(
    adapter: MetaInboundAdapter,
) -> None:
    """Rule 12(a) and R3.2, pinned by the *shape* of the code rather than by a name in it.

    A timing assertion in a unit suite is dominated by scheduling noise, so what this checks
    is the thing that actually regresses: somebody replacing the comparison with `==`. It is
    deliberately not a substring search for `"compare_digest"` — a guard by forbidden or
    required spelling is a guard a rename walks past (and `verify_signature` does not call
    `compare_digest` itself; it goes through `secrets_match`, which is the point). So this
    fixes the exact shape: the value the method returns on its one reachable success path is a
    call to `secrets_match`.
    """
    source = textwrap.dedent(inspect.getsource(MetaInboundAdapter.verify_signature))
    returns = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Return) and isinstance(node.value, ast.Call)
    ]
    assert len(returns) == 1, "verify_signature returns a computed value in exactly one place"
    called = returns[0].value
    assert isinstance(called, ast.Call) and isinstance(called.func, ast.Name)
    assert called.func.id == "secrets_match"


def test_no_secret_derived_value_is_ever_compared_with_an_equality_operator() -> None:
    """The other half: `secrets_match` being called does not help if a short-circuiting `==`
    already decided the answer above it.

    Only bare names are inspected, so `len(digest) != 64` — a comparison of a *length*, which
    is public and which the caller can vary freely — stays legal, while `digest == expected`
    in any order does not.
    """
    secret_derived = {"expected", "digest", "presented"}
    for comparison in _equality_comparisons(MetaInboundAdapter.verify_signature):
        operands = [comparison.left, *comparison.comparators]
        offenders = {
            node.id
            for node in operands
            if isinstance(node, ast.Name) and node.id in secret_derived
        }
        assert not offenders, (
            f"verify_signature compares {sorted(offenders)} with == or !=; rule 12(a) of "
            "steering/security.md requires hmac.compare_digest for this comparison"
        )


def test_the_comparison_it_delegates_to_is_the_constant_time_one() -> None:
    """One link further along the same chain, so this file does not merely assume it.

    `tests/integrations/test_webhook_auth.py` owns the full contract of `secrets_match`; this
    pins the property `verify_signature` depends on.
    """
    assert "compare_digest" in inspect.getsource(secrets_match)


# --- 4.4 parse: the mapping ----------------------------------------------------------------


def test_parse_maps_every_field_of_the_nested_body(adapter: MetaInboundAdapter) -> None:
    """R4.1/D9, field by field rather than by comparing whole objects — a positional slip
    between two `str` fields would survive an equality check against a fixture built the same
    wrong way."""
    parsed = adapter.parse(raw_body=raw(webhook_payload()), headers={})

    assert isinstance(parsed, InboundWhatsAppMessage)
    assert parsed.sender_phone == SENDER_PHONE
    assert parsed.provider_message_id == PROVIDER_MESSAGE_ID
    assert parsed.text == GUEST_TEXT
    assert parsed.received_at == datetime(2023, 11, 14, 22, 13, 19, tzinfo=UTC)
    assert parsed.business_phone_number == PHONE_NUMBER_ID


def test_the_sender_phone_is_metas_bare_digits_with_no_provider_prefix(
    adapter: MetaInboundAdapter,
) -> None:
    """D9 spells this out — Meta's `from` has "no `whatsapp:` prefix unlike Twilio's".

    Section 5 normalises it (`normalize_phone_e164("+" + wa_id)`), so a prefix invented here
    would travel into a guest lookup that then matches nobody.
    """
    parsed = adapter.parse(raw_body=raw(webhook_payload()), headers={})
    assert parsed.sender_phone == "34600111222"
    assert not parsed.sender_phone.startswith("whatsapp:")
    assert not parsed.sender_phone.startswith("+")


def test_the_business_number_is_the_graph_api_id_and_not_the_display_number(
    adapter: MetaInboundAdapter,
) -> None:
    """`value.metadata.phone_number_id`, per D9 — the identifier the outbound side already
    identifies itself with (`WHATSAPP_PHONE_NUMBER_ID`), not the human-readable number.

    Both keys sit side by side in the same object, so picking the wrong one is a one-word slip
    that nothing downstream would notice: R4.1 makes this field informational, so it is never
    checked against anything.
    """
    parsed = adapter.parse(raw_body=raw(webhook_payload()), headers={})
    assert parsed.business_phone_number == PHONE_NUMBER_ID
    assert parsed.business_phone_number != DISPLAY_PHONE_NUMBER


def test_the_timestamp_is_read_as_unix_seconds_in_utc(adapter: MetaInboundAdapter) -> None:
    """Seconds and not milliseconds, and aware and not naive.

    Read as milliseconds the message would be dated in 1970; read without `tz` it would carry
    the container's local zone as a naive value, and `received_at` is compared against the 24h
    session window (design D2) where that is a `TypeError` rather than an answer.
    """
    parsed = adapter.parse(raw_body=raw(webhook_payload()), headers={})
    assert parsed.received_at.tzinfo is not None
    assert parsed.received_at.utcoffset() == datetime(2023, 1, 1, tzinfo=UTC).utcoffset()
    assert parsed.received_at.timestamp() == TIMESTAMP_SECONDS


def test_parse_ignores_the_headers(adapter: MetaInboundAdapter) -> None:
    """Meta carries no part of the message's shape in a header; the parameter is the port's
    provider-generality, like `url` on the other method."""
    body = raw(webhook_payload())
    assert adapter.parse(raw_body=body, headers={}) == adapter.parse(
        raw_body=body, headers={"X-Hub-Signature-256": "sha256=" + "0" * 64}
    )


def test_a_batched_webhook_returns_the_first_message_and_counts_the_rest(
    adapter: MetaInboundAdapter, caplog: pytest.LogCaptureFixture
) -> None:
    """The known limitation D9's return type imposes, made visible instead of silent.

    Meta may batch several messages into one webhook and the port returns a single
    `InboundWhatsAppMessage`, so the extras are dropped. The warning carries a **count and
    nothing else** — rule 11 of `steering/security.md`: the dropped messages are the guest's
    words, and this route's input is unauthenticated text from the open internet.
    """
    second = message_payload(id="wamid.SECOND", text={"body": "y una segunda pregunta"})
    body = raw(webhook_payload(messages=[message_payload(), second]))

    with caplog.at_level("WARNING"):
        parsed = adapter.parse(raw_body=body, headers={})

    assert parsed.provider_message_id == PROVIDER_MESSAGE_ID
    records = [
        record
        for record in caplog.records
        if record.msg == "messaging.whatsapp_inbound_batch_truncated"
    ]
    assert len(records) == 1
    assert getattr(records[0], "message_count") == 2
    assert "y una segunda pregunta" not in caplog.text
    assert GUEST_TEXT not in caplog.text
    assert SENDER_PHONE not in caplog.text


def test_the_message_and_its_business_number_come_from_the_same_change(
    adapter: MetaInboundAdapter,
) -> None:
    """`_locate_message` returns the pair together for this reason.

    Pairing a message with another change's metadata would attribute it to the wrong business
    number, and since `business_phone_number` is informational (R4.1) nothing downstream could
    ever detect it.
    """
    payload = webhook_payload()
    other_change = {
        "value": {
            "messaging_product": "whatsapp",
            "metadata": {
                "display_phone_number": "15559999999",
                "phone_number_id": "9999999999",
            },
            "statuses": [{"id": "wamid.OTHER", "status": "read"}],
        },
        "field": "statuses"
    }
    payload["entry"][0]["changes"].append(other_change)

    parsed = adapter.parse(raw_body=raw(payload), headers={})
    assert parsed.business_phone_number == PHONE_NUMBER_ID


# --- 4.4 parse: the refusing paths ---------------------------------------------------------

#: Bodies Meta really sends, or really could, that carry no inbound text message. The first is
#: the one that motivated the typed error: a delivery receipt for a message *we* sent, posted
#: to the same URL as a real message, many times per conversation.
NO_MESSAGE_BODIES: list[tuple[str, object]] = [
    (
        "a delivery/read receipt: statuses where messages would be",
        {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "WABA_ID",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                                "statuses": [
                                    {
                                        "id": "wamid.OUTBOUND",
                                        "status": "delivered",
                                        "timestamp": "1699999999",
                                        "recipient_id": SENDER_PHONE,
                                    }
                                ],
                            },
                            "field": "statuses",
                        }
                    ],
                }
            ],
        },
    ),
    ("no entry key at all", {"object": "whatsapp_business_account"}),
    ("an empty entry list", {"object": "whatsapp_business_account", "entry": []}),
    ("entry is not a list", {"entry": {"id": "WABA_ID"}}),
    ("an entry that is not an object", {"entry": ["WABA_ID"]}),
    ("no changes key", {"entry": [{"id": "WABA_ID"}]}),
    ("an empty changes list", {"entry": [{"id": "WABA_ID", "changes": []}]}),
    ("a change with no value", {"entry": [{"changes": [{"field": "messages"}]}]}),
    ("a value that is not an object", {"entry": [{"changes": [{"value": "messages"}]}]}),
    (
        "a value with no messages key",
        {
            "entry": [
                {
                    "changes": [
                        {"value": {"metadata": {"phone_number_id": PHONE_NUMBER_ID}}}
                    ]
                }
            ]
        },
    ),
    (
        "an empty messages list",
        {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                                "messages": [],
                            }
                        }
                    ]
                }
            ]
        },
    ),
    ("a message that is not an object", webhook_payload(messages=["hola"])),
    ("no metadata beside the message", {"entry": [{"changes": [{"value": {"messages": [message_payload()]}}]}]}),
    ("a root that is a list", [webhook_payload()]),
    ("a root that is a string", "whatsapp_business_account"),
    ("a root that is null", None),
]

#: Bodies whose *message* is there but unusable. Every one of these is a real Meta webhook.
UNUSABLE_MESSAGE_BODIES: list[tuple[str, object]] = [
    ("an image with no text body", webhook_payload(messages=[{k: v for k, v in message_payload(type="image", image={"id": "media-id"}).items() if k != "text"}])),
    ("a sticker with no text body", webhook_payload(messages=[{k: v for k, v in message_payload(type="sticker").items() if k != "text"}])),
    ("a text object with no body key", webhook_payload(messages=[message_payload(text={})])),
    ("a text that is a string rather than an object", webhook_payload(messages=[message_payload(text=GUEST_TEXT)])),
    ("an empty text body", webhook_payload(messages=[message_payload(text={"body": ""})])),
    ("a whitespace-only text body", webhook_payload(messages=[message_payload(text={"body": "   "})])),
    ("no from", webhook_payload(messages=[{k: v for k, v in message_payload().items() if k != "from"}])),
    ("a blank from", webhook_payload(messages=[message_payload(**{"from": ""})])),
    ("no id", webhook_payload(messages=[{k: v for k, v in message_payload().items() if k != "id"}])),
    ("a blank id, the deduplication key of R3.5", webhook_payload(messages=[message_payload(id="")])),
    ("no timestamp", webhook_payload(messages=[{k: v for k, v in message_payload().items() if k != "timestamp"}])),
    ("a timestamp that is not a number", webhook_payload(messages=[message_payload(timestamp="not-a-number")])),
    ("a timestamp that is an integer rather than Meta's string", webhook_payload(messages=[message_payload(timestamp=TIMESTAMP_SECONDS)])),
    ("a timestamp far outside any representable date", webhook_payload(messages=[message_payload(timestamp="9" * 30)])),
    ("no phone_number_id in the metadata", webhook_payload(metadata={"display_phone_number": DISPLAY_PHONE_NUMBER})),
    ("a blank phone_number_id", webhook_payload(metadata={"phone_number_id": ""})),
    ("metadata that is not an object", webhook_payload(metadata="1234567890")),
]


@pytest.mark.parametrize(
    ("case", "payload"),
    NO_MESSAGE_BODIES + UNUSABLE_MESSAGE_BODIES,
    ids=[case for case, _ in NO_MESSAGE_BODIES + UNUSABLE_MESSAGE_BODIES],
)
def test_a_body_with_no_usable_message_raises_the_one_typed_error(
    adapter: MetaInboundAdapter, case: str, payload: object
) -> None:
    """The property section 7 depends on, and the reason `NoInboundMessageError` exists.

    Not one of these may arrive as a `KeyError`, an `IndexError` or a `TypeError`: the caller
    has to answer `202` to "nothing to do" (Meta redelivers on any non-2xx, so a status
    receipt answered 500 retries forever) and it cannot tell that apart from a bug of ours
    against whichever built-in the traversal happened to hit first.
    """
    with pytest.raises(NoInboundMessageError):
        adapter.parse(raw_body=json.dumps(payload).encode(), headers={})


@pytest.mark.parametrize(
    ("case", "body"),
    [
        ("not JSON at all", b"who is there"),
        ("truncated JSON", b'{"entry": [{"changes":'),
        ("an empty body", b""),
        ("bytes that are not valid UTF-8", b"\xff\xfe{}"),
        ("a bare number", b"7"),
        ("form-encoded, as Twilio would send", b"From=%2B34600111222&Body=Hola"),
    ],
    ids=lambda value: value if isinstance(value, str) else "",
)
def test_a_body_that_is_not_a_json_object_raises_the_one_typed_error(
    adapter: MetaInboundAdapter, case: str, body: bytes
) -> None:
    with pytest.raises(NoInboundMessageError):
        adapter.parse(raw_body=body, headers={})


def test_the_typed_error_is_a_messaging_domain_error_the_api_can_translate() -> None:
    """So an escape is a named 422 and not an unmapped 500 (`test_errors.py` owns the row)."""
    assert issubclass(NoInboundMessageError, MessagingDomainError)


@pytest.mark.parametrize(
    ("case", "payload"),
    NO_MESSAGE_BODIES + UNUSABLE_MESSAGE_BODIES,
    ids=[case for case, _ in NO_MESSAGE_BODIES + UNUSABLE_MESSAGE_BODIES],
)
def test_the_refusal_quotes_neither_the_guests_words_nor_their_number(
    adapter: MetaInboundAdapter, case: str, payload: object
) -> None:
    """Rule 11 of `steering/security.md`, over the whole set rather than one sample.

    `api/errors.py` renders `str(exc)` into a 422 body and every log line carries it, so a
    refusal that echoed the body would push the guest's message into both — from a route with
    no authentication in front of it. The messages name the field and the expected shape,
    which is the discipline `domain/value_objects.py` states for this module.
    """
    with pytest.raises(NoInboundMessageError) as raised:
        adapter.parse(raw_body=json.dumps(payload).encode(), headers={})

    message = str(raised.value)
    assert GUEST_TEXT not in message
    assert SENDER_PHONE not in message
    assert PROVIDER_MESSAGE_ID not in message


def test_json_decoding_never_leaks_the_document_into_the_refusal(
    adapter: MetaInboundAdapter,
) -> None:
    """`json`'s own `JSONDecodeError` embeds a slice of the input, which here is the guest's
    message. The refusal must be the adapter's sentence and not the library's."""
    with pytest.raises(NoInboundMessageError) as raised:
        adapter.parse(raw_body=f'{{"text": "{GUEST_TEXT}"'.encode(), headers={})

    assert GUEST_TEXT not in str(raised.value)


# --- 4.2 the value object ------------------------------------------------------------------


def test_parse_returns_a_frozen_value_object(adapter: MetaInboundAdapter) -> None:
    parsed = adapter.parse(raw_body=raw(webhook_payload()), headers={})
    with pytest.raises(dataclasses.FrozenInstanceError):
        parsed.text = "something else"  # type: ignore[misc]


def test_the_value_object_carries_exactly_the_five_fields_of_the_design() -> None:
    """D9 lists them, and a sixth would be a provider detail crossing the boundary this class
    exists to be — `type`, `wa_id`, the contact's profile name, the raw payload."""
    assert [field.name for field in InboundWhatsAppMessage.__dataclass_fields__.values()] == [
        "sender_phone",
        "provider_message_id",
        "text",
        "received_at",
        "business_phone_number",
    ]
