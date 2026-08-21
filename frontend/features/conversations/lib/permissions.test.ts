import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import type { UserRole } from "../data/dto";
import { canManageConversations } from "./permissions";

const ROLES: UserRole[] = [
  "SUPER_ADMIN",
  "TENANT_OWNER",
  "PROPERTY_MANAGER",
  "CLEANER",
  "TECHNICIAN",
];

describe("canManageConversations (task 2.3, D12, R6.1)", () => {
  it("is true for PROPERTY_MANAGER alone, over every role in the contract", () => {
    const allowed = ROLES.filter(canManageConversations);
    expect(allowed).toEqual(["PROPERTY_MANAGER"]);
  });

  it("answers for every role without falling through to undefined", () => {
    for (const role of ROLES) {
      expect(typeof canManageConversations(role)).toBe("boolean");
    }
  });
});

describe("the client implements no RBAC and no tenant scoping (R6.2)", () => {
  const featureDir = join(process.cwd(), "features/conversations");

  it("keeps the role decision to a single boolean and holds no permission list", () => {
    const src = readFileSync(join(featureDir, "lib/permissions.ts"), "utf8");
    // No permission catalogue mirrored from the backend's policy.py, and no
    // tenant predicate: the backend remains the authority (D12).
    expect(src).not.toMatch(/READ_CONVERSATIONS|MANAGE_CONVERSATIONS['"]/);
    expect(src).not.toMatch(/tenant_id|tenantId/);
    expect(src).not.toMatch(/Permission\b/);
  });
});
