import { describe, expect, it } from "vitest";

import { guestKeys } from "./query-keys";

/**
 * Tenant/token isolation at the cache layer (R5, task 1.3). The guest surface has
 * no session; the opaque token is the ONLY selector, so the React Query cache must
 * be partitioned by it. If a future refactor drops `token` from a key, two guests
 * would share a cache entry and one could be served another reservation's stay or
 * check-in status. These assertions fail closed on exactly that regression.
 */
describe("guestKeys token isolation (R5, task 1.3)", () => {
  it("carries the token as the last segment of every scoped key", () => {
    expect(guestKeys.info("token-a")).toEqual(["guest-portal", "info", "token-a"]);
    expect(guestKeys.checkin("token-a")).toEqual(["guest-portal", "checkin", "token-a"]);
    expect(guestKeys.conversation("token-a")).toEqual(["guest-portal", "conversation", "token-a"]);
  });

  it("derives distinct keys for distinct tokens, so no two tokens share a cache entry", () => {
    expect(guestKeys.info("token-a")).not.toEqual(guestKeys.info("token-b"));
    expect(guestKeys.checkin("token-a")).not.toEqual(guestKeys.checkin("token-b"));
    expect(guestKeys.conversation("token-a")).not.toEqual(guestKeys.conversation("token-b"));
  });

  it("keeps every scope distinct for the same token", () => {
    expect(guestKeys.info("token-a")).not.toEqual(guestKeys.checkin("token-a"));
    expect(guestKeys.conversation("token-a")).not.toEqual(guestKeys.info("token-a"));
    expect(guestKeys.conversation("token-a")).not.toEqual(guestKeys.checkin("token-a"));
  });

  /**
   * The conversation key is polled and invalidated on every send, so it is the one whose
   * partitioning is exercised constantly rather than once per page load. A key that dropped the
   * token would let one guest's poll serve another guest's thread out of cache — the messages
   * of a stay that is not theirs, which is a worse leak than the stay data the keys above
   * protect.
   */
  it("partitions the conversation cache by token, which is the only selector the portal has", () => {
    expect(guestKeys.conversation("token-a")).toContain("token-a");
    expect(guestKeys.conversation("token-a")).not.toContain("token-b");
  });
});
