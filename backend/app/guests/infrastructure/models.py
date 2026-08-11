import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, TenantScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.guests.domain.enums import GuestDocumentStatus, GuestDocumentType, LegalRegistrationStatus

legal_registration_status_enum = Enum(
    LegalRegistrationStatus, name="legal_registration_status", native_enum=True
)


class GuestModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    __tablename__ = "guests"
    __table_args__ = (
        Index("ix_guests_tenant_id_email", "tenant_id", "email"),
        # Redundant as a constraint (`id` is already the primary key) and load-bearing as an
        # FK **target**: PostgreSQL only lets a composite foreign key reference a declared
        # unique key, and `reservations.guest_id` needs one so a stay cannot be linked to a
        # guest of another tenant (`guest-portal-api` R4.2).
        #
        # It exists because the guest portal added the first writer of that column driven from
        # an anonymous surface — `LegalRegistrationStayStore.set_guest`, which OQ3 has creating
        # the `Guest` when a booking has none. The security, QA and tenancy panels of that
        # change's section 3 each reproduced the mismatched write independently before this
        # existed. Same remedy the same change applied to `guest_access_tokens` in section 1.
        UniqueConstraint("tenant_id", "id", name="uq_guests_tenant_id_id"),
    )

    full_name: Mapped[str] = mapped_column(String(300))
    email: Mapped[str | None] = mapped_column(String(255), default=None)
    phone: Mapped[str | None] = mapped_column(String(30), default=None)
    preferred_language: Mapped[str] = mapped_column(String(5), default="es", server_default="es")
    nationality: Mapped[str | None] = mapped_column(String(2), default=None)
    date_of_birth: Mapped[date | None] = mapped_column(Date, default=None)
    document_type: Mapped[GuestDocumentType | None] = mapped_column(
        Enum(GuestDocumentType, name="guest_document_type", native_enum=True), default=None
    )
    document_number_encrypted: Mapped[str | None] = mapped_column(default=None)
    document_expiry_date: Mapped[date | None] = mapped_column(Date, default=None)
    document_status: Mapped[GuestDocumentStatus] = mapped_column(
        Enum(GuestDocumentStatus, name="guest_document_status", native_enum=True),
        default=GuestDocumentStatus.NOT_PROVIDED,
        server_default=GuestDocumentStatus.NOT_PROVIDED.value,
    )
    legal_registration_status: Mapped[LegalRegistrationStatus] = mapped_column(
        legal_registration_status_enum,
        default=LegalRegistrationStatus.NOT_REQUIRED,
        server_default=LegalRegistrationStatus.NOT_REQUIRED.value,
    )


class GuestAccessTokenModel(Base, UUIDPrimaryKeyMixin, TenantScopedMixin, TimestampMixin):
    """The credential behind the anonymous guest portal, one live row per stay (design D2).

    **A table of its own rather than two columns on `reservations`.** A reservation is
    serialised into API responses and edited by `PATCH`, so a credential living there would
    be one `model_validate` away from a response body; and minting or rotating it would have
    no `created_at` of its own without disturbing the booking's `updated_at`. It is the same
    asymmetry by which `webhook_endpoints` is not a set of columns on `pms_credentials`.

    **A declared divergence from PRD §7**, which does not describe this table. But §23
    declares the four `{token}` endpoints and §7.13 declares
    `incidents.reported_by_guest_token`, so the PRD presupposes the token everywhere and
    never gives it a home. Same class as `webhook_endpoints`.

    `TenantScopedMixin` so the row joins `tenant_scoped_classes()` and the global filter the
    ordinary way. But note *when* that filter is off: the authorising lookup runs on an
    **unmarked** session, because the tenant is not known yet — it is this row that resolves
    it — and only then is the session bound (D4).

    That is why `reservation_id` is reached through a **composite** foreign key on
    `(tenant_id, reservation_id)` rather than a plain one, and it is the only composite FK in
    the codebase. With two independent FKs, a row pairing tenant A with a reservation owned
    by tenant B is legal, and the authoriser would then bind the session to A while reading
    B's stay — deriving, in R2.1's words, the wrong tenant from the token, with the global
    filter structurally unable to notice because limits 3 and 4 of `app/core/db.py` leave
    INSERTs and the identity map uncovered. That is rule 3(c) of `steering/security.md`: a
    scoping failure here does not disclose data, it grants control.

    An earlier revision of this docstring simply asserted that the two rows read before
    binding belong to the same tenant. They did not have to: the security and tenancy panels
    of section 1 each demonstrated the mismatched row being accepted. The composite FK is
    what makes the sentence true, so it is stated here as a mechanism rather than a hope.
    """

    __tablename__ = "guest_access_tokens"
    __table_args__ = (
        # The tenant of the token and the tenant of its stay cannot diverge — see the class
        # docstring. Targets `uq_reservations_tenant_id_id`, which exists for this.
        #
        # `ON DELETE RESTRICT`, not CASCADE: a live token is a reason not to delete the stay
        # silently. The row is the trail of who was given access to it.
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["reservations.tenant_id", "reservations.id"],
            ondelete="RESTRICT",
            name="fk_guest_access_tokens_reservation_within_tenant",
        ),
        # R1.5 as a schema invariant instead of use-case discipline: never two live tokens
        # authorising the same stay. Partial, because a plain UNIQUE on `reservation_id`
        # would also forbid the *revoked* history, and revocation has to leave a trail.
        Index(
            "uq_guest_access_tokens_live_per_reservation",
            "reservation_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    reservation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # 64 hex characters. UNIQUE **across tenants** on purpose: this is the column the
    # authorising path queries with no tenant in hand — it is what resolves the tenant — so
    # global uniqueness is what makes "exactly one row" a schema guarantee rather than an
    # assumption of the caller. `index=True, unique=True` rather than a bare `unique=True`
    # for the reason `webhook_endpoints.token_hash` documents: the first gives a unique
    # *index* and the second a unique *constraint*, and `alembic check` compares the shapes.
    token_hash: Mapped[str] = mapped_column(String(64), index=True, unique=True)
    # R1.4, and also R2.2's "consumido": revocation is the real shape that condition takes
    # here. There is deliberately no `expires_at` — the window is derived from the stay at
    # authorisation time (D3), so a reservation that moves or is cancelled needs no sweep.
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
