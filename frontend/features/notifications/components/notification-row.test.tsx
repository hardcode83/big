import { describe, expect, it, vi } from "vitest";

import { render, screen, fireEvent } from "@/test/render";
import { I18nProvider } from "@/lib/i18n/client-provider";

import type { NotificationDto } from "../data";
import { NotificationRow } from "./notification-row";

const TASK_UUID = "5f1b7c2e-9a3d-4e11-8b52-7c9a1d2e3f40";

function row(overrides: Partial<NotificationDto> = {}): NotificationDto {
  return {
    id: "n1",
    type: "CLEANING_TASK_ASSIGNED",
    relatedType: "cleaning_task",
    relatedId: TASK_UUID,
    createdAt: "2026-08-29T14:05:00Z",
    readAt: null,
    ...overrides,
  };
}

function setup(
  notification: NotificationDto,
  profile: Parameters<typeof NotificationRow>[0]["profile"] = "workspace",
  onOpen = vi.fn(),
) {
  const view = render(
    <I18nProvider locale="es">
      <NotificationRow
        notification={notification}
        profile={profile}
        onOpen={onOpen}
      />
    </I18nProvider>,
  );
  return { ...view, onOpen };
}

describe("NotificationRow", () => {
  it("paints the translated type, not the operator's subject/body (R4.2)", () => {
    setup(row());

    expect(screen.getByText("Se te ha asignado una limpieza")).toBeInTheDocument();
    // The English operator copy the backend stores is not even on the DTO, so it cannot
    // appear — and neither can the UUIDs it embeds (R4.2, R6.3).
    expect(document.body.textContent).not.toContain("assigned to you");
    expect(document.body.textContent).not.toContain(TASK_UUID);
  });

  it("falls back to the translated generic for an unknown type, without breaking (R4.3)", () => {
    setup(row({ type: "SOMETHING_FROM_BEFORE_THE_ENUM" }));

    expect(screen.getByText("Aviso del sistema")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("SOMETHING_FROM_BEFORE_THE_ENUM");
  });

  it("shows the date localized, never the raw ISO string (R4.4)", () => {
    setup(row());

    const time = screen.getByText((_, element) => element?.tagName === "TIME");
    expect(time).toHaveAttribute("dateTime", "2026-08-29T14:05:00Z");
    expect(time.textContent).not.toContain("2026-08-29T");
    expect(time.textContent).toContain("2026");
  });

  it("distinguishes unread from read, and says so to a screen reader (R4.4)", () => {
    const { unmount } = setup(row());
    expect(screen.getByText("Sin leer")).toBeInTheDocument();
    unmount();

    setup(row({ readAt: "2026-08-29T15:00:00Z" }));
    expect(screen.queryByText("Sin leer")).not.toBeInTheDocument();
  });

  it("acknowledges an unread row when it is opened (R5.1)", () => {
    const { onOpen } = setup(row());

    fireEvent.click(screen.getByRole("button"));

    expect(onOpen).toHaveBeenCalledWith("n1");
  });

  it("does not re-acknowledge a row that is already read (R1.3)", () => {
    const { onOpen } = setup(row({ readAt: "2026-08-29T15:00:00Z" }));

    fireEvent.click(screen.getByRole("button"));

    expect(onOpen).not.toHaveBeenCalled();
  });

  it("links to the live page when there is one (R6.1)", () => {
    setup(row({ type: "INCIDENT_CREATED_HIGH", relatedType: "incident", relatedId: "i1" }));

    expect(screen.getByRole("link")).toHaveAttribute("href", "/incidents/i1");
  });

  it("renders a cleaning task without a link and without its UUID (R6.2, R6.3)", () => {
    setup(row());

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain(TASK_UUID);
  });

  it("renders without a link in the field shells, whose pages are placeholders (R6.2)", () => {
    setup(
      row({ type: "TECHNICIAN_ASSIGNED", relatedType: "incident", relatedId: "i1" }),
      "technician",
    );

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain("i1");
  });

  it("renders without a link when either half of the pair is null (R6.3)", () => {
    setup(row({ relatedType: null, relatedId: null }));

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("acknowledges from a linking row too — reading is reading (R5.1)", () => {
    const { onOpen } = setup(
      row({ type: "INCIDENT_CREATED_HIGH", relatedType: "incident", relatedId: "i1" }),
    );

    fireEvent.click(screen.getByRole("link"));

    expect(onOpen).toHaveBeenCalledWith("n1");
  });

  it("renders in English too, from the same type (R4.1)", () => {
    render(
      <I18nProvider locale="en">
        <NotificationRow notification={row()} profile="workspace" onOpen={vi.fn()} />
      </I18nProvider>,
    );

    expect(
      screen.getByText("A cleaning has been assigned to you"),
    ).toBeInTheDocument();
  });
});
