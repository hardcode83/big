#!/usr/bin/env bash
# import.sh — adoption procedure for the eleven `github_actions_secret` resources.
#
# SCOPE: this script prints the eleven `terraform import` commands that adopt the
# secrets already in the repo (created with `gh secret set` during the bootstrap
# irreducible). It is executed ONCE during this change (R3 + D6): after the import
# the secrets live in Terraform and every subsequent `apply` reconciles them.
#
# FORMAT (correction vs. the task text):
# The task text says `<SECRET_NAME>` as the import ID; the actual import ID
# required by the `integrations/github` provider v5.45.0 is
# `<repository>/<secret_name>` (verified against the upstream import function in
# `resource_github_actions_secret.go` at tag v5.45.0). The repository component
# is fixed to `AutoHostAI` for now (the default in `variables.tf`), so the
# produced lines all start with `AutoHostAI/...`.
#
# ORDER: alphabetical by GitHub secret name (per task 3.4 — interpreted as
# alphabetical by the `secret_name` field, NOT by the Terraform resource name,
# so the lines mirror the human reading of the repo's Secrets page).
#
# USAGE:
#   bash infra/github/import.sh                   # prints the eleven commands
#   bash infra/github/import.sh | bash            # runs them (only after the
#                                                  # CI workflow has populated
#                                                  # the `backend.hcl` with real
#                                                  # OCI credentials — never
#                                                  # with real credentials on
#                                                  # a developer machine)
#
# Each import consumes the external ID (the secret's name in GitHub); running
# the script a second time against an already-imported state is a no-op for
# Terraform but produces a confusing error. The script does not run the
# commands — that is the operator's call, after reading the produced lines.

set -euo pipefail

REPO="AutoHostAI"

cat <<EOF
# Import commands for the eleven github_actions_secret resources.
# Run AFTER 'terraform init' against the real OCI backend and BEFORE
# 'terraform apply -target=github_actions_secret.*'.
#
# Each line is idempotent against the secret in GitHub; running twice is safe
# only if the secret hasn't been re-created in the meantime.

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
EOF