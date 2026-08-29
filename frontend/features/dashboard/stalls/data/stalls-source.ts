import type { BlockedTransitionPage } from "./dto";

/**
 * The dashboard card's data-access boundary for blocked transitions (proposal
 * `blocked-transitions-web` R1.1, D1).
 *
 * One method, one reason: the card reads the first page of the
 * `/api/v1/blocked-transitions` envelope and slices it by `property_id`
 * in memory. The interface keeps that promise — adding a second method
 * would let the card drift back to a per-property N+1, which design D1
 * rejects.
 *
 * `tenantId` is explicit at the boundary so the tenant-scoped query keys and
 * the HTTP implementation stay honest. It is provided from the session
 * context at the call site.
 */
export interface StallsDataSource {
  /**
   * The first page of blocked transitions for the tenant. The mock honours
   * `page`/`perPage` (design D9) so tests can prove pagination, and the HTTP
   * implementation forwards them verbatim.
   */
  listBlockedTransitions(
    tenantId: string,
    page: number,
    perPage?: number,
  ): Promise<BlockedTransitionPage>;
}