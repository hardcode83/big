import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

import type { PaginatedResponse, TimelineEntry } from "../../data";
import { TIMELINE_EVENT_TYPES } from "../../lib/timeline-event-types";
import { useTimelineFiltersStore } from "../../state/use-timeline-filters-store";
import { PropertyTimeline } from "./property-timeline";

const usePropertyTimeline = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-dashboard-data", () => ({ usePropertyTimeline }));

/** What the component sends when nothing is filtered (task 5.2: page + perPage). */
const BASE_FILTERS = { page: 1, perPage: 20 };

function page(
  entries: TimelineEntry[],
  envelope: Partial<PaginatedResponse<TimelineEntry>> = {},
): PaginatedResponse<TimelineEntry> {
  return {
    data: entries,
    total: entries.length,
    page: 1,
    per_page: 20,
    total_pages: entries.length === 0 ? 0 : 1,
    ...envelope,
  };
}

const entry: TimelineEntry = {
  id: "t1",
  occurredAt: "2026-07-30T09:12:00Z",
  actorType: "SYSTEM",
  eventType: "CLEANING_TASK_CREATED",
  severity: "INFO",
  title: "Tarea de limpieza creada automáticamente.",
  description: null,
};

function resolved(
  data: PaginatedResponse<TimelineEntry>,
): Record<string, unknown> {
  return { isPending: false, isError: false, data };
}

function renderTimeline(propertyId = "redes11") {
  return render(
    <I18nProvider locale="es">
      <PropertyTimeline propertyId={propertyId} />
    </I18nProvider>,
  );
}

beforeEach(() => {
  usePropertyTimeline.mockReset();
  useTimelineFiltersStore.getState().reset();
});

describe("PropertyTimeline (R2, R4)", () => {
  it("renders entries in the active locale", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();
    expect(
      screen.getByText("Tarea de limpieza creada automáticamente."),
    ).toBeInTheDocument();
    // Actor label localized (es), not the raw enum. It appears in both the
    // filter option and the entry, so assert at least one localized match.
    expect(screen.getAllByText(/Sistema/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/SYSTEM/)).not.toBeInTheDocument();
  });

  it("threads the actor filter into the query when the select changes", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    // Initial render: unfiltered, but always paginated (R3.1, R3.2).
    expect(usePropertyTimeline).toHaveBeenCalledWith("redes11", BASE_FILTERS);

    fireEvent.change(screen.getByLabelText("Actor"), {
      target: { value: "GUEST" },
    });

    expect(usePropertyTimeline).toHaveBeenCalledWith("redes11", {
      actorType: "GUEST",
      ...BASE_FILTERS,
    });
  });

  it("threads the event-type filter into the query", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    fireEvent.change(screen.getByLabelText("Tipo"), {
      target: { value: "CLEANING_TASK_CREATED" },
    });

    expect(usePropertyTimeline).toHaveBeenCalledWith("redes11", {
      eventType: "CLEANING_TASK_CREATED",
      ...BASE_FILTERS,
    });
  });

  it("shows the empty state when no entry matches", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([])));
    renderTimeline();
    expect(
      screen.getByText("No hay eventos para los filtros seleccionados."),
    ).toBeInTheDocument();
  });
});

describe("PropertyTimeline — closed event-type vocabulary (R2.1, R2.2, R2.5, R2.6)", () => {
  it("offers the closed enum values, localized, with a placeholder option", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    const options = Array.from(
      screen.getByLabelText<HTMLSelectElement>("Tipo").options,
    );
    // The closed list plus the "Tipo" placeholder — count is derived from
    // `TIMELINE_EVENT_TYPES` so adding a new event type (e.g. revenue-reviews' five
    // REVIEW_* types) does not require editing this assertion.
    expect(options).toHaveLength(TIMELINE_EVENT_TYPES.length + 1);
    expect(options[0].value).toBe("");
    expect(options.slice(1).map((o) => o.value)).toEqual([
      ...TIMELINE_EVENT_TYPES,
    ]);
  });

  it("labels every option and never falls back to the raw enum literal", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    const options = Array.from(
      screen.getByLabelText<HTMLSelectElement>("Tipo").options,
    ).slice(1);
    for (const option of options) {
      expect(option.textContent?.trim()).toBeTruthy();
      // R2.5: the visible text is never the enum value itself.
      expect(option.textContent).not.toBe(option.value);
    }
    expect(screen.getByRole("option", { name: "Reserva importada" })).toBeInTheDocument();
  });

  it("issues one query per render — the companion options query is gone (R2.2)", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    /*
      Before this change every render fired a SECOND, deliberately unfiltered query
      whose only job was to harvest the type options present in the data. Counting
      total calls would not catch its return, because the mount-time
      `reset()` legitimately re-renders once. What proves it is gone is that every
      call carries the SAME arguments, and that none of them is the filter-less
      shape the companion query used.
    */
    const shapes = new Set(
      usePropertyTimeline.mock.calls.map((call) => JSON.stringify(call)),
    );
    expect(shapes.size).toBe(1);
    expect([...shapes][0]).toBe(JSON.stringify(["redes11", BASE_FILTERS]));
  });

  it("shows the empty state for a type with no production writer (R2.6)", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([])));
    renderTimeline();

    fireEvent.change(screen.getByLabelText("Tipo"), {
      target: { value: "TECHNICIAN_EN_ROUTE" },
    });

    expect(
      screen.getByText("No hay eventos para los filtros seleccionados."),
    ).toBeInTheDocument();
  });
});

describe("PropertyTimeline — pagination (R3.2, R3.3, R3.4, R3.5)", () => {
  it("renders no page bar for a single page", () => {
    usePropertyTimeline.mockReturnValue(
      resolved(page([entry], { total_pages: 1 })),
    );
    renderTimeline();

    expect(
      screen.queryByRole("navigation", { name: "Paginación de la cronología" }),
    ).not.toBeInTheDocument();
  });

  it("navigates forward and back within 1..total_pages", () => {
    usePropertyTimeline.mockReturnValue(
      resolved(page([entry], { total: 30, total_pages: 2, page: 1 })),
    );
    renderTimeline();

    expect(
      screen.getByRole("navigation", { name: "Paginación de la cronología" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Página 1 de 2")).toBeInTheDocument();
    // Lower bound: page 1 cannot go back.
    expect(screen.getByRole("button", { name: "Página anterior" })).toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
    expect(usePropertyTimeline).toHaveBeenLastCalledWith("redes11", {
      page: 2,
      perPage: 20,
    });

    // Upper bound: on the last page, next is disabled and prev works.
    usePropertyTimeline.mockReturnValue(
      resolved(page([entry], { total: 30, total_pages: 2, page: 2 })),
    );
    renderTimeline();
    expect(screen.getAllByRole("button", { name: "Página siguiente" }).at(-1)).toBeDisabled();

    fireEvent.click(
      screen.getAllByRole("button", { name: "Página anterior" }).at(-1)!,
    );
    expect(usePropertyTimeline).toHaveBeenLastCalledWith("redes11", {
      page: 1,
      perPage: 20,
    });
  });

  it("returns to page 1 when a filter changes while on a later page (R3.5)", () => {
    usePropertyTimeline.mockReturnValue(
      resolved(page([entry], { total: 60, total_pages: 3, page: 3 })),
    );
    useTimelineFiltersStore.getState().setPage(3);
    renderTimeline();

    fireEvent.change(screen.getByLabelText("Severidad"), {
      target: { value: "ERROR" },
    });

    expect(usePropertyTimeline).toHaveBeenLastCalledWith("redes11", {
      severity: "ERROR",
      page: 1,
      perPage: 20,
    });
  });
});

describe("PropertyTimeline — date range (R4.1, R4.2, R4.3, R4.4)", () => {
  it("sends both ends as instants carrying a timezone, combined with the other filters", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    fireEvent.change(screen.getByLabelText("Desde"), {
      target: { value: "2026-08-01" },
    });
    fireEvent.change(screen.getByLabelText("Hasta"), {
      target: { value: "2026-08-31" },
    });

    const [, filters] = usePropertyTimeline.mock.calls.at(-1) as [
      string,
      { from: string; to: string },
    ];
    // A naive end is a 422 from the domain (R4.2).
    expect(filters.from).toMatch(/Z$/);
    expect(filters.to).toMatch(/Z$/);
    // Inclusive at both ends: `to` is the end of the chosen local day (R4.4).
    expect(new Date(filters.from).getDate()).toBe(1);
    expect(new Date(filters.to).getDate()).toBe(31);
    expect(new Date(filters.to).getHours()).toBe(23);
    expect(new Date(filters.to).getTime()).toBeGreaterThan(
      new Date(filters.from).getTime(),
    );
  });

  it("accepts either end alone — they are independent (R4.1)", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    fireEvent.change(screen.getByLabelText("Hasta"), {
      target: { value: "2026-08-31" },
    });

    const [, filters] = usePropertyTimeline.mock.calls.at(-1) as [
      string,
      Record<string, unknown>,
    ];
    expect(filters.to).toMatch(/Z$/);
    expect(filters).not.toHaveProperty("from");
  });

  it("an inverse range shows a field error and does NOT change the query (R4.3)", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    fireEvent.change(screen.getByLabelText("Desde"), {
      target: { value: "2026-08-31" },
    });
    const beforeInverse = usePropertyTimeline.mock.calls.at(-1);

    fireEvent.change(screen.getByLabelText("Hasta"), {
      target: { value: "2026-08-01" },
    });

    expect(
      screen.getByText("La fecha «hasta» es anterior a la fecha «desde»."),
    ).toBeInTheDocument();
    // Neither the invalid request nor a collateral "valid" one: the arguments the
    // hook receives are unchanged, so the query key does not move (design D8).
    expect(usePropertyTimeline.mock.calls.at(-1)).toEqual(beforeInverse);
    expect(screen.getByLabelText("Hasta")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("an inverse range typed on a later page leaves the query untouched (R4.3)", () => {
    // The same invariant as above, but from page 2 — where a page reset would
    // change the query key even though the committed range did not move. This is
    // the case the browser check caught and the first version of these tests
    // missed by always starting on page 1.
    //
    // The envelope reports page 1 throughout (the mock is static), so "next" stays
    // enabled and the assertion reads the STORE's page off the hook arguments —
    // which is the value that decides the query key.
    usePropertyTimeline.mockReturnValue(
      resolved(page([entry], { total: 30, total_pages: 2, page: 1 })),
    );
    renderTimeline();

    fireEvent.change(screen.getByLabelText("Desde"), {
      target: { value: "2026-08-01" },
    });
    fireEvent.change(screen.getByLabelText("Hasta"), {
      target: { value: "2026-08-31" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Página siguiente" }));
    const beforeInverse = usePropertyTimeline.mock.calls.at(-1);
    expect(beforeInverse?.[1]).toMatchObject({ page: 2 });

    // Make it inverse from page 2.
    fireEvent.change(screen.getByLabelText("Desde"), {
      target: { value: "2031-06-01" },
    });

    expect(
      screen.getByText("La fecha «hasta» es anterior a la fecha «desde»."),
    ).toBeInTheDocument();
    expect(usePropertyTimeline.mock.calls.at(-1)).toEqual(beforeInverse);
  });

  it("clearing an end reopens the range instead of erroring (R4.3)", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    renderTimeline();

    fireEvent.change(screen.getByLabelText("Desde"), {
      target: { value: "2026-08-01" },
    });
    fireEvent.change(screen.getByLabelText("Hasta"), {
      target: { value: "" },
    });

    expect(
      screen.queryByText("La fecha «hasta» es anterior a la fecha «desde»."),
    ).not.toBeInTheDocument();
    const [, filters] = usePropertyTimeline.mock.calls.at(-1) as [
      string,
      Record<string, unknown>,
    ];
    expect(filters).not.toHaveProperty("to");
    expect(filters.from).toMatch(/Z$/);
  });
});

describe("PropertyTimeline — text safety and preserved behaviour (R1.5, R6.1, R6.3)", () => {
  const hostile = "<img src=x onerror=alert(1)>";

  it("renders `description` as text, never as markup (R6.1)", () => {
    const { container } = (() => {
      usePropertyTimeline.mockReturnValue(
        resolved(page([{ ...entry, description: hostile }])),
      );
      return renderTimeline();
    })();

    // The literal characters are on screen…
    expect(screen.getByText(hostile)).toBeInTheDocument();
    // …and no element was created from them.
    expect(container.querySelector("img")).toBeNull();
    expect(container.innerHTML).not.toContain("<img");
    expect(container.innerHTML).toContain("&lt;img");
  });

  it("renders `title` as text too, exactly as the server composed it (R6.1, R6.3)", () => {
    const { container } = (() => {
      usePropertyTimeline.mockReturnValue(
        resolved(page([{ ...entry, title: hostile }])),
      );
      return renderTimeline();
    })();

    expect(screen.getByText(hostile)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("does not retranslate `title` — the server catalog already did (R6.3)", () => {
    // A title whose text happens to look like a translation key must still be
    // printed verbatim.
    usePropertyTimeline.mockReturnValue(
      resolved(page([{ ...entry, title: "timeline.eventType.CLEANING_STARTED" }])),
    );
    renderTimeline();

    expect(
      screen.getByText("timeline.eventType.CLEANING_STARTED"),
    ).toBeInTheDocument();
  });

  it("clears the active filters when the property changes (R1.5)", () => {
    usePropertyTimeline.mockReturnValue(resolved(page([entry])));
    const { unmount } = renderTimeline("redes11");

    fireEvent.change(screen.getByLabelText("Severidad"), {
      target: { value: "ERROR" },
    });
    fireEvent.change(screen.getByLabelText("Desde"), {
      target: { value: "2026-08-01" },
    });
    expect(useTimelineFiltersStore.getState().severity).toBe("ERROR");
    unmount();

    renderTimeline("pajaritos8");

    // The pre-existing reset-on-property-change now also clears the range draft
    // and the page, which had no test before this change.
    expect(useTimelineFiltersStore.getState()).toMatchObject({
      severity: undefined,
      actorType: undefined,
      eventType: undefined,
      fromDate: undefined,
      toDate: undefined,
      page: 1,
    });
    expect(usePropertyTimeline).toHaveBeenLastCalledWith(
      "pajaritos8",
      BASE_FILTERS,
    );
  });
});
