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
import esCleaning from "@/locales/es/cleaning.json";
import type {
  CleanerDataSource,
  CleaningTaskMessage,
  PaginatedResponse,
} from "@/features/cleaner/data";
import * as cleanerData from "@/features/cleaner/data";

const TENANT = "tenant-1";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT, role: "PROPERTY_MANAGER" } }),
  useHasPermission: () => true,
}));

const getTaskMessages = vi.fn();
const sendTaskMessage = vi.fn();

vi.spyOn(cleanerData, "getCleanerDataSource").mockImplementation(
  (): CleanerDataSource =>
    ({
      getTaskMessages,
      sendTaskMessage,
    }) as unknown as CleanerDataSource,
);

import { ManagerCleaningTaskMessagesPanel } from "./manager-cleaning-task-messages-panel";

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
    <ManagerCleaningTaskMessagesPanel
      taskId="task-1"
      enabled={enabled}
      onNotFound={onNotFound}
    />,
    { wrapper: Wrapper },
  );
}

const sendButton = () =>
  screen.getByRole("button", { name: esCleaning.messages.composer.send });
const composer = () =>
  screen.getByLabelText(esCleaning.messages.composer.label);
const loadNewer = () =>
  screen.getByRole("button", { name: esCleaning.messages.loadNewer });

beforeEach(() => {
  getTaskMessages.mockReset().mockResolvedValue(page([]));
  sendTaskMessage
    .mockReset()
    .mockResolvedValue(message("m-new", "enviado", "CLEANER"));
});

describe("ManagerCleaningTaskMessagesPanel — list states (R2.2, R2.5)", () => {
  it("shows LoadingState while the first page is in flight (R2.2)", async () => {
    getTaskMessages.mockReturnValue(new Promise(() => {}));
    renderPanel();
    await waitFor(() => expect(getTaskMessages).toHaveBeenCalled());
    expect(screen.getByText(esCleaning.messages.loading)).toBeInTheDocument();
  });

  it("shows an explicit EmptyState, not a blank gap, on an empty thread (R2.2)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows ErrorState when the list request fails (R2.5)", async () => {
    getTaskMessages.mockRejectedValue(
      new ApiError({ status: 403, code: "FORBIDDEN", message: "boom" }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.error.title),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/boom/)).toBeNull();
  });

  // Standalone fallback: with no parent listening, the panel still has to
  // say something rather than go silently blank with no way out.
  it("shows the task-unavailable empty state on a 404 with no onNotFound (R2.5)", async () => {
    getTaskMessages.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.error.title),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByLabelText(esCleaning.messages.composer.label),
    ).toBeNull();
  });

  // Parent-driven: the detail view is about to replace the entire screen
  // with its own not-found EmptyState. Painting the weaker, tab-confined
  // panel-local EmptyState first would flash for a frame, so the panel
  // renders nothing at all and lets the parent's swap be the only thing
  // the manager ever sees.
  it("renders nothing and notifies the parent on a 404 when onNotFound is given (R2.5)", async () => {
    getTaskMessages.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    const onNotFound = vi.fn();
    const { container } = renderPanel(true, onNotFound);

    await waitFor(() => expect(onNotFound).toHaveBeenCalled());

    // `useLayoutEffect` fires within the same commit as the render that
    // detected the 404, so by the time the callback has run there is
    // nothing of the panel left in the DOM.
    expect(container).toBeEmptyDOMElement();
    expect(
      screen.queryByText(esCleaning.messages.error.title),
    ).toBeNull();
    expect(
      screen.queryByLabelText(esCleaning.messages.composer.label),
    ).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("replaces the whole panel, typed draft included, when a 404 arrives after the thread loaded (R2.5)", async () => {
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

    fireEvent.click(loadNewer());

    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.error.title),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByLabelText(esCleaning.messages.composer.label),
    ).toBeNull();
    expect(screen.queryByText("antiguo")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("lists the messages oldest-first with their author role (R2.2)", async () => {
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
    expect(
      screen.getByText(esCleaning.messages.roles.PROPERTY_MANAGER),
    ).toBeInTheDocument();
    expect(
      screen.getByText(esCleaning.messages.roles.CLEANER),
    ).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    getTaskMessages.mockResolvedValue(page([message("m-1", "hola")]));
    const { container } = renderPanel();
    await waitFor(() => expect(screen.getByText("hola")).toBeInTheDocument());
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("ManagerCleaningTaskMessagesPanel — lazy query (D4)", () => {
  it("does not request the thread while the tab has not been opened", async () => {
    renderPanel(false);
    await waitFor(() =>
      expect(screen.getByText(esCleaning.messages.loading)).toBeInTheDocument(),
    );
    expect(getTaskMessages).not.toHaveBeenCalled();
  });

  it("requests page 1 once the tab flag is true", async () => {
    renderPanel(true);
    await waitFor(() =>
      expect(getTaskMessages).toHaveBeenCalledWith(TENANT, "task-1", 1),
    );
  });
});

describe("ManagerCleaningTaskMessagesPanel — pagination (D4)", () => {
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
    fireEvent.click(loadNewer());
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
      screen.queryByRole("button", { name: esCleaning.messages.loadNewer }),
    ).toBeNull();
  });
});

describe("ManagerCleaningTaskMessagesPanel — composer (R2.3, R2.4, D5)", () => {
  it("keeps the send control disabled while the field is empty (R2.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    expect(sendButton()).toBeDisabled();
    expect(screen.getByText("0/2000 caracteres")).toBeInTheDocument();
  });

  it("shows the inline validation and never calls the backend on blank content (R2.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "hola" } });
    expect(sendButton()).toBeEnabled();

    fireEvent.change(composer(), { target: { value: "   " } });
    expect(sendButton()).toBeDisabled();
    expect(
      screen.getByText(esCleaning.messages.errors.required),
    ).toBeInTheDocument();
    fireEvent.click(sendButton());
    await waitFor(() => expect(sendTaskMessage).not.toHaveBeenCalled());
  });

  it("caps the textarea at the contract's 2000 characters (R2.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    expect(composer()).toHaveAttribute("maxlength", "2000");
  });

  // The `maxlength` attribute above is the browser's constraint on *typing*;
  // paste and programmatic input walk straight past it, which is why the
  // component keeps its own `validate()` (`trim().length` in 1..2000). These
  // two exercise that function through the rendered composer at the exact
  // boundary — jsdom does not clip a programmatic `value`, so the 2001-char
  // case really does reach `validate()`.
  it("accepts exactly 2000 trimmed characters and sends them (R2.3)", async () => {
    const atLimit = "a".repeat(2000);
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: `  ${atLimit}  ` } });

    expect(sendButton()).toBeEnabled();
    expect(screen.queryByText(esCleaning.messages.errors.tooLong)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();

    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(sendTaskMessage).toHaveBeenCalledWith(TENANT, "task-1", atLimit),
    );
  });

  it("rejects 2001 trimmed characters without calling the backend (R2.3)", async () => {
    const overLimit = "a".repeat(2001);
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: `  ${overLimit}  ` } });

    // The value really is past the cap: `maxlength` did not intervene, so
    // what disables the control below is `validate()`, not the DOM.
    expect(composer()).toHaveValue(`  ${overLimit}  `);
    expect(sendButton()).toBeDisabled();
    expect(
      screen.getByText(esCleaning.messages.errors.tooLong),
    ).toBeInTheDocument();

    fireEvent.click(sendButton());
    await waitFor(() => expect(sendTaskMessage).not.toHaveBeenCalled());
  });

  it("sends the trimmed content and clears the field on success (R2.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "  llego tarde  " } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(sendTaskMessage).toHaveBeenCalledWith(
        TENANT,
        "task-1",
        "llego tarde",
      ),
    );
    await waitFor(() => expect(composer()).toHaveValue(""));
  });

  it("disables the send control while the request is in flight (R2.4)", async () => {
    let resolveSend: ((value: CleaningTaskMessage) => void) | undefined;
    sendTaskMessage.mockReturnValue(
      new Promise<CleaningTaskMessage>((resolve) => {
        resolveSend = resolve;
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "llego tarde" } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: esCleaning.messages.composer.sending,
        }),
      ).toBeDisabled(),
    );
    expect(sendTaskMessage).toHaveBeenCalledTimes(1);
    resolveSend?.(message("m-new", "llego tarde", "CLEANER"));
  });

  it("follows the thread's tail when the sent message opens a new page (R2.3)", async () => {
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
    expect(screen.getByText("antiguo")).toBeInTheDocument();
  });

  it("keeps the typed text and shows the length copy when the send is rejected with a 422 (R2.3, R4.3)", async () => {
    sendTaskMessage.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "content too long",
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "llego tarde" } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(
        screen.getByText(esCleaning.messages.errors.tooLong),
      ).toBeInTheDocument(),
    );
    expect(composer()).toHaveValue("llego tarde");
    expect(screen.queryByText(/content too long/)).toBeNull();
  });

  it.each<[number, string]>([
    [404, esCleaning.messages.errors.notFound],
    [403, esCleaning.messages.errors.forbidden],
    [409, esCleaning.messages.errors.generic],
  ])(
    "maps a %s on the send to its own copy and keeps the draft (R2.5)",
    async (status, copy) => {
      sendTaskMessage.mockRejectedValue(
        new ApiError({ status, code: "X", message: "english detail" }),
      );
      renderPanel();
      await waitFor(() =>
        expect(
          screen.getByText(esCleaning.messages.empty.title),
        ).toBeInTheDocument(),
      );
      fireEvent.change(composer(), { target: { value: "llego tarde" } });
      fireEvent.click(sendButton());

      await waitFor(() => expect(screen.getByText(copy)).toBeInTheDocument());
      expect(composer()).toHaveValue("llego tarde");
      expect(screen.queryByText("english detail")).toBeNull();
    },
  );
});
