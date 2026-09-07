import { describe, expect, it } from "vitest";

import { ROLE_HOME, roleHome } from "./role-home";

describe("roleHome", () => {
  it("maps each MVP role to its shell route", () => {
    expect(roleHome("TENANT_OWNER")).toBe("/dashboard");
    expect(roleHome("PROPERTY_MANAGER")).toBe("/dashboard");
    expect(roleHome("CLEANER")).toBe("/cleaner");
    expect(roleHome("TECHNICIAN")).toBe("/tech");
  });

  it("maps SUPER_ADMIN to the platform console, not /dashboard", () => {
    expect(roleHome("SUPER_ADMIN")).toBe("/platform");
  });

  it("falls back to /dashboard when the role is undefined", () => {
    expect(roleHome(undefined)).toBe("/dashboard");
  });

  it("falls back to /dashboard for any role outside the table", () => {
    expect(roleHome("FOO")).toBe("/dashboard");
  });

  it("exposes ROLE_HOME exhaustively for the MVP roles plus SUPER_ADMIN", () => {
    expect(Object.keys(ROLE_HOME).sort()).toEqual(
      [
        "CLEANER",
        "PROPERTY_MANAGER",
        "SUPER_ADMIN",
        "TECHNICIAN",
        "TENANT_OWNER",
      ].sort(),
    );
  });
});