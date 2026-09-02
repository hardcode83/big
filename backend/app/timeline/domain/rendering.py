"""Readable timeline entries in the reader's language (R5, design D4/D5).

`TimelineEventFactory` freezes an English `title` at write time
(`services.py:112`: `f"Property state changed to {...}"`) and the timeline is immutable,
so the past cannot be rewritten into anyone's language. What can be done is compose the
text **at read time** from the two columns that are language-neutral: `event_type` and
`metadata`. That is what this module does.

**Why the catalogue lives in `domain/` and not in `api/schemas.py`** (D4): the cards, the
detail and the timeline all need the same table, so a router-local copy would become three.
And there is precedent for a presentation rule owned by the domain —
`app/access/domain/masking.py` sits here because "the rule is a business constraint and not
a rendering detail". PRD §10 does the same with legibility. It stays pure Python: `str` and
`dict`, no pydantic, no sqlalchemy.

**The stored `title` is never modified** (R5.3). It remains the English audit copy that
`steering/backend.md` requires of system messages; this module reads past it, and falls
back to it when it has nothing better (R5.4).
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.i18n import Catalog, Locale
from app.timeline.domain.entities import TimelineEvent
from app.timeline.domain.enums import TimelineActorType, TimelineEventType, TimelineSeverity

# The longest metadata value that may be substituted into a template. `metadata` is free
# JSONB written by each domain's factory, so its values are not bounded by any column
# width; without a cap one oversized entry would be echoed verbatim into a response.
MAX_SUBSTITUTED_LENGTH = 200


@dataclass(frozen=True)
class RenderedEntry:
    """One timeline entry as the reader sees it — the fields of `TimelineEntry`
    (`frontend/features/dashboard/data/dto.ts:99-108`).

    `metadata` is deliberately absent: R4.3 says it is free JSON and not part of the read
    contract, and a projection that lacks the field cannot serialise it by accident — the
    same construction `GuestSummary` uses for the guest document.
    """

    id: uuid.UUID
    occurred_at: datetime
    actor_type: TimelineActorType
    event_type: TimelineEventType
    severity: TimelineSeverity
    title: str
    description: str | None


#: `event_type.value` → locale → title template.
#:
#: **Every `TimelineEventType` has an entry in both locales, and a test walks the enum to
#: keep it that way** (R5.4). The fallback in `render` therefore exists for a type added by
#: a *future* change, not for one forgotten today: a new enum member breaks the suite
#: instead of reaching production speaking English.
#:
#: Placeholders are used only where the writing factory guarantees the key:
#: `to_state` for `PROPERTY_STATE_CHANGED` (`TimelineEventFactory.property_state_changed`
#: always stores it) and `source` for `RESERVATION_IMPORTED` (`ingest.py:311`). Everywhere
#: else the title is static, because a placeholder whose key its factory never stored
#: would silently degrade the whole entry.
#:
#: The canonical literal inside `{to_state}` is NOT translated (R5.5): it travels as the
#: exact PRD value, which is what the frontend maps.
TIMELINE_TITLE_TEMPLATES: dict[TimelineEventType, dict[Locale, str]] = {
    TimelineEventType.RESERVATION_IMPORTED: {
        Locale.ES: "Reserva importada desde {source}",
        Locale.EN: "Reservation imported from {source}",
    },
    TimelineEventType.RESERVATION_CREATED_MANUAL: {
        Locale.ES: "Reserva creada manualmente",
        Locale.EN: "Reservation created manually",
    },
    TimelineEventType.RESERVATION_UPDATED: {
        Locale.ES: "Reserva actualizada",
        Locale.EN: "Reservation updated",
    },
    TimelineEventType.RESERVATION_CANCELLED: {
        Locale.ES: "Reserva cancelada",
        Locale.EN: "Reservation cancelled",
    },
    TimelineEventType.CHECKIN_WINDOW_OPENED: {
        Locale.ES: "Ventana de entrada abierta",
        Locale.EN: "Check-in window opened",
    },
    TimelineEventType.CHECKOUT_WINDOW_REACHED: {
        Locale.ES: "Hora de salida alcanzada",
        Locale.EN: "Check-out window reached",
    },
    TimelineEventType.PROPERTY_STATE_CHANGED: {
        Locale.ES: "Estado de la vivienda actualizado a {to_state}",
        Locale.EN: "Property state changed to {to_state}",
    },
    TimelineEventType.ACCESS_CODE_PENDING: {
        Locale.ES: "Acceso pendiente",
        Locale.EN: "Access pending",
    },
    TimelineEventType.ACCESS_CODE_CREATED_EXTERNAL: {
        Locale.ES: "Acceso gestionado por el proveedor",
        Locale.EN: "Access managed by the provider",
    },
    TimelineEventType.ACCESS_CODE_MANUAL_ADDED: {
        Locale.ES: "Código de acceso registrado",
        Locale.EN: "Access code registered",
    },
    TimelineEventType.ACCESS_CODE_DELIVERED: {
        Locale.ES: "Instrucciones de acceso entregadas",
        Locale.EN: "Access instructions delivered",
    },
    TimelineEventType.GUEST_MESSAGE_RECEIVED: {
        Locale.ES: "Mensaje del huésped recibido",
        Locale.EN: "Guest message received",
    },
    TimelineEventType.AI_RESPONSE_SENT: {
        Locale.ES: "Respuesta automática enviada",
        Locale.EN: "AI response sent",
    },
    TimelineEventType.AI_ESCALATED_TO_HUMAN: {
        Locale.ES: "Conversación escalada a una persona",
        Locale.EN: "Conversation escalated to a human",
    },
    TimelineEventType.HUMAN_RESPONSE_SENT: {
        Locale.ES: "Respuesta enviada por una persona",
        Locale.EN: "Human response sent",
    },
    TimelineEventType.CLEANING_TASK_CREATED: {
        Locale.ES: "Tarea de limpieza creada",
        Locale.EN: "Cleaning task created",
    },
    TimelineEventType.CLEANER_ASSIGNED: {
        Locale.ES: "Limpiadora asignada",
        Locale.EN: "Cleaner assigned",
    },
    TimelineEventType.CLEANER_ACCEPTED: {
        Locale.ES: "La limpiadora ha aceptado",
        Locale.EN: "Cleaner accepted",
    },
    TimelineEventType.CLEANER_REJECTED: {
        Locale.ES: "La limpiadora ha rechazado",
        Locale.EN: "Cleaner rejected",
    },
    TimelineEventType.CLEANING_STARTED: {
        Locale.ES: "Limpieza iniciada",
        Locale.EN: "Cleaning started",
    },
    TimelineEventType.CLEANING_PHOTO_UPLOADED: {
        Locale.ES: "Foto de limpieza subida",
        Locale.EN: "Cleaning photo uploaded",
    },
    TimelineEventType.CLEANING_COMPLETED: {
        Locale.ES: "Limpieza completada",
        Locale.EN: "Cleaning completed",
    },
    TimelineEventType.CLEANING_FAILED_VALIDATION: {
        Locale.ES: "La limpieza no ha superado la validación",
        Locale.EN: "Cleaning failed validation",
    },
    TimelineEventType.INCIDENT_CREATED: {
        Locale.ES: "Incidencia creada",
        Locale.EN: "Incident created",
    },
    TimelineEventType.INCIDENT_CLASSIFIED: {
        Locale.ES: "Incidencia clasificada",
        Locale.EN: "Incident classified",
    },
    TimelineEventType.TECHNICIAN_ASSIGNED: {
        Locale.ES: "Técnico asignado",
        Locale.EN: "Technician assigned",
    },
    TimelineEventType.TECHNICIAN_ACCEPTED: {
        Locale.ES: "El técnico ha aceptado",
        Locale.EN: "Technician accepted",
    },
    TimelineEventType.TECHNICIAN_REJECTED: {
        Locale.ES: "El técnico ha rechazado",
        Locale.EN: "Technician rejected",
    },
    TimelineEventType.TECHNICIAN_EN_ROUTE: {
        Locale.ES: "Técnico en camino",
        Locale.EN: "Technician en route",
    },
    TimelineEventType.TECHNICIAN_STARTED: {
        Locale.ES: "El técnico ha empezado",
        Locale.EN: "Technician started",
    },
    TimelineEventType.INCIDENT_RESOLVED: {
        Locale.ES: "Incidencia resuelta",
        Locale.EN: "Incident resolved",
    },
    TimelineEventType.INCIDENT_CANCELLED: {
        Locale.ES: "Incidencia cancelada",
        Locale.EN: "Incident cancelled",
    },
    TimelineEventType.OWNER_APPROVAL_REQUIRED: {
        Locale.ES: "Se requiere la aprobación del propietario",
        Locale.EN: "Owner approval required",
    },
    TimelineEventType.OWNER_APPROVED_EXPENSE: {
        Locale.ES: "El propietario ha aprobado el gasto",
        Locale.EN: "Owner approved the expense",
    },
    TimelineEventType.OWNER_REJECTED_EXPENSE: {
        Locale.ES: "El propietario ha rechazado el gasto",
        Locale.EN: "Owner rejected the expense",
    },
    TimelineEventType.LOCK_ALERT_RECEIVED: {
        Locale.ES: "Alerta de la cerradura recibida",
        Locale.EN: "Lock alert received",
    },
    TimelineEventType.PRICE_RECOMMENDATION_CREATED: {
        Locale.ES: "Recomendación de precio creada",
        Locale.EN: "Price recommendation created",
    },
    TimelineEventType.PRICE_UPDATED_EXTERNAL: {
        Locale.ES: "Precio actualizado en el canal",
        Locale.EN: "Price updated in the channel",
    },
    TimelineEventType.LEGAL_REGISTRATION_SUBMITTED: {
        Locale.ES: "Registro legal enviado",
        Locale.EN: "Legal registration submitted",
    },
    # `guest-portal-api` D12. Next to the legal registration and NOT next to
    # `CHECKIN_WINDOW_OPENED` on purpose: that one is the clock opening the window, this one is
    # the guest having actually filled in the eight fields of PRD §17, which is the step the
    # submission above waits for.
    #
    # A static title, with no placeholder: `metadata` carries only `reservation_id`, because the
    # timeline is append-only and the operation this event records is the one flow in the system
    # that handles an identity document — so nothing about the person may land in a row that can
    # never be redacted.
    TimelineEventType.GUEST_CHECKIN_COMPLETED: {
        Locale.ES: "El huésped ha completado el check-in",
        Locale.EN: "Guest completed check-in",
    },
    # `revenue-statements` (tasks 4.6, design D5/D12). Static title with no placeholder:
    # the period is in the row's `metadata` and the title just says what happened, exactly
    # like `PRICE_RECOMMENDATION_CREATED` — the trail for the clock path the audit log
    # does not carry (sixth exception of regla 9).
    TimelineEventType.OWNER_STATEMENT_GENERATED: {
        Locale.ES: "Liquidación generada",
        Locale.EN: "Owner statement generated",
    },
    TimelineEventType.REVIEW_IMPORTED: {
        Locale.ES: "Reseña importada",
        Locale.EN: "Review imported",
    },
    TimelineEventType.REVIEW_RESPONSE_DRAFTED: {
        Locale.ES: "Borrador de respuesta a la reseña",
        Locale.EN: "Review response drafted",
    },
    TimelineEventType.REVIEW_RESPONSE_APPROVED: {
        Locale.ES: "Respuesta a la reseña aprobada",
        Locale.EN: "Review response approved",
    },
    # `revenue-reviews` (design D8). Five new members, each carrying identifiers only
    # in `metadata` (no reviewer's body — the column is append-only and rule 11 of
    # `steering/security.md` would never recover from a leak). Static titles, on
    # purpose, mirroring the `REVIEW_IMPORTED` / `REVIEW_RESPONSE_DRAFTED` pair
    # above. A `REVIEW_CLASSIFIED_LOW_CONFIDENCE` carries the sentiment in metadata,
    # which the timeline does not interpolate today.
    TimelineEventType.REVIEW_CREATED: {
        Locale.ES: "Reseña creada",
        Locale.EN: "Review created",
    },
    TimelineEventType.REVIEW_DRAFT_EDITED: {
        Locale.ES: "Borrador de respuesta a la reseña editado",
        Locale.EN: "Review response draft edited",
    },
    TimelineEventType.REVIEW_CLASSIFIED_LOW_CONFIDENCE: {
        Locale.ES: "Reseña clasificada con baja confianza",
        Locale.EN: "Review classified with low confidence",
    },
    TimelineEventType.REVIEW_IGNORED: {
        Locale.ES: "Reseña ignorada",
        Locale.EN: "Review ignored",
    },
    TimelineEventType.REVIEW_POSTED_MANUALLY: {
        Locale.ES: "Reseña publicada manualmente",
        Locale.EN: "Review posted manually",
    },
    TimelineEventType.SLA_BREACH_WARNING: {
        Locale.ES: "Aviso de incumplimiento de SLA",
        Locale.EN: "SLA breach warning",
    },
    TimelineEventType.NOTIFICATION_SENT: {
        Locale.ES: "Notificación enviada",
        Locale.EN: "Notification sent",
    },
    TimelineEventType.NOTIFICATION_FAILED: {
        Locale.ES: "Notificación fallida",
        Locale.EN: "Notification failed",
    },
    TimelineEventType.WEBHOOK_RECEIVED: {
        Locale.ES: "Webhook recibido",
        Locale.EN: "Webhook received",
    },
}

TIMELINE_TITLES = Catalog(
    {event_type.value: templates for event_type, templates in TIMELINE_TITLE_TEMPLATES.items()}
)

#: Which `metadata` keys each event type may interpolate — an allow-list **per type**, not
#: per catalogue.
#:
#: Filtering by value type and length alone was the first version, and the security panel of
#: section 2 named what it does not cover: `metadata` is free JSONB written through generic
#: helpers (`reservations`' `record()` takes `dict[str, Any]` for any event type), so a key
#: called `source` could one day carry caller-influenced text for an event type that has
#: nothing to do with an import — and it would render verbatim into a title.
#:
#: Keyed to the factory that actually populates it: `TimelineEventFactory.property_state_changed`
#: always stores `to_state` (`app/timeline/domain/services.py:103-107`), and the CSV/PMS ingest
#: always stores `source` from a module constant (`app/integrations/application/ingest.py:311`).
#: An event type absent from this mapping may interpolate nothing at all, which is why every
#: other template is static text.
SUBSTITUTABLE_METADATA_KEYS: dict[TimelineEventType, frozenset[str]] = {
    TimelineEventType.PROPERTY_STATE_CHANGED: frozenset({"to_state"}),
    TimelineEventType.RESERVATION_IMPORTED: frozenset({"source"}),
}


def render(event: TimelineEvent, locale: Locale) -> RenderedEntry:
    """The entry as `locale` reads it, degrading to the stored title (R5.1, R5.4).

    `description` is passed through rather than composed, and that is not an omission: the
    descriptions the writers store are human text — `PropertyStateTransition.reason`, typed
    by whoever blocked or reactivated the property — and translating what a person wrote is
    not this module's job. A type whose description *is* system-generated can gain a
    template here when it arrives.
    """
    title = TIMELINE_TITLES.render(
        event.event_type.value, locale, _substitutable(event.event_type, event.metadata)
    )
    return RenderedEntry(
        id=event.id,
        occurred_at=event.created_at,
        actor_type=event.actor_type,
        event_type=event.event_type,
        severity=event.severity,
        title=title if title is not None else event.title,
        description=event.description,
    )


def _substitutable(
    event_type: TimelineEventType, metadata: dict[str, Any]
) -> dict[str, Any]:
    """The metadata entries this event type's template may interpolate.

    Two filters, and both are load-bearing:

    * **The key is on this type's allow-list** (`SUBSTITUTABLE_METADATA_KEYS`). Nothing else
      is offered to the template, whatever the writer stored.
    * **The value is a bounded scalar.** `metadata` is free JSONB, so a value can be a
      nested object, a list, or a string of any length — none of which belongs verbatim in
      a one-line title.

    Dropping a key rather than coercing it means the template cannot render, which routes
    the entry to the stored title (R5.4) instead of putting a `dict` repr in front of a
    reader.
    """
    allowed = SUBSTITUTABLE_METADATA_KEYS.get(event_type, frozenset())
    return {
        key: value
        for key, value in metadata.items()
        if key in allowed
        if isinstance(value, (str, int, float)) and not isinstance(value, bool)
        if not isinstance(value, str) or len(value) <= MAX_SUBSTITUTED_LENGTH
    }
