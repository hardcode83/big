# Tasks: user-management

Nada de este change está implementado todavía: no existen `app/auth/api/users_router.py`,
`app/auth/application/user_admin.py`, `app/tenants/application/`, `app/tenants/api/`,
`app/audit/domain/repositories.py` ni sus tests. Ninguna tarea nace marcada.

Orden pensado para que el sistema quede funcionando al final de cada sección: las secciones
1-2 son aditivas y no cambian comportamiento; los endpoints no se registran hasta la 6 y
la 8, así que hasta entonces la superficie HTTP es la de hoy.

`domain/` con invariante real se escribe **test primero** (`steering/testing.md`): secciones
1, 3 y 7. En `infrastructure/` no se fuerza TDD.

## 1. Cimientos de auditoría (`app/audit/`) <!-- panel: PASS 2026-07-31 (2 rondas de corrección: 6 hallazgos de seguridad y QA) -->

- [x] 1.1 Test primero de `ChangeSet`: `diff` produce `{campo: {"old", "new"}}` (la forma de
      PRD §7.25, no `from`/`to`), `redacted`
      produce `{campo: {"changed": true}}`, `diff` **levanta error de dominio** para cada
      campo de la lista de denegación (`password`, `password_hash`, `document_number`,
      `wifi_password`, `access_code`), y un valor no serializable a JSONB se rechaza nombrando
      la clave ofensiva — `tests/audit/test_change_set.py` [R6.1, R6.2, D3]
- [x] 1.2 Implementar `ChangeSet` inmutable con solo esos dos constructores —
      `app/audit/domain/value_objects.py` [R6.1, R6.2, D3]
- [x] 1.3 Vocabulario cerrado de `action` y `entity_type` como constantes de dominio
      (`USER`, `TENANT`, `TENANT_CONFIG`; `USER_CREATED`, `USER_UPDATED`,
      `USER_ROLE_CHANGED`, `USER_DEACTIVATED`, `USER_PASSWORD_RESET`, `TENANT_UPDATED`,
      `TENANT_CONFIG_UPDATED`) — `app/audit/domain/actions.py` [R6.5, D4]
- [x] 1.4 Fábrica de dominio que es la única forma de construir un `AuditLog`, tomando
      `ChangeSet`, actor y `actor_ip`, con su test — `app/audit/domain/services.py`,
      `tests/audit/test_factory.py` [R6.3, R6.5, D2]
- [x] 1.5 Puerto `AuditLogRepository.add(tenant_id, entry)` — `app/audit/domain/repositories.py`
      [R6.4, D2]
- [x] 1.6 Adaptador SQLAlchemy sin `commit` (la transacción es del caso de uso), rechazando
      una entrada de otro tenant con `CrossTenantWriteError`, con test de integración —
      `app/audit/infrastructure/repositories.py`, `tests/audit/test_repositories.py`
      [R6.4, R7.8, D2]
- [x] 1.7 Test de que `audit_logs` no es alcanzable para editar ni borrar: ninguna ruta
      registrada acepta `PUT`/`PATCH`/`DELETE` sobre esa entidad y el puerto no expone más
      que `add` — `tests/audit/test_immutability.py` [R6.6]

## 2. Sesiones revocables por usuario, y consolidación del UnitOfWork <!-- panel: PASS 2026-07-31 (revisado con §3-6) -->

- [x] 2.1 Añadir `USER_DEACTIVATED` y `PASSWORD_RESET` a `SessionRevokedReason` —
      `app/auth/domain/enums.py` [R3.7, R4.2, D7, D18]
- [x] 2.2 Migración Alembic con `down_revision = '96d526599bc1'`: dos `ALTER TYPE
      session_revoked_reason ADD VALUE`, sin escribir filas que los usen (Postgres no permite
      usar un valor nuevo en la misma transacción que lo añade), y `downgrade` documentado
      como irreversible en el propio fichero — `alembic/versions/<rev>_session_revoked_reason_admin.py`
      [R3.7, D7]
- [x] 2.3 Verificar la migración de las tres formas que ejecuta CI: `alembic upgrade head`,
      `alembic check` y `alembic downgrade base` sobre una base limpia [R3.7]
- [x] 2.4 `SessionRepository.revoke_all_for_user(tenant_id, user_id, reason, now)` en el
      puerto y su adaptador — una sola sentencia sobre todas las familias no revocadas del
      usuario — `app/auth/domain/ports.py`,
      `app/auth/infrastructure/repositories.py` [R3.7, R4.2, D7]
- [x] 2.5 Test de integración: revocar por usuario alcanza **varias** familias, no toca las de
      otro usuario ni las de otro tenant, y es idempotente —
      `tests/auth/test_repositories.py` [R3.7, R4.2, R7.8]
- [x] 2.6 Borrar `app/auth/infrastructure/unit_of_work.py` y apuntar
      `app/auth/api/dependencies.py` a `app/core/unit_of_work.py`; el Protocol de
      `app/auth/domain/ports.py` se queda. La suite de auth debe seguir verde sin cambios de
      comportamiento [D16]

## 3. Dominio de usuario: invariantes, permisos y contraseña temporal <!-- panel: PASS 2026-07-31 (revisado con §2-6) -->

- [x] 3.1 Test primero de la autoprotección: `change_role` y `change_status` levantan error de
      dominio cuando el actor es el propio usuario, y lo permiten cuando no —
      `tests/auth/test_entities.py` [R3.5, D5, D19]
- [x] 3.2 `User` gana `update_profile`, `change_role`, `change_status` y `set_password_hash`;
      `role` y `status` dejan de ser asignables desde fuera — `app/auth/domain/entities.py`
      [R3.1, R3.5, D5]
- [x] 3.3 Test primero de la regla del último propietario: rechaza el cambio de rol o de
      estado que dejaría el tenant sin ningún `TENANT_OWNER` activo, y lo permite cuando queda
      otro — `tests/auth/test_services.py` [R3.6, D6]
- [x] 3.4 Regla pura del último propietario, recibiendo el recuento como argumento (sin base
      de datos) — `app/auth/domain/services.py` [R3.6, D6]
- [x] 3.5 Test primero del rechazo de `SUPER_ADMIN` como rol asignable, tanto al crear como al
      cambiar de rol — `tests/auth/test_entities.py` [R1.6, D20 (alcance), R3.1]
- [x] 3.6 Excepciones de dominio nuevas: `UserNotFoundError`, `EmailAlreadyExistsError`,
      `SelfRoleChangeError`, `LastOwnerError`, `UnassignableRoleError` —
      `app/auth/domain/exceptions.py` [R1.4, R1.6, R3.5, R3.6]
- [x] 3.7 Generador de contraseña temporal: 16 caracteres, alfabeto sin `0`/`O` ni `1`/`l`/`I`,
      `secrets` (nada de `random`), por debajo del límite de 72 bytes de bcrypt; test de
      forma, de alfabeto y de que dos llamadas no coinciden — `app/auth/domain/passwords.py`,
      `tests/auth/test_passwords.py` [R1.2, R4.1, D9, D20]
- [x] 3.8 Cuatro permisos nuevos (`READ_USERS`, `MANAGE_USERS`, `READ_TENANT_SETTINGS`,
      `MANAGE_TENANT_SETTINGS`), con `MANAGE_*` incluyendo su `READ_*`, y el mapa por rol:
      `TENANT_OWNER` los cuatro, `PROPERTY_MANAGER` los dos de lectura, el resto ninguno —
      `app/auth/domain/policy.py` [R7.4, R7.5, R7.6, R7.7, D8]
- [x] 3.9 Ampliar el test del catálogo de política con los cuatro permisos y los cinco roles,
      escrito a mano y no derivado de `ROLE_PERMISSIONS` — `tests/auth/test_policy.py`
      [R7.4, R7.5, R7.6, R7.7]

## 4. Puerto y adaptador de usuarios <!-- panel: PASS 2026-07-31 (revisado con §2-6) -->

- [x] 4.1 Ampliar el puerto `UserRepository` con `get`, `list`, `add`, `apply_changes`,
      `count_active_owners_excluding` y `lock_tenant_for_admin`, todos con `tenant_id`
      explícito. **`apply_changes`, no `save`** (design D21): `auth-tenancy` borró
      `UserRepository.save` a propósito y dejó un guard de regresión que lo prohíbe, porque
      copiar la fila entera puede revertir una suspensión concurrente —
      `app/auth/domain/ports.py` [R2.1, R2.6, R3.1, R7.8, D21]
- [x] 4.2 `Page` y filtros del listado (rol, estado) en el dominio, con la cota de
      `per_page` a 100 y `page` a 100.000 — `app/auth/domain/repositories.py` o
      `ports.py` según encaje [R2.1, R2.2, R2.4]
- [x] 4.3 Adaptador: `get` y `list` filtrando por `tenant_id`, orden `name` ascendente con
      `id` de desempate, y `total` para el envelope — `app/auth/infrastructure/repositories.py`
      [R2.1, R2.3, R2.6, D17]
- [x] 4.4 Adaptador: `add` traduciendo el `IntegrityError` de `uq_users_lower_email` a
      `EmailAlreadyExistsError` **comprobando el nombre del constraint** y re-lanzando
      cualquier otro; `apply_changes` escribiendo **solo las columnas que cambiaron** y nunca
      `tenant_id`, `id` ni `last_login_at` —
      `app/auth/infrastructure/repositories.py` [R1.4, R1.5, R3.2, D11, D21]
- [x] 4.5 Adaptador: `count_active_owners_excluding` y `lock_tenant_for_admin` con
      `SELECT … FROM tenants WHERE id = :t FOR UPDATE` —
      `app/auth/infrastructure/repositories.py` [R3.6, D6]
- [x] 4.6 Tests de integración del adaptador: paginación estable (paginar no repite ni omite),
      filtros, `409` por duplicado con distinta caja, `save` que no puede mover una fila de
      tenant, recuento de propietarios activos —
      `tests/auth/test_repositories.py` [R1.4, R2.1, R2.2, R2.3, R2.4, R3.6, R7.8]
- [x] 4.7 **Reencuadrada al implementar**: la entidad `User` lleva `password_hash` a
      propósito (el login lo necesita), así que "el adaptador no lo expone" no es
      verificable ni cierto en esta capa. La frontera real de R2.5 es el esquema de
      respuesta, y se verifica en 6.1 (tipos de respuesta que no lo declaran) y 6.11
      (ninguna respuesta lo contiene). Aquí no se escribe un test vacuo [R2.5]

## 5. Casos de uso de administración de usuarios <!-- panel: PASS 2026-07-31 (revisado con §2-6) -->

- [x] 5.1 `CreateUserUseCase`: genera la temporal, hashea con el puerto `PasswordHasher`
      (en hilos, ya existente), inserta, escribe el `AuditLog` `USER_CREATED` **después** del
      `flush` del usuario para que un `409` no deje rastro de una creación que no ocurrió, y
      hace un solo `commit` — `app/auth/application/user_admin.py` [R1.1, R1.2, R1.3, R6.2, R6.4]
- [x] 5.2 `ListUsersUseCase` y `GetUserUseCase`, devolviendo `404` (`UserNotFoundError`) para
      un `id` inexistente o de otro tenant — `app/auth/application/user_admin.py`
      [R2.1, R2.6, R7.1]
- [x] 5.3 `UpdateUserUseCase`: aplica solo los campos presentes, normaliza el email y traduce
      su duplicado a `409`, toma el lock del tenant cuando el cambio afecta a la población de
      propietarios, y elige la acción de auditoría (`USER_ROLE_CHANGED` si el rol cambia,
      `USER_UPDATED` si no) — `app/auth/application/user_admin.py`
      [R3.1, R3.3, R3.4, R3.5, R3.6, D4]
- [x] 5.4 Un `PATCH` que no cambia nada —cuerpo vacío o valores idénticos— no escribe fila ni
      `AuditLog` [D15]
- [x] 5.5 `DeactivateUserUseCase` (el `DELETE`): pasa a `INACTIVE` conservando la fila, revoca
      todas las sesiones del usuario con `USER_DEACTIVATED`, audita `USER_DEACTIVATED`, es
      idempotente sobre un usuario ya `INACTIVE` (sin segundo `AuditLog`), y rechaza la
      autobaja — `app/auth/application/user_admin.py` [R3.7, R3.8, R3.9, D19]
- [x] 5.6 `ResetUserPasswordUseCase`: nueva temporal con las garantías de 3.7, reemplaza el
      hash, revoca todas las sesiones del usuario con `PASSWORD_RESET`, y audita
      `USER_PASSWORD_RESET` con `{"password": {"changed": true}}` — nunca la contraseña ni el
      hash — `app/auth/application/user_admin.py` [R4.1, R4.2, R4.3, R6.2]
- [x] 5.7 Tests de los seis casos de uso con **fakes en memoria** de los puertos (no la DB,
      no mocks de SQLAlchemy), incluyendo que cada mutación escribe exactamente un `AuditLog`
      y que un fallo al escribirlo deja el usuario sin cambiar —
      `tests/auth/test_user_admin_use_cases.py`, `tests/auth/doubles.py` [R6.4, R1, R2, R3, R4]
- [x] 5.8 Test de concurrencia de la invariante del último propietario: dos degradaciones
      simultáneas de dos propietarios distintos dejan uno en pie (con el lock tomado de
      verdad, contra Postgres) — `tests/auth/test_last_owner_concurrency.py` [R3.6, D6]

## 6. API de usuarios <!-- panel: PASS 2026-07-31 (2 hallazgos de seguridad y 3 de QA corregidos) -->

- [x] 6.1 Esquemas: peticiones con `extra="forbid"` y sin `tenant_id`; respuesta de listado y
      de detalle **sin** `temporary_password`; un tipo aparte para las dos respuestas que sí
      la llevan — `app/auth/api/user_schemas.py` [R1.2, R1.3, R2.5, R3.2, D10]
- [x] 6.2 Validación de entrada: email con formato, `preferred_language` en `es`/`en`, longitudes
      acotadas al ancho de columna, y rechazo de `role: SUPER_ADMIN` — `app/auth/api/user_schemas.py`
      [R1.6, R1.7, R3.2]
- [x] 6.3 Router con los seis endpoints, cada uno declarando su permiso con `require(...)`, y
      `Cache-Control: no-store` en las dos respuestas que devuelven la temporal —
      `app/auth/api/users_router.py` [R1.1, R2.1, R2.6, R3.1, R3.8, R4.1, D10]
- [x] 6.4 `summary`/`description` y modelos de respuesta anotados en cada ruta, para que el
      contrato quede legible en el OpenAPI que consume el frontend —
      `app/auth/api/users_router.py` [R4.4, `steering/documentation.md`]
- [x] 6.5 Builders de los seis casos de uso — `app/auth/api/dependencies.py` [R1, R2, R3, R4]
- [x] 6.6 Mapeo de las excepciones nuevas al envelope de PRD §23: `404` para
      `UserNotFoundError`, `409` para `EmailAlreadyExistsError`, `422` para
      `SelfRoleChangeError`/`LastOwnerError`/`UnassignableRoleError` —
      `app/auth/api/errors.py` [R1.4, R1.6, R3.5, R3.6, R7.1]
- [x] 6.7 Registrar el router en `app/main.py` [R1.1]
- [x] 6.8 Tests de API del camino feliz de los seis endpoints: `201` con temporal utilizable
      para hacer login, listado paginado con el envelope de PRD §23, `PATCH`, `DELETE`
      idempotente y reset — `tests/auth/test_user_admin_api.py` [R1.1, R2.1, R3.8, R4.1]
- [x] 6.9 **Matriz endpoint × 5 roles** con el molde de
      `tests/reservations/test_authorization.py`: expectativa escrita a mano por rol, ningún
      endpoint alcanzable sin token, y un rol sin permiso recibe la misma respuesta para un
      `id` real y para uno inventado — `tests/auth/test_user_admin_authorization.py`
      [R7.2, R7.3, R7.4, R7.5, R7.6, R7.7]
- [x] 6.10 **`404` cross-tenant** en los cuatro endpoints con `{id}`: un usuario que existe en
      el tenant B responde `404` y no `403` desde el tenant A, con cuerpo indistinguible del de
      un `id` inventado — `tests/auth/test_user_admin_isolation.py` [R7.1, R7.8]
- [x] 6.11 Test de que la temporal no aparece en ninguna respuesta de lectura, ni en
      `audit_logs.changes`, ni en los logs de la aplicación —
      `tests/auth/test_user_admin_api.py` [R1.2, R4.3, R6.2]
- [x] 6.12 Test de que un usuario desactivado **no puede renovar** por
      `POST /api/v1/auth/refresh` con un refresh emitido antes de la baja —
      `tests/auth/test_user_admin_api.py` [R3.7, D7]

## 7. Configuración del tenant: dominio e infraestructura <!-- panel: PASS 2026-07-31 (tenancy PASS; 1 hallazgo de seguridad y 6 de QA corregidos) -->

- [x] 7.1 Declarar `tzdata` explícitamente en las dependencias, con el motivo (hoy entra por
      `celery` → `kombu`; la validación de `timezone` no puede depender de una transitiva) —
      `backend/pyproject.toml`, `uv.lock` [R5.6, D14]
- [x] 7.2 Test primero de los value objects: `timezone` válido/ inválido vía `ZoneInfo`,
      `country` de dos letras ASCII mayúsculas, idioma en `es`/`en` —
      `tests/tenants/test_value_objects.py` [R5.5, R5.6, D14]
- [x] 7.3 Value objects — `app/tenants/domain/value_objects.py` [R5.5, R5.6, D14]
- [x] 7.4 Test primero de las invariantes de `Tenant`/`TenantConfig`: `status` y
      `storage_type` no son mutables por esta vía, umbral no negativo, confianza de IA en
      `[0,1]` y representable en `Numeric(3,2)`, SLAs positivos, ventanas no negativas —
      `tests/tenants/test_entities.py` [R5.3, R5.4, R5.5]
- [x] 7.5 Métodos de mutación de `Tenant` y `TenantConfig` con esas invariantes —
      `app/tenants/domain/entities.py` [R5.2, R5.3, R5.4, R5.5]
- [x] 7.6 Excepciones `TenantNotFoundError` y `TenantValidationError` —
      `app/tenants/domain/exceptions.py` [R5.5, R7.1]
- [x] 7.7 Puertos `TenantRepository` y `TenantConfigRepository`, este último con
      `get_or_create(tenant_id)` — `app/tenants/domain/repositories.py` [R5.1, R5.7]
- [x] 7.8 Adaptadores SQLAlchemy sin `commit`, con test de integración del `get_or_create`
      (crea con los valores por defecto la primera vez, devuelve la existente después) —
      `app/tenants/infrastructure/repositories.py`, `tests/tenants/test_repositories.py`
      [R5.1, R5.7]

## 8. API de configuración del tenant <!-- panel: PASS 2026-07-31 (tenancy PASS; 1 hallazgo de seguridad y 6 de QA corregidos) -->

- [x] 8.1 `GetTenantUseCase` y `UpdateTenantUseCase`: comparan el `id` de la ruta con el tenant
      del token y levantan `TenantNotFoundError` **antes de consultar la base de datos**;
      el `update` hace `get_or_create` de la config, aplica solo lo presente y audita
      `TENANT_UPDATED`/`TENANT_CONFIG_UPDATED` — `app/tenants/application/use_cases.py`
      [R5.1, R5.2, R5.7, R5.8, R7.1, R7.3, D12]
- [x] 8.2 Tests de los dos casos de uso con fakes, incluido que un `PATCH` sin cambios no
      escribe ni fila ni `AuditLog` — `tests/tenants/test_use_cases.py` [R5.2, R5.8, D15]
- [x] 8.3 Esquemas con la config **anidada**, consultando `model_fields_set` también en el
      objeto anidado para distinguir "ausente" de "null", y rechazando `status` y
      `storage_type` con `422` — `app/tenants/api/schemas.py` [R5.2, R5.3, R5.4, D13]
- [x] 8.4 Router `GET`/`PATCH /tenants/{id}` con `require(...)`, `summary`/`description` y
      modelos de respuesta; builders y mapeo de errores —
      `app/tenants/api/{router,dependencies,errors}.py` [R5.1, R5.2, R7.4, R7.5]
- [x] 8.5 Registrar el router y su handler de errores en `app/main.py` [R5.1]
- [x] 8.6 Tests de API: camino feliz de lectura y parcheo, `422` de `status`/`storage_type`,
      matriz de los cinco roles (`TENANT_OWNER` lee y escribe, `PROPERTY_MANAGER` solo lee,
      el resto `403`) — `tests/tenants/test_api.py` [R5.1, R5.2, R5.3, R5.4, R7.2, R7.4, R7.5, R7.6, R7.7]
- [x] 8.7 Test explícito de R7.9: `GET`/`PATCH /tenants/{otro-tenant-real}` responde `404`.
      Con su comentario de por qué necesita test propio — `tenants` no tiene columna
      `tenant_id`, así que `tenant_scoped_classes()` no la cubre y esta comparación es la única
      protección — `tests/tenants/test_isolation.py` [R7.9, D12]

## 9. Documentación

- [x] 9.1 `docs/user-management.md`: cómo se da de alta a alguien, cómo se le comunica la
      temporal, qué hacer cuando la pierde, y qué significa cada ajuste de `TenantConfig` —
      orientado a operación, enlazando a la spec en vez de repetirla
      [`steering/documentation.md`]
- [x] 9.2 Actualizar `docs/auth-tenancy.md`: los usuarios ya no entran solo por el bootstrap,
      y una desactivación o un reset revocan sesiones [R3.7, R4.2]
- [x] 9.3 Anotar en `docs/user-management.md` las tres limitaciones asumidas: la temporal no
      se fuerza a cambiar en el primer login (`auth-account-recovery`), `country` se valida
      solo de forma, y estos endpoints no tienen salida a internet todavía
      (`api-ingress-routing`, túnel SSH del `RUNBOOK.md` §7.4) [R4.4]
- [x] 9.4 README de la raíz revisado, y **sí necesitaba cambio** (dos afirmaciones que este
      change vuelve falsas): la sección Estructura decía que `auth`, `reservations` e
      `integrations` eran los únicos dominios con las cuatro capas — ahora `tenants` también —,
      y «Entrar en la aplicación» presentaba el bootstrap como la única forma de crear
      usuarios. Confirmado lo que **no** cambia: ninguna variable de entorno nueva (`.env.example`
      intacto), ningún target de Makefile, y ningún string de UI porque este change no toca
      `frontend/` [`steering/documentation.md`]

## 10. Verification

- [x] 10.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest`
      (con el stack parado, `docker compose run --rm backend uv run pytest`)
- [x] 10.2 Cadena de migraciones, igual que en CI: `uv run alembic upgrade head`,
      `uv run alembic check` y `uv run alembic downgrade base` sobre una base limpia
- [x] 10.3 Cobertura de `domain/` ≥ 80 % en lo que este change añade (PRD §4,
      `steering/testing.md`): `pytest --cov=app/auth/domain --cov=app/tenants/domain --cov=app/audit/domain`
- [x] 10.4 Comprobación manual del flujo completo con `make up` + `make bootstrap`: como
      `TENANT_OWNER`, crear una `CLEANER`, hacer login con la temporal devuelta, cambiarle el
      rol, leer `audit_logs` y confirmar que `changes` no contiene ninguna contraseña,
      resetear su contraseña y comprobar que su refresh anterior ya no renueva, desactivarla y
      confirmar el `401`; y como `PROPERTY_MANAGER`, que lista usuarios pero recibe `403` al
      crear
- [x] 10.5 Revisar que ningún test nuevo pasa en vacío: cada test de aislamiento y de la
      matriz falla si se invierte deliberadamente la condición que comprueba
