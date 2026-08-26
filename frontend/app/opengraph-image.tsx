import { ImageResponse } from "next/og";

import { getServerLocale } from "@/lib/i18n/server";
import esLanding from "@/locales/es/landing.json";

/**
 * Open Graph image for the public landing (R2.1, design D4).
 *
 * Generated at BUILD time by Next's `ImageResponse` machinery and shipped as a
 * static PNG, so the asset is reachable without a backend roundtrip and
 * without a third-party service. The text is a single line from the landing
 * catalogue — `landing.meta.title` — rendered on the emerald primary
 * background using Inter, the same typography the page itself publishes.
 *
 * `size: { width: 1200, height: 630 }` is the Open Graph recommended card;
 * Twitter and other consumers crop or letterbox the same dimensions.
 *
 * Per-locale variants (`og-es.png`, `og-en.png`) so the same image never
 * ships in the wrong language to a Spanish-speaking visitor. The locale is
 * resolved server-side via the existing `getServerLocale` helper.
 */
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "AutoHostAI";

export default async function OpengraphImage() {
  const locale = await getServerLocale();
  const table = locale === "en"
    ? (await import("@/locales/en/landing.json")).default
    : esLanding;
  const title = table.meta.title;

  return new ImageResponse(
    (
      <div
        style={{
          height: "100%",
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          background: "#006b5f",
          color: "#ffffff",
          padding: "48px",
        }}
      >
        <div
          style={{
            fontSize: 64,
            fontWeight: 800,
            letterSpacing: "-0.02em",
            lineHeight: 1.1,
            textAlign: "center",
          }}
        >
          {title}
        </div>
      </div>
    ),
    size,
  );
}
