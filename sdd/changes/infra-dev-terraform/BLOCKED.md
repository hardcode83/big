# Blocked — infra-dev-terraform

## Entry 1 — Backend de state remoto para Terraform (R2)

- **Phase**: design
- **Type**: `decision` (needs the user)
- **What & why**: `design.md` (D1-D6) asume que `infra/environments/dev/backend.tf` apunta a un backend remoto real, pero no decide cuál — el usuario planteó explícitamente esta duda al pedir el change ("no se si la capa gratuita de Terraform Cloud sera suficiente... u valorar otras opciones"). Es una decisión de requisitos (R2), no de implementación: cambia `backend.tf`, las variables/secrets que el workflow de CI necesita, y el paso de bootstrap manual previo al primer `init`. Bajo el modo auto, una ambigüedad de este tipo se bloquea en vez de adivinarse.

### Investigación (candidatos, para decidir en una sola lectura)

Alcance: ~10-15 recursos OCI (VCN, subred, security list, 1 instancia Ampere A1, presupuesto+alerta). Un solo entorno, equipo pequeño, GitHub Actions como CI.

| Opción | Coste | Locking | Complejidad de setup | Vendor lock-in | Encaje |
|---|---|---|---|---|---|
| **Backend nativo `oci`** (Terraform, tipo de backend propio, no el shim S3) | $0 (Object Storage ya dentro del Always Free) | Sí — nativo, escritura condicional `If-None-Match` (sin tabla tipo DynamoDB) | Baja — reutiliza las mismas credenciales que ya exige el provider `oracle/oci`; requiere Terraform ≥1.12 y un paso único de bootstrap manual (crear el bucket antes del primer `init`, no se puede hacer con el mismo Terraform que lo usará como backend) | Ninguno adicional al ya aceptado (Oracle) | El mejor encaje: cero coste nuevo, cero vendor nuevo, cero tipo de secret nuevo |
| **HCP Terraform (Terraform Cloud), capa gratuita** | $0 hasta 500 recursos gestionados (muy por encima de los ~10-15 de este change) | Sí — server-side | Media — cuenta/organización nueva, workspace, token de equipo como secret de GitHub, bloque `cloud {}` en la config | Cuenta de terceros nueva, además de Oracle+GitHub | Viable, pero el token de API **expira a los 30 días por defecto** — riesgo real de que CI se rompa en silencio si no se rota o se configura sin expiración |
| **Backend `s3` (shim S3-compatible contra OCI Object Storage)** | $0 | Obsoleto/no fiable — la propia documentación de Oracle recomienda ahora el backend `oci` nativo si se usa Terraform ≥1.12; la alternativa antigua necesitaba una tabla de locking al estilo DynamoDB | Alta — configuración extra, pieza ya superada | Ninguno adicional | Superado por el backend nativo — sin motivo para elegirlo hoy |
| Spacelift / env0 / Scalr (capas gratuitas) | $0 a esta escala | Varía (server-side) | Media-alta — otra cuenta/concepto de CI para un proyecto de 1 VM | Cuenta de terceros nueva | Sobredimensionado — resuelven problemas de equipo/políticas que este proyecto no tiene todavía |

**A favor / en contra de cada uno:**
- Backend nativo `oci`: **a favor** — sin cuenta nueva, sin categoría de secret nueva, locking real sin piezas extra. **en contra** — exige fijar Terraform ≥1.12 en CI, y el bucket de state necesita ese paso único de bootstrap manual fuera de este Terraform.
- HCP Terraform (gratis): **a favor** — UI real de historial de state/runs, integración con GitHub Actions muy documentada. **en contra** — dependencia nueva de terceros que la filosofía de coste-cero/superficie-mínima del ADR 0001 no necesita todavía, más el riesgo de expiración de token a 30 días para un equipo pequeño.
- Shim `s3`: ya no aporta nada frente al backend nativo; la propia Oracle recomienda migrar fuera de él.

**Si se quiere una recomendación**: el backend nativo `oci` es el default más coherente con el ADR 0001 (mismo razonamiento: cero coste, cero superficie nueva) — el único coste real es fijar Terraform ≥1.12 y documentar el paso manual de creación del bucket. HCP Terraform sigue siendo una alternativa razonable si se prefiere una UI hospedada sobre el historial de state/runs y no molesta añadir una segunda cuenta más el hábito de rotar el token.

**Fuentes**: [HCP Terraform Limits (HashiCorp)](https://support.hashicorp.com/hc/en-us/articles/4414055267603-HCP-Terraform-Limits) · [HCP Terraform free tier (blog HashiCorp)](https://www.hashicorp.com/en/blog/continuing-hcp-terraform-s-enhanced-free-tier-experience) · [Backend nativo `oci` — anuncio (Oracle)](https://blogs.oracle.com/cloud-infrastructure/terraform-oci-state-locking-backend) · [Backend Type: oci (Terraform docs)](https://developer.hashicorp.com/terraform/language/backend/oci) · [Backend Type: s3 (Terraform docs)](https://developer.hashicorp.com/terraform/language/backend/s3) · [S3-compat locking en OCI (Oracle, ahora superado)](https://docs.oracle.com/en/learn/terraform-tfstate-file-locking-s3-backend/index.html)

- **Resume command**: responde esta decisión (backend elegido) y borra este archivo (o esta entrada, si queda otra), luego `/sdd:design infra-dev-terraform` para fijar `backend.tf`/D-correspondiente con la elección, o directamente `/sdd:tasks infra-dev-terraform` si la elección no cambia nada más del diseño ya escrito.

---

## Entry 2 — Tenancy de Oracle Cloud inexistente (prerequisito de `run`)

- **Phase**: run (anticipado desde design/proposal)
- **Type**: `decision` (needs the user — es una acción humana, no delegable a un agente: registro de cuenta, verificación de email/teléfono, elección de home region)
- **What & why**: el usuario confirmó que todavía no se ha registrado en Oracle Cloud. Ninguna task de `terraform apply` real ni de configuración de secrets de GitHub Actions puede ejecutarse ni verificarse end-to-end sin esa tenancy — está marcado como `EXTERNAL_DEPENDENCY` en la propuesta y explícitamente fuera del alcance de verificación automática de este change (ver proposal.md, "Out of scope"). Esto no bloquea `tasks`/`run` para escribir y verificar el código (Terraform + CI se verifican con `validate`/`fmt`/`plan` sin credenciales y build multi-arch en CI, per R1-R6) — sí bloquea cualquier verificación que dependa de una cuenta real, y el propio `apply` inicial.
- **Recomendación práctica** (del ADR 0001, ya documentada): al crear la tenancy, elegir **Frankfurt o Singapur** como home region (mitiga el riesgo de "out of host capacity" para instancias Ampere A1) — la home region no se puede cambiar después sin recrear la cuenta.
- **Resume command**: una vez creada la tenancy y generadas las credenciales de API (tenancy OCID, user OCID, fingerprint, private key), añade los secrets al repo de GitHub y ejecuta `/sdd:run infra-dev-terraform` (o, si `run` ya completó todo lo verificable sin credenciales, dispara manualmente el workflow `infra-dev.yml` con `action: plan` como primera verificación real contra la cuenta).
