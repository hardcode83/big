# IAM — usuario de servicio de Terraform (mínimo privilegio)

Terraform y el pipeline se autentican como el usuario de servicio **`svc-terraform-dev`** (solo API key, sin login de consola), miembro del grupo **`autohostai-dev-terraform`**. Este documento versiona la policy mínima que ese grupo necesita, para auditarla y reproducirla.

**Por qué ESTA policy no está en el root module:** el propio usuario de Terraform no puede auto-otorgarse su IAM. El grupo, el usuario y **esta** policy los crea/aplica un **admin de la tenancy** en la consola OCI (Identity Domains) — fuera de `main.tf`. (Distinto del instance-principal del runner —`oci_identity_dynamic_group`/`oci_identity_policy` en `main.tf`—: esos SÍ los aplica el pipeline, posible gracias a la ampliación de abajo.)

## Grupo y usuario
- Grupo (normal, no dynamic): `autohostai-dev-terraform`.
- Usuario de servicio: `svc-terraform-dev` (solo API key), miembro del grupo.
- Las credenciales (OCID de usuario, fingerprint, private key) van a `dev.tfvars` (local) y a los secrets de GitHub `OCI_USER_OCID`/`OCI_FINGERPRINT`/`OCI_PRIVATE_KEY`.

## Policy (a nivel de tenancy — los recursos viven hoy en el compartment raíz)

```
Allow group autohostai-dev-terraform to manage virtual-network-family in tenancy
Allow group autohostai-dev-terraform to manage instance-family in tenancy
Allow group autohostai-dev-terraform to manage volume-family in tenancy
Allow group autohostai-dev-terraform to read instance-images in tenancy
Allow group autohostai-dev-terraform to manage object-family in tenancy where target.bucket.name='autohostai-tfstate-dev'
Allow group autohostai-dev-terraform to manage usage-budgets in tenancy
Allow group autohostai-dev-terraform to manage vaults in tenancy
Allow group autohostai-dev-terraform to manage keys in tenancy
Allow group autohostai-dev-terraform to manage secret-family in tenancy
Allow group autohostai-dev-terraform to read compartments in tenancy
Allow group autohostai-dev-terraform to manage dynamic-groups in tenancy
Allow group autohostai-dev-terraform to manage policies in tenancy
```

> Si el grupo está en un domain distinto del Default, cualificar: `Allow group 'NombreDominio'/'autohostai-dev-terraform' to ...`.

**Ampliación 2026-07-29 (change `app-deploy-dev`):** las dos últimas sentencias (`manage dynamic-groups` + `manage policies`) se añadieron para que el **pipeline** cree como IaC el instance-principal del runner self-hosted (el `oci_identity_dynamic_group` + `oci_identity_policy` de `main.tf`, que leen del Vault la clave de la GitHub App y los secrets de runtime). **Es una relajación consciente del mínimo privilegio**: `svc-terraform-dev` gana gestión de identidad a nivel tenancy (podría crear dynamic-groups que matcheen cualquier recurso → superficie de escalada). Decisión del usuario, priorizando "todo como código, cero pasos manuales por entorno" sobre acotar ese verbo. Alternativa rechazada: aplicar esos dos recursos a mano por un admin (mantendría el mínimo privilegio, a costa de un paso manual por entorno).

## Verificado
- `terraform plan` (provider con `svc-terraform-dev`): lee/refresca compute, red, budget y vault sin errores de autorización.
- `terraform init` (backend con `svc-terraform-dev`): lee el bucket del state (`object-family`).
- Ambos ejecutados el 2026-07-22, sin fallos de permisos.

## Mejora futura
Un compartment `dev` dedicado permitiría acotar la policy `in compartment dev` en vez de `in tenancy` (los budgets seguirían a nivel de tenancy). Requiere mover los recursos actuales — fuera de alcance de este change.
