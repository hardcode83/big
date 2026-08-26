# Design: tech-incident-context

## Context

El módulo `maintenance` ya entrega el ciclo completo de la incidencia: doce rutas en
`backend/app/maintenance/api/{incidents_router,approvals_router}.py`, los casos de uso en
`application/use_cases.py` (68 KB, un mixin `_IncidentTransitionMixin` que carga la incidencia
acotada por tenant y por técnico asignado) y la entidad en `domain/entities.py` con su tabla de
transiciones. `IncidentActor.restrict_to_technician_id` (`use_cases.py:378`) es el acotamiento por
fila que este change reusa: devuelve el id del llamante cuando su rol persistido es `TECHNICIAN` y
`None` para los demás, y no existe parámetro de petición que lo ensanche.

El precedente exacto de la proyección es `cleaner-task-context`:
`backend/app/cleaning/domain/read_models.py` (dataclass congelado de once campos, sin pydantic ni
SQLAlchemy — `tests/test_layering.py` lo obliga), `GetCleaningTaskContextUseCase` (composición de
repositorios ya inyectados, cada `get` con su `tenant_id` explícito),
`CleaningTaskContextResponse` (espejo campo a campo con `from_attributes=True`) y
`GET /cleaning-tasks/{task_id}/context` con su `_CONTEXT_RESPONSES`. Este change lo calca con dos
lecturas en vez de cuatro.

Lo que hace falta que no existe: `Incident` no tiene columna para la nota del manager (PRD §7.13 no
la declara), y `properties.access_notes` —hoy en `Property`, en `PropertyResponse` y por tanto
también en el listado paginado— no tiene fila en la tabla de sumideros de la regla 11 de
`sdd/steering/security.md`. `_flow_kwargs` de `api/dependencies.py` ya inyecta
`SqlAlchemyPropertyRepository`, así que no hay repositorio nuevo. La cabeza de Alembic es
`e7a3c419d82b` (`guest_portal_api`), doce migraciones en total.

## Premisas del proposal verificadas

El proposal afirma cosas sobre el código que este design tenía que comprobar antes de diseñar sobre
ellas. Todas se verificaron; una está **incompleta** y cambia la decisión D5.

| Afirmación | Verificación |
|---|---|
| `TECHNICIAN` tiene cinco permisos y ni `READ_PROPERTIES` ni `READ_RESERVATIONS` | ✅ `policy.py`: `UserRole.TECHNICIAN: _SELF_SERVICE \| _INCIDENT_EXECUTE` |
| `IncidentResponse` da `property_id` pelado | ✅ `api/schemas.py`, campos enumerados, sin atributo de `Property` |
| `IncidentPageResponse` no lleva contexto | ✅ es `list[IncidentResponse]` |
| No hay transición `reject` ni columna ETA | ✅ la tabla de `_TRANSITIONS` no la tiene; `maintenance` §Estado lo dice |
| No hay entidad ni ruta de fotos de incidencia | ✅ el único `photos_router.py` es de `cleaning` |
| `maintenance` R8 niega la ruta de creación | ✅ y la negativa es explícita en la spec |
| El andamio `frontend/app/(field)/tech/` existe | ✅ `page/layout/error.tsx` + `incidents/[id]/page.tsx`, los dos `RoutePlaceholder` |
| PRD §12 no pide la reserva | ✅ las once cosas de §12 no nombran importe, canal ni huésped |
| `properties.access_notes` no está en la tabla de sumideros | ✅ el censo son dieciocho columnas y ninguna de `properties` |
| `Incident` no tiene columna de nota | ✅ ni la entidad, ni `IncidentModel`, ni PRD §7.13 |

**La incompleta, y es la que mueve D5.** El proposal dice que exponer `access_notes` «a un rol que
hoy no la lee» es lo que dispara la decisión aparcada, con el subtexto de que hoy sólo la leen la
propietaria y el manager. Los lectores de rol son ésos dos (`_PROPERTY_READ` / `_PROPERTY_MANAGE`),
pero la columna **ya sale del sistema por una tercera vía y ante un público peor**: el portal del
huésped la devuelve verbatim como `arrival_notes` en `GET /api/v1/guest/info/{token}`
(`backend/app/guests/domain/portal_ports.py`, `StayInfo.arrival_notes`;
`infrastructure/portal_repositories.py` la selecciona), a un **portador anónimo de token**, decidido
en la OQ2 de `guest-portal-api` y mitigado con un aviso al operador en `docs/guest-portal.md`.

Es decir: el disparador que `sdd/roadmap/cleaner-app.md` describe —«que el conjunto de lectores de
una de esas columnas crezca a un rol que hoy no la tiene»— **ya se disparó una vez** y se resolvió
con documentación en vez de con una fila del censo. Eso no invalida R2, la refuerza: el censo lleva
un change de retraso, no cero. Y sí cambia qué forma vale la pena pagar, porque una forma cuyo
beneficio se evapora ante el lector que ya existe no es una forma, es una ceremonia (D5).

## Decisions

### D1 — Una proyección de solo lectura calcada de `cleaner-task-context`, sin permiso nuevo

**Chosen:** `GET /api/v1/incidents/{incident_id}/context` con `require(Permission.READ_INCIDENTS)`
en la puerta y el acotamiento por fila derivado del rol persistido dentro del caso de uso. La misma
anatomía en cinco ficheros que `cleaner-task-context`: dataclass congelado en `domain/read_models.py`
(nuevo), caso de uso en `application/use_cases.py`, esquema espejo en `api/schemas.py`, ruta en
`api/incidents_router.py`, builder en `api/dependencies.py`. R8 de `maintenance` pasa de doce rutas
a trece.

Por qué: la capacidad es la misma —decirle a un rol de campo a qué piso va sin concederle el CRUD
que guarda ese dato— y una segunda anatomía para el mismo problema es cómo se acaba con dos sitios
donde se escribe el acotamiento por fila. El precedente además ya pasó por su panel de seguridad.

Rejected: conceder `READ_PROPERTIES` a `TECHNICIAN` — abre el CRUD entero de propiedades, y sus
`cleaning_notes`, `emergency_notes` y la fila entera, para resolver un nombre y una dirección.
Rejected: un permiso `READ_INCIDENT_CONTEXT` propio — lo tendrían exactamente los roles que ya
tienen `READ_INCIDENTS` y acotaría exactamente las filas que ya están acotadas.
Rejected: embeber el contexto en `IncidentResponse` o en el listado — el proposal lo deja fuera de
alcance y `tech-app` lo decidirá con una pantalla delante.

### D2 — Composición de dos repositorios, no un `JOIN` ni un reader propio

**Chosen:** el caso de uso hace `incidents.get(tenant_id, incident_id)` y
`properties.get(tenant_id, incident.property_id)`. **Dos sentencias por petición**, cada una con su
`tenant_id` explícito. Los dos repositorios ya los inyecta `_flow_kwargs`, así que no hay puerto ni
adaptador nuevo.

Por qué: es la regla D2 de `dashboard-api` —un adaptador de proyección sería el segundo sitio donde
se escribe el scope de tenant— y aquí la composición además es **más estricta** que un `JOIN`:
`incidents.property_id` es una FK simple a `properties.id`, no compuesta con `tenant_id` (lo dice
`maintenance` R8 al justificar la precondición del alta genérica), así que la base de datos acepta
una incidencia del tenant A colgada de una propiedad del tenant B. Con composición esa fila resuelve
a `None` y se convierte en `404`; con un `JOIN` habría que acordarse de un segundo `WHERE`, que es
exactamente la fila que el panel de seguridad de `guest-portal-api` tuvo que cerrar a mano.

Rejected: un `SqlAlchemyIncidentContextReader` con un `select` conjunto — más rápido en una
sentencia, y a cambio un segundo sitio donde se escribe el aislamiento por tenant, sobre la lectura
de **una** incidencia.

### D3 — El acotamiento por fila se extrae a un único sitio en vez de escribirse por tercera vez

**Chosen:** extraer el par «cargar dentro del tenant + `404` si el técnico no es el asignado» a una
corrutina de módulo en `application/use_cases.py`, y hacer que la usen los **tres** llamantes:
`_IncidentTransitionMixin._load_incident`, `GetIncidentUseCase.execute` y el caso de uso nuevo.
Firma orientativa:

```python
async def _load_incident_in_scope(
    incidents: IncidentRepository,
    tenant_id: uuid.UUID,
    incident_id: uuid.UUID,
    actor: IncidentActor,
) -> Incident: ...
```

Por qué: hoy esas tres líneas están escritas **dos** veces (el mixin y `GetIncidentUseCase`, que no
lo hereda porque sólo toma `incidents`), y añadir la proyección haría la tercera. La regla R4.4 exige
que el `404` sea idéntico en cuatro casos, y una regla replicada en tres sitios es la que divergirá.
La spec de `maintenance` ya nombra este defecto en su §Estado y le pone candidato de roadmap
(`tenant-scoping-enumeration-guard`); esto no lo cierra, pero baja de tres copias a una en el único
momento en que el diff es de tres líneas.

Rejected: escribir la tercera copia, como hizo `cleaner-task-context` — allí era la segunda y en otro
módulo; aquí serían tres en el mismo fichero.
Rejected: hacer que el caso de uso nuevo llame a `GetIncidentUseCase` — acopla un caso de uso a otro
para reusar tres líneas, y `application/` no compone casos de uso en este repo.

### D4 — Once campos, dataclass congelado, y los nombres de las columnas

**Chosen:** `IncidentContext`, dataclass `frozen` en
`backend/app/maintenance/domain/read_models.py` (fichero nuevo), Python puro:

```python
@dataclass(frozen=True)
class IncidentContext:
    property_name: str
    property_internal_code: str
    address_line1: str | None
    address_line2: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    country: str
    timezone: str
    access_notes: str | None
    assignment_note: str | None
```

Nueve campos de la propiedad (los mismos nueve de `CleaningTaskContext`) más las dos notas. Los
campos de la respuesta se llaman **igual que sus columnas**.

Por qué el dataclass y no `from_attributes` sobre `Property`: es lo que convierte las exclusiones de
R5 en **estructurales** — un campo que no está en el dataclass no tiene dónde aterrizar, y
`Property` no se serializa nunca. Por qué once y fijados por un test propio: R1.4, calcado de
`tests/cleaning/test_task_context_read_model.py`.

Por qué los nombres de las columnas y no un alias por audiencia: el portal del huésped ya renombró
`access_notes` a `arrival_notes`, que era correcto ahí —su lector no ve nombres de columna nunca— y
un tercer nombre para una columna que hay que auditar en el censo la vuelve ingrepable. La pantalla
del técnico es una superficie de operación, no de huésped.

Rejected: incluir `wifi_name` — PRD §12 no lo pide y `cleaner-task-context` tampoco lo lleva.
Rejected: incluir un campo de contacto propio — no hay columna de contacto en `properties`, y el
censo de `sdd/roadmap/tech-app.md` ya asigna «instrucciones de contacto/acceso» de PRD §12 a
`access_notes`; inventar una columna es de otro change.
Rejected: reusar `CleaningTaskContext` — comparte nueve campos y no los otros dos, y una raíz común
haría que un campo añadido para una limpieza apareciese en la pantalla de un técnico.

### D5 — `properties.access_notes`: **excepción 6, nueva y nombrada**, más exclusión de los listados

Es la decisión que R2.2/R2.3 encargan al design y la única con una alternativa cara. Aprobada en el
gate de `/sdd:design` el **2026-08-19**, con el cifrado en reposo rechazado explícitamente y no
omitido (ver más abajo y la sección `Aplazado con nombre`).

**Chosen:** dos cosas, y una sola de ellas es mecanismo.

1. **La fila del censo, con forma propia: excepción 6.** `properties.access_notes` entra en la
   tabla de sumideros de la regla 11 con una excepción **nueva**, no con la 3.
2. **El mecanismo: la columna sale del listado paginado de propiedades.**
   `PropertyPageResponse.data` deja de ser `list[PropertyResponse]` y pasa a un
   `PropertyListItemResponse` sin ella; `GET /api/v1/properties/{id}` la conserva, el portal del
   huésped la conserva (ya decidido), y la proyección de este change la estrena. Es la forma de la
   regla 4 —«jamás en listados»— que es de lo que la regla 11 es una aplicación.

   **La exclusión alcanza a las tres notas de `properties`**, no sólo a `access_notes` (aprobado en
   el mismo gate): es un solo esquema y el mismo coste, y un listado que esconde una nota y muestra
   dos es una forma que nadie podrá explicar dentro de seis meses. La fila del censo, en cambio, es
   sólo de `access_notes` — D12 dice por qué.

**Por qué excepción 6 y no la 3.** Por la letra, `access_notes` encaja en la 3: la teclea una
persona autenticada con `MANAGE_PROPERTIES`, sobre su propia vivienda, acotada a 5000 caracteres, y
**no propaga** (`properties-crud` la registra con `redacted()`, así que en `audit_logs.changes` sólo
sale `{"changed": true}`). Pero la cláusula que **concede** la excepción 3 es «el valor no es
nuestro y **no lo hemos ido a buscar**», y aquí lo hemos ido a buscar: el propósito declarado de la
columna es la instrucción de acceso, el portal la renderiza al huésped como `arrival_notes`
precisamente por eso, y un código de portal dentro de ella no es un accidente del operador
descuidado —como sí lo es en `owner_approvals.response_notes`— sino el contenido esperado. Meterla
en la 3 sería una fila que promete «no fuimos a buscarlo» sobre una columna que existe para eso, y
la propia regla 11 dice que una fila del censo que miente es peor que una columna sin censar.

La excepción 6 concede entonces algo que ninguna de las cinco anteriores concede —**un valor de la
regla 3 que sí fuimos a buscar**— y por eso paga un precio que las otras no pagan: el punto 2, más
el aviso al operador. Lo que **no** concede, con el alcance de las demás: no propaga (no entra en
`AUDITABLE_FIELDS["PROPERTY"]` como diff real —sigue `redacted()`— ni en el `metadata` de ningún
`TimelineEvent`); no autoriza a un escritor nuestro (una alerta de cerradura que componga
instrucciones cae bajo la forma estructurada por defecto); y no convierte la columna en sitio seguro
para PII.

**Por qué la exclusión de los listados y no el cifrado en reposo.** El disparador que el roadmap
nombra es de **audiencia** («el conjunto de lectores crece»), y la exclusión de listados es el
remedio con la misma forma que el problema: hoy `GET /api/v1/properties` devuelve las instrucciones
de acceso de **todas** las viviendas del tenant en una sola respuesta, y esa es la única superficie
de bulto que existe. El cifrado en reposo responde a otra amenaza —lectura offline de la base, de un
backup o de una réplica— cuya exposición **este change no mueve**, y que es idéntica para
`cleaning_notes`, `emergency_notes` y `access_records.notes`: pagarla aquí sería o arbitraria (una
de cuatro) o arrastraría las cuatro columnas y una migración de datos a un change sobre la pantalla
de un técnico. Y en el margen: cifrar la columna mientras
`GET /api/v1/guest/info/{token}` la devuelve verbatim a un portador anónimo compra muy poco contra
el riesgo real.

Coste medido de la exclusión: **contrato, cero UI.** Ningún componente del frontend lee
`access_notes` — las cuatro apariciones en `frontend/` están todas en
`lib/api/generated/openapi.d.ts`, que es artefacto generado. Y cero migración.

Rejected: **cifrado en reposo** (Fernet, como `wifi_password_encrypted`) — arrastra migración de
datos sobre filas existentes, descifrado en tres caminos de lectura, y no reduce la exposición por
API, que es donde está. Su argumento no es de este change y cubre a las cuatro columnas por igual:
queda como candidato de roadmap, no como deuda silenciosa.
Rejected: **las dos formas juntas** — es el cifrado con sus costes más la exclusión, y el
razonamiento anterior es el mismo.
Rejected: **excepción 3 sin mecanismo** — R2.3 exige implementar la forma decidida y no sólo
documentarla, y además sería la fila que miente.
Rejected: **forma estructurada** (el valor no sobrevive) — «el código del portal es 4821 y la llave
está en la caja de la entrada» no tiene descomposición en campos que conserve lo que hace falta para
mandar allí a un técnico. Es el mismo argumento con el que la excepción 2 existe.

### D6 — La nota del manager: `incidents.assignment_note`, y **excepción 3 ensanchada**

**Chosen:** columna nueva `assignment_note VARCHAR(2000) NULL` en `incidents`, con su migración de
Alembic sobre `down_revision = 'e7a3c419d82b'`. En la entidad, `assignment_note: str | None = None`;
en `api/schemas.py`, `MAX_ASSIGNMENT_NOTE = 2000` espejando el ancho del DDL. Fila del censo con
forma **excepción 3**, ensanchando su enunciado para nombrarla en vez de abrir una séptima.

Por qué el nombre `assignment_note`: PRD §7.13 no declara ninguna columna aquí, así que no hay
nombre canónico que honrar —es una divergencia declarada del esquema del PRD, como
`users.must_change_password` o `properties.has_wifi_password`—, y nombrarla por el **acto que la
escribe** es lo que mantiene coherentes la fila del censo, el cuerpo de `assign` y la semántica de
D7. Rejected: `manager_note` — nombra un rol, y el rol podría cambiar sin que la columna cambie.
Rejected: `notes` a secas — la entidad ya tiene `title`, `description` y `ai_summary`.

Por qué ancho en el DDL y no `TEXT` con cota sólo en pydantic: es el patrón de `properties`
(`MAX_NAME`, `MAX_ADDRESS`… espejan el ancho de la columna) y evita la situación que
`properties-crud` R2.4 tuvo que arreglar a posteriori en cuatro columnas sin ancho. La cota vive en
la base **y** en el esquema, no sólo en el segundo.

Por qué excepción 3 y no una nueva: el escritor es una persona autenticada con `MANAGE_INCIDENTS`
tecleando prosa suya sobre un trabajo de su tenant, acotada, y **no propaga** (D8). Es la misma
concesión que `owner_approvals.response_notes` —que el propio proposal cita como precedente en
R3.4— y que `messages.content` del manager. El steering dice literalmente cómo se hace esto: «se
ensancha el enunciado en lugar de abrir una excepción nueva por parecido». Y aquí, al contrario que
en `access_notes`, no fuimos a buscar el valor: la columna es para «lo que el ticket no cuenta», no
para un código.

Rejected: reusar `description` — es la palabra de quien reporta, bajo excepción 2, y mezclar en ella
prosa nuestra o del manager es exactamente lo que esa excepción dice que no autoriza.
Rejected: `owner_approvals`-como-vehículo o una tabla de notas — una nota por asignación no es una
entidad, y PRD §12 la pide como un campo.

### D7 — Cada `assign` **reemplaza** la nota

**Chosen:** `assignment_note` es un parámetro **opcional** de `AssignIncidentUseCase.execute` y de
`Incident.assign`, y su valor se escribe **siempre**: enviarla la fija, no enviarla la deja a `NULL`.
La nota pertenece a la asignación vigente, no a la incidencia.

Por qué: `assign` admite reasignación desde cuatro de sus cinco estados de origen (`maintenance` R1: todos salvo `CLASSIFIED`, que es la primera asignación y no tiene técnico previo cuya nota sobrescribir), así que la
alternativa es enseñarle al técnico B lo que el manager escribió para el técnico A — una nota
obsoleta presentada como vigente es peor que ninguna. Además evita el centinela «no enviado» vs.
«enviado como null» que `UpdatePropertyRequest._reject_explicit_nulls` tuvo que construir para el
`PATCH` de propiedades: aquí `POST /assign` es una operación completa, no un parche.

Consecuencia asumida y verificada: `app/cli/seed_demo.py` llama a `AssignIncidentUseCase.execute`
para la incidencia `ACCESS` de PRD §27; no pasará nota, así que el dataset de demo queda con
`assignment_note` a `NULL` y **no cambia**.

Rejected: preservar la nota anterior cuando el cuerpo no la trae — necesita distinguir ausencia de
`null` y muestra a un asignatario lo escrito para otro.
Rejected: acumular notas (histórico) — es una tabla, no un campo, y ningún requisito la pide.

Es un juicio de producto y no una consecuencia del código, así que se llevó al gate y se aprobó
allí el **2026-08-19**.

### D8 — Las dos exclusiones de la nota son estructurales por **ausencia del allowlist**

**Chosen:** `assignment_note` **no** entra en `AUDITABLE_FIELDS["INCIDENT"]` (que sigue con sus once
campos) y **no** entra en `REDACTED_FIELDS`. Nombrarla en un `ChangeSet` levanta `AuditContractError`
por no ser un campo declarado de la entidad — el mismo mecanismo que ya excluye `title`,
`description`, `ai_summary` y `ai_classification`. Y el `TimelineEvent` de la asignación sigue
llevando título constante y `metadata` con sólo identificadores (`incident_id`, `technician_id`).

Por qué no también en el denylist: `wifi_password_encrypted` y `secret_encrypted` demuestran que
denylistar obliga a **añadir** al allowlist (si no, `redacted()` también falla), lo que es
estrictamente más superficie. Aquí no hay nada que registrar ni redactado: que el manager haya
dejado una nota no es un hecho operacional del que se audite el cambio.

R3.5 pide que la exclusión sea estructural «como la de `title`/`description`»: lo es, y con el mismo
mecanismo exacto, así que el test que la fija es una aserción más en
`backend/tests/maintenance/test_free_text_sink_contract.py`, cuyo `SINK_COLUMNS` pasa a tres.

### D9 — El `404` reusa `IncidentNotFoundError`: ni excepción nueva ni fila nueva en `_MAPPING`

**Chosen:** los cuatro casos de R4.4 —no existe, otro tenant, otro técnico, y `property_id` que no
resuelve dentro del tenant— levantan `IncidentNotFoundError`, ya mapeada a
`404 NOT_FOUND` en `api/errors.py`. Cuerpo idéntico en los cuatro por construcción: es la misma
excepción con el mismo mensaje.

El cuarto caso es el que decide algo: una propiedad que no resuelve **no** degrada a respuesta
parcial (R1.5), a diferencia de la reserva colgante de `cleaner-task-context`, que sí degradaba. La
asimetría es la que aquel design razonó y aquí es más fuerte: allí la reserva alimentaba uno de once
campos y la propiedad nueve; aquí la propiedad alimenta **diez de los once**, así que sin ella no
hay contexto que dar. Se registra igualmente un `logger.warning` con `tenant_id`, `incident_id` y
`property_id`, porque un puntero cruzado es una anomalía que una persona debe ver.

Rejected: un `404` propio (`IncidentContextUnavailableError`) — obligaría a declarar un segundo fallo
en el contrato y a que el cliente distinguiese dos cosas que no debe distinguir.
Rejected: `403` para el técnico que no es el asignado — convierte la ruta en sonda de existencia.

### D10 — El contrato: `responses=` per-endpoint y las dos mitades del puente

**Chosen:** la ruta declara `responses=_INCIDENT_CONTEXT_RESPONSES` con el `404` y su
`ErrorEnvelope`, calcado de `_CONTEXT_RESPONSES` de `cleaning/api/tasks_router.py`, y una
`description` que dice tres cosas: (a) el conjunto de incidencias visibles depende del **rol
persistido del token** y ningún parámetro lo ensancha; (b) qué significa cada `null` —campo sin
informar en la fila, no dato que no se pudo resolver—; (c) que `assignment_note` es la nota de la
**asignación vigente** y se sustituye en cada reasignación (D7). Se regeneran y commitean
`backend/openapi.json` (`make openapi`) y `frontend/lib/api/generated/openapi.d.ts` en el mismo PR,
más el campo opcional de `assign` (R6.4) y el listado de propiedades que pierde la columna (D5).

Aviso operativo para `/sdd:tasks`: `cd frontend && npm run api:check` **no funciona desde un
worktree enlazado**; la salida verificada está en `sdd/project.md` (§Worktree bootstrap) y hay que
ponerla en la sección Verification de las tareas, no el comando literal.

### D11 — Lo que la proyección nunca lleva, y por qué es estructural

**Chosen:** las cuatro negativas de R5 se cumplen por la misma propiedad de D4 —el dataclass es el
control, no el serializador— y se fijan con un test del **conjunto exacto** de claves sobre el
cuerpo serializado, no sobre la entidad:

- `wifi_password_encrypted` no es campo de `Property` (`properties-crud` D2), y `has_wifi_password`,
  `cleaning_notes` y `emergency_notes` no son campos de `IncidentContext`.
- Ningún campo de reserva: no se lee `ReservationRepository` en esta ruta. Dos sentencias, ninguna
  contra `reservations`.
- `reported_by_guest_token`, `reported_by_user_id` y `ai_classification` no son campos de
  `IncidentContext` (el primero ya lo descarta el puerto).
- La regla de `cleaner-task-context` se hereda literal: **una proyección puede estrechar, nunca
  unir.** Un campo que un permiso guarda como un todo pasa por la D10 de `dashboard-api`. Esta
  capacidad **diverge** de «agregar no puede conceder» con el mismo alcance acotado que aquélla: su
  sujeto es una incidencia que el llamante ya puede leer entera, y lo que añade son diez campos de
  una propiedad sobre un conjunto de filas **más estrecho** que el que `READ_PROPERTIES` daría.

### D12 — Por qué este change no cubre las otras tres columnas, y qué sí les llega

R2.4 exige que esto quede escrito. Va aquí y en la spec al archivar:

- **`properties.cleaning_notes` y `properties.emergency_notes`**: no las lee esta proyección, así
  que no ganan lector, y su propósito **no** es transportar un valor de la regla 3 —una instrucción
  de limpieza no es un código—, así que no les corresponde la excepción 6 de D5 ni una fila propia
  del censo hoy. Lo que **sí** les llega, y consta porque es más de lo que R2.4 pide: las dos salen
  del listado junto con `access_notes` (D5), porque el mecanismo es un solo esquema y un listado que
  esconde una nota y muestra dos no es una forma defendible. Salir del listado no las mete en el
  censo: el censo se hace por quién escribe la columna y qué transporta, y ninguna de las dos
  transporta un valor de la regla 3 por propósito. `emergency_notes` es la primera candidata a
  excepción 6 el día que gane lector: un código de caja de llaves cabe ahí igual de bien.
- **`access_records.notes`**: no se lee aquí en absoluto —`TECHNICIAN` no tiene
  `READ_ACCESS_RECORDS` y PRD §12 no pide accesos registrados—, y sigue siendo de `cleaner-app`,
  que la tiene aparcada con su propio razonamiento. Su mitigación actual
  (`AccessRecord.register_manual_code` rechaza la petición cuando el código aparece en las notas) no
  es trasladable a `access_notes`: no hay código en claro almacenado contra el que comparar
  (`access-notifications` D9), así que ese mecanismo no está disponible aquí.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dominio · maintenance | `backend/app/maintenance/domain/read_models.py` | **Nuevo.** `IncidentContext`, dataclass congelado de once campos, con el docstring que enumera por qué la lista está cerrada (D4, D11) |
| Dominio · maintenance | `backend/app/maintenance/domain/entities.py` | `Incident.assignment_note: str \| None = None`; `assign()` acepta `assignment_note` y lo escribe siempre (D6, D7) |
| Aplicación · maintenance | `backend/app/maintenance/application/use_cases.py` | `_load_incident_in_scope` extraída y usada por tres llamantes (D3); `GetIncidentContextUseCase` (D2); `AssignIncidentUseCase.execute` gana el parámetro opcional |
| API · maintenance | `backend/app/maintenance/api/schemas.py` | `IncidentContextResponse` (espejo, `from_attributes=True`); `MAX_ASSIGNMENT_NOTE = 2000`; `AssignIncidentRequest` gana el campo opcional manteniendo `extra="forbid"` |
| API · maintenance | `backend/app/maintenance/api/incidents_router.py` | `GET /{incident_id}/context` con `ReadDep`, `_INCIDENT_CONTEXT_RESPONSES` y la `description` de D10. Docstring del módulo: once rutas → doce |
| API · maintenance | `backend/app/maintenance/api/dependencies.py` | `get_incident_context_use_case` con `incidents` + `properties` |
| Infra · maintenance | `backend/app/maintenance/infrastructure/models.py` | `assignment_note: Mapped[str \| None] = mapped_column(String(2000), default=None)` |
| Infra · maintenance | `backend/app/maintenance/infrastructure/repositories.py` | `add`/`save`/rehidratación llevan la columna nueva |
| Migración | `backend/alembic/versions/<rev>_incident_assignment_note.py` | **Nuevo.** `down_revision = 'e7a3c419d82b'`; `ADD COLUMN` nullable, sin backfill; `downgrade` la borra |
| API · properties (D5) | `backend/app/properties/api/schemas.py` | `PropertyListItemResponse` sin las **tres** notas; `PropertyPageResponse.data` pasa a ese tipo |
| Steering | `sdd/steering/security.md` | Dos filas nuevas en la tabla de la regla 11 (+ el recuento de columnas y de filas); **excepción 6** nueva y nombrada; enunciado de la excepción 3 ensanchado para nombrar la nota (D5, D6) |
| Tests | `backend/tests/maintenance/test_incident_context_{read_model,use_case,api}.py` | **Nuevos.** Conjunto de campos cerrado, `null` con su clave sobre el cuerpo serializado, cruce de tenant (incluida la incidencia que apunta a la propiedad de otro tenant), los cuatro `404` idénticos, `CLEANER` y token de huésped rechazados |
| Tests | `backend/tests/maintenance/test_free_text_sink_contract.py` | `SINK_COLUMNS` pasa a tres; aserciones de D8 |
| Tests | `backend/tests/properties/test_api.py` | El listado ya no lleva las notas; el detalle sí |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerados y commiteados (D10) |
| Docs | `docs/maintenance.md` | La pantalla del técnico y el aviso al operador: lo que escriba en `access_notes` lo ve el técnico verbatim, igual que ya lo ve el huésped (`docs/guest-portal.md`) |
| Docs | `docs/properties.md` | La columna sale del listado y sigue en el detalle |
| Diagramas | `docs/diagrams/2026-08-11_autohost-er-entidades.png` | Regenerar al archivar: `incidents` gana una columna. **Los recuentos no cambian** — 31 entidades y 75 relaciones, porque la columna no lleva clave ajena |

## Data & interfaces

**Esquema.** Una columna, ninguna tabla, ninguna clave ajena, ningún índice:

```
incidents.assignment_note   VARCHAR(2000) NULL
```

Nullable y sin backfill: toda incidencia existente queda con `NULL`, que es la respuesta honesta
—nadie escribió una nota— y no un valor inventado. `downgrade` la borra; el dato que se pierde es
sólo el que se escribió tras la migración, y eso es lo que un `DROP COLUMN` significa siempre.

**API.**

```
GET /api/v1/incidents/{incident_id}/context     → 200 IncidentContextResponse | 404 ErrorEnvelope
   permiso: READ_INCIDENTS (+ acotamiento por rol persistido)

POST /api/v1/incidents/{incident_id}/assign     → cuerpo gana `assignment_note?: string(≤2000)`
   permiso: MANAGE_INCIDENTS (sin cambios)

GET /api/v1/properties                          → los items pierden access_notes, cleaning_notes
                                                   y emergency_notes (D5)
GET /api/v1/properties/{id}                      → sin cambios
```

`IncidentContextResponse` es el espejo campo a campo de `IncidentContext` (D4). Sin `exclude_none`
en ninguna parte de `backend/app`, así que un `null` viaja con su clave: comportamiento heredado de
pydantic, con test propio contra el cuerpo serializado y no dado por hecho (R1.3).

**Consultas por petición: dos.** `incidents.get` y `properties.get`. Menos en los caminos que
terminan en `404`. Es el coste de la composición de D2 y se paga en la lectura de una incidencia.

**Sin variables de entorno nuevas, sin cadenas de UI, sin jobs, sin puertos nuevos.**

## Risks & mitigations

| Riesgo | Mitigación |
|---|---|
| **La exclusión de los listados rompe un consumidor.** Es un cambio incompatible del contrato de `properties` | Verificado: ningún componente del frontend lee `access_notes` — las cuatro apariciones en `frontend/` están en el artefacto generado. El typecheck del frontend contra los tipos derivados lo atraparía si apareciera uno |
| **La migración es la primera en tocar `incidents` desde el baseline** y la BD de dev tiene datos desde el 2026-08-10 | `ADD COLUMN ... NULL` sin default de servidor no reescribe la tabla en PostgreSQL 16 y no puede fallar por datos existentes. Se prueba `upgrade`+`downgrade`+`upgrade` sobre una base sembrada |
| **D3 refactoriza dos llamantes vivos.** Un error ahí toca las doce rutas del módulo | El diff es de tres líneas por llamante y el comportamiento está cubierto por los tests de aislamiento existentes de `maintenance`; se corren antes y después. Si el panel lo prefiere mínimo, la alternativa (tercera copia) está en D3 |
| **La nota se pierde en silencio al reasignar** (D7) | Coste asumido en el gate. Documentado en la `description` de la operación (D10.c) y en `docs/maintenance.md`, que es lo único que evita que el manager lo descubra por sorpresa |
| **La excepción 6 es la primera que concede un valor de la regla 3 que sí fuimos a buscar**, y una excepción mal enunciada envejece peor que una columna sin censar | Se enuncia por la propiedad del escritor **y** por el propósito de la columna, con sus tres «lo que NO concede» explícitos, y con el precio (salida del listado) escrito en la misma fila. Dos redacciones fallidas de la excepción 1 constan en el steering como aviso |
| **El censo llevaba un change de retraso** (`arrival_notes` ya existía) y este change no puede cerrar retroactivamente aquella decisión | La fila del censo declara **todos** los escritores y lectores efectivos de hoy, incluido el portal, en vez de describir sólo lo que este change añade. Es lo que la regla 11 pide: la tabla dice quién escribe cada columna *hoy* |
| **Cifrado en reposo aplazado** para cuatro columnas | Rechazado en el gate con su motivo escrito (OQ1) y anotado como candidato de roadmap con nombre en `Aplazado con nombre`, no como deuda tácita |

## Requirement coverage

| Req | Dónde se resuelve |
|---|---|
| R1.1–R1.2 | D4 (nueve campos de propiedad + `timezone`), D2 |
| R1.3 | D4 + test contra el cuerpo serializado (`Data & interfaces`) |
| R1.4 | D4 (dataclass congelado) + test del conjunto exacto |
| R1.5 | D9 (nada de respuesta parcial; `404` + `logger.warning`) |
| R2.1 | D4 (`access_notes` en la proyección) |
| R2.2 | D5 punto 1 (fila del censo con su forma y su escritor) |
| R2.3 | D5 punto 2 (la forma se implementa, no sólo se documenta) |
| R2.4 | D12 |
| R2.5 | D11 (ninguno de los dos es campo del dataclass) |
| R3.1 | D6 (columna + migración) |
| R3.2 | D6 (campo opcional en `AssignIncidentRequest`, `extra="forbid"` y permiso intactos; la tabla de transiciones no se toca) |
| R3.3 | D4 (está en `IncidentContext`) + `IncidentResponse` no cambia (`Changes by area`) |
| R3.4 | D6 (excepción 3 ensanchada, precedente `owner_approvals.response_notes`) |
| R3.5 | D8 |
| R3.6 | D8 (timeline con título constante e identificadores; `AuditLog` como hoy) |
| R4.1 | D1 (`require(READ_INCIDENTS)` en la puerta, antes de la BD; sin permiso nuevo) |
| R4.2 | D3 (`restrict_to_technician_id`, rol persistido, no ensanchable) |
| R4.3 | D3 (`restrict` es `None` para manager y propietaria) |
| R4.4 | D9 (una excepción, cuatro casos, cuerpo idéntico) |
| R4.5 | D2 (`tenant_id` del token, explícito en cada `get`; ningún esquema lo acepta) |
| R4.6 | Tests de `Changes by area`, incluida la incidencia que apunta a la propiedad de otro tenant |
| R4.7 | `CLEANER` no tiene `READ_INCIDENTS`; el token de huésped no pasa por `require()`. Con test propio |
| R5.1–R5.5 | D4, D11 |
| R6.1–R6.4 | D10 |

## Open questions

**Ninguna abierta.** Las tres que este design levantó se resolvieron en el gate de `/sdd:design` el
**2026-08-19**, y quedan aquí con su alternativa rechazada para que `/sdd:run` no las reabra y para
que el panel de seguridad pueda auditar la decisión y no sólo el resultado.

### OQ1 — La forma de la regla 11 para `properties.access_notes` (R2.3) — RESUELTA

**Decidido: excepción 6 nueva y nombrada, más la salida del listado paginado. Sin cifrado en
reposo.** El razonamiento completo está en D5; lo que la decisión rechaza es el cifrado —aquí y en
la variante «las dos formas»— por tres motivos que constan: responde a una amenaza que este change
no mueve, no reduce la exposición por API (que es donde está, con el portal devolviendo la columna a
un portador anónimo), y su argumento cubre por igual a `cleaning_notes`, `emergency_notes` y
`access_records.notes`, así que pagarlo aquí sería arbitrario o arrastraría cuatro columnas y una
migración de datos a un change sobre la pantalla de un técnico.

### OQ2 — ¿La nota de asignación se reemplaza en cada `assign`, o persiste? (D7) — RESUELTA

**Decidido: se reemplaza.** La nota pertenece a la asignación vigente. Rechazado persistirla cuando
el cuerpo no la trae: obliga a distinguir «no enviado» de «enviado como `null`» y puede presentar
como vigente lo que el manager escribió para otro asignatario. El coste asumido —una reasignación sin
nota borra la anterior— va en la `description` de la operación y en `docs/maintenance.md`.

### OQ3 — ¿La exclusión de los listados alcanza a las tres notas o sólo a `access_notes`? — RESUELTA

**Decidido: a las tres.** Un solo esquema, el mismo coste, y un listado que esconde una nota y
muestra dos no es una forma explicable. Rechazado limitarlo a `access_notes`: minimiza el diff del
contrato y deja una asimetría que nadie podrá justificar. La **fila del censo** sigue siendo sólo de
`access_notes` — D12 dice por qué, y salir del listado no es entrar en el censo.

## Aplazado con nombre

Lo que este design decide **no** hacer y que no debe quedar como deuda tácita:

- **`plaintext-sink-encryption-at-rest`** — cifrado en reposo de las cuatro columnas de texto libre
  que pueden transportar un valor de la regla 3 por propósito o por descuido:
  `properties.access_notes`, `properties.cleaning_notes`, `properties.emergency_notes` y
  `access_records.notes`. Es la mitad de la decisión aparcada que OQ1 rechaza pagar aquí, y su
  amenaza (lectura offline de la base, de un backup o de una réplica) es idéntica para las cuatro.
  **`/sdd:tasks` lo añade como entrada de `sdd/roadmap.md`**, y la nota de
  `sdd/roadmap/cleaner-app.md` —que es donde vive hoy la mitad de `access_records.notes`— pasa a
  citarla en vez de seguir describiendo la decisión como pendiente en su totalidad.
- **La ausencia de columna de contacto en `properties`.** PRD §12 pide «instrucciones de
  contacto/acceso» y el censo de `sdd/roadmap/tech-app.md` asigna esa línea a `access_notes`, que es
  lo que este change entrega. Si `tech-app` encuentra con una pantalla delante que hace falta un
  contacto estructurado (teléfono del conserje, del propietario), es columna nueva y es de otro
  change; no se inventa aquí.
