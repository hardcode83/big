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
  });

  afterEach(() => {
    process.env = { ...original };
  });

  it("exposes the allowlisted public fields with the es default locale", () => {
    process.env.NEXT_PUBLIC_APP_ENV = "staging";
    const config = buildPublicRuntimeConfig();
    expect(config).toEqual({
      appEnv: "staging",
      defaultLocale: "es",
      featureFlags: {},
    });
  });

  it("boots without a backend or NEXT_PUBLIC_APP_ENV set", () => {
    expect(() => buildPublicRuntimeConfig()).not.toThrow();
    expect(buildPublicRuntimeConfig().appEnv).toBe("development");
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
    ]);
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
        config={{ appEnv: "test", defaultLocale: "es", featureFlags: {} }}
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
