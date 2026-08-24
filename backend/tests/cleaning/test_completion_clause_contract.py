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
  in here;
* and, from `cleaner-photo-requirements`, that the read-only projection of the photo categories
  stays a **reporter**. It reads the same port method the close compares
  (`uploaded_photo_types`), so the tempting edit is one step further: compare the two sets right
  there and hand the client a `satisfied`. That would be a second point of application of
  PRD §11's third clause, free to drift from `CleaningTask.complete()` — which R3.3 keeps as the
  only one.
"""

import ast
import inspect
from pathlib import Path

from app.cleaning.application.evidence import CompletionEvidenceGatherer
from app.cleaning.domain.ports import BlockingIncidentQuery

BLOCKING_MESSAGE = "An unresolved CRITICAL incident blocks completing this cleaning"
ENTITIES = Path(__file__).resolve().parents[2] / "app" / "cleaning" / "domain" / "entities.py"
USE_CASES = (
    Path(__file__).resolve().parents[2] / "app" / "cleaning" / "application" / "use_cases.py"
)
TASKS_ROUTER = (
    Path(__file__).resolve().parents[2] / "app" / "cleaning" / "api" / "tasks_router.py"
)
SCHEMAS = Path(__file__).resolve().parents[2] / "app" / "cleaning" / "api" / "schemas.py"
DEPENDENCIES = (
    Path(__file__).resolve().parents[2] / "app" / "cleaning" / "api" / "dependencies.py"
)
MAIN = Path(__file__).resolve().parents[2] / "app" / "main.py"
#: The name `main.py` mounts this router under, for the guard on the mount itself.
TASKS_ROUTER_MOUNTED_AS = "cleaning_tasks_router"


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


# --- `cleaner-photo-requirements`: the projection reports, it does not adjudicate -----------

PHOTO_REQUIREMENTS_USE_CASE = "GetPhotoRequirementsUseCase"
#: The names that would mean the projection had started deciding the close rather than
#: describing what is filed. `required_photo_types` is the accessor that filters on `required`;
#: the other three are the completion machinery itself.
COMPLETION_MACHINERY = (
    "required_photo_types",
    "missing_required_photo_types",
    "CleaningCompletionEvidence",
    "CompletionEvidenceGatherer",
)
#: A field by any of these names would be a verdict, whatever it was computed from.
VERDICT_FIELDS = frozenset(
    {"satisfied", "can_complete", "canComplete", "complete", "completed", "missing", "blocked"}
)


def _photo_requirements_use_case_node() -> ast.ClassDef:
    """The AST of the use case, found by name in the module it lives in."""
    source = USE_CASES.read_text(encoding="utf-8")
    for node in ast.parse(source).body:
        if isinstance(node, ast.ClassDef) and node.name == PHOTO_REQUIREMENTS_USE_CASE:
            return node
    raise AssertionError(f"{PHOTO_REQUIREMENTS_USE_CASE} is not in {USE_CASES}")


def test_the_photo_requirements_use_case_names_none_of_the_completion_machinery() -> None:
    """R2.2, R3.2, R3.4 — structurally, in one assertion.

    Read off the AST of the class body and **not** off the module: `use_cases.py` holds the
    close's own use case too — and imports `CompletionEvidenceGatherer` for it — so a substring
    search over the file would find every one of these names for reasons that have nothing to do
    with this projection.

    Collecting `Name`/`Attribute` nodes rather than text is also what lets the class keep
    explaining itself: its docstring names what it deliberately does not call, and a docstring is
    an `ast.Constant`, so the prose is invisible here while a real call would not be. A guard
    written over the source text would have forbidden the explanation along with the act.

    What each name being absent buys:

    * `required_photo_types` — the source is `spec.required_photos`, unfiltered, so an optional
      type stays in the collection (R2.2). Calling the accessor that filters on `required` is
      exactly how that regresses, and it would look like a tidy-up.
    * `missing_required_photo_types` / `CleaningCompletionEvidence` — the set difference that
      answers "can this close?" is the domain's, and computing it here would be the second point
      of application R3.3 forbids.
    * `CompletionEvidenceGatherer` — R3.4 says what is shared with it is the **port**, never the
      assembly. Importing it would share the assembly.
    """
    body = _photo_requirements_use_case_node()
    names = {
        node.id if isinstance(node, ast.Name) else node.attr
        for node in ast.walk(body)
        if isinstance(node, (ast.Name, ast.Attribute))
    }

    offenders = sorted(names & set(COMPLETION_MACHINERY))
    assert not offenders, (
        f"{PHOTO_REQUIREMENTS_USE_CASE} now names {offenders}. It is a reporter: it publishes "
        "what is uploaded and applies none of PRD §11's clauses, which live in "
        "`CleaningTask.complete()` and nowhere else (R3.2, R3.3, R3.4). If the projection "
        "genuinely needs one of these, that is a change to the design, not to this list."
    )


def test_the_photo_requirement_view_carries_no_verdict_field() -> None:
    """R3.2 — the other half: the shape the use case returns.

    The API test asserts this on a serialised body, which is the guarantee a client gets. This
    asserts it one layer earlier, where the field would actually be added — a view that grew
    `satisfied` would reach the schema as the obvious next step, and by then the change looks
    like plumbing rather than like a decision.
    """
    for node in ast.parse(USE_CASES.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef) and node.name == "PhotoRequirementView":
            break
    else:
        raise AssertionError("PhotoRequirementView is not in use_cases.py")

    fields = {
        statement.target.id
        for statement in node.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    }

    assert fields == {"photo_type", "label", "required", "uploaded"}, (
        f"PhotoRequirementView's fields changed to {sorted(fields)}. The four are the closed "
        "set R4.4/R4.5 fix; adding one is a deliberate act."
    )
    assert not fields & VERDICT_FIELDS, (
        f"the view grew a completion verdict: {sorted(fields & VERDICT_FIELDS)}"
    )


def test_the_evidence_gatherer_still_has_exactly_one_consumer() -> None:
    """R3.4 — what this capability shares with the gatherer is the **port**, not the assembly.

    An earlier version of this guard asserted `use_cases.py` does not import
    `CompletionEvidenceGatherer` at all, and that was simply false: the import at the top of the
    module is pre-existing and belongs to `CompleteCleaningTaskUseCase`, the close. A guard that
    fails on the tree it is written against is not a guard, so this asserts the thing that is
    both true and load-bearing — the gatherer has **one** consumer class, and the projection is
    not it.

    Read per class rather than per module for that exact reason: the file holds both, and a
    substring search could only ever say "the name appears somewhere in here", which it does and
    always did.
    """
    module = ast.parse(USE_CASES.read_text(encoding="utf-8"))
    consumers = {
        node.name
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and any(
            isinstance(inner, (ast.Name, ast.Attribute))
            and (inner.id if isinstance(inner, ast.Name) else inner.attr)
            == "CompletionEvidenceGatherer"
            for inner in ast.walk(node)
        )
    }

    assert consumers == {"CompleteCleaningTaskUseCase"}, (
        f"the evidence gatherer's consumers are now {sorted(consumers)}. R3.4 keeps it the only "
        "assembler of the close's evidence, with a single caller: a projection that assembled "
        "the same evidence would be free to drift from the rule the close applies."
    )
    assert PHOTO_REQUIREMENTS_USE_CASE not in consumers


# --- the same invariant as a SHAPE, because a name list only catches the spelling -----------
#
# Both guards below were added after the section-3 panel: the architect and the QA reviewer
# independently found the same hole from opposite ends. A name-membership check cannot see an
# edit that reimplements PRD §11's third clause *without naming it* — and the file's own older
# lesson (`test_the_blocking_query_still_takes_only_a_tenant_and_a_property`) had already said
# why: **check the shape, not the spelling**. These two say it for the projection.

#: Set algebra. A reporter answers membership — "is this type among the uploaded ones" — and has
#: no honest use for a difference, an intersection or a union: those are the operations that
#: compute *what is missing*, which is the close's question.
SET_ALGEBRA_OPS = (ast.Sub, ast.BitAnd, ast.BitOr, ast.BitXor)
#: Subset/superset tests, the operator spelling of "are all the required ones there?".
CONTAINMENT_COMPARISONS = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
#: The method spelling of the same thing.
SET_METHODS = frozenset(
    {"difference", "symmetric_difference", "intersection", "union", "issubset", "issuperset",
     "isdisjoint"}
)




# --- the same invariant as a WHITELIST, because a blacklist only moves the escape ------------
#
# The three guards below replace a first attempt that enumerated *forbidden* shapes — set
# algebra, subset comparisons, set-method calls, filtered comprehensions. Two review rounds
# walked straight through it, each time in a spelling the list did not name:
#
#   * an imperative loop — `for photo in spec.required_photos: if photo.required and
#     photo.photo_type not in uploaded: outstanding.append(...)` — which uses `NotIn` (not in the
#     comparison list), `.append` (not a set method) and a plain `for`/`if` (not a comprehension);
#   * the same computation moved into `PhotoRequirementsResponse.build`, handed a `Response` and
#     setting a header there, while the router stayed a textbook two-statement pass-through.
#     That one was demonstrated live: `x-cleaning-task-photos-satisfied: false` on a real
#     response, with all guards and all 650 tests green.
#
# A blacklist can only ever forbid the spellings someone thought of. So these assert what each
# function **is**: an exact statement shape, and for the projection an exact returned expression.
# Any third statement fails, whatever it computes and however it is written — which is the same
# move `test_the_blocking_query_still_takes_only_a_tenant_and_a_property` made when it stopped
# grepping for `cleaning_task_id` and asserted the port's arity instead.
#
# The bluntness is deliberate and has one sharp edge worth knowing before it bites: an audit-log
# call, a metric or a trace `await` added to the route handler would be refused too. That is the
# right refusal — `steering/backend.md` says "Routers finos … La lógica nunca vive en el router"
# — and the place for such a call is the use case. What must NOT happen is moving it into
# `schemas.py` or `dependencies.py` to satisfy the count; the third guard is why `schemas.py` is
# now in scope, and `dependencies.py` holds no code of this capability beyond wiring.

PHOTO_REQUIREMENTS_ROUTE = "/{task_id}/photo-requirements"


def _route_handler(path: str) -> ast.AsyncFunctionDef:
    """The handler registered for `path`, found by its DECORATOR and not by its name.

    By name would be a spelling check again: a second `@router.get` on the same path under
    another function name would be invisible, which the QA panel of section 3 named as an
    untried-but-plausible escape. The decorator is what FastAPI binds, so it is what this reads.
    """
    for node in ast.walk(ast.parse(TASKS_ROUTER.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and decorator.args[0].value == path
            ):
                return node
    raise AssertionError(f"no route handler is registered for {path}")


def _route_decorator(path: str) -> ast.Call:
    """The `@router.get(...)` call itself, for the assertions that live in its keywords.

    `_route_handler` returns the function; this returns the decorator, because `dependencies=`
    is a keyword on the decorator and never reaches the function's signature at all.
    """
    for node in ast.walk(ast.parse(TASKS_ROUTER.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and decorator.args[0].value == path
            ):
                return decorator
    raise AssertionError(f"no route decorator is registered for {path}")


def _provider_node(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    """The AST of one provider in `dependencies.py`, found by name in the module it lives in."""
    for node in ast.parse(DEPENDENCIES.read_text(encoding="utf-8")).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} is not in {DEPENDENCIES}")


def _schema_class(name: str) -> ast.ClassDef:
    """The AST of one response schema, found by name in `schemas.py`."""
    for node in ast.parse(SCHEMAS.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ClassDef) and node.name == name:
            return node
    raise AssertionError(f"{name} is not in {SCHEMAS}")


def _capability_nodes() -> dict[str, ast.AST]:
    """Every node this capability owns, labelled — the scope the spelling checks run over.

    Four files and five nodes: the use case, its provider, its handler and its two schemas.
    Assembled here so that adding a sixth place for this capability's code means adding it to
    one dict rather than remembering to add it to each assertion.
    """
    return {
        f"`{PHOTO_REQUIREMENTS_USE_CASE}`": _photo_requirements_use_case_node(),
        "`get_photo_requirements_use_case`": _provider_node(
            "get_photo_requirements_use_case"
        ),
        f"the handler for `{PHOTO_REQUIREMENTS_ROUTE}`": _route_handler(
            PHOTO_REQUIREMENTS_ROUTE
        ),
        "`PhotoRequirementStateResponse`": _schema_class("PhotoRequirementStateResponse"),
        "`PhotoRequirementsResponse`": _schema_class("PhotoRequirementsResponse"),
    }


def _statements(node) -> list[ast.stmt]:
    """A function's body with its docstring removed."""
    return [
        statement
        for statement in node.body
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
    ]


def test_the_projection_has_exactly_the_shape_that_reports_and_nothing_more() -> None:
    """R2.2, R3.2, R3.3 — asserted as the whole shape of `execute`, not as a list of don'ts.

    Six statements, in this order and no others:

        task = await self._load_task(...)          # R1.5, and always first (Risk 4)
        template = await self._templates.get(...)
        if template is None: raise ...             # R1.6
        spec = parse_template_content(...)
        uploaded = await self._photos.uploaded_photo_types(...)   # R3.1
        return [PhotoRequirementView(...) for photo in spec.required_photos]

    and the returned expression is a comprehension over `spec.required_photos` with **no `if`**.

    That single pair of assertions subsumes every blacklist the earlier rounds tried. A set
    difference, an imperative accumulation loop, a subset test, a filtered comprehension, a
    verdict computed and thrown away — each needs either a seventh statement or an `if` on the
    generator, and there is room for neither. It also keeps R2.2 true by construction: an
    unfiltered comprehension over the tuple cannot drop a `required: false` type.
    """
    node = _photo_requirements_use_case_node()
    execute = next(
        (n for n in node.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute"),
        None,
    )
    assert execute is not None, f"{PHOTO_REQUIREMENTS_USE_CASE} has no `execute`"

    body = _statements(execute)
    shape = [type(statement).__name__ for statement in body]
    assert shape == ["Assign", "Assign", "If", "Assign", "Assign", "Return"], (
        f"`execute` is now shaped {shape}. It reports what is uploaded and applies none of "
        "PRD §11's clauses — those live in `CleaningTask.complete()` and nowhere else (R3.3). "
        "A statement that derives anything from `uploaded` is a second point of application, "
        "whether or not its answer is ever published."
    )

    returned = body[-1].value
    assert isinstance(returned, ast.ListComp), "the projection stopped returning a comprehension"
    assert len(returned.generators) == 1
    generator = returned.generators[0]
    assert not generator.ifs, (
        "the comprehension now filters. R2.2 keeps every declared type in the collection, "
        "`required: false` included — the upload admits them, so the enumeration names them."
    )
    assert isinstance(generator.iter, ast.Attribute) and generator.iter.attr == "required_photos", (
        "the source is no longer `spec.required_photos`. R2.2 names it, and it is the only one "
        "that carries the `label` and the template's own order (R1.3)."
    )


def test_each_published_field_reads_its_own_photo_and_nothing_else() -> None:
    """R3.2, R3.3 — the VALUE axis, which the statement shape above cannot see.

    The guard above pins six statements, an unfiltered comprehension and its source, and stops
    at the comprehension's `elt`. Two reviewers of this change independently walked in through
    that gap, from opposite directions and both inside the single `Return`:

        label=(f"{photo.label} !" if photo.photo_type not in uploaded else photo.label)
        uploaded=(photo.photo_type in uploaded) and all(
            q.photo_type in uploaded for q in spec.required_photos if q.required)

    The second is a complete verdict on PRD §11's photo clause — *every required type filed* —
    folded into a boolean that is supposed to mean one type. Neither trips anything: the outer
    shape is untouched, `all()` is not a set method, and `in`/`not in` are deliberately
    whitelisted so that R3.1's honest `photo.photo_type in uploaded` can exist at all.

    So this pins the `elt` exactly, which is what the earlier rounds kept not doing: three
    fields copied straight off the loop variable, and `uploaded` the one membership test, with
    nothing wrapped around any of them. There is no room left inside `execute` after this — the
    statements, the generator, the source and now every published value are each fixed — which
    is the point. A blacklist has to be extended every time somebody is clever; this has to be
    edited on purpose, and the edit is the review.
    """
    node = _photo_requirements_use_case_node()
    execute = next(
        n for n in node.body if isinstance(n, ast.AsyncFunctionDef) and n.name == "execute"
    )
    returned = _statements(execute)[-1].value
    element = returned.elt
    assert isinstance(element, ast.Call), "the comprehension stopped building a view directly"

    assert not element.args, (
        "the view is now built positionally. R4.4 turns on which four fields are published, and "
        "keywords are what make that readable here and in `schemas.py`."
    )
    published = {keyword.arg: keyword.value for keyword in element.keywords}
    assert set(published) == {"photo_type", "label", "required", "uploaded"}, (
        f"the view now publishes {sorted(map(str, published))}. Four fields, and a fifth is a "
        "verdict or a template leak whatever it is called (R3.2, R4.4)."
    )

    loop_variable = returned.generators[0].target
    assert isinstance(loop_variable, ast.Name), "the comprehension now unpacks its loop variable"

    for field in ("photo_type", "label", "required"):
        value = published[field]
        assert (
            isinstance(value, ast.Attribute)
            and value.attr == field
            and isinstance(value.value, ast.Name)
            and value.value.id == loop_variable.id
        ), (
            f"`{field}` is no longer `{loop_variable.id}.{field}` but "
            f"`{ast.unparse(value)}`. These three are copied from the template row unchanged: "
            "anything computed into one of them is a channel that carries whatever the "
            "computation knows, and `label` is the one a reader would least suspect."
        )

    uploaded_value = published["uploaded"]
    assert (
        isinstance(uploaded_value, ast.Compare)
        and len(uploaded_value.ops) == 1
        and isinstance(uploaded_value.ops[0], ast.In)
        and isinstance(uploaded_value.left, ast.Attribute)
        and uploaded_value.left.attr == "photo_type"
        and isinstance(uploaded_value.left.value, ast.Name)
        and uploaded_value.left.value.id == loop_variable.id
        and len(uploaded_value.comparators) == 1
        and isinstance(uploaded_value.comparators[0], ast.Name)
    ), (
        f"`uploaded` is now `{ast.unparse(uploaded_value)}`. It is exactly one membership test "
        f"— `{loop_variable.id}.photo_type in <the uploaded set>` — and nothing else (R3.1). "
        "Anything joined onto it with `and`/`or`, or any call wrapped around it, can only be "
        "reporting something this entry's own type does not determine: that is the close's "
        "question, answered in `CleaningTask.complete()` and nowhere else (R3.3)."
    )


def test_the_route_handler_only_calls_the_use_case_and_returns_the_schema() -> None:
    """R3.2, R3.3 — the router derives nothing, and it is found by its route.

    Two statements beyond the docstring: the `await` and the `return`. The QA panel of section 3
    built the escape this refuses — a set of outstanding types computed here and returned as a
    response header — and measured 648 tests passing with it live.

    **No `Response` in the signature**, which is the half that matters after the escape moved:
    a handler that never receives one cannot set a header, and cannot hand one to a callee that
    would. That is what stops the derivation relocating into `schemas.py` while this function
    stays innocently two statements long.
    """
    handler = _route_handler(PHOTO_REQUIREMENTS_ROUTE)

    body = _statements(handler)
    shape = [type(statement).__name__ for statement in body]
    assert shape == ["Assign", "Return"], (
        f"the handler is now shaped {shape}. It is a pass-through — call the use case, hand the "
        "result to the schema (`steering/backend.md`: «La lógica nunca vive en el router»). An "
        "audit or metric call belongs in the use case, not here."
    )

    annotations = {
        ast.unparse(argument.annotation)
        for argument in handler.args.args + handler.args.kwonlyargs
        if argument.annotation is not None
    }
    assert not any("Response" in annotation for annotation in annotations), (
        "the handler now takes a `Response`. The only reason this projection would want one is "
        "to set a header, and a completion verdict reaches the client through a header exactly "
        "as well as through a field (R3.2)."
    )


def test_the_response_schemas_only_copy_fields() -> None:
    """R3.2, R3.3, R4.4 — `schemas.py` in scope, because that is where the escape went.

    The QA panel demonstrated the verdict computed inside `PhotoRequirementsResponse.build`,
    handed a `Response` by the router and emitted as a header, with every other guard green. No
    guard read this file; now one does.

    Both constructors are single-expression: `from_view` returns one `cls(...)` copying four
    named fields, `build` returns one `cls(data=[...])`. A derivation needs a statement, and
    neither has room for one — and neither may name a `Response`, so neither can reach a header.
    """
    module = ast.parse(SCHEMAS.read_text(encoding="utf-8"))
    classes = {
        node.name: node
        for node in module.body
        if isinstance(node, ast.ClassDef)
        and node.name in {"PhotoRequirementStateResponse", "PhotoRequirementsResponse"}
    }
    assert set(classes) == {"PhotoRequirementStateResponse", "PhotoRequirementsResponse"}, (
        f"expected both response schemas in schemas.py, found {sorted(classes)}"
    )

    for name, node in classes.items():
        for method in (n for n in node.body if isinstance(n, ast.FunctionDef)):
            body = _statements(method)
            shape = [type(statement).__name__ for statement in body]
            assert shape == ["Return"], (
                f"{name}.{method.name} is now shaped {shape}. These constructors copy fields and "
                "compute nothing: a completion verdict assembled here reaches the client just as "
                "surely as one assembled in the router (R3.2, R3.3)."
            )
            arguments = method.args.args + method.args.kwonlyargs
            annotations = {
                ast.unparse(argument.annotation)
                for argument in arguments
                if argument.annotation is not None
            }
            assert not any("Response" in annotation for annotation in annotations), (
                f"{name}.{method.name} now takes a `Response` — the header route to a verdict."
            )
            assert not [
                n
                for n in ast.walk(method)
                if isinstance(n, ast.Attribute) and n.attr == "headers"
            ], f"{name}.{method.name} touches response headers (R3.2)"


# --- and the file the last three rounds each declared out of scope by comment ----------------
#
# The three guards above were the round-2 fix, and the `/sdd:review` panel walked through them
# too: `dependencies.py` was named "wiring only" in this file's own prose while nothing read it.
# A `Depends()`-injected callable may itself take a `Response` — FastAPI resolves one for any
# dependency, not only for the path function — so the verdict simply moved one file further out
# than the round had reached, which is the same escape in its fourth spelling.
#
# The lesson is not "add the next file". It is that a whitelist scoped by a hand-kept list of
# paths is only ever as complete as the last review, so the two guards below fix the *scope*
# instead of the spelling: this module is wiring, asserted rather than asserted-in-a-comment,
# and the route declares no dependency that could carry a `Response` in. The channel itself is
# closed behaviourally in `test_photo_requirements_api.py`, which compares this route's response
# headers against a sibling's and so does not care which file computed a leak.


def test_the_capabilitys_wiring_module_is_wiring_and_nothing_else() -> None:
    """R3.2, R3.3 — `dependencies.py` in scope, because that is where the escape went next.

    Every provider in the module is a single `return`, none takes a `Response` and none touches
    `.headers`. All twenty-two already satisfied this when the guard was written: the point is
    not to change the file but to stop its shape being a claim in a comment.

    Module-wide and not just this capability's provider, deliberately. A leak needs somewhere to
    live, and a *new* helper next to the real provider is cheaper to add than an edit to it —
    scoping this to `get_photo_requirements_use_case` by name would be the spelling check this
    file keeps learning not to write.
    """
    module = ast.parse(DEPENDENCIES.read_text(encoding="utf-8"))
    providers = [
        node
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    assert providers, "no providers found in dependencies.py — has the module moved?"

    for provider in providers:
        shape = [type(statement).__name__ for statement in _statements(provider)]
        assert shape == ["Return"], (
            f"`{provider.name}` is now shaped {shape}. This module wires adapters into use "
            "cases and computes nothing: a completion verdict derived here reaches the client "
            "through a header exactly as well as one derived in the router (R3.2, R3.3)."
        )
        annotations = {
            ast.unparse(argument.annotation)
            for argument in provider.args.args + provider.args.kwonlyargs
            if argument.annotation is not None
        }
        assert not any("Response" in annotation for annotation in annotations), (
            f"`{provider.name}` now takes a `Response`. FastAPI resolves one for any dependency, "
            "not only for the path function, so this is a header channel out of the request "
            "regardless of how few statements the route handler has (R3.2)."
        )
        assert not [
            node
            for node in ast.walk(provider)
            if isinstance(node, ast.Attribute) and node.attr == "headers"
        ], f"`{provider.name}` touches response headers (R3.2)"


def test_the_route_declares_no_dependency_that_could_stamp_a_verdict() -> None:
    """R3.2 — the `dependencies=` kwarg, which `_route_handler` above cannot see.

    That helper matches on `decorator.args[0]`, the path. A `@router.get(..., dependencies=[
    Depends(_stamp)])` is a *keyword* argument, so it never appears in the handler's own
    signature and never changes its two-statement shape — the security reviewer of this change
    named it as the invisible half of the `dependencies.py` escape. FastAPI runs those callables
    for every request to the route and hands each one a `Response` if it asks.
    """
    decorator = _route_decorator(PHOTO_REQUIREMENTS_ROUTE)
    declared = {keyword.arg for keyword in decorator.keywords}
    assert "dependencies" not in declared, (
        "the route now declares `dependencies=`. Anything listed there runs per request and may "
        "take a `Response`, which is a verdict channel this route's guards cannot see from the "
        "handler's body (R3.2). Authorisation belongs in `ReadDep`; nothing else belongs here."
    )


def test_no_dependency_is_injected_above_the_route_either() -> None:
    """R3.2 — the two mounts that outrank the decorator, and outrank the sibling comparison too.

    `dependencies=` can be attached three places, not one: on the route (above), on the
    `APIRouter(...)` this module builds, and on `main.py`'s `include_router` of it. The upper two
    are worse than the route-level one, because they apply to `/checklist` as well — and the
    behavioural header test in `test_photo_requirements_api.py` measures this route **against**
    `/checklist`, so a verdict header stamped from either mount appears on both sides and the
    difference it computes comes out empty. The security reviewer of this change named that: the
    baseline can be poisoned from above. This is the assertion that keeps it honest, and the
    closed header set over there is the other half.
    """
    for node in ast.walk(ast.parse(TASKS_ROUTER.read_text(encoding="utf-8"))):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "APIRouter"
        ):
            declared = {keyword.arg for keyword in node.keywords}
            assert "dependencies" not in declared, (
                "this module's `APIRouter` now declares `dependencies=`. Those callables run for "
                "every route in it — including `/checklist`, which is the baseline the header "
                "test compares against — and each may take a `Response` (R3.2)."
            )
            break
    else:
        raise AssertionError(f"no `APIRouter(...)` call found in {TASKS_ROUTER}")

    mounts = [
        node
        for node in ast.walk(ast.parse(MAIN.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "include_router"
        and node.args
        and isinstance(node.args[0], ast.Name)
        and node.args[0].id == TASKS_ROUTER_MOUNTED_AS
    ]
    assert len(mounts) == 1, (
        f"expected exactly one `include_router({TASKS_ROUTER_MOUNTED_AS})` in {MAIN}, found "
        f"{len(mounts)} — a second mount would answer the same path under other dependencies."
    )
    declared = {keyword.arg for keyword in mounts[0].keywords}
    assert "dependencies" not in declared, (
        f"`{TASKS_ROUTER_MOUNTED_AS}` is now mounted with `dependencies=`. Same channel as the "
        "two above and the least visible of the three: it lives in `main.py`, nowhere near the "
        "route it would stamp (R3.2)."
    )


def test_no_set_algebra_reaches_the_capabilitys_own_code() -> None:
    """R2.2, R3.2, R3.3 — the spelling check, now actually wired to something.

    `SET_ALGEBRA_OPS`, `CONTAINMENT_COMPARISONS` and `SET_METHODS` were declared by the round-1
    fix and referenced by no assertion, so the lesson they record — the operations that compute
    *what is missing*, which is the close's question and not the reporter's — was documented and
    then unenforced. This is defence in depth behind the shape guards, not a replacement: the
    shape guards are what actually hold the line, and a blacklist alone is what two rounds
    already escaped.

    `in`/`not in` are deliberately absent from `CONTAINMENT_COMPARISONS`: membership is exactly
    the question a reporter answers, and `photo.photo_type in uploaded` is the projection's whole
    job (R3.1).
    """
    for label, node in _capability_nodes().items():
        offending_ops = [
            type(inner.op).__name__
            for inner in ast.walk(node)
            if isinstance(inner, ast.BinOp) and isinstance(inner.op, SET_ALGEBRA_OPS)
        ]
        assert not offending_ops, (
            f"{label} now performs set algebra ({', '.join(offending_ops)}). A difference, an "
            "intersection or a union computes what is missing — the close's question, answered "
            "in `CleaningTask.complete()` and nowhere else (R3.3)."
        )
        offending_comparisons = [
            type(op).__name__
            for inner in ast.walk(node)
            if isinstance(inner, ast.Compare)
            for op in inner.ops
            if isinstance(op, CONTAINMENT_COMPARISONS)
        ]
        assert not offending_comparisons, (
            f"{label} now compares sets ({', '.join(offending_comparisons)}). `required <= "
            "uploaded` is 'are all the required ones there?', which is a verdict (R3.2)."
        )
        offending_methods = sorted(
            {
                inner.func.attr
                for inner in ast.walk(node)
                if isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr in SET_METHODS
            }
        )
        assert not offending_methods, (
            f"{label} now calls {', '.join(offending_methods)} — the method spelling of the "
            "same verdict (R3.2)."
        )
