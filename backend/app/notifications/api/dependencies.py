"""Wiring for the notifications endpoints. Same shape as `app/cleaning/api/dependencies.py`."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.notifications.application.use_cases import ListOwnNotificationsUseCase
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_list_own_notifications_use_case(session: SessionDep) -> ListOwnNotificationsUseCase:
    return ListOwnNotificationsUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session)
    )
