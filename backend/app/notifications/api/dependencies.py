"""Wiring for the notifications endpoints. Same shape as `app/cleaning/api/dependencies.py`."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db_session
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.application.use_cases import (
    CountUnreadNotificationsUseCase,
    ListOwnNotificationsUseCase,
    MarkAllNotificationsReadUseCase,
    MarkNotificationReadUseCase,
)
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def get_list_own_notifications_use_case(session: SessionDep) -> ListOwnNotificationsUseCase:
    return ListOwnNotificationsUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session)
    )


def get_mark_notification_read_use_case(
    session: SessionDep,
) -> MarkNotificationReadUseCase:
    return MarkNotificationReadUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )


def get_count_unread_notifications_use_case(
    session: SessionDep,
) -> CountUnreadNotificationsUseCase:
    return CountUnreadNotificationsUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session)
    )


def get_mark_all_notifications_read_use_case(
    session: SessionDep,
) -> MarkAllNotificationsReadUseCase:
    return MarkAllNotificationsReadUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session),
        uow=SqlAlchemyUnitOfWork(session),
    )
