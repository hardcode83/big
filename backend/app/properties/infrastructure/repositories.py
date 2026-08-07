"""SQLAlchemy adapter for `PropertyRepository` (`reservations` design D16).

Every query filters `tenant_id` explicitly. The session-level listener in
`app/core/db.py` also scopes ORM SELECTs, but its own docstring lists what it does not
cover, so the explicit filter stays the authoritative mechanism (design D5).

No method commits: the transactional boundary is the use case (design D4).
"""

import uuid
from collections.abc import Collection

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tenancy import CrossTenantWriteError
from app.integrations.domain.enums import PMSProvider
from app.properties.domain.entities import Property, PropertyStateTransition
from app.properties.domain.enums import PropertyOperationalState
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError
from app.properties.infrastructure.models import PropertyModel, PropertyStateTransitionModel


class SqlAlchemyPropertyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, tenant_id: uuid.UUID, property_id: uuid.UUID) -> Property | None:
        result = await self._session.execute(
            select(PropertyModel).where(
                PropertyModel.tenant_id == tenant_id, PropertyModel.id == property_id
            )
        )
        model = result.scalar_one_or_none()
        return _to_property(model) if model is not None else None

    async def find_by_internal_code(
        self, tenant_id: uuid.UUID, internal_code: str
    ) -> Property | None:
        """`uq_properties_tenant_id_internal_code` guarantees at most one row."""
        result = await self._session.execute(
            select(PropertyModel).where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.internal_code == internal_code.strip(),
            )
        )
        model = result.scalar_one_or_none()
        return _to_property(model) if model is not None else None

    async def find_by_pms_external_id(
        self, tenant_id: uuid.UUID, pms_external_id: str
    ) -> Property | None:
        """Fails closed when the external id is ambiguous, with a DOMAIN error.

        `ix_properties_tenant_id_pms_external_id` is an index, NOT a unique constraint,
        so two properties of the same tenant *can* carry the same external id. Picking
        one would silently attach a booking — and a guest — to the wrong flat, so this
        refuses instead.

        It refuses by raising `AmbiguousPropertyExternalIdError`, never by letting
        SQLAlchemy's `MultipleResultsFound` escape: the port promises `Property | None`,
        and its caller (the PMS sync, R3.4) has to report the offending row and continue
        with the batch — which it could only do by catching an infrastructure exception,
        forbidden inside `application/` by the dependency rule.
        """
        rows = await self._session.execute(
            select(PropertyModel)
            .where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.pms_external_id == pms_external_id.strip(),
            )
            .limit(2)
        )
        models = list(rows.scalars())
        if len(models) > 1:
            raise AmbiguousPropertyExternalIdError(
                f"Two or more properties share pms_external_id {pms_external_id!r}",
                pms_external_id=pms_external_id,
            )
        return _to_property(models[0]) if models else None

    async def list_by_state(
        self, tenant_id: uuid.UUID, states: Collection[PropertyOperationalState]
    ) -> list[Property]:
        if not states:
            return []
        result = await self._session.execute(
            select(PropertyModel)
            .where(
                PropertyModel.tenant_id == tenant_id,
                PropertyModel.current_operational_state.in_(list(states)),
            )
            # Stable order so a job processes the same properties in the same sequence on
            # every tick, which is what makes a failure reproducible from its log.
            .order_by(PropertyModel.id)
        )
        return [_to_property(model) for model in result.scalars()]

    async def list_all(self, tenant_id: uuid.UUID) -> list[Property]:
        result = await self._session.execute(
            select(PropertyModel)
            .where(PropertyModel.tenant_id == tenant_id)
            # Deterministic order so a grouped sync processes providers the same way twice, which
            # makes a failing run reproducible instead of order-dependent.
            .order_by(PropertyModel.internal_code)
        )
        return [_to_property(model) for model in result.scalars().all()]

    async def save(self, tenant_id: uuid.UUID, property: Property) -> None:
        if property.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property",
                entity_tenant_id=property.tenant_id,
                acting_tenant_id=tenant_id,
            )
        await self._session.execute(
            update(PropertyModel)
            .where(PropertyModel.tenant_id == tenant_id, PropertyModel.id == property.id)
            .values(current_operational_state=property.current_operational_state)
        )


    async def set_pms_provider(
        self, tenant_id: uuid.UUID, property_id: uuid.UUID, provider: PMSProvider | None
    ) -> None:
        """One column, like `save`. See the port for why this is not a widening of it."""
        result = await self._session.execute(
            update(PropertyModel)
            .where(PropertyModel.tenant_id == tenant_id, PropertyModel.id == property_id)
            .values(pms_provider=provider)
        )
        if result.rowcount == 0:
            # Nothing matched, which within a tenant-filtered UPDATE means either "no such
            # property" or "it belongs to someone else" — indistinguishable here, and that is
            # the point: reporting which would leak a neighbour's property id (design D6 of
            # `reservations` answers the same question with 404 for the same reason).
            raise CrossTenantWriteError(
                entity="property",
                entity_tenant_id="unknown",
                acting_tenant_id=tenant_id,
            )


class SqlAlchemyPropertyStateTransitionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, tenant_id: uuid.UUID, transition: PropertyStateTransition) -> None:
        if transition.tenant_id != tenant_id:
            raise CrossTenantWriteError(
                entity="property state transition",
                entity_tenant_id=transition.tenant_id,
                acting_tenant_id=tenant_id,
            )
        self._session.add(
            PropertyStateTransitionModel(
                id=transition.id,
                tenant_id=transition.tenant_id,
                property_id=transition.property_id,
                from_state=transition.from_state,
                to_state=transition.to_state,
                triggered_by=transition.triggered_by,
                triggered_by_user_id=transition.triggered_by_user_id,
                reason=transition.reason,
                # `metadata` is taken by SQLAlchemy's declarative API, so the column named
                # `metadata` in Postgres is reached through `metadata_` — the same rename
                # `SqlAlchemyTimelineEventRepository` documents.
                metadata_=transition.metadata or None,
                created_at=transition.created_at,
            )
        )
        await self._session.flush()


def _to_property(model: PropertyModel) -> Property:
    return Property(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        internal_code=model.internal_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        pms_external_id=model.pms_external_id,
        pms_provider=model.pms_provider,
        address_line1=model.address_line1,
        address_line2=model.address_line2,
        city=model.city,
        province=model.province,
        postal_code=model.postal_code,
        country=model.country,
        timezone=model.timezone,
        max_guests=model.max_guests,
        bedrooms=model.bedrooms,
        bathrooms=model.bathrooms,
        current_operational_state=model.current_operational_state,
        default_check_in_time=model.default_check_in_time,
        default_check_out_time=model.default_check_out_time,
        wifi_name=model.wifi_name,
        # `wifi_password_encrypted` is intentionally not mapped onto the entity (design D2):
        # nothing reads it, and leaving it off the entity keeps it off every serialisation path.
        access_notes=model.access_notes,
        cleaning_notes=model.cleaning_notes,
        emergency_notes=model.emergency_notes,
        status=model.status,
    )
