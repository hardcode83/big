# Design: reservation-property-identity

## Context

`ReservationResponse` (`backend/app/reservations/api/schemas.py:119`) tiene 27 campos. La maqueta de Stitch del 2026-08-23 destapó que dos de los que la UI quiere pintar no son atributos propios: la columna Property enseña `{row.propertyId}` y la columna Guest `{row.guestId ?? "—"}` (`frontend/features/reservations/data/dto.ts:76`, `reservations-view.tsx:156-159`), porque el contrato solo expone los UUID.

El mismo problema y la misma forma ya los resolvieron `cleaner-task-context` (entregado 2026-08-21) y `tech-incident-context`: `CleaningTaskResponse` e `IncidentResponse` devolvían `property_id` pelado, y la solución en ambos casos fue **resolver el contexto en el servidor**, sin un endpoint hermano. La diferencia con los dos es que aquí el rol ya tiene `READ_RESERVATIONS` y la respuesta de lista/detalle, así que el contexto cabe en ese mismo contrato —mismo principio de `dashboard-api` D2 (composición por `tenant_id` explícito, no `JOIN` conjunto), sin una segunda ruta.

`GuestRepository.list_for_ids` ya existe con la forma de batch que `dashboard-api` R1.7 fija (`backend/app/guests/domain/repositories.py:32`). `PropertyRepository` no tiene todavía su batch reader — ese es el cambio de puerto que este design introduce, simétrico al de guests. El `GuestSummary` que devuelve el batch ya excluye los datos de documento (R1.8, D17) por construcción, así que el `guest_full_name` no abre la puerta que un volcado de la entidad habría abierto.

## Decisions

### D1 — Composición en los casos de uso, no en los response models

**Chosen:** la resolución corre en `ListReservationsUseCase` y en `GetReservationUseCase`, orquestando un `PropertyRepository` (ya conocido por `CreateReservationUseCase`) y un `GuestRepository` (ya conocido por `GetReservationUseCase`). Las clases de respuesta siguen con `from_domain`/`from_detail` campo a campo, sin nuevos dataclasses congelados. Es la forma que `cleaner-task-context` y `tech-incident-context` ya prefijaron, y R5.4 ("fijar el conjunto de campos derivados con un test propio") se cumple con un test que enumera los tres campos derivados sobre `ReservationResponse` directamente.

Rejected: un `ReservationListItemContext` (frozen dataclass en `domain/read_models.py`) y un `ReservationListItemContextResponse` que lo espeje. Es el patrón literal de `cleaning` y `maintenance`, pero allí la ruta era **nueva** y necesitaba la garantía estructural de que ningún campo no enumerado aterrizara. Aquí la ruta ya existe con su contrato vivo; el riesgo no es la ruta nueva, es **ampliar la existente**, y la garantía estructural más natural es un test que fija la diferencia de conjuntos (los tres derivados contra los que añadirían un campo nuevo).

### D2 — `PropertyRepository.list_for_ids` se añade al puerto (simétrico al de guests)

**Chosen:** una nueva firma `async def list_for_ids(tenant_id, property_ids) -> Sequence[Property]`, declarada en `backend/app/properties/domain/repositories.py` y resuelta en `backend/app/properties/infrastructure/repositories.py` con un único `SELECT ... WHERE tenant_id = :tenant_id AND id = ANY(:ids)`. Devuelve un `Sequence` disperso por `id` —una propiedad que no resuelve en el tenant está **ausente** del mapa, no mapeada a `None`— mismo contrato que `GuestRepository.list_for_ids` (`backend/app/guests/domain/repositories.py:44`).

Rejected: una llamada por fila con `for rid in page: await properties.get(...)`. Es el N+1 que `dashboard-api` "Composición por lotes" cierra a aserto de techo constante, y que `cleaner-task-context` y `tech-incident-context` miden en sus tests con `n_statements`.

Rejected: hacer el `JOIN` dentro de `SqlAlchemyReservationRepository.list`, ensanchando su firma. Sería el segundo sitio donde se escribe el scope de tenant — la forma exacta que `dashboard-api` D2 y `guest-portal-api` (panel de seguridad) rechazaron, y la grieta que esta capability nunca debería abrir.

### D3 — Lista y detalle resuelven en lotes, no en serie

**Chosen:** `ListReservationsUseCase` recibe la página del repo de reservas, agrupa los `property_id` no nulos y los `guest_id` no nulos en dos sets, llama una sola vez a `properties.list_for_ids` y otra a `guests.list_for_ids`, y mapea en memoria por `id`. Mismo techo constante de `dashboard-api`: dos lecturas extra por página de reservas, no una por fila.

Rejected: reutilizar `ListReservationsUseCase.execute` como `for res in result.items: enrich(res)`. Aunque el `if` de "no resuelve" del D5 convertiría las lecturas no resueltas en `None`, la cuenta de sentencias crece con la página y rompe la cláusula de `dashboard-api` "Composición por lotes" (las cards del dashboard lo miden con un test). El mismo cambio en batch cuesta las dos llamadas extra y un test de aislamiento que ya se necesita.

### D4 — El `guest_full_name` se toma del `GuestSummary` ya existente, no de la entidad `Guest`

**Chosen:** el `GuestRepository.get(tenant_id, id)` (que ya usaba `GetReservationUseCase` y devuelve `GuestSummary` por construcción) alimenta `guest_full_name` con `summary.full_name`. El batch reader, simétrico, devuelve `Sequence[GuestSummary]`. La proyección excluye los datos de documento y los PII de contacto (`email`, `phone`, `preferred_language`, `document_status`, `legal_registration_status`) **por construcción** — un campo que `GuestSummary` no tiene no tiene dónde aterrizar.

Rejected: tomar `full_name` de la entidad `Guest` y excluir el resto campo a campo en la respuesta. Es la receta que R1.8 cerró (`backend/app/reservations/api/schemas.py:95-116` y `GuestSummary` docstring, "no `document_number_encrypted` por construcción"), y aplicarla a `guest_full_name` separadamente reintroduciría la dependencia que el dataclass congelado vino a quitar.

### D5 — Cruce de tenant degrada la respuesta parcialmente, no a `404`

**Chosen:** una reserva cuya `property_id` (o `guest_id`) apunta a otro tenant —o a una fila inexistente dentro del tenant— deja `property_name`, `property_internal_code` y `guest_full_name` como `null` con su clave, y el resto de la reserva (`check_in_date`, `gross_amount`, `channel`, etc.) se sigue devolviendo. La fila de la reserva resuelve; lo que falla es su FK. Mismo criterio que `cleaner-task-context` aplica a su reserva colgante.

**Asimetría `property_id` / `guest_id` que la implementación ya recogió y el proposal ahora declara**: la FK de `reservations.guest_id` es compuesta (`fk_reservations_guest_within_tenant`, `backend/app/reservations/infrastructure/models.py:53-58`, añadida por `guest-portal-api` en Alembic `e7a3c419d82b`), así que un cruce de tenant por `guest_id` es **estructuralmente imposible** en disco. El caso "no hay fila" y "fila de otro tenant" colapsan al mismo en la capa de aplicación, y la degradación a `null` con clave los cubre por construcción. El test `backend/tests/reservations/test_identity_isolation.py` ejerce el cruce por `property_id` (cubrible) y documenta la asimetría — no hay un test cruzado por `guest_id` porque ningún INSERT lo producirá; `BLOCKED.md` ya no lo lleva porque esta nota lo cierra.

Rejected: `404` cuando el `property_id` no resuelve en el tenant. Es la forma de `tech-incident-context` (`backend/app/maintenance/api/schemas.py` §"Lo que la proyección nunca lleva"), válida allí porque la propiedad alimenta diez de los once campos de `IncidentContext`; aquí alimenta tres de treinta y la entidad principal es la reserva, no la propiedad. Un `404` por una FK cruzada sería mentir sobre la entidad principal: una reserva que sí responde a `GET /reservations/{id}` no debería desaparecer porque la propiedad esté en otro tenant.

Rejected: omitir las tres claves cuando no resuelven. La forma `null` con su clave es deliberada (R1.2, R2.2, R3.2, R4.2; `sdd/specs/cleaner-task-context.md` §"La proyección: a qué propiedad va la limpiadora" — *"un campo que no está en el dataclass no tiene dónde aterrizar"*). Una clave que aparece y desaparece según el estado del FK es en sí misma un canal de información, y el test del body serializado del D6 lo fija.

### D6 — El conjunto de campos derivados se fija con un test de pin (R5.4)

**Chosen:** un test `backend/tests/reservations/test_response_identity_fields.py` que:
- Enumera **exactamente** los tres campos derivados sobre `ReservationResponse` y `ReservationDetailResponse`: `property_name`, `property_internal_code`, `guest_full_name`.
- Lista los nombres de campos adyacentes de `Property` (`address_line1`…`country`, `timezone`, `wifi_name`, `has_wifi_password`, `access_notes`, `cleaning_notes`, `emergency_notes`, `max_guests`, `bedrooms`, `bathrooms`, `default_check_in_time`, `default_check_out_time`, `pms_provider`, `pms_external_id`, `current_operational_state`, `status`) y de `GuestSummary` (`email`, `phone`, `preferred_language`, `document_status`, `legal_registration_status`) como **prohibidos**, parametrizado uno a uno como hace `tests/cleaning/test_task_context_read_model.py`.
- Aserta que `ReservationResponse` mantiene `property_id` y `guest_id` además de los nuevos (R1.3, R3.1 — se añaden, no se sustituyen).

Rejected: un test que solo verifique "los tres campos están presentes". Es lo que la propuesta no permite — el cambio se valida con un pin asimétrico (los que entran, los que se quedan fuera) y no con un subconjunto.

### D7 — Aislamiento por tenant con tests propios (R5.3)

**Chosen:** un test `backend/tests/reservations/test_identity_isolation.py` que, sembrando dos tenants vecinos reales:
- Construye una `Reservation` en tenant A con `property_id` apuntando a una `Property` de tenant B, y otra con `guest_id` apuntando a un `Guest` de tenant B.
- Pide `GET /api/v1/reservations` y `GET /api/v1/reservations/{id}` con un token de tenant A.
- Aserta que los tres campos derivados son `null` con su clave en las dos respuestas, y que el resto de la reserva (los 27 actuales) **sí** se devuelve.

Rejected: un test que cruce los dos tenants con un join simulado en SQL. La forma del test es la que sostiene la composición (D1, D2, D3) — un test que imitara el join probaría otra cosa.

### D8 — Sin nueva ruta, sin nuevo permiso, sin backend hot-path en producción de otro módulo

**Chosen:** los dos endpoints existentes (`GET /api/v1/reservations` y `GET /api/v1/reservations/{id}`) siguen declarando `require(Permission.READ_RESERVATIONS)` (`backend/app/reservations/api/router.py:48`); R6.1, R6.2, R6.3 se cumplen sin tocar `backend/app/auth/domain/policy.py`. Las dos dependencias de los use cases (`PropertyRepository`, `GuestRepository`) se cablean en `backend/app/reservations/api/dependencies.py`, reusando los adaptadores SQLAlchemy que ya están en producción.

Rejected: una ruta `/reservations/{id}/context` paralela. Es la forma de `cleaner-task-context` y `tech-incident-context`, válida allí porque el rol **no** tenía la ruta principal; aquí el rol ya tiene `GET /reservations/{id}` y la respuesta del mismo. Abrir un segundo endpoint sería obligar al cliente a una segunda llamada — exactamente lo que R5.1 prohíbe.

### D9 — Migración: solo `PropertyRepository.list_for_ids` en el puerto, sin cambio de esquema

**Chosen:** el cambio de datos es **cero** — el esquema ya tiene `properties.name` y `properties.internal_code` (`backend/app/properties/infrastructure/models.py:82-83`) y `guests.full_name` (el campo que el `GuestSummary.full_name` ya devuelve). El Alembic no se toca. La regeneración de `backend/openapi.json` (`make openapi`) y de `frontend/lib/api/generated/openapi.d.ts` (`cd frontend && npm run api:generate`, con el workaround del worktree de `sdd/project.md` "Worktree bootstrap") sí: son las dos mitades del mismo puente que `steering/documentation.md` regla 1 fija, y `sdd/specs/api-contract.md` ya lo documenta así.

Rejected: añadir una vista SQL materializada `reservation_with_identity` que precalcule los tres campos. Es una optimización prematura: con 2 viviendas y N≤100 por página, dos `WHERE id = ANY(:ids)` están en microsegundos; meter una vista compromete la forma de la query (D2 de `dashboard-api`) y rompe la regla "agregar no puede conceder" de un modo más difícil de revertir que añadir tres campos a un response model.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Puerto de propiedades | `backend/app/properties/domain/repositories.py` | añadir `list_for_ids(tenant_id, property_ids) -> Sequence[Property]`, con docstring de su análogo en guests |
| Adaptador de propiedades | `backend/app/properties/infrastructure/repositories.py` | implementar `list_for_ids` con un único `SELECT ... WHERE tenant_id = :tenant_id AND id = ANY(:ids)`; tests de aislamiento ya existentes cubren `tenant_id` |
| Caso de uso de listado | `backend/app/reservations/application/use_cases.py:378` (`ListReservationsUseCase`) | aceptar `properties` y `guests` en el constructor; tras `reservations.list`, llamar `properties.list_for_ids` y `guests.list_for_ids` sobre los ids de la página (los `None` se descartan) y poblar los tres campos |
| Caso de uso de detalle | `backend/app/reservations/application/use_cases.py:356` (`GetReservationUseCase`) | añadir `properties` al constructor; tras `reservations.get`, llamar `properties.get(tenant_id, reservation.property_id)` y poblar los dos campos de propiedad en `ReservationDetail` |
| Read model de detalle | `backend/app/reservations/application/use_cases.py:95` (`ReservationDetail`) | añadir `property_name: str \| None` y `property_internal_code: str \| None` |
| DTO de respuesta | `backend/app/reservations/api/schemas.py:119` (`ReservationResponse`) | añadir `property_name: str \| None` y `property_internal_code: str \| None`, ambos con `default=None` y presentes en `from_domain`; añadir `guest_full_name: str \| None` con la misma forma |
| DTO de detalle | `backend/app/reservations/api/schemas.py:181` (`ReservationDetailResponse`) | hereda los tres nuevos campos; `from_detail` los propaga desde `detail` |
| Router | `backend/app/reservations/api/router.py` | sin cambios estructurales; el `from_detail`/`from_domain` ya cubre los campos nuevos |
| Wiring | `backend/app/reservations/api/dependencies.py` | pasar `SqlAlchemyPropertyRepository(session)` a `get_list_reservations_use_case` y a `get_reservation_use_case` |
| Tests de pin | `backend/tests/reservations/test_response_identity_fields.py` (nuevo) | enumera los tres campos derivados, los nombres prohibidos de `Property` y los nombres prohibidos de `GuestSummary` (D6) |
| Tests de aislamiento | `backend/tests/reservations/test_identity_isolation.py` (nuevo) | siembra dos tenants, demuestra la degradación parcial (D5, D7) |
| Tests de no-N+1 | `backend/tests/reservations/test_list_identity_queries.py` (nuevo) | aserta que la lista emite un número fijo de `SELECT` para una página de N reservas, independiente de N (D3, análogo a `dashboard-api` "Composición por lotes") |
| Contrato | `backend/openapi.json` | regenerar con `make openapi` |
| Contrato FE | `frontend/lib/api/generated/openapi.d.ts` | regenerar (con el workaround del worktree de `sdd/project.md`) |
| Spec | `sdd/specs/reservations.md` | añadir la sección "Identidad legible de la vivienda y del huésped" con los SHALL R1-R6; modificar "Consulta y listado" para que cite los tres campos |
| Spec | `sdd/specs/api-contract.md` | sin cambios estructurales — solo aplica si la nota de "regenerar y commitear" no estuviera ya; verificar |
| Roadmap | `sdd/roadmap/reservation-property-identity.md` | al archivar (regla `sdd-archive-must-update-unshipped-roadmap-details`), actualizar el estado |

## Data & interfaces

**Esquema de datos**: sin cambios. Las tres columnas leídas (`properties.name`, `properties.internal_code`, `guests.full_name`) ya existen.

**Contrato API** — `ReservationResponse` y `ReservationDetailResponse` ganan tres campos:

| Campo | Tipo | Origen | Vacío |
|---|---|---|---|
| `property_name` | `string \| None` | `Property.name` | `null` con clave cuando el `property_id` no resuelve en el tenant (R1.2, R2.2) |
| `property_internal_code` | `string \| None` | `Property.internal_code` | mismo criterio |
| `guest_full_name` | `string \| None` | `GuestSummary.full_name` | `null` con clave cuando `guest_id` es `null` (reserva manual sin huésped, R3.2) o no resuelve en el tenant (R3.3, R4.2) |

Los tres se serializan **siempre**, presentes con su clave —un valor `null` y una clave ausente no son lo mismo para el cliente (R1.2). `property_id` y `guest_id` se conservan (R1.3, R3.1).

**Eventos / jobs / config**: sin cambios. Ninguno de los tres campos se deriva de un job, ninguno requiere nueva variable de entorno.

## Risks & mitigations

- **N+1 si un futuro cambio itera `result.items` en lugar de hacer batch.** Mitigado por el test de techo constante de D7 (`test_list_identity_queries.py`) y por la firma `list_for_ids` que D2 introduce — un `for rid in page: properties.get(...)` no compila contra un `Sequence[Property]` sin un cast.
- **Drift del conjunto de campos derivados.** Mitigado por el test de pin de D6 — un `property_email` o un `address_line1` en `ReservationResponse` rompe el suite en rojo, no en silencio.
- **Olvido de regenerar una de las dos mitades del contrato publicado.** Mitigado por los workflows `api-contract` y `frontend-api-contract` (ya documentados en `steering/documentation.md` regla 1); el PR no pasa en verde sin ambos artefactos.
- **El batch de propiedades introduce un nuevo escritor del scope de tenant.** Mitigado por la firma `list_for_ids(tenant_id, ...)` y por la simetría con `GuestRepository.list_for_ids` (que ya tiene su test de aislamiento en `tests/test_route_authorization.py`).
- **Comportamiento divergente con `tech-incident-context` en el cruce de tenant** (allí `404`, aquí degradación parcial). Mitigación: la decisión está fechada, justificada (la entidad principal es la reserva, no la propiedad) y documentada como D5; cualquier `tech-incident-context`-shaped que aparezca después deberá comparar contra esta nota, no contra `tech-incident-context`.

## Open questions

Ninguna que requiera decisión antes de `/sdd:tasks`. El proposal ya cerró:
- La forma (sin `/context` hermano) — D8.
- El comportamiento de cruce de tenant (degradar, no `404`) — D5.
- La fuente de `guest_full_name` (`GuestSummary`, no la entidad) — D4.
- El pin del conjunto de campos (test de pin, no dataclass congelado) — D1, D6.

Si en implementación surge un matiz no previsto —por ejemplo, que el `WHERE id = ANY(:ids)` necesite un orden explícito para que la lista coincida con la página de reservas— se documenta en `BLOCKED.md` antes de continuar, no se decide implícitamente.
