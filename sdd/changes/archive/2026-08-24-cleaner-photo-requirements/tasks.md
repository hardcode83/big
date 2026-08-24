# Tasks: cleaner-photo-requirements

Deriva de [`design.md`](design.md). Cero migraciones, cero columnas, cero permisos, cero métodos
nuevos de puerto, cero excepciones de dominio nuevas: cada tarea de abajo es proyección de lo que
ya existe.

Orden elegido para que el sistema quede funcionando después de cada sección: 1 añade el caso de
uso sin exponerlo, 2 lo publica, 3 fija por construcción lo que no debe ocurrir, 4 sincroniza los
artefactos derivados, 5 verifica.

## 1. Aplicación — la proyección, sin exponerla todavía <!-- panel: PASS 2026-08-23 -->

- [x] 1.1 Caso de uso y su vista, con el test unitario escrito primero.
  Ficheros: `backend/app/cleaning/application/use_cases.py` (nuevo
  `PhotoRequirementView`, espejo de `ChecklistItemView:1391`, y
  `GetPhotoRequirementsUseCase(_TaskTransitionMixin)` con constructor de tres puertos —
  `tasks`, `templates`, `photos`), `backend/tests/cleaning/test_photo_requirements_use_case.py`
  (nuevo, fakes en memoria de los tres puertos según `steering/backend-architecture.md`
  §«Cómo se testea cada capa»).
  Hereda el mixin **sólo por `_load_task`** (`use_cases.py:551`), como
  `ListCleaningPhotosUseCase:1758`: no se fijan `_properties`, `_transitions`, `_timeline` ni
  `_reservations`, y `_transition` nunca se llama (D5).
  Itera `spec.required_photos` —la tupla— y **nunca** `photo_types()` ni
  `required_photo_types()` (D4); la cobertura sale de
  `photos.uploaded_photo_types(tenant_id, task.id)` como `uploaded: bool` (D2).
  El docstring del caso de uso deja escrito el orden de las dos llamadas —`_load_task` primero,
  siempre— igual que `ListCleaningPhotosUseCase` (Riesgo 4).
  Hecho = el test cubre: entrada por tipo con `photo_type`/`label` [R1.1], tupla vacía → lista
  vacía y ningún `404` [R1.2], orden idéntico al de la plantilla [R1.3], indiferencia al
  `task.status` [R1.4], `CleaningTaskNotFoundError` en las tres causas (id inexistente, otro
  tenant, otra limpiadora) desde `_load_task` [R1.5], `ChecklistTemplateNotFoundError` con la
  plantilla borrada [R1.6], un tipo con `required: false` presente en la colección [R2.2],
  `uploaded` verdadero sólo para los tipos que el fake declara subidos [R3.1] y el acotamiento
  por `CleaningActor.restrict_to_cleaner_id` sin ningún parámetro que lo ensanche [R4.3].
  [R1.1, R1.2, R1.3, R1.4, R1.5, R1.6, R2.2, R3.1, R3.4, R4.3]

- [x] 1.2 Revisar las dos docstrings de `RequiredPhotoSpec`/`photo_types()` contra el árbol
  resultante. Fichero: `backend/app/cleaning/domain/value_objects.py` (**sólo docstrings**;
  ningún cambio de comportamiento).
  `photo_types()` afirma *«The two photo accessors answer different questions and both have
  exactly one caller»* (línea ~154). Si 1.1 quedó como manda D4, la frase **sigue siendo cierta**
  y no se toca; si el `run` acabó llamando a `photo_types()`, la frase se corrige nombrando al
  segundo llamante. Hecho = la afirmación del docstring y el árbol coinciden, verificado con un
  recuento de llamantes, no de vista. [R2.2]

## 2. Contrato HTTP — esquemas, ruta y wiring <!-- panel: PASS 2026-08-23 -->

- [x] 2.1 Los dos esquemas de respuesta. Fichero: `backend/app/cleaning/api/schemas.py`.
  `PhotoRequirementStateResponse` con **cuatro campos enumerados a mano** —`photo_type`,
  `label`, `required`, `uploaded`— sin `from_attributes` (patrón de `CleaningPhotoResponse:296`),
  y `PhotoRequirementsResponse` con una única clave `data`, como `ChecklistResponse:280` y
  `CleaningPhotoListResponse:338`.
  Los nombres son los de D3 y **ninguno empieza por `CleaningPhoto…`**: ese prefijo ya está
  desambiguado por módulo en `backend/openapi.json` y una tercera colisión manglaría también las
  dos que hoy sobreviven. Hecho = `grep -rn PhotoRequirement backend/ frontend/` sólo devuelve
  código de este change. [R2.1, R4.4]

- [x] 2.2 El proveedor de dependencia. Fichero: `backend/app/cleaning/api/dependencies.py`,
  `get_photo_requirements_use_case(session)` junto a `get_checklist_use_case:180`, inyectando los
  tres repositorios SQLAlchemy que ya existen. Hecho = ninguna infraestructura nueva: se reutilizan
  `SqlAlchemyCleaningPhotoRepository.uploaded_photo_types` y
  `SqlAlchemyCleaningChecklistTemplateRepository.get`. [R1.1]

- [x] 2.3 La ruta y sus dos textos de contrato. Fichero:
  `backend/app/cleaning/api/tasks_router.py`.
  `GET /{task_id}/photo-requirements` con `ReadDep` (`= READ_CLEANING_TASKS`, línea 85), junto a
  `/checklist:353`, `/context:500` y `/photos:569` (D1).
  Añade `_PHOTO_REQUIREMENTS_RESPONSES` declarando **sólo las dos causas de `404`** que este
  handler alcanza —`CleaningTaskNotFoundError` y `ChecklistTemplateNotFoundError`—, con el mismo
  comentario de procedencia que `_PHOTO_UPLOAD_RESPONSES:381` y `_PHOTO_LISTING_RESPONSES:558`
  («cada entrada es una fila de `_MAPPING` alcanzada desde los raise sites de este handler»).
  Sin `409` (R1.4) y sin declarar el `422`, que FastAPI inyecta y
  `_point_errors_at_envelope` reescribe (D7).
  La `description` de la ruta dice que un `photo_type` ausente de esta colección es exactamente
  lo que `POST /cleaning-tasks/{task_id}/photos` responde con `404`, y se añade **una frase
  recíproca** al `404` de `_PHOTO_UPLOAD_RESPONSES` —que hoy dice *«The `photo_type` is not
  declared by the task's template»* sin decir dónde se leen los declarados— apuntando a la ruta
  nueva (D8). Es el único texto existente que este change toca, y es una `description`, no un
  esquema. Hecho = las dos direcciones de la relación están en el contrato publicado.
  [R2.3, R4.1, R4.3]

- [x] 2.4 Test de integración de la ruta. Fichero:
  `backend/tests/cleaning/test_photo_requirements_api.py` (nuevo), httpx `AsyncClient` sobre el
  aparejo de `backend/tests/cleaning/conftest.py`.
  Cubre: **conjunto de campos cerrado** con una constante escrita a mano y
  `assert set(entry) == PHOTO_REQUIREMENT_FIELDS`, siguiendo el patrón `CONTEXT_FIELDS` de
  `tests/maintenance/test_incident_context_api.py:54` [R4.5]; `200` con `{"data": []}` cuando la
  plantilla no declara fotos [R1.2]; orden idéntico al declarado en la plantilla [R1.3]; la misma
  respuesta en cada estado de la tarea, incluido antes de `IN_PROGRESS` [R1.4]; `404`
  indistinguible en las tres causas [R1.5] y con la plantilla borrada [R1.6]; un tipo
  `required: false` presente [R2.2]; `uploaded` reflejando fotos ya subidas [R3.1]; **ninguna
  fuga de plantilla** —ni `id`, ni `name`, ni `property_id`, ni `active`, ni `items`— [R4.4];
  RBAC por rol: `CLEANER`, `PROPERTY_MANAGER` y `OWNER` la alcanzan y `CLEANER` sigue **sin**
  `READ_CLEANING_TEMPLATES` ni `MANAGE_CLEANING_TEMPLATES` [R4.1, R4.2]; y **aislamiento de
  tenant** (regla 1 de `steering/security.md`, DoD §28.18) sobre una sesión **sin marcar** —los
  *loader criteria* de `app/core/db.py` harían pasar el test por construcción sobre una marcada,
  y entonces no probaría nada (Riesgo 2).
  [R1.2, R1.3, R1.4, R1.5, R1.6, R2.1, R2.2, R3.1, R4.1, R4.2, R4.4, R4.5]

## 3. Guards estructurales — lo que este change no debe hacer nunca <!-- panel: PASS 2026-08-24 (feature-scale, /sdd:review) -->

- [x] 3.1 Un guard AST más en
  `backend/tests/cleaning/test_completion_clause_contract.py`: el módulo del caso de uso nuevo
  **no nombra** `required_photo_types`, `missing_required_photo_types`,
  `CleaningCompletionEvidence` ni `CompletionEvidenceGatherer`, y la respuesta no gana ningún
  campo de veredicto (`satisfied`, `can_complete` o equivalente).
  Es la prueba estructural de tres cosas a la vez: la fuente no filtra por `required` [R2.2], la
  ruta no deriva un veredicto de cierre [R3.2] y lo que se comparte con
  `CompletionEvidenceGatherer` es el **puerto**, no el ensamblado — `application/evidence.py` no
  se importa ni se modifica [R3.4]. Junto con los guards que ese fichero ya tiene, cubre además
  que `CleaningTask.complete()` sigue siendo el único punto de aplicación [R3.3].
  Hecho = el guard falla si alguien añade el import o el campo. [R2.2, R3.2, R3.3, R3.4]

- [x] 3.2 Confirmar que las tres invariantes de R5 quedan **sin tocar**, con la suite existente y
  con el diff: `UploadCleaningPhotoUseCase` sigue validando contra `photo_types()` y no contra
  `required_photo_types()` [R5.1]; el orden, la enumeración y el alcance por **propiedad** de las
  tres cláusulas del `409` de `/complete` no se mueven [R5.2]; y
  `GET /cleaning-tasks/{task_id}/context` sigue devolviendo **once campos y solo once** [R5.3].
  Hecho = `git diff --stat` no lista `entities.py`, `evidence.py`, `auth/domain/policy.py` ni el
  caso de uso de `/context`, y `test_task_lifecycle.py`, `test_photos_api.py` y
  `test_task_context_api.py` pasan sin editarse. [R5.1, R5.2, R5.3]

## 4. Artefactos derivados y documentación <!-- panel: PASS 2026-08-24 -->

- [x] 4.1 Regenerar y commitear **las dos mitades del contrato** (`steering/documentation.md`):
  `backend/openapi.json` con `make openapi`, y `frontend/lib/api/generated/openapi.d.ts` con
  `npm run api:generate`. En este worktree enlazado el comando documentado no corre tal cual
  (Riesgo 3): usar la salida de `sdd/project.md` §Worktree bootstrap —`docker compose exec -T
  frontend mkdir -p /backend`, `docker compose cp backend/openapi.json
  frontend:/backend/openapi.json`, `docker compose exec -T frontend ln -sfn /app /frontend`, y
  entonces `docker compose exec -T frontend npm run api:generate`.
  Hecho = los dos ficheros commiteados en el mismo PR y `PhotoRequirementStateResponse` /
  `PhotoRequirementsResponse` aparecen **sin manglar por módulo** en `openapi.json`. [R5.4]

- [x] 4.2 `docs/cleaning.md` — inventario operativo de la capability. Añadir la ruta nueva en
  §«Las fotos de la limpieza», antes de «### Subir» (es lo que se hace primero), y **corregir la
  redacción que este change deja superada**: el párrafo *«Qué fotos pide una tarea lo decide su
  plantilla…»* pasa a nombrar la ruta por la que la limpiadora lo consulta, y la viñeta *«Un
  `photo_type` que la plantilla no declara es `404`»* de «### Subir» apunta a ella. Grepear
  `required_photos` y «adivinar» por `docs/` para que no quede otra frase que describa el hueco
  ya cerrado. No duplicar las specs EARS: enlazarlas.
  Hecho = la página describe el sistema tras el change, no antes. [R5.4]

## 5. Verification

- [x] 5.1 Suite backend completa en verde: `docker compose exec backend uv run pytest`. Leer las
  cifras reales, no un resumen filtrado: «PASS (0) FAIL (0)» es una recolección fallida, no un
  verde. [R1–R5]

- [x] 5.2 Contrato del backend sin deriva: `make openapi` no deja diff después de 4.1.

- [x] 5.3 Contrato del frontend sin deriva: `npm run api:check` por la vía del worktree de 4.1
  (`cd frontend && npm run api:check` **no** funciona aquí). Y `npm test`: los **2 ficheros**
  `features/provenance/workflow-contract.test.ts` y `lib/config/build-identity-contract.test.ts`
  fallan por `ENOENT` en un worktree enlazado y **no se leen como regresión** — la lista de
  `docker compose cp` de `sdd/project.md` los pone en verde si hace falta comprobarlo. [R5.4]

- [x] 5.4 Comprobación manual del flujo, con puertos publicados
  (`make up PORT_OFFSET=<n>`): con el token de una limpiadora asignada,
  `GET /api/v1/cleaning-tasks/<task_id>/photo-requirements` devuelve los tipos en el orden de la
  plantilla con su `label` y su `required`; subir una foto de uno de ellos y repetir la llamada
  cambia ese `uploaded` a `true` y ningún otro; un `photo_type` ausente de la colección responde
  `404` en la subida — la relación que 2.3 escribió en el contrato, comprobada de verdad.
  [R1.1, R2.3, R3.1]

## Notas de alcance (decisiones de `design.md` §Open questions, aplicadas aquí)

- **OQ1 — no se migra `GetChecklistUseCase` al mixin.** Su copia en línea de `_load_task`
  (`use_cases.py:1421-1426`) es previa a este change; migrarla ensancharía el diff. La asimetría
  queda nombrada en `design.md` para que el panel no la lea como un descuido. **No hay tarea.**
- **OQ2 — el `label` de las dos columnas JSONB de plantilla y el censo de la regla 11.** Hueco
  preexistente, con escritor vivo desde el change `cleaning` y sin fila en la tabla de sumideros.
  Fuera de alcance: este change **lee** esas columnas, no las escribe (D6). Va como candidata de
  roadmap propia, que **`/sdd:archive` añade a `sdd/roadmap.md`** al cerrar este change. **No hay
  tarea.**
- **D6, consecuencia para el archivado**: la spec viva que salga de aquí
  (`sdd/specs/cleaner-photo-requirements.md`) **no** debe contener prosa que atribuya escritor ni
  heredero de ninguna columna del censo — `backend/tests/test_rule11_ownership.py` recorre
  `sdd/specs/`, y `sdd/changes/` está excluido entero.
