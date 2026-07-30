import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { render, screen } from "@/test/render";
import {
  VersionBadge,
  formatBuildVersion,
} from "@/features/shell/components/version-badge";

const LABELS = {
  label: "Versión desplegada",
  unknown: "versión desconocida",
} as const;

describe("formatBuildVersion (OQ2)", () => {
  it("shortens the canonical string to base + short sha", () => {
    // The canonical form keeps the build date because /version and the OCI labels
    // report it; the badge drops it to stay readable on a phone.
    expect(formatBuildVersion("0.1.0+2026-07-30.a2f3c1d", "a2f3c1d")).toBe(
      "0.1.0+a2f3c1d",
    );
  });

  it("falls back to the base alone when no short sha was baked", () => {
    expect(formatBuildVersion("0.1.0+2026-07-30.a2f3c1d", "")).toBe("0.1.0");
  });

  it("handles a value with no build metadata, like the `local` of dev", () => {
    expect(formatBuildVersion("local", "")).toBe("local");
  });

  it("returns null when nothing was baked, so the caller can localize it", () => {
    // Returning "" would put an empty badge on screen; null lets the component choose
    // the translated "unknown" instead (R3.3 — it must never look like a real version).
    expect(formatBuildVersion("", "")).toBeNull();
    expect(formatBuildVersion("   ", "a2f3c1d")).toBeNull();
  });

  it.each(["+", "  +abc123", "++", " + "])(
    "returns null for %j, whose base is empty even though the string is not",
    (malformed) => {
      // The gap the QA panel found: these are non-empty, so the early return misses
      // them, and the old code returned "" — which `??` does not catch, so the badge
      // rendered BLANK instead of saying "unknown". The base needs its own check.
      expect(formatBuildVersion(malformed, "")).toBeNull();
      expect(formatBuildVersion(malformed, "a2f3c1d")).toBeNull();
    },
  );

  it("ignores surrounding whitespace in either input", () => {
    expect(formatBuildVersion(" 0.1.0+x.y ", " a2f3c1d ")).toBe(
      "0.1.0+a2f3c1d",
    );
  });
});

describe("VersionBadge (R3.1-R3.3, R3.6)", () => {
  const original = { ...process.env };

  beforeEach(() => {
    delete process.env.NEXT_PUBLIC_APP_VERSION;
    delete process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT;
  });

  afterEach(() => {
    process.env = { ...original };
  });

  function renderBadge() {
    return render(<VersionBadge labels={LABELS} />);
  }

  it("renders the shortened version from the baked snapshot", () => {
    process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0+2026-07-30.a2f3c1d";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "a2f3c1d";

    renderBadge();

    expect(screen.getByTestId("version-badge")).toHaveTextContent(
      "0.1.0+a2f3c1d",
    );
  });

  it("says so in the locale the shell resolved when no identity was baked", () => {
    renderBadge();

    expect(screen.getByTestId("version-badge")).toHaveTextContent(
      "versión desconocida",
    );
  });

  it("carries an accessible name that states what the value is", () => {
    process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0+2026-07-30.a2f3c1d";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "a2f3c1d";

    renderBadge();

    expect(
      screen.getByLabelText("Versión desplegada: 0.1.0+a2f3c1d"),
    ).toBeInTheDocument();
  });

  it("never renders the repository URL, the full sha, the PR or the run id", () => {
    // R3.6 / design D6: these are baked as plain ENV, server-only. Even with all of
    // them present in the environment the badge must not surface any of them — it reads
    // the public snapshot, which does not carry them.
    process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0+2026-07-30.a2f3c1d";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "a2f3c1d";
    process.env.REPO_URL = "https://github.com/autohostai-labs/AutoHostAI";
    process.env.BUILD_COMMIT = "a2f3c1d3f9b2000000000000000000000000000f";
    process.env.BUILD_PR = "42";
    process.env.BUILD_RUN_ID = "1234567890";

    const { container } = renderBadge();

    expect(container.textContent).not.toContain("github.com");
    expect(container.textContent).not.toContain("autohostai-labs");
    expect(container.textContent).not.toContain(
      "a2f3c1d3f9b2000000000000000000000000000f",
    );
    expect(container.textContent).not.toContain("1234567890");
    // `innerHTML`, not `textContent`: a leak into an attribute (an `aria-label` or a
    // `title`) would not show up in the text. And the PR is asserted as `#42`/`pr=`
    // rather than a bare "42", which would false-fail the day a real version reads
    // `0.1.42+…` — precision by accident is not precision (QA panel, finding 3).
    expect(container.innerHTML).not.toContain("#42");
    expect(container.innerHTML).not.toContain("pr=");
    expect(container.innerHTML).not.toContain("BUILD_PR");
  });
});
