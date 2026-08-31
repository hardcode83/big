import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen, waitFor } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

import * as dataModule from "../data";
import { notificationsKeys } from "../hooks/query-keys";
import { NotificationBell } from "./notification-bell";

const authState: { status: string; user: { tenant_id: string; id: string } | null } = {
  status: "authenticated",
  user: { tenant_id: "t1", id: "u1" },
};
vi.mock("@/lib/auth", () => ({
  useAuth: () => authState,
  getSessionGeneration: () => 1,
}));

const countUnread = vi.fn();
const listNotifications = vi.fn();
vi.spyOn(dataModule, "getNotificationsDataSource").mockImplementation(
  () =>
    ({ countUnread, listNotifications }) as unknown as ReturnType<
      typeof dataModule.getNotificationsDataSource
    >,
);

function setup(unread: number | null, locale: "es" | "en" = "es") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (unread !== null) {
    client.setQueryData(notificationsKeys.unread("t1", "u1"), unread);
  }
  countUnread.mockResolvedValue(unread ?? 0);
  listNotifications.mockResolvedValue({
    items: [], total: 0, page: 1, perPage: 20, totalPages: 0,
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <I18nProvider locale={locale}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </I18nProvider>
    );
  }
  return render(<NotificationBell profile="workspace" />, { wrapper: Wrapper });
}

beforeEach(() => {
  vi.clearAllMocks();
  authState.status = "authenticated";
  authState.user = { tenant_id: "t1", id: "u1" };
});

describe("NotificationBell (R3.2, R3.5, design D16)", () => {
  it("shows the count when there are unread ones", async () => {
    setup(3);

    await waitFor(() => expect(screen.getByText("3")).toBeInTheDocument());
  });

  it("shows no numeric badge at zero (R3.2)", async () => {
    setup(0);

    const button = await screen.findByRole("button");
    expect(button).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("announces the number to a screen reader, not only visually (R3.5)", async () => {
    setup(3);

    const button = await screen.findByRole("button");
    expect(button).toHaveAccessibleName("Notificaciones, 3 sin leer");
  });

  it("says there are none, rather than staying silent, at zero (R3.5)", async () => {
    setup(0);

    expect(await screen.findByRole("button")).toHaveAccessibleName(
      "Notificaciones, Sin notificaciones nuevas",
    );
  });

  it("translates the accessible name (R3.5, R4.1)", async () => {
    setup(2, "en");

    expect(await screen.findByRole("button")).toHaveAccessibleName(
      "Notifications, 2 unread",
    );
  });

  it("caps the badge so a big number cannot break the topbar", async () => {
    setup(150);

    await waitFor(() => expect(screen.getByText("99+")).toBeInTheDocument());
    // The cap's copy comes from the catalogue like every other visible string
    // (`steering/frontend.md`: nada hardcodeado), so it is not a literal in the JSX.
    expect(screen.queryByText("150")).not.toBeInTheDocument();
  });

  it("still announces the real number when the badge is capped (R3.5)", async () => {
    // The cap is a drawing decision. A screen reader user must hear how many there are, not
    // the abbreviation a sighted user sees.
    setup(150);

    expect(await screen.findByRole("button")).toHaveAccessibleName(
      "Notificaciones, 150 sin leer",
    );
  });

  it("renders nothing at all while the session is still resolving (D16)", () => {
    authState.status = "loading";

    const { container } = setup(null);

    expect(container).toBeEmptyDOMElement();
    expect(countUnread).not.toHaveBeenCalled();
  });

  it("renders nothing when there is no user, instead of throwing (D16)", () => {
    // The field shells put their `AuthGuard` INSIDE the shell, so the topbar renders during
    // the redirect. A throw here would tear down the whole chrome of both apps.
    authState.status = "authenticated";
    authState.user = null;

    expect(() => setup(null)).not.toThrow();
  });
});
