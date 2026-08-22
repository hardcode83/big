import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { ConversationsDataSource } from "../data/conversations-source";
import { conversationKeys } from "./query-keys";
import {
  useEscalate,
  useResolve,
  useSendReply,
  useTranscribeGuestMessage,
} from "./use-conversation-actions";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-from-session" } }),
}));

const source = vi.hoisted(() => ({
  listConversations: vi.fn(),
  getConversation: vi.fn(),
  listMessages: vi.fn(),
  createMessage: vi.fn(),
  escalate: vi.fn(),
  resolve: vi.fn(),
  listPropertyLabels: vi.fn(),
}));

vi.mock("../data", () => ({
  getConversationsDataSource: () => source as unknown as ConversationsDataSource,
}));

const TENANT = "tenant-from-session";
const CONVERSATION = "conversation-1";

function harness() {
  const client = new QueryClient();
  const invalidateQueries = vi.spyOn(client, "invalidateQueries");
  const clear = vi.spyOn(client, "clear");
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { Wrapper, invalidateQueries, clear };
}

interface CallRecorder {
  mock: { calls: unknown[][] };
}

function invalidatedKeys(spy: CallRecorder): string[] {
  return spy.mock.calls.map((call) =>
    JSON.stringify((call[0] as { queryKey: unknown }).queryKey),
  );
}

beforeEach(() => {
  for (const fn of Object.values(source)) {
    fn.mockReset();
  }
});

interface Action {
  mutate: () => void;
  isSuccess: boolean;
}

async function expectFullInvalidation(useAction: () => Action) {
  source.createMessage.mockResolvedValue({ id: "message-1" });
  source.escalate.mockResolvedValue({ id: CONVERSATION });
  source.resolve.mockResolvedValue({ id: CONVERSATION });

  const { Wrapper, invalidateQueries, clear } = harness();
  const { result } = renderHook(useAction, { wrapper: Wrapper });

  result.current.mutate();
  await waitFor(() => expect(result.current.isSuccess).toBe(true));

  const keys = invalidatedKeys(invalidateQueries);
  expect(keys).toContain(JSON.stringify(conversationKeys.listPrefix(TENANT)));
  expect(keys).toContain(
    JSON.stringify(conversationKeys.messagesPrefix(TENANT, CONVERSATION)),
  );
  expect(keys).toContain(
    JSON.stringify(conversationKeys.detail(TENANT, CONVERSATION)),
  );
  expect(clear).not.toHaveBeenCalled();
}

describe("write hooks invalidate list, thread and detail (task 4.4, D16, R4.4, R5.3)", () => {
  it("does it after a successful reply", async () => {
    await expectFullInvalidation(() => {
      const reply = useSendReply(CONVERSATION);
      return { mutate: () => reply.mutate("hola"), isSuccess: reply.isSuccess };
    });
  });

  it("does it after a successful transcription", async () => {
    await expectFullInvalidation(() => {
      const transcribe = useTranscribeGuestMessage(CONVERSATION);
      return {
        mutate: () => transcribe.mutate("hola"),
        isSuccess: transcribe.isSuccess,
      };
    });
  });

  it("does it after a successful escalation", async () => {
    await expectFullInvalidation(() => useEscalate(CONVERSATION));
  });

  it("does it after a successful resolution", async () => {
    await expectFullInvalidation(() => useResolve(CONVERSATION));
  });

  it("invalidates the detail by exact key and the other two by prefix", async () => {
    source.escalate.mockResolvedValue({ id: CONVERSATION });
    const { Wrapper, invalidateQueries } = harness();
    const { result } = renderHook(() => useEscalate(CONVERSATION), {
      wrapper: Wrapper,
    });

    result.current.mutate();
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    const byKey = new Map(
      invalidateQueries.mock.calls.map((call) => {
        const filters = call[0] as { queryKey: unknown; exact?: boolean };
        return [JSON.stringify(filters.queryKey), filters.exact];
      }),
    );
    expect(
      byKey.get(JSON.stringify(conversationKeys.detail(TENANT, CONVERSATION))),
    ).toBe(true);
    expect(byKey.get(JSON.stringify(conversationKeys.listPrefix(TENANT)))).toBe(
      undefined,
    );
    expect(
      byKey.get(
        JSON.stringify(conversationKeys.messagesPrefix(TENANT, CONVERSATION)),
      ),
    ).toBe(undefined);
  });

  it("never paints the outcome before the server computes it (D16: no optimistic update)", async () => {
    let release: (value: unknown) => void = () => {};
    source.resolve.mockImplementation(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    );

    const client = new QueryClient();
    const detailKey = conversationKeys.detail(TENANT, CONVERSATION);
    const serverState = {
      id: CONVERSATION,
      status: "OPEN",
      escalationStatus: "PENDING_HUMAN",
    };
    client.setQueryData(detailKey, serverState);

    function Wrapper({ children }: { children: ReactNode }) {
      return (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      );
    }
    const { result } = renderHook(() => useResolve(CONVERSATION), {
      wrapper: Wrapper,
    });

    result.current.mutate();
    await waitFor(() => expect(result.current.isPending).toBe(true));

    // In flight: both axes still say what the server last said, not what the
    // action asked for. An `onMutate` that wrote the expected result would fail
    // here — which is the whole point of D16 rejecting optimistic updates.
    expect(client.getQueryData(detailKey)).toEqual(serverState);

    release({
      id: CONVERSATION,
      status: "RESOLVED",
      escalationStatus: "RESOLVED",
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));

    // And on success it invalidates rather than writing the response into the
    // cache itself: with no active observer, an invalidated query keeps its old
    // value, so a direct `setQueryData` would show up as the new one.
    expect(client.getQueryData(detailKey)).toEqual(serverState);
  });

  it("invalidates nothing when the write fails for a reason that teaches nothing", async () => {
    source.resolve.mockRejectedValue(
      new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
    );
    const { Wrapper, invalidateQueries } = harness();
    const { result } = renderHook(() => useResolve(CONVERSATION), {
      wrapper: Wrapper,
    });

    result.current.mutate();
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidateQueries).not.toHaveBeenCalled();
  });

  it("refreshes the real state after a 409, so the UI stops offering it (D18, R5.2)", async () => {
    source.resolve.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "already resolved", status: 409 }),
    );
    const { Wrapper, invalidateQueries } = harness();
    const { result } = renderHook(() => useResolve(CONVERSATION), {
      wrapper: Wrapper,
    });

    result.current.mutate();
    await waitFor(() => expect(result.current.isError).toBe(true));

    const keys = invalidatedKeys(invalidateQueries);
    expect(keys).toContain(JSON.stringify(conversationKeys.listPrefix(TENANT)));
    expect(keys).toContain(
      JSON.stringify(conversationKeys.messagesPrefix(TENANT, CONVERSATION)),
    );
    expect(keys).toContain(
      JSON.stringify(conversationKeys.detail(TENANT, CONVERSATION)),
    );
  });

  it("refreshes after a 409 on escalate too", async () => {
    source.escalate.mockRejectedValue(
      new ApiError({ code: "CONFLICT", message: "already escalated", status: 409 }),
    );
    const { Wrapper, invalidateQueries } = harness();
    const { result } = renderHook(() => useEscalate(CONVERSATION), {
      wrapper: Wrapper,
    });

    result.current.mutate();
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(invalidatedKeys(invalidateQueries)).toContain(
      JSON.stringify(conversationKeys.detail(TENANT, CONVERSATION)),
    );
  });
});

describe("write hooks send the right body and never retry (task 4.4, R4.1, R4.2)", () => {
  it("replies without sender_type", async () => {
    source.createMessage.mockResolvedValue({ id: "message-1" });
    const { Wrapper } = harness();
    const { result } = renderHook(() => useSendReply(CONVERSATION), {
      wrapper: Wrapper,
    });

    result.current.mutate("Vamos a mirarlo");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(source.createMessage).toHaveBeenCalledWith(TENANT, CONVERSATION, {
      content: "Vamos a mirarlo",
    });
  });

  it("transcribes with sender_type GUEST", async () => {
    source.createMessage.mockResolvedValue({ id: "message-1" });
    const { Wrapper } = harness();
    const { result } = renderHook(
      () => useTranscribeGuestMessage(CONVERSATION),
      { wrapper: Wrapper },
    );

    result.current.mutate("No hay agua caliente");
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(source.createMessage).toHaveBeenCalledWith(TENANT, CONVERSATION, {
      content: "No hay agua caliente",
      senderType: "GUEST",
    });
  });

  it("does not retry a failed write, so the AI pipeline never runs twice", async () => {
    source.createMessage.mockRejectedValue(
      new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
    );
    const { Wrapper } = harness();
    const { result } = renderHook(
      () => useTranscribeGuestMessage(CONVERSATION),
      { wrapper: Wrapper },
    );

    result.current.mutate("No hay agua caliente");
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(source.createMessage).toHaveBeenCalledTimes(1);
  });
});

describe("useSendReply — retiring the draft survives the caller (D22, review 2026-08-22)", () => {
  // The composer lives inside a subtree keyed per conversation, so switching threads
  // while a reply is in flight unsubscribes its observer — and React Query then drops
  // any `mutate(…, { onSuccess })` callback. `onSent` therefore has to live in the
  // mutation's own options, or a success landing after the switch leaves the sent text
  // in the composer and the next click sends the guest a duplicate.
  it("calls onSent on success with no mutate-level callback in sight", async () => {
    const { Wrapper } = harness();
    source.createMessage.mockResolvedValue({ id: "message-1" });
    const onSent = vi.fn();
    const { result } = renderHook(() => useSendReply(CONVERSATION, { onSent }), {
      wrapper: Wrapper,
    });

    // Deliberately no second argument: this is the path the observer would discard.
    result.current.mutate("Vamos a mirarlo");

    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(1));
  });

  it("does not call onSent when the send fails", async () => {
    const { Wrapper } = harness();
    source.createMessage.mockRejectedValue(
      new ApiError({ code: "SERVER_ERROR", message: "boom", status: 500 }),
    );
    const onSent = vi.fn();
    const { result } = renderHook(() => useSendReply(CONVERSATION, { onSent }), {
      wrapper: Wrapper,
    });

    result.current.mutate("no se ha enviado");

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(onSent).not.toHaveBeenCalled();
  });

  it("still works for a caller that passes no options at all", async () => {
    const { Wrapper, invalidateQueries } = harness();
    source.createMessage.mockResolvedValue({ id: "message-1" });
    const { result } = renderHook(() => useSendReply(CONVERSATION), {
      wrapper: Wrapper,
    });

    result.current.mutate("hola");

    await waitFor(() => expect(invalidateQueries).toHaveBeenCalled());
    expect(invalidatedKeys(invalidateQueries as unknown as CallRecorder)).toContain(
      JSON.stringify(conversationKeys.detail(TENANT, CONVERSATION)),
    );
  });
});

describe("useSendReply — an in-flight reply is visible after a remount (D22)", () => {
  // The composer lives in a subtree keyed per conversation, so leaving the thread and
  // coming back gives a brand-new `useMutation` whose `isPending` is false while the
  // first request is still travelling. Reading that would let the operator send the
  // guest a second copy, so the flag comes from the mutation cache instead.
  it("still reports in-flight from a fresh hook instance", async () => {
    const { Wrapper } = harness();
    let settle: (value: unknown) => void = () => undefined;
    source.createMessage.mockImplementation(
      () => new Promise((resolve) => {
        settle = resolve;
      }),
    );

    const first = renderHook(() => useSendReply(CONVERSATION), { wrapper: Wrapper });
    first.result.current.mutate("Vamos a mirarlo");
    await waitFor(() => expect(first.result.current.isInFlight).toBe(true));

    // The operator leaves the thread: the keyed subtree unmounts.
    first.unmount();

    // ...and comes back to a fresh instance, with the request still travelling.
    const second = renderHook(() => useSendReply(CONVERSATION), { wrapper: Wrapper });
    expect(second.result.current.isPending).toBe(false);
    expect(second.result.current.isInFlight).toBe(true);

    settle({ id: "message-1" });
    await waitFor(() => expect(second.result.current.isInFlight).toBe(false));
  });

  it("does not report another conversation's send as in flight", async () => {
    const { Wrapper } = harness();
    source.createMessage.mockImplementation(() => new Promise(() => undefined));
    const mine = renderHook(() => useSendReply(CONVERSATION), { wrapper: Wrapper });
    mine.result.current.mutate("para esta");
    await waitFor(() => expect(mine.result.current.isInFlight).toBe(true));

    const other = renderHook(() => useSendReply("conversation-2"), { wrapper: Wrapper });
    expect(other.result.current.isInFlight).toBe(false);
  });
});
