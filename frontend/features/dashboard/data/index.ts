import type { DashboardDataSource } from "./dashboard-source";
import { MockDashboardSource } from "./mock/mock-dashboard-source";

export type { DashboardDataSource } from "./dashboard-source";
export type * from "./dto";

/**
 * The single composition point for the dashboard's data source (proposal R3).
 * UI and hooks resolve their source ONLY through here, so swapping the
 * implementation is a one-line change confined to this file.
 *
 * DEBT (dashboard-web): today it returns `MockDashboardSource`. When the
 * aggregate dashboard backend exists, return `HttpDashboardSource` (routed
 * through `lib/api`) here — no UI, hook, or query-key change required.
 */
const dashboardDataSource: DashboardDataSource = new MockDashboardSource();

export function getDashboardDataSource(): DashboardDataSource {
  return dashboardDataSource;
}
