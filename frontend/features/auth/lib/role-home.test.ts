import { describe, expect, it } from "vitest";

import { ROLE_HOME, roleHome } from "./role-home";

describe("roleHome", () => {
  it("maps each MVP role to its shell route", () => {
    expect(roleHome("TENANT_OWNER")).toBe("/dashboard");
    expect(roleHome("PROPERTY_MANAGER")).toBe("/dashboard");
    expect(roleHome("CLEANER")).toBe("/cleaner");
    expect(roleHome("TECHNICIAN")).toBe("/tech");
  });

  it("falls back to /dashboard when the role is undefined", () => {
    expect(roleHome(undefined)).toBe("/dashboard");
  });

  it("falls back to /dashboard for any role outside the table", () => {
    expect(roleHome("SUPER_ADMIN")).toBe("/dashboard");
    expect(roleHome("FOO")).toBe("/dashboard");
  });

  it("exposes ROLE_HOME exhaustively for the MVP roles", () => {
    expect(Object.keys(ROLE_HOME).sort()).toEqual(
      ["CLEANER", "PROPERTY_MANAGER", "TECHNICIAN", "TENANT_OWNER"].sort(),
    );
  });
});