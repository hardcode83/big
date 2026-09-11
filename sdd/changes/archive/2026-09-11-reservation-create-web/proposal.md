# Proposal: reservation-create-web

## Why

`/reservations` ya permite consultar el listado y el detalle, pero sigue siendo una
superficie de solo lectura: el backend ya publica `POST`, `PATCH` y `DELETE` para el
ciclo manual y el frontend todavía no los consume. Esto impide que el manager inicie
una estancia nueva desde el navegador y obliga a depender del seed, CSV o llamadas
manuales para probar el ciclo operativo del MVP.

La entrada correspondiente del roadmap y su nota (`sdd/roadmap.md` y
`sdd/roadmap/reservation-create-web.md`) fijan el alcance. El contrato OpenAPI actual
(`frontend/lib/api/generated/openapi.d.ts`) es la fuente de verdad del transporte y
`sdd/specs/reservations.md` la fuente de verdad de las reglas de negocio. El backend y
la disponibilidad/solapes quedan fuera de este change.

## What changes

La aplicación añadirá al workspace de reservations un flujo de alta manual en
`/reservations` y controles de edición y cancelación en `/reservations/[id]`, usando el
cliente API tipado y React Query existentes. El flujo estará disponible para el rol
con `MANAGE_RESERVATIONS`, respetará las restricciones del contrato (canales manuales,
fechas, horas de la propiedad, huésped opcional y cancelación como cambio de estado) y
mantendrá la experiencia mobile-first, accesible y localizada en ES/EN.

## Requirements

### R1 — Alta manual desde el listado

**As a** manager, **I want** crear una reserva manual desde `/reservations`, **so that**
pueda iniciar una estancia operativa sin usar el seed, CSV, PMS o `curl`.

Acceptance criteria:

1. WHEN un usuario con permiso `MANAGE_RESERVATIONS` abre `/reservations`, THE SYSTEM
   SHALL ofrecer un formulario de alta que envíe `POST /api/v1/reservations` mediante
   el cliente API tipado.
2. WHEN el formulario se envía con datos válidos, THE SYSTEM SHALL enviar únicamente
   campos admitidos por `CreateReservationRequest`, mostrar el recurso creado y
   actualizar el listado sin recarga completa.
3. WHEN se crea una reserva manual, THE SYSTEM SHALL ofrecer únicamente los canales
   `DIRECT` y `MANUAL`, y SHALL reflejar que el estado inicial contractual es
   `PENDING`.
4. IF la API responde un error de validación, autorización, propiedad inexistente o
   propiedad inactiva, THEN THE SYSTEM SHALL mostrar el estado de error localizado y
   SHALL conservar los valores editables del formulario.

### R2 — Datos de huésped y reglas de fechas

**As a** manager, **I want** introducir los datos operativos de la estancia y del
huésped, **so that** la reserva pueda enlazar una identidad sin convertir la pantalla
en un gestor de huéspedes.

Acceptance criteria:

1. WHEN se crea una reserva, THE SYSTEM SHALL permitir seleccionar la propiedad e
   introducir fechas, horas opcionales, adultos, niños, canal, importes, moneda,
   peticiones especiales y los campos de contacto manual definidos por
   `ManualGuestRequest`.
2. WHEN se introducen las horas, THE SYSTEM SHALL mostrar la zona horaria de la
   propiedad y sus horas por defecto como contexto; IF el usuario no introduce horas
   opcionales, THEN THE SYSTEM SHALL omitirlas del request y dejar que el backend
   aplique la semántica contractual correspondiente.
3. WHEN el usuario introduce un check-in el mismo día, THE SYSTEM SHALL permitirlo
   siempre que el contrato/backend lo permita. THE SYSTEM SHALL bloquear únicamente
   intervalos inválidos y restricciones definidas por el contrato o las specs, sin
   imponer reglas frontend más restrictivas que el backend.
4. WHEN se proporciona información de huésped, THE SYSTEM SHALL enviarla como un
   bloque `guest` conforme a `ManualGuestRequest`; WHEN no se proporciona, THE SYSTEM
   SHALL omitir el huésped. La UI SHALL NOT exponer `guest_id` como campo editable,
   UUID o UX de búsqueda/entrada manual, ni SHALL intentar buscar huéspedes por nombre,
   teléfono o documentos.
5. IF el payload contiene `guest_id` y `guest` a la vez, THEN THE SYSTEM SHALL
   conservar la protección contractual y mostrar el `422` correspondiente sin crear la
   reserva; el flujo web SHALL NOT generar ni solicitar `guest_id`.

### R3 — Modificación y cancelación desde el detalle

**As a** manager, **I want** modificar o cancelar una reserva desde su detalle, **so
that** pueda corregir la operación y cerrar una estancia sin borrar su histórico.

Acceptance criteria:

1. WHEN un usuario con permiso `MANAGE_RESERVATIONS` abre `/reservations/[id]`, THE
   SYSTEM SHALL ofrecer edición de los campos admitidos por `UpdateReservationRequest`
   y SHALL enviar sólo los campos modificados mediante `PATCH`.
2. WHEN una edición cambia fechas u ocupación, THE SYSTEM SHALL mostrar la respuesta
   recalculada por el backend, incluidos `nights` y `total_guests`, y SHALL invalidar
   el detalle y el listado afectados.
3. WHEN la reserva tiene un canal no manual, THE SYSTEM SHALL deshabilitar los campos
   propiedad del ingestor (`INGEST_OWNED_FIELDS`) que no deba editar la UI y SHALL
   explicar el motivo de forma localizada.
4. WHEN el manager confirma la cancelación, THE SYSTEM SHALL llamar a `DELETE` como
   operación de cancelación, no de borrado físico, y SHALL reflejar el estado
   `CANCELLED` y el timeline actualizado.
5. IF una mutación responde `404`, `409` o `422`, THEN THE SYSTEM SHALL mostrar el
   error localizado sin presentar la operación como completada.

### R4 — Permisos, tenancy y estados de interfaz

**As a** usuario del workspace, **I want** que los controles respeten mi rol y el
aislamiento del backend, **so that** una pantalla de gestión no se convierta en una
vía de acceso o escritura indebida.

Acceptance criteria:

1. WHEN el usuario no tiene `MANAGE_RESERVATIONS`, THE SYSTEM SHALL mantener la vista
   de reservations en modo lectura y SHALL ocultar o deshabilitar los controles de
   alta, edición y cancelación.
2. WHEN una mutación está en curso, THE SYSTEM SHALL impedir envíos duplicados y
   mostrar un estado de progreso accesible; al terminar, SHALL mostrar éxito o error
   de forma perceptible sin depender sólo del color.
3. IF la sesión expira o el API devuelve una respuesta de autenticación no válida,
   THEN THE SYSTEM SHALL delegar el comportamiento al cliente autenticado existente y
   SHALL NOT persistir datos sensibles del formulario en una URL.
4. WHEN se cambie de tenant o se invalide la sesión, THE SYSTEM SHALL invalidar las
   queries y mutaciones de reservations con las claves tenant-scoped existentes.

### R5 — Integración frontend y experiencia localizada

**As a** manager que opera desde móvil, **I want** un flujo comprensible y accesible,
**so that** pueda completar el ciclo sin ambigüedades ni depender del idioma del
navegador.

Acceptance criteria:

1. THE SYSTEM SHALL reutilizar las primitivas compartidas de UI, estados y cliente API
   existentes, y SHALL mantener los targets táctiles y el indicador de foco definidos
   por las specs frontend.
2. THE SYSTEM SHALL proporcionar todas las etiquetas, ayudas, confirmaciones y errores
   del flujo en los namespaces ES y EN de reservations, sin strings visibles
   hardcodeadas en componentes.
3. WHEN la API devuelve un dato nullable, THE SYSTEM SHALL renderizar el fallback
   establecido por la feature (em dash donde corresponda) y SHALL distinguir valores
   vacíos de cero.
4. WHEN el código generado del contrato OpenAPI cambia, THE SYSTEM SHALL mantener los
   DTOs y las operaciones de `HttpReservationsSource` alineados con el contrato y
   SHALL conservar las comprobaciones de `api:check`.

## Out of scope

- Cambios backend, migraciones, nuevos endpoints o cambios del contrato API; los
  endpoints y el contrato consumidos ya existen.
- Importación CSV desde la web.
- Disponibilidad, cálculo de solapes o integración con Beds24, Airbnb, Booking u otro
  proveedor real.
- La UI no SHALL afirmar que ha validado disponibilidad externa ni SHALL insinuar que
  una reserva manual bloquea o sincroniza calendarios OTA; esas capacidades no existen
  en este change.
- CRUD o edición de huéspedes como entidad, documentos de identidad o gestión del
  portal del huésped.
- Confirmación automática al crear una reserva; la propuesta parte del estado inicial
  `PENDING` y deja la forma exacta de cualquier acción posterior de estado para el
  design.
- Cambios al shell compartido o una extracción general de nuevos componentes fuera de
  lo necesario para esta pantalla.

## Affected specs

- `sdd/specs/reservations.md` — documentar la superficie frontend del ciclo manual y
  sus límites, si procede al archivar.
- `sdd/specs/frontend-foundation.md` — actualizar la descripción de reservations si
  deja de ser solo lectura.
- `sdd/specs/frontend-api-contract-consumer.md` — registrar las operaciones mutantes
  consumidas por la feature, si procede.
- `sdd/specs/design-system-tokens.md` — sólo si el change introduce una aplicación
  específica de tokens o estados que deba quedar documentada; no se prevé ampliar el
  sistema de diseño.
