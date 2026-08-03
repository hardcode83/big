# Tasks: frontend-api-contract-consumer

## 1. Generador y artefacto versionado

- [x] 1.1 Añadir `openapi-typescript` en la versión exacta elegida por el Design a
  `frontend/package.json` y `frontend/package-lock.json`, y registrar los scripts
  `api:generate` y `api:check` sin introducir otro generador o dependencia equivalente. [R1, R5]
- [x] 1.2 Implementar `frontend/scripts/generate-api-types.mjs` como único flujo oficial: resolver
  `backend/openapi.json` desde la ubicación del script, generar declaraciones, normalizar LF y
  newline final, escribir en modo generación y comparar bytes en modo check sin modificar el
  artefacto versionado. Verificar ambos modos con Node 22 desde `frontend/`. [R1, R3, R5]
- [x] 1.3 Ejecutar `npm run api:generate` para crear
  `frontend/lib/api/generated/openapi.d.ts`, comprobar que contiene los tipos de `paths` del
  contrato y dejarlo versionado como salida reproducible; confirmar que `backend/openapi.json` no
  cambia. Verificar además que el artefacto contiene únicamente declaraciones TypeScript, no
  genera JavaScript runtime, no contiene clientes HTTP, wrappers por endpoint ni lógica ejecutable,
  y representa exclusivamente los tipos derivados de `backend/openapi.json`. [R1, R4]

## 2. Cliente HTTP genérico tipado <!-- panel: PASS 2026-08-03 -->

- [x] 2.1 En `frontend/lib/api/client.ts`, importar `paths` y añadir helpers de tipos para extraer
  cuerpo JSON, respuesta de éxito y `undefined` para 204/sin cuerpo; tipar `request<Path, Method>`
  de modo que `Method` solo pueda ser uno de los verbos declarados para ese `Path`, sin una
  sobrecarga pública `string → unknown`. [R2]
- [x] 2.2 Ajustar `RequestOptions` y la implementación de `createApiClient` en
  `frontend/lib/api/client.ts` para conservar URL, headers, serialización JSON, `fetchImpl`,
  `getHeaders`, `onUnauthorized`, tratamiento 204 y propagación de `ApiError`, mientras las
  respuestas exitosas quedan inferidas por la operación OpenAPI. [R2, R4]
- [x] 2.3 Mantener `frontend/lib/api/errors.ts` como estrategia runtime: conservar
  `ApiError`/`parseApiError`, validar el envelope no-OK y no añadir tipos de error específicos por
  endpoint; actualizar solo los tipos compartidos que exija la compilación. [R2, R4]
- [x] 2.4 Actualizar `frontend/lib/api/index.ts` para reexportar `paths` y los tipos públicos
  necesarios, sin crear `ReservationsApi`, `CleaningApi`, `UserApi`, repositorios, servicios de
  dominio ni funciones wrapper por endpoint. [R2]
- [x] 2.5 Adaptar `frontend/lib/api/client.test.ts` y cualquier fixture afectado para usar rutas y
  métodos existentes en `backend/openapi.json`; conservar las pruebas de URL, cuerpo, headers,
  204, `ApiError` y hook 401, y añadir aserciones de tipos que demuestren que una ruta solo acepta
  sus métodos OpenAPI. [R2, R4]

## 3. Gate reproducible y documentación

- [x] 3.1 Crear `.github/workflows/frontend-api-contract.yml` con los disparadores PR/push a
  `main`/manual, Node 22, `npm ci`, permisos `contents: read`, concurrencia, timeout y actions
  fijadas por SHA; ejecutar `npm run api:check` desde `frontend/`, sin servicios ni filtros de
  paths, y fallar mostrando el diff y `npm run api:generate` cuando haya deriva. [R3]
- [x] 3.2 Actualizar `frontend/README.md` y el README raíz con `backend/openapi.json` como fuente,
  el artefacto generado, Node 22, `npm ci`, `npm run api:generate` y `npm run api:check`,
  incluyendo que el mismo flujo produce bytes idénticos en macOS, Linux y CI. [R5]

## 4. Verificación

- [x] 4.1 Desde `frontend/`, instalar exactamente el lockfile con `npm ci` y verificar que
  `npm run api:check` termina correctamente sin modificar
  `lib/api/generated/openapi.d.ts`. [R1, R3, R5]
- [x] 4.2 Desde `frontend/`, ejecutar `npm run api:generate` dos veces consecutivas y comprobar
  que la segunda ejecución no produce ningún cambio (`git diff` vacío sobre
  `lib/api/generated/openapi.d.ts`), confirmando que el proceso es determinista y reproducible.
  [R1, R3, R5]
- [x] 4.3 Desde `frontend/`, ejecutar la suite Vitest: `npm test`. [R4]
- [x] 4.4 Desde `frontend/`, ejecutar ESLint: `npm run lint`. [R4]
- [x] 4.5 Desde `frontend/`, ejecutar el typecheck estricto: `npm run typecheck`. [R2, R4]
- [x] 4.6 Desde `frontend/`, ejecutar el build de producción: `npm run build`. [R4]
- [x] 4.7 Revisar el diff final para confirmar que no se modifican backend ni
  `backend/openapi.json`, no se conectan superficies de UI a endpoints reales y no aparecen
  wrappers, repositorios o servicios por endpoint. [R2, R4]
