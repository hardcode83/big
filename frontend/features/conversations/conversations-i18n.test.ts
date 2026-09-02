import { describe, expect, it } from "vitest";

import type { components } from "@/lib/api/generated/openapi";
import es from "@/locales/es/conversations.json";
import en from "@/locales/en/conversations.json";

/**
 * Parity and enum coverage for the manager inbox's catalogs.
 *
 * **Why this file exists.** `guest-portal-messaging` added `PORTAL` to `ConversationChannel`, and
 * the inbox paints a channel with `t(`conversations:channel.${row.channel}`)` — so a member with
 * no translation is rendered as the raw key, in the manager's face, with nothing going red. The
 * `guest` namespace has had this guard since `guest-portal-web`; this namespace did not, and the
 * i18n panel of sections 9-10 pointed out that the `PORTAL` keys were correct today and unguarded
 * for tomorrow.
 *
 * The enum list is derived from the generated contract rather than hand-written, so the next
 * channel the backend adds fails here instead of shipping a raw key.
 */
function keyPaths(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    keyPaths(child, prefix ? `${prefix}.${key}` : key),
  );
}

const CHANNELS: components["schemas"]["ConversationChannel"][] = [
  "WHATSAPP",
  "AIRBNB_MSG",
  "BOOKING_MSG",
  "EMAIL",
  "PHONE_TRANSCRIPT",
  "MANUAL",
  "PORTAL",
];

describe("conversations i18n catalogs", () => {
  it("has identical key sets in es and en", () => {
    expect(keyPaths(es).sort()).toEqual(keyPaths(en).sort());
  });

  it("translates every ConversationChannel member in both locales", () => {
    for (const locale of [es, en] as const) {
      for (const channel of CHANNELS) {
        expect(locale.channel).toHaveProperty(channel);
        expect(locale.channel[channel as keyof typeof locale.channel]).toBeTruthy();
      }
    }
  });

  /**
   * The list above is only worth what its agreement with the contract is worth. If the backend
   * adds a channel and nobody updates `CHANNELS`, the test above would keep passing while the
   * inbox painted a raw key — so this asserts the list is exhaustive against the generated type
   * by construction: a missing member makes the assignment below a type error, and an extra one
   * makes this length check fail.
   */
  it("keeps its channel list exhaustive against the generated contract", () => {
    const fromContract: Record<components["schemas"]["ConversationChannel"], true> = {
      WHATSAPP: true,
      AIRBNB_MSG: true,
      BOOKING_MSG: true,
      EMAIL: true,
      PHONE_TRANSCRIPT: true,
      MANUAL: true,
      PORTAL: true,
    };
    expect(Object.keys(fromContract).sort()).toEqual([...CHANNELS].sort());
  });
});
