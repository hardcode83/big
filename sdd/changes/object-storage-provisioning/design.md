# Design: object-storage-provisioning

## Context

La costura ya está puesta y no hay que rehacerla:
`backend/app/integrations/infrastructure/storage/s3.py` declara
`build_s3_client(*, region_name=None, endpoint_url=None)` y `S3FileStorage.__init__(*, bucket,
client)` **recibe** el cliente inyectado; `ConfiguredFileStorageFactory`
(`.../storage/__init__.py`) ya rechaza `S3` con `StorageWriteError` cuando `s3_bucket` viene vacío
y nunca cae a `LOCAL`. Lo que falta es todo lo de fuera. El único punto de cableado es
`get_file_storage_factory` en `backend/app/cleaning/api/dependencies.py:198`, que hoy construye la
factoría **solo** con `signing_key`: ni bucket, ni región, ni endpoint, ni un `s3_client_factory`
configurado. `backend/app/core/config.py` no tiene ningún ajuste de almacén.

En infra, `infra/environments/dev/main.tf` es un único root module con providers `oci` +
`cloudflare`, un Vault (`oci_kms_vault.dev` + `oci_kms_key.dev_secrets`) donde Terraform ya escribe
`postgres_password`, `jwt_secret_key`, `encryption_key`, la clave de la GitHub App y el token del
túnel, y una `oci_identity_policy.dev_runner_read_secrets` con **un solo statement** que enumera por
OCID exactamente qué secretos puede leer el runner. `infra/environments/dev/iam-policy.md` versiona
la policy de `svc-terraform-dev`, que un admin de la tenancy aplica a mano.

El canal Terraform → VM es **el Vault leído por nombre**: `/etc/autohostai-deploy.env` lo escribe
`cloud-init` y `metadata` es ForceNew con `ignore_changes`, así que Terraform no puede reescribirlo
en la máquina viva (design D3 de `ingress-https-dev`). El paso «Render .env» de
`.github/workflows/deploy-dev.yml:160` ya tiene las dos funciones (`read_secret` por OCID,
`read_secret_by_name` por nombre) y escribe el `.env` que `docker-compose.deploy.yml` interpola.

El tenant de `dev` y su `TenantConfig` los crea `backend/app/cli/bootstrap.py:123`, con
`storage_type` en su default de columna (`LOCAL`). `make seed-demo` lo **completa**, no lo crea.

El camino completo —de Terraform a boto3, y de la URL prefirmada al navegador— está dibujado en
[`2026-08-15_object-storage-provisioning-flujo.svg`](2026-08-15_object-storage-provisioning-flujo.svg).

## Decisions

### D1 — Proveedor: OCI Object Storage por su API compatible con S3, en la tenancy que ya existe

**Chosen:** OCI Object Storage, en la misma tenancy y el mismo compartment que la VM de `dev`
(ADR 0001). No añade proveedor, cuenta ni factura; el bucket se declara con el provider `oci` que el
root module ya tiene cargado, y el backend le habla con boto3 apuntado por `endpoint_url`, sin SDK de
OCI en ninguna parte (R4.2).

Rejected: AWS S3 — cuenta, facturación y proveedor nuevos para el único entorno que hoy existe.
Rejected: Cloudflare R2 — el PRD lo nombra primero y es válido, pero añade una segunda relación de
proveedor cuando ya hay una viva (el túnel) y no aporta nada que OCI no dé aquí.
Rejected: MinIO autoalojado en la VM de `dev` — pone la durabilidad de las fotos sobre el mismo disco
que ya se juega el resto del stack, y sigue exigiendo credenciales y aprovisionamiento.

### D2 — El endpoint compatible se **deriva**, no se escribe: `data.oci_objectstorage_namespace` + `var.region`

**Chosen:** `data "oci_objectstorage_namespace"` da el namespace y el endpoint se compone como
`https://<namespace>.compat.objectstorage.<region>.oraclecloud.com`, con `var.region` como única
entrada. Es lo que R1.1 pide (namespace por data source, nunca a mano) y lo que hace que el mismo
código sirva en otro entorno sin editar una URL.

Rejected: variable con la URL completa — reintroduce a mano exactamente el dato que el data source
publica, y se desincroniza el día que cambie la región.

### D3 — Direccionamiento **path-style**, y solo cuando hay `endpoint_url`

**Chosen:** `build_s3_client` añade `s3={"addressing_style": "path"}` a la `Config` **únicamente**
cuando recibe un `endpoint_url`; sin endpoint (AWS) se deja el comportamiento por defecto de boto3.

Es una decisión forzada por el proveedor, no una preferencia: en OCI el estilo virtual-hosted vive en
**otro host** (`<bucket>.vhcompat.objectstorage...`) y **solo funciona para buckets creados a través
de la propia API S3** — un bucket creado por Terraform (API nativa) no lo soporta. Con el
`addressing_style` en `auto`, botocore construiría `<bucket>.<namespace>.compat.objectstorage...`,
que no existe, y **todas** las llamadas y todas las URL prefirmadas fallarían por DNS. MinIO y R2
también prefieren path-style, así que la regla «endpoint propio ⇒ path» es correcta para los tres
proveedores no-AWS de la matriz.

Rejected: fijar path-style siempre — cambiaría el comportamiento contra AWS S3, que es justo el caso
que R3.4 quiere dejar en «no configurar nada».
Rejected: un cuarto ajuste `S3_ADDRESSING_STYLE` — configuración que nadie va a variar, derivable de
la presencia del endpoint.

### D4 — Tres ajustes nuevos, y las credenciales **no** son ajustes

**Chosen:** `Settings` gana `s3_bucket`, `s3_region` y `s3_endpoint_url`, los tres `str = ""`
(R3.1: el default vacío preserva el comportamiento actual — `LOCAL` intacto, `S3` fallando ruidoso).
Las credenciales **no** entran en `Settings`: `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` viajan por
la cadena estándar de boto3 (R2.1), que es el mecanismo que la spec ya exige y el que mantiene el
secreto fuera de todo objeto de configuración serializable.

Rejected: leerlas como campos de `Settings` y pasarlas a `boto3.client(...)` — las mete en un objeto
que se imprime en cualquier `repr` de depuración y contradice `file-storage.md` §El adaptador `S3`.

### D5 — El cableado va en `get_file_storage_factory`, con `functools.partial`

**Chosen:** `get_file_storage_factory` (`backend/app/cleaning/api/dependencies.py`) pasa
`s3_bucket=settings.s3_bucket` y
`s3_client_factory=partial(build_s3_client, region_name=settings.s3_region or None,
endpoint_url=settings.s3_endpoint_url or None)`. La firma
`s3_client_factory: Callable[[], Any]` **no cambia**, así que los tests que ya inyectan un espía
siguen valiendo, y ningún caso de uso lee configuración (R3.2). El `or None` es lo que cumple R3.4:
cadena vacía ⇒ `None` ⇒ boto3 resuelve el endpoint de AWS.

Rejected: ampliar la firma a `Callable[[str | None, str | None], Any]` — rompe
`test_storage_factory.py` sin comprar nada; `partial` ya es el punto de enlace.
Rejected: mover `get_file_storage_factory` a `app/integrations/` porque el almacén no es de
`cleaning` — cierto, pero es un refactor con su propio radio (dependencias, overrides de tests) y no
pertenece a este change. Queda anotado, no hecho.

### D6 — Bucket privado, nombre `autohostai-<env>-media`, sin `prevent_destroy`

**Chosen:** `oci_objectstorage_bucket` con `access_type = "NoPublicAccess"` (R1.2),
`storage_tier = "Standard"`, versioning en su default (`Disabled`) y **sin** `lifecycle`
especial. R1.3 (converger sin recrear ni vaciar) sale de que `name`, `namespace` y `compartment_id`
son estables entre `apply`s: el recurso queda `no changes`. Y el borrado accidental ya tiene su
guarda natural — OCI rechaza eliminar un bucket no vacío, así que un `destroy` sobre un bucket con
fotos falla en vez de tragárselas.

Rejected: `prevent_destroy = true` — bloquearía el `terraform destroy` del entorno entero, que es
justamente la propiedad «reproducible desde cero» que `dev` quiere conservar.
Rejected: activar versioning de objetos — es una decisión de **retención**, y la retención está
explícitamente fuera de alcance en el proposal.

### D7 — El usuario IAM, su grupo, su policy y su Customer Secret Key los crea Terraform

**Chosen:** cinco recursos en el root module — `oci_identity_user`, `oci_identity_group`,
`oci_identity_user_group_membership`, `oci_identity_policy` (acotada al bucket y a las operaciones
del adaptador) y `oci_identity_customer_secret_key`. Es lo que R2.2 pide literalmente, y mantiene la
prioridad que el usuario ya fijó en `app-deploy-dev`: *todo como código, cero pasos manuales por
entorno*. La clave se rota con `terraform apply -replace`, no con un humano copiando de una consola.

El precio es real y se declara: `svc-terraform-dev` necesita **dos statements nuevos a nivel de
tenancy**, `manage users` y `manage groups`, y OCI **no permite acotarlos**: no existe
`target.user.name` ni `target.group.name` entre las variables de policy, así que la concesión es
sobre todos los usuarios de la tenancy — incluida la capacidad de acuñar una API key a un
administrador. Lo que evita que esto cambie la frontera de confianza **en clase** es que ya está
cruzada: `manage dynamic-groups` + `manage policies in tenancy` (relajación aceptada en
`app-deploy-dev`) ya permiten a `svc-terraform-dev` fabricarse un dynamic-group y una policy de
`manage all-resources`. Esto amplía la comodidad de la escalada, no su posibilidad. Se documenta como
**segunda relajación consciente** en `iam-policy.md`, con ámbito dev/test y revisión antes de
staging/prod. Planteado y aprobado en el gate de diseño — ver **OQ1**.

El valor de la clave secreta acaba en el `tfstate` (`oci_identity_customer_secret_key.key`), igual
que `POSTGRES_PASSWORD`, `JWT_SECRET_KEY` y `ENCRYPTION_KEY`: cubierto por la excepción dev/test de
`steering/security.md` §8, que apoya en que el bucket del state es privado, versionado y con IAM
mínima.

Rejected: crear usuario + clave **fuera de Terraform** (bootstrap irreducible, procedimiento en
`iam-policy.md`/RUNBOOK) e inyectar el par como variables sensibles desde GitHub Secrets, como ya se
hace con `github_app_private_key` — mantiene `svc-terraform-dev` sin `manage users`, a cambio de un
paso manual por entorno y de una rotación que deja de ser código. Es la alternativa exacta que OQ1
pone sobre la mesa.
Rejected: instance principal en vez de par de claves — la API compatible con S3 de OCI **solo**
autentica con Customer Secret Key; el instance principal no sirve para ese endpoint.
Rejected: reutilizar `svc-terraform-dev` como usuario del bucket — le daría a la aplicación la
credencial que gobierna toda la infraestructura.

### D8 — Policy del usuario del bucket: acotada al bucket y a cuatro permisos

**Chosen:**

```
Allow group autohostai-<env>-media to read buckets in compartment id <c>
  where target.bucket.name = 'autohostai-<env>-media'
Allow group autohostai-<env>-media to manage objects in compartment id <c>
  where all { target.bucket.name = 'autohostai-<env>-media',
              any { request.permission='OBJECT_CREATE',
                    request.permission='OBJECT_READ',
                    request.permission='OBJECT_DELETE',
                    request.permission='OBJECT_OVERWRITE' } }
```

`read buckets` es lo que permite resolver el bucket; los cuatro permisos son exactamente
`put_object` (crear y sobrescribir), `get_object` (que es lo que honra la URL prefirmada) y
`delete_object` — los tres únicos métodos que `S3FileStorage` invoca. `manage objects` a secas
añadiría `OBJECT_INSPECT` sin llamante, así que se enumera (R2.2).

Rejected: `manage object-family in compartment` — concede además gestión de buckets, incluido
borrarlos.

### D9 — Todo lo que la VM necesita viaja por el Vault, leído **por nombre**

**Chosen:** cuatro `oci_vault_secret` nuevos —
`autohostai-<env>-media-access-key-id`, `-media-secret-access-key`, `-media-s3-endpoint`,
`-media-region`— y los cuatro OCID añadidos a la enumeración del statement de
`oci_identity_policy.dev_runner_read_secrets`. El job de deploy los lee con la
`read_secret_by_name` que ya existe (los nombres son deterministas a partir de `ENV`, igual que el
token del túnel) y el nombre del bucket lo deriva del propio `ENV`. Resultado: **cero pasos manuales
por entorno** y una sola fuente de verdad, Terraform.

Dos de los cuatro no son secretos, y conviene decirlo en voz alta: el endpoint y la región van al
Vault porque **es el único canal Terraform → VM que existe hoy**, no porque haga falta cifrarlos.

Rejected: variables de repositorio de GitHub (`vars.S3_ENDPOINT_URL`, `vars.S3_REGION`), como
`OCI_VAULT_ID` — funciona y hay precedente, pero son dos pasos manuales por entorno justo en el
punto que `steering/infra.md` señala como lección de `app-deploy-dev`.
Rejected: derivarlos en el runner desde IMDS + `oci os ns get` — cero configuración, pero añade una
llamada a la API de OCI en el camino crítico del deploy y otro permiso al dynamic group.
Rejected: escribirlos en `/etc/autohostai-deploy.env` — imposible en la VM viva (ForceNew +
`ignore_changes`).

### D10 — `bootstrap.py` **converge** el `storage_type` desde un ajuste nuevo

**Chosen:** `Settings` gana `bootstrap_storage_type: str = "LOCAL"`, validado contra el enum
`StorageType`; `apply_plan` lo aplica al crear el `TenantConfig` **y lo actualiza si difiere** en una
re-ejecución. En `dev` el tenant y su config ya existen, así que sin convergencia el ajuste no
llegaría nunca sin un `UPDATE` a mano — que es exactamente lo que la norma IaC-first y R1.5 no
admiten.

Es la vía del seed que R6.1 pide, y no toca la API: R5.4 de `user-management` sigue vigente y el
`PATCH` de `TenantConfig` sigue devolviendo `422` para `storage_type`. R6.5 se conserva por
construcción: el default de columna sigue siendo `LOCAL` y el default del ajuste también, así que
cualquier tenant creado por cualquier otra vía nace `LOCAL`.

Consecuencia declarada: la idempotencia documentada de `bootstrap` («una segunda ejecución no cambia
nada») pasa a ser **convergencia** («una segunda ejecución deja el estado que declara la
configuración»). El docstring de `apply_plan` y el contador de resultados lo dicen.

Rejected: ponerlo en `seed_demo.py` — no crea ni posee el `TenantConfig`, y su spec declara
explícitamente que no toca `bootstrap.py`.
Rejected: create-only sin convergencia — deja `dev` necesitando un `UPDATE` manual.

### D11 — La aceptación de R5 vive en un ADR nuevo; la spec la cita

> **Enmienda de `/sdd:run` (2026-08-15): el ADR es el 0008, no el 0007.** El número que este design
> escribió estaba ya ocupado por `docs/adr/0007-webhook-event-retry-columns.md`, que entró con
> `reservations-webhooks`. Lo detectó el panel de arquitectura de la sección 1 antes de que nada
> apuntara al fichero equivocado. Cambia el identificador y nada más: el contenido y su hogar único
> son los que D11 decide.

**Chosen:** `docs/adr/0008-object-storage-provider-dev.md` recoge en un solo sitio la elección de
proveedor (D1, con sus alternativas) y la **aceptación escrita** de que la URL prefirmada lleve el
bucket y la clave completa, con las dos alternativas rechazadas de R5.2 (CDN/ruta propia delante del
bucket; servir `S3` por la ruta firmada propia). `sdd/specs/file-storage.md` §Catálogo cerrado de
asimetrías conserva **la regla** y enlaza al ADR para el razonamiento, sin reformularlo — la
disciplina que `steering/security.md` impone tras haber visto la misma afirmación corregida en cinco
copias distintas.

Rejected: dejar la aceptación solo en este `design.md` — los designs se archivan y dejan de ser el
documento que alguien lee al preguntar «¿por qué la clave está en la URL?».
Rejected: duplicar el razonamiento en la spec y en el ADR — dos copias que divergen.

### D12 — R5.3 se cumple con un barrido, no con una edición puntual

**Chosen:** la redacción absoluta de R3.2 sobrevive en cinco sitios de código y documentación vivos,
y se enmienda en todos con un barrido verificable (`grep -rn "storage_key" backend/app docs/
sdd/specs/` más `grep -rn "R3.2" backend/app`). Los archivos de `sdd/changes/archive/` **no se
tocan**: son registro histórico.

Lo que se enmienda (la clave sí aparece **dentro del valor** de una URL prefirmada):

| Sitio | Redacción de hoy |
|---|---|
| `backend/app/audit/domain/value_objects.py:225` | «R3.2 keeps the internal key out of **every** API response» |
| `backend/app/cleaning/application/use_cases.py:468` | idéntica |
| `backend/app/cleaning/application/use_cases.py:1285` | «which R3.2 forbids in **any** response» |
| `backend/app/integrations/infrastructure/storage/s3.py` | módulo: `EXTERNAL_DEPENDENCY: no object store account is provisioned`; `signed_url`: «an infrastructure decision this change does not get to make (the provider is not even chosen)» |
| `sdd/specs/file-storage.md` §Catálogo y §Estado | «Hoy es código inalcanzable», «No hay ningún almacén S3 aprovisionado», `EXTERNAL_DEPENDENCY` |

Lo que **no** se toca porque ya es preciso: `backend/app/cleaning/api/tasks_router.py:437` y `:503`
(dicen «no aparece como **campo** de la respuesta» y ya documentan la asimetría `LOCAL`/`S3`),
`docs/cleaning.md:134` (idem, «no es un **campo** de la respuesta») y `docs/dashboard.md:51`.

R5.4 y R5.5 no piden cambios: la prohibición absoluta para cuerpo, cabeceras y la URL de `LOCAL`
sigue escrita tal cual, y el catálogo de asimetrías sigue teniendo **cuatro** entradas — esta change
no añade ninguna, solo retira la nota de inalcanzabilidad de la primera.

> **Enmienda de `/sdd:run` (2026-08-15): un sitio más en `s3.py`, por la misma razón que los otros.**
> El docstring de la clase `S3FileStorage` afirmaba que el proveedor «is not decided» y que «no ADR,
> spec or steering doc narrows it further». El ADR 0008 lo vuelve falso, así que entra en el barrido
> aunque D12 no lo enumerara: la redacción nueva dice que el proveedor **sí** está decidido para
> `dev` y que staging/prod siguen deliberadamente sin elegir, que es lo cierto en las dos
> direcciones.

### D13 — La matriz de proveedores (R4.5) es una tabla en la spec, y un test la respalda

**Chosen:** `sdd/specs/file-storage.md` gana la tabla de qué vale cada ajuste en cada proveedor:

| Proveedor | `S3_BUCKET` | `S3_REGION` | `S3_ENDPOINT_URL` | Credenciales |
|---|---|---|---|---|
| **OCI Object Storage** (activo en `dev`) | nombre del bucket | identificador OCI (`eu-frankfurt-1`) | `https://<namespace>.compat.objectstorage.<region>.oraclecloud.com` | Customer Secret Key (par acceso/secreto) |
| AWS S3 | nombre del bucket | región AWS (`eu-west-1`) | *vacío* — boto3 resuelve el endpoint | IAM access key o rol de instancia |
| Cloudflare R2 | nombre del bucket | `auto` | `https://<account_id>.r2.cloudflarestorage.com` | token de API de R2 (par acceso/secreto) |
| MinIO | nombre del bucket | `us-east-1` | `http://<host>:9000` | par acceso/secreto de MinIO |

Y el test de R4.4 la hace verificable donde importa: construir la factoría con un endpoint arbitrario
produce un cliente **apuntado a ese endpoint**, comprobado sobre `client.meta.endpoint_url` sin abrir
red (`boto3.client` no llama a nadie al construirse). Se añaden dos guardas más: que
`app/integrations/domain/storage.py` no nombre ningún proveedor (R4.1) y que `oci` no aparezca ni en
las dependencias ni en ningún import del backend (R4.2) — el test que falla el día que alguien cablee
un proveedor por debajo del puerto.

Rejected: levantar MinIO en el compose para probarlo de verdad — fuera de alcance por decisión del
proposal, y el test de endpoint cubre lo que la agnosticidad significa aquí.

> **Enmienda de `/sdd:run` (2026-08-15): la guarda de R4.1 comprueba acoplamiento, no palabras.**
> `tasks.md` 2.1 la describía como un escaneo literal de `domain/storage.py` buscando `oci`, `aws`,
> `s3.`, `endpoint` y `region`. Escrita así habría fallado sobre prosa legítima y no sobre
> acoplamiento: **`S3` es el valor de `StorageType`** y el nombre del protocolo contra el que está
> escrito el puerto; «oracle» aparece en su sentido inglés (*«an existence oracle over the storage
> keyspace»*, *«a signing oracle»*); «endpoint» describe la ruta HTTP **nuestra** que sirve las
> fotos `LOCAL`; y `signature_version` habría chocado con `SIGNATURE_VERSION`, el prefijo de versión
> de nuestra propia firma de URL.
>
> En su lugar, tres guardas sobre lo que sí puede hacer algo: **imports de SDK de proveedor**
> (parseados con AST, así que un alias no escapa), **hostnames de proveedor** (texto, porque un host
> no aparece por accidente) y **símbolos de configuración de almacén definidos por el módulo**
> (`dir()`, no texto). Las cinco se probaron rompiéndolas a propósito durante el panel de la sección
> 2, y las cinco fallaron como debían.
>
> Y una violación real de R4.1 que el escaneo sí habría encontrado y que se corrigió: el docstring de
> `derive_signing_key` decía «in the OCI vault», ahora «in the secret vault».

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| Terraform · bucket | `infra/environments/dev/main.tf` | `data.oci_objectstorage_namespace`, `oci_objectstorage_bucket.media` (`NoPublicAccess`), `locals.media_s3_endpoint` |
| Terraform · IAM | `infra/environments/dev/main.tf` | `oci_identity_user.media`, `oci_identity_group.media`, `oci_identity_user_group_membership.media`, `oci_identity_policy.media_bucket_access` (D8), `oci_identity_customer_secret_key.media` |
| Terraform · Vault | `infra/environments/dev/main.tf` | 4 `oci_vault_secret` (D9) + los 4 OCID añadidos al statement de `oci_identity_policy.dev_runner_read_secrets` |
| Terraform · outputs | `infra/environments/dev/outputs.tf` | `media_bucket_name`, `media_region`, `media_s3_endpoint` (R1.4) y los nombres de los 4 secretos; ningún output con el valor de la clave |
| Terraform · docs | `infra/environments/dev/iam-policy.md`, `README.md`, `RUNBOOK.md` | los dos statements nuevos de `svc-terraform-dev` + `read objectstorage-namespaces`, una sentencia **nueva y aparte** `manage buckets … target.bucket.name='autohostai-<env>-media'` (**no** fusionada con la condición de `object-family` del bucket del state — ver la enmienda de abajo), la segunda relajación consciente, y el procedimiento de rotación de la Customer Secret Key |

> **Enmienda de `/sdd:run` (2026-08-15): el bucket de medios NO se añade a la condición de
> `object-family`.** Era una línea menos y así estaba escrito aquí, pero `object-family` incluye
> `OBJECT_READ` y `OBJECT_DELETE`: le habría dado a `svc-terraform-dev` —cuya credencial es un
> secret de GitHub Actions— lectura y borrado de **todas las fotos de todos los tenants**. Terraform
> solo declara el bucket, nunca un objeto, así que lleva su propia sentencia con `manage buckets`,
> que el panel de CI/CD verificó suficiente para crear, refrescar y destruir el recurso.
| CD | `.github/workflows/deploy-dev.yml` | leer los 4 secretos por nombre y escribir `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` al `.env` |
| Compose | `docker-compose.deploy.yml`, `docker-compose.yml` | las cinco variables en el `environment:` **solo del servicio `backend`** — el único que escribe y sirve ficheros |
| Backend · config | `backend/app/core/config.py` | `s3_bucket`, `s3_region`, `s3_endpoint_url`, `bootstrap_storage_type` (+ validador contra `StorageType`) |
| Backend · cliente | `backend/app/integrations/infrastructure/storage/s3.py` | `addressing_style="path"` condicionado al `endpoint_url` (D3); docstrings de D12 |
| Backend · cableado | `backend/app/cleaning/api/dependencies.py` | `get_file_storage_factory` pasa bucket y `partial(build_s3_client, ...)` |
| Backend · seed | `backend/app/cli/bootstrap.py` | `storage_type` al crear y convergencia al re-ejecutar (D10) |
| Backend · redacción | `backend/app/audit/domain/value_objects.py`, `backend/app/cleaning/application/use_cases.py` | enmiendas de D12 |
| Tests | `backend/tests/integrations/test_storage_factory.py`, nuevo `test_storage_provider_agnostic.py`, `backend/tests/cli/` (bootstrap) | R4.4, R4.1, R4.2, R3.3, R3.4, D10 |
| Entorno | `.env.example` | las cinco variables con valor vacío, con comentario nombrando el proveedor activo (R2.4, R3.5) |
| Specs / docs | `sdd/specs/file-storage.md`, `infra-dev-terraform.md`, `app-deploy-dev.md`, `seed-data-demo.md`, `cleaning.md`; `docs/adr/0008-...`, `docs/cleaning.md`, `README.md` | matriz (R4.5), aceptación (R5), estado, variables de despliegue, tenant de demo |
| Steering | `sdd/steering/security.md` | la enumeración de la regla 8 pasa de tres credenciales de entorno a cuatro (OQ2), con su radio de daño |

## Data & interfaces

**Esquema de base de datos: ninguno.** `TenantConfig.storage_type` ya existe con su enum y su
default; solo cambia el valor de una fila en `dev`.

**Contrato de API: ningún endpoint nuevo y ningún campo nuevo.**

> **Enmienda de `/sdd:run` (2026-08-15): este párrafo decía «Contrato de API: ninguno» y que
> `backend/openapi.json` no se regenera, y las dos cosas resultaron falsas.** El barrido de D12
> enmendó el docstring de `CleaningPhotoResponse`, y **Pydantic publica el docstring de un modelo de
> respuesta como su `description`**, así que el docstring *es* contrato. Se regeneraron las dos
> mitades que `steering/documentation.md` exige — `backend/openapi.json` y
> `frontend/lib/api/generated/openapi.d.ts` — y `api:check` las da por sincronizadas. Lo que sigue
> siendo cierto, y es lo que este párrafo quería decir: **ningún consumidor tiene que cambiar nada**. Lo único que cambia para un consumidor es el **valor** del campo `url` de una foto para el
tenant que pase a `S3`: URL absoluta del proveedor en vez de relativa — consecuencia ya documentada
en el catálogo de asimetrías, no un cambio de contrato.

**Variables de entorno nuevas (cinco).** Las tres primeras son ajustes de `Settings`; las dos
últimas **no** lo son y las consume boto3 por su cadena estándar:

| Variable | Valor por defecto | Dónde |
|---|---|---|
| `S3_BUCKET` | `""` | `.env.example`, `.env` del deploy, `backend` en ambos composes |
| `S3_REGION` | `""` | idem |
| `S3_ENDPOINT_URL` | `""` | idem |
| `AWS_ACCESS_KEY_ID` | `""` | idem — nunca en un fichero versionado con valor |
| `AWS_SECRET_ACCESS_KEY` | `""` | idem |

Más `BOOTSTRAP_STORAGE_TYPE` (default `LOCAL`), que solo lee el CLI de bootstrap y se pasa en línea
al ejecutarlo (`docker compose exec -e BOOTSTRAP_STORAGE_TYPE=S3 backend python -m app.cli.bootstrap`),
porque el deploy **trunca** el `.env` en cada ejecución.

**Outputs de Terraform:** `media_bucket_name`, `media_region`, `media_s3_endpoint`,
`media_access_key_secret_name`, `media_secret_key_secret_name`, `media_endpoint_secret_name`,
`media_region_secret_name`. Ninguno expone la clave secreta (R2.3); el `id` del recurso —la parte
pública del par— tampoco se publica como output porque no hace falta.

## Risks & mitigations

- **Las fotos ya subidas del tenant de demo dejan de servirse.** Al pasar a `S3`, la factoría
  resuelve el adaptador nuevo y `GET /api/v1/cleaning-photos/{id}` devuelve `404` para ese tenant:
  las filas siguen apuntando a claves que están en disco. Es literalmente el peligro que R5.4 de
  `user-management` nombra. *Mitigación*: comprobar `SELECT count(*) FROM cleaning_photos` para ese
  tenant **antes** de convergir, y si no es cero, decidir explícitamente (ver **OQ4**).
- **El sufijo del host del endpoint.** La documentación de Oracle publica hoy
  `<ns>.compat.objectstorage.<region>.oci.customer-oci.com` y el histórico
  `...oraclecloud.com` sigue siendo válido. *Mitigación*: el endpoint es un `local` de una línea y
  vive en el Vault, así que corregirlo es un `apply`; la comprobación real es la verificación R6.
- **Path-style es obligatorio y su fallo es silencioso hasta la primera llamada.** Sin D3 no falla
  el arranque: falla la primera subida, con un error de DNS. *Mitigación*: test que afirma el
  `addressing_style` resuelto del cliente cuando hay endpoint, y la verificación R6.
- **El `apply` de infra y el deploy solo corren desde `main`.** Ni el bucket ni las variables
  existen antes del merge, así que R6 **no se puede verificar en local ni en el PR**. *Mitigación*:
  procedimiento post-merge numerado (ver **OQ3**); el código es inerte hasta entonces, porque con
  `S3_BUCKET` vacío nada cambia.
- **Cuatro secretos nuevos y un statement de policy más largo.** La causa de fallo más probable al
  sumar secretos, ya nombrada en el design D4 de `app-deploy-dev`, es olvidar el OCID en la
  enumeración: el deploy falla nombrando la clave, que es el comportamiento correcto. *Mitigación*:
  los cuatro entran en el mismo `apply` que los crea.
- **Coste.** Bucket Standard + objetos: dentro de la capa gratuita de OCI para el volumen de `dev`,
  pero el presupuesto está en €1 con alerta ACTUAL y FORECAST, así que un desvío avisa solo.

## Cobertura de requisitos

| Req | Dónde queda |
|---|---|
| R1.1 | D2, D6 — namespace por data source; el compartment viene de `var.compartment_ocid`, como todos los demás recursos del módulo: es una variable de entrada, no un OCID escrito a mano |
| R1.2 | D6 (`NoPublicAccess`) |
| R1.3 | D6 — atributos estables ⇒ `no changes`; el borrado no vacío lo rechaza OCI |
| R1.4 | outputs `media_bucket_name`, `media_region`, `media_s3_endpoint` |
| R1.5 | Ningún paso queda fuera de Terraform salvo la policy de `svc-terraform-dev`, que ya es por diseño de admin de tenancy y está versionada en `iam-policy.md` |
| R2.1 | D4 — credenciales por la cadena de boto3, nunca en `Settings` |
| R2.2 | D7 + D8 — se cumple literal; **OQ1** resuelta a favor de Terraform |
| R2.3 | Ningún output con la clave; `dev.tfvars.example` no gana ninguna entrada nueva |
| R2.4 | `.env.example` con los dos nombres vacíos, + la enmienda de la regla 8 (**OQ2**) |
| R3.1 | D4 — tres ajustes, default `""` |
| R3.2 | D5 |
| R3.3 | **Sin cambio de código**: `ConfiguredFileStorageFactory.storage_for` ya lo hace y `test_s3_without_a_configured_bucket_fails_loudly` ya lo cubre. Se conserva |
| R3.4 | D5 (`or None`) + D3 |
| R3.5 | `.env.example` y el `.env` del deploy vía D9 |
| R4.1 | D13 (test de ausencia de proveedor en `domain/storage.py`) |
| R4.2 | D13 (test de ausencia de `oci` en dependencias e imports) |
| R4.3 | **Sin cambio**: las dos costuras se conservan; D3 solo añade una `Config` derivada del endpoint |
| R4.4 | D13 |
| R4.5 | D13 (tabla en la spec) |
| R5.1, R5.2 | D11 (ADR 0008) |
| R5.3 | D12 |
| R5.4, R5.5 | **Sin cambio** — D12 explica por qué |
| R6.1 | D10 |
| R6.2, R6.3, R6.4 | Verificación post-merge (**OQ3**) |
| R6.5 | D10 — default de columna y default del ajuste, ambos `LOCAL` |

## Open questions

**Las cuatro se plantearon y se resolvieron en el gate de `/sdd:design` (Jose, 2026-08-15).** Quedan
escritas con su resolución porque cada una es una decisión con consecuencias que las tareas heredan,
no una duda que se pueda borrar una vez contestada.

**OQ1 — ¿Se conceden `manage users` y `manage groups` en tenancy a `svc-terraform-dev`?**
Es lo que R2.2 exige tal como está escrita, y OCI no permite acotar ninguno de los dos. El argumento
a favor es que `manage policies` + `manage dynamic-groups` ya hacen a ese usuario escalable, así que
esto amplía la comodidad y no la posibilidad; el argumento en contra es que `manage users` permite
acuñar credenciales a cualquier usuario existente, y eso es un camino más corto y menos ruidoso.
La alternativa completa está descrita en D7 (usuario y clave fuera de Terraform, par inyectado como
variable sensible desde GitHub Secrets, como la clave de la GitHub App) y cuesta un paso manual por
entorno.

> **Resuelta: sí, todo por Terraform.** D7 queda tal como está escrita y R2.2 no cambia. Los dos
> statements nuevos se documentan en `iam-policy.md` como **segunda relajación consciente del mínimo
> privilegio**, con ámbito dev/test y revisión pendiente antes de staging/prod — el mismo formato y
> el mismo compromiso que la primera (`app-deploy-dev`, 2026-07-29).

**OQ2 — Amplía este change la enumeración cerrada de la regla 8 de `steering/security.md`.**
Esa regla lista hoy las credenciales de proveedor que viven en el entorno —`PMS_API_KEY`,
`CHANNEX_API_KEY`, `BEDS24_REFRESH_TOKEN`— y dice «**esas tres y nada más**».
`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` serían la cuarta. No hay forma de cumplir R2.1 (cadena
estándar del proveedor) sin ampliarla.

> **Resuelta: se amplía a cuatro.** Este change **edita `steering/security.md`** para añadir el par
> del almacén a la enumeración de la regla 8, diciendo qué es (credencial de proveedor que vive en el
> entorno, por eso esta regla y no la 3) y cuál es su radio de daño: **el bucket de un entorno**, ni
> la tenancy ni la cuenta —a diferencia de `BEDS24_REFRESH_TOKEN`, que la propia regla marca como
> credencial de cuenta. Es una edición de steering dentro de un change, así que se hace en su propia
> tarea y con su propia justificación, no de paso.

**OQ3 — R6 solo se puede verificar después del merge; ¿se acepta la secuencia?**
`infra-dev.yml` y `deploy-dev.yml` solo corren desde `main`.

> **Resuelta: se acepta la secuencia post-merge.** No se parte el change en dos. El orden obligado
> queda como procedimiento del change:
>
> 1. Merge del PR. **La aplicación queda inerte**: `S3_BUCKET` vacío ⇒ ningún comportamiento
>    cambia en la VM.
>
>    **Corrección de `/sdd:run` (2026-08-15): «inerte» no quiere decir «sin CI en rojo».** El
>    filtro de rutas de `deploy-dev.yml` (`backend/**`, `docker-compose.deploy.yml`,
>    `.github/workflows/deploy-dev.yml`) cubre este change, así que el merge **dispara un deploy
>    automático que falla** en «Render .env»: los cuatro secretos del Vault no existen hasta el
>    paso 2. Es el comportamiento que este mismo design llama correcto al hablar del riesgo de
>    los secretos nuevos, y es seguro — el paso falla **antes** del `pull` y del `up`, así que la
>    VM sigue sirviendo la versión anterior sin tocar. Se acepta a sabiendas: evitarlo exigiría o
>    bien tolerar secretos ausentes (perdiendo justo el fail-fast que mitiga «olvidar un OCID en
>    la policy»), o bien manipular el filtro de rutas por un problema de una sola vez.
> 2. `terraform apply` (`workflow_dispatch`, desde `main`) → bucket, IAM, Customer Secret Key y los
>    cuatro secretos del Vault.
> 3. **Re-lanzar** el deploy → ahora el paso «Render .env» rellena las cinco variables.
> 4. `SELECT count(*) FROM cleaning_photos` del tenant de demo (ver OQ4) y, si es cero,
>    `docker compose exec -e BOOTSTRAP_STORAGE_TYPE=S3 backend python -m app.cli.bootstrap` en la VM.
> 5. Subir una foto de limpieza de la demo, abrir la URL prefirmada **sin credenciales** y comprobar
>    `200` y `Content-Type: image/jpeg` (R6.2, R6.3).
> 6. Registrar la evidencia nombrando qué se subió y qué se obtuvo (R6.4) y **entonces**
>    `/sdd:archive`.
>
> Entre (1) y (6) el change lleva una entrada en `BLOCKED.md` de tipo `deferred` que nombra el paso
> pendiente y su comando de reanudación; `/sdd:archive` se niega a cerrar mientras exista.

**OQ4 — ¿Qué se hace con las fotos `LOCAL` que ya tenga el tenant de demo de `dev`?**
Al convergir a `S3` dejan de servirse (`404`): las filas siguen apuntando a claves que están en
disco. Es literalmente el peligro que R5.4 de `user-management` nombra.

> **Resuelta: comprobar que no hay ninguna y seguir.** El paso 4 de OQ3 es esa comprobación, y es
> **bloqueante**: si el recuento no es cero, no se converge y se decide entonces entre borrar las
> filas o volver a subirlas a mano. Migrar de verdad sigue fuera de alcance por decisión del
> proposal.
