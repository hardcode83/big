import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpConversationsSource } from "./http/http-conversations-source";

export type * from "./dto";

/**
 * The single composition point for the conversations data source (design D1).
 * `data/index.ts` is the **only** place that instantiates
 * `HttpConversationsSource`; UI and hooks resolve their source ONLY through
 * `getConversationsDataSource`, so swapping the implementation is a one-line
 * change confined to this file.
 *
 * There is no `ConversationsDataSource` interface and no
 * `MockConversationsSource` (D1): the backend exists since `messaging-ai`,
 * there is no UI pre-existing that depended on a mock, and the precedent of
 * `incidents-web` D1 and `reservations-web` D1 explicitly discard the
 * `dashboard-web` seam pattern.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory.
 */
const { apiClient: conversationsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const conversationsDataSource = new HttpConversationsSource(conversationsApiClient);

export function getConversationsDataSource(): HttpConversationsSource {
  return conversationsDataSource;
}