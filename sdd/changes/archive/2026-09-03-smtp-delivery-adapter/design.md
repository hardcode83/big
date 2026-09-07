# Design: smtp-delivery-adapter

## Context

`backend/app/notifications/infrastructure/adapters.py` registers `ConsoleEmailAdapter` for `EMAIL`/`CONSOLE` in `adapter_registry()` (a plain eager `dict`, called fresh at every use — `auth/api/dependencies.py:254` per request, `scheduler/tasks.py:168` every scheduler tick). It implements the `NotificationAdapter` `Protocol` (`domain/ports.py`): `async def send(...) -> NotificationResult`, never raises for a delivery failure, blank recipient is `INVALID_RECIPIENT`. `NotificationResult` (`domain/results.py`) is a closed dataclass — `delivered: bool` + `error_code: NotificationErrorCode | None` — with **no string field**, by design, so provider text can never reach `notification_logs.last_error` (rule 11 of `steering/security.md`). `use_cases.py`'s `_deliver` already wraps the adapter call in `try/except Exception` and converts any raise to `ADAPTER_ERROR`, anticipating a real adapter whose client library raises (`# ... but that is prose, and the next adapter to land is a real SMTP one`). `recovery.py` (password reset) does the same at its own call site.

`backend/app/core/config.py` deliberately declares **no** `SMTP_*` settings today — its own comment says why: rule 8 requires a secret *in use* to fail fast when absent, and none was in use. `.env.example` reserves the six names (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS`) with no value. `notification-channel-routing` (merged, PR #143) means `channel_resolver.py` now adds `EMAIL` to real notifications whenever the tenant flag is on and the contact is usable — this change is what finally reads those six names.

The deploy pipeline (`specs/app-deploy-dev.md`, `.github/workflows/deploy-dev.yml`) already has a working pattern for a secret added **after** the VM's `cloud-init` ran: `/etc/autohostai-deploy.env` (the file cloud-init writes) is `ForceNew` and Terraform cannot rewrite it on the live VM, so anything added later — the Cloudflare tunnel token, the four object-storage media secrets, `demo_account_password` — is read **by name** (`get-secret-bundle-by-name`) instead of by the OCID baked in at creation. `infra/environments/dev/main.tf`'s `oci_identity_policy.dev_runner_read_secrets` enumerates every readable secret **by OCID** in one statement (`design D4` of `app-deploy-dev`); a secret invisible there is invisible to the runner regardless of name.

## Decisions

### D1 — `SMTPEmailAdapter` lives in `adapters.py`, selected by `settings.smtp_host`

**Chosen:** add `SMTPEmailAdapter` as a new class in the same `backend/app/notifications/infrastructure/adapters.py`, next to `ConsoleEmailAdapter`. `adapter_registry()` imports the module-level `settings` singleton (`from app.core.config import settings`, the same object `auth/api/dependencies.py` already reads directly) and registers `SMTPEmailAdapter` for `EMAIL`/`CONSOLE` when `settings.smtp_host` is non-empty; otherwise it keeps registering `ConsoleEmailAdapter`, unchanged. `ConsoleEmailAdapter` is not deleted — it stays the behavior for any deployment that has not configured SMTP (R2.1).

Rejected: inject SMTP config through `adapter_registry()`'s parameters (mirroring `ConfiguredFileStorageFactory`'s constructor injection) — that pattern exists there to stop a *cached, cross-tenant* instance from leaking state between tenants; `adapter_registry()` builds a fresh dict per call with deployment-wide (not per-tenant) config, so there is nothing to protect against, and it would force both call sites (`auth/api/dependencies.py`, `scheduler/tasks.py`) to thread six new parameters through for no behavioral gain.

### D2 — Fail-fast boundary: at registry construction, on partial config only

**Chosen:** six new `Settings` fields, all with empty/permissive defaults (`smtp_host: str = ""`, `smtp_port: int = 0`, `smtp_username: str = ""`, `smtp_password: str = ""`, `smtp_from_email: str = ""`, `smtp_use_tls: bool = True`) — importing the module never fails, matching R2.1. Inside `adapter_registry()`: if `smtp_host` is set, `smtp_port`, `smtp_from_email`, `smtp_username` and `smtp_password` must all be non-empty too, or the function raises a new `SMTPConfigurationError(NotificationDomainError)` (`domain/exceptions.py`) naming the missing key. This is the same shape as `ConfiguredFileStorageFactory.storage_for()` raising `StorageWriteError` when `S3` is the tenant's type but no bucket is configured — refuse loud, at the point something is actually asked to use the broken config, never at import.

**Amendment (found during `/sdd:run`'s section 5-6 security review, not anticipated at design time):** the same check also refuses `smtp_use_tls = False` whenever `smtp_host` is set — `client.login` (`SMTPEmailAdapter._send_sync`) is gated on a username being present, not on TLS, so a relay with credentials and `smtp_use_tls=False` would put `SMTP_PASSWORD` and every recipient's mail on the wire in cleartext. Refusing it here keeps that state unrepresentable rather than trusting an operator not to disable TLS on a relay that requires auth. This narrows R2.2's literal "(cuando SMTP_USE_TLS lo requiera)" phrasing to unconditional for this field too — accepted because the chosen provider (D6, OCI Email Delivery) always requires both TLS and auth, so no real deployment shape is lost.

Because both call sites invoke `adapter_registry()` uncaught, a partial config surfaces as an unhandled exception on every password-reset request and every scheduler tick until fixed — deliberately loud (R2), not a background log line nobody reads.

Rejected: a Pydantic model-validator on `Settings` requiring the four fields together — rejected because that fires at import for **every** deployment, including ones that never set `SMTP_HOST` at all, which is exactly the "exigir SMTP mientras haya despliegues sin email" failure the proposal calls out.

### D3 — SMTP client: stdlib `smtplib` in a thread, no new dependency

**Chosen:** `smtplib.SMTP`/`SMTP_SSL` (stdlib) with a bounded `timeout=`, called through `asyncio.to_thread` so the blocking network call never blocks the event loop — exactly what `ports.py`'s docstring already anticipates ("a real SMTP or HTTP adapter would block the event loop for the duration of a network round trip"). No third-party SMTP client.

Rejected: `aiosmtplib` (native async) — a real dependency choice, not a style preference, but at this volume (`notification_batch_size=100`/tick, two dev properties) the stdlib client in a thread costs nothing measurable and avoids a new dependency that would trip the "dependencias nuevas" entry of `steering/security.md`'s extra-review triggers for no offsetting benefit.

### D4 — Exception → `NotificationErrorCode` mapping

**Chosen**, inside `SMTPEmailAdapter.send`, all caught (never re-raised, per `NotificationAdapter.send`'s contract):

| `smtplib` exception | `NotificationErrorCode` |
|---|---|
| `SMTPRecipientsRefused`, `SMTPSenderRefused` | `INVALID_RECIPIENT` |
| `TimeoutError` (the client's own `timeout=`) | `TIMEOUT` |
| anything else (`SMTPAuthenticationError`, `SMTPConnectError`, `SMTPServerDisconnected`, `SMTPHeloError`, `SMTPDataError`, `SMTPNotSupportedError`, `OSError`, …) | `ADAPTER_ERROR` |

No new `NotificationErrorCode` member — `ADAPTER_ERROR` is documented as the deliberately coarse catch-all and this change does not widen the enum.

### D5 — "SENT" documented as "relay accepted", nothing new to build

**Chosen:** a docstring change only — `SMTPEmailAdapter`'s class docstring and (if it does not already) `NotificationResult.ok()`'s own docstring state plainly that `delivered=True` means the relay returned 2xx, not that a human read the mail. No new column, no new status, no bounce/webhook handling (Out of scope in the proposal). R4 has no other design implication.

### D6 — Provider: **OCI Email Delivery**, not a third-party relay

**Chosen**, after researching the alternative the user raised: OCI's own transactional email service (`Email Delivery`), confirmed available in `eu-frankfurt-1` (this tenancy's region) and fully driven by the `oracle/oci` Terraform provider this project already uses — no new provider, no new external account, no new vendor for `steering/security.md`'s dependency-review trigger to look at:

- `oci_email_email_domain` — registers the sending domain (a subdomain of `autohostai.digitalsec.work`, e.g. `mail.autohostai.digitalsec.work`, so DKIM/SPF scope to mail traffic only).
- `oci_email_dkim` — generates the DKIM key pair **inside the apply** and exports `cname_record_value`/`dns_subdomain_name` as plain Terraform outputs. No dashboard step, no value to copy by hand.
- `oci_email_sender` — the "approved sender" (`noreply@mail.autohostai.digitalsec.work`), self-service and Terraform-managed; OCI's docs describe no sandbox/manual-approval wait comparable to SES's.
- `oci_identity_smtp_credential` — generates the SMTP username/password **for an IAM user**, inside the apply, the same "provider issues it, Terraform captures it" shape `oci_identity_customer_secret_key.media` already established for the object-storage credentials (`security.md` §8's fourth named exception). The service user can be the existing `media` user or a new `smtp` one — call decided in `tasks.md`, no design implication either way.

This means **R6 is satisfied more strongly than the proposal wrote it**: not merely "no new GitHub Actions secret" (R6.1) but no external bootstrap secret at all — `SMTP_USERNAME`/`SMTP_PASSWORD` never exist outside Terraform state and the Vault, matching exactly how `media_access_key_id`/`media_secret_access_key` already work. `SMTP_HOST`/`SMTP_PORT`/`SMTP_USE_TLS` become literal Terraform values for OCI's known SMTP endpoint (`smtp.email.eu-frankfurt-1.oci.oraclecloud.com:587`, STARTTLS); `SMTP_FROM_EMAIL` is `oci_email_sender.smtp.email_address`.

Rejected: **Brevo/Resend/SES** (the proposal's original menu) — all three add a vendor this project has no prior relationship with (SES excepted, but SES's SMTP credentials still require a manual "request production access" approval wait Oracle's own service does not, and would be a second cloud provider's IAM surface for one adapter). Rejected once OCI Email Delivery was confirmed to exist, cover the region, and need no comparable sandbox step — the "no SDK nuevo" and "sin pasos manuales" criteria the proposal set both favor the provider already in use over a new one.

### D7 — Deploy secrets follow the media-secret shape exactly (by name, not by OCID), DKIM feeds Cloudflare directly

**Chosen:** the six `SMTP_*` values enter dev the same way the four `media_*` values and the tunnel token already do, because they share the same constraint — added **after** `cloud-init` last wrote `/etc/autohostai-deploy.env`, so they must resolve **by name**, never by the OCID that file would have to carry. D6 already removes the need for any new GitHub secret or `TF_VAR_*` here:

- All six become `oci_vault_secret` resources created in the **same apply** as `oci_identity_smtp_credential`/`oci_email_sender`/`oci_email_dkim`: `smtp_username`/`smtp_password` read straight off the credential resource's own attributes, `smtp_host`/`smtp_port`/`smtp_use_tls`/`smtp_from_email` are literals/resource attributes (D6). Named deterministically `autohostai-${var.env}-smtp-{host,port,username,password,from-email,use-tls}` (same derivation as `autohostai-${env}-cloudflare-tunnel-token`).
- `oci_identity_policy.dev_runner_read_secrets`'s single `statements` entry gains the six new `target.secret.id = ...` clauses, in the same `apply` that creates the secrets — the same mitigation already applied for the four media secrets, so a forgotten OCID fails loud at "Render .env" instead of round-tripping.
- `.github/workflows/deploy-dev.yml`'s "Render .env" step gains six `read_secret_by_name` calls (`autohostai-${ENV}-smtp-host`, `-smtp-port`, `-smtp-username`, `-smtp-password`, `-smtp-from-email`, `-smtp-use-tls`) and six new lines in the rendered `.env`.
- **No change to `infra-dev.yml`** — there is no new secret to inject as `TF_VAR_*`, unlike `github_app_private_key`/`cloudflare_api_token`.

**DKIM and SPF** (closing R5.2): two new `cloudflare_record` resources in the same `main.tf` — SPF as a `TXT` on the domain (`v=spf1 include:rp.oracleemaildelivery.com ~all`, or the `eu.` variant OCI documents for `eu-frankfurt-1`) and DKIM as a `CNAME` whose `name`/`value` are `oci_email_dkim.smtp.dns_subdomain_name`/`cname_record_value` — **a direct resource reference, not a copied-in value**. The existing `cloudflare_api_token` already carries `Zone | DNS | Edit` (`variables.tf:187`), so no permission or token change. Because the DKIM value now comes from another Terraform resource in the same apply rather than a human reading a provider dashboard, **there is no bootstrap-irreducible step left for this change at all** — the only prerequisite from `infra.md`'s irreducible list (domain/DNS zone ownership, Cloudflare token) was already satisfied before this change started.

Rejected: configuring the records by hand in the Cloudflare dashboard — flatly against the IaC-first norm (`steering/infra.md`, "Prohibido configurar a mano... salvo el bootstrap irreducible"), and with OCI supplying the DKIM value programmatically there is no longer even a value that would justify the exception. Also rejected: a new GitHub Actions secret consumed directly by the deploy workflow (bypassing Terraform/Vault) — would be the one runtime credential in this project not flowing through the Vault, and D6 makes it unnecessary besides.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Adapter | `backend/app/notifications/infrastructure/adapters.py` | New `SMTPEmailAdapter` class; `adapter_registry()` selects it when `settings.smtp_host` is set (D1); module docstring's channel table updated (no longer "SMTP arrives with `hardening-release`"). |
| Domain | `backend/app/notifications/domain/exceptions.py` | New `SMTPConfigurationError(NotificationDomainError)` (D2). |
| Config | `backend/app/core/config.py` | Six new `Settings` fields, all empty/permissive defaults (D2); the existing "NO `SMTP_*` settings" comment is rewritten — it is no longer true and would mislead the next reader. |
| Stale comments | `backend/app/auth/api/dependencies.py:246`, `backend/app/cli/demo_reset.py:81`, `backend/app/cli/reset_password.py:5`, `backend/app/notifications/domain/enums.py:49` | Each names `hardening-release` as where SMTP "arrives"; update to reflect this change, or drop the forward-reference now that it is no longer forward. |
| Env | `.env.example` | No value changes (R6.3) — six names stay reserved and empty; comment at line 95 no longer says "arrives with `hardening-release`". |
| Terraform | `infra/environments/dev/main.tf` | New `oci_email_email_domain`, `oci_email_dkim`, `oci_email_sender`, `oci_identity_smtp_credential` resources; six new `oci_vault_secret` resources sourced from them; six new IAM policy clauses on `dev_runner_read_secrets`; two new `cloudflare_record` resources for SPF/DKIM (D6, D7). |
| CI | `.github/workflows/infra-dev.yml` | **No change** — D6 needs no new `TF_VAR_*`/GitHub secret. |
| Deploy | `.github/workflows/deploy-dev.yml` | Six new `read_secret_by_name` calls + six new `.env` lines in "Render .env" (D7). |
| Specs | `sdd/specs/access-notifications.md`, `sdd/specs/app-deploy-dev.md` | Documented at archive time, per the proposal's Affected specs. |

## Data & interfaces

- **New `Settings` fields** (`backend/app/core/config.py`): `smtp_host: str = ""`, `smtp_port: int = 0`, `smtp_username: str = ""`, `smtp_password: str = ""`, `smtp_from_email: str = ""`, `smtp_use_tls: bool = True`.
- **New exception**: `SMTPConfigurationError(NotificationDomainError)`.
- **New class**: `SMTPEmailAdapter` implementing `NotificationAdapter` — no port change, no new method.
- **No DB migration.** No new column, no new enum member.
- **No API contract change** — nothing here is reachable through a router; `openapi.json` is untouched.
- **New Terraform resources**: `oci_email_email_domain.smtp`, `oci_email_dkim.smtp`, `oci_email_sender.smtp`, `oci_identity_smtp_credential.smtp` (or reusing the `media` user — decided in `tasks.md`), two `cloudflare_record` resources (SPF `TXT`, DKIM `CNAME`), six `oci_vault_secret` resources sourced from the above. No new Terraform `variable` and no new GitHub Actions secret (D6).
- **New Vault secrets** (dev): `autohostai-dev-smtp-{host,port,username,password,from-email,use-tls}`, read by name.

## Risks & mitigations

- **A per-request 500.** D2's fail-fast means a partially-configured SMTP breaks `POST /auth/forgot-password` (and every SLA/notification scheduler tick) until fixed, not just a log line. Mitigation: this is the intended behavior (R2), but the router must not let `SMTPConfigurationError` leak a stack trace to the anonymous caller — catch it at the router boundary and answer the same generic error FastAPI already gives for an unhandled exception; add a test asserting the response shape, not just that it 500s.
- **Thread-pool pressure.** `asyncio.to_thread` for every SMTP send competes with the default executor's thread pool; `notification_batch_size=100` bounds how many run per tick, so this is not new pressure beyond what the batch already implies.
- **OCI Email Delivery's own ceiling.** Free tier is 100 emails/day, 3000/month (confirmed 2026-09) — plenty for dev's two properties today, but unmodeled/unlimited by this change; revisit if seed-data or load testing pushes past it. Called out in Out of scope ("Backoff/pacing de reintentos SMTP").
- **Regional scoping.** OCI's approved senders and suppression list are per-region (`eu-frankfurt-1` here); a future multi-region deployment would need its own `oci_email_sender`/DKIM per region, not a shared one — not a concern for dev alone, worth a `tasks.md` note.
- **Stale forward-references.** Four files currently say "arrives with `hardening-release`" — left uncorrected they would send the next reader chasing the wrong change; tasks.md must include fixing all four (found by grep, not by memory).
- **DNS propagation.** SPF/DKIM records take time to propagate after the `apply`; the first real send in dev should happen only after propagation, not immediately after `terraform apply` returns.

## Open questions

None outstanding — the one open question this design started with (which relay provider) was resolved during the gate: **OCI Email Delivery** (D6), chosen over the proposal's original Brevo/Resend/SES menu once confirmed to cover `eu-frankfurt-1` with no new provider, no new external account and no sandbox/approval wait.
