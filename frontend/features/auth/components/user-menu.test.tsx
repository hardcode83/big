import { afterEach, describe, expect, it, vi } from "vitest";

import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { UserMenu } from "./user-menu";

const mocks = vi.hoisted(() => ({
  mutateAsync: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
  user: { email: "user@example.com" } as
    | { email: string }
    | undefined,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: mocks.user }),
}));

vi.mock("@/features/auth/hooks/use-logout-mutation", () => ({
  useLogoutMutation: () => ({ mutateAsync: mocks.mutateAsync }),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mocks.replace, refresh: mocks.refresh }),
}));

function renderMenu(locale: "es" | "en" = "es") {
  return render(
    <I18nProvider locale={locale}>
      <UserMenu />
    </I18nProvider>,
  );
}

// Radix's DropdownMenu trigger only listens on pointerdown (not plain click),
// and userEvent v14's pointer-check trips on Radix portal leftovers across
// tests. Firing pointerdown + click through `fireEvent` opens the menu and
// sidesteps the cross-test state.
function openTrigger(button: HTMLElement) {
  fireEvent.pointerDown(button, { pointerType: "mouse", button: 0 });
  fireEvent.click(button);
}
function selectMenuItem(item: HTMLElement) {
  fireEvent.pointerDown(item, { pointerType: "mouse", button: 0 });
  fireEvent.click(item);
}

describe("UserMenu", () => {
  afterEach(() => {
    mocks.mutateAsync.mockReset();
    mocks.replace.mockReset();
    mocks.refresh.mockReset();
    mocks.user = { email: "user@example.com" };
  });

  it("renders the user's email on the trigger", () => {
    renderMenu();
    expect(
      screen.getByRole("button", { name: /Menú de usuario/ }),
    ).toHaveTextContent("user@example.com");
  });

  it("truncates a long email and still names it in the visible label", () => {
    mocks.user = {
      email: "verylongemailaddress-that-exceeds-the-cap@example.com",
    };
    renderMenu();
    const button = screen.getByRole("button", { name: /Menú de usuario/ });
    // Visible text gets an ellipsis past EMAIL_MAX; the accessible label stays
    // short so a screen-reader user hears "Menú de usuario" and then the
    // truncated address as the button text.
    expect(button.textContent).toContain("…");
  });

  it("falls back to 'Usuario' when there is no user yet", () => {
    mocks.user = undefined;
    renderMenu();
    const button = screen.getByRole("button", { name: /Menú de usuario/ });
    expect(button).toHaveTextContent("Usuario");
  });

  it("opens the dropdown and exposes 'Cerrar sesión'", async () => {
    renderMenu();
    openTrigger(screen.getByRole("button", { name: /Menú de usuario/ }));

    const item = await screen.findByRole("menuitem", {
      name: /Cerrar sesión/,
    });
    expect(item).toBeInTheDocument();
  });

  it("opens the AlertDialog when the logout menu item is selected", async () => {
    renderMenu();
    openTrigger(screen.getByRole("button", { name: /Menú de usuario/ }));
    selectMenuItem(
      await screen.findByRole("menuitem", { name: /Cerrar sesión/ }),
    );

    expect(
      await screen.findByRole("alertdialog", { name: /Cerrar sesión/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Vas a cerrar tu sesión en este dispositivo. Podrás volver a entrar cuando quieras.",
      ),
    ).toBeInTheDocument();
  });

  it("confirms: mutateAsync, replace('/'), refresh() — in that order (R3 #1)", async () => {
    mocks.mutateAsync.mockResolvedValue(undefined);
    const callOrder: string[] = [];
    mocks.mutateAsync.mockImplementation(async () => {
      callOrder.push("mutateAsync");
    });
    mocks.replace.mockImplementation((value: string) => {
      callOrder.push(`router.replace:${value}`);
    });
    mocks.refresh.mockImplementation(() => {
      callOrder.push("router.refresh");
      return undefined;
    });

    renderMenu();
    openTrigger(screen.getByRole("button", { name: /Menú de usuario/ }));
    selectMenuItem(
      await screen.findByRole("menuitem", { name: /Cerrar sesión/ }),
    );

    const confirm = await screen.findByRole("button", { name: /Cerrar sesión/ });
    fireEvent.click(confirm);

    await waitFor(() => expect(callOrder).toEqual([
      "mutateAsync",
      "router.replace:/",
      "router.refresh",
    ]));
  });

  it("still replaces + refreshes when mutateAsync() rejects (best-effort server)", async () => {
    // `use-logout-mutation.ts`'s `try/finally` already purges local state on a
    // server failure; the redirect must still happen so the user lands on the
    // landing instead of staring at a stale authenticated page.
    mocks.mutateAsync.mockRejectedValue(new Error("network"));
    renderMenu();
    openTrigger(screen.getByRole("button", { name: /Menú de usuario/ }));
    selectMenuItem(
      await screen.findByRole("menuitem", { name: /Cerrar sesión/ }),
    );

    const confirm = await screen.findByRole("button", { name: /Cerrar sesión/ });
    fireEvent.click(confirm);

    await waitFor(() => expect(mocks.replace).toHaveBeenCalledWith("/"));
    await waitFor(() => expect(mocks.refresh).toHaveBeenCalledTimes(1));
  });

  it("names the menu item in the English locale too", async () => {
    renderMenu("en");
    openTrigger(screen.getByRole("button", { name: /User menu/ }));
    expect(
      await screen.findByRole("menuitem", { name: /Sign out/ }),
    ).toBeInTheDocument();
  });
});