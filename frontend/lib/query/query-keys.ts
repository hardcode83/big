/**
 * Multi-tenant query-key convention (design D11). Every tenant-scoped resource
 * key begins with `['tenant', tenantId, ...]`, so a global or cross-tenant key
 * cannot be produced by accident. This change defines only the shape — no
 * concrete resources, endpoints, queries, or prefetch exist yet.
 */
export type QueryKey = readonly unknown[];

/**
 * Builds a tenant-scoped query key. `tenantId` is mandatory and non-empty; a
 * missing tenant is a programming error, not a silently-global cache entry.
 */
export function tenantScopedKey(
  tenantId: string,
  resource: string,
  ...scope: readonly unknown[]
): QueryKey {
  if (!tenantId) {
    throw new Error("tenantScopedKey requires a non-empty tenantId");
  }
  if (!resource) {
    throw new Error("tenantScopedKey requires a non-empty resource");
  }
  return ["tenant", tenantId, resource, ...scope];
}
