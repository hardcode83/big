import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ROLE_UI_PERMISSIONS, useHasPermission } from "./permissions";

const useAuth = vi.hoisted(() => vi.fn());
vi.mock("./auth-provider", () => ({ useAuth }));

describe("useHasPermission (R4.3)", () => {
  it("grants MANAGE_CLEANING_TASKS to PROPERTY_MANAGER", () => {
    useAuth.mockReturnValue({ user: { role: "PROPERTY_MANAGER" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CLEANING_TASKS"),
    );
    expect(result.current).toBe(true);
  });

  it("denies MANAGE_CLEANING_TASKS to TENANT_OWNER", () => {
    useAuth.mockReturnValue({ user: { role: "TENANT_OWNER" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CLEANING_TASKS"),
    );
    expect(result.current).toBe(false);
  });

  it("denies everything without an authenticated user", () => {
    useAuth.mockReturnValue({ user: null });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CLEANING_TASKS"),
    );
    expect(result.current).toBe(false);
  });

  it("hides rather than crashes on a role outside the generated union", () => {
    useAuth.mockReturnValue({ user: { role: "AUDITOR" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CLEANING_TASKS"),
    );
    expect(result.current).toBe(false);
  });

it("denies MANAGE_CONVERSATIONS to TENANT_OWNER — owner reads but does not operate (messaging-ai D17)", () => {
    useAuth.mockReturnValue({ user: { role: "TENANT_OWNER" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CONVERSATIONS"),
    );
    expect(result.current).toBe(false);
  });

  it("grants MANAGE_CONVERSATIONS to PROPERTY_MANAGER", () => {
    useAuth.mockReturnValue({ user: { role: "PROPERTY_MANAGER" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CONVERSATIONS"),
    );
    expect(result.current).toBe(true);
  });

  it("denies MANAGE_CONVERSATIONS to CLEANER", () => {
    useAuth.mockReturnValue({ user: { role: "CLEANER" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CONVERSATIONS"),
    );
    expect(result.current).toBe(false);
  });

  it("denies MANAGE_CONVERSATIONS to TECHNICIAN", () => {
    useAuth.mockReturnValue({ user: { role: "TECHNICIAN" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CONVERSATIONS"),
    );
    expect(result.current).toBe(false);
  });

  it("denies MANAGE_CONVERSATIONS to SUPER_ADMIN (the policy keeps super_admin outside the tenant's operational surface)", () => {
    useAuth.mockReturnValue({ user: { role: "SUPER_ADMIN" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_CONVERSATIONS"),
    );
    expect(result.current).toBe(false);
  });

  it("grants MANAGE_PRICE_RECOMMENDATIONS to PROPERTY_MANAGER (R7.1)", () => {
    useAuth.mockReturnValue({ user: { role: "PROPERTY_MANAGER" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_PRICE_RECOMMENDATIONS"),
    );
    expect(result.current).toBe(true);
  });

  it("grants MANAGE_PRICE_RECOMMENDATIONS to TENANT_OWNER too (R7.1, R7.2)", () => {
    // The asymmetry with `MANAGE_CLEANING_TASKS` is the point, and R7.2 names
    // copying that shape as the failure: the owner would see a queue of prices
    // for her own flat with every button hidden, while `policy.py:293-294`
    // and `324-325` were granting her the write.
    useAuth.mockReturnValue({ user: { role: "TENANT_OWNER" } });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_PRICE_RECOMMENDATIONS"),
    );
    expect(result.current).toBe(true);
  });

  it("denies MANAGE_PRICE_RECOMMENDATIONS to the other three roles (R7.1)", () => {
    for (const role of ["SUPER_ADMIN", "CLEANER", "TECHNICIAN"]) {
      useAuth.mockReturnValue({ user: { role } });
      const { result } = renderHook(() =>
        useHasPermission("MANAGE_PRICE_RECOMMENDATIONS"),
      );
      expect(result.current, `${role} should not have it`).toBe(false);
    }
  });

  it("denies MANAGE_PRICE_RECOMMENDATIONS without an authenticated user", () => {
    useAuth.mockReturnValue({ user: null });
    const { result } = renderHook(() =>
      useHasPermission("MANAGE_PRICE_RECOMMENDATIONS"),
    );
    expect(result.current).toBe(false);
  });

  it("declares every UserRole of the generated contract", () => {
    expect(Object.keys(ROLE_UI_PERMISSIONS).sort()).toEqual([
      "CLEANER",
      "PROPERTY_MANAGER",
      "SUPER_ADMIN",
      "TECHNICIAN",
      "TENANT_OWNER",
    ]);
  });
});
