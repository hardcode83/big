# Proposal: cleaning-completion-evidence-gatherer

## Why

`CompleteCleaningTaskUseCase` (`backend/app/cleaning/application/use_cases.py:883`) tiene **once
colaboradores**: siete que hereda de `_TaskLifecycleBase` (`tasks`, `properties`, `transitions`,
`timeline`, `reservations`, `audit`, `uow`) y cuatro propios (`completions`, `templates`, `photos`,
`incidents`). La entrada del roadmap
([`sdd/roadmap/cleaning-completion-evidence-gatherer.md`](../../roadmap/cleaning-completion-evidence-gatherer.md))
la abrió el arquitecto del panel de `cleaning-photos-storage` al arbitrar por qué la tarea 5.4 de
aquel change no se testeó con fakes: **que un caso de uso no se pueda testear con fakes a coste
razonable no es una propiedad del dominio, es una señal**, y once colaboradores es la señal.

La salida ya está insinuada en el propio código: el docstring de la clase dice *«Gathers the
evidence; does not judge it»* y enumera sus cuatro lecturas. Este change las saca a un colaborador
propio. **No toca D8** de `cleaning-photos-storage`: las tres cláusulas de PRD §11 se siguen
aplicando dentro de `CleaningTask.complete()` y en ningún otro sitio — se mueve la **lectura**, no
la **decisión**, y la entidad sigue recibiendo un `CleaningCompletionEvidence` ya poblado
exactamente igual que hoy.

**Un matiz que la entrada del roadmap da por hecho y no se sostiene entero, comprobado en el
código antes de escribir esto.** La entrada afirma que con la extracción «los fakes del camino
positivo pasan a ser baratos». Sólo en parte: de los once colaboradores, **siete son de la base y
los usa el cierre de verdad** — `_load_task` usa `tasks`; `_transition` usa `properties`,
`transitions`, `timeline` y `reservations`; más `audit` y `uow`. Extraer los cuatro propios deja el
caso de uso en **ocho** (siete de base + el gatherer), no en algo trivialmente fakeable: testear el
cierre completo con fakes seguiría costando ~8 dobles. Lo que sí se vuelve barato —y es la parte
que de verdad importa— es testear **la reunión de la evidencia en aislamiento**, con cuatro fakes y
sin base de datos, incluida la sutileza que hoy sólo está protegida por un comentario
(`use_cases.py:928-931`: leer `photo_types()` en vez de `required_photo_types()` haría obligatorio
todo tipo declarado y rompería R4.5 de `cleaning-photos-storage`). Adelgazar
`_TaskLifecycleBase` es un problema distinto, más grande, y queda fuera de alcance (ver *Out of
scope*).

## What changes

Aparece un colaborador propio —nombre de trabajo `CompletionEvidenceGatherer`— que posee las cuatro
lecturas del cierre (plantilla, completions, tipos de foto subidos, incidencia bloqueante) y
devuelve un `CleaningCompletionEvidence` poblado. `CompleteCleaningTaskUseCase` deja de inyectar
`completions`, `templates`, `photos` e `incidents`, pasa a inyectar el gatherer, y su `execute()`
queda en: cargar la tarea → pedir la evidencia → `task.complete(...)` → guardar, transicionar,
auditar, commitear. El cableado de `backend/app/cleaning/api/dependencies.py:141` se ajusta al
constructor nuevo. Ningún cambio de contrato HTTP, de errores, ni de orden de evaluación de las
cláusulas: es una refactorización con comportamiento observable idéntico, y eso es exactamente lo
que hay que demostrar.

## Requirements

### R1 — La orquestación de lectura vive en un colaborador propio

**As a** desarrollador del dominio de limpieza, **I want** que reunir la evidencia del cierre sea
una responsabilidad con nombre propio, **so that** el caso de uso del cierre deje de ser el sitio
donde conviven once colaboradores.

Acceptance criteria:

1. THE SYSTEM SHALL exponer un colaborador propio cuya única responsabilidad sea producir un
   `CleaningCompletionEvidence` a partir de `tenant_id` y la `CleaningTask`, recibiendo por
   constructor exactamente los cuatro puertos que hoy son propios del cierre
   (`CleaningChecklistTemplateRepository`, `CleaningChecklistCompletionRepository`,
   `CleaningPhotoRepository`, `BlockingIncidentQuery`) y ningún otro.
2. THE SYSTEM SHALL dejar `CompleteCleaningTaskUseCase` con **ocho** colaboradores — los siete de
   `_TaskLifecycleBase` más el gatherer —, verificable por inspección de las firmas de
   `__init__`.
3. WHERE el gatherer necesita persistencia, THE SYSTEM SHALL depender de los puertos declarados en
   `backend/app/cleaning/domain/ports.py` y nunca de `sqlalchemy`, `fastapi` ni `pydantic`, según
   la regla de dependencia de `steering/backend-architecture.md`.
4. WHEN el proceso arranca, THE SYSTEM SHALL construir el gatherer en
   `backend/app/cleaning/api/dependencies.py` con los mismos adaptadores concretos que hoy recibe
   el caso de uso, sin añadir ninguna sesión ni ningún adaptador nuevo.
5. THE SYSTEM SHALL mantener `ChecklistTemplateNotFoundError` como el error de una plantilla
   ausente, lanzado ahora desde el gatherer, con el mismo mensaje y la misma traducción a `404`.
   (Este criterio decía `409` hasta que el panel de QA de la sección 1 lo comprobó: la tabla de
   `backend/app/cleaning/api/errors.py:45` mapea esta excepción a **404 `NOT_FOUND`**, y
   `backend/tests/cleaning/test_errors.py:76` lo fija. La redacción era falsa desde el principio;
   el mapeo no se toca en este change, y lo que R1.5 exige —mismo tipo, mismo mensaje, misma
   respuesta HTTP que hoy— se cumple igual.)

### R2 — La decisión no se mueve: D8 sigue intacto

**As a** arquitecto, **I want** que la refactorización se detenga en la lectura, **so that** la
invariante que `cleaning` concentró en un solo método no se parta en dos por comodidad.

Acceptance criteria:

1. THE SYSTEM SHALL aplicar las tres cláusulas de PRD §11 **exclusivamente** dentro de
   `CleaningTask.complete()`; el gatherer no compara nada, sólo lee y ensambla.
2. THE SYSTEM SHALL construir el `CleaningCompletionEvidence` con los mismos cinco campos y los
   mismos accesores que hoy — en particular `spec.required_photo_types()` y **no**
   `spec.photo_types()`.
3. IF alguien introduce en el gatherer una comparación entre lo requerido y lo aportado, THEN el
   panel de review SHALL rechazarlo como violación de D8 de `cleaning-photos-storage`.
4. THE SYSTEM SHALL conservar `CleaningCompletionEvidence` y sus métodos
   (`missing_required_photo_types()` y el equivalente de ítems) sin cambios de firma ni de
   semántica.

### R3 — El cierre no cambia de comportamiento observable

**As a** manager que opera limpiezas, **I want** que el cierre siga comportándose exactamente igual,
**so that** una mejora interna no me cambie un `409` por un `500` ni el orden de lo que se me
reporta.

Acceptance criteria:

1. THE SYSTEM SHALL mantener idénticos el código de estado, el cuerpo y el `error.code` de todas
   las respuestas de `POST /api/v1/cleaning-tasks/{id}/complete`, demostrado por que la suite de
   `backend/tests/cleaning/test_tasks_api.py` pasa **sin modificar ninguna aserción**.
2. THE SYSTEM SHALL evaluar las cláusulas en el mismo orden que hoy —ítems, fotos, incidencia— y
   reportar la primera que falle, con los tests de frontera existentes en verde y sin tocarlos.
3. THE SYSTEM SHALL dejar `backend/openapi.json` **byte a byte idéntico** tras `make openapi`: si
   el contrato cambia, la refactorización se pasó de alcance.
4. WHEN el cierre supera la validación, THE SYSTEM SHALL seguir resolviendo el estado de la
   propiedad por contexto (`AWAITING_CHECKIN` / `READY_FOR_NEXT_GUEST` / `VACANT_READY`) mediante
   la misma llamada a `_transition(..., with_reservations=True)`.
5. THE SYSTEM SHALL seguir haciendo **un solo** `commit`, con la escritura de la tarea, la
   transición y la fila de auditoría dentro de él.

### R4 — La reunión de la evidencia se testea en aislamiento con fakes

**As a** desarrollador, **I want** un test directo y sin base de datos sobre el ensamblado de la
evidencia, **so that** la señal que abrió esta entrada quede efectivamente pagada donde se puede
pagar.

Acceptance criteria:

1. THE SYSTEM SHALL incluir un test del gatherer construido **sólo con fakes** de sus cuatro
   puertos, sin sesión de base de datos y sin `httpx`, siguiendo el precedente de
   `backend/tests/cleaning/test_photo_upload_use_case.py`.
2. THE SYSTEM SHALL cubrir con ese test el **camino positivo** —evidencia completa y bien
   poblada— que hoy no tiene cobertura con fakes en ningún caso de uso del ciclo de vida.
3. THE SYSTEM SHALL cubrir explícitamente que se leen los tipos de foto **requeridos** y no todos
   los declarados: una plantilla con un `photo_type` `required: false` SHALL producir un
   `required_photo_types` que no lo contenga.
4. THE SYSTEM SHALL cubrir que una plantilla ausente produce `ChecklistTemplateNotFoundError`.
5. THE SYSTEM SHALL cubrir que los cuatro puertos se consultan con el `tenant_id` recibido,
   incluida la consulta de incidencias, que se hace por `task.property_id`.

## Out of scope

- **Adelgazar `_TaskLifecycleBase`.** Sus siete colaboradores los usan de verdad `_load_task`,
  `_transition`, la auditoría y el commit, y tocarlos afecta a los seis casos de uso del ciclo de
  vida a la vez. Es un change distinto y bastante mayor que este (tamaño S); si se quiere, merece
  su propia entrada de roadmap tras ver cómo queda el cierre.
- **Un test con fakes del cierre completo** (`CompleteCleaningTaskUseCase.execute` de punta a
  punta). Seguiría costando ~8 dobles por lo anterior, y el camino positivo del cierre ya está
  cubierto por integración en `test_tasks_api.py`. R4 paga la parte que se abarata de verdad.
- **Extraer gatherers equivalentes para Accept/Start/Reject/Validate.** Ninguno tiene lecturas
  propias que extraer: sus colaboradores son los de la base.
- **Cambiar el contrato HTTP, los códigos de error o el orden de las cláusulas.** R3 lo prohíbe
  explícitamente; cualquier deriva ahí es un fallo del change, no una mejora.
- **Migración de Alembic.** No hay cambio de esquema.
- **`ai_validation_result`** sigue sin escribirse: depende de `MockAIAdapter`, que llega con
  `messaging-ai`.

## Affected specs

- [`sdd/specs/cleaning.md`](../../specs/cleaning.md) — la cláusula de *Cierre y validación* que hoy
  dice «El caso de uso solo reúne la evidencia» pasa a nombrar al gatherer como quien la reúne (la
  frase sobre dónde se aplican las tres cláusulas no cambia: sigue siendo la entidad), y la sección
  *Key files* recoge el colaborador nuevo.

Ninguna otra spec cambia: no hay contrato HTTP nuevo
([`api-contract.md`](../../specs/api-contract.md) intacta por R3.3) ni cambio de almacenamiento
([`file-storage.md`](../../specs/file-storage.md) intacta).
