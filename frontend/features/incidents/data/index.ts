import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpIncidentsSource } from "./http/http-incidents-source";

export type * from "./dto";

/**
 * The single composition point for the incidents data source (design D1).
 * UI and hooks resolve their source ONLY through `getIncidentsDataSource`,
 * so swapping the implementation is a one-line change confined to this file.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory.
 */
const { apiClient: incidentsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const incidentsDataSource = new HttpIncidentsSource(incidentsApiClient);

export function getIncidentsDataSource(): HttpIncidentsSource {
  return incidentsDataSource;
}