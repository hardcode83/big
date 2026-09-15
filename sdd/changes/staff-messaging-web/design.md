# Design: staff-messaging-web

## Context

`CleanerTaskDetailView` (`frontend/features/cleaner/components/detail/cleaner-task-detail-view.tsx`)
and `TechIncidentDetailView` (`frontend/features/tech/components/detail/tech-incident-detail-view.tsx`)
are the two mobile detail screens this change extends. Each follows the same
data-access pattern: a `*DataSource` interface (`CleanerDataSource` in
`frontend/features/cleaner/data/cleaner-source.ts`, the incidents equivalent in
`frontend/features/incidents/data/`) with a single `Http*Source` implementation
and a single composition-point function (`getCleanerDataSource`/
`getIncidentsDataSource`), tenant-scoped TanStack Query keys
(`cleanerKeys`/`incidentsKeys`), and a `map*Error` helper that turns `ApiError`
into a `{state, messageKey}` pair the view switches on. Crucially,
`frontend/features/incidents/` is **shared**: both the manager's
`/incidents/[id]` page and the tech app's `/tech/incidents/[id]` page import
`IncidentDetailView`/hooks from the same barrel
(`frontend/features/incidents/index.ts`) — only the tech app renders the full
`TechIncidentDetailView`, which itself composes `useIncident`/
`useIncidentContext` from `features/incidents` plus tech-only pieces.

The backend contract (`sdd/changes/archive/2026-09-03-staff-messaging/design.md`)
is closed and already merged: `POST`/`GET /api/v1/cleaning-tasks/{task_id}/messages`
and `POST`/`GET /api/v1/incidents/{incident_id}/messages`, each returning/accepting
`{id, author_id, author_role, content, created_at}`, paginated, chronological
ascending, `content` 1-2000 chars. No backend change is needed here.

Two hand-rolled tab components already exist for the same reason this change
needs one: `frontend/features/pricing/components/pricing-tabs.tsx` and
`frontend/features/reviews/components/reviews-tabs.tsx`, both documented as
"no `Tabs` primitive in `components/ui/`, and adding one means a fresh
dependency plus a reinstall across every worktree's `frontend_node_modules`
volume." The free-text composer (validated length, native `<input>`/`<textarea>`,
submit disabled while pending, error preserving the typed text) has an
almost-exact precedent in
`frontend/features/cleaner/components/detail/cleaner-incident-report-panel.tsx`.

## Decisions

### D-mobile — Pestaña, no sección inline

**Chosen:** el hilo de mensajes vive en una **pestaña** separada de cada
pantalla de detalle, con el checklist/fotos (limpiadora) o el detalle de la
incidencia (técnico) como pestaña activa por defecto. Motivo: ambas pantallas
ya son largas en 360px (`CleanerTaskDetailView` apila 5 bloques,
`TechIncidentDetailView` 4-6 según estado); insertar el hilo como sección
añadiría scroll permanente al flujo que se usa en *cada* apertura de tarea,
mientras que el mensaje del manager es comparativamente infrecuente. El coste
de un tap extra para lo infrecuente es menor que el coste de scroll extra en
lo frecuente — la misma asimetría que ya resolvió R3.

Rejected: sección inline al final de la página (lo que el roadmap señalaba
como alternativa, citando el salto de contexto de una pestaña más en mitad de
una limpieza) — descartada explícitamente por el usuario al invocar este
change: el hilo no es parte de la ejecución de la tarea/incidencia (no bloquea
ni condiciona ninguna acción del ciclo, R-cycle ya cubierto por otros
changes), así que sacarlo del flujo principal no interrumpe una decisión
operativa en curso.

### D1 — Componente de pestañas: copia adaptada de `reviews-tabs.tsx`, **ambos paneles montados**

**Chosen:** `CleanerTaskTabs` (`frontend/features/cleaner/components/detail/cleaner-task-tabs.tsx`)
y `TechIncidentTabs` (`frontend/features/tech/components/detail/tech-incident-tabs.tsx`),
cada uno una copia del patrón de `reviews-tabs.tsx` (mismo `role="tablist"`/
`role="tab"`/`role="tabpanel"`, mismo manejo de teclado ←/→/Home/End), adaptado
a dos claves de pestaña propias (`"content" | "messages"`) en vez de genérico —
**con una divergencia deliberada**: `reviews-tabs.tsx` desmonta el panel
inactivo (`if (key !== activeTab) return null`); aquí **los dos paneles
permanecen montados**, y el inactivo se oculta con `hidden` (atributo HTML,
`display: none`) en vez de desmontarse. R3.2 del proposal exige explícitamente
conservar scroll y estado de formulario de la pestaña de contenido al volver
de mensajes "sin desmontar sus datos ya cargados" — reviews/pricing nunca
tuvieron ese requisito, así que copiar su desmontaje habría violado R3.2 (el
formulario de reporte de incidencia de la limpiadora, `CleanerIncidentReportPanel`,
vive dentro de la pestaña de contenido y tiene estado local — `open`, `title`,
`description` — que un desmontaje borraría).

La query de mensajes, sin embargo, **sigue siendo perezosa**: `enabled` se
activa la primera vez que el usuario toca la pestaña "Mensajes"
(`hasOpenedMessagesTab`, un flag que pasa a `true` una vez y nunca vuelve a
`false`) y permanece activada después — así R1.1/R2.1 ("WHEN el usuario abre
la pestaña... SHALL listar") se cumplen sin disparar la petición antes de que
el usuario la pida, y sin volver a perderla si el usuario alterna de pestaña
tras haberla abierto una vez.

Rejected: desmontar el panel inactivo (precedente literal de `reviews-tabs.tsx`)
— viola R3.2, según el hallazgo del panel de arquitectura de este documento.
Rejected también: extraer un componente `Tabs` genérico a `components/ui/`
reutilizable por las cuatro instancias (pricing, reviews, cleaner, tech) — es
la refactorización correcta a medio plazo pero no la pide ningún requisito de
este change, y el proyecto ya ha tomado la decisión gemela dos veces (pricing,
reviews) de preferir la copia sobre la abstracción prematura; unificarlas es
trabajo de un change de tipo `tech` aparte, no de esta entrega.

### D2 — Capa de datos: extender `CleanerDataSource`, extender el `IncidentsSource` compartido — sin tocar `IncidentDetailView`

**Chosen:** en `cleaning`, añadir `getTaskMessages`/`sendTaskMessage` a
`CleanerDataSource` (`frontend/features/cleaner/data/cleaner-source.ts`) y a
`HttpCleanerSource`. En `incidents`, añadir `getIncidentMessages`/
`sendIncidentMessage` al data source compartido
(`frontend/features/incidents/data/`), porque ese es el módulo del que tech ya
importa `useIncident`/`useIncidentContext` — introducir un segundo data source
paralelo solo para tech duplicaría la resolución de cliente autenticado que
`getIncidentsDataSource` ya centraliza. El hilo queda disponible en el módulo
compartido, pero **solo se monta** en `TechIncidentTabs`/
`TechIncidentDetailView`: `IncidentDetailView` (la vista del manager) no
importa los hooks nuevos, así que el manager no gana superficie con este
change (proposal, Out of scope).

Rejected: un módulo `features/staff-messaging/` nuevo compartido por los dos
dominios — el propio backend rechazó la entidad polimórfica única (D1 del
design de `staff-messaging`) por la misma razón: cada dominio es dueño de su
hilo, y el frontend ya refleja esa frontera (`cleaner` vs `incidents` son
paquetes separados hoy).

### D3 — DTO y query keys

**Chosen:** un tipo `StaffMessage` por dominio (`CleaningTaskMessage` en
`cleaner/data/dto.ts`, `IncidentMessage` en `incidents/data/dto.ts`), forma
idéntica: `{id, authorId, authorRole, content, createdAt}` (camelCase, como el
resto de DTOs — el mapeo snake→camel ya lo hace cada `Http*Source`). Query
keys: `cleanerKeys.messages(tenantId, taskId, page)` e
`incidentsKeys.messages(tenantId, incidentId, page)`, mismo patrón que
`cleanerKeys.photos`/`incidentsKeys.photos` pero parametrizado por página
(D4). `listPrefix`-style helper (`cleanerKeys.messagesPrefix`/
`incidentsKeys.messagesPrefix`) para que la mutación de envío invalide todas
las páginas cacheadas de un hilo, no solo la que estaba abierta.

Rejected: reutilizar una forma `snake_case` cruda del backend en el DTO — rompería
la convención ya establecida en ambos módulos (`CleaningTask`, `Incident`, etc.
son todos camelCase en el DTO).

### D4 — Paginación: por página (20), orden ascendente, "cargar más" hacia delante

**Chosen:** `perPage = 20` (la misma constante que
`cleaner-task-list-view.tsx:33` usa para listas), página 1 por defecto. El
backend ya ordena ascendente-cronológico, así que la página 1 son los
mensajes **más antiguos**; un botón "Cargar mensajes más recientes" pide
`page + 1` y **añade** (no reemplaza) al final de la lista ya mostrada —
consistente con que avanzar de página avanza en el tiempo, nunca hacia atrás.
Sin scroll infinito ni websockets: el volumen esperado de un hilo de
coordinación interna por tarea/incidencia es bajo (task cortas, proposal Out
of scope descarta adjuntos), así que paginar hacia delante con un botón
explícito cubre R1.1/R2.1 sin la complejidad de un visor de chat en tiempo
real.

Rejected: pedir siempre la última página primero (más reciente arriba y scroll
hacia atrás para leer el historial) — invertiría el contrato de orden que el
backend ya fija y complicaría "añadir al final tras enviar" (R1.2/R2.2), que
es el caso que ocurre en cada envío.

### D5 — Mutación de envío: invalidar en `onSettled`, sin parcheo optimista

**Chosen:** `useSendCleaningTaskMessage`/`useSendIncidentMessage` invalidan
`cleanerKeys.messagesPrefix(tenantId, taskId)` /
`incidentsKeys.messagesPrefix(tenantId, incidentId)` en `onSettled`, igual que
`use-cleaner-cycle.ts` documenta para las mutaciones del ciclo ("no debe haber
un instante mostrando una transición que el backend no confirmó"). El nuevo
mensaje aparece al final de la lista tras el refetch que la invalidación
dispara — sin recarga de página (R1.2/R2.2 se satisfacen por SPA/TanStack
Query, no por parcheo local del array).

Rejected: `setQueryData` optimista con el mensaje compuesto localmente —
introduciría una fila con `id`/`created_at` provisionales que habría que
reconciliar si el backend responde con otros valores (recorte de espacios,
por ejemplo), inconsistente con el resto del módulo.

### D6 — Composer: copia adaptada de `cleaner-incident-report-panel.tsx`

**Chosen:** `<textarea maxLength={2000}>` nativo, sin librería de formularios,
con validación local (`trim().length` entre 1 y 2000) que bloquea el envío
antes de llamar al backend (R1.3/R2.3), contador de caracteres visible, label
asociado (`htmlFor`), `disabled` en el botón de envío mientras
`mutation.isPending` (R1.4/R2.4), y el texto escrito **se conserva** si el
envío falla (a diferencia del panel de incidencias, que sí limpia el
formulario en éxito — aquí también se limpia solo en éxito, nunca en error).

Rejected: `sanitize`/recorte de saltos de línea en el cliente — el backend ya
aplica `storable_text("\t\n\r")` (D5 del design de `staff-messaging`); duplicar
la validación de forma exacta en el cliente es solo UX (bloquear antes del
422), no una segunda fuente de verdad del contrato.

## Changes by area

| Area | Files | Change |
|---|---|---|
| `cleaner` data | `frontend/features/cleaner/data/dto.ts` | + `CleaningTaskMessage`, `SendCleaningTaskMessageInput` |
| `cleaner` data | `frontend/features/cleaner/data/cleaner-source.ts`, `http-cleaner-source.ts` | + `getTaskMessages(tenantId, taskId, page)`, `sendTaskMessage(tenantId, taskId, content)` |
| `cleaner` hooks | `frontend/features/cleaner/hooks/query-keys.ts` | + `messages`, `messagesPrefix` |
| `cleaner` hooks | `frontend/features/cleaner/hooks/use-cleaner-tasks.ts` (o nuevo `use-cleaner-task-messages.ts`) | + `useCleanerTaskMessages(taskId, page)` |
| `cleaner` hooks | nuevo `frontend/features/cleaner/hooks/use-send-cleaner-task-message.ts` | + `useSendCleanerTaskMessage(taskId)` |
| `cleaner` components | nuevo `frontend/features/cleaner/components/detail/cleaner-task-messages-panel.tsx` | lista + composer (D4, D6) |
| `cleaner` components | nuevo `frontend/features/cleaner/components/detail/cleaner-task-tabs.tsx` | D1 |
| `cleaner` components | `cleaner-task-detail-view.tsx` | envuelve el contenido actual + el panel de mensajes en `CleanerTaskTabs` |
| `cleaner` lib | `frontend/features/cleaner/lib/error-mapping.ts` | + kinds `"messages"`, `"sendMessage"` |
| `incidents` data | `frontend/features/incidents/data/dto.ts` | + `IncidentMessage`, `SendIncidentMessageInput` |
| `incidents` data | `frontend/features/incidents/data/index.ts`, `http/http-incidents-source.ts` | + `getIncidentMessages`, `sendIncidentMessage` |
| `incidents` hooks | `frontend/features/incidents/hooks/query-keys.ts` | + `messages`, `messagesPrefix` |
| `incidents` hooks | `frontend/features/incidents/hooks/use-incidents.ts` | + `useIncidentMessages(incidentId, page)` |
| `incidents` hooks | nuevo `frontend/features/incidents/hooks/use-send-incident-message.ts` | + `useSendIncidentMessage(incidentId)` |
| `incidents` lib | `frontend/features/incidents/lib/error-mapping.ts` | + kinds `"messages"`, `"sendMessage"` |
| `tech` components | nuevo `frontend/features/tech/components/detail/tech-incident-messages-panel.tsx` | lista + composer, reutiliza los hooks de `incidents` |
| `tech` components | nuevo `frontend/features/tech/components/detail/tech-incident-tabs.tsx` | D1 |
| `tech` components | `tech-incident-detail-view.tsx` | envuelve el contenido actual + el panel de mensajes en `TechIncidentTabs` |
| i18n | `frontend/locales/{es,en}/cleaner.json` | + `messages.*` (pestaña, vacío, error, composer, validaciones) |
| i18n | `frontend/locales/{es,en}/tech.json` | + `messages.*` (mismas claves, namespace propio) |
| specs | `sdd/specs/cleaner-app.md`, `sdd/specs/tech-app.md` | + sección de la pestaña de mensajes |
| specs | `sdd/specs/staff-messaging.md` | nota de alcance del consumo frontend (solo campo, no manager) |

`incidents/index.ts` no cambia sus exports públicos de `IncidentDetailView`
(el manager); solo gana nuevas exportaciones de hooks/tipos que `tech`
consume.

## Data & interfaces

Sin cambios de esquema ni de API — el contrato es el que `staff-messaging`
(backend) ya publicó y documentó. Nuevos tipos, solo en el frontend:

```
CleaningTaskMessage / IncidentMessage:
  id: string
  authorId: string
  authorRole: string
  content: string
  createdAt: string
```

## Risks & mitigations

- **Deriva entre `cleaner` y `tech/incidents`** (mismo shape, dos módulos).
  Mitigación: construir primero el lado `cleaner` completo con sus tests,
  luego el de `incidents`/`tech` como espejo literal — la misma mitigación que
  el backend aplicó para `cleaning`/`maintenance` en su propio design.
- **`incidents` es compartido con el manager.** Un futuro cambio en
  `IncidentDetailView` podría montar sin querer los hooks de mensajes antes de
  que exista una pantalla de manager equivalente para `cleaning`, rompiendo la
  simetría que el Out of scope del proposal declara a propósito. Mitigación:
  el panel/pestaña de mensajes vive en `features/tech/components/`, nunca en
  `features/incidents/components/`, así que `IncidentDetailView` no puede
  importarlo por accidente sin un cambio explícito de import.
- **i18n duplicado entre `cleaner.json` y `tech.json`.** Mismas claves, dos
  namespaces — ya es el patrón existente en el resto de ambos ficheros (cada
  feature es su propio namespace); no se introduce nada nuevo aquí.

## Open questions

Ninguna: D-mobile, alcance (dos pantallas de campo, no manager) y contrato de
backend ya estaban decididos antes de este documento (roadmap note + argumento
de `/sdd:auto` + design de `staff-messaging` archivado).
