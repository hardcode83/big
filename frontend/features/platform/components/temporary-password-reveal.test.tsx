import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import { TemporaryPasswordReveal } from "./temporary-password-reveal";

function renderReveal(props: { temporaryPassword: string; userName: string }) {
  return render(
    <I18nProvider locale="es">
      <TemporaryPasswordReveal {...props} />
    </I18nProvider>,
  );
}

describe("TemporaryPasswordReveal (R4.3, R4.4, design D7)", () => {
  const writeText = vi.fn().mockResolvedValue(undefined);

  beforeEach(() => {
    writeText.mockClear();
    Object.assign(navigator, { clipboard: { writeText } });
  });

  it("shows the password in a read-only monospace field", () => {
    renderReveal({ temporaryPassword: "temp-pass-123", userName: "Persona Nueva" });
    expect(screen.getByText("temp-pass-123")).toBeInTheDocument();
  });

  it("shows the persistent warning that it will not be shown again", () => {
    renderReveal({ temporaryPassword: "temp-pass-123", userName: "Persona Nueva" });
    expect(
      screen.getByText(/no volverá a mostrarse/),
    ).toBeInTheDocument();
  });

  it("copies the password to the clipboard and confirms it", async () => {
    renderReveal({ temporaryPassword: "temp-pass-123", userName: "Persona Nueva" });

    fireEvent.click(screen.getByRole("button", { name: "Copiar" }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith("temp-pass-123"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Copiada" })).toBeInTheDocument(),
    );
  });

  it("never writes the password to localStorage, sessionStorage, or navigation history — including after copying it", async () => {
    // `JSON.stringify(localStorage)` is vacuous when this jsdom build's Storage is
    // polyfilled as a plain object (`test/setup.ts`) — it serializes to `{"length":N}`
    // regardless of what `setItem` actually stored. Reading every key/value pair through
    // the real Storage API works against both the native and the polyfilled shape.
    const before = { ...window.location };
    const pushStateSpy = vi.spyOn(window.history, "pushState");
    const replaceStateSpy = vi.spyOn(window.history, "replaceState");

    renderReveal({ temporaryPassword: "temp-pass-123", userName: "Persona Nueva" });
    // Exercise the one code path inside this component that could plausibly write
    // somewhere: the copy handler. A regression added to `handleCopy` (e.g. a
    // `localStorage.setItem("lastCopied", ...)` "convenience") would only be caught by
    // asserting AFTER this click, not merely at mount.
    fireEvent.click(screen.getByRole("button", { name: "Copiar" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("temp-pass-123"));

    for (let i = 0; i < localStorage.length; i++) {
      expect(localStorage.getItem(localStorage.key(i)!)).not.toContain("temp-pass-123");
    }
    for (let i = 0; i < sessionStorage.length; i++) {
      expect(sessionStorage.getItem(sessionStorage.key(i)!)).not.toContain(
        "temp-pass-123",
      );
    }
    // `window.location.href` does not move under a client-side router push in jsdom —
    // `history.pushState`/`replaceState` (what `next/navigation`'s router actually calls)
    // is the sink that would carry the password into the URL/history, so that is what
    // this test asserts against, not the inert `location.href` comparison alone.
    expect(pushStateSpy).not.toHaveBeenCalled();
    expect(replaceStateSpy).not.toHaveBeenCalled();
    expect(window.location.href).toBe(before.href);

    pushStateSpy.mockRestore();
    replaceStateSpy.mockRestore();
  });
});
