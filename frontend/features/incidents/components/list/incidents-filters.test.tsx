import type { ReactNode } from "react";
import { I18nextProvider } from "react-i18next";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import esCommon from "@/locales/es/common.json";
import esIncidents from "@/locales/es/incidents.json";
import esNavigation from "@/locales/es/navigation.json";
import esStates from "@/locales/es/states.json";
import i18n from "@/lib/i18n";

import { IncidentsFilters } from "./incidents-filters";

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <I18nextProvider i18n={i18n}>
      <>{children}</>
    </I18nextProvider>
  );
}

async function setupI18n() {
  await i18n.init({
    lng: "es",
    fallbackLng: "es",
    defaultNS: "common",
    ns: ["common", "navigation", "states", "incidents"],
    resources: {
      es: {
        common: esCommon,
        navigation: esNavigation,
        states: esStates,
        incidents: esIncidents,
      },
    },
    interpolation: { escapeValue: false },
  });
}

describe("IncidentsFilters", () => {
  it("renders the status and severity selects and the clear button", async () => {
    await setupI18n();
    render(<IncidentsFilters value={{}} onChange={() => undefined} />, {
      wrapper: Wrapper,
    });
    expect(screen.getByLabelText(esIncidents.fields.status)).toBeInTheDocument();
    expect(
      screen.getByLabelText(esIncidents.fields.severity),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: esIncidents.fields.clearFilters }),
    ).toBeInTheDocument();
  });

  it("calls onChange with the new status when status changes", async () => {
    await setupI18n();
    let captured: unknown = null;
    render(
      <IncidentsFilters
        value={{}}
        onChange={(next) => {
          captured = next;
        }}
      />,
      { wrapper: Wrapper },
    );
    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText(esIncidents.fields.status),
      "OPEN",
    );
    expect(captured).toEqual({ status: "OPEN", page: 1 });
  });

  it("calls onChange with the new severity when severity changes", async () => {
    await setupI18n();
    let captured: unknown = null;
    render(
      <IncidentsFilters
        value={{}}
        onChange={(next) => {
          captured = next;
        }}
      />,
      { wrapper: Wrapper },
    );
    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText(esIncidents.fields.severity),
      "HIGH",
    );
    expect(captured).toEqual({ severity: "HIGH", page: 1 });
  });

  it("calls onChange({}) when the clear-filters button is pressed", async () => {
    await setupI18n();
    let captured: unknown = "untouched";
    render(
      <IncidentsFilters
        value={{ status: "OPEN" }}
        onChange={(next) => {
          captured = next;
        }}
      />,
      { wrapper: Wrapper },
    );
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: esIncidents.fields.clearFilters }),
    );
    expect(captured).toEqual({});
  });

  it("does NOT include propertyId / property_id in the onChange payload", async () => {
    await setupI18n();
    let captured: unknown = null;
    render(
      <IncidentsFilters
        value={{}}
        onChange={(next) => {
          captured = next;
        }}
      />,
      { wrapper: Wrapper },
    );
    const user = userEvent.setup();
    await user.selectOptions(
      screen.getByLabelText(esIncidents.fields.status),
      "OPEN",
    );
    await user.selectOptions(
      screen.getByLabelText(esIncidents.fields.severity),
      "HIGH",
    );
    expect(captured).not.toHaveProperty("propertyId");
    expect(captured).not.toHaveProperty("property_id");
  });
});