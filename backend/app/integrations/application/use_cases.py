"""Ingest use cases: PMS sync and CSV import (R3, R4, design D9, D10, D11).

Both are one business operation and one transaction: they build the rows, hand them to
`ReservationIngestor`, and commit once at the end (design D4). A per-row commit would leave a
half-imported file behind on the first infrastructure failure, and the report would then
describe a state nobody can reconstruct.
"""

import uuid
from datetime import datetime

from app.core.crypto import SecretDecryptionError
from app.core.unit_of_work import UnitOfWork
from app.guests.domain.repositories import GuestRepository
from app.integrations.application.ingest import (
    IngestReport,
    IngestRow,
    ReservationIngestor,
    RowError,
)
from app.integrations.domain.dtos import ReservationDTO
from app.audit.domain.actions import ENTITY_PMS_CREDENTIAL, PMS_CREDENTIAL_READ
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.integrations.domain.entities import CredentialReadLog
from app.integrations.domain.errors import MissingPmsCredentialError, PmsUnavailableError
from app.integrations.domain.enums import (
    PMSProvider,
    PmsCredentialScope,
    credential_scope_for,
)
from app.integrations.domain.ports import PMSAdapterFactory, ReservationCsvParser
from app.properties.domain.exceptions import AmbiguousPropertyExternalIdError
from app.properties.domain.entities import Property
from app.properties.domain.repositories import PropertyRepository
from app.reservations.domain.repositories import ReservationRepository
from app.timeline.domain.enums import TimelineActorType
from app.timeline.domain.repositories import TimelineEventRepository

PMS_SOURCE = "pms"
CSV_SOURCE = "csv"


class SyncReservationsFromPmsUseCase:
    """Pull reservations from the PMS into this tenant (R3).

    The actor of the timeline events is `SYSTEM`: a command or, later, Celery beat runs this,
    and there is no person to attribute it to (design D15).
    """

    def __init__(
        self,
        *,
        factory: PMSAdapterFactory,
        reservations: ReservationRepository,
        properties: PropertyRepository,
        guests: GuestRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
        audit: AuditLogRepository,
    ) -> None:
        # A FACTORY, not an adapter. ADR 0006 decision 7 is explicit that use cases must never
        # receive an adapter injected as a singleton, because that is precisely what makes
        # per-property resolution a retrofit across every one of them later.
        self._factory = factory
        self._properties = properties
        self._ingestor = ReservationIngestor(
            reservations=reservations, guests=guests, timeline=timeline
        )
        self._uow = uow
        # REQUIRED, not optional. It defaulted to `None` and `_record_credential_reads` returned
        # silently without it, so a future caller — the Celery job the docstrings promise — would
        # have decrypted credentials on every cycle with no audit row and no error. R4.2 says
        # SHALL; expressing that as a default argument makes it a suggestion, and the security
        # panel of sections 6-8 pointed out no test could ever notice the downgrade.
        self._audit = audit


    async def execute(
        self, *, tenant_id: uuid.UUID, since: datetime, now: datetime
    ) -> IngestReport:
        """One call to the PMS **per provider**, not per tenant and not per property.

        Per tenant is what this used to do, and it presupposes a single adapter per run — the
        assumption R2.2 retires. Per property would be the easy replacement and is the one that
        cannot be afforded: the measured Beds24 budget is 100 credits per 300 s **per account**
        and a sync cycle costs 8, so a dozen properties exhaust a five-minute window in one pass
        (`specs/pms-beds24-spike.md`), and the provider explicitly discourages real-time polling.

        Grouping scales with the number of DISTINCT providers a tenant has configured — two or
        three, bounded by definition — and since every evaluated provider authenticates with an
        account-scoped credential, "one call per provider" is "one call per account", which is
        the shape the spike measured and validated.
        """
        properties = await self._properties.list_all(tenant_id)
        report = IngestReport()
        # LOCAL to the run, never shared with the factory or across calls. See the constructor.
        read_log = CredentialReadLog()

        try:
            for provider, group in _group_by_provider(self._factory, properties).items():
                await self._sync_one_provider(
                    tenant_id=tenant_id,
                    provider=provider,
                    group=group,
                    since=since,
                    now=now,
                    report=report,
                    read_log=read_log,
                )
        finally:
            # These rows are added to the SAME unit of work as the ingest, so what they really
            # guarantee is bounded and worth stating exactly: **every failure a provider can
            # cause is caught in `_sync_one_provider`**, so the run always reaches the commit
            # below and the read is recorded. That now includes `SecretDecryptionError` — a
            # tampered ciphertext or a rotated key — which used to escape and take the pending
            # audit row down with the transaction. The feature-scale panel measured it: one row
            # pending, zero persisted, on precisely the case the trail exists for.
            #
            # What it does NOT survive is an exception raised OUTSIDE `_sync_one_provider`'s
            # try — and one of those is anticipated, not hypothetical:
            # `AmbiguousPropertyExternalIdError`, which `_index_by_external_id` raises below
            # AFTER a credential has been decrypted and recorded. Two properties of one provider
            # group sharing a `pms_external_id` is a real data condition (the index is not a
            # constraint), unreachable today only because BEDS24 still fails at the adapter
            # first, and reachable the day `pms-beds24-adapter` lands.
            #
            # An earlier version of this comment said "whatever the run does afterwards", and the
            # version after it said "an exception nobody anticipated" — both wider than the truth,
            # the second and third time in this change that fixing the audit came with an
            # overstated guarantee. Making it unconditional needs a transaction of its own, and
            # the architecture panel argued against that: an independently committed audit row can
            # outlive an ingest that rolls back, so `audit_logs` would assert a read the run's own
            # data denies — two sources of truth, which is the shape D6 rejects elsewhere.
            await self._record_credential_reads(
                tenant_id=tenant_id, now=now, read_log=read_log
            )

        await self._uow.commit()
        return report

    async def _sync_one_provider(
        self,
        *,
        tenant_id: uuid.UUID,
        provider: PMSProvider,
        group: list[Property],
        since: datetime,
        now: datetime,
        report: IngestReport,
        read_log: CredentialReadLog,
    ) -> None:
        """One provider's slice of the run. A failure here does NOT abort the others.

        Same reasoning `specs/celery-jobs.md` already fixed for tenants: one tenant failing must
        not stop the rest. A tenant mid-migration has properties on two providers, and one
        provider being unreachable — or having no adapter yet, which is Beds24's situation
        today — must not cost them the sync of the other.
        """
        # The premise the whole grouping decision rests on, asserted instead of assumed. One
        # adapter serves the group, built from ONE property's credential — which is only sound
        # while the provider authenticates per ACCOUNT, as every provider evaluated does. The day
        # one needs a per-property credential, grouping would silently fetch the whole group with
        # the first property's key. The security panel of sections 6-8 flagged it as latent; this
        # makes it loud instead.
        if credential_scope_for(provider) is PmsCredentialScope.PROPERTY:
            report.errors.append(
                RowError(
                    reason=(
                        f"provider {provider.value} uses per-property credentials, which the "
                        f"grouped sync cannot serve — see BLOCKED.md in pms-provider-resolution"
                    ),
                    reference=provider.value,
                )
            )
            report.provider_failures.append(provider.value)
            return

        try:
            adapter = await self._factory.reservations_for(group[0], read_log=read_log)
            fetched = await adapter.list_reservations(since)
        except (
            PmsUnavailableError,
            MissingPmsCredentialError,
            SecretDecryptionError,
        ) as error:
            # Reported, not raised: the run continues with the other providers and the operator
            # sees which one failed. The message carries the provider and the error class only —
            # `MissingPmsCredentialError` composes its own text from identifiers, and
            # `PmsUnavailableError` from the adapter's vocabulary, never a provider payload.
            report.errors.append(
                RowError(
                    reason=f"provider {provider.value} could not be synced: {error}",
                    reference=provider.value,
                )
            )
            # The channel that keeps the command's exit code honest. Reporting the failure and
            # exiting 0 would be indistinguishable from an empty PMS, which is what D9 forbids.
            report.provider_failures.append(provider.value)
            return

        # Matching is restricted to THIS group. Resolving over the whole tenant would let a
        # provider's reservation attach to a property served by a different provider that happens
        # to share an external id — ids are unique only WITHIN a provider, and
        # `ix_properties_tenant_id_pms_external_id` is an index, not a constraint.
        index = _index_by_external_id(group)

        async def resolve(row: ReservationDTO) -> Property | None:
            return index.get(row.property_external_id.strip())

        _merge(
            report,
            await self._ingestor.ingest(
                tenant_id=tenant_id,
                rows=[IngestRow(dto=row) for row in fetched.reservations],
                resolve_property=resolve,
                now=now,
                actor_type=TimelineActorType.SYSTEM,
                actor_user_id=None,
                source=PMS_SOURCE,
            ),
        )

        # Elements the adapter could not map are folded in HERE, not in the CLI (design D10),
        # matching what `ImportReservationsFromCsvUseCase` has always done with
        # `ParseResult.failures`. The identifier travels in `reference`, its own field, so
        # bounding `reason` to a closed vocabulary cannot destroy it.
        for failure in fetched.failures:
            report.skipped += 1
            report.errors.append(
                RowError(
                    reason=f"provider row could not be mapped: {failure.reason}",
                    reference=failure.external_id,
                )
            )

    async def _record_credential_reads(
        self, *, tenant_id: uuid.UUID, now: datetime, read_log: CredentialReadLog
    ) -> None:
        """One `PMS_CREDENTIAL_READ` row per DISTINCT credential this run decrypted (R4.2).

        Not one per property, which is the narrowing the named exception in rule 9 of
        `steering/security.md` authorises. The two coincide today — every evaluated provider
        authenticates per account, so a run over any portfolio decrypts one credential — and they
        only diverge if a provider ever needs per-property credentials.

        The diff is EMPTY: a read changes nothing, and an empty `ChangeSet` is falsy, so
        `AuditLogFactory` stores `changes` as SQL NULL rather than `{}`. `entity_id` names the
        credential row, which is the mechanical reason the credentials are a table and not
        columns on `properties` — an account credential spread across property columns would
        have no id of its own to point at.
        """
        for credential_id in sorted(read_log.credential_ids):
            await self._audit.add(
                tenant_id,
                AuditLogFactory.build(
                    tenant_id=tenant_id,
                    action=PMS_CREDENTIAL_READ,
                    entity_type=ENTITY_PMS_CREDENTIAL,
                    entity_id=credential_id,
                    actor_user_id=None,
                    actor_ip=None,
                    changes=ChangeSet(ENTITY_PMS_CREDENTIAL),
                    now=now,
                ),
            )


def _group_by_provider(
    factory: PMSAdapterFactory, properties: list[Property]
) -> dict[PMSProvider, list[Property]]:
    """Portfolio → {provider: its properties}, preserving `list_all`'s deterministic order.

    Grouping goes through `factory.provider_for` and NOT through `property.pms_provider`, so the
    operator override of `pms_sync --provider` is honoured here exactly as it is when the adapter
    is resolved. Reading the column directly would group a property under Beds24 and then talk to
    the mock — a disagreement with no symptom.
    """
    groups: dict[PMSProvider, list[Property]] = {}
    for property in properties:
        groups.setdefault(factory.provider_for(property), []).append(property)
    return groups


def _index_by_external_id(group: list[Property]) -> dict[str, Property]:
    """`pms_external_id` → property, within one provider's group.

    Raises `AmbiguousPropertyExternalIdError` on a duplicate, preserving what
    `find_by_pms_external_id` guarantees and for the same reason: two flats sharing an external
    id means adjudicating a booking — and a guest — to the wrong home, so it refuses instead of
    picking. Properties without an external id are simply not indexed; nothing can resolve to
    them, which is correct.
    """
    index: dict[str, Property] = {}
    for property in group:
        external_id = (property.pms_external_id or "").strip()
        if not external_id:
            continue
        if external_id in index:
            raise AmbiguousPropertyExternalIdError(
                tenant_id=property.tenant_id, pms_external_id=external_id
            )
        index[external_id] = property
    return index


def _merge(target: IngestReport, addition: IngestReport) -> None:
    """Accumulate one provider group's outcome into the run's report.

    `+=` on every counter, never assignment: each group contributes, and a run over three
    providers reports the sum rather than whichever happened to go last.
    """
    target.created += addition.created
    target.updated += addition.updated
    target.skipped += addition.skipped
    target.errors.extend(addition.errors)


class ImportReservationsFromCsvUseCase:
    """Import reservations from an uploaded CSV (R4).

    The actor is `USER` with the uploader's id: unlike the sync, there IS a person behind
    this, and the timeline has to be able to answer who imported what (design D15).
    """

    def __init__(
        self,
        *,
        parser: ReservationCsvParser,
        reservations: ReservationRepository,
        properties: PropertyRepository,
        guests: GuestRepository,
        timeline: TimelineEventRepository,
        uow: UnitOfWork,
        max_rows: int,
    ) -> None:
        self._parser = parser
        self._properties = properties
        self._ingestor = ReservationIngestor(
            reservations=reservations, guests=guests, timeline=timeline
        )
        self._uow = uow
        self._max_rows = max_rows

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        raw: bytes,
        now: datetime,
    ) -> IngestReport:
        # Parsing lives behind the port, so the file format is an adapter detail and the
        # router only has to hand over bytes (design D1's dependency rule).
        parsed = self._parser.parse(raw, max_rows=self._max_rows)

        async def resolve(row: ReservationDTO) -> Property | None:
            # By `internal_code` (REDES11), because a person fills in this file and does not
            # know UUIDs (design D11). It is also why a CSV can never name a property of
            # another tenant: the lookup is scoped.
            return await self._properties.find_by_internal_code(
                tenant_id, row.property_external_id
            )

        report = await self._ingestor.ingest(
            tenant_id=tenant_id,
            rows=[IngestRow(dto=row.reservation, line=row.line) for row in parsed.rows],
            resolve_property=resolve,
            now=now,
            actor_type=TimelineActorType.USER,
            actor_user_id=actor_user_id,
            source=CSV_SOURCE,
        )
        # The rows the file itself could not yield are part of the same report: to the person
        # who uploaded the CSV, "line 7 is not a date" and "line 9 names no property" are the
        # same kind of answer (R4.1, R4.2).
        for failure in parsed.failures:
            report.skipped += 1
            report.errors.append(RowError(reason=failure.reason, line=failure.line))
        report.errors.sort(key=lambda error: (error.line is None, error.line or 0))
        await self._uow.commit()
        return report
