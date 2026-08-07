# Tasks: properties-crud

Orden pensado para que el sistema siga en verde tras cada sección: el esquema primero, luego dominio → infraestructura → auditoría → permisos → aplicación, y la capa `api/` al final, cuando todo lo que necesita ya existe. La sección 8 es la única que cruza a otra capability y va aislada a propósito.

## 1. Migración: unicidad de `pms_external_id` (D5)

- [ ] 1.1 Nueva migración en `backend/alembic/versions/` con `down_revision = "c3f81a5d7e42"` (HEAD actual) que cree `uq_properties_tenant_id_pms_external_id` como índice **único parcial** con `postgresql_where=sa.text('pms_external_id IS NOT NULL')`. Copiar el estilo y el razonamiento del docstring de `c3f81a5d7e42:84-94` (Postgres trata los NULL como distintos, el parcial es lo que permite varias propiedades sin PMS). El `downgrade` lo borra. Poner en el docstring la afirmación de reversibilidad. [R2]
- [ ] 1.2 Verificar que `uv run alembic upgrade head`, `alembic check` y `alembic downgrade base` pasan los tres — el último es lo que CI corre y lo que detecta un tipo de enum filtrado. [R2]

## 2. Dominio: excepciones y puerto

- [ ] 2.1 Añadir a `backend/app/properties/domain/exceptions.py`: `PropertyNotFoundError`, `DuplicateInternalCodeError`, `DuplicatePmsExternalIdError` y `PropertyValidationError`, todas bajo `PropertyDomainError`. Hoy no existe ninguna de las cuatro. [R1, R2]
- [ ] 2.2 Añadir al puerto `backend/app/properties/domain/repositories.py` la firma `add(tenant_id, property, *, wifi_secret: EncryptedSecret | None)`, importando `EncryptedSecret` de `app.core.encrypted_secret` — que es exactamente el split que ese módulo existe para permitir (`encrypted_secret.py:10-17`: `domain/` puede nombrar un valor cifrado sin importar `cryptography`). Documentar en el docstring por qué el secreto es parámetro y no campo de la entidad (D2). [R2, R5]
- [ ] 2.3 Añadir al puerto `update_details(tenant_id, property_id, changes)` y `set_wifi_password(tenant_id, property_id, secret)`. En el docstring de `update_details`, dejar escrito que su conjunto admisible **excluye `current_operational_state`** y por qué, enlazando al docstring de `save` que ya veta el ensanchamiento (D3). [R3, R4]
- [ ] 2.4 Añadir al puerto `list(tenant_id, *, filters, page, per_page)` y un objeto `Page` propio del módulo, siguiendo `app/reservations/domain/repositories.py:48-53` — no hay helper de paginación compartido, cada dominio declara el suyo. [R1]
- [ ] 2.5 Test de dominio que afirme que el puerto **no** expone ningún método capaz de escribir `current_operational_state` más allá de `save`, para que un ensanchamiento futuro falle aquí y no en revisión. [R4]

## 3. Infraestructura: escritores y lectura paginada

- [ ] 3.1 Implementar `add` en `backend/app/properties/infrastructure/repositories.py` con la guarda `CrossTenantWriteError` como **primeras** sentencias (patrón de `SqlAlchemyPropertyStateTransitionRepository.add:149-154`), el `flush()`, y `try/except IntegrityError` traduciendo **por nombre de constraint** a `DuplicateInternalCodeError` / `DuplicatePmsExternalIdError`, re-lanzando cualquier otro `IntegrityError` — patrón exacto de `SqlAlchemyReservationRepository.add:151-162`. El secreto se escribe desde el parámetro `wifi_secret.ciphertext`, nunca desde la entidad. [R2, R5]
- [ ] 3.2 Test de integración contra Postgres real que viole `uq_properties_tenant_id_internal_code` **de verdad** y afirme `DuplicateInternalCodeError`; ídem para el índice parcial de `pms_external_id`, incluyendo el caso de control de que **dos propiedades con `pms_external_id = NULL` sí conviven** (es lo que el parcial concede y lo que un índice total rompería). [R2]
- [ ] 3.3 Implementar `update_details` con guarda de tenant post-hoc por `rowcount` (patrón de `set_pms_provider:132-141`, donde «no existe» y «es de otro» son deliberadamente indistinguibles) y un `UPDATE` acotado a las claves recibidas. Test de que una clave fuera de la allowlist no llega a SQL. [R3, R4]
- [ ] 3.4 Implementar `set_wifi_password` recibiendo `EncryptedSecret | None`, con la misma guarda. Test de que pasar `None` borra el valor y que el ciphertext almacenado no es el texto en claro. [R5]
- [ ] 3.5 Implementar `list` contando sobre la **misma** sentencia filtrada y aplicando `.limit/.offset`, con orden estable de dos claves `name` + `id` (patrón de `app/reservations/infrastructure/repositories.py:69-89,197-203`). Test de que paginar no repite ni omite filas. [R1]
- [ ] 3.6 Test de aislamiento por tenant sobre los cuatro métodos nuevos, con **dos** tenants sembrados — un test de aislamiento sin nada que fallar en alcanzar no prueba nada (`tests/reservations/conftest.py:6`). [R7]

## 4. Auditoría

- [ ] 4.1 Añadir `ENTITY_PROPERTY = "PROPERTY"` a `ENTITY_TYPES` y `PROPERTY_CREATED` / `PROPERTY_UPDATED` a `ACTIONS` en `backend/app/audit/domain/actions.py:49-65`. Sin esto `AuditLogFactory.build` lanza. [R7]
- [ ] 4.2 Añadir la entrada `"PROPERTY"` a `AUDITABLE_FIELDS` en `backend/app/audit/domain/value_objects.py:74-106`, enumerando las columnas auditables **incluido `wifi_password_encrypted`** para que `.redacted()` lo acepte — precedente `PMS_CREDENTIAL` (`:97-105`). Nota: `REDACTED_FIELDS:41-42` ya contiene `wifi_password` y `wifi_password_encrypted`, así que `.diff()` sobre ellos ya revienta sin tocar nada. [R5, R7]
- [ ] 4.3 Test que afirme que `ChangeSet("PROPERTY").diff("wifi_password_encrypted", ...)` **lanza** y que `.redacted("wifi_password_encrypted")` produce `{"changed": true}`; ídem para los tres campos de texto libre (`access_notes`, `cleaning_notes`, `emergency_notes`). [R5, R7]

## 5. Permisos (D12)

- [ ] 5.1 Añadir `READ_PROPERTIES` y `MANAGE_PROPERTIES` al enum `Permission` de `backend/app/auth/domain/policy.py:14-33`, y sus frozensets `_PROPERTY_READ` / `_PROPERTY_MANAGE` (manage **incluye** read, como `_RESERVATION_MANAGE`). [R6]
- [ ] 5.2 Actualizar `ROLE_PERMISSIONS` (`:55-65`): lectura para `TENANT_OWNER` y `PROPERTY_MANAGER`, mutación **solo** para `PROPERTY_MANAGER`; `SUPER_ADMIN`, `CLEANER` y `TECHNICIAN` sin ninguno. Dejar en un comentario la razón de D12 y su consecuencia asumida (la propietaria no da de alta su propia vivienda). [R6]

## 6. Casos de uso

- [ ] 6.1 Crear los cuatro casos de uso en `backend/app/properties/application/use_cases.py`, junto al `AdvancePropertyStatesUseCase` existente, recibiendo puertos por constructor y `_AuditWriter` como en `app/auth/application/user_admin.py:58-88`. Recordar que `application/` no puede importar `sqlalchemy` ni `fastapi` ni la `infrastructure` del propio dominio (`tests/test_layering.py:28,144-166`). [R1, R2, R3]
- [ ] 6.2 En el alta: cifrar con `app.core.crypto.encrypt()`, hacer `add()` —que **flushea**— y solo **después** construir el `AuditLog`, para que un `409` no deje rastro de una creación que no ocurrió (patrón de `CreateUserUseCase:133-134`, docstring `:116-119`). Un `commit()` exactamente una vez. Test del orden: un duplicado no escribe fila en `audit_logs`. [R2, R5, R7]
- [ ] 6.3 En el `PATCH`: construir el diccionario `written` campo a campo y usarlo para decidir **a la vez** qué se persiste y qué se audita; si está vacío, devolver sin escribir fila ni `AuditLog` (patrón de `UpdateUserUseCase:228-267`). La acción se elige a partir de `written`, no de la petición. Test del `PATCH` que no cambia nada. [R3, R7]
- [ ] 6.4 Test de que ningún caso de uso puede alterar `current_operational_state`, y de que crear una propiedad **no** escribe fila en `property_state_transitions` ni ningún `TimelineEvent` — no existe tipo `PROPERTY_CREATED` en `app/timeline/domain/enums.py` y PRD §3.1:101 ata el evento a la *transición*. [R4]

## 7. Capa API y cableado

- [ ] 7.1 Crear `backend/app/properties/api/schemas.py`: petición con `model_config = ConfigDict(extra="forbid")`, respuesta con campos enumerados y `from_domain` explícito (nunca `from_attributes`, convención de `reservations/api/schemas.py:9-11`), **sin `wifi_password_encrypted`** y con `has_wifi_password: bool` en su lugar. Cotas `MAX_PER_PAGE = 100`, `MAX_PAGE = 100_000` y una cota de texto explícita para las cuatro columnas `String` sin longitud. `PropertyPageResponse.build` propio del módulo. [R1, R2, R5]
- [ ] 7.2 Añadir al esquema de `PATCH` el validador `_reject_explicit_nulls` de `app/auth/api/user_schemas.py:105-128` con la lista `NULLABLE_FIELDS` de D9, y la constante `PATCHABLE` importada de la capa de aplicación para que la regla viva en un solo sitio (`user_schemas.py:133-141`). Test de que `PATCH {"name": null}` da `422` y que `PATCH {"city": null}` sí borra. [R3, R4]
- [ ] 7.3 Crear `backend/app/properties/api/errors.py` con `_MAPPING` (subclases antes que sus bases), `http_error_for` con fallback `(500, INTERNAL_ERROR)` y supresión del mensaje en el 500, y `register_property_error_handlers` — copiando `app/tenants/api/errors.py`, que es la instancia completa más pequeña. Sin códigos nuevos: 404/409/422 ya están en `ErrorCode`. [R2, R7]
- [ ] 7.4 Crear `backend/app/properties/api/dependencies.py` con un builder por caso de uso, construyendo los adaptadores en línea con `SqlAlchemyUnitOfWork` de `app/core/unit_of_work.py` y `SqlAlchemyAuditLogRepository`, siguiendo `app/reservations/api/dependencies.py`. [R1, R2, R3]
- [ ] 7.5 Crear `backend/app/properties/api/router.py` con `responses=AUTHENTICATED_RESPONSES` (`app/core/openapi.py:67`), `ReadDep`/`ManageDep` sobre `require(...)` como alias de módulo, los cuatro endpoints de PRD §23 con `summary` **y `description`** (lo exige `steering/documentation.md`, y es el hallazgo que `cleaning` tiene abierto por omitirlo), y `201` en el alta. Nada de lógica en el router. [R1, R2, R3, R6]
- [ ] 7.6 Cablear en `backend/app/main.py`: `register_property_error_handlers(app)` en el bloque `:46-50` e `include_router(properties_router, prefix=API_V1_PREFIX)` en `:51-58`. [R1]
- [ ] 7.7 Ampliar el snapshot de `backend/tests/test_route_authorization.py:256-278` con `/api/v1/properties` y `/api/v1/properties/{property_id}` — es un snapshot a propósito para que toda ruta nueva aparezca en el diff. [R6]
- [ ] 7.8 Crear `backend/tests/properties/test_authorization.py` con la matriz por endpoint × los cinco roles, afirmando el **código concreto** y no `!= 403`, escrita a mano y no derivada de `ROLE_PERMISSIONS` («una tabla calculada estaría de acuerdo con cualquier error en él», `tests/reservations/test_authorization.py:4-5`). Incluir el test de que las cuatro rutas dan `401` sin token, y el de que un `403` no revela si el recurso existe (mismo cuerpo para un id real y uno inventado). [R6, R7]
- [ ] 7.9 Crear `backend/tests/properties/conftest.py` reutilizando por import las fixtures de `tests/auth/conftest.py` (`tenant_a`, `tenant_b`, `users_by_role_a`, `users_by_role_b`, `utc_now`) en vez de re-sembrarlas, como hace `tests/reservations/conftest.py:26-33`. [R7]
- [ ] 7.10 Test de que el `404` cross-tenant tiene cuerpo **indistinguible** del de un id inventado, y de que la autorización se decide **antes** de consultar el recurso. [R1, R7]
- [ ] 7.11 Test de que ninguna respuesta de la capacidad contiene `wifi_password` ni `wifi_password_encrypted` ni credencial de PMS alguna, recorriendo el cuerpo serializado y no solo el esquema declarado. [R5]

## 8. Guarda de propiedad `INACTIVE` en reservas (D11)

Sección aparte porque es la única que toca una capability ajena y archivada; su alcance debe quedar visible en el diff y en la revisión.

- [ ] 8.1 Añadir en `backend/app/reservations/application/use_cases.py` la guarda que rechaza crear una reserva sobre una propiedad con `status = INACTIVE`, con un error de dominio propio de `reservations` y su fila en el `_MAPPING` de ese módulo. [R3]
- [ ] 8.2 Cubrir **las tres vías de entrada**, no solo la API: creación manual, import CSV (`app/integrations/application/use_cases.py`, resuelve por `internal_code`) y `pms_sync` (resuelve por `pms_external_id`) — ninguna de las tres mira hoy el `status`. Un test por vía. [R3]
- [ ] 8.3 Correr la suite completa de `tests/reservations/` **sin modificarla** y confirmar que sigue en verde: la guarda es una condición añadida, no un cambio de las existentes. [R3]

## 9. Contrato y documentación

- [ ] 9.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo en el mismo PR — lo exige el workflow `api-contract` y `tests/test_openapi_contract.py:233-235`. [R7]
- [ ] 9.2 Regenerar `frontend/lib/api/generated/openapi.d.ts` con `npm run api:generate` y confirmar `npm run api:check` en verde, o el workflow `frontend-api-contract` sale en rojo. [R7]
- [ ] 9.3 Confirmar que los contadores de la guarda de modelos de respuesta de `api-contract.md:97-99` (al menos 18 rutas y 5 prefijos) han crecido y que ninguna ruta nueva queda sin `response_model`. [R7]
- [ ] 9.4 Actualizar `README.md:180`: mover `properties` a la lista de dominios con las cuatro capas — hoy dice que «`auth`, `reservations`, `integrations` y `tenants` son los únicos con las cuatro, y `properties`/`notifications` ganaron `application/` con los jobs programados», y eso deja de ser cierto. [R7]
- [ ] 9.5 Añadir a `README.md` (sección «Entrar en la aplicación», tras el párrafo de administración del tenant en `:122-124`) los endpoints de propiedades con enlace a su página de `docs/`, siguiendo el formato de los dos párrafos vecinos. [R7]
- [ ] 9.6 Crear `docs/properties.md` orientada a **cómo se usa y se opera** (dar de alta una vivienda, qué rol puede hacerlo y por qué, cómo se retira con `status`, qué pasa con la contraseña de wifi y por qué no se puede leer de vuelta, y qué rastro deja en `audit_logs`), sin duplicar los criterios EARS y enlazando a la spec. [R7]
- [ ] 9.7 Comprobar si `docs/diagrams/2026-08-06_autohost-er-entidades.png` queda obsoleto. Se genera desde la metadata de SQLAlchemy y refleja entidades y relaciones (28 y 67), no índices — así que un índice único parcial **no debería** cambiarlo. Verificarlo regenerando y comparando; si no cambia, no tocar nada y anotarlo. [R7]

## 10. Verificación

`sdd/project.md` no registra comando de lint ni de typecheck para el backend, y no existe ninguno: `backend/pyproject.toml` declara como dev deps solo `pytest`, `pytest-asyncio` y `pytest-cov` — sin ruff, mypy ni pyright. Lo que CI corre en su lugar es `alembic check` y la reversibilidad de las migraciones, así que eso es lo que se verifica aquí.

- [ ] 10.1 Suite completa en verde: `docker compose exec backend uv run pytest` (con el stack levantado; con el stack parado, `docker compose run --rm backend uv run pytest`). Registrar el conteo de passed/skipped. [R1-R7]
- [ ] 10.2 `docker compose exec backend uv run alembic check` — los modelos coinciden con el esquema migrado. [R2]
- [ ] 10.3 Reversibilidad: `alembic downgrade base` y de vuelta `alembic upgrade head`, que es lo que corre `backend-tests.yml:295-300`. [R2]
- [ ] 10.4 Comprobación manual de extremo a extremo contra el stack real, que es lo que este change existe para desbloquear: `make up`, `make bootstrap`, login como el `PROPERTY_MANAGER` sembrado, `POST /api/v1/properties`, y después **`POST /api/v1/reservations` sobre esa propiedad devolviendo `201`** — hoy devuelve `404` en todas las peticiones. Confirmar además que el `GET` de la propiedad no trae la contraseña de wifi y que el mismo `POST` como `TENANT_OWNER` da `403`. [R1, R2, R5, R6]
- [ ] 10.5 Confirmar que `pms_credentials` sigue siendo solo de CLI: ninguna ruta nueva lo lee ni lo escribe, y `python -m app.integrations.cli.pms_credentials` sigue siendo la única vía. [R5]
