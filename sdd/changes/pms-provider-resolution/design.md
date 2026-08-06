# Design: pms-provider-resolution

## Context

`PMSAdapter` (`backend/app/integrations/domain/ports.py:26`) es un `Protocol` con **dos** métodos, `list_reservations` y `get_reservation`, más un atributo de clase `unmappable_rows: list[str]` que el propio módulo declara *"Still a stopgap"* (`ports.py:42-48`). Las otras seis operaciones de PRD §16 —incluidas `get_messages` y `send_message`— **no existen**: llegan con los changes que las consumen. Hay dos implementaciones, `MockPMSAdapter` (`infrastructure/mock_pms.py:27`) y `ChannexAdapter` (`infrastructure/channex/adapter.py:29`), y la elección entre ellas la hace hoy `build_adapter(provider)` (`cli/pms_sync.py:63`), un flag de operador que su propio docstring llama stopgap. `SyncReservationsFromPmsUseCase` recibe el adapter por constructor (`application/use_cases.py:42`) y **solo se construye desde el CLI** (`cli/pms_sync.py:131`): no hay ninguna ruta HTTP que resuelva un adapter de PMS (`api/router.py` tiene una sola ruta, la de CSV).

`Property` (`properties/infrastructure/models.py:21`) no tiene columna de proveedor ni de credencial; la única de cara al PMS es `pms_external_id`. `properties/` tiene `domain/`, `application/` e `infrastructure/`, pero **no `api/`**, así que hoy no existe ninguna respuesta HTTP por la que una credencial pudiera salir. No existe primitiva de cifrado: `git grep -in fernet -- backend/` y `-in cryptography` devuelven cero, y `wifi_password_encrypted` / `document_number_encrypted` son `Text` pelado — un diferimiento explícito de `domain-foundation-core` (`specs/domain-foundation-core.md:31`). Terraform sí genera la clave (`infra/environments/dev/main.tf:317-356`, base64url válido para Fernet) y el CD la escribe en el `.env` de la VM, pero **ningún código Python la lee** y `app/core/config.py` no tiene campo para ella.

Dos hechos del entorno que condicionan casi todas las decisiones de abajo: **no corre ningún type checker** —`pyproject.toml` declara solo pytest, no hay `pyrightconfig.json`, y CI ejecuta migraciones, `alembic check`, la suite y `alembic downgrade base` y nada más (`app/core/db.py:142-143` lo dice explícitamente)—; y **no existe ningún `TypeDecorator` en el backend**, así que una columna que se cifre sola sería un patrón nuevo sin precedente local.

## Decisions

### D1 — Los puertos en `domain/`, la factory partida en puerto e implementación

**Chosen:** `PMSMessagingPort` se declara junto a `PMSAdapter` en `backend/app/integrations/domain/ports.py`, vacío de métodos en este change. `PMSAdapterFactory` se declara como `Protocol` en el mismo fichero y se implementa en `backend/app/integrations/infrastructure/pms_factory.py`. `application/` recibe la factory por constructor y la tipa contra el puerto.

`tests/test_layering.py` decide esto, no el gusto: `test_application_modules_reach_infrastructure_only_through_ports` prohíbe que `application/` importe `app.integrations.infrastructure.*`, y `test_domain_modules_do_not_import_outer_layers` lo prohíbe también en `domain/`. Una factory que construye `ChannexAdapter` **solo** puede vivir en `infrastructure/`, `api/` o `cli/`. Partirla en puerto + implementación es lo que permite que el caso de uso dependa de ella sin romper la regla de dependencia, y es exactamente lo que pide ADR 0006 decisión 7 (*"los casos de uso nunca reciben un adapter inyectado como singleton"*). Precedente idéntico en el repo: `ReservationCsvParser` es puerto en `domain/ports.py:65` e implementación en `infrastructure/csv_parser.py:379`.

Rejected: la factory entera en `domain/` — la tumba el test de layering. Rejected: dejarla en `cli/` como hoy `build_adapter` — el scheduler la necesitará y `cli/` no es importable desde `app/scheduler/` sin invertir la dependencia. Rejected: una función `build_adapter(property)` sin puerto — no se puede inyectar ni sustituir en test sin parchear el módulo.

### D2 — Forma de la factory frente a los dos puertos

**Chosen** (aprobado por Jose, 2026-08-05): dos métodos, y la capacidad separada de la resolución:

```python
class PMSAdapterFactory(Protocol):
    def supports_messaging(self, provider: PMSProvider) -> bool: ...
    async def reservations_for(self, property: Property) -> PMSAdapter: ...
    async def messaging_for(self, property: Property) -> PMSMessagingPort: ...
```

`messaging_for` **lanza** `PMSMessagingUnsupportedError` (error de dominio, nombrando el proveedor) cuando el proveedor no la soporta; no devuelve `None`. `supports_messaging` es **puro**: depende solo del proveedor, no toca credenciales y no audita nada.

Esta es la respuesta a la pregunta que ADR 0006 decisión 7 deja abierta (*"¿una factory con dos métodos, o resolución de puerto opcional que devuelve `None`?"*), y la decide un hecho medido: **no corre ningún type checker**. Un `PMSMessagingPort | None` no lo comprueba nadie — ni CI ni un hook—, así que el `None` viajaría hasta un `AttributeError: 'NoneType' object has no attribute 'send_message'` en el peor sitio posible. Un error de dominio nombrado falla igual de pronto pero se explica solo, y es el estilo del módulo (`PmsUnavailableError`, `AmbiguousPropertyExternalIdError`).

Que `supports_messaging` sea puro no es cosmético: resolver un adapter **descifra credenciales**, y descifrar es un acto auditado (D6). Si la única forma de preguntar «¿esta propiedad tiene mensajería?» fuera intentar resolverla, planificar el trabajo de `messaging-ai` convertiría cada consulta de capacidad en un descifrado auditado. Separar la pregunta de la resolución evita convertir una consulta en un efecto. **Sin cifra**: una versión anterior decía «una fila por propiedad consultada», que es falso precisamente en el caso que D4 establece como el real —credencial de cuenta, que `CredentialReadLog` deduplica— y lo decía citando a D6 mientras contradecía su mecanismo. El argumento no necesitaba el número.

Qué hace `messaging-ai` ante una propiedad sin mensajería **no se decide aquí**: este change le da la pregunta (`supports_messaging`) y el error (`PMSMessagingUnsupportedError`); la política de producto es suya.

Rejected: `-> PMSMessagingPort | None` — sin type checker no lo verifica nada. Rejected: un solo `resolve(property)` devolviendo un bundle con ambos puertos — obliga a resolver mensajería para hacer un sync de reservas, y con ella a descifrar y auditar una credencial que ese caso de uso no necesita; choca con Interface Segregation (`steering/backend-architecture.md:109`). Rejected: dos factories independientes — duplican la resolución de proveedor y credenciales.

### D3 — Cifrado explícito en `app/core/crypto.py`, no un `TypeDecorator`

**Chosen:** un módulo `backend/app/core/crypto.py` con una primitiva estrecha y un value object opaco:

```python
class EncryptedSecret:              # domain-side, sin dependencia de cryptography
    """Ciphertext + nada más. No __str__/__repr__ que revele el claro."""
def encrypt(plaintext: str) -> EncryptedSecret: ...
def decrypt(secret: EncryptedSecret) -> str: ...   # el único sitio que produce claro
```

El descifrado es una **llamada explícita en un único punto de estrangulamiento** (la factory), no un efecto colateral de cargar una fila.

El motivo es que las dos obligaciones de R4 lo exigen en direcciones opuestas a lo que hace un `TypeDecorator`: R4.1 prohíbe que la credencial descifrada llegue a una respuesta, y R4.2 obliga a auditar cada lectura. Una columna que se descifra sola en cada `SELECT` es precisamente el mecanismo por el que una credencial acaba en un `PropertyOut`, y hace **imposible** saber dónde auditar, porque no hay una llamada que interceptar. Además no existe ningún `TypeDecorator` en el backend, así que no se hereda ningún patrón. Va en `app/core/` porque es infraestructura compartida sin entidad de negocio, que es el criterio que `steering/architecture.md:13` ya usó para descartar alojar `AuditLog` ahí.

`EncryptedSecret` sigue el precedente de cerrar el contrato **por construcción** y no por convención — el mismo argumento que llevó a `ChangeSet` + `AuditLogFactory` en `user-management`, donde el panel de seguridad demostró tres vías de fuga antes de que quedara cerrado (`steering/backend-architecture.md:136`). La redacción de `__repr__` copia `ChannexClient.__repr__` (`channex/client.py:55-61`), el único precedente de redacción del repo.

Rejected: `TypeDecorator` (`EncryptedText`) — descifra en cada carga, no deja punto donde auditar y es el camino directo a la fuga por serialización. Rejected: cifrar/descifrar a mano en cada repositorio — es la convención repetida que este proyecto ya vio fallar. Rejected: `SecretStr` de Pydantic — no cifra nada y `domain/` no puede importar Pydantic (`test_layering.py`).

### D4 — Las credenciales en su propia tabla con `scope`, no en columnas de `Property`

**Chosen** (aprobado por Jose, 2026-08-05): `Property` gana **una** columna, `pms_provider` (enum nativo, nullable). Las credenciales viven en una tabla nueva `pms_credentials`, tenant-scoped, con `id`, `tenant_id`, `provider`, `scope ∈ {PROPERTY, ACCOUNT, ORGANIZATION}`, `property_id` (nullable, solo con `scope=PROPERTY`), `secret_encrypted`, `rotated_at`.

ADR 0006 decisión 7 dice literalmente *"`Property` guarda su proveedor y sus credenciales"*, pero **dos párrafos después dice lo contrario y acierta**: *"No todas las credenciales son por propiedad… la regla 3 ampliada cubre las tres granularidades —propiedad, cuenta y organización— y no solo la primera."* Y la medición lo confirma: la credencial real de Beds24 es **un refresh token de cuenta** (`docs/beds24-spike.md:93,256` — *"El refresh token es de cuenta, no de propiedad"*), la de Channex una API key de cuenta, y la única credencial por propiedad que Beds24 tiene es la *access key* de la Arrivals API, que pertenece a la capa de accesos aplazada en la decisión 5. Columnas de credencial en `Property` obligarían a duplicar el mismo secreto de cuenta en cada fila: N copias del mismo texto cifrado, N sitios que rotar, y una rotación parcial que deja propiedades autenticando con un token muerto.

Hay además un motivo mecánico que no es negociable: `AuditLog.entity_id` es un `uuid.UUID` **requerido** (`audit/domain/entities.py:7-19`). Una credencial de cuenta u organización no tiene UUID al que apuntar si vive esparcida en columnas; como fila de `pms_credentials` sí lo tiene, y R4.2 se puede cumplir sin inventar un `entity_id` falso.

Se registra como **desviación del texto literal de ADR 0006** que sirve su intención; si se aprueba, el ADR merece una nota (Q1).

Rejected: columnas en `Property` (`pms_credentials_encrypted`) — duplica el secreto de cuenta por propiedad y no da `entity_id` para auditar. Rejected: credenciales de cuenta en el entorno y solo las de propiedad en base de datos — estructuralmente incapaz de sostener N tenants con su propia cuenta, que es el mismo argumento que ADR 0006 usa para retirar `PMS_PROVIDER`. Rejected: una tabla por granularidad — tres esquemas, tres tests de aislamiento y tres caminos de cifrado para un solo contrato.

### D5 — `ENCRYPTION_KEY` en `Settings` con validador, y cerrar la fontanería

**Chosen:** `Settings` gana `encryption_key: str = Field(min_length=1)` más un validador `mode="after"` que comprueba que es una clave Fernet válida (32 bytes en base64url), copiando la forma de `_reject_whitespace_jwt_secret` (`config.py:82-88`), que existe justamente porque `Field(min_length=32)` acepta 32 espacios.

La clave ya existe en dev de punta a punta (Terraform → Vault → CD → `.env` de la VM → `docker-compose.deploy.yml:120`), pero **solo llega al servicio `backend` del compose de despliegue**. Faltan seis piezas y todas son de este change: el nombre en `.env.example` (solo nombre, nunca valor — regla 8), las líneas `${ENCRYPTION_KEY:?...}` en `docker-compose.yml` para `backend`/`worker`/`migrate`, la generación local en el `Makefile` (y **no** con `openssl rand -hex 32` como la JWT: una clave Fernet es base64url de 32 bytes, `openssl rand 32 | base64 | tr '+/' '-_'`), las líneas que faltan en `docker-compose.deploy.yml` para `worker`/`migrate`/`beat`, el nombre en `.env.deploy.example`, y el campo con su validador.

Consecuencia que conviene tener presente: `settings = Settings()` es un singleton de módulo que se valida **al importar** (`config.py:104`), y `alembic/env.py:15` importa `settings`. Una clave ausente o inválida rompe también `alembic upgrade`, no solo el arranque de la API. Es el comportamiento correcto —fail-fast— pero hay que plumarla en el servicio `migrate` o CI se cae.

Rejected: una segunda variable propia para credenciales de PMS — R3.3 lo prohíbe y ADR 0006 ya aceptó la clave compartida, con `MultiFernet` nombrado como salida futura. Rejected: leer la clave con `os.environ` en `crypto.py` sin pasar por `Settings` — se salta el fail-fast y la validación.

### D6 — Auditoría: rotación siempre; lectura, según Q2

**Chosen** (aprobado por Jose, 2026-08-05): toda **rotación** de credencial escribe su fila de `AuditLog`, y la **lectura** automática dentro de un sync o un job se acota.

**La granularidad exacta NO se enuncia aquí.** Vive en un solo sitio, la entrada nombrada de la **regla 9 de `sdd/steering/security.md`**, y este design la cita. Es una decisión tomada tras el panel a escala de feature, y es correctiva: tres revisiones seguidas encontraron un error **distinto** en el enunciado porque la misma afirmación estaba duplicada en cinco artefactos, y cada ronda arreglaba una copia dejando obsoletas las demás. Este párrafo era una de esas copias — conservó durante dos rondas la unidad equivocada («3.600 filas por propiedad») y la promesa imposible («este run leyó credenciales de estas propiedades») que la regla ya había corregido. Un contrato con dos hogares no tiene ninguno.

Lo que este design sí aporta, porque es suyo y no de la regla: **la aprobación** que la regla 9 exige para acotarse, y el mecanismo — `CredentialReadLog`, que deduplica por id de credencial dentro de la ejecución, y `_record_credential_reads`, que escribe las filas al cerrar el run.

Mecánica, ya verificada contra el código: añadir acciones cuesta tres ediciones en dos ficheros —la constante y su alta en el frozenset `ACTIONS`, el `ENTITY_PMS_CREDENTIAL` en `ENTITY_TYPES`, y una clave en `AUDITABLE_FIELDS` (`audit/domain/value_objects.py:69-92`), obligatoria incluso para un evento sin diff porque `ChangeSet.__init__` rechaza un `entity_type` desconocido—. Una **lectura** se representa con un `ChangeSet` vacío, que es falsy y se persiste como `NULL` (ya cubierto por `tests/audit/test_factory.py:62`). Una **rotación** se representa con `redacted(field)` → `{"changed": true}`; nótese que `diff()` sobre un nombre `*_encrypted` **lanza** porque está en `REDACTED_FIELDS`, así que `redacted()` es la única vía y eso es correcto. Y el nombre de la columna nueva se añade a `REDACTED_FIELDS` (`value_objects.py:29-48`), cuyo docstring ya lo pide: *"A new sensitive column adds its name here."*

Rejected: auditar cada descifrado — véase el volumen; y convierte `audit_logs` en un log de aplicación. Rejected: no auditar nada de lectura — ADR 0006 obligación 4 la pide expresamente y la deja fuera de la enumeración de la regla 9 justamente para que este change la cierre.

### D7 — La escritura de credenciales no pasa por `PropertyRepository.save()`

**Chosen:** un repositorio propio, `PmsCredentialRepository` (puerto en `properties/domain/repositories.py` o en `integrations/domain/`, ver tabla de áreas), con `get_for(tenant_id, provider, scope, property_id)` y `upsert(tenant_id, credential)`. `PropertyRepository.save()` no se toca.

No es preferencia: `save()` escribe **una** columna a propósito (`properties/infrastructure/repositories.py:98-109`) y el docstring de su puerto prohíbe ensancharlo — *"widening this to a full update would offer every future caller a way to change a property without passing through the machine, which `steering/backend.md` forbids outright"*. Meter credenciales ahí rompería una regla escrita. Como las credenciales viven en su propia tabla (D4), la separación sale gratis.

La columna `pms_provider` de `Property` sí necesita camino de escritura y hoy **no existe ninguno** (no hay create ni update genérico de propiedades). Se resuelve con un método estrecho y nombrado, `set_pms_provider(tenant_id, property_id, provider)`, con el guard `CrossTenantWriteError` como primera sentencia, igual que los diez sitios que ya lo hacen.

Rejected: ensanchar `save()` — prohibido por el docstring del puerto y por `steering/backend.md`. Rejected: escribir con SQL crudo desde el caso de uso — se salta el guard cross-tenant.

### D8 — Marcado de sesión: cumplir el contrato que ya existe, no derivar uno nuevo

**Chosen:** R5 no introduce contrato nuevo. `specs/celery-jobs.md:38-53` ya fija el patrón completo —una sesión nueva marcada por tenant, nunca reutilizada ni desmarcada, tenants enumerados desde una sesión nunca marcada y cerrada antes de empezar, `tenant_id` explícito en toda consulta y comprobado en toda escritura—, y `bind_session_to_tenant` (`app/core/db.py:132-162`) ya lanza al re-marcar y ante `None`. Lo que este change añade es una obligación sobre la **factory**: no guarda ni cachea sesión alguna, de forma que no pueda convertirse en el objeto que arrastra la sesión de un tenant a la resolución de otro. Los adapters sostienen clientes HTTP, no sesiones — ya es cierto (`ChannexAdapter(client)`), y pasa a ser contrato.

Es el mismo criterio que el roadmap ya aplicó a `access-notifications` con los sumideros de la regla 11: quien escribe después **se atiene al contrato que hay**, no deriva uno nuevo.

Rejected: una sesión larga re-marcada por tenant — la rechaza el guard. Rejected: cachear adapters por propiedad en la factory — invita a retener sesión y credencial descifrada más allá de su uso.

### D9 — `--provider` sobrevive como override explícito de operador

**Chosen:** la resolución por propiedad es el mecanismo. `--provider` se conserva como **override** de operador que fuerza un proveedor para toda la ejecución, se documenta como tal y **se informa de forma destacada en la salida del comando** cuando está activo. Sin flag, cada propiedad resuelve el suyo; una propiedad con `pms_provider` nulo usa el defecto de bootstrap (`mock`).

`specs/reservations.md:162-166` defiende el flag con un argumento que sigue en pie —*"Un flag de operador no puede filtrarse a la aplicación ni resucitar ese nombre"*— y `reservations.md:147-149` fija que sin flag el comportamiento del comando y de la suite no dependa de configuración alguna. Retirarlo entero rompería el arranque local y la suite sin ganar nada; convertirlo en el mecanismo es lo que ADR 0006 prohíbe. Override explícito, ruidoso y de operador es la única lectura que respeta las tres cosas.

Los códigos de salida no cambian: 2 para argumento inválido o tenant inexistente, 3 para proveedor que no responde, 0 con filas omitidas (`cli/pms_sync.py:200-243`). Se añade un caso: IF una propiedad declara un proveedor cuyas credenciales no están, THEN el comando falla con 3 y nombra la propiedad y la variable o fila que falta, **nunca cae a `mock`** — el mismo razonamiento que `reservations.md:150-152` ya fija para `CHANNEX_API_KEY` (*"un fallback silencioso informaría «created 0» y sería indistinguible de un PMS vacío"*).

Rejected: retirar el flag — rompe suite y arranque local. Rejected: que la propiedad gane siempre sobre el flag — deja al operador sin forma de forzar mock en local.

### D10 — R6: `PmsFetchResult` y el pliegue se muda al caso de uso

**Chosen:** `list_reservations` pasa a devolver un tipo ancho en `domain/dtos.py`, siguiendo `ParseResult`:

```python
@dataclass(frozen=True)
class PmsRowFailure:
    external_id: str | None      # el PMS no tiene números de línea
    reason: str

@dataclass(frozen=True)
class PmsFetchResult:
    reservations: list[ReservationDTO]
    failures: list[PmsRowFailure]
```

`unmappable_rows` desaparece del `Protocol` y de las dos implementaciones. El pliegue de filas descartadas se mueve de `cli/pms_sync.py:152-154` a `SyncReservationsFromPmsUseCase.execute`, que es donde el caso de uso de CSV ya lo hace (`application/use_cases.py:140-143`) — esa asimetría es justo lo que el stopgap causó.

No se copia `RowFailure` porque su `line: int` es obligatorio y en el PMS no hay líneas; `external_id` es el identificador que el operador necesita, y mejora sobre el string concatenado que `ChannexAdapter` compone hoy (`adapter.py:70`). Se conserva la higiene ya documentada: en el motivo van el identificador y la clase de error, **nunca el payload**.

Beneficio lateral que cierra un agujero real: el idioma de conformidad del repo es `vars(Port)` + `callable(getattr(...))` (`tests/test_unit_of_work.py:29-39`), y `vars()` **no ve** una anotación desnuda como `unmappable_rows: list[str]` — vive en `__annotations__`. Es decir, el test de conformidad de puertos hoy no cubre ese miembro. Retirarlo hace que el idioma vuelva a ser completo.

Rejected: dejar `unmappable_rows` — el módulo lo declara stopgap y este change es el que toca la forma del puerto. Rejected: reutilizar `ParseResult` — su `line` obligatorio no aplica al PMS.

### D11 — `pms_provider` como enum nativo, con la ceremonia de migración completa

**Chosen:** `PMSProvider(str, enum.Enum)` en `backend/app/integrations/domain/enums.py` (idioma del repo: `properties/domain/enums.py`), con miembros `MOCK`, `CHANNEX`, `BEDS24`. En el modelo, `Enum(PMSProvider, name="pms_provider", native_enum=True)`; ídem para `pms_credential_scope`. Cero `CheckConstraint`: el repo usa enums nativos sin excepción.

La migración es la primera del repo con `op.add_column` y con una tabla nueva a la vez, así que hay dos cosas que **no** salen de autogenerate y hay que escribir a mano: crear los tipos enum explícitamente antes del `add_column` (no hay `CREATE TABLE` que los cree como efecto colateral para la columna de `Property`), y **dropearlos en `downgrade`** con `postgresql.ENUM(name=...).drop(op.get_bind(), checkfirst=True)`, como hacen las cuatro migraciones que crean tipos. CI ejecuta `alembic check` y `alembic downgrade base`, así que un tipo huérfano rompe la build.

**No hay migración de datos.** Las columnas nacen vacías y `pms_provider` es nullable, así que no hay nada que re-cifrar ni backfillear — lo cual es una suerte, porque el repo no tiene ni un solo precedente de migración con `UPDATE`/`INSERT` sobre filas existentes.

Rejected: `String` + `CheckConstraint` — sin precedente en el repo. Rejected: añadir los proveedores como texto libre — pierde la validación en el borde de la base de datos.

### D12 — Conformidad de puertos por test, no por anotaciones

**Chosen:** cada puerto nuevo gana un test de conformidad en el idioma del repo —enumerar el puerto y comprobar que la implementación expone sus miembros (`tests/test_unit_of_work.py:29-39`)— y el caso «proveedor sin mensajería» gana un test explícito de que `messaging_for` lanza y `supports_messaging` devuelve `False`. Nada se apoya en que una anotación sea correcta.

No es celo: **CI no ejecuta ningún type checker**, así que un adapter que no cumpla un `Protocol` no lo detecta nadie. Y `runtime_checkable` no se usa en el repo por decisión documentada (*"making it one just to satisfy a test would change production code to fit the test"*), así que la comprobación es estructural y a mano.

Rejected: `runtime_checkable` + `isinstance` — cambia producción para satisfacer al test, contra la decisión ya tomada. Rejected: confiar en pyright — no está instalado (`sdd/project.md:57`) ni corre en CI.

### D13 — Una vía de entrada mínima: comando `pms_credentials`

**Chosen** (añadido al desglosar las tareas, 2026-08-05): un comando `backend/app/integrations/cli/pms_credentials.py` con dos subcomandos, `set` y `rotate`, y un `--show-provider` que lista qué proveedor tiene cada propiedad sin revelar credencial alguna.

Sin esto el change entrega una tabla que **nadie puede rellenar**: `properties/` no tiene `api/`, no hay endpoint de credenciales (y D4/R4.1 no quieren uno), y el único camino sería SQL a mano — que se salta el cifrado, el guard cross-tenant y la auditoría de golpe. Y además dejaría la mitad «rotación» de R4.2 sin forma de ejercitarse fuera de un test unitario, cuando rotar es precisamente la operación que ADR 0006 obligación 4 manda auditar.

Es el layer correcto y el precedente existe: `cli/` puede importar `infrastructure/` (`test_layering.py` no lo cubre), y `cli/pms_sync.py` ya es el patrón de un comando que marca sesión por tenant y no atraviesa el token. Hereda de él tres cosas que no son opcionales: la credencial **no se acepta como argumento** de línea de comandos —se lee de una variable de entorno nombrada, igual que `beds24_probe.py` hace con `BEDS24_REFRESH_TOKEN` (`specs/pms-beds24-spike.md`), porque un argumento queda en el historial del shell y en `ps`—, un argumento no reconocido se rechaza **sin imprimir su valor**, y la salida no imprime nunca el secreto, ni enmascarado (R4.1).

Rejected: un endpoint HTTP — crea justo la superficie de serialización que R4.1 existe para que no exista, y `properties/` no tiene `api/` por decisión previa. Rejected: sembrarlas en `make bootstrap` — mezcla datos de desarrollo con credenciales reales y no da rotación. Rejected: dejarlo para `pms-beds24-adapter` — ese change necesita meter una credencial el primer día, así que el hueco se pagaría allí con prisa.

## Changes by area

| Area | Files | Change |
|---|---|---|
| Puertos PMS | `backend/app/integrations/domain/ports.py` | `PMSMessagingPort` (vacío), `PMSAdapterFactory` (Protocol); retirar `unmappable_rows` de `PMSAdapter`; `list_reservations -> PmsFetchResult` |
| DTOs | `backend/app/integrations/domain/dtos.py` | `PmsRowFailure`, `PmsFetchResult` |
| Enums | `backend/app/integrations/domain/enums.py` *(nuevo)* | `PMSProvider`, `PmsCredentialScope` |
| Errores | `backend/app/integrations/domain/errors.py` | `PMSMessagingUnsupportedError`, `MissingPmsCredentialError` |
| Factory | `backend/app/integrations/infrastructure/pms_factory.py` *(nuevo)* | Implementación: proveedor → constructor de adapter; descifra credencial; sin estado ni sesión |
| Adapters | `mock_pms.py`, `channex/adapter.py` | Retirar `unmappable_rows`; devolver `PmsFetchResult` |
| Caso de uso | `backend/app/integrations/application/use_cases.py` | `SyncReservationsFromPmsUseCase` recibe `PMSAdapterFactory` en vez de `pms: PMSAdapter`; absorbe el pliegue de `failures` |
| CLI (sync) | `backend/app/integrations/cli/pms_sync.py` | `build_adapter` → factory; `--provider` como override ruidoso; nuevo fallo por credencial ausente |
| CLI (credenciales) | `backend/app/integrations/cli/pms_credentials.py` *(nuevo)* | `set` / `rotate` / `--show-provider`; secreto por variable de entorno, nunca por argumento ni en salida |
| Steering | `sdd/steering/security.md` | Entrada nueva y nombrada en la regla 9 acotando la auditoría de lectura automática (aprobada en D6) |
| Cifrado | `backend/app/core/crypto.py` *(nuevo)* | `EncryptedSecret`, `encrypt`, `decrypt` |
| Config | `backend/app/core/config.py` | `encryption_key` + validador de clave Fernet |
| Credenciales | `backend/app/integrations/{domain/entities.py,infrastructure/models.py,infrastructure/repositories.py}` | Entidad `PmsCredential`, `PmsCredentialModel`, `SqlAlchemyPmsCredentialRepository` con guard cross-tenant |
| Propiedad | `properties/{infrastructure/models.py,domain/entities.py,infrastructure/repositories.py,domain/repositories.py}` | Columna `pms_provider` en modelo, entidad y `_to_property`; `set_pms_provider` en puerto e implementación |
| Auditoría | `backend/app/audit/domain/{actions.py,value_objects.py}` | `ENTITY_PMS_CREDENTIAL`, acciones de lectura y rotación, clave en `AUDITABLE_FIELDS`, nombre de columna en `REDACTED_FIELDS` |
| Registro de modelos | `backend/app/core/models_registry.py` | Alta del modelo nuevo |
| Migración | `backend/alembic/versions/<rev>_pms_provider_resolution.py` *(nuevo)* | Tipos enum explícitos, tabla `pms_credentials`, columna `pms_provider`; `downgrade` completo con `DROP TYPE` |
| Fontanería de la clave | `.env.example`, `.env.deploy.example`, `docker-compose.yml`, `docker-compose.deploy.yml`, `Makefile` | `ENCRYPTION_KEY`: nombre sin valor, `:?` en los servicios que la necesitan, generador local base64url |
| Tests | `backend/tests/integrations/`, `backend/tests/properties/`, `backend/tests/audit/` | Conformidad de puertos, factory, aislamiento propio de credenciales, redacción, `PmsFetchResult` |

## Data & interfaces

**Tabla nueva `pms_credentials`** (tenant-scoped, `UUIDPrimaryKeyMixin` + `TenantScopedMixin` + `TimestampMixin`):

| Columna | Tipo | Notas |
|---|---|---|
| `id` | `Uuid` PK | Es el `entity_id` que `AuditLog` exige |
| `tenant_id` | `Uuid` FK `tenants.id` | Del mixin; entra en `tenant_scoped_classes()` |
| `provider` | enum `pms_provider` | |
| `scope` | enum `pms_credential_scope` | `PROPERTY` / `ACCOUNT` / `ORGANIZATION` |
| `property_id` | `Uuid` FK `properties.id`, nullable | No nulo **solo** con `scope=PROPERTY` |
| `secret_encrypted` | `Text` | Fernet desde esta migración; nunca en respuesta |
| `rotated_at` | `DateTime(tz)` nullable | Última rotación |

Unicidad: `(tenant_id, provider, scope, property_id)`. La columna cifrada **no es consultable** (Fernet lleva IV aleatorio, así que `WHERE secret_encrypted = ?` no puede funcionar); no hace falta, porque siempre se lee por la clave de arriba.

**`properties`**: columna nueva `pms_provider` (enum `pms_provider`, nullable — nulo significa «usa el defecto de bootstrap»).

**Env vars**: `ENCRYPTION_KEY` (base64url de 32 bytes). Nombre sin valor en `.env.example` y `.env.deploy.example`; `${ENCRYPTION_KEY:?...}` en `backend`/`worker`/`migrate` del compose local y en `backend`/`worker`/`migrate`/`beat` del de despliegue.

**API**: ninguna ruta nueva y ninguna modificada. `properties/` sigue sin `api/`. Es deliberado y es lo que mantiene R4.1 verificable hoy por ausencia de superficie.

**Vocabulario de auditoría**: `ENTITY_PMS_CREDENTIAL = "PMS_CREDENTIAL"`; acciones `PMS_CREDENTIAL_READ` y `PMS_CREDENTIAL_ROTATED` (nombres a fijar en tasks).

## Risks & mitigations

- **`ENCRYPTION_KEY` ausente rompe `alembic upgrade`, no solo la API.** `settings` se valida al importar y `alembic/env.py` lo importa. *Mitigación*: plumarla en el servicio `migrate` de los dos composes y en CI **en la misma tarea** que añade el campo, y un test que verifique que el validador rechaza una clave inválida. Fail-fast es lo deseado; lo indeseado es descubrirlo en CI.
- **Clave compartida con la PII de huésped.** Rotarla obliga a re-cifrar todo a la vez. *Mitigación*: hoy no hay dato cifrado real, así que el coste es cero **ahora** y crece con el tiempo; queda registrado que la salida es `MultiFernet` (ADR 0006) y que cuanto más tarde, más caro.
- **La suite y el arranque local dependen hoy de que `--provider` por defecto sea `mock`.** Cambiar el mecanismo puede romperlos en silencio. *Mitigación*: `test_pms_sync_provider_flag.py` ya fija el defecto; se amplía en lugar de reescribirse, y una propiedad sin `pms_provider` conserva el comportamiento actual.
- **`_to_property` mapea 24 campos a mano**: una columna nueva que se olvide ahí queda `None` en toda lectura, sin error. *Mitigación*: test que comprueba que un `Property` leído conserva `pms_provider`.
- **Migración con tipos enum a mano.** Sin `CREATE TABLE` que los cree para la columna de `Property`, y CI corre `alembic downgrade base`. *Mitigación*: crear y dropear los tipos explícitamente, y verificar el ciclo `upgrade`→`downgrade` en local antes de abrir PR.
- **Retirar `unmappable_rows` toca una obligación escrita en una spec viva.** `specs/reservations.md:113-117` lo exige por requisito. *Mitigación*: ya está listado en *Affected specs* del proposal; la spec se corrige al archivar, no antes.
- **Volumen de `audit_logs`** si Q2 se resuelve como «auditar cada lectura». *Mitigación*: es exactamente lo que Q2 pone a decisión, con el orden de magnitud calculado.

### Excepciones de forma aceptadas en la revisión a escala de feature (2026-08-06)

Dos desviaciones que el panel encontró, que **no se corrigen** y que quedan registradas aquí para
que la spec las herede al archivar en vez de que alguien las redescubra como defectos.

**1. `properties/infrastructure` e `integrations/infrastructure` se importan mutuamente.**
`properties/infrastructure/models.py` importa `pms_provider_enum` de `integrations`, y
`integrations/infrastructure/repositories.py` importa `PropertyModel` para comprobar que una
propiedad pertenece al tenant que escribe la credencial. Es **el primer par bidireccional del
repositorio**: los demás cruces entre dominios en esa capa (`auth→tenants`,
`reservations→guests`) van en un solo sentido, y `tests/test_layering.py` no lo detecta porque
comprueba la dirección **dentro** de un dominio, no entre dominios.

Se acepta, con el criterio del panel de arquitectura: la norma efectiva de este repositorio no es
«sin acoplamiento entre dominios en `infrastructure/`» —ya lo hay— sino **«sin viaje de ida y
vuelta»**, y este lo es. La alternativa era enrutar la comprobación de propietario por el puerto
`PropertyRepository`, que hoy no tiene ningún método con la forma «¿este id es de este tenant?»:
habría que inventarlo para que su único consumidor fuese una guarda de tres líneas. Más
superficie por menos claridad. Si algún día el par crece más allá de estas dos aristas, la
respuesta correcta deja de ser documentarlo.

**Y el viaje de ida y vuelta que sí se cerró**, para que no se confundan: el puerto
`PmsCredentialRepository` nació en `properties/domain/` y la factory lo importaba de vuelta desde
`integrations/`. Ese sí se eliminó moviéndolo a `integrations/domain/repositories.py`. Lo que
queda es el de la capa de infraestructura, que es distinto y menor.

**2. `show-providers` es un subcomando, no el flag `--show-provider` que dicen D13 y la tarea
8.2.** Funcionalmente equivalente. Se conserva la forma entregada: un subcomando se lee mejor que
un flag para algo que **lista** en vez de mutar, no comparte la forma posicional de `set`/`rotate`,
y los tests ya lo fijan así. La desviación se registra aquí porque el design decía otra cosa y un
lector futuro merece saber cuál de las dos es la vigente.

### Lo que hay que saber de la granularidad de auditoría, si se toca (2026-08-06)

Rescatado de `BLOCKED.md` antes de retirarlo, porque el fichero es de trabajo y esto no.

La granularidad de la auditoría de lectura se escribió **mal siete veces** a lo largo de este
change, en cinco artefactos, y cuatro revisiones consecutivas encontraron cada una un error
**distinto** en ella. El arreglo estructural fue hacer de la entrada nombrada de la regla 9 su
único hogar normativo; todo lo demás la cita.

**Los barridos para verificar que nadie la reformula fallaron cuatro veces, y siempre por lo
mismo: eran temáticos.** Buscar frases falló porque «One `PMS_CREDENTIAL_READ` row per» no contiene
la subcadena «one row per». Enumerar los símbolos del read log falló porque `tasks.md` no cita
ninguno. Leer los artefactos del change enteros falló porque `design.md:36` enunciaba la cifra **de
pasada, dentro de un argumento sobre otra cosa**. El mejor chequeo encontrado —barrido del campo
semántico, auditoría ∩ credencial ∩ cuantificador, sobre todo fichero versionado— es estrictamente
más fuerte que los tres, y **tampoco está cerrado**: es una conjunción, y la afirmación se puede
hacer con un solo término (así sobrevivió un titular que decía «la fila de auditoría por
ejecución»).

**El tripwire preciso, que es lo más útil de todo esto**: distinguir **captura** de **emisión**.
`pms_factory.py` registra en el `CredentialReadLog` incondicionalmente, así que «cada lectura se
audita» es literalmente cierto y esas frases son seguras. Lo que no lo es: decir que cada lectura
**deja** o **escribe** una fila. Captura por lectura, emisión por credencial distinta; son etapas
distintas y por eso no se contradicen. Una frase cruza a ser cardinalidad —y falsa— exactamente en
ese verbo.

**Nota de contrato, no bloqueante**: un `read_log` obligatorio garantiza **recolección**, no
**persistencia**. Las filas llegan a `audit_logs` porque `SyncReservationsFromPmsUseCase` empareja
el log con un `audit` obligatorio y lo vuelca en el `finally`. Un futuro llamante iniciado por
persona o API debe emparejar los dos igual; hoy no existe tal llamante. Merece una frase en
`specs/` al archivar — y correr entonces el barrido semántico, porque `sdd/specs/` es el próximo
sitio donde esta afirmación intentará vivir.

### Frontera medida en el panel de las secciones 2-3, para que se herede a sabiendas

- **Un identificador escalar con forma de PAN sí llega a `external_id`.** `unique_id: "4111111111111111"` sobrevive al saneado: son 16 caracteres imprimibles y escalares, y R6.4 autoriza «el identificador». Distinguirlo de un id legítimo exigiría una comprobación de **contenido** (Luhn más longitud 13-19), que introduciría falsos positivos para cualquier proveedor futuro con ids puramente numéricos. Se acepta porque nada medido pone datos de tarjeta en `unique_id` — a diferencia de `guarantee`, que `specs/pms-channex-staging.md` midió en **toda** reserva de OTA. **Debe quedar escrito en la spec al archivar**, para que `reservations-webhooks` herede la frontera en vez de redescubrirla.
- **Candidato a change propio, fuera de alcance aquí**: un número JSON de más de 4300 dígitos hace que `json.loads` lance `ValueError` dentro de `ChannexClient.get_collection` — **fuera** del guard por elemento—, y `cli/pms_sync.py` solo captura `UnknownTenantError` y `PmsUnavailableError`, así que un solo número hostil aborta la página entera con un traceback crudo. `channex/client.py` no se toca en este change. Detectado al sondear el saneado del identificador; el mismo límite es lo que hace inalcanzable un desbordamiento de `str(int)` dentro de `_element_reference`.

## Requirement coverage

R1 → D1, D2, D12. R2 → D1, D2, D4, D7, D9. R3 → D3, **D4**, D5, D11. R4 → D3, D4, D6, D7, D13. R5 → D8 (sin contrato nuevo: cumple el de `celery-jobs`). R6 → D10.

**D4 se añadió a la cobertura de R3 tras el panel de la sección 1** (hallazgo de QA): R3.2 exige cubrir las **tres granularidades** —propiedad, cuenta y organización— y quien las materializa es la columna `scope` de D4, no D3 ni D11. Sin esa arista, R3.2 no tenía ninguna decisión asignada y ninguna tarea la nombraba, así que era el requisito con más probabilidad de darse por cumplido sin que nadie lo comprobara.

## Resolved questions

Las cuatro se resolvieron con Jose el 2026-08-05, antes de `/sdd:tasks`. Quedan registradas porque tres de ellas cierran decisiones que documentos de más arriba dejaron abiertas.

**Q1 — ¿Tabla `pms_credentials` con `scope`, o columnas en `Property`?** → **Tabla**, como propone D4. La desviación del texto literal de ADR 0006 decisión 7 (*"`Property` guarda su proveedor y sus credenciales"*) se registra **aquí y en la spec al archivar**, y no se anota en el ADR: se descartó explícitamente tocarlo. Conviene por tanto que la spec sea clara, porque el ADR va a seguir afirmando algo que el esquema no hace.

**Q2 — Granularidad de la auditoría de lectura.** → Acotada, con la excepción nombrada añadida a la **regla 9 de `steering/security.md`**, que es donde vive su enunciado exacto. Esta respuesta **no lo reformula**: su primera versión sí lo hacía y quedó obsoleta en cuanto la regla se corrigió, arrastrando la unidad equivocada y una granularidad invertida. Lo que aporta esta entrada es la **aprobación** que la propia regla exige, dada por Jose el 2026-08-05.

**Q3 — Forma de la factory.** → **`messaging_for` lanza `PMSMessagingUnsupportedError` más un `supports_messaging` puro**, como propone D2. Cierra con esto la pregunta que ADR 0006 decisión 7 deja abierta con nombre propio, y la razón que decide es medible: no corre ningún type checker que verificase un `| None`.

**Q4 — ¿Se cifran ahora las dos columnas que ya están en claro?** → **No.** `wifi_password_encrypted` y `document_number_encrypted` se quedan como están; este change construye la primitiva y no las toca. Queda registrado que el argumento a favor de hacerlo pronto **caduca**: hoy no hay dato de producción que migrar y el repo no tiene precedente de migración con `UPDATE` sobre filas existentes, así que el coste solo puede subir. Merece entrada propia de roadmap.
