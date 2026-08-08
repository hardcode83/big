import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";

import { buildPublicRuntimeConfig } from "./public";
import {
  composeBuildIdentity,
  validateBuildIdentity,
} from "../../scripts/build-identity.mjs";

const scriptPath = join(process.cwd(), "scripts/build-identity.mjs");
const temporaryDirectories: string[] = [];
const fullSha = `a2f3c1d${"0".repeat(33)}`;
const builtAt = "2026-07-31T12:34:56Z";

afterEach(() => {
  delete process.env.NEXT_PUBLIC_APP_VERSION;
  delete process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT;
  for (const directory of temporaryDirectories.splice(0)) rmSync(directory, { recursive: true });
});

describe("build identity contract", () => {
  it("composes a production identity accepted by the public snapshot", () => {
    const identity = composeBuildIdentity({
      base: "0.1.0",
      sha: fullSha,
      builtAt,
      repoUrl: "https://github.com/autohostai-labs/AutoHostAI",
    });

    process.env.NEXT_PUBLIC_APP_VERSION = identity.version;
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = identity.commitShort;

    expect(identity).toMatchObject({
      version: "0.1.0+2026-07-31.a2f3c1d",
      commitShort: "a2f3c1d",
      builtAt,
    });
    expect(buildPublicRuntimeConfig()).toMatchObject({
      appVersion: identity.version,
      buildCommitShort: identity.commitShort,
    });
  });

  it.each([
    ["a commit of the wrong length", { commitShort: "a2f3c1d0" }],
    ["a mismatched commit suffix", { version: "0.1.0+2026-07-31.b3e4d5f" }],
    ["a non-calendar date", { version: "0.1.0+2026-02-31.a2f3c1d" }],
    ["a base outside X.Y.Z", { version: "0.1.0-beta+2026-07-31.a2f3c1d" }],
  ])("rejects %s in final outputs", (_name, mutation) => {
    const identity = {
      version: "0.1.0+2026-07-31.a2f3c1d",
      commitShort: "a2f3c1d",
      builtAt,
      repoUrl: "https://github.com/autohostai-labs/AutoHostAI",
      ...mutation,
    };

    expect(() => validateBuildIdentity(identity)).toThrow();
  });

  it("accepts the local pair without requiring production metadata", () => {
    process.env.NEXT_PUBLIC_APP_VERSION = "local";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "";

    expect(buildPublicRuntimeConfig()).toMatchObject({
      appVersion: "local",
      buildCommitShort: "",
    });
  });

  it("writes all CLI outputs only after validation succeeds", () => {
    const directory = mkdtempSync(join(tmpdir(), "build-identity-contract-"));
    temporaryDirectories.push(directory);
    const versionPath = join(directory, "VERSION");
    const outputPath = join(directory, "outputs");
    writeFileSync(versionPath, "0.1.0\n");
    writeFileSync(outputPath, "");

    const result = spawnSync(process.execPath, [scriptPath], {
      env: {
        ...process.env,
        VERSION_FILE: versionPath,
        GITHUB_SHA: fullSha,
        GITHUB_SERVER_URL: "https://github.com",
        GITHUB_REPOSITORY: "autohostai-labs/AutoHostAI",
        GITHUB_OUTPUT: outputPath,
      },
      encoding: "utf8",
    });

    expect(result.status).toBe(0);
    expect(readFileSync(outputPath, "utf8")).toContain("version=0.1.0+20");
    expect(readFileSync(outputPath, "utf8")).toContain("commit_short=a2f3c1d");

    writeFileSync(versionPath, "0.1.0-beta\n");
    writeFileSync(outputPath, "");
    const failed = spawnSync(process.execPath, [scriptPath], {
      env: { ...process.env, VERSION_FILE: versionPath, GITHUB_SHA: fullSha, GITHUB_OUTPUT: outputPath },
      encoding: "utf8",
    });
    expect(failed.status).not.toBe(0);
    expect(readFileSync(outputPath, "utf8")).toBe("");
  });

  it("keeps the CD workflow and compose defaults on the same contract", () => {
    const workflow = readFileSync(join(process.cwd(), "..", ".github/workflows/deploy-dev.yml"), "utf8");
    const compose = readFileSync(join(process.cwd(), "..", "docker-compose.yml"), "utf8");
    const provenanceStep = workflow.match(/id: compose([\s\S]*?)\n\n  # --- Build/)?.[1] ?? "";

    expect(workflow).toContain("run: node frontend/scripts/build-identity.mjs");
    expect(provenanceStep).not.toMatch(/run:\s*\|/);
    expect(provenanceStep).not.toMatch(/version=.*GITHUB_SHA|commit_short=.*GITHUB_SHA/);
    expect(workflow).toContain("NEXT_PUBLIC_APP_VERSION=${{ needs.provenance.outputs.version }}");
    expect(workflow).toContain("NEXT_PUBLIC_BUILD_COMMIT_SHORT=${{ needs.provenance.outputs.commit_short }}");
    expect(compose).toContain("NEXT_PUBLIC_APP_VERSION: ${NEXT_PUBLIC_APP_VERSION:-local}");
    expect(compose).toContain("NEXT_PUBLIC_BUILD_COMMIT_SHORT: ${NEXT_PUBLIC_BUILD_COMMIT_SHORT:-}");
  });
});
