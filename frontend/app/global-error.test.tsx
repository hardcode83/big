import { afterEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render } from "@/test/render";
import GlobalError from "@/app/global-error";

afterEach(() => {
  document.cookie = "autohostai.locale=; path=/; max-age=0";
});

describe("GlobalError (D18)", () => {
  it("shows a safe localized message and never the error details", () => {
    const { container } = render(
      <GlobalError
        error={Object.assign(new Error("SECRET stack boom"), {
          digest: "abc123",
        })}
        reset={() => {}}
      />,
    );
    expect(container.textContent).toContain("Error inesperado");
    expect(container.textContent).not.toContain("SECRET stack boom");
    expect(container.textContent).not.toContain("abc123");
  });

  it("offers a real recovery action wired to reset", () => {
    const reset = vi.fn();
    const { container } = render(
      <GlobalError error={new Error("x")} reset={reset} />,
    );
    const button = container.querySelector("button");
    fireEvent.click(button!);
    expect(reset).toHaveBeenCalledOnce();
  });

  it("uses the locale cookie for its inline catalog", () => {
    document.cookie = "autohostai.locale=en";
    const { container } = render(
      <GlobalError error={new Error("x")} reset={() => {}} />,
    );
    expect(container.textContent).toContain("Unexpected error");
  });
});
