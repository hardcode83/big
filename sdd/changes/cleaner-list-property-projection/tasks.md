# Tasks: cleaner-list-property-projection

Sin design.md: triviality check aplicado (`/sdd:design`) — el enfoque reutiliza al pie de la letra
el patrón ya existente de `assignment_blocked_by` en el mismo caso de uso (una consulta batched por
página, cero por fila) y el método de repositorio que hace falta (`PropertyRepository.list_for_ids`)
ya existe y ya sirve este propósito exacto en `reservations`. No hay decisión de diseño que tomar:
solo aplicar la forma. Orden: §1 calcula el dato en la capa de aplicación sin tocar el contrato, §2
lo publica y rompe el contrato a propósito (aditivo), §3 verifica.

## 1. La vista del listado resuelve el nombre y el código de la vivienda <!-- panel: PASS 2026-09-18 receipt:101902f1 -->

- [x] 1.1 `CleaningTaskListView` (`backend/app/cleaning/application/use_cases.py:1710-1721`) gana
  `property_name: str | None` y `property_internal_code: str | None`, junto a `task` y `blocker`.
  [R1.1]
- [x] 1.2 `ListCleaningTasksUseCase.execute` (`use_cases.py:1744-1800`): tras calcular
  `property_ids` (los mismos, distintos, ya usados para `states_for`), añadir
  `properties_by_id = {p.id: p for p in await self._properties.list_for_ids(tenant_id,
  property_ids)}` y poblar los dos campos nuevos de cada `CleaningTaskListView` desde
  `properties_by_id.get(task.property_id)` — `.get()`, nunca `[]`, para fallar abierto igual que
  `blocker` cuando el id no resuelve (R1.3). **No** añadir ningún método a `PropertyRepository`: el
  puerto ya se inyecta en este caso de uso (para `states_for`) y `list_for_ids` ya existe en él.
  [R1.1, R1.3, R2.1, R2.2]
- [x] 1.3 Tests de `application/` con fakes en memoria (`steering/backend-architecture.md`: nunca la
  DB real en esta capa) en el fichero de test del caso de uso: una página con dos viviendas
  distintas puebla `property_name`/`property_internal_code` correctamente por fila, y un
  `property_id` que el fake `list_for_ids` no resuelve deja los dos campos en `None` sin lanzar.
  [R1.1, R1.3]

## 2. El contrato del listado publica los campos nuevos

- [ ] 2.1 `CleaningTaskListItemResponse` (`backend/app/cleaning/api/schemas.py:286-334`): añadir
  `property_name: str | None` y `property_internal_code: str | None`, poblados en `from_domain`
  desde `view.property_name` / `view.property_internal_code`. No heredar de `CleaningTaskResponse`
  (se mantiene la duplicación deliberada que ya documenta el comentario de la clase). [R1.1, R1.2]
- [ ] 2.2 Actualizar `test_the_listing_item_mirrors_the_task_response_field_for_field`
  (`backend/tests/cleaning/test_tasks_api.py:1162`): el conjunto de campos exclusivos del listado
  pasa de `{"assignment_blocked_by"}` a `{"assignment_blocked_by", "property_name",
  "property_internal_code"}`. [R1.2]
- [ ] 2.3 Tests de API del listado en `backend/tests/cleaning/test_tasks_api.py`: una página con
  filas de más de una vivienda devuelve el `property_name`/`property_internal_code` correctos por
  fila; `test_the_listing_rows_never_carry_notes` sigue en verde sin tocar; y un caso que reutilice
  el fake `_ResolvesNothing` (o equivalente) de
  `test_a_row_whose_property_state_is_unresolved_is_still_offered` (línea 1125) para probar que un
  `property_id` sin resolver deja los dos campos en `null` y la fila se sigue ofreciendo. [R1.1,
  R1.3, R1.4]
- [ ] 2.4 Test nuevo, mismo principio que `test_the_listing_reads_the_property_states_once_per_page`
  (línea 1182): envolver el `PropertyRepository` real para contar llamadas a `list_for_ids` durante
  un `GET /api/v1/cleaning-tasks` con varias filas repartidas en más de una vivienda, y afirmar
  **una sola llamada** con el conjunto exacto de `property_id` distintos de la página. [R2.1, R2.3]
- [ ] 2.5 Regenerar y commitear `backend/openapi.json` (`make openapi`) en el mismo Pull Request —
  `steering/documentation.md`, workflow `api-contract`. [R3.1]
- [ ] 2.6 Regenerar y commitear `frontend/lib/api/generated/openapi.d.ts` (`cd frontend && npm run
  api:generate`) — la otra mitad del puente que exige `steering/documentation.md`. **Desde este
  worktree el comando documentado no funciona tal cual**: usar la secuencia de `docker compose cp`
  de `sdd/project.md` («Lo que tampoco funciona tal cual: regenerar el contrato del frontend»),
  incluido el `mkdir -p /backend` antes del primer `cp`. [R3.1]

## 3. Verificación

- [ ] 3.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest` (o
  `docker compose run --rm backend uv run pytest` con el stack parado), desde este worktree sobre
  su propio stack.
- [ ] 3.2 `uv run pyright .` limpio en `backend` (`sdd/project.md`, Commands).
- [ ] 3.3 Deriva de contrato cero: tras 2.5/2.6, `cd frontend && npm run api:check` (con la
  secuencia de `docker compose cp` ya aplicada) y `git status` sin cambios en
  `backend/openapi.json` tras un `make openapi` de comprobación.
- [ ] 3.4 Repaso de cobertura, criterio a criterio:

  | Criterio | Qué lo demuestra |
  |---|---|
  | R1.1 | 1.3 (fakes de aplicación) + 2.3 (API, más de una vivienda por página) |
  | R1.2 | 2.1 (forma del item, no de `CleaningTaskResponse`) + 2.2 (drift guard actualizado) |
  | R1.3 | 1.2/1.3 (fails open en `application/`) + 2.3 (fails open en API) |
  | R1.4 | `test_the_listing_rows_never_carry_notes`, sin tocar, sigue en verde |
  | R2.1 | 1.2 (una llamada a `list_for_ids`, no una por fila) + 2.4 (test de cardinalidad) |
  | R2.2 | 1.2 — ningún método nuevo en `PropertyRepository` |
  | R2.3 | 2.4 |
  | R3.1 | 2.5, 2.6 |
  | R3.2 | 2.1 — ningún campo existente cambia de nombre/tipo/obligatoriedad |

## Implementation Notes

- `CleaningTaskListView` (`backend/app/cleaning/application/use_cases.py:1710-1727`) ganó dos campos, ambos `str | None`, sin default (después de `task`/`blocker` en el orden del dataclass): `property_name`, `property_internal_code`.
- La segunda llamada batched vive en `ListCleaningTasksUseCase.execute`, justo después de `states = await self._properties.states_for(...)` y antes de construir las `CleaningTaskListView`: `properties_by_id = {p.id: p for p in await self._properties.list_for_ids(tenant_id, property_ids)}`, reutilizando el mismo `property_ids` de `states_for` (mismo orden, mismos distintos).
- El comprehension original de `items=tuple(... for task in result.items)` se convirtió en un bucle `for` explícito (variable `views: list[CleaningTaskListView]`) para poder calcular `prop = properties_by_id.get(task.property_id)` una vez por fila y usarlo en dos campos; `.get()`, nunca `[]` — fails open a `None`/`None` igual que `blocker`.
- Test nuevo de aplicación (task 1.3): `backend/tests/cleaning/test_list_cleaning_tasks_use_case.py`. Sigue el patrón de `test_task_context_use_case.py` (fakes en memoria, sin DB). Clases reutilizables si hacen falta en §2: `FakeCleaningTaskRepository` (implementa solo `.list()`, ignora filtros) y `FakePropertyRepository` (implementa `states_for` — siempre `{}` — y `list_for_ids`, y graba las llamadas en `self.list_for_ids_calls` como `(tenant_id, frozenset(property_ids))`, útil como referencia para el contador de 2.4).
- **Regresión esperada, ya anotada por el propio `tasks.md`**: tras 1.2, `docker compose exec backend uv run pytest tests/cleaning/` da **2 failed** en `test_tasks_api.py` — `test_a_row_whose_property_state_is_unresolved_is_still_offered` y `test_the_listing_reads_the_property_states_once_per_page` — porque sus fakes ad-hoc (`_ResolvesNothing`, `_CountingProperties`) solo implementan `states_for` y ahora el caso de uso también llama a `list_for_ids`, que no existe en esos objetos (`AttributeError`). Esto es exactamente lo que 2.3 y 2.4 ya planean tocar (extender/reemplazar esos dos fakes con `list_for_ids`); no lo arreglé yo porque ese fichero es API-level y pertenece a §2. El resto de `tests/cleaning/` (778 tests) sigue en verde.
- `uv run pyright .` no introduce hallazgos nuevos atribuibles a este cambio más allá del patrón ya existente en el repo: los fakes de `test_list_cleaning_tasks_use_case.py` no implementan el protocolo completo de `CleaningTaskRepository`/`PropertyRepository` (mismos `reportArgumentType` que ya produce `test_task_context_use_case.py` con sus propios fakes parciales) — no es una regresión, es el estilo ya establecido para tests de `application/` con fakes.
