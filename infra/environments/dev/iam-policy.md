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
Allow group autohostai-dev-terraform to manage buckets in tenancy where target.bucket.name='autohostai-dev-media'
Allow group autohostai-dev-terraform to read objectstorage-namespaces in tenancy
Allow group autohostai-dev-terraform to manage users in tenancy
Allow group autohostai-dev-terraform to manage groups in tenancy
Allow group autohostai-dev-terraform to manage usage-budgets in tenancy
Allow group autohostai-dev-terraform to manage vaults in tenancy
Allow group autohostai-dev-terraform to manage keys in tenancy
Allow group autohostai-dev-terraform to manage secret-family in tenancy
Allow group autohostai-dev-terraform to read compartments in tenancy
Allow group autohostai-dev-terraform to manage dynamic-groups in tenancy
Allow group autohostai-dev-terraform to manage policies in tenancy
Allow group autohostai-dev-terraform to manage email-family in tenancy
```

> Si el grupo está en un domain distinto del Default, cualificar: `Allow group 'NombreDominio'/'autohostai-dev-terraform' to ...`.

**Ampliación 2026-07-29 (change `app-deploy-dev`):** las dos últimas sentencias (`manage dynamic-groups` + `manage policies`) se añadieron para que el **pipeline** cree como IaC el instance-principal del runner self-hosted (el `oci_identity_dynamic_group` + `oci_identity_policy` de `main.tf`, que leen del Vault la clave de la GitHub App y los secrets de runtime). **Es una relajación consciente del mínimo privilegio**: `svc-terraform-dev` gana gestión de identidad a nivel tenancy (podría crear dynamic-groups que matcheen cualquier recurso → superficie de escalada). Decisión del usuario, priorizando "todo como código, cero pasos manuales por entorno" sobre acotar ese verbo. Alternativa rechazada: aplicar esos dos recursos a mano por un admin (mantendría el mínimo privilegio, a costa de un paso manual por entorno).

**Ampliación 2026-08-15 (change `object-storage-provisioning`) — SEGUNDA relajación consciente del mínimo privilegio.** El change aprovisiona el bucket de fotos, su usuario IAM y su Customer Secret Key **por Terraform** (R2.2), y eso obliga a cuatro cambios en esta policy:

| Sentencia | Para qué | ¿Acotable? |
|---|---|---|
| `manage buckets … target.bucket.name='autohostai-dev-media'` (sentencia **nueva y aparte**) | crear y gestionar el bucket de medios | **Sí** — por nombre de bucket, igual que el del state |
| `read objectstorage-namespaces in tenancy` | el `data "oci_objectstorage_namespace"` del que se deriva el endpoint compatible (R1.1: el namespace nunca se escribe a mano) | No hace falta: solo lee un identificador de la tenancy, sin acceso a ningún dato |
| `manage users in tenancy` | crear `autohostai-dev-media` y su Customer Secret Key | **No.** OCI no expone `target.user.name` entre las variables de policy |
| `manage groups in tenancy` | crear el grupo al que se dirige la policy del bucket | **No.** Tampoco existe `target.group.name` |

**Sentencia aparte y `manage buckets`, no `manage object-family`, y el motivo importa**: añadir el bucket de medios a la condición de la sentencia del state habría sido una línea menos, pero `object-family` incluye `OBJECT_READ` y `OBJECT_DELETE` — le habría dado a `svc-terraform-dev`, cuya credencial es un secret de GitHub Actions, lectura y borrado de **todas las fotos de todos los tenants**. Terraform solo declara el bucket (`oci_objectstorage_bucket.media`), nunca un objeto, así que `manage buckets` es todo lo que necesita.

**Las dos últimas son la relajación, y hay que decir qué concede: `manage users` permite acuñar una API key a cualquier usuario de la tenancy, incluido un administrador.** Lo que evita que esto mueva la frontera de confianza *en clase* es que ya estaba cruzada por la primera relajación: `manage dynamic-groups` + `manage policies in tenancy` ya permiten a `svc-terraform-dev` fabricarse un dynamic-group y una policy de `manage all-resources`. Esto amplía la **comodidad** de la escalada, no su posibilidad.

Decisión del usuario en el gate de diseño (OQ1, 2026-08-15), con la misma prioridad que la primera: *todo como código, cero pasos manuales por entorno* — y aquí compra además que la rotación de la clave sea `terraform apply -replace` en vez de un humano copiando de una consola. **Ámbito dev/test, y revisión pendiente antes de staging/prod**, igual que la primera.

Alternativa rechazada, descrita entera porque es la que habría que retomar si la revisión decide lo contrario: crear el usuario y su Customer Secret Key **fuera de Terraform** (procedimiento en el RUNBOOK) e inyectar el par como variables sensibles desde GitHub Secrets, tal como ya se hace con `github_app_private_key`. Mantiene `svc-terraform-dev` sin `manage users`, a cambio de un paso manual por entorno y de una rotación que deja de ser código.

**Ampliación 2026-09-02 (change `smtp-delivery-adapter`) — nueva sentencia, no una relajación del mismo tipo que las dos anteriores.** El change aprovisiona el relay de OCI Email Delivery por Terraform (D6 de `design.md`): `oci_email_email_domain`, `oci_email_dkim` y `oci_email_sender` son un **tipo de recurso nuevo** para esta policy, `email-family`, que ninguna sentencia anterior cubre — a diferencia de `manage users`/`manage groups`/`manage buckets`, que solo ampliaron el alcance de verbos ya usados por otro recurso.

`manage email-family in tenancy` y no `use`: `svc-terraform-dev` necesita crear y actualizar estos recursos (`EMAIL_DOMAIN_CREATE`, `APPROVED_SENDER_CREATE`, y sus equivalentes de DKIM), no solo enviar correo con ellos — enviar (`SmtpSend`, permiso `APPROVED_SENDER_USE`) es un verbo **distinto y mucho más acotado** que sí se aplica al usuario de servicio `autohostai-${var.env}-smtp` que el propio `main.tf` crea, vía `oci_identity_policy.smtp_send_access` (`Allow group autohostai-${var.env}-smtp to use approved-senders in compartment id ...`) — esa policy la aplica el pipeline como parte del mismo apply, no un admin de la tenancy, porque `svc-terraform-dev` ya tiene `manage policies` (ampliación 2026-07-29) y `email-family`/`use approved-senders` no son verbos que necesiten relajar el mínimo privilegio de ese usuario de servicio SMTP: solo puede enviar correo, nada de gestionar el dominio ni los approved senders.

Mismo precedente que las dos ampliaciones anteriores: una sentencia de tenancy nueva la aplica un **admin de la tenancy en la consola OCI**, fuera de `main.tf`, antes del primer `terraform apply` que declare estos recursos — si no se aplica antes, el `apply` falla con `NotAuthorizedOrNotFound` al crear `oci_email_email_domain.smtp`.

**`smtp_send_access` es mínima en el verbo, no en el alcance, y hay que decirlo con la misma honestidad que el punto 2 de "Policy del runner" de abajo aplica a `var.compartment_ocid`.** El verbo es correcto (`use approved-senders`, el permiso `APPROVED_SENDER_USE` que cubre exactamente `SmtpSend` — nada de `manage`, nada de `email-family`): una credencial SMTP filtrada no puede crear ni modificar dominios ni approved senders. Pero `var.compartment_ocid` es **hoy la raíz de la tenancy** (ver "Mejora futura" al final de este documento), y una concesión ahí la hereda todo compartment descendiente, sin condición que la acote a un `oci_email_sender` concreto — OCI no expone una variable de policy para eso. Consecuencia real: una credencial SMTP filtrada podría enviar como **cualquier** approved sender presente o futuro de la tenancy, no solo como `noreply@mail.${var.public_hostname}`. Se acepta por lo mismo que las dos relajaciones de arriba — *todo como código, cero pasos manuales por entorno* —, y queda ligado a la misma mejora futura: un compartment `dev` dedicado acotaría esta sentencia a `in compartment dev` igual que al resto.

**Sin cambios por el change `ingress-https-dev` (2026-07-29):** el ingress HTTPS añade recursos de **Cloudflare** (otro provider, otra API) más un `oci_vault_secret` y una ampliación de la policy del runner. Ambas cosas caen en verbos que `svc-terraform-dev` ya tiene (`manage secret-family`, `manage policies`), así que **no hace falta ampliar esta policy**.

## Policy del runner (creada por Terraform, no por un admin)

Distinta de la de arriba: la aplica el propio pipeline como IaC (`oci_identity_dynamic_group.dev_runner` + `oci_identity_policy.dev_runner_read_secrets` en `main.tf`). Permite a **la instancia dev** —y solo a ella, por `matching_rule` sobre su OCID— leer del Vault por instance principal, sin credenciales en disco.

```
Allow dynamic-group autohostai-dev-runner to read secret-bundles in compartment id <compartment>
  where any {target.secret.id = '<gh-app-key>',
             target.secret.id = '<postgres-password>',
             target.secret.id = '<jwt-secret-key>',
             target.secret.id = '<encryption-key>',
             target.secret.id = '<cloudflare-tunnel-token>',
             target.secret.id = '<media-access-key-id>',
             target.secret.id = '<media-secret-access-key>',
             target.secret.id = '<media-s3-endpoint>',
             target.secret.id = '<media-region>',
             target.secret.id = '<demo-account-password>',
             target.secret.id = '<smtp-host>',
             target.secret.id = '<smtp-port>',
             target.secret.id = '<smtp-username>',
             target.secret.id = '<smtp-password>',
             target.secret.id = '<smtp-from-email>',
             target.secret.id = '<smtp-use-tls>'}
```

Los seis últimos entran con `smtp-delivery-adapter` (2026-09-02), en el mismo apply que crea los seis secretos (`oci_vault_secret.smtp_*` en `main.tf`) — misma mitigación que los cuatro de medios: olvidar uno haría fallar "Render .env" nombrando la clave, en vez de dejar el runner ciego a un secreto que sí existe.

**Una sola sentencia y una sola clase de condición**, desde el change `ingress-https-hardening` (2026-08-04). Los cuatro de medios entraron con `object-storage-provisioning` (2026-08-15) y el último, `demo-account-password`, con `demo-user` (2026-08-24), cada uno en el mismo `apply` que crea su secreto — que es la mitigación del punto 1 de abajo. Ese último lo lee el workflow `demo-reset` y no el deploy, y lo resuelve **por nombre** como el token del túnel, así que le vale igual esta condición por OCID. **Este bloque es el espejo de `oci_identity_policy.dev_runner_read_secrets` en `main.tf` y tiene que contarlos igual**: si al auditar ves una enumeración viva con más entradas que esta, lo primero que hay que descartar es que este documento se quedó atrás, no que alguien ensanchó el acceso.

Tres cosas a tener presentes al añadir secretos en el futuro:

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

**MEDIDO el 2026-08-04, y la duda queda cerrada por comportamiento, no solo por deducción.** Tras aplicar la policy acotada (`terraform apply`: `0 added, 1 changed, 0 destroyed`, modificación **in situ** en 1 s, sin ventana sin permisos) se lanzó `deploy-dev` por `workflow_dispatch` y el paso **"Render .env" pasó**, leyendo el token del túnel **por nombre** con un único statement condicionado por OCID. Cuatro consecuencias, todas verificadas:

- `GetSecretBundleByName` **no necesita** `SECRET_READ` ni `SECRET_INSPECT`: el statement eliminado era prescindible, como decía la tabla.
- La condición `where any {target.secret.id = …}` **sí se evalúa** en un acceso por nombre, o sea que OCI resuelve nombre→OCID **antes** de autorizar.
- El desconocido que quedaba —que el propio CLI de OCI hiciera un `GetSecret` extra al resolver por nombre, y era de **cliente**, no de política— **no ocurre**.
- La premisa declarada arriba (que la policy versionada sea la única concesión de `SECRET_BUNDLE_READ` que alcance a ese instance principal) queda **corroborada indirectamente**: eliminado el statement sin condición, la lectura sigue funcionando, luego lo que autoriza es el que queda.

No hizo falta recorrer ninguna escalera. Si esto se rompiera algún día, los peldaños siguen siendo (a) reintentar, porque las policies de OCI propagan con consistencia eventual; (b) reponer `read secrets` **con** `where target.vault.id`; (c) leer por OCID exponiéndolo como `output`. Y **nunca** volver a la condición por nombre: por el punto 2 de arriba sería ensanchar el acceso, no arreglarlo.

## Esta tenancy usa Identity Domains (IDCS), y eso condiciona crear usuarios por Terraform

Descubierto el 2026-08-15 al aplicar `object-storage-provisioning`: el primer `apply`
([run 31909392774](https://github.com/autohostai-labs/AutoHostAI/actions/runs/31909392774)) falló al
crear `oci_identity_user.media` con

```
400-IdcsConversionError … "The primary email must be specified."
error.identity.user.primaryEmailNotSpecified
```

**IDCS exige email primario en todo usuario, incluidos los de servicio que nunca inician sesión**; la
IAM clásica no lo pedía. Cualquier `oci_identity_user` que se añada aquí en adelante tiene que
declarar `email`, y la dirección debe ser **única** en el dominio — el patrón adoptado es
plus-addressing sobre un buzón que ya existe (`var.media_user_email`), que evita dar de alta buzones
y evita la colisión con la dirección del usuario humano.

Vale la pena saberlo antes de escribir el recurso: el fallo llega **a mitad del apply**, con los
recursos anteriores ya creados. No es grave —Terraform converge al relanzar— pero deja el entorno a
medias mientras tanto.

## Verificado
- `terraform plan` (provider con `svc-terraform-dev`): lee/refresca compute, red, budget y vault sin errores de autorización.
- `terraform init` (backend con `svc-terraform-dev`): lee el bucket del state (`object-family`).
- Ambos ejecutados el 2026-07-22, sin fallos de permisos.
- **2026-08-15**, con los cuatro statements de `object-storage-provisioning` ya aplicados: el `apply` crea bucket, grupo, policy del bucket y dos secretos del Vault sin ningún error de autorización — las sentencias `manage buckets`, `manage groups` y `read objectstorage-namespaces` quedan así verificadas contra la API real. `manage users` no llegó a ejercerse: el usuario falló antes por el email, no por permisos.

## Mejora futura
Un compartment `dev` dedicado permitiría acotar la policy `in compartment dev` en vez de `in tenancy` (los budgets seguirían a nivel de tenancy). Requiere mover los recursos actuales — fuera de alcance de este change.
