"""RBAC policy — PRD §6 in one auditable place (R3.1, design D8).

The catalogue holds only the permissions this change actually enforces. Each new
module adds the permissions its endpoints declare; there is no speculative
catalogue of capabilities nobody checks yet.
"""

import enum
from collections.abc import Mapping

from app.auth.domain.enums import UserRole


class Permission(str, enum.Enum):
    READ_OWN_PROFILE = "READ_OWN_PROFILE"
    MANAGE_OWN_SESSION = "MANAGE_OWN_SESSION"
    # Added by `reservations` (design D7). Two, not one: PRD §6 gives
    # `PROPERTY_MANAGER` "gestionar reservas (crear, editar, cancelar)" and
    # `TENANT_OWNER` only "ver sus propiedades y reservas", so read and write are
    # different capabilities. Importing a CSV and syncing the PMS are the same business
    # capability by another route, so they reuse MANAGE_RESERVATIONS instead of adding a
    # permission nobody reasons about separately.
    READ_RESERVATIONS = "READ_RESERVATIONS"
    MANAGE_RESERVATIONS = "MANAGE_RESERVATIONS"
    # Added by `user-management` (design D8). Four and not two: PRD §6 gives
    # `TENANT_OWNER` "configurar preferencias del tenant" and says nothing about who
    # administers staff, while `PROPERTY_MANAGER` needs to READ both — the roster to assign
    # cleanings, the thresholds and SLAs to operate — without being able to mutate either.
    # Whoever can assign roles can escalate privileges, so that stays with the owner.
    READ_USERS = "READ_USERS"
    MANAGE_USERS = "MANAGE_USERS"
    READ_TENANT_SETTINGS = "READ_TENANT_SETTINGS"
    MANAGE_TENANT_SETTINGS = "MANAGE_TENANT_SETTINGS"
    # Added by `properties-crud` (design D12). Unlike every entry above, this split could NOT be
    # cited from PRD §6: that section names no create-or-edit-property capability for any role at
    # all, so the reasoning is recorded rather than referenced. §6 gives `TENANT_OWNER` "ver sus
    # propiedades y reservas" — a read — and `PROPERTY_MANAGER` "acceder a todos los datos
    # operativos", so the split mirrors `reservations` exactly: the owner sees the portfolio, the
    # manager operates it.
    READ_PROPERTIES = "READ_PROPERTIES"
    MANAGE_PROPERTIES = "MANAGE_PROPERTIES"
    READ_BUILD_PROVENANCE = "READ_BUILD_PROVENANCE"

    # Added by `cleaning` (design D7). Five and not two, because three different
    # capabilities meet on these tables and PRD §6 gives them to different people:
    # reading the work, administering it (assigning, creating, validating), and *doing* it.
    #
    # `EXECUTE_CLEANING_TASKS` is the cleaner's alone — not the manager's. R3.4/R3.5/R3.6 say
    # "la limpiadora asignada" without exception, and the entity answers 404 to anyone who is
    # not the assignee (R7.2), so a manager holding it would see a task in the listing and get
    # a 404 acting on it. What the manager needs — reassign, create, validate — is
    # `MANAGE_CLEANING_TASKS`.
    READ_CLEANING_TASKS = "READ_CLEANING_TASKS"
    MANAGE_CLEANING_TASKS = "MANAGE_CLEANING_TASKS"
    EXECUTE_CLEANING_TASKS = "EXECUTE_CLEANING_TASKS"
    READ_CLEANING_TEMPLATES = "READ_CLEANING_TEMPLATES"
    MANAGE_CLEANING_TEMPLATES = "MANAGE_CLEANING_TEMPLATES"

    # Added by `maintenance` (design D13). The same triple split as cleaning above, with one
    # deliberate difference: **`EXECUTE_INCIDENTS` is the manager's too**, because R4.5 says
    # so literally — "un `PROPERTY_MANAGER` sí puede, para desatascar". The assignee
    # restriction therefore rides the role and not the permission, in
    # `IncidentActor.restrict_to_technician_id`, which is what puts it in the repository
    # filter where no router can forget it (R5.3).
    #
    # `RESPOND_OWNER_APPROVALS` is the owner's alone (R2.6). There is deliberately **no**
    # `READ_OWNER_APPROVALS` and no listing route: the dashboard already exposes pending
    # approvals per property, and this catalogue carries only the permissions a change
    # actually applies.
    READ_INCIDENTS = "READ_INCIDENTS"
    MANAGE_INCIDENTS = "MANAGE_INCIDENTS"
    EXECUTE_INCIDENTS = "EXECUTE_INCIDENTS"
    RESPOND_OWNER_APPROVALS = "RESPOND_OWNER_APPROVALS"

    # Added by `access-notifications`.
    #
    # `READ_OWN_NOTIFICATIONS` is self-service and not a role capability: the endpoint
    # returns the rows addressed to the caller, so a cleaner needs it exactly as much as an
    # owner does. Scoping happens in the repository (`list_for_recipient`), which is why the
    # permission can be universal without being a leak.
    READ_OWN_NOTIFICATIONS = "READ_OWN_NOTIFICATIONS"
    # Access records split read/manage on the same reasoning as `reservations` and
    # `properties`: PRD §6 gives `TENANT_OWNER` visibility and `PROPERTY_MANAGER` the
    # operation. `CLEANER`/`TECHNICIAN` get neither — a guest's door code is not part of
    # doing a cleaning or a repair.
    READ_ACCESS_RECORDS = "READ_ACCESS_RECORDS"
    MANAGE_ACCESS_RECORDS = "MANAGE_ACCESS_RECORDS"
    # Guest identity documents (PRD §17). Separate from `READ_RESERVATIONS` deliberately:
    # rule 4 of `steering/security.md` treats the document number as the most sensitive
    # value in the system, and folding it into "can read bookings" would grant it to every
    # future holder of that permission by accident.
    READ_GUEST_DOCUMENTS = "READ_GUEST_DOCUMENTS"
    MANAGE_GUEST_DOCUMENTS = "MANAGE_GUEST_DOCUMENTS"
    # Submitting the legal registration to SES.Hospedajes is an operation, not a read of the
    # document, so it is its own permission: an operator may need to submit without ever
    # being shown the number.
    SUBMIT_LEGAL_REGISTRATION = "SUBMIT_LEGAL_REGISTRATION"

    # Added by `guest-portal-api` (design D14). Minting and revoking the token that lets a
    # guest reach the portal, through the two JWT routes on
    # `/api/v1/reservations/{id}/guest-access-token`.
    #
    # **One permission, not a read/manage pair**, unlike almost every entry above. There is
    # nothing to read: the row stores only a hash, and rule 3(a)'s named exception lets the
    # cleartext value be returned exactly once at issue time and never in a later read — so a
    # `READ_GUEST_ACCESS_TOKENS` would grant the ability to see a digest, which is not a
    # capability anyone reasons about separately.
    #
    # **Not folded into `MANAGE_RESERVATIONS`**, for the reason `READ_GUEST_DOCUMENTS` is not
    # folded into `READ_RESERVATIONS`: this hands out a credential to an anonymous surface
    # that writes guest PII, and every future holder of "can edit bookings" would inherit it
    # by accident.
    MANAGE_GUEST_ACCESS_TOKENS = "MANAGE_GUEST_ACCESS_TOKENS"

    # Added by `messaging-ai` (design D17). The read/manage pair of `reservations` and
    # `properties`, and the split is cited rather than invented: PRD §6 gives
    # `PROPERTY_MANAGER` "operar reservas, limpiezas, incidencias, **conversaciones**".
    #
    # **No third `EXECUTE_CONVERSATIONS`**, unlike `cleaning` and `maintenance`: there is no
    # role that answers a guest and cannot also manage the inbox, and this catalogue carries
    # only the permissions a change actually applies.
    READ_CONVERSATIONS = "READ_CONVERSATIONS"
    MANAGE_CONVERSATIONS = "MANAGE_CONVERSATIONS"

    # Added by `revenue-pricing` (design D11). Four, in the usual two read/manage pairs —
    # reading a price and setting the box it moves in are different capabilities, the same
    # split `reservations`, `properties` and `cleaning` already draw.
    #
    # **What is NOT usual: the owner manages here too**, and it is a conscious divergence
    # from the "la owner ve, el manager opera" pattern every pair above follows.
    # `min_price`, `max_price` and `max_daily_change_pct` are the limits of her own money
    # (R3's user story: "pueda dejar el sistema generando sin vigilarlo"), and PRD §19 Mode 1
    # says literally "Manager/owner aprueba manualmente y actualiza en OTA". Denying her
    # either one would leave an owner without a manager — PRD §1's scale — unable to set her
    # own floor or approve a price for her own flat.
    #
    # `MANAGE_PRICE_RECOMMENDATIONS` covers the three transitions **and** `POST /generate`:
    # forcing a recalculation after touching a rule is the same operational capability, and
    # a permission for one button is not something anyone reasons about separately.
    #
    # `CLEANER` and `TECHNICIAN` get none of the four; `SUPER_ADMIN` neither, for the reason
    # the note below gives about every operational permission inside a tenant.
    READ_PRICING_RULES = "READ_PRICING_RULES"
    MANAGE_PRICING_RULES = "MANAGE_PRICING_RULES"
    READ_PRICE_RECOMMENDATIONS = "READ_PRICE_RECOMMENDATIONS"
    MANAGE_PRICE_RECOMMENDATIONS = "MANAGE_PRICE_RECOMMENDATIONS"

    # Added by `revenue-statements` (design D8). The split is the same as
    # `READ_ACCESS_RECORDS`/`MANAGE_ACCESS_RECORDS` two entries above: PRD §6 gives
    # `TENANT_OWNER` visibility ("ver sus propiedades y reservas") and `PROPERTY_MANAGER`
    # the operation ("acceder a todos los datos operativos"). Both read the statement
    # because the owner is the one who actually receives the document; the manager
    # operates it (generation, status transitions, notes, exports). `CLEANER`,
    # `TECHNICIAN`, `SUPER_ADMIN` get neither — `SUPER_ADMIN` for the same cross-tenant
    # reason it holds no operational permission today, and the field roles because a
    # cleaning or a ticket is not a financial review.
    READ_OWNER_STATEMENTS = "READ_OWNER_STATEMENTS"
    MANAGE_OWNER_STATEMENTS = "MANAGE_OWNER_STATEMENTS"
    # Added by `revenue-reviews` (design D3). Five, in the same one-per-action shape
    # `messaging-ai` and `cleaning` use: each verb the flow exposes gets its own
    # permission rather than a generic `MANAGE_REVIEWS`, because R4.2 has different
    # RBAC for `APPROVE`/`IGNORE`/`MARK_POSTED` and a single permission would force a
    # caller to widen the gate when they wanted to keep it narrow.
    #
    # **`CREATE_REVIEW` is the manager's alone.** Reading is shared (`READ_REVIEWS`),
    # the three terminal actions are shared too (`APPROVE_REVIEW`, `IGNORE_REVIEW`,
    # `MARK_REVIEW_POSTED`), and the create is a manager operation — same pattern
    # `_CONVERSATION_MANAGE` documents. `CLEANER` and `TECHNICIAN` get none of the
    # five: a review response is not part of doing a cleaning or a repair.
    READ_REVIEWS = "READ_REVIEWS"
    CREATE_REVIEW = "CREATE_REVIEW"
    APPROVE_REVIEW = "APPROVE_REVIEW"
    IGNORE_REVIEW = "IGNORE_REVIEW"
    MARK_REVIEW_POSTED = "MARK_REVIEW_POSTED"

    # Added by `platform-admin-api` (R5.1, R5.2, design D3, D6). The counterpart of
    # `_GUEST_ACCESS_TOKEN_MANAGE` for the platform surface: `POST /api/v1/platform/tenants`
    # and the operator console that follows. **One permission, not a read/manage pair**, and
    # not a read at all: the cross-tenant listing of D6 is `SUPER_ADMIN`-only, and the only
    # reason to read what the platform owns is to be the one who manages it. A read
    # permission would be granted to nobody, which is what this catalogue calls "speculative
    # vocabulary" in its own docstring.
    #
    # Held by `SUPER_ADMIN` alone for the reason every other operational permission inside
    # a tenant is NOT: its powers in PRD §6 are global — tenants, global configuration,
    # integrations — not the operation of one tenant, and cross-tenant visibility is
    # explicitly deferred to the `saas-cross-tenant` roadmap entry. Granting it to anyone
    # else would pre-empt that decision, which the design gate of 2026-08-16 already
    # resolved the same way for the same surface in `_GUEST_ACCESS_TOKEN_MANAGE`.
    MANAGE_PLATFORM = "MANAGE_PLATFORM"


_SELF_SERVICE = frozenset(
    {
        Permission.READ_OWN_PROFILE,
        Permission.MANAGE_OWN_SESSION,
        Permission.READ_OWN_NOTIFICATIONS,
    }
)
_RESERVATION_READ = frozenset({Permission.READ_RESERVATIONS})
_RESERVATION_MANAGE = frozenset({Permission.READ_RESERVATIONS, Permission.MANAGE_RESERVATIONS})
_USER_READ = frozenset({Permission.READ_USERS})
_USER_MANAGE = frozenset({Permission.READ_USERS, Permission.MANAGE_USERS})
_TENANT_SETTINGS_READ = frozenset({Permission.READ_TENANT_SETTINGS})
_TENANT_SETTINGS_MANAGE = frozenset(
    {Permission.READ_TENANT_SETTINGS, Permission.MANAGE_TENANT_SETTINGS}
)
_PROPERTY_READ = frozenset({Permission.READ_PROPERTIES})
_PROPERTY_MANAGE = frozenset({Permission.READ_PROPERTIES, Permission.MANAGE_PROPERTIES})
_BUILD_PROVENANCE_READ = frozenset({Permission.READ_BUILD_PROVENANCE})

_CLEANING_TEMPLATE_MANAGE = frozenset(
    {Permission.READ_CLEANING_TEMPLATES, Permission.MANAGE_CLEANING_TEMPLATES}
)
_CLEANING_READ = frozenset({Permission.READ_CLEANING_TASKS})
_CLEANING_MANAGE = frozenset(
    {Permission.READ_CLEANING_TASKS, Permission.MANAGE_CLEANING_TASKS}
)
_CLEANING_EXECUTE = frozenset(
    {Permission.READ_CLEANING_TASKS, Permission.EXECUTE_CLEANING_TASKS}
)

_ACCESS_READ = frozenset({Permission.READ_ACCESS_RECORDS})
_ACCESS_MANAGE = frozenset(
    {Permission.READ_ACCESS_RECORDS, Permission.MANAGE_ACCESS_RECORDS}
)
# The document read comes with the legal submission for the manager and the owner: PRD §17
# names both among the three roles that may see a full document number, and the submission
# is what they do with it.
_LEGAL_READ = frozenset({Permission.READ_GUEST_DOCUMENTS})
_LEGAL_MANAGE = frozenset(
    {
        Permission.READ_GUEST_DOCUMENTS,
        Permission.MANAGE_GUEST_DOCUMENTS,
        Permission.SUBMIT_LEGAL_REGISTRATION,
    }
)
# `guest-portal-api` D14. Given to `TENANT_OWNER` and `PROPERTY_MANAGER` and to nobody else:
# minting one of these lets whoever holds the resulting link submit the guest's identity
# document, so it belongs with the two administrative roles that PRD §17 already trusts with
# that document. `CLEANER` and `TECHNICIAN` get nothing here — a door code and a cleaning are
# not a reason to hand out a portal credential — and `SUPER_ADMIN` stays out for the same
# reason it holds no other operational permission inside a tenant (see the note below).
_GUEST_ACCESS_TOKEN_MANAGE = frozenset({Permission.MANAGE_GUEST_ACCESS_TOKENS})
# `maintenance` D13. Reading is for the owner, the manager and the technician; managing
# (classifying by hand, triaging, assigning) is the manager's; executing the technician's
# cycle is the technician's **and** the manager's, per R4.5. `CLEANER` gets none of the
# four — a broken boiler is not part of doing a cleaning — and `SUPER_ADMIN` stays out for
# the reason the note below gives about every other operational permission.
_INCIDENT_READ = frozenset({Permission.READ_INCIDENTS})
_INCIDENT_MANAGE = frozenset({Permission.READ_INCIDENTS, Permission.MANAGE_INCIDENTS})
_INCIDENT_EXECUTE = frozenset({Permission.READ_INCIDENTS, Permission.EXECUTE_INCIDENTS})
_OWNER_APPROVAL_RESPOND = frozenset({Permission.RESPOND_OWNER_APPROVALS})
# `messaging-ai` D17. Reading is the owner's and the manager's; operating the inbox — creating
# a conversation, writing into it, escalating, resolving — is the manager's alone.
#
# **The owner reads and does not operate, and that was weighed rather than assumed.** It was
# put against the precedent of `_GUEST_ACCESS_TOKEN_MANAGE`, which the owner *does* get on the
# argument that an owner of two flats without a manager would otherwise be unable to operate;
# the design gate of 2026-08-16 resolved it the other way, for symmetry with `reservations` and
# `properties` and because PRD §6 says it literally. The consequence is assumed and declared:
# `MessageSenderType.OWNER` has no writer in this change, and the role→`sender_type` map of
# D18 has a single entry. Whoever grants `MANAGE_CONVERSATIONS` to the owner adds the second.
#
# `CLEANER` and `TECHNICIAN` get neither — a guest's conversation is not part of doing a
# cleaning or a repair — and `SUPER_ADMIN` stays out for the reason the note below gives about
# every other operational permission inside a tenant.
_CONVERSATION_READ = frozenset({Permission.READ_CONVERSATIONS})
_CONVERSATION_MANAGE = frozenset(
    {Permission.READ_CONVERSATIONS, Permission.MANAGE_CONVERSATIONS}
)
# `revenue-pricing` D11. Both bundles go to `TENANT_OWNER` **and** `PROPERTY_MANAGER` — see
# the enum entry for why the owner manages here when she only reads elsewhere.
_PRICING_RULE_MANAGE = frozenset(
    {Permission.READ_PRICING_RULES, Permission.MANAGE_PRICING_RULES}
)
_PRICE_RECOMMENDATION_MANAGE = frozenset(
    {Permission.READ_PRICE_RECOMMENDATIONS, Permission.MANAGE_PRICE_RECOMMENDATIONS}
)
# `revenue-statements` D8. Owner reads, manager operates — same shape as
# `_ACCESS_READ`/`_ACCESS_MANAGE` above.
_STATEMENTS_READ = frozenset({Permission.READ_OWNER_STATEMENTS})
_STATEMENTS_MANAGE = frozenset(
    {Permission.READ_OWNER_STATEMENTS, Permission.MANAGE_OWNER_STATEMENTS}
)
# `revenue-reviews` D3. Approving, ignoring and marking-as-posted are shared with
# the owner — she is the one who has the right to decide what goes out under her own
# name, even when no manager is around. Only `CREATE_REVIEW` is the manager's alone,
# mirroring `_CONVERSATION_MANAGE` (the inbox operation is the manager's, the owner's
# role is to ratify or shelve).
_REVIEW_OPERATE = frozenset(
    {
        Permission.READ_REVIEWS,
        Permission.APPROVE_REVIEW,
        Permission.IGNORE_REVIEW,
        Permission.MARK_REVIEW_POSTED,
    }
)
_REVIEW_MANAGE = frozenset(
    {
        Permission.READ_REVIEWS,
        Permission.CREATE_REVIEW,
        Permission.APPROVE_REVIEW,
        Permission.IGNORE_REVIEW,
        Permission.MARK_REVIEW_POSTED,
    }
)
# `platform-admin-api` (R5.1, R5.2, D3, D6). The single permission that gates every route
# under `/api/v1/platform/`; held by `SUPER_ADMIN` and by nobody else, exactly as every
# other operational permission held by `SUPER_ADMIN` is the only one in its bundle. A
# frozenset and not a one-element literal, so the bundle line below mirrors every other
# bundle in this file — and so a future second permission (`VIEW_PLATFORM_BILLING`,
# `ROTATE_PLATFORM_INTEGRATION_SECRET`, …) does not have to be threaded through the
# declaration of `ROLE_PERMISSIONS[SUPER_ADMIN]` separately.
_PLATFORM = frozenset({Permission.MANAGE_PLATFORM})

# Every role that can authenticate may read its own profile and end its own
# session (PRD §6). Role-differentiated permissions belong to the modules that
# introduce the endpoints needing them.
#
# `SUPER_ADMIN` gets NO reservation permission on purpose (design D7): its powers in
# PRD §6 are global — tenants, global configuration, integrations — not the operation of
# one tenant, and cross-tenant visibility is explicitly deferred to the `saas-cross-tenant`
# roadmap entry. Granting it here would pre-empt that decision. `CLEANER` and `TECHNICIAN`
# see only their own tasks and tickets, never the booking ledger.
#
# **That rule outlives one PRD sentence, and `access-notifications` is where it first
# collides with one.** PRD §17 says "solo roles `SUPER_ADMIN`, `TENANT_OWNER`,
# `PROPERTY_MANAGER` pueden ver documento completo". That sentence is a **ceiling**, not a
# grant: it names who may, and this table still decides who does. `SUPER_ADMIN` gets no
# `READ_GUEST_DOCUMENTS` here for the same reason it gets no reservation permission — it has
# no operational role inside a tenant until `saas-cross-tenant` decides what cross-tenant
# access looks like, and identity documents are the worst possible place to pre-empt that.
# Nothing in §17 is violated: no role outside its three sees a document.
#
# **Consequence of `_PROPERTY_READ` for the owner, assumed and not accidental** (design D12):
# the owner cannot register her own flat — the manager does. `app/cli/bootstrap.py` creates both
# accounts, so a fresh environment can still reach the API; and this is the one place where
# product intuition ("she owns the homes") and PRD §6 ("ver sus propiedades") diverge, resolved
# in favour of the PRD and of symmetry with reservations.
ROLE_PERMISSIONS: Mapping[UserRole, frozenset[Permission]] = {
    UserRole.SUPER_ADMIN: _SELF_SERVICE | _PLATFORM,
    UserRole.TENANT_OWNER: (
        _SELF_SERVICE
        | _RESERVATION_READ
        | _PROPERTY_READ
        | _BUILD_PROVENANCE_READ
        | _USER_MANAGE
        | _TENANT_SETTINGS_MANAGE
        # Reads the work and owns the standard the tenant cleans to; does not operate it.
        | _CLEANING_READ
        | _CLEANING_TEMPLATE_MANAGE
        # Sees how her guests get in, and may see a document she is legally responsible for
        # (PRD §17 names `TENANT_OWNER` among the three roles). Registering the code and
        # submitting to SES.Hospedajes is operation, which PRD §6 gives to the manager.
        | _ACCESS_READ
        | _LEGAL_READ
        # Issues the guest's portal link. Unlike `_ACCESS_MANAGE` and `_LEGAL_MANAGE`, which
        # the owner does NOT get, this one she does: R1.1 asks for the token to be mintable
        # by the tenant's administrative roles, and an owner operating a small portfolio
        # without a manager (PRD §1's scale) would otherwise have no way to let a guest
        # check in at all.
        | _GUEST_ACCESS_TOKEN_MANAGE
        # Sees what is broken in her homes and answers the money questions; does not triage
        # or assign, which PRD §12 and R1.4/R3.1 give to the manager.
        | _INCIDENT_READ
        | _OWNER_APPROVAL_RESPOND
        # Sees what her guests are saying; does not answer them (D17).
        | _CONVERSATION_READ
        # Sets the box her own prices move in, and approves what comes out of it. The one
        # place an owner *manages* rather than only reads — D11 argues it from PRD §19
        # Mode 1 and from whose money the guardrails bound.
        | _PRICING_RULE_MANAGE
        | _PRICE_RECOMMENDATION_MANAGE
        # Reads the statement that closes her month (D8); does not operate it — same
        # split as `_INCIDENT_READ`/`_ACCESS_READ` above.
        | _STATEMENTS_READ
        # Sees what her guests write, and decides what goes out under her own name
        # (approve, ignore, mark posted). `CREATE_REVIEW` stays with the manager, the
        # same shape `_CONVERSATION_MANAGE` documents — operating the inbox is the
        # manager's, the owner's role is to ratify or shelve.
        | _REVIEW_OPERATE
    ),
    UserRole.PROPERTY_MANAGER: (
        _SELF_SERVICE
        | _RESERVATION_MANAGE
        | _PROPERTY_MANAGE
        | _BUILD_PROVENANCE_READ
        | _USER_READ
        | _TENANT_SETTINGS_READ
        | _CLEANING_MANAGE
        # R1.1 names `PROPERTY_MANAGER` **and** `TENANT_OWNER` as creators of a template, and
        # PRD §6 puts the manager in charge of cleaning ("gestionar limpiezas: asignar,
        # reasignar, validar"). A first draft gave the manager read-only here and the security
        # panel of sections 2-3 caught the divergence from R1.1 and from design D7: in a tenant
        # whose owner never logs in, `process_checkouts` would have nothing to resolve, because
        # `checklist_template_id` is NOT NULL.
        | _CLEANING_TEMPLATE_MANAGE
        # Operates access and the legal registration: PRD §15 has an operator register the
        # code, and PRD §17 step 4 has "manager puede hacer submit".
        | _ACCESS_MANAGE
        | _LEGAL_MANAGE
        | _GUEST_ACCESS_TOKEN_MANAGE
        # Both, and that is the difference from cleaning: `_INCIDENT_MANAGE` is triage and
        # assignment, `_INCIDENT_EXECUTE` is R4.5's "para desatascar".
        | _INCIDENT_MANAGE
        | _INCIDENT_EXECUTE
        # PRD §6: "operar reservas, limpiezas, incidencias, **conversaciones**".
        | _CONVERSATION_MANAGE
        # Operates pricing day to day: writes the rules and forces a regeneration after
        # changing one. Same bundles as the owner, which is the divergence D11 records.
        | _PRICING_RULE_MANAGE
        | _PRICE_RECOMMENDATION_MANAGE
        # Operates the statement end-to-end: generates, mutates, exports, deletes expenses
        # pending consolidation. Owner approves the threshold-driven approvals via
        # `RESPOND_OWNER_APPROVALS`, which is unchanged.
        | _STATEMENTS_MANAGE
        # Operates the review band: creates rows, approves drafts, ignores noise, marks
        # posted manually. PRD §18 and R4.2 give every action of the flow to the manager.
        | _REVIEW_MANAGE
    ),
    UserRole.CLEANER: _SELF_SERVICE | _CLEANING_EXECUTE,
    # Until `maintenance` this role held `_SELF_SERVICE` and nothing else: it existed and
    # could do nothing. R5.2 asks for exactly what R3 and R4 need and nothing more.
    UserRole.TECHNICIAN: _SELF_SERVICE | _INCIDENT_EXECUTE,
}


def is_allowed(role: UserRole, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, frozenset())
