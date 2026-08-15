# BLOCKED — object-storage-provisioning

## 1. La verificación en `dev` (R1.3, R6.2, R6.3, R6.4) sigue pendiente tras el merge

- **Fase**: review (repuesta post-merge)
- **Tipo**: `deferred` — el flujo puede reanudarlo solo, no hace falta ninguna decisión humana salvo
  el paso 3, que es bloqueante y está descrito abajo.
- **Qué y por qué**: `infra-dev.yml` y `deploy-dev.yml` **solo corren desde `main`**, así que ni el
  bucket ni las cinco variables de entorno existían antes del merge. R1.3 («converger sin recrear el
  bucket ni vaciarlo», observable únicamente en el `0 to destroy` del plan), R6.2 («la foto se
  almacena en el bucket y la URL prefirmada la resuelve el navegador sin credenciales»), R6.3
  (`Content-Type` correcto y no `binary/octet-stream`) y R6.4 (dejar la evidencia registrada) no se
  podían verificar en local ni en el PR. Se aceptó la secuencia en el gate de diseño (**OQ3**) en
  lugar de partir el change en dos.

  **Por qué esta entrada desapareció y volvió.** `ensure_local_gates` rechaza `mark-local-verified`
  con cualquier `BLOCKED.md` no vacío **y** con cualquier tarea sin marcar, y `/sdd:archive` aplica
  ese mismo par: el toolkit no tiene un estado para «verificado en local, con verificación
  legítimamente pendiente hasta después del merge», que es justo lo que OQ3 diseñó. Con la entrada
  puesta, el change no podía llegar a `READY_FOR_PR`. Se retiró para abrir el PR
  ([#83](https://github.com/autohostai-labs/AutoHostAI/pull/83)) y se repone ahora, que es cuando el
  archivado es posible y el gate empieza a servir para algo. El procedimiento completo vive en
  `tasks.md` §8, escrito **sin casillas** por la misma razón.

  **La aplicación quedó inerte** tras el merge: con `S3_BUCKET` vacío, `LOCAL` se comporta igual que
  siempre y un tenant `S3` sigue fallando ruidosamente con `StorageWriteError` sin caer a disco.
  Verificado en la tarea 7.3.

  **Pero el CI no quedó en verde, y estaba previsto.** El filtro de rutas de `deploy-dev.yml` cubre
  este change, así que el merge disparó un deploy automático que **falla en «Render .env»** nombrando
  el primer secreto de medios ausente — no existen hasta el paso 1 de abajo. Es seguro: el paso falla
  **antes** del `pull` y del `up`, así que la VM sigue sirviendo la versión anterior. No es un
  incidente, es el orden que OQ3 acepta.

- **Prerequisito humano del paso 1, sin el cual el `apply` falla por autorización**: un admin de la
  tenancy tiene que haber aplicado los cuatro statements nuevos de `svc-terraform-dev` que versiona
  `infra/environments/dev/iam-policy.md`: `manage users`, `manage groups`,
  `read objectstorage-namespaces` y una sentencia **nueva y aparte**
  `manage buckets in tenancy where target.bucket.name='autohostai-dev-media'` — **aparte**, no
  fusionada con la condición de `object-family` del bucket del state, que es lo que este change
  escribió primero y se corrigió: `object-family` habría concedido además `OBJECT_READ` y
  `OBJECT_DELETE` sobre todas las fotos de todos los tenants.

- **Procedimiento** (§8 de `tasks.md`, y RUNBOOK §9.2 para los pasos que se ejecutan en la VM):

  1. `terraform apply` por `workflow_dispatch` de `infra-dev.yml` desde `main`. Confirmar que el plan
     **crea** bucket, usuario, grupo, membership, policy, Customer Secret Key y los cuatro secretos
     del Vault, y que la instancia y el resto del entorno quedan intactos (`0 to destroy`) — ese
     `0 to destroy` es la verificación de **R1.3**.
  2. **Re-lanzar** el deploy desde `main` (el automático del merge ya falló, por lo de arriba) y
     comprobar que el paso «Render .env» rellena las cinco variables sin fallar por ningún OCID
     ausente de la enumeración de `oci_identity_policy.dev_runner_read_secrets`.
  3. **BLOQUEANTE (OQ4)**: `SELECT count(*) FROM cleaning_photos` del tenant de demo. Si **no** es
     cero, no convergir y decidir explícitamente entre borrar las filas o volver a subirlas —
     migrar de verdad está fuera de alcance. Si es cero:
     `docker compose exec -e BOOTSTRAP_STORAGE_TYPE=S3 backend python -m app.cli.bootstrap` en la VM.
  4. Subir una foto de limpieza de la demo, abrir la URL prefirmada **sin credenciales** y comprobar
     `200` y `Content-Type: image/jpeg` — no `binary/octet-stream`.
  5. Registrar la evidencia en el change nombrando **qué se subió y qué se obtuvo** (bucket, clave,
     código de respuesta, `Content-Type`), y borrar esta entrada.

- **Comando de reanudación**: `/sdd:review object-storage-provisioning`

`/sdd:archive` se niega a cerrar el change mientras esta entrada exista, que es exactamente lo que se
quiere: sin ella, un change que aprovisiona infraestructura se archivaría sin que nadie la hubiera
visto funcionar. **No se borra hasta que los cuatro requisitos estén verificados**, no solo los tres
de R6.
