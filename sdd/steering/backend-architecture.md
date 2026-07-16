---
applies_to: ["backend/**"]
---

# Backend architecture — DDD + Clean/Hexagonal + SOLID

Amplía `backend.md` con las reglas de diseño dentro de cada dominio y ejemplos concretos. Vinculante para cualquier módulo nuevo bajo `backend/app/<dominio>/`.

**No son dos arquitecturas distintas.** `architecture.md` habla de "hexagonal" a nivel de sistema (puertos definidos por el core, adapters en el borde); este documento da nombres de capa más explícitos (`domain`/`application`/`infrastructure`/`api`) al estilo Clean Architecture. Es el mismo patrón — puertos/adapters + regla de dependencia hacia el centro — con vocabulario distinto. No hay que elegir entre uno u otro.

## Regla de dependencia (la que manda sobre todas las demás)

```
api/  →  application/  →  domain/  ←  infrastructure/
```

Las flechas son de dependencia (import), no de llamada. **`domain/` no importa nada de `api/`, `application/` ni `infrastructure/`** — ni FastAPI, ni SQLAlchemy, ni Pydantic. Es Python puro. Todo lo demás depende de `domain/`, nunca al revés. `infrastructure/` **implementa** interfaces definidas en `domain/`, no las define.

Esto es Dependency Inversion (la D de SOLID) aplicado a rajatabla: si `domain/` necesita persistencia, define el puerto (`CleaningTaskRepository` como `Protocol`/ABC) — `infrastructure/` aporta el adaptador (`SqlAlchemyCleaningTaskRepository`).

**Cómo se verifica:** un `import` de `sqlalchemy`, `fastapi` o `pydantic` dentro de `backend/app/<dominio>/domain/` es un error de diseño, no un estilo — recházalo en review igual que un test que falla.

## Las 4 capas, con su responsabilidad exacta

| Capa | Contiene | No contiene |
|---|---|---|
| `domain/` | Entidades/agregados, value objects, servicios de dominio, eventos de dominio, **interfaces** de repositorio/adapter (puertos) | SQL, HTTP, Pydantic, lógica de orquestación entre agregados distintos |
| `application/` | Casos de uso (un caso de uso = una operación de negocio completa) — orquestan entidades + puertos | Reglas de negocio propias (si hay una regla, pertenece a `domain/`), acceso a infra directo |
| `infrastructure/` | Adaptadores que implementan los puertos de `domain/`: repos SQLAlchemy, clientes de APIs externas | Lógica de negocio |
| `api/` | Routers FastAPI (finos) + esquemas Pydantic (DTOs de request/response) | Lógica de negocio, acceso a `infrastructure/` directo — siempre a través de un caso de uso |

## DDD: bloques de construcción, con ejemplo real del dominio `cleaning`

**Entidad/Agregado** — tiene identidad (`id`), encapsula sus invariantes, se muta solo a través de sus propios métodos (nunca setters públicos arbitrarios):

```python
# backend/app/cleaning/domain/entities.py
class CleaningTask:
    def __init__(self, id: UUID, property_id: UUID, checklist: list[ChecklistItem]):
        self.id = id
        self.property_id = property_id
        self._checklist = checklist
        self._status = CleaningStatus.PENDING

    def complete(self) -> None:
        if not all(item.done for item in self._checklist):
            raise ChecklistIncompleteError(self.id)
        self._status = CleaningStatus.COMPLETED
```

`complete()` es el único sitio donde `_status` cambia — la invariante ("no completar con checklist a medias") vive aquí, no en el router ni en el caso de uso.

**Value Object** — sin identidad propia, definido por su valor, inmutable:

```python
@dataclass(frozen=True)
class ChecklistItem:
    label: str
    done: bool
```

**Servicio de dominio** — lógica que no pertenece a una sola entidad. `PropertyStateMachine` (ver `architecture.md`) es el ejemplo canónico del proyecto: coordina transiciones entre agregados `Property`, no vive dentro de `Property` porque conoce reglas que involucran reservas, limpiezas e incidencias a la vez.

**Puerto (interfaz de repositorio)** — vive en `domain/`, habla en términos de entidades de dominio, nunca de modelos ORM:

```python
# backend/app/cleaning/domain/repositories.py
class CleaningTaskRepository(Protocol):
    async def get(self, task_id: UUID) -> CleaningTask: ...
    async def save(self, task: CleaningTask) -> None: ...
```

**Evento de dominio** — una entidad completa una acción relevante → genera `TimelineEvent` (ver `architecture.md`: "Timeline inmutable... toda acción relevante lo genera"). El caso de uso, no la entidad, es quien decide persistir el evento — la entidad solo expone que ocurrió (p. ej. devolviendo el nuevo estado o lanzando el evento como valor de retorno de `complete()`).

## Caso de uso — orquestación, no reglas de negocio

```python
# backend/app/cleaning/application/use_cases.py
class CompleteCleaningTaskUseCase:
    def __init__(self, tasks: CleaningTaskRepository, timeline: TimelineRepository):
        self._tasks = tasks
        self._timeline = timeline

    async def execute(self, task_id: UUID) -> CleaningTask:
        task = await self._tasks.get(task_id)
        task.complete()                        # la regla vive en la entidad
        await self._tasks.save(task)
        await self._timeline.record(CleaningCompletedEvent(task.id))
        return task
```

Si este caso de uso empieza a tener `if`s sobre reglas de negocio (no sobre flujo), esa lógica se ha filtrado desde `domain/` — muévela de vuelta.

El router (`api/`) mapea Pydantic → parámetros del caso de uso → Pydantic de respuesta, y nada más:

```python
# backend/app/cleaning/api/router.py
@router.post("/{task_id}/complete", response_model=CleaningTaskOut)
async def complete_task(task_id: UUID, use_case: CompleteCleaningTaskUseCase = Depends(...)):
    task = await use_case.execute(task_id)
    return CleaningTaskOut.from_domain(task)
```

## SOLID, mapeado a decisiones que ya existen en este proyecto

- **S — Single Responsibility**: un router no valida reglas de negocio (ya en `backend.md`: "La lógica nunca vive en el router"); una entidad de dominio no sabe serializarse a JSON.
- **O — Open/Closed**: el patrón adapter ya obligatorio para todo sistema externo (`architecture.md`: "Todo sistema externo detrás de adapter") es Open/Closed en la práctica — un `OctorateAdapter` nuevo no toca `domain/` ni `application/`, solo implementa el puerto `PMSAdapter`.
- **L — Liskov Substitution**: `MockPMSAdapter` y el adapter real deben ser 100% intercambiables — mismas excepciones, misma forma de retorno, mismas precondiciones. Si el mock oculta un caso que el real no soporta, el contrato del puerto está mal definido, no es un detalle del mock.
- **I — Interface Segregation**: puertos pequeños y por rol, no un `StorageAdapter` gigante con 15 métodos si un caso de uso solo necesita `get_signed_url`. Divide por consumidor real, no por "todo lo que StorageAdapter podría hacer".
- **D — Dependency Inversion**: la regla de dependencia de arriba. `application/` recibe los puertos por constructor (inyectados vía `Depends` de FastAPI), nunca instancia un adapter de `infrastructure/` directamente.

## Estructura de ficheros por dominio

```
backend/app/cleaning/
  domain/
    entities.py          # CleaningTask, value objects
    repositories.py       # puertos (Protocol/ABC)
    exceptions.py          # ChecklistIncompleteError, etc.
  application/
    use_cases.py           # ScheduleCleaningTaskUseCase, CompleteCleaningTaskUseCase
  infrastructure/
    repositories.py         # SqlAlchemyCleaningTaskRepository
  api/
    router.py                # FastAPI router
    schemas.py                 # CleaningTaskOut, ScheduleCleaningRequest (Pydantic)
```

## Cuándo simplificar (evitar sobreingeniería)

El patrón puertos/adapters para sistemas externos **no es opcional** — lo exige el PRD (§3.3: "todo sistema externo detrás de adapter"), no es ceremonia añadida. Lo que sí es opcional es la **riqueza táctica de DDD** (value objects, eventos de dominio, invariantes elaboradas) dentro de `domain/`: aplícala solo donde hay una regla de negocio real que proteger.

- **Dominio con invariante real** (state machine, checklist de limpieza, guardrails de pricing, tenant isolation): entidad completa con métodos que protegen la regla, como `CleaningTask.complete()` arriba.
- **Dominio sin invariante real** (p. ej. `NotificationLog`, `AuditLog` — básicamente una tabla con lectura/escritura, sin reglas): una entidad puede ser un `dataclass` simple sin métodos, y el repositorio no necesita nada más que get/save. No fuerces value objects ni eventos de dominio donde no hay nada que encapsular.

Lo que **sí** se mantiene igual en todos los dominios, con o sin invariantes: la carpeta `domain/application/infrastructure/api/` y la regla de dependencia. La estructura uniforme es barata y ayuda a que un agente no confunda las convenciones entre módulos; la ceremonia táctica (value objects/eventos) es lo que se dosifica según haga falta.

## Don'ts

- No entidades con setters públicos arbitrarios — mutación solo vía métodos que protegen invariantes (`complete()`, no `task.status = "completed"`).
- No `import` de `sqlalchemy`/`fastapi`/`pydantic` dentro de `domain/`.
- No lógica de negocio en `application/` — si hay una regla (no solo un paso de orquestación), pertenece a `domain/`.
- No repositorio "Dios" con métodos de varios agregados — un repositorio por agregado raíz.
- No devolver modelos ORM de `infrastructure/` hacia `application/`/`api/` — los adapters traducen a entidades de dominio antes de devolver.

## Cómo se testea cada capa (ver también `testing.md`)

- `domain/`: unit tests puros, sin mocks — son objetos Python normales, se instancian y se llama a sus métodos.
- `application/`: unit tests con **fakes** en memoria de los puertos (no la DB real, no mocks de SQLAlchemy).
- `infrastructure/`: integration tests contra Postgres/Redis reales (o su contenedor local vía `local-environment`).
