# frontend-api-contract-consumer

[FE] consumir en el frontend el `openapi.json` versionado producido por `api-contract-export`: derivar tipos TypeScript, cablearlos en `frontend/lib/api/` y añadir una comprobación reproducible de deriva entre el contrato OpenAPI y los tipos generados. Depende de `api-contract-export` y no forma parte de `frontend-ci`.
