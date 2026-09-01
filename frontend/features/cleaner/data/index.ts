import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpCleanerSource } from "./http-cleaner-source";

export type * from "./dto";
export type { CleanerDataSource } from "./cleaner-source";

/**
 * The single composition point for the cleaner's data source (design D1).
 *
 * UI and hooks resolve their source ONLY through `getCleanerDataSource`, so
 * swapping the implementation is a one-line change confined to this file.
 * Tests inject a `CleanerDataSource` fake without touching this module.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory — the same wiring `tech-app` D2 and `incidents-web` D1 settled
 * on.
 */
const { apiClient: cleanerApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const cleanerDataSource = new HttpCleanerSource(cleanerApiClient);

export function getCleanerDataSource(): HttpCleanerSource {
  return cleanerDataSource;
}