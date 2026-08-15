"""`incidents.ai_summary` as a rule-11 sink: the admission condition for *any* adapter.

Rule 11 of `sdd/steering/security.md` censuses `incidents.ai_summary` under the **structured
form by default** — not under excepción 2, which says of itself that it "**No autoriza a un
escritor nuestro**". A classifier is our writer working from prose an anonymous guest typed,
so the column's contract is that the value is drawn from a closed vocabulary and never echoes
`title`/`description` (design D4).

**Why this file exists separately from `test_classifier.py`.** That file tests
`RuleBasedIncidentClassifier`; this one tests the *condition of admission* every future
adapter has to meet. Before it, D4 held for two reasons that both evaporate on the second
implementation: the deterministic adapter satisfies it *by construction* (`_SUMMARIES`), and
the port asks for it *in prose*. The type carries nothing —
`IncidentClassification.summary` is an unrestricted `str` — so a real LLM provider could
paraphrase the guest's description, carry a document number written differently enough to
share no long run with the original, and land it in a column the census calls "structured".

So the gate here is deliberately **structural, not behavioural**: an adapter module is
admitted only if it *publishes* `SUMMARY_VOCABULARY`, and every adapter that publishes one is
driven to prove nothing outside it escapes. A new adapter that forgets the declaration fails
collection, loudly, instead of silently inheriting a guarantee it does not provide.
"""

import ast
import importlib
import inspect
from pathlib import Path

import pytest

from app.maintenance.domain.enums import IncidentCategory
from app.maintenance.domain.value_objects import IncidentClassification

INFRASTRUCTURE_ROOT = (
    Path(__file__).resolve().parents[2] / "app" / "maintenance" / "infrastructure"
)

#: A guest's prose carrying exactly the rule-3 values the census is worried about: an identity
#: document, a phone number and an access code. Any adapter that paraphrases its input rather
#: than classifying it will surface one of these.
REPORTED_TITLE = "Cerradura rota, DNI 12345678Z"
REPORTED_DESCRIPTION = (
    "La cerradura no abre. Mi telefono es +34 600 123 456 y el codigo que me disteis "
    "es 4471. El agua tambien gotea y no hay wifi."
)

LEAK_MARKERS = ("12345678Z", "600 123 456", "4471", "DNI", "telefono", "codigo")


def _adapter_modules() -> list[str]:
    """Every module under `maintenance/infrastructure/` that defines a `classify` coroutine.

    Discovery is by AST rather than by import-and-introspect so that a module which fails to
    declare its vocabulary is still *found* — the point is to fail on the omission, not to
    skip the module that omits it.
    """
    found = []
    for path in sorted(INFRASTRUCTURE_ROOT.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defines_classify = any(
            isinstance(node, ast.AsyncFunctionDef) and node.name == "classify"
            for node in ast.walk(tree)
        )
        if defines_classify:
            found.append(f"app.maintenance.infrastructure.{path.stem}")
    return found


def test_the_discovery_finds_the_adapter_that_exists() -> None:
    """The gate below is only worth anything if it actually sees an adapter.

    Without this, deleting or renaming the adapter would turn every parametrized test into a
    vacuous pass and the census row would go unenforced without anything going red.
    """
    assert "app.maintenance.infrastructure.classifier" in _adapter_modules()


@pytest.mark.parametrize("module_name", _adapter_modules())
def test_every_classifier_adapter_publishes_its_closed_vocabulary(
    module_name: str,
) -> None:
    """The admission condition itself (rule 11, D4).

    An adapter is admitted only if it declares the closed set its summaries come from. This is
    the assertion the census row points at.
    """
    module = importlib.import_module(module_name)
    vocabulary = getattr(module, "SUMMARY_VOCABULARY", None)

    assert vocabulary is not None, (
        f"{module_name} implements `IncidentClassifier` but does not publish "
        "`SUMMARY_VOCABULARY`. Rule 11 of `sdd/steering/security.md` admits an adapter into "
        "`incidents.ai_summary` only if the closed set its summaries are drawn from is "
        "declared where this test can read it."
    )
    assert isinstance(vocabulary, frozenset)
    assert vocabulary, f"{module_name} declares an empty summary vocabulary"
    assert all(isinstance(entry, str) and entry for entry in vocabulary)


@pytest.mark.parametrize("module_name", _adapter_modules())
def test_no_declared_summary_can_interpolate_the_reported_text(
    module_name: str,
) -> None:
    """A constant with a `{}` or a `%s` in it is not a closed vocabulary.

    Cheap to write, and it closes the obvious way to satisfy the letter of the declaration
    while still emitting the guest's words.
    """
    vocabulary = importlib.import_module(module_name).SUMMARY_VOCABULARY

    for entry in vocabulary:
        assert "{" not in entry and "}" not in entry, (
            f"{module_name} declares a summary with a format placeholder: {entry!r}"
        )
        assert "%s" not in entry, (
            f"{module_name} declares a summary with a printf placeholder: {entry!r}"
        )


@pytest.mark.parametrize("module_name", _adapter_modules())
@pytest.mark.asyncio
async def test_the_adapter_only_ever_returns_a_declared_summary(
    module_name: str,
) -> None:
    """Drive the adapter over reported text carrying rule-3 values and check what comes out.

    The structural declaration above says what the adapter *promises*; this says it keeps the
    promise. Adapters that need constructor arguments are out of reach here and are expected
    to bring their own equivalent — the declaration test above still binds them.
    """
    module = importlib.import_module(module_name)
    vocabulary = module.SUMMARY_VOCABULARY

    adapters = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if obj.__module__ == module_name and hasattr(obj, "classify")
    ]
    assert adapters, f"{module_name} defines `classify` but exposes no class that has it"

    for adapter_class in adapters:
        try:
            adapter = adapter_class()
        except TypeError:  # pragma: no cover - no such adapter today
            continue

        classification = await adapter.classify(
            title=REPORTED_TITLE, description=REPORTED_DESCRIPTION
        )

        assert isinstance(classification, IncidentClassification)
        assert classification.summary in vocabulary, (
            f"{adapter_class.__name__} returned a summary outside its declared vocabulary: "
            f"{classification.summary!r}"
        )
        for marker in LEAK_MARKERS:
            assert marker.lower() not in classification.summary.lower(), (
                f"{adapter_class.__name__} echoed {marker!r} from the reported text into "
                "`incidents.ai_summary`, a rule-11 sink"
            )


@pytest.mark.asyncio
async def test_every_category_the_adapter_can_reach_has_a_declared_summary() -> None:
    """The vocabulary covers the enum, so no category falls through to derived text.

    `_summary_for` raises on a category with no constant rather than composing one, and this
    pins that the mapping is total: adding a member to `IncidentCategory` without adding its
    summary goes red here.
    """
    from app.maintenance.infrastructure.classifier import (
        SUMMARY_VOCABULARY,
        _SUMMARIES,
    )

    assert set(_SUMMARIES) == set(IncidentCategory)
    assert set(_SUMMARIES.values()) == set(SUMMARY_VOCABULARY)
