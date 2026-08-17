"""The closed catalogue an automatic reply is drawn from (R2.6, R3.3; design D7).

**Constants, with no interpolation hole anywhere.** No `{...}`, no `%s`, no `f`-string, and
`tests/messaging/test_templates.py` walks the catalogue and refuses one — calqued on
`tests/maintenance/test_classifier_vocabulary_contract.py`.

**What that buys, stated precisely, because it is easy to claim more.** It makes it
impossible for *the guest's own words* to end up in a reply: there is nowhere to put them. It
does **not** make it impossible for a person to hand-write a template that breaks rule 10 of
`sdd/steering/security.md` — "nunca prometer reembolsos/compensaciones, admitir
responsabilidad, dar asesoría legal, revelar datos de otros huéspedes, inventar
códigos/disponibilidad/precios, ni afirmar que un técnico va sin assignment real". Nothing
mechanical can: a constant is whatever someone typed. What guards the *wording* is review,
plus the phrase list in `test_no_template_can_promise_what_rule_10_forbids`, which is a net
and not a guarantee. Raised by the security panel of sections 3-4, which found this paragraph
claiming the stronger thing.

It is also what sustains the closed form of `messages.content` when the writer is **ours**
(R3.3, D16) — with the same care about how much is claimed. `GeneratedResponse` refuses a
`content` outside the vocabulary *the adapter declares*, which `steering/security.md` records
as the admission condition and explicitly not the guarantee ("un adaptador que construya su
`vocabulary` a partir de su propia salida satisface la comprobación trivialmente"). What
closes it for this change is that the only adapter shipped declares `RESPONSE_VOCABULARY`
below, and that `assert_in_catalogue` checks the value about to be persisted against **this**
catalogue rather than against whatever the adapter declared. The pipeline calls it before
sending and before building the row.

**Eleven intents and not fourteen.** `REFUND_OR_COMPENSATION`, `EMERGENCY` and `UNKNOWN`
have no template, because R2.7 forbids even calling `generate_response` for them. The
absence is the second net of that prohibition, and a loud `KeyError` for anyone who steps
over the first.

What a reply may say, and it is narrow on purpose: that we received the message and that a
person will answer. Notably absent, and each for a named reason — no apology (that edges
toward admitting responsibility), no WiFi password or door code (rule 3 values, which rule 4
keeps out of any rendered message), no price, no availability, and never that a technician is
on the way.
"""

from collections.abc import Mapping

from app.messaging.domain.enums import MessageIntent
from app.messaging.domain.exceptions import MessagingValidationError

#: Bumped whenever a template changes. Persisted alongside each automatic reply in
#: `messages.metadata["template_version"]` (D15), so an operator reading an old row can tell
#: which wording the guest actually received.
TEMPLATE_CATALOGUE_VERSION = "2026-08-16.1"

#: The three intents that never get an automatic reply (R2.7). Declared as a constant so the
#: prohibition can be asserted rather than inferred from a gap in the mapping below.
INTENTS_WITHOUT_TEMPLATE = frozenset(
    {
        MessageIntent.REFUND_OR_COMPENSATION,
        MessageIntent.EMERGENCY,
        MessageIntent.UNKNOWN,
    }
)

RESPONSE_TEMPLATES: Mapping[tuple[MessageIntent, str], str] = {
    (MessageIntent.CHECKIN_INSTRUCTIONS, "es"): (
        "Le enviaremos las instrucciones de entrada antes de su llegada. "
        "Si necesita cualquier otra cosa, escríbanos por aquí."
    ),
    (MessageIntent.CHECKIN_INSTRUCTIONS, "en"): (
        "We will send you the check-in instructions before your arrival. "
        "If you need anything else, write to us here."
    ),
    (MessageIntent.ACCESS_PROBLEM, "es"): (
        "Hemos registrado su problema de acceso y lo estamos revisando. "
        "Le responderemos por aquí lo antes posible."
    ),
    (MessageIntent.ACCESS_PROBLEM, "en"): (
        "We have registered your access problem and we are reviewing it. "
        "We will reply here as soon as possible."
    ),
    (MessageIntent.WIFI, "es"): (
        "Hemos registrado su consulta sobre la conexión a internet. "
        "Le responderemos por aquí lo antes posible."
    ),
    (MessageIntent.WIFI, "en"): (
        "We have registered your question about the internet connection. "
        "We will reply here as soon as possible."
    ),
    (MessageIntent.PARKING, "es"): (
        "Hemos registrado su consulta sobre el aparcamiento. "
        "Le responderemos por aquí lo antes posible."
    ),
    (MessageIntent.PARKING, "en"): (
        "We have registered your question about parking. "
        "We will reply here as soon as possible."
    ),
    (MessageIntent.LATE_CHECKOUT, "es"): (
        "Hemos registrado su solicitud de salida tardía. "
        "Le confirmaremos por aquí si es posible en su reserva."
    ),
    (MessageIntent.LATE_CHECKOUT, "en"): (
        "We have registered your late checkout request. "
        "We will confirm here whether it is possible for your booking."
    ),
    (MessageIntent.EARLY_CHECKIN, "es"): (
        "Hemos registrado su solicitud de entrada anticipada. "
        "Le confirmaremos por aquí si es posible en su reserva."
    ),
    (MessageIntent.EARLY_CHECKIN, "en"): (
        "We have registered your early check-in request. "
        "We will confirm here whether it is possible for your booking."
    ),
    (MessageIntent.CLEANING_ISSUE, "es"): (
        "Hemos registrado su aviso sobre la limpieza y lo estamos revisando. "
        "Le responderemos por aquí lo antes posible."
    ),
    (MessageIntent.CLEANING_ISSUE, "en"): (
        "We have registered your report about the cleaning and we are reviewing it. "
        "We will reply here as soon as possible."
    ),
    (MessageIntent.MAINTENANCE_ISSUE, "es"): (
        "Hemos registrado su aviso de avería y lo estamos revisando. "
        "Le responderemos por aquí lo antes posible."
    ),
    (MessageIntent.MAINTENANCE_ISSUE, "en"): (
        "We have registered your maintenance report and we are reviewing it. "
        "We will reply here as soon as possible."
    ),
    (MessageIntent.NOISE, "es"): (
        "Hemos registrado su aviso sobre el ruido y lo estamos revisando. "
        "Le responderemos por aquí lo antes posible."
    ),
    (MessageIntent.NOISE, "en"): (
        "We have registered your report about noise and we are reviewing it. "
        "We will reply here as soon as possible."
    ),
    (MessageIntent.GENERAL_FAQ, "es"): (
        "Hemos recibido su mensaje y lo estamos revisando. "
        "Le responderemos por aquí lo antes posible."
    ),
    (MessageIntent.GENERAL_FAQ, "en"): (
        "We have received your message and we are reviewing it. "
        "We will reply here as soon as possible."
    ),
    (MessageIntent.REVIEW_REQUEST, "es"): (
        "Gracias por escribirnos sobre su valoración. "
        "Le responderemos por aquí lo antes posible."
    ),
    (MessageIntent.REVIEW_REQUEST, "en"): (
        "Thank you for writing to us about your review. "
        "We will reply here as soon as possible."
    ),
}

#: **The catalogue as a set, and the obligation that goes with it.**
#: An `AIAdapter` declares its own vocabulary in the value it returns
#: (`GeneratedResponse.vocabulary`), which refuses a `content` outside it; that reaches every
#: adapter wherever it lives, but it is the *admission condition* and not the guarantee,
#: because an adapter may declare its own output.
#:
#: What closes it is `assert_in_catalogue` below, which the pipeline calls before persisting
#: an AI reply and before sending it: membership in *this* constant, not in
#: `GeneratedResponse.vocabulary`, which is whatever the adapter said.
RESPONSE_VOCABULARY: frozenset[str] = frozenset(RESPONSE_TEMPLATES.values())


#: What an incident derived from a conversation is **called** (R4.6, design D13).
#:
#: A closed catalogue of two constants, one per intent that opens one — never the guest's
#: words. `incidents.title` is a rule-11 sink and *we* compose it, so it goes in closed form;
#: the guest's own text goes to `description`, verbatim, where excepción 2 covers it because
#: the value is not ours.
#:
#: **This is the mapping, not the vocabulary.** `messaging` decides which conversation intent
#: opens an incident and therefore which title it asks for; the closed set those titles must
#: come from is `maintenance.domain.entities.CONVERSATION_INCIDENT_TITLES`, because
#: `maintenance` is the writer of `incidents.title` and the census in `steering/security.md`
#: is written by writer. Neither module imports the other: `ReportIncidentFromConversationUseCase`
#: validates against its own constant, and
#: `tests/maintenance/test_report_incident_from_conversation.py` asserts that these values are
#: exactly that set, so the two cannot drift apart in silence.
INCIDENT_TITLES: dict[MessageIntent, str] = {
    MessageIntent.MAINTENANCE_ISSUE: "Maintenance issue reported in a guest conversation",
    MessageIntent.ACCESS_PROBLEM: "Access problem reported in a guest conversation",
}


def assert_in_catalogue(content: str) -> None:
    """Refuse a reply that is not one of ours, before it can be persisted (R3.3).

    **This is the guarantee the admission condition is not.** `GeneratedResponse` refuses
    content outside the vocabulary *the adapter declares*, and `steering/security.md` records
    that an adapter can satisfy that trivially by declaring its own output. Comparing against
    this module's own catalogue is what closes it — and it lives here, in `domain/`, rather
    than as an `if` in the pipeline, because it is a rule ("si hay una regla, pertenece a
    `domain/`"). The architecture panel of sections 5-6 asked for the move; the pipeline calls
    it, which is the orchestration half.
    """
    if content not in RESPONSE_VOCABULARY:
        raise MessagingValidationError(
            "Generated content is not a member of the response catalogue; refusing to "
            "persist it into messages.content (rule 11 of steering/security.md, D7)"
        )


def template_key(intent: MessageIntent, language: str) -> str:
    """`"<INTENT>:<lang>"` — the identifier persisted in `messages.metadata` (D15).

    One function rather than an f-string at each call site, because three places build this
    value (the adapter, the message's metadata and the timeline event) and a second spelling
    would silently split the rows an operator filters on.
    """
    return f"{intent.value}:{language}"
