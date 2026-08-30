import { describe, expect, it } from "vitest";

import { validateFinalCost } from "./tech-resolve-form";

/**
 * The local validation of `final_cost` (R4.1, R4.5).
 *
 * Local validation exists to **prevent emitting** a request the backend will
 * refuse. The component test covers the `required` branch through the DOM;
 * these cover the branches that only this function can reach, so a regression
 * that drops one of the guards fails here instead of turning into a 422 the
 * technician has to interpret.
 */
describe("validateFinalCost (R4.1)", () => {
  // `required` means nothing was typed, and nothing else.
  it.each(["", "   ", "\t"])("asks for a value when %j is empty", (raw) => {
    expect(validateFinalCost(raw)).toBe("required");
  });

  /**
   * Anything typed but malformed is a *shape* problem. `"5,00"` is the one that
   * matters: a Spanish numeric keypad offers a comma, `Number("5,00")` is `NaN`,
   * and the old order answered "indica el coste final" to someone who had.
   */
  it.each(["5,00", "abc", ".", "5.0.0", "1 000", "1e3", "+5", "0x10"])(
    "rejects the malformed %j as a shape, not as a missing value",
    (raw) => {
      expect(validateFinalCost(raw)).toBe("format");
    },
  );

  it.each(["-0.01", "-1", "-99"])("rejects the negative %j", (raw) => {
    expect(validateFinalCost(raw)).toBe("negative");
  });

  it("rejects a value above the contract's maximum", () => {
    expect(validateFinalCost("100000000")).toBe("tooLarge");
    expect(validateFinalCost("99999999.999")).toBe("tooLarge");
  });

  it("accepts the maximum itself — the bound is inclusive", () => {
    expect(validateFinalCost("99999999.99")).toBeNull();
  });

  it.each(["1.005", "0.001", "12.3456"])(
    "rejects more than two decimals in %j",
    (raw) => {
      expect(validateFinalCost(raw)).toBe("decimals");
    },
  );

  /**
   * `"5."` and `".5"` are **accepted**, and this is the case that pins R4.5:
   * local validation only prevents emitting, so it may not refuse a value the
   * server would take. `Decimal("5.")` is `5` and `Decimal(".5")` is `0.5`,
   * both inside `ge=0` with two decimals, so an earlier revision that rejected
   * them as malformed was inventing a mistake the technician had not made.
   */
  it.each(["5.", ".5"])("accepts %j, which the server accepts", (raw) => {
    expect(validateFinalCost(raw)).toBeNull();
  });

  /**
   * The one place the local rule is knowingly stricter than the *published
   * pattern* — recorded so it stays a decision instead of drifting into a
   * contradiction. `^(?!^[-+.]*$)[+-]?0*\d*\.?\d{0,2}0*$` admits a leading `+`
   * and the server's `Decimal("+5")` passes `ge=0`, so `"+5"` would round-trip
   * fine. It is refused here because the control is an `<input type="number">`,
   * which never produces one: accepting it would widen the contract of this
   * form for a value no technician can type. The inverse case is the reason the
   * pattern is not the referent at all — it also admits `"5.100"`, which the
   * schema's `decimal_places=2` rejects.
   */
  it("refuses a leading + although the published pattern admits it", () => {
    expect(validateFinalCost("+5")).toBe("format");
  });

  it("refuses a third decimal although the published pattern admits it", () => {
    expect(validateFinalCost("5.100")).toBe("decimals");
  });

  it("keeps precision apart from shape", () => {
    expect(validateFinalCost("5,00")).toBe("format");
    expect(validateFinalCost("5.123")).toBe("decimals");
  });

  it("keeps a sign as a value problem, not a shape one", () => {
    expect(validateFinalCost("-1")).toBe("negative");
    expect(validateFinalCost("-0.01")).toBe("negative");
  });

  it.each(["0", "5", "0.00", "12.30", "00.10", "99.9"])(
    "accepts the well-formed %j",
    (raw) => {
      expect(validateFinalCost(raw)).toBeNull();
    },
  );

  it("trims before judging, because the form does not", () => {
    expect(validateFinalCost("  12.34  ")).toBeNull();
  });
});
