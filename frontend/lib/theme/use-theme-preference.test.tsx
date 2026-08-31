import { beforeEach, describe, expect, it, vi } from "vitest";
import { hydrateRoot } from "react-dom/client";
import { renderToString } from "react-dom/server";

import { act, render } from "@/test/render";
import { THEME_ATTRIBUTE } from "./theme";
import { useThemePreference, type ThemeChoice } from "./use-theme-preference";

/**
 * R4.4 in isolation: the hook is what makes any number of mounted
 * `ThemeSwitcher` instances agree, so what is worth testing is that two
 * subscribers see the same value after the attribute moves — not that one
 * component renders.
 *
 * Rendered rather than called directly because `useSyncExternalStore`'s
 * subscription only exists inside a mounted tree; a bare call would exercise
 * `choiceOf` and nothing else.
 *
 * Every mutation is wrapped in an ASYNC `act`, and that is not decoration: a
 * `MutationObserver` delivers its callback in a microtask, so a synchronous
 * `act` body returns before React has heard about the change and the assertion
 * reads the previous value. The first version of this file did exactly that and
 * five of nine cases failed.
 *
 * **What `initial` does and does not do here, learned the same way.**
 * `getServerSnapshot` runs during server rendering and hydration; a client-only
 * `render` like these calls `getSnapshot`, so `initial` is NOT what a mounted
 * instance reports — the attribute is. That is not a hole: `app/layout.tsx`
 * writes `data-theme={theme ?? undefined}` from the same `getServerTheme()` that
 * produces `initial`, so in the app the two always agree, and `initial` present
 * without its matching attribute is a state that cannot occur. These tests set
 * the attribute wherever they mean «the server said X»; the one case that makes
 * the two disagree does it on purpose, to pin which one a mounted instance
 * follows.
 *
 * `.test.tsx`, not the `.test.ts` task 2.2 named: its siblings in this directory
 * (`theme.test.ts`, `server.test.ts`) test pure functions, and this one has to
 * mount a component. The extension follows the JSX, not the neighbours.
 */

/** Probe that reports what the hook currently gives it. */
function Probe({
  initial,
  seen,
}: {
  initial: Parameters<typeof useThemePreference>[0];
  seen: ThemeChoice[];
}) {
  const choice = useThemePreference(initial);
  seen.push(choice);
  return <span data-testid="choice">{choice}</span>;
}

function current(container: HTMLElement): (string | null)[] {
  return [...container.querySelectorAll('[data-testid="choice"]')].map(
    (node) => node.textContent,
  );
}

/*
 * `beforeEach`, not `afterEach`: clearing the attribute after a test runs while
 * the tree is still mounted (Testing Library's own cleanup is a separate hook),
 * so the observer fires outside `act` and React warns. Clearing before the next
 * render mutates a document nothing is subscribed to.
 */
beforeEach(() => {
  delete document.documentElement.dataset.theme;
});

describe("useThemePreference — the server value seeds it (D9, R4.4)", () => {
  it.each([
    ["light", "light"],
    ["dark", "dark"],
  ] as const)(
    "reports the server's %s, as the server rendered it",
    (initial, expected) => {
      // Attribute AND prop, because that is the pair the server emits.
      document.documentElement.setAttribute(THEME_ATTRIBUTE, initial);
      const { container } = render(<Probe initial={initial} seen={[]} />);
      expect(current(container)).toEqual([expected]);
    },
  );

  it("reports «system» when the server sent no preference", () => {
    // No attribute and no prop: the absence IS the state (R3.6).
    const { container } = render(<Probe initial={null} seen={[]} />);
    expect(current(container)).toEqual(["system"]);
  });

  it("follows the attribute once mounted, even when `initial` disagrees", async () => {
    /*
     * The two halves of D9, pinned where they differ. `getServerSnapshot` must
     * return `initial` — reading the DOM there is what would produce a hydration
     * mismatch warning — while `getSnapshot`, which is what a MOUNTED instance
     * uses, must read the attribute: the sheet's instance is born fresh after a
     * change, and by then its `initial` prop is stale.
     *
     * The disagreement below cannot happen in the app (same cookie feeds both);
     * it is constructed so the assertion can only pass for one of the two
     * sources.
     */
    document.documentElement.setAttribute(THEME_ATTRIBUTE, "dark");
    const seen: ThemeChoice[] = [];
    await act(async () => {
      render(<Probe initial="light" seen={seen} />);
    });
    expect(seen.at(-1)).toBe("dark");
  });
});

describe("useThemePreference — every subscriber sees the same value (R4.4)", () => {
  it("gives two mounted subscribers the same value after the attribute changes", async () => {
    // This is the defect R4.4 exists to prevent, in its smallest form: two
    // instances that disagree about which button is pressed.
    const { container } = render(
      <>
        <Probe initial={null} seen={[]} />
        <Probe initial={null} seen={[]} />
      </>,
    );
    expect(current(container)).toEqual(["system", "system"]);

    await act(async () => {
      document.documentElement.setAttribute(THEME_ATTRIBUTE, "dark");
    });
    expect(current(container)).toEqual(["dark", "dark"]);

    await act(async () => {
      document.documentElement.setAttribute(THEME_ATTRIBUTE, "light");
    });
    expect(current(container)).toEqual(["light", "light"]);
  });

  it("reads «system» when the attribute is removed, which is how R3.6 is spelled", async () => {
    document.documentElement.setAttribute(THEME_ATTRIBUTE, "dark");
    const { container } = render(<Probe initial="dark" seen={[]} />);

    await act(async () => {
      delete document.documentElement.dataset.theme;
    });
    expect(current(container)).toEqual(["system"]);
  });

  it("reads «system» rather than trusting a value the CSS would not match", async () => {
    // The attribute is writable by anything on the page. An unknown value maps
    // to no CSS block, so reporting it as a choice would press no button and
    // look like a bug in the control.
    const { container } = render(<Probe initial={null} seen={[]} />);
    await act(async () => {
      document.documentElement.setAttribute(THEME_ATTRIBUTE, "solarized");
    });
    expect(current(container)).toEqual(["system"]);
  });

  it("ignores mutations of other attributes, so `lang` changes wake nobody", async () => {
    /*
     * `LocaleSwitcher` writes `document.documentElement.lang` on every language
     * change (`locale-switcher.tsx`). Without `attributeFilter` this hook would
     * re-render every switcher on the page for it — harmless but wasteful, and
     * the kind of thing that quietly stops being harmless.
     */
    const seen: ThemeChoice[] = [];
    render(<Probe initial="dark" seen={seen} />);
    const before = seen.length;

    await act(async () => {
      document.documentElement.lang = "en";
    });
    expect(seen.length).toBe(before);
  });
});

describe("useThemePreference — the server snapshot really is `initial` (D9)", () => {
  /**
   * Added after the QA panel found that nothing reached this path.
   *
   * Everything above mounts on the client, and a client mount calls
   * `getSnapshot` only — `getServerSnapshot` is invoked zero times. So every
   * assertion that *looked* like it pinned «`initial` drives the first paint»
   * was in fact watching `getSnapshot` read the attribute the test had just
   * set, and `useThemePreference(initial)` could have been written
   * `useThemePreference(null)` with all of them still green. That regression is
   * not cosmetic: on a real server render the snapshot would seed «system»
   * instead of the visitor's theme, and the control would correct itself a tick
   * after hydration — the exact flash D9 and `design-system-tokens.md:23` exist
   * to prevent.
   *
   * `renderToString` is what actually calls `getServerSnapshot`, so it is the
   * only way to assert the contract rather than assume it.
   */

  it("renders the server's `initial` on the server, ignoring the DOM entirely", () => {
    // The attribute says the opposite of the prop, so only one of the two
    // sources can produce a passing assertion. On the server the DOM is not a
    // source at all.
    document.documentElement.setAttribute(THEME_ATTRIBUTE, "light");
    expect(renderToString(<Probe initial="dark" seen={[]} />)).toContain("dark");
  });

  it("renders «system» on the server when the visitor has no preference", () => {
    expect(renderToString(<Probe initial={null} seen={[]} />)).toContain(
      "system",
    );
  });

  it("hydrates without a mismatch, which is what pairs the two snapshots", async () => {
    /*
     * The other half of the contract. `initial` and the attribute always come
     * from the same cookie in the app (`app/layout.tsx` writes
     * `data-theme={theme ?? undefined}` from the same `getServerTheme()` that
     * feeds `initial`), so hydration must be silent. React reports a mismatch
     * through `console.error`, which is why that is what is being watched.
     */
    const host = document.createElement("div");
    host.innerHTML = renderToString(<Probe initial="dark" seen={[]} />);
    document.body.appendChild(host);
    document.documentElement.setAttribute(THEME_ATTRIBUTE, "dark");

    const errors: unknown[][] = [];
    const spy = vi
      .spyOn(console, "error")
      .mockImplementation((...args: unknown[]) => {
        errors.push(args);
      });

    let root: ReturnType<typeof hydrateRoot> | undefined;
    try {
      await act(async () => {
        root = hydrateRoot(host, <Probe initial="dark" seen={[]} />);
      });
      expect(errors).toEqual([]);
      expect(host.querySelector('[data-testid="choice"]')?.textContent).toBe(
        "dark",
      );
    } finally {
      await act(async () => {
        root?.unmount();
      });
      spy.mockRestore();
      host.remove();
    }
  });
});

describe("useThemePreference — it lets go on unmount (D9)", () => {
  it("stops observing when the last subscriber unmounts", async () => {
    const seen: ThemeChoice[] = [];
    const { unmount } = render(<Probe initial={null} seen={seen} />);

    unmount();
    const after = seen.length;

    await act(async () => {
      document.documentElement.setAttribute(THEME_ATTRIBUTE, "dark");
    });
    // A leaked observer would keep calling `onStoreChange` on a torn-down tree.
    // React would warn rather than throw, so the render count is what proves it.
    expect(seen.length).toBe(after);
  });
});
