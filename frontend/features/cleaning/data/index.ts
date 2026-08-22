import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import type { CleaningDataSource } from "./cleaning-source";
import { HttpCleaningSource } from "./http/http-cleaning-source";

export type { CleaningDataSource } from "./cleaning-source";
export type * from "./dto";

/**
 * The single composition point for the cleaning view's data source (design D1).
 * Components and hooks resolve their source ONLY through here, which is what lets
 * the component tests inject a double.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory.
 */
const { apiClient: cleaningApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const cleaningDataSource: CleaningDataSource = new HttpCleaningSource(
  cleaningApiClient,
);

export function getCleaningDataSource(): CleaningDataSource {
  return cleaningDataSource;
}
