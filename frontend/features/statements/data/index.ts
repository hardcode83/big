import {
  createAuthenticatedClients,
  notifySessionExpired,
} from "@/lib/api/authenticated-client";

import { HttpStatementsSource } from "./http/http-statements-source";
import type { StatementsDataSource } from "./statements-source";

export type * from "./dto";
export type { StatementsDataSource } from "./statements-source";

const { apiClient: statementsApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
  onSessionExpired: notifySessionExpired,
});

const statementsDataSource: StatementsDataSource = new HttpStatementsSource(
  statementsApiClient,
);

export function getStatementsDataSource(): StatementsDataSource {
  return statementsDataSource;
}
