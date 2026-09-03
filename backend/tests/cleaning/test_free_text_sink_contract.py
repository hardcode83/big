"""`cleaning_task_messages.content`, the free-text sink `staff-messaging` opens (R5.3).

Rule 11 of `sdd/steering/security.md` censuses every plaintext sink, attributes its writer,
and says the guarantee "no se propaga" needs its own test rather than the census row's word.
This is that test, the `tests/maintenance/test_free_text_sink_contract.py` shape scaled down
to what this column actually needs: unlike `incidents`, `cleaning_task_messages` has exactly
one writer (`SendCleaningTaskMessageUseCase`, gated by RBAC — never an anonymous caller), so
there is no multi-writer census to walk here. What the census row promises and this file pins
are the two structural claims: `content` never reaches `audit_logs.changes`, and it never
reaches any `timeline_events.metadata`.
"""

import inspect

import pytest

from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import AUDITABLE_FIELDS, ChangeSet
from app.cleaning.application.use_cases import SendCleaningTaskMessageUseCase
from app.cleaning.domain.entities import MAX_CLEANING_TASK_MESSAGE_LENGTH
from app.cleaning.infrastructure.models import CleaningTaskMessageModel


def test_the_column_is_free_text_bounded_only_by_its_declared_maximum() -> None:
    """The premise: `content` is a `VARCHAR` bounded by `MAX_CLEANING_TASK_MESSAGE_LENGTH`
    (design D5) — "en el DDL y en el esquema", the same pair `incidents.materials` pins.

    The real DDL agreeing with the model is `tests/test_migrations.py`'s job, not this
    file's; what belongs here is that the model and the schema constant agree.
    """
    assert MAX_CLEANING_TASK_MESSAGE_LENGTH == 2000
    assert CleaningTaskMessageModel.__table__.columns["content"].type.length == (
        MAX_CLEANING_TASK_MESSAGE_LENGTH
    )


def test_cleaning_task_message_has_no_declared_auditable_fields() -> None:
    """"No se propaga", half one: `audit_logs.changes` (design D7).

    `CleaningTaskMessage` is not an audited entity at all — sending one is not a mutation of
    `CleaningTask`, so `AUDITABLE_FIELDS` never gained an entry for it. That absence is what
    the census row's "no está en `AUDITABLE_FIELDS`" means, and it is a stronger guarantee
    than a merely-empty allowlist: there is no entity type here to accidentally populate.
    """
    assert "CLEANING_TASK_MESSAGE" not in AUDITABLE_FIELDS
    # And `content` does not hide inside the entity `CleaningTask` **is** audited under,
    # confirming a future `ChangeSet("CLEANING_TASK")` could never carry the message's text
    # either.
    assert "content" not in AUDITABLE_FIELDS["CLEANING_TASK"]


def test_constructing_a_change_set_for_the_message_entity_raises() -> None:
    """The same claim, proved from the other side: attempting a `ChangeSet` for this entity
    is refused at construction, before any field is even named — `ChangeSet.__init__` checks
    the entity type against `AUDITABLE_FIELDS` and raises for one it does not recognise.

    Both forms are driven for symmetry with the maintenance file's own two-form check, even
    though here the refusal happens one step earlier (at construction, not at `diff`/`redacted`):
    there is no declared entity to name a field of, so there is nothing a caller could
    legitimately do with a `ChangeSet` bound to `content`'s table at all.
    """
    with pytest.raises(AuditContractError):
        ChangeSet("CLEANING_TASK_MESSAGE")


def test_the_use_case_holds_no_timeline_collaborator() -> None:
    """"No se propaga", half two: `timeline_events.metadata` (design D6).

    Structural and not merely behavioural: `SendCleaningTaskMessageUseCase.__init__` does not
    take a `TimelineEventRepository` at all — unlike every task-lifecycle use case, which
    inherits `_TaskTransitionMixin` for both `_load_task` **and** `_transition` and holds one.
    This use case inherits the mixin for `_load_task` alone (the same choice
    `UploadCleaningPhotoUseCase` makes), so it has no handle on the timeline table to write
    through even by mistake.
    """
    parameters = inspect.signature(SendCleaningTaskMessageUseCase.__init__).parameters
    assert "timeline" not in parameters
    names = set(parameters) - {"self"}
    assert names == {"tasks", "messages", "users", "configs", "notifications", "uow"}, (
        "the use case's collaborators changed: re-check whether a timeline repository was "
        f"added, which would reopen the route this test pins. Found {sorted(names)}"
    )
