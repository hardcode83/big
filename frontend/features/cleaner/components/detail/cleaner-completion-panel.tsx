"use client";

import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

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
    <section role="status" aria-labelledby="cleaner-completion-heading">
      <Card className="flex flex-col gap-3 p-4">
        <h2
          id="cleaner-completion-heading"
          className="text-body-lg font-semibold text-foreground"
        >
          {t("complete.success.title")}
        </h2>
        <p className="text-body-base text-muted-foreground">
          {t("complete.success.description")}
        </p>
        <div>
          <Button
            type="button"
            className="tap-target"
            onClick={() => router.replace("/cleaner")}
          >
            {t("complete.success.back")}
          </Button>
        </div>
      </Card>
    </section>
  );
}