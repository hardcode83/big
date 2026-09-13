# Design: revenue-statements-detail-breakdown

## Context

`GetOwnerStatementUseCase.execute` ya carga el statement con `OwnerStatementRepository.get`, obtiene los gastos del período mediante `ExpenseRepository.list_for_period`, conserva sólo los que tienen el mismo `statement_id` y obtiene las reservas mediante `ReservationRepository.list_for_properties`, filtrando después las que no son EUR (`backend/app/statements/application/use_cases.py:711-762`).

La capa API descarta dos de las tres claves del resultado: `GET /api/v1/owner-statements/{statement_id}` declara `OwnerStatementResponse` y llama a `OwnerStatementResponse.from_domain(payload["statement"])` (`backend/app/statements/api/router.py:218-242`). Ese schema también es el elemento de `OwnerStatementPageResponse` y la respuesta del PATCH, por lo que añadirle colecciones rompería la separación entre listado, detalle y mutación (`backend/app/statements/api/schemas.py:60-141`).

El cambio publica la composición ya existente sólo en el GET detail, mediante DTOs de proyección API mínimos. No cambia las entidades `OwnerStatement`, `Expense` o `Reservation`, sus repositorios, el criterio de selección, las exportaciones ni la base de datos.

## Decisions

### D1 — Response específico para el GET detail

**Chosen:** añadir un response schema específico del detalle, `OwnerStatementDetailResponse`, que conserve **todos** los campos actuales de `OwnerStatementResponse` en el mismo nivel, con los mismos nombres y tipos, y añada `expenses` y `reservations` como nuevos campos top-level. El wire contract no introduce un wrapper `statement: {...}` ni cambia la forma actual del payload para consumidores existentes. El GET detail será el único endpoint que lo use; `OwnerStatementPageResponse` seguirá referenciando `OwnerStatementResponse`, y el PATCH seguirá devolviendo `OwnerStatementResponse`.

Esto mantiene intactos el contrato y el coste del listado y evita que una respuesta de mutación anuncie datos que no consulta. El nombre hace explícita la diferencia entre el summary compartido y la lectura enriquecida.

Rejected: añadir `expenses` y `reservations` a `OwnerStatementResponse` — ese schema está compartido por el listado y el PATCH, y obligaría a contaminar ambos contratos o a ejecutar composición de detalle en el listado.

Rejected: crear otro endpoint de breakdown — duplicaría la ruta de lectura, introduciría otra superficie de permisos/404 y contradice el alcance aprobado de enriquecer el GET existente.

### D2 — Proyecciones API read-only mínimas

**Chosen:** definir dos proyecciones Pydantic anidadas dentro del contrato de detalle, una para cada colección, con sólo los campos necesarios para la fila financiera:

- Reservation breakdown: `id`, `check_in_date`, `nights`, `gross_amount`, `ota_commission`, `net_amount`, `currency`.
- Expense breakdown: `id`, `category`, `description`, `amount`, `currency`, `date`.

Los nombres se derivan de los atributos existentes en `Reservation`, `Expense` y sus schemas públicos. La API mapeará desde las entidades ya entregadas por el caso de uso; no se copiarán `guest_id`, `guest_full_name`, `internal_notes`, `external_*`, estados operativos, `approved_by`, `receipt_storage_key` ni timestamps que no son necesarios para reporting.

Rejected: reutilizar `ReservationResponse` y `ExpenseResponse` completos — arrastra PII, notas internas, identificadores externos, información operacional y datos de aprobación/almacenamiento ajenos al desglose.

Rejected: cambiar las entidades de dominio para crear objetos de breakdown — el dominio ya contiene los importes y fechas, y la proyección es una preocupación de transporte.

### D3 — Reutilizar la composición existente sin nuevas queries

**Chosen:** mantener `GetOwnerStatementUseCase` como compositor compartido únicamente del GET detail cubierto por este change. El router pasará sus tres resultados al mapper del response específico: `statement`, `expenses` y `reservations`. No se añadirá otra lectura a repositories ni se reconstruirá el período en la API.

`ExportOwnerStatementPdfUseCase` permanece fuera de scope: no se refactoriza el export PDF ahora ni se afirma que el GET detail y el PDF compartan actualmente la misma composición. Una eventual unificación futura de ambos flujos requerirá un change separado.

La colección de gastos conservará exactamente el filtro existente: tenant explícito, propiedad y período del statement, seguida de `statement_id == statement.id`. La colección de reservas conservará `list_for_properties` y el filtro EUR ya implementados. El desglose por reserva representa las reservas cuyo stay solapa el período según ese port del repositorio; no se inventa una relación `reservation.statement_id` que el modelo no tiene.

Rejected: que el router consulte directamente `ExpenseRepository` o `ReservationRepository` — rompería la arquitectura hexagonal y duplicaría criterios de tenant/período.

### D4 — Tenancy, permisos y 404

**Chosen:** no cambiar la dependencia `ReadDep` del GET detail ni el primer lookup de `OwnerStatementRepository.get(tenant_id, statement_id)`. Si no hay statement, el caso de uso seguirá lanzando `OwnerStatementNotFoundError` antes de consultar o serializar las colecciones. Todas las filas adicionales seguirán llegando de puertos invocados con el mismo `tenant_id` de la sesión.

La respuesta no incluirá `tenant_id`. Las proyecciones tampoco añadirán campos que permitan ampliar el alcance de un recurso o enumerar datos de otro tenant.

Rejected: hacer una consulta de colecciones antes de resolver el statement — podría revelar diferencias de existencia o producir respuestas parciales para un id ajeno.

### D5 — OpenAPI y tipos derivados

**Chosen:** cambiar sólo la respuesta documentada del GET detail, regenerando `backend/openapi.json` con `make openapi` y después `frontend/lib/api/generated/openapi.d.ts` con el procedimiento documentado en `sdd/project.md`. Los paths del listado, PATCH y exportación conservarán sus respuestas actuales.

La verificación de contrato comprobará que el nuevo schema aparece en el GET detail, que `OwnerStatementPageResponse.items` continúa apuntando a `OwnerStatementResponse` y que no aparecen operaciones nuevas.

Rejected: editar manualmente OpenAPI o los tipos generados — son artefactos derivados y el proyecto exige regenerarlos desde la aplicación.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Statements API schemas | `backend/app/statements/api/schemas.py` | Añadir el response específico de detalle y las dos proyecciones mínimas; conservar sin cambios `OwnerStatementResponse`, `OwnerStatementPageResponse`, `ExpenseResponse` y sus mappers públicos. |
| Statements API router | `backend/app/statements/api/router.py` | Cambiar sólo el `response_model` y la serialización de `GET /owner-statements/{statement_id}` para pasar las tres claves ya compuestas. PATCH, listado y exports permanecen iguales. |
| Application | `backend/app/statements/application/use_cases.py` | No añadir queries ni cambiar el criterio actual; como máximo, ajustar la anotación/documentación del payload compuesto si los tests lo requieren. |
| Tests | `backend/tests/statements/test_api.py`, tests de statements y `backend/tests/test_openapi_contract.py` sólo si el contrato existente necesita una aserción específica | Cubrir payload enriquecido, proyección mínima, aislamiento/404 y separación del listado. |
| Derived contracts | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | Regenerar, no editar manualmente. |
| Living specs | `sdd/specs/revenue-statements.md`, `sdd/specs/revenue-statements-detail-breakdown.md` al archivar | Registrar que el GET detail publica las proyecciones y cerrar la deuda documentada. |

No se modifican `backend/app/statements/domain/entities.py`, `backend/app/statements/domain/repositories.py`, `backend/app/statements/infrastructure/repositories.py`, modelos Alembic, frontend runtime ni el archive histórico.

## Data & interfaces

- Base de datos: sin cambios; se leen las tablas existentes.
- Dominio: sin cambios; no se introducen entidades, value objects, eventos ni cálculos nuevos.
- Queries: sin cambios; se reutilizan las tres lecturas que ya ejecuta `GetOwnerStatementUseCase`.
- Endpoint: no se añade ninguno; cambia de forma aditiva la respuesta exitosa de `GET /api/v1/owner-statements/{statement_id}`.
- Response detail: `OwnerStatementDetailResponse` conserva todos los campos actuales de `OwnerStatementResponse` al mismo nivel, con los mismos nombres y tipos, y añade `expenses` y `reservations` como campos top-level nuevos. No existe wrapper `statement: {...}` ni cambia la forma actual del payload para consumidores existentes. Los nombres de los campos de las proyecciones son los atributos existentes enumerados en D2.
- Listado/mutación: `OwnerStatementPageResponse` y la respuesta de PATCH continúan usando `OwnerStatementResponse` sin colecciones.
- Seguridad: `READ_OWNER_STATEMENTS`, tenant desde JWT y `404` constante permanecen sin cambios.
- Artefactos derivados: regenerar `backend/openapi.json` y `frontend/lib/api/generated/openapi.d.ts`.

## Risks & mitigations

- **Fuga de datos por reutilización de DTO:** se evita con proyecciones explícitas y tests que fallen ante campos no permitidos.
- **Contaminación del listado:** se evita con un response model exclusivo del GET detail y una aserción OpenAPI sobre la referencia de `OwnerStatementPageResponse.items`.
- **Divergencia entre composición y API:** el mapper consume directamente las tres claves del resultado del caso de uso; no vuelve a consultar ni recalcular.
- **Leakage cross-tenant:** el statement se resuelve primero con `tenant_id`; los puertos de expenses/reservations reciben el mismo tenant y un fallo de statement corta antes las consultas.
- **Cambio incompatible para clientes del GET detail:** la ampliación es aditiva; los campos actuales permanecen iguales y el contrato se publica en OpenAPI/tipos.
- **Coste de payload:** las colecciones son propias del detalle y no del listado; no se ejecuta composición por cada fila paginada.

## Open questions

None. El proposal aprobado fija el endpoint, el alcance read-only, la ausencia de nuevas queries y la separación del listado; D1-D5 concretan esas decisiones sin abrir alternativas que requieran una decisión humana.
