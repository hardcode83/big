/**
 * The contract's cap on the optional assignment note (R2.3): up to 2000
 * characters.
 */
export const MAX_ASSIGNMENT_NOTE_LENGTH = 2000;

/**
 * All of `U+0000`-`U+001F` except tab (`U+0009`) and line feed (`U+000A`) —
 * the note is free text that may span lines, but nothing else in that
 * control range belongs in it (R2.3, design D11). Deliberately does *not*
 * except carriage return (`U+000D`): R2.3's prose excepts only "salto de
 * línea y tabulador" (line feed and tab), so a lone `\r` is still rejected.
 *
 * Written with `\x` escapes rather than the raw control bytes the
 * design/tasks text renders as (visually indistinguishable from `/[ --]/`
 * once the invisible bytes are stripped by a terminal or viewer) — same two
 * ranges, `\x00`-`\x08` and `\x0B`-`\x1F`, just legible in source.
 */
const CONTROL_CHARACTERS = /[\x00-\x08\x0B-\x1F]/;

export function hasControlCharacters(value: string): boolean {
  return CONTROL_CHARACTERS.test(value);
}
