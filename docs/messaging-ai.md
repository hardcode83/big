# Mensajería con IA — cómo se opera

Capability del change `messaging-ai` (PRD §13, §16, §26.12). Esta página cuenta **cómo se usa
y se opera**; el *qué hace* está en `sdd/specs/messaging-ai.md` con sus criterios EARS, y el
contrato HTTP en `backend/openapi.json`.

El flujo completo, dibujado:
[`diagrams/2026-08-16_autohost-flujo-mensaje-entrante.png`](diagrams/2026-08-16_autohost-flujo-mensaje-entrante.png).

## El ciclo, de principio a fin

```
alguien abre una conversación        POST /conversations   (property_id obligatorio)
        │
        ▼
llega un mensaje del huésped         POST /conversations/{id}/messages
                                     { "content": "…", "sender_type": "GUEST" }
        │
        ├─ se detecta el idioma (es/en; si no se puede, el de la conversación)
        ├─ se clasifica el intent  (catorce del PRD §13)
        ├─ se guarda el mensaje con su idioma y su intent
        └─ TimelineEvent(GUEST_MESSAGE_RECEIVED)
        │
        ▼
   ¿toca escalar?   (las seis condiciones, en este orden)
        │
        ├── sí ──► ESCALATED + PENDING_HUMAN
        │           + TimelineEvent(AI_ESCALATED_TO_HUMAN)
        │           + notificación GUEST_ESCALATION a cada PROPERTY_MANAGER activo
        │           **y no se genera ninguna respuesta**
        │
        └── no ──► si ai_enabled y nadie la tiene ya en la mano:
                     respuesta de plantilla → se envía por el canal
                     + Message(sender_type=AI, ai_generated=true)
                     + TimelineEvent(AI_RESPONSE_SENT)
        │
        ▼
   ¿el intent es MAINTENANCE_ISSUE o ACCESS_PROBLEM?
        └── sí ──► incidencia OPEN **sin clasificar**, que recoge el job de `maintenance`
        │
        ▼
una persona contesta                 POST /conversations/{id}/messages  { "content": "…" }
                                     → sender_type del rol, y si estaba PENDING_HUMAN
                                       contestar **es** tomar el mando (HUMAN_HANDLING)
        ▼
se cierra                            POST /conversations/{id}/resolve
                                     → RESOLVED, y cierra la escalación con ella
```

Todo el procesamiento de un mensaje entrante ocurre en **una sola transacción**: o queda todo
—mensaje, evento de timeline, estado de la conversación, notificación, incidencia— o no queda
nada. No hay estado intermedio que alguien tenga que reparar a mano.

## Qué escala, y por qué

Seis condiciones, **en este orden**. El orden importa porque no son excluyentes y lo que se
registra es la primera que casa, que es lo que un operador lee para decidir cómo responder:

| # | Razón | Cuándo |
|---|---|---|
| 1 | `EMERGENCY_KEYWORD` | el mensaje contiene una palabra clave de emergencia (fuego, humo, gas, sangre, ambulancia…, en español o en inglés) |
| 2 | `LOW_CONFIDENCE` | la confianza es **estrictamente menor** que `TenantConfig.ai_confidence_threshold` (0,75 por defecto) — **o** el intent es `UNKNOWN` |
| 3 | `EMERGENCY_INTENT` | el clasificador dice `EMERGENCY` |
| 4 | `REFUND_OR_COMPENSATION` | el huésped pide dinero |
| 5 | `IMMINENT_CHECKIN_ACCESS_PROBLEM` | `ACCESS_PROBLEM` a **menos de 2 h** del check-in de su reserva |
| 6 | `REPEATED_INTENT` | **más de 2** mensajes del huésped con el mismo intent sin que la conversación se haya resuelto |

La primera va primera porque **no depende del clasificador**: un modelo teniendo un mal día no
puede tapar un «hay humo». La segunda va antes que todas las que miran el intent porque, si el
veredicto no es de fiar, nada derivado de él lo es.

Hay una séptima razón que no decide *si contestar*: `DELIVERY_FAILED`, el estado en el que
queda una conversación cuya respuesta no se pudo entregar (ver «Cuando el envío falla»).

Y hay tres intents que **nunca** se contestan automáticamente —`REFUND_OR_COMPENSATION`,
`EMERGENCY` y `UNKNOWN`—: escalan, y el catálogo de plantillas ni siquiera tiene entrada para
ellos, así que un fallo de programación futuro produce un error ruidoso en vez de una promesa
que no debimos hacer.

**Dos notas que sorprenden y son deliberadas:**

- **Apagar la IA (`ai_enabled = false`) no apaga la escalación.** El mensaje se registra, se
  clasifica y sale en el timeline, no se contesta nada — y si hay una emergencia, el aviso
  sale igual. Apagar la IA apaga la respuesta automática, no la alarma.
- **Una vez escalada, la IA deja de contestar.** Mientras la conversación esté en
  `PENDING_HUMAN` o `HUMAN_HANDLING`, los mensajes siguientes se registran y se clasifican
  pero no reciben respuesta automática: si no fuera así, el huésped podría recibir la
  respuesta del manager y una plantilla contradiciéndola. Al resolver, la escalación se cierra
  y un mensaje posterior reabre la conversación con la IA activa otra vez — porque eso ya es
  otro problema.

## Las palabras clave de emergencia

`ASSUMPTION`: el PRD §13 pide una «lista **configurable** de palabras clave de emergencia», y
lo que hay hoy es una **constante versionada en el dominio** (`EMERGENCY_KEYWORDS_VERSION`),
por idioma, no una columna de `TenantConfig`. Configurarla por tenant exige una migración y una
UI de settings, que son de `hardening-release`; la constante es sustituible sin tocar el
pipeline, así que el día que haga falta se cambia sin rehacer nada.

Consecuencia práctica para un operador: **hoy no se pueden añadir palabras clave desde el
panel.** Si un tenant necesita una que no está, es un cambio de código.

Se buscan **por palabras enteras** sobre el texto sin acentos, y **en los dos idiomas a la
vez** independientemente del idioma detectado: alguien asustado escribe en el idioma que le
sale.

## Quién puede hacer qué

| | `TENANT_OWNER` | `PROPERTY_MANAGER` | `CLEANER` / `TECHNICIAN` |
|---|---|---|---|
| Ver la bandeja y los hilos | sí | sí | no |
| Abrir una conversación | no | sí | no |
| Escribir un mensaje | no | sí | no |
| Escalar / resolver | no | sí | no |

La propietaria **lee y no opera**, por simetría con reservas y propiedades y porque PRD §6 lo
dice así. La consecuencia práctica: en un tenant sin manager nadie puede contestar. Si eso
llega a estorbar, lo que cambia es una línea del catálogo de permisos y una del mapa
rol→`sender_type`.

**El cliente no puede decir quién escribió un mensaje.** El cuerpo de `POST /messages` admite
`sender_type` con **un único valor, `GUEST`**, que significa «estoy transcribiendo lo que dijo
el huésped». Omitirlo significa «esto lo escribo yo», y entonces el `sender_type` sale del rol
del token. Cualquier otro valor —`AI` incluido— es un 422.

## Los canales, y el que queda mudo

| Canal | Qué pasa al enviar |
|---|---|
| `MANUAL` | la fila **es** la entrega: se lee en el panel |
| `WHATSAPP` | mock a consola (`MockWhatsAppAdapter`), al teléfono del huésped |
| `EMAIL` | consola (`ConsoleEmailAdapter`), al correo del huésped |
| `PHONE_TRANSCRIPT` | no tiene salida: entra por transcripción, no sale |
| `AIRBNB_MSG`, `BOOKING_MSG` | **error 422, siempre** |

> **Una conversación creada a mano con `AIRBNB_MSG` o `BOOKING_MSG` queda muda, y es por
> diseño.** El canal se acepta al crearla porque el enum lo tiene, pero cualquier envío falla
> con un error nombrado. Esos dos canales sólo existen a través del PMS, y el puerto que los
> serviría (`PMSMessagingPort`) sigue **sin métodos** a propósito: su forma la decide el primer
> proveedor que la implemente, que llega con `beds24-messaging-adapter`. La alternativa —
> registrar un adaptador que no hace nada— enseñaría un mensaje «entregado» que el huésped
> nunca recibió, y eso es peor que un error.

Si el huésped no tiene teléfono (para WhatsApp) o correo (para email), el envío falla con
`INVALID_RECIPIENT` y la conversación escala. Es correcto: de verdad no podemos entregar.

## Cuando el envío falla

El mensaje **no se pierde**. Se guarda con su resultado dentro:

- `metadata.delivery_status = "FAILED"` y `metadata.delivery_error_code` con el código
  (`INVALID_RECIPIENT`, `CHANNEL_INBOUND_ONLY`, `ADAPTER_UNAVAILABLE`);
- la conversación escala con `EscalationReason.DELIVERY_FAILED`, así que una persona la ve;
- **no** se emite `AI_RESPONSE_SENT`, porque no se envió — y el timeline es de sólo añadir, así
  que un evento equivocado no se podría retirar después.

Nunca se guarda el cuerpo del error del proveedor, sólo el código: un SDK rutinariamente mete
en su excepción el mismo mensaje que no pudo enviar.

## Qué se guarda de lo que escribe la gente

Tres columnas de `messages` son texto o JSON libre, y las tres están en el censo de la regla 11
de `sdd/steering/security.md`, que es **el único sitio** donde vive ese contrato. En corto:

- **`content` del huésped**: se guarda tal cual. No lo componemos nosotros, así que va bajo la
  excepción 4 — acotado por tipo y por longitud, y nada más. `ASSUMPTION`: el tope son **4000
  caracteres**, un número elegido y no medido — WhatsApp admite 4096 y los límites reales de
  Beds24 no están medidos todavía. Se descartaron 2000 (corto para una transcripción
  telefónica) y 10000 (holgado para un sumidero de la regla 11 sin necesidad demostrada).
  `beds24-messaging-adapter` lo ajustará con datos; la constante se cambia sin tocar nada más.
- **`content` de una persona**: igual, bajo la excepción 3, con la diferencia tranquilizadora
  de que quien teclea está autenticado.
- **`content` nuestro** (la respuesta de la IA): es **literalmente** una de las 22 constantes
  del catálogo. No hay interpolación en ninguna plantilla, así que no hay sitio donde meter lo
  que dijo el huésped.
- **`intent`**: un miembro del enum; lo que no encaje se guarda como `UNKNOWN`.
- **`metadata`**: seis claves y ninguna más, todas identificadores o valores cerrados.

Y **no se propaga**: ni el contenido ni el intent llegan a `timeline_events` ni a
`audit_logs.changes`. La única copia que existe es a `incidents.description` cuando el mensaje
abre una incidencia, y va **verbatim**.

> **La advertencia simétrica**, la misma que llevan `guest-portal.md` y `maintenance.md`: lo
> que el huésped diga se le enseña al operador tal cual. Si dicta su número de documento por
> WhatsApp, ahí queda. No hay forma de estructurar una conversación, y pretender lo contrario
> sería una fila del censo que miente.

## Lo que la IA no puede decir

Las respuestas salen de un catálogo cerrado de 22 constantes (once intents × dos idiomas). Eso
es lo que hace verificable la regla 10 de `sdd/steering/security.md`: un catálogo sin huecos de
interpolación **no puede** prometer un reembolso, admitir responsabilidad, dar asesoría legal,
revelar datos de otro huésped, inventar un código, un precio o disponibilidad, ni decir que un
técnico va de camino.

Lo que sí puede decir es corto: que hemos recibido el mensaje y que alguien responderá. No hay
disculpas en el catálogo, a propósito — una disculpa roza el admitir responsabilidad.

**Lo que eso no cierra**, dicho claro: nada mecánico impide que una persona escriba mañana una
plantilla que sí diga alguna de esas cosas. Lo que hay es revisión, más un test que busca las
frases que un cambio bienintencionado usaría.

## Límites conocidos

- **El adaptador de IA es un mock** (`MockAIAdapter`), determinista y por palabras clave. Es
  `EXTERNAL_DEPENDENCY`: el proveedor real implementa el mismo puerto y se cambia en una línea
  del cableado. Cuando llegue, el pipeline es **síncrono** dentro de la petición y habrá que
  sacar la clasificación a un job, como hizo `maintenance`.
- **La detección de idioma es tosca**: marcadores por idioma sobre una lista cerrada. Un
  mensaje de tres palabras puede caer del lado equivocado. El daño está acotado: lo peor que
  pasa es contestar en inglés a quien escribió en español.
- **No hay ingesta automática desde OTA.** Los mensajes entran por el panel o por la API. La
  llegada desde Airbnb/Booking es `beds24-messaging-adapter`.
- **No hay adjuntos.** Sin canal real no hay adjunto que transportar.
- **No hay SLA de respuesta humana** tras una escalación: se emite la notificación
  `GUEST_ESCALATION` y ahí termina. La maquinaria de SLA es de `celery-jobs`.
- **La cuenta de mensajes repetidos no se reinicia al reabrir** una conversación resuelta:
  arrastra los anteriores, así que escala antes. `ASSUMPTION`, asumida y no descubierta: «sin
  resolución» significa **que la conversación no está hoy en un estado terminal**, no «desde la
  última vez que se resolvió», porque `Conversation` no tiene una marca de tiempo de resolución
  y dársela sería una migración que este change no hace. Se acepta porque la desviación va en
  la dirección segura — quien vuelve a sacar el mismo tema después de darlo por resuelto es
  justo a quien la IA está fallando. Contar por episodios exige esa marca de tiempo y un
  parámetro `since`, y los trae quien los necesite.
- **La bandeja no tiene índice** para su orden (`last_message_at DESC`). A la escala del MVP
  es irrelevante; se revisa cuando un tenant pase de unos pocos miles de conversaciones.
- **No hay frontend todavía**: la bandeja de `/conversations` es de `conversations-inbox`.
