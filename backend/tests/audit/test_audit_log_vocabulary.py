"""The audit vocabulary `demo-tenant-audit-retention` mints.

Its own file, like `test_incident_photo_vocabulary.py`,
`test_maintenance_vocabulary.py` and the rest: each change that widens the closed vocabulary
of `app/audit/domain/` states what it added and what it deliberately left out, next to its
reason.

What this change adds is small — one entity type, one action, one allowlist entry (design D4)
— and almost all the value is in **the absence of any other action**: the demo reset's
`purge-audit` phase is the only writer, and an action for an operation nothing else performs
is exactly the speculative vocabulary `app/audit/domain/actions.py` argues against.
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import AUDITABLE_FIELDS, ChangeSet
from app.audit.infrastructure.models import AuditLogModel


def test_the_entity_type_is_declared_and_registered() -> None:
    """D4: `AUDIT_LOG` joins `ENTITY_TYPES`, alongside the entity it is not borrowing.

    The obvious candidate — `ENTITY_TENANT` — would have the wrong shape: `entity_id` is the
    resource modified, not the scope of the command, and the `ChangeSet` for `TENANT` would
    have no field for `deleted_count` or `cutoff`. A new entity type is the only way to give
    the purge a row that is queryable by `entity_type` and `entity_id`.
    """
    assert actions.ENTITY_AUDIT_LOG == "AUDIT_LOG"
    assert actions.ENTITY_AUDIT_LOG in actions.ENTITY_TYPES


def test_the_purge_action_is_declared_and_registered() -> None:
    """D4: one action, `AUDIT_LOG_PURGED`, registered in `ACTIONS`."""
    assert actions.AUDIT_LOG_PURGED == "AUDIT_LOG_PURGED"
    assert actions.AUDIT_LOG_PURGED in actions.ACTIONS


def test_this_feature_adds_exactly_one_action_and_one_entity_type() -> None:
    """The demo reset's `purge-audit` phase is the only writer; no other action is justified.

    Asserted **exhaustively over the module's namespace** rather than by filtering the action
    set: any new `AUDIT_LOG_*` constant fails this — a restore, a redaction, a freeze — which
    is the class of addition worth noticing. The same shape `test_incident_photo_vocabulary`
    uses, and for the same reason: a substring scan over `actions.ACTIONS` can pass vacuously
    when nothing matches, which is exactly what the QA panel of that change caught.
    """
    declared = {
        name
        for name in vars(actions)
        if name.startswith("AUDIT_LOG") or name == "ENTITY_AUDIT_LOG"
    }

    assert declared == {"AUDIT_LOG_PURGED", "ENTITY_AUDIT_LOG"}


def test_the_allowlist_is_exactly_what_d4_declares() -> None:
    """D4 — two fields, and nothing else: `deleted_count` and `cutoff`.

    Both are scalars (`int` and ISO timestamp string), so neither needs an entry on
    `REDACT_ONLY_FIELDS`. The allowlist is what makes a `ChangeSet(ENTITY_AUDIT_LOG).diff(...)`
    legal; this pins its exact shape.
    """
    assert AUDITABLE_FIELDS["AUDIT_LOG"] == frozenset({"deleted_count", "cutoff"})


def test_a_change_set_carries_deleted_count_and_cutoff() -> None:
    """Smoke test for the smoke test: `_storable` accepts both shapes the writer hands it.

    `deleted_count` arrives as a Python `int` (the `rowcount` of the DELETE), and `cutoff`
    arrives as `cutoff.isoformat()` — the same string SQLAlchemy would emit into a bind
    parameter. The factory rejects a `datetime` on `cutoff` via `_storable` (it converts
    silently, but the writer chose the string form for the diff). Pinned explicitly so the
    diff shape stays reproducible.
    """
    cutoff = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
    changes = (
        ChangeSet(actions.ENTITY_AUDIT_LOG)
        .diff("deleted_count", None, 0)
        .diff("cutoff", None, cutoff.isoformat())
    )

    rendered = changes.as_dict()
    assert rendered["deleted_count"] == {"old": None, "new": 0}
    assert rendered["cutoff"] == {"old": None, "new": cutoff.isoformat()}


def test_a_change_set_refuses_a_field_outside_the_allowlist() -> None:
    """The allowlist is only a guarantee if something enforces it.

    `ChangeSet` is that something. Naming a field that does not exist — say, `entity_type`,
    the natural temptation — raises `AuditContractError`, which is what stops a typo from
    silently writing `{"changed": true}` under a meaningless key.
    """
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_AUDIT_LOG).diff("entity_type", None, "AUDIT_LOG")


#: A representative value per allowlisted field, keyed by field name and checked for
#: completeness below. The QA panel of `incident-photos` flagged the previous hardcoded list
#: as exactly that latent trap; the completeness assertion below is what closes it.
_DIFF_VALUES: dict[str, object] = {
    "deleted_count": 0,
    "cutoff": datetime(2026, 8, 24, 12, 0, tzinfo=UTC) - timedelta(days=7),
}


def test_the_diff_values_cover_the_whole_allowlist() -> None:
    assert set(_DIFF_VALUES) == set(AUDITABLE_FIELDS["AUDIT_LOG"])


@pytest.mark.parametrize("field", sorted(AUDITABLE_FIELDS["AUDIT_LOG"]))
def test_every_allowlisted_field_survives_a_real_diff(field: str) -> None:
    """Membership in the allowlist is not the same as being storable.

    Guards the failure mode where an entry is a plausible-looking name that no column
    matches or that `_storable` cannot serialise — either way the entry is dead and the
    audit row would come out empty. `cutoff` here is a `datetime` rather than a string,
    so `_storable` exercises the `datetime.isoformat()` path; the writer chooses the
    string form, but the column accepts both shapes by construction.
    """
    changes = ChangeSet(actions.ENTITY_AUDIT_LOG).diff(field, None, _DIFF_VALUES[field])

    assert field in changes.as_dict()


@pytest.mark.parametrize("field", sorted(AUDITABLE_FIELDS["AUDIT_LOG"]))
def test_no_allowlisted_name_collides_with_an_audit_log_column(field: str) -> None:
    """The opposite of `incident-photos`'s test, and the right shape for this entity.

    `incident-photos` checks that each allowlisted name matches a column of `incident_photos`
    — there, the diff keys ARE the entity's columns. For `AUDIT_LOG` the diff keys are
    **metadata about the purge**, not attributes of an `audit_logs` row: `deleted_count` and
    `cutoff` are written into the JSONB `changes` column. A diff key that also existed as a
    real column of `audit_logs` would be ambiguous — "was this value stored as a column or
    as part of `changes`?" — so the contract is precisely that none of the allowlisted names
    are columns of `audit_logs`.

    Asserted as its own named test rather than left implicit in the exact-set check, so the
    reason is findable when someone later adds a column and wonders why a diff key cannot
    share its name.
    """
    assert field not in AuditLogModel.__table__.columns


def test_purge_action_carries_no_actor_exemption() -> None:
    """Rule 9 of `steering/security.md` allows the audit row to go without an actor only in
    five named cases, none of them `AUDIT_LOG_PURGED`.

    The demo reset has no actor — same shape as `seed_demo`'s convergence rows — and the
    audit module's own `_ACTOR_OPTIONAL_ACTIONS` would be the place to extend the rule. It
    does not list `AUDIT_LOG_PURGED`, and that is the assertion: this change asks for no new
    exception to rule 9 (R3.1 of the proposal is satisfied by `actor_user_id=None` passing
    through `AuditLogFactory.build` without naming an exemption).
    """
    # `maintenance` is the only module that currently declares an actor-optional set, and
    # the absence there is what the security panels of section 4-5 of `incident-photos`
    # already pinned. Reading it here gives the same shape of test against a vocabulary
    # the run panel can re-check on every section close.
    from app.maintenance.application.use_cases import _AuditWriter

    assert actions.AUDIT_LOG_PURGED not in _AuditWriter._ACTOR_OPTIONAL_ACTIONS


def test_audit_log_entity_type_does_not_collide_with_the_demo_tenant() -> None:
    """The obvious shortcut — re-using `ENTITY_TENANT` — is closed by construction.

    `entity_id` is the resource modified (the purge row itself), not the scope of the
    command (the demo tenant). Reusing `ENTITY_TENANT` would force the `ChangeSet` to lie
    about which table it diffs, and would not let the audit row carry `deleted_count` or
    `cutoff` at all.
    """
    assert actions.ENTITY_AUDIT_LOG != actions.ENTITY_TENANT
    assert "deleted_count" not in AUDITABLE_FIELDS["TENANT"]
    assert "cutoff" not in AUDITABLE_FIELDS["TENANT"]
