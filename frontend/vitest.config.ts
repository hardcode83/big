import { fileURLToPath } from "node:url";
import { configDefaults, defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { playwright } from "@vitest/browser-playwright";

/**
 * Two projects, because the two suites need two different definitions of «the
 * DOM» (`shell-topbar-overflow-360`, design D6).
 *
 * `node` is the suite that has always existed: jsdom, which does no layout, so
 * `scrollWidth` there is always 0. `browser` is the 360px overflow guard of R5,
 * which has to measure a real one — it runs a single file in Chromium through
 * Playwright and is kept out of `npm test` on purpose, so the everyday suite
 * never needs a browser binary. `npm run test:layout` is the one that does.
 *
 * The plugin list and the aliases are repeated per project rather than declared
 * once at the root: with `projects`, the root config contributes no Vite
 * configuration to them.
 */

const alias = {
  "@": fileURLToPath(new URL("./", import.meta.url)),
  "server-only": fileURLToPath(
    new URL("./test/stubs/server-only.ts", import.meta.url),
  ),
};

/** The single naming rule that routes a file to one project or the other. */
const LAYOUT_TESTS = "**/*.browser.test.{ts,tsx}";

export default defineConfig({
  test: {
    projects: [
      {
        plugins: [react()],
        resolve: { alias },
        test: {
          name: "node",
          environment: "jsdom",
          globals: true,
          setupFiles: ["./test/setup.ts"],
          include: ["**/*.test.{ts,tsx}"],
          // Spreading the defaults back in matters: `exclude` replaces them
          // rather than adding to them, and dropping `**/node_modules/**` would
          // hand vitest the dependency tree.
          exclude: [...configDefaults.exclude, LAYOUT_TESTS],
        },
      },
      {
        plugins: [react()],
        resolve: { alias },
        test: {
          name: "browser",
          globals: true,
          setupFiles: ["./test/browser-setup.ts"],
          include: [LAYOUT_TESTS],
          browser: {
            enabled: true,
            provider: playwright(),
            headless: true,
            // A red run here is a number, not a picture: R5.3 makes the failure
            // message name the composition and the measured width, and the
            // screenshots would otherwise be written into `features/`.
            screenshotFailures: false,
            instances: [{ browser: "chromium" }],
          },
        },
      },
    ],
  },
});
