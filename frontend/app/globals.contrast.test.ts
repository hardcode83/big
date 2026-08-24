import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { TONE_BADGE_CLASS, type Tone } from "@/lib/ui/status-tone";
import { readCss, themeBlocks } from "@/test/css-tokens";
import {
  AA_LARGE_TEXT_AND_UI,
  AA_NORMAL_TEXT,
  compositeOver,
  contrastRatio,
  round2,
} from "@/test/wcag-contrast";

/**
 * The contrast audit R1.6 requires, as a test rather than as a table (design
 * D11).
 *
 * R1.6: «IF un par fondo/texto de cualquiera de los dos temas no alcanza el
 * contraste WCAG 2.2 AA (4.5:1 texto normal, 3:1 texto grande y elementos de
 * interfaz), THEN THE SYSTEM SHALL corregirlo antes de darse por entregado, y la
 * comprobación SHALL quedar registrada con su ratio medido por par.»
 *
 * Two halves, and the second is why this is a test:
 *   · the threshold half is the assertions below;
 *   · «registrada con su ratio medido por par» is the table this file PRINTS.
 *     A markdown table in design.md ages the moment someone retouches a hex; a
 *     test that recomputes from `globals.css` cannot.
 *
 * It has to be bespoke because the obvious tool cannot do it: `getA11yViolations`
 * in `test/render.tsx` disables the `color-contrast` rule on purpose — «Colour-
 * contrast needs real rendering; jsdom can't compute it reliably» — so axe is
 * structurally unable to cover this. Playwright could, and `npx playwright test`
 * does not exist in this project yet (it arrives with `hardening-release`).
 */

const CSS = readCss(join(__dirname, "globals.css"));
const { light: LIGHT, darkMedia: DARK } = themeBlocks(CSS);

/**
 * The surfaces a foreground can land on. `background`, `surface` and
 * `surface-high` are the three declared in design §Paleta; `muted` is included
 * because `bg-muted` is a real backdrop in this codebase, and leaving it out
 * would make the audit narrower than the app.
 *
 * Worth recording, because two reviewers reached different numbers from it:
 * design.md's stated `state-*` range of «4.21-8.67» is the THREE-surface range;
 * including `muted` moves the floor to 3.81 (dark `state-error` on `muted`).
 * Both are correct about different sets, and nothing crosses its threshold
 * either way — verified by the assertions below, which use all four.
 */
const SURFACES = ["--background", "--surface", "--surface-high", "--muted"] as const;

/*
 * Why `--secondary` and `--accent` are NOT in that list, written down because an
 * unexplained omission is indistinguishable from an oversight:
 *
 *   · `--accent` is value-identical to `--muted` in both themes, so including it
 *     would add rows without adding coverage.
 *   · `--secondary` is a backdrop in exactly one place (`components/ui/badge.tsx`
 *     variant `secondary`) and it always carries `text-secondary-foreground`,
 *     which IS measured as a paired role (10.22 light / 4.60 dark).
 *
 * The reason to record it rather than just do it: if `--secondary` ever becomes a
 * general backdrop, these are the numbers that would come due — dark
 * `muted-foreground` on it is 3.54, `input` on it 2.85, badge info text over it
 * 4.32. All below their thresholds. Whoever makes `bg-secondary` general has to
 * add it here and fix those.
 *
 * There is a SECOND trigger, less obvious than the first: a `border-secondary` or
 * `border-accent` shipping anywhere. Today both tokens only ever appear as
 * backdrops carrying their own paired foreground, which is why the
 * `${role}-foreground on ${role}` pairs cover them. A border has no paired
 * foreground to piggyback on, so it would owe its own 3:1 `ui` pair here.
 * Verified as of this section: bare `text-secondary`, `text-accent`,
 * `border-secondary`, `border-accent` and their ring/fill/stroke variants are all
 * absent from shipped code.
 */

const TONES = ["success", "warning", "error", "info", "neutral"] as const;

type Theme = { name: string; tokens: Record<string, string> };

const THEMES: Theme[] = [
  { name: "light", tokens: LIGHT },
  { name: "dark", tokens: DARK },
];

/**
 * Every pair the audit measures, with the threshold that applies to it.
 *
 * `ui` is WCAG 2.2 **1.4.11 Non-text Contrast** (3:1), which applies to the
 * visual boundary of a *component*. `text` is 1.4.3 (4.5:1). The distinction is
 * not cosmetic: it is exactly what separates `--input` from `--border` in design
 * D9, and getting it wrong in either direction either fails a control that is
 * fine or passes one that is not.
 */
type Pair = {
  label: string;
  fg: string;
  bg: string;
  kind: "text" | "ui";
  /**
   * A declared D9 exception: measured and recorded, but no threshold applies.
   * Flagged rather than inferred from the label, so the register never prints
   * «FAIL» against a pair that was never required to pass — this register IS the
   * artefact R1.6 asks for, and one that reads as twenty-one failures is worse
   * than none.
   */
  exempt?: true;
};

function corePairs(theme: Theme): Pair[] {
  const t = theme.tokens;
  const pairs: Pair[] = [];

  // Body and secondary text, on every surface they can sit on.
  for (const surface of SURFACES) {
    pairs.push({
      label: `foreground on ${surface}`,
      fg: t["--foreground"],
      bg: t[surface],
      kind: "text",
    });
    pairs.push({
      label: `muted-foreground on ${surface}`,
      fg: t["--muted-foreground"],
      bg: t[surface],
      kind: "text",
    });
  }

  // The paired roles: each foreground token against the surface it names.
  for (const role of ["primary", "secondary", "accent"] as const) {
    pairs.push({
      label: `${role}-foreground on ${role}`,
      fg: t[`--${role}-foreground`],
      bg: t[`--${role}`],
      kind: "text",
    });
  }

  /*
   * `--primary` as TEXT, which is the axis the app actually uses and the one this
   * audit was blind to.
   *
   * `text-primary` is normal-size body text — `text-sm`, 14px, normal weight — in
   * five shipped places: `reservations/…/reservation-detail-view.tsx:46,79`,
   * `reservations/…/reservations-view.tsx:154`,
   * `dashboard/…/property-card.tsx:146`, `properties/…/properties-view.tsx:49`.
   * So it owes 4.5:1 under 1.4.3, not 3:1.
   *
   * It was invisible here because `--primary` and `--ring` hold the same value in
   * both themes, so the only pair that touched primary was `ring on <surface>` at
   * the 3:1 UI threshold. The gap was demonstrable, not theoretical: with light
   * `--primary: #7c727e` every assertion in this file passed while those five
   * links sat at 4.07:1 on `--background` and 3.71:1 on `--muted`.
   */
  for (const surface of SURFACES) {
    pairs.push({
      label: `primary as text on ${surface}`,
      fg: t["--primary"],
      bg: t[surface],
      kind: "text",
    });
  }

  /*
   * `--primary` as a UI boundary (1.4.11, 3:1): `border border-primary` at
   * `dashboard/…/property-card.tsx:87`. Same token, different threshold, because
   * what applies depends on the role the colour plays.
   */
  for (const surface of SURFACES) {
    pairs.push({
      label: `primary as border on ${surface}`,
      fg: t["--primary"],
      bg: t[surface],
      kind: "ui",
    });
  }

  /*
   * The other live composite in the tree: `hover:bg-primary/90` on the default
   * `Button` (`components/ui/button.tsx:12`), which keeps
   * `text-primary-foreground`. A hover state still has to be readable.
   *
   * On every surface, because a `Button` is not pinned to `--background`. Its
   * floor is 5.18 over `--surface-high`, not the 5.32 that recording only
   * `--background` would advertise — the same one-surface-of-four asymmetry the
   * hairline exception had, which is easy to reintroduce while fixing.
   */
  for (const surface of SURFACES) {
    pairs.push({
      label: `primary-foreground on primary/90 over ${surface} (hover:bg-primary/90)`,
      fg: t["--primary-foreground"],
      bg: compositeOver(t["--primary"], t[surface], 0.9),
      kind: "text",
    });
  }

  // Control boundaries and the focus ring — 1.4.11, not 1.4.3.
  for (const surface of SURFACES) {
    pairs.push({
      label: `input on ${surface}`,
      fg: t["--input"],
      bg: t[surface],
      kind: "ui",
    });
    pairs.push({
      label: `ring on ${surface}`,
      fg: t["--ring"],
      bg: t[surface],
      kind: "ui",
    });
  }

  // The five state anchors as graphic tokens: fills, dots, borders (3:1).
  for (const tone of TONES) {
    for (const surface of SURFACES) {
      pairs.push({
        label: `state-${tone} on ${surface}`,
        fg: t[`--state-${tone}`],
        bg: t[surface],
        kind: "ui",
      });
    }
  }

  /*
   * The five state text tokens on a PLAIN surface, not on a badge tint.
   *
   * `badgePairs` measures them over their own 15% tint, which is the badge. But
   * `text-state-error-text` also ships as bare error copy on an ordinary
   * background — the login form's `role="alert"`, the guest-portal field error
   * and the property timeline — and that is a different pair with a different
   * number. It reached the tree as `text-destructive`, a token `globals.css`
   * never declared, so those three messages painted nothing and inherited
   * `--foreground`: an error that did not look like one. The D13 guard found it;
   * this is the half that keeps it measured.
   *
   * All five families are measured, not just `error`, for the reason this file
   * gives about `--muted`: the audit should not be narrower than what the app
   * may paint, and any of the five is legitimate as bare text.
   */
  for (const tone of TONES) {
    for (const surface of SURFACES) {
      pairs.push({
        label: `state-${tone}-text on ${surface}  [bare text, not a badge]`,
        fg: t[`--state-${tone}-text`],
        bg: t[surface],
        kind: "text",
      });
    }
  }

  return pairs;
}

/**
 * The badge shape, read out of `lib/ui/status-tone.ts` instead of restated here.
 *
 * Design D6 has `TONE_BADGE_CLASS` render
 * `bg-state-X/15 text-state-X-text border-state-X/40`, so the text never sits on
 * `--state-X` itself: it sits on that anchor composited at 15% over whatever
 * surface is behind the badge. D6 measured `#10B981` on its own 15% tint at
 * 2.3:1, which is why `state-*-text` exists as a separate token at all.
 *
 * Those numbers used to be premises this file took from the design, and that was
 * a hole: had task 7.1 landed `/20`, or `text-state-warning` instead of
 * `text-state-warning-text`, the forty figures below would have stayed green
 * while measuring a badge the app no longer paints. So the alphas, the anchor and
 * the text token are now PARSED from the shipped strings, and the shape itself is
 * asserted — an unparseable entry drops out of the audit, which the size
 * assertions then reject.
 */
const BADGE_CLASS_SHAPE =
  /^bg-state-([a-z]+)\/(\d{1,3}) text-state-([a-z]+)-text border-state-([a-z]+)\/(\d{1,3})$/;

type BadgeSpec = {
  tone: Tone;
  anchor: string;
  bgAlpha: number;
  borderAlpha: number;
  textToken: string;
};

type BadgeParse =
  | { ok: true; spec: BadgeSpec }
  | { ok: false; tone: Tone; reason: string };

function parseBadgeClass(tone: Tone, classes: string): BadgeParse {
  const match = BADGE_CLASS_SHAPE.exec(classes);
  if (match === null) {
    return { ok: false, tone, reason: `does not match D6's shape: "${classes}"` };
  }
  const [, bgAnchor, bgAlpha, textAnchor, borderAnchor, borderAlpha] = match;
  if (bgAnchor !== textAnchor || bgAnchor !== borderAnchor) {
    return {
      ok: false,
      tone,
      reason: `mixes anchors (bg ${bgAnchor}, text ${textAnchor}, border ${borderAnchor})`,
    };
  }
  return {
    ok: true,
    spec: {
      tone,
      anchor: bgAnchor,
      bgAlpha: Number(bgAlpha) / 100,
      borderAlpha: Number(borderAlpha) / 100,
      textToken: `--state-${textAnchor}-text`,
    },
  };
}

const BADGE_PARSES: BadgeParse[] = (
  Object.keys(TONE_BADGE_CLASS) as Tone[]
).map((tone) => parseBadgeClass(tone, TONE_BADGE_CLASS[tone]));

const BADGE_SPECS: BadgeSpec[] = BADGE_PARSES.flatMap((parse) =>
  parse.ok ? [parse.spec] : [],
);

/** The badge pairs — the ones that need composition, over every surface. */
function badgePairs(theme: Theme): Pair[] {
  const t = theme.tokens;
  const pairs: Pair[] = [];
  for (const spec of BADGE_SPECS) {
    for (const surface of SURFACES) {
      const tint = compositeOver(
        t[`--state-${spec.anchor}`],
        t[surface],
        spec.bgAlpha,
      );
      pairs.push({
        label: `${spec.textToken.slice(2)} on state-${spec.anchor}/${spec.bgAlpha * 100} over ${surface} (${tint})`,
        fg: t[spec.textToken],
        bg: tint,
        kind: "text",
      });
    }
  }
  return pairs;
}

/**
 * The declared exceptions, from design D9 — measured and recorded, but not
 * asserted against a threshold.
 *
 * These are NOT failures being waved through. WCAG 1.4.11 governs the visual
 * boundary of a *component*; a hairline that divides content is decorative, and
 * no information depends on seeing it (every badge carries its own translated
 * label, so WCAG 1.4.1 is satisfied by the text, not the border). D9 rejected
 * raising `--border` to 3:1 explicitly: «cumpliría un requisito que WCAG no
 * impone y borraría la estética de hairline».
 *
 * They are still computed and printed, because an exception whose number nobody
 * measures is how the light `--border` figure came to be recorded against the
 * wrong surface in the first place — it said 1.32 (its ratio against `surface`)
 * while its dark counterpart was quoted against `background`.
 */
function exceptionPairs(theme: Theme): Pair[] {
  const t = theme.tokens;
  const pairs: Pair[] = [];

  /*
   * The hairline on EVERY surface, not just `--background`.
   *
   * Recording it on one surface of four is the same asymmetry the section-2
   * panel corrected in design.md, where the dark row was quoted against
   * `background` and the light row against `surface` — two rows of one declared
   * pair describing different pairs. R1.6 asks for the ratio «por par», so the
   * fix is to iterate, exactly as the other two lists do.
   *
   * It also surfaces something worth knowing: in dark, `--border` and `--muted`
   * are the same value (`#262a34`), so a bordered card on `bg-muted` has a
   * border at ratio 1.00 — literally invisible. D9's reasoning still covers it
   * (decorative, carries no information, no control boundary), but the number
   * should be in the register rather than discovered later.
   */
  for (const surface of SURFACES) {
    pairs.push({
      label: `border on ${surface}  [decorative hairline, D9]`,
      fg: t["--border"],
      bg: t[surface],
      kind: "ui",
      exempt: true,
    });
  }
  for (const spec of BADGE_SPECS) {
    for (const surface of SURFACES) {
      const anchor = t[`--state-${spec.anchor}`];
      const tint = compositeOver(anchor, t[surface], spec.bgAlpha);
      const edge = compositeOver(anchor, t[surface], spec.borderAlpha);
      pairs.push({
        label: `state-${spec.anchor}/${spec.borderAlpha * 100} edge on its own /${spec.bgAlpha * 100} tint over ${surface}  [badge border, D9]`,
        fg: edge,
        bg: tint,
        kind: "ui",
        exempt: true,
      });
    }
  }
  return pairs;
}

function threshold(kind: Pair["kind"]): number {
  return kind === "text" ? AA_NORMAL_TEXT : AA_LARGE_TEXT_AND_UI;
}

/** The record R1.6 asks for: every pair, its measured ratio, its verdict. */
function report(theme: Theme, pairs: Pair[], heading: string): string[] {
  const lines = [`\n  ${theme.name.toUpperCase()} — ${heading}`];
  for (const pair of pairs) {
    // The VERDICT comes from the unrounded ratio, the printed NUMBER is rounded.
    // Deciding on the rounded value let the register print «ok 4.50» about a pair
    // the gate rejects at 4.499978 — and since this register is the artefact R1.6
    // asks for, that is a wrong answer in the deliverable, not a cosmetic slip.
    const exact = contrastRatio(pair.fg, pair.bg);
    const need = threshold(pair.kind);
    const verdict = pair.exempt ? "n/a " : exact >= need ? "ok  " : "FAIL";
    const requirement = pair.exempt ? "exempt " : `needs ${need}`;
    lines.push(
      `    ${verdict} ${round2(exact).toFixed(2).padStart(6)}:1  (${requirement}) ${pair.label}`,
    );
  }
  return lines;
}

describe("WCAG 2.2 AA contrast audit (R1.6, design D11)", () => {
  it.each(THEMES)("$name — every text pair reaches 4.5:1", (theme) => {
    // Compares the UNROUNDED ratio. Rounding first lets a real failure through:
    // `#007eb7` on white measures 4.4986:1 — below AA — and rounds to «4.50 ok».
    // Rounding belongs in the register, which is for humans, not in the gate.
    const failures = [...corePairs(theme), ...badgePairs(theme)]
      .filter((pair) => pair.kind === "text")
      .map((pair) => ({ pair, ratio: contrastRatio(pair.fg, pair.bg) }))
      .filter(({ ratio }) => ratio < AA_NORMAL_TEXT)
      .map(({ pair, ratio }) => `${pair.label}: ${round2(ratio)}:1`);
    expect(failures).toEqual([]);
  });

  it.each(THEMES)(
    "$name — every control boundary and graphic token reaches 3:1",
    (theme) => {
      // Unrounded, for the same reason as the text gate above.
      const failures = corePairs(theme)
        .filter((pair) => pair.kind === "ui")
        .map((pair) => ({
          pair,
          ratio: contrastRatio(pair.fg, pair.bg),
        }))
        .filter(({ ratio }) => ratio < AA_LARGE_TEXT_AND_UI)
        .map(({ pair, ratio }) => `${pair.label}: ${round2(ratio)}:1`);
      expect(failures).toEqual([]);
    },
  );

  it("pins the shipped badge strings to the shape this audit measures", () => {
    /*
     * The coupling task 7.1 owed this file.
     *
     * Everything above reads the alphas, the anchor and the text token out of
     * `TONE_BADGE_CLASS`, so a drift there moves the numbers rather than
     * invalidating them silently. What parsing alone cannot catch is a string
     * that stops being a badge at all — `bg-muted text-muted-foreground` parses
     * to nothing, drops its four pairs, and would leave a smaller audit passing.
     * So: all five tones parse, and they parse to D6's numbers.
     */
    const unparseable = BADGE_PARSES.flatMap((parse) =>
      parse.ok ? [] : [`${parse.tone}: ${parse.reason}`],
    );
    expect(unparseable).toEqual([]);
    expect(BADGE_SPECS).toHaveLength(5);

    // The anchors the badges reach, against the tones the CSS declares: neither
    // set may be a subset of the other. `gray` maps to `state-neutral`, which is
    // R6.1's whole point — the fifth PRD §9.1 family, absent from DESIGN.md.
    expect(new Set(BADGE_SPECS.map((spec) => spec.anchor))).toEqual(
      new Set(TONES),
    );

    // D6's literals, stated once. A deliberate change to the design updates this
    // line; an accidental one fails here instead of quietly re-basing the audit.
    for (const spec of BADGE_SPECS) {
      expect(spec.bgAlpha, `${spec.tone} background alpha`).toBe(0.15);
      expect(spec.borderAlpha, `${spec.tone} border alpha`).toBe(0.4);
    }

    // And no `dark:` survives: R6.5's defect was that Tailwind's `dark:` follows
    // `prefers-color-scheme`, never our `data-theme` attribute.
    for (const [tone, classes] of Object.entries(TONE_BADGE_CLASS)) {
      expect(classes, `${tone} must not carry a dark: variant`).not.toContain(
        "dark:",
      );
    }
  });

  it("measures the 40 badge combinations, five tones over four surfaces in both themes", () => {
    // A count, so a tone or a surface silently dropping out of the audit is a
    // failure rather than a quieter pass.
    const all = THEMES.flatMap((theme) => badgePairs(theme));
    expect(all).toHaveLength(
      BADGE_SPECS.length * SURFACES.length * THEMES.length,
    );
    expect(all).toHaveLength(40);
  });

  it("keeps state-*-text as a distinct token, because the anchor alone would fail", () => {
    // D6's rejected alternative, re-measured here so the rejection stays true:
    // using the anchor as its own text colour («text-state-success») fails in
    // light for all five tones. If that ever stops being true the token could be
    // dropped — and this is where we would find out.
    const wouldFail = THEMES.flatMap((theme) =>
      BADGE_SPECS.flatMap((spec) =>
        SURFACES.map((surface) => {
          const anchor = theme.tokens[`--state-${spec.anchor}`];
          const tint = compositeOver(
            anchor,
            theme.tokens[surface],
            spec.bgAlpha,
          );
          return {
            label: `${theme.name} ${spec.anchor} on ${surface}`,
            ratio: round2(contrastRatio(anchor, tint)),
          };
        }),
      ),
    ).filter(({ ratio }) => ratio < AA_NORMAL_TEXT);
    expect(wouldFail.length).toBeGreaterThan(0);
  });

  it("covers every category at its expected size, counted independently", () => {
    /*
     * Hardcoded literals, NOT derived from `SURFACES`/`TONES`.
     *
     * The previous version compared the total against a `themeCount()` computed
     * from those same constants, which cannot see a SHRINK: deleting `--muted`
     * from `SURFACES` moved both sides together and left every assertion green.
     * The only thing that caught it was a sibling `toHaveLength(40)`, and that
     * was luck — `badgePairs` happens to iterate the same arrays, while
     * `corePairs`, the larger half, had no independent count at all.
     *
     * So the shared constants are pinned first, and each category's size is
     * stated as a number a human chose.
     */
    expect(SURFACES).toHaveLength(4);
    expect(TONES).toHaveLength(5);
    expect(THEMES).toHaveLength(2);

    for (const theme of THEMES) {
      // 4 foreground + 4 muted-foreground + 3 paired roles + 4 primary-as-text
      // + 4 primary-as-border + 4 hover composites + 4 input + 4 ring
      // + 20 state anchors + 20 state text tokens as bare text (D13)
      expect(corePairs(theme), `${theme.name} core`).toHaveLength(71);
      // 5 tones × 4 surfaces
      expect(badgePairs(theme), `${theme.name} badges`).toHaveLength(20);
      // 4 hairline + 20 badge edges
      expect(exceptionPairs(theme), `${theme.name} exceptions`).toHaveLength(24);

      /*
       * And the text/ui SPLIT, pinned separately.
       *
       * `kind` is what selects the threshold, so it is a laundering axis the size
       * literals cannot see: flipping `foreground` from `text` to `ui` drops its
       * requirement from 4.5 to 3.0, changes no count, sets no `exempt`, and used
       * to leave every assertion in this file green. Body text silently
       * reclassified as a UI boundary is exactly the confusion this file warns
       * about where it defines `kind`.
       */
      const core = corePairs(theme);
      expect(
        core.filter((pair) => pair.kind === "text"),
        `${theme.name} core text pairs`,
      ).toHaveLength(39);
      expect(
        core.filter((pair) => pair.kind === "ui"),
        `${theme.name} core ui pairs`,
      ).toHaveLength(32);
      expect(
        badgePairs(theme).filter((pair) => pair.kind === "text"),
        `${theme.name} badge text pairs`,
      ).toHaveLength(20);
    }
  });

  it("declares exactly D9's two exception kinds, so none can be smuggled in", () => {
    // D9 declares TWO exempt shapes and no others: the decorative hairline and
    // the badge edge at 40%. Asserting the total alone would let a pair migrate
    // out of the asserted sets into the exempt one without changing any count.
    for (const theme of THEMES) {
      const kinds = new Set(
        exceptionPairs(theme).map((pair) =>
          pair.label.includes("[decorative hairline, D9]")
            ? "hairline"
            : pair.label.includes("[badge border, D9]")
              ? "badge-edge"
              : `UNDECLARED: ${pair.label}`,
        ),
      );
      expect(kinds).toEqual(new Set(["hairline", "badge-edge"]));
      // And every exempt pair really is flagged, so `exempt` cannot be implied
      // by a label alone.
      expect(exceptionPairs(theme).every((pair) => pair.exempt)).toBe(true);
    }
    // Conversely, nothing in the asserted sets is exempt — no laundering.
    for (const theme of THEMES) {
      const asserted = [...corePairs(theme), ...badgePairs(theme)];
      expect(asserted.some((pair) => pair.exempt)).toBe(false);
    }
  });

  it("records the ratio of every pair, which is the register R1.6 requires", () => {
    const lines: string[] = [
      "\nWCAG 2.2 AA contrast register — recomputed from globals.css",
    ];
    for (const theme of THEMES) {
      lines.push(...report(theme, corePairs(theme), "core pairs"));
      lines.push(...report(theme, badgePairs(theme), "badges (anchor at 15%)"));
      lines.push(
        ...report(theme, exceptionPairs(theme), "declared D9 exceptions"),
      );
    }
    // The register is the artefact, so it is emitted rather than merely computed.
    console.log(lines.join("\n"));

    // Every pair must be a real measurement. A missing token yields `undefined`,
    // which `parseHex` throws on rather than silently scoring — so this also
    // pins that a token rename cannot quietly empty the audit.
    const measured = THEMES.flatMap((theme) => [
      ...corePairs(theme),
      ...badgePairs(theme),
      ...exceptionPairs(theme),
    ]);
    // (71 core + 20 badges + 24 exceptions) × 2 themes. Was 190 before D13
    // added the 20 bare-text state pairs per theme.
    expect(measured).toHaveLength(230);
    for (const pair of measured) {
      expect(pair.fg, pair.label).toMatch(/^#[0-9a-f]{6}$/i);
      expect(pair.bg, pair.label).toMatch(/^#[0-9a-f]{6}$/i);
      expect(contrastRatio(pair.fg, pair.bg)).toBeGreaterThanOrEqual(1);
    }
  });
});
