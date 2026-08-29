"""Tenant isolation over the acknowledgement surface (R1.5, rule 1 of `steering/security.md`).

**Two halves, and only the first one can fail.** That is the whole shape of this file, and it
is deliberate rather than tidy: an isolation test that cannot go red proves per-recipient
scoping and reports it as tenant isolation.

Two independent things mask a tenant-scoping failure here, and a test has to dodge both:

1. **The global listener.** The `api` fixture's session is bound to the acting tenant inside
   the authenticated request (`app/auth/api/dependencies.py`), and `app/core/db.py` then
   re-filters ORM SELECT, UPDATE **and** DELETE by tenant on its own. So a route test stays
   green whether or not the repository carries its own `WHERE tenant_id`.
2. **The recipient term.** Every statement conjuncts `tenant_id` AND `recipient_user_id`, and
   the two tenants' users are different rows. A notification of tenant A addressed to tenant
   A's manager is already excluded by the recipient term alone, so the tenant term is never
   the guard under test.

**Half one** therefore runs over the **unmarked** `db_session` (task 3.6: "el test se escribe
sobre sesión **no** marcada, para que pueda fallar de verdad"), against rows that belong to
tenant A but are addressed to **tenant B's user id** — legal in the schema, because
`notification_logs`' foreign keys are deliberately not composite with `tenant_id`, which the
port's own `add` docstring names as its unenforced precondition. With the recipient term
satisfied, `tenant_id` is the only thing left between the caller and the row: delete it from
any of the four statements and exactly one of these tests goes red. Measured that way, one
mutation at a time, rather than asserted.

**Half two** is the route, which R1.5 asks for by name ("cubrir la ruta"). It proves the `404`
and the uncontaminated counters an operator actually observes, and it pins R1.4's third case —
another tenant's row answers the same body as an unknown id — which half one cannot reach. Do
not read a green there as evidence that the tenant scoping is present; that is half one's job.
"""

import uuid

import pytest

from app.auth.infrastructure.models import UserModel
from app.core.unit_of_work import SqlAlchemyUnitOfWork
from app.notifications.application.use_cases import (
    CountUnreadNotificationsUseCase,
    MarkAllNotificationsReadUseCase,
    MarkNotificationReadUseCase,
)
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.domain.exceptions import NotificationNotFoundError
from app.notifications.infrastructure.models import NotificationLogModel
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from tests.notifications.conftest import auth_header, insert_notification


def _use_cases(db_session):
    repository = SqlAlchemyNotificationLogRepository(db_session)
    uow = SqlAlchemyUnitOfWork(db_session)
    return (
        MarkNotificationReadUseCase(notifications=repository, uow=uow),
        CountUnreadNotificationsUseCase(notifications=repository),
        MarkAllNotificationsReadUseCase(notifications=repository, uow=uow),
    )


async def _row_of_a_addressed_to(
    db_session, tenant_a, recipient: UserModel
) -> NotificationLogModel:
    """A notification of tenant A whose recipient is a user of ANOTHER tenant.

    Not a realistic row — nothing writes one — and that is the point: it is the only shape
    in which the `tenant_id` term of the query is the sole guard, because `recipient_user_id`
    already matches the caller. The database accepts it because the foreign key to `users` is
    single-column, exactly as `NotificationLogRepository.add` documents.
    """
    model = NotificationLogModel(
        tenant_id=tenant_a.id,
        recipient_user_id=recipient.id,
        recipient_contact=recipient.email,
        channel=NotificationChannel.IN_APP,
        notification_type="CLEANING_TASK_ASSIGNED",
        status=NotificationStatus.SENT,
    )
    db_session.add(model)
    await db_session.flush()
    return model


# --- the half that can fail: unmarked session, tenant term as the only guard --------------


@pytest.mark.asyncio
async def test_acknowledging_across_tenants_is_refused_when_the_recipient_matches(
    db_session, tenant_a, tenant_b, users_by_role_b
) -> None:
    theirs = users_by_role_b["PROPERTY_MANAGER"]
    row = await _row_of_a_addressed_to(db_session, tenant_a, theirs)
    mark_read, _, _ = _use_cases(db_session)

    with pytest.raises(NotificationNotFoundError):
        await mark_read.execute(
            tenant_id=tenant_b.id, user_id=theirs.id, notification_id=row.id
        )

    await db_session.refresh(row)
    assert row.read_at is None


@pytest.mark.asyncio
async def test_the_counter_across_tenants_ignores_a_row_addressed_to_the_caller(
    db_session, tenant_a, tenant_b, users_by_role_b
) -> None:
    theirs = users_by_role_b["PROPERTY_MANAGER"]
    await _row_of_a_addressed_to(db_session, tenant_a, theirs)
    _, count_unread, _ = _use_cases(db_session)

    assert await count_unread.execute(tenant_id=tenant_b.id, user_id=theirs.id) == 0


@pytest.mark.asyncio
async def test_mark_all_across_tenants_moves_nothing_addressed_to_the_caller(
    db_session, tenant_a, tenant_b, users_by_role_b
) -> None:
    theirs = users_by_role_b["PROPERTY_MANAGER"]
    row = await _row_of_a_addressed_to(db_session, tenant_a, theirs)
    _, _, mark_all_read = _use_cases(db_session)

    assert await mark_all_read.execute(tenant_id=tenant_b.id, user_id=theirs.id) == 0

    await db_session.refresh(row)
    assert row.read_at is None


@pytest.mark.asyncio
async def test_listing_across_tenants_ignores_a_row_addressed_to_the_caller(
    db_session, tenant_a, tenant_b, users_by_role_b
) -> None:
    """The `?unread=` filter narrows; it must not be a way around the scoping (R2.3)."""
    theirs = users_by_role_b["PROPERTY_MANAGER"]
    await _row_of_a_addressed_to(db_session, tenant_a, theirs)
    repository = SqlAlchemyNotificationLogRepository(db_session)

    everything = await repository.list_for_recipient(
        tenant_b.id, theirs.id, page=1, per_page=20
    )
    only_unread = await repository.list_for_recipient(
        tenant_b.id, theirs.id, page=1, per_page=20, unread=True
    )

    assert everything.total == 0
    assert only_unread.total == 0


# --- the half R1.5 asks for by name: the route, end to end -------------------------------
#
# These go through the whole stack, so the global listener is active and they cannot fail on
# the repository's `WHERE tenant_id` alone. They are here for what they DO prove: an operator
# of tenant B, holding a real token, observes a `404` and a counter that stays its own — and
# that the cross-tenant `404` is byte-identical to an unknown id's. Do not read a green here
# as evidence that the tenant scoping is present; that is what the four above are for.


@pytest.mark.asyncio
async def test_a_neighbour_cannot_acknowledge_our_notification(
    api, db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    ours = await insert_notification(
        db_session, tenant_a, recipient=users_by_role_a["PROPERTY_MANAGER"]
    )
    theirs = users_by_role_b["PROPERTY_MANAGER"]

    response = await api.post(
        f"/api/v1/notifications/{ours.id}/read", headers=auth_header(api, theirs)
    )

    assert response.status_code == 404
    await db_session.refresh(ours)
    assert ours.read_at is None


@pytest.mark.asyncio
async def test_the_neighbours_404_is_the_same_body_as_an_unknown_id(
    api, db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    """R1.4's third case, at the route: another tenant's row is not distinguishable."""
    ours = await insert_notification(
        db_session, tenant_a, recipient=users_by_role_a["PROPERTY_MANAGER"]
    )
    headers = auth_header(api, users_by_role_b["PROPERTY_MANAGER"])

    neighbours = await api.post(f"/api/v1/notifications/{ours.id}/read", headers=headers)
    unknown = await api.post(
        f"/api/v1/notifications/{uuid.uuid4()}/read", headers=headers
    )

    assert neighbours.status_code == unknown.status_code == 404
    assert neighbours.json() == unknown.json()


@pytest.mark.asyncio
async def test_a_neighbours_counter_is_not_contaminated_by_our_rows(
    api, db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    for _ in range(3):
        await insert_notification(
            db_session, tenant_a, recipient=users_by_role_a["PROPERTY_MANAGER"]
        )
    theirs = users_by_role_b["PROPERTY_MANAGER"]
    await insert_notification(db_session, tenant_b, recipient=theirs)

    response = await api.get(
        "/api/v1/notifications/unread-count", headers=auth_header(api, theirs)
    )

    assert response.json() == {"unread": 1}


@pytest.mark.asyncio
async def test_a_neighbours_mark_all_never_reaches_our_rows(
    api, db_session, tenant_a, tenant_b, users_by_role_a, users_by_role_b
) -> None:
    ours = await insert_notification(
        db_session, tenant_a, recipient=users_by_role_a["PROPERTY_MANAGER"]
    )
    theirs = users_by_role_b["PROPERTY_MANAGER"]
    await insert_notification(db_session, tenant_b, recipient=theirs)

    response = await api.post(
        "/api/v1/notifications/read-all", headers=auth_header(api, theirs)
    )

    assert response.json() == {"updated": 1}
    await db_session.refresh(ours)
    assert ours.read_at is None
