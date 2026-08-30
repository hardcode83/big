import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BlockedTransitionSummary } from "../data";
import { stallsKeys } from "../hooks/query-keys";
import { BlockedTransitionsSection } from "./blocked-transitions-section";

const useAuth = vi.hoisted(() => vi.fn());
const useHasPermission = vi.hoisted(() =>
  vi.fn((_permission: string): boolean => false),
);
vi.mock("@/lib/auth", () => ({ useAuth, useHasPermission }));

const cancelTask = vi.hoisted(() => vi.fn());
const resolveIncident = vi.hoisted(() => vi.fn());

vi.mock("@/features/cleaning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/cleaning")>()),
  useCancelCleaningTask: () => ({
    mutate: cancelTask,
    isPending: false,
    isError: false,
  }),
}));

vi.mock("@/features/incidents", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/incidents")>()),
  useResolveIncident: () => ({
    mutate: resolveIncident,
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

function makeStall(
  partial: Partial<BlockedTransitionSummary> & {
    property_id: string;
    reservation_id: string;
    trigger: string;
    blocking_state: string;
    due_since: string;
  },
): BlockedTransitionSummary {
  return {
    property_code: partial.property_id.toUpperCase(),
    ...partial,
  } as BlockedTransitionSummary;
}

function wrapper(queryClient: QueryClient) {
  return function Wrap({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
  };
}

function setRole(role: string) {
  useAuth.mockReturnValue({ user: { tenant_id: "tenant-1", role } });
}

function setPermissions(record: Record<string, boolean>) {
  useHasPermission.mockImplementation((p: string) => record[p] ?? false);
}

beforeEach(() => {
  useAuth.mockReset();
  useHasPermission.mockReset();
  cancelTask.mockReset();
  resolveIncident.mockReset();
});

describe("BlockedTransitionsSection — actions (R2.4, R3.2)", () => {
  it("renders nothing when there are no stalls (R1.3)", () => {
    const view = render(
      <BlockedTransitionsSection stalls={[]} headingId="h" />,
      { wrapper: wrapper(new QueryClient()) },
    );
    expect(view.container.firstChild).toBeNull();
  });

  it("does not show any action button when neither permission is held (R2.4)", () => {
    setRole("TENANT_OWNER");
    useHasPermission.mockReturnValue(false);
    const stalls: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-22T13:00:00Z",
        cleaning_task_id: "task-1",
      }),
      makeStall({
        property_id: "redes11",
        reservation_id: "r-2",
        trigger: "CHECKIN_WINDOW_OPENED",
        blocking_state: "MAINTENANCE_REQUIRED",
        due_since: "2026-08-21T13:00:00Z",
        incident_id: "incident-1",
      }),
    ];
    render(
      <BlockedTransitionsSection stalls={stalls} headingId="h" />,
      { wrapper: wrapper(new QueryClient()) },
    );
    expect(screen.queryByRole("button", { name: "card.blocked.cancelCleaning.label" })).toBeNull();
    expect(screen.queryByRole("button", { name: "card.blocked.resolveIncident.label" })).toBeNull();
  });

  it("shows the cancel button only for the cleaning row when MANAGE_CLEANING_TASKS is held (R2.2)", () => {
    setRole("PROPERTY_MANAGER");
    setPermissions({ MANAGE_CLEANING_TASKS: true });
    const stalls: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-22T13:00:00Z",
        cleaning_task_id: "task-1",
      }),
      makeStall({
        property_id: "redes11",
        reservation_id: "r-2",
        trigger: "CHECKIN_WINDOW_OPENED",
        blocking_state: "MAINTENANCE_REQUIRED",
        due_since: "2026-08-21T13:00:00Z",
        incident_id: "incident-1",
      }),
    ];
    render(
      <BlockedTransitionsSection stalls={stalls} headingId="h" />,
      { wrapper: wrapper(new QueryClient()) },
    );
    expect(
      screen.getByRole("button", { name: "card.blocked.cancelCleaning.label" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "card.blocked.resolveIncident.label" }),
    ).toBeNull();
  });

  it("shows the resolve button only for the incident row when EXECUTE_INCIDENTS is held (R2.3)", () => {
    setRole("PROPERTY_MANAGER");
    setPermissions({ EXECUTE_INCIDENTS: true });
    const stalls: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-22T13:00:00Z",
        cleaning_task_id: "task-1",
      }),
      makeStall({
        property_id: "redes11",
        reservation_id: "r-2",
        trigger: "CHECKIN_WINDOW_OPENED",
        blocking_state: "MAINTENANCE_REQUIRED",
        due_since: "2026-08-21T13:00:00Z",
        incident_id: "incident-1",
      }),
    ];
    render(
      <BlockedTransitionsSection stalls={stalls} headingId="h" />,
      { wrapper: wrapper(new QueryClient()) },
    );
    expect(
      screen.getByRole("button", { name: "card.blocked.resolveIncident.label" }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "card.blocked.cancelCleaning.label" }),
    ).toBeNull();
  });

  it("does not show a cancel button when the stall has no cleaning_task_id (deploy-skew window)", () => {
    setRole("PROPERTY_MANAGER");
    useHasPermission.mockReturnValue(true);
    const stalls: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-22T13:00:00Z",
      }),
    ];
    render(
      <BlockedTransitionsSection stalls={stalls} headingId="h" />,
      { wrapper: wrapper(new QueryClient()) },
    );
    expect(
      screen.queryByRole("button", { name: "card.blocked.cancelCleaning.label" }),
    ).toBeNull();
  });

  it("paints trigger and blocking_state as canonical literals, no translation (R4.2, R4.3)", () => {
    setRole("PROPERTY_MANAGER");
    useHasPermission.mockReturnValue(false);
    const stalls: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-22T13:00:00Z",
      }),
    ];
    render(
      <BlockedTransitionsSection stalls={stalls} headingId="h" />,
      { wrapper: wrapper(new QueryClient()) },
    );
    expect(screen.getByText("CHECKIN_TIME_REACHED")).toBeTruthy();
    expect(screen.getByText("AWAITING_CLEANING")).toBeTruthy();
  });
});

describe("BlockedTransitionsSection — action wiring (R3.2)", () => {
  it("clicking cancel opens the dialog, confirming triggers the mutation", async () => {
    setRole("PROPERTY_MANAGER");
    setPermissions({ MANAGE_CLEANING_TASKS: true });
    cancelTask.mockImplementation(
      (
        _input: { taskId: string; reason: string },
        opts: { onSuccess?: () => void; onSettled?: () => void },
      ) => {
        opts.onSuccess?.();
        opts.onSettled?.();
      },
    );
    const stalls: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-1",
        trigger: "CHECKIN_TIME_REACHED",
        blocking_state: "AWAITING_CLEANING",
        due_since: "2026-08-22T13:00:00Z",
        cleaning_task_id: "task-1",
      }),
    ];
    render(
      <BlockedTransitionsSection stalls={stalls} headingId="h" />,
      { wrapper: wrapper(new QueryClient()) },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "card.blocked.cancelCleaning.label" }),
    );
    const submit = await waitFor(() =>
      screen.getByRole("button", {
        name: "card.blocked.cancelCleaning.dialog.confirm",
      }),
    );
    expect(submit.hasAttribute("disabled")).toBe(true);

    const textarea = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "guest arrived early" } });

    fireEvent.click(submit);

    await waitFor(() =>
      expect(cancelTask).toHaveBeenCalledWith(
        { taskId: "task-1", reason: "guest arrived early" },
        expect.any(Object),
      ),
    );
  });

  it("clicking resolve opens the dialog, confirming triggers the mutation", async () => {
    setRole("PROPERTY_MANAGER");
    setPermissions({ EXECUTE_INCIDENTS: true });
    resolveIncident.mockImplementation(
      (
        _input: { incidentId: string; finalCost: number | string },
        opts: { onSuccess?: () => void; onSettled?: () => void },
      ) => {
        opts.onSuccess?.();
        opts.onSettled?.();
      },
    );
    const stalls: BlockedTransitionSummary[] = [
      makeStall({
        property_id: "redes11",
        reservation_id: "r-2",
        trigger: "CHECKIN_WINDOW_OPENED",
        blocking_state: "MAINTENANCE_REQUIRED",
        due_since: "2026-08-21T13:00:00Z",
        incident_id: "incident-1",
      }),
    ];
    render(
      <BlockedTransitionsSection stalls={stalls} headingId="h" />,
      { wrapper: wrapper(new QueryClient()) },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "card.blocked.resolveIncident.label" }),
    );
    const submit = await waitFor(() =>
      screen.getByRole("button", {
        name: "card.blocked.resolveIncident.dialog.confirm",
      }),
    );
    expect(submit.hasAttribute("disabled")).toBe(true);

    const input = (await screen.findByLabelText(
      "card.blocked.resolveIncident.dialog.finalCost.label",
    )) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "12.50" } });

    fireEvent.click(submit);

    await waitFor(() =>
      expect(resolveIncident).toHaveBeenCalledWith(
        { incidentId: "incident-1", finalCost: "12.50" },
        expect.any(Object),
      ),
    );
  });

  // R3.2 invalidation is asserted end-to-end in `use-cancel-cleaning-task.test.tsx`
  // and `use-resolve-incident.test.tsx` — these tests cover the cache plumbing
  // against the real hook. Re-asserting it here with a mocked hook only proves
  // that the mocked hook does not invalidate, which is what mocking does.
});

/**
 * R5.3 at the component level: the stub in `dashboard-view.test.tsx` asserts
 * the flag travels; this asserts the real component honours it.
 */
describe("BlockedTransitionsSection — failed stalls query (R5.3)", () => {
  function renderSection(props: {
    stalls?: BlockedTransitionSummary[];
    hasError?: boolean;
  }) {
    setRole("PROPERTY_MANAGER");
    setPermissions({ MANAGE_CLEANING_TASKS: true, EXECUTE_INCIDENTS: true });
    return render(
      <BlockedTransitionsSection
        stalls={props.stalls ?? []}
        headingId="stalls-heading"
        hasError={props.hasError}
      />,
      { wrapper: wrapper(new QueryClient()) },
    );
  }

  it("renders the localized fetch error when hasError is true, even with no stalls", () => {
    renderSection({ hasError: true });
    expect(screen.getByRole("alert").textContent).toBe(
      "card.blocked.error.fetch",
    );
    // The section keeps its heading, so the card still names the region.
    expect(screen.getByText("card.blocked.title")).toBeTruthy();
  });

  it("renders nothing when there are no stalls and no error", () => {
    const { container } = renderSection({});
    expect(container.querySelector("section")).toBeNull();
  });

  it("does not paint action buttons in the error state", () => {
    renderSection({ hasError: true });
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("prefers the error over the rows when both are present", () => {
    // A refetch that fails while stale rows are still cached: the operator
    // must learn the list is not current rather than trust stale rows.
    renderSection({
      hasError: true,
      stalls: [
        makeStall({
          property_id: "redes11",
          reservation_id: "r1",
          trigger: "CHECKIN_TIME_REACHED",
          blocking_state: "AWAITING_CLEANING",
          due_since: "2026-08-20T09:30:00Z",
        }),
      ],
    });
    expect(screen.getByRole("alert").textContent).toBe(
      "card.blocked.error.fetch",
    );
    expect(screen.queryByText("CHECKIN_TIME_REACHED")).toBeNull();
  });
});


/**
 * Caught by the manual visual pass of task 7.4, not by any test: a single
 * wrapping row left the separator stranded at the end of a line whenever the
 * date wrapped away from the literals.
 */
describe("BlockedTransitionsSection — separators never trail a line", () => {
  function renderOne() {
    setRole("PROPERTY_MANAGER");
    setPermissions({ MANAGE_CLEANING_TASKS: true, EXECUTE_INCIDENTS: true });
    return render(
      <BlockedTransitionsSection
        headingId="h"
        stalls={[
          makeStall({
            property_id: "redes11",
            reservation_id: "r1",
            trigger: "CHECKIN_TIME_REACHED",
            blocking_state: "MAINTENANCE_REQUIRED",
            due_since: "2026-08-27T15:00:00Z",
            incident_id: "incident-1",
          }),
        ]}
      />,
      { wrapper: wrapper(new QueryClient()) },
    );
  }

  it("keeps every separator glued to the literal that follows it", () => {
    const { container } = renderOne();
    const separators = [...container.querySelectorAll('[aria-hidden="true"]')]
      .filter((el) => el.textContent?.trim() === "·");
    expect(separators.length).toBeGreaterThan(0);
    for (const sep of separators) {
      // The separator's own box must also contain the <code> it introduces,
      // so a line break can never strand it.
      expect(sep.parentElement?.querySelector("code")).toBeTruthy();
    }
  });

  it("puts the date in a different row from the literals", () => {
    const { container } = renderOne();
    const codeRow = container.querySelector("code")?.closest("div");
    const dateEl = [...container.querySelectorAll("span")].find((el) =>
      /2026/.test(el.textContent ?? ""),
    );
    expect(dateEl).toBeTruthy();
    expect(dateEl?.closest("div")).not.toBe(codeRow);
  });

  it("still renders both literals and the date", () => {
    renderOne();
    expect(screen.getByText("CHECKIN_TIME_REACHED")).toBeTruthy();
    expect(screen.getByText("MAINTENANCE_REQUIRED")).toBeTruthy();
    expect(screen.getByRole("button", { name: /resolveIncident/ })).toBeTruthy();
  });
});
