import { describe, expect, it } from "vitest";

import { notificationsKeys } from "./query-keys";

describe("notificationsKeys (D12)", () => {
  it("scopes by tenant AND by user, because colleagues share a tenant and not an inbox", () => {
    const manager = notificationsKeys.unread("t1", "manager");
    const cleaner = notificationsKeys.unread("t1", "cleaner");

    expect(manager).toEqual(["tenant", "t1", "notifications-unread", "manager"]);
    expect(manager).not.toEqual(cleaner);
  });

  it("separates two users' lists inside one tenant", () => {
    expect(notificationsKeys.list("t1", "manager")).not.toEqual(
      notificationsKeys.list("t1", "cleaner"),
    );
  });

  it("separates the same user across tenants", () => {
    expect(notificationsKeys.unread("t1", "u1")).not.toEqual(
      notificationsKeys.unread("t2", "u1"),
    );
  });

  it("carries the filters in the list key, so two pages are two entries", () => {
    expect(notificationsKeys.list("t1", "u1", { page: 1 })).not.toEqual(
      notificationsKeys.list("t1", "u1", { page: 2 }),
    );
  });

  it("gives the list a prefix the filtered keys start with, so one invalidation reaches them all", () => {
    const prefix = notificationsKeys.listPrefix("t1", "u1");
    const page2 = notificationsKeys.list("t1", "u1", { page: 2, unread: true });

    expect(page2.slice(0, prefix.length)).toEqual(prefix);
  });

  it("keeps the unread counter out of the list family, so invalidating one is not both by accident", () => {
    const unread = notificationsKeys.unread("t1", "u1");
    const listPrefix = notificationsKeys.listPrefix("t1", "u1");

    expect(unread.slice(0, listPrefix.length)).not.toEqual(listPrefix);
  });
});
