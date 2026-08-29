import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { useShellUiStore } from "@/features/shell/state/use-shell-ui-store";

import * as dataModule from "../data";
import { NotificationInboxSheet } from "./notification-inbox-sheet";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ status: "authenticated", user: { tenant_id: "t1", id: "u1" } }),
  getSessionGeneration: () => 1,
}));

const listNotifications = vi.fn();
const markRead = vi.fn();
const markAllRead = vi.fn();
vi.spyOn(dataModule, "getNotificationsDataSource").mockImplementation(
  () =>
    ({ listNotifications, markRead, markAllRead }) as unknown as ReturnType<
      typeof dataModule.getNotificationsDataSource
    >,
);

function page(items: unknown[], totalPages = 1) {
  return { items, total: items.length, page: 1, perPage: 20, totalPages };
}

const ROW = {
  id: "n1",
  type: "CLEANING_TASK_ASSIGNED",
  relatedType: null,
  relatedId: null,
  createdAt: "2026-08-29T14:05:00Z",
  readAt: null,
};

function setup() {
  // `useNotifications` sets `retry: retryPolicy`, which retries a network error twice; the
  // zero delay is what lets the error state appear inside a test's patience rather than after
  // exponential backoff. The policy itself is covered in `use-dashboard-data.test.tsx`.
  const client = new QueryClient({
    defaultOptions: { queries: { retryDelay: 0 }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider locale="es">
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </I18nProvider>
    );
  }
  const view = render(
    <NotificationInboxSheet profile="workspace">
      <button type="button">abrir</button>
    </NotificationInboxSheet>,
    { wrapper: Wrapper },
  );
  return { ...view, client };
}

beforeEach(() => {
  vi.clearAllMocks();
  useShellUiStore.setState({ notificationsOpen: true });
});

describe("NotificationInboxSheet (R4.5, R5.2, design D9)", () => {
  it("shows the loading state while the page is in flight", async () => {
    listNotifications.mockImplementation(() => new Promise(() => {}));
    setup();

    expect(await screen.findByText("Cargando notificaciones…")).toBeInTheDocument();
  });

  it("shows the error state with a retry that refetches", async () => {
    listNotifications.mockRejectedValue(new Error("boom"));
    setup();

    const retry = await screen.findByRole("button", { name: "Reintentar" });
    expect(
      screen.getByText("No hemos podido cargar tus notificaciones"),
    ).toBeInTheDocument();

    // An outcome, not a call count: `retryPolicy` already retried the failure twice on its
    // own, so counting calls would pin the policy's branch table rather than this button.
    listNotifications.mockResolvedValue(page([]));
    fireEvent.click(retry);

    expect(await screen.findByText("No tienes notificaciones")).toBeInTheDocument();
  });

  it("shows the empty state on an inbox with nothing in it", async () => {
    listNotifications.mockResolvedValue(page([]));
    setup();

    expect(await screen.findByText("No tienes notificaciones")).toBeInTheDocument();
    // The "mark all" button has nothing to act on, so it is not offered.
    expect(
      screen.queryByRole("button", { name: "Marcar todas como leídas" }),
    ).not.toBeInTheDocument();
  });

  it("lists the rows and offers 'mark all as read' (R5.2)", async () => {
    listNotifications.mockResolvedValue(page([ROW]));
    markAllRead.mockResolvedValue(1);
    setup();

    expect(
      await screen.findByText("Se te ha asignado una limpieza"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Marcar todas como leídas" }));

    await waitFor(() => expect(markAllRead).toHaveBeenCalledWith("t1"));
  });

  it("acknowledges a row when it is opened (R5.1)", async () => {
    listNotifications.mockResolvedValue(page([ROW]));
    markRead.mockResolvedValue(undefined);
    setup();

    fireEvent.click(
      await screen.findByRole("button", { name: /Se te ha asignado una limpieza/ }),
    );

    await waitFor(() => expect(markRead).toHaveBeenCalledWith("t1", "n1"));
  });

  it("shows a translated error when the acknowledgement fails, never the server's text (R5.3)", async () => {
    listNotifications.mockResolvedValue(page([ROW]));
    markRead.mockRejectedValue(new Error("No such notification"));
    setup();

    fireEvent.click(
      await screen.findByRole("button", { name: /Se te ha asignado una limpieza/ }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "No hemos podido completar la acción. Inténtalo de nuevo.",
    );
    expect(alert.textContent).not.toContain("No such notification");
  });

  it("paginates, and the page controls bound at the ends", async () => {
    listNotifications.mockResolvedValue(page([ROW], 3));
    setup();

    const previous = await screen.findByRole("button", { name: "Anterior" });
    const next = screen.getByRole("button", { name: "Siguiente" });
    expect(previous).toBeDisabled();
    expect(next).toBeEnabled();
    expect(screen.getByText("Página 1 de 3")).toBeInTheDocument();

    fireEvent.click(next);
    await waitFor(() =>
      expect(listNotifications).toHaveBeenLastCalledWith("t1", {
        page: 2,
        perPage: 20,
      }),
    );
  });

  it("is governed by the shell store, so OverlayAutoCloser can close it (D9)", async () => {
    listNotifications.mockResolvedValue(page([ROW]));
    setup();
    expect(
      await screen.findByText("Se te ha asignado una limpieza"),
    ).toBeInTheDocument();

    // What `OverlayAutoCloser` does on a pathname change.
    useShellUiStore.getState().closeOverlays();

    await waitFor(() =>
      expect(
        screen.queryByText("Se te ha asignado una limpieza"),
      ).not.toBeInTheDocument(),
    );
  });

  it("keeps rendering the list when one row's type is unknown (R4.3)", async () => {
    // The half of R4.3 the section-6 and 7-9 QA reviewers both flagged: the key-resolution
    // half was covered at row scope, but "SHALL NOT romper el renderizado de la lista" is a
    // claim about the LIST — a known and an unknown row side by side, both rendered.
    listNotifications.mockResolvedValue(
      page([ROW, { ...ROW, id: "n2", type: "SOMETHING_FROM_BEFORE_THE_ENUM" }]),
    );
    setup();

    expect(
      await screen.findByText("Se te ha asignado una limpieza"),
    ).toBeInTheDocument();
    expect(screen.getByText("Aviso del sistema")).toBeInTheDocument();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("survives a type that collides with an Object prototype key (R4.3, R6.3)", async () => {
    // `related_type` and `notification_type` are free text off the wire, and a plain object
    // literal answers for its prototype: `"valueOf"` used to THROW inside this render, and
    // `"constructor"` used to return a function where a key belonged. In the field shells the
    // bell sits above the AuthGuard, so a throw here tore down the whole chrome (D16).
    listNotifications.mockResolvedValue(
      page([
        { ...ROW, id: "n1", type: "valueOf", relatedType: "valueOf", relatedId: "x1" },
        {
          ...ROW,
          id: "n2",
          type: "constructor",
          relatedType: "constructor",
          relatedId: "x2",
        },
      ]),
    );
    setup();

    expect(await screen.findAllByText("Aviso del sistema")).toHaveLength(2);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("x1");
    expect(document.body.textContent).not.toContain("x2");
  });
});
