import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import { PricingPagination } from "./pricing-pagination";

function renderPagination(props: {
  page: number;
  totalPages: number;
  total: number;
  onPageChange?: (page: number) => void;
  labelKey?: string;
}) {
  const onPageChange = props.onPageChange ?? vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <PricingPagination {...props} onPageChange={onPageChange} />
    </I18nProvider>,
  );
  return { ...result, onPageChange };
}

const prev = () => screen.getByRole("button", { name: "Página anterior" });
const next = () => screen.getByRole("button", { name: "Página siguiente" });

describe("PricingPagination (R2.3, design D18)", () => {
  it("renders nothing at all when there are no pages (R2.3)", () => {
    // «Página 1 de 0» must not be representable: with `total = 0` the boundary
    // computes `totalPages = 0` and the panel shows the empty state instead.
    const { container } = renderPagination({
      page: 1,
      totalPages: 0,
      total: 0,
    });
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByText(/de 0/)).not.toBeInTheDocument();
  });

  it("disables previous on the first page", () => {
    renderPagination({ page: 1, totalPages: 3, total: 45 });
    expect(prev()).toBeDisabled();
    expect(next()).toBeEnabled();
  });

  it("disables next on the last page", () => {
    renderPagination({ page: 3, totalPages: 3, total: 45 });
    expect(next()).toBeDisabled();
    expect(prev()).toBeEnabled();
  });

  it("reports the page and the total from the response envelope", () => {
    renderPagination({ page: 2, totalPages: 3, total: 45 });
    expect(screen.getByText(/Página 2 de 3/)).toBeInTheDocument();
    expect(screen.getByText(/45 en total/)).toBeInTheDocument();
  });

  it("asks for the next and previous page without touching the network", () => {
    const { onPageChange } = renderPagination({
      page: 2,
      totalPages: 3,
      total: 45,
    });

    fireEvent.click(next());
    expect(onPageChange).toHaveBeenCalledWith(3);

    fireEvent.click(prev());
    expect(onPageChange).toHaveBeenCalledWith(1);
  });

  it("takes its nav label from the namespace, so the two tabs differ", () => {
    // Both tabs mount this component; two navs announcing the same name would
    // be ambiguous to a screen reader.
    renderPagination({
      page: 1,
      totalPages: 2,
      total: 30,
      labelKey: "rules.pagination.label",
    });
    expect(
      screen.getByRole("navigation", { name: "Paginación de reglas de precio" }),
    ).toBeInTheDocument();
  });

  it("offers no page-size selector", () => {
    renderPagination({ page: 1, totalPages: 3, total: 45 });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderPagination({
      page: 2,
      totalPages: 3,
      total: 45,
    });
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
