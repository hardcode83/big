# object-storage-provisioning

[INFRA] **elegir proveedor de almacenamiento de objetos y provisionarlo**, para que el camino `S3`
del puerto de ficheros deje de estar muerto. Separada de `cleaning-photos-storage` el 2026-08-09 al
cerrar su `/sdd:review` (entrada §4 de su `BLOCKED.md`).

**El nombre no lleva `s3-` a propósito: el proveedor es parte de lo que hay que decidir.** El PRD
línea 196 dice literalmente *«Producción futura: S3-compatible (Cloudflare R2 o AWS S3)»*, así que
la elección está abierta y **AWS no es el favorito**. Hay un candidato que el PRD no nombra porque
es posterior: **OCI Object Storage expone una API compatible con S3**, y el entorno `dev` ya corre
en Oracle Cloud (ADR 0001), de modo que poner las fotos ahí no añade proveedor, cuenta ni factura
nueva — que es exactamente lo contrario de lo que haría AWS. Decisión del usuario (2026-08-08):
mantener el adaptador y dejarlo abierto a alternativas. MinIO entra por la misma puerta para
pruebas locales.

**Estado de partida, y es bueno**: la costura ya está puesta y no hay que rehacerla.
`build_s3_client(*, region_name, endpoint_url)` acepta un `endpoint_url` arbitrario y
`S3FileStorage.__init__(*, bucket, client)` **recibe el cliente inyectado** en vez de construirlo
(design D2b de `cleaning-photos-storage`), así que cambiar de proveedor es configuración, no código.
Lo que falta es todo lo de fuera: **no existe `S3_BUCKET`, ni región, ni `endpoint_url`, ni
credenciales en `config.py`**. Hoy no rompe nada porque el enum por defecto es `LOCAL` y
`user-management` dejó `storage_type` deliberadamente no escribible (su R5.4), así que ningún tenant
puede llegar a `S3` — pero el camino existe y un tenant configurado así recibiría `502` en **cada**
subida, de forma ruidosa, que es lo correcto. Todo esto va por Terraform: norma **IaC-first** de
`steering/infra.md`, innegociable.

**La obligación heredada, y es la parte que no puede llegar como sorpresa** (registrada como **D7c**
en el diseño de `cleaning-photos-storage`, detectada por los paneles de sus secciones 3 y 4): una
URL prefirmada de S3 lleva el nombre del bucket y la **clave completa**
—`tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.ext`— dentro de la propia URL, por
construcción del protocolo de firma. Eso **incumple R3.2** de aquel change («`storage_key` no
aparece en ninguna respuesta de la API»), que no admitía excepción. Hoy la excepción es literalmente
código inalcanzable: sin bucket configurado, `storage_for` lanza `StorageWriteError` → `502` antes de
emitir ninguna URL. **El día que se configure un bucket, R3.2 pasa a incumplirse en ese mismo commit
y sin que ningún test lo detenga.** Así que esta entrada debe decidir una de tres **antes** de
aprovisionar: (a) poner un CDN o una ruta propia delante del bucket, (b) aceptar la exposición por
escrito con su razón, o (c) servir también `S3` por la ruta firmada propia — opción que se rechazó
en su momento porque anula el motivo de usar presigned URLs (que el navegador vaya directo al
proveedor) y mete todo el tráfico de fotos por el backend.

**Lo que hay que decidir y codificar**: proveedor, bucket, región, `endpoint_url`, credenciales y
política de acceso, más los settings que hoy no existen y su entrada en `.env.example`. Y una
decisión de retención, si se aprovecha: `cleaning-photos-storage` dejó fuera el `DELETE` a propósito
porque PRD §23 no lo declara y la evidencia de una limpieza cerrada no debería poder desaparecer sin
una decisión que nadie ha tomado.

**Consumidores futuros del mismo puerto**, que heredan lo que aquí se decida: `maintenance` (fotos de
incidente, PRD §12) y `revenue` (`expenses.receipt_storage_key`, PRD §7.x).

completes: cleaning-photos-storage · size: M · kind: infra
