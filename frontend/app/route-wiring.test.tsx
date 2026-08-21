import { describe, expect, it, vi } from "vitest";

import { CleaningView } from "@/features/cleaning";
import { PropertyDetailView } from "@/features/dashboard";
import { GuestPortalView } from "@/features/guest-portal";

const redirectMock = vi.hoisted(() =>
  vi.fn((url: string) => {
    throw new Error(`REDIRECT:${url}`);
  }),
);
vi.mock("next/navigation", () => ({ redirect: redirectMock }));

describe("route wiring (tasks 7.2–7.6)", () => {
  it("redirects the root to /dashboard", async () => {
    const RootPage = (await import("@/app/(workspace)/page")).default;
    expect(() => RootPage()).toThrow("REDIRECT:/dashboard");
    expect(redirectMock).toHaveBeenCalledWith("/dashboard");
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
