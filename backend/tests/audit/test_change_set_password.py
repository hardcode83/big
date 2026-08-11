"""The password half of the `USER` audit contract (`auth-account-recovery` R4.4, design D9).

`user-management` is the first writer of a user's audit trail and pinned the contract itself
in `test_change_set.py`; this file pins what this change adds to it — two new actions, and one
new auditable field that is deliberately NOT redacted.

Split from `test_change_set.py` for the same reason `test_change_set_property.py` was: that
file owns the contract, these own one entity's use of it.
"""

import pytest

from app.audit.domain import actions
from app.audit.domain.exceptions import AuditContractError
from app.audit.domain.value_objects import AUDITABLE_FIELDS, ChangeSet


def test_the_two_new_actions_are_part_of_the_closed_vocabulary() -> None:
    """Without this `AuditLogFactory.build` raises and neither operation could be audited."""
    assert actions.USER_PASSWORD_CHANGED in actions.ACTIONS
    assert actions.USER_PASSWORD_RECOVERED in actions.ACTIONS


def test_the_three_password_actions_are_distinct() -> None:
    """Design D9, and the reason it refused to reuse `USER_PASSWORD_RESET` for all three.

    Rule 9 of `steering/security.md` only makes an operation auditable if it can be found by
    filtering on `action`. "An administrator reset it", "the holder changed it" and "the
    holder recovered the account through a mailed link" are exactly the three cases a review
    of an incident has to tell apart; one shared name would make that impossible.
    """
    assert (
        len(
            {
                actions.USER_PASSWORD_RESET,
                actions.USER_PASSWORD_CHANGED,
                actions.USER_PASSWORD_RECOVERED,
            }
        )
        == 3
    )


def test_the_password_itself_still_cannot_be_recorded_as_a_diff() -> None:
    """Rule 11 of `steering/security.md`, unchanged by this change: the value never survives,
    not even masked. Re-asserted here because this change adds two new writers of the column.
    """
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_USER).diff("password", "old-secret", "new-secret")


def test_a_password_change_is_recorded_as_the_fact_that_it_changed() -> None:
    changes = ChangeSet(actions.ENTITY_USER).redacted("password").as_dict()

    assert changes == {"password": {"changed": True}}
    assert "old-secret" not in str(changes)


def test_the_temporary_flag_is_auditable() -> None:
    """R5.1 — `must_change_password` has to be recordable or the transition out of the
    temporary-password state leaves no trail."""
    assert "must_change_password" in AUDITABLE_FIELDS["USER"]


def test_the_temporary_flag_is_recorded_as_a_real_diff_and_not_redacted() -> None:
    """Design D9: it is a boolean of account state, not a value of rule 3.

    Redacting it would throw away the only thing it says. `{"changed": true}` cannot answer
    "did this account stop owing a password change, and when" — which is the question.
    """
    changes = (
        ChangeSet(actions.ENTITY_USER)
        .diff("must_change_password", True, False)
        .as_dict()
    )

    assert changes == {"must_change_password": {"old": True, "new": False}}


def test_a_recovery_records_both_the_redacted_password_and_the_flag() -> None:
    """The shape R3 and R1 actually write (design D9)."""
    changes = (
        ChangeSet(actions.ENTITY_USER)
        .redacted("password")
        .diff("must_change_password", True, False)
        .as_dict()
    )

    assert changes["password"] == {"changed": True}
    assert changes["must_change_password"] == {"old": True, "new": False}


def test_an_undeclared_user_field_is_still_refused() -> None:
    """Adding `must_change_password` must not have opened the allow-list to anything else."""
    with pytest.raises(AuditContractError):
        ChangeSet(actions.ENTITY_USER).diff("password_hash", "a", "b")
