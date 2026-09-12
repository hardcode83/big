import { describe, expect, it } from "vitest";

import { validateTenantConfig } from "./validate-tenant-config";

describe("validateTenantConfig (R5.3)", () => {
  describe("ownerApprovalThresholdEur (threshold >= 0)", () => {
    it("rejects a negative threshold", () => {
      expect(validateTenantConfig({ ownerApprovalThresholdEur: "-0.01" })).toHaveProperty(
        "ownerApprovalThresholdEur",
      );
    });

    it("accepts zero (the boundary)", () => {
      expect(validateTenantConfig({ ownerApprovalThresholdEur: "0.00" })).toEqual({});
    });

    it("accepts a positive decimal string", () => {
      expect(validateTenantConfig({ ownerApprovalThresholdEur: "150.50" })).toEqual({});
    });

    it("accepts a positive number", () => {
      expect(validateTenantConfig({ ownerApprovalThresholdEur: 150.5 })).toEqual({});
    });

    it("rejects a non-numeric string", () => {
      expect(validateTenantConfig({ ownerApprovalThresholdEur: "not-a-number" })).toHaveProperty(
        "ownerApprovalThresholdEur",
      );
    });

    it("is not checked when absent from the input", () => {
      expect(validateTenantConfig({})).toEqual({});
    });
  });

  describe("aiConfidenceThreshold (confidence in [0, 1])", () => {
    it("rejects below 0", () => {
      expect(validateTenantConfig({ aiConfidenceThreshold: "-0.01" })).toHaveProperty(
        "aiConfidenceThreshold",
      );
    });

    it("accepts the lower boundary 0", () => {
      expect(validateTenantConfig({ aiConfidenceThreshold: "0" })).toEqual({});
    });

    it("accepts the upper boundary 1", () => {
      expect(validateTenantConfig({ aiConfidenceThreshold: "1" })).toEqual({});
    });

    it("rejects above 1", () => {
      expect(validateTenantConfig({ aiConfidenceThreshold: "1.01" })).toHaveProperty(
        "aiConfidenceThreshold",
      );
    });

    it("accepts a mid-range value", () => {
      expect(validateTenantConfig({ aiConfidenceThreshold: "0.75" })).toEqual({});
    });
  });

  describe("SLA minutes (> 0)", () => {
    it("rejects zero for slaCriticalMinutes", () => {
      expect(validateTenantConfig({ slaCriticalMinutes: 0 })).toHaveProperty(
        "slaCriticalMinutes",
      );
    });

    it("rejects a negative slaHighMinutes", () => {
      expect(validateTenantConfig({ slaHighMinutes: -5 })).toHaveProperty("slaHighMinutes");
    });

    it("accepts the boundary 1 for slaMediumMinutes", () => {
      expect(validateTenantConfig({ slaMediumMinutes: 1 })).toEqual({});
    });

    it("accepts a typical slaLowMinutes value", () => {
      expect(validateTenantConfig({ slaLowMinutes: 480 })).toEqual({});
    });

    it("rejects a non-finite value", () => {
      expect(validateTenantConfig({ slaCriticalMinutes: Number.NaN })).toHaveProperty(
        "slaCriticalMinutes",
      );
    });
  });

  describe("timezone (IANA)", () => {
    it("accepts a real IANA zone", () => {
      expect(validateTenantConfig({ timezone: "Europe/Madrid" })).toEqual({});
    });

    it("accepts UTC", () => {
      expect(validateTenantConfig({ timezone: "UTC" })).toEqual({});
    });

    it("rejects an unrecognized zone", () => {
      expect(validateTenantConfig({ timezone: "Not/AZone" })).toHaveProperty("timezone");
    });

    it("rejects an empty string", () => {
      expect(validateTenantConfig({ timezone: "" })).toHaveProperty("timezone");
    });

    it("rejects a whitespace-only string", () => {
      expect(validateTenantConfig({ timezone: "   " })).toHaveProperty("timezone");
    });

    it("is case-sensitive, mirroring the backend's normalise_timezone (trims but does not fold case)", () => {
      // Real IANA zones are capitalized (Europe/Madrid); a lowercased variant
      // that some engines happen to still construct is not something this
      // test asserts either way — the backend contract is "constructible as
      // given, case included", not "case-insensitive lookup".
      expect(validateTenantConfig({ timezone: "Europe/Madrid" })).toEqual({});
    });
  });

  it("validates multiple present fields independently", () => {
    const errors = validateTenantConfig({
      ownerApprovalThresholdEur: "-1",
      aiConfidenceThreshold: "0.5",
      timezone: "Not/AZone",
    });
    expect(Object.keys(errors).sort()).toEqual(["ownerApprovalThresholdEur", "timezone"]);
  });

  it("returns no errors for a fully valid, fully populated input", () => {
    expect(
      validateTenantConfig({
        timezone: "Europe/Madrid",
        ownerApprovalThresholdEur: "100.00",
        aiConfidenceThreshold: "0.80",
        slaCriticalMinutes: 15,
        slaHighMinutes: 30,
        slaMediumMinutes: 60,
        slaLowMinutes: 120,
      }),
    ).toEqual({});
  });
});
