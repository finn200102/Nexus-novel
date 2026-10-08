import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import OfflineBadge from "./OfflineBadge";
import { offlineReaderStore } from "../../services/offlineReaderStore";
import { markServerReachable, markServerUnreachable } from "../../services/serverReachability";

describe("OfflineBadge", () => {
  beforeEach(() => {
    markServerReachable();
    vi.spyOn(offlineReaderStore, "has").mockResolvedValue(true);
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    markServerReachable();
  });

  it("is hidden while online and the server answers", () => {
    render(<OfflineBadge novelId={1} chapterNumber={2} />);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("appears when a request fails with a network error while navigator.onLine is true", () => {
    render(<OfflineBadge novelId={1} chapterNumber={2} />);
    act(() => markServerUnreachable());
    expect(screen.getByText("Server unreachable")).toBeTruthy();
  });

  it("clears on the next successful request", () => {
    render(<OfflineBadge novelId={1} chapterNumber={2} />);
    act(() => markServerUnreachable());
    act(() => markServerReachable());
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("starts visible when the server was already unreachable on mount", () => {
    markServerUnreachable();
    render(<OfflineBadge novelId={1} chapterNumber={2} />);
    expect(screen.getByText("Server unreachable")).toBeTruthy();
  });
});
