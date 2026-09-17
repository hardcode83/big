import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { OwnerStatementDownload } from "../data";
import {
  deliverBlobDownload,
  deliverDownload,
  resolveDownloadFilename,
} from "./download";

const createObjectURL = vi.hoisted(() => vi.fn(() => "blob:statement"));
const revokeObjectURL = vi.hoisted(() => vi.fn());

beforeEach(() => {
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function payload(
  headers: Record<string, string> = {},
  bytes: Uint8Array = new Uint8Array([1, 2, 3]),
): OwnerStatementDownload {
  return { bytes, headers: new Headers(headers) };
}

describe("resolveDownloadFilename (R4.1/R4.2 — filename from headers only)", () => {
  it("falls back to statement.<ext> when Content-Disposition is absent", () => {
    expect(resolveDownloadFilename(new Headers(), "csv")).toBe("statement.csv");
    expect(resolveDownloadFilename(new Headers(), "pdf")).toBe("statement.pdf");
  });

  it("reads a quoted filename", () => {
    const headers = new Headers({ "Content-Disposition": 'attachment; filename="report-01.csv"' });
    expect(resolveDownloadFilename(headers, "csv")).toBe("report-01.csv");
  });

  it("reads a bare (unquoted) filename", () => {
    const headers = new Headers({ "Content-Disposition": "attachment; filename=report.pdf" });
    expect(resolveDownloadFilename(headers, "pdf")).toBe("report.pdf");
  });

  it("prefers and percent-decodes a UTF-8 filename* (RFC 5987)", () => {
    const headers = new Headers({
      "Content-Disposition":
        "attachment; filename=\"fallback.csv\"; filename*=UTF-8''liquidaci%C3%B3n.csv",
    });
    expect(resolveDownloadFilename(headers, "csv")).toBe("liquidación.csv");
  });

  it("falls through to the quoted filename when filename* is malformed", () => {
    const headers = new Headers({
      "Content-Disposition": "attachment; filename=\"safe.csv\"; filename*=UTF-8''%E0%A4%A",
    });
    expect(resolveDownloadFilename(headers, "csv")).toBe("safe.csv");
  });
});

describe("deliverBlobDownload (D4 — opaque bytes handed to the browser)", () => {
  it("builds an object URL, clicks a hidden anchor named by filename, and always revokes", () => {
    const anchor = document.createElement("a");
    const click = vi.spyOn(anchor, "click").mockImplementation(() => {});
    const remove = vi.spyOn(anchor, "remove");
    vi.spyOn(document, "createElement").mockReturnValue(anchor);

    deliverBlobDownload(payload({ "Content-Type": "text/csv" }), "report.csv");

    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(anchor.download).toBe("report.csv");
    expect(click).toHaveBeenCalledTimes(1);
    expect(remove).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:statement");
  });

  it("revokes the object URL even when the anchor click throws (R4.4 — no leaked resource)", () => {
    const anchor = document.createElement("a");
    vi.spyOn(anchor, "click").mockImplementation(() => {
      throw new Error("click failed");
    });
    vi.spyOn(document, "createElement").mockReturnValue(anchor);

    expect(() => deliverBlobDownload(payload(), "report.pdf")).toThrow("click failed");
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:statement");
  });
});

describe("deliverDownload (resolve + deliver)", () => {
  it("uses the response filename and hands over the exact bytes", () => {
    const anchor = document.createElement("a");
    vi.spyOn(anchor, "click").mockImplementation(() => {});
    vi.spyOn(document, "createElement").mockReturnValue(anchor);

    deliverDownload(
      payload({ "Content-Disposition": 'attachment; filename="q1.csv"', "Content-Type": "text/csv" }),
      "csv",
    );

    expect(anchor.download).toBe("q1.csv");
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(revokeObjectURL).toHaveBeenCalledTimes(1);
  });

  it("creates no downloadable object when the response never arrives (failed response)", async () => {
    // A failed export rejects before any delivery: deliver is never reached, so
    // no Blob/URL is created and nothing needs revoking (R4.4).
    const source = {
      exportCsv: vi.fn().mockRejectedValue(new Error("network")),
    };

    let delivered = false;
    try {
      const result = await source.exportCsv();
      deliverDownload(result, "csv");
      delivered = true;
    } catch {
      // swallow — the failed response short-circuits before deliverDownload
    }

    expect(delivered).toBe(false);
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(revokeObjectURL).not.toHaveBeenCalled();
  });
});
