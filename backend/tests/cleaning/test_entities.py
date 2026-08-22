import uuid
from datetime import datetime, timezone

import pytest

from app.cleaning.domain.entities import (
    INCIDENT_REPORTABLE_STATUSES,
    CleaningChecklistCompletion,
    CleaningChecklistTemplate,
    CleaningPhoto,
    CleaningTask,
)
from app.cleaning.domain.enums import CleaningTaskStatus, CleaningValidationStatus
from app.cleaning.domain.exceptions import (
    CleaningTaskNotFoundError,
    InvalidCleaningTransitionError,
)


def test_cleaning_task_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    task = CleaningTask(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        checklist_template_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
    )

    assert task.status == CleaningTaskStatus.CREATED
    assert task.validation_status == CleaningValidationStatus.PENDING
    assert task.reservation_id is None
    assert task.assigned_cleaner_id is None


def test_cleaning_checklist_template_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    template = CleaningChecklistTemplate(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="Standard checklist",
        items=[{"id": "ventilate", "label_es": "Ventilar", "label_en": "Ventilate", "required": True, "order": 1}],
        required_photos=[{"id": "living_room", "label_es": "Salón", "label_en": "Living room", "required": True}],
        created_at=now,
        updated_at=now,
    )

    assert template.active is True
    assert template.property_id is None


def test_cleaning_checklist_completion_instantiates_with_defaults() -> None:
    completion = CleaningChecklistCompletion(
        id=uuid.uuid4(),
        cleaning_task_id=uuid.uuid4(),
        item_id="ventilate",
    )

    assert completion.completed is False
    assert completion.completed_at is None
    assert completion.completed_by is None


def test_cleaning_photo_instantiates_with_defaults() -> None:
    now = datetime.now(timezone.utc)
    photo = CleaningPhoto(
        id=uuid.uuid4(),
        cleaning_task_id=uuid.uuid4(),
        uploaded_by=uuid.uuid4(),
        photo_type="living_room",
        storage_key="cleaning/2026-07-17/living_room.jpg",
        created_at=now,
    )

    assert photo.ai_validation_result is None


# --- the incident-reporting gate (`cleaner-incident-report` R2.5, design D6) ---------------


def _task(
    status: CleaningTaskStatus, *, assigned_cleaner_id: uuid.UUID | None = None
) -> CleaningTask:
    now = datetime.now(timezone.utc)
    return CleaningTask(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        property_id=uuid.uuid4(),
        checklist_template_id=uuid.uuid4(),
        created_at=now,
        updated_at=now,
        status=status,
        assigned_cleaner_id=assigned_cleaner_id,
    )


def test_the_reportable_statuses_are_declared_by_inclusion() -> None:
    """D6, and **by inclusion rather than by exclusion of the three terminal ones**.

    This is a write surface for the least privileged role, so a status added tomorrow must not
    become reportable by omission. Written out literally rather than derived, so that adding a
    member to `CleaningTaskStatus` cannot silently widen it.
    """
    assert INCIDENT_REPORTABLE_STATUSES == frozenset(
        {
            CleaningTaskStatus.ASSIGNED,
            CleaningTaskStatus.ACCEPTED,
            CleaningTaskStatus.IN_PROGRESS,
        }
    )


def test_the_assigned_cleaner_may_report_from_every_reportable_status() -> None:
    """R2.5: "cualquier estado en el que la limpiadora pueda estar trabajando".

    Deliberately wider than the photo upload, which is `IN_PROGRESS` only: a photo is evidence
    of the checklist and exists only while the work happens, but a broken boiler is a fact about
    the flat that the cleaner meets on opening the door, before pressing "start".
    """
    cleaner = uuid.uuid4()

    for status in sorted(INCIDENT_REPORTABLE_STATUSES, key=lambda s: s.value):
        task = _task(status, assigned_cleaner_id=cleaner)

        task.assert_incident_reportable(cleaner)


@pytest.mark.parametrize(
    "status",
    [
        CleaningTaskStatus.CREATED,
        CleaningTaskStatus.PENDING_REVIEW,
        CleaningTaskStatus.FAILED,
        CleaningTaskStatus.COMPLETED,
        CleaningTaskStatus.REJECTED,
        CleaningTaskStatus.CANCELLED,
    ],
)
def test_every_other_status_is_refused_with_a_transition_error(
    status: CleaningTaskStatus,
) -> None:
    """The six that are not in the set, named one by one rather than derived from it.

    Deriving them as `set(CleaningTaskStatus) - INCIDENT_REPORTABLE_STATUSES` would make this
    test agree with the constant by construction and prove nothing — and iterating a `frozenset`
    to build parametrize ids is what `steering/testing.md` forbids, because the ids would
    differ between CI workers.

    `InvalidCleaningTransitionError` already maps to `409` in `cleaning/api/errors.py`, so R2.5
    needs no new exception.
    """
    cleaner = uuid.uuid4()
    task = _task(status, assigned_cleaner_id=cleaner)

    with pytest.raises(InvalidCleaningTransitionError):
        task.assert_incident_reportable(cleaner)


def test_a_task_of_another_cleaner_is_not_found_rather_than_conflicting() -> None:
    """R2.3, and the ordering that makes it true.

    `_require_assignee` runs **before** `_require_status`: a `409` saying "cannot report on a
    task in status COMPLETED" would confirm to an unrelated cleaner that the task exists and
    what it is doing, which is the probe the `404` closes.
    """
    task = _task(CleaningTaskStatus.IN_PROGRESS, assigned_cleaner_id=uuid.uuid4())

    with pytest.raises(CleaningTaskNotFoundError):
        task.assert_incident_reportable(uuid.uuid4())


def test_the_assignee_is_checked_before_the_status() -> None:
    """The order itself, on a task that would fail **both** checks.

    Without this, swapping the two lines leaves every other test in this file green: each of
    them fails only one of the two conditions.
    """
    task = _task(CleaningTaskStatus.COMPLETED, assigned_cleaner_id=uuid.uuid4())

    with pytest.raises(CleaningTaskNotFoundError):
        task.assert_incident_reportable(uuid.uuid4())


def test_an_unassigned_task_is_not_found_for_anyone() -> None:
    """`CREATED` is out of the set, and for the only role holding the permission it is a `404`
    before it is a `409` anyway: nobody has been handed it, so `assigned_cleaner_id` is NULL."""
    task = _task(CleaningTaskStatus.CREATED)

    with pytest.raises(CleaningTaskNotFoundError):
        task.assert_incident_reportable(uuid.uuid4())
