import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import { PlatformPagination } from "./platform-pagination";

function renderPagination(props: {
  page: number;
  totalPages: number;
  total: number;
  onPageChange?: (page: number) => void;
}) {
  const onPageChange = props.onPageChange ?? vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <PlatformPagination {...props} onPageChange={onPageChange} />
    </I18nProvider>,
  );
  return { ...result, onPageChange };
}

const prev = () => screen.getByRole("button", { name: "Página anterior" });
const next = () => screen.getByRole("button", { name: "Página siguiente" });

describe("PlatformPagination (design D10)", () => {
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

  it("asks for the previous and the next page by number", () => {
    const { onPageChange } = renderPagination({
      page: 2,
      totalPages: 5,
      total: 90,
    });

    fireEvent.click(prev());
    expect(onPageChange).toHaveBeenCalledWith(1);

    fireEvent.click(next());
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it("reflects total and total_pages from the response envelope", () => {
    renderPagination({ page: 2, totalPages: 5, total: 90 });
    expect(screen.getByText(/Página 2 de 5/)).toBeInTheDocument();
    expect(screen.getByText(/90 tenants en total/)).toBeInTheDocument();
  });

  it("names its own landmark and every string comes from i18n", () => {
    renderPagination({ page: 1, totalPages: 2, total: 30 });
    expect(
      screen.getByRole("navigation", { name: "Paginación de tenants" }),
    ).toBeInTheDocument();
  });

  it("renders the English catalog when the locale is en (R5.1)", () => {
    render(
      <I18nProvider locale="en">
        <PlatformPagination
          page={1}
          totalPages={2}
          total={30}
          onPageChange={vi.fn()}
        />
      </I18nProvider>,
    );
    expect(screen.getByRole("button", { name: "Next page" })).toBeInTheDocument();
    expect(screen.getByText(/Page 1 of 2/)).toBeInTheDocument();
  });

  it("has no accessibility violations", async () => {
    const { container } = renderPagination({ page: 2, totalPages: 5, total: 90 });
    expect(await getA11yViolations(container)).toEqual([]);
  });
});
