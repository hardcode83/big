import { afterEach, describe, expect, it } from "vitest";
import { useTranslation } from "react-i18next";

import { fireEvent, render, screen, waitFor } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { LocaleSwitcher } from "@/features/shell/components/locale-switcher";

function Probe() {
  const { t } = useTranslation("navigation");
  return <span data-testid="probe">{t("routes.dashboard.title")}</span>;
}

function setup() {
  return render(
    <I18nProvider locale="es">
      <LocaleSwitcher />
      <Probe />
    </I18nProvider>,
  );
}

afterEach(() => {
  document.cookie = "autohostai.locale=; path=/; max-age=0";
  document.documentElement.lang = "";
});

describe("LocaleSwitcher (D13)", () => {
  it("exposes an accessible group with both languages", () => {
    setup();
    expect(screen.getByRole("group", { name: "Idioma" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Español" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "English" })).toBeInTheDocument();
  });

  it("marks the active language with aria-pressed", () => {
    setup();
    expect(screen.getByRole("button", { name: "Español" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "English" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("switches language, updates document lang and the locale cookie", async () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "English" }));

    await waitFor(() =>
      expect(screen.getByTestId("probe")).toHaveTextContent("Dashboard"),
    );
    expect(document.documentElement.lang).toBe("en");
    expect(document.cookie).toContain("autohostai.locale=en");
  });
});
