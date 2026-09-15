import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";

import type { StatementsDataSource } from "../data";
import { useStatementDetail, useStatementPropertyDirectory, useStatementsList } from "./use-statements-data";

const listStatements = vi.hoisted(() => vi.fn());
const getStatement = vi.hoisted(() => vi.fn());
const useActiveProperties = vi.hoisted(() => vi.fn());

vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { tenant_id: "tenant-1" } }) }));
vi.mock("@/features/properties", () => ({ useActiveProperties }));
vi.mock("../data", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../data")>()),
  getStatementsDataSource: (): StatementsDataSource => ({
    listStatements,
    getStatement,
    exportCsv: vi.fn(),
    exportPdf: vi.fn(),
  }),
}));

function harness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  }
  return { Wrapper };
}

beforeEach(() => {
  listStatements.mockReset().mockResolvedValue({ items: [], total: 0, page: 1, perPage: 20 });
  getStatement.mockReset().mockResolvedValue({ id: "statement-1" });
  useActiveProperties.mockReset().mockReturnValue({
    data: { data: [{ id: "property-1", name: "Madrid flat" }], total: 1 },
    isPending: false,
    isError: false,
  });
});

describe("statements read hooks", () => {
  it("queries the list with tenant, filters, page, and shared retry policy wiring", async () => {
    const { result } = renderHook(() => useStatementsList({ status: "READY" }, 2), { wrapper: harness().Wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(listStatements).toHaveBeenCalledWith("tenant-1", { status: "READY" }, 2);
  });

  it.each([null, ""])("does not activate detail without an id (%s)", (statementId) => {
    renderHook(() => useStatementDetail(statementId), { wrapper: harness().Wrapper });
    expect(getStatement).not.toHaveBeenCalled();
  });

  it("uses the existing active-properties hook and derives a complete id index", () => {
    const { result } = renderHook(() => useStatementPropertyDirectory(), { wrapper: harness().Wrapper });
    expect(useActiveProperties).toHaveBeenCalledTimes(1);
    expect(result.current.index.get("property-1")?.name).toBe("Madrid flat");
  });

  it("keeps a property-directory failure independent from statement errors", async () => {
    useActiveProperties.mockReturnValue({ isPending: false, isError: true, error: new Error("catalog") });
    const { Wrapper } = harness();
    const statements = renderHook(() => useStatementsList({}, 1), { wrapper: Wrapper });
    const directory = renderHook(() => useStatementPropertyDirectory(), { wrapper: Wrapper });
    await waitFor(() => expect(statements.result.current.isSuccess).toBe(true));
    expect(directory.result.current.isError).toBe(true);
    expect(statements.result.current.isError).toBe(false);
  });

  it("does not retry a 4xx through the shared policy", async () => {
    listStatements.mockRejectedValue(new ApiError({ code: "FORBIDDEN", message: "no", status: 403 }));
    const client = new QueryClient();
    const Wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    const { result } = renderHook(() => useStatementsList({}, 1), { wrapper: Wrapper });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(listStatements).toHaveBeenCalledTimes(1);
  });
});
