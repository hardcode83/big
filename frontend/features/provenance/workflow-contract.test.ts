import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

type ContractField = {
  name: string;
  environment: string;
  pattern?: string;
  minimum?: number;
};

const root = resolve(import.meta.dirname, "../..");
const contract = JSON.parse(
  readFileSync(resolve(root, "../scripts/provenance-contract.json"), "utf8"),
) as {
  fields: ContractField[];
  public_forbidden_fields: string[];
};
const workflow = readFileSync(resolve(root, "../.github/workflows/deploy-dev.yml"), "utf8");
const frontendWorkflow = readFileSync(
  resolve(root, "../.github/workflows/frontend-tests.yml"),
  "utf8",
);
const compose = readFileSync(resolve(root, "../docker-compose.deploy.yml"), "utf8");
const openapi = JSON.parse(readFileSync(resolve(root, "../backend/openapi.json"), "utf8")) as {
  components: { schemas: Record<string, { properties: Record<string, Record<string, unknown>> }> };
};

function serviceBlock(service: string, nextService: string): string {
  const start = compose.indexOf(`  ${service}:`);
  const end = compose.indexOf(`  ${nextService}:`, start);
  expect(start, `missing compose service ${service}`).toBeGreaterThanOrEqual(0);
  return compose.slice(start, end < 0 ? undefined : end);
}

describe("producer/consumer provenance contract", () => {
  it("uses only declared canonical provenance outputs", () => {
    const declaredOutputs = new Set(
      [...workflow.matchAll(/^\s{6}([a-z_]+): \$\{\{ steps\.compose\.outputs\.([a-z_]+) \}\}$/gm)].map(
        ([, output, producer]) => {
          expect(producer).toBe(output);
          return output;
        },
      ),
    );
    const consumedOutputs = [
      ...workflow.matchAll(/needs\.provenance\.outputs\.([a-z_]+)/g),
    ].map(([, output]) => output);

    expect(workflow).not.toContain("repo_url");
    expect(consumedOutputs.length).toBeGreaterThan(0);
    for (const output of consumedOutputs) {
      expect(declaredOutputs, `undeclared provenance output: ${output}`).toContain(output);
    }
  });

  it("wires every canonical field through the real workflow and backend-only deploy path", () => {
    const backend = serviceBlock("backend", "worker");
    const frontend = serviceBlock("frontend", "cloudflared");
    const worker = serviceBlock("worker", "beat");
    const beat = serviceBlock("beat", "frontend");
    const migrate = serviceBlock("migrate", "backend");
    const cloudflared = compose.slice(compose.indexOf("  cloudflared:"));

    for (const field of contract.fields) {
      expect(workflow).toContain(
        `${field.name}: $` + `{{ steps.compose.outputs.${field.name} }}`,
      );
      expect(workflow).toContain(`echo "${field.name}=$`);
      expect(workflow).toContain(
        `${field.environment}=$` + `{{ needs.provenance.outputs.${field.name} }}`,
      );
      expect(backend).toContain(
        `${field.environment}: $` + `{${field.environment}:-}`,
      );
      for (const publicService of [frontend, worker, beat, migrate, cloudflared]) {
        expect(publicService).not.toContain(field.environment);
      }
    }
  });

  it("keeps the OpenAPI schema aligned with canonical formats and atomic absence", () => {
    const schema = openapi.components.schemas.PrivateProvenanceResponse;
    expect(schema).toBeDefined();
    for (const field of contract.fields) {
      const property = schema.properties[field.name];
      expect(property, field.name).toBeDefined();
      if (field.pattern) expect(property.pattern).toBe(field.pattern);
      if (field.minimum) expect(property.minimum).toBe(field.minimum);
    }
    expect(frontendWorkflow).toContain("npm test -- --run features/provenance");
    expect(frontendWorkflow).toContain("npm run api:check");
    expect(frontendWorkflow).toContain("scripts/validate-provenance-contract.py --self-test");
    expect(workflow).toContain("scripts/validate-provenance-contract.py");
  });

  it("keeps every private field outside public source boundaries", () => {
    const publicBoundaries = [
      "app/layout.tsx",
      "lib/config/public.ts",
      "app/(public)/login/page.tsx",
      "app/(guest)/guest/[token]/page.tsx",
      "app/(guest)/guest/[token]/layout.tsx",
    ];
    for (const relativePath of publicBoundaries) {
      const source = readFileSync(resolve(root, relativePath), "utf8");
      for (const field of contract.public_forbidden_fields) {
        expect(source, `${relativePath}:${field}`).not.toContain(field);
      }
    }
  });

  it("keeps unsupported and ambiguous PR subjects as the canonical empty absence", () => {
    const extractor = resolve(root, "../.github/scripts/extract-pr.sh");
    const extract = (subject: string) =>
      execFileSync("bash", [extractor, subject], { encoding: "utf8" }).trim();

    expect(extract("Fix issue #44")).toBe("");
    expect(extract("Title (#46) extra (#47)")).toBe("");
    expect(extract("Merge pull request #42 from example/feature (#43)")).toBe("");
    expect(extract("Ship provenance metadata (#43)")).toBe("43");
  });
});
