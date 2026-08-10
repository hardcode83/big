import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "../..");
const forbidden = [
  "APP_PROVENANCE_",
  "repository_url",
  "pull_request_number",
  "actions_run_id",
  "commit_sha",
];
const publicBoundaries = [
  "app/layout.tsx",
  "lib/config/public.ts",
  "app/(public)/login/page.tsx",
  "app/(guest)/guest/[token]/page.tsx",
  "app/(guest)/guest/[token]/layout.tsx",
];

describe("private provenance disclosure boundaries", () => {
  it("keep private fields out of public config and anonymous routes", () => {
    for (const relativePath of publicBoundaries) {
      const source = readFileSync(resolve(root, relativePath), "utf8");
      for (const field of forbidden) expect(source, relativePath).not.toContain(field);
    }
  });
});
