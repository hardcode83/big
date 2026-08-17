# 0008 — Proveedor del almacén de objetos en `dev`, y la clave en la URL prefirmada

## Estado

Aceptado — 2026-08-15. Decidido por Jose en el gate de diseño del change `object-storage-provisioning` (D1, D11, D13; OQ1–OQ4).

**La decisión 1 no es una desviación del PRD; la decisión 2 sí, y conviene decirlo en voz alta.** La línea 196 del PRD dice *«Producción futura: S3-compatible (Cloudflare R2 o AWS S3)»* y deliberadamente no elige, así que elegir OCI llena un hueco abierto y no contradice nada.

La decisión 2 es distinta: la línea 198 dice *«Nunca exponer paths internos directamente al cliente»*, sin excepción, y aceptar que la URL prefirmada lleve la clave **relaja exactamente esa línea**. Se registra aquí como desviación consciente en lugar de enmendar el PRD, que es documento cerrado (`sdd/project.md`): el alcance de la relajación es el **valor de la URL prefirmada de `S3`** y nada más, y la regla 5 de `sdd/steering/security.md` —que es la norma viva que hereda esa línea— lleva la excepción escrita con este mismo alcance. Fuera de ahí, la línea 198 sigue vigente tal cual.

## Contexto

El camino `S3` del puerto de ficheros estaba **muerto por falta de aprovisionamiento, no de código**. `cleaning-photos-storage` dejó el puerto en `domain/`, la factoría por tenant y `S3FileStorage` **recibiendo** el cliente inyectado, pero no existía bucket, ni región, ni `endpoint_url`, ni credenciales: un tenant con `storage_type = S3` recibía `502` en cada subida.

Elegir proveedor era, por tanto, lo único que faltaba — y con ello llegaban dos preguntas que no se podían aplazar más:

1. **Cuál**, sabiendo que el entorno `dev` ya corre en Oracle Cloud ([ADR 0001](0001-dev-hosting-provider.md)).
2. **Qué se hace con la contradicción** entre la URL prefirmada y R3.2 de `cleaning-photos-storage`, que prohíbe exponer la clave interna. Aprovisionar sin resolverla habría incumplido un requisito en silencio en el mismo commit.

## Decisión 1 — OCI Object Storage, por su API compatible con S3

El bucket vive en la **misma tenancy y el mismo compartment** que la VM de `dev`. No añade proveedor, ni cuenta, ni factura: el bucket se declara con el provider `oci` que el root module ya tenía cargado, y el backend le habla con **boto3 apuntado por `endpoint_url`**, sin SDK de OCI en ninguna parte.

Eso último es la parte que importa a medio plazo: **`S3` aquí es el protocolo, no el proveedor**. Esta decisión elige un proveedor sin cerrar la puerta, y hay un test que falla el día que alguien la cierre (`backend/tests/integrations/test_storage_provider_agnostic.py`).

### Alternativas descartadas

**AWS S3.** Cuenta, facturación y relación de proveedor nuevas para el único entorno que hoy existe. Es la opción por defecto de la industria y por eso se consideró en serio; lo que la descarta no es técnico sino de coste organizativo.

**Cloudflare R2.** El PRD lo nombra primero y es perfectamente válido. Se descarta porque añadiría una **segunda** relación con Cloudflare cuando ya hay una viva (el túnel de ingress, [ADR 0003](0003-https-ingress-dev.md)) y no aporta nada que OCI no dé aquí. Sigue siendo el candidato más probable si algún día `dev` deja Oracle Cloud.

**MinIO autoalojado en la VM de `dev`.** Pone la durabilidad de las fotos sobre el mismo disco que ya se juega el resto del stack, y sigue exigiendo credenciales y aprovisionamiento — paga el precio sin comprar la propiedad.

### Consecuencia declarada: dos statements nuevos a nivel de tenancy

Crear el usuario del bucket y su Customer Secret Key **por Terraform** obliga a conceder `manage users` y `manage groups` a `svc-terraform-dev`, y **OCI no permite acotar ninguno de los dos**: no existe `target.user.name` ni `target.group.name` entre las variables de policy.

Se acepta como **segunda relajación consciente del mínimo privilegio**, con ámbito dev/test y revisión pendiente antes de staging/prod. El argumento que la hace aceptable es que la frontera ya estaba cruzada: `manage dynamic-groups` + `manage policies in tenancy` (primera relajación, `app-deploy-dev`, 2026-07-29) ya permiten a ese usuario fabricarse un dynamic-group y una policy de `manage all-resources`. Esto amplía la **comodidad** de la escalada, no su posibilidad. Detalle, tabla de verbos y la alternativa completa en [`infra/environments/dev/iam-policy.md`](../../infra/environments/dev/iam-policy.md).

## Decisión 2 — Se acepta que la URL prefirmada lleve el bucket y la clave completa

`generate_presigned_url` construye una dirección que el propio almacén honrará, así que `tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.jpg` aparece en la ruta o en la query, junto al nombre del bucket. **Es parte del protocolo de firma y no se puede retirar**: una URL prefirmada no tiene a nadie en medio que resuelva la clave, que es precisamente lo que la hace prefirmada.

Se acepta, y la razón es que **la clave no dice nada**: se compone únicamente de identificadores que el propio sistema generó — un literal, el UUID del tenant, el UUID de la tarea y el UUID de la foto. No hay ningún nombre de fichero elegido por el usuario, ningún dato de negocio y ninguna ruta fuera del almacén. Lo que sí revela es el UUID del tenant —ya conocido por el destinatario, porque es el suyo— y la disposición interna del bucket.

**La prohibición sigue siendo absoluta para todo lo demás**: cuerpo de la respuesta, cabeceras, y la URL del adaptador `LOCAL`, que publica solo `Path(key).stem` porque apunta a una ruta nuestra que sabe resolver la clave. La asimetría vive en el catálogo cerrado de `sdd/specs/file-storage.md` y **no crece**: esta decisión no añade ninguna entrada. Lo que hará es **retirar** la nota de «código inalcanzable» de una que ya estaba (`file-storage.md:192`) — en futuro, no en pasado: la spec se actualiza en `/sdd:archive`, y hasta entonces la nota sigue escrita y sigue siendo cierta, porque el bucket no existe hasta el `apply` post-merge.

### Alternativas descartadas

**Un CDN o una ruta propia delante del bucket.** Es la única que oculta la clave de verdad. Se descarta porque añade un componente de infraestructura nuevo con su dominio, su TLS, su caché y su coste — una decisión de infra con su propio alcance, no un detalle de este change. Si algún día se quiere ocultar la clave, esta es la vía.

**Servir `S3` por la ruta firmada propia**, como hace `LOCAL`. Anula el motivo entero de usar URLs prefirmadas y mete todo el tráfico de fotos por el backend, que es exactamente el coste que el adaptador `S3` existe para evitar.

## Matriz de proveedores compatibles

Es la forma de que «agnóstico» sea verificable y no una afirmación. Cambiar de proveedor es dar otros valores a estas cuatro columnas:

| Proveedor | `S3_BUCKET` | `S3_REGION` | `S3_ENDPOINT_URL` | Credenciales |
|---|---|---|---|---|
| **OCI Object Storage** (activo en `dev`) | nombre del bucket | identificador OCI (`eu-frankfurt-1`) | `https://<namespace>.compat.objectstorage.<region>.oraclecloud.com` | Customer Secret Key (par acceso/secreto) |
| AWS S3 | nombre del bucket | región AWS (`eu-west-1`) | *vacío* — boto3 resuelve el endpoint | IAM access key o rol de instancia |
| Cloudflare R2 | nombre del bucket | `auto` | `https://<account_id>.r2.cloudflarestorage.com` | token de API de R2 (par acceso/secreto) |
| MinIO | nombre del bucket | `us-east-1` | `http://<host>:9000` | par acceso/secreto de MinIO |

Las credenciales **nunca** son ajustes de la aplicación: viajan por la cadena estándar de boto3 (`AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`), que es lo que las mantiene fuera de cualquier objeto de configuración serializable.

**Un detalle no evidente de la tabla: un `S3_ENDPOINT_URL` no vacío activa además el direccionamiento *path-style*.** No es una preferencia, es una obligación del proveedor: en OCI el estilo virtual-hosted vive en otro host (`<bucket>.vhcompat.objectstorage…`) y **solo funciona para buckets creados a través de la propia API S3** — uno creado por Terraform (API nativa) no lo soporta, así que con el estilo por defecto **todas** las llamadas y todas las URL prefirmadas fallarían por DNS. R2 y MinIO también prefieren path-style, y AWS —el único caso sin endpoint— se queda con el comportamiento por defecto de boto3, que es lo que hace que apuntar a AWS sea *no configurar nada*.

## Consecuencias

- El aprovisionamiento entero es código: bucket, usuario IAM, grupo, policy acotada al bucket y a cuatro permisos de objeto, Customer Secret Key y cuatro secretos del Vault. **Cero pasos manuales por entorno**, y la rotación de la clave es `terraform apply -replace` (RUNBOOK §9.1).
- `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` amplían a **cuatro** la enumeración cerrada de credenciales de entorno de la regla 8 de `sdd/steering/security.md`. Su radio de daño es el bucket de **un entorno** — ni la tenancy, ni la cuenta.
- El valor de la clave secreta acaba en el `tfstate`, igual que `POSTGRES_PASSWORD`, `JWT_SECRET_KEY` y `ENCRYPTION_KEY`: cubierto por la excepción dev/test de esa misma regla, que se apoya en que el bucket del state es privado, versionado y con IAM mínima.
- **Staging y producción no heredan esta decisión.** `sdd/steering/infra.md` deja esos entornos sin proveedor elegido, y la revisión de la relajación de IAM es una condición previa.
- Revertir a otro proveedor es cambiar cuatro valores de configuración y aplicar otro Terraform. Eso es la propiedad que este ADR compra, y el test de agnosticidad es lo que evita que se pierda sin que nadie se entere.
