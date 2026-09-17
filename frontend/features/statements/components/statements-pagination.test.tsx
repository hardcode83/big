import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, getA11yViolations, render, screen } from "@/test/render";

import { StatementsPagination } from "./statements-pagination";

function renderPagination(props: {
  page: number;
  total: number;
  perPage: number;
  onPageChange?: (page: number) => void;
}) {
  const onPageChange = props.onPageChange ?? vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <StatementsPagination {...props} onPageChange={onPageChange} />
    </I18nProvider>,
  );
  return { ...result, onPageChange };
}

const prev = () => screen.getByRole("button", { name: "Página anterior" });
const next = () => screen.getByRole("button", { name: "Página siguiente" });

describe("StatementsPagination — derives page count from total/perPage, never total_pages (R2.4)", () => {
  it("renders nothing when total is 0", () => {
    const { container } = renderPagination({ page: 1, total: 0, perPage: 20 });
    expect(container).toBeEmptyDOMElement();
  });

  it("computes 'page X of Y' from total and perPage alone", () => {
    renderPagination({ page: 2, total: 45, perPage: 20 });
    expect(screen.getByText(/Página 2 de 3/)).toBeInTheDocument();
    expect(screen.getByText(/45 en total/)).toBeInTheDocument();
  });

  it("disables previous on the first page", () => {
    renderPagination({ page: 1, total: 45, perPage: 20 });
    expect(prev()).toBeDisabled();
    expect(next()).toBeEnabled();
  });

  it("disables next on the last page", () => {
    renderPagination({ page: 3, total: 45, perPage: 20 });
    expect(next()).toBeDisabled();
    expect(prev()).toBeEnabled();
  });

  it("asks for the next and previous page without touching the network", () => {
    const { onPageChange } = renderPagination({ page: 2, total: 45, perPage: 20 });
    fireEvent.click(next());
    expect(onPageChange).toHaveBeenCalledWith(3);
    fireEvent.click(prev());
    expect(onPageChange).toHaveBeenCalledWith(1);
  });

  it("offers no page-size selector", () => {
    renderPagination({ page: 1, total: 45, perPage: 20 });
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});

describe("StatementsPagination — keyboard and accessibility", () => {
  it("exposes the nav via an accessible name", () => {
    renderPagination({ page: 1, total: 30, perPage: 20 });
    expect(
      screen.getByRole("navigation", { name: "Paginación de liquidaciones" }),
    ).toBeInTheDocument();
  });

  it("keeps both controls reachable by keyboard as real buttons", () => {
    renderPagination({ page: 1, total: 30, perPage: 20 });
    expect(prev().tagName).toBe("BUTTON");
    expect(next().tagName).toBe("BUTTON");
  });

  it("has no accessibility violations", async () => {
    const { container } = renderPagination({ page: 2, total: 45, perPage: 20 });
    expect(await getA11yViolations(container)).toEqual([]);
  });

  it("uses touch-sized controls", () => {
    renderPagination({ page: 2, total: 45, perPage: 20 });
    expect(prev()).toHaveClass("tap-target");
    expect(next()).toHaveClass("tap-target");
  });
});
