import { describe, expect, it } from "vitest";

import type { ConversationChannel } from "../data/dto";
import { isMuteChannel } from "./channels";

const CHANNELS: ConversationChannel[] = [
  "WHATSAPP",
  "AIRBNB_MSG",
  "BOOKING_MSG",
  "EMAIL",
  "PHONE_TRANSCRIPT",
  "MANUAL",
];

describe("isMuteChannel (D13)", () => {
  it("is true for exactly the two PMS messaging channels", () => {
    expect(CHANNELS.filter(isMuteChannel)).toEqual([
      "AIRBNB_MSG",
      "BOOKING_MSG",
    ]);
  });

  it("answers for every channel in the contract", () => {
    for (const channel of CHANNELS) {
      expect(typeof isMuteChannel(channel)).toBe("boolean");
    }
  });

  it("does not treat PHONE_TRANSCRIPT as mute, because it has an inbound-only adapter", () => {
    // D13: its AI replies are stored with `delivery_status = FAILED` and the
    // conversation escalates — a different failure from a channel with no adapter,
    // and it is the message's delivery mark that reports it, not this predicate.
    expect(isMuteChannel("PHONE_TRANSCRIPT")).toBe(false);
  });
});
