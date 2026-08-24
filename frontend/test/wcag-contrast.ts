/**
 * WCAG 2.x contrast arithmetic, for the audit R1.6 requires.
 *
 * Separate from the CSS parsing helpers because this is the part that has to be
 * *right* rather than merely convenient: every threshold decision in the palette
 * rests on these three functions, and one of them models something a browser
 * does rather than something the spec defines (see `compositeOver`).
 */

/** sRGB channel → linear light. WCAG 2.x definition, not a gamma approximation. */
function toLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function parseHex(hex: string): [number, number, number] {
  const h = hex.trim().replace(/^#/, "");
  if (!/^[0-9a-f]{6}$/i.test(h)) {
    throw new Error(`not a 6-digit hex colour: ${hex}`);
  }
  return [
    Number.parseInt(h.slice(0, 2), 16),
    Number.parseInt(h.slice(2, 4), 16),
    Number.parseInt(h.slice(4, 6), 16),
  ];
}

/** Relative luminance, per WCAG 2.x. */
export function relativeLuminance(hex: string): number {
  const [r, g, b] = parseHex(hex);
  return (
    0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b)
  );
}

/** Contrast ratio, per WCAG 2.x. Always ≥ 1, order of arguments irrelevant. */
export function contrastRatio(a: string, b: string): number {
  const la = relativeLuminance(a);
  const lb = relativeLuminance(b);
  const lighter = Math.max(la, lb);
  const darker = Math.min(la, lb);
  return (lighter + 0.05) / (darker + 0.05);
}

/**
 * What a browser actually paints for Tailwind v4's opacity modifier, e.g.
 * `bg-state-success/15`.
 *
 * Tailwind compiles that to `color-mix(in oklab, var(--color-state-success) 15%,
 * transparent)`. Mixing a colour with `transparent` yields that same colour at
 * alpha 0.15 — the hue is preserved, because a mix against transparent in a
 * premultiplied space scales alpha rather than shifting chroma — and the browser
 * then composites that translucent layer over whatever is behind it. So the
 * arithmetic that matters is ordinary source-over alpha compositing in sRGB,
 * which is what this does.
 *
 * Grounded in the spec rather than in agreement between implementations.
 * CSS Color 5 interpolates with **premultiplied** alpha, and `transparent` is
 * transparent black at alpha 0, whose premultiplied components are all zero.
 * So `color-mix(in oklab, C 15%, transparent)` gives alpha = 0.15·1 + 0.85·0 =
 * 0.15 and premultiplied components 0.15·C, which un-premultiply to exactly C:
 * hue and chroma preserved, no darkening toward black, and the choice of `oklab`
 * is irrelevant to the result for a mix against transparent. The browser then
 * paints that translucent layer with ordinary source-over — Cr = Cs·As +
 * Cb·(1−As) on gamma-encoded sRGB — which is what this computes.
 *
 * Stated that way deliberately. This function's earlier justification was that
 * it reproduced design.md's independently-derived table across thirty values,
 * which is weaker than it sounds: two implementations of the same *wrong* model
 * would also have agreed. The agreement is still a useful cross-check, and it
 * holds — but the spec is the reason.
 *
 * Residual deviation: the oklab round-trip and 8-bit rounding below, worth at
 * most ~±0.02 on a ratio, plus a small shift when compositing on a wide-gamut
 * display. Immaterial against the palette's tightest margin.
 *
 * `alpha` is a fraction, not a percentage: pass 0.15 for `/15`.
 */
export function compositeOver(
  foreground: string,
  backdrop: string,
  alpha: number,
): string {
  if (alpha < 0 || alpha > 1) {
    throw new Error(`alpha must be a fraction in [0,1], got ${alpha}`);
  }
  const fg = parseHex(foreground);
  const bg = parseHex(backdrop);
  const channels = fg.map((f, i) => Math.round(f * alpha + bg[i] * (1 - alpha)));
  return `#${channels.map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}

/** WCAG 2.2 AA thresholds. */
export const AA_NORMAL_TEXT = 4.5;
/** Large text (≥18.66px bold or ≥24px) and non-text UI components (1.4.11). */
export const AA_LARGE_TEXT_AND_UI = 3;

/** Two decimals, the precision design.md's table is stated in. */
export function round2(value: number): number {
  return Math.round(value * 100) / 100;
}
