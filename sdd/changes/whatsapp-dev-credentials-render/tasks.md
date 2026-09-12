# Tasks: whatsapp-dev-credentials-render

<!-- Markers, read by /sdd:run and the lifecycle gates (HTML comments, invisible
     when rendered). On a section heading: "hard" makes that section's
     implementer run on the stronger model; "panel: PASS <date> receipt:<id>"
     is written by the panel gate (reviewer_panel.py) when the section's review
     panel passes — never by hand; "panel: skipped — <reason>" records a
     deliberate skip (scaffolding, docs, config). On a task line:
     "manual" marks a task only a human can perform — run leaves it to you and
     it may travel with the PR as a deferred entry; it may sit on any line of
     the task item, not only the checkbox line. -->

## 1. Terraform — variables + Vault secrets for the four sensitive credentials

- [ ] 1.1 `infra/environments/dev/variables.tf`: add four sensitive Terraform variables —
      `whatsapp_access_token`, `whatsapp_phone_number_id`, `whatsapp_app_secret`,
      `whatsapp_webhook_verify_token` (all `type = string`, `sensitive = true`, no default) — same
      shape as `github_app_private_key`. [R1.1]
- [ ] 1.2 `infra/environments/dev/main.tf`: add four `oci_vault_secret` resources named
      `autohostai-${var.env}-whatsapp-access-token`, `-whatsapp-phone-number-id`,
      `-whatsapp-app-secret`, `-whatsapp-webhook-verify-token`, each `secret_content` =
      `base64encode(var.whatsapp_*)` — same shape as `oci_vault_secret.github_app_key`. Terraform
      only transports these; none is `random_*`-generated. [R1.2, R1.4]
- [ ] 1.3 Same file: extend the single statement of `oci_identity_policy.dev_runner_read_secrets`
      (the one enumerating the runner's `target.secret.id` clauses) with the four new secret IDs
      from 1.2, in the same apply that creates them — mirrors the pattern already used for the
      tunnel token, the four media secrets and the six `SMTP_*`. No new IAM resource-type grant is
      needed: `manage secret-family in tenancy` and `manage policies` already cover creating
      `oci_vault_secret` and extending this policy (same conclusion `infra-dev-terraform.md`
      records for `ingress-https-dev`'s single secret + policy extension — verify this still holds
      by reading `infra/environments/dev/iam-policy.md` before assuming no admin step is needed).
      [R1.3]
- [ ] 1.4 `terraform fmt -check -diff` and (`terraform init -backend=false && terraform validate`)
      in `infra/environments/dev/` — no live `plan`/`apply` here (Post-merge operational steps,
      below). [R1]

## 2. GitHub Actions — wiring the four secrets into `terraform apply`

- [ ] 2.1 `.github/workflows/infra-dev.yml`: add four `TF_VAR_*` mappings —
      `TF_VAR_whatsapp_access_token`, `TF_VAR_whatsapp_phone_number_id`,
      `TF_VAR_whatsapp_app_secret`, `TF_VAR_whatsapp_webhook_verify_token` — each sourced from a
      new GitHub Actions secret of the same suffix (`secrets.WHATSAPP_ACCESS_TOKEN` etc.), in both
      the `plan` and `apply` jobs' `env:` blocks — same pattern and same two jobs as
      `TF_VAR_github_app_private_key`. Do not register these secrets with the `github` Terraform
      provider (R2.2 — out of scope, `infra-github-iac`). [R2.1, R2.2]

## 3. Deploy pipeline — render the five `WHATSAPP_*` into the runtime `.env`

- [ ] 3.1 `.github/workflows/deploy-dev.yml`'s "Render .env" step: add four `read_secret_by_name`
      calls for `autohostai-${ENV}-whatsapp-access-token`, `-whatsapp-phone-number-id`,
      `-whatsapp-app-secret`, `-whatsapp-webhook-verify-token` — same fail-fast contract as the
      existing by-name reads (tunnel token, media, SMTP). [R3.1, R3.5]
- [ ] 3.2 Same step: read `WHATSAPP_PROVIDER` from a new repo variable
      (`${{ vars.WHATSAPP_PROVIDER }}`, added to the step's own `env:` block) — same pattern as
      `PUBLIC_HOSTNAME`, no Vault involved. [R3.2]
- [ ] 3.3 Same step: write the five lines to `$RUNTIME_ENV_FILE` —
      `WHATSAPP_PROVIDER=${WHATSAPP_PROVIDER:-}`, `WHATSAPP_ACCESS_TOKEN=...`,
      `WHATSAPP_PHONE_NUMBER_ID=...`, `WHATSAPP_APP_SECRET=...`,
      `WHATSAPP_WEBHOOK_VERIFY_TOKEN=...` — unset `vars.WHATSAPP_PROVIDER` renders an empty value,
      matching `.env.example`'s documented default (`config.py` resolves blank/absent identically
      to `"mock"`). [R3.3, R3.4]

## 4. Compose passthrough — the rendered `.env` reaching the containers that use it

- [ ] 4.1 `docker-compose.deploy.yml`: add the five `WHATSAPP_*` (`${VAR:-}`, no `:?`) to
      `backend`'s `environment:` block — it builds `WhatsAppCloudAdapter`/`outbound_registry()` for
      the inbound webhook and the synchronous human-reply send
      (`messaging/api/dependencies.py`). [R4.1, R4.4]
- [ ] 4.2 Same file: add the same five to `worker`'s `environment:` block — it executes
      `backend/app/scheduler/whatsapp_tasks.py`'s background sends via `outbound_registry()`.
      [R4.2, R4.4]
- [ ] 4.3 Same file: do NOT add them to `beat`'s `environment:` block — same reasoning already
      documented there for `SMTP_*` (beat only schedules, never runs a task body). [R4.3]

## 5. Verification

- [ ] 5.1 `terraform fmt -check -diff` and `terraform validate` (from `infra/environments/dev/`,
      `terraform init -backend=false` first) pass clean.
- [ ] 5.2 `grep -rn "WHATSAPP_ACCESS_TOKEN=.\+\|WHATSAPP_APP_SECRET=.\+\|WHATSAPP_PHONE_NUMBER_ID=.\+\|WHATSAPP_WEBHOOK_VERIFY_TOKEN=.\+" .github .env.example infra` finds no committed real value (every match is either a `${...}` reference or the bare, unset name).
- [ ] 5.3 Full backend test suite unaffected: `docker compose exec backend uv run pytest` (this
      change touches no `backend/` code — confirms no regression).
- [ ] 5.4 Manual: after the next real `infra-dev` apply and `deploy-dev` run, confirm the four new
      Vault secrets exist and the VM's `.env` carries all five `WHATSAPP_*`. <!-- manual -->

## Post-merge operational steps (not gated by `mark-local-verified`)

Same shape as `smtp-delivery-adapter`'s: `infra-dev.yml`'s `plan`/`apply` jobs are gated to `main`,
so these cannot run before merge. Local review certifies the Terraform/workflow code; these confirm
it live.

1. An admin/operator sets the four new GitHub Actions secrets (`WHATSAPP_ACCESS_TOKEN`,
   `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`) with the
   real Meta App values, and the repo variable `WHATSAPP_PROVIDER` when ready to flip dev to
   `meta` (left unset otherwise — resolves to `mock`, same as today).
2. Run `infra-dev.yml`'s `apply` on `main`; confirm the four `oci_vault_secret` resources are
   created and the runner policy extension applies without an unanticipated IAM statement (per
   1.3's note — verify against `iam-policy.md` if it fails).
3. Confirm the next `deploy-dev.yml` run renders all five `WHATSAPP_*` into the VM's `.env` and
   that `docker compose exec backend env | grep WHATSAPP` (and same for `worker`) shows them
   inside the containers.

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
