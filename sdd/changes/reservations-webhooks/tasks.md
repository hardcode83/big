# Tasks: reservations-webhooks

Orden pensado para que el sistema siga en pie al cerrar cada sección: primero el material que la
autenticación necesita (§1), luego la recepción que lo usa (§2), la frontera de texto libre que la
recepción destapa (§3), y por último el procesamiento asíncrono (§4). Hasta §4 el sistema tiene una cola
que se llena y nadie vacía — que es exactamente el estado que PRD §16 describe (`processed=FALSE`), no
una rotura.

Cada tarea incluye su test. TDD obligatorio en `domain/` con invariante real (`steering/testing.md`), no
forzado en `infrastructure/`.

## 1. Endpoint de webhook: entidad, esquema y administración

- [x] 1.1 Entidad `WebhookEndpoint` y su puerto de repositorio en
  `backend/app/integrations/domain/{entities.py,repositories.py}`, más los errores propios en
  `errors.py`. Python puro, sin SQLAlchemy ni Pydantic (regla de dependencia). **TDD**: el test exige
  primero que la entidad no admita un token ni un secreto vacíos y que exponga la comparación en tiempo
  constante como método propio, no como detalle del caso de uso. [R2.1]
  > **Ajuste al ejecutar**: la comparación en tiempo constante **no** quedó como método de la entidad,
  > sino como función pura en `domain/webhook_auth.py`. Motivo: `EncryptedSecret` no sabe descifrarse
  > —eso es deliberado, es el chokepoint de la regla 3(a)— así que un método de la entidad tendría que
  > recibir el texto en claro de su propio secreto como parámetro, que es una firma que invita a
  > malinterpretar quién custodia qué. Las tres primitivas (`generate_webhook_token`,
  > `hash_webhook_token`, `secrets_match`) son stdlib puro y viven en `domain/` igual.
  > 20 tests nuevos; la entidad rechaza además un `token_hash` que sea el **token** en vez de su hash,
  > que es el único accidente capaz de anular D3 y que ninguna constraint de columna vería.
- [x] 1.2 `WebhookEndpointModel` en `backend/app/integrations/infrastructure/models.py` con
  `TenantScopedMixin`, `UNIQUE(tenant_id, provider)`, `token_hash` `String(64)` `UNIQUE` y
  `header_secret_encrypted` `Text`; **y** las dos columnas de D9 en `WebhookEventModel`
  (`attempts SMALLINT NOT NULL DEFAULT 0`, `next_attempt_at TIMESTAMPTZ NULL`). Migración Alembic única
  en `backend/alembic/versions/`. Verificación: `uv run alembic upgrade head`, `uv run alembic check`
  (sin deriva modelo↔migración) y `uv run alembic downgrade base` limpio, que es lo que corre el CI.
  [R2.1, R5.3]
- [x] 1.3 `SqlAlchemyWebhookEndpointRepository` en `infrastructure/repositories.py`, con búsqueda por
  `token_hash`. **Test de aislamiento propio** de `webhook_endpoints` (no el genérico del módulo): un
  fallo de scoping aquí no filtra datos, concede control. Añadir su caso al test parametrizado de
  aislamiento. [R2.6]
  > **Ajuste al ejecutar**: no hay ningún test parametrizado que enumere tablas al que añadir un caso —
  > `tenant_scoped_classes()` selecciona **por presencia de columna**, así que la tabla entra en el
  > filtro global sola. Lo que sí se añade, siguiendo la forma que ya usa `test_pms_credentials.py`, es
  > la aserción explícita de esa premisa (`WebhookEndpointModel in tenant_scoped_classes()`), que es
  > lo que evita que los tests de aislamiento pasen en silencio contra una tabla que el filtro dejó de
  > cubrir. 12 tests nuevos; 1395 en verde en `tests/integrations` + tenancy + layering.
- [x] 1.4 Ampliar el vocabulario cerrado de `backend/app/audit/domain/actions.py` con la entidad y las
  acciones de este change (creación y rotación del endpoint), y añadirlas a los `frozenset`. Test que
  falla si `AuditLogFactory.build` las rechaza — un vocabulario incompleto lanza `AuditContractError` y
  **aborta la transacción de la operación auditada**. [R2.4]
  > **Más de lo previsto, y era necesario**: el vocabulario cerrado no basta, `ChangeSet` exige además
  > una entrada en `AUDITABLE_FIELDS` (`value_objects.py`). Añadida, y **los dos** secretos van al
  > denylist `REDACTED_FIELDS`: el obvio es `header_secret_encrypted`; el que importa señalar es
  > `token_hash`, que por ser ya un digest parece inocuo pero es la clave de búsqueda de la ruta cuya
  > no-adivinabilidad *es* la regla 12(b) — un par `old`/`new` de digests en `audit_logs` deja registro
  > permanente de todas las rutas que el tenant ha tenido, contra el que un token robado se confirma
  > offline. `header_name` sí se diffea: no es secreto y su cambio es un hecho operativo. 10 tests
  > nuevos, 119 en verde en `tests/audit`.
- [x] 1.5 Casos de uso de alta y rotación en `application/use_cases.py`: generar `webhook_token` con
  `secrets.token_urlsafe(32)`, guardar su SHA-256, cifrar el secreto de cabecera con `EncryptedSecret`,
  escribir el `AuditLog` de la rotación, y devolver los dos valores en claro **una sola vez**. La
  rotación sobrescribe ambos en una transacción, sin ventana de gracia (D3). Tests: el valor viejo deja
  de autenticar; ninguna lectura posterior devuelve el secreto ni enmascarado. [R2.1, R2.2, R2.3, R2.4]
  > **Dos añadidos que la tarea no anticipaba y que el alta necesita**. (1) El **alta se niega** si el
  > tenant ya tiene endpoint para ese proveedor (`WebhookEndpointAlreadyExistsError`), en vez de
  > sobrescribir: `upsert` es la forma correcta para la rotación y la equivocada para un `POST`, que
  > invalidaría material vivo sin decirlo — el proveedor seguiría enviando a la ruta muerta, todo
  > `404` por D4, y el operador leería «creado». Para poder negarse hace falta un método de puerto
  > nuevo, `find_for(tenant_id, provider)`, porque `get` es por id. (2) El secreto de cabecera lo
  > **generamos nosotros** (R2.1 dice generar los dos), con una primitiva propia
  > `generate_header_secret()` junto a las tres de 1.1 — misma entropía que el token y función
  > separada a propósito: son dos defensas que deben poder fallar por separado.
  > El `AuditLog` se escribe también en el **alta** (`WEBHOOK_ENDPOINT_CREATED`), no sólo en la
  > rotación: la acción ya existía en el vocabulario desde 1.4 y una creación sin rastro deja el
  > `WEBHOOK_ENDPOINT_ROTATED` posterior sin origen. 12 tests nuevos; 1523 en verde.
- [ ] 1.6 Endpoints `POST /api/v1/integrations/webhook-endpoints` y `.../{id}/rotate` en
  `api/router.py` + `schemas.py` + `dependencies.py`, con RBAC. Tests de endpoint incluyendo el rechazo
  sin autenticación y con rol insuficiente, y que la respuesta de lectura **no** contiene el material.
  [R2.3, R2.5]
- [ ] 1.7 Regenerar las **dos mitades** del contrato y commitearlas: `make openapi` (backend) y
  `cd frontend && npm run api:generate` (`frontend/lib/api/generated/openapi.d.ts`). Verificar con
  `uv run python -m app.cli.openapi --check`. [documentation.md]

## 2. Recepción autenticada

- [ ] 2.1 Los dos limitadores de D6 en `infrastructure/throttle.py` (por token, generoso; por IP y solo
  para fallos de autenticación, estricto), con el patrón de `RedisLoginThrottle` pero sin reutilizar su
  clase. Config nueva en `core/config.py`: `webhook_rate_limit_per_minute` (120) y
  `webhook_probe_limit_per_minute` (20). Tests de los dos límites por separado, incluido que el tráfico
  legítimo de un proveedor con muchos tenants **no** se estrangula. [R3.1, R3.3, R3.4]
- [ ] 2.2 Tope de tamaño de cuerpo: **sin código nuevo** (D5 corregido). `MaxBodySizeMiddleware` ya cubre
  `/api/v1/` entero, antes del enrutado y por tanto antes de la autenticación, y ya trata el
  `Content-Length` ausente, negativo y no numérico. Esta tarea es sólo el test que lo demuestra **sobre
  la ruta nueva**: cuerpo por encima de `REQUEST_MAX_BYTES` → `413 PAYLOAD_TOO_LARGE` sin fila en
  `webhook_events`, y sin necesidad de token válido. Sin `webhook_max_body_bytes`. [R3.2, R1.7]
- [ ] 2.3 Caso de uso de recepción en `application/webhooks.py`: valida el provider contra `PMSProvider`,
  resuelve el tenant por `token_hash`, compara el secreto con `hmac.compare_digest`, y persiste el
  `WebhookEvent` con `processed=FALSE`. La **decisión** vive aquí, no en el router (D5). Tests sin
  FastAPI de por medio: token desconocido, provider desconocido, cabecera ausente y cabecera incorrecta
  producen el **mismo** resultado indistinguible; y un test que fija que la comparación es de tiempo
  constante (que no usa `==`). [R1.1, R1.2, R1.3, R1.4, R1.5, R1.6]
- [ ] 2.4 `scrub_card_data` en la frontera, antes de construir el `WebhookEvent`, y `error` en forma
  estructurada (código + campo, nunca texto del cuerpo). Tests que pasan los **fixtures reales
  anonimizados** de Beds24 y Channex por el receptor completo y comprueban que `payload` no contiene
  ninguna aguja de tarjeta ni rama opaca. [R4.1, R4.2, R4.3, R4.5]
- [ ] 2.5 Router fino `api/webhooks_router.py` registrado en `main.py`: solo dependencias de transporte
  (límite de tasa, tope de cuerpo) y traducción a `404`/`429`/`413`. Tests de endpoint que fijan el
  `404` uniforme de D4 y que un `202` no lleva cuerpo de negocio. [R1.1, R1.7, R3.1, R3.2]
- [ ] 2.6 Guard automático que **lee los ficheros de fixtures en disco** (no la función que los produce)
  y falla si alguno contiene datos con forma de tarjeta, derivando las agujas del propio anonimizador.
  Cubre **todos** los fixtures, no uno: así es como se filtró un `expiration_date` en
  `channex-staging-adapter`. [R4.4]
- [ ] 2.7 Regenerar las dos mitades del contrato por el endpoint nuevo (`make openapi` +
  `npm run api:generate`) y commitearlas. [documentation.md]

## 3. `special_requests`: la frontera heredada (D8 — provisional)

> Depende de la ratificación de D8 en `BLOCKED.md`. Si Jose elige otra de las alternativas de D8, estas
> dos tareas se reescriben; el resto del change no se ve afectado.

- [ ] 3.1 `infrastructure/free_text.py`: redacción de rachas de 13-19 dígitos ignorando espacios y
  guiones, sin Luhn. **TDD**: el test exige primero que un PAN con y sin separadores desaparezca y que
  una referencia de reserva corta sobreviva; y documenta con un caso el falso positivo aceptado. [R4.1]
- [ ] 3.2 Aplicarlo a `special_requests` **solo en fuentes externas** (webhook y sync de PMS) en
  `infrastructure/{beds24,channex}/mapping.py`, dejando intacto el texto que una persona escribe por la
  API. Tests de los dos caminos: el externo redacta, el manual no. [R4.1]

## 4. Procesamiento asíncrono

- [ ] 4.1 Repositorio de la cola en `infrastructure/repositories.py`, leyendo desde una sesión **nunca
  marcada**. Test que fija que las filas con `tenant_id` NULL son visibles ahí y **no** desde una sesión
  marcada — el comportamiento que `tests/test_tenant_filter.py` ya documenta al revés. [R5.5, R1.8]
- [ ] 4.2 Caso de uso de procesamiento en `application/webhooks.py`: lee el lote, agrupa por tenant, y
  abre **una sesión marcada por tenant, nunca re-marcada**, extrayendo el helper de
  `app/scheduler/runner.py` en vez de usar `run_for_every_tenant` (que itera todos los tenants activos).
  Aislamiento por evento: uno que falla no arrastra a los demás. Alimenta `ReservationIngestor` como
  única ruta de upsert. Tests de los dos aislamientos (por evento y por tenant). [R5.1, R5.2, R5.4, R5.5]
- [ ] 4.3 Reintentos: `attempts < 3` en la selección, incremento y `next_attempt_at = now + backoff` al
  fallar, `error` estructurado al agotarlos. Tests: los tres reintentos con su espaciado creciente, que
  el cuarto no ocurre, y que un evento agotado **no** vuelve a seleccionarse en cada tick. Incluye la
  rama de `tenant_id` NULL de D11 (se cuenta, se marca agotada, no bucle infinito). [R5.3, R1.8]
- [ ] 4.4 Coalescing: agrupar el lote por destino de re-lectura y emitir **una** llamada por destino
  distinto y por ejecución. Tests: N avisos del mismo destino producen una sola llamada, y un test que
  fija que **el puerto del adapter no se toca desde el router** (R6.3). [R6.1, R6.2, R6.3]
- [ ] 4.5 Re-lectura por API a través del `pms_factory` existente, sin auditoría propia: reutiliza la
  granularidad "una fila por credencial distinta y por ejecución" que ya implementa el caso de uso de
  sync (D14). Test que lo verifica sobre una ejecución con varias propiedades servidas por una misma
  credencial de cuenta. [R6.4, R6.1]
- [ ] 4.6 Transición y causalidad: invocar `AdvancePropertyStatesUseCase` **sin modificarlo** con
  `trigger=RESERVATION_CANCELLED_BEFORE_CHECKIN` (primer llamante en producción), y escribir el
  `TimelineEvent` de la ingesta con `actor_type=TimelineActorType.WEBHOOK` y una constante
  `WEBHOOK_SOURCE` nueva junto a `PMS_SOURCE`/`CSV_SOURCE`. Tests: la transición persiste su
  `PropertyStateTransition` **y** su `TimelineEvent` en la misma transacción, y la cadena causal es
  legible (evento → timeline de ingesta con actor `WEBHOOK` → transición con actor `SYSTEM`). Si esto
  exige tocar `app/properties/`, **es un `DESIGN-CONFLICT` y hay que parar** (D12). [R5.6]
- [ ] 4.7 Desorden: test que procesa dos avisos del mismo objeto en orden inverso y comprueba que el
  estado final es el mismo, apoyándose en la idempotencia por `(tenant_id, external_pms_id)` y en que el
  dato viene de la re-lectura y no del cuerpo. [R5.7, R6.1]
- [ ] 4.8 Registrar `process_webhook_events` en `CADENCES` (`app/scheduler/schedule.py`, 60 s) y la tarea
  Celery en `app/scheduler/tasks.py` con su lock, siguiendo el patrón `_guarded`. Test de que
  `beat_schedule` y el TTL del lock se derivan de `CADENCES` sin números duplicados. [R5.1]

## 5. Documentación

- [ ] 5.1 `.env.example` con las tres variables nuevas, con nombre y comentario (llevan default: no son
  secretos, `security.md` regla 8). README raíz si cambia estructura o comandos. [documentation.md]
- [ ] 5.2 `docs/reservations-webhooks.md`: cómo se opera — obtener la URL y el secreto, pegarlos en el
  panel del proveedor, rotar, y qué hacer cuando la rotación deja avisos perdidos (el sondeo de
  `pms_sync` los recupera). Marcar `ASSUMPTION` la forma de D8 y `EXTERNAL_DEPENDENCY` la cabecera
  estática sin verificar. [documentation.md]

## 6. Verification

- [ ] 6.1 Suite completa del backend: `docker compose exec backend uv run pytest -q -rs`
  (project.md; el stack corre en Docker y `uv` no está en el host).
- [ ] 6.2 Migraciones íntegras, con los tres comandos que corre el CI:
  `uv run alembic upgrade head`, `uv run alembic check`, `uv run alembic downgrade base`.
- [ ] 6.3 Contrato sin deriva en sus dos mitades: `uv run python -m app.cli.openapi --check` y
  `cd frontend && npm run api:generate` sin cambios pendientes en
  `frontend/lib/api/generated/openapi.d.ts`.
- [ ] 6.4 Comprobación manual del flujo, **sin navegador** (un worktree no publica puertos): dar de alta
  un endpoint por API, hacer `POST` al receptor desde dentro del stack con token y cabecera correctos y
  ver la fila en `webhook_events` con `processed=FALSE`; repetir con token incorrecto y ver el `404`;
  disparar el job y ver `processed=TRUE`.

> **Sin tarea de lint/typecheck a propósito.** Ni el `Makefile` ni `.github/workflows/backend-tests.yml`
> definen ninguno para el backend (no hay ruff ni mypy configurados), así que inventar un comando aquí
> sería inventarse la validación del proyecto (regla compartida 9). El typecheck que sí existe es el del
> frontend contra el contrato derivado, cubierto por 6.3.
