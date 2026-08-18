# Autenticación, autorización y tenencia

## Purpose

Esta capacidad autentica a los usuarios del producto con email y contraseña, emite y
renueva tokens JWT, decide qué puede hacer cada rol y garantiza que los datos de un
tenant sean inalcanzables desde la cuenta de otro. Es también el primer *vertical slice*
del backend: establece el patrón de capas (`api/` → `application/` → `domain/` ←
`infrastructure/`, ADR 0004) que heredan los módulos posteriores.

No incluye alta ni administración de usuarios —eso es `user-management`
(`specs/user-management.md`), que también añadió al enum de revocación las dos razones
administrativas y los cuatro permisos de administración al catálogo de esta capacidad— ni
acceso de huéspedes. Tampoco el autoservicio de credenciales: el cambio de contraseña por el
propio usuario y la recuperación anónima son `auth-account-recovery`
(`specs/auth-account-recovery.md`), que se apoya en los mecanismos de aquí —el hasher, el
throttle, la revocación de familias de refresh— y aporta además la política de contraseña que
esta capacidad nunca fijó. El comando de bootstrap sigue siendo la única forma de **crear la
primera cuenta** de un entorno recién levantado; recuperar una cuenta existente ya no exige
tocar la base de datos a mano.

## Requirements

### Identidad: el email identifica la cuenta en toda la instalación

- THE SYSTEM SHALL tratar el email normalizado (recortado y en minúsculas) como
  identificador único de usuario **en toda la instalación**, no por tenant, garantizado
  por el índice único funcional `uq_users_lower_email` sobre `lower(email)`.
- THE SYSTEM SHALL normalizar el email tanto al escribir como al leer, y comparar en SQL
  por igualdad simple contra el valor ya normalizado en Python — nunca aplicando
  `lower()` dentro de la consulta.
- IF una escritura introduciría una dirección que ya existe bajo cualquier tenant,
  incluso con distinta caja, THEN THE SYSTEM SHALL rechazarla en la base de datos.
- Es una desviación deliberada de PRD §7.3, que define `UNIQUE(tenant_id, email)`, y
  `find_by_email_globally` —una de las consultas sin scope de tenant del sistema— depende de
  ella: con unicidad por tenant, el email no identificaría la cuenta y quien pudiera crear
  usuarios en otro tenant dejaría fuera del producto a una cuenta existente. Motivo completo y
  alternativas descartadas en ADR 0005.
- Todas comparten el mismo motivo estructural: quien presenta la credencial no está autenticado
  y no puede aportar un tenant, así que el scope se **deriva** de la fila encontrada.
  `PasswordResetTokenRepository.consume_globally` lo hace desde `auth-account-recovery`, y
  `SqlAlchemyGuestAccessTokenRepository.find_live_by_token_hash` desde
  [`guest-portal-api.md`](guest-portal-api.md).
- THE SYSTEM SHALL mantener su **enumeración en un solo sitio y en forma ejecutable** —el
  conjunto de llamantes de `require_unmarked_session` (`backend/app/core/db.py`), afirmado por
  `backend/tests/test_unscoped_reads.py`—, y todo lo demás la cita en vez de repetir el
  recuento. Ese censo cubre **una clase completa**: las lecturas que resuelven el tenant a partir
  de la fila que leen — las cinco, desde que el panel de review de
  `rule11-ownership-single-source` encontró que `find_by_token_hash` estaba fuera. No es el
  conjunto de toda consulta que corre sin tenant: los drenajes de cola de `webhook_events`, cuyo
  `tenant_id` es nullable, exigen sesión sin marcar por otro motivo —una sesión marcada esconde
  sus filas `NULL` sin error— y no llaman al guard. Esa frontera la declara el propio test en vez
  de dejarla implícita. Vivió en prosa, en el docstring de `find_by_email_globally`, hasta
  `rule11-ownership-single-source` (2026-08-17): decía «tres» cuando eran cinco —el recuento en
  prosa se equivocó cuatro veces, la última mientras se le buscaba sustituto—. Es el control de auditoría de la regla 1 de `steering/security.md`, y la lista se
  quedó obsoleta dos veces por estar copiada: `auth-account-recovery` y `guest-portal-api`
  añadieron cada uno un caso en ramas paralelas y cada uno actualizó el número a «dos», así que
  el merge dejó tres consultas y un número que decía dos. **La auditoría por `grep` del sufijo
  `*_globally` dejó además de ser exhaustiva**: la del portal no lleva el sufijo ni vive en ese
  módulo. **Quien añada una consulta sin scope de esa clase la declara en tres sitios y ninguno
  es una viñeta de spec**: la llamada al guard como primera sentencia, su entrada en
  `DECLARED_UNSCOPED_READS` (`backend/tests/test_unscoped_reads.py`) y un test que la invoque
  sobre sesión marcada y exija el fallo. Una viñeta aquí **cita** el censo; reenunciarlo es
  devolverle un segundo hogar a la enumeración, que es lo que este párrafo narra haber fallado
  dos veces.
- WHERE en el futuro una misma identidad deba pertenecer a varios tenants, THE SYSTEM
  SHALL modelarlo como identidad global más memberships separadas, nunca repitiendo la
  dirección.

### Login

- WHEN se envía a `POST /api/v1/auth/login` un email y una contraseña que corresponden a
  un usuario `ACTIVE` de un tenant `ACTIVE`, THE SYSTEM SHALL responder `200` con token de
  acceso, token de refresh, tipo de token y la vida del token de acceso en segundos.
- WHEN un login tiene éxito, THE SYSTEM SHALL actualizar `last_login_at` del usuario con
  el instante de la autenticación en UTC, mediante un `UPDATE` de esa única columna.
- IF un login falla por cualquier motivo, THEN THE SYSTEM SHALL NOT modificar
  `last_login_at`.
- THE SYSTEM SHALL verificar la contraseña contra el hash bcrypt de `User.password_hash` y
  no almacenar, registrar ni devolver nunca la contraseña en claro ni ninguna forma
  reversible de ella.
- IF el email no existe, la contraseña no coincide, el usuario no está `ACTIVE`, su tenant
  no está `ACTIVE`, o la cuenta está bloqueada, THEN THE SYSTEM SHALL responder `401` con
  un cuerpo indistinguible entre esos casos
  (`{"error": {"code": "INVALID_CREDENTIALS", ...}}`).
- THE SYSTEM SHALL gastar el mismo trabajo de bcrypt en **todos** los caminos de fallo,
  incluidos los que nunca llegan a verificar un hash (email inexistente, cuenta
  bloqueada), verificando contra un hash señuelo. Sin eso, la diferencia de latencia entre
  "no existe" y "existe" enumera usuarios y revela el estado de bloqueo aunque las
  respuestas sean idénticas.
- THE SYSTEM SHALL construir el hash señuelo al importar el módulo, no en la primera
  petición que lo necesite: pagarlo en caliente costaría el doble que una verificación
  real y sería un bit de "esta dirección no existe" por vida de proceso.
- IF una contraseña excede 72 bytes en UTF-8, THEN THE SYSTEM SHALL rechazarla al crear el
  hash en lugar de truncarla, y devolver `False` al verificarla — bcrypt ignora todo lo que
  pasa de ese límite, así que aceptarla haría equivalentes dos contraseñas distintas. El
  atajo es simétrico entre la verificación y el señuelo, para no invertir el oráculo de
  latencia.
- Esta capacidad **no fija política de contraseña alguna**: el tope de 72 bytes es una
  propiedad de bcrypt, no una política. La política —mínimo de 12 caracteres, tope de 72 bytes
  y ninguna regla de composición— la aporta `auth-account-recovery` en
  `app/auth/domain/password_policy.py`, y se aplica en los bordes que aceptan una contraseña
  elegida por una persona; el login se limita a verificar la que ya existe.

### El hash de contraseña no bloquea el event loop

- THE SYSTEM SHALL ejecutar toda operación bcrypt —crear hash, verificar y señuelo— en un
  hilo de trabajo, nunca en el hilo del event loop.
- THE SYSTEM SHALL acotar el número de operaciones bcrypt simultáneas mediante un
  limitador **compartido por el proceso** (`BCRYPT_MAX_CONCURRENCY`; por defecto, el número
  de CPUs visibles). El limitador no puede vivir en la instancia del adaptador: la
  inyección de dependencias construye una por petición, así que acotaría cada petición
  contra sí misma.
- El puerto `PasswordHasher` es asíncrono a propósito, aunque el cálculo sea puro CPU: la
  frontera `await` es lo que impide que un llamante futuro vuelva a ejecutarlo en línea.
- Con el coste 12 configurado, una verificación cuesta ~250 ms de CPU. Medido: ejecutada en
  el loop lo detiene esos 250 ms y ocho simultáneas se serializan en 1,87 s; en hilos, las
  ocho tardan 271 ms sin detenerlo. bcrypt libera el GIL, así que el paralelismo es real.
- Esto acota el daño, no lo elimina: el coste de CPU por intento no cambia, y el límite por
  IP sigue siendo la defensa que acota el número de intentos.

### Renovación con rotación, cierre de sesión y usuario actual

- WHEN se presenta un token de refresh válido y utilizable a `POST /api/v1/auth/refresh`,
  THE SYSTEM SHALL marcarlo como usado, emitir un par nuevo y persistir la sesión hija con
  el mismo `family_id` y `parent_id` apuntando a la consumida.
- THE SYSTEM SHALL decidir quién consume una sesión con **una única sentencia condicional**
  (`UPDATE ... WHERE used_at IS NULL AND revoked_at IS NULL AND expires_at > now`) y
  comprobando `rowcount`. Separar la comprobación de la escritura permitiría que dos
  presentaciones simultáneas del mismo token rotaran ambas, y que una revocación
  concurrente perdiera el desempate.
- WHEN dos peticiones presentan el mismo token de refresh a la vez, THE SYSTEM SHALL dejar
  que solo una lo consuma; la que pierde se trata exactamente como una reutilización.
- IF se presenta un token de refresh ya usado, THEN THE SYSTEM SHALL revocar **la familia
  completa** con razón `REUSE_DETECTED` —incluida la sesión legítima que rotó, cuya hija
  queda revocada e inutilizable— y responder con error.
- IF una revocación concurrente (logout, o reuso en un hermano) ocurre entre la lectura y
  la escritura de una renovación, THEN THE SYSTEM SHALL impedir que esa renovación inserte
  una sesión hija utilizable: no queda ninguna sesión usable en la familia.
- WHEN se llama a `POST /api/v1/auth/logout` con un token de acceso válido, THE SYSTEM
  SHALL revocar la familia de refresh de esa sesión con razón `LOGOUT`. La familia viaja en
  el claim `fam` del token de acceso, porque el endpoint va autenticado con el access y su
  `jti` no guarda vínculo con la familia.
- Los tokens de acceso ya emitidos siguen siendo válidos hasta expirar (como máximo 15
  minutos) después de un logout: no existe lista de revocación de access tokens.
- WHEN se llama a `GET /api/v1/auth/me` con un token de acceso válido, THE SYSTEM SHALL
  devolver el usuario autenticado sin su `password_hash`.
- Una rotación **no** es una revocación: la sesión consumida queda con `used_at` puesto y
  `revoked_at` nulo.
- El enum `SessionRevokedReason` tiene cuatro valores. `LOGOUT` y `REUSE_DETECTED` son los de
  esta capacidad, en los que el dueño de la sesión **es** el actor. `USER_DEACTIVATED` y
  `PASSWORD_RESET` los añadió `user-management` para lo contrario: un administrador que actúa
  sobre la cuenta de otra persona. Hacen falta porque `POST /api/v1/auth/refresh` no atraviesa
  `get_authenticated_request` y por tanto no revalida el estado de la cuenta — sin revocar, una
  cuenta desactivada seguiría emitiendo pares nuevos toda la vida del refresh.

### Tokens

- THE SYSTEM SHALL firmar con HS256, con el algoritmo fijado como constante en el código y
  pasado explícitamente al verificar — nunca configurable, para que un despliegue mal
  configurado no pueda desactivar la verificación de firma.
- THE SYSTEM SHALL incluir en cada token el identificador de usuario, el `tenant_id`, el
  rol, el instante de emisión, el de expiración, un `jti` y el tipo (`access` o `refresh`);
  ambos llevan además `fam`.
- El `jti` del token de refresh **es** la clave primaria de su fila en `user_sessions`, así
  que el token no se almacena ni en claro ni hasheado: la firma prueba autenticidad y la
  fila aporta el estado.
- IF un token de refresh se presenta donde se espera uno de acceso, o al contrario, THEN
  THE SYSTEM SHALL rechazarlo.
- THE SYSTEM SHALL fijar la vida del token de acceso en 15 minutos y la del de refresh en
  7 días, ambas configurables por entorno.
- IF la clave de firma JWT no está configurada al arrancar, o tiene menos de 32 caracteres
  no blancos, THEN THE SYSTEM SHALL fallar el arranque en vez de servir con una clave
  débil o por defecto.

### Autorización por rol, denegando por defecto

- THE SYSTEM SHALL materializar la política de PRD §6 como un enum `Permission` y un mapa
  de rol a permisos en `app/auth/domain/policy.py`, sin permisos especulativos: cada
  capacidad añade los que sus endpoints declaran. Además de los de autoservicio
  (`READ_OWN_PROFILE`, `MANAGE_OWN_SESSION` y `READ_OWN_NOTIFICATIONS`), que PRD §6 concede a
  todo rol que puede autenticarse, el catálogo contiene hoy los que añadió `reservations`
  (`READ_RESERVATIONS`, `MANAGE_RESERVATIONS`), los cuatro de `user-management`
  (`READ_USERS`, `MANAGE_USERS`, `READ_TENANT_SETTINGS`, `MANAGE_TENANT_SETTINGS`), los dos de
  `properties-crud` (`READ_PROPERTIES`, `MANAGE_PROPERTIES`), los cinco de `cleaning` y los
  cuatro de `maintenance` (`READ_INCIDENTS`, `MANAGE_INCIDENTS`, `EXECUTE_INCIDENTS`,
  `RESPOND_OWNER_APPROVALS`), todos diferenciados por rol.
- **`TECHNICIAN` dejó de ser un rol sin capacidades el 2026-08-15.** Hasta `maintenance` tenía
  autoservicio y nada más: existía y no podía hacer nada. Ahora suma `READ_INCIDENTS` y
  `EXECUTE_INCIDENTS` —exactamente lo que necesita el ciclo del técnico— y NEVER SHALL poder
  clasificar, triar, asignar, cancelar ni responder aprobaciones, que son de
  `PROPERTY_MANAGER` y `TENANT_OWNER` ([`maintenance.md`](maintenance.md)). Es el mismo reparto
  que `CLEANER` tiene con `_CLEANING_EXECUTE`, con una diferencia deliberada: el manager
  **también** puede conducir el ciclo del técnico, para desatascar.
- WHERE un rol sólo puede ver una parte de las filas de una capacidad, THE SYSTEM SHALL derivar
  esa restricción del **rol del token** y NEVER SHALL aceptarla como parámetro de la petición.
  `TECHNICIAN` es el caso vivo: sólo ve las incidencias que tiene asignadas, la ruta no expone
  filtro por técnico, y una incidencia de otro devuelve el **mismo `404`** que una inexistente,
  para que el endpoint no sirva de sonda de existencia.
- **`properties-crud` es el único reparto que no se puede citar de PRD §6**, y por eso su razón
  queda registrada en lugar de referenciada: §6 no nombra capacidad de crear ni editar
  propiedades para ningún rol. Da a `TENANT_OWNER` «ver sus propiedades y reservas» —una
  lectura— y a `PROPERTY_MANAGER` «acceder a todos los datos operativos», así que el reparto
  reproduce el de `reservations`: la propietaria ve el inventario y el manager lo opera.
- WHEN un usuario autenticado invoca un endpoint que exige un permiso que su rol no tiene,
  THE SYSTEM SHALL responder `403` con `{"error": {"code": "FORBIDDEN", ...}}`.
- THE SYSTEM SHALL declarar el permiso exigido en cada ruta mediante la dependencia
  `require(permission)`, que etiqueta su closure con ese permiso.
- Un test estructural recorre las rutas registradas y falla si alguna no declara permiso y
  no está en una lista explícita de endpoints anónimos. La lista es un conjunto de
  `(método, path)`: por path solo, un `GET /login` o un `POST /health` heredaría la
  exención. El test aplana los routers incluidos (esta versión de FastAPI no lo hace),
  afirma que encuentra los endpoints de auth para no pasar en vacío, y falla ante cualquier
  tipo de ruta que no pueda inspeccionar — un websocket o un `mount` no pueden satisfacer
  una comprobación de permisos, así que ignorarlos dejaría pasar superficie sin autenticar.

### Aislamiento por tenant

- WHEN se atiende cualquier petición autenticada, THE SYSTEM SHALL derivar el `tenant_id`
  efectivo únicamente de los claims verificados del token, e ignorar cualquier `tenant_id`
  presente en el cuerpo, la query string, la ruta o las cabeceras.
- THE SYSTEM SHALL revalidar en cada petición autenticada, contra la base de datos, que el
  usuario y su tenant siguen `ACTIVE`, y tomar el rol de la fila almacenada, no del claim
  — así una suspensión o un cambio de rol surten efecto de inmediato en lugar de esperar a
  que expire el token.
- IF un token válido nombra un tenant inexistente o no `ACTIVE`, o un usuario inexistente o
  no `ACTIVE`, THEN THE SYSTEM SHALL responder `401`.
- WHEN se construye el `RequestContext` de una petición autenticada, THE SYSTEM SHALL incluir
  el `preferred_language` del usuario como un `Locale` ya resuelto, tomado de la **misma fila
  que la revalidación acaba de releer**, de modo que no cueste ninguna consulta adicional. Lo
  añadió `dashboard-api` (su diseño D3) para que la capa de lectura pueda localizar textos sin
  releer el usuario ni depender de `Accept-Language`: PRD:205 fija el idioma en la preferencia
  del usuario autenticado, que es la fila y no el navegador.
- IF `users.preferred_language` contiene un valor que no corresponde a ningún `Locale`
  soportado —la columna es `String(5)` y no lo restringe—, THEN THE SYSTEM SHALL degradar al
  idioma por defecto en vez de fallar la petición.
- THE SYSTEM SHALL pasar el `tenant_id` efectivo como parámetro explícito a cada método de
  repositorio, que filtra por él. Es el mecanismo autorizado.
- THE SYSTEM SHALL aplicar además, como red de seguridad, un filtro global por tenant en el
  evento `do_orm_execute` de SQLAlchemy, activo **solo** en sesiones marcadas con el tenant
  de la petición. Tiene cinco límites documentados en `app/core/db.py` y por eso no
  sustituye al parámetro explícito: cubre solo SELECT/UPDATE/DELETE del ORM; no actúa en
  sesiones sin marcar (bootstrap, el login anónimo —que lo necesita—, `POST /auth/refresh` y
  los dos endpoints anónimos de `auth-account-recovery`, `POST /auth/forgot-password` y
  `POST /auth/reset-password`, que resuelven la cuenta antes de conocer su tenant;
  **las tareas Celery dejaron de estarlo con `celery-jobs`**, que abre
  una sesión marcada por tenant y enumera los tenants desde otra que nunca se marca; y
  `make seed-demo`, el primer llamante que **lee sin marcar y marca a media ejecución** — resuelve
  el tenant por nombre y comprueba el conflicto global de correos con la sesión aún limpia, y sólo
  entonces la marca, porque «sin scope» es una propiedad de la sentencia y no del método: marcada,
  el listener añade la cláusula de tenant también a `find_by_email_globally`); no protege INSERTs; no cubre el mapa de identidad; y no alcanza
  las tablas hijas sin `tenant_id` propio (`messages`, `cleaning_checklist_completions`,
  `cleaning_photos`), que deben unirse a su padre scopado y traer su propio test.
- WHEN un comando o job resuelve credenciales de PMS propiedad a propiedad, THE SYSTEM SHALL
  marcar la sesión con el tenant **antes** de la resolución y mantener una sesión por tenant.
  Es el mismo patrón que `celery-jobs` (sesión marcada por tenant, enumeración de tenants desde
  otra sin marcar), y aquí no es una precaución: sin el marcado, el filtro global no actúa y la
  consulta de credenciales devolvería las de cualquier tenant, que en esta tabla no filtra datos
  sino que concede escritura sobre el sistema del cliente.

- El escaneo de clases con `tenant_id` **no** se memoiza, y `app/core/models_registry.py`
  importa los diez módulos de modelos en un único sitio compartido por la aplicación,
  Alembic y los tests: una caché excluiría para siempre a cualquier entidad importada
  después de la primera consulta filtrada, y sin el registro la red cubriría menos tablas
  en producción que en la suite.
- THE SYSTEM SHALL incluir tests automáticos que, para cada uno de los cinco roles,
  demuestren que un usuario del tenant A no alcanza datos del tenant B a través de la
  superficie que esta capacidad expone: el puerto `UserRepository` con dos tenants
  poblados, y `GET /api/v1/auth/me` con un token que nombra otro tenant para un `user_id`
  real.
- **Alcance declarado**: el `404` frente a `403` al referenciar un recurso de otro tenant y
  la matriz completa de autorización por endpoint de negocio y por rol **no** pertenecen a
  esta capacidad. Ninguno de sus cuatro endpoints recibe un identificador de recurso —
  `login`, `refresh`, `logout` y `me` son autorreferenciales, y los tres que añadió
  `auth-account-recovery` también—, así que no son verificables
  aquí sin inventar un endpoint de negocio. Cada capacidad con endpoints de negocio
  demuestra esos dos criterios sobre **sus** endpoints: los demostraron `reservations`
  (`specs/reservations.md`) y `user-management` (`specs/user-management.md`), en ese orden —
  no solo `user-management` como se anotó aquí al archivar esta capacidad, porque el orden
  real de ejecución los invirtió. **Ya no queda ninguno pendiente.**

### Protección de los endpoints de autenticación

- WHILE una misma dirección IP ha consumido 10 o más peticiones del presupuesto en el último
  minuto, THE SYSTEM SHALL responder `429` con `{"error": {"code": "RATE_LIMITED", ...}}` sin
  comprobar las credenciales.
- WHEN una cuenta acumula 10 intentos fallidos consecutivos, THE SYSTEM SHALL bloquear los
  siguientes intentos sobre esa cuenta durante 15 minutos (configurable) respondiendo el
  mismo `401` genérico.
- IF un intento se rechaza **por** el bloqueo, THEN THE SYSTEM SHALL NOT contarlo como
  fallo: contar un intento que nunca se evaluó empujaría el bloqueo hacia delante en cada
  prueba y dejaría de estar acotado a 15 minutos.
- WHEN un login tiene éxito, THE SYSTEM SHALL poner a cero el contador de fallos de esa
  cuenta.
- El contador por cuenta (`login:fail:<uid>`) y su bloqueo (`login:lock:<uid>`) **no son
  exclusivos del login**: `auth-account-recovery` los alimenta también desde
  `POST /api/v1/auth/change-password`, que verifica una contraseña igual que el login y sin
  ellos sería una vía de probarla más barata que él. Y `POST /api/v1/auth/reset-password`
  **los borra** al completar una recuperación, porque 10 fallos son justo lo que precede a un
  «he perdido la contraseña» y el bloqueo seguiría rechazando el login inmediatamente
  posterior. La regla 7 de `steering/security.md` se aplica a **todo** camino que verifica una
  contraseña, no solo al anónimo.
- THE SYSTEM SHALL mantener los contadores en Redis, el único almacén compartido entre los
  procesos `backend` y `worker`, de forma que el límite se respete con varios workers.
- **De qué depende esta garantía, y no es del código**: los contadores viven en un Redis que
  corre **sin `requirepass`**, así que quien alcance su puerto puede borrarlos entre intentos y
  entonces ni el límite por IP ni el bloqueo por cuenta se disparan. En dev local lo que los
  protege es que `docker-compose.yml` publica `redis` **solo en `127.0.0.1`** (ver spec
  `local-environment` §Postura de red del stack local) — el bind, no la autenticación. Devolver
  ese mapeo a `0.0.0.0` deja estos dos requisitos sin defensa efectiva, aunque el código no
  cambie. Residual aceptado: otro proceso de la propia máquina sí puede tocarlos.
- THE SYSTEM SHALL (re)aplicar la expiración de cada contador en **todos** los intentos
  (`EXPIRE ... NX`), no solo cuando el contador se crea: `INCR` y `EXPIRE` son dos viajes,
  y si el segundo no llega a ejecutarse la clave se queda sin TTL y esa IP queda bloqueada
  para siempre en lugar de un minuto.
- La ventana es fija, no deslizante: en el límite entre dos minutos una IP puede hacer
  hasta el doble del límite seguidas. El bloqueo por cuenta cubre exactamente esa ráfaga.
- THE SYSTEM SHALL registrar cada intento fallido y cada bloqueo en el log de la
  aplicación, en inglés y sin la contraseña presentada.
- WHERE la API se sirve por el camino público, THE SYSTEM SHALL contabilizar el límite de
  10 intentos/min contra la dirección real del cliente y no contra la del proxy, de modo
  que dos clientes distintos no compartan presupuesto y ninguno pueda agotar el del otro.
- WHERE `POST /api/v1/auth/refresh` es alcanzable desde internet, THE SYSTEM SHALL
  aplicarle el **mismo** límite por IP que a `login`, comprobado **antes** de decodificar el
  token presentado, respondiendo `429` con `code` `RATE_LIMITED`. El endpoint es anónimo por
  diseño —el refresh token es la credencial— y acuña access tokens, así que publicarlo sin
  medir dejaría una operación de credenciales con un molinillo ilimitado.
- THE SYSTEM SHALL contabilizar en **un solo** contador por IP (`login:ip:<ip>`) los **cuatro**
  endpoints anónimos de credenciales: `login`, `refresh` y —desde `auth-account-recovery`—
  `POST /auth/forgot-password` y `POST /auth/reset-password`; y THE SYSTEM SHALL NOT dar a
  ninguno un presupuesto propio: partirlo permitiría gastar cuatro presupuestos desde una
  dirección. Coste aceptado: un refresh legítimo puede recibir `429` si ese cliente ya gastó el
  presupuesto — con access tokens de 15 minutos, unos pocos refresh por hora contra un techo de
  diez por minuto.
- `POST /auth/change-password` es la excepción, y por la razón contraria: su llamante está
  autenticado, así que se contabiliza por `user_id` y no por IP (arriba), que es una clave más
  precisa.
- **Residual conocido**: el contador es **por IP y global**, no por tenant. Con la API
  alcanzable desde internet, usuarios de **tenants distintos** detrás de un mismo NAT o
  CGNAT comparten presupuesto de login, un escenario que no era alcanzable mientras el
  backend escuchaba solo en loopback. No viola la regla 1 de `steering/security.md` (no
  cruza dato alguno entre tenants) ni la 7 (el límite es por IP, como pide); es equidad y
  disponibilidad. El bloqueo **por cuenta** sí está acotado por `user_id`, que es único
  global, así que un ataque contra la cuenta de un tenant no bloquea la de otro.

### Identificación del cliente

- THE SYSTEM SHALL usar **la IP del peer del socket** como identidad del cliente, y THE
  SYSTEM SHALL NOT leer ninguna cabecera de reenvío en código de aplicación.
- THE SYSTEM SHALL delegar la resolución de la cabecera de proxy en
  `ProxyHeadersMiddleware` de uvicorn, arrancado con `--proxy-headers` y con
  `--forwarded-allow-ips` nombrando explícitamente los peers de confianza, de modo que
  `scope["client"]` ya sea la IP real del cliente cuando —y solo cuando— la petición viene
  de un proxy de confianza.
- THE SYSTEM SHALL pinear `--forwarded-allow-ips` en **ambos** stages de
  `backend/devops/Dockerfile`, porque un flag ausente no es neutro: uvicorn cae entonces a
  la variable de entorno `FORWARDED_ALLOW_IPS` (`uvicorn/config.py:356`), que el backend
  recibe por `env_file` junto al resto del `.env`. El flag del CLI gana sobre el entorno, y
  el `command:` del compose de deploy es la única vía para ensanchar la lista.
- WHERE el entorno es el desplegado, THE SYSTEM SHALL fijar esa lista a la dirección
  estática del contenedor `frontend` en `private`, declarada **una sola vez** con un ancla
  de YAML que alimenta tanto su `ipv4_address` como el `--forwarded-allow-ips` del
  `backend`. Un valor malformado impide arrancar el contenedor y con él el deploy, en vez
  de degradar el límite en silencio — uvicorn convierte cualquier entrada inválida de esa
  lista en una comparación literal de cadena sin avisar.
- THE SYSTEM SHALL usar un **/32** y no la subred, porque la subred contiene a los demás
  servicios: medido en el deploy real, `private` alberga `postgres`, `redis`, `backend`,
  `worker`, `beat`, `migrate` y `frontend`, de los cuales **uno solo** es el proxy. Confiar
  en la subred sería autorizar a seis servicios a reportar la dirección de un cliente.
- WHERE el entorno es el local, THE SYSTEM SHALL NOT confiar en ningún peer
  (`--forwarded-allow-ips 127.0.0.1`), porque `docker-compose.yml` publica el 8000 en todas
  las interfaces a propósito y con un puerto abierto a la LAN la cabecera la suministra
  quien llama. Consecuencia aceptada: el límite por IP degrada a un contador único.
- WHEN el valor resuelto no es una dirección IP, o es **IPv6 con zone identifier**, o
  excede los 45 caracteres de `audit_logs.actor_ip`, THE SYSTEM SHALL usar `127.0.0.1`.
  Delegar en uvicorn da la selección del salto correcta pero **no** la validación: devuelve
  el primer salto no confiable literalmente. Y «parsea como IP» no basta, porque el texto
  tras `%` de un zone identifier es casi libre: medido, un zone rotatorio daba un contador
  de throttle nuevo por petición, un zone con CR/LF forjaba líneas en el log de login, y uno
  largo hacía lanzar `AuditContractError`, abortando la transacción de la operación
  auditada. Un zone identifier es ámbito link-local de una máquina y nunca describe
  legítimamente a un cliente remoto.
- THE SYSTEM SHALL canonicalizar la dirección y colapsar las formas IPv4-mapped sobre su
  IPv4, de modo que `::ffff:1.2.3.4` y `1.2.3.4`, o dos grafías del mismo IPv6, sean un
  único contador y un único `actor_ip`.

### Tope de tamaño de cuerpo

- THE SYSTEM SHALL aplicar un tope de tamaño de cuerpo a **todo** `/api/v1/`, antes de leer
  el cuerpo, respondiendo `413` con `code` `PAYLOAD_TOO_LARGE` — de modo que un cuerpo sin
  tope en un endpoint anónimo no pueda amplificar memoria por delante del throttle de login.
- El contrato completo —los cuatro techos, por qué cada número, el orden en que se resuelven,
  el mecanismo en dos pasos y el riesgo aceptado de cuerpo anónimo pre-auth— vive en
  [`specs/backend-http-posture.md`](backend-http-posture.md), que es su único hogar. Aquí no
  se reenuncia: esta sección llegó a nombrar dos techos de los cuatro que
  `app/main.py` resuelve. Regla 12(c) y reglas 6 y 14 de `steering/security.md`.

### Contrato HTTP y patrón de capas

- THE SYSTEM SHALL exponer los endpoints bajo `/api/v1/`, con `GET /health` fuera del
  prefijo (el healthcheck de los composes depende de esa ruta).
- THE SYSTEM SHALL devolver todo error con el sobre `{"error": {"code", "message",
  "details"}}` de PRD §23, incluido el `422` de validación de FastAPI, cuya forma nativa
  (`{"detail": [...]}`) rechazaría el parseador del frontend.
- THE SYSTEM SHALL organizar cada módulo en cuatro capas con la regla de dependencia
  `api/ → application/ → domain/ ← infrastructure/`, verificada por un test que recorre por
  AST cada módulo de `domain/` y `application/` — cubre alias, imports dentro de funciones,
  imports relativos que suben de paquete y `importlib`, y tiene su propio test para no poder
  pasar en vacío. Registrado como ADR 0004.
- THE SYSTEM SHALL abrir una sesión de base de datos por petición que hace `rollback` si la
  petición termina en excepción y `close` siempre, y **nunca** `commit`: la frontera
  transaccional es el caso de uso, a través del puerto `UnitOfWork`.
- Los esquemas de petición usan `extra="forbid"`, así que un campo no declarado —un
  `tenant_id` inyectado, por ejemplo— se rechaza con `422`.

### Bootstrap del acceso inicial

- El producto no tiene registro público, así que THE SYSTEM SHALL proveer un comando
  ejecutable (`python -m app.cli.bootstrap`, o `make bootstrap` en local) que crea el
  tenant inicial, su `TenantConfig` y dos usuarios (`TENANT_OWNER` y `PROPERTY_MANAGER`).
- THE SYSTEM SHALL validar las ocho variables `BOOTSTRAP_*` **antes** de abrir transacción,
  listando de golpe todas las que falten.
- El comando es **convergente**, no idempotente, y la distinción es de `object-storage-provisioning`
  (2026-08-15): repetirlo no duplica nada y tolera un cambio de caja en el email, pero **sí deja el
  estado que declara la configuración** en el único campo que actualiza.
- THE SYSTEM SHALL aplicar `BOOTSTRAP_STORAGE_TYPE` (default `LOCAL`, validado contra el enum
  `StorageType`) al crear el `TenantConfig` **y actualizarlo si difiere** en una re-ejecución. Es la
  única vía por la que ese ajuste alcanza un entorno cuyo tenant se sembró hace tiempo: create-only
  exigiría un `UPDATE` a mano, que es justo lo que la norma IaC-first no admite. El contador de
  resultados distingue lo creado de lo convergido.
- THE SYSTEM SHALL NOT abrir `storage_type` a escritura por la API: el `PATCH` de `TenantConfig`
  sigue devolviendo `422`. Cambiarlo apuntaría a ficheros ya subidos a un sitio donde no están.
- THE SYSTEM SHALL mantener `LOCAL` como default tanto de la columna como del ajuste, de modo que
  cualquier tenant creado por cualquier otra vía nazca `LOCAL`.
- IF una dirección del bootstrap ya existe bajo otro tenant, THEN THE SYSTEM SHALL abortar
  con `BootstrapConflictError` nombrando `BOOTSTRAP_TENANT_NAME`. El índice único global
  rechazaría la escritura igualmente; el aborto explícito existe para dar un mensaje
  accionable en lugar de un `IntegrityError` sobre un índice. Hace falta porque la
  idempotencia se apoya en el nombre del tenant y `tenants` no tiene unicidad en `name`:
  un typo crearía un segundo tenant y reintentaría las mismas direcciones.
- La comprobación pasa por el puerto `find_by_email_globally`, de modo que no introduce una
  consulta sin scope nueva: reutiliza una ya enumerada (§Identidad) en vez de escribir otra.
- No es una migración de datos de Alembic (mezclaría esquema con contenido y no se puede
  reejecutar con seguridad) ni está enganchado a `make up`, que sigue arrancando sin pasos
  manuales.
- El bootstrap crea **dos** cuentas y nada más. WHERE haga falta un tenant recorrible, THE SYSTEM
  SHALL completarlo con `make seed-demo`, que añade una `CLEANER` y una `TECHNICIAN` desde las seis
  variables `SEED_*` —obligatorias y sin default en el árbol, como las `BOOTSTRAP_*_PASSWORD`— y
  resuelve al owner y al manager **por rol**, no por correo, para no crear un segundo
  `TENANT_OWNER`. Esas dos cuentas nacen **operativas**, con `must_change_password` en falso: no
  pasan por `CreateUserUseCase` —que genera la contraseña y por eso marca el flag— sino por
  `User.create` y el puerto, que es lo que el default `False` de la entidad existe para permitir.
  Comportamiento completo en la spec `seed-data-demo`.
- A partir de esas cuatro cuentas, el alta de usuarios es por API (`POST /api/v1/users`, spec
  `user-management`): ni el bootstrap ni el seed son la vía normal de crear gente.

### Secretos y configuración

- THE SYSTEM SHALL leer toda su configuración vía `Settings(BaseSettings)`.
- `.env.example` declara `JWT_SECRET_KEY` **por nombre y sin valor**; los dos composes la
  exigen con `${JWT_SECRET_KEY:?...}` en `backend`, `worker` y `migrate` — los tres
  importan `settings` al arrancar, así que a los tres les falta si no está.
- WHEN se ejecuta `make up` y falta la clave en `.env`, THE SYSTEM SHALL generarla con
  `openssl rand -hex 32` bajo `umask 077` y dejar el fichero en `600`, de forma idempotente:
  el valor vive en la máquina del desarrollador y nunca en el repositorio.
- En el entorno desplegado la genera Terraform y vive en OCI Vault; el workflow de deploy la
  lee de ahí y renderiza el `.env` de la VM con permisos `600`.
- Las contraseñas del bootstrap **no** se generan ni se guardan en el `.env` que el deploy
  reescribe: las elige una persona y se pasan una sola vez por un env-file `600` que se
  borra al terminar, nunca con `-e` en la línea de comandos (acabaría en el historial del
  shell y en `/proc/<pid>/cmdline`).
- El nombre `JWT_SECRET_KEY` se aparta del `SECRET_KEY` de PRD §25 a propósito, de forma
  consistente en todo el repositorio: en esa misma sección del PRD ya convive
  `ENCRYPTION_KEY`, así que el nombre genérico no diría de qué clave se habla.

## Key files

- Dominio: `backend/app/auth/domain/` — `context.py` (`RequestContext` inmutable, con
  `preferred_language: Locale` desde `dashboard-api`),
  `policy.py` (`Permission`, `ROLE_PERMISSIONS`, `is_allowed`), `ports.py`, `entities.py`
  (`User`, `UserSession` con `is_usable`/`rotate`), `enums.py`, `value_objects.py`
  (`normalize_email`), `exceptions.py`.
- Aplicación: `backend/app/auth/application/use_cases.py` — login, refresh, logout, me.
- Infraestructura: `backend/app/auth/infrastructure/` — `password_hasher.py` (bcrypt en
  hilos con cota), `token_codec.py` (PyJWT HS256), `repositories.py`, `throttle.py`
  (Redis), `models.py` (`UserModel`, `UserSessionModel`). El `SqlAlchemyUnitOfWork` de este
  módulo se borró en `user-management`: la única copia vive en `app/core/unit_of_work.py`. El
  Protocol `UnitOfWork` sigue declarado en `app/auth/domain/ports.py` a propósito, para que
  `auth/application/` importe sus puertos de su propio `domain/`.
- API: `backend/app/auth/api/` — `router.py`, `schemas.py`, `dependencies.py`
  (`get_authenticated_request`, `require(permission)`, `get_client_ip`).
- Núcleo compartido: `backend/app/core/` — `config.py`, `db.py` (filtro global por tenant),
  `errors.py` (sobre de error), `redis.py`, `models_registry.py`.
- Bootstrap: `backend/app/cli/bootstrap.py`. El seed que lo completa vive en
  `backend/app/cli/seed_demo.py` y es capacidad aparte (`specs/seed-data-demo.md`).
- Migraciones: `backend/alembic/versions/8ff62a7cb50c_auth_sessions.py`,
  `e1eed2e039ee_globally_unique_lower_email.py`.
- Tests: `backend/tests/auth/`, `backend/tests/test_layering.py`,
  `test_route_authorization.py`, `test_tenant_filter.py`, `test_migrations.py`,
  `test_models_registry.py`.
- Documentación: `docs/auth-tenancy.md` (operación), `docs/adr/0004-backend-layering-pattern.md`,
  `docs/adr/0005-global-email-uniqueness.md`, `infra/environments/dev/RUNBOOK.md` §6.4-6.5.
