# Design: cleaning-completion-evidence-gatherer

## Context

`CompleteCleaningTaskUseCase` (`backend/app/cleaning/application/use_cases.py:883-968`) hereda
siete colaboradores de `_TaskLifecycleBase` (`use_cases.py:605-625`) y declara cuatro propios
(`completions`, `templates`, `photos`, `incidents`). Su `execute` hace exactamente dos cosas
separables: **reunir la evidencia** (`use_cases.py:913-940` — leer plantilla, parsearla, leer
completions, leer tipos de foto subidos, preguntar por la incidencia bloqueante y ensamblar un
`CleaningCompletionEvidence`) y **cerrar** (`task.complete()`, `save`, `_transition`, `audit`,
`commit`). La decisión de PRD §11 ya vive entera en `CleaningTask.complete()` y en el value object
`CleaningCompletionEvidence` (`backend/app/cleaning/domain/value_objects.py:73-120`), no en el caso
de uso: eso es lo que hace que este change sea sólo un movimiento de la **lectura**.

El único punto de construcción es `get_complete_cleaning_task_use_case`
(`backend/app/cleaning/api/dependencies.py:140-148`); `tasks_router.py:303` sólo lo anota como
tipo y no cambia. `backend/tests/test_layering.py` ya vigila por glob todo
`app/*/application/**/*.py`: prohíbe `sqlalchemy`/`fastapi` y cualquier import de
`infrastructure/` o `api/`, así que la regla de dependencia de R1.3 queda verificada por un test
que ya existe, sin añadir ninguno.

## Decisions

### D1 — El gatherer vive en `application/`, en un módulo propio

**Chosen:** `backend/app/cleaning/application/evidence.py`, con la clase
`CompletionEvidenceGatherer`. Es orquestación de puertos asíncronos —justo lo que
`steering/backend-architecture.md` asigna a `application/`— y el proyecto ya tiene precedente de
módulos de aplicación fuera de `use_cases.py`: `auth/application/recovery.py`,
`auth/application/user_admin.py`, `integrations/application/ingest.py`,
`integrations/application/webhooks.py`, `guests/application/portal.py`,
`properties/application/property_admin.py`. Un módulo aparte le da al test con fakes un import
pequeño en vez de arrastrar el `use_cases.py` de 1.700 líneas con sus ~40 imports.

Rejected: dejarlo dentro de `use_cases.py` justo encima del caso de uso — no cuesta imports, pero
engorda el fichero que este change existe para adelgazar y no separa nada navegable.
Rejected: un servicio de dominio en `domain/` — haría I/O asíncrono a través de repositorios desde
la capa que `backend-architecture.md` define como Python puro sin orquestación entre agregados.

### D2 — Se inyecta la clase concreta, no un `Protocol`

**Chosen:** `CompleteCleaningTaskUseCase.__init__` recibe `evidence: CompletionEvidenceGatherer`,
la clase concreta. Un puerto existe para **invertir** una dependencia que cruza una frontera de
capa; aquí las dos piezas viven en `application/`, así que un `Protocol` sería una interfaz con
una implementación y un consumidor — la ceremonia que Interface Segregation no pide. Lo único que
querría esa costura es un test con fakes del cierre completo, que el proposal deja explícitamente
*out of scope*.

Rejected: declarar un `CompletionEvidencePort` en `domain/ports.py` — no invierte nada
(`application` → `application`) y dejaría a `domain/` declarando un puerto que ningún adaptador
implementa. Si algún día llega el test de punta a punta con fakes, esa es la decisión a revisar.

### D3 — Firma: recibe la `CleaningTask` ya cargada, no su id

**Chosen:**

```python
class CompletionEvidenceGatherer:
    def __init__(
        self,
        *,
        templates: CleaningChecklistTemplateRepository,
        completions: CleaningChecklistCompletionRepository,
        photos: CleaningPhotoRepository,
        incidents: BlockingIncidentQuery,
    ) -> None: ...

    async def gather(
        self, *, tenant_id: uuid.UUID, task: CleaningTask
    ) -> CleaningCompletionEvidence: ...
```

La entidad, no el id: `_load_task` es quien aplica el scoping por tenant **y** por limpiadora
(R7.2/R7.3 de `cleaning`, `use_cases.py:533-543`) y tiene que correr antes; pasarle el id al
gatherer le obligaría a repetir esa lectura o le permitiría saltársela. De la tarea lee
`checklist_template_id`, `id` y `property_id`, que es exactamente lo que hoy lee el bloque movido.
Argumentos keyword-only, como el `execute` de todos los casos de uso del módulo.

Rejected: devolver la tupla `(spec, evidence)` para que el caso de uso conserve el `spec` — nadie
lo usa después del ensamblado (`use_cases.py:918-940` lo consume entero ahí mismo).

### D4 — Se mueve el bloque entero, comentarios incluidos; ninguna comparación cruza

**Chosen:** `use_cases.py:913-940` pasa tal cual a `gather()`: el `get` de la plantilla, el
`raise ChecklistTemplateNotFoundError("The task's checklist template no longer exists")` (R1.5,
mismo mensaje y misma traducción a **404 `NOT_FOUND`** en `api/errors.py:45` — este documento y
R1.5 decían 409 hasta que el panel de QA de la sección 1 leyó la tabla y el test que la fija,
`tests/cleaning/test_errors.py:76`), `parse_template_content`, el
`list_for_task` de completions, y las cinco asignaciones del `CleaningCompletionEvidence` —
**con el comentario de `use_cases.py:928-931`**, que es la única cosa que hoy protege la
diferencia entre `required_photo_types()` y `photo_types()` (R2.2, R4.3). Lo que se queda en
`execute`: `previous = task.status`, `task.complete(...)`, `save`, `_transition`, `audit`,
`commit`. El gatherer no compara nada — no hay ni un `-`, ni un `in`, ni un `if` sobre la
evidencia dentro de él (R2.1, R2.3); D8 de `cleaning-photos-storage` sigue entero porque la
entidad recibe el mismo objeto que hoy.

Rejected: aprovechar el movimiento para que el gatherer devuelva ya los faltantes — es
literalmente la violación de D8 que R2.3 manda rechazar en review.

### D5 — Cableado: se construye en `dependencies.py`, y no entra en `_lifecycle_kwargs`

**Chosen:** `get_complete_cleaning_task_use_case` construye el gatherer con los **mismos cuatro
adaptadores y la misma sesión** de hoy y lo pasa como `evidence=`, junto a
`**_lifecycle_kwargs(session)` (R1.4):

```python
def get_complete_cleaning_task_use_case(session: SessionDep) -> CompleteCleaningTaskUseCase:
    return CompleteCleaningTaskUseCase(
        evidence=CompletionEvidenceGatherer(
            templates=SqlAlchemyCleaningChecklistTemplateRepository(session),
            completions=SqlAlchemyCleaningChecklistCompletionRepository(session),
            photos=SqlAlchemyCleaningPhotoRepository(session),
            incidents=SqlAlchemyBlockingIncidentQuery(session),
        ),
        **_lifecycle_kwargs(session),
    )
```

`_lifecycle_kwargs` no se toca: su docstring dice «los siete colaboradores que toma **cada** caso
de uso del ciclo de vida» y el gatherer sólo lo usa el cierre. Ningún adaptador nuevo, ninguna
sesión nueva — es la misma sesión de la petición, ya marcada con el tenant, que es de lo que
depende el listener de `app/core/db.py`.

Rejected: un `Depends` propio para el gatherer (`get_completion_evidence_gatherer`) — el módulo
tiene un builder por caso de uso y esto no es uno; añadiría un nodo al grafo de dependencias de
FastAPI sin que nadie más lo consuma.

### D6 — La prueba de que no cambia el comportamiento es la suite existente, sin tocarla

**Chosen:** el oráculo de R3 son los tests que ya hay: `backend/tests/cleaning/test_tasks_api.py`
(incluidas las fronteras de orden de cláusulas y el caso de aislamiento de
`SqlAlchemyBlockingIncidentQuery` de su línea 360) y `test_task_lifecycle.py`, en verde **sin
editar ninguna aserción**. El contrato se comprueba con `make openapi` seguido de
`git diff --exit-code backend/openapi.json` (R3.3) — `make openapi` corre
`compose run --rm --no-deps -T backend`, así que funciona desde el worktree, al contrario que el
`npm run api:check` que `sdd/project.md` avisa que no.

Que un fichero de test **cambie** es la señal de que el change se pasó de alcance; el único test
que se añade es el nuevo de D7.

Rejected: añadir tests de caracterización del cierre antes de refactorizar — el cierre ya está
cubierto por integración de punta a punta; escribir una segunda red delante de la que hay sería
trabajo que R3 no pide y que habría que borrar después.

### D7 — El test nuevo: cuatro fakes, sin base de datos

**Chosen:** `backend/tests/cleaning/test_completion_evidence_gatherer.py`, con el molde de
`backend/tests/cleaning/test_photo_upload_use_case.py` (fakes de clase, constantes `TENANT`/`NOW`
a nivel de módulo, sin `httpx` y sin sesión). Los fakes **registran los argumentos con los que se
les llama**, que es lo que hace comprobable R4.5: que los cuatro puertos reciben el `tenant_id`
recibido, que completions y fotos se piden por `task.id` y que incidencias se pregunta por
`task.property_id`. Casos: camino positivo con evidencia completa (R4.2), plantilla con un
`photo_type` `required: false` que **no** aparece en `required_photo_types` (R4.3), plantilla
ausente → `ChecklistTemplateNotFoundError` (R4.4), y propagación de `tenant_id` (R4.5).

Rejected: parametrizar los cuatro casos sobre un fixture común — `steering/testing.md` pide tests
legibles en paralelo y estos cuatro montan plantillas distintas; cuatro funciones explícitas se
leen mejor que un `parametrize` con cuatro formas de plantilla.

### D8 — R1.3 se lee como «los puertos del dominio», no como «los de `ports.py`»

**Chosen:** el gatherer importa `CleaningChecklistTemplateRepository`,
`CleaningChecklistCompletionRepository` y `CleaningPhotoRepository` de
`backend/app/cleaning/domain/repositories.py` y `BlockingIncidentQuery` de
`backend/app/cleaning/domain/ports.py`, que es donde viven hoy. R1.3 los cita a los cuatro como
«los puertos declarados en `domain/ports.py`», pero sólo el último está ahí: los otros tres son
puertos de repositorio y este proyecto los pone siempre en `repositories.py`. **Ningún fichero se
mueve** — lo que R1.3 exige de verdad (depender de puertos del dominio y nunca de `sqlalchemy`,
`fastapi` ni `pydantic`) se cumple igual, y lo verifica `test_layering.py`.

Rejected: unificar los cuatro puertos en `ports.py` para que la letra de R1.3 cuadre — tocaría
todos los importadores de `cleaning` para satisfacer una imprecisión de redacción.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Application | `backend/app/cleaning/application/evidence.py` (**nuevo**) | `CompletionEvidenceGatherer`: cuatro puertos por constructor, `gather(tenant_id, task) -> CleaningCompletionEvidence`. Recibe el bloque de `use_cases.py:913-940` con sus comentarios. |
| Application | `backend/app/cleaning/application/use_cases.py` | `CompleteCleaningTaskUseCase.__init__` pasa de cuatro kwargs propios a uno (`evidence`); `execute` pierde las cuatro lecturas. Se retira el import de `CleaningCompletionEvidence` (queda sin usar; `ChecklistTemplateNotFoundError` y `parse_template_content` se quedan, los usan otros cuatro casos de uso). Se actualiza el docstring de la clase: sigue sin juzgar, pero ya no reúne. |
| API | `backend/app/cleaning/api/dependencies.py` | `get_complete_cleaning_task_use_case` construye el gatherer (D5); los cuatro imports de adaptadores se quedan, ahora usados desde ahí. |
| Tests | `backend/tests/cleaning/test_completion_evidence_gatherer.py` (**nuevo**) | Los cuatro casos de D7. |
| Tests | resto de `backend/tests/` | **Sin cambios** — es la evidencia de R3.1/R3.2. |
| Specs | `sdd/specs/cleaning.md` | En *Cierre y validación*, la frase «El caso de uso solo reúne la evidencia» pasa a nombrar al gatherer (la frase sobre dónde se aplican las tres cláusulas no cambia); en *Key files*, entra `application/evidence.py`. Lo escribe `/sdd:archive`, no `/sdd:run`. |

## Data & interfaces

Sin cambios de esquema, sin migración de Alembic, sin variables de entorno nuevas. El contrato
HTTP no se toca: `backend/openapi.json` debe quedar byte a byte idéntico (R3.3). La única interfaz
nueva es interna al backend: el constructor y el `gather()` de D3.

## Risks & mitigations

- **Que el orden de las cláusulas cambie sin que nadie lo note.** Es imposible por construcción —
  el orden vive en `CleaningTask.complete()`, que no se toca— y además está fijado por los tests
  de frontera de `test_tasks_api.py`, que corren sin editarse (R3.2).
- **Deriva de contrato.** `make openapi` + `git diff --exit-code backend/openapi.json` en la
  sección Verification; cualquier byte de diferencia es un fallo del change, no una mejora (D6).
- **Que el gatherer acabe comparando.** La tentación real es devolver «lo que falta». R2.3 manda
  rechazarlo en review y D4 lo dice en el docstring del módulo nuevo, junto a la referencia a D8
  de `cleaning-photos-storage`.
- **Import muerto.** Quitar `CleaningCompletionEvidence` de los imports de `use_cases.py` es
  obligatorio (ruff F401 lo marcaría); comprobado que es su único uso en ese fichero.
- **Aislamiento entre tenants.** No hay lectura nueva ni scoping nuevo: los cuatro `tenant_id` que
  se pasaban se siguen pasando, y R4.5 los ancla con fakes que registran sus argumentos.

## Open questions

Ninguna abierta. Las dos que había se resolvieron en el gate del 2026-08-16:

1. **Nombre de la clase y del kwarg** → `CompletionEvidenceGatherer`, recibido como `evidence=`.
   Se descartaron `CleaningCompletionEvidenceGatherer` (el prefijo `Cleaning` es redundante dentro
   de `app/cleaning/`) y el kwarg `gatherer=`.
2. **Ubicación de los cuatro puertos (D8)** → se quedan donde están: `BlockingIncidentQuery` en
   `domain/ports.py` y los tres de repositorio en `domain/repositories.py`. Se descartó unificarlos
   en `ports.py` para hacer literal la letra de R1.3, porque tocaría a todos los importadores de
   `cleaning` y ensancharía un diff que R3 quiere estrecho.
