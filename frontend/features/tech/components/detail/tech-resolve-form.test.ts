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
  it.each([
    ["", "required"],
    ["   ", "required"],
    ["abc", "required"],
  ] as const)("rejects %j as %s", (raw, expected) => {
    expect(validateFinalCost(raw)).toBe(expected);
  });

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
   * A trailing or leading bare point used to pass: `Number("5.")` is `5`, and
   * the old `^\d*\.?\d{0,2}$` accepted the shape. The string was then sent
   * verbatim and the backend's two-decimal pattern answered 422 — exactly the
   * round-trip R4.5 asks local validation to prevent.
   *
   * It is `format`, not `decimals`: `"5."` carries no decimals at all, so
   * "at most two decimals" would name a rule the technician did not break.
   */
  it.each(["5.", ".5"])("rejects the bare point in %j as a shape", (raw) => {
    expect(validateFinalCost(raw)).toBe("format");
  });

  it("keeps the two refusals apart — shape is not the same mistake as precision", () => {
    expect(validateFinalCost("5.")).toBe("format");
    expect(validateFinalCost("5.123")).toBe("decimals");
  });

  it('rejects the lone point as unparseable', () => {
    expect(validateFinalCost(".")).toBe("required");
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
