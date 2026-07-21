import { describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

const boundaries = [
  ["workspace", () => import("@/app/(workspace)/error")],
  ["public", () => import("@/app/(public)/error")],
  ["cleaner", () => import("@/app/(field)/cleaner/error")],
  ["technician", () => import("@/app/(field)/tech/error")],
  ["guest", () => import("@/app/(guest)/guest/[token]/error")],
] as const;

describe("segment error boundaries (D18)", () => {
  for (const [name, load] of boundaries) {
    it(`${name}: composes ErrorState, hides the error, retries via reset`, async () => {
      const Boundary = (await load()).default;
      const reset = vi.fn();
      render(
        <I18nProvider locale="es">
          <Boundary
            error={Object.assign(new Error("LEAK internal detail"), {
              digest: "d1",
            })}
            reset={reset}
          />
        </I18nProvider>,
      );

      const alert = screen.getByRole("alert");
      expect(alert).toBeInTheDocument();
      expect(alert.textContent).not.toContain("LEAK internal detail");
      expect(alert.textContent).not.toContain("d1");

      const retry = screen.getByRole("button", { name: "Reintentar" });
      fireEvent.click(retry);
      expect(reset).toHaveBeenCalledOnce();
    });
  }
});
