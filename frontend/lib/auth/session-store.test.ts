import { afterEach, describe, expect, it } from "vitest";

import {
  clearSessionTokens,
  getSessionTokens,
  setSessionTokens,
} from "@/lib/auth/session-store";

describe("session store", () => {
  afterEach(() => clearSessionTokens());

  it("stores and returns a defensive copy of the JWT pair in memory", () => {
    const tokens = { accessToken: "access", refreshToken: "refresh" };

    setSessionTokens(tokens);
    tokens.accessToken = "mutated";

    expect(getSessionTokens()).toEqual({
      accessToken: "access",
      refreshToken: "refresh",
    });
  });

  it("clears the pair idempotently", () => {
    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });

    clearSessionTokens();
    clearSessionTokens();

    expect(getSessionTokens()).toBeNull();
  });
});
