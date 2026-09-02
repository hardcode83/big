import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
  within,
} from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { THEME_ATTRIBUTE } from "@/lib/theme/theme";
import { TopbarOverflowSheet } from "@/features/shell/components/topbar-overflow-sheet";

/**
 * The narrow layout's container for the two preference controls
 * (`shell-topbar-overflow-360`, R2.1, R2.2, R3.1, design D2).
 *
 * What matters here is not that a sheet opens — Radix does that — but that the
 * controls inside are the SAME controls: R2.2 requires «el mismo nombre
 * accesible y el mismo efecto que tiene en la barra completa», so the accessible
 * names are asserted against the exact strings the wide bar exposes, not against
 * a paraphrase.
 */

// `LocaleSwitcher` calls `router.refresh()` after writing the locale cookie
// (`public-zone-hardening` R1). This test never asserts on the refresh, so a
// no-op spy is enough to keep the import graph intact.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() }),
  usePathname: () => "/dashboard",
}));

function setup(initial: Parameters<typeof TopbarOverflowSheet>[0]["initial"] = null) {
  return render(
    <I18nProvider locale="es">
      <TopbarOverflowSheet initial={initial} />
    </I18nProvider>,
  );
}

function trigger(): HTMLElement {
  return screen.getByRole("button", { name: "Preferencias" });
}

beforeEach(() => {
  delete document.documentElement.dataset.theme;
});

describe("TopbarOverflowSheet — the trigger (R2.4, R3.1, D8)", () => {
  it("takes its accessible name from the catalog, in both locales", () => {
    // R2.4: «THE SYSTEM SHALL declararla en `frontend/locales/es/` y
    // `frontend/locales/en/`, sin texto incrustado en el componente». A
    // hardcoded Spanish label would survive an `es`-only test.
    setup();
    expect(trigger()).toBeInTheDocument();

    render(
      <I18nProvider locale="en">
        <TopbarOverflowSheet initial={null} />
      </I18nProvider>,
    );
    expect(
      screen.getByRole("button", { name: "Preferences" }),
    ).toBeInTheDocument();
  });

  it("carries `tap-target`, so the 44×44 guarantee survives (R3.1)", () => {
    // Asserted as the class because jsdom computes no layout. The measured
    // guarantee is the header block of section 6's browser test — the trigger
    // does live in the `<header>`, unlike the controls inside the sheet.
    setup();
    expect(trigger()).toHaveClass("tap-target");
  });

  it("hides its icon from the accessibility tree, so the label is the whole name", () => {
    const { container } = setup();
    for (const svg of container.querySelectorAll("svg")) {
      expect(svg).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("is type=button, so it can never submit a form it knows nothing about", () => {
    // The same latent defect `theme-switcher.test.tsx` pins: `Button` sets no
    // default `type`, and this lives in a shared `Topbar` that could end up
    // inside someone else's form.
    setup();
    expect(trigger()).toHaveAttribute("type", "button");
  });

  it("forwards `className` so the caller owns the media query (D3)", () => {
    // `TopbarPreferences` passes `sm:hidden`. The component takes no position on
    // when it applies, which is what keeps the breakpoint in one place.
    render(
      <I18nProvider locale="es">
        <TopbarOverflowSheet initial={null} className="sm:hidden" />
      </I18nProvider>,
    );
    const button = screen.getByRole("button", { name: "Preferencias" });
    expect(button).toHaveClass("sm:hidden");
    expect(button).toHaveClass("tap-target");
  });
});

describe("TopbarOverflowSheet — what is inside (R2.1, R2.2)", () => {
  it("opens the sheet and serves both preference controls from it", async () => {
    setup();
    fireEvent.click(trigger());

    const dialog = await screen.findByRole("dialog");
    // The theme control keeps its group semantics — the reason D2 chose a Sheet
    // over a DropdownMenu, whose menu pattern would have destroyed them.
    expect(
      within(dialog).getByRole("group", { name: "Tema" }),
    ).toBeInTheDocument();
    // R2.2: the SAME accessible name the wide bar exposes, verbatim.
    expect(
      within(dialog).getByRole("button", { name: "Cambiar idioma a English" }),
    ).toBeInTheDocument();
  });

  it("keeps the three theme choices with their own names and tap targets", async () => {
    // The class, not the rendered size — jsdom computes no layout. The measured
    // guarantee for these three is the sheet-interior block of section 6's
    // browser test, which opens the sheet and reads `getBoundingClientRect()`;
    // it had to open it, because `SheetContent` renders through a portal to
    // `body` and the header-scoped check never saw these controls at all.
    setup();
    fireEvent.click(trigger());
    const dialog = await screen.findByRole("dialog");

    for (const name of ["Claro", "Oscuro", "Seguir al sistema"]) {
      const button = within(dialog).getByRole("button", { name });
      expect(button).toHaveClass("tap-target");
    }
  });

  it("presses the button the server's `initial` selects (R2.2 — the same effect)", async () => {
    // The control inside must not be a decorative copy: it reflects the real
    // preference. `initial` and the attribute arrive together from the server,
    // so the test supplies both, as `app/layout.tsx` does.
    document.documentElement.setAttribute(THEME_ATTRIBUTE, "dark");
    setup("dark");
    fireEvent.click(trigger());
    const dialog = await screen.findByRole("dialog");

    expect(
      within(dialog).getByRole("button", { name: "Oscuro" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("titles the sheet from the catalog", async () => {
    setup();
    fireEvent.click(trigger());
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("Preferencias")).toBeInTheDocument();
  });

  it("labels its close button from the existing `closeMenu` key (D8)", async () => {
    // Reused rather than duplicated, as `more-menu.tsx` does.
    setup();
    fireEvent.click(trigger());
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("button", { name: "Cerrar menú" }),
    ).toBeInTheDocument();
  });
});

describe("TopbarOverflowSheet — keyboard and focus (frontend-foundation.md:28)", () => {
  it("closes on Escape and returns focus to the trigger", async () => {
    // The behaviour D2 bought by choosing a dialog primitive instead of writing
    // the focus trap, the `Escape` and the focus return by hand.
    setup();
    const button = trigger();
    button.focus();
    fireEvent.click(button);

    const dialog = await screen.findByRole("dialog");
    fireEvent.keyDown(dialog, { key: "Escape" });

    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await waitFor(() => expect(button).toHaveFocus());
  });

  it("reports its expanded state on the trigger", async () => {
    /*
     * The reference is captured once rather than re-queried, and that detail is
     * the interesting part. Radix makes the sheet a MODAL dialog, so while it is
     * open everything outside it is marked `aria-hidden` — which means
     * `getByRole("button", { name: "Preferencias" })` stops finding the trigger
     * the moment it works. The first version of this test re-queried and failed
     * with «Unable to find role="button" and name "Preferencias"», which was the
     * component behaving correctly.
     */
    setup();
    const button = trigger();
    expect(button).toHaveAttribute("aria-expanded", "false");

    fireEvent.click(button);
    await waitFor(() =>
      expect(button).toHaveAttribute("aria-expanded", "true"),
    );
  });

  it("takes the rest of the document out of the a11y tree while open (helps R4.2)", async () => {
    /*
     * Worth pinning because it is load-bearing for R4.2 — «en cualquier ancho la
     * tecnología asistiva encuentre **una sola** instancia de cada control».
     *
     * The media query is what removes the branch that does not apply, but while
     * this sheet is open its own `ThemeSwitcher` and the wide branch's are both
     * mounted. The modal's `aria-hidden` on everything outside the dialog is what
     * keeps that from ever being two instances a screen reader can reach. If the
     * sheet were made non-modal, R4.2 would break here without any media query
     * changing.
     */
    setup();
    fireEvent.click(trigger());
    await screen.findByRole("dialog");

    // The trigger is outside the dialog, so it must now be unreachable by role.
    expect(
      screen.queryByRole("button", { name: "Preferencias" }),
    ).not.toBeInTheDocument();
    // And still present in the DOM — hidden from AT, not unmounted.
    expect(
      document.querySelector('button[aria-label="Preferencias"]'),
    ).not.toBeNull();
  });

  it("mounts nothing while closed, so the controls are not duplicated (D4)", () => {
    /*
     * Radix unmounts the sheet's content on close, and D4 leans on it: with the
     * sheet shut there is exactly ONE `ThemeSwitcher` in the DOM at any width, so
     * the two instances only coexist while it is open. If Radix ever kept the
     * content mounted, the wide branch and this one would both be in the
     * accessibility tree at once and R4.2 would be broken by this component
     * rather than by the media query.
     */
    setup();
    expect(screen.queryByRole("group", { name: "Tema" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cambiar idioma a English" }),
    ).not.toBeInTheDocument();
  });

  it("has no axe violations, open or closed", async () => {
    const { container } = setup();
    expect(await getA11yViolations(container)).toEqual([]);

    fireEvent.click(trigger());
    const dialog = await screen.findByRole("dialog");
    /*
     * Scoped to the dialog, not to `baseElement`, and the reason is worth
     * recording rather than hiding behind a disabled rule.
     *
     * Scanning the whole document reports `region` («Some page content is not
     * contained by landmarks») against `div[data-radix-popper-content-wrapper]` —
     * the portal the tooltips of `ThemeSwitcher`/`LocaleSwitcher` render into.
     * That is a page-level best-practice rule about landmark structure, and this
     * is a component test that renders no landmarks at all: in the real app the
     * shell supplies them (`ShellFrame`, `Topbar`'s `<header>`), and the shell
     * tests are where landmark structure is asserted. Scanning the dialog is the
     * scope this component is actually responsible for.
     */
    expect(await getA11yViolations(dialog)).toEqual([]);
  });
});
