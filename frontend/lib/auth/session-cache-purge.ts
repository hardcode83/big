import { getQueryClient } from "@/lib/query/query-client";

/**
 * Purges every entry of the singleton `QueryClient` — query cache, mutation
 * cache, and the non-reactive client state. Called from `AuthProvider` at the
 * four identity transition points (logout, login, refresh failure, session
 * expiration) so a subsequent user in the same tab cannot read cached data
 * from the previous one. Returns `void` because `QueryClient.clear()` is
 * synchronous and infallible — the local cleanup is unconditional, mirroring
 * the in-memory token store.
 */
export function purgeSessionCache(): void {
  getQueryClient().clear();
}
