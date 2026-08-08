import { afterEach, describe, expect, it, vi } from "vitest";

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

  it("does not persist credentials through browser storage APIs", () => {
    const localStorageWrite = vi.spyOn(window.localStorage, "setItem");
    const sessionStorageWrite = vi.spyOn(window.sessionStorage, "setItem");
    const indexedDbOpen = vi.fn();
    const hadIndexedDB = "indexedDB" in window;
    const originalIndexedDB = window.indexedDB;
    Object.defineProperty(window, "indexedDB", {
      configurable: true,
      value: { open: indexedDbOpen },
    });
    const cookieWrite = vi.spyOn(Document.prototype, "cookie", "set");

    setSessionTokens({ accessToken: "access", refreshToken: "refresh" });
    expect(getSessionTokens()).toEqual({ accessToken: "access", refreshToken: "refresh" });
    clearSessionTokens();

    expect(localStorageWrite).not.toHaveBeenCalled();
    expect(sessionStorageWrite).not.toHaveBeenCalled();
    expect(indexedDbOpen).not.toHaveBeenCalled();
    expect(cookieWrite).not.toHaveBeenCalled();

    localStorageWrite.mockRestore();
    sessionStorageWrite.mockRestore();
    cookieWrite.mockRestore();
    if (hadIndexedDB) {
      Object.defineProperty(window, "indexedDB", {
        configurable: true,
        value: originalIndexedDB,
      });
    } else {
      Reflect.deleteProperty(window, "indexedDB");
    }
  });
});
