"""The closed catalogue a review response draft is drawn from (R3.2, R3.4; design D6, D12).

**Constants, with no interpolation hole anywhere.** No `{...}`, no `%s`, no `f`-string, and
`tests/reviews/test_draft_templates.py` walks the catalogue and refuses one — calqued on
`tests/messaging/test_templates.py`.

**What that buys, stated precisely, because it is easy to claim more.** It makes it
impossible for *the reviewer's own words* to end up in a reply: there is nowhere to put
them. It does **not** make it impossible for a person to hand-write a template that breaks
rule 10 of `sdd/steering/security.md` — "nunca prometer reembolsos/compensaciones, admitir
responsabilidad, dar asesoría legal, revelar datos de otros huéspedes, inventar
códigos/disponibilidad/precios, ni afirmar que un técnico va sin assignment real". Nothing
mechanical can: a constant is whatever someone typed. What guards the *wording* is review,
plus the phrase list in `test_no_draft_can_promise_what_rule_10_forbids`, which is a net
and not a guarantee.

It is also what sustains the closed form of `review_response_drafts.draft_content` (R3.3,
D6) — with the same care about how much is claimed. `GeneratedDraft` refuses a `content`
outside the vocabulary *the adapter declares*, which `steering/security.md` records as the
admission condition and explicitly not the guarantee ("un adaptador que construya su
`vocabulary` a partir de su propia salida satisface la comprobación trivialmente"). What
closes it for this change is that the only adapter shipped declares
`REVIEW_DRAFT_VOCABULARY` below, and that `assert_in_catalogue` checks the value about to
be persisted against **this** catalogue rather than against whatever the adapter declared.
The pipeline calls it before persisting.

**Six entries and not eight.** Sentiment × language: `IGNORED` and `POSTED_MANUALLY` do
not generate a draft (D12 — the manager made the call, no response is required for
`IGNORED`; the human already posted for `POSTED_MANUALLY`). The absence is the second net
of that prohibition, and a loud `KeyError` for anyone who steps over the first.
"""

from collections.abc import Mapping

from app.reviews.domain.enums import ReviewSentiment
from app.reviews.domain.exceptions import ReviewValidationError

#: Bumped whenever a template changes. Carried in `GeneratedDraft.template_version`, and
#: from there into a structured log line so an operator can correlate a sent draft with the
#: catalogue that produced it (D13). Not persisted into `review_response_drafts` itself —
#: PRD §7.21 declares no `metadata` column, and adding one would be a deviation the
#: proposal chose not to make.
REVIEW_DRAFT_TEMPLATES_VERSION = "2026-09-01.1"

#: Six entries: three sentiments (POSITIVE, NEUTRAL, NEGATIVE) × two languages (es, en).
#: Each entry is a single sentence in the language the reviewer wrote, with no
#: interpolation, no `f`-string, no `{...}`, no `%s`. A reviewer's words cannot reach
#: `review_response_drafts.draft_content` from this catalogue.
REVIEW_DRAFT_TEMPLATES: Mapping[tuple[ReviewSentiment, str], str] = {
    (ReviewSentiment.POSITIVE, "es"): (
        "Gracias por su valoracion. Nos alegra que su estancia fuera positiva."
    ),
    (ReviewSentiment.POSITIVE, "en"): (
        "Thank you for your review. We are glad your stay was a positive one."
    ),
    (ReviewSentiment.NEUTRAL, "es"): (
        "Gracias por su valoracion. Tomamos nota de sus comentarios para mejorar."
    ),
    (ReviewSentiment.NEUTRAL, "en"): (
        "Thank you for your review. We are taking your comments on board to improve."
    ),
    (ReviewSentiment.NEGATIVE, "es"): (
        "Gracias por su valoracion. Sentimos que algunos aspectos no estuvieran a la "
        "altura y queremos revisarlos."
    ),
    (ReviewSentiment.NEGATIVE, "en"): (
        "Thank you for your review. We are sorry some aspects fell short and we want to "
        "look into them."
    ),
}

#: **The catalogue as a set, and the obligation that goes with it.** A draft adapter
#: declares its own vocabulary in the value it returns (`GeneratedDraft.vocabulary`),
#: which refuses a `content` outside it; that reaches every adapter wherever it lives,
#: but it is the *admission condition* and not the guarantee, because an adapter may
#: declare its own output.
#:
#: What closes it is `assert_in_catalogue` below, which the pipeline calls before
#: persisting a draft: membership in *this* constant, not in `GeneratedDraft.vocabulary`,
#: which is whatever the adapter said.
REVIEW_DRAFT_VOCABULARY: frozenset[str] = frozenset(REVIEW_DRAFT_TEMPLATES.values())


def assert_in_catalogue(content: str) -> None:
    """Refuse a draft that is not one of ours, before it can be persisted (R3.3, D7).

    **This is the guarantee the admission condition is not.** `GeneratedDraft` refuses
    content outside the vocabulary *the adapter declares*, and `steering/security.md`
    records that an adapter can satisfy that trivially by declaring its own output.
    Comparing against this module's own catalogue is what closes it — and it lives here,
    in `domain/`, rather than as an `if` in the pipeline, because it is a rule ("si hay una
    regla, pertenece a `domain/`"). The architecture panel of sections 5-6 asked for the
    move in `messaging`; the pipeline calls it, which is the orchestration half.
    """
    if content not in REVIEW_DRAFT_VOCABULARY:
        raise ReviewValidationError(
            "Generated content is not a member of the review draft catalogue; refusing "
            "to persist it into review_response_drafts.draft_content (rule 11 of "
            "steering/security.md, design D7)"
        )
