import { describe, expect, it } from "vitest";

import { resolveProvenance } from "@/features/shell/components/provenance";

const FULL = {
  commit: "a2f3c1d3f9b2000000000000000000000000000f",
  pr: "42",
  builtAt: "2026-07-30T09:14:02Z",
  runId: "1234567890",
  ref: "main",
  repoUrl: "https://github.com/autohostai-labs/AutoHostAI",
};

describe("resolveProvenance (R4.1, R4.2, R4.4)", () => {
  it("builds the three links from the repository URL", () => {
    const r = resolveProvenance(FULL);

    expect(r.prHref).toBe(
      "https://github.com/autohostai-labs/AutoHostAI/pull/42",
    );
    expect(r.commitHref).toBe(
      "https://github.com/autohostai-labs/AutoHostAI/commit/a2f3c1d3f9b2000000000000000000000000000f",
    );
    expect(r.runHref).toBe(
      "https://github.com/autohostai-labs/AutoHostAI/actions/runs/1234567890",
    );
  });

  it("shortens the commit for display but links the full sha", () => {
    const r = resolveProvenance(FULL);
    expect(r.commitShort).toBe("a2f3c1d");
    expect(r.commitFull).toBe(FULL.commit);
    expect(r.commitHref).toContain(FULL.commit);
  });

  it("tolerates a trailing slash on the repository URL", () => {
    const r = resolveProvenance({ ...FULL, repoUrl: `${FULL.repoUrl}/` });
    expect(r.prHref).toBe(
      "https://github.com/autohostai-labs/AutoHostAI/pull/42",
    );
  });

  it("emits NO link when the repository URL was not baked", () => {
    // A half-formed href is worse than none: it looks clickable and goes nowhere.
    const r = resolveProvenance({ ...FULL, repoUrl: undefined });
    expect(r.prHref).toBeNull();
    expect(r.commitHref).toBeNull();
    expect(r.runHref).toBeNull();
    // The values themselves survive, so the panel can still show them as text.
    expect(r.pr).toBe("42");
    expect(r.commitShort).toBe("a2f3c1d");
  });

  it("emits no PR link when the commit reached main directly (R4.4)", () => {
    const r = resolveProvenance({ ...FULL, pr: undefined });
    expect(r.pr).toBeNull();
    expect(r.prHref).toBeNull();
    // The other links are unaffected — a direct push still has a commit and a run.
    expect(r.commitHref).not.toBeNull();
    expect(r.runHref).not.toBeNull();
  });

  it("degrades every field to null when nothing was baked", () => {
    expect(
      resolveProvenance({
        commit: undefined,
        pr: undefined,
        builtAt: undefined,
        runId: undefined,
        ref: undefined,
        repoUrl: undefined,
      }),
    ).toEqual({
      commitShort: null,
      commitFull: null,
      commitHref: null,
      pr: null,
      prHref: null,
      builtAt: null,
      runId: null,
      runHref: null,
      ref: null,
    });
  });
});
