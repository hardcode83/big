# Proposal: conversations-inbox

## Why

`messaging-ai` entregó el módulo completo de mensajería —pipeline del mensaje entrante,
`MockAIAdapter`, política de escalación de PRD §13 y los siete endpoints de bandeja
(`specs/messaging-ai.md` R7)— pero **nadie puede verlo desde la aplicación**. La ruta
`/conversations` que PRD §24 declara existe hoy como `RoutePlaceholder`: la capability que
sustituye la atención al huésped de MAGNO es, para la propietaria y el manager, invisible.

Este change es el punto 21 de PRD §26 (*«Frontend conversaciones»*) y cierra la última de las
cuatro superficies en que se partió `field-apps` el 2026-08-18. También es la única superficie
donde la IA del producto se ve funcionando: hasta ahora el escalado a humano solo se observa en
la suite de tests.

Origen: entrada `conversations-inbox` de `sdd/roadmap.md` (`needs: messaging-ai,
frontend-auth-session`, ambas cerradas; la entrada está en la frontera). PRD §26.21, §24, §13.

## What changes

Aparece la bandeja de conversaciones real en `/conversations`: una lista paginada y filtrable de
conversaciones del tenant y, junto a ella en la misma ruta, el hilo de la conversación
seleccionada en orden cronológico ascendente, distinguiendo visualmente quién escribió cada
mensaje (huésped / IA con su `confidence_score` e `intent` / manager / sistema). Desde el hilo, un
manager responde, transcribe un mensaje del huésped —lo que dispara el pipeline de IA— escala a
humano y resuelve; la propietaria ve exactamente lo mismo en modo lectura, porque
`MANAGE_CONVERSATIONS` es solo del manager (`messaging-ai` D17).

Es un change **solo de frontend**: consume los siete endpoints ya publicados a través del
`ApiClient` tipado y del patrón de frontera que estableció `dashboard-web-frontend`
(`ConversationsDataSource` + implementación HTTP + mapeo explícito `snake_case` → DTO
`camelCase`), sin tocar backend, contrato OpenAPI ni sus dos artefactos generados.

## Requirements

### R1 — Lista de conversaciones

**Como** manager o propietaria, **quiero** ver todas las conversaciones del tenant ordenadas por
actividad, **para** saber en un vistazo qué hilo pide mi atención.

Criterios de aceptación:

1. WHEN una persona autenticada abre `/conversations`, THE SYSTEM SHALL llamar a
   `GET /api/v1/conversations` a través del `ApiClient` compartido y renderizar una fila por
   conversación devuelta, en el orden que devuelve el backend, **sin reordenar en el cliente**.
2. WHEN se renderiza una fila, THE SYSTEM SHALL mostrar el código interno de la propiedad, el
   canal, el `status`, el `escalation_status`, el idioma y la antigüedad de `last_message_at`
   localizada.
3. IF `last_message_at` es `null`, THEN THE SYSTEM SHALL mostrar un texto localizado de «sin
   mensajes» en su lugar y NEVER SHALL mostrar una fecha inventada ni una cadena vacía.
4. WHILE la consulta de la lista está pendiente, THE SYSTEM SHALL renderizar el estado de carga
   compartido (`aria-busy`); IF falla, THEN THE SYSTEM SHALL renderizar el estado de error
   compartido (`role="alert"`) con un reintento que re-ejecuta la consulta, sin exponer detalle
   crudo del error.
5. IF el backend devuelve cero conversaciones, THEN THE SYSTEM SHALL renderizar el estado vacío
   compartido, visualmente distinto del de error y del de carga.
6. WHEN el total excede una página, THE SYSTEM SHALL ofrecer navegación de páginas usando
   `page`/`per_page` y los metadatos `total`/`page`/`per_page` de `ConversationPageResponse`, y
   NEVER SHALL acumular páginas en el cliente como si fueran una sola lista.
7. THE SYSTEM SHALL resolver el nombre y el código de cada propiedad mediante
   `GET /api/v1/properties`, en **una sola consulta cacheada** para toda la lista, y IF una
   `property_id` no aparece en esa respuesta THEN THE SYSTEM SHALL mostrar un marcador localizado
   en vez del código, sin romper la fila.

### R2 — Filtros de bandeja

**Como** manager, **quiero** filtrar la bandeja por estado, escalación y propiedad, **para**
atacar primero lo que está escalado.

Criterios de aceptación:

1. THE SYSTEM SHALL ofrecer filtros por `status`, `escalation_status` y `property_id`, y SHALL
   serializarlos como los parámetros de query que `GET /api/v1/conversations` declara,
   **omitiendo** los no seleccionados.
2. THE SYSTEM SHALL restringir los valores ofrecidos a los del contrato generado —
   `ConversationStatus` y `ConversationEscalationStatus` — de forma exhaustiva sobre la unión, de
   modo que un valor nuevo en el backend no se pierda en silencio.
3. WHERE `status = CLOSED` se ofrece como filtro, THE SYSTEM SHALL acompañarlo de una nota
   localizada de que hoy nada produce ese estado —`CLOSED` aparece como origen y nunca como
   destino en `_STATUS_TRANSITIONS`, y ninguna ruta lo escribe—, para que una lista siempre vacía
   no se lea como un fallo. NEVER SHALL poner esa nota en `escalation_status = HUMAN_HANDLING`,
   que **sí** es alcanzable: responder a un hilo en `PENDING_HUMAN` ejecuta `take_over`
   (`RecordHumanReplyUseCase`), así que ese filtro devuelve resultados reales.
4. WHEN cambian los filtros o la página, THE SYSTEM SHALL incluirlos en la clave de TanStack
   Query con ámbito de tenant (`['tenant', tenantId, …]`), de modo que cada combinación se
   cachee por separado.
5. THE SYSTEM SHALL guardar la selección de filtros como estado ligero de UI en Zustand y NEVER
   SHALL almacenar ahí las conversaciones ni los mensajes (server state).

### R3 — Hilo de la conversación

**Como** manager o propietaria, **quiero** leer el hilo completo con el huésped, **para** entender
qué pasó antes de contestar.

Criterios de aceptación:

1. WHEN una persona selecciona una conversación de la lista, THE SYSTEM SHALL mostrar su hilo en
   la misma ruta `/conversations` junto a la lista, y SHALL reflejar la conversación seleccionada
   en la URL (query string) para que el hilo sea enlazable y recargable.
2. WHEN se abre un hilo, THE SYSTEM SHALL llamar a `GET /api/v1/conversations/{id}` y a
   `GET /api/v1/conversations/{id}/messages` y SHALL renderizar los mensajes en el orden
   cronológico ascendente que devuelve el backend, sin reordenar en el cliente.
3. WHEN se renderiza un mensaje, THE SYSTEM SHALL distinguir su `sender_type` de forma
   exhaustiva sobre los cinco valores de `MessageSenderType` (`GUEST`, `OWNER`, `MANAGER`, `AI`,
   `SYSTEM`), con etiqueta localizada y alineación distinta para el huésped y para nosotros.
4. WHERE `ai_generated` es verdadero, THE SYSTEM SHALL marcar el mensaje como generado por IA y
   SHALL mostrar su `intent` y su `confidence_score`; IF `confidence_score` es `null`, THEN SHALL
   omitir la cifra sin renderizar `null` ni `NaN`. THE SYSTEM SHALL leer `confidence_score` como
   la **cadena decimal** que el contrato declara y NEVER SHALL redondearla antes de formatearla.
5. WHEN el hilo excede una página de mensajes, THE SYSTEM SHALL permitir cargar las anteriores
   con `page`/`per_page`, conservando el orden ascendente.
6. IF `GET /api/v1/conversations/{id}` responde 404, THEN THE SYSTEM SHALL renderizar un estado
   localizado de «no encontrada» dentro del chrome de la shell y NEVER SHALL reintentar la
   consulta (política de no reintento en 4xx).
7. THE SYSTEM SHALL mostrar el idioma detectado del hilo y su canal, y WHERE el canal es
   `AIRBNB_MSG` o `BOOKING_MSG` THE SYSTEM SHALL advertir con texto localizado de que ese hilo
   es **mudo por diseño** hasta `beds24-messaging-adapter` (`messaging-ai` R6.3), antes de que
   alguien escriba una respuesta que no se va a entregar.

### R4 — Responder y transcribir

**Como** manager, **quiero** contestar al huésped y transcribir lo que me dijo por teléfono,
**para** cerrar el soporte de primer nivel desde un único sitio.

Criterios de aceptación:

1. WHEN un manager envía el compositor de respuesta, THE SYSTEM SHALL llamar a
   `POST /api/v1/conversations/{id}/messages` **sin** `sender_type`, dejando que el backend derive
   el remitente de su rol.
2. THE SYSTEM SHALL ofrecer una acción **separada y etiquetada sin ambigüedad** para transcribir
   un mensaje del huésped, que llama al mismo endpoint con `sender_type: "GUEST"`, y SHALL
   advertir en su texto localizado de que eso dispara la respuesta automática de la IA y puede
   escalar la conversación. THE SYSTEM SHALL NOT permitir enviar un mensaje de huésped desde el
   compositor de respuesta ni por defecto.
3. THE SYSTEM SHALL limitar el contenido a los 4000 caracteres que declara `CreateMessageRequest`
   y SHALL impedir el envío de contenido vacío, mostrando el límite antes de que el backend
   responda 422.
4. WHEN un envío tiene éxito, THE SYSTEM SHALL invalidar las consultas del hilo, de la
   conversación y de la lista, de modo que la respuesta de la IA y el nuevo `status`/
   `escalation_status` aparezcan sin recargar la página.
5. WHILE un envío está en curso, THE SYSTEM SHALL deshabilitar el compositor e impedir un segundo
   envío del mismo texto; IF falla, THEN THE SYSTEM SHALL mostrar un error localizado derivado del
   `ApiError` **conservando el texto escrito**, y NEVER SHALL mostrar el mensaje como enviado.

### R5 — Escalar y resolver

**Como** manager, **quiero** escalar una conversación a humano y marcarla resuelta, **para** que
ningún huésped se quede esperando y la bandeja refleje lo que ya está cerrado.

Criterios de aceptación:

1. WHEN un manager escala un hilo, THE SYSTEM SHALL llamar a
   `POST /api/v1/conversations/{id}/escalate`, y WHEN lo resuelve, a
   `POST /api/v1/conversations/{id}/resolve`, y SHALL reflejar en la UI el
   `ConversationResponse` devuelto.
2. THE SYSTEM SHALL ofrecer cada acción solo cuando la transición es válida según las tablas de
   `messaging-ai` R5 —escalar solo con `escalation_status = NONE`, resolver solo con
   `status ∈ {OPEN, ESCALATED}`— y IF el backend la rechaza igualmente (409 sobre una
   conversación ya escalada) THEN THE SYSTEM SHALL mostrar un error localizado y refrescar el
   estado real, NEVER SHALL dejar la UI mostrando el resultado que no ocurrió.
3. WHEN una acción tiene éxito, THE SYSTEM SHALL invalidar la lista y el hilo, de modo que las
   insignias de estado y el orden de la bandeja se actualicen.
4. THE SYSTEM SHALL requerir confirmación antes de resolver, y NEVER SHALL resolver por un solo
   click accidental.

### R6 — Lo que ve la propietaria (RBAC solo oculta)

**Como** propietaria, **quiero** leer la bandeja sin poder operarla, **para** enterarme sin
romper nada — y **como** equipo, **queremos** que la autoridad siga siendo del backend.

Criterios de aceptación:

1. WHERE el rol de la sesión no tiene `MANAGE_CONVERSATIONS` —hoy todos salvo
   `PROPERTY_MANAGER`— THE SYSTEM SHALL ocultar el compositor, la transcripción y las acciones de
   escalar y resolver, dejando lista e hilo legibles.
2. THE SYSTEM SHALL derivar esa decisión del rol que expone `GET /api/v1/auth/me` y SHALL
   tratarla como **UX y no como autorización**: NEVER SHALL implementar RBAC ni aislamiento de
   tenant en el frontend, y el backend sigue decidiendo (`steering/frontend.md`,
   `specs/frontend-auth-session.md`).
3. IF el backend responde 403 a una acción que la UI mostró, THEN THE SYSTEM SHALL mostrar un
   error localizado de permisos y NEVER SHALL interpretarlo como un fallo de red que reintentar.

### R7 — Frontera de datos, i18n y calidad

**Como** equipo, **queremos** que esta superficie siga el patrón que ya estableció el dashboard,
**para** que no estrene una tercera forma de hablar con el backend.

Criterios de aceptación:

1. THE SYSTEM SHALL definir una interfaz tipada `ConversationsDataSource` cuyos métodos devuelven
   DTOs de la feature, con una única implementación HTTP sobre el `ApiClient` compartido,
   resuelta en **un solo punto de composición**.
2. THE SYSTEM SHALL mapear explícitamente los campos `snake_case` del contrato generado a DTOs
   `camelCase`, preservando los `null` y las cadenas ISO-8601, y NEVER SHALL construir clientes
   por endpoint ni tipos de error por endpoint (`specs/frontend-api-contract-consumer.md`).
3. THE SYSTEM SHALL mantener componentes y hooks dependientes solo de la interfaz y del punto de
   composición, verificado por un test de frontera; cualquier fixture de test SHALL quedar
   aislada y sin importarse desde runtime.
4. WHEN se renderiza cualquier string visible de esta superficie, THE SYSTEM SHALL resolverlo por
   react-i18next en un namespace `conversations` **registrado en `lib/i18n/resources.ts` y
   presente en `locales/es` y `locales/en`**; IF falta una clave en cualquiera de los dos, THEN el
   test de paridad SHALL fallar. Los valores dinámicos del backend (contenido del mensaje,
   `intent`, canal) se renderizan como dato.
5. WHEN el frontend se verifica, THE SYSTEM SHALL pasar type-check, lint, la suite colocada y un
   build de producción **sin backend corriendo**.
6. THE SYSTEM SHALL ser usable en móvil colapsando a una sola columna (lista → hilo, con vuelta
   atrás) sin desbordamiento horizontal, y navegable por teclado con foco visible y nombres
   accesibles localizados.

## Out of scope

- **`take_over` y `reopen` como acciones explícitas**: ninguna de las siete rutas las expone como
  operación propia, así que la bandeja no ofrece un botón para ellas. Lo que **no** es cierto —y
  este proposal lo afirmó antes de que `/sdd:design` leyera el código— es que sus estados sean
  inalcanzables: `RecordHumanReplyUseCase` llama a `take_over` cuando un manager responde a un hilo
  en `PENDING_HUMAN` («answering *is* taking over»), y el paso 1 del pipeline reabre un hilo
  `RESOLVED` cuando se transcribe un mensaje de huésped. Las dos transiciones ocurren, como efecto
  de responder y de transcribir, y `HUMAN_HANDLING` es un estado con filas reales. El valor que de
  verdad no tiene escritor es `ConversationStatus.CLOSED` (R2.3).
- **Nombre del huésped y preview del último mensaje en la lista**: `ConversationResponse` trae
  `guest_id` pero no nombre, y **no existe `GET /api/v1/guests/{id}`** —solo el sub-recurso
  `/document`, cerrado por PII—; `ReservationResponse` tampoco trae nombre. Un preview exigiría un
  `GET /messages` por fila (N+1). Ambas cosas piden una proyección de bandeja en el backend, no un
  apaño en el cliente. Misma entrada de roadmap.
- **Contador de no leídos**: no hay nada en el modelo que lo soporte (ni `read_at` ni marca por
  usuario). Requiere migración; fuera de una superficie de lectura.
- **Tiempo real (WebSocket/SSE)**: sigue ausente en ambos lados, igual que en
  `dashboard-web-frontend`. La bandeja se actualiza por invalidación tras las mutaciones y por
  recarga manual; no se añade polling.
- **Crear conversación desde la UI** (`POST /api/v1/conversations`): la bandeja atiende hilos que
  ya existen. Abrir uno nuevo es una acción de contacto proactivo que no está en PRD §24 y cuyo
  destinatario no es resoluble sin nombre de huésped.
- **Configurar el catálogo de plantillas, el umbral de confianza o las palabras clave de
  emergencia**: es `hardening-release` (`/settings`), como ya declaró `messaging-ai`.
- **Superficie móvil propia** (una ruta tipo `/cleaner` o `/tech`) y **roles nuevos**: la entrada
  del roadmap lo excluye explícitamente. `/conversations` es responsive, no una app aparte.
- **Backend, contrato OpenAPI y sus dos artefactos generados**: este change no los toca, así que
  no genera tareas de `make openapi` ni de `npm run api:generate`.

## Registro en el roadmap

Al aprobar este proposal se propondrá añadir una entrada de roadmap **`messaging-inbox-projection`**
(`[BE]`, `size: S`, `kind: tech`) que enriquezca la proyección de la lista con lo que una bandeja
necesita para identificar un hilo: nombre de huésped y preview del último mensaje sin un `GET`
por fila. No es un pre-requisito de este change —la bandeja funciona sin ella— sino la deuda que
este change **descubre y documenta** en vez de tapar.

**Su alcance se redujo en el gate de `/sdd:design` (2026-08-19)**: la redacción anterior le
encargaba además exponer `take_over` y `reopen` como rutas, sobre la premisa de que sus estados
eran inalcanzables. El código dice lo contrario (ver *Out of scope*), así que eso deja de ser deuda
descubierta y pasa a ser, si acaso, una comodidad de API que nadie ha pedido.

## Affected specs

- `docs/conversations-inbox.md` — *(no existe aún — se creará al archivar)*: la página de
  capability que `sdd/steering/documentation.md` exige para una superficie nueva de cara a
  usuario/operación, orientada a **cómo se usa**: qué ve la propietaria frente al manager, el
  recorrido de responder / transcribir / escalar / resolver, qué significan los dos ejes de
  estado en las insignias, y las dos advertencias de canal mudo con su diferencia (se guarda y
  no se envía, frente a se pierde entera). **Registrado en `/sdd:review` del 2026-08-21**: la
  obligación no estaba en ningún artefacto, así que `/sdd:archive` no tenía de dónde deducirla.
- `sdd/specs/conversations-inbox.md` — *(no existe aún — se creará al archivar)*: el
  comportamiento de esta superficie.
- `sdd/specs/messaging-ai.md` — se anotará que su R7 tiene por fin un consumidor; que el hueco de
  la proyección de bandeja (sin nombre de huésped ni preview) queda **divulgado** aquí y no
  cerrado; y que `take_over` y `reopen` **sí ocurren** aunque no tengan ruta propia — como efecto
  de responder y de transcribir—, de modo que `HUMAN_HANDLING` es alcanzable y el único valor sin
  escritor es `ConversationStatus.CLOSED`.
- `sdd/specs/frontend-foundation.md` — la ruta `/conversations` deja de ser `RoutePlaceholder`. Y con ello **su regla «ninguna `page.tsx` importa `Suspense` ni `LoadingState`»** (`app/error-architecture.test.ts`, «no ceremonial loading/Suspense on placeholders») deja de ser absoluta: se escribió para placeholders, y una ruta real que lee `useSearchParams()` necesita la frontera para acotar al subárbol el abandono de prerender (D5, R7.5) —**no** para que `next build` pase, como esta frase afirmaba antes de `/sdd:review` del 2026-08-21: la i18n de servidor ya hace dinámicas las 24 rutas y el build compila igual sin frontera—. El test pasa a llevar lista de exenciones con motivo, y la spec necesita el mismo matiz.
- `sdd/specs/frontend-api-contract-consumer.md` — su afirmación «mantener el dashboard y el shell
  sin llamadas funcionales al backend real» necesita el mismo matiz que ya recibió con
  `dashboard-web-frontend`: aparece un segundo consumidor real del contrato.
- `docs/messaging-ai.md` — **corrección de un hecho falso, descubierta en `/sdd:run` (panel de
  las secciones 2-3, 2026-08-19)**. Su tabla de canales dice de `AIRBNB_MSG` y `BOOKING_MSG`
  «**error 422, siempre**», y el párrafo siguiente que «cualquier envío falla con un error
  nombrado». Es falso para la vía de responder, que es la que un manager usa: verificado en
  `backend/app/messaging/application/use_cases.py`, `RecordHumanReplyUseCase` **no toca ningún
  `OutboundMessagePort`**, así que el mensaje se persiste con 201 y nunca se entrega, sin error
  alguno. El 422 es real solo en la vía de transcribir, cuando el pipeline llega a `_reply` y no
  encuentra adapter (D13). La copia de esta bandeja ya dice la verdad («se guarda, no se envía»),
  así que dejar el doc como está deja dos afirmaciones incompatibles en el árbol. Se corrige la
  fila y el párrafo al archivar; no se toca en `/sdd:run`, donde el diff es solo de frontend
  (tarea 9.5).
