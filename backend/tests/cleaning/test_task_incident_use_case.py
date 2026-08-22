"""`ReportTaskIncidentUseCase` — the five steps of D5, and what each refusal must look like.

The four failure paths of R2.3 answer **one indistinguishable `404`**, which is the whole point:
the route must not work as a probe for which cleaning tasks exist. Three of them are exercised
here; the fourth (`property_id` that does not resolve inside the tenant) needs a real database to
be anything other than a fake returning `None`, so it gets one.

**The cross-tenant test runs on an unmarked session, and that is load-bearing.** Under
`bind_session_to_tenant` the listener of `app/core/db.py` filters every statement down to the
`select` of a single column, so a repository that had forgotten its own `WHERE tenant_id` would
still return nothing and the test would pass while the code was wrong. It is written against
`db_session`, which is deliberately not bound, so the `404` it observes is produced by the use
case and not by the framework.
"""

import uuid
from datetime import UTC, datetime

import pytest

from app.auth.domain.enums import UserRole
from app.cleaning.application.use_cases import (
    CleaningActor,
    ReportTaskIncidentUseCase,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.domain.exceptions import (
    CleaningTaskNotFoundError,
    InvalidCleaningTransitionError,
)
from app.cleaning.domain.ports import IncidentReport, IncidentReportedAcknowledgement
from app.cleaning.infrastructure.repositories import SqlAlchemyCleaningTaskRepository
from app.maintenance.domain.enums import IncidentStatus
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from tests.cleaning.conftest import insert_property, insert_task

NOW = datetime(2026, 8, 19, 11, 0, tzinfo=UTC)
REPORT = IncidentReport(
    title="Caldera rota",
    description="No sale agua caliente en el baño.",
)


class _SpyIncidents:
    """The port, recording what it was handed. A fake and not a mock: the contract under test
    is what the use case *passes*, which is the half `maintenance` cannot check for itself."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def report(self, **kwargs) -> IncidentReportedAcknowledgement:
        self.calls.append(kwargs)
        return IncidentReportedAcknowledgement(
            id=uuid.uuid4(), status=IncidentStatus.OPEN, created_at=NOW
        )


def _use_case(db_session, incidents: _SpyIncidents) -> ReportTaskIncidentUseCase:
    return ReportTaskIncidentUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(db_session),
        properties=SqlAlchemyPropertyRepository(db_session),
        incidents=incidents,
    )


def _cleaner(user_id: uuid.UUID) -> CleaningActor:
    return CleaningActor(user_id=user_id, role=UserRole.CLEANER, ip="203.0.113.9")


async def _user(db_session, tenant, role: str = "CLEANER"):
    from app.auth.infrastructure.models import UserModel

    user = UserModel(
        tenant_id=tenant.id,
        name=f"{role.title()} {uuid.uuid4().hex[:6]}",
        email=f"{uuid.uuid4().hex[:12]}@example.com",
        password_hash="hash",
        role=role,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest.mark.asyncio
async def test_the_happy_path_hands_the_port_the_task_and_its_property(
    db_session, tenant_a, property_a, template_a
) -> None:
    """R1.1, R1.4, R4.3: `property_id` is the resolved task's, and `cleaning_task_id` the route's."""
    cleaner = await _user(db_session, tenant_a)
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner,
    )
    incidents = _SpyIncidents()

    acknowledgement = await _use_case(db_session, incidents).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=_cleaner(cleaner.id),
        report=REPORT,
        now=NOW,
    )

    assert acknowledgement.status is IncidentStatus.OPEN
    assert len(incidents.calls) == 1
    call = incidents.calls[0]
    assert call["tenant_id"] == tenant_a.id
    assert call["property_id"] == property_a.id
    assert call["cleaning_task_id"] == task.id
    assert call["actor_user_id"] == cleaner.id
    assert call["report"] is REPORT
    # No `source` to be had: the port does not take one and the writer seals it (R3.1).
    assert "source" not in call


@pytest.mark.asyncio
async def test_an_unknown_task_is_not_found_and_writes_nothing(
    db_session, tenant_a
) -> None:
    """First of R2.3's four paths."""
    incidents = _SpyIncidents()

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=uuid.uuid4(),
            actor=_cleaner(uuid.uuid4()),
            report=REPORT,
            now=NOW,
        )

    assert incidents.calls == []


@pytest.mark.asyncio
async def test_another_tenants_task_is_not_found_on_an_unmarked_session(
    db_session, tenant_a, tenant_b, property_a, template_b
) -> None:
    """Second path, and the one the session choice exists for (Risks, R2.4).

    **Every other step is rigged to succeed, and that is the whole design of this test.** The
    task is `IN_PROGRESS`, assigned to the very cleaner asking for it, and — deliberately —
    points at `property_a`, a property of the *asking* tenant, which the schema permits because
    `cleaning_tasks.property_id` is a single-column foreign key. So the assignee check passes,
    the status gate passes, and `properties.get(tenant_a, …)` resolves. The only thing that can
    produce the `404` is step 1's explicit `tenant_id`.

    The first version of this test used `property_b` and was **measured not to test step 1 at
    all**: with the repository's `WHERE tenant_id` deleted it still passed, because step 4
    refused the foreign property instead. A tenant-isolation test that passes against the
    unscoped repository proves nothing, which is the same lesson `test_repositories.py` records
    about running these on an unmarked session.

    Unmarked session for that second reason too: under `bind_session_to_tenant` the listener of
    `app/core/db.py` filters every statement, so the task would be invisible whatever the
    repository did.
    """
    cleaner = await _user(db_session, tenant_b)
    task = await insert_task(
        db_session,
        tenant_b,
        property_a,
        template_b,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner,
    )
    incidents = _SpyIncidents()

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_cleaner(cleaner.id),
            report=REPORT,
            now=NOW,
        )

    assert incidents.calls == []


@pytest.mark.asyncio
async def test_another_cleaners_task_is_not_found(
    db_session, tenant_a, property_a, template_a
) -> None:
    """Third path: a task of this tenant assigned to somebody else is, for this cleaner,
    indistinguishable from one that does not exist.

    **What this does not prove, measured by the QA panel of section 5**: *which* of the two
    checks refused. Step 2's `restrict_to_cleaner_id` comparison and step 3's
    `_require_assignee` are the same comparison for a `CLEANER`, so deleting either leaves this
    green. That is a property of the code — the use case docstring says why the redundancy is
    kept — and not something another test could tease apart. What is pinned here is the
    outcome R2.2 and R2.3 actually require: this cleaner gets the same `404` as for an unknown
    id, and nothing is written.
    """
    mine = await _user(db_session, tenant_a)
    theirs = await _user(db_session, tenant_a)
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=theirs,
    )
    incidents = _SpyIncidents()

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_cleaner(mine.id),
            report=REPORT,
            now=NOW,
        )

    assert incidents.calls == []


@pytest.mark.asyncio
async def test_a_property_that_does_not_resolve_in_the_tenant_is_not_found(
    db_session, tenant_a, tenant_b, template_a
) -> None:
    """Fourth path, and the reason step 4 exists at all (D5).

    A task of `tenant_a` pointing at a property of `tenant_b` — which the schema permits, because
    `cleaning_tasks.property_id` is a single-column foreign key. Letting the alta in `maintenance`
    catch this instead would answer `MaintenanceValidationError` ⇒ `422`, a body distinguishable
    from the other three refusals, which is exactly the probe R2.3 closes.
    """
    foreign_property = await insert_property(db_session, tenant_b, code="AJENA9")
    cleaner = await _user(db_session, tenant_a)
    task = await insert_task(
        db_session,
        tenant_a,
        foreign_property,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner,
    )
    incidents = _SpyIncidents()

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_cleaner(cleaner.id),
            report=REPORT,
            now=NOW,
        )

    assert incidents.calls == []


@pytest.mark.asyncio
async def test_the_four_refusals_are_one_indistinguishable_error(
    db_session, tenant_a, tenant_b, property_a, property_b, template_a, template_b
) -> None:
    """R2.3 stated as the property it actually is: same type, same message, every time.

    The four tests above each prove their own path; this one proves they cannot be told apart,
    which is the requirement. Asserting the **message** and not only the type, because
    `CleaningTaskNotFoundError` takes an optional argument and a caller that passed "not yours"
    would reopen the probe one layer below the status code.
    """
    mine = await _user(db_session, tenant_a)
    theirs = await _user(db_session, tenant_a)
    their_tenant_cleaner = await _user(db_session, tenant_b)
    foreign_property = await insert_property(db_session, tenant_b, code="AJENA7")

    others_task = await insert_task(
        db_session, tenant_a, property_a, template_a,
        status=CleaningTaskStatus.IN_PROGRESS, cleaner=theirs,
    )
    other_tenant_task = await insert_task(
        db_session, tenant_b, property_b, template_b,
        status=CleaningTaskStatus.IN_PROGRESS, cleaner=their_tenant_cleaner,
    )
    unresolvable_property_task = await insert_task(
        db_session, tenant_a, foreign_property, template_a,
        status=CleaningTaskStatus.IN_PROGRESS, cleaner=mine,
    )

    messages = set()
    for task_id in (
        uuid.uuid4(),
        other_tenant_task.id,
        others_task.id,
        unresolvable_property_task.id,
    ):
        with pytest.raises(CleaningTaskNotFoundError) as refusal:
            await _use_case(db_session, _SpyIncidents()).execute(
                tenant_id=tenant_a.id,
                task_id=task_id,
                actor=_cleaner(mine.id),
                report=REPORT,
                now=NOW,
            )
        messages.add(str(refusal.value))

    assert len(messages) == 1, f"the four refusals are distinguishable: {messages}"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        CleaningTaskStatus.COMPLETED,
        CleaningTaskStatus.REJECTED,
        CleaningTaskStatus.CANCELLED,
    ],
)
async def test_a_terminal_task_conflicts_instead_of_reporting(
    db_session, tenant_a, property_a, template_a, status: CleaningTaskStatus
) -> None:
    """R2.5's `409`, and it is reached only by the assignee — the three `404`s come first."""
    cleaner = await _user(db_session, tenant_a)
    task = await insert_task(
        db_session, tenant_a, property_a, template_a, status=status, cleaner=cleaner
    )
    incidents = _SpyIncidents()

    with pytest.raises(InvalidCleaningTransitionError):
        await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_cleaner(cleaner.id),
            report=REPORT,
            now=NOW,
        )

    assert incidents.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [
        CleaningTaskStatus.ASSIGNED,
        CleaningTaskStatus.ACCEPTED,
        CleaningTaskStatus.IN_PROGRESS,
    ],
)
async def test_every_working_status_may_report(
    db_session, tenant_a, property_a, template_a, status: CleaningTaskStatus
) -> None:
    """R2.5's positive half, through the use case rather than only on the entity: PRD §12's
    "durante checklist" includes the moment before pressing start."""
    cleaner = await _user(db_session, tenant_a)
    task = await insert_task(
        db_session, tenant_a, property_a, template_a, status=status, cleaner=cleaner
    )
    incidents = _SpyIncidents()

    await _use_case(db_session, incidents).execute(
        tenant_id=tenant_a.id,
        task_id=task.id,
        actor=_cleaner(cleaner.id),
        report=REPORT,
        now=NOW,
    )

    assert len(incidents.calls) == 1


@pytest.mark.asyncio
async def test_a_manager_is_not_restricted_to_her_own_assignments_but_still_needs_the_gate(
    db_session, tenant_a, property_a, template_a
) -> None:
    """`restrict_to_cleaner_id` is `None` for every role but `CLEANER`, and the entity gate must
    still apply — which is why step 3 passes `actor.user_id` rather than the restriction.

    A `PROPERTY_MANAGER` does not hold `EXECUTE_CLEANING_TASKS` so cannot reach this route today
    (R2.1); the test exists because the use case must not depend on that being true forever.
    """
    manager = await _user(db_session, tenant_a, role="PROPERTY_MANAGER")
    cleaner = await _user(db_session, tenant_a)
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner,
    )
    incidents = _SpyIncidents()

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=CleaningActor(
                user_id=manager.id, role=UserRole.PROPERTY_MANAGER, ip=None
            ),
            report=REPORT,
            now=NOW,
        )

    assert incidents.calls == []


@pytest.mark.asyncio
async def test_the_reported_text_never_reaches_the_log(
    db_session, tenant_a, property_a, template_a, caplog
) -> None:
    """R5.4: `task_id` and `incident_id`, never the text.

    Rule 11's "no se propaga" clause means the value does not leave the two columns, and a log
    line is a place it would leave them to — one no redaction can reach afterwards. The clause
    that covers a cleaner is **excepción 3** (a person authenticated with RBAC writing about
    their own scope), not the 2nd, which is the anonymous portal reporter; D9 turns on exactly
    that distinction.
    """
    import logging

    cleaner = await _user(db_session, tenant_a)
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=cleaner,
    )
    incidents = _SpyIncidents()

    with caplog.at_level(logging.INFO, logger="app.cleaning.application.use_cases"):
        acknowledgement = await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_cleaner(cleaner.id),
            report=REPORT,
            now=NOW,
        )

    emitted = [r for r in caplog.records if r.message == "cleaning.task_incident_reported"]
    assert len(emitted) == 1
    record = emitted[0]
    assert record.cleaning_task_id == str(task.id)
    assert record.incident_id == str(acknowledgement.id)

    whole_log = "\n".join(f"{r.message} {r.__dict__}" for r in caplog.records)
    assert REPORT.title not in whole_log
    assert REPORT.description not in whole_log


@pytest.mark.asyncio
async def test_an_unassigned_task_is_refused_even_for_a_role_with_no_restriction(
    db_session, tenant_a, property_a, template_a
) -> None:
    """The one case that separates step 3's argument from step 2's, and the reason it is
    `actor.user_id` (D5).

    Raised by the QA panel of section 5, which measured that swapping
    `assert_incident_reportable(actor.user_id)` for `assert_incident_reportable(restrict)` left
    all fourteen tests green. Every one of them used a task assigned to *somebody*, so `None !=
    assigned` and `user_id != assigned` refused alike and the two arguments were
    indistinguishable.

    An **unassigned** task with a non-`CLEANER` actor is where they part: `restrict` is `None`
    for that role and `assigned_cleaner_id` is `None` on the row, so passing the restriction
    would satisfy `_require_assignee` by `None == None` and let a manager open an incident on a
    task nobody has been given. Passing `actor.user_id` refuses, which is what this pins.

    Not reachable today — R2.1 confines the route to `CLEANER` — but "not reachable today" is
    exactly the premise `_require_assignee`'s own docstring refuses to rest on.
    """
    manager = await _user(db_session, tenant_a, role="PROPERTY_MANAGER")
    task = await insert_task(
        db_session,
        tenant_a,
        property_a,
        template_a,
        status=CleaningTaskStatus.IN_PROGRESS,
        cleaner=None,
    )
    assert task.assigned_cleaner_id is None
    incidents = _SpyIncidents()

    with pytest.raises(CleaningTaskNotFoundError):
        await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=CleaningActor(
                user_id=manager.id, role=UserRole.PROPERTY_MANAGER, ip=None
            ),
            report=REPORT,
            now=NOW,
        )

    assert incidents.calls == []


@pytest.mark.asyncio
async def test_a_terminal_task_conflicts_even_when_its_property_would_not_resolve(
    db_session, tenant_a, tenant_b, template_a
) -> None:
    """The precedence R2.3 and R2.5 both claim, pinned so the step order cannot drift.

    One row satisfies both criteria: the caller's own task, terminal, pointing at a property
    outside the tenant. R2.3 lists the unresolvable property among its four `404`s and R2.5
    calls the terminal status a `409`. The order settles it — step 3 runs before step 4 — and
    the `409` wins.

    That is the right way round rather than an accident of ordering: reaching this point means
    steps 1 and 2 already passed, so the task is the caller's own and the conflict tells them
    nothing they did not have. Inverting it would mean resolving the property before the state
    gate, and a terminal-status `409` would become reachable for a task belonging to somebody
    else — which is precisely what `_require_assignee`-before-`_require_status` closes inside
    the entity.

    Raised as an untested edge by the QA panel of section 5, after the architect found the two
    requirements contradicted each other on this row.
    """
    foreign_property = await insert_property(db_session, tenant_b, code="AJENA5")
    cleaner = await _user(db_session, tenant_a)
    task = await insert_task(
        db_session,
        tenant_a,
        foreign_property,
        template_a,
        status=CleaningTaskStatus.COMPLETED,
        cleaner=cleaner,
    )
    incidents = _SpyIncidents()

    with pytest.raises(InvalidCleaningTransitionError):
        await _use_case(db_session, incidents).execute(
            tenant_id=tenant_a.id,
            task_id=task.id,
            actor=_cleaner(cleaner.id),
            report=REPORT,
            now=NOW,
        )

    assert incidents.calls == []
