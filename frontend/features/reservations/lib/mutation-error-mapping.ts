import { ApiError } from "@/lib/api";

/** Localizable mutation error keys; server messages/details never cross this boundary. */
export type ReservationMutationErrorKey =
  `reservations:mutation.errors.${"create" | "edit" | "cancel"}.${"session" | "forbidden" | "notFound" | "conflict" | "validation" | "server" | "network"}`;

export type ReservationMutationOperation = "create" | "edit" | "cancel";

export function reservationMutationErrorKey(
  error: unknown,
  operation: ReservationMutationOperation = "create",
): ReservationMutationErrorKey {
  let reason: "session" | "forbidden" | "notFound" | "conflict" | "validation" | "server" | "network";
  if (!(error instanceof ApiError)) reason = "network";
  else switch (error.status) {
    case 401:
      reason = "session";
      break;
    case 403:
      reason = "forbidden";
      break;
    case 404:
      reason = "notFound";
      break;
    case 409:
      reason = "conflict";
      break;
    case 422:
      reason = "validation";
      break;
    default:
      reason = error.status >= 500 ? "server" : "network";
  }
  return `reservations:mutation.errors.${operation}.${reason}` as ReservationMutationErrorKey;
}
