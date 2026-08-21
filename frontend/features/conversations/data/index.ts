import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import type { ConversationsDataSource } from "./conversations-source";
import { HttpConversationsSource } from "./http/http-conversations-source";

export type { ConversationsDataSource } from "./conversations-source";
export type * from "./dto";

/**
 * The single composition point for the inbox's data source (R7.1). Components,
 * hooks and stores resolve their source ONLY through here.
 *
 * Same-origin API proxy by default; auth headers and one-shot refresh are shared
 * with the auth provider through the session client factory.
 */
const { apiClient: conversationsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});
const conversationsDataSource: ConversationsDataSource =
  new HttpConversationsSource(conversationsApiClient);

export function getConversationsDataSource(): ConversationsDataSource {
  return conversationsDataSource;
}
