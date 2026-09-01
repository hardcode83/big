import { beforeEach, describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import {
  act,
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
  within,
} from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { THEME_COOKIE } from "@/lib/config/constants";
import { THEME_ATTRIBUTE } from "@/lib/theme/theme";
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
  /*
   * The attribute goes on alongside the prop because that is the pair the server
   * emits: `app/layout.tsx` writes `data-theme={theme ?? undefined}` from the
   * same `getServerTheme()` that produces `initial`. Since
   * `shell-topbar-overflow-360` (D9/R4.4) `aria-pressed` is read from the
   * attribute so that two mounted instances cannot disagree, so a test that set
   * only the prop would be asserting against a state the app never renders.
   */
  if (initial !== null) {
    document.documentElement.setAttribute(THEME_ATTRIBUTE, initial);
  }
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

/*
 * `beforeEach` for the attribute, not `afterEach`: since D9 the switcher
 * subscribes to it, and clearing it after a test runs while the tree is still
 * mounted (Testing Library's cleanup is a separate hook), so the observer fires
 * outside `act` and React warns. Clearing it before the next render mutates a
 * document nothing is subscribed to. The cookie has no observer, so it can be
 * cleared on either side; both are done here to keep the pair in one place.
 */
beforeEach(() => {
  document.cookie = `${THEME_COOKIE}=; path=/; max-age=0`;
  delete document.documentElement.dataset.theme;
});

/*
 * Why the third label is a verb phrase while the other two are adjectives.
 *
 * «Sistema» read as a third colour, indistinguishable from «Oscuro» to anyone
 * whose OS is already dark — reported from the browser on 2026-08-24. The button
 * does not choose an appearance, it CEDES the choice back to
 * `prefers-color-scheme`, and «Seguir al sistema» says that where a noun could
 * not. The asymmetry with «Claro»/«Oscuro» is the point, not an oversight.
 */
describe("ThemeSwitcher — the accessible group (R3.5, design D5)", () => {
  it("is a labelled group with the three choices", () => {
    setup(null);
    expect(screen.getByRole("group", { name: "Tema" })).toBeInTheDocument();
    for (const name of ["Claro", "Oscuro", "Seguir al sistema"]) {
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
    for (const name of ["Light", "Dark", "Follow the system"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("gives every button a 44×44 touch area", () => {
    // `Button size="sm"` is `h-9` (36px), below the requirement, so the
    // `tap-target` utility is what satisfies R3.5. Asserted as the class because
    // jsdom computes no layout.
    setup(null);
    for (const name of ["Claro", "Oscuro", "Seguir al sistema"]) {
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
    for (const name of ["Claro", "Oscuro", "Seguir al sistema"]) {
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
      "Seguir al sistema",
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
    "presses %s from the server-rendered state on mount",
    (initial, label) => {
      /*
       * Not from reading the cookie on mount: the colours would be right either
       * way (the server put the attribute in the HTML) but the pressed button
       * would flip a tick after hydration.
       *
       * Precise about what this pins, since D9: `setup` supplies the prop AND
       * the attribute, as the server does, and a MOUNTED instance reads the
       * attribute — so this case cannot tell the two apart. That the `initial`
       * prop is really the server snapshot is pinned by the `renderToString`
       * block above, which is the only place `getServerSnapshot` runs.
       */
      setup(initial);
      expect(screen.getByRole("button", { name: label })).toHaveAttribute(
        "aria-pressed",
        "true",
      );
    },
  );

  it("presses «Sistema» when no preference is persisted", () => {
    setup(null);
    expect(screen.getByRole("button", { name: "Seguir al sistema" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("presses exactly one button at a time", () => {
    setup("dark");
    const pressed = ["Claro", "Oscuro", "Seguir al sistema"].filter(
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
    fireEvent.click(screen.getByRole("button", { name: "Seguir al sistema" }));
    return waitFor(() => {
      expect(screen.getByRole("button", { name: "Seguir al sistema" })).toHaveAttribute(
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

describe("ThemeSwitcher — the server render presses the server's button (D9)", () => {
  /**
   * Added after the QA panel found this unreachable by any test.
   *
   * Every other case in this file mounts on the client, and a client mount never
   * calls the hook's `getServerSnapshot` — so since D9 they all pass by reading
   * the `data-theme` attribute, and `useThemePreference(initial)` could have been
   * written `useThemePreference(null)` with the whole file still green. On a real
   * server render that regression would seed «system» for a visitor whose cookie
   * says otherwise, and the pressed button would jump one tick after hydration:
   * the flash `design-system-tokens.md` resolves the theme on the server to
   * avoid, reintroduced in the control rather than in the colours.
   *
   * `renderToString` is what calls `getServerSnapshot`, so it is what can tell a
   * correct wiring from a dropped prop.
   */

  /** `aria-pressed` per accessible name, parsed out of server-rendered HTML. */
  function pressedInHtml(html: string): string[] {
    const host = document.createElement("div");
    host.innerHTML = html;
    return [...host.querySelectorAll("button")]
      .filter((button) => button.getAttribute("aria-pressed") === "true")
      .map((button) => button.getAttribute("aria-label") ?? "");
  }

  it.each([
    ["light", "Claro"],
    ["dark", "Oscuro"],
  ] as const)(
    "presses %s from the `initial` prop with no DOM to read",
    (initial, label) => {
      // The attribute is deliberately set to disagree: on the server it is not a
      // source, so only the prop can make this pass.
      document.documentElement.setAttribute(
        THEME_ATTRIBUTE,
        initial === "dark" ? "light" : "dark",
      );
      const html = renderToString(
        <I18nProvider locale="es">
          <ThemeSwitcher initial={initial} />
        </I18nProvider>,
      );
      expect(pressedInHtml(html)).toEqual([label]);
    },
  );

  it("presses «Sistema» when the visitor has no persisted preference", () => {
    const html = renderToString(
      <I18nProvider locale="es">
        <ThemeSwitcher initial={null} />
      </I18nProvider>,
    );
    expect(pressedInHtml(html)).toEqual(["Seguir al sistema"]);
  });
});

describe("ThemeSwitcher — two mounted instances agree (R4.4, D9)", () => {
  /**
   * The requirement `shell-topbar-overflow-360` added, tested where it lives.
   *
   * R4.4: «después de un cambio de preferencia hecho en cualquiera de ellas, la
   * otra SHALL reflejar la preferencia nueva sin requerir navegación ni recarga».
   * The narrow layout mounts this control twice — the wide topbar branch and the
   * overflow sheet — and before D9 each held its own `useState`, so the one that
   * did not receive the click kept showing the button the server had rendered.
   */
  function setupPair(initial: Parameters<typeof ThemeSwitcher>[0]["initial"]) {
    if (initial !== null) {
      document.documentElement.setAttribute(THEME_ATTRIBUTE, initial);
    }
    return render(
      <I18nProvider locale="es">
        <div data-testid="wide">
          <ThemeSwitcher initial={initial} />
        </div>
        <div data-testid="sheet">
          <ThemeSwitcher initial={initial} />
        </div>
      </I18nProvider>,
    );
  }

  /** `aria-pressed` of the named button, per branch. */
  function pressedIn(branch: string, name: string): string | null {
    return within(screen.getByTestId(branch))
      .getByRole("button", { name })
      .getAttribute("aria-pressed");
  }

  it("moves aria-pressed in BOTH instances when one of them is clicked", async () => {
    setupPair(null);
    expect(pressedIn("wide", "Seguir al sistema")).toBe("true");
    expect(pressedIn("sheet", "Seguir al sistema")).toBe("true");

    // The click happens in the sheet — the instance the user can reach at 360px.
    fireEvent.click(
      within(screen.getByTestId("sheet")).getByRole("button", {
        name: "Oscuro",
      }),
    );

    await waitFor(() => {
      expect(pressedIn("sheet", "Oscuro")).toBe("true");
      // This is the assertion that failed before D9: the wide branch never saw
      // the click and had no reason to re-render.
      expect(pressedIn("wide", "Oscuro")).toBe("true");
    });
    expect(pressedIn("wide", "Seguir al sistema")).toBe("false");
  });

  it("agrees on «system» too, where the state is the ABSENCE of the attribute", async () => {
    // The delete branch of the effect, which is the half that is easy to get
    // wrong: an instance reading a cached value rather than the attribute would
    // keep showing «Oscuro» because nothing told it the attribute went away.
    setupPair("dark");
    expect(pressedIn("wide", "Oscuro")).toBe("true");

    fireEvent.click(
      within(screen.getByTestId("sheet")).getByRole("button", {
        name: "Seguir al sistema",
      }),
    );

    await waitFor(() => {
      expect(pressedIn("wide", "Seguir al sistema")).toBe("true");
      expect(pressedIn("sheet", "Seguir al sistema")).toBe("true");
    });
    expect(pressedIn("wide", "Oscuro")).toBe("false");
  });

  it("keeps exactly one button pressed per instance", async () => {
    setupPair(null);
    fireEvent.click(
      within(screen.getByTestId("wide")).getByRole("button", { name: "Claro" }),
    );

    const names = ["Claro", "Oscuro", "Seguir al sistema"];
    await waitFor(() => {
      for (const branch of ["wide", "sheet"]) {
        expect(
          names.filter((name) => pressedIn(branch, name) === "true"),
        ).toEqual(["Claro"]);
      }
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

    fireEvent.click(screen.getByRole("button", { name: "Seguir al sistema" }));
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
      fireEvent.click(screen.getByRole("button", { name: "Seguir al sistema" }));
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
    fireEvent.click(screen.getByRole("button", { name: "Seguir al sistema" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Seguir al sistema" })).toHaveAttribute(
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
    // `setup` puts the attribute there, as the server does. What this pins is
    // that mounting neither wrote the cookie nor moved the attribute — since D9
    // the component reads that attribute, so «untouched» is now «still exactly
    // the server's value» rather than «absent».
    expect(attribute()).toBe("dark");
  });

  it("re-selecting a value this instance already requested still writes it", async () => {
    /*
     * The defect that decoupling `aria-pressed` from `requested` introduced, and
     * the reason `requested` is an object rather than a bare `Choice` (D9).
     *
     * Reachable with the two instances section 4 mounts: pick «dark» in one,
     * pick «light» in the other, pick «dark» in the first again. With the bare
     * value, that third click found `requested` already `"dark"`, changed no
     * state, ran no effect — and left the document on «light» after a click that
     * said «dark». Simulated here with one instance plus an outside write, which
     * is exactly what the other instance is from this one's point of view.
     */
    setup(null);
    const dark = screen.getByRole("button", { name: "Oscuro" });

    fireEvent.click(dark);
    await waitFor(() => expect(attribute()).toBe("dark"));

    // The other instance's click, as this one experiences it.
    await act(async () => {
      document.documentElement.setAttribute(THEME_ATTRIBUTE, "light");
    });
    expect(screen.getByRole("button", { name: "Claro" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(dark);
    await waitFor(() => expect(attribute()).toBe("dark"));
    expect(cookieValue()).toBe("dark");
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
