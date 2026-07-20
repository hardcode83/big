# Design: infra-dev-terraform

## Context

`infra/environments/dev/README.md` es hoy un placeholder: documenta la decisión del ADR 0001 pero no hay ningún `.tf`. `infra/` no tiene `modules/` todavía (spec `infra-scaffold`: se crea con el primer módulo compartido — no aplica aún, un solo entorno). No existe `.github/workflows/` en el repo: este change añade el primer workflow. El stack a desplegar es el `docker-compose.yml` de la raíz (6 servicios: `postgres`, `redis`, `migrate`, `backend`, `worker`, `frontend`), con `backend/devops/Dockerfile` y `frontend/devops/Dockerfile` ya multi-stage (`dev`/`prod`) pero sin build multi-plataforma probado. Los puertos publicados hoy en local son `5432` (postgres), `6379` (redis), `8000` (backend), `3000` (frontend) — en `dev` remoto solo `8000`/`3000`/`22` (SSH) deberían ser accesibles desde fuera de la VM; `postgres`/`redis` quedan solo en la red interna de `docker-compose` dentro de la instancia, igual que en local.

## Decisions

### D1 — Topología de red y cómputo (R1)

**Chosen:** Un root module en `infra/environments/dev/` con: 1 VCN (`10.0.0.0/16`), 1 subred pública (`10.0.1.0/24`), 1 security list permitiendo ingress TCP 22 (SSH, restringido por variable `allowed_ssh_cidr`, sin default abierto a `0.0.0.0/0`), 8000 y 3000 desde `0.0.0.0/0` — exactamente los puertos de `docker-compose.yml` que R1.1 lista, nada más; egress abierto. Instancia `oci_core_instance` shape `VM.Standard.A1.Flex` (2 OCPU/12 GB, el cupo Always Free completo dado que es una única instancia), imagen base Oracle Linux o Ubuntu ARM64 (a confirmar en tasks contra la lista de imágenes Always-Free-eligible vigente), con `cloud-init` mínimo que instala Docker + Docker Compose plugin y clona/despliega el repo (o recibe el compose vía el workflow de CI, ver D3). IP pública reservada (`oci_core_public_ip`, tipo `RESERVED`) asociada a la VNIC, no efímera — sobrevive a un reinicio/recreate de la instancia.

Rejected: instancia AMD micro (1 OCPU/1GB, también Always Free) — insuficiente para 5 servicios simultáneos, ya descartada explícitamente en el ADR. Múltiples instancias (una por servicio) — rompe el modelo "VM única + docker-compose" que es el punto central del ADR (cero reescritura de topología). Abrir 80/443 de forma especulativa para un futuro proxy TLS — ninguna R# de este change lo pide y `docker-compose.yml` no lo usa hoy; se añade en el change que introduzca TLS, no antes (superficie de ataque innecesaria mientras tanto).

### D2 — Gestión de secretos y variables (R1.4, security.md regla 8)

**Chosen:** `variables.tf` declara `tenancy_ocid`, `user_ocid`, `fingerprint`, `private_key_path`, `region`, `compartment_ocid`, `allowed_ssh_cidr`, `budget_alert_email` — todas sin default. La clave privada se pasa **por ruta a fichero, nunca por contenido inline** — evita el riesgo de sintaxis HCL de embeber un PEM multilínea en un string/heredoc (hallazgo de revisión de arquitectura, corregido: el workflow ahora escribe el secret `OCI_PRIVATE_KEY` a un fichero en `RUNNER_TEMP` con `printf '%s\n'`, garantizando el salto de línea final, y solo la ruta llega a Terraform). El resto de variables se inyectan desde secrets del repo (`OCI_TENANCY_OCID`, `OCI_USER_OCID`, etc.) vía `TF_VAR_*` en el step de `plan`/`apply`. Ningún valor real vive en el repo ni en `.tfvars` versionado; un `dev.tfvars.example` documenta los nombres esperados (mismo patrón que `.env.example`, security.md regla 8).

Rejected: `.tfvars` real committeado (aunque fuera `.gitignore`d, invita a errores) — se prefiere el patrón ya establecido de "solo el nombre, nunca el valor".

### D3 — Pipeline de CI/CD (R3)

**Chosen:** `.github/workflows/infra-dev.yml` con **dos triggers distintos, alcance distinto** (resuelve la tensión R3.2/R3.3):
1. `pull_request` (paths: `infra/environments/dev/**`) → job `check`: `terraform fmt -check` + `terraform init -backend=false` + `terraform validate`. `-backend=false` es la clave: no requiere ni el backend de state remoto ni ningún secret de OCI, así que se ejecuta siempre, en cualquier PR, sin credenciales — esto es exactamente lo que R3.3 pide ("sin secretos de OCI configurados... sigue completando con éxito").
2. `workflow_dispatch` (input `action`: `plan` | `apply`) → job `plan-apply`: checkout → `hashicorp/setup-terraform` → `terraform init` (con el backend real, credenciales desde secrets) → `terraform plan` → `terraform apply -auto-approve` solo si `action == 'apply'` y el `plan` fue exitoso. Este es el único disparador que puede tocar recursos reales — satisface R3.2 (nada de auto-apply en push/merge).

El despliegue de la app (`docker compose pull && up -d` dentro de la VM) queda fuera de este workflow — es un segundo workflow/step futuro (fuera de alcance, ver proposal) que necesita la IP de salida de este `apply` como input.

Rejected: un único job compartido entre PR y `workflow_dispatch` — obligaría a decidir entre pedir secrets en cada PR (inseguro, expone credenciales a cualquier PR incluso de forks) o saltarse la validación en PRs (viola R3.3). Trigger automático de `plan`/`apply` en push a `main` — el steering `infra.md` deja el disparador de `apply` explícitamente sin decidir, y aplicar contra cuenta real sin revisión humana es un riesgo alto para un primer despliegue; `workflow_dispatch` es el default conservador coherente con "nunca adivinar" de este flujo automatizado.

### D4 — Build multi-arch en CI (R4)

**Chosen:** Job separado (`.github/workflows/multiarch-build-check.yml` o step añadido a un workflow de CI existente de la app si lo hay — a verificar en tasks) que usa `docker/setup-qemu-action` + `docker/setup-buildx-action` + `docker buildx build --platform linux/amd64,linux/arm64` contra `backend/devops/Dockerfile` (target `prod`) y `frontend/devops/Dockerfile` (target `prod`), sin `--push` (solo build, sin publicar a ningún registry — coherente con el "Out of scope" del proposal). Verifica en CI lo que el ADR marcó como riesgo a confirmar: que `python:3.12-slim`, el binario de `astral-sh/uv`, y `node:22-slim` construyen limpio en `arm64`.

Rejected: verificarlo solo manualmente una vez en un portátil — no queda como verificación repetible, contradice R4.3.

### D5 — Alerta de presupuesto (R5)

**Chosen:** `oci_budget_budget` con `target_type = "COMPARTMENT"` sobre el compartment de `dev`, más `oci_budget_alert_rule` (tipo `ACTUAL`, umbral configurable por variable `budget_alert_threshold_percent`, default documentado pero variable `budget_alert_email` obligatoria sin default para el destinatario). Mitigación directa del riesgo "facturación bajo tenancy PAYG" documentado en el ADR.

Rejected: alerta configurada manualmente en la consola de Oracle — no es reproducible ni versionada, y el ADR pide explícitamente que esto exista "desde el primer día", lo que encaja mejor con IaC que con un paso manual olvidable.

### D7 — Backend de state remoto: `oci` nativo (R2)

**Chosen:** backend nativo `oci` (state en un bucket de OCI Object Storage) — decisión del usuario tras revisar la investigación de `BLOCKED.md` (coste $0 dentro del Always Free, locking nativo vía escritura condicional `If-None-Match`, sin cuenta de terceros nueva, reutiliza las mismas credenciales que ya exige el provider `oracle/oci`). Requisitos concretos:
- Fijar `required_version = ">= 1.12"` en `main.tf` (el backend `oci` es reciente).
- `backend.tf` declara `terraform { backend "oci" {} }` con **configuración parcial** — sin `namespace`/`bucket`/`region` hardcodeados en el archivo. Esos valores se pasan en `terraform init -backend-config=...` (flags en CI, o un `backend.hcl` local no versionado) — mismo patrón que el resto de credenciales: el nombre se documenta, el valor nunca vive en el repo.
- **Bootstrap manual, una sola vez, fuera de este Terraform**: crear el bucket de Object Storage (p. ej. `autohostai-tfstate-dev`) vía consola o CLI de OCI antes del primer `terraform init` — no puede crearlo el mismo Terraform que lo usará después como backend (dependencia circular). Se documenta paso a paso en el README (D6).
- El workflow de GitHub Actions (D3) añade los valores de `-backend-config` (namespace, bucket, región, más las credenciales — el backend `oci` no puede leer `var.*` del provider, necesita su propia autenticación) junto a las credenciales del provider ya previstas en D2.
- **Límite de la capa Always Free de Object Storage (R2.3)**, documentado explícitamente igual que el ADR 0001 cuantificó el de cómputo: **20 GB de Object Storage estándar + 20 GB de Archive Storage, siempre gratis**, más un cupo de peticiones API/mes también siempre gratis. Un `.tfstate` de los ~10 recursos de este módulo pesa unos pocos cientos de KB — muy por debajo del límite. Mismo matiz que el resto de recursos Always Free: Oracle ya ha recortado cupos sin aviso previo (recorte de cómputo de jun-2026, ADR 0001) — verificar el cupo vigente en la propia consola (`Governance & Administration → Tenancy Management → Always Free Resources`) en vez de asumir que esta cifra se mantiene indefinidamente.

Rejected: HCP Terraform (Terraform Cloud) free tier — añadía una cuenta de terceros nueva y el riesgo del token de 30 días sin necesidad, dado que el backend nativo cubre lo mismo sin coste ni superficie nueva.

### D6 — Documentación (R6)

**Chosen:** Reescribir `infra/environments/dev/README.md`: qué aprovisiona, el paso de **bootstrap manual del bucket de state** (D7, con los comandos exactos de la OCI CLI), cómo ejecutar `terraform plan/apply` (local, con `dev.tfvars.example`/`backend.hcl.example` como referencia, y vía el workflow), qué secrets de GitHub Actions hacen falta, y una sección "Estado" explícita: *"Código y pipeline listos y verificados (`validate`/`fmt`/`plan` sin credenciales, build multi-arch en CI). `apply` real pendiente — requiere tenancy de Oracle Cloud (`EXTERNAL_DEPENDENCY`, ver ADR 0001), el bootstrap del bucket de state, y configuración de secrets, todo manual."*

Rejected: describir el entorno como "desplegado" u omitir el estado real — violaría la regla de mantener specs/docs veraces (shared rule 1).

## Changes by area

| Area | Files | Change |
|---|---|---|
| Infra (dev) | `infra/environments/dev/{main.tf,variables.tf,outputs.tf,backend.tf,dev.tfvars.example,backend.hcl.example}` | Nuevos — red, cómputo, presupuesto, backend de state `oci` (config parcial) |
| Infra (docs) | `infra/environments/dev/README.md` | Reescrito — de placeholder a instrucciones reales |
| CI | `.github/workflows/infra-dev.yml` | Nuevo — plan/apply manual |
| CI | `.github/workflows/multiarch-build-check.yml` (o job añadido a workflow existente si aplica) | Nuevo — build `arm64`+`amd64` sin publish |
| Backend | `backend/devops/Dockerfile` | Ajustes menores si el build `arm64` revela algo a corregir (p. ej. pin de plataforma en alguna capa) |
| Frontend | `frontend/devops/Dockerfile` | Idem |
| Specs | `sdd/specs/infra-scaffold.md`, `sdd/specs/infra-dev-terraform.md` (nuevo) | Al archivar |

## Data & interfaces

Variables de Terraform (ver D2). Secrets/valores de GitHub Actions esperados (nombres, no valores): `OCI_TENANCY_OCID`, `OCI_USER_OCID`, `OCI_FINGERPRINT`, `OCI_PRIVATE_KEY`, `OCI_REGION`, `OCI_COMPARTMENT_OCID`, `BUDGET_ALERT_EMAIL`, más `TFSTATE_NAMESPACE`/`TFSTATE_BUCKET` para la configuración parcial del backend `oci` (D7). Ninguna entidad de dominio ni API afectada — este change es puramente infraestructura/CI.

## Risks & mitigations

- **Riesgo ARM64 (ya señalado en el ADR)**: mitigado por D4 — verificación en CI antes de aprovisionar, no al primer despliegue real.
- **"Out of host capacity" de Oracle para Ampere A1** (documentado en el ADR): fuera del control de este change; el `apply` real puede fallar por esto la primera vez — el README (D6) debe mencionar Frankfurt/Singapur como regiones recomendadas, ya señalado en el ADR.
- **Verificación limitada sin credenciales reales**: `validate`/`fmt`/`plan` no capturan todos los errores posibles de un `apply` real (p. ej. cuotas exactas, nombres de imagen exactos disponibles en la región). Se acepta explícitamente (ver proposal, Out of scope) — el primer `apply` real seguirá siendo el punto donde puede aparecer un problema no visto aquí.
- **Bootstrap del backend de state** (D7): el bucket de Object Storage necesita existir *antes* de que este Terraform pueda inicializarse contra él — paso manual único, documentado en el README, no resuelto por este mismo `.tf` (no se puede usar Terraform para crear el almacén de su propio state antes de tenerlo).
- **Versión de Terraform**: el backend `oci` nativo exige `>= 1.12` — fijar esa versión tanto en `hashicorp/setup-terraform` (CI) como en cualquier ejecución local, documentado en el README, para evitar un `init` que funcione en una máquina y falle en otra.

## Open questions

Ninguna abierta. La única pregunta de diseño pendiente (R2, backend de state) quedó resuelta por el usuario — ver D7 y `BLOCKED.md` (entrada 1, cerrada).
