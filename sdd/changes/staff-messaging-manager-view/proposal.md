# Proposal: staff-messaging-manager-view

## Why

`staff-messaging-web` ([archive/2026-09-17](../archive/2026-09-17-staff-messaging-web/proposal.md)) entregó la pestaña "Mensajes" en **/cleaner/tasks/[id]** y **/tech/incidents/[id]** pero **excluyó deliberadamente** la vista del manager sobre esos mismos hilos:

> *«El backend ya autoriza a `PROPERTY_MANAGER` a leer y escribir ambos hilos (D3 de `staff-messaging`/design.md), pero esta entrega se recorta explícitamente a las dos pantallas móviles que ya existen como página real para los roles de campo — `/cleaner/tasks/[id]` y `/tech/incidents/[id]`. El manager no tiene hoy una página de detalle de tarea de limpieza (`/incidents/[id]` sí existe y es real, pero su contraparte de `cleaning` no), así que dar el hilo solo al lado de incidencias del manager crearía una cobertura asimétrica entre sus dos dominios.»*

La razón principal del recorte era la asimetría: hoy `/cleaning/[id]` no existía y dárselo solo a `incidents` del manager dejaba a `cleaning` sin contraparte. `cleaning-manager-task-detail` ([archive/2026-09-18](../archive/2026-09-18-cleaning-manager-task-detail/proposal.md), archivado el mismo día que se promueve esta entrada) cierra ese hueco entregando la página de detalle de tarea para el manager. Con ambas páginas existentes, **la condición que bloqueó el recorte se ha cumplido**: dar la pestaña "Mensajes" al manager sobre `/cleaning/[id]` y `/incidents/[id]` ya no introduce cobertura asimétrica entre los dos dominios.

El backend ya autoriza a `PROPERTY_MANAGER` (y `TENANT_OWNER` como efecto colateral aceptado en D3 del design de `staff-messaging`) a leer y escribir ambos hilos. Las queries, mutaciones, DTOs y query keys ya existen en `features/incidents/hooks/use-incident-messages.ts` (exportado desde `features/incidents/index.ts` desde `staff-messaging-web`) y en `features/cleaner/hooks/use-cleaner-task-messages.ts`. El trabajo de esta entrada es **montar** esa superficie en las dos páginas reales del manager, no añadir nada de fondo.

## What changes

El manager abre `/incidents/[id]` o `/cleaning/[id]`, encuentra una segunda pestaña **"Mensajes"** además del contenido existente, y al abrirla ve el historial cronológico del hilo (paginado hacia delante desde el más antiguo) y puede enviar un mensaje nuevo con el mismo composer validado (1..2000 chars). El contenido existente del detalle no se mueve ni se altera — el coste de un tap extra al hilo es coherente con la asimetría que ya resolvió `staff-messaging-web` para los roles de campo (R3 de su proposal: la pestaña es separada, no inline al final, porque el hilo es comparativamente infrecuente y no debe añadir scroll permanente al flujo principal).

Estructura de cada vista:

- **`/incidents/[id]`** — `IncidentDetailView` (compartido con `tech`) gana un envoltorio `ManagerIncidentDetailView` que compone `ManagerIncidentTabs` con dos paneles: el contenido actual (encabezado, identificación, técnico asignado, descripción, costes, metadata, acciones del manager) y `ManagerIncidentMessagesPanel` (lista + composer). `IncidentDetailView` no se importa por el nuevo wrapper — la vista tech sigue montando la suya (`TechIncidentDetailView`). Esto preserva la frontera del design de `staff-messaging-web` (D2): el módulo compartido `features/incidents/` expone los hooks de mensajes, pero cada dominio (`tech`, manager) los monta en su propia variante de tabs. La página `frontend/app/(workspace)/incidents/[id]/page.tsx` pasa a montar el wrapper del manager.
- **`/cleaning/[id]`** — `CleaningTaskDetailView` se refactoriza para que la composición por bloques de lectura pase a ser el contenido de la pestaña "Tarea" de un nuevo `ManagerCleaningTaskTabs`, con `ManagerCleaningTaskMessagesPanel` como segunda pestaña. La página `frontend/app/(workspace)/cleaning/[id]/page.tsx` no cambia (sigue montando `CleaningTaskDetailView`).

i18n: cada namespace existente (`incidents.json`, `cleaning.json`) gana una sección `messages.*` con las mismas claves que `tech.json` y `cleaner.json` ya usan, en `es/` y `en/` — sin cadenas incrustadas, simetría con lo que ya se hace en los dos namespaces de campo.

## Requirements

### R1 — Pestaña "Mensajes" en `/incidents/[id]` para el manager

**As a** `PROPERTY_MANAGER`, **I want** abrir la pestaña "Mensajes" en `/incidents/[id]`, **so that** lea y responda el hilo de coordinación con el técnico asignado sin salir de la página de detalle.

Acceptance criteria:

1. WHEN un usuario autenticado con `READ_INCIDENTS` navega a `/incidents/[id]`, THE SYSTEM SHALL mostrar dos pestañas dentro de la página: **"Tarea"** (contenido actual, activa por defecto) y **"Mensajes"**, separadas por un tablist accesible (`role="tablist"` / `role="tab"` / `role="tabpanel"`, ←/→/Home/End, roving tabIndex) siguiendo el patrón de `TechIncidentTabs` (`frontend/features/tech/components/detail/tech-incident-tabs.tsx`) y `CleanerTaskTabs`.
2. WHEN el manager selecciona la pestaña "Mensajes" por primera vez, THE SYSTEM SHALL cargar y mostrar el historial del hilo paginado (página 1 = más antiguos, 20 por página, ascendente cronológico) usando `useIncidentMessages(incidentId, page, enabled)`; WHERE ya la había abierto antes, THE SYSTEM SHALL no relanzar la petición al alternar pestañas.
3. WHEN el manager envía un mensaje válido (1..2000 caracteres tras `trim()`) desde el composer, THE SYSTEM SHALL hacer `POST /api/v1/incidents/{incident_id}/messages` con `useSendIncidentMessage`, invalidar `incidentsKeys.messagesPrefix(tenantId, incidentId)` en `onSettled`, y mostrar el mensaje enviado al final del hilo tras el refetch; el texto del composer SHALL persistir si el envío falla y SHALL limpiarse solo en éxito.
4. WHILE una petición de envío está en vuelo, THE SYSTEM SHALL deshabilitar el botón de envío y mostrar la etiqueta "Enviando…" (clave `messages.composer.sending`) en `frontend/locales/{es,en}/incidents.json`.
5. IF la petición de envío falla por validación (`422` contenido > 2000), THEN THE SYSTEM SHALL mostrar `t("messages.errors.tooLong")` cerca del composer sin recargar la página; IF falla por `404` (incidencia desaparecida), THEN THE SYSTEM SHALL reemplazar la pantalla completa con el mismo `EmptyState` "no disponible" que el resto de lecturas paralelas del detalle (mismo convenio que `TechIncidentMessagesPanel` con `onNotFound`); IF falla por cualquier otro motivo, THEN THE SYSTEM SHALL mostrar `t("messages.errors.generic")`.

### R2 — Pestaña "Mensajes" en `/cleaning/[id]` para el manager

**As a** `PROPERTY_MANAGER`, **I want** abrir la pestaña "Mensajes" en `/cleaning/[id]`, **so that** lea y responda el hilo de coordinación con la limpiadora asignada sin salir de la página de detalle.

Acceptance criteria:

1. WHEN un usuario autenticado con `READ_CLEANING_TASKS` navega a `/cleaning/[id]`, THE SYSTEM SHALL mostrar dos pestañas dentro de la página: **"Tarea"** (contenido actual, activa por defecto) y **"Mensajes"**, con el mismo contrato ARIA y patrón de teclado que R1.1.
2. WHEN el manager selecciona la pestaña "Mensajes" por primera vez, THE SYSTEM SHALL cargar y mostrar el historial del hilo paginado (mismo criterio que R1.2: página 1 = más antiguos, 20 por página, ascendente) usando `useCleanerTaskMessages(taskId, page, enabled)` (las queries de limpieza ya exportan `messages` con esta forma desde `features/cleaner/hooks/query-keys.ts`); WHERE ya la había abierto antes, THE SYSTEM SHALL no relanzar la petición al alternar pestañas.
3. WHEN el manager envía un mensaje válido (1..2000 caracteres tras `trim()`), THE SYSTEM SHALL hacer `POST /api/v1/cleaning-tasks/{task_id}/messages` con `useSendCleanerTaskMessage`, invalidar `cleanerKeys.messagesPrefix(tenantId, taskId)` en `onSettled`, y mostrar el mensaje enviado al final del hilo tras el refetch; el composer SHALL seguir las mismas reglas de persistencia y borrado que R1.3.
4. WHILE una petición de envío está en vuelo, THE SYSTEM SHALL deshabilitar el botón de envío y mostrar la etiqueta "Enviando…" en `frontend/locales/{es,en}/cleaning.json`.
5. IF la petición de envío falla por validación (`422`), THEN THE SYSTEM SHALL mostrar `t("messages.errors.tooLong")`; IF falla por `404` (tarea desaparecida), THEN THE SYSTEM SHALL reemplazar la pantalla completa con el `EmptyState` "no disponible"; IF falla por cualquier otro motivo, THEN THE SYSTEM SHALL mostrar `t("messages.errors.generic")`.

### R3 — Simetría con los roles de campo y preservación de su comportamiento

**As a** manager que también usa el móvil para revisar tareas, **I want** que el comportamiento de la pestaña sea indistinguible del de `/tech/incidents/[id]` y `/cleaner/tasks/[id]`, **so that** la cobertura entre dominios (incidencias/limpiezas) y entre roles (manager/campo) sea simétrica y no me tenga que reaprender la pantalla.

Acceptance criteria:

1. THE SYSTEM SHALL implementar la pestaña de manager como una **copia adaptada** de `TechIncidentTabs`/`TechIncidentMessagesPanel` y de `CleanerTaskTabs`/`CleanerTaskMessagesPanel` respectivamente (mismo ARIA, misma paginación, misma mutación por invalidación, mismo composer, mismas etiquetas i18n con la misma forma — `messages.tab`, `messages.title`, `messages.composer.*`, `messages.errors.*`), y NO introducir un componente `Tabs` genérico ni un panel de mensajes compartido entre los cuatro sitios — `staff-messaging-web` design D1 ya rechazó la abstracción prematura dos veces y el design de `staff-messaging` D1 del backend rechazó la entidad polimórfica única por la misma razón.
2. THE SYSTEM SHALL **NO** modificar `IncidentDetailView` (compartido con `tech`), `TechIncidentDetailView`, `TechIncidentTabs`, `TechIncidentMessagesPanel`, `CleanerTaskTabs`, `CleanerTaskMessagesPanel` ni `CleaningTaskDetailView`'s bloques de lectura — solo añadir el wrapper de manager y el panel de manager encima, conservando el contenido existente exactamente como está.
3. WHERE `TENANT_OWNER` (que tiene `READ_CLEANING_TASKS` y `READ_INCIDENTS` vía `_CLEANING_READ`/`_INCIDENT_READ`) abre las dos pestañas, THE SYSTEM SHALL mostrar el mismo contenido que para `PROPERTY_MANAGER` — el efecto colateral aceptado en D3 del design de `staff-messaging` es la fuente de verdad.
4. THE SYSTEM SHALL NO mostrar la pestaña "Mensajes" a `TECHNICIAN` ni a `CLEANER` desde estas rutas — sus pantallas de detalle son `/tech/incidents/[id]` y `/cleaner/tasks/[id]`, que esta entrada no toca. La pestaña se monta siempre que el viewer tenga los permisos de lectura (R1/R2), sin gate adicional por rol: `PROPERTY_MANAGER` y `TENANT_OWNER` son los únicos que llegan a estas rutas hoy.

### R4 — i18n en `es` y `en`, sin cadenas incrustadas

**As a** propietaria que opera desde el móvil, **I want** la pestaña en mi idioma y operable en 320 px, **so that** revise hilos sin abrir el portátil.

Acceptance criteria:

1. THE SYSTEM SHALL declarar toda cadena visible nueva (etiquetas de pestaña, títulos, copy del composer, contador, placeholders, errores, etiqueta de envío en vuelo) en `frontend/locales/es/incidents.json` y `frontend/locales/en/incidents.json` para R1, y en `frontend/locales/es/cleaning.json` y `frontend/locales/en/cleaning.json` para R2, con el prefijo `messages.*` y las mismas claves que ya usan `tech.json` y `cleaner.json`.
2. THE SYSTEM SHALL NO tener ninguna cadena visible nueva incrustada en el código TSX nuevo (componentes del manager, hooks, wrappers, páginas) — toda cadena SHALL pasar por `useTranslation` y por las claves registradas; el panel de revisión i18n (`sdd-review-i18n`) la consideraría defecto si encuentra alguna.
3. THE SYSTEM SHALL respetar el patrón mobile-first y la guía de estilos existente: el botón de envío SHALL tener `className="tap-target"`; el composer SHALL ser un `<textarea rows={3} maxLength={2000}>` nativo (sin librería de formularios) con `label` asociado por `htmlFor`, contador visible y `aria-describedby` apuntando al contador, igual que `TechIncidentMessagesPanel`/`CleanerTaskMessagesPanel`.

### R5 — Cobertura y censo de superficies: las dos rutas siguen registradas y contadas

**As a** mantenedor del censo de superficies funcionales (regla 11 del proyecto), **I want** que añadir la pestaña de mensajes no rompa el conteo de rutas reales, **so that** el panel del gate `route-surface-counts-have-an-authoritative-source` siga verde.

Acceptance criteria:

1. THE SYSTEM SHALL NO añadir ninguna ruta nueva al `routeRegistry` (`frontend/features/shell/navigation/route-registry.ts`) ni a `REAL_PAGE_ROUTE_IDS` (`frontend/app/route-coverage.test.ts`) — las dos rutas ya están registradas como `incident-detail` y `cleaning-detail`, y el censo las cuenta. Solo cambia el contenido que renderizan.
2. WHERE el suite `App Router coverage` corre, THE SYSTEM SHALL seguir verde con la misma cifra de superficies (las dos rutas reales del manager para tareas/incidencias); el suite NO SHALL ser ampliado ni reducido por esta entrada.

## Out of scope

- **Notificaciones push/badge** de mensaje nuevo en el listado del manager o en el listado de tareas/incidencias (`NotificationLog` ya se escribe en backend, D8 de `staff-messaging`, pero mostrarlo en `/cleaning` o `/incidents` es una superficie distinta, no las dos pestañas de detalle que esta entrada cubre — mismo out-of-scope literal que `staff-messaging-web`).
- **Editar o borrar mensajes enviados**: no existe endpoint para ello y no se ha pedido — el contrato del backend es append-only y esta entrada no lo extiende.
- **Adjuntar fotos al mensaje**: el contrato de `content` es texto plano de hasta 2000 caracteres (D5/D6 del design de `staff-messaging`); adjuntar ficheros es una extensión de ese contrato, no del front.
- **Hilo del manager con el huésped (`/conversations`)**: la pantalla `/conversations` ya existe y consume su propia API (guest↔property); el backend no la cruza con el hilo de personal (`staff-messaging` design, mismo out-of-scope mantenido).
- **Notificaciones a managers específicos cuando se publica un mensaje**: `staff-messaging` ya decidió notificar a todos los `PROPERTY_MANAGER` del tenant (D9) y este change no toca notificaciones — un manager que abre la pestaña ve los mensajes que otros managers ya dejaron.
- **Refactorizar `TechIncidentMessagesPanel`/`CleanerTaskMessagesPanel` para compartir un componente con las nuevas vistas del manager**: `staff-messaging-web` design D1 ya rechazó la abstracción prematura dos veces (precedente `reviews-tabs.tsx`/`pricing-tabs.tsx`). Cada dominio es dueño de su variante; el manager recibe su copia.
- **Vista del manager sobre el listado de mensajes (`/incidents` con su hilo agregado, `/cleaning` con el suyo)**: las dos rutas son `/incidents/[id]` y `/cleaning/[id]`; el agregado a nivel de lista es otra entrada del roadmap.
- **Indicador de mensajes no leídos / unread badge** en la pestaña: nada en el backend lo soporta y añadirlo requiere una marca por usuario que ningún requisito pide hoy.

## Affected specs

- `sdd/specs/staff-messaging.md` — añadir nota de alcance del consumo frontend en la vista del manager (sección simétrica a la que `staff-messaging-web` añadió para los roles de campo; este change NO modifica la nota de los roles de campo, solo añade la del manager).
- `sdd/specs/cleaning-manager-task-detail.md` — añadir nota de la pestaña de mensajes montada en `/cleaning/[id]`.
- `sdd/specs/incidents.md` — añadir nota de la pestaña de mensajes montada en `/incidents/[id]` para `PROPERTY_MANAGER`/`TENANT_OWNER`.
