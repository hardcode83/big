# Proposal: revenue-statements

## Why

El producto lleva todo el ciclo operativo — reservas, limpieza, mantenimiento, mensajería
— y termina hoy sin la última pieza que PRD §30 enumera: la liquidación al propietario.
Las dos tablas existen desde `domain-foundation-financial` (archivado 2026-07-31) y un
único lector (`PropertyFinancialSummary` que `dashboard-api` ya consume) las ha rozado,
pero `OwnerStatement` y `Expense` siguen siendo entidades sin escritor: no hay forma de
generar, modificar ni exportar una liquidación, ni se puede decidir el coste real del mes
de una vivienda sin abrir SQL. Cierra el peldaño 8 de §30 (statements) y deja dos de tres
changes de `revenue` entregados; los dos cambios existentes (`demo-user` y los agregados
de dashboard) ya presuponen que estos números se producen en algún sitio.

## What changes

Nace `app/statements/{application,api}/` con los casos de uso que faltan, el puerto y
adaptador de lectura/escritura para las dos tablas y un router FastAPI montado en
`/api/v1/owner-statements` y `/api/v1/expenses`, más dos exportadores (CSV de gastos y
PDF del statement, este último como stream directo en la respuesta — sin StorageAdapter).
`app/auth/domain/policy.py` añade un par de permisos (`READ_OWNER_STATEMENTS`,
`MANAGE_OWNER_STATEMENTS`); `app/audit/domain/actions.py` registra dos entidades nuevas
(`OWNER_STATEMENT`, `EXPENSE`) y las acciones correspondientes; `app/scheduler/{tasks,schedule}.py`
registra la tarea mensual. Las entidades y enums de `app/statements/domain/` no cambian:
siguen siendo los dataclass planos que `domain-foundation-financial` dejó, y la lógica
de transiciones y agregado entra en `domain/` al lado de ellos. La pantalla `/statements`
queda como `RoutePlaceholder` — la FE entra con su propio change (precedente: `revenue-pricing`
→ `pricing-web`).

## Requirements

### R1 — Generación automática mensual

**As an** operador del sistema, **I want** un job mensual que emita una liquidación por
vivienda y por tenant cuando el mes anterior se cierra, **so that** cada propietaria tenga
su número listo para revisar antes de que llegue el primer correo del nuevo mes, sin
esperar a que alguien lance SQL.

Acceptance criteria:

1. WHEN el reloj llega al **primer día de cada mes a las 02:00 UTC**, THE SYSTEM SHALL
   generar un `OwnerStatement` en estado `DRAFT` para cada `(tenant, property)` cuyo
   período cerrado sea el mes natural anterior, iterando los tenants activos y sus
   propiedades `ACTIVE`.
2. THE SYSTEM SHALL ejecutar la generación bajo el mismo mecanismo de lock que
   `generate_price_recommendations` (`specs/celery-jobs.md`, TTL declarado
   explícitamente — valor exacto a fijar en `/sdd:design`); perder el lock es `skipped`,
   no un fallo, y dos instancias del job no deben producir dos filas para el mismo
   `(tenant, property, period_start, period_end)`.
3. IF ya existe un `OwnerStatement` para la clave UNIQUE
   `(tenant_id, property_id, period_start, period_end)`, THEN THE SYSTEM SHALL
   preservarlo intacto: el barrido **no** sobrescribe liquidaciones producidas
   manualmente, sólo rellena huecos. La idempotencia llega del `UNIQUE` de §7.22
   y de la lectura previa del repositorio, no de un `INSERT … ON CONFLICT` que
   pisaría el contenido.
4. THE SYSTEM SHALL abrir una transacción por `(tenant, property)` y no una por tenant, de
   modo que una vivienda que falle no descarte las liquidaciones ya escritas de las
   anteriores.
5. IF una `(tenant, property)` falla, THEN THE SYSTEM SHALL abandonar su unidad, contarla
   en el informe del job, registrarla con su identificador y **seguir** con la siguiente.
6. THE SYSTEM SHALL **no** invocar `PMSAdapter` en este flujo: las cifras del período se
   leen de `reservations` y de `expenses` ya persistidos, del mismo modo que `revenue-pricing`
   consume sus reservas locales para calcular la ocupación.

### R2 — Generación manual bajo demanda

**As a** `PROPERTY_MANAGER`, **I want** lanzar la generación de una liquidación concreta
desde la API, **so that** pueda cerrar el mes antes de tiempo (un propietario que se va
de viaje, una auditoría a mitad de mes) sin esperar al reloj.

Acceptance criteria:

1. WHEN el manager invoca `POST /api/v1/owner-statements/generate` con un cuerpo
   `{property_id?, period_start, period_end}`, THE SYSTEM SHALL generar la liquidación
   síncronamente y devolverla con el mismo sobre que `GET /{id}`.
2. WHERE el cuerpo nombra un `property_id`, THE SYSTEM SHALL limitarse a esa vivienda
   del tenant de la sesión; WHERE se omite, THE SYSTEM SHALL recorrer todas las
   propiedades `ACTIVE` del tenant.
3. THE SYSTEM SHALL ser **idempotente** sobre la clave UNIQUE
   `(tenant_id, property_id, period_start, period_end)`: una segunda llamada
   sobre el mismo período y vivienda responde con el statement existente y un
   mensaje que lo distingue de la creación; `status` no muta.
4. IF `property_id` nombra una vivienda de otro tenant, inactiva, o inexistente, THEN
   THE SYSTEM SHALL responder `422` con cuerpo constante por cada causa (análoga a
   `revenue-pricing` R2.5), y `404` queda reservado al recurso ausente por id.
5. THE SYSTEM SHALL exigir `period_start <= period_end` y duración máxima de **un mes
   natural** cerrado (mismo mes-calendario) — un rango que cruza dos meses se rechaza
   con `422` nombrando el campo, para que la liquidación siga siendo mensual aunque
   la generación sea manual.
6. THE SYSTEM SHALL devolver los contadores del barrido (`created`, `skipped`,
   `failed`) en la respuesta, igual que `POST /price-recommendations/generate`.

### R3 — Lectura y filtrado

**As a** `TENANT_OWNER` o `PROPERTY_MANAGER`, **I want** consultar las liquidaciones
del tenant con filtros útiles, **so that** cada rol encuentre la suya sin abrir SQL.

Acceptance criteria:

1. WHEN un usuario con permiso emite `GET /api/v1/owner-statements` con los filtros
   `property_id`, `period_start_from`, `period_start_to` y `status` (combinados con `AND`),
   THE SYSTEM SHALL devolver únicamente las del tenant de la sesión, paginadas con
   tamaño fijo de **20** por página.
2. THE SYSTEM SHALL leer y devolver el sobre `{items, total, page, per_page}` —
   `items`, **no** `data` — para no romper la convención que `pricing-web` R3.4 fija y
   que `/sdd:auto` espera; `total_pages` lo calcula el cliente (no se publica).
3. WHEN un usuario emite `GET /api/v1/owner-statements/{statement_id}`, THE SYSTEM
   SHALL devolver el detalle, su lista de `Expense` asociadas y el desglose por
   reserva (`gross_amount`, `ota_commission`, `net_amount`) del período.
4. IF el `statement_id` no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL
   responder `404` con cuerpo constante para los dos casos, sin revelar la existencia.
5. WHERE una liquidación está en estado `DRAFT`, THE SYSTEM SHALL incluir el desglose
   por reserva. La inclusión y consolidación de los `Expense` asociados sigue la OQ
   obligatoria de `/sdd:design` sobre consolidación de `Expense` y snapshot del
   `OwnerStatement` (sección Open questions for /sdd:design, nº 4).

### R4 — Mutación del statement

**As a** `PROPERTY_MANAGER`, **I want** anotar y transicionar el estado de una
liquidación, **so that** el flujo manual (revisar → marcar como lista → marcar como
enviada) sea trazable y no manipule los importes.

Acceptance criteria:

1. WHEN el manager emite `PATCH /api/v1/owner-statements/{statement_id}` con un cuerpo
   `{notes?}`, THE SYSTEM SHALL actualizar `notes` y devolver el detalle. Ninguna otra
   columna del statement es escribible desde la API: importes y períodos son producto
   de la generación, y moverlos a mano sería saltarse el contrato del módulo.
2. WHEN el manager emite `PATCH /api/v1/owner-statements/{statement_id}` con un cuerpo
   `{status: "READY"}` (o `"SENT"`), THE SYSTEM SHALL transicionar **una sola vez** y
   validar el movimiento legal desde el estado actual — `DRAFT → READY → SENT`, sin
   saltos — antes de mutar, devolviendo `409` si el origen no encaja.
3. THE SYSTEM SHALL alojar la máquina de estados en la entidad
   `OwnerStatement` (`ALLOWED_TRANSITIONS`) y no en el caso de uso, por la misma razón
   que `PriceRecommendation` la aloja allí: la regla de negocio no se dispersa.
4. THE SYSTEM SHALL rechazar, con `409`, transicionar una liquidación ya en `SENT`: la
   marca de enviada es el **estado terminal e inmutable** del ciclo, sin movimientos
   legales hacia atrás ni hacia adelante.
5. THE SYSTEM SHALL tratar `notes` como sumidero de texto libre de regla 11 de
   `steering/security.md`: el campo existe en el esquema con `String` libre, pero su
   valor **no** se audita literalmente en `audit_logs.changes` (sólo `{"changed":
   true}`), y la entrada del censo se ampliará al archivar para declararlo.
6. WHEN una mutación se rechaza por validación, THEN THE SYSTEM SHALL restaurar el
   `updated_at` desde una instantánea previa, de modo que un rechazo no deje marca
   temporal fantasma en el statement.

### R5 — Expenses CRUD

**As a** `PROPERTY_MANAGER`, **I want** registrar gastos manuales por vivienda y
período, **so that** la liquidación refleje los costes reales (amenities, lavandería,
plataforma, otros) que no se deducen automáticamente de otras features.

Acceptance criteria:

1. WHEN el manager emite `POST /api/v1/expenses` con `{property_id, category,
   description, amount, currency?, date, receipt_storage_key?, incident_id?}`,
   THE SYSTEM SHALL persistirla en el tenant de la sesión y devolver `201` con el
   recurso.
2. THE SYSTEM SHALL limitar `category` a uno de los siete valores de `ExpenseCategory`
   (`CLEANING`, `LAUNDRY`, `AMENITIES`, `MAINTENANCE`, `SPECIALIST`, `PLATFORM_FEE`,
   `OTHER`); `currency`, cuando se omita, defaultea a `EUR`; `amount` se rechaza si
   excede `10**8` (el `NUMERIC(10,2)`); `description` queda acotado a 500 caracteres
   por la columna y `date` a una fecha válida no futura.
3. WHEN un manager emite `PATCH /api/v1/expenses/{expense_id}` con un subconjunto de
   los campos anteriores, THE SYSTEM SHALL validar el recurso **completo** y rechazar
   con `422` nombrando los campos que fallan; el `statement_id` **no** es escribible
   desde la API — se asigna por la generación del statement y sigue la OQ obligatoria
   sobre consolidación de `/sdd:design` (sección Open questions for /sdd:design, nº 4).
4. WHEN el manager emite `DELETE /api/v1/expenses/{expense_id}`, THE SYSTEM SHALL
   borrarla **sólo si `statement_id` es NULL**: un gasto ya consolidado forma parte
   del statement visible al propietario, y borrarlo en silencio falsearía la
   liquidación. Devuelve `409` con cuerpo nombrado si está consolidado.
5. IF el `expense_id` pertenece a otro tenant, THEN THE SYSTEM SHALL responder `404`
   con cuerpo constante por caso (análogo a R3.4).
6. THE SYSTEM SHALL rechazar gastos con texto vacío en `description` o con caracteres
   de control (`U+0000`), coherente con el contrato de sumideros de texto libre de
   regla 11.
7. WHEN el manager emite `POST /api/v1/expenses` o `PATCH` con
   `amount > TenantConfig.owner_approval_threshold_eur`, THE SYSTEM SHALL **no**
   crear ni mutar el `Expense` directamente: el umbral contractual del tenant
   exige aprobación del propietario, y este endpoint no puede ser un bypass de
   esa regla. La forma concreta del cumplimiento la cierra `/sdd:design` como
   OQ obligatoria, **utilizando el modelo canónico existente** (entidades,
   enums y esquema declarados inalterados en este proposal). Si la integración
   no puede satisfacerse sin introducir un nuevo estado, una nueva entidad,
   una nueva enum o una migración de esquema, `/sdd:design` debe **identificar
   el gap explícitamente** antes de pasar a `/sdd:tasks`; en tal caso, las
   extensiones quedan fuera del alcance de este change.

### R6 — Export CSV y PDF

**As a** `TENANT_OWNER` o `PROPERTY_MANAGER`, **I want** descargar la liquidación en
CSV (gastos) y PDF (statement completo), **so that** pueda enviarla por correo sin
manipular la API cada vez y archivar una copia local.

Acceptance criteria:

1. WHEN un usuario con `READ_OWNER_STATEMENTS` emite
   `GET /api/v1/owner-statements/{statement_id}/export.csv`, THE SYSTEM SHALL responder
   `200` con `Content-Type: text/csv; charset=utf-8` y `Content-Disposition:
   attachment; filename="owner-statement-<period>.csv"`, y el cuerpo es una fila de
   cabecera + una fila por `Expense` del statement con sus seis columnas planas
   (`date`, `category`, `description`, `amount`, `currency`, `receipt_storage_key`).
2. THE SYSTEM SHALL **no** traducir el CSV ni añadir BOM: el destino es una hoja de
   cálculo, y los acentos vienen en UTF-8 directo.
3. WHEN el usuario emite
   `GET /api/v1/owner-statements/{statement_id}/export.pdf`, THE SYSTEM SHALL responder
   `200` con `Content-Type: application/pdf` y el `Content-Disposition` equivalente,
   y el cuerpo es el PDF **generado en el momento** y devuelto como stream directo.
   El PDF **no** se persiste en `StorageAdapter` ni crea una segunda ruta de
   descarga — esto se elige en el gate de `/sdd:new` y queda cerrado aquí.
4. THE SYSTEM SHALL componer el PDF con: cabecera de tenant (`name`, `country`),
   bloque por vivienda (`name`, `internal_code`, `address`), bloque del período
   (`period_start`–`period_end`, `status`), tabla de cada línea de ingreso
   (reserva → `gross_amount`/`ota_commission`/`net_amount`), tabla de gastos por
   `ExpenseCategory` con subtotal, fila de totales (`net_owner_result`) y caja de
   `notes`. Sin logo, sin marca propia — el PRD §20 no la declara.
5. THE SYSTEM SHALL dibujar todo importe con dos decimales y separador decimal `,`
   (locale `es-ES`), sin símbolo de moneda por columna: el `OwnerStatement` canónico
   de PRD §7.22 no expone `currency`, y el `currency` por fila del CSV es de la
   `Expense` (R5), donde la columna sí existe (ver Open questions for /sdd:design
   para la estrategia de multi-moneda).
6. IF el statement no existe o pertenece a otro tenant, ambas rutas de export
   responden `404` con el mismo cuerpo constante que R3.4.
7. THE SYSTEM SHALL **no** registrar `AuditLog` por la descarga: un export es una
   lectura, no una mutación, y el log no se ensucia con cada GET — la auditoría del
   statement vive en sus transiciones (R4) y en las mutaciones de sus gastos (R5).

### R7 — Permisos, aislamiento, auditoría, i18n

**As** cualquier rol del sistema, **I want** que la liquidación esté gobernada por los
mismos controles que el resto del backend, **so that** un `TECHNICIAN` no vea cifras
financieras, un propietario de otro tenant no vea mi mes, y un cambio quede
documentado en el idioma del operador.

Acceptance criteria:

1. THE SYSTEM SHALL proteger las rutas anteriores con dos permisos nuevos:
   `READ_OWNER_STATEMENTS` y `MANAGE_OWNER_STATEMENTS`, concedidos a `TENANT_OWNER` y
   `PROPERTY_MANAGER` para `READ`, y sólo a `PROPERTY_MANAGER` para `MANAGE` (mismo
   dibujo que `READ_ACCESS_RECORDS`/`MANAGE_ACCESS_RECORDS`); `CLEANER`, `TECHNICIAN`
   y `SUPER_ADMIN` no obtienen ninguno.
2. THE SYSTEM SHALL resolver el tenant desde la sesión autenticada en cada endpoint
   (nunca desde el cuerpo o la query), y SHALL comprobar en el repositorio que la
   entidad pertenece al tenant que actúa antes de cualquier lectura o mutación —
   mismo patrón que `revenue-pricing` R6.
3. THE SYSTEM SHALL registrar `AuditLog` con dos entidades nuevas
   (`OWNER_STATEMENT`, `EXPENSE`) y, como mínimo, las acciones
   `OWNER_STATEMENT_GENERATED` (con `property_id`, `period_start`, `period_end` y los
   contadores en `metadata` cuando el actor es persona, vía R2),
   `OWNER_STATEMENT_STATUS_CHANGED` (con diff de `status`),
   `OWNER_STATEMENT_NOTES_UPDATED` (con `{"changed": true}` por R4.5),
   `EXPENSE_CREATED`, `EXPENSE_UPDATED` y `EXPENSE_DELETED`. Las demás acciones de
   la enumeración se mantienen **estrictamente** a lo que un caso de uso ejerce — sin
   acción para una operación que nadie ejecuta.
4. THE SYSTEM SHALL declarar `AUDITABLE_FIELDS["OWNER_STATEMENT"] = {"status", "notes"}`
   y `AUDITABLE_FIELDS["EXPENSE"] = {"category", "amount", "currency", "date",
   "statement_id", "incident_id", "approved_by", "receipt_storage_key"}`,
   excluyendo **`description`** (sumidero regla 11 — su valor va al `audit_logs` sólo
   como `{"changed": true}`) y excluyendo las once columnas monetarias de
   `OwnerStatement` (no son escribibles por API: su única fuente es la generación).
5. THE SYSTEM SHALL auditar la generación mensual a través de la **misma acción** que
   la manual (`OWNER_STATEMENT_GENERATED`); la decisión concreta — auditar siempre,
   exceptuar por actor de sistema, o alguna forma intermedia — la cierra
   `/sdd:design` como OQ obligatoria. PRD §7.25 admite `actor_user_id` nullable para
   actores de sistema (precedente: `INCIDENT_CLASSIFIED`), así que la decisión es de
   criterio, no de imposibilidad del esquema — el design debe nombrar la regla o la
   excepción que la sustituye.
6. THE SYSTEM SHALL registrar el job mensual en `app/scheduler/{tasks,schedule}.py`,
   con TTL de lock **declarado explícitamente** (mismo patrón que
   `generate_price_recommendations`); el informe del job devuelve `created`,
   `skipped`, `failed` por tenant, como en R2.6.
7. THE SYSTEM SHALL traducir todos los mensajes de error al locale de la sesión en
   ES y EN, con la misma forma `{items, total, page, per_page}` en `GET`-lista y las
   mismas claves de error que `revenue-pricing` ya canónica, de modo que el frontend
   pueda reutilizar las tablas de mapeo por `status HTTP`.

## Open questions for /sdd:design

Estas cuatro decisiones quedan abiertas y `/sdd:design` debe cerrarlas antes de pasar
a tareas. Ninguna se ha tomado implícitamente en el proposal; todas tienen la
misma forma: "el requisito es invariante, el design decide cómo".

1. **Multi-moneda del statement**. PRD §7.22 no tiene columna `currency` en
   `OwnerStatement` y su `UNIQUE(tenant_id, property_id, period_start, period_end)`
   no incluye moneda. La estrategia concreta cuando una vivienda tiene `Expense` en
   monedas distintas dentro del mismo período (rechazar el statement, fijar una
   moneda única por tenant, desglosar, o equivalente) la cierra `/sdd:design` —
   y la decisión **no debe alterar el modelo canónico** del PRD.
2. **`Expense` y umbral de aprobación del tenant**
   (`TenantConfig.owner_approval_threshold_eur`, PRD §7.2). R5.7 prohíbe el bypass
   del flujo de `OwnerApproval` mediante `POST /api/v1/expenses`. El design
   debe decidir la forma concreta del cumplimiento **utilizando el modelo
   canónico existente** (entidades, enums y esquema declarados inalterados en
   este proposal). Si la integración no puede satisfacerse sin introducir un
   nuevo estado, una nueva entidad, una nueva enum o una migración de esquema,
   el design debe **identificar el gap explícitamente** antes de pasar a
   `/sdd:tasks`; en tal caso, las extensiones quedan fuera del alcance de este
   change.
3. **Auditoría del job mensual**. R7.5 deja la decisión a design: auditar siempre
   con `actor_user_id = NULL`, exceptuar al actor de sistema por nombre, o alguna
   forma intermedia. PRD §7.25 admite `actor_user_id` nullable para actores de
   sistema (precedente: `INCIDENT_CLASSIFIED`), así que la decisión es de
   criterio — el design debe nombrar la regla o la excepción que la sustituye,
   del mismo modo que `revenue-pricing` nombró la suya en `steering/security.md`.
4. **Consolidación de `Expense` y snapshot del `OwnerStatement`**. R1, R3 y R5
   tocan la asociación entre `Expense.statement_id` y el statement, pero el
   proposal no fija el momento exacto en que esa asociación se escribe ni
   cuándo los importes del statement se "congelan". El design debe cerrar las
   cuatro caras de la pregunta antes de pasar a `/sdd:tasks`:
   1. **Momento exacto**: cuándo se rellena `Expense.statement_id` y, por
      simetría, cuándo se rellenan las once columnas monetarias del
      `OwnerStatement` — al cierre del job mensual, en el instante de la
      generación manual, o en algún evento intermedio. La idempotencia de R1.3
      exige que ese momento sea **único**: regenerar sobre la misma clave
      UNIQUE no existe (R2.3), así que la única escritura es la primera.
   2. **Mutabilidad antes y después**: si un `Expense` puede seguir creándose,
      editarse o borrarse una vez asociado al statement, y bajo qué
      condiciones. R5.4 ya cierra el borrado (`statement_id IS NULL`); la
      edición y la creación tardía requieren la misma respuesta.
   3. **`Expense` con `date` dentro de un período ya cerrado**: ¿se permiten,
      se rechazan, o se asocian retroactivamente al statement existente? V1
      no soporta regenerar, así que la asociación retroactiva sería el único
      camino para que aparezcan en la liquidación — y debe decidirse aquí.
   4. **Coherencia con V1**: el no-regenerar de R1.3 y R2.3 obliga a que la
      consolidación sea **una operación irreversible y determinista** — sin
      reescritura del statement, sin reasociación masiva, y sin estados
      intermedios que R5/R4 no enumeren.

   Si la respuesta requiere un nuevo estado, una nueva entidad, una nueva
   enum o una migración de esquema, el design debe **identificar el gap
   explícitamente** y las extensiones quedan fuera del alcance de este
   change.

## Out of scope

- **Pantalla `/statements`**: el FE es un change propio (precedente:
  `revenue-pricing` → `pricing-web`). Aquí la ruta queda como `RoutePlaceholder`.
  Owner/manager consumen la API o el PDF por correo hasta que entre el FE.
- **Envío real al propietario** (email, WhatsApp, link): `status = SENT` significa
  "marcado como enviado por el operador", no "entregado por el sistema". La
  notificación llega con un change que reutilice `NotificationAdapter`.
- **Facturación fiscal**: explícitamente fuera del MVP y fuera de la entrada del
  roadmap (`"Sin facturación fiscal"`).
- **Derivación automática de costes desde `CleaningTask`/`Incident`**: la versión 1
  cuenta sólo los `Expense` explícitos. El cálculo cruzado con `cleaning` y
  `maintenance` se hará en un change posterior (candidata natural:
  `dashboard-operational-kpis` o la entrada de Métricas de revenue).
- **Versionado / histórico del statement**: V1 conserva intacto el existente si la
  clave UNIQUE ya tiene fila (R1.3, R2.3). No existe tabla de snapshots ni
  `effective_at`; regenerar con el mismo `(property_id, period_start, period_end)`
  no es una operación soportada — si la liquidación existe, sólo se modifica vía
  `notes` o transiciones de estado (R4). El versionado en sí queda como decisión
  de `/sdd:design` si surge un caso de uso real.
- **Multi-moneda**: la estrategia concreta (cómo consolidar una vivienda con
  `Expense` en monedas distintas en el mismo período, o cómo rechazar el caso) la
  cierra `/sdd:design` como OQ obligatoria arriba. `OwnerStatement` del PRD no
  tiene `currency` y su `UNIQUE` no incluye moneda, así que el modelo canónico no
  se modifica.
- **Cifrado en reposo de `notes` / `description`**: lo decide el change
  `plaintext-sink-encryption-at-rest` del roadmap (M, TECH) cuando aterrice.
- **Receipt uploader / OCR**: `receipt_storage_key` ya existe; subir y validar
  recibos llega aparte.
- **`RESPOND_OWNER_APPROVALS` aplicado a `Expense` manuales**: la integración
  concreta entre `Expense` y el flujo de `OwnerApproval` para gastos sobre el
  umbral es la OQ obligatoria nº 2 de arriba; este change no declara que `Expense`
  evite esa ruta — R5.7 lo prohíbe.

## Affected specs

- **Crear** `sdd/specs/revenue-statements.md` (no existe aún — se creará al archivar).
  Cubre las siete R, los exportadores, el job, los enums del vocabulario de auditoría
  y la tabla de errores por status HTTP.
- **Modificar** `sdd/specs/api-contract.md` para añadir los paths
  `/api/v1/owner-statements`, `/api/v1/owner-statements/{id}/export.{csv,pdf}` y
  `/api/v1/expenses` a la lista publicada en `backend/openapi.json` (el contrato
  nuevo se regenera al archivar — `make openapi`).
- **Modificar** `sdd/steering/security.md` para nombrar la nueva excepción de regla 9
  (job mensual sin actor — análoga a la de `revenue-pricing`) y ampliar la entrada
  del censo en regla 11 con `OWNER_STATEMENT.notes` y `EXPENSE.description`. La
  redacción final la cierra `/sdd:design`.
- **Sin tocar** `sdd/specs/domain-foundation-financial.md`: la entidad se queda en
  su spec de origen, igual que `pricing` quedó allí tras `revenue-pricing`. La
  aplicación nueva se documenta en su propio spec.
- **Cross-feature, no es dependencia**: `dashboard-api` ya consume
  `PropertyFinancialSummary` (pendientes = `statement_id IS NULL`). Cuando la
  generación empiece a consolidar, esa vista pasará a mostrar `SENT`. El contrato
  del lector no cambia; el comportamiento cambia por construcción. Sin esto, el
  panel financiero del detalle de propiedad empezaría a mentir — `/sdd:design` lo
  nombra y `dashboard-api` lo verifica después.
