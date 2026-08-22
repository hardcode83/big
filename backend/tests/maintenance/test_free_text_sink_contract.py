"""The free-text sinks of `incidents`, with the test rule 11 demands of each.

Rule 11 of `sdd/steering/security.md` censuses the free-text columns and says the contract
"lo hereda el change que primero escribe en cada una, **con su propio test**". That table is
where the census and its attribution live — no count and no owner is repeated here. What makes
this file necessary is local: for `title`/`description` the writer at the other end is an
anonymous stranger on the internet, and for `assignment_note` the value is prose typed about a
flat somebody has to get into. So this is that test.

**What is being pinned is the *boundary* of a named exception**, not the prose it allows. The
exception concedes text somebody else wrote; what it explicitly does not concede is that the
value travels, or that any code of ours renders a rule-3 value into these columns. Both of those
are structural today, and structural claims rot silently — a new writer, a new audit field, a
richer timeline payload — which is exactly what these assertions are here to catch.

`assignment_note` joined the sink columns in `tech-incident-context` (R3.5, R3.6, design D8). It
differs from the other two in **which** exception covers it and in nothing this file does: the
mechanism that keeps it out of `audit_logs.changes` and out of `timeline_events` is the same
allowlist and the same constant title, so it rides the same assertions rather than getting a
file of its own.
"""

import ast
from pathlib import Path

import pytest
from sqlalchemy import select

from app.audit.domain import actions as audit_actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import (
    AUDITABLE_FIELDS,
    REDACTED_FIELDS,
    ChangeSet,
)
from app.auth.domain.enums import UserRole
from app.guests.api.portal_schemas import (
    MAX_INCIDENT_DESCRIPTION,
    MAX_INCIDENT_TITLE,
    ReportIncidentRequest,
)
from app.maintenance.application.use_cases import IncidentActor
from app.maintenance.domain.enums import IncidentStatus
from app.maintenance.infrastructure.models import IncidentModel
from app.timeline.domain.enums import TimelineEventType
from app.timeline.infrastructure.models import TimelineEventModel
from tests.maintenance.conftest import (  # noqa: F401
    NOW,
    flow,
    make_incident,
    world,
)

APP_ROOT = Path(__file__).resolve().parents[2] / "app"
SINK_COLUMNS = ("title", "description", "assignment_note")


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


def test_the_three_columns_are_free_text_which_is_why_they_need_this_file() -> None:
    """The premise. `title` and `assignment_note` are bounded by the DDL, `description` is not.

    If a later change gave `description` a width, the field-level maximum below would stop being
    the only bound and this file's reasoning would need revisiting — so the premise is asserted
    rather than assumed.

    `assignment_note`'s width is asserted in the model here and in the **real DDL** in
    `tests/test_migrations.py`, which is the half this file cannot see: the suite's schema comes
    from `Base.metadata.create_all`, so a model and a migration that disagree would both look
    right from here (`tech-incident-context` D6).
    """
    columns = IncidentModel.__table__.columns

    assert columns["title"].type.length == 300
    assert columns["description"].type.length is None
    assert columns["assignment_note"].type.length == 2000


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


def test_naming_a_sink_column_in_a_change_set_raises() -> None:
    """"No se propaga", the same half proved from the other side: it **raises**.

    The test above reads the allowlist; this one drives `ChangeSet` and shows that the absence is
    a refusal rather than a gap somebody has to remember. R3.5 of `tech-incident-context` asks for
    exactly this word — "nombrarla en un `ChangeSet` levanta error, no pasa desapercibida" — and
    the mechanism is the one design D8 chose: absence from the allowlist, not presence in the
    denylist.

    Both forms are driven, because they are two different doors: `diff()` carries the value and
    `redacted()` carries only the fact, and a column outside the allowlist must be refused by
    both. That is what makes this different from `REDACTED_FIELDS`, where `redacted()` is the one
    form that still works.
    """
    for column in SINK_COLUMNS:
        with pytest.raises(AuditContractError):
            ChangeSet(audit_actions.ENTITY_INCIDENT).diff(column, None, "whatever")
        with pytest.raises(AuditContractError):
            ChangeSet(audit_actions.ENTITY_INCIDENT).redacted(column)


def test_the_note_is_excluded_by_absence_and_not_by_the_denylist() -> None:
    """Design D8's choice, asserted so a later change cannot quietly convert it.

    Putting `assignment_note` on `REDACTED_FIELDS` would look stricter and be strictly more
    surface: `wifi_password_encrypted` and `secret_encrypted` demonstrate that denylisting forces
    you to **add** the column to the allowlist as well, or `redacted()` fails too — and then
    `{"changed": true}` starts being written for a field nobody audits.
    """
    assert "assignment_note" not in REDACTED_FIELDS
    assert "assignment_note" not in AUDITABLE_FIELDS[audit_actions.ENTITY_INCIDENT]
    # The eleven fields `maintenance` R9 audits, unchanged.
    assert len(AUDITABLE_FIELDS[audit_actions.ENTITY_INCIDENT]) == 11


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

    # **The whole mapping, not just its keys** — tightened in `tech-incident-context` (task 3.2).
    # The key-set form this replaces treated an allowlist entry as a licence for every sink
    # column at once, so admitting `maintenance/domain/entities.py` for `assignment_note` would
    # have silently admitted a future `self.title = ...` in the one module that can mutate an
    # incident's text. Comparing the mapping costs nothing and keeps each entry as narrow as the
    # reason that earned it.
    assert offenders == {
        "maintenance/application/use_cases.py": {"title", "description", "assignment_note"},
        "maintenance/infrastructure/repositories.py": {
            "title",
            "description",
            "assignment_note",
        },
        # `tech-incident-context` (R3.5, D7): the entity is where the value is actually
        # assigned — `self.assignment_note = assignment_note` inside `Incident.assign`, written
        # unconditionally so the note belongs to the assignment in force. Same contract as the
        # two modules above, so it is the same census row and not a new one.
        "maintenance/domain/entities.py": {"assignment_note"},
        # The three `maintenance` adds are the false positives this docstring predicts, and
        # each is named rather than waved through:
        #
        # * `api/schemas.py` declares `title` and `description` as **response** fields and
        #   fills them in `IncidentResponse.from_domain` — a read of the columns, on the way
        #   out. It cannot write them: a Pydantic DTO has no session, and the only writer of
        #   the row is the adapter above, whose `_MUTABLE_INCIDENT_COLUMNS` excludes both.
        # * The two routers match on FastAPI's own `description=` route metadata — the
        #   documented reason `properties/api/router.py` forced the raw-SQL clause of this
        #   census to be quote-aware in the first place. `incidents_router.py` additionally
        #   matches on `assignment_note=payload.assignment_note`, which is the router
        #   forwarding the field to the use case — a pass-through, not a producer of text.
        #
        # What the entries cost is real and bounded: a genuine write appearing in one of
        # these three would no longer be reported. It would still have to reach the database
        # through the adapter, which is still gated, still allowlisted, and still the only
        # module with an `IncidentModel(...)` in it.
        "maintenance/api/schemas.py": {"title", "description"},
        "maintenance/api/incidents_router.py": {"description", "assignment_note"},
        "maintenance/api/approvals_router.py": {"description"},
        # `seed-data-demo-extension`: the demo seed is the third writer of both columns and the
        # first one outside `maintenance/`. It is here rather than waved through because its
        # contract is declared in the census — **closed form by discipline**: the three PRD §27
        # literals are module constants (`SEED_INCIDENTS`), so no prose of ours is composed and
        # exception 2 is neither invoked nor needed. What the entry does not buy is enforcement:
        # `ReportIncidentUseCase` accepts any `str`, so a future caller that composes text there
        # is under the structured form by default and owes this table a row of its own.
        #
        # It does not pass a note: `AssignIncidentUseCase.execute` is called without one, so the
        # demo dataset leaves `assignment_note` at `NULL` (D7's assumed consequence).
        "cli/seed_demo.py": {"title", "description"},
    }, (
        "a module names one of incidents.title/description/assignment_note in a writing "
        "position: rule 11's exceptions are declared for a specific writer and no other "
        "producer, so a new writer needs its own trip through steering — or, if this is a false "
        "positive of a deliberately coarse census, its own allowlist entry here, narrowed to "
        f"the column that earned it. Found {offenders}"
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


@pytest.mark.asyncio
async def test_the_assignment_timeline_event_carries_only_two_identifiers(
    flow, world, db_session
) -> None:
    """R3.6 — the **exact** key set of the assignment event's `metadata`, on the built row.

    Behavioural and not static, because this is the half no allowlist protects:
    `TimelineEventFactory` only checks that `metadata` is a `dict`, and `timeline_events` is
    append-only, so whatever lands there can never be redacted afterwards. The exact-set form is
    what catches a `metadata=asdict(incident)` — the same shape `revenue-pricing` had to pin for
    `price_recommendations.explanation`, and for the same reason.

    Read this together with the warning it inherits: whoever reads "no se propaga" as a guarantee
    of the framework and deletes this assertion reopens the route.
    """
    note = "El código del portal es 4821"
    incident = await make_incident(db_session, world, status=IncidentStatus.CLASSIFIED)

    await flow.assign.execute(
        tenant_id=world.tenant.id,
        incident_id=incident.id,
        technician_id=world.technician.id,
        actor=IncidentActor(user_id=world.manager.id, role=UserRole.PROPERTY_MANAGER),
        now=NOW,
        assignment_note=note,
    )

    events = (
        (await db_session.execute(select(TimelineEventModel))).scalars().all()
    )
    assignment = [
        event
        for event in events
        if event.event_type is TimelineEventType.TECHNICIAN_ASSIGNED
    ]
    assert len(assignment) == 1
    assert set(assignment[0].metadata_) == {"incident_id", "technician_id"}
    assert "assignment_note" not in assignment[0].metadata_
    assert note not in str(assignment[0].metadata_)
    assert note not in assignment[0].title


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
