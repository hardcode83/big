import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { fireEvent, render, screen, waitFor } from "@/test/render";
import esReservations from "@/locales/es/reservations.json";

import * as dataModule from "../../data";
import { GuestPortalLinkCard } from "./guest-portal-link-card";

const useAuth = vi.hoisted(() => vi.fn());
const useHasPermission = vi.hoisted(() => vi.fn());
vi.mock("@/lib/auth", () => ({ useAuth, useHasPermission }));

const getGuestAccessTokenStatus = vi.fn();
const issueGuestAccessToken = vi.fn();
const revokeGuestAccessToken = vi.fn();
const sendGuestAccessTokenEmail = vi.fn();

vi.spyOn(dataModule, "getReservationsDataSource").mockImplementation(
  () =>
    ({
      getGuestAccessTokenStatus,
      issueGuestAccessToken,
      revokeGuestAccessToken,
      sendGuestAccessTokenEmail,
    }) as unknown as ReturnType<typeof dataModule.getReservationsDataSource>,
);

const strings = esReservations.guestPortalLink;

function makeClient(): QueryClient {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function wrapperFor(client: QueryClient) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
  };
}

function renderCard(client: QueryClient, reservationId = "reservation-1") {
  return render(<GuestPortalLinkCard reservationId={reservationId} />, {
    wrapper: wrapperFor(client),
  });
}

beforeEach(() => {
  useAuth.mockReturnValue({
    user: { tenant_id: "tenant-1", role: "PROPERTY_MANAGER" },
  });
  useHasPermission.mockReturnValue(true);
  getGuestAccessTokenStatus.mockReset().mockResolvedValue({
    isLive: false,
    issuedAt: null,
  });
  issueGuestAccessToken.mockReset();
  revokeGuestAccessToken.mockReset();
  sendGuestAccessTokenEmail.mockReset();
  Object.assign(navigator, {
    clipboard: { writeText: vi.fn().mockResolvedValue(undefined) },
  });
});

describe("GuestPortalLinkCard (R1, R3, design D7)", () => {
  it("renders nothing without MANAGE_GUEST_ACCESS_TOKENS, and never fetches status (R1.4)", () => {
    useHasPermission.mockReturnValue(false);
    const { container } = renderCard(makeClient());
    expect(container.firstChild).toBeNull();
    expect(getGuestAccessTokenStatus).not.toHaveBeenCalled();
  });

  it("shows 'no live token' status when none exists (R1.1)", async () => {
    renderCard(makeClient());
    await waitFor(() =>
      expect(screen.getByText(strings.status.none)).toBeInTheDocument(),
    );
  });

  it("shows the live status with its issuance instant, without exposing the token (R1.1)", async () => {
    getGuestAccessTokenStatus.mockResolvedValue({
      isLive: true,
      issuedAt: "2026-09-01T09:00:00Z",
    });
    renderCard(makeClient());
    await waitFor(() =>
      expect(screen.getByText(/2026-09-01T09:00:00Z/)).toBeInTheDocument(),
    );
    expect(screen.queryByText(/token/i)).not.toBeInTheDocument();
  });

  it("reveals a minted token as the full portal URL exactly once, in a copy-to-clipboard control with a persistent warning (R1.2)", async () => {
    issueGuestAccessToken.mockResolvedValue("clear-token-abc");
    renderCard(makeClient());

    fireEvent.click(
      await screen.findByRole("button", { name: strings.actions.mint }),
    );

    const portalUrl = `${window.location.origin}/guest/clear-token-abc`;
    await waitFor(() =>
      expect(screen.getByText(portalUrl)).toBeInTheDocument(),
    );
    expect(screen.getByText(strings.reveal.warning)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: strings.reveal.copy }));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(portalUrl),
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: strings.reveal.copied }),
      ).toBeInTheDocument(),
    );
  });

  it("never re-displays the minted token's URL after the component unmounts and remounts (R1.2)", async () => {
    issueGuestAccessToken.mockResolvedValue("clear-token-abc");
    const client = makeClient();
    const { unmount } = renderCard(client);

    fireEvent.click(
      await screen.findByRole("button", { name: strings.actions.mint }),
    );
    const portalUrl = `${window.location.origin}/guest/clear-token-abc`;
    await waitFor(() =>
      expect(screen.getByText(portalUrl)).toBeInTheDocument(),
    );

    unmount();
    // Same QueryClient (the app's module-level MutationCache), a fresh mount —
    // `gcTime: 0` on `useIssueGuestAccessToken` is what guarantees the
    // previous mutation (and its cleartext `data`) is gone by the time this
    // second render observes the cache.
    renderCard(client);

    await waitFor(() =>
      expect(screen.getByText(strings.status.none)).toBeInTheDocument(),
    );
    expect(screen.queryByText(portalUrl)).not.toBeInTheDocument();
  });

  it("disables the mint button while its own mutation is pending (R1.5)", async () => {
    let resolveIssue!: (value: string) => void;
    issueGuestAccessToken.mockReturnValue(
      new Promise<string>((resolve) => {
        resolveIssue = resolve;
      }),
    );
    renderCard(makeClient());

    const mintButton = await screen.findByRole("button", {
      name: strings.actions.mint,
    });
    fireEvent.click(mintButton);

    await waitFor(() => expect(mintButton).toBeDisabled());
    resolveIssue("clear-token-xyz");
    await waitFor(() => expect(mintButton).not.toBeDisabled());
  });

  it("disables the revoke button while its own mutation is pending, independently of mint (R1.5)", async () => {
    let resolveRevoke!: () => void;
    revokeGuestAccessToken.mockReturnValue(
      new Promise<void>((resolve) => {
        resolveRevoke = resolve;
      }),
    );
    renderCard(makeClient());

    const revokeButton = await screen.findByRole("button", {
      name: strings.actions.revoke,
    });
    const mintButton = screen.getByRole("button", { name: strings.actions.mint });
    fireEvent.click(revokeButton);

    await waitFor(() => expect(revokeButton).toBeDisabled());
    expect(mintButton).not.toBeDisabled();
    resolveRevoke();
    await waitFor(() => expect(revokeButton).not.toBeDisabled());
  });

  it("updates the visible status to 'no live token' after revoke, without a reload (R1.3)", async () => {
    getGuestAccessTokenStatus
      .mockResolvedValueOnce({ isLive: true, issuedAt: "2026-09-01T09:00:00Z" })
      .mockResolvedValueOnce({ isLive: false, issuedAt: null });
    revokeGuestAccessToken.mockResolvedValue(undefined);
    renderCard(makeClient());

    await waitFor(() =>
      expect(screen.getByText(/2026-09-01T09:00:00Z/)).toBeInTheDocument(),
    );
    fireEvent.click(
      screen.getByRole("button", { name: strings.actions.revoke }),
    );

    await waitFor(() =>
      expect(screen.getByText(strings.status.none)).toBeInTheDocument(),
    );
  });

  it("surfaces delivered: true as inline feedback after send (R3.5)", async () => {
    sendGuestAccessTokenEmail.mockResolvedValue(true);
    renderCard(makeClient());

    fireEvent.click(
      await screen.findByRole("button", { name: strings.actions.send }),
    );

    await waitFor(() =>
      expect(screen.getByText(strings.feedback.delivered)).toBeInTheDocument(),
    );
  });

  it("surfaces delivered: false distinctly from a rejection (R3.5)", async () => {
    sendGuestAccessTokenEmail.mockResolvedValue(false);
    renderCard(makeClient());

    fireEvent.click(
      await screen.findByRole("button", { name: strings.actions.send }),
    );

    await waitFor(() =>
      expect(
        screen.getByText(strings.feedback.notDelivered),
      ).toBeInTheDocument(),
    );
  });
});
