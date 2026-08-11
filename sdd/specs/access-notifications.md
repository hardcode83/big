# Accesos, notificaciones y registro legal

## Purpose

Cubre tres capas operativas que comparten esqueleto —puerto, adapter, máquina de estados y
timeline— y que hasta ahora existían como tabla sin motor: el **registro de acceso** de cada
estancia (PRD §15), la **entrega** de las notificaciones que los demás módulos encolan
(PRD §14) y la **capa operativa de SES.Hospedajes** para el registro legal del huésped
(PRD §17). Es el change que enciende el escalado de SLA: es el primer código que marca
`SENT`, el valor que `check_sla_breaches` exigía y nadie escribía.

El *cómo se opera y se diagnostica* está en
[`docs/access-notifications.md`](../../docs/access-notifications.md); aquí vive el *qué hace*.

## Requirements

### El reconciliador de accesos

- THE SYSTEM SHALL mantener el estado del acceso en `access_records.status` como única verdad,
  y SHALL actualizar `reservations.access_status` como columna derivada **dentro del propio
  repositorio**, en la misma transacción, de modo que ningún llamante pueda persistir una
  transición sin su proyección. `Reservation.UPDATABLE_FIELDS` excluye la columna: no hay otro
  escritor.
- THE SYSTEM SHALL proyectar `REVOKED` a `ReservationAccessStatus.NOT_REQUIRED`, porque PRD §7.6
  cierra ese enum en `PENDING, CREATED_EXTERNAL, MANUAL_ADDED, DELIVERED, EXPIRED, NOT_REQUIRED`
  y los nombres del PRD son canónicos. Marcado `ASSUMPTION` en el mapeo. Un registro sin
  `reservation_id` no proyecta a ninguna parte.
- THE SYSTEM SHALL ejecutar `provision_access_records` cada 5 minutos y, por tenant, en este
  orden: crear los registros que falten, revocar los de reservas canceladas y expirar los de
  `valid_to` vencido, con un único `commit` al final.
- WHEN el barrido encuentra una reserva confirmada sin `AccessRecord`, THE SYSTEM SHALL crear uno
  en `PENDING` con `provider`/`created_mode` por defecto y el `property_id`/`reservation_id`/
  `tenant_id` de la reserva, y SHALL escribir un `TimelineEvent` `ACCESS_CODE_PENDING` asociado a
  la propiedad y a la reserva.
- IF la reserva ya está cancelada cuando el barrido la ve por primera vez, THEN THE SYSTEM SHALL
  crear el registro y revocarlo **en el mismo paso**, de modo que nazca `REVOKED` y no se acuñe
  un acceso `PENDING` para una reserva muerta.
- WHEN el barrido encuentra un registro vivo cuya reserva está cancelada, THE SYSTEM SHALL
  revocarlo con motivo `"reservation cancelled"`.
- THE SYSTEM SHALL derivar su idempotencia de la propia consulta de trabajo y no de un flag
  almacenado, con una regla deliberadamente **asimétrica**: una estancia no cancelada queda
  excluida si tiene algún registro **no terminal**; una estancia cancelada queda excluida si
  tiene **cualquier** registro. Las reservas en `PENDING` quedan fuera por completo.
- WHEN una reserva cancelada vuelve a confirmarse, THE SYSTEM SHALL darle un `AccessRecord`
  nuevo en `PENDING` junto al `REVOKED` anterior, y SHALL converger a la pasada siguiente sin
  escribir nada más.
- THE SYSTEM SHALL devolver como «el acceso de esta reserva» **el registro más reciente**, que es
  lo que hace resoluble el caso anterior.
- THE SYSTEM SHALL acotar cada pasada por un tamaño de lote y apoyarse en el lock distribuido de
  Redis por nombre de tarea que ya usan los cuatro jobs de PRD §8.3; perder el lock es
  «saltado», no un fallo.

**La regla asimétrica no es un detalle de implementación.** `CANCELLED → CONFIRMED` está
permitido y ninguna máquina de estados lo impide, y `revoke()` es terminal: con la regla
simétrica una reserva re-confirmada se quedaba en `access_status = NOT_REQUIRED` para siempre.
Aplicar la regla de las vivas a las canceladas acuñaría un `REVOKED` nuevo cada cinco minutos.
Lo encontró el panel de QA a escala de feature.

**Por qué un barrido y no un hook**: hay reservas **ya confirmadas** en la base de datos, y un
hook solo cubriría las futuras, dejando el histórico sin registro para siempre. Además las
confirmaciones entran por tres caminos (`UpdateReservationUseCase`, import CSV y sync PMS, los
dos últimos vía `ReservationStatus.parse_ingested`, que **por defecto confirma**). Coste
aceptado: hasta 5 minutos entre confirmar y ver el registro, irrelevante frente a un check-in
que ocurre días después.

### Máquina de estados del `AccessRecord`

- THE SYSTEM SHALL admitir exactamente estas transiciones, por estado destino, y SHALL rechazar
  cualquier otra con `409` sin escribir ningún evento:
  `MANUAL_ADDED ← {PENDING}`; `CREATED_EXTERNAL ← {PENDING}`;
  `DELIVERED ← {MANUAL_ADDED, CREATED_EXTERNAL}`;
  `REVOKED ← {PENDING, MANUAL_ADDED, CREATED_EXTERNAL, DELIVERED}`;
  `EXPIRED ← {MANUAL_ADDED, CREATED_EXTERNAL, DELIVERED}`.
- THE SYSTEM SHALL no admitir **ninguna** transición hacia `PENDING`: es solo el valor inicial.
  `REVOKED` y `EXPIRED` son terminales.
- THE SYSTEM SHALL alojar esa invariante en la entidad `AccessRecord` (`register_manual_code`,
  `mark_external_managed`, `mark_delivered`, `revoke`, `expire`) y no en el caso de uso: es una
  regla de negocio, y `steering/backend-architecture.md` es explícito. **No** es una transición
  de estado de propiedad: `PropertyStateMachine` queda intacta.
- WHEN el operador registra un código manualmente, THE SYSTEM SHALL pasar el registro a
  `MANUAL_ADDED` con `provider = MANUAL` y `created_mode = MANUAL`, y escribir
  `ACCESS_CODE_MANUAL_ADDED`.
- WHEN el operador declara que el acceso lo gestiona el proveedor externo, THE SYSTEM SHALL pasar
  el registro a `CREATED_EXTERNAL` con `provider = EXTERNAL_MANAGED` y
  `created_mode = EXTERNAL_PMS_AUTOMATIC`, sin fijar `code_masked`, y escribir
  `ACCESS_CODE_CREATED_EXTERNAL`.
- WHEN el operador confirma que el huésped recibió las instrucciones, THE SYSTEM SHALL pasar el
  registro a `DELIVERED` y escribir `ACCESS_CODE_DELIVERED`.
- THE SYSTEM SHALL **no** escribir `TimelineEvent` alguno para `REVOKED` ni para `EXPIRED`: PRD
  §15 no declara evento para ellos y la fila de `AuditLog` es la que lo registra.
- THE SYSTEM SHALL conservar `code_masked` al revocar, y SHALL sustituir `notes` por
  `"Revoked: <motivo>"` — una revocación pisa las notas del operador.
- THE SYSTEM SHALL limitar `notes` a 2000 caracteres truncando en silencio.
- THE SYSTEM SHALL llevar en el `metadata` del evento de timeline únicamente
  `access_record_id` y `status`, y nunca `code_masked`: el timeline es append-only y nada que
  caiga en él se puede redactar después.

**`EXPIRED` está implementado y hoy no se ejercita**: nada escribe `valid_from`/`valid_to`, de
modo que la consulta de expirables no devuelve nada. Se construyó para no dejar un valor del
enum sin camino; `test_expirable_finds_nothing_because_nothing_writes_valid_to` fija esa ausencia
y empezará a fallar, útilmente, el día que un proveedor real llene la columna.

### El código en claro no se persiste, no se registra y no viaja

- THE SYSTEM SHALL derivar de un código recibido únicamente su forma enmascarada `****XX`
  mediante `mask_access_code`, persistirla en `code_masked` y descartar el original.
  `AccessRecordModel` **no tiene columna** para el valor completo y no se le añade.
- THE SYSTEM SHALL recortar los espacios antes de enmascarar, y SHALL enmascarar **por completo**
  un código cuya longitud no supere el sufijo visible (`"7"` → `"****"`, nunca `"****7"`):
  revelar el secreto entero es lo único que una máscara no puede hacer, y un código corto es
  justo donde ocurriría.
- IF el código recibido está en blanco, THEN THE SYSTEM SHALL rechazar la petición con `422`.
- THE SYSTEM SHALL normalizar ambos lados a minúsculas y solo alfanuméricos antes de comparar, y
  SHALL rechazar con `422` la petición cuyo `notes` contenga el código que se está registrando —
  `code="AbC123"` con `notes="el código es abc123"`, o un código partido por un espacio, son el
  mismo código. La comparación **yerra hacia rechazar**: una colisión con un número corriente
  («piso 12») cuesta al operador una reescritura, y el error opuesto guarda un código de puerta
  en una columna servida a todo el tenant.
- THE SYSTEM SHALL no persistir, registrar en logs ni devolver por API el código completo en
  ningún punto: solo `code_masked`.
- THE SYSTEM SHALL registrar `notes` en la auditoría como campo **redactado** y nunca diferenciado,
  y SHALL diferenciar `code_masked` —que no está entre los campos redactados— solo en la
  transición a `MANUAL_ADDED`.

**No es una limitación del MVP.** PRD §15 dice que AutoHostAI **no** controla la cerradura: el
código lo genera y lo entrega el proveedor a través del PMS. `MANUAL_ADDED` registra que existe;
`DELIVERED` registra que el operador confirmó que el huésped lo tiene. La entrega del valor real
es fuera de banda, por diseño. Cifrarlo con Fernet se rechazó porque descifrarlo exige un
consumidor y no hay ninguno.

**Deuda nombrada**: `access_records.notes` **no** está en la tabla de sumideros de la regla 11 de
`steering/security.md`. La comprobación de arriba cierra el caso del operador descuidado dentro de
la propia petición; el caso general —escribir *otro* código más tarde— no lo puede cerrar ninguna
comprobación intra-petición, y ampliar el contrato de un sumidero es una decisión de steering.
Anotado en la entrada de roadmap de `field-apps`, que es quien ampliará la superficie de `notes`.

### El puerto del proveedor de acceso

- THE SYSTEM SHALL declarar `AccessProviderAdapter` en `access/domain/ports.py` con
  `get_access_status`, `create_manual_access` y `mark_external_managed` (PRD §15), `async` aunque
  PRD §15 los escriba síncronos: un proveedor real implica un viaje de red y este backend es
  async de punta a punta. Los argumentos y la semántica de §15 se respetan.
- THE SYSTEM SHALL devolver `None` desde `get_access_status` cuando el proveedor no conoce la
  reserva, y no una excepción: «el proveedor todavía no ha importado esta reserva» es una
  respuesta ordinaria durante la ventana entre que llega la reserva y el proveedor la importa.
- THE SYSTEM SHALL exponer en `AccessStatusResult` únicamente `status`, `external_id` y
  `code_masked`, y nunca el código en claro.
- THE SYSTEM SHALL hacer que los métodos de escritura tomen y devuelvan la entidad, de modo que la
  máquina de estados siga siendo el único sitio donde ocurre una transición y el argumento `code`
  muera dentro de la llamada.
- THE SYSTEM SHALL proveer `ManualAccessAdapter` —el operador introduce el código; sin visión del
  proveedor— y `MockAccessAdapter`, que se distingue **solo** en `get_access_status`, donde
  devuelve un estado externo con código demo enmascarado. `ManualAccessAdapter` es el que está
  cableado; el mock está marcado `EXTERNAL_DEPENDENCY` y no se usa en producción.
- THE SYSTEM SHALL mantener ambos en el `infrastructure/` de su dominio —no integran con nada— y
  reservar `app/integrations/` para los de proveedor real, donde ya viven los de PMS.
- THE SYSTEM SHALL confirmar la entrega (`DELIVERED`) llamando directamente a la entidad y no al
  puerto: es un hecho que registra el operador, no algo que el proveedor sepa.

**El proveedor es una decisión abierta y este puerto es lo que la protege**:
[ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md) decisión 5 reabrió lo que PRD §5.5
daba por cerrado — GrinPass no tiene API pública *todavía* pero es receptivo, y Beds24 aporta
TTLock/Nuki más una Arrivals API. Nada por encima de la interfaz puede asumir hacia dónde sale.
El adapter cableado es una sola línea de DI, señalada como tal.

### La entrega de notificaciones

- THE SYSTEM SHALL declarar el puerto `NotificationAdapter` de PRD §14 con
  `send(recipient_contact, subject, body, channel) -> NotificationResult`, `async` por la misma
  razón que el anterior, y SHALL contratar que **no lance nunca** por un fallo de entrega: el
  fallo vuelve como resultado, y las excepciones quedan para errores de programación.
- THE SYSTEM SHALL resolver el adapter por canal desde un registro explícito construido con
  antelación: `EMAIL` y `CONSOLE` → `ConsoleEmailAdapter`, `WHATSAPP` → `MockWhatsAppAdapter`,
  `IN_APP` → `InAppNotificationAdapter`. `PUSH` **no tiene entrada** a propósito — un marcador que
  informase de éxito marcaría `SENT` filas que nadie recibió.
- THE SYSTEM SHALL hacer que `InAppNotificationAdapter` no llame a nada y devuelva éxito: en el
  canal in-app **la fila es la entrega**, y lo que la hace legible es el endpoint de lectura. Si
  ese endpoint desapareciera, este adapter sería una mentira y tendría que irse con él.
- THE SYSTEM SHALL rechazar con `INVALID_RECIPIENT` un `recipient_contact` en blanco, en todos los
  adapters.
- THE SYSTEM SHALL registrar en el log de los adapters únicamente el canal y las **longitudes** de
  `subject`/`body`, y nunca su contenido ni el destinatario: desde R2 ese campo lleva el contacto
  del *huésped*, y registrarlo convertiría el log en un directorio de huéspedes por tenant.
- THE SYSTEM SHALL ejecutar `dispatch_notifications` cada minuto, seleccionando por tenant las
  filas `PENDING` de más antigua a más nueva y acotadas por el tamaño de lote.
- THE SYSTEM SHALL, por cada fila entregable, (1) incrementar `attempts` en uno y **comitear**,
  (2) invocar el adapter, y (3) escribir el resultado y comitear.
- WHEN la entrega tiene éxito, THE SYSTEM SHALL pasar la fila a `SENT`, fijar `sent_at` y limpiar
  `last_error`, y SHALL no marcar `SENT` ninguna fila cuya entrega no confirmó el adapter.
- IF la entrega falla y quedan intentos, THEN THE SYSTEM SHALL dejar la fila en `PENDING` para el
  siguiente tick; IF el intento alcanza `notification_max_attempts`, THEN THE SYSTEM SHALL pasarla
  a `FAILED` con código `MAX_ATTEMPTS_EXCEEDED`.
- IF no existe adapter para el canal de una fila, THEN THE SYSTEM SHALL pasarla directamente a
  `SKIPPED` con código `NO_ADAPTER_FOR_CHANNEL`, **sin invocar adapter alguno y sin consumir un
  intento**.
- IF el adapter lanza pese al contrato, THEN THE SYSTEM SHALL capturarlo, registrar únicamente el
  **nombre del tipo** de la excepción —nunca su mensaje ni la traza— y convertirlo en un fallo
  `ADAPTER_ERROR` que siga el camino normal.
- THE SYSTEM SHALL escopar cada ejecución por tenant con una sesión propia marcada, filtrar
  `tenant_id` explícitamente tanto en la lectura como en la escritura, y por tanto no cargar —ni
  poder entregar a— un `recipient_contact` de otro tenant.
- THE SYSTEM SHALL apoyar la exclusión mutua entre ejecuciones en el `task_lock` de Redis por
  nombre de tarea, con TTL de tres veces la cadencia, sin un estado `SENDING` intermedio y sin
  bloqueo de filas.

**El despachador no es el único camino de entrega.** `auth-account-recovery` es el segundo
escritor vivo de `notification_logs` y **no pasa por aquí**: invoca el adapter de canal `EMAIL`
de forma síncrona dentro de su propia petición HTTP y escribe la fila ya en `SENT` o `FAILED`,
con `attempts = 1`, **nunca en `PENDING`**. No es una excepción de conveniencia sino la única
forma de cumplir la regla 11 de `steering/security.md`: el despachador entrega *leyendo*
`subject`/`body`, y lo que esa notificación tiene que entregar es un enlace de recuperación, que
no puede quedar escrito ahí. Consecuencias que conviene conocer al leer una de esas filas:
guarda constantes sin enlace, así que registra **que se envió un aviso, no su contenido**; y un
fallo del adapter **no se reintenta**, porque un reintento del despachador entregaría el cuerpo
guardado, que no lleva enlace. El usuario vuelve a solicitar.

**Semántica declarada: at-least-once acotado.** Un proceso que muera entre la llamada al adapter
y la escritura del resultado puede reenviar esa fila en el siguiente tick, pero `attempts` ya
está persistido, así que el tope de reintentos **acota** los duplicados en vez de dejarlos sin
límite; el lock es lo que sostiene esa cota, porque dos ejecuciones solapadas quemarían cada una
su propio intento sobre la misma fila. Con adapters de consola y mock el daño es una línea de log
repetida; se revisará antes de conectar un SMTP real. **Sin backoff exponencial**: no hay columna
donde guardar el próximo intento y añadirla para un logger de consola sería esquema inventado por
adelantado.

La captura de excepciones existe aunque el puerto las prohíba porque sin ella coexistían dos
fallos: la traza llegaba al `logger.exception` del runner llevándose el texto del proveedor, y la
fila nunca alcanzaba `FAILED`, con lo que «at-least-once **acotado**» dejaba de estar acotado.

### `last_error` estructurado por construcción

- THE SYSTEM SHALL hacer que el campo de error de `NotificationResult` sea un
  `NotificationErrorCode` —enum cerrado: `ADAPTER_ERROR`, `INVALID_RECIPIENT`, `TIMEOUT`,
  `NO_ADAPTER_FOR_CHANNEL`, `MAX_ATTEMPTS_EXCEEDED`— y no SHALL llevar **ningún** campo de texto
  libre en ese tipo de retorno.
- THE SYSTEM SHALL serializar `last_error` como `{"code": …, "channel": …, "attempt": n}`, tres
  campos todos internos.
- THE SYSTEM SHALL rechazar en construcción un resultado entregado que traiga código de error, y
  uno fallido que no lo traiga: la escritura ramifica exactamente sobre esos dos campos, y un
  `last_error` nulo no le dice nada al operador.

Es la aplicación de la regla 11 de `steering/security.md` a la única columna de la que este change
es primer escritor. Que el tipo sea un enum es lo que impide que la excepción de un SDK —que
rutinariamente lleva incrustado el mensaje que no pudo enviar— acabe en la columna: el texto del
proveedor **no cabe** en el tipo de retorno, y ampliarlo es un diff que un revisor ve. Un campo
`provider_message_id: str | None` llegó a existir y el panel de seguridad lo retiró por ser
exactamente el agujero que este tipo existe para cerrar. Mismo patrón que `ChangeSet` en `audit`,
y por el mismo motivo: la regla 11 documenta que la disciplina repetida falló tres veces.

### El escalado de SLA deja de estar inerte, y responder cierra el plazo

- THE SYSTEM SHALL exponer `cancel_sla_deadline(tenant_id, related_type, related_id,
  notification_type)`, que pone `sla_deadline_at = NULL` en las filas que casan y **solo** eso: no
  toca `status`, `sla_breached`, `subject`, `body` ni `recipient_contact`. Devuelve el número de
  filas y **nunca** falla por no encontrar ninguna, a diferencia de las otras dos escrituras del
  repositorio.
- WHEN una limpiadora acepta o rechaza una tarea de limpieza, THE SYSTEM SHALL invocarlo con
  `related_type = "cleaning_task"`, `related_id = task.id` y
  `notification_type = CLEANING_TASK_ASSIGNED`, **antes del único `commit`** del caso de uso, de
  modo que la respuesta y el plazo cerrado sean una escritura o ninguna: una aceptación comiteada
  con el plazo vivo es exactamente el escalado que esto existe para evitar.
- THE SYSTEM SHALL conceder esa escritura únicamente a los dos casos de uso que **responden** a una
  asignación, y no a iniciar, cerrar ni validar: para entonces el plazo ya está cerrado.
- IF la tarea no tiene fila de asignación, o su plazo ya está cerrado, THEN THE SYSTEM SHALL
  completar la respuesta sin error, registrarlo a nivel informativo y no modificar nada: aquí cero
  filas es el caso normal, porque una tarea creada antes de este change no tiene plazo que anular.
- WHEN el plazo se cierra, THE SYSTEM SHALL sacar la fila de la consulta de candidatos por su
  condición `sla_deadline_at IS NOT NULL`, y no producir ningún escalado `SLA_BREACH` para esa
  tarea en ejecuciones posteriores.
- THE SYSTEM SHALL cerrar el plazo anulándolo y **no** marcándolo incumplido: `sla_breached = True`
  afirmaría un incumplimiento que no ocurrió y dispararía el escalado, y `status = SKIPPED`
  mentiría sobre la entrega de una notificación que sí se envió.

**`check_sla_breaches` cambió de comportamiento sin cambiar de código.** Su consulta exige
`status = SENT` y hasta este change nada escribía ese valor, así que cada ejecución encontraba
cero candidatos. El emisor lo alimenta. La consecuencia está aceptada y **medida**: las filas
`CLEANING_TASK_ASSIGNED` con plazo ya vencido pasan a ser candidatas en cuanto se entregan y se
escalan de golpe en el primer tick, con relación **1:1** (7 filas de plazo vencido → 0 candidatas
antes del emisor, 7 después, `breached=7`). Son incumplimientos que ocurrieron de verdad, así que
filtrarlos sería mentir sobre el pasado; el volumen del entorno real se sabe antes de desplegar con
`SELECT count(*) FROM notification_logs WHERE notification_type = 'CLEANING_TASK_ASSIGNED' AND
status = 'PENDING' AND sla_deadline_at < now()`.

### La bandeja in-app

- THE SYSTEM SHALL exponer `GET /api/v1/notifications` con el envelope paginado de PRD §23,
  devolviendo **solo** las filas dirigidas al usuario del token, de más nueva a más vieja —es una
  bandeja, no una cola. El identificador de usuario sale del JWT y no hay parámetro de ruta ni de
  consulta que ensanche el alcance.
- THE SYSTEM SHALL publicar en cada fila `id`, `notification_type`, `channel`, `status`, `subject`,
  `body`, `related_type`, `related_id`, `sent_at` y `created_at`, y SHALL retener
  `recipient_contact`, `last_error`, `sla_deadline_at` y `sla_breached`: el primero convertiría la
  bandeja en un directorio y los otros son diagnóstico de operación.
- THE SYSTEM SHALL **no** ofrecer «marcar como leída» ni añadir una columna `read_at`: PRD §7.24 no
  la declara y este change no inventa esquema para cerrar el ciclo. El frontend lleva su propio
  estado hasta que una entrada de roadmap decida lo contrario.

`subject` y `body` sí viajan: la máscara `****XX` es la excepción que la regla 11 concede
precisamente para que el destinatario pueda leer su aviso. El ciclo in-app queda a medias **a
propósito** —se listan, no se acusan—, y se deja dicho aquí para que el siguiente no lo lea como
olvido. Polling y no SSE: SSE es infraestructura de tiempo real que ninguna pantalla consume
todavía y que complica el despliegue detrás del ingress.

### La capa operativa de SES.Hospedajes

- THE SYSTEM SHALL declarar el puerto `SESHospedajesAdapter` de PRD §17 (`submit_guest`,
  `get_submission_status`) con una única implementación `MockSESHospedajesAdapter`, marcada
  `EXTERNAL_DEPENDENCY`, que simula una submission exitosa y cuyo fallo se dispara por un flag de
  constructor y **no** por un valor mágico en los datos: un número de documento mágico es una
  regla que alguien acaba tocando por accidente con datos de siembra reales.
- THE SYSTEM SHALL hacer que `submit_guest` no lance nunca por un rechazo, y devolver en su lugar
  `SubmissionResult(accepted, external_id, error_code)` cuyo `error_code` es de vocabulario
  cerrado y **nunca** el mensaje del proveedor: lo que una API de submission dice al fallar tiende
  a citar lo que se le envió, y aquí eso es un número de documento.
- THE SYSTEM SHALL mantener el estado del registro legal en
  `reservations.legal_registration_status`, porque el flujo de PRD §17 es **por estancia**.
- THE SYSTEM SHALL dejar `guests.legal_registration_status` en `NOT_REQUIRED` y **no escribirlo**:
  un huésped con dos estancias tendría dos valores y una sola columna. Lo que sí describe al
  huésped es `guests.document_status`, que este change mueve de `NOT_PROVIDED` a `PROVIDED` al
  recibir los datos. Se declara explícitamente para que el siguiente no lo lea como olvido;
  `guest-portal-api` puede revisarlo cuando traiga la captura por el huésped.
- WHEN el reconciliador de accesos ve una reserva confirmada y no cancelada, THE SYSTEM SHALL
  fijar su estado legal a `PENDING_GUEST_DATA` a través del puerto `LegalRegistrationInitialiser`,
  de un solo método, para que el barrido no importe el módulo de huéspedes. La escritura lleva
  `legal_registration_status = NOT_REQUIRED` en su propia condición, de modo que nunca arrastra
  hacia atrás una estancia ya `SUBMITTED`, `READY_TO_SUBMIT` o `FAILED`.
- WHEN están presentes los ocho datos mínimos de PRD §17 —`full_name`, `nationality`,
  `date_of_birth`, `document_type`, `document_number`, `document_expiry_date`, `check_in_date`,
  `check_out_date`— THE SYSTEM SHALL pasar el estado a `READY_TO_SUBMIT`; IF falta alguno, THEN
  SHALL mantenerlo en `PENDING_GUEST_DATA` y poder nombrar **cuáles** faltan, que es de lo que
  trata ese estado.
- THE SYSTEM SHALL evaluar esa condición en un servicio puro de dominio sobre la unión de huésped
  y reserva —`check_in_date`/`check_out_date` son de la reserva— que recibe la presencia del
  documento como **booleano** y nunca el valor: la comprobación de completitud no es uno de los
  sitios que tocan PII descifrada.
- THE SYSTEM SHALL mover ese cálculo **solo** entre `PENDING_GUEST_DATA` y `READY_TO_SUBMIT`, en
  ambos sentidos, y SHALL devolver sin tocar cualquier otro estado. Una estancia ya `SUBMITTED`,
  `FAILED` o `MANUAL_REVIEW` está más allá de esta pregunta, y recalcularla desde la presencia de
  campos dejaría que editar un teléfono deshiciera en silencio una presentación ante la policía.
  `NOT_REQUIRED` tampoco se toca: significa que nadie ha decidido aún que la estancia deba
  reportarse, y eso es del reconciliador.
- THE SYSTEM SHALL reevaluar la disponibilidad **solo** cuando la escritura de documento nombra
  explícitamente una reserva, y no propagar a las demás estancias del huésped.
- WHEN un rol autorizado ejecuta el envío sobre una reserva en `READY_TO_SUBMIT`, THE SYSTEM SHALL
  invocar el adapter, pasar el estado a `SUBMITTED` y escribir un `TimelineEvent`
  `LEGAL_REGISTRATION_SUBMITTED` cuyo `metadata` lleve solo el identificador de la reserva.
- IF el adapter devuelve un fallo, THEN THE SYSTEM SHALL pasar el estado a `FAILED`, encolar una
  notificación in-app `PENDING` a cada `PROPERTY_MANAGER` activo —o a los `TENANT_OWNER` si no hay
  ninguno—, auditarlo, y **no** escribir el evento de submission: sería una afirmación permanente
  de que la presentación ocurrió. La respuesta HTTP sigue siendo `200`, con `FAILED` en el cuerpo.
- IF la reserva no está en `READY_TO_SUBMIT`, no tiene huésped asociado, o su estado es
  `READY_TO_SUBMIT` pero una reevaluación encuentra huecos, THEN THE SYSTEM SHALL rechazar con
  `409` **sin invocar el adapter y sin escribir nada**: un proveedor real cobra por submission y
  presenta ante la policía, así que el orden importa. El mensaje nombra los campos que faltan y
  nunca sus valores.

**No hay submission real y no la habrá en el MVP** (PRD §29). Lo que existe es la capa operativa
completa detrás del mock, para que conectar el proveedor real sea un cambio de cableado. Antes de
adoptar Chekin —[ADR 0006](../../docs/adr/0006-pms-channel-manager-provider.md) decisión 4— hacen
falta DPA, política de retención y verificación de qué PII sale de verdad, porque se convierte en
**sub-encargado de datos personales**. **La regla 12 de `steering/security.md` (webhooks sin firma)
no está resuelta**: se deja dicho aquí para que el siguiente no lo crea. Sus webhooks
`PoliceRegistration.created|complete|error|retry_error` son un segundo endpoint entrante sin firma
sobre datos de registro policial, y llegan con la integración real.

**El tipo de notificación de fallo queda fuera de los dieciséis de PRD §14**, así que su escalado
resuelve a nada: una presentación fallida avisa a los managers y no escala a nadie. Es deliberado
—inventar un tipo del PRD sería peor— y queda anotado como deuda.

El enum `NotificationType` ya no tiene dieciséis miembros sino **diecisiete**:
`auth-account-recovery` añadió `PASSWORD_RESET_REQUESTED`, declarándolo como divergencia
explícita de PRD §14 igual que esta capacidad declaró sus dos jobs frente a los cuatro de
PRD §8.3. Ese decimoséptimo tampoco tiene escalado, y en su caso **no es deuda**: una
recuperación de contraseña no tiene plazo que incumplir, así que su fila se escribe sin
`sla_deadline_at` a propósito.

### Protección del dato de documento

- THE SYSTEM SHALL persistir `document_number` cifrado en reposo con Fernet, con IV aleatorio por
  llamada, en `guests.document_number_encrypted`, de modo que la columna no sea buscable por valor.
- THE SYSTEM SHALL no devolver el número en ningún listado: los listados viajan sobre un tipo que
  estructuralmente **no tiene** el campo, junto con `document_expiry_date`, `date_of_birth` ni
  `nationality`. Lo único que describe el documento en un listado es `document_status`.
- THE SYSTEM SHALL descifrarlo en exactamente dos sitios: la lectura explícita del documento y la
  construcción de la submission legal.
- THE SYSTEM SHALL aceptar los datos de documento **solo** por `PATCH /api/v1/guests/{id}/document`
  y no por el `PATCH` genérico de la reserva, que `OPAQUE_IN_TIMELINE` y `UPDATABLE_FIELDS`
  diseñaron precisamente para no llevar PII.
- THE SYSTEM SHALL hacer de `GET /api/v1/guests/{id}/document` el **único** endpoint que devuelve
  el número completo, y SHALL restringirlo a `TENANT_OWNER` y `PROPERTY_MANAGER`.
- WHEN un usuario accede al documento completo, THE SYSTEM SHALL escribir y **comitear** la fila de
  `AuditLog` `GUEST_DOCUMENT_READ` —quién, desde qué IP, qué y cuándo— **antes de producir el texto
  en claro**: si la escritura falla, la transacción revierte y quien llamó recibe un error en lugar
  de un documento. Es la única acción auditada del sistema que no registra una mutación.
- THE SYSTEM SHALL auditar la escritura como `GUEST_DOCUMENT_UPDATED` registrando **qué campos**
  cambiaron y nunca sus valores.
- THE SYSTEM SHALL impedir por construcción que `document_number`, `document_number_encrypted` y
  `date_of_birth` se registren como diferencia en la auditoría: están en la lista de campos
  redactados y pedir su diferencia **lanza un error de contrato**, no lo registra a medias.
- THE SYSTEM SHALL restringir además los nombres de campo auditables de un huésped a una lista
  blanca de columnas reales, y SHALL rechazar como valor auditable cualquier estructura compuesta,
  que podría esconder una clave denegada.
- THE SYSTEM SHALL no incluir `document_number`, fecha de nacimiento ni ningún dato de documento en
  `notification_logs.subject`, `body` ni `last_error`, ni en logs de aplicación.

**Dónde acaba la garantía estructural.** En `last_error` y en la auditoría el tipo lo impide. En
`notification_logs.subject`/`body` no: son cadenas libres, y lo que sostiene la regla aquí es que
el escritor que añadió esta capacidad fija un asunto constante y un cuerpo que solo lleva el
identificador de la
reserva, cubierto por un test que comprueba la ausencia del número y de la fecha de nacimiento —un
test que estuvo **vacío** hasta que el panel de QA vio que solo ejercitaba el camino de éxito, que
no encola ninguna notificación. En los logs de aplicación la garantía es igualmente convención más
revisión. Y `nationality` no está denegada: la frase de steering nombra el documento y la fecha de
nacimiento y ahí se detiene, así que su redacción es disciplina del caso de uso.

### Aislamiento, RBAC y contrato de API

- THE SYSTEM SHALL derivar el rol del token **dentro del caso de uso** y nunca de la petición,
  siguiendo el patrón `CleaningActor.restrict_to_cleaner_id`.
- THE SYSTEM SHALL filtrar `tenant_id` explícitamente en toda consulta y toda escritura de estos
  módulos, porque el filtro global de sesión no cubre los `INSERT` ni el mapa de identidad.
- IF se referencia un acceso, reserva, huésped o propiedad que existe pero pertenece a otro tenant,
  THEN THE SYSTEM SHALL responder `404` con un cuerpo **idéntico** al de un identificador
  inexistente: un `403` distinguible convertiría el endpoint en un oráculo de existencia entre
  tenants, y sobre un documento de identidad eso es lo último que puede ser.
- IF una entidad de otro tenant llega a una escritura como objeto, THEN THE SYSTEM SHALL fallar con
  un error interno (`500`) y no con un `4xx`: eso no es una petición mal formada sino un fallo de
  programación, y debe arreglarse, no manejarse.
- WHILE el solicitante tiene un rol sin el permiso de escritura correspondiente, THE SYSTEM SHALL
  admitir la lectura que sí tenga y rechazar la operación con `403`.
- THE SYSTEM SHALL acotar la paginación del listado de accesos y de la bandeja de notificaciones a
  `per_page` entre 1 y 100 (defecto 20) y `page` entre 1 y 100.000, respondiendo `422` fuera de
  rango. El techo de `page` existe porque se convierte en un `OFFSET` de SQL y un número de veinte
  cifras desbordaría el entero del driver en lugar de dar un `422`.
- THE SYSTEM SHALL rechazar con `422` todo cuerpo con campos no declarados, incluidos los de
  identidad como `tenant_id`.
- THE SYSTEM SHALL no ofrecer ninguna ruta que reciba el estado destino como dato: revocar y
  expirar ocurren solo en el barrido, y las transiciones del operador son rutas con nombre propio.
- THE SYSTEM SHALL repartir los permisos así, sin herencia por jerarquía —`ROLE_PERMISSIONS` es un
  mapa explícito por rol, no una cadena:

| Método | Ruta | Permiso | Quién lo tiene |
|---|---|---|---|
| GET | `/api/v1/access-records` (filtros `reservation_id`, `property_id`, `status`) | `READ_ACCESS_RECORDS` | owner, manager |
| GET | `/api/v1/access-records/{id}` | `READ_ACCESS_RECORDS` | owner, manager |
| POST | `/api/v1/access-records/{id}/manual-code` | `MANAGE_ACCESS_RECORDS` | manager |
| POST | `/api/v1/access-records/{id}/external` | `MANAGE_ACCESS_RECORDS` | manager |
| POST | `/api/v1/access-records/{id}/delivered` | `MANAGE_ACCESS_RECORDS` | manager |
| GET | `/api/v1/notifications` | `READ_OWN_NOTIFICATIONS` | cualquier rol autenticado |
| PATCH | `/api/v1/guests/{id}/document` | `MANAGE_GUEST_DOCUMENTS` | manager |
| GET | `/api/v1/guests/{id}/document` | `READ_GUEST_DOCUMENTS` | owner, manager |
| POST | `/api/v1/reservations/{id}/legal-registration/submit` | `SUBMIT_LEGAL_REGISTRATION` | manager |

- THE SYSTEM SHALL mantener las tres rutas legales en el router de huéspedes, incluida la de
  submission, para que todo lo que toca SES.Hospedajes esté en el fichero que un revisor abrirá el
  día que llegue Chekin. PRD §23 no declara ninguna de estas rutas: son de este change.

**El owner lee y no opera**: PRD §6 le da «ver sus propiedades y reservas» y al manager «acceder a
todos los datos operativos»; registrar el código y presentar a SES.Hospedajes son operación. Es el
mismo corte que `reservations` y `properties-crud` ya hicieron.

**`READ_OWN_NOTIFICATIONS` es autoservicio y no una capacidad de rol**: el endpoint devuelve las
filas dirigidas a quien llama, así que una limpiadora lo necesita exactamente igual que un owner.
El scoping ocurre en el repositorio, que es lo que permite que el permiso sea universal sin ser una
fuga.

**`SUPER_ADMIN` no recibe ninguno de los cinco, ni siquiera `READ_GUEST_DOCUMENTS`, que PRD §17 sí
le nombra.** Esa frase del PRD es un **techo** —dice quién *puede* ver un documento— y la tabla
sigue decidiendo quién lo hace. `SUPER_ADMIN` no tiene rol operativo dentro de un tenant en ninguna
parte del sistema: sus poderes de PRD §6 son globales y la visibilidad cross-tenant está aplazada a
`saas-cross-tenant`. Concederlo aquí pre-decidiría esa entrada sobre el dato más sensible del
sistema. No se incumple §17: ningún rol fuera de sus tres ve un documento, y retirar es más
estrecho que el techo.

**`SUBMIT_LEGAL_REGISTRATION` es un permiso aparte** para que un operador pueda presentar sin que
se le muestre nunca el número. Hoy ningún rol ejercita esa separación —el manager los tiene los
tres—, pero la separación existe para cuando alguno la necesite.

### Configuración y calendario

- THE SYSTEM SHALL leer `NOTIFICATION_MAX_ATTEMPTS` (defecto 3) y `NOTIFICATION_BATCH_SIZE`
  (defecto 100) de la configuración, declarados en `.env.example`, y SHALL usar el segundo también
  como tamaño de lote del barrido de accesos.
- THE SYSTEM SHALL no añadir ningún secreto: los adapters son consola y mocks, y las variables de
  un WhatsApp o un SMTP reales quedan reservadas por la regla 8 de `steering/security.md`.
- THE SYSTEM SHALL registrar en la tabla única de cadencias `dispatch_notifications` cada minuto y
  `provision_access_records` cada 5 minutos, de modo que `beat_schedule` y el TTL del lock sigan
  derivándose de la misma fuente.

`dispatch_notifications` va a un minuto y no más lento porque una fila solo puede incumplir su
plazo **después** de entregarse: un emisor más lento retrasaría cada escalado en su propia
cadencia.

**Divergencia declarada**: PRD §8.3 nombra cuatro jobs periódicos y estos son el quinto y el sexto.
El PRD dice qué debe ocurrir, no qué lo dispara, así que nombrarlos es una decisión de este change
y no una contradicción. Los nombres de los cuatro originales no se tocan.

## Estado y deuda conocida

- **No hay adapters reales de envío.** `ConsoleEmailAdapter` registra en el log y
  `MockWhatsAppAdapter` es un mock marcado `EXTERNAL_DEPENDENCY`; SMTP y WhatsApp reales llegan con
  `hardening-release`. **Desde `auth-account-recovery` esto ya no solo retrasa avisos operativos:
  deja sin entregar una credencial.** Los enlaces de recuperación salen por el canal `EMAIL`, que
  resuelve a `ConsoleEmailAdapter`, y la regla de arriba le prohíbe registrar contenido y
  destinatario — así que el enlace no puede leerse del log **ni siquiera en desarrollo**. Hasta
  que llegue el adapter SMTP real, la vía que de verdad recupera una cuenta es el comando
  `python -m app.cli.reset_password`.
- **`sent_at` es la marca de tiempo de la ejecución**, no el instante exacto del envío: el job toma
  un único `now` para todo el recorrido del tenant.
- **Un fallo de presentación legal no escala a nadie**, porque su tipo de notificación queda fuera
  de los dieciséis de PRD §14 y no tiene escalado definido. Avisa a los managers y ahí acaba.
- **No hay `PhoneAdapter`** ni la rama `TECHNICIAN_ASSIGNED + CRITICAL` de PRD §14: no existe puerto
  ni implementación, `escalation.py:44` deja constancia, y sigue escalando al manager.
- **Catorce tipos de notificación siguen sin escalado definido**. Cada uno recibe el suyo en el
  change que le da un `sla_deadline_at`, no aquí. El decimoséptimo miembro del enum
  (`PASSWORD_RESET_REQUESTED`, de `auth-account-recovery`) no cuenta entre ellos: no tener plazo
  es su comportamiento correcto, no una pieza pendiente.
- **Valores de enum sin escritor**: `LegalRegistrationStatus.MANUAL_REVIEW` no lo escribe nadie, y
  de `GuestDocumentStatus` solo se alcanza `PROVIDED` —`PENDING`, `VERIFIED` y `REJECTED` no tienen
  camino. `MockSESHospedajesAdapter.get_submission_status` solo devuelve `ACCEPTED` o `UNKNOWN`.
- **`AccessRecord.expire()` es un camino no ejercitado**: nada escribe `valid_from`/`valid_to`.
- **`MockAccessAdapter` es código muerto en producción**: solo lo referencian los tests.
- **No hay lógica basada en apertura de puerta** (`DoorSensorAdapter`, `DOOR_OPENED_SENSOR`): PRD
  §15 y §29 la excluyen, y `steering/architecture.md` la lista entre los anti-patrones.
- **La captura de los datos del huésped por el propio huésped** —token web, formulario de check-in—
  es `guest-portal-api`, que declara `needs: access-notifications` precisamente por esto. Aquí los
  datos los introduce el operador o llegan del PMS.
- **No hay frontend**: las pantallas de accesos, la bandeja de notificaciones y los formularios de
  registro legal son `field-apps` y `dashboard-web`.
- **No hay endpoints de listado de huéspedes**: las tres rutas legales son de entidad única.
- **Ninguna tabla nueva ni enum ampliado**: las seis implicadas (`access_records`,
  `notification_logs`, `guests`, `reservations`, `audit_logs`, `timeline_events`) ya existían con
  todas sus columnas.

## Key files

- `backend/app/access/domain/` — `entities.py` (máquina de estados), `enums.py`, `ports.py`
  (`AccessProviderAdapter`, `LegalRegistrationInitialiser`), `masking.py`, `repositories.py`,
  `exceptions.py`
- `backend/app/access/application/use_cases.py` — `RegisterManualAccessCodeUseCase`,
  `MarkAccessExternallyManagedUseCase`, `MarkAccessDeliveredUseCase`, `ListAccessRecordsUseCase`,
  `GetAccessRecordUseCase`, `ProvisionAccessRecordsUseCase`
- `backend/app/access/infrastructure/` — `repositories.py` (incluida la proyección a
  `reservations.access_status`), `adapters.py` (`ManualAccessAdapter`, `MockAccessAdapter`)
- `backend/app/access/api/` — `router.py`, `schemas.py`, `dependencies.py`, `errors.py`
- `backend/app/notifications/domain/` — `ports.py` (`NotificationAdapter`), `results.py`
  (`NotificationResult`, `NotificationErrorCode`), `repositories.py` (`cancel_sla_deadline`)
- `backend/app/notifications/infrastructure/adapters.py` — registro de canales
- `backend/app/notifications/application/use_cases.py` — `DispatchPendingNotificationsUseCase` y la
  lectura in-app
- `backend/app/notifications/api/router.py` — `GET /api/v1/notifications`
- `backend/app/guests/domain/legal_registration.py` — los ocho campos de PRD §17, `missing_fields`
  y `status_for`
- `backend/app/guests/domain/ports.py` — `SESHospedajesAdapter`, `LegalSubmission`,
  `SubmissionResult`
- `backend/app/guests/infrastructure/` — `adapters.py` (`MockSESHospedajesAdapter`), `legal.py`
  (`SqlAlchemyLegalRegistrationInitialiser`)
- `backend/app/guests/application/use_cases.py` — `SetGuestDocumentUseCase`,
  `ReadGuestDocumentUseCase`, `SubmitLegalRegistrationUseCase`
- `backend/app/guests/api/router.py` — las tres rutas legales
- `backend/app/audit/domain/value_objects.py` — campos redactados y lista blanca auditable
- `backend/app/scheduler/tasks.py`, `schedule.py` — `dispatch_notifications`,
  `provision_access_records` y sus cadencias
- `backend/app/auth/domain/policy.py` — los cinco permisos nuevos y su reparto
- `backend/app/cleaning/application/use_cases.py` — el cierre del plazo al aceptar/rechazar
