import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { render, renderHook, screen } from "@/test/render";
import { buildPublicRuntimeConfig } from "@/lib/config/public";
import {
  RuntimeConfigProvider,
  useRuntimeConfig,
} from "@/lib/config/runtime-config-provider";

describe("public runtime config (D15)", () => {
  const original = { ...process.env };

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_APP_ENV;
    delete process.env.BACKEND_INTERNAL_URL;
    delete process.env.NEXT_PUBLIC_APP_VERSION;
    delete process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT;
  });

  afterEach(() => {
    process.env = { ...original };
  });

  it("exposes the allowlisted public fields with the es default locale", () => {
    process.env.NEXT_PUBLIC_APP_ENV = "staging";
    process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0+2026-07-30.a2f3c1d";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "a2f3c1d";
    const config = buildPublicRuntimeConfig();
    expect(config).toEqual({
      appEnv: "staging",
      defaultLocale: "es",
      featureFlags: {},
      appVersion: "0.1.0+2026-07-30.a2f3c1d",
      buildCommitShort: "a2f3c1d",
    });
  });

  it("boots without a backend or NEXT_PUBLIC_APP_ENV set", () => {
    expect(() => buildPublicRuntimeConfig()).not.toThrow();
    expect(buildPublicRuntimeConfig().appEnv).toBe("development");
  });

  it("renders empty build identity when nothing was baked, without throwing", () => {
    // A local `npm run dev` and an image built without build-args both land here. The
    // shell has to keep working; only the badge degrades (R2.7).
    const config = buildPublicRuntimeConfig();
    expect(config.appVersion).toBe("");
    expect(config.buildCommitShort).toBe("");
  });

  it("never leaks server-only values or non-allowlisted env into the snapshot", () => {
    process.env.BACKEND_INTERNAL_URL = "http://backend:8000";
    process.env.ENCRYPTION_KEY = "super-secret-value";
    process.env.NEXT_PUBLIC_SNEAKY = "should-not-appear";

    const serialized = JSON.stringify(buildPublicRuntimeConfig());

    expect(serialized).not.toContain("http://backend:8000");
    expect(serialized).not.toContain("super-secret-value");
    expect(serialized).not.toContain("should-not-appear");
    expect(Object.keys(buildPublicRuntimeConfig())).toEqual([
      "appEnv",
      "defaultLocale",
      "featureFlags",
      "appVersion",
      "buildCommitShort",
    ]);
  });

  it("keeps the repository identity out of the browser snapshot", () => {
    // A standing guard (R2.4), not a description of today's build: none of these names
    // is read anywhere in the current code — the provenance scope moved out to
    // `app-version-provenance`. It stays because it FAILS the moment anyone routes one
    // of them into the public snapshot, which reaches every anonymous surface. That is
    // exactly the leak this change was trimmed to remove, so the guard outlives it.
    process.env.REPO_URL = "https://github.com/autohostai-labs/AutoHostAI";
    process.env.BUILD_COMMIT = "a2f3c1d3f9b2000000000000000000000000000f";
    process.env.BUILD_PR = "42";
    process.env.BUILD_RUN_ID = "1234567890";
    process.env.BUILD_REF = "refs/heads/main";

    const serialized = JSON.stringify(buildPublicRuntimeConfig());

    expect(serialized).not.toContain("github.com");
    expect(serialized).not.toContain("autohostai-labs");
    expect(serialized).not.toContain(
      "a2f3c1d3f9b2000000000000000000000000000f",
    );
    expect(serialized).not.toContain("1234567890");
    expect(serialized).not.toContain("refs/heads/main");
  });

  it("keeps the feature-flag registry empty and frozen", () => {
    const { featureFlags } = buildPublicRuntimeConfig();
    expect(featureFlags).toEqual({});
    expect(Object.isFrozen(featureFlags)).toBe(true);
  });
});

describe("RuntimeConfigProvider", () => {
  it("delivers the snapshot to consumers", () => {
    function Probe() {
      const { appEnv } = useRuntimeConfig();
      return <span>{appEnv}</span>;
    }
    render(
      <RuntimeConfigProvider
        config={{
          appEnv: "test",
          defaultLocale: "es",
          featureFlags: {},
          appVersion: "",
          buildCommitShort: "",
        }}
      >
        <Probe />
      </RuntimeConfigProvider>,
    );
    expect(screen.getByText("test")).toBeInTheDocument();
  });

  it("throws when used outside the provider", () => {
    expect(() => renderHook(() => useRuntimeConfig())).toThrow(
      /RuntimeConfigProvider/,
    );
  });
});
