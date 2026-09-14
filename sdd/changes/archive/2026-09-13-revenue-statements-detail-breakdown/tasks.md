# Tasks: revenue-statements-detail-breakdown

## 1. API projections for statement detail <!-- panel: PASS 2026-09-12 receipt:203014ec -->

- [x] 1.1 En `backend/app/statements/api/schemas.py`, añadir el response schema específico del detalle conservando todos los campos actuales de `OwnerStatementResponse` al mismo nivel y con los mismos nombres/tipos, y añadir sólo los campos top-level `expenses` y `reservations` [R1, R4].
- [x] 1.2 En `backend/app/statements/api/schemas.py`, definir las proyecciones read-only mínimas para las colecciones: reservations con `id`, `check_in_date`, `nights`, `gross_amount`, `ota_commission`, `net_amount`, `currency`; expenses con `id`, `category`, `description`, `amount`, `currency`, `date` [R1, R2].
- [x] 1.3 Añadir tests de serialización que demuestren que las proyecciones no publican PII, notas internas, identificadores externos, estados operativos, datos de aprobación, claves de almacenamiento ni timestamps innecesarios [R1, R2].

## 2. GET detail composition and compatibility <!-- panel: PASS 2026-09-12 receipt:b6a64556 -->

- [x] 2.1 En `backend/app/statements/api/router.py`, cambiar únicamente el `response_model` y el mapper de `GET /api/v1/owner-statements/{statement_id}` para serializar `statement`, `expenses` y `reservations` desde el resultado existente de `GetOwnerStatementUseCase`, sin introducir wrapper `statement: {...}` [R1, R2, R4].
- [x] 2.2 Mantener `GetOwnerStatementUseCase`, `OwnerStatementRepository`, `ExpenseRepository` y `ReservationRepository` sin nuevas queries ni cambios de criterio; verificar mediante tests que se conserva el filtro de gastos por tenant/propiedad/período/`statement_id` y el filtro EUR de reservas [R2, R3].
- [x] 2.3 Añadir tests API para un detalle válido que comprueben todos los campos actuales del resumen, las colecciones top-level y el contenido mínimo de cada proyección [R1, R2, R5].

## 3. Tenancy and error boundaries <!-- panel: PASS 2026-09-12 receipt:04260370 -->

- [x] 3.1 Añadir o ajustar tests API para demostrar que un statement inexistente y uno de otro tenant responden con el mismo `404` constante y no consultan ni publican colecciones asociadas [R3, R5].
- [x] 3.2 Verificar con tests de aislamiento que las filas de `expenses` y `reservations` del detalle quedan limitadas al tenant de la sesión y a la propiedad/período del statement, sin aceptar `tenant_id` desde path, query o body [R3, R5].
- [x] 3.3 Añadir una aserción de contrato que confirme que `OwnerStatementPageResponse.items` sigue referenciando `OwnerStatementResponse`, que el PATCH sigue devolviendo `OwnerStatementResponse` y que ni el listado ni las mutaciones ejecutan la composición de detalle [R2, R4, R5].

## 4. OpenAPI and generated frontend contract <!-- panel: PASS 2026-09-12 receipt:1f9c8052 -->

- [x] 4.1 Regenerar `backend/openapi.json` con `make openapi` desde el código y comprobar que sólo el `200` del GET detail referencia el response enriquecido; no añadir paths ni operaciones de escritura [R4, R5].
- [x] 4.2 Regenerar `frontend/lib/api/generated/openapi.d.ts` siguiendo el procedimiento documentado en `sdd/project.md` para worktrees, y comprobar que el tipo del GET detail contiene el resumen plano y las colecciones mínimas [R4, R5].
- [x] 4.3 Ejecutar `cd frontend && npm run api:check` en el entorno preparado para el worktree y confirmar que el artefacto generado coincide con `backend/openapi.json` [R4, R5].

## 5. Verification

- [x] 5.1 Ejecutar la suite backend completa: `docker compose run --rm backend uv run pytest` [R1, R2, R3, R5].
- [x] 5.2 Ejecutar el chequeo de contrato OpenAPI: `docker compose run --rm backend python -m app.cli.openapi --check` [R4, R5].
- [x] 5.3 Ejecutar el chequeo de tipos API del frontend: `cd frontend && npm run api:check` [R4, R5].
- [x] 5.4 Ejecutar el chequeo de tipado estático del backend con la versión/configuración vigente (`cd backend && uv run pyright .`) y comparar sus diagnósticos contra un baseline equivalente medido en la base real del change (el merge-base/base branch correspondiente), sin fijar un número histórico de errores. Los errores ya presentes deben quedar identificados como baseline; cualquier error nuevo introducido por `revenue-statements-detail-breakdown`, especialmente en archivos tocados o atribuible al change, debe corregirse antes de marcar la task como completada [R2, R3, R5].

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
- `OwnerStatementDetailResponse` hereda el resumen plano y añade proyecciones mínimas; `docker compose -f docker-compose.yml -f docker-compose.worktree.yml run --rm backend uv run pytest tests/statements/test_detail_schemas.py` · 2 passed.
- El mapper del router consume las tres claves existentes de `GetOwnerStatementUseCase`; `docker compose -f docker-compose.yml -f docker-compose.worktree.yml run --rm backend uv run pytest tests/statements/test_api.py::TestGetOwnerStatement` · 2 passed; `... pytest tests/statements/test_use_cases.py` · 24 passed.
- `docker compose -f docker-compose.yml -f docker-compose.worktree.yml run --rm backend uv run pytest tests/statements/test_detail_schemas.py tests/statements/test_api.py::TestGetOwnerStatement tests/statements/test_use_cases.py::TestOwnerStatementReads` · 9 passed; 404 idéntico, no-queries tras miss y schema de listado fijados.
- `make openapi`; frontend `api:generate` con el workaround documentado; `npm run api:check` · pass. OpenAPI confirma list/detail/PATCH refs: `OwnerStatementPageResponse`/`OwnerStatementDetailResponse`/`OwnerStatementResponse`.
- Verification: suite backend completa · `11049 passed, 44 skipped`; OpenAPI `--check` · pass; frontend `api:check` · pass.
- Pyright baseline medido en merge-base `202d86c4892e9c1cd09e345dde1ad2425fec29c6` · `980 errors`; HEAD final · `979 errors`; no se introdujeron diagnósticos nuevos y la deuda restante es baseline.
- Correcciones de tipado del change verificadas con `tests/statements/test_detail_schemas.py tests/statements/test_use_cases.py` · `29 passed`; Pyright acotado sin errores en schemas/tests nuevos y solo los 12 diagnósticos preexistentes de `router.py`.
