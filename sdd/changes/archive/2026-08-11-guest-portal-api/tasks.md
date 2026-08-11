# Tasks: guest-portal-api

> Orden pensado para que el sistema quede funcionando al final de cada sección:
> §1-§3 añaden esquema y puertos sin exponer nada; §4 da la vía de operador
> (utilizable ya, aunque el portal no exista); §5-§7 abren la superficie anónima
> ruta a ruta; §8 cierra contrato y documentación.
>
> Todo test de backend se escribe en `backend/tests/<dominio>/` y se corre con
> `docker compose exec backend uv run pytest` desde **este** worktree
> (`sdd/project.md` § Worktree bootstrap: el stack del principal serviría el
> código del principal).

## 1. Esquema, primitivas y configuración <!-- panel: PASS 2026-08-10 -->

<!-- Panel de 5 (architect, security, qa, tenancy, documentation). Ronda 1: architect y
     documentation PASS; security 3 hallazgos, tenancy 2, qa 1 (con solape). Arreglados:
     FK compuesta (tenant_id, reservation_id) contra uq_reservations_tenant_id_id — la
     primera FK compuesta del repo, aprobada por Jose; CHECK
     ck_audit_logs_actor_guest_token_hash_is_a_digest más re-validación en el repositorio;
     y cuatro tests que conducen Postgres en vez de leer metadata. Ronda 2: los tres
     reviewers re-verificaron contra la base de datos (tenancy reejecutó su sonda de
     inserción) y cerraron todo. PASS. -->


- [x] 1.1 **TDD** — `backend/app/guests/domain/portal_token.py` (nuevo) con
  `generate_guest_token()` (`secrets.token_urlsafe(32)`) y `hash_guest_token()`
  (SHA-256 hex, 64 chars, sin sal), calcado de
  `app/integrations/domain/webhook_auth.py`. Test primero en
  `backend/tests/guests/test_portal_token.py`: entropía/longitud, hash
  determinista de 64 hex, tokens distintos en llamadas sucesivas, y que el
  módulo es stdlib puro (sin import de infra). [R1.1, R1.2] (D2)
- [x] 1.2 `GuestAccessTokenModel` en
  `backend/app/guests/infrastructure/models.py`: `Base` + `UUIDPrimaryKeyMixin`
  + `TenantScopedMixin` + `TimestampMixin`, `reservation_id` FK
  `ON DELETE RESTRICT` NOT NULL, `token_hash VARCHAR(64)` con índice **UNIQUE
  global**, `revoked_at TIMESTAMPTZ NULL`, más el índice único parcial
  `uq_guest_access_tokens_live_per_reservation` sobre `(reservation_id) WHERE
  revoked_at IS NULL`. Test en `backend/tests/guests/test_models.py`: columnas,
  unicidad global y parcial declaradas. [R1.1, R1.5] (D2)
- [x] 1.3 Columna `actor_guest_token_hash VARCHAR(64) NULL` en
  `backend/app/audit/infrastructure/models.py`, propagada a la entidad de
  `backend/app/audit/domain/entities.py` y rellenada por `AuditLogFactory.build`
  en `backend/app/audit/domain/services.py` desde `GuestActor.token_hash`. Tests
  en `backend/tests/audit/`: un actor con `token_hash` produce la fila con la
  columna puesta y `actor_user_id = NULL`; el índice
  `ix_audit_logs_tenant_id_actor_user_id_created_at` no se toca. [R6.1] (D11)
- [x] 1.4 Valor `GUEST_CHECKIN_COMPLETED` en `TimelineEventType`
  (`backend/app/timeline/domain/enums.py`), con su test de pertenencia al enum en
  `backend/tests/timeline/`. [R6.3] (D12)
- [x] 1.5 Migración única `backend/alembic/versions/<rev>_guest_portal_api.py`:
  tabla `guest_access_tokens` con sus dos índices, columna
  `audit_logs.actor_guest_token_hash`, y el `ALTER TYPE timeline_event_type ADD
  VALUE IF NOT EXISTS` **sin** `autocommit_block()`, siguiendo al precedente que
  esta tarea citaba (`b7c41d92e5a3_session_revoked_reason_administrative.py`), que
  ya documenta que en PostgreSQL 12+ lo prohibido es *usar* el valor nuevo en la
  transacción que lo añade, no añadirlo — y esta migración no escribe ninguna fila
  de `timeline_events`. **Corregido en run** (la redacción anterior pedía el bloque
  autocommit): `backend/alembic/env.py` envuelve toda la tanda en un solo
  `context.begin_transaction()`, así que abrirlo comitearía las revisiones
  anteriores y `upgrade head` dejaría de ser todo-o-nada. `downgrade()` revierte
  tabla y columna; documentar en el propio fichero por qué el valor de enum no se
  retira. Verificar `uv run alembic check`, `upgrade head` y `downgrade base`, y
  que `backend/tests/test_migrations.py` y `test_models_registry.py` pasan.
  [R1.1, R1.5, R6.1, R6.3] (D2, D11, D12, Riesgos)
- [x] 1.6 **Cuatro** settings en `backend/app/core/config.py` con sus defectos —
  `guest_portal_token_grace_days=2`, `guest_portal_rate_limit_per_minute=60`,
  `guest_portal_probe_limit_per_minute=20` y
  `guest_portal_support_channel=None` — y sus entradas comentadas (nombre, sin
  valor sensible) en `.env.example`. Test en
  `backend/tests/test_config.py`. [R1.3, R2.4, R3.1] (D3, D6, D9,
  steering/documentation)

  El cuarto se añadió en §6 (decisión de Jose): esta tarea enumeraba tres y D9
  define `support_channel` como «constante de configuración», así que el cableado
  lo dejaba fijo a `None` y el campo viajaba en el contrato como `required` sin que
  ningún huésped pudiera recibir valor nunca. Lo encontraron los paneles de
  arquitectura y documentación de §6. El defecto sigue siendo `None` a propósito:
  un `support@example.com` de relleno se publicaría a todos los huéspedes de todo
  tenant que olvidara configurarlo.

## 2. Vocabulario de auditoría y permiso de operador <!-- panel: PASS 2026-08-10 -->

<!-- Panel de 5. Ronda 1: architect, tenancy y documentation PASS; security y qa
     convergieron en el mismo hallazgo por separado — `full_name` estaba en el allowlist y
     no en la denylist, así que `diff("full_name", …)` era legal y a partir de §6 ese texto
     lo teclea un anónimo. Arreglado (decisión de Jose): `full_name` y `nationality` entran
     en `REDACTED_FIELDS`; `nationality` no la introduce este change pero sí le cambia la
     premisa, así que hubo que invertir el test de `access-notifications` que fijaba la
     decisión contraria y corregir tres copias más de la redacción vieja. Ronda 2: ambos
     cerraron. Security encontró además una cuarta copia en `sdd/specs/access-notifications.md`
     que NO se toca ahora a propósito — las specs describen lo desplegado — y queda anotada
     en la proposal para `/sdd:archive`. PASS. -->


- [x] 2.1 `backend/app/audit/domain/actions.py`: `ENTITY_INCIDENT = "INCIDENT"` +
  `INCIDENT_CREATED`; `ENTITY_GUEST_ACCESS_TOKEN` +
  `GUEST_ACCESS_TOKEN_ISSUED` / `GUEST_ACCESS_TOKEN_REVOKED`. En
  `backend/app/audit/domain/value_objects.py`:
  `AUDITABLE_FIELDS["INCIDENT"] = {"source", "status", "reservation_id"}` (**no**
  `title` ni `description`), `AUDITABLE_FIELDS["GUEST_ACCESS_TOKEN"] =
  {"token_hash", "revoked_at"}`, y `full_name` añadido a
  `AUDITABLE_FIELDS["GUEST"]` auditado como `redacted()`. Tests: `diff()` sobre
  `token_hash` lanza (ya está en `REDACTED_FIELDS`), un campo fuera del allowlist
  se rechaza, `full_name` se audita redactado. **No** se añade acción de check-in:
  la operación es `GUEST_DOCUMENT_UPDATED`. [R6.1, R6.4] (D10, D11)
- [x] 2.2 Permiso `MANAGE_GUEST_ACCESS_TOKENS` en
  `backend/app/auth/domain/policy.py`, concedido a `TENANT_OWNER` y
  `PROPERTY_MANAGER` y a nadie más. Test de reparto por rol en
  `backend/tests/auth/`. [R1.1, R1.4] (D14)

## 3. Puertos y adaptadores del portal <!-- panel: PASS 2026-08-10 -->

<!-- Panel de 5. Ronda 1: architect y documentation PASS; security 4 hallazgos (2
     bloqueantes), tenancy 1, qa 4. Dos de fondo, ambos reproducidos en vivo:
     (a) `stay_info` filtraba `tenant_id` en `reservations` pero NO en el join a
     `properties` — en sesión sin marcar devolvía nombre, WiFi e instrucciones de acceso de
     otro tenant; arreglado con el filtro explícito y un test que corre deliberadamente sin
     marcar, porque con la sesión marcada la red lo habría tapado. (b) `set_guest` aceptaba
     un huésped de otro tenant — misma forma que §1; cerrado con FK compuesta
     `(tenant_id, guest_id)` contra `uq_guests_tenant_id_id` (decisión de Jose). El esquema
     de `reservations.property_id` queda fuera de alcance a propósito y anotado como
     invariante en la proposal: este change no lo escribe. Resto: desempate por `id` en
     `_access_code`, tres tests de cobertura, y el docstring de `find_by_email_globally`
     que decía ser «THE ONLY unscoped query». Ronda 2: los tres reviewers re-verificaron
     contra el esquema reconstruido (incluida la semántica MATCH SIMPLE) y cerraron todo.
     PASS. -->


- [x] 3.1 `backend/app/guests/domain/portal_ports.py` (nuevo): puerto
  `GuestAccessTokenRepository`, puerto de lectura `GuestPortalStayReader`, y los
  `frozen dataclass` `StayInfo` (exactamente los campos de la tabla de D9, ni uno
  más) y `GuestSession` (tenant, reserva, propiedad, huésped, `token_hash`).
  `backend/tests/test_layering.py` debe seguir pasando: `domain/` sin imports de
  infraestructura. [R1.1, R2.1, R3.2] (D2, D4, D9)
- [x] 3.2 Método estrecho `set_guest(reservation_id, guest_id)` junto a
  `set_status` en `LegalRegistrationStayStore`
  (`backend/app/guests/domain/ports.py`), con su implementación en
  `backend/app/guests/infrastructure/legal.py` — escribe **solo**
  `reservations.guest_id`, sin ensanchar el puerto a la reserva entera. Test en
  `backend/tests/guests/test_repositories.py`. [R4.2] (D10, OQ3)
- [x] 3.3 `backend/app/guests/infrastructure/portal_repositories.py` (nuevo):
  implementación SQLAlchemy de `GuestAccessTokenRepository` — alta, revocación y
  la consulta por `token_hash` sobre sesión **sin marcar** (aún no hay tenant;
  misma situación que `find_by_email_globally`, `app/core/db.py:79-86`). Tests de
  integración en `backend/tests/guests/test_repositories.py`: la consulta global
  resuelve el tenant, dos tokens vivos sobre la misma reserva dan
  `IntegrityError`, y un token de otro tenant no se cuela una vez marcada la
  sesión. [R1.5, R2.5] (D2, D4)
- [x] 3.4 Implementación de `GuestPortalStayReader` en el mismo fichero: proyecta
  `StayInfo` desde `reservations` + `properties` + `access_records`, con
  *fallback* de `check_in_time`/`check_out_time` a
  `properties.default_check_*_time`, `wifi_name` (**nunca**
  `wifi_password_encrypted`), `arrival_notes` desde `properties.access_notes`,
  `access_code_masked` desde `access_records.code_masked` si hay registro vivo, y
  `support_channel` de configuración. Test estructural: el conjunto de campos de
  `StayInfo` es exactamente el esperado, y no contiene `internal_notes`,
  `gross_amount`, `ota_commission`, `net_amount`, `external_pms_id`,
  `external_channel_id` ni `document_number`. [R3.1, R3.2, R3.3] (D9)

## 4. Emisión y revocación (ruta de operador, JWT) <!-- panel: PASS 2026-08-10 -->

<!-- Panel de 5. Ronda 1: tenancy PASS; security 1, qa 4, documentation 2, architect 1.
     El de fondo era de seguridad y sutil: el handler traducía `IntegrityError` a 409
     comparando el nombre de la constraint como **substring del mensaje del driver**, y
     asyncpg incluye la línea DETAIL con el valor de la fila — así que un `internal_code`
     que deletreara la constraint hacía que un duplicado cualquiera, en cualquier parte de
     la app, respondiera «reintenta». Ahora compara `exc.orig.__cause__.constraint_name`.
     QA confirmó sin suavizarlo que la cobertura de API no bastaba para 4.1: van 12
     unitarios con fakes que fijan revoke-antes-de-add, audit-antes-de-commit y un solo
     commit — nada de eso es alcanzable por HTTP porque el índice parcial tapa el orden malo
     como un 409. Ronda 2: los tres cerraron; QA dejó dos residuales de una línea (el guard
     `walked >= 5` lo satisfacían 7 rutas irrelevantes, y faltaba el `entity_id` del lado de
     emisión), ambos arreglados. El hallazgo del architect —los dos casos de uso usan
     `LegalRegistrationStayStore` solo para comprobar existencia— se aplaza a 5.1 con
     obligación explícita, porque su resolución es el puerto de proyección que D4 asigna a
     §5 y que necesita el `status` de la reserva, no el legal. PASS.

     Nota de proceso: `test_openapi_contract.py` se puso rojo al añadir los dos endpoints,
     así que regenerar las dos mitades del contrato es obligación **por sección**, no de
     cierre. Anotado en 8.1. -->


- [x] 4.1 `IssueGuestAccessTokenUseCase` y `RevokeGuestAccessTokenUseCase` en
  `backend/app/guests/application/portal.py` (nuevo). La emisión **revoca y crea
  dentro de la misma transacción** (sustitución explícita de R1.5), devuelve el
  valor en claro **una sola vez** y escribe `GUEST_ACCESS_TOKEN_ISSUED`; la
  revocación pone `revoked_at` y escribe `GUEST_ACCESS_TOKEN_REVOKED`. Tests
  unitarios: reemisión sobre una reserva con token vigente deja exactamente un
  token vivo, el `AuditLog` lleva el hash redactado y nunca el valor. [R1.1,
  R1.4, R1.5, R6.1] (D14, Riesgos)
- [x] 4.2 Rutas `POST` y `DELETE /api/v1/reservations/{reservation_id}/guest-access-token`
  en `backend/app/guests/api/router.py`, con sus schemas en
  `backend/app/guests/api/schemas.py`, cableado en `dependencies.py` y traducción
  de `IntegrityError` a `409 CONFLICT` en `errors.py`. Tests de API en
  `backend/tests/guests/test_api.py`: el token en claro aparece en la respuesta de
  emisión y **en ninguna lectura posterior**, un rol sin
  `MANAGE_GUEST_ACCESS_TOKENS` recibe `403`, y un operador del tenant A no puede
  emitir sobre una reserva del tenant B. [R1.1, R1.4, R1.5] (D14,
  steering/security regla 3a)

## 5. Autorización, límite de tasa y redacción de logs <!-- panel: PASS 2026-08-10 -->

<!-- Panel de 5. Ronda 1: documentation y tenancy PASS; security 4 hallazgos, qa 2,
     architect 1 (DESIGN-CONFLICT). Lo importante:
     (a) el docstring afirmaba «la estancia se resuelve incondicionalmente» y el código
         lanzaba antes de resolverla cuando no había fila — «desconocido» costaba una
         consulta y «muerto» dos, justo la asimetría que §3 dejó vinculante. Arreglado: los
         dos lookups corren siempre, el fallido contra ids que no resuelven.
     (b) `find_live_by_token_hash` cargaba el modelo entero, así que la seguridad del mapa de
         identidad dependía del refcounting de CPython. Ahora selecciona columnas: garantía
         estructural, reverificada por tenancy.
     (c) DESIGN-CONFLICT del architect: la regla de vigencia vivía en `application/`.
         Aprobado por Jose, extraída a `domain/portal_authorisation.py` como servicio de
         dominio (cruza dos entidades). D3 y D4 corregidos. Ganancia real: 12 tests puros de
         frontera que antes eran incómodos, incluida la parametrización sobre todos los
         `ReservationStatus`.
     (d) `now` naive se rechaza por adelantado: si no, reventaba solo en la rama que alcanzan
         los tokens que resuelven — un oráculo de existencia limpio.
     (e) Los dos adaptadores nuevos no tenían ningún test; ahora tienen siete de integración.
     El hallazgo 4 de security (TOCTOU del probe) se **retiró**: su premisa era que
     `RedisWebhookThrottle` cobra en un solo `INCR`, y no es así — ese es el de login, que
     cuenta intentos. Documentado como ASSUMPTION en vez de divergir del precedente que D6
     manda copiar. Ronda 2: los tres re-verificaron y cerraron. PASS.

     Las nueve restricciones que security dejó para §6/§7 están en la tarea 6.1. -->


- [x] 5.1 `GuestPortalAuthenticator` en
  `backend/app/guests/application/portal.py` con
  `authorize(token, now) -> GuestSession`, en el orden fijo de D4: hash → fila por
  `token_hash` sin marcar → proyección de la reserva → las tres comprobaciones
  (`revoked_at IS NULL`, `status is not CANCELLED`, `now <= medianoche UTC de
  check_out_date + grace_days`) → `bind_session_to_tenant` → `GuestSession`
  congelado. Tests unitarios de las cinco condiciones de rechazo (inexistente,
  mal formado, revocado, fuera de ventana, reserva `CANCELLED`) y de que
  tenant/reserva/propiedad salen **solo** de la fila del token. [R1.3, R1.4,
  R2.1, R2.2, R2.5] (D3, D4)

  **Restricción del panel de seguridad de §3, vinculante aquí.** El adaptador
  distingue «token desconocido» (una consulta) de «conocido pero muerto» (al menos
  dos, porque hay que leer la estancia para calcular la ventana). Es un oráculo de
  *confirmación* —no de adivinación: con 256 bits no hay nada que adivinar—, pero
  D5 exige que las cinco causas sean indistinguibles y el cuerpo constante solo
  cubre el cuerpo. El autorizador **no debe**: resolver la estancia solo cuando el
  hash existe (resolverla siempre y ramificar después); cobrar el límite por token
  únicamente a los hashes que resuelven; escribir `AuditLog` en un camino cuya
  latencia o respuesta difiera del camino desconocido; ni lanzar un tipo de
  excepción distinto por causa. Lo que lo fija es un test que compare la **forma de
  la respuesta** entre las cinco condiciones de rechazo, no solo su código.

  **Y la proyección que esta tarea debe estrenar, con una deuda de §4 colgando de
  ella.** D4 paso 2 pide `reservation_id`, `tenant_id`, `property_id`, `guest_id`,
  `check_in_date`, `check_out_date` y **`status`** — el de la reserva
  (`ReservationStatus`, para detectar `CANCELLED`), que **no** es el de
  `LegalRegistrationStay` (ese es `LegalRegistrationStatus`). Así que hace falta un
  puerto de lectura nuevo en `portal_ports.py`, no vale reutilizar
  `LegalRegistrationStayStore`.

  Cuando exista, **mover a él los dos casos de uso de §4**: hoy
  `IssueGuestAccessTokenUseCase` y `RevokeGuestAccessTokenUseCase` llaman a
  `LegalRegistrationStayStore.get(...)` solo para comprobar existencia y tenant, y
  descartan el resultado. Funciona y filtra bien —lo verificaron los paneles de
  seguridad, QA y tenancy—, pero el architect de §4 lo marcó con razón contra la
  segregación de interfaces: ese puerto se documenta a sí mismo como «one column of
  `reservations`, and no more», con un rol que no es este. Se aplazó a esta tarea
  precisamente para no inventar aquí un puerto que D4 ya asigna a §5.

  **Y la disciplina que §3 dejó implícita**: el autorizador lee dos filas con la
  sesión sin marcar. Ninguna instancia ORM puede sobrevivir a
  `bind_session_to_tenant` — hay que convertir a dataclass y soltar la referencia,
  como hace `find_live_by_token_hash`. Seguridad y tenancy comprobaron que hoy la
  fila no persiste en el mapa de identidad, pero por refcounting de CPython sobre un
  `WeakInstanceDict`, no por ninguna garantía estructural: es el límite 4 de
  `app/core/db.py`, y basta con que un llamante retenga la fila para reabrirlo.
- [x] 5.2 `RedisGuestPortalThrottle` en
  `backend/app/guests/infrastructure/portal_throttle.py` (nuevo), con la forma de
  `RedisWebhookThrottle` pero clase propia: límite por IP contado **solo sobre
  autorizaciones fallidas** y preguntado antes de cualquier trabajo, y límite por
  token cobrado **después** de autorizar usando el hash ya almacenado (nunca
  re-hasheando el segmento de ruta). Tests en
  `backend/tests/guests/test_portal_throttle.py`, siguiendo
  `backend/tests/integrations/test_webhook_throttle.py`. [R2.4] (D6)
- [x] 5.3 Segundo patrón en `backend/app/core/log_redaction.py` para
  `/api/v1/guest/{acción}/{token}` (conserva la acción, redacta el token),
  renombrando el filtro a `PathTokenRedactingFilter` y el instalador a
  `install_path_token_redaction`, con su única llamada en `backend/app/main.py:62`
  actualizada. Tests en `backend/tests/test_log_redaction.py`: las cuatro rutas
  del portal quedan redactadas, la ruta de webhook sigue redactada, y una quinta
  acción hipotética bajo `/api/v1/guest/` también. [R1.2, R6.4] (D8)

## 6. Superficie anónima: info y check-in <!-- panel: PASS 2026-08-10 -->

<!-- Panel de 5. Ronda 1: los cinco FAIL, 25 hallazgos, y ninguno de confidencialidad —
     seguridad confirmó que no hay fuga de PII, ni oráculo de existencia, ni rotura de
     tenant, y tenancy verificó instrumentando la app que las tres rutas crean UNA sola
     sesión por petición.

     El más grave lo encontró QA y era destructivo: `full_name="   "` pasaba `min_length=1`,
     el escritor no normalizaba y `missing_fields` sí, así que con huésped existente
     respondía 200, borraba el nombre legal y dejaba la estancia atascada en
     PENDING_GUEST_DATA para siempre sin error en ninguna parte; sin huésped, la misma
     entrada daba 404. Cerrado con `str_strip_whitespace=True` en el esquema.

     El más repetido: cuatro de los cinco llegaron por separado al doble `commit()`.
     `SetGuestDocumentUseCase.execute` comitea siempre, así que componerlo con una unidad
     de trabajo real partía la operación en dos transacciones y un fallo del TimelineEvent
     dejaba el check-in hecho y el hito perdido para siempre (el reintento ya no transiciona).
     Cerrado con `CallerOwnedUnitOfWork` en `app/core/unit_of_work.py`. Los tres docstrings
     que afirmaban «one transaction with one commit» pasaban sus tests porque ambos cableados
     dejan las mismas filas: es el patrón de este change en seis secciones seguidas — el
     docstring que afirma la garantía que el código no da.

     Otros cerrados: `record_failed_authorisation` en los 404 posteriores a la autorización
     (restricción 2, incumplida en tres ramas); `GuestNotFoundError`/`ReservationNotFoundError`
     escapaban al handler global con cuerpo propio, rompiendo el 404 constante de D5;
     `support_channel` fijo a None (cuarto setting, tarea 1.6); la carrera de OQ3 que dejaba
     un documento cifrado en una fila huérfana (`set_guest` pasa a reclamar con
     `WHERE guest_id IS NULL`); `missing_fields` reimplementado en la rama sin huésped; las
     dos `description` públicas (el 404 enumeraba causas, el 429 publicaba qué presupuesto
     consume cada cosa, y `/openapi.json` es anónimo); y «cuatro rutas» donde hay tres.

     Cobertura que faltaba y ahora existe: los cuatro tests que la tarea 6.5 exigía y nadie
     había escrito (un solo commit, R4.3 con los cuatro estados intactos, no propagación,
     auditoría antes del commit), el aislamiento cruzado de tenant sobre la superficie
     anónima (regla 1, obligatoria en módulo nuevo), la sesión marcada con el tenant del
     token, el throttle REAL a través del router, y la IP y el TimelineEvent en la auditoría.

     Dos decisiones de Jose que no eran fixes: la restricción 8 se reescribe (el titular se
     cumple, la cláusula que lo explicaba pedía más que D4), y el portón por IP se mantiene
     con su límite conocido documentado en D6 — el contador solo cuenta fallos, pero el
     portón frena también al token bueno del vecino de CGNAT. -->

<!-- Ronda 2: los cinco revisores, acotados a verificar los arreglos. -->


- [x] 6.1 `backend/app/guests/api/portal_router.py` y `portal_schemas.py`
  (nuevos): router **separado** del autenticado, sin `bearer_scheme`, sin
  `AuthenticatedDep` y sin `require(...)`; constante de módulo con el único
  cuerpo de fallo `404 NOT_FOUND` vía `app/core/errors.py::error_envelope`;
  `responses=` propio con `404`/`429`/`413` sobre `ErrorEnvelope` (**no**
  `AUTHENTICATED_RESPONSES`); todos los cuerpos con `extra="forbid"`. Montaje en
  `backend/app/main.py` y las **tres** entradas que esta sección monta en
  `ANONYMOUS_ENDPOINTS` de `backend/tests/test_route_authorization.py` — `GET
  /info/{token}`, `GET /checkin/{token}` y `POST /checkin/{token}`; la cuarta de
  PRD §23 (`POST /incident/{token}`) la añade §7, y decía «cuatro» aquí por
  describir el estado final (panel de documentación de §6). Test: una petición con JWT válido
  y token de ruta inválido recibe el mismo `404` que cualquier otra. [R2.2, R2.3]
  (D1, D5, D16)

  **Las nueve restricciones que el panel de seguridad de §5 dejó vinculantes aquí.**
  §5 entrega las piezas y no cablea ninguna; esto es lo que el router tiene que
  respetar para que R2.2 y D6 sobrevivan al contacto con FastAPI:

  1. **Orden**: `probe_allowed(ip)` → `429` si se niega → `authorize(token, now_utc())`
     → si autoriza, `request_allowed(session.token_hash)`. Nada puede tocar la base
     de datos antes de `probe_allowed` (D6: «se pregunta antes de cualquier trabajo»).
  2. `record_failed_authorisation` **en toda** `GuestPortalUnauthorised`, incluido el
     caso «no hay fila», y esperado antes de escribir la respuesta. Cobrar solo
     algunas causas convertiría al propio throttle en el distinguidor que D5 prohíbe.
  3. Una caída de Redis debe degradar **igual para todos**: se elija fail-open o
     fail-closed, no puede depender del token.
  4. El `429` de `request_allowed` solo lo alcanza un token que resuelve, y eso es
     aceptable **solo** porque llegar ahí exige ya tener el token. Así que el camino
     `404` no lleva `Retry-After`, ni código distinto, ni cabecera alguna de la que
     un anónimo pueda inferir lo mismo. El cuerpo es la constante única del módulo,
     idéntica en las cuatro rutas.
  5. **Nunca re-hashear el segmento de ruta**: `request_allowed` recibe
     `session.token_hash`; volver a llamar a `hash_guest_token` pone el valor en
     claro otra vez en circulación sin ganar nada (D6).
  6. `now` sale de `now_utc()`, nunca de una cabecera, query o cuerpo. El
     autorizador ya rechaza un `datetime` naive por adelantado, pero eso es una red,
     no la política.
  7. La forma de ruta se queda en `/api/v1/guest/{acción}/{token}` — **exactamente
     dos segmentos** tras `/guest/`. El patrón de `log_redaction.py` exige el
     segmento de acción; una ruta `/api/v1/guest/{token}` no casaría y el token
     acabaría en claro en el log de acceso (el riesgo que D8 nombra).
  8. **Ninguna dependencia de FastAPI devuelve `GuestSession`** (D4, alternativa
     rechazada). Redactado así tras el panel de §6 (decisión de Jose): la versión
     anterior añadía «la llamada al autorizador vive en el caso de uso, no en `api/`»,
     que es más de lo que D4 rechaza. El router **sí llama** al autorizador, en un
     único helper que ordena las cuatro operaciones de transporte; lo que no puede
     vivir en `api/` es la **decisión**, y no vive: está en
     `application/portal.py` y `domain/portal_authorisation.py`. R2.1 queda cumplido
     igual — tenant, reserva y propiedad salen del token dentro de
     `GuestPortalAuthenticator.authorize`, y el router recibe el token y nada más.
  9. La redacción cubre **solo uvicorn**. `install_path_token_redaction` se engancha
     al logger `uvicorn.access` y a nada más, así que cualquier proxy o balanceador
     por delante que registre la línea de petición guardará el token del huésped tal
     cual — y aquí el token *es* toda la credencial, sin secreto de cabecera detrás
     como en los webhooks. Es preexistente desde `reservations-webhooks`, pero §6 es
     lo que hace la superficie públicamente alcanzable: **confirmar el log de acceso
     del ingress antes de exponerla**. El panel no localizó esa configuración en
     `infra/` de este repo.
- [x] 6.2 `GET /api/v1/guest/info/{token}` + `GetStayInfoUseCase`, serializando
  `StayInfo`. Tests de API: la respuesta contiene los campos de D9 y **ninguno
  más**, un token de otra estancia devuelve datos de esa otra y no de esta, y las
  cinco condiciones de rechazo dan el `404` constante. [R3.1, R3.2, R3.3] (D9)
- [x] 6.3 `GET /api/v1/guest/checkin/{token}` + `GetCheckinStatusUseCase`:
  devuelve `missing_fields` sobre los ocho campos de PRD §17 más
  `document_status` y `legal_registration_status`, **sin devolver ningún dato ya
  aportado que sea sensible**. Test: con documento ya aportado, la respuesta dice
  que no falta y no incluye el número. [R4.1, R3.3]
- [x] 6.4 Ensanchar el escritor existente en
  `backend/app/guests/application/use_cases.py`: `GuestActor` pasa a
  `user_id: UUID | None` + `token_hash: str | None` con invariante
  «exactamente uno» en `__post_init__`; `DocumentInput` gana `full_name`; y
  `save_document` persiste esa columna (`domain/repositories.py`,
  `infrastructure/repositories.py`). Tests: construir un `GuestActor` vacío o con
  los dos falla; los llamantes existentes del manager siguen pasando; el
  `AuditLog` resultante lleva `full_name` redactado. **No** se crea un segundo
  escritor de `document_number_encrypted`. [R4.2, R6.1] (D10, Riesgos)
- [x] 6.5 `SubmitGuestCheckinUseCase` en
  `backend/app/guests/application/portal.py`: valida, resuelve el `Guest` de la
  estancia — creándolo desde `full_name` y enlazándolo con `set_guest` si
  `reservations.guest_id` es `NULL` (OQ3) —, delega en
  `SetGuestDocumentUseCase`, deja que este reevalúe el estado legal vía
  `status_for` (**no se reimplementa**), y escribe `TimelineEvent
  GUEST_CHECKIN_COMPLETED` **solo cuando el estado legal transiciona de verdad**.
  Un solo `UnitOfWork`, un solo `commit()` al final, con el `AuditLog` escrito
  **antes** del commit. Tests: reenvío del mismo formulario deja el mismo estado
  final y **no** un segundo `TimelineEvent`, pero **sí** un segundo `AuditLog`;
  el estado legal solo se mueve entre `PENDING_GUEST_DATA` y `READY_TO_SUBMIT` y
  cualquier otro se devuelve intacto; no se propaga a otras estancias del mismo
  huésped. [R4.2, R4.3, R4.5, R6.1, R6.2, R6.3] (D10, D13)
- [x] 6.6 `POST /api/v1/guest/checkin/{token}` con validación Pydantic v2 de los
  seis campos del cuerpo y respuesta `{document_status,
  legal_registration_status}` — **sin eco del número de documento**. Tests de
  API: un cuerpo inválido o incompleto devuelve `422` y **no persiste nada**
  (comprobado leyendo la fila después), y un cuerpo con `tenant_id` o
  `reservation_id` se rechaza por `extra="forbid"`. [R4.1, R4.4, R2.1, R6.4]
  (D10, D16)

  **Carry-forward del panel de seguridad de §2**: el esquema es lo único que
  acota los cuatro campos de `GUEST` que siguen siendo *diffables* en auditoría
  (`document_type`, `document_expiry_date`, `document_status`,
  `legal_registration_status`). Tipar `document_expiry_date` como `date` —**no**
  como `str` para dar un error más amable— y conservar el
  `min_length=2, max_length=2` de `nationality` que ya tiene
  `backend/app/guests/api/schemas.py:39`. Si alguno se declara `str`, ese campo
  pasa a ser texto libre de un anónimo sobre una entrada del allowlist que
  admite `diff()`, y nada del módulo de auditoría lo detendría.
- [x] 6.7 Fijar con test el tope de cuerpo que `MaxBodySizeMiddleware` ya aplica
  (`settings.request_max_bytes`, 1 MiB) sobre las rutas del portal, siguiendo
  `backend/tests/integrations/test_webhook_body_ceiling.py`; y comprobar que un
  cuerpo truncado (`ClientDisconnect`) devuelve `413` **antes** de escribir nada.
  Sin código nuevo de middleware ni setting nuevo. [R2.4] (D7)

## 7. Superficie anónima: incidencia del huésped <!-- panel: PASS 2026-08-11 -->

<!-- Panel de 5 (architect, security, qa, tenancy, documentation). Ronda 1: architect y tenancy
     PASS; qa PASS con un defecto real; security FAIL con 2; documentation FAIL con 5. Arreglados:
     tope de `description` (el techo de cuerpo acota la petición, no lo que una estancia acumula a
     60 req/min); NUL byte -> 500 sin manejar, que reproducía también en el `full_name` de §6;
     y siete sitios con la redacción «tres rutas hoy, la cuarta cuando llegue §7».

     El hallazgo grande de security fue de steering, no de código: `incidents.title`/`description`
     son la octava y novena columnas de la regla 11 y este change es su primer escritor. Enmendada
     la regla con la SEGUNDA excepción nombrada, aprobada por Jose el 2026-08-11 (design D15), con
     su test de contrato en `tests/maintenance/test_free_text_sink_contract.py`.

     Ronda 2: security encontró 4 más, todas sobre mis propios arreglos —surrogate suelto (`Cs`, no
     `Cc`) que el guard dejaba pasar, la razón falsa por la que había eximido `document_number`
     (Fernet no inmuniza: `.encode()` peta antes), un párrafo duplicado en el steering y un censo
     AST que solo veía una forma sintáctica—. Arregladas, y el gate del censo hubo que rehacerlo
     dos veces: gatear por `IncidentModel` saltaba justo el módulo que compone el texto.

     QA en ronda 2 cerró el defecto y dejó una precisión que también era mía: el escape `\uD800`
     lo rechaza el parser de pydantic-core antes de llegar al validador, así que la rama de
     surrogate es defensa en profundidad y no el vector que su docstring afirmaba. Corregido, y la
     rama anclada con un test que la ejercita directamente. PASS. -->

<!-- Fuera de requisito, registrado por el panel de QA y no arreglado a propósito: los caracteres
     de categoría `Cf` (p. ej. `U+202E`, anulación bidireccional) pasan el guard, así que un
     huésped puede escribir un título que se *muestre* al revés en la lista del operador. Ningún
     requisito en alcance pide defensa contra spoofing visual, y la defensa correcta es de
     renderizado (frontend), no de esquema. Candidato de roadmap anotado en el proposal. -->


- [x] 7.1 `maintenance` estrena `application/`: puerto
  `IncidentRepository` con **un solo método** `add(tenant_id, incident)` en
  `backend/app/maintenance/domain/repositories.py` (nuevo) y
  `SqlAlchemyIncidentRepository` en
  `backend/app/maintenance/infrastructure/repositories.py` (nuevo). **Sin
  `api/`**. Test de repositorio en `backend/tests/maintenance/`. [R5.5] (D15,
  `sdd/specs/domain-foundation-ops.md:12`)
- [x] 7.2 `ReportGuestIncidentUseCase` en
  `backend/app/maintenance/application/use_cases.py` (nuevo): crea el `Incident`
  con `source = GUEST`, `status = OPEN`, `property_id`/`reservation_id`
  derivadas del token y `reported_by_guest_token` con el **hash de 64 hex**;
  deja `category`, `severity`, `ai_summary` y `ai_classification` en sus
  `server_default`; escribe `AuditLog INCIDENT_CREATED` antes del commit y
  `TimelineEvent INCIDENT_CREATED` con `actor_type = GUEST` y
  `actor_user_id = None`. Tests: la fila creada es indistinguible de cualquier
  otra en `OPEN` para el flujo de clasificación, y ni el token en claro ni el
  documento aparecen en auditoría ni en timeline. [R5.1, R5.4, R6.1, R6.2, R6.3,
  R6.4] (D15, D12, D13)
- [x] 7.3 `POST /api/v1/guest/incident/{token}` con `title` (requerido, ≤300 tras
  `strip()`) y `description`, respuesta `{id, status, created_at}` y nada más.
  Tests de API: un cuerpo sin descripción válida se rechaza **antes** de crear la
  incidencia, no existe ninguna ruta de portal que liste/lea/modifique
  incidencias, y `reported_by_guest_token` guarda el hash y nunca el valor.
  [R5.1, R5.2, R5.3] (D15)

## 8. Contrato y documentación

- [x] 8.1 Regenerar y commitear las **dos mitades del puente**: `make openapi`
  (`backend/openapi.json`) y `cd frontend && npm run api:generate`
  (`frontend/lib/api/generated/openapi.d.ts`). Comprobar que
  `backend/tests/test_openapi_contract.py` pasa y que ningún código de error
  nuevo entra en `app/core/error_codes.py`. (D16, steering/documentation)

  **No es solo una tarea de cierre: hay que regenerar al final de cada sección que
  añada o cambie una ruta.** `test_openapi_contract.py` es parte de la suite, así
  que en cuanto §4 metió sus dos endpoints la suite quedó roja — y el preámbulo de
  este fichero exige que el sistema funcione al final de cada sección. Regenerado
  ya al cerrar §4; §6 y §7 vuelven a moverlo, y esta tarea es la pasada final que
  comprueba que las dos mitades siguen cuadrando.

  **Cómo se regenera el lado del frontend desde un worktree**: `npm ci` en `frontend/`
  y luego `npm run api:generate`, igual que hace `.github/workflows/frontend-api-contract.yml`.
  No vale lanzarlo dentro del contenedor `frontend`: solo monta `./frontend`, así que
  el script no encuentra `backend/openapi.json`, que resuelve desde la raíz del repo.
  `node_modules/` está en `.gitignore`, así que instalarlo en el host no ensucia el árbol.

  **HECHO 2026-08-11, y la pasada final se hizo después de mergear `main`**, que es lo que
  ahorró hacerla dos veces: `main` traía 48 commits con `dashboard-api`, `auth-account-recovery`
  y `provenance`, y los dos artefactos generados eran dos de los diez conflictos. Se resolvieron
  regenerando, no editando. Verificado además que `app/core/error_codes.py` no cambia respecto a
  `main` (`git diff origin/main...HEAD` vacío) y que `test_openapi_contract.py` pasa.
- [x] 8.2 `docs/guest-portal.md` (nuevo): cómo se opera la capability — emisión y
  revocación del token desde la ruta de operador, qué ve el huésped, y la
  **advertencia explícita de OQ2** de que `properties.access_notes` se le muestra
  tal cual, así que no debe contener códigos de puerta en claro. Enlazar a la
  spec en vez de duplicarla. (steering/documentation, OQ2)

  **Y su cara simétrica, que la segunda excepción de la regla 11 exige aquí** (panel
  de seguridad de §7, aprobada por Jose el 2026-08-11): lo que el huésped teclea en
  `title`/`description` se le muestra al operador **tal cual**, sin estructurar ni
  enmascarar, así que una incidencia puede contener lo que el huésped decidiera
  escribir —incluido su propio documento—. El steering nombra este fichero como el
  sitio donde consta; citarlo, no reenunciar el contrato.
- [x] 8.3 Regenerar el ER (~~29 → 30~~ **30 → 31** entidades, entra `guest_access_tokens`) en
  `docs/diagrams/<YYYY-MM-DD>_autohost-er-entidades.png` con `/sdd:diagram`,
  actualizar las referencias y **borrar el anterior**. (steering/documentation,
  steering/architecture)

  **La aritmética de la tarea la movió el merge, y se recontó en vez de arrastrarla.** Cuando se
  escribió esta tarea el esquema tenía 29 tablas; `auth-account-recovery` entró en `main` con
  `password_reset_tokens`, así que la base era 30 y con `guest_access_tokens` son **31**, contadas
  desde `Base.metadata` y no a mano. El anterior era `2026-08-10_...` (ya regenerado por ese
  change, también tras mergear `main`), y es el que se borra; la referencia viva estaba solo en
  `sdd/steering/architecture.md`.

  Generado desde la metadata de SQLAlchemy —31 entidades, 414 columnas, 75 relaciones— y
  renderizado con `mmdc`.

  **La cifra de relaciones se corrigió en `review` (era 74).** Las entidades y las columnas
  cuadraban; las relaciones no cuadraban con ninguna definición contable. Recontado desde
  `Base.metadata`: **75** columnas con clave ajena —que es la regla que fija
  `steering/architecture.md:11`—, 75 objetos `ForeignKeyConstraint` y 73 pares de tablas
  distintos. Ninguna daba 74. Con 75 la serie de ese steering vuelve a cerrar: 73 de
  `auth-account-recovery` más las dos claves ajenas de `guest_access_tokens`. Y las
  referencias de ese fichero —el párrafo que atribuye el diagrama vivo y el que hace la
  aritmética— se actualizaron entonces: esta tarea había cambiado **solo** el nombre del
  fichero en la lista de arriba, dejando los dos de debajo describiendo el diagrama anterior. Se mantiene `.png` a propósito aunque el skill recomiende SVG para
  ficheros de repositorio: el nombrado `{YYYY-MM-DD}_{slug}.png` está fijado en
  `steering/documentation.md` y los otros cinco diagramas son PNG, así que cambiar de formato
  aquí sería una decisión de convención y no una tarea de este change.
- [x] 8.4 Revisar el `README.md` de raíz: si la sección de estructura enumera las
  capas por módulo, reflejar que `maintenance` ya tiene `application/`; si no lo
  hace, dejarlo intacto y anotarlo así en la tarea. (steering/documentation)

  **Sí las enumera, así que se editó** — y el caso no encaja en la frase que había.
  `maintenance` no pasa a «tener las cuatro»: gana `application/` e
  `infrastructure/` pero D15 le niega `api/` a propósito, porque la ruta es del
  portal. Queda descrito como el **caso simétrico de `dashboard`**, que es el único
  con `api/` y sin `infrastructure/`. La frase también dice quién traerá su `api/`,
  para que la ausencia se lea como una decisión y no como un olvido.

## 9. Verificación

- [x] 9.1 Suite completa verde desde este worktree:
  `docker compose exec backend uv run pytest` (o
  `docker compose run --rm backend uv run pytest` con el stack parado).

  **6089 pasan, 0 fallan, 35 skipped** — con un reencuadre que el merge de `main` obligó a
  hacer y que conviene que quede escrito, porque afecta a cómo se corre la suite aquí:
  **un test no puede pasar dentro del contenedor**.
  `tests/provenance/test_workflow_to_endpoint_wiring.py` lee el workflow **real**
  `.github/workflows/deploy-dev.yml` a propósito —en vez de modelarlo en Python—, y el
  compose monta solo `./backend:/app`, así que el fichero no existe en el contenedor y el
  test hace `pytest.fail`. CI no tiene el problema: le pasa la ruta en
  `PROVENANCE_WORKFLOW_PATH`. Llegó con `provenance` en `main`; no lo introduce ni lo rompe
  este change, y se comprobó que pasa en cuanto se le da el fichero.

  La invocación honesta desde un worktree es por tanto la de CI:

  ```
  docker compose cp .github/workflows/deploy-dev.yml backend:/tmp/deploy-dev.yml
  docker compose exec -T -e PROVENANCE_WORKFLOW_PATH=/tmp/deploy-dev.yml backend uv run pytest
  ```

  Sin eso son 6088 verdes y ese 1 rojo, que es el mismo resultado que daría `main` a solas.
- [x] 9.2 Migración limpia en los dos sentidos, como hace CI:
  `docker compose exec backend uv run alembic upgrade head`,
  `uv run alembic check` (sin deriva de modelos) y
  `uv run alembic downgrade base`.

  Verificado el ciclo entero —`upgrade head`, `check` («No new upgrade operations detected»),
  `downgrade base` hasta la revisión baseline, y `upgrade head` otra vez— **sobre la cadena
  reencadenada** tras el merge, que es lo que había que probar: la revisión de este change pasó
  a colgar de `a7c4e91b2d05` (`auth-account-recovery`) para no dejar dos cabezas.

  **Y una lección que no estaba en la tarea: reencadenar invalida cualquier base de datos que
  ya hubiera aplicado la revisión.** La de dev decía estar en `e7a3c419d82b` sin haber aplicado
  nunca la de `main`, así que `upgrade head` no hacía nada y `downgrade base` fallaba
  intentando desaplicar una columna que no existía. Se reconstruyó el esquema desde cero. Es
  estado local y no afecta a ningún entorno desplegado —ninguno tiene aún esta revisión—, pero
  quien reencadene una migración con la BD ya migrada se va a encontrar exactamente esto.
- [x] 9.3 Los guardias transversales pasan sin excepción añadida a mano:
  `test_route_authorization.py` (las cuatro rutas anónimas declaradas),
  `test_layering.py`, `test_models_registry.py`, `test_tenant_filter.py`,
  `test_session_marking.py` y `test_openapi_contract.py`.

  1451 pasan. Ninguno lleva excepción a mano: la única entrada añadida es la cuarta ruta
  anónima en `ANONYMOUS_ENDPOINTS`, que es el diff visible que esa lista existe para forzar.
  `incidents` no necesitó entrada nueva en el censo de tenant —`IncidentModel` ya llevaba
  `TenantScopedMixin` desde `domain-foundation-ops` y su módulo ya estaba en
  `models_registry`—, lo cual verificó el reviewer de tenancy explícitamente en vez de darlo
  por hecho.
- [x] 9.4 Recorrido manual end-to-end **desde dentro de la red de compose** (un
  worktree no publica puertos, `sdd/project.md` § Worktree bootstrap): emitir un
  token con la ruta de operador, y con él recorrer `GET /guest/info`,
  `GET /guest/checkin`, `POST /guest/checkin` y `POST /guest/incident`; después
  revocar y comprobar que las cuatro devuelven el mismo `404`. Verificar en
  `docker compose logs backend` que **ninguna** línea del log de acceso contiene
  el token en claro. [R1.2, R1.4, R2.2]

  **Hecho el 2026-08-11, todo por HTTP contra `backend:8000` por nombre de servicio.** Dos
  detalles prácticos para quien lo repita: **el contenedor no tiene `curl`** (sí `httpx`, que
  usa la suite), y crear la propiedad es de `PROPERTY_MANAGER` — el `TENANT_OWNER` recibe un
  `403`, así que el recorrido entero se hace con el manager, que también tiene
  `MANAGE_GUEST_ACCESS_TOKENS`.

  Resultado, comprobación por comprobación: token de 43 caracteres devuelto una vez (`201`);
  `info` `200` con `property_name`, `city` y `arrival_notes`, y **ninguno** de los campos
  prohibidos de R3.2 presente en la respuesta; `checkin` `200` listando los **seis** campos
  que faltan —los dos del calendario no, porque son de la reserva—; `POST checkin` `200` con
  `document_status: PROVIDED` y **sin eco** del número; `POST incident` `201` con exactamente
  `{id, status: OPEN, created_at}`; revocación `204`; y las cuatro rutas después de revocar
  devolviendo `404` con **un único cuerpo idéntico** (comprobado comparando los cuatro, no
  solo los códigos).

  Dos cosas que el recorrido ejercitó sin que la tarea las pidiera, y que salieron bien:
  la reserva se creó **sin huésped**, así que el `POST checkin` pasó por la rama de **OQ3** y
  creó el `Guest` con el nombre tecleado; y su `legal_registration_status` era `NOT_REQUIRED`,
  de modo que se vio en vivo la mitad de **R4.3** que dice devolver *sin tocar* cualquier
  estado que no sea `PENDING_GUEST_DATA` o `READY_TO_SUBMIT`.

  **El log**: ocho líneas del portal, las ocho con el último segmento redactado
  (`GET /api/v1/guest/info/*** 200 OK`), conservando la acción. Cero líneas con el token en
  claro y cero con el número de documento — buscados literalmente sobre el log capturado.
