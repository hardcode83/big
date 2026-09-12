# Tasks: reservation-confirm-web

## 1. Mutation hook and error-mapping <!-- hard -->

- [ ] 1.1 Add `useConfirmReservation` to `frontend/features/reservations/hooks/use-reservations.ts`; payload fijo `{ status: "CONFIRMED" }`, `retry: false`, awaited tenant-scoped invalidation through the existing `invalidateReservationQueries` helper (list, detail, `property-timeline`) [R1, R4]
- [ ] 1.2 Extend `ReservationMutationOperation` union with `"confirm"` in `frontend/features/reservations/lib/mutation-error-mapping.ts`; exporta el nuevo tipo [R4]
- [ ] 1.3 Add colocated test for `useConfirmReservation` (payload fijo, sin retries, invalidación tras `onSettled`) y otro para `reservationMutationErrorKey` con `operation="confirm"` cubriendo `ApiError` 401/403/404/409/422, 5xx y error de red [R1, R4]
- [ ] 1.4 Export `useConfirmReservation` from `frontend/features/reservations/index.ts` [R1]

## 2. Confirm button and visibility gating

- [ ] 2.1 Add the «Confirmar reserva» button in `ReservationManageActions` (`frontend/features/reservations/components/detail/reservation-detail-view.tsx`), gated by `detail.status === "PENDING"` y `canManage`, `variant="default"`, con `aria-busy` y `disabled` mientras la mutación está pendiente [R1, R4]
- [ ] 2.2 On click, call `useConfirmReservation().mutate({ reservationId: detail.id })`; on success, announce localised status with `<p role="status" aria-live="polite">`; on error, render the message via `reservationMutationErrorKey(error, "confirm")` reusing the existing `AlertDialog` pattern only if needed for accessibility review (single-click path is the default per D1) [R1, R4, R5]
- [ ] 2.3 Extend `frontend/features/reservations/components/detail/reservation-detail-view.test.tsx` con casos para: botón visible sólo cuando `status === "PENDING"` y `MANAGE_RESERVATIONS`; oculto para `CONFIRMED`/`CANCELLED`/cualquier otro estado; oculto sin permiso; clic dispara PATCH con `{ status: "CONFIRMED" }`; éxito anuncia el mensaje localizado; error 404/409/422 muestra el mensaje localizado de `mutation.errors.confirm.*` [R1, R4]

## 3. paymentStatus editable in the edit form

- [ ] 3.1 Extend `EDITABLE_FIELDS` in `frontend/features/reservations/components/edit/edit-reservation-form.tsx` con `"paymentStatus"`; añadir las entradas `paymentStatus → paymentStatus` en `DETAIL_TO_FORM` y `paymentStatus → payment_status` en `API_FIELDS`; `formValue` formatea el `PaymentStatus` como cadena (los enums ya llegan como string); `normalizeValue` deja la cadena tal cual (no es número ni fecha) [R2]
- [ ] 3.2 Render un `<select>` controlado de cuatro opciones (`PENDING`/`PARTIALLY_PAID`/`PAID`/`REFUNDED`) usando las etiquetas existentes `paymentStatuses.*` del namespace `reservations`; valor inicial igual al `detail.paymentStatus`; estilo consistente con el resto del formulario (mismo `fieldClass`, mismo `aria-invalid`/`aria-describedby` cuando aplique) [R2, R5]
- [ ] 3.3 Verificar que `buildReservationPatch` envía `payment_status` cuando el valor seleccionado difiere del cargado, sin tocar `status`; añadir un test colocated que cubre: (a) sin cambios en `payment_status`, el campo no aparece en el patch; (b) cambio de `payment_status`, el campo aparece en el patch como `payment_status` snake_case y ningún otro [R2]
- [ ] 3.4 Actualizar la aserción existente en `frontend/features/reservations/components/edit/edit-reservation-form.test.ts:58` que excluía `payment_status` del patch: el nuevo contrato permite `payment_status` cuando difiere pero sigue excluyendo `status`/`cleaning_required`/`channel`/`guest_id` [R2, R4]

## 4. Localisation (ES/EN)

- [ ] 4.1 Add `confirm.label`, `confirm.submitting`, `confirm.success` en `frontend/locales/es/reservations.json` y `frontend/locales/en/reservations.json` [R1, R5]
- [ ] 4.2 Add `edit.fields.paymentStatus` en ambos locales (las etiquetas `paymentStatuses.*` ya existen) [R2, R5]
- [ ] 4.3 Add the seven keys `mutation.errors.confirm.{session,forbidden,notFound,conflict,validation,server,network}` en ambos locales, reflejando la semántica de la operación (`«No tienes permiso para confirmar esta reserva»`, etc.) [R4, R5]

## 5. Verification

- [ ] 5.1 Run the focused reservations tests: `cd frontend && npm test -- features/reservations` [R1, R2, R3, R4, R5]
- [ ] 5.2 Run the full frontend suite: `cd frontend && npm test` [R1, R2, R3, R4, R5]
- [ ] 5.3 Run frontend lint: `cd frontend && npm run lint` [R4, R5]
- [ ] 5.4 Run the API contract guard: `cd frontend && npm run api:check` (la fuente HTTP no se toca y `UPDATE_FIELDS` ya lista `status` y `payment_status`, así que el contrato generado sigue válido) [R5]
- [ ] 5.5 Browser flow end-to-end: crear una reserva directa desde `/reservations` (nace `PENDING`) → confirmarla desde `/reservations/[id]` con un clic → `sim-advance` la mueve por el reloj de estados; en el mismo formulario, marcar `payment_status: PARTIALLY_PAID` y comprobar que persiste sin afectar a `status`; verificar ES/EN en cada paso y una ruta de error de mutación (`409`/`422` simulado) preservando los valores del formulario <!-- manual --> [R1, R2, R3, R4, R5]

## Implementation Notes

<!-- Append-only, written by the implementer of each section for the next one:
     decisions taken, names chosen, gotchas found. One bullet each, no prose. -->
