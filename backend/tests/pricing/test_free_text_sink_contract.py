"""`price_recommendations.explanation` as a rule-11 sink, with the test the rule demands.

Rule 11 of `sdd/steering/security.md` censuses the free-text columns and says the contract
"lo hereda el change que primero escribe en cada una, **con su propio test**". This change
is its first writer, so this file is that test. The census row itself is task 8.2.

**What is being pinned is the boundary of the exception D13 asks for**, not the prose it
allows. `explanation` is composed by our own closed template (`domain/explanation.py`), and
the *only* text in it that we did not write is the `name` the manager typed into one of her
own `seasonality_rules`/`event_rules`. The exception takes the shape of exception 3
(`owner_approvals.response_notes`): the value is not ours and we did not go looking for it.

What the exception does **not** concede is that the value travels, and the two halves of
that are **not** in the same state:

- **The audit half is structural.** `AUDITABLE_FIELDS["PRICE_RECOMMENDATION"]` is
  `{"status"}`, and the five JSONB columns of `PRICING_RULE` are in `REDACT_ONLY_FIELDS`, so
  `ChangeSet` refuses both by field name whatever encoding a caller uses. That is enforced
  and tested below.
- **The timeline half is an obligation, not a fact.** `TimelineEventFactory` checks only
  that `metadata` is a `dict` — no key allowlist — and `timeline_events` is append-only, so
  nothing that lands there can be redacted afterwards. The only assertion here
  (`test_no_timeline_metadata_carries_the_explanation`) reads source and **skips** until the
  use cases exist. What actually closes it is task 5.6's exact-metadata-keys assertion on
  the *constructed event*, which is where `metadata=asdict(recommendation)` gets caught.
  Said plainly because a reader who took this half for enforced could drop 5.6 as redundant.

Structural claims rot silently — a new writer, a richer audit diff, a fuller timeline
payload — which is exactly what the assertions below exist to catch.
"""

import ast
import json
from pathlib import Path

import pytest

from app.audit.domain import actions as audit_actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import AUDITABLE_FIELDS, ChangeSet
from app.pricing.domain.entities import MAX_MODIFIER_NAME_LENGTH
from app.pricing.infrastructure.models import PriceRecommendationModel

APP_ROOT = Path(__file__).resolve().parents[2] / "app"

#: The five columns of `pricing_rules` whose contents can reach `explanation`.
JSONB_RULE_COLUMNS = (
    "weekday_modifiers",
    "lead_time_rules",
    "occupancy_rules",
    "seasonality_rules",
    "event_rules",
)


def _touches_the_column(path: Path) -> bool:
    """Whether the module refers to `explanation` **as code**, not as prose.

    AST rather than a substring search, for the reason `maintenance`'s own sink test
    records about `incidents`: the bare word appears in comments and docstrings all over
    this codebase — `audit/domain/value_objects.py` explains why the column is not
    auditable, `cli/bootstrap.py` uses the English word — and a text match makes the census
    gate cry wolf until somebody adds an allowlist that explains nothing.

    Comments never reach the AST at all; a docstring only matches if it *equals* the name.

    **What this does not close, said plainly** — the disclosure rule 11's own
    `IncidentClassifier` row models, because a scan that oversells itself is worse than one
    that admits its edge. This is a tripwire for the straightforward new writer, not a
    boundary. Four evasions the section-4 QA and security panels demonstrated:

    - a name built at runtime — `setattr(row, "expl" + "anation", v)` is a `BinOp` of two
      constants, neither equal to the name;
    - `**payload` / `**{field: value}` from a variable, which is a `keyword` with `arg=None`;
    - `getattr(rec, field)` in a loop over a list of column names;
    - whole-object serialisation — `asdict(...)`, `model_dump()`, `dict(row._mapping)` —
      which carries the value without the token appearing anywhere.

    What actually holds the line is one layer down and does not depend on spelling:
    `AUDITABLE_FIELDS["PRICE_RECOMMENDATION"]` is `{"status"}` and the five rule columns are
    in `REDACT_ONLY_FIELDS`, so **`ChangeSet.diff()` refuses them by field name whatever
    encoding the caller uses**. This file is the second net.

    Said with that precision on purpose: the guarantee covers every route **through
    `ChangeSet`**, which is every writer in the app today. It is not a guarantee about
    `audit_logs.changes` as a column. `AuditLog` is a plain mutable dataclass and
    `SqlAlchemyAuditLogRepository.add` re-validates only `tenant_id` and
    `actor_guest_token_hash`, so a caller that hand-builds an `AuditLog` bypasses the
    allowlist entirely — the section-4 QA panel demonstrated it. That gap predates this
    change, belongs to `app/audit/` rather than to pricing, and has no call site: nothing in
    `app/` constructs an `AuditLog` outside `AuditLogFactory.build`. Closing it means
    re-checking `changes` in the repository, the way `actor_guest_token_hash` already is at
    three layers, and that is a change of its own.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return any(
        (isinstance(node, ast.Attribute) and node.attr == "explanation")
        or (isinstance(node, ast.keyword) and node.arg == "explanation")
        or (isinstance(node, ast.Name) and node.id == "explanation")
        or (isinstance(node, ast.Constant) and node.value == "explanation")
        for node in ast.walk(tree)
    )


def test_the_column_is_unbounded_text_which_is_why_it_needs_this_file() -> None:
    """The premise, asserted rather than assumed.

    `explanation` is `TEXT` with no width, so the only bound on what a manager can push
    into it is `MAX_MODIFIER_NAME_LENGTH` times the entry cap. If a later change gave the
    column a width, this file's reasoning would need revisiting.
    """
    assert PriceRecommendationModel.__table__.columns["explanation"].type.length is None
    assert MAX_MODIFIER_NAME_LENGTH == 100


def test_the_managers_text_cannot_reach_the_audit_sink_through_the_recommendation() -> None:
    """"No se propaga", half one: `audit_logs.changes` is itself a rule-11 sink."""
    allowlist = AUDITABLE_FIELDS[audit_actions.ENTITY_PRICE_RECOMMENDATION]

    assert allowlist == frozenset({"status"}), (
        "AUDITABLE_FIELDS['PRICE_RECOMMENDATION'] grew past {'status'}: D13's exception is "
        "bounded to the explanation column itself and does not authorise auditing it"
    )
    assert "explanation" not in allowlist


@pytest.mark.parametrize("column", JSONB_RULE_COLUMNS)
def test_the_managers_text_cannot_reach_the_audit_sink_through_the_rule(column: str) -> None:
    """"No se propaga", half one again, by the other door.

    The five JSONB columns *are* auditable — a manager editing her seasons is exactly what a
    trail should record — but only as `{"changed": true}`, because they are in
    `REDACT_ONLY_FIELDS` and `diff()` refuses them **by field name**. So the fact survives
    and the text does not, whatever encoding the caller reaches for.

    The name-level refusal is the point. An earlier version of this docstring credited
    `_storable` refusing a `Mapping`/`list`, which is a guard on the *shape*: a caller who
    serialised first walked straight through it. That attribution was corrected in
    `value_objects.py` and survived here for a round — the third time this module has had to
    correct the same class of claim (`GUEST`, then `PRICING_RULE`, then this line).
    """
    change_set = ChangeSet(audit_actions.ENTITY_PRICING_RULE)
    value = {"monday": 10} if column == "weekday_modifiers" else [
        {"name": "DNI 12345678Z", "modifier_pct": 10}
    ]

    with pytest.raises(AuditContractError):
        change_set.diff(column, None, value)
    # And in the encoding that used to slip past: the refusal is by field name, not by the
    # shape of the value (`_storable` accepts any `str`).
    with pytest.raises(AuditContractError):
        change_set.diff(column, None, json.dumps(value))

    assert change_set.redacted(column).as_dict() == {column: {"changed": True}}


def test_no_timeline_metadata_carries_the_explanation() -> None:
    """"No se propaga", half two: `timeline_events` is append-only, so it cannot be redacted.

    Read from the source rather than by running the use case: what this adds over a
    behavioural check is that no key of any pricing timeline payload is ever *named*
    `explanation`, which a future edit could add while every "not equal to the fixture"
    assertion still passed.
    """
    use_cases = APP_ROOT / "pricing" / "application" / "use_cases.py"
    if not use_cases.exists():
        pytest.skip("the use cases arrive in section 5; the assertion below is their gate")

    tree = ast.parse(use_cases.read_text(encoding="utf-8"))
    keys = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }

    assert "explanation" not in keys, (
        "a pricing timeline payload names 'explanation': D14 gives those events identifiers "
        "and a price, never the rendered text"
    )


def test_the_only_writer_of_the_column_is_the_recommendation_adapter() -> None:
    """The census, done the way rule 11 says: by **who writes the column**.

    The exception concedes our own template plus the manager's rule names. It does not
    concede a second producer — an AI adapter paraphrasing, a support tool annotating —
    which would need its own trip through steering rather than inheriting this one.
    """
    writers = {
        path.relative_to(APP_ROOT).as_posix()
        for path in APP_ROOT.glob("**/*.py")
        if _touches_the_column(path)
    }

    assert writers <= {
        # Renders it (R6.1, R6.2) — the closed template itself.
        "pricing/domain/explanation.py",
        # Carries it on the entity.
        "pricing/domain/entities.py",
        # Declares the column.
        "pricing/infrastructure/models.py",
        # Persists it, on both branches of the upsert.
        "pricing/infrastructure/repositories.py",
        # Composes the entity from a calculation (section 5).
        "pricing/application/use_cases.py",
        # Serialises it back to the manager who owns it (section 6).
        "pricing/api/schemas.py",
    }, f"a module outside the pricing module now touches `explanation`: {sorted(writers)}"


def test_no_ai_adapter_composes_the_explanation() -> None:
    """R6.2 at the census level rather than the module level.

    `test_explanation.py` pins the render's own import closure. This asserts the broader
    claim the census row makes: nothing under `app/integrations/` — where a real provider
    would live — mentions the column at all.
    """
    integrations = APP_ROOT / "integrations"

    offenders = [
        path.relative_to(APP_ROOT).as_posix()
        for path in integrations.glob("**/*.py")
        if _touches_the_column(path)
    ]

    assert not offenders, offenders
