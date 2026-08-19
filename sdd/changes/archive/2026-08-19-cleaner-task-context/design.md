# Design: cleaner-task-context

## Context

El módulo de limpieza ya tiene la mitad del acotamiento que este change necesita:
`CleaningActor.restrict_to_cleaner_id` (`backend/app/cleaning/application/use_cases.py:504-511`)
deriva del **token** el id de la limpiadora y `GetCleaningTaskUseCase`
(`use_cases.py:1054-1067`) lo aplica devolviendo `CleaningTaskNotFoundError` — que
`cleaning/api/errors.py:44` mapea a `404 NOT_FOUND` — tanto para una tarea de otro tenant como
para una de otra limpiadora. La ruta hermana `GET /cleaning-tasks/{task_id}/photos`
(`tasks_router.py:493-519`) es el patrón exacto de sub-recurso que R4 pide: `ReadDep` sobre
`READ_CLEANING_TASKS`, un `responses=` propio que declara su 404 y una `description` que dice
que el conjunto de filas sale del rol del token.

Lo que falta es la proyección. `Property` (`properties/domain/entities.py:14-53`) tiene los
nueve campos de R1 y también los tres sumideros que R1.4 prohíbe; `Reservation`
(`reservations/domain/entities.py:84-113`) tiene `check_in_time`/`check_out_time` nullable y
los importes que R2.5 prohíbe. Y el fallback a los valores por defecto de la propiedad, con su
política de horario de verano, ya existe una sola vez:
`effective_bounds(property, reservation)` (`properties/domain/clock_triggers.py:59-68`), cuyo
docstring de módulo dice que su aritmética DST «no debe reimplementarse nunca».

**Hallazgo que cambia el alcance de R2**: los dos instantes que R2 pide ya se calculan hoy —
`_effective_checkout` y `_next_checkin` (`cleaning/application/use_cases.py:1653-1704`) — y
`process_checkouts` los guarda en `CleaningTask.scheduled_start`/`scheduled_end`
(`use_cases.py:259-272`), que `CleaningTaskResponse` ya devuelve a la limpiadora
(`api/schemas.py:160-161`). Pero son una **instantánea del momento de creación** y
`_next_checkin` solo mira las reservas que el job cargó, cuya ventana es
`candidate_window(now)` = `[now-30d, now+2d]` (`clock_triggers.py:41-56`): una llegada a cinco
días vista deja `scheduled_end` en `None` **para siempre**, y una tarea creada a mano toma los
dos valores del cuerpo de la petición. R2 pide la respuesta viva, no la instantánea — ver D4.

Dos precedentes de arquitectura tiran en direcciones opuestas y hay que elegir:
`guest-portal-api` D9 escribió un adaptador de proyección con su propio `SELECT` conjunto
(`guests/infrastructure/portal_repositories.py:211-299`), y `dashboard-api` D2 **rechazó** un
adaptador propio porque «sería el segundo sitio donde se escribe el scope de tenant»
(`dashboard/application/use_cases.py:1-19`). Ver D2.

## Decisions

### D1 — Un sub-recurso `GET /api/v1/cleaning-tasks/{task_id}/context`, no una ampliación de `CleaningTaskResponse`

**Chosen:** ruta nueva en `cleaning/api/tasks_router.py`, con su propio `response_model`.
Es la primera de las dos decisiones que el roadmap marca como «no cosmética». `CleaningTaskResponse`
la devuelven nueve rutas —incluidas `POST`, `PATCH` y las cinco de ciclo de vida—, así que
ampliarla haría que cada escritura pagase dos consultas más por unos datos que nadie le pidió, y
metería la proyección detrás de las puertas `MANAGE_` y `EXECUTE_`, donde ningún requisito la
quiere. El router ya tiene dos sub-recursos de lectura (`/{task_id}/checklist`,
`/{task_id}/photos`) con la forma exacta que R3 y R4 describen.

Rejected: ampliar `CleaningTaskResponse` — acopla nueve respuestas y rompe el tipo generado de
todos sus consumidores actuales para servir a uno.
Rejected: incrustar la proyección en `CleaningTaskPageResponse` — es la ASSUMPTION 2 del
proposal, y sigue abierta (OQ2).
Rejected: un árbol `/cleaner/...` — una segunda URL para el mismo agregado, y URLs con forma de
rol, que esta API no tiene en ninguna parte.

### D2 — Componer los repositorios existentes en un caso de uso; ningún `SELECT` nuevo, ningún adaptador de proyección

**Chosen:** `GetCleaningTaskContextUseCase` en `cleaning/application/use_cases.py`, con
`CleaningTaskRepository`, `PropertyRepository` y `ReservationRepository` — los tres ya
inyectados en ese módulo (`use_cases.py:524-528`). Manda `dashboard-api` D2: un adaptador propio
sería el segundo sitio donde se escribe el scope de tenant. Y aquí la composición además es
**más segura** que el `JOIN`: cada `get` lleva su `tenant_id` explícito, así que una tarea que
apunte a la propiedad de otro tenant devuelve `None` → 404, que es exactamente la fila que el
panel de seguridad de `guest-portal-api` tuvo que cerrar con un segundo `WHERE` dentro de su
join (`portal_repositories.py:255-269`). Coste: 3 sentencias en la lectura de **una** tarea, no
en un listado.

Rejected: un `CleaningTaskContextReader` con un `SELECT` conjunto (patrón `guest-portal-api` D9)
— una consulta en vez de tres, pero un segundo sitio escribiendo el scope de tenant; allí lo
justificaba una sesión anónima **sin marcar**, y esta ruta no la tiene.

### D3 — La proyección es un dataclass congelado del dominio, espejado campo a campo en el contrato

**Chosen:** `CleaningTaskContext` (frozen dataclass, sin pydantic ni sqlalchemy) en
`cleaning/domain/read_models.py`, y `CleaningTaskContextResponse` en `cleaning/api/schemas.py`
con `model_config = ConfigDict(from_attributes=True)`, espejo campo a campo. Así R1.4 y R2.5 son
**estructurales**: un campo que no está en el dataclass no tiene dónde aterrizar, y ni `Property`
ni `Reservation` se serializan nunca. Es la construcción de `StayInfo`/`StayInfoResponse`
(`guests/api/portal_schemas.py:150-180`) y de `dashboard/domain/read_models.py:1-26`, con su test
que fija el conjunto de campos (`tests/guests/test_portal_ports.py`).

Rejected: construir el modelo pydantic desde `Property` en el router — el router pasaría a ser
dueño de la denylist, y cada edición futura podría ensancharla sin que nada se pusiera en rojo.

Campos, y son todos (R1.1, R1.2, R2.1, R2.2):

| Campo | Tipo | Origen |
|---|---|---|
| `property_name` | `str` | `Property.name` |
| `property_internal_code` | `str` | `Property.internal_code` |
| `address_line1` | `str \| None` | `Property.address_line1` |
| `address_line2` | `str \| None` | `Property.address_line2` |
| `city` | `str \| None` | `Property.city` |
| `province` | `str \| None` | `Property.province` |
| `postal_code` | `str \| None` | `Property.postal_code` |
| `country` | `str` | `Property.country` |
| `timezone` | `str` | `Property.timezone` |
| `checkout_at` | `datetime \| None` | D5 |
| `next_checkin_deadline` | `datetime \| None` | D5 |

R1.3 (una dirección `NULL` viaja como `null`, no se omite la clave) sale del defecto de pydantic:
no hay `exclude_none` ni `response_model_exclude_none` en ningún sitio de `backend/app`. Es
comportamiento heredado, así que lleva su test propio en vez de darse por hecho.

### D4 — Los dos instantes se resuelven **en la lectura**, no se leen de `scheduled_start`/`scheduled_end`

**Chosen:** la proyección los calcula contra las reservas del momento. Es lo que R2 pide y lo
que la instantánea del job no puede dar: con el lookahead de 2 días de `candidate_window`, una
llegada a cinco días vista deja `scheduled_end` en `None` de forma permanente, y una tarea creada
por `POST /cleaning-tasks` toma los dos valores del cuerpo de la petición sin resolver nada.

Los dos pares **pueden discrepar, y significan cosas distintas**: `scheduled_start`/`scheduled_end`
son el **plan** de la tarea —lo que el planificador se comprometió a, y sobre lo que se
construyeron la asignación y el SLA—, y `checkout_at`/`next_checkin_deadline` son la respuesta
**de ahora**. Se llaman distinto en el contrato precisamente para que la discrepancia no se lea
como una contradicción, y la `description` de la ruta lo dice.

La respuesta **no** repite `scheduled_*`: el cliente ya tiene la tarea, que es de donde viene a
esta ruta.

Rejected: devolver `task.scheduled_start`/`scheduled_end` — gratis, pero falso justo en los casos
que R2.2 y R2.3 distinguen, y convertiría R2 en un no-op que sus propias palabras no describen.
Rejected: refrescar los valores guardados en la tarea al leer — una lectura que escribe, y movería
el ancla del SLA por debajo de la asignación ya notificada.

### D5 — Reutilizar `effective_bounds` y extraer la regla de `_next_checkin`; **no** reutilizar `_effective_checkout`

**Chosen:** tres piezas.

1. **`checkout_at`** = el `end` de `effective_bounds(property, reservation)` cuando la tarea
   referencia una reserva. Esa función es R2.1 al pie de la letra (`Reservation.check_out_time`
   con fallback a `Property.default_check_out_time`) más la política DST que
   `clock_triggers.py:23-26` prohíbe reimplementar. Devuelve un `datetime` **con zona** en el
   timezone de la propiedad, así que R2.4 (ISO 8601 con offset explícito) sale de la
   serialización por defecto de pydantic sin formateador propio, y el campo `timezone` de R1.2
   es lo que permite leer ese offset como un lugar.
2. **`next_checkin_deadline`** = la regla que hoy vive en `_next_checkin`
   (`use_cases.py:1669-1704`): salta la reserva actual, solo `CONFIRMED`, y el mínimo de las
   llegadas iguales o posteriores al ancla. Se **mueve** a `cleaning/domain/windows.py` como
   función pura junto con la resolución del checkout: un segundo llamante es el disparador
   clásico de la extracción, y el revisor de arquitectura de `cleaning` ya movió
   `resolve_auto_assignee` a `domain/` por esta misma razón (`use_cases.py:293-298`). Su firma
   cambia de `current: Reservation` a un id de exclusión opcional, porque la proyección no tiene
   «reserva actual» cuando `task.reservation_id` es `None` (D6); `process_checkouts` pasa
   `current.id` y su comportamiento no cambia.
3. **Las reservas candidatas** salen de `ReservationRepository.list_for_properties(tenant_id,
   [property_id], date_from, date_to)`, que ya existe y ya es solapamiento de estancia. La
   ventana, en D10.

`_effective_checkout` (`use_cases.py:1653-1666`) **no** se reutiliza, y esto no es un descuido:
degrada a `now` cuando los límites no se materializan, que es correcto para una pista de
planificación e **inaceptable para una hora que se muestra** — sería una hora de salida
inventada en la pantalla de la limpiadora. La proyección llama a `effective_bounds` directamente
y devuelve `null` cuando lanza `IncompatibleTransitionContextError`.

Consecuencia de heredar el filtro `CONFIRMED`, dicha explícitamente: una llegada `PENDING` no
impone deadline y `next_checkin_deadline` sale `null`. No se diverge — dos políticas de
elegibilidad en el mismo repositorio es peor que una discutible.

Rejected: una segunda copia del fallback y de la aritmética DST en la proyección — prohibido por
nombre en el docstring de `clock_triggers.py`.
Rejected: dejar `_next_checkin` donde está y llamarla desde el nuevo caso de uso — funciona, pero
consolida una regla de negocio en `application/`, que `steering/backend-architecture.md` §Don'ts
pone en `domain/`.

### D6 — `task.reservation_id is None` → `checkout_at: null`, y el ancla del deadline pasa a ser `now`

**Chosen:** la ASSUMPTION 1 del proposal queda **verificada, no asumida**: `process_checkouts`
crea toda tarea con `reservation_id=reservation.id` y esa reserva *es* la de cuyo checkout salió
la limpieza (`use_cases.py:259-272`), así que la resolución alternativa por propiedad y fecha que
la assumption ofrecía no hace falta y R2 no se ajusta. El caso `None` es real pero es solo el
`POST /cleaning-tasks` manual sin reserva: no hay huésped saliente, así que `checkout_at` es
`null` — la respuesta honesta, ni un error ni una fecha inventada. Con el ancla del checkout
ausente, R2.2 se resuelve desde `now`.

Rejected: 409/422 para una tarea sin reserva — una tarea manual es una tarea legítima, y R2.3 ya
eligió `null` como la forma de decir «no hay».

**Addendum (2026-08-18, aprobado por Jose en el panel de la sección 2 de `/sdd:run`): un
`reservation_id` informado que NO resuelve dentro del tenant degrada igual, con log.** El caso lo
levantó el revisor de arquitectura: esta decisión razonaba solo sobre `reservation_id is None`, y
el código se encontró con el tercer estado —puntero colgado por borrado, o a otro tenant— que
ninguna cláusula cubría. Se resuelve como el `None`: `checkout_at: null`, ancla en `now`, y un
`logger.warning` con tenant/tarea/reserva.

Y **no** como el puntero de propiedad que no resuelve, que sí es `404` (D2), porque los dos no
pesan lo mismo: la propiedad es de donde salen nueve de los once campos —sin ella no hay respuesta
que dar—, mientras que la reserva solo alimenta `checkout_at`. Negar el contexto entero por un
puntero colgado le quitaría a la limpiadora la dirección, que es la mitad de lo que PRD §11 pide
de esta ruta. El panel de seguridad lo cerró explícitamente: una reserva de otro tenant y una
inexistente producen el mismo `None`, así que la rama no es un oráculo de existencia y no se lee
ningún campo de la reserva no resuelta.

Rejected: `404` por simetría con D2 — consistente de forma, pero cobra el precio en la pantalla
equivocada.

### D7 — Ningún permiso nuevo: `READ_CLEANING_TASKS` en la puerta, `restrict_to_cleaner_id` en la fila

**Chosen:** `ReadDep` (`tasks_router.py:78`) y la comprobación que `GetCleaningTaskUseCase` ya
hace. R3 entero sale de piezas existentes: R3.4 (403 antes de tocar la BD) del `require(...)`,
que FastAPI resuelve antes del handler; R3.1/R3.2/R3.5 de `restrict_to_cleaner_id`, que es `None`
para `PROPERTY_MANAGER` y `TENANT_OWNER`; R3.3 y R4.2 de `CleaningTaskNotFoundError → 404
NOT_FOUND`, ya en la tabla de `errors.py:44` — no hace falta ninguna excepción nueva ni ninguna
fila nueva.

**Consecuencia para las Affected specs del proposal**: `sdd/specs/auth-tenancy.md` **no cambia**.
El proposal la listaba con la condición «si el design introduce un permiso nuevo», y la condición
es falsa. La tabla de política de `policy.py` no se toca.

Rejected: un `READ_OWN_TASK_CONTEXT` nuevo — lo tendrían exactamente los roles que ya tienen
`READ_CLEANING_TASKS` y acotaría exactamente las filas que ya están acotadas: una fila más en la
tabla y ninguna frontera nueva.
Rejected: dar `READ_PROPERTIES`/`READ_RESERVATIONS` a `CLEANER` — descartado en el *Why* del
proposal.

### D8 — La divergencia con `dashboard-api` D10, dicha en voz alta

**Chosen:** divergir, y acotar por qué esto no es el agujero que D10 cierra. D10 —«agregar no
puede conceder»— omite cada bloque cuando el rol del llamante no tiene el permiso que guarda su
**fuente** (`dashboard/application/use_cases.py:14-18`); leído literalmente, una `CLEANER` no
recibiría bloque de propiedad, que es justo lo que este change existe para dar.

La diferencia es de forma, no de grado. El sujeto de D10 es un **agregado sobre una raíz que el
llamante ya puede leer entera**: `GET /properties/{id}/dashboard` entrega la propiedad, sus
reservas, su dinero y sus huéspedes, así que la unión de cuatro permisos *es* la respuesta. Esta
proyección no es una unión: son nueve campos de `Property` y dos instantes derivados, sin
importes, sin huésped, sin notas, sin wifi, sin códigos de acceso y sin ids externos — y su
conjunto de **filas** es más estrecho que el que `READ_PROPERTIES` daría: la propiedad de una
tarea, y solo mientras esa tarea esté asignada al llamante. Ninguna de las dos superficies
guardadas se puede reconstruir desde aquí.

La regla que sobrevive, y que es lo que hay que citar la próxima vez: **una proyección puede
estrechar, nunca unir**. El change que quiera añadir aquí un campo que un permiso guarda *como
un todo* —un importe de reserva, el nombre de un huésped— no lo añade aquí: pasa por D10.

Rejected: aplicar D10 al pie de la letra y omitir el bloque para `CLEANER` — deja el change sin
objeto y `cleaner-app` sin implementar, que es de donde salió esta entrada.

### D9 — La decisión de steering aparcada **no se dispara**, y éste es el «por qué no» explícito

**Chosen:** no tocarla. `sdd/roadmap/cleaner-app.md` aparca `access_records.notes` junto con
`properties.access_notes`/`cleaning_notes`/`emergency_notes` —las cuatro auditables pero no
denylisted, con la disciplina en el caso de uso (`properties-crud` design D7)— y exige que la
decisión «cubra las cuatro columnas a la vez **o diga explícitamente por qué no**». Éste es el
por qué no: lo que dispara esa decisión es que **el conjunto de lectores de una columna crezca a
un rol que hoy no la tiene**, y esta proyección no lee ninguna de las cuatro. `Property` no se
serializa (D3), así que no existe ruta por la que ninguna llegue a la respuesta. La decisión
sigue aparcada, entera, en `cleaner-app`, que es quien muestra accesos.

Y R1.4 no deja un hueco en la proyección: PRD §11 enumera «propiedades asignadas, dirección,
hora programada, info de checkout previo, deadline del próximo check-in, checklist, fotos,
reportar incidencia, finalizar». **No pide instrucciones de limpieza.** Excluir `cleaning_notes`
no es quedarse corto; es que nadie lo pidió.

Rejected: incluir `cleaning_notes` porque «una limpiadora necesita las instrucciones de limpieza»
— dispararía la decisión aparcada por un campo que ningún requisito pide, en el change que no es
su casa.

### D10 — El horizonte de la próxima llegada, como ASSUMPTION declarada

**Chosen:** **14 días** desde el ancla (el checkout, o `now` según D6).
`list_for_properties` necesita una ventana y hay que elegirla. El +2 días de `candidate_window`
es la del planificador y es exactamente lo que hace poco fiable el `scheduled_end` guardado:
reutilizarlo aquí reproduciría el defecto que D4 existe para arreglar. `dashboard-api` eligió 90
días para «reserva actual o próxima» con una ASSUMPTION de esta misma clase
(`dashboard/application/use_cases.py:65-70`).

14 días porque el deadline existe para que una limpiadora ordene su jornada: una llegada a dos
semanas no impone deadline sobre la limpieza de hoy, y un horizonte más corto que el del
dashboard mantiene el coste de una ventana amplia fuera de una lectura por tarea.

**Consecuencia que hay que escribir en el contrato**: el `null` de R2.3 pasa a significar «no
hay llegada `CONFIRMED` en los 14 días siguientes al checkout», y eso va en la `description` de
la operación, no solo aquí. Es la decisión más discutible del design → **OQ1**.

Rejected: sin límite — una consulta sin techo en una ruta por petición.
Rejected: +2 días reutilizando `candidate_window` — reproduce el defecto.

### D11 — Los dos artefactos del contrato, y el 404 declarado en la ruta

**Chosen:** `make openapi` regenera `backend/openapi.json` y **además** se regenera
`frontend/lib/api/generated/openapi.d.ts`; los dos se commitean en el mismo PR
(`steering/documentation.md` — son las dos mitades del mismo puente, y los workflows
`api-contract` y `frontend-api-contract` comprueban cada una). En un worktree enlazado el
comando documentado del frontend no corre; el sustituto de cuatro líneas está en
`sdd/project.md` §Worktree bootstrap.

La ruta declara su propio `responses={404: ErrorEnvelope}` siguiendo
`_PHOTO_LISTING_RESPONSES` (`tasks_router.py:482-490`), que es la vía que `app/core/openapi.py`
D8 deja abierta per-endpoint. R4.3 va en la `description`, con la redacción que la ruta de fotos
ya usa: el conjunto de tareas visibles sale del rol persistido del token y ningún parámetro lo
ensancha.

## Changes by area

| Area | Files | Change |
|---|---|---|
| cleaning · domain | `backend/app/cleaning/domain/read_models.py` **(nuevo)** | `CleaningTaskContext`, frozen dataclass de 11 campos (D3) |
| cleaning · domain | `backend/app/cleaning/domain/windows.py` **(nuevo)** | `resolve_checkout` y `next_arrival_after`, puras; la segunda es `_next_checkin` movida con id de exclusión opcional (D5) |
| cleaning · application | `backend/app/cleaning/application/use_cases.py` | `GetCleaningTaskContextUseCase` (D2); `_next_checkin`/`_effective_checkout` pasan a delegar en `domain/windows.py`; `process_checkouts` pasa `current.id` |
| cleaning · api | `backend/app/cleaning/api/schemas.py` | `CleaningTaskContextResponse`, espejo con `from_attributes=True` (D3) |
| cleaning · api | `backend/app/cleaning/api/tasks_router.py` | `GET /{task_id}/context` con `ReadDep`, `_CONTEXT_RESPONSES` y la `description` de R4.3 (D1, D11) |
| cleaning · api | `backend/app/cleaning/api/dependencies.py` | `get_cleaning_task_context_use_case`, con los tres repositorios ya usados en el módulo |
| contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados y commiteados juntos (D11) |
| docs | `docs/cleaning.md` | la operación nueva y qué significa `null` en cada uno de los dos instantes |

Sin migración, sin columna nueva, sin `.env`, sin permiso nuevo, sin fila nueva en la tabla de
errores, sin i18n (no hay UI en alcance) y sin escritor nuevo de ningún sumidero de la regla 11.

## Data & interfaces

```
GET /api/v1/cleaning-tasks/{task_id}/context     → 200 CleaningTaskContextResponse
                                                   403 (sin READ_CLEANING_TASKS)
                                                   404 NOT_FOUND (desconocida / otro tenant /
                                                       otra limpiadora — indistinguibles)
```

```python
# cleaning/domain/read_models.py
@dataclass(frozen=True)
class CleaningTaskContext:
    property_name: str
    property_internal_code: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    timezone: str
    checkout_at: datetime | None            # con zona → ISO 8601 con offset (R2.4)
    next_checkin_deadline: datetime | None

# cleaning/domain/windows.py
def resolve_checkout(property: Property, reservation: Reservation) -> datetime | None: ...
def next_arrival_after(
    property: Property,
    candidates: Sequence[Reservation],
    anchor: datetime,
    *,
    exclude_id: uuid.UUID | None = None,
) -> datetime | None: ...
```

Esquema de BD: sin cambios. Consultas por petición: **hasta 4**, sobre una sola tarea —
`tasks.get`, `properties.get`, `reservations.get` y `reservations.list_for_properties`. Son **3**
cuando la tarea no tiene reserva (D6), porque entonces no hay `reservations.get` que hacer, y
menos aún en los caminos que terminan en `404`. Una redacción anterior decía «= 4» a secas y era
falsa justo en el caso que D6 existe para describir.

## Risks & mitigations

- **La discrepancia entre `scheduled_*` y los dos campos nuevos se lee como un bug.** Es la
  consecuencia deliberada de D4. Mitigación: nombres distintos en el contrato, la `description`
  de la operación explicando cuál es el plan y cuál es la respuesta de ahora, y `docs/cleaning.md`
  diciendo lo mismo.
- **Mover `_next_checkin` a `domain/windows.py` toca `process_checkouts`**, que es el camino que
  crea toda tarea automática. Mitigación: es un movimiento sin cambio de comportamiento y su
  suite existente es el arnés; los tests de `process_checkouts` corren sin tocarse, y si hay que
  tocarlos es que el movimiento cambió algo.
- **El horizonte de 14 días hace que `null` sea ambiguo** entre «no hay llegada» y «hay una más
  allá del horizonte». Mitigación: el contrato lo dice con esas palabras (D10). Si la ambigüedad
  molesta, la salida es un campo aparte y no un horizonte infinito.
- **La proyección crece con el tiempo** hasta convertirse en el volcado que este change rechaza.
  Mitigación: el test que fija el conjunto de campos de `CleaningTaskContext` (patrón
  `tests/guests/test_portal_ports.py`), que obliga a que añadir un campo sea un cambio
  deliberado; y la regla de D8 —estrechar sí, unir no— como criterio para revisarlo.
- **Aislamiento**: además del test de tenant obligatorio (`security.md` regla 1), hace falta el
  caso de la tarea que apunta a la propiedad de otro tenant, que es la fila que el panel de
  `guest-portal-api` construyó a mano. Aquí D2 lo cierra por composición, pero eso hay que
  demostrarlo, no afirmarlo.

## Open questions

Ninguna abierta. Las dos que este design planteó las resolvió Jose en el gate de `/sdd:design`
el 2026-08-18, y quedan registradas aquí porque son elecciones y no derivaciones:

**OQ1 — El horizonte de la próxima llegada (D10) → 14 días.** `null` significa por tanto
«ninguna llegada `CONFIRMED` en los 14 días siguientes al checkout», y eso va en la
`description` de la operación y en `docs/cleaning.md`, no solo aquí. Descartadas: 7 días (más
ajustado a «ordenar mi jornada», pero más `null`), 30 días (menos `null`, y devuelve como
deadline cosas que no aprietan hoy) y los 90 del dashboard (coherencia entre módulos a cambio de
la ventana más amplia en una ruta por petición).

**OQ2 — La ASSUMPTION 2 del proposal: el listado → fuera de alcance.** `/cleaner` pedirá el
contexto por tarea; lo decide `cleaner-app` con una pantalla real delante. Con 2 viviendas en el
MVP, N es 1-3, y una proyección incrustada en `CleaningTaskPageResponse` es exactamente la
ampliación de respuesta que D1 rechaza. Descartado: incrustar nombre y dirección en cada
elemento del listado — habría entrado como requisito de este change y contradiciendo D1 para las
nueve rutas que devuelven esa respuesta.
