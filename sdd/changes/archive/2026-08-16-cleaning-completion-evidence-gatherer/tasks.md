# Tasks: cleaning-completion-evidence-gatherer

Orden pensado para que el sistema siga funcionando tras cada sección: la 1 sólo **añade**
(el módulo nuevo y su test; nadie lo consume todavía, la suite sigue verde), la 2 hace el
corte en un solo movimiento (caso de uso + cableado, que tienen que cambiar juntos o el
proceso no arranca), y la 3 demuestra que no cambió nada observable.

## 1. El gatherer y su test con fakes <!-- panel: PASS 2026-08-16 -->

- [x] 1.1 Crear `backend/app/cleaning/application/evidence.py` con `CompletionEvidenceGatherer`:
  constructor keyword-only con **exactamente** los cuatro puertos
  (`templates: CleaningChecklistTemplateRepository`,
  `completions: CleaningChecklistCompletionRepository`, `photos: CleaningPhotoRepository`,
  `incidents: BlockingIncidentQuery`) importados de `domain/repositories.py` y `domain/ports.py`
  (D8 — no se mueve ningún fichero), y
  `async def gather(self, *, tenant_id: uuid.UUID, task: CleaningTask) -> CleaningCompletionEvidence`.
  El cuerpo es el bloque de `use_cases.py:913-940` **movido tal cual**: `templates.get` →
  `raise ChecklistTemplateNotFoundError("The task's checklist template no longer exists")` →
  `parse_template_content` → `completions.list_for_task` → construcción del
  `CleaningCompletionEvidence` con sus cinco campos, **conservando el comentario de
  `use_cases.py:928-931`** sobre `required_photo_types()` vs `photo_types()` y el de
  `uploaded_photo_types`. Docstring del módulo/clase: reúne, no juzga — ninguna comparación,
  ningún `if` sobre la evidencia, con la referencia a D8 de `cleaning-photos-storage`.
  Sin `sqlalchemy`, `fastapi` ni `pydantic`. [R1.1, R1.3, R1.5, R2.1, R2.2, R2.4]
- [x] 1.2 Crear `backend/tests/cleaning/test_completion_evidence_gatherer.py` con el molde de
  `backend/tests/cleaning/test_photo_upload_use_case.py` (constantes `TENANT`/`NOW` a nivel de
  módulo, fakes de clase que **registran los argumentos recibidos**, sin sesión de BD y sin
  `httpx`) y el primer caso: **camino positivo** — plantilla con ítems requeridos y un
  `photo_type` requerido, completions mixtas, fotos subidas e incidencia resuelta producen un
  `CleaningCompletionEvidence` con los cinco campos poblados como corresponde. [R4.1, R4.2]
- [x] 1.3 Añadir al mismo fichero el caso de **`required` vs declarado**: una plantilla con un
  `photo_type` `required: false` produce un `required_photo_types` que **no** lo contiene, y ese
  tipo sí aparecería en `spec.photo_types()`. Es el test que fija por comportamiento lo que hoy
  sólo protege un comentario. [R2.2, R4.3]
- [x] 1.4 Añadir el caso de **plantilla ausente**: `templates.get` devuelve `None` y `gather()`
  lanza `ChecklistTemplateNotFoundError` con el mensaje exacto de hoy. [R1.5, R4.4]
- [x] 1.5 Añadir el caso de **propagación de scoping**: los cuatro fakes registran sus llamadas y
  el test afirma que los cuatro reciben el `tenant_id` pasado a `gather()`, que `templates` se
  pide por `task.checklist_template_id`, que `completions` y `photos` se piden por `task.id` y
  que `incidents` se pregunta por `task.property_id`. [R4.5]

## 2. El cierre adelgazado y su cableado <!-- panel: PASS 2026-08-16 -->

- [x] 2.1 En `backend/app/cleaning/application/use_cases.py`, `CompleteCleaningTaskUseCase`:
  `__init__` cambia los cuatro kwargs propios por uno solo,
  `evidence: CompletionEvidenceGatherer` (clase concreta, D2), dejando la clase en **ocho**
  colaboradores (siete de `_TaskLifecycleBase` + el gatherer); `execute` sustituye las cuatro
  lecturas por `evidence = await self._evidence.gather(tenant_id=tenant_id, task=task)` y
  conserva sin tocar `previous = task.status`, `task.complete(...)`, `self._tasks.save`,
  `self._transition(..., with_reservations=True)`, `self._audit.record` y el único
  `self._uow.commit()`; se retira el import ya muerto de `CleaningCompletionEvidence` (línea 65)
  y se actualiza el docstring de la clase — sigue sin juzgar, pero ya no reúne.
  `ChecklistTemplateNotFoundError` y `parse_template_content` se quedan: los usan otros casos de
  uso. [R1.2, R2.1, R3.4, R3.5]
- [x] 2.2 En `backend/app/cleaning/api/dependencies.py`,
  `get_complete_cleaning_task_use_case` construye el `CompletionEvidenceGatherer` con los
  **mismos cuatro adaptadores y la misma sesión** de hoy y lo pasa como `evidence=`, junto a
  `**_lifecycle_kwargs(session)`. Sin `Depends` propio, sin tocar `_lifecycle_kwargs`, sin
  adaptador ni sesión nuevos; los cuatro imports de adaptadores se quedan. [R1.4]

## 3. Verification

- [x] 3.1 Suite backend completa en verde desde el worktree:
  `docker compose exec backend uv run pytest` (o `docker compose run --rm backend uv run pytest`
  con el stack parado). Incluye `backend/tests/test_layering.py`, que es quien verifica la regla
  de dependencia del módulo nuevo sin añadir ningún test. [R1.3, R3.1, R3.2]
- [x] 3.2 Probar que la suite existente **no se tocó**: `git status --short backend/tests/` no
  muestra ningún fichero modificado — sólo el nuevo
  `test_completion_evidence_gatherer.py` como *untracked*/añadido. Un test editado es la señal de
  que el change se pasó de alcance. [R3.1, R3.2]
- [x] 3.3 Contrato HTTP byte a byte: `make openapi` seguido de
  `git diff --exit-code backend/openapi.json`. Equivalente exacto de la puerta de CI
  (`api-contract.yml` corre `uv run python -m app.cli.openapi --check`), reproducible aquí con
  `docker compose run --rm --no-deps -T backend python -m app.cli.openapi --check`. Cualquier
  diferencia es un fallo del change, no una mejora. (No hace falta `npm run api:generate`: si el
  backend no deriva, el artefacto del frontend tampoco.) [R3.3]
- [x] 3.4 Cableado de endpoints en verde:
  `docker compose exec backend uv run pytest tests/provenance/test_workflow_to_endpoint_wiring.py`
  — el CI lo corre aparte y es lo que cubre el constructor tocado en 2.2. **No hay lint ni
  comprobador estático en este proyecto** (`sdd/specs/maintenance.md`: sin `ruff`, sin `mypy`,
  sin `pyright`), así que el import muerto de `CleaningCompletionEvidence` que la tarea 2.1
  retira hay que comprobarlo a ojo — nada va a fallar si se queda. [R1.4, R3.1]
- [x] 3.5 Inspección dirigida de `evidence.py` antes de pedir review: ninguna resta de conjuntos,
  ningún `in`, ningún `if` sobre los campos de la evidencia, ninguna llamada a
  `missing_required_*` — el panel de review (`sdd:sdd-architect`) lo rechaza como violación de D8
  de `cleaning-photos-storage`. [R2.1, R2.3]
