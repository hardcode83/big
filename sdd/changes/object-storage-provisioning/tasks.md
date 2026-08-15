# Tasks: object-storage-provisioning

> **Dos notas que condicionan todo el checklist.**
>
> 1. **`sdd/specs/` no se edita aquí.** `steering/documentation.md` reserva las specs al archivado, y
>    además la §Estado de `file-storage.md` («no hay ningún almacén S3 aprovisionado») solo deja de
>    ser cierta **después** del `apply` post-merge. Lo que este change sí escribe es el **ADR 0008**,
>    que es donde D11 pone el razonamiento y D13 la matriz de proveedores; `/sdd:archive` vuelca los
>    deltas a las cinco specs que el proposal enumera en *Affected specs*. Desviación consciente de
>    la letra de D13 (que situaba la tabla en la spec): el contenido es el mismo, cambia quién lo
>    escribe y cuándo.
> 2. **R1.3 y R6.2–R6.4 no se pueden verificar antes del merge** (`infra-dev.yml` y `deploy-dev.yml`
>    solo corren desde `main` — OQ3). La §8 es el procedimiento post-merge y **se escribe sin
>    casillas**, por lo que explica ahí: en casillas bloquearía `mark-local-verified`, que rechaza
>    cualquier tarea sin marcar. La entrada `deferred` de `BLOCKED.md` se repone **después del
>    merge**, que es cuando el gate de `/sdd:archive` puede llegar a importar.
>
> **El contrato de API no gana ni un endpoint ni un campo** (design §Data & interfaces) — pero sí
> cambia, y esta nota decía lo contrario hasta el panel de la sección 6. El barrido de D12 enmendó
> el docstring de `CleaningPhotoResponse`, y Pydantic publica el docstring de un modelo de respuesta
> como su `description`, así que **es** parte del contrato. Se regeneraron **las dos mitades** que
> `steering/documentation.md` exige (`backend/openapi.json` y
> `frontend/lib/api/generated/openapi.d.ts`), y `api:check` las da por sincronizadas. Lo que sigue
> siendo cierto: ningún consumidor tiene que cambiar nada.
>
> **Excepción de diagrama, decidida por Jose en el panel de `/sdd:run` (2026-08-15).**
> `steering/documentation.md` pide que los diagramas vivan en `docs/diagrams/` como
> `{YYYY-MM-DD}_{slug}.png`, y el de este change se queda en el directorio del change y en `.svg`.
> Motivo: los seis de `docs/diagrams/` son diagramas del **sistema** (C4, máquina de estados, ER,
> dominios hexagonales) y se mantienen vivos; este describe el flujo de **un change concreto**, se
> archiva con él y caduca con él. Meterlo ahí contradiría la propia coletilla de esa regla —«los
> obsoletos se borran, no se acumulan»—. Queda anotado para que `/sdd:archive` no lo lea como un
> descuido.

## 1. Configuración y cableado del backend (inerte con los defaults vacíos) <!-- panel: PASS 2026-08-15 -->

- [x] 1.1 Añadir a `Settings` los tres ajustes `s3_bucket`, `s3_region`, `s3_endpoint_url`, los tres
  `str = ""` (D4), con el comentario que explique por qué las credenciales **no** son ajustes
  (viajan por la cadena estándar de boto3). Test en `backend/tests/test_config.py`: los tres tienen
  default vacío y se pueblan desde el entorno. — **Files:** `backend/app/core/config.py`,
  `backend/tests/test_config.py` — [R3.1, R2.1]
- [x] 1.2 Condicionar el direccionamiento **path-style** a la presencia de `endpoint_url` en
  `build_s3_client` (D3): con endpoint, `Config(..., s3={"addressing_style": "path"})`; sin
  endpoint, la `Config` actual intacta. Tests en
  `backend/tests/integrations/test_s3_file_storage.py` (o fichero nuevo si encaja mejor) que
  afirman el `addressing_style` resuelto del cliente en los dos casos, **sin red**. — **Files:**
  `backend/app/integrations/infrastructure/storage/s3.py`,
  `backend/tests/integrations/test_s3_file_storage.py` — [R3.4, R4.3]
- [x] 1.3 Cablear `get_file_storage_factory` (`dependencies.py:198`) con `s3_bucket=settings.s3_bucket`
  y `s3_client_factory=partial(build_s3_client, region_name=settings.s3_region or None,
  endpoint_url=settings.s3_endpoint_url or None)` (D5). La firma
  `s3_client_factory: Callable[[], Any]` **no cambia**. Test que comprueba que el `or None`
  convierte cadena vacía en `None` (R3.4) y que ningún caso de uso lee configuración. — **Files:**
  `backend/app/cleaning/api/dependencies.py`, `backend/tests/integrations/test_storage_factory.py`
  — [R3.2, R3.4]
- [x] 1.4 Confirmar sin tocar código que R3.3 sigue cubierto: `ConfiguredFileStorageFactory.storage_for`
  ya lanza `StorageWriteError` con bucket vacío y **nunca** cae a `LOCAL`, y
  `test_s3_without_a_configured_bucket_fails_loudly` ya lo pinea. Dejar constancia en el diff (no
  relajar el test al añadir el cableado de 1.3). — **Files:** ninguno (verificación) — [R3.3]

## 2. La agnosticidad de proveedor, verificable <!-- panel: PASS 2026-08-15 -->

- [x] 2.1 Crear `backend/tests/integrations/test_storage_provider_agnostic.py` con las tres guardas
  de D13: (a) construir la factoría con un `endpoint_url` arbitrario produce un cliente cuyo
  `meta.endpoint_url` es ese endpoint, sin abrir red; (b)
  `backend/app/integrations/domain/storage.py` no menciona ningún proveedor (`oci`, `aws`, `s3.`,
  `endpoint`, `region`) — lectura del fichero, no import; (c) `oci` no aparece ni en las
  dependencias de `backend/pyproject.toml` ni en ningún import del árbol de `backend/app/`. —
  **Files:** `backend/tests/integrations/test_storage_provider_agnostic.py` — [R4.1, R4.2, R4.3, R4.4]

  > **La guarda (b) se implementó distinta a como está escrita aquí**, a propósito y con el visto
  > bueno del panel de arquitectura: comprueba acoplamiento (imports de SDK por AST, hostnames de
  > proveedor, símbolos de configuración de almacén) en vez de las palabras `oci`/`aws`/`s3.`/
  > `endpoint`/`region`, que habrían fallado sobre prosa legítima — `S3` es el valor del enum
  > `StorageType`. Razonamiento completo en la enmienda de D13 en `design.md`.

## 3. El tenant de demo llega a `S3` por la vía del seed <!-- panel: PASS 2026-08-15 -->

- [x] 3.1 Añadir `bootstrap_storage_type: str = "LOCAL"` a `Settings`, validado contra el enum
  `StorageType` (rechaza cualquier otro valor al construir `Settings`). Test del valor válido, del
  default y del rechazo. — **Files:** `backend/app/core/config.py`,
  `backend/tests/test_config.py` — [R6.1, R6.5]
- [x] 3.2 Hacer que `apply_plan` (`backend/app/cli/bootstrap.py:118-124`) **converja**: aplica
  `storage_type` al crear el `TenantConfig` y lo **actualiza si difiere** en una re-ejecución (D10).
  Actualizar el docstring y el contador de resultados para que digan convergencia y no
  idempotencia. Tests en `backend/tests/auth/test_bootstrap.py`: crea con el valor configurado;
  re-ejecuta con otro valor y converge; el default sigue siendo `LOCAL` para cualquier tenant nuevo
  (R6.5). — **Files:** `backend/app/cli/bootstrap.py`, `backend/tests/auth/test_bootstrap.py` —
  [R6.1, R6.5]
- [x] 3.3 Comprobar que el `PATCH` de `TenantConfig` **sigue** devolviendo `422` para `storage_type`
  (R5.4 de `user-management` intacta): ejecutar el test que ya existe en
  `backend/tests/tenants/` y, si no lo hubiera, escribirlo. — **Files:**
  `backend/tests/tenants/test_mutations.py` (o `test_api.py`) — [R6.1]

## 4. Terraform: bucket, IAM, Vault y outputs

- [x] 4.1 Declarar en el root module de `dev` el `data "oci_objectstorage_namespace"`, el
  `oci_objectstorage_bucket.media` (`name = "autohostai-${var.env}-media"`,
  `access_type = "NoPublicAccess"`, `storage_tier = "Standard"`, sin `lifecycle` ni versioning —
  D6) y el `locals.media_s3_endpoint` compuesto como
  `https://<namespace>.compat.objectstorage.<region>.oraclecloud.com` (D2). Ningún OCID ni namespace
  escritos a mano. — **Files:** `infra/environments/dev/main.tf` — [R1.1, R1.2, R1.3]
- [x] 4.2 Declarar los cinco recursos de identidad de D7: `oci_identity_user.media`,
  `oci_identity_group.media`, `oci_identity_user_group_membership.media`,
  `oci_identity_policy.media_bucket_access` con los **dos statements exactos de D8** (`read buckets`
  acotado por `target.bucket.name` + `manage objects` acotado por bucket y por los cuatro
  `request.permission` enumerados) y `oci_identity_customer_secret_key.media`. — **Files:**
  `infra/environments/dev/main.tf` — [R2.2]
- [x] 4.3 Crear los cuatro `oci_vault_secret` de D9 (`-media-access-key-id`,
  `-media-secret-access-key`, `-media-s3-endpoint`, `-media-region`) y **añadir sus cuatro OCID a la
  enumeración** del statement de `oci_identity_policy.dev_runner_read_secrets` — en el mismo `apply`
  que los crea, que es la mitigación del riesgo declarado en el design. — **Files:**
  `infra/environments/dev/main.tf` — [R2.1, R3.5]
- [x] 4.4 Añadir a `outputs.tf` los outputs `media_bucket_name`, `media_region`, `media_s3_endpoint`
  y los cuatro nombres de secreto (`media_access_key_secret_name`, `media_secret_key_secret_name`,
  `media_endpoint_secret_name`, `media_region_secret_name`), cada uno con su `description`.
  **Ningún output con el valor de la clave secreta**, y `dev.tfvars.example` no gana ninguna entrada
  nueva. — **Files:** `infra/environments/dev/outputs.tf` — [R1.4, R2.3]
- [x] 4.5 Actualizar la documentación de infra: `iam-policy.md` con los statements nuevos que
  `svc-terraform-dev` necesita (`manage users`, `manage groups`, `read objectstorage-namespaces` y
  una sentencia **nueva y aparte** `manage buckets … target.bucket.name='autohostai-<env>-media'`,
  **no** fusionada con la condición de `object-family` del bucket del state — fusionarla habría dado
  `OBJECT_READ`/`OBJECT_DELETE` sobre todas las fotos de todos los tenants), documentados como **segunda relajación
  consciente del mínimo privilegio** con ámbito dev/test y revisión pendiente antes de
  staging/prod (OQ1, mismo formato que la primera); `RUNBOOK.md` con el procedimiento de rotación de
  la Customer Secret Key (`terraform apply -replace`) y con el paso 4 de OQ3; `README.md` de `dev`
  con el bucket y sus outputs. — **Files:** `infra/environments/dev/iam-policy.md`,
  `infra/environments/dev/RUNBOOK.md`, `infra/environments/dev/README.md` — [R1.5, R2.2, R2.3]
- [x] 4.6 `terraform fmt -check -diff` y `terraform validate` en `infra/environments/dev/` pasan
  (los mismos comandos que `infra-dev.yml` corre). El `plan` real es post-merge (§8). — **Files:**
  ninguno (verificación) — [R1.1, R1.2, R2.2]

## 5. CD, compose y plantilla de entorno

- [x] 5.1 En el paso «Render .env» de `deploy-dev.yml`, leer los cuatro secretos **por nombre** con
  la `read_secret_by_name` que ya existe (nombres deterministas a partir de `ENV`, igual que el
  token del túnel), derivar el nombre del bucket de `ENV`, y escribir al `.env` las cinco variables
  `S3_BUCKET`, `S3_REGION`, `S3_ENDPOINT_URL`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`. —
  **Files:** `.github/workflows/deploy-dev.yml` — [R3.5, R2.1]
- [x] 5.2 Declarar las cinco variables en el `environment:` **solo del servicio `backend`** de
  `docker-compose.deploy.yml` y de `docker-compose.yml` — es el único servicio que escribe y sirve
  ficheros. Sin `:?` (los defaults vacíos deben seguir arrancando). — **Files:**
  `docker-compose.deploy.yml`, `docker-compose.yml` — [R3.5]
- [x] 5.3 Añadir a `.env.example` las cinco variables con valor vacío y un comentario que nombre el
  proveedor activo en `dev` (OCI Object Storage) y remita a la matriz del ADR 0008; las dos de
  credenciales, explícitamente sin valor. Añadir también `BOOTSTRAP_STORAGE_TYPE` con su default
  `LOCAL` y la nota de que en el deploy se pasa en línea al CLI porque el `.env` se trunca en cada
  ejecución. — **Files:** `.env.example` — [R2.4, R3.5]

## 6. Decisiones escritas y barrido de redacción

- [x] 6.1 Crear `docs/adr/0008-object-storage-provider-dev.md` con: la elección de proveedor (D1 y
  sus tres alternativas rechazadas), la **aceptación escrita** de que la URL prefirmada lleve el
  bucket y la clave completa con su razón (R5.1) y las **dos alternativas rechazadas** de R5.2
  (CDN/ruta propia delante del bucket; servir `S3` por la ruta firmada propia), y la **matriz de
  proveedores** de D13 (OCI, AWS, R2, MinIO × bucket/región/endpoint/credenciales). — **Files:**
  `docs/adr/0008-object-storage-provider-dev.md` — [R5.1, R5.2, R4.5]
- [x] 6.2 Barrido de D12: enmendar la redacción **absoluta** de R3.2 en los cuatro sitios vivos —
  `backend/app/audit/domain/value_objects.py:225` («out of *every* API response»),
  `backend/app/cleaning/application/use_cases.py:468` (idéntica) y `:1285` («forbids in *any*
  response»), y en `s3.py` el `EXTERNAL_DEPENDENCY` del módulo y el párrafo de `signed_url` que dice
  que el proveedor «no está ni elegido» — cada uno citando el ADR 0008. **No tocar**
  `tasks_router.py:437/:503`, `docs/cleaning.md:134` ni `docs/dashboard.md:51` (ya dicen «campo de
  la respuesta» y son precisos), ni nada bajo `sdd/changes/archive/`. Cerrar el barrido con
  `grep -rn "storage_key" backend/app docs sdd/specs` y `grep -rn "R3.2" backend/app` para que no
  sobreviva ninguna copia. — **Files:** `backend/app/audit/domain/value_objects.py`,
  `backend/app/cleaning/application/use_cases.py`,
  `backend/app/integrations/infrastructure/storage/s3.py` — [R5.3, R5.4, R5.5]
- [x] 6.3 Ampliar a cuatro la enumeración cerrada de la regla 8 de `sdd/steering/security.md` (OQ2):
  añadir el par `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` diciendo qué es (credencial de proveedor
  que vive en el entorno, por eso la regla 8 y no la 3) y cuál es su **radio de daño** — el bucket
  de un entorno, ni la tenancy ni la cuenta, a diferencia de `BEDS24_REFRESH_TOKEN`. Edición de
  steering con su propia justificación en el commit. — **Files:** `sdd/steering/security.md` —
  [R2.1, R2.4]
- [x] 6.4 Actualizar `docs/cleaning.md` y el `README.md` de raíz solo donde el change los deje
  desfasados (variables de entorno nuevas y qué significa que un tenant esté en `S3`), sin duplicar
  el razonamiento del ADR. — **Files:** `docs/cleaning.md`, `README.md` — [R4.5, R3.5]

## 7. Verificación local (pre-PR)

- [x] 7.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest` (o
  `docker compose run --rm backend uv run pytest` con el stack parado), desde el worktree y con su
  propio stack (`make up`). — [R3, R4, R6.1, R6.5]
- [x] 7.2 `terraform fmt -check -diff` y `terraform validate` en `infra/environments/dev/` en verde
  (§4.6). — [R1]
- [x] 7.3 Comprobación de inercia: con las cinco variables **vacías**, el stack local arranca, un
  tenant `LOCAL` sube y sirve una foto igual que antes, y un tenant `S3` sigue fallando con
  `StorageWriteError` y no cae a `LOCAL`. Es la propiedad de la que depende que el merge sea inerte
  (OQ3 paso 1). — [R3.1, R3.3, R6.5]
- [x] 7.4 Dejar registrada la deuda `deferred` de OQ3 —R1.3 y R6.2–R6.4 pendientes hasta después del
  merge— con su procedimiento y su comando de reanudación
  (`/sdd:review object-storage-provisioning`). **Vive en la §8**, escrita como procedimiento sin
  casillas; la entrada en `BLOCKED.md` que esta tarea creó primero se retiró en el panel de
  `/sdd:review` (2026-08-15) porque bloqueaba `mark-local-verified`, y se repone **después del
  merge**, que es cuando el gate de `/sdd:archive` puede llegar a importar. El porqué completo, en la
  cabecera de la §8. — **Files:** `sdd/changes/object-storage-provisioning/tasks.md` §8 —
  [R1.3, R6.2, R6.3, R6.4]

## 8. Verificación post-merge en `dev` — **procedimiento, no checklist**

> **Esta sección no lleva casillas a propósito, y es la única del fichero que no las lleva.**
> Nada de aquí se puede ejecutar antes del merge (`infra-dev.yml` y `deploy-dev.yml` solo corren
> desde `main`, OQ3), así que como casillas serían trabajo pendiente permanente: `ensure_local_gates`
> del toolkit rechaza `mark-local-verified` con cualquier tarea sin marcar **y** con cualquier
> `BLOCKED.md` no vacío, y `/sdd:archive` aplica ese mismo par. Con §8 en casillas y la entrada en
> `BLOCKED.md`, el change no podía llegar a `READY_FOR_PR` sin renunciar a la secuencia que el gate
> de diseño aprobó. Escrito como procedimiento numerado dice exactamente lo mismo y no bloquea el PR.
>
> **Lo que sí hay que reponer, y es el precio de esta decisión** (panel de `/sdd:review`,
> 2026-08-15): en cuanto el PR esté mergeado, **volver a crear la entrada `deferred` en
> `BLOCKED.md`** con el contenido de esta sección, para que `/sdd:archive` no pueda cerrar el change
> antes de los cinco pasos. El gate se necesita justo cuando el archivado es posible, que es después
> del merge y no antes. Comando de reanudación: `/sdd:review object-storage-provisioning`.
>
> **Son cuatro requisitos los que dependen de esto, no tres**: R6.2, R6.3, R6.4 y también **R1.3**
> —«converger sin recrear el bucket ni vaciarlo» solo se observa en el `plan` del paso 1, ese
> `0 to destroy`—. Esta sección no se da por cerrada hasta que los cuatro estén verificados.

**Prerequisito humano del paso 1, sin el cual el `apply` falla por autorización.** Un admin de la
tenancy tiene que haber aplicado antes los cuatro statements nuevos de `svc-terraform-dev` que
versiona `infra/environments/dev/iam-policy.md`: `manage users`, `manage groups`,
`read objectstorage-namespaces` y una sentencia **nueva y aparte**
`manage buckets in tenancy where target.bucket.name='autohostai-dev-media'` — **aparte**, no
fusionada con la condición de `object-family` del bucket del state, que es lo que este change
escribió primero y se corrigió: `object-family` habría concedido además `OBJECT_READ` y
`OBJECT_DELETE` sobre todas las fotos de todos los tenants.

1. (op.) `terraform apply` por `workflow_dispatch` de `infra-dev.yml` desde `main`. Confirmar que el
   plan **crea** bucket, usuario, grupo, membership, policy, Customer Secret Key y los cuatro
   secretos del Vault, y que la instancia y el resto del entorno quedan intactos (`0 to destroy`) —
   ese `0 to destroy` es la verificación de R1.3. — [R1.1, R1.3, R2.2]
2. (op.) **Re-lanzar** el deploy desde `main` y comprobar que el paso «Render .env» rellena las cinco
   variables sin fallar por ningún OCID ausente de la enumeración de la policy. «Re-lanzar» porque el
   merge ya disparó uno —el filtro de rutas de `deploy-dev.yml` cubre este change— y ese **falló a
   propósito** en «Render .env»: los secretos no existían hasta el paso 1. Falla antes del `pull` y
   del `up`, así que la VM no se toca. — [R3.5, R2.1]
3. (op.) **Bloqueante** (OQ4): `SELECT count(*) FROM cleaning_photos` del tenant de demo. Si no es
   cero, **no convergir** y decidir explícitamente (borrar las filas o volver a subirlas); migrar de
   verdad sigue fuera de alcance. Si es cero,
   `docker compose exec -e BOOTSTRAP_STORAGE_TYPE=S3 backend python -m app.cli.bootstrap` en la VM. —
   [R6.1]
4. (op.) Subir una foto de limpieza de la demo, abrir la URL prefirmada **sin credenciales** y
   comprobar `200` y `Content-Type: image/jpeg` — no `binary/octet-stream`. — [R6.2, R6.3]
5. Registrar la evidencia en el change nombrando **qué se subió y qué se obtuvo** (bucket, clave,
   código de respuesta, `Content-Type`), borrar la entrada repuesta de `BLOCKED.md` y solo entonces
   `/sdd:archive` — que además vuelca los deltas a las cinco specs de *Affected specs*. — [R6.4]
