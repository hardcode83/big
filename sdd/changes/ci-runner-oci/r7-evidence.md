# R7 evidence — ci-runner-oci (branch `sdd/ci-runner-oci`)

Generated: 2026-09-03T14:36:30Z. Source: `GET /repos/autohostai-labs/AutoHostAI/actions/runs/{id}/jobs` (field `runner_name`).

## Cómo leer esta tabla

- **Dos pasadas.** La primera (commit `f82a035`, 13:53–14:08 UTC) disparó los 9 workflows con `workflow_dispatch` sobre la rama: 5 verdes y 4 rojos por tooling implícito de `ubuntu-latest` (`backend-tests` 33763662524, `deploy-dev` 33763676598, `frontend-tests` 33763690752, `rule11-ownership` 33763711320 — detalle medido en `design.md` D11). La segunda (commit `c34303f`, tras aplicar §8) volvió a disparar solo esos cuatro: **todos verdes**. La tabla mezcla el último run de cada workflow, que es el que cuenta; los cinco que no cambiaron en §8 conservan el run de la primera pasada.
- **`backend-tests-suite` en el runner**: `Using CPython 3.12.14` (antes del pin, 3.14.7), `9903 passed, 41 skipped in 472.51s` — bajo el presupuesto de 540 s de `specs/backend-ci.md`. Los `services` Postgres/Redis del job funcionaron en la VM.
- **Jobs `skipped`**: no son fallos, son gating a `main`. `deploy-dev`: `build-backend`, `build-frontend` y `deploy` llevan `if: github.ref == 'refs/heads/main'`; su `provenance` sí corrió en el runner (con el `setup-node` de D11). `infra-dev`: `check` solo se dispara por `pull_request`, y `plan`/`apply` solo por `workflow_dispatch` desde `main`, así que un dispatch sobre la rama no puede ejecutar ninguno. **La prueba runner-side de `infra-dev/check` y de los builds de `deploy-dev` llega, por construcción, al abrir el PR (`check`) y con el primer push a `main` tras el merge (builds + deploy)** — es lo que R7.1 exige literalmente («WHEN el PR se abre …»), y `/sdd:ship` debe comprobar el check `infra-dev/check` en verde sobre `autohostai-dev-vm` antes de dar el PR por listo.
- **`multiarch-build-check`** corre en `GitHub Actions …` / `ubuntu-latest` a propósito: excepción R4.2/D5 (QEMU no verificado), documentada en `docs/ci-runner-rollback.md` §2.
- **`demo-reset`** no se disparó desde la rama: su único job está gateado a `main` y ejecutarlo allí resetea el tenant de demostración. Su evidencia es el run programado de hoy sobre `main`, abajo, que ya corre en el runner (caso base R1.3).

| workflow | run | job | job conclusion | runner_name | labels |
|---|---|---|---|---|---|
| api-contract | 33763655542 | api-contract | success | autohostai-dev-vm | self-hosted,dev |
| backend-tests | 33766368745 | backend-tests-detect | success | autohostai-dev-vm | self-hosted,dev |
| backend-tests | 33766368745 | backend-tests-suite | success | autohostai-dev-vm | self-hosted,dev |
| backend-tests | 33766368745 | backend-tests | success | autohostai-dev-vm | self-hosted,dev |
| compose-ports | 33763669452 | compose-ports | success | autohostai-dev-vm | self-hosted,dev |
| deploy-dev | 33766375127 | provenance | success | autohostai-dev-vm | self-hosted,dev |
| deploy-dev | 33766375127 | build-frontend | skipped | — | self-hosted,dev |
| deploy-dev | 33766375127 | build-backend | skipped | — | self-hosted,dev |
| deploy-dev | 33766375127 | deploy | skipped | — | self-hosted,dev |
| frontend-api-contract | 33763684078 | frontend-api-contract | success | autohostai-dev-vm | self-hosted,dev |
| frontend-tests | 33766381743 | frontend-tests | success | autohostai-dev-vm | self-hosted,dev |
| frontend-tests | 33766381743 | provenance-contract | success | autohostai-dev-vm | self-hosted,dev |
| infra-dev | 33763697391 | check | skipped | — | self-hosted,dev |
| infra-dev | 33763697391 | apply | skipped | — | self-hosted,dev |
| infra-dev | 33763697391 | plan | skipped | — | self-hosted,dev |
| multiarch-build-check | 33763704150 | build-backend | success | GitHub Actions 1000003650 | ubuntu-latest |
| multiarch-build-check | 33763704150 | build-frontend | success | GitHub Actions 1000003651 | ubuntu-latest |
| rule11-ownership | 33766387942 | rule11-ownership | success | autohostai-dev-vm | self-hosted,dev |

## demo-reset (base case, `runs-on` unchanged) — latest run on `main`

- run 33731083627 · event=schedule · completed/success · 2026-09-03T08:01:01Z
  - job `reset`: success on runner `autohostai-dev-vm` (labels: self-hosted,dev)
