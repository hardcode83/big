"use client";

import { useEffect, useRef } from "react";

/**
 * Last-resort boundary for unrecoverable failures in the RootLayout or its
 * providers (design D18). It replaces the whole document, so it renders its own
 * html/body and cannot rely on the i18n provider that may have failed — hence a
 * minimal inline ES/EN catalog. It NEVER shows error.message, stack traces,
 * secrets, or internal URLs; the error is only logged in development.
 */
const MESSAGES = {
  es: {
    title: "Error inesperado",
    description:
      "La aplicación ha encontrado un problema. Vuelve a intentarlo.",
    retry: "Recargar",
  },
  en: {
    title: "Unexpected error",
    description: "The application ran into a problem. Please try again.",
    retry: "Reload",
  },
} as const;

function resolveLocale(): "es" | "en" {
  if (typeof document !== "undefined") {
    const match = document.cookie.match(/autohostai\.locale=(es|en)/);
    if (match) {
      return match[1] as "es" | "en";
    }
  }
  return "es";
}

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const locale = resolveLocale();
  const copy = MESSAGES[locale];
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    headingRef.current?.focus();
  }, []);

  useEffect(() => {
    if (process.env.NODE_ENV === "development") {
      console.error(error);
    }
  }, [error]);

  return (
    <html lang={locale}>
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <main style={{ maxWidth: "28rem", padding: "1.5rem", textAlign: "center" }}>
          <h1
            ref={headingRef}
            tabIndex={-1}
            style={{ fontSize: "1.25rem", fontWeight: 600, outline: "none" }}
          >
            {copy.title}
          </h1>
          <p style={{ marginTop: "0.75rem", color: "#555" }}>
            {copy.description}
          </p>
          <button
            type="button"
            onClick={() => reset()}
            style={{
              marginTop: "1.25rem",
              padding: "0.5rem 1rem",
              borderRadius: "0.375rem",
              border: "1px solid #ccc",
              cursor: "pointer",
            }}
          >
            {copy.retry}
          </button>
        </main>
      </body>
    </html>
  );
}
