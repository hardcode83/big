"use client";

import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

/**
 * The reversible close panel (R7.2, D8).
 *
 * Renders after `useCompleteCleaningTask` succeeds: a localized «Cerrada»
 * headline + «Volver a mis tareas» button that calls
 * `router.replace("/cleaner")`. Reversible by definition: no auto-dismiss.
 */
export function CleanerCompletionPanel() {
  const { t } = useTranslation("cleaner");
  const router = useRouter();

  return (
    <section
      role="status"
      aria-labelledby="cleaner-completion-heading"
      className="flex flex-col gap-3 rounded-lg border bg-surface p-4"
    >
      <h2
        id="cleaner-completion-heading"
        className="text-sm font-semibold text-foreground"
      >
        {t("complete.success.title")}
      </h2>
      <p className="text-sm text-muted-foreground">
        {t("complete.success.description")}
      </p>
      <div>
        <Button
          type="button"
          onClick={() => router.replace("/cleaner")}
        >
          {t("complete.success.back")}
        </Button>
      </div>
    </section>
  );
}