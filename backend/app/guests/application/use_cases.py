"""Guest documents and the legal registration (R6, R7; PRD §17; design D10, D11).

Three operations, and all three are governed by the same paragraph of
`sdd/steering/security.md` — rule 9's "acceso/modificación de documentos de Guest" and
rule 4's "número de documento jamás en listados".

**Where the cleartext document number exists, exhaustively:**

1. as a parameter of `SetGuestDocumentUseCase.execute`, until `encrypt()` two lines later;
2. as the return value of `ReadGuestDocumentUseCase.execute`, after its audit row is written;
3. inside `LegalSubmission`, built at the last moment in `SubmitLegalRegistrationUseCase` and
   handed straight to the adapter.

Nowhere else. It is not in any `ChangeSet` (rule 11 denylists the column name, so `diff()`
on it *raises*), not in any timeline event, not in any log line, and not in any response
model except the one endpoint that exists to return it.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime

from app.audit.domain import actions as audit_actions
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.auth.domain.enums import UserRole, UserStatus
from app.auth.domain.ports import UserRepository
from app.auth.domain.repositories import UserFilters
from app.core.crypto import decrypt, encrypt
from app.core.encrypted_secret import EncryptedSecret
from app.core.unit_of_work import UnitOfWork
from app.guests.domain.entities import Guest
from app.guests.domain.enums import GuestDocumentStatus, GuestDocumentType, LegalRegistrationStatus
from app.guests.domain.exceptions import (
    GuestDocumentMissingError,
    GuestNotFoundError,
    LegalRegistrationNotReadyError,
    ReservationNotFoundError,
)
from app.guests.domain.legal_registration import (
    LegalRegistrationSubject,
    missing_fields,
    status_for,
)
from app.guests.domain.ports import (
    LegalRegistrationStayStore,
    LegalSubmission,
    SESHospedajesAdapter,
)
from app.guests.domain.repositories import GuestRepository
from app.notifications.domain.entities import NotificationLog
from app.notifications.domain.enums import NotificationChannel, NotificationStatus
from app.notifications.domain.repositories import NotificationLogRepository
from app.timeline.domain.enums import TimelineActorType, TimelineEventType
from app.timeline.domain.repositories import TimelineEventRepository
from app.timeline.domain.services import TimelineEventFactory
from app.timeline.domain.value_objects import TimelineEventData

logger = logging.getLogger(__name__)

#: `related_type` for a notification pointing at `reservations`.
RELATED_TYPE_RESERVATION = "reservation"

#: Outside PRD §14's sixteen, on purpose — see `_failure_notification`.
LEGAL_REGISTRATION_FAILED_NOTIFICATION = "LEGAL_REGISTRATION_FAILED"

#: A tenant's roster is small (PRD §1), and the roles that receive this are the two
#: administrative ones. Same bound and same reasoning as `EscalateBreachedSlasUseCase`.
_MAX_RECIPIENTS = 100


@dataclass(frozen=True)
class GuestActor:
    """Who is acting, and from where (rule 9)."""

    user_id: uuid.UUID
    ip: str | None = None


@dataclass(frozen=True)
class DocumentInput:
    """What `PATCH /guests/{id}/document` accepts (R7.1).

    All six together, not a partial patch: PRD §17 requires the set, and letting a caller
    send `document_number` without `document_expiry_date` produces a guest who looks
    documented and cannot be reported.
    """

    nationality: str
    date_of_birth: date
    document_type: GuestDocumentType
    document_number: str
    document_expiry_date: date


@dataclass(frozen=True)
class GuestDocument:
    """The decrypted document, returned by the one endpoint allowed to (R7.2)."""

    guest_id: uuid.UUID
    full_name: str
    nationality: str | None
    date_of_birth: date | None
    document_type: GuestDocumentType | None
    document_number: str
    document_expiry_date: date | None
    document_status: GuestDocumentStatus


class _AuditWriter:
    """Builds and appends an audit entry, so no use case constructs one by hand."""

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        actor: GuestActor,
        changes: ChangeSet,
        now: datetime,
    ) -> None:
        await self._audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                actor_user_id=actor.user_id,
                actor_ip=actor.ip,
                changes=changes,
                now=now,
            ),
        )


class SetGuestDocumentUseCase:
    """R7.1 — store an identity document, encrypted, and re-evaluate readiness.

    The plaintext lives for two lines. What is persisted is `encrypt()`'s output, and what is
    audited is **which fields changed**, never their values: `document_number_encrypted` is on
    rule 11's denylist, so `ChangeSet.diff()` on it raises and `redacted()` is the only form
    that exists. That is not politeness — it is the mechanism.
    """

    def __init__(
        self,
        *,
        guests: GuestRepository,
        stays: LegalRegistrationStayStore,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._guests = guests
        self._stays = stays
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        guest_id: uuid.UUID,
        document: DocumentInput,
        actor: GuestActor,
        now: datetime,
        reservation_id: uuid.UUID | None = None,
    ) -> Guest:
        guest = await self._guests.get_full(tenant_id, guest_id)
        if guest is None:
            raise GuestNotFoundError(guest_id)

        had_document = guest.document_number_encrypted is not None
        guest.nationality = document.nationality
        guest.date_of_birth = document.date_of_birth
        guest.document_type = document.document_type
        guest.document_number_encrypted = encrypt(document.document_number).ciphertext
        guest.document_expiry_date = document.document_expiry_date
        guest.document_status = GuestDocumentStatus.PROVIDED
        await self._guests.save_document(tenant_id, guest)

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.GUEST_DOCUMENT_UPDATED,
            entity_type=audit_actions.ENTITY_GUEST,
            entity_id=guest.id,
            actor=actor,
            # `redacted()` for the number — the only form rule 11 leaves — and for the two
            # other fields of the document group. Recording *which* changed is the point;
            # recording a birth date in an append-only trail is not.
            changes=ChangeSet(audit_actions.ENTITY_GUEST)
            .redacted("document_number_encrypted")
            .redacted("date_of_birth")
            .redacted("nationality")
            .diff("document_type", None, document.document_type.value)
            .diff(
                "document_status",
                (
                    GuestDocumentStatus.PROVIDED.value
                    if had_document
                    else GuestDocumentStatus.NOT_PROVIDED.value
                ),
                GuestDocumentStatus.PROVIDED.value,
            ),
            now=now,
        )

        # R6.3 — the stay may now be ready to report. Only the one named, if any: a guest can
        # have several stays and recomputing all of them from here would make one document
        # edit fan out across bookings a caller never mentioned.
        if reservation_id is not None:
            await self._refresh_readiness(tenant_id, reservation_id, guest)

        await self._uow.commit()
        return guest

    async def _refresh_readiness(
        self, tenant_id: uuid.UUID, reservation_id: uuid.UUID, guest: Guest
    ) -> None:
        stay = await self._stays.get(tenant_id, reservation_id)
        if stay is None:
            raise ReservationNotFoundError()
        target = status_for(
            LegalRegistrationSubject.of(
                guest,
                check_in_date=stay.check_in_date,
                check_out_date=stay.check_out_date,
            ),
            current=stay.status,
        )
        if target is not stay.status:
            await self._stays.set_status(tenant_id, reservation_id, target)


class ReadGuestDocumentUseCase:
    """R7.2 and R7.3 — return the full document, and record that somebody looked.

    **The audit row is written before the plaintext is produced**, not after. If the write
    fails the transaction rolls back and the caller gets an error instead of a document —
    which is the safe direction. The other order would hand out an unaudited document
    whenever the audit write failed, and rule 9 exists precisely for the case where somebody
    later asks who saw it.
    """

    def __init__(
        self,
        *,
        guests: GuestRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._guests = guests
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        guest_id: uuid.UUID,
        actor: GuestActor,
        now: datetime,
    ) -> GuestDocument:
        guest = await self._guests.get_full(tenant_id, guest_id)
        if guest is None:
            raise GuestNotFoundError(guest_id)
        if guest.document_number_encrypted is None:
            raise GuestDocumentMissingError()

        await self._audit.record(
            tenant_id=tenant_id,
            action=audit_actions.GUEST_DOCUMENT_READ,
            entity_type=audit_actions.ENTITY_GUEST,
            entity_id=guest.id,
            actor=actor,
            # A read changes nothing, so the change set is empty and `AuditLogFactory` stores
            # `NULL`. What the row records is the four things rule 9 asks for: who, from
            # where, what and when.
            changes=ChangeSet(audit_actions.ENTITY_GUEST),
            now=now,
        )
        await self._uow.commit()

        return GuestDocument(
            guest_id=guest.id,
            full_name=guest.full_name,
            nationality=guest.nationality,
            date_of_birth=guest.date_of_birth,
            document_type=guest.document_type,
            document_number=decrypt(
                EncryptedSecret(ciphertext=guest.document_number_encrypted)
            ),
            document_expiry_date=guest.document_expiry_date,
            document_status=guest.document_status,
        )


class SubmitLegalRegistrationUseCase:
    """R6.4, R6.5, R6.6 — report a stay to SES.Hospedajes through the adapter.

    PRD §17 step 4-5. The adapter is `MockSESHospedajesAdapter` and PRD §29 keeps it that
    way for the MVP; what this use case delivers is the operational layer around it, so that
    connecting a real one is a change of wiring and nothing else.
    """

    def __init__(
        self,
        *,
        guests: GuestRepository,
        stays: LegalRegistrationStayStore,
        provider: SESHospedajesAdapter,
        users: UserRepository,
        timeline: TimelineEventRepository,
        notifications: NotificationLogRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._guests = guests
        self._stays = stays
        self._provider = provider
        self._users = users
        self._timeline = timeline
        self._notifications = notifications
        self._audit = _AuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        actor: GuestActor,
        now: datetime,
    ) -> LegalRegistrationStatus:
        stay = await self._stays.get(tenant_id, reservation_id)
        if stay is None:
            raise ReservationNotFoundError()
        if stay.status is not LegalRegistrationStatus.READY_TO_SUBMIT:
            # R6.6 — refused **without invoking the adapter**. The order matters: a real
            # provider charges per submission and files with the police.
            raise LegalRegistrationNotReadyError(current=stay.status.value)
        if stay.guest_id is None:
            raise LegalRegistrationNotReadyError(
                current=stay.status.value, missing=("full_name",)
            )

        guest = await self._guests.get_full(tenant_id, stay.guest_id)
        if guest is None:
            raise GuestNotFoundError(stay.guest_id)

        subject = LegalRegistrationSubject.of(
            guest, check_in_date=stay.check_in_date, check_out_date=stay.check_out_date
        )
        absent = missing_fields(subject)
        if absent:
            # `READY_TO_SUBMIT` and yet incomplete: the guest lost a field after the status
            # was computed. Refuse and say which — never submit a partial filing.
            raise LegalRegistrationNotReadyError(current=stay.status.value, missing=absent)

        result = await self._provider.submit_guest(
            submission=self._submission(stay, guest)
        )

        if result.accepted:
            await self._stays.set_status(
                tenant_id, reservation_id, LegalRegistrationStatus.SUBMITTED
            )
            await self._record_event(tenant_id=tenant_id, stay=stay, actor=actor, now=now)
            await self._record_audit(
                tenant_id=tenant_id,
                reservation_id=reservation_id,
                action=audit_actions.LEGAL_REGISTRATION_SUBMITTED,
                previous=stay.status,
                new=LegalRegistrationStatus.SUBMITTED,
                actor=actor,
                now=now,
            )
            await self._uow.commit()
            return LegalRegistrationStatus.SUBMITTED

        # R6.5 — `FAILED`, a notification to the manager, and **no timeline event**: the
        # timeline is append-only and `LEGAL_REGISTRATION_SUBMITTED` would be a permanent
        # claim that a filing happened.
        await self._stays.set_status(
            tenant_id, reservation_id, LegalRegistrationStatus.FAILED
        )
        for recipient in await self._managers(tenant_id):
            await self._notifications.add(
                tenant_id, self._failure_notification(tenant_id, stay, recipient, now)
            )
        await self._record_audit(
            tenant_id=tenant_id,
            reservation_id=reservation_id,
            action=audit_actions.LEGAL_REGISTRATION_FAILED,
            previous=stay.status,
            new=LegalRegistrationStatus.FAILED,
            actor=actor,
            now=now,
        )
        await self._uow.commit()
        logger.warning(
            "guests.legal_registration_failed",
            extra={
                "tenant_id": str(tenant_id),
                "reservation_id": str(reservation_id),
                # The provider's code, which is a closed vocabulary by contract — never its
                # message, which tends to quote back what was submitted.
                "error_code": result.error_code,
            },
        )
        return LegalRegistrationStatus.FAILED

    def _submission(self, stay, guest: Guest) -> LegalSubmission:
        """Built here and nowhere else, from an entity that has already been checked complete.

        The `assert`-free narrowing below is what `missing_fields` bought: every field is
        known present by the time this runs, so the type is fully populated without any of
        the `or ""` fallbacks that would quietly file an incomplete registration.
        """
        return LegalSubmission(
            reservation_id=stay.reservation_id,
            guest_id=guest.id,
            full_name=guest.full_name,
            nationality=guest.nationality,  # type: ignore[arg-type]
            date_of_birth=guest.date_of_birth,  # type: ignore[arg-type]
            document_type=guest.document_type,  # type: ignore[arg-type]
            document_number=decrypt(
                EncryptedSecret(ciphertext=guest.document_number_encrypted)  # type: ignore[arg-type]
            ),
            document_expiry_date=guest.document_expiry_date,  # type: ignore[arg-type]
            check_in_date=stay.check_in_date,
            check_out_date=stay.check_out_date,
        )

    async def _record_event(
        self, *, tenant_id: uuid.UUID, stay, actor: GuestActor, now: datetime
    ) -> None:
        await self._timeline.add(
            tenant_id,
            TimelineEventFactory.create(
                TimelineEventData(
                    id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    property_id=stay.property_id,
                    reservation_id=stay.reservation_id,
                    actor_type=TimelineActorType.USER,
                    actor_user_id=actor.user_id,
                    event_type=TimelineEventType.LEGAL_REGISTRATION_SUBMITTED,
                    title="Legal registration submitted",
                    created_at=now,
                    # Ids only. The timeline is append-only, so nothing that lands here can
                    # ever be redacted — and this is the one flow that handles a document.
                    metadata={"reservation_id": str(stay.reservation_id)},
                )
            ),
        )

    async def _record_audit(
        self,
        *,
        tenant_id: uuid.UUID,
        reservation_id: uuid.UUID,
        action: str,
        previous: LegalRegistrationStatus,
        new: LegalRegistrationStatus,
        actor: GuestActor,
        now: datetime,
    ) -> None:
        await self._audit.record(
            tenant_id=tenant_id,
            action=action,
            entity_type=audit_actions.ENTITY_RESERVATION,
            entity_id=reservation_id,
            actor=actor,
            changes=ChangeSet(audit_actions.ENTITY_RESERVATION).diff(
                "legal_registration_status", previous.value, new.value
            ),
            now=now,
        )

    async def _managers(self, tenant_id: uuid.UUID) -> list:
        """Active managers, falling back to the owner — the pattern `celery-jobs` set.

        R6.5 says "alertar al manager", not "alert whoever pressed the button": the person who
        submitted may not be the one who has to chase it, and in a tenant with no manager the
        owner still has to hear about a failed filing with the police.
        """
        page = await self._users.list(
            tenant_id,
            UserFilters(role=UserRole.PROPERTY_MANAGER, status=UserStatus.ACTIVE),
            page=1,
            per_page=_MAX_RECIPIENTS,
        )
        if page.items:
            return list(page.items)
        owners = await self._users.list(
            tenant_id,
            UserFilters(role=UserRole.TENANT_OWNER, status=UserStatus.ACTIVE),
            page=1,
            per_page=_MAX_RECIPIENTS,
        )
        return list(owners.items)

    def _failure_notification(
        self, tenant_id: uuid.UUID, stay, recipient, now: datetime
    ) -> NotificationLog:
        """Queued, not sent: `PENDING` is the seam `dispatch_notifications` drains.

        `subject`/`body` carry ids and a type, never the content of another row — the
        contract rule 11 fixed in `celery-jobs`, which this change complies with rather than
        re-deriving. Note what is **not** here: no document number, no guest name, nothing
        about why the provider refused.

        `notification_type` is `LEGAL_REGISTRATION_FAILED`, which is **not** one of PRD §14's
        sixteen, and that is deliberate on both counts. The column is free text (`String(100)`)
        precisely so a later module can name its own events; and `NotificationType` is not
        widened because §14's list is the PRD's and its names are canonical. The consequence
        is correct rather than accidental: `escalation_for` returns `None` for an unknown type,
        so a failed filing escalates to nobody — which is right, since it has no SLA deadline
        and the manager is already being told.
        """
        return NotificationLog(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            recipient_user_id=recipient.id,
            recipient_contact=recipient.email,
            channel=NotificationChannel.IN_APP,
            notification_type=LEGAL_REGISTRATION_FAILED_NOTIFICATION,
            created_at=now,
            updated_at=now,
            subject="Legal registration failed",
            body=(
                f"The SES.Hospedajes submission failed. Reservation {stay.reservation_id}."
            ),
            status=NotificationStatus.PENDING,
            related_type=RELATED_TYPE_RESERVATION,
            related_id=stay.reservation_id,
        )
