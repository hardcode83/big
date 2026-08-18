"""Fills a bootstrapped tenant with the demo dataset of PRD §27 (`make seed-demo`).

**It presupposes `make bootstrap`.** That command creates the tenant, its config and the two
administrative accounts; this one completes them with the two properties, the two operational
accounts, the three reservations and the cleaning checklist template. Without the tenant it
refuses to run rather than creating one — two commands that both create tenants would be two
answers to "which tenant is this environment about".

Everything is written through each domain's canonical way in — its use case where one does what
the seed needs, its entity and port where none does, never an ORM model (design D2). That is
what keeps the seed from becoming a second writer with its own copy of the invariants.

Deliberately NOT an Alembic data migration, for the reasons `bootstrap.py` already gives, and
NOT hooked into `make up`: it needs SEED_* values a person has to choose.
"""

import asyncio
import sys
import uuid
from dataclasses import dataclass
from functools import partial
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Imported for its side effect, the same way `pms_sync.py` documents it: a command has its own
# import graph, and without every model module registered SQLAlchemy cannot resolve the foreign
# keys between tables it has not seen. No unit test catches its absence — the suite's conftest
# imports the registry for every test — so only running the command for real does.
import app.core.models_registry  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.domain import actions
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.auth.domain.entities import User
from app.auth.domain.enums import UserRole
from app.auth.domain.repositories import UserFilters
from app.auth.domain.value_objects import normalize_email
from app.auth.infrastructure.password_hasher import BcryptPasswordHasher
from app.auth.infrastructure.repositories import SqlAlchemyUserRepository
from app.cleaning.application.evidence import CompletionEvidenceGatherer
from app.cleaning.application.use_cases import (
    AcceptCleaningTaskUseCase,
    CleaningActor,
    CompleteChecklistItemUseCase,
    CompleteCleaningTaskUseCase,
    CreateChecklistTemplateCommand,
    CreateChecklistTemplateUseCase,
    ProvisionCleaningTaskUseCase,
    StartCleaningTaskUseCase,
    UploadCleaningPhotoUseCase,
)
from app.cleaning.domain.enums import CleaningTaskStatus
from app.cleaning.infrastructure.repositories import (
    SqlAlchemyBlockingIncidentQuery,
    SqlAlchemyCleaningChecklistCompletionRepository,
    SqlAlchemyCleaningChecklistTemplateRepository,
    SqlAlchemyCleaningPhotoRepository,
    SqlAlchemyCleaningTaskRepository,
)
from app.core.config import settings
from app.core.db import async_session_factory, bind_session_to_tenant
from app.core.unit_of_work import CallerOwnedUnitOfWork, SqlAlchemyUnitOfWork
from app.guests.domain.entities import Guest
from app.guests.infrastructure.repositories import SqlAlchemyGuestRepository
from app.integrations.application.ingest import IngestRow, ReservationIngestor
from app.integrations.domain.dtos import ReservationDTO
from app.integrations.domain.storage import derive_signing_key
from app.integrations.infrastructure.storage import (
    ConfiguredFileStorageFactory,
    build_s3_client,
    credentials_are_resolvable,
)
from app.maintenance.application.use_cases import (
    AssignIncidentUseCase,
    ClassifyIncidentUseCase,
    IncidentActor,
    ReportIncidentUseCase,
)
from app.maintenance.domain.entities import Incident
from app.maintenance.domain.exceptions import InvalidTechnicianError
from app.maintenance.domain.enums import (
    IncidentCategory,
    IncidentSeverity,
    IncidentSource,
)
from app.maintenance.domain.repositories import IncidentFilters
from app.maintenance.infrastructure.classifier import RuleBasedIncidentClassifier
from app.maintenance.infrastructure.repositories import (
    SqlAlchemyIncidentReader,
    SqlAlchemyIncidentRepository,
    SqlAlchemyLiveCleaningTaskQuery,
)
from app.notifications.infrastructure.repositories import SqlAlchemyNotificationLogRepository
from app.properties.application.use_cases import (
    AdvancePropertyStatesUseCase,
    AdvanceReport,
)
from app.properties.domain.clock_triggers import effective_bounds
from app.properties.domain.entities import Property
from app.properties.domain.transition_enums import PropertyStateTrigger
from app.properties.application.property_admin import (
    CreatePropertyCommand,
    CreatePropertyUseCase,
)
from app.properties.infrastructure.repositories import (
    SqlAlchemyPropertyRepository,
    SqlAlchemyPropertyStateTransitionRepository,
)
from app.reservations.application.use_cases import (
    CreateReservationCommand,
    CreateReservationUseCase,
    UpdateReservationUseCase,
)
from app.reservations.domain.entities import Reservation
from app.reservations.domain.enums import ReservationChannel, ReservationStatus
from app.reservations.domain.repositories import ReservationFilters
from app.reservations.infrastructure.repositories import SqlAlchemyReservationRepository
from app.tenants.infrastructure.repositories import SqlAlchemyTenantConfigRepository
from app.tenants.domain.enums import StorageType
from app.tenants.infrastructure.models import TenantConfigModel, TenantModel
from app.timeline.domain.enums import TimelineActorType
from app.timeline.infrastructure.repositories import SqlAlchemyTimelineEventRepository


class SeedConfigurationError(Exception):
    """A required SEED_* variable is missing."""


class SeedPreconditionError(Exception):
    """The environment this seed completes has not been bootstrapped."""


class SeedConflictError(Exception):
    """An address of the demo dataset already belongs to another tenant."""


class SeedIngestError(Exception):
    """The ingest of the OTA reservations reported rows it could not take.

    Its own exception because `ReservationIngestor.ingest` does NOT raise for a bad row: it
    counts it in `skipped`/`errors` and returns a report, which is right for a CSV a person
    uploaded and wrong for a dataset this module wrote itself. Without this, a seed that
    ingested nothing would print counts saying it had seeded.
    """


@dataclass(frozen=True)
class SeedAccount:
    name: str
    email: str
    password: str
    role: UserRole


@dataclass(frozen=True)
class SeedPlan:
    tenant_name: str
    accounts: tuple[SeedAccount, ...]


# The two homes of PRD §27, verbatim. `country` and `timezone` are left off because
# `CreatePropertyCommand` already defaults them to "ES"/"Europe/Madrid", which is what §27
# says; `postal_code` is absent from §27 and stays `None`. `pms_external_id` is deliberately
# NOT set — OQ1 closed that with a no, so `make pms-sync` does not silently import the mock's
# own copy of these reservations on top of the seed's.
SEED_PROPERTIES = (
    CreatePropertyCommand(
        name="Redes 11",
        internal_code="REDES11",
        address_line1="Calle de las Redes, 11",
        city="Madrid",
        province="Madrid",
        max_guests=4,
        bedrooms=2,
        bathrooms=1,
        default_check_in_time=time(15, 0),
        default_check_out_time=time(11, 0),
    ),
    CreatePropertyCommand(
        name="Pajaritos 8",
        internal_code="PAJARITOS8",
        address_line1="Calle Pajaritos, 8",
        city="Madrid",
        province="Madrid",
        max_guests=2,
        bedrooms=1,
        bathrooms=1,
        default_check_in_time=time(15, 0),
        default_check_out_time=time(11, 0),
    ),
)

# The identifiers the seed coins for itself (design D9). They are part of the command's
# contract WITH ITSELF: change one in a future version and that run re-seeds a duplicate,
# because idempotency is keyed on exactly these strings and not on the dates, which move.
AIRBNB_PMS_ID = "SEED-AIRBNB-1"
BOOKING_PMS_ID = "SEED-BOOKING-1"
DIRECT_CHANNEL_ID = "SEED-DIRECT-1"

# What the timeline event will say the stay came from. Not "csv" and not "pms": both would
# be false, and the event is what a person reads when they ask where a booking came from.
SEED_SOURCE = "seed"

# Page size for the one lookup that has to go through `list` (see `_has_reservation_with_
# channel_id`). Paged rather than assumed-to-fit, because a demo environment that has been
# used accumulates real reservations alongside the seeded one.
_RESERVATION_PAGE = 100

#: The same, for the one incident lookup that has to go through `list` (see
#: `_incidents_of_the_tenant`). Paged rather than assumed-to-fit for the same reason.
_INCIDENT_PAGE = 100


# The default cleaning checklist of PRD §7.10, in the shape `parse_template_content` accepts
# and `items_as_json()` persists — `{item_id, label, required}` and
# `{photo_type, label, required}`.
#
# **Declared divergence from §7.10** (design D10): the PRD draws `id`/`label_es`/`label_en`/
# `order`, and what `cleaning` actually implemented has ONE label and orders by position in
# the list. So the label is written in Spanish — the tenant's `default_language` per §27 —
# and §7.10's order is the order below. Teaching the schema two languages is a change to
# `cleaning`, not to the seed.
#
# `required` is `True` on every entry and spelled out rather than left off: the parser reads
# a missing `required` as `False`, and it demands a real `bool` — `1` is refused.
_CHECKLIST_NAME = "Limpieza estándar"
_CHECKLIST_ITEMS = (
    ("ventilate", "Ventilar la vivienda"),
    ("remove_rubbish", "Sacar la basura"),
    ("check_fridge", "Revisar la nevera"),
    ("clean_kitchen_surfaces", "Limpiar las superficies de la cocina"),
    ("clean_sink", "Limpiar el fregadero"),
    ("clean_bathroom", "Limpiar el baño"),
    ("replace_toilet_paper", "Reponer el papel higiénico"),
    ("replace_towels", "Cambiar las toallas"),
    ("make_beds", "Hacer las camas"),
    ("check_linen", "Revisar la ropa de cama"),
    ("mop_floor", "Fregar el suelo"),
    ("check_sofa", "Revisar el sofá"),
    ("replenish_amenities", "Reponer los amenities"),
    ("check_wifi_router", "Comprobar el router del WiFi"),
    ("check_ac_remote", "Comprobar el mando del aire acondicionado"),
    ("check_keys", "Comprobar las llaves"),
    ("report_damages", "Reportar desperfectos"),
    ("upload_photos", "Subir las fotos"),
)
_CHECKLIST_PHOTOS = (
    ("living_room", "Salón"),
    ("bedroom", "Dormitorio"),
    ("bathroom", "Baño"),
    ("kitchen", "Cocina"),
    ("entrance", "Entrada"),
    ("damage_if_found", "Desperfecto, si lo hay"),
)


@dataclass(frozen=True)
class SeedIncident:
    """One of the three incidents of PRD §27, with the verdict §27 declares for it.

    `category` and `severity` are **not** written by the seed: they are what the classifier
    has to produce, and R1.3 aborts if it produces anything else. Keeping them here is what
    turns a drifting classifier into a red failure instead of a quietly different dataset.
    """

    internal_code: str
    source: IncidentSource
    title: str
    description: str
    category: IncidentCategory
    severity: IncidentSeverity


# The three incidents of PRD §27, verbatim.
#
# **Constants of the module and not composed text**, which is the whole point (design D6):
# `incidents.title`/`description` are rule-11 sinks of `steering/security.md`, and their
# excepción 2 concedes "la prosa que escribió quien reporta… porque el valor no es nuestro y
# no lo hemos ido a buscar" while saying explicitly that it "no autoriza a un escritor
# nuestro". The seed is one of ours, so it does not invoke that exception at all: it writes
# strings that live in the repository, the same move `auth-account-recovery` makes with
# `notification_logs.subject`/`body`.
SEED_INCIDENTS = (
    SeedIncident(
        internal_code="REDES11",
        source=IncidentSource.GUEST,
        title="WiFi va lento",
        description="El huésped reporta que el WiFi va muy lento en la habitación",
        category=IncidentCategory.WIFI,
        severity=IncidentSeverity.LOW,
    ),
    SeedIncident(
        internal_code="REDES11",
        source=IncidentSource.GUEST,
        title="Problema con código de acceso",
        description="El código de acceso no funciona. Huésped bloqueado en la entrada.",
        category=IncidentCategory.ACCESS,
        severity=IncidentSeverity.HIGH,
    ),
    SeedIncident(
        internal_code="PAJARITOS8",
        source=IncidentSource.CLEANER,
        title="Lavadora hace ruido extraño",
        description=(
            "La limpiadora reporta que la lavadora hace un ruido metálico al centrifugar"
        ),
        category=IncidentCategory.APPLIANCE,
        severity=IncidentSeverity.MEDIUM,
    ),
)


def _minimal_jpeg(label: str) -> bytes:
    """A JPEG of the smallest shape `detect_image_type` accepts, tagged with its photo type.

    Synthetic on purpose (proposal, §Out of scope): photos of the real homes are marketing
    material, not seed data. What the six have to be is *real bytes* — the upload path reads
    the format from the content and never from a declared MIME — and *different from each
    other*, so six objects in the store are six objects and not one written six times.

    SOI, a JFIF APP0, a comment segment carrying the photo type, EOI. The three magic bytes
    `\\xff\\xd8\\xff` come from SOI plus the marker prefix of APP0.
    """
    comment = label.encode("ascii")
    return (
        b"\xff\xd8"
        b"\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\xff\xfe"
        + (len(comment) + 2).to_bytes(2, "big")
        + comment
        + b"\xff\xd9"
    )


# One per required photo type, derived from `_CHECKLIST_PHOTOS` rather than written out six
# times: the template above is what decides which photos the cleaning needs to close, so a
# seventh type added there would otherwise leave the seed one photo short of a close it
# cannot explain.
SEED_PHOTO_BYTES: dict[str, bytes] = {
    photo_type: _minimal_jpeg(photo_type) for photo_type, _ in _CHECKLIST_PHOTOS
}


class BytesUpload:
    """`ChunkedUpload` over bytes already in memory — the Protocol only asks for `read`.

    `UploadCleaningPhotoUseCase` consumes its upload in chunks because an HTTP body may be
    enormous; here the content is a constant of this module, and the point of implementing
    the Protocol rather than passing the bytes is that the seed goes through the same door
    as the cleaner's phone.
    """

    def __init__(self, content: bytes) -> None:
        self._content = content
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        end = len(self._content) if size < 0 else self._offset + size
        chunk = self._content[self._offset : end]
        self._offset += len(chunk)
        return chunk


def _ota_reservation_dtos(today: date) -> tuple[ReservationDTO, ...]:
    """The two OTA stays of §27, dated relative to the day of the run (R4.3).

    Both land on REDES11, as §27 says. `status` is left `None` on purpose — see R4.4 — and
    there is no `net_amount` to set: §27's €297.50 is `gross_amount - ota_commission`, which
    `net_amount_from` derives inside the ingestor.
    """
    return (
        ReservationDTO(
            external_id=AIRBNB_PMS_ID,
            channel="AIRBNB",
            property_external_id="REDES11",
            check_in_date=today - timedelta(days=2),
            check_out_date=today + timedelta(days=1),
            guest_name="John Smith",
            guest_email="john.smith@example.com",
            adults=2,
            gross_amount=Decimal("350.00"),
            ota_commission=Decimal("52.50"),
        ),
        ReservationDTO(
            external_id=BOOKING_PMS_ID,
            channel="BOOKING",
            property_external_id="REDES11",
            check_in_date=today + timedelta(days=3),
            check_out_date=today + timedelta(days=7),
            guest_name="María García",
            guest_email="maria.garcia@example.com",
            adults=3,
        ),
    )


def build_plan() -> SeedPlan:
    """Validates everything BEFORE any transaction is opened (R1.5).

    Reporting every missing variable at once for the same reason `bootstrap.build_plan` does:
    the operator is filling in a `.env` and wants the whole list, not one name per run.

    `BOOTSTRAP_TENANT_NAME` is validated here too, although it is not one of the six this
    change adds: it is what names the tenant to complete, so an empty one is missing
    configuration and not a tenant that does not exist. R1.3's message would otherwise send
    the reader to `make bootstrap` for a variable they never filled in.
    """
    required = {
        "BOOTSTRAP_TENANT_NAME": settings.bootstrap_tenant_name,
        "SEED_CLEANER_NAME": settings.seed_cleaner_name,
        "SEED_CLEANER_EMAIL": settings.seed_cleaner_email,
        "SEED_CLEANER_PASSWORD": settings.seed_cleaner_password,
        "SEED_TECHNICIAN_NAME": settings.seed_technician_name,
        "SEED_TECHNICIAN_EMAIL": settings.seed_technician_email,
        "SEED_TECHNICIAN_PASSWORD": settings.seed_technician_password,
    }
    missing = sorted(name for name, value in required.items() if not value.strip())
    if missing:
        # The remedy travels with the condition rather than being appended to every exit-1
        # message by `main()`: since R6.1 the same exception also reports a database column
        # (`tenants.timezone`), and a blanket "fill them in your .env" sent that operator to
        # edit a file where the setting does not exist.
        raise SeedConfigurationError(
            "Missing required environment variables: "
            + ", ".join(missing)
            + ". Fill them in your .env — no defaults are shipped for user passwords "
            "(see .env.example)."
        )

    if normalize_email(settings.seed_cleaner_email) == normalize_email(
        settings.seed_technician_email
    ):
        # Refused HERE, before a transaction, because the alternative is not "one account
        # instead of two": the two lookups below are keyed by address, so one address
        # collapses them into a single entry that answers `None` for both, the loop inserts
        # twice, and the second insert dies inside `uq_users_lower_email`. A SQLAlchemy
        # `IntegrityError` stringifies its statement WITH its parameters, and one of those
        # parameters is the bcrypt hash of a live account — R1.4 forbids exactly that. The
        # address itself is not echoed: it is a person's, and naming the two variables is
        # what the operator needs to fix it.
        raise SeedConfigurationError(
            "SEED_CLEANER_EMAIL and SEED_TECHNICIAN_EMAIL are the same address (value not "
            "echoed). Emails are unique across the whole installation, so the two demo "
            "accounts need two of them."
        )

    return SeedPlan(
        tenant_name=settings.bootstrap_tenant_name.strip(),
        accounts=(
            SeedAccount(
                name=settings.seed_cleaner_name.strip(),
                # Normalised here as well as in the repository, for the reason
                # `bootstrap.build_plan` documents: stored mixed-case, the login lookup would
                # never match and the account could not get in.
                email=normalize_email(settings.seed_cleaner_email),
                password=settings.seed_cleaner_password,
                role=UserRole.CLEANER,
            ),
            SeedAccount(
                name=settings.seed_technician_name.strip(),
                email=normalize_email(settings.seed_technician_email),
                password=settings.seed_technician_password,
                role=UserRole.TECHNICIAN,
            ),
        ),
    )


def _refuse_addresses_owned_by_another_tenant(
    plan: SeedPlan, known: dict[str, User | None], tenant_id: uuid.UUID
) -> None:
    """R3.6, decided before the first write rather than during it.

    Separate from `_seed_accounts` because of WHEN it has to run, not to tidy it away. D11
    requires every exit-1 condition to be settled "antes de la primera escritura […] para que
    «sin escribir nada» sea una propiedad y no una esperanza", and judging one address at a
    time inside the write loop did not do that: a clean `SEED_CLEANER_EMAIL` followed by a
    `SEED_TECHNICIAN_EMAIL` owned by a neighbour flushed a user and an audit row on the first
    iteration and only refused on the second, leaving the guarantee to the rollback of an
    uncommitted transaction — which is precisely the hope D11's sentence rejects. Both
    addresses are judged here, so nothing has been written when the refusal happens.

    The index would refuse the insert anyway (`uq_users_lower_email`): this exists for the
    message, not for the invariant — the same reasoning `bootstrap.apply_plan` gives.
    """
    for account in plan.accounts:
        existing = known[account.email]
        if existing is not None and existing.tenant_id != tenant_id:
            # The address is not echoed: it is a person's, and naming the variable to point
            # elsewhere is what the operator needs (R1.4).
            raise SeedConflictError(
                f"The address of {account.role.value} already belongs to another tenant. "
                "Emails are unique across the whole installation, so this one cannot be "
                "seeded here. Point SEED_CLEANER_EMAIL/SEED_TECHNICIAN_EMAIL elsewhere."
            )


async def _refuse_an_object_store_this_run_cannot_reach(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    """R3.3: an `S3` tenant with a half-filled store is refused BEFORE the transaction.

    It has to be a precondition and not a failure in flight, because `storage_for(S3)` raises
    `StorageWriteError` and **never** falls back to `LOCAL`
    (`integrations/infrastructure/storage/__init__.py:74-82`): without this, a `dev` missing
    one variable would break in the middle of the cleaning cycle and leave `main()`'s
    catch-all to report "unexpected …; details withheld" with exit 2 — the same defect R6.1
    fixes for the timezone. Six photos are `required: True` in the seed's own template, so
    there is no version of this run that skips the store.

    Read with an explicit `WHERE` rather than through `TenantConfigRepository.get_or_create`,
    which INSERTS the row when it is missing: a refusal that had already written something
    would not be the refusal D11 asks for. A tenant with no config row is a `LOCAL` one — that
    is the column's default, and what `get_or_create` would write later inside the
    transaction.

    Names what is missing and never a value: `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` are
    two of the four real secrets of rule 8 in `steering/security.md`.

    **`S3_ENDPOINT_URL` is deliberately NOT in the list**, although R3.3 named it (amended
    2026-08-16, agreed at the section-4 panel after the architect raised the conflict): an
    empty endpoint is the *correct* configuration for AWS itself — «*turning it into `None` is
    what makes "point at AWS" mean configure nothing*» (`cleaning/api/dependencies.py`) — so
    demanding it here would refuse an S3 deployment that every other path of the system
    serves. The store that `dev` runs on does need one, and finds out the ordinary way.
    """
    storage_type = (
        await session.execute(
            select(TenantConfigModel.storage_type).where(
                TenantConfigModel.tenant_id == tenant_id
            )
        )
    ).scalar_one_or_none()
    if storage_type is not StorageType.S3:
        return

    missing = [
        name
        for name, value in (
            ("S3_BUCKET", settings.s3_bucket),
            ("S3_REGION", settings.s3_region),
        )
        if not value.strip()
    ]
    # Asked of the storage package rather than of the environment: the credentials are
    # deliberately not settings of ours (rule 8), so what matters is whether the provider's
    # own chain resolves them — and that question belongs to the module that talks to it.
    if not credentials_are_resolvable():
        missing.append("AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY")
    if missing:
        raise SeedConfigurationError(
            "This tenant stores files in S3 and the demo cleaning uploads six photos, but "
            "this is not configured (values not echoed): "
            + ", ".join(missing)
            + ". Fill it in the environment this command runs in — no photo can be written "
            "until then, and there is no fallback to local disk."
        )


async def _only_actor(
    users: SqlAlchemyUserRepository, tenant_id: uuid.UUID, role: UserRole
) -> User:
    """Resolve one of the two accounts `make bootstrap` created, BY ROLE (design D4).

    Not by the addresses of PRD §27: those belong to `BOOTSTRAP_OWNER_EMAIL` /
    `BOOTSTRAP_MANAGER_EMAIL`, chosen by whoever bootstrapped the environment. Seeding
    §27's addresses blindly would create a fifth account — and a second `TENANT_OWNER` —
    the moment they differ.
    """
    # `assert_tenant_keeps_an_owner` guarantees at LEAST one owner, not exactly one, so a
    # tenant may hold two. Which one this picks is then decided by `list`'s ordering —
    # `name`, with `id` as the tiebreaker — and that is why it is stable rather than
    # arbitrary: two runs of the seed over the same tenant attribute their writes to the
    # same person. Nothing here needs the owner to be unique; D5 needs it to be the same
    # one every time.
    page = await users.list(tenant_id, UserFilters(role=role), page=1, per_page=1)
    if not page.items:
        raise SeedPreconditionError(
            f"This tenant has no {role.value}. The demo seed completes an environment that "
            "`make bootstrap` already prepared — run it first."
        )
    return page.items[0]


async def apply_plan(
    session: AsyncSession,
    plan: SeedPlan,
    hasher: BcryptPasswordHasher,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    """Idempotent: a second run over a seeded database creates nothing (R1.2).

    Split out from `run` so the suite can exercise it against the test session, exactly as
    `test_bootstrap.py` and `test_pms_sync_cli.py` do with theirs.
    """
    at = now or datetime.now(UTC)
    created = {
        "users": 0,
        "properties": 0,
        "guests": 0,
        "reservations": 0,
        "checklist_templates": 0,
        # The three the advance phase adds (D12). Counts of entities CREATED and nothing
        # else: no operational state, no transition — the spec's "un recuento por entidad y
        # nada más", and a state is not an entity somebody created.
        "cleaning_tasks": 0,
        "cleaning_photos": 0,
        "incidents": 0,
    }

    # Resolved BEFORE the session is marked, and the order is not interchangeable: the tenant
    # is found by NAME, so there is no tenant id to scope the lookup with yet. `pms_sync` can
    # mark first only because its tenant arrives as an id. Nothing has been written at this
    # point, so R1.3's "sin escribir nada" is a property of the sequence and not a promise.
    tenant = (
        await session.execute(select(TenantModel).where(TenantModel.name == plan.tenant_name))
    ).scalar_one_or_none()
    if tenant is None:
        raise SeedPreconditionError(
            f"No tenant named {plan.tenant_name!r}. The demo seed completes an environment "
            "that `make bootstrap` already prepared — run it first."
        )
    # Judged here — right after the tenant is resolved and before the first write — and not
    # left to `ZoneInfo(tenant.timezone)` further down: from there an unresolvable zone came
    # out of `main()`'s catch-all as "unexpected ZoneInfoNotFoundError; details withheld",
    # which names neither the column nor the value an operator has to fix. Nothing about a
    # zone name is sensitive, so unlike the `SEED_*` refusals this one echoes it.
    try:
        tenant_zone = ZoneInfo(tenant.timezone)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as error:
        raise SeedConfigurationError(
            f"tenants.timezone is not a resolvable time zone: {tenant.timezone!r}. The demo "
            "dataset is dated on the tenant's calendar day, so this column has to name an "
            "IANA zone (for example 'Europe/Madrid')."
        ) from error

    await _refuse_an_object_store_this_run_cannot_reach(session, tenant.id)

    users = SqlAlchemyUserRepository(session)
    # R3.6's check runs HERE, while the session is still unmarked, and that placement is the
    # whole reason it works. `find_by_email_globally` is one of the deliberately unscoped
    # queries — the set of them is the callers of `require_unmarked_session`, held by
    # `tests/test_unscoped_reads.py` and not by a numeral here, which said "three" and was not
    # off by one — but "unscoped" is a property of the statement, not of the method: once
    # `bind_session_to_tenant` marks the session, the listener of `app/core/db.py` adds the
    # tenant clause to it like to any other ORM read, and an address belonging to a neighbour
    # comes back as `None`. The seed would then insert and get `EmailAlreadyExistsError` out of
    # the index — precisely the database-level failure R3.6 exists to replace with an
    # explanation. Amends design D11, which read this as a check the write loop could make.
    known = {
        account.email: await users.find_by_email_globally(account.email)
        for account in plan.accounts
    }
    # Judged here, with both answers in hand and nothing written yet — see the function's
    # docstring for why this cannot live inside the write loop (R3.6, D11).
    _refuse_addresses_owned_by_another_tenant(plan, known, tenant.id)

    # "Today" is the TENANT's calendar day, not UTC's (R4.3). Taken off `now.date()`, a run
    # between midnight and 01:00 or 02:00 Madrid time used UTC's day, which was still the
    # previous one: all three stays landed a day early against the local calendar, and the
    # "live" AIRBNB stay then checked out at 11:00 that same local morning instead of the
    # following day. §27's environment is `Europe/Madrid` and the tenant carries its own zone,
    # so the composition past/live/upcoming is computed on the calendar the demo is watched
    # on. Recorded as the amendment to D9; pinned by
    # `test_the_dates_are_anchored_to_the_tenants_day_and_not_to_utc`.
    today = at.astimezone(tenant_zone).date()

    # From here on every ORM read is tenant-scoped by that listener: a command does not go
    # through `get_authenticated_request`, which is what normally marks the session.
    bind_session_to_tenant(session, tenant.id)

    uow = SqlAlchemyUnitOfWork(session)

    owner = await _only_actor(users, tenant.id, UserRole.TENANT_OWNER)
    # Resolved and not used as an actor: R3.1 wants the four roles present, and D5 picks the
    # owner for every write because a tenant is guaranteed to keep one
    # (`assert_tenant_keeps_an_owner`) while a manager can be deactivated.
    await _only_actor(users, tenant.id, UserRole.PROPERTY_MANAGER)
    actor_user_id = owner.id

    accounts = await _seed_accounts(
        session,
        plan=plan,
        tenant_id=tenant.id,
        actor_user_id=actor_user_id,
        hasher=hasher,
        users=users,
        known=known,
        now=at,
        created=created,
    )
    properties = SqlAlchemyPropertyRepository(session)
    await _seed_properties(
        session,
        tenant_id=tenant.id,
        actor_user_id=actor_user_id,
        properties=properties,
        now=at,
        created=created,
    )
    await _seed_reservations(
        session,
        tenant_id=tenant.id,
        actor_user_id=actor_user_id,
        properties=properties,
        today=today,
        now=at,
        created=created,
    )
    await _seed_checklist_template(
        session,
        tenant_id=tenant.id,
        properties=properties,
        now=at,
        created=created,
    )
    uploaded_keys: list[str] = []
    try:
        await _advance_the_clock(
            session,
            tenant_id=tenant.id,
            actor_user_id=actor_user_id,
            cleaner=accounts[plan.accounts[0].email],
            technician=accounts[plan.accounts[1].email],
            properties=properties,
            now=at,
            created=created,
            uploaded_keys=uploaded_keys,
        )
        await uow.commit()
    except Exception:
        # R4.6. The rows go back; the objects do not, because they are not in the database —
        # so the one honest thing left is to say which ones are there with nothing pointing
        # at them. Enumerating is not cleaning, and the proposal puts deleting them out of
        # scope: a bucket sweep is an operational tool, not a seed's business. The keys are
        # made of identifiers this command generated (`tenants/{tenant_id}/cleaning-tasks/
        # {task_id}/{photo_id}.{ext}`), never a file name or a value of anyone's.
        if uploaded_keys:
            print(
                "seed-demo: these objects were written to storage and their rows rolled "
                "back, so nothing references them now: " + ", ".join(uploaded_keys),
                file=sys.stderr,
            )
        raise
    return created


async def _advance_the_clock(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    cleaner: User,
    technician: User,
    properties: SqlAlchemyPropertyRepository,
    now: datetime,
    created: dict[str, int],
    uploaded_keys: list[str],
) -> None:
    """The second half of the run: make the dataset happen instead of writing it down (D1, D2).

    Everything above seeds rows; this replays the facts §27 describes **in the order they
    would have occurred**, through the same use cases the API and the scheduler drive. It
    lives inside `apply_plan` and inside its one transaction — a "dataset seeded but not
    advanced" is exactly the intermediate state R4.5 forbids — so every use case is composed
    with `CallerOwnedUnitOfWork()`, as `_seed_checklist_template` already does.

    **The order is the contract, not the presentation** (D2). `_POLICY` is order-sensitive,
    and one permutation loses half the journey in silence: seeding the incidents before the
    stays leaves REDES11 in `MAINTENANCE_REQUIRED`, `(MAINTENANCE_REQUIRED,
    CHECKIN_WINDOW_OPENED)` does not exist in the matrix, and `_advance_one` swallows the
    refusal as a warning — same final state, five transitions fewer, empty timeline. The
    sequence test of the change is what keeps that failure red instead of invisible.

    **Every instant is historical, and that is obligatory rather than tidy** (D3): with
    `now` = today, `CHECKIN_WINDOW_OPENED` demands a stay entering *today* and
    `CHECKIN_TIME_REACHED` demands `utc_instant < utc_end`, so the check-in of a stay that
    began ten days ago is unreachable. The instants are not recomputed here either: they come
    from `effective_bounds`, the same helper the scheduler's own candidate logic uses, so the
    seed cannot drift from the machine's idea of when a stay starts and ends.
    """
    redes = await properties.find_by_internal_code(tenant_id, "REDES11")
    if redes is None:  # pragma: no cover - `_seed_properties` has just guaranteed it
        raise SeedPreconditionError("REDES11 was not seeded; cannot advance its clock.")

    reservations = SqlAlchemyReservationRepository(session)
    direct = await _reservation_by_channel_id(
        reservations, tenant_id, redes.id, DIRECT_CHANNEL_ID
    )
    airbnb = await reservations.find_by_external_pms_id(tenant_id, AIRBNB_PMS_ID)
    if direct is None or airbnb is None:  # pragma: no cover - just seeded above
        raise SeedPreconditionError(
            "The demo stays are not there; cannot advance a clock over nothing."
        )

    past_start, past_end = effective_bounds(redes, direct)
    live_start, _ = effective_bounds(redes, airbnb)

    # Step 1. The DIRECT stay is born `PENDING` — `CreateReservationCommand` takes no `status`
    # on purpose — and all four clock preconditions demand `CONFIRMED`, so until this line the
    # stay the seed has been writing since 2026-08-12 was in a state the clock could never
    # advance (D4). Not a defect of that change: nothing advanced it.
    #
    # **Guarded, and that guard is R4.1's "no mover ningún estado ya alcanzado".** The other
    # two moves below are idempotent for free, because `update_details` writes nothing when
    # the value is already stored; this one is not, because on a second run the stay is
    # `COMPLETED` and `update_details` has no state machine — it would walk it back to
    # `CONFIRMED` and forward again, two real writes and two `RESERVATION_UPDATED` events per
    # re-run. Found by the section-5 review panel.
    if direct.status is ReservationStatus.PENDING:
        await _move_reservation(
            session,
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            reservation_id=direct.id,
            status=ReservationStatus.CONFIRMED,
            now=now,
        )

    # Steps 2-4: Pedro López arrives, stays, and leaves. The checkout is the one that carries
    # a provisioner, which is what creates the `CleaningTask` instead of inserting it.
    await _advance_states(session, tenant_id=tenant_id, trigger=PropertyStateTrigger.CHECKIN_WINDOW_OPENED, now=past_start)
    await _advance_states(session, tenant_id=tenant_id, trigger=PropertyStateTrigger.CHECKIN_TIME_REACHED, now=past_start)
    checkout = await _advance_states(
        session, tenant_id=tenant_id, trigger=PropertyStateTrigger.CHECKOUT_TIME_REACHED, now=past_end
    )
    # Counted off the report and not by looking the row up afterwards: the use case already
    # separates "transitioned" from "transitioned but with no task", so the difference is the
    # number of cleanings its provisioner really created.
    provisioned = checkout.transitioned - checkout.transitioned_without_task
    created["cleaning_tasks"] += provisioned

    # Step 5. Only now: `CHECKOUT_TIME_REACHED` demands a stay that is still `CONFIRMED` or
    # `CHECKED_IN_ESTIMATED`, so closing it any earlier would cost the transition above.
    await _move_reservation(
        session,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        reservation_id=direct.id,
        status=ReservationStatus.COMPLETED,
        now=past_end,
    )

    # Steps 6-8: the cleaning of that checkout, from the cleaner's hands. It has to happen
    # here, between the two stays: the property leaves `CLEANING_SCHEDULED` only when the
    # cleaning closes, and from there no policy admits `CHECKIN_WINDOW_OPENED` — the next
    # arrival would be refused in silence.
    await _run_the_cleaning(
        session,
        tenant_id=tenant_id,
        cleaner=cleaner,
        property_id=redes.id,
        reservation_id=direct.id,
        provisioned=bool(provisioned),
        now=past_end,
        created=created,
        uploaded_keys=uploaded_keys,
    )

    # Steps 9-10: John Smith arrives two days ago and is still in the flat.
    await _advance_states(session, tenant_id=tenant_id, trigger=PropertyStateTrigger.CHECKIN_WINDOW_OPENED, now=live_start)
    await _advance_states(session, tenant_id=tenant_id, trigger=PropertyStateTrigger.CHECKIN_TIME_REACHED, now=live_start)

    # Step 11. `UpdateReservationUseCase` is a **declared substitute** and not the definitive
    # way: `reservations` offers no check-in operation and no closing one — the state machine
    # reads both statuses as a precondition and never writes them — so this is honestly
    # "setting a column with a use case in the middle". Opening those operations is work for
    # `reservations`, and the proposal puts it out of scope.
    await _move_reservation(
        session,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        reservation_id=airbnb.id,
        status=ReservationStatus.CHECKED_IN_ESTIMATED,
        now=live_start,
    )
    # The BOOKING stay (today+3) is deliberately untouched: it is the upcoming one, and its
    # `status` stays exactly where the ingestor left it.

    # Step 12, and last for a reason the sequence test pins: an incident seeded before the
    # stays would put REDES11 in `MAINTENANCE_REQUIRED`, from where no policy admits
    # `CHECKIN_WINDOW_OPENED` — and `_advance_one` swallows that refusal as a warning, so the
    # dataset would reach the same final state with the journey missing.
    await _seed_incidents(
        session,
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        technician=technician,
        properties=properties,
        now=now,
        created=created,
    )


async def _seed_incidents(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    technician: User,
    properties: SqlAlchemyPropertyRepository,
    now: datetime,
    created: dict[str, int],
) -> None:
    """The three incidents of PRD §27, each by its own way in (R1, D2 step 12).

    Created **unclassified** and then put through the classifier, which is the whole point:
    `category`, `severity` and `ai_classification` are its verdict and not values this
    command chose. The alternative — seeding them classified — would be writing by hand the
    columns the demo exists to show being filled in.

    Idempotent on `(property_id, title)` with §27's literal titles (D9): `Incident` has no
    `external_id`, and the pair is the only key of this dataset that does not move with the
    day of the run.

    Incidents 1 and 3 end `CLASSIFIED` rather than the literal `OPEN` of §27, and that is a
    declared divergence: `classify` is the only way out of `OPEN`, and the beat job would
    move an `OPEN` one within five minutes anyway. A dataset that changes on its own is not
    a dataset.
    """
    incidents_repo = SqlAlchemyIncidentRepository(session)
    existing = {
        (incident.property_id, incident.title)
        for incident in await _incidents_of_the_tenant(session, tenant_id)
    }

    report = ReportIncidentUseCase(
        incidents=incidents_repo,
        properties=properties,
        audit=SqlAlchemyAuditLogRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=CallerOwnedUnitOfWork(),
    )
    classify = ClassifyIncidentUseCase(
        classifier=RuleBasedIncidentClassifier(),
        configs=SqlAlchemyTenantConfigRepository(session),
        **_incident_flow_kwargs(session),
    )
    assign = AssignIncidentUseCase(
        users=SqlAlchemyUserRepository(session),
        notifications=SqlAlchemyNotificationLogRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        **_incident_flow_kwargs(session),
    )

    for seeded in SEED_INCIDENTS:
        property = await properties.find_by_internal_code(tenant_id, seeded.internal_code)
        if property is None:  # pragma: no cover - `_seed_properties` has just guaranteed it
            raise SeedPreconditionError(
                f"{seeded.internal_code} was not seeded; cannot place its incident."
            )
        if (property.id, seeded.title) in existing:
            continue

        incident = await report.execute(
            tenant_id=tenant_id,
            property_id=property.id,
            source=seeded.source,
            title=seeded.title,
            description=seeded.description,
            # The owner reports them: §27 names a guest and a cleaner as the *source*, which
            # is the column, and neither has a way in of their own from a command.
            actor=IncidentActor(user_id=actor_user_id, role=UserRole.TENANT_OWNER),
            now=now,
        )
        created["incidents"] += 1

        # `actor=None`, wired as the job wires it: the classification is the classifier's
        # work, and an actor here would put the owner's name on a verdict she did not reach
        # — `_record_timeline` turns the absence into actor `AI`, which is what the demo has
        # to show. Rule 9's fourth exception of `steering/security.md` names this command
        # alongside the job for exactly this row.
        incident = await classify.execute(
            tenant_id=tenant_id, incident_id=incident.id, actor=None, now=now
        )
        if (incident.category, incident.severity) != (seeded.category, seeded.severity):
            # R1.3. The defence against classifier drift: if somebody edits the keywords, the
            # seed stops producing §27's dataset, and a seed that adapts in silence is worse
            # than one that fails. Both values, because "it is not what §27 says" without
            # saying what it is instead sends the reader to the wrong file.
            raise SeedConflictError(
                f"The classifier put {seeded.title!r} in "
                f"{incident.category.value}/{incident.severity.value}, and PRD §27 declares "
                f"{seeded.category.value}/{seeded.severity.value}. The demo dataset is not "
                "what it claims to be; nothing was written."
            )

        if seeded.severity is IncidentSeverity.HIGH:
            # §27 asks for the ACCESS one, and only that one, to be `ASSIGNED` to the
            # technician. Keyed on the severity §27 declares rather than on the position in
            # the tuple, so reordering the constants cannot silently assign another.
            #
            # **The actor's role is not checked here, and that is not an omission**: it is
            # the one `_only_actor` resolved BY ROLE at the top of the run, so a tenant
            # without an owner has already failed loudly by this line. `AssignIncidentUseCase`
            # itself demands nothing of the actor's role — permission for this operation is
            # enforced at the HTTP layer the CLI does not go through — so a check here would
            # be asserting a claim this module is the one making.
            try:
                await assign.execute(
                    tenant_id=tenant_id,
                    incident_id=incident.id,
                    technician_id=technician.id,
                    actor=IncidentActor(user_id=actor_user_id, role=UserRole.TENANT_OWNER),
                    now=now,
                )
            except InvalidTechnicianError as error:
                # The use case checks by itself that the technician exists, is a `TECHNICIAN`
                # and is `ACTIVE`. Caught and named because otherwise this reaches `main()`'s
                # catch-all as "unexpected InvalidTechnicianError; details withheld" and exit
                # 2 — the same opaque failure R6.1 and R3.3 replaced for their conditions.
                # Reached when `SEED_TECHNICIAN_EMAIL` names an account that already existed
                # with another role or deactivated: the seed reuses such an account intact
                # (R3.5) rather than editing it.
                raise SeedPreconditionError(
                    "SEED_TECHNICIAN_EMAIL's account cannot take the incident PRD §27 "
                    "assigns to it: an assignee has to be an ACTIVE user with the TECHNICIAN "
                    "role. The seed leaves an existing account exactly as it is, so this one "
                    "has to be fixed where it lives."
                ) from error


async def _incidents_of_the_tenant(
    session: AsyncSession, tenant_id: uuid.UUID
) -> list[Incident]:
    """Every incident of the tenant, paged, for the `(property_id, title)` idempotency key.

    Through `list` and not a port method of its own, the same call D9 made for the DIRECT
    stay: `IncidentFilters` has no title, and adding one whose only caller would be a demo
    command is the port change that decision already rejected once.
    """
    reader = SqlAlchemyIncidentReader(session)
    found: list[Incident] = []
    page_number = 1
    while True:
        page = await reader.list(
            tenant_id, IncidentFilters(), page=page_number, per_page=_INCIDENT_PAGE
        )
        found.extend(page.items)
        if page_number * _INCIDENT_PAGE >= page.total:
            return found
        page_number += 1


def _incident_flow_kwargs(session: AsyncSession) -> dict:
    """The nine collaborators every incident-flow use case takes, as `maintenance` wires them.

    Same shape `maintenance/api/dependencies.py` builds for its routes, with D11's one
    difference: the unit of work is the caller's, so nothing here commits on its own.
    """
    return {
        "incidents": SqlAlchemyIncidentRepository(session),
        "reader": SqlAlchemyIncidentReader(session),
        "properties": SqlAlchemyPropertyRepository(session),
        "transitions": SqlAlchemyPropertyStateTransitionRepository(session),
        "timeline": SqlAlchemyTimelineEventRepository(session),
        "reservations": SqlAlchemyReservationRepository(session),
        "cleaning_tasks": SqlAlchemyLiveCleaningTaskQuery(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": CallerOwnedUnitOfWork(),
    }


async def _run_the_cleaning(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    cleaner: User,
    property_id: uuid.UUID,
    reservation_id: uuid.UUID,
    provisioned: bool,
    now: datetime,
    created: dict[str, int],
    uploaded_keys: list[str],
) -> None:
    """Steps 6-8 of D2: the cleaning of the past stay, walked from the cleaner's hands.

    **The actor is the cleaner and cannot be anyone else** (D8, R5.2): `accept`, `start`,
    `complete` and every upload call `_require_assignee` on the entity, so the `TENANT_OWNER`
    that signs everything else in this command would be refused. That invariant of `cleaning`
    is what retires the old rule "el actor de todo lo que el seed escribe es el `TENANT_OWNER`"
    — the change does not relax it, the dataset simply grew field work in it.

    **It does not assign the task**, and that is the section-5 panel's amendment to D2's step
    6: the checkout's provisioner already did, because PRD §11 auto-assigns when the tenant
    has exactly one active cleaner and §27's tenant has exactly one. Re-assigning would write
    a second assignment notification and a second audit row on every run for no change at
    all, so what happens here instead is that the assignment is **checked**: an unexpected
    assignee is a dataset nobody can explain, and it fails rather than being written over.

    Idempotent by one question — "is it already `COMPLETED`?" — which covers the task, its 18
    items and its 6 photos at once (D9). That single check is what keeps a second run from
    leaving six orphaned objects in the store: the rows would roll back, the objects would
    not.
    """
    tasks = SqlAlchemyCleaningTaskRepository(session)
    task = next(
        (
            candidate
            for candidate in await tasks.list_for_property(tenant_id, property_id)
            if candidate.reservation_id == reservation_id
        ),
        None,
    )
    if task is None:
        if provisioned:
            # The checkout just created one and it is not there: something between the two
            # is wrong, and this is the case that must not be silent (amended D9, agreed at
            # the section-7 panel after the architect separated it from the ordinary ones).
            raise SeedPreconditionError(
                "The checkout provisioned a cleaning task and it cannot be found. The demo "
                "dataset is not what this command wrote; nothing was committed."
            )
        # And this is the ordinary half, which is quiet on purpose. Two situations reach it
        # and neither is this command's to refuse: a tenant that turned
        # `auto_create_cleaning_task` off or has no checklist template
        # (`ProvisionCleaningTaskUseCase` "returns `None` for every ordinary reason not to
        # create one and lets the caller count it"), and a re-seed over a dataset whose past
        # stay somebody deleted by hand, where the property is no longer in a state the
        # checkout can fire from — so nothing was provisioned this run either. What says it
        # happened is the console: `0 cleaning_tasks, 0 cleaning_photos`.
        return
    if task.status is CleaningTaskStatus.COMPLETED:
        return

    if task.assigned_cleaner_id != cleaner.id:
        # Loud, because every step below would be refused with a 404-shaped
        # `CleaningTaskNotFoundError` — `_require_assignee` answers "not yours" that way on
        # purpose — and a seed that failed with "task not found" over a task it had just
        # created would send whoever reads it looking in the wrong place.
        raise SeedPreconditionError(
            "The demo cleaning is not assigned to SEED_CLEANER_EMAIL's account, so the "
            "cleaner cannot walk it. That assignment is made automatically at checkout when "
            "the tenant has exactly one active cleaner."
        )
    actor = CleaningActor(user_id=cleaner.id, role=UserRole.CLEANER)
    lifecycle = _cleaning_lifecycle_kwargs(session)

    await AcceptCleaningTaskUseCase(
        notifications=SqlAlchemyNotificationLogRepository(session), **lifecycle
    ).execute(tenant_id=tenant_id, task_id=task.id, actor=actor, now=now)
    await StartCleaningTaskUseCase(**lifecycle).execute(
        tenant_id=tenant_id, task_id=task.id, actor=actor, now=now
    )

    complete_item = CompleteChecklistItemUseCase(
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        completions=SqlAlchemyCleaningChecklistCompletionRepository(session),
        **lifecycle,
    )
    for item_id, _ in _CHECKLIST_ITEMS:
        await complete_item.execute(
            tenant_id=tenant_id, task_id=task.id, item_id=item_id, actor=actor, now=now
        )

    upload = UploadCleaningPhotoUseCase(
        tasks=SqlAlchemyCleaningTaskRepository(session),
        templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
        photos=SqlAlchemyCleaningPhotoRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        storage=_file_storage_factory(),
        audit=SqlAlchemyAuditLogRepository(session),
        uow=CallerOwnedUnitOfWork(),
        max_bytes=settings.photo_upload_max_bytes,
    )
    for photo_type, content in SEED_PHOTO_BYTES.items():
        uploaded = await upload.execute(
            tenant_id=tenant_id,
            task_id=task.id,
            photo_type=photo_type,
            upload=BytesUpload(content),
            actor=actor,
            now=now,
        )
        created["cleaning_photos"] += 1
        # Remembered because the object is the one write of this command that a rollback
        # cannot undo (D11): `UploadCleaningPhotoUseCase` deletes it compensatorily only when
        # **its own** `commit()` fails, and under `CallerOwnedUnitOfWork` that commit never
        # happens. A failure after this point takes the six rows and leaves the six objects.
        uploaded_keys.append(uploaded.photo.storage_key)

    # The four reads of the close arrive as one collaborator since
    # `cleaning-completion-evidence-gatherer` (its R1.1): `CompleteCleaningTaskUseCase` no longer
    # takes the four repositories, and the gatherer is not a use case, so it is built inline here
    # exactly as `cleaning/api/dependencies.py` builds it for the route.
    await CompleteCleaningTaskUseCase(
        evidence=CompletionEvidenceGatherer(
            templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
            completions=SqlAlchemyCleaningChecklistCompletionRepository(session),
            photos=SqlAlchemyCleaningPhotoRepository(session),
            incidents=SqlAlchemyBlockingIncidentQuery(session),
        ),
        **lifecycle,
    ).execute(tenant_id=tenant_id, task_id=task.id, actor=actor, now=now)


def _cleaning_lifecycle_kwargs(session: AsyncSession) -> dict:
    """The seven collaborators every task-lifecycle use case takes, as `cleaning` wires them.

    Same helper `cleaning/api/dependencies.py` keeps for its routes, with one difference that
    is the whole of D11: the unit of work is the caller's, so nothing here commits on its own.
    """
    return {
        "tasks": SqlAlchemyCleaningTaskRepository(session),
        "properties": SqlAlchemyPropertyRepository(session),
        "transitions": SqlAlchemyPropertyStateTransitionRepository(session),
        "timeline": SqlAlchemyTimelineEventRepository(session),
        "reservations": SqlAlchemyReservationRepository(session),
        "audit": SqlAlchemyAuditLogRepository(session),
        "uow": CallerOwnedUnitOfWork(),
    }


def _file_storage_factory() -> ConfiguredFileStorageFactory:
    """The tenant-agnostic factory, wired exactly as the HTTP dependency wires it.

    The seed does not choose a backend: the factory answers from the tenant's stored
    `storage_type`, which is why `make seed-demo` writes to the object store in `dev` and to
    the disk locally without a line of difference here.
    """
    return ConfiguredFileStorageFactory(
        signing_key=derive_signing_key(settings.jwt_secret_key),
        s3_bucket=settings.s3_bucket,
        s3_client_factory=partial(
            build_s3_client,
            region_name=settings.s3_region.strip() or None,
            endpoint_url=settings.s3_endpoint_url.strip() or None,
        ),
    )


async def _move_reservation(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reservation_id: uuid.UUID,
    status: ReservationStatus,
    now: datetime,
) -> None:
    """One status, through the only writer there is, with the `TENANT_OWNER` as actor (D8).

    Idempotent for free: `update_details` compares against what is stored and a value that
    did not change writes nothing and records nothing — "the timeline is evidence of change,
    not of requests".
    """
    use_case = UpdateReservationUseCase(
        reservations=SqlAlchemyReservationRepository(session),
        guests=SqlAlchemyGuestRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        uow=CallerOwnedUnitOfWork(),
    )
    await use_case.execute(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        reservation_id=reservation_id,
        changes={"status": status},
        now=now,
    )


async def _advance_states(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    trigger: PropertyStateTrigger,
    now: datetime,
) -> AdvanceReport:
    """One clock trigger, wired exactly as `scheduler/tasks.py::_advance` wires it.

    Actor `SYSTEM`, which is what the use case builds for a clock trigger and what rule 9 of
    `steering/security.md` exempts from `AuditLog`; the provisioner only for the checkout,
    because that is the only trigger that has one (`cleaning` design D1). Copied rather than
    imported because importing `app.scheduler.tasks` would drag Celery into a CLI that has no
    broker; what must not drift is the *wiring*, and that is one function long.
    """
    provisioner = (
        ProvisionCleaningTaskUseCase(
            tasks=SqlAlchemyCleaningTaskRepository(session),
            templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
            configs=SqlAlchemyTenantConfigRepository(session),
            users=SqlAlchemyUserRepository(session),
            transitions=SqlAlchemyPropertyStateTransitionRepository(session),
            timeline=SqlAlchemyTimelineEventRepository(session),
            properties=SqlAlchemyPropertyRepository(session),
            notifications=SqlAlchemyNotificationLogRepository(session),
        )
        if trigger is PropertyStateTrigger.CHECKOUT_TIME_REACHED
        else None
    )
    use_case = AdvancePropertyStatesUseCase(
        properties=SqlAlchemyPropertyRepository(session),
        reservations=SqlAlchemyReservationRepository(session),
        transitions=SqlAlchemyPropertyStateTransitionRepository(session),
        timeline=SqlAlchemyTimelineEventRepository(session),
        configs=SqlAlchemyTenantConfigRepository(session),
        uow=CallerOwnedUnitOfWork(),
        provisioner=provisioner,
    )
    return await use_case.execute(tenant_id=tenant_id, trigger=trigger, now=now)


async def _seed_checklist_template(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    properties: SqlAlchemyPropertyRepository,
    now: datetime,
    created: dict[str, int],
) -> None:
    """The tenant's default checklist, applicable to both homes (R5.1, R5.2).

    No `property_id`, which is how the schema spells "the whole tenant" — §7.10 declares that
    column nullable for exactly this.
    """
    templates = SqlAlchemyCleaningChecklistTemplateRepository(session)
    # "The tenant already has at least one" is the idempotency key (design D9): §27 asks for
    # ONE template per tenant, so a second one is what R5.2 forbids, whatever it is called.
    if (await templates.list(tenant_id, page=1, per_page=1)).total > 0:
        return

    use_case = CreateChecklistTemplateUseCase(
        templates=templates,
        properties=properties,
        uow=CallerOwnedUnitOfWork(),
    )
    await use_case.execute(
        tenant_id=tenant_id,
        command=CreateChecklistTemplateCommand(
            name=_CHECKLIST_NAME,
            items=[
                {"item_id": item_id, "label": label, "required": True}
                for item_id, label in _CHECKLIST_ITEMS
            ],
            required_photos=[
                {"photo_type": photo_type, "label": label, "required": True}
                for photo_type, label in _CHECKLIST_PHOTOS
            ],
        ),
        now=now,
    )
    created["checklist_templates"] += 1


async def _seed_reservations(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    properties: SqlAlchemyPropertyRepository,
    today: date,
    now: datetime,
    created: dict[str, int],
) -> None:
    """The three stays of PRD §27 — one past, one live, one upcoming — dated from today.

    `today` arrives already resolved in the tenant's timezone (see `apply_plan`) rather than
    being taken off `now.date()` here: the two are a different day for part of every night,
    and R4.3's past/live/upcoming composition is about the calendar the demo is watched on.

    Two doors, because the channel decides which one is open (R4.1, R4.2):
    `CreateReservationCommand.__post_init__` refuses any channel outside `MANUAL_CHANNELS`,
    and that refusal is not an obstacle to route around — an OTA channel means the stay came
    from a feed and carries an `external_pms_id`, which is the idempotency key the next sync
    keys on. So the DIRECT one goes through its use case and the two OTA ones through the
    ingestor, which is what assigns that id.

    **No `status` anywhere.** On the DIRECT side that is free: `CreateReservationCommand` has
    no such field. On the OTA side the DTO does have one, and leaving it `None` is the whole
    of R4.4 — this is the exact spot where a careless seed would plant §27's
    `CHECKED_IN_ESTIMATED` by hand instead of letting the state machine and the scheduler of
    `celery-jobs` get there.
    """
    redes = await properties.find_by_internal_code(tenant_id, "REDES11")
    if redes is None:  # pragma: no cover - `_seed_properties` has just guaranteed it
        raise SeedPreconditionError("REDES11 was not seeded; cannot place its reservations.")

    reservations = SqlAlchemyReservationRepository(session)
    guests = SqlAlchemyGuestRepository(session)
    timeline = SqlAlchemyTimelineEventRepository(session)

    await _seed_direct_reservation(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        property_id=redes.id,
        reservations=reservations,
        properties=properties,
        guests=guests,
        timeline=timeline,
        today=today,
        now=now,
        created=created,
    )
    await _seed_ota_reservations(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        reservations=reservations,
        properties=properties,
        guests=guests,
        timeline=timeline,
        today=today,
        now=now,
        created=created,
    )


async def _seed_direct_reservation(
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    property_id: uuid.UUID,
    reservations: SqlAlchemyReservationRepository,
    properties: SqlAlchemyPropertyRepository,
    guests: SqlAlchemyGuestRepository,
    timeline: SqlAlchemyTimelineEventRepository,
    today: date,
    now: datetime,
    created: dict[str, int],
) -> None:
    """Pedro López, today−10 → today−7, the past stay the demo uses to show history (R4.1).

    Its guest is created first, by the entity and its port: R4.5 asks for the guest to be
    registered "by the same way that creates the reservation", and that way does not create
    guests — `CreateReservationUseCase` only checks that a `guest_id` exists (design D8). One
    step below the use case, never in the model, exactly as D3 resolves the same asymmetry
    for users. `add` flushes, and the single commit of `apply_plan` closes both writes, so a
    reservation that failed would take its guest with it rather than leave an orphan.
    """
    if (
        await _reservation_by_channel_id(
            reservations, tenant_id, property_id, DIRECT_CHANNEL_ID
        )
        is not None
    ):
        return

    guest = Guest(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        full_name="Pedro López",
        created_at=now,
        updated_at=now,
        # §27 gives no address for this one, and inventing one would be dataset drift.
        email=None,
    )
    await guests.add(tenant_id, guest)
    created["guests"] += 1

    use_case = CreateReservationUseCase(
        reservations=reservations,
        properties=properties,
        guests=guests,
        timeline=timeline,
        uow=CallerOwnedUnitOfWork(),
    )
    await use_case.execute(
        tenant_id=tenant_id,
        actor_user_id=actor_user_id,
        command=CreateReservationCommand(
            property_id=property_id,
            # DIRECT is in `MANUAL_CHANNELS`, which is why this stay can come through here
            # and the other two cannot.
            channel=ReservationChannel.DIRECT,
            check_in_date=today - timedelta(days=10),
            check_out_date=today - timedelta(days=7),
            guest_id=guest.id,
            external_channel_id=DIRECT_CHANNEL_ID,
        ),
        now=now,
    )
    created["reservations"] += 1


async def _reservation_by_channel_id(
    reservations: SqlAlchemyReservationRepository,
    tenant_id: uuid.UUID,
    property_id: uuid.UUID,
    external_channel_id: str,
) -> Reservation | None:
    """The DIRECT stay, found by an id that does not move with the calendar.

    Not by property + dates, which is R4.6's letter: those dates are relative to the day of
    the run, so that key would match a fresh duplicate every day (design D9). And through
    `list` rather than a new `find_by_external_channel_id` on the port — D9 rejected adding a
    port method whose only caller would be a demo command.

    Returns the reservation rather than a boolean, because the advance phase needs the row
    itself and asking twice for the same page would be two answers to one question.
    """
    page_number = 1
    while True:
        page = await reservations.list(
            tenant_id,
            ReservationFilters(property_id=property_id),
            page=page_number,
            per_page=_RESERVATION_PAGE,
        )
        for item in page.items:
            if item.external_channel_id == external_channel_id:
                return item
        if page_number * _RESERVATION_PAGE >= page.total:
            return None
        page_number += 1


async def _seed_ota_reservations(
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    reservations: SqlAlchemyReservationRepository,
    properties: SqlAlchemyPropertyRepository,
    guests: SqlAlchemyGuestRepository,
    timeline: SqlAlchemyTimelineEventRepository,
    today: date,
    now: datetime,
    created: dict[str, int],
) -> None:
    """The AIRBNB and BOOKING stays, through `ReservationIngestor` (R4.2, R4.5, design D7).

    Three of the DTO's names do not match the columns they end up in, and each has bitten
    somebody: the stable identifier goes in `external_id` (the ingestor persists it as
    `external_pms_id`), the property is named in `property_external_id` — an internal code
    here, because that is what this resolver reads — and there is **no `net_amount` field**:
    §27's €297.50 is gross minus commission, derived by `net_amount_from`.

    **The seed checks the keys itself and does not hand the ingestor rows that already
    exist.** The ingestor's idempotency is to UPDATE what it knows, so delegating it would
    move the dates of an environment seeded two weeks ago — precisely what R1.2 forbids
    (design D9).
    """
    rows = [
        IngestRow(dto=dto)
        for dto in _ota_reservation_dtos(today)
        if await reservations.find_by_external_pms_id(tenant_id, dto.external_id) is None
    ]
    if not rows:
        return
    # Counted BEFORE the ingest and through the port, not inferred from `report.created`:
    # `_link_guest` reuses a guest that matches by email, so "one guest per new reservation"
    # is true of today's dataset and not of the operation. A count that guesses is a count
    # that will be wrong the first time somebody adds a stay for a returning guest.
    # An explicit loop and not a `sum(... for ...)`: a generator expression containing
    # `await` is an ASYNC generator, which `sum` cannot consume.
    new_guests = 0
    for row in rows:
        email = row.dto.guest_email
        if email and await guests.find_by_email(tenant_id, email) is None:
            new_guests += 1

    async def resolve(row: ReservationDTO) -> Property | None:
        # The same resolver `ImportReservationsFromCsvUseCase` uses. `resolve_property` is a
        # parameter precisely because "how a property is resolved is the ONLY difference
        # between the three routes" — and this is the third one the ingestor now enumerates.
        return await properties.find_by_internal_code(tenant_id, row.property_external_id)

    ingestor = ReservationIngestor(
        reservations=reservations, guests=guests, timeline=timeline
    )
    report = await ingestor.ingest(
        tenant_id=tenant_id,
        rows=rows,
        resolve_property=resolve,
        now=now,
        actor_type=TimelineActorType.USER,
        actor_user_id=actor_user_id,
        source=SEED_SOURCE,
    )
    if report.skipped or report.errors:
        # Loud, because `ingest` is built to survive a bad row and carry on — right for a
        # file a person uploaded, wrong for a dataset this module wrote itself. Silence here
        # would print counts claiming a seed that did not happen.
        # `skipped` can be non-zero with no `RowError` behind it (`ingest.py`: "known and
        # unchanged"), and joining an empty `errors` produced a refusal that ended in a colon
        # and said nothing. Unreachable while the pre-filter above holds — a row the ingestor
        # already knows never gets handed to it — but a loud failure that reports no reason is
        # the one shape this exception exists to prevent, so it states the counts instead.
        detail = "; ".join(error.reason for error in report.errors) or (
            f"no row was rejected, but {report.skipped} were skipped and "
            f"{report.updated} updated, so the dataset is not what this command wrote"
        )
        raise SeedIngestError("The demo reservations could not be ingested: " + detail)
    created["reservations"] += report.created
    # `_link_guest` registers John Smith and María García on the way through (R4.5).
    created["guests"] += new_guests


async def _seed_properties(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    properties: SqlAlchemyPropertyRepository,
    now: datetime,
    created: dict[str, int],
) -> None:
    """REDES11 and PAJARITOS8, through `CreatePropertyUseCase` (R2.1, R2.4).

    Neither command carries `current_operational_state`, and that is not restraint on the
    seed's part — `CreatePropertyCommand` has no such field, on purpose, so both homes take
    the DDL default `VACANT_READY` and the column stays where `PropertyStateMachine` governs
    it (R2.2).

    The use case is handed a `CallerOwnedUnitOfWork`: `apply_plan` owns the transaction, and
    a real one here would commit each property independently, which is the failure mode that
    class was written for.
    """
    use_case = CreatePropertyUseCase(
        properties=properties,
        audit=SqlAlchemyAuditLogRepository(session),
        uow=CallerOwnedUnitOfWork(),
    )
    for command in SEED_PROPERTIES:
        # Idempotency keys on `internal_code`, which does not move with the calendar the way
        # a reservation's dates do (design D9).
        if await properties.find_by_internal_code(tenant_id, command.internal_code) is not None:
            continue
        await use_case.execute(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            # No IP: this is a command, not a request. `CreatePropertyUseCase` takes it as
            # optional precisely because not every caller has one.
            actor_ip=None,
            command=command,
            now=now,
        )
        created["properties"] += 1


async def _seed_accounts(
    session: AsyncSession,
    *,
    plan: SeedPlan,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID,
    hasher: BcryptPasswordHasher,
    users: SqlAlchemyUserRepository,
    known: dict[str, User | None],
    now: datetime,
    created: dict[str, int],
) -> dict[str, User]:
    """The CLEANER and the TECHNICIAN, with passwords their owners can actually use (R3.4).

    **Returns them, whether it created them or found them.** The advance phase needs the
    cleaner as an actor, and the alternative — looking the address up again later — would run
    `find_by_email_globally` on a session `bind_session_to_tenant` has already marked, which
    contradicts the invariant that method documents for itself ("this lookup must run on a
    session that is NOT marked with a tenant") and quietly adds a caller to the audited list
    of unscoped lookups. Raised by the section-6 tenancy panel.

    `User.create` + the port, never `CreateUserUseCase`: that one generates the password and
    therefore marks `must_change_password`, which is what R3.4 rules out — a demo that asks
    for four password rotations before the first click is not a demo (design D3). What is
    incompatible with R3.4 is the use case, not the domain: `must_change_password` defaults to
    `False` on the entity precisely so the paths whose passwords a person chooses keep working.

    Through the port and not `session.add(UserModel(...))`, which is what keeps the three
    guards a raw insert skips: `GRANTABLE_ROLES`, `CrossTenantWriteError`, and the translation
    of `uq_users_lower_email` into `EmailAlreadyExistsError`.
    """
    audit = SqlAlchemyAuditLogRepository(session)
    resolved: dict[str, User] = {}
    for account in plan.accounts:
        # One global lookup, taken before the session was marked, answered both questions
        # for the reason `bootstrap.apply_plan` spells out: a normalised email is unique
        # across the whole installation, so an address that already exists is either ours (a
        # re-run) or a neighbour's. The neighbour case cannot reach this loop —
        # `_refuse_addresses_owned_by_another_tenant` judged both addresses before the first
        # write — so what is left here is only "ours, leave it alone".
        existing = known[account.email]
        if existing is not None:
            # Left completely intact, password included (R3.5).
            resolved[account.email] = existing
            continue

        user = User.create(
            tenant_id=tenant_id,
            name=account.name,
            email=account.email,
            password_hash=await hasher.hash(account.password),
            role=account.role,
            now=now,
            must_change_password=False,
        )
        await users.add(tenant_id, user)
        await audit.add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=actions.USER_CREATED,
                entity_type=actions.ENTITY_USER,
                entity_id=user.id,
                actor_user_id=actor_user_id,
                actor_ip=None,
                changes=(
                    ChangeSet(actions.ENTITY_USER)
                    .diff("email", None, user.email)
                    .diff("role", None, user.role)
                    # `.redacted()` and not `.diff()`: `password` is in `REDACTED_FIELDS`, and
                    # `diff()` refuses it outright.
                    .redacted("password")
                ),
                now=now,
            ),
        )
        created["users"] += 1
        resolved[account.email] = user
    return resolved


async def run() -> dict[str, int]:
    plan = build_plan()
    hasher = BcryptPasswordHasher(rounds=settings.bcrypt_rounds)
    async with async_session_factory() as session:
        return await apply_plan(session, plan, hasher)


def main() -> int:
    try:
        created = asyncio.run(run())
    except SeedConfigurationError as exc:
        print(f"seed-demo: {exc}", file=sys.stderr)
        return 1
    except SeedPreconditionError as exc:
        print(f"seed-demo: {exc}", file=sys.stderr)
        return 1
    except SeedConflictError as exc:
        print(f"seed-demo: refusing to continue — {exc}", file=sys.stderr)
        return 1
    except SeedIngestError as exc:
        # Handled ahead of the catch-all so the REASONS survive: this is the one unexpected
        # failure whose detail a person can act on, and every reason `ReservationIngestor`
        # produces is a field name or a fixed sentence — never a guest, an amount or a hash.
        print(f"seed-demo: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        # The CLASS of the failure and nothing else, and this is a security boundary rather
        # than tidiness (R1.4). SQLAlchemy's `StatementError.__str__` appends
        # `[SQL: INSERT INTO users ...] [parameters: (...)]`, and those parameters are this
        # command's inputs: a bcrypt hash, a name, an address. Anything that reaches the
        # flush unexpectedly — an over-long `SEED_*_NAME` against `String(200)`, a
        # constraint nobody anticipated — would otherwise print them to stderr and into
        # whatever captures it. Same posture `ConfigurationError` takes in
        # `app/core/config.py`, and for the same measured reason.
        #
        # Exit 2 and not 1: the four conditions of exit 1 are checked refusals, and a
        # runbook has to be able to tell "this environment is not ready" from "this
        # command broke". Extends the table of design D11.
        print(
            f"seed-demo: unexpected {type(exc).__name__}; details withheld because they "
            "would carry the command's inputs. Re-run with the stack's logs if you need "
            "the statement.",
            file=sys.stderr,
        )
        return 2
    # Counts and nothing else: never a password, a hash or a token (R1.4). Every entity type
    # is printed even at zero, because "created 0 users, 0 properties…" is what tells an
    # operator a second run did nothing — a line that silently omitted the zeros would be
    # indistinguishable from a run that only did part of the work.
    print(
        "seed-demo: created "
        + ", ".join(f"{count} {entity}" for entity, count in created.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
