import { describe, expect, it } from "vitest";

import {
  MAX_ASSIGNMENT_NOTE_LENGTH,
  hasControlCharacters,
} from "./assignment-note";

describe("hasControlCharacters (R2.3, D11)", () => {
  it("accepts plain text", () => {
    expect(hasControlCharacters("Left the spare key under the mat.")).toBe(false);
  });

  it("accepts tab (U+0009)", () => {
    expect(hasControlCharacters("col1\tcol2")).toBe(false);
  });

  it("accepts line feed (U+000A)", () => {
    expect(hasControlCharacters("first line\nsecond line")).toBe(false);
  });

  it("accepts both tab and newline together", () => {
    expect(hasControlCharacters("a\tb\nc")).toBe(false);
  });

  it("rejects NUL (U+0000)", () => {
    expect(hasControlCharacters("a\u0000b")).toBe(true);
  });

  it("rejects carriage return (U+000D) - only newline and tab are excepted", () => {
    expect(hasControlCharacters("a\rb")).toBe(true);
  });

  it("rejects the unit separator (U+001F), the top of the control range", () => {
    expect(hasControlCharacters("a\u001Fb")).toBe(true);
  });

  it("rejects a control character just below tab (U+0008, backspace)", () => {
    expect(hasControlCharacters("a\u0008b")).toBe(true);
  });

  it("rejects a control character just above newline (U+000B, vertical tab)", () => {
    expect(hasControlCharacters("a\u000Bb")).toBe(true);
  });

  it("accepts the empty string", () => {
    expect(hasControlCharacters("")).toBe(false);
  });
});

describe("MAX_ASSIGNMENT_NOTE_LENGTH (R2.3)", () => {
  it("is 2000", () => {
    expect(MAX_ASSIGNMENT_NOTE_LENGTH).toBe(2000);
  });

  it("callers can use it to check the boundary (2000 ok, 2001 not)", () => {
    const atLimit = "a".repeat(MAX_ASSIGNMENT_NOTE_LENGTH);
    const overLimit = "a".repeat(MAX_ASSIGNMENT_NOTE_LENGTH + 1);
    expect(atLimit.length <= MAX_ASSIGNMENT_NOTE_LENGTH).toBe(true);
    expect(overLimit.length <= MAX_ASSIGNMENT_NOTE_LENGTH).toBe(false);
  });
});
