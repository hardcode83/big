import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

/**
 * Setup for the `browser` project (`shell-topbar-overflow-360`, design D6).
 *
 * The jsdom setup is not reused: its whole body is a `localStorage` polyfill for
 * a jsdom build that lacks Web Storage, and Chromium has the real thing.
 *
 * What Chromium lacks is `process`. `lib/config/public.ts` reads
 * `process.env.NEXT_PUBLIC_*`, which Next.js inlines at build time and Vite does
 * not — so in a real browser those reads throw `process is not defined` before
 * any shell can render. An empty env is the honest stand-in: every one of those
 * fields already has a documented fallback for the unset case, which is what the
 * shells get here.
 */
const shimmed = globalThis as { process?: { env: Record<string, string> } };
shimmed.process ??= { env: {} };

afterEach(() => {
  cleanup();
});
