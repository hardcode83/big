import { beforeAll, describe, expect, it } from "vitest";
import { ESLint } from "eslint";

/**
 * Verifies the dependency-boundary rules of design D2 are actually enforced by
 * eslint.config.mjs. Uses synthetic source (no business features) linted
 * against a representative filePath so the right config object applies.
 */
const eslint = new ESLint();

// The first lint resolves the whole Next flat config (slow); warm it up once so
// the individual assertions stay well within the default timeout.
beforeAll(async () => {
  await eslint.lintText("export const x = 1;\n", { filePath: "warmup.ts" });
}, 30000);

async function boundaryErrors(code: string, filePath: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath });
  return result.messages
    .filter((m) => m.ruleId === "no-restricted-imports")
    .map((m) => m.message);
}

describe("dependency boundaries (D2)", () => {
  it("forbids components/ importing from features/", async () => {
    const errors = await boundaryErrors(
      `import { x } from "@/features/shell/navigation/route-registry";\nexport const y = x;\n`,
      "components/ui/button.tsx",
    );
    expect(errors.length).toBeGreaterThan(0);
  });

  it("forbids lib/ importing from app/", async () => {
    const errors = await boundaryErrors(
      `import { x } from "@/app/providers";\nexport const y = x;\n`,
      "lib/api/client.ts",
    );
    expect(errors.length).toBeGreaterThan(0);
  });

  it("forbids a feature reaching into another feature's internals", async () => {
    const errors = await boundaryErrors(
      `import { x } from "@/features/other/internal/thing";\nexport const y = x;\n`,
      "features/shell/components/topbar.tsx",
    );
    expect(errors.length).toBeGreaterThan(0);
  });

  it("allows app/ to compose a feature's public entry point", async () => {
    const errors = await boundaryErrors(
      `import { x } from "@/features/shell";\nexport const y = x;\n`,
      "app/(workspace)/layout.tsx",
    );
    expect(errors).toEqual([]);
  });

  it("allows features/ to import shared components and lib", async () => {
    const errors = await boundaryErrors(
      `import { a } from "@/components/ui/button";\nimport { b } from "@/lib/utils";\nexport const y = { a, b };\n`,
      "features/shell/components/topbar.tsx",
    );
    expect(errors).toEqual([]);
  });
});
