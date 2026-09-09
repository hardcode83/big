# Design: cleaning-task-manage-web

## Context

`/cleaning` ya existe y está descrita entera en `sdd/specs/cleaning-manager-view.md`: `CleaningView`
(`frontend/features/cleaning/components/cleaning-view.tsx`) orquesta tres consultas —tareas paginadas
más los dos catálogos cacheados de `hooks/use-cleaning-data.ts`—, un store Zustand de filtros y **una
sola región viva** `role="status" aria-live="polite"`, y `CleaningTaskRow` pinta cada tarea como
tarjeta con el control de asignación detrás de `useHasPermission("MANAGE_CLEANING_TASKS")`
(`cleaning-task-row.tsx:120`). La única mutación que la vista posee hoy es
`hooks/use-assign-cleaning-task.ts`.

Las tres operaciones que faltan ya están publicadas por el backend y por el contrato generado:
`POST /api/v1/cleaning-tasks` (201, `CreateCleaningTaskRequest` = `property_id` + `reservation_id?` +
`scheduled_start?` + `scheduled_end?`), `POST /api/v1/cleaning-tasks/{id}/validate`
(`ValidateCleaningTaskRequest` = `validation_status`) y `POST /api/v1/cleaning-tasks/{id}/cancel`
(`{ reason }`), esta última con hook ya escrito —`hooks/use-cancel-cleaning-task.ts`— y un único
consumidor en `features/dashboard/stalls/components/cancel-cleaning-dialog.tsx`. Los cuatro campos que
el DTO descarta (`completed_at`, `validation_status`, `validated_at` en el ítem del listado;
`current_operational_state` en el de propiedad) están en `frontend/lib/api/generated/openapi.d.ts`
verificados el 2026-09-05, así que **no hay regeneración de contrato ni cambio de backend**.

Precedentes de los que este diseño no se separa: `features/platform/components/create-user-form.tsx`
(formulario de creación con `<form onSubmit>` y errores por campo),
`features/tech/components/detail/tech-eta-field.tsx` (`datetime-local` → `toISOString()`),
`features/dashboard/stalls/components/cancel-cleaning-dialog.tsx` (Sheet con motivo acotado a 500) y
`features/cleaning/lib/assign-error.ts` (estado HTTP → clave, nunca `ApiError.message`).

## Decisions

### D1 — El formulario de creación es un panel en el flujo de la vista, no un Sheet

**Chosen:** un botón de creación en una barra nueva por encima de `CleaningFilters` que despliega un
panel **en el flujo normal del documento** (disclosure), no un overlay. R1.5 exige que el resultado se
anuncie por la **región viva única** de la vista «sin añadir una segunda región», y esa región vive
justo encima del cuerpo: con un Sheet superpuesto el usuario no la vería y habría que duplicarla dentro
del overlay, que es exactamente lo prohibido. Un panel en el flujo también evita un Sheet a pantalla
completa en 320 px, que es donde se opera.

Rejected: Sheet como el de cancelar — obliga a la segunda región viva que R1.5 prohíbe.
Rejected: ruta propia `/cleaning/new` — estrena superficie de navegación y pierde el contexto de la lista.
Rejected: `AlertDialog` — es para confirmar, no para capturar tres campos.

### D2 — El aviso de no-asignabilidad se deriva de `current_operational_state` del catálogo, con una constante local

**Chosen:** opción (a) de la pregunta abierta 1 del proposal. `PropertySummary` gana
`currentOperationalState`, que **ya viaja** en `PropertyListItemResponse` sin petición extra, y
`features/cleaning/lib/assignable-property-state.ts` declara la única fila de la matriz que admite
`CLEANER_ASSIGNED`:

```ts
export const ASSIGNABLE_PROPERTY_STATES: readonly PropertyOperationalState[] = ["AWAITING_CLEANING"];
export function warnsNotAssignable(state: PropertyOperationalState | undefined): boolean;
```

El tipo se alía del contrato generado (`components["schemas"]["PropertyOperationalState"]`), como ya
hacen `CleaningTaskStatus` y `CleaningAssignmentBlocker` en `data/dto.ts`, así que **renombrar** un
estado en el backend rompe el typecheck. **Lo que no rompe nada es añadir una segunda fila
`(X, CLEANER_ASSIGNED)` a `PropertyStateMachine._POLICY`**: esa es la deriva que `assignment_blocker`
advierte, y aquí se acepta a cambio de que el aviso sea cortesía (R2.2 deja crear igualmente) y de que
R2.3 falle abierto. Queda escrito en el propio módulo y en la spec.

Rejected: (b) crear y leer `assignment_blocked_by` de la fila recién creada — renuncia al «antes de crear» que es todo R2.
Rejected: (c) que el backend publique los estados legales — rompe el «sin backend» del change. Verificado que hoy no hay de dónde leerlo: `GET /properties/{id}/state` (`PropertyStateResponse`) publica exactamente `current_operational_state` y `last_transition_at`, y nada sobre transiciones admitidas.

### D3 — Los cuatro campos nuevos entran en el tipo base `CleaningTask`, no sólo en el ítem de listado

**Chosen:** `completedAt`, `validationStatus` y `validatedAt` se añaden a `CleaningTask` y no a
`CleaningTaskListItem`, porque **las dos respuestas del backend los publican**:
`CleaningTaskResponse` (lo que devuelven crear, validar y cancelar) y `CleaningTaskListItemResponse`
(el listado) los enumeran igual. Un solo `mapTask` los mapea y `mapListItem` sigue añadiendo únicamente
`assignmentBlockedBy`. Así la respuesta de `validateTask` ya trae el veredicto que el backend guardó, y
no hay dos definiciones del mismo campo. `PropertySummary` gana `currentOperationalState` en su propio
mapeador.

Rejected: colgarlos de `CleaningTaskListItem` — obligaría a un segundo tipo para la respuesta de validar y dejaría el veredicto fuera del dato que el servidor acaba de confirmar.

### D4 — La vista posee las tres mutaciones; la región viva sigue siendo una

**Chosen:** `CleaningView` instancia `useCreateCleaningTask`, `useValidateCleaningTask` y
`useCancelCleaningTask`, y `announcement()` pasa de leer una mutación a resolver por **precedencia
explícita** (la que esté `isPending` primero; después el último `isError`; después el último
`isSuccess`), manteniendo un único `role="status" aria-live="polite"` montado desde el primer render
(D11 de la spec vigente, R1.5). El diálogo de cancelar recibe la mutación por props —igual que
`CancelCleaningDialogBody` ya hace hoy— en vez de instanciarla dentro.

**La excepción declarada**: el diálogo de cancelar es un overlay que **permanece abierto tras un
fallo** (precedente y R4.5), así que pinta su mensaje de error `role="alert"` dentro. No es una segunda
región `aria-live="polite"`: es la misma forma que R1.5 ya admite para el fallo dentro de la región
única, aplicada donde está el foco. El éxito lo anuncia la región de la vista después de cerrarse.

Rejected: una región por operación — N sitios que pueden haber hablado, que es lo que D11 de la spec descartó.
Rejected: dejar la mutación de cancelar dentro del diálogo — su resultado no llegaría a la región de la vista.

### D5 — Diálogo de cancelación propio de `features/cleaning`, sin tocar el del dashboard

**Chosen:** `features/cleaning/components/cancel-cleaning-task-dialog.tsx`, un `Sheet` con el mismo
esqueleto que el del dashboard (textarea, `maxLength={500}`, guardia de motivo en blanco, `submittingRef`
contra el doble clic) pero con las claves del namespace `cleaning` y su propio mapeador de error. R4.1
manda reutilizar **`useCancelCleaningTask`**, la mutación —y se reutiliza tal cual, sin duplicarla—, no
el diálogo. Los dos diálogos difieren en cabecera (el del dashboard pinta `trigger` y `blocking_state`
como literales canónicos), en namespace y en vocabulario de error.

La duplicación del formulario (~60 líneas) se acepta y se declara: unificarla exigiría mover las claves
`card.blocked.cancelCleaning.*` al namespace `cleaning` y reescribir tres ficheros de test de
`features/dashboard`, en una capacidad que este change no posee. **Disparador para consolidarlo**: un
tercer consumidor de `cancelTask`.

Rejected: promover el diálogo del dashboard a `features/cleaning` — cambia copy y tests de una feature ajena al alcance.
Rejected: extraer un primitivo compartido a `components/ui/` — el trozo común es un textarea con contador, no un primitivo.

### D6 — Validar son dos botones explícitos en la fila, no un desplegable

**Chosen:** `ValidateCleaningControl` renderiza dos `<button>` —«Validar» (`PASSED`) y «No pasa»
(`FAILED`)— dentro de la tarjeta, visibles cuando `status === "COMPLETED"` y el rol tiene el permiso
(R5.1). No hay `<select>` + confirmar porque el peligro que justificó ese patrón en
`AssignCleanerControl` —un `<select>` recorrido con las flechas dispara `change` en cada opción— no
existe con botones, y con dos veredictos un desplegable añade una interacción sin añadir seguridad.

**El control no desaparece con el primer veredicto** (decisión del gate del 2026-09-05, que enmienda
R3.1): un «No pasa» mal pulsado notifica a una persona, y la remediación es poder corregirlo desde la
misma pantalla, no un paso de confirmación que se pulsa en piloto automático. El backend ya lo admite —
`record_manual_validation` sólo exige `COMPLETED` y rechaza `PENDING` como veredicto; **no** comprueba
el `validation_status` previo—, así que revalidar no estrena ninguna ruta ni relaja ninguna regla.

Lo que sí se cierra es el envío que no cambia nada: **el botón cuyo veredicto ya es el vigente va
deshabilitado**, por la misma razón por la que `AssignCleanerControl` impide reconfirmar a la limpiadora
ya asignada — reenviar `FAILED` volvería a notificar a la limpiadora y a escribir otra fila de
auditoría.

Debajo, un texto estático (no `title`, la vista es mobile-first) advierte de las dos consecuencias
medidas: **`FAILED` notifica a la limpiadora asignada** (`NotificationType.CLEANING_FAILED`) y
**validar no mueve la vivienda** (R3.4 —`ValidateCleaningTaskUseCase` no ejecuta ninguna transición, y
lo dice en un comentario literal—).

Rejected: esconder el control tras el primer veredicto (R3.1 tal como se escribió) — deja un `FAILED` accidental sin remedio desde el producto.
Rejected: confirmación en línea sólo para `FAILED` — protege del misclic pero no del error de juicio, y sigue sin dar vuelta atrás.
Rejected: `<select>` + confirmar — dos interacciones para dos opciones.
Rejected: ofrecer también `WAIVED` — sin semántica declarada en el PRD (`ASSUMPTION` 3 del proposal, fuera de alcance).

### D7 — El campo de validación se pinta donde significa algo

**Chosen:** la fila muestra el `validation_status` vigente y, si existe, `validated_at`, **cuando
`completedAt !== null` o `validationStatus !== "PENDING"`**. Ése es el motivo por el que el proposal
ensancha `completed_at`: pintar «Pendiente de validación» en una tarea `CREATED` que nadie ha limpiado
todavía es ruido que se lee como una tarea atascada. Es un refinamiento de R3.3 —aprobado en el gate
del 2026-09-05 y bajado al proposal—, no una excepción: allí donde el veredicto puede existir se
muestra el vigente, y se muestra **a todos los roles** (R5.2), control o no.

Rejected: pintarlo siempre — «Pendiente» en las nueve filas de una página recién creada.
Rejected: pintarlo sólo en `COMPLETED` — una tarea que pasó a otro estado tras un veredicto perdería el dato.

### D8 — Un mapeador de error nuevo por operación, en una tabla por estado HTTP

**Chosen:** `features/cleaning/lib/manage-error.ts` con un resolvedor `keyForStatus(error, table,
genericKey)` y tres tablas —crear, validar, cancelar—, siguiendo literalmente el patrón de
`assign-error.ts` (R1.4, R3.5, R4.5): la elección la hace el **estado HTTP** y, dentro del `409`, el
`code` del sobre; nunca `ApiError.message`, que es técnico y está en inglés. `assign-error.ts` se deja
intacto: su refinamiento por `code` es específico de la asignación y tocarlo es churn sin beneficio.

Los estados de cada operación, leídos de `backend/app/cleaning/api/errors.py` y de los casos de uso:

| Operación | 403 | 404 | 409 | 422 |
|---|---|---|---|---|
| crear | sin permiso | vivienda inexistente **o** sin plantilla de checklist activa | `AmbiguousChecklistTemplateError` (`CONFLICT`) | cuerpo inválido |
| validar | sin permiso | tarea inexistente | la tarea ya no está `COMPLETED` (`CONFLICT`) | — |
| cancelar | sin permiso | tarea inexistente | terminal (`CONFLICT`) **o** estado de la vivienda (`PROPERTY_STATE_CONFLICT`) | motivo en blanco (imposible desde la UI) |

**El `404` de crear es ambiguo y el mensaje tiene que decirlo.** `CreateCleaningTaskUseCase` lanza
`PropertyNotFoundError` y `resolve_template` lanza `ChecklistTemplateNotFoundError`; las dos filas del
mapeo dan `404` con el **mismo** `ErrorCode.NOT_FOUND`, así que el cliente no puede distinguirlas sin
un cambio de backend. La copia cubre las dos causas en una frase honesta en vez de afirmar la que
suene mejor.

### D9 — El selector de viviendas del formulario reutiliza el catálogo ya cacheado

**Chosen:** `usePropertyDirectory()`, la misma consulta que ya sirve al filtro y a la identidad de cada
fila —una copia cacheada, sin petición nueva—. Hereda el techo declarado de la spec: `per_page: 100`,
así que **a partir de la vivienda 101 del tenant no se puede crear una limpieza desde aquí**, la misma
`ASSUMPTION` que ya degrada la identidad y el filtro. Se hace explícita en la spec, no se descubre.

Rejected: consulta propia paginada para el formulario — un segundo techo distinto del que ya tiene la pantalla.

### D10 — Ninguna de las tres mutaciones reintenta, y todas invalidan el prefijo de tareas

**Chosen:** `retry: false` e invalidación de `cleaningKeys.tasksPrefix(tenantId)` en `onSettled` —en el
fallo también—, igual que `useAssignCleaningTask` (R1.3, R3.2, R4.3). Ninguna actualización optimista:
una creación cambia `total` y `total_pages`, una validación puede sacar la fila del filtro activo y una
cancelación **crea una tarea de reemplazo** que sólo aparece releyendo la página. `useCancelCleaningTask`
no se toca: sus cuatro invalidaciones (incluidas las del dashboard) son inocuas desde `/cleaning`.

### D11 — Los tres controles cuelgan del permiso, no del rol

**Chosen:** `useHasPermission("MANAGE_CLEANING_TASKS")` en los tres sitios (R5.1), como ya hace
`cleaning-task-row.tsx:120`. El botón de crear se calcula una vez en `CleaningView` y los de validar y
cancelar en la fila, junto al `canAssign` que ya existe (se generaliza a un solo `canManage`). Sin el
permiso, la lista y **todos** los datos —`validation_status` incluido— se siguen viendo (R5.2). Es
cortesía y jamás autorización: el backend responde `403` igual (R5.3, `steering/security.md` regla 2).

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| DTO | `frontend/features/cleaning/data/dto.ts` | `CleaningTask` gana `completedAt`, `validationStatus`, `validatedAt`; alias `CleaningValidationStatus` y `CleaningValidationVerdict` (`"PASSED" \| "FAILED"`) y `PropertyOperationalState` desde el contrato generado; `PropertySummary` gana `currentOperationalState`; nuevo `CreateCleaningTaskInput` |
| Frontera de datos | `data/cleaning-source.ts`, `data/http/http-cleaning-source.ts` | Interfaz y HTTP: `createTask`, `validateTask`; `mapTask` y `mapProperty` ensanchados |
| Hooks | **nuevos** `hooks/use-create-cleaning-task.ts`, `hooks/use-validate-cleaning-task.ts` | Mutaciones con `retry: false` e invalidación del prefijo en `onSettled` (D10) |
| Componentes | **nuevos** `components/create-cleaning-task-panel.tsx`, `components/validate-cleaning-control.tsx`, `components/cancel-cleaning-task-dialog.tsx` | Panel de creación (D1), dos botones de veredicto (D6), Sheet de cancelación (D5) |
| Componentes | `components/cleaning-view.tsx` | Barra con el botón de crear, panel desplegable, las tres mutaciones, `announcement()` por precedencia (D4), estado del diálogo de cancelar |
| Componentes | `components/cleaning-task-row.tsx` | `canManage`; campo de validación (D7); controles de validar y cancelar |
| Lib | **nuevos** `lib/assignable-property-state.ts`, `lib/manage-error.ts` | Constante de estados asignables con su aviso de deriva (D2); tablas de error por estado (D8) |
| i18n | `frontend/locales/es/cleaning.json`, `frontend/locales/en/cleaning.json` | Claves nuevas bajo `create.*`, `validate.*`, `cancel.*`, `columns.validation`, `columns.completedAt`, `validation.*`; mismo juego en los dos idiomas |
| Tests | Un fichero junto a cada componente/lib nuevo, más los existentes de `cleaning-view`, `cleaning-task-row`, `http-cleaning-source` y `dto` | Doble de `CleaningDataSource` inyectado, como ya hacen los tests de la capacidad |
| Docs | `docs/cleaning.md` | Sección de operación de las tres acciones nuevas (`steering/documentation.md`, se concreta en `/sdd:tasks`) |
| Spec | `sdd/specs/cleaning-manager-view.md` | La escribe `/sdd:archive`: tres operaciones, aviso de no-asignabilidad, campos nuevos del DTO, techo de 100 viviendas para crear |

## Data & interfaces

**Sin cambios de backend, sin migración y sin regenerar el contrato.** Las tres rutas y los cuatro
campos existen; `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` no se tocan, y por
tanto `sdd/specs/api-contract.md` tampoco.

Lo que se estrena en el frontend, con la forma de cable que ya publica el contrato:

```ts
interface CreateCleaningTaskInput {
  propertyId: string;
  scheduledStart?: string;   // ISO-8601 UTC, desde `datetime-local` con toISOString()
  scheduledEnd?: string;
}
// POST /api/v1/cleaning-tasks  → 201 CleaningTaskResponse
//   body: { property_id, scheduled_start?, scheduled_end? }   ← y ningún campo más (R1.2)
// POST /api/v1/cleaning-tasks/{task_id}/validate → 200 CleaningTaskResponse
//   body: { validation_status: "PASSED" | "FAILED" }
```

`reservation_id` **no se envía nunca** (`ASSUMPTION` 2 del proposal): una limpieza extraordinaria no la
implica ningún checkout y un selector de reservas es superficie nueva. Las dos fechas se leen de dos
`datetime-local` y se convierten con `new Date(value).toISOString()`, el mecanismo exacto de
`etaToInstant` en `features/tech/components/detail/tech-eta-field.tsx`: la hora se interpreta en la zona
del dispositivo y viaja con `Z`. Un campo vacío se omite del cuerpo, no se manda `null`.

## Risks & mitigations

- **La constante de D2 deriva en silencio si la matriz gana una fila.** Mitigación: el aviso es
  cortesía (R2.2 deja crear, R2.3 falla abierto), la deriva queda escrita en el módulo y en la spec, y
  el tipo aliado del contrato hace que un **renombrado** sí rompa el build. Lo que quedaría mal es un
  aviso de más, no un bloqueo.
- **El typecheck de un campo nuevo del DTO rompe sólo en el mapeador** (lo advierte la spec vigente en
  «Key files»): un consumidor anotado con el tipo base compila igual sin leerlo nunca. Mitigación:
  tests de componente con aserciones de DOM sobre el campo de validación, que es lo que cubre ese tramo.
- **Doble envío en el panel de creación.** Mitigación: el `submittingRef` síncrono del precedente
  (`mutation.isPending` sólo cambia en el siguiente commit de React).
- **El `404` ambiguo de crear** (D8) puede mandar al manager a buscar una vivienda que sí existe.
  Mitigación: la copia nombra las dos causas. Distinguirlas exige un `ErrorCode` nuevo en el backend —
  candidato de roadmap, no de este change.
- **Veredicto `FAILED` accidental**: notifica a la limpiadora. Mitigación aprobada en el gate: el
  control sobrevive al primer veredicto y permite corregirlo (D6), con el botón del veredicto vigente
  deshabilitado para que reenviarlo no vuelva a notificar. Lo que **no** se puede deshacer es la
  notificación ya emitida — no hay retracción en `notifications`, y la corrección no manda un aviso
  nuevo porque `ValidateCleaningTaskUseCase` sólo notifica en `FAILED`.
- **La deuda de pasada visual de la spec sigue viva** y este change es su disparador natural: crear una
  limpieza sobre una vivienda en `VACANT_READY` es la forma más barata que ha tenido nunca de fabricar
  el caso «no asignable». Se recoge en Verification de `/sdd:tasks`, no aquí.

## Open questions

Ninguna abierta. Las tres que este diseño levantó se resolvieron en el gate del **2026-09-05**, y las
dos que enmiendan un requisito ya están bajadas a `proposal.md`:

1. **Veredictos y reversibilidad** → **permitir revalidar**. Se ofrecen `PASSED` y `FAILED` (`WAIVED`
   sigue fuera, `ASSUMPTION` 3 confirmada) y el control sobrevive al primer veredicto para poder
   corregir un «No pasa» mal pulsado; el botón del veredicto vigente va deshabilitado. **Enmienda R3.1**
   del proposal, ya aplicada. Se descartó el paso de confirmación sólo para `FAILED`: protege del
   misclic pero no da vuelta atrás.
2. **Propiedad del diálogo de cancelar (D5)** → **uno nuevo en `features/cleaning`**, dashboard
   intacto, con el disparador de consolidación escrito (un tercer consumidor de `cancelTask`). No
   enmienda ningún requisito.
3. **Alcance del campo de validación en la fila (D7)** → **acotado**: se pinta cuando la tarea se ha
   completado alguna vez o ya tiene veredicto. **Enmienda R3.3** del proposal, ya aplicada.
