import { describe, expect, it } from "vitest";
import { useTranslation } from "react-i18next";

import { render, screen } from "@/test/render";
import { resolveLocale } from "@/lib/i18n/locale";
import { I18nProvider } from "@/lib/i18n/client-provider";

describe("resolveLocale (D13)", () => {
  it("accepts supported locales", () => {
    expect(resolveLocale("es")).toBe("es");
    expect(resolveLocale("en")).toBe("en");
  });

  it("falls back to es for missing or invalid values", () => {
    expect(resolveLocale(undefined)).toBe("es");
    expect(resolveLocale(null)).toBe("es");
    expect(resolveLocale("fr")).toBe("es");
    expect(resolveLocale("")).toBe("es");
  });
});

function Probe() {
  const { t } = useTranslation("navigation");
  return <span>{t("routes.dashboard.title")}</span>;
}

describe("I18nProvider (D13)", () => {
  it("renders Spanish copy for the es locale", () => {
    render(
      <I18nProvider locale="es">
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByText("Panel")).toBeInTheDocument();
  });

  it("renders English copy for the en locale", () => {
    render(
      <I18nProvider locale="en">
        <Probe />
      </I18nProvider>,
    );
    expect(screen.getByText("Dashboard")).toBeInTheDocument();
  });

  it("keeps instances isolated across providers", () => {
    render(
      <div>
        <div data-testid="a">
          <I18nProvider locale="es">
            <Probe />
          </I18nProvider>
        </div>
        <div data-testid="b">
          <I18nProvider locale="en">
            <Probe />
          </I18nProvider>
        </div>
      </div>,
    );
    expect(screen.getByTestId("a")).toHaveTextContent("Panel");
    expect(screen.getByTestId("b")).toHaveTextContent("Dashboard");
  });
});
