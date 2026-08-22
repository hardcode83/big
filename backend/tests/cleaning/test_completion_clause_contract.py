"""Structural guards on `complete()`'s third clause and its refusal (`cleaner-incident-report` R6).

Separate from `test_task_lifecycle.py`, which declares itself "Pure Python: no repository, no
session, no mocks" and tests `CleaningTask`'s behaviour by calling it. These two are a different
kind of test: they read the source and assert its *shape*, the way
`tests/maintenance/test_free_text_sink_contract.py` does for the rule-11 sinks. Keeping them
here rather than there was the architect panel's call in section 9 — a file whose docstring
promises pure-domain behaviour should not be parsing `ast` out of `application/`.

Both guard against a **tempting** edit rather than against a defect that exists:

* the refusal message is the one thing a cleaner could learn an incident from, and the helpful
  thing to do is name the incident in it — which R6.3 forbids, because `CLEANER` has no
  `READ_INCIDENTS`;
* `incidents.cleaning_task_id` now exists, so narrowing the blocking clause from the property to
  the cleaning became *possible* with this change. The proposal puts that out of scope precisely
  because it would **relax** an existing invariant: a `CRITICAL` incident opened by a guest would
  stop blocking. It is a change with its own roadmap entry and its own panel, not a line to slip
  in here.
"""

import ast
import inspect
from pathlib import Path

from app.cleaning.application.evidence import CompletionEvidenceGatherer
from app.cleaning.domain.ports import BlockingIncidentQuery

BLOCKING_MESSAGE = "An unresolved CRITICAL incident blocks completing this cleaning"
ENTITIES = Path(__file__).resolve().parents[2] / "app" / "cleaning" / "domain" / "entities.py"


def test_the_blocking_message_is_a_literal_that_cannot_grow_an_identifier() -> None:
    """R6.3, structurally — and this is the half that holds the line.

    The behavioural test in `test_task_lifecycle.py` passes for any message equal to the constant
    today. What it cannot catch is the edit that makes the message an f-string: the moment
    somebody writes `f"... (incident {incident.id})"` to be helpful, that assertion is simply
    updated to match and the leak ships green. Read off the AST, an interpolation is not a
    `Constant` and there is nothing to update.
    """
    raised = [
        node
        for node in ast.walk(ast.parse(ENTITIES.read_text(encoding="utf-8")))
        if isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id == "BlockingIncidentError"
    ]

    assert len(raised) == 1, "BlockingIncidentError gained a second raise site"
    argument = raised[0].exc.args[0]
    assert isinstance(argument, ast.Constant), (
        "the blocking message stopped being a literal: an interpolated one can name the "
        "incident, and `CLEANER` has no `READ_INCIDENTS` (R6.3)"
    )
    assert argument.value == BLOCKING_MESSAGE


def test_the_blocking_query_still_takes_only_a_tenant_and_a_property() -> None:
    """R6.1 — on the **port's arity**, not on a substring.

    The first version of this guard asserted `"cleaning_task_id" not in` the gatherer's source,
    and the architect panel of section 9 showed it was unsound: the narrowing D11 rejects would
    be written `has_unresolved_critical(tenant_id, task.property_id, task.id)` — or with a
    parameter called `focus_task_id` — and neither contains that substring. The guard would have
    waved through the exact edit it existed to stop.

    Asserting the signature catches the narrowing whatever the new argument is named, which is
    the same lesson the message guard above already encodes: check the shape, not the spelling.
    """
    parameters = list(
        inspect.signature(BlockingIncidentQuery.has_unresolved_critical).parameters
    )

    assert parameters == ["self", "tenant_id", "property_id"], (
        "the blocking-incident port changed shape. Narrowing R6.1 from the property to the "
        "cleaning task relaxes an existing invariant — a CRITICAL incident opened by a guest "
        "would stop blocking a close — so it is its own change with its own panel, not a "
        f"parameter added here. Found {parameters}"
    )


def test_the_gatherer_passes_exactly_those_two_arguments() -> None:
    """The other end of the same invariant: the port could keep its shape while the call site
    started passing something else through a keyword.

    Read from the AST of the real call rather than from a substring, for the reason above.
    """
    source = inspect.getsource(CompletionEvidenceGatherer)
    calls = [
        node
        for node in ast.walk(ast.parse(source.lstrip()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "has_unresolved_critical"
    ]

    assert len(calls) == 1, f"expected one blocking-incident query, found {len(calls)}"
    call = calls[0]
    assert len(call.args) == 2, (
        f"the blocking-incident query is called with {len(call.args)} positional arguments; "
        "R6.1 keeps it at the tenant and the property"
    )
    assert call.keywords == [], (
        "the blocking-incident query gained a keyword argument: see R6.1 and the proposal's "
        "§Out of scope before widening it"
    )
    # And the second argument is the *property* of the task, not the task.
    assert isinstance(call.args[1], ast.Attribute)
    assert call.args[1].attr == "property_id"
