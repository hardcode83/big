# Design: guest-portal-api

## Context

El suelo existe entero y la costura no. `GuestModel` ya tiene
`document_number_encrypted` y `document_status`
(`backend/app/guests/infrastructure/models.py`), `ReservationModel` tiene
`legal_registration_status` y `guest_id` **nullable**
(`backend/app/reservations/infrastructure/models.py:31`), e `IncidentModel` tiene
`source = GUEST` y `reported_by_guest_token VARCHAR(200)`
(`backend/app/maintenance/infrastructure/models.py:35`). Lo que no existe es
ningún token de huésped, ninguna ruta pública y ningún `application/` en
`maintenance` —ese módulo hoy es solo `domain/` + `infrastructure/models.py`.

Y existe un precedente casi exacto de todo lo que este change necesita:
`reservations-webhooks` construyó una superficie **anónima, autenticada por un
token opaco que viaja en la ruta**, con hash SHA-256 sin sal e índice único
global (`backend/app/integrations/domain/webhook_auth.py`,
`WebhookEndpointModel`), router propio fuera del router autenticado
(`backend/app/integrations/api/webhooks_router.py`), doble límite de tasa
(`backend/app/integrations/infrastructure/throttle.py`), respuesta de fallo única
e indistinguible, y redacción del token en el log de acceso
(`backend/app/core/log_redaction.py`). Este diseño **copia esa forma** en lugar de
inventar otra; donde se separa, se dice por qué.

**Corrección a la proposal.** Su nota dice que los tres endpoints «se diseñan
aquí desde cero, no se rellena un hueco existente». Eso es cierto de
`sdd/specs/api-contract.md`, que efectivamente no cataloga rutas — pero **el PRD
sí las declara**, las cuatro, en §23 (`docs/AutoHostAI_PRD_v5_Claude.md:2022-2026`):

```
# Guest token endpoints (sin auth JWT, con token de un solo uso)
GET    /api/v1/guest/checkin/{token}
POST   /api/v1/guest/checkin/{token}
POST   /api/v1/guest/incident/{token}
GET    /api/v1/guest/info/{token}
```

Son cuatro, no tres: `GET /guest/checkin/{token}` es el estado de R4.1 y
`POST` el envío de R4.2. Se adoptan tal cual (D1). Su comentario «un solo uso»
**no se adopta**, y el porqué está en D3.

## Decisions

### D1 — Las cuatro rutas del PRD §23, en un router anónimo propio de `guests`

**Chosen:** las rutas literales del PRD, servidas por
`backend/app/guests/api/portal_router.py`, un segundo router del módulo `guests`
montado por separado en `app/main.py`, y sus cuatro entradas añadidas a
`ANONYMOUS_ENDPOINTS` de `backend/tests/test_route_authorization.py`.

El módulo es `guests` porque el token identifica a un huésped en una estancia, que
es su agregado. El router es **otro** porque `app/guests/api/router.py` declara
`responses=AUTHENTICATED_RESPONSES` y cuelga sus tres rutas de `require(...)`:
meter ahí una ruta anónima es exactamente lo que `app/main.py:79-86` describe como
«esconder un endpoint sin autenticar dentro de una forma que dice lo contrario».
Las cuatro entradas en la allowlist son el diff visible que esa decisión tiene que
atravesar.

Rejected: un dominio nuevo `app/guest_portal/` — `steering/architecture.md` §3.2
enumera los dominios y no lo incluye; el token no es un dominio, es una credencial
de uno existente.
Rejected: colgarlas del router autenticado con una dependencia distinta — el test
de autorización pasaría por la allowlist igual, pero la forma del fichero mentiría.

### D2 — El token: tabla propia `guest_access_tokens`, hash SHA-256 sin sal

**Chosen:** una tabla nueva con `reservation_id`, `token_hash` (64 hex, índice
`UNIQUE` **global**) y `revoked_at`, más `tenant_id`/`created_at`/`updated_at` de
los mixins. Las primitivas —generación con `secrets.token_urlsafe(32)` y hash—
viven en `backend/app/guests/domain/portal_token.py`, Python puro, calcado de
`webhook_auth.py`.

`UNIQUE` global sobre `token_hash` porque la ruta de verificación consulta **sin
tenant en la mano**: es el hash quien resuelve el tenant, así que «exactamente una
fila» tiene que ser garantía del esquema y no suposición del llamante. Sin sal por
la misma razón que allí: 256 bits de CSPRNG no tienen diccionario que atacar, y un
bcrypt salado sería **imposible de indexar**, que es justo la propiedad de la que
depende toda la ruta.

Índice único **parcial** `(reservation_id) WHERE revoked_at IS NULL`: es R1.5
—«nunca dos tokens vigentes que autoricen la misma estancia»— convertida en
invariante de esquema en lugar de en disciplina del caso de uso.

Rejected: dos columnas en `reservations` (`guest_token_hash`,
`guest_token_revoked_at`) — `reservations` se serializa en respuestas de API y se
edita por `PATCH`, así que una credencial ahí queda a un `model_validate` de una
respuesta; y la emisión/rotación no tendría `created_at` propio sin tocar el
`updated_at` de la reserva. Es la misma asimetría por la que `webhook_endpoints`
no son columnas de `pms_credentials`.
Rejected: guardar el token en claro — R1.2 lo prohíbe y un volcado de la tabla
entregaría todas las estancias vivas.

**Divergencia declarada del PRD §7**: no declara esta tabla. Pero §23 declara los
cuatro endpoints con `{token}` y §7.13 declara `incidents.reported_by_guest_token`,
así que el PRD **presupone** el token y nunca le da casa. Misma clase que
`webhook_endpoints`. El ER hay que regenerarlo (`steering/documentation.md`). La
aritmética **la movió el merge de `main`** y la cifra viva no vive aquí: cuando se
escribió esta decisión el esquema tenía 29 tablas, pero `auth-account-recovery` entró
antes con `password_reset_tokens`, así que la base era 30 y con `guest_access_tokens`
son **31**. El recuento verificado —31 entidades, 414 columnas, 75 relaciones, contadas
desde `Base.metadata`— está en la tarea 8.3 y en `steering/architecture.md`; aquí se
cita para no dejar una tercera copia que corregir.

### D3 — La vigencia **se deriva en la verificación**, no se almacena

**Chosen:** no hay columna `expires_at`. En cada petición se comprueba, contra la
reserva:

1. `revoked_at IS NULL`;
2. `reservation.status is not CANCELLED`;
3. `now <= medianoche UTC de (check_out_date + settings.guest_portal_token_grace_days)`.

Esto resuelve R1.3 y R1.4 **sin ningún job**: una reserva cancelada deja de
autorizar en el instante en que se cancela, no en el siguiente barrido, y un cambio
de fechas de la estancia mueve la ventana en vez de dejar un `expires_at` obsoleto.
Es fail-closed por construcción, que es la dirección correcta para una superficie
anónima.

**Dónde vive esta regla — corregido en run.** Las tres comprobaciones y la
aritmética de la ventana son un **servicio de dominio**,
`app/guests/domain/portal_authorisation.py`, no métodos del autorizador. Esta
decisión no decía nada sobre la capa y D4 solo argumenta contra poner la decisión
en una dependencia de FastAPI; el panel de arquitectura de §5 levantó el silencio
como `DESIGN-CONFLICT` contra `steering/backend-architecture.md` («si hay una regla
—no solo un paso de orquestación— pertenece a `domain/`»), y Jose aprobó moverlo.

Servicio y no método de una entidad porque la regla **cruza dos**: el token aporta
`revoked_at` y la estancia aporta su `status` y sus fechas — que es literalmente el
caso que el steering describe para un servicio de dominio. Lo que gana: la
aritmética es pura y se testea con fechas y nada más, que es donde
`steering/testing.md` pide TDD. Y hacía falta: la primera implementación concedía un
día de más.

**La frontera, explícita porque ya falló una vez**: medianoche de una fecha es su
*primer* instante, así que con check-out el día 3 y 2 días de gracia el token muere
a las 00:00 del 5 — el huésped lo conserva todo el 3 y todo el 4. Leer «2 días de
gracia» como «hasta el final del 5» concede un tercer día.

`ASSUMPTION` (zona horaria): la ventana cierra a medianoche **UTC**, no en la
`properties.timezone`. Con una gracia por defecto de 2 días el desfase máximo son
2 horas sobre 48, y meter la zona de la propiedad en el cálculo obligaría a leerla
en el camino de autenticación, antes de tener tenant.

**El «token de un solo uso» del PRD §23 no se implementa, y es una divergencia
declarada**: un token de un solo uso no puede servir a la vez `GET info`,
`GET checkin`, `POST checkin` y `POST incident` a lo largo de una estancia —las
cuatro rutas que el propio comentario encabeza—. Lo que el paréntesis quiere decir
es «no es una credencial permanente», y eso lo da la ventana. R2.2 nombra
«consumido» entre las condiciones de rechazo: se cubre con `revoked_at`, que es la
forma real que tiene aquí «consumido».

Rejected: `expires_at` calculado en la emisión — queda obsoleto si la estancia se
mueve, y obliga a un barrido para las cancelaciones.

### D4 — Verificación: hash → fila → reserva → `bind_session_to_tenant`

**Chosen:** un servicio de aplicación `GuestPortalAuthenticator` en
`backend/app/guests/application/portal.py`, con
`authorize(token: str, now: datetime) -> GuestSession`. El orden es fijo:

1. hash del token, consulta por `token_hash` sobre la sesión **sin marcar** (no hay
   tenant todavía — es la misma situación que `find_by_email_globally` en el login,
   documentada en `app/core/db.py:79-86`);
2. proyección de la reserva (`reservation_id`, `tenant_id`, `property_id`,
   `guest_id`, `check_in_date`, `check_out_date`, `status`), aún sin marcar;
3. las tres comprobaciones de D3;
4. `bind_session_to_tenant(session, tenant_id)` — a partir de aquí el filtro global
   cubre el resto de la petición;
5. devuelve `GuestSession`, congelado, con tenant/reserva/propiedad/huésped y el
   `token_hash`.

El límite 4 de `app/core/db.py` (el mapa de identidad no queda cubierto) no muerde
aquí: las dos filas leídas antes de marcar pertenecen al tenant que se acaba de
resolver, no a otro. Y `bind_session_to_tenant` es de un solo sentido, lo cual es
correcto porque la sesión de una ruta anónima nace sin marcar.

R2.1 se cumple literalmente: **tenant, reserva y propiedad salen de la fila del
token**, y ninguna de las cuatro rutas acepta un identificador de negocio en ruta,
cuerpo, query o cabecera. El router recibe el token y nada más.

R2.5 (aislamiento sin excepción para `SUPER_ADMIN`) es trivialmente cierto: no hay
rol en esta ruta, no hay JWT y no hay ninguna consulta que consulte un rol.

Rejected: una dependencia de FastAPI que devuelva el `GuestSession` — pondría la
decisión de autorización en `api/`, contra `steering/backend.md` («la lógica nunca
vive en el router») y contra el precedente explícito de
`webhooks_router.py`/`application/webhooks.py`.

**Precisión que el panel de arquitectura de §6 obligó a escribir** (decisión de Jose):
lo rechazado es esa dependencia y nada más. El router **sí llama** al autorizador, en
un único helper `_authorised` que ordena las cuatro operaciones de transporte; la
*decisión* —qué token resuelve qué tenant, si la ventana cerró— sigue en
`application/portal.py` y `domain/portal_authorisation.py`. La cláusula de la
restricción 8 de la tarea 6.1 decía «la llamada al autorizador vive en el caso de uso»,
que es más de lo que esta decisión rechaza y de lo que R2.1 pide: R2.1 exige que
tenant, reserva y propiedad salgan del token **dentro del caso de uso**, y salen —
`GuestPortalAuthenticator.authorize` es ese caso de uso, y el router recibe el token y
nada más. La restricción quedó reescrita para decir lo que esta decisión rechaza.

**Lo que este párrafo no decía, y el panel de §5 obligó a decir.** Argumentar contra
`api/` no es argumentar a favor de `application/`: el paso 3 es una **regla**, y las
reglas van a `domain/`. Corregido en run — vive en
`app/guests/domain/portal_authorisation.py` (ver D3), y `GuestPortalAuthenticator`
la invoca como un paso más de la orquestación. Lo que queda en `application/` es
exactamente lo que le toca: secuenciar dos puertos y un binder.

**Dos precisiones más que salieron al implementarlo**, ambas del panel de §5:

- El paso 2 se ejecuta **siempre**, incluso cuando el paso 1 no encontró fila —
  contra ids que no resuelven. Un primer borrador cortaba ahí, lo que dejaba
  «desconocido» costando una consulta y «conocido pero muerto» costando dos: justo
  la asimetría que el panel de §3 había dejado como restricción vinculante, y que el
  docstring ya afirmaba haber cerrado.
- Los dos pasos seleccionan **columnas**, no modelos, así que no se crea ninguna
  instancia ORM antes de marcar la sesión. La afirmación de esta decisión de que «el
  límite 4 de `app/core/db.py` no muerde aquí» era cierta solo por el refcounting de
  CPython sobre un `WeakInstanceDict`; ahora lo es estructuralmente.

### D5 — Una sola respuesta de fallo: `404 NOT_FOUND`, cuerpo constante

**Chosen:** token inexistente, mal formado, revocado, fuera de ventana o de una
reserva cancelada devuelven **el mismo** `404` con el mismo envoltorio
(`app/core/errors.py::error_envelope`), construido una vez como constante del
módulo para que cuatro sitios no puedan divergir. Es literalmente el patrón de
`webhooks_router.py:48`.

`404` y no `401`: un `401` invita a una cabecera `Authorization` que aquí no
significa nada, y `NOT_FOUND` es el código que el proyecto ya usa para «existe pero
no es tuyo» (`app/core/error_codes.py:49-51`).

**R2.3 (rechazar cualquier JWT) se cumple por ausencia, no por comprobación**:
ninguna de las cuatro rutas declara `bearer_scheme`, `AuthenticatedDep` ni
`require(...)`, así que no hay código que lea `Authorization`. Una petición con un
JWT válido y sin token de ruta válido recibe el mismo `404` que cualquier otra. Un
rechazo explícito sería peor: obligaría a leer la cabecera para poder rechazarla.

### D6 — Límite de tasa: `RedisGuestPortalThrottle`, dos límites asimétricos

**Chosen:** una clase nueva en
`backend/app/guests/infrastructure/portal_throttle.py`, con la **forma** de
`RedisWebhookThrottle` pero no su clase, con dos límites:

- **por IP, estricto, contado solo sobre autorizaciones fallidas**
  (`guest_portal_probe_limit_per_minute`, defecto 20). Es R2.4: adivinar cuesta.
  Se pregunta **antes de cualquier consulta**, como en `webhooks_router.py:118` —
  no antes de *todo*: en el `POST`, FastAPI valida el cuerpo al resolver
  dependencias, así que un cuerpo malformado es un `422` que no llega al portón ni
  gasta presupuesto. Lo acota el tope de cuerpo (D7) y no informa de nada (el `422`
  es idéntico con token bueno o malo), pero la redacción original decía «antes de
  cualquier trabajo» y el panel de seguridad de §6 la midió falsa.
- **por token, generoso** (`guest_portal_rate_limit_per_minute`, defecto 60),
  cobrado **después** de autorizar y con el hash **ya almacenado**, nunca
  re-hasheando el segmento de ruta.

El segundo importa más aquí que en los webhooks: un token válido puede hacer
`POST /guest/incident` indefinidamente, así que este límite es lo único que acota
cuántas filas de `incidents` produce una estancia.

No se reutiliza `RedisWebhookThrottle`: su vocabulario habla de entregas de
proveedor, y compartir clase obligaría a un segundo significado para sus métodos.
No se reutiliza `RedisLoginThrottle`: no hay cuenta que bloquear.

Rejected: un único límite por IP sobre todo el tráfico — un hotel con WiFi
compartido pone a todos sus huéspedes detrás de una IP.

**Límite conocido, medido por el panel de seguridad de §6 y aceptado a propósito
(decisión de Jose).** El rechazo de arriba se cumple en el *contador* —solo lo
alimentan las autorizaciones fallidas, como exige R2.4— pero **no en el portón**:
`probe_allowed(ip)` se consulta en toda petición, incluida la de un token bueno. Así
que agotado el presupuesto de una dirección por 20 fallos, un huésped legítimo que
salga por ese mismo CGNAT o WiFi de hotel recibe `429` hasta que acabe la ventana.

Se mantiene por dos razones, no por una: es el orden que la restricción 1 del panel
de §5 dejó vinculante —el portón tiene que morder **antes** de las consultas que un
adivinador intenta provocar— y es el que ya lleva en producción `webhooks_router.py`,
que R2.4 nombra como precedente a seguir. La alternativa (autorizar primero y
consultar el presupuesto solo al fallar) nunca frenaría a un token bueno, pero
devuelve a cada intento de adivinar dos consultas por columnas, que es exactamente la
asimetría que los paneles de §3 y §5 cerraron.

Queda anotado como **candidato de roadmap** con su forma ya identificada: un portón
por token en lugar de por dirección, o un presupuesto por IP con lista de excepción
para las direcciones de salida conocidas de un operador. Escrito además donde lo verá
quien lo sufra: `app/core/config.py` y `.env.example`, junto al valor que lo gobierna.

### D7 — El tope de cuerpo ya está puesto; no se añade nada

**Chosen:** `MaxBodySizeMiddleware` cubre todo `/api/v1/` antes del routing y
estas rutas caen en la rama por defecto, `settings.request_max_bytes` (1 MiB)
—`app/main.py:182-195`—. Ni rama nueva ni setting nuevo. R2.4 se satisface sin
código; lo que sí hace falta es **fijarlo con un test**, como
`tests/integrations/test_webhook_body_ceiling.py`.

Consecuencia que hay que respetar en el router: un cuerpo truncado llega como
`ClientDisconnect`, y hay que devolver `413` **antes** de escribir nada, igual que
en `webhooks_router.py:152-167`. Un rechazo que además escribe es peor que
cualquiera de los dos resultados por separado.

### D8 — Redacción del token en el log de acceso, generalizando `log_redaction.py`

**Chosen:** el token de huésped viaja en el **path**, así que uvicorn lo escribe en
cada línea del log de acceso — exactamente la fuga que `reservations-webhooks`
encontró y cerró. `backend/app/core/log_redaction.py` gana un segundo patrón
(`/api/v1/guest/{acción}/{token}`, conservando la acción, que no es secreta), el
filtro pasa a llamarse `PathTokenRedactingFilter` y el instalador
`install_path_token_redaction`, con su única llamada en `app/main.py:62`
actualizada.

Es obligatorio, no cosmético: R1.2 prohíbe el token en claro en logs, y sin esto
cualquiera con lectura del log recupera todas las estancias vivas.

Rejected: mover el token a una cabecera — perdería la propiedad de ruta no
adivinable y obligaría al frontend `/guest/[token]` a un flujo distinto.
Rejected: un filtro nuevo aparte — dos filtros haciendo lo mismo sobre el mismo
logger es cómo uno de los dos deja de instalarse.

### D9 — `GET /guest/info`: una proyección `StayInfo`, no la entidad

**Chosen:** un puerto de lectura `GuestPortalStayReader` (en
`app/guests/domain/portal_ports.py`) que devuelve un `frozen dataclass` con
**exactamente** estos campos y ninguno más:

| Campo | Origen |
|---|---|
| `check_in_date`, `check_out_date` | `reservations` |
| `check_in_time`, `check_out_time` | `reservations`, con *fallback* a `properties.default_check_*_time` (las de la reserva son nullable) |
| `property_name`, `address_line1`, `address_line2`, `city`, `province`, `postal_code`, `country`, `timezone` | `properties` |
| `wifi_name` | `properties` — **el nombre, nunca `wifi_password_encrypted`** |
| `arrival_notes` | `properties.access_notes` — se expone, y `docs/guest-portal.md` advierte al operador de que el huésped lo ve tal cual (OQ2) |
| `access_code_masked` | `access_records.code_masked`, si hay registro vivo para la estancia |
| `support_channel` | constante de configuración, no un dato de otro huésped — `GUEST_PORTAL_SUPPORT_CHANNEL`, texto libre, sin valor por defecto |

R3.2 se cumple **estructuralmente**: el tipo no tiene `internal_notes`,
`gross_amount`, `ota_commission`, `net_amount`, `external_pms_id`,
`external_channel_id`, ni ninguna columna de otro huésped, así que ningún
serializador futuro puede filtrarlos por descuido. Es el mismo mecanismo que
`GuestSummary` (`app/guests/domain/repositories.py:6-12`).

R3.3 también: `document_number` no existe en el tipo. El único endpoint que
devuelve un número de documento sigue siendo `GET /api/v1/guests/{id}/document`.

`access_code_masked` sale ya enmascarado de la base de datos —el sistema **no
almacena el código en claro en ninguna parte** (`access_records` solo tiene
`code_masked`)— así que este endpoint no puede violar la regla 4 aunque quisiera.

### D10 — Check-in: se **ensancha** `SetGuestDocumentUseCase`, no se duplica

**Chosen:** el portal no escribe `guests.document_number_encrypted` por su cuenta.
Reutiliza el escritor que ya existe
(`app/guests/application/use_cases.py::SetGuestDocumentUseCase`), ensanchándolo:

- `GuestActor` pasa a `user_id: uuid.UUID | None` + `token_hash: str | None`, con
  una invariante en `__post_init__`: **exactamente uno** de los dos. Un actor
  vacío deja de ser construible.
- `DocumentInput` gana `full_name: str`, y `GuestRepository.save_document`
  persiste también esa columna.
- `AUDITABLE_FIELDS["GUEST"]` gana `full_name`
  (`app/audit/domain/value_objects.py:235`), auditado como `redacted()` igual que
  los otros tres del grupo documental. **Y `full_name` y `nationality` entran
  además en `REDACTED_FIELDS`** — corregido en run tras el panel de §2, donde
  seguridad y QA demostraron por separado que `diff("full_name", …)` era legal y
  habría escrito en claro, en una tabla append-only, texto que teclea un anónimo.
  La redacción original de esta decisión dejaba `redacted()` como disciplina del
  llamante, que es justo lo que D11 rechaza para `incidents.title`/`description`
  en este mismo change; la asimetría no se sostenía. `nationality` no la
  introduce este change, pero sí le cambia el nivel de confianza: hasta ahora la
  escribía un operador, y `access-notifications` la dejó fuera de la denylist por
  eso. No se pierde nada — ambos siguen en el allowlist, así que `redacted()`
  sigue registrando que cambiaron, que es todo lo que los casos de uso hacían.

El motivo es el docstring del propio módulo: enumera **exhaustivamente** los tres
sitios donde existe el número en claro, y esa enumeración es verificable
precisamente porque hay un escritor. Un segundo caso de uso escribiendo la misma
columna la convertiría en una lista que alguien tiene que acordarse de actualizar.

Encima de él, `SubmitGuestCheckinUseCase`
(`app/guests/application/portal.py`) orquesta: valida, resuelve el huésped de la
estancia —creándolo desde el `full_name` enviado si `reservations.guest_id` es
`NULL`, decidido en OQ3—, delega, reevalúa el estado legal y escribe el
`TimelineEvent`. Enlazar el huésped recién creado necesita un método propio y
estrecho (`set_guest`) junto a `set_status`: `LegalRegistrationStayStore` alcanza
una sola columna a propósito, y ensancharlo para escribir la reserva entera
borraría esa frontera.

La reevaluación de R4.3 **no se reimplementa**: `SetGuestDocumentUseCase` ya llama
a `status_for(...)` sobre `LegalRegistrationStayStore` cuando la escritura nombra
una reserva, y `app/guests/domain/legal_registration.py:89-111` ya se mueve solo
entre `PENDING_GUEST_DATA` y `READY_TO_SUBMIT` sin propagar a otras estancias.
R4.3 es, literalmente, el comportamiento que ya existe; lo único que cambia es
quién lo dispara.

R4.4 (nunca una actualización parcial): un solo `UnitOfWork`, un solo `commit()` al
final. La validación de formato es Pydantic v2 en `api/schemas.py`, así que un
cuerpo inválido muere antes de tocar la base de datos.

**Cómo se consigue ese «un solo `commit()`», que no salió gratis** (corregido en run,
§6): `SetGuestDocumentUseCase.execute` termina con `await self._uow.commit()` de forma
incondicional, así que componerlo dentro de otro caso de uso con una unidad de trabajo
real le da a la operación dos transacciones. El cableado le pasa
`CallerOwnedUnitOfWork` (`app/core/unit_of_work.py`, nuevo), cuyo `commit()` no hace
nada, y la frontera se queda entera en `SubmitGuestCheckinUseCase`. Cuatro de los cinco
revisores de §6 encontraron el fallo por separado, y los tres docstrings que afirmaban
«one transaction with one commit» pasaban sus tests porque ambos cableados dejan
exactamente las mismas filas cuando no falla nada. Lo que los distingue es la
**secuencia**, que ahora fija `tests/guests/test_portal_use_cases.py`.

**Y la reclamación de OQ3 es condicional, no una asignación** (corregido en run, §6):
`set_guest` escribe `WHERE guest_id IS NULL` y devuelve quién sostiene la estancia. Dos
envíos simultáneos del mismo formulario —el reintento por pérdida de red que nombra
R4.5— leían ambos `guest_id IS NULL`, creaban dos `Guest` y el segundo sobrescribía el
enlace: la fila perdedora quedaba huérfana **con el número de documento cifrado
dentro**, inalcanzable desde cualquier ruta y no borrable por el flujo normal. Con la
reclamación condicional el perdedor continúa con el huésped del ganador, y lo más que
deja atrás es una fila con solo un nombre.

Rejected: un `SubmitGuestDocumentUseCase` paralelo — dos escritores del dato más
sensible del sistema.
Rejected: dejar `full_name` fuera y reportarlo solo como ausente — un huésped con
el nombre vacío quedaría en `PENDING_GUEST_DATA` sin ninguna vía para arreglarlo.

### D11 — Auditoría con actor no-usuario: columna nueva en `audit_logs`

**Chosen:** `audit_logs` gana `actor_guest_token_hash VARCHAR(64) NULL`, que
`AuditLogFactory.build` rellena desde `GuestActor.token_hash`.

Las alternativas están cerradas, no descartadas por gusto:

- meterlo en `changes` es **imposible por construcción**: `token_hash` está en
  `REDACTED_FIELDS` (`value_objects.py:66`), así que `diff()` lanza, y además no
  es un campo de la entidad `GUEST`, así que el *allowlist* también lo rechaza.
  El contrato de la regla 11 ya lo impide, que es señal de que ese no es su sitio.
- dejar el actor a `NULL` como hacen las filas del reconciliador contradice R6.1,
  que pide el portador identificado por su referencia no reversible. Y la
  diferencia con el reconciliador es real: allí **no hay** actor a quien nombrar;
  aquí lo hay, y es justo lo que una revisión de incidente necesita.

El índice `ix_audit_logs_tenant_id_actor_user_id_created_at` no se toca: estas
filas caen en el cubo `NULL` de `actor_user_id`, y la pregunta que ese índice
responde («todo lo que hizo esta persona») es sobre usuarios.

**Divergencia declarada del PRD §7.25**, que enumera sus columnas y no incluye
esta. Se justifica porque el PRD §23 declara una superficie de huésped anónima y
la regla 9 exige saber quién tocó los datos: las dos frases solo son
compatibles con una columna.

Vocabulario nuevo en `app/audit/domain/actions.py`:

- `ENTITY_INCIDENT = "INCIDENT"` + `INCIDENT_CREATED` — la regla 9 nombra
  `Incident` en su enumeración explícitamente, así que no hace falta argumentarlo.
  `AUDITABLE_FIELDS["INCIDENT"] = {"source", "status", "reservation_id"}`; **no**
  `title` ni `description`, que son texto libre escrito desde fuera y
  `audit_logs.changes` es un sumidero de la regla 11.
- `GUEST_ACCESS_TOKEN_ISSUED` / `GUEST_ACCESS_TOKEN_REVOKED` con
  `ENTITY_GUEST_ACCESS_TOKEN`, y `AUDITABLE_FIELDS` con `{"token_hash",
  "revoked_at"}` — `token_hash` ya está denegado, así que la única forma
  alcanzable es `redacted()`, exactamente como en `WEBHOOK_ENDPOINT`.

**No** se añade acción nueva para el check-in del huésped: la operación *es*
`GUEST_DOCUMENT_UPDATED` («modificación de documentos de Guest»), y quién la hizo
lo dice el actor, no el verbo. Inventar `GUEST_CHECKIN_SUBMITTED` partiría en dos
la consulta «quién tocó el documento de este huésped».

R6.2 (auditar **antes** de responder) se cumple sin esfuerzo: la fila se escribe
dentro de la misma transacción y antes del `commit()`, así que una escritura de
auditoría que falla revierte la operación entera — el orden que
`ReadGuestDocumentUseCase` ya documenta.

R6.4: ni el token en claro ni el número de documento pueden llegar a estas filas.
El primero porque solo circula su hash desde el autorizador; el segundo porque
`document_number_encrypted` está denegado y `diff()` sobre él lanza.

### D12 — `TimelineEvent`: `INCIDENT_CREATED` existe, el de check-in no

**Chosen:**

- incidencia abierta → `TimelineEventType.INCIDENT_CREATED`, que ya existe, con
  `actor_type = GUEST` (ya existe en `TimelineActorType`) y `actor_user_id = None`
  —que es lo único que `TimelineEventFactory` permite para un actor que no es
  `USER` (`services.py:43-46`).
- check-in completado → **no hay tipo**, así que se añade
  `GUEST_CHECKIN_COMPLETED` a `TimelineEventType`. R6.3 lo exige y ninguno de los
  45 existentes lo dice: `CHECKIN_WINDOW_OPENED` es el reloj, y reutilizar
  `LEGAL_REGISTRATION_SUBMITTED` afirmaría permanentemente que hubo una
  presentación ante la policía que no hubo.

`timeline_events.event_type` es un enum **nativo** de Postgres, así que esto es un
`ALTER TYPE ... ADD VALUE` en la migración (ver Riesgos). `metadata` lleva solo
identificadores —`reservation_id`— nunca campos ni valores del documento: la
timeline es inmutable y nada que aterrice ahí se puede redactar después.

### D13 — Idempotencia del check-in: efecto de negocio una vez, auditoría siempre

**Chosen:** R4.5 se cumple sin claves de idempotencia ni estado extra, porque la
operación es una **sobrescritura completa** del mismo conjunto de campos: reenviar
el formulario deja exactamente el mismo estado final, y `status_for` converge al
mismo valor. Lo único que no sería idempotente son los efectos laterales, y se
tratan de forma distinta y deliberada:

- **`TimelineEvent`: solo cuando el estado legal cambia de verdad.** Un reenvío no
  transiciona nada, así que no escribe un segundo evento en una tabla inmutable.
- **`AuditLog`: en cada llamada, a propósito.** La regla 9 audita accesos y
  modificaciones de PII de huésped; suprimir la segunda fila escondería un segundo
  envío del documento, posiblemente desde otra IP, que es justo lo que una revisión
  de incidente busca. «Sin un segundo efecto» es sobre el efecto de negocio, no
  sobre el rastro.

La incidencia (R5) **no** es idempotente y no se pide que lo sea: un reintento crea
una segunda incidencia en `OPEN`. Lo que la acota es el límite por token de D6.
Queda anotado como deuda conocida, no disfrazado.

### D14 — Emisión y revocación: dos rutas de operador, el token devuelto una sola vez

**Chosen:** R1.6 dejaba abierta la entrega. Se resuelve con la vía mínima que hace
la funcionalidad alcanzable y no invade `access-notifications`:

- `POST /api/v1/reservations/{reservation_id}/guest-access-token` — acuña el token
  de la estancia y **devuelve el valor en claro exactamente una vez**. Si ya había
  uno vigente, lo revoca y devuelve el nuevo: sustitución explícita, que es la
  mitad de R1.5 que el índice parcial no puede dar (devolver el antiguo es
  imposible, solo se guarda su hash).
- `DELETE /api/v1/reservations/{reservation_id}/guest-access-token` — revoca
  (R1.4), sin cuerpo.

Ambas viven en `app/guests/api/router.py` (el autenticado), bajo un permiso nuevo
`MANAGE_GUEST_ACCESS_TOKENS` concedido a `TENANT_OWNER` y `PROPERTY_MANAGER`, y
ambas escriben su `AuditLog`.

Devolver el valor una vez está **explícitamente permitido**: es la excepción única
y nombrada de la regla 3(a) de `steering/security.md` —«un secreto que *nosotros*
generamos para que un tercero nos autentique… se puede devolver una sola vez en el
momento de generarlo y en cada rotación, nunca en una lectura posterior»—. El token
de huésped es exactamente esa clase, igual que `webhook_endpoints.header_secret`.

Rejected: emitirlo automáticamente en el barrido `provision_access_records` — hoy
**nada podría entregarlo**: `ConsoleEmailAdapter` y `MockWhatsAppAdapter` son los
únicos adapters y la spec de `access-notifications` declara que sus plantillas no
llevan enlace de portal. Acuñaría credenciales que nadie recibe, y obligaría a
modificar la spec de otro change.
Rejected: acuñarlo dentro de la plantilla de notificación — eso pertenece al change
que traiga un adapter de envío real (`hardening-release`).

Lo que este diseño deja preparado es la costura: el caso de uso de emisión y su
puerto existen, así que la emisión automática es después un llamante más.

### D15 — La incidencia: `maintenance` gana `application/` y un puerto, nada más

**Chosen:** exactamente lo que pide R5.5 y ni un fichero más:

- `app/maintenance/domain/repositories.py` — `IncidentRepository` con **un solo
  método**, `add(tenant_id, incident)`. Segregación de interfaces: listar, asignar
  o resolver son de `maintenance`, y un puerto que los declarara sería una puerta
  abierta para el siguiente.
- `app/maintenance/application/use_cases.py` — `ReportGuestIncidentUseCase`.
- `app/maintenance/infrastructure/repositories.py` —
  `SqlAlchemyIncidentRepository`.
- **Sin `api/`**: la ruta es del portal, no de `maintenance`.

`incidents.title` es `NOT NULL`, así que el cuerpo lleva `title` (requerido, ≤300
tras `strip()`) además de `description`. Derivarlo de los primeros caracteres de la
descripción sería inventar un dato del huésped.

`reported_by_guest_token` recibe el **hash hexadecimal de 64 caracteres**, nunca el
valor (R5.1); cabe de sobra en su `VARCHAR(200)`.

R5.4: `category`, `severity`, `ai_summary` y `ai_classification` no se pasan — se
quedan en los `server_default` del modelo (`OTHER`, `MEDIUM`, `NULL`, `NULL`), de
modo que la fila es indistinguible de cualquier otra en `OPEN` para el flujo de
clasificación.

R5.3 es **estructural**: no existe ninguna ruta `GET` de incidencias en el portal,
así que no hay nada que restringir. La respuesta del `POST` devuelve `id`, `status`
y `created_at` de la que acaba de crear y nada más.

**Añadido en run, sección 7: `incidents.title`/`description` son la octava y novena
columnas de la regla 11, y se declaran como su segunda excepción nombrada.** Lo
levantó el panel de seguridad de la sección: el esquema traía las dos columnas desde
`domain-foundation-ops` sin escritor, este change es el primero, y el censo de la
regla 11 se hace *«por quién escribe la columna, no por lo que su nombre promete»* —
aquí, un anónimo de internet. La forma estructurada por defecto no es aplicable: la
descripción **es** el relato que la gestora tiene que leer.

Aprobado por Jose el 2026-08-11, por la vía que la regla 9 fija para ampliar una
excepción —*«con una entrada nueva y nombrada aquí, aprobada en el design del change
que la pida»*—, y escrito en `steering/security.md`, que es su único hogar. Este
párrafo lo cita y no lo reenuncia: el propio contrato advierte de que tres revisiones
seguidas encontraron un error distinto en una afirmación que vivía en cinco sitios.

Lo que sí pertenece a este design es el **por qué acotado**: lo que la excepción
concede es texto de un tercero, no un valor que nosotros hayamos ido a buscar, y las
dos garantías que la sostienen ya estaban construidas antes de que la excepción
existiera —`AUDITABLE_FIELDS` deja `title`/`description` fuera de
`audit_logs.changes` (D11) y el evento de timeline lleva título constante e
identificadores (D12)—, así que el valor no se propaga. Lo que la excepción añade es
el deber de decírselo al operador, que es la cara simétrica de la advertencia de OQ2
y vive con ella en `docs/guest-portal.md` (tarea 8.2).

### D16 — Contrato de error y OpenAPI

**Chosen:** las cuatro rutas declaran su propio `responses=` con `404`/`429`/`413`
apuntando a `ErrorEnvelope`, como `_RECEIVER_RESPONSES`
(`webhooks_router.py:66-86`), y **no** `AUTHENTICATED_RESPONSES` —no pueden
prometer un `401` que nunca devuelven—. Ningún código de error nuevo:
`NOT_FOUND`, `RATE_LIMITED`, `PAYLOAD_TOO_LARGE` y `VALIDATION_ERROR` ya están en
`app/core/error_codes.py`, así que el registro y su guard no cambian.

`backend/openapi.json` (`make openapi`) y
`frontend/lib/api/generated/openapi.d.ts` (`npm run api:generate`) se regeneran y
se commitean en el mismo PR — las dos mitades del puente de
`steering/documentation.md`.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Token (dominio) | `backend/app/guests/domain/portal_token.py` **(nuevo)** | `generate_guest_token()`, `hash_guest_token()`; stdlib puro, calcado de `webhook_auth.py` |
| Token (esquema) | `backend/app/guests/infrastructure/models.py` | `GuestAccessTokenModel` (D2) |
| Token (puertos) | `backend/app/guests/domain/portal_ports.py` **(nuevo)**, `domain/ports.py` | `GuestAccessTokenRepository`, `GuestPortalStayReader`, `StayInfo`, `GuestSession`; y `LegalRegistrationStayStore.set_guest` (OQ3) |
| Token (adapters) | `backend/app/guests/infrastructure/portal_repositories.py` **(nuevo)** | implementaciones SQLAlchemy; la consulta por `token_hash` sin tenant |
| Autorización | `backend/app/guests/application/portal.py` **(nuevo)** | `GuestPortalAuthenticator` (D4), `GetStayInfoUseCase`, `GetCheckinStatusUseCase`, `SubmitGuestCheckinUseCase` |
| Emisión | `backend/app/guests/application/portal.py` | `IssueGuestAccessTokenUseCase`, `RevokeGuestAccessTokenUseCase` (D14) |
| API pública | `backend/app/guests/api/portal_router.py` **(nuevo)**, `portal_schemas.py` **(nuevo)** | las cuatro rutas de PRD §23 (D1, D5, D16) |
| API operador | `backend/app/guests/api/router.py`, `schemas.py`, `dependencies.py`, `errors.py` | las dos rutas de D14 y el cableado de todo lo nuevo |
| Escritor de documento | `backend/app/guests/application/use_cases.py`, `domain/repositories.py`, `infrastructure/repositories.py` | `GuestActor` con `token_hash`, `DocumentInput.full_name`, `save_document` persiste `full_name` (D10) |
| Límite de tasa | `backend/app/guests/infrastructure/portal_throttle.py` **(nuevo)** | `RedisGuestPortalThrottle` (D6) |
| Incidencia | `backend/app/maintenance/{domain/repositories.py,application/use_cases.py,infrastructure/repositories.py}` **(nuevos)** | R5.5, D15 |
| Auditoría | `backend/app/audit/{infrastructure/models.py,domain/entities.py,domain/services.py,domain/actions.py,domain/value_objects.py}` | columna `actor_guest_token_hash`, vocabulario nuevo, `AUDITABLE_FIELDS` (D11) |
| Timeline | `backend/app/timeline/domain/enums.py` | `GUEST_CHECKIN_COMPLETED` (D12) |
| Log | `backend/app/core/log_redaction.py`, `backend/app/main.py` | segundo patrón de ruta, renombrado del filtro e instalador (D8) |
| RBAC | `backend/app/auth/domain/policy.py` | `MANAGE_GUEST_ACCESS_TOKENS` y su reparto |
| Config | `backend/app/core/config.py`, `.env.example` | `guest_portal_token_grace_days`, `guest_portal_rate_limit_per_minute`, `guest_portal_probe_limit_per_minute`, `guest_portal_support_channel` (D9) |
| Montaje | `backend/app/main.py`, `backend/tests/test_route_authorization.py` | router nuevo + cuatro entradas en `ANONYMOUS_ENDPOINTS` |
| Migración | `backend/alembic/versions/<rev>_guest_portal_api.py` **(nuevo)** | tabla, columna de `audit_logs`, valor de enum |
| Contrato | `backend/openapi.json`, `frontend/lib/api/generated/openapi.d.ts` | regenerados |
| Docs | `docs/guest-portal.md` **(nuevo)**, `docs/diagrams/<fecha>_autohost-er-entidades.png`, `README.md`, `docs/README.md` | capability nueva; ER regenerado (cifra en la tarea 8.3); `maintenance` gana `application/` en la estructura del README |

## Data & interfaces

**Tabla nueva** `guest_access_tokens` (`Base`, `UUIDPrimaryKeyMixin`,
`TenantScopedMixin`, `TimestampMixin`):

| Columna | Tipo | Nota |
|---|---|---|
| `reservation_id` | `UUID` FK `reservations.id` `ON DELETE RESTRICT`, `NOT NULL` | la estancia que autoriza |
| `token_hash` | `VARCHAR(64)`, `index=True, unique=True` | SHA-256 hex; único **global**, se consulta sin tenant |
| `revoked_at` | `TIMESTAMPTZ NULL` | R1.4; también cubre «consumido» de R2.2 |

Índice parcial `uq_guest_access_tokens_live_per_reservation`
sobre `(reservation_id) WHERE revoked_at IS NULL` — R1.5.

**Columna nueva** `audit_logs.actor_guest_token_hash VARCHAR(64) NULL` (D11) — 64
porque es un SHA-256 hex, igual que `webhook_endpoints.token_hash`.

**Valor nuevo de enum** `timeline_event_type`: `GUEST_CHECKIN_COMPLETED` (D12).

**API pública** (sin autenticación, token en la ruta):

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /api/v1/guest/info/{token}` | — | `StayInfoResponse` (D9) |
| `GET /api/v1/guest/checkin/{token}` | — | `{missing_fields: [...], document_status, legal_registration_status}` — **qué falta**, nunca lo ya aportado (R4.1) |
| `POST /api/v1/guest/checkin/{token}` | `full_name`, `nationality`, `date_of_birth`, `document_type`, `document_number`, `document_expiry_date` | `{document_status, legal_registration_status}` — **no** eco del número |
| `POST /api/v1/guest/incident/{token}` | `title`, `description` | `{id, status: OPEN, created_at}` |

Todos los cuerpos rechazan campos no declarados (`extra="forbid"`), incluidos los
de identidad como `tenant_id` o `reservation_id`, siguiendo la norma que
`access-notifications` ya fijó.

**API de operador** (JWT, `MANAGE_GUEST_ACCESS_TOKENS`):
`POST` y `DELETE /api/v1/reservations/{reservation_id}/guest-access-token`.

**Variables de entorno** (`.env.example`, nombres sin valores sensibles; ninguna
es secreta, así que las tres llevan defecto):
`GUEST_PORTAL_TOKEN_GRACE_DAYS=2`, `GUEST_PORTAL_RATE_LIMIT_PER_MINUTE=60`,
`GUEST_PORTAL_PROBE_LIMIT_PER_MINUTE=20`.

## Risks & mitigations

- **`ALTER TYPE ... ADD VALUE` sobre `timeline_event_type`.** En Postgres un valor
  de enum añadido no puede **usarse** en la misma transacción que lo añade —
  añadirlo sí se puede, desde PostgreSQL 12. Esta redacción decía «no puede usarse»
  y concluía envolverlo en `op.get_context().autocommit_block()`; **corregido en
  run tras implementarlo**, porque la conclusión no se sigue de la premisa y el
  precedente que este mismo diseño cita ya lo tenía resuelto:
  `b7c41d92e5a3_session_revoked_reason_administrative.py` lo documenta y no usa
  bloque autocommit. La migración de este change solo **añade** el valor; ninguna
  fila de `timeline_events` se escribe en ella.

  Y el bloque autocommit no habría sido neutral: `backend/alembic/env.py` envuelve
  toda la tanda en un único `context.begin_transaction()`, así que abrir uno
  comitearía todas las revisiones anteriores y `alembic upgrade head` dejaría de ser
  todo-o-nada. Se implementa por tanto con un `ALTER TYPE ... ADD VALUE IF NOT
  EXISTS` normal, y la verificación son las dos direcciones contra PostgreSQL 16:
  `upgrade head`, `alembic check` sin deriva, `downgrade base` y re-`upgrade`.
- **El índice parcial y la carrera de dos emisiones concurrentes.** Dos `POST` de
  emisión simultáneos sobre la misma reserva: uno gana, el otro recibe
  `IntegrityError`. Se traduce a `409 CONFLICT` en vez de propagar un `500`; el
  operador reintenta y obtiene el token vigente del ganador… que no puede
  devolverse. Mitigación: la emisión revoca-y-crea **dentro de la misma
  transacción**, así que el perdedor no deja estado y su reintento acuña limpio.
- **La superficie anónima escribe PII.** Es el riesgo intrínseco del change. Lo
  que lo acota: el token es 256 bits de CSPRNG, la ventana es la estancia más dos
  días, el límite por IP hace que adivinar cueste, el cuerpo está topado en 1 MiB
  antes del routing, y cada escritura deja `AuditLog` con el hash del portador y la
  IP. Nada de eso impide que quien **tenga** el enlace escriba: el modelo de
  amenaza es «el enlace es la credencial», igual que en cualquier portal de
  huésped, y por eso la vigencia es corta y revocable.
- **Fuga por el log de acceso.** Cerrada en D8; el riesgo real es que alguien
  añada una quinta ruta de huésped con otra forma de path y el patrón no la cubra.
  Mitigación: el patrón ancla en `/api/v1/guest/` + un segmento, así que cubre
  cualquier acción futura bajo ese prefijo.
- **Ensanchar `GuestActor` afloja una invariante existente.** `user_id` deja de ser
  obligatorio, y una llamada del manager podría escribir una fila sin actor.
  Mitigación: la invariante «exactamente uno de los dos» en `__post_init__`, con
  test propio; el tipo se vuelve más estricto, no menos.
- **`maintenance` estrena `application/` con un solo caso de uso.** El riesgo es
  que el change que traiga la clasificación IA encuentre un puerto que no le sirve.
  Es el precio correcto: `steering/domain-foundation-ops.md:12` dice que el
  `application/` lo pone quien primero persiste la entidad, y un puerto de un
  método es más fácil de ensanchar que uno especulativo de diez.
- **El ER queda obsoleto.** Se regenera desde la metadata de SQLAlchemy y se borra el
  anterior, como manda `steering/architecture.md`. La cifra resultante vive en la tarea
  8.3 y en ese steering, no aquí.

## Open questions

Las cuatro que este diseño abrió quedaron **resueltas en el gate por Jose el
2026-08-10**, todas en el sentido recomendado. Se conservan aquí con su decisión
porque el porqué de cada una es parte del diseño, no ruido de proceso.

**OQ1 — ¿Quién acuña el token (D14)? → Ruta de operador.** La alternativa era el
barrido `provision_access_records`, más fiel a «el sistema solicita datos al
huésped» (PRD §17, paso 2), pero hoy ningún adapter puede entregar el enlace, así
que acuñaría credenciales que nadie recibe. La emisión automática llega con el
adapter de envío real; este diseño deja la costura hecha.

**OQ2 — ¿Se expone `properties.access_notes` (D9)? → Sí, con advertencia
explícita.** Es el campo cuyo propósito son las instrucciones de llegada y cuyo
destinatario es el huésped, pero es texto libre donde un operador podría pegar un
código de puerta en claro y la regla 4 exige `****XX` siempre. Se expone **y**
`docs/guest-portal.md` advierte al operador de que ese campo se le enseña al
huésped tal cual. Se descartó no exponerlo: dejaría la llegada en
`access_code_masked` más un canal de soporte, que para quien está en la puerta es
casi inútil.

**OQ3 — `reservations.guest_id` a `NULL` (D10) → se crea el `Guest`.** El
`POST /reservations` permite una reserva sin huésped, así que el caso es real.
Rechazar dejaría estancias que nunca pueden completar su registro legal y sin
señal para el operador. Crear está acotado: una fila por estancia, y solo para un
token que un operador ya decidió acuñar. **Consecuencia de implementación**: hace
falta un método nuevo y estrecho para escribir `reservations.guest_id`
—`LegalRegistrationStayStore` solo toca el estado legal, y ensancharlo rompería la
razón por la que es estrecho—, así que el puerto lo declara `guests/domain` y lo
implementa `guests/infrastructure`, junto a `set_status`.

**OQ4 — `audit_logs.actor_guest_token_hash` (D11) → aceptada como divergencia
declarada.** Del PRD §7.25, que enumera las columnas de esa tabla y no la incluye.
Las dos alternativas estaban cerradas, no descartadas por gusto: `changes` lo
prohíbe la regla 11 por construcción, y el actor `NULL` contradice R6.1. Se anota
en `sdd/specs/` al archivar, junto a la de `guest_access_tokens`.
