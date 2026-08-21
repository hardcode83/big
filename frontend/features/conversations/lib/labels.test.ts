import { describe, expect, it } from "vitest";

import { resources } from "@/lib/i18n/resources";

import {
  CHANNEL_KEYS,
  CONVERSATION_STATUS_KEYS,
  ESCALATION_STATUS_KEYS,
  SENDER_TYPE_KEYS,
} from "./labels";

/**
 * The `Record<Literal, key>` type is what makes a value added to the backend stop
 * compiling (design D7); these assertions pin the unions as the contract declares
 * them today, so widening one shows up in the diff instead of silently rendering a
 * missing key.
 */
describe("enum label maps are exhaustive (task 2.1, D7, R2.2, R3.3)", () => {
  it("covers the four ConversationStatus values", () => {
    expect(Object.keys(CONVERSATION_STATUS_KEYS).sort()).toEqual(
      ["CLOSED", "ESCALATED", "OPEN", "RESOLVED"],
    );
  });

  it("covers the four ConversationEscalationStatus values", () => {
    expect(Object.keys(ESCALATION_STATUS_KEYS).sort()).toEqual(
      ["HUMAN_HANDLING", "NONE", "PENDING_HUMAN", "RESOLVED"],
    );
  });

  it("covers the six ConversationChannel values", () => {
    expect(Object.keys(CHANNEL_KEYS).sort()).toEqual([
      "AIRBNB_MSG",
      "BOOKING_MSG",
      "EMAIL",
      "MANUAL",
      "PHONE_TRANSCRIPT",
      "WHATSAPP",
    ]);
  });

  it("covers the five MessageSenderType values", () => {
    expect(Object.keys(SENDER_TYPE_KEYS).sort()).toEqual([
      "AI",
      "GUEST",
      "MANAGER",
      "OWNER",
      "SYSTEM",
    ]);
  });

  it.each([
    ["status", CONVERSATION_STATUS_KEYS],
    ["escalationStatus", ESCALATION_STATUS_KEYS],
    ["channel", CHANNEL_KEYS],
    ["senderType", SENDER_TYPE_KEYS],
  ] as const)(
    "maps each %s literal to its own key, so a swapped pair fails",
    (prefix, map) => {
      for (const [literal, key] of Object.entries(map)) {
        expect(key).toBe(`${prefix}.${literal}`);
      }
    },
  );

  it("writes every key literally, never interpolated, and never duplicated", () => {
    const all = [
      ...Object.values(CONVERSATION_STATUS_KEYS),
      ...Object.values(ESCALATION_STATUS_KEYS),
      ...Object.values(CHANNEL_KEYS),
      ...Object.values(SENDER_TYPE_KEYS),
    ];
    expect(new Set(all).size).toBe(all.length);
    for (const key of all) {
      expect(key).not.toContain("${");
      expect(key).toMatch(/^[a-zA-Z]+\.[A-Z_]+$/);
    }
  });
});

/**
 * R7.4: a key missing from either locale must fail a test. The catalog parity test
 * proves the two locales agree; this proves the keys these maps name are actually
 * in them, which parity alone cannot see.
 */
describe("every enum label key resolves in both locales (task 3.1, R7.4)", () => {
  const ALL_KEYS = [
    ...Object.values(CONVERSATION_STATUS_KEYS),
    ...Object.values(ESCALATION_STATUS_KEYS),
    ...Object.values(CHANNEL_KEYS),
    ...Object.values(SENDER_TYPE_KEYS),
  ];

  function resolve(locale: "es" | "en", key: string): unknown {
    return key
      .split(".")
      .reduce<unknown>(
        (node, segment) =>
          node && typeof node === "object"
            ? (node as Record<string, unknown>)[segment]
            : undefined,
        resources[locale].conversations,
      );
  }

  it.each(["es", "en"] as const)("resolves all of them in %s", (locale) => {
    for (const key of ALL_KEYS) {
      expect(typeof resolve(locale, key), `${locale} ${key}`).toBe("string");
    }
  });
});
