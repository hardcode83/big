# Proposal: cleaning-assign-preconditions

## Why

La vista de gestión de limpiezas que `cleaning-manager-view` entregó (PR #107) se usó contra el
entorno `dev` por primera vez el **2026-08-22**, y su acción principal —asignar limpiadora— falló
con «Esa tarea ya no admite un cambio de asignación» sobre una tarea `CREATED` y sin asignar, que
es exactamente el caso que la vista existe para resolver.

El mensaje no describe lo que pasó. La primera asignación de una tarea `CREATED` dispara
`CLEANER_ASSIGNED` sobre la vivienda (`cleaning/application/use_cases.py`,
`AssignCleaningTaskUseCase`), y la matriz de `properties/domain/state_machine.py` admite ese
trigger **solo desde `AWAITING_CLEANING`** — es su única fila. Desde cualquier otro estado la
transición se rechaza, `_transition` la traduce a `PropertyStateBlocksCleaningError` y el endpoint
responde `409`. `features/cleaning/lib/assign-error.ts` mapea todo `409` a
`assign.error.conflict`, cuyo texto habla del ciclo de vida de la tarea; su propio docstring
enumera los `409` de `cleaning/api/errors.py` y no incluye el que de verdad llega por este camino.
Así que el sistema culpa a la tarea de una precondición de la vivienda.

Dos hechos más, medidos el mismo día, que delimitan el arreglo:

- **La pantalla no puede prevenirlo.** `GET /api/v1/cleaning-tasks` no devuelve el estado
  operacional de la vivienda, así que el control de asignación se ofrece siempre; solo se
  deshabilita por no haber elegido a nadie o por elegir a quien ya está asignado
  (`assign-cleaner-control.tsx`).
- **La suite no lo cubría porque su fixture no lo permite.** `task_a`
  (`backend/tests/cleaning/conftest.py`) fuerza `current_operational_state = AWAITING_CLEANING`
  antes de crear la tarea, que es el único estado en que la operación funciona.

**Y el contraste está cerrado por medición, no por análisis.** El mismo 2026-08-22, llevando
PAJARITOS8 por el camino real —reserva, checkout y aprovisionamiento, procedimiento en
`infra/environments/dev/RUNBOOK-seed-demo.md` §5— la vivienda quedó en `AWAITING_CLEANING` con una
tarea `CREATED` sin asignar, y desde la misma pantalla y con el mismo usuario la asignación **pasó
sin error** a las 08:47:43 UTC: la tarea quedó `ASSIGNED` y la vivienda en `CLEANING_SCHEDULED`, con
su fila de transición escrita en la misma transacción. Dos operaciones idénticas, dos resultados
opuestos, y la única variable es el estado operacional de la vivienda. El diagnóstico no depende de
leer la matriz: está medido por los dos lados.

Un tercer dato, este sí medido, sobre por qué esto importa más de lo que parece: en `dev` la vivienda
REDES11 llegó a `AWAITING_CLEANING` el 2026-08-16 **sin ninguna fila en
`property_state_transitions`**, cinco minutos y medio después de que alguien creara una tarea a mano
y justo antes de asignarla con éxito. Es decir: la columna se escribió por fuera de la máquina de
estados. El motivo no consta —una petición rechazada no deja auditoría—, pero el análisis completo
está en la proposal de `cleaning-stall-blocks-next-stay`, y la hipótesis que encaja con la secuencia
es que este mismo `409` ya bloqueó a alguien y la salida que encontró fue el `UPDATE`.

Entrada de roadmap: `cleaning-assign-preconditions` (`completes: cleaning-manager-view`).

## What changes

Después de este change, `/cleaning` dice la verdad sobre por qué una asignación no puede ocurrir, y
no ofrece confirmar una acción que va a fallar. El backend distingue las dos causas del `409` —el
ciclo de vida de la tarea y la máquina de estados de la vivienda— de forma que el cliente pueda
discriminarlas sin leer prosa; el listado publica lo que la pantalla necesita para saber si una
tarea es asignable ahora; y el contrato declara la precondición en vez de dejarla implícita.

**La máquina de estados no se toca.** El principio 1 de `steering/product.md` la hace innegociable:
si `CLEANER_ASSIGNED` solo es legal desde `AWAITING_CLEANING`, la respuesta correcta a una vivienda
en otro estado sigue siendo negarse. Lo que este change corrige es que el sistema mienta sobre el
motivo y que la UI invite a intentarlo.

## Requirements

### R1 — El `409` de la vivienda es distinguible del `409` de la tarea

**As a** cliente del API (hoy la web, mañana la app de campo), **I want** poder discriminar por qué
se rechazó la asignación sin interpretar el mensaje, **so that** cada causa pueda tratarse distinto.

Acceptance criteria:

1. WHEN `PATCH /api/v1/cleaning-tasks/{id}` se rechaza porque el estado operacional de la vivienda
   no admite `CLEANER_ASSIGNED`, THE SYSTEM SHALL responder un sobre de error cuyo campo de código
   sea **distinto** del que devuelve un rechazo por el ciclo de vida de la tarea.
2. WHEN el rechazo viene de `CleaningTask.assign` —la tarea no está en `CREATED` ni en `ASSIGNED`—
   THE SYSTEM SHALL conservar el código y el estado HTTP que devuelve hoy, para no romper a ningún
   consumidor existente.
3. THE SYSTEM SHALL NOT incluir en el sobre el estado operacional concreto de la vivienda como
   dato libre si eso amplía lo que el rol del llamante puede leer; qué se publica y a quién se
   decide en design.
4. THE SYSTEM SHALL cubrir con test cada una de las dos causas **partiendo de un estado de vivienda
   distinto del fixture actual**: un test cuya vivienda no esté en `AWAITING_CLEANING` es el que
   faltaba y el que prueba que la distinción existe.

### R2 — El mensaje nombra a quien bloquea

**As a** `PROPERTY_MANAGER`, **I want** que el error me diga qué impide asignar, **so that** sepa
si tengo que esperar, arreglar la vivienda o mirar otra tarea.

Acceptance criteria:

1. WHEN la asignación se rechaza por el estado de la vivienda, THE SYSTEM SHALL mostrar un mensaje
   localizado que atribuya el bloqueo **a la vivienda** y SHALL NOT afirmar que la tarea no admite
   un cambio de asignación.
2. WHEN se rechaza por el ciclo de vida de la tarea, THE SYSTEM SHALL seguir mostrando el mensaje
   actual.
3. THE SYSTEM SHALL elegir el mensaje por el código del sobre de R1, nunca por el texto que venga
   del backend, que es técnico y está en inglés (regla ya vigente en `assign-error.ts`).
4. THE SYSTEM SHALL declarar las claves nuevas en `locales/es` **y** `locales/en`.

### R3 — La pantalla no ofrece confirmar lo que no puede ocurrir

**As a** `PROPERTY_MANAGER`, **I want** ver de un vistazo qué tareas puedo asignar ahora,
**so that** no gaste intentos en las que no.

Acceptance criteria:

1. WHERE una tarea no es asignable en este momento, THE SYSTEM SHALL deshabilitar el control de
   confirmación de esa fila y SHALL indicar el motivo de forma localizada.
2. THE SYSTEM SHALL derivar esa condición de datos que **ya vienen en la respuesta del listado**,
   sin una petición adicional por fila.
3. IF la condición cambia entre la carga de la lista y la confirmación, THEN THE SYSTEM SHALL
   seguir tratando el rechazo del backend como la autoridad (R1/R2): la guarda de la UI es una
   cortesía, no un permiso.
4. THE SYSTEM SHALL mantener habilitado el `<select>` aunque el botón esté deshabilitado, por la
   razón de accesibilidad que `assign-cleaner-control.tsx` ya documenta (deshabilitar un elemento
   con el foco lo manda al `<body>`).

### R4 — La precondición está escrita donde se consulta

**As a** quien integra o opera el sistema, **I want** que la precondición de estado esté declarada,
**so that** no haya que leer la matriz de la máquina de estados para saber cuándo se puede asignar.

Acceptance criteria:

1. THE SYSTEM SHALL declarar en la descripción OpenAPI del `PATCH /cleaning-tasks/{id}` que la
   primera asignación exige que la vivienda esté en `AWAITING_CLEANING`, y qué se responde si no.
2. WHERE el contrato publicado cambie de forma, THE SYSTEM SHALL regenerar `backend/openapi.json`
   y el artefacto derivado del frontend en el mismo Pull Request, conforme a
   `steering/documentation.md`.
3. THE SYSTEM SHALL recoger la misma precondición en `docs/cleaning.md`, junto al resto de la
   operación de asignación.

## Out of scope

- **Ampliar la matriz de estados** para que `CLEANER_ASSIGNED` sea legal desde más estados. Es una
  decisión de producto sobre el principio 1 de `steering/product.md`, no un arreglo de mensaje.
- **La limpieza que se queda sin cerrar y congela la vivienda**, incluido si debe existir una
  operación de abandono de tarea y qué pasa con el check-in que no puede aplicarse: eso es la
  entrada `cleaning-stall-blocks-next-stay`, que sale del mismo día de operación.
- **Impedir la creación manual de tareas** (`POST /cleaning-tasks`) sobre viviendas que no están en
  `AWAITING_CLEANING`. Una limpieza a mitad de estancia es un caso legítimo y negarla aquí sería
  decidir de más; lo que este change garantiza es que la pantalla no finja que esa tarea se puede
  asignar ya (R3).
- **La vista de detalle de tarea** (`/cleaning/[id]`) y cualquier otra superficie nueva.
- El resto de las nueve mutaciones de limpieza, que `cleaning-manager-view` ya dejó fuera.

## Affected specs

- `sdd/specs/cleaning-manager-view.md` — el mapa de errores de la asignación y la nueva condición
  de la UI.
- `sdd/specs/cleaning.md` — la precondición de estado de la asignación y la respuesta de error.
- `sdd/specs/api-contract.md` — solo si R1 estrena código de error en el sobre publicado.
- `sdd/specs/dashboard-api.md` — solo si R3 se resuelve ampliando el listado de tareas con datos de
  la vivienda y eso toca su contrato de lectura.
