# Proposal: conversations-inbox

## Why

`/conversations` es hoy un `RoutePlaceholder` (`routeId="conversations"` en
`frontend/app/(workspace)/conversations/page.tsx`): la ruta existe en el registro tipado y
aparece en la navegación del workspace, pero renderiza el placeholder del shell. PRD §24 la
declara como «bandeja de mensajes», PRD §26 la pone en el puesto 21 y PRD §30 la prioriza en
el #5 (mensajería/escalado). El backend ya expone los siete endpoints de
`sdd/specs/messaging-ai.md` R7, el cliente tipado del frontend los conoce desde
`api-contract-export` + `frontend-api-contract-consumer`, y `docs/messaging-ai.md` lo dice
explícitamente: «No hay frontend todavía: la bandeja de /conversations es de
`conversations-inbox`». La negociación de formas ya está cerrada.

**Limitación de demo que se declara antes de empezar**: `backend/app/cli/seed_demo.py` no
siembra `Conversation` ni `Message` (verificado: no existe `_seed_conversations` ni equivalente;
la única conversación que crea el seed es de `Incident`, no de `messaging`). La bandeja
abrirá **vacía** en el entorno demo y `make seed-demo` mostrará legítimamente el estado
vacío localizado del R2.4 — esta es la condición esperada de la demo, no un fallo. Las
conversaciones nacen por un evento externo a esta entrada —un mensaje del huésped a través
del portal, una escalación automática desde el pipeline de `messaging-ai` R4, o una
transcripción manual desde el panel de gestión— y este change **no** las crea:
`POST /api/v1/conversations` está explícitamente fuera de alcance (ver «Out of scope»).
Para demostrar list / detail / reply fuera del entorno de tests, el operador de la demo
necesita una conversación **previamente** creada por otra capability o productor legítimo
de la API (p. ej. el pipeline de `messaging-ai` R4 disparado desde un `Incident` con intent
`MAINTENANCE_ISSUE` / `ACCESS_PROBLEM`, o el portal del huésped si su change ya estuviera
mergeado); sin esa conversación previa, la bandeja muestra el estado vacío del R2.4, que
es el comportamiento correcto. Si la demo sistemática requiere conversaciones precargadas,
eso es una **futura extensión del seed**, no del FE, y queda fuera de esta entrada.

Entrada de roadmap: `conversations-inbox` (`needs: messaging-ai, frontend-auth-session`,
ambas archivadas; size M, cuarta de la frontera al abrir esta propuesta).

## What changes

Existirá una pantalla `/conversations` con la bandeja de conversaciones del tenant —
listado paginado y filtrable por `status` y `escalation_status`, ordenado por
`last_message_at` descendente con nulos al final (regla de negocio del backend,
`sdd/specs/messaging-ai.md` R7)— y una pantalla `/conversations/[id]` con el hilo de una
conversación: sus mensajes en orden cronológico ascendente y la respuesta manual del
operador. La única mutación de esta entrada es `POST /api/v1/conversations/{id}/messages`
(la respuesta humana, con `sender_type` omitido —el backend lo deriva del rol del
caller—); las demás mutaciones del agregado (`POST /conversations`, `POST /escalate`,
`POST /resolve`) quedan fuera.

No se introduce ni se modifica ningún endpoint backend: los siete de `messaging-ai` R7 ya
están publicados y `backend/openapi.json` + `frontend/lib/api/generated/openapi.d.ts`
están sincronizados con la rama (verificado por inspección directa del OpenAPI y del
cliente tipado). Por tanto **no se regenera el contrato** en este change — la regeneración
corresponde al change de backend que modifique un endpoint, según
`sdd/specs/frontend-api-contract-consumer.md`. La superficie a entregar es:

- `frontend/features/conversations/` con data layer (HTTP source + tipos derivados del
  cliente tipado, sin mock de dominio), hooks de TanStack Query (`useConversations`,
  `useConversation`, `useConversationMessages`, `useReplyToConversation`), componentes de
  lista, hilo, etiqueta de estado y badge de escalación.
- `frontend/app/(workspace)/conversations/page.tsx` sustituye el `RoutePlaceholder` por
  `<ConversationsInboxView />`.
- `frontend/app/(workspace)/conversations/[id]/page.tsx` nueva, renderiza
  `<ConversationThreadView />`.
- `frontend/features/shell/navigation/route-registry.ts` registra `conversation-detail`
  con `pattern: "/conversations/[id]"`, `match: "exact"`, **sin** `href` y **sin**
  `navigationGroup`, replicando la forma de `property-detail` (`route-registry.ts:114-122`),
  `reservation-detail` (`route-registry.ts:137-145`) e `incident-detail`
  (`route-registry.ts:124-138` ya cubre la asimetría del `[id]` en PRD §24).
- `frontend/locales/{es,en}/navigation.json` añaden las claves
  `routes.conversation-detail.{title,description}`.
- `frontend/locales/{es,en}/conversations.json` (nuevo) con títulos, descripciones,
  etiquetas de los cuatro `ConversationStatus`, los cuatro `ConversationEscalationStatus`,
  los cinco `MessageSenderType` visibles al manager, copy de carga / error / vacío /
  «sin mensajes», copy del formulario de respuesta (placeholder, botón, error de longitud),
  copy del badge «escalado a humano».

El shell del workspace no cambia: las claves `routes.conversations.{title,description}` ya
estaban y ya prometen «Bandeja de conversaciones». La sesión autenticada viene de
`frontend-auth-session`, y la autorización RBAC del backend (R7 de `messaging-ai.md`) es
quien realmente decide a qué datos llega cada usuario — `MANAGER` y `OWNER` ven el inbox
del tenant con `READ_CONVERSATIONS` (la propietaria **lee** y no opera, per `messaging-ai`
D17 / `docs/messaging-ai.md` RBAC), y solo `MANAGER` recibe `MANAGE_CONVERSATIONS` para
contestar (la UI lo aplica como `useHasPermission("MANAGE_CONVERSATIONS")` que oculta el
formulario al `OWNER`). El aislamiento por tenant lo fuerza el `JOIN` con `conversations`
que la spec R1 declara como **único** mecanismo de aislamiento (no es defensa en
profundidad).

## Requirements

### R1 — Shell: ruta `/conversations/[id]` y registro del detalle

**As a** usuario autenticado del workspace, **I want** que `/conversations` muestre contenido
y que `/conversations/[id]` exista como destino navegable desde la lista, **so that** la
primera entrada `[FE]` del roadmap sobre el módulo `messaging` quede resuelta y el flujo
lista → hilo sea profundo-enlaceable.

Acceptance criteria:

1. WHEN se navega a `/conversations`, THE SYSTEM SHALL mostrar el listado de conversaciones
   (R2) en lugar de un `RoutePlaceholder`.
2. THE SYSTEM SHALL registrar `conversation-detail` en
   `frontend/features/shell/navigation/route-registry.ts` con `pattern:
   "/conversations/[id]"`, `match: "exact"`, **sin** `href` y **sin** `navigationGroup`
   —no aparece en la barra lateral, se llega solo desde la lista—, y `breadcrumbKeys:
   crumbs("conversations", "conversation-detail")`, replicando la forma de
   `property-detail` (líneas 114-122), `reservation-detail` (líneas 137-145) e
   `incident-detail` (líneas 124-138).
3. THE SYSTEM SHALL crear las claves `routes.conversation-detail.title` y
   `routes.conversation-detail.description` en `frontend/locales/{es,en}/navigation.json`,
   **sin** hardcodear la cadena en ningún componente.
4. WHEN se navega a `/conversations/[id]` con un `id` válido del tenant, THE SYSTEM SHALL
   mostrar el hilo (R3).
5. THE SYSTEM SHALL extender la lista `PRD_24_SURFACES` de `route-registry.test.ts` con
   `/conversations/[id]`, igual que ya contiene `/incidents/[id]`, `/properties/[id]` y
   `/reservations/[id]`: la lista es de **superficies de navegación** con id, y la
   asimetría de excluir el hijo parametrizado sería una sorpresa para el siguiente
   descriptor detail.
6. THE SYSTEM SHALL añadir la página Next.js `frontend/app/(workspace)/conversations/[id]/page.tsx`
   que renderiza `<ConversationThreadView />` (R3).

### R2 — Listado paginado y filtrable en `/conversations`

**As a** manager o propietario del workspace, **I want** ver y paginar las conversaciones
del tenant con filtros por estado y por estado de escalación, **so that** la bandeja deje
de ser un placeholder y refleje lo que el backend ya sirve.

Acceptance criteria:

1. WHEN `/conversations` se monta autenticado, THE SYSTEM SHALL llamar a
   `GET /api/v1/conversations` con el `tenantId` implícito en el token y renderizar la
   respuesta.
2. THE SYSTEM SHALL pasar al endpoint, cuando la UI los exponga, los parámetros de filtro
   que correspondan: en v1, `status` y `escalation_status`, además de `page` y `per_page`.
   **El endpoint soporta `property_id` pero esta UI no lo expone en v1** — añadir el
   selector de propiedad exigiría un `usePropertiesList` contra `GET /api/v1/properties`
   con su propio estado, deep-linking y ciclo de cache, y sale de `size: M` (es el mismo
   movimiento que `reservations-web` D4 documentó para excluir `property_id` en v1 y que
   `incidents-web` R2.2 volvió a aplicar). El contrato del backend no se reabre.
3. THE SYSTEM SHALL consumir el sobre `ConversationPageResponse` —
   `{items, total, page, per_page}` de `messaging-ai.md` R7— y SHALL **no** asumir la
   forma `{data, ...}` que otros módulos del frontend puedan usar.
4. WHEN la lista carga, THE SYSTEM SHALL mostrar el estado de carga accesible definido en
   `frontend-foundation` (`LoadingState`, `aria-busy`); WHEN la llamada falla, THE
   SYSTEM SHALL mostrar `ErrorState` con `role="alert"` y acción de reintento localizada;
   WHEN el sobre llega con `items` vacío, THE SYSTEM SHALL mostrar el estado vacío
   localizado —los tres estados ya tienen precedente en el resto del frontend.
5. THE SYSTEM SHALL permitir al usuario avanzar y retroceder de página usando `page` y
   `per_page`, y SHALL deshabilitar los controles en el extremo correspondiente cuando
   `page = 1` o `page = lastPage`. **El backend no expone `total_pages`** en
   `ConversationPageResponse` (`backend/openapi.json:955-985`: el sobre es `{items, total,
   page, per_page}`, sin `total_pages`), así que la última página SHALL derivarse en el
   cliente como `lastPage = max(1, ceil(total / perPage))`; si `total = 0`, `lastPage = 1`
   y ambos controles quedan deshabilitados.
6. THE SYSTEM SHALL pasar `status` y `escalation_status` como enums tipados
   (`ConversationStatus` y `ConversationEscalationStatus` del `openapi.d.ts`), **no** como
   cadenas sueltas, para que un valor inválido del lado de la UI falle en la compilación y
   no en runtime.
7. THE SYSTEM SHALL construir la query key del listado como
   `conversationsKeys.list(tenantId, filters)` pasando el **objeto de filtros
   normalizado directamente** como último segmento (precedente:
   `reservationsKeys.list(tenantId, filters)` y `incidentsKeys.list(tenantId, filters)`),
   sin `JSON.stringify` y con claves en orden estable, de modo que dos renders con los
   mismos filtros produzcan la misma key y TanStack Query no duplique cache.
8. THE SYSTEM SHALL mostrar la etiqueta localizada de `status` y de `escalation_status` en
   cada fila, y SHALL destacar visualmente las conversaciones con `escalation_status`
   distinto de `NONE` (PENDING_HUMAN, HUMAN_HANDLING, RESOLVED) —es la única heurística
   de inbox útil sin un campo explícito de prioridad— con un badge de color semántico
   coherente con `dashboard-web` §Property operational states y con la convención del
   workspace.

### R3 — Hilo de una conversación en `/conversations/[id]`

**As a** manager o propietario del workspace, **I want** abrir una conversación por su
enlace y leer todos sus mensajes en orden, **so that** la consulta puntual desde la
bandeja, desde notificaciones o desde un deep link externo sea posible sin volver al
listado.

Acceptance criteria:

1. WHEN se navega a `/conversations/[id]` con un `id` del tenant, THE SYSTEM SHALL llamar
   a `GET /api/v1/conversations/{id}` y SHALL renderizar `ConversationResponse` con sus
   mensajes, obtenidos por `GET /api/v1/conversations/{id}/messages`.
2. THE SYSTEM SHALL mostrar los campos de la conversación: `id`, `property_id`,
   `reservation_id`, `guest_id`, `channel`, `status`, `escalation_status`, `language`,
   `ai_enabled`, `last_message_at`, `created_at`, `updated_at`. El canal
   (`ConversationChannel`) y los dos ejes (`ConversationStatus`,
   `ConversationEscalationStatus`) SHALL localizarse con etiqueta en el idioma activo;
   los seis valores de `ConversationChannel` —`WHATSAPP`, `AIRBNB_MSG`, `BOOKING_MSG`,
   `EMAIL`, `PHONE_TRANSCRIPT`, `MANUAL`— SHALL aparecer en `conversations.json` aunque
   tres de ellos (`AIRBNB_MSG`, `BOOKING_MSG`, `WHATSAPP` desde PMS) sean «mute by
   design» hoy: el FE localiza **exactamente** los valores que la API expone, no un
   subconjunto (mismo criterio que `incidents-web` R4.3 para las trece `IncidentCategory`).
3. THE SYSTEM SHALL mostrar los mensajes en orden **cronológico ascendente**
   (`messaging-ai.md` R7 — «una conversación se lee hacia adelante, al revés que el
   timeline, que es un feed»), paginados con `page`/`per_page`, derivando `lastPage` en
   cliente por la misma fórmula que R2.5.
4. THE SYSTEM SHALL renderizar cada `Message.content` como **texto plano**, **nunca**
   como HTML. Esto es una exigencia material: `messages.content` está declarado en la
   regla 11 de `steering/security.md` como sumidero de texto en claro, con dos formas —
   prosa de tercero (`sender_type = GUEST`, R3) o forma cerrada (`ai_generated = true`,
   R3—), y la regla 11 lo prohíbe explícitamente. **Ningún** componente del hilo SHALL
   usar `dangerouslySetInnerHTML`, SHALL usar `ReactMarkdown`/`MDX`, SHALL parsear URLs a
   `<a>`, SHALL colorear markdown, SHALL autolinkear ni SHALL ejecutar ninguna
   transformación que interprete el texto. El escape SHALL ser responsabilidad del
   renderizador (React ya escapa por defecto en nodos de texto); SHALL añadirse un test
   que renderice un `content` con `<script>alert(1)</script>` y compruebe que el `<script>`
   aparece como texto literal y que la alerta no se ejecuta.
5. THE SYSTEM SHALL distinguir visualmente los mensajes por `sender_type` con un
   indicador de rol (etiqueta localizada: `Tú`, `Huésped`, `IA`, `Sistema`, `Propietario`),
   aplicando la convención del workspace. SHALL localizar los cinco miembros de
   `MessageSenderType` —`GUEST`, `OWNER`, `MANAGER`, `AI`, `SYSTEM`— en
   `conversations.json`. WHEN `sender_type = AI`, SHALL mostrar también el `intent` del
   mensaje si está presente (campo libre `intent` en `MessageResponse`); WHEN
   `ai_generated = false` y `sender_type` es uno de los nuestros, SHALL mostrar el
   `sender_user_id` **fuera** del bloque principal del mensaje, **sin** tooltip de copia,
   **sin** botón «copiar UUID» y con una nota localizada que documente la limitación: el
   id no puede resolverse a nombre dentro de `size: M` porque no hay `GET /api/v1/users`
   en el contrato ni se introduce uno aquí. La nota aparece una sola vez, en la sección
   secundaria donde vive el campo.
6. THE SYSTEM SHALL respetar el principio «mensajes append-only» de `messaging-ai.md`
   R1 — no SHALL ofrecer botones de edición, borrado o reordenación de mensajes
   individuales; SHALL ofrecer solo la acción de **responder como humano** (R4).
7. WHEN la carga del hilo falla por `404`, THE SYSTEM SHALL mostrar un estado localizado
   de «no encontrado» **distinto** del error genérico (un manager de otro tenant recibe
   el mismo `404` por R1 — la UI no debe filtrar existencia); WHEN falla por `401`/`403`/
   `5xx`, SHALL mostrar el estado de error genérico localizado.
8. THE SYSTEM SHALL mostrar el badge de escalación de la conversación
   (`escalation_status` distinto de `NONE`) en la cabecera del hilo, replicando el de la
   lista y reflejando su cambio tras una respuesta del operador (R4) sin recarga
   explícita —la cache de TanStack Query se invalida por el `useReplyToConversation`
   con `onSuccess` que revalida la query del hilo y de la lista (mismo patrón que
   `useReservationDetail` revalidando `useReservations`).

### R4 — Respuesta humana en `/conversations/[id]`

**As a** manager del workspace (único rol con `MANAGE_CONVERSATIONS` per `messaging-ai`
D17; la propietaria lee pero no opera), **I want** responder manualmente a una
conversación que la IA ha escalado o que requiere intervención, **so that** el huésped
reciba una respuesta de una persona y la conversación pase a `HUMAN_HANDLING` (R5 de
`messaging-ai.md`: `take_over` ocurre como efecto lateral del POST `/messages` cuando la
conversación esperaba a una persona).

Acceptance criteria:

1. THE SYSTEM SHALL mostrar un formulario de respuesta en `/conversations/[id]` con un
   campo de texto multilínea, un botón «Enviar» localizado y un contador de caracteres
   visible que SHALL avisar cuando se acerque al límite (`MAX_MESSAGE_CONTENT_LENGTH =
   4000` caracteres, `messaging-ai.md` R3 último párrafo; el esquema Pydantic
   `CreateMessageRequest` rechaza con `422` si se supera, verificado en
   `backend/openapi.json:1253-1257`).
2. WHEN el operador envía el formulario, THE SYSTEM SHALL llamar a
   `POST /api/v1/conversations/{id}/messages` con `{content}` y **sin** `sender_type` —
   el backend deriva `sender_type` del rol del llamante (`messaging-ai.md` R7: «WHERE
   `POST /messages` es **una ruta con dos comportamientos**… omitido, el llamante
   contesta él mismo»). Si el cliente envía `sender_type`, el backend responde `422`
   (`openapi.json:1258-1268`: el tipo es `Literal["GUEST"] | null`, no la enum completa);
   la UI SHALL **no** enviar nunca `sender_type` en esta ruta.
3. THE SYSTEM SHALL deshabilitar el botón «Enviar» mientras la mutación está en vuelo y
   SHALL mostrar un estado de error localizado si falla (`401`/`403`/`422`/`5xx`),
   manteniendo el texto escrito por el operador en el campo para que no tenga que
   reescribirlo.
4. WHEN la mutación resuelve `201`, THE SYSTEM SHALL limpiar el campo de texto, SHALL
   invalidar la query de mensajes del hilo (`conversationMessagesKeys.list`) y SHALL
   invalidar la query de la conversación (`conversationKeys.detail`) **y** la query de la
   lista (`conversationsKeys.list`) —para que el `last_message_at`, `status` y
   `escalation_status` de la fila de la bandeja reflejen el cambio—, sin recarga manual.
   El nuevo mensaje del propio operador SHALL aparecer en el hilo al volver a montar la
   vista (TanStack Query re-fetcha al revalidar).
5. THE SYSTEM SHALL **no** exponer un botón «Escalar» (`POST /escalate`) ni un botón
   «Resolver» (`POST /resolve`): la escalación la dispara el pipeline del backend
   automáticamente cuando se cumplen las condiciones de R5, y la resolución tiene su
   propia UX de confirmación y permiso que vive en una entrada posterior. Esta entrada
   cubre la única mutación que el PRD §13 «Manual (panel)`ManualConversationAdapter`»
   implica como acción directa del manager: responder.

### R5 — Enumeraciones etiquetadas y superficie i18n

**As a** manager o propietario, **I want** que los cuatro `ConversationStatus`, los cuatro
`ConversationEscalationStatus`, los seis `ConversationChannel` y los cinco
`MessageSenderType` se muestren con etiqueta en mi idioma, **so that** el estado real de
cada conversación sea legible y no dependa de traducir la constante a mano.

Acceptance criteria:

1. THE SYSTEM SHALL localizar las cuatro etiquetas de `ConversationStatus`: `OPEN`,
   `RESOLVED`, `ESCALATED`, `CLOSED`.
2. THE SYSTEM SHALL localizar las cuatro etiquetas de `ConversationEscalationStatus`:
   `NONE`, `PENDING_HUMAN`, `HUMAN_HANDLING`, `RESOLVED`.
3. THE SYSTEM SHALL localizar las seis etiquetas de `ConversationChannel`:
   `WHATSAPP`, `AIRBNB_MSG`, `BOOKING_MSG`, `EMAIL`, `PHONE_TRANSCRIPT`, `MANUAL`.
4. THE SYSTEM SHALL localizar las cinco etiquetas de `MessageSenderType`: `GUEST`,
   `OWNER`, `MANAGER`, `AI`, `SYSTEM`.
5. THE SYSTEM SHALL definir las claves en `frontend/locales/es/conversations.json` y
   `frontend/locales/en/conversations.json` y SHALL usarlas desde el componente, sin
   string hardcodeado.
6. THE SYSTEM SHALL aplicar la misma etiqueta localizada al badge de la lista, al badge
   de la cabecera del hilo y al indicador de rol del mensaje (R3.5), de modo que un valor
   del backend no se traduzca a mano en ningún punto.

### R6 — Tenancy, free-text sink y patrones del frontend

**As a** mantenedor, **I want** que esta entrada cumpla las reglas de
`steering/security.md` y `steering/frontend.md` sin excepciones, **so that** el panel de
revisión no la devuelva por defectos ya conocidos y conocidos tres veces en otros
módulos.

Acceptance criteria:

1. THE SYSTEM SHALL mantener server state con TanStack Query v5, con una clave por
   recurso que incluya el `tenantId`, y SHALL **no** duplicar server state en Zustand u
   otro store.
2. THE SYSTEM SHALL **no** contener ningún string de UI en código: todo vive en
   `frontend/locales/{es,en}/`, y SHALL cubrir al menos los títulos, descripciones,
   etiquetas de las cuatro enumeraciones (R5), textos de carga/errores/vacío, cabecera y
   cuerpo del hilo, copy del formulario de respuesta y notas de la limitación del UUID
   del sender.
3. THE SYSTEM SHALL usar el cliente HTTP centralizado (`lib/api`) para todas las
   llamadas autenticadas; SHALL **no** usar `fetch` directo. NO SHALL usar mocks de
   dominio en la superficie final — los mocks solo entran en tests; el `features/
   conversations/data/` SHALL consumir el cliente HTTP y nunca un `MockConversationSource`
   paralelo al dashboard (que ya se retiró al hacer `dashboard-web`).
4. THE SYSTEM SHALL distinguir los códigos de error del backend al menos para los casos
   usados por la UI: `401` (sesión expirada, gestiona `frontend-auth-session`), `403`
   (sin permiso, error localizado), `404` (R3.7), `422` (validación: **estado localizado
   exclusivo** — SHALL **no** leer, mapear ni exponer `message`, `details`, `code` ni el
   cuerpo del envelope de PRD §23; muestra únicamente copy localizado del frontend) y
   `5xx` (error genérico).
5. THE SYSTEM SHALL **nunca** renderizar `messages.content`, `Conversation` description
   libre (ninguna en este agregado) ni ningún texto recibido como HTML. La regla 11 de
   `steering/security.md` ya documenta esta misma clase de riesgo tres veces; SHALL
   añadirse un test que lo verifique (R3.4).
6. THE SYSTEM SHALL construir las query keys incluyendo el `tenantId` y SHALL pasar el
   objeto de filtros normalizado directamente como segmento final (R2.7), con claves en
   orden estable y **sin** `JSON.stringify`, para evitar colisiones de cache entre
   tenants y entre filtros.
7. THE SYSTEM SHALL añadir tests de componente con Testing Library para la lista, el hilo
   y el formulario de respuesta, cubriendo al menos: render del estado de carga, render
   del sobre con datos, render del estado vacío, render del error de la lista y del
   hilo, render de un mensaje con `<script>` como texto plano (R3.4), envío exitoso del
   formulario (mockeando solo el cliente HTTP, **no** el dominio), envío con error `422`
   de longitud, y respuesta a una conversación `PENDING_HUMAN` reflejando el badge
   actualizado tras la mutación.

## Out of scope

- **Seed de conversaciones y mensajes** — `seed-data-demo` no siembra `Conversation`/
  `Message` (verificado: `backend/app/cli/seed_demo.py` no tiene `_seed_conversations`
  ni equivalente; el único escritor de producción hoy es el pipeline de `messaging-ai`
  R4). En la demo, `make seed-demo` deja la bandeja legítimamente vacía y el R2.4 muestra
  el estado vacío localizado — este es el comportamiento esperado, no un defecto.
  Cualquier conversación que se necesite para demostrar list / detail / reply fuera de
  tests debe existir **previamente** por otra capability o productor legítimo de la API;
  este change **no** añade creación de conversaciones (siguiente bullet) ni siembra el
  seed. Si la demo sistemática requiere conversaciones precargadas, eso es una **futura
  extensión del seed**, no del FE, y queda fuera de esta entrada. La bandeja **es
  funcional** con la API sola.
- **Mutaciones del agregado distintas de responder**:
  - `POST /api/v1/conversations` (crear): no se invoca desde el panel; las conversaciones
    nacen por el pipeline de `messaging-ai` R4 (`MAINTENANCE_ISSUE`/`ACCESS_PROBLEM`) o
    por el portal del huésped, no por el manager. Su entrada de UI, si llegara, tendría
    su propia UX con `property_id` requerido y validación de canal «mute by design»
    (`messaging-ai.md` R7, `backend/openapi.json:8860`).
  - `POST /api/v1/conversations/{id}/escalate`: la escalación la dispara el pipeline
    automáticamente cuando se cumplen las condiciones de R5 (`EMERGENCY_KEYWORD`,
    `LOW_CONFIDENCE`, `EMERGENCY_INTENT`, etc.). No se ofrece botón en la UI: sería
    superficie de UI sin significado operacional, porque la conversación **ya está
    escalada** si el manager está leyendo el hilo.
  - `POST /api/v1/conversations/{id}/resolve`: pertenece a la superficie de cierre con
    confirmación, su propio permiso (`MANAGE_CONVERSATIONS`) y su auditoría, y al
    roadmap no le urge esta entrada.
- **Resolución nombre↔id de `sender_user_id`** — el id no se puede resolver a nombre
  porque no hay `GET /api/v1/users` con permiso de leer otros usuarios y abrir uno sale
  de `size: M`. El campo vive fuera del bloque principal del mensaje con una nota
  localizada que lo dice (R3.5). Mismo razonamiento que `incidents-web` R3.8 con
  `assigned_technician_id`.
- **`/cleaner`, `/tech`, `/cleaning`, `/approvals`, `/pricing`, `/statements`,
  `/reviews`, `/settings/*`** — cada una tiene su entrada en el roadmap. No se abren aquí.
- **Dashboard agregado sobre conversaciones** (KPIs de tiempo de primera respuesta,
  recurrencia de intents) — pertenece a la familia `dashboard-api`/`dashboard-web`, no a
  la bandeja.
- **Búsqueda full-text o filtros por texto libre** (`content LIKE %q%`) — el endpoint
  `GET /api/v1/conversations` no lo soporta; añadirlo sería un cambio de contrato BE,
  fuera de `size: M`.
- **Adjuntos / fotos / archivos** — la spec R3 no los contempla y el canal MVP es texto;
  WhatsApp real con adjuntos llega con `beds24-messaging-adapter`, no aquí.
- **Acciones masivas** (selección múltiple, exportación a CSV, filtros guardados) — no
  son read-mostly; primera lectura no las necesita.
- **Notificaciones en tiempo real** — la bandeja se revalida al mutar; un canal en vivo
  es otra capacidad.
- **Cualquier integración con un PMS real** — `messaging-ai.md` deja
  `PMSMessagingPort` vacío y `beds24-messaging-adapter` lo implementa. El PMS es historia
  de `pms-beds24-adapter`, no se invoca aquí.
- **Adaptadores externos reales** (WhatsApp Business, SMTP, modelos IA) — `MockAIAdapter`
  y los adaptadores consola siguen siendo los del MVP. Esta entrada no introduce ni
  enchufa ninguno.
- **`guest-portal` (creación de conversaciones por el huésped)** — vive en una
  capability / change independiente y fuera de scope; aquí se consume la API que aquella
  ya estableció, sin reabrir ni coordinarse con ella.

## Affected specs

- **`sdd/specs/messaging-ai.md`** — esta capacidad ya está documentada y cerrada. Este
  change **no la modifica** (acuerdo explícito, mismo que el de `reservations-web` con
  `specs/reservations.md` y el de `incidents-web` con `specs/maintenance.md`): el
  contrato del backend y la spec de la capacidad no entran en este diff. R7 enumera los
  siete endpoints y sus permisos y se consume tal cual.
- **`sdd/specs/frontend-auth-session.md`** — no se modifica. Se consume tal cual está:
  tokens en memoria, `AuthGuard` sobre la ruta workspace y refresh coordinado por el
  cliente HTTP. Cualquier cambio a esa superficie (p. ej. sobrevivir a un reload) es una
  entrada propia.
- **`sdd/specs/frontend-api-contract-consumer.md`** — no se modifica. El cliente tipado
  ya incluye los siete endpoints de `/conversations`; este change los consume sin
  regenerar el contrato (no se modifica ningún endpoint, no se añade ninguno).
- **`sdd/specs/frontend-foundation.md`** — no se modifica. El shell, el `RoutePlaceholder`,
  el `route-registry` y sus tests ya están; este change sustituye el placeholder en una
  ruta concreta y añade un descriptor simétrico a `property-detail`, `reservation-detail`
  e `incident-detail`.
- **`sdd/specs/seed-data-demo.md`** — no se modifica. La ausencia de seed de
  conversaciones se declara en «Limitación de demo» del `Why`; añadir conversaciones
  sembradas sería una entrada posterior que afecta al seed y no a esta superficie.
- **`sdd/roadmap.md`** — la entrada `conversations-inbox` ya existe; no se duplica ni se
  modifica. `/sdd:archive` la marcará `[x]` con `→ changes/archive/<…>/` tras el merge,
  siguiendo el mismo procedimiento que `reservations-web` e `incidents-web`.