"""Bilingual error vocabulary for owner statements (R7.7).

The shared i18n module owns the rendering mechanism; this domain owns the messages that
belong to statements, following the timeline and dashboard catalogues.
"""

from app.core.i18n import Catalog, Locale

STATEMENTS_ERROR_MESSAGES = Catalog(
    {
        "owner_statement_not_found": {
            Locale.ES: "La liquidación no existe",
            Locale.EN: "The owner statement does not exist",
        },
        "expense_not_found": {
            Locale.ES: "El gasto no existe",
            Locale.EN: "The expense does not exist",
        },
        "expense_already_consolidated": {
            Locale.ES: "El gasto ya está consolidado y no se puede modificar",
            Locale.EN: "The expense is already consolidated and cannot be changed",
        },
        "named_expense_in_closed_period": {
            Locale.ES: "La fecha del gasto pertenece a un período cerrado",
            Locale.EN: "The expense date belongs to a closed period",
        },
        "owner_statement_invalid_transition": {
            Locale.ES: "La transición de estado de la liquidación no es válida",
            Locale.EN: "The owner statement status transition is invalid",
        },
    }
)
