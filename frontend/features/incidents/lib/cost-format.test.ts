import { describe, expect, it } from "vitest";

import { isPositiveDecimal } from "./cost-format";

describe("isPositiveDecimal (R3.2, D11)", () => {
  it.each(["0", "0.5", "0.50", ".5", ".50", "12", "12.3", "12.34", "1000000"])(
    "accepts %s",
    (value) => {
      expect(isPositiveDecimal(value)).toBe(true);
    },
  );

  it.each([
    "12.345",
    "-1",
    "-1.50",
    "1,50",
    "1e5",
    "1.5.5",
    "",
    " ",
    "abc",
    ".",
    "1.",
    "+1",
  ])("rejects %s", (value) => {
    expect(isPositiveDecimal(value)).toBe(false);
  });
});
