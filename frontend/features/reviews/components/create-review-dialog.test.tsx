import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import type { PropertySummary } from "../data";
import { CreateReviewDialog, type CreateReviewDialogProps } from "./create-review-dialog";

const CATALOG: PropertySummary[] = [
  { id: "p-1", name: "Ático Sol", internalCode: "MAD-01" },
  { id: "p-2", name: "Loft Latina", internalCode: "MAD-02" },
];

function renderDialog(overrides: Partial<CreateReviewDialogProps> = {}) {
  const onOpenChange = vi.fn();
  const onSubmit = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <CreateReviewDialog
        open={overrides.open ?? true}
        onOpenChange={onOpenChange}
        catalog={overrides.catalog ?? CATALOG}
        isBusy={overrides.isBusy ?? false}
        errorKey={overrides.errorKey ?? null}
        onSubmit={onSubmit}
      />
    </I18nProvider>,
  );
  return { ...result, onOpenChange, onSubmit };
}

describe("CreateReviewDialog — the form (R5.3, R5.4)", () => {
  it("lists every property of the catalog", () => {
    renderDialog();
    const select = screen.getByLabelText("Vivienda");
    expect(select).toHaveTextContent("Ático Sol");
    expect(select).toHaveTextContent("Loft Latina");
  });

  it("offers all five channel values, none dropped (R5.3)", () => {
    renderDialog();
    const options = Array.from(
      screen.getByLabelText("Canal").querySelectorAll("option"),
    ).map((o) => o.textContent);
    expect(options).toEqual(["Airbnb", "Booking", "Google", "Manual", "Otro"]);
  });

  it("has an optional language field wired to the submit body", () => {
    renderDialog();
    expect(screen.getByLabelText("Idioma (opcional)")).toBeInTheDocument();
  });

  it("disables submit until a property is chosen", () => {
    renderDialog();
    expect(screen.getByRole("button", { name: "Crear reseña" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    expect(screen.getByRole("button", { name: "Crear reseña" })).toBeEnabled();
  });

  it("submits propertyId, channel, rating and the optional fields when filled", () => {
    const { onSubmit } = renderDialog();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-2" } });
    fireEvent.change(screen.getByLabelText("Canal"), { target: { value: "GOOGLE" } });
    fireEvent.change(screen.getByLabelText("Nombre del huésped (opcional)"), {
      target: { value: "Jane" },
    });
    fireEvent.change(screen.getByLabelText("Valoración (/5)"), {
      target: { value: "3.5" },
    });
    fireEvent.change(screen.getByLabelText("Texto de la reseña (opcional)"), {
      target: { value: "Nice place" },
    });
    fireEvent.change(screen.getByLabelText("Idioma (opcional)"), {
      target: { value: "en" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Crear reseña" }));

    expect(onSubmit).toHaveBeenCalledWith({
      propertyId: "p-2",
      channel: "GOOGLE",
      reviewerName: "Jane",
      rating: 3.5,
      content: "Nice place",
      language: "en",
    });
  });

  it("omits reviewerName, content and language entirely when left blank", () => {
    const { onSubmit } = renderDialog();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    fireEvent.click(screen.getByRole("button", { name: "Crear reseña" }));

    const sent = onSubmit.mock.calls[0]![0];
    expect(sent).not.toHaveProperty("reviewerName");
    expect(sent).not.toHaveProperty("content");
    expect(sent).not.toHaveProperty("language");
  });

  it("resets its local state when the cancel button closes it", () => {
    // `open` stays true here on purpose: `AlertDialogCancel` fires the
    // component's own `onOpenChange` wrapper (which calls `reset()`) before
    // the parent ever gets to lower `open` — the reset does not depend on
    // the parent re-rendering with `open=false`.
    renderDialog();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    fireEvent.change(screen.getByLabelText("Idioma (opcional)"), {
      target: { value: "en" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(screen.getByLabelText("Idioma (opcional)")).toHaveValue("");
    expect(screen.getByLabelText("Vivienda")).toHaveValue("");
  });

  it("the cancel button never submits the form", () => {
    const { onSubmit } = renderDialog();
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    expect(screen.getByRole("button", { name: "Cancelar" })).toHaveAttribute(
      "type",
      "button",
    );
    fireEvent.click(screen.getByRole("button", { name: "Cancelar" }));
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("CreateReviewDialog — busy state (design D9)", () => {
  it("disables both submit and cancel while a write is in flight", () => {
    renderDialog({ isBusy: true });
    fireEvent.change(screen.getByLabelText("Vivienda"), { target: { value: "p-1" } });
    expect(screen.getByRole("button", { name: "Crear reseña" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Cancelar" })).toBeDisabled();
  });
});

describe("CreateReviewDialog — the error renders inside the dialog, not behind it (R5.5)", () => {
  it("shows nothing when errorKey is null", () => {
    renderDialog({ errorKey: null });
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("renders the localized error text inside the overlay", () => {
    renderDialog({ errorKey: "reviews:create.error.invalid" });
    expect(
      screen.getByText("Los datos enviados no son válidos."),
    ).toBeInTheDocument();
  });
});

describe("CreateReviewDialog — accessibility", () => {
  it("has no violations", async () => {
    const { container } = renderDialog();
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
