import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

describe("SourceStatusBanner", () => {
  beforeEach(() => {
    sessionStorage.clear();
    resetSourceStatusCache();
    vi.restoreAllMocks();
  });

  it("shows only unhealthy sites", async () => {
    vi.spyOn(sourceStatusService, "list").mockResolvedValue([healthy, rateLimited]);
    render(<SourceStatusBanner />);
    expect(await screen.findByText(/rate-limiting us/)).toBeTruthy();
    expect(screen.queryByText(/AO3/)).toBeNull();
  });

  it("hides a notice for the session once dismissed", async () => {
    vi.spyOn(sourceStatusService, "list").mockResolvedValue([rateLimited]);
    const { unmount } = render(<SourceStatusBanner />);
    fireEvent.click(await screen.findByRole("button", { name: "Dismiss FanFiction.net notice" }));
    expect(screen.queryByText(/rate-limiting us/)).toBeNull();
    unmount();

    render(<SourceStatusBanner />);
    await waitFor(() => expect(sourceStatusService.list).toHaveBeenCalled());
    expect(screen.queryByText(/rate-limiting us/)).toBeNull();
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
