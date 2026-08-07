"""R3.1, R3.2 — PRD §11's auto-assignment rule, as a pure function.

Extracted from `ProvisionCleaningTaskUseCase` after the architecture panel of section 4:
the policy is now testable without a tenant, a roster or a session, which is the point of
keeping rules in `domain/`.
"""

import uuid

import pytest

from app.cleaning.domain.assignment import resolve_auto_assignee

A = uuid.uuid4()
B = uuid.uuid4()


def test_exactly_one_active_cleaner_is_assigned():
    assert resolve_auto_assignee(active_cleaner_ids=[A], total_active=1, rejecter_ids=set()) == A


def test_no_active_cleaner_leaves_it_pending():
    assert (
        resolve_auto_assignee(active_cleaner_ids=[], total_active=0, rejecter_ids=set()) is None
    )


@pytest.mark.parametrize("total", [2, 3, 17])
def test_more_than_one_active_cleaner_is_the_managers_choice(total):
    """`total_active`, not the page length: the count is the unpaginated one."""
    assert (
        resolve_auto_assignee(active_cleaner_ids=[A, B], total_active=total, rejecter_ids=set())
        is None
    )


def test_a_page_holding_one_row_of_a_larger_roster_does_not_qualify():
    """The probe page is 2 rows, so a tenant of five arrives as one row plus a total of five."""
    assert (
        resolve_auto_assignee(active_cleaner_ids=[A], total_active=5, rejecter_ids=set()) is None
    )


def test_the_single_cleaner_who_rejected_is_not_reassigned():
    """Design D3 — otherwise the replacement task returns to them for ever."""
    assert (
        resolve_auto_assignee(active_cleaner_ids=[A], total_active=1, rejecter_ids={A}) is None
    )


def test_a_rejecter_who_is_not_the_single_cleaner_is_irrelevant():
    assert resolve_auto_assignee(active_cleaner_ids=[A], total_active=1, rejecter_ids={B}) == A


def test_a_count_of_one_with_an_empty_page_declines():
    """A disagreement between the count and the page is not a tie to break."""
    assert (
        resolve_auto_assignee(active_cleaner_ids=[], total_active=1, rejecter_ids=set()) is None
    )
