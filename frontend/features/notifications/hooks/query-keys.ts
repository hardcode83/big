import { tenantScopedKey, type QueryKey } from "@/lib/query/query-keys";

import type { NotificationFilters } from "../data";

/**
 * Tenant- AND user-scoped query keys for the notifications resources (design D12).
 *
 * `tenantScopedKey` guarantees the `['tenant', tenantId, …]` prefix, and here that is not
 * enough on its own: a manager and a cleaner share a tenant and do not share an inbox, so the
 * user id is part of the key. `purgeSessionCache()` already empties the whole `QueryClient` at
 * the four identity transitions (R3.4), so this is the second line rather than the first — and
 * the one that survives somebody adding a fifth transition and forgetting to purge.
 *
 * The `prefix` builders exist for invalidation (R5.4): a mutation invalidates the family, not
 * the one page it happens to know about, so a page-2-with-a-filter entry is refetched too.
 * Precedent: `pricingKeys.recommendationsPrefix`.
 */
/**
 * The key a notifications query carries while there is no resolved session.
 *
 * It exists because two rules meet: `tenantScopedKey` throws on an empty tenant on purpose
 * ("a missing tenant is a programming error, not a silently-global cache entry"), and design
 * D16 requires the bell to render inside the field shells while the guard is still resolving.
 * A query holding this key is always `enabled: false`, so it never fetches and the entry never
 * holds anybody's data — which is what keeps it from being the silently-global entry
 * `tenantScopedKey` refuses to build.
 */
export const ANONYMOUS_NOTIFICATIONS_KEY: QueryKey = ["notifications-no-session"];

export const notificationsKeys = {
  unread: (tenantId: string, userId: string): QueryKey =>
    tenantScopedKey(tenantId, "notifications-unread", userId),
  listPrefix: (tenantId: string, userId: string): QueryKey =>
    tenantScopedKey(tenantId, "notifications-list", userId),
  list: (
    tenantId: string,
    userId: string,
    filters: NotificationFilters = {},
  ): QueryKey => tenantScopedKey(tenantId, "notifications-list", userId, filters),
} as const;
