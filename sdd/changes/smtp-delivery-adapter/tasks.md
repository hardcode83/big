# Tasks: smtp-delivery-adapter

## 1. Config foundations <!-- panel: PASS 2026-09-02 -->

- [x] 1.1 `backend/app/notifications/domain/exceptions.py`: add `SMTPConfigurationError(NotificationDomainError)`, naming the missing key in its message (D2). [R2.2]
- [x] 1.2 `backend/app/core/config.py`: add six `Settings` fields — `smtp_host: str = ""`, `smtp_port: int = 0`, `smtp_username: str = ""`, `smtp_password: str = ""`, `smtp_from_email: str = ""`, `smtp_use_tls: bool = True` — all empty/permissive so import never fails (D2). Rewrite the "NO `SMTP_*` settings" comment (~line 113-118): no longer true, would mislead the next reader. [R2.1, R2.3]
- [x] 1.3 `.env.example`: rewrite the line-95 comment (no longer "arrives with `hardening-release`"); the six names stay reserved with no value. [R6.3]

## 2. SMTPEmailAdapter <!-- panel: PASS 2026-09-02 -->

- [x] 2.1 `backend/app/notifications/infrastructure/adapters.py`: implement `SMTPEmailAdapter` (`NotificationAdapter` Protocol) — blank-recipient precondition returns `INVALID_RECIPIENT` without contacting the relay (R1.2); sends via `smtplib.SMTP`/`SMTP_SSL` (stdlib, bounded `timeout=`) called through `asyncio.to_thread` (D3); never logs `recipient_contact`/`subject`/`body` (R1.4); class docstring states `delivered=True` means the relay returned 2xx, not that a human read the mail — no new column/status, nothing else to build here (R4.1, R4.2). [R1.1, R1.2, R1.4, R4.1, R4.2]
- [x] 2.2 Same file: catch every `smtplib`/`OSError` exception inside `send` per the D4 table — `SMTPRecipientsRefused`/`SMTPSenderRefused` → `INVALID_RECIPIENT`, `TimeoutError` → `TIMEOUT`, anything else → `ADAPTER_ERROR`; 2xx response → `NotificationResult.ok()`. No new `NotificationErrorCode` member. Tests in `backend/tests/notifications/test_adapters.py` (mock `smtplib.SMTP`, no real network): 2xx → ok(), each exception family → its mapped code, and extend the existing parametrized never-logs-subject/body/recipient tests to include `SMTPEmailAdapter`. [R1.3, R3.1, R3.2, R3.3, R3.4]
- [x] 2.3 `adapter_registry()` in the same file: register `SMTPEmailAdapter` for `EMAIL`/`CONSOLE` when `settings.smtp_host` is non-empty (D1); otherwise keep registering `ConsoleEmailAdapter`, unchanged (R2.1). When `smtp_host` is set, raise `SMTPConfigurationError` naming the first missing field if any of `smtp_port`, `smtp_from_email`, `smtp_username`, `smtp_password` is empty/zero (D2) — this is also where R2.3's "no silent empty string" is enforced. Update the module docstring's channel table (no longer "SMTP arrives with `hardening-release`"). Tests: registry returns `ConsoleEmailAdapter` when `smtp_host` empty; returns `SMTPEmailAdapter` when fully configured; raises `SMTPConfigurationError` naming the right field, parametrized over each individually-missing field. [R1.1, R2.1, R2.2, R2.3]

## 3. Fail-fast boundary safety net <!-- panel: PASS 2026-09-02 -->

- [x] 3.1 Test (e.g. `backend/tests/auth/test_recovery_api.py` or a new focused test module): with `settings.smtp_host` monkeypatched to a non-empty value and another required SMTP field left empty, `POST /auth/forgot-password` answers the existing generic `NotificationDomainError` 500 envelope (`register_notification_error_handlers`, already wired in `main.py`) — assert the response body shape (`error.code == INTERNAL_ERROR`, generic message) and that no configuration detail or stack trace leaks to the caller. Confirms the design's risk mitigation needs no new router code, only this test. [R2.2]

## 4. Stale forward-references <!-- panel: PASS 2026-09-02 -->

- [x] 4.1 Update every place that names `hardening-release` as where SMTP "arrives", now that it exists here — `backend/app/notifications/infrastructure/adapters.py` (module docstring's channel table already covered by 2.3, plus `ConsoleEmailAdapter`'s own docstring), `backend/app/auth/api/dependencies.py:246`, `backend/app/cli/demo_reset.py` (~line 81), `backend/app/cli/reset_password.py` (~line 5), `backend/app/notifications/domain/enums.py` (~line 49), `backend/app/core/config.py` (~lines 253, 262 — the WhatsApp/SMTP reserved-keys comment and the backoff-revisit comment, per the proposal's Out of scope note that the backoff comment should re-point here). Verify with `grep -rn "hardening-release" backend .env.example` afterwards — no remaining hit should be about SMTP. [R1]

## 5. Infra — OCI Email Delivery, DKIM/SPF, Vault secrets <!-- panel: PASS 2026-09-02 -->

- [x] 5.1 `infra/environments/dev/iam-policy.md`: document a new tenancy-level statement, `Allow group autohostai-dev-terraform to manage email-family in tenancy`, required for `oci_email_email_domain`/`oci_email_dkim`/`oci_email_sender` — a new resource-type grant, distinct from the `manage users`/`manage groups` relaxation already documented. Note that a tenancy admin must apply it out-of-band before `terraform apply`, same precedent as the two prior ampliaciones (`app-deploy-dev`, `object-storage-provisioning`). [R5.1]
- [x] 5.2 `infra/environments/dev/variables.tf`: add `smtp_user_email` variable (mirrors `media_user_email`'s validation — IDCS rejects a new service user with no primary email). [R6]
- [x] 5.3 `infra/environments/dev/main.tf`: add `oci_identity_user.smtp` (dedicated service user, no console login, only holds the SMTP credential below) and `oci_identity_smtp_credential.smtp` bound to it — a new user rather than reusing `media`, so a leaked media S3 key never also grants mail-send capability and vice versa. [R5, R6]
- [x] 5.4 Same file: add `oci_email_email_domain.smtp` (`mail.autohostai.digitalsec.work`), `oci_email_dkim.smtp`, `oci_email_sender.smtp` (`noreply@mail.autohostai.digitalsec.work`) (D6). [R5.1]
- [x] 5.5 Same file: add two `cloudflare_record` resources — SPF `TXT` (`v=spf1 include:rp.oracleemaildelivery.com ~all`, or the `eu.` variant OCI documents for `eu-frankfurt-1`) and DKIM `CNAME` referencing `oci_email_dkim.smtp.dns_subdomain_name`/`cname_record_value` directly (D7, no copied-in value). [R5.2]
- [x] 5.6 Same file: add six `oci_vault_secret` resources named `autohostai-${var.env}-smtp-{host,port,username,password,from-email,use-tls}`, sourced from the resources above (`smtp_username`/`smtp_password` off the credential's own attributes; the rest literals/resource attributes per D6) (D7). [R6.1]
- [x] 5.7 Same file: extend `oci_identity_policy.dev_runner_read_secrets`'s single statement with the six new `target.secret.id` clauses, in the same apply that creates the secrets; mirror the change in `infra/environments/dev/iam-policy.md`'s runner-policy block. [R6.2]
- [x] 5.8 `terraform fmt` and `terraform validate` in `infra/environments/dev/` (plan/apply happen in Verification, against the live dev workspace, after 5.1's policy grant is applied). [R5, R6]

## 6. Deploy pipeline <!-- panel: PASS 2026-09-02 -->

- [x] 6.1 `.github/workflows/deploy-dev.yml`'s "Render .env" step: add six `read_secret_by_name` calls (`autohostai-${ENV}-smtp-host`, `-smtp-port`, `-smtp-username`, `-smtp-password`, `-smtp-from-email`, `-smtp-use-tls`) and six new lines in the rendered `.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS`) — same fail-fast contract as the existing calls. [R6.1, R6.2]

## 7. Verification

- [x] 7.1 Full backend test suite: `docker compose exec backend uv run pytest` — 9716 passed, 41 skipped, 0 failed.
- [x] 7.2 Static tooling: `uv sync --frozen && uv run pyright .` (from `backend`) — 838 pre-existing errors across the repo, none in any file this change touches (confirmed by grep against the pyright output).
- [ ] 7.3 Apply Terraform to dev (`terraform apply` in `infra/environments/dev/`) once 5.1's IAM grant is live; confirm the SPF/DKIM records appear in Cloudflare and the Vault holds all six `autohostai-dev-smtp-*` secrets.
- [ ] 7.4 After DNS propagation, trigger `app-deploy-dev` and confirm "Render .env" succeeds with the six SMTP values present in the deployed `.env`.
- [ ] 7.5 Manual end-to-end in dev: request a password reset with SMTP configured and confirm the mail is delivered through the real relay — the first real `EMAIL`→real-recipient path this change measures (R7.1).
