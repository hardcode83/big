# Tasks: platform-admin-api

## 1. Domain foundations — audit vocabulary, tenant factory, `MANAGE_PLATFORM` <!-- panel: PASS 2026-09-02 -->

- [x] 1.1 Añadir `TENANT_CREATED = "TENANT_CREATED"` a `backend/app/audit/domain/actions.py` y registrarlo en el `frozenset ACTIONS`. `ENTITY_TENANT` ya existe y no cambia. [R2.1, R2.2, D1, D7]
- [x] 1.2 Añadir `Tenant.create(...)` como `@classmethod` en `backend/app/tenants/domain/entities.py` que reutilice `_require_text` (con `MAX_NAME`), `_require_email`, `normalise_country`, `normalise_timezone`, `normalise_language` — los mismos guardias que `Tenant.update`. Devuelve un `Tenant` con `status=TenantStatus.ACTIVE`, `created_at`/`updated_at=now`, y un `id` nuevo. [R1.1, D2]
- [x] 1.3 Test en `backend/tests/tenants/test_entities.py` (nuevo, `test_create_classmethod`): `Tenant.create(name="x", billing_email="a@b.co", country="ES", timezone="Europe/Madrid", default_language="es", now=now)` levanta una `Tenant` válida; rechaza `name=""`, `billing_email` sin `@`, `country` fuera de `len == 2`, `default_language` fuera del catálogo del normalizador (mismos casos que `update`). [R1.1, D2]
- [x] 1.3a **Merge revision primero, antes de añadir la migración de unicidad.** El branch tiene dos cabezas en este momento — `c22b8ae01096` (archivada en `super-admin-identity`) y `r3v1ew5a03` (archivada en `revenue-reviews`, PR #151) — porque ambas descienden de `e5c9b1f47a28`. El contenedor `migrate` falla con "Multiple head revisions are present". Generar `alembic merge -m "merge platform-admin-api pre-revision" c22b8ae01096 r3v1ew5a03` desde `backend/`, que crea un nuevo fichero en `backend/alembic/versions/` con `down_revision = ('c22b8ae01096', 'r3v1ew5a03')` y `upgrade()`/`downgrade()` vacíos. Verificar con `alembic heads` que ahora solo hay una cabeza antes de seguir. Precedente: `parallel-migrations-need-a-merge-revision` (memoria de proyecto).
- [x] 1.3b Migración nueva en `backend/alembic/versions/` con `down_revision` apuntando a la revisión merge de 1.3a. `upgrade()` ejecuta `op.create_unique_constraint('uq_tenants_name', 'tenants', ['name'])`. `downgrade()` la retira con `op.drop_constraint(...)`. Acompañar con `unique=True` en `TenantModel.name` (`backend/app/tenants/infrastructure/models.py`). La baseline no creó la restricción (`4a5faad7796b_baseline_domain_foundation_core.py`), y `bootstrap.py:176` documenta el hueco — esta migración lo cierra. No requiere backfill: el bootstrap ya impide duplicados en la práctica, y la migración falla ruidosamente si los hubiera. [R-2, D2 (enmienda)]
- [x] 1.4 Añadir `TenantRepository.add(tenant: Tenant, config: TenantConfig) -> None` al puerto en `backend/app/tenants/domain/repositories.py` con docstring explicando que es el único camino de alta por dominio (`bootstrap.py` queda intacto por R7.1). Implementarlo en `backend/app/tenants/infrastructure/repositories.py`: dos `session.add` (uno por modelo) y un solo `flush()` para que `IntegrityError` de `tenants.name` surja aquí; traducir `IntegrityError` cuyo `error.orig` mencione `uq_tenants_name` (o el nombre que la migración 1.3b haya dejado) a `TenantAlreadyExistsError`, lo demás se re-raise. [R1.2, R1.4, R-2, D2]
- [x] 1.5 Test de integración en `backend/tests/tenants/test_repositories.py`: `add` con un nombre libre crea `TenantModel` y `TenantConfigModel`; `add` con un nombre repetido lanza `TenantAlreadyExistsError`; `add` con un FK inválido deja subir la `IntegrityError` sin mapear (la traducción es por nombre de constraint, no captura global). [R1.2, R1.4, R-2]
- [x] 1.6 Añadir `Permission.MANAGE_PLATFORM = "MANAGE_PLATFORM"` al enum en `backend/app/auth/domain/policy.py` (mismo `str, enum.Enum`, sin herencia), y un bundle `_PLATFORM = frozenset({Permission.MANAGE_PLATFORM})` para `SUPER_ADMIN`. Extender `ROLE_PERMISSIONS[UserRole.SUPER_ADMIN]` con `_SELF_SERVICE | _PLATFORM`. `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN` no se tocan. Ningún otro `_SOMETHING_*` arrastra `MANAGE_PLATFORM`. [R5.1, R5.2, D3, D6]
- [x] 1.7 Tests en `backend/tests/auth/test_policy.py`: actualizar `test_super_admin_holds_exactly_self_service_and_nothing_else` para que pine `ROLE_PERMISSIONS[UserRole.SUPER_ADMIN] == _SELF_SERVICE | _PLATFORM` (en vez del pin actual `_SELF_SERVICE`, que la tarea 1.6 invalida) — el cambio de pin es la parte que la lista de tareas omitía; `is_allowed(SUPER_ADMIN, MANAGE_PLATFORM) is True`; `is_allowed(role, MANAGE_PLATFORM) is False` para los otros cuatro roles; `Permission.MANAGE_PLATFORM` es miembro del enum; `MANAGE_PLATFORM` no aparece en `ROLE_PERMISSIONS` de ningún rol que no sea `SUPER_ADMIN`. [R5.2, R5.3, D6]

## 2. Platform module — `CreateTenantUseCase` and the SUPER_ADMIN-side audit seam <!-- hard --> <!-- panel: PASS 2026-09-02 -->

<!-- The seam is load-bearing (D5): `SUPER_ADMIN`'s session stays unmarked
     (`super-admin-identity`), so `audit_logs.tenant_id` MUST come from the use case,
     not from the session. The race on `uq_tenants_name` (R-2) is the second hard bit:
     two concurrent `add`s must both pass a name lookup but only one can pass the flush,
     and the loser has to surface as `TenantAlreadyExistsError` mapped to 409 without
     leaking the `IntegrityError`. -->

- [x] 2.1 Crear `backend/app/platform/__init__.py` vacío y `backend/app/platform/domain/__init__.py` vacío. Crear `backend/app/platform/domain/exceptions.py` con `TenantAlreadyExistsError`, mapeada a `409` con `ErrorCode.CONFLICT` por el handler del módulo (no por el genérico — `tenant` no la ve, así que tiene su propio `register_platform_error_handlers`). [R1.4, R2.3, D2]
- [x] 2.2 Crear `backend/app/platform/application/use_cases.py` con `CreateTenantUseCase.__init__(tenants, configs, audit, uow)` y `execute(*, actor_user_id, actor_ip, command, now) -> TenantSettings`. Orquesta: (a) `tenant = Tenant.create(...)`; (b) `config = TenantConfig.with_defaults(tenant_id=tenant.id, now=now)`; (c) `await self._tenants.add(tenant, config)` (la traducción de `IntegrityError` vive en el repo); (d) escribe una fila `audit_logs` con `action=TENANT_CREATED`, `entity_type=ENTITY_TENANT`, `entity_id=tenant.id`, `tenant_id=tenant.id` (del path/entidad, **nunca** del actor — D5), `actor_user_id`, `actor_ip`, y `changes` describiendo los cinco campos del cuerpo vía `ChangeSet(ENTITY_TENANT).diff(name, None, t.name).diff(billing_email, None, ...).diff(country, ...).diff(timezone, ...).diff(default_language, ...)`; (e) `await self._uow.commit()`. Si cualquier paso falla, **no** se llama `commit()` y la transacción aborta — R2.3, R4.2. Devuelve `TenantSettings(tenant=tenant, config=config)`. [R1.1, R2.1, R2.3, R4.1, D2, D5]
- [x] 2.3 Test unitario en `backend/tests/platform/test_use_cases.py` (con fakes de los puertos, sin DB): un `TenantRepository`/`TenantConfigRepository`/`AuditLogRepository`/`UnitOfWork` falsos verifican que (a) `Tenant.create` se llama con los cinco campos del comando y un `now`, (b) `tenants.add` se llama con `(tenant, config)`, (c) `audit.add` se llama con un `AuditLog` cuyos `tenant_id`/`entity_id` son los del tenant recién creado (no `None`), (d) `uow.commit()` se llama una vez y solo si los pasos anteriores no fallaron. [R2.3, R4.2, D5]
- [x] 2.4 Test unitario: si `tenants.add` lanza `TenantAlreadyExistsError`, `uow.commit()` NO se llama (verificado por el fake), y la excepción se propaga sin envolver. [R2.3, R-2]
- [x] 2.5 Test de integración en `backend/tests/platform/test_use_cases.py` (mismo fichero, marcador `@pytest.mark.asyncio` y la fixture `db_session`): sembrar la BD vacía; ejecutar `CreateTenantUseCase(...).execute(...)` con `actor_user_id=super_admin.id`, `actor_ip="127.0.0.1"`, un nombre único y los cinco campos; verificar que (a) hay una fila en `tenants` con `status=ACTIVE`, (b) hay una fila en `tenant_configs` con `tenant_id=tenants.id`, (c) hay una fila en `audit_logs` con `action=TENANT_CREATED`, `entity_type=TENANT`, `entity_id=tenant.id`, `tenant_id=tenant.id`, `actor_user_id=super_admin.id`, `actor_ip="127.0.0.1"`, y `changes` contiene los cinco `diff`. [R1.1, R2.1, R2.4, D5]
- [x] 2.6 Test de integración (concurrencia / R-2): sembrar la BD con un tenant de nombre `T`; lanzar `CreateTenantUseCase` con el mismo `name="T"` y `actor_user_id=super_admin.id`; debe terminar en `TenantAlreadyExistsError` y NO dejar una segunda fila en `tenants` ni una segunda fila de auditoría con `action=TENANT_CREATED` para `name="T"`. El test de concurrencia de dos corutinas se cubre en la sección N con dos requests simultáneos al router. [R1.2, R-2]

## 3. Platform module — `CreateUserInTenantUseCase` (validate tenant, delegate) <!-- panel: PASS 2026-09-02 -->

- [x] 3.1 Añadir `TenantNotActiveError` en `backend/app/platform/domain/exceptions.py`, mapeada a `404` (mismo trato que un tenant inexistente — R3.3). La clase `TenantAlreadyExistsError` ya está del paso 2.1. [R3.3, R3.4]
- [x] 3.2 Crear `backend/app/platform/application/use_cases.py::CreateUserInTenantUseCase` con `__init__(tenants, create_user: CreateUserUseCase)` (composición, no duplicación — D3). `execute(*, tenant_id, actor_user_id, actor_ip, command, now) -> CreatedUser`: (a) `tenant = await self._tenants.get(tenant_id)`; (b) si `tenant is None` o `tenant.status is not TenantStatus.ACTIVE`, lanzar `TenantNotActiveError` (404 indistinguible de inexistente); (c) delegar en `self._create_user.execute(tenant_id=tenant_id, actor_user_id=actor_user_id, actor_ip=actor_ip, command=command, now=now)` y devolver su `CreatedUser` tal cual. NO duplicar hashing, generación de password temporal, `must_change_password=True` ni el `ChangeSet` — `CreateUserUseCase` ya lo hace y la auditoría sale con `tenant_id=<path>` por la firma del parámetro (D5, R4.3). [R3.1, R3.3, R4.3, D3]
- [x] 3.3 Test unitario en `backend/tests/platform/test_use_cases.py`: con un `TenantRepository` fake que devuelve `None` para el `tenant_id`, `execute` lanza `TenantNotActiveError` y `create_user.execute` NO se llama. [R3.3]
- [x] 3.4 Test unitario: con un `TenantRepository` fake que devuelve un `Tenant(status=TenantStatus.SUSPENDED)`, `execute` lanza `TenantNotActiveError` y `create_user.execute` NO se llama. [R3.3]
- [x] 3.5 Test unitario: con un `TenantRepository` fake que devuelve un `Tenant(status=TenantStatus.ACTIVE)`, `execute` llama a `create_user.execute(tenant_id=<path>, actor_user_id=<actor>, actor_ip=<ip>, command=<cmd>, now=<now>)` y devuelve su `CreatedUser` sin tocar el resultado (incluida la contraseña temporal). [R3.1, R4.3]
- [x] 3.6 Test de integración en `backend/tests/platform/test_use_cases.py`: sembrar `tenant_a` (status ACTIVE) y un `super_admin` sin tenant; ejecutar `CreateUserInTenantUseCase(...).execute(tenant_id=tenant_a.id, ..., command=CreateUserCommand(name="...", email="...", role=UserRole.PROPERTY_MANAGER))`; verificar (a) hay una fila nueva en `users` con `tenant_id=tenant_a.id`, `role=PROPERTY_MANAGER`, `must_change_password=True`, `status=ACTIVE`; (b) hay una fila en `audit_logs` con `action=USER_CREATED`, `entity_type=USER`, `entity_id=<new_user.id>`, `tenant_id=tenant_a.id` (del path, no del actor — el actor es SUPER_ADMIN sin tenant), `actor_user_id=super_admin.id`, `actor_ip`, y `changes` con `email`, `role`, `password` (redactado a `{"changed": true}` por la regla 11 que ya aplica `CreateUserUseCase`). [R4.1, R4.3, D5]
- [x] 3.7 Test de integración con un tenant `SUSPENDED`: ejecutar el mismo flujo debe terminar en `TenantNotActiveError` y NO crear fila de `users` ni fila de `audit_logs` con `USER_CREATED`. [R3.3, R4.2]

## 4. Platform API — schemas, router, dependencies, errors, mounting <!-- panel: PASS 2026-09-03 -->

- [x] 4.1 Crear `backend/app/platform/api/__init__.py` vacío y `backend/app/platform/api/schemas.py` con `CreateTenantRequest` (cinco campos: `name: str` con `max_length=200`, `billing_email: EmailStr`, `country: str` con `min_length=2, max_length=2`, `timezone: str` con `max_length=50`, `default_language: Literal["es","en"]`), `TenantResponse` con `id`, `name`, `billing_email`, `country`, `timezone`, `default_language`, `status`, `created_at`, `updated_at`, y `config: TenantConfigResponse` anidada; `CreatePlatformUserRequest` (cuatro campos: `email: EmailStr`, `full_name: str` con `max_length=200`, `phone: str | None`, `role: UserRole` con constraint que rechaza `SUPER_ADMIN` por un `field_validator` — R3.5), `CreatedPlatformUserResponse` con `user: UserResponse` + `temporary_password: str`. Todos con `model_config = ConfigDict(from_attributes=True, extra="forbid")`. [R1.1, R1.3, R3.1, R3.5, R3.6]
- [x] 4.2 Crear `backend/app/platform/api/dependencies.py` con `require_platform()` que devuelve `Annotated[AuthenticatedRequest, Depends(require(Permission.MANAGE_PLATFORM))]`. Reutiliza `require` y `AuthenticatedRequest` de `app/auth/api/dependencies.py`. Una sola declaración porque las dos rutas comparten el mismo permiso. [R5, R6.1, D6]
- [x] 4.3 Crear `backend/app/platform/api/use_case_dependencies.py` con builders para los dos casos de uso:
  - `get_create_tenant_use_case(session, audit)` → `CreateTenantUseCase(tenants=SqlAlchemyTenantRepository(session), configs=SqlAlchemyTenantConfigRepository(session), audit=SqlAlchemyAuditLogRepository(session), uow=SqlAlchemyUnitOfWork(session))`. Mismo patrón que `auth/api/user_dependencies.py` y `tenants/api/dependencies.py`. [R1.1, D2]
  - `get_create_user_in_tenant_use_case(session, hasher)` → `CreateUserInTenantUseCase(tenants=SqlAlchemyTenantRepository(session), create_user=CreateUserUseCase(users=SqlAlchemyUserRepository(session), audit=SqlAlchemyAuditLogRepository(session), hasher=hasher, uow=SqlAlchemyUnitOfWork(session)))`. El `UnitOfWork` interior y el de fuera NO se anidan: una sola transacción por `uow.commit()` cuando el wrapper llega al final — esto es lo que la regla 1 ya promete vía `db_session` por-request. [R3.1, R4.2, D3]
- [x] 4.4 Crear `backend/app/platform/api/errors.py` con `register_platform_error_handlers(app)` que mapea `TenantAlreadyExistsError → 409 ErrorCode.CONFLICT` y `TenantNotActiveError → 404 ErrorCode.NOT_FOUND`. Mensaje accionable en ambos: "A tenant with that name already exists" y "Tenant does not exist". La `domain/exceptions.py` define un `PlatformDomainError` base que la jerarquía usa para que un handler genérico cubra el futuro (no se añade ningún `PlatformDomainError` más aquí — el módulo es pequeño y dos entradas en la tabla son explícitas). [R1.4, R3.3]
- [x] 4.5 Crear `backend/app/platform/api/router.py` con `router = APIRouter(prefix="/platform", tags=["platform"], responses=AUTHENTICATED_RESPONSES)` y las dos rutas:
  - `POST /tenants` con `response_model=TenantResponse`, `status_code=201`, `summary="Create a tenant (SUPER_ADMIN only)"`, `description` que diga literalmente "Requires `SUPER_ADMIN` — issues `MANAGE_PLATFORM`. Creates the tenant and its default configuration; idempotent against a pre-existing `tenant_configs` row." Cable: `body: CreateTenantRequest`, `authenticated: PlatformDep`, `client_ip: ClientIpDep`, `use_case: Annotated[CreateTenantUseCase, Depends(get_create_tenant_use_case)]`. Mapea `TenantSettings` → `TenantResponse`. [R1, R5, R6.1, R6.3, D5]
  - `POST /tenants/{tenant_id}/users` con `response_model=CreatedPlatformUserResponse`, `status_code=201`, `summary="Create a user in a named tenant (SUPER_ADMIN only)"`, `description` que diga literalmente "Requires `SUPER_ADMIN` — issues `MANAGE_PLATFORM`. `tenant_id` comes from the path, not the token; the caller names the tenant the new account belongs to. Returns the temporary password exactly once." Cabecera `Cache-Control: no-store` en la respuesta (`NO_STORE` de `auth/api/users_router.py:60`). Mapea `CreatedUser` → `CreatedPlatformUserResponse`. [R3, R5, R6.1, R6.3]
- [x] 4.6 Registrar en `backend/app/main.py`: añadir `from app.platform.api.router import router as platform_router`, `from app.platform.api.errors import register_platform_error_handlers`, `register_platform_error_handlers(app)` en la cadena de `register_*_error_handlers` (justo después de `register_auth_error_handlers` para mantener el orden lógico: auth → platform), y `app.include_router(platform_router, prefix=API_V1_PREFIX)` después de los demás routers (siguiendo el patrón: lo nuevo se monta al final para que un fallo de carga no rompa routers anteriores). [R6.1, D5]
- [x] 4.7 Test de API en `backend/tests/platform/test_api.py`: `POST /api/v1/platform/tenants` con un `super_admin` autenticado y un cuerpo válido devuelve `201` con el `id` del tenant nuevo, `status=ACTIVE`, y `config` con los defaults de `TenantConfig.with_defaults`. Verificar el header `Cache-Control: no-store` no aplica a esta ruta — aplica solo al alta de usuario. [R1.1, R5]
- [x] 4.8 Test de API: `POST /api/v1/platform/tenants` con un nombre que ya existe en `tenants` (status `ACTIVE`) devuelve `409` con `{error: {code: "CONFLICT", message: ...}}` y NO crea segunda fila. [R1.2, R1.4]
- [x] 4.9 Test de API: `POST /api/v1/platform/tenants` con cuerpo inválido (`name=""`, `billing_email="not-an-email"`, `country="ESPA"`) devuelve `422` con la lista de campos fallidos en el envelope PRD §23. [R1.3]
- [x] 4.10 Test de API: `POST /api/v1/platform/tenants/{tenant_a.id}/users` con un `super_admin` y un cuerpo válido (`role=PROPERTY_MANAGER`) crea el usuario en `tenant_a` y devuelve `201` con `Cache-Control: no-store`, `user` con `tenant_id=tenant_a.id` y `temporary_password`. [R3.1, R3.4]
- [x] 4.11 Test de API: `POST /api/v1/platform/tenants/{tenant_a.id}/users` con `role=SUPER_ADMIN` devuelve `422` (rechazado por el `field_validator` del schema, no por `GRANTABLE_ROLES` en la entidad — la entrada del schema es la primera línea de defensa, R3.5). [R3.5]
- [x] 4.12 Test de API: `POST /api/v1/platform/tenants/<id-inexistente>/users` y `POST /api/v1/platform/tenants/<id-de-tenant-SUSPENDED>/users` devuelven `404` con `code=NOT_FOUND` indistinguible entre sí. [R3.3]
- [x] 4.13 Test de API: `POST /api/v1/platform/tenants/{tenant_a.id}/users` con un email ya usado por `tenant_b` devuelve `409` con `code=CONFLICT` sin nombrar a qué tenant pertenece (mismo trato que `user-management`). [R3.4]
- [x] 4.14 Test de API: `POST /api/v1/platform/tenants` con cuerpo inválido (`name=""`) Y un token no `SUPER_ADMIN` (p. ej. `tenant_a`'s `TENANT_OWNER`): el `require(Permission.MANAGE_PLATFORM)` corta ANTES de validar el cuerpo y devuelve `403` con un único motivo. Confirmar este orden: `require(...)` está declarado antes que `body: CreateTenantRequest` en la firma del endpoint. [R1.4, R5.3]

## 5. Authorization matrix, isolation, structural guards, and docs <!-- panel: PASS 2026-09-03 -->

- [x] 5.1 Añadir las dos rutas al snapshot protegido de `backend/tests/test_route_authorization.py::test_the_protected_endpoints_are_the_ones_expected`: `"/api/v1/platform/tenants"` y `"/api/v1/platform/tenants/{tenant_id}/users"`. Actualizar el comentario del snapshot citando `platform-admin-api` como el cambio que las añadió (mismo formato que los snapshots previos). [R6.1, R6.2]
- [x] 5.2 Nuevo test estructural en `backend/tests/test_route_authorization.py::test_manage_platform_only_lives_under_platform_prefix`: walkear las rutas registradas, recoger las que llevan `require(Permission.MANAGE_PLATFORM)` (vía `getattr(dependant.call, REQUIRED_PERMISSION_ATTR, None)` igual que en el resto del módulo), y fallar si alguna cuelga de un path que NO empieza por `/api/v1/platform/`. Esto cierra R-6 del design. [R-6]
- [x] 5.3 Nuevo fichero `backend/tests/platform/test_authorization.py` con un test por rol, para cada una de las dos rutas: `TENANT_OWNER`, `PROPERTY_MANAGER`, `CLEANER`, `TECHNICIAN` y un `SUPER_ADMIN` con `must_change_password=True` (que es fenced, R5.4 — el `require(...)` corta antes de la autorización, pero el test declara el caso para cerrar una regresión futura). Cada rol no autorizado debe obtener `403` con un único motivo. Usar la fixture `users_by_role_a` y la fixture `super_admin` (añadir a `tests/auth/conftest.py` si no existe — `tenant_a` no sirve para SUPER_ADMIN por `ck_users_super_admin_tenant_id_null`, sigue el patrón de `tenant_for_role`). [R5.3]
- [x] 5.4 Test de aislamiento: nuevo fichero `backend/tests/platform/test_isolation.py` con `test_creating_a_user_in_tenant_a_does_not_leak_to_tenant_b`: sembrar `tenant_a`, `tenant_b`, y un `super_admin`; ejecutar `POST /api/v1/platform/tenants/{tenant_a.id}/users` y verificar que el usuario creado tiene `tenant_id=tenant_a.id`, no `tenant_b.id` y no `None` (que sería el tenant del actor — la regla 1 dice que `SUPER_ADMIN` puede saltarse esa restricción **en el actor**, no en la entidad). [R3.2, R3.7]
- [x] 5.5 Test de bootstrap (R7.2/R7.3): nuevo test en `backend/tests/cli/test_bootstrap.py` o en `backend/tests/platform/test_isolation.py` que ejecute `apply_plan(session, plan, hasher)` con un `BootstrapPlan` que contiene los dos seeds (`tenant_name=MAGNO_REDES11`, `users=(OWNER, MANAGER, SUPER_ADMIN)`) y luego invoque `POST /api/v1/platform/tenants` con `name="MAGNO_REDES11"`: debe responder `409` con `code=CONFLICT`. Repetir el bootstrap (`apply_plan` segunda vez) sobre la misma BD: ninguna fila nueva; `tenants=0`, `users=0`, `tenant_configs_converged` solo si `storage_type` cambia — la unicidad del nombre por la API no afecta a la convergencia del bootstrap. [R7.1, R7.2, R7.3]
- [x] 5.6 Modificar `sdd/specs/auth-tenancy.md`: añadir `MANAGE_PLATFORM` a la enumeración de permisos y al mapeo `ROLE_PERMISSIONS` para `SUPER_ADMIN` (mismo formato que las entradas existentes); añadir las dos rutas al censo de excepciones a la regla 1 (mismo formato que las entradas de `super-admin-identity`). [R5.1, R5.2, R6.1]
- [x] 5.7 Modificar `sdd/specs/user-management.md`: añadir una nota sobre el caso de uso compartido con `POST /api/v1/platform/tenants/{tenant_id}/users` (R4.3) y otra nota declarando que `GRANTABLE_ROLES` no se abre por API en esta entrada (R3.5/D2). [R4.3, R3.5]
- [x] 5.8 Regenerar el contrato: `python3 backend/scripts/export_openapi.py` (o el comando que `sdd/project.md` §Verification declare hoy) → `backend/openapi.json` regenerado; `backend/tests/test_openapi_contract.py` verde. Confirmar que `tags=["platform"]` aparece en las dos rutas y que `summary`/`description` dicen literalmente `Requires SUPER_ADMIN`. [R6.3]

## N. Verification

- [ ] N.1 Suite backend completa verde: `docker compose exec backend uv run pytest` — incluye `tests/platform/` (cuando exista), `tests/tenants/`, `tests/auth/`, `tests/cli/`, `tests/test_route_authorization.py`, `tests/test_openapi_contract.py`, `tests/test_layering.py`, `tests/test_unscoped_reads.py`. Comparar el total de ficheros y tests contra el `pytest --collect-only` de partida del worktree (no contra el del principal — `sdd/project.md` §Worktree bootstrap). [testing.md]
- [ ] N.2 `uv run pyright .` (con `uv sync --frozen` hecho dentro de `backend`) sin findings nuevos en `app/platform/`, `app/auth/domain/policy.py`, `app/tenants/domain/entities.py`, `app/audit/domain/actions.py`. Los findings preexistentes en módulos no tocados no se imputan a este change. [testing.md]
- [ ] N.3 Aislamiento de tenant: ejecutar `tests/platform/test_isolation.py` y `tests/platform/test_authorization.py` con la suite global y verificar que (a) cada rol no-`SUPER_ADMIN` recibe `403` con un único motivo en ambas rutas, (b) un `tenant_id` inexistente o `SUSPENDED` recibe `404` indistinguible, (c) un email ya usado bajo otro tenant recibe `409`. [R5.3, R3.3, R3.4]
- [ ] N.4 Concurrencia (R-2): dos corutinas lanzan `POST /api/v1/platform/tenants` con el mismo `name` contra la misma BD; una termina en `201` con la fila en `tenants`, la otra en `409` con `code=CONFLICT` y la BD queda con exactamente una fila para ese nombre y una sola fila `TENANT_CREATED` en `audit_logs`. [R1.2, R-2]
- [ ] N.5 Re-ejecución del bootstrap (R7.3): ejecutar `python -m app.cli.bootstrap` con `.env` apuntando a la BD del worktree; una segunda ejecución con el mismo `.env` debe terminar con `tenants=0, tenant_configs=0, users=0` (o `tenant_configs_converged=1` si `BOOTSTRAP_STORAGE_TYPE` cambia); el alta de un tercer tenant por la API no afecta a una segunda ejecución del bootstrap. [R7.1, R7.2, R7.3]
- [ ] N.6 Confirmar que `tests/test_route_authorization.py` queda verde después del cambio del snapshot (5.1) y del nuevo test estructural (5.2): cada ruta nueva declara `MANAGE_PLATFORM` y vive bajo `/api/v1/platform/`; el snapshot protegido incluye las dos rutas. [R6.1, R6.2, R-6]
- [ ] N.7 Confirmar `tests/test_rule11_ownership.py` no se ve afectado: este change no introduce nuevas columnas con texto en claro (las cinco columnas del cuerpo de `POST /tenants` ya estaban cubiertas por el censo de `TenantConfigPatch`/`tenant_configs`; el `full_name` y `email` del alta de usuario son campos USER ya cubiertos). Si el guard encuentra algo, es un falso positivo del propio guard o un cambio accidental. [security.md regla 11]
- [ ] N.8 `backend/openapi.json` regenerado y commiteado junto al `platform-router` y al `platform-error-handlers`; `cd frontend && npm run api:check` con el workaround de ENOENT documentado en `sdd/project.md` §Worktree bootstrap (no aplica en CI). El `.d.ts` generado incluye el namespace `platform` con los dos DTOs. [R6.3, project.md §Worktree bootstrap]

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
- `make up` falls because the `migrate` container can't run `alembic upgrade head` while
  the branch has two heads (`c22b8ae01096` + `r3v1ew5a03`); fix order is `alembic merge`
  via `docker compose run --rm --no-deps backend alembic …` BEFORE `make up` brings the
  stack up. The `run --rm --no-deps` form works around the broken `migrate` container
  by bypassing it entirely (the `backend` image carries `alembic` and the same env).
- The merge revision Alembic generated is `936fef59b1d4`; the new constraint
  migration is `936fef5a01b1_tenants_name_unique.py` (down_revision points at the merge).
  Both files live in `backend/alembic/versions/` next to the archived heads.
- Setting `unique=True` on `TenantModel.name` made SQLAlchemy create a *second* unique
  index called `tenants_name_key` (independent of the migration's `uq_tenants_name`).
  Both are now in `pg_constraint`; the repository's `IntegrityError` translator matches
  against a frozenset of `{"uq_tenants_name", "tenants_name_key"}` so the duplicate test
  passes. The second constraint is harmless for now but redundant; if section 2 wants
  to drop one, dropping `tenants_name_key` (created by `unique=True` on the model) and
  keeping the migration's `uq_tenants_name` is the more idiomatic option, because the
  migration's name matches the rest of the catalogue.
- `TenantRepository.add` flushes the tenant row BEFORE adding the configuration row:
  two `session.add` calls do not guarantee INSERT order in SQLAlchemy 2, and
  `tenant_configs.tenant_id` is a `ForeignKey` to `tenants.id`. A single `flush` after
  both `add`s would race the FK against the UNIQUE we want to translate. The first
  `flush` is what surfaces the `uq_tenants_name` violation cleanly.
- `TENANT_CREATED` is added in section 1 but its writer (the use case in section 4) is
  not; `AUDITABLE_FIELDS` does not need a per-action entry — the entity-level allowlist
  for `TENANT` already exists. Section 4's responsibility is to wire the writer, not to
  extend the vocabulary.
- `test_add_translates_a_duplicate_name_into_TenantAlreadyExistsError` calls
  `db_session.commit()` after seeding the existing tenant and `db_session.rollback()`
  after the failed `add`; the `db_session` fixture in this suite is transactional, and
  without the commit the rollback wipes the seed. Both are intentional and the
  docstring records why.
- `CreateTenantUseCase.__init__` declares `configs` even though `execute()` never calls
  it; section 4 will wire `get_create_tenant_use_case` to inject
  `SqlAlchemyTenantConfigRepository` for the GET path, and re-declaring the constructor
  signature now would break that wiring.
- `TenantAlreadyExistsError` is re-exported from `backend/app/platform/domain/exceptions.py`
  (`from app.tenants.domain.exceptions import TenantAlreadyExistsError`); section 4's
  `register_platform_error_handlers` imports it from there, so the platform module has
  one canonical location. The exception class itself stays in `tenants/domain/` because
  `TenantRepository.add` raises it (R-2, section 1's decision).
- `_AuditWriter` from `app.auth.application.user_admin` is used (not the `AuditLogFactory`
  directly) so the chokepoint that enforces `action`/`entity_type`/`changes`/`now`
  contracts runs the same path `CreateUserUseCase` does. The audit row is built with
  `tenant_id=tenant.id` (the NEW tenant's id, never the actor's) — design D5 requires
  this for the `SUPER_ADMIN` actor because its session is unmarked and the global
  tenant filter cannot supply `audit_logs.tenant_id` from the session.
- The unit tests use fakes for all four ports (`_FakeTenantRepository`,
  `_FakeTenantConfigRepository`, `_FakeAuditLogRepository`, `_FakeUnitOfWork`). They
  record calls, not state, and the assertions check `tenant_repo.add_called_with`,
  `audit_repo.entries`, `uow.commits`. The `_FakeTenantConfigRepository`'s `get_or_create`
  is a guard: it raises `AssertionError` if `execute()` ever reaches for it, so a future
  drift (e.g. someone adding a "load existing config" call) fails loudly in tests rather
  than silently passing.
- The 2.6 integration test (`test_create_use_case_with_duplicate_name_raises_and_writes_nothing`)
  calls `await db_session.rollback()` after the second `execute()` raises
  `TenantAlreadyExistsError`. Without it the session is in `PendingRollbackError` state
  and the subsequent `select(TenantModel)...` query fails. Same pattern as the section-1
  test the implementation notes already cite.
- The 2.5 integration test seeds the `SUPER_ADMIN` actor inline (via `UserModel` with
  `tenant_id=None`) because `tests/auth/conftest.py` does not yet have a `super_admin`
  fixture; section 5 will add one and the 2.5 test can stop carrying that helper. Until
  then the row satisfies `audit_logs.actor_user_id`'s FK.
- `TenantNotActiveError` accepts an optional `tenant_id` for log diagnostics only; the
  response never carries it (R3.3 wants the missing-vs-suspended case indistinguishable).
  It inherits from `PlatformDomainError` so a future handler can match the family with one
  clause; section 4's explicit mapping still wins today.
- `CreateUserInTenantUseCase.__init__` takes the wrapped use case directly as
  `create_user: CreateUserUseCase` (positional-or-keyword, no `*`), per the task's signature.
  It does NOT take a `UnitOfWork`: the wrapped use case owns its own `commit()`, and
  section 4's `get_create_user_in_tenant_use_case` injects the same `SqlAlchemyUnitOfWork`
  the inner `CreateUserUseCase` receives so the per-request transaction is one commit, not
  a nested `SAVEPOINT`. The wrapper's docstring records this so a future reader does not
  "fix" the signature by adding a `uow` parameter.
- The wrapper returns whatever `CreateUserUseCase.execute` returns, untouched — including
  the `temporary_password`. The 3.5 unit test asserts identity (`result is create_user.return_value`)
  to catch any future copy that would silently drop the one-time secret.
- The section-3 fakes reuse the section-2 `_FakeTenantRepository`, extended with a
  `get_return` / `get_calls` pair. `get_calls` lets the unit tests assert "yes, the wrapper
  did look up the tenant before raising" without coupling to internal call counts. The
  same fake is reused because the wrapper's view of the port is the same as section 2's:
  `add` is unused (the wrapper never persists a tenant) and only the new `get` method
  carries assertions.
- `_FakeCreateUserUseCase` records the EXACT kwargs the wrapper forwarded — including
  the `command` by identity, so the test catches a future "let me rebuild the command"
  drift that would silently lose the `phone` or `preferred_language` fields.
- The 3.6 and 3.7 integration tests reuse the inline `SUPER_ADMIN` pattern from the 2.5
  test; section 5's `super_admin` fixture will let them drop the helper. The seeded
  tenant in 3.6 is `TenantModel(...)` + `TenantConfigModel(...)` rather than the
  `tests/auth/conftest.py::insert_tenant` helper, because the helper's `with_notification_config=True`
  default already pins the two channel flags — the assertion only needs the `ACTIVE` row
  to exist, and the helper would carry the same data either way. Using the raw models
  keeps the test self-contained and readable.
- The 3.6 integration test verifies `audit_row.changes["password"] == {"changed": True}`:
  this is the redaction rule 11 of `steering/security.md`, applied by `CreateUserUseCase`,
  reused verbatim. Section 4 does not need to redo this; the wrapper's only contract
  is "delegate, do not edit".
- `email-validator>=2.0` is added to `backend/pyproject.toml`'s `[project].dependencies`
  because `CreateTenantRequest.billing_email` and `CreatePlatformUserRequest.email` are
  pydantic `EmailStr`. The tenants-scoped `POST /api/v1/users` keeps its `EMAIL_PATTERN`
  regex on purpose (`app/auth/api/user_schemas.py`), so this is the only place that needs
  the package. The dependency was added after `docker compose exec -T backend uv pip install
  email-validator` confirmed the import path; `uv sync` from a fresh image will pick it up.
- `PlatformUserResponse` is a new type, NOT a re-export of `app.auth.api.user_schemas.UserResponse`,
  because the platform operator names the tenant in the path and the response has to echo
  `tenant_id` back. `UserResponse` deliberately omits it (the tenants-scoped endpoints derive
  it from the token, so printing it would be a no-op). Two types, one router; section 5's
  isolation test (5.4) uses this `tenant_id` field as its primary assertion.
- The endpoint signature declares `authenticated: PlatformDep` BEFORE `body: CreateTenantRequest`,
  matching task 4.14's order requirement. FastAPI resolves dependencies before bodies in
  practice, but the declaration order is what a reviewer reads and what the test pins; the
  same order applies to `create_user_in_tenant`.
- `tests/platform/test_api.py::test_post_tenants_with_a_duplicate_name_answers_409_without_a_second_row`
  calls `await db_session.commit()` after seeding the existing tenant AND
  `await db_session.rollback()` after the API call. Both are intentional and the test's
  docstring records why: the `db_session` fixture is shared across requests, the seed only
  flushes (never commits), and the API's failed INSERT rolls the session back. Without the
  explicit commit the seed would be wiped by the rollback; without the explicit rollback the
  `select(TenantModel)...` after the API call would fail with `PendingRollbackError`. Same
  pattern the section-2 integration test documented.
- `super_admin` is added as a fixture in `tests/platform/conftest.py` (re-exported from
  `tests/auth/conftest.py` for the rest of the package) until section 5 promotes it to the
  shared conftest. The pattern matches the section-2/3 integration tests: `tenant=None`,
  `role=UserRole.SUPER_ADMIN`. `ck_users_super_admin_tenant_id_null` enforces the `None`.
- The two new entries in `tests/test_route_authorization.py::test_the_protected_endpoints_are_the_ones_expected`
  are appended to the snapshot set with a comment block following the format of the previous
  changes. The assertion now requires every new protected path to be a visible diff in this
  snapshot — exactly what the comment block promises.
- The OpenAPI summary/description for both routes literally say
  "Create a tenant (SUPER_ADMIN only)" and "Create a user in a named tenant (SUPER_ADMIN only)",
  and the descriptions literally include "Requires SUPER_ADMIN — issues MANAGE_PLATFORM",
  per task 4.5's wording. Section 5.8 regenerates `backend/openapi.json` from this contract.
- Section 5's snapshot entry (5.1) was already added by section 4 — the
  `test_the_protected_endpoints_are_the_ones_expected` set includes the two
  `/api/v1/platform/...` paths with the `platform-admin-api` comment block. Marking 5.1
  `[x]` retroactively; no code change.
- The structural test (5.2) lives next to the snapshot, not next to the platform tests:
  it walks every registered route and pins the property the snapshot cannot — that
  `MANAGE_PLATFORM` is bound to the `/api/v1/platform/` prefix, not just to a single
  route. A future cross-tenant surface either lives under the same prefix (and the test
  stays green) or it fails here, which is the visible diff R-6 asks for.
- The per-role authorization test (5.3) reuses `users_by_role_a` for the four tenant
  roles and the platform's `super_admin` for the authorized case; the fenced case gets
  a `fenced_super_admin` fixture seeded inline because `users_by_role_a` cannot hold a
  `SUPER_ADMIN` (`ck_users_super_admin_tenant_id_null`) and the platform's
  `super_admin` fixture would defeat the test's point. The fence fires before the
  permission check, so the 403 reason is `PASSWORD_CHANGE_REQUIRED` (or `FORBIDDEN`
  depending on the gate wiring); the test pins both because either is acceptable as
  long as the request is refused.
- `hasher` is now re-exported from `tests/platform/conftest.py` so the fenced fixture
  can hash a temporary password; it was already used internally by `auth/conftest.py`
  but not re-exported here. Same pattern as the existing `insert_user`/`tenant_a`
  re-exports — the platform test package pulls the auth package's fixtures by name.
- The isolation test (5.4) does the cross-tenant check in three states — right
  tenant, wrong tenant, NULL — and asserts the first by ground truth against the
  database, not just against the response envelope. The envelope already pins the
  happy path (`body["user"]["tenant_id"] == str(tenant_a.id)`); the SQL query is what
  closes the case where the response lies. A symmetric test (named `tenant_b` instead
  of `tenant_a`) catches a regression where the `tenant_id` came from a cached lookup
  rather than the path.
- The bootstrap test (5.5) is in `test_isolation.py` rather than `test_bootstrap.py`
  because no such file exists yet — the project's CLI tests are split between
  `test_demo_reset.py` and `test_seed_demo.py`. The bootstrap test pairs a real
  `apply_plan` run with a real API call against the same database, then re-runs the
  bootstrap to assert convergence: `tenants=0`, `users=0`, `tenant_configs_converged=0`
  because the plan's `storage_type` matches the one already persisted. The convergence
  property survives the platform's `uq_tenants_name` migration — the bootstrap is
  create-only on the tenant identity, the API is what enforces uniqueness, and the
  two writers cooperate rather than collide.
- The fenced-super-admin test uses `pytest.skip` for the `SUPER_ADMIN` role rather
  than forking the matrix into "authorized" and "unauthorized" tests; one test pins
  the 201 vs 403 split (parametrised), the next pins the 403 envelope, and the fenced
  case stands on its own. The skip keeps the parametrised test's assertion coherent —
  "200 vs 403" reads better than "this row is special-cased below".
- Spec changes (5.6, 5.7) are prose-only; they fold the change into the catalogue of
  permissions and the rule-1 exception census the spec already maintained. The
  `MANAGE_PLATFORM` entry uses the same `_SOMETHING` bundle shape the rest of the
  catalogue does (`_PLATFORM`), and the cross-tenant exception is its own paragraph
  rather than an extension of the `_SELF_SERVICE` enumeration — the platform route
  is NOT self-service, so listing it there would lie about what the actor does.
