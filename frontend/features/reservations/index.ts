// Barrel for the reservations feature. The App Router pages import the two
// view components from here; the data layer and the hooks are also
// re-exported so a single `@/features/reservations` import brings the whole
// feature into scope.
export { ReservationsView } from "./components/list/reservations-view";
export { ReservationsFilters } from "./components/list/reservations-filters";
export { CreateReservationForm } from "./components/create/create-reservation-form";
export { ReservationDetailView } from "./components/detail/reservation-detail-view";
export { EditReservationForm, buildReservationPatch, initialEditValues } from "./components/edit/edit-reservation-form";
export {
  useCancelReservation,
  useCreateReservation,
  useReservation,
  useReservations,
  useUpdateReservation,
} from "./hooks/use-reservations";
export type {
  CancelReservationVariables,
  UpdateReservationVariables,
} from "./hooks/use-reservations";
export { reservationsKeys } from "./hooks/query-keys";
export { mapReservationsError } from "./lib/error-mapping";
export {
  reservationMutationErrorKey,
} from "./lib/mutation-error-mapping";
export type {
  ReservationMutationErrorKey,
} from "./lib/mutation-error-mapping";
export { getReservationsDataSource } from "./data";
export type * from "./data";
