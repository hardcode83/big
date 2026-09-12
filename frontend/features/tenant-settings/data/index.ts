import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpTenantSettingsSource } from "./http/http-tenant-settings-source";

export type * from "../dto";

/**
 * The single composition point for the tenant-settings data source (design
 * D1, mirroring `features/platform/data/index.ts` and
 * `features/reservations/data/index.ts`). `data/index.ts` is the **only**
 * place that instantiates `HttpTenantSettingsSource`; UI and hooks resolve
 * their source ONLY through `getTenantSettingsDataSource()`, so swapping the
 * implementation is a one-line change confined to this file.
 *
 * The client uses the same-origin API proxy by default; authentication
 * headers and one-shot refresh are shared with the auth provider through the
 * session client factory.
 */
const { apiClient: tenantSettingsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const tenantSettingsDataSource = new HttpTenantSettingsSource(
  tenantSettingsApiClient,
);

export function getTenantSettingsDataSource(): HttpTenantSettingsSource {
  return tenantSettingsDataSource;
}
