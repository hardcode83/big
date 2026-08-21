/**
 * Resolving a raw id to a readable identity (design D5, R2.1–R2.4).
 *
 * The result has **four** shapes, not two, and the reason is R2.3: "unassigned"
 * has to be distinguishable from "we could not load this". With only those two,
 * the window in which the catalog has not arrived yet gets painted as one of them
 * and lies. So the interval gets its own shape.
 *
 * A catalog that failed and a catalog that resolved without the id collapse into
 * the same `unavailable`: both mean the row still renders and the identity does
 * not (R2.4). The catalog's error never propagates to the view's `ErrorState`.
 */
export type Identity<T> =
  /** The task carries no cleaner at all (R2.3). */
  | { kind: "unassigned" }
  /** The catalog is still in flight — neutral marker, no identity text. */
  | { kind: "pending" }
  /** Catalog settled (resolved or failed) and this id is not in it (R2.4). */
  | { kind: "unavailable" }
  | { kind: "resolved"; value: T };

export interface Directory<T> {
  index: ReadonlyMap<string, T>;
  isPending: boolean;
}

/** Indexes a catalog by id. An absent catalog (in flight or failed) gives an empty index. */
export function buildDirectory<T extends { id: string }>(
  entries: readonly T[] | undefined,
): Map<string, T> {
  return new Map((entries ?? []).map((entry) => [entry.id, entry]));
}

export function resolveIdentity<T>(
  id: string | null,
  directory: Directory<T>,
): Identity<T> {
  if (id === null) {
    return { kind: "unassigned" };
  }
  const value = directory.index.get(id);
  if (value !== undefined) {
    return { kind: "resolved", value };
  }
  return directory.isPending ? { kind: "pending" } : { kind: "unavailable" };
}
