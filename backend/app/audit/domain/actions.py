"""The closed vocabulary of `audit_logs.action` and `entity_type` (R6.5, design D4).

PRD §7.25 types both columns as free-form `VARCHAR`, which is exactly why they need a
vocabulary in code: `ix_audit_logs_tenant_id_entity_type_entity_id` only helps if every
writer spells the entity type the same way, and rule 9 of `steering/security.md` ("AuditLog
para … roles de User") is only auditable if a role change is findable by `action` rather
than by a JSONB query over `changes`.

One row per API mutation (design D4): a `PATCH` that changes the role **and** the profile
records `USER_ROLE_CHANGED` with both fields in `changes`, not two rows.

Not enums: §7.25 declares plain strings and `AuditLog.action` is typed `str`. Constants
give the single spelling without pretending the column is constrained.
"""

# entity_type — the table `entity_id` points at. Singular, upper snake case.
ENTITY_USER = "USER"
ENTITY_TENANT = "TENANT"
ENTITY_TENANT_CONFIG = "TENANT_CONFIG"
# A row of `pms_credentials`. It has an id of its own, which is why the credentials are a table
# and not columns on `properties`: `AuditLog.entity_id` is a required UUID, and an account-scoped
# credential spread across property columns would have nothing to point at (ADR 0006, obligation
# 4, and `pms-provider-resolution` design D4).
ENTITY_PMS_CREDENTIAL = "PMS_CREDENTIAL"
# A row of `properties` (`properties-crud` design D7). Rule 9's enumeration names "estados de
# propiedad" and not the property itself, so creating one or editing its address was invisible
# until this change. Audited anyway, on the precedent rule 9 already set for `TenantConfig`: the
# enumeration is a floor, and a row nobody can attribute is a gap in the trail whether or not the
# list happens to name it. The state column stays out — its trail is `property_state_transitions`,
# and rule 9's named exception covers the `SYSTEM` actor that writes it.
ENTITY_PROPERTY = "PROPERTY"

# A row of `cleaning_tasks`. Added by `cleaning`: rule 9 of `sdd/steering/security.md` exempts
# a property state transition from `AuditLog` **only when the actor is `SYSTEM`**, and says so
# explicitly — "una transición con cualquier otro actor —`USER`, `WEBHOOK` o `SCHEDULER`— NO
# está exenta". Accepting, rejecting, starting and completing a cleaning are all done by a
# person, so each writes its row. The task created by `process_checkouts` is `SYSTEM` and is
# covered by that exemption.
ENTITY_CLEANING_TASK = "CLEANING_TASK"

# A row of `access_records` (`access-notifications`). Rule 9 of `sdd/steering/security.md`
# names `AccessRecord` in its enumeration explicitly — unlike `PROPERTY`, which had to be
# argued for — so no reasoning is needed here beyond the citation.
ENTITY_ACCESS_RECORD = "ACCESS_RECORD"
# A row of `guests` (`access-notifications`). Rule 9: "acceso/modificación de documentos de
# Guest". Note **acceso**: a read writes a row too, which is unusual in this vocabulary and
# is why `GUEST_DOCUMENT_READ` exists alongside the update.
ENTITY_GUEST = "GUEST"
# A row of `reservations` (`access-notifications`). Only for the legal-registration
# submission of PRD §17: `specs/reservations.md` records that the module's own mutations
# still owe their `AuditLog`, and this change does not pay that debt — it audits the one
# operation it introduces.
ENTITY_RESERVATION = "RESERVATION"

# action — the operation that produced the row.
USER_CREATED = "USER_CREATED"
USER_UPDATED = "USER_UPDATED"
USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
USER_DEACTIVATED = "USER_DEACTIVATED"
USER_PASSWORD_RESET = "USER_PASSWORD_RESET"
TENANT_UPDATED = "TENANT_UPDATED"
TENANT_CONFIG_UPDATED = "TENANT_CONFIG_UPDATED"

# Provider credentials (ADR 0006 obligation 4, which rule 9's enumeration did not cover — so
# before this change, reading or rotating one was invisible).
#
# How many READ rows a run writes is stated in ONE place — the named exception in rule 9 of
# `sdd/steering/security.md`. This comment does not restate it, not even the negative half: the
# sweep that found the previous copies found this clause too, and "everything else cites it"
# either holds or it does not. That is not fastidiousness: three consecutive reviews each found
# a DIFFERENT error in this statement while it lived in five artifacts, and a paraphrase here was
# one of the survivors, still asserting an inverted granularity and the wrong unit after the rule
# had been corrected. Approved for this change in design D6, which likewise cites rather than
# restates.
PMS_CREDENTIAL_READ = "PMS_CREDENTIAL_READ"
PMS_CREDENTIAL_ROTATED = "PMS_CREDENTIAL_ROTATED"

# There is no `PROPERTY_DELETED`: retirement is `status = INACTIVE`, so it arrives as an update
# (`properties-crud` R3.4, and `domain-foundation-core`: "el PRD modela el borrado vía `status`,
# nunca `DELETE` real"). An action for an operation the API does not offer would be the
# speculative vocabulary this module's docstring argues against.
PROPERTY_CREATED = "PROPERTY_CREATED"
PROPERTY_UPDATED = "PROPERTY_UPDATED"

# Cleaning tasks (`cleaning`). One action per operation rather than a single
# `CLEANING_TASK_UPDATED`, because rule 9 is only auditable if the operation is findable by
# `action` — the same reasoning that made `USER_ROLE_CHANGED` its own action instead of a JSONB
# query over `changes`. `CLEANING_TASK_ASSIGNED` covers both the manager's `PATCH` and a
# re-assignment; the automatic one at checkout is `SYSTEM` and writes nothing.
CLEANING_TASK_ASSIGNED = "CLEANING_TASK_ASSIGNED"
CLEANING_TASK_ACCEPTED = "CLEANING_TASK_ACCEPTED"
CLEANING_TASK_REJECTED = "CLEANING_TASK_REJECTED"
CLEANING_TASK_STARTED = "CLEANING_TASK_STARTED"
CLEANING_TASK_COMPLETED = "CLEANING_TASK_COMPLETED"
CLEANING_TASK_VALIDATED = "CLEANING_TASK_VALIDATED"
CLEANING_TASK_CREATED = "CLEANING_TASK_CREATED"

# Access records (`access-notifications`). One action per operation, same reasoning as the
# cleaning ones: rule 9 is only auditable if the operation is findable by `action` rather than
# by a JSONB query over `changes`.
#
# `ACCESS_RECORD_CREATED` and `ACCESS_RECORD_REVOKED` are written by the reconciler of design
# D2, whose actor is automatic, so their rows carry `actor_user_id = NULL`. That is NOT the
# named `SYSTEM` exception of rule 9 — that one is about property state transitions and does
# not extend here. The row is written; it just has no person to name, exactly like the
# credential-resolution rows of `pms-provider-resolution`.
ACCESS_RECORD_CREATED = "ACCESS_RECORD_CREATED"
ACCESS_CODE_REGISTERED = "ACCESS_CODE_REGISTERED"
ACCESS_MARKED_EXTERNAL = "ACCESS_MARKED_EXTERNAL"
ACCESS_DELIVERED = "ACCESS_DELIVERED"
ACCESS_REVOKED = "ACCESS_REVOKED"
ACCESS_EXPIRED = "ACCESS_EXPIRED"

# Guest documents and the legal registration (`access-notifications`, PRD §17).
#
# `GUEST_DOCUMENT_READ` is the odd one in this file: every other action records a *mutation*.
# Rule 9 asks for "acceso/modificación", and for an identity document the access is the part
# that matters — a leak is somebody reading, not somebody writing.
GUEST_DOCUMENT_UPDATED = "GUEST_DOCUMENT_UPDATED"
GUEST_DOCUMENT_READ = "GUEST_DOCUMENT_READ"
LEGAL_REGISTRATION_SUBMITTED = "LEGAL_REGISTRATION_SUBMITTED"
LEGAL_REGISTRATION_FAILED = "LEGAL_REGISTRATION_FAILED"

ENTITY_TYPES = frozenset(
    {
        ENTITY_USER,
        ENTITY_TENANT,
        ENTITY_TENANT_CONFIG,
        ENTITY_PMS_CREDENTIAL,
        ENTITY_PROPERTY,

        ENTITY_CLEANING_TASK,
        ENTITY_ACCESS_RECORD,
        ENTITY_GUEST,
        ENTITY_RESERVATION,
    }
)

ACTIONS = frozenset(
    {
        USER_CREATED,
        USER_UPDATED,
        USER_ROLE_CHANGED,
        USER_DEACTIVATED,
        USER_PASSWORD_RESET,
        TENANT_UPDATED,
        TENANT_CONFIG_UPDATED,
        PMS_CREDENTIAL_READ,
        PMS_CREDENTIAL_ROTATED,
        PROPERTY_CREATED,
        PROPERTY_UPDATED,

        CLEANING_TASK_CREATED,
        CLEANING_TASK_ASSIGNED,
        CLEANING_TASK_ACCEPTED,
        CLEANING_TASK_REJECTED,
        CLEANING_TASK_STARTED,
        CLEANING_TASK_COMPLETED,
        CLEANING_TASK_VALIDATED,
        ACCESS_RECORD_CREATED,
        ACCESS_CODE_REGISTERED,
        ACCESS_MARKED_EXTERNAL,
        ACCESS_DELIVERED,
        ACCESS_REVOKED,
        ACCESS_EXPIRED,
        GUEST_DOCUMENT_UPDATED,
        GUEST_DOCUMENT_READ,
        LEGAL_REGISTRATION_SUBMITTED,
        LEGAL_REGISTRATION_FAILED,
    }
)
