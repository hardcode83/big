# Design: messaging-ai

## Context

`backend/app/messaging/` es hoy uno de los dos módulos que siguen siendo «solo estructura
de datos» en el sentido de `steering/backend-architecture.md`: tiene `domain/entities.py`
(dos `@dataclass` planas, `Conversation` y `Message`), `domain/enums.py` (cuatro enums) e
`infrastructure/models.py` (`ConversationModel`, `MessageModel`), y nada más — sin
`application/`, sin `api/`, sin puertos y **sin ningún escritor**
(`specs/domain-foundation-ops.md:12,14,29`).

Todo lo que este change necesita alrededor ya existe y está construido:
`TimelineEventFactory` (`app/timeline/domain/services.py`) con los cuatro
`TimelineEventType` de mensajería ya declarados y sin escritor;
`NotificationType.GUEST_ESCALATION` (`app/notifications/domain/enums.py`) igual;
`ConsoleEmailAdapter`/`MockWhatsAppAdapter` (`app/notifications/infrastructure/adapters.py`)
con la disciplina de no loguear contenido ni destinatario;
`TenantConfig.ai_confidence_threshold` con default `0.75`
(`app/tenants/domain/entities.py:106`); `UnitOfWork`/`CallerOwnedUnitOfWork`
(`app/core/unit_of_work.py`); y el catálogo RBAC de `app/auth/domain/policy.py`.

El módulo hermano que este design imita línea a línea es `maintenance`, que resolvió el
mismo problema hace un día: puerto de IA propio y pequeño (`IncidentClassifier`), un value
object que **hace cumplir el vocabulario cerrado en el tipo**
(`IncidentClassification.vocabulary`), adaptador determinista sin I/O
(`infrastructure/classifier.py`), tabla de transiciones dentro de la entidad
(`Incident._TRANSITIONS`), constructores puros de notificaciones
(`domain/notifications.py`), y `api/{router,dependencies,errors,schemas}.py` con `require(...)`
por ruta. Para el aislamiento de una tabla sin `tenant_id`, el precedente exacto es
`SqlAlchemyCleaningPhotoRepository` (`app/cleaning/infrastructure/repositories.py:409-518`):
ninguna sentencia toca la tabla hija sola.

El pipeline completo de D11 —la transacción única, las dos ramas excluyentes, las siete
razones de escalación y el alta ortogonal de incidencia— está dibujado en
[`docs/diagrams/2026-08-16_autohost-flujo-mensaje-entrante.png`](../../../docs/diagrams/2026-08-16_autohost-flujo-mensaje-entrante.png).
En PNG como los seis anteriores. Se generó primero en SVG, con el argumento de que es el
único diagrama que se lee **junto a este documento durante la revisión** y de que en SVG
diffea y se renderiza inline en GitHub; la review de 2026-08-16 lo revirtió, porque
`steering/documentation.md` fija el nombrado `{YYYY-MM-DD}_{slug}.png` y una excepción de un
solo fichero cuesta más de lo que ahorra. El diff de un SVG de Mermaid, además, no es
legible: son 300 KB de coordenadas generadas.

## Decisions

### D1 — Estructura del módulo: `messaging` gana sus cuatro capas

**Chosen:** `domain/` crece con `enums.py` (+`MessageIntent`, `EscalationReason`),
`repositories.py` (puertos de persistencia), `ports.py` (`AIAdapter`, `OutboundMessagePort`,
`IncidentReportingPort`), `value_objects.py`, `exceptions.py`, `templates.py`,
`language.py`, `escalation.py`, `notifications.py`; `application/use_cases.py`;
`infrastructure/{repositories,ai,channels}.py`; `api/{router,schemas,dependencies,errors}.py`.
Es la forma que `steering/backend-architecture.md` prescribe cuando un dominio deja de ser
estructura de datos, y la que `maintenance` estrenó el 2026-08-15.

Rejected: colgar los casos de uso de `notifications` o de `integrations` — mezclaría el
dominio de negocio con el borde de adaptadores.

### D2 — Puertos de repositorio: solo los métodos que este change consume (R1.1)

**Chosen:** dos puertos, un agregado raíz cada uno, y los métodos exactos que las rutas de
R7 y el pipeline de R4 gastan:

```python
class ConversationRepository(Protocol):
    async def add(self, tenant_id, conversation) -> None: ...
    async def get(self, tenant_id, conversation_id) -> Conversation | None: ...
    async def save(self, tenant_id, conversation) -> None: ...
    async def list(self, tenant_id, filters: ConversationFilters, *, page, per_page) -> ConversationPage: ...

class MessageRepository(Protocol):
    async def add(self, tenant_id, message) -> None: ...
    async def list_for_conversation(self, tenant_id, conversation_id, *, page, per_page) -> MessagePage: ...
    async def count_guest_messages(self, tenant_id, conversation_id) -> int: ...          # ← sección 6
    async def count_unresolved_guest_messages_with_intent(self, tenant_id, conversation_id, intent) -> int: ...
```

**`count_guest_messages` no estaba en esta lista** y se añadió al implementar la sección 6
(2026-08-16). Es la única forma de rellenar `ConversationContext.guest_message_count`, que
R2.1 y D6 declaran como parte de lo que se le cuenta a un `AIAdapter` — y que tiene que ser
cierto, porque el objeto viaja a algo que mañana es un proveedor externo. Las alternativas
eran pasar un número que no es la cuenta de mensajes del huésped, o quitar un campo que el
design fija. Lo que R1.1 prohíbe es un método **sin consumidor**, y éste trae el suyo en el
mismo commit; `tests/messaging/test_ports.py` lo comprueba recorriendo el código del pipeline
en vez de creérselo.

Nada de `delete`, nada de `search`, nada de `get(message_id)`: la disciplina que
`domain-foundation-ops.md:14` registra como apuesta ganada (`IncidentRepository` nació con
`add` y `maintenance` lo ensanchó cuando le tocó). El tercer método existe porque la quinta
condición de escalación de R5.1 no se puede contestar sin él, y su nombre dice la pregunta
—no «dame los mensajes»— para que la regla no se reimplemente en el caso de uso.

**Qué significa «sin resolución» en ese tercer método**, precisado al implementar la sección
4 (2026-08-16) tras el panel de arquitectura: significa **que la conversación no está hoy en
un estado terminal**, no «desde la última vez que se resolvió». `Conversation` no tiene
`resolved_at` ni `reopened_at` —todas las transiciones tocan el mismo `updated_at`— y darle
uno sería una migración que este change no hace. Así que se cuentan **todos** los mensajes de
huésped de la conversación con ese intent, con la conversación fuera de `RESOLVED`/`CLOSED`.

Consecuencia que se asume en vez de descubrirse: una conversación resuelta y reabierta
arrastra su cuenta anterior, así que escala antes de lo que escalaría una lectura por
episodios. Es la dirección segura —un huésped que vuelve a sacar el mismo tema después de
darlo por resuelto es justo a quien la IA está fallando— y es la que entrega este change.
Quien quiera contar por episodios trae la marca de tiempo y un parámetro `since` con ella.

Rejected: un `MessagingRepository` único con ambos agregados — «no repositorio "Dios" con
métodos de varios agregados» (`steering/backend-architecture.md`).

### D3 — `messages` se consulta siempre por `JOIN` con `conversations` (R1.2, R1.3)

**Chosen:** `SqlAlchemyMessageRepository` no contiene **ninguna sentencia que toque
`messages` sola**. Las lecturas hacen `select(MessageModel).join(ConversationModel, ...)
.where(ConversationModel.tenant_id == tenant_id, ...)`; la escritura resuelve primero el
padre dentro del tenant (`select(ConversationModel.id).where(tenant_id, id)`), levanta
`ConversationNotFoundError` si no resuelve, e inserta contra **el id que resolvió**, no
contra el que traía la entidad. Es literalmente `SqlAlchemyCleaningPhotoRepository`
(`app/cleaning/infrastructure/repositories.py:424-518`), y por la misma razón: `messages`
no tiene columna `tenant_id`, así que `tenant_scoped_classes()` no la selecciona y el
`with_loader_criteria` global de `app/core/db.py` **no la cubre** — el `JOIN` es el único
mecanismo, no defensa en profundidad.

Consecuencia de R1.5 que cae sola de aquí: «conversación inexistente» y «conversación de
otro tenant» son la misma consulta con cero filas, así que el mismo error, sin rama que las
distinga.

Rejected: añadir `messages.tenant_id` por migración — cambia el esquema que
`domain-foundation-ops` fijó desde el PRD §7.15, duplica la verdad y no elimina el `JOIN`
(habría que mantener las dos columnas coherentes).

### D4 — `Conversation` gana dos tablas de transiciones, una por eje (R5.3)

**Chosen:** la entidad declara **dos** `ClassVar` de transiciones, con la forma
`operación -> (orígenes admitidos, destino)` de `Incident._TRANSITIONS`, y las comprueba
**antes de escribir ningún campo**:

| Eje | Operación | Orígenes | Destino |
|---|---|---|---|
| `escalation_status` | `escalate` | `NONE` | `PENDING_HUMAN` |
| | `take_over` | `PENDING_HUMAN` | `HUMAN_HANDLING` |
| | `resolve_escalation` | `PENDING_HUMAN`, `HUMAN_HANDLING` | `RESOLVED` |
| `status` | `escalate` | `OPEN` | `ESCALATED` |
| | `resolve` | `OPEN`, `ESCALATED` | `RESOLVED` |
| | `reopen` | `RESOLVED` | `OPEN` |

Dos tablas y no una porque son dos enums que el PRD §7.14 declara por separado y que se
mueven por motivos distintos: `status` es el estado de la conversación para la bandeja,
`escalation_status` es el estado del traspaso a una persona. Una tabla combinada tendría
que enumerar el producto cartesiano y ocultaría cuál de los dos ejes rechazó una operación.

Tres consecuencias que se declaran aquí en vez de descubrirse:

- **`resolve_escalation` admite `PENDING_HUMAN` directamente**, sin pasar por
  `HUMAN_HANDLING`: un manager puede cerrar sin haber declarado formalmente que tomaba el
  mando, y R7.1 no da ruta para ese paso intermedio.
- **`HUMAN_HANDLING` sí tiene escritor**, y es la respuesta humana: contestar *es* tomar el
  mando, así que `POST /messages` con respuesta de persona sobre una conversación en
  `PENDING_HUMAN` ejecuta `take_over`. Sin esto el miembro del enum quedaría muerto.
- **`ConversationStatus.CLOSED` no tiene escritor en este change**, y consta así en vez de
  inventarle una ruta. Un mensaje de huésped sobre una conversación `RESOLVED` la reabre
  (`reopen`); sobre una `CLOSED` se rechaza con error de dominio nombrado.

Y dos efectos **entre ejes** que la tabla no cubre porque la tabla es por eje, precisados al
implementar la sección 2 (2026-08-16) en vez de descubrirse en el primer incidente:

- **`resolve` cierra también la escalación** cuando la hay (`PENDING_HUMAN` o
  `HUMAN_HANDLING` → `RESOLVED`). R7.1 no da ruta para `resolve_escalation` por separado, así
  que `POST /resolve` es lo único que puede moverla: sin esto, una conversación resuelta se
  queda para siempre en la lista de traspasos pendientes.
- **`reopen` limpia una escalación `RESOLVED`** (vuelve a `NONE`). `escalate` solo admite
  origen `NONE` —el mecanismo de R5.4—, así que una conversación reabierta arrastrando
  `escalation_status = RESOLVED` no podría volver a escalar nunca: un huésped escribiendo
  «hay humo» en un hilo reabierto levantaría un error en vez de llegar a una persona.
  Reiniciar el ciclo de escalación es lo que mantiene R5.1 alcanzable **sin** ensanchar los
  orígenes de `escalate`, que es lo que rompería R5.4.

Rejected: validar las transiciones en el caso de uso — «si hay una regla, pertenece a
`domain/`», y habría que repetirla en cada una de las tres rutas que escalan o resuelven.

### D5 — `MessageIntent`: enum cerrado de catorce miembros (R2.3)

**Chosen:** `app/messaging/domain/enums.py` gana `MessageIntent` con los catorce nombres
literales del PRD §13 (`CHECKIN_INSTRUCTIONS`, `ACCESS_PROBLEM`, `WIFI`, `PARKING`,
`LATE_CHECKOUT`, `EARLY_CHECKIN`, `CLEANING_ISSUE`, `MAINTENANCE_ISSUE`, `NOISE`,
`REFUND_OR_COMPENSATION`, `EMERGENCY`, `GENERAL_FAQ`, `REVIEW_REQUEST`, `UNKNOWN`). Sin
`ASSUMPTION`: a diferencia de `ConversationStatus`, el PRD sí lo declara como bloque propio;
lo que no tiene es nombre, y `<Entidad><Campo>` daría `MessageIntent` igual.

Rejected: reutilizar `IncidentCategory` para los intents de avería — son vocabularios de
dominios distintos y `maintenance` ya prohíbe expresamente el cruce (R2.2).

### D6 — El puerto `AIAdapter`: dos métodos, y el vocabulario vive en el tipo (R2.1, R2.4)

**Chosen:** `app/messaging/domain/ports.py` declara

```python
class AIAdapter(Protocol):
    async def classify_message(self, *, content: str, language: str,
                               context: ConversationContext) -> MessageClassification: ...
    async def generate_response(self, *, intent: MessageIntent, language: str,
                                context: ConversationContext) -> GeneratedResponse: ...
```

y nada más — ni `classify_incident` (es de `maintenance`, con puerto propio, y su spec lo
prohíbe en la dirección contraria), ni `validate_cleaning_photo`, ni `summarize_incident`,
ni `draft_review_response`. `ConversationContext` es un value object congelado con
**solo identificadores y valores cerrados** (`conversation_id`, `property_id`,
`reservation_id`, `channel`, `language`, `ai_enabled`, `guest_message_count`): nunca el
historial de texto, porque el objeto se le pasa a un adaptador que mañana es un proveedor
externo.

El contrato de R2.4 se hace cumplir **en `__post_init__` de los dos valores de retorno**,
que es lo que `IncidentClassification` demostró que hace falta —la prosa en el puerto y la
construcción cuidadosa de un adaptador no sobreviven a la segunda implementación—:

```python
@dataclass(frozen=True)
class MessageClassification:
    intent: MessageIntent      # __post_init__ exige que sea miembro del enum
    confidence: Decimal        # __post_init__ exige 0 <= c <= 1

@dataclass(frozen=True)
class GeneratedResponse:
    content: str
    language: str              # miembro de SUPPORTED_LANGUAGES
    template_key: str          # "<INTENT>:<lang>", identificador cerrado
    vocabulary: frozenset[str] # no vacío; content DEBE estar dentro
```

`MessageClassification` no lleva `vocabulary` y sí lo lleva `GeneratedResponse`, y la
asimetría es deliberada: el vocabulario cerrado de una clasificación **es** `MessageIntent`,
y comprobarlo es un `isinstance`; el de una respuesta es un catálogo de cadenas que solo el
adaptador conoce, así que tiene que declararlo en el valor que devuelve. La comprobación en
`__post_init__` alcanza a todo adaptador que devuelva el tipo declarado, viva donde viva —
incluido `app/integrations/`, adonde iría un proveedor real.

`EXTERNAL_DEPENDENCY` (R2.8): el adaptador real queda fuera; `MockAIAdapter` es el único
implementador que entrega este change.

Rejected: un `vocabulary` ceremonial también en la clasificación — un campo que un adaptador
rellena con `frozenset(MessageIntent)` no comprueba nada que el `isinstance` no compruebe ya.
Rejected: declarar el puerto con los seis métodos del PRD §13 y dejar cuatro en
`NotImplementedError` — rompe Liskov exactamente como ADR 0006 decisión 3 razonó para
`PMSMessagingPort`.

### D7 — Catálogo de plantillas versionado, sin un solo hueco de interpolación (R2.6, R3.3)

**Chosen:** `app/messaging/domain/templates.py` declara

```python
TEMPLATE_CATALOGUE_VERSION = "2026-08-16.1"
RESPONSE_TEMPLATES: Mapping[tuple[MessageIntent, str], str]   # 11 intents x {es, en}
RESPONSE_VOCABULARY = frozenset(RESPONSE_TEMPLATES.values())
```

Once intents y no catorce: `REFUND_OR_COMPENSATION`, `EMERGENCY` y `UNKNOWN` **no tienen
plantilla**, porque R2.7 prohíbe siquiera invocar `generate_response` para ellos — la
ausencia en el catálogo es la segunda red de esa prohibición, y un `KeyError` ruidoso
si alguien la salta.

Las plantillas son constantes completas, sin `{...}`, sin `%s` y sin `f`: un test recorre el
catálogo y rechaza cualquier hueco, igual que
`tests/maintenance/test_classifier_vocabulary_contract.py` hace con los `summary`. Eso es lo
que convierte la regla 10 de `steering/security.md` y el principio 6 de `product.md` en algo
verificable en vez de una promesa: un catálogo cerrado no puede prometer un reembolso,
admitir responsabilidad, dar asesoría legal, inventar un código de acceso ni afirmar que un
técnico va de camino, porque no hay sitio donde meter esa frase.

Y es lo que sostiene la forma cerrada de `messages.content` cuando el escritor somos
nosotros (R3.3, D16): el valor persistido es *literalmente un miembro de
`RESPONSE_VOCABULARY`*, comprobado en construcción por `GeneratedResponse`.

Rejected: plantillas con datos de la reserva interpolados (hora de check-in, nombre) — es
justamente la vía por la que `incidents.ai_summary` estuvo a punto de acabar con el número
de documento de un huésped; el día que haga falta, se declara como forma estructurada con
su conjunto cerrado de huecos y su propio test, no como una excepción tácita.

### D8 — `MockAIAdapter`: determinista, sin I/O, con la confianza que fija el PRD (R2.5)

**Chosen:** `app/messaging/infrastructure/ai.py`, calcado de
`RuleBasedIncidentClassifier`: tabla de palabras clave por intent en `es`/`en`, orden de la
tupla como desempate explícito, normalización a minúsculas sin acentos y por palabras
enteras. Reconocido → `confidence = Decimal("0.80")` (PRD §13 lo dice literalmente);
no reconocido → `UNKNOWN` con `Decimal("0.30")`, por debajo del `0.75` por defecto, de modo
que **el camino de escalación queda ejercitado por el mock** y no solo por un test que
fabrica una confianza baja a mano.

Vive en `messaging/infrastructure/` y no en `app/integrations/` por el mismo criterio que el
clasificador de averías: no habla con ningún sistema externo y no lo comparte nadie;
`steering/backend.md` reserva ese paquete para «adapters externos compartidos».

Rejected: un mock que devuelva confianza aleatoria o variable — haría los tests
aproximaciones en vez de aserciones, y la suite corre en paralelo (`steering/testing.md`).

### D9 — Detección de idioma: función pura de dominio entre `es` y `en` (R4.8)

**Chosen:** `app/messaging/domain/language.py` expone
`detect_language(content: str) -> str | None`: puntúa marcadores cerrados por idioma
(palabras función y caracteres exclusivos del español) sobre el texto normalizado, y
devuelve `None` cuando empatan o no hay señal. El caso de uso hace
`detected or conversation.language` — que es exactamente lo que pide R4.8, y deja la
decisión de fallback en un solo sitio.

Rejected: `langdetect`/`fasttext` — dependencia nueva para distinguir dos idiomas, con
resultado dependiente de semilla (rompe `steering/testing.md`: nada aleatorio en la suite)
y peor sobre mensajes de una línea, que es el 90 % de este tráfico.
Rejected: reutilizar el `_normalise` de `maintenance/infrastructure/classifier.py` — sería
un import de la `infrastructure/` de otro dominio desde el `domain/` de éste, que
`tests/test_layering.py` rechaza; se copian las seis líneas y consta por qué.

### D10 — La política de escalación es un servicio de dominio puro, con orden declarado (R5.1)

**Chosen:** `app/messaging/domain/escalation.py` declara `EscalationReason` (enum cerrado) y

```python
def evaluate(*, classification, content, threshold, repeated_intent_count,
             hours_to_checkin: Decimal | None) -> EscalationReason | None
```

Puro, sin repositorios: el caso de uso reúne los datos y esta función decide. Es una regla
de negocio, así que vive en `domain/` («No lógica de negocio en `application/`»), y así las
seis condiciones se testean sin montar nada.

**El orden importa y se declara**, porque las condiciones no son excluyentes y la razón que
se registra es la primera que casa. Va de menos a más dependiente del clasificador:

1. `EMERGENCY_KEYWORD` — no depende del clasificador en absoluto.
2. `LOW_CONFIDENCE` — si la confianza es baja, el intent no es de fiar, así que se decide
   antes que cualquier condición basada en él. La comparación es **estrictamente menor**
   que `TenantConfig.ai_confidence_threshold`, el mismo borde exacto que
   `Incident.classify` (`app/maintenance/domain/entities.py:219`), para que las dos
   capabilities no diverjan (R4.2).
3. `EMERGENCY_INTENT`
4. `REFUND_OR_COMPENSATION`
5. `IMMINENT_CHECKIN_ACCESS_PROBLEM` — intent `ACCESS_PROBLEM` con menos de 2 h para el
   check-in.
6. `REPEATED_INTENT` — más de dos mensajes de huésped con el mismo intent sin resolución.

Y una séptima que **no** es del PRD §13 y se nombra como divergencia:
`DELIVERY_FAILED` (D14). Las seis del PRD deciden *si contestar*; ésta es el estado en el
que queda una conversación cuyo envío falló, y R6.5 exige que un humano pueda recuperarla.

**Precisión sobre la condición 2, hecha al implementar la sección 3 (2026-08-16).**
`LOW_CONFIDENCE` cubre **dos** formas de no tener veredicto, no una: la confianza por debajo
del umbral (R4.2) **y el intent `UNKNOWN`**. R2.7 exige escalar sin generar respuesta para
`UNKNOWN`, y D7 no le da plantilla — así que sin esto un clasificador *seguro* de que un
mensaje es inclasificable (o un tenant con el umbral por debajo del `0.30` del mock) se
colaría por las seis condiciones y llegaría a un `KeyError` del catálogo. No se añade una
octava razón porque no habría nada nuevo que contarle a un operador: las dos significan que
el clasificador no dio nada sobre lo que actuar, que es lo que `LOW_CONFIDENCE` ya nombra.

La condición 5 necesita el instante real del check-in, que no es una resta de fechas: se
obtiene con `effective_bounds(property, reservation)`
(`app/properties/domain/clock_triggers.py:59`), que ya resuelve la zona horaria de la
vivienda y los dos huecos de DST. Reimplementarla es la única aritmética que ese módulo
dice expresamente que no se debe reimplementar. Si la conversación no tiene
`reservation_id`, `hours_to_checkin` llega `None` y la condición **no se cumple**, sin
fallar el procesamiento (R5.6).

Rejected: `requires_escalation` como campo de `MessageClassification` (lo sugiere el PRD
§13) — pondría la política dentro del adaptador, es decir, dentro de lo que mañana es un
proveedor externo; el sistema decide cuándo escala, no el modelo.

### D11 — El pipeline: un caso de uso, una transacción, síncrono (R4.1, R4.7)

**Chosen:** `ProcessInboundGuestMessageUseCase.execute()` en
`app/messaging/application/use_cases.py`, con este orden y **un solo `commit()` al final**:

1. resolver la conversación dentro del tenant (404 indistinguible, R1.5) y rechazar si está
   `CLOSED`; reabrir si está `RESOLVED`;
2. persistir el `Message` del huésped, con `language` detectado (D9);
3. actualizar `Conversation.last_message_at` en la misma transacción (R1.4);
4. clasificar con `AIAdapter`;
5. emitir `TimelineEvent(GUEST_MESSAGE_RECEIVED)`;
6. evaluar la política de escalación (D10);
7. si escala → R5 (estado, timeline, notificación) y **no** se genera respuesta;
8. si no escala y `ai_enabled` → generar, persistir el `Message` de IA, enviar (D14),
   `TimelineEvent(AI_RESPONSE_SENT)`;
9. si el intent es `MAINTENANCE_ISSUE` o `ACCESS_PROBLEM` → alta de incidencia (D12);
10. `commit()`.

El paso 3 va donde va para que la bandeja pueda ordenarse sin recorrer `messages` (R1.4), y
se hace con un método de la entidad (`Conversation.register_message(now)`), no con un
`setattr` desde el caso de uso.

**Dos precisiones sobre el orden, hechas al implementar la sección 6 (2026-08-16):**

- **Se clasifica antes de persistir** el mensaje del huésped, y no después como sugiere la
  lectura literal de R4.1. `Message` es `frozen` —el arreglo del panel de seguridad para que
  la degradación de `intent` de R3.4 no fuera sólo de construcción—, así que su `intent` tiene
  que conocerse al construirlo. Dentro de la transacción única las dos ordenaciones son
  indistinguibles desde fuera, y lo que R4.1 exige de fondo —que el mensaje quede registrado,
  clasificado y en el timeline, todo o nada— no cambia.
- **El destinatario del envío se resuelve del huésped de la conversación**: teléfono para
  `WHATSAPP`, correo para `EMAIL`, y nada para `MANUAL` (la fila *es* la entrega) ni para
  `PHONE_TRANSCRIPT` (no tiene salida). D14 declara `recipient_contact` en el puerto sin decir
  quién lo resuelve; lo resuelve el pipeline, con `GuestRepository.get`, que devuelve
  `GuestSummary` — la proyección que lleva los contactos y estructuralmente no puede llevar el
  documento de identidad. Sin huésped o sin contacto de ese tipo llega `None`, el adaptador
  responde `INVALID_RECIPIENT` y R6.5 lo lleva a una persona: no podemos entregar de verdad, y
  fingir lo contrario le enseñaría a un operador un mensaje que el huésped nunca recibió.

R4.3 cae en el paso 8: con `ai_enabled = false` se ejecutan 1-6 y 9, y nunca 8 — el mensaje
se clasifica y se registra, pero no se genera ni se envía nada. Nótese que **la escalación
sí ocurre** con `ai_enabled = false`: apagar la IA apaga la respuesta automática, no el
aviso de que hay una emergencia.

**Y una segunda condición para el paso 8, decidida al implementar la sección 6 (2026-08-16)
tras el panel de QA: la IA deja de contestar en cuanto ha traspasado.** Mientras
`escalation_status` sea `PENDING_HUMAN` o `HUMAN_HANDLING`, los mensajes siguientes se
registran y se clasifican pero no reciben respuesta automática. R5.4 sólo dice que no se
vuelva a notificar, y el pipeline tal como estaba escrito seguía contestando con plantillas a
cada mensaje posterior de una conversación que un manager ya tenía en la mano — así que el
huésped podía recibir la respuesta del manager y una plantilla contradiciéndola, y el manager
estaría discutiendo con su propio sistema. `RESOLVED` **no** cuenta como traspasada: la
escalación terminó y un mensaje nuevo reabre la conversación con el eje en `NONE` (D4), así
que la IA vuelve a contestar — y está bien, porque eso ya es otro problema.

**Síncrono, dentro de la petición**, y la diferencia con `maintenance` (que sacó su
clasificación a un job de Celery, su D2) es deliberada: allí el huésped no espera nada, aquí
la promesa de producto es que se le contesta. Con `MockAIAdapter` el coste es aritmética. El
riesgo que esto abre con un proveedor real está en Risks, con su remedio nombrado.

Rejected: partir el pipeline en dos transacciones (mensaje + procesamiento) — R4.7 lo
prohíbe expresamente, y el estado intermedio (mensaje persistido sin evento de timeline, o
conversación escalada sin notificación) es justo el que nadie sabe reparar.

### D12 — El alta de incidencia entra por un puerto de `messaging`, no por un import lateral (R4.6)

**Chosen:** `messaging` declara en su propio `domain/ports.py`

```python
class IncidentReportingPort(Protocol):
    async def report(self, *, tenant_id, property_id, reservation_id, title,
                     description, actor_user_id, ip, now) -> uuid.UUID: ...
```

y `maintenance` aporta el implementador: un `ReportIncidentFromConversationUseCase` nuevo en
`app/maintenance/application/use_cases.py`, hermano del `ReportGuestIncidentUseCase` que
`guest-portal-api` dejó allí, que crea el `Incident` en `OPEN`, escribe su `AuditLog` y su
`TimelineEvent(INCIDENT_CREATED)`. El cableado ocurre en `messaging/api/dependencies.py`,
que es la capa a la que le está permitido conocer los dos módulos, y se le inyecta un
`CallerOwnedUnitOfWork` para que **el commit siga siendo uno solo**, el del pipeline — el
mecanismo que `app/core/unit_of_work.py:41` documenta y que `guest-portal-api` estrenó tras
equivocarse primero exactamente en esto.

Dos cosas que esto resuelve sin pedir permiso a nadie:

- **La clasificación de la incidencia NO ocurre aquí** (R4.6): la incidencia nace `OPEN` con
  `ai_classification` nulo, que es precisamente lo que el job `classify_incidents` de
  `maintenance` (su D2) recoge en el siguiente tick. Ni una línea de `IncidentClassifier` en
  este change.
- **El `AuditLog` de esa incidencia lleva actor humano**, así que **no hace falta ninguna
  excepción nueva a la regla 9** de `steering/security.md`: el mensaje de huésped entra por
  panel o por API con un usuario autenticado al teclado (R4.5, «los mensajes entran por el
  panel o por API»), y ése es el actor. Se dice explícitamente porque la cuarta excepción de
  la regla 9 —la clasificación automática sin actor— invita a suponer lo contrario.

`IncidentSource.GUEST` es el valor correcto y el enum no cambia.

Rejected: importar `maintenance.application.use_cases` desde `messaging/application/` —
funciona y `tests/test_layering.py` no lo vería, pero deja `application/` dependiendo de otro
dominio en vez de de un puerto propio, que es lo contrario de lo que hizo
`LiveCleaningTaskQuery`.
Rejected: reutilizar `ReportGuestIncidentUseCase` — exige un `reporter_token_hash` que aquí
no existe y prohíbe el actor humano; forzarlo significaría inventar un digest.

### D13 — `Incident.title` constante, `description` verbatim (R4.6 + regla 11)

**Chosen:** al derivar una incidencia de un mensaje, `title` sale de un catálogo cerrado de
dos constantes (`"Maintenance issue reported in a guest conversation"` /
`"Access problem reported in a guest conversation"`, por intent) y `description` es **el
contenido del mensaje del huésped, tal cual, sin recortar ni parafrasear**.

El censo de la regla 11 se hace por quién escribe: `title` lo componemos nosotros, así que
va en forma cerrada; `description` no es nuestro, es la prosa del huésped, y la fila de
`incidents.title`/`description` en `steering/security.md` nombra ya como heredero a «quien
traiga las demás vías de alta de incidencias» bajo la excepción 2. La copia de una columna a
otra no lo convierte en escritura nuestra: **el valor sigue siendo el que tecleó el
huésped**, no hay plantilla, no hay interpolación y ningún valor de la regla 3 se renderiza
ahí. Es la lectura estricta de la excepción 2 («el valor no es nuestro y no lo hemos ido a
buscar») y no una ampliación de ella.

Rejected: `description` constante con el id de la conversación — el técnico dejaría de saber
qué está roto, que es lo único para lo que existe el campo.
Rejected: un resumen generado del mensaje — eso sí sería escritura nuestra, cae bajo la
forma estructurada por defecto, y es la fuga exacta que `maintenance` D4 cerró.

### D14 — Puerto de canal de salida: fallo por valor, canales de OTA por excepción (R6)

**Chosen:** `app/messaging/domain/ports.py` declara

```python
class OutboundMessagePort(Protocol):
    async def send(self, *, channel: ConversationChannel, conversation_id: uuid.UUID,
                   recipient_contact: str | None, content: str,
                   language: str) -> ChannelSendResult: ...
```

`ChannelSendResult` es el patrón de `NotificationResult`: éxito o fallo **por valor**, con
`ChannelErrorCode` cerrado (`INVALID_RECIPIENT`, `CHANNEL_INBOUND_ONLY`,
`ADAPTER_UNAVAILABLE`) y **nunca el cuerpo** (R6.5).

`app/messaging/infrastructure/channels.py` registra:

| `ConversationChannel` | Adaptador | Qué hace |
|---|---|---|
| `MANUAL` | `PanelOutboundAdapter` | no-op: la fila **es** la entrega (precedente `InAppNotificationAdapter`) |
| `WHATSAPP` | delega en `MockWhatsAppAdapter` | el mock que `access-notifications` ya gobierna |
| `EMAIL` | delega en `ConsoleEmailAdapter` | ídem |
| `PHONE_TRANSCRIPT` | `InboundOnlyAdapter` | devuelve `CHANNEL_INBOUND_ONLY` |
| `AIRBNB_MSG`, `BOOKING_MSG` | — | **ausentes del registro**; el caso de uso levanta `PMSChannelUnavailableError` |

Delegar en los adaptadores de `notifications` en vez de duplicarlos hereda gratis su
disciplina —no loguean `subject`, `body` ni `recipient_contact`, solo longitudes— que es
exactamente lo que la regla 11 quiere para este contenido.

La ausencia de los dos canales de OTA es el mecanismo de R6.3: no hay ninguna clave en el
registro con la que caer a consola en silencio. `PMSMessagingPort` **no se toca** (R6.4):
sigue siendo el puerto sin métodos que `pms-provider-resolution` fijó, y su forma la decide
el primer proveedor que la implemente.

**Qué pasa cuando el envío falla** (R6.5): el `Message` de IA se escribe con
`delivery_status = "FAILED"` y `delivery_error_code = <miembro de ChannelErrorCode>` en su
`metadata`, la conversación escala con `EscalationReason.DELIVERY_FAILED`, y **no** se emite
`AI_RESPONSE_SENT` — porque no se envió, y `timeline_events` es append-only.

**Precisión sobre el orden, hecha al implementar la sección 2 (2026-08-16).** Este párrafo
decía «el `Message` de IA ya está persistido (se persiste antes de enviar, para que un fallo
no lo pierda)». Dentro de la transacción única de R4.7 eso no es una garantía distinta de
construir la fila después de enviar: **nada es durable hasta el único `commit()`**, así que
las dos ordenaciones pierden exactamente lo mismo si algo revienta, y ninguna de las dos
pierde nada en el camino de fallo-por-valor de D14, que es el que R6.5 gobierna. Lo que sí
cambia es que «persistir y luego anotar» exige mutar un `Message` ya escrito —y por tanto
`save()` en `MessageRepository`, que R1.1 no admite, y un `Message` mutable, que es el hueco
que el panel de seguridad encontró en `intent`—. Así que el pipeline **envía primero y
construye la fila una sola vez, con su resultado ya dentro**; `Message` es `frozen`, y
`messages` sigue siendo append-only también en el código.

Rejected: excepciones para los fallos de entrega — obligaría a abortar la transacción y
perder el mensaje, que es exactamente lo que R6.5 prohíbe.
Rejected: un `NoOpAdapter` para `AIRBNB_MSG`/`BOOKING_MSG` — es el «caer en silencio a
consola» que R6.3 nombra.

### D15 — `messages.metadata`: value object con conjunto cerrado de claves (R3.5)

**Chosen:** `MessageMetadata`, dataclass congelado en `domain/value_objects.py`, con
`to_dict()` que emite solo las claves presentes. El conjunto cerrado, y nada más:

| Clave | Valor | Quién la pone |
|---|---|---|
| `escalation_reason` | miembro de `EscalationReason` | pipeline al escalar |
| `template_key` | `"<INTENT>:<lang>"` | respuesta de IA |
| `template_version` | `TEMPLATE_CATALOGUE_VERSION` | respuesta de IA |
| `delivery_status` | `"SENT"` / `"FAILED"` | envío |
| `delivery_error_code` | miembro de `ChannelErrorCode` | envío fallido |
| `source_message_id` | UUID en texto | respuesta de IA (el mensaje que contesta) |

El repositorio acepta `MessageMetadata | None`, no un `dict`, así que no hay vía por la que
un caso de uso posterior meta texto del huésped: es el mecanismo de `ChangeSet` en
`audit_logs.changes`, aplicado a la columna de al lado.

**Y `Message.metadata` también**, precisado al implementar la sección 2 (2026-08-16) tras el
panel de seguridad: la obligación estaba escrita sobre la firma del repositorio, pero la
entidad seguía llevando el `dict[str, Any]` que dejó `domain-foundation-ops`, así que el
conjunto cerrado era cierto del value object y falso de la columna — la fila del censo que
miente. `Message.metadata` es `MessageMetadata | None` y el adaptador llama a `to_dict()` al
persistir.

Dos claves de las seis son cadenas y no enums, y **se comprueban en vez de confiarse**:
`template_key` contra `MessageIntent` × `SUPPORTED_LANGUAGES`, y `template_version` contra la
forma `AAAA-MM-DD.N`. El precedente es la columna de al lado: el censo registra que el
`adapter` de `incidents.ai_classification` «degrada a `UNKNOWN_CLASSIFIER` si no es un
identificador de Python», porque una clave que solo *parece* un identificador es el hueco por
el que se censa un sumidero.

Rejected: un `dict[str, Any]` con un test que barra las claves — un barrido no alcanza a un
escritor que se mude de directorio, que es la lección literal de
`IncidentClassification.vocabulary`.

### D16 — El censo de la regla 11 crece con **cinco** filas, no con tres (R3)

**Chosen:** `sdd/steering/security.md` —el único sitio donde vive ese contrato— gana:

| Columna | Forma | Escritor |
|---|---|---|
| `messages.content` (`sender_type = GUEST`) | **excepción 4** (nueva): prosa de tercero | `messaging-ai` |
| `messages.content` (`sender_type` de persona autenticada) | **excepción 3**, la que ya existe | `messaging-ai` |
| `messages.content` (`ai_generated = true`) | estructurada (forma cerrada: miembro de `RESPONSE_VOCABULARY`) | `messaging-ai` |
| `messages.intent` | estructurada (forma cerrada: miembro de `MessageIntent`; lo que no encaje degrada a `UNKNOWN`) | `messaging-ai` |
| `messages.metadata` | estructurada (conjunto cerrado de claves, D15) | `messaging-ai` |

La cuenta de la cabecera son las **cinco** filas de esa tabla; el título decía «cuatro» y lo
corrigió la review de 2026-08-16, que además partió en dos la fila de
`incidents.title`/`description` —este change es su segundo escritor y con él `title` deja de
ser excepción 2 para ser forma cerrada—, de modo que el censo entregado tiene dieciséis
columnas y dieciocho filas.

**Más de tres, y el porqué es lo que hay que llevarse de esta decisión.** El proposal
enumera dos contratos para `messages.content` —el del huésped (R3.2) y el nuestro (R3.3)—
pero R4.5 introduce un **tercer escritor** que ninguno de los dos cubre: la respuesta manual
de un manager o de una propietaria. No es prosa de tercero (la persona está autenticada y
tiene RBAC) ni es forma cerrada (teclea lo que quiere), y ya existe una excepción escrita
para exactamente esa figura: la 3, la de `owner_approvals.response_notes`, concedida «por la
misma propiedad del escritor… el valor no es nuestro y no lo hemos ido a buscar», con la
diferencia tranquilizadora de que quien teclea está autenticado. Se cita, no se rederiva.

El censo se hace **por quién escribe la columna**, no por la columna, así que una columna con
tres escritores da tres filas. Es la lección literal de `webhook_events.event_type`.

`messages.intent` es un `VARCHAR(100)` que *parece* un enum y no lo es — el mismo aspecto que
hizo que aquélla se olvidara —, y por eso la degradación a `UNKNOWN` va en la construcción de
`Message` y no en la confianza de que el llamante pase un miembro.

**No se propaga** (R3.6): el `TimelineEvent` de un mensaje lleva título constante y solo
identificadores y enums en `metadata`; ni el contenido ni el intent entran en
`audit_logs.changes` (el `AUDITABLE_FIELDS` que este change necesita para la incidencia
derivada no nombra ningún campo de texto). Cada una de las formas anteriores lleva su test
(R3.7).

Rejected: una sola fila para `messages.content` con «depende del escritor» — una fila del
censo que no dice qué contrato aplica es peor que una columna sin censar, que es
textualmente lo que el panel encontró en `owner_approvals.response_notes`.

### D17 — Los siete endpoints, sus permisos y sus dos permisos nuevos (R7)

**Chosen:** `app/messaging/api/router.py`, prefijo `/conversations`, tag `messaging`, con
las rutas exactas del PRD §16 y `require(...)` por ruta (que
`tests/test_route_authorization.py` recorre):

| Ruta | Permiso | Notas |
|---|---|---|
| `GET /conversations` | `READ_CONVERSATIONS` | filtros `status`, `escalation_status`, `property_id`; `page`/`per_page`; orden `last_message_at DESC NULLS LAST, id` (R7.3) |
| `POST /conversations` | `MANAGE_CONVERSATIONS` | `property_id` obligatorio (D19) |
| `GET /conversations/{id}` | `READ_CONVERSATIONS` | |
| `GET /conversations/{id}/messages` | `READ_CONVERSATIONS` | orden `created_at ASC, id`; paginado (R7.4) |
| `POST /conversations/{id}/messages` | `MANAGE_CONVERSATIONS` | dos comportamientos, D18 |
| `POST /conversations/{id}/escalate` | `MANAGE_CONVERSATIONS` | escalación manual |
| `POST /conversations/{id}/resolve` | `MANAGE_CONVERSATIONS` | |

Dos permisos nuevos en `app/auth/domain/policy.py`, con el reparto que ya usan
`reservations` y `properties`: `PROPERTY_MANAGER` recibe los dos (PRD §6 le da «operar
reservas, limpiezas, incidencias, **conversaciones**»), `TENANT_OWNER` recibe la lectura,
`CLEANER` y `TECHNICIAN` ninguno, y `SUPER_ADMIN` ninguno por la razón de siempre (no tiene
papel operativo dentro de un tenant hasta que `saas-cross-tenant` decida).

**Resuelto en el gate de `/sdd:design` (2026-08-16): la propietaria solo lee.** Se pesó
contra el precedente de `_GUEST_ACCESS_TOKEN_MANAGE` —que sí se le concedió, con el
argumento de que una propietaria de dos pisos sin manager se quedaría sin poder operar— y se
resolvió a favor de la simetría con `reservations` y `properties`, que es lo que PRD §6 dice
literalmente. Consecuencia que se asume y se declara en vez de descubrirse:
**`MessageSenderType.OWNER` no tiene escritor en este change**, y el mapeo rol→`sender_type`
de D18 tiene una sola entrada (`PROPERTY_MANAGER → MANAGER`). Quien conceda
`MANAGE_CONVERSATIONS` a la propietaria más adelante añade la segunda; el mapeo es una tabla
precisamente para que sea una línea.

El orden de la bandeja es `last_message_at DESC NULLS LAST`: una conversación recién creada
sin mensajes tiene `last_message_at` nulo, y colarla arriba escondería lo que arde.

`app/messaging/api/errors.py` mapea los errores de dominio al sobre del PRD §23, con tabla
exhaustiva sobre `domain/exceptions.py` y un test que lo comprueba (precedente
`maintenance/api/errors.py`): `ConversationNotFoundError` → 404;
`InvalidConversationTransitionError`/`ConversationClosedError` → 409;
`PMSChannelUnavailableError` → 422; `MessagingValidationError` → 422.

Rejected: un tercer permiso `EXECUTE_CONVERSATIONS` para escalar/resolver — no hay un rol
que las haga y no pueda gestionar la bandeja, y el catálogo lleva «solo las permisos que un
change aplica de verdad».

### D18 — `POST /messages`: `sender_type` declarado, nunca inventado por el cliente (R4.4, R4.5)

**Chosen:** el cuerpo lleva `sender_type` opcional con **un único valor admitido, `GUEST`**.

- Con `GUEST`: «estoy transcribiendo lo que dijo el huésped» → pipeline completo de D11.
- Omitido: respuesta humana → `sender_type` se **deriva del rol** del token
  (hoy una sola entrada, `PROPERTY_MANAGER → MANAGER`, porque D17 deja a la propietaria en
  solo lectura; un rol sin entrada en la tabla es un 403 antes de llegar aquí, no un
  `sender_type` inventado), se persiste con `sender_user_id`,
  se emite `TimelineEvent(HUMAN_RESPONSE_SENT)`, y si la conversación está en
  `PENDING_HUMAN` se ejecuta `take_over` (D4).
- Cualquier otro valor (`AI`, `SYSTEM`, o un `MANAGER` explícito): 422. Un cliente no puede
  declarar que un mensaje lo escribió la IA.

`ai_generated`, `confidence_score`, `intent` y `metadata` **no son campos de entrada** en
ningún caso: los escribe el pipeline.

Rejected: dos endpoints separados para mensaje entrante y respuesta — el PRD §16 declara
uno, y la bandeja del frontend (`field-apps`) espera esa ruta.

### D19 — `property_id` obligatorio al crear una conversación, sin migración

**Chosen:** `POST /conversations` exige `property_id`, y `Conversation` rechaza en
construcción una conversación sin él. **La columna sigue siendo nullable**: no hay
migración en este change.

Es una restricción de este change y no del esquema, y la razón es dura:
`TimelineEventFactory` exige `property_id` como UUID no nulo, así que una conversación sin
vivienda **no puede producir ninguno de los cuatro `TimelineEvent`** que R4.1, R4.4, R4.5 y
R5.2 declaran obligatorios. Entre no poder cumplir cuatro SHALL y exigir un dato que
siempre existe (una conversación es sobre una estancia, y una estancia es en una vivienda),
se exige el dato. Dejar la columna nullable es lo que no le cierra la puerta a
`beds24-messaging-adapter`, que podría recibir del PMS una conversación sin vivienda
resuelta todavía; ese día, quien la traiga decide qué hacer con el timeline.

Rejected: hacer la columna `NOT NULL` por migración — decide por un change futuro sobre un
caso que hoy nadie ejercita.
Rejected: omitir el `TimelineEvent` cuando falta `property_id` — convierte cuatro SHALL en
«casi siempre».

### D20 — La notificación de escalación, y la que no se repite (R5.2, R5.4)

**Chosen:** `app/messaging/domain/notifications.py`, constructor puro calcado de
`maintenance/domain/notifications.py`: `NotificationLog` con
`notification_type = GUEST_ESCALATION`, `channel = IN_APP`, `status = PENDING`,
`related_type = "conversation"`, `related_id = conversation_id`, `subject`/`body`
constantes más identificadores, y **sin `sla_deadline_at`** — `escalation_for`
(`app/notifications/domain/escalation.py:52`) no tiene regla para `GUEST_ESCALATION`, así
que un plazo aquí produciría un incumplimiento que no escala a nadie, exactamente el
razonamiento de `owner_approval_notification`. El SLA de respuesta humana es de
`celery-jobs` y está fuera de alcance.

Destinatarios: los `PROPERTY_MANAGER` activos del tenant, resueltos por
`UserRepository.list(UserFilters(role=..., status=ACTIVE))` como hace `_notify_owner`. Si no
hay ninguno, se registra un `logger.warning` y **no se falla el procesamiento**: el mensaje
del huésped ya está guardado y la conversación ya está en `ESCALATED`, que es el registro
que importa.

R5.4 se hace cumplir en la tabla de transiciones de D4, no con un `if` en el caso de uso:
`escalate` solo admite origen `NONE`, así que una conversación ya `PENDING_HUMAN` no puede
volver a escalar y por tanto **no puede emitir una segunda notificación**. Un mensaje
entrante sobre una conversación ya escalada se registra y clasifica con normalidad, y no
escala otra vez. La invariante vive en un sitio.

Rejected: comprobar `if conversation.escalation_status is not NONE` en el pipeline — sería
la misma regla escrita dos veces (pipeline y `POST /escalate`), y sabemos cómo acaba eso.

### D21 — Longitud máxima del cuerpo del mensaje (R7.6)

**Chosen:** `MAX_MESSAGE_CONTENT_LENGTH = 4000` en `app/messaging/domain/`, aplicada **dos
veces y a propósito**: en el esquema Pydantic (`max_length`), que es donde rechaza antes de
llegar al caso de uso, y en la construcción de `Message`, que es el único techo para un
llamante sin HTTP delante (un test, un worker, el pipeline). Es la disciplina de
`UploadCleaningPhotoUseCase._read_within_limit`.

**No se presenta como «rechazar antes de leer el cuerpo»**: eso solo lo satisface
`MaxBodySizeMiddleware` (regla 14 de `steering/security.md`), y este cuerpo es JSON pequeño
que el middleware ya acota. El comentario que acompañe la comprobación dirá lo que la
comprobación hace de verdad.

`ASSUMPTION`, confirmado en el gate de `/sdd:design` (2026-08-16): 4000 caracteres. WhatsApp
admite 4096 y los límites reales de Beds24 no están medidos; la constante es sustituible sin
tocar el pipeline y `beds24-messaging-adapter` la ajustará con datos. Se descartó 2000 (el de
`owner_approvals.response_notes`) por corto para una transcripción telefónica, y 10000 por
holgado para un sumidero de la regla 11 sin necesidad medida. La columna `messages.content`
es `TEXT` sin límite, así que **no hay migración**.

## Changes by area

| Área | Ficheros | Cambio |
|---|---|---|
| `messaging` / domain | `domain/enums.py` | +`MessageIntent` (14), +`EscalationReason` (7) |
| | `domain/entities.py` | `Conversation` gana dos tablas de transiciones y métodos (`escalate`, `take_over`, `resolve`, `reopen`, `register_message`); `Message` gana `__post_init__` (degradación de `intent`, longitud) y factorías |
| | `domain/value_objects.py` *(nuevo)* | `MessageClassification`, `GeneratedResponse`, `ConversationContext`, `MessageMetadata`, `ChannelSendResult`, `ChannelErrorCode` |
| | `domain/ports.py` *(nuevo)* | `AIAdapter`, `OutboundMessagePort`, `IncidentReportingPort` |
| | `domain/repositories.py` *(nuevo)* | `ConversationRepository`, `MessageRepository`, `ConversationFilters`, `ConversationPage`, `MessagePage` |
| | `domain/exceptions.py` *(nuevo)* | `MessagingDomainError` y su jerarquía plana |
| | `domain/templates.py` *(nuevo)* | catálogo versionado 11×2 + `RESPONSE_VOCABULARY` |
| | `domain/language.py` *(nuevo)* | `detect_language` |
| | `domain/escalation.py` *(nuevo)* | palabras clave de emergencia por idioma + `evaluate()` |
| | `domain/notifications.py` *(nuevo)* | `guest_escalation_notification` |
| `messaging` / application | `application/use_cases.py` *(nuevo)* | `ProcessInboundGuestMessage`, `RecordHumanReply`, `CreateConversation`, `ListConversations`, `GetConversation`, `ListMessages`, `EscalateConversation`, `ResolveConversation` |
| `messaging` / infra | `infrastructure/repositories.py` *(nuevo)* | los dos adapters SQLAlchemy; **ninguna sentencia sobre `messages` sin `JOIN`** |
| | `infrastructure/ai.py` *(nuevo)* | `MockAIAdapter` |
| | `infrastructure/channels.py` *(nuevo)* | registro de adapters de salida (delegan en `notifications`) |
| `messaging` / api | `api/{router,schemas,dependencies,errors}.py` *(nuevos)* | 7 rutas, DTOs, cableado, mapeo de errores |
| `maintenance` | `application/use_cases.py` | +`ReportIncidentFromConversationUseCase` (D12) |
| `auth` | `domain/policy.py` | +`READ_CONVERSATIONS`, +`MANAGE_CONVERSATIONS` y su reparto por rol |
| `app` | `main.py` | `include_router` + `register_messaging_error_handlers` |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados en el mismo PR (R7.5) |
| Steering | `sdd/steering/security.md` | censo de la regla 11: 16 columnas y 18 filas (D16), con la excepción 4 |
| Docs | `docs/messaging-ai.md`, `README.md` | capability operativa nueva |
| Diagramas | `docs/diagrams/2026-08-16_autohost-flujo-mensaje-entrante.png` | ya generado; ningún diagrama existente queda obsoleto (el hexagonal ya dibuja `messaging`, y el ER no cambia porque no hay migración) |
| Tests | `backend/tests/messaging/` | dominio, casos de uso con fakes, repositorios contra Postgres, rutas, aislamiento |

## Data & interfaces

**Esquema: sin migración.** Ni una columna, ni un índice, ni un tipo `ENUM` nuevo.
`MessageIntent` se persiste en el `VARCHAR(100)` que ya existe (mismo criterio que
`NotificationType` sobre `notification_logs.notification_type`), y `messages.content` es
`TEXT`. `conversations.property_id` sigue nullable (D19).

**Variables de entorno: ninguna.** El adaptador de IA es un mock sin credenciales; los de
canal delegan en los de `notifications`, que ya están configurados.

**API**: siete rutas nuevas bajo `/api/v1/conversations` (tabla en D17), con el sobre de
errores y la paginación del PRD §23. `openapi.json` y el `.d.ts` derivado se regeneran en el
mismo PR (R7.5) — ojo a la salvedad de `sdd/project.md`: `npm run api:generate` no funciona
tal cual en un worktree enlazado, hay que usar la secuencia de cuatro comandos documentada
allí.

**Eventos de timeline** (los cuatro ya declarados, ninguno nuevo):

| Evento | Actor | `metadata` |
|---|---|---|
| `GUEST_MESSAGE_RECEIVED` | `GUEST` (sin `actor_user_id`) | `conversation_id`, `message_id`, `intent`, `language` |
| `AI_RESPONSE_SENT` | `AI` | `conversation_id`, `message_id`, `intent`, `template_key` |
| `AI_ESCALATED_TO_HUMAN` | `AI` (automática) / `USER` (manual) | `conversation_id`, `escalation_reason` |
| `HUMAN_RESPONSE_SENT` | `USER` | `conversation_id`, `message_id` |

Títulos constantes, `metadata` con identificadores y enums cerrados, nunca contenido (R3.6).

**Notificación**: `GUEST_ESCALATION`, `IN_APP`, `PENDING`, sin `sla_deadline_at` (D20).

## Risks & mitigations

- **Latencia con un proveedor real de IA.** El pipeline es síncrono (D11) y con
  `MockAIAdapter` cuesta microsegundos; con un modelo real cuesta segundos, dentro de una
  transacción abierta. Mitigación nombrada, no resuelta aquí: el remedio es el que
  `maintenance` D2 ya eligió para su clasificación —un job de Celery— y el pipeline está
  partido en pasos precisamente para que mover 4-8 fuera sea un cambio de orquestación y no
  de reglas. Se anota como deuda del change que traiga el adaptador real.
- **Límite no documentado del canal real.** Es el riesgo residual que el proposal ya asume:
  se construye contra mocks, así que un límite del canal de Beds24 que no esté en
  `docs/beds24-spike.md` aparecerá con `beds24-messaging-adapter`. Lo que este design hace
  para abaratar ese día es que el único sitio que hay que tocar sea el registro de
  `channels.py` y el catálogo de plantillas.
- **Orden de la bandeja sin índice.** `ORDER BY last_message_at DESC` no tiene índice de
  respaldo (`conversations` solo trae `(tenant_id, status)` y `(reservation_id)`). A la
  escala del MVP —dos viviendas— es irrelevante y no se paga una migración por ello. Se
  revisa cuando un tenant pase de unos pocos miles de conversaciones, y consta aquí para que
  esa revisión no empiece de cero.
- **La detección de idioma de D9 es tosca.** Un mensaje de tres palabras puede caer del lado
  equivocado. El daño está acotado por construcción: la respuesta sale de un catálogo
  cerrado, así que lo peor que pasa es contestar en inglés a quien escribió en español —
  molesto, nunca peligroso —, y `Conversation.language` es el fallback declarado.
- **Una conversación con `AIRBNB_MSG`/`BOOKING_MSG` creada a mano queda muda.** El canal es
  aceptable en `POST /conversations` (el enum lo tiene) pero todo envío falla con
  `PMSChannelUnavailableError`. Es lo que R6.3 pide, y se documenta en `docs/messaging-ai.md`
  para que no se lea como un fallo.

## Open questions

Ninguna abierta. Las dos que levantó este design se resolvieron en su gate el 2026-08-16 y
viven ya en la decisión que gobiernan, no aquí:

- **La propietaria solo lee la bandeja** — en D17, con el precedente que se pesó en contra y
  la consecuencia que se asume (`MessageSenderType.OWNER` sin escritor).
- **4000 caracteres de longitud máxima** — en D21, con las dos alternativas descartadas.
