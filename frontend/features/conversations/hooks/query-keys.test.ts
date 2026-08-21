import { describe, expect, it } from "vitest";

import { conversationKeys } from "./query-keys";

describe("conversation query keys (task 4.2, D16, R2.4)", () => {
  it("scopes every key to the tenant", () => {
    const keys = [
      conversationKeys.listPrefix("tenant-1"),
      conversationKeys.list("tenant-1", {}, 1),
      conversationKeys.detail("tenant-1", "conversation-1"),
      conversationKeys.messagesPrefix("tenant-1", "conversation-1"),
      conversationKeys.messages("tenant-1", "conversation-1", 2),
      conversationKeys.propertyLabels("tenant-1"),
    ];
    for (const key of keys) {
      expect(key.slice(0, 2)).toEqual(["tenant", "tenant-1"]);
    }
  });

  it("refuses to build a key without a tenant", () => {
    expect(() => conversationKeys.list("", {}, 1)).toThrow();
    expect(() => conversationKeys.detail("", "conversation-1")).toThrow();
  });

  it("gives different filter combinations different keys", () => {
    const a = conversationKeys.list("tenant-1", { status: "OPEN" }, 1);
    const b = conversationKeys.list("tenant-1", { status: "ESCALATED" }, 1);
    const c = conversationKeys.list(
      "tenant-1",
      { status: "OPEN", propertyId: "property-1" },
      1,
    );
    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b));
    expect(JSON.stringify(a)).not.toBe(JSON.stringify(c));
  });

  it("gives different pages different keys", () => {
    expect(
      JSON.stringify(conversationKeys.list("tenant-1", {}, 1)),
    ).not.toBe(JSON.stringify(conversationKeys.list("tenant-1", {}, 2)));
    expect(
      JSON.stringify(conversationKeys.messages("tenant-1", "c1", 1)),
    ).not.toBe(JSON.stringify(conversationKeys.messages("tenant-1", "c1", 2)));
  });

  it("keeps two tenants apart for the same filters and page", () => {
    expect(
      JSON.stringify(conversationKeys.list("tenant-1", { status: "OPEN" }, 1)),
    ).not.toBe(
      JSON.stringify(conversationKeys.list("tenant-2", { status: "OPEN" }, 1)),
    );
  });

  it("makes the prefixes real prefixes of the keys they invalidate", () => {
    const listPrefix = conversationKeys.listPrefix("tenant-1");
    const list = conversationKeys.list("tenant-1", { status: "OPEN" }, 3);
    expect(list.slice(0, listPrefix.length)).toEqual([...listPrefix]);

    const messagesPrefix = conversationKeys.messagesPrefix("tenant-1", "c1");
    const messages = conversationKeys.messages("tenant-1", "c1", 4);
    expect(messages.slice(0, messagesPrefix.length)).toEqual([
      ...messagesPrefix,
    ]);
  });

  it("does not let one conversation's thread prefix match another's", () => {
    const prefix = conversationKeys.messagesPrefix("tenant-1", "c1");
    const other = conversationKeys.messages("tenant-1", "c2", 1);
    expect(other.slice(0, prefix.length)).not.toEqual([...prefix]);
  });

  it("keeps the property-label key free of filters and pages, so it stays cached", () => {
    expect(conversationKeys.propertyLabels("tenant-1")).toEqual([
      "tenant",
      "tenant-1",
      "conversation-property-labels",
    ]);
  });
});
