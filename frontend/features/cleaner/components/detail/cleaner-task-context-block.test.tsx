import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { CleaningTask, CleaningTaskContext } from "../../data";
import { CleanerTaskContextBlock } from "./cleaner-task-context-block";

const tenantId = vi.hoisted(() => ({ current: "tenant-1" }));

vi.mock("@/lib/auth", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth")>()),
  useAuth: () => ({
    user: { tenant_id: tenantId.current, role: "CLEANER" },
  }),
}));
vi.mock("@/lib/auth/auth-provider", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/auth/auth-provider")>()),
  useAuth: () => ({
    user: { tenant_id: tenantId.current, role: "CLEANER" },
  }),
}));

const task: CleaningTask = {
  id: "task-1",
  propertyId: "property-1",
  reservationId: "reservation-1",
  assignedCleanerId: "cleaner-1",
  status: "ASSIGNED",
  scheduledStart: null,
  scheduledEnd: null,
  acceptedAt: null,
  startedAt: null,
  completedAt: null,
  validationStatus: "PENDING",
  createdAt: "2026-08-19T18:00:00Z",
};

const baseContext: CleaningTaskContext = {
  propertyName: "Redes 11",
  propertyInternalCode: "REDES11",
  addressLine1: "Calle Mayor 1",
  addressLine2: null,
  city: "Madrid",
  province: "Madrid",
  postalCode: "28013",
  country: "ES",
  timezone: "Europe/Madrid",
  checkoutAt: "2026-08-20T11:00:00Z",
  nextCheckinDeadline: null,
};

function renderBlock(locale: "es" | "en") {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale={locale}>{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(<CleanerTaskContextBlock task={task} context={baseContext} />, {
    wrapper: Wrapper,
  });
}

describe("CleanerTaskContextBlock (R2.2, R2.6)", () => {
  it("renders the em-dash for null scalars (R2.6)", () => {
    renderBlock("es");
    // The two nullable instants are checkout_at (present) and next_checkin_deadline (null).
    const dash = screen.getAllByText("—");
    expect(dash.length).toBeGreaterThanOrEqual(1);
  });

  it("formats the checkout instant in Spanish", () => {
    renderBlock("es");
    const expected = new Intl.DateTimeFormat("es", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date("2026-08-20T11:00:00Z"));
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("formats the checkout instant in English", () => {
    renderBlock("en");
    const expected = new Intl.DateTimeFormat("en", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date("2026-08-20T11:00:00Z"));
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("never concatenates unitless values with ?? \"\"", () => {
    renderBlock("es");
    // The address line1 + line2 + city concatenation is ","-joined only with
    // truthy parts; the rendered text must not contain ", null".
    expect(screen.queryByText(/null/)).toBeNull();
  });
});