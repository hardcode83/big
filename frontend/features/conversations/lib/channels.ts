import type { ConversationChannel } from "../data/dto";

/**
 * ASSUMPTION, and a time-bound one: these are the channels with no outbound adapter
 * **today**, and the day `beds24-messaging-adapter` lands this map is what has to
 * change — `AIRBNB_MSG` and `BOOKING_MSG` stop being mute and both warnings of D13
 * stop applying. Nothing fails if it is forgotten, which is why it is marked.
 *
 * Which channels have no outbound adapter until that adapter lands (design D13). An exhaustive `Record` rather than a list, so a channel added to
 * the backend has to be classified here instead of defaulting to "deliverable" —
 * the same shape as the other maps over closed contract enums (`labels.ts`,
 * `transitions.ts`, `permissions.ts`), and the reason this lives in `lib/` and not
 * in a component: the thread header and the transcription dialog both need the
 * predicate, and their two warnings say different things.
 */
const IS_MUTE: Record<ConversationChannel, boolean> = {
  WHATSAPP: false,
  AIRBNB_MSG: true,
  BOOKING_MSG: true,
  EMAIL: false,
  PHONE_TRANSCRIPT: false,
  MANUAL: false,
};

export function isMuteChannel(channel: ConversationChannel): boolean {
  return IS_MUTE[channel];
}
