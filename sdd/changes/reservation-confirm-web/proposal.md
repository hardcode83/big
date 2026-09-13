# Proposal: reservation-confirm-web

## Why

Una reserva creada desde `/reservations` nace `PENDING` para siempre desde la UI: el
backend ya admite `PATCH {"status": "CONFIRMED"}` y `PATCH {"payment_status": ...}` (sin
restricción de transición en el dominio), pero `EDITABLE_FIELDS` en el formulario de
edición excluye ambos campos a propósito
(`frontend/features/reservations/components/edit/edit-reservation-form.tsx:17-20`,
fijado por su propio test) y ningún control los dispara. La consecuencia es operativa:
ni `sim-advance` ni el `beat` de jobs de reloj mueven una reserva `PENDING`
(`sdd/specs/reservations.md` lo declara así), así que el ciclo completo del Hito 1
(alta → confirmación → sim-advance → check-in → limpieza) exige hoy un `PATCH` manual
por API — exactamente el mismo patrón que usa `seed-data-demo-extension`.

La entrada correspondiente del roadmap y su nota (`sdd/roadmap.md` y
`sdd/roadmap/reservation-confirm-web.md`) fijan el alcance, incluyendo la
investigación del 2026-09-12 contra la práctica real del sector (ventana de 24 h del
host en Airbnb/Booking "Request to Book", no ligada a la fecha de check-in;
arras/señal 20-30 % y aprobación manual en gestión directa, patrón Guesty/OwnerRez) y
la decisión de confirmación manual desacoplada del pago. El contrato OpenAPI actual
(`frontend/lib/api/generated/openapi.d.ts`) es la fuente de verdad del transporte y
`sdd/specs/reservations.md` la fuente de verdad de las reglas de negocio.

## What changes

La pantalla de detalle `/reservations/[id]` gana un botón «Confirmar reserva» visible
sólo cuando `status === "PENDING"` y el usuario tiene `MANAGE_RESERVATIONS`, que
dispara `PATCH {"status": "CONFIRMED"}` mediante el cliente API tipado existente. El
formulario de edición expone también `payment_status` (cuatro valores de
`PaymentStatus`) como campo editable más — sin lógica de negocio nueva, sin gate de
transición. La acción «Cancelar» ya existente se mantiene visible y operativa sobre
una `PENDING` igual que sobre una `CONFIRMED` (rechazar reutiliza `DELETE`, no añade un
segundo botón). La UI nunca ofrece un selector genérico con los siete
`ReservationStatus`: los cuatro que dispara la máquina de estados
(`CHECKED_IN_ESTIMATED`, `CHECKED_OUT_ESTIMATED`, `COMPLETED`, `NO_SHOW`) sólo los
alcanza el reloj, igual que ya dejó dicho `sim-advance`. Todo el flujo respeta i18n
ES/EN, accesibilidad mobile-first y los errores mapeados (`404`/`409`/`422`) por
`mutation-error-mapping.ts`.

## Requirements

### R1 — Confirmación manual de una reserva PENDING

**As a** manager, **I want** confirmar una reserva `PENDING` desde su detalle con un
único clic, **so that** la estancia arranque el reloj de estados sin recurrir a un
`PATCH` por API.

Acceptance criteria:

1. WHEN un usuario con `MANAGE_RESERVATIONS` abre `/reservations/[id]` sobre una
   reserva con `status === "PENDING"`, THE SYSTEM SHALL ofrecer un botón «Confirmar
   reserva» diferenciado del botón «Cancelar», claramente etiquetado y localizado
   en ES/EN.
2. WHEN el manager confirma, THE SYSTEM SHALL enviar
   `PATCH /api/v1/reservations/{id}` con `{"status": "CONFIRMED"}` mediante el
   cliente API tipado existente y SHALL invalidar el detalle y el listado afectados.
3. WHEN la reserva no está `PENDING` (ya `CONFIRMED`, `CANCELLED` o cualquier otro
   estado), THE SYSTEM SHALL ocultar el botón «Confirmar» y SHALL NOT exponer
   ningún otro mecanismo de cambio de `status` desde la UI.
4. WHEN el usuario no tiene `MANAGE_RESERVATIONS`, THE SYSTEM SHALL ocultar el
   botón «Confirmar» aunque la reserva esté `PENDING`.

### R2 — payment_status editable, desacoplado del gate

**As a** manager, **I want** anotar el estado de pago de la señal desde el mismo
formulario de edición, **so that** confirmar la reserva y dejar constancia de la
señal cobrada sea una sola visita al detalle.

Acceptance criteria:

1. WHEN el usuario con `MANAGE_RESERVATIONS` abre `/reservations/[id]`, THE SYSTEM
   SHALL exponer `payment_status` como campo editable con los cuatro valores de
   `PaymentStatus` (`PENDING`, `PARTIALLY_PAID`, `PAID`, `REFUNDED`), mostrando el
   valor actual del detalle como valor inicial.
2. WHEN el usuario envía el formulario con un `payment_status` distinto del actual,
   THE SYSTEM SHALL enviar únicamente ese campo en el `PATCH` (diff respecto al
   detalle cargado, igual que el resto del formulario) y SHALL actualizar tanto el
   detalle como el listado.
3. WHEN el manager envía un cambio de `payment_status` sin tocar `status`, THE
   SYSTEM SHALL NOT cambiar `status` ni SHALL exigir como precondición que
   `status === "CONFIRMED"`.
4. WHEN el canal de la reserva no es manual, THE SYSTEM SHALL deshabilitar
   `payment_status` según `INGEST_OWNED_FIELDS` o la política equivalente vigente y
   SHALL explicar el motivo de forma localizada.

### R3 — Rechazo reutiliza el cancelar existente

**As a** manager, **I want** rechazar una reserva `PENDING` desde la misma pantalla
con la acción «Cancelar» ya existente, **so that** no aparezca un segundo botón nuevo
para la misma operación semántica.

Acceptance criteria:

1. WHEN la reserva está en cualquier estado distinto de `CANCELLED` (incluido
   `PENDING`), THE SYSTEM SHALL ofrecer la acción «Cancelar» que ya entrega
   `reservation-create-web`.
2. WHEN el manager cancela una `PENDING`, THE SYSTEM SHALL llamar a `DELETE`
   (cancelación lógica, no borrado físico) y SHALL reflejar `status: "CANCELLED"` y
   el timeline resultante igual que para cualquier otra cancelación.
3. THE SYSTEM SHALL NOT añadir un botón «Rechazar» ni SHALL introducir un estado
   distinto de `CANCELLED` para representar el rechazo.

### R4 — Permisos, tenancy y errores

**As a** usuario del workspace, **I want** que las nuevas acciones respeten mi rol y
el aislamiento del backend, **so that** la confirmación y el registro de pago no
abran una vía de escritura indebida.

Acceptance criteria:

1. THE SYSTEM SHALL mantener la mirror de permisos en
   `frontend/lib/auth/permissions.ts` para que `MANAGE_RESERVATIONS` cubra
   «Confirmar» y el cambio de `payment_status`; sin ese permiso, los controles no se
   renderizan y las mutaciones no se envían.
2. WHEN una mutación está en curso (confirmación o edición con `payment_status`),
   THE SYSTEM SHALL impedir envíos duplicados, mantener el botón en estado
   `aria-busy="true"` y SHALL comunicar éxito o error de forma localizada, no
   dependiente sólo del color.
3. IF la API devuelve `404`, `409` o `422` al confirmar o al cambiar
   `payment_status`, THEN THE SYSTEM SHALL mostrar el error localizado sin presentar
   la operación como completada y SHALL conservar los valores locales del
   formulario.
4. WHEN se cambie de tenant o se invalide la sesión, THE SYSTEM SHALL invalidar las
   queries y mutaciones de reservations con las claves tenant-scoped existentes.

### R5 — Localización, contrato OpenAPI y verificación

**As a** manager que opera desde móvil, **I want** un flujo localizado, accesible y
verificable, **so that** la confirmación no introduzca regresiones en la suite ni
dependencias del idioma del navegador.

Acceptance criteria:

1. THE SYSTEM SHALL añadir todos los textos nuevos al namespace `reservations` en
   `frontend/locales/es/reservations.json` y `frontend/locales/en/reservations.json`,
   sin strings hardcodeadas en componentes.
2. THE SYSTEM SHALL mantener los DTOs y operaciones de `HttpReservationsSource`
   alineados con el contrato OpenAPI regenerado y SHALL pasar
   `cd frontend && npm run api:check`.
3. THE SYSTEM SHALL añadir tests colocated que cubran: visibilidad del botón
   «Confirmar» por estado y permiso, mutación `PATCH {status: "CONFIRMED"}`,
   edición de `payment_status` independiente de `status`, mapeo de errores
   `404`/`409`/`422`, e invariantes ES/EN.
4. THE SYSTEM SHALL verificar con los comandos de `sdd/project.md` desde el
   worktree aislado (`make up` para el stack, `cd frontend && npm test`,
   `cd frontend && npm run lint`, `docker compose exec backend uv run pytest`).

## Out of scope

- Validación de transiciones de `status` en el dominio: hoy cualquier `PATCH` con
  cualquier valor de `status` pasa; añadir esa guarda es candidata `[BE]` aparte.
- Pasarela de pago o cobro automático de la señal; `payment_status` se registra a
  mano, sin integración con Stripe/Redsys/etc.
- Auto-cancelación de una `PENDING` que lleva tiempo sin confirmarse; automatización
  futura no comprendida en esta entrada.
- Saldo restante / recordatorio de pago cerca del check-in — corresponde a
  `guest-scheduled-comms`, no a esta pantalla.
- Un evento de timeline `RESERVATION_CONFIRMED` propio; el design decide si añadirlo
  o usar `RESERVATION_UPDATED` con `metadata.changed`.
- Selector genérico con los siete `ReservationStatus` desde la UI; ofrecerlos
  falsificaría el timeline auditable.
- Cambios al shell compartido o extracción general de nuevos componentes fuera de
  lo necesario para esta pantalla.

## Affected specs

- `sdd/specs/reservations.md` — documentar la superficie frontend de la confirmación
  manual y su límite (sin gate de pago, sin selector de `status`), si procede al
  archivar.
- `sdd/specs/frontend-foundation.md` — recoger que `/reservations/[id]` ahora ofrece
  mutación de `status` por acción específica, no por selector genérico.
- `sdd/specs/frontend-api-contract-consumer.md` — registrar las operaciones `PATCH`
  con `status` y `payment_status` consumidas por esta feature, si procede al archivar.
