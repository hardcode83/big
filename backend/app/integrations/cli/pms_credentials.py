"""`python -m app.integrations.cli.pms_credentials` — store and rotate PMS credentials (D13).

**Why a command and not an endpoint.** Rule 3(a) of `steering/security.md` forbids serialising a
provider credential in any API response, even masked, and `properties/` deliberately has no
`api/` layer. An endpoint would create exactly the surface that rule exists to prevent. Without
this command the only way to fill `pms_credentials` would be SQL by hand, which bypasses the
encryption, the cross-tenant guard and the audit in one go — and the "rotation" half of R4.2
would have no way to happen at all.

**The secret never arrives as an argument.** It is read from a named environment variable,
because an argument survives in the shell history and is visible in `ps` to every user on the
box. Same reasoning as `beds24_probe.py` with `BEDS24_REFRESH_TOKEN`, and the same reason
`pms_sync` refuses to echo a rejected `--provider` value.

Nothing this command prints ever contains the secret, not even masked: rule 4's masked form is
for access codes, and rule 3(a) gives provider credentials no such allowance.
"""

import asyncio
import os
import sys
import uuid
from datetime import UTC, datetime

# Imported for its side effect, exactly as `pms_sync` does: every model module must be registered
# before the first query or SQLAlchemy cannot resolve the foreign keys between tables it has not
# seen. A command has its own import graph.
import app.core.models_registry  # noqa: F401
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.domain.actions import (
    ENTITY_PMS_CREDENTIAL,
    PMS_CREDENTIAL_ROTATED,
)
from app.audit.domain.services import AuditLogFactory
from app.audit.domain.value_objects import ChangeSet
from app.audit.infrastructure.repositories import SqlAlchemyAuditLogRepository
from app.core.crypto import SecretDecryptionError, encrypt
from app.core.db import async_session_factory, bind_session_to_tenant
from app.integrations.domain.entities import PmsCredential
from app.integrations.domain.enums import (
    PMSProvider,
    PmsCredentialScope,
    credential_scope_for,
)
from app.integrations.infrastructure.repositories import SqlAlchemyPmsCredentialRepository
from app.properties.infrastructure.repositories import SqlAlchemyPropertyRepository
from app.tenants.infrastructure.models import TenantModel

SECRET_ENV_VAR = "PMS_CREDENTIAL_SECRET"
SUBCOMMANDS = ("set", "rotate", "show-providers")
USAGE = (
    "usage:\n"
    "  python -m app.integrations.cli.pms_credentials set <tenant-uuid> <provider> <scope> "
    "[property-uuid]\n"
    "  python -m app.integrations.cli.pms_credentials rotate <tenant-uuid> <provider> <scope> "
    "[property-uuid]\n"
    "  python -m app.integrations.cli.pms_credentials show-providers <tenant-uuid>\n"
    f"\nThe secret is read from ${SECRET_ENV_VAR}, never from an argument.\n"
    f"providers: {', '.join(p.value.lower() for p in PMSProvider)}\n"
    f"scopes: {', '.join(s.value.lower() for s in PmsCredentialScope)}"
)


class UsageError(RuntimeError):
    """A malformed invocation. Never carries the offending value — it might be the secret."""


def _read_secret() -> str:
    secret = os.environ.get(SECRET_ENV_VAR, "")
    if not secret.strip():
        # Names the variable and stops. Not a prompt: a command that reads a secret from a TTY
        # cannot be used from a runbook, and one that accepts an empty value would store a
        # credential that authenticates nothing while looking configured.
        raise UsageError(
            f"{SECRET_ENV_VAR} is empty or unset. Provide the credential through it, "
            f"never as a command-line argument (shell history, ps)."
        )
    return secret.strip()


def _parse_enum(raw: str, enum_type, label: str):
    try:
        return enum_type(raw.strip().upper())
    except ValueError:
        # The value is NOT echoed: a mistyped argument list can put the secret here.
        valid = ", ".join(member.value.lower() for member in enum_type)
        raise UsageError(f"unknown {label} (expected one of {valid})") from None


async def store_with_session(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    provider: PMSProvider,
    scope: PmsCredentialScope,
    property_id: uuid.UUID | None,
    secret: str,
    rotating: bool,
    now: datetime | None = None,
) -> None:
    """Store or replace one credential, audited when it replaces an existing one.

    Split from `main` so the suite can drive it on the test session, exactly as
    `pms_sync.sync_with_session` is.
    """
    at = now or datetime.now(UTC)
    bind_session_to_tenant(session, tenant_id)
    if await session.scalar(select(TenantModel.id).where(TenantModel.id == tenant_id)) is None:
        raise UsageError(f"No tenant with id {tenant_id}")

    # The coordinates must be the ones the RESOLVER reads, or the command is theatre. The
    # security panel of sections 6-8 reproduced both halves: storing a Channex key at
    # `channex account` succeeded and printed "ok" while every sync kept using the
    # environment-wide key, and `rotate beds24 property <uuid>` succeeded and wrote a
    # PMS_CREDENTIAL_ROTATED row while the ACCOUNT credential the factory actually reads was
    # untouched — an audit trail asserting a leaked secret had been replaced when it had not.
    # That is exactly the deception the "refuse to rotate what is absent" guard below exists to
    # prevent, arriving through the other door.
    expected_scope = credential_scope_for(provider)
    if expected_scope is None:
        raise UsageError(
            f"provider '{provider.value.lower()}' stores no credential here — it authenticates "
            f"from the environment, so nothing written at these coordinates would ever be read"
        )
    if scope is not expected_scope:
        raise UsageError(
            f"provider '{provider.value.lower()}' uses '{expected_scope.value.lower()}' scope; "
            f"a credential stored at '{scope.value.lower()}' would never be read"
        )

    if scope is PmsCredentialScope.PROPERTY and property_id is None:
        raise UsageError("scope 'property' requires a property uuid")
    if scope is not PmsCredentialScope.PROPERTY and property_id is not None:
        raise UsageError(f"scope '{scope.value.lower()}' takes no property uuid")

    credentials = SqlAlchemyPmsCredentialRepository(session)
    # `id_at` and NOT `get_for`: this command is about to overwrite whatever is stored, so it
    # needs the row's identity, never its value. Reading the value made a malformed credential
    # unfixable — `get_for` raised `SecretDecryptionError`, nothing here caught it, and the
    # command died with a traceback on both `set` and `rotate`. The operator was then left with
    # hand-written SQL as the only way to replace it, which is the exact path this command exists
    # to close, on the one occasion it matters most: the credential has leaked AND will not parse.
    # The hole predates this change; typing the error is what made it visible.
    existing_id = await credentials.id_at(tenant_id, provider, scope, property_id=property_id)
    if rotating and existing_id is None:
        # Rotating something that is not there is almost always a typo in the coordinates, and
        # silently creating it would hide that — the operator would believe they had replaced a
        # leaked credential while the leaked one is still live under different coordinates.
        raise UsageError(
            "nothing to rotate at those coordinates; use 'set' to store a new credential"
        )

    await credentials.upsert(
        tenant_id,
        PmsCredential(
            id=existing_id if existing_id is not None else uuid.uuid4(),
            tenant_id=tenant_id,
            provider=provider,
            scope=scope,
            secret=encrypt(secret),
            property_id=property_id,
            rotated_at=at if existing_id is not None else None,
        ),
    )
    await session.flush()

    if existing_id is not None:
        # A REPLACEMENT is a rotation and rule 9 requires the row (ADR 0006 obligation 4).
        # Recorded with `redacted()`, never `diff()`: `secret_encrypted` is on rule 11's denylist,
        # so `diff()` on it raises by construction and the only recordable form is
        # `{"changed": true}` — which is the whole point, the value must not survive anywhere.
        await SqlAlchemyAuditLogRepository(session).add(
            tenant_id,
            AuditLogFactory.build(
                tenant_id=tenant_id,
                action=PMS_CREDENTIAL_ROTATED,
                entity_type=ENTITY_PMS_CREDENTIAL,
                entity_id=existing_id,
                actor_user_id=None,
                actor_ip=None,
                changes=ChangeSet(ENTITY_PMS_CREDENTIAL).redacted("secret_encrypted"),
                now=at,
            ),
        )


async def show_providers_with_session(session: AsyncSession, tenant_id: uuid.UUID) -> list[str]:
    """Which provider each property uses. Never touches a credential, so nothing is audited."""
    bind_session_to_tenant(session, tenant_id)
    properties = await SqlAlchemyPropertyRepository(session).list_all(tenant_id)
    return [
        f"{prop.internal_code}\t{prop.pms_provider.value if prop.pms_provider else '(default)'}"
        for prop in properties
    ]


async def _run(argv: list[str]) -> int:
    if not argv or argv[0] not in SUBCOMMANDS:
        raise UsageError("missing or unknown subcommand")
    subcommand, rest = argv[0], argv[1:]
    if not rest:
        raise UsageError("missing tenant uuid")
    try:
        tenant_id = uuid.UUID(rest[0])
    except ValueError:
        raise UsageError("tenant argument is not a uuid") from None

    async with async_session_factory() as session:
        if subcommand == "show-providers":
            for line in await show_providers_with_session(session, tenant_id):
                print(line)
            return 0

        if len(rest) < 3:
            raise UsageError("missing provider or scope")
        provider = _parse_enum(rest[1], PMSProvider, "provider")
        scope = _parse_enum(rest[2], PmsCredentialScope, "scope")
        property_id = None
        if len(rest) > 3:
            try:
                property_id = uuid.UUID(rest[3])
            except ValueError:
                raise UsageError("property argument is not a uuid") from None

        await store_with_session(
            session,
            tenant_id=tenant_id,
            provider=provider,
            scope=scope,
            property_id=property_id,
            secret=_read_secret(),
            rotating=subcommand == "rotate",
        )
        await session.commit()

    # Confirms the COORDINATES and nothing else. Never the secret, never a prefix of it, never a
    # masked form: rule 3(a) gives provider credentials no masked allowance at all.
    print(
        f"pms-credentials: {subcommand} ok — provider={provider.value} "
        f"scope={scope.value} tenant={tenant_id}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    try:
        return asyncio.run(_run(args))
    except UsageError as error:
        print(f"pms-credentials: {error}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 2
    except SecretDecryptionError as error:
        # No path in this command decrypts any more, so reaching here means a NEW one was added.
        # It exits 3 with the message rather than a traceback, and does not print USAGE: this is
        # not a malformed invocation, and telling the operator to check their arguments would
        # send them looking in the wrong place. The message names the row id and never the value.
        print(f"pms-credentials: {error}", file=sys.stderr)
        return 3


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())
