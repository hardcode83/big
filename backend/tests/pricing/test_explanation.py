import ast
import pathlib
import tempfile
from datetime import date
from decimal import Decimal

from app.pricing.domain.calculator import calculate_price
from app.pricing.domain.explanation import render_explanation
from tests.pricing.test_calculator import compute, make_rule

# The rule and arguments that reproduce design D13's worked example, guardrails included.
D13_RULE = make_rule(
    base_price=Decimal("100.00"),
    min_price=Decimal("50.00"),
    max_price=Decimal("130.00"),
    max_daily_change_pct=Decimal("20.00"),
    weekday_modifiers={"saturday": 20},
    lead_time_rules=[{"days_before": 3, "modifier_pct": -10}],
    occupancy_rules=[{"occupancy_pct_above": 50, "modifier_pct": 5}],
    seasonality_rules=[
        {"name": "high_summer", "start_month": 7, "start_day": 1, "end_month": 8,
         "end_day": 31, "modifier_pct": 30}
    ],
)
D13_ARGUMENTS = {
    "target_date": date(2026, 8, 15),  # a Saturday inside high_summer
    "days_before": 2,
    "occupancy_pct": Decimal("60"),
    "previous_price": Decimal("110.00"),
}

D13_TEXT = (
    "Base price 100.00 EUR. "
    "Weekday (saturday) +20.00% -> 120.00. "
    "Lead time (<=3 days) -10.00% -> 108.00. "
    "Occupancy (>50%) +5.00% -> 113.40. "
    "Season (high_summer) +30.00% -> 147.42. "
    "Guardrail max_daily_change_pct (+20.00% of 110.00) -> 132.00. "
    "Guardrail max_price -> 130.00. "
    "Recommended 130.00 EUR."
)


def test_the_worked_example_of_the_design_renders_exactly() -> None:
    calculation = calculate_price(D13_RULE, **D13_ARGUMENTS)  # type: ignore[arg-type]

    assert render_explanation(calculation) == D13_TEXT


def test_a_price_with_no_modifiers_renders_base_and_recommended_only() -> None:
    calculation = compute(make_rule())

    assert render_explanation(calculation) == (
        "Base price 100.00 EUR. Recommended 100.00 EUR."
    )


def test_the_guardrail_that_cut_leaves_its_trace(  # R3.5
) -> None:
    rule = make_rule(max_price=Decimal("110.00"), weekday_modifiers={"tuesday": 50})

    text = render_explanation(compute(rule))

    assert "Guardrail max_price -> 110.00." in text
    assert "Recommended 110.00 EUR." in text


def test_a_guardrail_that_did_not_cut_is_not_mentioned() -> None:
    text = render_explanation(compute(make_rule(weekday_modifiers={"tuesday": 5})))

    assert "Guardrail" not in text


def test_the_daily_cap_names_the_price_it_measured_against() -> None:
    rule = make_rule(max_daily_change_pct=Decimal("20.00"), weekday_modifiers={"tuesday": -60})

    text = render_explanation(compute(rule, previous_price=Decimal("100.00")))

    assert "Guardrail max_daily_change_pct (-20.00% of 100.00) -> 80.00." in text


def test_a_discount_too_small_to_show_still_renders_as_a_discount() -> None:
    """`Decimal('-0.00') >= 0` is True, which printed a cut as `+0.00%`."""
    rule = make_rule(weekday_modifiers={"tuesday": -0.001})

    text = render_explanation(compute(rule))

    assert "Weekday (tuesday) -0.00% ->" in text
    assert "+0.00%" not in text


def test_the_event_kind_is_labelled() -> None:
    rule = make_rule(event_rules=[{"holidays": "ES_NATIONAL", "modifier_pct": 15}])

    text = render_explanation(compute(rule, target_date=date(2026, 12, 25)))

    assert "Event (Christmas Day) +15.00% -> 115.00." in text


def test_rendering_is_deterministic() -> None:
    calculation = calculate_price(D13_RULE, **D13_ARGUMENTS)  # type: ignore[arg-type]

    assert render_explanation(calculation) == render_explanation(calculation)
    assert render_explanation(
        calculate_price(D13_RULE, **D13_ARGUMENTS)  # type: ignore[arg-type]
    ) == D13_TEXT


def _app_imports(module_name: str, module_path: pathlib.Path) -> set[str]:
    """Every `app.*` module this file imports, in all three shapes.

    The shapes matter because each one was a hole in an earlier version of this guard:

    - `import app.integrations.x` is an `ast.Import`, which the first version never walked;
    - `from app.integrations import x` is the obvious `ast.ImportFrom`;
    - `from .x import y` is an `ast.ImportFrom` whose `module` is `"x"` — it does **not**
      start with `app`, so the second version filtered it away. Relative imports are a live
      convention in this codebase's domain layer (`app/properties/domain/state_machine.py`,
      `app/timeline/domain/services.py`), so that hole was reachable, not theoretical.

    `node.level` is resolved against the importing module's own package, the same way
    `tests/test_layering.py::_absolute_module` does it.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    package = module_name.rsplit(".", 1)[0]
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    imported.add(node.module)
                continue
            parts = package.split(".")
            base = ".".join(parts[: len(parts) - (node.level - 1)])
            if node.module:
                imported.add(f"{base}.{node.module}")
            else:
                # `from . import calculator` — each name is a submodule of `base`.
                imported.update(f"{base}.{alias.name}" for alias in node.names)
    return {name for name in imported if name.split(".")[0] == "app"}


def test_no_ai_adapter_takes_part_in_the_rendering() -> None:
    """R6.2, over the whole reachable closure and not just one hop.

    A one-hop check on `explanation.py` alone would pass for ever while somebody added an
    adapter import to `calculator.py`, which is on its allowlist. So this walks outwards
    until nothing new appears, and asserts that everything reachable stays inside
    `app.pricing.domain`.

    **What this does not check, and who does**: a runtime `importlib.import_module(...)`
    defeats any AST walk. `tests/test_layering.py::test_domain_modules_do_not_import_
    dynamically` rejects the *call* across every `app/*/domain/**` module, which covers all
    three members of this closure — but only because the closure happens to live entirely
    under `domain/`. If the allowed set below ever legitimately grows a member outside it,
    that cover lapses silently and this guard needs its own dynamic-import assertion.
    """
    start = pathlib.Path(render_explanation.__globals__["__file__"])
    # .../app/pricing/domain/explanation.py -> the directory that CONTAINS the `app` package,
    # so a dotted module name maps onto a path by simple substitution.
    package_parent = start.parents[3]

    seen: set[str] = set()
    frontier = {"app.pricing.domain.explanation"}
    while frontier:
        module = frontier.pop()
        if module in seen:
            continue
        seen.add(module)
        path = package_parent / (module.replace(".", "/") + ".py")
        assert path.exists(), f"{module} is imported but not a module of app/"
        frontier |= _app_imports(module, path)

    assert seen == {
        "app.pricing.domain.explanation",
        "app.pricing.domain.calculator",
        "app.pricing.domain.holidays",
    }, f"the rendering reaches {sorted(seen - {'app.pricing.domain.explanation'})}"


def test_the_import_guard_would_catch_a_plain_import_statement() -> None:
    """The guard gets its own test, because its previous form silently missed this shape."""
    scratch = pathlib.Path(tempfile.mkdtemp()) / "probe.py"
    scratch.write_text("import app.integrations.pretend_ai\nfrom decimal import Decimal\n")

    assert _app_imports("app.pricing.domain.calculator", scratch) == {
        "app.integrations.pretend_ai"
    }


def test_the_import_guard_resolves_relative_imports() -> None:
    """The second hole: `from .x import y` never starts with `app`, so it was filtered out.

    Without this, an AI adapter reached through a relatively-imported sibling of
    `calculator.py` would leave the closure looking untouched.

    `from ..infrastructure import adapters` resolves to the module imported *from* —
    `app.pricing.infrastructure`, a package — and not to `…infrastructure.adapters`, since
    the name could equally be a class. That is what `tests/test_layering.py::_absolute_module`
    does, and it is enough for the walk: a package path has no `.py`, so the closure's
    `path.exists()` assertion fails closed on it.
    """
    scratch = pathlib.Path(tempfile.mkdtemp()) / "probe.py"
    scratch.write_text(
        "from .ai_summary import summarise\n"
        "from . import sibling\n"
        "from ..infrastructure import adapters\n"
    )

    assert _app_imports("app.pricing.domain.calculator", scratch) == {
        "app.pricing.domain.ai_summary",
        "app.pricing.domain.sibling",
        "app.pricing.infrastructure",
    }
