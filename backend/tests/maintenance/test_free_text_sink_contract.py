"""`incidents.title`/`description` as a rule-11 sink, with the test the rule demands.

Rule 11 of `sdd/steering/security.md` censuses the free-text columns and says the contract
"lo hereda el change que primero escribe en cada una, **con su propio test**". That table is
where the census and its attribution live — no count and no owner is repeated here. What makes
this file necessary is local: the writer at the other end is an anonymous stranger on the
internet, so this is that test.

**What is being pinned is the *boundary* of the second named exception**, not the prose it
allows. The exception concedes text a third party wrote; what it explicitly does not concede is
that the value travels, or that any code of ours renders a rule-3 value into these columns. Both
of those are structural today, and structural claims rot silently — a new writer, a new audit
field, a richer timeline payload — which is exactly what these assertions are here to catch.
"""

import ast
from pathlib import Path

from app.audit.domain import actions as audit_actions
from app.audit.domain.value_objects import AUDITABLE_FIELDS
from app.guests.api.portal_schemas import (
    MAX_INCIDENT_DESCRIPTION,
    MAX_INCIDENT_TITLE,
    ReportIncidentRequest,
)
from app.maintenance.infrastructure.models import IncidentModel

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
SINK_COLUMNS = ("title", "description")


def _writes_incidents_in_raw_sql(tree: ast.Module) -> bool:
    """Whether any string literal in the module looks like a raw write against `incidents`.

    The third clause of the census gate, and it is deliberately about **string literals with a
    write verb** rather than the bare word. A quote-agnostic substring search over the source
    matched `properties/api/router.py`, which mentions incidents in prose and uses FastAPI's own
    `description=` — a false positive whose only honest resolutions were an allowlist entry that
    explains nothing, or this.
    """
    return any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and "incidents" in node.value.lower()
        and any(verb in node.value.lower() for verb in ("insert", "update", "merge"))
        for node in ast.walk(tree)
    )


def test_the_two_columns_are_free_text_which_is_why_they_need_this_file() -> None:
    """The premise. `title` is bounded by the DDL, `description` is not bounded at all.

    If a later change gave `description` a width, the field-level maximum below would stop being
    the only bound and this file's reasoning would need revisiting — so the premise is asserted
    rather than assumed.
    """
    columns = IncidentModel.__table__.columns

    assert columns["title"].type.length == 300
    assert columns["description"].type.length is None


def test_what_the_reporter_writes_cannot_reach_the_audit_sink() -> None:
    """"No se propaga", half one: `audit_logs.changes`.

    `ChangeSet` refuses a field outside the entity's allowlist, so this is enforced by
    construction — and the allowlist is what a future change would edit without noticing that
    it is also the boundary of a steering exception.
    """
    allowlist = AUDITABLE_FIELDS[audit_actions.ENTITY_INCIDENT]

    for column in SINK_COLUMNS:
        assert column not in allowlist, (
            f"{column!r} entered AUDITABLE_FIELDS['INCIDENT']: rule 11's second exception is "
            "bounded to the incidents columns themselves, and does not authorise auditing what "
            "the guest typed"
        )


def test_the_timeline_entry_carries_neither_of_them() -> None:
    """"No se propaga", half two: `timeline_events`, which is append-only.

    Read from the source rather than by running the use case — the behavioural version lives in
    `test_report_guest_incident.py`. What this adds is that the title is a **constant**: a
    future edit interpolating the guest's own title would satisfy every behavioural assertion
    that only checks "not equal to the fixture's title".
    """
    source = (APP_ROOT / "maintenance" / "application" / "use_cases.py").read_text(
        encoding="utf-8"
    )
    tree = ast.parse(source)

    timeline_title = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "_TIMELINE_TITLE"
            for target in node.targets
        )
    )

    assert isinstance(timeline_title, ast.Constant), (
        "_TIMELINE_TITLE stopped being a literal: the timeline is immutable, so a value "
        "assembled from the report cannot be redacted afterwards (design D12)"
    )
    assert isinstance(timeline_title.value, str) and timeline_title.value.strip()


def test_the_only_writer_of_the_two_columns_is_the_incident_adapter() -> None:
    """The census, done the way rule 11 says: by **who writes the column**.

    The exception concedes the reporter's own prose. It does not concede a writer of ours
    rendering a rule-3 value into these columns — a lock alert pasting an access code, a
    classifier summarising a WiFi password. Such a writer would be a second producer of this
    text, and would need its own trip through steering rather than inheriting this one.

    So the check is a census of production modules that name these columns in any position that
    writes them. Today there is exactly one, and its input is the request body.

    **The first version of this census matched one syntactic form and the security panel showed
    the hole**: it only saw `IncidentModel(...)` where the callee was a bare name, plus
    attribute assignment. It was blind to `models.IncidentModel(...)`,
    `update(IncidentModel).values(description=…)` and `insert(...).values(...)` — and a
    `values()` update is precisely how the classifier this exception names as the dangerous
    future writer would touch `description`.

    So the write forms are matched broadly — any keyword argument, any attribute assignment,
    `setattr` — but only inside a **gated** set of modules. The gate is what makes the census mean
    something: `title=` and `description=` are also FastAPI's own route metadata and the
    timeline's event fields, so an ungated version reports twenty-four modules and its allowlist
    would have to name them all, which proves nothing.

    **The gate itself was wrong twice, and the second time is worth recording.** Version two
    gated on the source naming `IncidentModel` — which skipped
    `maintenance/application/use_cases.py`, the module that *decides* what goes in those columns:
    it names `Incident`, `IncidentSource`, `IncidentRepository` and never `IncidentModel`. So the
    broad form-matching never ran on the one file where a second producer would naturally be
    written, and a future `ClassifyIncidentUseCase` assigning `incident.description = ai_summary`
    would have kept this green. Caught by the security panel, which walked the gate instead of
    the matcher. The gate is now the **package** — everything under `app/maintenance/` — plus any
    module anywhere that names the ORM class or the table, quote-agnostically for the raw-SQL
    case.

    The allowlist consequently names **two** modules rather than one, which is more honest: the
    use case composes the text and the adapter persists it, and both are the declared writer.

    **And the gate was wrong a third time, which is the one that says why this keeps happening.**
    `seed-data-demo-extension` (2026-08-17) made `app/cli/seed_demo.py` a writer of both columns,
    and the gate did not see it: it is not under `maintenance/`, it never names `IncidentModel`,
    and its only `"incidents"` literals are dict keys of the console counts with no write verb
    beside them. Its census row was added by a human reviewer noticing, which is exactly the
    failure mode rule 11 warns about — «una columna viva puede ganar escritores sin que la fila lo
    note». The lesson is that the gate had been tracking *where the column is persisted* while
    producers accumulate *wherever the use case is callable from*. So the gate now also follows
    the door: any module naming **`ReportIncidentUseCase`**, the generic creation path that change
    opened and that the lock alert announced in `maintenance/api/incidents_router.py` will come
    through. A CLI is the first caller outside the package; it will not be the last.

    **And the gate keys on names, which is the residual — written down rather than left implied**,
    because the security panel's re-review pointed out that a module receiving the use case as an
    injected collaborator names neither the class nor the ORM model. That is why the port itself
    (`IncidentRepository`) is a clause too: anything that can reach the row has to hold the port
    somewhere, and the five extra modules that clause admits —`guests/api/portal_dependencies.py`,
    the three of `messaging/`, and `scheduler/tasks.py`— turn out to write neither column, so the
    offender set is unchanged and the gate is strictly stronger for free. What would still evade
    it is a caller typed only against a protocol alias that mentions none of the four names; if
    that ever appears, the fifth clause is the import graph rather than another substring.
    """
    gated_prefix = "maintenance/"
    offenders: dict[str, set[str]] = {}
    for module_path in sorted(APP_ROOT.glob("**/*.py")):
        relative = str(module_path.relative_to(APP_ROOT))
        source = module_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        if not (
            relative.startswith(gated_prefix)
            or "IncidentModel" in source
            or "ReportIncidentUseCase" in source
            or "IncidentRepository" in source
            or _writes_incidents_in_raw_sql(tree)
        ):
            continue
        writes: set[str] = set()
        for node in ast.walk(tree):
            # Any `foo(title=…)` / `.values(description=…)`, whatever the callee looks like.
            if isinstance(node, ast.Call):
                writes.update(
                    keyword.arg
                    for keyword in node.keywords
                    if keyword.arg in SINK_COLUMNS
                )
            # Any `something.title = …`, including augmented and annotated assignment.
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            writes.update(
                target.attr
                for target in targets
                if isinstance(target, ast.Attribute) and target.attr in SINK_COLUMNS
            )
            # `setattr(row, "description", …)`, the escape an AST check invites.
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "setattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value in SINK_COLUMNS
            ):
                writes.add(str(node.args[1].value))
        if writes:
            offenders[relative] = writes

    assert set(offenders) == {
        "maintenance/application/use_cases.py",
        "maintenance/infrastructure/repositories.py",
        # The three `maintenance` adds are the false positives this docstring predicts, and
        # each is named rather than waved through:
        #
        # * `api/schemas.py` declares `title` and `description` as **response** fields and
        #   fills them in `IncidentResponse.from_domain` — a read of the columns, on the way
        #   out. It cannot write them: a Pydantic DTO has no session, and the only writer of
        #   the row is the adapter above, whose `_MUTABLE_INCIDENT_COLUMNS` excludes both.
        # * The two routers match on FastAPI's own `description=` route metadata — the
        #   documented reason `properties/api/router.py` forced the raw-SQL clause of this
        #   census to be quote-aware in the first place.
        #
        # What the entries cost is real and bounded: a genuine write appearing in one of
        # these three would no longer be reported. It would still have to reach the database
        # through the adapter, which is still gated, still allowlisted, and still the only
        # module with an `IncidentModel(...)` in it.
        "maintenance/api/schemas.py",
        "maintenance/api/incidents_router.py",
        "maintenance/api/approvals_router.py",
        # `seed-data-demo-extension`: the demo seed is the third writer of both columns and the
        # first one outside `maintenance/`. It is here rather than waved through because its
        # contract is declared in the census — **closed form by discipline**: the three PRD §27
        # literals are module constants (`SEED_INCIDENTS`), so no prose of ours is composed and
        # exception 2 is neither invoked nor needed. What the entry does not buy is enforcement:
        # `ReportIncidentUseCase` accepts any `str`, so a future caller that composes text there
        # is under the structured form by default and owes this table a row of its own.
        "cli/seed_demo.py",
    }, (
        "a module names incidents.title/description in a writing position: rule 11's second "
        "exception is declared for the reporter's own prose and no other producer, so a new "
        "writer needs its own trip through steering — or, if this is a false positive of a "
        f"deliberately coarse census, its own allowlist entry here. Found {offenders}"
    )


def test_the_census_catches_the_escapes_it_claims_to() -> None:
    """The enforcement mechanism gets its own test, as `test_layering.py` does for its own.

    Every case here is a form that a previous version of the census missed, or that its gate
    would have skipped. They are pinned because the census is only worth its runtime if a future
    tidy-up of this file cannot quietly narrow it back.
    """
    # The gate's raw-SQL clause: a write verb plus the table, whatever the quoting.
    assert _writes_incidents_in_raw_sql(
        ast.parse("q = text('UPDATE incidents SET description = :d')")
    )
    assert _writes_incidents_in_raw_sql(
        ast.parse('q = text("INSERT INTO incidents (title) VALUES (:t)")')
    )
    # Prose mentioning incidents is not a writer — the false positive that made the bare
    # substring version report `properties/api/router.py`.
    assert not _writes_incidents_in_raw_sql(
        ast.parse('"""Properties can have incidents attached to them."""')
    )
    assert not _writes_incidents_in_raw_sql(ast.parse('x = "incidents"'))

    # And the forms the matcher itself must see. Asserted through the same helper shape the
    # census uses, so a narrowing of one is caught here rather than in six months.
    for snippet in (
        "models.IncidentModel(title=t, description=d)",
        "update(IncidentModel).values(description=d)",
        "insert(IncidentModel).values(title=t)",
        "incident.description = summary",
        "incident.title += suffix",
        'setattr(incident, "description", summary)',
    ):
        tree = ast.parse(snippet)
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                found.update(k.arg for k in node.keywords if k.arg in SINK_COLUMNS)
                if (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "setattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in SINK_COLUMNS
                ):
                    found.add(str(node.args[1].value))
            targets: list[ast.expr] = []
            if isinstance(node, ast.Assign):
                targets = list(node.targets)
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            found.update(
                target.attr
                for target in targets
                if isinstance(target, ast.Attribute) and target.attr in SINK_COLUMNS
            )
        assert found, f"the census would not see {snippet!r}"


def test_the_anonymous_boundary_bounds_what_can_land_there() -> None:
    """What acots the risk, since the value is not structured: types, length, no control chars.

    The exception's text leans on exactly these three, so they are asserted here and not only
    where the schema is tested — a `max_length` quietly removed would widen a steering exception,
    which is not something to discover from a rendered incident list.
    """
    fields = ReportIncidentRequest.model_fields

    assert MAX_INCIDENT_TITLE == 300
    assert MAX_INCIDENT_DESCRIPTION == 5000
    for name, maximum in (
        ("title", MAX_INCIDENT_TITLE),
        ("description", MAX_INCIDENT_DESCRIPTION),
    ):
        constraints = {
            type(item).__name__: item for item in fields[name].metadata
        }
        assert any(
            getattr(item, "max_length", None) == maximum
            for item in fields[name].metadata
        ), f"{name} lost its maximum: {constraints}"
        assert "AfterValidator" in constraints, (
            f"{name} lost its control-character guard, which is one of the three things "
            "rule 11's second exception names as what bounds an anonymous writer"
        )

    assert ReportIncidentRequest.model_config["extra"] == "forbid"
    assert ReportIncidentRequest.model_config["str_strip_whitespace"] is True
