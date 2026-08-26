# Design: conversations-inbox

## Context

`/conversations` es hoy `frontend/app/(workspace)/conversations/page.tsx` renderizando
`RoutePlaceholder routeId="conversations"`. La ruta está registrada en el shell con su
descriptor completo (`route-registry.ts:179-189`: `id`, `pattern`, `href`, `navigationGroup:
"work"`, `order: 4`, `icon: "MessagesSquare"`) y sus claves i18n
(`routes.conversations.title`/`.description`) ya prometen «Bandeja de conversaciones».

El backend ya expone los siete endpoints de `sdd/specs/messaging-ai.md` R7, todos tipados
en `frontend/lib/api/generated/openapi.d.ts:1091-1155` (enums) y `:220-263` (paths). El
cliente HTTP tipado los conoce desde `api-contract-export` + `frontend-api-contract-consumer`
archivados. La sesión autenticada viene de `frontend-auth-session` archivado. El codebase ya
tiene el patrón completo en `features/incidents/` y `features/reservations/`: `data/dto.ts`
+ `data/http/http-*-source.ts` + `data/index.ts` (composition point) + `hooks/query-keys.ts`
+ `hooks/use-*.ts` + `lib/error-mapping.ts` + `components/list/*.tsx` + `components/detail/*.tsx`
+ `app/(workspace)/.../page.tsx` que sustituye el placeholder. La mutación se modela con
`useMutation` + `retry: false` + invalidación cruzada en `onSettled` (precedente:
`features/cleaning/hooks/use-assign-cleaning-task.ts:33-58`).

Las conversaciones que la bandeja pinta las crea otro productor: el pipeline de `messaging-ai`
R4 (a partir de un `Incident` con intent `MAINTENANCE_ISSUE`/`ACCESS_PROBLEM`), el portal
del huésped, o una transcripción manual. `seed-data-demo` no siembra conversaciones, así que
en demo la bandeja abre legítimamente vacía y el R2.4 muestra el estado vacío localizado.
Este change **no** crea conversaciones: `POST /api/v1/conversations` está explícitamente
fuera de alcance.

## Decisions

### D1 — `data/index.ts` como composition point único; sin seam `ConversationsDataSource` ni `MockConversationsSource`

**Chosen:** módulo `frontend/features/conversations/` con `data/dto.ts`,
`data/http/http-conversations-source.ts`, `data/index.ts` (composition point que instancia
un `HttpConversationsSource` y exporta `getConversationsDataSource()` que devuelve ese
singleton), `hooks/query-keys.ts`, `hooks/use-conversations.ts`,
`hooks/use-reply-to-conversation.ts`, `lib/error-mapping.ts`,
`components/list/conversations-view.tsx`, `components/list/conversations-filters.tsx`,
`components/thread/conversation-thread-view.tsx`,
`components/thread/conversation-thread-messages.tsx`,
`components/thread/conversation-reply-form.tsx`, `index.ts` (barrel). **`data/index.ts`
es el único punto de composición**: ahí se construye el `HttpConversationsSource` con el
`ApiClient` autenticado (precedent: `features/incidents/data/index.ts:19-26`,
`features/reservations/data/index.ts`). **No existe interfaz `ConversationsDataSource`**,
**no existe `MockConversationsSource`** y **no existe `data/mock/`**: el backend existe
desde `messaging-ai` archivado, no hay nada que suplantar, y el precedent de `incidents-web`
D1 y `reservations-web` D1 lo desaconseja explícitamente — la interfaz estaba justificada
en `dashboard-web` porque había una UI preexistente que dependía del mock, y aquí no hay
UI previa. UI y hooks dependen SOLO de `getConversationsDataSource()`, y reemplazar la
implementación (si llegara) es un cambio de una línea confinado a `data/index.ts`.

**Why:** El precedent de `incidents-web` D1 lo discute y descarta para este caso: *"aquí
no hay mock previo que sustituir ni UI previa que respetar: se va directo a HTTP contra
`lib/api`, sin la indirección `Mock*Source` que allí existía sólo porque la UI se adelantó
al backend"*. Mantener la indirección cuando no hay mock que preservar solo añadiría una
capa sin el problema que la justificaba. Las pruebas unitarias del source usan
`vi.fn().mockResolvedValue(...)` contra `ApiClient`, igual que
`http-incidents-source.test.ts`, sin necesidad de un mock por encima. El composition point
se mantiene porque es donde la sesión autenticada cablea el cliente: UI y hooks dependen
SOLO de `getConversationsDataSource()`, y reemplazar la implementación es un cambio de una
línea confinado a `data/index.ts`.

**Rejected:**
- *Interfaz `ConversationsDataSource` + `HttpConversationsSource` + `MockConversationsSource`*
  — patrón de `dashboard-web`, pero no hay UI preexistente que dependa de la interfaz;
  añadirla solo mueve la frontera sin beneficiario.
- *Llamar `ApiClient.request` directamente desde los hooks* — pierde el composition point
  único (los tests del source son la única forma de fijar el contrato HTTP sin levantar la
  suite del navegador, y necesitan un `ApiClient` que poder mockear a nivel de método).

### D2 — Un único fichero de locale nuevo: `conversations.json`

**Chosen:** Crear `frontend/locales/{es,en}/conversations.json` con seis secciones:
`status` (cuatro etiquetas de `ConversationStatus`: `OPEN`, `RESOLVED`, `ESCALATED`, `CLOSED`),
`escalationStatus` (cuatro de `ConversationEscalationStatus`: `NONE`, `PENDING_HUMAN`,
`HUMAN_HANDLING`, `RESOLVED`), `channel` (seis de `ConversationChannel`: `WHATSAPP`,
`AIRBNB_MSG`, `BOOKING_MSG`, `EMAIL`, `PHONE_TRANSCRIPT`, `MANUAL`), `senderType` (cinco de
`MessageSenderType`: `GUEST`, `OWNER`, `MANAGER`, `AI`, `SYSTEM`), `fields` (etiquetas de
columnas de la lista + cabeceras del hilo + copy del formulario de respuesta + nota del UUID
del sender **+ las dos claves de paginación `prevPage` y `nextPage`**) y `thread` (copy
específico del hilo: «Mensajes», «Sin mensajes», «Responder», «Enviar», «Cancelar»,
«Caracteres restantes», placeholders). Reutilizar `frontend/locales/{es,en}/states.json`
para `loading.label`, `error.title`, `error.description`, `error.retry`, `empty.title`,
`empty.description` (son los textos comunes de carga / error / vacío del workspace y ya
existen para todo el frontend).

**Why:** Las seis secciones son específicas de esta capacidad — no las reutiliza otra
feature — y mezclarlas en `states.json`, `incidents.json` o `navigation.json` haría que un
futuro cambio de etiquetas aquí obligara a tocar un fichero que también mira el resto del
workspace. `dashboard.json` ya contiene claves del dashboard agregado (`propertyCode`,
`operationalState`), no de la pantalla de conversaciones. Los textos de carga / error /
vacío **no** se duplican: `states.json` ya los provee para todo el frontend.
`prevPage` / `nextPage` viven en `conversations.json` (sección `fields`) porque ningún
namespace compartido los aloja con un caracter genuinamente genérico — `common.json` y
`states.json` no los tienen, y `incidents.json` los tiene porque son del workspace de
incidencias; reusar el de otro dominio impone una dependencia entre features que no
existe, y crear un namespace nuevo solo por estas dos claves es ceremonia. La
sección `thread` se separa de `fields` para que la lista (`fields`) y el hilo
(`thread`)lean por separado cuando crezca cualquiera de los dos.

**Rejected:**
- *Reutilizar `incidents.json` para `prevPage` / `nextPage`* — el dominio es distinto
  (`incident.status` ≠ `conversation.status`), y crear una dependencia cruzada entre
  features por dos cadenas de paginación impone un acoplamiento sin beneficiario.
- *Crear un namespace compartido nuevo (`pagination.json` o similar)* — solo por
  `prevPage` / `nextPage` es ceremonia; dos claves no justifican un fichero transversal.
  Cuando un tercer workspace necesite las mismas dos cadenas, ahí se decide el
  namespace compartido (o no).
- *Un fichero por enumeración (`status.json`, `channel.json`, etc.)* — seis ficheros para
  una entrada `size: M` es ceremonia.
- *Un fichero por requisito (lista.json, thread.json, form.json)* — tres ficheros para una
  entrada `size: M` es ceremonia; mejor agrupación semántica (`fields` + `thread`).

### D3 — DTOs camelCase, sobre local `ConversationList`, sin genérico reutilizado

**Chosen:** Modelar `ConversationSummaryDto`, `ConversationDetailDto` y `MessageDto`
(camelCase) como tipos UI, y mapear las respuestas de la API con funciones explícitas —
un `mapConversationSummary`, un `mapConversationDetail`, un `mapMessage` — siguiendo el
precedent de `http-incidents-source.ts:14-49`. `ConversationPageResponse` (sobre `{items,
total, page, per_page}`) se tipifica con `ConversationSummaryDto` dentro; `MessagePageResponse`
(misma forma) con `MessageDto` dentro. El DTO de detalle **no** se mete el en el sobre,
solo en el método del source que devuelve un único objeto.

**Why:** El codebase ya estandariza dos cosas: (a) los DTOs UI son camelCase y el resto
del frontend los consume así; (b) los mappers son funciones nombradas en `http-*-source.ts`
y no `pick`/`omit` dinámicos. El **sobre** del backend es deliberadamente distinto al del
dashboard: `ConversationPageResponse` lleva `items` (no `data`) y devuelve `per_page` /
`page` / `total` sin `total_pages` (`openapi.json:955-985`). Reutilizar el genérico
`PaginatedResponse<T>` del dashboard es **mentira estructural**: habría que cambiar el
nombre del campo (`items` vs `data`) en la frontera, y el mapper se vuelve menos trazable.
Mejor un tipo local `ConversationList` que coincida con la forma del backend. Tres mappers
separados (summary / detail / message) evitan `pick` dinámicos: `ConversationResponse`
tiene 13 campos, `ConversationSummary` tendría 5 (D5) y `MessageResponse` tiene 11 —
forzar un mapper único obligaría a sobre-tipar o a pick por reflection.

**Rejected:**
- *Devolver directamente los tipos `components["schemas"][...]`* — pierde la frontera de
  snake_case→camelCase; los componentes quedarían filtrándose capa a capa hasta los
  componentes de presentación, y un cambio de nombre del backend rompería la UI sin que
  `tsc` se enterara.
- *Un `PaginatedResponse<T>` genérico reutilizado del dashboard* — el sobre es distinto
  (`items` vs `data`, sin `total_pages`); mezclar el genérico es adaptar la fuente al
  consumidor equivocado.
- *Un mapper único para summary / detail / message* — los campos no coinciden; un solo
  mapper obliga a `pick` dinámicos o a sobre-tipar.

### D4 — Filtros v1: `status` (enum tipado), `escalationStatus` (enum tipado), sin `propertyId`; query key con objeto de filtros normalizado

**Chosen:** La query del hook `useConversations` admite en v1
`{ status?: ConversationStatus; escalationStatus?: ConversationEscalationStatus; page?:
number; perPage?: number }` en camelCase UI. **`propertyId` no se expone en v1**:
añadir ese filtro exigiría un selector de propiedad (cuyas propiedades hay que listar
desde `/api/v1/properties`, lo que o vuelve a la entrada `M`/`L` por el selector, o pide
al usuario pegar un UUID a mano, que no es UI). El endpoint del backend sigue aceptando
`property_id` — sólo no se le envía desde esta pantalla —. `ConversationStatus` y
`ConversationEscalationStatus` se mantienen como enums del `openapi.d.ts`, de modo que un
valor no enumerado falle en `tsc` antes de llegar a runtime.

La query key del listado se construye como `conversationsKeys.list(tenantId, filters)`
pasando el **objeto de filtros normalizado directamente** como último segmento
(precedent: `incidentsKeys.list(tenantId, filters)` y `reservationsKeys.list(tenantId,
filters)`). El objeto se construye una sola vez por render con sus claves en un orden
estable, así dos renders con los mismos filtros producen la misma key y TanStack Query no
invalida.

**Why:** La razón para no exponer `property_id` en v1 no es técnica (el endpoint lo
acepta), es de scope: el selector de propiedad abre un combo/async que duplica
`usePropertiesList`, y eso vuelve a entrar en la decisión de «esta entrada es `size: M`».
Cuando llegue el momento, una entrada propia con su design lo añade — el precedent de
`reservations-web` D4 y `incidents-web` D4 dejaron la puerta abierta exactamente para
esto. La query key como objeto directo evita dos trampas: (a) `JSON.stringify` no es
estable frente al orden de claves de un objeto literal TS, así que dos renders con
`filters` equivalentes pero construidos en orden distinto generarían keys distintas y
duplicarían cache; (b) un comparador a mano duplica la lógica de igualdad que TanStack
Query ya hace con `deepEqual` sobre la parte serializada. El `tenantScopedKey` del shell
(`lib/query/query-keys.ts`) ya aísla la cache por tenant, así que el último segmento
puede ser el objeto entero sin riesgo cross-tenant.

**Rejected:**
- *Aceptar `status: string` libre* — pierde el guard de tipos del proposal R2.6 y abre
  la puerta a que un estado renombrado rompa en runtime.
- *Exponer `propertyId` en v1 con un selector* — multiplica la entrada por 2-3: fetch
  de propiedades, estado del selector, deep-linking de la selección. Rompe `size: M`.
- *Pedir al usuario pegar un UUID a mano* — no es UI; es depuración.
- *`JSON.stringify(filters)` para la query key* — `JSON.stringify({a:1,b:2}) !==
  JSON.stringify({b:2,a:1})` en algunas plataformas, y los filters se construyen desde
  varios sitios (URL, estado, defaults) donde el orden de claves puede divergir.

### D5 — Lista: cinco columnas, sin `propertyId`; los `id` como UUID no son información operacional principal

**Chosen:** La tabla de `/conversations` muestra, y solo estas, en este orden: **canal**
(etiqueta localizada con icono de canal), **estado** (etiqueta localizada de
`ConversationStatus`, R5), **escalación** (etiqueta localizada de
`ConversationEscalationStatus` con badge de color cuando es distinto de `NONE`), **último
mensaje** (`lastMessageAt` en formato `YYYY-MM-DD HH:mm` o `—` si es `null`), **creada**
(`createdAt` en formato `YYYY-MM-DD HH:mm`). **No se pinta `propertyId`**, **`guestId`**,
**`reservationId`** ni **`id`** en la lista: el endpoint devuelve estos como UUID y un
UUID pelado no es información operacional principal. Cada fila es un `<Link>` a
`/conversations/[id]` con `title={lastMessageAt}` para hover.

**Why:** El endpoint de lista no devuelve nombres, solo identificadores; un UUID en una
columna «propiedad» no aporta valor operacional al manager (que abre el detalle para ver
el `property_id` si lo necesita, donde sí tiene sentido). Fingir un nombre con un fetch
extra por fila vuelve a la entrada `M` y meter el UUID como dato primario contradice la
regla que prohíbe pintar identificadores internos como información principal — misma
forma que `incidents-web` D5 con `propertyId` en `IncidentSummary`. La densidad de la
tabla es lo que la hace útil en una pantalla de operaciones: si la tabla replica el
detalle deja de ser tabla. El `escalationStatus` es la única heurística de inbox útil
sin un campo explícito de prioridad — un manager mira primero lo escalado a humano — y
un badge de color lo hace visible sin consumir ancho extra.

**Rejected:**
- *Mostrar las 13 columnas de `ConversationResponse`* (`openapi.d.ts:1117-1144`) — la
  lista deja de ser lista, se vuelve un detalle horizontal.
- *Hacer fetch de la propiedad por cada fila para sacar el nombre* — convierte la
  pantalla `size: M` en una que no entra en el change, y mete latencia de N peticiones
  por carga. Es el patrón de `cleaning-manager-view` D3, que en este agregado no
  necesitamos — las conversaciones son más propensas a abrirse que a leerse en tabla.
- *Pintar `propertyId` como columna con tooltip + copiar UUID* — el mismo problema que
  D5 de `assigned_technician_id` en `incidents-web` (proposal R3.6): un UUID pelado no
  es información operacional principal.
- *Expandir la fila al click para mostrar campos extra* — duplica la ruta
  `/conversations/[id]` sin ganar nada que el detalle no dé ya; el comportamiento
  canónico es navegar al detalle, que es deep-linkable.

### D6 — Ruta de detalle sin `href` ni `navigationGroup`, simétrica con `property-detail`, `reservation-detail`, `incident-detail`

**Chosen:** Añadir el descriptor `conversation-detail` en `route-registry.ts` con
`pattern: "/conversations/[id]"`, `match: "exact"`, **sin** `href` y **sin**
`navigationGroup` — replicando `property-detail` (`route-registry.ts:114-122`),
`reservation-detail` (`route-registry.ts:137-145`) e `incident-detail`
(`route-registry.ts:170-177`). Las claves `routes.conversation-detail.{title,description}`
se crean en los dos locales, y la lista `PRD_24_SURFACES` de `route-registry.test.ts` se
**extiende** con `/conversations/[id]`, igual que ya contiene `/properties/[id]`,
`/reservations/[id]` y `/incidents/[id]`: la lista es de **superficies de navegación** con
id, y la asimetría de excluir el hijo parametrizado sería una sorpresa para el siguiente
descriptor detail.

**Why:** Replicar los tres precedents evita tres regresiones a la vez (las suites de
`route-registry`, `route-metadata` y `breadcrumbs` cubren el contrato, y un descriptor
mal formado las pone en rojo). El test "covers exactly the PRD §24 surfaces" compara
`routeRegistry.map(r => r.pattern).sort()` con la lista, así que si el descriptor entra
al registro y la lista no se actualiza, el test falla en rojo por construcción — no hay
forma de saltarse la cobertura. Incluir el id en la lista mantiene la simetría con los
otros tres detail routes, y deja al siguiente detail route con un precedent claro.

**Rejected:**
- *Dejar `PRD_24_SURFACES` sin `/conversations/[id]`* — el test "covers exactly..."
  fallaría en rojo; el precedent de los otros tres detail routes es la postura simétrica.
- *Poner `navigationGroup` y `href` en la ruta de detalle* — la haría aparecer en la
  barra lateral, que no es lo que la spec pide ni lo que los otros tres detail hacen.

### D7 — `content` se renderiza como texto plano, una sola vez, en el bloque del hilo

**Chosen:** El hilo muestra cada `Message.content` como texto plano (`{value}` directo,
sin `dangerouslySetInnerHTML`, sin `react-markdown`, sin `parseHtml`), con
`whitespace-pre-wrap` para respetar saltos de línea del mensaje y `max-w-prose` para
limitar ancho en desktop. El bloque lleva una etiqueta accesible (`aria-label` localizado)
y nunca se pinta dentro de la lista. Cada mensaje va en su propio bloque etiquetado por
`sender_type` (R3.5): etiqueta de rol localizada (Tú / Huésped / IA / Sistema /
Propietario) y, cuando `sender_type = AI`, el `intent` si está presente.

**Why:** `messages.content` está declarado en la regla 11 de `steering/security.md` como
sumidero de texto en claro, con dos formas — prosa de tercero (`sender_type = GUEST`,
`messaging-ai.md` R3) o forma cerrada (`ai_generated = true`) — y la regla 11 lo prohíbe
explícitamente como HTML. El precedent de `incidents-web` D7 lo fija para `description`
de `Incident`: *"el precedent de `reservations-web` R3.3 lo fija para `internal_notes` y
`special_requests`; este change lo aplica al mismo género de columna"*. Renderizarlo en
la lista multiplica la superficie de exposición; renderizarlo en el hilo, en un bloque
etiquetado y con ancho acotado, lo mantiene visible para quien necesita leer la
conversación pero no lo arrastra a la pantalla de operaciones. El escape SHALL ser
responsabilidad del renderizador (React ya escapa por defecto en nodos de texto);
SHALL añadirse un test que renderice un `content` con `<script>alert(1)</script>` y
compruebe que el `<script>` aparece como texto literal y que la alerta no se ejecuta.

**Rejected:**
- *Renderizar con un markdown seguro* — el precedente de `incidents-web` y
  `reservations-web` no lo hace; `messaging-ai.md` R3 ya prohíbe `messages.content`
  como HTML o estructura interpretable, y `messaging-ai.md` R3 segundo párrafo declara
  la forma cerrada cuando `ai_generated = true` precisamente porque no queremos que la
  respuesta automática sea interpretable.
- *Truncar `content` en la tabla* — la lista no muestra `content`; el truncamiento es
  problema del hilo si lo hubiera, y por ahora los mensajes son legibles sin truncar.
- *Pintar `content` como `whitespace-pre-wrap` sin `max-w-prose`* — un mensaje de 4000
  caracteres ocupa toda la pantalla en desktop; el ancho acotado es lo que mantiene
  legible el bloque.

### D8 — `sender_user_id` fuera del bloque principal del mensaje, sin tooltip de copia, con nota localizada

**Chosen:** El `sender_user_id` (UUID) del mensaje se renderiza **fuera** del bloque
principal del mensaje, bajo una sección secundaria etiquetada (`thread.senderUserIdSection`),
**sin** tooltip de copia, **sin** botón «copiar UUID» y **sin** ningún elemento de UI
específico para su valor. El campo va acompañado de una **nota localizada única** en
`thread.senderUserIdNote` que documenta la limitación: el id no puede resolverse a nombre
dentro de `size: M` porque no hay `GET /api/v1/users` en el contrato con permiso suficiente
para listar otros usuarios y abrir uno sale de esta entrada. La nota aparece **una sola
vez**, en la sección secundaria donde vive el campo; no se duplica en otros sitios. Si
`sender_user_id` es `null` (mensaje de `SYSTEM` o `AI` sin `sender_user_id`), la sección
se oculta.

**Why:** Misma forma de tratarlo que `incidents-web` R3.8 con `assigned_technician_id`:
un UUID pelado no es información operacional principal, y `tech-app` (que vive en otra
rama del roadmap y depende de tres entradas `[BE]` previas) es donde se resolverá
nombre↔id para los técnicos. Aquí el `sender_user_id` lo producen los roles `OWNER` /
`MANAGER`, así que la resolución vive cuando se introduzca `users` en el contrato — no en
este change. La nota única evita cinco copies del mismo disclaimer y deja la superficie
de UI consistente con el resto del workspace.

**Rejected:**
- *Mostrar el UUID en el bloque principal del mensaje* — contradice el precedent de
  `incidents-web` D5 y mete identificador interno como dato primario.
- *Tooltip de copia + botón «copiar UUID»* — mismo problema que `incidents-web` R3.8:
  exponer un UUID pelado invitando a copiarlo es depuración, no UI.
- *Resolver el nombre en el cliente con un fetch extra por mensaje* — N+1 por mensaje
  no escala, y no hay `GET /api/v1/users` en el contrato.
- *No mostrar `sender_user_id` en absoluto* — perdería la pista de auditoría visual
  («¿quién me respondió?»), que es lo único que el campo da en este change.

### D9 — Respuesta humana con `useReplyToConversation`: invalidación cruzada, sin patch optimista, `sender_type` nunca se envía

**Chosen:** `frontend/features/conversations/hooks/use-reply-to-conversation.ts` exporta
`useReplyToConversation(conversationId)` que usa `useMutation` con:

- `mutationFn` que llama `getConversationsDataSource().replyToConversation(tenantId,
  conversationId, { content })` — el body **no** incluye `sender_type`, porque el
  esquema `CreateMessageRequest` lo declara `Literal["GUEST"] | null`
  (`openapi.d.ts:1258-1268`, `openapi.json:1258-1268`); la UI **nunca** envía
  `sender_type` en esta ruta.
- `retry: false` — una escritura rechazada no se reintenta, precedent:
  `features/cleaning/hooks/use-assign-cleaning-task.ts:49`,
  `features/guest-portal/hooks/use-checkin.ts:7`.
- `onSettled` invalida los tres keys del recurso conversaciones del tenant:
  `conversationsKeys.listPrefix(tenantId)` (todas las páginas y filtros),
  `conversationsKeys.detail(tenantId, conversationId)` (la conversación para refrescar
  `status` / `escalationStatus` / `lastMessageAt` / `updatedAt`),
  `conversationsKeys.messagesPrefix(tenantId, conversationId)` (el hilo para incluir el
  nuevo mensaje). **No patch optimista**: igual que `useAssignCleaningTask`, una fila
  con un mensaje que el backend no confirmó es peor que un refetch.

El hook **no** almacena ni devuelve copia del draft: el contenido que el operador está
escribiendo pertenece exclusivamente al estado local de `ConversationReplyForm`. En
éxito el formulario limpia el campo por su cuenta; en error el formulario simplemente no
lo modifica. Responsabilidades del hook: la mutación, `retry: false` y la invalidación de
los tres keys. Una sola fuente de verdad para el draft (el `useState` del formulario).

**Why:** `invalidateQueries` con `queryKey: conversationsKeys.listPrefix(tenantId)`
alcanza cada combinación de filtros y página sin enumerarlas — precedent:
`useAssignCleaningTask` invalida `cleaningKeys.tasksPrefix(tenantId)` en
`onSettled` para que R4.5 quede libre. Patch optimista es tentador para una mutación
«rápida» como enviar un mensaje, pero introduce un instante en el que la fila muestra
un mensaje que el backend no confirmó, y en mensajería eso es **mentira operacional**:
el huésped podría ver (en su canal, fuera del UI) un mensaje que el panel dice
«enviado» pero el backend rechazó. `sender_type` se omite por construcción: el backend
deriva el rol del caller (`messaging-ai.md` R7: «omitido, el llamante contesta él
mismo y el `sender_type` se deriva de su rol»), y enviar cualquier valor no nulo
responde `422`. La responsabilidad sobre el draft queda en el formulario: el hook no
conoce el contenido que está escribiendo el operador, y el formulario decide limpiarlo
en éxito o preservarlo en error — evitar dos fuentes de verdad (hook + componente) es
lo que mantiene el formulario trivial de leer y razonar.

**Rejected:**
- *Patch optimista + rollback en `onError`* — introduce el instante de mentira
  operacional descrito arriba; el precedent de `useAssignCleaningTask` lo desaconseja
  explícitamente.
- *Invalidar solo `conversationsKeys.messages(...)` y dejar la lista desactualizada* —
  el `lastMessageAt`, `status` y `escalationStatus` de la fila de la bandeja
  quedarían stale hasta el siguiente refetch; un manager que mire la bandeja justo
  después de responder vería un orden incorrecto.
- *Enviar `sender_type` desde la UI* — el esquema lo rechaza con `422`; no hacerlo es
  literalmente el contrato.
- *`retry: true` con backoff* — `useAssignCleaningTask` ya discutió esto: una escritura
  rechazada no se reintenta, y un mensaje rechazado debe ver el error inmediatamente.
- *El hook almacena o devuelve una copia del draft* — son dos fuentes de verdad
  (hook + formulario) y propaga estado que pertenece al componente. El draft vive
  exclusivamente en el `useState` del formulario; el hook solo dispara la mutación y
  invalida cache.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Shell | `frontend/features/shell/navigation/route-registry.ts` | Add `conversation-detail` descriptor (D6). |
| Locales (nav) | `frontend/locales/{es,en}/navigation.json` | Add `routes.conversation-detail.{title,description}` (D6). |
| Locales (feature) | `frontend/locales/{es,en}/conversations.json` | New file: `status` (4) + `escalationStatus` (4) + `channel` (6) + `senderType` (5) + `fields` + `thread` (D2). |
| Locales (registry) | `frontend/lib/i18n/resources.ts` | Register `esConversations` / `enConversations` namespaces (D2). |
| Data | `frontend/features/conversations/data/index.ts` | New: composition point exporting `getConversationsDataSource()` (D1). |
| Data | `frontend/features/conversations/data/dto.ts` | New: `ConversationSummaryDto`, `ConversationDetailDto`, `MessageDto`, `ConversationList`, `MessageList`, `MessagePageResponse` (camelCase); re-exports de enums; `ConversationFilters` (D3). |
| Data | `frontend/features/conversations/data/http/http-conversations-source.ts` | New: `HttpConversationsSource` with `listConversations`, `getConversation`, `listMessages`, `replyToConversation`, plus `mapConversationSummary`, `mapConversationDetail`, `mapMessage` (D3, D9). |
| Data | `frontend/features/conversations/data/http/http-conversations-source.test.ts` | New: unit tests for the four methods (mappers + paths + query params + body del `POST` sin `sender_type`). |
| Lib | `frontend/features/conversations/lib/error-mapping.ts` | New: `mapConversationsError<TData>` (discriminated union: `loading` / `forbidden` / `not-found` / `validation` / `error` / `ok`), precedent: `features/incidents/lib/error-mapping.ts`. |
| Hooks | `frontend/features/conversations/hooks/query-keys.ts` | New: `conversationsKeys` (list, detail, messages, listPrefix, messagesPrefix) usando `tenantScopedKey` (D4, D9). |
| Hooks | `frontend/features/conversations/hooks/use-conversations.ts` | New: `useConversations(filters)`, `useConversation(id)`, `useConversationMessages(id, page)` con `retry: retryPolicy` (D4). |
| Hooks | `frontend/features/conversations/hooks/use-conversations.test.tsx` | New: hook tests contra un `HttpConversationsSource` mockeado (D1). |
| Hooks | `frontend/features/conversations/hooks/use-reply-to-conversation.ts` | New: `useReplyToConversation(id)` con `useMutation` + invalidación cruzada de los 3 keys (D9). |
| Hooks | `frontend/features/conversations/hooks/use-reply-to-conversation.test.tsx` | New: test del `onSettled` invalidando los 3 keys y verificando que `sender_type` no se envía (D9). |
| Components | `frontend/features/conversations/components/list/conversations-view.tsx` | New: client view que consume `useConversations`, renderiza tabla con paginación y estado vacío/error (D5). |
| Components | `frontend/features/conversations/components/list/conversations-view.test.tsx` | New: render tests (loading / loaded / empty / error / `<script>` no en lista — no aplica, contenido nunca va a la lista, D7). |
| Components | `frontend/features/conversations/components/list/conversations-filters.tsx` | New: filtros (`status`, `escalationStatus`) con control tipado. Sin `propertyId` en v1 (D4). |
| Components | `frontend/features/conversations/components/list/conversations-filters.test.tsx` | New: tests del comportamiento del filtro (reset a página 1). |
| Components | `frontend/features/conversations/components/thread/conversation-thread-view.tsx` | New: client view que consume `useConversation(id)` y `useConversationMessages(id, page)` (D7). |
| Components | `frontend/features/conversations/components/thread/conversation-thread-view.test.tsx` | New: tests (loading / loaded / not-found / error / `<script>` como texto plano, D7). |
| Components | `frontend/features/conversations/components/thread/conversation-thread-messages.tsx` | New: bloque presentacional de mensajes con etiqueta de rol (D7, D8). |
| Components | `frontend/features/conversations/components/thread/conversation-thread-messages.test.tsx` | New: tests de cada `sender_type` + `intent` cuando AI + `sender_user_id` nota localizada (D7, D8). |
| Components | `frontend/features/conversations/components/thread/conversation-reply-form.tsx` | New: formulario con contador `4000`, estado de envío, error localizado, draft en estado local propio (D9). |
| Components | `frontend/features/conversations/components/thread/conversation-reply-form.test.tsx` | New: tests de contador, deshabilitación mientras vuela, draft preservado en error, draft limpiado en éxito, envío exitoso. |
| Components | `frontend/features/conversations/index.ts` | New: barrel export. |
| Pages | `frontend/app/(workspace)/conversations/page.tsx` | Replace placeholder with `<ConversationsInboxView />`. |
| Pages | `frontend/app/(workspace)/conversations/[id]/page.tsx` | New: detail page que llama `routeMetadata('conversation-detail')` y renderiza `<ConversationThreadView conversationId={id} />`. |
| Tests | `frontend/features/shell/navigation/route-registry.test.ts` | Extend `PRD_24_SURFACES` con `/conversations/[id]` (D6). |

## Data & interfaces

**Sin cambios de schema, sin migraciones, sin variables de entorno.** Todo el contrato ya
existe en `backend/openapi.json` y está tipado en
`frontend/lib/api/generated/openapi.d.ts:1091-1155` (enums) y `:220-263` (paths). El
regenerado del contrato NO se hace en este change — la regeneración corresponde al change
de backend que modifique un endpoint, según `sdd/specs/frontend-api-contract-consumer.md`.

**API consumida (1 mutación in-scope + 3 lecturas, ya tipadas):**
- `GET /api/v1/conversations?page&per_page&status&escalation_status&property_id` →
  `ConversationPageResponse` (sobre `{items, total, page, per_page}`,
  `ConversationResponse[]` dentro).
- `GET /api/v1/conversations/{id}` → `ConversationResponse`.
- `GET /api/v1/conversations/{id}/messages?page&per_page` → `MessagePageResponse`
  (misma forma `{items, total, page, per_page}`, `MessageResponse[]` dentro).
- `POST /api/v1/conversations/{id}/messages` con `{content}` y **sin** `sender_type`
  → `MessageResponse` (única mutación in-scope, R4).

**Enums que el FE localiza (de `openapi.d.ts:1091-1155, 1929`):**
- `ConversationStatus` (4): `OPEN`, `RESOLVED`, `ESCALATED`, `CLOSED`.
- `ConversationEscalationStatus` (4): `NONE`, `PENDING_HUMAN`, `HUMAN_HANDLING`, `RESOLVED`.
- `ConversationChannel` (6): `WHATSAPP`, `AIRBNB_MSG`, `BOOKING_MSG`, `EMAIL`,
  `PHONE_TRANSCRIPT`, `MANUAL`.
- `MessageSenderType` (5): `GUEST`, `OWNER`, `MANAGER`, `AI`, `SYSTEM`.

**DTOs UI (camelCase, exportados desde `features/conversations/data/dto.ts`):**
- `ConversationStatus` / `ConversationEscalationStatus` / `ConversationChannel` /
  `MessageSenderType` — re-exports de `openapi.d.ts`.
- `ConversationSummaryDto` — `{ id, channel, status, escalationStatus, lastMessageAt,
  createdAt }` (subset del detalle para la tabla; **no incluye `propertyId`,
  `guestId`, `reservationId`** — la lista v1 no pinta esas columnas, ver D5).
- `ConversationDetailDto` — los 13 campos de `ConversationResponse` en camelCase:
  `{ id, propertyId, reservationId, guestId, channel, status, escalationStatus,
  language, aiEnabled, lastMessageAt, createdAt, updatedAt }`.
- `MessageDto` — los 11 campos de `MessageResponse` en camelCase: `{ id,
  conversationId, senderType, senderUserId, content, language, aiGenerated,
  confidenceScore, intent, createdAt }`. **`metadata` se descarta en el mapper**: es
  un objeto cerrado con claves de auditoría (`escalation_reason`, `template_key`,
  `template_version`, `delivery_status`, `delivery_error_code`,
  `source_message_id` — `messaging-ai.md` R3) que el FE no muestra en este change; si
  llegara a hacer falta, una entrada posterior lo añade. Mantenerlo fuera del DTO
  protege la regla 11 — `metadata` es también sumidero de texto en claro en su
  semántica interna (códigos, no prosa), pero exponerlo en UI sin motivo abre preguntas
  que no necesitamos responder.
- `ConversationList` — `{ items: ConversationSummaryDto[]; total: number; page:
  number; perPage: number }` (sobre del backend, renombrado a camelCase en la
  frontera).
- `MessageList` — `{ items: MessageDto[]; total: number; page: number; perPage: number }`
  (misma forma que `ConversationList`).
- `ConversationFilters` — `{ status?: ConversationStatus; escalationStatus?:
  ConversationEscalationStatus; page?: number; perPage?: number }` (v1, sin
  `propertyId` por D4).
- `ConversationPagination` — tipo derivado en el cliente, NO viene del backend:
  `{ page: number; perPage: number; total: number; lastPage: number }` donde
  `lastPage = max(1, ceil(total / perPage))` (`total = 0 → lastPage = 1`). El backend
  no expone `total_pages` en `ConversationPageResponse` (`openapi.json:955-985`), así
  que el cliente lo calcula; el `disabled` del botón «siguiente» usa `page >= lastPage`
  (R2.5).

**Errores relevantes** (de `lib/api/errors.ts`): `ApiError` con `status` 401, 403, 404,
422, 5xx. Mapeo a UI ya está en R3.7 y R5.4 (discriminated union vía
`mapConversationsError`).

## Risks & mitigations

- **Riesgo: la PII del huésped en `messages.content` se renderiza como HTML por
  accidente.** Mitigación: el componente `ConversationThreadMessages` lo pinta con
  `{value}` directo y `whitespace-pre-wrap`, nunca `dangerouslySetInnerHTML`. El test
  del componente verifica que un `content` con `<script>alert(1)</script>`, `\n` y PII
  se renderiza como texto literal (D7). El precedent de `incidents-web` R7.6 y D7 lo
  fija.
- **Riesgo: el operador envía `sender_type` por error y el backend responde `422`.**
  Mitigación: el `HttpConversationsSource.replyToConversation` solo acepta `{ content }`
  como input y serializa el body sin `sender_type` (D9); un test del source verifica
  que el body serializado es exactamente `{content: "..."}` y nunca lleva la clave.
- **Riesgo: el patch optimista del nuevo mensaje muestra un mensaje que el backend no
  confirmó.** Mitigación: `useReplyToConversation` no hace patch optimista; invalida los
  tres keys en `onSettled` (D9; precedent: `useAssignCleaningTask`). El estado del UI
  siempre refleja el resultado de la mutación.
- **Riesgo: la query key del listado no incluye los filtros, así que cambiar de página
  en la misma vista reusa la respuesta cacheada de otra página.** Mitigación:
  `conversationsKeys.list(tenantId, filters)` recibe el **objeto de filtros
  normalizado** directamente como parte de la key (D4; precedent:
  `incidentsKeys.list(tenantId, filters)` en `query-keys.ts:18-19`). El objeto se
  construye con sus claves en orden estable, no se serializa con `JSON.stringify`.
- **Riesgo: `status` o `escalationStatus` enviados como string libre pasan el typecheck
  pero la API devuelve 422.** Mitigación parcial por R2.6 (tipo
  `ConversationStatus`/`ConversationEscalationStatus`); el resto se cubre con el test de
  mapper, que verifica que un valor enumerado se serializa al nombre exacto del enum
  del backend (precedent: `incidents-web` R7.6).
- **Riesgo: el `ApiError 404` del detalle entra por la rama genérica de error y oculta
  la distinción que pide R3.7.** Mitigación: `mapConversationsError` distingue `404`
  por `instanceof ApiError && status === 404`; un test cubre el caso. La pantalla de
  detalle muestra «Conversación no encontrada» localizado, distinto del error genérico.
  Un manager de otro tenant recibe el mismo `404` por R1 de `messaging-ai.md` — la UI
  no filtra existencia.
- **Riesgo: la cache de TanStack Query cruza tenants.** Mitigación: `tenantScopedKey`
  del shell (`lib/query/query-keys.ts:13-25`) hace que cada key empiece con
  `['tenant', tenantId, ...]`; un cross-tenant key no se puede producir por accidente.
  Cobertura: tests de `query-keys.test.ts`.
- **Riesgo: la bandeja muestra `sender_user_id` como un UUID pelado, que no identifica
  al remitente.** Mitigación: el hilo muestra el campo bajo una sección secundaria
  etiquetada, **sin** tooltip de copia, **sin** botón «Copiar UUID», **sin** elemento de
  UI específico para su valor, y **con** una nota localizada única que documenta la
  limitación: el id no puede resolverse a nombre dentro de `size: M` (no hay
  `GET /api/v1/users` con permiso suficiente en el contrato y abrir uno sale de esta
  entrada). Misma forma de tratarlo que `incidents-web` R3.8 con
  `assigned_technician_id`.
- **Riesgo: la bandeja lista sin conversaciones y el revisor lo cuenta como fallo.**
  Mitigación: la limitación de demo está declarada en el `Why` de la proposal; el R2.4
  muestra el estado vacío localizado; `make seed-demo` deja legítimamente la bandeja
  vacía y esto es el comportamiento esperado, no un defecto. El test del componente
  cubre el caso `items = []`.
- **Riesgo: el dev stack del worktree choca con el del principal.** Mitigación: este
  change no toca infra; el shell `make up` ya levanta la suite del FE vía `npm test`
  con Vitest en el propio contenedor, sin necesidad de API real (precedent:
  `incidents-web` R5.7, `frontend-foundation.md` §Testing). Si el revisor necesita el
  navegador, `make up PORT_OFFSET=<n>` está disponible (worktree-port-offset).
- **Riesgo: regenerar `openapi.d.ts` en otro change futuro introduce un campo nuevo en
  `ConversationResponse` o `MessageResponse` que no aparece en el mapper.** Mitigación:
  el mapper enumera campos explícitamente (D3), así que un campo nuevo es invisible al
  UI hasta que se mapee — exactamente el comportamiento que el precedent de
  `incidents-web` D3 y `properties-crud` demostró necesario. `metadata` se descarta
  deliberadamente (ver DTOs UI): su adición futura exige decisión de UI.

## Open questions

*(Resueltas durante el gate de design, **2026-08-22**:*

- *Sobre del backend `ConversationPageResponse` vs `PaginatedResponse<T>` del dashboard
  → sobre local `ConversationList` con DTOs propios, D3. Sin genérico reutilizado.*
- *Enumeraciones a localizar → las 4 de `ConversationStatus`, las 4 de
  `ConversationEscalationStatus`, las 6 de `ConversationChannel` y las 5 de
  `MessageSenderType`: la lista la fija `openapi.d.ts`, no la spec de `messaging-ai.md`.
  D2 y el listado en §Data & interfaces.*
- *Exposición de `property_id` en v1 → no se expone, queda para una entrada propia con su
  design, D4. Misma forma que `reservations-web` D4 y `incidents-web` D4.*
- *Renderizado de `content` → un único bloque en el hilo, texto plano, D7. Nunca en la
  lista.*
- *Acciones del manager (escalar, resolver, crear) → fuera de scope y fuera de la
  pantalla, R5 del proposal y out-of-scope. La UI solo expone responder.*
- *`metadata` en `MessageResponse` → descartado del DTO, sin render en este change, ver
  §Data & interfaces. Futura entrada con decisión de UI lo añade si llega a hacer
  falta.*
- *Invalidación tras `POST /messages` → tres keys (lista, detalle, mensajes), D9. Sin
  patch optimista. El draft pertenece al formulario; el hook solo dispara y invalida.*

*No queda ninguna abierta para `tasks.md`: la entrada puede pasar a tareas sin más
gates.)*