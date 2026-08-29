import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

/**
 * `@/features/shell` must stay importable from a Client Component.
 *
 * This exists because the claim was made in prose first and enforced by nothing. During
 * `notifications-inbox-web` the inbox panel imported `useNotificationsPanel` from that barrel,
 * the barrel re-exported the five shells and `routeMetadata`, and those reach `server-only`
 * (the shells through `lib/theme/server`, `routeMetadata` through
 * `lib/metadata/create-route-metadata` → `lib/i18n/server`). A Client Component therefore
 * dragged `server-only` into the browser graph.
 *
 * Nothing caught it locally: `tsc` type-checks, Vitest runs modules in isolation, and ESLint's
 * boundary rules are about *which feature* you import, not about what that import transitively
 * pulls. The React Server/Client boundary is enforced only by `next build`, which in this
 * project runs exclusively in the `provenance-contract` CI job. That is a slow, remote signal
 * for a mistake that is one import away at any time.
 *
 * So the barrel's client-safety is pinned here as a fact instead of a comment. The walk is
 * deliberately over the *whole transitive graph* rather than the barrel's own import list: the
 * defect that motivated it was three modules deep.
 */

const FRONTEND_ROOT = resolve(__dirname, "..");
const CLIENT_BARREL = join(FRONTEND_ROOT, "features/shell/index.ts");
const SERVER_BARREL = join(FRONTEND_ROOT, "features/shell/server.ts");

/** Modules that may only be evaluated on the server. Reaching either from a client graph is the bug. */
const SERVER_ONLY_SPECIFIERS = new Set(["server-only", "next/headers"]);

const EXTENSIONS = [".ts", ".tsx", ".js", ".jsx"];

/** Resolves an import specifier to a file inside this app, or null if it is external. */
function resolveSpecifier(specifier: string, importer: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) {
    base = join(FRONTEND_ROOT, specifier.slice(2));
  } else if (specifier.startsWith(".")) {
    base = resolve(dirname(importer), specifier);
  } else {
    return null; // node_modules or a bare builtin — not ours to walk
  }
  for (const extension of EXTENSIONS) {
    const candidate = `${base}${extension}`;
    if (existsSync(candidate)) return candidate;
  }
  for (const extension of EXTENSIONS) {
    const candidate = join(base, `index${extension}`);
    if (existsSync(candidate)) return candidate;
  }
  return existsSync(base) ? base : null;
}

const IMPORT_RE = /(?:^|\n)\s*(?:import|export)[\s\S]*?from\s*["']([^"']+)["']/g;
const BARE_IMPORT_RE = /(?:^|\n)\s*import\s*["']([^"']+)["']/g;

function specifiersOf(source: string): string[] {
  const found: string[] = [];
  for (const match of source.matchAll(IMPORT_RE)) found.push(match[1]);
  for (const match of source.matchAll(BARE_IMPORT_RE)) found.push(match[1]);
  return found;
}

/**
 * Walks the transitive import graph from `entry` and returns the chain that reaches a
 * server-only module, or null when none does. Returning the *chain* rather than a boolean is
 * what makes a failure actionable: the offending import is rarely in the file you edited.
 */
function findServerOnlyPath(entry: string): string[] | null {
  const seen = new Set<string>();
  const stack: { file: string; chain: string[] }[] = [{ file: entry, chain: [entry] }];

  while (stack.length > 0) {
    const { file, chain } = stack.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);

    let source: string;
    try {
      source = readFileSync(file, "utf8");
    } catch {
      continue;
    }

    for (const specifier of specifiersOf(source)) {
      if (SERVER_ONLY_SPECIFIERS.has(specifier)) {
        return [...chain, specifier];
      }
      const resolved = resolveSpecifier(specifier, file);
      if (resolved && !seen.has(resolved)) {
        stack.push({ file: resolved, chain: [...chain, resolved] });
      }
    }
  }
  return null;
}

function relative(paths: string[]): string[] {
  return paths.map((p) => (p.startsWith(FRONTEND_ROOT) ? p.slice(FRONTEND_ROOT.length + 1) : p));
}

describe("@/features/shell is client-safe", () => {
  it("reaches no server-only module from the client barrel", () => {
    const offending = findServerOnlyPath(CLIENT_BARREL);
    expect(
      offending === null ? null : relative(offending).join("\n  → "),
      "features/shell/index.ts is imported by Client Components. Anything it reaches ends up in " +
        "the browser graph, and a server-only module there fails `next build` — a signal that " +
        "only appears in the provenance-contract CI job. Move the offending export to " +
        "features/shell/server.ts, which app/ imports directly.",
    ).toBeNull();
  });

  /**
   * The positive control. Without it a walker that silently resolved nothing would pass the
   * assertion above while checking exactly zero imports — a guard that cannot fail is worse
   * than no guard, because it reads as evidence.
   */
  it("does reach a server-only module from the server barrel, proving the walk sees imports", () => {
    const offending = findServerOnlyPath(SERVER_BARREL);
    expect(offending, "the walk found no server-only module even from features/shell/server.ts").not.toBeNull();
  });
});
