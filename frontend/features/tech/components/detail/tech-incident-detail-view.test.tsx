import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { ApiError } from "@/lib/api";
import esTech from "@/locales/es/tech.json";
import type { IncidentStatus } from "@/features/incidents";
import * as incidentsData from "@/features/incidents/data";

const TENANT = "tenant-1";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ user: { tenant_id: TENANT } }),
}));

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

const getIncident = vi.fn();
const getIncidentContext = vi.fn();
const listPhotos = vi.fn();
const accept = vi.fn();
const enRoute = vi.fn();
const reject = vi.fn();
const waitParts = vi.fn();
const resume = vi.fn();
const resolve = vi.fn();
const uploadPhoto = vi.fn();

vi.spyOn(incidentsData, "getIncidentsDataSource").mockImplementation(
  () =>
    ({
      getIncident,
      getIncidentContext,
      listPhotos,
      accept,
      enRoute,
      reject,
      waitParts,
      resume,
      resolve,
      uploadPhoto,
    }) as unknown as ReturnType<typeof incidentsData.getIncidentsDataSource>,
);

import { TechIncidentDetailView } from "./tech-incident-detail-view";
import { formatDateTime } from "../../lib/format";

function incident(overrides: Record<string, unknown> = {}) {
  return {
    id: "i1",
    propertyId: "p1",
    reservationId: null,
    source: "GUEST",
    category: "WATER",
    severity: "HIGH",
    status: "ASSIGNED" as IncidentStatus,
    title: "Fuga en el baño",
    description: "Gotea bajo el lavabo",
    aiSummary: null,
    assignedTechnicianId: "t1",
    ownerApprovalRequired: false,
    etaAt: null,
    estimatedCost: null,
    approvedCost: null,
    finalCost: null,
    materials: null,
    resolvedAt: null,
    createdAt: "2026-08-12T08:00:00Z",
    updatedAt: "2026-08-12T08:00:00Z",
    ...overrides,
  };
}

const CONTEXT = {
  propertyName: "Piso Sol",
  propertyInternalCode: "MAD-01",
  addressLine1: "Calle Mayor 1",
  addressLine2: null,
  city: "Madrid",
  province: "Madrid",
  postalCode: "28013",
  country: "ES",
  timezone: "Europe/Madrid",
  accessNotes: "Portal 2, código 4571",
  assignmentNote: "Llama al llegar",
};

function renderDetail() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <I18nProvider locale="es">{children}</I18nProvider>
    </QueryClientProvider>
  );
  return {
    client,
    ...render(<TechIncidentDetailView incidentId="i1" />, { wrapper }),
  };
}

describe("TechIncidentDetailView (R2–R5)", () => {
  beforeEach(() => {
    replace.mockReset();
    for (const mock of [
      getIncident,
      getIncidentContext,
      listPhotos,
      accept,
      enRoute,
      reject,
      waitParts,
      resume,
      resolve,
      uploadPhoto,
    ]) {
      mock.mockReset();
    }
    getIncident.mockResolvedValue(incident());
    getIncidentContext.mockResolvedValue(CONTEXT);
    listPhotos.mockResolvedValue([]);
    accept.mockResolvedValue(incident({ status: "ACCEPTED" }));
  });

  it("(a) renders the incident fields and the context, access notes verbatim (R2.2, R2.3)", async () => {
    renderDetail();

    expect(await screen.findByText("Fuga en el baño")).toBeInTheDocument();
    expect(screen.getByText("Gotea bajo el lavabo")).toBeInTheDocument();
    expect(screen.getByText("Piso Sol")).toBeInTheDocument();
    expect(screen.getByText("Calle Mayor 1")).toBeInTheDocument();
    expect(screen.getByText("Portal 2, código 4571")).toBeInTheDocument();
    expect(screen.getByText("Llama al llegar")).toBeInTheDocument();
    expect(screen.getByText("Europe/Madrid")).toBeInTheDocument();
  });

  it("(a) renders inline nulls as the em-dash (R2.4)", async () => {
    renderDetail();

    await screen.findByText("Fuga en el baño");
    // etaAt, estimatedCost, approvedCost, finalCost, materials, resolvedAt.
    expect(screen.getAllByText("—")).toHaveLength(6);
  });

  it("(i) a 404 on the detail renders `not available` with the way back to /tech (R2.6)", async () => {
    getIncident.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "x" }),
    );
    renderDetail();

    expect(
      await screen.findByText(esTech.detail.unavailable.title),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: esTech.detail.back })).toHaveAttribute(
      "href",
      "/tech",
    );
  });

  it("(i) a 404 on the context alone is also `not available` (R2.6)", async () => {
    getIncidentContext.mockRejectedValue(
      new ApiError({ status: 404, code: "NOT_FOUND", message: "x" }),
    );
    renderDetail();

    expect(
      await screen.findByText(esTech.detail.unavailable.title),
    ).toBeInTheDocument();
  });

  it.each<[IncidentStatus, string[], string[]]>([
    ["ASSIGNED", [esTech.actions.accept, esTech.actions.reject], [esTech.actions.resume]],
    ["ACCEPTED", [esTech.actions["en-route"], esTech.actions.reject], [esTech.actions.accept]],
    ["IN_PROGRESS", [esTech.actions["wait-parts"], esTech.resolve.submit], [esTech.actions.reject]],
    ["WAITING_EXTERNAL_PARTS", [esTech.actions.resume], [esTech.actions.accept]],
  ])(
    "(b) %s offers exactly the actions of the D6 table",
    async (status, offered, notOffered) => {
      getIncident.mockResolvedValue(incident({ status }));
      renderDetail();

      for (const label of offered) {
        expect(
          await screen.findByRole("button", { name: label }),
        ).toBeInTheDocument();
      }
      for (const label of notOffered) {
        expect(screen.queryByRole("button", { name: label })).toBeNull();
      }
    },
  );

  it.each<[IncidentStatus, string]>([
    ["AWAITING_OWNER_APPROVAL", esTech.actions.none["awaiting-owner"]],
    ["RESOLVED", esTech.actions.none.closed],
    ["CANCELLED", esTech.actions.none.closed],
  ])("(b) %s offers no cycle action and says why (R3.2)", async (status, copy) => {
    getIncident.mockResolvedValue(incident({ status }));
    renderDetail();

    expect(await screen.findByText(copy)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: esTech.actions.accept })).toBeNull();
  });

  it("(c) `Accept` with no ETA sends no body at all (R3.3)", async () => {
    renderDetail();

    fireEvent.click(await screen.findByRole("button", { name: esTech.actions.accept }));

    await waitFor(() => expect(accept).toHaveBeenCalled());
    expect(accept).toHaveBeenCalledWith(TENANT, "i1", undefined);
  });

  it("(c) `Accept` with an ETA sends the instant with a zone (R3.3)", async () => {
    renderDetail();
    await screen.findByRole("button", { name: esTech.actions.accept });

    fireEvent.change(screen.getByLabelText(esTech.eta.label), {
      target: { value: "2026-08-12T18:30" },
    });
    fireEvent.click(screen.getByRole("button", { name: esTech.actions.accept }));

    await waitFor(() => expect(accept).toHaveBeenCalled());
    const sent = accept.mock.calls[0][2] as string;
    expect(sent.endsWith("Z")).toBe(true);
    expect(new Date(sent).getTime()).toBe(
      new Date("2026-08-12T18:30").getTime(),
    );
  });

  it("(c) a 422 on the ETA keeps what was typed (R3.4)", async () => {
    accept.mockRejectedValue(
      new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "past" }),
    );
    renderDetail();
    await screen.findByRole("button", { name: esTech.actions.accept });

    fireEvent.change(screen.getByLabelText(esTech.eta.label), {
      target: { value: "2020-01-01T10:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: esTech.actions.accept }));

    expect(await screen.findByText(esTech.eta.invalid)).toBeInTheDocument();
    expect(screen.getByLabelText(esTech.eta.label)).toHaveValue(
      "2020-01-01T10:00",
    );
  });

  /**
   * `wait-parts` carries no body at all, so a 422 on it cannot be about the
   * ETA. Telling the technician "the server did not accept that time" names a
   * field they never filled in — R3.4 governs the ETA case, not every 422.
   */
  it("(c) a 422 on an action that sent no ETA does not blame the ETA (R3.4)", async () => {
    getIncident.mockResolvedValue(incident({ status: "IN_PROGRESS" }));
    waitParts.mockRejectedValue(
      new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "nope" }),
    );
    renderDetail();

    fireEvent.click(
      await screen.findByRole("button", { name: esTech.actions["wait-parts"] }),
    );

    expect(await screen.findByText(esTech.actions.error)).toBeInTheDocument();
    expect(screen.queryByText(esTech.eta.invalid)).toBeNull();
  });

  it.each<[IncidentStatus, string]>([
    ["RESOLVED", esTech.actions.conflict.closed],
    ["AWAITING_OWNER_APPROVAL", esTech.actions.conflict["awaiting-owner"]],
    ["ACCEPTED", esTech.actions.conflict["out-of-order"]],
  ])(
    "(d) a 409 shows the reason derived from the refreshed status %s (R3.7, D7)",
    async (refreshedStatus, copy) => {
      // The first read is the status the screen mounted with; the refresh the
      // mutation triggers in `onSettled` brings the one that explains the
      // refusal, which is what `conflictReason` reads.
      getIncident
        .mockResolvedValueOnce(incident({ status: "WAITING_EXTERNAL_PARTS" }))
        .mockResolvedValue(incident({ status: refreshedStatus }));
      resume.mockRejectedValue(
        new ApiError({ status: 409, code: "CONFLICT", message: "english" }),
      );
      renderDetail();

      fireEvent.click(
        await screen.findByRole("button", { name: esTech.actions.resume }),
      );

      expect(await screen.findByText(copy)).toBeInTheDocument();
      expect(screen.queryByText("english")).toBeNull();
      expect(resume).toHaveBeenCalledTimes(1);
    },
  );

  it("(e) a close answered RESOLVED presents the incident as closed with its cost", async () => {
    getIncident.mockResolvedValue(
      incident({
        status: "RESOLVED",
        finalCost: "120.50",
        materials: "Junta de 12 mm",
        resolvedAt: "2026-08-12T12:00:00Z",
      }),
    );
    renderDetail();

    expect(
      await screen.findByText(esTech.resolve.resolved.title),
    ).toBeInTheDocument();
    // R4.2 names three things a closed incident must show. The test used to
    // assert only `materials`, leaving the other two unverified.
    expect(screen.getByText("Junta de 12 mm")).toBeInTheDocument();
    expect(screen.getByText("120,50")).toBeInTheDocument();
    expect(
      screen.getByText(formatDateTime("2026-08-12T12:00:00Z", "es")),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(esTech.resolve.awaitingOwner.title),
    ).toBeNull();
  });

  it("(e) a close answered AWAITING_OWNER_APPROVAL says so and shows no resolvedAt (R4.3)", async () => {
    getIncident.mockResolvedValue(
      incident({
        status: "AWAITING_OWNER_APPROVAL",
        finalCost: "980.00",
        resolvedAt: null,
      }),
    );
    renderDetail();

    expect(
      await screen.findByText(esTech.resolve.awaitingOwner.title),
    ).toBeInTheDocument();
    expect(screen.queryByText(esTech.resolve.resolved.title)).toBeNull();
    expect(screen.getByText("980,00")).toBeInTheDocument();
    // `resolvedAt` arrives null and is painted as the em-dash, never invented.
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);
  });

  it("(e) never shows or anticipates the owner-approval threshold (R4.4)", async () => {
    getIncident.mockResolvedValue(
      incident({ status: "AWAITING_OWNER_APPROVAL", finalCost: "980.00" }),
    );
    const { container } = renderDetail();

    await screen.findByText(esTech.resolve.awaitingOwner.title);
    expect(container.textContent ?? "").not.toMatch(/threshold|umbral/i);
  });

  it("(f) local validation of the close emits no request (R4.5)", async () => {
    getIncident.mockResolvedValue(incident({ status: "IN_PROGRESS" }));
    renderDetail();

    fireEvent.click(
      await screen.findByRole("button", { name: esTech.resolve.submit }),
    );

    expect(
      await screen.findByText(esTech.resolve.errors.required),
    ).toBeInTheDocument();
    expect(resolve).not.toHaveBeenCalled();
  });

  it("(f) a 422 on the close does not empty the form (R4.5)", async () => {
    getIncident.mockResolvedValue(incident({ status: "IN_PROGRESS" }));
    resolve.mockRejectedValue(
      new ApiError({ status: 422, code: "VALIDATION_ERROR", message: "x" }),
    );
    renderDetail();

    const cost = await screen.findByLabelText(esTech.resolve.finalCost);
    fireEvent.change(cost, { target: { value: "120.50" } });
    fireEvent.change(screen.getByLabelText(esTech.resolve.materials), {
      target: { value: "Junta" },
    });
    fireEvent.click(screen.getByRole("button", { name: esTech.resolve.submit }));

    expect(
      await screen.findByText(esTech.resolve.errors.server),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(esTech.resolve.finalCost)).toHaveValue(120.5);
    expect(screen.getByLabelText(esTech.resolve.materials)).toHaveValue("Junta");
  });

  it("(f) the close sends final_cost as the typed string (D12)", async () => {
    getIncident.mockResolvedValue(incident({ status: "IN_PROGRESS" }));
    resolve.mockResolvedValue(incident({ status: "RESOLVED" }));
    renderDetail();

    fireEvent.change(await screen.findByLabelText(esTech.resolve.finalCost), {
      target: { value: "120.50" },
    });
    fireEvent.click(screen.getByRole("button", { name: esTech.resolve.submit }));

    await waitFor(() => expect(resolve).toHaveBeenCalled());
    expect(resolve.mock.calls[0][2]).toEqual({
      finalCost: "120.50",
      materials: "",
    });
  });

  it("(g) the gallery paints each url verbatim, grouped by stage (R5.1, R5.2)", async () => {
    const before = "/api/v1/incident-photos/b?exp=1&sig=x";
    const after = "https://bucket.s3.example/after.jpg?X-Amz-Signature=y";
    listPhotos.mockResolvedValue([
      { id: "b", incidentId: "i1", stage: "BEFORE", uploadedBy: "u", createdAt: "2026-08-12T08:00:00Z", url: before },
      { id: "a", incidentId: "i1", stage: "AFTER", uploadedBy: "u", createdAt: "2026-08-12T09:00:00Z", url: after },
    ]);
    renderDetail();

    const images = await screen.findAllByRole("img");
    expect(images.map((image) => image.getAttribute("src"))).toEqual([
      before,
      after,
    ]);
    expect(screen.getByText(esTech.photos.stage.BEFORE)).toBeInTheDocument();
    expect(screen.getByText(esTech.photos.stage.AFTER)).toBeInTheDocument();
  });

  it("(g) a broken image re-lists at most once per photo (D10)", async () => {
    listPhotos.mockResolvedValue([
      { id: "b", incidentId: "i1", stage: "BEFORE", uploadedBy: "u", createdAt: "2026-08-12T08:00:00Z", url: "/expired" },
    ]);
    renderDetail();

    const image = await screen.findByRole("img");
    fireEvent.error(image);
    await waitFor(() => expect(listPhotos).toHaveBeenCalledTimes(2));

    fireEvent.error(await screen.findByRole("img"));
    fireEvent.error(await screen.findByRole("img"));
    await new Promise((done) => setTimeout(done, 50));
    expect(listPhotos).toHaveBeenCalledTimes(2);
  });

  it("(g) offers no way to delete a photo (R5.7)", async () => {
    listPhotos.mockResolvedValue([
      { id: "b", incidentId: "i1", stage: "BEFORE", uploadedBy: "u", createdAt: "2026-08-12T08:00:00Z", url: "/b" },
    ]);
    const { container } = renderDetail();

    await screen.findByRole("img");
    expect(container.textContent ?? "").not.toMatch(/borrar|eliminar|delete/i);
  });

  it.each<[IncidentStatus, boolean]>([
    ["IN_PROGRESS", true],
    ["WAITING_EXTERNAL_PARTS", true],
    ["ASSIGNED", false],
    ["ACCEPTED", false],
    ["AWAITING_OWNER_APPROVAL", false],
    ["RESOLVED", false],
    ["CANCELLED", false],
  ])("(h) %s offers the upload: %s (R5.3)", async (status, offered) => {
    getIncident.mockResolvedValue(incident({ status }));
    renderDetail();

    await screen.findByText("Fuga en el baño");
    const control = screen.queryByLabelText(esTech.upload.file);
    expect(control !== null).toBe(offered);
  });

  it.each<[number, string]>([
    [409, esTech.upload.errors.conflict],
    [413, esTech.upload.errors.tooLarge],
    [422, esTech.upload.errors.unsupportedFormat],
    [502, esTech.upload.errors.storage],
  ])(
    "(h) the upload shows its own message for a %s and does not retry (R5.6)",
    async (status, copy) => {
      getIncident.mockResolvedValue(incident({ status: "IN_PROGRESS" }));
      uploadPhoto.mockRejectedValue(
        new ApiError({ status, code: "X", message: "english detail" }),
      );
      renderDetail();

      const input = (await screen.findByLabelText(
        esTech.upload.file,
      )) as HTMLInputElement;
      fireEvent.change(input, {
        target: {
          files: [new File(["bytes"], "photo.jpg", { type: "image/jpeg" })],
        },
      });
      fireEvent.click(screen.getByRole("button", { name: esTech.upload.submit }));

      expect(await screen.findByText(copy)).toBeInTheDocument();
      expect(screen.queryByText("english detail")).toBeNull();
      expect(uploadPhoto).toHaveBeenCalledTimes(1);
    },
  );

  /**
   * The 409 refresh (design D8) is what makes the screen honest: the manager
   * cancels the incident while the technician is picking a file, the upload is
   * refused, the incident is re-read — and the form **withdraws** (R5.3 offers
   * it only in `IN_PROGRESS`/`WAITING_EXTERNAL_PARTS`) while the action bar
   * says what the incident became. This is why the upload's own 409 copy names
   * no reason: by the time a reason existed, this component is gone.
   */
  it.each<[string, string]>([
    ["CANCELLED", esTech.actions.none.closed],
    ["AWAITING_OWNER_APPROVAL", esTech.actions.none["awaiting-owner"]],
  ])(
    "(h) a 409 refreshed to %s withdraws the upload and the screen explains (R5.3, R5.6, D8)",
    async (refreshedStatus, copy) => {
      getIncident
        .mockResolvedValueOnce(incident({ status: "IN_PROGRESS" }))
        .mockResolvedValue(
          incident({ status: refreshedStatus as IncidentStatus }),
        );
      uploadPhoto.mockRejectedValue(
        new ApiError({ status: 409, code: "CONFLICT", message: "english" }),
      );
      renderDetail();

      const input = (await screen.findByLabelText(
        esTech.upload.file,
      )) as HTMLInputElement;
      fireEvent.change(input, {
        target: {
          files: [new File(["bytes"], "photo.jpg", { type: "image/jpeg" })],
        },
      });
      fireEvent.click(screen.getByRole("button", { name: esTech.upload.submit }));

      // The screen now says what happened...
      expect(await screen.findByText(copy)).toBeInTheDocument();
      // ...and stops offering an upload the state no longer admits.
      await waitFor(() =>
        expect(screen.queryByLabelText(esTech.upload.file)).toBeNull(),
      );
      expect(screen.queryByText("english")).toBeNull();
    },
  );

  it("(h) the photo gallery uses the shared states, so load is aria-busy (R6.2)", async () => {
    listPhotos.mockReturnValue(new Promise(() => {}));
    renderDetail();

    await screen.findByText("Fuga en el baño");
    const busy = screen
      .getAllByRole("status")
      .filter((node) => node.getAttribute("aria-busy") === "true");
    expect(busy.length).toBeGreaterThan(0);
  });

  it("(h) a failed photo list is an alert, not a bare paragraph (R6.2)", async () => {
    listPhotos.mockRejectedValue(
      new ApiError({ status: 400, code: "BOOM", message: "english detail" }),
    );
    renderDetail();

    expect(
      await screen.findByText(esTech.photos.error.title),
    ).toBeInTheDocument();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("english detail")).toBeNull();
  });

  it("(h) an empty photo list renders the shared EmptyState (R6.2)", async () => {
    listPhotos.mockResolvedValue([]);
    renderDetail();

    // Asserts the structure `EmptyState` uniquely provides, not just its copy:
    // a `<p>` carrying the same key satisfied the old assertion and survived a
    // mutation. `StatePanel` renders the title as a **heading** and the
    // description as its own node, and D14 keeps the empty state neutral — no
    // alert, no busy semantics, which is what separates it from Error/Loading.
    expect(
      await screen.findByRole("heading", { name: esTech.photos.empty.title }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(esTech.photos.empty.description),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  /**
   * R3.5's navigation half. The hook stopped owning the route in this cycle
   * (it now calls `onRejected`), so without this the only assertion that the
   * technician actually leaves `/tech/incidents/[id]` would have disappeared
   * with the hook test that used to make it.
   */
  it("(d) a successful reject returns the technician to /tech (R3.5)", async () => {
    reject.mockResolvedValue(incident({ status: "OPEN" }));
    renderDetail();

    fireEvent.click(
      await screen.findByRole("button", { name: esTech.actions.reject }),
    );

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/tech"));
  });

  it("(h) the 422 message names JPEG, PNG and WebP (R5.6)", () => {
    expect(esTech.upload.errors.unsupportedFormat).toMatch(/JPEG/);
    expect(esTech.upload.errors.unsupportedFormat).toMatch(/PNG/);
    expect(esTech.upload.errors.unsupportedFormat).toMatch(/WebP/);
  });

  it("(h) does not present a photo as a requirement of the close (R5.7)", async () => {
    getIncident.mockResolvedValue(incident({ status: "IN_PROGRESS" }));
    renderDetail();

    expect(await screen.findByText(esTech.upload.optional)).toBeInTheDocument();
    // The close is on offer with no photo uploaded.
    expect(
      screen.getByRole("button", { name: esTech.resolve.submit }),
    ).toBeEnabled();
  });

  it("calls no /api/v1/properties route from this screen (R2.5)", async () => {
    renderDetail();
    await screen.findByText("Piso Sol");

    // The only source these screens reach is `HttpIncidentsSource`, and the
    // methods this view can call are exactly the ones mocked above.
    expect(getIncidentContext).toHaveBeenCalledWith(TENANT, "i1");
  });
});
