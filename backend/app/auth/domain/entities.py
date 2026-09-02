import uuid
from dataclasses import dataclass
from datetime import datetime

from app.auth.domain.enums import SessionRevokedReason, UserRole, UserStatus
from app.auth.domain.exceptions import SelfRoleChangeError, UnassignableRoleError
from app.auth.domain.value_objects import normalize_email

# `SUPER_ADMIN` is not grantable through the API (R1.6). Its powers in PRD §6 are global —
# all tenants, global configuration, global integrations — not the operation of one tenant,
# and cross-tenant visibility is deferred to the `saas-cross-tenant` roadmap entry. A tenant
# administrator handing it out would pre-empt that decision with a role whose scope this
# capability cannot bound.
GRANTABLE_ROLES = frozenset(UserRole) - {UserRole.SUPER_ADMIN}

# What `update_profile` may touch. `email` is NOT here: it is the login identity (ADR 0005)
# and needs the normalisation and the 409 translation of its own path. `role` and `status`
# are not here either — they have methods that protect their own invariants.
PROFILE_FIELDS = ("name", "phone", "preferred_language")

_UNSET = object()


@dataclass
class User:
    """The account of a person who can authenticate.

    Was a passive dataclass until `user-management`: with `auth-tenancy` nothing mutated a
    user except `touch_last_login`, so there was nothing to protect. Now that roles and
    statuses change through the API, `role` and `status` are only reachable through methods
    that hold their invariants — `steering/backend-architecture.md`: "No entidades con
    setters públicos arbitrarios — mutación solo vía métodos que protegen invariantes".

    Every mutator reports **whether anything actually changed**, so a `PATCH` that changes
    nothing writes neither a row nor an audit entry (design D15).
    """

    id: uuid.UUID
    # `None` for `SUPER_ADMIN` only (`super-admin-identity` R1.1, design D2): the role has
    # no tenant by product requirement, not by omission. Every other role keeps a concrete
    # `tenant_id` — nothing in this entity enforces that pairing; the schema does (R1.2).
    tenant_id: uuid.UUID | None
    name: str
    email: str
    password_hash: str
    role: UserRole
    created_at: datetime
    updated_at: datetime
    phone: str | None = None
    status: UserStatus = UserStatus.ACTIVE
    preferred_language: str = "es"
    last_login_at: datetime | None = None
    must_change_password: bool = False

    @classmethod
    def create(
        cls,
        *,
        tenant_id: uuid.UUID,
        name: str,
        email: str,
        password_hash: str,
        role: UserRole,
        now: datetime,
        phone: str | None = None,
        preferred_language: str = "es",
        must_change_password: bool = False,
    ) -> "User":
        """A new ACTIVE account (R1.1). `email` must arrive already normalised.

        `must_change_password` defaults to False so the bootstrap path — whose passwords a
        person chooses — keeps today's behaviour. Administrative creation passes True
        (`auth-account-recovery` R5.2): the password it hands out is temporary.
        """
        if role not in GRANTABLE_ROLES:
            raise UnassignableRoleError(
                f"Role {role.value} cannot be granted through the API"
            )
        return cls(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            name=name,
            email=email,
            password_hash=password_hash,
            role=role,
            created_at=now,
            updated_at=now,
            phone=phone,
            status=UserStatus.ACTIVE,
            preferred_language=preferred_language,
            must_change_password=must_change_password,
        )

    def update_profile(
        self,
        *,
        name: str | object = _UNSET,
        phone: str | None | object = _UNSET,
        preferred_language: str | object = _UNSET,
    ) -> set[str]:
        """Apply the profile fields that were passed; returns the names that changed.

        A sentinel per field rather than `None` means "absent", because `phone` is nullable:
        `None` is a legitimate value that clears it, and conflating the two would make
        clearing a phone impossible (the same distinction `reservations` draws with
        `model_fields_set`).
        """
        changed: set[str] = set()
        for field, value in (
            ("name", name),
            ("phone", phone),
            ("preferred_language", preferred_language),
        ):
            if value is _UNSET:
                continue
            # `phone` is the only nullable column of the three; a `None` for the other two
            # would end up as the string "None" or as an unmapped `500` at the NOT NULL
            # constraint (security panel of sections 2-6). The API boundary rejects it too;
            # this is the layer that makes it impossible rather than merely unlikely.
            if value is None and field != "phone":
                raise ValueError(f"{field} cannot be None")
            if getattr(self, field) == value:
                continue
            setattr(self, field, value)
            changed.add(field)
        return changed

    def change_email(self, new_email: str) -> bool:
        """Change the login identity; returns whether it changed (R3.3).

        A method and not a bare attribute assignment, which is what the use case did until the
        feature-scale architecture review caught it: `email` was the only field of this entity
        written with a `setattr` from `application/`, and
        `steering/backend-architecture.md` names exactly that as the anti-pattern — "No
        entidades con setters públicos arbitrarios — mutación solo vía métodos que protegen
        invariantes".

        **Normalises here** (ADR 0005, design D19), which makes it symmetric with
        `Tenant.update()`/`_require_email` in the neighbouring module of this change: the
        entity guarantees the invariant instead of demanding it. The first version of this
        method rejected an unnormalised address and justified it with "`domain/` cannot import
        `normalize_email` without a cycle" — the re-review of the architecture panel showed
        that claim was simply **false** (`value_objects.py` imports only `enums.py`, and
        `ports.py` already imports from it), so the method was delegating an invariant it could
        perfectly well own, on a technical constraint that did not exist.

        The duplicate-address `409` stays where only the database can decide it (design D11).
        """
        candidate = normalize_email(new_email)
        if not candidate:
            raise ValueError("email cannot be empty")
        if candidate == self.email:
            return False
        self.email = candidate
        return True

    def change_role(self, new_role: UserRole, *, actor_user_id: uuid.UUID) -> bool:
        """Grant a different role; returns whether it changed (R3.1, R3.5, R1.6).

        Refuses a self-change even for a promotion: the rule is about who may decide, and
        an actor editing their own row is how a tenant loses its last administrator with no
        endpoint back.

        The `isinstance` guard mirrors `change_status`, and the QA panel of sections 2-6 was
        right to call its absence an asymmetry: without it `change_role(None, …)` raises
        `AttributeError`, which is not an `AuthDomainError` and would surface as an unmapped
        `500` for any future caller that does not go through the request schema — a CLI, a bulk
        import, another use case.
        """
        if not isinstance(new_role, UserRole):
            raise ValueError(f"{new_role!r} is not a UserRole")
        if actor_user_id == self.id:
            raise SelfRoleChangeError("An account cannot change its own role")
        if new_role not in GRANTABLE_ROLES:
            raise UnassignableRoleError(
                f"Role {new_role.value} cannot be granted through the API"
            )
        if new_role is self.role:
            return False
        self.role = new_role
        return True

    def change_status(self, new_status: UserStatus, *, actor_user_id: uuid.UUID) -> bool:
        """Suspend, reactivate or deactivate; returns whether it changed (R3.1, R3.5).

        The membership check mirrors the one in `change_role`, and it is not decoration: the
        security panel of sections 2-6 showed that a `null` status arriving from a PATCH slipped
        through this method and died at the `NOT NULL` constraint as an unmapped `500`. The
        boundary now refuses explicit nulls (`UpdateUserRequest`), and this refuses anything
        that is not a status — so the invariant does not depend on a column constraint that a
        future schema change could relax.
        """
        if not isinstance(new_status, UserStatus):
            raise ValueError(f"{new_status!r} is not a UserStatus")
        if actor_user_id == self.id:
            raise SelfRoleChangeError("An account cannot change its own status")
        if new_status is self.status:
            return False
        self.status = new_status
        return True

    def deactivate(self, *, actor_user_id: uuid.UUID) -> bool:
        """The `DELETE` of R3.8: logical, never a physical delete.

        The row stays because `audit_logs.actor_user_id` and
        `timeline_events.actor_user_id` point at it — deleting it would destroy the trail
        rule 9 of `steering/security.md` requires keeping. Idempotent by way of
        `change_status`, which reports False when the user is already INACTIVE (R3.9).
        """
        return self.change_status(UserStatus.INACTIVE, actor_user_id=actor_user_id)

    def set_password_hash(self, password_hash: str, *, temporary: bool) -> None:
        """Replace the stored hash (R4.1). Takes the hash, never a cleartext password.

        Writes `must_change_password` in the same call, and that is the whole point
        (`auth-account-recovery` design D5): one method for both fields means no path
        **through this entity or its repository** replaces a password without deciding
        whether it is temporary. Two methods that must be called together are two that
        somebody will call separately, and the failure is silent — a temporary password that
        never has to be changed, which is the deficiency R5 exists to close.
        `SqlAlchemyUserRepository.apply_changes` enforces the same pairing, because it takes
        a mapping of column names and is the second write path.

        The scope of that claim is deliberate. `app/cli/bootstrap.py` builds `UserModel`
        directly and never comes through here, so its accounts keep the column's `false`
        server default — which design D5 names explicitly and calls correct: bootstrap
        passwords are chosen by a person, not handed out as temporaries.

        `temporary` is keyword-only and has no default on purpose: a default would make
        forgetting it look like a decision.
        """
        self.password_hash = password_hash
        self.must_change_password = temporary


@dataclass
class UserSession:
    """One refresh token's server-side state (R2.1, R2.2, design D5).

    The `id` is the refresh token's `jti`, so the token itself is never stored:
    its signature proves authenticity and this row carries the state. Sessions
    rotated from one another share a `family_id`, which is what makes revoking a
    whole lineage possible when a used token is presented again.
    """

    id: uuid.UUID
    # `None` for a `SUPER_ADMIN` session (`super-admin-identity` R2, design D1/D2): there is
    # no tenant to attribute it to, the same reason `User.tenant_id` above is optional.
    tenant_id: uuid.UUID | None
    user_id: uuid.UUID
    family_id: uuid.UUID
    expires_at: datetime
    parent_id: uuid.UUID | None = None
    used_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_reason: SessionRevokedReason | None = None

    def __post_init__(self) -> None:
        _require_aware(self.expires_at, "expires_at")

    def is_usable(self, now: datetime) -> bool:
        _require_aware(now, "now")
        return self.used_at is None and self.revoked_at is None and self.expires_at > now

    def rotate(self, new_id: uuid.UUID, expires_at: datetime, now: datetime) -> "UserSession":
        """Consume this session and return its replacement in the same family."""
        if not self.is_usable(now):
            raise ValueError("Cannot rotate a session that is used, revoked or expired")
        self.used_at = now
        return UserSession(
            id=new_id,
            tenant_id=self.tenant_id,
            user_id=self.user_id,
            family_id=self.family_id,
            expires_at=expires_at,
            parent_id=self.id,
        )

    def revoke(self, reason: SessionRevokedReason, now: datetime) -> None:
        _require_aware(now, "now")
        if self.revoked_at is not None:
            return
        self.revoked_at = now
        self.revoked_reason = reason


@dataclass
class PasswordResetToken:
    """One recovery link's server-side state (`auth-account-recovery` R3.1, design D1).

    `token_hash` is a SHA-256 digest, never the token: the row must not let anyone
    reconstruct the credential (R4.1). Deterministic rather than salted because that is what
    makes the single conditional `UPDATE` of R3.2 possible — see
    `app/auth/domain/recovery_tokens.py`.

    Deliberately thin. `is_usable` states the invariant for readers and for the in-memory
    double, but it is NOT what decides who spends a token: that is the database's job,
    through one conditional statement (design D1/R3.2). Checking usability here and writing
    afterwards would be exactly the read-then-write race the design forbids.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    token_hash: str
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
    used_at: datetime | None = None
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_aware(self.expires_at, "expires_at")

    def is_usable(self, now: datetime) -> bool:
        _require_aware(now, "now")
        return self.used_at is None and self.revoked_at is None and self.expires_at > now


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
