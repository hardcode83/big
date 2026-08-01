"""Reservation endpoints (PRD §23, R1, R5).

Thin by contract: map Pydantic → use case → Pydantic. Every route declares its permission
with `require(...)`, which is what `tests/test_route_authorization.py` walks — an endpoint
added here without one fails the suite (R5.3).
"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.auth.api.dependencies import AuthenticatedRequest, now_utc, require
from app.auth.domain.policy import Permission
from app.reservations.api.dependencies import (
    get_cancel_reservation_use_case,
    get_create_reservation_use_case,
    get_list_reservations_use_case,
    get_reservation_use_case,
    get_update_reservation_use_case,
)
from app.reservations.api.schemas import (
    MAX_PAGE,
    MAX_PER_PAGE,
    CreateReservationRequest,
    ReservationDetailResponse,
    ReservationPageResponse,
    ReservationResponse,
    UpdateReservationRequest,
)
from app.reservations.application.use_cases import (
    CancelReservationUseCase,
    CreateReservationCommand,
    CreateReservationUseCase,
    GetReservationUseCase,
    ListReservationsUseCase,
    UpdateReservationUseCase,
)
from app.reservations.domain.enums import ReservationStatus
from app.reservations.domain.repositories import ReservationFilters

router = APIRouter(prefix="/reservations", tags=["reservations"])

ReadDep = Annotated[AuthenticatedRequest, Depends(require(Permission.READ_RESERVATIONS))]
ManageDep = Annotated[AuthenticatedRequest, Depends(require(Permission.MANAGE_RESERVATIONS))]


@router.get(
    "",
    response_model=ReservationPageResponse,
    summary="List the tenant's reservations",
    description=(
        "Paginated with `page`/`per_page` (PRD §23). Filters combine with AND; the date "
        "range matches stays that OVERLAP it, so a guest already in the property when the "
        "range opens is included."
    ),
)
async def list_reservations(
    authenticated: ReadDep,
    use_case: Annotated[ListReservationsUseCase, Depends(get_list_reservations_use_case)],
    page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    per_page: Annotated[int, Query(ge=1, le=MAX_PER_PAGE)] = 20,
    property_id: uuid.UUID | None = None,
    status_filter: Annotated[ReservationStatus | None, Query(alias="status")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> ReservationPageResponse:
    # No validation here: `ReservationFilters` rejects an inverted range itself, and
    # `CreateReservationCommand` the non-manual channel — the router only translates.
    result = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        filters=ReservationFilters(
            property_id=property_id,
            status=status_filter,
            date_from=date_from,
            date_to=date_to,
        ),
        page=page,
        per_page=per_page,
    )
    return ReservationPageResponse.build(
        result.items, total=result.total, page=page, per_page=per_page
    )


@router.post(
    "",
    response_model=ReservationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reservation by hand",
    description=(
        "For bookings that do not come from the PMS. `nights` and `total_guests` are "
        "derived from the dates and the party, never accepted from the caller. Answers "
        "`404` when the property is not the caller's tenant's."
    ),
)
async def create_reservation(
    body: CreateReservationRequest,
    authenticated: ManageDep,
    use_case: Annotated[CreateReservationUseCase, Depends(get_create_reservation_use_case)],
) -> ReservationResponse:
    reservation = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        command=CreateReservationCommand(
            property_id=body.property_id,
            channel=body.channel,
            check_in_date=body.check_in_date,
            check_out_date=body.check_out_date,
            adults=body.adults,
            children=body.children,
            guest_id=body.guest_id,
            check_in_time=body.check_in_time,
            check_out_time=body.check_out_time,
            gross_amount=body.gross_amount,
            ota_commission=body.ota_commission,
            net_amount=body.net_amount,
            currency=body.currency,
            payment_status=body.payment_status,
            cleaning_required=body.cleaning_required,
            special_requests=body.special_requests,
            internal_notes=body.internal_notes,
            external_channel_id=body.external_channel_id,
        ),
        now=now_utc(),
    )
    return ReservationResponse.from_domain(reservation)


@router.get(
    "/{reservation_id}",
    response_model=ReservationDetailResponse,
    summary="One reservation, with its linked guest",
    description=(
        "The guest is returned without any identity-document data. A reservation of "
        "another tenant answers `404`, indistinguishable from one that does not exist."
    ),
)
async def get_reservation(
    reservation_id: uuid.UUID,
    authenticated: ReadDep,
    use_case: Annotated[GetReservationUseCase, Depends(get_reservation_use_case)],
) -> ReservationDetailResponse:
    detail = await use_case.execute(
        tenant_id=authenticated.context.tenant_id, reservation_id=reservation_id
    )
    return ReservationDetailResponse.from_detail(detail)


@router.patch(
    "/{reservation_id}",
    response_model=ReservationResponse,
    summary="Update a reservation partially",
    description=(
        "Only the fields present in the body are applied. Dates and occupancy are "
        "revalidated on the RESULT, and `nights`/`total_guests` are recomputed. A body "
        "that changes nothing writes nothing and records no timeline event."
    ),
)
async def update_reservation(
    reservation_id: uuid.UUID,
    body: UpdateReservationRequest,
    authenticated: ManageDep,
    use_case: Annotated[UpdateReservationUseCase, Depends(get_update_reservation_use_case)],
) -> ReservationResponse:
    reservation = await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        reservation_id=reservation_id,
        changes=body.changes(),
        now=now_utc(),
    )
    return ReservationResponse.from_domain(reservation)


@router.delete(
    "/{reservation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a reservation",
    description=(
        "Cancellation, not physical deletion: the row stays and its status becomes "
        "`CANCELLED`. Idempotent — cancelling an already cancelled reservation answers "
        "`204` and adds no second timeline event."
    ),
)
async def cancel_reservation(
    reservation_id: uuid.UUID,
    authenticated: ManageDep,
    use_case: Annotated[CancelReservationUseCase, Depends(get_cancel_reservation_use_case)],
) -> Response:
    await use_case.execute(
        tenant_id=authenticated.context.tenant_id,
        actor_user_id=authenticated.context.user_id,
        reservation_id=reservation_id,
        now=now_utc(),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
