import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpReservationsSource } from "./http/http-reservations-source";

export type * from "./dto";

/**
 * The single composition point for the reservations data source (design D1).
 * UI and hooks resolve their source ONLY through `getReservationsDataSource`,
 * so swapping the implementation is a one-line change confined to this file.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory.
 */
const { apiClient: reservationsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const reservationsDataSource = new HttpReservationsSource(reservationsApiClient);

export function getReservationsDataSource(): HttpReservationsSource {
  return reservationsDataSource;
}
