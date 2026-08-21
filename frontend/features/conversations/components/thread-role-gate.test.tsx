import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { ConversationDetail, ThreadMessage, UserRole } from "../data/dto";
import { ConversationThread } from "./conversation-thread";

const session = vi.hoisted(() => ({
  user: { tenant_id: "tenant-1", role: "TENANT_OWNER" as UserRole },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: session.user }) }));

const useConversation = vi.hoisted(() => vi.fn());
const useThread = vi.hoisted(() => vi.fn());
vi.mock("../hooks/use-conversations", () => ({ useConversation, useThread }));

interface ActionState {
  mutate: ReturnType<typeof vi.fn>;
  reset?: ReturnType<typeof vi.fn>;
  isPending: boolean;
  isError: boolean;
  error: Error | null;
}

function idleAction(): ActionState {
  return { mutate: vi.fn(), isPending: false, isError: false, error: null };
}

const escalateState = vi.hoisted(() => ({
  current: { mutate: vi.fn(), isPending: false, isError: false, error: null } as {
    mutate: ReturnType<typeof vi.fn>;
    isPending: boolean;
    isError: boolean;
    error: Error | null;
  },
}));
const resolveState = vi.hoisted(() => ({
  current: { mutate: vi.fn(), isPending: false, isError: false, error: null } as {
    mutate: ReturnType<typeof vi.fn>;
    isPending: boolean;
    isError: boolean;
    error: Error | null;
  },
}));
const sendState = vi.hoisted(() => ({
  current: { mutate: vi.fn(), isPending: false, isError: false, error: null } as {
    mutate: ReturnType<typeof vi.fn>;
    isPending: boolean;
    isError: boolean;
    error: Error | null;
  },
}));
const transcribeState = vi.hoisted(() => ({
  current: {
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  } as {
    mutate: ReturnType<typeof vi.fn>;
    reset: ReturnType<typeof vi.fn>;
    isPending: boolean;
    isError: boolean;
    error: Error | null;
  },
}));
vi.mock("../hooks/use-conversation-actions", () => ({
  useEscalate: () => escalateState.current,
  useResolve: () => resolveState.current,
  useSendReply: () => sendState.current,
  useTranscribeGuestMessage: () => transcribeState.current,
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

const message: ThreadMessage = {
  id: "message-1",
  conversationId: "conversation-1",
  senderType: "GUEST",
  senderUserId: null,
  content: "No hay agua caliente",
  language: "es",
  intent: null,
  aiGenerated: false,
  confidenceScore: null,
  deliveryStatus: null,
  escalationReason: null,
  createdAt: "2026-08-19T10:00:00Z",
};

function renderThread(role: UserRole) {
  session.user = { tenant_id: "tenant-1", role };
  render(
    <I18nProvider locale="es">
      <ConversationThread conversationId="conversation-1" />
    </I18nProvider>,
  );
}

const MANAGEMENT_CONTROLS = [
  "Escalar a una persona",
  "Marcar como resuelta",
  "Transcribir mensaje del huésped",
  "Enviar respuesta",
];

beforeEach(() => {
  useConversation.mockReset();
  useThread.mockReset();
  useConversation.mockReturnValue({
    isPending: false,
    isError: false,
    data: detail,
    refetch: vi.fn(),
  });
  useThread.mockReturnValue({
    isPending: false,
    isError: false,
    data: { items: [message], page: 1, perPage: 50, total: 1, totalPages: 1 },
    refetch: vi.fn(),
  });
  escalateState.current = idleAction();
  resolveState.current = idleAction();
  sendState.current = idleAction();
  transcribeState.current = {
    mutate: vi.fn(),
    reset: vi.fn(),
    isPending: false,
    isError: false,
    error: null,
  };
});

describe("the role gate hides, it does not authorize (task 7.5, D12, R6.1)", () => {
  it.each(["TENANT_OWNER", "SUPER_ADMIN", "CLEANER", "TECHNICIAN"] as const)(
    "gives %s the whole thread to read and zero management controls",
    (role) => {
      renderThread(role as UserRole);

      // Reading is intact: the header and the message are both there.
      expect(screen.getByText("WhatsApp")).toBeInTheDocument();
      expect(screen.getByText("No hay agua caliente")).toBeInTheDocument();

      for (const name of MANAGEMENT_CONTROLS) {
        expect(screen.queryByRole("button", { name })).toBeNull();
      }
      expect(screen.queryByLabelText("Responder al huésped")).toBeNull();
    },
  );

  it("gives PROPERTY_MANAGER every management control", () => {
    renderThread("PROPERTY_MANAGER");

    for (const name of MANAGEMENT_CONTROLS) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByLabelText("Responder al huésped")).toBeInTheDocument();
    expect(screen.getByText("No hay agua caliente")).toBeInTheDocument();
  });

  it("still reads a mute channel's warning without any control to act on it", () => {
    useConversation.mockReturnValue({
      isPending: false,
      isError: false,
      data: { ...detail, channel: "AIRBNB_MSG" },
      refetch: vi.fn(),
    });
    renderThread("TENANT_OWNER");

    expect(
      screen.getByText(
        "Este canal es mudo por diseño hasta que llegue el adaptador de mensajería del PMS: lo que escribas se guarda en el hilo, pero no se envía al huésped.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Enviar respuesta" }),
    ).toBeNull();
  });
});

describe("the PHONE_TRANSCRIPT combination D13 calls systematic", () => {
  it("carries no mute warning, yet marks the AI reply as undelivered", () => {
    useConversation.mockReturnValue({
      isPending: false,
      isError: false,
      data: { ...detail, channel: "PHONE_TRANSCRIPT" },
      refetch: vi.fn(),
    });
    useThread.mockReturnValue({
      isPending: false,
      isError: false,
      data: {
        items: [
          message,
          {
            ...message,
            id: "message-2",
            senderType: "AI",
            aiGenerated: true,
            content: "Aviso al técnico",
            deliveryStatus: "FAILED",
            escalationReason: "DELIVERY_FAILED",
          },
        ],
        page: 1,
        perPage: 50,
        total: 2,
        totalPages: 1,
      },
      refetch: vi.fn(),
    });
    renderThread("PROPERTY_MANAGER");

    // D13: `PHONE_TRANSCRIPT` has an `InboundOnlyAdapter`, so it is NOT a mute
    // channel — but every AI reply on it is stored `FAILED`. Both halves at once.
    expect(screen.getByText("Transcripción telefónica")).toBeInTheDocument();
    expect(screen.queryByText(/mudo por diseño/)).toBeNull();
    expect(screen.getByText("No entregado al huésped")).toBeInTheDocument();
  });
});

describe("a 403 on an action the UI showed (task 7.5, D18, R6.3)", () => {
  it("shows the localized permissions error and never retries", () => {
    escalateState.current = {
      mutate: vi.fn(),
      isPending: false,
      isError: true,
      error: new ApiError({ code: "FORBIDDEN", message: "denied", status: 403 }),
    };
    renderThread("PROPERTY_MANAGER");

    const alerts = screen.getAllByRole("alert");
    expect(alerts.some((alert) => alert.textContent?.includes("Tu rol no permite esta acción."))).toBe(true);
    // A permissions failure is not a transient one: nothing offers a retry.
    expect(screen.queryByRole("button", { name: "Reintentar" })).toBeNull();
    expect(escalateState.current.mutate).not.toHaveBeenCalled();
  });
});
