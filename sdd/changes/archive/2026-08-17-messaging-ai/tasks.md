# Tasks: messaging-ai

Backend puro. El módulo `backend/app/messaging/` solo tiene hoy `domain/entities.py`,
`domain/enums.py` e `infrastructure/models.py` (lo que dejó `domain-foundation-ops`): **nada
de este change está preexistente**, así que ninguna tarea nace marcada.

Orden pensado para que la suite quede verde al cerrar cada sección: el dominio puro primero
(secciones 1-3, sin infra que montar y con TDD según `steering/testing.md`), después puertos
y adaptadores, después los casos de uso, y la API al final — el router no se registra en
`main.py` hasta que hay algo detrás que responda.

## 1. Vocabulario de dominio: enums, excepciones y value objects <!-- panel: PASS 2026-08-16 -->

- [x] 1.1 `MessageIntent` con los catorce miembros literales del PRD §13 y `EscalationReason`
      con los siete de D10 (las seis del PRD más `DELIVERY_FAILED`) — `app/messaging/domain/enums.py`,
      `backend/tests/messaging/test_enums.py`. Test que fija los catorce nombres exactos, para que
      un renombrado futuro rompa aquí y no en producción. [R2.3]
- [x] 1.2 Jerarquía plana de errores de dominio en `app/messaging/domain/exceptions.py`:
      `MessagingDomainError` y sus hijas `ConversationNotFoundError`,
      `InvalidConversationTransitionError`, `ConversationClosedError`,
      `PMSChannelUnavailableError`, `MessagingValidationError`. Sin lógica, solo tipos. [R1.5, R5.3, R6.3]
- [x] 1.3 `MessageClassification` y `GeneratedResponse` congelados en
      `app/messaging/domain/value_objects.py`, con el contrato **en `__post_init__`**:
      `intent` miembro del enum, `confidence` en `0..1`, `language` en `SUPPORTED_LANGUAGES`,
      `vocabulary` no vacío y `content` dentro de él. Tests en
      `backend/tests/messaging/test_value_objects.py` que construyen fuera de contrato y exigen
      el rechazo — el precedente es `IncidentClassification.vocabulary`. [R2.4]
- [x] 1.4 `ConversationContext` congelado con **solo identificadores y valores cerrados**
      (`conversation_id`, `property_id`, `reservation_id`, `channel`, `language`, `ai_enabled`,
      `guest_message_count`) — `domain/value_objects.py`. Test que afirma que no hay ningún campo
      de texto libre: el objeto viaja a un adaptador que mañana es un proveedor externo. [R2.1]
- [x] 1.5 `MessageMetadata` congelado con el conjunto cerrado de seis claves de D15 y `to_dict()`
      que emite solo las presentes — `domain/value_objects.py`. Test que demuestra que no admite
      claves arbitrarias ni texto del huésped. [R3.5]
- [x] 1.6 `ChannelErrorCode` (`INVALID_RECIPIENT`, `CHANNEL_INBOUND_ONLY`, `ADAPTER_UNAVAILABLE`)
      y `ChannelSendResult` — éxito o fallo **por valor**, nunca con el cuerpo dentro, patrón
      `NotificationResult` — en `domain/value_objects.py`, con test. [R6.5]

## 2. Entidades: transiciones e invariantes <!-- panel: PASS 2026-08-16 -->

- [x] 2.1 TDD: escribir primero los tests de las **dos tablas de transiciones** de D4
      (`escalate`, `take_over`, `resolve_escalation` sobre `escalation_status`; `escalate`,
      `resolve`, `reopen` sobre `status`), incluidas las inválidas, y luego implementarlas como
      dos `ClassVar` en `Conversation` — `app/messaging/domain/entities.py`,
      `backend/tests/messaging/test_entities.py`. Comprobación **antes** de escribir ningún campo,
      rechazo con `InvalidConversationTransitionError`. DoD §28.19 exige las inválidas. [R5.3]
- [x] 2.2 `Conversation.register_message(now)` actualiza `last_message_at` desde la entidad, no
      con un `setattr` del caso de uso — `domain/entities.py`, con test. [R1.4]
- [x] 2.3 `Conversation` rechaza en construcción una conversación sin `property_id` (D19), y la
      columna **sigue nullable**: ninguna migración en este change. Test que fija ambas mitades
      (rechazo en la entidad, `nullable=True` en el modelo). Sin `property_id` no hay ninguno de
      los cuatro `TimelineEvent` que este change declara obligatorios. [R4.1, R5.2]
- [x] 2.4 `Message.__post_init__` en `domain/entities.py`: `intent` que no sea miembro de
      `MessageIntent` **degrada a `UNKNOWN`** y nunca se almacena tal cual, y `content` por encima
      de `MAX_MESSAGE_CONTENT_LENGTH = 4000` se rechaza. La constante vive en `domain/` y es el
      único techo para un llamante sin HTTP delante. Tests de ambas. [R3.4, R7.6]

## 3. Servicios de dominio puros <!-- panel: PASS 2026-08-16 -->

- [x] 3.1 Catálogo de plantillas en `app/messaging/domain/templates.py`:
      `TEMPLATE_CATALOGUE_VERSION`, `RESPONSE_TEMPLATES` con **once** intents × `{es, en}` —
      `REFUND_OR_COMPENSATION`, `EMERGENCY` y `UNKNOWN` **no tienen plantilla** — y
      `RESPONSE_VOCABULARY`. Test que recorre el catálogo y **rechaza cualquier hueco de
      interpolación** (`{...}`, `%s`, prefijo `f`), calcado de
      `tests/maintenance/test_classifier_vocabulary_contract.py`, más un test que afirma la
      ausencia de esos tres intents. [R2.6, R2.7]
- [x] 3.2 `detect_language(content) -> str | None` en `app/messaging/domain/language.py`:
      marcadores cerrados por idioma sobre texto normalizado, `None` al empatar o sin señal. Se
      copian las líneas de normalización en vez de importar `maintenance/infrastructure/` (lo
      rechaza `tests/test_layering.py`), y consta por qué. Tests con mensajes de una línea en
      ambos idiomas y con el caso ambiguo. [R4.8]
- [x] 3.3 Política de escalación en `app/messaging/domain/escalation.py`: constante de palabras
      clave de emergencia versionada por idioma (`ASSUMPTION` de R5.5, no columna de
      `TenantConfig`) y `evaluate(...) -> EscalationReason | None`, pura y sin repositorios, con
      el **orden de D10 declarado y testeado**. Un test por cada una de las seis condiciones del
      PRD §13, más el del orden entre condiciones que casan a la vez. La comparación del umbral es
      **estrictamente menor**, el mismo borde exacto que `Incident.classify`
      (`app/maintenance/domain/entities.py:219`). [R5.1, R4.2]
- [x] 3.4 `hours_to_checkin` llega `None` cuando la conversación no tiene `reservation_id`, y la
      condición `IMMINENT_CHECKIN_ACCESS_PROBLEM` **no se cumple** sin fallar — test explícito en
      `backend/tests/messaging/test_escalation.py`. El instante del check-in sale de
      `effective_bounds(property, reservation)` (`app/properties/domain/clock_triggers.py:59`),
      nunca de una resta de fechas. [R5.6]
- [x] 3.5 `guest_escalation_notification(...)` en `app/messaging/domain/notifications.py`:
      constructor puro calcado de `maintenance/domain/notifications.py`, con
      `GUEST_ESCALATION` / `IN_APP` / `PENDING`, `related_type = "conversation"`, `subject` y
      `body` constantes más identificadores, y **sin `sla_deadline_at`** (D20). Test que fija la
      ausencia del plazo y su motivo. [R5.2]

## 4. Puertos <!-- panel: PASS 2026-08-16 -->

- [x] 4.1 `app/messaging/domain/repositories.py`: `ConversationRepository` (`add`, `get`, `save`,
      `list`) y `MessageRepository` (`add`, `list_for_conversation`,
      `count_unresolved_guest_messages_with_intent`) — **solo esos métodos**, más
      `ConversationFilters`, `ConversationPage`, `MessagePage`. Ni `delete`, ni `search`, ni
      `get(message_id)`. [R1.1]
- [x] 4.2 `app/messaging/domain/ports.py`: `AIAdapter` con **exactamente dos métodos**
      (`classify_message`, `generate_response`), `OutboundMessagePort` e `IncidentReportingPort`.
      Test que afirma que `AIAdapter` no declara `classify_incident`, `validate_cleaning_photo`,
      `summarize_incident` ni `draft_review_response`, y que `IncidentClassifier` de `maintenance`
      queda intacto. [R2.1, R2.2, R6.1]
- [x] 4.3 Test que demuestra que `PMSMessagingPort` sigue siendo el puerto **sin métodos** que
      `pms-provider-resolution` fijó — este change no le añade `get_messages` ni `send_message`. [R6.4]

## 5. Infraestructura: repositorios, IA y canales <!-- panel: PASS 2026-08-16 -->

- [x] 5.1 `SqlAlchemyConversationRepository` en `app/messaging/infrastructure/repositories.py`,
      con el orden de bandeja `last_message_at DESC NULLS LAST, id` y los filtros `status`,
      `escalation_status`, `property_id` — tests de integración contra Postgres en
      `backend/tests/messaging/test_repositories.py`. [R1.1, R7.3]
- [x] 5.2 `SqlAlchemyMessageRepository` en el mismo fichero, **sin ninguna sentencia que toque
      `messages` sola**: lecturas por `JOIN` con `conversations` filtrando `tenant_id`; la
      escritura resuelve primero el padre dentro del tenant, levanta `ConversationNotFoundError`
      si no resuelve e inserta contra **el id que resolvió**. Precedente literal:
      `SqlAlchemyCleaningPhotoRepository` (`app/cleaning/infrastructure/repositories.py:424-518`).
      `messages` no tiene `tenant_id`, así que el `JOIN` es el único mecanismo de aislamiento, no
      defensa en profundidad. [R1.2]
- [x] 5.3 Tests de aislamiento propios de `messages` en
      `backend/tests/messaging/test_tenant_isolation.py`, uno por **cada vía de acceso**: listado,
      detalle, alta y envío. Deben correr sobre sesión **sin marcar** — sobre una sesión marcada el
      filtro global taparía el fallo y el test no podría fallar nunca. [R1.3]
- [x] 5.4 «Conversación inexistente» y «conversación de otro tenant» producen **el mismo error**,
      sin rama que las distinga: es la misma consulta con cero filas. Test que compara las dos
      respuestas. [R1.5]
- [x] 5.5 `MockAIAdapter` en `app/messaging/infrastructure/ai.py`, calcado de
      `RuleBasedIncidentClassifier`: tabla de palabras clave por intent en `es`/`en`, orden de la
      tupla como desempate explícito, normalización sin acentos por palabras enteras, determinista
      y sin I/O. Reconocido → `Decimal("0.80")`; no reconocido → `UNKNOWN` con `Decimal("0.30")`,
      **por debajo del `0.75` por defecto**, de modo que el camino de escalación quede ejercitado
      por el mock. Marcar `EXTERNAL_DEPENDENCY`: el adaptador real queda fuera. Tests en
      `backend/tests/messaging/test_ai_adapter.py`. [R2.5, R2.8]
- [x] 5.6 Registro de canales de salida en `app/messaging/infrastructure/channels.py`:
      `MANUAL` → `PanelOutboundAdapter` (no-op, la fila **es** la entrega), `WHATSAPP` y `EMAIL`
      **delegando** en `MockWhatsAppAdapter` / `ConsoleEmailAdapter` de `notifications` — para
      heredar su disciplina de no loguear cuerpo ni destinatario —, `PHONE_TRANSCRIPT` →
      `InboundOnlyAdapter` que devuelve `CHANNEL_INBOUND_ONLY`. [R6.2]
- [x] 5.7 `AIRBNB_MSG` y `BOOKING_MSG` **ausentes del registro**, y el caso de uso levanta
      `PMSChannelUnavailableError`: no hay clave con la que caer a consola en silencio. Test que
      comprueba la ausencia en el registro *y* el error, porque un `NoOpAdapter` añadido más tarde
      pasaría el segundo pero no el primero. [R6.3]

## 6. Casos de uso <!-- panel: PASS 2026-08-16 -->

- [x] 6.1 `ReportIncidentFromConversationUseCase` en
      `app/maintenance/application/use_cases.py`, hermano de `ReportGuestIncidentUseCase`: crea el
      `Incident` en `OPEN` con `ai_classification` nulo, `IncidentSource.GUEST`, su `AuditLog` con
      **actor humano** y su `TimelineEvent(INCIDENT_CREATED)`. `title` sale de un catálogo cerrado
      de dos constantes por intent y `description` es el contenido del huésped **verbatim**
      (D13). Ni una línea de `IncidentClassifier`: la clasificación es el job de Celery de
      `maintenance` D2. Tests en `backend/tests/maintenance/`. [R4.6]
- [x] 6.2 `ProcessInboundGuestMessageUseCase` en `app/messaging/application/use_cases.py` con los
      diez pasos de D11 y **un solo `commit()` al final**: resolver conversación (rechazar
      `CLOSED`, reabrir `RESOLVED`), persistir el mensaje con idioma detectado,
      `register_message`, clasificar, `TimelineEvent(GUEST_MESSAGE_RECEIVED)`, evaluar escalación,
      rama de escalación **o** rama de respuesta, alta de incidencia, commit. Test que demuestra
      que un fallo a mitad no deja mensaje sin evento de timeline ni conversación escalada sin
      notificación. [R4.1, R4.7]
- [x] 6.3 Umbral y `ai_enabled` en el pipeline: confianza **estrictamente menor** que
      `TenantConfig.ai_confidence_threshold` → escala y **nunca** genera respuesta; mayor o igual
      → continúa. Con `ai_enabled = false` se ejecutan los pasos 1-6 y 9 pero nunca el 8 — y **la
      escalación sí ocurre**: apagar la IA apaga la respuesta automática, no el aviso de que hay
      una emergencia. Tests de los tres casos de borde del umbral. [R4.2, R4.3]
- [x] 6.4 Rama de respuesta automática: generar, persistir el `Message` con `sender_type = AI`,
      `ai_generated = true`, `confidence_score` e `intent`, enviar, y emitir
      `TimelineEvent(AI_RESPONSE_SENT)`. Test que afirma que **`generate_response` no se invoca**
      para `REFUND_OR_COMPENSATION`, `EMERGENCY` ni `UNKNOWN`. [R4.4, R2.7]
- [x] 6.5 Rama de escalación: `status = ESCALATED`, `escalation_status = PENDING_HUMAN`,
      `TimelineEvent(AI_ESCALATED_TO_HUMAN)` y `NotificationLog(GUEST_ESCALATION)` dirigida a los
      `PROPERTY_MANAGER` activos del tenant. Si no hay ninguno, `logger.warning` y **no** se falla
      el procesamiento. La no-repetición de R5.4 se apoya en la tabla de transiciones (`escalate`
      solo admite origen `NONE`), no en un `if` del caso de uso: test que envía un segundo mensaje
      sobre una conversación ya `PENDING_HUMAN` y exige **una sola** notificación. [R5.2, R5.4]
- [x] 6.6 Fallo de envío (R6.5): el `Message` de IA se persiste **antes** de enviar; al fallar, su
      `metadata` recibe `delivery_status = "FAILED"` y `delivery_error_code`, la conversación
      escala con `EscalationReason.DELIVERY_FAILED`, y **no** se emite `AI_RESPONSE_SENT` porque
      no se envió y `timeline_events` es append-only. Test que comprueba que el mensaje no se
      pierde y que el error registrado no contiene el cuerpo. [R6.5]
- [x] 6.7 `RecordHumanReplyUseCase`: `sender_type` **derivado del rol** del token (hoy una sola
      entrada, `PROPERTY_MANAGER → MANAGER`), `sender_user_id` persistido,
      `TimelineEvent(HUMAN_RESPONSE_SENT)`, y `take_over` si la conversación está en
      `PENDING_HUMAN` — contestar *es* tomar el mando (D4). [R4.5]
- [x] 6.8 Casos de uso de bandeja: `CreateConversation`, `ListConversations` (filtros + paginación
      + orden), `GetConversation`, `ListMessages` (cronológico ascendente + paginación),
      `EscalateConversation` y `ResolveConversation`, con sus tests contra fakes de los puertos. [R7.3, R7.4]

## 7. API <!-- panel: PASS 2026-08-16 -->

- [x] 7.1 `READ_CONVERSATIONS` y `MANAGE_CONVERSATIONS` en `app/auth/domain/policy.py`, con el
      reparto de D17: `PROPERTY_MANAGER` los dos, `TENANT_OWNER` solo la lectura, `CLEANER`,
      `TECHNICIAN` y `SUPER_ADMIN` ninguno. Test que fija el reparto. [R7.2]
- [x] 7.2 `app/messaging/api/schemas.py`: DTOs de las siete rutas. `sender_type` en el cuerpo de
      `POST /messages` es opcional con **un único valor admitido, `GUEST`**; cualquier otro
      (`AI`, `SYSTEM`, o un `MANAGER` explícito) es 422. `ai_generated`, `confidence_score`,
      `intent` y `metadata` **no son campos de entrada**. `max_length` del contenido en el esquema,
      además del techo de la entidad (2.4) — dos comprobaciones a propósito. [R7.6]
- [x] 7.3 `app/messaging/api/router.py`: las siete rutas exactas del PRD §16 bajo `/conversations`,
      tag `messaging`, con `require(...)` por ruta (lo recorre `tests/test_route_authorization.py`).
      Tests de las rutas en `backend/tests/messaging/test_api_conversations.py`. [R7.1]
- [x] 7.4 `app/messaging/api/errors.py`: mapeo al sobre del PRD §23 —
      `ConversationNotFoundError` → 404, `InvalidConversationTransitionError` y
      `ConversationClosedError` → 409, `PMSChannelUnavailableError` → 422,
      `MessagingValidationError` → 422 — con **tabla exhaustiva** sobre `domain/exceptions.py` y
      test que falla si aparece una excepción sin mapear (precedente `maintenance/api/errors.py`). [R7.1]
- [x] 7.5 `app/messaging/api/dependencies.py`: cableado de repositorios, `MockAIAdapter`, registro
      de canales y el `IncidentReportingPort` implementado por
      `ReportIncidentFromConversationUseCase`, al que se le inyecta un `CallerOwnedUnitOfWork`
      para que **el commit siga siendo uno solo**, el del pipeline. Test que lo demuestra. [R4.6, R4.7]
- [x] 7.6 `include_router` y `register_messaging_error_handlers` en `backend/app/main.py`; test de
      autorización por rol sobre las siete rutas en
      `backend/tests/messaging/test_api_authorization.py`. [R7.1, R7.2]

## 8. Censo de sumideros de texto en claro (regla 11)

- [x] 8.1 `sdd/steering/security.md` — el único sitio donde vive ese contrato — gana las **cinco
      filas** de D16 (con `messages.content` apareciendo tres veces porque tiene tres
      escritores) y la **excepción 4** nueva, la de prosa de tercero para
      `sender_type = GUEST`. La respuesta manual de una persona autenticada se acoge a la
      excepción 3 ya existente, citándola, no rederivándola. La review de 2026-08-16 añadió
      dos correcciones al censo: partir la fila `incidents.title`/`description`, porque este
      change es su segundo escritor y con él `title` es forma cerrada y no excepción 2, y
      listar `messaging-ai` en la fila de `notification_logs.subject`/`body`. El censo
      entregado queda en **16 columnas y 18 filas**. [R3.1, R3.2, R3.3]
- [x] 8.2 Tests de las cuatro formas en
      `backend/tests/messaging/test_free_text_sink_contract.py`, calcado del homónimo de
      `maintenance`: prosa de tercero acotada por tipo y longitud; forma cerrada de la respuesta de
      IA (el valor persistido es *literalmente* un miembro de `RESPONSE_VOCABULARY`); forma cerrada
      de `messages.intent` con la degradación a `UNKNOWN`; y `messages.metadata` estructurada con
      su conjunto cerrado de claves. [R3.7, R3.4, R3.5]
- [x] 8.3 Test de no-propagación: el `TimelineEvent` de un mensaje lleva título constante y solo
      identificadores y enums en `metadata`, y ni el contenido ni el intent llegan a
      `timeline_events` ni a `audit_logs.changes`. [R3.6]

## 9. Contrato y documentación

- [x] 9.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo. [R7.5]
- [x] 9.2 Regenerar `frontend/lib/api/generated/openapi.d.ts` y commitearlo en el mismo PR — son
      las dos mitades del mismo puente (`steering/documentation.md`). **Ojo**: `cd frontend &&
      npm run api:generate` no funciona en un worktree enlazado; usar la secuencia de cuatro
      comandos documentada en `sdd/project.md` (incluido el `mkdir -p /backend`). [R7.5]
- [x] 9.3 `docs/messaging-ai.md` nueva: cómo se opera la bandeja, qué escala y por qué, y el aviso
      de que una conversación creada a mano con `AIRBNB_MSG`/`BOOKING_MSG` queda muda **por
      diseño** (R6.3), para que no se lea como un fallo. Enlazar el diagrama
      `docs/diagrams/2026-08-16_autohost-flujo-mensaje-entrante.png`, ya generado. [R6.3]
- [x] 9.4 `README.md` de raíz: la capability nueva en las secciones que la nombran. Sin variables
      de entorno nuevas y sin migración, así que `.env.example` y `docs/diagrams/` (el ER) no se
      tocan.

## 10. Verification

- [x] 10.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest`
      (desde este worktree, con su propio stack levantado con `make up`).
- [x] 10.2 Los guardianes transversales pasan sin excepciones nuevas: `test_layering.py`
      (nada de `domain/` importando `infrastructure/` de otro dominio), `test_route_authorization.py`
      (las siete rutas declaran permiso), `test_openapi_contract.py`, `test_tenant_filter.py` y
      `test_log_redaction.py`.
- [x] 10.3 `test_migrations.py` confirma que **no hay migración**: ni columna, ni índice, ni tipo
      `ENUM` nuevo (D «Data & interfaces»).
- [x] 10.4 Contrato sin deriva: `openapi.json` corresponde al código y el `.d.ts` derivado
      corresponde al `openapi.json` (lo que comprueban los workflows `api-contract` y
      `frontend-api-contract`).
- [x] 10.5 Comprobación manual del flujo end-to-end contra el stack del worktree: crear una
      conversación, mandar un mensaje de huésped que el mock reconoce (respuesta automática +
      `AI_RESPONSE_SENT`), otro con palabra clave de emergencia (escalación + notificación
      `GUEST_ESCALATION` + sin respuesta), y uno con intent `MAINTENANCE_ISSUE` (incidencia `OPEN`
      sin clasificar). Sin puertos publicados no hay navegador: se hace desde dentro del
      contenedor o por la red de compose.
