# Infraestructura real del entorno dev (Terraform + CI/CD)

## Purpose

Terraform real y pipeline de CI/CD para el entorno `dev` de AutoHostAI en Oracle Cloud Infrastructure, según `docs/adr/0001-dev-hosting-provider.md` (addendum 2026-07-21: tenancy en Pay-As-You-Go conservando la capa gratuita a $0 — change `infra-dev-payg`): una VM única (Ampere A1) ejecutando el `docker-compose.yml` del repo. Cubre red, cómputo, backend de state remoto, alerta de presupuesto, backup de credenciales en OCI Vault, IAM de mínimo privilegio, y los workflows de GitHub Actions que validan y aplican ese Terraform — sin desplegar todavía la aplicación en sí ni tocar `staging`/`prod`.

## Requirements

### Red y cómputo (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL aprovisionar una VCN (`10.0.0.0/16`) con una subred pública (`10.0.1.0/24`), internet gateway y route table.
- THE SYSTEM SHALL acotar el security list de la subred a **un único puerto de entrada, el 22 (SSH)**, restringido a `var.allowed_ssh_cidrs` (ningún `0.0.0.0/0` de entrada), generando una regla por (CIDR × puerto) con un bloque `dynamic`. Los puertos 8000 y 3000 se retiraron en `ingress-https-dev`: la aplicación se sirve por Cloudflare Tunnel mediante una conexión saliente, así que no necesita exposición entrante. Ver spec `ingress-https-dev`.
- THE SYSTEM SHALL aprovisionar una única instancia `VM.Standard.A1.Flex` (4 OCPU/24 GB, boot volume 200 GB, dentro del grant Always Free que la tenancy PAYG conserva a $0), fijada en AD-3 vía `var.ad_number` (default 3), con imagen Ubuntu 22.04 ARM64 resuelta vía `data.oci_core_images` — nunca un OCID hardcodeado.
- THE SYSTEM SHALL inyectar por `cloud-init` las claves de `var.ssh_authorized_keys` (`list(string)`) al usuario `ubuntu`, e instalar Docker + Compose vía el **repositorio APT oficial de Docker** (`docker-ce`, `docker-compose-plugin`, arm64) — nunca `docker-compose-plugin` de los repos por defecto de Ubuntu (no existe ahí).
- THE SYSTEM SHALL declarar `lifecycle { ignore_changes = [metadata] }` en la instancia: el `metadata` (user_data/claves) es ForceNew en el provider `oci`, así que cambiarlo recrearía la VM; la lista de claves y el cloud-init definen el arranque de una VM nueva, y las altas/rotaciones de clave sobre la VM viva se hacen out-of-band por SSH (ver `RUNBOOK.md`).
- THE SYSTEM SHALL asociar una IP pública reservada (no efímera) a la instancia.
- El `cloud-init` (movido a `cloud-init.yaml.tftpl` vía `templatefile()`) provisiona además el **runner self-hosted de GitHub Actions** del CD y declara el **instance principal** (`oci_identity_dynamic_group` + `oci_identity_policy` de mínimo privilegio) que lo autoriza a leer del Vault; el comportamiento del CD se especifica en `app-deploy-dev`.
- WHEN algún elemento de `var.allowed_ssh_cidrs` no es un CIDR IPv4 con prefijo ≥ /24, o `var.ssh_authorized_keys` está vacía / con formato inválido, THE SYSTEM SHALL rechazar el `plan`/`apply` en la validación de variables.
- THE SYSTEM SHALL admitir rangos SSH más anchos **solo** por `var.allowed_ssh_cidrs_wide`, lista aparte con su propio suelo (≥ /16, que sigue rechazando /8 y `0.0.0.0/0`) y vacía por defecto; ambas listas se concatenan en `local.ingress_cidrs` conservando cada una su validación. Va separada para que abrir un rango ancho siga siendo una decisión explícita en vez de colarse en una lista donde todo lo demás es un /32 — el 22 es la **única** vía de entrada a la máquina. Uso actual: el `/16` de una operadora con IP dinámica, que llevaba tiempo puesto **a mano en la consola** hasta que el primer `plan` posterior propuso borrarlo.
- THE SYSTEM SHALL leer los CIDRs y las claves de operadores desde secrets con forma de **array JSON** (`ALLOWED_SSH_CIDRS`, `SSH_PUBLIC_KEYS`), cayendo a los secrets singulares históricos mientras los plurales estén vacíos. El singular admitía **un solo operador**, y eso es lo que empujaba a añadir los demás por consola, donde el siguiente `apply` los borraba sin avisar.

### Almacén de objetos de medios (`infra/environments/dev/main.tf`)

Aprovisionado por `object-storage-provisioning`. Su comportamiento de aplicación se especifica en `file-storage`; aquí está lo que declara Terraform.

- THE SYSTEM SHALL declarar el bucket `autohostai-<env>-media` con `access_type = "NoPublicAccess"` y `storage_tier = "Standard"`, obteniendo el **namespace por data source** (`data.oci_objectstorage_namespace`) y nunca escribiéndolo a mano, igual que el `compartment_ocid` viene de variable.
- THE SYSTEM SHALL componer el endpoint compatible con S3 como `https://<namespace>.compat.objectstorage.<region>.oraclecloud.com` en un `local`, derivado y no escrito: una variable con la URL completa se desincronizaría el día que cambie la región.
- THE SYSTEM SHALL declarar sin `prevent_destroy` ni versioning de objetos: la reproducibilidad desde cero de `dev` es deliberada, y el borrado accidental ya tiene guarda natural porque OCI rechaza eliminar un bucket no vacío. La retención es una decisión aparte, sin tomar.
- THE SYSTEM SHALL crear por Terraform los cinco recursos de identidad del usuario del bucket —usuario, grupo, membresía, policy y Customer Secret Key— de modo que la rotación de la clave sea `terraform apply -replace` y no un humano copiando de una consola.
- THE SYSTEM SHALL acotar la policy de ese usuario a **dos statements**: `read buckets` por `target.bucket.name`, y `manage objects` por bucket y por los **cuatro** `request.permission` que el adaptador usa (`OBJECT_CREATE`, `OBJECT_READ`, `OBJECT_DELETE`, `OBJECT_OVERWRITE`). `manage objects` a secas añadiría `OBJECT_INSPECT` sin llamante, y `manage object-family` concedería además gestión de buckets.
- THE SYSTEM SHALL declarar el usuario con `email`: esta tenancy usa **Identity Domains (IDCS)**, que rechaza crear un usuario sin email primario aunque sea de servicio y no inicie sesión jamás. El fallo llega a mitad del `apply`, con los recursos anteriores ya creados.
- THE SYSTEM SHALL escribir al Vault cuatro secretos (`-media-access-key-id`, `-media-secret-access-key`, `-media-s3-endpoint`, `-media-region`) y añadir sus cuatro OCID a la enumeración de `oci_identity_policy.dev_runner_read_secrets` **en el mismo `apply` que los crea**. Dos de los cuatro no son secretos: el endpoint y la región van al Vault porque es el único canal Terraform → VM que existe hoy.
- THE SYSTEM SHALL exponer como `output` el nombre del bucket, la región, el endpoint y los **nombres** de los cuatro secretos, y THE SYSTEM SHALL NOT exponer el valor de la Customer Secret Key en ningún output.

### Backend de state remoto (`infra/environments/dev/backend.tf`)

- THE SYSTEM SHALL usar el backend nativo `oci` con configuración parcial — namespace, bucket, región y credenciales por `-backend-config`, nunca hardcodeados en el repo; autenticación por `private_key_path` (ruta a fichero), nunca el PEM inline.
- THE SYSTEM SHALL requerir Terraform >= 1.12 (versión mínima con backend `oci`).
- El bucket de Object Storage (`autohostai-tfstate-dev`) se crea manualmente una vez fuera de este Terraform (dependencia circular), con **versioning activado**; el procedimiento de recuperación del state (restaurar una versión previa del objeto) está en `RUNBOOK.md`.
- THE SYSTEM SHALL ejecutarse (provider y backend) como el usuario de servicio **`svc-terraform-dev`**, miembro de un grupo con **policy IAM** acotada a los recursos gestionados (compute, red, budgets, object-family del bucket del state, vault/keys/secrets, y — desde `app-deploy-dev` — `dynamic-groups`/`policies` para el instance principal del runner), versionada en `iam-policy.md` y aplicada por un admin de la tenancy. La inclusión de `manage dynamic-groups/policies in tenancy` es una **relajación consciente** del mínimo privilegio (superficie de escalada), documentada y de ámbito dev/test; a revisar antes de staging/prod. Desde `object-storage-provisioning` hay una **segunda relajación consciente**, con el mismo ámbito y el mismo compromiso de revisión: `manage users` y `manage groups` en tenancy, que OCI no permite acotar —no existe `target.user.name` ni `target.group.name`—, necesarias para crear por código el usuario del bucket y su clave. Lo que evita que mueva la frontera de confianza *en clase* es que la primera ya la había cruzado: con `manage dynamic-groups` + `manage policies` ese usuario ya podía fabricarse una policy de `manage all-resources`. Amplía la comodidad de la escalada, no su posibilidad. El bucket de medios lleva además una sentencia **nueva y aparte** (`manage buckets` acotado por nombre) y **no** se fusiona con la condición de `object-family` del bucket del state: `object-family` habría concedido `OBJECT_READ` y `OBJECT_DELETE` sobre todas las fotos de todos los tenants.

### Alerta de presupuesto (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL crear un `oci_budget_budget` mensual de importe `var.budget_amount` (default **1**) más **dos** `oci_budget_alert_rule`: una `ACTUAL` y una `FORECAST`, ambas `threshold_type = ABSOLUTE` al importe del presupuesto, notificando a `var.budget_alert_recipients` (`list(string)`, default Jose + Marta).
- IF `var.budget_alert_recipients` está vacía, THEN THE SYSTEM SHALL rechazar el `plan`/`apply`.

### Backup de la clave SSH en OCI Vault (`infra/environments/dev/main.tf`)

- THE SYSTEM SHALL crear un `oci_kms_vault` (tipo `DEFAULT`) y un `oci_kms_key` **software-protected** (Always Free, $0).
- THE SYSTEM SHALL mantener la clave privada SSH como secret del Vault **subido out-of-band** (OCI CLI, ver `RUNBOOK.md`), **nunca como recurso Terraform con contenido inline** — para que el valor en claro no llegue al `tfstate`.
- Desde `app-deploy-dev`, el Vault aloja además secrets **gestionados por Terraform**: los de runtime de la app (`POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `ENCRYPTION_KEY`) generados con `random_*`, y la clave privada de la GitHub App (inyectada desde un GitHub Secret vía var sensible). Sus valores **sí** residen en el `tfstate` — relajación aceptada de la regla anterior para dev/test (`steering/security.md` §8), no aplicable a la clave SSH. Ver `app-deploy-dev`.

### Pipeline de GitHub Actions (`.github/workflows/infra-dev.yml`)

- WHEN se abre/actualiza un PR que toca `infra/environments/dev/**`, THE SYSTEM SHALL ejecutar el job `check` (`terraform fmt -check`, `init -backend=false`, `validate`) sin ningún secret.
- THE SYSTEM SHALL exponer un único camino a recursos reales: `workflow_dispatch` con input `action` (`plan`|`apply`), en dos jobs — `plan` (init→validate→plan, para revisión por logs) y `apply` (re-planifica y aplica en el mismo job). El `plan` **no** usa `-out` ni sube el `tfplan` como artifact: desde `app-deploy-dev` el plan contiene secrets (clave de la App + secrets generados) y un artifact es descargable por cualquiera con read del repo.
- THE SYSTEM SHALL ejecutar los jobs `plan` **y** `apply` **solo desde `main`** (`if: github.ref == 'refs/heads/main'`), con `concurrency` (serializa applies sobre el mismo state) y `timeout-minutes`; todas las GitHub Actions fijadas por **SHA de commit**. El gating de `plan` se añadió en `ingress-https-dev`: desde ese change el job recibe un API token con control del DNS y del TLS de toda una zona, y `sensitive = true` no impide desredactarlo desde código de una rama no revisada. Consecuencia operativa: no se puede planificar desde una rama de feature, así que el `plan`/`apply` de un change de infra ocurre tras el merge.
- El gate de aprobación es **convención** (review de PR + `apply` manual desde `main`): en repo privado + plan Free NO hay Environments con required reviewers ni branch protection/rulesets (la API devuelve 403). Lo forzado técnicamente es que el `apply` solo corre contra `main`; el "PR revisado antes de merge" es un modelo de confianza de operadores. Enforcement real requeriría GitHub Pro/Team o repo público.

### Provider de Cloudflare (desde `ingress-https-dev`)

- El **API token de Cloudflare** tiene un radio de daño que va más allá de la zona DNS: permite publicar en internet cualquier dirección alcanzable desde el contenedor del túnel, porque la configuración de ingress es remota. La enumeración canónica y actualizada vive en [ADR 0003](../../docs/adr/0003-https-ingress-dev.md) §Addendum 2026-08-04 §1, y esta spec **no la reformula** a propósito.
- THE SYSTEM SHALL declarar el provider `cloudflare` en el **mismo root module** que `oci`, porque el `oci_vault_secret` del token del túnel depende de atributos de recursos Cloudflare y ambos deben resolverse en un solo `apply`.
- El comportamiento de los recursos de Cloudflare (túnel, routing, CNAME, ajuste de zona) y sus variables se especifica en `ingress-https-dev`.
- El **API token de Cloudflare** es bootstrap irreducible (se acuña en el dashboard) y **no** se copia al Vault, a diferencia de la clave de la GitHub App: su radio abarca toda la zona y es re-emitible en segundos.

### Build multi-arch (`.github/workflows/multiarch-build-check.yml`)

- WHEN se modifica `backend/devops/Dockerfile`, `frontend/devops/Dockerfile` o sus lockfiles, THE SYSTEM SHALL construir ambas imágenes (`target: prod`) para `linux/amd64` y `linux/arm64` sin publicar a registry — verifica que corren en la arquitectura ARM64 de la instancia.

## Key files

- `infra/environments/dev/{main.tf,variables.tf,outputs.tf,backend.tf}` — Terraform real.
- `infra/environments/dev/{backend.hcl.example,dev.tfvars.example}` — plantillas, sin valores reales.
- `infra/environments/dev/README.md` — uso, estado y secrets esperados; `RUNBOOK.md` — operación/recuperación; `iam-policy.md` — policy IAM mínima versionada.
- `.github/workflows/{infra-dev.yml,multiarch-build-check.yml}` — pipelines.
- `docs/adr/0001-dev-hosting-provider.md` — decisión de proveedor (con addendum PAYG).

## Estado y pendientes

- Infra **desplegada y operativa** (aplicada por el pipeline como `svc-terraform-dev`): instancia 4 OCPU/24 GB/200 GB en AD-3 (PAYG, $0), Docker+Compose vía repo oficial, budget €1 con alertas ACTUAL+FORECAST, Vault + key + secret SSH recuperable, versioning del state activo. Añadido por `app-deploy-dev`: runner self-hosted (cloud-init) + instance principal + secrets de runtime y clave de la App en el Vault. Añadido por `ingress-https-dev`: provider `cloudflare` con el túnel/DNS/ajuste de zona, el secreto del túnel en el Vault, y el security list reducido a **solo el 22**.
- El **despliegue de la aplicación** ya está resuelto por el change **`app-deploy-dev`** (build → GHCR → deploy local en el runner self-hosted) y su **acceso público** por **`ingress-https-dev`** (Cloudflare Tunnel); ver sus specs. El repo vive en la org **`autohostai-labs`**.
- **Cerrado por `ingress-https-hardening`** (2026-08-04): la policy del runner queda con **un solo statement** (`read secret-bundles` condicionado por la enumeración de OCID). El `read secrets` sin condición no se acotó sino que se **eliminó**, porque nunca fue necesario: `GetSecretBundleByName` exige solo `SECRET_BUNDLE_READ`. Aplicado in situ (`0 added, 1 changed, 0 destroyed`) y verificado con un deploy real cuyo paso de lectura del Vault pasó.
