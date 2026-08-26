/**
 * The one badge palette in the tree, extracted at its third consumer (design
 * D22 of `pricing-web`). `features/cleaning/lib/task-status.ts` wrote the
 * trigger for itself — duplicate «until a third consumer appears» — and
 * `features/pricing` is it.
 *
 * A tone is a semantic bucket, not a state: each consumer keeps its own
 * `Record<ItsEnum, Tone>` because what «amber» means belongs to that enum's
 * lifecycle. Only the Tailwind strings are shared.
 */
export type Tone = "green" | "blue" | "amber" | "red" | "gray";

/**
 * One string per tone, no `dark:` variant — design D6.
 *
 * The background and the border are the `--state-*` anchor composited over
 * whatever surface is behind the badge (`bg-state-success/15` resolves to
 * `color-mix(in oklab, var(--color-state-success) 15%, transparent)`), so both
 * themes come out of the same string: what changes is the token, not the class.
 * That is what closes R6.5 — the previous strings carried `dark:` variants, and
 * Tailwind's `dark:` follows `prefers-color-scheme`, never our `data-theme`
 * attribute, so a badge on a page forced dark kept painting its light variant.
 *
 * The text needs its own token: measured, `--state-success` on its own 15% tint
 * gives 2.3:1 in light. `--state-*-text` exists for that and nothing else.
 *
 * The shape of these strings is load-bearing, not stylistic. The WCAG register
 * in `app/globals.contrast.test.ts` measures the badge pairs by *parsing* them
 * — the 15%, the 40% and the `-text` suffix are read from here — so a change to
 * the alphas or the suffix moves the audit with it instead of leaving it green
 * about a badge the app no longer paints.
 */
const BADGE_CLASS: Record<Tone, string> = {
  green: "bg-state-success/15 text-state-success-text border-state-success/40",
  blue: "bg-state-info/15 text-state-info-text border-state-info/40",
  amber: "bg-state-warning/15 text-state-warning-text border-state-warning/40",
  red: "bg-state-error/15 text-state-error-text border-state-error/40",
  gray: "bg-state-neutral/15 text-state-neutral-text border-state-neutral/40",
};

/**
 * Frozen, for the reason `features/pricing/lib/recommendation-status.ts` gives
 * about its own table and the section-7 panel pointed out applies here with more
 * force: this is a module-level singleton that **every** badge in the app indexes,
 * so one stray write would change what every later badge renders. Its consumer
 * `features/incidents/lib/severity-tone.ts` was already frozen while the palette
 * it reads was not.
 */
export const TONE_BADGE_CLASS: Readonly<Record<Tone, string>> =
  Object.freeze(BADGE_CLASS);
