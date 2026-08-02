import { ApiError } from "@/lib/api";

import type { DashboardDataSource } from "../dashboard-source";
import type {
  PaginatedResponse,
  PropertyDashboardCard,
  PropertyDetail,
  TimelineEntry,
  TimelineFilters,
} from "../dto";
import {
  MOCK_DASHBOARD_CARDS,
  MOCK_PROPERTY_DETAILS,
  MOCK_PROPERTY_TIMELINES,
} from "./fixtures";

/**
 * ASSUMPTION / DEBT (dashboard-web): in-memory implementation of
 * `DashboardDataSource` backed by fixed fixtures. It mimics the real API's
 * observable behaviour — async resolution, the §23 pagination envelope, and a
 * §23 not-found error (thrown as `ApiError`, exactly what `lib/api` produces for
 * a 404) — so the UI and hooks that depend only on the interface behave
 * identically once `HttpDashboardSource` replaces this class.
 */
function singlePage<T>(items: readonly T[]): PaginatedResponse<T> {
  return {
    data: [...items],
    total: items.length,
    page: 1,
    per_page: items.length,
    total_pages: items.length === 0 ? 0 : 1,
  };
}

function notFound(propertyId: string): ApiError {
  return new ApiError({
    code: "NOT_FOUND",
    message: `Property ${propertyId} not found`,
    status: 404,
  });
}

function matchesFilters(entry: TimelineEntry, filters: TimelineFilters): boolean {
  if (filters.eventType && entry.eventType !== filters.eventType) return false;
  if (filters.severity && entry.severity !== filters.severity) return false;
  if (filters.actorType && entry.actorType !== filters.actorType) return false;
  if (filters.from && entry.occurredAt < filters.from) return false;
  if (filters.to && entry.occurredAt > filters.to) return false;
  return true;
}

export class MockDashboardSource implements DashboardDataSource {
  // `tenantId` is accepted to honour the contract; the single-tenant dev fixture
  // set is returned regardless (real tenant scoping is enforced by the backend).
  getDashboardCards(
    _tenantId: string,
  ): Promise<PaginatedResponse<PropertyDashboardCard>> {
    return Promise.resolve(singlePage(MOCK_DASHBOARD_CARDS));
  }

  getPropertyDetail(
    _tenantId: string,
    propertyId: string,
  ): Promise<PropertyDetail> {
    const detail = MOCK_PROPERTY_DETAILS[propertyId];
    if (!detail) {
      return Promise.reject(notFound(propertyId));
    }
    return Promise.resolve(detail);
  }

  getPropertyTimeline(
    _tenantId: string,
    propertyId: string,
    filters: TimelineFilters = {},
  ): Promise<PaginatedResponse<TimelineEntry>> {
    const entries = MOCK_PROPERTY_TIMELINES[propertyId];
    if (!entries) {
      return Promise.reject(notFound(propertyId));
    }
    const filtered = entries.filter((entry) => matchesFilters(entry, filters));
    return Promise.resolve(singlePage(filtered));
  }
}
