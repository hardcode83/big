import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

/**
 * The proxy's SCOPE, as a structural guarantee rather than a convention (R2.3).
 *
 * R2.1 says only `/api/` is proxied, which is what keeps `/openapi.json`, `/docs`,
 * `/docs/oauth2-redirect` and `/redoc` unreachable from the public origin now that one
 * exists (R2.2). Those endpoints are anonymous by allowlist in
 * `backend/tests/test_route_authorization.py` and were protected only by the backend
 * listening on loopback — so from this change on, the routing scope IS the protection.
 *
 * A behavioural test would need a running Next server, which the frontend suite
 * deliberately does not have (`specs/frontend-foundation.md` §Testing). So the scope is
 * pinned where it is decided: the filesystem.
 */

// Vitest runs from the frontend package root.
const packageRoot = process.cwd();
const appDir = join(packageRoot, "app");

const PROXY_ROUTE = "api/[...path]/route.ts";

/** Package directories that ship code, i.e. everywhere a second path could appear. */
const SOURCE_DIRS = ["app", "components", "features", "lib"];

function findFiles(dir: string, predicate: (name: string) => boolean): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      return findFiles(full, predicate);
    }
    return predicate(entry.name) ? [full] : [];
  });
}

function relativeToApp(file: string): string {
  return file.slice(appDir.length + 1);
}

/**
 * Does this module know how to reach the backend, by ANY of the ways available?
 *
 * All four predicates matter, and the last two were missing until a security review
 * pointed out the hole: the sweep only looked for the config boundary, so a Server Action
 * or a helper doing `fetch("http://backend:8000/openapi.json")` — a second door into the
 * `private` network, invocable from the public origin — matched nothing, added no
 * `route.ts`, and left this suite green. The literal is the one R1.4 forbids by name, and
 * it has to be checked HERE, over the swept tree, not only in a root proxy file.
 */
function reachesTheBackend(source: string): boolean {
  return (
    // The config boundary, by alias or by relative path.
    /from ["']@\/lib\/config\/server["']/.test(source) ||
    /from ["'][./]+lib\/config\/server["']/.test(source) ||
    // Round the boundary, straight to the variable.
    source.includes("process.env.BACKEND_INTERNAL_URL") ||
    // Or naming the internal origin outright.
    /\bbackend:\d+/.test(source) ||
    /\/\/backend\b/.test(source)
  );
}

describe("API proxy scope (R2.1, R2.3)", () => {
  it("has exactly one route handler, and it is the /api catch-all", () => {
    const handlers = findFiles(appDir, (name) => /^route\.tsx?$/.test(name))
      .map(relativeToApp)
      .sort();

    // A second route handler is not automatically wrong — but it is a new server
    // endpoint on the public origin, so it must be a deliberate decision reviewed as
    // one, not something that appears while doing something else. Adding it here is
    // that decision.
    expect(handlers).toEqual([PROXY_ROUTE]);
  });

  it("keeps the internal backend URL out of every surface but the proxy", () => {
    // Swept across the WHOLE package, not just `app/`: a Server Action or a helper under
    // `lib/`/`features/` reaching the backend would be a second path from the public
    // origin into the `private` network, and the earlier version of this test could not
    // see one. `lib/config/server.ts` is the boundary that OWNS the value, so it is the
    // one expected reader besides the proxy.
    const readers = SOURCE_DIRS.flatMap((dir) =>
      findFiles(join(packageRoot, dir), (name) => /\.tsx?$/.test(name)),
    )
      .filter((file) => !/\.test\.tsx?$/.test(file))
      .filter((file) => reachesTheBackend(readFileSync(file, "utf8")))
      .map((file) => file.slice(packageRoot.length + 1))
      .sort();

    // `lib/config/server.ts` is the boundary that owns the value, so it is expected here.
    expect(readers).toEqual(["app/api/[...path]/route.ts", "lib/config/server.ts"]);
  });

  it("has no root-level proxy that could route around the handler", () => {
    // The blind spot a security review pointed at, and it is not hypothetical: design D1
    // records that `frontend-auth-session` plans to own `proxy.ts` (Next 16's rename of
    // `middleware.ts`) for route protection. A `proxy()` there can rewrite ANY path,
    // `/openapi.json` included, straight to the backend — with this whole suite green,
    // because nothing under `app/` would change. So the guard has to look outside `app/`.
    const roots = readdirSync(packageRoot, { withFileTypes: true })
      .filter((entry) => entry.isFile() && /^(proxy|middleware)\.tsx?$/.test(entry.name))
      .map((entry) => entry.name);

    if (roots.length === 0) {
      return;
    }

    // If one exists, it must not be a second door to the backend. Whoever adds it owns
    // updating this expectation deliberately.
    //
    // BOTH ways of naming the destination are checked, and the second one is the whole
    // point: a security review pointed out that asserting only the config accessors let
    // through `NextResponse.rewrite(new URL("/openapi.json", "http://backend:8000"))` —
    // which mentions neither, adds no `route.ts`, touches no `rewrites` key, and
    // republishes the anonymous surface with this suite green. It is also precisely the
    // literal R1.4 forbids by name.
    for (const name of roots) {
      const source = readFileSync(join(packageRoot, name), "utf8");
      expect(reachesTheBackend(source)).toBe(false);
      expect(source).not.toContain("getServerConfig");
    }
  });

  it("does not proxy through next.config rewrites", () => {
    // Design D1: rewrite destinations are baked into routes-manifest.json at build
    // time, so a rewrite reading BACKEND_INTERNAL_URL would capture the CI build job's
    // empty value — and would work in `next dev`, making the failure look like an
    // environment problem rather than a wrong mechanism. Asserted as an absence so
    // nobody reintroduces it as an "optimisation" of the handler.
    const config = readFileSync(join(process.cwd(), "next.config.ts"), "utf8");

    expect(config).not.toContain("rewrites");
  });
});
