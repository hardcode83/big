import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type {
  ConversationDetail,
  ConversationPage,
  ThreadMessage,
} from "../data/dto";
import { ConversationThread } from "./conversation-thread";

const useConversation = vi.hoisted(() => vi.fn());
const useThread = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-conversations", () => ({ useConversation, useThread }));

// This suite covers the read surface; the write controls have their own tests, so
// the session here is a role that cannot operate the inbox.
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1", role: "TENANT_OWNER" } }),
}));

const detail: ConversationDetail = {
  id: "conversation-1",
  propertyId: "property-1",
  guestId: null,
  reservationId: null,
  channel: "WHATSAPP",
  status: "OPEN",
  escalationStatus: "NONE",
  language: "es",
  aiEnabled: true,
  lastMessageAt: "2026-08-19T10:00:00Z",
  createdAt: "2026-08-10T09:00:00Z",
  updatedAt: "2026-08-19T10:00:00Z",
};

function message(id: string, content: string): ThreadMessage {
  return {
    id,
    conversationId: "conversation-1",
    senderType: "GUEST",
    senderUserId: null,
    content,
    language: "es",
    intent: null,
    aiGenerated: false,
    confidenceScore: null,
    deliveryStatus: null,
    escalationReason: null,
    createdAt: "2026-08-19T10:00:00Z",
  };
}

function threadPage(
  items: ThreadMessage[],
  overrides: Partial<ConversationPage<ThreadMessage>> = {},
): ConversationPage<ThreadMessage> {
  return {
    items,
    page: 1,
    perPage: 50,
    total: items.length,
    totalPages: 1,
    ...overrides,
  };
}

function renderThread(conversationId = "conversation-1") {
  return render(
    <I18nProvider locale="es">
      <ConversationThread
        conversationId={conversationId}
        draft=""
        onDraftChange={() => undefined}
        onDraftSent={() => undefined}
      />
    </I18nProvider>,
  );
}

beforeEach(() => {
  useConversation.mockReset();
  useThread.mockReset();
  useConversation.mockReturnValue({
    isPending: false,
    isError: false,
    data: detail,
  });
  useThread.mockReturnValue({
    isPending: false,
    isError: false,
    data: threadPage([]),
  });
});

describe("ConversationThread — order preserved (task 6.3, R3.2, R3.5)", () => {
  it("renders the messages in the ascending order the backend returned", () => {
    useThread.mockReturnValue({
      isPending: false,
      isError: false,
      data: threadPage([
        message("m1", "primero"),
        message("m2", "segundo"),
        message("m3", "tercero"),
      ]),
    });
    renderThread();

    const bubbles = screen.getAllByRole("listitem");
    expect(bubbles.map((bubble) => bubble.textContent)).toEqual([
      expect.stringContaining("primero"),
      expect.stringContaining("segundo"),
      expect.stringContaining("tercero"),
    ]);
  });

  it("keeps the ascending order across two pages and replaces the page, not appends it", () => {
    useThread.mockReturnValue({
      isPending: false,
      isError: false,
      data: threadPage([message("m3", "tercero"), message("m4", "cuarto")], {
        page: 2,
        total: 4,
        totalPages: 2,
      }),
    });
    const { unmount } = renderThread();

    expect(
      screen.getAllByRole("listitem").map((bubble) => bubble.textContent),
    ).toEqual([
      expect.stringContaining("tercero"),
      expect.stringContaining("cuarto"),
    ]);
    expect(screen.getByText("Página 2 de 2")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Anterior" }));
    expect(useThread).toHaveBeenLastCalledWith("conversation-1", 1);
    unmount();

    useThread.mockReturnValue({
      isPending: false,
      isError: false,
      data: threadPage([message("m1", "primero"), message("m2", "segundo")], {
        page: 1,
        total: 4,
        totalPages: 2,
      }),
    });
    renderThread();

    const bubbles = screen.getAllByRole("listitem");
    expect(bubbles).toHaveLength(2);
    expect(bubbles.map((bubble) => bubble.textContent)).toEqual([
      expect.stringContaining("primero"),
      expect.stringContaining("segundo"),
    ]);
  });

  // Exercises the component's own fallback: `ConversationsView` never reaches this
  // path because it keys the subtree per conversation (D22), so this is a standalone
  // contract for a caller that forgets the key, not integration coverage.
  it("asks for page 1 again when another conversation is selected", () => {
    useThread.mockReturnValue({
      isPending: false,
      isError: false,
      data: threadPage([message("m1", "primero")], {
        page: 1,
        total: 120,
        totalPages: 3,
      }),
    });
    const { rerender } = renderThread();

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(useThread).toHaveBeenLastCalledWith("conversation-1", 2);

    rerender(
      <I18nProvider locale="es">
        <ConversationThread
        conversationId="conversation-2"
        draft=""
        onDraftChange={() => undefined}
        onDraftSent={() => undefined}
      />
      </I18nProvider>,
    );
    expect(useThread).toHaveBeenLastCalledWith("conversation-2", 1);
  });
});

describe("ConversationThread — the three read failures (task 6.5, D17, D18)", () => {
  it("shows a localized «no encontrada» with no retry on a 404", () => {
    useConversation.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "NOT_FOUND", message: "gone", status: 404 }),
      refetch: vi.fn(),
    });
    renderThread();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Conversación no encontrada");
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
    expect(alert).not.toHaveTextContent("gone");
  });

  it("shows the no-access state with no retry on a 403", () => {
    useConversation.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "denied", status: 403 }),
      refetch: vi.fn(),
    });
    renderThread();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Sin acceso a las conversaciones");
    expect(alert).not.toHaveTextContent("denied");
    expect(alert).not.toHaveTextContent("403");
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
  });

  it("offers a working retry on any other failure", () => {
    const refetch = vi.fn();
    useConversation.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
      refetch,
    });
    renderThread();

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("No se pudo cargar la conversación");
    expect(alert).not.toHaveTextContent("boom");
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("shows the shared loading state while the conversation is pending", () => {
    useConversation.mockReturnValue({ isPending: true, isError: false });
    renderThread();
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
  });

  it("shows the empty state for a conversation with no messages yet", () => {
    renderThread();
    expect(
      screen.getByText("Esta conversación todavía no tiene mensajes."),
    ).toBeInTheDocument();
  });

  it("keeps the header readable when the message page itself fails", () => {
    useThread.mockReturnValue({
      isPending: false,
      isError: true,
      error: new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
      refetch: vi.fn(),
    });
    renderThread();

    expect(screen.getByText("WhatsApp")).toBeInTheDocument();
    expect(screen.getByText(/Idioma detectado: es/)).toBeInTheDocument();
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("No se pudo cargar la conversación");
    expect(alert).not.toHaveTextContent("boom");
    expect(alert).not.toHaveTextContent("500");
  });

  it("keeps the way back when a non-first page comes back empty (R3.5)", () => {
    useThread.mockReturnValue({
      isPending: false,
      isError: false,
      data: threadPage([], { page: 3, total: 40, totalPages: 3 }),
    });
    renderThread();

    // The thread shrank under us: the page is empty but page 3 of 3 still exists,
    // so navigation must survive or the reader has no way off this page.
    expect(
      screen.getByText("Esta conversación todavía no tiene mensajes."),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Paginación" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Anterior" }));
    expect(useThread).toHaveBeenLastCalledWith("conversation-1", 2);
  });
});
