/**
 * The one badge palette in the tree, extracted at its third consumer (design
 * D22 of `pricing-web`). `features/cleaning/lib/task-status.ts` wrote the
 * trigger for itself — duplicate «until a third consumer appears» — and
 * `features/pricing` is it. The two live copies were identical string for
 * string, so the move carries no behaviour change and no test may need editing.
 *
 * A tone is a semantic bucket, not a state: each consumer keeps its own
 * `Record<ItsEnum, Tone>` because what «amber» means belongs to that enum's
 * lifecycle. Only the Tailwind strings are shared.
 */
export type Tone = "green" | "blue" | "amber" | "red" | "gray";

export const TONE_BADGE_CLASS: Record<Tone, string> = {
  green:
    "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950 dark:text-emerald-200 dark:border-emerald-800",
  blue: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950 dark:text-blue-200 dark:border-blue-800",
  amber:
    "bg-amber-100 text-amber-900 border-amber-200 dark:bg-amber-950 dark:text-amber-200 dark:border-amber-800",
  red: "bg-red-100 text-red-800 border-red-200 dark:bg-red-950 dark:text-red-200 dark:border-red-800",
  gray: "bg-muted text-muted-foreground border-border",
};
