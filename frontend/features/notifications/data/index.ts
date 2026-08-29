import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpNotificationsSource } from "./http/http-notifications-source";

export type * from "./dto";

/**
 * The single composition point for the notifications data source (design D10, the
 * `features/incidents/data/index.ts` mould). Hooks and components resolve their source ONLY
 * through `getNotificationsDataSource`, so replacing the implementation is a one-line change
 * confined to this file.
 */
const { apiClient: notificationsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const notificationsDataSource = new HttpNotificationsSource(notificationsApiClient);

export function getNotificationsDataSource(): HttpNotificationsSource {
  return notificationsDataSource;
}
