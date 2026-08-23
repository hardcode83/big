import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpPropertiesSource } from "./http/http-properties-source";

export type * from "./dto";

/**
 * The single composition point for the properties data source (design D4).
 * UI and hooks resolve their source ONLY through `getPropertiesDataSource`, so
 * swapping the implementation is a one-line change confined to this file.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory — identical wiring to `features/reservations`.
 */
const { apiClient: propertiesApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const propertiesDataSource = new HttpPropertiesSource(propertiesApiClient);

export function getPropertiesDataSource(): HttpPropertiesSource {
  return propertiesDataSource;
}
