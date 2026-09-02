# Tasks: guest-portal-messaging

> Orden pensado para que el árbol quede verde al final de cada sección. Las secciones 1-4
> son backend interno (nadie las alcanza aún); la 7 es la que abre la superficie anónima.

## 1. El canal `PORTAL`: enum, adapter y migración <!-- core-reviewers: architect/security/qa CLEAN 2026-08-29 tras 1 ronda de arreglos; panel gate NO ejecutado (ver BLOCKED.md) -->

- [x] 1.1 Añadir `PORTAL = "PORTAL"` a `ConversationChannel` en
  `backend/app/messaging/domain/enums.py`. Test en `backend/tests/messaging/test_enums.py`
  que afirma la pertenencia y el valor. [R3.1]
- [x] 1.2 Escribir `PortalOutboundAdapter` en
  `backend/app/messaging/infrastructure/channels.py` y registrarlo como entrada **literal** del
  `dict` de `outbound_registry()` (nunca por despacho dinámico). Su docstring nombra el endpoint
  que sostiene su promesa —`GET /api/v1/guest/messages/{token}`— igual que
  `PanelOutboundAdapter` nombra el suyo, y **no** gana entrada en `contact_kind_for`. Tests en
  `backend/tests/messaging/test_channels.py`: la clave existe, es una clase distinta de
  `PanelOutboundAdapter`, reporta entrega, y `contact_kind_for(PORTAL)` es `None`. [R3.1, R3.2]
- [x] 1.3 Crear la revisión Alembic en `backend/alembic/versions/` con
  `down_revision = "d4a7e18c6b93"` (head actual): `ALTER TYPE conversation_channel ADD VALUE
  IF NOT EXISTS 'PORTAL'` **dentro de `op.get_context().autocommit_block()`**, más el índice único
  parcial sobre `conversations (tenant_id, reservation_id)` con predicado **`WHERE channel =
  'PORTAL'`**. El `downgrade` borra el índice y **deja la etiqueta**, diciéndolo en el cuerpo como
  hizo `c8e1f4a92b70`. El cuerpo explica por qué hace falta salir de la transacción y qué cuesta
  (D7, corregido el 2026-08-29: el casteo a `text` que la redacción original elegía **no es
  declarable** en un predicado de índice — `functions in index predicate must be marked IMMUTABLE`).
  El mismo índice se declara además en `__table_args__` de `ConversationModel`, porque la suite
  construye su esquema con `create_all` y no corre las migraciones. [R3.1, R3.4]
- [x] 1.4 Verificar la migración en limpio:
  `docker compose exec backend uv run alembic downgrade base && docker compose exec backend
  uv run alembic upgrade head`. [R3.4]

## 2. El actor portador de token <!-- core-reviewers: architect/security/qa CLEAN 2026-08-29 tras 2 rondas de arreglos; panel gate NO ejecutado (ver BLOCKED.md) -->

- [x] 2.1 Declarar `InboundMessageActor` frozen en
  `backend/app/messaging/domain/value_objects.py` con `user_id: uuid.UUID | None`,
  `token_hash: str | None`, `ip: str | None`, y un `__post_init__` que exige **exactamente uno**
  de los dos actores. Tests en `backend/tests/messaging/test_value_objects.py`: acepta cada
  actor por separado, rechaza los dos a la vez y rechaza ninguno. [R4.1]
- [x] 2.2 Sustituir `actor_user_id` + `ip` por `actor: InboundMessageActor` en
  `ProcessInboundGuestMessageUseCase.execute` (`backend/app/messaging/application/use_cases.py`)
  y en `IncidentReportingPort.report` (`backend/app/messaging/domain/ports.py`), actualizando
  `backend/app/messaging/api/router.py` para construirlo desde el `User` autenticado. Los tests
  existentes de `backend/tests/messaging/test_use_cases.py`, `test_ports.py` y
  `test_api_conversations.py` se adaptan a la firma nueva. [R4.1]
- [x] 2.3 Adaptar el implementador `ReportIncidentFromConversationUseCase`
  (`backend/app/maintenance/application/use_cases.py`) para derivar del actor las tres cosas que
  hoy tiene fijas: el reportante del `Incident` (`reported_by_user_id` **o**
  `reported_by_guest_token`), el actor del `AuditLog` (`actor_user_id` **o**
  `actor_guest_token_hash`) y el `TimelineActorType` (`USER` **o** `GUEST`). Tests en
  `backend/tests/maintenance/` que cubran las dos ramas y afirmen que la fila de `AuditLog`
  lleva exactamente uno de los dos actores. [R4.1]

## 3. Repositorio: una sola conversación `PORTAL` por estancia <!-- core-reviewers: architect/security/qa CLEAN 2026-08-29 tras 1 ronda; panel gate NO ejecutado (ver BLOCKED.md) -->

- [x] 3.1 Añadir `ensure_portal(...)` y `find_portal(tenant_id, reservation_id) -> Conversation
  | None` al `Protocol` `ConversationRepository`
  (`backend/app/messaging/domain/repositories.py`), con docstrings que fijen que ninguno
  commitea y que `find_portal` **no crea nada**. [R2.5, R3.4]
- [x] 3.2 Implementarlos en `backend/app/messaging/infrastructure/repositories.py`:
  `ensure_portal` hace `INSERT … ON CONFLICT DO NOTHING` seguido de `SELECT` (precedente:
  `cleaning/infrastructure/repositories.py:397`), y ambos filtran por `channel = PORTAL` y por
  `tenant_id`. `reservation_id` va tipado **obligatorio** (`uuid.UUID`, nunca `| None`) en las
  dos firmas: el índice no alcanza a las filas con `reservation_id IS NULL` —los `NULL` no
  colisionan entre sí— así que sin ese tipo R3.4 dependería de qué llamante haya (D6, panel de
  seguridad de la sección 1). Tests en `backend/tests/messaging/test_repositories.py`: crea la primera vez,
  devuelve la existente la segunda sin duplicar, `find_portal` devuelve `None` sin insertar, y
  ninguno de los dos ve ni toca conversaciones de otros canales de la misma estancia. [R3.4, R3.5]
- [x] 3.3 Test de concurrencia en `backend/tests/messaging/test_repositories.py`: dos sesiones
  concurrentes llamando a `ensure_portal` sobre la misma estancia acaban en **una** fila y
  ambas la ven, sin que el perdedor de la carrera aborte su transacción. [R3.4]

## 4. La bandeja no puede abrir un hilo de portal <!-- core-reviewers: architect/security/qa CLEAN 2026-08-29 (revisada junto con la 3); panel gate NO ejecutado -->

- [x] 4.1 `CreateConversationUseCase` (`backend/app/messaging/application/use_cases.py`) rechaza
  `ConversationChannel.PORTAL` con `MessagingValidationError` —en el caso de uso, no en el
  esquema—. Tests en `backend/tests/messaging/test_use_cases.py` y en
  `backend/tests/messaging/test_api_conversations.py` (la ruta `POST /api/v1/conversations`
  responde con el error de validación, no con un `201`). [R3.7]

## 5. Los puertos del portal y la proyección congelada <!-- core-reviewers: panel de 7 (architect/security/qa + cicd/documentation/i18n/tenancy) 2026-08-30: CLEAN tras 1 ronda de arreglos; gate ejecutable NO ejecutado (ver BLOCKED.md) -->

- [x] 5.1 En `backend/app/guests/domain/portal_ports.py`, declarar los enums cerrados
  `PortalMessageSender` (`GUEST`, `PROPERTY`) y `PortalThreadState` (`AUTOMATIC`,
  `AWAITING_HUMAN`), y los dataclasses frozen `PortalMessage` (`id`, `sender`, `content`,
  `created_at`) y `PortalThread` (`items`, `total`, `page`, `per_page`, `state`). Docstring en
  la línea de `StayInfo`: el listado de campos *es* el control de seguridad. [R2.2, R2.3, R2.4]
- [x] 5.2 En el mismo fichero, declarar los dos `Protocol`: `GuestPortalThreadReader` y
  `GuestPortalMessageSubmitter`, ambos recibiendo el `GuestSession` y **ningún** identificador
  suelto, y sin ningún método de escalar, resolver, cerrar, reabrir ni listar. [R1.3, R2.6, R3.5]
- [x] 5.3 Tests en `backend/tests/guests/test_portal_ports.py`: `PortalMessage` y `PortalThread`
  son frozen; el conjunto de sus campos es **exactamente** el declarado (test estructural que
  falla si alguien añade `sender_user_id`, `ai_generated`, `confidence_score`, `intent`,
  `metadata`, `conversation_id` o una razón de escalación); los dos enums tienen exactamente
  dos miembros. [R2.2, R2.4]

## 6. Los casos de uso del portal en `messaging` <!-- core-reviewers: panel de 7 (architect/security/qa + cicd/documentation/i18n/tenancy) 2026-08-30: CLEAN tras 1 ronda de arreglos; gate ejecutable NO ejecutado (ver BLOCKED.md) -->

- [x] 6.1 Extraer la condición de `_is_handed_over`
  (`backend/app/messaging/application/use_cases.py:104`) a una función compartida que consuman
  el pipeline y el lector del hilo, para que no puedan divergir. Test que afirme que las dos
  vías dan el mismo veredicto sobre las mismas conversaciones. [R2.3]
- [x] 6.2 Crear `backend/app/messaging/application/portal.py` con
  `PostPortalGuestMessageUseCase`: resuelve o crea la conversación `PORTAL` vía `ensure_portal`
  con `property_id`, `reservation_id` y `guest_id` del `GuestSession` y `language =
  detect_language(content) or "es"` (solo en la creación), y delega en
  `ProcessInboundGuestMessageUseCase.execute(...)` pasándole un `InboundMessageActor` con el
  `token_hash`. **No construye ningún `Message`.** Devuelve un `PortalMessage`. Tests en
  `backend/tests/messaging/test_portal_use_cases.py` (nuevo): el pipeline entero corre (mensaje
  con intent y confianza, `TimelineEvent(GUEST_MESSAGE_RECEIVED)`, evaluación de escalación,
  respuesta o escalación, incidencia para `MAINTENANCE_ISSUE`/`ACCESS_PROBLEM`) en **un solo
  commit**; y un test que afirme que el caso de uso no instancia `Message`.
  **Y el test que la sección 3 no puede escribir**: que los tres anclajes (`property_id`,
  `reservation_id`, `guest_id`) salen del `GuestSession` y de ningún campo de la petición.
  `ensure_portal` **declara** esa precondición y no la comprueba —las FK de `conversations`
  son globales, no compuestas con `tenant_id`—, así que este caso de uso es lo único que la
  sostiene; `CreateConversationUseCase` se gasta tres lecturas en el mismo peligro. Lo levantó
  el panel de seguridad de las secciones 3-4, y el hueco queda fijado en
  `test_tenant_isolation.py::test_ensure_portal_does_not_verify_the_stay_belongs_to_the_tenant`.
  [R1.3, R1.4, R3.3, R4.1]
- [x] 6.3 En el mismo módulo, `ReadPortalThreadUseCase`: usa `find_portal`; sin conversación
  devuelve `PortalThread(items=(), total=0, state=AUTOMATIC)` sin crear nada; con ella reutiliza
  `MessageRepository.list_for_conversation` (ya ascendente por `(created_at, id)`), con
  paginación `?page&per_page` y los topes que `messaging/api/schemas.py` ya declara
  (`MAX_PER_PAGE = 100`, `MAX_PAGE = 100_000`). Sin `page`, calcula
  `page = max(1, ceil(total / per_page))` — la última ventana. `state` sale de la función
  compartida de 6.1. Tests: hilo vacío devuelve `200` sin fila creada; orden ascendente;
  `page` omitido devuelve la última página; `page` explícito alcanza las anteriores; `total`,
  `page` y `per_page` viajan en la respuesta. [R2.1, R2.3, R2.5]
- [x] 6.4 La agrupación de remitente es un `dict[MessageSenderType, PortalMessageSender]`
  **total** en el implementador, con test que afirme `set(mapa) == set(MessageSenderType)` —un
  miembro nuevo del enum rompe el test en vez de caer por defecto en `PROPERTY`—. Test adicional:
  un mensaje de `sender_type = AI` y otro de `MANAGER` se emiten los dos como `PROPERTY`, y la
  proyección no lleva forma alguna de distinguirlos. [R2.2, R5.5]
- [x] 6.5 Test que `PostPortalGuestMessageUseCase` y `ReadPortalThreadUseCase` satisfacen
  estructuralmente los dos `Protocol` de 5.2 (comprobación de tipo o `isinstance` sobre
  `runtime_checkable`, según el patrón que ya use `backend/tests/guests/test_portal_wiring.py`).
  [R1.4, R2.1]

## 7. Las dos rutas anónimas y su cableado <!-- core-reviewers: panel de 7 (architect/security/qa + cicd/documentation/i18n/tenancy) 2026-08-30: CLEAN tras 1 ronda de arreglos; gate ejecutable NO ejecutado (ver BLOCKED.md) -->

- [x] 7.1 `PostGuestMessageRequest` en `backend/app/guests/api/portal_schemas.py`: un **único**
  campo `content` (`MultiLineText` de `app/core/storable_text.py`, `min_length=1`,
  `max_length=MAX_MESSAGE_CONTENT_LENGTH`) y `model_config = ConfigDict(extra="forbid")`.
  Los esquemas de respuesta publican la proyección de 5.1 y nada más. [R1.5, R1.6, R4.3]
- [x] 7.2 Declarar `POST` y `GET /api/v1/guest/messages/{token}` en
  `backend/app/guests/api/portal_router.py`, con el token como **último** segmento, reutilizando
  `_authorised` (probe → authorize → record_failed → request_allowed) **sin una segunda copia
  del orden**, `_PORTAL_RESPONSES` tal cual, y `_unauthorised` para cualquier
  `GuestPortalUnauthorised` levantada después de autorizar. El `POST` responde `201`. Ningún
  identificador se lee de la ruta, del cuerpo, de la query ni de una cabecera: todos salen del
  `GuestSession`. **El `POST` pasa además `client_ip` al submitter** (`get_client_ip`, como las
  cuatro rutas ya existentes): no es un identificador —la reserva, el tenant y la propiedad
  siguen saliendo del token— sino la dirección de la que llegó la petición, y la regla 9 la
  quiere en `actor_ip`. Sin ella toda fila `INCIDENT_CREATED` del portal iría con `actor_ip`
  NULL mientras `POST /guest/incident/{token}` sí la registra, para el mismo actor anónimo y la
  misma entidad. El puerto ya declara el parámetro (sección 5, panel de seguridad de §5-6).
  El throttle por token no es sólo el límite de ritmo de la ruta: desde D8 es
  **lo único que acota que un portador escriba filas de `audit_logs`** (una por mensaje con
  intent de incidencia), que es el patrón de hecho de la tercera excepción de la regla 9. El
  comentario de la ruta lo nombra citando D8, sin volver a derivarlo. [R1.1, R1.2, R1.3, R1.7,
  R4.3, R4.7]
- [x] 7.3 Cablear los dos puertos en `backend/app/guests/api/portal_dependencies.py`,
  reutilizando `get_process_inbound_message_use_case` para no duplicar el grafo del pipeline.
  Test en `backend/tests/guests/test_portal_wiring.py`. [R1.4]
- [x] 7.4 Tests de ruta en `backend/tests/guests/test_portal_messages_api.py` —fichero
  propio y no más casos en `test_portal_api.py`, siguiendo el precedente que sentó
  `test_portal_incident_api.py` para la cuarta ruta: aquél ya son mil líneas sobre la
  estancia, el check-in y las cinco negativas, y una ruta cuyo montaje es una conversación
  y un pipeline no comparte sus fixtures. Cambio de ubicación acordado durante `/sdd:run`;
  el contenido de la tarea no cambia—: `201` con el mensaje
  registrado; `422` para `sender_type`, `tenant_id`, `reservation_id`, `property_id`,
  `conversation_id` y `ai_generated` en el cuerpo; `422` por longitud y por texto no almacenable
  (`U+0000`, sustituto suelto) **antes de crear nada** y sin eco del valor rechazado; `404`
  constante e indistinguible para token inexistente, mal formado, revocado, fuera de ventana y
  de reserva cancelada, en **las dos** rutas; `429` cuando el throttle por token se agota.
  [R1.1, R1.5, R1.6, R1.7, R4.3, R4.7]
- [x] 7.5 Test de que la respuesta del `GET` no contiene `sender_user_id`, `ai_generated`,
  `confidence_score`, `intent`, `metadata`, `conversation_id` ni razón de escalación, ni
  siquiera cuando la conversación está `PENDING_HUMAN`/`HUMAN_HANDLING` — donde sí declara
  `AWAITING_HUMAN`. [R2.2, R2.3, R2.4]
- [x] 7.6 Tests de aislamiento propios, en `backend/tests/guests/` y con la cautela que fija el
  design: montar la fixture del tenant A **antes** de cualquier ligado de sesión y conducir la
  **ruta real** con el token del tenant B. Uno por vía: lectura del hilo y envío. Ninguna de
  las dos alcanza mensajes ni conversaciones del otro tenant. [R4.5]

## 8. Censos, sumideros y contrato publicado

- [x] 8.1 Añadir las dos entradas nuevas a `ANONYMOUS_ENDPOINTS` en
  `backend/tests/test_route_authorization.py` (de cuatro rutas de portal a seis) y **reescribir**
  el comentario de las líneas 82-95 contra la lista resultante —«That is the whole of PRD §23's
  guest surface», «a fifth route under `/api/v1/guest/`»—, recontando sobre la lista y no
  incrementando el número a ojo. [R4.6]
- [x] 8.2 Enmendar en `sdd/steering/security.md` la fila del censo de la regla 11 para
  `messages.content` con `sender_type = GUEST`: nombrar `guest-portal-messaging` como escritor
  vivo y declarar el cambio de audiencia (de prosa transcrita por un operador autenticado a
  escritura directa de un portador anónimo desde internet), ampliando la enumeración de la
  excepción 4 con el portal. Se **enmienda**, no se parte: quien teclea sigue siendo el huésped.
  [R4.2]
- [x] 8.3 Comprobar que `backend/tests/test_rule11_ownership.py` sigue verde: el código nuevo de
  `backend/app/`, `backend/tests/`, `backend/alembic/versions/` y `docs/` puede **citar** la
  regla pero no reafirmar quién escribe o hereda una columna del censo. [R4.2]

  **No estaba verde al llegar aquí, y no por este change.** El guardián señalaba
  `sdd/roadmap.md:187`, la entrada `guest-scheduled-comms`, cuya frase «sus tres tipos no
  tienen escritor» dispara el eje de propiedad (`(?:ya\s+)?tienen?\s+escritor`) junto al
  «regla 11» del mismo bloque. Introducida por `0537b69` (2026-08-28, nueve entradas de
  roadmap de comunicación de campo). Que el defecto es heredado se verificó **antes** de tocar
  nada: `git diff` daba `sdd/roadmap.md` sin modificar, así que el rojo no lo traía el trabajo
  de este change. Reescrita a «sus tres tipos siguen sin implementar», que dice lo mismo sin
  vocabulario de censo. **Es una edición fuera del alcance de este change** —el roadmap de
  otra entrada— y se hace porque el guardián es una puerta de merge y dejarla roja bloquearía
  esta feature por un defecto ajeno; queda anotado aquí para que se vea en el diff.
  El censo enmendado en 8.2 **no** añadió ningún infractor nuevo: comprobado antes y después.
- [x] 8.4 Extender `backend/tests/messaging/test_free_text_sink_contract.py` con el caso del
  portal: el contenido del mensaje del huésped llega a `messages.content` y **no** a
  `timeline_events` ni a `audit_logs.changes`. [R4.4]
- [x] 8.5 Regenerar y commitear `backend/openapi.json` (`make openapi`) y
  `frontend/lib/api/generated/openapi.d.ts` — las dos mitades del puente. En worktree enlazado,
  el `npm run api:generate` va por el rodeo documentado en `sdd/project.md` («Worktree
  bootstrap»): `mkdir -p /backend`, `docker compose cp backend/openapi.json`, symlink
  `/frontend → /app`, y entonces el comando. [R5.10]

## 9. Front — datos: DTOs, fuente y hook con polling <!-- core-reviewers: panel de 7 (architect/security/qa + cicd/documentation/i18n/tenancy) 2026-08-30: CLEAN tras 2 rondas de arreglos; gate ejecutable NO ejecutado (ver BLOCKED.md) -->

- [x] 9.1 DTOs en `frontend/features/guest-portal/data/dto.ts` derivados **exclusivamente** de
  los tipos generados en `frontend/lib/api/generated/openapi.d.ts`, para el hilo y para el
  mensaje. [R5.9, R5.10]
- [x] 9.2 Dos métodos nuevos en `frontend/features/guest-portal/data/guest-portal-source.ts` y su
  implementación HTTP en `.../data/http/http-guest-portal-source.ts`, por la misma instancia de
  `createApiClient({ baseUrl: "" })` de `data/index.ts` —construida **sin `getHeaders`**, de modo
  que estructuralmente no pueda emitir `Authorization: Bearer`—. Tests en
  `http-guest-portal-source.test.ts`: las dos llamadas apuntan a las rutas correctas, y un test
  que fije que el cliente sigue sin `getHeaders`. [R5.9]
- [x] 9.3 Clave `guestKeys.conversation(token)` en
  `frontend/features/guest-portal/hooks/query-keys.ts`, con su test en `query-keys.test.ts`.
  [R5.3]
- [x] 9.4 `frontend/features/guest-portal/hooks/use-conversation.ts`: `useQuery` con
  `refetchInterval: PORTAL_THREAD_POLL_MS` (constante de módulo, `15_000`, con el comentario que
  justifica la aritmética contra el presupuesto de 60 peticiones/minuto compartido por las seis
  rutas) y `refetchIntervalInBackground: false` **explícito**, más el `useMutation` de envío con
  `retry: false` e invalidación de la clave del hilo al terminar. Ni WebSocket ni SSE. Tests:
  el hilo se re-consulta con la pestaña visible y **deja** de hacerlo al ocultarla (test que
  oculta la pestaña, para que la garantía no dependa de un valor por defecto); un `429` no se
  reintenta. [R5.3, R5.8]

## 10. Front — UI e i18n <!-- core-reviewers: panel de 7 (architect/security/qa + cicd/documentation/i18n/tenancy) 2026-08-30: CLEAN tras 2 rondas de arreglos; gate ejecutable NO ejecutado (ver BLOCKED.md) -->

- [x] 10.1 `ConversationSection` en
  `frontend/features/guest-portal/components/guest-portal-view.tsx`, cuarta hija de
  `GuestPortalView`, mobile-first, con su propio `useQuery`/`useMutation` y sus propios estados
  para que su fallo no derribe estancia, check-in ni incidencia. Bajo el gate de `info`: con
  `useStayInfo` sin autorizar no se renderiza. Tests en `guest-portal-view.test.tsx` para las
  dos cosas. [R5.1, R5.2]
- [x] 10.2 Envío: botón deshabilitado mientras `isPending`, región `role="alert"
  aria-live="polite"` como ya hacen `CheckinSection` e `IncidentSection`, y el hilo actualizado
  al terminar. Tests de los tres. [R5.4]
- [x] 10.3 Presentación del hilo: cada mensaje como **«tú»** o **«el alojamiento»** según el
  `sender` agrupado que publica la API, sin derivar en el cliente ninguna distinción IA/persona;
  y la copia localizada de espera cuando el estado es `AWAITING_HUMAN`, sin razón de escalación
  alguna. Tests de ambos. [R5.5, R5.6]
- [x] 10.4 Estados accesibles y localizados de carga, vacío, error de autorización, `422`, `429`
  y error genérico (`5xx`/red) para las dos operaciones, reutilizando `guest:errors.*` donde ya
  existan; el `429` no se reintenta automáticamente ni se presenta como prueba de que el mensaje
  no se envió. Tests por estado. [R5.8]
- [x] 10.5 Claves `guest:conversation.*` en `frontend/locales/es/guest.json` **y**
  `frontend/locales/en/guest.json` (título, vacío, cargando, campo, enviar, enviando, «tú», «el
  alojamiento», copia de espera y los errores de 10.4). Ninguna cadena hardcodeada. El test
  `frontend/features/guest-portal/guest-i18n.test.ts` cubre la paridad ES/EN. [R5.7]
- [x] 10.6 Clave `conversations:channel.PORTAL` en `frontend/locales/es/conversations.json` y
  `frontend/locales/en/conversations.json`: sin ella la bandeja del manager
  (`conversations-view.tsx:102`, `conversation-thread-view.tsx:126`) pinta la clave cruda para
  todo hilo de portal. Test de paridad. [R3.1, R3.6]
- [x] 10.7 Test de que el token no se renderiza en texto visible, metadata, título ni mensaje de
  error de la sección nueva. [R5.9]

## 11. Documentación

- [x] 11.1 `docs/guest-portal.md`: la sección de conversación del portal —qué ve el huésped,
  polling, estados, límites—. [R5.1]
- [x] 11.2 `docs/messaging-ai.md`: el canal `PORTAL`, su adapter, que el hilo lo abre el primer
  mensaje del huésped y que el manager contesta desde la bandeja con el flujo que ya existe.
  [R3.1, R3.6]
- [x] 11.3 Actualizar el comentario de `GUEST_PORTAL_RATE_LIMIT_PER_MINUTE` en `.env.example`
  (línea 207): el presupuesto de 60/min pasa a repartirse entre **seis** rutas, y el polling lo
  convierte en un número con consecuencia visible. Ninguna variable de entorno nueva. [R4.3]

## 12. Verification

- [x] 12.1 Suite backend completa en verde: `docker compose exec backend uv run pytest`. Entran
  las suites de `guests`, `messaging` **y `maintenance`** — la firma de `IncidentReportingPort`
  cambia y ese módulo no es del change. Y también `cli` y `audit`: `seed_demo.py` llama al
  pipeline y el actor nuevo escribe en `audit_logs`. Correr sólo los directorios que tocas es
  cómo se coló un llamante roto en la sección 2.

  **Aviso de entorno, medido el 2026-08-29**: con varios stacks de compose vivos en la máquina,
  `pytest` sin ruta muere con **exit 137 (OOM)** antes de reportar nada. No es una regresión ni
  un fallo de la suite. Las pasadas por directorio sí caben. Si la completa hace falta para el
  gate, hay que correrla con los demás stacks parados (`make down` en los otros worktrees, que
  son de otras sesiones — **preguntar antes**) o aceptar la evidencia por subconjuntos diciendo
  cuáles se corrieron. Hay además un `401 INVALID_TOKEN` en
  `test_api_conversations.py::test_the_pipeline_owned_fields_are_not_inputs[intent]` visto **una
  vez** bajo carga y no reproducido en 5 pasadas; QA lo trazó a `get_active_by_id` devolviendo
  `None`, sin relación con este change.

  **Medido el 2026-08-30: la suite COMPLETA, sin ruta, en verde — 9226 passed, 41 skipped, en
  9m04s, exit 0.** No hizo falta parar el stack de nadie: había tres stacks vivos (uno de otra
  sesión, `tech-app`) y aun así no hubo OOM, así que el aviso de arriba describe una condición
  posible, no una que se diera hoy. No se aceptó evidencia por subconjuntos: se corrió entera.
  Antes de ella, y por si sirve para acotar un fallo futuro, se midieron aparte
  `tests/guests tests/messaging` = 1005, `tests/maintenance` = 763 y `tests/cli tests/audit` =
  460. El `401 INVALID_TOKEN` intermitente que menciona el párrafo anterior **no** reapareció.
- [x] 12.2 Migración en limpio: `docker compose exec backend uv run alembic downgrade base &&
  docker compose exec backend uv run alembic upgrade head`, que es lo que corre CI.
- [x] 12.3 Contrato sin deriva: `make openapi` no deja diff, y `npm run api:check` en el
  contenedor de frontend tampoco (rodeo de worktree de `sdd/project.md` si aplica).
- [x] 12.4 Suite frontend en verde: `cd frontend && npm test` —comparando contra la cifra de
  partida medida en este árbol, no contra un número recordado— con los `docker compose cp` que
  `sdd/project.md` enumera para los dos ficheros que leen por encima de `/app`.

  **Medido: 168 ficheros, 1685 tests, todo en verde**, con los `docker compose cp` puestos.
  Y una honestidad sobre la comparación que esta tarea pide: **la cifra de partida no se midió
  antes de empezar a editar**, así que no hay un «antes» medido en este árbol contra el que
  restar — decirlo es más útil que fabricarlo. Lo que sí está contado contra el árbol:
  **3 ficheros de test nuevos con 12 tests** (`hooks/use-conversation.test.tsx`,
  `features/conversations/conversations-i18n.test.ts`,
  `data/index.test.ts`), medidos corriéndolos aislados, lo que deja 165 ficheros preexistentes;
  el resto del delta son tests añadidos a ficheros que ya existían
  (`guest-portal-view.test.tsx`, `http-guest-portal-source.test.ts`, `query-keys.test.ts`).
  Ningún fichero preexistente quedó en rojo en ninguna pasada.
- [x] 12.5 Typecheck del frontend: `npm run typecheck` (o `tsc --noEmit`) en verde.
- [x] 12.6 Comprobación manual del flujo extremo a extremo: abrir `/guest/[token]`, escribir un
  mensaje, ver la respuesta automática aparecer en el hilo, forzar una escalación y comprobar la
  copia de espera, y verificar que el hilo llega a la bandeja del manager con el canal traducido y
  que su respuesta se lee desde el portal.

  **Hecha el 2026-08-30 en este worktree**, en Chromium real contra el stack levantado con
  `make up PORT_OFFSET=41`, sobre datos de `bootstrap` + `seed-demo` y un token acuñado por la
  ruta de operador. La premisa que decía que esto no se podía hacer aquí —«con `PORT_OFFSET` la
  página no hidrata»— **resultó falsa al medirla**: `sdd/project.md` §«Worktree bootstrap» queda
  corregido en este mismo commit, con la constancia de que `next.config.ts` sigue **sin**
  `allowedDevOrigins` y aun así hidrata, así que la causa que aquella nota apuntaba era la
  equivocada.

  Las seis cláusulas, una por una:
  1. `/guest/[token]` carga las cuatro secciones en una página real —«Tu estancia», «Check-in»,
     «Comunicar una incidencia» y «Conversación»— y el hilo vacío dice «Todavía no has escrito
     nada», no `404` (R2.5, R5.1, R5.2).
  2. Mensaje enviado desde el textarea; aparece etiquetado «Tú» y el `aria-live` anuncia «Mensaje
     enviado.» (R5.4).
  3. La respuesta automática aparece en el mismo sondeo, etiquetada «El alojamiento» y **sin
     ninguna marca de IA** (R5.5).
  4. Escalación forzada con una queja: el hilo pasa a mostrar «Te responderá una persona.» y
     **no** explica el motivo (R2.3, R5.6).
  5. En `/conversations` la fila sale como **«Portal del huésped»** —traducida, el literal
     `PORTAL` no aparece en la página— con «Escalada / Esperando a una persona» (R3.6, D11).
  6. Respuesta del manager desde `/conversations/[id]`, leída de vuelta en el portal como «El
     alojamiento», **indistinguible de la de la IA**. Ésta es la comprobación más fuerte de R5.5:
     en la misma pantalla del manager ese mismo hilo muestra «IA» y el intent
     `CHECKIN_INSTRUCTIONS`, y en el portal no se ve ninguna de las dos cosas.

  **Observación de UX, no hallazgo**: tras contestar la persona, el portal sigue diciendo «Te
  responderá una persona.». Es conforme al spec —`is_handed_over()` cubre `PENDING_HUMAN` y
  `HUMAN_HANDLING` por D9, el estado real era `HUMAN_HANDLING`, y R2.3 sólo define dos valores—,
  pero quien lea la copia después de que le hayan contestado puede leerla como que aún no lo han
  hecho. Si se quiere afinar, es una copia más y un tercer valor en el vocabulario de R2.3.
