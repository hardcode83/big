"""`ChangeSet` — rule 11 of `sdd/steering/security.md`, made structural (design D3).

Rule 11 governs the columns through which a rule-3 value (an access code, a WiFi password,
a document number) could reach the database in cleartext without the column name announcing
it. `audit_logs.changes` is one of them, and this change is its first writer.

The rule is not enforced here by convention but by construction: there are exactly two ways
to record a field, and the one that keeps the value **raises** for any field on
`REDACTED_FIELDS`. So the only reachable form for a secret is `{"changed": true}`.

Shape: `{field: {"old": ..., "new": ...}}` per PRD §7.25, or `{field: {"changed": true}}`.
"""

import enum
import math
import uuid
from collections.abc import Mapping
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.audit.domain.exceptions import AuditContractError

# Fields whose value never survives in `changes`, not even masked. Matched
# case-insensitively, and by exact name rather than by substring: a substring rule
# ("anything containing 'code'") would silently swallow `internal_code` and
# `country_code`, and a denylist that quietly covers more than it says is one nobody
# can reason about. A new sensitive column adds its name here.
REDACTED_FIELDS = frozenset(
    {
        "password",
        "password_hash",
        "temporary_password",
        # The real column names of the schema, not only the conceptual ones: the security
        # panel of section 1 caught `wifi_password_encrypted`
        # (`app/properties/infrastructure/models.py`) missing while its shorter form was
        # listed. An exact-name denylist that does not carry the exact names is decoration.
        "document_number",
        "document_number_encrypted",
        # Added by `access-notifications` after its feature-scale security panel. The number
        # was already here and the birth date was not, so `redacted()` was the only form for
        # one and mere convention for the other — the module claims its guarantee holds "by
        # construction", and for `date_of_birth` it did not.
        #
        # It belongs here on the steering's own words: §"Datos sensibles" reads "PII de
        # huéspedes (documento de identidad, **fecha de nacimiento** — requeridos por
        # SES.Hospedajes)".
        "date_of_birth",
        # `full_name` and `nationality`, added by `guest-portal-api` after its section 2
        # panel — where the security and QA reviewers independently demonstrated that
        # `diff("full_name", ...)` was legal and would store the value verbatim.
        #
        # **`nationality` was deliberately excluded until now, and the premise that justified
        # excluding it is what changed.** `access-notifications` argued that §"Datos
        # sensibles" does not name it and that a denylist growing past what the rule says is
        # one nobody can reason about — which was right *while an operator was the only
        # writer*. The guest portal makes both fields the free text of an **anonymous
        # internet caller**: `POST /api/v1/guest/checkin/{token}` takes `full_name` and
        # `nationality` straight from a form nobody authenticates. That is the same property
        # that disqualified `incidents.title`/`description` in the very same change, and
        # treating the two cases differently is what the panel objected to.
        #
        # This is therefore not the denylist quietly growing: it is the same criterion
        # applied to a writer that did not exist when the earlier decision was made. Nothing
        # is lost — both stay on the `GUEST` allowlist, so `redacted()` still records that
        # they changed, which is all the use cases ever did with them.
        "full_name",
        "nationality",
        "wifi_password",
        "wifi_password_encrypted",
        "access_code",
        "access_code_encrypted",
        # Provider credentials (`pms-provider-resolution`). A stolen one grants **write** access
        # to a client's calendar, pricing and messaging, so it is the most consequential name on
        # this list — and note the effect: `diff()` on it RAISES, which leaves `redacted()` as
        # the only way to record a rotation. That is the intended shape, not an obstacle.
        "secret_encrypted",
        # The webhook endpoint's two halves (`reservations-webhooks` D3). `header_secret_encrypted`
        # is the obvious one. `token_hash` is here for a less obvious reason worth stating: it is
        # already a digest, so it looks harmless — but it is the **lookup key** for a route whose
        # non-guessability IS the defence of rule 12(b), and an `old`/`new` pair of digests in
        # `audit_logs` hands an insider a permanent record of every route the tenant has ever had,
        # against which a stolen token can be confirmed offline.
        "token_hash",
        "header_secret_encrypted",
        # `access_records.code_masked` is already the masked form rule 4 allows, so it is
        # not denylisted: forcing `{"changed": true}` on it would record less than the
        # rule permits.
    }
)

# The fields that may appear in an audited diff AT ALL — an allowlist, checked on top of the
# denylist above. This is what makes the guarantee structural instead of aspirational.
#
# Why an allowlist is needed and the denylist is not enough: `diff` can only vet the name it
# is handed, so a caller inventing a field name gets to write whatever it likes under it. The
# security panel of section 1 found this as a compound value; refusing compounds moved the
# same hole to `diff("profile_patch", None, json.dumps({...}))`, because a `str` carries any
# shape you care to encode. Vetting the *content* of strings is unwinnable — the next encoding
# is base64, or no encoding at all. Vetting the *name* is decidable: an audited field must be
# a real, non-sensitive column of the entity being audited.
#
# A new writer registers its fields here, which forces the sensitivity question at the moment
# somebody adds a column to the audit trail rather than at review time.
#
# `ASSUMPTION` — what this still does not stop, stated plainly rather than over-claimed: a
# caller passing a secret as the VALUE of a legitimate field
# (`diff("name", None, "<the wifi password>")`). No
# validation can close that — it is closed by the use cases feeding these diffs from typed
# entity attributes, and by the closed `action`/`entity_type` vocabulary of actions.py.
AUDITABLE_FIELDS: Mapping[str, frozenset[str]] = {
    "USER": frozenset(
        {
            "name",
            "email",
            "phone",
            "preferred_language",
            "role",
            "status",
            "password",
            # `auth-account-recovery` R5.1/design D9. Auditable as a real diff and NOT
            # redacted, unlike `password` beside it: it is a boolean of account state, not a
            # value of rule 3 of `steering/security.md`, so recording that it went from true
            # to false leaks nothing and is exactly what a review of an incident wants.
            "must_change_password",
        }
    ),
    "TENANT": frozenset(
        {"name", "billing_email", "country", "timezone", "default_language"}
    ),
    "TENANT_CONFIG": frozenset(
        {
            "owner_approval_threshold_eur",
            "ai_confidence_threshold",
            "sla_critical_minutes",
            "sla_high_minutes",
            "sla_medium_minutes",
            "sla_low_minutes",
            "checkin_window_hours_before",
            "checkout_ready_hours_after",
            "auto_create_cleaning_task",
            "cleaning_photo_required",
            "notification_email_enabled",
            "notification_whatsapp_enabled",
        }
    ),
    # Mandatory even though a credential read records NO diff: `ChangeSet.__init__` refuses an
    # unknown `entity_type`, and an empty `ChangeSet` still has to be constructed for one.
    #
    # `secret_encrypted` is listed here AND denylisted above, which is not a contradiction: the
    # allowlist says "this field may appear in a credential's audit row at all", the denylist says
    # "only in its redacted form". Together they mean a rotation records `{"changed": true}` and
    # there is no path that records the value. Removing it from here would make `redacted()` fail
    # too, leaving rotation unrecordable.
    "PMS_CREDENTIAL": frozenset({"secret_encrypted", "rotated_at"}),
    # `reservations-webhooks`. Both secrets are on the denylist below, so the only reachable form
    # for either is `{"changed": true}` — which is all a rotation needs to record and is exactly
    # what rule 11 demands ("el valor no sobrevive en absoluto"). `header_name` is NOT a secret:
    # it is the provider's own header name, an operational fact worth seeing change.
    "WEBHOOK_ENDPOINT": frozenset(
        {"token_hash", "header_secret_encrypted", "header_name", "rotated_at"}
    ),
    # `properties-crud`. Mirrors `PATCHABLE_PROPERTY_FIELDS` plus the two things a PATCH cannot
    # write: `wifi_password_encrypted` (its own writer encrypts it) and nothing else.
    #
    # `current_operational_state` is absent, and that is the same boundary the port draws: its
    # trail is `property_state_transitions`, which records more than a generic row could
    # (`from_state`, `triggered_by`, `reason`), and rule 9 of `steering/security.md` carries the
    # named exception for the `SYSTEM` actor that writes it. Listing it here would invite a second
    # source of truth for one fact.
    #
    # `wifi_password_encrypted` is listed here AND denylisted above, for the same reason
    # `secret_encrypted` is: the allowlist says it may appear in a property's audit row at all,
    # the denylist says only as `{"changed": true}`. Removing it here would make `redacted()`
    # fail too, and a WiFi password changing would leave no trace whatsoever.
    #
    # The three free-text notes are auditable but **not** denylisted, so `diff()` on them is
    # technically legal. Design D7 records them as `redacted()` regardless — they are the kind of
    # field where an operator pastes a door code — and that discipline lives in the use case, not
    # here. Stated rather than left implicit, because the asymmetry with the WiFi password above
    # is deliberate: rule 11 governs a rule-3 *value*, and a cleaning note is not one.
    "PROPERTY": frozenset(
        {
            "name",
            "internal_code",
            "pms_external_id",
            "address_line1",
            "address_line2",
            "city",
            "province",
            "postal_code",
            "country",
            "timezone",
            "max_guests",
            "bedrooms",
            "bathrooms",
            "default_check_in_time",
            "default_check_out_time",
            "wifi_name",
            "wifi_password_encrypted",
            "access_notes",
            "cleaning_notes",
            "emergency_notes",
            "status",
        }
    ),
    # `cleaning`. Only the columns a person's action moves, and none of them is sensitive:
    # a status, an assignee, a verdict and the four timestamps. Deliberately **without
    # `notes`** — design D13 keeps that column out of this change's writable surface because
    # rule 11's table does not enumerate it, and an audited diff would carry its content into
    # `audit_logs.changes`, which is a rule-11 sink itself.
    "CLEANING_TASK": frozenset(
        {
            "status",
            "assigned_cleaner_id",
            "validation_status",
            "validated_by_user_id",
            "accepted_at",
            "started_at",
            "completed_at",
            "validated_at",
        }
    ),
    # `cleaning-photos-storage`. Three fields, and what is **absent** is the point:
    # `storage_key` is not auditable. R3.2 keeps the internal key out of every API response
    # **field** — the one accepted exception is that it appears inside the *value* of an `S3`
    # presigned URL, which is part of the signing protocol and cannot be removed
    # (`docs/adr/0008-object-storage-provider-dev.md`) —
    # and `audit_logs.changes` is a rule-11 sink whose whole contract is that a value cannot
    # arrive through it without the column announcing it — writing the key here would put the
    # one string the design works to keep private into the one column designed to be dumped.
    # `photo_type` and the two ids are what an incident review actually asks for: who uploaded
    # what kind of evidence, against which cleaning.
    "CLEANING_PHOTO": frozenset({"photo_type", "cleaning_task_id", "uploaded_by"}),
    # `access-notifications`. Rule 9 of `steering/security.md` names `AccessRecord` in its
    # enumeration, so every operator action on one writes a row.
    #
    # **`code_masked` is listed and NOT denylisted**, unlike every other secret-adjacent
    # column above, and the denylist's own comment already anticipated it: what the entity
    # stores is *already* the `****XX` form rule 4 grants, so forcing `{"changed": true}`
    # would record less than the rule permits. There is no plaintext column to protect
    # (design D9) — the value never reaches the entity, let alone this diff.
    #
    # `notes` is here because `revoke()` writes the reason into it and losing that would make
    # a revocation unattributable. It is free text an operator types, so the use cases record
    # it with `redacted()`, the same discipline `properties-crud` design D7 applies to its
    # three note columns — a manager pasting a door code into "notes" is the case both guard.
    "ACCESS_RECORD": frozenset(
        {"status", "provider", "created_mode", "code_masked", "external_id", "notes"}
    ),
    # `access-notifications`. Rule 9: "acceso/modificación de documentos de Guest".
    #
    # `document_number_encrypted` is listed here AND denylisted above, exactly like
    # `secret_encrypted` and `wifi_password_encrypted`: the allowlist says it may appear in a
    # guest's audit row at all, the denylist says only as `{"changed": true}`. Removing it
    # here would make `redacted()` fail too, and a document being replaced would leave no
    # trace.
    #
    # `date_of_birth` is listed here AND denylisted above — see the entry there for why. This
    # comment used to argue the opposite ("auditable as a diff, and that is deliberate"), and
    # it survived the commit that moved the field onto the denylist: the stale-copy failure
    # rule 11's own paragraph describes, found by the panel's re-review. Nothing here restates
    # the reasoning any more; it cites.
    #
    # `nationality` and `full_name` are listed here AND denylisted above, since
    # `guest-portal-api` — see the entry there for why the premise changed. This comment used
    # to say `nationality` "IS auditable as a diff, deliberately"; that was true while an
    # operator was its only writer, and the guest portal is what stopped it being true.
    #
    # `full_name` arrives with the same change (design D10): the portal's check-in is the
    # first path that WRITES it, because a stay whose `reservations.guest_id` is NULL creates
    # the `Guest` from the name the guest typed (OQ3).
    #
    # Four of these eight are also on the denylist above, which is the usual pairing and not
    # a contradiction: the allowlist says the field may appear in a guest's audit row at all,
    # the denylist says only as `{"changed": true}`. Removing any of them from here would
    # make `redacted()` fail too, and the change would leave no trace whatsoever.
    #
    # What stays diffable is `document_type`, `document_status`, `legal_registration_status`
    # and `document_expiry_date` — three closed enumerations and a date, none of them a field
    # a caller composes freely.
    #
    # **That bound is the caller's, not this module's**, and saying so matters because an
    # earlier draft of this comment claimed otherwise: `_storable` accepts any `str` for any
    # of the four, so what actually stops composed text is `app/guests/api/schemas.py` typing
    # the boundary as Pydantic `date`/enum fields, and the use cases passing `.value` off real
    # enum instances. It is the same boundary the `ASSUMPTION` note above already describes
    # for every allowlisted field; the guest portal is what made it load-bearing here.
    "GUEST": frozenset(
        {
            "full_name",
            "nationality",
            "date_of_birth",
            "document_type",
            "document_number_encrypted",
            "document_expiry_date",
            "document_status",
            "legal_registration_status",
        }
    ),
    # `access-notifications`. The legal registration of a stay (PRD §17) moves on the
    # reservation, not on the guest (design D10), so its audit rows point at a reservation.
    "RESERVATION": frozenset({"legal_registration_status", "access_status"}),
    # `guest-portal-api` D11. `token_hash` is already on the denylist above, so the only
    # reachable form is `{"changed": true}` — which is all an issue or a rotation needs to
    # record, and is exactly what rule 11 demands. It is listed here anyway for the reason
    # `secret_encrypted` is listed under `PMS_CREDENTIAL`: removing it would make
    # `redacted()` fail too, leaving the minting of a portal credential untraceable.
    #
    # `revoked_at` is a plain timestamp and carries no secret, so it is a real diff.
    "GUEST_ACCESS_TOKEN": frozenset({"token_hash", "revoked_at"}),
    # `guest-portal-api` D11, widened by `maintenance` D6. Deliberately **without `title`
    # and `description`**: both are free text written from outside by an anonymous guest, and
    # `audit_logs.changes` is a rule-11 sink. What the audit row needs is that an incident
    # was opened, by whom and against which stay — `source`, `status` and `reservation_id`
    # say that without carrying a word the guest typed into an append-only column.
    #
    # `maintenance` adds the fields its flow mutates, and **`ai_summary` and
    # `ai_classification` are absent for the same reason `title` and `description` are**:
    # excepción 2 of rule 11 says of itself that it does not propagate and does not
    # authorise a writer of ours, so a classifier's output does not enter this column
    # either. What an audit trail of an incident needs is what changed operationally — its
    # category, its severity, who it went to, and the three costs.
    "INCIDENT": frozenset(
        {
            "source",
            "status",
            "reservation_id",
            "category",
            "severity",
            "assigned_technician_id",
            "owner_approval_required",
            "estimated_cost",
            "approved_cost",
            "final_cost",
            "resolved_at",
        }
    ),
    # `maintenance` D6. **Without `reason` and `response_notes`**, the two free-text columns
    # of `owner_approvals`: the first is written by our code and the second typed by the
    # owner, and neither has any business in a rule-11 sink on an append-only table.
    #
    # **And without `approved_cost_applied`, which D6 listed and this does not implement.**
    # That name is not a column of `owner_approvals` — it was meant to record the fact that
    # the approved amount reached the incident (R2.4) — and `_check_auditable` says what an
    # allowlist entry is for: "an audited diff may only name a real, non-sensitive column of
    # the entity: an invented name is how a caller writes an arbitrary payload — including a
    # secret — into audit_logs.changes under a harmless-looking key". A slot with no column
    # has no type behind it, so `.diff("approved_cost_applied", None, approval.reason)` would
    # have carried the owner's free text past the only defence this module has. The fact
    # itself is not lost: it is `INCIDENT.approved_cost`, one entity over and on a real
    # column. Raised by the security panel of section 4; recorded in the change's D6.
    "OWNER_APPROVAL": frozenset(
        {
            "status",
            "amount",
            "related_type",
            "responded_by",
            "responded_at",
        }
    ),
    # `revenue-pricing` D12. The twelve writable columns of `pricing_rules`, mirroring
    # `UPDATABLE_RULE_FIELDS` in `app/pricing/domain/entities.py` exactly — a rule's whole
    # editable surface is what an auditor needs, and none of the twelve is a rule-3 value,
    # so there is no entry on the denylist.
    #
    # **The five JSONB columns are in `REDACT_ONLY_FIELDS` below**, so `diff()` on any of
    # them raises and `{"changed": true}` is the only form that reaches
    # `audit_logs.changes`. That matters because those five carry the `name` the manager
    # types into a season or an event, which design D13 declares is the one piece of
    # `price_recommendations.explanation` our template does not compose — it must not follow
    # her text into a second sink.
    #
    # An earlier version of this comment claimed the guarantee came from `_storable`
    # refusing a `Mapping` or a `list`. That was the same overclaim this module already made
    # and corrected for `GUEST`: `_storable` accepts any `str`, so a caller serialising the
    # column first — `diff(column, None, json.dumps(value))` — walked straight through. The
    # name-level refusal is what makes "by construction" true rather than nearly true.
    #
    # **`name` is deliberately NOT redact-only**, and that asymmetry is a decision: it is the
    # rule's label, a manager renaming "Madrid base" to "Madrid summer" is exactly what a
    # trail should show, and it is a bounded scalar rather than a document. It is free text
    # she types, so it carries a census row of its own in `steering/security.md` (task 8.2).
    #
    # **Not under exception 3's shape**, and the distinction matters enough to write down: that
    # exception's defining clause is «no se propaga» — `owner_approvals.response_notes` is
    # *outside* `AUDITABLE_FIELDS`, so `ChangeSet` refuses it by construction. `name` is
    # inside it, right below, and `_rule_change_set` diffs it here literally. Borrowing that
    # shape would put a "does not propagate" promise on a value that demonstrably does, which
    # rule 11 calls worse than an uncensused column. Its row goes under the ground this module
    # already uses for `properties.access_notes`: rule 11 governs a **rule-3 value**, and a
    # pricing rule's label is not one. Raised by the section-5 security panel on re-review.
    "PRICING_RULE": frozenset(
        {
            "name",
            "active",
            "property_id",
            "base_price",
            "min_price",
            "max_price",
            "max_daily_change_pct",
            "weekday_modifiers",
            "lead_time_rules",
            "occupancy_rules",
            "seasonality_rules",
            "event_rules",
        }
    ),
    # `revenue-pricing` D12. **`status` and nothing else**, and the shortness is the point.
    #
    # A recommendation's only human-moved column is its status (PRD §7.18 gives the table no
    # `updated_at` either). Everything else — `recommended_price`, `pricing_rule_id`,
    # `confidence` — is rewritten by a job nobody attributes, and `explanation` is sink 14 of
    # rule 11: it holds the manager's own `name` text, so listing it here would carry that
    # text into `audit_logs.changes`, which is itself a rule-11 sink. `ChangeSet` therefore
    # rejects every other field of this entity by construction, which is what
    # `tests/pricing/test_free_text_sink_contract.py` pins.
    "PRICE_RECOMMENDATION": frozenset({"status"}),
}

#: Fields that may appear in an entity's audit row **only** as `{"changed": true}`, keyed by
#: entity type. The per-entity sibling of `REDACTED_FIELDS` above, which is global.
#:
#: Why a second mechanism rather than adding these names to the global denylist: these are
#: not rule-3 values, and a name like `name` or `event_rules` denylisted globally would
#: silently swallow the same column on every other entity that happens to share the spelling
#: — the exact over-reach the denylist's own comment rejects ("un denylist que quietly cubre
#: más de lo que dice es uno sobre el que nadie puede razonar").
#:
#: **What earned the first entries here.** `revenue-pricing`'s five JSONB columns carry the
#: free text a manager types into a season or an event name, and design D13 makes that text
#: the one part of `price_recommendations.explanation` our template does not compose. The
#: change first relied on `_storable` refusing `Mapping`/`list` and called that "by
#: construction" — but `_storable` accepts any `str`, so `diff(column, None,
#: json.dumps(value))` walked straight through and wrote the manager's text verbatim into
#: this sink. Its own security panel found it, and the module had already made and corrected
#: the identical overclaim once for `GUEST` (see the comment on that entry). Refusing the
#: field by name is what makes the claim true instead of nearly true.
REDACT_ONLY_FIELDS: Mapping[str, frozenset[str]] = {
    "PRICING_RULE": frozenset(
        {
            "weekday_modifiers",
            "lead_time_rules",
            "occupancy_rules",
            "seasonality_rules",
            "event_rules",
        }
    ),
}

_REDACTED_MARKER = {"changed": True}


class ChangeSet:
    """Immutable accumulator of audited field changes, bound to one entity type.

    Immutable because a shared mutable accumulator would let the fields of one use case
    leak into the audit row written by the next one in the same request.

    Bound to an entity type because that is what makes the allowlist possible: `USER` and
    `TENANT_CONFIG` audit different columns, and a change set that did not know which entity
    it described could only ever check a union of every field in the system.
    """

    __slots__ = ("_entity_type", "_entries")

    def __init__(
        self, entity_type: str, _entries: Mapping[str, dict[str, Any]] | None = None
    ) -> None:
        if entity_type not in AUDITABLE_FIELDS:
            raise AuditContractError(
                f"Unknown audit entity type {entity_type!r}: it has no declared auditable "
                "fields in app/audit/domain/value_objects.py."
            )
        self._entity_type = entity_type
        self._entries: dict[str, dict[str, Any]] = dict(_entries or {})

    @property
    def entity_type(self) -> str:
        return self._entity_type

    def diff(self, field: str, old: Any, new: Any) -> "ChangeSet":
        """Record the old and the new value of a field.

        Raises `AuditContractError` if the field is on `REDACTED_FIELDS` (for those the only
        available form is `redacted()`) or if it is not an auditable field of this entity.
        """
        self._check_recordable(field)
        return self._with(field, {"old": _storable(field, old), "new": _storable(field, new)})

    def redacted(self, field: str) -> "ChangeSet":
        """Record that a field changed, without its value. The default form of rule 11."""
        self._check_auditable(field)
        return self._with(field, dict(_REDACTED_MARKER))

    def as_dict(self) -> dict[str, dict[str, Any]]:
        """A copy: handing out the internal mapping would let a caller edit an audited diff."""
        return {field: dict(entry) for field, entry in self._entries.items()}

    def fields(self) -> frozenset[str]:
        return frozenset(self._entries)

    def __bool__(self) -> bool:
        """Falsy when empty, so a caller can skip writing an audit row (design D15)."""
        return bool(self._entries)

    def _check_recordable(self, field: str) -> None:
        """The denylist is checked FIRST, for the more actionable message of the two."""
        if field.strip().lower() in REDACTED_FIELDS:
            raise AuditContractError(
                f"Field {field!r} is a rule-3 value: record it with redacted(), never as a "
                "diff. Its value must not reach audit_logs.changes, masked or otherwise "
                "(rule 11 of steering/security.md)."
            )
        if field in REDACT_ONLY_FIELDS.get(self._entity_type, frozenset()):
            raise AuditContractError(
                f"Field {field!r} of {self._entity_type} is redact-only: record it with "
                "redacted(), never as a diff. It carries free text a user typed, and "
                "audit_logs.changes is itself a rule-11 sink — so the value must not "
                "survive here in ANY encoding, serialised to a string included."
            )
        self._check_auditable(field)

    def _check_auditable(self, field: str) -> None:
        if field not in AUDITABLE_FIELDS[self._entity_type]:
            raise AuditContractError(
                f"Field {field!r} is not an auditable field of {self._entity_type}. An "
                "audited diff may only name a real, non-sensitive column of the entity: an "
                "invented name is how a caller writes an arbitrary payload — including a "
                "secret — into audit_logs.changes under a harmless-looking key."
            )

    def _with(self, field: str, entry: dict[str, Any]) -> "ChangeSet":
        if field in self._entries:
            raise AuditContractError(
                f"Field {field!r} is already recorded in this change set; two entries for one "
                "field make the audited diff ambiguous."
            )
        return ChangeSet(self._entity_type, {**self._entries, field: entry})


def _storable(field: str, value: Any) -> Any:
    """The value as JSONB can store it, or `AuditContractError` naming the field.

    Naming the offending field rather than failing at the driver is the same choice
    `TimelineEventFactory` makes for its `metadata`: a JSONB write that dies inside
    asyncpg aborts the whole transaction and says nothing about which key did it.

    **Scalars only.** A `Mapping` or a list is refused, and that is a security boundary,
    not a limitation nobody got round to lifting. The security panel of section 1 showed
    the bypass: `diff` can only vet the field name it is given, so a compound value
    smuggles a denylisted key past it —

        diff("profile_patch", {...}, {"wifi_password_encrypted": "gAAAA-secret"})

    — and the secret would survive verbatim, defeating the "by construction, not by care"
    guarantee this module exists for (design D3). Recursing the denylist into nested keys
    would close that one hole while leaving the shape of `changes` free-form, against
    PRD §7.25 (`{field: {old: val, new: val}}`); refusing compounds closes the class.
    Scalars are also why `as_dict()` can copy shallowly and stay honest about immutability.

    A future change that genuinely needs a structured diff records one field per leaf, or
    argues for compounds with its own security review.

    `uuid`, `Decimal`, `date`/`datetime` and enums are converted rather than rejected:
    they are what the callers naturally hold, and making every call site remember a
    `str(...)` is how one of them forgets.
    """
    if isinstance(value, enum.Enum):
        return _storable(field, value.value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            # Postgres JSONB has no NaN/Infinity; the insert would fail at the driver.
            raise AuditContractError(
                f"Field {field!r} carries a non-finite number, which JSONB cannot store."
            )
        return value
    if isinstance(value, (str, int)):
        return value
    if isinstance(value, (uuid.UUID, Decimal)):
        return str(value)
    # `time` alongside the other two since `properties-crud`: `properties` is the first audited
    # entity with bare `TIME` columns (`default_check_in_time`, `default_check_out_time`), and
    # without this a PATCH of a check-in time reached here and became a `500`. It is a scalar and
    # JSONB stores it as the same ISO string the other two produce — the omission was that no
    # entity had needed it, not a decision.
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (Mapping, list, tuple, set, frozenset)):
        raise AuditContractError(
            f"Field {field!r} carries a {type(value).__name__}. Audited diffs are scalar: a "
            "compound value can hide a denylisted key that diff() never sees (rule 11 of "
            "steering/security.md). Record one field per leaf instead."
        )
    raise AuditContractError(
        f"Field {field!r} carries a {type(value).__name__}, which JSONB cannot store."
    )
