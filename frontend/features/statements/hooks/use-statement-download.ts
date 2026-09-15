"use client";

import { useCallback, useLayoutEffect, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";

import { getStatementsDataSource } from "../data";
import { deliverDownload, type DownloadFormat } from "../lib/download";

export function useStatementDownload(statementId: string | null) {
  const { user } = useAuth();
  const tenantId = user?.tenant_id;
  // `tenantIdRef.current` is mirrored from `useAuth()` on every identity
  // change so the closure below always reads the LATEST authenticated tenant
  // — without it, an in-flight download started under tenant A would only
  // see A even after logout or a switch to tenant B. `useLayoutEffect`
  // (rather than the render-phase "mirroring" pattern) keeps the React
  // Compiler / `react-hooks/refs` lint happy AND shrinks the race window to
  // "synchronous, before paint" — before any async response can possibly
  // resolve.
  const tenantIdRef = useRef<string | undefined>(tenantId);
  useLayoutEffect(() => {
    tenantIdRef.current = tenantId;
  }, [tenantId]);

  const [pending, setPending] = useState<Record<DownloadFormat, boolean>>({ csv: false, pdf: false });
  const [errors, setErrors] = useState<Record<DownloadFormat, Error | null>>({ csv: null, pdf: null });
  const pendingRef = useRef<Record<DownloadFormat, boolean>>({ csv: false, pdf: false });

  const download = useCallback(async (format: DownloadFormat) => {
    const tenantIdAtStart = tenantIdRef.current;
    if (!statementId || !tenantIdAtStart || pendingRef.current[format]) return;
    pendingRef.current[format] = true;
    setPending((current) => ({ ...current, [format]: true }));
    setErrors((current) => ({ ...current, [format]: null }));
    try {
      const source = getStatementsDataSource();
      const payload = format === "csv"
        ? await source.exportCsv(tenantIdAtStart, statementId)
        : await source.exportPdf(tenantIdAtStart, statementId);
      // Re-check identity AFTER the request completes: if the user logged out
      // or switched tenant while we were waiting on the network, the bytes
      // we just received belong to a session the browser no longer
      // represents — drop them on the floor without creating a Blob, an
      // object URL, or touching `<a download>`. (security.md rule 1, R1.3, D5)
      if (tenantIdRef.current !== tenantIdAtStart) {
        return;
      }
      deliverDownload(payload, format);
    } catch (error) {
      // An identity change AFTER the request resolved is not an error to the
      // caller — the old session went away cleanly. Anything else (network,
      // 5xx, source rejection) is.
      if (tenantIdRef.current !== tenantIdAtStart) {
        return;
      }
      const normalized = error instanceof Error ? error : new Error("Download failed");
      setErrors((current) => ({ ...current, [format]: normalized }));
      throw error;
    } finally {
      pendingRef.current[format] = false;
      setPending((current) => ({ ...current, [format]: false }));
    }
  }, [statementId]);

  return {
    downloadCsv: () => download("csv"),
    downloadPdf: () => download("pdf"),
    csvPending: pending.csv,
    pdfPending: pending.pdf,
    isCsvPending: pending.csv,
    isPdfPending: pending.pdf,
    csvError: errors.csv,
    pdfError: errors.pdf,
  };
}
