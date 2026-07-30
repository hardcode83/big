# Autenticación, autorización y tenencia

## Purpose

Esta capacidad autentica a los usuarios del producto con email y contraseña, emite y
renueva tokens JWT, decide qué puede hacer cada rol y garantiza que los datos de un
tenant sean inalcanzables desde la cuenta de otro. Es también el primer *vertical slice*
del backend: establece el patrón de capas (`api/` → `application/` → `domain/` ←
`infrastructure/`, ADR 0004) que heredan los módulos posteriores.

No incluye alta ni administración de usuarios —los usuarios entran por el comando de
bootstrap— ni recuperación de contraseña ni acceso de huéspedes.

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
- Es una desviación deliberada de PRD §7.3, que define `UNIQUE(tenant_id, email)`, y la
  única consulta sin scope de tenant del sistema (`find_by_email_globally`) depende de
  ella: con unicidad por tenant, el email no identificaría la cuenta y quien pudiera
  crear usuarios en otro tenant dejaría fuera del producto a una cuenta existente. Motivo
  completo y alternativas descartadas en ADR 0005.
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
  `revoked_at` nulo. El enum `SessionRevokedReason` solo tiene `LOGOUT` y
  `REUSE_DETECTED`.

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
  de rol a permisos en `app/auth/domain/policy.py`, con solo los permisos que esta
  capacidad usa.
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
- THE SYSTEM SHALL pasar el `tenant_id` efectivo como parámetro explícito a cada método de
  repositorio, que filtra por él. Es el mecanismo autorizado.
- THE SYSTEM SHALL aplicar además, como red de seguridad, un filtro global por tenant en el
  evento `do_orm_execute` de SQLAlchemy, activo **solo** en sesiones marcadas con el tenant
  de la petición. Tiene cinco límites documentados en `app/core/db.py` y por eso no
  sustituye al parámetro explícito: cubre solo SELECT/UPDATE/DELETE del ORM; no actúa en
  sesiones sin marcar (tareas Celery, bootstrap, el login anónimo —que lo necesita—, y
  `POST /auth/refresh`); no protege INSERTs; no cubre el mapa de identidad; y no alcanza
  las tablas hijas sin `tenant_id` propio (`messages`, `cleaning_checklist_completions`,
  `cleaning_photos`), que deben unirse a su padre scopado y traer su propio test.
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
  `login`, `refresh`, `logout` y `me` son autorreferenciales—, así que no son verificables
  aquí sin inventar un endpoint de negocio. Son criterios de aceptación bloqueantes de
  `user-management`, la primera capacidad con endpoints que reciben identificadores
  tenant-scoped.

### Protección de los endpoints de autenticación

- WHILE una misma dirección IP ha realizado 10 o más intentos de login en el último minuto,
  THE SYSTEM SHALL responder `429` con `{"error": {"code": "RATE_LIMITED", ...}}` sin
  comprobar las credenciales.
- WHEN una cuenta acumula 10 intentos fallidos consecutivos, THE SYSTEM SHALL bloquear los
  siguientes intentos sobre esa cuenta durante 15 minutos (configurable) respondiendo el
  mismo `401` genérico.
- IF un intento se rechaza **por** el bloqueo, THEN THE SYSTEM SHALL NOT contarlo como
  fallo: contar un intento que nunca se evaluó empujaría el bloqueo hacia delante en cada
  prueba y dejaría de estar acotado a 15 minutos.
- WHEN un login tiene éxito, THE SYSTEM SHALL poner a cero el contador de fallos de esa
  cuenta.
- THE SYSTEM SHALL mantener los contadores en Redis, el único almacén compartido entre los
  procesos `backend` y `worker`, de forma que el límite se respete con varios workers.
- THE SYSTEM SHALL (re)aplicar la expiración de cada contador en **todos** los intentos
  (`EXPIRE ... NX`), no solo cuando el contador se crea: `INCR` y `EXPIRE` son dos viajes,
  y si el segundo no llega a ejecutarse la clave se queda sin TTL y esa IP queda bloqueada
  para siempre en lugar de un minuto.
- La ventana es fija, no deslizante: en el límite entre dos minutos una IP puede hacer
  hasta el doble del límite seguidas. El bloqueo por cuenta cubre exactamente esa ráfaga.
- THE SYSTEM SHALL registrar cada intento fallido y cada bloqueo en el log de la
  aplicación, en inglés y sin la contraseña presentada.

### Identificación del cliente

- THE SYSTEM SHALL usar la IP del peer del socket como identidad del cliente, y honrar una
  cabecera de proxy **solo** si `TRUSTED_CLIENT_IP_HEADER` la nombra explícitamente. Viene
  vacía por defecto.
- WHERE esa cabecera está configurada, THE SYSTEM SHALL tomar el salto de **más a la
  derecha** de su **última** aparición y validarlo con `ipaddress.ip_address`, cayendo a la
  IP del socket si no parsea. El primer salto es el valor que envió el cliente cuando el
  proxy **añade** (comportamiento de nginx y de cualquier implementación conforme), así que
  leerlo sería leer entrada del atacante.
- **Limitación conocida**: el código honra la cabecera venga de donde venga, sin comprobar
  que el peer sea un proxy de confianza. Esa comprobación pertenece a
  `api-ingress-routing`, que es donde el proxy existe de verdad. Mientras no exista, activar
  la cabecera con la API alcanzable por otra vía permitiría a quien llegue por ahí darse un
  presupuesto nuevo de 10/min en cada petición.

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
- El comando es idempotente: repetirlo no duplica ni modifica nada, y tolera un cambio de
  caja en el email.
- IF una dirección del bootstrap ya existe bajo otro tenant, THEN THE SYSTEM SHALL abortar
  con `BootstrapConflictError` nombrando `BOOTSTRAP_TENANT_NAME`. El índice único global
  rechazaría la escritura igualmente; el aborto explícito existe para dar un mensaje
  accionable en lugar de un `IntegrityError` sobre un índice. Hace falta porque la
  idempotencia se apoya en el nombre del tenant y `tenants` no tiene unicidad en `name`:
  un typo crearía un segundo tenant y reintentaría las mismas direcciones.
- La comprobación pasa por el puerto `find_by_email_globally`, de modo que sigue siendo la
  única consulta sin scope del sistema y la auditoría por `grep` sigue siendo exhaustiva.
- No es una migración de datos de Alembic (mezclaría esquema con contenido y no se puede
  reejecutar con seguridad) ni está enganchado a `make up`, que sigue arrancando sin pasos
  manuales.

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

- Dominio: `backend/app/auth/domain/` — `context.py` (`RequestContext` inmutable),
  `policy.py` (`Permission`, `ROLE_PERMISSIONS`, `is_allowed`), `ports.py`, `entities.py`
  (`User`, `UserSession` con `is_usable`/`rotate`), `enums.py`, `value_objects.py`
  (`normalize_email`), `exceptions.py`.
- Aplicación: `backend/app/auth/application/use_cases.py` — login, refresh, logout, me.
- Infraestructura: `backend/app/auth/infrastructure/` — `password_hasher.py` (bcrypt en
  hilos con cota), `token_codec.py` (PyJWT HS256), `repositories.py`, `throttle.py`
  (Redis), `models.py` (`UserModel`, `UserSessionModel`), `unit_of_work.py`.
- API: `backend/app/auth/api/` — `router.py`, `schemas.py`, `dependencies.py`
  (`get_authenticated_request`, `require(permission)`, `get_client_ip`).
- Núcleo compartido: `backend/app/core/` — `config.py`, `db.py` (filtro global por tenant),
  `errors.py` (sobre de error), `redis.py`, `models_registry.py`.
- Bootstrap: `backend/app/cli/bootstrap.py`.
- Migraciones: `backend/alembic/versions/8ff62a7cb50c_auth_sessions.py`,
  `e1eed2e039ee_globally_unique_lower_email.py`.
- Tests: `backend/tests/auth/`, `backend/tests/test_layering.py`,
  `test_route_authorization.py`, `test_tenant_filter.py`, `test_migrations.py`,
  `test_models_registry.py`.
- Documentación: `docs/auth-tenancy.md` (operación), `docs/adr/0004-backend-layering-pattern.md`,
  `docs/adr/0005-global-email-uniqueness.md`, `infra/environments/dev/RUNBOOK.md` §6.4-6.5.
