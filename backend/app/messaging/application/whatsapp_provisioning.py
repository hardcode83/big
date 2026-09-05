"""Provisioning a tenant's WhatsApp number (section 6, `whatsapp-cloud-adapter` R6.1-R6.3, D3/D8).

**Rewritten mid-run.** Meta admits one App/WABA for the whole platform — built in section 1
with the global `WHATSAPP_ACCESS_TOKEN`/`WHATSAPP_APP_SECRET` — and each tenant brings its own
`phone_number_id` under that App. So there is no secret to mint per tenant, only a
number-to-tenant association to give a tenant control over. `AssociateWhatsAppPhoneNumberUseCase`
is `CreateWebhookEndpointUseCase`'s structural sibling in `app/integrations/application
/use_cases.py`, with one operation instead of two: there is no secret whose lifetime a separate
"rotate" verb needs to protect, so a single call expresses both "this tenant has no number yet"
and "this tenant's number changed" (R6.3).
"""

import uuid
from datetime import datetime

from app.audit.domain.actions import (
    ENTITY_WHATSAPP_PHONE_NUMBER,
    WHATSAPP_PHONE_NUMBER_ASSOCIATED,
    WHATSAPP_PHONE_NUMBER_RELEASED,
)
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.core.unit_of_work import UnitOfWork
from app.messaging.domain.entities import WhatsAppPhoneNumberAssociation
from app.messaging.domain.exceptions import (
    MessagingValidationError,
    WhatsAppPhoneNumberNotFoundError,
)
from app.messaging.domain.repositories import WhatsAppPhoneNumberRepository
from app.properties.domain.repositories import PropertyRepository


class _WhatsAppPhoneNumberAuditWriter:
    """Builds the audit row for both operations, so neither builds one by hand.

    Same shape as `_WebhookEndpointAuditWriter`
    (`app/integrations/application/use_cases.py`): `AuditLogFactory` is already the shared
    piece, and this stays private to this module rather than hoisted.
    """

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        association_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=ENTITY_WHATSAPP_PHONE_NUMBER,
                entity_id=association_id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=changes,
                now=now,
            ),
        )


def _association_changes(
    old: WhatsAppPhoneNumberAssociation | None, new: WhatsAppPhoneNumberAssociation
) -> ChangeSet:
    """What an association's audit row records: every column, as a plain diff.

    Unlike `_material_changes` in `integrations/application/use_cases.py`, nothing here is
    `.redacted()` — there is no secret in this table at all (D3/D8's whole point), so every
    field of `AUDITABLE_FIELDS["WHATSAPP_PHONE_NUMBER"]` is diffed with its real value.
    `old` is `None` on a fresh association, so every field's `old` reads as `None` too — the
    same "the row did not exist" reading `_material_changes`'s `header_name is None` branch
    uses for a creation.
    """
    return (
        ChangeSet(ENTITY_WHATSAPP_PHONE_NUMBER)
        .diff(
            "phone_number_id",
            old.phone_number_id if old is not None else None,
            new.phone_number_id,
        )
        .diff(
            "display_phone_number",
            old.display_phone_number if old is not None else None,
            new.display_phone_number,
        )
        .diff(
            "default_property_id",
            old.default_property_id if old is not None else None,
            new.default_property_id,
        )
    )


def _release_changes(old: WhatsAppPhoneNumberAssociation) -> ChangeSet:
    """What a release's audit row records: every column, old value to `None` (R6.3).

    The mirror of `_association_changes`'s creation branch: there the row went from
    non-existent to these values, here it goes from these values to non-existent.
    """
    return (
        ChangeSet(ENTITY_WHATSAPP_PHONE_NUMBER)
        .diff("phone_number_id", old.phone_number_id, None)
        .diff("display_phone_number", old.display_phone_number, None)
        .diff("default_property_id", old.default_property_id, None)
    )


class AssociateWhatsAppPhoneNumberUseCase:
    """Give a tenant control of a `phone_number_id` under the platform's Meta App (R6.1, R6.2).

    Create-or-replace, not create-then-separately-rotate: task 6.3 and R6.3 ask for a single
    operation, because there is no secret whose lifetime a rotation would need to protect. A
    second call for the same tenant with a different `phone_number_id` simply replaces the
    association — the previous number stops resolving to this tenant from that moment, and
    whichever *other* tenant now wants it may associate it in turn.

    **`phone_number_id` uniqueness is enforced by the database, not by a prior read** (design
    D8, `steering/backend-architecture.md`): it is genuinely global across tenants, so a
    read-then-write here would leave a race two concurrent tenants could both win. The
    repository's `upsert` lets the unique index raise and this use case lets that exception —
    `WhatsAppPhoneNumberAlreadyAssociatedError` — propagate unchanged; there is nothing to
    translate at this layer.
    """

    def __init__(
        self,
        *,
        phone_numbers: WhatsAppPhoneNumberRepository,
        properties: PropertyRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._phone_numbers = phone_numbers
        self._properties = properties
        self._audit = _WhatsAppPhoneNumberAuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        phone_number_id: str,
        display_phone_number: str | None,
        default_property_id: uuid.UUID,
        now: datetime,
    ) -> WhatsAppPhoneNumberAssociation:
        """`default_property_id` is validated as belonging to `tenant_id` before anything is
        written — the same pattern `CreateConversationUseCase` already uses for a
        client-supplied `property_id` (`app/messaging/application/use_cases.py`): `properties
        .get` returns `None` for both "does not exist" and "belongs to another tenant", and
        that is deliberately the one refusal this raises, so a cross-tenant probe learns
        nothing more than a typo would.
        """
        if await self._properties.get(tenant_id, default_property_id) is None:
            raise MessagingValidationError("Property does not exist")

        existing = await self._phone_numbers.find_for_tenant(tenant_id)
        association = WhatsAppPhoneNumberAssociation(
            id=existing.id if existing is not None else uuid.uuid4(),
            tenant_id=tenant_id,
            phone_number_id=phone_number_id,
            display_phone_number=display_phone_number,
            default_property_id=default_property_id,
        )

        # Raises `WhatsAppPhoneNumberAlreadyAssociatedError` if `phone_number_id` already
        # belongs to a different tenant — see the repository's own docstring for why this is
        # a database-level check and not a read this use case performs itself.
        await self._phone_numbers.upsert(tenant_id, association)
        await self._audit.record(
            tenant_id=tenant_id,
            action=WHATSAPP_PHONE_NUMBER_ASSOCIATED,
            association_id=association.id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=_association_changes(existing, association),
            now=now,
        )
        await self._uow.commit()
        return association


class ReleaseWhatsAppPhoneNumberUseCase:
    """Retire a tenant's association (R6.3) — the equivalent of "rotate" in this model.

    No symmetric `default_property_id`: releasing a number does not touch the conversations
    already opened under it (R6.3's own words), so there is nothing here for that id to apply
    to. A tenant that later associates a new number brings a fresh `default_property_id` of
    its own, through `AssociateWhatsAppPhoneNumberUseCase`.
    """

    def __init__(
        self,
        *,
        phone_numbers: WhatsAppPhoneNumberRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._phone_numbers = phone_numbers
        self._audit = _WhatsAppPhoneNumberAuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        now: datetime,
    ) -> None:
        existing = await self._phone_numbers.find_for_tenant(tenant_id)
        if existing is None:
            raise WhatsAppPhoneNumberNotFoundError(
                "this tenant has no WhatsApp number associated"
            )

        await self._phone_numbers.delete_for_tenant(tenant_id)
        await self._audit.record(
            tenant_id=tenant_id,
            action=WHATSAPP_PHONE_NUMBER_RELEASED,
            association_id=existing.id,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=_release_changes(existing),
            now=now,
        )
        await self._uow.commit()
