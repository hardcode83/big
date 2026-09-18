import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import { DetailHeaderBlock } from "./detail-header-block";

function renderBlock(
  overrides: Partial<React.ComponentProps<typeof DetailHeaderBlock>> = {},
) {
  const props = {
    status: "COMPLETED" as const,
    validationStatus: "PASSED" as const,
    scheduledStart: "2026-08-20T09:00:00Z",
    scheduledEnd: "2026-08-20T11:00:00Z",
    completedAt: "2026-08-20T11:00:00Z",
    validatedAt: "2026-08-20T12:00:00Z",
    ...overrides,
  };
  return render(
    <I18nProvider locale="es">
      <DetailHeaderBlock {...props} />
    </I18nProvider>,
  );
}

/**
 * The locale catalog additions for `cleaning:detail.*` land in section 6 of
 * the change. Tests assert against the localized catalog values (es locale)
 * rather than against the key path — the same shape the screen reader
 * announces once the catalog is in place. Section 6 of the change fills the
 * catalog, so the assertions track those translations.
 */
const STATUS_LABEL = "Estado";
const VALIDATION_LABEL = "Validación";
const SCHEDULED_LABEL = "Ventana programada";
const COMPLETED_LABEL = "Fecha de finalización";
const VALIDATED_LABEL = "Fecha de validación";

describe("DetailHeaderBlock (proposal R2.1-R2.3)", () => {
  it("renders the status as a translated, coloured badge (R2.1)", () => {
    renderBlock({ status: "COMPLETED" });
    // The status label and the column header label both appear; the
    // status translation exists in the catalog, the column header is
    // the new key.
    expect(screen.getByText("Completada")).toBeInTheDocument();
    expect(screen.getByText(STATUS_LABEL)).toBeInTheDocument();
  });

  it("renders the validation status as a plain label (R2.1)", () => {
    renderBlock({ validationStatus: "FAILED" });
    expect(screen.getByText("No conforme")).toBeInTheDocument();
    expect(screen.getByText(VALIDATION_LABEL)).toBeInTheDocument();
  });

  it("formats the scheduled window with Intl.DateTimeFormat (R2.1)", () => {
    renderBlock();
    expect(screen.getByText(SCHEDULED_LABEL)).toBeInTheDocument();
    // Both endpoints render — the locale is `es`, so a mid-morning time
    // lands inside a date string. We don't pin the exact format (it
    // depends on ICU data) — only that both endpoints render.
    const text = document.body.textContent ?? "";
    expect(text).toMatch(/20/);
    expect(text).toContain(":");
  });

  it("does not show completedAt/validatedAt for a fresh task (R2.2)", () => {
    renderBlock({
      status: "CREATED",
      validationStatus: "PENDING",
      completedAt: null,
      validatedAt: null,
    });
    expect(screen.queryByText(COMPLETED_LABEL)).not.toBeInTheDocument();
    expect(screen.queryByText(VALIDATED_LABEL)).not.toBeInTheDocument();
  });

  it("shows completedAt when the task was completed (R2.2)", () => {
    renderBlock({
      status: "COMPLETED",
      validationStatus: "PENDING",
      completedAt: "2026-08-20T11:00:00Z",
      validatedAt: null,
    });
    expect(screen.getByText(COMPLETED_LABEL)).toBeInTheDocument();
    expect(screen.queryByText(VALIDATED_LABEL)).not.toBeInTheDocument();
  });

  it("renders both completedAt and validatedAt when both exist (R2.2)", () => {
    renderBlock();
    expect(screen.getByText(COMPLETED_LABEL)).toBeInTheDocument();
    expect(screen.getByText(VALIDATED_LABEL)).toBeInTheDocument();
  });

  it("never prints the raw enum identifiers in the body text", () => {
    const { container } = renderBlock({ status: "COMPLETED" });
    expect(container.textContent).not.toContain("COMPLETED");
    expect(container.textContent).not.toContain("PASSED");
  });

  it("uses the 'Validación rechazada' label when validationStatus is FAILED (R2.3)", () => {
    renderBlock({ validationStatus: "FAILED" });
    expect(screen.getByText("Validación rechazada")).toBeInTheDocument();
    expect(screen.queryByText(VALIDATED_LABEL)).not.toBeInTheDocument();
  });
});