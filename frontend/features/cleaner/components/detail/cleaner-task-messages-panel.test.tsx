import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import {
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
} from "@/test/render";

import type {
  CleanerDataSource,
  CleaningTaskMessage,
  PaginatedResponse,
} from "../../data";
import { CleanerTaskMessagesPanel } from "./cleaner-task-messages-panel";

const listTasks = vi.hoisted(() => vi.fn());
const getTask = vi.hoisted(() => vi.fn());
const getTaskContext = vi.hoisted(() => vi.fn());
const getTaskChecklist = vi.hoisted(() => vi.fn());
const getTaskPhotoRequirements = vi.hoisted(() => vi.fn());
const getTaskPhotos = vi.hoisted(() => vi.fn());
const acceptTask = vi.hoisted(() => vi.fn());
const rejectTask = vi.hoisted(() => vi.fn());
const startTask = vi.hoisted(() => vi.fn());
const completeTask = vi.hoisted(() => vi.fn());
const completeChecklistItem = vi.hoisted(() => vi.fn());
const uploadPhoto = vi.hoisted(() => vi.fn());
const reportIncident = vi.hoisted(() => vi.fn());
const getTaskMessages = vi.hoisted(() => vi.fn());
const sendTaskMessage = vi.hoisted(() => vi.fn());

const tenantId = vi.hoisted(() => ({ current: "tenant-1" }));

vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth")>()),
  useAuth: () => ({
    user: { tenant_id: tenantId.current, role: "CLEANER" },
  }),
}));
vi.mock("@/lib/auth/auth-provider", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/auth-provider")>()),
  useAuth: () => ({
    user: { tenant_id: tenantId.current, role: "CLEANER" },
  }),
}));

vi.mock("../../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../data")>()),
  getCleanerDataSource: (): CleanerDataSource => ({
    listTasks,
    getTask,
    getTaskContext,
    getTaskChecklist,
    getTaskPhotoRequirements,
    getTaskPhotos,
    acceptTask,
    rejectTask,
    startTask,
    completeTask,
    completeChecklistItem,
    uploadPhoto,
    reportIncident,
    getTaskMessages,
    sendTaskMessage,
  }),
}));

function message(
  id: string,
  content: string,
  authorRole: CleaningTaskMessage["authorRole"] = "PROPERTY_MANAGER",
): CleaningTaskMessage {
  return {
    id,
    authorId: "user-1",
    authorRole,
    content,
    createdAt: "2026-08-20T10:00:00Z",
  };
}

function page(
  rows: CleaningTaskMessage[],
  overrides: Partial<PaginatedResponse<CleaningTaskMessage>> = {},
): PaginatedResponse<CleaningTaskMessage> {
  return {
    data: rows,
    total: rows.length,
    page: 1,
    perPage: 20,
    totalPages: rows.length === 0 ? 0 : 1,
    ...overrides,
  };
}

// `onNotFound` is left off by default on purpose: that is the standalone
// fallback path, where the panel owns its own not-found rendering. The tests
// that care about the parent-driven path pass it explicitly.
function renderPanel(enabled = true, onNotFound?: () => void) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(
    <CleanerTaskMessagesPanel
      taskId="task-1"
      enabled={enabled}
      onNotFound={onNotFound}
    />,
    { wrapper: Wrapper },
  );
}

const sendButton = () => screen.getByRole("button", { name: "Enviar mensaje" });
const composer = () => screen.getByLabelText("Escribe un mensaje");

beforeEach(() => {
  tenantId.current = "tenant-1";
  for (const mock of [
    listTasks,
    getTask,
    getTaskContext,
    getTaskChecklist,
    getTaskPhotoRequirements,
    getTaskPhotos,
    acceptTask,
    rejectTask,
    startTask,
    completeTask,
    completeChecklistItem,
    uploadPhoto,
    reportIncident,
  ]) {
    mock.mockReset();
  }
  getTaskMessages.mockReset().mockResolvedValue(page([]));
  sendTaskMessage
    .mockReset()
    .mockResolvedValue(message("message-new", "enviado", "CLEANER"));
});

describe("CleanerTaskMessagesPanel — list states (R4)", () => {
  it("shows LoadingState while the first page is in flight (R4.1)", async () => {
    getTaskMessages.mockReturnValue(new Promise(() => {}));
    renderPanel();
    await waitFor(() => expect(getTaskMessages).toHaveBeenCalled());
    expect(screen.getByText("Cargando los mensajes…")).toBeInTheDocument();
  });

  it("shows an explicit EmptyState, not a blank gap, on an empty thread (R4.2)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Todavía no hay mensajes")).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows ErrorState when the list request fails (R4.3)", async () => {
    getTaskMessages.mockRejectedValue(
      new ApiError({ status: 403, code: "FORBIDDEN", message: "boom" }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(/No hemos podido cargar los mensajes/),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/boom/)).toBeNull();
  });

  // Standalone fallback: with no parent listening, the panel still has to say
  // something rather than go silently blank with no way out.
  it("shows the task-unavailable empty state on a 404 with no onNotFound (R4.3)", async () => {
    getTaskMessages.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Tarea no disponible")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Escribe un mensaje")).toBeNull();
  });

  // Parent-driven: the detail view is about to replace the entire screen with
  // its own not-found EmptyState (the one with the back button). Painting the
  // weaker, tab-confined panel-local EmptyState first would flash for a frame,
  // so the panel renders nothing at all and lets the parent's swap be the only
  // thing the cleaner ever sees.
  it("renders nothing and notifies the parent on a 404 when onNotFound is given (R4.3)", async () => {
    getTaskMessages.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    const onNotFound = vi.fn();
    const { container } = renderPanel(true, onNotFound);

    await waitFor(() => expect(onNotFound).toHaveBeenCalled());

    // `useLayoutEffect` fires within the same commit as the render that
    // detected the 404, so by the time the callback has run there is nothing
    // of the panel left in the DOM — no competing EmptyState to flash.
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText("Tarea no disponible")).toBeNull();
    expect(screen.queryByLabelText("Escribe un mensaje")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("replaces the whole panel, typed draft included, when a 404 arrives after the thread loaded (R4.3)", async () => {
    getTaskMessages.mockImplementation(
      (_tenant: string, _task: string, requested: number) =>
        requested === 1
          ? Promise.resolve(
              page([message("m-1", "antiguo")], {
                page: 1,
                total: 2,
                totalPages: 2,
              }),
            )
          : Promise.reject(
              new ApiError({
                status: 404,
                code: "NOT_FOUND",
                message: "missing",
              }),
            ),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("antiguo")).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "llego tarde" } });
    expect(composer()).toHaveValue("llego tarde");

    // The task disappears under the cleaner while she was writing: the next
    // read of the thread 404s.
    fireEvent.click(
      screen.getByRole("button", { name: "Cargar mensajes más recientes" }),
    );

    // Intentional, and the same convention every parallel read of this screen
    // follows: a 404 swaps the entire detail surface for the "task not
    // available" EmptyState — composer, draft and already-loaded rows go with
    // it, because there is nowhere left to send that draft.
    await waitFor(() =>
      expect(screen.getByText("Tarea no disponible")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Escribe un mensaje")).toBeNull();
    expect(screen.queryByText("antiguo")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("lists the messages oldest-first with their author role (R1.1)", async () => {
    getTaskMessages.mockResolvedValue(
      page([
        message("m-1", "primero"),
        message("m-2", "segundo", "CLEANER"),
      ]),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("primero")).toBeInTheDocument(),
    );
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("primero");
    expect(items[1]).toHaveTextContent("segundo");
    expect(screen.getByText("Gestora")).toBeInTheDocument();
    expect(screen.getByText("Limpiadora")).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    getTaskMessages.mockResolvedValue(page([message("m-1", "hola")]));
    const { container } = renderPanel();
    await waitFor(() => expect(screen.getByText("hola")).toBeInTheDocument());
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("CleanerTaskMessagesPanel — lazy query (design D1)", () => {
  it("does not request the thread while the tab has not been opened", async () => {
    renderPanel(false);
    await waitFor(() =>
      expect(screen.getByText("Cargando los mensajes…")).toBeInTheDocument(),
    );
    expect(getTaskMessages).not.toHaveBeenCalled();
  });

  it("requests page 1 once the tab flag is true", async () => {
    renderPanel(true);
    await waitFor(() =>
      expect(getTaskMessages).toHaveBeenCalledWith("tenant-1", "task-1", 1),
    );
  });
});

describe("CleanerTaskMessagesPanel — pagination (design D4)", () => {
  it("appends the newer page instead of replacing the one on screen", async () => {
    getTaskMessages.mockImplementation(
      (_tenant: string, _task: string, requested: number) =>
        Promise.resolve(
          requested === 1
            ? page([message("m-1", "antiguo")], {
                page: 1,
                total: 2,
                totalPages: 2,
              })
            : page([message("m-2", "reciente")], {
                page: 2,
                total: 2,
                totalPages: 2,
              }),
        ),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("antiguo")).toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Cargar mensajes más recientes" }),
    );
    await waitFor(() =>
      expect(screen.getByText("reciente")).toBeInTheDocument(),
    );
    expect(screen.getByText("antiguo")).toBeInTheDocument();
    const items = screen.getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("antiguo");
    expect(items[1]).toHaveTextContent("reciente");
  });

  it("offers no load button when the open page is the last one", async () => {
    getTaskMessages.mockResolvedValue(page([message("m-1", "único")]));
    renderPanel();
    await waitFor(() => expect(screen.getByText("único")).toBeInTheDocument());
    expect(
      screen.queryByRole("button", { name: "Cargar mensajes más recientes" }),
    ).toBeNull();
  });
});

describe("CleanerTaskMessagesPanel — composer (R1.2, R1.3, R1.4, D6)", () => {
  it("keeps the send control disabled while the field is empty (R1.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Todavía no hay mensajes")).toBeInTheDocument(),
    );
    expect(sendButton()).toBeDisabled();
    expect(screen.getByText("0/2000 caracteres")).toBeInTheDocument();
  });

  it("shows the inline validation and never calls the backend on blank content (R1.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Todavía no hay mensajes")).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "hola" } });
    expect(sendButton()).toBeEnabled();

    fireEvent.change(composer(), { target: { value: "   " } });
    expect(sendButton()).toBeDisabled();
    expect(
      screen.getByText("Escribe un mensaje antes de enviarlo."),
    ).toBeInTheDocument();
    fireEvent.click(sendButton());
    await waitFor(() => expect(sendTaskMessage).not.toHaveBeenCalled());
  });

  it("caps the textarea at the contract's 2000 characters (R1.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Todavía no hay mensajes")).toBeInTheDocument(),
    );
    expect(composer()).toHaveAttribute("maxlength", "2000");
  });

  it("sends the trimmed content and clears the field on success (R1.2)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Todavía no hay mensajes")).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "  llego tarde  " } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(sendTaskMessage).toHaveBeenCalledWith(
        "tenant-1",
        "task-1",
        "llego tarde",
      ),
    );
    await waitFor(() => expect(composer()).toHaveValue(""));
  });

  it("disables the send control while the request is in flight (R1.4)", async () => {
    let resolveSend: ((value: CleaningTaskMessage) => void) | undefined;
    sendTaskMessage.mockReturnValue(
      new Promise<CleaningTaskMessage>((resolve) => {
        resolveSend = resolve;
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Todavía no hay mensajes")).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "llego tarde" } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Enviando…" }),
      ).toBeDisabled(),
    );
    expect(sendTaskMessage).toHaveBeenCalledTimes(1);
    resolveSend?.(message("m-new", "llego tarde", "CLEANER"));
  });

  it("follows the thread's tail when the sent message opens a new page (R1.2)", async () => {
    let sent = false;
    getTaskMessages.mockImplementation(
      (_tenant: string, _task: string, requested: number) => {
        if (requested === 2) {
          return Promise.resolve(
            page([message("m-2", "llego tarde", "CLEANER")], {
              page: 2,
              total: 2,
              totalPages: 2,
            }),
          );
        }
        return Promise.resolve(
          page([message("m-1", "antiguo")], {
            page: 1,
            total: sent ? 2 : 1,
            totalPages: sent ? 2 : 1,
          }),
        );
      },
    );
    sendTaskMessage.mockImplementation(() => {
      sent = true;
      return Promise.resolve(message("m-2", "llego tarde", "CLEANER"));
    });
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("antiguo")).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "llego tarde" } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(screen.getByText("llego tarde")).toBeInTheDocument(),
    );
    // The page left behind is still on screen: the list grew, it did not swap.
    expect(screen.getByText("antiguo")).toBeInTheDocument();
  });

  it("keeps the typed text and shows the mapped copy when the send fails (R4.3)", async () => {
    sendTaskMessage.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "content too long",
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(screen.getByText("Todavía no hay mensajes")).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "llego tarde" } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(
        screen.getByText("El mensaje no puede pasar de 2000 caracteres."),
      ).toBeInTheDocument(),
    );
    expect(composer()).toHaveValue("llego tarde");
    expect(screen.queryByText(/content too long/)).toBeNull();
  });
});
