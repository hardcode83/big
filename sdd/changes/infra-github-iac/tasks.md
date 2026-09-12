# Tasks: infra-github-iac

<!-- Markers, read by /sdd:run and the lifecycle gates (HTML comments, invisible
     when rendered). On a section heading: "hard" makes that section's
     implementer run on the stronger model; "panel: PASS <date> receipt:<id>"
     is written by the panel gate (reviewer_panel.py) when the section's review
     panel passes — never by hand; "panel: skipped — <reason>" records a
     deliberate skip (scaffolding, docs, config). On a task line:
     "manual" marks a task only a human can perform — run leaves it to you and
     it may travel with the PR as a deferred entry; it may sit on any line of
     task item, not only the checkbox line. -->

## 1. Bootstrap & module scaffolding <!-- hard -->

- [ ] 1.1 Crear el bucket de Object Storage `autohostai-tfstate-github` (mismo compartimento que `autohostai-tfstate-dev`) con `versioning = enabled` — **bootstrap irreducible**, no codificable. <!-- manual -->
- [x] 1.2 Crear `infra/github/{main.tf,variables.tf,outputs.tf,backend.tf,backend.hcl.example,github.tfvars.example,README.md}` con el esqueleto vacío salvo `terraform { required_version = ">= 1.12"; required_providers { github = { source = "integrations/github"; version = "~> 5.0" } } }` en `main.tf`. [R1.2]
- [x] 1.3 `backend.tf`: backend nativo `oci` con configuración parcial vía `-backend-config`. [R1]
- [x] 1.4 `backend.hcl.example`: plantilla con placeholders para namespace/bucket/region/tenancy/user/fingerprint/private_key (comentado: NUNCA versionar con valores reales). [R1]
- [x] 1.5 `github.tfvars.example`: placeholders no sensibles (`github_owner = "autohostai-labs"`, `github_repository_name = "AutoHostAI"`) con comentario de que las sensibles van por `TF_VAR_*`. [R1.3]
- [x] 1.6 `variables.tf`: declarar las 14 variables (12 sensibles + 2 no sensibles) según §"Variables nuevas (resumen)" del design — validar CIDRs (≥/24 para `allowed_ssh_cidrs`, ≥/16 para `allowed_ssh_cidrs_wide`, ≥1 entrada SSH) y formato de clave pública (regex SSH) en línea con `infra/environments/dev/variables.tf`. [R1.3, R3]
- [x] 1.7 `outputs.tf`: tres outputs (`github_repository_full_name`, `github_repository_default_branch`, `github_app_installation_id`) — nunca valores de secrets. [R1]
- [x] 1.8 Verificación local: `terraform -chdir=infra/github init -backend=false && terraform -chdir=infra/github validate && terraform -chdir=infra/github fmt -check -recursive` deben pasar. [R1.4]

## 2. Repository settings + App installation

- [ ] 2.1 `main.tf`: declarar `provider "github"` con `owner = var.github_owner` y `app_auth { id, installation_id, pem_file }` mapeados desde las variables (sin marcar sensibles en el HCL — son IDs públicos). [R1.1, R1.3]
- [ ] 2.2 `main.tf`: declarar `github_repository_settings.this` con `description`, `homepage` (vacío hasta que exista), `topics = []`, `visibility = "private"`, `default_branch = "main"`, `has_issues = true`, `has_projects = false`, `has_wiki = false`, `archived = false`. Verificar los nombres exactos de los atributos contra la doc del provider pinado en `tasks.md` del design. [R2.1]
- [ ] 2.3 `main.tf`: declarar `github_app_installation_repositories.this` con `installation_id = var.github_app_installation_id` y `selected_repositories = [var.github_repository_full_name]`. NO incluir `data "github_app"` (no se necesita). [R4.1]
- [ ] 2.4 `main.tf`: añadir `lifecycle { ignore_changes = [...] }` defensivo sobre los atributos derivados del provider que `tasks.md` del design identifica (D10). Lista inicial vacía si la doc del provider pinado no expone ninguno — se rellena si el primer `plan` muestra diff inocuo. [R1.4]
- [ ] 2.5 Verificación: `terraform -chdir=infra/github plan -var-file=github.tfvars.example -var github_app_id=<test> -var github_app_installation_id=<test> -var github_app_private_key_path=/dev/null` debe mostrar el recurso `github_repository_settings` (con diff inocuo — `terraform plan` posterior post-`apply` debe quedar vacío) y `github_app_installation_repositories` como nuevo (todavía no se ha aplicado). [R2.2, R4]

## 3. Actions secrets (importación del primer `apply`) <!-- hard -->

- [ ] 3.1 `main.tf`: declarar los once `github_actions_secret` (uno por secreto listado en `infra/environments/dev/README.md` §"Secrets de GitHub Actions esperados": `OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT`, `OCI_REGION`, `OCI_PRIVATE_KEY`, `OCI_COMPARTMENT_OCID`, `TFSTATE_NAMESPACE`, `TFSTATE_BUCKET`, `ALLOWED_SSH_CIDRS`, `ALLOWED_SSH_CIDRS_WIDE`, `SSH_PUBLIC_KEYS`). Cada uno mapea su `plaintext_value` desde la variable Terraform correspondiente marcada `sensitive = true`. [R3.1]
- [ ] 3.2 NO declarar `github_actions_secret` para los secretos que viven en el Vault (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`, los cuatro de medios, los seis `SMTP_*`, el token del túnel, `DEMO_ACCOUNT_PASSWORD`) — fuente de verdad es `infra/environments/dev/`. Comentar en `RUNBOOK.md` §2 (en sección 5) por qué no se duplican. [R3.4]
- [ ] 3.3 NO declarar `github_actions_secret` para `GH_APP_PRIVATE_KEY` — el módulo NO inyecta el secreto de su **propia** App en Actions; el provider `integrations/github` lee la clave directamente desde `pem_file` (D2). El secreto se inyecta al `deploy-dev.yml` desde otra fuente (la misma que `infra-dev`). [R3.3]
- [ ] 3.4 Crear `infra/github/import.sh` (script versionado) que imprime los once `terraform import github_actions_secret.<nombre> <SECRET_NAME>` listos para copiar/pegar — orden: alfabético por nombre del recurso. Incluir comentario de cabecera explicando que el script se ejecuta **una sola vez** durante este change, y que cada `import` consume el ID externo (el nombre del secret en GitHub). [R3.1, D6]
- [ ] 3.5 Verificación: `terraform -chdir=infra/github plan` (con valores reales cargados desde el workflow de CI, NO localmente) debe mostrar los once secretos como **ya en el state** tras ejecutar `bash infra/github/import.sh` + `terraform -chdir=infra/github apply -target=github_actions_secret.*` — el plan post-import debe quedar vacío sobre estos recursos. **Ejecutar `terraform plan` localmente solo si se dispone de credenciales reales de la App — NO versionar.** [R3, D6]

## 4. Actions variables + branch protection

- [ ] 4.1 `main.tf`: declarar los cuatro `github_actions_variable` (R3.2): `github_actions_variable.gh_app_id` (`GH_APP_ID`), `.gh_app_installation_id` (`GH_APP_INSTALLATION_ID`), `.next_public_app_env` (`NEXT_PUBLIC_APP_ENV`), `.public_hostname` (`PUBLIC_HOSTNAME`). `GH_APP_ID` y `GH_APP_INSTALLATION_ID` leen de variables no sensibles; `NEXT_PUBLIC_APP_ENV` y `PUBLIC_HOSTNAME` requieren variables nuevas — añadirlas a `variables.tf` como no sensibles con defaults `""` y validación fail-fast si el workflow no las inyecta. [R3.2]
- [ ] 4.2 Actualizar `infra/github/import.sh` para incluir los cuatro `terraform import github_actions_variable.<nombre> <VARIABLE_NAME>`. [R3.2, D6]
- [ ] 4.3 `main.tf`: declarar `github_branch_protection.this` sobre `main` con: `required_status_checks { strict = false; contexts = [...] }` (lista de checks que los workflows `infra-dev.yml`, `deploy-dev.yml`, `frontend-tests.yml`, `backend-tests.yml` exponen; verificar nombres exactos contra los YAML), `require_linear_history = true`, `enforce_admins = true`. Verificar los nombres exactos contra la doc del provider pinado en `tasks.md` del design. [R5.1]
- [ ] 4.4 Si la API rechaza alguna regla por el límite del plan Free (típicamente `required_pull_request_reviews`), `terraform plan` debe reportarlo sin fallar — añadir comentario en el recurso explicando cómo se documenta el rechazo en `RUNBOOK.md` §3 (sección 5). [R5.2]
- [ ] 4.5 Verificación local: `terraform -chdir=infra/github plan` (con credenciales) muestra los cuatro `github_actions_variable` y `github_branch_protection` post-import con diff vacío. [R3.2, R5]

## 5. RUNBOOK + first apply + import de los recursos existentes <!-- hard -->

- [ ] 5.1 Crear `infra/github/RUNBOOK.md` con tres secciones: (1) **Bootstrap irreducible** — crear la org (manual una vez), crear la GitHub App con permisos `administration: write` + `repository: read/write` + `members: read` + `packages: write` (OQ1), generar `.pem`, configurar la App en `autohostai-labs`, rotar la clave; (2) **Lo que Terraform ya cubre** — enumerar los recursos que este módulo declara (R2-R5) con qué secret/variable/settings corresponde a cada uno; (3) **Rotación / Known limitations** — procedimiento de dos pasos coordinados (Terraform + Vault) para rotar la clave de la App, y la limitación si la flag de packages no es modelable en la versión pinada del provider (D9). [R6.1]
- [ ] 5.2 Actualizar `infra/environments/dev/RUNBOOK.md` §6 — añadir una línea al inicio: *"El bootstrap irreducible de la GitHub App (creación, permisos, generación de clave `.pem`) está documentado en `infra/github/RUNBOOK.md` §1; este §6 mantiene cómo se opera el runner."* No tocar el resto del §6. [R6.2]
- [ ] 5.3 Añadir `import.sh` a la cabecera del RUNBOOK como referencia al procedimiento de adopción. [R6.1]
- [ ] 5.4 Ejecutar el primer `apply` real (vía `workflow_dispatch action: apply` — el local sin credenciales reales no es suficiente para validar la importación) y verificar post-apply que `terraform plan` queda **completamente vacío** sobre los once secrets + cuatro variables + repo settings + branch protection + App installation. Si el plan muestra diff, NO marcar la tarea como hecha — el diff es un bug del `import.sh` o de los recursos. [R7.3, D6]
- [ ] 5.5 Verificar que ningún `output` de Terraform expone el valor de un secret — `terraform show -json | jq '.outputs'` debe mostrar solo los tres outputs planeados y ningún valor que parezca PEM o CIDR. [R1]

## 6. CI workflow + GHCR verification job

- [ ] 6.1 Crear `.github/workflows/infra-github.yml` siguiendo el patrón de `.github/workflows/infra-dev.yml`: (1) job `check` para `pull_request` con `paths: ['infra/github/**']`, sin secretos, en `ubuntu-latest`, ejecutando `terraform fmt -check -recursive infra/github/`, `terraform -chdir=infra/github init -backend=false`, `terraform -chdir=infra/github validate`; (2) workflow `workflow_dispatch` con `action: plan|apply`, gateado por `if: github.ref == 'refs/heads/main'` (D7), ejecutado en `[self-hosted, dev]`, con `concurrency` (serializa applies) y `timeout-minutes`. [R7.1, R7.2, R7.4]
- [ ] 6.2 Reutilizar el patrón de `terraform` por SHA de commit (mismo SHA que `infra-dev.yml`); inyectar las variables sensibles con `env: TF_VAR_github_app_private_key_path: ${{ env.GH_APP_PRIVATE_KEY_PATH }}` y compañía desde `${{ secrets.* }}`. [R7]
- [ ] 6.3 Añadir un job `pull_request` adicional `verify-ghcr` (en el mismo workflow, con el `paths`-filter adecuado) que publique una imagen efímera a `ghcr.io/autohostai-labs/infra-github-iac-smoke` con etiqueta `ephemeral-${{ github.run_id }}` y la borre al terminar — verificación end-to-end de que el permiso `packages: write` de la App + el flag de packages del repo componen un acceso que funciona. Si la flag de packages no es modelable (D9, fallo documentado), el job sigue siendo válido: verifica el lado App y deja explícito en su log qué limitación existe. [R4.2]
- [ ] 6.4 Verificación: abrir un PR de prueba (puede ser un commit vacío sobre la rama) y verificar que `check` y `verify-ghcr` corren y pasan. [R7.1]

## 7. Documentación: specs + steering

- [ ] 7.1 Actualizar `infra/README.md` añadiendo `infra/github/` al árbol con una línea de descripción corta. [Spec affected]
- [ ] 7.2 Actualizar `sdd/specs/infra-scaffold.md` añadiendo una nota bajo "Estructura de `/infra` por entorno" que menciona `infra/<superficie-cross-env>/` como tercer patrón documentado. [Spec affected]
- [ ] 7.3 Actualizar `sdd/specs/infra-dev-terraform.md` añadiendo una nota bajo "Pendiente" (o donde quede coherente) que la declaración de secrets/variables de Actions pasa a `infra/github/` — este spec mantiene la lista de secrets **esperados** como referencia cruzada. [Spec affected]
- [ ] 7.4 Actualizar `sdd/specs/app-deploy-dev.md` añadiendo una nota en "Estado" indicando que la lista de variables (`GH_APP_ID`/`GH_APP_INSTALLATION_ID`/`NEXT_PUBLIC_APP_ENV`/`PUBLIC_HOSTNAME`) se gestiona en `infra/github/`; este spec mantiene cómo se consumen en runtime. [Spec affected]
- [ ] 7.5 Actualizar `sdd/steering/infra.md`: (a) §"Convención de layout" — añadir un tercer bullet `infra/<superficie-cross-env>/` con la justificación de superficies por-organización (GitHub-side hoy; DNS/org/policies futuras); (b) bajo "Lección de `app-deploy-dev`" — confirmar que el provider `github` ya está adoptado (la nota de "cambio futuro pendiente" queda obsoleta). [R1.2, Spec affected]
- [ ] 7.6 Verificación: `make check-rule11-ownership` pasa (los cambios de prosa en `sdd/` y `docs/` están bajo el censo del guard; este change no introduce sumideros nuevos). [Steering rule 11]

## 8. Verificación "deploy from zero" <!-- hard -->

- [ ] 8.1 Disparar `workflow_dispatch` con `action: apply` en `infra-github.yml` desde `main` — confirmar que el run termina en verde y aplica todos los recursos declarados. [R7.2, R7.3]
- [ ] 8.2 Inmediatamente después, disparar `workflow_dispatch` con `action: plan` — confirmar que el `plan` queda **completamente vacío** (R7.3). Si no, el primer apply no se completó bien: NO marcar la tarea como hecha y volver a sección 5. [R7.3]
- [ ] 8.3 Confirmar que el job `verify-ghcr` del run de CI de 6.4 publicó y borró la imagen efímera correctamente (`gh api /user/packages/container/infra-github-iac-smoke/versions` no debe devolverla). [R4.2]
- [ ] 8.4 Verificación final: re-correr todas las verificaciones locales (`terraform fmt -check -recursive infra/github/`, `validate`, `plan` con `backend=false`) — deben pasar. [R1.4, R7]
- [ ] 8.5 Vincular el run del workflow desde la sección "Pendiente" de `infra/github/RUNBOOK.md` como evidencia viva de "deploy from zero" exitosa. [R7.3]

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->

- Tarea 1.1 (manual) queda PENDIENTE — el bucket `autohostai-tfstate-github` no lo crea este Terraform.
- Variables: declaradas EXACTAMENTE 14 (12 sensibles + 2 no sensibles) siguiendo el conteo literal de la tarea 1.6. `github_app_id`, `github_app_installation_id` y `github_repository_full_name` NO están declaradas como variables — sección 2 las añade (las dos primeras) y la tercera es un `local.*` (computado, como dice el design §"Variables nuevas").
- `outputs.tf` referencia `local.*` placeholders (`github_repository_default_branch = "main"`, `github_app_installation_id = "0"`); sección 2 los cablea a los recursos reales — esto evita pre-comprometer nombres de atributos del provider pinado y hace que `terraform validate` pase ya en sección 1.
- `backend.hcl.example` usa `key = "github.tfstate"` (el módulo dev usa `dev.tfstate`); el bucket queda fijo a `autohostai-tfstate-github` en el ejemplo — el bootstrap irreducible (tarea 1.1) sigue siendo quien lo crea.
- Provider pinado: `~> 5.0` resuelve a `v5.45.0` (verificado en `terraform init`). OJO si sección 2 mira atributos — la doc debe ser de esa versión.
- `.terraform.lock.hcl` se commitea (whitelisted en `.gitignore` raíz, mismo patrón que el módulo dev).