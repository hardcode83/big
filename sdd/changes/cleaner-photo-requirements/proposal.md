# Proposal: cleaner-photo-requirements

## Why

PRD §11 «UI de limpiadora» pide **«botones de subir foto por categoría»**, y hoy la limpiadora no
puede saber cuáles son esas categorías. Los tipos admisibles de una tarea viven en
`cleaning_checklist_templates.required_photos` (JSONB de `RequiredPhotoSpec`: `photo_type`,
`label`, `required`), y esa columna se publica en **exactamente dos esquemas** del contrato —
`ChecklistTemplateResponse` y `CreateChecklistTemplateRequest` — servidos por dos rutas que exigen
`READ_CLEANING_TEMPLATES` / `MANAGE_CLEANING_TEMPLATES`. `UserRole.CLEANER` es
`_SELF_SERVICE | _CLEANING_EXECUTE` (`backend/app/auth/domain/policy.py:327`) y no tiene ninguno de
los dos.

La asimetría es concreta: `GET /api/v1/cleaning-tasks/{task_id}/checklist` sí le lleva los **ítems**
con su `label` y su `required`; las **fotos** no tienen equivalente. Así que la limpiadora puede
subir una foto con un `photo_type` —`404` si la plantilla no lo declara— y listar las que ya subió,
pero no puede enumerar los tipos, saber cuáles son obligatorios ni leer su etiqueta. Las dos únicas
vías de descubrimiento que le quedan son adivinar identificadores contra un `404`, o **fallar el
cierre** y leer el `409` que enumera lo que falta. Es exactamente lo contrario de un botón por
categoría.

Origen y medición completa: [`sdd/roadmap/cleaner-photo-requirements.md`](../../roadmap/cleaner-photo-requirements.md).
Es el tercer reparto de la entrada `cleaner-app`, después de
[`cleaner-task-context`](../../specs/cleaner-task-context.md) y
[`cleaner-incident-report`](../../specs/cleaner-incident-report.md), y su **último bloqueo conocido**.

## What changes

Después de este change, un llamante con `READ_CLEANING_TASKS` podrá leer, **acotado a una tarea que
ya alcanza**, los tipos de foto que esa tarea admite: su identificador, su etiqueta legible, si son
obligatorios para el cierre y cuántas fotos de ese tipo hay ya subidas. Es una proyección de solo
lectura de la plantilla de la tarea, sin conceder ningún permiso de plantilla y sin ampliar el
acotamiento por fila que ya hace `_load_task`. No cambia la subida, no cambia el cierre y no cambia
`/context`.

## Requirements

### R1 — Enumerar los tipos de foto que la tarea admite

**As a** limpiadora asignada a una tarea, **I want** ver qué categorías de foto me pide esta tarea
y cómo se llaman, **so that** pueda subirlas sin adivinar identificadores ni descubrirlas fallando
el cierre.

Acceptance criteria:

1. WHEN un llamante con `READ_CLEANING_TASKS` pide los requisitos de foto de una tarea que alcanza,
   THE SYSTEM SHALL devolver una entrada por cada `photo_type` declarado en las `required_photos`
   de la plantilla de esa tarea, cada una con su `photo_type` y su `label`.
2. WHERE la plantilla de la tarea no declara ningún tipo de foto, THE SYSTEM SHALL responder `200`
   con una colección vacía, y NEVER SHALL responder `404`: «esta tarea no pide fotos» es una
   respuesta, no un error.
3. THE SYSTEM SHALL emitir las entradas en el orden **declarado en la plantilla** —el de la tupla
   `ChecklistTemplateSpec.required_photos`—, que es estable entre peticiones y entre procesos
   porque es el orden persistido del array JSONB. *(Enmendado en `/sdd:design`, D4: la redacción
   original pedía sólo un orden estable y lo justificaba por el `frozenset` de
   `ChecklistTemplateSpec.photo_types()`, cuyo orden de iteración varía con la semilla de hash. El
   diseño no construye la colección desde ese `frozenset`, así que ese riesgo no se llega a correr,
   y el orden de la plantilla es además el orden en que se hace el trabajo.)*
4. THE SYSTEM SHALL responder con independencia del estado de la tarea, igual que
   `GET /cleaning-tasks/{task_id}/checklist`: la limpiadora necesita saber qué se le va a pedir
   **antes** de pasar a `IN_PROGRESS`, no solo durante.
5. IF la tarea no existe para el llamante —id desconocido, tarea de otro tenant o tarea de otra
   limpiadora—, THEN THE SYSTEM SHALL responder `404` de forma indistinguible entre los tres casos,
   heredado de `_load_task` sin excepción propia.
6. IF la plantilla de la tarea ya no existe, THEN THE SYSTEM SHALL responder `404`
   (`ChecklistTemplateNotFoundError`), igual que ya hace el cierre por la misma causa.

### R2 — *Admisible* y *obligatorio*, nombrados por separado

**As a** consumidora del contrato (la app de la limpiadora, y quien lo lea después), **I want** que
el cuerpo distinga «este tipo se puede subir» de «este tipo hace falta para cerrar», **so that** la
UI pinte los botones correctos sin heredar la ambigüedad del nombre de la columna.

`cleaning_checklist_templates.required_photos` declara los tipos que la subida admite **con
independencia de su `required`** (`specs/cleaning.md` §Fotos de la limpieza: *«un tipo opcional se
puede subir, y lo que `required: true` gobierna es el cierre»*), y el propio dominio lo dice de sí
mismo en `value_objects.py:63`: *«The column's name says `required_photos` while the entries in it
may perfectly well be optional»*. Dos conceptos, dos nombres.

Acceptance criteria:

1. THE SYSTEM SHALL publicar la colección bajo un nombre distinto de `required_photos`, y la
   obligatoriedad bajo una clave propia por entrada, de modo que *admisible* (pertenecer a la
   colección) y *obligatorio* (esa clave en `true`) se lean como dos hechos separados.
2. WHERE un tipo tiene `required: false` en la plantilla, THE SYSTEM SHALL incluirlo igualmente en
   la colección, porque la subida lo admite — la fuente es `ChecklistTemplateSpec.required_photos`,
   de donde `photo_types()` se deriva, y NEVER SHALL ser `required_photo_types()`. *(Enmendado en
   `/sdd:design`, D4: la redacción original nombraba `photo_types()` como fuente, y ése no puede
   serlo aquí porque descarta el `label`. Lo que la cláusula exige —no filtrar por `required`— se
   cumple íntegro: la tupla es el conjunto sin filtrar del que ese `frozenset` sale.)*
3. THE SYSTEM SHALL declarar en el contrato publicado que un `photo_type` que no está en esta
   colección es el que `POST /cleaning-tasks/{task_id}/photos` responde con `404`, para que la
   relación entre las dos rutas sea explícita y no una coincidencia que el cliente descubra.

### R3 — La cobertura ya subida, como hecho y no como veredicto

**As a** limpiadora, **I want** ver de un vistazo de qué categorías ya tengo foto, **so that** no
tenga que cruzar dos respuestas a mano ni recordar qué subí.

La cobertura es derivable por el cliente (`GET /cleaning-tasks/{task_id}/photos` ya publica
`photo_type`), pero la regla que gobierna el cierre es del servidor y dejar que el cliente la
reimplemente es exactamente cómo dos implementaciones de la misma regla se separan. La salida es
publicar el **hecho de subida** sin aplicar la regla.

Acceptance criteria:

1. WHEN se devuelven los requisitos, THE SYSTEM SHALL incluir por cada tipo la evidencia ya subida
   para esa tarea —cuántas fotos de ese `photo_type` existen, o al menos si existe alguna—, leída
   de `cleaning_photos` acotada al `tenant_id` y a la `task.id` del llamante.
2. THE SYSTEM NEVER SHALL derivar de esa lectura un veredicto sobre si la tarea puede cerrarse, ni
   devolver un campo que lo afirme: la respuesta reporta qué hay subido, no aplica ninguna de las
   tres cláusulas de PRD §11.
3. THE SYSTEM SHALL mantener las tres cláusulas aplicadas **dentro de `CleaningTask.complete()` y
   en ningún otro sitio** (`specs/cleaning.md` §Cierre y validación), de modo que esta capacidad no
   añada un segundo punto de aplicación ni reimplemente la comparación de conjuntos de
   `CleaningCompletionEvidence.missing_required_photo_types()`.
4. THE SYSTEM SHALL dejar `CompletionEvidenceGatherer` como el único ensamblador de la evidencia
   del cierre: si esta capacidad comparte con él la lectura de tipos subidos, comparte el **puerto**
   (`CleaningPhotoRepository`), nunca el ensamblado ni la comparación.

### R4 — Sin permisos nuevos y sin ensanchar el acotamiento

**As a** responsable de la superficie de autorización, **I want** que esto no le abra a `CLEANER`
nada que hoy no alcance más allá de tres campos de su propia plantilla, **so that** la proyección
estreche y no una permisos.

Acceptance criteria:

1. THE SYSTEM SHALL exigir `READ_CLEANING_TASKS`, que ya tienen `CLEANER`, `PROPERTY_MANAGER` y
   `OWNER`; la proyección la alcanzan los tres y no hay decisión de audiencia que tomar.
2. THE SYSTEM NEVER SHALL conceder a `UserRole.CLEANER` `READ_CLEANING_TEMPLATES` ni
   `MANAGE_CLEANING_TEMPLATES`: eso le abriría el catálogo de plantillas del tenant entero para
   resolver tres campos de la suya — la misma alternativa que `cleaner-task-context` descartó con
   `READ_PROPERTIES`, y por el mismo motivo.
3. THE SYSTEM SHALL derivar el acotamiento por fila del rol persistido en el token
   (`CleaningActor.restrict_to_cleaner_id`, el mismo que ya usa `_load_task`), y NEVER SHALL admitir
   un parámetro de petición que lo ensanche.
4. THE SYSTEM SHALL NOT publicar nada de la plantilla más allá de los tres campos de cada
   `RequiredPhotoSpec`: ni el `id` de la plantilla, ni su `name`, ni su `property_id`, ni su
   `active`, ni sus `items` en crudo.
5. THE SYSTEM SHALL fijar el conjunto de campos con un test propio, de modo que añadir uno sea un
   acto deliberado y no una deriva — el mismo mecanismo que `specs/cleaner-task-context.md` ya
   exige para sus once campos.

### R5 — Lo que no se mueve

**As a** mantenedora de las specs vivas, **I want** que esta capacidad se añada sin tocar los
invariantes que otros changes cerraron, **so that** el panel de revisión pueda comprobarlo y no
tenga que reabrir tres decisiones.

Acceptance criteria:

1. THE SYSTEM SHALL dejar `POST /cleaning-tasks/{task_id}/photos` validando el `photo_type` contra
   `photo_types()` y no contra `required_photo_types()`, de modo que un tipo opcional se siga
   pudiendo subir.
2. THE SYSTEM SHALL dejar intactos el orden de las tres cláusulas del `409` de `/complete`, su
   enumeración estable y su alcance por **propiedad** en la cláusula de incidencia crítica.
3. THE SYSTEM SHALL dejar `GET /cleaning-tasks/{task_id}/context` devolviendo **once campos y solo
   once** (`specs/cleaner-task-context.md`), sin ampliarlo ni enmendar ese `SHALL`.
4. WHEN el change se dé por hecho, THE SYSTEM SHALL tener la capacidad publicada en
   `backend/openapi.json` y en el cliente tipado del frontend, con `api:check` en verde.

## Out of scope

- **La UI de la limpiadora.** Los botones por categoría los pinta `cleaner-app` (`[FE]`), que
  declara `needs:` sobre esto. Este change es solo el backend que se lo hace posible.
- **Meterlo en `GET /cleaning-tasks/{task_id}/context`.** Esa ruta tiene un `SHALL` fuerte y vivo
  —*«devolver **once campos y solo once**»*, `specs/cleaner-task-context.md`— y usarla exigiría
  **enmendar una spec viva**, no ampliarla. Queda descartado aquí para que el change siga siendo
  pequeño; `/sdd:design` elige entre las otras dos formas (ensanchar `ChecklistResponse` o ruta
  hermana), que no contradicen nada.
- **Conceder permisos de plantilla a `CLEANER`** (R4.2), y con ello reabrir por qué
  `_CLEANING_TEMPLATE_MANAGE` va al owner y al manager (R1.1 de `cleaning`).
- **El almacenamiento de las fotos**: proveedor, esquema de claves, firma, formatos admitidos y
  tope de tamaño. Los cerraron `cleaning-photos-storage` y `object-storage-provisioning`, y la ruta
  de subida ya existe entera.
- **Renombrar la columna `cleaning_checklist_templates.required_photos`.** El nombre miente y se
  queda: es el esquema que creó `domain-foundation-ops` y no se renombra por una docstring. Lo que
  este change arregla es que el **contrato nuevo** no herede la ambigüedad (R2).
- **Estrechar la tercera cláusula del cierre a la tarea** ahora que `incidents.cleaning_task_id`
  existe: tiene entrada de roadmap propia y relajaría el invariante.
- **La validación automática de fotos** (`ai_validation_result`): necesita un puerto propio de
  `cleaning` que nadie ha construido (`specs/cleaning.md`).

## Affected specs

- `sdd/specs/cleaner-photo-requirements.md` — *(no existe aún — se creará al archivar)*, siguiendo
  el patrón de `cleaner-task-context.md` y `cleaner-incident-report.md`.
- `sdd/specs/cleaning.md` — §Fotos de la limpieza y §Checklist: la nueva ruta o el ensanche de
  `ChecklistResponse`, y la referencia cruzada que hace explícita la relación entre los tipos
  declarados y el `404` de la subida (R2.3).
- `sdd/specs/api-contract.md` — el esquema nuevo entra en el contrato publicado.
- `sdd/specs/frontend-api-contract-consumer.md` — el cliente tipado se regenera (R5.4).
- `sdd/specs/cleaner-task-context.md` — **solo referencia cruzada**, si el diseño elige la ruta
  hermana: su `SHALL` de once campos no se toca (R5.3).

## Notas para el diseño

> **Las tres están resueltas en [`design.md`](design.md)**: dónde vive → D1 (ruta hermana
> `GET /cleaning-tasks/{task_id}/photo-requirements`); la colisión de nombres → D3
> (`PhotoRequirementStateResponse` / `PhotoRequirementsResponse`, medidos contra los 144 esquemas
> de `backend/openapi.json`); el `label` y la regla 11 → D6 (sin fila de censo: este change es
> lector y no abre audiencia nueva). Se conservan porque son la medición, no la decisión.

Tres cosas medidas que `/sdd:design` no debería tener que redescubrir:

1. **Dónde vive** es la decisión abierta, reducida a dos opciones por el Out of scope: ensanchar
   `ChecklistResponse` con un segundo array —junta en una petición las dos mitades de la evidencia
   que el cierre exige— o una ruta hermana `GET /cleaning-tasks/{task_id}/photo-requirements`, que
   deja `/checklist` intacto y hace explícito el recurso.
2. **Colisión de nombres en el contrato.** `backend/openapi.json` ya publica dos
   `CleaningPhotoResponse` desambiguados por módulo
   (`app__cleaning__api__schemas__…` y `app__dashboard__api__schemas__…`), y esos nombres mangled
   llegan al cliente tipado del frontend. El esquema nuevo debería elegir un nombre que no añada
   una tercera colisión.
3. **`label` y la regla 11 de `steering/security.md`.** Es texto libre que el tenant escribe en un
   JSONB, y las dos columnas de plantilla (`items`, `required_photos`) **no** están en la tabla de
   sumideros de la regla 11. No es una omisión que este change deba cerrar: el precedente vivo es
   que `ChecklistItemStateResponse.label` ya publica el `label` de la columna hermana al mismo rol
   y a la misma audiencia. Publicar el de las fotos es simétrico con lo que ya se entrega.

`ASSUMPTION`: la cobertura de R3 se resuelve por `photo_type` sobre las fotos de la tarea, sin
paginación. `cleaning_photos` no tiene restricción de unicidad por `(task_id, photo_type)` a
propósito —varias fotos del mismo tipo son deliberadas— pero el volumen por tarea es de decenas,
no de miles.
