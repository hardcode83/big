"""Ingest use cases: PMS sync and CSV import (R3, R4, design D9, D10, D11), plus the
provisioning and rotation of webhook endpoints (`reservations-webhooks` R2).

Both ingest paths are one business operation and one transaction: they build the rows, hand them
to `ReservationIngestor`, and commit once at the end (design D4). A per-row commit would leave a
half-imported file behind on the first infrastructure failure, and the report would then
describe a state nobody can reconstruct.
"""

import dataclasses
import uuid
from dataclasses import dataclass
from datetime import datetime

from app.core import crypto
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
from app.audit.domain.actions import (
    ENTITY_PMS_CREDENTIAL,
    ENTITY_WEBHOOK_ENDPOINT,
    PMS_CREDENTIAL_READ,
    WEBHOOK_ENDPOINT_CREATED,
    WEBHOOK_ENDPOINT_ROTATED,
)
from app.audit.domain.repositories import AuditLogRepository
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.integrations.domain.entities import CredentialReadLog, WebhookEndpoint
from app.integrations.domain.errors import (
    MissingPmsCredentialError,
    PmsUnavailableError,
    WebhookEndpointAlreadyExistsError,
    WebhookEndpointNotFoundError,
)
from app.integrations.domain.enums import (
    PMSProvider,
    PmsCredentialScope,
    credential_scope_for,
)
from app.integrations.domain.ports import PMSAdapterFactory, ReservationCsvParser
from app.integrations.domain.repositories import WebhookEndpointRepository
from app.integrations.domain.webhook_auth import (
    generate_header_secret,
    generate_webhook_token,
    hash_webhook_token,
)
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
        cannot be afforded: Beds24's quota is 100 credits per 300 s **per account**, so a dozen
        properties exhaust a five-minute window in one pass, and the provider explicitly
        discourages real-time polling.

        **The per-cycle cost is deliberately not written here.** It lives in
        `docs/beds24-spike.md`, generated from the committed measurement record. This docstring
        said "8" and went stale when the measurement moved to 10; it was the eighth copy of a
        number with one home, found by the feature-scale QA panel after two sweeps had already
        missed it. The quota above is the provider's and does not move.

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
        """Record this run's credential reads (R4.2).

        **How many rows** is the narrowing that the named exception in rule 9 of
        `steering/security.md` authorises, and **that rule is where it is stated** — this
        docstring cites it and says nothing about it — **including this summary line**, which
        stated the count while the paragraph under it denied stating it. Two earlier versions got
        this wrong: one added a gloss that was backwards (claiming the granularities coincide under
        account scope, which is where they diverge most), and one kept the number in the summary
        after the gloss was deleted. Both survived a sweep, because both sweeps matched phrases
        instead of the claim.

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


@dataclass(frozen=True)
class WebhookEndpointMaterial:
    """The two cleartext secrets, handed back **exactly once** (R2.3, rule 3(a)'s exception).

    This is the only type in the system that carries either value in cleartext, and it exists
    only between the use case and the HTTP response of the call that generated it. Nothing
    persists it: the token is stored as a digest and the header secret as Fernet ciphertext, so
    after this object is discarded there is no path back to either — which is what makes "losing
    the URL is repaired by rotating, not by asking" a property of the system and not a policy
    somebody has to enforce (design D3).

    It carries no `__repr__` guard, unlike `EncryptedSecret`, and that is deliberate rather than
    an omission: redacting the repr of the object whose entire purpose is to be rendered into a
    response would be theatre. The protection here is the object's *lifetime*, not its printing.
    """

    endpoint_id: uuid.UUID
    provider: PMSProvider
    header_name: str
    webhook_token: str
    header_secret: str


class _WebhookEndpointAuditWriter:
    """Builds the audit row for the two endpoint operations, so neither builds one by hand.

    Same shape as `properties/application/property_admin.py`'s writer and, like it, private to
    this module rather than hoisted: `AuditLogFactory` is already the shared piece.
    """

    def __init__(self, audit: AuditLogRepository) -> None:
        self._audit = audit

    async def record(
        self,
        *,
        tenant_id: uuid.UUID,
        action: str,
        endpoint: WebhookEndpoint,
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
                entity_type=ENTITY_WEBHOOK_ENDPOINT,
                entity_id=endpoint.id,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                changes=changes,
                now=now,
            ),
        )


def _material_changes(header_name: str | None) -> ChangeSet:
    """What an endpoint's audit row records: that both secrets moved, and nothing of either.

    `redacted()` and never `diff()` — and here that is enforced rather than remembered:
    `token_hash` and `header_secret_encrypted` are both on `REDACTED_FIELDS`, so `diff()` on
    either raises `AuditContractError`. Recording that they changed is all rule 11 permits and
    all a rotation needs.

    `header_name` is the exception and is diffed with its value, because it is not a secret: it
    is the name of the provider's own header, and an operator changing it is an operational fact
    worth being able to read out of `audit_logs`. `None` means this operation did not touch it,
    which is the rotation case.
    """
    changes = (
        ChangeSet(ENTITY_WEBHOOK_ENDPOINT)
        .redacted("token_hash")
        .redacted("header_secret_encrypted")
    )
    if header_name is None:
        return changes
    return changes.diff("header_name", None, header_name)


class CreateWebhookEndpointUseCase:
    """Mint this tenant's webhook authentication material for one provider (R2.1-R2.5).

    Both secrets are generated here — never derived from the tenant, never a constant shared
    across tenants (R2.1, rule 12(a)/(b)) — and both leave in `WebhookEndpointMaterial` and in
    the stored row, in incomparable forms: a SHA-256 digest and Fernet ciphertext.

    Refuses when the tenant already has an endpoint for this provider. See
    `WebhookEndpointAlreadyExistsError` for why that is not merely tidier than overwriting.
    """

    def __init__(
        self,
        *,
        endpoints: WebhookEndpointRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._endpoints = endpoints
        self._audit = _WebhookEndpointAuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        provider: PMSProvider,
        header_name: str,
        now: datetime,
    ) -> WebhookEndpointMaterial:
        if await self._endpoints.find_for(tenant_id, provider) is not None:
            raise WebhookEndpointAlreadyExistsError(
                f"tenant already has a webhook endpoint for {provider.value}; "
                f"rotate it instead of creating a second one"
            )

        token = generate_webhook_token()
        secret = generate_header_secret()
        endpoint = WebhookEndpoint(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            provider=provider,
            token_hash=hash_webhook_token(token),
            header_name=header_name.strip(),
            header_secret=crypto.encrypt(secret),
        )

        await self._endpoints.upsert(tenant_id, endpoint)
        await self._audit.record(
            tenant_id=tenant_id,
            action=WEBHOOK_ENDPOINT_CREATED,
            endpoint=endpoint,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=_material_changes(endpoint.header_name),
            now=now,
        )
        await self._uow.commit()

        return WebhookEndpointMaterial(
            endpoint_id=endpoint.id,
            provider=endpoint.provider,
            header_name=endpoint.header_name,
            webhook_token=token,
            header_secret=secret,
        )


class RotateWebhookEndpointUseCase:
    """Replace both secrets of an existing endpoint, in one transaction (R2.4, design D3).

    No grace window and no second valid value: `upsert` overwrites the single row, so the old
    token and the old header secret stop authenticating the moment this commits. That has a real
    operational cost — the provider keeps posting to the dead route until somebody updates its
    panel, and those notices are lost — which is why this is a deliberate act by a person with
    RBAC and never automatic, and why the recovery is the `pms_sync` poll that still exists.

    `header_name` is deliberately NOT rotatable here: it is the provider's own header name, not
    material, and changing it is a different operation from replacing a leaked secret. Bundling
    them would mean a rotation could silently break authentication in a way that looks like a
    successful rotation.
    """

    def __init__(
        self,
        *,
        endpoints: WebhookEndpointRepository,
        audit: AuditLogRepository,
        uow: UnitOfWork,
    ) -> None:
        self._endpoints = endpoints
        self._audit = _WebhookEndpointAuditWriter(audit)
        self._uow = uow

    async def execute(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        actor_ip: str | None,
        endpoint_id: uuid.UUID,
        now: datetime,
    ) -> WebhookEndpointMaterial:
        existing = await self._endpoints.get(tenant_id, endpoint_id)
        if existing is None:
            # Also the answer for an endpoint of another tenant: `get` is scoped, so both arrive
            # here as `None` and leave as one indistinguishable 404.
            raise WebhookEndpointNotFoundError(f"no webhook endpoint {endpoint_id}")

        token = generate_webhook_token()
        secret = generate_header_secret()
        # `replace` rather than mutation: the entity is frozen precisely so that no half-rotated
        # aggregate — new token, old secret — can exist for anything to observe (design D3).
        rotated = dataclasses.replace(
            existing,
            token_hash=hash_webhook_token(token),
            header_secret=crypto.encrypt(secret),
            rotated_at=now,
        )

        await self._endpoints.upsert(tenant_id, rotated)
        await self._audit.record(
            tenant_id=tenant_id,
            action=WEBHOOK_ENDPOINT_ROTATED,
            endpoint=rotated,
            actor_user_id=actor_user_id,
            actor_ip=actor_ip,
            changes=_material_changes(None).diff("rotated_at", existing.rotated_at, now),
            now=now,
        )
        await self._uow.commit()

        return WebhookEndpointMaterial(
            endpoint_id=rotated.id,
            provider=rotated.provider,
            header_name=rotated.header_name,
            webhook_token=token,
            header_secret=secret,
        )


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
