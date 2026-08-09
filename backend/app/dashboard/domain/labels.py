"""The dashboard's vocabulary, in the reader's language (R5.2, design D4).

`dto.ts:28-34` declares `LocalizedText` as text "already localized by the backend", and PRD
§10 requires the same of anything a person reads. This module is where the **six**
vocabularies the dashboard needs are written down:

* `CLEANING_STATUS_LABELS` — the cleaning status shown on a card,
* `NEXT_ACTION_LABELS` — the actions of `app/dashboard/domain/next_action.py`,
* `RESPONSIBLE_LABELS` — the role that owes one,
* `INCIDENT_TITLE_LABELS` — the title of an open incident, from its **category**,
* `ACCESS_STATUS_LABELS` — how the guest gets in, from `Reservation.access_status`,
* `APPROVAL_LABELS` — a pending owner approval, from its **related type**.

Five of them arrived with section 5 and `ACCESS_STATUS_LABELS` with section 6, which is why
task 5.3 names only four vocabularies: R2.5 needs an access label and the task list did not
enumerate it. Each catalogue is named here rather than described loosely, because the last
time this list was prose it drifted out of date within one section (QA panel, section 5).

**Why titles come from enums and not from the stored text.** `incidents.title` and
`owner_approvals.reason` are free text typed by whoever reported the fault or requested the
money, in whatever language they typed it — so they could never satisfy a `LocalizedText`
contract, and rule 11 of `steering/security.md` treats them as sinks that may be carrying
something sensible without saying so. `IncidentCategory` and `OwnerApprovalRelatedType` are
closed enums, translate cleanly, and are what
`app/maintenance/domain/value_objects.py` projects. The privacy fix and the localisation
requirement turn out to want the same thing.

**Why it lives in `domain/` and not in `api/schemas.py`** (D4): the cards, the detail and
future surfaces need the same table, and a router-local copy would become three. Precedent:
`app/access/domain/masking.py` sits in `domain/` because "the rule is a business constraint
and not a rendering detail". It stays pure Python — `str` and `dict` — which
`tests/test_layering.py` enforces.

Every catalogue is **exhaustive over its enum**, and a test walks each one, so a value added
later breaks the suite instead of reaching a reader untranslated.
"""

from app.cleaning.domain.enums import CleaningTaskStatus
from app.core.i18n import Catalog, Locale
from app.dashboard.domain.next_action import NEXT_ACTION_BY_STATE, Responsible
from app.maintenance.domain.enums import IncidentCategory, OwnerApprovalRelatedType
from app.reservations.domain.enums import ReservationAccessStatus

CLEANING_STATUS_LABELS = Catalog(
    {
        CleaningTaskStatus.CREATED.value: {
            Locale.ES: "Limpieza creada",
            Locale.EN: "Cleaning created",
        },
        CleaningTaskStatus.ASSIGNED.value: {
            Locale.ES: "Limpiadora asignada",
            Locale.EN: "Cleaner assigned",
        },
        CleaningTaskStatus.ACCEPTED.value: {
            Locale.ES: "Limpieza aceptada",
            Locale.EN: "Cleaning accepted",
        },
        CleaningTaskStatus.REJECTED.value: {
            Locale.ES: "Limpieza rechazada",
            Locale.EN: "Cleaning rejected",
        },
        CleaningTaskStatus.IN_PROGRESS.value: {
            Locale.ES: "Limpieza en curso",
            Locale.EN: "Cleaning in progress",
        },
        CleaningTaskStatus.PENDING_REVIEW.value: {
            Locale.ES: "Pendiente de validar",
            Locale.EN: "Pending validation",
        },
        CleaningTaskStatus.COMPLETED.value: {
            Locale.ES: "Limpieza completada",
            Locale.EN: "Cleaning completed",
        },
        CleaningTaskStatus.FAILED.value: {
            Locale.ES: "Limpieza no superada",
            Locale.EN: "Cleaning failed",
        },
        CleaningTaskStatus.CANCELLED.value: {
            Locale.ES: "Limpieza cancelada",
            Locale.EN: "Cleaning cancelled",
        },
    }
)

#: Keyed by the `action_key` of `NextAction`, not by state: two states could one day share
#: an action, and the catalogue should not have to know which states exist.
NEXT_ACTION_LABELS = Catalog(
    {
        "assign_cleaner": {
            Locale.ES: "Asignar limpiadora",
            Locale.EN: "Assign a cleaner",
        },
        "pending_acceptance": {
            Locale.ES: "Pendiente de aceptar",
            Locale.EN: "Pending acceptance",
        },
        "cleaning_in_progress": {
            Locale.ES: "Limpieza en curso",
            Locale.EN: "Cleaning in progress",
        },
        "deliver_access": {
            Locale.ES: "Entregar acceso",
            Locale.EN: "Deliver access",
        },
        "review_incident": {
            Locale.ES: "Revisar incidencia",
            Locale.EN: "Review the incident",
        },
        "attend_incident": {
            Locale.ES: "Atender incidencia",
            Locale.EN: "Attend the incident",
        },
    }
)

#: The role that owes an action, as a person reads it. A role and never a name (D6).
RESPONSIBLE_LABELS = Catalog(
    {
        Responsible.MANAGER.value: {
            Locale.ES: "Gestor",
            Locale.EN: "Manager",
        },
        Responsible.ASSIGNED_CLEANER.value: {
            Locale.ES: "Limpiadora asignada",
            Locale.EN: "Assigned cleaner",
        },
    }
)

#: An open incident's title, from its category. See this module's docstring for why not from
#: `incidents.title`.
INCIDENT_TITLE_LABELS = Catalog(
    {
        IncidentCategory.ACCESS.value: {Locale.ES: "Problema de acceso", Locale.EN: "Access problem"},
        IncidentCategory.LOCK.value: {Locale.ES: "Problema con la cerradura", Locale.EN: "Lock problem"},
        IncidentCategory.WIFI.value: {Locale.ES: "Problema de wifi", Locale.EN: "Wi-Fi problem"},
        IncidentCategory.ELECTRICITY.value: {Locale.ES: "Problema eléctrico", Locale.EN: "Electrical problem"},
        IncidentCategory.WATER.value: {Locale.ES: "Problema de agua", Locale.EN: "Water problem"},
        IncidentCategory.PLUMBING.value: {Locale.ES: "Problema de fontanería", Locale.EN: "Plumbing problem"},
        IncidentCategory.HVAC.value: {
            Locale.ES: "Problema de climatización",
            Locale.EN: "Heating or cooling problem",
        },
        IncidentCategory.APPLIANCE.value: {
            Locale.ES: "Electrodoméstico averiado",
            Locale.EN: "Broken appliance",
        },
        IncidentCategory.NOISE.value: {Locale.ES: "Problema de ruido", Locale.EN: "Noise problem"},
        IncidentCategory.CLEANING.value: {
            Locale.ES: "Problema de limpieza",
            Locale.EN: "Cleaning problem",
        },
        IncidentCategory.DAMAGE.value: {Locale.ES: "Desperfecto", Locale.EN: "Damage"},
        IncidentCategory.SAFETY.value: {
            Locale.ES: "Problema de seguridad",
            Locale.EN: "Safety problem",
        },
        IncidentCategory.OTHER.value: {Locale.ES: "Otra incidencia", Locale.EN: "Other incident"},
    }
)

#: How the guest gets in, as a **label and never a code** (R2.5, design D9).
#:
#: Rendered from `Reservation.access_status`, the column `AccessRecordRepository.save`
#: projects — so the detail costs no extra query for it. Not from the access record itself:
#: that would be a second source for one fact, and the projection exists precisely so
#: readers do not have to join.
#:
#: Task 5.3 listed four vocabularies and this is a fifth. It is not scope creep: R2.5 says
#: "en `access` únicamente una etiqueta de estado", `AccessBlock.label` is typed
#: `LocalizedText` by `dto.ts:125-127`, and there was no catalogue that could render it —
#: the task list simply did not enumerate it.
ACCESS_STATUS_LABELS = Catalog(
    {
        ReservationAccessStatus.PENDING.value: {
            Locale.ES: "Acceso pendiente",
            Locale.EN: "Access pending",
        },
        ReservationAccessStatus.CREATED_EXTERNAL.value: {
            Locale.ES: "Acceso gestionado por el proveedor",
            Locale.EN: "Access managed by the provider",
        },
        ReservationAccessStatus.MANUAL_ADDED.value: {
            Locale.ES: "Acceso registrado",
            Locale.EN: "Access registered",
        },
        ReservationAccessStatus.DELIVERED.value: {
            Locale.ES: "Acceso entregado",
            Locale.EN: "Access delivered",
        },
        ReservationAccessStatus.EXPIRED.value: {
            Locale.ES: "Acceso caducado",
            Locale.EN: "Access expired",
        },
        ReservationAccessStatus.NOT_REQUIRED.value: {
            Locale.ES: "Sin acceso que entregar",
            Locale.EN: "No access to deliver",
        },
    }
)

#: A pending approval's label, from what it relates to.
APPROVAL_LABELS = Catalog(
    {
        OwnerApprovalRelatedType.INCIDENT.value: {
            Locale.ES: "Aprobación de incidencia",
            Locale.EN: "Incident approval",
        },
        OwnerApprovalRelatedType.MAINTENANCE_COST.value: {
            Locale.ES: "Aprobación de gasto de mantenimiento",
            Locale.EN: "Maintenance cost approval",
        },
        OwnerApprovalRelatedType.OTHER.value: {
            Locale.ES: "Aprobación pendiente",
            Locale.EN: "Pending approval",
        },
    }
)

#: Every `action_key` the next-action table can produce. Derived rather than restated, so
#: the coverage test cannot drift from the table it is checking.
NEXT_ACTION_KEYS = frozenset(
    action.action_key for action in NEXT_ACTION_BY_STATE.values() if action is not None
)
