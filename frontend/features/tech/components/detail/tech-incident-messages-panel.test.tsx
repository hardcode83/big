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
import esTech from "@/locales/es/tech.json";
import type { IncidentMessage, PaginatedResponse } from "@/features/incidents";
import * as incidentsData from "@/features/incidents/data";

const TENANT = "tenant-1";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT, role: "TECHNICIAN" } }),
}));

const getIncidentMessages = vi.fn();
const sendIncidentMessage = vi.fn();

vi.spyOn(incidentsData, "getIncidentsDataSource").mockImplementation(
  () =>
    ({
      getIncidentMessages,
      sendIncidentMessage,
    }) as unknown as ReturnType<typeof incidentsData.getIncidentsDataSource>,
);

import { TechIncidentMessagesPanel } from "./tech-incident-messages-panel";

function message(
  id: string,
  content: string,
  authorRole: IncidentMessage["authorRole"] = "PROPERTY_MANAGER",
): IncidentMessage {
  return {
    id,
    authorId: "user-1",
    authorRole,
    content,
    createdAt: "2026-08-20T10:00:00Z",
  };
}

function page(
  rows: IncidentMessage[],
  overrides: Partial<PaginatedResponse<IncidentMessage>> = {},
): PaginatedResponse<IncidentMessage> {
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
    <TechIncidentMessagesPanel
      incidentId="i1"
      enabled={enabled}
      onNotFound={onNotFound}
    />,
    { wrapper: Wrapper },
  );
}

const sendButton = () =>
  screen.getByRole("button", { name: esTech.messages.composer.send });
const composer = () => screen.getByLabelText(esTech.messages.composer.label);
const loadNewer = () =>
  screen.getByRole("button", { name: esTech.messages.loadNewer });

beforeEach(() => {
  getIncidentMessages.mockReset().mockResolvedValue(page([]));
  sendIncidentMessage
    .mockReset()
    .mockResolvedValue(message("m-new", "enviado", "TECHNICIAN"));
});

describe("TechIncidentMessagesPanel — list states (R4)", () => {
  it("shows LoadingState while the first page is in flight (R4.1)", async () => {
    getIncidentMessages.mockReturnValue(new Promise(() => {}));
    renderPanel();
    await waitFor(() => expect(getIncidentMessages).toHaveBeenCalled());
    expect(screen.getByText(esTech.messages.loading)).toBeInTheDocument();
  });

  it("shows an explicit EmptyState, not a blank gap, on an empty thread (R4.2)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.empty.title),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows ErrorState when the list request fails (R4.3)", async () => {
    // A 4xx on purpose: the hook keeps `retry: retryPolicy`, which the test
    // client's `retry: false` does not override, so a 5xx fixture would retry
    // twice and time the test out.
    getIncidentMessages.mockRejectedValue(
      new ApiError({ status: 403, code: "FORBIDDEN", message: "boom" }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.error.title),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText(/boom/)).toBeNull();
  });

  // Standalone fallback: with no parent listening, the panel still has to say
  // something rather than go silently blank with no way out.
  it("shows the incident-unavailable empty state on a 404 with no onNotFound (R4.3)", async () => {
    getIncidentMessages.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.detail.unavailable.title),
      ).toBeInTheDocument(),
    );
    expect(
      screen.queryByLabelText(esTech.messages.composer.label),
    ).toBeNull();
  });

  // Parent-driven: the detail view is about to replace the entire screen with
  // its own not-found EmptyState. Painting the weaker, tab-confined
  // panel-local EmptyState first would flash for a frame, so the panel renders
  // nothing at all and lets the parent's swap be the only thing the technician
  // ever sees.
  it("renders nothing and notifies the parent on a 404 when onNotFound is given (R4.3)", async () => {
    getIncidentMessages.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "missing" }),
    );
    const onNotFound = vi.fn();
    const { container } = renderPanel(true, onNotFound);

    await waitFor(() => expect(onNotFound).toHaveBeenCalled());

    // `useLayoutEffect` fires within the same commit as the render that
    // detected the 404, so by the time the callback has run there is nothing
    // of the panel left in the DOM — no competing EmptyState to flash.
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(esTech.detail.unavailable.title)).toBeNull();
    expect(screen.queryByLabelText(esTech.messages.composer.label)).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("replaces the whole panel, typed draft included, when a 404 arrives after the thread loaded (R4.3)", async () => {
    getIncidentMessages.mockImplementation(
      (_tenant: string, _incident: string, requested: number) =>
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

    // The incident disappears under the technician while he was writing: the
    // next read of the thread 404s.
    fireEvent.click(loadNewer());

    // Intentional, and the same convention every parallel read of this screen
    // follows: a 404 swaps the whole surface for the "incident not available"
    // EmptyState — composer, draft and already-loaded rows go with it, because
    // there is nowhere left to send that draft.
    await waitFor(() =>
      expect(
        screen.getByText(esTech.detail.unavailable.title),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText(esTech.messages.composer.label)).toBeNull();
    expect(screen.queryByText("antiguo")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("lists the messages oldest-first with their author role (R2.1)", async () => {
    getIncidentMessages.mockResolvedValue(
      page([
        message("m-1", "primero"),
        message("m-2", "segundo", "TECHNICIAN"),
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
      screen.getByText(esTech.messages.roles.PROPERTY_MANAGER),
    ).toBeInTheDocument();
    expect(
      screen.getByText(esTech.messages.roles.TECHNICIAN),
    ).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    getIncidentMessages.mockResolvedValue(page([message("m-1", "hola")]));
    const { container } = renderPanel();
    await waitFor(() => expect(screen.getByText("hola")).toBeInTheDocument());
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("TechIncidentMessagesPanel — lazy query (design D1)", () => {
  it("does not request the thread while the tab has not been opened", async () => {
    renderPanel(false);
    await waitFor(() =>
      expect(screen.getByText(esTech.messages.loading)).toBeInTheDocument(),
    );
    expect(getIncidentMessages).not.toHaveBeenCalled();
  });

  it("requests page 1 once the tab flag is true", async () => {
    renderPanel(true);
    await waitFor(() =>
      expect(getIncidentMessages).toHaveBeenCalledWith(TENANT, "i1", 1),
    );
  });
});

describe("TechIncidentMessagesPanel — pagination (design D4)", () => {
  it("appends the newer page instead of replacing the one on screen", async () => {
    getIncidentMessages.mockImplementation(
      (_tenant: string, _incident: string, requested: number) =>
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
    getIncidentMessages.mockResolvedValue(page([message("m-1", "único")]));
    renderPanel();
    await waitFor(() => expect(screen.getByText("único")).toBeInTheDocument());
    expect(
      screen.queryByRole("button", { name: esTech.messages.loadNewer }),
    ).toBeNull();
  });
});

describe("TechIncidentMessagesPanel — composer (R2.2, R2.3, R2.4, D6)", () => {
  it("keeps the send control disabled while the field is empty (R2.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.empty.title),
      ).toBeInTheDocument(),
    );
    expect(sendButton()).toBeDisabled();
    expect(screen.getByText("0/2000 caracteres")).toBeInTheDocument();
  });

  it("shows the inline validation and never calls the backend on blank content (R2.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "hola" } });
    expect(sendButton()).toBeEnabled();

    fireEvent.change(composer(), { target: { value: "   " } });
    expect(sendButton()).toBeDisabled();
    expect(
      screen.getByText(esTech.messages.errors.required),
    ).toBeInTheDocument();
    fireEvent.click(sendButton());
    await waitFor(() => expect(sendIncidentMessage).not.toHaveBeenCalled());
  });

  it("caps the textarea at the contract's 2000 characters (R2.3)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.empty.title),
      ).toBeInTheDocument(),
    );
    expect(composer()).toHaveAttribute("maxlength", "2000");
  });

  it("sends the trimmed content and clears the field on success (R2.2)", async () => {
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "  llego tarde  " } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(sendIncidentMessage).toHaveBeenCalledWith(
        TENANT,
        "i1",
        "llego tarde",
      ),
    );
    await waitFor(() => expect(composer()).toHaveValue(""));
  });

  it("disables the send control while the request is in flight (R2.4)", async () => {
    let resolveSend: ((value: IncidentMessage) => void) | undefined;
    sendIncidentMessage.mockReturnValue(
      new Promise<IncidentMessage>((resolve) => {
        resolveSend = resolve;
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "llego tarde" } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: esTech.messages.composer.sending }),
      ).toBeDisabled(),
    );
    expect(sendIncidentMessage).toHaveBeenCalledTimes(1);
    resolveSend?.(message("m-new", "llego tarde", "TECHNICIAN"));
  });

  it("follows the thread's tail when the sent message opens a new page (R2.2)", async () => {
    let sent = false;
    getIncidentMessages.mockImplementation(
      (_tenant: string, _incident: string, requested: number) => {
        if (requested === 2) {
          return Promise.resolve(
            page([message("m-2", "llego tarde", "TECHNICIAN")], {
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
    sendIncidentMessage.mockImplementation(() => {
      sent = true;
      return Promise.resolve(message("m-2", "llego tarde", "TECHNICIAN"));
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

  it("keeps the typed text and shows the length copy when the send is rejected with a 422 (R4.3)", async () => {
    sendIncidentMessage.mockRejectedValue(
      new ApiError({
        status: 422,
        code: "VALIDATION_ERROR",
        message: "content too long",
      }),
    );
    renderPanel();
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.empty.title),
      ).toBeInTheDocument(),
    );
    fireEvent.change(composer(), { target: { value: "llego tarde" } });
    fireEvent.click(sendButton());
    await waitFor(() =>
      expect(
        screen.getByText(esTech.messages.errors.tooLong),
      ).toBeInTheDocument(),
    );
    expect(composer()).toHaveValue("llego tarde");
    expect(screen.queryByText(/content too long/)).toBeNull();
  });

  /**
   * `mapIncidentsError` has no `kind` parameter and returns no `messageKey`
   * (unlike `cleaner`'s mapper), so the kind → copy table lives in the panel.
   * These are the branches of that table that a send can actually reach.
   */
  it.each<[number, string]>([
    [404, esTech.messages.errors.notFound],
    [403, esTech.messages.errors.forbidden],
    [409, esTech.messages.errors.generic],
  ])(
    "maps a %s on the send to its own copy and keeps the draft (R4.3)",
    async (status, copy) => {
      sendIncidentMessage.mockRejectedValue(
        new ApiError({ status, code: "X", message: "english detail" }),
      );
      renderPanel();
      await waitFor(() =>
        expect(
          screen.getByText(esTech.messages.empty.title),
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
