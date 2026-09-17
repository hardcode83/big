"use client";

import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/button";

import { useStatementDownload } from "../hooks/use-statement-download";

export interface StatementDownloadsProps {
  /** The statement whose CSV/PDF exports these controls download (R4). */
  statementId: string;
}

/**
 * CSV/PDF export controls for one statement (R4, R5, design D4-D6).
 *
 * Purely a UI shell over `useStatementDownload`: it never touches the network,
 * the data source or the payload directly — the hook calls the existing
 * `/export.csv` and `/export.pdf` endpoints and hands the opaque bytes to the
 * browser. This component therefore does not parse, validate, re-encode or
 * reconstruct the CSV/PDF (R4.3); it only renders the two controls and their
 * per-format pending/error state.
 *
 * Accessibility/UX baseline (steering frontend.md, D6): each control is a real
 * `<button>` whose visible text is its accessible name, focus-visible comes
 * from the shared `Button`, and `tap-target` keeps both controls ≥44px. Per
 * D5, each download has its own pending/error state and only its own control is
 * disabled while running, which (together with the hook's per-format lock)
 * prevents double activation (R5.1). On failure a translated error is shown
 * without ever inspecting the file bytes (R4.4).
 */
export function StatementDownloads({ statementId }: StatementDownloadsProps) {
  const { t } = useTranslation("statements");
  const { downloadCsv, downloadPdf, csvPending, pdfPending, csvError, pdfError } =
    useStatementDownload(statementId);

  return (
    <section
      aria-label={t("downloads.label")}
      className="flex min-w-0 flex-col gap-2"
      data-testid="statement-downloads"
    >
      <div className="flex flex-wrap items-center gap-2">
        <Button
          type="button"
          variant="outline"
          className="tap-target"
          disabled={csvPending}
          aria-busy={csvPending}
          onClick={() => {
            // The hook owns the error state and re-throws; swallow the rejection
            // here so the failed download never surfaces as an unhandled
            // rejection, and never inspect the payload (R4.3/R4.4).
            void downloadCsv().catch(() => {});
          }}
        >
          {csvPending ? t("downloads.pending") : t("downloads.csv")}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="tap-target"
          disabled={pdfPending}
          aria-busy={pdfPending}
          onClick={() => {
            void downloadPdf().catch(() => {});
          }}
        >
          {pdfPending ? t("downloads.pending") : t("downloads.pdf")}
        </Button>
      </div>
      {csvError ? (
        <p role="alert" className="text-body-base text-destructive">
          {t("downloads.error")}
        </p>
      ) : null}
      {pdfError ? (
        <p role="alert" className="text-body-base text-destructive">
          {t("downloads.error")}
        </p>
      ) : null}
    </section>
  );
}
