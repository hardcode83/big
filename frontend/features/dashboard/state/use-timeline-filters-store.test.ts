import { beforeEach, describe, expect, it } from "vitest";

import { useTimelineFiltersStore } from "./use-timeline-filters-store";

/**
 * R3.5 is an invariant of the TRANSITION, not of a later effect: changing a filter
 * must land on page 1 in the same state change, or the render in between queries a
 * page of the new filter that the user never asked for (design D7). So the
 * assertions count state changes, not just the final value.
 */
function trackChanges(): () => number {
  let changes = 0;
  const unsubscribe = useTimelineFiltersStore.subscribe(() => {
    changes += 1;
  });
  return () => {
    unsubscribe();
    return changes;
  };
}

beforeEach(() => {
  useTimelineFiltersStore.getState().reset();
});

describe("useTimelineFiltersStore (R3.5, R4.1)", () => {
  it("starts on page 1 with no filter and no range draft", () => {
    const state = useTimelineFiltersStore.getState();
    expect(state.page).toBe(1);
    expect(state.actorType).toBeUndefined();
    expect(state.severity).toBeUndefined();
    expect(state.eventType).toBeUndefined();
    expect(state.fromDate).toBeUndefined();
    expect(state.toDate).toBeUndefined();
    expect(state.from).toBeUndefined();
    expect(state.to).toBeUndefined();
  });

  it.each([
    ["setActorType", () => useTimelineFiltersStore.getState().setActorType("GUEST")],
    ["setSeverity", () => useTimelineFiltersStore.getState().setSeverity("ERROR")],
    [
      "setEventType",
      () => useTimelineFiltersStore.getState().setEventType("INCIDENT_CREATED"),
    ],
    [
      "setRange",
      () => useTimelineFiltersStore.getState().setRange("2026-08-01", "2026-08-31"),
    ],
  ])("%s returns to page 1 in a single state change", (_name, applyFilter) => {
    useTimelineFiltersStore.getState().setPage(3);
    expect(useTimelineFiltersStore.getState().page).toBe(3);

    const changes = trackChanges();
    applyFilter();

    expect(changes()).toBe(1);
    expect(useTimelineFiltersStore.getState().page).toBe(1);
  });

  it("moves the page only through setPage", () => {
    useTimelineFiltersStore.getState().setEventType("INCIDENT_CREATED");
    useTimelineFiltersStore.getState().setPage(4);

    const state = useTimelineFiltersStore.getState();
    expect(state.page).toBe(4);
    // Paging does not disturb the active filter.
    expect(state.eventType).toBe("INCIDENT_CREATED");
  });

  it("keeps the range draft as the date input produced it", () => {
    useTimelineFiltersStore.getState().setRange("2026-08-05", undefined);

    const state = useTimelineFiltersStore.getState();
    expect(state.fromDate).toBe("2026-08-05");
    expect(state.toDate).toBeUndefined();
  });

  it("reset clears every filter, the range draft and the page", () => {
    const store = useTimelineFiltersStore.getState();
    store.setActorType("GUEST");
    store.setSeverity("ERROR");
    store.setEventType("INCIDENT_CREATED");
    store.setRange("2026-08-01", "2026-08-31");
    store.setPage(7);

    useTimelineFiltersStore.getState().reset();

    expect(useTimelineFiltersStore.getState()).toMatchObject({
      actorType: undefined,
      severity: undefined,
      eventType: undefined,
      fromDate: undefined,
      toDate: undefined,
      from: undefined,
      to: undefined,
      page: 1,
    });
  });

  /*
    The draft and the committed pair diverge only while the draft is inverse
    (design D8). This is the store half of R4.3: the committed pair is what feeds
    the query key, so leaving it untouched is what keeps the request from firing.
  */
  it("commits a valid range as instants carrying a timezone", () => {
    useTimelineFiltersStore.getState().setRange("2026-08-01", "2026-08-31");

    const state = useTimelineFiltersStore.getState();
    expect(state.from).toMatch(/Z$/);
    expect(state.to).toMatch(/Z$/);
    expect(new Date(state.to!).getTime()).toBeGreaterThan(
      new Date(state.from!).getTime(),
    );
  });

  it("keeps the committed pair when the draft turns inverse", () => {
    useTimelineFiltersStore.getState().setRange("2026-08-01", "2026-08-31");
    const committed = useTimelineFiltersStore.getState();

    useTimelineFiltersStore.getState().setRange("2026-08-31", "2026-08-01");

    const state = useTimelineFiltersStore.getState();
    // The inputs show what was typed...
    expect(state.fromDate).toBe("2026-08-31");
    expect(state.toDate).toBe("2026-08-01");
    // ...while the query still sees the last valid pair, unchanged.
    expect(state.from).toBe(committed.from);
    expect(state.to).toBe(committed.to);
  });

  it("does not move the page when the draft turns inverse", () => {
    // Regression: `setRange` used to reset the page unconditionally, so making
    // the range inverse while reading page 2 changed the query key and jumped the
    // reader back to page 1 behind the error message — the "collateral valid"
    // query D8 forbids. Caught by the browser check, not by a unit test, because
    // the earlier tests were already on page 1.
    useTimelineFiltersStore.getState().setRange("2026-08-01", "2026-08-31");
    useTimelineFiltersStore.getState().setPage(2);
    const committed = useTimelineFiltersStore.getState();

    useTimelineFiltersStore.getState().setRange("2031-06-01", "2026-08-31");

    const state = useTimelineFiltersStore.getState();
    expect(state.page).toBe(2);
    expect(state.from).toBe(committed.from);
    expect(state.to).toBe(committed.to);
    // The draft still shows what was typed, so the error can be rendered.
    expect(state.fromDate).toBe("2031-06-01");
  });

  it("reopens the range when an end is cleared", () => {
    useTimelineFiltersStore.getState().setRange("2026-08-01", "2026-08-31");
    useTimelineFiltersStore.getState().setRange("2026-08-01", undefined);

    const state = useTimelineFiltersStore.getState();
    expect(state.to).toBeUndefined();
    expect(state.from).toMatch(/Z$/);
  });
});
