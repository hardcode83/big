import { describe, expect, it } from "vitest";

import type {
  ConversationEscalationStatus,
  ConversationStatus,
} from "../data/dto";
import { escalateGate, resolveGate, writeMessageGate } from "./transitions";

const STATUSES: ConversationStatus[] = [
  "OPEN",
  "RESOLVED",
  "ESCALATED",
  "CLOSED",
];
const ESCALATIONS: ConversationEscalationStatus[] = [
  "NONE",
  "PENDING_HUMAN",
  "HUMAN_HANDLING",
  "RESOLVED",
];

function axes() {
  return STATUSES.flatMap((status) =>
    ESCALATIONS.map((escalationStatus) => ({ status, escalationStatus })),
  );
}

describe("escalate gate (task 2.2, D10, R5.2)", () => {
  it("is enabled only for OPEN + NONE, across the whole product of both axes", () => {
    const enabled = axes().filter((a) => escalateGate(a).enabled);
    expect(enabled).toEqual([{ status: "OPEN", escalationStatus: "NONE" }]);
  });

  it("does not offer escalation on RESOLVED + NONE, which would promise a 409", () => {
    const gate = escalateGate({ status: "RESOLVED", escalationStatus: "NONE" });
    expect(gate).toEqual({
      enabled: false,
      reasonKey: "actions.disabled.conversationResolved",
    });
  });

  it("says already-escalated when the escalation axis is not NONE", () => {
    expect(
      escalateGate({ status: "OPEN", escalationStatus: "PENDING_HUMAN" }),
    ).toEqual({
      enabled: false,
      reasonKey: "actions.disabled.alreadyEscalated",
    });
    expect(
      escalateGate({ status: "ESCALATED", escalationStatus: "HUMAN_HANDLING" }),
    ).toEqual({
      enabled: false,
      reasonKey: "actions.disabled.alreadyEscalated",
    });
  });

  it("says closed for a CLOSED conversation whose escalation axis is NONE", () => {
    expect(escalateGate({ status: "CLOSED", escalationStatus: "NONE" })).toEqual({
      enabled: false,
      reasonKey: "actions.disabled.conversationClosed",
    });
  });
});

describe("resolve gate (task 2.2, D10, R5.2)", () => {
  it("is enabled for OPEN and ESCALATED on every escalation value", () => {
    const enabled = axes().filter((a) => resolveGate(a).enabled);
    expect(enabled.map((a) => a.status)).toEqual([
      ...Array(4).fill("OPEN"),
      ...Array(4).fill("ESCALATED"),
    ]);
  });

  it("gives a distinct reason for already-resolved and for closed", () => {
    expect(resolveGate({ status: "RESOLVED", escalationStatus: "NONE" })).toEqual(
      { enabled: false, reasonKey: "actions.disabled.alreadyResolved" },
    );
    expect(resolveGate({ status: "CLOSED", escalationStatus: "NONE" })).toEqual({
      enabled: false,
      reasonKey: "actions.disabled.conversationClosed",
    });
  });
});

describe("write gate — reply and transcribe (task 2.2, D10)", () => {
  it("is enabled for every status but CLOSED", () => {
    const blocked = axes().filter((a) => !writeMessageGate(a).enabled);
    expect(new Set(blocked.map((a) => a.status))).toEqual(new Set(["CLOSED"]));
    expect(blocked).toHaveLength(4);
  });

  it("blocks a CLOSED conversation with the closed reason", () => {
    expect(
      writeMessageGate({ status: "CLOSED", escalationStatus: "RESOLVED" }),
    ).toEqual({
      enabled: false,
      reasonKey: "actions.disabled.conversationClosed",
    });
  });
});
