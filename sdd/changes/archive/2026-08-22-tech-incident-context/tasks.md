# Tasks: tech-incident-context

Orden pensado para que el sistema quede funcionando al final de cada sección: primero la columna
nueva (invisible hasta que alguien la escriba), luego su escritor, luego el refactor del
acotamiento por fila, y sólo entonces la proyección que lo lee todo. El contrato publicado se
regenera **una vez**, al final, porque tres secciones lo tocan.

Aviso que arrastra el design (D10) y `sdd/project.md` §Worktree bootstrap: **`cd frontend && npm
run api:check` no funciona desde un worktree enlazado**. La salida verificada está en la sección
Verification y hay que usar ésa, no el comando literal del steering.

## 1. La columna `assignment_note` y su migración <!-- panel: PASS 2026-08-21 -->

- [x] 1.1 Añadir `assignment_note: str | None = None` a la entidad `Incident`
  (`backend/app/maintenance/domain/entities.py`), sin tocar la tabla de transiciones ni
  `_check_transition`. Test en `backend/tests/maintenance/test_entities.py`: una incidencia recién
  construida la tiene a `None`. [R3.1]
- [x] 1.2 Añadir la columna al modelo: `assignment_note: Mapped[str | None] =
  mapped_column(String(2000), default=None)` en
  `backend/app/maintenance/infrastructure/models.py`. Test en
  `backend/tests/maintenance/test_models.py`: la columna existe, es nullable y `type.length == 2000`
  — el ancho vive en el DDL y no sólo en pydantic (D6). [R3.1]
- [x] 1.3 Migración de Alembic nueva en `backend/alembic/versions/<rev>_incident_assignment_note.py`
  con `down_revision = 'e7a3c419d82b'` (cabeza verificada: `guest_portal_api`, doce migraciones).
  `ADD COLUMN` nullable **sin** default de servidor y sin backfill; `downgrade` la borra.
  **No escribir en el fichero de migración quién escribe la columna** —
  `backend/tests/test_rule11_ownership.py` barre `backend/alembic/versions/` y se pone en rojo ante
  una atribución fuera de la tabla del censo. [R3.1]
- [x] 1.4 Llevar la columna a `add`/`save` y a la rehidratación en
  `backend/app/maintenance/infrastructure/repositories.py`. Test en
  `backend/tests/maintenance/test_repositories.py`: un `save` con nota y un `get` posterior la
  devuelven; un `save` con `None` la deja a `NULL`. [R3.1]
- [x] 1.5 Verificar que `backend/tests/test_migrations.py` sigue verde — en particular
  `test_the_models_match_the_migrations` (el modelo y la migración coinciden) y
  `test_the_revisions_can_be_reapplied_after_a_downgrade` (upgrade → downgrade → upgrade). [R3.1]

## 2. `assign` acepta la nota, y nada más cambia <!-- panel: PASS 2026-08-21 -->

- [x] 2.1 `Incident.assign` (`backend/app/maintenance/domain/entities.py`) gana el parámetro
  `assignment_note: str | None = None` y lo escribe **siempre**: enviarla la fija, no enviarla la
  deja a `None` (D7 — la nota pertenece a la asignación vigente). Tests en
  `backend/tests/maintenance/test_entities.py`: reasignar sin nota **borra** la anterior; reasignar
  con nota la sustituye; la tabla de transiciones no cambia. [R3.1]
- [x] 2.2 `AssignIncidentUseCase.execute` (`backend/app/maintenance/application/use_cases.py`) gana
  el parámetro opcional y lo pasa a `incident.assign`. Sin tocar la resolución del técnico dentro
  del tenant ni la cancelación del deadline de SLA. Tests en
  `backend/tests/maintenance/test_use_cases.py`. [R3.2]
- [x] 2.3 `MAX_ASSIGNMENT_NOTE = 2000` y el campo opcional en `AssignIncidentRequest`
  (`backend/app/maintenance/api/schemas.py`), manteniendo
  `model_config = ConfigDict(extra="forbid")`. El router (`incidents_router.py`) lo reenvía al caso
  de uso; el permiso sigue siendo `MANAGE_INCIDENTS` (`ManageDep`). Tests en
  `backend/tests/maintenance/test_api_incidents.py`: se acepta ausente, se acepta presente, 2001
  caracteres dan `422`, y una clave desconocida sigue dando `422`. [R3.2]
- [x] 2.4 Comprobar que `IncidentResponse` **no** gana la nota y que el listado paginado no cambia:
  aserción del conjunto exacto de claves del cuerpo de `GET /incidents/{id}` y de un item de
  `GET /incidents` en `backend/tests/maintenance/test_api_incidents.py`. [R3.3]
- [x] 2.5 Comprobar que la asignación sigue escribiendo el mismo `AuditLog` (los dos `diff` de
  `assigned_technician_id` y `status`) y el mismo `TimelineEvent` (título constante, `metadata` con
  sólo identificadores), sin que el texto de la nota viaje a ninguno de los dos. Aserciones en
  `backend/tests/maintenance/test_use_cases.py`. [R3.6]
- [x] 2.6 Verificar que `app/cli/seed_demo.py` sigue verde sin cambios: no pasa nota, así que el
  dataset de demo queda con `assignment_note` a `NULL` (consecuencia asumida en D7). Correr
  `backend/tests/cli/`. [R3.1]

## 3. Las dos exclusiones de la nota, estructurales por ausencia del allowlist <!-- panel: n/a 2026-08-21 — sección de sólo tests, ningún fichero de producción -->

- [x] 3.1 Confirmar que `assignment_note` **no** entra en `AUDITABLE_FIELDS["INCIDENT"]` (sigue con
  sus once campos) ni en `REDACTED_FIELDS`, y añadir en
  `backend/tests/maintenance/test_free_text_sink_contract.py` la aserción de que nombrarla en un
  `ChangeSet` de `INCIDENT` levanta `AuditContractError` — el mismo mecanismo que ya excluye
  `title`/`description`. [R3.5]
- [x] 3.2 `SINK_COLUMNS` pasa de `("title", "description")` a incluir `"assignment_note"` en
  `backend/tests/maintenance/test_free_text_sink_contract.py`, y el barrido AST queda verde: el
  único escritor es `AssignIncidentUseCase` a través de `Incident.assign`. Si el barrido señala un
  módulo más, es un escritor real y necesita fila propia del censo — no se silencia. [R3.5]
- [x] 3.3 Aserción de que el `TimelineEvent` de la asignación lleva el conjunto **exacto** de claves
  de `metadata` (`incident_id`, `technician_id`) y que la nota no está entre ellas
  (`backend/tests/maintenance/test_free_text_sink_contract.py`). [R3.6]

## 4. El acotamiento por fila, escrito una sola vez <!-- panel: PASS 2026-08-21 -->

- [x] 4.1 Extraer a `backend/app/maintenance/application/use_cases.py` la corrutina de módulo
  `_load_incident_in_scope(incidents, tenant_id, incident_id, actor) -> Incident`: carga dentro del
  tenant, `IncidentNotFoundError` si no existe, y `IncidentNotFoundError` si
  `actor.restrict_to_technician_id` no coincide con `assigned_technician_id`. Docstring con el
  motivo del `404` indistinguible. [R4.2, R4.3, R4.4]
- [x] 4.2 Hacer que `_IncidentTransitionMixin._load_incident` y `GetIncidentUseCase.execute` la
  usen, borrando las dos copias. Correr **antes y después** la suite completa de `maintenance`
  (`backend/tests/maintenance/`), que es lo que cubre las doce rutas vivas, y en particular
  `test_api_authorization.py`. [R4.2, R4.3]
- [x] 4.3 Test propio de la corrutina en `backend/tests/maintenance/test_use_cases.py`: técnico
  asignado la obtiene; técnico no asignado, incidencia inexistente e incidencia de otro tenant dan
  la **misma** excepción con el mismo mensaje; para `PROPERTY_MANAGER` y `TENANT_OWNER`
  `restrict_to_technician_id` es `None` y no acota. [R4.2, R4.3, R4.4]

## 5. La proyección `GET /incidents/{incident_id}/context` <!-- panel: PASS 2026-08-21 -->

- [x] 5.1 `backend/app/maintenance/domain/read_models.py` **nuevo**: dataclass congelado
  `IncidentContext` con los once campos de D4 (`property_name`, `property_internal_code`,
  `address_line1`, `address_line2`, `city`, `province`, `postal_code`, `country`, `timezone`,
  `access_notes`, `assignment_note`). Python puro — ni pydantic ni SQLAlchemy, que es lo que
  `backend/tests/test_layering.py` obliga. Docstring que enumera por qué la lista está cerrada y qué
  exclusiones dependen de que siga cerrada, **sin atribuir escritor a ninguna columna del censo** (lo
  caza `backend/tests/test_rule11_ownership.py`, que barre `backend/app/`). El docstring hereda
  literal la regla de `cleaner-task-context`: **una proyección puede estrechar, nunca unir** — un
  campo que un permiso guarda como un todo pasa por la D10 de `dashboard-api`.
  [R1.1, R1.2, R2.1, R5.1, R5.5]
- [x] 5.2 `backend/tests/maintenance/test_incident_context_read_model.py` **nuevo**, calcado de
  `backend/tests/cleaning/test_task_context_read_model.py`: el conjunto **exacto** de campos del
  dataclass es esos once, y el dataclass es `frozen`. Añadir uno tiene que ser un acto deliberado.
  [R1.4, R5.1]
- [x] 5.3 `GetIncidentContextUseCase` en `backend/app/maintenance/application/use_cases.py`:
  `_load_incident_in_scope(...)` y luego `properties.get(tenant_id, incident.property_id)`. **Dos
  sentencias**, cada una con su `tenant_id` explícito, ningún `JOIN` ni reader propio (D2). Si la
  propiedad no resuelve dentro del tenant: `logger.warning` con `tenant_id`, `incident_id` y
  `property_id`, y `IncidentNotFoundError` — nunca respuesta parcial. [R1.5, R4.4, R4.5, R5.3]
- [x] 5.4 `backend/tests/maintenance/test_incident_context_use_case.py` **nuevo**: los once campos se
  componen de las dos filas; la propiedad colgante (incidencia del tenant A apuntando a una
  propiedad del tenant B) da `IncidentNotFoundError` y **no** una respuesta parcial, y deja el
  `warning`; se cuentan las consultas y son dos (o menos en los caminos que acaban en `404`), usando
  `backend/tests/sql_counter.py`. [R1.5, R4.4, R4.6]
- [x] 5.5 `IncidentContextResponse` en `backend/app/maintenance/api/schemas.py`: espejo campo a campo
  de `IncidentContext` con `from_attributes=True`. Nunca se serializa `Property` ni `Reservation`.
  [R1.1, R1.2, R5.1]
- [x] 5.6 `get_incident_context_use_case` en `backend/app/maintenance/api/dependencies.py` con
  `SqlAlchemyIncidentRepository` + `SqlAlchemyPropertyRepository` (ambos ya construidos en
  `_flow_kwargs`; no hace falta puerto ni adaptador nuevo). [R1.1]
- [x] 5.7 La ruta `GET /{incident_id}/context` en
  `backend/app/maintenance/api/incidents_router.py` con `ReadDep`
  (`require(Permission.READ_INCIDENTS)` — **sin permiso nuevo**),
  `response_model=IncidentContextResponse`, `responses=_INCIDENT_CONTEXT_RESPONSES` (el `404` con
  `ErrorEnvelope` y código `NOT_FOUND`, calcado de `_CONTEXT_RESPONSES` de
  `cleaning/api/tasks_router.py`) y la `description` de D10 con sus tres afirmaciones: el conjunto
  visible depende del rol persistido del token y ningún parámetro lo ensancha; qué significa cada
  `null`; y que `assignment_note` es la nota de la asignación **vigente** y se sustituye en cada
  reasignación. Actualizar el docstring del módulo (once rutas → doce). [R4.1, R6.2, R6.3]
- [x] 5.8 `backend/tests/maintenance/test_incident_context_api.py` **nuevo**. Cubre, sobre el
  **cuerpo serializado** y no sobre la entidad:
  - conjunto **exacto** de claves de la respuesta `200` (los once campos, ni uno más) [R1.4, R5.2, R5.3, R5.4]
  - un campo `NULL` en origen viaja como `null` **con su clave**, no omitido [R1.3]
  - `wifi_password_encrypted`, `has_wifi_password`, `cleaning_notes` y `emergency_notes` no aparecen [R2.5, R5.2]
  - ningún campo de reserva ni `reported_by_guest_token`/`reported_by_user_id`/`ai_classification` [R5.3, R5.4]
  - técnico asignado → `200`; técnico no asignado, incidencia inexistente, incidencia de otro tenant
    y propiedad que no resuelve dentro del tenant → `404` con cuerpo **idéntico** en los cuatro [R4.4]
  - `PROPERTY_MANAGER` y `TENANT_OWNER` ven el contexto de cualquier incidencia de su tenant [R4.3]
  - un llamante sin `READ_INCIDENTS` recibe `403` (el rol `CLEANER` no lo tiene) y un token de
    huésped no pasa la puerta [R4.1, R4.7]
  - ningún esquema de esta ruta acepta `tenant_id` [R4.5]

  Ojo al escribir el test de aislamiento: sobre una sesión marcada no puede fallar — usar la sesión
  sin marcar, como el resto de tests de tenancy del repo.

## 6. `access_notes` sale del listado de propiedades (la forma de la regla 11 que D5 decide) <!-- panel: PASS 2026-08-21 -->

- [x] 6.1 `PropertyListItemResponse` en `backend/app/properties/api/schemas.py`: el mismo conjunto de
  campos que `PropertyResponse` **menos las tres notas** (`access_notes`, `cleaning_notes`,
  `emergency_notes`), con su `from_domain` enumerado. `PropertyPageResponse.data` pasa a
  `list[PropertyListItemResponse]`. `PropertyResponse` (el detalle) no cambia. [R2.3]
- [x] 6.2 Tests en `backend/tests/properties/test_api.py`: un item de `GET /api/v1/properties` no
  lleva ninguna de las tres notas (aserción del conjunto exacto de claves), y
  `GET /api/v1/properties/{id}` sigue llevándolas. [R2.3]
- [x] 6.3 Comprobar que ningún otro sitio de `backend/app/` consume `PropertyPageResponse.data`
  esperando el tipo antiguo, y que el portal del huésped sigue devolviendo `arrival_notes` sin
  cambios (`backend/app/guests/`). [R2.3]

## 7. El censo de la regla 11 en `sdd/steering/security.md` <!-- panel: PASS 2026-08-22 -->

- [x] 7.1 Fila nueva para `properties.access_notes` en la tabla de sumideros, con forma
  **excepción 6** y con **todos** sus escritores y lectores efectivos de hoy — incluido el portal del
  huésped, que ya la devuelve verbatim como `arrival_notes` a un portador anónimo. La tabla dice
  quién escribe cada columna *hoy*, no sólo lo que este change añade. [R2.2]
- [x] 7.2 Redactar la **excepción 6** debajo de la tabla, con el mismo formato que las cinco
  anteriores: qué concede (un valor de la regla 3 que **sí** fuimos a buscar — es lo que la separa de
  la 3), su precio (la salida del listado paginado y el aviso al operador), y los tres «lo que NO
  concede»: no se propaga (sigue `redacted()`, fuera de `AUDITABLE_FIELDS["PROPERTY"]` y fuera del
  `metadata` de cualquier `TimelineEvent`), no autoriza a un escritor nuestro, y no convierte la
  columna en sitio seguro para PII. [R2.2, R2.3]
- [x] 7.3 Fila nueva para `incidents.assignment_note` con forma **excepción 3**, y **ensanchar el
  enunciado de la excepción 3** para nombrarla junto a `owner_approvals.response_notes` y
  `messages.content` del manager — en vez de abrir una séptima por parecido, que es lo que el
  steering dice literalmente que no se hace. [R3.4]
- [x] 7.4 Actualizar los recuentos del bloque de cabecera de la sección: dieciocho → **veinte**
  columnas, veintitrés → **veinticinco** filas, y la frase «**Las excepciones son cuatro**», que ya
  estaba desfasada con cinco y pasa a seis. [R2.2, R3.4]
- [x] 7.5 Correr `backend/tests/test_rule11_ownership.py` en verde: la atribución de las dos columnas
  nuevas vive **sólo** en esta tabla y en ningún docstring, spec, nota de roadmap ni fichero de
  migración. [R2.2, R3.4]
- [x] 7.6 Verificar que D12 del design deja escrito, completo, **por qué** este change no cubre
  `properties.cleaning_notes`, `properties.emergency_notes` ni `access_records.notes`, y que dice
  además qué sí les llega (salen del listado, pero no entran en el censo). Es el texto que
  `/sdd:archive` traslada a `sdd/specs/tech-incident-context.md`. [R2.4]

## 8. El contrato publicado <!-- panel: PASS 2026-08-22 -->

- [x] 8.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo: la operación nueva con su
  esquema de respuesta enumerado campo a campo, el `404` con el sobre de error de PRD §23 y el código
  `NOT_FOUND`, el campo opcional de `assign`, y los items del listado de propiedades sin las tres
  notas. [R6.1, R6.2, R6.4]
- [x] 8.2 Regenerar y commitear `frontend/lib/api/generated/openapi.d.ts` — **desde un worktree
  enlazado el comando documentado no funciona**; usar la salida verificada de `sdd/project.md`:
  ```bash
  docker compose exec -T frontend mkdir -p /backend
  docker compose cp backend/openapi.json frontend:/backend/openapi.json
  docker compose exec -T frontend ln -sfn /app /frontend
  docker compose exec -T frontend npm run api:generate
  ```
  [R6.1]
- [x] 8.3 `backend/tests/test_openapi_contract.py` en verde, en particular
  `test_the_committed_contract_matches_the_code`, `test_every_api_route_declares_a_response_model` y
  `test_every_documented_error_response_references_the_envelope`. [R6.1, R6.2]

## 9. Documentación y lo aplazado con nombre <!-- panel: PASS 2026-08-22 -->

- [x] 9.1 `docs/maintenance.md`: la pantalla del técnico (qué ve y de dónde sale), el aviso al
  operador de que **lo que escriba en las instrucciones de acceso se le enseña al técnico verbatim**
  —igual que ya se le enseña al huésped, `docs/guest-portal.md`— y que la nota de asignación se
  **sustituye** en cada reasignación (D7). Redactarlo **sin atribuir escritor a una columna del
  censo**: `backend/tests/test_rule11_ownership.py` barre `docs/` y exige los dos ejes. [R2.1, R3.2]
- [x] 9.2 `docs/properties.md`: las tres notas salen del listado y siguen en el detalle, con el motivo
  (la regla 4 aplicada por la regla 11). Mismo cuidado con la atribución. [R2.3]
- [x] 9.3 Entrada nueva `plaintext-sink-encryption-at-rest` en `sdd/roadmap.md` — `[TECH]`, junto a
  `audit-changes-repository-guard` y `validation-error-loc-redaction`, con su sub-línea de metadatos
  (`size: M · kind: tech`) — y su nota larga en
  `sdd/roadmap/plaintext-sink-encryption-at-rest.md`: cifrado en reposo de las cuatro columnas
  (`properties.access_notes`, `cleaning_notes`, `emergency_notes`, `access_records.notes`), la
  amenaza que cubre (lectura offline de la base, de un backup o de una réplica), y por qué se rechazó
  pagarla aquí (OQ1). Es lo que el design encarga para que no quede como deuda tácita.
- [x] 9.4 La nota de `sdd/roadmap/cleaner-app.md` deja de describir la decisión de la regla 11 como
  pendiente **en su totalidad**: `properties.access_notes` ya está decidida (excepción 6 + salida del
  listado) y la mitad de cifrado en reposo pasa a citar `plaintext-sink-encryption-at-rest`.
  `access_records.notes` sigue siendo suya.
- [x] 9.5 `README.md` de raíz: comprobar que no hay nada que actualizar — este change no añade módulo,
  ni comando de Makefile, ni cambia la estructura de carpetas. Dejar constancia de la comprobación,
  no del cambio.
  - **Comprobado el 2026-08-22 y no hay nada que cambiar.** El §Estructura describe `maintenance`
    con sus **dos routers** (`/incidents` y `/owner-approvals`) y el motivo de que sean dos (dos
    agregados); este change añade una ruta **dentro** de `/incidents`, así que el recuento que el
    README publica sigue siendo correcto — no enumera rutas. No hay dominio nuevo (siguen 17), ni
    target de `Makefile` nuevo, ni carpeta nueva fuera de `backend/app/maintenance/domain/`, que
    el README no enumera fichero a fichero. Las variables de entorno no cambian, así que
    `.env.example` tampoco.

## 10. Verification <!-- panel: PASS 2026-08-22 -->

- [x] 10.1 Suite completa del backend en verde desde el worktree:
  `docker compose exec backend uv run pytest` (con el stack parado,
  `docker compose run --rm backend uv run pytest`). [todos]
- [x] 10.2 Migración probada de ida y vuelta sobre una base sembrada: `upgrade` → `downgrade` →
  `upgrade`, verificando que `ADD COLUMN ... NULL` no falla con datos existentes. [R3.1]
- [x] 10.3 Contrato sin deriva: `make openapi` no deja `backend/openapi.json` modificado, y la
  regeneración del artefacto del frontend (comando de 8.2) tampoco deja
  `frontend/lib/api/generated/openapi.d.ts` modificado. [R6.1]
- [x] 10.4 Typecheck del frontend contra los tipos derivados, para confirmar que quitar las tres notas
  del listado no rompe ningún consumidor (verificado en el design: las cuatro apariciones de
  `access_notes` en `frontend/` están todas en el artefacto generado). [R2.3]
- [x] 10.5 Recorrido manual del flujo con el stack levantado (`make up PORT_OFFSET=<n>` si hace falta
  navegador): un `PROPERTY_MANAGER` asigna una incidencia con nota; el `TECHNICIAN` asignado llama a
  `GET /api/v1/incidents/{id}/context` y recibe los once campos; otro técnico recibe `404`; el
  `CLEANER` recibe `403`; una reasignación sin nota deja el campo a `null`. [R1, R3, R4]
