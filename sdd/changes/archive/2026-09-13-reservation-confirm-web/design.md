# Design: reservation-confirm-web

## Context

El backend ya admite `PATCH {"status": "CONFIRMED"}` y `PATCH {"payment_status": ...}`
sin restricción de transición
(`backend/app/reservations/api/schemas.py:150-176`); un PATCH con
`status: CONFIRMED` no es cancelación y cae en la rama `RESERVATION_UPDATED` genérica
(`backend/app/reservations/use_cases.py:315-319`). No hay un `RESERVATION_CONFIRMED`
propio en `TimelineEventType`. La UI, sin embargo, excluye ambos campos de
`EDITABLE_FIELDS` a propósito
(`frontend/features/reservations/components/edit/edit-reservation-form.tsx:17-20`,
fijado por su propio test) y ningún control los dispara. El cliente HTTP ya filtra
`status` y `payment_status` en `UPDATE_FIELDS`
(`frontend/features/reservations/data/http/http-reservations-source.ts:38-49`), así
que la fuente no necesita cambios — basta con que el frontend deje de excluirlos y
añada una acción específica para confirmar. `reservation-create-web` ya dejó en su
propuesta que «la confirmación automática al crear queda fuera de alcance y la forma
exacta de cualquier acción posterior de estado para el design».

## Decisions

### D1 — Acción «Confirmar» con un clic, sin diálogo intermedio

El botón «Confirmar reserva» se renderiza dentro de `ReservationManageActions`
(`frontend/features/reservations/components/detail/reservation-detail-view.tsx`),
al lado de `EditReservationForm` y del botón «Cancelar». Es un `Button` simple
(`variant="default"`) que al pulsarlo envía el `PATCH` y muestra estado pendiente
(`aria-busy`, texto «Confirmando…») y éxito localizado. **No** usa `AlertDialog`.

Razones: R1.1 fija «un único clic»; el botón sólo aparece cuando `status === "PENDING"`
y el usuario tiene `MANAGE_RESERVATIONS`, así que el riesgo de clic accidental está
acotado por la guardia de estado — un clic que sale mal no es destructivo y el
backend puede revertirlo con un segundo PATCH o cancelando. La diferenciación visual
es por variant (`default` vs `destructive`) y por etiqueta, suficiente para
separarlo del «Cancelar» existente.

Alternativas rechazadas: añadir un `AlertDialog` (alarga un paso que la práctica del
sector tampoco exige — Guesty/OwnerRez aprueban con un solo clic) y reusar el
formulario de edición para confirmar (mezcla semánticas y rompería la lectura del
timeline).

### D2 — Hook dedicado `useConfirmReservation` que envuelve `updateReservation`

Se añade `useConfirmReservation` en
`frontend/features/reservations/hooks/use-reservations.ts`. Su `mutationFn` llama a
`getReservationsDataSource().updateReservation(tenantId, reservationId, { status: "CONFIRMED" })`
— el payload es fijo, no acepta argumentos del llamante. `retry: false` y la misma
invalidación que `useUpdateReservation` (prefijo de listado, detalle, y
`property-timeline`) a través de `invalidateReservationQueries`.

Razones: encapsula el payload cerrado para que ningún componente pueda disparar
por error otro `status` distinto de `CONFIRMED`; reusa `updateReservation` en lugar
de añadir un método HTTP nuevo (la fuente no necesita cambios); alinea con el patrón
`useCancelReservation` ya existente.

Alternativas rechazadas: reusar `useUpdateReservation({status: "CONFIRMED"})` desde
los componentes (deja el `status` configurable y rompe la invariante «sólo el botón
Confirmar dispara CONFIRMED»), y añadir `confirmReservation` a
`HttpReservationsSource` (duplica transporte: el backend no expone un endpoint
distinto de PATCH).

### D3 — Visibilidad del botón por estado y permiso, sin tocar permisos

El botón «Confirmar» se renderiza dentro de `ReservationManageActions` (que ya está
detrás de `canManage = useHasPermission("MANAGE_RESERVATIONS")`); la condición
adicional es `detail.status === "PENDING"`. Cuando la reserva sale de `PENDING`
(`CONFIRMED`/`CANCELLED`/cualquier otro), el botón no aparece — React Query
invalidará el detalle y el siguiente render lo ocultará.

`MANAGE_RESERVATIONS` ya está declarado en `frontend/lib/auth/permissions.ts`
(`reservation-create-web` lo añadió) y cubre esta acción: confirmar muta la
reserva igual que editar o cancelar. No se añade permiso nuevo, no se añade rol
nuevo.

Alternativa rechazada: un permiso `CONFIRM_RESERVATIONS` aparte (rompe el principio
de «un permiso por superficie mutante», y nadie en la práctica distingue entre
«editar» y «confirmar» un `PENDING`).

### D4 — `payment_status` editable, sin gate y sin lógica nueva

`EDITABLE_FIELDS` en
`frontend/features/reservations/components/edit/edit-reservation-form.tsx:17-20`
suma `"paymentStatus"`. Las tablas `DETAIL_TO_FORM` (`paymentStatus → paymentStatus`)
y `API_FIELDS` (`paymentStatus → payment_status`) se amplían con la misma entrada;
`formValue` formatea como el resto (string vacío para `null`/`undefined`), y
`normalizeValue` deja la cadena tal cual (no es número ni fecha). El `<select>` de
cuatro opciones (`PENDING`, `PARTIALLY_PAID`, `PAID`, `REFUNDED`) usa
`paymentStatuses.*` de `frontend/locales/{es,en}/reservations.json` como labels.

`buildReservationPatch` envía únicamente `payment_status` cuando el valor del
formulario difiere del cargado (mismo diff que el resto). El backend acepta el
campo y `useUpdateReservation` ya lo invalida; no hace falta lógica de negocio en
el frontend ni método HTTP nuevo.

`paymentStatus` no entra en `INGEST_OWNED_FIELDS`, así que para canales no manuales
sigue editable. La nota del roadmap recomienda esta postura (editable por canal
directo para anotar la señal cobrada) — **esta decisión se registra como `assumed`
en `BLOCKED.md`** porque la nota dejó la cuestión abierta y el design tomó la
opción recomendada sin preguntar; viaja con el PR para que el usuario la vete si
lo desea. Si en el futuro `pms-ingest-change-events` decide meter `payment_status`
en `INGEST_OWNED_FIELDS` para canales OTA, se ajusta en una entrada aparte.

Alternativas rechazadas: ofrecer `payment_status` sólo en reservas `CONFIRMED`
(el proposal lo prohíbe — R2.3 explicita que no es gate), meter `paymentStatus` en
`INGEST_OWNED_FIELDS` desde esta entrada (rompe la separación `pms-ingest-change-events`
vs `reservation-confirm-web`), y serializar el cambio como PATCH por sí solo fuera
del diff (rompe el principio «diff contra el detalle» que ya fija
`buildReservationPatch`).

### D5 — Cancelar sigue siendo el rechazo, sin cambios funcionales

R3 reutiliza el botón «Cancelar» ya existente: la acción DELETE está activa para
`PENDING` igual que para `CONFIRMED` (`useCancelReservation` no filtra por estado y
el backend `cancel()` es idempotente para reservas no terminales —
`backend/app/reservations/use_cases.py:350-362`). El componente `AlertDialog`
existente ya muestra el diálogo; basta con verificar que el botón se renderiza
también para `PENDING` (lo hace, porque la única guarda hoy es `canManage`, no el
estado).

No se añade botón «Rechazar», no se añade estado nuevo, no se modifica
`useCancelReservation`. Si el `AlertDialog` actual resulta ambiguo para `PENDING`,
se ajusta el texto del diálogo en el mismo namespace `cancel.*` de los locales.

Alternativa rechazada: añadir un segundo botón «Rechazar» con semántica idéntica a
«Cancelar» (duplica UI y diluye la decisión de R3 — «un solo botón para la misma
operación semántica»).

### D6 — `RESERVATION_UPDATED` cubre el evento de timeline; sin nuevo vocabulario

La mutación de confirmación cae en la rama genérica
(`use_cases.py:315-319`) que escribe una nueva entrada `RESERVATION_UPDATED` en la
tabla de timeline (no se modifica la fila existente). Esta entrada es `[FE]` y
añadir un nuevo `TimelineEventType` cruza al backend — fuera de alcance por
propuesta y por nota de roadmap («no añadir vocabulario nuevo sin necesidad»).
Si en el futuro el panel de revisión detecta que «confirmar» debería tener su
propio evento, se introduce en una entrada `[BE]` aparte.

Alternativa rechazada: proponer un `RESERVATION_CONFIRMED` para distinguir el
evento de «se confirmó» de «se editó cualquier campo» (cambio backend no
justificado por el MVP; el `metadata.changed` del timeline ya indica qué cambió).

### D7 — i18n, accesibilidad y error-mapping, mismo patrón que cancelar

Los textos nuevos viven en el namespace `reservations`:

- `confirm.label` («Confirmar reserva»), `confirm.submitting` («Confirmando…»),
  `confirm.success` («Reserva confirmada correctamente. Estado: Confirmada.»).
- `edit.fields.paymentStatus` («Estado de pago»), consumido por el `<label>` del
  nuevo control.
- `paymentStatuses.*` ya existe en ambos locales (`PENDING`/`PAID`/
  `PARTIALLY_PAID`/`REFUNDED`).

Los errores de la mutación de confirmación pasan por
`reservationMutationErrorKey(error, "confirm")` (operación nueva en el union
`"create" | "edit" | "cancel" | "confirm"`), con su propio namespace
`mutation.errors.confirm.*` en los locales — las siete claves (`session`/
`forbidden`/`notFound`/`conflict`/`validation`/`server`/`network`) reflejadas
para que un 403 diga «No tienes permiso para confirmar esta reserva» en vez de
«para editar».

Accesibilidad: el botón usa `aria-busy` mientras la mutación está pendiente y
`disabled` mientras está pendiente; el éxito se anuncia con `<p role="status"
aria-live="polite">` (mismo patrón que `cancelAnnouncement` ya existente).

Alternativa rechazada: reusar `mutation.errors.edit.*` para la confirmación
(deciría «No tienes permiso para editar esta reserva» al fallar un confirm —
texto engañoso para la operación real).

### D8 — Permisos, tests colocated, comandos de verificación

- `MANAGE_RESERVATIONS` ya cubre `Confirmar` y el cambio de `payment_status`; sin
  cambios en `frontend/lib/auth/permissions.ts`.
- Tests colocated:
  - `edit-reservation-form.test.ts` extiende la aserción actual sobre
    `EDITABLE_FIELDS` para verificar que `paymentStatus` está dentro y que el diff
    envía `payment_status` cuando cambia.
  - Nuevo `reservation-detail-view.test.tsx` (extensión) cubre visibilidad del
    botón «Confirmar» por estado (`PENDING` lo muestra, `CONFIRMED`/`CANCELLED` lo
    ocultan) y por permiso.
  - Nuevo `use-confirm-reservation.test.tsx` cubre la mutación (payload fijo,
    invalidación tras `onSettled`, sin retries).
- Verificación: `cd frontend && npm test`, `cd frontend && npm run lint`,
  `cd frontend && npm run api:check` (la fuente HTTP no cambia y `UPDATE_FIELDS`
  ya lista `status` y `payment_status`, así que el contrato generado sigue
  válido). El backend no se toca, así que `docker compose exec backend uv run
  pytest` corre sin cambios.

## Requirement coverage

- R1 (confirmación): D1 (UX del botón), D2 (hook dedicado), D3 (visibilidad por
  estado y permiso), D7 (i18n/accesibilidad), D8 (tests).
- R2 (`payment_status` editable): D4 (suma al formulario y al diff), D7 (locale),
  D8 (test).
- R3 (rechazo reutiliza cancelar): D5 (no se añade botón nuevo).
- R4 (permisos, tenancy, errores): D2 (invalidación tenant-scoped vía
  `invalidateReservationQueries`), D3 (mirror de permisos sin cambios),
  D7 (error-mapping con namespace `edit.*`), D8 (tests).
- R5 (i18n, OpenAPI, verificación): D7 (locales ES/EN), D8 (api:check y comandos
  de `sdd/project.md`).

## Affected files

| Area | Files | Change |
|---|---|---|
| Hooks | `frontend/features/reservations/hooks/use-reservations.ts` | añade `useConfirmReservation`; exporta en `index.ts` |
| Detail view | `frontend/features/reservations/components/detail/reservation-detail-view.tsx` | añade botón «Confirmar» en `ReservationManageActions`, gated por `status === "PENDING"` |
| Edit form | `frontend/features/reservations/components/edit/edit-reservation-form.tsx` | suma `paymentStatus` a `EDITABLE_FIELDS`, `DETAIL_TO_FORM`, `API_FIELDS`; render del `<select>` de cuatro valores |
| Edit form tests | `frontend/features/reservations/components/edit/edit-reservation-form.test.ts` | extender aserción sobre `EDITABLE_FIELDS`; añadir caso de diff con `payment_status` |
| Detail view tests | `frontend/features/reservations/components/detail/reservation-detail-view.test.tsx` | añadir caso de visibilidad del botón «Confirmar» por estado y por permiso |
| Hook tests | `frontend/features/reservations/hooks/use-confirm-reservation.test.tsx` (nuevo) | cubre payload fijo, invalidación, sin retries |
| Locales ES | `frontend/locales/es/reservations.json` | añade `confirm.*` (label/submitting/success), `edit.fields.paymentStatus`, `mutation.errors.confirm.*` (siete claves) |
| Locales EN | `frontend/locales/en/reservations.json` | añade `confirm.*` (label/submitting/success), `edit.fields.paymentStatus`, `mutation.errors.confirm.*` (siete claves) |
| Error mapping | `frontend/features/reservations/lib/mutation-error-mapping.ts` | extiende `ReservationMutationOperation` con `"confirm"` |
| Barrel | `frontend/features/reservations/index.ts` | exporta `useConfirmReservation` |

## Data & interfaces

Sin cambios de esquema, sin migración, sin endpoints nuevos. El transporte HTTP
existente (`PATCH /api/v1/reservations/{id}`) ya acepta los dos campos. La fuente
`http-reservations-source.ts` no se toca: `UPDATE_FIELDS` ya lista
`status` (línea 47) y `payment_status` (línea 44).

Tipo nuevo en frontend: ninguno — `UpdateReservationInput` ya cubre ambos campos
vía `Omit<components["schemas"]["UpdateReservationRequest"], never>`. El
`useConfirmReservation` introduce un wrapper que restringe el input a
`{ status: "CONFIRMED" }`.

## Risks & mitigations

- **Clic accidental de Confirmar**: el botón sólo aparece cuando `status === "PENDING"`
  y el usuario tiene permiso; el cambio se revierte con un PATCH posterior o
  cancelando. No se necesita `AlertDialog`.
- **`payment_status` editable en canales PMS**: no se mete en `INGEST_OWNED_FIELDS`
  por la práctica real (señal cobrada a veces fuera del PMS); si `pms-ingest-change-events`
  decide lo contrario, se ajusta en una entrada aparte.
- **Cambios de contrato OpenAPI**: la fuente no se toca y `api:check` se ejecuta
  como gate en el workflow; un fallo del check se ve antes de PR.
- **Suite frontend en Docker**: los dos fallos de rutas documentados en
  `sdd/project.md` reaparecen al re-crear el contenedor; se prepara el contenedor
  con los `docker compose cp`/`mkdir` declarados antes de interpretar esos
  rojos como regresiones.
- **`RESERVATION_UPDATED` demasiado genérico**: aceptable por MVP. Si el panel de
  revisión detecta ambigüedad, el cambio a `RESERVATION_CONFIRMED` propio entra en
  una entrada `[BE]` aparte (D6).

## Open questions

- **`paymentStatus` editable en canales no manuales** — el roadmap deja la cuestión
  abierta. D4 toma la opción recomendada (editable para todos los canales, no en
  `INGEST_OWNED_FIELDS`) **registrada como `assumed` en `BLOCKED.md`**; viaja con
  el PR para que el usuario la vete. La alternativa (mover `paymentStatus` a
  `INGEST_OWNED_FIELDS` y deshabilitarlo en canales OTA) requiere coordinarse con
  `pms-ingest-change-events` y queda fuera de esta entrada.

No hay otras preguntas que cambien requisitos. Los tres «loose mentions» que
`suggest` señaló (`guest-scheduled-comms`, `pms-ingest-change-events`,
`statements-web`) son referencias de contexto, no dependencias funcionales — la
nota del roadmap lo deja escrito y esta entrada no depende de ninguno.
