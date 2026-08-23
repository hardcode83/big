# Design: cleaner-photo-requirements

## Context

El dominio `cleaning` ya tiene todo lo que esta capacidad necesita leer, y no tiene la lectura.
`ChecklistTemplateSpec.required_photos` (`backend/app/cleaning/domain/value_objects.py:135`) es una
**tupla** de `RequiredPhotoSpec` —`photo_type`, `label`, `required`— parseada por
`parse_template_content` (`value_objects.py:216`), que rechaza un `photo_type` duplicado
(`value_objects.py:266`) igual que rechaza un `item_id` duplicado. `CleaningPhotoRepository`
(`domain/repositories.py:202`) publica `uploaded_photo_types()` (línea 264), el `frozenset` con el
que `CompletionEvidenceGatherer` (`application/evidence.py:69`) alimenta a
`CleaningTask.complete()`. Y `tasks_router.py` ya tiene **tres** `GET` hermanos de solo lectura
acotados a una tarea —`/checklist` (línea 353), `/context` (500) y `/photos` (569)—, los tres con
`ReadDep` = `READ_CLEANING_TASKS` (línea 85).

Lo que falta es exclusivamente la proyección: los tres campos de cada `RequiredPhotoSpec` no salen
por ninguna ruta que `UserRole.CLEANER` alcance. Este diseño añade una cuarta ruta hermana, un caso
de uso que espeja `GetChecklistUseCase` (`application/use_cases.py:1402`) y dos esquemas Pydantic.
**Cero migraciones, cero columnas, cero permisos, cero métodos nuevos de puerto, cero excepciones
de dominio nuevas** — `_MAPPING` de `api/errors.py` ya mapea a `404` las dos únicas que se lanzan
(`CleaningTaskNotFoundError`, `ChecklistTemplateNotFoundError`).

## Decisions

### D1 — Ruta hermana, no ensanchar `ChecklistResponse`

**Chosen:** `GET /api/v1/cleaning-tasks/{task_id}/photo-requirements`, en `tasks_router.py`, junto
a las otras tres. Es el patrón vivo del propio router para una proyección de solo lectura acotada a
una tarea, no toca ningún esquema publicado, y deja `data` significando *el recurso* —la convención
que `ChecklistResponse` (`api/schemas.py:280`) y `CleaningPhotoListResponse` comparten: una clave
`data` y nada más. Y no encarece `/checklist`: ensanchar `ChecklistResponse` obligaría a
`GetChecklistUseCase` a leer `cleaning_photos` en **cada** pintado del checklist, incluido el de
quien sólo va a marcar ítems.

Rejected: ensanchar `ChecklistResponse` con un segundo array — modifica un esquema ya publicado en
`backend/openapi.json`, rompe la convención de `{data: [...]}` y añade una lectura a un camino que
no la necesita.
Rejected: meterlo en `GET /{task_id}/context` — descartado en el proposal (§Out of scope): exigiría
**enmendar** el `SHALL` de «once campos y solo once» de `specs/cleaner-task-context.md`.

### D2 — `uploaded: bool`, reutilizando `uploaded_photo_types()` — el puerto se queda en cuatro métodos

**Chosen:** la cobertura de R3 se publica como un booleano por entrada, derivado de
`CleaningPhotoRepository.uploaded_photo_types(tenant_id, task.id)` tal cual. R3.1 admite
explícitamente esta lectura («…o al menos si existe alguna»), y es la forma más fuerte de cumplir
R3.4: no es que se comparta *un* puerto con `CompletionEvidenceGatherer`, es que se comparte **el
mismo método**, el que el cierre compara. El docstring de `CleaningPhotoRepository` se conserva
íntegro —«Four methods, and each one has a caller in this change … A fifth method "for later" would
be the Interface Segregation failure `steering/backend-architecture.md` names»— sin necesidad de
excepción escrita.

Y espeja exactamente `ChecklistItemStateResponse` (`api/schemas.py:260`), que es
`{item_id, label, required, completed, …}`: la entrada nueva es
`{photo_type, label, required, uploaded}`. Esa simetría no es estética, es la que el dominio ya
declara suya en `CleaningCompletionEvidence` — *«the two photo fields are the exact mirror of the
two item fields, down to the shape of the accessor … one rule, expressed twice in the same words»*
(`value_objects.py:82`).

Rejected: un quinto método `uploaded_photo_counts()` devolviendo un recuento por tipo — obligaría a
`CompletionEvidenceGatherer` a depender de un método que no usa (la I de SOLID que
`steering/backend-architecture.md` nombra), a escribir una excepción razonada a ese docstring, y el
recuento exacto ya lo puede contar el cliente desde `GET /{task_id}/photos`, que publica
`photo_type` por foto.

### D3 — Nombres de esquema: `PhotoRequirementStateResponse` y `PhotoRequirementsResponse`

**Chosen:** entrada `PhotoRequirementStateResponse`, sobre `PhotoRequirementsResponse`. Los dos
espejan la pareja `ChecklistItemStateResponse` / `ChecklistResponse` (el «State» está por lo mismo:
la entrada lleva estado, `uploaded`), y **ninguno de los dos colisiona**: medido contra los 144
esquemas de `backend/openapi.json` y contra `grep -rn PhotoRequirement backend/ frontend/`, que no
devuelve nada. Así el contrato no gana una tercera colisión al lado de
`app__cleaning__api__schemas__CleaningPhotoResponse` / `app__dashboard__api__schemas__CleaningPhotoResponse`,
que es lo que la nota 2 del proposal pedía evitar: esos nombres *mangled* llegan al cliente tipado
del frontend y son los que un consumidor escribe a mano.

Rejected: cualquier nombre que empiece por `CleaningPhoto…` — es exactamente el prefijo que ya
colisiona, y una tercera colisión mangla también las dos que hoy sobreviven por módulo.

### D4 — El orden es el declarado en la plantilla, iterando la tupla; y eso enmienda R1.3 y R2.2

**Chosen:** el caso de uso itera `spec.required_photos` —la tupla— exactamente como
`GetChecklistUseCase` itera `spec.items` (*«Driven by the template, not by the completions
table»*, `use_cases.py:1445`). Sale gratis un orden **más fuerte** que el que R1.3 pide: es estable
entre peticiones y entre procesos porque es el orden persistido del array JSONB (Postgres conserva
el orden de un array en `jsonb`; sólo reordena claves de objeto), y además es el que escribió quien
creó la plantilla — que es el orden en que la limpiadora hace el trabajo, y por tanto el orden en
que la UI debe pintar los botones. No hace falta ordenar nada, y el riesgo que R1.3 nombra
—`frozenset` con orden de iteración dependiente de la semilla de hash— no se llega a correr porque
no se toca ningún `frozenset` para construir la colección.

Esto **enmienda dos frases del proposal**, y la enmienda baja a `proposal.md` en este mismo change
(no sólo aquí, o acabaría como un `SHALL` falso en la spec viva al archivar):

- **R1.3**: el orden estable pasa a ser, nombrado, el *declarado en la plantilla* —el de la tupla
  `ChecklistTemplateSpec.required_photos`— en lugar de justificarse por el `frozenset` de
  `photo_types()`.
- **R2.2**: la fuente pasa a ser `spec.required_photos`, de donde `photo_types()` se deriva
  (`value_objects.py:142`), y no `photo_types()` — que no puede ser la fuente de nada aquí, porque
  descarta el `label`. La intención de R2.2 se cumple íntegra y literalmente: **no** se filtra por
  `required`, nunca se llama a `required_photo_types()`, y un tipo con `required: false` sale en la
  colección.

Rejected: `sorted(spec.photo_types())` y recuperar el `label` indexando después — dos pasadas sobre
lo mismo, orden alfabético en vez del orden del trabajo, y un `frozenset` de por medio que hay que
volver a ordenar para que sea estable.

### D5 — `GetPhotoRequirementsUseCase(_TaskTransitionMixin)`: `_load_task` heredado, sin tercera copia

**Chosen:** el caso de uso hereda `_TaskTransitionMixin` (`use_cases.py:535`) **sólo por
`_load_task`** (línea 551), con constructor propio que fija únicamente los tres puertos que usa
(`tasks`, `templates`, `photos`). Es literalmente el patrón que `ListCleaningPhotosUseCase`
(`use_cases.py:1758`) ya documenta de sí mismo —*«Inherits `_TaskTransitionMixin` for `_load_task`
alone, exactly as the upload does and for exactly the same two rules»*— y es lo que hace verdadera
la letra de R1.5: el `404` indistinguible entre las tres causas queda **heredado de `_load_task`
sin excepción propia**, no reimplementado. Los otros cuatro atributos que el mixin anota
(`_properties`, `_transitions`, `_timeline`, `_reservations`) no se fijan y no se tocan: `_transition`
nunca se llama, igual que en el listado de fotos.

Rejected: extender `_TaskLifecycleBase` (`use_cases.py:623`) — su constructor exige siete
dependencias, cinco de ellas para transiciones de estado que una proyección de solo lectura no hace.
Es el fallo de segregación de interfaces del propio `steering/backend-architecture.md`.
Rejected: copiar las seis líneas en línea, como hace `GetChecklistUseCase` (`use_cases.py:1421-1426`)
— sería la **tercera** copia de una regla de acotamiento por fila, y R1.5 dice «sin excepción
propia» precisamente sobre esa regla. Lo que este diseño **no** hace es migrar `GetChecklistUseCase`
al mixin: la copia que ya existe es previa a este change y arreglarla ensancharía el diff (ver
§Open questions, OQ1).

### D6 — `label` no añade fila al censo de la regla 11: este change es lector, y sin audiencia nueva

**Chosen:** no se toca la tabla de sumideros de `steering/security.md`. Las dos columnas JSONB de
plantilla (`items`, `required_photos`) no están en el censo de veintiuna columnas, y este change
**no escribe** ninguna de las dos: sólo lee. Y no abre audiencia nueva —el precedente decisivo—:
`ChecklistItemStateResponse.label` (`api/schemas.py:261`) ya publica el `label` de la **columna
hermana de la misma fila de la misma tabla** al mismo permiso (`READ_CLEANING_TASKS`) y a los mismos
tres roles. Publicar el de las fotos es simétrico con lo que ya se entrega, no un ensanche.

Es la diferencia con `properties.access_notes`, que sí entró en el censo por un change que sólo le
añadía un lector (`tech-incident-context`): allí el lector nuevo era un **rol nuevo** —el técnico,
que no tiene `READ_PROPERTIES`— leyendo una nota de propiedad que en la práctica lleva códigos de
portal. Aquí no hay rol nuevo ni columna nueva en el camino.

Rejected: declarar una fila de censo «por si acaso» — una fila cuyo escritor no es este change
atribuye propiedad fuera de la tabla que es la autoridad, que es exactamente lo que
`backend/tests/test_rule11_ownership.py` se puso a vigilar. **Consecuencia para el archivado**: la
spec viva que salga de aquí (`sdd/specs/cleaner-photo-requirements.md`) **no** debe contener prosa
que atribuya escritor ni heredero de ninguna columna del censo; `sdd/specs/` está dentro de lo que
ese test recorre, y `sdd/changes/` —donde vive este documento— está excluido entero.

Lo que sí queda anotado, sin cerrarlo aquí, es un hueco **preexistente** que se ve desde este
diseño: el `label` de esas dos columnas es texto libre de hasta 200 caracteres
(`MAX_LABEL_LENGTH`, `value_objects.py:21`) que teclea un `OWNER`/`PROPERTY_MANAGER` con
`MANAGE_CLEANING_TEMPLATES`, y su escritor vive desde el change `cleaning` sin fila en el censo. El
panel que revisó esas columnas cerró el agujero **estructural** —el docstring de `items_as_json()`
lo dice: *«a key the parser never inspected would survive into the column and back out of `GET`
unchanged»*— y no el del **valor** del `label`. Es de otro change (ver OQ2).

### D7 — El catálogo de `404` de la ruta, y el `422` que no se declara

**Chosen:** la ruta declara `responses={404: ...}` con las **dos** causas que su propio handler
puede alcanzar, siguiendo el criterio que `_PHOTO_UPLOAD_RESPONSES` y `_PHOTO_LISTING_RESPONSES`
(`tasks_router.py:381,558`) ya fijaron: *«each entry below is a row of
`app/cleaning/api/errors.py::_MAPPING` reached from this handler's own raise sites, not a guess»*.
Las dos son `CleaningTaskNotFoundError` (R1.5, desde `_load_task`) y `ChecklistTemplateNotFoundError`
(R1.6). No hay `409`: R1.4 dice que la ruta responde con independencia del estado de la tarea, igual
que `/checklist`. El `422` no se declara — FastAPI lo inyecta solo por el `task_id` validado y
`_point_errors_at_envelope` lo reescribe al sobre.

Rejected: no declarar nada y dejar el catálogo genérico — `app/core/openapi.py` no inventa
catálogos por endpoint y deja la puerta abierta a que un endpoint declare el suyo; éste califica.

### D8 — R2.3 se cumple en la `description` de la ruta, en las dos direcciones

**Chosen:** la relación entre esta colección y el `404` de la subida se escribe en la
`description` de la ruta nueva —el texto va al contrato publicado, que es donde R2.3 la pide («en el
contrato publicado»)— nombrando que un `photo_type` ausente de esta colección es exactamente lo que
`POST /cleaning-tasks/{task_id}/photos` responde `404`. Y se añade la frase recíproca a la
`description` del `404` de `_PHOTO_UPLOAD_RESPONSES`, que hoy dice *«The `photo_type` is not
declared by the task's template»* sin decir **dónde** se leen los declarados. Es el único cambio de
este diseño sobre un texto existente, y es una descripción, no un esquema.

Rejected: dejarlo sólo en `sdd/specs/cleaning.md` — la spec viva no es el contrato publicado, y R2.3
dice «publicado» para que el cliente no descubra la relación por coincidencia.

## Cobertura de requisitos

| Req | Dónde queda | Nota |
|---|---|---|
| R1.1 | `GetPhotoRequirementsUseCase.execute` + `PhotoRequirementsResponse` | una entrada por `photo_type` con su `label` |
| R1.2 | iterar una tupla vacía da `{"data": []}` | `parse_template_content` acepta `required_photos: []`; nunca hay `404` por vacío |
| R1.3 | D4 — orden de la tupla, no de un `frozenset` | **enmienda R1.3 en `proposal.md`** |
| R1.4 | el caso de uso no mira `task.status` | ningún `InvalidCleaningTransitionError`; ningún `409` en D7 |
| R1.5 | `_load_task` heredado (D5) | sin excepción propia; test de las tres causas |
| R1.6 | `ChecklistTemplateNotFoundError`, ya en `_MAPPING` → `404` | mismo mensaje que el cierre y que `/checklist` |
| R2.1 | colección `data` (no `required_photos`) + clave `required` por entrada | *admisible* = pertenecer; *obligatorio* = `required: true` |
| R2.2 | D4 — fuente `spec.required_photos`, nunca `required_photo_types()` | **enmienda R2.2 en `proposal.md`**; guard estructural |
| R2.3 | D8 — `description` de la ruta nueva + recíproca en la de subida | en el contrato publicado |
| R3.1 | `uploaded: bool` desde `uploaded_photo_types(tenant_id, task.id)` (D2) | acotado al tenant y a la tarea por la firma del puerto |
| R3.2 | ningún campo de veredicto; guard estructural que lo prueba | sin `satisfied`, sin `can_complete`, sin diferencia de conjuntos |
| R3.3 | **sin implicación de diseño**: no se toca `CleaningTask.complete()` ni `entities.py` | lo prueba el guard de R3.2 + `test_completion_clause_contract.py`, que ya existe |
| R3.4 | se comparte el **método** del puerto, no el ensamblado (D2) | `evidence.py` no se importa ni se modifica |
| R4.1 | `ReadDep` = `Permission.READ_CLEANING_TASKS` (`tasks_router.py:85`) | sin decisión de audiencia |
| R4.2 | **sin implicación de diseño**: no se toca `auth/domain/policy.py` | lo prueba un test de rol por endpoint |
| R4.3 | `CleaningActor.restrict_to_cleaner_id` dentro de `_load_task` | la ruta no admite ningún parámetro de consulta |
| R4.4 | `PhotoRequirementStateResponse` enumera cuatro campos, sin `from_attributes` | el patrón de `CleaningPhotoResponse` (`schemas.py:296`) |
| R4.5 | test de conjunto de campos cerrado, escrito a mano | patrón `CONTEXT_FIELDS` de `tests/maintenance/test_incident_context_api.py:51` |
| R5.1 | **sin implicación de diseño**: no se toca `UploadCleaningPhotoUseCase` | `photo_types()` gana un segundo llamante — ver Riesgo 1 |
| R5.2 | **sin implicación de diseño**: no se toca `complete()` ni `missing_required_photo_types()` | |
| R5.3 | **sin implicación de diseño**: `/context` no se toca (D1) | ninguna referencia cruzada obligatoria |
| R5.4 | `make openapi` + `npm run api:generate`, los dos artefactos commiteados | ver §Risks, Riesgo 3 |

## Changes by area

| Area | Files | Change |
|---|---|---|
| `domain/` | `app/cleaning/domain/value_objects.py` | **sólo docstrings.** `photo_types()` dice «both have exactly one caller» y pasa a tener dos; se corrige nombrando al segundo. Ningún cambio de comportamiento |
| `application/` | `app/cleaning/application/use_cases.py` | nuevos: `PhotoRequirementView` (dataclass, espejo de `ChecklistItemView:1391`) y `GetPhotoRequirementsUseCase(_TaskTransitionMixin)` con tres puertos |
| `api/` | `app/cleaning/api/schemas.py` | nuevos: `PhotoRequirementStateResponse` (4 campos enumerados) y `PhotoRequirementsResponse` (`data`) |
| `api/` | `app/cleaning/api/tasks_router.py` | nueva ruta `GET /{task_id}/photo-requirements` con `ReadDep`, `_PHOTO_REQUIREMENTS_RESPONSES` (D7) y la `description` de D8; **una frase** añadida al `404` de `_PHOTO_UPLOAD_RESPONSES` |
| `api/` | `app/cleaning/api/dependencies.py` | `get_photo_requirements_use_case(session)` junto a `get_checklist_use_case:180` |
| `infrastructure/` | — | **nada.** `SqlAlchemyCleaningPhotoRepository.uploaded_photo_types` y `…ChecklistTemplateRepository.get` ya existen |
| migraciones | — | **nada.** Ni columna, ni índice, ni backfill |
| tests | `backend/tests/cleaning/test_photo_requirements_use_case.py` (nuevo) | unit con fakes en memoria de los tres puertos, según `steering/backend-architecture.md` §Cómo se testea |
| tests | `backend/tests/cleaning/test_photo_requirements_api.py` (nuevo) | integración: campos cerrados (R4.5), vacío `200` (R1.2), orden de plantilla (R1.3), cualquier estado (R1.4), `404` × 3 causas (R1.5) y por plantilla borrada (R1.6), tipo opcional incluido (R2.2), sin fugas de plantilla (R4.4), RBAC por rol (R4.1/R4.2) y **aislamiento de tenant** (regla 1 de `steering/security.md`) |
| tests | `backend/tests/cleaning/test_completion_clause_contract.py` | un guard AST más: el módulo del caso de uso nuevo no nombra `required_photo_types`, `missing_required_photo_types`, `CleaningCompletionEvidence` ni `CompletionEvidenceGatherer` (R2.2 + R3.2 + R3.4, estructuralmente) |
| contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados y commiteados en el mismo PR (`steering/documentation.md`) |
| docs | `docs/cleaning.md` | la ruta nueva en el inventario de endpoints de la capability |

## Data & interfaces

**Esquema de base de datos: sin cambios.** Ni migración, ni columna, ni índice.

**Variables de entorno: ninguna.**

Contrato nuevo (los cuatro campos son el conjunto cerrado que R4.5 fija con un test):

```
GET /api/v1/cleaning-tasks/{task_id}/photo-requirements     → 200 PhotoRequirementsResponse
                                                              404 ErrorEnvelope
{"data": [{"photo_type": "kitchen", "label": "Cocina",       "required": true,  "uploaded": true},
          {"photo_type": "before",  "label": "Antes de empezar", "required": false, "uploaded": false}]}
```

Firmas nuevas (sin cuerpo; la implementación es de `/sdd:run`):

```python
# application/use_cases.py
@dataclass(frozen=True)
class PhotoRequirementView:
    photo_type: str
    label: str
    required: bool
    uploaded: bool

class GetPhotoRequirementsUseCase(_TaskTransitionMixin):
    def __init__(self, *, tasks: CleaningTaskRepository,
                 templates: CleaningChecklistTemplateRepository,
                 photos: CleaningPhotoRepository) -> None: ...
    async def execute(self, *, tenant_id: uuid.UUID, task_id: uuid.UUID,
                      actor: CleaningActor) -> list[PhotoRequirementView]: ...
```

**Puertos: sin cambios.** `CleaningPhotoRepository` sigue en cuatro métodos (D2);
`CleaningChecklistTemplateRepository.get` y `CleaningTaskRepository.get` se usan tal cual.

**Excepciones de dominio: sin cambios.** Las dos que la ruta puede levantar ya tienen fila en
`_MAPPING` (`api/errors.py:41-42`), así que el test de exhaustividad de `test_errors.py` no se
mueve.

## Risks & mitigations

1. **`photo_types()` gana un segundo llamante y su docstring dice que tiene uno.**
   `value_objects.py:154` afirma *«The two photo accessors answer different questions and both have
   exactly one caller»*. El diseño no llama a `photo_types()` (D4 usa la tupla), así que la frase
   **sigue siendo cierta** — pero es exactamente la clase de afirmación que envejece sin que nada se
   ponga rojo. *Mitigación*: la tarea que toque `value_objects.py` revisa esa frase contra el árbol
   y, si el `run` acaba llamando a `photo_types()`, la corrige nombrando al segundo llamante. No se
   deja al panel encontrarlo.
2. **Un test de aislamiento de tenant que no puede fallar.** Sobre una sesión ya marcada con el
   tenant, los *loader criteria* globales de `app/core/db.py` filtran antes de que la query llegue,
   así que la prueba pasa por construcción y no demuestra nada. *Mitigación*: el test de
   aislamiento usa una sesión **sin marcar**, como el resto de los de `tests/cleaning/`; el
   `conftest.py` del paquete ya tiene el aparejo.
3. **Regenerar el contrato del frontend no funciona tal cual en un worktree enlazado.**
   `cd frontend && npm run api:check` —el comando que manda la sección Verification— falla aquí:
   el contenedor `frontend` monta sólo `./frontend`. *Mitigación*: usar la salida documentada en
   `sdd/project.md` §Worktree bootstrap (`docker compose cp` de `backend/openapi.json` +
   `ln -sfn /app /frontend`), verificada en `dashboard-api`. Y `npm test` da **2 ficheros en rojo
   ajenos al change** por la misma causa: no se leen como regresión.
4. **`uploaded_photo_types` devuelve conjunto vacío cuando la tarea no es de este tenant.** Es su
   contrato declarado («the safe direction: it blocks a completion rather than granting one»), y
   aquí la dirección segura es la misma: `uploaded: false` para todo. Pero el caso no se alcanza —
   `_load_task` ya levantó `404` antes—, así que el vacío nunca se publica. *Mitigación*: el orden
   de las dos llamadas (`_load_task` primero, siempre) queda escrito en el docstring del caso de
   uso, como lo está en `ListCleaningPhotosUseCase`.
5. **Rendimiento: dos lecturas por petición, ninguna paginada.** Una por la plantilla y una
   `DISTINCT` sobre las fotos de la tarea, ambas acotadas. El `ASSUMPTION` del proposal se mantiene
   —decenas de fotos por tarea, no miles— y `MAX_REQUIRED_PHOTOS = 50` (`value_objects.py:24`) acota
   el tamaño de la respuesta por construcción. Sin paginación, a propósito.

## Open questions

**OQ1 — ¿Se migra `GetChecklistUseCase` al mixin en este change?**
`GetChecklistUseCase` (`use_cases.py:1421-1426`) reimplementa en línea las seis líneas de
`_load_task` en vez de heredarlas, y es la única de las cuatro proyecciones por tarea que lo hace.
Migrarla es un cambio de cero comportamiento (`_load_task` levanta la misma excepción con el mismo
mensaje) y quita una copia de una regla de acotamiento por fila. **Recomendación: no hacerlo aquí**
— la copia es previa a este change, el diff se mantiene honesto, y la asimetría queda nombrada en
este documento para que el panel no la lea como un descuido. Si se acepta hacerlo, es una tarea
propia y explícita en `tasks.md`.

**OQ2 — El `label` de las dos columnas JSONB de plantilla y el censo de la regla 11 (D6).**
Es texto libre de 200 caracteres que teclea un `OWNER`/`PROPERTY_MANAGER`, con escritor vivo desde
el change `cleaning` y **sin fila** en la tabla de sumideros, mientras `properties.access_notes` —el
caso análogo— sí la tiene. Está fuera del alcance de este change, que no escribe esas columnas
(D6). **Recomendación: candidata de roadmap propia**, con su propio panel, no una tarea de aquí.
Si se acepta, `/sdd:archive` la añade a `sdd/roadmap.md` al cerrar este change.

**Resueltas antes de escribir este documento** (las tres que `BLOCKED.md` §2 dejó pendientes, y por
las que `/sdd:tasks` se paró): dónde vive la capacidad → **D1**, ruta hermana; la forma de R3 contra
el puerto → **D2**, `uploaded: bool` reutilizando `uploaded_photo_types()`; el nombre del esquema →
**D3**, `PhotoRequirementStateResponse` / `PhotoRequirementsResponse`. La enmienda de R1.3/R2.2 que
**D4** obliga está aprobada y baja a `proposal.md` en este change.
