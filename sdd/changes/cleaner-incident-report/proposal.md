# Proposal: cleaner-incident-report

## Why

PRD §11 pone «reportar incidencia» como uno de los nueve elementos de la UI de limpiadora, y
PRD §12 lista «reporte de limpiadora durante checklist» como una de las cinco fuentes de creación
de incidencias. **Hoy no existe ninguna de las dos mitades**: el enum tiene `IncidentSource.CLEANER`
pero su único escritor es `backend/app/cli/seed_demo.py`, no hay ninguna ruta que cree incidencias
fuera del portal anónimo del huésped y del pipeline de mensajería, `Incident` no tiene forma de
apuntar a la tarea durante la cual se reportó, y `specs/maintenance.md` R8 dice literalmente
«THE SYSTEM NEVER SHALL exponer estas rutas al rol `CLEANER`» con la fila RBAC
`` `CLEANER`, `SUPER_ADMIN` | nada de este módulo ``.

La pieza que faltaba ya está puesta: `maintenance` dejó en 2026-08-17 un `ReportIncidentUseCase`
genérico —cualquier `IncidentSource`, `property_id` resuelto dentro del tenant, `AuditLog` +
`TimelineEvent` en la misma transacción— **deliberadamente sin ruta**, y su docstring nombra a los
futuros llamantes. Este change trae el primero de ellos. Y `cleaner-task-context` (archivada el
2026-08-19) dejó el molde exacto de una superficie de limpiadora: una ruta colgada de la tarea,
acotada por `CleaningActor.restrict_to_cleaner_id` derivado del rol persistido, sin permiso nuevo
y sin ensanchar nada por parámetro.

Entrada de roadmap: `cleaner-incident-report` (`needs: maintenance, cleaning`, ambas cerradas).
Desbloquea `cleaner-app`, que la declara en su `needs`.

## What changes

Después de este change una limpiadora podrá abrir una incidencia **desde una tarea de limpieza
suya y solo desde ahí**, con título y descripción, y el sistema la creará `OPEN` sellada con
`IncidentSource.CLEANER`, atribuida a su usuario y vinculada a la tarea por una columna nueva
`incidents.cleaning_task_id`. La incidencia entra en el flujo de `maintenance` como cualquier otra:
el job de clasificación de R3 le pondrá `category` y `severity` en su siguiente tick, y a partir de
ahí es del manager. La limpiadora no lee, no lista, no clasifica y no resuelve nada: recibe el
acuse de la que acaba de crear y nada más. La tabla RBAC de `specs/maintenance.md` y su cláusula
`NEVER SHALL` pasan de «nada de este módulo» a «solo el alta acotada a su propia tarea».

## Requirements

### R1 — La ruta de alta, colgada de la tarea

**Como** limpiadora, **quiero** reportar una incidencia desde la tarea que estoy haciendo, **para**
que lo que me encuentro en el piso llegue a quien puede arreglarlo sin llamar a nadie.

Criterios de aceptación:

1. WHEN se solicita `POST /api/v1/cleaning-tasks/{task_id}/incidents` con `title` y `description`
   sobre una tarea alcanzable por el llamante, THE SYSTEM SHALL crear la incidencia y responder
   `201` con el acuse de R4.
2. THE SYSTEM SHALL montar la ruta **bajo `cleaning`** y NEVER SHALL añadir una ruta de creación
   bajo `/api/v1/incidents`: la negativa de `specs/maintenance.md` R8 («NEVER SHALL exponer una
   ruta de **creación** de incidencias en este módulo») sigue siendo cierta después de este change,
   porque el sujeto de esta ruta es la tarea de limpieza y no la incidencia.
3. THE SYSTEM SHALL aceptar **exactamente dos campos** en el cuerpo, `title` y `description`, con
   `extra="forbid"`, y NEVER SHALL aceptar `property_id`, `reservation_id`, `tenant_id`, `source`,
   `category`, `severity`, `status`, `assigned_technician_id` ni ningún campo de coste.
4. THE SYSTEM SHALL derivar `property_id` de la tarea resuelta dentro del tenant, y NEVER SHALL
   tomarlo de la petición.
5. THE SYSTEM SHALL declarar la operación en `backend/openapi.json` con su esquema de petición y de
   respuesta, y SHALL mantener regenerado y commiteado `frontend/lib/api/generated/openapi.d.ts`.
6. THE SYSTEM SHALL declarar sus respuestas de error en la propia ruta con el sobre
   `{error:{code,message,details}}` de PRD §23.

### R2 — Quién puede llamarla, y sobre qué filas

**Como** responsable de la seguridad del sistema, **quiero** que el alta esté acotada al mismo
conjunto de filas que la limpiadora ya puede operar, **para** que reportar no le conceda ni una
lectura más de las que tiene.

Criterios de aceptación:

1. THE SYSTEM SHALL exigir `EXECUTE_CLEANING_TASKS` en la puerta y responder `403` **antes de
   resolver la tarea y sin escribir nada** cuando el llamante no lo tiene. No hay permiso nuevo: ese permiso lo tiene hoy
   **solo** el rol `CLEANER` (`PROPERTY_MANAGER` tiene `MANAGE_CLEANING_TASKS`, no éste), que es
   exactamente el conjunto de llamantes que PRD §12 nombra para esta fuente.

   **Corregido el 2026-08-22 (panel de seguridad de la sección 6): la redacción original decía
   «antes de tocar la base de datos» y era literalmente falsa.** `get_authenticated_request`
   hace un `SELECT` sobre `users` —`get_active_by_id`, que es lo que relee el rol persistido en
   cada petición— **antes** de que `require(...)` llegue a evaluar el permiso, así que toda ruta
   autenticada de este sistema toca la base de datos antes de poder devolver un `403`. Esa
   lectura es la autenticación misma y no es evitable ni deseable evitarla. Lo que sí es cierto,
   y es lo que la garantía necesita, es que el `403` llega **antes de resolver la tarea y sin
   escribir una fila**: la puerta no sirve como sonda de qué tareas existen, y eso se comprueba
   con un `403` idéntico para una tarea real y para un uuid inventado.
2. WHILE el llamante tiene rol `CLEANER`, THE SYSTEM SHALL restringir la tarea a las que tienen su
   `assigned_cleaner_id`, derivado de `CleaningActor.restrict_to_cleaner_id` sobre el rol
   **persistido** que se relee de la fila del usuario en cada petición, y NEVER SHALL aceptar ni
   ensanchar ese acotamiento desde la petición.
3. IF la tarea no existe, pertenece a otro tenant, está asignada a otra limpiadora, o su
   `property_id` no resuelve dentro del tenant, THEN THE SYSTEM SHALL responder `404 NOT_FOUND` con
   un cuerpo **idéntico** en los cuatro casos, de modo que la ruta no sirva de sonda de existencia.

   **Precedencia con R2.5, aclarada el 2026-08-19 (panel de sección 5).** Una fila puede cumplir
   este criterio y el de R2.5 a la vez: una tarea **propia**, en estado terminal, cuyo
   `property_id` no resuelve dentro del tenant. Los dos no pueden ser ciertos a la vez en la
   respuesta, así que manda el orden de D5 y **gana el `409`**: la puerta de estado corre antes
   que la resolución de la propiedad. No abre ninguna sonda, y por eso se resuelve así y no al
   revés — para llegar a ese `409` el llamante ya ha pasado las dos comprobaciones de pertenencia,
   de modo que sólo aprende algo de una tarea que ya es suya. Los otros tres caminos de este
   criterio siguen siendo indistinguibles entre sí.
4. THE SYSTEM SHALL tomar el `tenant_id` únicamente del token verificado y SHALL pasarlo explícito a
   cada método de repositorio.
5. THE SYSTEM SHALL permitir el alta sobre una tarea en cualquier estado en el que la limpiadora
   pueda estar trabajando —`ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`— y SHALL rechazarla con `409` sobre
   una tarea ya terminal (`COMPLETED`, `REJECTED`, `CANCELLED`): PRD §12 dice «durante checklist».

### R3 — El escritor que sella `IncidentSource.CLEANER`

**Como** manager, **quiero** que la incidencia de la limpiadora entre en el flujo de mantenimiento
indistinguible de cualquier otra, **para** que la clasificación, la asignación y el timeline
funcionen sin un camino especial.

Criterios de aceptación:

1. THE SYSTEM SHALL crear la incidencia con `source = IncidentSource.CLEANER`, sellado por el
   escritor, y NEVER SHALL leerlo de la petición.
2. THE SYSTEM SHALL dejarla en `status = OPEN` sin fijar `category`, `severity`, `ai_summary` ni
   `ai_classification`, de modo que la recoja el job de clasificación de `specs/maintenance.md` R3
   en su siguiente tick, y NEVER SHALL clasificarla dentro de la petición que la crea.
3. THE SYSTEM SHALL escribir `reported_by_user_id` con el id del usuario autenticado, y NEVER SHALL
   escribir `reported_by_guest_token`.
4. THE SYSTEM SHALL descargar la precondición que el puerto no puede detectar: resolver
   `property_id` dentro del tenant antes de escribir nada. `specs/maintenance.md` R8 la declara
   como obligación del llamante porque las claves ajenas de `incidents` son globales y no compuestas
   con `tenant_id`; aquí se satisface por composición, porque el `property_id` sale de una tarea ya
   resuelta dentro del tenant.
5. THE SYSTEM SHALL escribir la entidad, su `AuditLog` (`INCIDENT_CREATED`, actor el usuario, con su
   IP) y su `TimelineEvent` (`INCIDENT_CREATED`, actor `USER`) en **una sola transacción**, con un
   título de timeline **constante** y metadatos que sean solo identificadores.
6. THE SYSTEM SHALL exigir actor: una creación sin actor SHALL rechazarse y no comitear nada.
7. THE SYSTEM SHALL NOT crear un segundo caso de uso paralelo a `ReportIncidentUseCase` para esta
   fuente: el alta genérica existe precisamente para esto y SHALL extenderse, no duplicarse.

### R4 — El vínculo con la tarea, y el acuse

**Como** manager, **quiero** saber durante qué limpieza se reportó cada incidencia, **para** poder
mirar las fotos y el checklist de esa misma tarea cuando la triago.

Criterios de aceptación:

1. THE SYSTEM SHALL añadir a `incidents` una columna `cleaning_task_id` **nullable**, con clave
   ajena a `cleaning_tasks(id)` y `ondelete="RESTRICT"` —la misma postura que `property_id` y
   `reservation_id` ya tienen en esa tabla—, y su migración Alembic.
2. THE SYSTEM SHALL dejarla `NULL` en toda incidencia que no nazca de una tarea de limpieza, y NEVER
   SHALL exigirla: las incidencias del portal del huésped, de una conversación y del comando de
   siembra siguen siendo válidas sin ella.
3. THE SYSTEM SHALL escribirla en el alta de R1 con el `task_id` de la ruta, y NEVER SHALL aceptarla
   en ningún esquema de petición ni exponer una ruta que la modifique después.
4. WHEN el alta tiene éxito, THE SYSTEM SHALL responder un acuse de **tres campos** —`id`, `status`
   y `created_at`— espejo del `IncidentReportedResponse` del portal, y NEVER SHALL incluir en él
   `category`, `severity`, `ai_summary`, `ai_classification`, `reported_by_guest_token` ni el
   `description` de vuelta.
5. THE SYSTEM SHALL fijar ese conjunto de campos con un test propio, de modo que añadir uno sea un
   acto deliberado y no una deriva.

### R5 — Texto libre: los dos sumideros de la regla 11

**Como** responsable de la seguridad del sistema, **quiero** que el segundo escritor humano de
`incidents.title`/`description` quede censado y acotado, **para** que la excepción de la regla 11 no
se ensanche por omisión.

Criterios de aceptación:

1. THE SYSTEM SHALL acotar `title` y `description` en el esquema de petición —no en la entidad—, con
   `min_length=1`, recorte de espacios y los mismos máximos que el portal (`300` y `5000`), que son
   los que la DDL y el censo ya conocen.
2. THE SYSTEM NEVER SHALL propagar `title` ni `description` a `audit_logs.changes` ni a
   `timeline_events`: el `ChangeSet` de `INCIDENT` sigue con su lista blanca y el título de timeline
   sigue siendo una constante literal.
3. THE SYSTEM SHALL registrar este escritor en el censo de sumideros de texto libre de
   `sdd/steering/security.md` regla 11 y SHALL hacer que el guardián automático
   (`backend/tests/maintenance/test_free_text_sink_contract.py`, que vigila a quien nombre
   `ReportIncidentUseCase` o el puerto `IncidentRepository`) lo reconozca en vez de fallar.
4. THE SYSTEM SHALL registrar en logs el `task_id` y el `incident_id`, y NEVER SHALL registrar el
   texto reportado.

### R6 — La incidencia que le bloquea su propio cierre

**Como** limpiadora, **quiero** entender por qué no puedo cerrar la tarea después de reportar,
**para** no quedarme atascada delante de un `409` que no explica nada.

Criterios de aceptación:

1. THE SYSTEM SHALL dejar intacta la tercera cláusula de evidencia de `CleaningTask.complete()`:
   sigue siendo `has_unresolved_critical(tenant_id, property_id)`, acotada a la **propiedad**.
   `specs/cleaning.md` ya lo dice con esas palabras, y es más estricta que PRD §11 («creadas durante
   la limpieza»), nunca más laxa. Estrecharla a la tarea es otro change (ver §Out of scope).
2. THE SYSTEM SHALL documentar el acoplamiento como comportamiento declarado: una incidencia recién
   creada por la limpiadora nace `MEDIUM` por defecto y **no bloquea el cierre en el momento**; solo
   lo bloquea si el job de clasificación de `maintenance` R3 la sube después a `CRITICAL`, o si ya
   había una `CRITICAL` sin resolver en la propiedad por cualquier otra vía.
3. IF el cierre se rechaza por esa cláusula, THEN THE SYSTEM SHALL seguir respondiendo el `409` que
   `BlockingIncidentError` ya produce, con un mensaje que nombre la causa —una incidencia `CRITICAL`
   sin resolver **en la propiedad**— y NEVER SHALL incluir el identificador, el título ni la
   descripción de la incidencia que bloquea: `CLEANER` no tiene `READ_INCIDENTS` y ese cuerpo sería
   la lectura que R2 le niega.
4. THE SYSTEM SHALL cubrir con un test el recorrido completo: la limpiadora reporta, el clasificador
   sube la incidencia a `CRITICAL`, y su `complete()` se rechaza.

### R7 — La reescritura de lo que `specs/maintenance.md` afirma hoy

**Como** cualquiera que lea las specs, **quiero** que la fila RBAC diga lo que el código hace,
**para** que la spec no siga afirmando lo contrario de lo que este change entrega.

Criterios de aceptación:

1. THE SYSTEM SHALL reescribir la fila `` `CLEANER`, `SUPER_ADMIN` | nada de este módulo `` de la
   tabla RBAC de `specs/maintenance.md` R8, separando los dos roles: `SUPER_ADMIN` sigue sin nada,
   y `CLEANER` pasa a «abrir una incidencia desde una tarea de limpieza suya, y nada más».
2. THE SYSTEM SHALL reescribir la cláusula «THE SYSTEM NEVER SHALL exponer estas rutas al rol
   `CLEANER` ni al portador de un token de huésped» para que siga siendo cierta: las **once rutas
   de `/api/v1/incidents`** siguen cerradas a `CLEANER`, y lo que se abre está en otro módulo.
3. THE SYSTEM SHALL actualizar la enumeración de superficies que crean incidencias («la anónima del
   portal del huésped, el pipeline de mensajería y el comando `make seed-demo`») para incluir ésta.
4. THE SYSTEM SHALL grepear la redacción vieja por todo el árbol —`specs/`, docstrings, `docs/`— y
   no dejar ninguna afirmación superviviente de que `CLEANER` no puede nada de este módulo.

## Out of scope

- **La UI.** `/cleaner` y `/cleaner/tasks/[id]` con su botón «reportar incidencia» los implementa
  `cleaner-app`, que ya declara esta entrada en su `needs:`.
- **Estrechar la tercera cláusula de `complete()` a la tarea.** PRD §11 dice «creadas durante la
  limpieza» y el código mira toda la propiedad. Con `cleaning_task_id` el arreglo pasa a ser
  posible, pero **relajaría** un invariante de cierre existente —una `CRITICAL` del huésped dejaría
  de bloquear— y toca el puerto `BlockingIncidentQuery`, su adaptador, `CleaningCompletionEvidence`
  y `specs/cleaning.md`. Merece su propia entrada de roadmap con su panel; decidido en el gate de
  `/sdd:new` del 2026-08-19.
- **Que la limpiadora lea, liste o siga incidencias.** Decidido en el mismo gate: el acuse de R4 es
  toda la lectura que tiene. Un `GET` acotado a su tarea exigiría permiso de lectura nuevo y más
  filas RBAC que reescribir, y PRD §11 no lo pide entre sus nueve elementos.
- **Que la limpiadora fije `category` o `severity`.** Decidido en el mismo gate: rompería la
  invariante de `specs/maintenance.md` R8 de que `classify` es la única puerta de salida de `OPEN`,
  y PRD §12 pone la clasificación en el `AIAdapter`.
- **Fotos en la incidencia.** `cleaning-photos-storage` sube fotos contra la **tarea**; adjuntarlas
  a la incidencia es superficie de `maintenance` y PRD §11 no la pide para la limpiadora.
- **`IncidentSource.LOCK_ALERT`.** Sigue sin escritor y sin superficie de importación, como
  `maintenance` declaró.
- **Notificaciones al manager por la incidencia de la limpiadora.** El disparo por severidad
  (`INCIDENT_HIGH`/`INCIDENT_CRITICAL`) ya vive en `maintenance` y ocurre al clasificar, no al
  crear; este change no lo toca.

## Affected specs

- `sdd/specs/cleaner-incident-report.md` *(no existe aún — se creará al archivar)*
- `sdd/specs/maintenance.md` — tabla RBAC de R8, la cláusula `NEVER SHALL … rol CLEANER`, la
  enumeración de superficies de creación y el contrato de `ReportIncidentUseCase`
  (`cleaning_task_id` y `reported_by_user_id`, que hoy dice «SHALL NOT aceptar»).
- `sdd/specs/cleaning.md` — la ruta nueva colgada de la tarea y la referencia al acoplamiento de la
  tercera cláusula de cierre.
- `sdd/specs/api-contract.md` — la operación nueva en `backend/openapi.json` y su artefacto derivado
  del frontend.
- `sdd/specs/auth-tenancy.md` — solo **si** el design decide un permiso propio en vez de reusar
  `EXECUTE_CLEANING_TASKS` (R2.1). Con la reutilización que este proposal asume, el reparto de
  permisos por rol que esa spec fija no cambia, y basta con que su descripción de `CLEANER` no
  contradiga la superficie nueva.
### Las ocurrencias literales que `/sdd:archive` tiene que reescribir

Grepeadas por todo el árbol el 2026-08-22 (tarea 10.1). Todo lo que estaba **fuera** de
`sdd/specs/` ya está corregido en este change; lo que sigue es lo que queda, con su línea, para
que el archivado no tenga que volver a buscarlo:

| Fichero:línea | Lo que dice hoy | Por qué es falso después de este change |
|---|---|---|
| `sdd/specs/maintenance.md:227` | «Las superficies que crean incidencias son la anónima del portal del huésped, el pipeline de mensajería y el comando `make seed-demo`» | Falta la cuarta: la limpiadora desde su propia tarea (R7.3) |
| `sdd/specs/maintenance.md:244` | «THE SYSTEM SHALL NOT aceptar `reservation_id` ni `reported_by_user_id`» | `ReportIncidentUseCase` acepta ya `reported_by_user_id` y `cleaning_task_id`, cada uno con su precondición descargada (R7.4, D4) |
| `sdd/specs/maintenance.md:277` | Fila RBAC `` `CLEANER`, `SUPER_ADMIN` \| nada de este módulo `` | `SUPER_ADMIN` sigue sin nada; `CLEANER` pasa a «abrir una incidencia desde una tarea de limpieza suya, y nada más» (R7.1) |
| `sdd/specs/maintenance.md:292` | «THE SYSTEM NEVER SHALL exponer estas rutas al rol `CLEANER`…» | Sigue siendo **cierta** de las once rutas de `/api/v1/incidents`, y hay que reescribirla para que se lea así en vez de como «CLEANER no puede nada» (R7.2) |
| `sdd/specs/maintenance.md:313` | «auditar sobre `INCIDENT` exactamente **once** campos» | Son doce: entró `cleaning_task_id` (R7.4, D10) |
| `sdd/specs/maintenance.md:96` | «las vías que crean incidencias por HTTP son una ruta **anónima desde internet** y un pipeline disparado por un webhook» | Son tres: esta ruta es una tercera vía HTTP y es **autenticada**. La frase sostiene el razonamiento de la regla 12(d) sobre por qué no se clasifica en la petición, así que hay que reescribirla sin romper ese argumento — que sigue en pie, porque lo que la 12(d) acota es el trabajo que un desconocido provoca desde fuera (R7.4) |

Y **fuera** de `sdd/specs/`, ya arreglado aquí, anotado para que no se busque dos veces:
`ReportIncidentUseCase`'s docstring (el «took no `reservation_id`»), el docstring de
`BlockingIncidentQuery` en `cleaning/domain/ports.py` («`maintenance` has no application layer
yet»), `docs/cleaning.md` («las incidencias no se pueden crear todavía») y
`docs/maintenance.md` (la enumeración de fuentes y la tabla RBAC). El docstring de
`tests/maintenance/test_api_authorization.py` se revisó y **sigue siendo cierto** — se le añadió
la nota de por qué sobrevive a este change en vez de cambiarlo.

- `sdd/specs/domain-foundation-ops.md` — describe el esquema base de las 8 entidades operativas,
  incluidas las FK nullable de `incidents`. La columna `cleaning_task_id` la documenta en primer
  lugar la spec nueva; aquí solo hay que evitar que la enumeración de FKs de `Incident` quede
  desactualizada.
