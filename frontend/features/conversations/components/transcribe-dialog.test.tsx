import { fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { ConversationChannel } from "../data/dto";
import { TranscribeDialog } from "./transcribe-dialog";

const useTranscribeGuestMessage = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-conversation-actions", () => ({
  useTranscribeGuestMessage,
}));

const MUTE_WARNING =
  "En este canal la transcripción puede perderse entera: si la IA intenta responder y no encuentra por dónde enviarlo, no se guarda nada.";

function transcribeState(overrides: Record<string, unknown> = {}) {
  return {
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  };
}

function renderDialog(
  channel: ConversationChannel = "WHATSAPP",
  state = transcribeState(),
  gate: Parameters<typeof TranscribeDialog>[0]["gate"] = { enabled: true },
) {
  useTranscribeGuestMessage.mockReturnValue(state);
  render(
    <I18nProvider locale="es">
      <TranscribeDialog
        conversationId="conversation-1"
        channel={channel}
        gate={gate}
      />
    </I18nProvider>,
  );
  const open = () =>
    fireEvent.click(
      screen.getByRole("button", { name: "Transcribir mensaje del huésped" }),
    );
  return { state, open };
}

beforeEach(() => {
  useTranscribeGuestMessage.mockReset();
});

describe("TranscribeDialog — a separate, unambiguous action (task 7.3, R4.2)", () => {
  it("is labelled as transcribing the guest's message, not as replying", () => {
    renderDialog();
    const trigger = screen.getByRole("button", {
      name: "Transcribir mensaje del huésped",
    });
    expect(trigger).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Enviar respuesta/ })).toBeNull();
  });

  it("warns that it triggers the AI's reply and may escalate, before anything is sent", () => {
    const { open } = renderDialog();
    open();

    expect(screen.getByRole("dialog")).toHaveTextContent(
      "La IA responderá automáticamente y la conversación puede escalar a una persona.",
    );
  });

  it("sends the content as a guest message", async () => {
    const { state, open } = renderDialog();
    open();
    fireEvent.change(screen.getByLabelText("Mensaje del huésped"), {
      target: { value: "No hay agua caliente" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Transcribir" }));

    expect(state.mutate).toHaveBeenCalledTimes(1);
    expect(state.mutate.mock.calls[0][0]).toBe("No hay agua caliente");
  });

  it("blocks an empty transcription", () => {
    const { state, open } = renderDialog();
    open();
    expect(screen.getByRole("button", { name: "Transcribir" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Transcribir" }));
    expect(state.mutate).not.toHaveBeenCalled();
  });
});

describe("TranscribeDialog — the two warnings are different (task 7.3, D13)", () => {
  it.each(["AIRBNB_MSG", "BOOKING_MSG"] as const)(
    "warns on %s that the whole transcription can be lost",
    (channel) => {
      const { open } = renderDialog(channel as ConversationChannel);
      open();

      const warning = screen.getByText(MUTE_WARNING);
      expect(warning).toBeInTheDocument();
      // D13: this path loses data, unlike replying, which merely never delivers.
      expect(warning.textContent).toContain("no se guarda nada");
    },
  );

  it.each(["WHATSAPP", "EMAIL", "PHONE_TRANSCRIPT", "MANUAL"] as const)(
    "does not carry the mute warning on %s",
    (channel) => {
      const { open } = renderDialog(channel as ConversationChannel);
      open();
      expect(screen.queryByText(MUTE_WARNING)).toBeNull();
    },
  );

  it("says nothing about the thread-level «se guarda, no se envía» wording", () => {
    const { open } = renderDialog("AIRBNB_MSG");
    open();
    // The thread header owns that other sentence; repeating it here would describe
    // the wrong path — the one that loses the guest's message.
    expect(screen.getByRole("dialog")).not.toHaveTextContent(
      "lo que escribas se guarda en el hilo, pero no se envía al huésped",
    );
  });
});

describe("TranscribeDialog — a failure says nothing was stored (task 7.3, D13, D18)", () => {
  it("shows the localized «no se ha guardado nada» copy and keeps the dialog open", () => {
    const { open } = renderDialog(
      "AIRBNB_MSG",
      transcribeState({
        isError: true,
        error: new ApiError({
          code: "VALIDATION_ERROR",
          message: "PMS channel unavailable",
          status: 422,
        }),
      }),
    );
    open();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("No se ha guardado nada");
    expect(alert).toHaveTextContent("Los datos enviados no son válidos.");
    expect(alert).not.toHaveTextContent("PMS channel unavailable");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("keeps the typed transcription so it can be copied elsewhere", () => {
    const { open } = renderDialog(
      "AIRBNB_MSG",
      transcribeState({
        isError: true,
        error: new ApiError({ code: "VALIDATION_ERROR", message: "x", status: 422 }),
      }),
    );
    open();
    const field = screen.getByLabelText("Mensaje del huésped");
    fireEvent.change(field, { target: { value: "No hay agua caliente" } });
    expect(field).toHaveValue("No hay agua caliente");
  });

  // Review 2026-08-21: the «nothing was stored» claim is only derivable from a 4xx.
  // A 5xx, or a dropped connection, may have committed the guest's prose, and
  // telling the operator it did not is what hides a record nobody will ask to
  // delete (`steering/security.md` rule 11 exception 4).
  it("does not claim nothing was stored when the failure cannot prove it (5xx)", () => {
    const { open } = renderDialog(
      "WHATSAPP",
      transcribeState({
        isError: true,
        error: new ApiError({
          code: "SERVER_ERROR",
          message: "Request failed with status 502",
          status: 502,
        }),
      }),
    );
    open();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Puede que la transcripción no se haya guardado.");
    expect(alert).not.toHaveTextContent("No se ha guardado nada");
    expect(alert).toHaveTextContent("No hemos podido completar la operación.");
    expect(alert).not.toHaveTextContent("502");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("does not claim nothing was stored when the request never got an answer", () => {
    const { open } = renderDialog(
      "WHATSAPP",
      transcribeState({ isError: true, error: new Error("network down") }),
    );
    open();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Puede que la transcripción no se haya guardado.");
    expect(alert).not.toHaveTextContent("No se ha guardado nada");
    expect(alert).not.toHaveTextContent("network down");
  });
});

describe("TranscribeDialog — gates (task 7.3, D10, D11)", () => {
  it("is disabled with the localized reason on a closed conversation", () => {
    renderDialog("WHATSAPP", transcribeState(), {
      enabled: false,
      reasonKey: "actions.disabled.conversationClosed",
    });

    const trigger = screen.getByRole("button", {
      name: "Transcribir mensaje del huésped",
    });
    expect(trigger).toBeDisabled();
    const reason = screen.getByText("Esta conversación está cerrada.");
    expect(trigger).toHaveAttribute("aria-describedby", reason.id);
  });

  it("clears the field and the error when it is closed", async () => {
    const state = transcribeState();
    const { open } = renderDialog("WHATSAPP", state);
    open();
    fireEvent.change(screen.getByLabelText("Mensaje del huésped"), {
      target: { value: "algo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(state.reset).toHaveBeenCalled();
  });
});
