# Tasks: reservation-property-identity

> Cada tarea lleva el test que introduce la regla (`sdd/steering/testing.md`
> §"Cada tarea de implementación incluye su test"). Las pruebas de pin, de
> aislamiento y de N+1 viven en su propia sección porque son **la** garantía
> estructural de R5.3 / R5.4 / D3 y necesitan acceso a dos tenants vecinos —
> mismo patrón que `tests/cleaning/test_task_context_read_model.py` y
> `tests/cleaning/test_batch_reader.py`.

## 1. Puerto de propiedades — `list_for_ids` (D2)

- [x] 1.1 Añadir `async def list_for_ids(self, tenant_id, property_ids) -> Sequence[Property]`
      al puerto `PropertyRepository` en `backend/app/properties/domain/repositories.py`,
      con docstring simétrica a la de `GuestRepository.list_for_ids`
      (`backend/app/guests/domain/repositories.py:32`): mismo contrato
      (`Sequence` disperso por `id`, ausencia en lugar de `None`, batch con
      `tenant_id` explícito por consulta, lote vacío sin `IN ()`). [R5.1, R5.2]
- [x] 1.2 TDD: tests del adaptador en `backend/tests/properties/test_list_for_ids.py`
      — lote vacío no consulta (`count_statements` con `tests/sql_counter.py`,
      mismo filo que `tests/cleaning/test_batch_reader.py:22`); lote con ids
      del mismo tenant devuelve cada propiedad; id de otro tenant queda
      **ausente** del mapa (no `None`, no excepción); id inexistente queda
      ausente; ids `None`/duplicados se descartan sin error. Implementar
      `SqlAlchemyPropertyRepository.list_for_ids` en
      `backend/app/properties/infrastructure/repositories.py` con un único
      `SELECT ... WHERE tenant_id = :tenant_id AND id = ANY(:ids)` y verificar
      que la suite queda verde. [R5.1, R5.2]

## 2. Casos de uso — composición por lotes (D1, D3, D4)

- [x] 2.1 Extender el dataclass `ReservationDetail` en
      `backend/app/reservations/application/use_cases.py:95` con dos campos
      opcionales nuevos: `property_name: str | None = None` y
      `property_internal_code: str | None = None`. Sin dataclass congelado
      nuevo — D1 fija que la garantía estructural del conjunto de campos
      derivados vive en el test de pin, no en una clase intermedia. [R2.1, R2.2]
- [x] 2.2 `GetReservationUseCase` (`use_cases.py:356`) acepta `properties` en
      el constructor; tras `reservations.get`, llama
      `properties.get(tenant_id, reservation.property_id)` y pobla los dos
      campos en `ReservationDetail` (dejando `property_name` y
      `property_internal_code` a `None` cuando la `Property` no resuelve en el
      tenant — D5). TDD: tests en `backend/tests/reservations/test_use_cases.py`
      cubriendo happy path, FK a otro tenant (`None` con clave, sin `404`), y
      reserva sin huésped (`guest_full_name` se poblará en 2.3, pero el camino
      del detalle no debe romperse). [R2.1, R2.2]
- [x] 2.3 `ListReservationsUseCase` (`use_cases.py:378`) acepta `properties` y
      `guests` en el constructor; tras `reservations.list`, agrupa los
      `property_id` y `guest_id` no nulos de la página en dos sets, llama una
      vez a `properties.list_for_ids(tenant_id, property_ids)` y otra a
      `guests.list_for_ids(tenant_id, guest_ids)`, y mapea en memoria por
      `id` — un ausente → `None` con su clave. Los `None`/id de otro tenant se
      ignoran antes de la llamada (un `set` con un `None` revienta). TDD:
      ampliar `backend/tests/reservations/test_use_cases.py` con lista de N
      reservas con dos `property_id` distintos y un `guest_id` ausente, y
      asertar que los tres campos derivados se poblan para las que resuelven
      y quedan `None` para las que no. [R1.1, R1.2, R3.1, R3.2, R3.3, R5.1, R5.2]

## 3. API — DTOs y wiring (D1, D8)

- [x] 3.1 Añadir `property_name: str | None = None`,
      `property_internal_code: str | None = None` y `guest_full_name: str | None = None`
      a `ReservationResponse` en `backend/app/reservations/api/schemas.py:119`;
      propagar los tres campos en `from_domain` (leyéndolos del
      `Reservation`/de la `Property`/`GuestSummary` ya resueltos por el use
      case — el DTO no consulta, el use case sí). [R1.1, R1.3, R3.1]
- [x] 3.2 Propagar los tres campos en `ReservationDetailResponse.from_detail`
      (`schemas.py:181`); la clase hereda de `ReservationResponse` y
      `from_detail` ya deserializa `base.model_dump()`, así que basta con
      asegurar que el `from_domain` los lleva y verificarlo. TDD: tests en
      `backend/tests/reservations/test_api.py` — `GET /reservations` y
      `GET /reservations/{id}` exponen los tres campos cuando resuelven, los
      exponen como `null` con su clave cuando no resuelven (R1.2/R2.2/R3.3/R4.2),
      y el resto de la reserva (los 27 actuales) no se altera. [R1.1, R1.2,
      R1.3, R2.1, R2.2, R3.1, R3.2, R3.3, R4.1, R4.2]
- [x] 3.3 Cablear `SqlAlchemyPropertyRepository(session)` en
      `backend/app/reservations/api/dependencies.py`: pasarlo a
      `get_list_reservations_use_case` y a `get_reservation_use_case`. El
      router (`backend/app/reservations/api/router.py:48`) sigue declarando
      `require(Permission.READ_RESERVATIONS)` — sin nueva ruta, sin nuevo
      permiso, sin tocar `backend/app/auth/domain/policy.py`. TDD: el test
      de R6.3 vive en `backend/tests/reservations/test_authorization.py` —
      ampliarlo para que un `CLEANER` siga recibiendo `403` y un token de
      huésped `401` aunque el cuerpo pida `property_name`; el suite de
      `test_api_authorization.py` de mantenimiento cubre el patrón. [R6.1,
      R6.2, R6.3]

## 4. Tests estructurales — pin, aislamiento y N+1 (D3, D5, D6, D7)

- [x] 4.1 `backend/tests/reservations/test_response_identity_fields.py` —
      **test de pin del conjunto de campos derivados** (R5.4, D6). Dos
      aserciones duras: (a) `ReservationResponse` y `ReservationDetailResponse`
      declaran **exactamente** los tres campos nuevos (`property_name`,
      `property_internal_code`, `guest_full_name`) además de los que ya
      tienen — parametrizar uno a uno los nombres de campos adyacentes de
      `Property` que **no** deben entrar (`address_line1`, `address_line2`,
      `city`, `province`, `postal_code`, `country`, `timezone`, `wifi_name`,
      `has_wifi_password`, `wifi_password_encrypted`, `access_notes`,
      `cleaning_notes`, `emergency_notes`, `max_guests`, `bedrooms`,
      `bathrooms`, `default_check_in_time`, `default_check_out_time`,
      `pms_provider`, `pms_external_id`, `current_operational_state`, `status`)
      y los de `GuestSummary` que **no** deben entrar (`email`, `phone`,
      `preferred_language`, `document_status`,
      `legal_registration_status`), igual que
      `backend/tests/cleaning/test_task_context_read_model.py:40-69`. Asertar
      también que `property_id` y `guest_id` siguen presentes — R1.3 / R3.1
      dicen "se añaden, no se sustituyen". [R1.3, R3.1, R5.4, R6.1]
- [x] 4.2 `backend/tests/reservations/test_identity_isolation.py` —
      **aislamiento por tenant con dos vecinos reales** (R5.3, D7). Usar
      `tenant_a`/`tenant_b`/`users_by_role_a`/`property_a`/`property_b` (ya
      en `backend/tests/reservations/conftest.py:26,71,84`) y sembrar
      además un `guest_b` en tenant B. Construir una `Reservation` en
      tenant A con `property_id` apuntando a `property_b` y otra con
      `guest_id` apuntando a `guest_b`. Asertar, sobre la respuesta de
      `GET /reservations` y `GET /reservations/{id}` con token de tenant A,
      que los tres campos derivados son `null` con su clave y que el resto
      de los 27 campos actuales sí se devuelve — sin `5xx`, sin `404`. [R1.2,
      R2.2, R3.3, R4.2, R5.2, R5.3]
- [x] 4.3 `backend/tests/reservations/test_list_identity_queries.py` —
      **techo constante de `SELECT`s** (D3, análogo a `dashboard-api`
      "Composición por lotes"). Con una página de N=10 reservas distintas,
      contar las sentencias que tocan `reservations`, `properties` y
      `guests` con `tests/sql_counter.count_statements` y asertar que la
      suma es **independiente de N** (un `list` + un `list_for_ids` por
      repositorio, no N+1). Cubrir también el caso de una página donde
      todas las reservas tienen `guest_id` `None` (sin llamada a
      `guests.list_for_ids`) y donde todas comparten `property_id` (la
      deduplicación del set mantiene una sola lectura a `properties`). [R5.1,
      R5.2]

## 5. Regeneración del contrato publicado (D8, regla 1 de `sdd/steering/documentation.md`)

- [x] 5.1 Regenerar `backend/openapi.json` con `make openapi` y commitearlo
      en este PR — el workflow `api-contract` falla en rojo si no
      corresponde al código. [R1.1, R1.2, R1.3, R2.1, R2.2, R3.1, R3.2, R3.3,
      R4.1, R4.2]
- [x] 5.2 Regenerar `frontend/lib/api/generated/openapi.d.ts` con el
      workaround del worktree descrito en `sdd/project.md` "Worktree bootstrap":
      `docker compose exec -T frontend mkdir -p /backend`,
      `docker compose cp backend/openapi.json frontend:/backend/openapi.json`,
      `docker compose exec -T frontend ln -sfn /app /frontend`,
      `docker compose exec -T frontend npm run api:generate`. Commitear el
      `.d.ts` regenerado junto al `openapi.json` — son las dos mitades del
      mismo puente y `frontend-api-contract` falla si una se queda atrás. [R1.1,
      R1.2, R1.3, R2.1, R2.2, R3.1, R3.2, R3.3, R4.1, R4.2]

## 6. Specs

- [x] 6.1 Añadir a `sdd/specs/reservations.md` la sección "Identidad legible
      de la vivienda y del huésped" con los SHALL R1, R2, R3, R4 (lista y
      detalle exponen `property_name`, `property_internal_code` y
      `guest_full_name`; los tres campos son `null` con su clave cuando el
      FK no resuelve en el tenant; los ids se conservan), y modificar la
      sección de "Consulta y listado" para que cite los tres campos
      derivados y el criterio de D5 ("degradación parcial, no `404`"). [R1.1,
      R1.2, R1.3, R2.1, R2.2, R3.1, R3.2, R3.3, R4.1, R4.2, R5.1, R5.2]

## 7. Verification

> Comandos verbatim de `sdd/project.md`. Las cifras se miden, no se
> comparan contra un número escrito aquí — `pricing-web` (2026-08-23)
> descubrió que el «63 ficheros, 415 tests» que figuraba en
> `project.md` era de varios changes atrás. Mide contra lo que dé tu
> `pytest` de partida.

- [x] 7.1 Suite backend completa en verde:
      `docker compose exec backend uv run pytest`. Incluye
      `backend/tests/reservations/` (los cuatro nuevos + los existentes),
      `backend/tests/properties/test_list_for_ids.py`, `backend/tests/cleaning/`
      y `backend/tests/maintenance/` (la regresión de los dos precedentes que
      comparten el patrón de `list_for_ids`), y el resto de la suite. [R1-R6]
- [x] 7.2 `cd frontend && npm run api:check` en verde con el `.d.ts`
      regenerado en 5.2 — el `tsc --noEmit` no atrapa un campo añadido, así
      que esta línea es por la **ausencia** de deriva, no por la propagación
      (lo deja dicho la regla 1 de `sdd/steering/documentation.md`). [R1-R6]
