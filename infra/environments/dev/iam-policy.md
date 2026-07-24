# IAM — usuario de servicio de Terraform (mínimo privilegio)

Terraform y el pipeline se autentican como el usuario de servicio **`svc-terraform-dev`** (solo API key, sin login de consola), miembro del grupo **`autohostai-dev-terraform`**. Este documento versiona la policy mínima que ese grupo necesita, para auditarla y reproducirla.

**Por qué no está en el root module:** el propio usuario de Terraform no puede auto-otorgarse IAM (y darle `manage` de IAM contradiría el mínimo privilegio). El grupo, el usuario y la policy los crea/aplica un **admin de la tenancy** en la consola OCI (Identity Domains) — fuera de `main.tf`.

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
```

> Si el grupo está en un domain distinto del Default, cualificar: `Allow group 'NombreDominio'/'autohostai-dev-terraform' to ...`.

## Verificado
- `terraform plan` (provider con `svc-terraform-dev`): lee/refresca compute, red, budget y vault sin errores de autorización.
- `terraform init` (backend con `svc-terraform-dev`): lee el bucket del state (`object-family`).
- Ambos ejecutados el 2026-07-22, sin fallos de permisos.

## Mejora futura
Un compartment `dev` dedicado permitiría acotar la policy `in compartment dev` en vez de `in tenancy` (los budgets seguirían a nivel de tenancy). Requiere mover los recursos actuales — fuera de alcance de este change.
