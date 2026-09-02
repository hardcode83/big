import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor, within } from "@/test/render";
import { getA11yViolations } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";
import { ApiError } from "@/lib/api";
import { PORTAL_THREAD_POLL_MS } from "../hooks/use-conversation";

const source = vi.hoisted(() => ({
  getStayInfo: vi.fn(),
  getCheckinStatus: vi.fn(),
  submitCheckin: vi.fn(),
  reportIncident: vi.fn(),
  getConversation: vi.fn(),
  postMessage: vi.fn(),
}));

vi.mock("@/features/guest-portal/data", () => ({
  getGuestPortalDataSource: () => source,
}));

import { GuestPortalView } from "./guest-portal-view";

const TOKEN = "opaque-secret-token-2f9a";

const STAY = {
  accessCodeMasked: "••1234",
  addressLine1: "Calle Redes 11",
  addressLine2: null,
  arrivalNotes: "Sube al 3º",
  checkInDate: "2026-08-11",
  checkInTime: "15:00",
  checkOutDate: "2026-08-12",
  checkOutTime: "11:00",
  city: "Madrid",
  country: "ES",
  postalCode: "28001",
  propertyName: "Casa Redes",
  province: "Madrid",
  supportChannel: "+34 600 000 000",
  timezone: "Europe/Madrid",
  wifiName: "CasaWifi",
};

const EMPTY_THREAD = { items: [], total: 0, page: 1, perPage: 50, state: "AUTOMATIC" as const };

const THREAD = {
  items: [
    { id: "m1", sender: "GUEST" as const, content: "¿A qué hora puedo entrar?", createdAt: "2026-08-30T10:00:00Z" },
    { id: "m2", sender: "PROPERTY" as const, content: "La entrada es a partir de las 15:00.", createdAt: "2026-08-30T10:00:01Z" },
  ],
  total: 2,
  page: 1,
  perPage: 50,
  state: "AUTOMATIC" as const,
};

const CHECKIN_STATUS = {
  documentStatus: "NOT_PROVIDED" as const,
  legalRegistrationStatus: "PENDING_GUEST_DATA" as const,
  missingFields: ["full_name"],
};

function renderView(token = TOKEN) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <I18nProvider locale="es">{children}</I18nProvider>
    </QueryClientProvider>
  );
  return render(<GuestPortalView token={token} />, { wrapper });
}

function fillCheckin(number = "DOC-VALUE") {
  fireEvent.change(screen.getByLabelText("Nombre completo"), { target: { value: "Ana" } });
  fireEvent.change(screen.getByLabelText("Nacionalidad"), { target: { value: "ES" } });
  fireEvent.change(screen.getByLabelText("Fecha de nacimiento"), { target: { value: "1990-01-01" } });
  fireEvent.change(screen.getByLabelText("Número de documento"), { target: { value: number } });
  fireEvent.change(screen.getByLabelText("Caducidad del documento"), { target: { value: "2030-01-01" } });
}

beforeEach(() => {
  vi.clearAllMocks();
  source.getStayInfo.mockResolvedValue(STAY);
  source.getCheckinStatus.mockResolvedValue(CHECKIN_STATUS);
  source.submitCheckin.mockResolvedValue({ documentStatus: "PROVIDED", legalRegistrationStatus: "SUBMITTED" });
  source.reportIncident.mockResolvedValue({ id: "11111111-1111-1111-1111-111111111111", status: "OPEN", createdAt: "2026-08-11T10:00:00Z" });
  source.getConversation.mockResolvedValue(EMPTY_THREAD);
  source.postMessage.mockResolvedValue({ id: "m1", sender: "GUEST", content: "Hola", createdAt: "2026-08-30T10:00:00Z" });
});


/**
 * The conversation section's own live region.
 *
 * Scoped rather than global: the check-in and incident sections each own a `role="alert"` too,
 * so `screen.getByRole("alert")` is ambiguous — which is correct page structure, not a bug. A
 * test that reached for the first one would silently assert about another section's status.
 */
function conversationAlert() {
  return within(screen.getByRole("region", { name: "Conversación" })).getByRole("alert");
}

/**
 * `useConversation` uses the shared `retryPolicy`, which retries a `5xx` twice with React
 * Query's exponential backoff — so the error state genuinely takes a few seconds to settle.
 * That is the production behaviour these tests are about, so the wait is widened rather than
 * the policy weakened.
 */
const RETRY_SETTLE_MS = 8000;

/**
 * Vitest's own per-test budget for the three tests that wait out `RETRY_SETTLE_MS`.
 *
 * `frontend/vitest.config.ts` sets no `testTimeout`, so the default is 5000 ms — **less** than
 * the assertion timeout above. Widening only the inner `findByText` was therefore protection
 * against exactly the slow-runner condition it could not survive: vitest would kill the test at
 * 5 s before the 8 s allowance was ever reached. Raised together, and deliberately a little
 * above it so the assertion is what fails (with a useful message) rather than the harness.
 * Found by the CI/CD panel of sections 9-10.
 */
const RETRY_TEST_TIMEOUT_MS = RETRY_SETTLE_MS + 4000;

describe("404 gate (R1.2, task 3.3)", () => {
  it("shows one uniform invalid-link state and hides check-in/incident, without internal detail", async () => {
    source.getStayInfo.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "tenant xyz reservation gone", status: 404, details: { trace: "app/guest/service.py:42" } }),
    );
    renderView();

    expect(await screen.findByText("Este enlace no es válido")).toBeInTheDocument();
    expect(screen.getByText("Pide a tu anfitrión un enlace nuevo.")).toBeInTheDocument();
    // Check-in and incident forms are not rendered on a dead link.
    expect(screen.queryByText("Check-in")).not.toBeInTheDocument();
    expect(screen.queryByText("Comunicar una incidencia")).not.toBeInTheDocument();
    // No internal cause / trace / tenant leaks into the page.
    expect(document.body.innerHTML).not.toMatch(/tenant xyz|service\.py|trace/i);
  });
});

describe("render security regression (R1.3, R2.2, task 3.4)", () => {
  it("never renders the token anywhere on the page", async () => {
    renderView();
    await screen.findByText("Casa Redes");
    expect(document.body.innerHTML).not.toContain(TOKEN);
    expect(document.title).not.toContain(TOKEN);
  });

  it("does not echo the document number after a successful check-in", async () => {
    renderView();
    await screen.findByText("Casa Redes");
    await screen.findByLabelText("Número de documento");
    fillCheckin("ZZ-SECRET-999");
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    await screen.findByText(/Check-in enviado/);
    const alert = screen.getByText(/Check-in enviado/);
    expect(alert.textContent).not.toContain("ZZ-SECRET-999");
  });

  it("masks nothing itself: renders the already-masked access code verbatim", async () => {
    renderView();
    expect(await screen.findByText("••1234")).toBeInTheDocument();
  });
});

describe("stay & status presentation (R1.1, R1.4, R2.1)", () => {
  it("renders a localized safe absence for null stay fields, never the literal null/undefined", async () => {
    source.getStayInfo.mockResolvedValue({ ...STAY, wifiName: null, arrivalNotes: null });
    renderView();
    await screen.findByText("Casa Redes");
    expect(document.body.innerHTML).not.toMatch(/>\s*(null|undefined)\s*</);
    expect(screen.getAllByText("No disponible").length).toBeGreaterThanOrEqual(2);
  });

  it("shows missing_fields verbatim as backend-declared info, without inferring steps", async () => {
    renderView();
    expect(await screen.findByText("Estado: full_name")).toBeInTheDocument();
  });
});

describe("check-in journey (R2, task 4.3)", () => {
  it("sends exactly the six contract fields and shows both localized statuses", async () => {
    renderView();
    await screen.findByLabelText("Número de documento");
    fillCheckin("X123");
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    await waitFor(() => expect(source.submitCheckin).toHaveBeenCalledTimes(1));
    expect(source.submitCheckin).toHaveBeenCalledWith(TOKEN, {
      full_name: "Ana",
      nationality: "ES",
      date_of_birth: "1990-01-01",
      document_type: "DNI",
      document_number: "X123",
      document_expiry_date: "2030-01-01",
    });
    expect(await screen.findByText(/Aportado/)).toBeInTheDocument();
    expect(screen.getByText(/Enviado/)).toBeInTheDocument();
  });

  it("blocks empty submits client-side without calling the API", async () => {
    renderView();
    await screen.findByLabelText("Nombre completo");
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    expect(await screen.findAllByText("Este campo es obligatorio.")).not.toHaveLength(0);
    expect(source.submitCheckin).not.toHaveBeenCalled();
  });

  it("disables the submit button while the mutation is in flight (no duplicates)", async () => {
    source.submitCheckin.mockReturnValue(new Promise(() => {}));
    renderView();
    await screen.findByLabelText("Número de documento");
    fillCheckin();
    const button = screen.getByRole("button", { name: "Enviar check-in" });
    fireEvent.click(button);

    await waitFor(() => expect(button).toBeDisabled());
    fireEvent.click(button);
    expect(source.submitCheckin).toHaveBeenCalledTimes(1);
  });

  it("maps a 422 to the offending field, without leaking the raw body", async () => {
    source.submitCheckin.mockRejectedValue(
      new ApiError({
        code: "VALIDATION_ERROR",
        message: "Request validation failed",
        status: 422,
        details: { errors: [{ loc: ["body", "full_name"], msg: "RAW_BACKEND_MSG", type: "value_error" }] },
      }),
    );
    renderView();
    await screen.findByLabelText("Número de documento");
    fillCheckin();
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    await waitFor(() => expect(screen.getByLabelText("Nombre completo")).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText("Revisa este campo.")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("RAW_BACKEND_MSG");
  });
});

describe("incident journey (R3, task 5.2)", () => {
  it("blocks an invalid report without any API call", async () => {
    renderView();
    await screen.findByLabelText("Título");
    fireEvent.click(screen.getByRole("button", { name: "Enviar aviso" }));

    expect(source.reportIncident).not.toHaveBeenCalled();
  });

  it("sends only title and description and confirms without the UUID", async () => {
    renderView();
    await screen.findByLabelText("Título");
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Fuga" } });
    fireEvent.change(screen.getByLabelText("Descripción"), { target: { value: "Agua en la cocina" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar aviso" }));

    await waitFor(() => expect(source.reportIncident).toHaveBeenCalledWith(TOKEN, { title: "Fuga", description: "Agua en la cocina" }));
    expect(await screen.findByText(/Incidencia comunicada/)).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("11111111-1111-1111-1111-111111111111");
  });

  it("on 429 tells the guest to wait without confirming or denying creation", async () => {
    source.reportIncident.mockRejectedValue(new ApiError({ code: "RATE_LIMITED", message: "slow down", status: 429 }));
    renderView();
    await screen.findByLabelText("Título");
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Fuga" } });
    fireEvent.change(screen.getByLabelText("Descripción"), { target: { value: "Agua" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar aviso" }));

    const message = await screen.findByText(/Espera antes de volver a intentarlo/);
    expect(message).toBeInTheDocument();
    expect(message.textContent).toMatch(/No sabemos si se recibió/);
  });
});

describe("token cache isolation (R5, task 1.3)", () => {
  it("never serves one token's cached stay data to a different token", async () => {
    // A single client shared across both renders, so any bleed would come through
    // its cache. Token A resolves; token B is kept pending, so the only way B could
    // ever show "Casa A" is a colliding (token-less) cache key. It must not.
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <I18nProvider locale="es">{children}</I18nProvider>
      </QueryClientProvider>
    );
    source.getStayInfo.mockImplementation((token: string) =>
      token === "token-a" ? Promise.resolve({ ...STAY, propertyName: "Casa A" }) : new Promise(() => {}),
    );
    source.getCheckinStatus.mockImplementation((token: string) =>
      token === "token-a" ? Promise.resolve(CHECKIN_STATUS) : new Promise(() => {}),
    );

    const first = render(<GuestPortalView token="token-a" />, { wrapper });
    expect(await screen.findByText("Casa A")).toBeInTheDocument();
    first.unmount();

    render(<GuestPortalView token="token-b" />, { wrapper });
    // B has no cache entry of its own and its query is still pending → it must show
    // the loading state, and crucially must never surface A's cached "Casa A".
    expect(await screen.findByText("Cargando…")).toBeInTheDocument();
    expect(screen.queryByText("Casa A")).not.toBeInTheDocument();
  });
});

describe("safe error mapping for 413/5xx (R5.3, tasks 4.3, 5.2)", () => {
  it("maps a 413 on check-in to the too-large copy without leaking the raw body", async () => {
    source.submitCheckin.mockRejectedValue(
      new ApiError({ code: "PAYLOAD_TOO_LARGE", message: "body too large", status: 413 }),
    );
    renderView();
    await screen.findByLabelText("Número de documento");
    fillCheckin();
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    expect(await screen.findByText("El contenido es demasiado grande.")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("body too large");
  });

  it("maps a 5xx on check-in to the generic safe copy without leaking a trace", async () => {
    source.submitCheckin.mockRejectedValue(
      new ApiError({ code: "INTERNAL_ERROR", message: "Traceback (most recent call last)", status: 500 }),
    );
    renderView();
    await screen.findByLabelText("Número de documento");
    fillCheckin();
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    expect(await screen.findByText("No hemos podido completar la operación.")).toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("Traceback");
  });

  it("maps a 5xx on an incident to the generic safe copy without confirming creation", async () => {
    source.reportIncident.mockRejectedValue(
      new ApiError({ code: "INTERNAL_ERROR", message: "boom stacktrace", status: 500 }),
    );
    renderView();
    await screen.findByLabelText("Título");
    fireEvent.change(screen.getByLabelText("Título"), { target: { value: "Fuga" } });
    fireEvent.change(screen.getByLabelText("Descripción"), { target: { value: "Agua" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar aviso" }));

    expect(await screen.findByText("No hemos podido completar la operación.")).toBeInTheDocument();
    expect(screen.queryByText(/Incidencia comunicada/)).not.toBeInTheDocument();
    expect(document.body.innerHTML).not.toContain("stacktrace");
  });
});

describe("accessibility (R4.3, task 5.4)", () => {
  it("wires labels and error descriptions and has no axe violations", async () => {
    renderView();
    const numberField = await screen.findByLabelText("Número de documento");
    // Accessible name via label association.
    expect(numberField).toHaveAttribute("id", "document_number");
    fireEvent.click(screen.getByRole("button", { name: "Enviar check-in" }));

    await waitFor(() => expect(numberField).toHaveAttribute("aria-invalid", "true"));
    expect(numberField.getAttribute("aria-describedby")).toBe("document_number-error");
    // The described-by target actually exists and carries the localized error.
    expect(document.getElementById("document_number-error")).toHaveTextContent("Este campo es obligatorio.");
    // page-has-heading-one is a best-practice rule; the portal uses section-level h2s by design (D5).
    expect(await getA11yViolations(document.body, ["page-has-heading-one"])).toEqual([]);
  });
});

describe("the conversation section (R5.1-R5.8, design D10)", () => {
  it("renders the thread labelled only as the guest or the accommodation", async () => {
    source.getConversation.mockResolvedValue(THREAD);
    renderView();

    expect(await screen.findByText("¿A qué hora puedo entrar?")).toBeInTheDocument();
    expect(screen.getByText("La entrada es a partir de las 15:00.")).toBeInTheDocument();
    expect(screen.getByText("Tú")).toBeInTheDocument();
    expect(screen.getByText("El alojamiento")).toBeInTheDocument();
  });

  /**
   * R5.5: the automatic reply and a manager's are the same `PROPERTY` on the wire, and the UI
   * must not reintroduce the difference. Asserted as an absence over the whole rendered page,
   * because the failure mode is a caption *appearing* — a later edit adding "asistente" or
   * "respuesta automática" would keep every positive assertion above green.
   */
  it("never labels a reply as written by the AI or by a person", async () => {
    source.getConversation.mockResolvedValue(THREAD);
    renderView();
    await screen.findByText("La entrada es a partir de las 15:00.");

    for (const word of [/\bIA\b/i, /autom[áa]tic/i, /asistente/i, /bot/i, /manager/i, /gestor/i]) {
      expect(document.body.textContent ?? "").not.toMatch(word);
    }
  });

  it("shows the localized waiting copy and never an escalation reason", async () => {
    source.getConversation.mockResolvedValue({ ...THREAD, state: "AWAITING_HUMAN" });
    renderView();

    expect(await screen.findByText("Te responderá una persona.")).toBeInTheDocument();
    for (const word of [/escalad/i, /motivo/i, /confianza/i, /intent/i]) {
      expect(document.body.textContent ?? "").not.toMatch(word);
    }
  });

  it("invites a first message when the thread is empty, rather than showing an error", async () => {
    renderView();

    expect(
      await screen.findByText("Todavía no has escrito nada. Escríbenos y te contestamos."),
    ).toBeInTheDocument();
  });

  it("sends the message and announces progress in a live region", async () => {
    let resolve: (value: unknown) => void = () => {};
    source.postMessage.mockReturnValue(new Promise((r) => { resolve = r; }));
    renderView();
    await screen.findByLabelText("Tu mensaje");

    fireEvent.change(screen.getByLabelText("Tu mensaje"), { target: { value: "Hola" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensaje" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Enviar mensaje" })).toBeDisabled());
    expect(conversationAlert()).toHaveTextContent("Enviando…");

    resolve({ id: "m1", sender: "GUEST", content: "Hola", createdAt: "2026-08-30T10:00:00Z" });
    await waitFor(() => expect(source.postMessage).toHaveBeenCalledWith(TOKEN, { content: "Hola" }));
  });

  it("re-reads the thread after a send, which is what shows the reply", async () => {
    source.getConversation.mockResolvedValueOnce(EMPTY_THREAD).mockResolvedValue(THREAD);
    renderView();
    await screen.findByLabelText("Tu mensaje");

    fireEvent.change(screen.getByLabelText("Tu mensaje"), { target: { value: "Hola" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensaje" }));

    expect(await screen.findByText("La entrada es a partir de las 15:00.")).toBeInTheDocument();
  });

  it("keeps what the guest typed when the send is rate limited", async () => {
    source.postMessage.mockRejectedValue(
      new ApiError({ code: "RATE_LIMITED", message: "Too many requests", status: 429, details: {} }),
    );
    renderView();
    await screen.findByLabelText("Tu mensaje");

    fireEvent.change(screen.getByLabelText("Tu mensaje"), { target: { value: "Hola" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensaje" }));

    await waitFor(() =>
      expect(conversationAlert()).toHaveTextContent(
        "Espera antes de volver a intentarlo. No sabemos si se recibió lo que enviaste.",
      ),
    );
    // R5.8: a cleared box would read as "it did not arrive", which we do not know.
    expect(screen.getByLabelText("Tu mensaje")).toHaveValue("Hola");
    expect(source.postMessage).toHaveBeenCalledTimes(1);
  });

  it("refuses an empty message before calling the API", async () => {
    renderView();
    await screen.findByLabelText("Tu mensaje");

    fireEvent.click(screen.getByRole("button", { name: "Enviar mensaje" }));

    expect(await screen.findByText("Este campo es obligatorio.")).toBeInTheDocument();
    expect(source.postMessage).not.toHaveBeenCalled();
  });

  it("shows a localized, retryable error when the thread cannot be loaded", async () => {
    source.getConversation.mockRejectedValue(
      new ApiError({ code: "INTERNAL", message: "boom", status: 500, details: {} }),
    );
    renderView();

    expect(
      await screen.findByText("No hemos podido cargar la conversación", undefined, {
        timeout: RETRY_SETTLE_MS,
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("No hemos podido completar la operación.")).toBeInTheDocument();
  }, RETRY_TEST_TIMEOUT_MS);

  /**
   * R5.1: the conversation is the fourth section and must fail alone. A thread that errors
   * leaves the stay, check-in and incident sections standing.
   */
  it("does not bring the other three sections down when it fails", async () => {
    source.getConversation.mockRejectedValue(
      new ApiError({ code: "INTERNAL", message: "boom", status: 500, details: {} }),
    );
    renderView();

    await screen.findByText("No hemos podido cargar la conversación", undefined, {
      timeout: RETRY_SETTLE_MS,
    });
    expect(screen.getByText("Casa Redes")).toBeInTheDocument();
    expect(screen.getByText("Check-in")).toBeInTheDocument();
    expect(screen.getByText("Comunicar una incidencia")).toBeInTheDocument();
  }, RETRY_TEST_TIMEOUT_MS);

  it("is not rendered at all while the link has not authorised", async () => {
    source.getStayInfo.mockRejectedValue(
      new ApiError({ code: "NOT_FOUND", message: "gone", status: 404, details: {} }),
    );
    renderView();

    await screen.findByText("Este enlace no es válido");
    expect(screen.queryByText("Conversación")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Tu mensaje")).not.toBeInTheDocument();
  });

  /** R5.9, task 10.7: the token is the credential, so it must never be rendered. */
  it("never renders the token in visible text, in an attribute, or in an error", async () => {
    source.getConversation.mockResolvedValue(THREAD);
    source.postMessage.mockRejectedValue(
      new ApiError({ code: "VALIDATION_ERROR", message: `bad ${TOKEN}`, status: 422, details: {} }),
    );
    const { container } = renderView();
    await screen.findByLabelText("Tu mensaje");

    fireEvent.change(screen.getByLabelText("Tu mensaje"), { target: { value: "Hola" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensaje" }));
    await waitFor(() => expect(conversationAlert()).toHaveTextContent("Revisa los campos indicados."));

    expect(document.body.textContent ?? "").not.toContain(TOKEN);
    expect(container.innerHTML).not.toContain(TOKEN);
    expect(document.title).not.toContain(TOKEN);
  });

  it("has no accessibility violations with a loaded thread", async () => {
    source.getConversation.mockResolvedValue(THREAD);
    const { container } = renderView();
    await screen.findByText("La entrada es a partir de las 15:00.");

    expect(await getA11yViolations(container)).toEqual([]);
  });
});

describe("a poll that fails after the thread loaded (R5.8)", () => {
  /**
   * The defect the QA panel of sections 9-10 reproduced: branching on `thread.isError` alone
   * blanked a conversation the guest was reading, because TanStack Query flips `status` to
   * `error` on *any* failed fetch — including a background poll — even while good data is
   * cached. The blast radius is real: the portal's six routes share one 60/min budget, so a
   * `429` mid-conversation is the expected case, not a freak one.
   */
  it("keeps the visible history and says the refresh failed, instead of wiping it", async () => {
    source.getConversation
      .mockResolvedValueOnce(THREAD)
      .mockRejectedValue(
        new ApiError({ code: "RATE_LIMITED", message: "slow down", status: 429, details: {} }),
      );
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      renderView();
      await screen.findByText("La entrada es a partir de las 15:00.");

      // Let the poll fire, which is the path that produces the failure with data already held.
      await vi.advanceTimersByTimeAsync(PORTAL_THREAD_POLL_MS + 100);
      await waitFor(() => expect(source.getConversation.mock.calls.length).toBeGreaterThan(1));
    } finally {
      vi.useRealTimers();
    }

    await waitFor(() =>
      expect(screen.getByText("No hemos podido actualizar la conversación. Esto es lo último que recibimos.")).toBeInTheDocument(),
    );
    // The history is still there…
    expect(screen.getByText("La entrada es a partir de las 15:00.")).toBeInTheDocument();
    expect(screen.getByText("¿A qué hora puedo entrar?")).toBeInTheDocument();
    // …and the send-oriented copy is NOT shown for what was only a read.
    expect(document.body.textContent ?? "").not.toContain("No sabemos si se recibió lo que enviaste.");
  });

  it("still shows the full error state when the very first load fails", async () => {
    source.getConversation.mockRejectedValue(
      new ApiError({ code: "RATE_LIMITED", message: "slow down", status: 429, details: {} }),
    );
    renderView();

    expect(
      await screen.findByText("No hemos podido cargar la conversación", undefined, {
        timeout: RETRY_SETTLE_MS,
      }),
    ).toBeInTheDocument();
    // The **description**, not just the title. The first version of this test asserted only the
    // title, and the i18n panel of sections 9-10 pointed out that a `429` here was still showing
    // the send-oriented copy — a regression this test would have watched happen in silence. A
    // first load is a plain `GET`: the guest has typed nothing, so nothing may have been sent.
    expect(
      screen.getByText("Demasiadas peticiones. Espera un momento y vuelve a intentarlo."),
    ).toBeInTheDocument();
    expect(document.body.textContent ?? "").not.toContain("No sabemos si se recibió lo que enviaste.");
  }, RETRY_TEST_TIMEOUT_MS);
});
