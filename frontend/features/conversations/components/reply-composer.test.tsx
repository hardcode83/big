import { fireEvent } from "@testing-library/react";
import { useState } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import { MAX_MESSAGE_LENGTH } from "../lib/limits";
import { ReplyComposer } from "./reply-composer";

const useSendReply = vi.hoisted(() => vi.fn());
const useTranscribeGuestMessage = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-conversation-actions", () => ({
  useSendReply,
  useTranscribeGuestMessage,
}));

function sendState(overrides: Record<string, unknown> = {}) {
  return {
    mutate: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
    ...overrides,
  };
}

/**
 * The draft is owned above the keyed boundary (D22), so the composer is controlled.
 * This harness plays the part `ConversationsView` plays in the app: it holds the
 * draft and hands it back down, which is what lets these suites type normally.
 */
function Harness({
  conversationId = "conversation-1",
  gate = { enabled: true } as Parameters<typeof ReplyComposer>[0]["gate"],
}: {
  conversationId?: string;
  gate?: Parameters<typeof ReplyComposer>[0]["gate"];
}) {
  const [draft, setDraft] = useState("");
  return (
    <ReplyComposer
      conversationId={conversationId}
      gate={gate}
      draft={draft}
      onDraftChange={setDraft}
    />
  );
}

function renderComposer(
  state = sendState(),
  gate: Parameters<typeof ReplyComposer>[0]["gate"] = { enabled: true },
) {
  useSendReply.mockReturnValue(state);
  const { container } = render(
    <I18nProvider locale="es">
      <Harness gate={gate} />
    </I18nProvider>,
  );
  return {
    container,
    state,
    textarea: screen.getByLabelText("Responder al huésped"),
    send: () => screen.getByRole("button", { name: /Enviar respuesta|Enviando/ }),
  };
}

beforeEach(() => {
  useSendReply.mockReset();
  useTranscribeGuestMessage.mockReset();
});

describe("ReplyComposer — the limit and the empty case (task 7.2, R4.3)", () => {
  it("shows the character count against the contract's limit", () => {
    const { textarea } = renderComposer();
    fireEvent.change(textarea, { target: { value: "hola" } });
    expect(screen.getByText(`4 de ${MAX_MESSAGE_LENGTH} caracteres`)).toBeInTheDocument();
  });

  it("blocks sending an empty or whitespace-only reply before the backend can 422", () => {
    const { state, textarea, send } = renderComposer();
    expect(send()).toBeDisabled();

    fireEvent.change(textarea, { target: { value: "   " } });
    expect(send()).toBeDisabled();

    fireEvent.click(send());
    expect(state.mutate).not.toHaveBeenCalled();
  });

  it("blocks and explains a reply over 4000 characters", () => {
    const { state, textarea, send } = renderComposer();
    fireEvent.change(textarea, {
      target: { value: "a".repeat(MAX_MESSAGE_LENGTH + 1) },
    });

    expect(
      screen.getByText(`La respuesta no puede pasar de ${MAX_MESSAGE_LENGTH} caracteres.`),
    ).toBeInTheDocument();
    expect(send()).toBeDisabled();
    fireEvent.click(send());
    expect(state.mutate).not.toHaveBeenCalled();
  });

  it("accepts exactly 4000 characters", () => {
    const { textarea, send } = renderComposer();
    fireEvent.change(textarea, {
      target: { value: "a".repeat(MAX_MESSAGE_LENGTH) },
    });
    expect(send()).toBeEnabled();
  });
});

describe("ReplyComposer — in flight (task 7.2, R4.5)", () => {
  it("disables the composer and says it is sending", () => {
    const { textarea, send } = renderComposer(sendState({ isPending: true }));
    expect(textarea).toBeDisabled();
    expect(send()).toBeDisabled();
    expect(screen.getByRole("button", { name: "Enviando…" })).toBeInTheDocument();
  });

  it("sends the content once, without a sender type of its own (R4.1)", () => {
    const { state, textarea, send } = renderComposer();
    fireEvent.change(textarea, { target: { value: "Vamos a mirarlo" } });
    fireEvent.click(send());

    expect(state.mutate).toHaveBeenCalledTimes(1);
    expect(state.mutate.mock.calls[0][0]).toBe("Vamos a mirarlo");
    // The composer speaks as us; only `useTranscribeGuestMessage` can speak as the
    // guest, and this component never reaches for it (R4.2).
    expect(useTranscribeGuestMessage).not.toHaveBeenCalled();
  });

  it("cannot be made to send a guest message: it offers no sender control", () => {
    const { container, textarea } = renderComposer();
    fireEvent.change(textarea, { target: { value: "hola" } });

    // The only field is the reply body. There is no way — default or otherwise —
    // to choose who the message is from (R4.2's "NOT ... ni por defecto").
    expect(container.querySelectorAll("textarea, input, select")).toHaveLength(1);
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.queryByRole("button", { name: /Transcribir/ })).toBeNull();
  });
});

describe("ReplyComposer — a failed send (task 7.2, R4.5, D18)", () => {
  it("keeps the written text and shows localized copy, never the technical message", () => {
    const { textarea } = renderComposer(
      sendState({
        isError: true,
        error: new ApiError({
          code: "SERVER_ERROR",
          message: "Request failed with status 500",
          status: 500,
        }),
      }),
    );
    fireEvent.change(textarea, { target: { value: "Vamos a mirarlo" } });

    expect(textarea).toHaveValue("Vamos a mirarlo");
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("No se ha enviado la respuesta");
    expect(alert).toHaveTextContent("No hemos podido completar la operación.");
    expect(alert).not.toHaveTextContent("500");
    expect(alert).not.toHaveTextContent("Request failed");
  });

  it("maps a 403 on the action to the localized permissions copy (R6.3)", () => {
    renderComposer(
      sendState({
        isError: true,
        error: new ApiError({ code: "FORBIDDEN", message: "denied", status: 403 }),
      }),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Tu rol no permite esta acción.",
    );
  });

  it("does not present the message as sent — nothing is appended to the thread", () => {
    renderComposer(
      sendState({
        isError: true,
        error: new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
      }),
    );
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});

describe("ReplyComposer — the closed conversation (task 7.2, D10, D11)", () => {
  it("is disabled with the localized reason wired to the field", () => {
    const { textarea, send } = renderComposer(sendState(), {
      enabled: false,
      reasonKey: "actions.disabled.conversationClosed",
    });

    expect(textarea).toBeDisabled();
    expect(send()).toBeDisabled();
    const reason = screen.getByText("Esta conversación está cerrada.");
    expect(textarea).toHaveAttribute("aria-describedby", reason.id);
  });
});

describe("ReplyComposer — the draft is owned above it (R4.5, D22)", () => {
  const textarea = () => screen.getByLabelText("Responder al huésped");

  // The composer holds no draft of its own any more: `ConversationsView` owns a map
  // per conversation, above the boundary that keys this subtree. That is what makes a
  // failed send survive the operator walking away, and it is why an empty composer can
  // mean "delivered" again. Isolation between conversations is asserted where it now
  // lives, in `conversations-view.test.tsx`.
  it("renders exactly the draft it is handed and reports every edit upward", () => {
    useSendReply.mockReturnValue(sendState());
    const onDraftChange = vi.fn();
    const { rerender } = render(
      <I18nProvider locale="es">
        <ReplyComposer
          conversationId="conversation-1"
          gate={{ enabled: true }}
          draft="lo que habia escrito"
          onDraftChange={onDraftChange}
        />
      </I18nProvider>,
    );
    expect(textarea()).toHaveValue("lo que habia escrito");

    fireEvent.change(textarea(), { target: { value: "corregido" } });
    expect(onDraftChange).toHaveBeenCalledWith("corregido");
    // Controlled: it does not move on its own until the owner hands the new value back.
    expect(textarea()).toHaveValue("lo que habia escrito");

    rerender(
      <I18nProvider locale="es">
        <ReplyComposer
          conversationId="conversation-1"
          gate={{ enabled: true }}
          draft="corregido"
          onDraftChange={onDraftChange}
        />
      </I18nProvider>,
    );
    expect(textarea()).toHaveValue("corregido");
  });

  it("clears the draft upward on a successful send, and leaves it alone on a failure", () => {
    const ok = sendState({
      mutate: vi.fn((_c: string, opts?: { onSuccess?: () => void }) => opts?.onSuccess?.()),
    });
    useSendReply.mockReturnValue(ok);
    const cleared = vi.fn();
    render(
      <I18nProvider locale="es">
        <ReplyComposer
          conversationId="conversation-1"
          gate={{ enabled: true }}
          draft="Vamos a mirarlo"
          onDraftChange={cleared}
        />
      </I18nProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: /Enviar respuesta|Enviando/ }));
    expect(cleared).toHaveBeenCalledWith("");

    // A failure must not clear it: the surviving text is the only thing left saying
    // "this was never sent" once the mutation's own error state dies with the remount.
    const failing = sendState({
      mutate: vi.fn((_c: string, _opts?: { onSuccess?: () => void }) => undefined),
      isError: true,
      error: new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
    });
    useSendReply.mockReturnValue(failing);
    const untouched = vi.fn();
    render(
      <I18nProvider locale="es">
        <ReplyComposer
          conversationId="conversation-2"
          gate={{ enabled: true }}
          draft="no se ha enviado"
          onDraftChange={untouched}
        />
      </I18nProvider>,
    );
    const buttons = screen.getAllByRole("button", { name: /Enviar respuesta|Enviando/ });
    fireEvent.click(buttons[buttons.length - 1]);
    expect(untouched).not.toHaveBeenCalled();
  });

  it("does not refuse an identical reply to another conversation as a double submit", () => {
    const state = sendState({
      mutate: vi.fn((_content: string, opts?: { onSuccess?: () => void }) => {
        opts?.onSuccess?.();
      }),
    });
    useSendReply.mockReturnValue(state);
    const view = (conversationId: string, draft: string) => (
      <I18nProvider locale="es">
        <ReplyComposer
          conversationId={conversationId}
          gate={{ enabled: true }}
          draft={draft}
          onDraftChange={() => undefined}
        />
      </I18nProvider>
    );
    const { rerender } = render(view("conversation-1", "Gracias"));
    fireEvent.click(screen.getByRole("button", { name: /Enviar respuesta|Enviando/ }));
    expect(state.mutate).toHaveBeenCalledTimes(1);
    // Sent here, so the same text is refused — that guard is R4.5 and must survive.
    rerender(view("conversation-1", "Gracias"));
    expect(screen.getByRole("button", { name: /Enviar respuesta|Enviando/ })).toBeDisabled();

    // Another conversation, same words: a legitimate reply, not a double submit.
    rerender(view("conversation-2", "Gracias"));
    expect(screen.getByRole("button", { name: /Enviar respuesta|Enviando/ })).toBeEnabled();
  });
});
