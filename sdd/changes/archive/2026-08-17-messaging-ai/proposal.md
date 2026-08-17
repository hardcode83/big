# Proposal: messaging-ai

## Why

El PRD §13 define la atención de primer nivel al huésped con IA y escalado humano
como una de las capacidades nucleares del MVP, y `product.md` la coloca la quinta en
la prioridad de entrega (PRD §30). Hoy no existe: `domain-foundation-ops` dejó
`Conversation` y `Message` como dataclasses planas con sus modelos SQLAlchemy, sin
`application/`, sin `api/`, sin repositorios y **sin ningún escritor** — su propia spec
lo dice y nombra a este change como el que cierra el hueco
(`specs/domain-foundation-ops.md`, líneas 12, 14 y 29).

Que se construya ahora, y no después del canal real, es una decisión ya tomada y
argumentada en `sdd/roadmap/messaging-ai.md`: su `needs:` apunta a `pms-beds24-adapter`
y **no** a `beds24-messaging-adapter`, porque aquél está aplazado a la ventana de corte
de los dos anuncios de Madrid, sin fecha, y colgar de un evento operativo externo una
capability nuclear la dejaría bloqueada indefinidamente. Lo que la mensajería real
aportaba al diseño eran sus **límites**, y esos ya están medidos y escritos
([ADR 0006](../../../docs/adr/0006-pms-channel-manager-provider.md), `docs/beds24-spike.md`).

Riesgo residual, asumido y nombrado por esa misma nota: se construye contra adapters
mock, así que un límite **no documentado** del canal real aparecería al llegar
`beds24-messaging-adapter`. El riesgo original —descubrir tarde los límites conocidos—
sí queda cubierto.

## What changes

El módulo `backend/app/messaging/` gana sus capas `application/` y `api/`: repositorios
de `Conversation` y `Message`, un puerto `AIAdapter` propio con su `MockAIAdapter`, el
pipeline de procesamiento del mensaje entrante del PRD §13 (detección de idioma →
clasificación de intent → umbral de confianza → escalación → generación y envío de
respuesta → `TimelineEvent` → derivación a incidencia), las seis condiciones de
escalación inmediata, un puerto de canal de salida con sus adapters mock, y los siete
endpoints de bandeja del PRD §16. Los mensajes entran por el panel o por API — no hay
ingesta automática desde OTA, y `PMSMessagingPort` sigue siendo el puerto sin métodos
que `pms-provider-resolution` fijó a propósito.

Tres columnas que hasta hoy no tenían escritor —`messages.content`, `messages.intent`
y `messages.metadata`— lo ganan aquí, así que este change hereda por primera vez el
contrato de la regla 11 de `steering/security.md` para ellas.

## Requirements

### R1 — Persistencia de conversaciones y mensajes

**Como** manager, **quiero** que las conversaciones con huéspedes y sus mensajes se
persistan de forma consultable y acotada a mi tenant, **para que** el historial de una
estancia sea auditable y no se mezcle nunca con el de otro tenant.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar en `messaging` puertos de repositorio propios para
   `Conversation` y `Message`, con **solo los métodos que este change consume**, y NEVER
   SHALL declarar métodos especulativos — la disciplina que `domain-foundation-ops`
   registra como apuesta ganada en el puerto de un método de `Incident`.
2. WHEN se consulta cualquier `Message`, THE SYSTEM SHALL partir del `JOIN` con
   `conversations` para acotar por `tenant_id`, y NEVER SHALL consultar `messages`
   directamente. La tabla no tiene columna `tenant_id`, así que `tenant_scoped_classes()`
   no la selecciona y el filtro global de `with_loader_criteria` **no la cubre**: el
   `JOIN` no es defensa en profundidad, es el único mecanismo de aislamiento
   (`specs/domain-foundation-ops.md`, obligación heredada explícitamente por este change).
3. THE SYSTEM SHALL tener test de aislamiento propio para `messages` que demuestre que
   un tenant no lee ni escribe los mensajes de otro, en **cada** vía de acceso: listado,
   detalle, alta y envío.
4. WHEN se añade un mensaje a una conversación, THE SYSTEM SHALL actualizar
   `Conversation.last_message_at` en la misma transacción, de modo que la bandeja pueda
   ordenarse sin recorrer `messages`.
5. IF la conversación referida no existe o pertenece a otro tenant, THEN THE SYSTEM
   SHALL responder con el mismo error de "no encontrada" en ambos casos, y NEVER SHALL
   permitir distinguir una de otra.

### R2 — Puerto `AIAdapter` y su adaptador mock

**Como** equipo, **quiero** un puerto de IA propio de `messaging` con un adaptador
determinista, **para que** el pipeline sea verificable end-to-end sin credenciales de
ningún proveedor de modelos.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar el puerto `AIAdapter` en `messaging` con **exactamente dos
   métodos** —`classify_message` y `generate_response`—, y NEVER SHALL declarar
   `classify_incident`, `validate_cleaning_photo`, `summarize_incident` ni
   `draft_review_response` del PRD §13, que pertenecen a otras capabilities o no existen
   todavía.
2. THE SYSTEM SHALL dejar intacto el puerto `IncidentClassifier` de `maintenance`, y
   NEVER SHALL colgar la clasificación de incidencias de este adaptador — es la
   prohibición literal de `specs/maintenance.md` R2, en la dirección contraria.
3. THE SYSTEM SHALL declarar los catorce intents del PRD §13 como enum cerrado
   (`CHECKIN_INSTRUCTIONS`…`UNKNOWN`), con esos nombres exactos.
4. THE SYSTEM SHALL exigir que toda clasificación y toda respuesta generada declaren
   **en el valor que devuelven** el vocabulario cerrado del que salen, y SHALL rechazar
   en construcción una confianza fuera de `0..1` o un contenido fuera de ese vocabulario
   — el mismo contrato que `IncidentClassification.vocabulary` en `maintenance`, por la
   misma razón: la comprobación vive en el tipo, no en un barrido de directorio que un
   adaptador puede esquivar mudándose.
5. WHEN `MockAIAdapter` clasifica un mensaje cuyo intent reconoce, THE SYSTEM SHALL
   devolver `confidence = 0.80` (PRD §13); IF no lo reconoce, THEN SHALL devolver
   `UNKNOWN` con una confianza por debajo del umbral por defecto (`0.75`), de modo que
   el camino de escalación quede ejercitado por el mock.
6. THE SYSTEM SHALL generar respuestas a partir de plantillas versionadas por intent y
   por idioma (`es`/`en`), y NEVER SHALL interpolar en ellas texto recibido del huésped.
   Esto es lo que hace verificable la regla 10 de `steering/security.md` y el principio 6
   de `product.md`: un catálogo cerrado no puede prometer un reembolso, admitir
   responsabilidad, dar asesoría legal, inventar un código de acceso ni afirmar que un
   técnico va de camino.
7. WHEN el intent es `REFUND_OR_COMPENSATION`, `EMERGENCY` o `UNKNOWN`, THE SYSTEM SHALL
   escalar sin generar respuesta alguna (R5), y NEVER SHALL invocar `generate_response`
   para ellos.
8. `EXTERNAL_DEPENDENCY`: el adaptador real contra un proveedor de modelos queda fuera;
   el mock es el único implementador que entrega este change.

### R3 — Censo de sumideros de texto en claro para `messages`

**Como** responsable de seguridad, **quiero** que las tres columnas libres de `messages`
entren en el censo de la regla 11 con su contrato declarado, **para que** ningún change
posterior las lea creyéndolas seguras.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar en `steering/security.md` —el único sitio donde vive ese
   contrato— las columnas `messages.content`, `messages.intent` y `messages.metadata`,
   con este change como primer escritor vivo. Hoy no están en el censo de trece porque
   no tenían escritor, exactamente como `incidents.title`/`description` antes de
   `guest-portal-api`.
2. WHERE el mensaje lo escribe el huésped (`sender_type = GUEST`), `messages.content`
   SHALL ir bajo **excepción de prosa de tercero**: el valor no es nuestro y ningún
   código nuestro renderiza ahí un valor de la regla 3. Se acota con tipos y longitud
   máxima, no pretendiendo que la columna sea estructurada.
3. WHERE el mensaje lo escribe el sistema (`ai_generated = true`), `messages.content`
   SHALL ser **forma cerrada**: una plantilla del catálogo de R2.6, sin interpolación de
   texto recibido. Un escritor nuestro no cae bajo la excepción anterior — es la
   distinción que `maintenance` tuvo que hacer para `incidents.ai_summary`.
4. `messages.intent` SHALL ser **forma cerrada**: un miembro del enum de R2.3, y lo que
   no encaje SHALL degradar a `UNKNOWN`, nunca almacenarse tal cual. La columna es un
   `VARCHAR(100)` que *parece* un enum y no lo es — el mismo aspecto que hizo que
   `webhook_events.event_type` se olvidara en el censo.
5. `messages.metadata` SHALL ser **estructurada**, con un conjunto cerrado de claves
   declarado, y NEVER SHALL contener texto del huésped ni un valor de la regla 3.
6. THE SYSTEM SHALL impedir la propagación: el `TimelineEvent` de un mensaje SHALL
   llevar título constante e identificadores en `metadata`, y NEVER SHALL copiar el
   contenido del mensaje a `timeline_events` ni a `audit_logs.changes`.
7. THE SYSTEM SHALL tener test que demuestre cada una de las cuatro formas anteriores.

### R4 — Pipeline de procesamiento del mensaje entrante

**Como** propietaria, **quiero** que un mensaje de huésped se clasifique y se conteste
solo cuando el sistema esté seguro, **para que** el soporte de primer nivel funcione sin
que la IA hable por encima de sus posibilidades.

Criterios de aceptación:

1. WHEN se registra un mensaje con `sender_type = GUEST`, THE SYSTEM SHALL, en este
   orden: detectar su idioma, clasificar el intent con `AIAdapter`, persistir el mensaje
   con ambos y emitir `TimelineEvent(GUEST_MESSAGE_RECEIVED)` — el tipo ya existe en
   `TimelineEventType`, sin escritor hasta hoy. Los cuatro pasos ocurren dentro de la
   única transacción de R4.7, así que desde fuera no hay estado intermedio observable.

   *(Enmendado en la review de 2026-08-16. El texto decía «persistir el mensaje, detectar
   su idioma, clasificar», que es el orden que se escribió antes de implementar; `Message`
   es `frozen` y necesita `intent` e idioma en construcción, así que clasificar después de
   persistir exigiría una segunda escritura sobre la misma fila. Se corrige el criterio en
   vez de dejar la desviación implícita hasta el archivado.)*
2. IF la confianza de la clasificación es **estrictamente menor** que
   `TenantConfig.ai_confidence_threshold`, THEN THE SYSTEM SHALL escalar (R5) y NEVER
   SHALL generar respuesta. IF es **mayor o igual**, THEN SHALL continuar. La
   comparación se fija aquí con el mismo criterio que `maintenance` R2, para que las dos
   capabilities no diverjan en el borde exacto del umbral.
3. IF `Conversation.ai_enabled` es `false`, THEN THE SYSTEM SHALL clasificar y registrar
   el mensaje pero NEVER SHALL generar ni enviar respuesta automática.
4. WHEN se envía una respuesta automática, THE SYSTEM SHALL persistirla como `Message`
   con `sender_type = AI`, `ai_generated = true`, su `confidence_score` y su `intent`, y
   SHALL emitir `TimelineEvent(AI_RESPONSE_SENT)`.
5. WHEN un usuario autenticado contesta manualmente, THE SYSTEM SHALL persistir el
   mensaje con `sender_type` según su rol y `sender_user_id`, y SHALL emitir
   `TimelineEvent(HUMAN_RESPONSE_SENT)`.
6. WHEN el intent clasificado es `MAINTENANCE_ISSUE` o `ACCESS_PROBLEM`, THE SYSTEM
   SHALL crear un `Incident` a través del puerto de escritura que `maintenance` ya
   expone, y NEVER SHALL clasificarlo en la misma petición — la clasificación de
   incidencias es el job de Celery que `maintenance` decidió en su D2.
7. THE SYSTEM SHALL ejecutar todo el procesamiento de un mensaje entrante en una sola
   transacción, de modo que un fallo no deje el mensaje persistido sin evento de timeline
   ni la conversación escalada sin notificación.
8. THE SYSTEM SHALL detectar el idioma entre `es` y `en` y SHALL responder en el idioma
   detectado; IF no puede decidirlo, THEN SHALL usar `Conversation.language`.

### R5 — Escalación a humano

**Como** manager, **quiero** que las situaciones que la IA no debe manejar lleguen a una
persona de inmediato y de forma visible, **para que** ninguna se quede esperando en una
bandeja que nadie mira.

Criterios de aceptación:

1. THE SYSTEM SHALL escalar inmediatamente en las seis condiciones del PRD §13, cada una
   con test propio: intent `EMERGENCY`; intent `ACCESS_PROBLEM` con menos de 2 h para el
   check-in de la reserva asociada; intent `REFUND_OR_COMPENSATION`; más de 2 mensajes
   del huésped con el mismo intent sin resolución; confianza por debajo del umbral; y
   presencia de una palabra clave de emergencia.
2. WHEN se escala, THE SYSTEM SHALL fijar `Conversation.status = ESCALATED` y
   `escalation_status = PENDING_HUMAN`, emitir `TimelineEvent(AI_ESCALATED_TO_HUMAN)` y
   registrar una notificación de tipo `GUEST_ESCALATION` — el miembro ya existe en
   `NotificationType`, sin escritor hasta hoy.
3. THE SYSTEM SHALL declarar las transiciones válidas de `escalation_status`
   (`NONE → PENDING_HUMAN → HUMAN_HANDLING → RESOLVED`) en la propia entidad
   `Conversation`, comprobarlas **antes** de escribir ningún campo, y rechazar las que no
   lo son con un error de dominio nombrado — el patrón que `AccessRecord` e `Incident` ya
   siguen.
4. IF la conversación ya está escalada, THEN THE SYSTEM SHALL registrar el mensaje
   entrante sin volver a notificar, y NEVER SHALL emitir una segunda notificación de
   escalación por la misma conversación mientras siga `PENDING_HUMAN`.
5. `ASSUMPTION`: la "lista configurable de palabras clave de emergencia" del PRD §13 se
   entrega como constante versionada por idioma en el dominio, no como columna nueva de
   `TenantConfig`. Configurarla por tenant exigiría migración y UI de settings, que son
   de `hardening-release`; la constante es sustituible sin cambiar el pipeline.
6. IF la condición de check-in inminente necesita una reserva y la conversación no tiene
   `reservation_id`, THEN THE SYSTEM SHALL tratar la condición como no cumplida, y NEVER
   SHALL fallar el procesamiento del mensaje por ello.

### R6 — Canales de salida

**Como** equipo, **quiero** que el envío salga por un puerto con adapters mock
explícitos, **para que** el día que llegue el canal real solo haya que implementar el
puerto.

Criterios de aceptación:

1. THE SYSTEM SHALL declarar en `messaging` un puerto de canal de salida propio, y los
   casos de uso SHALL depender de él y nunca de un adapter concreto.
2. THE SYSTEM SHALL entregar los adapters mock del PRD §13 para los canales que este
   change soporta: `MANUAL` (panel), `WHATSAPP` (`MockWhatsAppAdapter`, a consola),
   `EMAIL` (el `ConsoleEmailAdapter` que `access-notifications` ya gobierna) y
   `PHONE_TRANSCRIPT` (entrada manual, sin salida).
3. IF el canal de la conversación es `AIRBNB_MSG` o `BOOKING_MSG`, THEN THE SYSTEM SHALL
   rechazar el envío con un error de dominio nombrado, y NEVER SHALL caer en silencio a
   consola: esos dos canales solo existen a través de `PMSMessagingPort` y llegan con
   `beds24-messaging-adapter`.
4. THE SYSTEM SHALL dejar `PMSMessagingPort` exactamente como está —un puerto sin
   métodos— y NEVER SHALL añadirle `get_messages` ni `send_message`: su forma se decide
   con el primer proveedor que la implemente, que es lo que
   `specs/pms-provider-resolution.md` fijó.
5. WHEN el envío por un canal falla, THE SYSTEM SHALL registrar el fallo en forma
   estructurada (código y campo, nunca el cuerpo) y SHALL dejar la conversación en un
   estado del que un humano pueda recuperarla, y NEVER SHALL perder el mensaje en
   silencio.

### R7 — API de bandeja de conversaciones

**Como** manager, **quiero** los endpoints de conversaciones del PRD §16, **para que**
la bandeja del frontend (`field-apps`) tenga contra qué construirse.

Criterios de aceptación:

1. THE SYSTEM SHALL exponer los siete endpoints del PRD §16 con esas rutas exactas:
   `GET`/`POST /api/v1/conversations`, `GET /api/v1/conversations/{id}`,
   `GET`/`POST /api/v1/conversations/{id}/messages`,
   `POST /api/v1/conversations/{id}/escalate` y
   `POST /api/v1/conversations/{id}/resolve`.
2. THE SYSTEM SHALL declarar el permiso RBAC de cada endpoint en el backend (regla 2 de
   `steering/security.md`), con los roles del PRD §6.
3. WHEN se listan conversaciones, THE SYSTEM SHALL permitir filtrar por `status`,
   `escalation_status` y `property_id`, y SHALL paginar, ordenando por
   `last_message_at` descendente.
4. WHEN se listan los mensajes de una conversación, THE SYSTEM SHALL devolverlos en
   orden cronológico ascendente y SHALL paginarlos.
5. THE SYSTEM SHALL regenerar `backend/openapi.json` con `make openapi` y el artefacto
   derivado del frontend (`frontend/lib/api/generated/openapi.d.ts`) en el mismo PR — las
   dos mitades del puente que exige `steering/documentation.md`.
6. THE SYSTEM SHALL rechazar un cuerpo de mensaje que exceda la longitud máxima
   declarada, antes de persistirlo.

## Out of scope

- **Ingesta automática desde OTA** (Airbnb/Booking vía el PMS) — es
  `beds24-messaging-adapter`, aplazada a la ventana de corte. Aquí los mensajes entran
  por panel o API.
- **Adaptador de IA real** contra un proveedor de modelos — `MockAIAdapter` es el único
  implementador. El puerto queda listo para el real.
- **Los otros cuatro métodos del `AIAdapter` del PRD §13**: `classify_incident` ya es de
  `maintenance` con puerto propio; `validate_cleaning_photo` iría a `cleaning`;
  `summarize_incident` y `draft_review_response` no tienen consumidor todavía
  (`revenue` trae reviews).
- **Frontend de la bandeja** (`/conversations`, PRD §26.21 y §24) — es `field-apps`, que
  ya declara `messaging-ai` en su `needs:`. Este change es backend puro.
- **WhatsApp real y SMTP real** — `hardening-release`.
- **Adjuntos en mensajes** (el límite de 2 MB de Beds24, Booking.com sin enlaces ni PDF)
  — sin canal real no hay adjunto que transportar; llega con `beds24-messaging-adapter`.
- **SLA de respuesta humana tras una escalación** — la maquinaria de SLA es de
  `celery-jobs`; aquí solo se emite la notificación `GUEST_ESCALATION`.
- **Palabras clave de emergencia configurables por tenant** — ver `ASSUMPTION` en R5.5;
  la UI de settings es de `hardening-release`.

## Affected specs

- `sdd/specs/messaging-ai.md` — *(no existe aún — se creará al archivar)*.
- `sdd/specs/domain-foundation-ops.md` — `messaging` gana `application/` y `api/`,
  `Conversation` gana métodos de mutación, y `messages` deja de ser la tabla sin escritor
  con la obligación de aislamiento pendiente.
- `sdd/specs/api-contract.md` — los siete endpoints nuevos y la regeneración del
  contrato en sus dos mitades.
- `sdd/specs/maintenance.md` — nueva vía de alta de incidencias (desde una conversación),
  que hereda el contrato de `incidents.title`/`description`.
- `sdd/specs/access-notifications.md` — `NotificationType.GUEST_ESCALATION` gana su
  primer escritor.
- `sdd/specs/timeline-state-machine.md` — los cuatro eventos de mensajería
  (`GUEST_MESSAGE_RECEIVED`, `AI_RESPONSE_SENT`, `AI_ESCALATED_TO_HUMAN`,
  `HUMAN_RESPONSE_SENT`) ganan escritor.
- `sdd/steering/security.md` — **no es una spec, pero se modifica**: el censo de la regla
  11 crece con `messages.content`, `messages.intent` y `messages.metadata`, y ése es el
  único sitio donde vive ese contrato.
