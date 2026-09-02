# Blocked items — smtp-delivery-adapter

- **phase**: run
  **type**: decision
  **what & why**: Task 5.1's tenancy-level IAM grant (`Allow group autohostai-dev-terraform to manage email-family in tenancy`, documented in `infra/environments/dev/iam-policy.md`) must be applied by a tenancy admin in the OCI console before the first `terraform apply` that declares `oci_email_email_domain.smtp`/`oci_email_dkim.smtp`/`oci_email_sender.smtp` — same precedent as the two prior IAM widenings (`app-deploy-dev`, `object-storage-provisioning`). I have no OCI credentials and applying a tenancy-level IAM policy is not something to do autonomously regardless.
  **resume**: after the grant is applied out-of-band, run `terraform plan`/`terraform apply` in `infra/environments/dev/` (task 7.3), then continue with `/sdd:run smtp-delivery-adapter 7`.

- **phase**: run
  **type**: decision
  **what & why**: Task 7.3 (`terraform apply` against the live dev workspace) requires real OCI/Cloudflare credentials I don't have, and applying infra to a shared dev environment is a consequential, hard-to-reverse action that needs an explicit go-ahead regardless of credentials — not something to do without the user's confirmation.
  **resume**: once applied, confirm the SPF/DKIM records appear in Cloudflare and the Vault holds all six `autohostai-dev-smtp-*` secrets, then continue with `/sdd:run smtp-delivery-adapter 7`.

- **phase**: run
  **type**: decision
  **what & why**: Tasks 7.4 (trigger `app-deploy-dev`, confirm "Render .env" succeeds with the six SMTP values) and 7.5 (manual end-to-end password-reset send through the real relay) both depend on 7.3 having run and on DNS propagation after it, and involve triggering a real deploy / sending a real email — the user's call on timing, not something to do autonomously.
  **resume**: after DNS propagation, trigger `app-deploy-dev`, confirm the rendered `.env` on the VM has all six `SMTP_*` values, then request a password reset in dev with SMTP configured and confirm delivery. Once both pass, run `/sdd:run smtp-delivery-adapter 7` to check them off, then `/sdd:review smtp-delivery-adapter`.
