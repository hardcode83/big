"""The audit vocabulary `incident-photos` mints, and the one column it refuses to carry.

Its own file, like `test_maintenance_vocabulary.py`, `test_guest_portal_vocabulary.py` and
`test_webhook_endpoint_vocabulary.py`: each change that widens the closed vocabulary of
`app/audit/domain/` states what it added and what it deliberately left out, next to its reason.

What this change adds is small — one entity type, one action, one allowlist entry (design D8) —
and almost all of the value is in the **absences**, so those are what most of these tests pin:
no `storage_key` in the allowlist (R6.2), no delete action, and no new exception to rule 9 of
`sdd/steering/security.md`.
"""

import uuid

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import AUDITABLE_FIELDS, ChangeSet
from app.maintenance.domain.enums import IncidentPhotoStage
from app.maintenance.infrastructure.models import IncidentPhotoModel


def test_the_entity_type_is_declared_and_registered() -> None:
    """R6.1 — its own entity type, not the incident's.

    Registered in `ENTITY_TYPES` as well as declared: the constant alone is inert, and it is
    membership of that frozenset that `ChangeSet` and the audit factory check.
    """
    assert actions.ENTITY_INCIDENT_PHOTO == "INCIDENT_PHOTO"
    assert actions.ENTITY_INCIDENT_PHOTO in actions.ENTITY_TYPES


def test_the_upload_action_is_declared_and_registered() -> None:
    assert actions.INCIDENT_PHOTO_UPLOADED == "INCIDENT_PHOTO_UPLOADED"
    assert actions.INCIDENT_PHOTO_UPLOADED in actions.ACTIONS


def test_this_feature_adds_exactly_one_action_and_one_entity_type() -> None:
    """The proposal keeps every deletion surface out of scope, so the vocabulary has no word
    for it. An action for an operation the API does not offer is exactly the speculative
    vocabulary `app/audit/domain/actions.py` argues against.

    Asserted **exhaustively over the module's namespace** rather than by filtering the action
    set: any new `INCIDENT_PHOTO_*` constant fails this — a delete, a replace, a restore —
    which is the class of addition worth noticing. An earlier version of this test scanned
    `actions.ACTIONS` for the substring instead, and the QA panel of this section pointed out
    that it was the same shape as a test deleted in section 3 for being able to pass vacuously.

    **What it still cannot catch, stated rather than implied**: a deletion action named without
    this prefix. No name-based test can, and the structural guard against *that* is
    `AUDITABLE_FIELDS` plus the fact that a writer has to exist — there is no delete use case,
    no delete route, and `IncidentPhotoRepository` declares no `delete`.
    """
    declared = {
        name
        for name in vars(actions)
        if name.startswith("INCIDENT_PHOTO") or name == "ENTITY_INCIDENT_PHOTO"
    }

    assert declared == {"INCIDENT_PHOTO_UPLOADED", "ENTITY_INCIDENT_PHOTO"}


def test_the_allowlist_is_exactly_what_d8_declares() -> None:
    """R6.2 — three fields, and `storage_key` is not one of them."""
    assert AUDITABLE_FIELDS["INCIDENT_PHOTO"] == frozenset(
        {"stage", "incident_id", "uploaded_by"}
    )


def test_storage_key_is_not_auditable() -> None:
    """**The assertion this file exists for** (R6.2).

    `audit_logs.changes` is a rule-11 sink of `sdd/steering/security.md`, whose contract is that
    a value cannot arrive through it without the column announcing it. `storage_key` is the one
    string this change works to keep out of every response, so writing it into the column
    designed to be dumped would undo that work in the one place nobody looks.

    Stated as its own named test, rather than left implicit in the exact-set assertion above,
    so that the reason is findable when someone later wants the key "just for debugging".
    """
    assert "storage_key" not in AUDITABLE_FIELDS["INCIDENT_PHOTO"]


def test_a_change_set_refuses_storage_key_by_construction() -> None:
    """Not just absent from the allowlist — actually refused at the boundary.

    The allowlist is only a guarantee if something enforces it. `ChangeSet` is that something,
    so this drives the refusal rather than trusting the frozenset.
    """
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_INCIDENT_PHOTO).diff(
            "storage_key", None, "tenants/t/incidents/i/p.jpg"
        )


#: A representative value per allowlisted field, using the type the column actually carries —
#: a native enum and two UUIDs — because `_storable` is what turns those into JSON and a
#: regression there would only show up on the field types nobody tried.
#:
#: Keyed by field name and checked for completeness below, so adding a fourth field to the
#: allowlist without giving it a value here **fails** rather than silently skipping its
#: serialisation check. The QA panel of this section flagged the previous hardcoded list as
#: exactly that latent trap.
_DIFF_VALUES: dict[str, object] = {
    "stage": IncidentPhotoStage.BEFORE,
    "incident_id": uuid.uuid4(),
    "uploaded_by": uuid.uuid4(),
}


def test_the_diff_values_cover_the_whole_allowlist() -> None:
    """The completeness check that makes the parametrisation below trustworthy."""
    assert set(_DIFF_VALUES) == set(AUDITABLE_FIELDS["INCIDENT_PHOTO"])


@pytest.mark.parametrize("field", sorted(AUDITABLE_FIELDS["INCIDENT_PHOTO"]))
def test_every_allowlisted_field_survives_a_real_diff(field: str) -> None:
    """Membership in the allowlist is not the same as being storable.

    Guards the failure mode where an entry is a plausible-looking name that no column matches
    or that `_storable` cannot serialise — either way the entry is dead and the audit row would
    come out empty.
    """
    changes = ChangeSet(actions.ENTITY_INCIDENT_PHOTO).diff(field, None, _DIFF_VALUES[field])

    assert field in changes.as_dict()


@pytest.mark.parametrize("field", sorted(AUDITABLE_FIELDS["INCIDENT_PHOTO"]))
def test_every_allowlisted_name_is_a_real_column(field: str) -> None:
    """The other half of the previous test: each name matches a column of `incident_photos`."""
    assert field in IncidentPhotoModel.__table__.columns


def test_the_upload_is_not_exempt_from_naming_its_actor() -> None:
    """Rule 9 of `steering/security.md`, and design D8's claim that this change asks for no new
    exception to it.

    A person uploads the photo — the assigned technician, or a `PROPERTY_MANAGER` unblocking the
    job — so there is always an actor to name. The exemption set lives in `maintenance`'s
    `_AuditWriter` and holds exactly one action, the automatic classification; this asserts our
    action did not join it.
    """
    from app.maintenance.application.use_cases import _AuditWriter

    assert actions.INCIDENT_PHOTO_UPLOADED not in _AuditWriter._ACTOR_OPTIONAL_ACTIONS
    assert _AuditWriter._ACTOR_OPTIONAL_ACTIONS == frozenset(
        {actions.INCIDENT_CLASSIFIED}
    )


def test_the_photo_vocabularies_do_not_collide() -> None:
    """`CLEANING_PHOTO` and `INCIDENT_PHOTO` are separate entity types with separate allowlists.

    They are near-identical by design (D8 says so), which is exactly why a copy-paste that
    pointed one at the other's allowlist would be easy to miss and hard to see.
    """
    assert actions.ENTITY_INCIDENT_PHOTO != actions.ENTITY_CLEANING_PHOTO
    assert (
        AUDITABLE_FIELDS["INCIDENT_PHOTO"] != AUDITABLE_FIELDS["CLEANING_PHOTO"]
    )
    # The distinguishing field is the stage/type pair: neither allowlist carries the other's.
    assert "photo_type" not in AUDITABLE_FIELDS["INCIDENT_PHOTO"]
    assert "stage" not in AUDITABLE_FIELDS["CLEANING_PHOTO"]
