import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import esIncidents from "@/locales/es/incidents.json";

import { TECH_STATUS_CHIPS, TechStatusChips } from "./tech-status-chips";

function renderChips(value = {}, onChange = vi.fn()) {
  render(
    <I18nProvider locale="es">
      <TechStatusChips value={value} onChange={onChange} />
    </I18nProvider>,
  );
  return onChange;
}

describe("TechStatusChips (R1.5, D5)", () => {
  it("offers exactly the six statuses a technician can see on their own rows", () => {
    expect([...TECH_STATUS_CHIPS]).toEqual([
      "ASSIGNED",
      "ACCEPTED",
      "IN_PROGRESS",
      "WAITING_EXTERNAL_PARTS",
      "AWAITING_OWNER_APPROVAL",
      "RESOLVED",
    ]);
    renderChips();
    expect(screen.getAllByRole("button")).toHaveLength(6);
  });

  it("offers neither OPEN, CLASSIFIED nor CANCELLED — none of them is assigned to anybody", () => {
    renderChips();
    for (const status of ["OPEN", "CLASSIFIED", "CANCELLED"] as const) {
      expect(
        screen.queryByRole("button", { name: esIncidents.status[status] }),
      ).toBeNull();
    }
  });

  it("emits a single status value on the first tap", () => {
    const onChange = renderChips();

    fireEvent.click(
      screen.getByRole("button", { name: esIncidents.status.IN_PROGRESS }),
    );

    expect(onChange).toHaveBeenCalledWith({ status: "IN_PROGRESS" });
  });

  it("goes back to no filter when the active chip is tapped again", () => {
    const onChange = renderChips({ status: "IN_PROGRESS" });

    fireEvent.click(
      screen.getByRole("button", { name: esIncidents.status.IN_PROGRESS }),
    );

    expect(onChange).toHaveBeenCalledWith({});
  });

  it("marks the active chip with aria-pressed", () => {
    renderChips({ status: "RESOLVED" });

    expect(
      screen.getByRole("button", { name: esIncidents.status.RESOLVED }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByRole("button", { name: esIncidents.status.ASSIGNED }),
    ).toHaveAttribute("aria-pressed", "false");
  });
});
