import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { StatementsDataSource } from "../data";
import { useStatementDownload } from "./use-statement-download";

const exportCsv = vi.hoisted(() => vi.fn());
const exportPdf = vi.hoisted(() => vi.fn());
const createObjectURL = vi.hoisted(() => vi.fn(() => "blob:statement"));
const revokeObjectURL = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { tenant_id: "tenant-1" } }) }));
vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getStatementsDataSource: (): StatementsDataSource => ({
    listStatements: vi.fn(),
    getStatement: vi.fn(),
    exportCsv,
    exportPdf,
  }),
}));

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  exportCsv.mockReset();
  exportPdf.mockReset();
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
  vi.stubGlobal("URL", { createObjectURL, revokeObjectURL });
});

describe("useStatementDownload", () => {
  it("keeps CSV and PDF pending state independent and uses the response filename", async () => {
    let resolveCsv!: (value: unknown) => void;
    exportCsv.mockReturnValue(new Promise((resolve) => { resolveCsv = resolve; }));
    exportPdf.mockResolvedValue({ bytes: new Uint8Array([7]), headers: new Headers({ "Content-Disposition": 'attachment; filename="report.pdf"', "Content-Type": "application/pdf" }) });
    const { result } = renderHook(() => useStatementDownload("statement-1"), { wrapper });

    const csvPromise = result.current.downloadCsv();
    await waitFor(() => expect(result.current.csvPending).toBe(true));
    expect(result.current.pdfPending).toBe(false);
    await result.current.downloadPdf();
    expect(exportPdf).toHaveBeenCalledWith("tenant-1", "statement-1");
    resolveCsv({ bytes: new Uint8Array([1, 2]), headers: new Headers({ "Content-Disposition": 'attachment; filename="report.csv"' }) });
    await csvPromise;
    expect(createObjectURL).toHaveBeenCalledTimes(2);
    expect(revokeObjectURL).toHaveBeenCalledTimes(2);
  });

  it("prevents synchronous double activation of one format", async () => {
    let resolve!: (value: unknown) => void;
    exportCsv.mockReturnValue(new Promise((res) => { resolve = res; }));
    const { result } = renderHook(() => useStatementDownload("statement-1"), { wrapper });
    const first = result.current.downloadCsv();
    const second = result.current.downloadCsv();
    expect(exportCsv).toHaveBeenCalledTimes(1);
    resolve({ bytes: new Uint8Array([1]), headers: new Headers() });
    await first;
    await second;
  });

  it("cleans up the anchor and revokes the URL when clicking fails", async () => {
    const anchor = document.createElement("a");
    vi.spyOn(anchor, "click").mockImplementation(() => { throw new Error("click failed"); });
    const remove = vi.spyOn(anchor, "remove");
    exportCsv.mockResolvedValue({ bytes: new Uint8Array([1]), headers: new Headers() });
    const { result } = renderHook(() => useStatementDownload("statement-1"), { wrapper });
    const createElement = vi.spyOn(document, "createElement").mockReturnValue(anchor);

    try {
      await expect(result.current.downloadCsv()).rejects.toThrow("click failed");
      expect(remove).toHaveBeenCalledTimes(1);
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:statement");
    } finally {
      createElement.mockRestore();
    }
  });

  it("does not create a Blob or URL after a failed response and cleans pending state", async () => {
    exportCsv.mockRejectedValue(new Error("failed"));
    const { result } = renderHook(() => useStatementDownload("statement-1"), { wrapper });
    await expect(result.current.downloadCsv()).rejects.toThrow("failed");
    expect(createObjectURL).not.toHaveBeenCalled();
    expect(revokeObjectURL).not.toHaveBeenCalled();
    await waitFor(() => {
      expect(result.current.csvPending).toBe(false);
      expect(result.current.csvError?.message).toBe("failed");
    });
  });
});
