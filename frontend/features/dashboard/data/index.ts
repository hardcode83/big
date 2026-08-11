import type { DashboardDataSource } from "./dashboard-source";
import { createAuthenticatedClients } from "@/lib/api/authenticated-client";
import { HttpDashboardSource } from "./http/http-dashboard-source";

export type { DashboardDataSource } from "./dashboard-source";
export type * from "./dto";

/**
 * The single composition point for the dashboard's data source (proposal R3).
 * UI and hooks resolve their source ONLY through here, so swapping the
 * implementation is a one-line change confined to this file.
 *
 * The client uses the same-origin API proxy by default; authentication headers
 * and one-shot refresh are shared with the auth provider through the session
 * client factory.
 */
const { apiClient: dashboardApiClient } = createAuthenticatedClients({
  apiBaseUrl: "",
});
const dashboardDataSource: DashboardDataSource = new HttpDashboardSource(
  dashboardApiClient,
);

export function getDashboardDataSource(): DashboardDataSource {
  return dashboardDataSource;
}
