# Requisitos de foto de una tarea de limpieza

## Purpose

Dice a la limpiadora **qué categorías de foto le pide su tarea, cómo se llaman, cuáles hacen falta
para cerrar y de cuáles ya tiene una subida**, sin concederle ningún permiso de plantilla. Es la
lectura que PRD §11 necesita para pintar «botones de subir foto por categoría», entregada como una
**proyección de solo lectura acotada a una tarea que el llamante ya alcanza**.

Existe porque las categorías admisibles viven **solo** en
`cleaning_checklist_templates.required_photos`, publicada en exactamente dos esquemas del contrato
—`ChecklistTemplateResponse` y `CreateChecklistTemplateRequest`— tras `READ_CLEANING_TEMPLATES` /
`MANAGE_CLEANING_TEMPLATES`, y el rol `CLEANER` no tiene ninguno de los dos. La asimetría que
cierra es concreta: `GET /cleaning-tasks/{task_id}/checklist` ya le lleva los **ítems** con su
`label` y su `required`, y las **fotos** no tenían equivalente, así que las dos únicas vías de
descubrimiento eran adivinar identificadores contra un `404` o **fallar el cierre** y leer el `409`
que enumera lo que falta.

Cuelga de una tarea de [`cleaning`](cleaning.md) y reusa su acotamiento por rol sin ampliarlo. El
*cómo se opera* está en [`docs/cleaning.md`](../../docs/cleaning.md).

## Requirements

### La enumeración: qué categorías pide la tarea

- WHEN se solicita `GET /api/v1/cleaning-tasks/{task_id}/photo-requirements` sobre una tarea
  alcanzable por el llamante, THE SYSTEM SHALL devolver `200` con una entrada por cada `photo_type`
  declarado en las `required_photos` de la plantilla de esa tarea, cada una con su `photo_type`, su
  `label`, su `required` y su `uploaded`.
- THE SYSTEM SHALL emitir las entradas en el orden **declarado en la plantilla** —el de la tupla
  `ChecklistTemplateSpec.required_photos`—, que es estable entre peticiones y entre procesos
  porque es el orden persistido del array JSONB, y es además el orden en que se hace el trabajo,
  que es el orden en que la UI debe pintar los botones.
- THE SYSTEM SHALL construir la colección iterando esa **tupla**, y SHALL NOT construirla desde
  `photo_types()` ni desde `required_photo_types()`: la tupla es la única fuente que lleva el
  `label`, y el `frozenset` de `photo_types()` tiene orden de iteración dependiente de la semilla
  de hash.
- WHERE la plantilla de la tarea no declara ningún tipo de foto, THE SYSTEM SHALL responder `200`
  con una colección vacía, y NEVER SHALL responder `404`: «esta tarea no pide fotos» es una
  respuesta, no un error.
- THE SYSTEM SHALL responder con independencia del estado de la tarea, igual que
  `GET /cleaning-tasks/{task_id}/checklist`: la limpiadora necesita saber qué se le va a pedir
  **antes** de pasar a `IN_PROGRESS`, no solo durante. Ningún estado produce un `409`.
- IF existe una foto subida de un `photo_type` que la plantilla ya no declara, THEN THE SYSTEM
  SHALL no añadir entrada por ella: la enumeración la manda la plantilla, no la tabla de fotos —
  la misma regla que el checklist aplica a una completion de un ítem que la plantilla ya no
  declara.

### *Admisible* y *obligatorio*, dos hechos con dos nombres

- THE SYSTEM SHALL publicar la colección bajo la clave `data` —y **no** bajo `required_photos`— con
  la obligatoriedad en una clave `required` propia de cada entrada, de modo que *admisible*
  (pertenecer a la colección) y *obligatorio* (`required: true`) se lean como dos hechos
  separados. El nombre de la columna miente sobre su contenido y la ambigüedad se detiene en el
  esquema.
- WHERE un tipo tiene `required: false` en la plantilla, THE SYSTEM SHALL incluirlo igualmente en
  la colección, porque la subida lo admite.
- THE SYSTEM SHALL declarar en el contrato publicado que un `photo_type` que no está en esta
  colección es exactamente lo que `POST /cleaning-tasks/{task_id}/photos` responde con `404`, y
  SHALL llevar la frase recíproca en la `description` del `404` de la subida. La relación entre las
  dos rutas es una garantía —leen la misma plantilla— y no una coincidencia que el cliente
  descubra probando identificadores.

### La cobertura ya subida, como hecho y no como veredicto

- WHEN se devuelven los requisitos, THE SYSTEM SHALL indicar por cada tipo, en `uploaded`, si ya
  existe alguna foto de ese `photo_type` para esa tarea, leída con
  `CleaningPhotoRepository.uploaded_photo_types(tenant_id, task.id)` — **el mismo método del puerto
  que el cierre compara**, no un segundo camino de lectura.
- WHERE hay varias fotos del mismo `photo_type`, THE SYSTEM SHALL devolver una sola entrada con
  `uploaded` en `true`: es un hecho de pertenencia y no un recuento. El recuento exacto lo cuenta
  el cliente desde `GET /cleaning-tasks/{task_id}/photos`, que publica `photo_type` por foto.
- THE SYSTEM NEVER SHALL derivar de esa lectura un veredicto sobre si la tarea puede cerrarse, ni
  publicar un campo que lo afirme —ni en el cuerpo ni en una cabecera propia de la ruta—: la
  respuesta reporta qué hay subido y no aplica ninguna de las tres cláusulas de PRD §11.
- THE SYSTEM SHALL mantener las tres cláusulas aplicadas **dentro de `CleaningTask.complete()` y en
  ningún otro sitio** ([`cleaning`](cleaning.md) §Cierre y validación), y SHALL dejar
  `CompletionEvidenceGatherer` como el único ensamblador de la evidencia del cierre. Esta capacidad
  comparte con él el **puerto**, nunca el ensamblado ni la comparación de conjuntos de
  `CleaningCompletionEvidence.missing_required_photo_types()`.
- THE SYSTEM SHALL fijar eso con guardas estructurales sobre los cinco nodos que esta capacidad
  posee —caso de uso, proveedor de dependencia, handler y los dos esquemas—: ninguna álgebra de
  conjuntos, ninguna referencia a la maquinaria del cierre, ningún campo de veredicto en la vista,
  handler que solo llama al caso de uso y devuelve el esquema, y esquemas que solo copian campos.
- THE SYSTEM SHALL cerrar además por **conducta** los dos canales que un cliente lee —el conjunto
  de claves del cuerpo y el conjunto de nombres de cabecera de la respuesta, comparado contra una
  línea base cerrada—, porque una guarda por AST sobre una lista de ficheros mantenida a mano vale
  lo que la última revisión y no ve un veredicto montado por encima de la ruta.

### El orden de las dos lecturas es portante

- THE SYSTEM SHALL resolver la tarea **antes** de leer los tipos ya subidos. `uploaded_photo_types`
  responde un conjunto vacío para una tarea que no es de este tenant —su dirección segura
  declarada, que bloquea un cierre en vez de concederlo—, y publicar esa vacuidad sería responder
  `200` a un llamante que no posee nada. Resolver la tarea primero es lo que hace el caso
  inalcanzable en vez de meramente inocuo.

### Acotamiento por fila y autorización

- THE SYSTEM SHALL exigir `READ_CLEANING_TASKS` en la puerta —el mismo permiso que sus tres rutas
  hermanas de solo lectura sobre una tarea— y responder `403` antes de tocar la base de datos
  cuando el llamante no lo tiene. No hay permiso nuevo: uno propio lo tendrían exactamente los
  roles que ya tienen éste.
- WHILE el llamante tiene rol `CLEANER`, THE SYSTEM SHALL restringir la consulta a las tareas cuya
  `assigned_cleaner_id` sea la suya, derivada de `CleaningActor.restrict_to_cleaner_id` sobre el rol
  **persistido** del token, y SHALL NOT admitir ningún parámetro de petición que lo ensanche. La
  ruta no declara ningún parámetro de consulta.
- WHILE el llamante tiene rol `PROPERTY_MANAGER` o `TENANT_OWNER`, THE SYSTEM SHALL devolver los
  requisitos de cualquier tarea de su tenant, sin ese acotamiento.
- IF la tarea no existe, pertenece a otro tenant o está asignada a otra limpiadora, THEN THE SYSTEM
  SHALL responder `404 NOT_FOUND` con un cuerpo **idéntico** en los tres casos, heredado de
  `_load_task` sin excepción propia ni mensaje propio.
- IF la plantilla de la tarea ya no existe, THEN THE SYSTEM SHALL responder `404`
  (`ChecklistTemplateNotFoundError`), igual que ya hace el cierre por la misma causa.
- THE SYSTEM NEVER SHALL conceder a `UserRole.CLEANER` `READ_CLEANING_TEMPLATES` ni
  `MANAGE_CLEANING_TEMPLATES`: eso le abriría el catálogo de plantillas del tenant entero para
  resolver tres campos de la suya. El rol sigue siendo `_SELF_SERVICE | _CLEANING_EXECUTE`, y que
  siga sin alcanzar por HTTP el catálogo de plantillas lleva test propio.
- THE SYSTEM SHALL llevar un `tenant_id` explícito en cada una de las tres lecturas que compone, y
  SHALL demostrar con tests sobre una sesión **sin marcar** que el filtro de tenant es portante en
  las tres —la tarea, la plantilla y las fotos—, en vez de descansar en el listener de sesión.

### Lo que la respuesta nunca lleva

- THE SYSTEM SHALL enumerar los cuatro campos de cada entrada a mano, sin `from_attributes`, de
  modo que el conjunto cerrado sea una propiedad de la clase y no de quien edite después la vista
  de la que se construye.
- THE SYSTEM SHALL NOT publicar nada de la plantilla más allá de los tres campos de cada
  `RequiredPhotoSpec`: ni el `id` de la plantilla, ni su `name`, ni su `property_id`, ni su
  `active`, ni sus `items` en crudo.
- THE SYSTEM SHALL NOT publicar `storage_key` ni el identificador de ninguna foto: `uploaded` es un
  booleano y esta superficie no es un listado de evidencia.
- THE SYSTEM SHALL fijar el conjunto de campos con un test propio, de modo que añadir uno sea un
  acto deliberado y no una deriva, y SHALL demostrar que la búsqueda de campos prohibidos no es
  vacua.
- WHERE la fila almacenada de la plantilla ya no parsea, THE SYSTEM SHALL responder el `422` **sin
  nombrar la plantilla**: este camino no pasa `template_id=` al parser, a diferencia de la ruta de
  creación, donde un `MANAGE_CLEANING_TEMPLATES` sí debe leer de qué plantilla se habla.
- El alcance de esa cláusula es **esta ruta**, y no una garantía del sistema: `/checklist` y los
  demás lectores con `READ_CLEANING_TASKS` siguen pasando `template_id=` y siguen nombrando la
  plantilla sobre la misma fila corrupta, y la rama de `item_id` duplicado interpola el **valor**
  repetido, que el sobre publica. No hay delta de información —la misma limpiadora, el mismo
  permiso, la misma fila, y los mismos `item_id` se leen en `/checklist`— y las dos quedan como
  entrada de roadmap propia, no como una línea de aquí.

### Contrato publicado

- THE SYSTEM SHALL declarar la operación en `backend/openapi.json` con sus dos esquemas
  —`PhotoRequirementStateResponse` y `PhotoRequirementsResponse`— enumerados campo a campo, y SHALL
  mantener regenerado y commiteado el artefacto derivado del frontend
  `frontend/lib/api/generated/openapi.d.ts`: las dos mitades del mismo puente.
- THE SYSTEM SHALL nombrar esos dos esquemas **sin** el prefijo `CleaningPhoto`, que ya colisiona en
  el contrato publicado —`app__cleaning__api__schemas__CleaningPhotoResponse` y
  `app__dashboard__api__schemas__CleaningPhotoResponse`, desambiguados por módulo—: una tercera
  colisión manglaría también las dos que hoy sobreviven, y esos nombres son los que un consumidor
  del frontend escribe a mano. Lleva test propio.
- THE SYSTEM SHALL declarar en la ruta **solo el `404`** y sus dos causas alcanzables desde su
  propio handler, cada una fila de `cleaning/api/errors.py::_MAPPING` y no una conjetura. No declara
  `409`, y el `422` no se declara porque lo inyecta FastAPI por el `task_id` validado y
  `_point_errors_at_envelope` lo reescribe al sobre. Lleva test propio.
- THE SYSTEM SHALL documentar en la `description` de la operación que pertenecer a la colección y
  `required` son dos hechos distintos, que un tipo ausente es el `404` de la subida, que el orden es
  el de la plantilla, que `uploaded` no decide nada, que una plantilla sin fotos responde `200`
  vacío, y que el conjunto de tareas visibles viene del rol persistido del token y **no es
  ensanchable por parámetro**.

## Consultas por petición

**Tres** sentencias sobre una sola tarea: `tasks.get`, `templates.get` y
`photos.uploaded_photo_types` —un `DISTINCT` sobre las fotos de la tarea—, las tres acotadas al
tenant. Menos en los caminos que terminan en `404`. Sin paginación, a propósito:
`MAX_REQUIRED_PHOTOS` = 50 acota el tamaño de la respuesta por construcción, y el volumen de fotos
por tarea es de decenas.

## Fuera de alcance

- **La UI.** Los botones por categoría los pinta `cleaner-app`, que declara esta entrada en su
  `needs`.
- **Meterlo en `GET /cleaning-tasks/{task_id}/context`.** Esa ruta devuelve *once campos y solo
  once* ([`cleaner-task-context`](cleaner-task-context.md)) y usarla exigiría **enmendar** ese
  `SHALL`, no ampliarlo. Es una ruta hermana precisamente por eso.
- **Ensanchar `ChecklistResponse`.** Obligaría a leer `cleaning_photos` en **cada** pintado del
  checklist, incluido el de quien solo va a marcar ítems, y modificaría un esquema ya publicado.
- **Un recuento exacto por tipo.** `uploaded` es un booleano: un quinto método del puerto
  obligaría a `CompletionEvidenceGatherer` a depender de algo que no usa, y el recuento ya se
  deriva de `GET /cleaning-tasks/{task_id}/photos`.
- **Renombrar `cleaning_checklist_templates.required_photos`.** El nombre miente y se queda; lo que
  esta capacidad arregla es que el contrato nuevo no herede la ambigüedad.
- **La subida, el cierre y el almacenamiento.** No se toca ninguno: el `photo_type` se sigue
  validando contra todos los tipos declarados y no solo los `required`, y las tres cláusulas del
  `409` de `/complete` conservan su orden, su enumeración estable y el alcance por **propiedad** de
  la cláusula de incidencia crítica.
- **La validación automática de fotos** (`ai_validation_result`): necesita un puerto propio de
  `cleaning` que nadie ha construido.

## Key files

- `backend/app/cleaning/application/use_cases.py` — `PhotoRequirementView`, el dataclass congelado
  de cuatro campos, y `GetPhotoRequirementsUseCase`, que hereda `_TaskTransitionMixin` **solo por
  `_load_task`** y fija únicamente los tres puertos que usa.
- `backend/app/cleaning/domain/value_objects.py` — `RequiredPhotoSpec`, la tupla
  `ChecklistTemplateSpec.required_photos`, `parse_template_content` y `MAX_REQUIRED_PHOTOS`.
- `backend/app/cleaning/domain/repositories.py` — `CleaningPhotoRepository.uploaded_photo_types`, el
  método que esta capacidad comparte con el cierre.
- `backend/app/cleaning/api/schemas.py` — `PhotoRequirementStateResponse` (cuatro campos a mano, sin
  `from_attributes`) y `PhotoRequirementsResponse` (una clave `data`).
- `backend/app/cleaning/api/tasks_router.py` — `GET /{task_id}/photo-requirements`,
  `_PHOTO_REQUIREMENTS_RESPONSES`, la `description` del contrato y la frase recíproca en el `404` de
  `_PHOTO_UPLOAD_RESPONSES`.
- `backend/app/cleaning/api/dependencies.py` — `get_photo_requirements_use_case`, con los tres
  adaptadores ya usados en el módulo.
- `backend/tests/cleaning/test_photo_requirements_use_case.py` — el orden de la tupla, las tres
  causas del mismo `404`, el tipo opcional en la colección y el manager sin acotamiento.
- `backend/tests/cleaning/test_photo_requirements_api.py` — el conjunto cerrado de campos, la
  ausencia de veredicto en cuerpo y cabeceras, los `404` byte a byte, la vacuidad de la búsqueda
  prohibida, el contrato publicado y las lecturas sobre sesión sin marcar.
- `backend/tests/cleaning/test_completion_clause_contract.py` — las guardas estructurales sobre los
  cinco nodos de la capacidad y el único consumidor de `CompletionEvidenceGatherer`.
- `docs/cleaning.md` — cómo se opera.
