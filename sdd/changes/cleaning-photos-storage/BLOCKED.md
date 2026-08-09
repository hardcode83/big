# Blocked — cleaning-photos-storage

Entradas sin resolver. `/sdd:archive` se niega a cerrar el change mientras quede alguna.
El usuario pidió explícitamente avanzar en modo auto y resolverlas después, así que la
implementación sigue la **recomendación** de cada una y ninguna queda a medias en el código.

---

## 1. ¿Se admite HEIC/HEIF en la subida de fotos?

- **phase**: design
- **type**: decision
- **what & why**: D5 restringe la allowlist de *magic bytes* a JPEG, PNG y WebP, y deja fuera
  HEIC/HEIF — el formato **nativo de la cámara de iPhone**. Si las limpiadoras suben desde
  iPhone sin que el navegador transcodifique, `field-apps` (PRD §26.19) se encontrará con
  subidas rechazadas con `422` y la causa no será evidente desde la UI. Admitirlo obliga a
  decidir entre transcodificar en el backend (dependencia pesada: `pillow-heif`/`libheif`) o
  servirlo tal cual (Chrome y Firefox no lo pintan). Es una decisión de producto sobre hardware
  real, no una decisión técnica.
- **recomendación aplicada**: NO admitirlo por ahora. El código queda con la allowlist en una
  sola constante, de modo que ampliarla sea una línea.
- **resume**: `/sdd:design cleaning-photos-storage` (amend de D5) o abrir entrada de roadmap si
  llega después de archivar.

---

## 2. ¿Clave de firma derivada de `JWT_SECRET_KEY`, o secreto propio `MEDIA_SIGNING_KEY`?

- **phase**: design
- **type**: decision
- **what & why**: D6 firma las URLs locales con `HMAC-SHA256` bajo una clave derivada por HKDF
  de `JWT_SECRET_KEY`, para no introducir un secreto nuevo que haya que provisionar en
  Terraform (`random_password` + `oci_vault_secret`), en `docker-compose`, en el deploy y en
  `.env.example`. La alternativa ortodoxa —`MEDIA_SIGNING_KEY` propio— permite **rotar la firma
  de las fotos sin invalidar todas las sesiones**, y viceversa, que es una propiedad operativa
  real. Afecta a infraestructura (`steering/infra.md`, norma IaC-first), así que no es sólo
  código.
- **recomendación aplicada**: derivación por HKDF, con prefijo de versión `v1|` en el mensaje
  firmado para poder migrar el esquema sin romper URLs vivas.
- **resume**: `/sdd:design cleaning-photos-storage` (amend de D6).

---

## 4. No existe `S3_BUCKET`: un tenant con `storage_type = S3` recibe `502` en cada subida

- **phase**: run (sección 3)
- **type**: decision
- **what & why**: `ConfiguredFileStorageFactory` construye `S3FileStorage` con `s3_bucket=""`
  por defecto, y **ninguna tarea de las secciones 1-3 provisiona el bucket**. El resultado es
  que un tenant configurado como `S3` obtiene un `StorageWriteError` → `502` en **cada** subida,
  de forma ruidosa (no silenciosa, que es lo correcto). Hoy no rompe nada porque el enum por
  defecto es `LOCAL` y `user-management` dejó `storage_type` deliberadamente no escribible, así
  que ningún tenant puede llegar a `S3` — pero el camino existe y está muerto.
  Decidirlo toca **infraestructura** (`steering/infra.md`, norma IaC-first): bucket, región,
  credenciales y política, todo por Terraform. No es una línea de config.
- **recomendación**: **no** resolverlo en este change. `S3FileStorage` está marcado
  `EXTERNAL_DEPENDENCY` desde la sección 1; provisionarlo aquí ampliaría el alcance a Terraform
  sin que ningún requisito lo pida. Candidato a entrada propia de roadmap, **junto con la
  elección de proveedor, que sigue abierta** (ver D2b).

  **El proveedor NO está decidido, y AWS no es el favorito.** PRD línea 196 dice literalmente
  *«Producción futura: S3-compatible (Cloudflare R2 o AWS S3)»*. Y hay un candidato que el PRD
  no nombra porque es posterior: **OCI Object Storage expone una API compatible con S3**, y el
  entorno `dev` ya corre en Oracle Cloud (ADR 0001) — poner las fotos ahí no añade proveedor,
  cuenta ni factura nueva, que es exactamente lo contrario de lo que haría AWS. Decisión del
  usuario, 2026-08-08: mantener el adaptador y **dejarlo abierto a alternativas**.

  Lo que esa entrada tendrá que decidir y codificar (IaC-first, `steering/infra.md`): proveedor,
  bucket, región, `endpoint_url` y credenciales, más los settings que hoy no existen. La costura
  ya está puesta y no hay que rehacerla: `build_s3_client(*, region_name, endpoint_url)` acepta
  un endpoint arbitrario y `S3FileStorage` recibe el cliente inyectado, así que cambiar de
  proveedor es configuración, no código.
  **Obligación heredada, y es la parte que no puede olvidarse** (paneles de las secciones 3 y 4,
  registrada como **D7c**): una URL prefirmada de S3 lleva el bucket y la **clave completa**
  —`tenants/{tenant_id}/cleaning-tasks/{task_id}/{photo_id}.ext`— dentro de la propia URL, y eso
  incumple R3.2, que no admitía excepción. Hoy es código inalcanzable porque sin bucket se
  responde `502` antes de emitir nada. **El día que se configure un bucket, R3.2 se incumple en
  ese mismo commit y ningún test lo detiene.** Esa entrada debe decidir una de tres antes de
  aprovisionar: CDN o ruta propia delante del bucket, aceptación escrita de la exposición con su
  razón, o servir también S3 por la ruta firmada propia.
- **resume**: `/sdd:new object-storage-provisioning` (nombre deliberadamente sin `s3-`: el
  proveedor es parte de lo que hay que decidir), o ampliar el alcance de este change si se
  decide lo contrario.

---

## 5. Aserción invertida en `test_subclasses_come_before_their_base` (defecto preexistente)

- **phase**: run (sección 3)
- **type**: deferred
- **what & why**: `backend/tests/cleaning/test_errors.py::test_subclasses_come_before_their_base`
  guarda el orden de `_MAPPING`, que se resuelve **primera coincidencia gana** — si una subclase
  quedara después de su base, el error se mapearía al código de la base y devolvería el status
  equivocado. Pero la aserción está **invertida**: comprueba que una fila anterior *no* es
  subclase de una posterior. Hoy es vacía porque todos los errores de `cleaning` son hijos
  directos, así que nunca ha protegido nada. Se detectó al implementar la sección 3, y **es
  preexistente, no introducido por este change** — el agente lo esquivó haciendo
  `UnsupportedPhotoFormatError` hermano en vez de subclase, que además es más simple.
- **recomendación**: no arreglarlo aquí (disciplina de alcance: no lo pide ningún requisito de
  este change, y tocar un guardián de orden de errores merece su propio diff revisable). Dejarlo
  registrado para que no se pierda.
- **resume**: entrada de roadmap propia, o incluirlo en `backend-suite-runtime`, que ya va a
  tocar la suite.

---

## 6. Dos candidatos a change propio, detectados por los paneles y NO hechos aquí

- **phase**: run (secciones 4 y 5)
- **type**: deferred
- **what & why**: los dos son mejoras reales que ningún requisito de este change pide, y hacerlas
  aquí habría ampliado el alcance a superficie que nadie ha revisado con ese propósito.

  **(a) `CompleteCleaningTaskUseCase` tiene 11 colaboradores** —`_TaskLifecycleBase` aporta 7
  (`tasks`, `properties`, `transitions`, `timeline`, `reservations`, `audit`, `uow`) y el cierre
  añade `completions`, `templates`, `photos`, `incidents`—. Lo contó el arquitecto al evaluar por
  qué no se testeó con fakes, y su lectura es la correcta: que no se pueda testear con fakes no
  es propiedad del dominio, es una señal. La salida que propone **no toca D8**: D8 prohíbe mover
  la *decisión* fuera de la entidad, no la *lectura*, así que la orquestación de lectura
  (plantilla + completions + fotos + incidencia) podría extraerse a un `CompletionEvidenceGatherer`
  propio sin romper nada.

  **(b) No hay `X-Content-Type-Options: nosniff` en ninguna ruta salvo la anónima de fotos.** Lo
  midió el revisor de seguridad: el único `nosniff` de todo `backend/app` es el que este change
  añadió; las 12 rutas autenticadas no lo llevan. Un middleware global lo cerraría de una vez,
  pero es postura de seguridad de **todo** el backend y merece su propio diff revisable, no
  colarse en un change de fotos.
- **resume**: entradas de roadmap propias, o incluirlas en `hardening-release`.

---

## 7. El mismo error de razonamiento sobre topes de tamaño ya está reproducido en un segundo módulo

- **phase**: review
- **type**: deferred
- **what & why**: el panel de `/sdd:review` gastó dos rondas en una afirmación falsa sobre D11 —que
  el conteo por trozos del caso de uso protege de un `Content-Length` mentido, cuando la comprobación
  que de verdad cumple R2.5 es el contador acumulativo de `MaxBodySizeMiddleware`—. Estaba
  reenunciada en **cinco** ficheros y cuatro habían derivado; quedó arreglada y con un solo hogar
  (el docstring de `_read_within_limit`).
  Al grepear apareció que **el patrón se ha reproducido solo, en otro change**:
  `backend/app/integrations/api/router.py:56-58` (import de CSV, del change `integrations` /
  `api-ingress-routing`) justifica su `file.read(limit+1)` como *«defence in depth for a request
  whose body arrived in one chunk under a lying `Content-Length`»*. Un cuerpo que «arrived» ya está
  volcado: esa lectura acota la copia en memoria, **no** caza al que miente. Misma clase de error,
  módulo distinto, y nadie lo había mirado.
  Lo que esto sugiere no es un tercer arreglo de redacción sino una **nota de steering**: una
  comprobación de tamaño posterior a `request.form()` / `file.read()` acota memoria, no satisface un
  requisito de «rechazar antes de leer»; eso sólo lo puede hacer el middleware. Escrita una vez en
  `steering/backend.md` o `steering/security.md`, deja de reinventarse por módulo.
- **recomendación**: no tocarlo aquí — es código de otro change, ningún requisito R1-R6 de éste lo
  alcanza, y corregirlo ampliaría el alcance a superficie que este panel no ha revisado con ese
  propósito.
- **resume**: `/sdd:new` de una entrada propia, o incluirlo en `hardening-release`, que ya va a
  tocar postura transversal del backend (ver §6(b), que está en el mismo caso).

---

## 3. ¿`sdd/specs/file-storage.md` propia, o el puerto dentro de `sdd/specs/cleaning.md`?

- **phase**: design
- **type**: deferred
- **what & why**: el puerto de almacenamiento es compartido (D2, vive en `app/integrations/`) y
  tendrá al menos dos consumidores más (`maintenance` para fotos de incidente, `revenue` para
  `expenses.receipt_storage_key`). Una spec propia lo refleja; plegarlo en `cleaning.md` lo
  esconde bajo un dominio que sólo es su primer usuario. **No bloquea la implementación** — es
  una decisión sobre dónde se documenta el comportamiento, y se toma al archivar.
- **recomendación aplicada**: spec propia (`sdd/specs/file-storage.md`), tal como declara
  `proposal.md` §Affected specs.
- **resume**: `/sdd:archive cleaning-photos-storage`.
