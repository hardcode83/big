# BLOCKED — infra-dev-hardening

Código completo (§1-5, §7) y verificado por `terraform plan` (`5 to add, 1 to change, 0 to destroy`, instancia intacta). Falta el panel de revisión y las operaciones que requieren tu consola/CLI/admin + el apply por pipeline.

## panel · run · deferred — panel de revisión no ejecutado
El código infra no ha pasado por el panel (architect/security/qa + reviewers de proyecto).
**Resume:** `/sdd:review infra-dev-hardening` antes de `/sdd:archive`.

## ops · run · decision — secuencia operativa (tras mergear el PR de hardening)
Orden recomendado:
1. ~~**§3.3** — borrar el budget/alerta manual en consola.~~ HECHO.
2. ~~**§5.4** — Environment `dev-apply`.~~ RESUELTO vía **opción A** (repo privado + Free: sin Environment; gate = review del PR + apply manual desde `main`, ya en el workflow/RUNBOOK).
3. **§6.1/6.2** — crear/aplicar la policy IAM mínima (grupo acotado al compartment dev; debe incluir verbos de KMS/Vault, budgets, object-storage, compute/red); mover el usuario de Terraform al grupo y verificar `plan`/`apply`.
4. **§6.3** — activar versioning del bucket `autohostai-tfstate-dev` (`oci os bucket update --versioning Enabled`).
5. **§8.3** — lanzar el `workflow_dispatch` `apply` desde `main` (tras merge): crea budget €1 + 2 alertas + vault + key, y aplica el security list. Confirmar `0 to destroy`.
6. **§4.2** — subir la clave SSH al secret del Vault out-of-band (`oci vault secret create-base64 …`, ver RUNBOOK) — el vault ya existe tras el apply.
7. **§8.4** — verificar secret recuperable, versioning activo, y smoke SSH.

**Resume:** `/sdd:run infra-dev-hardening` para marcar estas tareas conforme se completen, o hazlas y luego `/sdd:review` + `/sdd:archive`.
