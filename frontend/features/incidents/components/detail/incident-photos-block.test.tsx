import type { UseQueryResult } from "@tanstack/react-query";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen, fireEvent, waitFor } from "@/test/render";

import type { IncidentPhotoDto } from "../../data";

const useIncidentPhotosMock = vi.hoisted(() => vi.fn());
const invalidateQueriesMock = vi.hoisted(() => vi.fn());

vi.mock("../../hooks/use-incidents", () => ({
  useIncidentPhotos: useIncidentPhotosMock,
}));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: "tenant-1" } }),
}));
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({ invalidateQueries: invalidateQueriesMock }),
}));

import { IncidentPhotosBlock } from "./incident-photos-block";

function makeQueryResult(
  overrides: Partial<UseQueryResult<IncidentPhotoDto[], Error>> = {},
): UseQueryResult<IncidentPhotoDto[], Error> {
  return {
    isPending: false,
    isError: false,
    isSuccess: true,
    data: [],
    error: null,
    refetch: vi.fn(),
    ...overrides,
  } as unknown as UseQueryResult<IncidentPhotoDto[], Error>;
}

function photo(overrides: Partial<IncidentPhotoDto> = {}): IncidentPhotoDto {
  return {
    id: "photo-1",
    incidentId: "incident-1",
    stage: "BEFORE",
    uploadedBy: "tech-1",
    createdAt: "2026-09-18T09:00:00Z",
    url: "/api/v1/incident-photos/photo-1?exp=1&sig=a",
    ...overrides,
  } as IncidentPhotoDto;
}

function renderBlock() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <I18nProvider locale="es">
        <IncidentPhotosBlock incidentId="incident-1" />
      </I18nProvider>
    </QueryClientProvider>,
  );
}

describe("IncidentPhotosBlock (R1.1-R1.6)", () => {
  beforeEach(() => {
    invalidateQueriesMock.mockReset();
    useIncidentPhotosMock.mockReturnValue(makeQueryResult());
  });

  it("shows the loading state while the query is pending (R1.2)", () => {
    useIncidentPhotosMock.mockReturnValue(
      makeQueryResult({ isPending: true, isSuccess: false, data: undefined }),
    );
    renderBlock();
    expect(screen.getByText("Cargando las fotos…")).toBeInTheDocument();
  });

  it("shows the empty state when there are no photos (R1.3)", () => {
    renderBlock();
    expect(screen.getByText("Todavía no hay fotos")).toBeInTheDocument();
  });

  it("shows the error state with a retry that refetches (R1.2)", () => {
    const refetch = vi.fn();
    useIncidentPhotosMock.mockReturnValue(
      makeQueryResult({
        isError: true,
        isSuccess: false,
        data: undefined,
        error: new Error("network broken"),
        refetch,
      }),
    );
    renderBlock();
    expect(
      screen.getByText("No hemos podido cargar las fotos"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });

  it("groups photos by the fixed BEFORE/AFTER stage order and paints urls verbatim (R1.1, R1.4)", () => {
    useIncidentPhotosMock.mockReturnValue(
      makeQueryResult({
        data: [
          photo({ id: "p1", stage: "AFTER", url: "/photo/p1" }),
          photo({ id: "p2", stage: "BEFORE", url: "/photo/p2" }),
          photo({ id: "p3", stage: "AFTER", url: "/photo/p3" }),
        ],
      }),
    );
    renderBlock();
    const headings = screen.getAllByRole("heading", { level: 3 });
    expect(headings.map((h) => h.textContent)).toEqual(["Antes", "Después"]);
    const images = screen.getAllByRole("img") as HTMLImageElement[];
    expect(images.map((img) => img.src)).toEqual([
      expect.stringContaining("/photo/p2"),
      expect.stringContaining("/photo/p1"),
      expect.stringContaining("/photo/p3"),
    ]);
  });

  it("does not offer any upload or delete control (R1.5)", () => {
    useIncidentPhotosMock.mockReturnValue(
      makeQueryResult({ data: [photo()] }),
    );
    renderBlock();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("textbox", { name: /file/i }),
    ).not.toBeInTheDocument();
  });

  it("re-fetches the photo list at most once per photo id on image error (R1.6)", async () => {
    useIncidentPhotosMock.mockReturnValue(
      makeQueryResult({ data: [photo({ id: "p1", url: "/photo/p1" })] }),
    );
    renderBlock();
    const img = screen.getByRole("img");
    fireEvent.error(img);
    fireEvent.error(img);
    await waitFor(() => expect(invalidateQueriesMock).toHaveBeenCalledTimes(1));
    expect(invalidateQueriesMock).toHaveBeenCalledWith({
      queryKey: ["tenant", "tenant-1", "incidents-photos", "incident-1"],
    });
  });
});
