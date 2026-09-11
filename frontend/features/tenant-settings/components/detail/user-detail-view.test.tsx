import { describe, expect, it, vi } from "vitest";

import { render, screen } from "@/test/render";

const useUserMock = vi.hoisted(() => vi.fn());
vi.mock("../../hooks/use-user", () => ({
  useUser: useUserMock,
}));

import { UserDetailView } from "./user-detail-view";

const INACTIVE_USER = {
  id: "user-1",
  name: "Marta Cleaner",
  email: "marta@example.com",
  phone: "+34123456789",
  preferredLanguage: "es",
  role: "CLEANER",
  status: "INACTIVE",
  lastLoginAt: null,
  createdAt: "2026-08-01T09:00:00Z",
  updatedAt: "2026-08-01T09:00:00Z",
};

describe("UserDetailView (R1.3)", () => {
  it("shows the loading state", () => {
    useUserMock.mockReturnValue({ isPending: true, isError: false, data: undefined, refetch: vi.fn() });
    render(<UserDetailView userId="user-1" />);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows the error state", () => {
    useUserMock.mockReturnValue({ isPending: false, isError: true, data: undefined, refetch: vi.fn() });
    render(<UserDetailView userId="user-1" />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  it("renders an INACTIVE user's full detail, not hidden or specially cased", () => {
    useUserMock.mockReturnValue({ isPending: false, isError: false, data: INACTIVE_USER, refetch: vi.fn() });
    render(<UserDetailView userId="user-1" />);

    expect(screen.getByText("Marta Cleaner")).toBeInTheDocument();
    expect(screen.getByText("marta@example.com")).toBeInTheDocument();
    expect(screen.getByText("+34123456789")).toBeInTheDocument();
    expect(screen.getByText("CLEANER")).toBeInTheDocument();
    expect(screen.getByText("INACTIVE")).toBeInTheDocument();
  });
});
