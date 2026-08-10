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
  readFileSync(resolve(root, "../backend/app/provenance/provenance-contract.json"), "utf8"),
) as {
  fields: ContractField[];
  public_forbidden_fields: string[];
};
const buildIdentityContract = JSON.parse(
  readFileSync(resolve(root, "lib/config/build-identity-contract.json"), "utf8"),
) as { basePattern: string; datePattern: string; commitShortPattern: string };
const deployFixture = JSON.parse(
  readFileSync(resolve(root, "../backend/tests/fixtures/build-identity-provenance.json"), "utf8"),
) as {
  app_version: string;
  repository_url: string;
  pull_request_number: number;
  commit_sha: string;
  actions_run_id: number;
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

function jobBlocks(): Map<string, string> {
  const jobsStart = workflow.indexOf("jobs:\n") + "jobs:\n".length;
  const jobs = workflow.slice(jobsStart);
  const blocks = new Map<string, string>();
  const matches = [...jobs.matchAll(/^  ([a-z-]+):\n/gm)];
  for (let index = 0; index < matches.length; index += 1) {
    const match = matches[index];
    const start = match.index ?? 0;
    const end = matches[index + 1]?.index ?? jobs.length;
    blocks.set(match[1], jobs.slice(start, end));
  }
  return blocks;
}

function declaredNeeds(block: string): Set<string> {
  const match = block.match(/^    needs:\s*(.+)$/m);
  if (!match) return new Set();
  const value = match[1].trim();
  if (value.startsWith("[")) {
    return new Set(value.slice(1, -1).split(",").map((item) => item.trim()));
  }
  return new Set([value]);
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

  it("requires a direct needs edge for every needs output reference", () => {
    const blocks = jobBlocks();
    for (const [job, block] of blocks) {
      const needs = declaredNeeds(block);
      for (const match of block.matchAll(/needs\.([a-z-]+)\.outputs\.([a-z_]+)/g)) {
        expect(needs, `${job} must directly need ${match[1]}`).toContain(match[1]);
      }
    }
    const deploy = blocks.get("deploy");
    expect(deploy).toBeDefined();
    expect(declaredNeeds(deploy ?? "")).toContain("provenance");
    expect(deploy).not.toMatch(/needs\.provenance\.outputs\.[a-z_]+:-/);
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
      const deploy = jobBlocks().get("deploy") ?? "";
      expect(deploy, field.name).toContain(
        `APP_PROVENANCE_${field.name.toUpperCase()}=` + `\${{ needs.provenance.outputs.${field.name} }}`,
      );
      expect(backend).toContain(
        `${field.environment}: $` + `{${field.environment}:-}`,
      );
      for (const publicService of [frontend, worker, beat, migrate, cloudflared]) {
        expect(publicService).not.toContain(field.environment);
      }
    }
    expect(frontend).not.toContain("repository_url");
    expect(frontend).not.toContain("APP_PROVENANCE_");
    expect(frontend).not.toContain("org.opencontainers.image.source");
    expect(frontend).not.toContain("org.opencontainers.image.revision=${{ github.sha }}");
    expect(frontend).not.toContain("${{ needs.provenance.outputs.repository_url }}");
    expect(frontend).not.toContain("${{ needs.provenance.outputs.commit_sha }}");
    expect(readFileSync(resolve(root, "app/(workspace)/layout.tsx"), "utf8"))
      .toMatch(/<AuthGuard><WorkspaceShell>/);
  });

  it("protects the frontend image boundary in the build-frontend job itself", () => {
    const frontendBuild = jobBlocks().get("build-frontend");
    expect(frontendBuild).toBeDefined();
    const job = frontendBuild ?? "";

    expect(job).toContain("org.opencontainers.image.revision=${{ needs.provenance.outputs.commit_short }}");
    expect(job).toContain("org.opencontainers.image.version=${{ needs.provenance.outputs.version }}");
    expect(job).toContain("org.opencontainers.image.created=${{ needs.provenance.outputs.built_at }}");
    expect(job).toContain("NEXT_PUBLIC_APP_VERSION=${{ needs.provenance.outputs.version }}");
    expect(job).toContain("NEXT_PUBLIC_BUILD_COMMIT_SHORT=${{ needs.provenance.outputs.commit_short }}");

    const labels = job.match(/labels: \|\n([\s\S]*?)\n\s+tags:/)?.[1] ?? "";
    const buildArgs = job.match(/build-args: \|\n([\s\S]*?)\n\s+labels:/)?.[1] ?? "";
    const environment = job.match(/^\s{8}env:\n([\s\S]*?)(?=^\s{8}\S|$)/m)?.[1] ?? "";
    for (const [surfaceName, surface] of Object.entries({ labels, buildArgs, environment })) {
      expect(surface, `${surfaceName} must not contain private repository URL`).not.toMatch(
        /repository_url|org\.opencontainers\.image\.source/,
      );
      expect(surface, `${surfaceName} must not contain private provenance env`).not.toMatch(
        /APP_PROVENANCE_|pull_request_number|actions_run_id|GITHUB_RUN_ID/,
      );
      expect(surface, `${surfaceName} must not contain private SHA`).not.toMatch(
        /commit_sha|org\.opencontainers\.image\.revision=.*github\.sha|NEXT_PUBLIC_COMMIT_SHA/,
      );
    }
    expect(job).not.toMatch(/NEXT_PUBLIC_(?:REPOSITORY_URL|PROVENANCE|PULL_REQUEST|RUN_ID)/);
  });

  it("keeps the public build identity congruent with the authenticated response", () => {
    expect(deployFixture.app_version).toMatch(
      new RegExp(
        `^${buildIdentityContract.basePattern}\\+${buildIdentityContract.datePattern}\\.${buildIdentityContract.commitShortPattern}$`,
      ),
    );
    const producerOutput = { version: deployFixture.app_version };
    const resolveOutput = (expression: string): string => {
      const match = expression.match(/needs\.provenance\.outputs\.([a-z_]+)/);
      expect(match).not.toBeNull();
      const value = producerOutput[match?.[1] as keyof typeof producerOutput];
      expect(value).toBeDefined();
      return value;
    };
    const frontendBuild = jobBlocks().get("build-frontend") ?? "";
    const frontendVersion = resolveOutput(
      frontendBuild.match(/NEXT_PUBLIC_APP_VERSION=\$\{\{ ([^}]+) \}\}/)?.[1] ?? "",
    );
    const deploy = jobBlocks().get("deploy") ?? "";
    const backendVersion = resolveOutput(
      deploy.match(/echo "APP_VERSION=\$\{\{ ([^}]+) \}\}"/)?.[1] ?? "",
    );
    expect(frontendVersion).toBe(producerOutput.version);
    expect(backendVersion).toBe(producerOutput.version);
    expect(frontendVersion).toBe(deployFixture.app_version);
    expect(backendVersion).toBe(deployFixture.app_version);
    expect(compose).toContain("APP_VERSION: ${APP_VERSION:?Falta APP_VERSION}");
    expect(readFileSync(resolve(root, "../backend/app/provenance/api/router.py"), "utf8")).toContain(
      "settings.app_version.strip() or package_version()",
    );
  });

  it("resolves every private workflow output from the shared deploy fixture", () => {
    const fixtureByField = {
      repository_url: deployFixture.repository_url,
      pull_request_number: String(deployFixture.pull_request_number),
      commit_sha: deployFixture.commit_sha,
      actions_run_id: String(deployFixture.actions_run_id),
    };
    const deploy = jobBlocks().get("deploy") ?? "";
    for (const [field, expected] of Object.entries(fixtureByField)) {
      expect(workflow).toContain(
        `${field}: $` + `{{ steps.compose.outputs.${field} }}`,
      );
      expect(deploy).toContain(
        `APP_PROVENANCE_${field.toUpperCase()}=$` +
          `{{ needs.provenance.outputs.${field} }}`,
      );
      expect(expected).toBe(fixtureByField[field as keyof typeof fixtureByField]);
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
