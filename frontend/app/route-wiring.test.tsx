import { afterEach, describe, expect, it, vi } from "vitest";

import { CleaningView } from "@/features/cleaning";
import { PropertyDetailView } from "@/features/dashboard";
import { GuestPortalView } from "@/features/guest-portal";

const redirectMock = vi.hoisted(() =>
  vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
);
const cookie = vi.hoisted(() => ({ value: undefined as string | undefined }));
vi.mock("next/navigation", () => ({ redirect: redirectMock }));
vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: () => (cookie.value ? { value: cookie.value } : undefined),
  }),
}));

afterEach(() => {
  cookie.value = undefined;
  redirectMock.mockReset();
});

describe("route wiring (tasks 7.2–7.6)", () => {
  it("redirects the root to /dashboard when the session presence cookie is set", async () => {
    cookie.value = "1";
    const RootPage = (await import("@/app/page")).default;
    await expect(RootPage()).rejects.toThrow("REDIRECT:/dashboard");
    expect(redirectMock).toHaveBeenCalledWith("/dashboard", "replace");
  });

  it("renders the landing when the session presence cookie is absent", async () => {
    cookie.value = undefined;
    const RootPage = (await import("@/app/page")).default;
    const element = await RootPage();
    // The landing is wrapped in PublicShell and contains the hero
    // section — a Server Component, so we look at the rendered JSX.
    expect(element.type.name || element.type.displayName).toBeTruthy();
    expect(redirectMock).not.toHaveBeenCalled();
  });

  it("wires the property detail page to PropertyDetailView with the awaited id", async () => {
    const Page = (await import("@/app/(workspace)/properties/[id]/page")).default;
    const element = await Page({ params: Promise.resolve({ id: "redes11" }) });
    expect(element.type).toBe(PropertyDetailView);
    expect(element.props.propertyId).toBe("redes11");
  });

  it("wires the guest token page to GuestPortalView with the awaited token", async () => {
    const Page = (await import("@/app/(guest)/guest/[token]/page")).default;
    const element = await Page({ params: Promise.resolve({ token: "opaque-token" }) });
    expect(element.type).toBe(GuestPortalView);
    expect(element.props.token).toBe("opaque-token");
  });

  it("wires /cleaning to CleaningView and not to a placeholder (R1.1)", async () => {
    const Page = (await import("@/app/(workspace)/cleaning/page")).default;
    const element = Page();
    expect(element.type).toBe(CleaningView);
  });

  it("wires the cleaner task page to the cleaner-task placeholder", async () => {
    const Page = (await import("@/app/(field)/cleaner/tasks/[id]/page")).default;
    expect(Page().props.routeId).toBe("cleaner-task");
  });
});
