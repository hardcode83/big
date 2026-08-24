import { afterEach, describe, expect, it } from "vitest";

import {
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
} from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { THEME_COOKIE } from "@/lib/config/constants";
import { ThemeSwitcher } from "@/features/shell/components/theme-switcher";

/**
 * The real verification of the switcher (task 6.3).
 *
 * There is no visual pass available for it here and that is a property of the
 * environment, not a choice: in a linked worktree the app does not hydrate under
 * `PORT_OFFSET` (`sdd/project.md` — the page is served but the form submits
 * natively and no React props appear), so the browser could not exercise this
 * component even if it were open. Changing `next.config` to make it hydrate would
 * be editing the app in order to look at it, so these assertions are the
 * verification rather than a stand-in for one.
 */

function setup(initial: Parameters<typeof ThemeSwitcher>[0]["initial"]) {
  return render(
    <I18nProvider locale="es">
      <ThemeSwitcher initial={initial} />
    </I18nProvider>,
  );
}

/** What the document currently carries, as the CSS would see it. */
function attribute(): string | undefined {
  return document.documentElement.dataset.theme;
}

function cookieValue(): string | undefined {
  const match = document.cookie.match(
    new RegExp(`${THEME_COOKIE.replace(".", "\\.")}=([^;]*)`),
  );
  return match?.[1];
}

afterEach(() => {
  document.cookie = `${THEME_COOKIE}=; path=/; max-age=0`;
  delete document.documentElement.dataset.theme;
});

describe("ThemeSwitcher — the accessible group (R3.5, design D5)", () => {
  it("is a labelled group with the three choices", () => {
    setup(null);
    expect(screen.getByRole("group", { name: "Tema" })).toBeInTheDocument();
    for (const name of ["Claro", "Oscuro", "Sistema"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("takes every label from the catalog, with nothing hardcoded", () => {
    // Rendering under `en` must change all four strings. A hardcoded Spanish
    // label would survive this and nothing else would notice.
    render(
      <I18nProvider locale="en">
        <ThemeSwitcher initial={null} />
      </I18nProvider>,
    );
    expect(screen.getByRole("group", { name: "Theme" })).toBeInTheDocument();
    for (const name of ["Light", "Dark", "System"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("gives every button a 44×44 touch area", () => {
    // `Button size="sm"` is `h-9` (36px), below the requirement, so the
    // `tap-target` utility is what satisfies R3.5. Asserted as the class because
    // jsdom computes no layout.
    setup(null);
    for (const name of ["Claro", "Oscuro", "Sistema"]) {
      expect(screen.getByRole("button", { name })).toHaveClass("tap-target");
    }
  });

  it("gives every button type=button, so it can never submit a form", () => {
    /*
     * `Button` sets no default `type`, so a bare `<button>` is `type="submit"`.
     * The switcher lives in a shared `Topbar`, so it can end up inside a form it
     * knows nothing about — and then every click would submit that form and
     * reload the page, which is exactly what R3.4 forbids («sin recargar la
     * página»).
     *
     * No form wraps it today, so this is latent rather than broken. It is pinned
     * because removing the attribute passed all sixteen other tests in this file:
     * the defect would ship silently and only surface when someone else's change
     * put a form around the topbar.
     */
    setup(null);
    for (const name of ["Claro", "Oscuro", "Sistema"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute(
        "type",
        "button",
      );
    }
  });

  it("orders the buttons Claro, Oscuro, Sistema", () => {
    // Not required by any criterion, but the order is a deliberate constant and
    // a silent reshuffle would move the control under the user's finger. Read
    // from `aria-label` rather than text content: the buttons are icon-only now,
    // so their text content is empty and their name lives in the label.
    setup(null);
    const buttons = screen
      .getByRole("group", { name: "Tema" })
      .querySelectorAll("button");
    expect([...buttons].map((button) => button.getAttribute("aria-label"))).toEqual([
      "Claro",
      "Oscuro",
      "Sistema",
    ]);
  });

  it("hides the icon from the accessibility tree so the label is the whole name", () => {
    // Icon-only buttons take their accessible name from `aria-label`. A visible
    // `<svg>` without `aria-hidden` can leak into the computed name in some
    // engines, which is how an icon button ends up announced twice.
    const { container } = setup(null);
    for (const svg of container.querySelectorAll("svg")) {
      expect(svg).toHaveAttribute("aria-hidden", "true");
    }
  });

  it("has no axe violations", async () => {
    const { container } = setup(null);
    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("ThemeSwitcher — aria-pressed tracks the PREFERENCE (R3.5, D5)", () => {
  it.each([
    ["light", "Claro"],
    ["dark", "Oscuro"],
  ] as const)(
    "presses %s from the server-provided value on the first paint",
    (initial, label) => {
      // From a prop, not from reading the cookie on mount: the colours would be
      // right either way (the server put the attribute in the HTML) but the
      // pressed button would flip a tick after hydration.
      setup(initial);
      expect(screen.getByRole("button", { name: label })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    },
  );

  it("presses «Sistema» when no preference is persisted", () => {
    setup(null);
    expect(screen.getByRole("button", { name: "Sistema" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("presses exactly one button at a time", () => {
    setup("dark");
    const pressed = ["Claro", "Oscuro", "Sistema"].filter(
      (name) =>
        screen.getByRole("button", { name }).getAttribute("aria-pressed") ===
        "true",
    );
    expect(pressed).toEqual(["Oscuro"]);
  });

  it("tracks the chosen preference, NOT the resolved theme", () => {
    /*
     * The distinction D5 insists on. With «Sistema» chosen on a dark OS the page
     * is dark, but the pressed button is «Sistema» — pressing «Oscuro» instead
     * would tell the user they had made a choice they never made, and leave no
     * way to see that they are following the system.
     */
    setup("dark");
    fireEvent.click(screen.getByRole("button", { name: "Sistema" }));
    return waitFor(() => {
      expect(screen.getByRole("button", { name: "Sistema" })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
      expect(screen.getByRole("button", { name: "Oscuro" })).toHaveAttribute(
        "aria-pressed",
        "false",
      );
    });
  });
});

describe("ThemeSwitcher — the three selections (R3.4, R3.6)", () => {
  it.each([
    ["Oscuro", "dark"],
    ["Claro", "light"],
  ] as const)(
    "writing %s sets the cookie and the attribute together",
    async (label, value) => {
      setup(null);
      fireEvent.click(screen.getByRole("button", { name: label }));
      await waitFor(() => {
        expect(cookieValue()).toBe(value);
        expect(attribute()).toBe(value);
      });
    },
  );

  it("choosing «Sistema» clears the cookie AND removes the attribute", async () => {
    /*
     * R3.6. Both halves matter and they are easy to half-do: leaving the
     * attribute behind pins the old theme on this page, and leaving the cookie
     * behind pins it on the next navigation. Either one alone looks like it
     * worked.
     */
    setup("dark");
    fireEvent.click(screen.getByRole("button", { name: "Oscuro" }));
    await waitFor(() => expect(cookieValue()).toBe("dark"));

    fireEvent.click(screen.getByRole("button", { name: "Sistema" }));
    await waitFor(() => {
      expect(cookieValue()).toBeUndefined();
      expect(attribute()).toBeUndefined();
    });
  });

  it("writes the cookie with the posture R3.1 requires", async () => {
    /*
     * This section is the first to WRITE the cookie — sections 1-5 only read it —
     * so `path=/`, `samesite=lax` and the one-year `max-age` are satisfied or
     * violated here and nowhere else.
     *
     * jsdom's `document.cookie` does not expose attributes on read, so the
     * written string is asserted at its source instead. Weaker than reading them
     * back, and the strongest available in this environment.
     */
    const written: string[] = [];
    const original = Object.getOwnPropertyDescriptor(
      Document.prototype,
      "cookie",
    );
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => "",
      set: (value: string) => written.push(value),
    });

    try {
      setup(null);
      fireEvent.click(screen.getByRole("button", { name: "Oscuro" }));
      await waitFor(() => expect(written.length).toBeGreaterThan(0));

      const [set] = written;
      expect(set).toContain(`${THEME_COOKIE}=dark`);
      expect(set).toContain("path=/");
      expect(set).toContain("samesite=lax");
      expect(set).toContain("max-age=31536000");
      // Non-sensitive by construction: the value is one of two literal words.
      expect(set).not.toMatch(/httponly|secure/i);

      written.length = 0;
      fireEvent.click(screen.getByRole("button", { name: "Sistema" }));
      await waitFor(() => expect(written.length).toBeGreaterThan(0));
      // Expiry, not a `system` value: the absence of the cookie is the state.
      expect(written[0]).toContain("max-age=0");
      expect(written[0]).not.toContain("system");
    } finally {
      Object.defineProperty(document, "cookie", original!);
    }
  });

  it("never persists «system» as a cookie value", async () => {
    setup(null);
    fireEvent.click(screen.getByRole("button", { name: "Sistema" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sistema" })).toHaveAttribute(
        "aria-pressed",
        "true",
      ),
    );
    // D4: «Tres estados, sin valor "system" persistido: la ausencia *es* el
    // estado.» A persisted "system" would match no CSS block.
    expect(document.cookie).not.toContain("system");
    expect(cookieValue()).toBeUndefined();
  });

  it("does not touch the document before the user chooses anything", () => {
    /*
     * The `requested === null` guard from `LocaleSwitcher`. Without it the effect
     * would write the server-provided value back on mount — harmless-looking, but
     * it would resurrect a cookie the user had just cleared, and it would mutate
     * during the first commit rather than in response to an interaction (R3.4).
     */
    setup("dark");
    expect(document.cookie).toBe("");
    expect(attribute()).toBeUndefined();
  });

  it("applies the change without reloading the page", () => {
    // R3.4: «sin recargar la página». The component owns no navigation — asserted
    // structurally, since jsdom would not reload anyway and a `location.assign`
    // here would pass any behavioural test.
    const source = ThemeSwitcher.toString();
    expect(source).not.toMatch(/location\s*\.\s*(assign|replace|reload|href)/);
    expect(source).not.toMatch(/window\s*\.\s*location/);
  });
});
