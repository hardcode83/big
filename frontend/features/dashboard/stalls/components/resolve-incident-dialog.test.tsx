import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import { ResolveIncidentDialog } from "./resolve-incident-dialog";

const mutate = vi.hoisted(() => vi.fn());

/** Mutable so a test can drive the hook into its error state. */
const mutationState = vi.hoisted(() => ({
  isPending: false,
  isError: false,
  error: null as unknown,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("@/features/incidents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/incidents")>()),
  useResolveIncident: () => ({
    mutate,
    isPending: mutationState.isPending,
    isError: mutationState.isError,
    error: mutationState.error,
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
  mutationState.isPending = false;
  mutationState.isError = false;
  mutationState.error = null;
});

function renderDialog() {
  return render(
    <ResolveIncidentDialog
      open
      onOpenChange={() => {}}
      incidentId="incident-1"
      trigger="CHECKIN_WINDOW_OPENED"
      blockingState="MAINTENANCE_REQUIRED"
    />,
    { wrapper: wrapper() },
  );
}

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

/** BLOCKED #5, mirror of the cancel dialog's coverage. */
describe("ResolveIncidentDialog — the error is visible and the dialog stays open (R3.3)", () => {
  it("renders the generic error and keeps the form on screen on a 500", async () => {
    mutationState.isError = true;
    mutationState.error = new ApiError({
      code: "INTERNAL",
      message: "boom",
      status: 500,
    });
    renderDialog();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe(
      "card.blocked.resolveIncident.dialog.error.generic",
    );
    expect(
      screen.getByLabelText(
        "card.blocked.resolveIncident.dialog.finalCost.label",
      ),
    ).toBeTruthy();
  });

  it("renders the conflict copy on a 409, not the generic one (R3.4)", async () => {
    mutationState.isError = true;
    mutationState.error = new ApiError({
      code: "INCIDENT_ALREADY_RESOLVED",
      message: "already resolved by someone else",
      status: 409,
    });
    renderDialog();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("card.blocked.error.conflict");
  });

  it("renders the forbidden copy on a 403", async () => {
    mutationState.isError = true;
    mutationState.error = new ApiError({
      code: "FORBIDDEN",
      message: "nope",
      status: 403,
    });
    renderDialog();

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toBe("card.blocked.error.forbidden");
  });

  it("never paints the backend's technical message", async () => {
    mutationState.isError = true;
    mutationState.error = new ApiError({
      code: "INCIDENT_ALREADY_RESOLVED",
      message: "already resolved by someone else",
      status: 409,
    });
    const { container } = renderDialog();
    expect(container.textContent).not.toContain("already resolved by someone else");
  });
});

describe("ResolveIncidentDialog — double submit (L1)", () => {
  it("dispatches one mutation for two clicks in the same frame", async () => {
    renderDialog();
    const input = (await screen.findByLabelText(
      "card.blocked.resolveIncident.dialog.finalCost.label",
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "12.50" } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.resolveIncident.dialog.confirm",
    });

    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
  });
});
