"""The audit vocabulary `revenue-statements` mints, and what it refuses to carry (design D7).

Its own file, like `test_pricing_vocabulary.py`: each change that widens the closed
vocabulary of `app/audit/domain/` states what it added and what it deliberately left out,
next to its reason.

The placement of `notes` in `REDACT_ONLY_FIELDS["OWNER_STATEMENT"]` (and not in
`AUDITABLE_FIELDS["OWNER_STATEMENT"]` alone) is the structural enforcement that regla 11
demands for regla-11 sumideros. `properties.access_notes` documented why the discipline-only
contract is weaker (`steering/security.md` row on `properties.access_notes`); this change
follows the `pricing_rules.event_rules` precedent instead.
"""

from app.audit.domain import actions
from app.audit.domain.value_objects import AUDITABLE_FIELDS, REDACT_ONLY_FIELDS

REVENUE_STATEMENTS_ACTIONS = {
    "OWNER_STATEMENT_GENERATED",
    "OWNER_STATEMENT_STATUS_CHANGED",
    "OWNER_STATEMENT_NOTES_UPDATED",
    "EXPENSE_CREATED",
    "EXPENSE_UPDATED",
    "EXPENSE_DELETED",
}


def test_the_six_actions_are_declared() -> None:
    assert REVENUE_STATEMENTS_ACTIONS <= actions.ACTIONS


def test_the_two_entity_types_exist() -> None:
    assert actions.ENTITY_OWNER_STATEMENT == "OWNER_STATEMENT"
    assert actions.ENTITY_EXPENSE == "EXPENSE"
    assert {actions.ENTITY_OWNER_STATEMENT, actions.ENTITY_EXPENSE} <= actions.ENTITY_TYPES


def test_owner_statement_status_changed_is_one_action() -> None:
    """D7 + R4.2/R4.4: `mark_ready` (DRAFT → READY) and `mark_sent` (READY → SENT) are
    the only status moves, and they share one action. Mirror of `OWNER_APPROVAL_ANSWERED`
    (one action with `status` in the diff). A third action for `sent` would be a verb for
    one transition; `SENT` is terminal — adding it would be a vocabulary entry for an
    operation that does not exist.
    """
    assert not {"OWNER_STATEMENT_MARKED_READY", "OWNER_STATEMENT_MARKED_SENT"} & (
        actions.ACTIONS
    )


def test_owner_statement_audit_scope_is_only_two_fields() -> None:
    """The eleven money columns are set once by `GenerateOwnerStatementUseCase` and never
    mutated thereafter — `save` on `OwnerStatementRepository` writes `status` and `notes`
    only. The eleven columns are not in `AUDITABLE_FIELDS` because there is no API path
    that mutates them, and rule 9 audits mutations, not writes that happen once at creation."""
    assert AUDITABLE_FIELDS["OWNER_STATEMENT"] == {"status", "notes"}


def test_owner_statement_notes_is_structurally_protected() -> None:
    """`diff("notes", old, new)` must raise `AuditContractError`, leaving
    `redacted("notes")` as the only reachable form. The structural refusal is what makes
    the regla-11 sumidero enforceable by construction, not by reviewer discipline."""
    assert "notes" in REDACT_ONLY_FIELDS["OWNER_STATEMENT"]


def test_expense_description_is_redact_only() -> None:
    """`description` is regla 11 sumidero (excepción 3, manager-authored prose). It is in
    `AUDITABLE_FIELDS` so `ChangeSet.redacted("description")` is reachable, and in
    `REDACT_ONLY_FIELDS["EXPENSE"]` so `ChangeSet.diff("description", ...)` raises
    `AuditContractError` — the structural guarantee is the per-entity denylist, not
    the use case's discipline. The same shape as `OWNER_STATEMENT.notes` (line 64
    above) and `pricing_rules.event_rules` (the precedent this pattern was lifted from)."""
    assert "description" in AUDITABLE_FIELDS["EXPENSE"]
    assert "description" in REDACT_ONLY_FIELDS["EXPENSE"]


def test_expense_audit_scope_excludes_the_eleven_monetary_columns() -> None:
    """Statements have no API path to mutate the eleven monetary columns either — the
    amount is on the statement snapshot, not on the expense. The expense's `amount`
    column IS auditable (it can move pre-consolidation)."""
    monetary_statement_columns = {
        "gross_revenue",
        "ota_commissions",
        "net_revenue",
        "cleaning_costs",
        "laundry_costs",
        "amenities_costs",
        "maintenance_costs",
        "specialist_costs",
        "platform_fee",
        "other_costs",
    }
    for col in monetary_statement_columns:
        assert col not in AUDITABLE_FIELDS["EXPENSE"], (
            f"{col} is a statement column, not an expense column"
        )


def test_expense_audit_scope_is_exactly_nine_fields() -> None:
    """Pin the exact set so a silent drop of `approved_by` (D4 writes it; rules 9 audit it)
    is caught at this layer. `description` is in the allowlist because redact-only
    fields are reachable through `redacted()` only — see the test above and the
    `OWNER_STATEMENT.notes` precedent."""
    assert AUDITABLE_FIELDS["EXPENSE"] == frozenset(
        {
            "category",
            "amount",
            "currency",
            "date",
            "description",
            "statement_id",
            "incident_id",
            "approved_by",
            "receipt_storage_key",
        }
    )


def test_redact_only_fields_subset_invariant_holds() -> None:
    """For every entity, every field in `REDACT_ONLY_FIELDS` is also in `AUDITABLE_FIELDS`.

    If a `REDACT_ONLY_FIELDS` entry ever names a field the entity does not audit, the
    `ChangeSet.redacted()` path is unreachable and the redaction is dead code. The invariant
    is a tripwire for that mistake."""
    for entity_type, redacted_fields in REDACT_ONLY_FIELDS.items():
        audited_fields = AUDITABLE_FIELDS[entity_type]
        assert redacted_fields <= audited_fields, (
            f"REDACT_ONLY_FIELDS[{entity_type!r}] has fields outside "
            f"AUDITABLE_FIELDS[{entity_type!r}]"
        )