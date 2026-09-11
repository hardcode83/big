import { ApiError } from "@/lib/api";

/** Localizable mutation error keys; server messages/details never cross this boundary. */
export type ReservationMutationErrorKey =
  | "reservations:mutation.errors.session"
  | "reservations:mutation.errors.forbidden"
  | "reservations:mutation.errors.notFound"
  | "reservations:mutation.errors.conflict"
  | "reservations:mutation.errors.validation"
  | "reservations:mutation.errors.server"
  | "reservations:mutation.errors.network";

export function reservationMutationErrorKey(
  error: unknown,
): ReservationMutationErrorKey {
  if (!(error instanceof ApiError)) {
    return "reservations:mutation.errors.network";
  }
  switch (error.status) {
    case 401:
      return "reservations:mutation.errors.session";
    case 403:
      return "reservations:mutation.errors.forbidden";
    case 404:
      return "reservations:mutation.errors.notFound";
    case 409:
      return "reservations:mutation.errors.conflict";
    case 422:
      return "reservations:mutation.errors.validation";
    default:
      return error.status >= 500
        ? "reservations:mutation.errors.server"
        : "reservations:mutation.errors.network";
  }
}
