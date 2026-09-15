import type { OwnerStatementDownload } from "../data";

/**
 * The two opaque export formats (R4). The value doubles as the extension used
 * for the safe filename fallback (`statement.csv` / `statement.pdf`) when the
 * response carries no usable `Content-Disposition`.
 */
export type DownloadFormat = "csv" | "pdf";

/**
 * Resolves the download filename from the response's `Content-Disposition`
 * header, never from the payload (D4, R4.1/R4.2). The bytes are opaque: this
 * only reads a contractual header, it does not parse, validate or inspect the
 * file itself (R4.3).
 *
 * Resolution order, safest interpretation first:
 *  1. RFC 5987 `filename*=UTF-8''…` (percent-decoded; malformed encodings fall
 *     through instead of throwing).
 *  2. `filename="quoted"` or bare `filename=plain`.
 *  3. A safe `statement.<ext>` fallback when the header is absent or unusable,
 *     so a download is never handed to the browser without a name.
 */
export function resolveDownloadFilename(headers: Headers, fallbackExt: string): string {
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
  return filename?.[1] ?? filename?.[2] ?? `statement.${fallbackExt}`;
}

/**
 * Hands the browser the exact received bytes as a download (D4, R4.3). A `Blob`
 * is built ONLY to transport the opaque payload to the DOM — no decoding,
 * re-encoding or transformation happens at this boundary — and the temporary
 * object URL is ALWAYS revoked in a `finally`, even if the anchor click throws,
 * so no partial download or leaked resource survives a failure (R4.4).
 */
export function deliverBlobDownload(payload: OwnerStatementDownload, filename: string): void {
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
    anchor.download = filename;
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

/**
 * Convenience over `resolveDownloadFilename` + `deliverBlobDownload`: resolve
 * the filename from the payload's own headers (using `format` as the extension
 * fallback) and deliver the bytes. This is the single entry point the download
 * hook calls; the two lower-level functions stay exported for direct/tested use.
 */
export function deliverDownload(payload: OwnerStatementDownload, format: DownloadFormat): void {
  deliverBlobDownload(payload, resolveDownloadFilename(payload.headers, format));
}
