import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { renderHook, waitFor } from "@/test/render";
import { ApiError } from "@/lib/api";

const source = vi.hoisted(() => ({
  getConversation: vi.fn(),
  postMessage: vi.fn(),
}));

vi.mock("@/features/guest-portal/data", () => ({
  getGuestPortalDataSource: () => source,
}));

import { PORTAL_THREAD_POLL_MS, useConversation, usePostMessage } from "./use-conversation";
import { guestKeys } from "./query-keys";

const TOKEN = "opaque-secret-token-2f9a";

const THREAD = {
  items: [
    { id: "m1", sender: "GUEST" as const, content: "Hola", createdAt: "2026-08-30T10:00:00Z" },
  ],
  total: 1,
  page: 1,
  perPage: 50,
  state: "AUTOMATIC" as const,
};

function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { value: state, configurable: true });
  document.dispatchEvent(new Event("visibilitychange"));
}

function wrap() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
}

beforeEach(() => {
  vi.clearAllMocks();
  setVisibility("visible");
  source.getConversation.mockResolvedValue(THREAD);
  source.postMessage.mockResolvedValue(THREAD.items[0]);
});

afterEach(() => {
  vi.useRealTimers();
  setVisibility("visible");
});

describe("useConversation polling (R5.3, design D10)", () => {
  it("re-fetches the thread on the documented interval while the tab is visible", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { wrapper } = wrap();

    renderHook(() => useConversation(TOKEN), { wrapper });
    await waitFor(() => expect(source.getConversation).toHaveBeenCalledTimes(1));

    await vi.advanceTimersByTimeAsync(PORTAL_THREAD_POLL_MS);
    await waitFor(() => expect(source.getConversation).toHaveBeenCalledTimes(2));

    await vi.advanceTimersByTimeAsync(PORTAL_THREAD_POLL_MS);
    await waitFor(() => expect(source.getConversation).toHaveBeenCalledTimes(3));
  });

  /**
   * R5.3's second half, and the reason the hook passes `refetchIntervalInBackground: false`
   * explicitly rather than relying on the default: a guarantee nobody can see in the code is
   * one nobody can check. Hiding the tab here is what turns it from a default into a pinned
   * behaviour — if a later edit set the flag to `true`, this goes red.
   */
  it("stops polling once the tab is hidden", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { wrapper } = wrap();

    renderHook(() => useConversation(TOKEN), { wrapper });
    await waitFor(() => expect(source.getConversation).toHaveBeenCalledTimes(1));

    setVisibility("hidden");
    // Wait for the event to have actually reached TanStack Query before snapshotting the call
    // count. Without this the assertion races the in-flight interval: the CI/CD panel of
    // sections 9-10 reproduced it failing roughly once in eleven runs under load, with polling
    // observed continuing because the snapshot was taken before `focusManager` had processed
    // the `visibilitychange`. Waiting on the observable state makes the test about the wiring
    // (does hiding the tab stop the polling?) rather than about who wins a race.
    await waitFor(() => expect(focusManager.isFocused()).toBe(false));
    const callsWhenHidden = source.getConversation.mock.calls.length;

    await vi.advanceTimersByTimeAsync(PORTAL_THREAD_POLL_MS * 4);

    expect(source.getConversation).toHaveBeenCalledTimes(callsWhenHidden);
  });

  it("asks for no particular page, so the backend answers the most recent window", async () => {
    const { wrapper } = wrap();

    renderHook(() => useConversation(TOKEN), { wrapper });

    await waitFor(() => expect(source.getConversation).toHaveBeenCalledTimes(1));
    expect(source.getConversation).toHaveBeenCalledWith(TOKEN);
  });

  it("polls at a rate the shared per-token budget can afford", () => {
    // 60 requests/minute is one budget for all six portal routes, and opening the page already
    // spends two of them. Four a minute leaves room for several tabs on the same link; this
    // assertion is what makes a later edit to the constant a deliberate act.
    expect(60_000 / PORTAL_THREAD_POLL_MS).toBeLessThanOrEqual(4);
  });
});

describe("usePostMessage (R5.4, R5.8)", () => {
  it("does not retry a 429 — the message may well have been received", async () => {
    source.postMessage.mockRejectedValue(
      new ApiError({ code: "RATE_LIMITED", message: "Too many requests", status: 429, details: {} }),
    );
    const { wrapper } = wrap();

    const { result } = renderHook(() => usePostMessage(TOKEN), { wrapper });
    result.current.mutate({ content: "Hola" });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(source.postMessage).toHaveBeenCalledTimes(1);
  });

  it("re-reads the thread after a send, which is what shows the automatic reply", async () => {
    const { client, wrapper } = wrap();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    const { result } = renderHook(() => usePostMessage(TOKEN), { wrapper });
    result.current.mutate({ content: "Hola" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidate).toHaveBeenCalledWith({ queryKey: guestKeys.conversation(TOKEN) });
  });

  it("sends only the content, never a sender the caller could claim", async () => {
    const { wrapper } = wrap();

    const { result } = renderHook(() => usePostMessage(TOKEN), { wrapper });
    result.current.mutate({ content: "Hola" });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(source.postMessage).toHaveBeenCalledWith(TOKEN, { content: "Hola" });
  });
});
