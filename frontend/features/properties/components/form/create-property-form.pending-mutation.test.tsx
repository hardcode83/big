import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import esProperties from "@/locales/es/properties.json";
import { fireEvent, render, screen, waitFor } from "@/test/render";

import type { PropertyDetailDto } from "../../data";
import type { HttpPropertiesSource } from "../../data/http/http-properties-source";

/**
 * Sibling to `create-property-form.test.tsx`, which mocks `useCreateProperty`
 * wholesale (design D1's plain-`useState` skeleton needs nothing more for its
 * own tests). QA finding 3 (R1.6) asks for something that mock cannot give:
 * proof that two rapid REAL submissions against a genuinely in-flight
 * `useCreateProperty` mutation call the underlying data-source method only
 * once — the earlier test only exercised `handleSubmit`'s defensive
 * early-return with `isPending` hard-coded `true`, never a real pending
 * transition.
 *
 * So this file leaves `useCreateProperty` real and mocks one level lower, at
 * `getPropertiesDataSource().createProperty` — the same precedent
 * `use-create-property.test.tsx` and `features/cleaning/components/
 * cleaning-view.test.tsx` (`createTask`/`assignTask` returning a
 * caller-controlled promise, under a real `QueryClient`) already establish
 * for this codebase.
 */
const pushMock = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

const createProperty = vi.hoisted(() => vi.fn());
vi.mock("../../data", () => ({
  getPropertiesDataSource: () =>
    ({
      listProperties: vi.fn(),
      getProperty: vi.fn(),
      createProperty,
    }) as unknown as HttpPropertiesSource,
}));

import { CreatePropertyForm } from "./create-property-form";

const created: PropertyDetailDto = {
  id: "new-property-id",
  name: "Redes 11",
  internalCode: "REDES11",
  pmsProvider: null,
  pmsExternalId: null,
  addressLine1: null,
  addressLine2: null,
  city: null,
  province: null,
  postalCode: null,
  country: "ES",
  timezone: "Europe/Madrid",
  maxGuests: 2,
  bedrooms: 1,
  bathrooms: 1,
  currentOperationalState: "VACANT_READY",
  defaultCheckInTime: "15:00:00",
  defaultCheckOutTime: "11:00:00",
  wifiName: null,
  hasWifiPassword: false,
  accessNotes: null,
  cleaningNotes: null,
  emergencyNotes: null,
  status: "ACTIVE",
  createdAt: "2026-09-01T09:00:00Z",
  updatedAt: "2026-09-01T09:00:00Z",
};

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * `name`/`internal_code` labels carry a visible, `aria-hidden` " *" required
 * marker (UI-UX finding 1) that is not part of the translated label string —
 * matched as an anchored, optional suffix so "Nombre" cannot ambiguously
 * match the unrelated, longer "Nombre del WiFi" label.
 */
function labelMatcher(label: string): RegExp {
  return new RegExp(`^${escapeRegExp(label)}( \\*)?$`);
}

function fillRequiredFields() {
  fireEvent.change(
    screen.getByLabelText(labelMatcher(esProperties.createForm.fields.name)),
    { target: { value: "Redes 11" } },
  );
  fireEvent.change(
    screen.getByLabelText(
      labelMatcher(esProperties.createForm.fields.internalCode),
    ),
    { target: { value: "REDES11" } },
  );
}

function renderForm() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  }
  return render(<CreatePropertyForm />, { wrapper: Wrapper });
}

beforeEach(() => {
  pushMock.mockReset();
  createProperty.mockReset();
});

describe("CreatePropertyForm — double-submit prevention against a real in-flight mutation (R1.6)", () => {
  it("calls the data source only once for two rapid submissions while the real mutation is pending", async () => {
    let resolveCreate!: (value: PropertyDetailDto) => void;
    const pending = new Promise<PropertyDetailDto>((resolve) => {
      resolveCreate = resolve;
    });
    createProperty.mockReturnValue(pending);

    const { container } = renderForm();
    fillRequiredFields();

    // First click: starts the real, unresolved mutation.
    fireEvent.click(
      screen.getByRole("button", { name: esProperties.createForm.submit }),
    );

    // Wait for the REAL `isPending` to actually reach the DOM (not a
    // hard-coded prop) before attempting the second submission — this is
    // the transition the earlier, hook-mocked test could never exercise.
    await waitFor(() =>
      expect(
        screen.getByRole("button", {
          name: esProperties.createForm.submitting,
        }),
      ).toBeDisabled(),
    );
    expect(createProperty).toHaveBeenCalledTimes(1);

    // A second, rapid submission (e.g. an Enter keypress landing on the
    // <form> before React repaints the disabled button) must still be
    // swallowed by `handleSubmit`'s own `mutation.isPending` guard.
    fireEvent.submit(container.querySelector("form")!);
    expect(createProperty).toHaveBeenCalledTimes(1);

    resolveCreate(created);
    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith("/properties/new-property-id"),
    );

    // Settling the mutation does not retroactively call the source again.
    expect(createProperty).toHaveBeenCalledTimes(1);
  });
});
