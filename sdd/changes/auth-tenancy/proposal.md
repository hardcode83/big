# Proposal: auth-tenancy

## Why

El backend tiene hoy dominio puro y esquema de base de datos —`domain-foundation-core`,
`domain-foundation-ops` y el `PropertyStateMachine` de `timeline-state-machine`— pero
**ninguna superficie HTTP**: `backend/app/main.py` expone solo `/health` y no existe
todavía ninguna capa `application/` ni `api/` en el proyecto. Nada de lo construido es
alcanzable por un cliente.

Este change abre esa superficie por donde manda PRD §26.4-5: autenticación JWT, RBAC y
aislamiento por tenant. Se elige como primer *vertical slice* porque `POST /auth/login`
es la rodaja completa más pequeña que atraviesa las cuatro capas de
`steering/backend-architecture.md`, y porque cualquier endpoint de negocio necesita
antes un tenant autenticado al que scoparse: sin auth no hay forma legítima de probar
la fontanería. El patrón que quede aquí (inyección de dependencias, sesión por request,
sobre de error, mapeo entidad↔Pydantic) es el que heredan `reservations`, `cleaning`,
`dashboard-web` y el resto de módulos, así que se documenta explícitamente como
referencia.

Fuente funcional: PRD §26.4-5 (orden de desarrollo), §6 (roles RBAC), §22 (auditoría y
seguridad), §23 (convenciones REST).

## What changes

Después de este change el backend expondrá `POST /api/v1/auth/login`,
`POST /api/v1/auth/refresh`, `POST /api/v1/auth/logout` y `GET /api/v1/auth/me` sobre
el prefijo versionado y el sobre de error de PRD §23, con contraseñas verificadas
contra hash bcrypt, tokens de acceso de 15 minutos y refresh de 7 días con rotación y
detección de reuso. Toda request autenticada llevará un contexto de request con
`user_id`, `tenant_id` y `role` derivado **exclusivamente del token**, y existirá una
dependencia de autorización por rol que cada endpoint debe declarar, de forma que un
endpoint sin declaración explícita quede inaccesible. Los endpoints de auth quedarán
protegidos con límite de 10 intentos por minuto y IP y bloqueo temporal de la cuenta
tras 10 fallos consecutivos. Habrá un comando de bootstrap idempotente para crear el
tenant y los usuarios iniciales, porque el producto no tiene registro público. Y
quedarán establecidas, por primera vez, las capas `application/`, `api/` y el
repositorio SQLAlchemy de `User`, con una sesión de base de datos por request.

## Requirements

### R1 — Autenticación con credenciales

**As a** usuaria del sistema (propietaria, manager, limpiadora o técnico), **I want**
identificarme con mi email y mi contraseña, **so that** pueda acceder a los datos de mi
vivienda desde el móvil sin exponerlos a nadie más.

Acceptance criteria:

1. WHEN se envía a `POST /api/v1/auth/login` un email y una contraseña que corresponden
   a un usuario con `status = ACTIVE`, THE SYSTEM SHALL responder `200` con un token de
   acceso, un token de refresh y el tipo de token.
2. WHEN un login tiene éxito, THE SYSTEM SHALL actualizar `last_login_at` del usuario
   con el instante de la autenticación en UTC.
3. THE SYSTEM SHALL verificar la contraseña contra el hash bcrypt almacenado en
   `User.password_hash` y no almacenar, registrar ni devolver nunca la contraseña en
   claro ni ninguna forma reversible de ella.
4. IF el email no existe, la contraseña no coincide, o el usuario tiene
   `status = INACTIVE` o `status = SUSPENDED`, THEN THE SYSTEM SHALL responder `401`
   con un cuerpo indistinguible entre esos casos
   (`{"error": {"code": "INVALID_CREDENTIALS", ...}}`), sin revelar si el email existe
   ni cuál es el estado de la cuenta. `ASSUMPTION`: el PRD no especifica la respuesta a
   cuenta inactiva; se unifica con credencial inválida para no permitir enumeración de
   usuarios.
5. WHEN se emite un token de acceso, THE SYSTEM SHALL incluir en él el identificador de
   usuario, el `tenant_id`, el rol, el instante de emisión, el de expiración, un
   identificador único de token y el tipo de token (acceso o refresh).
6. THE SYSTEM SHALL fijar la vida del token de acceso en 15 minutos y la del de refresh
   en 7 días, ambas configurables por entorno.
7. IF la clave de firma JWT no está configurada al arrancar, THEN THE SYSTEM SHALL
   fallar el arranque en vez de servir con una clave por defecto.

### R2 — Renovación con rotación y cierre de sesión

**As a** usuaria en el móvil, **I want** seguir dentro de la aplicación sin reintroducir
la contraseña cada 15 minutos, **so that** operar no sea una molestia, pero que un token
robado deje de servir en cuanto se use.

Acceptance criteria:

1. WHEN se presenta a `POST /api/v1/auth/refresh` un token de refresh válido, vigente y
   no usado todavía, THE SYSTEM SHALL responder `200` con un par de tokens nuevo e
   invalidar el token presentado.
2. IF se presenta un token de refresh que ya había sido usado o invalidado, THEN THE
   SYSTEM SHALL responder `401` e invalidar además todos los tokens de refresh
   descendientes de la misma sesión. `ASSUMPTION`: el PRD pide *rotation* sin definir la
   respuesta al reuso; se adopta la invalidación de la familia completa, que es el
   comportamiento estándar para tratar el reuso como indicio de robo.
3. WHEN se invoca `POST /api/v1/auth/logout` con una sesión válida, THE SYSTEM SHALL
   invalidar el token de refresh de esa sesión y responder `204`.
4. THE SYSTEM SHALL dejar que los tokens de acceso ya emitidos caduquen por su propia
   expiración —como máximo 15 minutos— sin mantener una lista de revocación de tokens
   de acceso.
5. IF un token está expirado, mal firmado, malformado, o es de un tipo distinto al que
   el endpoint espera (un refresh usado como acceso o al revés), THEN THE SYSTEM SHALL
   responder `401` sin ejecutar la operación.
6. WHEN se invoca `GET /api/v1/auth/me` con un token de acceso válido, THE SYSTEM SHALL
   devolver el identificador, nombre, email, rol, idioma preferido y `tenant_id` del
   usuario del token, y nunca su `password_hash`.

### R3 — Autorización por rol, denegando por defecto

**As a** propietaria, **I want** que cada persona pueda hacer exactamente lo que le
corresponde por su rol, **so that** una limpiadora no vea mis ingresos ni un técnico
gestione reservas.

Acceptance criteria:

1. THE SYSTEM SHALL reconocer los cinco roles ya definidos en `UserRole`
   (`SUPER_ADMIN`, `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN`) con los
   permisos de PRD §6.
2. THE SYSTEM SHALL exigir que todo endpoint declare explícitamente su requisito de
   autorización mediante una dependencia de FastAPI, y un test SHALL recorrer todas las
   rutas registradas para demostrar que ninguna queda sin declararlo.
3. WHERE una ruta está en la lista explícita de rutas anónimas (`/health`,
   `POST /api/v1/auth/login`, `POST /api/v1/auth/refresh`, y la documentación OpenAPI),
   THE SYSTEM SHALL permitir el acceso sin token; para cualquier otra ruta, la ausencia
   de una declaración de autorización SHALL ser un fallo de test, no un acceso libre.
4. WHEN un usuario autenticado invoca un endpoint que su rol no permite, THEN THE SYSTEM
   SHALL responder `403` con `{"error": {"code": "FORBIDDEN", ...}}` y no ejecutar la
   operación.
5. WHEN se invoca un endpoint protegido sin cabecera `Authorization` o con un esquema
   distinto de `Bearer`, THEN THE SYSTEM SHALL responder `401`.
6. THE SYSTEM SHALL aplicar el RBAC en el backend, de modo que la comprobación no
   dependa de ninguna decisión del frontend.

### R4 — Aislamiento por tenant, sin excepciones

**As a** propietaria, **I want** que mis datos sean inalcanzables desde la cuenta de
otro cliente, **so that** el sistema pueda venderse como SaaS multi-tenant sin
rediseñar la seguridad.

Acceptance criteria:

1. WHEN se atiende cualquier request autenticada, THE SYSTEM SHALL derivar el
   `tenant_id` efectivo únicamente del token e ignorar cualquier `tenant_id` presente en
   el cuerpo, la query string, la ruta o las cabeceras de la request.
2. THE SYSTEM SHALL scopar toda lectura y toda escritura al `tenant_id` efectivo, sin
   ninguna ruta de código que consulte una entidad con `tenant_id` sin filtrarlo,
   incluido el rol `SUPER_ADMIN`.
3. IF un usuario referencia un recurso que existe pero pertenece a otro tenant, THEN
   THE SYSTEM SHALL responder `404` y no `403`, para no revelar la existencia del
   recurso. `ASSUMPTION`: el PRD no especifica el código; se elige `404` por
   consistencia con no filtrar información entre tenants.
4. THE SYSTEM SHALL incluir tests automáticos que, para cada uno de los cinco roles,
   demuestren que un usuario del tenant A no obtiene datos del tenant B ni puede
   modificarlos.
5. IF un token válido nombra un tenant que no existe o que no está `ACTIVE`, THEN THE
   SYSTEM SHALL rechazar la request con `401`.

### R5 — Protección de los endpoints de autenticación

**As a** propietaria, **I want** que nadie pueda probar contraseñas por fuerza bruta
contra las cuentas, **so that** el acceso a mis viviendas no dependa de la suerte de un
atacante.

Acceptance criteria:

1. WHILE una misma dirección IP ha realizado 10 o más intentos de login en el último
   minuto, THE SYSTEM SHALL responder `429` con
   `{"error": {"code": "RATE_LIMITED", ...}}` sin comprobar las credenciales.
2. WHEN una cuenta acumula 10 intentos de login fallidos consecutivos, THE SYSTEM SHALL
   bloquear los siguientes intentos sobre esa cuenta durante un periodo configurable
   (default 15 minutos) y responder con el mismo `401` genérico de R1.4.
   `ASSUMPTION`: PRD §22 pide "bloqueo tras 10 intentos fallidos" sin decir cómo se
   libera; se elige bloqueo temporal configurable en lugar de permanente, para no
   necesitar intervención manual ni un endpoint de desbloqueo que aún no existe.
3. WHEN un login tiene éxito, THE SYSTEM SHALL poner a cero el contador de fallos
   consecutivos de esa cuenta.
4. THE SYSTEM SHALL contar los intentos en un almacén compartido entre procesos, de
   forma que el límite se respete con varios workers de la aplicación en marcha.
5. THE SYSTEM SHALL registrar cada intento fallido y cada bloqueo en el log de la
   aplicación, en inglés, sin incluir la contraseña presentada.

### R6 — Contrato HTTP y patrón de capas de referencia

**As a** desarrollador de los módulos siguientes (reservas, limpieza, dashboard),
**I want** encontrar ya resueltos el contrato HTTP y el cableado de capas, **so that**
cada módulo nuevo se limite a su lógica de negocio en vez de reinventar la fontanería.

Acceptance criteria:

1. THE SYSTEM SHALL servir todos los endpoints de negocio bajo el prefijo `/api/v1/`,
   con fechas en ISO 8601 en UTC.
2. WHEN una request falla por cualquier causa gestionada (validación, autenticación,
   autorización, recurso inexistente, límite de intentos), THE SYSTEM SHALL responder
   con el sobre `{"error": {"code": ..., "message": ..., "details": {...}}}` de PRD §23,
   con `code` estable y `message` en inglés.
3. THE SYSTEM SHALL abrir una sesión de base de datos por request y cerrarla siempre,
   también cuando la request termina en excepción, sin dejar transacciones abiertas
   entre requests.
4. THE SYSTEM SHALL mantener la regla de dependencia de
   `steering/backend-architecture.md`: ningún módulo bajo `<dominio>/domain/` importa
   `fastapi`, `sqlalchemy` ni `pydantic`, verificado por un test.
5. THE SYSTEM SHALL definir el puerto de repositorio de `User` en `domain/` en términos
   de la entidad de dominio, y su implementación SQLAlchemy en `infrastructure/`, de
   modo que los casos de uso no conozcan el modelo ORM.
6. THE SYSTEM SHALL exponer el esquema OpenAPI con la seguridad Bearer declarada, de
   forma que los endpoints protegidos se puedan ejercitar desde la documentación
   generada.
7. THE SYSTEM SHALL declarar `JWT_SECRET_KEY` en `.env.example` y en el
   `docker-compose.yml` local con la misma semántica de fallo rápido que ya tiene el
   compose de deploy, sin ningún valor real en el repositorio.

### R7 — Bootstrap del acceso inicial

**As a** operador del entorno, **I want** un comando que cree el tenant y los usuarios
iniciales, **so that** haya forma de entrar en un despliegue recién levantado, dado que
el producto no tiene registro público.

Acceptance criteria:

1. WHEN se ejecuta el comando de bootstrap, THE SYSTEM SHALL crear el tenant inicial y
   sus usuarios con los roles indicados, tomando emails y contraseñas de variables de
   entorno.
2. WHEN el comando se ejecuta de nuevo sobre una base de datos ya inicializada, THE
   SYSTEM SHALL terminar con éxito sin duplicar ni modificar nada.
3. IF falta alguna de las variables de entorno requeridas, THEN THE SYSTEM SHALL
   terminar con error antes de escribir nada en la base de datos.
4. THE SYSTEM SHALL almacenar las contraseñas del bootstrap como hash bcrypt y no
   contener ninguna contraseña por defecto embebida en el repositorio.

## Out of scope

- **CRUD de usuarios y asignación de roles** (`/api/v1/users` de PRD §23) y su
  `AuditLog` de cambios de rol (regla 9 de `steering/security.md`), junto con los
  endpoints de `tenants`: van al change **`user-management`**, ya registrado en
  `sdd/roadmap.md` justo detrás de este. Aquí los usuarios entran por el bootstrap de R7.
- **Acceso del huésped**: PRD §6 le da token seguro de un solo uso y ningún panel, y
  `UserRole` no incluye `GUEST` — no es un `User`. Va al change **`guest-portal`**, ya
  registrado en `sdd/roadmap.md` detrás de `access-notifications`.
- **Login del frontend**: pantalla, almacenamiento del token, refresh en cliente y
  guardas de ruta van en `dashboard-web` (PRD §26.16), que es donde el roadmap sitúa la
  auth de FE.
- **Visibilidad cross-tenant de `SUPER_ADMIN`** e impersonation auditada (PRD §6): se
  descarta en este change por decisión explícita, para que la regla 1 de
  `steering/security.md` quede absoluta y verificable. Va al change
  **`saas-cross-tenant`**, registrado en `sdd/roadmap.md` como post-MVP condicional —
  reabrirlo exige rediseñar el scoping y documentar una excepción en el steering, no es
  aditivo.
- **Endpoints de negocio** (properties, reservations, cleaning…): llegan con sus
  módulos.
- **Recuperación de contraseña y cambio de contraseña**: van al change
  **`auth-account-recovery`**, registrado en `sdd/roadmap.md` como *opcional MVP* (así lo
  marca PRD §24) detrás de `access-notifications`, porque requieren
  `NotificationAdapter`. El 2FA no está en el PRD y no se registra.
- **Cifrado Fernet de campos sensibles** (regla 3): este change no toca `wifi_password`,
  `document_number` ni códigos de acceso.
- **Rotación de la clave de firma JWT** y `AuditLog` de eventos de login: el `AuditLog`
  como entidad llega en `domain-foundation-financial`.

## Affected specs

- `sdd/specs/auth-tenancy.md` — *(no existe aún — se creará al archivar)*: auth JWT,
  RBAC, aislamiento por tenant y el contrato HTTP/patrón de capas de referencia.
- `sdd/specs/local-environment.md` — actualización: `JWT_SECRET_KEY` en `.env.example`
  y en el `docker-compose.yml` local, y el comando de bootstrap en el arranque local.
- `sdd/specs/domain-foundation-core.md` — actualización: `User` y `Tenant` pasan de ser
  solo esquema a tener repositorio y ciclo de vida de autenticación.
