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

# A row of `cleaning_photos`. Added by `cleaning-photos-storage` (R2.7). Its own entity type
# rather than auditing the upload against the parent task, because `entity_id` is what
# `ix_audit_logs_tenant_id_entity_type_entity_id` indexes: pointing several uploads at one
# task id would make "who uploaded THIS photo" a scan over `changes` instead of a lookup.
# The link back to the task travels as an auditable field of the diff.
ENTITY_CLEANING_PHOTO = "CLEANING_PHOTO"
# A row of `incident_photos`. Added by `incident-photos` (R6.1, design D8). Its own entity type
# rather than auditing the upload against the parent incident, for exactly the reason
# `ENTITY_CLEANING_PHOTO` above gives: `entity_id` is what
# `ix_audit_logs_tenant_id_entity_type_entity_id` indexes, so pointing several uploads at one
# incident id would turn "who uploaded THIS photo" into a scan over `changes`. The link back to
# the incident travels as an auditable field of the diff.
ENTITY_INCIDENT_PHOTO = "INCIDENT_PHOTO"
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
# A row of `incidents` (`guest-portal-api`). Rule 9 of `sdd/steering/security.md` names
# `Incident` in its enumeration explicitly, so unlike `PROPERTY` this needs no argument
# beyond the citation. Only the guest-reported creation is audited here; classifying,
# assigning and resolving belong to `maintenance` and bring their own actions when they land.
ENTITY_INCIDENT = "INCIDENT"
# A row of `guest_access_tokens` (`guest-portal-api` D2, D11). Its own entity type rather
# than auditing against the reservation, for the reason `ENTITY_CLEANING_PHOTO` exists:
# `entity_id` is what `ix_audit_logs_tenant_id_entity_type_entity_id` indexes, so pointing
# several tokens of one stay at the reservation id would turn "who minted THIS token" into a
# scan over `changes`. It is also the same distinction `ENTITY_WEBHOOK_ENDPOINT` draws — a
# credential *we* mint is not the entity it grants access to.
ENTITY_GUEST_ACCESS_TOKEN = "GUEST_ACCESS_TOKEN"
# A row of `owner_approvals` (`maintenance` D6). Rule 9 of `sdd/steering/security.md` names
# `OwnerApproval` in its enumeration explicitly. Its own entity type and not the incident's,
# for the reason `ENTITY_GUEST_ACCESS_TOKEN` gives: one incident can raise two approvals —
# D11's budget gate and its real-cost gate — so pointing both at the incident's id would
# turn "who answered THIS one" into a scan over `changes`.
ENTITY_OWNER_APPROVAL = "OWNER_APPROVAL"
# A row of `pricing_rules` (`revenue-pricing` D12). Rule 9 of `sdd/steering/security.md`
# names `PricingRule/PriceRecommendation` in its enumeration explicitly, so unlike
# `PROPERTY` this needs no argument beyond the citation.
ENTITY_PRICING_RULE = "PRICING_RULE"
# A row of `price_recommendations`. Its own entity type and not the rule's, for the reason
# `ENTITY_OWNER_APPROVAL` gives: one rule produces sixty recommendations per property per
# night, so pointing them all at the rule's id would turn "who approved THIS price" into a
# scan over `changes` instead of a lookup on
# `ix_audit_logs_tenant_id_entity_type_entity_id`.
ENTITY_PRICE_RECOMMENDATION = "PRICE_RECOMMENDATION"
# `demo-tenant-audit-retention`. The purge is not a mutation of any other table — its rows
# vanish — so it does not borrow the entity it acted on (`ENTITY_TENANT`, the obvious
# candidate): `entity_id` is the resource modified, not the scope of the command, and the
# `ChangeSet` for `TENANT` would have no field for `deleted_count` or `cutoff`. Its own
# entity type and its own allowlist entry, exactly like the other writer-less resources the
# vocabulary already enumerates.
ENTITY_AUDIT_LOG = "AUDIT_LOG"

# action — the operation that produced the row.
USER_CREATED = "USER_CREATED"
USER_UPDATED = "USER_UPDATED"
USER_ROLE_CHANGED = "USER_ROLE_CHANGED"
USER_DEACTIVATED = "USER_DEACTIVATED"
USER_PASSWORD_RESET = "USER_PASSWORD_RESET"
# `auth-account-recovery` design D9. Three password actions and not one, because rule 9 of
# `steering/security.md` only makes an operation auditable if it can be FOUND by filtering on
# `action` — and "an administrator reset somebody's password", "the holder changed their own"
# and "the holder recovered the account through a mailed link" are exactly the three a review
# of an incident needs to tell apart. Collapsing them would leave the trail unable to answer
# the question it exists for.
USER_PASSWORD_CHANGED = "USER_PASSWORD_CHANGED"
USER_PASSWORD_RECOVERED = "USER_PASSWORD_RECOVERED"
# `platform-admin-api` (R2.1, R2.2, design D1, D7). The counterpart of `TENANT_UPDATED` for the
# row's birth: until this change a tenant could only arrive through `app/cli/bootstrap.py`, which
# is not an API mutation and writes no audit row, so "who created this tenant" had no answer at
# all. Now `POST /api/v1/platform/tenants` creates one, and rule 9 of `sdd/steering/security.md`
# names `Tenant` in its enumeration — so the creation is audited on the same footing as the
# update, on `ENTITY_TENANT`, in the same transaction as the two inserts.
#
# One action for the whole creation and not one per row, exactly as this module's docstring
# prescribes ("one row per API mutation"): the tenant and its `tenant_configs` row are a single
# operation with a single actor, and the config's defaults are not a separate decision anybody
# audits. `TENANT_CONFIG_UPDATED` covers the later edits.
#
# There is no `TENANT_DELETED` and no `TENANT_SUSPENDED`: `domain-foundation-core` models
# retirement through `status`, this change exposes no route that writes it, and an action for an
# operation the API does not offer is the speculative vocabulary this module argues against.
TENANT_CREATED = "TENANT_CREATED"
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
# change que la pida" — steering, not a comment. It went through that route: design D15, approved by
# Jose on 2026-08-08, and written as the **third named exception of rule 9**, which is where it
# lives. This comment cites it. The security panel of section 1 caught that the route had been
# skipped, which is the only reason it exists at all.
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
# `cleaning-stall-blocks-next-stay` R3.3. Its own action for the reason above: rule 9 is only
# auditable if the operation is findable by `action`, and "who retired this cleaning, and why"
# is the question this one exists to answer. Always a person — `MANAGE_CLEANING_TASKS` — so
# rule 9's `SYSTEM` exemption does not reach it, and the `reason` the entity demands travels
# with the row.
CLEANING_TASK_CANCELLED = "CLEANING_TASK_CANCELLED"

# Cleaning photos (`cleaning-photos-storage`, R2.7). A person uploads it, so rule 9's actor
# exemption — which covers only `SYSTEM` — does not reach it. There is no
# `CLEANING_PHOTO_DELETED`: the proposal keeps deletion out of scope, and an action for an
# operation the API does not offer is the speculative vocabulary this module argues against.
CLEANING_PHOTO_UPLOADED = "CLEANING_PHOTO_UPLOADED"
# Incident photos (`incident-photos`, R6.1, design D8). The technician or the manager uploads
# it, so rule 9's actor exemption — which covers only `SYSTEM` — does not reach it, and this
# action is deliberately **absent** from `_ACTOR_OPTIONAL_ACTIONS` in
# `app/maintenance/application/use_cases.py`: this change asks for no new exception to rule 9.
#
# One action, not two: there is no `INCIDENT_PHOTO_DELETED`, because the proposal keeps every
# deletion surface out of scope and an action for an operation the API does not offer is the
# speculative vocabulary this module argues against. The compensating delete of design D7 is
# not an audited operation — it undoes a transaction that never committed.
INCIDENT_PHOTO_UPLOADED = "INCIDENT_PHOTO_UPLOADED"
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

# The guest portal (`guest-portal-api` D11, D15).
#
# **There is deliberately no `GUEST_CHECKIN_SUBMITTED`**, and the absence is the decision.
# When a guest completes their own check-in the operation *is* `GUEST_DOCUMENT_UPDATED` —
# "modificación de documentos de Guest" in rule 9's words — and who did it is said by the
# actor (`actor_guest_token_hash`), not by a second verb. Inventing one would split the
# question "who touched this guest's document" across two actions, which is exactly what
# this module's docstring says the closed vocabulary exists to prevent.
#
# The two token actions are minted and revoked by an **operator** through the JWT routes of
# D14, so they are ordinary human actions with RBAC behind them. `AUDITABLE_FIELDS` gives
# them `token_hash` and `revoked_at`, and `token_hash` is already on rule 11's denylist —
# so `redacted()` is the only reachable form, exactly as for `WEBHOOK_ENDPOINT`.
GUEST_ACCESS_TOKEN_ISSUED = "GUEST_ACCESS_TOKEN_ISSUED"
GUEST_ACCESS_TOKEN_REVOKED = "GUEST_ACCESS_TOKEN_REVOKED"

# Incidents (`guest-portal-api` D15, then `maintenance` D6). The creation is the guest
# portal's, which was the first writer of `incidents`; rule 9 names the entity.
#
# Where this comment used to say there is no `INCIDENT_CLASSIFIED`/`_ASSIGNED`/`_RESOLVED`
# "because nothing performs those yet, and pre-authorising an operation no code exercises is
# what rule 9 refuses to do for `SCHEDULER`": that door is what `maintenance` walks through.
# The ten actions below are each performed by a use case of that module, so they are minted
# by the same rule that kept them out — a writer exists now.
#
# `INCIDENT_CLASSIFIED` is the one written **without an actor** when the job of D2 does the
# classifying (`actor_user_id` and `actor_ip` both `NULL`). That is rule 9's **fourth named
# exception** in `sdd/steering/security.md`, minted by this change rather than borrowed: the
# second exception is justified by cadence, and this one by there being no actor at all — the
# clock fires the job, so there is no person and no request for `actor_ip` to come from.
#
# It is bounded to this one action and to that one caller. A manual classification by a
# manager carries its actor like any other operation, and none of the eleven actions below
# may be written anonymously — `_AuditWriter` in `app/maintenance/application/use_cases.py`
# refuses them by construction.
INCIDENT_CREATED = "INCIDENT_CREATED"
INCIDENT_CLASSIFIED = "INCIDENT_CLASSIFIED"
INCIDENT_TRIAGED = "INCIDENT_TRIAGED"
INCIDENT_ASSIGNED = "INCIDENT_ASSIGNED"
INCIDENT_ACCEPTED = "INCIDENT_ACCEPTED"
# The technician refused the job (`tech-cycle-completion` R5.2). Its own action rather than a
# reuse of `INCIDENT_ASSIGNED`: an auditor reading the trail has to be able to tell "the
# manager handed this to somebody" from "the person it was handed to said no", and the two
# rows carry the same field in opposite directions (`assigned_technician_id` set versus
# cleared).
INCIDENT_REJECTED = "INCIDENT_REJECTED"
# Written by `en_route` as well as by `resume_work`: the operational fact is the same move
# into `IN_PROGRESS`, and an append-only trail should not carry two verbs for one transition
# (`tech-cycle-completion` D4).
INCIDENT_STARTED = "INCIDENT_STARTED"
INCIDENT_WAITING_PARTS = "INCIDENT_WAITING_PARTS"
INCIDENT_RESOLVED = "INCIDENT_RESOLVED"
INCIDENT_CANCELLED = "INCIDENT_CANCELLED"
# The two states an owner approval leaves the incident in, and they are their own actions
# because neither is a triage. `INCIDENT_TRIAGED` covered both until the architecture panel
# of section 4's sibling — section 6 — pointed out that an auditor reading it on those rows
# would think somebody corrected a category. `maintenance` D6 records the addition.
#
# `INCIDENT_AWAITING_APPROVAL`: the technician's closing cost went past the tenant threshold
# and the close was not accepted (D11's second gate).
# `INCIDENT_RESUMED`: the owner said yes and the incident went back to where its approval's
# `related_type` says it belongs.
INCIDENT_AWAITING_APPROVAL = "INCIDENT_AWAITING_APPROVAL"
INCIDENT_RESUMED = "INCIDENT_RESUMED"

# Owner approvals (`maintenance` D6). Two actions and not one per outcome: the answer's
# outcome is a field of the approval (`status`), so `APPROVED` and `REJECTED` are the same
# operation with a different diff. Splitting them would put the same question — "what did the
# owner decide about this cost" — in two places, which is what this module's closed
# vocabulary exists to prevent.
OWNER_APPROVAL_REQUESTED = "OWNER_APPROVAL_REQUESTED"
OWNER_APPROVAL_ANSWERED = "OWNER_APPROVAL_ANSWERED"

# Pricing (`revenue-pricing` D12). Rule 9 names both entities in its enumeration.
#
# `PRICE_RECOMMENDATION_DECIDED` is **one** action for `APPROVED` and `REJECTED`, with the
# outcome in the diff — the precedent `OWNER_APPROVAL_ANSWERED` set just above: the
# decision's outcome is a field of the entity, and splitting it would put "what was decided
# about this price" in two places.
#
# `PRICE_RECOMMENDATION_APPLIED_EXTERNAL` is separate, and that asymmetry is the decision.
# It is **not a decision but a fact of the world**: somebody published that price in the
# OTA, outside this system. A review asks those two things separately.
#
# `PRICE_RECOMMENDATIONS_GENERATED` covers **only the human path**: one row per property
# whose horizon `POST /price-recommendations/generate` rewrote, on `ENTITY_PROPERTY`, because
# a horizon is 60 recommendations and the property is the single honest anchor an
# `entity_id` can hold. It carries no diff — the question it answers is "who repriced this
# property, and when", and the counts belong to the response and the run's log.
#
# **The nightly job still writes nothing**, and that asymmetry is the decision. Why it is
# permitted is stated in ONE place — the named exception in rule 9 of
# `sdd/steering/security.md`, written by task 8.1 of this change. This comment does not
# restate it, not even the volume figures, for the reason the `PMS_CREDENTIAL_READ` comment
# above gives at length: rule 9 says "todo lo demás la cita, nadie la reformula", and a
# paraphrase here would be the fourth copy of a statement whose previous five-copy life
# produced three consecutive reviews each finding a different error in it.
#
# The scope narrowed after design D12/OQ1 were approved: OQ1 exempted both paths on the
# ground of «ausencia de actor», which is true of the clock and false of an endpoint that
# receives a `user_id` and an `ip` — and rule 9's second and third exceptions say in as many
# words that they «no exime la lectura con actor humano o iniciada por API». Decided by Jose
# on 2026-08-17, on the section-5 security panel's finding.
#
# Until task 8.1 lands there is nothing to cite, which is why that task gates the change
# rather than trailing it — the same route rule 9's fourth exception took through
# `maintenance`'s task 9.1b, and for the reason rule 9 states: the approval in a design is
# not what widens the rule, the line in `security.md` is.
#
# Every action here carries its actor: `_AuditWriter` in
# `app/pricing/application/use_cases.py` refuses all five without one, which is also the
# mechanism that keeps the job's rows unwritten — it is called only when somebody is acting.
PRICING_RULE_CREATED = "PRICING_RULE_CREATED"
PRICING_RULE_UPDATED = "PRICING_RULE_UPDATED"
PRICE_RECOMMENDATION_DECIDED = "PRICE_RECOMMENDATION_DECIDED"
PRICE_RECOMMENDATION_APPLIED_EXTERNAL = "PRICE_RECOMMENDATION_APPLIED_EXTERNAL"
PRICE_RECOMMENDATIONS_GENERATED = "PRICE_RECOMMENDATIONS_GENERATED"

# `demo-tenant-audit-retention`. One action for the purge, and no other: the demo reset's
# `purge-audit` phase is the only operation that mints it, and an action for an operation
# nothing else performs is the speculative vocabulary this module's docstring argues against.
AUDIT_LOG_PURGED = "AUDIT_LOG_PURGED"

# `revenue-reviews` R1.7 / R3.5 — four actions for the four transitions of `Review.status`
# the proposal enumerates, plus one for the draft-edit of `R3.5`. Each is written by the
## corresponding use case in `app/reviews/application/use_cases.py` in the same transaction
## as the row mutation, with `actor_user_id` from the token. The vocabulary closes here
## because adding an action for an operation nothing else performs is the speculative
## vocabulary this module's docstring argues against — same precedent
## `AUDIT_LOG_PURGED` follows for `demo-tenant-audit-retention`.
REVIEW_CREATED = "REVIEW_CREATED"
REVIEW_APPROVED = "REVIEW_APPROVED"
REVIEW_IGNORED = "REVIEW_IGNORED"
REVIEW_POSTED_MANUALLY = "REVIEW_POSTED_MANUALLY"
REVIEW_DRAFT_EDITED = "REVIEW_DRAFT_EDITED"

# `revenue-reviews` — two entity types so the audit row's `entity_id` points at a real
# primary key. The drafts entity sits separately from the reviews one because
# `ix_audit_logs_tenant_id_entity_type_entity_id` is what makes "who did what to
# THIS draft" a lookup, not a scan over `changes`. Same precedent
# `ENTITY_CLEANING_PHOTO` follows for `cleaning-photos-storage`.
ENTITY_REVIEW = "REVIEW"
ENTITY_REVIEW_RESPONSE_DRAFT = "REVIEW_RESPONSE_DRAFT"

ENTITY_TYPES = frozenset(
    {
        ENTITY_USER,
        ENTITY_TENANT,
        ENTITY_TENANT_CONFIG,
        ENTITY_PMS_CREDENTIAL,
        ENTITY_WEBHOOK_ENDPOINT,
        ENTITY_PROPERTY,

        ENTITY_CLEANING_TASK,
        ENTITY_CLEANING_PHOTO,
        ENTITY_INCIDENT_PHOTO,
        ENTITY_ACCESS_RECORD,
        ENTITY_GUEST,
        ENTITY_RESERVATION,
        ENTITY_INCIDENT,
        ENTITY_GUEST_ACCESS_TOKEN,
        ENTITY_OWNER_APPROVAL,
        ENTITY_PRICING_RULE,
        ENTITY_PRICE_RECOMMENDATION,
        ENTITY_AUDIT_LOG,
        ENTITY_REVIEW,
        ENTITY_REVIEW_RESPONSE_DRAFT,
    }
)

ACTIONS = frozenset(
    {
        USER_CREATED,
        USER_UPDATED,
        USER_ROLE_CHANGED,
        USER_DEACTIVATED,
        USER_PASSWORD_RESET,
        USER_PASSWORD_CHANGED,
        USER_PASSWORD_RECOVERED,
        TENANT_CREATED,
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
        CLEANING_TASK_CANCELLED,
        CLEANING_PHOTO_UPLOADED,
        INCIDENT_PHOTO_UPLOADED,
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
        GUEST_ACCESS_TOKEN_ISSUED,
        GUEST_ACCESS_TOKEN_REVOKED,
        INCIDENT_CREATED,
        INCIDENT_CLASSIFIED,
        INCIDENT_TRIAGED,
        INCIDENT_ASSIGNED,
        INCIDENT_ACCEPTED,
        INCIDENT_REJECTED,
        INCIDENT_STARTED,
        INCIDENT_WAITING_PARTS,
        INCIDENT_RESOLVED,
        INCIDENT_CANCELLED,
        INCIDENT_AWAITING_APPROVAL,
        INCIDENT_RESUMED,
        OWNER_APPROVAL_REQUESTED,
        OWNER_APPROVAL_ANSWERED,
        PRICING_RULE_CREATED,
        PRICING_RULE_UPDATED,
        PRICE_RECOMMENDATION_DECIDED,
        PRICE_RECOMMENDATION_APPLIED_EXTERNAL,
        PRICE_RECOMMENDATIONS_GENERATED,
        AUDIT_LOG_PURGED,
        REVIEW_CREATED,
        REVIEW_APPROVED,
        REVIEW_IGNORED,
        REVIEW_POSTED_MANUALLY,
        REVIEW_DRAFT_EDITED,
    }
)
