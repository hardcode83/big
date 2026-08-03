# Consumidor del contrato API del frontend

## Purpose

Esta capacidad convierte el `backend/openapi.json` versionado en tipos TypeScript que el
transporte HTTP genérico del frontend puede consumir. Mantiene la frontera desacoplada del
backend runtime y evita que el artefacto generado derive silenciosamente entre desarrollo y CI.

## Requirements

### Fuente única y generación

- THE SYSTEM SHALL usar `backend/openapi.json` como única fuente de generación de tipos del
  frontend.
- THE SYSTEM SHALL usar exactamente un generador oficial OpenAPI → TypeScript, fijado en las
  dependencias y lockfile de `frontend/`.
- WHEN una persona ejecuta `npm run api:generate` desde `frontend/`, THE SYSTEM SHALL escribir
  `frontend/lib/api/generated/openapi.d.ts` con la salida del contrato versionado.
- THE SYSTEM SHALL producir un artefacto compuesto únicamente por declaraciones TypeScript,
  sin JavaScript runtime, clientes HTTP, wrappers por endpoint ni lógica ejecutable.

### Reproducibilidad y deriva

- WHEN `npm run api:check` se ejecuta, THE SYSTEM SHALL regenerar la salida en un área temporal y
  compararla byte a byte con el artefacto versionado sin modificarlo.
- IF la salida regenerada difiere, THEN THE SYSTEM SHALL fallar mostrando el diff y
  `npm run api:generate` como comando correctivo.
- THE SYSTEM SHALL producir la misma salida en macOS, Linux y CI usando Node 22, `npm ci`, el
  generador fijado y saltos de línea normalizados.
- WHEN se abre o actualiza un Pull Request, se hace push a `main` o se inicia una ejecución
  manual, THE SYSTEM SHALL ejecutar el workflow `frontend-api-contract` sin filtros de paths,
  sin servicios de backend y con `contents: read`.

### Transporte genérico tipado

- WHEN una persona llama a `ApiClient.request`, THE SYSTEM SHALL aceptar solo rutas presentes
  en `paths` y solo métodos HTTP declarados para esa ruta.
- THE SYSTEM SHALL requerir el método explícito para rutas que no declaran `GET` y SHALL permitir
  omitirlo únicamente cuando `GET` está declarado.
- THE SYSTEM SHALL tipar cuerpos `application/json`, respuestas JSON de éxito y `undefined`
  para respuestas 204 o sin cuerpo; los media types no JSON no se anuncian como cuerpos JSON.
- THE SYSTEM SHALL preservar `joinUrl`, headers, `fetchImpl`, serialización JSON, tratamiento
  204 y hooks `getHeaders`/`onUnauthorized`.

### Errores y límites

- THE SYSTEM SHALL continuar procesando respuestas no-OK mediante `ApiError` y
  `parseApiError`, sin generar tipos de error específicos por endpoint.
- THE SYSTEM SHALL no crear clientes `ReservationsApi`, `CleaningApi` o `UserApi`, repositorios,
  servicios de dominio ni funciones wrapper por endpoint.
- THE SYSTEM SHALL mantener el dashboard y el shell sin llamadas funcionales al backend real.

## Key files

- `backend/openapi.json` — fuente versionada del contrato.
- `frontend/scripts/generate-api-types.mjs` — flujo único de generación y deriva.
- `frontend/lib/api/generated/openapi.d.ts` — artefacto TypeScript versionado.
- `frontend/lib/api/client.ts` — transporte HTTP genérico tipado.
- `frontend/lib/api/errors.ts` — tratamiento runtime del envelope de errores.
- `frontend/lib/api/client.test.ts` — pruebas de transporte y restricciones de métodos.
- `frontend/package.json` / `frontend/package-lock.json` — generador y comandos fijados.
- `.github/workflows/frontend-api-contract.yml` — gate de deriva en CI.
- `README.md` y `frontend/README.md` — flujo documentado para contributors.
