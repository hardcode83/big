import { describe, expect, it } from "vitest";

import { I18nProvider } from "@/lib/i18n/client-provider";
import { render, screen } from "@/test/render";

import type { CleanerSummary } from "../../data";
import { buildDirectory } from "../../lib/directory";
import { DetailAssignedCleanerBlock } from "./detail-assigned-cleaner-block";

const CLEANER_UUID = "c9f0f895-fb98-4b41-a54b-2e1a7c0d9e8f";

const CLEANERS: CleanerSummary[] = [
  { id: CLEANER_UUID, name: "Marta Ruiz", isActive: true },
  { id: "inactive-1", name: "Ana Pérez", isActive: false },
];

function settled<T extends { id: string }>(entries: readonly T[]) {
  return { index: buildDirectory(entries), isPending: false };
}
function absent<T extends { id: string }>(isPending: boolean) {
  return { index: buildDirectory<T>(undefined), isPending };
}

function renderBlock(
  overrides: Partial<React.ComponentProps<typeof DetailAssignedCleanerBlock>> = {},
) {
  const props = {
    assignedCleanerId: CLEANER_UUID as string | null,
    cleaners: settled(CLEANERS),
    ...overrides,
  };
  return render(
    <I18nProvider locale="es">
      <DetailAssignedCleanerBlock {...props} />
    </I18nProvider>,
  );
}

const LABEL_KEY = "detail.assigned.label";
const UNASSIGNED_KEY = "detail.assigned.unassigned";
const NOT_FOUND_KEY = "detail.assigned.notFound";

describe("DetailAssignedCleanerBlock (proposal R3.3/R3.4)", () => {
  it("names the assigned cleaner, never her id (R3.3)", () => {
    const { container } = renderBlock();
    expect(screen.getByText("Marta Ruiz")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain(CLEANER_UUID);
  });

  it("resolves an inactive cleaner's name just as well (design D5)", () => {
    renderBlock({ assignedCleanerId: "inactive-1" });
    expect(screen.getByText("Ana Pérez")).toBeInTheDocument();
  });

  it("says 'unassigned' for null cleaner, distinct from not-available (R3.3)", () => {
    renderBlock({ assignedCleanerId: null });
    expect(screen.getByText(UNASSIGNED_KEY)).toBeInTheDocument();
    expect(screen.queryByText(NOT_FOUND_KEY)).not.toBeInTheDocument();
  });

  it("degrades to not-available when the catalog has no match (R3.4)", () => {
    const { container } = renderBlock({
      assignedCleanerId: "gone-1",
      cleaners: settled([]),
    });
    expect(screen.getByText(NOT_FOUND_KEY)).toBeInTheDocument();
    expect(container.innerHTML).not.toContain("gone-1");
  });

  it("shows the loading marker while the catalog is in flight (R3.5)", () => {
    const { container } = renderBlock({
      assignedCleanerId: CLEANER_UUID,
      cleaners: absent<CleanerSummary>(true),
    });
    // The visible marker is an em-dash with an `sr-only` "loading" copy
    // from the cleaning namespace (the same pattern
    // `cleaning-task-row.tsx:140-148` uses).
    expect(screen.getByText("Cargando identidad…")).toBeInTheDocument();
    expect(container.innerHTML).not.toContain(CLEANER_UUID);
  });

  it("falls through to 'not-available' once the catalog query failed (R3.4)", () => {
    renderBlock({
      assignedCleanerId: CLEANER_UUID,
      cleaners: absent<CleanerSummary>(false),
    });
    expect(screen.getByText(NOT_FOUND_KEY)).toBeInTheDocument();
    expect(screen.queryByText("Cargando identidad…")).not.toBeInTheDocument();
  });

  it("renders the section heading label", () => {
    renderBlock();
    expect(screen.getByText(LABEL_KEY)).toBeInTheDocument();
  });
});