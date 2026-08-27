import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

import { ConversationsFilters } from "./conversations-filters";

describe("ConversationsFilters (D4)", () => {
  it("changing the status resets page to 1", () => {
    const onChange = vi.fn();
    const { getByLabelText } = render(
      <ConversationsFilters
        value={{ status: "OPEN", page: 3, perPage: 20 }}
        onChange={onChange}
      />,
    );
    fireEvent.change(getByLabelText("fields.status"), {
      target: { value: "RESOLVED" },
    });
    expect(onChange).toHaveBeenCalledWith({
      status: "RESOLVED",
      page: 1,
    });
  });

  it("changing the escalationStatus resets page to 1", () => {
    const onChange = vi.fn();
    const { getByLabelText } = render(
      <ConversationsFilters
        value={{ escalationStatus: "NONE", page: 2, perPage: 20 }}
        onChange={onChange}
      />,
    );
    fireEvent.change(getByLabelText("fields.escalationStatus"), {
      target: { value: "PENDING_HUMAN" },
    });
    expect(onChange).toHaveBeenCalledWith({
      escalationStatus: "PENDING_HUMAN",
      page: 1,
    });
  });

  it("emits the filter object with stable key order (status, escalationStatus, page, perPage)", () => {
    const onChange = vi.fn();
    const { getByLabelText } = render(
      <ConversationsFilters
        value={{ page: 5 }}
        onChange={onChange}
      />,
    );
    fireEvent.change(getByLabelText("fields.status"), {
      target: { value: "ESCALATED" },
    });
    const arg = onChange.mock.calls[0][0];
    expect(Object.keys(arg)).toEqual(["status", "page"]);
  });

  it("clearFilters resets to an empty filters object (the view starts at page 1 by default)", () => {
    const onChange = vi.fn();
    const { getByText } = render(
      <ConversationsFilters
        value={{ status: "OPEN", page: 3 }}
        onChange={onChange}
      />,
    );
    fireEvent.click(getByText("fields.clearFilters"));
    expect(onChange).toHaveBeenCalledWith({});
  });

  it("does NOT render a property picker (D4: property_id is out of v1)", () => {
    const onChange = vi.fn();
    render(<ConversationsFilters value={{}} onChange={onChange} />);
    expect(document.querySelector("#conversations-property")).toBeNull();
  });
});