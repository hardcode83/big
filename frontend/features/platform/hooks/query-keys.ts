import type { QueryKey } from "@/lib/query/query-keys";

/**
 * Query keys for the platform feature (design D4).
 *
 * Deliberately NOT built on `lib/query/query-keys.ts`'s `tenantScopedKey`: that helper's
 * contract throws on an empty `tenantId` (`if (!tenantId) throw ...`), and `SUPER_ADMIN` — the
 * only role that reaches this feature — has none (`super-admin-identity`). The platform
 * surface is the first caller for whom "no tenant" is the correct, not an error, state.
 *
 * A future reader should not "fix" this omission by threading a fake tenant id through
 * `tenantScopedKey`: the right fix, if this ever needs generalizing, is a helper that accepts
 * `tenantId: string | null`, not relaxing the non-empty invariant every other caller relies on.
 */
export const platformKeys = {
  tenantsList: (page: number, perPage: number): QueryKey => [
    "platform",
    "tenants-list",
    page,
    perPage,
  ],
} as const;
