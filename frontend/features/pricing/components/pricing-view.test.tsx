import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { I18nProvider } from "@/lib/i18n/client-provider";
import {
  fireEvent,
  getA11yViolations,
  render,
  screen,
  waitFor,
} from "@/test/render";

import type {
  PriceRecommendation,
  PricingDataSource,
  PricingRule,
} from "../data";
import { usePricingUiStore } from "../state/use-pricing-ui-store";
import { PricingView } from "./pricing-view";

const listRecommendations = vi.hoisted(() => vi.fn());
const listRules = vi.hoisted(() => vi.fn());
const listProperties = vi.hoisted(() => vi.fn());
const decideRecommendation = vi.hoisted(() => vi.fn());
const generateRecommendations = vi.hoisted(() => vi.fn());
const useHasPermission = vi.hoisted(() => vi.fn(() => true));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1", role: "PROPERTY_MANAGER" } }),
  useHasPermission,
}));

vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getPricingDataSource: (): PricingDataSource => ({
    listRecommendations,
    listRules,
    listProperties,
    decideRecommendation,
    generateRecommendations,
  }),
}));

const RECOMMENDATION: PriceRecommendation = {
  id: "rec-1",
  propertyId: "p-1",
  pricingRuleId: "rule-1",
  date: "2026-09-01",
  recommendedPrice: "142.50",
  status: "RECOMMENDED",
  explanation: "Base 120.00 · Season (High) +10.00%",
};

const RULE: PricingRule = {
  id: "rule-1",
  propertyId: null,
  name: "Regla de cartera",
  active: true,
  basePrice: "120.00",
  minPrice: "80.00",
  maxPrice: "300.00",
  maxDailyChangePct: "15.00",
  modifierCounts: {
    weekday: 1,
    leadTime: 0,
    occupancy: 0,
    seasonality: 0,
    event: 0,
  },
};

function page<T>(items: T[], overrides: Partial<Record<string, number>> = {}) {
  return {
    items,
    total: items.length,
    page: 1,
    perPage: 20,
    totalPages: items.length === 0 ? 0 : 1,
    ...overrides,
  };
}

function renderView() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(<PricingView />, { wrapper: Wrapper });
}

beforeEach(() => {
  usePricingUiStore.getState().reset();
  useHasPermission.mockReturnValue(true);
  listRecommendations.mockReset().mockResolvedValue(page([RECOMMENDATION]));
  listRules.mockReset().mockResolvedValue(page([RULE]));
  listProperties
    .mockReset()
    .mockResolvedValue([
      { id: "p-1", name: "Ático Sol", internalCode: "MAD-01" },
    ]);
  decideRecommendation.mockReset().mockResolvedValue({
    ...RECOMMENDATION,
    status: "APPROVED",
  });
  generateRecommendations
    .mockReset()
    .mockResolvedValue({ created: 4, updated: 3, preserved: 2, skipped: 1 });
});

const tab = (name: string) => screen.getByRole("tab", { name });

describe("PricingView — tabs (R1.1, R1.3, R2.1, R5.1)", () => {
  it("opens on Recommendations", async () => {
    renderView();
    await waitFor(() =>
      expect(tab("Recomendaciones")).toHaveAttribute("aria-selected", "true"),
    );
  });

  it("does not query the rules until the tab is opened", async () => {
    // Only the active panel is mounted (design D10), so the inactive tab's
    // query must not fire on load.
    renderView();
    await waitFor(() => expect(listRecommendations).toHaveBeenCalled());
    expect(listRules).not.toHaveBeenCalled();

    fireEvent.click(tab("Reglas"));
    await waitFor(() => expect(listRules).toHaveBeenCalledTimes(1));
  });

  it("keeps each tab's filters and page when switching back and forth", async () => {
    renderView();
    await waitFor(() => expect(listRecommendations).toHaveBeenCalled());

    usePricingUiStore.getState().setRecommendationPage(3);
    fireEvent.click(tab("Reglas"));
    await waitFor(() => expect(listRules).toHaveBeenCalled());
    expect(usePricingUiStore.getState().rules.page).toBe(1);

    fireEvent.click(tab("Recomendaciones"));
    expect(usePricingUiStore.getState().recommendations.page).toBe(3);
  });
});

describe("PricingView — the queue (R2.3, R2.4)", () => {
  it("renders the rows the source returned", async () => {
    renderView();
    expect(
      await screen.findByRole("heading", { name: /MAD-01 · Ático Sol/ }),
    ).toBeInTheDocument();
    expect(screen.getByText("142,50")).toBeInTheDocument();
  });

  it("renders the empty state and no pagination when total is 0 (R2.3)", async () => {
    listRecommendations.mockResolvedValue(page([]));
    renderView();
    expect(await screen.findByText("Sin recomendaciones")).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByText(/de 0/)).not.toBeInTheDocument();
  });
});

describe("PricingView — one write in flight (R3.3, R4.4, design D8)", () => {
  it("disables every row's decision buttons and the regenerate button", async () => {
    // A never-resolving decision, so the in-flight state is observable.
    decideRecommendation.mockImplementation(() => new Promise(() => {}));
    listRecommendations.mockResolvedValue(
      page([RECOMMENDATION, { ...RECOMMENDATION, id: "rec-2" }]),
    );
    renderView();

    const approveButtons = await screen.findAllByRole("button", {
      name: "Aprobar",
    });
    fireEvent.click(approveButtons[0]);
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Regenerar ahora" }),
      ).toBeDisabled(),
    );
    // The other row's buttons are blocked too: a second mutate would detach the
    // first and swallow its rejection.
    expect(screen.getByRole("button", { name: "Aprobar" })).toBeDisabled();
  });

  it("does NOT disable the filter controls", async () => {
    // Disabling a focused element drops focus to `<body>`, stranding a keyboard
    // user because someone else's write is in flight.
    decideRecommendation.mockImplementation(() => new Promise(() => {}));
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Regenerar ahora" }),
      ).toBeDisabled(),
    );
    for (const label of ["Vivienda", "Desde", "Hasta", "Estado"]) {
      expect(screen.getByLabelText(label)).toBeEnabled();
    }
  });
});

describe("PricingView — the live region (R3.6, R3.8, R4.2, R4.3)", () => {
  it("announces the four counters after a generation", async () => {
    renderView();
    fireEvent.click(
      await screen.findByRole("button", { name: "Regenerar ahora" }),
    );
    expect(
      await screen.findByText(
        "Generación ejecutada: 4 creadas, 3 actualizadas, 2 conservadas, 1 omitidas.",
      ),
    ).toBeInTheDocument();
  });

  it("shows the 409 copy of its own, distinct from the generic one (R3.6)", async () => {
    decideRecommendation.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "wrong state", status: 409 }),
    );
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    expect(
      await screen.findByText(
        "Esa recomendación ya no está en el estado que creías. Vuelve a cargar la lista.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a 403 as an error and never as success (R3.8)", async () => {
    decideRecommendation.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
    );
    renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(
      "No tienes permiso para decidir recomendaciones de precio.",
    );
  });

  it("never paints the backend's own message (R3.7)", async () => {
    decideRecommendation.mockRejectedValue(
      new ApiError({
        code: "CONFLICT",
        message: "Recommendation 7f3c is not in state RECOMMENDED",
        status: 409,
      }),
    );
    const { container } = renderView();

    fireEvent.click(await screen.findByRole("button", { name: "Aprobar" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirmar" }));

    await screen.findByRole("alert");
    expect(container.textContent).not.toContain("7f3c");
    expect(container.textContent).not.toContain("is not in state");
  });

  it("has exactly one live region (design D8)", async () => {
    const { container } = renderView();
    await screen.findByRole("heading", { name: /MAD-01/ });
    expect(container.querySelectorAll('[aria-live="polite"]')).toHaveLength(1);
  });
});

describe("PricingView — the catalog does not take the view down (R2.8)", () => {
  it("renders the queue with degraded identity when the catalog fails", async () => {
    listProperties.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );
    renderView();

    expect(
      await screen.findByText("Identidad no disponible"),
    ).toBeInTheDocument();
    expect(screen.getByText("142,50")).toBeInTheDocument();
    expect(
      screen.queryByText("No se pudieron cargar las recomendaciones"),
    ).not.toBeInTheDocument();
  });
});

describe("PricingView — reading without permission (R7.3, design D17)", () => {
  it("shows the localized 403 copy rather than a blank screen", async () => {
    // A CLEANER arriving from the sidebar, which does not filter by role.
    useHasPermission.mockReturnValue(false);
    listRecommendations.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }),
    );
    renderView();

    expect(
      await screen.findByText(
        "No tienes permiso para ver los precios de este tenant.",
      ),
    ).toBeInTheDocument();
  });

  it("hides the decision and regeneration controls", async () => {
    useHasPermission.mockReturnValue(false);
    renderView();

    await screen.findByRole("heading", { name: /MAD-01/ });
    expect(
      screen.queryByRole("button", { name: "Aprobar" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Regenerar ahora" }),
    ).not.toBeInTheDocument();
  });
});

describe("PricingView — the rules tab (R5.3, R5.5)", () => {
  it("lists rules read-only, naming the whole-portfolio scope", async () => {
    renderView();
    await screen.findByRole("heading", { name: /MAD-01/ });
    fireEvent.click(tab("Reglas"));

    expect(await screen.findByText("Regla de cartera")).toBeInTheDocument();
    expect(screen.getByText("Toda la cartera")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Aprobar" }),
    ).not.toBeInTheDocument();
  });
});

describe("PricingView — the rules tab's own empty and error states (R5.1)", () => {
  /**
   * These two branches of `rules-panel.tsx` were reachable by nothing until the
   * QA panel enumerated the suite and found them. They are not the same code as
   * the recommendations panel's: the rules tab has its own copy keys
   * (`rules.list.empty.*`, `rules.list.error.title`) and its own query. The note
   * on task 7.8 claiming this was «igual que 7.6» was wrong — 7.6's three tests
   * do exist above; these did not exist at all.
   */
  it("renders the rules empty state, with its own copy and no pagination", async () => {
    listRules.mockResolvedValue(page([]));
    renderView();
    await screen.findByRole("heading", { name: /MAD-01/ });
    fireEvent.click(tab("Reglas"));

    expect(await screen.findByText("Sin reglas de precio")).toBeInTheDocument();
    // Its own copy, not the recommendations one.
    expect(screen.queryByText("Sin recomendaciones")).not.toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByText(/de 0/)).not.toBeInTheDocument();
  });

  it("shows the read-error copy for the rules tab, chosen by status", async () => {
    listRules.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "no rules for you", status: 403 }),
    );
    const { container } = renderView();
    await screen.findByRole("heading", { name: /MAD-01/ });
    fireEvent.click(tab("Reglas"));

    expect(
      await screen.findByText("No se pudieron cargar las reglas"),
    ).toBeInTheDocument();
    // `readErrorKey`, not the decide mapper: a 403 on a listing says something a
    // retry will never change.
    expect(
      screen.getByText("No tienes permiso para ver los precios de este tenant."),
    ).toBeInTheDocument();
    // And never the backend's own words (R3.7).
    expect(container.textContent).not.toContain("no rules for you");
  });

  it("keeps the recommendations tab working when the rules query fails", async () => {
    // The two tabs are independent queries; one failing must not take the other
    // down when the user switches back.
    //
    // A 4xx, not a 5xx: the read hooks set `retry: retryPolicy`, which overrides
    // the harness's `queries: { retry: false }` default, and the shared policy
    // retries a 5xx twice with backoff — so a 500 never settles inside the test
    // and the error state simply never appears.
    listRules.mockRejectedValue(
      new ApiError({ code: "FORBIDDEN", message: "nope", status: 403 }),
    );
    renderView();
    await screen.findByRole("heading", { name: /MAD-01/ });
    fireEvent.click(tab("Reglas"));
    await screen.findByText("No se pudieron cargar las reglas");

    fireEvent.click(tab("Recomendaciones"));
    expect(
      await screen.findByRole("heading", { name: /MAD-01/ }),
    ).toBeInTheDocument();
  });
});

describe("PricingView — accessibility", () => {
  it("has no violations", async () => {
    const { container } = renderView();
    await screen.findByRole("heading", { name: /MAD-01/ });
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
