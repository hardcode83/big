# Proposal: revenue-statements-detail-breakdown

## Why

PRD §20 exige que el reporting financiero incluya el resumen mensual, el export de gastos y el desglose financiero por reserva. `revenue-statements` ya implementó esa composición para el caso de uso de detalle, pero `GET /api/v1/owner-statements/{statement_id}` sólo publica el resumen `OwnerStatementResponse`, por lo que la futura `statements-web` no puede consumir el desglose ni los gastos asociados. Este change cierra únicamente esa diferencia entre la composición interna existente y el contrato HTTP.

## What changes

El GET detail existente publicará de forma aditiva las colecciones `expenses` y `reservations` que `GetOwnerStatementUseCase` ya devuelve internamente, mediante un response schema específico del detalle o una composición API equivalente. No se reutilizarán directamente `ReservationResponse` ni `ExpenseResponse` si eso arrastra campos no necesarios: la proyección read-only incluirá sólo el identificador mínimo de fila y los campos financieros/temporales requeridos. El resumen/listado actual, los permisos, el aislamiento por tenant y el `404` indistinguible se conservarán. Se actualizarán los tests del caso de uso/API/contrato, `backend/openapi.json` y los tipos generados del frontend; no se añaden queries, endpoints, migraciones ni cambios de dominio.

## Requirements

### R1 — Detalle financiero completo en el contrato existente

**As a** propietaria o manager autorizado, **I want** que el detalle de un statement incluya su resumen, reservas y gastos asociados, **so that** una futura superficie frontend pueda cumplir el reporting financiero del PRD.

Acceptance criteria:

1. WHEN un usuario autorizado solicita `GET /api/v1/owner-statements/{statement_id}`, THE SYSTEM SHALL devolver el `OwnerStatement` actual con sus campos existentes y, además, las colecciones `expenses` y `reservations` que ya compone `GetOwnerStatementUseCase`.
2. WHEN el detalle contiene reservas, THE SYSTEM SHALL publicar únicamente el identificador de la reserva y los campos financieros/temporales existentes `check_in_date`, `nights`, `gross_amount`, `ota_commission`, `net_amount` y `currency`, sin recalcularlos en la capa API.
3. WHEN el detalle contiene gastos asociados, THE SYSTEM SHALL publicar únicamente el identificador del gasto y los campos existentes necesarios para el desglose: `category`, `description`, `amount`, `currency` y `date`.
4. THE SYSTEM SHALL not expose from `ReservationResponse` or `ExpenseResponse` fields unrelated to this read-only financial detail, including PII, internal notes, operational status, approval identity, receipt storage keys, external identifiers, timestamps or relationship identifiers not required to render the row.

### R2 — Reutilización de composición y schemas existentes

**As a** mantenedor del backend, **I want** que el contrato reutilice la composición y los DTOs ya existentes, **so that** el nuevo detalle no cree una segunda definición financiera ni otra ruta de lectura.

Acceptance criteria:

1. WHEN se serializa el detalle, THE SYSTEM SHALL consumir las claves `statement`, `expenses` y `reservations` que ya devuelve `GetOwnerStatementUseCase`, sin añadir una consulta paralela o duplicar su criterio de período, moneda y asociación por `statement_id`.
2. WHEN se construyen los elementos de las colecciones, THE SYSTEM SHALL usar los tipos de dominio existentes y reutilizar sólo los mapeos de `ExpenseResponse` y `ReservationResponse` que no arrastren datos adicionales; una proyección API read-only más estrecha es obligatoria si la reutilización completa expone campos innecesarios.
3. THE SYSTEM SHALL representar las colecciones únicamente en el response schema específico del GET detail o en una composición API equivalente, sin añadir `expenses` ni `reservations` a `OwnerStatementResponse` compartido por el listado y las respuestas de mutación.
4. WHEN se solicita el listado paginado de statements o una respuesta de mutación existente, THE SYSTEM SHALL conservar exactamente su schema, envelope, coste y comportamiento actuales, sin ejecutar la composición de detalle.

### R3 — Seguridad, tenancy y errores sin leakage

**As a** usuario autorizado, **I want** que el detalle enriquecido mantenga las mismas guardas de acceso, **so that** añadir colecciones no amplíe la visibilidad de datos.

Acceptance criteria:

1. WHEN el usuario solicita un statement, THE SYSTEM SHALL aplicar el tenant derivado de la sesión a la lectura del statement, de los gastos y de las reservas, sin aceptar `tenant_id` desde la petición.
2. IF el statement no existe o pertenece a otro tenant, THEN THE SYSTEM SHALL responder `404` con el mismo cuerpo constante actual y no ejecutar ni publicar sus colecciones asociadas.
3. WHEN se publica una colección, THE SYSTEM SHALL incluir únicamente filas que el caso de uso ya haya acotado al tenant, propiedad, período, `statement_id` y moneda aplicables, sin permitir que una colección revele datos de otro tenant.

### R4 — Compatibilidad y contrato derivado

**As a** consumidor actual de la API, **I want** que la ampliación sea aditiva y esté reflejada en los contratos derivados, **so that** los clientes existentes sigan funcionando y el frontend pueda generar tipos correctos.

Acceptance criteria:

1. WHEN un cliente consume los campos actuales de `OwnerStatementResponse`, THE SYSTEM SHALL seguir recibiendo sus mismos nombres, tipos y semántica.
2. WHEN se regenera el contrato, THE SYSTEM SHALL reflejar en `backend/openapi.json` el response enriquecido y específico del GET detail, con la proyección mínima de `expenses` y `reservations`, y regenerar `frontend/lib/api/generated/openapi.d.ts` desde ese contrato.
3. WHEN se inspecciona el schema del listado, THE SYSTEM SHALL mantener `OwnerStatementPageResponse` y su referencia actual a `OwnerStatementResponse` sin añadirle colecciones ni aumentar el coste de `GET /api/v1/owner-statements`.

### R5 — Verificación de comportamiento

**As a** mantenedor del sistema, **I want** pruebas que cubran la respuesta enriquecida, **so that** el contrato no vuelva a descartar la composición interna.

Acceptance criteria:

1. WHEN los tests API solicitan un statement válido, THE SYSTEM SHALL verificar el resumen actual y la presencia/contenido de `expenses` y `reservations` conforme al contrato publicado.
2. WHEN los tests cubren otro tenant o un identificador inexistente, THE SYSTEM SHALL verificar el mismo `404` y la ausencia de cualquier dato asociado.
3. WHEN los tests de contrato se ejecutan tras regenerar OpenAPI y tipos, THE SYSTEM SHALL verificar que las colecciones del detalle están declaradas y que no se han añadido endpoints ni operaciones de escritura.

## Out of scope

- CRUD de gastos.
- Edición de `notes`.
- Transiciones `DRAFT`/`READY`/`SENT`.
- Generación manual desde UI.
- Envío por email.
- Cualquier cambio frontend o visual de `statements-web`.
- Nuevos endpoints o nuevas queries para el desglose; se enriquece el GET detail existente usando la composición ya presente.
- Exponer directamente `ReservationResponse` o `ExpenseResponse` completos si contienen campos no necesarios; el desglose usa una proyección API read-only mínima derivada de los campos existentes.
- Añadir `expenses` o `reservations` a `OwnerStatementResponse` compartido por `OwnerStatementPageResponse`; las colecciones pertenecen sólo al response del GET detail.
- Migraciones, cambios de dominio y modificaciones no necesarias del modelo financiero.

## Affected specs

- `sdd/specs/revenue-statements.md` — actualizar el estado/documentación del gap del DTO detail.
- `sdd/specs/revenue-statements-detail-breakdown.md` *(no existe aún — se creará al archivar)* — contrato vivo del GET detail enriquecido.
