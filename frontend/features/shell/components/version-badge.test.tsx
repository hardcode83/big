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

describe("formatBuildVersion", () => {
  it("shows the canonical string whole, build date included", () => {
    // This is the production shape: the CD bakes the canonical string AND the short sha,
    // so the assertion also pins that the sha is not appended a second time at the end.
    expect(formatBuildVersion("0.1.0+2026-07-30.a2f3c1d", "a2f3c1d")).toBe(
      "0.1.0+2026-07-30.a2f3c1d",
    );
  });

  it("does not need the short sha when the canonical string carries metadata", () => {
    // It used to compose `base + short sha` and therefore depended on the second argument;
    // now the date-bearing string is shown as-is and the sha inside it is enough.
    expect(formatBuildVersion("0.1.0+2026-07-30.a2f3c1d", "")).toBe(
      "0.1.0+2026-07-30.a2f3c1d",
    );
  });

  it("handles a value with no build metadata, like the `local` of dev", () => {
    expect(formatBuildVersion("local", "")).toBe("local");
  });

  it("appends the short sha only when there is no metadata to show", () => {
    // The remaining job of the second argument: `local` is not an identity, so a baked
    // sha is the only thing that distinguishes one dev image from another.
    expect(formatBuildVersion("local", "a2f3c1d")).toBe("local+a2f3c1d");
  });

  it.each(["0.1.0+", "0.1.0++", "0.1.0+   "])(
    "treats %j as having no metadata, since its `+` carries nothing",
    (empty) => {
      // Mirror image of the empty-base guard: showing `0.1.0+` would be the half-formed
      // version string the degradation rules forbid, so it degrades like `local` does.
      expect(formatBuildVersion(empty, "")).toBe("0.1.0");
      expect(formatBuildVersion(empty, "a2f3c1d")).toBe("0.1.0+a2f3c1d");
    },
  );

  it("returns null when nothing was baked, so the caller can localize it", () => {
    // Returning "" would put an empty badge on screen; null lets the component choose
    // the translated "unknown" instead (R2.7 — it must never look like a real version).
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
    expect(formatBuildVersion(" 0.1.0+x.y ", " a2f3c1d ")).toBe("0.1.0+x.y");
  });

  it("keeps metadata that itself contains a `+`, instead of dropping the tail", () => {
    expect(formatBuildVersion("0.1.0+2026-07-30.a2f3c1d+dirty", "")).toBe(
      "0.1.0+2026-07-30.a2f3c1d+dirty",
    );
  });
});

describe("VersionBadge (R2.1-R2.4, R2.7)", () => {
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

  it("renders the whole canonical version from the baked snapshot", () => {
    process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0+2026-07-30.a2f3c1d";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "a2f3c1d";

    renderBadge();

    expect(screen.getByTestId("version-badge")).toHaveTextContent(
      "0.1.0+2026-07-30.a2f3c1d",
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
      screen.getByLabelText("Versión desplegada: 0.1.0+2026-07-30.a2f3c1d"),
    ).toBeInTheDocument();
  });

  it("never renders the repository URL, the full sha, the PR or the run id", () => {
    // R2.4. A standing guard, not a description of today's build: these names are not
    // read anywhere in the current code (the provenance scope moved to
    // `app-version-provenance`). It stays because it FAILS if anyone ever routes one of
    // them into the public snapshot — which is the leak this change was trimmed to avoid.
    process.env.NEXT_PUBLIC_APP_VERSION = "0.1.0+2026-07-30.a2f3c1d";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "a2f3c1d";
    process.env.REPO_URL = "https://github.com/autohostai-labs/AutoHostAI";
    process.env.BUILD_COMMIT = "a2f3c1d3f9b2000000000000000000000000000f";
    process.env.BUILD_PR = "42";
    process.env.BUILD_RUN_ID = "1234567890";

    const { container } = renderBadge();

    // `innerHTML`, not `textContent`, for EVERY value. The security panel proved the
    // earlier version missed the likeliest shape of the leak: a `title={REPO_URL}` or an
    // `<a href={`${REPO_URL}/pull/${PR}`}>` left all 13 tests green, because a value in an
    // attribute never reaches the text. And a link is exactly how `app-version-provenance`
    // will render the pairing when it lands — so the guard has to cover the attribute
    // case, or it will be green on the very day it matters.
    expect(container.innerHTML).not.toContain("github.com");
    expect(container.innerHTML).not.toContain("autohostai-labs");
    expect(container.innerHTML).not.toContain(
      "a2f3c1d3f9b2000000000000000000000000000f",
    );
    expect(container.innerHTML).not.toContain("1234567890");
    // The PR is asserted as `#42`/`pr=` rather than a bare "42", which would false-fail
    // the day a real version reads `0.1.42+…` — precision by accident is not precision.
    expect(container.innerHTML).not.toContain("#42");
    expect(container.innerHTML).not.toContain("pr=");
    expect(container.innerHTML).not.toContain("BUILD_PR");
  });
});
