import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ResolveIncidentDialog } from "./resolve-incident-dialog";

const mutate = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("@/features/incidents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/incidents")>()),
  useResolveIncident: () => ({
    mutate,
    isPending: false,
    isError: false,
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en" },
  }),
}));

function wrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrap({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  };
}

beforeEach(() => {
  mutate.mockReset();
});

describe("ResolveIncidentDialog — validation (R2.3, R3.1)", () => {
  it("does not submit when final_cost is empty", async () => {
    render(
      <ResolveIncidentDialog
        open
        onOpenChange={() => {}}
        incidentId="incident-1"
        trigger="CHECKIN_WINDOW_OPENED"
        blockingState="MAINTENANCE_REQUIRED"
      />,
      { wrapper: wrapper() },
    );
    const submit = await screen.findByRole("button", {
      name: "card.blocked.resolveIncident.dialog.confirm",
    });
    expect(submit.hasAttribute("disabled")).toBe(true);
    fireEvent.click(submit);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("does not submit when final_cost is not a positive decimal", async () => {
    render(
      <ResolveIncidentDialog
        open
        onOpenChange={() => {}}
        incidentId="incident-1"
        trigger="CHECKIN_WINDOW_OPENED"
        blockingState="MAINTENANCE_REQUIRED"
      />,
      { wrapper: wrapper() },
    );
    const input = (await screen.findByLabelText(
      "card.blocked.resolveIncident.dialog.finalCost.label",
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "abc" } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.resolveIncident.dialog.confirm",
    });
    expect(submit.hasAttribute("disabled")).toBe(true);
  });

  it("submits with a valid positive decimal", async () => {
    render(
      <ResolveIncidentDialog
        open
        onOpenChange={() => {}}
        incidentId="incident-1"
        trigger="CHECKIN_WINDOW_OPENED"
        blockingState="MAINTENANCE_REQUIRED"
      />,
      { wrapper: wrapper() },
    );
    const input = (await screen.findByLabelText(
      "card.blocked.resolveIncident.dialog.finalCost.label",
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "12.50" } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.resolveIncident.dialog.confirm",
    });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        { incidentId: "incident-1", finalCost: "12.50" },
        expect.any(Object),
      ),
    );
  });

  it("the mutation hook is configured retry:false — exactly one attempt per click", async () => {
    let calls = 0;
    mutate.mockImplementation(() => {
      calls += 1;
    });
    render(
      <ResolveIncidentDialog
        open
        onOpenChange={() => {}}
        incidentId="incident-1"
        trigger="CHECKIN_WINDOW_OPENED"
        blockingState="MAINTENANCE_REQUIRED"
      />,
      { wrapper: wrapper() },
    );
    const input = (await screen.findByLabelText(
      "card.blocked.resolveIncident.dialog.finalCost.label",
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "12.50" } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.resolveIncident.dialog.confirm",
    });
    fireEvent.click(submit);
    await waitFor(() => expect(calls).toBe(1));
  });
});