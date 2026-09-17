import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import { StatementDownloads } from "./statement-downloads";

const useStatementDownload = vi.hoisted(() => vi.fn());

vi.mock("../hooks/use-statement-download", () => ({ useStatementDownload }));

type HookState = Partial<ReturnType<typeof buildHook>>;

function buildHook() {
  return {
    downloadCsv: vi.fn(() => Promise.resolve()),
    downloadPdf: vi.fn(() => Promise.resolve()),
    csvPending: false,
    pdfPending: false,
    isCsvPending: false,
    isPdfPending: false,
    csvError: null as Error | null,
    pdfError: null as Error | null,
  };
}

function renderDownloads(state: HookState = {}, locale: "es" | "en" = "es") {
  const hook = { ...buildHook(), ...state };
  useStatementDownload.mockReturnValue(hook);
  const result = render(
    <I18nProvider locale={locale}>
      <StatementDownloads statementId="st-1" />
    </I18nProvider>,
  );
  return { ...result, hook };
}

const csvButton = (name = "Descargar CSV") => screen.getByRole("button", { name });
const pdfButton = (name = "Descargar PDF") => screen.getByRole("button", { name });

describe("StatementDownloads — controls call the hook (R4, R5)", () => {
  it("passes the statement id to the download hook", () => {
    renderDownloads();
    expect(useStatementDownload).toHaveBeenCalledWith("st-1");
  });

  it("triggers the CSV export via the hook, never touching the network directly", () => {
    const { hook } = renderDownloads();
    fireEvent.click(csvButton());
    expect(hook.downloadCsv).toHaveBeenCalledTimes(1);
    expect(hook.downloadPdf).not.toHaveBeenCalled();
  });

  it("triggers the PDF export via the hook", () => {
    const { hook } = renderDownloads();
    fireEvent.click(pdfButton());
    expect(hook.downloadPdf).toHaveBeenCalledTimes(1);
    expect(hook.downloadCsv).not.toHaveBeenCalled();
  });

  it("does not inspect the payload — it only calls the hook (R4.3)", () => {
    const { hook } = renderDownloads();
    fireEvent.click(csvButton());
    // The hook is the only integration point; the component holds no parsing,
    // validation or re-encoding of the returned bytes.
    expect(hook.downloadCsv).toHaveBeenCalledWith();
  });
});

describe("StatementDownloads — per-format pending state (R5.1, D5)", () => {
  it("shows a localized pending label and disables only the CSV control while CSV downloads", () => {
    renderDownloads({ csvPending: true });
    const csv = screen.getByRole("button", { name: "Descargando…" });
    expect(csv).toBeDisabled();
    expect(csv).toHaveAttribute("aria-busy", "true");
    expect(pdfButton()).toBeEnabled();
  });

  it("disables only the PDF control while PDF downloads", () => {
    renderDownloads({ pdfPending: true });
    const pdf = screen.getByRole("button", { name: "Descargando…" });
    expect(pdf).toBeDisabled();
    expect(csvButton()).toBeEnabled();
  });

  it("prevents a second activation while pending (disabled control is a no-op)", () => {
    const { hook } = renderDownloads({ csvPending: true });
    fireEvent.click(screen.getByRole("button", { name: "Descargando…" }));
    expect(hook.downloadCsv).not.toHaveBeenCalled();
  });
});

describe("StatementDownloads — translated error without inspecting the file (R4.4, R5.4)", () => {
  it("shows a translated error when the CSV download fails", () => {
    renderDownloads({ csvError: new Error("boom") });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "No se pudo descargar el archivo. Vuelve a intentarlo.",
    );
  });

  it("shows the English error under the en locale", () => {
    renderDownloads({ pdfError: new Error("boom") }, "en");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The file could not be downloaded. Please try again.",
    );
  });

  it("shows no error region on the happy path", () => {
    renderDownloads();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("StatementDownloads — accessibility and touch targets (D6, R5.5)", () => {
  it("uses touch-sized controls with accessible names", () => {
    renderDownloads();
    expect(csvButton()).toHaveClass("tap-target");
    expect(pdfButton()).toHaveClass("tap-target");
    expect(csvButton().tagName).toBe("BUTTON");
  });

  it("exposes the controls under an accessible group label", () => {
    renderDownloads();
    expect(
      screen.getByRole("region", { name: "Exportar liquidación" }),
    ).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderDownloads();
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("keeps controls keyboard reachable with visible interaction and mobile-safe layout", () => {
    renderDownloads();
    const csv = csvButton();
    const pdf = pdfButton();
    const controls = csv.parentElement;

    expect(csv).toHaveProperty("tabIndex", 0);
    expect(pdf).toHaveProperty("tabIndex", 0);
    csv.focus();
    expect(csv).toHaveFocus();
    expect(csv).toHaveClass(
      "focus-visible:outline-none",
      "focus-visible:ring-2",
      "hover:bg-accent",
      "hover:text-accent-foreground",
      "bg-background",
    );
    expect(controls).toHaveClass("flex", "flex-wrap");
    expect(csv).toHaveClass("tap-target");
    expect(pdf).toHaveClass("tap-target");
  });
});
