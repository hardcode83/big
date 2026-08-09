# Design: reservations-webhooks

## Context

La tabla ya existe y **nadie escribe en ella todavía**: `WebhookEventModel`
(`backend/app/integrations/infrastructure/models.py:34-79`) es la única del esquema con
`tenant_id` nullable, deja escrito en su docstring que este change hereda el contrato de la
regla 11 para `payload`/`error`, y que la cola debe leerse desde una **sesión nunca marcada** —
fijado por `tests/test_tenant_filter.py::test_webhook_events_without_a_tenant_are_invisible_to_a_marked_session`.

Lo que ya está construido y este change **reutiliza en vez de reinventar**:

- `ReservationIngestor` (`backend/app/integrations/application/ingest.py:102`) — única ruta de
  upsert, idempotente por `(tenant_id, external_pms_id)`, y con la política de "una fila mala no
  cuesta las buenas" ya resuelta como `RowError` en vez de excepción.
- `scrub_card_data` (`backend/app/integrations/infrastructure/card_data.py`) — el descarte de
  datos de tarjeta de la regla 13, con tope de profundidad, ramas opacas y la lista de agujas
  fijada por test contra `scripts/anonymise.py`.
- El motor de jobs: `app/scheduler/{schedule,tasks,runner,locks}.py`. `CADENCES` es fuente única
  (el `beat_schedule` se deriva de ella y `lock_ttl_for` dimensiona el lock desde los mismos
  números), `run_for_every_tenant` abre **una sesión marcada por tenant, nunca re-marcada**, y
  `worker_redis`/`worker_session_factory` resuelven el problema de bucle de eventos por ejecución.
- Cripto y credenciales: `app/core/crypto.py`, `app/core/encrypted_secret.py` (`EncryptedSecret`
  rechaza por construcción cualquier cosa que no sea ciphertext Fernet) y el precedente de
  `PmsCredentialModel` (`models.py:85-156`), con su índice parcial y su `CheckConstraint`.
- Limitación de tasa: `RedisLoginThrottle` + `settings.login_rate_limit_per_minute`
  (`app/auth/api/dependencies.py:141`), el patrón de throttle que ya existe en el repo.
- Auditoría: `AuditLogFactory.build` (`app/audit/domain/services.py:25`) con **vocabulario
  cerrado** en `app/audit/domain/actions.py` — añadir acciones nuevas es obligatorio, no opcional.

Y una medición que corrige a ADR 0006 y hay que respetar: `specs/pms-beds24-spike.md` dice que en
Beds24 **los webhooks se configuran por API**, que **solo se disparan para reservas de canal** (así
que esta capacidad no se valida de extremo a extremo sin canales conectados) y que el techo de cuota
es un ciclo de sync por cuenta cada 30 s.

## Decisions

### D1 — La ruta lleva el token, y el token resuelve el tenant

**Chosen:** `POST /api/v1/webhooks/{provider}/{webhook_token}` en un router nuevo
`backend/app/integrations/api/webhooks_router.py`, registrado en `main.py` junto a los demás.
`{provider}` se valida contra el enum `PMSProvider`; `{webhook_token}` se busca por hash en la
tabla de D2 y **es lo que resuelve el `tenant_id`**. Es la forma que exige la regla 12(b) y la
cuarta desviación registrada en ADR 0006 frente a PRD §23.

La petición **no lleva JWT**, así que su sesión nunca se marca: el endpoint filtra por `tenant_id`
explícito, igual que ya hacen el login anónimo y el worker. No se marca la sesión ni después de
resolver el tenant — `bind_session_to_tenant` es de un solo sentido y marcar a mitad de petición
crea justo la sesión medio-marcada que el guard existe para impedir.

Rejected: mantener `POST /api/v1/webhooks/{provider}` de PRD §23 — globalmente adivinable, deja el
secreto de cabecera como única defensa. Rejected: el token en cabecera y no en la ruta — 12(a) y
12(b) están pensadas para sostenerse mutuamente, y con ambos secretos en cabeceras un solo volcado
de cabeceras los pierde los dos.

**Coste declarado de poner el token en la ruta: se registra en cada log de peticiones que haya
delante.** Un path es lo único de una petición que todo servidor, proxy y agregador guarda por
defecto, así que la no-adivinabilidad de 12(b) convive con que el valor quede escrito en sitios que
no elegimos. Dentro del proceso está cerrado —`app/core/log_redaction.py` redacta el segmento en el
log de acceso de uvicorn, y el limitador usa el hash para no convertirlo en clave de Redis—, pero
**fuera no**: [ADR 0003](../../../docs/adr/0003-https-ingress-dev.md) pone un túnel de Cloudflare
por delante, y Cloudflare registra el URI completo en sus propios logs. Quien tenga acceso a esa
cuenta ve el token vivo de todos los tenants. Lo destapó el re-review de seguridad de la sección 2.

**Resuelto por Jose el 2026-08-08: aceptado en dev, con condición para prod.** Hoy el entorno es de
una sola persona y los datos son suyos, así que la exposición es a su propia cuenta de Cloudflare;
y el material es rotable, que es la mitigación que ya existe. **La Transform Rule que redacte
`/api/v1/webhooks/*` en los logs del borde es requisito antes de que entre el primer tenant real**,
no una tarea opcional: en cuanto haya un segundo cliente, «visible para quien administra el túnel»
deja de significar «visible para su dueño». No se mueve el token fuera de la ruta — eso devuelve el
problema a la regla 12(b), que es más caro que el que resuelve.

### D2 — Tabla propia `webhook_endpoints`, no columnas en `pms_credentials`

**Chosen:** tabla nueva en el módulo `integrations`, con `TenantScopedMixin` (entra en
`tenant_scoped_classes()` y en el filtro global) y `UNIQUE(tenant_id, provider)`.

La dirección de la confianza es la **opuesta** a la de `pms_credentials`: ahí guardamos un secreto
que el proveedor nos dio, aquí uno que **nosotros acuñamos para que él nos autentique**. De eso
depende la única excepción de la regla 3(a) —devolverlo una vez— que precisamente *no* aplica a las
credenciales del proveedor; meterlos en la misma tabla pondría dos contratos de exposición en la
misma columna. Y el modelo de `scope` de `pms_credentials` (PROPERTY/ACCOUNT/ORGANIZATION, con su
`CheckConstraint` y su índice parcial) no dice nada aquí: la regla 12(a) fija la granularidad en
**por tenant**.

Rejected: columnas en `pms_credentials` — mezcla las dos direcciones de confianza en un contrato de
exposición. Rejected: un blob en `TenantConfig` — una credencial sin fila propia no tiene `entity_id`
que auditar (el mismo argumento mecánico que ya decidió `PmsCredentialModel`) ni test de aislamiento
propio, que la regla 3(c) exige.

### D3 — El token se guarda **hasheado**; el secreto de cabecera, cifrado con Fernet

**Chosen:** dos materiales distintos con dos tratamientos distintos, y la asimetría es deliberada.

- `token_hash`: SHA-256 **sin sal** del token, con índice `UNIQUE`. Sin sal a propósito, y no es un
  descuido: la búsqueda tiene que ser O(1) por índice, y con 256 bits de entropía aleatoria
  (`secrets.token_urlsafe(32)`) no hay diccionario que atacar — lo que hace peligroso un hash rápido
  es la baja entropía del secreto, no la velocidad del hash. Un bcrypt con sal sería además
  **imposible de indexar**.
- `header_secret_encrypted`: ciphertext Fernet vía `EncryptedSecret`, porque la regla 3 es vinculante
  y nombra explícitamente este secreto ("el de la regla 12(a), que un operador debe copiar al panel
  del proveedor"). Se descifra y se compara con `hmac.compare_digest` (regla 12(a): tiempo constante).

Consecuencia operativa, y hay que decirla: **los dos se entregan una sola vez**, al crearlos y en cada
rotación (excepción acotada de la regla 3(a)). Perder la URL no se resuelve consultándola; se resuelve
rotando. Es la postura de una API key, y es la única compatible con 3(a).

**Qué hace exactamente la rotación (R2.4):** sobrescribe `token_hash` y `header_secret_encrypted` en
**una sola transacción**, sin ventana de gracia y sin conservar el valor anterior en ninguna parte. El
material viejo deja de autenticar en cuanto la transacción hace commit. El coste operativo es real y hay
que decirlo: entre la rotación y la actualización del panel del proveedor, sus webhooks reciben `404` y
se pierden — recuperarlos es el sondeo de `pms_sync`, que sigue existiendo. Por eso la rotación es una
operación deliberada de un humano con RBAC, nunca automática ni programada.

Rejected: dos secretos válidos a la vez durante una ventana de gracia — dobla la superficie justo en el
mecanismo cuya única defensa es el secreto, para ahorrar una pérdida de avisos que el sondeo ya cubre.
Rejected: token en claro en la base de datos — un volcado de la tabla entrega la ruta, y entonces 12(b)
deja de ser una defensa independiente de 12(a). Rejected: guardar el secreto de cabecera solo hasheado
(mejor en reposo, porque nada reversible queda) — la regla 3 es vinculante y manda Fernet; desviarse
habría que declararlo, y aquí no hace falta nada que Fernet no dé.

### D4 — Todo fallo de autenticación responde lo mismo: `404`

**Chosen:** provider desconocido, token que no existe y cabecera ausente o incorrecta devuelven el
**mismo** `404` con el mismo cuerpo del envelope de PRD §23. Un `401` distinguible convertiría el
endpoint en un oráculo de "este token existe".

**Fuga residual declarada, en vez de tapada con teatro:** la búsqueda del token es un acierto/fallo de
índice y su latencia difiere. No se compensa con una comparación falsa de relleno porque eso no
iguala el camino, solo lo alarga. No es explotable para *recuperar* un token de 256 bits: el oráculo
solo responde sobre un candidato que ya haya que adivinar. Donde una fuga byte a byte **sí** es
explotable es en la comparación del secreto, y ahí es donde la regla 12(a) pone el tiempo constante
(D3).

Rejected: `401` con `WWW-Authenticate` — correcto en HTTP y un oráculo en la práctica.

### D5 — El orden de las comprobaciones es la defensa: cabeceras antes que cuerpo

> **Corregido al implementar (tarea 1.2→2.2).** La primera redacción ponía el tope de cuerpo *dentro*
> del orden del endpoint, después de la autenticación, y describía un mecanismo a construir
> (`Content-Length` primero, contador sobre el stream si falta). Las dos cosas estaban equivocadas: ese
> mecanismo **ya existe** —`MaxBodySizeMiddleware` en `app/core/http_limits.py:82`, del change
> `api-ingress-routing` (D11)— y no está después de la autenticación sino **antes del enrutado**, que es
> estrictamente mejor. Hace ya exactamente lo que este diseño pedía: comprueba `Content-Length` con
> `.isdigit()` (así un valor negativo o no numérico no es una vía de escape, cae al conteo), cuenta los
> bytes del stream cuando no viene declarado, y es ASGI puro para no materializar el cuerpo. Y ya cubre
> `/api/v1/` **entero**, con un test de regresión que falla si alguien estrecha los prefijos
> (`tests/test_request_body_ceiling.py`).

**Chosen:** el tope de cuerpo **no es una decisión de este change**. `/api/v1/webhooks/…` cae por
construcción en la rama `else settings.request_max_bytes` (1 MiB) del proveedor por path de
`app/main.py:115-121`, y el rechazo ocurre antes de que exista una ruta, un dependency o una sesión. Así
que R3.2 y R1.7 se cumplen **por reutilización**, y lo único que aporta este change es el test que lo
demuestra sobre la ruta nueva.

**Y no se añade `WEBHOOK_MAX_BODY_BYTES`.** 1 MiB es holgado para un aviso de reserva, y una tercera
perilla junto a `REQUEST_MAX_BYTES` y `CSV_IMPORT_MAX_BYTES` sería una que nadie ajusta y un segundo
sitio donde vive el mismo hecho. Si algún proveedor resulta mandar cuerpos mayores, la reparación es una
rama más en ese proveedor por path — que es la capacidad que `cleaning` ya dejó pagada.

Lo que sí ordena este change, entonces, es sólo la parte que le pertenece: provider → límite de tasa por
IP → token → secreto de cabecera → parseo. La autenticación de R1 vive **entera en la ruta y las
cabeceras**, así que se resuelve sin tocar el cuerpo.

**Quién decide qué, porque "entera en la ruta y las cabeceras" describe de dónde salen los datos, no qué
capa manda** (aclarado tras el panel: `backend.md` línea 17 y la regla de dependencia de
`backend-architecture.md` hacen esto vinculante, y sin decirlo la autenticación acabaría en el router):

- `webhooks_router.py` es **fino**: resuelve las preocupaciones de transporte como dependencias de
  FastAPI —límite de tasa y tope de cuerpo, que son legítimamente de `api/`— y traduce la excepción del
  dominio al `404`/`429`/`413`. Nada más.
- El caso de uso de `application/webhooks.py` **decide**: resuelve el token, compara el secreto en tiempo
  constante, descarta los datos de tarjeta y persiste. La regla de la regla 12(a)-(b) es de negocio y
  vive ahí, con su test sin FastAPI de por medio.

Rejected: `Content-Length` como única comprobación — es un dato del cliente y opcional. Rejected: la
decisión de autenticación en el router — es exactamente la lógica que `backend.md` prohíbe alojar ahí, y
la volvería testeable sólo a través de HTTP.

### D6 — Dos límites de tasa con propósitos distintos

**Chosen:** un limitador Redis nuevo en `integrations`, con el patrón de `RedisLoginThrottle` pero sin
reutilizar su clase (su vocabulario es de intentos de login y bloqueo de cuenta):

- **Por token**, generoso (`webhook_rate_limit_per_minute`, default 120): protege la tabla del tráfico
  legítimo desbocado de un proveedor.
- **Por IP, y solo para peticiones que fallan la autenticación** (`webhook_probe_limit_per_minute`,
  default 20): es lo que hace que sondear tokens cueste (R3.4).

La distinción importa y es la razón de que no haya un único límite por IP: un proveedor envía desde
pocas IPs para **muchos** tenants, así que un límite por IP sobre el tráfico bueno estrangularía a
todos los tenants a la vez.

Rejected: una librería de rate limiting — dependencia nueva para algo que el módulo `auth` ya modela.
Rejected: un solo límite por IP — penaliza al proveedor legítimo, que es el patrón de tráfico normal.

> **Corregido en parte al implementar, y con una premisa falsada que sigue abierta** (panel de
> seguridad de la sección 2).
>
> **Lo que se arregló**: el contador por token se cargaba **antes** de autenticar, así que
> cualquiera con sólo el token de ruta —la mitad del par que viaja en una URL— podía gastar el
> presupuesto de un tenant y dejar su integración en `429` indefinidamente. Eso invierte el
> propósito del límite: existe para contener el tráfico desbocado de un proveedor, no para ser un
> arma que un tercero apunta al tenant. Ahora se cobra **después** de autenticar, y el fallo se
> cobra al presupuesto por IP.
>
> **Lo que NO se arregló, porque es una decisión de diseño**: esta decisión afirma que el límite
> por IP no estrangula al proveedor legítimo porque «sólo cuenta los fallos» y un proveedor
> legítimo no falla. **Eso es falso, y lo falsa este mismo change**: R2 entrega rotación, y entre
> rotar y actualizar el panel del proveedor sus entregas fallan. 20 fallos en un minuto desde la
> IP compartida del proveedor bloquean a **todos** los tenants que hay detrás — el estrangulamiento
> multi-tenant que esta decisión dice evitar, provocado por un tenant cualquiera con configuración
> obsoleta. La salida naïve —no contar los fallos cuyo token sí resuelve— reintroduce el oráculo de
> D4, porque *no* ser estrangulado confirma que el token existe.
>
> **Resuelto por Jose el 2026-08-08: se acepta y se documenta, con disparador.** El límite se queda
> como está. Con la cartera actual no se alcanzan 20 fallos por minuto ni de lejos: los webhooks se
> disparan por evento de reserva, y hacen falta 20 entregas fallidas **en el mismo minuto y desde la
> misma IP** para que muerda. Es un problema de escala, no de corrección.
>
> **La reparación cuando muerda es la allowlist de IPs de egreso del proveedor**, exentas del
> presupuesto de sondeo: cierra el caso sin tocar D4, y su coste es configuración operativa que hoy
> no se rentabiliza. **Disparador acordado**, para que esto no sea un «algún día»: el corte de 25-50
> unidades que [ADR 0006](../../../docs/adr/0006-pms-channel-manager-provider.md) ya tiene marcado
> para la migración a Channex, o antes si una rotación llega a provocar un `429` cruzado — lo que
> ocurra primero. Descartadas: el presupuesto por `(IP, token)`, que se lo regala a quien adivina
> porque cada intento estrena presupuesto; y hacer el `429` indistinguible del `404`, que cierra el
> oráculo pero hace que un proveedor legítimo estrangulado pierda entregas en silencio.

### D7 — `scrub_card_data` en la frontera, reutilizado tal cual

**Chosen:** el cuerpo parseado pasa por `scrub_card_data` **antes** de construir el `WebhookEvent`, y
lo que se persiste en `payload` es su salida. No se re-litiga la decisión D9 de `pms-beds24-adapter`
(denylist en vez de allowlist, aprobada por Jose): se reutiliza la función, con su tope de profundidad
y sus ramas opacas, y se le añade un test que corre los fixtures reales de Beds24 y Channex a través
del receptor completo.

`error` nunca lleva texto del cuerpo: forma estructurada (código + campo), como exige la regla 11 y
como el docstring del modelo ya advierte ("`error` must never echo the raw body back").

Rejected: un scrubber propio del receptor — dos copias de una función de seguridad divergen en el
primer arreglo unilateral, que es exactamente lo que el docstring de `card_data.py` explica.

### D8 — `special_requests`: la frontera que este change hereda **como bloqueante**

`pms-beds24-adapter` dejó esto decidido y con fecha de caducidad: su tarea P.8 y su D9 acotan la regla
13 a `raw_payload` y dejan `special_requests` fuera —lo llenan `comments` (Beds24) y `notes` (Channex),
viaja a `reservations.special_requests` y a la respuesta de la API— con una condición literal: *"se
vuelve exigible en cuanto exista una escritura no autenticada desde internet sobre esa misma columna,
que es lo que traen `reservations-webhooks` y `beds24-messaging-adapter`"*. Este change es esa
escritura. La condición se ha cumplido.

**Chosen (RATIFICADA por Jose el 2026-08-08):** redactar **rachas largas de dígitos** (13-19 dígitos
ignorando espacios y guiones) en `special_requests` **solo cuando la reserva viene de una fuente
externa** (webhook o sync de PMS), dejando intacto lo que una persona escribe por la API. Sin
comprobación de Luhn.

**Corrección del umbral tras implementarlo (aprobada por Jose el 2026-08-09): son 13 dígitos o más,
sin tope superior.** La banda cerrada 13-19 era la longitud de un PAN, y como criterio de corte deja
un agujero con disparador trivial: una racha *maximal* de 20+ dígitos queda fuera de la banda, así
que un PAN pegado a cualquier otro número se funde con él y sobrevive entero — `4111111111111111 1225`
(tarjeta y caducidad) son 20 dígitos y persistían en claro en una columna que la API devuelve. Redactar
desde 13 sin tope **solo redacta un superconjunto** de lo ratificado, y sobre entradas que el propio
argumento de la ratificación cubre a fortiori: si nada operativo llega a 13 dígitos, nada operativo
llega a 20. La banda 13-19 se conserva como lo que siempre fue, el razonamiento de la longitud, y vive
en el docstring de `MIN_REDACTED_DIGITS`. Lo encontró el panel de la sección 3.

**Segunda corrección, del alfabeto (misma fecha y mismo panel): los separadores y los dígitos son
Unicode, no ASCII.** «Ignorando espacios y guiones» escrito como `[ -]` sólo honra la decisión para
el teclado en que se escribió: un **espacio duro** —lo que produce copiar una tarjeta de una web o un
PDF, que es la forma más probable de que un PAN real llegue a una nota— la atravesaba entera, igual
que los guiones que sustituye un procesador de texto; y con `[0-9]` una racha en dígitos fullwidth o
arábigo-indios ni siquiera se reconocía como racha. **El punto sigue sin ser separador a propósito**
(`4111.1111.1111.1111` sobrevive): los puntos unen decimales, fechas, versiones e IPs, y D8 no dice
ignorarlos. Es el borde aceptado de la regla, con test propio.

**Dónde vive, decidido explícitamente (Jose, 2026-08-09) tras un `DESIGN-CONFLICT` del arquitecto:**
`free_text.py` se queda en `infrastructure/`, junto a `card_data.py`. La tabla de capas de
`steering/backend-architecture.md` empujaría una función pura sin I/O hacia `domain/`, y el argumento
es bueno; pesa más tener los **dos scrubbers de la misma frontera PCI en el mismo sitio**, que es donde
quien busque uno encontrará el otro. La razón por la que `card_data.py` está en Infra —moverlo tocaba
módulos de otros dos changes— no le aplicaba a un módulo nuevo, así que esta excepción se razona aquí
en vez de heredarse por inercia.

**Lo que cerró la ratificación**, porque el compromiso que había que aceptar era el falso positivo
sobre una nota que lee el personal de limpieza: los casos operativos reales caen **por debajo** del
umbral. Un código de portal español son 4-8 dígitos, un móvil español 9, uno internacional con
prefijo 11-12 — ninguno llega a 13. Jose confirmó además que en sus notas no es habitual nada de 13
dígitos o más. La ventana de falso positivo queda acotada a alguna referencia larga de OTA, que es
un dato reconstruible desde `external_pms_id`, no un dato que se pierda.

Por qué esta forma: el disparador de P.8 es "escritura no autenticada desde internet", así que el
riesgo está acotado al texto de origen externo, y ahí es donde se paga el coste. Lo que se pierde con
un falso positivo es una racha de dígitos en una nota que lee el personal de limpieza; lo que se
pierde sin la redacción es un PAN persistido en claro en una columna que devuelve la API.

Rejected: Luhn completo — D9 ya lo rechazó por falsos positivos reales sobre un campo operativo, y
nada nuevo lo justifica. Rejected: descartar el campo entero para fuentes externas — tira información
operativa real ("llegamos a las 23:00", "código del portal") por un riesgo que la redacción acota.
Rejected: no hacer nada y volver a diferirlo — P.8 dice "bloqueante", no "diferible otra vez".

**Residuo aceptado, nombrado a propósito para que sea decisión y no olvido (Jose, 2026-08-09):
`csv_parser.py` también llena `special_requests` y NO se redacta.** El alcance de D8 es "fuente
externa (webhook o sync de PMS)", y el disparador literal de P.8 es la escritura **no autenticada**
desde internet; el import de CSV es un fichero que sube un operador autenticado. El panel de seguridad
de la sección 3 objetó —con razón— que eso responde a *cómo se autenticó la escritura* y no a *si el
PAN puede estar ahí*, porque una exportación del PMS reempaqueta las mismas notas del huésped. Se
acepta el residuo en vez de ampliar el alcance ratificado. **Disparador para revisarlo**: que el CSV
deje de ser una reintroducción revisada por una persona y pase a ser reingesta cruda de una exportación
del PMS. Entonces hereda esta misma regla, no una nueva.

### D9 — La cola es durable: `attempts` y `next_attempt_at` en `webhook_events`

**Chosen (RATIFICADA por Jose el 2026-08-08, registrada en
[ADR 0007](../../../docs/adr/0007-webhook-event-retry-columns.md)):** dos columnas nuevas por
migración, `attempts SMALLINT NOT NULL DEFAULT 0` y `next_attempt_at TIMESTAMPTZ NULL`. El job
selecciona `processed = FALSE AND attempts < 3 AND (next_attempt_at IS NULL OR next_attempt_at <= now)`;
al fallar incrementa `attempts` y fija `next_attempt_at = now + backoff(attempts)`. Eso son los "3
reintentos con backoff exponencial" de PRD §16, persistidos.

**Añadido en la sección 4 tras el panel de seguridad: la selección además _reclama_ el lote.**
`select_pending` no tomaba ninguna prenda sobre las filas que devolvía —ni bloqueo, ni lease, y ni
`attempts` ni `next_attempt_at` se movían al seleccionar—, así que lo único que impedía que dos
ejecuciones solapadas cogieran **las mismas filas** era el lock de Redis, cuyo TTL es finito **a
propósito** (D9 de `celery-jobs` prefiere un lock que caduque a uno que atasque el job para
siempre). Una ejecución que se pasara de su TTL dejaba que el siguiente tick re-seleccionara el
mismo lote y emitiera una **segunda llamada saliente al mismo destino**: el techo de D10 pasaba a
depender de un TTL en vez de de la cola, que es justo el acoplamiento con el volumen que la regla
12(d) prohíbe. Ahora el lote se marca `next_attempt_at = now + BATCH_LEASE` (15 min) y se
commitea **antes** de trabajar. Se escribe en `next_attempt_at` y no en una columna nueva porque
«no seleccionable antes de este instante» es ya lo que esa columna significa, y **no toca
`attempts`**: una ejecución que muera a medias le cuesta a sus avisos una espera, nunca un trozo
de su presupuesto de reintentos.

Rejected: una subtarea Celery por evento con `autoretry_for` + `retry_backoff` — el estado del reintento
vive en el broker, así que un reinicio del worker lo pierde y, peor, el job por cadencia no puede
distinguir "en vuelo" de "pendiente" y reprocesa. Rejected: contar intentos en Redis — el contador
caduca y el evento vuelve a intentarse indefinidamente. Rejected: una tabla
`webhook_event_attempts` — una fila por evento con dos enteros no gana nada frente a dos columnas y
añade un join a la consulta caliente.

### D10 — Coalescing por construcción, no por ventana configurable

**Chosen:** el receptor **no hace ninguna llamada saliente**. El job por cadencia lee el lote pendiente,
lo **agrupa por destino de re-lectura** y emite **una** llamada por destino distinto y por ejecución.
Con eso, N avisos entre dos ticks producen una llamada, y el número de llamadas salientes queda acotado
por la cadencia (no por el volumen de peticiones), que es literalmente lo que pide la regla 12(d).
Cadencia inicial 60 s en `CADENCES`, holgada frente al techo medido de un ciclo cada 30 s por cuenta.

La coalescencia no necesita una ventana propia porque **el lote ya es la ventana**. Un test cierra R6.3:
el puerto del adapter no se toca desde el router.

**El «destino» es `(tenant, proveedor)`, y la granularidad es la garantía.** Se precisa aquí porque la
sección 4 obligó a elegirla y la elección no es indiferente: con destino **por reserva**, N avisos sobre
N reservas distintas darían N llamadas salientes —acotadas por el volumen de peticiones, que es
exactamente lo que 12(d) prohíbe—. Agrupando por proveedor, el techo por ejecución es
(tenants × proveedores del lote) y no se mueve con el tráfico. La re-lectura es por tanto la
`list_reservations` que el sync ya hace, no una `get_reservation` por aviso.

**Una re-lectura por destino, en bucle, y no una llamada que los lleve todos** (corregido en la
sección 4 tras los paneles de arquitectura y QA). El número de llamadas es el mismo —el caso de uso
de sync ya emitía una por grupo de proveedor—, pero la unidad de fallo y la de ventana pasan a ser
el destino. Importa por dos cosas que se midieron: `AmbiguousPropertyExternalIdError` escapa del
`try` por proveedor del sync, así que una sola llamada abarcando todos convertía el
`pms_external_id` duplicado de **un** proveedor en fallo de los avisos de **todos** los demás del
mismo tenant —contra R5.4, reproducido por el panel—; y la ventana quedaba anclada en el aviso más
antiguo del lote entero, ensanchando la de un proveedor porque otro distinto tenía un aviso más
viejo en el mismo tick.

**Y el `since` de esa re-lectura no puede anclarse en el aviso** (decidido en la implementación de 4.2,
`RE_READ_LOOKBACK`, marcado `ASSUMPTION` en el código). Un aviso anuncia un cambio **ya ocurrido**, así
que su `received_at` es posterior a la modificación que reporta: pedir al proveedor «todo lo cambiado
desde el aviso» excluye justo la reserva que el aviso señala. El margen tiene que cubrir la latencia de
entrega del proveedor, y **esa latencia está sin medir** — es una de las tres cosas que
`sdd/roadmap/beds24-webhook-cutover-measurement.md` existe para establecer. Se toma **una hora antes del
aviso más antiguo del grupo**: holgada frente a cualquier retraso plausible y barata frente a lo que
importa, porque el **número de llamadas** lo fija el agrupamiento de arriba y no se mueve con el ancho de
la ventana. Se revisa cuando llegue la medición.

Rejected: una ventana de coalescencia en Redis además de la cadencia — dos relojes para una sola
garantía, y el segundo no añade ninguna. Rejected: re-leer en el receptor con un debounce — cualquier
llamada saliente síncrona en la ruta de recepción es exactamente lo que 12(d) prohíbe.

### D11 — Sesiones: la cola sin marcar, el trabajo marcado por tenant

**Chosen:** el job lee la cola desde una sesión **nunca marcada** (obligatorio: `tenant_id` es nullable
y una sesión marcada esconde las filas `NULL` sin error), agrupa por tenant, y abre **una sesión marcada
por tenant** para el trabajo, apoyándose en el patrón de `run_for_every_tenant`. No se puede usar esa
función tal cual: itera *todos* los tenants activos y aquí solo interesan los que tienen eventos
pendientes, así que se extrae la parte de "sesión marcada por tenant" y se alimenta con la lista de
tenants del lote.

Los eventos con `tenant_id` NULL no se pueden convertir en reservas —no hay tenant al que atribuirlas—.
Con la autenticación de R1 en pie no deberían existir; la rama se mantiene para que la forma de PRD
§7.26 siga siendo honesta: se cuentan, se les fija `error` estructurado y `attempts = 3`, de forma que
quedan visibles para diagnóstico y **no** vuelven a seleccionarse en cada tick para siempre.

Rejected: marcar la sesión y leer la cola — el test de `test_tenant_filter.py` fija que eso esconde
precisamente las filas que hay que procesar.

### D12 — La transición la sigue haciendo el caso de uso que ya existe, con actor `SYSTEM`

**Corregido tras el panel de arquitectura.** La primera redacción de esta decisión decía que una
transición provocada por un webhook se registraría con actor `WEBHOOK` y su fila de `AuditLog`. Estaba
mal por dos motivos que el panel comprobó contra el código:

1. No declaraba **ningún** fichero bajo `app/properties/`, así que la transición que prometía auditar no
   tenía sitio de llamada. Y `AdvancePropertyStatesUseCase` fija el actor a
   `StateTransitionTriggeredBy.SYSTEM` en `app/properties/application/use_cases.py:290`, así que "actor
   `WEBHOOK`" exigía además modificar ese caso de uso.
2. Omitía el `TimelineEvent`, que `architecture.md` (línea 20) declara obligatorio en **toda**
   transición. No era evitable en la práctica —`PropertyStateMachine.evaluate` devuelve
   `PropertyStateChangeResult(transition=…, timeline_event=…)`, los dos siempre
   (`state_machine.py:128`)— pero un diseño que no lo nombra invita a implementarlo mal.

**Chosen:** este change **no introduce ningún actor nuevo** en `property_state_transitions`. Reutiliza
`AdvancePropertyStatesUseCase` **sin tocarlo**, invocándolo desde `process_webhook_events` con
`trigger=RESERVATION_CANCELLED_BEFORE_CHECKIN`. Ese trigger ya existe en la máquina de estados, con sus
estados de origen y su guarda (`state_machine.py:34,163,213,226`) y con test parametrizado, y **no tiene
hoy ningún llamante en producción**: este change es su primero. Por venir del caso de uso existente, la
transición sale con actor `SYSTEM` y con su `PropertyStateTransition` **y** su `TimelineEvent` en la
misma transacción, por construcción.

**Y la causalidad no se pierde, que es lo que hacía atractivo el actor `WEBHOOK`.** Queda registrada un
paso antes, donde de verdad ocurre: la ingesta escribe su propio `TimelineEvent` con
`actor_type=TimelineActorType.WEBHOOK` —el miembro ya existe en `app/timeline/domain/enums.py:9`— y un
`WEBHOOK_SOURCE` nuevo junto a los `PMS_SOURCE`/`CSV_SOURCE` que ya hay
(`app/integrations/application/use_cases.py:41-42`). La cadena queda legible de punta a punta: fila en
`webhook_events` → `TimelineEvent` de ingesta con actor `WEBHOOK` → transición con actor `SYSTEM`.

Con eso, la cláusula "`WEBHOOK` **no está exento**" de la regla 9 **no se activa**, porque ningún actor
`WEBHOOK` escribe en `property_state_transitions`. Y eso es lo correcto según el propio razonamiento de
la regla sobre `SCHEDULER`: *"pre-autorizar un actor que nadie ejercita es exactamente lo que el párrafo
de abajo dice que no se hace"*. El actor de una transición es quien la **ejecuta**, no quien cambió el
dato del que se deduce.

Lo que sí obliga a ampliar el vocabulario cerrado de `app/audit/domain/actions.py` son las operaciones
de **R2** (creación y rotación del endpoint de webhook), que son mutaciones de API hechas por una
persona. No es opcional: `AuditLogFactory.build` lanza `AuditContractError` ante un vocabulario
desconocido, y eso **aborta la transacción de la operación auditada**.

Rejected: parametrizar el actor de `AdvancePropertyStatesUseCase` para pasarle `WEBHOOK` — toca un caso
de uso de otro dominio para introducir un actor que la regla 9 nombra sólo para excluirlo de la
exención, y a cambio de un dato que el `TimelineEvent` de la ingesta ya da. Rejected: escribir la
transición desde `integrations` — `architecture.md` línea 20 lo prohíbe, `PropertyStateMachine` es el
único sitio.

### D14 — La resolución de credenciales en la re-lectura se reutiliza tal cual (R6.4)

**Chosen:** ninguna decisión nueva. La re-lectura por API resuelve el adapter y su credencial por el
`pms_factory` que ya existe, y con él viene la auditoría que `pms-provider-resolution` construyó: el
caso de uso de sync ya importa `PMS_CREDENTIAL_READ`/`ENTITY_PMS_CREDENTIAL` y ya implementa la
granularidad "una fila por credencial distinta y por ejecución" de la segunda excepción nombrada de la
regla 9 (`app/integrations/application/use_cases.py:22-25,74-77,124-139`). R6.4 queda cubierto **por
reutilización**, y la tarea que lo verifica es un test, no código nuevo.

**Lo que la implementación sí añadió, y por qué no es una segunda implementación** (sección 4):
`SyncReservationsFromPmsUseCase.execute` recibe tres argumentos opcionales — `providers`, `actor_type` y
`source` — con los valores por defecto que tenía antes, de modo que el sync programado y el manual no
cambian de comportamiento. `providers` acota la ejecución a los proveedores que el lote de webhooks
nombra (sin él, un aviso de un proveedor gastaría la cuota de otro en cada tick); `actor_type`/`source`
sólo describen **por qué** apareció la reserva y aterrizan en el `TimelineEvent` de la ingesta, nunca en
`property_state_transitions` — D12 sigue intacto. Lo que **no** se duplicó es lo que esta decisión
protege: la resolución de credenciales, la ruta única de upsert y el registro de lecturas siguen
existiendo una sola vez.

Rejected: una auditoría propia del procesamiento de webhooks — sería una segunda implementación de una
granularidad que ya está decidida, medida y con su excepción nombrada en la regla 9.

### D13 — Los eventos llegan desordenados y el aviso no es la fuente de verdad

**Chosen:** el cuerpo del webhook se usa para **saber qué mirar**, nunca como dato. El estado se obtiene
re-leyendo por API (ADR 0006), y el upsert va por `ReservationIngestor`, cuya idempotencia por
`(tenant_id, external_pms_id)` es lo que hace que el desorden no importe: si dos avisos del mismo objeto
se procesan al revés, la re-lectura devuelve el estado actual las dos veces. Esto es lo que cierra R5.7
sin necesidad de números de secuencia, que el proveedor no da.

Rejected: aplicar el cuerpo del webhook directamente — Channex documenta que llegan desordenados, así
que el último cuerpo recibido no es el último hecho.

### D15 — La lectura del material de webhook no se audita, y eso es una exención de la regla 3(b)

**Añadida tras el panel de seguridad de la sección 1.** La implementación ya había tomado esta
decisión —no existe `WEBHOOK_ENDPOINT_READ` en el vocabulario, con test que lo fija— pero la había
tomado **en un comentario de código**, y ese no es el canal. La regla 3(b) obliga a auditar la
lectura de toda credencial de proveedor, y la regla 9 dice cómo se exceptúa: *"con una entrada
nueva y nombrada aquí, aprobada en el design del change que la pida. El razonamiento de arriba **no
es un criterio reutilizable**"*. Sin esta entrada, el change se estaba auto-concediendo la exención.

**Chosen (RATIFICADA por Jose el 2026-08-08; la entrada nombrada ya está escrita como tercera
excepción de la regla 9 de `sdd/steering/security.md`):** la lectura del material de webhook **en la
ruta de recepción anónima** no escribe `AuditLog`.

Por qué: aquí la "lectura" equivalente a `PMS_CREDENTIAL_READ` ocurre en **cada webhook entrante**
—anónimo, desde internet, a la cadencia del proveedor—. Auditarla deja que un tercero escriba filas
en `audit_logs` a voluntad: es una denegación de servicio disfrazada de diligencia, y ahoga
precisamente el índice `ix_audit_logs_tenant_id_actor_user_id_created_at` que la segunda excepción
nombrada de la regla 9 existe para mantener respondible. Es el mismo argumento de cadencia que ya
justificó esa segunda excepción, aplicado a un caso peor: allí el actor es automático, aquí es
**hostil y no autenticado**.

**Lo que esta exención NO concede, y hay que decirlo porque la regla 9 lo dice de la suya:** no
exime la lectura con **actor humano**. Un comando de soporte o una herramienta de operador que lea
este material trae su propio `WEBHOOK_ENDPOINT_READ` el día que exista. No se añade ahora porque una
acción para una operación que nadie ejecuta es el vocabulario especulativo contra el que argumenta
el docstring de `actions.py` — el mismo razonamiento que la regla 9 aplica a `SCHEDULER`. Lo que sí
se corrigió al detectarlo: el test que fijaba la ausencia la fijaba **como política permanente**, y
ahora la fija atada a su premisa (*"while the only reader is anonymous"*).

Rejected: auditar cada recepción — la denegación de servicio descrita arriba. Rejected: auditar solo
las recepciones que fallan — es peor, porque son exactamente las que un atacante controla. Rejected:
dejarlo en el comentario de código y no tocar steering — es lo que el panel marcó: la regla 9 nombra
el canal, y un comentario no lo es.

## Changes by area

| Area | Files | Change |
|---|---|---|
| API receptor | `backend/app/integrations/api/webhooks_router.py` (nuevo) | Endpoint de recepción, orden de comprobaciones de D5, `404` uniforme de D4 |
| API administración | `backend/app/integrations/api/router.py`, `schemas.py`, `dependencies.py` | Alta y rotación del endpoint de webhook, con RBAC; respuesta de un solo uso con token y secreto |
| Dominio | `backend/app/integrations/domain/{entities.py,repositories.py,errors.py}` | Entidad `WebhookEndpoint`, su puerto de repositorio, errores propios; y para §4, `QueuedWebhookEvent` (el lote **sin cuerpo**, D13), el presupuesto de reintentos y la mitad lectora de `WebhookEventRepository` |
| Dominio | `backend/app/integrations/domain/ports.py` | `PropertyStateAdvancer`: el puerto de un solo método por el que llega `AdvancePropertyStatesUseCase` sin importarlo (D12) |
| Aplicación | `backend/app/integrations/application/webhooks.py` (nuevo) | Caso de uso de recepción (autenticar, descartar tarjeta, persistir) y de procesamiento del lote |
| Aplicación | `backend/app/integrations/application/use_cases.py` | Casos de uso de alta y rotación, con su `AuditLog`; constante `WEBHOOK_SOURCE` junto a `PMS_SOURCE`/`CSV_SOURCE` |
| Transiciones | **ningún fichero nuevo bajo `backend/app/properties/`** | `process_webhook_events` invoca `AdvancePropertyStatesUseCase` **sin modificarlo** (D12) y se convierte en el primer llamante en producción de `RESERVATION_CANCELLED_BEFORE_CHECKIN`. Si la implementación descubre que hace falta tocar `app/properties/`, es un `DESIGN-CONFLICT` y para |
| Infra | `backend/app/integrations/infrastructure/models.py` | `WebhookEndpointModel`; `attempts`/`next_attempt_at` en `WebhookEventModel` (D9) |
| Infra | `backend/app/integrations/infrastructure/repositories.py` | Repositorios de `WebhookEndpoint` y de la cola de `WebhookEvent` |
| Infra | `backend/app/integrations/infrastructure/throttle.py` (nuevo) | Los dos limitadores de D6 |
| Infra | `backend/app/integrations/infrastructure/free_text.py` (nuevo) | Redacción de rachas de dígitos de D8, y su reutilización desde los mapeos. **En `infrastructure/` por decisión razonada, no por defecto** — ver D8; junto a `card_data.py`, el otro scrubber de la misma frontera. Exporta además el detector que usa el guard de fixtures, para que la regla no tenga dos copias |
| Mapeos | `backend/app/integrations/infrastructure/{beds24,channex}/mapping.py` | Aplicar D8 a `special_requests` en las fuentes externas |
| Scheduler | `backend/app/scheduler/{schedule.py,tasks.py,runner.py}` | `process_webhook_events` en `CADENCES`, la tarea, y el helper de sesión marcada por lote de D11 |
| Auditoría | `backend/app/audit/domain/actions.py` | Entidad y acciones nuevas (D12) |
| Config | `backend/app/core/config.py`, `.env.example` | `webhook_rate_limit_per_minute`, `webhook_probe_limit_per_minute`, `webhook_max_body_bytes` |
| Migración | `backend/alembic/versions/` | `webhook_endpoints` + las dos columnas de `webhook_events` |
| Tests | `backend/tests/integrations/`, `backend/tests/scheduler/` | Aislamiento propio de `webhook_endpoints`, receptor, cola, reintentos, guard de fixtures |
| Docs | `docs/reservations-webhooks.md`, `README.md`, `.env.example` | Según `steering/documentation.md` |

## Data & interfaces

**Tabla nueva `webhook_endpoints`** (módulo `integrations`, `TenantScopedMixin` + `UUIDPrimaryKeyMixin`
+ `TimestampMixin`):

| Columna | Tipo | Notas |
|---|---|---|
| `tenant_id` | `Uuid` FK `tenants.id` | `NOT NULL`, del mixin: entra en el filtro global |
| `provider` | `pms_provider_enum` | El tipo Postgres que ya existe, compartido |
| `token_hash` | `String(64)` | SHA-256 hex, `UNIQUE` — la búsqueda de D1 |
| `header_name` | `String(100)` | El nombre de cabecera que el proveedor manda |
| `header_secret_encrypted` | `Text` | Ciphertext Fernet vía `EncryptedSecret` |
| `rotated_at` | `TIMESTAMPTZ NULL` | Igual que `pms_credentials` |

`UNIQUE(tenant_id, provider)`: un endpoint por proveedor y tenant.

**Columnas nuevas en `webhook_events`** (D9, desviación de PRD §7.26): `attempts SMALLINT NOT NULL
DEFAULT 0`, `next_attempt_at TIMESTAMPTZ NULL`. El índice existente
`ix_webhook_events_provider_processed_received_at` sigue sirviendo a la consulta de la cola.

**API:**

- `POST /api/v1/webhooks/{provider}/{webhook_token}` — sin JWT. `202` en éxito; `404` uniforme (D4);
  `429` por tasa; `413` por tamaño. Sin cuerpo de negocio en la respuesta.
- `POST /api/v1/integrations/webhook-endpoints` — RBAC. Devuelve **una sola vez** la URL completa y el
  secreto de cabecera.
- `POST /api/v1/integrations/webhook-endpoints/{id}/rotate` — RBAC. Igual, y `AuditLog`.
- Ninguna respuesta de lectura devuelve el token ni el secreto, ni enmascarados (regla 3(a)).

**Config nueva:** `WEBHOOK_RATE_LIMIT_PER_MINUTE` (120) y `WEBHOOK_PROBE_LIMIT_PER_MINUTE` (20). No son
secretos, así que llevan default (regla 8). **Sin `WEBHOOK_MAX_BODY_BYTES`**: el tope ya lo pone
`REQUEST_MAX_BYTES` a través del middleware existente (D5).

**Job:** `process_webhook_events` en `CADENCES` con `timedelta(seconds=60)`; el `beat_schedule` y el TTL
del lock se derivan de ahí sin tocar nada más.

## Risks & mitigations

- **La migración toca una tabla de otro change.** `webhook_events` es de
  `domain-foundation-financial`. La migración es aditiva y con default, así que no rompe nada existente
  —hoy la tabla está vacía en todos los entornos, porque nadie escribe en ella—. Mitigación documental:
  la spec de esa capacidad se actualiza al archivar, declarando a este change escritor vivo.
- **La entrega de un solo uso deja al operador sin la URL si la pierde.** Mitigación: la rotación es
  una operación de primera clase desde el día uno (no un añadido posterior), y la respuesta del alta lo
  dice explícitamente.
- **No se puede validar contra Beds24 real.** El spike midió que sus webhooks solo se disparan para
  reservas de canal, y la cuenta de medición no tiene canales. Mitigación: fixtures reales anonimizados
  ya versionados + `MockPMSAdapter`; la medición de latencia y desorden es de
  `beds24-webhook-cutover-measurement`, que existe para eso.
- **La redacción de D8 puede comerse un dato operativo real.** Mitigación: acotada a rachas de 13
  dígitos **o más** (ver la corrección del umbral en D8; la banda 13-19 era el razonamiento, no el
  corte) y a fuentes externas, y es reversible en un sitio (`free_text.py`) si el falso positivo
  resulta molesto en la práctica.
- **`AuditContractError` aborta la transacción auditada.** Mitigación: ampliar el vocabulario es una
  tarea explícita y con test, no un efecto colateral de otra.
- **Cola envenenada.** Un evento que falla siempre podría bloquear el lote. Mitigación: `attempts < 3`
  lo saca de la selección, y el aislamiento por evento (R5.4) impide que su fallo arrastre a los demás.
- **Nadie ha verificado que Beds24 entregue la cabecera estática.** Es uno de los tres puntos que
  `sdd/roadmap/beds24-webhook-cutover-measurement.md` deja explícitamente sin medir, junto a la latencia
  y el orden. Si resultara que no llega, la regla 12(a) se queda **sin mecanismo** en ese proveedor y el
  token de ruta pasa a ser la única defensa — que es precisamente la situación que 12(a)+12(b) están
  escritas para evitar. Mitigación: el `header_name` es una columna, no una constante, así que adaptarse
  a lo que el proveedor mande de verdad no exige migración de código; y lo que **no** depende de esa
  medición es la arquitectura, como esa misma entrada del roadmap deja dicho ("lo que la medición afina
  es la cadencia y las expectativas de orden, no la arquitectura"). Si la cabecera no existe, es un
  hallazgo para `security.md`, no un reajuste de este diseño.

## Open questions

**Ninguna abierta.** Las cinco decisiones que este diseño no podía cerrar por sí solo las resolvió
Jose el **2026-08-08**, y cada una queda escrita en su sitio, no aquí:

| | Decisión | Resultado | Dónde vive ahora |
|---|---|---|---|
| **D8** | Forma de la redacción de `special_requests` | Ratificada la provisional | D8, con el motivo por el que el falso positivo es acotado |
| **D9** | `attempts`/`next_attempt_at` (5ª desviación del PRD) | Ratificada | D9 + [ADR 0007](../../../docs/adr/0007-webhook-event-retry-columns.md) |
| **D15** | No auditar la lectura en la ruta anónima | Ratificada | Tercera excepción nombrada de la regla 9 de `steering/security.md` |
| **D6** | Presupuesto por IP vs. rotación | Aceptado con disparador (25-50 uds o primer `429` cruzado) | Nota de corrección en D6 |
| **D1** | El token en el path acaba en los logs del borde | Aceptado en dev; Transform Rule antes del primer tenant real | Nota de coste declarado en D1 |

Las tres últimas comparten una propiedad que conviene no perder: **no eran errores de código sino
premisas del diseño que la implementación falsó**, y ninguna era visible leyendo el diseño. Aparecieron
porque los paneles corrieron contra código que ya existía.
