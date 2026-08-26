/**
 * Locale contract tests for the `pricing` i18n namespace (R6.4, R6.6, design D15).
 *
 * Why this is not redundant with `lib/i18n/catalog-parity.test.ts`: that test
 * compares the ES and EN **key sets** of every registered namespace, so it
 * catches a key present in one language and missing in the other. It does not
 * check that there is a key per **enum value** — an enum with six values and five
 * labels passes it, in both languages at once. This file closes that gap, with
 * the pattern of `features/properties/locales/properties-locale.test.ts`.
 *
 * The list of statuses is **derived** from `RECOMMENDATION_STATUS_ORDER`, never
 * transcribed here. That is the whole point (D15): a hand-written fixture
 * validates the translations against itself, so a sixth status the backend adds
 * would look covered. `RECOMMENDATION_STATUS_ORDER` comes from an exhaustive
 * `Record<PriceRecommendationStatus, …>`, so the compiler keeps it complete and
 * this test inherits that guarantee — including `DRAFT`, which nothing produces
 * today and which R6.4 requires a label for anyway.
 */

import { describe, expect, it } from "vitest";
import i18next from "i18next";

import enPricing from "@/locales/en/pricing.json";
import esPricing from "@/locales/es/pricing.json";

import type { DecisionStatus } from "../data";
import { RECOMMENDATION_STATUS_ORDER } from "../lib/recommendation-status";
import {
  GENERIC_DECIDE_ERROR_KEY,
  GENERIC_GENERATE_ERROR_KEY,
  GENERIC_READ_ERROR_KEY,
} from "../lib/pricing-error";

const CATALOGS = { es: esPricing, en: enPricing } as const;

/** The three moves, derived from the union rather than transcribed. */
const DECISION_STATUSES: readonly DecisionStatus[] = [
  "APPROVED",
  "REJECTED",
  "APPLIED_EXTERNAL",
];

describe("pricing locale — the five statuses (R6.4)", () => {
  it("has five statuses to cover, matching the generated enum", () => {
    // Guards the premise of the test below: if this stops being 5, the contract
    // moved and both catalogs need revisiting.
    expect(RECOMMENDATION_STATUS_ORDER).toHaveLength(5);
  });

  it("localizes every status in ES and EN, DRAFT included", () => {
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      for (const status of RECOMMENDATION_STATUS_ORDER) {
        expect(
          (catalog.status as Record<string, string>)[status],
          `${locale} missing label for status ${status}`,
        ).toBeTypeOf("string");
      }
    }
  });

  it("has no label for a status the contract does not declare", () => {
    // The other direction: a leftover label is dead copy suggesting a state the
    // product no longer has.
    for (const catalog of Object.values(CATALOGS)) {
      expect(Object.keys(catalog.status).sort()).toEqual(
        [...RECOMMENDATION_STATUS_ORDER].sort(),
      );
    }
  });

  it("asks a distinct question before each of the three moves (R3.3)", () => {
    // «¿seguro?» would not tell the user what she is confirming, so the copy is
    // per move — and therefore has to exist per move, in both locales.
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      const questions = catalog.decide.confirmQuestion as Record<string, string>;
      expect(Object.keys(questions).sort()).toEqual(
        [...DECISION_STATUSES].sort(),
      );
      const texts = DECISION_STATUSES.map((move) => questions[move]);
      expect(new Set(texts).size, `${locale} reuses a confirmation`).toBe(
        DECISION_STATUSES.length,
      );
    }
  });
});

describe("pricing locale — every error key the mappers can emit (R3.6, R3.7)", () => {
  /**
   * Taken from the three generic constants plus the tables' own keys, so this
   * list cannot drift from `lib/pricing-error.ts` silently: those constants are
   * imported, and the branch keys are asserted below against the catalog.
   */
  const ERROR_KEYS = [
    "decide.error.forbidden",
    "decide.error.notFound",
    "decide.error.conflict",
    "decide.error.invalid",
    GENERIC_DECIDE_ERROR_KEY,
    "generate.error.forbidden",
    "generate.error.invalid",
    GENERIC_GENERATE_ERROR_KEY,
    "read.error.forbidden",
    GENERIC_READ_ERROR_KEY,
  ].map((key) => key.replace(/^pricing:/, ""));

  function lookup(catalog: object, path: string): unknown {
    return path
      .split(".")
      .reduce<unknown>(
        (node, part) => (node as Record<string, unknown>)?.[part],
        catalog,
      );
  }

  it("resolves every key `pricing-error.ts` can return, in both locales", () => {
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      for (const key of ERROR_KEYS) {
        expect(lookup(catalog, key), `${locale} missing ${key}`).toBeTypeOf(
          "string",
        );
      }
    }
  });

  it("gives the 409 copy of its own, distinct from the generic one (R3.6)", () => {
    // R3.6 asks for copy that says something different, not merely for a key
    // that exists — «esa recomendación ya no está en el estado que creías».
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      const conflict = lookup(catalog, "decide.error.conflict");
      const generic = lookup(catalog, "decide.error.generic");
      expect(conflict, `${locale} 409 copy equals the generic one`).not.toBe(
        generic,
      );
    }
  });

  it("gives the read 403 copy of its own, distinct from the generic one (design D9)", () => {
    // What a CLEANER arriving from the unfiltered sidebar reads. «Try again in a
    // few seconds» would be false.
    for (const catalog of Object.values(CATALOGS)) {
      expect(lookup(catalog, "read.error.forbidden")).not.toBe(
        lookup(catalog, "read.error.generic"),
      );
    }
  });
});

describe("pricing locale — the generation report claims nothing (R4.3)", () => {
  it("interpolates the four counters", () => {
    for (const [locale, catalog] of Object.entries(CATALOGS)) {
      const report = catalog.generate.report;
      for (const counter of ["created", "updated", "preserved", "skipped"]) {
        expect(report, `${locale} report omits ${counter}`).toContain(
          `{{${counter}}}`,
        );
      }
    }
  });

  it("says exactly the four counters and nothing else", () => {
    // R4.3: the contract exposes no `failed` counter — «un barrido con agujeros
    // se ve verde desde la API» — so the copy reports numbers and claims
    // nothing.
    //
    // Pinned as an **exact string**, not as a denylist of words like «éxito» or
    // «success». The QA panel on this section defeated the denylist in one
    // attempt, by appending «, sin ningún error, resultado perfecto.» — a
    // textbook overclaim that happens to use none of the listed words. A
    // denylist can only forbid the phrasings someone thought of; the sentence
    // here is fixed and known, so equality forbids every other phrasing at once
    // and makes any future edit to this copy a deliberate, visible act.
    expect(esPricing.generate.report).toBe(
      "Generación ejecutada: {{created}} creadas, {{updated}} actualizadas, {{preserved}} conservadas, {{skipped}} omitidas.",
    );
    expect(enPricing.generate.report).toBe(
      "Generation ran: {{created}} created, {{updated}} updated, {{preserved}} preserved, {{skipped}} skipped.",
    );
  });
});

describe("pricing locale — ES and EN are actually two languages (R6.6)", () => {
  /**
   * `catalog-parity.test.ts` proves both locales have the same **keys**; nothing
   * proved they have different **values**. The QA panel on this section copied
   * three Spanish strings verbatim into the English catalog and every test
   * stayed green — an untranslated string is exactly what R6.6 forbids, and it
   * was invisible.
   *
   * A blanket «all values differ» assertion would be wrong: a few genuinely
   * coincide. Enumerating those instead turns each one into a decision on the
   * record, and makes any *new* coincidence fail.
   */
  const LEGITIMATELY_IDENTICAL = new Set([
    // A typographic separator, not a word.
    "separator",
    // «Base» is the same in both languages, and translating it to anything else
    // would be worse: it names the `base_price` column.
    "rules.columns.basePrice",
  ]);

  function flatten(
    value: unknown,
    prefix = "",
    into: Record<string, string> = {},
  ): Record<string, string> {
    if (typeof value === "string") {
      into[prefix] = value;
      return into;
    }
    for (const [key, child] of Object.entries(value as object)) {
      flatten(child, prefix ? `${prefix}.${key}` : key, into);
    }
    return into;
  }

  it("has no untranslated string beyond the ones declared identical", () => {
    const es = flatten(esPricing);
    const en = flatten(enPricing);
    const identical = Object.keys(es).filter((key) => es[key] === en[key]);
    expect(identical.sort()).toEqual([...LEGITIMATELY_IDENTICAL].sort());
  });
});

describe("pricing locale — whole-portfolio scope (R5.3)", () => {
  it("names the null-property scope in both locales", () => {
    expect(esPricing.rules.scope.portfolio).toBe("Toda la cartera");
    expect(enPricing.rules.scope.portfolio).toBe("Whole portfolio");
  });
});

describe("pricing locale — the percent lives in the label (design D14)", () => {
  it("marks max_daily_change_pct as a percentage in its column label", () => {
    // The number is formatted by `fmtDecimal` and carries no unit, so the label
    // has to.
    for (const catalog of Object.values(CATALOGS)) {
      expect(catalog.rules.columns.maxDailyChangePct).toContain("%");
    }
  });
});

describe("pricing locale — resolution through i18next", () => {
  it("resolves the keys the screen asks for, in the pricing namespace", async () => {
    await i18next.init({
      lng: "es",
      fallbackLng: "en",
      ns: ["pricing"],
      defaultNS: "pricing",
      resources: { es: { pricing: esPricing }, en: { pricing: enPricing } },
      interpolation: { escapeValue: false },
    });

    for (const status of RECOMMENDATION_STATUS_ORDER) {
      expect(i18next.t(`status.${status}`)).toBe(
        (esPricing.status as Record<string, string>)[status],
      );
    }
    expect(i18next.t("tabs.recommendations")).toBe("Recomendaciones");
    expect(i18next.t("tabs.rules")).toBe("Reglas");
    expect(
      i18next.t("generate.report", {
        created: 4,
        updated: 3,
        preserved: 2,
        skipped: 1,
      }),
    ).toBe(
      "Generación ejecutada: 4 creadas, 3 actualizadas, 2 conservadas, 1 omitidas.",
    );
  });
});
