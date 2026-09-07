"""`incident_messages.content`, the free-text sink `staff-messaging` opens on `maintenance`
(R2, R5.3).

Rule 11 of `sdd/steering/security.md` censuses every plaintext sink, attributes its writer,
and says the guarantee "no se propaga" needs its own test rather than the census row's word.
This is that test, the `tests/cleaning/test_free_text_sink_contract.py` shape and NOT the
multi-writer census of `tests/maintenance/test_free_text_sink_contract.py` (a different,
already-existing file for a different set of columns — `incidents.title`/`description` and
friends, several writers each): `incident_messages.content` has exactly **one** writer
(`SendIncidentMessageUseCase`, gated by RBAC — never an anonymous caller), so there is no
multi-writer census to walk here and no reason to grow that file's unrelated concern. A new,
small sibling file is the same choice `cleaning`'s own from-scratch `test_free_text_sink_contract.py`
made for `cleaning_task_messages.content`, and it lives under its own name so it does not
collide with the existing file in this same directory.

What the census row promises and this file pins are the two structural claims: `content`
never reaches `audit_logs.changes`, and it never reaches any `timeline_events.metadata`.
"""

import inspect

import pytest

from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import AUDITABLE_FIELDS, ChangeSet
from app.maintenance.application.use_cases import SendIncidentMessageUseCase
from app.maintenance.domain.entities import MAX_INCIDENT_MESSAGE_LENGTH
from app.maintenance.infrastructure.models import IncidentMessageModel


def test_the_column_is_free_text_bounded_only_by_its_declared_maximum() -> None:
    """The premise: `content` is a `VARCHAR` bounded by `MAX_INCIDENT_MESSAGE_LENGTH`
    (design D5) — "en el DDL y en el esquema", the same pair `incidents.materials` pins.

    The real DDL agreeing with the model is `tests/test_migrations.py`'s job, not this
    file's; what belongs here is that the model and the schema constant agree.
    """
    assert MAX_INCIDENT_MESSAGE_LENGTH == 2000
    assert IncidentMessageModel.__table__.columns["content"].type.length == (
        MAX_INCIDENT_MESSAGE_LENGTH
    )


def test_incident_message_has_no_declared_auditable_fields() -> None:
    """"No se propaga", half one: `audit_logs.changes` (design D6/D7).

    `IncidentMessage` is not an audited entity at all — sending one is not a mutation of
    `Incident`, so `AUDITABLE_FIELDS` never gained an entry for it. That absence is what the
    census row's "no está en `AUDITABLE_FIELDS`" means, and it is a stronger guarantee than a
    merely-empty allowlist: there is no entity type here to accidentally populate.
    """
    assert "INCIDENT_MESSAGE" not in AUDITABLE_FIELDS
    # And `content` does not hide inside the entity `Incident` **is** audited under,
    # confirming a future `ChangeSet("INCIDENT")` could never carry the message's text either.
    assert "content" not in AUDITABLE_FIELDS["INCIDENT"]


def test_constructing_a_change_set_for_the_message_entity_raises() -> None:
    """The same claim, proved from the other side: attempting a `ChangeSet` for this entity is
    refused at construction, before any field is even named — `ChangeSet.__init__` checks the
    entity type against `AUDITABLE_FIELDS` and raises for one it does not recognise.
    """
    with pytest.raises(AuditContractError):
        ChangeSet("INCIDENT_MESSAGE")


def test_the_use_case_holds_no_timeline_collaborator() -> None:
    """"No se propaga", half two: `timeline_events.metadata` (design D6).

    Structural and not merely behavioural: `SendIncidentMessageUseCase.__init__` does not take
    a `TimelineEventRepository` at all — unlike every incident-flow use case, which takes
    `_flow_kwargs()`'s nine collaborators including `timeline`. This use case calls
    `_load_incident_in_scope` directly instead (the same choice `ListIncidentPhotosUseCase`
    makes), so it has no handle on the timeline table to write through even by mistake.
    """
    parameters = inspect.signature(SendIncidentMessageUseCase.__init__).parameters
    assert "timeline" not in parameters
    names = set(parameters) - {"self"}
    assert names == {
        "incidents",
        "messages",
        "users",
        "configs",
        "notifications",
        "uow",
    }, (
        "the use case's collaborators changed: re-check whether a timeline repository was "
        f"added, which would reopen the route this test pins. Found {sorted(names)}"
    )
