# Proposal: staff-messaging-web

## Why

`staff-messaging` (archivado, PR fusionada 2026-09-03) entregó el backend del hilo
limpiadora↔manager y técnico↔manager: `cleaning_task_messages`/`incident_messages`, los
endpoints `POST`/`GET /api/v1/cleaning-tasks/{task_id}/messages` y
`POST`/`GET /api/v1/incidents/{incident_id}/messages`, y los permisos ya cubiertos por
`READ_CLEANING_TASKS`/`EXECUTE_CLEANING_TASKS`/`MANAGE_CLEANING_TASKS` y
`READ_INCIDENTS`/`EXECUTE_INCIDENTS` (`design.md` de ese change, D3). Hoy ese contrato no
tiene ningún consumidor: la limpiadora y el técnico siguen sin forma de responder a un
manager desde la pantalla donde ya trabajan.

## What changes

Se añade el hilo de mensajería de personal a las **dos pantallas móviles que ya existen y
ya estrenaron sus rutas reales** (`cleaner-app`, `tech-app`, ambas archivadas):
`/cleaner/tasks/[id]` (`CleanerTaskDetailView`) y `/tech/incidents/[id]`
(`TechIncidentDetailView`). Cada una gana una pestaña "Mensajes" — decisión D-mobile,
ver design.md — con lista cronológica paginada y un compositor de hasta 2000 caracteres,
consumiendo exactamente los cuatro endpoints que `staff-messaging` ya expone. Sin backend
nuevo, sin permisos nuevos, sin entidades nuevas: es una capa de consumo TanStack Query +
componentes sobre un contrato ya construido y ya probado.

## Requirements

### R1 — Hilo de mensajes en el detalle de tarea de la limpiadora

**As a** limpiadora, **I want** ver y responder los mensajes del manager sobre mi tarea
actual, **so that** puedo coordinar sin salir de la pantalla donde ya trabajo.

Acceptance criteria:

1. WHEN la limpiadora abre la pestaña de mensajes de `/cleaner/tasks/[id]`, THE SYSTEM
   SHALL listar los mensajes de `GET /api/v1/cleaning-tasks/{task_id}/messages` en orden
   cronológico ascendente, paginados.
2. WHEN la limpiadora envía un mensaje de 1-2000 caracteres, THE SYSTEM SHALL llamar a
   `POST /api/v1/cleaning-tasks/{task_id}/messages` y, en éxito, añadirlo al final de la
   lista sin recargar la página.
3. IF el campo de mensaje está vacío o supera 2000 caracteres, THEN THE SYSTEM SHALL
   deshabilitar el envío y mostrar la validación en línea, sin llamar al backend.
4. WHILE una petición de envío está en curso, THE SYSTEM SHALL deshabilitar el control de
   envío para evitar doble envío (steering/frontend.md, "Estados UI").

### R2 — Hilo de mensajes en el detalle de incidencia del técnico

**As a** técnico, **I want** ver y responder los mensajes del manager sobre mi incidencia
actual, **so that** puedo coordinar sin salir de la pantalla donde ya trabajo.

Acceptance criteria:

1. WHEN el técnico abre la pestaña de mensajes de `/tech/incidents/[id]`, THE SYSTEM SHALL
   listar los mensajes de `GET /api/v1/incidents/{incident_id}/messages` en orden
   cronológico ascendente, paginados.
2. WHEN el técnico envía un mensaje de 1-2000 caracteres, THE SYSTEM SHALL llamar a
   `POST /api/v1/incidents/{incident_id}/messages` y, en éxito, añadirlo al final de la
   lista sin recargar la página.
3. IF el campo de mensaje está vacío o supera 2000 caracteres, THEN THE SYSTEM SHALL
   deshabilitar el envío y mostrar la validación en línea, sin llamar al backend.
4. WHILE una petición de envío está en curso, THE SYSTEM SHALL deshabilitar el control de
   envío para evitar doble envío.

### R3 — Colocación móvil: pestaña, no sección inline

**As a** limpiadora o técnico en móvil, **I want** que el hilo de mensajes no ocupe espacio
en el flujo principal de la tarea/incidencia, **so that** el checklist/fotos (limpiadora) o
la información de la incidencia (técnico) siguen siendo lo primero que veo al entrar.

Acceptance criteria:

1. WHEN la pantalla de detalle carga, THE SYSTEM SHALL mostrar por defecto la pestaña de
   contenido operacional existente (checklist/fotos o detalle de incidencia), no la de
   mensajes.
2. WHEN el usuario cambia a la pestaña de mensajes, THE SYSTEM SHALL conservar el estado
   de scroll/formulario de la otra pestaña al volver (sin desmontar sus datos ya cargados).
3. WHERE el ancho de viewport es 360px (steering/frontend.md, "Responsive verificable"),
   THE SYSTEM SHALL mostrar ambas pestañas sin overflow horizontal ni recorte de texto.

### R4 — Estados vacío/carga/error con paridad de accesibilidad

**As a** limpiadora o técnico, **I want** saber si el hilo está cargando, vacío o falló al
cargar, **so that** no confundo un hilo sin mensajes con un error.

Acceptance criteria:

1. WHEN la lista de mensajes está cargando, THE SYSTEM SHALL mostrar `LoadingState`.
2. IF la lista de mensajes está vacía (sin mensajes aún), THEN THE SYSTEM SHALL mostrar un
   `EmptyState` explícito ("sin mensajes todavía"), nunca un hueco en blanco ni un error.
3. IF la petición de lista o de envío falla, THEN THE SYSTEM SHALL mostrar `ErrorState`
   (lista) o un error en línea junto al compositor (envío), sin perder el texto ya
   escrito por el usuario.
4. THE SYSTEM SHALL cumplir la línea base de `steering/frontend.md` ("UI/UX baseline"):
   foco visible, orden de tabulación lógico, objetivos táctiles ≥44×44px, contraste AA y
   labels asociados en el compositor.

### R5 — i18n completo ES/EN

**As a** usuario de cualquier locale soportado, **I want** que toda cadena del hilo de
mensajes esté traducida, **so that** la experiencia es consistente con el resto de la app.

Acceptance criteria:

1. THE SYSTEM SHALL definir cada string visible nueva (pestaña, placeholder del
   compositor, validaciones, estados vacío/error, contador de caracteres) en
   `locales/es/` y `locales/en/`, sin cadenas incrustadas.

## Out of scope

- **Vista del manager** sobre el hilo (tarea o incidencia). El backend ya autoriza a
  `PROPERTY_MANAGER` a leer y escribir ambos hilos (D3 de `staff-messaging`/design.md),
  pero esta entrega se recorta explícitamente a las **dos pantallas móviles que ya
  existen como página real** para los roles de campo — `/cleaner/tasks/[id]` y
  `/tech/incidents/[id]`. El manager no tiene hoy una página de detalle de tarea de
  limpieza (`/incidents/[id]` sí existe y es real, pero su contraparte de `cleaning` no),
  así que dar el hilo solo al lado de incidencias del manager crearía una cobertura
  asimétrica entre sus dos dominios. Queda para una entrada de roadmap futura, cuando
  exista la página de detalle de tarea del manager (o se decida deliberadamente no
  construirla).
- **Notificaciones push/badge** de mensaje nuevo en la lista de tareas/incidencias
  (`NotificationLog` ya se escribe en backend, D8 de `staff-messaging`, pero mostrarlo en
  la lista de `/cleaner`/`/tech` es una superficie distinta, no las dos pantallas de
  detalle que este change cubre).
- **Editar o borrar mensajes enviados**: no existe endpoint para ello y no se ha pedido.
- **Adjuntar fotos al mensaje**: el contrato de `content` es texto plano de hasta 2000
  caracteres (D5 de `staff-messaging`); adjuntar ficheros es una extensión de ese
  contrato, no de esta pantalla.
- **Guest↔limpiadora/técnico**: fuera de alcance también en el backend (`staff-messaging`
  proposal.md), no reabierto aquí.

## Affected specs

- `sdd/specs/cleaner-app.md` — añadir la sección de la pestaña de mensajes en
  `/cleaner/tasks/[id]`.
- `sdd/specs/tech-app.md` — añadir la sección de la pestaña de mensajes en
  `/tech/incidents/[id]`.
- `sdd/specs/staff-messaging.md` — el backend ya está documentado ahí; añadir la nota de
  que el consumo frontend cubre solo los dos roles de campo (enlazar el out-of-scope de
  arriba), no el manager.
