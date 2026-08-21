import { fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import { PageNav } from "./page-nav";

function renderNav(page: number, totalPages: number) {
  const onPageChange = vi.fn();
  const result = render(
    <I18nProvider locale="es">
      <PageNav page={page} totalPages={totalPages} onPageChange={onPageChange} />
    </I18nProvider>,
  );
  return { ...result, onPageChange };
}

describe("PageNav — offered only when there is more than one page (task 5.3, R1.6)", () => {
  it.each([0, 1])("renders nothing for totalPages %i", (totalPages) => {
    const { container } = renderNav(1, totalPages);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders a named navigation landmark once there are two pages", () => {
    renderNav(1, 2);
    expect(
      screen.getByRole("navigation", { name: "Paginación" }),
    ).toBeInTheDocument();
  });
});

describe("PageNav — the edges (task 5.3, R1.6, R3.5)", () => {
  it("disables the previous control on the first page", () => {
    const { onPageChange } = renderNav(1, 3);
    const previous = screen.getByRole("button", { name: "Anterior" });

    expect(previous).toBeDisabled();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeEnabled();
    fireEvent.click(previous);
    expect(onPageChange).not.toHaveBeenCalled();
  });

  it("disables the next control on the last page", () => {
    const { onPageChange } = renderNav(3, 3);
    const next = screen.getByRole("button", { name: "Siguiente" });

    expect(next).toBeDisabled();
    expect(screen.getByRole("button", { name: "Anterior" })).toBeEnabled();
    fireEvent.click(next);
    expect(onPageChange).not.toHaveBeenCalled();
  });

  it("enables both controls in the middle and moves exactly one page", () => {
    const { onPageChange } = renderNav(2, 3);

    fireEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(onPageChange).toHaveBeenLastCalledWith(3);

    fireEvent.click(screen.getByRole("button", { name: "Anterior" }));
    expect(onPageChange).toHaveBeenLastCalledWith(1);
    expect(onPageChange).toHaveBeenCalledTimes(2);
  });
});

describe("PageNav — the position (task 5.3, R1.6)", () => {
  it("interpolates both the page and the total", () => {
    renderNav(2, 7);
    expect(screen.getByText("Página 2 de 7")).toBeInTheDocument();
  });

  it("localizes the position and the controls", () => {
    render(
      <I18nProvider locale="en">
        <PageNav page={2} totalPages={7} onPageChange={vi.fn()} />
      </I18nProvider>,
    );
    expect(screen.getByText("Page 2 of 7")).toBeInTheDocument();
    expect(
      screen.getByRole("navigation", { name: "Pagination" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Next" })).toBeInTheDocument();
  });
});
