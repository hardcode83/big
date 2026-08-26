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
    delete process.env.NEXT_PUBLIC_API_BASE_URL;
    delete process.env.BACKEND_INTERNAL_URL;
    delete process.env.NEXT_PUBLIC_APP_VERSION;
    delete process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT;
    delete process.env.NEXT_PUBLIC_APP_URL;
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
      apiBaseUrl: "",
      appEnv: "staging",
      defaultLocale: "es",
      featureFlags: {},
      appVersion: "0.1.0+2026-07-30.a2f3c1d",
      buildCommitShort: "a2f3c1d",
      appUrl: "",
    });
  });

  it("boots without a backend or NEXT_PUBLIC_APP_ENV set", () => {
    expect(() => buildPublicRuntimeConfig()).not.toThrow();
    expect(buildPublicRuntimeConfig().appEnv).toBe("development");
  });

  it("allows an explicit public API origin without exposing server config", () => {
    process.env.NEXT_PUBLIC_API_BASE_URL = "https://api.example.com";
    process.env.BACKEND_INTERNAL_URL = "http://backend:8000";

    const config = buildPublicRuntimeConfig();

    expect(config.apiBaseUrl).toBe("https://api.example.com");
    expect(JSON.stringify(config)).not.toContain("backend:8000");
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
      "apiBaseUrl",
      "appEnv",
      "defaultLocale",
      "featureFlags",
      "appVersion",
      "buildCommitShort",
      "appUrl",
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

  it.each([
    ["the full 40-char SHA in place of the abbreviation", "0.1.0+2026-07-30.a2f3c1d3f9b2000000000000000000000000000f"],
    ["a run id appended after the commit", "0.1.0+2026-07-30.a2f3c1d.1234567890"],
    // Decimal digits are a SUBSET of hex, so a lenient `{7,12}` bound accepted an Actions
    // run id — 11 digits — as if it were a commit. That was the security panel's finding
    // against my own first attempt; the bound is pinned to exactly 7 for this reason.
    ["a run id substituted INTO the commit slot", "0.1.0+2026-07-30.30618352968"],
    ["a branch ref as metadata", "0.1.0+refs/heads/main"],
    ["a `+`-smuggled suffix", "0.1.0+2026-07-30.a2f3c1d+dirty"],
    ["a base that is not a version at all", "https://github.com/autohostai-labs/AutoHostAI"],
    // The base half of the same finding, filed after the metadata half was already tight.
    // A cap on length only limits how much of a secret leaks; it does not stop one — the
    // security panel proved the old `{0,31}` cap was incidental by widening it to `{0,63}`
    // and watching the whole suite stay green with a bare 40-char SHA admitted.
    ["a run id in the base", "0.1.0-30618352968+2026-07-31.5872022"],
    ["a PR number in the base", "0.1.0-pr1234+2026-07-31.5872022"],
    ["a bare 40-char SHA", "a2f3c1d3f9b2000000000000000000000000000f"],
    ["a 32-char hex prefix that still resolves to a commit", "8a34fec66181ee2aa1969864bc384ba4"],
    ["a branch name", "feature-my-branch"],
    // The date slot was the last component still bounded by digit COUNT rather than by value:
    // `\d{4}-\d{2}-\d{2}` is eight free decimal digits, enough room for numeric provenance.
    // Found at feature-scale review, and it is the same mistake as the base one slot along.
    ["numeric provenance in the date slot", "0.1.0+3061-83-52.9680000"],
    ["a month that does not exist", "0.1.0+2026-13-01.5872022"],
    ["a day that does not exist", "0.1.0+2026-07-32.5872022"],
    ["a zero month", "0.1.0+2026-00-15.5872022"],
    ["a day that does not exist in February", "0.1.0+2026-02-29.5872022"],
    ["a day that does not exist in April", "0.1.0+2026-04-31.5872022"],
  ])("drops %s instead of letting it into the snapshot", (_why, widened) => {
    // This is the layer that matters, and the reason it is here and not in `VersionBadge`:
    // React serializes this object as a prop into the RSC payload of the root layout, so
    // whatever it contains travels in the server-rendered HTML of EVERY surface — including
    // `/guest/<token>`, the one the capability spec singles out as the surface that must not
    // receive it ("Alcance de la divulgación, aceptado", and the prohibition on the full SHA,
    // the PR number, the run id and the ref). Validating in the badge only cleaned the pixels
    // the operator sees; the architecture panel reproduced the value still sitting in the page
    // source with a real `next build`.
    process.env.NEXT_PUBLIC_APP_VERSION = widened;

    const config = buildPublicRuntimeConfig();

    expect(config.appVersion).toBe("");
    expect(JSON.stringify(config)).not.toContain(widened);
  });

  it.each([
    ["the full 40-char SHA", "a2f3c1d3f9b2000000000000000000000000000f"],
    ["a run id", "30618352968"],
    ["a branch ref", "refs/heads/main"],
  ])("drops %s from the short-commit field too", (_why, widened) => {
    // The second half of the same finding, and the sharper one: `buildCommitShort` is where
    // every degradation LANDS, and the CD composes it on the line adjacent to the version
    // (`commit_short=${GITHUB_SHA:0:7}`). The single edit that widens one widens both, so
    // validating only the version left the fallback path publishing the full SHA.
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = widened;

    const config = buildPublicRuntimeConfig();

    expect(config.buildCommitShort).toBe("");
    expect(JSON.stringify(config)).not.toContain(widened);
  });

  it("still admits what the CD actually composes, and the `local` of dev", () => {
    // The boundary has to be tight without breaking the two shapes that are legitimate —
    // otherwise the badge silently loses the date that is this change's whole point.
    process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0+2026-07-31.5872022";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "5872022";
    expect(buildPublicRuntimeConfig()).toMatchObject({
      appVersion: "0.1.0+2026-07-31.5872022",
      buildCommitShort: "5872022",
    });

    process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "";
    expect(buildPublicRuntimeConfig()).toMatchObject({
      appVersion: "0.1.0",
      buildCommitShort: "",
    });

    process.env.NEXT_PUBLIC_APP_VERSION = "local";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "";
    expect(buildPublicRuntimeConfig()).toMatchObject({
      appVersion: "local",
      buildCommitShort: "",
    });
  });

  it("keeps the feature-flag registry empty and frozen", () => {
    const { featureFlags } = buildPublicRuntimeConfig();
    expect(featureFlags).toEqual({});
    expect(Object.isFrozen(featureFlags)).toBe(true);
  });

  it("falls back to empty string when NEXT_PUBLIC_APP_URL is unset or off-shape", () => {
    expect(buildPublicRuntimeConfig().appUrl).toBe("");

    process.env.NEXT_PUBLIC_APP_URL = "   ";
    expect(buildPublicRuntimeConfig().appUrl).toBe("");

    process.env.NEXT_PUBLIC_APP_URL = "not-a-url";
    expect(buildPublicRuntimeConfig().appUrl).toBe("");

    process.env.NEXT_PUBLIC_APP_URL = "/relative/only";
    expect(buildPublicRuntimeConfig().appUrl).toBe("");

    process.env.NEXT_PUBLIC_APP_URL = "ftp://example.com";
    expect(buildPublicRuntimeConfig().appUrl).toBe("");

    process.env.NEXT_PUBLIC_APP_URL = "javascript:alert(1)";
    expect(buildPublicRuntimeConfig().appUrl).toBe("");
  });

  it("passes a valid absolute URL through unchanged", () => {
    process.env.NEXT_PUBLIC_APP_URL = "https://app.autohostai.com/";
    const config = buildPublicRuntimeConfig();
    expect(config.appUrl).toBe("https://app.autohostai.com/");

    process.env.NEXT_PUBLIC_APP_URL = "http://localhost:3000";
    expect(buildPublicRuntimeConfig().appUrl).toBe("http://localhost:3000/");
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
          apiBaseUrl: "",
          appEnv: "test",
          defaultLocale: "es",
          featureFlags: {},
          appVersion: "",
          buildCommitShort: "",
          appUrl: "",
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
