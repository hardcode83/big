"""The timeline endpoint (PRD §10, §23:1952, `dashboard-api` R4, R5).

The `api/` layer `timeline` did not have. Until now the module was a factory and a write
port, and its events were recorded by *other* domains' use cases — `domain/repositories.py`
said so in as many words: "reading events back belongs to the change that introduces the
timeline endpoints".

**One route, and it reads.** `GET /api/v1/timeline` — the global variant of §23:1951 — is
out of scope (the roadmap entry bounds this to the per-property one, which is what the
detail page consumes). There is no writer here and there will not be one: events are
appended by the use case that caused them, which is what keeps the timeline a record.

**Query parameter naming.** The frontend contract spells its filters `eventType`,
`actorType`, `from` and `to` (`dto.ts:111-117`). On the wire they are `event_type`,
`actor_type`, `from` and `to`: R4.2 names *which* filters must exist, and this API's
convention for the spelling is snake_case — `per_page`, `current_operational_state`. The
two range bounds keep the contract's own names because they are single words already;
`from` is a Python keyword, so it reaches the handler through an alias.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.auth.api.dependencies import AuthenticatedRequest, require
from app.auth.domain.policy import Permission
from app.core.openapi import AUTHENTICATED_RESPONSES
from app.timeline.api.dependencies import get_property_timeline_use_case
from app.timeline.api.schemas import MAX_PAGE, MAX_PER_PAGE, TimelinePageResponse
from app.timeline.application.use_cases import GetPropertyTimelineUseCase
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity
from app.timeline.domain.repositories import TimelineFilters

router = APIRouter(prefix="/timeline", tags=["timeline"], responses=AUTHENTICATED_RESPONSES)

# `READ_PROPERTIES` and not a permission of this module's own: `policy.py` says the
# catalogue "holds only the permissions this change actually enforces... there is no
# speculative catalogue of capabilities nobody checks yet", and a property's history is
# gated by the same capability as the property. It also lands the right way round today —
# `TENANT_OWNER` and `PROPERTY_MANAGER` hold it, `CLEANER` and `TECHNICIAN` do not, and a
# cleaner has no business reading a flat's whole operational history.
#
# The block-level redaction of design D10 is not applied per entry here, but the rule it
# comes from — "agregar no puede conceder" — still binds, and the security panel of
# section 2 was right that the first version of this comment waved it away too fast.
#
# What is true: an entry carries no `metadata` (R4.3), so no cross-domain *payload* is
# handed over. What is also true: its `event_type` and title announce that something
# happened in another domain ("Access instructions delivered", "Legal registration
# submitted"), and reading that same fact through `access` or `guests` needs a permission
# of its own. A role with `READ_PROPERTIES` and not `READ_ACCESS_RECORDS` would learn here
# what it was denied there.
#
# No such role exists — and `tests/auth/test_policy.py::
# test_reading_properties_implies_every_permission_a_timeline_entry_can_reveal` is what
# keeps that a fact rather than a coincidence. Filtering entries per permission was the
# alternative; it was not taken because it would need a 45-value event-type-to-permission
# table that no requirement asks for, and because a timeline with silent holes in it is a
# worse audit surface than one that is honestly gated. If that test ever fails, the
# decision is reopened there, before the role ships.
ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_PROPERTIES))]


@router.get(
    "/{property_id}",
    response_model=TimelinePageResponse,
    summary="A property's timeline",
    description=(
        "Paginated with `page`/`per_page` (PRD §23) and ordered by occurrence descending, "
        "with the entry id as tiebreaker so paging neither repeats an entry nor skips one "
        "when several share an instant. Filters combine with AND; `from`/`to` are "
        "inclusive on both ends. `title` arrives already composed in the authenticated "
        "user's language (PRD §10); `description` does not — it carries operator-written "
        "text, such as the reason a property was blocked, and is returned verbatim in "
        "whatever language it was typed. The `event_type`, `actor_type` and "
        "`severity` literals are never translated. The `metadata` column is not part of "
        "this contract and is never serialised. A property of another tenant answers "
        "`404`, with a body indistinguishable from one that does not exist."
    ),
)
async def get_property_timeline(
    property_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[
        GetPropertyTimelineUseCase, Depends(get_property_timeline_use_case)
    ],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    event_type: TimelineEventType | None = None,
    severity: TimelineSeverity | None = None,
    actor_type: TimelineActorType | None = None,
    occurred_from: Annotated[datetime | None, Query(alias="from")] = None,
    occurred_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> TimelinePageResponse:
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        property_id=property_id,
        filters=TimelineFilters(
            event_type=event_type,
            severity=severity,
            actor_type=actor_type,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        ),
        page=page,
        per_page=per_page,
        locale=authenticated.context.preferred_language,
    )
    return TimelinePageResponse.build(
        result.entries, total=result.total, page=page, per_page=per_page
    )
