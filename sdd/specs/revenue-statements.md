# Liquidación al propietario (`revenue-statements`)

## Purpose

Esta capacidad cierra el peldaño 8 de PRD §30: da a `OwnerStatement` y `Expense` —dos
tablas que existían desde `domain-foundation-financial` sin ningún escritor— sus casos de
uso, su router y sus dos exportadores. Cada mes genera, por vivienda y por tenant, una
liquidación con los once importes de PRD §7.22 a partir de las `reservations` y los
`expenses` ya persistidos; el manager la anota, la transiciona (`DRAFT → READY → SENT`) y
la descarga en CSV (gastos) o PDF (statement completo). Los gastos que superan el umbral
de aprobación del tenant se enrutan por el `OwnerApproval` canónico de `maintenance` en
vez de crear un flujo propio.

No hay ninguna llamada al `PMSAdapter` en todo el módulo: las cifras del período se leen
de tablas locales, igual que `revenue-pricing`. La pantalla `/statements` queda como
`RoutePlaceholder` — el frontend es un change propio (precedente: `revenue-pricing` →
`pricing-web`); hasta entonces owner y manager consumen la API o el PDF por correo.

## Requirements

### Dominio: máquina de estados de `OwnerStatement`

- THE SYSTEM SHALL alojar la tabla de transiciones legales en la propia entidad
  (`OwnerStatement._TRANSITIONS: ClassVar`), **keyed by operación** y no por
  origen→destinos: `mark_ready` es únicamente `DRAFT → READY`, `mark_sent` es
  únicamente `READY → SENT`, y ninguna operación salta `DRAFT → SENT`.
- WHEN se invoca `mark_ready(now=...)` sobre un statement en `DRAFT`, THE SYSTEM SHALL
  transicionarlo a `READY` y actualizar `updated_at`; WHEN se invoca desde cualquier otro
  estado (incluido `READY` sobre sí mismo), THE SYSTEM SHALL rechazar con
  `OwnerStatementInvalidTransitionError`.
- WHEN se invoca `mark_sent(now=...)` sobre un statement en `READY`, THE SYSTEM SHALL
  transicionarlo a `SENT`; WHEN se invoca desde cualquier otro origen, THE SYSTEM SHALL
  rechazar. `SENT` no aparece como origen de ninguna operación, así que es terminal por
  construcción y no por una guarda adicional.
- WHEN se invoca `update_notes(notes, now=...)`, THE SYSTEM SHALL rechazar con
  `OwnerStatementValidationError` si `notes` no es `str`, si contiene `U+0000`, o si
  queda vacío tras `strip()`; en cualquier otro caso SHALL reemplazar `notes` y
  actualizar `updated_at`.
- `Expense` sigue siendo un dataclass plano (sin invariantes propias): R5.1-R5.6 son
  reglas de validación de entrada y de borrado, y viven en `CreateExpenseUseCase` y
  `DeleteExpenseUseCase`, no en la entidad.

### Puertos y adaptadores

- THE SYSTEM SHALL exponer dos `Protocol` nuevos en
  `app/statements/domain/repositories.py` — `OwnerStatementRepository`
  (`get`, `find_by_unique_key`, `list_paginated`, `add`, `save`) y `ExpenseRepository`
  (`get`, `list_paginated`, `add`, `save`, `delete`, `find_closed_period`,
  `list_for_period`, `list_pending_for_property`, `bulk_associate_to_statement`,
  `find_pending_owner_approval_for`) — implementados por `SqlAlchemyOwnerStatementRepository`
  y `SqlAlchemyExpenseRepository`. El `ExpenseReader` de `dashboard-api` queda intacto:
  ningún método nuevo lo toca.
- `get` y `find_by_unique_key` SHALL devolver `None` tanto si el id no existe como si
  pertenece a otro tenant, para que la capa de API responda el mismo `404` en los dos
  casos (R3.4, R5.5).
- `find_pending_owner_approval_for(tenant_id, expense_id)` SHALL escopar por `tenant_id`
  explícitamente en el SQL (`oa.tenant_id = :tenant_id`), no sólo por el `related_id` —
  regla 1 de `steering/security.md` sobre toda query cross-módulo.
- `bulk_associate_to_statement(tenant_id, ids, statement_id)` SHALL ejecutar
  `UPDATE expenses SET statement_id = :new WHERE id = ANY(:ids) AND tenant_id = :t AND
  statement_id IS NULL`, idempotente: una segunda llamada sobre las mismas filas
  devuelve `0` filas tocadas.
- `save` de `Expense` en el adaptador SQLAlchemy SHALL rechazar con
  `ExpenseAlreadyConsolidatedError(field)` cualquier intento de mutar `amount`,
  `currency`, `category`, `date`, `property_id`, `statement_id` o `approved_by` cuando
  `statement_id IS NOT NULL`; `description` y `receipt_storage_key` SHALL permanecer
  mutables sin condición.
- `delete` SHALL rechazar con `ExpenseAlreadyConsolidatedError` cuando
  `statement_id IS NOT NULL`, con la guarda estructural (`WHERE statement_id IS NULL`)
  en la propia sentencia, no sólo en el caso de uso.

### Generación mensual y bajo demanda (R1, R2)

- WHEN el reloj llega al **primer día de cada mes a las 02:00 UTC**, THE SYSTEM SHALL
  ejecutar la tarea Celery `generate_owner_statements`, registrada en `MONTHLY_JOBS`
  con `MonthlySchedule(day_of_month=1, hour=2, lock_ttl=timedelta(hours=6))`, y generar
  un `OwnerStatement DRAFT` por cada `(tenant, property ACTIVE)` cuyo período cerrado
  sea el mes natural anterior.
- THE SYSTEM SHALL exponer la misma generación en
  `POST /api/v1/owner-statements/generate` (payload `{property_id?, period_end}`),
  ejecutada **síncronamente** dentro de la petición — sin `202` ni identificador de
  job — devolviendo el informe del barrido: `created`, `skipped`, `failed`,
  `consolidated_count`, `currency_mismatch`. WHERE se omite `property_id`, THE SYSTEM
  SHALL recorrer todas las propiedades `ACTIVE` del tenant.
- `Period.month_containing(period_end)` SHALL exigir que `period_end` sea el último día
  de su mes natural; una llamada con un `period_end` que no lo sea SHALL fallar la
  construcción (`ValueError`, mapeado a `422` por el router vía validación previa).
- THE SYSTEM SHALL ser **idempotente** sobre la clave única
  `(tenant_id, property_id, period_start, period_end)`: si `find_by_unique_key` ya
  devuelve una fila, THE SYSTEM SHALL preservarla intacta y contarla en `skipped`, sin
  volver a calcular ni a reasociar `Expense`.
- THE SYSTEM SHALL comprobar la mezcla de monedas **antes** de sumar (`CurrencyFilter.check`
  sobre las `reservations` y `expenses` en bruto del período): si **cualquier** fila
  computable tiene `currency != "EUR"`, THE SYSTEM SHALL abortar la generación de ese
  `(tenant, property, period)` entero — sin statement parcial — y reportarlo en
  `currency_mismatch` con la lista `(row_id, currency, table)`, siguiendo con el
  siguiente `(tenant, property, period)`. No hay conversión FX ni columna `currency` en
  `OwnerStatement`: la moneda es implícitamente EUR.
- `MonetaryAggregator.aggregate` SHALL sumar `gross_revenue`/`ota_commissions` de las
  `reservations` del período y derivar `net_revenue = gross_revenue - ota_commissions`;
  SHALL sumar cada `Expense` en su bucket de categoría (los siete de
  `ExpenseCategory` → `cleaning_costs`…`other_costs`) **excluyendo** las filas ya
  consolidadas (`statement_id IS NOT NULL`) y las pendientes de aprobación de umbral
  (`amount > threshold_eur AND approved_by IS NULL`); SHALL derivar
  `net_owner_result = net_revenue - Σ(costes)`.
- WHEN la generación produce un statement nuevo, THE SYSTEM SHALL, en la misma
  transacción: (1) persistir el `OwnerStatement DRAFT` con los once importes, (2)
  ejecutar `bulk_associate_to_statement` sobre las `Expense` del período (`date` dentro
  de `[period_start, period_end]`, `statement_id IS NULL`) para fijar su
  `statement_id`, contando las filas tocadas en `consolidated_count`. Ese `statement_id`
  **no vuelve a cambiar** — no hay regeneración ni reasociación posterior (R1.3, R2.3).
- THE SYSTEM SHALL abrir **una transacción por `(tenant, property)`** y no una por
  tenant: una vivienda que falle no descarta las liquidaciones ya escritas de las
  anteriores del mismo barrido. IF una unidad falla, THEN THE SYSTEM SHALL abandonarla,
  contarla en `failed`, registrar su identificador y seguir con la siguiente.
- IF `property_id` del cuerpo de `POST /generate` nombra una vivienda de otro tenant,
  inactiva o inexistente, THEN THE SYSTEM SHALL responder `422`; `404` queda reservado
  al `statement_id` ausente de las rutas de recurso.
- THE SYSTEM SHALL emitir un `TimelineEvent OWNER_STATEMENT_GENERATED` por cada
  statement **creado** (no por los `skipped`), con `metadata` cerrado
  (`statement_id, property_id, period_start, period_end, source`) y actor `SCHEDULER`
  cuando lo dispara el reloj, `USER` cuando lo dispara una persona.
- THE SYSTEM SHALL **no** escribir `AuditLog` cuando la generación la dispara el job
  mensual (sexta excepción de regla 9 de `steering/security.md`, ya documentada allí);
  SHALL escribirlo siempre (`OWNER_STATEMENT_GENERATED`, con actor) cuando la dispara
  `POST /api/v1/owner-statements/generate`.

### Umbral de aprobación del propietario (R5.7)

- WHEN `CreateExpenseUseCase.execute()` recibe `amount > TenantConfig.owner_approval_threshold_eur`,
  THE SYSTEM SHALL, en la misma transacción: crear el `Expense` con `approved_by=None`,
  crear un `OwnerApproval(related_type=OTHER, related_id=expense.id, amount, reason)` vía
  el `OwnerApprovalRepository` de `maintenance` (puerto reusado, sin cambios en
  `maintenance.application`), y devolver el `Expense` con `pending_owner_approval_id`
  apuntando a esa aprobación. WHEN `amount <= threshold`, THE SYSTEM SHALL dejar
  `pending_owner_approval_id` en `None` y no crear `OwnerApproval` alguna.
- THE SYSTEM SHALL ejecutar cada 5 minutos la tarea `reconcile_owner_approvals_for_expenses`
  (registrada en `CADENCES`), que materializa las respuestas ya dadas por el propietario
  sin cursor externo — la query lee directamente el estado de las filas
  (`owner_approvals.responded_at IS NOT NULL` cruzado con `expenses.approved_by`/
  `statement_id`), así que ninguna respuesta llegada entre dos ejecuciones se pierde.
  WHEN encuentra `OwnerApproval(OTHER, APPROVED)` con `Expense.approved_by IS NULL AND
  statement_id IS NULL`, THE SYSTEM SHALL fijar `approved_by`; WHEN encuentra
  `OwnerApproval(OTHER, REJECTED)` con `Expense.statement_id IS NULL`, THE SYSTEM SHALL
  borrar la fila. Ambas escrituras son idempotentes por sus propias guardas SQL
  (`rowcount=0` en la segunda pasada).
- IF `OwnerApproval(OTHER, REJECTED)` apunta a un `Expense` ya con `statement_id IS NOT
  NULL`, THEN THE SYSTEM SHALL **no** borrar ni reinterpretar la fila: la reporta en
  `failed_reconciliation` (`approval_id, expense_id, property_id, period_start,
  period_end`) con `logger.error`, como anomalía de datos.
- La consolidación del cálculo (`MonetaryAggregator`) SHALL filtrar por
  `approved_by IS NOT NULL OR amount <= threshold_eur`: una fila `PENDING` no cuenta
  hasta que la reconciliación materialice la respuesta.
- **Latencia esperada de hasta 5 minutos** entre la respuesta del owner y su
  materialización en `expenses` — comportamiento aceptado por diseño (D4), no un
  defecto.

### Lectura y filtrado (R3)

- WHEN un usuario con `READ_OWNER_STATEMENTS` emite `GET /api/v1/owner-statements`, THE
  SYSTEM SHALL devolver únicamente las del tenant de la sesión, filtradas por
  `property_id`, `period_start_from`, `period_start_to` y `status` (todas combinadas con
  AND), paginadas con tamaño **fijo de 20** en el servidor — el `per_page` que el
  cliente envíe se acepta pero se ignora, y la respuesta SHALL declarar el valor
  realmente usado.
- THE SYSTEM SHALL devolver el sobre `{items, total, page, per_page}` — `items`, no
  `data` — siguiendo la convención que `revenue-pricing` fijó para este proyecto.
- WHEN un usuario emite `GET /api/v1/owner-statements/{statement_id}`, THE SYSTEM SHALL
  devolver el detalle con los once importes y `status`/`notes`; el mismo caso de uso
  (`GetOwnerStatementUseCase`) alimenta el exportador PDF, así que las dos superficies
  no pueden divergir sobre qué es "el detalle".
- IF el `statement_id` no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL
  responder `404` con **el mismo cuerpo constante** en los dos casos.
- `GET /api/v1/expenses` SHALL filtrar por `property_id`, el rango
  `period_start_from`/`period_start_to` sobre `expense.date` y `category`, paginado
  igual que la lista de statements. Cada fila SHALL llevar `pending_owner_approval_id`
  (D13): el `id` de la `OwnerApproval(OTHER, PENDING)` que la referencia, o `None`.
  `GET /api/v1/expenses/{expense_id}` SHALL devolver el mismo campo para el detalle.

### Mutación del statement (R4)

- WHEN el manager emite `PATCH /api/v1/owner-statements/{statement_id}` con
  `{notes}`, THE SYSTEM SHALL actualizar sólo `notes` (vía `update_notes`) y registrar
  `AuditLog OWNER_STATEMENT_NOTES_UPDATED` con `{"changed": true}` — el valor de `notes`
  **nunca** llega literal a `audit_logs.changes` (regla 11).
- WHEN el manager emite `PATCH .../{statement_id}` con `{status: "READY"|"SENT"}`, THE
  SYSTEM SHALL validar la transición contra `_TRANSITIONS` **antes** de mutar, devolver
  `409` si el origen no encaja, y registrar `AuditLog OWNER_STATEMENT_STATUS_CHANGED`
  con el diff de `status` cuando la transición es legal.
- Ninguna otra columna del statement es escribible desde la API: `amount`/`period`/etc.
  no están en el esquema Pydantic de la petición (`extra="forbid"`), así que enviarlas
  es un `422` de Pydantic y no llega al caso de uso.
- IF una mutación se rechaza por validación, THEN THE SYSTEM SHALL restaurar
  `updated_at` desde una instantánea previa, de modo que un rechazo no deje marca
  temporal fantasma.

### Expenses CRUD (R5)

- WHEN el manager emite `POST /api/v1/expenses`, THE SYSTEM SHALL persistir el gasto en
  el tenant de la sesión, validando `category` contra los siete valores de
  `ExpenseCategory`, `currency` por defecto `EUR`, `amount <= 10**8`, `description` no
  vacía ni con `U+0000` y acotada a 500 caracteres, `date` válida y no futura.
- IF `date` cae dentro de un período ya cubierto por un `OwnerStatement` de la misma
  vivienda, THEN THE SYSTEM SHALL rechazar con `409 NamedExpenseInClosedPeriodError`
  tanto en `POST` como en `PATCH` que mueva `date` a esa franja — es un conflicto de
  estado (el período ya cerró), no un fallo de esquema.
- WHEN el manager emite `PATCH /api/v1/expenses/{expense_id}`, THE SYSTEM SHALL validar
  el recurso completo y aplicar sólo los campos presentes en el cuerpo
  (`model_dump(exclude_unset=True)`); campos consolidados (`amount`, `currency`,
  `category`, `date`, `property_id`, `statement_id`, `approved_by`) sobre un gasto con
  `statement_id IS NOT NULL` SHALL rechazarse con `409 ExpenseAlreadyConsolidatedError`
  nombrando el campo. `statement_id`, `property_id`, `approved_by`, `incident_id` y
  `created_at` no están en el esquema de la petición.
- WHEN el manager emite `DELETE /api/v1/expenses/{expense_id}`, THE SYSTEM SHALL
  borrarlo **sólo si** `statement_id IS NULL`; si está consolidado, `409` con cuerpo
  nombrado.
- IF el `expense_id` pertenece a otro tenant o no existe, THEN THE SYSTEM SHALL
  responder `404` con el mismo cuerpo constante que R3.4.
- THE SYSTEM SHALL registrar `AuditLog` para `EXPENSE_CREATED`, `EXPENSE_UPDATED` y
  `EXPENSE_DELETED`, con actor siempre presente (ninguna vía de `Expense` está exenta
  de regla 9).

### Export CSV y PDF (R6)

- WHEN un usuario con `READ_OWNER_STATEMENTS` emite
  `GET /api/v1/owner-statements/{statement_id}/export.csv`, THE SYSTEM SHALL responder
  `200` con `Content-Type: text/csv; charset=utf-8`, `Content-Disposition: attachment;
  filename="owner-statement-<period_end>.csv"` y un cuerpo con la cabecera
  `date,category,description,amount,currency,receipt_storage_key` seguida de una fila
  por `Expense` del statement, en UTF-8 sin BOM.
- THE SYSTEM SHALL anteponer una comilla simple a cualquier celda cuyo valor empiece
  por `=`, `+`, `-` o `@` (protección contra ejecución de fórmula al abrir en hoja de
  cálculo), sin escapar ningún otro carácter — los acentos y demás UTF-8 viajan
  directos, coherente con R6.2.
- WHEN un usuario emite `GET .../{statement_id}/export.pdf`, THE SYSTEM SHALL responder
  `200` con `Content-Type: application/pdf` y devolver un PDF **generado en el
  momento** (no persistido en `StorageAdapter`), compuesto con `fpdf2`: cabecera de
  tenant (`name`, país), bloque de vivienda (`name`, `internal_code`, dirección),
  bloque de período (`period_start`–`period_end`, `status`), tabla de reservas
  (`check_in_date`, noches, `gross_amount`, `ota_commission`, `net_amount`), tabla de
  gastos agrupada por categoría con subtotal, fila de totales (`net_owner_result`) y
  caja de `notes` si existen. Sin logo.
- THE SYSTEM SHALL formatear todo importe con dos decimales y separador `,` (locale
  `es-ES`), sin símbolo de moneda por columna en el PDF; el `currency` sólo aparece por
  fila en el CSV, donde es propiedad de cada `Expense`.
- IF el statement no existe o pertenece a otro tenant, ambas rutas de export SHALL
  responder `404` con el mismo cuerpo constante que R3.4.
- THE SYSTEM SHALL **no** registrar `AuditLog` por ninguna de las dos descargas: un
  export es una lectura.

### Permisos, aislamiento, auditoría

- THE SYSTEM SHALL proteger las once rutas con dos permisos —`READ_OWNER_STATEMENTS` y
  `MANAGE_OWNER_STATEMENTS`—, concediendo `READ` a `TENANT_OWNER` y `PROPERTY_MANAGER`,
  y `MANAGE` sólo a `PROPERTY_MANAGER`. `CLEANER`, `TECHNICIAN` y `SUPER_ADMIN` no
  reciben ninguno. `RESPOND_OWNER_APPROVALS`, ya existente, sigue siendo el permiso con
  el que el owner responde las aprobaciones de umbral que D4 genera.
- THE SYSTEM SHALL resolver el tenant siempre desde la sesión autenticada (nunca del
  cuerpo ni de la query) y comprobar en el repositorio que la entidad pertenece a ese
  tenant antes de leer o mutar.
- THE SYSTEM SHALL registrar dos entidades nuevas en `app/audit/domain/actions.py`
  (`OWNER_STATEMENT`, `EXPENSE`) y seis acciones
  (`OWNER_STATEMENT_GENERATED`, `OWNER_STATEMENT_STATUS_CHANGED`,
  `OWNER_STATEMENT_NOTES_UPDATED`, `EXPENSE_CREATED`, `EXPENSE_UPDATED`,
  `EXPENSE_DELETED`), con `AUDITABLE_FIELDS["OWNER_STATEMENT"] = {"status", "notes"}` y
  `AUDITABLE_FIELDS["EXPENSE"] = {"category", "amount", "currency", "date",
  "statement_id", "incident_id", "approved_by", "receipt_storage_key"}`.
  `REDACT_ONLY_FIELDS["EXPENSE"] = {"description"}` — su valor va a `audit_logs.changes`
  sólo como `{"changed": true}`.
- La sexta excepción de regla 9 (job mensual sin `AuditLog`) y las dos filas nuevas del
  censo de regla 11 (`owner_statements.notes`, `expenses.description`, ambas excepción
  3) están documentadas en `sdd/steering/security.md`.

## Boundaries (Out of scope)

- **Pantalla `/statements`**: queda como `RoutePlaceholder`; el frontend es un change
  propio (precedente `revenue-pricing` → `pricing-web`).
- **Envío real al propietario**: `status = SENT` significa "marcado como enviado por el
  operador", no "entregado por el sistema". Ningún canal de notificación se abre desde
  este módulo.
- **Facturación fiscal**: fuera del MVP.
- **Derivación automática de costes** desde `CleaningTask`/`Incident`: V1 sólo cuenta
  `Expense` explícitos.
- **Versionado / histórico del statement**: no hay tabla de snapshots; regenerar sobre
  la misma clave única no es una operación soportada — la fila existente se preserva
  intacta.
- **Multi-moneda real**: la generación aborta el `(tenant, property, period)` completo
  ante cualquier fila no-EUR; no hay conversión FX ni columna `currency` en
  `OwnerStatement`.
- **Cifrado en reposo de `notes`/`description`**: pendiente del change
  `plaintext-sink-encryption-at-rest` del roadmap.
- **Receipt uploader / OCR**: `receipt_storage_key` es un puntero de texto libre; no hay
  subida ni validación de justificantes en este change.
- **`RESPOND_OWNER_APPROVALS` sobre `Expense`**: el endpoint de respuesta de
  `maintenance` no se toca; la integración pasa por el `OwnerApproval(related_type=OTHER)`
  canónico y el job de reconciliación, sin acoplar `maintenance.application` a
  `Expense`.

## Estado y deuda conocida

- **No hay traducción de mensajes de error por locale de sesión en el backend.** A
  diferencia de lo que sugiere R7.7 del proposal ("traducir todos los mensajes de error
  al locale de la sesión en ES y EN"), `app/statements/api/errors.py` — igual que
  `app/pricing/api/errors.py`, el precedente que sigue — renderiza `str(exc)` de
  mensajes constantes en inglés; no existe ningún módulo `backend/app/core/i18n/` ni
  mecanismo de traducción por `Accept-Language` o locale de usuario en el backend de
  este proyecto. El patrón real del proyecto (fijado por `revenue-pricing` →
  `pricing-web`, sección "Errores por status") es que el **frontend** elige la copia
  ES/EN por status HTTP y nunca expone el cuerpo del backend — pero como
  `/statements` queda `RoutePlaceholder` en este change, esa capa de traducción no
  existe todavía para `owner-statements`/`expenses`. La tarea 10.1 de `tasks.md`, que
  se marcó completa, no encontró ningún módulo i18n backend real que extender.
- **El `_MAPPING` de `app/statements/api/errors.py` no está wireado en la guarda de
  `backend/tests/test_openapi_contract.py`.** Es un duodécimo caso del mismo hueco que
  `sdd/specs/api-contract.md` ya documenta para `access`, `guests`, `maintenance`,
  `messaging` y `timeline`: existir en `app/*/api/errors.py` no basta, hay que
  importarlo explícitamente en la tupla de la guarda. `statements` no lo hace, así que
  un futuro literal de `ErrorCode` fuera de `_MAPPING` en este módulo no lo detectaría
  ningún test estructural.
- **`fpdf2` renderiza con la fuente `Helvetica` core y una recodificación a `cp1252`**
  (`_text()` en `pdf.py`), no UTF-8 nativo: un carácter fuera de `cp1252` se sustituye
  (`errors="replace"`) en vez de preservarse. Suficiente para español (acentos, `ñ`,
  `€` no se usa porque el PDF no imprime símbolo de moneda), pero un nombre de tenant o
  vivienda con un carácter fuera de Latin-1 perdería fidelidad en el PDF.
- **El detalle JSON no lleva el desglose por reserva ni la lista de `Expense`.**
  R3.3/R3.5 del proposal lo pedían, pero `OwnerStatementResponse` expone sólo identidad,
  período, `status`, `notes`, los once importes y timestamps. El desglose por reserva y
  los gastos consolidados sólo son alcanzables hoy por `export.pdf` (ambos) y
  `export.csv` (gastos), o filtrando `GET /api/v1/expenses` por vivienda y período.
  Quien lo quiera en JSON tiene que añadirlo al DTO en un change propio.
- **`failed` sí está en el contrato publicado** — a diferencia de `revenue-pricing`,
  `OwnerStatementGenerationReportResponse` expone los cinco contadores (`created`,
  `skipped`, `failed`, `consolidated_count`, `currency_mismatch`), así que un barrido
  con agujeros **no** se ve verde desde la API.
- **No hubo migración.** Las dos tablas y sus dos enums ya estaban en
  `domain-foundation-financial`; este change no añade columnas, enums ni variables de
  entorno. `fpdf2` es la única dependencia nueva (`backend/pyproject.toml`).

## Key files

- `backend/app/statements/domain/entities.py` — `OwnerStatement` (`_TRANSITIONS`,
  `mark_ready`, `mark_sent`, `update_notes`), `Expense`.
- `backend/app/statements/domain/exceptions.py` — las siete excepciones del módulo,
  jerarquía plana sobre `StatementsDomainError`.
- `backend/app/statements/domain/repositories.py` — `ExpenseReader` (intacto,
  `dashboard-api`), `OwnerStatementRepository`, `ExpenseRepository`,
  `OwnerStatementFilters`, `ExpenseFilters`.
- `backend/app/statements/domain/enums.py` — `OwnerStatementStatus`, `ExpenseCategory`
  (sin cambios de esquema; `domain-foundation-financial`).
- `backend/app/statements/application/use_cases.py` — los once casos de uso, el
  `_AuditWriter` interno y `StatementsActor`.
- `backend/app/statements/application/generation.py` — `Period`, `CurrencyFilter`,
  `MonetaryAggregator`, `StatementBreakdown`.
- `backend/app/statements/application/reconciliation.py` — `ReconcileOwnerApprovalsForExpensesUseCase`.
- `backend/app/statements/infrastructure/repositories.py` — los dos adaptadores
  SQLAlchemy.
- `backend/app/statements/infrastructure/pdf.py` — `PdfStatementGenerator` (fpdf2).
- `backend/app/statements/infrastructure/csv_export.py` — `CsvStatementExporter`.
- `backend/app/statements/api/router.py` — las once rutas bajo `/owner-statements` y
  `/expenses`.
- `backend/app/statements/api/schemas.py`, `dependencies.py`, `errors.py` — DTOs
  Pydantic v2, builders de casos de uso, mapeo de excepciones a HTTP.
- `backend/app/scheduler/schedule.py` — `MonthlySchedule`, `MONTHLY_JOBS`.
- `backend/app/scheduler/tasks.py` — `_generate_owner_statements`, `_guarded_monthly`,
  `_reconcile_owner_approvals_for_expenses`, las dos tareas Celery.
- `backend/app/auth/domain/policy.py` — `READ_OWNER_STATEMENTS`,
  `MANAGE_OWNER_STATEMENTS`, `_STATEMENTS_READ`, `_STATEMENTS_MANAGE`.
- `backend/app/audit/domain/actions.py`, `value_objects.py` — entidades, acciones,
  `AUDITABLE_FIELDS`, `REDACT_ONLY_FIELDS` de `OWNER_STATEMENT`/`EXPENSE`.
- `backend/tests/statements/` — tests de entidad, repositorio, casos de uso,
  generación, reconciliación, PDF, CSV, idempotencia, consolidación, umbral, API.
- `backend/tests/scheduler/` — el job mensual y su lock.
- `docs/revenue-statements.md` — cómo se opera: generación, aprobaciones, exports.
