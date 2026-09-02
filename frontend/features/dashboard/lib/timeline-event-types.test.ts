import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { TIMELINE_EVENT_TYPES } from "./timeline-event-types";

/**
 * The compile-time guard in `timeline-event-types.ts` catches an enum that GREW,
 * and its `satisfies` clause rejects a value the enum never had. This suite covers
 * what neither expresses at runtime: the count, the absence of duplicates, and
 * that nothing stale survives a value being REMOVED from the contract (R2.1).
 *
 * The contract is read from the generated declaration rather than restated here,
 * so the assertion cannot drift with the copy it is meant to police. The file
 * lives inside `/app`, unlike the two suites that read above it and go red in a
 * linked worktree.
 */
function contractEventTypes(): string[] {
  const declaration = readFileSync(
    join(process.cwd(), "lib/api/generated/openapi.d.ts"),
    "utf8",
  );
  const union = /TimelineEventType:([^;]*);/.exec(declaration);
  if (!union) throw new Error("TimelineEventType not found in openapi.d.ts");
  return [...union[1].matchAll(/"([A-Z_]+)"/g)].map(([, value]) => value);
}

describe("TIMELINE_EVENT_TYPES (R2.1)", () => {
  it("matches the published TimelineEventType enum, value and count", () => {
    // The contract is the source of truth — the count is derived so the assertion
    // cannot drift when the backend enum grows (which is exactly what revenue-reviews
    // does, adding REVIEW_CREATED / REVIEW_DRAFT_EDITED / REVIEW_CLASSIFIED_LOW_CONFIDENCE
    // / REVIEW_IGNORED / REVIEW_POSTED_MANUALLY).
    const contract = contractEventTypes();
    expect(TIMELINE_EVENT_TYPES).toHaveLength(contract.length);
    expect(new Set(TIMELINE_EVENT_TYPES).size).toBe(contract.length);
  });

  it("is exactly the TimelineEventType enum of the published contract", () => {
    expect([...TIMELINE_EVENT_TYPES].sort()).toEqual(
      contractEventTypes().sort(),
    );
  });
});
