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

**Sin cambios por el change `ingress-https-dev` (2026-07-29):** el ingress HTTPS añade recursos de **Cloudflare** (otro provider, otra API) más un `oci_vault_secret` y una ampliación de la policy del runner. Ambas cosas caen en verbos que `svc-terraform-dev` ya tiene (`manage secret-family`, `manage policies`), así que **no hace falta ampliar esta policy**.

## Policy del runner (creada por Terraform, no por un admin)

Distinta de la de arriba: la aplica el propio pipeline como IaC (`oci_identity_dynamic_group.dev_runner` + `oci_identity_policy.dev_runner_read_secrets` en `main.tf`). Permite a **la instancia dev** —y solo a ella, por `matching_rule` sobre su OCID— leer del Vault por instance principal, sin credenciales en disco.

```
Allow dynamic-group autohostai-dev-runner to read secret-bundles in compartment id <compartment>
  where any {target.secret.id = '<gh-app-key>',
             target.secret.id = '<postgres-password>',
             target.secret.id = '<jwt-secret-key>',
             target.secret.id = '<encryption-key>',
             target.secret.id = '<cloudflare-tunnel-token>'}
```

**Una sola sentencia y una sola clase de condición**, desde el change `ingress-https-hardening` (2026-08-04). Tres cosas a tener presentes al añadir secretos en el futuro:

1. **Es una enumeración explícita de OCID.** Un secreto nuevo es **invisible** para el runner hasta que se añade a esa lista — es la causa de fallo más probable al sumar secretos, y se manifiesta como un deploy que falla en el paso "Render .env" nombrando la clave. Se mantiene así a propósito: un `read secret-bundles` sin condición daría acceso a todo secreto presente y futuro — y como el compartment es la **raíz de la tenancy** y la concesión se hereda, eso significa de toda la tenancy, no de un compartment acotado.
2. **Por qué la condición NO va por nombre, aunque el deploy lea por nombre.** Es tentador añadir `target.secret.name` para cubrir el `get-secret-bundle-by-name`, y se descartó por una razón de **ámbito**: `compartment_ocid` es hoy la **raíz de la tenancy** (ver §"Mejora futura" abajo), una concesión en la raíz la heredan todos los compartments descendientes, y los nombres de secreto son únicos **por vault**, no por compartment. Una condición por nombre concedería lectura de **contenido** a cualquier secreto que se llamara igual en cualquier vault de la tenancy — es decir, rompería el invariante del punto 1 para ese nombre, reproducible sin más que recrear el vault o levantar un segundo stack con `env = "dev"`. Y además no hace falta: ver el apartado siguiente.
3. **Aquí había una segunda sentencia `read secrets in compartment` sin condición, y se eliminó porque nunca fue necesaria.** La añadió `ingress-https-dev` suponiendo que resolver por nombre exigía leer metadatos del secreto. La [referencia de policies del servicio Vault](https://docs.oracle.com/en-us/iaas/Content/Identity/Reference/keypolicyreference.htm) dice otra cosa:

   | Operación de API | Permiso exigido | Quién lo concede |
   |---|---|---|
   | `GetSecretBundleByName` | `SECRET_BUNDLE_READ` | `read secret-bundles` — la sentencia que queda |
   | `GetSecretBundle` | `SECRET_BUNDLE_READ` | idem |
   | `GetSecret` | `SECRET_READ` | `read secrets` — **eliminada** |
   | `ListSecrets` | `SECRET_INSPECT` | idem |

   El deploy solo invoca `secrets secret-bundle get` y `secrets secret-bundle get-secret-bundle-by-name` (`.github/workflows/deploy-dev.yml`), nunca `GetSecret` ni `ListSecrets`, así que el permiso concedido no lo usaba nadie. La descripción del recurso y este documento afirmaban mínimo privilegio mientras la policy concedía lectura de metadatos de **todos** los secretos presentes y futuros de la tenancy entera (por la herencia desde la raíz); eliminarla hace cierta la afirmación.

**Sobre la duda que este documento dejó abierta** (*"que la condición `where any {target.secret.id = ...}` se evalúe correctamente en un acceso por nombre"*): **resuelta por deducción**, y es lo que permite que la condición siga siendo solo por OCID. `GetSecretBundleByName` exige `SECRET_BUNDLE_READ`; la sentencia condicionada por OCID lo concede y la `read secrets` eliminada **no** (concedía `SECRET_INSPECT`/`SECRET_READ`); el deploy lee el token del túnel por nombre con éxito desde el 2026-07-29. Luego OCI resuelve nombre→OCID **antes** de autorizar.

**Premisa de esa deducción, dicha en voz alta porque no es comprobable desde el repositorio**: que la policy versionada aquí sea la **única** concesión de `SECRET_BUNDLE_READ` (o `secret-family`) que alcance a ese instance principal — no solo la única dirigida al dynamic-group `autohostai-dev-runner`: un `any-user … where request.principal.id = <la instancia>` o un segundo dynamic-group que matchee la misma VM la romperían igual. Este documento registra que parte de las policies las aplica **un admin de la tenancy desde la consola**, fuera de `main.tf`, así que el repositorio no puede establecerlo. Si existiera una concesión a mano, lo que hoy autoriza la lectura por nombre podría ser esa y no esta, y la deducción caería. Se cierra con un comando de solo lectura cuando haya credenciales a mano:

```bash
oci iam policy list --compartment-id <OCID de la raíz de la tenancy> \
  --all --query 'data[].{name:name,statements:statements}' \
  | grep -i -B2 -A2 'autohostai-dev-runner\|secret'
```

Y si esa premisa no se sostuviera, el síntoma sería que el deploy posterior al `apply` falla en "Render .env": la salida es la escalera de abajo, no volver a la condición por nombre (que por el punto 2 sería ensanchar el acceso, no arreglarlo).

Queda un desconocido más pequeño, y es de cliente, no de política: que el propio OCI CLI no haga un `GetSecret` extra al resolver por nombre. Si lo hiciera, el deploy fallaría en "Render .env" tras el `apply`, y la salida es (a) reintentar por si es propagación de la policy, que en OCI es eventual, (b) reponer `read secrets` **con** `where target.vault.id`, o (c) leer por OCID exponiéndolo como `output`. La medición está pendiente del primer deploy posterior al `apply` de este change.

## Verificado
- `terraform plan` (provider con `svc-terraform-dev`): lee/refresca compute, red, budget y vault sin errores de autorización.
- `terraform init` (backend con `svc-terraform-dev`): lee el bucket del state (`object-family`).
- Ambos ejecutados el 2026-07-22, sin fallos de permisos.

## Mejora futura
Un compartment `dev` dedicado permitiría acotar la policy `in compartment dev` en vez de `in tenancy` (los budgets seguirían a nivel de tenancy). Requiere mover los recursos actuales — fuera de alcance de este change.
