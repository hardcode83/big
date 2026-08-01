import { fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

import type { PaginatedResponse, TimelineEntry } from "../../data";
import { useTimelineFiltersStore } from "../../state/use-timeline-filters-store";
import { PropertyTimeline } from "./property-timeline";

const usePropertyTimeline = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-dashboard-data", () => ({ usePropertyTimeline }));

function page(entries: TimelineEntry[]): PaginatedResponse<TimelineEntry> {
  return {
    data: entries,
    total: entries.length,
    page: 1,
    per_page: entries.length,
    total_pages: entries.length === 0 ? 0 : 1,
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

function renderTimeline() {
  return render(
    <I18nProvider locale="es">
      <PropertyTimeline propertyId="redes11" />
    </I18nProvider>,
  );
}

beforeEach(() => {
  usePropertyTimeline.mockReset();
  useTimelineFiltersStore.getState().reset();
});

describe("PropertyTimeline (R2, R4)", () => {
  it("renders entries in the active locale", () => {
    usePropertyTimeline.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([entry]),
    });
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
    usePropertyTimeline.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([entry]),
    });
    renderTimeline();

    // Initial render: the display query runs unfiltered.
    expect(usePropertyTimeline).toHaveBeenCalledWith("redes11", {});

    fireEvent.change(screen.getByLabelText("Actor"), {
      target: { value: "GUEST" },
    });

    expect(usePropertyTimeline).toHaveBeenCalledWith("redes11", {
      actorType: "GUEST",
    });
  });

  it("threads the event-type filter into the query and labels options", () => {
    usePropertyTimeline.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([entry]),
    });
    renderTimeline();

    // The type option is derived from the data and localized (not the raw enum).
    const typeSelect = screen.getByLabelText("Tipo");
    expect(typeSelect).toBeInTheDocument();

    fireEvent.change(typeSelect, {
      target: { value: "CLEANING_TASK_CREATED" },
    });

    expect(usePropertyTimeline).toHaveBeenCalledWith("redes11", {
      eventType: "CLEANING_TASK_CREATED",
    });
  });

  it("shows the empty state when no entry matches", () => {
    usePropertyTimeline.mockReturnValue({
      isPending: false,
      isError: false,
      data: page([]),
    });
    renderTimeline();
    expect(
      screen.getByText("No hay eventos para los filtros seleccionados."),
    ).toBeInTheDocument();
  });
});
