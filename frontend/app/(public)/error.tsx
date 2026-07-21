"use client";

import { useTranslation } from "react-i18next";

import { ErrorState } from "@/components/states";

/**
 * Segment error boundary (design D18). Composes ErrorState inside the content
 * slot so the shell chrome stays visible; never renders the received error; and
 * passes retry only via App Router's real `reset`.
 */
export default function PublicError({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  const { t } = useTranslation("states");
  return (
    <ErrorState
      title={t("error.title")}
      description={t("error.description")}
      onRetry={reset}
      retryLabel={t("error.retry")}
    />
  );
}
