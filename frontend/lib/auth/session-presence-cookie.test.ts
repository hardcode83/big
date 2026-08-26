import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { SESSION_PRESENT_COOKIE } from "@/lib/config/constants";
import {
  clearSessionPresent,
  markSessionPresent,
} from "@/lib/auth/session-presence-cookie";

function readCookie(name: string): string | null {
  const cookies = document.cookie ? document.cookie.split("; ") : [];
  const match = cookies.find((entry) => entry.startsWith(`${name}=`));
  return match ? match.slice(name.length + 1) : null;
}

function clearAll(): void {
  document.cookie.split("; ").forEach((entry) => {
    const name = entry.split("=")[0];
    if (name) {
      document.cookie = `${name}=; path=/; max-age=0; samesite=lax`;
    }
  });
}

describe("session presence cookie", () => {
  beforeEach(() => {
    clearAll();
  });

  afterEach(() => {
    clearAll();
  });

  it("marks presence with the expected cookie posture", () => {
    markSessionPresent();
    expect(readCookie(SESSION_PRESENT_COOKIE)).toBe("1");
  });

  it("clears the cookie without touching other cookies", () => {
    document.cookie = "autohostai.locale=es; path=/; max-age=31536000; samesite=lax";
    markSessionPresent();
    clearSessionPresent();
    expect(readCookie(SESSION_PRESENT_COOKIE)).toBeNull();
    expect(readCookie("autohostai.locale")).toBe("es");
  });

  it("is idempotent on repeated marks", () => {
    markSessionPresent();
    markSessionPresent();
    markSessionPresent();
    expect(readCookie(SESSION_PRESENT_COOKIE)).toBe("1");
  });

  it("clear is a no-op when the cookie is unset", () => {
    expect(() => clearSessionPresent()).not.toThrow();
    expect(readCookie(SESSION_PRESENT_COOKIE)).toBeNull();
  });
});
