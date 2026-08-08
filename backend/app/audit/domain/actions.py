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
# A row of `webhook_endpoints`: the material WE mint for a provider to authenticate itself with,
# not a credential a provider gave us. A distinct entity type for the same reason it is a distinct
# table (`reservations-webhooks` design D2) — the two have opposite exposure contracts, and one
# spelling for both would make "who read a provider credential" and "who minted an endpoint
# secret" the same audit question over the same index.
ENTITY_WEBHOOK_ENDPOINT = "WEBHOOK_ENDPOINT"
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

# No `WEBHOOK_ENDPOINT_READ` counterpart to `PMS_CREDENTIAL_READ` **today**, and the asymmetry is
# the point. The credential read is audited because ADR 0006 obligation 4 requires it and because
# each read decrypts. Here the equivalent "read" happens on **every incoming webhook** — an
# anonymous, internet-facing request at provider cadence — so auditing it would let an outsider
# write rows to `audit_logs` at will, which is a denial-of-service dressed as diligence.
#
# **This comment is not where that exemption is granted, and it cannot be.** Rule 3(b) of
# `steering/security.md` requires the read of a provider credential to be audited, and rule 9 says
# an exception to it arrives "con una entrada nueva y nombrada aquí, aprobada en el design del
# change que la pida" — steering, not a comment. Recorded as design D15, PROVISIONAL, and queued in
# `BLOCKED.md` for Jose; the security panel of section 1 caught that the route had been skipped.
#
# Its scope is narrow and stays narrow: it covers the **anonymous receiving path only**. Rule 9 is
# explicit that it "no exime la lectura con actor humano", so a support command or operator tool
# that reads this material brings its own `WEBHOOK_ENDPOINT_READ` when it lands. Not added now,
# because an action for an operation nothing performs is the speculative vocabulary this module's
# docstring argues against — the same reasoning rule 9 applies to `SCHEDULER`.
WEBHOOK_ENDPOINT_CREATED = "WEBHOOK_ENDPOINT_CREATED"
WEBHOOK_ENDPOINT_ROTATED = "WEBHOOK_ENDPOINT_ROTATED"

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

ENTITY_TYPES = frozenset(
    {
        ENTITY_USER,
        ENTITY_TENANT,
        ENTITY_TENANT_CONFIG,
        ENTITY_PMS_CREDENTIAL,
        ENTITY_WEBHOOK_ENDPOINT,
        ENTITY_PROPERTY,

        ENTITY_CLEANING_TASK,
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
        WEBHOOK_ENDPOINT_CREATED,
        WEBHOOK_ENDPOINT_ROTATED,
        PROPERTY_CREATED,
        PROPERTY_UPDATED,

        CLEANING_TASK_CREATED,
        CLEANING_TASK_ASSIGNED,
        CLEANING_TASK_ACCEPTED,
        CLEANING_TASK_REJECTED,
        CLEANING_TASK_STARTED,
        CLEANING_TASK_COMPLETED,
        CLEANING_TASK_VALIDATED,
    }
)
