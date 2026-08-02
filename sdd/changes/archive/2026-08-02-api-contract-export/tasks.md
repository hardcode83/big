# Tasks: api-contract-export

<!-- Orden deliberado: la forma del contrato se arregla ANTES de generar el artefacto (§1
     antes de §2). Al revés se commitearía un contrato con el 422 mentiroso y el
     siguiente commit lo reescribiría entero, dejando un diff inicial ilegible. -->

## 1. El documento describe lo que el backend devuelve de verdad <!-- panel: PASS 2026-08-01 -->

- [x] 1.1 Crear `backend/app/core/openapi.py` con el modelo `ErrorEnvelope`, espejo exacto de
      `error_envelope()` de `app/core/errors.py` (`{"error": {"code", "message", "details"}}`).
      Sin tocar `errors.py`: el envoltorio de runtime no cambia, solo se documenta. [R3]
- [x] 1.2 En el mismo fichero, `custom_openapi(app)`: registra `ErrorEnvelope` en
      `components.schemas`, reescribe la respuesta 422 de **toda** operación para referenciarlo y
      elimina el `HTTPValidationError` de FastAPI, que queda sin referenciar. Un punto de control
      para las 18 rutas y las futuras — no se toca ningún decorador. [R3]
- [x] 1.3 Crear `backend/app/core/error_codes.py` con el `StrEnum` `ErrorCode`, fuente única de
      verdad de los códigos de PRD §23. Incluye los que hoy viven repartidos en seis sitios —
      entre ellos `CONFLICT` (409) y `PAYLOAD_TOO_LARGE` (413), que la primera redacción de D11 no
      habría visto. [R3]
- [x] 1.3b Migrar a `ErrorCode` los seis puntos que hoy escriben el código como literal: atributos
      `code` de las subclases de `AppError` y `_HTTP_STATUS_CODES` (`app/core/errors.py`), las
      tablas `_MAPPING` de `app/{auth,reservations,tenants}/api/errors.py` y los literales de
      `app/integrations/api/errors.py`. Sustitución mecánica sin cambio de comportamiento: un
      `StrEnum` serializa igual que el literal. La suite existente, que ya afirma códigos concretos
      por módulo, es la verificación. [R3]
- [x] 1.3c Derivar el `enum` de `ErrorEnvelope.code` de `ErrorCode`, no de una lista propia. [R3]
- [x] 1.4 Cablear en `backend/app/main.py`: asignar `app.openapi` al generador de 1.2 y pasar
      `version=` leyendo la versión declarada en `backend/pyproject.toml`. **No** usar la cadena
      de build de `app-version-visibility` ni leer el `VERSION` de la raíz — la primera dejaría el
      check de §3 permanentemente en rojo y el contenedor no ve la segunda. [R1, R3]
- [x] 1.5 Declarar `responses` de 401/403 a nivel de `APIRouter` en los routers cuyas rutas cuelgan
      de la dependencia de autorización (`tenants`, `reservations`, `integrations`, `users`). En
      `auth`, declararlo en las rutas que lo tienen y **no** en `login`/`refresh`, que son anónimas
      según `ANONYMOUS_ENDPOINTS` de `tests/test_route_authorization.py`. No inventar 404/409/429
      por endpoint. [R3]
- [x] 1.6 Crear `backend/tests/test_openapi_contract.py` sobre `create_app()` y `app.routes`,
      espejando la estructura de `tests/test_route_authorization.py`, con cuatro comprobaciones:
      (a) toda ruta bajo `/api/v1` cuyo código de éxito no sea `204` declara `response_model` —
      hoy pasa, las tres sin modelo son `POST /auth/logout`, `DELETE /users/{user_id}` y
      `DELETE /reservations/{reservation_id}`; (b) ninguna operación referencia
      `HTTPValidationError` y el 422 apunta a `ErrorEnvelope`; (c) **fidelidad** — una petición
      realmente inválida vía `TestClient` devuelve un cuerpo que valida contra el `ErrorEnvelope`
      publicado; (d) **integridad del registro** — recorrer los `_MAPPING`, los atributos `code` de
      `AppError` y `_HTTP_STATUS_CODES` y fallar si alguno contiene un valor que no sea miembro de
      `ErrorCode`. Sin (c), 1.2 es una promesa sin verificar; sin (d), el `enum` vuelve a quedarse
      corto en cuanto alguien escriba un código nuevo en literal. [R3]

## 2. El contrato como artefacto reproducible <!-- panel: PASS 2026-08-01 -->

- [x] 2.1 Crear `backend/app/cli/openapi.py` (`python -m app.cli.openapi`), espejo de
      `app/cli/bootstrap.py`: importa `create_app()`, serializa con `json.dumps(..., indent=2,
      sort_keys=True, ensure_ascii=False)` más `\n` final y escribe `backend/openapi.json`. Sin
      base de datos, Redis ni red: la única variable que `Settings` exige para importar es
      `jwt_secret_key`. [R1]
- [x] 2.2 Añadir a `backend/tests/test_openapi_contract.py` el test de determinismo: generar dos
      veces produce bytes idénticos, y hacerlo **bajo dos configuraciones distintas** — no dos
      veces seguidas con el mismo entorno, que no probaría nada si un esquema derivase un default
      de `Settings`. [R1]
- [x] 2.3 Añadir el target `openapi` al `Makefile` (`docker compose exec backend python -m
      app.cli.openapi`), siguiendo la forma del target `bootstrap`. [R1]
- [x] 2.4 Generar y commitear `backend/openapi.json`. Revisar el fichero resultante a ojo una vez:
      que `info.version` sea `0.1.0`, que no aparezca `HTTPValidationError` y que no se haya
      colado ningún `servers` ni valor derivado del entorno. [R1]

## 3. El fichero commiteado no puede quedarse obsoleto <!-- panel: PASS 2026-08-01 -->

- [x] 3.1 Crear `.github/workflows/api-contract.yml`: regenera el contrato y falla si difiere del
      commiteado, mostrando el diff y el comando que lo arregla. Mismas garantías que
      `backend-tests.yml` — `pull_request` y push a `main` **sin filtro de rutas** (motivo en
      `specs/backend-ci.md`), `concurrency` con `cancel-in-progress`, `timeout-minutes`,
      `permissions: contents: read`, actions pineadas por SHA, clave JWT efímera con `openssl rand
      -hex 32` y `uv sync --frozen`. **Sin** services de PostgreSQL ni Redis: este check no los
      necesita. [R2]
- [x] 3.2 Demostrar que el gate muerde: cambiar un `response_model` en local sin regenerar,
      ejecutar la comparación y comprobar que falla con el comando de arreglo en el mensaje;
      revertir. Sin esta comprobación, R2.2 queda afirmada y no verificada. [R2]

## 4. Cómo se consume <!-- panel: PASS 2026-08-01 -->

- [x] 4.1 Actualizar el `README.md` de la raíz: el target `make openapi` en la sección de
      comandos —`steering/documentation.md` lo exige cuando un change añade un target— y junto a
      él el comando recomendado para derivar tipos TypeScript del fichero (`openapi-typescript`),
      como referencia para `frontend-ci`. Sin añadir la dependencia al frontend. [R4]
- [x] 4.2 Actualizar `sdd/steering/documentation.md` §Audiencias para que la línea de
      OpenAPI/Swagger apunte al artefacto versionado además de al `/docs` servido. [R4]

## 5. Verification

- [x] 5.1 Suite completa del backend en verde: `docker compose exec backend uv run pytest`. [R1, R3]
- [x] 5.2 `make openapi` no produce ningún diff sobre el fichero commiteado — el estado que el
      workflow de 3.1 exige. [R1, R2]
- [x] 5.3 Comprobar que el change **no ha tocado `frontend/**`**: `git diff --name-only main` no
      devuelve ninguna ruta bajo `frontend/`. Es la promesa explícita del proposal (§Out of scope),
      y el reparto con `frontend-ci` depende de ella. [R4]
- [x] 5.4 Arrancar el stack (`make up`) y confirmar que `/docs` sigue sirviendo y que el 422 que
      muestra es el `ErrorEnvelope`, no el `HTTPValidationError` — que el post-proceso de 1.2 no
      ha roto la documentación interactiva. [R3]

<!-- Cobertura de requisitos: R1 → 2.1-2.4, 5.1-5.2 (y 1.4, que sostiene R1.2: sin una
     `info.version` estable la salida no es byte-idéntica entre commits) · R2 → 3.1, 3.2,
     5.2 · R3 → 1.1-1.6, 5.1, 5.4 · R4 → 4.1, 4.2, 5.3. El criterio de secreto efímero
     (R1.4) lo cumplen 2.1 y 3.1, no la tarea 1.4 — la coincidencia de numeración la
     señaló el panel de QA. Ninguna tarea preexistente: todo el alcance es nuevo (las 18
     rutas ya cumplen 1.6a, pero el test no existía). -->
