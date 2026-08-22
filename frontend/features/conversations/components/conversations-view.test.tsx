import { fireEvent } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import { useInboxFiltersStore } from "../state/use-inbox-filters-store";
import { ConversationsView } from "./conversations-view";

const replace = vi.hoisted(() => vi.fn());
const params = vi.hoisted(() => ({ current: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/conversations",
  useSearchParams: () => params.current,
}));

const session = vi.hoisted(() => ({
  current: { tenant_id: "tenant-1", id: "user-1", role: "PROPERTY_MANAGER" as string },
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: session.current }) }));

// The list, the filters and the thread each have their own suites; here they are
// stubbed so this one is about the master-detail wiring and nothing else.
vi.mock("./inbox-filters", () => ({
  InboxFilters: () => <div data-testid="filters" />,
}));
vi.mock("./inbox-list", () => ({
  InboxList: ({
    selectedId,
    onSelect,
  }: {
    selectedId: string | null;
    onSelect: (id: string) => void;
  }) => (
    <div data-testid="list" data-selected={selectedId ?? ""}>
      <button type="button" onClick={() => onSelect("conversation-7")}>
        pick
      </button>
    </div>
  ),
}));
// Counts **mounts**, not renders, so the keying below can be asserted by its
// observable consequence (a fresh component instance) instead of by inspecting a
// `key` attribute React never puts in the DOM.
const threadMounts = vi.hoisted(() => ({ ids: [] as string[] }));
vi.mock("./conversation-thread", async () => {
  const { useEffect, useRef } = await import("react");
  return {
    ConversationThread: ({
      conversationId,
      draft,
      onDraftChange,
      onDraftSent,
    }: {
      conversationId: string;
      draft: string;
      onDraftChange: (next: string) => void;
      onDraftSent: (sent: string) => void;
    }) => {
      // Mount-only on purpose: this counts component instances, which is the whole
      // assertion. Reading through a ref keeps the dependency list honestly empty
      // instead of re-firing on a prop change, which would make the guard pass even
      // with the `key` removed.
      const idRef = useRef(conversationId);
      useEffect(() => {
        threadMounts.ids.push(idRef.current);
      }, []);
      return (
        <div data-testid="thread" data-draft={draft}>
          {conversationId}
          <button
            type="button"
            onClick={() => onDraftChange(`borrador de ${conversationId}`)}
          >
            escribir
          </button>
          <button type="button" onClick={() => onDraftChange("editado")}>
            editar
          </button>
          <button
            type="button"
            onClick={() => onDraftSent(`borrador de ${conversationId}`)}
          >
            entregado
          </button>
        </div>
      );
    },
  };
});

function renderView() {
  return render(
    <I18nProvider locale="es">
      <ConversationsView />
    </I18nProvider>,
  );
}

beforeEach(() => {
  replace.mockReset();
  params.current = new URLSearchParams();
  session.current = { tenant_id: "tenant-1", id: "user-1", role: "PROPERTY_MANAGER" };
  useInboxFiltersStore.getState().reset();
  threadMounts.ids.length = 0;
});

describe("ConversationsView — selection lives in the URL (task 8.1, D5, R3.1)", () => {
  it("shows the inbox and no thread when the parameter is absent", () => {
    renderView();

    expect(screen.getByTestId("list")).toBeInTheDocument();
    expect(screen.queryByTestId("thread")).toBeNull();
    expect(
      screen.getByText("Ninguna conversación seleccionada"),
    ).toBeInTheDocument();
  });

  it("writes the selection to the query string without scrolling or pushing history", () => {
    renderView();
    fireEvent.click(screen.getByRole("button", { name: "pick" }));

    expect(replace).toHaveBeenCalledWith(
      "/conversations?conversation=conversation-7",
      { scroll: false },
    );
  });

  it("renders that conversation's thread on reload with the parameter present", () => {
    params.current = new URLSearchParams("conversation=conversation-42");
    renderView();

    expect(screen.getByTestId("thread")).toHaveTextContent("conversation-42");
    expect(screen.getByTestId("list")).toHaveAttribute(
      "data-selected",
      "conversation-42",
    );
    expect(
      screen.queryByText("Ninguna conversación seleccionada"),
    ).toBeNull();
  });

  it("keeps any other query parameter when it changes the selection", () => {
    params.current = new URLSearchParams("foo=bar");
    renderView();
    fireEvent.click(screen.getByRole("button", { name: "pick" }));

    expect(replace).toHaveBeenCalledWith(
      "/conversations?foo=bar&conversation=conversation-7",
      { scroll: false },
    );
  });

  it("drops the parameter entirely when the selection is cleared", () => {
    params.current = new URLSearchParams("conversation=conversation-42");
    renderView();
    fireEvent.click(screen.getByRole("button", { name: "Volver a la bandeja" }));

    expect(replace).toHaveBeenCalledWith("/conversations", { scroll: false });
  });
});

describe("ConversationsView — one column on a small screen (task 8.2, D19, R7.6)", () => {
  it("shows the list and hides the thread panel when nothing is selected", () => {
    renderView();

    const list = screen.getByLabelText("Bandeja");
    expect(list.className).toContain("flex");
    expect(list.className).not.toContain("hidden");

    const thread = screen.getByTestId("filters").parentElement!.nextElementSibling!;
    expect(thread.className).toContain("hidden");
    expect(thread.className).toContain("lg:flex");
  });

  it("hides the list and shows the thread when one is selected", () => {
    params.current = new URLSearchParams("conversation=conversation-42");
    renderView();

    const list = screen.getByLabelText("Bandeja");
    expect(list.className).toContain("hidden");
    expect(list.className).toContain("lg:flex");
    expect(screen.getByTestId("thread")).toBeInTheDocument();
  });

  it("offers the back control only below lg, and it is localized", () => {
    params.current = new URLSearchParams("conversation=conversation-42");
    renderView();

    const back = screen.getByRole("button", { name: "Volver a la bandeja" });
    expect(back.parentElement!.className).toContain("lg:hidden");
  });

  it("decides from state, never from the viewport", () => {
    // D19: no `matchMedia`, so the render is deterministic. jsdom does not even
    // implement it — a component that reached for it would throw here.
    expect(
      (window as unknown as { matchMedia?: unknown }).matchMedia,
    ).toBeUndefined();
    params.current = new URLSearchParams("conversation=conversation-42");
    expect(() => renderView()).not.toThrow();
  });
});

describe("ConversationsView — the filters belong to a tenant (task 8.1)", () => {
  it("clears them when the session's tenant changes", () => {
    renderView();
    useInboxFiltersStore.getState().setPropertyId("property-of-tenant-1");
    expect(useInboxFiltersStore.getState().propertyId).toBe(
      "property-of-tenant-1",
    );

    session.current = { tenant_id: "tenant-2", id: "user-2", role: "PROPERTY_MANAGER" };
    renderView();

    expect(useInboxFiltersStore.getState().propertyId).toBeUndefined();
    expect(useInboxFiltersStore.getState().page).toBe(1);
  });
});

describe("ConversationsView — the thread is keyed by conversation (review 2026-08-22)", () => {
  // Why this matters: selecting a cached conversation does not unmount the thread on
  // its own, and the send mutation's error state lives on the hook instance, so a
  // failure in one conversation was painting its banner over another's composer.
  // Only a fresh instance clears that; no render-time derivation reaches it.
  it("mounts a new thread instance when the selection changes", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    const { rerender } = renderView();
    expect(threadMounts.ids).toEqual(["conversation-1"]);

    params.current = new URLSearchParams("conversation=conversation-2");
    rerender(
      <I18nProvider locale="es">
        <ConversationsView />
      </I18nProvider>,
    );

    // Two mounts, not one mount plus a prop change: the second conversation gets a
    // component with no state inherited from the first.
    expect(threadMounts.ids).toEqual(["conversation-1", "conversation-2"]);
  });

  it("does not remount the thread when the selection is unchanged", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    const { rerender } = renderView();
    rerender(
      <I18nProvider locale="es">
        <ConversationsView />
      </I18nProvider>,
    );
    expect(threadMounts.ids).toEqual(["conversation-1"]);
  });
});

describe("ConversationsView — it owns the reply drafts (D22, R4.5)", () => {
  const thread = () => screen.getByTestId("thread");
  const type = () => fireEvent.click(screen.getByRole("button", { name: "escribir" }));
  const goTo = (id: string, rerender: (ui: ReactElement) => void) => {
    params.current = new URLSearchParams(`conversation=${id}`);
    rerender(
      <I18nProvider locale="es">
        <ConversationsView />
      </I18nProvider>,
    );
  };

  it("keeps each conversation's draft to itself", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    const { rerender } = renderView();
    type();
    expect(thread()).toHaveAttribute("data-draft", "borrador de conversation-1");

    goTo("conversation-2", rerender);
    // Not conversation-1's text: a draft under the wrong guest's id is one click
    // from a reply delivered to the wrong person.
    expect(thread()).toHaveAttribute("data-draft", "");
  });

  it("gives the draft back when the operator returns, which is what a failed send leaves behind", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    const { rerender } = renderView();
    type();

    goTo("conversation-2", rerender);
    goTo("conversation-1", rerender);

    // The thread subtree was remounted twice over (D22 keys it), so the mutation's own
    // error state is long gone. The surviving text is the only thing left that says the
    // reply was never sent — and its absence is what lets an empty composer mean
    // "delivered" again.
    expect(thread()).toHaveAttribute("data-draft", "borrador de conversation-1");
    expect(threadMounts.ids).toEqual([
      "conversation-1",
      "conversation-2",
      "conversation-1",
    ]);
  });

  it("drops every draft when the session's tenant changes", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    const { rerender } = renderView();
    type();
    expect(thread()).toHaveAttribute("data-draft", "borrador de conversation-1");

    // Guest-directed prose must not cross a tenant boundary, and a same-tab session
    // switch does not reload the page.
    session.current = { tenant_id: "tenant-2", id: "user-2", role: "PROPERTY_MANAGER" };
    rerender(
      <I18nProvider locale="es">
        <ConversationsView />
      </I18nProvider>,
    );
    expect(thread()).toHaveAttribute("data-draft", "");
  });
});

describe("ConversationsView — a draft belongs to the operator too (review 2026-08-22)", () => {
  const thread = () => screen.getByTestId("thread");
  const type = () => fireEvent.click(screen.getByRole("button", { name: "escribir" }));
  const rerenderView = (rerender: (ui: ReactElement) => void) =>
    rerender(
      <I18nProvider locale="es">
        <ConversationsView />
      </I18nProvider>,
    );

  // Two managers of the same tenant are a same-tenant, different-operator switch, and
  // handing Y the unsent prose X was writing to a guest is the same exposure as
  // crossing a tenant. Unreachable today only because `AuthGuard` unmounts this tree
  // while re-authenticating — this does not lean on that staying true.
  it("does not hand one operator's draft to another within the same tenant", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    const { rerender } = renderView();
    type();
    expect(thread()).toHaveAttribute("data-draft", "borrador de conversation-1");

    session.current = { tenant_id: "tenant-1", id: "user-2", role: "PROPERTY_MANAGER" };
    rerenderView(rerender);

    expect(thread()).toHaveAttribute("data-draft", "");
  });

  it("does not resurrect a draft when the original operator comes back", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    const { rerender } = renderView();
    type();

    session.current = { tenant_id: "tenant-1", id: "user-2", role: "PROPERTY_MANAGER" };
    rerenderView(rerender);
    // The second operator writes, which is what drops the first one's entries for good
    // rather than merely masking them behind the derivation.
    type();
    expect(thread()).toHaveAttribute("data-draft", "borrador de conversation-1");

    session.current = { tenant_id: "tenant-1", id: "user-1", role: "PROPERTY_MANAGER" };
    rerenderView(rerender);
    expect(thread()).toHaveAttribute("data-draft", "");
  });
});

describe("ConversationsView — retiring a draft only when it is still the delivered text", () => {
  const thread = () => screen.getByTestId("thread");
  const click = (name: string) => fireEvent.click(screen.getByRole("button", { name }));

  it("clears the draft when delivery matches what is still there", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    renderView();
    click("escribir");
    expect(thread()).toHaveAttribute("data-draft", "borrador de conversation-1");

    click("entregado");
    // Empty again, so an empty composer means "delivered" rather than "unknown".
    expect(thread()).toHaveAttribute("data-draft", "");
  });

  it("keeps a draft the operator has edited since sending", () => {
    params.current = new URLSearchParams("conversation=conversation-1");
    renderView();
    click("escribir");
    click("editar");
    expect(thread()).toHaveAttribute("data-draft", "editado");

    // The send that is now landing carried the *earlier* text. Clearing here would
    // discard the operator's new version with no signal at all.
    click("entregado");
    expect(thread()).toHaveAttribute("data-draft", "editado");
  });
});
