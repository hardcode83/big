# Runbook — rollback del runner self-hosted

Procedimiento para revertir los workflows migrados al runner self-hosted de la VM dev (`[self-hosted, dev]`) y volver a `ubuntu-latest` cuando haga falta. Complementa a `infra/environments/dev/RUNBOOK.md` (operación del runner) y a `sdd/changes/ci-runner-oci/{proposal,design}.md` (decisiones del change). Cada archive posterior que toque `runs-on:` debe mantener este runbook sincronizado (R6.3).

Referencias rápidas: PR de migración `<n>` · SHA del commit `<migration_sha>` · runner label `dev` · usuario de la VM `ubuntu` · clave local `~/.ssh/autohostai_dev_vm` · el runner corre en `/opt/actions-runner` sobre la VM `dev` (AD-3).

> **`<n>`, `<migration_sha>` y `<merge_sha>` (§3) son placeholders literales mientras este change no tiene PR.** `/sdd:ship` los rellena con valores reales al abrir el PR (`<n>`, `<migration_sha>`) y, si el merge es por merge-commit, al mergear (`<merge_sha>` en §3 solo se conoce entonces — el comando de squash de §3 usa `<migration_sha>`, que sí queda fijado al abrir el PR). No copies los comandos de §3 verbatim hasta que estos placeholders tengan valores reales.

## 1. Resumen

El change `ci-runner-oci` migra 9 de los 10 workflows bajo `.github/workflows/` al runner self-hosted de la VM `dev` con label `[self-hosted, dev]` (la excepción es `multiarch-build-check.yml`, ver §2). Antes del merge del PR, cada workflow migrado ha corrido al menos una vez verde en el runner (R7). Tras el merge:

- **PR**: `<n>`
- **Commit**: `<migration_sha>` (SHA del merge; o del squash si el PR se fusionó por squash)
- **Label del runner**: `[self-hosted, dev]`
- **Workflows migrados**: **9 de 10** (la salvedad es `multiarch-build-check.yml`, ver §2 y la nota sobre QEMU debajo)

El rollback es **un `git revert`**: deja el repo exactamente en la línea base de CI previa al PR (los `runs-on: ubuntu-latest` originales).

## 2. Tabla de workflows

La tabla refleja los ficheros `.yml` migrados bajo `.github/workflows/` a fecha del change `ci-runner-oci`.

| Workflow | runs-on previo | runs-on actual | Excepción |
|---|---|---|---|
| `api-contract.yml` | `ubuntu-latest` (1 job) | `[self-hosted, dev]` (1 job) | — |
| `backend-tests.yml` | `ubuntu-latest` (3 jobs) | `[self-hosted, dev]` (3 jobs) | — |
| `compose-ports.yml` | `ubuntu-latest` (1 job) | `[self-hosted, dev]` (1 job) | — |
| `demo-reset.yml` | `[self-hosted, dev]` (1 job) | `[self-hosted, dev]` (1 job) | ya estaba en `[self-hosted, dev]` |
| `deploy-dev.yml` | `ubuntu-latest` (3 jobs: provenance/build-backend/build-frontend) + `[self-hosted, dev]` (1 job: deploy) | `[self-hosted, dev]` (4 jobs) | — (el job `deploy` ya estaba en `[self-hosted, dev]`) |
| `frontend-api-contract.yml` | `ubuntu-latest` (1 job) | `[self-hosted, dev]` (1 job) | — |
| `frontend-tests.yml` | `ubuntu-latest` (2 jobs) | `[self-hosted, dev]` (2 jobs) | — |
| `infra-dev.yml` | `ubuntu-latest` (3 jobs) | `[self-hosted, dev]` (3 jobs) | — |
| `multiarch-build-check.yml` | `ubuntu-latest` | `ubuntu-latest` | **Sí — QEMU no verificado; fallback R4.2/D5** (sin probe ejecutado en §1, VM IP no reachable) |
| `rule11-ownership.yml` | `ubuntu-latest` (1 job) | `[self-hosted, dev]` (1 job) | — |

> **Multiarch y QEMU — resolución adoptada en §1.** El probe de §1.2 no llegó a ejecutarse (VM IP no reachable desde este worktree: sin tfstate, OCI CLI con sesión expirada, SSH key presente pero sin destino). Se adoptó el fallback explícito de R4.2 / D5: `multiarch-build-check.yml` queda en `ubuntu-latest` y la columna Excepción marca **«QEMU no verificado; fallback R4.2/D5»**. La tabla dice «9 de 10 migrados, 1 excepción deliberada — QEMU no verificado». El operador puede verificar QEMU en un follow-up change y migrar ese workflow si el probe pasa; ese cambio actualizará esta misma fila y la columna Excepción a `—`.

## 3. Rollback por `git revert`

El rollback global preferido. Una sola operación revierte los 9 workflows migrados a `ubuntu-latest` (`multiarch-build-check.yml` ya está en `ubuntu-latest`, no participa del revert).

```bash
# PR mergeado por merge commit (lo habitual con /sdd:ship):
git revert -m 1 <merge_sha>

# PR mergeado por squash (un único commit con todos los cambios):
git revert <migration_sha>
```

Qué pasa con los jobs en vuelo:

- Los jobs **ya en ejecución** en el runner cuando el revert entra al `main` siguen corriendo con la versión actual (`[self-hosted, dev]`). El runner no aborta jobs en vuelo al cambiar el `runs-on:`.
- Los jobs **nuevos** que se disparen tras el merge del revert arrancan ya con la versión revertida (`ubuntu-latest`), porque Actions evalúa el `runs-on:` en cada `workflow_run`.
- El revert es un commit nuevo en `main`; un segundo revert del revert (si hace falta) vuelve a poner el repo en `[self-hosted, dev]`.

Tiempo esperado: el `git revert` puro tarda **segundos** (es local + push); los runs de Actions que se disparen después pueden tardar minutos dependiendo de la cola de GH-hosted, pero no hace falta esperar a ninguno para considerar el rollback completo.

```bash
# Tras el revert, verificar que main está como antes:
git log -1 --format='%H %s'   # muestra el commit del revert
gh run list --limit 1 --json name,conclusion,headBranch   # el primer run post-revert ya va en ubuntu-latest
```

## 4. Rollback manual de un solo workflow

Si el runner VM **está caído** (no responde SSH, el servicio `actions.runner.service` falló, la VM se recreó y aún no se ha reaprovisionado el runner) y necesitas publicar un fix puntual sin esperar a recuperar el runner, puedes restaurar **un solo workflow** a `ubuntu-latest` con un patch mínimo. Es la vía de urgencia; **`git revert` global sigue siendo preferible** (§3) — esta sección solo cubre el caso de fuerza mayor.

```bash
# Ejemplo: restaurar infra-dev.yml a ubuntu-latest (3 jobs: check, plan, apply).
# El cambio mínimo: cada `runs-on: [self-hosted, dev]` → `runs-on: ubuntu-latest`.
sed -i '' 's|runs-on: \[self-hosted, dev\]|runs-on: ubuntu-latest|g' \
  .github/workflows/infra-dev.yml

# Commitea y pushea directamente a main (o vía PR si el repo lo permite):
git add .github/workflows/infra-dev.yml
git commit -m "fix(ci): restore infra-dev to ubuntu-latest (runner VM down)"
git push origin main
```

Notas importantes:

- **Sin cabecera**: el comentario `# Runner self-hosted...` no se retira en este rollback puntual; se retira al hacer el `git revert` global (§3) o al re-migrar.
- **Mismo camino al re-migrar**: cuando la VM vuelva, `git revert <este-commit>` + push deja el workflow otra vez en `[self-hosted, dev]` con la cabecera intacta.
- **Límite**: este parche cambia **un workflow**. Si la VM está caída, probablemente hay que parchear varios — sigue siendo preferible un `git revert` global cuando la VM vuelva a estar disponible, porque deshace el cambio de una sola vez y deja el repo consistente.

## 5. Validación post-rollback

Tras ejecutar `git revert` (§3) o un rollback manual (§4), confirma que los workflows vuelven a correr en `ubuntu-latest`. La validación va en dos pasos: `gh run list` localiza el último run de cada workflow, y la API REST de jobs (`GET /repos/{owner}/{repo}/actions/runs/{id}/jobs`) dice en qué runner corrió cada job — su campo `runner_name` vale `autohostai-dev-vm` para `[self-hosted, dev]` y `GitHub Actions N` para `ubuntu-latest`. **Ojo**: `gh run view --json jobs` **no** expone ese campo (medido el 2026-09-03: sus jobs solo traen `name`, `status`, `conclusion`, `steps`, `url`, fechas), así que hay que ir por `gh api`.

```bash
# Lista de los 10 workflows para iterar:
WORKFLOWS=(
  api-contract
  backend-tests
  compose-ports
  demo-reset
  deploy-dev
  frontend-api-contract
  frontend-tests
  infra-dev
  multiarch-build-check
  rule11-ownership
)

# Por cada workflow: el último run y, job a job, en qué runner corrió.
for w in "${WORKFLOWS[@]}"; do
  echo "== $w =="
  run_id="$(gh run list --workflow="$w" --limit 1 --json databaseId --jq '.[0].databaseId')"
  gh run list --workflow="$w" --limit 1 \
    --json conclusion,headBranch,event,createdAt,databaseId \
    --jq '.[] | "  run=\(.databaseId) event=\(.event) branch=\(.headBranch) conclusion=\(.conclusion) created=\(.createdAt)"'
  gh api "repos/autohostai-labs/AutoHostAI/actions/runs/${run_id}/jobs" \
    --jq '.jobs[] | "    job=\(.name) conclusion=\(.conclusion) runner=\(.runner_name)"'
done
```

Comprobaciones esperadas:

- `branch=main` (o el `head_branch` del commit de revert) — confirma que el run viene del revert, no de un push anterior.
- `conclusion=success` (o `failure`/`cancelled` por motivos no relacionados con el runner).
- Para los workflows migrados, el `runs-on:` efectivo es `ubuntu-latest`: ni `gh run list` ni `gh run view` muestran el runner, lo dice `runner_name` en la API de jobs (`GitHub Actions 4` o similar, no `autohostai-dev-vm`).

```bash
# Comprobación directa del runner usado por cada job del último run:
gh api "repos/autohostai-labs/AutoHostAI/actions/runs/<run-id>/jobs" \
  --jq '.jobs[] | "  job=\(.name) conclusion=\(.conclusion) runner=\(.runner_name) labels=\((.labels // []) | join(","))"'
```

Si algún workflow sigue apareciendo en `autohostai-dev-vm` tras el revert, abre un PR con el patch manual (§4) y no des el rollback por bueno hasta que la salida de arriba sea coherente.

## 6. Rotación / retirada del runner

Si la VM se recrea (cambio de `source_id` o rebuild completo, ver `oci-source-id-update-replaces-boot-volume`), el runner se vuelve a provisionar al reaplicar `infra/environments/dev/`. El `cloud-init` del módulo Terraform ejecuta `runner-bootstrap.sh` con `--replace`, que es idempotente: el runner se registra de nuevo con el mismo label (`dev`) y los workflows reanudan solos en cuanto Actions detecta el runner online.

```bash
# En la VM (post-rebuild), reaprovisionar el runner:
sudo bash /opt/bootstrap-runner.sh    # idempotente, label = ENV (dev)
# Verificar: GitHub → Settings → Actions → Runners muestra autohostai-dev-vm Idle.
```

Cuándo conviene migrar el runner a `infra-github-iac` (provider `integrations/github`) en vez de mantenerlo por código imperativo (`runner-bootstrap.sh`):

- Cuando el equipo crezca y haya que gestionar varios entornos (staging/prod) con runners paralelos.
- Cuando la rotación de credenciales de la GitHub App quiera declararse en Terraform en lugar de los pasos manuales del `RUNBOOK.md §6.1`.
- Cuando se quiera que el `terraform plan` detecte drift en el registration del runner (hoy se detecta por la salida de `gh api /repos/.../actions/runners`, no por plan).

Hasta entonces, `runner-bootstrap.sh` es la fuente de verdad y el reaprovisionamiento manual cubre el ciclo de vida de la VM. **No** se retira el script al migrar a `infra-github-iac` — se conserva como puente mientras el provider declara el equivalente, y se retira solo cuando el `apply` que use `integrations/github` esté verde en los tres entornos.
