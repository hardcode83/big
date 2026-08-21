# Design: conversations-inbox

## Context

El backend está entero y publicado: `backend/app/messaging/api/router.py` expone las siete rutas
de PRD §16 con `READ_CONVERSATIONS` para las tres de lectura y `MANAGE_CONVERSATIONS` para las
cuatro de escritura, y `backend/app/auth/domain/policy.py` da la primera a `TENANT_OWNER` y
`PROPERTY_MANAGER` y la segunda **solo** a `PROPERTY_MANAGER`. En el frontend,
`frontend/app/(workspace)/conversations/page.tsx` es todavía un `RoutePlaceholder`, y el patrón a
seguir ya existe dos veces: `frontend/features/dashboard/` (frontera `DashboardDataSource` +
`HttpDashboardSource` + punto de composición en `data/index.ts` + claves con `tenantScopedKey`) y
`frontend/features/guest-portal/`, que es el mismo patrón sin `data/mock/`. Lo compartido está en
`frontend/lib/api/` (`ApiClient` tipado sobre `lib/api/generated/openapi.d.ts`, `ApiError`,
`retryPolicy`), `frontend/components/states/` (loading / error / empty) y
`frontend/lib/i18n/resources.ts`.

La investigación del código encontró **tres divergencias con lo que el proposal daba por cierto**, y
las tres cambian el diseño: dos estados que declaraba inalcanzables sí lo son (OQ1, ya enmendado), la
semántica real de los canales mudos es distinta de la que R3.7 describe (D13), y el sobre de
paginación de mensajería no es el de PRD §23 que usa el dashboard (D3).

## Decisions

### D1 — Feature nueva `features/conversations/`, con la misma forma de cuatro capas que el dashboard

**Chosen:** un módulo propio en `frontend/features/conversations/` con `data/`, `hooks/`,
`components/`, `state/` y `lib/`, y un único `index.ts` público que exporta `ConversationsView`.
Es la tercera aplicación del patrón, no una variante: `steering/frontend.md` y
`specs/frontend-api-contract-consumer.md` lo fijan, y `eslint.config.mjs` ya impide que otra
feature entre en sus internos.

Rejected: ampliar `features/dashboard` — son capacidades distintas con endpoints distintos, y
acoplarlas obligaría a que un cambio de bandeja recompile el panel.
Rejected: poner el acceso a datos en `lib/` — la frontera es **por feature** por contrato.

### D2 — `ConversationsDataSource` con siete métodos, incluido el de etiquetas de propiedad

**Chosen:** una interfaz con `listConversations`, `getConversation`, `listMessages`,
`createMessage`, `escalate`, `resolve` y `listPropertyLabels`, todos con `tenantId` explícito en la
firma como en `DashboardDataSource`, y una sola implementación `HttpConversationsSource` sobre el
`ApiClient` compartido, resuelta en `data/index.ts` (R7.1). `listPropertyLabels` vive **aquí** y no
en una feature de propiedades: devuelve un DTO de tres campos (`id`, `internalCode`, `name`), y eso
es lo que mantiene `access_notes`, `emergency_notes` y `wifi_name` —que `PropertyResponse` sí
trae— **fuera de la caché de TanStack Query**, porque el mapeo ocurre en el data source y la caché
guarda el DTO, no la respuesta.

Rejected: crear `features/properties/data/` para compartirlo — `properties-crud` es su dueño
natural y todavía no tiene superficie; adelantarla aquí es alcance que nadie pidió.
Rejected: reutilizar `DashboardDataSource` — cruzaría dos fronteras de feature por un `internal_code`.

### D3 — Sobre de página propio (`ConversationPage<T>`), porque el de mensajería no es el de §23

**Chosen:** un tipo de feature `ConversationPage<T> = { items: T[]; page: number; perPage: number;
total: number; totalPages: number }`, donde `totalPages` se **deriva** como
`Math.max(1, Math.ceil(total / perPage))` en el mapper. Motivo objetivo: en el contrato generado
`ConversationPageResponse` y `MessagePageResponse` traen `items` y **no traen `total_pages`**,
mientras que `PropertyPageResponse` trae `data` y `total_pages`. Son dos sobres distintos en el
mismo contrato, y el `PaginatedResponse` de `features/dashboard/data/dto.ts` modela el segundo.

Rejected: reutilizar `PaginatedResponse` del dashboard — habría que sintetizar `data` y
`total_pages` y el DTO mentiría sobre lo que el endpoint devuelve.
Rejected: derivar las páginas en el componente — cada consumidor repetiría el `ceil`.
Nota: `listPropertyLabels` lee `data`/`total_pages` porque su endpoint sí los tiene; el mapper lo
declara por separado en lugar de fingir un sobre único.

### D4 — Sin `data/mock/`: solo HTTP, y los dobles de test viven en los tests

**Chosen:** una sola implementación (HTTP), como en `features/guest-portal`. Los tests construyen
un objeto que satisface `ConversationsDataSource` y las fixtures viven junto al test que las usa,
nunca en un módulo importable desde runtime (R7.3).

Rejected: replicar `features/dashboard/data/mock/` — allí existe porque el dashboard se construyó
antes de que su API existiera; aquí los siete endpoints ya están publicados, y un mock de negocio
sería una segunda fuente de verdad que envejece sola.

### D5 — Maestro-detalle en una ruta, con la selección en el query string y `Suspense`

**Chosen:** `/conversations` renderiza `ConversationsView`, un Client Component que lee la
conversación seleccionada de `?conversation=<uuid>` con `useSearchParams()` y la escribe con
`router.replace(...,{scroll:false})`. La página (Server Component) envuelve la vista en
`<Suspense>` con el `LoadingState` compartido como fallback: `useSearchParams()` hace que Next
abandone el prerender, y la frontera es lo que mantiene ese abandono **acotado al subárbol** en vez
de a la ruta entera.

**Corregido en `/sdd:review` (2026-08-21).** Esta decisión afirmaba que sin la frontera «rompe
`next build`», y **es falso en este árbol**: cada página espera `getServerT()`, que lee `cookies()`,
así que las 24 rutas ya son dinámicas y no queda camino estático que el build pueda rechazar.
Comprobado empíricamente quitando la frontera: el build compila igual. La frontera sigue siendo
obligatoria —por el acotado, y por que la ruta siga siendo correcta el día que la i18n de servidor
deje de ser dependencia por petición— pero **`next build` no es el mecanismo que detecta su
retirada**: lo es `app/error-architecture.test.ts`, cuyas aserciones se reforzaron en la misma
revisión para comprobar que la frontera envuelve de verdad al consumidor y que ese consumidor sigue
llamando a `useSearchParams()`.

Rejected: guardar la selección en Zustand — R3.1 pide que el hilo sea enlazable y recargable.
Rejected: una ruta anidada `/conversations/[id]` — R3.1 dice explícitamente «la misma ruta», y
partirla duplicaría el chrome de la shell en móvil.

### D6 — Filtros y página en Zustand; la selección, no

**Chosen:** `useInboxFiltersStore` (Zustand) guarda `{ status, escalationStatus, propertyId, page }`
y nada más — jamás conversaciones ni mensajes (R2.5) —, y poner un filtro **resetea `page` a 1**,
porque la página 3 de un filtro no existe en el siguiente. Los cuatro valores entran en la clave de
query (R2.4).

Rejected: llevar también los filtros al query string — R2.5 los manda a Zustand, y dos fuentes de
verdad para el estado de la lista es peor que la limitación que esto acepta.
Limitación asumida y declarada: un enlace comparte el **hilo**, no el filtro ni la página.

### D7 — Etiquetas de enum por mapa exhaustivo `Record<Literal, key>`, no por `t(\`...${valor}\`)`

**Chosen:** un módulo `lib/labels.ts` con un `Record` por enum (`ConversationStatus`,
`ConversationEscalationStatus`, `ConversationChannel`, `MessageSenderType`), tipado contra el
literal del contrato generado. Un valor nuevo en el backend deja de compilar en vez de perderse en
silencio (R2.2, R3.3), y el test de paridad de catálogos cubre las claves porque están escritas.

Rejected: interpolar la clave (`t(\`status.${status}\`)`) como hace
`property-timeline.tsx` con `eventType` — allí es correcto porque `TimelineEventType` es abierto a
propósito; aquí los cuatro enums son cerrados y la exhaustividad es un requisito.

### D8 — `confidenceScore` viaja como cadena decimal y solo se formatea al pintar

**Chosen:** el DTO declara `confidenceScore: string | null` y el mapper lo copia tal cual. El
formateo a porcentaje ocurre en el componente, sobre `Number(value)`, con
`Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 })`; si es `null`, no se
pinta cifra alguna (R3.4). Es lo contrario de `decimalToNumber` en
`http-dashboard-source.ts`, y a propósito: ahí convertir en la frontera es inocuo, aquí R3.4
prohíbe redondear **antes** de formatear.

Rejected: `Number()` en el mapper — pierde precisión en la frontera, que es justo lo que R3.4 cierra.

### D9 — Antigüedad con `Intl.RelativeTimeFormat`, y nunca como único dato

**Chosen:** `lib/format.ts` de la feature con `formatAge(iso, locale)` sobre
`Intl.RelativeTimeFormat` eligiendo la unidad más gruesa que aplique, y `formatDateTime` como en
el dashboard. Se pinta en un `<time dateTime={iso}>` cuyo `title` es la fecha absoluta, para que
«hace 3 días» no sea la única información disponible. `last_message_at === null` → texto
localizado de «sin mensajes» (R1.3).

Rejected: añadir `date-fns`/`dayjs` — `Intl` está en el runtime y este change no añade dependencias.
Consecuencia para tests: la salida depende del reloj, así que las suites que la comprueban fijan
la hora (`vi.setSystemTime`).

### D10 — Puertas de acción derivadas de las **dos** tablas de transición, no de una

**Chosen:** un módulo puro `lib/transitions.ts` que responde qué se ofrece, leído de
`backend/app/messaging/domain/entities.py`:

| Acción | Habilitada cuando | Origen |
|---|---|---|
| Escalar | `escalationStatus === "NONE"` **y** `status === "OPEN"` | `escalate` comprueba **los dos ejes** antes de escribir |
| Resolver | `status ∈ {OPEN, ESCALATED}` (+ confirmación, R5.4) | `_STATUS_TRANSITIONS["resolve"]` |
| Responder / transcribir | `status !== "CLOSED"` | `ConversationClosedError` → 409 |

R5.2 solo nombraba el eje de escalación; el eje de estado también restringe, así que una
conversación `RESOLVED` con `escalation_status = NONE` **no** se puede escalar y ofrecerlo sería
prometer un 409.

Rejected: preguntar al backend antes de habilitar — no hay endpoint de transiciones válidas y
duplicaría un viaje por cada fila.

### D11 — Las acciones inválidas se renderizan deshabilitadas con motivo localizado

**Chosen:** el botón existe siempre que el rol pueda operar (D12) y se deshabilita
(`disabled` + `aria-describedby` con el motivo) cuando D10 dice que la transición no cabe. «Ofrecer
solo cuando la transición es válida» (R5.2) se cumple en el sentido de *accionable*: un botón que
desaparece no enseña por qué. Resuelto en el gate del 2026-08-19 (OQ3).

Rejected: ocultarlo — el manager no distingue «no puedo» de «no existe».

### D12 — Permiso derivado del rol, en un módulo de la feature, exhaustivo sobre `UserRole`

**Chosen:** `lib/permissions.ts` con `canManageConversations(role: UserRole): boolean` escrito como
`Record<UserRole, boolean>` sobre el literal generado, `true` solo en `PROPERTY_MANAGER`. El rol
sale de `useAuth().user.role`, que es lo único que `CurrentUserResponse` expone —no hay lista de
permisos en `/auth/me`—. Es **UX y no autorización** (R6.2): el backend sigue decidiendo, y el 403
se maneja igual que si el botón no se hubiera ocultado.

Rejected: un mapa general de permisos en `lib/auth/` — hoy no hay segundo consumidor, y el reparto
por rol de cada capacidad vive en `policy.py`; replicarlo entero en el cliente es superficie de
divergencia sin beneficio.
Rejected: inferirlo de un 403 observado — dejaría la UI ofreciendo lo que no se puede hasta el
primer fallo.

### D13 — Canales mudos: la advertencia se corrige contra el código, y son dos avisos distintos

**Chosen:** el hilo lleva un aviso permanente cuando `channel ∈ {AIRBNB_MSG, BOOKING_MSG}` y el
diálogo de transcripción, uno propio. No dicen lo mismo, porque el backend no se comporta igual en
las dos vías (`use_cases.py`, `messaging-ai` R6.3):

- **Responder** en un canal mudo **funciona**: `RecordHumanReplyUseCase` no toca ningún
  `OutboundMessagePort`, así que el mensaje se persiste con 201 y **nunca se entrega**. Ningún
  error avisa. Este es el caso que R3.7 quería cubrir, y la advertencia debe decir «se guarda, no
  se envía», no «fallará».
- **Transcribir** en un canal mudo puede **perderse entero**: si la política de escalación no salta,
  el pipeline llega a `_reply`, no encuentra adapter y lanza `PMSChannelUnavailableError` → **422**,
  y como todo va en una transacción única, el mensaje del huésped tampoco se guarda. Si la política
  sí salta, no hay envío y la transcripción se guarda sin problema. El estado de error de la
  transcripción tiene que decir que **no se ha guardado nada**.
- `PHONE_TRANSCRIPT` sí tiene adapter (`InboundOnlyAdapter`) y nunca entrega: la respuesta de la IA
  se guarda con `delivery_status = FAILED` y la conversación se escala con `DELIVERY_FAILED`.

Rejected: un único aviso genérico de «canal mudo» — describiría mal una de las dos vías, y la que
describiría mal es la que pierde datos.

### D14 — Marca de entrega en los mensajes de la IA, leída de `metadata`

**Chosen:** el mapper extrae de `MessageResponse.metadata` **solo** `delivery_status` y
`escalation_reason` (dos campos nombrados, no el diccionario entero), y un mensaje con
`delivery_status = FAILED` se pinta con una marca localizada de «no entregado». Sin esto la bandeja
enseña como enviada una respuesta que el huésped no recibió — sistemático en `PHONE_TRANSCRIPT`.
Resuelto en el gate del 2026-08-19 (OQ2): entra en alcance.

Rejected: pasar `metadata` completo al DTO — es un `JSONB` cuyo contrato cerrado vive en el backend
(`MessageMetadata`); copiarlo entero al cliente invita a leer claves que nadie declaró aquí.

### D15 — El contenido del mensaje se pinta como texto y nada más

**Chosen:** `content` se renderiza dentro de un `<p className="whitespace-pre-wrap">` con el
escapado por defecto de React. Sin `dangerouslySetInnerHTML`, sin markdown, sin autolinkado y sin
recortes ni resúmenes. Es la aplicación directa de la excepción 4 de la regla 11 de
`steering/security.md`: lo que hay ahí es prosa verbatim de un huésped, que puede contener su
número de documento, y esta es la primera superficie que se lo enseña a un operador. La misma
regla aplica a `intent` y al idioma, que se pintan como dato.

Rejected: enriquecer el texto (enlaces, saltos a WhatsApp) — convierte contenido no confiable en
superficie activa por una comodidad que nadie pidió.

### D16 — Claves de query e invalidación explícita tras cada mutación

**Chosen:** `hooks/query-keys.ts` sobre `tenantScopedKey` (R2.4):
`list(tenantId, filters, page)` → `['tenant',id,'conversations-list',filters,page]`;
`detail(tenantId, id)`; `messages(tenantId, id, page)`; `propertyLabels(tenantId)`. Tras
`createMessage`, `escalate` o `resolve` se invalidan por prefijo la lista y los mensajes de ese
hilo, y la clave exacta del detalle (R4.4, R5.3). Las lecturas usan `retryPolicy` compartido, que
no reintenta 4xx (R3.6); las mutaciones van con `retry: false`, como en `guest-portal`.

Rejected: `queryClient.clear()` — tira la caché de otras features.
Rejected: actualización optimista del hilo — la respuesta de la IA y los dos ejes de estado los
calcula el servidor dentro de la misma petición; pintar antes sería inventar el resultado.

### D17 — Un 403 en la lectura es un estado propio, no un error reintentable

**Chosen:** si `GET /api/v1/conversations` responde 403 —alcanzable: `/conversations` es una ruta de
`profile: "workspace"` y `CLEANER`/`TECHNICIAN` no tienen `READ_CONVERSATIONS`—, la vista pinta un
estado localizado de «sin acceso» **sin** botón de reintento. Con 404 en el hilo, el estado
localizado de «no encontrada» (R3.6). El resto de fallos van al `ErrorState` compartido con
reintento (R1.4).

Rejected: dejarlo caer al error genérico con reintento — un reintento que no puede funcionar
(`retryPolicy` ya lo evita internamente) invita a pulsarlo indefinidamente.

### D18 — La copia de error se deriva del `status` del `ApiError`, nunca de su `message`

**Chosen:** un `lib/errors.ts` de feature que traduce `ApiError.status` (403 / 404 / 409 / 422) a
una clave de i18n con fallback genérico, y refresca el estado real tras un 409 (R5.2). `message` es
técnico y en inglés por diseño (`lib/api/errors.ts`) y no se pinta nunca (R1.4). En un fallo de
envío el compositor **conserva el texto** y no marca el mensaje como enviado (R4.5).

Rejected: mapear por `error.code` — los códigos de `ErrorCode` son genéricos (`CONFLICT`,
`VALIDATION_ERROR`) y no distinguen los casos que el operador necesita distinguir.

### D19 — Una columna en móvil sin media queries en JS

**Chosen:** dos paneles en `lg:` y arriba; por debajo se muestra la lista cuando no hay selección y
el hilo cuando la hay, con un control de «volver» que borra el parámetro de la URL. La decisión de
qué se ve depende del **estado** (hay selección o no), no del viewport, así que se resuelve con
clases de Tailwind y sin `matchMedia` — que rompería el determinismo del render y de los tests
(R7.6).

Rejected: `useMediaQuery` — estado derivado del navegador para algo que ya es estado de la URL.

### D20 — Confirmación de resolución sobre el Radix Dialog que ya está en el árbol

**Chosen:** un `components/ui/confirm-dialog.tsx` construido sobre `@radix-ui/react-dialog`, que ya
es dependencia (`components/ui/sheet.tsx` la usa). Es una primitiva genérica, así que vive en
`components/ui/` y no en la feature.

Rejected: `AlertDialog` de shadcn — trae `@radix-ui/react-alert-dialog`, una dependencia nueva para
un diálogo que la que ya hay cubre.
Rejected: `window.confirm` — no se localiza, no se estiliza y no gestiona el foco.

### D21 — Sin diagrama, y dicho a propósito

**Chosen:** la máquina de estados de dos ejes ya tiene su casa en `sdd/specs/messaging-ai.md` y en
`entities.py`; redibujarla aquí duplicaría un hecho (regla 1 de las reglas compartidas). Lo que
esta superficie añade es el mapeo acción → cuándo se ofrece, y eso es la tabla de D10, que además
diffea en revisión.

## Changes by area

Esta tabla nombra **módulos de producción**; los tests colocados (`*.test.ts[x]` junto al
módulo que prueban) van implícitos y no se enumeran — son 23 en este change, incluido
`components/thread-role-gate.test.tsx`, que prueba la puerta de rol de 7.5 y no tiene módulo
propio porque la puerta vive en `conversation-thread.tsx`. Dos se nombran igualmente, y por
motivo: `data/boundary.test.ts` no está colocado junto a ningún módulo homónimo —es la
verificación de R7.3 sobre la feature entera— y `ui/confirm-dialog.test.tsx` acompaña a una
primitiva compartida fuera de la feature. Son las dos excepciones a la convención, no una
contradicción de ella. La convención se escribe aquí a
raíz de la revisión del 2026-08-21, que leyó la tabla como un inventario exhaustivo de
ficheros; lo que sí faltaban eran módulos de producción (`lib/channels.ts`) y un fichero
modificado fuera de la feature (`app/error-architecture.test.ts`), ambos ya en la tabla.

| Area | Files | Change |
|---|---|---|
| Feature: entrada | `frontend/features/conversations/index.ts` | **Nuevo**. Exporta solo `ConversationsView` |
| Feature: datos | `.../conversations/data/dto.ts` | **Nuevo**. `ConversationPage<T>`, `ConversationSummary`, `ConversationDetail`, `ThreadMessage`, `PropertyLabel`, `InboxFilters`, `NewMessage` (D3, D8, D14) |
| | `.../data/conversations-source.ts` | **Nuevo**. Interfaz de siete métodos (D2) |
| | `.../data/http/http-conversations-source.ts` | **Nuevo**. Mapeo explícito `snake_case` → `camelCase` de los 5 endpoints de mensajería + `GET /properties`; `method` explícito y estrechado del tipo de respuesta en `/messages`, que tiene `get` y `post`, como ya hace `http-guest-portal-source.ts` con `/guest/checkin/{token}` |
| | `.../data/index.ts` | **Nuevo**. Único punto de composición vía `createAuthenticatedClients({apiBaseUrl:""})` (R7.1) |
| | `.../data/boundary.test.ts` | **Nuevo**. R7.3: ningún componente/hook/store/lib importa fixtures de test |
| Feature: hooks | `.../hooks/query-keys.ts` | **Nuevo**. Claves con `tenantScopedKey` (D16) |
| | `.../hooks/use-conversations.ts` | **Nuevo**. `useConversationList`, `useConversation`, `useThread`, `usePropertyLabels` |
| | `.../hooks/use-conversation-actions.ts` | **Nuevo**. `useSendReply`, `useTranscribeGuestMessage`, `useEscalate`, `useResolve` + invalidación (D16) |
| Feature: estado | `.../state/use-inbox-filters-store.ts` | **Nuevo**. Filtros + página en Zustand (D6, R2.5) |
| Feature: lógica pura | `.../lib/labels.ts`, `.../lib/transitions.ts`, `.../lib/permissions.ts`, `.../lib/format.ts`, `.../lib/errors.ts`, `.../lib/channels.ts`, `.../lib/limits.ts` | **Nuevos** (D7, D10, D12, D9, D18). `channels.ts` es el predicado `isMuteChannel` que **D13 exige** y que esta tabla omitió hasta la revisión del 2026-08-21; `limits.ts` recoge `MAX_MESSAGE_LENGTH`, que vivía en `reply-composer.tsx` y era el único dato de contrato viajando de componente a componente (D1) |
| Feature: UI | `.../components/conversations-view.tsx` | **Nuevo**. Maestro-detalle, lee/escribe `?conversation=` (D5, D19) |
| | `.../components/inbox-filters.tsx`, `inbox-list.tsx`, `inbox-row.tsx`, `page-nav.tsx` | **Nuevos**. R1, R2 |
| | `.../components/thread-header.tsx`, `conversation-thread.tsx`, `message-bubble.tsx` | **Nuevos**. R3, D13, D14, D15 |
| | `.../components/reply-composer.tsx`, `transcribe-dialog.tsx`, `thread-actions.tsx` | **Nuevos**. R4, R5, D11, D13 |
| Primitivas compartidas | `frontend/components/ui/dialog-shell.tsx`, `frontend/components/ui/confirm-dialog.tsx` (+ `confirm-dialog.test.tsx`) | **Nuevos** (D20). `dialog-shell.tsx` sale de la revisión del 2026-08-21: `ConfirmDialog` cierra siempre al confirmar y no puede servir a la transcripción, que debe quedarse abierta para decir que no se guardó nada (D13), así que el armazón de overlay/contenido —la duplicación real— se extrae y lo componen los dos |
| Ruta | `frontend/app/(workspace)/conversations/page.tsx` | **Modificado**. `RoutePlaceholder` → `<Suspense><ConversationsView/></Suspense>`; `generateMetadata` intacto |
| | `frontend/app/route-coverage.test.ts` | **Modificado**. Entrada `"(workspace)/conversations/page.tsx": "conversations"` en `REAL_PAGE_ROUTE_IDS`, o el test falla al no encontrar `routeId="…"` |
| | `frontend/app/error-architecture.test.ts` | **Modificado**. Su regla «ninguna `page.tsx` importa `Suspense`/`LoadingState`» pasa a llevar lista de exenciones con motivo (task 8.3). La revisión del 2026-08-21 reforzó sus aserciones: la frontera debe tener `fallback` y **envolver** al componente cliente, y ese componente seguir llamando a `useSearchParams()` |
| i18n | `frontend/lib/i18n/resources.ts` | **Modificado**. Namespace `conversations` en `NAMESPACES` y en `resources` de ambos locales (R7.4) |
| | `frontend/locales/es/conversations.json`, `frontend/locales/en/conversations.json` | **Nuevos**. El test de paridad exige juegos de claves idénticos |
| Backend / contrato | — | **Sin cambios**. Ni `make openapi` ni `npm run api:generate` |

## Data & interfaces

**Endpoints consumidos** (todos ya en `lib/api/generated/openapi.d.ts`, ninguno nuevo):

| Método y ruta | Permiso | Se usa para |
|---|---|---|
| `GET /api/v1/conversations` | `READ_CONVERSATIONS` | R1, R2. Query: `page`, `per_page`, `status`, `escalation_status`, `property_id` |
| `GET /api/v1/conversations/{id}` | `READ_CONVERSATIONS` | R3, refresco tras 409 |
| `GET /api/v1/conversations/{id}/messages` | `READ_CONVERSATIONS` | R3. Query: `page`, `per_page` |
| `POST /api/v1/conversations/{id}/messages` | `MANAGE_CONVERSATIONS` | R4. Body `{content}` (responder) o `{content, sender_type:"GUEST"}` (transcribir) |
| `POST /api/v1/conversations/{id}/escalate` | `MANAGE_CONVERSATIONS` | R5. Sin body |
| `POST /api/v1/conversations/{id}/resolve` | `MANAGE_CONVERSATIONS` | R5. Sin body |
| `GET /api/v1/properties` | `READ_PROPERTIES` | R1.7, R2.1. `per_page: 100`, una sola query cacheada |

`POST /api/v1/conversations` (crear) **no se consume**: fuera de alcance por el proposal.

**Formas del contrato que el diseño da por ciertas** (verificadas en el fichero generado):
`ConversationPageResponse`/`MessagePageResponse` = `{items, page, per_page, total}` sin
`total_pages`; `PropertyPageResponse` = `{data, page, per_page, total, total_pages}`;
`ConversationResponse` no trae `property_code` ni nombre de huésped, y `property_id`, `guest_id` y
`last_message_at` son nullables; `MessageResponse.confidence_score` es `string | null` y
`metadata` es `{[k:string]: string} | null`. Las cuatro uniones cerradas: `ConversationStatus`
(4), `ConversationEscalationStatus` (4), `ConversationChannel` (6), `MessageSenderType` (5).

Los 404 y 409 que R3.6 y R5.2 esperan **no están declarados** en las respuestas del contrato
generado (solo 401/403/422): los produce el backend a través del sobre §23 y llegan como
`ApiError.status`. El diseño se apoya en el status del `ApiError`, no en el tipo generado.

**Nada de esquema, migraciones, variables de entorno ni dependencias nuevas.**

## Risks & mitigations

- **La transcripción en un canal mudo pierde el mensaje del huésped** (D13). Mitigación: aviso en
  el diálogo antes de enviar y estado de error que dice explícitamente que no se ha guardado nada.
  No se puede evitar desde el cliente: es una transacción del backend que aborta.
- **Un tenant con más de 100 propiedades pierde etiquetas.** `per_page` tope 100 y R1.7 pide una
  sola query. Mitigación: la rama `IF` de R1.7 ya existe — marcador localizado en vez del código—,
  así que degrada sin romper la fila. Se declara como límite conocido, no se pagina el catálogo.
- **La antigüedad relativa depende del reloj** (D9): render no determinista en tests y potencial
  desajuste de hidratación. Mitigación: la vista es cliente bajo `AuthGuard` (no se prerenderiza
  con datos), y las suites que la comprueban fijan la hora.
- **`useSearchParams()` sin `Suspense` amplía el abandono de prerender a toda la ruta** (D5).
  Mitigación: la frontera está en la página, y lo que detecta su retirada es
  `app/error-architecture.test.ts` (aserciones reforzadas en la revisión del 2026-08-21), **no** el
  build: con la i18n de servidor leyendo `cookies()` en cada página, `next build` pasa igual sin
  frontera. Riesgo residual asumido y declarado: si algún día se quita esa dependencia por petición,
  la ruta vuelve a ser prerenderizable y entonces sí sería el build quien fallara.
- **`route-coverage.test.ts` deja de pasar en cuanto la página no tiene `routeId="…"`.** Mitigación:
  la entrada en `REAL_PAGE_ROUTE_IDS` es parte del cambio, no un arreglo posterior.
- **El hilo no es tiempo real**: la respuesta de la IA aparece porque se genera **dentro** de la
  misma petición (`ProcessInboundGuestMessageUseCase` es síncrono) y la invalidación la trae; un
  mensaje que entre por otra vía no aparece hasta recargar. Fuera de alcance por el proposal, y se
  documenta en la vista para que no se lea como un fallo.
- **La bandeja no dice de quién es cada hilo** (no hay nombre de huésped en el contrato). Riesgo de
  producto real: identificar un hilo exige abrirlo. Mitigación: código de propiedad + canal +
  idioma + antigüedad en la fila, y la deuda queda registrada (OQ1).

## Requirement coverage

| Req | Dónde se resuelve |
|---|---|
| R1.1–R1.6 | D2, D3, D16 (lista, orden del backend sin reordenar, estados compartidos), D9 (R1.2/R1.3) |
| R1.7 | D2 (`listPropertyLabels`, una query cacheada, DTO de tres campos), Risks (tope de 100) |
| R2.1, R2.4, R2.5 | D6, D16 |
| R2.2 | D7 |
| R2.3 | D7 + nota sobre `status = CLOSED`. **R2.3 se enmendó en el gate del 2026-08-19** (OQ1): el estado sin escritor es `CLOSED`, no `HUMAN_HANDLING` |
| R3.1 | D5, D19 |
| R3.2, R3.5 | D2, D3, D16 |
| R3.3 | D7 |
| R3.4 | D8 |
| R3.6 | D17, D18 |
| R3.7 | D13 (corregido: dos avisos, semántica distinta por vía) |
| R4.1, R4.2 | D2 (`createMessage` con y sin `sender_type`), D13 |
| R4.3 | Validación en el compositor: 1–4000 caracteres, contador visible, envío bloqueado en vacío |
| R4.4 | D16 |
| R4.5 | D18 (conserva el texto), mutación con `retry: false` y compositor deshabilitado en vuelo |
| R5.1, R5.3 | D2, D16 |
| R5.2 | D10, D11, D18 |
| R5.4 | D20 |
| R6.1, R6.2 | D12 |
| R6.3 | D18 (403 → error de permisos, nunca reintento) |
| R7.1, R7.2 | D2, D3 |
| R7.3 | D4 + `boundary.test.ts` |
| R7.4 | D7, cambios en `lib/i18n/resources.ts` y los dos catálogos |
| R7.5 | D5 (la frontera acota el abandono de prerender; el build pasa por la i18n de servidor, y quien guarda la frontera es `error-architecture.test.ts`) |
| R7.6 | D19 + nombres accesibles localizados y foco visible en los controles |
| Seguridad | D12 (RBAC solo oculta), D15 (prosa verbatim como texto), D2 (notas de propiedad fuera de la caché), claves con ámbito de tenant en D16 |

## Open questions

Las tres se resolvieron en el gate de `/sdd:design` del **2026-08-19**. Se conservan con su
resolución porque cada una cambió el proposal o el alcance, y borrarlas dejaría los cambios sin
motivo escrito.

**OQ1 — Dos estados que el proposal declaraba inalcanzables sí lo son.** Verificado en
`use_cases.py` y `entities.py`:

- `take_over` (`PENDING_HUMAN` → `HUMAN_HANDLING`) **se alcanza**: `RecordHumanReplyUseCase` lo
  llama cuando un manager responde a un hilo que espera a una persona — «answering *is* taking
  over». Así que el filtro `HUMAN_HANDLING` **no** está siempre vacío y la nota que R2.3 pide
  diría algo falso.
- `reopen` (`RESOLVED` → `OPEN`) **se alcanza**: transcribir un mensaje de huésped en un hilo
  resuelto lo reabre (paso 1 del pipeline).
- El valor realmente sin escritor es `ConversationStatus.CLOSED`: aparece como origen y nunca como
  destino, y ninguna ruta lo produce.

**Resuelto — corregir R2.3 y el apunte de roadmap.** (a) R2.3 re-apunta su nota a `CLOSED` y
prohíbe explícitamente ponerla en `HUMAN_HANDLING`; (b) la entrada propuesta
`messaging-inbox-projection` se reduce a la proyección de bandeja (nombre de huésped + preview del
último mensaje), quitando `take_over`/`reopen` de su alcance. `proposal.md` ya está enmendado en
R2.3, en *Out of scope* y en *Registro en el roadmap*.

**OQ2 — ¿Se marca la entrega fallida en los mensajes de la IA?** No estaba en el proposal. A favor:
`metadata.delivery_status` ya viene en el payload, y en `PHONE_TRANSCRIPT` **toda** respuesta de la
IA se guarda como `FAILED`, así que sin la marca la bandeja enseña como enviado algo que el huésped
no recibió. En contra: amplía R3 con un campo que nadie pidió.

**Resuelto — entra en alcance.** D14 se implementa: los dos campos nombrados en el DTO y marca
localizada de «no entregado». Es una ampliación de R3 que este diseño asume explícitamente, no un
requisito nuevo del proposal.

**OQ3 — ¿Acción inválida deshabilitada con motivo, u oculta?** La lectura literal de R5.2 («ofrecer
cada acción solo cuando la transición es válida») admite ocultarla.

**Resuelto — deshabilitada con motivo localizado** (D11): «ofrecer» se lee como *accionable*, y el
manager necesita saber que la conversación ya está escalada en vez de buscar un botón que no está.
