import type { ApiClient } from "@/lib/api";

import type { StallsDataSource } from "../stalls-source";
import type { BlockedTransitionPage } from "../dto";

/**
 * HTTP implementation of `StallsDataSource` against
 * `GET /api/v1/blocked-transitions` (proposal D2).
 *
 * The contract declares six fields and travels in `snake_case`; the dashboard
 * DTO already mirrors them via the alias on `BlockedTransitionSummary`
 * (`data/dto.ts`). Mapping is therefore a no-op at the field level, but
 * `blocked_transition` would still hit a `PropertyDashboardCard` consumer
 * without one — we cast through `unknown` only at the page envelope
 * boundary, where the page's `data` array has the same shape the generated
 * `BlockedTransitionPageResponse` publishes.
 */
export class HttpStallsSource implements StallsDataSource {
  constructor(private readonly client: ApiClient) {}

  async listBlockedTransitions(
    _tenantId: string,
    page: number,
    perPage?: number,
  ): Promise<BlockedTransitionPage> {
    const query: Record<string, number | undefined> = {
      page,
      per_page: perPage,
    };
    const response = await this.client.request(
      "/api/v1/blocked-transitions",
      { query },
    );
    // `BlockedTransitionPage` is the same shape as
    // `components["schemas"]["BlockedTransitionPageResponse"]` (openapi.d.ts:946)
    // — pagination envelope, six-field items. The DTO re-exports the item
    // alias so the page can be cast through `unknown` at this single boundary.
    return response as unknown as BlockedTransitionPage;
  }
}