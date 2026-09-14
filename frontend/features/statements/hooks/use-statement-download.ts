"use client";

import { useCallback, useRef, useState } from "react";

import { useAuth } from "@/lib/auth";

import { getStatementsDataSource, type OwnerStatementDownload } from "../data";

type DownloadFormat = "csv" | "pdf";

function filenameFromHeaders(headers: Headers, format: DownloadFormat): string {
  const disposition = headers.get("Content-Disposition");
  const encoded = disposition?.match(/filename\*\s*=\s*UTF-8''([^;]+)/i)?.[1];
  if (encoded) {
    try {
      return decodeURIComponent(encoded.replace(/^"|"$/g, ""));
    } catch {
      // Fall through to the quoted/plain filename or a safe extension fallback.
    }
  }
  const filename = disposition?.match(/filename\s*=\s*(?:"([^"]+)"|([^;\s]+))/i);
  return filename?.[1] ?? filename?.[2] ?? `statement.${format}`;
}

function deliverDownload(payload: OwnerStatementDownload, format: DownloadFormat): void {
  // Copy the opaque payload into an ArrayBuffer accepted by the DOM Blob type.
  // No decoding or re-encoding occurs at this boundary.
  const bytes = new Uint8Array(payload.bytes);
  const buffer = bytes.buffer as ArrayBuffer;
  const blob = new Blob([buffer], {
    type: payload.headers.get("Content-Type") ?? "application/octet-stream",
  });
  const url = URL.createObjectURL(blob);
  let anchor: HTMLAnchorElement | null = null;
  try {
    anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filenameFromHeaders(payload.headers, format);
    anchor.style.display = "none";
    document.body.appendChild(anchor);
    anchor.click();
  } finally {
    try {
      anchor?.remove();
    } finally {
      URL.revokeObjectURL(url);
    }
  }
}

export function useStatementDownload(statementId: string | null) {
  const { user } = useAuth();
  const tenantId = user?.tenant_id;
  const [pending, setPending] = useState<Record<DownloadFormat, boolean>>({ csv: false, pdf: false });
  const [errors, setErrors] = useState<Record<DownloadFormat, Error | null>>({ csv: null, pdf: null });
  const pendingRef = useRef<Record<DownloadFormat, boolean>>({ csv: false, pdf: false });

  const download = useCallback(async (format: DownloadFormat) => {
    if (!statementId || !tenantId || pendingRef.current[format]) return;
    pendingRef.current[format] = true;
    setPending((current) => ({ ...current, [format]: true }));
    setErrors((current) => ({ ...current, [format]: null }));
    try {
      const source = getStatementsDataSource();
      const payload = format === "csv"
        ? await source.exportCsv(tenantId, statementId)
        : await source.exportPdf(tenantId, statementId);
      deliverDownload(payload, format);
    } catch (error) {
      const normalized = error instanceof Error ? error : new Error("Download failed");
      setErrors((current) => ({ ...current, [format]: normalized }));
      throw error;
    } finally {
      pendingRef.current[format] = false;
      setPending((current) => ({ ...current, [format]: false }));
    }
  }, [statementId, tenantId]);

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
