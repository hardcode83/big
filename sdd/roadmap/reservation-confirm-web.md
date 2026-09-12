# reservation-confirm-web

[FE] **confirmar o rechazar una reserva `PENDING`, y registrar su señal de pago, desde
`/reservations/[id]`** — lo único que `reservation-create-web` dejó sin mover.

> Hito «MVP operable» 1 — *ciclo operativo completo desde el navegador* (auditoría del
> 2026-09-04, ampliada el 2026-09-12 al cerrar `reservation-create-web`). Sin esta pieza el
> ciclo del Hito 1 se demuestra hasta el alta, pero no arranca de verdad: una reserva directa
> nunca despega hacia el reloj de estados sin un `PATCH` manual por API.

## El hecho medido (2026-09-12)

`UpdateReservationRequest` (`backend/app/reservations/api/schemas.py:150-176`) acepta
`status: ReservationStatus | None` y `payment_status: PaymentStatus | None` sin restricción de
transición alguna en el dominio — `Reservation.update_details` (`domain/entities.py`) no valida
qué valores anteriores permiten cuáles siguientes, salvo el caso especial de `CANCELLED`
(`use_cases.py:299-309`: un `PATCH` que fija `status: CANCELLED` se trata como una cancelación
real y escribe `RESERVATION_CANCELLED`, no `RESERVATION_UPDATED`).

Pero **`EDITABLE_FIELDS`** en `frontend/features/reservations/components/edit/edit-reservation-form.tsx:17-20`
excluye `status`, `payment_status`, `cleaning_required`, `channel` y `guest_id` a propósito — el
propio test del formulario lo fija (`edit-reservation-form.test.ts:58`:
`.not.toEqual(expect.arrayContaining(["status", "payment_status", ...]))`). Es una decisión
explícita de `reservation-create-web`, no un olvido: su proposal lo deja escrito en «Out of
scope» — *"Confirmación automática al crear una reserva; la propuesta parte del estado inicial
`PENDING` y deja la forma exacta de cualquier acción posterior de estado para el design."* — y el
design que siguió no llegó a resolverla.

**Consecuencia**: una reserva creada desde `/reservations` nace y se queda `PENDING` para
siempre desde la UI. `sim-advance` y el `beat` de jobs de reloj sólo mueven reservas
`CONFIRMED` (`reservations.md`: *"el reloj no puede avanzar nunca una reserva `PENDING`"*), así
que hoy el ciclo completo (alta → confirmación → sim-advance → check-in → limpieza) exige al
menos un `curl`/`PATCH` manual, exactamente el mismo patrón que usa `seed-data-demo-extension`
para sus estancias sembradas.

## Por qué no es cosmético, y qué dice la práctica real del sector

Investigado el 2026-09-12 contra tres fuentes — plataformas OTA, software de gestión de alquiler
vacacional, y normativa española de consumo — antes de fijar el mecanismo, porque las dos
hipótesis iniciales (que confirma el huésped cerca de la fecha, o que la OTA obliga cuando
quedan semanas) resultaron **incorrectas**:

1. **Las OTA no confirman "cuando quedan pocas semanas"**: Airbnb "Request to Book" y
   Booking.com/Agoda "Book on Request" dan al **host** una ventana de **24 horas desde el
   momento de la reserva** — no ligada a la fecha de check-in — para aceptar o rechazar; si no
   responde, expira y se reembolsa. La mayoría de reservas OTA hoy son "Instant Book": se
   confirman al instante, sin ventana. Para cuando una reserva OTA llega a este sistema por
   sync/webhook del PMS, la OTA **ya resolvió** su propio ciclo — por eso
   `ReservationStatus.parse_ingested` **ya** por defecto confirma
   (`reservations/domain/entities.py`, comentario explícito). **Esto ya está bien modelado; el
   gap es sólo en el canal `DIRECT`/`MANUAL`.**
2. **El huésped no "confirma" la reserva cerca de la fecha.** Lo que sí ocurre cerca del
   check-in es un hito de **pago del saldo restante** (no de confirmación de estado) y el aviso
   de llegada — ambos cubiertos, cuando lleguen, por `guest-scheduled-comms`, no por esta
   entrada.
3. **La práctica real para reservas directas** (OwnerRez, Guesty) separa dos cosas: la reserva
   queda `Pending`/`Reserved` bloqueando el calendario, y pasa a `Confirmed` cuando el host la
   **aprueba manualmente** (patrón "Approve/decline a reservation" de Guesty) — a veces
   condicionado a que la señal se haya cobrado, a veces no. En España, la práctica de
   arras/señal (20-30% del total, vinculante bajo Código Civil art. 1454) es lo que convierte
   una reserva provisional en firme.

**Decisión tomada (2026-09-12, con el usuario)**: confirmación **manual y desacoplada** del
pago — un botón «Confirmar reserva» que el manager acciona con su propio criterio (llamada al
huésped, WhatsApp, lo que sea fuera del sistema), sin que `payment_status` la bloquee. Es el
patrón más fiel al resto del producto (ninguna otra pantalla del MVP condiciona una acción
humana a un estado de pago automático; no hay pasarela de pago integrada en el PRD) y el más
simple de verificar. Rechazar una reserva `PENDING` **reutiliza el `DELETE`/cancelar que ya
existe** — no hace falta un estado "rechazada" distinto de `CANCELLED`.

Junto a esto, se expone `payment_status` como campo editable en la misma pantalla (hoy tampoco
lo está, mismo hallazgo de exclusión deliberada) — no como gate, sino porque confirmar una
reserva directa va casi siempre de la mano de anotar que la señal llegó, y separarlo en un
change aparte sobre el mismo formulario cuesta más coordinación que la propia feature.

## Alcance

- **Botón «Confirmar»** en `/reservations/[id]`, visible sólo si `status === "PENDING"` y el
  usuario tiene `MANAGE_RESERVATIONS` (mismo permiso que el resto de mutaciones de esta
  pantalla). Al confirmar: `PATCH { status: "CONFIRMED" }`, invalida detalle y listado.
- **`payment_status` editable** en el mismo formulario de edición (`EDITABLE_FIELDS` lo suma),
  con las cuatro opciones de `PaymentStatus` (`PENDING`/`PARTIALLY_PAID`/`PAID`/`REFUNDED`) — sin
  lógica de negocio nueva, es un campo más del `PATCH` que el backend ya acepta.
- **Ningún selector genérico de `status`.** La UI **NUNCA** ofrece un desplegable con los 7
  valores de `ReservationStatus` — sólo dos acciones con nombre: «Confirmar» (`PENDING→CONFIRMED`)
  y «Cancelar» (ya existe, cualquier estado → `CANCELLED`). `CHECKED_IN_ESTIMATED`,
  `CHECKED_OUT_ESTIMATED`, `COMPLETED` y `NO_SHOW` los alcanza sólo la máquina de estados/reloj
  — ofrecerlos desde un formulario falsificaría el timeline auditable (mismo principio que
  citó `sim-advance` para blindarse a dev-only).

## Lo que decide y no es cosmético

1. **El backend no valida transiciones de `status` hoy.** `update_details` acepta cualquier
   valor sin comprobar el anterior — el único caso especial es `CANCELLED`
   (`use_cases.py:299-309`). Esta entrada **no** cierra ese hueco de dominio (sería `[BE]`,
   fuera de alcance); se limita a que la UI **nunca ofrezca** una transición que el dominio no
   validaría. Si en el futuro se ajusta la máquina de reservas para rechazar transiciones
   inválidas, esta pantalla no tiene que cambiar: ya sólo dispara las dos que son válidas.
2. **Qué evento de timeline deja «Confirmar».** Hoy un `PATCH` con `status: CONFIRMED` que no
   sea una cancelación cae en la rama `RESERVATION_UPDATED` genérica (`use_cases.py:315-319`);
   no hay un `RESERVATION_CONFIRMED` propio en `TimelineEventType`. El design decide si conviene
   uno nuevo (mismo criterio de vocabulario que dejó pendiente `pms-ingest-change-events`) o si
   `RESERVATION_UPDATED` con `metadata.changed` basta para el MVP. Recomendación: no añadir
   vocabulario nuevo sin necesidad — es backend, y esta entrada es `[FE]`.
3. **`payment_status` no dispara ningún efecto colateral hoy** (no hay
   `reconcile_owner_approvals_for_expenses` ni similar ligado a este campo, a diferencia de los
   gastos de `statements-web`) — es puramente informativo/de registro. Confirmarlo en el design
   antes de ofrecerlo como si activara algo.
4. **Un rechazo reutiliza `cancel()`, que es idempotente** (`use_cases.py:350-362`): no hace
   falta lógica nueva, sólo que el botón «Cancelar» ya existente siga apareciendo sobre una
   reserva `PENDING` igual que sobre una `CONFIRMED` (comprobar que el design de
   `reservation-create-web` no lo restringió por estado).
5. **i18n y el mismo patrón de error-mapping** que el resto de la pantalla
   (`error-mapping.ts`, `mutation-error-mapping.ts`) — un `404`/`409`/`422` en la confirmación
   se trata igual que en el resto de mutaciones de `/reservations/[id]`.

## Fuera de alcance

- **Validación de transiciones de `status` en el dominio** (candidata `[BE]` aparte si se
  decide cerrarla; hoy cualquier `PATCH` con cualquier valor de `status` pasa).
- **Pasarela de pago o cobro automático de la señal.** `payment_status` se registra a mano;
  no hay integración con Stripe/Redsys/etc. en el PRD.
- **Auto-cancelación de una reserva `PENDING` que lleva tiempo sin confirmarse.** Patrón real
  (Guesty bloquea 12-72h, OwnerRez permite auto-cancelar por días) pero es automatización nueva
  que el MVP no pide — candidata futura si se necesita, no esta entrada.
- **Saldo restante / recordatorio de pago cerca del check-in** — es `guest-scheduled-comms`,
  no esto: aquella es la entrega automática al huésped; esta es el registro manual del manager.
- **Un evento de timeline `RESERVATION_CONFIRMED` propio** — ver punto 2 de arriba; se decide
  en `/sdd:design`, no aquí.
- **Rediseñar `cancel()`/`DELETE`** — se reutiliza tal cual.

## Verificación que el change debe dejar hecha

Crear una reserva directa desde `/reservations` (nace `PENDING`) → confirmarla desde
`/reservations/[id]` sin salir del navegador → `sim-advance` la mueve por el reloj de estados
sin ningún `curl` de por medio. Y, en el mismo formulario, marcar `payment_status: PARTIALLY_PAID`
y comprobar que persiste sin afectar a `status`.
