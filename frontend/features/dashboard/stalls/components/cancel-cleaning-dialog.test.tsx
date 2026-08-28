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

import { CancelCleaningDialog } from "./cancel-cleaning-dialog";

const mutate = vi.hoisted(() => vi.fn());

/**
 * Mutable so a test can put the hook into its error state. The dialog reads
 * `isError` and `error`; nothing else of the mutation result reaches it.
 */
const mutationState = vi.hoisted(() => ({
  isPending: false,
  isError: false,
  error: null as unknown,
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));

vi.mock("@/features/cleaning", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/features/cleaning")>()),
  useCancelCleaningTask: () => ({
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
    <CancelCleaningDialog
      open
      onOpenChange={() => {}}
      taskId="task-1"
      trigger="CHECKIN_TIME_REACHED"
      blockingState="AWAITING_CLEANING"
    />,
    { wrapper: wrapper() },
  );
}

describe("CancelCleaningDialog — error mapping (R3.3, R3.4)", () => {
  it("submits exactly once when the reason is non-empty, and never retries", async () => {
    mutate.mockImplementation(() => {
      // resolve synchronously
    });
    render(
      <CancelCleaningDialog
        open
        onOpenChange={() => {}}
        taskId="task-1"
        trigger="CHECKIN_TIME_REACHED"
        blockingState="AWAITING_CLEANING"
      />,
      { wrapper: wrapper() },
    );
    const textarea = await screen.findByRole("textbox");
    fireEvent.change(textarea, { target: { value: "guest arrived early" } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.cancelCleaning.dialog.confirm",
    });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(mutate).toHaveBeenCalledWith(
        { taskId: "task-1", reason: "guest arrived early" },
        expect.any(Object),
      ),
    );
    expect(mutate).toHaveBeenCalledTimes(1);
  });

  it("does not submit when the reason is whitespace-only", async () => {
    render(
      <CancelCleaningDialog
        open
        onOpenChange={() => {}}
        taskId="task-1"
        trigger="CHECKIN_TIME_REACHED"
        blockingState="AWAITING_CLEANING"
      />,
      { wrapper: wrapper() },
    );
    const textarea = await screen.findByRole("textbox");
    fireEvent.change(textarea, { target: { value: "   " } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.cancelCleaning.dialog.confirm",
    });
    expect(submit.hasAttribute("disabled")).toBe(true);
    fireEvent.click(submit);
    expect(mutate).not.toHaveBeenCalled();
  });

  it("does not submit when the reason exceeds 500 chars", async () => {
    render(
      <CancelCleaningDialog
        open
        onOpenChange={() => {}}
        taskId="task-1"
        trigger="CHECKIN_TIME_REACHED"
        blockingState="AWAITING_CLEANING"
      />,
      { wrapper: wrapper() },
    );
    const textarea = await screen.findByRole("textbox") as HTMLTextAreaElement;
    // The textarea hard-caps with `maxLength`; a 501-char input is impossible
    // through the UI itself. Simulate the bypass: a controlled input with more
    // than 500 chars via direct value set.
    fireEvent.change(textarea, { target: { value: "x".repeat(501) } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.cancelCleaning.dialog.confirm",
    });
    expect(submit.hasAttribute("disabled")).toBe(true);
  });
});

describe("CancelCleaningDialog — 409 / 4xx / 5xx (R3.3, R3.4)", () => {
  it("the mutation hook is configured retry:false — exactly one attempt per click", async () => {
    let calls = 0;
    mutate.mockImplementation(() => {
      calls += 1;
    });
    render(
      <CancelCleaningDialog
        open
        onOpenChange={() => {}}
        taskId="task-1"
        trigger="CHECKIN_TIME_REACHED"
        blockingState="AWAITING_CLEANING"
      />,
      { wrapper: wrapper() },
    );
    const textarea = await screen.findByRole("textbox");
    fireEvent.change(textarea, { target: { value: "guest arrived early" } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.cancelCleaning.dialog.confirm",
    });
    fireEvent.click(submit);
    await waitFor(() => expect(calls).toBe(1));
    // No retry: the dialog's `retry: false` is wired at the hook level, not
    // visible from a mocked mutate. End-to-end retry semantics are covered by
    // `use-cancel-cleaning-task.test.tsx` (R3.4 — `expect(cancelTask).toHaveBeenCalledTimes(1)`).
  });
});

/**
 * BLOCKED #5: the hook-level invalidation was tested, but nothing asserted
 * that the dialog actually paints an error and stays open. A future change
 * that closed the dialog in `onError` would have shipped green.
 */
describe("CancelCleaningDialog — the error is visible and the dialog stays open (R3.3)", () => {
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
      "card.blocked.cancelCleaning.dialog.error.generic",
    );
    // The form is still mounted — the user can retry or dismiss.
    expect(screen.getByRole("textbox")).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: "card.blocked.cancelCleaning.dialog.confirm",
      }),
    ).toBeTruthy();
  });

  it("renders the conflict copy on a 409, not the generic one (R3.4)", async () => {
    mutationState.isError = true;
    mutationState.error = new ApiError({
      code: "CLEANING_CANCEL_NOT_ALLOWED",
      message: "guest still in flat",
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
      code: "CLEANING_CANCEL_NOT_ALLOWED",
      message: "guest still in flat",
      status: 409,
    });
    const { container } = renderDialog();
    expect(container.textContent).not.toContain("guest still in flat");
  });
});

describe("CancelCleaningDialog — double submit (L1)", () => {
  it("dispatches one mutation for two clicks in the same frame", async () => {
    renderDialog();
    const textarea = await screen.findByRole("textbox");
    fireEvent.change(textarea, { target: { value: "guest arrived early" } });
    const submit = screen.getByRole("button", {
      name: "card.blocked.cancelCleaning.dialog.confirm",
    });

    // Two clicks before React can commit `isPending: true`.
    fireEvent.click(submit);
    fireEvent.click(submit);

    await waitFor(() => expect(mutate).toHaveBeenCalledTimes(1));
  });
});
