# Design: incident-triage-web

## Context

`/incidents/[id]` es hoy una vista de sólo lectura: `frontend/features/incidents/components/detail/incident-detail-view.tsx` compone seis bloques de `incident-detail-sections.tsx` y su docstring lo declara («No mutation controls»). La capa de datos de la feature (`data/http/http-incidents-source.ts`) expone las seis operaciones del técnico más las fotos, y **ninguna** de las cuatro del manager: verificado el 2026-09-05 recorriendo todo `frontend/**/*.ts{,x}` — `/classify`, `/assign` y el `PATCH /incidents/{incident_id}` no aparecen fuera de `lib/api/generated/openapi.d.ts`, y las coincidencias de `/cancel` son de limpieza y del dashboard.

En backend, `Incident._TRANSITIONS` (`backend/app/maintenance/domain/entities.py:203-259`) declara las transiciones **por nombre de operación**; `set_triage` (`:406-431`) anota campos y no transiciona; `TriageIncidentUseCase` (`application/use_cases.py:1525-1606`) escribe un `AuditLog` `INCIDENT_TRIAGED`, notifica severidad y **no escribe ningún `TimelineEvent`** —hoy no lo necesita, porque no mueve el `status`—. `status` ya está en `AUDITABLE_FIELDS["INCIDENT"]` (`audit/domain/value_objects.py:345`), así que el `ChangeSet` puede nombrarlo sin tocar el allowlist.

Los dos patrones que este change copia ya existen y están probados: la tabla `Record<IncidentStatus, …>` de `frontend/features/tech/lib/tech-actions.ts` con su consumidor `tech-cycle-actions.tsx` (incluido el `conflictReason` sobre el estado **refrescado**), y el catálogo de personas de `frontend/features/cleaning` (`listCleaners` sin filtro de `status` + `useCleanerDirectory` + `AssignCleanerControl`, que filtra a los `ACTIVE` en cliente).

## Decisions

### D1 — Una fila nueva en `_TRANSITIONS` llamada `classify_by_triage`, no un ensanche de `classify`

**Chosen:** añadir `"classify_by_triage": (frozenset({IncidentStatus.OPEN}), IncidentStatus.CLASSIFIED)`. La fila es idéntica en orígenes y destino a la de `classify`, y aun así es una fila propia: la tabla está **keyed por operación y no por par** justamente para que dos operaciones que hoy comparten par puedan divergir mañana sin arrastrarse (su propio docstring lo argumenta con `resume_after_approval`, que aparece dos veces). Si algún día `classify` admite re-clasificar una incidencia ya `CLASSIFIED`, la vía humana no debe heredarlo en silencio.

Rejected: reusar la clave `classify` — acopla dos decisiones distintas a una fila y hace que el mensaje de `InvalidIncidentTransitionError` mienta sobre qué se intentaba. Rejected: una excepción fuera de la tabla (mutar `status` en `set_triage` a pelo) — R3.5 lo prohíbe y es exactamente lo que `steering/architecture.md` llama transición fuera del sitio único.

### D2 — La condición vive en `set_triage`, que devuelve `bool`

**Chosen:** `set_triage` termina con la regla «si estaba en `OPEN` y esta llamada trae `category` **y** `severity`, transiciona por `classify_by_triage`» y devuelve `True` en ese caso, `False` en cualquier otro. La regla es de negocio —no un paso de orquestación—, así que `steering/backend-architecture.md` la manda a `domain/`; ponerla en el caso de uso dejaría a cualquier otro llamante del entity sin ella. El único llamante en `app/` es `TriageIncidentUseCase`, y los dos tests que la usan ignoran el retorno sin romperse.

Firma resultante (sin cambios en los parámetros):

```python
def set_triage(self, *, now, category=None, severity=None, estimated_cost=None) -> bool: ...
```

Rejected: un método aparte `classify_by_triage(now)` que el caso de uso llame condicionalmente — devuelve la condición a `application/` y deja abierta la vía de llamar a uno sin el otro. Rejected: que el caso de uso compare `previous_status != incident.status` — indistinguible del salto a `AWAITING_OWNER_APPROVAL` que la puerta de D3 puede añadir en la misma petición.

### D3 — El orden ya vigente (triaje → puerta) es el que hace posible R3.5, y arregla un `409` latente

**Chosen:** no reordenar nada. `TriageIncidentUseCase` ya llama a `set_triage` **antes** de `needs_owner_approval`/`require_owner_approval`, y eso es precisamente lo que hace que la cláusula «IF el mismo triaje abre la puerta, la incidencia acaba en `AWAITING_OWNER_APPROVAL` pasando por `CLASSIFIED`» salga sola: `require_owner_approval` sólo admite `CLASSIFIED` e `IN_PROGRESS` como orígenes.

Efecto colateral que conviene declarar porque nadie lo pidió y aun así cambia: **hoy**, triar una incidencia `OPEN` con un `estimated_cost` por encima del umbral responde `409` (`OPEN` no es origen de `require_owner_approval`). Tras este change, si ese mismo triaje trae además categoría y severidad, responde `200` con `AWAITING_OWNER_APPROVAL`. Si trae **sólo** el coste, sigue dando `409` exactamente como hoy — y ese `409` cae en la rama `out-of-order` de `conflictReason` (R6.1), cuyo texto («el estado ha cambiado y esta acción ya no encaja») describe mal el caso. Se acota en D9.

Rejected: bloquear en el esquema el envío de coste sin categoría+severidad sobre una incidencia `OPEN` — sería una regla que el DTO inventa y que deja a los llamantes no-HTTP fuera.

### D4 — Una fila de auditoría (`INCIDENT_TRIAGED` con el `status` difado) y un evento de timeline (`INCIDENT_CLASSIFIED`)

**Chosen:** el `ChangeSet` de `INCIDENT_TRIAGED` gana `.diff("status", previous_status, incident.status)` —`status` ya es campo auditable, no se toca `AUDITABLE_FIELDS`—, y **sólo cuando `set_triage` devolvió `True`** se escribe además el `TimelineEvent` `INCIDENT_CLASSIFIED`. Una sola fila de auditoría porque la operación que el manager ejecutó es un triaje; una segunda fila `INCIDENT_CLASSIFIED` afirmaría que corrió el clasificador. El actor sale `USER` sin escribir nada: `_record_timeline` pone `TimelineActorType.AI` únicamente cuando `actor is None`, y en este caso de uso el actor es obligatorio. La excepción de actor ausente de `maintenance.md` R9 es de la vía automática y aquí no se invoca.

Rejected: escribir también un `AuditLog` `INCIDENT_CLASSIFIED` — duplica el hecho y confunde al auditor sobre quién decidió la categoría. Rejected: difar `status` siempre (también cuando no cambia) — `ChangeSet` lo permitiría, pero una fila que dice `OPEN → OPEN` es ruido.

### D5 — El triaje que clasifica **sí** dispara el estado de la vivienda, y sólo esa vía

**Chosen** (gate del 2026-09-05, OQ1): cuando `set_triage` devuelve `True`, `TriageIncidentUseCase` llama a `_fire_trigger` con lo que devuelva `_severity_trigger(incident)` —`INCIDENT_HIGH` o `INCIDENT_CRITICAL`, `None` para `MEDIUM`/`LOW`— exactamente como hace `ClassifyIncidentUseCase` en su rama `CLASSIFIED`. Ambos métodos están en `_IncidentTransitionMixin`, que este caso de uso ya hereda, así que no hay colaborador nuevo.

El hueco que cierra, medido: crear una incidencia no dispara ningún trigger (`ReportIncidentUseCase` no llama a `_fire_trigger`) y el clasificador sólo lo dispara al alcanzar `CLASSIFIED`; de modo que **hoy** una incidencia que el clasificador dejó en `OPEN` no lleva la vivienda a `CRITICAL_INCIDENT` ni aunque un humano la marque crítica. El aviso al manager (`_notify_severity`) ya se enviaba desde el triaje; lo que faltaba era el estado operacional. Es justo el camino que R6.6 recorre en dev, así que sin esto la verificación de extremo a extremo dejaría la vivienda en un estado que miente.

Orden dentro del caso de uso: el trigger va **después** de `self._incidents.save(...)`, porque `_fire_trigger` lee la incidencia de vuelta con `list_active_for_property` y su docstring exige que el llamante persista antes.

Rejected: disparar el trigger en todo triaje que suba la severidad, esté donde esté la incidencia — es una decisión más ancha que R3.5, cambia comportamiento existente que nadie ha pedido revisar y merece entrada propia. Rejected: dejarlo fuera por ceñirse a la letra de R3.5 — se enmienda R3.5 en el `proposal.md`, que es más barato que entregar el ciclo con la vivienda en verde y una avería crítica dentro.

### D6 — Tabla estado→acciones del manager en `features/incidents/lib/manager-actions.ts`

**Chosen:** un `Record<IncidentStatus, readonly ManagerAction[]>` congelado sobre el enum del contrato generado, con `Object.hasOwn` en el lector, calcado de `features/tech/lib/tech-actions.ts`. Vive en `features/incidents/lib/` y no en `features/tech/` porque su consumidor es la superficie del manager, y la feature `incidents` es la que ya posee el vocabulario compartido (`conflict-reason.ts`, `severity-tone.ts`).

```ts
export type ManagerAction = "classify" | "assign" | "triage" | "cancel";

const ACTIONS: Record<IncidentStatus, readonly ManagerAction[]> = {
  OPEN:                   ["classify", "triage", "cancel"],
  CLASSIFIED:             ["assign", "triage", "cancel"],
  ASSIGNED:               ["assign", "triage", "cancel"],
  ACCEPTED:               ["assign", "triage", "cancel"],
  IN_PROGRESS:            ["assign", "triage", "cancel"],
  WAITING_EXTERNAL_PARTS: ["assign", "triage", "cancel"],
  AWAITING_OWNER_APPROVAL:["cancel"],
  RESOLVED:               [],
  CANCELLED:              [],
};
```

Junto a ella, `managerStatusNote(status): "awaiting-owner" | null` —el texto de R1.4—, también como `Record` exhaustivo, para que un décimo estado rompa el build en los dos sitios y no sólo en uno. Es presentación del contrato, no autorización (R1.6): el backend refuta con `403`/`409` pase lo que pase.

Rejected: derivar la tabla del `IncidentStatus` con condicionales (`status !== "RESOLVED" && …`) — no es exhaustiva frente al compilador, que es la única propiedad por la que existe la tabla.

### D7 — Cuatro métodos en `HttpIncidentsSource` y **cuatro hooks nombrados**, no un hook con discriminante

**Chosen:** `classifyIncident`, `triageIncident`, `assignIncident`, `cancelIncident` en la fuente HTTP existente (tipados sobre `openapi.d.ts`, mapeando con `mapIncidentDetail`, que ya existe), y cuatro hooks en un fichero nuevo `hooks/use-incident-management.ts`. Cuatro y no uno como `useIncidentCycleAction` porque los cuerpos y las invalidaciones difieren de verdad —`triage` manda hasta tres campos, `assign` dos, las otras dos ninguno, y `cancel` alcanza además al dashboard (D8)—; un discriminante obligaría a un tipo de entrada unión que ninguna pantalla usa entera.

`triageIncident` envía **sólo los campos que cambian** (el esquema es `extra="forbid"` y todo opcional) y manda `estimated_cost` como **string**, que el contrato admite (`anyOf: number | string(pattern .2f)`), por el mismo motivo por el que `final_cost` viaja así: un `round-trip` por `number` corrompe un valor monetario.

Rejected: un módulo `features/users` compartido para el roster — extraerlo movería código de `cleaning` que este change no toca; el catálogo se implementa en `HttpIncidentsSource.listTechnicians` con la **misma forma** que `listCleaners` (`GET /api/v1/users?role=TECHNICIAN&page=1&per_page=100`, sin filtro de `status`, `isActive` derivado en el mapper).

### D8 — Invalidación en `onSettled`, **awaited**, y qué alcanza cada mutación

**Chosen:** las cuatro invalidan `incidentsKeys.detail`, `incidentsKeys.context` y `incidentsKeys.listPrefix`, con `retry: false` y sin actualización optimista. `cancel` invalida además el bucket del dashboard, con las mismas claves literales que `use-resolve-incident.ts` ya reproduce (`blocked-transitions`, `dashboard-cards`, `property-timeline`) y por la misma razón documentada allí: `features/incidents` no importa la fábrica de claves del dashboard.

La invalidación se **espera** (`await`) dentro de `onSettled`, no se descarta con `void`. Es la lección medida en `use-incident-cycle.ts`: `conflictReason` lee el `status` ya refrescado, y con una invalidación descartada el primer render del error usa el estado viejo y enseña la razón equivocada durante un viaje completo.

Rejected: invalidar sólo en `onSuccess` — R6.1 exige refrescar **también en el fallo**, que es lo que hace explicable el `409`.

### D9 — Errores: `conflictReason` para el `409`, mensaje propio para el `422` de `assign`, ocultar en `403`

**Chosen:** una función `managerActionMessage(error, status, action)` en `features/incidents/lib/`, con la forma de `messageFor` en `tech-cycle-actions.tsx`:

- `409` → `conflictReason(statusRefrescado)` → tres claves localizadas. **Con un matiz nuevo**: cuando la acción es `triage`, el estado refrescado es `OPEN` y la razón sale `out-of-order`, el mensaje es el de D3 —«hay que fijar categoría y severidad antes de presupuestar»— y no el genérico, porque ése es el único `409` que este change puede producir sobre una incidencia que **no** ha cambiado de estado. Sin ese caso, el texto de `out-of-order` («el estado ha cambiado») sería falso.
- `422` en `assign` → clave propia (`InvalidTechnicianError`: no es `TECHNICIAN` `ACTIVE` del tenant), nunca el `message` del sobre.
- `422` en `triage` → clave propia de validación del coste (la guarda de cliente lo hace improbable, no imposible).
- `403` → la sección de acciones se oculta y se muestra el texto de «sin permiso» que el detalle ya usa (`incidents:fields.forbidden`). `401` no tiene variante: lo lleva el flujo de expiración de sesión del cliente autenticado.

Rejected: renderizar `error.message` — R6.1/R6.2 lo prohíben y los tres `409` comparten `code: "CONFLICT"`.

### D10 — El nombre del técnico se resuelve contra el roster; la pantalla **no** consume `/context`

**Chosen:** `DetailAssignedTechnicianBlock` pasa a recibir el nombre ya resuelto (`technicianName: string | null`) y el UUID deja de imprimirse; la vista lo resuelve con `useTechnicianDirectory()` y muestra el texto localizado «no disponible» si el roster no lo contiene o la consulta falla. **Para todo el que abra la pantalla, no sólo para el manager** (gate del 2026-09-05, OQ2): el `TENANT_OWNER` —el único otro rol con perfil `workspace`— tiene `READ_USERS` por `_USER_MANAGE`, así que la resolución funciona, y el «exactamente como hoy» de R1.2 se lee como lo que su segunda mitad dice, sin controles de mutación ni hueco reservado, no como un compromiso de dejar el UUID a la vista. Los inactivos **sí** resuelven nombre (por eso el catálogo va sin filtro de `status`) aunque no sean seleccionables — el mismo criterio que `cleaning` D4.

La pantalla **no** llama a `GET /incidents/{id}/context`, aunque el manager tenga permiso: esa respuesta lleva `properties.access_notes`, un sumidero de la regla 11 con excepción propia, y pintarlo en una pantalla de workspace por primera vez es superficie que R2 no pide. El aviso de R2.2 sobre la nota y la ETA que se pierden al reasignar es **texto estático localizado**, no una lectura de la nota vigente.

Rejected: mostrar la nota de la asignación en vigor en el diálogo de reasignación — es útil y cuesta un lector nuevo de `access_notes`; si se quiere, es entrada propia.

### D11 — Guardas de cliente: coste y nota, cada una con su fichero y su test

**Chosen:**

- **Coste**: se **extrae** `POSITIVE_DECIMAL` de `features/dashboard/stalls/components/resolve-incident-dialog.tsx` a `features/incidents/lib/cost-format.ts` (`isPositiveDecimal(value): boolean`), se exporta por el barrel de `incidents` y el diálogo del dashboard pasa a importarlo. Ese diálogo ya importa `useResolveIncident` de `@/features/incidents`, así que no estrena acoplamiento — y R6 existe para no estrenar una tercera forma de hacer lo mismo, no para tener dos.
- **Nota de asignación**: `hasControlCharacters(value)` en `features/incidents/lib/assignment-note.ts`, `/[\u0000-\u0008\u000B-\u001F]/` (todo `U+0000`–`U+001F` salvo tabulador `U+0009` y salto de línea `U+000A`), más el tope de 2000 caracteres que el contrato declara. Es una acotación del síntoma, no la corrección: `incidents.assignment_note` sigue sin pasar por `app/core/storable_text.py` en backend y eso es de la entrada `assignment-note-storable-text`.

Rejected: copiar la expresión del coste a un tercer fichero — es literalmente lo que R6 prohíbe.

### D12 — La descripción del `PATCH` se actualiza y el contrato se regenera

**Chosen:** la `description` de `PATCH /incidents/{incident_id}` pasa a decir que un triaje que fija categoría **y** severidad sobre una incidencia `OPEN` la clasifica. El esquema no cambia; el fichero sí, así que hay que regenerar **las dos mitades del puente** (`steering/documentation.md`): `make openapi` y el artefacto derivado del frontend. En worktree, `make openapi` funciona tal cual (`run --rm --no-deps`); `npm run api:generate` necesita el rodeo documentado en `sdd/project.md` §Worktree bootstrap.

Rejected: dejar la descripción como está para no tocar el contrato — una ruta cuya documentación publicada no describe lo que hace es la deriva que el workflow `api-contract` existe para no tener.

### D13 — Composición de la UI: una sección, tres `Sheet` y un botón

**Chosen:** un componente `ManagerIncidentActions({ incident })` en `features/incidents/components/detail/`, montado por `IncidentDetailView` **sólo** si `useHasPermission("MANAGE_INCIDENTS")` (R1.1/R1.2: sin permiso no se renderiza ni un hueco). Dentro, con la forma de `TechCycleActions`:

- `classify` → botón directo (sin cuerpo).
- `assign` → `Sheet` con `<select>` nativo de técnicos `ACTIVE` + `<textarea>` de nota, botón de confirmación explícito (un `<select>` recorrido con flechas dispara `change` en cada opción; el precedente de `AssignCleanerControl` lo argumenta). Sin preselección, y etiqueta «reasignar» + aviso de R2.2 cuando ya hay asignatario.
- `triage` → `Sheet` con categoría, severidad y coste, **precargados** con los valores actuales, enviando sólo lo que cambió.
- `cancel` → `AlertDialog` (`components/ui/alert-dialog.tsx` ya existe) nombrando la consecuencia; sin motivo, que el contrato no tiene.

El espejo `ROLE_UI_PERMISSIONS` de `frontend/lib/auth/permissions.ts` gana `"MANAGE_INCIDENTS"` en la unión `Permission` y en la fila de `PROPERTY_MANAGER`, y **en ninguna otra** — copiado de `ROLE_PERMISSIONS` de `backend/app/auth/domain/policy.py`, medido: sólo `_INCIDENT_MANAGE` lo trae y sólo `PROPERTY_MANAGER` lo tiene; el `TENANT_OWNER` se queda con `_INCIDENT_READ`.

Rejected: un `Sheet` único con pestañas — tres formularios distintos con tres validaciones distintas metidos en un contenedor que oculta cuál está activo.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dominio maintenance | `backend/app/maintenance/domain/entities.py` | Fila `classify_by_triage` en `_TRANSITIONS`; `set_triage` transiciona cuando procede y devuelve `bool` (D1, D2) |
| Aplicación maintenance | `backend/app/maintenance/application/use_cases.py` | `TriageIncidentUseCase`: captura `previous_status`, difa `status`, escribe `INCIDENT_CLASSIFIED` en el timeline y dispara `_severity_trigger`/`_fire_trigger` (tras el `save`) cuando `set_triage` devuelve `True` (D4, D5) |
| API maintenance | `backend/app/maintenance/api/incidents_router.py` | `description` del `PATCH` (D12) |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regeneración por D12 |
| Tests backend | `backend/tests/maintenance/test_entities.py`, `test_use_cases.py`, `test_incidents_api.py` | Dominio (los dos campos → `CLASSIFIED`; uno solo → `OPEN`), caso de uso (audit con `status`, timeline `INCIDENT_CLASSIFIED` con actor `USER`, disparo de vivienda en `CRITICAL` y **ausencia** de disparo en `MEDIUM`, doble salto a `AWAITING_OWNER_APPROVAL`), API (200 + aislamiento por tenant) — R3.6 |
| Datos frontend | `frontend/features/incidents/data/http/http-incidents-source.ts`, `data/dto.ts` | `classifyIncident`, `triageIncident`, `assignIncident`, `cancelIncident`, `listTechnicians`; DTO `TechnicianSummary` (D7) |
| Hooks frontend | `frontend/features/incidents/hooks/use-incident-management.ts` *(nuevo)*, `hooks/query-keys.ts`, `index.ts` | Cuatro hooks de mutación + `useTechnicianDirectory`; clave `incidentsKeys.technicians` (D7, D8) |
| Lógica de presentación | `frontend/features/incidents/lib/manager-actions.ts` *(nuevo)*, `lib/manager-action-error.ts` *(nuevo)*, `lib/cost-format.ts` *(nuevo)*, `lib/assignment-note.ts` *(nuevo)* | Tabla estado→acciones, mapeo de errores, guardas de cliente (D6, D9, D11) |
| UI frontend | `frontend/features/incidents/components/detail/manager-incident-actions.tsx` *(nuevo)* + tres diálogos, `incident-detail-view.tsx`, `incident-detail-sections.tsx` | Sección de acciones gateada por permiso; nombre del técnico en vez del UUID (D10, D13) |
| Permisos frontend | `frontend/lib/auth/permissions.ts` | Fila `MANAGE_INCIDENTS` en el espejo (D13) |
| Reutilización | `frontend/features/dashboard/stalls/components/resolve-incident-dialog.tsx` | Importa `isPositiveDecimal` en vez de declarar la expresión (D11) |
| i18n | `frontend/locales/{es,en}/incidents.json` | Acciones, notas de estado, tres razones de `409`, `422` de técnico, validaciones, «técnico no disponible» (R6.4) |
| Documentación | `docs/maintenance.md`, `docs/diagrams/` | Cómo se opera el triaje desde la web; **se regenera** `docs/diagrams/2026-08-23_autohost-secuencia-mantenimiento.png` (gate OQ3): es un paso nuevo del ciclo —origen `OPEN`, destino `CLASSIFIED`, ruta `PATCH /incidents/{id}`, evento `INCIDENT_CLASSIFIED`— por el criterio de `steering/architecture.md`. Se genera con `sdd:diagram` **sin abrir el PNG anterior** (cuesta ~140k de contexto), derivando el contenido de `_TRANSITIONS` y los casos de uso; el obsoleto se borra |

## Data & interfaces

- **Esquema de base de datos**: ninguno. Sin migración de Alembic, sin columnas nuevas, sin entidades nuevas.
- **`AUDITABLE_FIELDS`**: sin cambios; `status` ya está declarado para `INCIDENT`.
- **Censo de la regla 11**: sin fila nueva y sin escritor nuevo. `incidents.assignment_note` la sigue escribiendo un `PROPERTY_MANAGER` autenticado al asignar, con el mismo contrato y la misma audiencia; lo único que cambia es que ahora lo teclea en un navegador en vez de en un `curl`. El diseño evita deliberadamente estrenar un lector de `properties.access_notes` (D10).
- **Estado operacional de la vivienda**: un triaje que clasifica con severidad `HIGH`/`CRITICAL` pasa a pedirle a `PropertyStateMachine` que recomponga el estado (D5). No se añade ningún trigger al vocabulario: `INCIDENT_HIGH` e `INCIDENT_CRITICAL` ya existen y son los que dispara la vía automática.
- **Contrato HTTP**: sin rutas nuevas, sin campos nuevos, sin códigos de estado nuevos. Sólo cambia la `description` del `PATCH` (D12). Lo que sí cambia es el **comportamiento observable** de esa ruta: un cuerpo con `category` + `severity` sobre una incidencia `OPEN` devuelve ahora `CLASSIFIED` (o `AWAITING_OWNER_APPROVAL` si además abre la puerta), donde antes devolvía `OPEN`.
- **Permisos**: ninguno nuevo, en backend ni en frontend. `MANAGE_INCIDENTS` y `READ_USERS` existen y el `PROPERTY_MANAGER` los tiene.
- **Variables de entorno**: ninguna.
- **Claves de consulta nuevas**: `incidentsKeys.technicians(tenantId)` → `['tenant', <id>, 'incidents-technicians']`.

## Risks & mitigations

- **El `409` que R3.4 no cubre.** Triar sólo con coste, por encima del umbral, sobre una incidencia `OPEN` sigue dando `409` y el texto genérico de `out-of-order` lo describiría mal. Mitigado en D9 con un caso explícito, y cubierto por el test de componente que R6.5 exige para los caminos del `409`.
- **La regeneración del contrato en worktree.** `npm run api:check` literal no funciona aquí (`sdd/project.md`). Mitigado: `make openapi` sí, y para el artefacto del frontend se usa el rodeo documentado; la comprobación real la hace el workflow `frontend-api-contract` en el PR.
- **`npm test` de partida trae dos ficheros en rojo ajenos al change** (`features/provenance/workflow-contract.test.ts`, `lib/config/build-identity-contract.test.ts`) por `ENOENT`. Mitigado: aplicar los `docker compose cp` de `sdd/project.md` y **medir** la cifra de partida antes de tocar nada, no compararla con ningún número escrito.
- **Roster truncado a 100.** `per_page: 100` como en `cleaning`. Un tenant con más de cien técnicos vería el roster incompleto; el MVP tiene dos viviendas y el riesgo es teórico, pero la limitación se hereda tal cual en vez de inventar paginación en un `<select>`.
- **Regresión silenciosa del triaje existente.** `set_triage` cambia de firma (retorno) y de comportamiento condicional. Mitigado: el caso negativo (un solo campo → sigue `OPEN`) es requisito explícito (R3.5, R3.6) y va con test de dominio propio.
- **Contaminación entre superficies.** Las cuatro mutaciones invalidan `incidentsKeys.context`, que `/tech` comparte. Es deliberado (R2.4) y no hay ninguna escritura optimista que pueda pintar un estado que el backend no confirmó.

## Open questions

Ninguna abierta. Las tres que este diseño levantó se resolvieron en el gate del 2026-09-05, con la
recomendación en los tres casos, y sus enmiendas ya están bajadas a `proposal.md` (regla: una OQ que
enmienda un requisito y no llega al proposal acaba como `SHALL` falso en la spec viva).

| OQ | Decisión | Dónde vive |
|---|---|---|
| ¿El triaje que clasifica dispara el estado de la vivienda? | **Sí, acotado a la vía `classify_by_triage`** | D5; R3.5 del `proposal.md` enmendado |
| ¿El `TENANT_OWNER` ve el nombre del técnico o el UUID? | **El nombre, como todo el que abra la pantalla** | D10; R1.2 y R2.6 del `proposal.md` matizados |
| ¿Se regenera el diagrama de secuencia de mantenimiento? | **Sí**, como tarea explícita | «Changes by area»; `/sdd:tasks` la escribe |
