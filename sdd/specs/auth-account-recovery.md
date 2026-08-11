# Autoservicio de contraseña y recuperación

## Purpose

Cierra el autoservicio de credenciales de una capacidad que ya estaba viva: cualquier usuario
autenticado rota su propia contraseña, y quien la ha perdido recupera el acceso con solo su
email, sin depender de que otra persona del tenant pueda resetearle. Añade además la pieza que
convierte la contraseña temporal de [`user-management.md`](user-management.md) en algo que hay
que cambiar antes de operar.

Son tres endpoints nuevos bajo `/api/v1/auth/` —uno autenticado y dos anónimos—, una tabla
`password_reset_tokens`, la columna `users.must_change_password`, una política de contraseña que
antes no existía en ninguna parte, y el decimoséptimo `NotificationType`. Todo dentro de
`app/auth/`, sobre los mecanismos que [`auth-tenancy.md`](auth-tenancy.md) ya montó: el hasher
bcrypt en hilos, el throttle de Redis, la revocación de familias de refresh y la razón
`PASSWORD_RESET`. **Sin frontend** — la página que abre el enlace la sirve `dashboard-web`.

El *cómo se opera* —invocaciones, tabla de configuración, procedimiento de rescate— está en
[`docs/auth-account-recovery.md`](../../docs/auth-account-recovery.md); esta spec cubre qué
garantiza el sistema.

> **EXTERNAL_DEPENDENCY — el aviso todavía no alcanza a ninguna persona.** El canal `EMAIL`
> resuelve a `ConsoleEmailAdapter`, al que [`access-notifications.md`](access-notifications.md)
> prohíbe registrar contenido y destinatario: solo canal y longitudes. El enlace no puede leerse
> del log ni en desarrollo. El adapter SMTP real llega con `hardening-release`; hasta entonces el
> flujo anónimo está **probado pero no entrega**, y la vía que de verdad recupera una cuenta es
> el comando de rescate.

## Requirements

### Reparto de rutas y contrato

- THE SYSTEM SHALL servir exactamente estas tres rutas nuevas, todas en
  `app/auth/api/router.py` bajo el prefijo `/api/v1/auth`:

  | Ruta | Auth | Éxito |
  |---|---|---|
  | `POST /api/v1/auth/change-password` | `MANAGE_OWN_SESSION` | `204`, sin cuerpo |
  | `POST /api/v1/auth/forgot-password` | anónima | `202` con cuerpo fijo |
  | `POST /api/v1/auth/reset-password` | anónima, el token es la credencial | `204`, sin cuerpo |

- THE SYSTEM SHALL declarar los tres esquemas de petición con `extra="forbid"` y SHALL NOT
  admitir en ninguno un campo que nombre al sujeto (`tenant_id`, `user_id` o, en los
  autenticados, `email`): el sujeto de `change-password` se deriva del token de acceso y el de
  los anónimos, de la fila resuelta.
- THE SYSTEM SHALL responder `202` en `forgot-password` con `ForgotPasswordResponse`, cuyo campo
  `detail` es la constante `"If the address belongs to an account, a recovery link has been
  sent."` declarada como `Field(default=...)` para que siga apareciendo en el contrato OpenAPI y
  en el artefacto derivado del frontend.
- THE SYSTEM SHALL exponer `must_change_password` en `GET /api/v1/auth/me`
  (`CurrentUserResponse`) y SHALL NOT exponerlo en `GET /api/v1/users` ni en
  `GET /api/v1/users/{id}`: el flag existe para que el frontend redirija al propio usuario, no
  para que la administración liste el estado de credenciales ajenas.

### Política de contraseña

- THE SYSTEM SHALL exigir **12 caracteres** como mínimo (`PASSWORD_MIN_LENGTH`) y **72 bytes**
  en UTF-8 como máximo (`PASSWORD_MAX_BYTES`), en `app/auth/domain/password_policy.py`, y SHALL
  NOT imponer reglas de composición: exigir dígito, mayúscula y minúscula no mide la fuerza de
  una contraseña y prohíbe contraseñas mejores.
- THE SYSTEM SHALL mantener el mínimo como **constante de dominio y no como ajuste**: una
  política que cada despliegue puede bajar no es una política.
- IF la contraseña presentada tiene menos de 12 caracteres, no es codificable en UTF-8 (un
  sustituto suelto), o excede los 72 bytes, THEN THE SYSTEM SHALL responder `422` con
  `VALIDATION_ERROR` —`PasswordPolicyError` en los dos primeros casos, `PasswordTooLongError` en
  el tercero— y SHALL NOT devolver ni registrar la contraseña presentada.
- THE SYSTEM SHALL aceptar sin excepción toda contraseña que emite
  `generate_temporary_password()`, y un test SHALL fijar `TEMPORARY_PASSWORD_LENGTH >=
  PASSWORD_MIN_LENGTH` (hoy 16 ≥ 12): el generador de `user-management` existe precisamente para
  que esta política no acabe rechazando lo que aquel sistema emite.
- El tope de 72 bytes no es cosmético: `auth-tenancy` **rechaza** al crear el hash toda
  contraseña que lo supere en vez de truncarla, así que sin validación en el borde eso saldría
  como error no mapeado en lugar de como `422`.

### Cambio de contraseña por el propio usuario

- WHEN se envía a `POST /api/v1/auth/change-password` un token de acceso válido, la contraseña
  actual correcta y una nueva que cumple la política, THE SYSTEM SHALL reemplazar el hash
  almacenado y responder `204`.
- IF la contraseña actual no coincide, THEN THE SYSTEM SHALL responder `401` con
  `INVALID_CREDENTIALS` y SHALL NOT modificar el hash.
- IF la contraseña nueva es idéntica a la actual, THEN THE SYSTEM SHALL responder `422`
  (`PasswordUnchangedError`): un cambio que no cambia nada revoca todas las sesiones del usuario
  sin rotar credencial alguna.
- THE SYSTEM SHALL comprobar «nueva igual a actual» y la política **después** de verificar la
  contraseña actual, de modo que ninguna de las dos pueda usarse como oráculo por quien no la
  conoce.
- WHEN el cambio tiene éxito, THE SYSTEM SHALL revocar **todas** las familias de refresh del
  usuario con razón `PASSWORD_RESET`, **incluida la de la sesión que hizo la llamada**: un cambio
  que deja vivas las sesiones anteriores no rota la credencial, solo añade una.

#### El presupuesto por cuenta, y el residuo que no cierra

- WHILE la cuenta está bloqueada por acumulación de fallos, THE SYSTEM SHALL rechazar la petición
  **sin verificar** la contraseña presentada, comprobando `login:lock:<uid>` antes de bcrypt.
- IF la contraseña actual presentada no coincide, THEN THE SYSTEM SHALL contabilizar el fallo en
  el **mismo** contador por cuenta que `login` (`login:fail:<uid>`), de modo que el bloqueo de 10
  fallos de `auth-tenancy` cubra también esta vía.
- THE SYSTEM SHALL NOT aplicar aquí el presupuesto por IP de `login`/`refresh`: el llamante está
  autenticado y `user_id` es una clave más precisa que la dirección.

  Con esto, este endpoint deja de ser una vía de verificar contraseñas **más barata que `login`**
  —sin bloqueo, sin contador y sin rastro—, que es lo que permitía convertir un token de acceso
  robado de 15 minutos en la contraseña real a base de bcrypt, y lo que permitía retener todas
  las plazas del `CapacityLimiter` compartido con `login` sin credencial robada alguna. **Y no lo
  cierra del todo, medido y aceptado**: el contador solo avanza cuando la verificación *falla*,
  así que quien conoce una contraseña válida —la suya— puede seguir quemando un `verify` de bcrypt
  (~250 ms) por petición indefinidamente mandando una contraseña nueva que incumple la política,
  sin incrementar el contador, sin bloquearse, sin rotar nada y sin dejar fila de auditoría. No
  obtiene credencial, pero degrada el `CapacityLimiter` compartido con `login` igual que el
  escenario original. Lo único que lo cerraría es un presupuesto por usuario y por minuto,
  ofrecido y descartado; **no** un reordenamiento, que solo abarataría la variante de contraseña
  nueva débil y obligaría a cambiar el `401` por un `422`.
- THE SYSTEM SHALL NOT levantar el bloqueo por cuenta en esta vía: quien acaba de demostrar que
  sabe su contraseña no estaba bloqueado, porque el bloqueo se comprueba antes.

### Solicitud de recuperación, anónima e indistinguible

- WHEN se envía a `POST /api/v1/auth/forgot-password` un email cualquiera, THE SYSTEM SHALL
  responder `202` con el cuerpo fijo, que no describe el resultado.
- IF el email no corresponde a ninguna cuenta, o el usuario no está `ACTIVE`, o su tenant no está
  `ACTIVE`, THEN THE SYSTEM SHALL responder **exactamente la misma** respuesta —código, cuerpo y
  cabeceras— que en el caso con cuenta, y SHALL NOT emitir token ni escribir fila alguna en
  `notification_logs`. Es el mismo criterio con el que `auth-tenancy` hace indistinguibles los
  cinco motivos de fallo del login, y por el mismo motivo: la alternativa es un enumerador de
  usuarios anónimo y expuesto a internet.
- THE SYSTEM SHALL resolver la cuenta por `UserRepository.find_by_email_globally` y SHALL derivar
  el `tenant_id` de la fila encontrada — nunca del cuerpo de la petición, que no lo admite.
- THE SYSTEM SHALL registrar el intento en el log de la aplicación en inglés
  (`auth.password_reset_requested`) con el resultado —`resolved`, `emitted`, `delivered`,
  `revoked_older`— y SHALL NOT registrar el email ni el token en ninguna forma reversible.

#### Cota de enlaces vivos por cuenta, con margen de gracia

- THE SYSTEM SHALL acotar cuántos enlaces vivos acumula **una misma cuenta**
  (`PASSWORD_RESET_MAX_LIVE_TOKENS`, 3 por defecto), de modo que la dirección de una víctima no
  pueda inundarse desde IPs distintas, y SHALL aplicar la cota sin que el resultado sea
  observable en la respuesta.
- WHEN la cuenta ya está en la cota, THE SYSTEM SHALL **revocar el enlace vivo más antiguo y
  emitir el nuevo** (`revoke_oldest_beyond`), en lugar de descartar la solicitud: descartar
  convertía la cota en un arma: tres peticiones dentro del presupuesto por IP bastaban para que,
  durante los 30 minutos de vida del token, toda recuperación real del titular devolviera el
  mismo `202` sin enviar nada — y recargando a medida que expiraban, la supresión era indefinida.
  Revocando el más antiguo, **una solicitud legítima siempre gana**, y el número de enlaces
  válidos que coexisten sigue acotado.
- THE SYSTEM SHALL NOT revocar un enlace vivo **más joven que `PASSWORD_RESET_GRACE_MINUTES`**
  (2 por defecto), y IF todos los vivos están dentro de ese margen, THEN SHALL descartar la
  solicitud en silencio, registrando `reason: "all_live_links_within_grace"`. El margen cierra
  dos agujeros con un solo mecanismo: el correo por cuenta vuelve a estar acotado a `cota` por
  ventana de gracia —un presupuesto **por IP** no puede acotar un total **por cuenta**—, y el
  enlace del titular es irrevocable durante la ventana en la que lo va a pulsar, en vez de
  retirársele a los ~20 segundos por un atacante sostenido a ~3 peticiones por minuto.
- La cota es **check-then-act y no es a prueba de carreras**, medido: 8 peticiones concurrentes
  sobre una cuenta con cota 3 producen 8 tokens vivos; en secuencia se detiene correctamente en
  3. Aceptado, porque el volumen real lo acota el presupuesto por IP, porque enlaces adicionales
  no ayudan a adivinar ninguno (256 bits de `secrets` cada uno) y porque cerrarlo pediría un
  `SELECT … FOR UPDATE` o un advisory lock en superficie **anónima** — un candado que cualquiera
  en internet puede hacer tomar.

### Consumo del token de recuperación

- WHEN se presenta a `POST /api/v1/auth/reset-password` un token válido, no usado, no expirado y
  no revocado junto a una contraseña que cumple la política, THE SYSTEM SHALL reemplazar el hash
  del usuario y responder `204`.
- THE SYSTEM SHALL decidir quién consume un token con **una única sentencia condicional**,
  `PasswordResetTokenRepository.consume_globally`:
  `UPDATE password_reset_tokens SET used_at = :now WHERE token_hash = :h AND used_at IS NULL AND
  revoked_at IS NULL AND expires_at > :now RETURNING *`, comprobando `rowcount` — exactamente
  como `auth-tenancy` resuelve la rotación de refresh. Separar la comprobación de la escritura
  dejaría que dos presentaciones simultáneas resetearan las dos.
- IF el token no existe, ya se usó, expiró, fue revocado, o su usuario o su tenant dejaron de
  estar `ACTIVE`, THEN THE SYSTEM SHALL responder `401` `INVALID_TOKEN` con un error único e
  indistinguible entre esos casos y SHALL NOT modificar el hash. `InvalidRecoveryTokenError`
  **no acepta argumentos** y lleva su mensaje como constante de clase: la garantía de que no
  existe un canal por causa es estructural, no de disciplina.
- THE SYSTEM SHALL validar la política de contraseña **antes** de tocar la base de datos, y SHALL
  consumir el token **antes** de cargar y validar la cuenta: así el bcrypt de ~250 ms solo se
  paga después de que un token válido haya ganado su `UPDATE`. En consecuencia, un token
  presentado contra una cuenta que dejó de estar `ACTIVE` **se quema** — deliberado.
- THE SYSTEM SHALL fijar la vida del token en `PASSWORD_RESET_TOKEN_MINUTES` (30 por defecto) y
  SHALL generarlo con `secrets.token_urlsafe(32)` — 256 bits, nunca derivado de datos de la
  cuenta.
- WHEN un reset se completa, THE SYSTEM SHALL (a) revocar todas las familias de refresh del
  usuario con razón `PASSWORD_RESET`, (b) invalidar los demás tokens de recuperación vivos de esa
  cuenta (`revoke_other_live`), y (c) borrar `login:fail:<uid>` y `login:lock:<uid>`
  (`clear_account_lock`). Sin (c) la recuperación no recupera nada: 10 intentos fallidos son justo
  lo que precede a un «he perdido la contraseña», y el bloqueo de 15 minutos seguiría rechazando
  el login inmediatamente posterior con el mismo `401` genérico.
- THE SYSTEM SHALL ejecutar (c) **después** del commit y fuera de la transacción, y IF Redis no
  responde, THEN SHALL registrar `auth.password_reset_lock_not_cleared` y dar la operación por
  buena: el peor caso es un bloqueo que expira solo en 15 minutos sobre una cuenta ya recuperada.
- THE SYSTEM SHALL NOT emitir tokens de sesión en la respuesta del reset: el usuario se autentica
  después por `POST /api/v1/auth/login`. Un reset que además inicia sesión convierte la posesión
  del enlace en una sesión sin volver a presentar credencial.
- THE SYSTEM SHALL NOT comprobar aquí que la contraseña nueva difiere de la anterior: no se
  presenta ninguna actual, y verificarla costaría un bcrypt en superficie anónima para una
  comprobación que este camino no necesita.

### Presupuesto por IP compartido

- THE SYSTEM SHALL contabilizar cada llamada a `forgot-password` y a `reset-password` en el
  **mismo** contador por IP que `login` y `refresh` (`login:ip:<ip>`, `LOGIN_RATE_LIMIT_PER_MINUTE`
  = 10/min, ventana fija de 60 s) y SHALL NOT darles presupuesto propio, respondiendo `429` con
  `RATE_LIMITED`. Partir el presupuesto permitiría gastar cuatro desde una misma dirección, que
  es literalmente el razonamiento con el que `auth-tenancy` metió `refresh` en el contador de
  `login`.
- THE SYSTEM SHALL comprobar ese presupuesto **antes** de resolver el email y **antes** de
  siquiera calcular el hash del token presentado.

### El token no persiste en claro en ningún sumidero

- THE SYSTEM SHALL almacenar el token como `sha256(token)` en hexadecimal
  (`token_hash`, `String(64)`, índice único) y SHALL NOT persistirlo en claro en ninguna columna:
  la fila no permite reconstruirlo. El hash es **determinista y sin sal** a propósito — es lo
  único que hace posible la sentencia condicional única; bcrypt añadiría ~250 ms de CPU en un
  endpoint anónimo.
- THE SYSTEM SHALL NOT escribir el token, ni el enlace que lo contiene, en
  `notification_logs.subject` ni en `notification_logs.body`. La regla 11 de
  `steering/security.md` da a esas dos columnas **una excepción y solo una**, la forma
  enmascarada `****XX` de un código de acceso, y un token de recuperación no es eso.
- THE SYSTEM SHALL NOT escribir el token ni ninguna contraseña —nueva o presentada— en el log de
  la aplicación, en `audit_logs.changes`, en ningún `TimelineEvent` ni en ninguna respuesta de la
  API, en ninguna forma reversible ni enmascarada.
- THE SYSTEM SHALL registrar en `AuditLog` que hubo una recuperación a través de
  `ChangeSet`/`AuditLogFactory`, de modo que la entrada no pueda transportar el secreto por
  construcción.

### Rastro de auditoría

- THE SYSTEM SHALL distinguir por acción las tres vías que tocan una contraseña, y SHALL NOT
  reutilizar una sola: `USER_PASSWORD_CHANGED` (el propio usuario, autenticado),
  `USER_PASSWORD_RECOVERED` (el propio usuario, por token) y el preexistente `USER_PASSWORD_RESET`
  (un administrador, o el rescate por CLI). Distinguir «un administrador la reseteó» de «el
  usuario se recuperó solo» es exactamente lo que pregunta la revisión de un incidente.
- THE SYSTEM SHALL escribir el `ChangeSet` como `ChangeSet(ENTITY_USER).redacted("password")`,
  añadiendo el diff de `must_change_password` solo cuando el flag se mueve — campo real de
  `AUDITABLE_FIELDS["USER"]`, no redactado.
- THE SYSTEM SHALL registrar como actor al propio usuario en las dos vías de autoservicio
  (`actor_user_id = user.id`, `actor_ip` del cliente): en el consumo del token, quien lo presenta
  ha demostrado la posesión del enlace.
- THE SYSTEM SHALL NOT escribir `AuditLog` en `POST /api/v1/auth/forgot-password`: una solicitud
  no muta nada, y auditarla convertiría el rastro en el enumerador de usuarios que la respuesta
  indistinguible evita. Queda en el log de aplicación.

### `must_change_password`: la temporal deja de ser permanente

- THE SYSTEM SHALL llevar `users.must_change_password` (booleano, `NOT NULL`, `server_default`
  falso) y SHALL NOT rellenar la columna al migrar: las cuentas existentes quedan en falso, así
  que ningún despliegue deja a nadie fuera.
- THE SYSTEM SHALL mutarlo **únicamente** a través de `User.set_password_hash(password_hash, *,
  temporary: bool)`, que escribe el hash y el flag en la misma llamada. `temporary` es
  keyword-only y sin defecto: dos métodos que hay que llamar juntos son dos que alguien llamará
  por separado.
- THE SYSTEM SHALL acoplar los dos campos también en la segunda vía de escritura:
  `SqlAlchemyUserRepository.apply_changes` define `COUPLED_PASSWORD_COLUMNS` y SHALL rechazar con
  `ValueError` toda actualización que nombre uno de los dos sin el otro.
- WHEN `user-management` crea un usuario, completa un reset asistido, o el rescate por CLI fija
  una temporal, THE SYSTEM SHALL dejar `must_change_password` en verdadero.
- WHEN el propio usuario cambia su contraseña o completa una recuperación, THE SYSTEM SHALL
  dejarlo en falso.
- WHILE `must_change_password` es verdadero, THE SYSTEM SHALL responder `403` con
  `PASSWORD_CHANGE_REQUIRED` a toda petición autenticada salvo exactamente estos tres pares
  `(método, ruta)`: `GET /api/v1/auth/me`, `POST /api/v1/auth/logout` y
  `POST /api/v1/auth/change-password`.
- THE SYSTEM SHALL aplicar ese gate en `get_authenticated_request` —no en `require(permission)` y
  no en un middleware ASGI—, comparando `(request.method, get_route_path(request.scope))`:
  ponerlo en `require` dejaría fuera cualquier endpoint futuro escrito con el `AuthenticatedDep`
  público, y un middleware correría antes de que se resuelvan las dependencias, duplicando la
  revalidación de `auth-tenancy`. Un test estructural SHALL comprobar que cada par exento
  corresponde a una ruta registrada.
- THE SYSTEM SHALL seguir emitiendo el par de tokens en un login con la temporal: sin sesión no
  hay forma de llamar al endpoint de cambio, y bloquear el login dejaría la cuenta muerta en vez
  de acotada. `POST /api/v1/auth/refresh` no pasa por esta dependencia y por tanto tampoco queda
  bloqueado.

### El aviso: qué se envía y qué se guarda

- THE SYSTEM SHALL añadir `NotificationType.PASSWORD_RESET_REQUESTED`, decimoséptimo valor y
  divergencia declarada frente a los dieciséis de PRD §14.
- THE SYSTEM SHALL componer el correo y llamar al `NotificationAdapter` de canal `EMAIL`
  **de forma síncrona, dentro de la misma petición**, y SHALL escribir después la fila de
  `notification_logs` con el resultado de esa llamada. El emisor asíncrono entrega *leyendo*
  `subject`/`body`, así que la única forma de que el enlace llegue sin quedar escrito ahí es que
  el envío ocurra mientras el token todavía existe en memoria.
- THE SYSTEM SHALL producir el texto enviado y el texto guardado con **dos funciones distintas**
  de `app/auth/domain/recovery_messages.py`: `render_recovery_email(link)` para lo que se envía, y
  las constantes `STORED_RECOVERY_SUBJECT` / `STORED_RECOVERY_BODY` —que no aceptan argumento
  alguno— para lo que se persiste. La garantía es estructural: la función que guarda no tiene por
  dónde recibir el enlace.
- THE SYSTEM SHALL escribir la fila directamente en `SENT` o `FAILED`, con `attempts = 1`, y
  SHALL NOT escribirla nunca en `PENDING`: el despachador solo mira `PENDING`, y reenviaría el
  cuerpo *guardado*, que no lleva enlace — un correo inútil.
- THE SYSTEM SHALL emitir la fila sin `sla_deadline_at`, de modo que `escalation_for` devuelva
  `None` y el job de SLA no la escale: no hay plazo que incumplir en una recuperación.
- THE SYSTEM SHALL escribir la fila con el `tenant_id` de la cuenta resuelta y su
  `recipient_user_id`, apoyándose en el `NotificationLogRepository.add` existente sin ensanchar el
  puerto.
- IF el adapter falla o no existe para el canal, THEN THE SYSTEM SHALL dejar la fila en `FAILED`
  con su `NotificationErrorCode` y SHALL NOT reintentar: el usuario vuelve a solicitar. Un
  reintento entregaría el cuerpo sin enlace.
- **Consecuencia aceptada, y única de este tipo de notificación**: la fila registra *que se envió
  un aviso*, no su contenido.

### Rescate operativo mientras no hay SMTP

- THE SYSTEM SHALL ofrecer `python -m app.cli.reset_password --email <dirección>` como vía de
  recuperación de un `TENANT_OWNER` bloqueado, y SHALL NOT exponerla como objetivo de `Makefile`:
  es una operación de rescate, y un verbo de `make` la haría parecer parte del flujo normal.
- THE SYSTEM SHALL, en ese comando, fijar una temporal con `set_password_hash(..., temporary=True)`,
  revocar las familias de refresh con razón `PASSWORD_RESET`, levantar el bloqueo por cuenta,
  escribir un `AuditLog` con acción `USER_PASSWORD_RESET` y `actor_user_id = NULL` —el comando no
  tiene identidad que registrar—, e imprimir la contraseña **una sola vez** por salida estándar,
  sin registrarla en ningún log.
- IF Redis no responde al levantar el bloqueo, THEN THE SYSTEM SHALL avisar por `stderr` de que
  la contraseña **sí se cambió** y de que el bloqueo expirará solo, devolviendo código 0: lo
  contrario sería informar de un fallo después de haber cambiado la credencial.
- IF la dirección no corresponde a ninguna cuenta, THEN THE SYSTEM SHALL escribir el error en
  `stderr` y devolver código 1.
- THE SYSTEM SHALL NOT ofrecer ningún `--print-link` ni variable de entorno que registre el
  enlace en desarrollo: un interruptor que imprime credenciales es un interruptor que acabará
  puesto en un entorno que no es dev.

### Aislamiento por tenant

- THE SYSTEM SHALL derivar el `tenant_id` de la fila resuelta en las dos vías anónimas y SHALL
  NOT aceptarlo del cliente en ninguna forma, tampoco embebido en el propio token: el scope lo
  aportaría el atacante.
- THE SYSTEM SHALL mantener `consume_globally` como la **única** consulta sin scope de tenant de
  este módulo, y SHALL declararla en la enumeración que el sistema guarda en un solo sitio —el
  docstring de `UserRepository.find_by_email_globally` (ADR 0005)— en lugar de reenunciar aquí
  cuántas hay. No es «la última»: [`guest-portal-api.md`](guest-portal-api.md) añadió después la
  del portal del huésped, por el mismo motivo estructural. Las demás operaciones sobre
  `password_reset_tokens` —`add`, `count_live`, `revoke_other_live`, `revoke_oldest_beyond`—
  **sí** llevan `tenant_id`, y `add` rechaza con `CrossTenantWriteError` una fila cuyo tenant no
  coincide.

### Configuración

- THE SYSTEM SHALL exponer cuatro ajustes: `PASSWORD_RESET_TOKEN_MINUTES` (30, `0 < n ≤ 720`),
  `PASSWORD_RESET_MAX_LIVE_TOKENS` (3, `1 ≤ n ≤ 10`), `PASSWORD_RESET_GRACE_MINUTES`
  (2, `1 ≤ n ≤ 60`) y `FRONTEND_BASE_URL` (`http://localhost:3000`), que compone el enlace como
  `{FRONTEND_BASE_URL}/reset-password?token=<token>`.
- IF `PASSWORD_RESET_GRACE_MINUTES >= PASSWORD_RESET_TOKEN_MINUTES`, THEN THE SYSTEM SHALL
  negarse a arrancar: un margen de gracia igual o mayor que la vida del token haría irrevocable
  todo enlace vivo. La vida coherente mínima del token es, por tanto, de 2 minutos.
- THE SYSTEM SHALL reservar por nombre y sin valor en `.env.example` lo que un SMTP real
  necesitará —`SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`,
  `SMTP_USE_TLS`— y SHALL NOT declararlos en `Settings` ni exigirlos en los composes: la regla 8
  de `steering/security.md` manda que un secreto **en uso** falle rápido, y ninguno lo está
  todavía.

## Deuda declarada

- **El aviso no llega a nadie** (`EXTERNAL_DEPENDENCY`, marcado en
  `app/notifications/domain/enums.py`, `app/auth/api/dependencies.py`, `app/cli/reset_password.py`
  y `.env.example`). Hasta que `hardening-release` traiga un adapter SMTP real, el flujo anónimo
  se ejercita en la suite —donde el `NotificationAdapter` es un doble que captura lo enviado— y
  **no a mano en dev**. La promesa «el propietario bloqueado se recupera solo» no está cerrada;
  la vía real sigue siendo el comando de rescate.
- **Obligación explícita para `hardening-release`: el oráculo de latencia.** Con cuenta, la
  solicitud hace un insert y una llamada al adapter; sin cuenta, nada. Hoy la diferencia es una
  escritura; con SMTP real serían segundos, y el endpoint distinguiría **por tiempo** lo que la
  respuesta iguala en código, cuerpo y cabeceras. El change que conecte SMTP tiene que sacar el
  envío del camino de la petición. No se mitiga aquí: quemar trabajo equivalente en el camino
  vacío no tiene análogo para un envío.
- **El enlace lleva el token en la query string** (`…/reset-password?token=…`). Ninguno de los
  cinco sumideros enumerados arriba lo recoge, pero cuando `dashboard-web` sirva esa página el
  token pasará por el log de acceso del frontend, el historial del navegador y la cabecera
  `Referer` de lo que cargue la página. Quien la construya: fragmento (`#token=`) o
  consumir-y-limpiar la URL al llegar.
- **Dos `change-password` simultáneos: gana el último.** `apply_changes` es un `UPDATE … WHERE
  tenant_id, id` sin predicado sobre el hash anterior, así que ambos verifican contra el hash
  viejo, ambos pasan, y el segundo sobrescribe al primero sin conflicto: quien eligió la
  contraseña sobrescrita recibe un `204` por un cambio que no quedó. Registrado para que sea una
  decisión y no un descuido.
- **El test de sumideros vigila una costura, no todas.** La prueba que sostiene la ausencia del
  token en `notification_logs` y en el log captura el secreto parcheando `generate_recovery_token`
  **en `app/auth/application/recovery.py`**, hoy el único llamante. Un camino futuro —reenvío de
  enlace, magic link— que importe la función en otro sitio o llame a `secrets` por su cuenta
  emitiría un token que ese fixture no ve. **Quien añada un emisor nuevo tiene que ampliar la
  captura.**
- **El envío no es atómico con la transacción**: ocurre antes del único `commit`. Si el commit
  falla tras un envío correcto, el usuario recibe un enlace cuyo token no existe. Falla en
  cerrado —el enlace no sirve— y la ventana es de milisegundos; la alternativa (commit y luego
  envío) cambia eso por un fallo peor: un token vivo del que nadie fue avisado.
- **`403 PASSWORD_CHANGE_REQUIRED` no aparece por endpoint en el contrato OpenAPI**:
  `AUTHENTICATED_RESPONSES` no se amplió y su descripción del 403 sigue hablando solo de permisos.
  El código sí está en el enum de errores.
- **Fuera de alcance, con dueño**: la página `/forgot-password` y la pantalla de cambio
  (`dashboard-web` / `hardening-release` — el enlace compuesto ya es válido, la página que abre
  todavía no existe); el adapter SMTP real (`hardening-release`); segundo factor, magic links y
  expiración periódica de contraseñas (nada en el PRD los pide); el cambio del propio email, que
  es identidad de login y sigue administrado en `PATCH /api/v1/users/{id}`; y la recuperación de
  huéspedes, que es token opaco por estancia y pertenece a `guest-portal-api`.

## Key files

- `backend/app/auth/api/router.py` — las tres rutas.
- `backend/app/auth/api/schemas.py` — `ChangePasswordRequest`, `ForgotPasswordRequest`,
  `ForgotPasswordResponse`, `ResetPasswordRequest`, `CurrentUserResponse`.
- `backend/app/auth/api/dependencies.py` — gate `must_change_password` en
  `get_authenticated_request`, `PASSWORD_CHANGE_EXEMPT`, cableado de los casos de uso.
- `backend/app/auth/api/errors.py` — mapeo a `422`/`401`/`403`/`429`.
- `backend/app/auth/application/recovery.py` — `ChangeOwnPasswordUseCase`,
  `RequestPasswordResetUseCase`, `ConsumePasswordResetUseCase`.
- `backend/app/auth/domain/password_policy.py` — `assert_password_acceptable`,
  `assert_password_changed`, `PASSWORD_MIN_LENGTH`, `PASSWORD_MAX_BYTES`.
- `backend/app/auth/domain/recovery_tokens.py` — generación y hash del token.
- `backend/app/auth/domain/recovery_messages.py` — texto enviado vs. texto guardado.
- `backend/app/auth/domain/entities.py` — `User.set_password_hash(..., temporary=...)`.
- `backend/app/auth/domain/ports.py` — `PasswordResetTokenRepository`, `LoginThrottle`.
- `backend/app/auth/infrastructure/models.py`, `repositories.py` — `password_reset_tokens`,
  `consume_globally`, `count_live`, `revoke_other_live`, `revoke_oldest_beyond`,
  `COUPLED_PASSWORD_COLUMNS`.
- `backend/app/auth/infrastructure/throttle.py` — `clear_account_lock`.
- `backend/app/cli/reset_password.py` — el rescate.
- `backend/alembic/versions/a7c4e91b2d05_password_recovery.py` — tabla y columna.
- `backend/app/core/config.py` — los cuatro ajustes y su validación cruzada.
- `docs/auth-account-recovery.md` — operación; `infra/environments/dev/RUNBOOK.md` — rescate en dev.
