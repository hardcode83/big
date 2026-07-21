import axe from "axe-core";

/**
 * Shared render helpers for component tests. The default `render` is re-exported
 * from Testing Library; suites that need context (i18n, query, config) pass their
 * own `wrapper` option. Kept provider-agnostic and free of business data so
 * shared primitives can be tested in isolation.
 */
export * from "@testing-library/react";

/**
 * Runs axe-core against a rendered DOM node and returns its violations, so tests
 * can assert `expect(await getA11yViolations(container)).toEqual([])`.
 */
export async function getA11yViolations(
  container: Element = document.body,
  disableRules: string[] = [],
): Promise<axe.Result[]> {
  const rules: axe.RunOptions["rules"] = {
    // Colour-contrast needs real rendering; jsdom can't compute it reliably.
    "color-contrast": { enabled: false },
  };
  for (const rule of disableRules) {
    rules[rule] = { enabled: false };
  }
  const results = await axe.run(container, { rules });
  return results.violations;
}
