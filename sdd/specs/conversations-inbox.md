# Bandeja de conversaciones (`/conversations`)

## Purpose

La superficie web desde la que un operador del tenant **opera** la bandeja de conversaciones
que produce el módulo de mensajería: `/conversations` lista las conversaciones del tenant
paginadas y filtrables por `status` y `escalation_status`, y `/conversations/[id]` muestra
el hilo con sus mensajes en orden cronológico ascendente y el formulario para responder
manualmente. Es una capa de presentación pura sobre los siete endpoints de
[`messaging-ai.md`](messaging-ai.md) R7 — **no añade ni relaja ninguna regla de negocio ni
de acceso**: el backend sigue siendo la única autoridad sobre `Conversation` y `Message`, sus
transiciones, su aislamiento por tenant y la persistencia del mensaje. Las conversaciones que
la bandeja pinta las crea otro productor (pipeline de `messaging-ai` R4 desde un `Incident`
con intent `MAINTENANCE_ISSUE`/`ACCESS_PROBLEM`, portal del huésped, transcripción manual);
`make seed-demo` deja la bandeja legítimamente vacía y es el estado vacío localizado de R2.4.

## Requirements

### R1 — Shell: rutas `/conversations` y `/conversations/[id]`

- WHEN un usuario autenticado abre `/conversations`, THE SYSTEM SHALL renderizar
  `<ConversationsView />` en lugar del `RoutePlaceholder routeId="conversations"`, bajo
  el `AuthGuard` del grupo `(workspace)`, que redirige a `/login?returnTo=…` a quien no
  tenga sesión.
- WHEN un usuario autenticado abre `/conversations/[id]`, THE SYSTEM SHALL renderizar
  `<ConversationThreadView conversationId={id} />`, leyendo `id` de `params`
  (`Promise<{id: string}>` de Next.js App Router).
- THE SYSTEM SHALL registrar ambas rutas en `route-registry.ts` con `navigationGroup:
  "work"`, `order: 4` y `icon: "MessagesSquare"`, y SHALL exponer sus títulos y
  descripciones en `navigation:routes.conversations.*` y `navigation:routes.conversation-detail.*`
  de `frontend/locales/{es,en}/navigation.json`.
- THE SYSTEM SHALL mantener `frontend/app/route-coverage.test.ts` con las dos entradas
  `"(workspace)/conversations/page.tsx": "conversations"` y
  `"(workspace)/conversations/[id]/page.tsx": "conversation-detail"`, de modo que un test
  cubra que ninguna ruta del workspace ha vuelto a `RoutePlaceholder` por accidente.
- THE SYSTEM SHALL aplicar `routeMetadata("conversations")` y
  `routeMetadata("conversation-detail")` desde `generateMetadata`, y SHALL no ofrecer
  edición, borrado ni reordenación de mensajes individuales; SHALL ofrecer solo la acción
  de **responder como humano** (R4).

### R2 — Listado paginado y filtrable en `/conversations`

- WHEN `/conversations` carga, THE SYSTEM SHALL pedir `GET /api/v1/conversations` con los
  filtros activos (`status`, `escalation_status`, `property_id`) y la página solicitada,
  y NO SHALL filtrar en el cliente una página ya descargada.
- THE SYSTEM SHALL mostrar el orden que devuelve el backend (`last_message_at DESC` con
  nulos al final — [`messaging-ai.md`](messaging-ai.md) R7), y NO SHALL reordenar en el
  cliente.
- THE SYSTEM SHALL consumir el shape `{items, total, page, per_page}` del backend sin
  asumir la forma antigua, y SHALL no romper el typecheck si el backend cambia la forma
  del envelope.
- THE SYSTEM SHALL enviar `page` y `per_page` como enteros validados; si el backend
  responde `422`, SHALL mostrar el `ErrorState` localizado de paginación inválida.
- WHEN el operador cambia un filtro, THE SYSTEM SHALL volver a la página 1 sin perder los
  demás filtros activos.
- IF ninguna conversación coincide con los filtros activos, THEN THE SYSTEM SHALL
  mostrar `EmptyState` localizado (`states:empty.title` / `states:empty.description`)
  distinguible del estado de error y del de carga.
- WHILE la consulta está en vuelo, THE SYSTEM SHALL mostrar `LoadingState`
  (`role="status"`, `aria-busy="true"`, `aria-live="polite"`, esqueletos `aria-hidden`)
  del namespace `states`, sin estado de carga propio.
- IF la consulta falla por `401`/`403`/`404`/`422`, THEN THE SYSTEM SHALL mostrar
  `ErrorState` con `role="alert"` y una acción de reintento que relanza la consulta;
  SHALL no reintentar respuestas `4xx` automáticamente.
- THE SYSTEM SHALL reintentar hasta dos veces respuestas distintas de `4xx` por la
  política de reintentos compartida del frontend.
- THE SYSTEM SHALL derivar el conjunto de valores de cada enum (`ConversationStatus`,
  `ConversationEscalationStatus`, `ConversationChannel`) del contrato generado en
  `frontend/lib/api/generated/openapi.d.ts`, no de una recopia local, de modo que un
  valor nuevo en el backend rompa el typecheck; SHALL degradar a gris un valor
  desconocido en runtime para que una asimetría de despliegue no tumbe la vista.

### R3 — Hilo de una conversación en `/conversations/[id]`

- WHEN `/conversations/[id]` carga, THE SYSTEM SHALL pedir `GET /api/v1/conversations/{id}`
  y `GET /api/v1/conversations/{id}/messages` en paralelo, y SHALL mostrar el hilo solo
  cuando **ambas** respuestas estén disponibles, sin pintar estado intermedio.
- THE SYSTEM SHALL pintar los mensajes en el orden cronológico ascendente que devuelve
  el backend, y NO SHALL invertir el orden en el cliente.
- WHEN un mensaje tiene `sender_type = GUEST` o `ai_generated = true`, THE SYSTEM SHALL
  renderizar su `content` como **texto plano**: la regla 11 de
  [`steering/security.md`](../steering/security.md) lo prohíbe como HTML o estructura
  interpretable, y SHALL añadir un test (`conversation-thread-messages.test.tsx`) que lo
  verifique.
- WHEN el operador pide una página siguiente de mensajes, THE SYSTEM SHALL concatenar
  sin duplicar y sin reordenar los mensajes ya cargados con la página siguiente, hasta
  agotar `total`.
- WHEN el backend responde `404` para una conversación inexistente o de otro tenant,
  THE SYSTEM SHALL mostrar el mismo estado de "no encontrada" localizado sin filtrar
  existencia; SHALL aplicar la misma indistinguibilidad que
  [`messaging-ai.md`](messaging-ai.md) R1 declara para el backend.
- WHEN la consulta falla por `401`/`403`/`422`/5xx, THE SYSTEM SHALL mapear el error a
  `ErrorState` localizado vía `mapConversationsError`, que distingue `404`/`403`/`422`
  del resto.
- IF una conversación queda inválida por una mutación remota (otra pestaña la escaló o
  resolvió), THEN THE SYSTEM SHALL invalidar `conversation`, `conversation-messages` y
  `conversations-list` desde `onSettled` del `useReplyToConversation`, y SHALL pintar
  el estado fresco sin recarga.

### R4 — Respuesta humana en `/conversations/[id]`

- WHEN el operador envía el formulario de respuesta, THE SYSTEM SHALL llamar
  `POST /api/v1/conversations/{id}/messages` con `body: { content }`, **omitiendo
  `sender_type`** (el backend lo deriva del rol del caller, R7 de
  [`messaging-ai.md`](messaging-ai.md)) y SHALL no enviar `sender_user_id` ni
  `sender_type` desde el cliente.
- IF el `content` supera `MAX_MESSAGE_CONTENT_LENGTH` (4000 caracteres), THEN THE
  SYSTEM SHALL bloquear el envío en el cliente con el contador localizado de
  caracteres restantes, y SHALL no enviar la petición.
- THE SYSTEM SHALL limpiar el `body` y el `content` del formulario tras una respuesta
  exitosa, preservando el borrador mientras la mutación está en vuelo (optimista) o
  mientras falla sin haber sido aceptada por el backend.
- THE SYSTEM SHALL invalidar `conversation`, `conversation-messages` y `conversations-list`
  desde `onSettled` (no `onSuccess`), de modo que un fallo también refresque el estado
  en caso de que el backend hubiera aplicado efectos colaterales.
- THE SYSTEM SHALL configurar la mutación con `retry: false` (precedente:
  `use-assign-cleaning-task`), porque reintentar una respuesta que el backend rechazó
  con `422` solo añadiría carga sin cambiar el veredicto.
- IF el backend responde `409` (transición inválida), THEN THE SYSTEM SHALL mostrar el
  error localizado y SHALL invalidar la conversación para reflejar el estado remoto.
- WHEN el envío tiene éxito, THE SYSTEM SHALL añadir el mensaje al hilo sin esperar
  al refetch (insertar en el cache de TanStack Query bajo `conversation-messages`),
  para que el operador vea su respuesta antes de que la red complete la invalidación.

### R5 — Etiquetas localizadas de las cuatro enumeraciones

- THE SYSTEM SHALL crear `frontend/locales/{es,en}/conversations.json` con seis
  secciones: `status`, `escalationStatus`, `channel`, `senderType`, `fields` y `thread`.
  Las cuatro secciones de enums SHALL cubrir los valores generados desde
  `frontend/lib/api/generated/openapi.d.ts`:

  | Enum | Valores |
  |---|---|
  | `ConversationStatus` | `OPEN`, `RESOLVED`, `ESCALATED`, `CLOSED` |
  | `ConversationEscalationStatus` | `NONE`, `PENDING_HUMAN`, `HUMAN_HANDLING`, `RESOLVED` |
  | `ConversationChannel` | `WHATSAPP`, `AIRBNB_MSG`, `BOOKING_MSG`, `EMAIL`, `PHONE_TRANSCRIPT`, `MANUAL`, `PORTAL` |
  | `MessageSenderType` | `GUEST`, `OWNER`, `MANAGER`, `AI`, `SYSTEM` |

- THE SYSTEM SHALL etiquetar cada valor con una cadena traducida, no con el
  identificador crudo del enum, y SHALL colorear la etiqueta de estado con el mismo
  color que el resto del workspace para el mismo valor semántico.
- THE SYSTEM SHALL etiquetar `sender_type` en la cabecera del mensaje con la sección
  `senderType` (Tú / Huésped / IA / Sistema / Propietaria), no con un literal inglés,
  para que el operador sepa quién escribió sin traducir mentalmente.
- THE SYSTEM SHALL consumir `frontend/locales/{es,en}/states.json` para
  `loading.label`, `error.title`, `error.description`, `error.retry`, `empty.title` y
  `empty.description`, y NO SHALL duplicarlos en `conversations.json`.

### R6 — Tenancy, free-text sink y patrones del frontend

- THE SYSTEM SHALL depender SOLO de `getConversationsDataSource()` desde la UI y los
  hooks; SHALL no instanciar `HttpConversationsSource` fuera de
  `frontend/features/conversations/data/index.ts`, y SHALL no exponer la interfaz
  `ConversationsDataSource` ni un `MockConversationsSource` — el backend existe desde
  [`messaging-ai.md`](messaging-ai.md) archivado y no hay mock que preservar (precedente:
  `incidents-web` D1, `reservations-web` D1).
- THE SYSTEM SHALL construir el cliente HTTP con el `ApiClient` autenticado exportado
  por [`frontend-foundation.md`](frontend-foundation.md), reutilizando el mismo
  composition point que `features/incidents/data/index.ts` y
  `features/reservations/data/index.ts`.
- THE SYSTEM SHALL centralizar las claves de TanStack Query en
  `frontend/features/conversations/hooks/query-keys.ts` con la forma
  `["conversations", "list", filtros]` / `["conversations", "detail", id]` /
  `["conversations", "detail", id, "messages", page]`, y SHALL invalidar las tres
  desde `onSettled` de la mutación de respuesta.
- THE SYSTEM SHALL mapear los errores HTTP a UI a través de
  `frontend/features/conversations/lib/error-mapping.ts`, que produce un
  `ConversationsError` discriminado por `kind` (`notFound`, `forbidden`, `validation`,
  `network`, `unknown`) y SHALL cubrir `401`/`403`/`404`/`422`/5xx.
- THE SYSTEM SHALL aplicar la regla 11 de [`steering/security.md`](../steering/security.md):
  ningún componente SHALL inyectar `messages.content` como HTML; SHALL escapar siempre
  vía React, y SHALL añadir un test (`conversation-thread-messages.test.tsx`) que
  verifique que `<script>alert(1)</script>` como contenido se renderiza como texto
  literal.
- THE SYSTEM SHALL aplicar la regla 6 de [`steering/architecture.md`](../steering/architecture.md):
  el código de `features/conversations/` SHALL importar solo de `@/lib/api`, `@/i18n`
  y `@/features/shell`; SHALL no importar de `@/features/incidents` ni de
  `@/features/reservations`, y SHALL ser importable desde `app/(workspace)/...` sin
  ciclos.
- THE SYSTEM SHALL ejecutar la suite del feature con el mismo target que
  [`frontend-foundation.md`](frontend-foundation.md) §Testing (`npm run typecheck`,
  `npm run lint`, `npm test`), SHALL pasar `npm run api:check` sin regenerar el
  contrato — los símbolos `ConversationStatus`, `ConversationEscalationStatus`,
  `ConversationChannel`, `MessageSenderType`, `ConversationResponse`,
  `ConversationPageResponse`, `MessageResponse`, `CreateMessageRequest` viven en
  `frontend/lib/api/generated/openapi.d.ts` y SHALL demostrarse en la suite de
  verificación del change.

## Key files

- `frontend/features/conversations/data/dto.ts` — tipos DTO derivados del cliente
  tipado (`ConversationSummaryDto`, `ConversationDetailDto`, `MessageDto`,
  `ConversationFilters`, `ConversationPagination`).
- `frontend/features/conversations/data/http/http-conversations-source.ts` — el
  `HttpConversationsSource` que implementa las cuatro llamadas (`list`, `detail`,
  `messages`, `reply`).
- `frontend/features/conversations/data/index.ts` — composition point único que
  instancia `HttpConversationsSource` con el `ApiClient` autenticado y exporta
  `getConversationsDataSource()`.
- `frontend/features/conversations/hooks/query-keys.ts`, `use-conversations.ts`,
  `use-reply-to-conversation.ts` — hooks de TanStack Query con `onSettled` invalidando
  las tres claves.
- `frontend/features/conversations/lib/error-mapping.ts` — el mapa a `ConversationsError`
  discriminado.
- `frontend/features/conversations/components/list/conversations-view.tsx`,
  `conversations-filters.tsx` — la lista con sus dos filtros y la paginación.
- `frontend/features/conversations/components/thread/conversation-thread-view.tsx`,
  `conversation-thread-messages.tsx`, `conversation-thread-sender-meta.tsx`,
  `conversation-reply-form.tsx` — el hilo y el formulario.
- `frontend/features/conversations/index.ts` — el barrel que exporta la vista, el
  hilo y el composition point.
- `frontend/app/(workspace)/conversations/page.tsx` — sustituye el
  `RoutePlaceholder` por `<ConversationsView />`.
- `frontend/app/(workspace)/conversations/[id]/page.tsx` — renderiza
  `<ConversationThreadView conversationId={id} />`.
- `frontend/app/route-coverage.test.ts` — registro de las dos rutas reales.
- `frontend/locales/{es,en}/conversations.json` — las seis secciones de etiquetas.
- `frontend/lib/api/generated/openapi.d.ts` — los tipos consumidos
  (`ConversationStatus`, `ConversationEscalationStatus`, `ConversationChannel`,
  `MessageSenderType`, `ConversationResponse`, `ConversationPageResponse`,
  `MessageResponse`, `CreateMessageRequest`); no regenerados por este change.
- El backend que sirve las cuatro llamadas vive en [`messaging-ai.md`](messaging-ai.md);
  este spec solo cubre la cara FE.
