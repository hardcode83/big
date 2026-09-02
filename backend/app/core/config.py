import base64
import binascii
from pathlib import Path

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.tenants.domain.enums import StorageType

REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"

# A Fernet key is base64url of exactly this many bytes (16 for signing + 16 for AES).
FERNET_KEY_BYTES = 32

# Deliberately NOT configurable (design D3): a deployment that set this to "none"
# would disable signature verification altogether.
JWT_ALGORITHM = "HS256"


class Settings(BaseSettings):
    # `validate_default=True` restores a property the move to field validators would otherwise
    # have dropped: a `field_validator` does not run on a default value, while the
    # `model_validator(mode="after")` it replaced did. Unreachable today — `jwt_secret_key` and
    # `encryption_key` are both required and rule 8 forbids giving them one — but the day someone
    # adds a default "just for tests", it would ship unvalidated. Cheap insurance, and no other
    # field pairs a default with a validator, so nothing else changes behaviour.
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT_ENV_FILE, extra="ignore", validate_default=True
    )

    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    redis_url: str = "redis://redis:6379/0"
    database_url: str = ""

    # Required: the application must refuse to boot without a signing key (R1.7)
    # rather than serve with a default one. The 32-character floor matches the
    # 256-bit key HS256 expects — a placeholder like "changeme" would be
    # brute-forceable offline from any issued token, which is the same failure
    # R1.7 exists to prevent. `make up` generates 64 hex characters.
    jwt_secret_key: str = Field(min_length=32)
    jwt_access_token_minutes: int = 15
    jwt_refresh_token_days: int = 7

    # Fernet key for secrets at rest (rule 3 of steering/security.md, R3.3). Required
    # for the same reason as the signing key above: a default would mean shipping a
    # publicly known key, and "encrypted with a key everyone has" is worse than
    # cleartext because it reads as protected.
    #
    # Terraform already generates this value and the CD writes it into the VM's .env
    # (`infra/environments/dev/main.tf`, `encryption_key_fernet`); R3.3 forbids adding
    # a second key or a second variable name, so this field consumes that one.
    #
    # NOT `openssl rand -hex 32` like the JWT key: Fernet expects base64url of 32
    # bytes, and hex would be rejected at construction time. `make up` generates it.
    encryption_key: str

    bcrypt_rounds: int = 12
    # How many password hashes may run at once (design D21). bcrypt is CPU-bound and
    # runs in a worker thread, so this is the login endpoint's CPU budget: too low
    # queues legitimate logins, too high lets one burst of failed attempts starve
    # every other request on the box. `None` derives it from the visible CPU count,
    # which is the only value that adapts to the 4-OCPU dev VM and to a laptop alike.
    bcrypt_max_concurrency: int | None = None

    login_rate_limit_per_minute: int = 10
    login_max_failed_attempts: int = 10
    login_lockout_minutes: int = 15

    # Password recovery. Design D13 named three; `password_reset_grace_minutes` below is the
    # fourth, added by D7's grace amendment during `run`, so **four** settings live here. None
    # of them is a secret, so each carries a working default and none belongs in the
    # `${VAR:?}` fail-fast list of rule 8 of `steering/security.md`.
    #
    # 30 minutes is R3.4's "del orden de los minutos, no de los días", with enough margin for
    # somebody to read the mail on a phone.
    #
    # Bounded, not merely defaulted: R3.4 says the system SHALL **fijar** a short lifetime,
    # and an unbounded int makes "short" a property of the default rather than of the system
    # — `PASSWORD_RESET_TOKEN_MINUTES=43200` would silently buy 30-day recovery links. The
    # ceiling is 12 hours: comfortably under "días" whichever way that is read, and still far
    # more room than any legitimate tuning needs.
    password_reset_token_minutes: int = Field(default=30, gt=0, le=720)
    # How many live links one account may accumulate (design D7). Bounds two things with one
    # mechanism: how much mail an attacker can provoke from different IPs, and how many valid
    # links coexist for one account — a security property in its own right.
    #
    # `ge=1` because 0 or a negative value does not tighten the cap, it changes what the cap
    # MEANS: depending on how the comparison is written it either refuses every recovery
    # outright or wraps around to unlimited, and both are silent. `le=10` keeps the setting a
    # tuning knob rather than a way to switch D7 off.
    password_reset_max_live_tokens: int = Field(default=3, ge=1, le=10)
    # How long a freshly issued link is protected from being retired by the cap (R2.5, design
    # D7's grace amendment). Without it, revoking the oldest let a sustained attacker retire
    # the owner's link seconds after it was sent, and removed the only per-account bound on
    # mail volume — a per-IP budget cannot bound a per-account total across IPs.
    #
    # Must stay well under `password_reset_token_minutes`; the validator below enforces it,
    # because a grace at or above the lifetime would make nothing revocable and turn the cap
    # back into a permanent discard.
    password_reset_grace_minutes: int = Field(default=2, ge=1, le=60)
    # What the recovery link is built on: `{base}/reset-password?token=…`. The page it opens
    # arrives with `dashboard-web`/`hardening-release`, so until then the link is valid and
    # the page is not — the same truth R6.4 declares about the mail itself.
    frontend_base_url: str = "http://localhost:3000"

    # NO `password_min_length` setting, deliberately (design D4). R1.6 obliges the policy to
    # accept every password `app/auth/domain/passwords.py` emits, so a deployment that raised
    # the minimum above `TEMPORARY_PASSWORD_LENGTH` would make the system reject the
    # credentials it hands out itself. It is a domain constant in
    # `app/auth/domain/password_policy.py`, pinned to the generator by a test.
    #
    # NO `SMTP_*` settings either, and that is also design D13: the six names are reserved by
    # name and without value in `.env.example` for `hardening-release`. Rule 8 of
    # `steering/security.md` requires a secret IN USE to fail fast when absent, and none of
    # these is in use yet — declaring them here would make the app demand credentials no code
    # reads.

    # No setting for the real-client-IP header, deliberately (change
    # `api-ingress-routing`, design D3). Resolving it is uvicorn's job:
    # `ProxyHeadersMiddleware` rewrites `scope["client"]` from `X-Forwarded-For`, but
    # only for peers listed in `--forwarded-allow-ips`, which the deploy compose sets
    # to the frontend container's static address. A second reader in the application
    # would have to decide whether to trust a peer the first one may already have
    # rewritten — a check validating its own input.

    # Limits of the CSV reservation import (R4.3, design D11). The two are enforced in
    # different places and NEITHER of them here: the byte ceiling by `MaxBodySizeMiddleware`,
    # which is the only layer that refuses before a byte is read, and the row ceiling by the
    # parser (`integrations/infrastructure/csv_parser.py`), during the parse, over a buffer the
    # middleware has already bounded. Rule 14 of `steering/security.md` is where that contract
    # lives; do not restate it here. The byte ceiling is rule 6 of the same document ("tamaño
    # máx. configurable, default 10 MB"); the row ceiling is this change's, because a small
    # file can still hold a million rows.
    csv_import_max_bytes: int = 10 * 1024 * 1024
    csv_import_max_rows: int = 1000

    # Ceiling for a cleaning photo upload (change `cleaning-photos-storage`, R2.5, design
    # D10/D11). Mirrors `csv_import_max_bytes` deliberately — same rule 6 of
    # `steering/security.md` ("tamaño máx. configurable, default 10 MB"), same default, and
    # the same "checked before the body is read" contract.
    #
    # It exists as its OWN setting rather than reusing the CSV one because the two ceilings
    # answer to different things: a CSV import is bounded by how many reservations a person
    # pastes in, a photo by what a phone camera produces. Sharing the number would make
    # tuning one silently move the other.
    #
    # **Raising `JSON_BODY_MAX_BYTES` instead of adding this was the alternative, and it is
    # forbidden** (design D10): that constant is the ceiling of every `/cleaning-` route, and
    # lifting it re-opens the measured hole `cleaning` closed — an anonymous ~50 MB POST to
    # `/cleaning-checklist-templates` read in full before the `401`. The middleware branch in
    # `app/main.py` is what applies this number to the photo route and only to it.
    #
    # It is checked TWICE, and the second check is not redundant. **What satisfies R2.5
    # ("reject before reading the whole body") is `MaxBodySizeMiddleware`'s accumulating
    # counter, and only it**; the chunk counting inside `UploadCleaningPhotoUseCase` cannot do
    # that job. Why it cannot is rule 14 of `steering/security.md`, the single home of that
    # contract — do not restate the derivation here.
    #
    # What is specific to this number: the use-case count stays because it bounds the
    # in-process copy to this ceiling plus one chunk, and because it is the only ceiling for a
    # caller with no middleware in front (a test, a worker, a future non-HTTP consumer).
    photo_upload_max_bytes: int = 10 * 1024 * 1024

    # The ceiling for every OTHER body under `/api/v1/` (change `api-ingress-routing`). It is
    # deliberately separate from `csv_import_max_bytes` and two orders of magnitude smaller:
    # these are JSON payloads, and the largest legitimate one in the contract is a reservation.
    # It exists because `/api/v1` is now reachable from the internet, where an unbounded body on
    # an anonymous endpoint is a memory amplifier — measured at 1 GiB of RSS from a single 400 MB
    # POST to `/auth/login`, read by FastAPI before the login throttle runs. 1 MiB leaves roughly
    # three orders of magnitude of headroom over a real request.
    request_max_bytes: int = 1024 * 1024

    # Build provenance is private backend configuration. These remain strings so an absent
    # value in the deploy `.env` is an unavailable provenance block, not a boot-time failure;
    # `PrivateProvenance.from_settings` validates the four values atomically before exposure.
    app_provenance_repository_url: str = ""
    app_provenance_pull_request_number: str = ""
    app_provenance_commit_sha: str = ""
    app_provenance_actions_run_id: str = ""
    # Produced by the same build-identity-contract output consumed by the frontend.
    # Empty is only a local-development fallback; deploy writes the full build identity.
    app_version: str = ""
    # The two webhook limits of rule 12(c) (`reservations-webhooks` design D6). Two and not one,
    # because they defend against opposite things and a single number cannot serve both.
    #
    # The per-token limit is GENEROUS: it protects the table from a provider whose legitimate
    # traffic runs away. A provider sends from few IPs on behalf of MANY tenants, so a limit on
    # the good traffic keyed by IP would throttle every tenant at once — which is why this one is
    # keyed by token, i.e. per tenant.
    #
    # The per-IP limit is STRICT and applies **only to requests that failed authentication**. That
    # is what makes probing for a route token cost something (R3.4) without the legitimate
    # provider ever meeting it.
    #
    # Both carry a default because neither is a secret (rule 8 of `steering/security.md`). There is
    # deliberately no `webhook_max_body_bytes`: the body ceiling is already `request_max_bytes`,
    # applied to all of `/api/v1/` by `MaxBodySizeMiddleware` before routing (design D5).
    webhook_rate_limit_per_minute: int = 120
    webhook_probe_limit_per_minute: int = 20

    # The guest portal (`guest-portal-api` design D3, D6, D9). Four tunables, none of them a
    # secret, so all four carry a default (rule 8 of `steering/security.md`).
    #
    # `guest_portal_token_grace_days` is the whole of R1.3: there is no `expires_at` column,
    # so the window is derived at authorisation time as "up to midnight UTC of
    # `check_out_date` + this many days" (D3). Deriving it rather than storing it is what
    # makes a stay that moves — or is cancelled — take effect immediately instead of on the
    # next sweep. ASSUMPTION: the window closes at midnight **UTC**, not in the property's
    # timezone; at two days of grace the worst-case skew is two hours out of forty-eight,
    # and using the property's zone would mean reading it before a tenant is known.
    guest_portal_token_grace_days: int = 2
    # Two limits, asymmetric on purpose, and the reasoning is NOT the webhook one above even
    # though the shape is (D6). The per-token limit is generous and charged **after** a
    # successful authorisation. It is **one budget shared by every portal route** — six of them
    # since `guest-portal-messaging` added `GET`/`POST /guest/messages/{token}`, recounted
    # against `portal_router.py` rather than incremented — which is what makes the polling of
    # that change's thread a cost the other routes feel. And for `POST /guest/incident`, which
    # is deliberately not idempotent (D13), it is the only thing bounding how many `incidents`
    # rows one stay can produce.
    guest_portal_rate_limit_per_minute: int = 60
    # The per-IP limit is strict and counted **only over failed authorisations**, asked
    # before any lookup — that is what makes guessing a token cost something (R2.4). Keyed by
    # IP rather than by token because a failed authorisation has no token to key on; and a
    # single shared limit over all traffic was rejected because a hotel's WiFi puts every
    # one of its guests behind one address.
    #
    # "Before any lookup" and not "before any work": on `POST /guest/checkin` the body is
    # parsed and validated before the route function runs at all, so a malformed one is a
    # `422` that spends nothing. Bounded by the body ceiling and identical whatever the
    # token — measured by the security panel of section 6, which found the docstrings
    # claiming the stronger thing.
    #
    # KNOWN LIMIT, measured by the security panel of section 6: the *counter* is only fed by
    # failures, as R2.4 requires, but the *gate* is consulted on every request. So once an
    # address has spent this budget, a guest holding a perfectly good token from behind the
    # same NAT is refused for the rest of the window. Kept deliberately — it is the order the
    # section 5 panel made binding and the one `webhooks_router.py` already ships — and
    # recorded in `design.md` D6 as a roadmap candidate rather than left to be rediscovered.
    guest_portal_probe_limit_per_minute: int = 20
    # Where a guest is told to ask for help (R3.1, D9). A configuration constant and not a
    # row: reading a support contact from the database would be one join away from exposing
    # whoever staffs it, and this is served to the open internet. Free text, because what
    # goes in it — a phone number, an address, a URL — is the operator's decision and the
    # portal only renders it. `None` means the field is served as `null` and the frontend
    # shows no help card; it is the honest default for an installation that has not chosen
    # one, not a placeholder.
    guest_portal_support_channel: str | None = None

    # Notification delivery (change `access-notifications`, design D4). No credential here:
    # the MVP adapters are a console logger and two mocks (PRD §14's channel table), and the
    # real WhatsApp/SMTP keys are already reserved by rule 8 of `steering/security.md`.
    #
    # `notification_max_attempts` is what bounds duplicates. The dispatcher records the attempt
    # BEFORE calling the adapter, so a process that dies mid-send re-sends at most until this
    # ceiling instead of for ever — at-least-once, acotado, which is the trade design D4 takes
    # in exchange for not adding a `SENDING` state and its stuck-row failure mode.
    #
    # **No backoff setting, deliberately**: `notification_logs` has no column for "next attempt
    # at", and adding one to pace a console logger would be schema invented ahead of a need.
    # A failed row is retried on the next tick until the ceiling. Revisit when a real SMTP
    # adapter lands (`hardening-release`), which is also when rate limits start to matter.
    notification_max_attempts: int = 3
    # How many rows one run drains per tenant. The job runs every minute, so a backlog drains
    # in slices instead of in one transaction that holds row locks for as long as the slowest
    # provider takes.
    notification_batch_size: int = 100

    # Channex staging (change `channex-staging-adapter`, design D3/D4). Only
    # `cli/pms_sync.py --provider channex` reads these; the application never does.
    #
    # The key has NO default: rule 8 of steering/security.md, and R3.2 requires the
    # command to abort naming the missing variable instead of falling back to the mock.
    channex_api_key: str = ""
    # Defaults to STAGING on purpose: this adapter is a dev/validation tool (ADR 0006 keeps
    # Beds24 as the MVP provider), so a misconfiguration must land on staging and never on
    # a production Channex account that could be talking to real OTA listings.
    channex_base_url: str = "https://staging.channex.io/api/v1"
    # Channex pages with a default `limit` of 10, so a sync MUST paginate. The cap exists
    # so a provider bug reporting an ever-growing `total` cannot spin forever; reaching it
    # raises rather than truncating (design D6) — silently returning a short list inside a
    # sync is indistinguishable from "the PMS had nothing more".
    channex_max_pages: int = 50
    channex_page_limit: int = 100
    channex_timeout_seconds: float = 30.0

    # Beds24 (change `pms-beds24-adapter`, design D2). **No credential here, deliberately.**
    # Beds24's refresh token is an ACCOUNT credential stored encrypted in `pms_credentials` and
    # governed by rule 3 of steering/security.md; `BEDS24_REFRESH_TOKEN` exists only for the
    # measurement bench in `scripts/`, which rule 8 covers. Two homes for one credential is how
    # one of them stops being rotated.
    #
    # No `beds24_base_url` either: the base URL and the host allowlist are constants in
    # `infrastructure/beds24/client.py`. Channex has one because its default points at staging,
    # which is what stops a mistake reaching a live account — Beds24 has **no staging
    # environment**, so a configurable base would be a lever with no use case, guarding a
    # credential that grants write access to every property of the account.
    beds24_max_pages: int = 50
    beds24_page_limit: int = 100
    beds24_timeout_seconds: float = 30.0

    # Object storage for the `S3` adapter (change `object-storage-provisioning`, design D4).
    # Three settings and no credentials: `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` travel by
    # boto3's standard chain (environment, instance role), which is what rule 8 of
    # `steering/security.md` and `sdd/specs/file-storage.md` already require — reading them as
    # fields would put the secret inside an object any debug `repr` prints.
    #
    # All three default to empty, and that default is what makes merging this change inert
    # (R3.1): `LOCAL` is untouched and an `S3` tenant keeps failing loudly with
    # `StorageWriteError` instead of silently falling back (R3.3).
    #
    # An empty `s3_endpoint_url` means "let boto3 resolve the AWS endpoint" (R3.4), so pointing
    # at AWS is *configuring nothing* and pointing at OCI, R2 or MinIO is configuring a URL.
    # The provider active in `dev` and the value each setting takes per provider are in
    # `docs/adr/0008-object-storage-provider-dev.md`.
    s3_bucket: str = ""
    s3_region: str = ""
    s3_endpoint_url: str = ""

    # Which storage the bootstrap CLI converges the tenant's `TenantConfig` onto
    # (`object-storage-provisioning` design D10, R6.1). It is the **seed** route into `S3`, and
    # deliberately the only one: R5.4 of `user-management` keeps `storage_type` out of the
    # `PATCH` of `TenantConfig`, because moving a tenant that already has photos would point it
    # at a store where those photos are not.
    #
    # `LOCAL` by default, which is what keeps R6.5 true by construction: the column default and
    # this default agree, so a tenant created by any route is born `LOCAL`.
    #
    # Only `app/cli/bootstrap.py` reads it, and the deploy passes it inline
    # (`docker compose exec -e BOOTSTRAP_STORAGE_TYPE=S3 …`) rather than through the `.env`,
    # which the deploy truncates on every run.
    bootstrap_storage_type: str = "LOCAL"

    bootstrap_tenant_name: str = ""
    bootstrap_tenant_billing_email: str = ""
    bootstrap_owner_name: str = ""
    bootstrap_owner_email: str = ""
    bootstrap_owner_password: str = ""
    bootstrap_manager_name: str = ""
    bootstrap_manager_email: str = ""
    bootstrap_manager_password: str = ""

    # The third bootstrap seed (`super-admin-identity` R5.1): a `SUPER_ADMIN` with no
    # tenant, so the identity model is verifiable end to end and not just declarable in
    # the schema. Same pattern as the eight above — no defaults, real passwords only
    # (steering/security.md #8).
    bootstrap_super_admin_name: str = ""
    bootstrap_super_admin_email: str = ""
    bootstrap_super_admin_password: str = ""

    # Demo dataset (`make seed-demo`, change `seed-data-demo` design D4). Only the two
    # operational accounts: the owner and the manager are whoever BOOTSTRAP_* already named,
    # resolved by role, so re-declaring them here would let the two declarations disagree.
    # Neither password can be echoed by a validation failure, and that holds whatever these
    # fields are named: `_load_settings` formats `errors(include_input=False)`, so no
    # submitted value reaches the message. There is no `*_password` pattern anywhere in this
    # module, and reading the protection off the field name would be worth nothing twice over
    # — it would make a future `seed_*_secret` look unprotected, and make renaming a field
    # look like a fix.
    seed_cleaner_name: str = ""
    seed_cleaner_email: str = ""
    seed_cleaner_password: str = ""
    seed_technician_name: str = ""
    seed_technician_email: str = ""
    seed_technician_password: str = ""

    # The single password of the four demonstration accounts (`make demo-reset`, change
    # `demo-user` design D3). No default, exactly like the BOOTSTRAP_*/SEED_* settings above: a
    # default here would be a known credential shipped in the tree, and the demo tenant lives in
    # a publicly reachable environment. Its floor is `PASSWORD_MIN_LENGTH`, checked by
    # `app/cli/demo_reset.py:build_plan` before any transaction opens rather than by a
    # `field_validator` — a short value has to fail the command, not refuse to boot the whole
    # application, which would take the API down with it.
    demo_account_password: str = ""

    # Both secret checks are FIELD validators, not model validators, and that is a security
    # property rather than a style choice. A `model_validator(mode="after")` reports the whole
    # settings input as the offending value, so any one failure printed every other secret in
    # the dict: a whitespace-padded signing key dumped a valid, live `encryption_key`, and an
    # invalid encryption key dumped `POSTGRES_PASSWORD`, `CHANNEX_API_KEY` and the bootstrap
    # passwords. A field validator scopes that value to its own field.
    #
    # `_default_database_url` below stays a model validator because it genuinely needs several
    # fields — it is safe there only because it cannot raise.
    @field_validator("jwt_secret_key")
    @classmethod
    def _reject_whitespace_jwt_secret(cls, value: str) -> str:
        if len(value.strip()) < 32:
            raise ValueError(
                "jwt_secret_key must have at least 32 non-whitespace characters"
            )
        return value

    @field_validator("encryption_key")
    @classmethod
    def _reject_invalid_encryption_key(cls, value: str) -> str:
        # Checked here rather than with `Field(min_length=44)` because length is not the
        # property that matters: a 44-character string that is not base64url of 32 bytes
        # fails later, inside `Fernet(...)`, at the first attempt to read a credential —
        # which is a runtime failure on the sync path instead of a refusal to boot.
        #
        # Validated with the standard library on purpose, so `config.py` does not import
        # `cryptography`: this module is imported by `alembic/env.py` and by every entry
        # point, and the check needs no more than decoding 32 bytes.
        key = value.strip()
        try:
            raw = base64.urlsafe_b64decode(key)
        except (binascii.Error, ValueError) as error:
            raise ValueError(
                "encryption_key must be base64url-encoded 32 bytes "
                "(generate with: openssl rand 32 | base64 | tr '+/' '-_')"
            ) from error
        if len(raw) != FERNET_KEY_BYTES:
            # The shape is repeated here rather than only in the branch above because this is
            # the branch a hex key lands in: "0" * 64 is valid base64url and decodes cleanly
            # to 48 bytes, so the reader who copied `openssl rand -hex 32` from the signing
            # key sees this message and not the other one.
            raise ValueError(
                f"encryption_key must be base64url-encoded {FERNET_KEY_BYTES} bytes; "
                f"this value decodes to {len(raw)} "
                "(generate with: openssl rand 32 | base64 | tr '+/' '-_')"
            )
        return value

    @field_validator("bootstrap_storage_type")
    @classmethod
    def _reject_unknown_storage_type(cls, value: str) -> str:
        """R6.1 — refuse at boot, not at the `INSERT`.

        An unknown value would otherwise reach `TenantConfigModel.storage_type` and fail inside
        the driver, after the bootstrap transaction has already created a tenant and hashed two
        passwords. Validated against the enum itself rather than a copied list, so adding a
        storage type never leaves a second, stale enumeration behind.
        """
        candidate = value.strip().upper()
        allowed = [member.value for member in StorageType]
        if candidate not in allowed:
            raise ValueError(
                f"bootstrap_storage_type must be one of {', '.join(allowed)}; got {candidate!r}"
            )
        return candidate

    @model_validator(mode="after")
    def _default_database_url(self) -> "Settings":
        # Docker Compose overrides this with the `postgres` hostname (see
        # docker-compose.yml); this default lets host-side commands
        # (`cd backend && uv run pytest`) reach Postgres via the published
        # port, since `postgres` doesn't resolve outside the compose network.
        if not self.database_url:
            self.database_url = (
                f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
                f"@localhost:5432/{self.postgres_db}"
            )
        return self

    @model_validator(mode="after")
    def _grace_must_be_shorter_than_the_token(self) -> "Settings":
        """`auth-account-recovery` R2.5 / design D7's grace amendment.

        A grace at or above the token lifetime makes NOTHING revocable, which silently turns
        the per-account cap back into a permanent discard — the suppression vector the
        amendment exists to close. A `model_validator` and not two independent `Field`
        bounds, because the constraint is between the two values: either alone can be
        perfectly reasonable.

        Same shape as D4's coupling between the password minimum and the temporary-password
        generator: a relationship the suite refuses to let drift, rather than a comment
        asking the next reader to remember it.
        """
        if self.password_reset_grace_minutes >= self.password_reset_token_minutes:
            raise ValueError(
                "PASSWORD_RESET_GRACE_MINUTES must be shorter than "
                "PASSWORD_RESET_TOKEN_MINUTES, or no recovery link is ever old enough to be "
                "retired and the per-account cap becomes a permanent discard"
            )
        return self


class ConfigurationError(RuntimeError):
    """Settings could not be loaded, reported without echoing any submitted value.

    Exists because `ValidationError.__str__()` embeds the constructor input — the whole dict
    for an `mode="after"` validator — so a truncated `ENCRYPTION_KEY` or signing key would be
    printed by the very error that refuses it. In CI the key is generated and disposable, but
    the deployed `backend`/`worker`/`beat`/`migrate` containers receive the real
    Terraform-provisioned one, and an invalid value there would land in container logs.

    R3.4 requires failing "nombrando la variable y sin imprimir su valor", which is exactly
    the pair `errors(include_input=False)` gives: the field path and the reason, no value.
    """


def _load_settings() -> "Settings":
    problems: str | None = None
    try:
        return Settings()
    except ValidationError as error:
        problems = "; ".join(
            # `loc` is the field path, `msg` the reason. `include_input=False` is the whole
            # point of this function — with it left on, this wrapper would leak exactly what
            # it exists to withhold. Note `loc` is EMPTY for a model-level validator, so the
            # field name reaches the reader through `msg`, which names it.
            f"{'.'.join(str(part) for part in item['loc']) or '(model)'}: {item['msg']}"
            for item in error.errors(include_input=False, include_url=False)
        )

    # Raised OUTSIDE the except block, and that placement is load-bearing. `raise ... from None`
    # is not enough: it only sets `__suppress_context__`, while `__context__` keeps pointing at
    # the original `ValidationError` — which still carries the whole submitted input. The
    # default traceback printer honours the suppression flag, but anything that walks the
    # exception chain (a log formatter, an error reporter) reads straight through it.
    #
    # Measured on this branch: that chained input contained the invalid key AND a
    # `bootstrap_*_password`, so this is wider than the key it was written for. Outside the
    # except block the exception is no longer being handled, so `__context__` is never set.
    raise ConfigurationError(f"invalid configuration: {problems}")


settings = _load_settings()
