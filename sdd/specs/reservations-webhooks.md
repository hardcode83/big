# Recepción de webhooks del PMS

## Purpose

El PMS avisa de que una reserva cambió, y ese aviso se convierte en reservas actualizadas sin que
nadie sondee. Cierra el cuarto ítem de PRD §16, que `reservations` entregó sin él porque sus dos
dependencias —la entidad `WebhookEvent` de `domain-foundation-financial` y el job
`process_webhook_events` de `celery-jobs`— no existían todavía.

La regla que gobierna todo lo demás: **el aviso nunca es la fuente de verdad**. Ninguno de los once
proveedores evaluados firma sus webhooks ([ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md)),
así que el cuerpo que llega es texto que cualquiera podría haber enviado. Lo único que hace es decir
*dónde mirar*: el dato se obtiene releyendo por API, y esa re-lectura va encolada y coalescida, nunca
una llamada saliente por webhook recibido. Por eso **no se implementa la rama de firma HMAC** de
PRD §16: su condición ("si el provider lo soporta") es falsa para todos.

Operación y runbook: [`docs/reservations-webhooks.md`](../../docs/reservations-webhooks.md).

## Requirements

### La ruta lleva el token, y el token resuelve el tenant

- THE SYSTEM SHALL exponer la recepción en `POST /api/v1/webhooks/{provider}/{webhook_token}`, y
  **no** en la forma global `POST /api/v1/webhooks/{provider}` de PRD §23. Es la cuarta desviación
  del PRD registrada en ADR 0006, y la exige la regla 12(b) de `steering/security.md`: una ruta
  globalmente adivinable deja el secreto de cabecera como única defensa.
- THE SYSTEM SHALL resolver el `tenant_id` **desde el token de la ruta** —buscando su hash en
  `webhook_endpoints`, con el `provider` en la misma condición— y no desde ningún dato que el
  llamante aporte en el cuerpo o en una cabecera.
- THE SYSTEM SHALL atender la petición **sin JWT** y sobre una sesión **nunca marcada**: el endpoint
  filtra por `tenant_id` explícito. No SHALL marcar la sesión ni siquiera después de resolver el
  tenant, porque marcar a mitad de petición crea la sesión medio-marcada que el guard existe para
  impedir.
- WHEN la autenticación de la sección siguiente se supera, THE SYSTEM SHALL responder `202` **sin
  cuerpo alguno** — ni de negocio ni de diagnóstico.
- THE SYSTEM SHALL redactar el segmento del token en el log de acceso del proceso, y SHALL usar el
  hash y no el valor como clave del limitador de tasa, de forma que el token no se materialice en
  Redis.

### Autenticación: dos secretos que se sostienen mutuamente

- THE SYSTEM SHALL exigir **dos** materiales para aceptar un aviso: el token opaco de la ruta y el
  valor de una **cabecera estática cuyo nombre es dato del endpoint** (`webhook_endpoints.header_name`),
  no una constante del sistema. Son dos y no uno a propósito: un volcado de cabeceras pierde el
  segundo pero no el primero; un log de peticiones registra el primero pero no el segundo.
- THE SYSTEM SHALL comparar el valor de la cabecera en **tiempo constante** (regla 12(a)), y no SHALL
  usar comparación de cortocircuito. Una comparación contra un valor ausente o vacío SHALL devolver
  falso en vez de fallar.
- THE SYSTEM SHALL usar un `webhook_token` opaco de **256 bits** generado con un CSPRNG, y no SHALL
  derivarlo del identificador del tenant, de su nombre ni de ningún dato enumerable.
- IF el `{provider}` de la ruta no es un proveedor soportado, o el `webhook_token` no corresponde a
  ningún endpoint de ese proveedor, o la cabecera falta, o su valor no coincide, o el secreto
  almacenado no descifra, THEN THE SYSTEM SHALL responder **el mismo `404`, con el mismo cuerpo**, sin
  escribir nada. Un `401` distinguible convertiría el endpoint en un oráculo de «este token existe».
- THE SYSTEM SHALL no emitir **nunca** un `401` desde esta ruta.

**Fuga de latencia declarada, no tapada.** Los tres rechazos tienen tres perfiles de coste: un
proveedor no soportado corta en el constructor del enum y no toca la base de datos; un token
desconocido cuesta el `SELECT` indexado; un token válido con cabecera incorrecta cuesta ese `SELECT`
más un descifrado Fernet y la comparación. El único salto que distingue «este token existe» es el
segundo, y es el menor de los dos. No es vía para *recuperar* un token de 256 bits: el oráculo solo
responde sobre candidatos que ya haya que adivinar, y el presupuesto de sondeo por IP acota el
muestreo. Igualar el coste con trabajo de relleno alargaría el camino sin igualarlo.

### El orden de las comprobaciones es la defensa

- THE SYSTEM SHALL rechazar la petición **antes de leer el cuerpo** cuando la autenticación falla, de
  forma que un cuerpo grande de un llamante no autenticado no se materialice en memoria. La
  autenticación vive **entera en la ruta y las cabeceras**, así que se resuelve sin tocar el cuerpo.
- THE SYSTEM SHALL ordenar las comprobaciones así: límite de sondeo por IP → proveedor → token →
  secreto de cabecera → cobro del límite por token → parseo del cuerpo → persistencia.
- THE SYSTEM SHALL alojar la **decisión** de autenticación en la capa de aplicación —resolver el
  token, comparar el secreto, descartar los datos de tarjeta y persistir—, dejando en el router solo
  las preocupaciones de transporte y la traducción del error a `404`/`429`/`413`. La regla 12(a)-(b)
  es de negocio, y su test no pasa por HTTP.
- IF el cuerpo de un llamante **autenticado** no es JSON válido, THEN THE SYSTEM SHALL encolarlo igual
  con `payload` vacío en vez de descartarlo: el cuerpo no decide nada, y una fila visible se
  diagnostica mejor que un aviso perdido.

### Tope de cuerpo y límites de tasa

- THE SYSTEM SHALL aplicar a esta ruta el mismo tope de cuerpo que a todo `/api/v1/`
  (`REQUEST_MAX_BYTES`, 1 MiB por defecto), impuesto **antes del enrutado** por el middleware
  existente, y no SHALL declarar una tercera perilla propia. El mecanismo del middleware está en
  [`specs/backend-http-posture.md`](backend-http-posture.md), su único hogar.
- IF el cuerpo supera ese tope, THEN THE SYSTEM SHALL responder `413` sin escribir ningún
  `WebhookEvent`, incluso cuando la sobremedida se descubre a mitad del stream.
- THE SYSTEM SHALL declarar **dos** límites de tasa como configuración con valor por defecto, con
  propósitos opuestos y ventana de 60 segundos:
  - `WEBHOOK_RATE_LIMIT_PER_MINUTE` (120), **por token**: protege la tabla del tráfico legítimo
    desbocado de un proveedor, y su radio de daño es un solo tenant.
  - `WEBHOOK_PROBE_LIMIT_PER_MINUTE` (20), **por IP y contando solo las peticiones que fallan la
    autenticación**: es lo que hace que sondear tokens cueste.
- THE SYSTEM SHALL cobrar el límite por token **solo después** de una autenticación correcta, de forma
  que quien tenga únicamente la URL no pueda gastar el presupuesto de un tenant y dejarle la
  integración en `429`.
- THE SYSTEM SHALL contar en el presupuesto por IP **solo los fallos**, y no el tráfico bueno: un
  proveedor envía desde pocas IPs en nombre de muchos tenants, así que un límite por IP sobre las
  entregas correctas los estrangularía a todos a la vez.
- IF cualquiera de los dos límites se supera, THEN THE SYSTEM SHALL responder `429` sin escribir
  ningún `WebhookEvent`.

### Aprovisionamiento, rotación y custodia del material

- THE SYSTEM SHALL exponer el alta en `POST /api/v1/integrations/webhook-endpoints` (`201`) y la
  rotación en `POST /api/v1/integrations/webhook-endpoints/{endpoint_id}/rotate` (`200`), y SHALL
  exigir en ambas el permiso `MANAGE_TENANT_SETTINGS` —de `TENANT_OWNER` según PRD §6—, nunca el de
  gestión de reservas: acuñar este material decide quién puede escribir en el tenant desde internet,
  para todas las viviendas a la vez, y eso es un acto de configuración.
- THE SYSTEM SHALL aceptar del llamante únicamente el `provider` y el **nombre** de la cabecera,
  validado contra una forma cerrada, y no SHALL aceptar ninguno de los dos secretos: los minta el
  sistema.
- THE SYSTEM SHALL generar un `webhook_token` y un secreto de cabecera **distintos por tenant**, y no
  SHALL usar ninguna constante global para ninguno de los dos.
- THE SYSTEM SHALL guardar el token **hasheado** con SHA-256 sin sal, con índice único global, y el
  secreto de cabecera **cifrado con Fernet** (regla 3). La asimetría es deliberada: la búsqueda del
  token tiene que ser O(1) por índice y con 256 bits de entropía no hay diccionario que atacar,
  mientras que el secreto tiene que poder descifrarse para compararlo.
- THE SYSTEM SHALL devolver los dos materiales en claro **una sola vez** —al crearlos y en cada
  rotación, excepción acotada de la regla 3(a)—, junto a la URL completa de recepción, y no SHALL
  ofrecer ninguna lectura posterior, ni siquiera enmascarada. No existe endpoint de lectura ni de
  borrado.
- WHEN se rota un endpoint, THE SYSTEM SHALL sobrescribir token y secreto en **una sola transacción**,
  sin ventana de gracia y sin conservar el valor anterior: el material viejo deja de autenticar en
  cuanto la transacción hace commit. No SHALL rotar el `header_name`, que es dato del proveedor y no
  material secreto.
- IF ya existe un endpoint para ese tenant y proveedor, THEN THE SYSTEM SHALL responder `409` en vez
  de reemplazar material vivo —eso es lo que hace `rotate`—, y SHALL cerrar la carrera con una
  restricción única `(tenant_id, provider)` en la base de datos, no solo con la comprobación previa.
- IF el `endpoint_id` a rotar no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL responder
  `404` en los dos casos, sin distinguirlos.
- WHEN se crea o se rota un endpoint, THE SYSTEM SHALL escribir una entrada de `AuditLog` (regla 9)
  con actor e IP, usando las acciones `WEBHOOK_ENDPOINT_CREATED` y `WEBHOOK_ENDPOINT_ROTATED` sobre la
  entidad `WEBHOOK_ENDPOINT`, y SHALL registrar el token y el secreto en forma **redactada**, de modo
  que intentar diferenciarlos como valores rompa el contrato de auditoría en vez de filtrarlos.
- THE SYSTEM SHALL cubrir `webhook_endpoints` con su **test de aislamiento propio** (regla 1 y regla
  3(c)), porque un fallo de scoping aquí no filtra datos: concede control.

**La lectura del material no se audita, y es una exención nombrada de la regla 3(b)** (tercera
excepción de la regla 9 en `steering/security.md`). La lectura equivalente a `PMS_CREDENTIAL_READ`
ocurre en **cada webhook entrante** —anónimo, desde internet, a la cadencia del proveedor—, así que
auditarla dejaría a un tercero escribir filas en `audit_logs` a voluntad: una denegación de servicio
disfrazada de diligencia, que ahoga el índice que la segunda excepción de la regla 9 existe para
mantener respondible. La exención **no** cubre una lectura con actor humano: una herramienta de
soporte que lea este material traerá su propia acción el día que exista.

### Los datos de titular de tarjeta se descartan en la frontera

- WHEN se recibe un cuerpo de webhook, THE SYSTEM SHALL eliminar los datos de titular de tarjeta
  **antes** de construir el `WebhookEvent`, y no SHALL cifrarlos ni enmascararlos: PCI DSS prohíbe
  retener el CVV, así que la obligación es descartarlos (regla 13(a)).
- THE SYSTEM SHALL aplicar el descarte de forma recursiva sobre toda la estructura, incluidos los
  objetos anidados dentro de listas, sustituyendo el **subárbol entero** de una clave que encaja en
  vez de descender en él.
- THE SYSTEM SHALL acotar la profundidad del recorrido y **descartar** lo que quede por debajo del
  tope en vez de inspeccionarlo: una recursión sin tope no falla de forma segura.
- THE SYSTEM SHALL mantener **una sola** definición de las agujas de tarjeta, compartida con el resto
  de la frontera PCI, y no SHALL escribir un scrubber propio del receptor: dos copias de una función
  de seguridad divergen en el primer arreglo unilateral.
- THE SYSTEM SHALL derivar `payload` **y** `event_type` del cuerpo ya limpiado, no del original.
- THE SYSTEM SHALL exigir que la función de descarte se inyecte sin valor por defecto, de forma que un
  receptor construido sin ella no compile en vez de persistir en claro.
- THE SYSTEM SHALL garantizar que ningún fixture versionado contiene datos de tarjeta, con un guard
  automático que **lea los ficheros en disco** —no la función que los produce—, que descubra los
  fixtures por glob en vez de por lista, que importe las agujas del anonimizador en vez de
  restatearlas, y que incluya un caso que demuestre que el propio guard dispara.
- THE SYSTEM SHALL mantener los datos de tarjeta fuera de los logs de acceso y de error del endpoint.

### `event_type` es una columna de texto libre escrita desde fuera

- THE SYSTEM SHALL leer `event_type` de las claves `event`, `event_type`, `type` o `action` del cuerpo
  limpiado, y SHALL aceptarlo **solo si tiene forma de nombre**: empieza por letra y sigue con
  alfanuméricos, punto, guion, guion bajo o dos puntos.
- THE SYSTEM SHALL rechazar además cualquier valor con una racha de **5 dígitos o más contada a través
  de los separadores** —`.`, `-`, `_` y `:`, que están en el alfabeto de la propia etiqueta y por
  tanto son justo lo que hay disponible para partir una racha—, y SHALL anclar el patrón al principio
  del valor.
- IF el valor no encaja, THEN THE SYSTEM SHALL registrar `unknown` en vez de persistirlo: nada
  ramifica sobre esta cadena, así que degradar lo desconocido no cuesta nada.

Esta columna entró tarde en el censo de la regla 11, y la lección se conserva a propósito: se llama
«tipo» y uno espera un enum, pero la rellenaba el cuerpo, así que **el censo se hace por quién escribe
la columna, no por lo que su nombre promete**. Y «estructurada» significa aquí menos que en las otras
filas de esa tabla: la forma cerrada excluye los valores **numéricos largos**, no todo valor de la
regla 3 —una cadena externa con forma de nombre sobrevive verbatim—. Cerrar `event_type` tampoco saca
el valor de la fila: el descarte de tarjeta es una denylist **por clave**, no inspecciona valores, así
que un PAN bajo `event` se sigue persistiendo en `payload`. Es el riesgo que la D9 de
`pms-beds24-adapter` acepta por escrito.

### Rachas largas de dígitos en `special_requests`

- WHEN un mapeo de **fuente externa** —webhook o sondeo del PMS— promueve texto libre a
  `reservations.special_requests`, THE SYSTEM SHALL redactar las rachas de **13 dígitos o más**, sin
  tope superior, antes de persistirlo.
- THE SYSTEM SHALL ignorar como separadores el espacio y el guion en su forma **Unicode**, no solo
  ASCII: un espacio duro es lo que produce copiar una tarjeta de una web o un PDF, que es la forma más
  probable de que un PAN real llegue a una nota.
- THE SYSTEM SHALL dejar intacto lo que una persona escribe por la API: el alcance es la fuente
  externa, no la columna.
- THE SYSTEM SHALL no comprobar Luhn: ya se rechazó por falsos positivos reales sobre un campo
  operativo.

Esto cierra la frontera que `pms-beds24-adapter` dejó declarada como bloqueante: su condición literal
era «una escritura no autenticada desde internet sobre esa misma columna», y esta capacidad es esa
escritura. El umbral de 13 se eligió porque los casos operativos reales caen por debajo —un código de
portal español son 4-8 dígitos, un móvil español 9, uno internacional 11-12—, y sin tope superior
porque una banda cerrada 13-19 dejaba pasar un PAN pegado a su caducidad. **El punto no es separador a
propósito** (`4111.1111.1111.1111` sobrevive): los puntos unen decimales, fechas, versiones e IPs. El
salto de línea **sí** lo es, así que dos números cortos en líneas consecutivas pueden sumar 13 y
redactarse juntos. Los dos bordes tienen test propio.

### El `WebhookEvent` y su contrato de columnas

- THE SYSTEM SHALL persistir cada aviso aceptado como una fila de `webhook_events` con `processed`
  falso, el `provider`, el `event_type`, el `payload` limpiado, el `received_at` y el `tenant_id`
  resuelto por el token.
- THE SYSTEM SHALL escribir `payload` y `error` en **forma estructurada** (regla 11). Esta capacidad
  es el primer escritor de las tres columnas de esta tabla y hereda su contrato.
- THE SYSTEM SHALL admitir en `error` **únicamente** un par código-campo serializado: el código de un
  vocabulario cerrado (`UNATTRIBUTED`, `UNMAPPABLE`, `PROVIDER_UNAVAILABLE`) y el `field` un **nombre**
  de clave con forma de identificador, nunca un valor. El tipo de la entidad no es una cadena libre,
  de modo que devolver el cuerpo recibido no es expresable.
- IF un evento aceptado no es atribuible a un tenant, THEN THE SYSTEM SHALL escribirlo con `tenant_id`
  NULL en vez de descartarlo (PRD §7.26). Con la autenticación en pie no debería existir; la rama se
  mantiene para que la forma de PRD §7.26 siga siendo honesta.

### Procesamiento asíncrono con `process_webhook_events`

- THE SYSTEM SHALL registrar `process_webhook_events` en la tabla única de cadencias con **60
  segundos**, de la que se derivan el `beat_schedule` y el TTL de su lock, y SHALL tratar esa cadencia
  como **parámetro de seguridad**: como el job coalesce todo un tick en una llamada por destino, la
  cadencia *es* el techo de llamadas salientes.
- THE SYSTEM SHALL proteger la ejecución con el mismo lock Redis que los demás jobs y SHALL informar
  la contención como un contador (`skipped_locked`), no como un error.
- WHEN el job se ejecuta, THE SYSTEM SHALL seleccionar los eventos con `processed` falso, presupuesto
  de reintentos disponible y `next_attempt_at` vencido o nulo, en orden de llegada y con tope de lote.
- THE SYSTEM SHALL **reclamar** el lote antes de trabajarlo, fijando su `next_attempt_at` a un lease
  futuro y **commiteando antes** de empezar. La reclamación SHALL ser un compare-and-swap que repita
  el predicado de selección y devuelva los ids ganados, y SHALL procesarse **lo reclamado, no lo
  visto**: sin esa condición, dos ejecuciones solapadas trabajarían el mismo lote y emitirían dos
  llamadas salientes al mismo destino. La reclamación **no** SHALL tocar `attempts`: una ejecución que
  muera a medias le cuesta a sus avisos una espera, nunca un trozo de su presupuesto.
- THE SYSTEM SHALL alimentar el `ReservationIngestor` como **única** ruta de upsert, a través del caso
  de uso de sync que ya existe, y no SHALL escribir reservas por ninguna otra vía.
- WHEN todos los avisos de un destino se completan, THE SYSTEM SHALL fijar `processed` y `processed_at`
  en esas filas.

### La cola es durable: presupuesto de reintentos en la propia fila

- IF el procesamiento de un evento falla, THEN THE SYSTEM SHALL reintentarlo hasta **3 veces con
  backoff exponencial** (PRD §16) —1, 2 y 4 minutos—, incrementando `attempts` en la propia sentencia
  SQL y fijando `next_attempt_at`. Agotado el presupuesto, la fila **se queda** con `processed` falso
  y su causa en `error`, y deja de seleccionarse.
- THE SYSTEM SHALL persistir el estado del reintento en la fila y no en el broker ni en Redis
  ([ADR 0007](../../docs/adr/0007-webhook-event-retry-columns.md), quinta desviación del PRD): un
  reinicio del worker perdería el primero, y el segundo caduca y devuelve el evento a la cola para
  siempre.
- THE SYSTEM SHALL agrupar los reintentos por el `attempts` **actual** de cada evento, de forma que
  avisos con historias distintas obtengan huecos distintos.
- IF un evento no tiene tenant, THEN THE SYSTEM SHALL agotarle el presupuesto de golpe —reintentar no
  inventa un tenant— dejándolo visible para diagnóstico, y SHALL emitir un aviso en el log.
- THE SYSTEM SHALL aislar el fallo de un evento del resto: un evento que falla no SHALL impedir el
  procesamiento de los demás de la misma ejecución, ni de los de otro proveedor del mismo tenant.

### Sesiones: la cola sin marcar, el trabajo marcado por tenant

- THE SYSTEM SHALL leer la cola de `webhook_events` desde una sesión **nunca marcada**: la columna
  `tenant_id` es nullable y una sesión marcada esconde las filas NULL **sin error**, que son
  precisamente las que hay que diagnosticar.
- THE SYSTEM SHALL abrir **una sesión marcada por tenant**, nunca re-marcada, para el trabajo de cada
  tenant, y SHALL alimentarla solo con los tenants que tienen eventos pendientes en vez de recorrer
  todos los activos.
- IF el trabajo de un tenant falla, THEN THE SYSTEM SHALL deshacer su transacción y cargar el
  reintento desde la sesión del lote, no desde la del tenant.

### La re-lectura va desacoplada del volumen de peticiones

- THE SYSTEM SHALL tratar el webhook como **aviso no fiable** y obtener el dato re-leyendo por API, y
  no SHALL confiar en el cuerpo recibido como fuente de verdad.
- THE SYSTEM SHALL garantizar que **ninguna** ruta del endpoint de recepción realiza una llamada
  saliente al proveedor de forma síncrona.
- THE SYSTEM SHALL agrupar el lote por destino `(tenant, proveedor)` y emitir **una** llamada por
  destino distinto y por ejecución, de modo que el techo por ejecución sea (tenants × proveedores del
  lote) y no se mueva con el tráfico. La granularidad es la garantía: con destino por reserva, N
  avisos sobre N reservas darían N llamadas, que es exactamente lo que la regla 12(d) prohíbe.
- THE SYSTEM SHALL emitir esas llamadas **en bucle, una por destino**, y no una sola que los abarque a
  todos: la unidad de fallo y la de ventana son el destino, así que un `pms_external_id` duplicado de
  un proveedor no SHALL convertirse en fallo de los avisos de los demás.
- THE SYSTEM SHALL no necesitar una ventana de coalescencia propia: el lote **es** la ventana, y dos
  relojes para una sola garantía es uno de más.
- THE SYSTEM SHALL anclar el `since` de la re-lectura **una hora antes** del aviso más viejo de cada
  grupo, y no en el aviso: un aviso anuncia un cambio **ya ocurrido**, así que pedir «todo lo cambiado
  desde el aviso» excluiría justo la reserva que señala. El margen es holgado y barato, porque el
  número de llamadas lo fija el agrupamiento y no el ancho de la ventana.
- THE SYSTEM SHALL excluir el cuerpo del aviso de la estructura que viaja al procesamiento, de modo
  que confiar en él no sea expresable.
- WHEN se resuelven credenciales de proveedor durante el procesamiento, THE SYSTEM SHALL registrar una
  fila de `AuditLog` por cada credencial **distinta** descifrada, no una por descifrado (segunda
  excepción nombrada de la regla 9), reutilizando el registro de lecturas que ya existe.

### Los eventos llegan desordenados

- THE SYSTEM SHALL tratar los eventos como potencialmente **desordenados** —Channex documenta que
  llegan así— y no SHALL asumir que el orden de llegada es el orden de los hechos.
- THE SYSTEM SHALL apoyarse para ello en la idempotencia del `ReservationIngestor` por
  `(tenant_id, external_pms_id)` y en que el estado se obtiene releyendo: si dos avisos del mismo
  objeto se procesan al revés, la re-lectura devuelve el estado actual las dos veces. No SHALL
  introducir números de secuencia ni columna de versión, que el proveedor no da.

### Causalidad y transiciones de estado

- WHEN un aviso produce una reserva ingerida, THE SYSTEM SHALL escribir su `TimelineEvent` de ingesta
  con actor `WEBHOOK`, que es donde la causalidad de verdad ocurre.
- WHEN un aviso produce una transición de estado operacional, THE SYSTEM SHALL hacerla pasar por el
  caso de uso de propiedades que ya existe, **sin modificarlo**, persistiendo su
  `PropertyStateTransition` **y** su `TimelineEvent` en la misma transacción.
- THE SYSTEM SHALL **no introducir ningún actor nuevo** en `property_state_transitions`: la transición
  sale con actor `SYSTEM`, porque el actor de una transición es quien la **ejecuta**, no quien cambió
  el dato del que se deduce. La cadena queda legible de punta a punta —fila en `webhook_events` →
  `TimelineEvent` de ingesta con actor `WEBHOOK` → transición con actor `SYSTEM`— sin inventar actores,
  y por tanto la cláusula «`WEBHOOK` no está exento» de la regla 9 no se activa.

### Observabilidad

- THE SYSTEM SHALL informar en cada ejecución del job los contadores `selected`, `processed`, `failed`,
  `unattributed`, `tenants` y `skipped_locked`, usando para la contención el mismo nombre que los
  demás jobs.

## Estado y deuda conocida

- **Nunca se ha visto llegar un webhook real de ningún proveedor a este receptor**
  (`EXTERNAL_DEPENDENCY`). La cuenta de desarrollo de Beds24 no puede tener canales OTA conectados, y
  sus webhooks solo se disparan para reservas de canal, así que quedan sin verificar contra un
  proveedor real **tres** cosas: que la cabecera estática llegue tal como se configuró, cuál es la
  latencia de entrega y cómo se comporta el orden. Las cierra
  `beds24-webhook-cutover-measurement`. Lo verificado con fixtures y `MockPMSAdapter` es todo lo
  nuestro. Si resultara que la cabecera no llega, la regla 12(a) se queda **sin mecanismo** en ese
  proveedor: sería un hallazgo para `steering/security.md`, no un reajuste de este diseño, y adaptarse
  no exige migración de código porque `header_name` es una columna y no una constante.
- **El token viaja en la ruta y por tanto en los logs del borde.** Dentro del proceso está cerrado
  (redacción en el log de acceso, hash como clave del limitador), pero el túnel de Cloudflare de
  [ADR 0003](../../docs/adr/0003-https-ingress-dev.md) registra el URI completo en sus propios logs.
  Aceptado en dev, donde el entorno es de una sola persona y esos logs son suyos. **La Transform Rule
  que redacte `/api/v1/webhooks/*` en el borde es requisito antes de que entre el primer tenant
  real**, no una tarea opcional. No se mueve el token fuera de la ruta: eso devuelve el problema a la
  regla 12(b).
- **El presupuesto de sondeo por IP puede estrangular a un proveedor legítimo.** Entre una rotación y
  la actualización del panel del proveedor sus entregas fallan, y 20 fallos en un minuto desde su IP
  compartida bloquean a todos los tenants que hay detrás. Aceptado como problema de escala, no de
  corrección. **La reparación es una allowlist de IPs de egreso del proveedor**, exentas del
  presupuesto; **disparador acordado**: el corte de 25-50 unidades que ADR 0006 marca para Channex, o
  antes si una rotación llega a provocar un `429` cruzado. Descartadas: el presupuesto por
  `(IP, token)`, que estrena presupuesto en cada intento adivinado, y hacer el `429` indistinguible
  del `404`, que cierra el oráculo pero hace que un proveedor estrangulado pierda entregas en silencio.
- **La deduplicación de `PMS_CREDENTIAL_READ` es por llamada de sync, no por tick.** Como la
  re-lectura emite una llamada por proveedor, cada una construye su propio registro de lecturas: sale
  una fila por credencial, por grupo de proveedor, por tenant y por ejecución. Es más granular que
  «una por ejecución» y no menos, así que respeta el techo que la regla 9 protege; queda dicho porque
  el enunciado literal del requisito dice «en esa ejecución».
- **`csv_parser.py` también llena `special_requests` y no se redacta.** El alcance decidido es «fuente
  externa», y el import de CSV es un fichero que sube un operador autenticado. Se aceptó el residuo en
  vez de ampliar el alcance ratificado, con **disparador para revisarlo**: que el CSV deje de ser una
  reintroducción revisada por una persona y pase a ser reingesta cruda de una exportación del PMS.
- **Dos tipos de error del dominio no los lanza nadie**: los de cuerpo demasiado grande y límite de
  tasa existen con sus docstrings, pero el router construye las respuestas `413`/`429` directamente.
  Son tipos muertos con documentación viva.
- **Fuera de alcance, con dueño**: la **suscripción** automática de webhooks en el proveedor (es del
  adapter y de la ventana de corte — y Beds24 la sirve por API, `POST /properties`, contra lo que
  afirmaba ADR 0006; cuando se automatice, `additionalData` va fijado a `none` **como constante y no
  como parámetro**, porque sus otros valores meten el CVV en el cuerpo); la medición de latencia y
  desorden; los webhooks de **registro policial** (de `access-notifications`) y de **mensajería** (de
  `beds24-messaging-adapter`); el **frontend** para administrar el material (de `dashboard-web`); la
  redacción de códigos de acceso en recepción (depende de una decisión abierta en PRD §5.5); y el
  **reproceso manual** de eventos ya procesados junto al panel de cola de errores.

## Key files

- `backend/app/integrations/api/webhooks_router.py` — el receptor: orden de comprobaciones, `404`
  uniforme, `413` por desconexión del middleware.
- `backend/app/integrations/api/router.py`, `schemas.py`, `dependencies.py` — alta y rotación con
  RBAC, respuesta de un solo uso, y la raíz de composición del receptor.
- `backend/app/integrations/application/webhooks.py` — los casos de uso de recepción y de
  procesamiento del lote, la forma cerrada de `event_type`, la agrupación por destino y el `since`.
- `backend/app/integrations/application/use_cases.py` — alta y rotación con su `AuditLog`, y el sync
  reutilizado con `providers`/`actor_type`/`source`.
- `backend/app/integrations/domain/webhook_auth.py` — generación del material, hash del token y
  comparación en tiempo constante.
- `backend/app/integrations/domain/entities.py` — `WebhookEndpoint`, `QueuedWebhookEvent` (el lote
  **sin cuerpo**), `WebhookEventFailure` y el presupuesto de reintentos.
- `backend/app/integrations/domain/ports.py` — el puerto de un solo método por el que llega el caso de
  uso de transiciones sin importarlo.
- `backend/app/integrations/infrastructure/{models,repositories}.py` — `webhook_endpoints`, las dos
  columnas nuevas de `webhook_events`, y la selección/reclamación de la cola.
- `backend/app/integrations/infrastructure/throttle.py` — los dos limitadores.
- `backend/app/integrations/infrastructure/{card_data,free_text}.py` — los dos scrubbers de la misma
  frontera PCI, juntos a propósito.
- `backend/app/core/log_redaction.py` — la redacción del segmento del token en el log de acceso.
- `backend/app/scheduler/{schedule,tasks,runner}.py` — la cadencia, la tarea y la sesión marcada por
  lote de tenants.
- `backend/alembic/versions/a4d17e83b6c1_reservations_webhooks.py` — la migración.
- `docs/reservations-webhooks.md` — el runbook; `docs/adr/0007-webhook-event-retry-columns.md` — la
  quinta desviación del PRD.
