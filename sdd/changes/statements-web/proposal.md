# Proposal: statements-web

## Why

La ruta `/statements` sigue siendo un `RoutePlaceholder`, aunque `revenue-statements` y
`revenue-statements-detail-breakdown` ya entregaron el contrato backend definitivo y el job
mensual. La propietaria y el manager necesitan consultar las liquidaciones mensuales del tenant,
revisar el resumen junto con el desglose financiero de reservas y gastos, y descargar sus
exportaciones desde el workspace. Este change completa la superficie frontend de reporting
soportada por el backend, como exige PRD §20 y el hito PRD §28.16.

## What changes

La ruta `/statements` se convertirá en una superficie frontend responsive para listar y consultar
`OwnerStatement` por propiedad, período y estado, mostrando el resumen financiero y, en el detalle,
las colecciones de reservas y gastos que publica `OwnerStatementDetailResponse`. También ofrecerá
las descargas CSV y PDF según el contrato actual. Reutilizará la sesión autenticada, los permisos
backend, el aislamiento por tenant, el cliente API tipado, los patrones de TanStack Query, estados
de carga/error/vacío y las traducciones ES/EN existentes. No requiere cambios backend.

La separación contractual será explícita: el listado consume `OwnerStatementResponse` y el detalle
consume `OwnerStatementDetailResponse`, cuyo summary permanece plano e incorpora `reservations[]`
y `expenses[]`.

## Requirements

### R1 — Acceso autenticado y alcance por tenant

**As a** propietaria o manager, **I want** acceder a `/statements` con mi sesión del workspace,
**so that** pueda consultar únicamente las liquidaciones de mi tenant.

Acceptance criteria:

1. WHEN una propietaria o manager autenticado navega a `/statements`, THE SYSTEM SHALL renderizar la
   superficie financiera usando el workspace shell y la sesión existente.
2. WHEN el backend responde `401` o `403`, THE SYSTEM SHALL reutilizar el comportamiento de
   sesión/autorización existente y no mostrar datos financieros.
3. WHEN se consultan statements, THE SYSTEM SHALL enviar únicamente los filtros del usuario y
   consumir el alcance de tenant garantizado por `GET /api/v1/owner-statements`; THE SYSTEM SHALL no
   aceptar ni construir un `tenant_id` desde la UI.

### R2 — Listado filtrable y paginado

**As a** propietaria o manager, **I want** ver mis liquidaciones agrupadas por período y propiedad
 y filtrarlas, **so that** pueda encontrar rápidamente un statement concreto.

Acceptance criteria:

1. WHEN la ruta carga, THE SYSTEM SHALL consultar `GET /api/v1/owner-statements` mediante el
   cliente API tipado y consumir sus `items` como `OwnerStatementResponse`, mostrando período,
   estado y resultado neto; como el contrato publica únicamente `property_id`, THE SYSTEM SHALL
   resolver el nombre o label legible mediante la fuente existente de propiedades del workspace.
2. WHEN el usuario selecciona una propiedad, THE SYSTEM SHALL ofrecer las opciones y resolver su
   label usando esa misma fuente existente de propiedades, no únicamente las filas de la página
   actual de statements; THE SYSTEM SHALL enviar el `property_id` seleccionado al endpoint existente
   y no añadir ningún endpoint backend nuevo.
3. WHEN el usuario selecciona propiedad, rango de período o estado, THE SYSTEM SHALL combinarlos en
   la consulta usando los parámetros `property_id`, `period_start_from`, `period_start_to` y `status`
   del contrato OpenAPI.
4. WHEN el backend devuelve paginación, THE SYSTEM SHALL respetar `items`, `total`, `page` y
   `per_page`, y permitir navegar entre páginas sin inventar un `total_pages` no publicado.

### R3 — Detalle financiero completo del statement

**As a** propietaria o manager, **I want** abrir una liquidación, **so that** pueda revisar su
resumen, sus líneas financieras y su estado antes de descargarla.

Acceptance criteria:

1. WHEN el usuario abre un statement, THE SYSTEM SHALL consultar
   `GET /api/v1/owner-statements/{statement_id}` y renderizar el `OwnerStatementDetailResponse`:
   el summary plano con período, estado, notas y las once cantidades monetarias de
   `OwnerStatementResponse`, además de `reservations[]` y `expenses[]`.
2. WHEN se renderiza `reservations[]`, THE SYSTEM SHALL mostrar únicamente sus campos contractuales:
   `id`, `check_in_date`, `nights`, `gross_amount`, `ota_commission`, `net_amount` y `currency`.
3. WHEN se renderiza `expenses[]`, THE SYSTEM SHALL mostrar únicamente sus campos contractuales:
   `id`, `category`, `description`, `amount`, `currency` y `date`.
4. WHEN cualquiera de los breakdowns está vacío, THE SYSTEM SHALL mostrar un estado vacío
   traducido para esa colección, sin tratarlo como error y sin inventar líneas, subtotales o
   agregados que el backend no publica.
5. WHEN una reserva contiene `gross_amount`, `ota_commission` o `net_amount` a `null`, THE SYSTEM
   SHALL representar el importe como ausente según el diseño localizado y no sustituirlo por cero
   ni calcular un valor alternativo.
6. WHEN se muestran importes de breakdown, THE SYSTEM SHALL respetar la `currency` de cada fila;
   como el summary no publica una moneda, la UI no SHALL inventar una moneda global, convertir
   monedas ni presentar un agregado entre monedas distintas.
7. WHEN el identificador no existe o pertenece a otro tenant, THE SYSTEM SHALL mostrar el estado de
   recurso no encontrado conforme al contrato existente, sin revelar cuál de las dos causas ocurrió.
8. WHEN el backend devuelve `notes: null`, THE SYSTEM SHALL mantener visible el campo en el estado
   de detalle sin sustituirlo por datos de otro recurso.

### R4 — Descarga de exportaciones

**As a** propietaria o manager, **I want** descargar el CSV de gastos y el PDF del statement,
**so that** pueda usar el reporting fuera de la aplicación.

Acceptance criteria:

1. WHEN el usuario solicita CSV, THE SYSTEM SHALL llamar
   `GET /api/v1/owner-statements/{statement_id}/export.csv` y descargar como bytes el archivo de
   gastos devuelto por el backend, respetando `Content-Type`, `Content-Disposition`/`filename` y
   las demás cabeceras contractuales.
2. WHEN el usuario solicita PDF, THE SYSTEM SHALL llamar
   `GET /api/v1/owner-statements/{statement_id}/export.pdf` y descargar como bytes el archivo de
   reporting financiero devuelto por el backend, respetando `Content-Type`,
   `Content-Disposition`/`filename` y las demás cabeceras contractuales.
3. THE SYSTEM SHALL tratar ambos archivos como payloads opacos: el frontend no SHALL parsear,
   validar internamente, re-encodear, transformar ni reconstruir el CSV o el PDF; la estructura
   interna de cada archivo es responsabilidad del endpoint backend existente.
4. IF una descarga falla, THEN THE SYSTEM SHALL mostrar un error traducido, limpiar cualquier recurso
   temporal creado y no presentar una descarga parcial como válida.

### R5 — Estados de UI, responsive e i18n

**As a** usuario del workspace, **I want** una pantalla comprensible en móvil y escritorio,
**so that** pueda revisar el reporting sin depender del idioma ni de una respuesta instantánea de
red.

Acceptance criteria:

1. WHEN el listado, detalle o descarga está en curso, THE SYSTEM SHALL mostrar el estado de carga
   del patrón frontend correspondiente y evitar acciones duplicadas mientras la operación está
   pendiente.
2. WHEN el listado no contiene resultados, THE SYSTEM SHALL mostrar un estado vacío traducido que
   distinga ausencia de statements de error de red.
3. WHEN una colección de breakdown no contiene filas, THE SYSTEM SHALL distinguir la ausencia de
   datos de un error de red y mantener visible el summary disponible.
4. WHEN la sesión está en español o inglés, THE SYSTEM SHALL renderizar etiquetas, categorías,
   estados, fechas, importes, monedas y mensajes de error mediante las claves ES/EN existentes o
   nuevas claves de este change, sin texto visible hardcodeado.
5. WHEN el viewport es móvil, THE SYSTEM SHALL mantener legibles los filtros, importes, breakdowns,
   estado y controles de descarga sin exigir desplazamiento horizontal de la página completa.

## Out of scope

- Generación manual de statements desde la UI; la generación mensual y su endpoint ya pertenecen a
  `revenue-statements`.
- Creación, edición o borrado de gastos; el formulario de gastos queda para una decisión/change
  posterior.
- Edición de notes o transiciones `DRAFT → READY → SENT` desde la UI; este change sólo expone el
  estado y las notes existentes.
- Cambios backend, nuevas rutas, cambios de permisos, cambios de tenancy o modificaciones del
  contrato OpenAPI; los endpoints y breakdowns consumidos ya existen.
- Envío por email del statement; queda condicionado a `guest-scheduled-comms`.
- Cambios en dashboard, detalle de propiedad, pricing, reviews o superficies de José.

## Affected specs

- `sdd/specs/revenue-statements.md` — actualizar la descripción de la superficie frontend y sus
  límites, incluyendo el consumo del summary, breakdowns y exportaciones existentes.
- `sdd/specs/revenue-statements-detail-breakdown.md` — referencia del contrato de detalle que esta
  superficie consume; no se modifica el backend ni su contrato en este change.
- `sdd/specs/statements-web.md` *(no existe aún — se creará al archivar)* — contrato vivo de la
  superficie `/statements`, incluido el listado, detalle, estados vacíos e i18n.
