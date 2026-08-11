# Tasks: auth-account-recovery

Orden pensado para que la suite quede en verde al final de cada sección: primero el dominio
puro (TDD, sin infra que montar — `steering/testing.md`), luego persistencia y migración, luego
las piezas transversales que los tres casos de uso comparten, y sólo después los endpoints, uno
por requisito. El contrato generado y la documentación van al final porque dependen de que las
tres rutas y el código de error nuevo existan ya.

## 1. Dominio puro: política, token y mensajes <!-- panel: PASS 2026-08-09 -->

- [x] 1.1 `backend/app/auth/domain/password_policy.py` (nuevo): `PASSWORD_MIN_LENGTH = 12` y
  `assert_password_acceptable(password)` que lanza `PasswordPolicyError` si
  `len(password) < 12` y `PasswordTooLongError` si `len(password.encode("utf-8")) > 72`
  (D4 reutiliza la excepción existente, que ya mapea a `422 VALIDATION_ERROR`). Test primero en
  `backend/tests/auth/test_password_policy.py`: caso válido, corto, 72 bytes exactos (acepta),
  73 bytes con multibyte (rechaza), y el mensaje nombra la regla incumplida sin incluir la
  contraseña. [R1.5, R1.6]
- [x] 1.2 Test de acoplamiento con el generador en `backend/tests/auth/test_password_policy.py`:
  `TEMPORARY_PASSWORD_LENGTH >= PASSWORD_MIN_LENGTH`, y `assert_password_acceptable` acepta un
  lote de contraseñas producidas por `generate_temporary_password()`. Es el test que D4 exige
  para que mover cualquiera de las dos constantes rompa la suite. [R1.6]
- [x] 1.3 `backend/app/auth/domain/recovery_tokens.py` (nuevo):
  `generate_recovery_token() -> tuple[str, str]` con `secrets.token_urlsafe(32)` y
  `hashlib.sha256(...).hexdigest()` — sólo stdlib, sin romper la pureza de `domain/`. Test en
  `backend/tests/auth/test_recovery_tokens.py`: el hash tiene 64 caracteres hex, dos llamadas dan
  tokens distintos, y el hash es determinista para un mismo claro (es lo que permite el `UPDATE`
  condicional de D1). [R3.4, R4.1]
- [x] 1.4 `backend/app/auth/domain/recovery_messages.py` (nuevo):
  `render_recovery_email(link) -> (subject, body)` para **lo que se envía**, y las constantes
  `STORED_RECOVERY_SUBJECT` / `STORED_RECOVERY_BODY` para **lo que se persiste**, sin enlace
  (D2). Test que afirma que ninguna de las dos constantes contiene el enlace ni ninguna subcadena
  del token, y que son dos funciones distintas del mismo módulo. [R4.2]
- [x] 1.5 `backend/app/auth/domain/exceptions.py`: añadir `PasswordPolicyError`,
  `PasswordUnchangedError`, `InvalidRecoveryTokenError` y `PasswordChangeRequiredError`, todas
  bajo `AuthDomainError`. Extender `backend/tests/auth/test_exceptions.py` con las cuatro. [R1.5,
  R1.7, R3.3, R5.4]

## 2. Entidad, modelos, repositorio y migración <!-- panel: PASS 2026-08-09 -->

- [x] 2.1 `backend/app/auth/domain/entities.py`: campo `User.must_change_password: bool = False`;
  `set_password_hash(password_hash, *, temporary: bool)` fija los dos campos a la vez (D5);
  `User.create(..., must_change_password: bool = False)`. Añadir la entrada
  `must_change_password → set_password_hash` a `FIELD_OWNERS` en
  `backend/tests/auth/test_entities.py` — el test que deriva los campos mutables de
  `User.__dataclass_fields__` (`test_entities.py:304`) fallará hasta que exista. [R5.1]
- [x] 2.2 `backend/app/auth/domain/entities.py`: entidad `PasswordResetToken` (dataclass con
  `id`, `tenant_id`, `user_id`, `token_hash`, `expires_at`, `used_at`, `revoked_at`,
  `created_at`, `updated_at`) con `is_usable(now)`. Tests en `test_entities.py` para usable,
  usado, revocado y expirado. [R3.1, R3.3]
- [x] 2.3 `backend/app/auth/domain/ports.py`: protocolo `PasswordResetTokenRepository` con `add`,
  `consume_globally(token_hash, now)` (**sin `tenant_id`** — D3, segunda consulta sin scope del
  sistema, nombrada como tal en el docstring), `count_live(tenant_id, user_id, now)` y
  `revoke_other_live(tenant_id, user_id, keep_id, now)`; y `LoginThrottle.clear_account_lock(user_id)`.
  [R2.5, R3.2, R3.5, R4.1]
- [x] 2.4 `backend/app/auth/infrastructure/models.py`: `UserModel.must_change_password`
  (`Boolean`, `NOT NULL`, `server_default false`) y `PasswordResetTokenModel` con
  `TenantScopedMixin` + `UUIDPrimaryKeyMixin` + `TimestampMixin`, índice único
  `uq_password_reset_tokens_token_hash` sobre `token_hash` (`String(64)`) e índice
  `ix_password_reset_tokens_tenant_id_user_id`. Extender `backend/tests/auth/test_models.py` y
  comprobar que la tabla entra en `tenant_scoped_classes()`
  (`backend/tests/test_models_registry.py`). [R4.1, R5.1]
- [x] 2.5 `backend/alembic/versions/<rev>_password_recovery.py` (nuevo): crea
  `password_reset_tokens` con sus dos índices y añade `users.must_change_password` con
  `server_default false`, sin backfill (las cuentas existentes conservan el comportamiento
  actual). `downgrade` completo. Verificar con `docker compose exec backend uv run alembic
  upgrade head`, `alembic check` y `alembic downgrade base`. [R5.1]
- [x] 2.6 `backend/app/auth/infrastructure/repositories.py`:
  `SqlAlchemyPasswordResetTokenRepository`. `consume_globally` es **una única sentencia**
  `UPDATE … SET used_at = :now WHERE token_hash = :h AND used_at IS NULL AND revoked_at IS NULL
  AND expires_at > :now RETURNING user_id, tenant_id` comprobando `rowcount` (D1/R3.2).
  `count_live` y `revoke_other_live` sí van scopados por tenant. Tests en
  `backend/tests/auth/test_repositories.py`, incluido uno de **doble consumo concurrente** que
  demuestre que sólo una de las dos presentaciones gana la fila. [R3.2, R3.5, R2.5]
- [x] 2.7 `backend/app/auth/infrastructure/throttle.py`: `RedisLoginThrottle.clear_account_lock`
  borra `login:fail:<uid>` y `login:lock:<uid>`. Test en `backend/tests/auth/test_throttle.py`
  que verifica que las dos claves desaparecen — `reset_failures` sólo borraba el contador, y ese
  es justo el fallo que D8 descarta. [R3.5]
- [x] 2.8 Añadir el doble en memoria del nuevo repositorio y `clear_account_lock` al throttle
  falso de `backend/tests/auth/doubles.py`, para que los casos de uso de las secciones 4-7 se
  puedan testear sin base de datos. [R1, R2, R3]

## 3. Piezas transversales: config, códigos de error y auditoría <!-- panel: PASS 2026-08-09 -->

- [x] 3.1 `backend/app/core/config.py`: `PASSWORD_RESET_TOKEN_MINUTES=30`,
  `PASSWORD_RESET_MAX_LIVE_TOKENS=3` y `FRONTEND_BASE_URL=http://localhost:3000` (D13). Los seis
  nombres `SMTP_*` **no** entran aquí. Extender `backend/tests/test_config.py`. [R2.5, R3.4]
  **Acabaron siendo cuatro**: `PASSWORD_RESET_GRACE_MINUTES=2` entró después, con la enmienda del
  margen de gracia de D7, y con él el validador que exige que sea estrictamente menor que
  `PASSWORD_RESET_TOKEN_MINUTES` — porque una gracia igual o mayor que la vida del token no
  revocaría nunca nada y devolvería la cota a ser un descarte permanente.
- [x] 3.2 `backend/app/core/error_codes.py`: `ErrorCode.PASSWORD_CHANGE_REQUIRED`. [R5.4]
- [x] 3.3 `backend/app/auth/api/errors.py`: **cuatro** entradas nuevas en `_MAPPING` —el plan
  decía «tres» agrupando las dos de `422` en una línea, pero `_MAPPING` despacha por clase exacta
  con `isinstance`, así que una tupla no puede servir a dos excepciones distintas (lo notó el
  panel de QA de la sección 3)—
  `PasswordPolicyError`/`PasswordUnchangedError` → `422 VALIDATION_ERROR`,
  `InvalidRecoveryTokenError` → `401 INVALID_TOKEN`, `PasswordChangeRequiredError` →
  `403 PASSWORD_CHANGE_REQUIRED`. Tests de envoltorio de error para las tres. [R1.5, R3.3, R5.4]
- [x] 3.4 `backend/app/audit/domain/actions.py`: `USER_PASSWORD_CHANGED` y
  `USER_PASSWORD_RECOVERED` en `ACTIONS`; `must_change_password` en `AUDITABLE_FIELDS["USER"]`
  (`value_objects.py`). Dos acciones distintas y no reutilizar `USER_PASSWORD_RESET`, porque
  distinguir «un administrador la reseteó» de «el propio usuario se recuperó» es lo que un
  repaso de incidente pregunta (D9). Tests en `backend/tests/audit/`. [R4.4]

## 4. R1 — Cambio de contraseña por el propio usuario <!-- panel: PASS 2026-08-10 -->

- [x] 4.1 `backend/app/auth/application/recovery.py` (nuevo): `ChangeOwnPasswordUseCase` —
  verifica la actual (si falla, `InvalidCredentialsError`, sin tocar el hash), rechaza la nueva
  idéntica a la actual comparando en claro tras la verificación (D11,
  `PasswordUnchangedError`), aplica `assert_password_acceptable`, escribe con
  `set_password_hash(..., temporary=False)`, revoca **todas** las familias de refresh del usuario
  con razón `PASSWORD_RESET` incluida la de la sesión que llama, y escribe el `AuditLog`
  `USER_PASSWORD_CHANGED` con `ChangeSet(ENTITY_USER).redacted("password")` más el diff de
  `must_change_password` si cambió. Tests de caso de uso en
  `backend/tests/auth/test_recovery_use_cases.py` (nuevo). [R1.1, R1.2, R1.3, R1.5, R1.7, R4.4,
  R5.3]
- [x] 4.2 `backend/app/auth/api/schemas.py`: `ChangePasswordRequest`
  (`{current_password, new_password}`, `extra="forbid"` — el sujeto se deriva del token y el
  cuerpo no puede nombrar a otro usuario). `backend/app/auth/api/router.py`:
  `POST /api/v1/auth/change-password`, `204`, tras `require(Permission.MANAGE_OWN_SESSION)`.
  Tests de endpoint en `backend/tests/auth/test_recovery_api.py` (nuevo): `204` en el camino
  feliz, `401 INVALID_CREDENTIALS` con la actual equivocada y sin mutar el hash, `422` por
  política, `422` por contraseña sin cambiar, `422` por campo extra, y que las sesiones previas
  quedan revocadas. [R1.1, R1.2, R1.3, R1.4, R1.5, R1.7]

- [x] 4.3 `ChangeOwnPasswordUseCase` recibe el `LoginThrottle` existente (D14, R1.8): comprueba
  `is_account_locked(user_id)` **antes** de verificar y responde `InvalidCredentialsError`
  —indistinguible de una contraseña equivocada—, y llama a `record_failure(user_id)` cuando la
  verificación falla. Sin contador propio, sin ajuste nuevo, sin método nuevo del puerto: el
  endpoint sólo deja de estar exento del bloqueo que `auth-tenancy` ya tiene. Tests: la cuenta
  se bloquea a los 10 fallos por esta vía; una vez bloqueada la petición se rechaza **sin pagar
  bcrypt** (contando las llamadas al hasher con `CountingPasswordHasher`); el camino feliz no
  toca el contador; y el `401` del bloqueo es idéntico al de la contraseña equivocada.
  **Tarea añadida en `run`**: la levantó el panel de seguridad de la sección 4 y la aprobó Jose.
  [R1.8]

## 5. R5 — La contraseña temporal deja de ser permanente <!-- panel: PASS 2026-08-10 -->

- [x] 5.1 `backend/app/auth/application/user_admin.py`: `CreateUserUseCase` y
  `ResetUserPasswordUseCase` pasan `temporary=True`. Extender
  `backend/tests/auth/test_user_admin_use_cases.py` para exigir que ambos caminos dejen el flag
  en verdadero. [R5.2]
- [x] 5.2 `backend/app/auth/api/dependencies.py`: conjunto `PASSWORD_CHANGE_EXEMPT` de pares
  `(método, path)` — `GET /api/v1/auth/me`, `POST /api/v1/auth/logout`,
  `POST /api/v1/auth/change-password` — y gate en `get_authenticated_request` que lanza
  `PasswordChangeRequiredError` cuando el flag está puesto y la ruta no está exenta (D6).
  `POST /api/v1/auth/refresh` no atraviesa esta dependencia y por tanto sigue funcionando (R5.5).
  [R5.4, R5.5]
- [x] 5.3 Test estructural en `backend/tests/test_route_authorization.py`: cada par de
  `PASSWORD_CHANGE_EXEMPT` corresponde a una ruta registrada de verdad, para que un renombrado no
  deje una exención apuntando al vacío ni un endpoint exento por accidente. [R5.4]
- [x] 5.4 Test de flujo completo en `backend/tests/auth/test_recovery_api.py`: login con la
  temporal devuelve el par de tokens → un endpoint cualquiera responde
  `403 PASSWORD_CHANGE_REQUIRED` → `change-password` responde `204` → el mismo endpoint responde.
  Es la red contra el riesgo de dejar una cuenta encerrada. [R5.3, R5.4, R5.5]
- [x] 5.5 `backend/app/auth/api/schemas.py`: `CurrentUserResponse.must_change_password: bool`, y
  test de que `GET /api/v1/auth/me` lo expone en ambos valores. Sólo aquí — no se añade a
  `GET /api/v1/users` ni a `GET /api/v1/users/{id}` (open question 3). [R5.6]

## 6. R2 — Solicitud de recuperación, anónima e indistinguible <!-- panel: PASS 2026-08-10 -->

- [x] 6.1 `backend/app/notifications/domain/enums.py`: decimoséptimo
  `NotificationType.PASSWORD_RESET_REQUESTED`, con comentario declarándolo divergencia de los
  dieciséis de PRD §14. Extender el test del enum en `backend/tests/notifications/`. [R6.1]
- [x] 6.2 `backend/app/auth/application/recovery.py`: `RequestPasswordResetUseCase` — resuelve por
  `find_by_email_globally` y deriva el `tenant_id` de la fila; si no hay cuenta, o el usuario o su
  tenant no están `ACTIVE`, o `count_live` alcanza `PASSWORD_RESET_MAX_LIVE_TOKENS` (D7), termina
  **por el mismo camino de respuesta** sin emitir token ni escribir en `notification_logs`. En el
  camino con cuenta: emite el token, inserta la fila, compone el enlace con `FRONTEND_BASE_URL`,
  llama **síncronamente** al `NotificationAdapter` del canal `EMAIL`, y escribe la fila de
  `notification_logs` ya en `SENT`/`FAILED` —nunca `PENDING`, que es la cola del dispatcher— con
  `subject`/`body` **constantes y sin enlace**, `sla_deadline_at` nulo, el `tenant_id` de la
  cuenta y su `recipient_user_id`, usando `NotificationLogRepository.add` sin ensanchar el puerto
  (D2). Tests de caso de uso con un doble de adapter que captura lo enviado. [R2.1, R2.2, R2.3,
  R2.5, R4.2, R6.2, R6.3]
- [x] 6.3 Log de aplicación en inglés con el resultado del intento, **sin** el email ni el token
  ni forma reversible de ninguno de los dos, y test con `caplog` que lo demuestre en los dos
  caminos. [R2.6, R4.3]
- [x] 6.4 `backend/app/auth/api/schemas.py` + `router.py`: `ForgotPasswordRequest` (`{email}`,
  `extra="forbid"`, sin `tenant_id`) y `POST /api/v1/auth/forgot-password`, anónimo, `202` con
  cuerpo fijo. El contador por IP `login:ip:<ip>` (el **mismo** de `login`/`refresh`, sin
  presupuesto propio) se comprueba **antes** de resolver el email y devuelve `429 RATE_LIMITED`.
  Añadir el par a `ANONYMOUS_ENDPOINTS` de `backend/tests/test_route_authorization.py`. [R2.1,
  R2.4]
- [x] 6.5 Test de indistinguibilidad en `test_recovery_api.py`: email inexistente, usuario
  inactivo, tenant inactivo y cuota de tokens vivos agotada producen **el mismo** código, cuerpo y
  cabeceras que el caso con cuenta, y ninguno escribe fila en `notification_logs`. [R2.2, R2.5]
- [x] 6.6 Test de presupuesto compartido en `test_recovery_api.py`: gastar el contador con
  `login` deja `forgot-password` en `429` desde la misma IP, y viceversa. [R2.4]

- [x] 6.7 `PasswordResetTokenRepository.revoke_oldest_beyond(tenant_id, user_id, keep_newest, now)`
  (puerto, adapter y doble) y `RequestPasswordResetUseCase`: al alcanzar la cota, **revocar el
  enlace vivo más antiguo y emitir el nuevo** en vez de descartar la solicitud (D7 enmendada,
  R2.5). Una sola sentencia: revoca los vivos salvo los `keep_newest` más recientes por
  `created_at`, así que también corrige una cota que se haya bajado por configuración. Tests: la
  4ª solicitud emite y deja 3 vivos; el más antiguo queda `revoked_at` y **no** `used_at`; el
  enlace revocado ya no sirve para consumir; y una solicitud legítima nunca se queda sin enviar
  aunque un tercero haya gastado la cota. **Tarea añadida en `run`**: la levantó el panel de
  seguridad de la sección 6 y la aprobó Jose. [R2.5]

## 7. R3 — Consumo del token de recuperación <!-- panel: PASS 2026-08-10 -->

- [x] 7.1 `backend/app/auth/application/recovery.py`: `ConsumePasswordResetUseCase` en el orden de
  D10 — validar la política (puro, antes de tocar la base de datos y antes de pagar bcrypt) →
  `consume_globally` → `get_active_by_id`; si algo no resuelve, `InvalidRecoveryTokenError`
  indistinguible. Al completar: `set_password_hash(..., temporary=False)`, revocar todas las
  familias de refresh con `PASSWORD_RESET`, `revoke_other_live` sobre los demás tokens vivos de la
  cuenta, y `AuditLog` `USER_PASSWORD_RECOVERED` con `actor_user_id = user.id` y `actor_ip`. **No**
  emite tokens de sesión. [R3.1, R3.2, R3.3, R3.5, R3.6, R4.4, R5.3]
- [x] 7.2 `clear_account_lock(user_id)` se llama **después** del commit y su fallo se registra
  como aviso sin tumbar la operación (D8). Test que verifica el orden y que un Redis caído no
  convierte un reset correcto en un error. [R3.5]
- [x] 7.3 `backend/app/auth/api/schemas.py` + `router.py`: `ResetPasswordRequest`
  (`{token, new_password}`, `extra="forbid"`) y `POST /api/v1/auth/reset-password`, anónimo,
  `204`; contador por IP comprobado **antes** de resolver el token. Añadir el par a
  `ANONYMOUS_ENDPOINTS`. [R3.1, R3.7]
- [x] 7.4b **Dos huecos de cobertura que cerró el panel de QA de las secciones 7-10**, los dos en
  tests que existían y parecían cubrir lo que no cubrían:
    - **R3.3 tenía cinco de sus seis causas.** `test_every_failure_answers_the_same_401` no
      presentaba nunca un token vivo cuyo **usuario está ACTIVE y cuyo tenant no**, que es la única
      de las seis que depende del join con `tenants` dentro de `get_active_by_id`. Añadida la sexta
      (tenant `SUSPENDED`, usuario activo, token vivo), con `assert len(cases) == 6` y la
      comprobación de que a ese usuario no se le movió el hash. **Comprobado que es de carga**:
      quitando `TenantModel.status == TenantStatus.ACTIVE` del repositorio, esa causa responde
      `204` y el test cae. Restaurada la línea.
    - **R3.5(c) no se probaba nunca sobre una cuenta bloqueada de verdad.** El test que lleva ese
      nombre —`test_the_previous_sessions_die_and_the_login_after_a_lockout_works`— corre sobre el
      fixture `api`, que instala `UnlimitedLoginThrottle` (`max_failures=10**9`): ahí no hay número
      de fallos que bloquee nada, así que la mitad «aunque la cuenta estuviera bloqueada» era una
      promesa del nombre. Añadido `test_a_reset_lets_a_LOCKED_account_log_in_again` sobre
      `throttled_api`: tres logins fallidos por HTTP, `is_account_locked` afirmado **antes** del
      reset —si no, un verde podría significar «nunca se bloqueó»—, la contraseña correcta
      rechazada estando bloqueada, y después del `204` el candado levantado y el login con la nueva
      en `200`. Es lo que ata el cableado: si el caso de uso dejara de recibir el throttle, sólo
      este test lo vería. [R3.3, R3.5]
- [x] 7.4 Tests de endpoint: `204` en el camino feliz; `401 INVALID_TOKEN` idéntico para token
  inexistente, ya usado, expirado, revocado, usuario inactivo y tenant inactivo; el hash no cambia
  en ninguno de esos casos; el segundo intento con el mismo token falla; la respuesta no lleva
  `access_token` ni `refresh_token`; y tras un reset el login inmediatamente posterior funciona
  aunque la cuenta estuviera bloqueada por 10 fallos. [R3.1, R3.3, R3.5, R3.6]

## 8. R4 — Tests de sumideros y aislamiento <!-- panel: PASS 2026-08-10 -->

- [x] 8.1 `backend/tests/auth/test_recovery_secret_sinks.py` (nuevo): ejercita el flujo completo
  R2→R3 y afirma que el token en claro **no aparece** en ninguna fila de
  `password_reset_tokens`, ni en `notification_logs.subject`/`body`, ni en `audit_logs.changes`,
  ni en el log de aplicación (`caplog`), ni en ninguna respuesta de la API. Es el test que R4.5
  exige que exista en rojo antes de dar los tres criterios por buenos. [R4.1, R4.2, R4.3, R4.5]
- [x] 8.2 En el mismo fichero: la contraseña —nueva y presentada— tampoco aparece en ninguno de
  esos cinco sumideros, en ninguna forma reversible ni enmascarada. [R4.3]
- [x] 8.3 Test de aislamiento en `backend/tests/auth/test_isolation.py` con dos tenants poblados:
  consumir el token del tenant A sólo toca al usuario de A, y `count_live`/`revoke_other_live` no
  ven filas del tenant B (DoD §28.18). **Tiene que vivir en `test_isolation.py`**, que es el hogar
  que el proyecto le da a esta obligación: la sección 2 ya dejó aserciones cruzadas equivalentes en
  `test_repositories.py`, pero quien audite «cobertura de aislamiento por módulo» leyendo
  `test_isolation.py` —como en todos los demás módulos— concluiría hoy que `password_reset_tokens`
  no tiene ninguna. Lo levantó el panel de tenancy de la sección 2. [R4.1]
  **Ampliada tras el panel de tenancy de la sección 6**: tiene que cubrir también el camino de
  **escritura** de `forgot-password`, no sólo el de consumo. `RequestPasswordResetUseCase` corre en
  superficie anónima, así que **el filtro global está apagado** durante toda la petición
  (`bind_session_to_tenant` no llega a ejecutarse) y sus dos `add()` son `INSERT`, que el filtro no
  cubriría ni estando encendido — la única protección es el `tenant_id` derivado de la fila más el
  `CrossTenantWriteError` de cada repositorio. Y las dos mitades se comprueban de forma distinta,
  porque **ejecutar el caso de uso no ejercita el guard**: su `tenant_id` sale siempre de la fila
  que acaba de resolver, así que nunca intenta una escritura cruzada.
    - **Alcanzable**: sembrar dos tenants, ejecutar `RequestPasswordResetUseCase` para cada uno, y
      comprobar que las filas de `password_reset_tokens` y `notification_logs` quedan en el tenant
      correcto y que una lectura scopada al otro no las ve.
    - **Escribible**: llamar **directamente** a `tokens.add(tenant_a.id, <token con tenant_b.id>)`
      y a `notifications.add(tenant_a.id, <log con tenant_b.id>)` y exigir `CrossTenantWriteError`
      —la forma que ya usan `test_adding_a_token_for_another_tenant_is_refused` y
      `test_add_refuses_a_log_of_another_tenant`—. Sin esto, la mitad «escribible» sería un guard
      vacuo, que es el fallo que este change ya ha cometido dos veces con la lista de exenciones
      (ver el docstring de `password_change_exempt_key`).
  Lo afinó el panel de tenancy de la sección 6 al revisar la propia ampliación. [R2.3, R6.3, R4.1]
  **Ampliada otra vez por el panel de las secciones 7-10**: el fichero de sumideros sembraba su
  propio token y buscaba **ése** en los cinco sumideros, pero la llamada a `forgot-password` que
  hace en el mismo test emite otro distinto e inobservable (D2). Los dos sumideros que escribe el
  camino R2 —`notification_logs` y el log de aplicación— quedaban ciegos al único token que ese
  camino puede filtrar: meter la salida de `render_recovery_email` en la fila habría dejado el
  fichero en verde. Cerrado con un fixture `emitted_token` que captura el valor donde
  `recovery.py` **mira el nombre** (no donde se define, que no lo alcanzaría), con su propio
  test de que la captura captura, y con los cinco sumideros buscando **los dos** secretos. Y en
  el camino del CLI faltaba el sumidero 4: la temporal sólo se probaba ausente de
  `audit_logs.changes`, así que un `logger.info("issued %s", temporary)` habría entrado en verde
  — añadida la aserción sobre `caplog` con guarda de no-vacuidad. [R4.2, R4.3, R4.5]

## 9. R6.5 — Vía de operación mientras no hay SMTP <!-- panel: PASS 2026-08-10 -->

- [x] 9.1 `backend/app/cli/reset_password.py` (nuevo), con el patrón de `app.cli.bootstrap`:
  `python -m app.cli.reset_password --email <dirección>` genera una temporal con
  `generate_temporary_password()`, la escribe con `set_password_hash(..., temporary=True)`, revoca
  las familias de refresh con `PASSWORD_RESET`, limpia el bloqueo por cuenta, escribe un `AuditLog`
  `USER_PASSWORD_RESET` con `actor_user_id = NULL`, y la imprime **una sola vez** por salida
  estándar (D12). Sin objetivo de Makefile: es una operación de rescate, no flujo normal.
  [R6.5]
- [x] 9.2 Tests en `backend/tests/auth/test_reset_password_cli.py` (nuevo): la contraseña impresa
  sirve para hacer login, el flag queda en verdadero, las sesiones previas quedan revocadas, el
  bloqueo por cuenta se levanta, la fila de auditoría existe sin actor, y un email inexistente
  falla con un mensaje claro sin tocar nada. [R6.5]
- [x] 9.2b **Añadido por el panel de las secciones 7-10, y es el hallazgo más grave del change**:
  `reset_password()` —la mitad que abre su propia sesión, y la que `main()` llama de verdad— leía
  `async_session_factory()()`. Una llamada de más: `async_session_factory` **es** el sessionmaker,
  así que la segunda cae sobre la `AsyncSession` que devuelve la primera y **toda** invocación real
  del comando moría con `TypeError: 'AsyncSession' object is not callable` antes de tocar nada. Los
  doce tests estaban en verde porque todos llamaban a `apply_reset` con una sesión ya hecha: el
  split que hace la tarea 9.2 testeable dejó sin cubrir justo la línea que compone. Lo encontró el
  arquitecto **ejecutando el comando**, no leyéndolo. Arreglado a una sola llamada (como
  `bootstrap.py:172`) y cerrado con cinco tests nuevos: uno atraviesa `reset_password()` con el
  sessionmaker apuntado al motor de test —se comprobó que falla si se reintroduce la doble
  llamada— y cuatro cubren `main()` (imprime la contraseña **una sola vez**, `0` con Redis caído
  diciendo que la contraseña **sí** cambió, `1` sin imprimir nada con una dirección inexistente).
  La tarea 11.4 lo confirma de punta a punta contra la app en marcha. [R6.5, D12]
- [x] 9.3 El `ConsoleEmailAdapter` **no se toca**: comprobar por `grep` que este change no añade
  ningún flag ni variable que imprima el enlace en el log (D12 lo descarta explícitamente).
  [R4.2, R6.4]

## 10. Contrato, configuración y documentación <!-- panel: PASS 2026-08-10 -->

- [x] 10.1 **Adelantada a la sección 3**, donde entraron los ajustes en `Settings`: la regla de
  `steering/documentation.md` es «Variable de entorno nueva → `.env.example` actualizado», y la
  dispara el cambio de configuración, no la sección de documentación. Lo levantaron a la vez los
  paneles de documentación y de seguridad de la sección 3.
  `.env.example`: los cuatro ajustes con comentario —los tres de D13 más
  `PASSWORD_RESET_GRACE_MINUTES`, de la enmienda de D7—, y los seis nombres `SMTP_HOST`,
  `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL`, `SMTP_USE_TLS` **reservados
  por nombre y sin valor**, con el comentario de que llegan con `hardening-release`. No entran en
  `Settings` ni en los `${VAR:?}` de los composes. [R6.6]
- [x] 10.2 Regenerar **las dos mitades del puente**: `make openapi` (reescribe
  `backend/openapi.json`) y `cd frontend && npm run api:generate` (reescribe
  `frontend/lib/api/generated/openapi.d.ts`), y commitear ambos. Los tres endpoints, el campo
  `must_change_password` de `CurrentUserResponse` y el `ErrorCode.PASSWORD_CHANGE_REQUIRED` tienen
  que aparecer en el diff. Extender `backend/tests/test_openapi_contract.py` si hace falta.
  **Ojo**: las dos mitades ya se regeneraron una vez en la sección 3, porque
  `ErrorCode.PASSWORD_CHANGE_REQUIRED` dejó el contrato obsoleto en cuanto entró y
  `tests/test_openapi_contract.py` se puso en rojo — el orden de `tasks.md` promete suite verde al
  cerrar cada sección. Aquello cubrió sólo el código de error; esta tarea sigue siendo obligatoria
  y tiene que volver a correr las dos, porque las tres rutas y `must_change_password` llegan
  después. [R1, R2, R3, R5.6]
  **Hecho**: las dos mitades regeneradas (`backend/openapi.json` +221, `openapi.d.ts` +152) con las
  tres rutas, `must_change_password` en `CurrentUserResponse` y `PASSWORD_CHANGE_REQUIRED` en el
  enum `ErrorCode` en el diff. `test_openapi_contract.py` **no necesitó extenderse**: es
  estructural —la cota de rutas es `>= 22` y el conjunto de prefijos ya nombra `auth`— y
  `test_the_committed_contract_matches_the_code` es la comprobación de frescura. 13 pasan.
  Nota de entorno: `npm run api:generate` **no** corre en el contenedor del frontend, porque el
  script resuelve `../backend/openapi.json` desde la raíz del repositorio y allí `/app` es sólo
  `frontend/`. En un worktree las dependencias viven en un volumen de Docker (`project.md`
  §«Worktree bootstrap»), así que hizo falta `npm ci` en el host —igual que en
  `frontend-api-contract.yml`— para poder generar.
- [x] 10.3 `docs/auth-account-recovery.md` (nuevo): operación de los tres endpoints, la política de
  contraseña, el gate `PASSWORD_CHANGE_REQUIRED`, el `EXTERNAL_DEPENDENCY` marcado de R6.4 —el
  aviso **no alcanza a la persona** hasta que llegue el adapter SMTP con `hardening-release`,
  porque el `ConsoleEmailAdapter` tiene prohibido registrar contenido y destinatario— y el
  procedimiento de rescate de D12. [R6.4, R6.5]
- [x] 10.4 `infra/environments/dev/RUNBOOK.md`: entrada para el comando de D12 como la vía de
  recuperación de un `TENANT_OWNER` bloqueado, en sustitución del SQL improvisado. [R6.5]
  **Hecho**: §8 nueva, con las cuatro cosas que el comando hace y un `UPDATE` a mano no, el
  comportamiento con Redis caído y por qué no hay objetivo de `make`.
- [x] 10.5 `README.md` de raíz: revisar si la sección de estructura/comandos necesita mencionar el
  módulo de CLI nuevo; si no cambia nada, dejarlo y anotarlo (el README describe el sistema
  actual, no el planeado). [R6.5]
  **Sí cambiaba**: el README tiene una lista explícita de «Comandos de consola del backend (no hay
  endpoint para ninguno, a propósito)», y `python -m app.cli.reset_password` pertenece a ella —es
  justo el caso, y además no tiene objetivo de `make` que lo cubra en otra parte. Añadido allí, y
  añadido también un párrafo de autoservicio en §«Entrar en la aplicación»: los tres endpoints, el
  gate con sus tres exenciones y que **el aviso todavía no entrega**, con enlace a
  `docs/auth-account-recovery.md`. Sin esto el README describiría un sistema sin recuperación,
  que dejó de ser el sistema actual.
- [x] 10.6 Regenerar el diagrama ER: la sección 2 añade una entidad de SQLAlchemy
  (`PasswordResetTokenModel`) y una columna (`users.must_change_password`), así que
  `docs/diagrams/2026-08-06_autohost-er-entidades.png` —que `steering/architecture.md` describe
  como generado **desde la metadata de SQLAlchemy**, con «28 entidades, 67 relaciones»— queda
  obsoleto. Regenerar con `/sdd:diagram`, borrar el anterior y actualizar la referencia y el
  recuento en `sdd/steering/architecture.md`. Lo exige `steering/documentation.md`: «Si el change
  altera arquitectura, flujos o modelo de datos de forma que un diagrama existente queda obsoleto
  → regenerarlo». **Tarea añadida en `run`**, no en `tasks`: la levantó el panel de la sección 2,
  porque el plan original no la contemplaba.
  **Hecho, y rehecho en `review` tras mergear `main`**: `docs/diagrams/2026-08-10_autohost-er-entidades.png`,
  generado leyendo `Base.metadata` tras `app.core.models_registry` y renderizado con
  `mmdc -s 2 -w 4080` para igualar el lienzo del anterior. El script de volcado es de un solo uso
  y **no se commitea** —no lo era antes tampoco—, así que la regla de recuento se escribe en
  `steering/architecture.md`, que es lo que hacía falta: la cifra de `pms-provider-resolution`
  («67 relaciones») no era reproducible, y con la regla de ahora —una relación por columna con
  clave ajena— aquel esquema daba 70, no 67.
  **La primera pasada salió con la cifra equivocada, y el panel de documentación de `review` lo
  cogió**: se generó desde el `Base.metadata` de esta rama, que iba 77 commits por detrás y por
  tanto no tenía `webhook_endpoints`; daba «29 entidades, 72 relaciones» y borraba un
  `2026-08-06_...` que en `main` ya no existía. Regenerado desde el metadata **mergeado**, queda
  **30 entidades, 73 relaciones** (71 pares de tablas distintos), y el borrado que corresponde es
  el de `2026-08-09_...`. Lección que vale más que la cifra: un diagrama generado desde el código
  hereda la antigüedad de la rama, así que en un change largo se regenera **después** de traer la
  base, no antes.

## 11. Verification

<!--
Panel de las secciones 7-10 (un solo panel para las cuatro, porque las tres primeras estaban
cerradas cuando se lanzó y la 10 es su documentación): arquitectura FAIL(1) → PASS,
seguridad FAIL(2) → PASS, QA FAIL(2) → PASS, tenancy/documentación/cicd/i18n PASS a la primera.
Una sola ronda de arreglos. Los cinco hallazgos y lo que se hizo con cada uno están anotados en
las tareas 7.4b, 8.3, 9.2b. Dos observaciones más, levantadas al re-verificar y también cerradas:
el cuerpo real de `clear_lock` no lo ejecutaba ningún test (ahora sí, contra el Redis de compose)
y el orden de D8 estaba afirmado en un comentario en vez de comprobado (ahora lo atestigua una
sesión ajena que lee la fila desde dentro del callback).

Panel de feature (`/sdd:review`, 2026-08-10): arquitectura, seguridad, QA, tenancy e i18n PASS;
documentación FAIL(3) y cicd FAIL(1). Cinco hallazgos, todos cerrados en una ronda, y tres de
ellos tenían la misma causa raíz — la rama iba **77 commits por detrás de `main`**, así que eran
defectos que sólo existían al mergear:
  1. La implementación estaba **sin commitear** (HEAD era el commit del proposal), así que
     `mark-ready` habría certificado un SHA que no contenía el change. Commiteada en dos commits.
  2. **Dos cabezas de Alembic** al mergear: `a7c4e91b2d05` y `a4d17e83b6c1` declaraban el mismo
     padre. Re-apuntada; los tres pasos de CI verificados sobre una base de datos limpia de
     verdad (11 migraciones arriba, `check` sin deriva, 11 abajo) en vez de sobre la de dev, que
     tenía estado que enmascaraba el fallo.
  3. **La cláusula de gracia de R2.5 no la protegía ningún test contra el SQL real** — el panel
     de QA borró `created_at <= older_than` y la suite entera siguió en verde, porque los cuatro
     tests de repositorio pasaban `older_than=now` sobre filas de minutos. Es el cuarto test
     vacuo de este change (7.4b, 8.3, 9.2b). Cerrado en `test_repositories.py` con los dos lados
     del límite, y comprobado que el primero **falla** si se quita la cláusula.
  4. Diagrama ER y `steering/architecture.md`: ver 10.6.
  5. «Los tres ajustes» cuando son cuatro: ver 3.1 y 10.1.

Y un sexto que no vino del panel sino de correr la suite **después** de mergear, que es el único
sitio donde se veía: `tests/auth/test_reset_password_cli.py` dejaba envenenado el cliente global
de `app.core.redis` —memoiza uno solo, y `redis.asyncio` lo ata al bucle de eventos vivo cuando
se construye—, así que el siguiente test de la sesión que tocaba Redis de verdad moría con
`RuntimeError: Event loop is closed`. Lo pagaba
`tests/integrations/test_webhook_receiver_api.py::test_the_router_drives_the_real_throttle`,
cientos de tests más tarde y en otro módulo, y **pasaba en aislamiento**: sólo una ejecución
completa lo enseña. Producción no se ve afectada (la API mantiene un bucle toda su vida y el CLI
hace `asyncio.run` una vez y sale), así que el arreglo es una fixture `autouse` en el fichero que
lo provoca. Vale registrarlo porque es la forma que ninguno de los dos paneles podía ver: el de
sección no corre la suite entera, y el de feature la corrió **antes** de traer `main`.
-->


- [x] 11.1 Suite completa del backend en verde:
  `docker compose exec backend uv run pytest` (con el stack parado,
  `docker compose run --rm backend uv run pytest`).
  **4834 pasan, 35 se saltan, 0 fallan** (681 s). Los 35 saltos son los de siempre, ninguno de
  este change. La cuenta de partida al abrirlo eran 4603, así que el change deja **+231 tests**.
  **Re-corrida en `review` tras mergear `main`: 5715 pasan, 35 se saltan, 0 fallan** (200 s). El
  salto de 4834 a 5715 es casi todo de `main` (`reservations-webhooks`, `dashboard-api`,
  `backend-suite-runtime` traen sus suites, y ese último es también el motivo de que 5715 tarden
  200 s donde 4834 tardaban 681); de este change son los dos tests nuevos del límite de gracia.
  Hicieron falta **tres** ejecuciones completas: la primera destapó 6 fallos —4 de un test de
  `dashboard-api` que llamaba a `get_authenticated_request` con la firma de antes de R5.4, 1 de
  contenedor rancio sin el montaje que `app-version-provenance` añadió al compose, y 1 de fuga
  del cliente global de Redis (arriba)—, la segunda dejó sólo ése, y la tercera cerró en verde.
- [x] 11.2 Migraciones: `docker compose exec backend uv run alembic upgrade head`,
  `uv run alembic check` (los modelos coinciden con el esquema migrado) y
  `uv run alembic downgrade base` — los tres pasos que corre `backend-tests.yml`.
  **Los tres en verde**: `upgrade head` deja `a7c4e91b2d05 (head)`, `check` responde «No new
  upgrade operations detected», y `downgrade base` baja hasta la raíz sin error. La base de dev
  se volvió a subir a `head` después, porque `downgrade base` se lleva sus datos.
  **Re-verificado en `review` tras mergear `main`, y esta vez sobre una base de datos limpia de
  verdad**: la de dev tenía `alembic_version = a7c4e91b2d05` de la pasada anterior, así que
  `upgrade head` no hacía nada y `check` fallaba pidiendo `webhook_endpoints` — el estado de dev
  enmascaraba el resultado en las dos direcciones. Con una base recién creada: **11 migraciones
  arriba** hasta `a7c4e91b2d05 (head)` pasando por `a4d17e83b6c1`, `check` sin deriva, y **11
  abajo** hasta base. Se hizo así, y no con `downgrade base` sobre dev, porque había una suite
  corriendo contra ese stack.
- [x] 11.3 Contrato sin deriva: `docker compose run --rm --no-deps -T backend python -m
  app.cli.openapi --check` y `cd frontend && npm run api:check`, que son los que ejecutan
  `api-contract.yml` y `frontend-api-contract.yml`.
  **Las dos en verde** (salida 0; la del frontend dice «api: generated types are up to date»). La
  mitad del frontend se invocó como `node scripts/generate-api-types.mjs --check`, que es
  literalmente lo que `npm run api:check` ejecuta: en este entorno el hook de shell reescribe
  `npm run …` y el subcomando no llega.
- [x] 11.4 Comprobación manual del flujo que **sí** se puede ejercitar sin SMTP: `make bootstrap`,
  login con la temporal de un usuario recién creado por `POST /api/v1/users`, verificar el
  `403 PASSWORD_CHANGE_REQUIRED`, cambiar la contraseña por `POST /api/v1/auth/change-password` y
  comprobar que las sesiones anteriores quedaron revocadas; después, ejecutar
  `python -m app.cli.reset_password --email …` y entrar con lo que imprime. El flujo R2/R3 **no**
  se puede ejercitar a mano en dev (D12) — queda cubierto sólo por la suite. Desde un worktree no
  hay puertos publicados, así que esta comprobación se hace desde el clon principal o vía
  `docker compose exec`.
  **Hecha por `docker compose exec` contra la app en marcha**, en veinte pasos, todos como se
  esperaba: login del owner → `POST /users` → login con la temporal (**permitido**) → `/auth/me`
  con `must_change_password=true` → `GET /properties` con `403 PASSWORD_CHANGE_REQUIRED` →
  `refresh` permitido con la bandera puesta → `change-password` con la actual equivocada `401` y
  con una de menos de 12 `422` → `change-password` `204` → las **dos** familias de refresh
  (incluida la de la llamada que la cambió) `401` → la temporal ya no entra `401` → login con la
  elegida `200`, `must_change_password=false` y `GET /properties` `200` → `forgot-password` `202`
  con dirección real y `202` con una inexistente → `reset-password` con un token inventado `401`.
  Después, `python -m app.cli.reset_password --email …` imprimió la temporal, se entró con ella
  `200`, `/auth/me` volvió a `must_change_password=true`, `GET /properties` volvió a `403` y la
  contraseña que el rescate reemplazó dio `401`.
  Dos cosas que la comprobación enseñó y la suite no: **el comando de rescate estaba roto**
  (`async_session_factory()()`, ver la nota del panel en la sección 9 — esta comprobación es la
  que lo confirma arreglado de punta a punta), y el segundo login tras el flujo completo salió
  `429 RATE_LIMITED`, que es el presupuesto por IP de R2.4 comportándose como debe: los tres
  endpoints y `login` lo comparten, y veinte llamadas desde la misma IP lo agotan. Se esperó a
  que caducara la ventana.
