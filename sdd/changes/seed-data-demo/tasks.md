# Tasks: seed-data-demo

Orden pensado para que el sistema siga en pie tras cada sección: la 1 sólo añade
configuración inerte y un comando que aún no escribe; de la 2 a la 6 cada sección deja el
comando funcionando con una porción más del dataset; la 7 cierra el contrato de consola y el
aislamiento; la 8 documenta.

Los valores del dataset salen de PRD §27 (líneas 2167-2288) y §7.10 (líneas 644-687), y las
decisiones que citan las tareas están en `design.md`.

## 1. Configuración y contrato de entrada <!-- panel: SKIPPED (config/scaffolding) 2026-08-12 -->

- [x] 1.1 Añadir los seis campos del seed a `backend/app/core/config.py`, con default `""`,
  inmediatamente tras el bloque `bootstrap_*` (línea 298): `seed_cleaner_name`,
  `seed_cleaner_email`, `seed_cleaner_password`, `seed_technician_name`,
  `seed_technician_email`, `seed_technician_password`. Ampliar
  `backend/tests/test_config.py` con una aserción análoga a
  `test_bootstrap_credentials_have_no_defaults` (línea 449) para
  `SEED_CLEANER_PASSWORD`/`SEED_TECHNICIAN_PASSWORD`: limpia las dos del entorno con
  `monkeypatch.delenv` y comprueba que quedan en `""`, porque la ausencia de default es la
  propiedad bajo prueba y un `.env` del desarrollador la falsearía. Los nombres acaban en
  `_password`, así que quedan dentro del patrón que ya redacta el manejo de errores de
  `_load_settings` (`config.py:410-429`) — verificar que sigue siendo cierto para estos dos.
  [R3.2]

- [x] 1.2 Añadir el bloque `SEED_*` a `.env.example` justo después del bloque `BOOTSTRAP_*`
  (línea 307), las seis variables **vacías**, con un comentario en la forma del bloque vecino:
  que son contraseñas de personas, que no hay defaults en el árbol (`steering/security.md`
  regla 8), y que `make seed-demo` falla antes de escribir hasta que se rellenen. [R3.2, R6.2]

- [x] 1.3 Crear `backend/app/cli/seed_demo.py` con el esqueleto de `bootstrap.py`: docstring
  que diga qué es y que **presupone** `make bootstrap`, excepciones propias
  (`SeedConfigurationError`, `SeedPreconditionError`, `SeedConflictError`) y `build_plan()`
  que valide las seis variables **antes de abrir cualquier transacción**, reportando **todas**
  las ausentes de una vez y contando el blanco como ausencia — igual que
  `bootstrap.build_plan` (líneas 55-97). Normalizar los dos correos con `normalize_email`.
  Añadir `main()` con el mapa de códigos de salida de D11 (0 sembrado o nada que hacer, 1 para
  las cuatro condiciones de aborto) imprimiendo a `stderr` un mensaje que nombre lo que falta.
  Tests en el nuevo `backend/tests/cli/test_seed_demo.py` (con su `__init__.py`), modelados
  sobre `backend/tests/auth/test_bootstrap.py`: un `COMPLETE_ENV` con las seis, un test
  parametrizado por variable ausente y uno de sólo-espacios, **ninguno de los dos tocando la
  base de datos**. [R1.5, R3.3, D1, D11]

- [x] 1.4 Añadir el target `seed-demo` al `Makefile` junto a `bootstrap` (línea 131) y a la
  lista `.PHONY` (línea 30), como
  `$(COMPOSE) exec backend python -m app.cli.seed_demo`, con el comentario que explique que
  **no** cuelga de `up` (mismo motivo que `bootstrap`: DoD §28.20) y que exige `bootstrap`
  antes. `python -m` y no `uv run`, por el motivo que ya documenta el comentario de
  `bootstrap` (`uv` sólo existe en la etapa dev de la imagen). [R1.1]

## 2. Precondiciones: el tenant y los dos actores que ya existen <!-- panel: PASS 2026-08-12 (con la 3) -->

- [x] 2.1 En `seed_demo.py`, escribir `run()` y el arranque de `apply_plan(session, ...)`:
  `import app.core.models_registry` por su efecto colateral (`pms_sync.py:37`; sin él falla la
  resolución de claves ajenas), y resolver el tenant por `settings.bootstrap_tenant_name`
  con un `select(TenantModel)` **sin sesión marcada todavía**, exactamente como
  `bootstrap.apply_plan:105-107` — el orden importa y es al revés que en `pms_sync`, que busca
  el tenant *por id* y por eso puede marcar primero. Si no existe, abortar con código 1 y un
  mensaje que nombre `make bootstrap`, **sin haber escrito nada** (la lectura precede a
  cualquier escritura y sin `commit` no queda nada). Con el tenant resuelto, llamar
  `bind_session_to_tenant(session, tenant_id)` (`backend/app/core/db.py:132`) antes de cualquier
  otra consulta, y construir el `SqlAlchemyUnitOfWork(session)` que cerrará la transacción.
  Test: sin tenant, `apply_plan` levanta la excepción de precondición y el recuento de filas de
  todas las tablas implicadas no cambia. [R1.3, D12]

- [x] 2.2 Resolver el `TENANT_OWNER` y el `PROPERTY_MANAGER` del tenant **por rol** (vía
  `SqlAlchemyUserRepository.list` con `UserFilters(role=...)`), nunca por los correos de §27 —
  el motivo, y su consecuencia para la documentación, están en D4. Si falta cualquiera de los
  dos, abortar con código 1 y la misma explicación que R1.3. Guardar el `id` del owner como el
  único `actor_user_id` de toda la ejecución (D5). Tests: falta el owner → aborto sin escribir;
  falta el manager → aborto sin escribir; con los dos presentes, el actor elegido es el owner.
  [R3.1, D4, D5]

## 3. Las dos cuentas nuevas (`CLEANER` y `TECHNICIAN`) <!-- panel: PASS 2026-08-12 -->

- [x] 3.1 Crear las dos cuentas con `User.create(..., must_change_password=False)` seguido de
  `SqlAlchemyUserRepository.add(tenant_id, user)`, hasheando con `BcryptPasswordHasher(rounds=settings.bcrypt_rounds)`
  como `bootstrap`. `User.create` acuña su propio `id`, fuerza `status=ACTIVE` y exige el correo
  **ya normalizado** (lo hace `build_plan`, tarea 1.3); por el puerto se conservan las tres
  guardas que un `session.add` se salta: `UnassignableRoleError` (`GRANTABLE_ROLES`),
  `CrossTenantWriteError` y la traducción de `uq_users_lower_email` a `EmailAlreadyExistsError`.
  **Nunca `CreateUserUseCase`** (genera la contraseña y marca el flag) ni
  `session.add(UserModel(...))` — el razonamiento completo en D3. Idempotencia por correo
  normalizado vía `find_by_email_globally`, **ejecutado antes de `bind_session_to_tenant`** (ver la
  enmienda del 2026-08-12 en D11: con la sesión marcada esa consulta deja de ser global y R3.6 se
  vuelve incomprobable): si existe y es de este tenant, dejarla **intacta,
  incluida su contraseña**; si existe en **otro** tenant, abortar con código 1 y un mensaje que
  explique el conflicto y que los correos son únicos en toda la instalación (el índice
  `uq_users_lower_email` rechazaría el `INSERT` de todos modos: la comprobación existe por el
  mensaje, no por el invariante). Tests en `test_seed_demo.py`: las dos cuentas nacen con
  `must_change_password` en falso y con el rol correcto; una segunda ejecución no crea filas ni
  cambia el `password_hash` existente; un correo dado de alta en otro tenant aborta.
  [R3.1, R3.2, R3.4, R3.5, R3.6, D3]

- [x] 3.2 Escribir la fila de `AuditLog` del alta de cada cuenta nueva:
  `AuditLogFactory.build(tenant_id=..., action=USER_CREATED, entity_type=ENTITY_USER,
  entity_id=user.id, actor_user_id=<owner de D5>, actor_ip=None, changes=..., now=...)` —
  `USER_CREATED` y `ENTITY_USER` son constantes de módulo en
  `backend/app/audit/domain/actions.py`, no miembros de un `Enum`. El `ChangeSet` se construye
  como el de `CreateUserUseCase`: `ChangeSet("USER").diff("email", None, email).diff("role",
  None, role).redacted("password")` — **`redacted` y no `diff` para la contraseña**, porque
  `password` está en `REDACTED_FIELDS` y `diff()` levanta excepción sobre ella
  (`value_objects.py:29`, `:357`). Persistir con `SqlAlchemyAuditLogRepository.add(tenant_id,
  entry)` (es el único método de escritura; no hay `save`) **dentro de la misma transacción**.
  Es la única asignación de rol de la ejecución, y `steering/security.md` regla 9 la exige.
  Tests: una fila por cuenta creada, el `ChangeSet` guarda la contraseña como marcador redactado
  y no en claro, y una segunda ejecución no añade ninguna. [D6]

## 4. Las dos propiedades <!-- panel: PASS 2026-08-12 (con la 5 y la 6) -->

- [x] 4.1 Crear `Redes 11`/`REDES11` y `Pajaritos 8`/`PAJARITOS8` invocando
  `CreatePropertyUseCase` con el actor de D5 y los valores de §27 (`address_line1`, `city` y
  `province` de Madrid, `max_guests` 4 y 2, `bedrooms` 2 y 1, `bathrooms` 1 y 1,
  `default_check_in_time` 15:00, `default_check_out_time` 11:00). `country="ES"` y
  `timezone="Europe/Madrid"` ya son los defaults del comando y coinciden con §27, así que no hay
  que pasarlos; §27 no da `postal_code`, y se queda en `None`. **No pasar ni escribir
  `current_operational_state`** —`CreatePropertyCommand` no tiene ese campo *a propósito*
  (`property_admin.py:18`, `:68-69`), así que ambas toman el default del DDL `VACANT_READY` y el
  estado queda donde `PropertyStateMachine` lo gobierna. Tampoco pasar `pms_external_id`: OQ1 lo
  resolvió con un NO. Idempotencia por `internal_code`
  (`PropertyRepository.find_by_internal_code`): si ya hay una con ese código, dejarla intacta y
  no crear una segunda. Ninguna escritura directa en la tabla `properties`. Tests: las dos
  nacen en `VACANT_READY`; una segunda ejecución no crea una tercera; los valores de §27 quedan
  persistidos tal cual. [R2.1, R2.2, R2.3, R2.4]

## 5. Las tres reservas y sus huéspedes <!-- panel: PASS 2026-08-12 -->

- [x] 5.1 La reserva `DIRECT` de Pedro López (hoy−10 → hoy−7): crear primero el huésped con
  `Guest(...)` + `SqlAlchemyGuestRepository.add(tenant_id, guest)` en la misma sesión, con la
  forma exacta de `ReservationIngestor._link_guest` (`ingest.py:277`), y después invocar
  `CreateReservationUseCase` con `external_channel_id="SEED-DIRECT-1"`. El orden importa: `add`
  hace `flush` y el `commit` del caso de uso cierra las dos escrituras, así que si la reserva
  falla el huésped se va con el rollback (D8). **No asignar `status`**: nace en el estado por
  defecto de su agregado — `CreateReservationCommand` **no tiene campo `status`**, así que R4.4
  se cumple por construcción en esta vía, no por disciplina. `DIRECT` sí está en
  `MANUAL_CHANNELS` (`use_cases.py:45`), que es por lo que esta reserva puede ir por aquí y las
  otras dos no. Idempotencia por `external_channel_id`, buscado en
  `ReservationRepository.list` filtrado por la propiedad — no por propiedad+fechas, que es la
  letra de R4.6 pero crea un duplicado cada día (D9). Tests: la reserva nace en el estado por
  defecto y no en `COMPLETED`; el huésped queda vinculado con nombre; una segunda ejecución no
  crea un duplicado ni mueve las fechas. [R4.1, R4.3, R4.4, R4.5, R4.6, D8, D9]

- [x] 5.2 Las dos reservas OTA por `ReservationIngestor`: construir dos `ReservationDTO`
  (`backend/app/integrations/domain/dtos.py:25`) con los datos de §27 — `AIRBNB`, John Smith
  `<john.smith@example.com>`, hoy−2 → hoy+1, 2 adultos, `gross_amount` 350.00 y
  `ota_commission` 52.50; y `BOOKING`, María García `<maria.garcia@example.com>`, hoy+3 → hoy+7,
  3 adultos. Ojo a tres nombres, porque el DTO no se llama como la tabla: el identificador
  estable va en **`external_id`** (`SEED-AIRBNB-1` / `SEED-BOOKING-1`) — es el ingestor quien lo
  persiste como `external_pms_id`—, la propiedad se nombra en **`property_external_id`**
  (`REDES11`, que es lo que lee el resolver), y **no hay campo `net_amount`**: los 297,50 € de
  §27 son gross − comisión, derivados. Pasarlos a `ReservationIngestor.ingest(...)` con
  `resolve_property` buscando por `internal_code` (el mismo resolver que
  `ImportReservationsFromCsvUseCase`, `use_cases.py:656`), `source="seed"`, y el `actor_type` /
  `actor_user_id` del owner de D5. Las dos van a `REDES11` conforme a §27. **Dejar `status` del
  DTO en `None`**: aquí sí existe el campo, así que R4.4 depende de no rellenarlo — es el punto
  en el que una siembra descuidada plantaría `CHECKED_IN_ESTIMATED` a mano. El ingestor **no
  hace `commit`** (no recibe `uow`): cierra la transacción el `SqlAlchemyUnitOfWork` del seed.
  **El seed comprueba él mismo las claves con `find_by_external_pms_id` y no entrega al ingestor
  las filas que ya existen** — la idempotencia del ingestor es *actualizar* lo conocido, y
  delegar en ella modificaría las fechas en una segunda siembra, que es justo lo que R1.2
  prohíbe (D9). **Y comprobar el `IngestReport` que devuelve**: `ingest` no levanta excepción por
  una fila mala, la cuenta en `skipped`/`errors` (`ingest.py:147-160`), así que el seed debe
  fallar en voz alta si vuelve con `skipped > 0` o con errores, en lugar de imprimir un recuento
  que dice que sembró. No usar `MockPMSAdapter`: las cuatro razones están en D7. Tests: las dos
  quedan con su `external_pms_id` y su canal OTA, nacen en el estado por defecto, los dos
  huéspedes quedan registrados con nombre y correo, una segunda ejecución **no modifica las
  fechas** de ninguna de las dos, y un informe con filas saltadas hace fallar el comando.
  [R4.2, R4.3, R4.4, R4.5, R4.6, D7, D9]

## 6. La plantilla de checklist del tenant <!-- panel: PASS 2026-08-12 -->

- [x] 6.1 Crear la plantilla por defecto de §7.10 invocando `CreateChecklistTemplateUseCase`,
  aplicable a **ambas** propiedades (sin `property_id`, que es cómo el esquema expresa
  «todo el tenant»), con los 18 items (`ventilate` … `upload_photos`) y las 6 fotos
  (`living_room`, `bedroom`, `bathroom`, `kitchen`, `entrance`, `damage_if_found`), todos con
  `required: true` **explícito** —`parse_template_content` lo toma como `False` si falta
  (`value_objects.py:255`) y exige un `bool` de verdad, `1` no vale. Escribirlos con la forma que
  `parse_template_content` (`backend/app/cleaning/domain/value_objects.py:216`) acepta
  —`{item_id, label, required}` y `{photo_type, label, required}`— y **no** con la de §7.10 (que
  dibuja `id`/`label_es`/`label_en`/`order`): la divergencia está declarada en D10, la etiqueta
  va en **español** (el `default_language` del tenant) y el orden de §7.10 es el orden de la
  lista. Los 18 identificadores de §7.10 pasan `KEY_PATTERN` y caben de sobra en `MAX_ITEMS`
  (200) y `MAX_REQUIRED_PHOTOS` (50). Sembrar sólo si el tenant no tiene ninguna
  (`CleaningChecklistTemplateRepository.list(tenant_id, page=1, per_page=1)` y su
  `TemplatePage.total > 0` ⇒ no crear otra). Tests: se crea una
  con los 18 items y las 6 fotos y pasa la validación del value object; con una plantilla
  preexistente no se crea ninguna. [R5.1, R5.2, D10]

## 7. Contrato de consola, idempotencia global y aislamiento <!-- panel: PASS 2026-08-12 -->

- [x] 7.1 Cerrar `main()`: imprimir **únicamente** recuentos por tipo de entidad creada y, como
  mucho, identificadores — nunca contraseñas, hashes ni tokens. Una segunda ejecución imprime
  todos los recuentos a cero y sale con 0. Tests: capturar la salida de una siembra completa y
  comprobar que **ninguna** de las contraseñas de `COMPLETE_ENV` aparece en ella (ni en `stdout`
  ni en `stderr`), que hay un recuento por tipo, y que una segunda ejecución sale 0 dejando
  idéntico el recuento de filas de todas las tablas tocadas. [R1.1, R1.2, R1.4, D11]

- [x] 7.2 Test de aislamiento de tenant sobre todo lo que el seed escribe — usuarios,
  propiedades, huéspedes, reservas, plantilla, `AuditLog` y `TimelineEvent`: todo lleva el
  `tenant_id` del tenant sembrado y nada de ello es visible desde un segundo tenant. Obligatorio
  por `steering/testing.md` (DoD §28.18) y `steering/security.md` regla 1. [R1.1, regla 1 de
  `steering/security.md`]

## 8. Documentación <!-- panel: PASS 2026-08-12 -->

- [x] 8.1 `README.md` §«Entrar en la aplicación» (línea 106): añadir `make seed-demo` como
  tercer paso tras `make up` → `make bootstrap`, con la precondición de R1.3 (exige un tenant
  ya creado, y falla antes de escribir si no lo hay) y el enlace a `docs/seed-demo.md`. Decir en
  voz alta la consecuencia de D4: los correos de §27 para el owner y el manager son **lo que
  pongas en tu `.env`**, no algo que el comando imponga. [R6.1]

- [x] 8.2 Crear `docs/seed-demo.md` y añadir su entrada al índice de `docs/README.md`: el
  dataset que siembra, las credenciales de §27 como *lo que pones en tu `.env`* (D4), la nota de
  **envejecimiento** de D9 —un entorno sembrado hace semanas enseña una reserva «activa» que ya
  terminó, y `seed-demo` no lo arregla— con la receta para empezar de cero
  (`docker compose down -v` → `bootstrap` → `seed-demo`), y la nota de deriva con el fixture del
  `MockPMSAdapter` (contiene otra versión de las mismas reservas de §27, ya divergente en
  `adults`) para que quien lea las dos no crea que una está mal. [R6.3]

## 9. Verification

- [x] 9.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest`
  (con el stack parado, `docker compose run --rm backend uv run pytest`).
- [x] 9.2 Levantar el stack de este worktree —`make up`, que además resuelve la entrada de
  `BLOCKED.md`— y ejecutar el camino completo de verdad: `make bootstrap` y luego
  `make seed-demo`. Esto es lo único que verifica D12 (`models_registry` y
  `bind_session_to_tenant`): **ningún test unitario detecta la ausencia de ninguna de las dos**.
  Comprobar la salida: recuentos por tipo, ninguna contraseña.
- [x] 9.3 Ejecutar `make seed-demo` una segunda vez: salida con todos los recuentos a cero,
  código de salida 0, y ninguna fila nueva ni modificada (contrastar con el MCP `postgres` o
  `make sh`). [R1.2]
- [x] 9.4 Comprobar los tres abortos contra el stack real: `make seed-demo` con una variable
  `SEED_*` vacía (lista todas las ausentes, no escribe), con un `BOOTSTRAP_TENANT_NAME` que no
  existe (nombra `make bootstrap`, no escribe), y sobre una base sin correr `bootstrap`.
  [R1.3, R1.5]
- [x] 9.5 Confirmar que el esquema no cambió: `docker compose exec backend uv run alembic check`
  no propone ninguna migración.
- [ ] 9.6 `make down` al terminar el change, **antes** de borrar el worktree — **única casilla
  deliberadamente sin marcar**: el stack sigue arriba y sembrado porque `/sdd:review` lo necesita
  para correr la suite y para comprobar el comando contra la base real. Se baja **después** del
  merge y antes de borrar el worktree, no ahora.
  (`sdd/project.md` §«Stacks huérfanos»), y borrar la entrada resuelta de `BLOCKED.md`.

**Lo que esta sección deliberadamente no incluye**, para que su ausencia no se lea como un
olvido: no hay `make openapi` ni `cd frontend && npm run api:check` porque el change no añade
ningún endpoint ni cambia la forma de ninguna respuesta; no hay claves de `locales/` porque no
hay UI; y no hay paso de lint/typecheck de backend porque el proyecto no tiene ninguno
configurado (ni en `backend/pyproject.toml` ni en `.github/workflows/backend-tests.yml`) —
inventar un comando aquí violaría la regla 9 compartida.

## Cobertura de requisitos

| Requisito | Tareas |
|---|---|
| R1.1 | 1.4, 7.1, 7.2, 9.2 |
| R1.2 | 7.1, 9.3 |
| R1.3 | 2.1, 8.1, 9.4 |
| R1.4 | 7.1 |
| R1.5 | 1.3, 9.4 |
| R2.1 – R2.4 | 4.1 |
| R3.1 | 2.2, 3.1 |
| R3.2 | 1.1, 1.2, 3.1 |
| R3.3 | 1.3 |
| R3.4, R3.5, R3.6 | 3.1 |
| R4.1, R4.3 – R4.6 | 5.1 |
| R4.2 – R4.6 | 5.2 |
| R5.1, R5.2 | 6.1 |
| R6.1 | 8.1 |
| R6.2 | 1.1, 1.2 |
| R6.3 | 8.2 |
