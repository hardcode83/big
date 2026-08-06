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

ENTITY_TYPES = frozenset(
    {ENTITY_USER, ENTITY_TENANT, ENTITY_TENANT_CONFIG, ENTITY_PMS_CREDENTIAL}
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
    }
)
