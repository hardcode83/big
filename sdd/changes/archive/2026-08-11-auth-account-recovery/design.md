# Design: auth-account-recovery

## Context

Todo lo que este change necesita ya existe en `backend/app/auth/`, montado por `auth-tenancy` y
ampliado por `user-management`: el hasher bcrypt en hilos con cota de concurrencia
(`infrastructure/password_hasher.py`), el throttle por IP y el bloqueo por cuenta en Redis
(`infrastructure/throttle.py`, claves `login:ip:<ip>`, `login:fail:<uid>`, `login:lock:<uid>`), la
revocación de familias de refresh (`SessionRepository.revoke_all_for_user`, con la razón
`PASSWORD_RESET` ya en el enum), la única consulta sin scope del sistema
(`UserRepository.find_by_email_globally`) y la escritura auditada por construcción
(`app/audit/domain/`: `ChangeSet` ligado a `entity_type`, `AuditLogFactory`, vocabulario cerrado
en `actions.py`).

La entidad `User` (`domain/entities.py`) es un dataclass cuyos campos mutables tienen cada uno un
método propietario, y `tests/auth/test_entities.py:304` deriva ese conjunto de
`User.__dataclass_fields__` — nombrando literalmente `must_change_password` como el caso que
vendría después. La autenticación de cada petición pasa por `get_authenticated_request`
(`api/dependencies.py`), que recarga usuario y tenant de la base de datos y deja el
`RequestContext`; `require(permission)` cuelga de ella y etiqueta su closure con el permiso.

Del lado de notificaciones, `app/notifications/` tiene el puerto `NotificationAdapter`
(`domain/ports.py`), el registro de canales (`infrastructure/adapters.py`: `EMAIL` y `CONSOLE` →
`ConsoleEmailAdapter`), el puerto de persistencia `NotificationLogRepository` (`domain/repositories.py`)
y el emisor asíncrono `DispatchPendingNotificationsUseCase`, que **solo recoge filas `PENDING`**
(`list_pending`) y entrega leyendo `subject`/`body`. `NotificationType` (`domain/enums.py`) tiene
hoy los dieciséis nombres de PRD §14.

Nada de esto se reescribe. El change añade un endpoint autenticado y dos anónimos bajo
`/api/v1/auth/`, una tabla, una columna y una política, sobre esas piezas.

## Decisions

### D1 — El token de recuperación se guarda como SHA-256 y se consume con una única sentencia condicional

**Chosen:** el token es `secrets.token_urlsafe(32)` (256 bits); la fila guarda
`sha256(token)` en hexadecimal bajo índice único, y el consumo es un
`UPDATE password_reset_tokens SET used_at = :now WHERE token_hash = :h AND used_at IS NULL AND
revoked_at IS NULL AND expires_at > :now RETURNING user_id, tenant_id`, comprobando `rowcount`.

Las dos mitades se sostienen la una a la otra, y por eso son una sola decisión: **un hash
determinista es lo único que permite la sentencia condicional de R3.2**. Con bcrypt —salado por
diseño— no se puede buscar la fila por el valor presentado, así que habría que leer todas las
candidatas y verificarlas una a una en Python: exactamente la separación entre comprobación y
escritura que R3.2 prohíbe y que `auth-tenancy` ya rechazó para la rotación de refresh. Y SHA-256
basta porque lo que protege un KDF lento es un secreto de baja entropía; 256 bits de `secrets` no
son adivinables, así que bcrypt aquí solo añadiría 250 ms de CPU **en un endpoint anónimo**, es
decir una palanca de agotamiento de CPU donde antes no la había. R4.1 queda cumplida: de
`sha256(token)` no se reconstruye el token.

Rejected: guardar bcrypt del token — imposibilita el `UPDATE` condicional de R3.2 y pone un coste
CPU alto en superficie anónima.
Rejected: guardar el token cifrado con Fernet — es reconstruible con la clave, que es justo lo que
R4.1 prohíbe.
Rejected: un JWT firmado sin fila — un solo uso exige estado en servidor; la firma no lo da.

### D2 — El enlace no viaja por `notification_logs`: se envía en la misma petición y la fila queda redactada

**Chosen:** el caso de uso compone el correo (asunto + cuerpo con el enlace) y llama
**síncronamente** al `NotificationAdapter` del canal `EMAIL` que ya resuelve
`adapter_registry()`. Después escribe la fila de `notification_logs` con el **resultado** de esa
llamada (`SENT` con `sent_at` y `attempts = 1`, o `FAILED` con su `NotificationErrorCode`), un
`subject` constante y un `body` constante **sin enlace**. Lo que se envía y lo que se guarda son
dos textos distintos producidos por dos funciones distintas de `app/auth/domain/recovery_messages.py`.

Esta es la restricción que R4.2 señala como la más dura del change, y la razón por la que no
puede resolverse de otra forma: el emisor asíncrono entrega leyendo `subject`/`body`, así que
para que entregase el enlace habría que escribirlo ahí — prohibido por la regla 11 de
`steering/security.md`, cuya única excepción es la forma `****XX` de un código de acceso— o
persistir el token en algún sitio recuperable hasta el siguiente tick, prohibido por R4.1. En
cuanto el token no puede sobrevivir a la petición, **el envío tiene que ocurrir dentro de ella**.

Detalle que decide la corrección, y no es cosmético: la fila se escribe ya en `SENT`/`FAILED` y
**nunca en `PENDING`**. `list_pending` es la cola del dispatcher; una fila `PENDING` sería
recogida en el siguiente minuto y entregaría el cuerpo *almacenado* —el que no lleva enlace—,
mandando al usuario un correo inútil. Escribir el estado final es además honesto: el adapter ya
respondió. R6.2 se cumple dejando `sla_deadline_at` nulo, con lo que `escalation_for` no la ve y
el job de SLA no la escala.

Consecuencia aceptada: para este único tipo de notificación, la fila registra **que se envió un
aviso**, no su contenido. Se declara en `specs/access-notifications.md` al archivar.

Rejected: escribir el enlace en `body` y dejar que lo entregue el dispatcher — viola la regla 11
frontalmente.
Rejected: guardar el token en Redis con TTL y que el dispatcher lo resuelva — un sumidero más
para el mismo secreto, y R4.1 habla de que el token no sea reconstruible, no de en qué motor.
Rejected: enviar en un `BackgroundTask` posterior a la respuesta — quita el oráculo de latencia
(ver D8) pero la sesión de base de datos ya está cerrada cuando corre, así que el resultado del
envío no se podría registrar en la misma transacción.

### D3 — El consumo del token es la **segunda** consulta sin scope de tenant, nombrada como tal

**Chosen:** `PasswordResetTokenRepository.consume_globally(token_hash, now)` no recibe
`tenant_id`: el token es la credencial y su índice único lo identifica en toda la instalación; el
`tenant_id` se deriva de la fila encontrada. Es el mismo patrón —y el mismo motivo— que
`find_by_email_globally`: el endpoint es anónimo, no hay tenant todavía.

Lo que cambia respecto a lo que hoy afirma `specs/auth-tenancy.md` («la única consulta sin scope
de tenant del sistema») es que pasan a ser **dos**, ambas nombradas de forma que la auditoría por
`grep` siga siendo exhaustiva. La spec se corrige al archivar. `count_live` y `revoke_other_live`
sí van scopadas por tenant, porque para entonces ya se conoce.

Rejected: incrustar el `tenant_id` en el token (`<tenant>.<secreto>`) para que la consulta fuese
scopada — el scope lo aportaría el propio atacante, así que sería aislamiento aparente; y alarga
el enlace sin comprar nada.

### D4 — Política de contraseña: mínimo 12 caracteres y tope de 72 bytes, sin reglas de composición, y el mínimo **no** es configurable

**Chosen:** `app/auth/domain/password_policy.py`, función pura
`assert_password_acceptable(password)`, con dos reglas: `len(password) >= 12` y
`len(password.encode("utf-8")) <= 72`. Sin exigencia de clases de caracteres.

El tope no es cosmético: `auth-tenancy` **rechaza** al crear el hash toda contraseña de más de 72
bytes en vez de truncarla, así que sin validación en el borde eso saldría como error no mapeado
en lugar de como `422`. Se reutiliza la excepción que ya existe para eso, `PasswordTooLongError`,
que ya mapea a `422 VALIDATION_ERROR`.

El mínimo es una **constante de dominio y no un ajuste de entorno** porque R1.6 obliga a aceptar
sin excepción todo lo que genera `app/auth/domain/passwords.py` (16 caracteres): un despliegue
que pusiera el mínimo en 20 haría que el sistema rechazara las contraseñas que él mismo emite. Un
test afirma `TEMPORARY_PASSWORD_LENGTH >= PASSWORD_MIN_LENGTH` para que ese acoplamiento falle en
la suite si alguien mueve uno de los dos.

Sin reglas de composición porque no aportan y sí quitan: obligarían a describirlas al usuario y
rechazarían frases largas, mientras que el generador ya garantiza sus tres clases por su propia
cuenta. Que el generador las garantice y la política no las exija es asimetría deliberada, no un
descuido: la garantía existe para no ser rechazado, no para ser copiada aquí.

Rejected: mínimo 8 — por debajo de cualquier recomendación vigente para una credencial sin 2FA.
Rejected: exigir dígito + mayúscula + minúscula — no mide fuerza y prohíbe contraseñas mejores.
Rejected: lista de contraseñas comunes — dependencia nueva y un fichero de datos, fuera de alcance.

### D5 — `must_change_password` lo escribe el mismo método que escribe el hash

**Chosen:** `User.set_password_hash(password_hash, *, temporary: bool)` fija los dos campos a la
vez, y `User.create(..., must_change_password: bool = False)` lo acepta en el alta. `FIELD_OWNERS`
de `tests/auth/test_entities.py` gana la entrada `must_change_password → set_password_hash`.

Un solo método para los dos campos es lo que impide que la bandera se desacople del hash: no
existe camino por el que se reemplace la contraseña sin decidir si es temporal. Los cuatro
escritores quedan así — `CreateUserUseCase` y `ResetUserPasswordUseCase` de `user-management`
pasan `temporary=True` (R5.2); el cambio propio (R1) y el consumo del token (R3) pasan
`temporary=False` (R5.3). El bootstrap no pasa por aquí: construye `UserModel` directamente
(`app/cli/bootstrap.py:153`) y sus contraseñas las elige una persona, así que la columna se queda
en su `server_default` falso, que es lo correcto.

Rejected: un método propio `require_password_change()` — dos métodos que deben llamarse juntos son
dos que alguien llamará por separado, y el test de campos mutables sólo exige que exista uno.
Rejected: derivar la bandera de una marca temporal (`password_set_by_admin_at`) — columna nueva
para expresar un booleano.

### D6 — El bloqueo por `must_change_password` vive en `get_authenticated_request`, con una lista explícita de rutas exentas

**Chosen:** `get_authenticated_request` compara `(método, path)` de la petición contra un conjunto
`PASSWORD_CHANGE_EXEMPT` —`GET /api/v1/auth/me`, `POST /api/v1/auth/logout`,
`POST /api/v1/auth/change-password`— y lanza `PasswordChangeRequiredError` (403, código nuevo
`PASSWORD_CHANGE_REQUIRED`) cuando la bandera está puesta y la ruta no está en él.

Es el único punto por el que pasan **todas** las peticiones autenticadas, y ya tiene delante la
entidad `User` recargada de la base de datos, así que la bandera está disponible sin una consulta
extra. El conjunto es de pares `(método, path)` y no de paths, por el mismo motivo por el que lo
es la lista de endpoints anónimos de `tests/test_route_authorization.py`: por path solo, un
`GET` heredaría la exención de un `POST` homónimo. Un test estructural comprueba que cada entrada
del conjunto corresponde a una ruta registrada, para que un renombrado no deje una exención
apuntando al vacío — ni, peor, un endpoint exento por accidente.

`POST /api/v1/auth/refresh` no atraviesa esta dependencia y por tanto no queda bloqueado, que es
lo que R5.5 pide: sin sesión no habría forma de llamar al endpoint de cambio.

Rejected: middleware ASGI — correría antes de resolver dependencias, así que tendría que decodificar
el token y recargar el usuario por su cuenta, duplicando la revalidación de `auth-tenancy`.
Rejected: comprobarlo dentro de `require(permission)` — no cubre un endpoint futuro escrito con
`AuthenticatedDep`, que es público, y es el mismo agujero que el docstring de `require` documenta.

### D7 — La cota por cuenta de R2.5 son los tokens **vivos** en la tabla, no un contador en Redis

**Chosen (enmendado en `run`, 2026-08-10):** antes de emitir, `count_live(tenant_id, user_id, now)`
cuenta las filas sin usar, sin revocar y no expiradas de esa cuenta; si alcanza
`PASSWORD_RESET_MAX_LIVE_TOKENS` (3 por defecto), **se revoca el enlace vivo más antiguo y se emite
el nuevo** —`revoke_oldest_beyond(tenant_id, user_id, keep_newest, now)`, una sola sentencia— de
modo que la cuenta nunca acumula más de la cota y una solicitud legítima nunca se queda sin
respuesta.

**La versión original descartaba la solicitud, y era explotable al revés.** Lo levantó el panel de
seguridad de la sección 6 y lo aprobó Jose. Quien conociera una dirección gastaba tres peticiones
—dentro del presupuesto de 10/min por IP— y durante los 30 minutos de vida del token toda
recuperación real del titular devolvía el mismo `202` sin enviar nada; por R2.2 la víctima no
recibía señal, y recargando al expirar la supresión era indefinida. La cota anulaba exactamente la
capacidad que este change existe para dar, y la única salida era una temporal emitida por un
administrador. Revocar el más antiguo conserva las dos propiedades que la cota compraba —cuántos
enlaces válidos coexisten, y cuánto correo puede provocar un atacante desde IPs distintas, que lo
sigue acotando el presupuesto por IP— y elimina la supresión.

**Margen de gracia (segunda enmienda de `run`, 2026-08-10, aprobada por Jose).** Revocar-el-más-
antiguo sin más quitaba dos propiedades que descartar sí daba, y el panel de seguridad las midió:
el correo por cuenta dejaba de estar acotado entre IPs (un presupuesto **por IP** no acota un total
**por cuenta**), y un atacante a ~3 peticiones/minuto retiraba el enlace del titular unos 20
segundos después de emitirlo. Así que `revoke_oldest_beyond` recibe además `older_than` y **no
revoca ningún enlace vivo más joven que `PASSWORD_RESET_GRACE_MINUTES`** (2 por defecto); si no
queda ninguno revocable —todos los vivos están dentro del margen— la solicitud se descarta en
silencio, como antes.

Un solo mecanismo para las dos: el enlace recién enviado es irrevocable durante la ventana en que
alguien lo pulsa, y el correo por cuenta vuelve a estar acotado a la cota por ventana de gracia.
Lo que reaparece es un camino que descarta, pero acotado a 2 minutos en vez de a los 30 de la vida
del token — y con el titular, que acaba de recibir un enlace válido, como el beneficiario del
descarte en lugar de su víctima.

El margen **tiene que ser mucho menor que la vida del token**, o nada sería nunca revocable y la
cota volvería a ser un descarte permanente: `Settings` lo valida
(`password_reset_grace_minutes < password_reset_token_minutes`) en vez de dejarlo a la disciplina
del despliegue, por el mismo motivo por el que D4 ata el mínimo de contraseña al generador.

**La cota es «check-then-act» y NO es a prueba de carreras. Medido**: el panel de QA de la sección
6 lanzó 8 peticiones concurrentes para una misma cuenta con cota 3 y obtuvo **8 tokens vivos**;
secuencialmente se detiene en 3 correctamente. `count_live` es un `SELECT count()` sin bloqueo, y
entre él y el `INSERT` no hay nada que serialice a dos llamantes. Se acepta así, y la afirmación
correcta es la de abajo, no «nunca más de la cota»:

- Lo que acota de verdad el volumen —correo enviado y tokens creados— es el **presupuesto por IP**
  de R2.4, que es la defensa que esta regla siempre tuvo delante. La cota por cuenta ordena y
  recorta, no serializa.
- Que coexistan más enlaces de los previstos no le sirve a un atacante para adivinar ninguno: cada
  uno son 256 bits de `secrets`, así que tener diez en vez de tres no mejora sus probabilidades.
- Cerrarlo pediría un `SELECT … FOR UPDATE` sobre la cuenta o un bloqueo por advisory lock en
  superficie **anónima**, es decir un candado que cualquiera en internet puede hacer tomar. Eso es
  peor que el problema: convierte una cota de volumen en un punto de contención.

Si algún día hace falta, la salida es el mismo `lock_tenant_for_admin` que `user-management` usa
para la regla del último propietario, no un contador nuevo.

Rejected (en la enmienda): cambiar la clave a una ventana de tiempo por cuenta en Redis —acortaría
la supresión pero no la elimina, introduce el segundo almacén que esta misma decisión ya había
descartado, y deja de acotar cuántos enlaces coexisten. Ofrecido a Jose y descartado.
Rejected (en la enmienda): aceptar la supresión como limitación conocida — es la funcionalidad
central del change, sin señal para quien la sufre. Ofrecido y descartado.

Acota dos cosas con un solo mecanismo: cuántos correos puede provocar un atacante desde IPs
distintas (tres por ventana de vida del token) y cuántos enlaces válidos coexisten para una misma
cuenta, que es una propiedad de seguridad por derecho propio. Y no necesita almacén nuevo: la
tabla ya tiene el índice por `(tenant_id, user_id)` que la consulta usa. R2.5 exige que la cota no
sea observable, y no lo es: el camino de la cota y el de la emisión terminan en la misma respuesta.

Rejected: ventana por cuenta en Redis (p. ej. 3/hora) — segundo almacén para un dato que la tabla
ya tiene, y desacoplado de la vida real del token.

### D8 — El levantamiento del bloqueo por cuenta ocurre **después** del commit, y no es transaccional

**Chosen:** R3.5(c) se implementa con un método nuevo del puerto,
`LoginThrottle.clear_account_lock(user_id)`, que borra `login:fail:<uid>` y `login:lock:<uid>`; se
llama **tras** el `commit` del caso de uso y su fallo se registra como aviso sin tumbar la
operación.

Redis y Postgres no comparten transacción, así que hay que elegir qué se pierde en el fallo de uno
de los dos. Limpiar antes del commit desbloquearía una cuenta cuya contraseña no llegó a cambiar;
limpiar después deja, en el peor caso, un bloqueo que caduca solo en 15 minutos sobre una cuenta
ya recuperada. La segunda es la degradación benigna. `reset_failures` se queda como está para el
camino de login, que sólo necesita el contador.

Rejected: reutilizar `reset_failures` — sólo borra el contador, no la clave de bloqueo, así que
dejaría al recién recuperado rechazado por el mismo `401` genérico durante 15 minutos, que es
justo lo que R3.5(c) existe para evitar.

### D9 — Auditoría: dos acciones nuevas para las dos mutaciones; la **solicitud** no se audita

**Chosen:** `USER_PASSWORD_CHANGED` (R1) y `USER_PASSWORD_RECOVERED` (R3) se añaden a
`app/audit/domain/actions.py` y a `ACTIONS`; ambas se escriben con
`ChangeSet(ENTITY_USER).redacted("password")` más, cuando cambia, el diff de
`must_change_password`, que se añade a `AUDITABLE_FIELDS["USER"]`. `POST /auth/forgot-password`
**no** escribe `AuditLog`.

La solicitud no muta nada del usuario, y `user-management` ya fijó el criterio: «`audit_logs` es
evidencia de cambios, no de peticiones». Además es superficie anónima, y auditar ahí sería dejar
que internet dictara el ritmo de crecimiento de la tabla. Queda registrada en el log de aplicación
por R2.6. `must_change_password` es auditable como diff y no redactado porque es un booleano de
estado, no un valor de la regla 3.

En R3 el actor **es** el propio usuario: `actor_user_id = user.id` (conocido tras consumir el
token) y `actor_ip` por el `get_client_ip` de siempre. En R1 sale del `RequestContext`.

Rejected: reutilizar `USER_PASSWORD_RESET` para los tres caminos — la regla 9 sólo es auditable si
la operación se encuentra filtrando por `action`; distinguir «un administrador la reseteó» de «el
propio usuario se recuperó» es exactamente lo que un repaso de incidente pregunta.

### D10 — El reset consume el token **primero** y valida la cuenta después

**Chosen:** el orden de `POST /auth/reset-password` es: throttle por IP → validar la política de
contraseña (puro, sin E/S) → `consume_globally` → cargar el usuario con `get_active_by_id` → si no
resuelve, mismo error indistinguible.

Consumir antes de validar la cuenta significa que un token presentado sobre una cuenta desactivada
se quema. Es el resultado deseado: un enlace presentado es un enlace gastado, y la alternativa
—comprobar el estado antes de escribir— reintroduce la lectura-antes-de-escritura que R3.2
prohíbe. Validar la política antes de tocar la base de datos evita quemar un token por una
contraseña débil, y ordena el gasto de CPU: el hash bcrypt (~250 ms) sólo se paga **después** de
que un token válido haya ganado su `UPDATE`, de modo que el endpoint anónimo no es un molinillo de
CPU para quien no tiene token.

Rejected: comprobar usuario y tenant antes de consumir — carrera prohibida por R3.2.

### D11 — La comparación «nueva igual a la actual» se hace en claro y sólo en R1

**Chosen:** en `change-password` las dos contraseñas están en el cuerpo, así que la comprobación de
R1.7 es una comparación de cadenas después de haber verificado la actual — exacta y gratis. En
`reset-password` **no se comprueba**: no hay contraseña actual presentada y averiguarlo exigiría un
`verify` bcrypt adicional en superficie anónima.

R1.7 está redactada dentro de R1 y no se extiende a R3, y la asimetría tiene sentido: lo que R1.7
evita es revocar todas las sesiones sin rotar nada, y quien completa una recuperación quiere
precisamente revocarlas.

Rejected: `verify(nueva, hash_actual)` también en el reset — coste bcrypt en anónimo por una
comprobación que R3 no pide.

### D12 — La vía de operación de R6.5 es un comando de CLI, y el `ConsoleEmailAdapter` **no** se toca

**Chosen:** `python -m app.cli.reset_password --email <dirección>` genera una temporal con
`generate_temporary_password()`, la escribe con `set_password_hash(..., temporary=True)`, revoca
las familias de refresh con `PASSWORD_RESET`, limpia el bloqueo por cuenta, escribe un `AuditLog`
`USER_PASSWORD_RESET` con `actor_user_id = NULL` y **la imprime una sola vez** por salida estándar.
Se documenta en `docs/auth-account-recovery.md` y en `infra/environments/dev/RUNBOOK.md`.

Es lo que sustituye al SQL improvisado que hoy es la única salida para un `TENANT_OWNER` bloqueado.
No abre superficie: quien puede ejecutarlo ya tiene shell en el host y por tanto acceso completo a
la base de datos; lo que aporta es que la operación pase por la entidad, revoque las sesiones y
deje rastro, tres cosas que un `UPDATE` a mano no hace. Reutiliza la acción de auditoría existente
porque es exactamente un reset asistido, sólo que por otra puerta. La fila va sin actor, como las
de `pms-provider-resolution`: el comando no tiene identidad que registrar.

**El `ConsoleEmailAdapter` se queda como está**, y esa es la otra mitad de la decisión que R6.5
delega en el diseño. Registrar el enlace en el log lo pondría en un sumidero sin retención, sin
scope de tenant y sin auditoría —el razonamiento con el que la regla 11 gobierna las columnas, con
la agravante de que aquí el valor es una credencial viva—, y contradiría literalmente la prohibición
que `specs/access-notifications.md` impone a ese adapter. Consecuencia declarada: **el flujo R2/R3
no se puede ejercitar a mano en dev** hasta que llegue el adapter SMTP; se ejercita en la suite,
donde el `NotificationAdapter` es un doble que captura lo enviado.

Rejected: un flag `--print-link` o una variable `DEV_LOG_RECOVERY_LINK` — un interruptor que
imprime credenciales es un interruptor que acabará puesto en un entorno que no es dev.
Rejected: documentar el SQL — es exactamente lo que este change existe para retirar.

### D13 — Configuración nueva, y qué se reserva sin usar

**Chosen:** tres ajustes en `Settings` con valor por defecto y sin sensibilidad —
`PASSWORD_RESET_TOKEN_MINUTES=30`, `PASSWORD_RESET_MAX_LIVE_TOKENS=3`,
`FRONTEND_BASE_URL=http://localhost:3000`— y seis nombres **reservados sin valor** para el SMTP
que llegará con `hardening-release`: `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`,
`SMTP_FROM_EMAIL`, `SMTP_USE_TLS`.

**Son cuatro, no tres, desde la enmienda del margen de gracia de D7** (`run`, 2026-08-10):
`PASSWORD_RESET_GRACE_MINUTES=2` se añadió allí y obedece a la misma regla que los otros tres
—valor por defecto, sin sensibilidad, fuera de los `${VAR:?}`—, con la diferencia de que
`Settings` valida además que sea estrictamente menor que `PASSWORD_RESET_TOKEN_MINUTES`. Esta
frase existe porque «los tres ajustes» sobrevivió en varios sitios después de la enmienda y el
panel de documentación de review lo levantó: la cuenta de D13 es histórica, la del sistema es
cuatro.

30 minutos es «del orden de los minutos, no de los días» de R3.4 con margen para que alguien lea el
correo en el móvil. `FRONTEND_BASE_URL` es lo que compone el enlace
(`{base}/reset-password?token=…`); no es un secreto, así que lleva valor por defecto, y la página
que ese enlace abre llega con `dashboard-web`/`hardening-release` — hasta entonces el enlace es
válido y la página no existe, que es la misma verdad que declara R6.4.

Los seis nombres del SMTP **no** entran en `Settings` ni en los `${VAR:?}` de los composes: la
regla 8 de `steering/security.md` exige que un secreto en uso falle rápido si falta, y ninguno de
estos está en uso todavía. Van sólo a `.env.example`, por nombre, con el comentario de que están
reservados.

Rejected: `PASSWORD_MIN_LENGTH` como ajuste — ver D4.

### D14 — `change-password` entra en el bloqueo por cuenta de `login`, no en un presupuesto propio

**Decisión añadida en `run` (2026-08-10)**, no en `/sdd:design`: la levantó el panel de seguridad
de la sección 4 y la aprobó Jose. Cubre el criterio R1.8, también añadido entonces.

**Chosen:** `ChangeOwnPasswordUseCase` recibe el `LoginThrottle` que ya existe y lo usa con las
claves que ya existen: comprueba `is_account_locked(user_id)` **antes** de verificar la
contraseña —y responde `InvalidCredentialsError`, cuya **respuesta** (código, cuerpo y cabeceras)
es idéntica a la de una contraseña equivocada; la **latencia** no lo es, porque el camino
bloqueado se salta el bcrypt, que es justo lo que cierra la mitad de agotamiento de CPU. Esa
diferencia de tiempo se acepta a sabiendas: igualarla exigiría pagar el bcrypt en una cuenta
bloqueada, es decir reabrir lo que esta decisión existe para cerrar, y el bit que filtra lo
obtiene el llamante igualmente al ver que tampoco funciona la contraseña correcta—,
llama a `record_failure(user_id)` cuando la verificación falla, y no toca el contador en el
camino feliz. `clear_account_lock` **no** se llama aquí: quien acaba de demostrar que conoce su
contraseña no estaba bloqueado, porque el bloqueo se comprueba antes.

Lo que decide la elección es que el contador por cuenta y el bloqueo de 15 minutos **ya
existen** (`login:fail:<uid>`, `login:lock:<uid>`) y ya están probados contra el Redis real. El
endpoint no necesita almacén nuevo, ni ajuste nuevo, ni método nuevo del puerto: necesita
**dejar de estar exento** del que hay. Y un solo contador compartido con `login` es lo correcto
por la misma razón por la que R2.4 comparte el contador por IP: dos presupuestos separados para
la misma cuenta permitirían gastar los dos.

Cierra con un solo mecanismo los dos agujeros **del caso del token robado**: el bloqueo detiene la
escalada de token a contraseña a los 10 intentos, y detiene también el bucle de agotamiento de CPU
de ese actor, porque a partir del bloqueo la petición se rechaza **sin llegar a bcrypt**. Lo que
no cierra —el mismo bucle en manos de quien sí conoce una contraseña— está justo abajo y **viaja
con esta frase**: al escribir `specs/` en el archivado, la afirmación de cierre y el residuo van
en el mismo párrafo, porque una frase de cierre sin matizar es exactamente la que se copia mientras
los párrafos de abajo se comprimen, y una spec que diga que el bucle está cerrado impedirá que el
siguiente panel lo compruebe (lo avisó el panel de seguridad de la sección 4).

**Residuo aceptado, y acotado con precisión** (lo midió el panel de seguridad al re-verificar la
propia D14, y está aquí porque «escenario (b) cerrado» sin matizar sería falso): el contador sólo
avanza cuando la verificación **falla**, así que quien conoce una contraseña válida —la suya—
puede repetir `{current correcto, new débil}` y pagar un `verify` de bcrypt (~250 ms) por
petición indefinidamente, sin incrementar el contador, sin bloquearse, sin rotar nada y sin dejar
fila de auditoría. El impacto sobre el `CapacityLimiter` compartido con `login` es el mismo que
el del escenario (b); lo que cambia es el requisito previo, de «robar un token de 15 minutos» a
«conocer una contraseña». La misma forma existe en el camino feliz (dos bcrypts por llamada) y en
el rechazo por contraseña sin cambiar (uno), que D11 obliga a dejar después del `verify`.

**Lo que lo cerraría es exactamente el presupuesto por usuario y por minuto que se descartó
abajo**, no un reordenamiento: adelantar `assert_password_acceptable` por delante del `verify`
abarataría sólo la variante de contraseña nueva débil —y obligaría a enmendar R1.2, porque una
petición equivocada en las dos cosas pasaría de `401` a `422`—, dejando el camino feliz y el de
contraseña sin cambiar igual de caros. Se deja registrado como límite conocido y no se mitiga
aquí: quien lo alcanza está autenticado y gasta CPU de su propio tenant y de los demás, pero no
obtiene credencial alguna. Si algún día el coste se vuelve real, la salida está nombrada.

Rejected: un presupuesto por minuto y por usuario, con clave y ajuste propios — acota además el
ritmo por debajo del umbral de fallos, y es lo único que cerraría el residuo de arriba, pero era
config nueva, clave nueva y método nuevo del puerto. Ofrecido a Jose como alternativa y
descartado por él.
Rejected: dejarlo documentado como limitación conocida y diferirlo a `hardening-release` — la
mitad de agotamiento de CPU la alcanza cualquier usuario autenticado sin robar nada, y degrada
el login de todos. También ofrecido y descartado.
Rejected: el presupuesto por IP de `login`/`refresh` — es la conclusión equivocada del
razonamiento correcto. La clave tiene que ser el `user_id`, que aquí se conoce y es más preciso
que la IP.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Dominio auth — entidades | `backend/app/auth/domain/entities.py` | `User.must_change_password: bool = False`; `set_password_hash(hash, *, temporary)`; `User.create(..., must_change_password=False)`. Nueva entidad `PasswordResetToken` (dataclass: `id`, `tenant_id`, `user_id`, `token_hash`, `expires_at`, `used_at`, `revoked_at`, `created_at`, `updated_at`) con `is_usable(now)` |
| Dominio auth — nuevo | `backend/app/auth/domain/recovery_tokens.py` | `generate_recovery_token() -> tuple[str, str]` (claro, sha256 hex) con `secrets`/`hashlib` — stdlib, sin romper la pureza de `domain/` |
| Dominio auth — nuevo | `backend/app/auth/domain/password_policy.py` | `PASSWORD_MIN_LENGTH = 12`, `assert_password_acceptable(password)` |
| Dominio auth — nuevo | `backend/app/auth/domain/recovery_messages.py` | `render_recovery_email(link) -> (subject, body)` (lo que se envía) y `STORED_RECOVERY_SUBJECT`/`STORED_RECOVERY_BODY` (lo que se persiste, sin enlace) |
| Dominio auth — puertos | `backend/app/auth/domain/ports.py` | `PasswordResetTokenRepository` (`add`, `consume_globally`, `count_live`, `revoke_other_live`); `LoginThrottle.clear_account_lock` |
| Dominio auth — errores | `backend/app/auth/domain/exceptions.py` | `PasswordPolicyError`, `PasswordUnchangedError`, `InvalidRecoveryTokenError`, `PasswordChangeRequiredError` |
| Aplicación auth | `backend/app/auth/application/recovery.py` (nuevo) | `ChangeOwnPasswordUseCase`, `RequestPasswordResetUseCase`, `ConsumePasswordResetUseCase` |
| Aplicación auth | `backend/app/auth/application/user_admin.py` | `CreateUserUseCase` y `ResetUserPasswordUseCase` pasan `temporary=True` (R5.2) |
| API auth | `backend/app/auth/api/router.py`, `schemas.py`, `dependencies.py`, `errors.py` | Tres endpoints nuevos; `ChangePasswordRequest`/`ForgotPasswordRequest`/`ResetPasswordRequest` (`extra="forbid"`); `CurrentUserResponse.must_change_password`; gate D6 y `PASSWORD_CHANGE_EXEMPT`; tres entradas nuevas en `_MAPPING` |
| Infraestructura auth | `backend/app/auth/infrastructure/models.py`, `repositories.py`, `throttle.py` | `UserModel.must_change_password`; `PasswordResetTokenModel`; `SqlAlchemyPasswordResetTokenRepository`; `RedisLoginThrottle.clear_account_lock` |
| Notificaciones | `backend/app/notifications/domain/enums.py` | Decimoséptimo `NotificationType.PASSWORD_RESET_REQUESTED`, declarado como divergencia de PRD §14 |
| Auditoría | `backend/app/audit/domain/actions.py`, `value_objects.py` | `USER_PASSWORD_CHANGED`, `USER_PASSWORD_RECOVERED` en `ACTIONS`; `must_change_password` en `AUDITABLE_FIELDS["USER"]` |
| Núcleo | `backend/app/core/error_codes.py`, `config.py` | `ErrorCode.PASSWORD_CHANGE_REQUIRED`; los cuatro ajustes de D13 (tres suyos más `PASSWORD_RESET_GRACE_MINUTES`, de la enmienda de D7) y el validador que ata la gracia a la vida del token |
| CLI | `backend/app/cli/reset_password.py` (nuevo) | Comando de recuperación asistida de D12 |
| Migración | `backend/alembic/versions/<rev>_password_recovery.py` (nuevo) | Tabla `password_reset_tokens` + columna `users.must_change_password` |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerados (`make openapi` y `npm run api:generate`) — las dos mitades del puente, `steering/documentation.md` |
| Configuración | `.env.example` | Los cuatro ajustes con comentario y los seis nombres SMTP reservados sin valor |
| Documentación | `docs/auth-account-recovery.md` (nuevo), `infra/environments/dev/RUNBOOK.md` | Operación de los tres endpoints, el `EXTERNAL_DEPENDENCY` de R6.4 y el procedimiento de D12 |
| Tests | `backend/tests/auth/`, `backend/tests/notifications/` | Ver «Riesgos» y R4.5 |

## Data & interfaces

**Tabla `password_reset_tokens`** (`TenantScopedMixin` + `UUIDPrimaryKeyMixin` + `TimestampMixin`,
como el resto):

| Columna | Tipo | Notas |
|---|---|---|
| `id` | UUID PK | |
| `tenant_id` | UUID | del usuario resuelto; la tabla entra en `tenant_scoped_classes()` y queda cubierta por el filtro global en sesiones marcadas |
| `user_id` | UUID FK `users.id` | |
| `token_hash` | `String(64)` | SHA-256 hex, **índice único** `uq_password_reset_tokens_token_hash` |
| `expires_at` | TIMESTAMPTZ | |
| `used_at` / `revoked_at` | TIMESTAMPTZ nulos | |

Índice adicional `ix_password_reset_tokens_tenant_id_user_id`, que sirve a `count_live` y a
`revoke_other_live`.

**Columna `users.must_change_password`**: `Boolean`, `NOT NULL`, `server_default false`. La
migración no necesita backfill: las cuentas existentes conservan el comportamiento de hoy, que es
lo correcto — nadie debe quedar bloqueado por un despliegue.

**API** (todos bajo `/api/v1/auth/`):

| Método | Ruta | Auth | Cuerpo | Respuesta |
|---|---|---|---|---|
| POST | `/change-password` | Bearer + `MANAGE_OWN_SESSION` | `{current_password, new_password}` | `204`; `401 INVALID_CREDENTIALS`; `422 VALIDATION_ERROR` |
| POST | `/forgot-password` | anónimo | `{email}` | `202` con cuerpo fijo; `429 RATE_LIMITED` |
| POST | `/reset-password` | anónimo | `{token, new_password}` | `204`; `401 INVALID_TOKEN`; `422 VALIDATION_ERROR`; `429 RATE_LIMITED` |

`GET /auth/me` gana `must_change_password: bool`. Los dos endpoints anónimos entran en la lista de
exentos de `tests/test_route_authorization.py`. `POST /forgot-password` y `POST /reset-password`
contabilizan en el contador `login:ip:<ip>` existente, comprobado **antes** de resolver el email o
el token (R2.4, R3.7). El código de error nuevo `PASSWORD_CHANGE_REQUIRED` (403) se publica en el
`enum` de la OpenAPI.

**Configuración**: `PASSWORD_RESET_TOKEN_MINUTES`, `PASSWORD_RESET_MAX_LIVE_TOKENS`,
`FRONTEND_BASE_URL` (con valor); `SMTP_*` reservados sin valor.

**Requisitos sin implicación de diseño**, dichos explícitamente para que conste que se leyeron:
R1.4 (el sujeto sale del token y el esquema es `extra="forbid"` — es la convención ya vigente en
todos los esquemas del módulo), R2.3 (`find_by_email_globally` se usa tal cual), R6.3
(`NotificationLogRepository.add` se usa sin ensanchar el puerto).

## Risks & mitigations

- **Oráculo de latencia en `/forgot-password`.** Con cuenta se hace una inserción y una llamada al
  adapter; sin cuenta, nada. Hoy el adapter es una línea de log, así que la diferencia es del orden
  de una escritura; con un SMTP real serían segundos y el endpoint distinguiría por tiempo lo que
  R2.2 iguala en código, cuerpo y cabeceras. **No se mitiga aquí** —quemar trabajo equivalente en el
  camino vacío no tiene análogo para un envío— y se declara como obligación explícita para
  `hardening-release`: el change que conecte SMTP tiene que sacar el envío del camino de la
  petición. Se anota en `specs/` al archivar y en `BLOCKED.md` no, porque no bloquea nada de este.
- **Envío y transacción no son atómicos.** Se envía antes del único `commit`: si el commit falla
  tras un envío correcto, el usuario recibe un enlace cuyo token no existe. Falla cerrado (el enlace
  no sirve) y el usuario reintenta. La ventana es de milisegundos y la alternativa —comitear y luego
  enviar— cambia el fallo por uno peor: un token vivo del que nadie recibió aviso.
- **Un fallo del adapter no se reintenta.** La fila queda `FAILED` y el dispatcher no la recoge
  (sólo mira `PENDING`), que es lo correcto: el cuerpo almacenado no lleva enlace, así que un
  reintento entregaría un correo inútil. El usuario vuelve a solicitar.
- **Migración sobre una tabla viva.** `users` es pequeña y la columna entra con `server_default`, así
  que es un `ALTER` de metadatos en Postgres 16 sin reescritura. La tabla nueva no tiene datos.
- **Dos `change-password` simultáneos: gana el último, y el otro recibe un `204` que miente.**
  `apply_changes` es un `UPDATE … WHERE tenant_id, id` sin predicado sobre el hash anterior, así
  que dos peticiones concurrentes verifican las dos contra el hash viejo, las dos pasan, y la
  segunda escritura sobrescribe la primera sin conflicto ni error. Lo afinó el panel de QA de la
  sección 4 y merece decirse con precisión: el resultado sigue siendo «una de las dos contraseñas
  que eligió el titular», pero **quien eligió la que se sobrescribió recibe un `204` por un cambio
  que no quedó**. No se queda fuera —sus sesiones se revocan igual, y puede volver a entrar con la
  otra— pero se le informa mal. No se mitiga: ningún requisito pide serialización, las dos
  llamadas exigen conocer la contraseña actual, y cerrarlo pediría un compare-and-set sobre el
  hash o un bloqueo de fila. Registrado para que sea una decisión y no un olvido.
- **Regresión en el contrato.** `ErrorCode` gana un miembro y `CurrentUserResponse` un campo, así que
  `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts` quedan obsoletos en el mismo
  commit; los workflows `api-contract` y `frontend-api-contract` fallan si no se regeneran los dos.
  Es tarea explícita, no un paso opcional.
- **El gate de D6 puede dejar una cuenta encerrada** si la lista de exentos pierde
  `/auth/change-password`. Lo cubre el test estructural de rutas exentas más un test de flujo
  completo: login con temporal → `403 PASSWORD_CHANGE_REQUIRED` en un endpoint cualquiera →
  `change-password` → `204` → el endpoint responde.
- **Tests obligatorios por R4.5 y por la regla 1**: un test que demuestre en rojo que el token no
  aparece en `password_reset_tokens` en claro, ni en `notification_logs.subject`/`body`, ni en
  `audit_logs.changes`, ni en el log de aplicación, ni en ninguna respuesta; y un test de
  aislamiento con dos tenants poblados que compruebe que consumir el token de A sólo toca al usuario
  de A.

## Open questions

Ninguna abierta. Las cuatro que el diseño levantó se resolvieron en el gate de `/sdd:design`
(Jose, 2026-08-09), todas confirmando la opción propuesta:

1. **Mínimo de longitud: 12.** Constante de dominio, no ajuste de entorno (D4), atada al generador
   por un test. Las alternativas eran 10 y 14.
2. **Vida del token: 30 minutos** (D13). Las alternativas eran 15 y 60.
3. **`must_change_password` se expone sólo en `GET /auth/me`**, como pide R5.6. Se descartó
   añadirlo a `GET /api/v1/users` y `GET /api/v1/users/{id}`: ensancharía el contrato —y con él el
   artefacto generado del frontend— más allá de los requisitos.
4. **El comando de D12 se queda como módulo**, `python -m app.cli.reset_password --email …`, con el
   patrón de `app.cli.bootstrap`. Se descartó el objetivo de Makefile: es una operación de rescate y
   un `make` la haría parecer parte del flujo normal de desarrollo.
