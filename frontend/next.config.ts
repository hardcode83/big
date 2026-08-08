import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  // No body-size ceiling here, and that is a measured conclusion rather than an
  // omission (design D8, corrected during /sdd:run).
  //
  // `proxyClientMaxBodySize` — which the Next docs describe — does NOT exist in
  // 16.2.11: the running server rejects it as an unrecognized key. It is a canary-only
  // option. And it turned out not to be needed: the backend already refuses an
  // oversized body with `413` BEFORE reading it, via `MaxBodySizeMiddleware` scoped to
  // `/api/v1/integrations/` with `CSV_IMPORT_MAX_BYTES` (backend/app/main.py). Since
  // `app/api/[...path]/route.ts` forwards the body as a STREAM (`duplex: "half"`), that
  // refusal arrives while the body is still being sent — this process never accumulates
  // it. Adding a second ceiling here would duplicate a limit that has one home.
};

export default nextConfig;
