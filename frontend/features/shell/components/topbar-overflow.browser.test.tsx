import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { render } from "@testing-library/react";

/*
 * The compiled stylesheet, and the single line that decides whether this file
 * measures anything at all (`shell-topbar-overflow-360`, R5.2, design D6).
 *
 * `npm run test:layout` rebuilds it from `app/globals.css` with the Tailwind CLI
 * before vitest starts. Without it the shells render as unstyled markup: no
 * `display:none` on either branch of `TopbarPreferences`, no `h-14`, no flex row
 * — and an unstyled document never overflows horizontally, so every assertion
 * below would pass forever while measuring nothing. That is the exact silent
 * failure R5.2 names, which is why task 6.5 validates this guard in reverse
 * before it is trusted.
 */
import "@/test/artifacts/globals.css";

import { QueryProvider } from "@/lib/query/query-provider";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { WorkspaceShell } from "@/features/shell/components/workspace-shell";
import { CleanerShell } from "@/features/shell/components/cleaner-shell";
import { TechnicianShell } from "@/features/shell/components/technician-shell";
import { PublicShell } from "@/features/shell/components/public-shell";
import { GuestShell } from "@/features/shell/components/guest-shell";
import { MarketingNav } from "@/features/landing";
import AuthenticatedLayout from "@/app/(authenticated)/layout";

/*
 * The same mocks the jsdom shell suites use (`workspace-shell.test.tsx`,
 * `field-public-guest-shell.test.tsx`), reused verbatim on purpose: design D6
 * chose the vitest browser project over an E2E suite precisely so this harness
 * could be shared. No server, no seeded database, no login — swapping jsdom for
 * Chromium is the only difference.
 */
const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({
  usePathname: () => nav.pathname,
  useRouter: () => ({ refresh: vi.fn(), replace: vi.fn(), push: vi.fn() }),
}));
/*
 * Spread over the real module rather than replaced wholesale, which is where
 * this harness had to diverge from its jsdom twin: a real ES module linker
 * rejects an import of a name the mock does not define, and the barrel exports
 * eleven. jsdom never noticed because the shells only reach for `useAuth`.
 */
vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth")>()),
  useAuth: () => ({
    status: "authenticated",
    // A long address on purpose: the `truncate max-w-48` on the `UserMenu`
    // trigger is what keeps it from pushing the row, and `min-w-0` on the `end`
    // slot (task 4.3) is what makes that truncation effective. A short email
    // would leave both untested.
    user: {
      tenant_id: "t1",
      id: "u1",
      email: "propietaria.operaciones@autohostai.example",
      role: "MANAGER",
    },
    logout: vi.fn(),
  }),
  getSessionGeneration: () => 1,
}));
vi.mock("@/lib/auth/session-store", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/session-store")>()),
  getSessionTokens: () => ({ accessToken: "test" }),
}));
vi.mock("@/lib/config/runtime-config-provider", () => ({
  useRuntimeConfig: () => ({ apiBaseUrl: "" }),
}));
vi.mock("next/headers", () => ({
  cookies: async () => ({ get: () => undefined }),
}));
/*
 * `__esModule` is load-bearing here and is not in the jsdom twin: vite
 * pre-bundles `next/link` as CommonJS, so the default import goes through the
 * interop helper, which without this flag hands the component the whole module
 * object. React then reports «Element type is invalid … got: object» from inside
 * `NavLink`.
 */
vi.mock("next/link", () => ({
  __esModule: true,
  default: ({
    href,
    children,
    ...props
  }: {
    href: unknown;
    children: React.ReactNode;
  }) => (
    <a href={typeof href === "string" ? href : "#"} {...props}>
      {children}
    </a>
  ),
}));

type Composition = {
  /** What the failure message names, so a red run points at one screen. */
  label: string;
  pathname: string;
  mount: () => Promise<ReactElement>;
};

const content = <div>contenido</div>;

/**
 * The six compositions R1.1 enumerates, plus the landing variant of
 * `PublicShell`.
 *
 * The seventh is not scope creep: `/` is the public surface with the least room
 * (its topbar carries a `center` slot the other public routes do not), it is the
 * row design D0 predicted wrong and task 1.1 measured at 345/345 — no slack at
 * all — and R1.4 forbids this change making a composition that already fitted
 * any worse. Measuring `PublicShell` only in its roomier configuration would
 * leave exactly that regression undetected.
 */
const COMPOSITIONS: readonly Composition[] = [
  {
    label: "WorkspaceShell (/dashboard)",
    pathname: "/dashboard",
    mount: () => WorkspaceShell({ children: content }),
  },
  {
    label: "TechnicianShell (/tech)",
    pathname: "/tech",
    mount: () => TechnicianShell({ children: content }),
  },
  {
    label: "CleanerShell (/cleaner)",
    pathname: "/cleaner",
    mount: () => CleanerShell({ children: content }),
  },
  {
    label: "(authenticated) layout (/welcome)",
    pathname: "/welcome",
    mount: () => AuthenticatedLayout({ children: content }),
  },
  {
    label: "PublicShell (/login)",
    pathname: "/login",
    mount: () => PublicShell({ children: content }),
  },
  {
    label: "PublicShell with MarketingNav (/)",
    pathname: "/",
    mount: async () =>
      PublicShell({ marketingNav: await MarketingNav(), children: content }),
  },
  {
    label: "GuestShell (/guest/[token])",
    pathname: "/guest/secret-token-123",
    mount: () => GuestShell({ children: content }),
  },
];

/** Two animation frames: one for the resize to apply, one for layout to settle. */
function settle(): Promise<void> {
  return new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
  );
}

async function mountAt(composition: Composition, width: number): Promise<void> {
  nav.pathname = composition.pathname;
  await page.viewport(width, 780);
  render(
    <QueryProvider>
      <I18nProvider locale="es">{await composition.mount()}</I18nProvider>
    </QueryProvider>,
  );
  await settle();
}

/**
 * Reports whether the document overflows horizontally, as a sentence.
 *
 * A sentence rather than a bare number because R5.3 requires the failure to name
 * «la composición concreta que desborda y el ancho medido». `toBeLessThanOrEqual`
 * would print `457 <= 345`, which says neither which screen nor at what width.
 */
async function overflowVerdict(
  composition: Composition,
  width: number,
): Promise<string> {
  await mountAt(composition, width);

  const root = document.documentElement;
  const scrollWidth = root.scrollWidth;
  const clientWidth = root.clientWidth;
  const prefix = `${composition.label} @ ${width}px viewport`;

  return scrollWidth <= clientWidth
    ? `${prefix}: fits (scrollWidth ${scrollWidth} <= clientWidth ${clientWidth})`
    : `${prefix}: OVERFLOWS by ${scrollWidth - clientWidth}px (scrollWidth ${scrollWidth} > clientWidth ${clientWidth})`;
}

/** The 44px floor, in CSS pixels, from `design-system-tokens.md:31`. */
const TAP_TARGET_FLOOR = 44;

/**
 * Reports every rendered-too-small touch target in the topbar, as a sentence.
 *
 * This exists because the width check above is not sufficient for R3, and the
 * gap is not theoretical: it is how this file's first green run hid a live
 * defect. Making the row fit at 360px has two solutions and R3.2 permits only
 * one — regroup, or squeeze — and `scrollWidth <= clientWidth` reads exactly the
 * same either way. Measured here before `NotificationBell` was given
 * `tap-target`: the bell rendered 22px wide on `/tech` while all seven
 * compositions reported «fits».
 *
 * `offsetParent === null` is what filters out the branch the media query hides,
 * which is the point of measuring in a browser at all: at 360px the wide branch
 * of `TopbarPreferences` is `display:none` and its controls have no box to
 * measure. jsdom would have handed back every one of them at 0×0.
 */
/**
 * The one control exempt from the floor, named so the exemption cannot spread.
 *
 * `SheetPrimitive.Close` renders a bare 16×16 `X` (`components/ui/sheet.tsx`) on
 * all six surfaces that mount a `Sheet`, and did so before this change existed.
 * R3.1 covers «los controles que pasen al desplegable» — the theme and locale
 * controls that moved — and this is not one of them: it is the sheet's own
 * chrome, identical on the `More` menu and the notification inbox, which this
 * change never touched. Giving it a real touch target is a design-system change
 * across six surfaces, so it is recorded as a candidate for a future change,
 * which is what the proposal's «Out of scope» prescribes for a finding the
 * measurement turns up. Keyed to the slot, not to a label or a size, so a second
 * undersized control cannot inherit the exemption.
 */
const FLOOR_EXEMPT = '[data-slot="sheet-close"]';

function undersizedWithin(root: ParentNode): string[] {
  return Array.from(root.querySelectorAll("button, a, [role='button']"))
    .filter((el) => !el.matches(FLOOR_EXEMPT))
    .filter((el) => (el as HTMLElement).offsetParent !== null)
    .map((el) => {
      const { width: w, height: h } = el.getBoundingClientRect();
      return { el, w: Math.round(w), h: Math.round(h) };
    })
    .filter(({ w, h }) => w < TAP_TARGET_FLOOR || h < TAP_TARGET_FLOOR)
    .map(
      ({ el, w, h }) =>
        `«${el.getAttribute("aria-label") ?? el.textContent?.trim() ?? "?"}» ${w}×${h}`,
    );
}

function floorVerdict(scope: string, tooSmall: readonly string[]): string {
  return tooSmall.length === 0
    ? `${scope}: every touch target is at least ${TAP_TARGET_FLOOR}×${TAP_TARGET_FLOOR}`
    : `${scope}: BELOW ${TAP_TARGET_FLOOR}×${TAP_TARGET_FLOOR} — ${tooSmall.join(", ")}`;
}

async function tapTargetVerdict(
  composition: Composition,
  width: number,
): Promise<string> {
  await mountAt(composition, width);
  const header = document.querySelector("header");
  return floorVerdict(
    `${composition.label} @ ${width}px viewport`,
    header ? undersizedWithin(header) : [],
  );
}

/**
 * The same 44px floor, for the controls R3.1 sends INTO the sheet.
 *
 * R3.1 says «incluidos los controles que pasen al desplegable», and the check
 * above cannot see them for two independent reasons, either of which alone would
 * be enough: the sheet is closed, and `SheetContent` renders through a Radix
 * portal appended to `document.body` (`components/ui/sheet.tsx`), so it is never
 * inside the `<header>` that check scopes to. So this one opens the sheet and
 * scopes to the dialog.
 *
 * `topbar-overflow-sheet.test.tsx` asserts these same controls carry
 * `tap-target`. That is a different claim: a control can carry the class and
 * still be squeezed by a flex parent, which is precisely how `NotificationBell`
 * — which carried no class at all — reached 22px while every width assertion
 * reported «fits». The class test pins the intent; this pins the pixels.
 *
 * Only at the widths where the trigger exists: above `sm` it is `display:none`
 * and the controls live in the wide branch, which the header check already
 * measures.
 */
async function sheetTapTargetVerdict(
  composition: Composition,
  width: number,
): Promise<string> {
  await mountAt(composition, width);

  const trigger = document
    .querySelector("header")
    ?.querySelector<HTMLElement>(`button[aria-label="${PREFERENCES_LABEL}"]`);
  const scope = `${composition.label} @ ${width}px viewport, sheet open`;
  if (!trigger || trigger.offsetParent === null) {
    return `${scope}: no preferences sheet on this composition`;
  }

  trigger.click();
  const dialog = await waitForDialog();
  if (!dialog) return `${scope}: BELOW — the sheet never opened`;

  return floorVerdict(scope, undersizedWithin(dialog));
}

/** The accessible name of the sheet trigger, from `navigation:topbarPreferences.trigger` (es). */
const PREFERENCES_LABEL = "Preferencias";

async function waitForDialog(): Promise<Element | null> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const dialog = document.querySelector('[role="dialog"]');
    if (dialog) {
      // Radix animates the panel in; measure the settled box, not the entry frame.
      await settle();
      return document.querySelector('[role="dialog"]');
    }
    await settle();
  }
  return null;
}

beforeEach(() => {
  window.localStorage.clear();
});

describe("no shell composition overflows at 360px (R1.1, R1.2, R5.1, R5.3)", () => {
  for (const composition of COMPOSITIONS) {
    it(`${composition.label} fits in 360px`, async () => {
      // Asserting on the sentence, not on the numbers, is what makes the
      // failure readable: vitest prints the received string, which already
      // names the composition, the viewport and both measured widths (R5.3).
      // `toBeLessThanOrEqual` would print `457 <= 345` and nothing else.
      expect(await overflowVerdict(composition, 360)).toContain(": fits (");
    });
  }
});

/**
 * R1.3: the range, not the point.
 *
 * 360 is where the bug was reported and 640 is the `sm` breakpoint where the
 * full layout comes back (design D7) — the two ends. The two intermediates sit
 * either side of the ~547px that D7 predicts the full layout needs, so if that
 * prediction is wrong the narrow branch is still what renders at both and this
 * stays green; what it catches is the opposite failure, a width where neither
 * branch fits.
 *
 * 640 itself is the interesting one: it is the first width where the wide branch
 * is displayed, so it is where too low a breakpoint would show up as overflow.
 */
const RANGE_WIDTHS = [420, 520, 640] as const;

describe("no shell composition overflows between 360px and the sm breakpoint (R1.3)", () => {
  for (const composition of COMPOSITIONS) {
    for (const width of RANGE_WIDTHS) {
      it(`${composition.label} fits in ${width}px`, async () => {
        expect(await overflowVerdict(composition, width)).toContain(": fits (");
      });
    }
  }
});

/**
 * R3.1/R3.2, measured rather than asserted on class names.
 *
 * `topbar-overflow-sheet.test.tsx` already pins that the trigger CARRIES
 * `tap-target`; this pins what the browser then RENDERS, which is a different
 * claim and the one R3.1 makes («al menos 44 × 44 px»). A control can carry the
 * class and still be squeezed by a flex parent — and a control can be missing it
 * without any jsdom test noticing, which is exactly what happened.
 *
 * Every width, not just 360: R3.1 is written about the narrow layout, but the
 * wide branch that returns at 640 mounts three more controls, and they are worth
 * the same two lines.
 */
const ALL_WIDTHS = [360, ...RANGE_WIDTHS] as const;

describe("no topbar touch target renders below 44×44 (R3.1, R3.2, R3.3)", () => {
  for (const composition of COMPOSITIONS) {
    for (const width of ALL_WIDTHS) {
      it(`${composition.label} keeps its 44px floor at ${width}px`, async () => {
        expect(await tapTargetVerdict(composition, width)).toContain(
          ": every touch target is at least",
        );
      });
    }
  }
});

/**
 * R3.1's «incluidos los controles que pasen al desplegable», measured.
 *
 * Only the narrow widths: at 640 the trigger is `sm:hidden`, so there is no
 * sheet to open and the wide branch is what the header check above measures.
 * The four compositions with no sheet trigger (`/welcome` carries only the user
 * menu) report so and pass — the verdict says which case it is rather than
 * silently measuring nothing.
 */
const NARROW_WIDTHS = [360, 420, 520] as const;

describe("no touch target inside the preferences sheet renders below 44×44 (R3.1)", () => {
  for (const composition of COMPOSITIONS) {
    for (const width of NARROW_WIDTHS) {
      it(`${composition.label} keeps the floor inside the sheet at ${width}px`, async () => {
        const verdict = await sheetTapTargetVerdict(composition, width);
        expect(verdict).not.toContain("BELOW");
      });
    }
  }
});
