"""Resolving which checklist template a property's cleaning uses (R1.3, R1.4, design D5).

Pure function over candidates the repository already fetched, so the precedence rule is
unit-testable without a database and the same rule serves the automatic provisioning
(`process_checkouts`) and the manual creation endpoint.

**Why a rule and not a column**: `CleaningTask.checklist_template_id` is NOT NULL
(`app/cleaning/infrastructure/models.py:21-23`) but PRD §23 declares no template endpoint
and PRD §27 seeds none, so something has to decide which template a task is born with.
Precedence property → tenant is the cheapest rule that lets a tenant keep one default and
still override it per property.
"""

import uuid
from collections.abc import Sequence

from app.cleaning.domain.entities import CleaningChecklistTemplate
from app.cleaning.domain.exceptions import (
    AmbiguousChecklistTemplateError,
    ChecklistTemplateNotFoundError,
)


def resolve_template(
    candidates: Sequence[CleaningChecklistTemplate], property_id: uuid.UUID
) -> CleaningChecklistTemplate:
    """The active template for `property_id`, falling back to the tenant-wide default.

    Two active templates at the *same* level is an ambiguity of the tenant's data, not a
    tie to break: raising leaves it visible instead of silently freezing the checklist's
    content to whichever row sorted first.

    Inactive templates are ignored here rather than filtered by the caller, so a
    repository that returns everything and one that pre-filters behave the same.
    """
    active = [template for template in candidates if template.active]

    for level in (
        [template for template in active if template.property_id == property_id],
        [template for template in active if template.property_id is None],
    ):
        if len(level) == 1:
            return level[0]
        if len(level) > 1:
            raise AmbiguousChecklistTemplateError(
                f"{len(level)} active checklist templates compete for property {property_id}"
            )

    raise ChecklistTemplateNotFoundError(
        f"No active checklist template resolves for property {property_id}"
    )
