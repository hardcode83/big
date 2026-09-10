import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpApprovalsSource } from "./http/http-approvals-source";

export type * from "./dto";

/**
 * The single composition point for the approvals data source (design D9/D10,
 * mirroring `features/incidents/data/index.ts`'s D1). UI and hooks resolve
 * their source ONLY through `getApprovalsDataSource`, so swapping the
 * implementation is a one-line change confined to this file.
 *
 * The client uses the same-origin API proxy by default; authentication
 * headers and one-shot refresh are shared with the auth provider through the
 * session client factory.
 */
const { apiClient: approvalsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const approvalsDataSource = new HttpApprovalsSource(approvalsApiClient);

export function getApprovalsDataSource(): HttpApprovalsSource {
  return approvalsDataSource;
}
