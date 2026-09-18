# Design: staff-messaging-manager-view

## Context

El backend ya publica `POST/GET /api/v1/incidents/{incident_id}/messages` y `POST/GET /api/v1/cleaning-tasks/{task_id}/messages` ([archive/2026-09-03-staff-messaging](../archive/2026-09-03-staff-messaging/design.md) D2/D3/D6) y `PROPERTY_MANAGER` (con `TENANT_OWNER` como efecto colateral aceptado) ya tiene permisos de lectura y escritura sobre ambos hilos (D3). El frontend ya expone los hooks `useIncidentMessages` / `useSendIncidentMessage` (en `frontend/features/incidents/hooks/use-incident-messages.ts`, exportados desde `frontend/features/incidents/index.ts` desde `staff-messaging-web`) y `useCleanerTaskMessages` / `useSendCleanerTaskMessage` (en `frontend/features/cleaner/hooks/use-cleaner-task-messages.ts`), y ya tiene dos paneles completos reutilizables como referencia: `TechIncidentMessagesPanel` + `TechIncidentTabs` (`frontend/features/tech/components/detail/tech-incident-{messages-panel,tabs}.tsx`) y `CleanerTaskMessagesPanel` + `CleanerTaskTabs` (`frontend/features/cleaner/components/detail/cleaner-task-{messages-panel,tabs}.tsx`).

Lo que falta es **montar** esa superficie en las dos páginas reales del manager: `/incidents/[id]` (existe hoy, renderiza `IncidentDetailView`) y `/cleaning/[id]` (existe desde `cleaning-manager-task-detail`, renderiza `CleaningTaskDetailView`). El recorte que `staff-messaging-web` documentó en su out-of-scope («dar el hilo solo al lado de incidencias del manager crearía una cobertura asimétrica entre sus dos dominios») ya no aplica porque `/cleaning/[id]` ya existe.

Esta entrada NO toca el backend, NO modifica `IncidentDetailView`, NO modifica `TechIncidentDetailView`/`TechIncidentTabs`/`TechIncidentMessagesPanel` ni `CleanerTaskTabs`/`CleanerTaskMessagesPanel`, NO modifica los bloques de lectura de `CleaningTaskDetailView` — replica el patrón «wrapper que compone los mismos bloques con tabs» que ya aplican `TechIncidentDetailView` (compone bloques + tabs) y `CleaningTaskDetailView` (compone bloques, sin tabs hoy). El censo de superficies del App Router (`frontend/app/route-coverage.test.ts`) NO cambia: las dos rutas reales son las mismas.

## Decisions

### D1 — Wrapper del manager para `/incidents/[id]`, no patchwork sobre `IncidentDetailView`

**Chosen:** crear `ManagerIncidentDetailView` (`frontend/features/incidents/components/detail/manager-incident-detail-view.tsx`) que reutiliza los mismos bloques de `incident-detail-sections.tsx` (`DetailHeader`, `DetailIdentifyingBlock`, `DetailAssignedTechnicianBlock`, `DetailDescriptionBlock`, `DetailCostsBlock`, `DetailMetadataBlock`) y `ManagerIncidentActions` que `IncidentDetailView` ya compone hoy, pero los monta como contenido de `ManagerIncidentTabs` (D2) con `ManagerIncidentMessagesPanel` (D3) como segunda pestaña. La página `frontend/app/(workspace)/incidents/[id]/page.tsx` pasa a renderizar el wrapper. `IncidentDetailView` se queda en su sitio y se exporta: su contrato (estado + render del artículo) no cambia.

Rejected: extender `IncidentDetailView` con un slot opcional para envolver el contenido — añade una prop cuya presencia cambia el árbol y cuyo ausencia tiene que recordar el comportamiento viejo; cualquier consumidor futuro (la suite ya cubre el contrato de no-montar-mensajes, D2 de `staff-messaging-web`) tendría que conocer la semántica de la nueva prop.

Rejected: duplicar el contenido de `IncidentDetailView` dentro del wrapper sin pasar por los bloques de `incident-detail-sections.tsx` — sería la segunda fuente de verdad de la composición de bloques y el panel de arquitectura lo cazaría (D1 de `cleaning-manager-task-detail` ya midió los bloques como la frontera correcta).

### D2 — `ManagerIncidentTabs`: copia adaptada de `TechIncidentTabs`, ambos paneles montados

**Chosen:** `ManagerIncidentTabs` (`frontend/features/incidents/components/detail/manager-incident-tabs.tsx`), copia literal del patrón de `TechIncidentTabs` (`frontend/features/tech/components/detail/tech-incident-tabs.tsx`) con los identificadores de DOM y los namespaces i18n cambiados:
- `role="tablist"`, dos botones (`role="tab"`, `aria-selected`, `aria-controls`, roving `tabIndex`), dos paneles (`role="tabpanel"`, `aria-labelledby`, `hidden` para el inactivo).
- Manejo de teclado ←/→/Home/End idéntico.
- `activeTab` arranca en `"content"` (R1.1/R2.1).
- `hasOpenedMessagesTab` sticky: pasa de `false` a `true` la primera vez que el manager toca la pestaña y nunca vuelve (mismo flag que ya consumen `CleanerTaskTabs` y `TechIncidentTabs`).
- IDs de DOM con prefijo `manager-incident-` (`manager-incident-tab-{key}`, `manager-incident-panel-{key}`) para que ningún selector global (`frontend/test/`, capturas de Playwright) confunda los paneles de manager con los de `tech`.
- `useTranslation("incidents")` resuelve las claves `tabs.label` y `tabs.content` (nuevas en `incidents.json`); la clave `messages.tab` la aporta la pestaña, no el wrapper (mismo reparto que en `tech.json`).

Rejected: extraer un `Tabs` genérico a `components/ui/` y reusarlo en las cuatro instancias (manager-incident, manager-cleaning, cleaner, tech) — `staff-messaging-web` design D1 ya rechazó la abstracción prematura dos veces (precedente `reviews-tabs.tsx`/`pricing-tabs.tsx`) por el mismo motivo: añadir un `Tabs` compartido exige reinstalar el `frontend_node_modules` del worktree y reconsidera el contrato ARIA de tres componentes que ya funcionan. El cambio que unifique las cuatro pestañas, si llega, es un change de tipo `tech` aparte, no de esta entrega.

### D3 — `ManagerIncidentMessagesPanel`: copia adaptada de `TechIncidentMessagesPanel`

**Chosen:** `ManagerIncidentMessagesPanel` (`frontend/features/incidents/components/detail/manager-incident-messages-panel.tsx`), copia del patrón de `TechIncidentMessagesPanel` (`frontend/features/tech/components/detail/tech-incident-messages-panel.tsx`):

- `useIncidentMessages(incidentId, page, enabled)` (ya exportado desde `frontend/features/incidents/index.ts`) — la query es perezosa y se activa la primera vez que se abre la pestaña.
- `useSendIncidentMessage(incidentId)` (mismo lugar) — mutación con `onSettled` que invalida `incidentsKeys.messagesPrefix(tenantId, incidentId)` (D5 de `staff-messaging-web`).
- Paginación: `perPage = 20`, página 1 por defecto, orden ascendente (más antiguos primero), botón «Cargar mensajes más recientes» pide `page + 1` y añade al final.
- Composer: `<textarea maxLength={2000}>` nativo, validación local `trim().length` en 1..2000 antes de llamar al backend (R1.3), `disabled` cuando hay error de validación local **o** `mutation.isPending` (mismo predicado `disabled={validationKey !== null || mutation.isPending}` que `TechIncidentMessagesPanel.tsx:191-202`), texto se conserva si el envío falla y se limpia solo en éxito (R1.3, R4.3).
- `MAX_CONTENT = 2000` como constante local (mismo valor que `TechIncidentMessagesPanel`).
- `onNotFound` callback: cuando la query 404a, lo invoca en `useLayoutEffect` para que el wrapper (`ManagerIncidentDetailView`) pueda reemplazar la pantalla completa por el `EmptyState` de «no disponible» en el mismo frame (D5 de `staff-messaging-web`, ya medido en `tech-incident-messages-panel.tsx`).
- i18n namespace: `useTranslation("incidents")` con claves `messages.title`, `messages.tab`, `messages.loading`, `messages.error.{title,description}`, `messages.empty.{title,description}`, `messages.composer.{label,placeholder,counter,send,sending}`, `messages.roles.<ROLE>`, `messages.errors.{required,tooLong,forbidden,notFound,generic}`, `messages.loadNewer` — **mismas claves que `tech.json`**, mismo árbol `messages.*` que el resto de la suite, para que cambiar de pestaña entre manager y `tech` sea predecible.

Rejected: una única `IncidentMessagesPanel` que acepte un parámetro de estilo y se reuse desde `tech` y desde el manager — `staff-messaging-web` design D1 ya rechazó un panel de mensajes compartido entre los dos roles por la misma razón que rechazó un módulo `features/staff-messaging/` (D2): cada rol opera sobre su propia vista y la frontera `tech/` vs `incidents/` (manager) ya está marcada. Mezclar dos consumidores en un solo componente mezcla también dos i18n namespaces (`tech` vs `incidents`) y dos permisos de vista (D3 del design de `staff-messaging` reusaba los mismos permisos pero los dos namespaces i18n se quedaron separados).

Rejected: añadir un parámetro `variant: "manager" | "tech"` que cambie las claves i18n — vuelve a la abstracción rechazada arriba, esta vez en miniatura; el coste del wrapper es menor y el panel local gana el campo de su propia tabla.

### D4 — `ManagerCleaningTaskTabs`: copia adaptada de `CleanerTaskTabs`

**Chosen:** `ManagerCleaningTaskTabs` (`frontend/features/cleaning/components/detail/manager-cleaning-task-tabs.tsx`), copia del patrón de `CleanerTaskTabs` (`frontend/features/cleaner/components/detail/cleaner-task-tabs.tsx`) con los identificadores de DOM cambiados a prefijo `manager-cleaning-` y el namespace i18n a `cleaning` (en vez de `cleaner`). Misma estructura: dos botones, dos paneles con `hidden` para el inactivo, sticky `hasOpenedMessagesTab`, ←/→/Home/End.

Rejected: reusar `CleanerTaskTabs` directamente — comparte `useTranslation("cleaner")`, que no es el namespace del manager. Si el wrapper importa el componente del cleaner, las claves `tabs.label`, `tabs.content` y `messages.tab` se buscan en `locales/{es,en}/cleaner.json` (no en `cleaning.json`), que es donde vive la app de campo. Cambiar el namespace en una prop añade una variante que ya rechazamos para `Tabs` genérico (D2).

### D5 — `ManagerCleaningTaskMessagesPanel`: copia adaptada de `CleanerTaskMessagesPanel`

**Chosen:** `ManagerCleaningTaskMessagesPanel` (`frontend/features/cleaning/components/detail/manager-cleaning-task-messages-panel.tsx`), copia del patrón de `CleanerTaskMessagesPanel` (`frontend/features/cleaner/components/detail/cleaner-task-messages-panel.tsx`):

- `useCleanerTaskMessages(taskId, page, enabled)` y `useSendCleanerTaskMessage(taskId)` (ambos exportados desde `frontend/features/cleaner/hooks/use-cleaner-task-messages.ts`).
- `useTranslation("cleaning")` con las mismas claves `messages.*` que `incidents.json` (D3) — simetría entre las dos vistas del manager, no entre una vista del manager y una del campo.
- `onNotFound` callback hacia `CleaningTaskDetailView` (D6).
- `MAX_CONTENT = 2000` local, misma composición y reglas que el panel de manager de `incidents`.

Rejected: reusar `CleanerTaskMessagesPanel` desde el manager — `useTranslation("cleaner")` busca en `cleaner.json`, no en `cleaning.json`. Misma razón que D4.

### D6 — `CleaningTaskDetailView` gana los tabs sin tocar sus bloques

**Chosen:** `CleaningTaskDetailView` (`frontend/features/cleaning/components/detail/cleaning-task-detail-view.tsx`) conserva intactos sus seis bloques (`DetailHeaderBlock`, `DetailIdentifyingBlock`, `DetailAssignedCleanerBlock`, `DetailContextLinksBlock`, `DetailManagerActionsBlock`, más el bloque de cancelación que cuelga del header), su única región viva `role="status"` y el selector `pickAnnouncementSource` que alimenta las tres mutaciones del manager (`useAssignCleaningTask`, `useValidateCleaningTask`, `useCancelCleaningTask`); esa región viva y ese selector viven en el wrapper, no en `ManagerCleaningTaskTabs` ni en `ManagerCleaningTaskMessagesPanel` — el precedent ya mide esa separación en `cleaning-manager-task-detail` D7 y un implementador que los mueva al panel de mensajes rompería R5.5 del proposal (live region observable para el manager). La única modificación es **estructural**: lo que antes era el `<article>` raíz se compone ahora como el `content` de `ManagerCleaningTaskTabs`, con `ManagerCleaningTaskMessagesPanel` como segunda pestaña. El wrapper del state machine (loading/forbidden/not-found/validation/error → success) se queda arriba, igual que hoy — solo cambia la forma del éxito.

Rejected: extraer los bloques a un sub-componente `CleaningTaskDetailBody` y reusar desde dos vistas (con y sin tabs) — la página Next.js `frontend/app/(workspace)/cleaning/[id]/page.tsx` solo monta `CleaningTaskDetailView`, así que el segundo consumidor no existe. La extracción prematura paga el coste del desacoplo sin amortizarlo.

Rejected: pasar a `CleaningTaskDetailView` una prop `withMessages` que active los tabs — mismo problema que D1: introduce una prop cuya presencia cambia el árbol y cuya ausencia tiene que recordar el comportamiento viejo. El panel de arquitectura del 2026-09-18 midió los bloques como la frontera correcta, no la página.

### D7 — `ManagerIncidentDetailView` reusa los mismos bloques que `IncidentDetailView` ya compone

**Chosen:** `ManagerIncidentDetailView` invoca `useIncident(incidentId)` directamente (mismo hook que `IncidentDetailView`), resuelve `useTechnicianDirectory()` (mismo hook) y monta los bloques `DetailHeader`, `DetailIdentifyingBlock`, `DetailAssignedTechnicianBlock`, `DetailDescriptionBlock`, `DetailCostsBlock`, `DetailMetadataBlock`, `ManagerIncidentActions` en el mismo orden y con las mismas props que `IncidentDetailView`. El state machine (loading/forbidden/not-found/validation/error → success) vive en el wrapper. El éxito renderiza `ManagerIncidentTabs` con el contenido como `content` y `ManagerIncidentMessagesPanel` como `messages` (con `onNotFound` propagando al state machine del wrapper para que un 404 del hilo colapse a «no disponible», mismo convenio que `TechIncidentDetailView`).

Rejected: importar `IncidentDetailView` desde el wrapper y renderizarlo dentro del panel `content` — duplica el state machine (el wrapper tiene que manejar los suyos y los del componente que envuelve), pierde la oportunidad de propagar `onNotFound` del panel de mensajes a un único árbol de estados, y confunde el `useTechnicianDirectory()` que el wrapper ya invoca con el que `IncidentDetailView` también invoca.

### D8 — i18n: clonar `messages.*` desde `tech.json`/`cleaner.json` a `incidents.json`/`cleaning.json`

**Chosen:** añadir las mismas claves `messages.*` (con la misma forma) que ya existen en `frontend/locales/{es,en}/tech.json` y `frontend/locales/{es,en}/cleaner.json` a `frontend/locales/{es,en}/incidents.json` y `frontend/locales/{es,en}/cleaning.json`, en `es/` y `en/` por separado (R4.1). Claves nuevas en cada namespace del manager:

- `tabs.label` y `tabs.content` — la pestaña activa por defecto y el `aria-label` del tablist (mismas que `tech.json`/`cleaner.json`).
- `messages.tab`, `messages.title`, `messages.loading`, `messages.error.{title,description}`, `messages.empty.{title,description}`, `messages.composer.{label,placeholder,counter,send,sending}`, `messages.roles.<ROLE>` con **el mismo conjunto de roles que ya tienen `tech.json`/`cleaner.json`** (incidencias: `TECHNICIAN`/`PROPERTY_MANAGER`/`TENANT_OWNER`; limpiezas: `CLEANER`/`PROPERTY_MANAGER`/`TENANT_OWNER` — el manager no es la única parte del hilo, también lo son el técnico/la limpiadora que lo alimentan desde `/tech/incidents/[id]` y `/cleaner/tasks/[id]`, y la barra de roles del panel los pinta con `t(messages.roles.${message.authorRole})`), `messages.errors.{required,tooLong,forbidden,notFound,generic}`, `messages.loadNewer`.

Rejected: reusar `tech.json`/`cleaner.json` desde los componentes del manager — rompe la regla 11 del proyecto: el namespace i18n es la frontera del feature, y el manager no vive ni en `tech` ni en `cleaner` (vive en `incidents` y `cleaning`). El panel i18n (`sdd-review-i18n`) lo cazaría como cadena en namespace incorrecto.

Rejected: declarar las claves en `common.json` para evitar duplicar entre `incidents.json` y `cleaning.json` — `common.json` ya existe y se usa para cadenas compartidas transversales (estados genéricos, errores de validación de formularios), pero los mensajes del hilo son específicos del dominio (el composer de incidencias y el de limpieza son componentes distintos y pueden divergir, como ya divergen los de `cleaner.json` y `tech.json`).

### D9 — Tests: mismas firmas que `tech-incident-*.test.tsx` y `cleaner-task-*.test.tsx`

**Chosen:** cuatro tests nuevos junto a sus componentes (patrón de los existentes en `frontend/features/{tech,cleaner}/components/detail/`):

- `manager-incident-tabs.test.tsx` — cubre el contrato ARIA (roles, `aria-selected`/`aria-controls`/`aria-labelledby`, `tabIndex` roving), el manejo de teclado (←/→/Home/End), el comportamiento sticky de `hasOpenedMessagesTab` (el panel `messages` se monta una sola vez y no se desmonta al volver), y el `hidden` del panel inactivo (mismas cinco aserciones que `cleaner-task-tabs.test.tsx`).
- `manager-incident-messages-panel.test.tsx` — cubre el flujo de carga paginada (R1.2), el envío válido (R1.3), el envío inválido bloqueado por validación local (R1.3), la persistencia del texto al fallar y el borrado en éxito (R1.3, R4.3), el callback `onNotFound` en `useLayoutEffect` para 404, y la deshabilitación del botón durante `mutation.isPending` (R1.4). Patrón de `tech-incident-messages-panel.test.tsx` (el suite ya está, sólo cambia el namespace i18n y los IDs de los selectores).
- `manager-cleaning-task-tabs.test.tsx` — equivalente al de `cleaner-task-tabs.test.tsx` con los selectores cambiados al prefijo `manager-cleaning-` y los hooks cambiados al namespace `cleaning`.
- `manager-cleaning-task-messages-panel.test.tsx` — equivalente al de `cleaner-task-messages-panel.test.tsx` con la mutación cambiada de `useSendCleanerTaskMessage` (mismo hook hoy, sólo cambia el namespace i18n).

Rejected: tests E2E con Playwright para esta entrada — el suite E2E no está completo todavía (`specs/e2e-testing.md` lo declara pendiente) y los tests unitarios cubren el contrato que el panel del proyecto mide; los hooks de TanStack y los selectores ARIA ya son el camino barato para verificar el flujo del manager sin levantar un navegador.

### D10 — Sin cambios de censo: las dos rutas siguen siendo dos superficies

**Chosen:** el censo de superficies del App Router (`frontend/features/shell/navigation/route-registry.ts` + `frontend/app/route-coverage.test.ts`) queda intacto: `incident-detail` y `cleaning-detail` ya están registradas como `REAL_PAGE_ROUTE_IDS`. La página de incidencias del manager (`frontend/app/(workspace)/incidents/[id]/page.tsx`) solo cambia el componente que monta — sigue siendo la misma `page.tsx`, en la misma ruta, registrada con la misma clave. La página de limpieza del manager no cambia.

Rejected: reescribir las páginas para que el censo se recalcule — el gate `route-surface-counts-have-an-authoritative-source` lee el censo contra `route-registry.ts`/`route-coverage.test.ts`, no contra el árbol de `app/`. Tocar esos ficheros por un cambio que no añade ni quita rutas abre dos fuentes de verdad (la del censo y la del archivo) y el panel de revisión lo cazaría.

## Changes by area

| Area | Files | Change |
|---|---|---|
| incidents barrel | `frontend/features/incidents/index.ts` | + `export { ManagerIncidentDetailView } from "./components/detail/manager-incident-detail-view"` |
| incidents detail | `frontend/features/incidents/components/detail/manager-incident-tabs.tsx` (nuevo) | Tabs ARIA, dos paneles, sticky `hasOpenedMessagesTab` (D2) |
| incidents detail | `frontend/features/incidents/components/detail/manager-incident-messages-panel.tsx` (nuevo) | Lista paginada + composer, `onNotFound` (D3) |
| incidents detail | `frontend/features/incidents/components/detail/manager-incident-detail-view.tsx` (nuevo) | Wrapper: state machine + tabs + bloques de `incident-detail-sections.tsx` (D1, D7) |
| incidents detail tests | `frontend/features/incidents/components/detail/manager-incident-tabs.test.tsx` (nuevo) | ARIA, teclado, sticky, hidden (D9) |
| incidents detail tests | `frontend/features/incidents/components/detail/manager-incident-messages-panel.test.tsx` (nuevo) | Flujo de carga + envío + 404 (D9) |
| incidents page | `frontend/app/(workspace)/incidents/[id]/page.tsx` | Cambia el componente montado de `IncidentDetailView` a `ManagerIncidentDetailView` |
| cleaning detail | `frontend/features/cleaning/components/detail/manager-cleaning-task-tabs.tsx` (nuevo) | Tabs (D4) |
| cleaning detail | `frontend/features/cleaning/components/detail/manager-cleaning-task-messages-panel.tsx` (nuevo) | Panel (D5) |
| cleaning detail | `frontend/features/cleaning/components/detail/cleaning-task-detail-view.tsx` | Estructural: el contenido pasa a ser `content` de `ManagerCleaningTaskTabs`; bloques intactos (D6) |
| cleaning detail tests | `frontend/features/cleaning/components/detail/manager-cleaning-task-tabs.test.tsx` (nuevo) | (D9) |
| cleaning detail tests | `frontend/features/cleaning/components/detail/manager-cleaning-task-messages-panel.test.tsx` (nuevo) | (D9) |
| cleaning barrel | `frontend/features/cleaning/index.ts` | + `export { ManagerCleaningTaskTabs } from "./components/detail/manager-cleaning-task-tabs"` + `export { ManagerCleaningTaskMessagesPanel } from "./components/detail/manager-cleaning-task-messages-panel"` (simetría con la fila del barrel de `incidents`) |
| locales | `frontend/locales/es/incidents.json` + `frontend/locales/en/incidents.json` | + sección `messages.*` + `tabs.{label,content}` (D8) |
| locales | `frontend/locales/es/cleaning.json` + `frontend/locales/en/cleaning.json` | + sección `messages.*` + `tabs.{label,content}` (D8) |

## Data & interfaces

**Sin cambios** en el backend: el contrato de `CleaningTaskMessage`/`IncidentMessage` (`{id, authorId, authorRole, content, createdAt}`) y los endpoints `POST`/`GET /api/v1/{incidents,cleaning-tasks}/{id}/messages` ya están publicados y documentados (`backend/openapi.json`, `sdd/specs/staff-messaging.md`). Las queries y mutaciones del frontend ya existen y se reusan:

- `useIncidentMessages(incidentId, page, enabled)` → `GET /api/v1/incidents/{incident_id}/messages?page=N` (existente).
- `useSendIncidentMessage(incidentId)` → `POST /api/v1/incidents/{incident_id}/messages` (existente).
- `useCleanerTaskMessages(taskId, page, enabled)` → `GET /api/v1/cleaning-tasks/{task_id}/messages?page=N` (existente, nombre del hook `Cleaner*` porque `staff-messaging-web` lo modeló así; semánticamente es de manager también, mismo export).
- `useSendCleanerTaskMessage(taskId)` → `POST /api/v1/cleaning-tasks/{task_id}/messages` (existente, misma observación).

`incidentsKeys.messagesPrefix(tenantId, incidentId)` y `cleanerKeys.messagesPrefix(tenantId, taskId)` ya existen (D3 de `staff-messaging-web`) y son las que la mutación invalida.

## Risks & mitigations

- **Riesgo: `IncidentDetailView` comparte implícitamente el rol con `tech`.** Si en el futuro `TechIncidentDetailView` decide importar `IncidentDetailView` (en vez de componer sus propios bloques), nuestro wrapper ya no sería la única ruta del manager y el censo se rompería. Mitigación: `IncidentDetailView` queda como estaba (no se importa desde el wrapper), y `TechIncidentDetailView` no cambia — el módulo `tech/components/detail/` sigue siendo independiente (D2 de `staff-messaging-web`).
- **Riesgo: el `useHasPermission("MANAGE_INCIDENTS")` que `ManagerIncidentActions` consulta no es el mismo permiso que `READ_INCIDENTS`.** Un `PROPERTY_MANAGER` tiene los dos, pero el panel de acciones se gatea con el primero. Si un `TENANT_OWNER` (que tiene `READ_INCIDENTS` pero no `MANAGE_INCIDENTS`) abre `/incidents/[id]`, el bloque de acciones se oculta. La pestaña "Mensajes" se sigue mostrando porque `useIncidentMessages` solo necesita `READ_INCIDENTS` (R3.3 del proposal: el efecto colateral aceptado en D3 del design de `staff-messaging` lo ampara).
- **Riesgo: la query de mensajes no se cancela al desmontar.** Si el manager navega a otra ruta mientras la query está en vuelo, TanStack Query ya descarta el resultado (su cancellation policy estándar), pero el test `manager-incident-messages-panel.test.tsx` debe ejercitar el path de «el manager hace clic en un enlace y vuelve» para confirmarlo.
- **Riesgo: i18n duplicado entre `incidents.json`/`cleaning.json`.** Mismas claves, dos namespaces — ya es el patrón existente en el resto de los ficheros del manager (cada feature es su propio namespace); no se introduce nada nuevo.
- **Riesgo: las pruebas de `cleaner-task-tabs.test.tsx` y `manager-cleaning-task-tabs.test.tsx` divergen por copiar.** Aceptado: `staff-messaging-web` ya documentó que la abstracción prematura pierde frente a la copia adaptada (D1); un cambio futuro que unifique las cuatro pestañas vivirá como su propio change de tipo `tech`.

## Open questions

Ninguna: las decisiones D1–D10 siguen el precedente directo de `staff-messaging-web` (D1/D2/D3/D5/D6 de su design) y `cleaning-manager-task-detail` (D1 de su design), y los requisitos del proposal ya están cerrados.
