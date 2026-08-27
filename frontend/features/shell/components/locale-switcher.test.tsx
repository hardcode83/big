import { afterEach, describe, expect, it, vi } from "vitest";
import { useTranslation } from "react-i18next";

import {
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
} from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { LocaleSwitcher } from "@/features/shell/components/locale-switcher";

const refresh = vi.hoisted(() => vi.fn());
const router = vi.hoisted(() => ({ refresh }));

vi.mock("next/navigation", () => ({
  // Returning the SAME object on every render — a fresh `{ refresh }`
  // literal would change identity each render, putting `router` in the
  // LocaleSwitcher's useEffect deps and re-firing the effect on every
  // render until i18n settles.
  useRouter: () => router,
}));

/**
 * Rewritten 2026-08-24 when the control went from two buttons to one.
 *
 * The old tests asserted a `role="group"` named «Idioma» with a button per
 * language and `aria-pressed` on the active one. That shape is gone, and the
 * accessible semantics changed with it on purpose: two buttons were a set of
 * choices, so `aria-pressed` described which was current; one button is an
 * ACTION, so its accessible name has to say what pressing it will do.
 *
 * `sdd/specs/frontend-foundation.md:43` was checked before changing this — it
 * requires «an accessible topbar control switches ES/EN, updating i18next, the
 * cookie, and `lang`», fixing the behaviour and not the number of buttons.
 * The behaviour below is the same as before; only the surface changed.
 */

function Probe() {
  const { t } = useTranslation("navigation");
  return <span data-testid="probe">{t("routes.dashboard.title")}</span>;
}

function setup(locale: "es" | "en" = "es") {
  return render(
    <I18nProvider locale={locale}>
      <LocaleSwitcher />
      <Probe />
    </I18nProvider>,
  );
}

afterEach(() => {
  document.cookie = "autohostai.locale=; path=/; max-age=0";
  document.documentElement.lang = "";
});

describe("LocaleSwitcher (D13)", () => {
  afterEach(() => {
    refresh.mockReset();
  });
  it("names the destination, not the current locale, because pressing it acts", () => {
    // On `es`, the button switches TO English. Naming it «Español» would tell a
    // screen-reader user the opposite of what the press does.
    setup("es");
    expect(
      screen.getByRole("button", { name: "Cambiar idioma a English" }),
    ).toBeInTheDocument();
  });

  it("names the other direction when the locale is en", () => {
    setup("en");
    expect(
      screen.getByRole("button", { name: "Switch language to Español" }),
    ).toBeInTheDocument();
  });

  it("shows the ACTIVE locale as its visible text, which is what orients a sighted user", () => {
    setup("es");
    const button = screen.getByRole("button", {
      name: "Cambiar idioma a English",
    });
    expect(button).toHaveTextContent("es");
  });

  it("carries no aria-pressed, because one button is an action and not a state", () => {
    // Deliberate: `aria-pressed` on a single switch button would be pressed
    // relative to nothing. The old two-button version needed it; this must not
    // inherit it by copy-paste.
    setup("es");
    expect(
      screen.getByRole("button", { name: "Cambiar idioma a English" }),
    ).not.toHaveAttribute("aria-pressed");
  });

  it("switches language, updates document lang and the locale cookie", async () => {
    setup("es");
    fireEvent.click(
      screen.getByRole("button", { name: "Cambiar idioma a English" }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent("Dashboard"),
    );
    expect(document.documentElement.lang).toBe("en");
    expect(document.cookie).toContain("autohostai.locale=en");
  });

  it("calls router.refresh() exactly once after writing the locale cookie", async () => {
    // R1 + D1: the cookie write and the refresh must be paired in the same
    // effect, so the refresh's request carries the new cookie header. A second
    // click would be a separate user gesture, not a re-fire.
    setup("es");
    fireEvent.click(
      screen.getByRole("button", { name: "Cambiar idioma a English" }),
    );

    await waitFor(() => expect(refresh).toHaveBeenCalledTimes(1));
    expect(document.cookie).toContain("autohostai.locale=en");
  });

  it("offers a 44×44 touch area", () => {
    setup("es");
    expect(
      screen.getByRole("button", { name: "Cambiar idioma a English" }),
    ).toHaveClass("tap-target");
  });

  it("gives the button type=button, so it can never submit a form", () => {
    // Same latent hazard the theme switcher had: `Button` sets no default
    // `type`, and this control lives in a shared topbar.
    setup("es");
    expect(
      screen.getByRole("button", { name: "Cambiar idioma a English" }),
    ).toHaveAttribute("type", "button");
  });

  it("hides the icon and the code from the accessibility tree", () => {
    // The accessible name must come from `aria-label` alone. Without
    // `aria-hidden` the name would become «Cambiar idioma a English es».
    const { container } = setup("es");
    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(
      screen.getByRole("button", { name: "Cambiar idioma a English" })
        .querySelector("span[aria-hidden='true']"),
    ).not.toBeNull();
  });

  it("has no axe violations", async () => {
    const { container } = setup("es");
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
