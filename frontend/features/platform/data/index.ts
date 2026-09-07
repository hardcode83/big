import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpPlatformSource } from "./http/http-platform-source";

export type * from "../dto";

/**
 * The single composition point for the platform data source (design D3, mirroring
 * `features/conversations` D1). `data/index.ts` is the **only** place that instantiates
 * `HttpPlatformSource`; UI and hooks resolve their source ONLY through
 * `getPlatformDataSource()`, so swapping the implementation is a one-line change confined to
 * this file.
 *
 * There is no `PlatformDataSource` interface and no mock source (design D3): nothing
 * pre-existing depended on a mock, and the backend already exists (sections 1-3).
 *
 * The client uses the same-origin API proxy by default; authentication headers and one-shot
 * refresh are shared with the auth provider through the session client factory.
 */
const { apiClient: platformApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const platformDataSource = new HttpPlatformSource(platformApiClient);

export function getPlatformDataSource(): HttpPlatformSource {
  return platformDataSource;
}
