# Proposal: tech-app

## Why

`/tech` y `/tech/incidents/[id]` existen como `RoutePlaceholder` desde `frontend-foundation`, con
`TechnicianShell` y `AuthGuard allow={["TECHNICIAN"]}` ya puestos. El rol `TECHNICIAN` es el único
del PRD que todavía no tiene ninguna superficie funcional: hoy un técnico que entra en la app ve
«En preparación».

La entrada se abrió una vez y **se cerró sin proposal el 2026-08-19**, porque de las once cosas que
PRD §12 «UI del técnico» enumera sólo cuatro tenían backend. De ahí salieron tres entradas `[BE]`
—`tech-incident-context` (2026-08-22), `tech-cycle-completion` (2026-08-23) e `incident-photos`
(2026-08-23)—, **las tres archivadas**. El censo de `sdd/roadmap/tech-app.md` ya no tiene ni un ❌ y
se ha vuelto a medir contra el código para este proposal: las once peticiones de PRD §12 están
servidas por rutas que el rol puede llamar.

Fuentes: PRD §12 (UI del técnico, flujo, regla de aprobación), §24 (páginas), §26.20 (orden de
desarrollo), `sdd/roadmap/tech-app.md` (censo y precisiones), y los contratos vivos en
`sdd/specs/maintenance.md`, `sdd/specs/tech-incident-context.md`, `sdd/specs/incident-photos.md`.

## What changes

Las dos páginas del segmento `(field)/tech` dejan de ser placeholders y pasan a ser superficies
funcionales sobre la API de mantenimiento que ya existe: una lista «mis incidencias» con la
vivienda de cada fila, y un detalle que reúne la avería, el contexto de acceso a la propiedad, la
galería de fotos, los botones del ciclo del técnico (aceptar / rechazar / en ruta / esperar piezas
/ reanudar), la subida de fotos antes/después y el cierre con coste y materiales, con la puerta de
aprobación de la propietaria mostrada tal como el backend la resuelve.

**Es un change de frontend en su totalidad**: no toca esquema, ni migraciones, ni el contrato
publicado. El cliente tipado generado (`frontend/lib/api/generated/openapi.d.ts`) ya conoce las
quince rutas implicadas — verificado: `context`, `photos`, `en-route`, `reject`,
`/incident-photos/{photo_id}`, `IncidentEtaRequest` y `materials` están presentes.

**Permisos, contados contra `backend/app/auth/domain/policy.py`.** `TECHNICIAN` es
`_SELF_SERVICE | _INCIDENT_EXECUTE` = `READ_OWN_PROFILE`, `MANAGE_OWN_SESSION`,
`READ_OWN_NOTIFICATIONS`, `READ_INCIDENTS`, `EXECUTE_INCIDENTS`. Cruzado con las dependencias de
`app/maintenance/api/incidents_router.py`, puede llamar exactamente a: `GET /incidents`,
`GET /incidents/{id}`, `GET /incidents/{id}/context`, `GET /incidents/{id}/photos` (`ReadDep`);
`POST` `accept`, `reject`, `en-route`, `wait-parts`, `resume`, `resolve`, `photos` (`ExecuteDep`);
y `GET /api/v1/incident-photos/{photo_id}`, anónima a propósito. **No** puede llamar a `classify`,
`PATCH /incidents/{id}` (triage), `assign` ni `cancel` (`ManageDep`), ni a `/api/v1/properties/…`
(`READ_PROPERTIES`). Toda la pantalla cabe dentro de esa lista.

## Requirements

### R1 — Mis incidencias en `/tech`

**Como** técnico, **quiero** ver mis incidencias asignadas con la vivienda a la que voy, **para**
saber qué tengo pendiente sin llamar al manager.

Criterios de aceptación:

1. WHEN un usuario autenticado con rol `TECHNICIAN` abre `/tech`, THE SYSTEM SHALL sustituir el
   `RoutePlaceholder` actual por la lista servida por `GET /api/v1/incidents`, y SHALL NOT enviar
   ningún parámetro que identifique al técnico: el acotamiento por fila lo deriva el backend del
   token (`IncidentActor.restrict_to_technician_id`) y no existe parámetro de consulta para él.
2. WHEN la lista se renderiza, THE SYSTEM SHALL mostrar por fila el título, la severidad, el
   estado, la categoría y la fecha de creación de `IncidentResponse`, más el `property_name` y el
   `property_internal_code` obtenidos de `GET /api/v1/incidents/{id}/context` para esa fila.
3. THE SYSTEM SHALL emitir la consulta de contexto de cada fila bajo la **misma clave de query
   tenant-scoped** que usará el detalle, de modo que abrir una fila no vuelva a pedir su contexto.
4. WHERE no hay ningún filtro seleccionado, THE SYSTEM SHALL pedir la página sin `status` y
   presentarla en el orden que sirve el backend (`created_at` descendente) SIN reordenar en
   cliente, y SHALL indicar en la propia pantalla que la lista incluye incidencias ya cerradas.
5. WHEN el usuario selecciona uno de los chips de estado, THE SYSTEM SHALL re-consultar con un
   **único** valor `status` —el contrato no admite varios— y reflejar esa selección en la clave de
   query; un segundo clic sobre el chip activo SHALL volver al estado sin filtro.
6. IF la respuesta está vacía, THEN THE SYSTEM SHALL renderizar el `EmptyState` compartido; IF la
   petición falla, THEN THE SYSTEM SHALL renderizar el `ErrorState` compartido sin exponer el
   detalle del error, reutilizando `retryPolicy` (sin reintento en 4xx).

> `ASSUMPTION`: los chips cubren los seis estados que un técnico puede ver en sus propias filas
> (`ASSIGNED`, `ACCEPTED`, `IN_PROGRESS`, `WAITING_EXTERNAL_PARTS`, `AWAITING_OWNER_APPROVAL`,
> `RESOLVED`). `OPEN`, `CLASSIFIED` y `CANCELLED` no se ofrecen porque en ninguno de los tres la
> incidencia está asignada a nadie, así que el filtro devolvería siempre vacío.

### R2 — Detalle: a qué piso voy, cómo entro y qué me dijeron

**Como** técnico, **quiero** abrir una incidencia y ver la avería junto con la dirección, las
instrucciones de acceso y la nota de quien me la asignó, **para** presentarme y entrar sin
depender de una llamada.

Criterios de aceptación:

1. WHEN un técnico abre `/tech/incidents/[id]`, THE SYSTEM SHALL sustituir el `RoutePlaceholder`
   actual y componer la pantalla con `GET /api/v1/incidents/{id}` y
   `GET /api/v1/incidents/{id}/context`.
2. THE SYSTEM SHALL mostrar de `IncidentResponse`: título, descripción, severidad, categoría,
   estado, fuente, `eta_at`, `estimated_cost`, `approved_cost`, `final_cost`, `materials`,
   `owner_approval_required`, `resolved_at` y `created_at`.
3. THE SYSTEM SHALL mostrar de `IncidentContextResponse`: `property_name`,
   `property_internal_code`, la dirección completa (`address_line1`, `address_line2`, `city`,
   `province`, `postal_code`, `country`), `access_notes` como instrucciones de acceso y
   `assignment_note` como la nota del manager —que es lo que PRD §12 llama «notas del
   propietario/manager»: `Incident` no tiene columna propia para ellas.
4. WHEN un campo nulo de esos DTOs se renderiza en línea dentro de una fila poblada, THE SYSTEM
   SHALL mostrar el em-dash `—` (U+2014) como marca tipográfica, conforme a la convención de
   `sdd/specs/frontend-foundation.md`, y SHALL NOT concatenarlo con su unidad ni usar `?? ""`.
5. THE SYSTEM SHALL NOT llamar a ninguna ruta de `/api/v1/properties/…` ni construir URLs de
   almacenamiento en el cliente: el rol no tiene `READ_PROPERTIES` y la proyección de contexto
   existe precisamente para eso.
6. IF cualquiera de las dos peticiones responde `404`, THEN THE SYSTEM SHALL tratarlo como
   «incidencia no disponible» sin distinguir si no existe, es de otro tenant o es de otro técnico
   —el backend los hace deliberadamente indistinguibles— y ofrecer la vuelta a `/tech`.

### R3 — El ciclo del técnico: aceptar, rechazar, en ruta, piezas, reanudar

**Como** técnico, **quiero** mover la incidencia por su ciclo desde el móvil, **para** que el
manager y la propietaria vean dónde estoy sin que yo tenga que avisar.

Criterios de aceptación:

1. THE SYSTEM SHALL ofrecer exactamente las acciones que el estado admite, según la tabla de
   transiciones vigente: `ASSIGNED` → «Aceptar» (`POST accept`) y «Rechazar» (`POST reject`);
   `ACCEPTED` → «En ruta» (`POST en-route`) y «Rechazar»; `IN_PROGRESS` → «Esperando piezas»
   (`POST wait-parts`) y el cierre de R4; `WAITING_EXTERNAL_PARTS` → «Reanudar» (`POST resume`).
2. WHERE el estado es `AWAITING_OWNER_APPROVAL`, `RESOLVED` o `CANCELLED`, THE SYSTEM SHALL no
   ofrecer ninguna acción de ciclo y SHALL explicar por qué (a la espera de la propietaria, o
   cerrada).
3. WHEN el técnico ejecuta «Aceptar» o «En ruta», THE SYSTEM SHALL permitir adjuntar una ETA
   opcional en el cuerpo `IncidentEtaRequest`, enviada como instante **con offset de zona**, y
   SHALL omitir el cuerpo por completo cuando no se informa ninguna.
4. IF la API rechaza la ETA con `422` («must carry a timezone», «cannot be in the past»), THEN THE
   SYSTEM SHALL mostrarlo junto al campo sin perder lo que el técnico había escrito, y SHALL NOT
   replicar esa validación como si fuera suya —la frontera es `now` del servidor.
5. WHEN `POST reject` responde `200`, THE SYSTEM SHALL devolver al técnico a `/tech` e invalidar la
   lista, porque el rechazo borra los tres campos de la asignación (asignatario, ETA y nota) y a
   partir de ese momento `GET /incidents/{id}` le responde `404` a quien rechazó.
6. WHEN cualquiera de estas mutaciones responde `200`, THE SYSTEM SHALL refrescar la incidencia y
   la lista desde la respuesta o invalidando su clave, sin recomponer el estado en el cliente.
7. IF una mutación responde `409` (transición inválida, incidencia cerrada o esperando a la
   propietaria), THEN THE SYSTEM SHALL mostrar el mensaje que corresponde a cada uno de esos tres
   casos, refrescar la incidencia y SHALL NOT reintentar automáticamente.

### R4 — Cerrar con coste y materiales, y la puerta de la propietaria

**Como** técnico, **quiero** cerrar la incidencia declarando lo que ha costado y qué materiales he
usado, **para** que el gasto quede registrado sin pasar por el manager.

Criterios de aceptación:

1. WHERE el estado es `IN_PROGRESS`, THE SYSTEM SHALL ofrecer un formulario de cierre con
   `final_cost` **obligatorio** (número ≥ 0, ≤ 99 999 999,99, como mucho dos decimales) y
   `materials` opcional (entre 1 y 2000 caracteres), y SHALL enviar `POST /incidents/{id}/resolve`.
2. WHEN la respuesta llega con `status = RESOLVED`, THE SYSTEM SHALL presentar la incidencia como
   cerrada mostrando `final_cost`, `materials` y `resolved_at`.
3. WHEN la respuesta llega con `status = AWAITING_OWNER_APPROVAL`, THE SYSTEM SHALL comunicar
   explícitamente que **el cierre no se ha aceptado** y queda a la espera de la propietaria,
   conservando visible el `final_cost` que devuelve la respuesta y sin inventar un `resolved_at`
   que la respuesta trae a `null`.
4. THE SYSTEM SHALL NOT calcular, mostrar ni anticipar el umbral `owner_approval_threshold_eur`:
   el rol no puede leer la configuración del tenant y la puerta la resuelve el backend al recibir
   el cierre. La app lo muestra; no lo predice ni lo evita.
5. IF la validación local del formulario falla, THEN THE SYSTEM SHALL no emitir la petición; IF la
   API responde `422`, THEN THE SYSTEM SHALL mostrarlo sin vaciar el formulario.

### R5 — Fotos del incidente: galería y subida antes/después

**Como** técnico, **quiero** ver las fotos de la avería y subir las mías de antes y después,
**para** dejar constancia del trabajo sin usar WhatsApp.

Criterios de aceptación:

1. WHEN el detalle carga, THE SYSTEM SHALL listar `GET /api/v1/incidents/{id}/photos` y renderizar
   cada `IncidentPhotoResponse.url` **tal cual** en el `src` de la imagen, agrupadas por `stage` y
   de la más antigua a la más reciente, que es el orden que sirve el backend.
2. THE SYSTEM SHALL NOT persistir, reescribir ni reconstruir esa `url` —es una URL firmada acuñada
   para esa respuesta y con caducidad acotada—; cuando deje de servir, la recuperación SHALL ser
   volver a listar, y SHALL NOT existir ninguna `storage_key` en el cliente.
3. WHERE el estado es `IN_PROGRESS` o `WAITING_EXTERNAL_PARTS`, THE SYSTEM SHALL ofrecer subir una
   foto con `stage` ∈ {`BEFORE`, `AFTER`} —enum cerrado de dos valores, sin campo de texto libre—
   mediante `POST /api/v1/incidents/{id}/photos` en `multipart/form-data`. En cualquier otro
   estado la subida SHALL no ofrecerse.
4. THE SYSTEM SHALL emitir esa subida por un camino que **no** imponga
   `Content-Type: application/json` ni serialice el cuerpo con `JSON.stringify`: el
   `createApiClient` actual hace ambas cosas incondicionalmente, así que ésta es la primera
   petición multipart del frontend y necesita una vía explícita que conserve la cabecera de
   sesión, el reintento único ante `401` y el mapeo de errores del cliente compartido.
5. WHEN la subida responde `201`, THE SYSTEM SHALL invalidar la lista de fotos de esa incidencia.
6. IF la subida responde `409` (estado que no admite fotos), `413` (tamaño), `422` (los bytes no
   son JPEG, PNG ni WebP) o `502` (fallo del almacenamiento), THEN THE SYSTEM SHALL mostrar un
   mensaje distinto para cada uno y SHALL NOT reintentar automáticamente. El mensaje del `422`
   SHALL nombrar los formatos admitidos, porque la causa frecuente en un móvil es un HEIC de
   iPhone y la acción que lo resuelve es cambiar el formato, no reintentar.

   > Enmienda acordada en el gate de `/sdd:design` (2026-08-29, OQ3). La redacción original
   > enumeraba tres códigos; el contrato publicado declara cuatro
   > (`_PHOTO_UPLOAD_RESPONSES` en `backend/app/maintenance/api/incidents_router.py`). La otra
   > causa del `422` —un `stage` fuera de `BEFORE`/`AFTER`— no es alcanzable desde esta pantalla,
   > porque el control ofrece exactamente los dos valores del enum cerrado.
7. THE SYSTEM SHALL NOT presentar la foto de cierre como requisito del cierre —no hay puerta de
   evidencia en `resolve`— ni ofrecer borrar una foto: la API no expone ningún borrado.

### R6 — Postura mobile-first, estados e i18n

**Como** técnico que trabaja de pie y con una mano, **quiero** una pantalla legible en el móvil y
en mi idioma, **para** poder operarla en el portal de un edificio.

Criterios de aceptación:

1. THE SYSTEM SHALL pasar toda cadena visible por `frontend/locales/es/` y `frontend/locales/en/`,
   sin ninguna literal en los componentes.
2. THE SYSTEM SHALL construir los estados de carga, vacío y error sobre los primitivos compartidos
   (`StatePanel`, `LoadingState`, `EmptyState`, `ErrorState`), con `aria-busy` en la carga y
   `role="alert"` en el error, y SHALL NOT renderizar el detalle crudo de ningún error.
3. THE SYSTEM SHALL disponer ambas pantallas en una sola columna con objetivos táctiles cómodos y
   sin desplazamiento horizontal a 360 px de ancho.
4. THE SYSTEM SHALL reutilizar la paleta existente (`features/incidents/lib/severity-tone.ts` sobre
   `lib/ui/status-tone.ts`) para severidad y estado, y SHALL NOT introducir una segunda tabla de
   colores.

   > **Enmienda (2026-08-30, gate de `/sdd:review`).** La mitad «y estado» es **insatisfacible tal
   > como está escrita**: no existe ninguna tabla estado-de-incidencia→`Tone` en el árbol —
   > `severity-tone.ts` sólo mapea `IncidentSeverity`, y las únicas hermanas
   > (`features/cleaning/lib/task-status.ts`, `features/pricing/lib/recommendation-status.ts`)
   > mapean otros enums. No había nada que reutilizar, así que el estado se pinta como un chip
   > neutro (`text-muted-foreground`). La mitad prohibitiva —no introducir una segunda tabla de
   > colores— sí se cumple, y es la que protege la regla de
   > `frontend-foundation.md` («keep the badge colour palette in exactly one place»).
   > Crear la tabla que falta habría sido alcance que nadie pidió y una decisión de vocabulario
   > (qué significa cada color para un estado) que no es de este change. Queda como candidato de
   > roadmap para `/sdd:archive`: `incident-status-tone`.
5. THE SYSTEM SHALL confiar la autorización al backend: el `AuthGuard allow={["TECHNICIAN"]}` que
   ya monta el layout es un escudo de UX, y ninguna decisión de negocio SHALL derivarse del rol en
   el cliente.

## Out of scope

- **Cualquier cambio de backend**: esquema, migraciones, permisos del rol, o el contrato publicado.
  Si algo de PRD §12 resultara no estar servido, se para y se abre una entrada `[BE]`, como ya se
  hizo el 2026-08-19.
- **Un filtro multi-estado en `GET /api/v1/incidents`**. Hoy `status` admite un solo valor, y por
  eso R1.4/R1.5 se resuelven con chips en lugar de con una vista «activas». Si se quiere esa vista,
  es una entrada `[BE]` propia.
- **Las cuatro operaciones del manager** (`classify`, `PATCH` triage, `assign`, `cancel`) y la
  respuesta de aprobación (`POST /owner-approvals/{id}/respond`): el rol no puede llamarlas.
  `/approvals` sigue siendo placeholder.
- **Las pantallas del workspace** (`/incidents`, `/incidents/[id]`): no cambian su presentación.
  Este change puede ensanchar el `IncidentDetailDto` compartido con `etaAt` y `materials` —que
  `IncidentResponse` trae desde `tech-cycle-completion` y el DTO todavía no enumera—, pero
  **renderizarlos en el detalle del manager queda fuera**.
- **`cleaner-app`**: la app de la limpiadora es su propia entrada del roadmap y no comparte
  pantallas con ésta. Lo único que las relaciona es el criterio con el que ambas se partieron.
- **Notificaciones al técnico** (`READ_OWN_NOTIFICATIONS` está en el rol pero PRD §12 no pide
  bandeja) y el **SLA de técnicos** de PRD §12, que es trabajo de Celery y no de pantalla.
- **E2E con Playwright**: la suite E2E completa es de `hardening-release` (PRD §26.27, DoD §28).

## Affected specs

- `sdd/specs/tech-app.md` — *(no existe aún — se creará al archivar)*. La capacidad completa: las
  dos superficies, el ciclo del técnico en la web, la galería y la subida de fotos, y la puerta de
  aprobación tal como se muestra.
- `sdd/specs/frontend-foundation.md` — el inventario de superficies deja de contar `/tech` y
  `/tech/incidents/[id]` como placeholders (de once a nueve) y los suma a las funcionales (de
  quince a diecisiete), en las líneas 25 y 99. **Además arrastra una redacción caduca que este
  change debe corregir al archivar**: esa misma línea 25 nombra `start` entre las operaciones de
  mantenimiento fuera de alcance desde la web, y esa ruta no existe en el contrato publicado desde
  que `tech-cycle-completion` la renombró a `en-route`.
- `sdd/specs/maintenance.md`, `sdd/specs/tech-incident-context.md`, `sdd/specs/incident-photos.md` —
  **no se modifican**. Son los contratos que esta pantalla consume; se citan como fuente, no se
  tocan.

### Trabajo pendiente para `/sdd:archive`

Levantado en el gate de `/sdd:review` (2026-08-29). Ninguno de los cinco es editable desde esta
fase: los puntos 2, 3, 4 y 5 viven en ficheros que sólo `/sdd:archive` escribe —`sdd/roadmap*` y
`sdd/specs/`, por la regla 1— y el punto 1 depende de un fichero que archive todavía no ha creado.

1. `docs/maintenance.md` §«La app del técnico» **no enlaza a ninguna spec**, mientras que su
   sección hermana sí lo hace (línea 145 → `sdd/specs/incident-photos.md`). La norma de
   `sdd/steering/documentation.md` es «no duplicar, enlazar»: cuando archive cree
   `sdd/specs/tech-app.md`, hay que añadir el enlace desde esa sección, o la página operativa se
   convierte en la única descripción del ciclo y empieza a derivar.
2. `sdd/roadmap/demo-user.md:25` y `:31` siguen contando `/tech` (+detalle) entre las superficies
   **placeholder** y afirmando que «limpiadora y técnico entran, pero no tienen a dónde ir». La
   mitad del técnico deja de ser cierta con este change. `demo-user` es una entrada ya entregada,
   así que decidir entre corregir las dos líneas o datarlas como registro histórico es de archive.
   La página operativa viva del mismo asunto, `docs/demo-tenant.md`, sí se actualizó aquí.
3. `sdd/specs/frontend-foundation.md:25` y `:99` — el recuento de superficies (placeholder 11→9,
   funcionales 15→17) y la mención caduca de `start`, ya descritas arriba.
4. **Candidato de roadmap: la cabecera del shell desborda a 360 px.** Medido el 2026-08-29 al hacer
   la tarea 9.6: la página produce desplazamiento horizontal (`scrollWidth` 433 sobre un viewport
   de 360) y el desbordamiento está **entero** en la cabecera del `TechnicianShell` —su botón de
   menú de usuario y el contenedor `flex` que lo envuelve—, no en el contenido de las pantallas,
   que no desborda ni un elemento. Se reproduce idéntico en `/dashboard`, así que es del shell
   compartido y afecta a todas las superficies, no sólo a las del técnico.

   **Dónde está**, para que archive no tenga que buscarlo: el contenedor es el slot `end` de
   `frontend/features/shell/components/topbar.tsx` —un `<div className="flex items-center gap-2">`
   que, a diferencia de los otros dos slots, no lleva `min-w-0`—, y lo que lo empuja es el botón de
   menú de usuario de `frontend/features/auth/components/user-menu.tsx`. El mismo `Topbar` lo monta
   el shell del workspace, que es por lo que `/dashboard` se comporta igual.

   `tech-app` no lo toca ni puede tocarlo sin salirse de su alcance: este change son las dos
   pantallas de `(field)/tech`, y `features/shell` no está en sus ficheros afectados ni en su
   §Out of scope como algo a modificar. **Consecuencia para R6.3**: se cumple para lo que estas dos
   pantallas gobiernan, pero un usuario a 360 px sí tiene desplazamiento horizontal. Archive debe
   abrir la entrada `[FE]` que lo arregle en el shell.
5. **`sdd/specs/cleaning-manager-view.md` contradice ahora a `sdd/project.md`.** Esa spec aplaza su
   pasada visual «porque `next dev` con `PORT_OFFSET` sirve la página sin hidratarla», y ese
   disparador («el primer despliegue en `dev`») se apoya en una premisa que este change ha medido
   falsa para su propio caso. Hay que reconciliar las dos: o la spec se anota con el matiz de
   `design-system-tokens` —el fallo es real **sólo para `next dev`**, y con `next start` en un
   contenedor aparte la app hidrata—, o se revisa su deuda, porque un worktree enlazado puede ser
   ahora un sitio válido para hacer esa comprobación. Es de archive porque `sdd/specs/` es suyo.

## Coordinación

`blocked-transitions-web` está en vuelo en otro worktree y es también `[FE]` sobre el dominio de
incidencias/limpieza. Ninguna de sus superficies es `/tech`, pero comparten árbol en
`frontend/locales/*/` y potencialmente en `frontend/features/incidents/`. Merece una comprobación
de conflictos al abrir el PR, no una dependencia declarada.
