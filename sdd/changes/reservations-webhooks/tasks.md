# Tasks: reservations-webhooks

Orden pensado para que el sistema siga en pie al cerrar cada sección: primero el material que la
autenticación necesita (§1), luego la recepción que lo usa (§2), la frontera de texto libre que la
recepción destapa (§3), y por último el procesamiento asíncrono (§4). Hasta §4 el sistema tiene una cola
que se llena y nadie vacía — que es exactamente el estado que PRD §16 describe (`processed=FALSE`), no
una rotura.

Cada tarea incluye su test. TDD obligatorio en `domain/` con invariante real (`steering/testing.md`), no
forzado en `infrastructure/`.

## 1. Endpoint de webhook: entidad, esquema y administración <!-- panel: PASS 2026-08-08 -->

> **Panel de la sección 1 (siete reviewers, un solo mensaje): PASS.** `sdd-architect`, `sdd-review-tenancy`,
> `sdd-review-cicd`, `sdd-review-documentation` y `sdd-review-i18n` sin hallazgos. Tres aceptados y
> arreglados antes de cerrar:
> - **QA, medio — carrera check-then-act en el alta.** `find_for` + `upsert` sin bloqueo entre medias: dos
>   altas concurrentes para el mismo `(tenant, provider)` pasaban las dos la lectura, y la perdedora
>   moría con `IntegrityError` sin manejador — un `500` donde la operación promete `409`. Reproducida por
>   el panel con dos sesiones. Arreglado donde tenía que estarlo: **el índice es la autoridad sobre el
>   duplicado, no la lectura previa** — `upsert` hace `flush` y traduce la violación de
>   `uq_webhook_endpoints_tenant_provider` a `WebhookEndpointAlreadyExistsError`, con el mismo patrón que
>   `SqlAlchemyPropertyRepository.add` ya usa. El `flush` además pone el fallo **antes** de construir la
>   fila de auditoría, así que un alta rechazada no deja rastro de algo que no ocurrió. Test con
>   concurrencia real (`asyncio.gather` sobre dos sesiones); nada más débil lo reproduce.
> - **QA, bajo — cobertura del guard de `_to_endpoint`.** Sólo se probaba la rama del ciphertext
>   malformado, no las de `token_hash` que no es digest ni `header_name` en blanco, que ninguna
>   constraint de columna impide. Test parametrizado para las dos.
> - **Seguridad, medio — el canal de la exención de auditoría.** Ver entrada 3 de `BLOCKED.md` y D15:
>   la decisión es buena, el sitio donde estaba tomada no. Queda propuesta para Jose; el test que fijaba
>   la ausencia como política permanente se acotó a su premisa.

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
- [x] 1.6 Endpoints `POST /api/v1/integrations/webhook-endpoints` y `.../{id}/rotate` en
  `api/router.py` + `schemas.py` + `dependencies.py`, con RBAC. Tests de endpoint incluyendo el rechazo
  sin autenticación y con rol insuficiente, y que la respuesta de lectura **no** contiene el material.
  [R2.3, R2.5]
  > **El permiso elegido, que el diseño no fijaba: `MANAGE_TENANT_SETTINGS`** (sólo `TENANT_OWNER`), no
  > el `MANAGE_RESERVATIONS` que usa el import de CSV al lado. Acuñar este material decide **quién
  > puede escribir en el tenant desde internet**, para todas las propiedades a la vez; eso es
  > configuración del tenant («configurar preferencias del tenant», PRD §6), no operar reservas. Sin
  > permiso nuevo, siguiendo el precedente que dejó `reservations` («un permiso que nadie razona por
  > separado es uno que nadie administra»). El test parametriza los tres roles que **no** deben poder,
  > incluido `PROPERTY_MANAGER`, que es la relajación plausible.
  > **No hay endpoint de lectura**, y por eso la última cláusula de la tarea se verifica por ausencia:
  > la regla 3(a) permite entregar el material «una sola vez», y una lectura enmascarada sería una
  > segunda serialización que la excepción no cubre. Se documenta en el schema.
  > **La URL absoluta sale de `request.base_url`**, no de configuración nueva: no existe un ajuste de
  > origen público y añadirlo sería la tercera perilla contra la que argumenta D5. No es inyección de
  > `Host`: la cabecera es de la petición del propio operador autenticado.
  > `test_route_authorization.py` lleva las dos rutas nuevas en su snapshot, con la nota de que el
  > receptor de §2 irá al allowlist anónimo y no aquí. 14 tests nuevos.
- [x] 1.7 Regenerar las **dos mitades** del contrato y commitearlas: `make openapi` (backend) y
  `cd frontend && npm run api:generate` (`frontend/lib/api/generated/openapi.d.ts`). Verificar con
  `uv run python -m app.cli.openapi --check`. [documentation.md]
  > **`npm run api:generate` no corre en el host de un worktree**: las dependencias del frontend viven
  > en el volumen `frontend_node_modules`, no en el árbol (project.md § Worktree bootstrap), así que
  > el comando documentado falla con `ERR_MODULE_NOT_FOUND`. Se generó dentro del contenedor
  > `frontend`, alimentándole `backend/openapi.json` por stdin en la ruta que el script espera. Las
  > dos mitades pasan su `--check`; el diff del `.d.ts` es puramente aditivo (+131, −0).

## 2. Recepción autenticada

- [x] 2.1 Los dos limitadores de D6 en `infrastructure/throttle.py` (por token, generoso; por IP y solo
  para fallos de autenticación, estricto), con el patrón de `RedisLoginThrottle` pero sin reutilizar su
  clase. Config nueva en `core/config.py`: `webhook_rate_limit_per_minute` (120) y
  `webhook_probe_limit_per_minute` (20). Tests de los dos límites por separado, incluido que el tráfico
  legítimo de un proveedor con muchos tenants **no** se estrangula. [R3.1, R3.3, R3.4]
  > **La aritmética de los dos límites no es la misma, y confundirla fue el primer error**: el de
  > entrega *es* el intento, así que se cuenta a sí mismo (`<=`, como `ip_attempt_allowed`); el de
  > sondeo pregunta por fallos **ya cometidos**, así que es estricto (`<`) — con `<=` regalaba un
  > intento de más. `probe_allowed` además **lee sin incrementar**: si preguntar contase, el tráfico
  > bueno del proveedor gastaría el presupuesto de fallos y se auto-bloquearía. 10 tests, contra el
  > Redis real del stack y sin `skip`, por el motivo que ya dejó escrito `tests/auth/test_throttle.py`.
  > Dos de ellos fijan la **dirección** de la asimetría (el generoso es el de token) y que agotar uno
  > no toca al otro: intercambiar los dos números deja todo lo demás en verde y reintroduce
  > exactamente el estrangulamiento multi-tenant que D6 rechaza.
- [x] 2.2 Tope de tamaño de cuerpo: **sin código nuevo** (D5 corregido). `MaxBodySizeMiddleware` ya cubre
  `/api/v1/` entero, antes del enrutado y por tanto antes de la autenticación, y ya trata el
  `Content-Length` ausente, negativo y no numérico. Esta tarea es sólo el test que lo demuestra **sobre
  la ruta nueva**: cuerpo por encima de `REQUEST_MAX_BYTES` → `413 PAYLOAD_TOO_LARGE` sin fila en
  `webhook_events`, y sin necesidad de token válido. Sin `webhook_max_body_bytes`. [R3.2, R1.7]
  > **Medido, no supuesto — y D5 afirmaba de más.** El middleware tiene dos caminos: un
  > `Content-Length` declarado por encima del tope se rechaza al instante, y uno ausente, negativo o
  > no numérico cae al **conteo del stream**. Ese contador sólo avanza cuando algo **lee** el cuerpo, y
  > Starlette contesta `404` a una ruta inexistente sin llegar a llamar a `receive()`. Así que hoy, sin
  > el router de 2.5, un `Content-Length` mentiroso da `404` y no `413`. No es un agujero —un cuerpo que
  > no se lee no se materializa, que es lo que protege R1.7— pero significa que esa mitad sólo es
  > observable cuando hay ruta que lea: su test se escribe en 2.5. Las otras tres afirmaciones
  > (413 con envelope, sin token válido, sin fila en `webhook_events`) sí se verifican ya. 3 tests.
- [x] 2.3 Caso de uso de recepción en `application/webhooks.py`: valida el provider contra `PMSProvider`,
  resuelve el tenant por `token_hash`, compara el secreto con `hmac.compare_digest`, y persiste el
  `WebhookEvent` con `processed=FALSE`. La **decisión** vive aquí, no en el router (D5). Tests sin
  FastAPI de por medio: token desconocido, provider desconocido, cabecera ausente y cabecera incorrecta
  producen el **mismo** resultado indistinguible; y un test que fija que la comparación es de tiempo
  constante (que no usa `==`). [R1.1, R1.2, R1.3, R1.4, R1.5, R1.6]
  > **Un agujero que sólo apareció al probarlo, y era el oráculo de D4 por otra puerta.** Una fila
  > dañada no falla en el `decrypt` del caso de uso: falla antes, en `_to_endpoint`, dentro de
  > `find_by_token_hash`. Sin capturar `SecretDecryptionError` **también ahí**, un `500` le decía a un
  > llamante anónimo «esta ruta existe y su material está roto». Capturado en `_resolve`.
  > **`scrub_card_data` se inyecta, no se importa** (ajuste a D7). D7 dice que el caso de uso
  > descarta los datos de tarjeta antes de construir el `WebhookEvent` reutilizando esa función,
  > pero vive en `infrastructure/` y
  > `test_application_modules_reach_infrastructure_only_through_ports` prohíbe a esta capa importar
  > un adaptador concreto. Se pasa por constructor, **obligatorio y sin default**: un default
  > "no hacer nada" convertiría la obligación PCI de la regla 13(a) en opt-in. Mover `card_data.py`
  > a `domain/` sería lo ortodoxo pero toca módulos de otros dos changes sin necesidad.
  > Se adelanta aquí el descarte de tarjeta (2.4 lo prueba con fixtures reales) para que **no exista
  > en ningún momento** un camino de escritura sin depurar. `event_type` se trunca a 200 y cae a
  > `"unknown"`: lo llena un anónimo y la columna es `NOT NULL` `String(200)`, así que sin acotarlo
  > una etiqueta de 10 KB aborta la transacción que estaba registrando el aviso. 12 tests nuevos.
- [x] 2.4 `scrub_card_data` en la frontera, antes de construir el `WebhookEvent`, y `error` en forma
  estructurada (código + campo, nunca texto del cuerpo). Tests que pasan los **fixtures reales
  anonimizados** de Beds24 y Channex por el receptor completo y comprueban que `payload` no contiene
  ninguna aguja de tarjeta ni rama opaca. [R4.1, R4.2, R4.3, R4.5]
  > **Mi primer borrador afirmaba lo que no dice la regla y fallaba contra código correcto**:
  > `scrub_card_data` sustituye el **valor** por un marcador y conserva la clave. Eso es justo la
  > forma estructurada que pide la regla 11 («el valor no sobrevive»), y además distingue «el
  > proveedor no mandó esto» de «se lo quitamos nosotros». Los tests aserotan sobre valores.
  > `error` no se resuelve con una convención sino con un tipo: `WebhookEventFailure` lleva un
  > `code` de vocabulario cerrado y un **nombre** de campo, y **no tiene ningún campo de texto
  > libre**, así que el mensaje de diagnóstico natural —interpolar lo que falló— es imposible de
  > escribir. Es lo que impide que un PAN retirado de `payload` vuelva por la columna de al lado.
  > 11 tests nuevos, incluido uno que planta la forma exacta que midió `channex-staging-adapter`
  > anidada dentro de una lista, que es donde un scrubber no recursivo aprueba sus propios tests.
- [x] 2.5 Router fino `api/webhooks_router.py` registrado en `main.py`: solo dependencias de transporte
  (límite de tasa, tope de cuerpo) y traducción a `404`/`429`/`413`. Tests de endpoint que fijan el
  `404` uniforme de D4 y que un `202` no lleva cuerpo de negocio. [R1.1, R1.7, R3.1, R3.2]
- [x] 2.6 Guard automático que **lee los ficheros de fixtures en disco** (no la función que los produce)
  y falla si alguno contiene datos con forma de tarjeta, derivando las agujas del propio anonimizador.
  Cubre **todos** los fixtures, no uno: así es como se filtró un `expiration_date` en
  `channex-staging-adapter`. [R4.4]
- [x] 2.7 Regenerar las dos mitades del contrato por el endpoint nuevo (`make openapi` +
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
