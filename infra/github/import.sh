#!/usr/bin/env bash
# import.sh — adoption procedure for the GitHub-side resources of `infra/github/`.
#
# SCOPE: this script prints the `terraform import` commands that adopt the
# resources already in the repo (created by hand during the bootstrap irreducible
# or in earlier sections of this change). It is executed ONCE during this change
# (R3 + R5 + D6): after the import the resources live in Terraform and every
# subsequent `apply` reconciles them.
#
# SECTIONS (sección 2 declaró github_repository.this; sección 3 añadió los
# once secrets; sección 4 añade las cuatro variables — el branch protection
# de la tarea 4.3 original NO se declara: D5 se enmendó en la propia sección 4
# tras confirmar en vivo que la API la rechaza por completo en el plan Free,
# no solo el sub-bloque de reviewers; ver `sdd/changes/infra-github-iac/
# design.md` §D5 y `main.tf`):
#   2.2 — one    github_repository.this                (sección 2; import añadido en sección 5 — gap detectado por el implementer de esa sección, ver tasks.md Implementation Notes)
#   3.1 — eleven github_actions_secret.*                (sección 3, importado en commit 74d96322)
#   4.1 — four   github_actions_variable.*              (sección 4, tarea 4.2)
#
# FORMAT (correction vs. some task text):
# The provider `integrations/github` v5.45.0 accepts DIFFERENT import ID formats
# per resource kind (verified against the upstream import functions at tag
# v5.45.0 and the `terraform-provider-github` v5.45.0 README/CHANGELOG, except
# `github_repository` — the bare repo name is the provider's long-standing
# documented convention for that resource across major versions; not found in
# the locally vendored CHANGELOG, so treat as plausible-not-locally-confirmed
# and verify against the live `terraform import` error message if it rejects
# the ID):
#
#   github_repository                 <repository name>                   (bare name, no owner/colon/slash)
#   github_actions_secret.<name>      <repository>/<secret_name>          (slash)
#   github_actions_variable.<name>    <repository>:<variable_name>        (colon)
#
# The `<repository>` component is the GitHub repo name (NOT the OCID). The
# repo name is fixed to `AutoHostAI` for now (the default in `variables.tf`),
# so the produced lines all start with `AutoHostAI/...` or `AutoHostAI:...`.
#
# ORDER: alphabetical by GitHub-side identifier (per task 3.4 — interpreted as
# alphabetical by the human-facing name in the repo's Settings page). Within
# each section the lines mirror the GitHub UI order.
#
# USAGE:
#   bash infra/github/import.sh                   # prints all commands
#   bash infra/github/import.sh | bash            # runs them (only after the
#                                                  # CI workflow has populated
#                                                  # the `backend.hcl` with real
#                                                  # OCI credentials — never
#                                                  # with real credentials on
#                                                  # a developer machine)
#
# Each import consumes the external ID (the resource's name in GitHub); running
# the script a second time against an already-imported state is a no-op for
# Terraform but produces a confusing error. The script does not run the
# commands — that is the operator's call, after reading the produced lines.

set -euo pipefail

REPO="AutoHostAI"

cat <<EOF
# ============================================================================
# Import commands for the GitHub-side resources of 'infra/github/'.
# Run AFTER 'terraform init' against the real OCI backend and BEFORE
# 'terraform apply -target=<kind>.*'.
#
# Each line is idempotent against the resource in GitHub; running twice is safe
# only if the resource hasn't been re-created in the meantime.
# ============================================================================

# --- Sección 2 — one github_repository.this (R2.3 — adopts the existing repo,
# never creates it) ---
# Format: bare repository name (no owner, no colon, no slash).

terraform import github_repository.this                      ${REPO}

# --- Sección 3 — eleven github_actions_secret.* (R3.1) ---
# Format: <repository>/<secret_name>

terraform import github_actions_secret.allowed_ssh_cidrs      ${REPO}/ALLOWED_SSH_CIDRS
terraform import github_actions_secret.allowed_ssh_cidrs_wide ${REPO}/ALLOWED_SSH_CIDRS_WIDE
terraform import github_actions_secret.oci_compartment_ocid   ${REPO}/OCI_COMPARTMENT_OCID
terraform import github_actions_secret.oci_fingerprint        ${REPO}/OCI_FINGERPRINT
terraform import github_actions_secret.oci_private_key        ${REPO}/OCI_PRIVATE_KEY
terraform import github_actions_secret.oci_region             ${REPO}/OCI_REGION
terraform import github_actions_secret.oci_tenancy_ocid       ${REPO}/OCI_TENANCY_OCID
terraform import github_actions_secret.oci_user_ocid          ${REPO}/OCI_USER_OCID
terraform import github_actions_secret.ssh_public_keys        ${REPO}/SSH_PUBLIC_KEYS
terraform import github_actions_secret.tfstate_bucket         ${REPO}/TFSTATE_BUCKET
terraform import github_actions_secret.tfstate_namespace      ${REPO}/TFSTATE_NAMESPACE

# --- Sección 4 — four github_actions_variable.* (R3.2) ---
# Format: <repository>:<variable_name>  (colon, NOT slash like secrets)

terraform import github_actions_variable.gh_app_id             ${REPO}:GH_APP_ID
terraform import github_actions_variable.gh_app_installation_id ${REPO}:GH_APP_INSTALLATION_ID
terraform import github_actions_variable.next_public_app_env   ${REPO}:NEXT_PUBLIC_APP_ENV
terraform import github_actions_variable.public_hostname       ${REPO}:PUBLIC_HOSTNAME

# NOTE: no github_branch_protection import — D5 (amended in section 4) does
# NOT declare that resource. The GitHub API rejects it entirely on this repo
# while private on the Free plan (confirmed live 2026-09-13); the three
# rules it would have enforced are documented as unforced convention in
# infra/github/RUNBOOK.md instead. See design.md §D5.
EOF