import { afterEach, describe, expect, it, vi } from "vitest";

import { fireEvent, render, screen, waitFor } from "@/test/render";
import { ProvenancePanel } from "@/features/shell/components/provenance-panel";
import { resolveProvenance } from "@/features/shell/components/provenance";

const LABELS = {
  trigger: "Detalles",
  title: "Procedencia del despliegue",
  closeLabel: "Cerrar detalles",
  commit: "Commit",
  pullRequest: "Pull Request",
  noPullRequest: "push directo, sin PR",
  builtAt: "Construido",
  runId: "Run de Actions",
  ref: "Rama",
  unknown: "desconocido",
  frontendVersion: "Frontend",
  backendVersion: "Backend",
  driftWarning: "Frontend y backend no corren la misma versión.",
  checking: "consultando…",
};

const PROVENANCE = resolveProvenance({
  commit: "a2f3c1d3f9b2000000000000000000000000000f",
  pr: "42",
  builtAt: "2026-07-30T09:14:02Z",
  runId: "1234567890",
  ref: "main",
  repoUrl: "https://github.com/autohostai-labs/AutoHostAI",
});

const FRONTEND_VERSION = "0.1.0+2026-07-30.a2f3c1d";

function renderPanel(
  overrides: Partial<Parameters<typeof ProvenancePanel>[0]> = {},
) {
  return render(
    <ProvenancePanel
      labels={LABELS}
      provenance={PROVENANCE}
      frontendVersion={FRONTEND_VERSION}
      {...overrides}
    />,
  );
}

function stubBackend(version: string | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      Response.json({ frontend: FRONTEND_VERSION, backend: version }),
    ),
  );
}

async function open() {
  fireEvent.click(screen.getByTestId("provenance-trigger"));
  await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ProvenancePanel (R4.1-R4.4, R5.3-R5.4)", () => {
  it("makes NO request until it is opened", async () => {
    // R5.4/design D9: the shell must render without a backend, so nothing may be
    // fetched while the panel is merely mounted in the footer.
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    renderPanel();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("links the PR, the commit and the Actions run when opened", async () => {
    stubBackend(FRONTEND_VERSION);
    renderPanel();
    await open();

    expect(screen.getByTestId("pr-link")).toHaveAttribute(
      "href",
      "https://github.com/autohostai-labs/AutoHostAI/pull/42",
    );
    expect(screen.getByTestId("commit-link")).toHaveAttribute(
      "href",
      "https://github.com/autohostai-labs/AutoHostAI/commit/a2f3c1d3f9b2000000000000000000000000000f",
    );
    expect(screen.getByTestId("run-link")).toHaveAttribute(
      "href",
      "https://github.com/autohostai-labs/AutoHostAI/actions/runs/1234567890",
    );
  });

  it("says 'direct push' instead of a broken link when there is no PR (R4.4)", async () => {
    stubBackend(FRONTEND_VERSION);
    renderPanel({
      provenance: resolveProvenance({
        commit: "a2f3c1d3f9b2000000000000000000000000000f",
        pr: undefined,
        builtAt: "2026-07-30T09:14:02Z",
        runId: "1234567890",
        ref: "main",
        repoUrl: "https://github.com/autohostai-labs/AutoHostAI",
      }),
    });
    await open();

    expect(screen.getByTestId("no-pr")).toHaveTextContent(
      "push directo, sin PR",
    );
    expect(screen.queryByTestId("pr-link")).not.toBeInTheDocument();
  });

  it("shows no drift warning when both versions match", async () => {
    stubBackend(FRONTEND_VERSION);
    renderPanel();
    await open();

    await waitFor(() =>
      expect(screen.getByTestId("backend-version")).toHaveTextContent(
        FRONTEND_VERSION,
      ),
    );
    expect(screen.queryByTestId("drift-warning")).not.toBeInTheDocument();
  });

  it("warns, with both versions on screen, when they differ (R5.3)", async () => {
    stubBackend("0.1.0+2026-07-29.0000000");
    renderPanel();
    await open();

    await waitFor(() =>
      expect(screen.getByTestId("drift-warning")).toBeInTheDocument(),
    );
    expect(screen.getByTestId("drift-warning")).toHaveAttribute(
      "role",
      "alert",
    );
    // Both have to be readable, otherwise the warning does not say what to do.
    expect(screen.getByTestId("backend-version")).toHaveTextContent(
      "0.1.0+2026-07-29.0000000",
    );
    expect(screen.getByText(FRONTEND_VERSION)).toBeInTheDocument();
  });

  it("shows the backend as unknown, and does NOT claim drift, when it is unreachable", async () => {
    // R5.4. An unreachable backend is not drift: claiming it would cry wolf every time
    // the backend is merely down, which is exactly when an operator needs to trust this.
    stubBackend(null);
    renderPanel();
    await open();

    await waitFor(() =>
      expect(screen.getByTestId("backend-version")).toHaveTextContent(
        "desconocido",
      ),
    );
    expect(screen.queryByTestId("drift-warning")).not.toBeInTheDocument();
  });

  it("survives a rejected request without breaking the panel", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("fetch failed");
      }),
    );
    renderPanel();
    await open();

    await waitFor(() =>
      expect(screen.getByTestId("backend-version")).toHaveTextContent(
        "desconocido",
      ),
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByTestId("drift-warning")).not.toBeInTheDocument();
  });

  it("does not claim drift when its own version is unknown", async () => {
    stubBackend("0.1.0+2026-07-29.0000000");
    renderPanel({ frontendVersion: null });
    await open();

    await waitFor(() =>
      expect(screen.getByTestId("backend-version")).toHaveTextContent(
        "0.1.0+2026-07-29.0000000",
      ),
    );
    expect(screen.queryByTestId("drift-warning")).not.toBeInTheDocument();
  });

  it("queries the backend once, not on every open", async () => {
    const fetchMock = vi.fn(async () =>
      Response.json({ frontend: FRONTEND_VERSION, backend: FRONTEND_VERSION }),
    );
    vi.stubGlobal("fetch", fetchMock);
    renderPanel();

    await open();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    fireEvent.keyDown(document.body, { key: "Escape" });
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    await open();

    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
