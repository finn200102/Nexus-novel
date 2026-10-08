import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UpdatesInbox from "./UpdatesInbox";
import { activityService } from "../../services/activityService";
import type { InboxNovel } from "../../types/activity";

vi.mock("../../services/activityService", () => ({
  activityService: {
    getInbox: vi.fn(),
    markInboxRead: vi.fn(),
    markInboxCaughtUp: vi.fn(),
    markAllRead: vi.fn(),
  },
}));

const row = (overrides: Partial<InboxNovel> = {}): InboxNovel => ({
  novel_id: 12,
  title: "Serial",
  new_chapter_count: 3,
  first_new_chapter_number: 4,
  latest_at: "2026-10-08T10:00:00",
  event_ids: [1, 2],
  next_unread_chapter_id: 40,
  next_unread_chapter_number: 4,
  ...overrides,
});

function LocationProbe() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderInbox(onChanged?: () => void) {
  return render(
    <MemoryRouter initialEntries={["/activity"]}>
      <Routes>
        <Route path="/activity" element={<UpdatesInbox libraryId={3} onChanged={onChanged} />} />
        <Route path="*" element={<LocationProbe />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("UpdatesInbox", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(activityService.getInbox).mockResolvedValue([row()]);
    vi.mocked(activityService.markInboxRead).mockResolvedValue(2);
    vi.mocked(activityService.markInboxCaughtUp).mockResolvedValue({ updated: 2, progress_chapter_number: 6 });
    vi.mocked(activityService.markAllRead).mockResolvedValue(2);
  });

  it("shows per-story new chapter counts", async () => {
    renderInbox();

    expect(await screen.findByText("Serial")).toBeTruthy();
    expect(screen.getByText("— 3 new chapters")).toBeTruthy();
    expect(vi.mocked(activityService.getInbox)).toHaveBeenCalledWith(3);
  });

  it("shows the empty state when nothing is unread", async () => {
    vi.mocked(activityService.getInbox).mockResolvedValue([]);
    renderInbox();

    expect(await screen.findByText("You are all caught up.")).toBeTruthy();
    expect(screen.queryByText("Mark all read")).toBeNull();
  });

  it("opens the reader at the next unread chapter", async () => {
    renderInbox();
    fireEvent.click(await screen.findByRole("button", { name: /read next/i }));

    expect(screen.getByTestId("location").textContent).toBe("/library/3/novels/12/4");
  });

  it("marks one story read and reloads", async () => {
    renderInbox();
    fireEvent.click(await screen.findByRole("button", { name: "Mark read" }));

    await waitFor(() => expect(activityService.markInboxRead).toHaveBeenCalledWith(12));
    await waitFor(() => expect(activityService.getInbox).toHaveBeenCalledTimes(2));
  });

  it("catches a story up", async () => {
    renderInbox();
    fireEvent.click(await screen.findByRole("button", { name: "Caught up" }));

    await waitFor(() => expect(activityService.markInboxCaughtUp).toHaveBeenCalledWith(12));
  });

  it("marks every update in the library read", async () => {
    const onChanged = vi.fn();
    renderInbox(onChanged);
    fireEvent.click(await screen.findByRole("button", { name: /mark all read/i }));

    await waitFor(() => expect(activityService.markAllRead).toHaveBeenCalledWith(3));
    // The Activity page reloads its feed so read badges update too.
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
  });

  it("shows an error when loading fails", async () => {
    vi.mocked(activityService.getInbox).mockRejectedValue(new Error("offline"));
    renderInbox();

    expect(await screen.findByRole("alert")).toBeTruthy();
  });
});
