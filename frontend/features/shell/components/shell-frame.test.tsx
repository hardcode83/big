import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";
import { ShellFrame } from "@/features/shell/components/shell-frame";

vi.mock("next/navigation", () => ({ usePathname: () => "/dashboard" }));

function renderFrame(props: Partial<Parameters<typeof ShellFrame>[0]> = {}) {
  return render(
    <ShellFrame
      skipLink={<a href="#main-content">saltar</a>}
      topbar={<div data-testid="topbar" />}
      {...props}
    >
      <div>contenido</div>
    </ShellFrame>,
  );
}

describe("ShellFrame footer slot (change app-version-visibility, D7/R3.1)", () => {
  it("renders the footer when one is passed", () => {
    renderFrame({ footer: <div data-testid="footer-probe">pie</div> });
    expect(screen.getByTestId("footer-probe")).toBeInTheDocument();
  });

  it("renders no footer element when the shell passes none", () => {
    // The guest portal relies on this: it simply does not pass the slot (R3.7).
    const { container } = renderFrame();
    expect(container.querySelector("footer")).toBeNull();
  });

  it("keeps the footer OUTSIDE the main landmark", () => {
    // A footer nested inside `main` would break the single-landmark structure that
    // `frontend-foundation` requires of the frame.
    renderFrame({ footer: <div data-testid="footer-probe">pie</div> });
    expect(
      screen.getByRole("main").querySelector('[data-testid="footer-probe"]'),
    ).toBeNull();
  });

  it("reserves the mobile bottom-nav space on the column, not on main", () => {
    // This is the whole point of design D7. `BottomNavigation` is
    // `fixed inset-x-0 bottom-0 z-40 md:hidden`, so something has to reserve its height
    // on mobile. With `pb-16` on `main` (where it used to be), a footer rendered after
    // `main` lands inside the overlaid strip and is unreadable on a phone; with the
    // padding on the column that wraps topbar/main/footer, the footer sits above it.
    const { container } = renderFrame({
      footer: <div data-testid="footer-probe">pie</div>,
      bottomNavigation: (
        <nav data-testid="bottom-nav" className="fixed bottom-0" />
      ),
    });

    const main = screen.getByRole("main");
    expect(main.className).not.toContain("pb-16");

    const column = main.parentElement;
    expect(column?.className).toContain("pb-16");
    expect(column?.className).toContain("md:pb-0");
    // And the footer is inside that padded column, which is what lifts it clear.
    expect(
      column?.querySelector('[data-testid="footer-probe"]'),
    ).not.toBeNull();
    expect(
      container.querySelector('[data-testid="bottom-nav"]'),
    ).not.toBeNull();
  });

  it("places the footer before the fixed bottom navigation in document order", () => {
    const { container } = renderFrame({
      footer: <div data-testid="footer-probe">pie</div>,
      bottomNavigation: <nav data-testid="bottom-nav" />,
    });

    const footer = container.querySelector('[data-testid="footer-probe"]')!;
    const bottomNav = container.querySelector('[data-testid="bottom-nav"]')!;
    expect(
      footer.compareDocumentPosition(bottomNav) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });
});
