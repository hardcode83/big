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
    // Two assertions because each input's trim shows up on a different branch: the first on
    // the canonical path, the second on the fallback where the baked sha is what gets used.
    expect(formatBuildVersion(" 0.1.0+2026-07-30.a2f3c1d ", "")).toBe(
      "0.1.0+2026-07-30.a2f3c1d",
    );
    expect(formatBuildVersion(" local ", " a2f3c1d ")).toBe("local+a2f3c1d");
  });

  it("reads the metadata WHOLE, so a `+`-smuggled suffix cannot be truncated into shape", () => {
    // Taking only the first segment (`rest[0]`) would see `2026-07-30.a2f3c1d`, match the
    // canonical shape, and render `0.1.0+2026-07-30.a2f3c1d` — passing a modified build off
    // as a clean one. Reading it whole makes it off-shape, so it degrades instead.
    expect(formatBuildVersion("0.1.0+2026-07-30.a2f3c1d+dirty", "")).toBe("0.1.0");
    expect(formatBuildVersion("0.1.0+2026-07-30.a2f3c1d+dirty", "a2f3c1d")).toBe(
      "0.1.0+a2f3c1d",
    );
  });

  it.each([
    ["the full 40-char SHA", "0.1.0+2026-07-30.a2f3c1d3f9b2000000000000000000000000000f"],
    ["an appended run id", "0.1.0+2026-07-30.a2f3c1d.1234567890"],
    ["a run id on its own", "0.1.0+1234567890"],
    ["a branch ref", "0.1.0+refs/heads/main"],
    ["a commit with no date", "0.1.0+a2f3c1d"],
  ])(
    "refuses to render %s, which the metadata shape does not allow",
    (_why, widened) => {
      // The security panel's finding. Until this change the metadata was DISCARDED and
      // replaced by the short SHA, so only 7 characters could reach the screen no matter
      // what the CD composed. Showing it whole removes that structural limit, and the badge
      // is painted on ANONYMOUS surfaces — so the component, not the pipeline, has to be the
      // thing that refuses the full SHA and the run id (R2.4 of the parent capability).
      expect(formatBuildVersion(widened, "a2f3c1d")).toBe("0.1.0+a2f3c1d");
      // Asserted with no baked sha too, because for `0.1.0+a2f3c1d` the line above happens
      // to equal its own input — it would pass under the old verbatim behaviour as well, and
      // a case that cannot fail proves nothing.
      expect(formatBuildVersion(widened, "")).toBe("0.1.0");
    },
  );
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

  it("does not render a widened canonical string, even though that is the field it reads", () => {
    // The gap the security panel found in the guard above: it plants sensitive values in env
    // vars the component NEVER reads, so it asserts against a vector this change removed and
    // is blind to the one it created. The badge now renders the metadata verbatim, and the
    // only input it actually reads is NEXT_PUBLIC_APP_VERSION — so that is where a leak would
    // arrive from, if the CD's provenance step ever dropped `:0:7` or appended the run id.
    process.env.NEXT_PUBLIC_APP_VERSION =
      "0.1.0+2026-07-30.a2f3c1d3f9b2000000000000000000000000000f.1234567890";
    process.env.NEXT_PUBLIC_BUILD_COMMIT_SHORT = "a2f3c1d";

    const { container } = renderBadge();

    expect(container.innerHTML).not.toContain(
      "a2f3c1d3f9b2000000000000000000000000000f",
    );
    expect(container.innerHTML).not.toContain("1234567890");
    // Degrades to the short form rather than to "unknown": less than expected, never more.
    expect(screen.getByTestId("version-badge")).toHaveTextContent("0.1.0+a2f3c1d");
  });
});
