from app.core.i18n import Locale
from app.statements.domain.messages import STATEMENTS_ERROR_MESSAGES


def test_statement_error_catalog_covers_both_locales() -> None:
    expected = {
        "owner_statement_not_found",
        "expense_not_found",
        "expense_already_consolidated",
        "named_expense_in_closed_period",
        "owner_statement_invalid_transition",
    }
    assert STATEMENTS_ERROR_MESSAGES.keys == frozenset(expected)
    for key in expected:
        assert STATEMENTS_ERROR_MESSAGES.locales_for(key) == frozenset(Locale)
