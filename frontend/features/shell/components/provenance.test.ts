import { describe, expect, it } from "vitest";

import {
  OPERATOR_SURFACE_IS_AUTHENTICATED,
  resolveProvenance,
} from "@/features/shell/components/provenance";

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
    const r = resolveProvenance(FULL, true);

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
    const r = resolveProvenance(FULL, true);
    expect(r.commitShort).toBe("a2f3c1d");
    expect(r.commitHref).toContain(FULL.commit);
  });

  it("tolerates a trailing slash on the repository URL", () => {
    const r = resolveProvenance({ ...FULL, repoUrl: `${FULL.repoUrl}/` }, true);
    expect(r.prHref).toBe(
      "https://github.com/autohostai-labs/AutoHostAI/pull/42",
    );
  });

  it("emits NO link when the repository URL was not baked", () => {
    // A half-formed href is worse than none: it looks clickable and goes nowhere.
    const r = resolveProvenance({ ...FULL, repoUrl: undefined }, true);
    expect(r.prHref).toBeNull();
    expect(r.commitHref).toBeNull();
    expect(r.runHref).toBeNull();
    // The values themselves survive, so the panel can still show them as text.
    expect(r.pr).toBe("42");
    expect(r.commitShort).toBe("a2f3c1d");
  });

  it("emits no PR link when the commit reached main directly (R4.4)", () => {
    const r = resolveProvenance({ ...FULL, pr: undefined }, true);
    expect(r.pr).toBeNull();
    expect(r.prHref).toBeNull();
    // The other links are unaffected — a direct push still has a commit and a run.
    expect(r.commitHref).not.toBeNull();
    expect(r.runHref).not.toBeNull();
  });

  it("degrades every field to null when nothing was baked", () => {
    expect(
      resolveProvenance(
        {
          commit: undefined,
          pr: undefined,
          builtAt: undefined,
          runId: undefined,
          ref: undefined,
          repoUrl: undefined,
        },
        true,
      ),
    ).toEqual({
      commitShort: null,
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

describe("withholding the repository details (security panel, finding 1)", () => {
  it("defaults to WITHHELD, because the operator surface has no authentication yet", () => {
    // The default matters more than any explicit call: a caller that forgets the flag must
    // get the safe behaviour. /dashboard is as anonymous as /login until `dashboard-web`.
    expect(OPERATOR_SURFACE_IS_AUTHENTICATED).toBe(false);

    const r = resolveProvenance(FULL);

    expect(r.prHref).toBeNull();
    expect(r.commitHref).toBeNull();
    expect(r.runHref).toBeNull();
    expect(r.pr).toBeNull();
    expect(r.runId).toBeNull();
    expect(r.ref).toBeNull();
  });

  it("still exposes what was already public: short commit and build date", () => {
    const r = resolveProvenance(FULL, false);
    expect(r.commitShort).toBe("a2f3c1d");
    expect(r.builtAt).toBe("2026-07-30T09:14:02Z");
  });

  it("leaks NOTHING that identifies the repository when withheld", () => {
    // Serialized straight into the RSC payload of a public page, so this is the assertion
    // that matters: no repo name, no full sha, no PR number, anywhere in the object.
    const serialized = JSON.stringify(resolveProvenance(FULL, false));

    expect(serialized).not.toContain("github.com");
    expect(serialized).not.toContain("autohostai-labs");
    expect(serialized).not.toContain(FULL.commit);
    expect(serialized).not.toContain("42");
    expect(serialized).not.toContain("1234567890");
  });
});

describe("hostile repoUrl (QA panel, finding 4)", () => {
  it.each([
    "javascript:alert(1)",
    "data:text/html,<script>x</script>",
    "../../etc/passwd",
    "not a url at all",
  ])("drops the link for %j instead of composing one", (repoUrl) => {
    const r = resolveProvenance({ ...FULL, repoUrl }, true);
    expect(r.prHref).toBeNull();
    expect(r.commitHref).toBeNull();
    expect(r.runHref).toBeNull();
  });

  it("accepts plain http as well as https", () => {
    const r = resolveProvenance(
      { ...FULL, repoUrl: "http://git.example" },
      true,
    );
    expect(r.prHref).toBe("http://git.example/pull/42");
  });
});
