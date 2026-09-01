import type { BlockedTransitionPage, BlockedTransitionSummary } from "../dto";
import type { StallsDataSource } from "../stalls-source";

/**
 * ASSUMPTION / DEBT (dashboard-mock): in-memory implementation of
 * `StallsDataSource`. It mimics the real API's observable behaviour — async
 * resolution, the §23 pagination envelope, and tenant isolation (an empty
 * fixtures set for an unknown tenant) — so the UI and hooks that depend only
 * on the interface behave identically once `HttpStallsSource` replaces this
 * class.
 *
 * The mock honours `page`/`perPage` (design D9) because a mock that ignored
 * them would let a test "prove" a pagination that never happens.
 */

const TENANT_FIXTURES: Record<
  string,
  readonly BlockedTransitionSummary[]
> = {
  // Tenant A — two properties with three stalls across them (R2.5).
  "tenant-a": [
    {
      property_id: "redes11",
      property_code: "REDES11",
      reservation_id: "r-1",
      trigger: "CHECKIN_TIME_REACHED",
      blocking_state: "AWAITING_CLEANING",
      due_since: "2026-08-23T13:00:00Z",
    },
    {
      property_id: "redes11",
      property_code: "REDES11",
      reservation_id: "r-2",
      trigger: "CHECKIN_WINDOW_OPENED",
      blocking_state: "MAINTENANCE_REQUIRED",
      due_since: "2026-08-22T13:00:00Z",
    },
    {
      property_id: "pajaritos8",
      property_code: "PAJARITOS8",
      reservation_id: "r-3",
      trigger: "CHECKOUT_TIME_REACHED",
      blocking_state: "CRITICAL_INCIDENT",
      due_since: "2026-08-21T13:00:00Z",
    },
  ],
};

function notFound(tenantId: string): Error {
  return new Error(`Tenant ${tenantId} has no stalls fixture`);
}

function paginate(
  items: readonly BlockedTransitionSummary[],
  page: number,
  perPage?: number,
): BlockedTransitionPage {
  if (perPage === undefined) {
    return {
      data: [...items],
      total: items.length,
      page: 1,
      per_page: items.length,
      total_pages: items.length === 0 ? 0 : 1,
    };
  }
  const totalPages = Math.ceil(items.length / perPage);
  const start = (page - 1) * perPage;
  return {
    data: items.slice(start, start + perPage),
    total: items.length,
    page,
    per_page: perPage,
    total_pages: totalPages,
  };
}

export class MockStallsSource implements StallsDataSource {
  // `tenantId` is accepted to honour the contract; the fixture set is keyed by
  // tenant so a test can prove isolation without an HTTP round trip.
  listBlockedTransitions(
    tenantId: string,
    page: number,
    perPage?: number,
  ): Promise<BlockedTransitionPage> {
    const items = TENANT_FIXTURES[tenantId];
    if (!items) {
      return Promise.reject(notFound(tenantId));
    }
    return Promise.resolve(paginate(items, page, perPage));
  }
}