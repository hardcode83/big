# Proposal: reservation-manual-guest-resolution

## Why

El único mecanismo actual para **vincular** un huésped durante el alta manual de
`POST /api/v1/reservations` es aportar un `guest_id` previamente conocido; la reserva sin
huésped sigue siendo válida. Eso impide que `reservation-create-web` convierta los datos de
huésped introducidos por un gestor en una reserva operativa. El repositorio ya reutiliza
huéspedes por email normalizado durante la ingesta, pero el patrón `find_by_email -> add` tiene
una condición de carrera y no existe una constraint de unicidad por tenant/email.

Este change habilita la resolución estrictamente dentro del caso de uso de alta manual y
extrae la política común para que la ingesta no mantenga una segunda implementación. La
constraint UNIQUE y la reconciliación de duplicados históricos quedan para un hardening
posterior, porque el dominio actual no define una política automática de merge de identidad.

## What changes

Se introduce un servicio de aplicación compartido `ResolveOrCreateGuest`, con aislamiento por
tenant, email normalizado como único criterio automático de reutilización y lock transaccional
de PostgreSQL para serializar la resolución/creación concurrente. El alta manual podrá recibir
`guest_id` existente o una identidad de contacto; ambos caminos producirán el `guest_id` que
necesita la reserva y permanecerán en la UoW de la creación manual.

El cambio no crea un endpoint genérico de huéspedes, no hace matching por nombre o teléfono y
no fusiona datos históricos.

## Requirements

### R1 — Resolver por identidad de contacto

**As a** gestor, **I want** crear una reserva manual aportando la identidad de contacto del
huésped, **so that** la reserva quede vinculada a un `guest_id` sin gestionar Guests aparte.

Acceptance criteria:

1. WHEN una alta manual recibe un `guest_id` válido del tenant, THE SYSTEM SHALL reutilizarlo
   sin crear otro Guest.
2. WHEN una alta manual recibe un email no vacío, THE SYSTEM SHALL normalizarlo con la regla
   vigente (`trim` + `lower`) y reutilizar el Guest coincidente dentro del mismo tenant.
3. WHEN el email normalizado no coincide, THE SYSTEM SHALL crear un único Guest con los datos
   permitidos y vincular su id a la reserva.
4. IF el `guest_id` no pertenece al tenant o no existe, THEN THE SYSTEM SHALL responder con el
   error de dominio existente y no SHALL escribir la reserva.
5. WHEN se reutiliza un Guest existente por email normalizado, THE SYSTEM SHALL NOT actualizar
   silenciosamente su nombre, teléfono, idioma ni ningún otro dato con los valores recibidos en
   el alta manual; el request SHALL servir para resolver identidad, no para editar el Guest
   existente.

### R2 — Política explícita de matching

**As a** operador, **I want** que la resolución evite coincidencias ambiguas, **so that** no se
   mezclen identidades de huéspedes.

Acceptance criteria:

1. WHEN no hay email, THE SYSTEM SHALL not match automatically por nombre ni por teléfono.
2. WHEN no hay email y hay nombre válido, THE SYSTEM SHALL crear un Guest nuevo en cada alta
   que no aporte `guest_id`.
3. THE SYSTEM SHALL tratar email vacío o solo whitespace como ausencia y no SHALL persistirlo
   como identidad.
4. THE SYSTEM SHALL mantener teléfono e idioma como datos del Guest, no como claves de
   matching automático.
5. IF existen duplicados históricos con el mismo email normalizado dentro del tenant, THEN THE
   SYSTEM SHALL NOT fusionarlos ni reconciliarlos en este change, SHALL conservar una selección
   determinista compatible con el comportamiento existente del repositorio y SHALL evitar crear
   duplicados adicionales mediante el mecanismo concurrente.

### R3 — Concurrencia y reutilización compartida

**As a** sistema, **I want** serializar la resolución concurrente de una misma identidad,
**so that** dos altas simultáneas no creen duplicados adicionales por el race conocido.

Acceptance criteria:

1. WHEN dos transacciones del mismo tenant resuelven simultáneamente el mismo email
   normalizado, THE SYSTEM SHALL serializar el `find/create` mediante un lock transaccional
   determinista y ambas SHALL obtener el mismo Guest.
2. THE SYSTEM SHALL revisar los call sites actuales de creación/resolución de Guest y todos
   los writers existentes que utilicen la política de resolución por email SHALL pasar por el
   resolver compartido; `ReservationIngestor` SHALL quedar incluido explícitamente como writer
   conocido. Esta revisión SHALL limitarse a los writers existentes y no SHALL crear CRUD ni
   funcionalidades nuevas.
3. THE SYSTEM SHALL allow la serialización transaccional por `(tenant_id, normalized_email)`
   mediante una primitiva de infraestructura cuando sea necesaria, pero cualquier primitiva
   específica de PostgreSQL (`pg_advisory_xact_lock`, SQL u otra) SHALL quedar detrás de un
   port/adapter de infraestructura. `domain/` y `application/` SHALL NOT acoplarse directamente
   a PostgreSQL.
4. WHEN se ejecuta un alta manual con identidad de huésped, la resolución/creación del Guest,
   la creación de la Reservation y el evento `RESERVATION_CREATED_MANUAL` SHALL pertenecer a
   la misma UoW y a un único commit.
5. IF cualquiera de esas operaciones falla, THEN THE SYSTEM SHALL hacer rollback conjunto de
   Guest, Reservation y evento, sin dejar escrituras parciales.
6. THE SYSTEM SHALL retain tenant isolation in every lookup, lock key and write.

### R4 — Contrato manual compatible

**As a** consumidor de la API, **I want** conservar el camino actual de `guest_id` y disponer
**de** un bloque opcional de identidad, **so that** los clientes existentes no se rompan.

Acceptance criteria:

1. WHEN el request contiene `guest_id` sin `guest`, THE SYSTEM SHALL mantener el contrato y la
   respuesta actuales, vinculando ese huésped si existe en el tenant.
2. WHEN el request contiene `guest` sin `guest_id`, THE SYSTEM SHALL resolver o crear el Guest
   y devolver la reserva creada con el `guest_id` resuelto en su representación existente.
3. WHEN el request no contiene ni `guest_id` ni `guest`, THE SYSTEM SHALL considerarlo válido y
   crear la reserva sin huésped.
4. IF el request contiene simultáneamente `guest_id` y `guest`, THEN THE SYSTEM SHALL responder
   `422` usando el envelope de error/validación existente y no SHALL crear Guest ni Reservation.
5. WHEN existe `guest`, THE SYSTEM SHALL exigir `full_name`, aplicar `trim` y aceptar entre 1
   y 300 caracteres después del trim.
6. WHEN existe `guest.email`, THE SYSTEM SHALL tratarlo como opcional, aplicar `trim` +
   lowercase mediante la normalización vigente y tratar el resultado vacío como ausencia.
7. WHEN existe `guest.phone`, THE SYSTEM SHALL tratarlo como opcional y aplicar la normalización
   de teléfono existente.
8. WHEN existe `guest.preferred_language`, THE SYSTEM SHALL aceptar únicamente `es` o `en`;
   si no se aporta, THE SYSTEM SHALL usar `es` como valor por defecto.
9. IF `guest` no cumple cualquiera de las reglas anteriores o `guest_id` no existe en el tenant,
   THEN THE SYSTEM SHALL responder con el envelope de validación/error existente y no SHALL
   crear Guest ni Reservation.
10. THE SYSTEM SHALL publish the changed request/response models in OpenAPI and keep generated
    backend/frontend contract artifacts consistent.

### R5 — Alcance limitado y ausencia de merge implícito

**As a** responsable del dominio, **I want** limitar el cambio al alta manual, **so that** no se
   convierta en una capacidad genérica de gestión de huéspedes.

Acceptance criteria:

1. THE SYSTEM SHALL expose no generic Guest CRUD or guest-search surface as part of this
   change.
2. THE SYSTEM SHALL not automatically merge existing duplicate Guests or reassign their
   reservations/conversations.
3. THE SYSTEM SHALL document the absence of a database UNIQUE email constraint and the need
   for a separate, explicitly approved identity-hardening change.

## Out of scope

- Constraint UNIQUE funcional parcial sobre `(tenant_id, lower(trim(email)))`; se reserva para
  `guest-email-identity-hardening`.
- Inventario, reconciliación o merge automático de Guests duplicados existentes.
- CRUD genérico, búsqueda libre o pantalla de guest-management.
- Matching automático por nombre o teléfono.
- Cambios en Guest Portal, guest-link-delivery, documentos o legal registration.
- La interfaz de `reservation-create-web`, que consumirá este contrato en su propio change.

## Affected specs

- `sdd/specs/reservations.md`
- `sdd/specs/domain-foundation-core.md`
- `sdd/specs/guest-portal-api.md` (solo si el contrato compartido o sus invariantes requieren
  una aclaración; no se modifica la funcionalidad del portal)
- `sdd/specs/ingest.md` *(no existe aún — se creará al archivar, si la extracción de la política
  de ingesta necesita una spec propia)*
