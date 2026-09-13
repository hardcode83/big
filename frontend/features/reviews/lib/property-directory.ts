/**
 * Resolving a raw property id to a readable identity (design D6, R2.8, R5.3).
 *
 * Copy of `features/pricing/lib/property-directory.ts`. The reviews list always
 * carries a `propertyId` (R1.5 of the backend spec, never `null`), so the
 * `portfolio` branch — which `pricing-web` uses to render whole-portfolio rules —
 * is never reached from this feature. It is kept here on purpose: the type
 * matches `pricing`'s, the tests cover the same four shapes, and the rule
 * `extract at the third consumer` is what would move it to `lib/` once reviews
 * itself becomes that third consumer (design D6, rejected).
 *
 * There are **four** shapes and not two for the reason R2.8 gives: «catalog
 * still in flight» has to be distinguishable from «not in the catalog», or the
 * window before the catalog arrives gets painted as one of them and lies.
 *
 * A catalog that failed and a catalog that resolved without the id collapse
 * into the same `unavailable`: both mean the row still renders and the identity
 * does not. **The catalog's error never propagates to the view's `ErrorState`**
 * (R2.8) — the review, the channel, the rating and the date have already
 * arrived, and they are what the screen is for.
 */
export type PropertyIdentity<T> =
  /** The rule applies to every property the tenant has (R5.3, unused here). */
  | { kind: "portfolio" }
  /** The catalog is still in flight — neutral marker, no identity text. */
  | { kind: "pending" }
  /** Catalog settled (resolved or failed) and this id is not in it (R2.8). */
  | { kind: "unavailable" }
  | { kind: "resolved"; value: T };

export interface PropertyDirectory<T> {
  index: ReadonlyMap<string, T>;
  isPending: boolean;
}

/** Indexes a catalog by id. An absent catalog (in flight or failed) gives an empty index. */
export function buildPropertyDirectory<T extends { id: string }>(
  entries: readonly T[] | undefined,
): Map<string, T> {
  return new Map((entries ?? []).map((entry) => [entry.id, entry]));
}

export function resolvePropertyIdentity<T>(
  id: string,
  directory: PropertyDirectory<T>,
): PropertyIdentity<T> {
  const value = directory.index.get(id);
  if (value !== undefined) {
    return { kind: "resolved", value };
  }
  return directory.isPending ? { kind: "pending" } : { kind: "unavailable" };
}