# Proposal: object-storage-provisioning

## Why

El camino `S3` del puerto de ficheros está **muerto por falta de aprovisionamiento**, no por falta
de código: `cleaning-photos-storage` dejó el puerto en `domain/`, la factoría por tenant y
`S3FileStorage` recibiendo el cliente **inyectado**, pero no existe `S3_BUCKET`, ni región, ni
`endpoint_url`, ni credenciales en la configuración. Un tenant con `storage_type = S3` recibe hoy
`502` en cada subida (`sdd/specs/file-storage.md` §Estado, `EXTERNAL_DEPENDENCY`).

El PRD (línea 196) deja el proveedor abierto — *«Producción futura: S3-compatible (Cloudflare R2 o
AWS S3)»* — y **AWS no es el favorito**: OCI Object Storage expone una API compatible con S3 y el
entorno `dev` ya corre en Oracle Cloud ([ADR 0001](../../../docs/adr/0001-dev-hosting-provider.md)),
así que poner las fotos ahí no añade proveedor, cuenta ni factura nueva.

Este change arrastra además una obligación heredada que no puede llegar como sorpresa: **D7c** del
diseño de `cleaning-photos-storage`. Detalle completo en `sdd/roadmap/object-storage-provisioning.md`.

## What changes

Después de este change existe un **bucket de OCI Object Storage aprovisionado por Terraform** en el
entorno `dev`, con su usuario IAM, su Customer Secret Key y su política de acceso; los settings que
hoy no existen (`S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`) cableados a `ConfiguredFileStorageFactory`
y publicados en `.env.example` y en el despliegue; el tenant de demo de `dev` con
`storage_type = S3` por la vía del seed, de modo que el camino se ejecuta de verdad al menos una
vez; y la exposición de la clave en la URL prefirmada **aceptada por escrito** con su razón, cerrando
la contradicción con R3.2.

**Lo que este change NO hace es crear la agnosticidad de proveedor: ya está.** `build_s3_client`
acepta un `endpoint_url` arbitrario y el adaptador recibe el cliente construido desde fuera, así que
apuntar a AWS S3, Cloudflare R2 o MinIO es configuración y no código. Lo que aquí se añade es lo que
lo mantiene cierto: no introducir ninguna dependencia de OCI por debajo del puerto, y un test que
falle el día que alguien la introduzca.

## Requirements

### R1 — El bucket existe como código, nunca a mano

**As a** responsable de infraestructura, **I want** el almacén de objetos definido en Terraform junto
al resto del entorno `dev`, **so that** se cumpla la norma IaC-first de `steering/infra.md` y el
entorno sea reproducible desde cero.

Acceptance criteria:

1. THE SYSTEM SHALL declarar el bucket como recurso `oci_objectstorage_bucket` en el root module de
   `infra/environments/dev/`, con su `compartment_ocid` y su namespace obtenidos por `data source` y
   **nunca** con un OCID ni un namespace escritos a mano.
2. THE SYSTEM SHALL crear el bucket con acceso **privado** (`access_type = "NoPublicAccess"`): todo
   objeto se entrega por URL prefirmada de caducidad acotada, así que un bucket público anularía el
   esquema de firma entero.
3. WHEN se aplica el plan de Terraform sobre un entorno donde el bucket ya existe, THE SYSTEM SHALL
   converger sin recrearlo ni vaciarlo.
4. THE SYSTEM SHALL exponer el nombre del bucket, la región y el endpoint compatible con S3 como
   `output` del módulo, porque son exactamente los tres valores que el backend necesita configurar.
5. IF algún paso del aprovisionamiento no se puede expresar en Terraform, THEN THE SYSTEM SHALL
   dejarlo como script versionado o documentado en el RUNBOOK, nunca como configuración que solo
   viva en la consola de OCI.

### R2 — Credenciales por la cadena estándar, fuera del árbol

**As a** responsable de seguridad, **I want** que las credenciales del almacén no estén en ningún
fichero versionado, **so that** se cumpla la regla 8 de `steering/security.md`.

Acceptance criteria:

1. THE SYSTEM SHALL tomar las credenciales del almacén de la **cadena estándar del proveedor**
   (variables de entorno o rol de instancia) y no de ajustes versionados, tal como ya exige
   `sdd/specs/file-storage.md`.
2. THE SYSTEM SHALL crear el usuario IAM y su Customer Secret Key por Terraform, con una política
   acotada al bucket de este entorno y a las operaciones que el adaptador usa —escribir, leer y
   borrar objetos—, y **no** una política de administración del tenancy.
3. THE SYSTEM SHALL marcar como `sensitive` en Terraform todo output que contenga la clave secreta,
   y THE SYSTEM SHALL NOT escribirla en `dev.tfvars.example`, en el README ni en ningún fichero
   versionado.
4. THE SYSTEM SHALL declarar en `.env.example` los nombres de las variables de credenciales con
   valor vacío o de ejemplo evidente, de modo que se sepa qué hay que aportar sin aportar nada.

### R3 — Los settings existen y llegan a la factoría

**As a** desarrollador, **I want** que el despliegue pueda configurar bucket, región y endpoint,
**so that** `storage_for(S3)` deje de fallar por falta de configuración.

Acceptance criteria:

1. THE SYSTEM SHALL añadir a la configuración de la aplicación los ajustes de **bucket**, **región**
   y **endpoint_url**, con valores por defecto vacíos que preserven el comportamiento actual.
2. THE SYSTEM SHALL pasar esos ajustes a `ConfiguredFileStorageFactory` y a `build_s3_client` en el
   punto donde hoy se construye la factoría, sin que ningún caso de uso los lea.
3. IF `storage_type` es `S3` y el bucket configurado está vacío, THEN THE SYSTEM SHALL seguir
   fallando con `StorageWriteError` y **nunca** caer a `LOCAL` — el comportamiento que
   `sdd/specs/file-storage.md` ya exige y que este change no puede relajar.
4. WHEN el endpoint configurado está vacío, THE SYSTEM SHALL dejar que boto3 resuelva el endpoint por
   defecto de AWS, de modo que apuntar a AWS S3 sea *no configurar nada* y apuntar a OCI o R2 sea
   *configurar una URL*.
5. THE SYSTEM SHALL declarar los tres ajustes en `.env.example` y en la configuración del despliegue
   a `dev`, con un comentario que nombre el proveedor activo.

### R4 — La agnosticidad de proveedor sigue siendo cierta después de aprovisionar

**As a** arquitecto, **I want** que cambiar de OCI a AWS S3, R2 o MinIO siga siendo configuración y
no código, **so that** la decisión de proveedor pueda revisarse sin reabrir el dominio.

Acceptance criteria:

1. THE SYSTEM SHALL mantener `backend/app/integrations/domain/storage.py` libre de toda referencia a
   un proveedor concreto: ni OCI, ni AWS, ni endpoint, ni región.
2. THE SYSTEM SHALL NOT introducir ninguna dependencia del SDK de OCI en el backend; el único cliente
   del almacén sigue siendo boto3 apuntado por `endpoint_url`.
3. THE SYSTEM SHALL conservar las dos costuras que lo sostienen: `build_s3_client` acepta
   `endpoint_url` arbitrario y `S3FileStorage` **recibe** el cliente inyectado en lugar de
   construirlo.
4. THE SYSTEM SHALL cubrir con un test que construir la factoría con un endpoint de un proveedor
   arbitrario produce un cliente apuntado a ese endpoint, **sin** tocar red — el test que falla el
   día que alguien cablee un proveedor por debajo del puerto.
5. THE SYSTEM SHALL documentar en la spec la matriz de proveedores compatibles y qué valor toma cada
   ajuste en cada uno (OCI, AWS, R2, MinIO), porque es la forma de que «agnóstico» sea verificable y
   no una afirmación.

### R5 — La exposición de la clave en la URL prefirmada queda aceptada por escrito

**As a** responsable del producto, **I want** que la contradicción entre la URL prefirmada y R3.2 de
`cleaning-photos-storage` se resuelva **antes** de que exista un bucket, **so that** no se incumpla un
requisito en silencio en el mismo commit que aprovisiona.

Acceptance criteria:

1. THE SYSTEM SHALL registrar la decisión de **aceptar** que la URL prefirmada de `S3` contenga el
   bucket y la clave completa, con su razón: es parte del protocolo de firma y no se puede retirar, y
   la clave se compone únicamente de identificadores que el propio sistema generó
   (`tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.{ext}`), sin ningún dato de negocio.
2. THE SYSTEM SHALL dejar constancia de las dos alternativas rechazadas y de por qué: un CDN o ruta
   propia delante del bucket (añade un componente de infra nuevo con su dominio, TLS, caché y coste),
   y servir `S3` por la ruta firmada propia (anula el motivo de usar URLs prefirmadas y mete todo el
   tráfico de fotos por el backend).
3. THE SYSTEM SHALL enmendar la redacción de R3.2 allí donde sobreviva como prohibición **sin
   excepción**, de modo que ningún documento del árbol siga afirmando que `storage_key` no aparece
   nunca en ninguna respuesta de la API.
4. THE SYSTEM SHALL mantener la prohibición **absoluta** para todo lo demás: cuerpo de la respuesta,
   cabeceras y la URL del adaptador `LOCAL`.
5. THE SYSTEM SHALL dejar la asimetría en el catálogo cerrado de `sdd/specs/file-storage.md`, sin
   añadir ninguna otra.

### R6 — El camino `S3` se ejecuta de verdad al menos una vez

**As a** desarrollador, **I want** que el bucket recién aprovisionado se pruebe end-to-end en `dev`,
**so that** no se entregue infraestructura que nadie ha visto funcionar.

Acceptance criteria:

1. THE SYSTEM SHALL dejar el tenant de demo de `dev` con `storage_type = S3` por la **vía del seed**,
   sin abrir `storage_type` a escritura por la API: R5.4 de `user-management` sigue vigente y por su
   razón original — cambiarlo apuntaría a ficheros ya subidos a un sitio donde no están.
2. WHEN se sube una foto de limpieza para ese tenant en `dev`, THE SYSTEM SHALL almacenarla en el
   bucket y devolver una URL prefirmada que el navegador resuelve sin credenciales.
3. THE SYSTEM SHALL servir esa foto con el `Content-Type` correcto y no como `binary/octet-stream`,
   verificando el etiquetado del objeto que `sdd/specs/file-storage.md` ya exige.
4. THE SYSTEM SHALL dejar la evidencia de esa comprobación registrada en el change, nombrando qué se
   subió y qué se obtuvo.
5. THE SYSTEM SHALL mantener `LOCAL` como valor por defecto de `TenantConfig.storage_type` para
   cualquier tenant nuevo, en `dev` y en local.

## Out of scope

- **Borrado desde la API y política de retención.** `cleaning-photos-storage` dejó fuera el `DELETE`
  a propósito porque PRD §23 no lo declara. Sigue siendo una decisión de producto sin tomar; su sitio
  es una entrada propia de roadmap, no este change.
- **CDN o ruta propia delante del bucket.** Rechazado en R5.2. Si algún día se quiere ocultar la
  clave, es un change de infra con su propio dominio, TLS y coste.
- **Staging y producción.** `sdd/project.md` y `steering/infra.md` dejan esos entornos sin proveedor
  elegido, y esa decisión no se hereda de `dev`.
- **Abrir `storage_type` al `PATCH` de `TenantConfig`** (R5.4 de `user-management`) y **migrar fotos
  ya subidas** de `LOCAL` a `S3`. Lo segundo es justamente lo que hace peligroso lo primero.
- **Antivirus o escaneo de contenido** de lo subido, y **ampliar la allowlist a HEIC/HEIF**. Ambas
  son superficies propias ya nombradas en `sdd/specs/file-storage.md` §Estado.
- **MinIO en el compose local.** El MVP local corre sobre `LOCAL` y eso basta; MinIO entra en la
  matriz documental de R4.5 como proveedor compatible, sin levantar un servicio nuevo.
- **Un `MEDIA_SIGNING_KEY` propio** que desacople la rotación de la firma de ficheros de
  `JWT_SECRET_KEY`. Residuo consciente ya escrito en la spec; el prefijo de versión deja la migración
  abierta.

## Affected specs

- `sdd/specs/file-storage.md` — modificar: §Estado deja de decir «no hay ningún almacén S3
  aprovisionado» y pierde el `EXTERNAL_DEPENDENCY`; entra la matriz de proveedores (R4.5), la
  aceptación escrita de la exposición de clave (R5) y los ajustes de configuración (R3).

  **Redacción concreta que queda desfasada** (nombrada aquí para que `/sdd:archive` no tenga que
  redescubrirla): en el §Catálogo cerrado de asimetrías, la frase final de la primera entrada —
  «*Hoy es código inalcanzable: sin bucket configurado la resolución falla antes de emitir ninguna
  URL*» (`file-storage.md:192`)— deja de ser cierta en cuanto el `apply` post-merge crea el bucket,
  y se retira. **Ojo, no confundir con la de la cuarta entrada** («*Hoy es inalcanzable porque la
  única productora de claves es la función del esquema*», `:202`): esa habla de la validación de
  precondiciones sobre la clave y **sigue siendo cierta** — no se toca. La entrada de la asimetría
  en sí no cambia, y el catálogo sigue teniendo cuatro entradas (R5.5); lo único que se retira es
  la nota de inalcanzabilidad de la primera. El razonamiento no se copia aquí: vive en
  [ADR 0008](../../../docs/adr/0008-object-storage-provider-dev.md) y la spec lo enlaza.
- `sdd/specs/infra-dev-terraform.md` — modificar: el bucket, el usuario IAM, su política acotada y
  los outputs nuevos.
- `sdd/specs/app-deploy-dev.md` — modificar: las variables de entorno del despliegue a `dev`.
- `sdd/specs/seed-data-demo.md` — modificar: el tenant de demo pasa a `storage_type = S3` (R6.1).
- `sdd/specs/cleaning.md` — revisar: es el consumidor real del puerto y la fuente donde puede
  sobrevivir la redacción de R3.2 que R5.3 obliga a enmendar.
