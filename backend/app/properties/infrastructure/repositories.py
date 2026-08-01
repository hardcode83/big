"""SQLAlchemy adapter for `PropertyRepository` (design D16).

Every query filters `tenant_id` explicitly. The session-level listener in
`app/core/db.py` also scopes ORM SELECTs, but its own docstring lists what it does not
cover, so the explicit filter stays the authoritative mechanism (design D5).

No method commits: the transactional boundary is the use case (design D4).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.properties.domain.entities import Property
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError
from app.properties.infrastructure.models import PropertyModel


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


def _to_property(model: PropertyModel) -> Property:
    return Property(
        id=model.id,
        tenant_id=model.tenant_id,
        name=model.name,
        internal_code=model.internal_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        pms_external_id=model.pms_external_id,
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
        wifi_password_encrypted=model.wifi_password_encrypted,
        access_notes=model.access_notes,
        cleaning_notes=model.cleaning_notes,
        emergency_notes=model.emergency_notes,
        status=model.status,
    )
