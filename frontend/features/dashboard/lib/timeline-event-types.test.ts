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
  it("carries 47 values with no duplicate", () => {
    expect(TIMELINE_EVENT_TYPES).toHaveLength(47);
    expect(new Set(TIMELINE_EVENT_TYPES).size).toBe(47);
  });

  it("is exactly the TimelineEventType enum of the published contract", () => {
    expect([...TIMELINE_EVENT_TYPES].sort()).toEqual(
      contractEventTypes().sort(),
    );
  });
});
