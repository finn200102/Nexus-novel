import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SourceStatusBanner from "./SourceStatusBanner";
import SourceStatusChip from "./SourceStatusChip";
import { sourceStatusService, SourceStatus, describeSourceStatus } from "../../services/sourceStatusService";
import { resetSourceStatusCache, useSourceStatus } from "../../hooks/useSourceStatus";

vi.mock("../../context/AuthContext", () => ({
  useAuth: () => ({ isAuthenticated: true }),
}));

const until = new Date(2026, 9, 8, 14, 20).toISOString();

const rateLimited: SourceStatus = {
  site: "fanfiction",
  label: "FanFiction.net",
  state: "rate_limited",
  until,
  message: "FanFiction.net is rate-limiting us.",
};
const healthy: SourceStatus = { site: "ao3", label: "AO3", state: "ok", until: null, message: "AO3 is working normally." };

describe("source status text", () => {
  it("names the resume time for a rate-limited site", () => {
    expect(describeSourceStatus(rateLimited)).toBe("FanFiction.net is rate-limiting us — updates resume around 14:20");
  });
});

const degraded: SourceStatus = {
  site: "royalroad",
  label: "Royal Road",
  state: "degraded",
  until: null,
  message: "Royal Road is responding slowly; updates may be delayed.",
};
const down: SourceStatus = {
  site: "archive",
  label: "Archive of Our Own",
  state: "down",
  until: null,
  message: "Archive of Our Own is unavailable right now.",
};

describe("SourceStatusBanner", () => {
  beforeEach(() => {
    localStorage.clear();
    resetSourceStatusCache();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when every site is ok", async () => {
    vi.spyOn(sourceStatusService, "list").mockResolvedValue([healthy]);
    const { container } = render(<SourceStatusBanner />);
    await act(async () => { await Promise.resolve(); });
    expect(container.textContent).toBe("");
  });

  it("does not show a banner for a degraded site", async () => {
    vi.spyOn(sourceStatusService, "list").mockResolvedValue([degraded]);
    const { container } = render(<SourceStatusBanner />);
    await act(async () => { await Promise.resolve(); });
    expect(container.querySelector(".source-status-banner")).toBeNull();
  });

  it("shows a single slim strip for a rate-limited site and ignores healthy ones", async () => {
    vi.spyOn(sourceStatusService, "list").mockResolvedValue([healthy, rateLimited]);
    const { container } = render(<SourceStatusBanner />);
    expect(await screen.findByText(/rate-limiting us/)).toBeTruthy();
    expect(screen.queryByText(/AO3/)).toBeNull();
    expect(container.querySelectorAll(".source-status-banner")).toHaveLength(1);
  });

  it("collapses several affected sites into one line with details", async () => {
    vi.spyOn(sourceStatusService, "list").mockResolvedValue([rateLimited, down]);
    render(<SourceStatusBanner />);
    expect(await screen.findByText("2 sources are having problems")).toBeTruthy();
    expect(screen.queryByText(/unavailable right now/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByText(/unavailable right now/)).toBeTruthy();
    expect(screen.getByText(/rate-limiting us/)).toBeTruthy();
  });

  it("removes the strip automatically once the site recovers", async () => {
    vi.useFakeTimers();
    const list = vi
      .spyOn(sourceStatusService, "list")
      .mockResolvedValueOnce([rateLimited])
      .mockResolvedValue([healthy]);
    render(<SourceStatusBanner />);
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(screen.getByText(/rate-limiting us/)).toBeTruthy();

    await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
    expect(list).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(/rate-limiting us/)).toBeNull();
  });

  it("stays hidden for a dismissed site and state, and returns when the state changes", async () => {
    const list = vi.spyOn(sourceStatusService, "list").mockResolvedValue([rateLimited]);
    const { unmount } = render(<SourceStatusBanner />);
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss FanFiction.net notice" }));
    expect(screen.queryByText(/rate-limiting us/)).toBeNull();
    expect(JSON.parse(localStorage.getItem("nexus:source-status-dismissed") || "[]")).toEqual(["fanfiction:rate_limited"]);
    unmount();

    render(<SourceStatusBanner />);
    await waitFor(() => expect(list).toHaveBeenCalled());
    expect(screen.queryByText(/rate-limiting us/)).toBeNull();
    cleanup();
    resetSourceStatusCache();

    list.mockResolvedValue([{ ...rateLimited, state: "down", message: "FanFiction.net is unavailable right now." }]);
    render(<SourceStatusBanner />);
    expect(await screen.findByText(/unavailable right now/)).toBeTruthy();
  });

  it("renders nothing when the service call fails", async () => {
    vi.spyOn(sourceStatusService, "list").mockRejectedValue(new Error("offline"));
    const { container } = render(<SourceStatusBanner />);
    await act(async () => { await Promise.resolve(); });
    expect(container.textContent).toBe("");
  });
});

describe("SourceStatusChip", () => {
  beforeEach(() => {
    resetSourceStatusCache();
    vi.restoreAllMocks();
  });

  it("shows the state for the novel's site", async () => {
    vi.spyOn(sourceStatusService, "list").mockResolvedValue([rateLimited]);
    render(<SourceStatusChip site="fanfiction" />);
    expect(await screen.findByText("Rate-limited until 14:20")).toBeTruthy();
  });

  it("renders nothing for a site the reader has no novels from", async () => {
    vi.spyOn(sourceStatusService, "list").mockResolvedValue([rateLimited]);
    const { container } = render(<SourceStatusChip site="royalroad" />);
    await act(async () => { await Promise.resolve(); });
    expect(container.textContent).toBe("");
  });
});

describe("useSourceStatus", () => {
  it("does not call the server while signed out", async () => {
    const list = vi.spyOn(sourceStatusService, "list").mockResolvedValue([]);
    const Probe = () => { useSourceStatus(false); return null; };
    render(<Probe />);
    await act(async () => { await Promise.resolve(); });
    expect(list).not.toHaveBeenCalled();
  });
});
