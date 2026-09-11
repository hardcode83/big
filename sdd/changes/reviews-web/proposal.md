# Proposal: reviews-web

## Why

`revenue-reviews` (archivado 2026-09-02, `sdd/specs/revenue-reviews.md`) entregó la
mitad de máquina de PRD §18 —entidades, pipeline de IA, draft, máquina de estados,
seis rutas REST y el job `classify_reviews` cada 5 min— pero **sin UI**. Hoy
`frontend/app/(workspace)/reviews/page.tsx:11` es un `RoutePlaceholder`, así que la
mitad humana del flujo es inalcanzable: hay borradores que nadie lee, no hay cola
de decisión, y la manager no puede dar de alta a mano una reseña que llegó por un
canal que no es OTA. Ni `revenue-reviews` ni el roadmap registraron esa mitad `[FE]`,
y el reparto de permisos ya está cerrado en `auth/domain/policy.py` (la owner
aprueba, ignora y marca como publicada; el manager crea con `CREATE_REVIEW`).

Esto la hace distinta de las entradas `[FE]` de lectura anteriores
(`reservations-web`, `incidents-web`, `properties-web`). Aquí el sólo-lectura no es
un alcance más pequeño: **es un alcance sin producto**. Una pantalla que pintase
reseñas sin poder decidir borradores sería un informe, y una pantalla sin alta a
mano dejaría el caso «canal no automatizado, el huésped llamó por teléfono» sin
salida — `create-review-from-reservation` no existe como ruta del backend, y la
[R5.1](../specs/revenue-reviews.md#r5--creación-manual-y-listado-de-reseñas) del
spec sólo expone el alta manual.

Fuentes: entrada de roadmap `reviews-web` y su nota
`sdd/roadmap/reviews-web.md` (análisis largo, con el contrato verificado contra el
código); `sdd/specs/revenue-reviews.md`; `sdd/specs/auth-tenancy.md` (permisos);
PRD §7.20-7.21, §18, §23, §24.

## What changes

Después de este change, `/reviews` es una superficie funcional con dos pestañas —
**Borradores** (por defecto) y **Reseñas**— servidas bajo el descriptor de ruta
ya existente (`id: "reviews"`, `pattern: "/reviews"`, `match: "exact"`,
`features/shell/navigation/route-registry.ts:239-243`). Aparece la feature
`frontend/features/reviews/` completa (data source, hooks de query y mutación,
store de UI, componentes), un namespace i18n `reviews` en ES y EN, y el espejo
de permisos del frontend gana `MANAGE_REVIEW_DECISIONS` (decidir) para la
`TENANT_OWNER` y `CREATE_REVIEW_UI` (alta y edición de borrador) para la
`PROPERTY_MANAGER`. No se toca el backend, ni el registro de ruta, ni
`navigation.json`: las siete operaciones están archivadas en
`backend/openapi.json`, el descriptor ya existe y sus claves i18n ya están en
los dos locales.

La pestaña **Borradores** es la cola de decisión: lista reseñas en estado
`DRAFTED` (la pipeline las puso ahí), ordenadas por `published_at DESC` con
nulos al final, con el botón **Aprobar** que envía `PATCH .../response` con
`action = APPROVE`, **Ignorar** con `action = IGNORE` y **Marcar como publicada**
sólo cuando ya están `APPROVED`. **Editar el borrador** abre un campo editable
sobre el texto propuesto por la IA y envía `action = EDIT` antes de aprobar; el
backend exige el permiso `APPROVE_REVIEW` para la edición también, así que el
control es del mismo grupo que la decisión.

La pestaña **Reseñas** es el listado completo de la tabla: filtros por
`property_id`, `channel`, `sentiment`, `status`, `rating_min`/`rating_max`,
`date_from`/`date_to`, paginación `?page&per_page`, y un diálogo de alta a
mano (sólo la manager) que envía `POST /api/v1/reviews`. La fila de cada
reseña abre un detalle con texto original (`content`), `ai_summary`,
`recurring_issues` y `sentiment` (los tres campos que la pipeline rellenó), más
el borrador (`draft_content`) si existe.

Fuera de la feature se tocan **dos** cosas más, ambas decididas en `/sdd:design`:

- **`frontend/lib/auth/permissions.ts`** amplia la unión `Permission` con dos
  miembros nuevos, `MANAGE_REVIEW_DECISIONS` y `CREATE_REVIEW_UI`, y los reparte
  en `ROLE_UI_PERMISSIONS` siguiendo la línea de `policy.py`: `TENANT_OWNER`
  tiene el primero, `PROPERTY_MANAGER` tiene el segundo. La owner **no** ve el
  diálogo de alta —no tiene `CREATE_REVIEW` en el backend, y concederle la
  entrada al formulario la expondría a un `403` que la propia UI no avisa
  limpiamente—; el manager **no** ve los botones de decisión —no tiene
  `APPROVE_REVIEW`/`IGNORE_REVIEW`/`MARK_REVIEW_POSTED` en el backend, y la
  asimetría es la misma que `approvals-web` D10 ya fijó para
  `RESPOND_OWNER_APPROVALS`.
- **`backend/openapi.json`** se regenera para que el cliente tipado del
  frontend refleje las siete rutas y los cinco enums de `reviews`. Es un paso
  obligatorio del worktree de esta feature (mismo workaround de
  `sdd/project.md` §Commands) y **no** modifica el contrato: el contrato está
  congelado y archivado.

## Requirements

### R1 — Una ruta, dos pestañas, una decisión

**As a** manager o propietaria, **I want** ver en `/reviews` tanto la cola de
borradores pendientes de decidir como el historial completo de reseñas,
**so that** pueda operar lo urgente sin perder el contexto.

El registro de ruta ya prometió esa forma: `routes.reviews.description` dice
*«Gestión de reseñas de huéspedes.»* / *«Guest review management.»*.

Acceptance criteria:

1. WHEN una usuaria autorizada abre `/reviews`, THE SYSTEM SHALL renderizar la
   pestaña **Borradores** como activa inicial y una pestaña **Reseñas**
   alcanzable desde la misma ruta, ambas con etiqueta localizada en ES y EN.
2. THE SYSTEM SHALL servir las dos pestañas bajo el descriptor de ruta
   existente (`id: "reviews"`, `pattern: "/reviews"`, `match: "exact"`,
   `features/shell/navigation/route-registry.ts:239-243`) **sin** dar de alta
   ningún descriptor nuevo, sin cambiar `match` a `"prefix"` y sin añadir
   claves a `locales/{es,en}/navigation.json`.
3. THE SYSTEM SHALL mantener la pestaña activa en el store de UI de la feature
   (Zustand), y NOT SHALL reflejarla en la URL ni en un parámetro de query.
4. WHEN se abre `/reviews`, THE SYSTEM SHALL dejar de renderizar
   `RoutePlaceholder` en esa ruta.

### R2 — La cola de borradores: el lado humano del flujo

**As a** propietaria, **I want** ver sólo las reseñas que están en estado
`DRAFTED`, **so that** la cola que tengo que decidir esté limpia de casos ya
resueltos y de casos que la IA aún no ha clasificado.

Acceptance criteria:

1. WHEN se muestra la pestaña Borradores, THE SYSTEM SHALL pedir
   `GET /api/v1/reviews` con `status = DRAFTED` y los demás filtros activos
   (`property_id`, `channel`, `sentiment`, `rating_min`/`rating_max`,
   `date_from`/`date_to`), `page` y `per_page`.
2. THE SYSTEM SHALL leer el sobre de paginación como `{ items, page, per_page,
   total }` — `items`, no `data` — y calcular las páginas en el cliente como
   `Math.ceil(total / per_page)` porque la respuesta **no** expone
   `total_pages`.
3. IF `total` es `0`, THEN THE SYSTEM SHALL renderizar el estado vacío
   localizado, y NOT SHALL renderizar «página 1 de 0».
4. THE SYSTEM SHALL pintar por fila: vivienda (nombre resuelto del catálogo),
   `channel`, `rating` (formateado como `/5`), `sentiment` localizado, y
   `published_at` con día del locale o em-dash si es `null` (mismo criterio de
   `published_at DESC` con nulos al final que `revenue-reviews` R5.3 fija en el
   backend).
5. THE SYSTEM SHALL NOT pintar `content` en la fila —es prosa del huésped, va
   al detalle—, y SHALL NOT pintar `ai_summary` ni `recurring_issues` en la
   fila —son sumideros de la regla 11 de `steering/security.md` y su lectura
   tiene sentido con la fila abierta, no en una lista compacta.

### R3 — Decidir: los tres movimientos legales, con la edición como preludio

**As a** propietaria, **I want** aprobar, ignorar o marcar como publicada una
reseña, y editar el borrador antes de aprobar si lo deseo, **so that** la
mitad humana de PRD §18 quede cerrada — el sistema recomienda, yo decido.

`PATCH /api/v1/reviews/{id}/response` admite **cuatro** acciones
(`APPROVE`, `IGNORE`, `MARK_POSTED`, `EDIT`), y `EDIT` lleva `draft_content`
obligatorio.

Acceptance criteria:

1. WHEN la fila está en `DRAFTED`, THE SYSTEM SHALL ofrecer **Editar
   borrador**, **Aprobar** y **Ignorar**. **Aprobar** envía
   `{"action": "APPROVE"}`; **Ignorar** envía `{"action": "IGNORE"}` y requiere
   confirmación antes de mutar (mismo patrón que `pricing-web` R3.3 — `409` si
   el estado no admite el salto).
2. WHEN la fila está en `APPROVED`, THE SYSTEM SHALL ofrecer **Marcar como
   publicada** con `{"action": "MARK_POSTED"}`, y SHALL NOT ofrecerla en ningún
   otro estado — `POSTED_MANUALLY` y `IGNORED` son terminales
   ([specs/revenue-reviews.md R4.1](../specs/revenue-reviews.md)).
3. WHEN la fila está en `DRAFTED` y la usuaria pulsa **Editar borrador**, THE
   SYSTEM SHALL abrir un campo editable sobre el `draft_content` que la IA
   propuso; al guardar envía `{"action": "EDIT", "draft_content": "<texto>"}` y
   SHALL NOT cambiar `ai_generated` (el campo no se publica, y el backend lo
   trata como bitácora de origen: spec R3.6). **No** SHALL ofrecer Editar
   borrador cuando la fila está en `APPROVED`: la entidad
   `ReviewResponseDraft.edit()` rechaza con `ReviewValidationError` en cuanto
   `approved_at` está fijado (regla R3.6 del spec, fija por
   `test_edit_after_approval_is_refused`), así que prometer ese botón sólo
   serviría para entregar un `422` que la UI no puede enseñar — la norma del
   proyecto prohíbe pintar el cuerpo del `422`.
4. WHEN una decisión o una edición se envía, THE SYSTEM SHALL deshabilitar los
   controles de **todas** las filas y los del diálogo **Marcar como
   publicada** mientras la petición vuela —una sola escritura en vuelo, como
   `pricing-web` R3.3—; configurar la mutación
   con `retry: false`, y SHALL invalidar el **prefijo** de la clave de
   reseñas en `onSettled` —también cuando falla— de modo que la fila desaparezca
   del filtro que ya no la contiene. La respuesta del `PATCH` es una reseña
   suelta y no sabe nada de `total` ni de la página.
5. IF el `PATCH` responde `409` (la reseña ya no está en el estado que la
   acción exige, p. ej. otra persona la decidió antes), THEN THE SYSTEM SHALL
   mostrar copia localizada **propia** de ese caso —*«esa reseña ya no está en
   el estado que creías»*—, distinta del error genérico. Mismo criterio que
   `pricing-web` R3.6.
6. THE SYSTEM SHALL elegir la copia de error por **status HTTP** (`403`,
   `404`, `409`, `422`, genérico) y SHALL NOT leer, mapear ni exponer
   `ApiError.message` ni el cuerpo del backend.
7. IF cualquier operación responde `403`, THEN THE SYSTEM SHALL mostrarlo
   como error y SHALL NOT tratarlo como éxito.
8. THE SYSTEM SHALL renderizar el **texto del borrador** y el **texto del
   huésped** como texto y nunca como HTML, sin traducir ni parsear, con
   etiqueta localizada alrededor. El del huésped es sumidero de la regla 11
   (`reviews.content`, excepción 4 de `steering/security.md`); el del borrador
   es sumidero cerrado por sumidero (`review_response_drafts.draft_content`,
   vocabulario `REVIEW_DRAFT_TEMPLATES`). La UI no recombina ninguno.

### R4 — Marcar como publicada: una afirmación humana sobre algo fuera del sistema

**As a** manager, **I want** registrar que ya publiqué la respuesta en la OTA,
**so that** la fila salga de la cola sin que el sistema finja que sabe lo que
no sabe — el posting lo hice yo, en Airbnb/Booking, no el sistema.

Acceptance criteria:

1. THE SYSTEM SHALL llamar a **Marcar como publicada** un diálogo que termina
   con un `Button` cuyo `aria-label` localizado dice que **ya** se publicó en
   la OTA (no «publicar»), porque el sistema no publica nada — la frase
   [«una afirmación humana sobre algo que pasó fuera del sistema»](../roadmap/reviews-web.md)
   es lo que la UI debe reflejar.
2. THE SYSTEM SHALL requerir confirmación explícita: un `ConfirmDialog` con el
   texto del huésped en preview, el `draft_content` aprobado en preview, y la
   confirmación se cierra sólo con un clic en el botón primario del diálogo.
   Sin esta puerta la fila pasa a `POSTED_MANUALLY` sin posibilidad de
   deshacer, y `IGNORED`/`POSTED_MANUALLY` son terminales (R4.1 del spec).
3. WHEN la confirmación se acepta, THE SYSTEM SHALL enviar
   `{"action": "MARK_POSTED"}` sin `draft_content` — la marca es independiente
   del texto— y SHALL invalidar el prefijo de reseñas como en R3.4.

### R5 — La pestaña Reseñas: el historial completo y el alta a mano

**As a** manager, **I want** ver todas las reseñas de mis viviendas —no sólo
las pendientes de decidir— y dar de alta a mano una que llegó por un canal no
automatizado, **so that** la cobertura de PRD §18 alcance los casos que la
pipeline no cubre.

Acceptance criteria:

1. WHEN se muestra la pestaña Reseñas, THE SYSTEM SHALL pedir
   `GET /api/v1/reviews` con los mismos filtros que R2.1 **menos** `status` —
   la pestaña lista todos los estados, y el filtro de estado vive en un
   selector de la cabecera.
2. THE SYSTEM SHALL pintar por fila los mismos campos que R2.4, más el
   `status` localizado —los cinco valores del enum: `NEW`, `DRAFTED`,
   `APPROVED`, `POSTED_MANUALLY`, `IGNORED`—, con etiqueta en ES y EN.
3. WHEN la usuaria con permiso `CREATE_REVIEW_UI` pulsa **Añadir reseña**,
   THE SYSTEM SHALL abrir un diálogo con `property_id` (selector del
   catálogo de viviendas), `channel` (selector cerrado con los **cinco**
   miembros del enum `ReviewChannel`: `AIRBNB`, `BOOKING`, `GOOGLE`,
   `MANUAL`, `OTHER`), `reviewer_name` (opcional, máximo 200 caracteres),
   `rating` (selector `1.0`..`5.0` con paso `0.5`), `content` (opcional,
   máximo 4000 caracteres), y `language` opcional. La validación de cliente
   refleja la del backend ([specs/revenue-reviews.md R5.1](../specs/revenue-reviews.md))
   y SHALL NOT añadir restricciones que el backend no impone.
4. WHEN el diálogo se envía, THE SYSTEM SHALL llamar a
   `POST /api/v1/reviews` con `Content-Type: application/json`, mostrar éxito
   con copia localizada, invalidar el prefijo de reseñas, y cerrar el diálogo.
   La reseña creada aparece con `sentiment = NEUTRAL`, `ai_summary = NULL`,
   `recurring_issues = []` y `status = NEW` (R5.2 del spec) — el campo se
   actualiza cuando la pipeline corre en los siguientes 5 min, sin que la UI
   necesite volver a llamar.
5. WHEN la respuesta de `POST` es `422`, THE SYSTEM SHALL mostrar copia
   localizada por **status HTTP**, sin leer el cuerpo —la norma del proyecto
   prohíbe pintar el `422` del backend, mismo criterio que `pricing-web`
   R3.7/R3.8.

### R6 — El detalle de la reseña: lo que la IA rellenó y lo que la persona decide

**As a** propietaria o manager, **I want** abrir una reseña y leer su texto
original, su análisis y su borrador, **so that** pueda decidir con el
contexto completo.

Acceptance criteria:

1. WHEN la usuaria abre el detalle de una reseña (en la misma pestaña,
   encima del listado, sin ruta hija), THE SYSTEM SHALL pedir
   `GET /api/v1/reviews/{id}` y, si la reseña está en `DRAFTED` (único
   estado en el que existe borrador editable, R3.3 arriba), también
   `GET /api/v1/reviews/{id}/response` para pintar el borrador.
2. THE SYSTEM SHALL pintar, en este orden: `content` (prosa del huésped), el
   `reviewer_name` si existe, `rating`, `channel`, `published_at`, `sentiment`
   localizado, `ai_summary` localizado y etiquetado como
   *«Resumen automático»* (no como más de lo que es — la pipeline es por
   palabras clave y el backend no usa IA real, `revenue-reviews` R2.4),
   `recurring_issues` como etiquetas localizadas, y `draft_content` cuando
   exista, también etiquetado como *«Borrador propuesto»*.
3. THE SYSTEM SHALL pintar el `content` y el `draft_content` como texto y
   nunca como HTML, con etiqueta localizada alrededor (regla 11: prosa de
   tercero el primero, vocabulario cerrado el segundo).
4. THE SYSTEM SHALL incluir en el detalle los **controles de decisión** que
   correspondan al estado actual y al rol de la usuaria, según R3.1, R3.2,
   R3.3 y R4.1: el manager ve **Editar borrador** si la reseña está en
   `DRAFTED` (no en `APPROVED`, R3.3); la owner ve **Aprobar**/**Ignorar**/**Editar
   borrador** en `DRAFTED` y **Marcar como publicada** en `APPROVED` (sin
   edición, R3.3). Lo que no le toque por permiso **no se renderiza**, y el
   backend es la autoridad si se cuela un `403`.
5. THE SYSTEM SHALL NOT pintar `classification_attempts` (es un contador
   interno del job de clasificación y `reviews.spec` R2.4 lo explica como
   detalle de运维 que la UI no necesita), `created_at` ni `updated_at` —la
   fecha visible es `published_at`.

### R7 — El espejo de permisos, acertado para los dos roles

**As a** propietaria o manager, **I want** ver los controles que me tocan y
sólo esos, **so that** un `403` del backend no me llegue disfrazado de éxito
tras pulsar un botón que el frontend me ofreció.

Acceptance criteria:

1. THE SYSTEM SHALL ampliar la unión `Permission` de
   `frontend/lib/auth/permissions.ts` con dos miembros:
   `"MANAGE_REVIEW_DECISIONS"` (aprobar / ignorar / marcar-como-publicada) y
   `"CREATE_REVIEW_UI"` (alta a mano y edición de borrador).
2. THE SYSTEM SHALL conceder `MANAGE_REVIEW_DECISIONS` a `TENANT_OWNER` **y**
   `CREATE_REVIEW_UI` a `PROPERTY_MANAGER`, **sin** conceder ninguno a
   `CLEANER`, `TECHNICIAN` ni `SUPER_ADMIN`. **Esto es una elección de UX,
   no una consecuencia del backend**: `auth/domain/policy.py` concede al
   `PROPERTY_MANAGER` los cinco permisos de review (`_REVIEW_MANAGE` en
   `policy.py:309-316`, agregados en `policy.py:434`), y la nota 432-433
   documenta explícitamente que «PRD §18 y R4.2 give every action of the flow
   to the manager». El frontend **esconde** aprobar / ignorar /
   marcar-como-publicada al manager por el reparto de trabajo que el roadmap
   enuncia — *«el owner aprueba, ignora y marca como publicada; el manager
   crea»*— y porque el PRD §18 modela la aprobación como decisión de la
   propietaria, no como tarea operativa del manager. **Si un manager dispara
   `PATCH /reviews/{id}/response` por la API directamente, el backend lo
   acepta** — el espejo es pista de UX, no autoridad.
3. THE SYSTEM SHALL NOT copiar la forma de `MANAGE_CLEANING_TASKS`
   (`TENANT_OWNER: []`): eso dejaría a la propietaria mirando una cola que no
   puede decidir, con los botones ocultos por el propio frontend mientras el
   backend se los concedía.
4. THE SYSTEM SHALL tratar el espejo como pista de UX y no como autoridad: el
   RBAC del backend decide y el frontend sólo oculta. Si un permiso futuro
   amplia la matriz, el frontend no tiene que conocerlo por anticipado — el
   espejo declara sólo lo que la UI pinta.

### R8 — i18n, dinero y estado en dos locales

**As a** usuaria en español o inglés, **I want** leer la pantalla en mi
idioma sin ninguna cadena técnica a la vista, **so that** operar reseñas no
sea un ejercicio de traducción sobre la marcha.

Acceptance criteria:

1. THE SYSTEM SHALL crear el namespace `reviews` en `locales/es/` y
   `locales/en/` y registrarlo en `lib/i18n/resources.ts` en sus **cuatro**
   puntos (el `import` por locale, la lista `NAMESPACES`, y la entrada dentro
   de `resources.es` y `resources.en`).
2. THE SYSTEM SHALL proveer etiqueta localizada en ES y EN para **todos**
   los miembros de cada enum que la pantalla pinta: los **cinco** valores de
   `ReviewStatus` (`NEW`, `DRAFTED`, `APPROVED`, `POSTED_MANUALLY`,
   `IGNORED`), los **tres** de `ReviewSentiment` (`POSITIVE`, `NEUTRAL`,
   `NEGATIVE`), los **cinco** valores del enum `ReviewChannel` que el
   diálogo de alta expone (`AIRBNB`, `BOOKING`, `GOOGLE`, `MANUAL`, `OTHER`),
   y los
   **nueve** valores de `RecurringIssueTag` (`WIFI`, `NOISE`,
   `CLEANLINESS`, `ACCESS`, `COMMUNICATION`, `LOCATION`, `VALUE`,
   `AMENITIES`, `OTHER`). El test de locales recorre cada enum desde los
   tipos generados y exige su entrada en los dos locales.
3. THE SYSTEM SHALL formatear `rating` como `/5` con el separador decimal
   del locale activo (coma en ES, punto en EN), reutilizando el patrón de
   `features/incidents/.../incident-detail-sections.tsx`.
4. THE SYSTEM SHALL formatear `published_at` como día del locale sin hora y
   sin conversión de zona, y SHALL NOT inventar marca temporal de decisión
   —el DTO no expone `auded_at` ni `updated_at` en el contrato que la UI
   consume (ver `ReviewResponse` en `openapi.d.ts`).
5. THE SYSTEM SHALL NOT dejar ninguna string visible sin traducir —las
   etiquetas de los cinco estados y tres sentimientos, los nombres de las
   nueve etiquetas de problemas recurrentes, los textos de los cuatro
   botones y sus confirmaciones, y las copias de vacío, error, `409` y
   `422`.

## Out of scope

- **`POST /api/v1/reviews/{id}/response`** (regenerar el borrador con
  `action = REGENERATE` o similar) — la ruta existe en el spec
  ([R3.5](../specs/revenue-reviews.md)) y exige el mismo permiso que
  aprobar, pero el botón de **regenerar** queda fuera de esta entrega: si
  la usuaria quiere un borrador nuevo espera al siguiente ciclo de
  `classify_reviews` (5 min). Un botón de regeneración aquí sería otra
  mutación con `409` ante transiciones inválidas, y su valor real es
  marginal contra la latencia del job —queda como candidata `[FE]` para un
  futuro change.
- **Edición libre del `ai_summary`** — el campo es output de la pipeline y
  el spec no expone un endpoint para sobreescribirlo. La UI lo pinta en
  lectura, y la edición del borrador (`draft_content`) es lo que la manager
  modifica —no el resumen.
- **Búsqueda full-text sobre `content`** — el spec R5.3 enumera filtros
  pero no full-text; queda como mejora posterior.
- **Notificación al owner de un borrador nuevo más allá de
  `notification-writers-gap`** — ya cubierta por `REVIEW_RESPONSE_APPROVED`
  en `R6.2` del spec. Una notificación al crearse el borrador sería ruido
  (la pipeline es automática).
- **Cambios en el backend de `reviews`** — el contrato está congelado y
  archivado; `frontend/lib/api/generated/openapi.d.ts` ya declara las
  siete rutas y los cinco enums, y `backend/openapi.json` se regenera **sin
  tocar el contrato** (workaround documentado en `sdd/project.md`).
- **Historial de auditoría en pantalla** — el rastro vive en `AuditLog`
  con `REVIEW_APPROVED`/`REVIEW_IGNORED`/`REVIEW_DRAFT_EDITED` y en los
  `TimelineEvent`s del spec; ninguno tiene superficie aquí.
- **Cambios en el registro de ruta ni en `navigation.json`** — el descriptor
  `reviews` ya existe con `match: "exact"` y las claves i18n del sidebar ya
  están en los dos locales.

## Affected specs

- `sdd/specs/revenue-reviews.md` — se amplía con la superficie de frontend
  que consume las siete operaciones, y se cierra la frase *«No incluye UI
  — la pantalla del manager es otro change»*, que a partir del merge deja
  de ser cierta.
- `sdd/specs/frontend-foundation.md` — su inventario de `frontend/app/`
  pasa de «cinco placeholder pages» a **cuatro** (verificado hoy: cinco
  páginas con `RoutePlaceholder` — `settings`, `settings-integrations`,
  `statements`, `reviews`, `forgot-password` — y la última no entra en
  este count porque es de `(public)` y el spec lista las del workspace).
  Se registra además el namespace `reviews` en la lista de catálogos de
  traducción.
- `sdd/specs/auth-tenancy.md` — **no se modifica**: los cinco permisos
  `READ_REVIEWS`, `CREATE_REVIEW`, `APPROVE_REVIEW`, `IGNORE_REVIEW`,
  `MARK_REVIEW_POSTED` ya están en el `Permission` enum del backend y
  `ROLE_PERMISSIONS` ya los reparte entre `TENANT_OWNER` y
  `PROPERTY_MANAGER`. El espejo del frontend se documenta en su propio
  `permissions.ts`, mismo criterio que `approvals-web` aplicó para
  `RESPOND_OWNER_APPROVALS`.
- `sdd/specs/frontend-auth-session.md` — **no se modifica**: se consume
  tal cual (tokens en memoria, `AuthGuard` sobre la ruta workspace,
  refresh coordinado por el cliente HTTP).
- `sdd/specs/frontend-api-contract-consumer.md` — **no se modifica**: el
  cliente tipado ya incluye las siete operaciones de reviews; la
  regeneración de `openapi.json` no modifica el contrato.