import { fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type {
  ConversationDetail,
  ConversationEscalationStatus,
  ConversationStatus,
} from "../data/dto";
import { ThreadActions } from "./thread-actions";

const useEscalate = vi.hoisted(() => vi.fn());
const useResolve = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-conversation-actions", () => ({ useEscalate, useResolve }));

function actionState(overrides: Record<string, unknown> = {}) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  };
}

function conversation(
  status: ConversationStatus,
  escalationStatus: ConversationEscalationStatus,
): ConversationDetail {
  return {
    id: "conversation-1",
    propertyId: "property-1",
    guestId: null,
    reservationId: null,
    channel: "WHATSAPP",
    status,
    escalationStatus,
    language: "es",
    aiEnabled: true,
    lastMessageAt: "2026-08-19T10:00:00Z",
    createdAt: "2026-08-10T09:00:00Z",
    updatedAt: "2026-08-19T10:00:00Z",
  };
}

function renderActions(
  status: ConversationStatus = "OPEN",
  escalationStatus: ConversationEscalationStatus = "NONE",
  escalate = actionState(),
  resolve = actionState(),
) {
  useEscalate.mockReturnValue(escalate);
  useResolve.mockReturnValue(resolve);
  render(
    <I18nProvider locale="es">
      <ThreadActions conversation={conversation(status, escalationStatus)} />
    </I18nProvider>,
  );
  return {
    escalate,
    resolve,
    escalateButton: () =>
      screen.getByRole("button", { name: "Escalar a una persona" }),
    resolveButton: () =>
      screen.getByRole("button", { name: "Marcar como resuelta" }),
  };
}

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

beforeEach(() => {
  useEscalate.mockReset();
  useResolve.mockReset();
});

describe("ThreadActions — the gates, by combination (task 7.4, D10, R5.2)", () => {
  it("enables escalation only for OPEN + NONE across both axes", () => {
    const enabled: string[] = [];
    for (const status of STATUSES) {
      for (const escalationStatus of ESCALATIONS) {
        const { escalateButton } = renderActions(status, escalationStatus);
        if (!escalateButton().hasAttribute("disabled")) {
          enabled.push(`${status}+${escalationStatus}`);
        }
        screen.getByRole("button", { name: "Escalar a una persona" });
        document.body.innerHTML = "";
      }
    }
    expect(enabled).toEqual(["OPEN+NONE"]);
  });

  it("enables resolution for OPEN and ESCALATED, whatever the escalation axis", () => {
    const enabled: string[] = [];
    for (const status of STATUSES) {
      for (const escalationStatus of ESCALATIONS) {
        const { resolveButton } = renderActions(status, escalationStatus);
        if (!resolveButton().hasAttribute("disabled")) {
          enabled.push(status);
        }
        document.body.innerHTML = "";
      }
    }
    expect(new Set(enabled)).toEqual(new Set(["OPEN", "ESCALATED"]));
    expect(enabled).toHaveLength(8);
  });
});

describe("ThreadActions — a blocked action is visible and explains itself (task 7.4, D11)", () => {
  it("renders escalate disabled with its reason, rather than hiding it", () => {
    const { escalateButton } = renderActions("ESCALATED", "PENDING_HUMAN");
    const button = escalateButton();

    expect(button).toBeInTheDocument();
    expect(button).toBeDisabled();
    const reason = screen.getByText("Esta conversación ya está escalada.");
    expect(button).toHaveAttribute("aria-describedby", reason.id);
  });

  it("explains a RESOLVED conversation that cannot be escalated (D10's second axis)", () => {
    const { escalateButton } = renderActions("RESOLVED", "NONE");
    expect(escalateButton()).toBeDisabled();
    expect(
      screen.getByText("Una conversación resuelta no se puede escalar."),
    ).toBeInTheDocument();
  });

  it("renders resolve disabled with its own reason when already resolved", () => {
    const { resolveButton } = renderActions("RESOLVED", "NONE");
    const button = resolveButton();

    expect(button).toBeDisabled();
    const reason = screen.getByText("Esta conversación ya está resuelta.");
    expect(button).toHaveAttribute("aria-describedby", reason.id);
  });
});

describe("ThreadActions — escalation acts once (task 7.4, R5.1)", () => {
  it("escalates on click", () => {
    const { escalate, escalateButton } = renderActions("OPEN", "NONE");
    fireEvent.click(escalateButton());
    expect(escalate.mutate).toHaveBeenCalledTimes(1);
  });

  it("is disabled while in flight", () => {
    const { escalateButton } = renderActions(
      "OPEN",
      "NONE",
      actionState({ isPending: true }),
    );
    expect(escalateButton()).toBeDisabled();
  });
});

describe("ThreadActions — resolving demands confirmation (task 7.4, R5.4)", () => {
  it("does not resolve on the first click", () => {
    const { resolve, resolveButton } = renderActions("OPEN", "NONE");
    fireEvent.click(resolveButton());

    expect(resolve.mutate).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toHaveTextContent(
      "¿Marcar la conversación como resuelta?",
    );
  });

  it("resolves only after confirming", async () => {
    const { resolve, resolveButton } = renderActions("OPEN", "NONE");
    fireEvent.click(resolveButton());
    fireEvent.click(screen.getByRole("button", { name: "Sí, resolver" }));

    expect(resolve.mutate).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("does not resolve when the confirmation is cancelled", async () => {
    const { resolve, resolveButton } = renderActions("OPEN", "NONE");
    fireEvent.click(resolveButton());
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(resolve.mutate).not.toHaveBeenCalled();
  });
});

describe("ThreadActions — a 409 (task 7.4, D18, R5.2)", () => {
  it("shows the localized conflict copy, never the technical message", () => {
    renderActions(
      "OPEN",
      "NONE",
      actionState({
        isError: true,
        error: new ApiError({
          code: "CONFLICT",
          message: "Conversation is already escalated",
          status: 409,
        }),
      }),
    );

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent(
      "El estado de la conversación ha cambiado y la acción ya no cabe.",
    );
    expect(alert).not.toHaveTextContent("already escalated");
    expect(alert).not.toHaveTextContent("409");
  });

  it("maps a 403 to the localized permissions copy instead (R6.3)", () => {
    renderActions(
      "OPEN",
      "NONE",
      actionState(),
      actionState({
        isError: true,
        error: new ApiError({ code: "FORBIDDEN", message: "denied", status: 403 }),
      }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Tu rol no permite esta acción.",
    );
  });
});
