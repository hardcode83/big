import { describe, expect, it } from "vitest";

import { render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { TONE_BADGE_CLASS } from "@/lib/ui/status-tone";
import { severityColorGroup } from "@/features/incidents";
import esTech from "@/locales/es/tech.json";
import esIncidents from "@/locales/es/incidents.json";

import { TechIncidentRow } from "./tech-incident-row";

const INCIDENT = {
  id: "i1",
  status: "ASSIGNED",
  severity: "CRITICAL",
  category: "WATER",
  source: "GUEST",
  title: "Fuga en el baño",
  createdAt: "2026-08-12T08:00:00Z",
} as const;

function renderRow(name: string | null, code: string | null) {
  return render(
    <I18nProvider locale="es">
      <ul>
        <TechIncidentRow
          incident={INCIDENT}
          propertyName={name}
          propertyInternalCode={code}
        />
      </ul>
    </I18nProvider>,
  );
}

describe("TechIncidentRow (R1.2, R6.3, R6.4)", () => {
  it("is a list item card that links to the detail, not a table row", () => {
    renderRow("Piso Sol", "MAD-01");

    expect(screen.getByRole("listitem")).toBeInTheDocument();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/tech/incidents/i1",
    );
  });

  it("shows title, severity, status, category, creation date and the property", () => {
    renderRow("Piso Sol", "MAD-01");

    expect(screen.getByText("Fuga en el baño")).toBeInTheDocument();
    expect(screen.getByText(esIncidents.severity.CRITICAL)).toBeInTheDocument();
    expect(screen.getByText(esIncidents.status.ASSIGNED)).toBeInTheDocument();
    expect(screen.getByText(esIncidents.category.WATER)).toBeInTheDocument();
    expect(screen.getByText("Piso Sol")).toBeInTheDocument();
    expect(screen.getByText("MAD-01")).toBeInTheDocument();
  });

  it("paints the severity badge from the shared palette, with no second table (R6.4)", () => {
    renderRow("Piso Sol", "MAD-01");

    const badge = screen.getByText(esIncidents.severity.CRITICAL);
    for (const token of TONE_BADGE_CLASS[severityColorGroup("CRITICAL")].split(
      " ",
    )) {
      expect(badge.className).toContain(token);
    }
  });

  it("renders a missing property as the em-dash rather than an empty string (R2.4)", () => {
    renderRow(null, null);

    expect(screen.getAllByText(esTech.common.empty)).toHaveLength(2);
  });
});
