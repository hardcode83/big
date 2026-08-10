"""Wiring for the timeline endpoint: one builder per use case.

Same shape as `app/properties/api/dependencies.py` — no container, no registry, one
function naming exactly the adapters its use case needs.

The repositories take the session from `get_db_session`, which is the same session
`get_authenticated_request` has already marked with the tenant, so the listener of
`app/core/db.py` scopes ORM reads too — as a net under the explicit `tenant_id` argument,
never instead of it.
"""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.timeline.application.use_cases import GetPropertyTimelineUseCase
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventReader

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_property_timeline_use_case(session: SessionDep) -> GetPropertyTimelineUseCase:
    return GetPropertyTimelineUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        events=SqlAlchemyTimelineEventReader(session),
    )
