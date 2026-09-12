# Proposal: whatsapp-dev-credentials-render

## Why

`whatsapp-cloud-adapter` entregó el adaptador real y `app/core/config.py` ya declara y valida las
cinco variables (`WHATSAPP_PROVIDER`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`) — `.env.example` las documenta en detalle
(líneas 171-196) y explica incluso que `WHATSAPP_PROVIDER` no es un secreto. `human-reply-outbound-delivery`
acaba de cerrar el último tramo que dependía de que la respuesta del humano saliera por un canal
real, WhatsApp incluido. Pero el pipeline de despliegue de dev (`app-deploy-dev`) nunca aprendió a
escribir ninguna de las cinco: el paso "Render .env" de `deploy-dev.yml` no las menciona, y
`infra/environments/dev/main.tf` no tiene ningún `oci_vault_secret` para ellas. Así que hoy, aunque
alguien active `WHATSAPP_PROVIDER=meta` a mano en la VM, el próximo deploy trunca y regenera el
`.env` (comportamiento ya especificado en `app-deploy-dev.md`) y se lo lleva por delante — el canal
WhatsApp real nunca puede sobrevivir a un redeploy en dev.

## What changes

Las cuatro variables sensibles (`WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_APP_SECRET`, `WHATSAPP_WEBHOOK_VERIFY_TOKEN`) entran por el mecanismo ya establecido para
credenciales externas que Terraform no genera (mismo patrón que `github_app_private_key`): una
variable Terraform sensible por cada una, inyectada por Actions secret vía `TF_VAR_*` en
`infra-dev.yml`, escrita a un `oci_vault_secret` propio (`autohostai-<env>-whatsapp-*`) y leída
**por nombre** en el paso "Render .env" de `deploy-dev.yml` — mismo mecanismo que el token del
túnel, los cuatro secretos de medios y los seis `SMTP_*`. `WHATSAPP_PROVIDER` no es un secreto (el
propio `.env.example` ya lo aclara) y sigue el patrón de `PUBLIC_HOSTNAME`: variable de repo
(`vars.WHATSAPP_PROVIDER`) leída directamente en el workflow, sin pasar por Vault ni por Terraform.
Ningún cambio en `app/core/config.py`, en el adaptador ni en el webhook — ya existen y ya validan
estas cinco variables; este change es exclusivamente el tramo de aprovisionamiento e infraestructura
que falta entre el Vault/GitHub y el `.env` que la VM arranca.

## Requirements

### R1 — Las cuatro credenciales sensibles de Meta como secretos de Terraform

**As a** operador de infraestructura, **I want** que `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`,
`WHATSAPP_APP_SECRET` y `WHATSAPP_WEBHOOK_VERIFY_TOKEN` se aprovisionen como código, **so that**
ningún valor real de estas credenciales se configure a mano en la VM ni en la consola de OCI.

Acceptance criteria:

1. THE SYSTEM SHALL declarar cuatro variables Terraform sensibles (`sensitive = true`) en
   `infra/environments/dev/variables.tf`, una por credencial — mismo patrón que
   `github_app_private_key`.
2. THE SYSTEM SHALL escribir cada una a un `oci_vault_secret` propio con nombre determinista
   `autohostai-${var.env}-whatsapp-<credencial>` en `infra/environments/dev/main.tf` — mismo
   mecanismo que el token del túnel, los cuatro secretos de medios y los seis `SMTP_*`.
3. THE SYSTEM SHALL conceder al dynamic group del runner (`dev_runner`) permiso de lectura sobre
   los cuatro secretos nuevos, ampliando la policy existente que ya enumera el resto de secretos
   leídos por nombre.
4. THE SYSTEM SHALL NOT generar ningún valor de estas cuatro credenciales con Terraform
   (`random_*` o similar): son credenciales externas de la App de Meta, y Terraform solo las
   transporta, igual que hace con `github_app_private_key`.

### R2 — Los cuatro secretos llegan a Terraform por Actions secret

**As a** operador desplegando la infraestructura de dev, **I want** que las cuatro credenciales de
Meta lleguen a `terraform apply` por el mismo canal que la clave privada de la GitHub App, **so
that** ningún valor real se commitee ni se pegue a mano en la consola de OCI.

Acceptance criteria:

1. THE SYSTEM SHALL definir cuatro GitHub Actions secrets nuevos (uno por credencial) y
   mapearlos a `TF_VAR_whatsapp_access_token`, `TF_VAR_whatsapp_phone_number_id`,
   `TF_VAR_whatsapp_app_secret` y `TF_VAR_whatsapp_webhook_verify_token` en los pasos `plan` y
   `apply` de `infra-dev.yml` — mismo patrón que `TF_VAR_github_app_private_key`.
2. THE SYSTEM SHALL NOT registrar estos cuatro secretos con el provider `github` de Terraform: esa
   gestión-como-código del lado GitHub es alcance de `infra-github-iac` (roadmap, no completado),
   y este change usa el mecanismo manual ya vigente para todos los demás Actions secrets del
   proyecto.

### R3 — El deploy de dev escribe las cinco `WHATSAPP_*` en el `.env` de runtime

**As a** operador desplegando a dev, **I want** que el paso "Render .env" de `deploy-dev.yml`
escriba las cinco variables `WHATSAPP_*` en cada deploy, **so that** el canal WhatsApp sobreviva a
un redeploy en vez de depender de un valor puesto a mano en la VM.

Acceptance criteria:

1. WHEN el paso "Render .env" de `deploy-dev.yml` corre, THE SYSTEM SHALL leer del Vault **por
   nombre** los cuatro secretos `autohostai-${ENV}-whatsapp-*` — mismo mecanismo (`read_secret_by_name`)
   ya usado para el token del túnel, los secretos de medios y los `SMTP_*`.
2. THE SYSTEM SHALL leer `WHATSAPP_PROVIDER` de la variable de repo `vars.WHATSAPP_PROVIDER` —
   mismo patrón que `PUBLIC_HOSTNAME` — sin pasar por Vault ni por Terraform, porque no es un
   secreto (ya documentado así en `.env.example`).
3. THE SYSTEM SHALL escribir las cinco `WHATSAPP_PROVIDER`, `WHATSAPP_ACCESS_TOKEN`,
   `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_APP_SECRET` y `WHATSAPP_WEBHOOK_VERIFY_TOKEN` al
   `$RUNTIME_ENV_FILE` en cada ejecución del paso.
4. IF `vars.WHATSAPP_PROVIDER` no está definida, THEN THE SYSTEM SHALL escribir
   `WHATSAPP_PROVIDER=` (vacío) — el mismo valor por defecto que `.env.example` deja a propósito,
   que `app/core/config.py` ya resuelve a `"mock"` sin fallar el arranque.
5. IF cualquiera de los cuatro secretos Vault-por-nombre de R1 no se puede leer, THEN THE SYSTEM
   SHALL fallar el paso "Render .env" nombrando la clave ausente, antes de tocar contenedores —
   mismo contrato fail-fast que el resto de secretos por nombre de este mismo paso.

### R4 — Ningún valor real en el repo

**As a** cualquiera que lea el repositorio, **I want** que ningún valor real de estas cinco
variables aparezca commiteado, **so that** las credenciales de la App de Meta de dev no se filtren
por control de versiones.

Acceptance criteria:

1. THE SYSTEM SHALL NOT commitear ningún valor real de las cinco `WHATSAPP_*` en `.env.example`,
   en ningún workflow ni en ningún fichero de Terraform — `.env.example` sigue con los cinco
   nombres sin valor (ya así hoy; este change no lo toca).

## Out of scope

- **El adaptador `WhatsAppCloudAdapter`, el webhook y la validación de `Settings`**: ya entregados
  por `whatsapp-cloud-adapter`; este change no toca `backend/`.
- **Activar `WHATSAPP_PROVIDER=meta` en dev**: este change deja el mecanismo listo para que el
  operador ponga la variable de repo cuando tenga credenciales reales de Meta que provisionar;
  no decide ni fuerza ese valor.
- **Staging/prod**: `steering/infra.md` es explícito en que son decisiones propias y futuras; este
  change es solo `dev`.
- **Provider `github` de Terraform** para gestionar los cuatro Actions secrets nuevos como código:
  es `infra-github-iac`, entrada de roadmap separada: este change usa el mecanismo manual ya
  vigente para todos los demás secrets del proyecto.
- **Pantalla de settings/integraciones (FE)** para configurar WhatsApp desde la UI: fuera de
  alcance, no forma parte de este change de infraestructura.

## Affected specs

- `sdd/specs/infra-dev-terraform.md` — documenta las cuatro variables Terraform sensibles, los
  `oci_vault_secret` de WhatsApp y su alta en la policy del runner (R1), y el `TF_VAR_*` nuevo en
  `infra-dev.yml` (R2).
- `sdd/specs/app-deploy-dev.md` — documenta los cuatro secretos `WHATSAPP_*` nuevos leídos del
  Vault por nombre, `WHATSAPP_PROVIDER` como variable de repo, y su fail-fast en "Render .env"
  (R3).
