import { describe, expect, it, vi } from "vitest";
import { page } from "vitest/browser";
import { render } from "@testing-library/react";

/*
 * The compiled stylesheet, and the single line that decides whether this file
 * measures anything at all (task 6.3, R4.4).
 *
 * `npm run test:layout` rebuilds it from `app/globals.css` with the Tailwind CLI
 * before vitest starts. Without it the forms render as unstyled markup: no
 * `tap-target` min-height, no `overflow-y-auto` on the sheet panel, no `h-full`,
 * no flex column — and an unstyled document never overflows horizontally, so
 * every assertion below would pass forever while measuring nothing. That is the
 * silent failure `topbar-overflow.browser.test.tsx` names, and the reason this
 * file is a sibling of that one rather than another jsdom suite.
 */
import "@/test/artifacts/globals.css";

import { I18nProvider } from "@/lib/i18n/client-provider";

/*
 * Every data hook is mocked, so this file needs no server, no react-query
 * provider and no seeded database — the same harness-sharing design D6 chose for
 * the shell suite, applied to this feature's three overlays.
 *
 * The module mocks spread over the real module rather than replacing it:
 * `topbar-overflow.browser.test.tsx` records why, and it is not optional here
 * either — a real ES module linker rejects an import of a name the mock does not
 * define, and `use-dashboard-data.ts` exports four names of which this file
 * overrides two.
 */
const useHasPermissionMock = vi.hoisted(() => vi.fn(() => true));
vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth")>()),
  useHasPermission: useHasPermissionMock,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/properties",
}));

const LIST_ROW = {
  id: "property-1",
  name: "Redes 11",
  internalCode: "REDES11",
  pmsProvider: "BEDS24",
  pmsExternalId: "ext-9999",
  addressLine1: "Calle Redes 11",
  addressLine2: "3ºB",
  city: "Madrid",
  province: "ZZ-PROVINCE",
  postalCode: "28051",
  country: "ES",
  timezone: "Europe/Madrid",
  maxGuests: 4,
  bedrooms: 2,
  bathrooms: 1,
  currentOperationalState: "AWAITING_CLEANING",
  defaultCheckInTime: "16:00:00",
  defaultCheckOutTime: "11:00:00",
  wifiName: "REDES11-WIFI",
  hasWifiPassword: true,
  status: "ACTIVE" as const,
  createdAt: "1999-01-02T03:04:05Z",
  updatedAt: "1999-06-07T08:09:10Z",
};

/*
 * Long, realistic values on purpose. A form seeded with `""` everywhere cannot
 * overflow: the widest thing in the panel would be the labels. These are the
 * lengths the backend actually accepts (`lib/field-limits.ts`), which is what
 * decides whether an input is allowed to push its own row.
 */
const DETAIL = {
  ...LIST_ROW,
  name: "Apartamento Redes 11 — Ático exterior con terraza",
  addressLine1: "Calle de las Redes de Pescadores Número 11, Escalera 2",
  accessNotes:
    "El portal está a la derecha del bar; el portero automático no funciona.",
  cleaningNotes: "Sábanas de repuesto en el armario del pasillo, balda alta.",
  emergencyNotes: null,
};

vi.mock("@/features/properties/hooks/use-properties", () => ({
  useProperties: () => ({
    isPending: false,
    isError: false,
    error: null,
    data: {
      data: [LIST_ROW],
      page: 1,
      perPage: 20,
      total: 1,
      totalPages: 1,
    },
  }),
}));
vi.mock("@/features/properties/hooks/use-property", () => ({
  useProperty: () => ({ isPending: false, isError: false, data: DETAIL }),
}));

const idleMutation = {
  mutate: vi.fn(),
  isPending: false,
  isError: false,
  isSuccess: false,
  error: null,
};
vi.mock("@/features/properties/hooks/use-create-property", () => ({
  useCreateProperty: () => idleMutation,
}));
vi.mock("@/features/properties/hooks/use-update-property", () => ({
  useUpdateProperty: () => idleMutation,
}));

vi.mock("@/features/dashboard/hooks/use-dashboard-data", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/features/dashboard/hooks/use-dashboard-data")
  >()),
  usePropertyDetail: () => ({
    isPending: false,
    isError: false,
    data: {
      propertyId: "property-1",
      propertyCode: "REDES11",
      operationalState: "AWAITING_CLEANING",
      currentOrNextReservation: null,
      guest: null,
      access: null,
      cleaningStatus: null,
      lastCleaningPhotos: [],
      openIncidents: [],
      financial: null,
      notes: null,
      pendingApprovals: [],
    },
  }),
  usePropertyTimeline: () => ({
    isPending: false,
    isError: false,
    data: { data: [], total: 0, page: 1, per_page: 0, total_pages: 0 },
  }),
}));

import { PropertiesView } from "@/features/properties";
import { PropertyDetailView } from "@/features/dashboard/components/detail/property-detail-view";
import esDashboard from "@/locales/es/dashboard.json";
import esProperties from "@/locales/es/properties.json";

/** Two animation frames: one for the resize to apply, one for layout to settle. */
function settle(): Promise<void> {
  return new Promise((resolve) =>
    requestAnimationFrame(() => requestAnimationFrame(() => resolve())),
  );
}

type Surface = {
  /** What a failure message names, so a red run points at one overlay. */
  label: string;
  /** The `role` the opened panel exposes — `Sheet` is a dialog, `AlertDialog` is not. */
  role: "dialog" | "alertdialog";
  mount: () => React.ReactElement;
  /** The accessible name of the control that opens it. */
  trigger: string;
};

/**
 * The three overlays this change adds, mounted through their real hosts rather
 * than in isolation.
 *
 * Through the hosts because the `overflow-y-auto` that makes a twenty-field form
 * reachable lives on the CALL SITE's `SheetContent`, not inside the primitive:
 * a harness that mounted `<SheetContent>` itself with hand-written props would
 * be measuring the props this file chose, not the ones the app passes.
 */
const SURFACES: readonly Surface[] = [
  {
    label: "create Sheet (PropertiesView)",
    role: "dialog",
    mount: () => <PropertiesView />,
    trigger: esProperties.newProperty,
  },
  {
    label: "edit Sheet (PropertyDetailView)",
    role: "dialog",
    mount: () => <PropertyDetailView propertyId="property-1" />,
    trigger: esDashboard.detail.edit.button,
  },
  {
    label: "retire AlertDialog (PropertyDetailView)",
    role: "alertdialog",
    mount: () => <PropertyDetailView propertyId="property-1" />,
    trigger: esDashboard.detail.retire.button,
  },
];

/**
 * The project's minimum supported width.
 *
 * `steering/frontend.md`'s «Responsive verificable» names no number; the one the
 * tree actually fixes is 360, set by `shell-topbar-overflow-360` and recorded in
 * `vitest.config.ts` as «the 360px overflow guard of R5». Reused verbatim rather
 * than picking a second minimum, which would make the two guards disagree about
 * what «mobile-first» means here.
 */
const MIN_WIDTH = 360;

/**
 * 640 is Tailwind's `sm`, where `PropertiesView` swaps its stacked cards for the
 * table and `SheetContent` stops being full-bleed. Both ends are measured because
 * the wide branch is a different layout, not a wider copy of the narrow one.
 */
const WIDTHS = [MIN_WIDTH, 640] as const;

/** The 44px floor, in CSS pixels (`steering/frontend.md`, «Interaction targets»). */
const TAP_TARGET_FLOOR = 44;

/**
 * The one control exempt from the floor, named so the exemption cannot spread.
 *
 * `SheetPrimitive.Close` renders a bare 16×16 `X` (`components/ui/sheet.tsx`) on
 * every surface that mounts a `Sheet` and did so long before this change:
 * `topbar-overflow.browser.test.tsx` measured it, decided it is the sheet's own
 * chrome rather than a control this change introduced, and recorded giving it a
 * real touch target as a candidate for a future change instead of restyling six
 * surfaces. This file inherits that decision verbatim rather than re-opening it,
 * and keys it to the slot so a second undersized control cannot inherit it.
 */
const FLOOR_EXEMPT = '[data-slot="sheet-close"]';

async function openSurface(surface: Surface, width: number): Promise<HTMLElement> {
  await page.viewport(width, 780);
  render(<I18nProvider locale="es">{surface.mount()}</I18nProvider>);
  await settle();

  const trigger = Array.from(
    document.querySelectorAll<HTMLButtonElement>("button"),
  ).find((button) => button.textContent?.trim() === surface.trigger);
  if (!trigger) {
    throw new Error(`no «${surface.trigger}» trigger on ${surface.label}`);
  }
  trigger.click();

  for (let attempt = 0; attempt < 40; attempt += 1) {
    const panel = document.querySelector<HTMLElement>(`[role="${surface.role}"]`);
    if (panel) {
      // Radix animates the panel in; measure the settled box, not the entry frame.
      await settle();
      return document.querySelector<HTMLElement>(`[role="${surface.role}"]`)!;
    }
    await settle();
  }
  throw new Error(`${surface.label} never opened at ${width}px`);
}

/**
 * Reports whether anything overflows horizontally, as a sentence.
 *
 * A sentence rather than a bare comparison because a red run has to say WHICH
 * overlay and at what width: `toBeLessThanOrEqual` would print `457 <= 360` and
 * name neither. Same convention as `topbar-overflow.browser.test.tsx`.
 *
 * Both the document and the panel are measured. The document alone is not
 * enough: `SheetContent` is `fixed` and clips its own children, so a field wider
 * than the panel is invisible to `documentElement.scrollWidth` while being
 * exactly the clipping R4.4 forbids.
 */
function horizontalVerdict(
  scope: string,
  panel: HTMLElement,
): string {
  const root = document.documentElement;
  if (root.scrollWidth > root.clientWidth) {
    return `${scope}: the DOCUMENT OVERFLOWS by ${root.scrollWidth - root.clientWidth}px (scrollWidth ${root.scrollWidth} > clientWidth ${root.clientWidth})`;
  }
  if (panel.scrollWidth > panel.clientWidth) {
    return `${scope}: the PANEL OVERFLOWS by ${panel.scrollWidth - panel.clientWidth}px (scrollWidth ${panel.scrollWidth} > clientWidth ${panel.clientWidth})`;
  }
  return `${scope}: fits (document ${root.scrollWidth} <= ${root.clientWidth}, panel ${panel.scrollWidth} <= ${panel.clientWidth})`;
}

/**
 * Reports whether the panel's last control can be brought into view, as a
 * sentence.
 *
 * This is task 6.3's «clipping» half, and the half a width check cannot see.
 * `SheetContent`'s `side="right"` variant is `inset-y-0 h-full` — exactly the
 * viewport's height — and the fieldset is twenty stacked fields plus buttons, so
 * it is always taller. Without the call site's `overflow-y-auto` the surplus is
 * not a scrollbar short, it is unreachable: no scroll, no submit button. So the
 * panel is scrolled to its bottom and the last control's box is compared against
 * the panel's, which is the same question a thumb asks.
 */
async function reachabilityVerdict(
  scope: string,
  panel: HTMLElement,
): Promise<string> {
  const controls = Array.from(
    panel.querySelectorAll<HTMLElement>("input, textarea, select, button"),
  ).filter((element) => element.offsetParent !== null);
  if (controls.length === 0) {
    return `${scope}: UNREACHABLE — the panel renders no controls at all`;
  }

  panel.scrollTop = panel.scrollHeight;
  await settle();

  /*
   * The control that ends LOWEST once scrolled, not the last one in DOM order.
   * Reading DOM order here is what made the first version of this guard green
   * against a panel with its `overflow-y-auto` removed: `SheetContent` renders
   * its own `SheetPrimitive.Close` after `children` and pins it `absolute
   * right-4 top-4`, so the last control in the markup is the one nearest the
   * TOP of the panel, and a twenty-field form hanging a thousand pixels below
   * the fold was reported as fully reachable.
   */
  const panelBox = panel.getBoundingClientRect();
  const lowest = controls.reduce((worst, element) =>
    element.getBoundingClientRect().bottom >
    worst.getBoundingClientRect().bottom
      ? element
      : worst,
  );
  const overhang = Math.round(
    lowest.getBoundingClientRect().bottom - panelBox.bottom,
  );
  const name = lowest.id || lowest.textContent?.trim() || lowest.tagName;

  return overhang <= 1
    ? `${scope}: every control is reachable (the lowest, «${name}», ends ${-overhang}px inside the panel, scrolled ${Math.round(panel.scrollTop)}px of ${panel.scrollHeight - panel.clientHeight}px)`
    : `${scope}: CLIPPED — «${name}» still hangs ${overhang}px below the panel after scrolling to the bottom (scrollTop ${Math.round(panel.scrollTop)}, scrollHeight ${panel.scrollHeight}, clientHeight ${panel.clientHeight})`;
}

/**
 * The box a thumb actually has to hit for a control.
 *
 * Usually the control's own. The exception is a native checkbox with a
 * `<label for>`: the label IS a pointer target — clicking anywhere in it toggles
 * the box — so `edit-property-form.tsx` puts `tap-target` on the label rather
 * than inflating the 13×13 UA glyph to the size of a button, and documents the
 * exception beside the component as `steering/frontend.md` requires. Measuring
 * the glyph there would be measuring the wrong rectangle; measuring the label is
 * what checks the exception actually holds. Deliberately NOT extended to any
 * other control: a button wrapped in a large label would still be reported.
 */
function pointerTarget(element: HTMLElement): HTMLElement {
  if (
    element instanceof HTMLInputElement &&
    element.type === "checkbox" &&
    element.labels?.length
  ) {
    return element.labels[0];
  }
  return element;
}

/** Reports every rendered-too-small touch target inside the panel, as a sentence. */
function floorVerdict(scope: string, panel: HTMLElement): string {
  const tooSmall = Array.from(
    panel.querySelectorAll<HTMLElement>(
      "input, textarea, select, button, a[href], [role='button']",
    ),
  )
    .filter((element) => !element.matches(FLOOR_EXEMPT))
    .filter((element) => element.offsetParent !== null)
    .map((element) => {
      const { width, height } = pointerTarget(element).getBoundingClientRect();
      return { element, w: Math.round(width), h: Math.round(height) };
    })
    .filter(({ w, h }) => w < TAP_TARGET_FLOOR || h < TAP_TARGET_FLOOR)
    .map(
      ({ element, w, h }) =>
        `«${element.id || element.textContent?.trim() || element.tagName}» ${w}×${h}`,
    );

  return tooSmall.length === 0
    ? `${scope}: every touch target is at least ${TAP_TARGET_FLOOR}×${TAP_TARGET_FLOOR}`
    : `${scope}: BELOW ${TAP_TARGET_FLOOR}×${TAP_TARGET_FLOOR} — ${tooSmall.join(", ")}`;
}

describe("no property overlay overflows or clips at the minimum supported width (R4.4, task 6.3)", () => {
  for (const surface of SURFACES) {
    for (const width of WIDTHS) {
      it(`${surface.label} fits horizontally at ${width}px`, async () => {
        const panel = await openSurface(surface, width);
        expect(horizontalVerdict(`${surface.label} @ ${width}px`, panel)).toContain(
          ": fits (",
        );
      });

      it(`${surface.label} keeps every control reachable at ${width}px`, async () => {
        const panel = await openSurface(surface, width);
        expect(
          await reachabilityVerdict(`${surface.label} @ ${width}px`, panel),
        ).toContain(": every control is reachable");
      });
    }
  }
});

/**
 * R4.2/R4.3's 44×44 floor, measured rather than asserted on class names.
 *
 * `property-forms-a11y.test.tsx` and `property-detail-view.test.tsx` pin that
 * these controls CARRY `tap-target`; this pins what the browser then RENDERS,
 * which is a different claim and the one `steering/frontend.md` makes. A control
 * can carry the class and still be squeezed by a flex parent — and, as the
 * retire dialog's two buttons proved, a control can carry the class at the call
 * site while a primitive drops it on the floor, with no jsdom test noticing.
 */
describe("no control inside a property overlay renders below 44×44", () => {
  for (const surface of SURFACES) {
    for (const width of WIDTHS) {
      it(`${surface.label} keeps its 44px floor at ${width}px`, async () => {
        const panel = await openSurface(surface, width);
        expect(floorVerdict(`${surface.label} @ ${width}px`, panel)).toContain(
          ": every touch target is at least",
        );
      });
    }
  }
});
