"""SQLAlchemy adapters for the guest portal's two ports (design D2, D4, D9).

**One of these queries deliberately runs without a tenant filter**, which is unusual enough
in this codebase to state up front: `find_live_by_token_hash` is the step that *resolves* the
tenant, so there is nothing to filter by when it runs. It is the same situation as
`find_by_email_globally` on the login path, and `app/core/db.py`'s second documented limit
covers it — an unmarked session is not filtered, which is what makes an anonymous entry point
possible at all.

What makes it safe here is not the query, it is the schema. `token_hash` carries a **global**
`UNIQUE` index, so "exactly one row" is a guarantee rather than an assumption; and the
composite foreign key on `(tenant_id, reservation_id)` makes it impossible for the row to
name a reservation belonging to somebody else — the hole the security and tenancy panels of
section 1 demonstrated before that constraint existed. Every other method here filters
`tenant_id` explicitly, in the ordinary way.
"""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.access.domain.enums import AccessRecordStatus
from app.access.infrastructure.models import AccessRecordModel

#: The states in which a stay's access record has a code the guest can actually use (D9's
#: "registro vivo"). Derived from `_ALLOWED_FROM` in `app/access/domain/entities.py` rather
#: than guessed: `PENDING` is a record with no code registered yet, and `REVOKED`/`EXPIRED`
#: are codes that will not open the door.
#:
#: Showing a dead code to somebody standing at the door is worse than showing none, because
#: they will try it and conclude the flat is wrong rather than the code.
_USABLE_ACCESS_STATUSES = (
    AccessRecordStatus.MANUAL_ADDED,
    AccessRecordStatus.CREATED_EXTERNAL,
    AccessRecordStatus.DELIVERED,
)
from app.core.db import bind_session_to_tenant
from app.core.tenancy import CrossTenantWriteError
from app.guests.domain.portal_ports import GuestAccessToken, PortalStay, StayInfo
from app.guests.infrastructure.models import GuestAccessTokenModel
from app.properties.infrastructure.models import PropertyModel
from app.reservations.infrastructure.models import ReservationModel


class SqlAlchemyGuestAccessTokenRepository:
    """`GuestAccessTokenRepository` — mint, revoke, resolve. Never commits.

    The transactional boundary is the use case, which is what makes an issue and its audit
    row atomic, and what lets `IssueGuestAccessTokenUseCase` revoke-and-create inside one
    transaction so a loser in the race leaves no state behind (D14, Risks).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_live_by_token_hash(self, token_hash: str) -> GuestAccessToken | None:
        """The unfiltered lookup — see the module docstring for why, and why it is safe.

        Named `find_live_...` for the port's contract, but it returns the row **whatever its
        state**: `revoked_at` comes back untouched and the authoriser decides. Filtering
        revoked rows here would split the "is this token still good?" decision across two
        modules, and D5 needs every failure to be indistinguishable, which is only checkable
        if one place makes all of them.
        """
        row = (
            await self._session.execute(
                # **Columns, not the model**, and on this method that is a security property
                # rather than a micro-optimisation. This read runs on an *unmarked* session
                # (D4 step 1), and limit 4 of `app/core/db.py` warns that a row read while
                # unmarked stays reachable through the identity map afterwards. Selecting the
                # entity left that safety resting on CPython dropping the last reference out
                # of a `WeakInstanceDict` — which the section 3 and 4 panels both declined to
                # accept for the sibling read, and which the section 5 panel then found still
                # in place here while the docstring above claimed otherwise. No instance is
                # created now, so there is nothing to linger.
                select(
                    GuestAccessTokenModel.id,
                    GuestAccessTokenModel.tenant_id,
                    GuestAccessTokenModel.reservation_id,
                    GuestAccessTokenModel.token_hash,
                    GuestAccessTokenModel.revoked_at,
                ).where(GuestAccessTokenModel.token_hash == token_hash)
            )
        ).one_or_none()
        if row is None:
            return None
        return GuestAccessToken(
            id=row.id,
            tenant_id=row.tenant_id,
            reservation_id=row.reservation_id,
            token_hash=row.token_hash,
            revoked_at=row.revoked_at,
        )

    async def add(self, tenant_id: uuid.UUID, token: GuestAccessToken) -> None:
        if token.tenant_id != tenant_id:
            # `app/core/db.py`'s third limit: the session filter does not cover INSERTs, so
            # this check is the only one — exactly as `SqlAlchemyAuditLogRepository.add`
            # documents for the same reason.
            raise CrossTenantWriteError(
                entity="guest_access_token",
                entity_tenant_id=token.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            GuestAccessTokenModel(
                id=token.id,
                tenant_id=token.tenant_id,
                reservation_id=token.reservation_id,
                token_hash=token.token_hash,
                revoked_at=token.revoked_at,
            )
        )

    async def revoke_live_for_reservation(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID, *, now: datetime
    ) -> uuid.UUID | None:
        """R1.4, as a predicate rather than a read-then-write.

        `WHERE revoked_at IS NULL` is the same predicate as the partial unique index, so the
        two cannot disagree about what "live" means, and two concurrent issues cannot both
        believe they revoked the previous token.

        `RETURNING id` rather than a row count: the index guarantees at most one live token
        per stay, so the id is the exact answer where a count would be a weaker one — and it
        is what the caller actually needs, since the revocation's `AuditLog` has to point at
        the credential that was withdrawn. One statement rather than a select-then-update,
        which would reopen the race the predicate exists to close.
        """
        return (
            await self._session.execute(
                update(GuestAccessTokenModel)
                .where(
                    GuestAccessTokenModel.tenant_id == tenant_id,
                    GuestAccessTokenModel.reservation_id == reservation_id,
                    GuestAccessTokenModel.revoked_at.is_(None),
                )
                .values(revoked_at=now)
                .returning(GuestAccessTokenModel.id)
            )
        ).scalar_one_or_none()


class SessionTenantBinder:
    """`TenantBinder` over the request's session (D4 step 4).

    A three-line adapter, and it earns its file for one reason: it is what keeps
    `bind_session_to_tenant` — and therefore SQLAlchemy — out of `application/`, so
    `GuestPortalAuthenticator` can be unit-tested with a fake that records the tenant it was
    handed. It adds no behaviour of its own: the refusals for a null tenant and for a rebind
    live in `app/core/db.py`, where they apply to every caller and not just this one.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def bind(self, tenant_id: uuid.UUID) -> None:
        bind_session_to_tenant(self._session, tenant_id)


class SqlAlchemyPortalStayLocator:
    """`PortalStayLocator` — seven columns of one reservation, filtered by tenant.

    Selects columns rather than the model, so no `ReservationModel` instance is created and
    nothing can linger in the identity map across `bind_session_to_tenant`. That is not
    fastidiousness: this runs on an **unmarked** session (D4 step 2), and limit 4 of
    `app/core/db.py` warns that a row read while unmarked stays reachable afterwards. Both
    the security and the tenancy panels of section 3 checked that the sibling lookup happened
    to be safe only because it dropped its ORM instance; here there is no instance to drop.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> PortalStay | None:
        row = (
            await self._session.execute(
                select(
                    ReservationModel.id,
                    ReservationModel.tenant_id,
                    ReservationModel.property_id,
                    ReservationModel.guest_id,
                    ReservationModel.check_in_date,
                    ReservationModel.check_out_date,
                    ReservationModel.status,
                ).where(
                    ReservationModel.tenant_id == tenant_id,
                    ReservationModel.id == reservation_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return PortalStay(
            reservation_id=row.id,
            tenant_id=row.tenant_id,
            property_id=row.property_id,
            guest_id=row.guest_id,
            check_in_date=row.check_in_date,
            check_out_date=row.check_out_date,
            status=row.status,
        )


class SqlAlchemyGuestPortalStayReader:
    """`GuestPortalStayReader` — the projection behind `GET /guest/info` (D9).

    Reads three tables and returns a type that names sixteen fields, none of which is a
    money column, an internal note, an external id or a document. That is R3.2 and R3.3
    enforced by the shape of `StayInfo` rather than by this query remembering — but the query
    still selects column by column rather than whole models, so the two agree and a widened
    `StayInfo` cannot start returning something by accident.
    """

    def __init__(self, session: AsyncSession, *, support_channel: str | None = None) -> None:
        self._session = session
        # Configuration, not a column, and deliberately: D9 says the support channel is "una
        # constante de configuración, no un dato de otro huésped". Reading it from a row would
        # be one join away from exposing whoever staffs it.
        self._support_channel = support_channel

    async def stay_info(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> StayInfo | None:
        row = (
            await self._session.execute(
                select(
                    ReservationModel.check_in_date,
                    ReservationModel.check_out_date,
                    ReservationModel.check_in_time,
                    ReservationModel.check_out_time,
                    PropertyModel.name,
                    PropertyModel.address_line1,
                    PropertyModel.address_line2,
                    PropertyModel.city,
                    PropertyModel.province,
                    PropertyModel.postal_code,
                    PropertyModel.country,
                    PropertyModel.timezone,
                    PropertyModel.wifi_name,
                    PropertyModel.access_notes,
                    PropertyModel.default_check_in_time,
                    PropertyModel.default_check_out_time,
                )
                .join(PropertyModel, PropertyModel.id == ReservationModel.property_id)
                .where(
                    ReservationModel.tenant_id == tenant_id,
                    ReservationModel.id == reservation_id,
                    # **Both sides of the join carry the filter**, and the second one is not
                    # redundant. `reservations.property_id` is a plain FK to `properties.id`
                    # with no tenant coupling — unlike the composite FK section 1 gave
                    # `guest_access_tokens` — so a reservation of tenant A pointing at tenant
                    # B's property is representable. The security panel of section 3 built
                    # that row and read another operator's address, WiFi name and arrival
                    # instructions back through this very method.
                    #
                    # Filtering the reservation alone would have left the isolation of an
                    # anonymous endpoint resting entirely on the global net of
                    # `app/core/db.py` — on the one path in the system whose defining
                    # property is that the session is **not marked yet** (its limit 2). That
                    # is exactly the inversion its own docstring warns against: the explicit
                    # `tenant_id` is the authoritative mechanism and the net is only the net.
                    PropertyModel.tenant_id == tenant_id,
                )
            )
        ).one_or_none()
        if row is None:
            return None

        return StayInfo(
            check_in_date=row.check_in_date,
            check_out_date=row.check_out_date,
            # The reservation's own times are nullable — a booking imported from a channel
            # often carries none — so the property's defaults stand in (D9). Falling back
            # rather than returning `None` matters for the guest standing at the door.
            check_in_time=row.check_in_time or row.default_check_in_time,
            check_out_time=row.check_out_time or row.default_check_out_time,
            property_name=row.name,
            address_line1=row.address_line1,
            address_line2=row.address_line2,
            city=row.city,
            province=row.province,
            postal_code=row.postal_code,
            country=row.country,
            timezone=row.timezone,
            # The network's name. `wifi_password_encrypted` is not selected above and has no
            # field to land in — rule 4 grants no masked form for it, so there is no shape in
            # which it could appear here.
            wifi_name=row.wifi_name,
            arrival_notes=row.access_notes,
            access_code_masked=await self._access_code(tenant_id, reservation_id),
            support_channel=self._support_channel,
        )

    async def _access_code(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID
    ) -> str | None:
        """The masked code of the stay's live access record, if it has one.

        A second query rather than an outer join, because a stay can have several access
        records over its life (issued, revoked, reissued) and a join would multiply the rows
        of the projection above — turning a one-row read into something whose cardinality
        depends on history.

        Only the three usable states count — see `_USABLE_ACCESS_STATUSES`. `code_masked` is
        the only form stored anywhere (`access-notifications` D9), so this cannot leak a real
        code even if the filter were wrong.

        Newest first, because a stay whose code was reissued has two usable records and the
        guest needs the current one. `limit(1)` rather than trusting there to be one: the
        schema does not forbid two, and a projection that raised on a state the schema allows
        would turn an operator's reissue into a broken portal.

        **`id` breaks the tie**, which is the same fix `SqlAlchemyGuestRepository.find_by_email`
        already carries for the same hazard: `created_at` has microsecond resolution but two
        rows written in one transaction can share it exactly, and `ORDER BY created_at DESC`
        alone then lets the query plan pick — so the code a guest sees would depend on which
        plan Postgres chose. The QA panel of section 3 caught that this precedent had not been
        carried over.
        """
        return (
            await self._session.execute(
                select(AccessRecordModel.code_masked)
                .where(
                    AccessRecordModel.tenant_id == tenant_id,
                    AccessRecordModel.reservation_id == reservation_id,
                    AccessRecordModel.status.in_(_USABLE_ACCESS_STATUSES),
                )
                .order_by(AccessRecordModel.created_at.desc(), AccessRecordModel.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
