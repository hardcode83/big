# BLOCKED — ci-runner-pool-oci

Two verification tasks (`5.3` and `5.4`) cannot complete from the implementation worktree because they require the live OCI `dev` VM, which is not reachable from this environment. They are the **final gate** before `/sdd:ship` and `/sdd:archive`, and are the only items the user will resolve by hand.

## What's blocked

### Phase · type

- **Phase**: run (verification section)
- **Type**: environment — VM access required, no replacement from this worktree

### Tasks

- **5.3** — `terraform apply` on the live VM + re-run `runner-bootstrap.sh` + verify N runners via `gh api /actions/runners`. Requires SSH to the dev VM.
- **5.4** — `workflow_dispatch` matrix: launch `api-contract.yml` N times serially (60s apart) from the PR branch and confirm each job ran on a distinct `autohostai-${ENV}-vm-<i>` runner. Requires the N runners to actually exist (depends on 5.3).

### Why

The implementation worktree has no access to the OCI VM (no `oci-cli` instance-principal auth, no SSH key from this host). The change ships the IaC + the bootstrap script + the spec, but the live deployment and the matrix verification can only happen after merge, on a machine with the same access as the original `ci-runner-oci` rollout had.

### What was tried

- `terraform -chdir=infra/environments/dev fmt -check -recursive` (5.1): **PASS** (`FMT_EXIT=0`).
- `terraform -chdir=infra/environments/dev validate` (5.1): **PASS** (`VAL_EXIT=0`).
- `git diff origin/main -- .github/workflows/` (5.2): **PASS** (diff vacío, los 10 `runs-on: [self-hosted, dev]` están intactos; `multiarch-build-check.yml` sigue en `ubuntu-latest` por la salvedad de QEMU del change `ci-runner-oci` original).
- 5.3 y 5.4 requieren VM: no intentado desde aquí.

## Exact resume command

When the user is ready to run the final gate, from a machine with the same SSH + `oci-cli` access as `RUNBOOK.md §5.3`:

```bash
# 1) Apply + reaprovisionar el bootstrap con el nuevo default (4).
cd infra/environments/dev
terraform apply                           # crea los nuevos OCIDs / actualiza el tfstate si hace falta
ssh ubuntu@<dev-vm-ip> sudo /opt/bootstrap-runner.sh "$RUNNER_COUNT"   # RUNNER_COUNT=4 viene de variables.tf

# 2) Verificar que los N agentes están online y sin legado.
gh api repos/autohostai-labs/AutoHostAI/actions/runners?per_page=100
# esperado: N entradas con name=autohostai-${ENV}-vm-1 … autohostai-${ENV}-vm-4, todas status=online;
#           ninguna con name=autohostai-${ENV}-vm (legado migrado).

# 3) Matriz de verificación (D7). N=4 jobs, 60s entre cada uno.
for i in 1 2 3 4; do
  gh workflow run api-contract.yml --ref <pr-branch>
  sleep 60
done
# Tras 5 min, para cada run_id del último minuto:
gh api repos/autohostai-labs/AutoHostAI/actions/runs?per_page=10 \
  | jq -r '.workflow_runs[] | "\(.id)\t\(.display_title)\t\(.status)"'
# y por cada run_id:
gh api repos/autohostai-labs/AutoHostAI/actions/runs/<id>/jobs \
  | jq -r '.jobs[] | "\(.runner_name)\t\(.status)"'
# esperado: cada run tiene un runner_name distinto (autohostai-${ENV}-vm-1..4), todos status=success.
```

If 5.4 fails (some jobs share a runner), the diagnosis is in the sleep duration — increase it from 60s to the suite runtime + buffer.

## Why this is not a BLOCK on ship

`/sdd:ship` opens the PR (publishes the branch and creates the PR URL). The user said "resolveremos blocked en el ultimo paso antes de shipearlo" — meaning the gate is the final manual step before merging the PR, not before publishing it. The PR can be reviewed with the live gate still pending; the merge happens after 5.3 + 5.4 pass.

## Resume later

When the user runs 5.3 + 5.4 successfully:

1. Mark 5.3 and 5.4 as `[x]` in `tasks.md` with the date and one-line result.
2. Delete this `BLOCKED.md` (per shared rule 5).
3. `/sdd:archive` can then proceed after the merge, with the live-verification evidence attached to the archive notes.
