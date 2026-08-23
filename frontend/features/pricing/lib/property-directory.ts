/**
 * Resolving a raw property id to a readable identity (design D5, R2.8, R5.3).
 *
 * Adapted from `features/cleaning/lib/directory.ts`, and the adaptation is not
 * cosmetic. In `cleaning` a null id means «nobody is assigned» — an absence. Here
 * a `PricingRule` with `propertyId === null` means **the whole portfolio**, which
 * is a positive claim about scope (R5.3), so the shape is named `portfolio` and
 * the copy that renders it says «Toda la cartera», not «sin asignar». Only rules
 * reach that branch: a recommendation always names one property.
 *
 * There are **four** shapes and not two for the reason R2.8 gives: «catalog still
 * in flight» has to be distinguishable from «not in the catalog», or the window
 * before the catalog arrives gets painted as one of them and lies.
 *
 * A catalog that failed and a catalog that resolved without the id collapse into
 * the same `unavailable`: both mean the row still renders and the identity does
 * not. **The catalog's error never propagates to the view's `ErrorState`** (R2.8)
 * — the price, the day and the status have already arrived, and they are what the
 * screen is for.
 *
 * Not imported from `features/cleaning`: that would be a deep import into a
 * feature whose `index.ts` does not export it, and the null branch means something
 * different. Not extracted to a shared `lib/` either — the tree's own rule is to
 * extract at the **third** consumer, and this is the second (design D5).
 */
export type PropertyIdentity<T> =
  /** The rule applies to every property the tenant has (R5.3). */
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
  id: string | null,
  directory: PropertyDirectory<T>,
): PropertyIdentity<T> {
  if (id === null) {
    return { kind: "portfolio" };
  }
  const value = directory.index.get(id);
  if (value !== undefined) {
    return { kind: "resolved", value };
  }
  return directory.isPending ? { kind: "pending" } : { kind: "unavailable" };
}
