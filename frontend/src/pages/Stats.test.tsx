import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Stats from "./Stats";
import { readingStatsService, type StatsSummary } from "../services/readingStatsService";

vi.mock("../services/readingStatsService", () => ({
  readingStatsService: { getSummary: vi.fn() },
}));

const summary = (overrides: Partial<StatsSummary> = {}): StatsSummary => ({
  range: "week",
  start: "2026-10-03",
  end: "2026-10-09",
  totals: { seconds: 3720, words: 12000, chapters_finished: 4, stories_finished: 1 },
  daily: [
    { date: "2026-10-08", seconds: 1800, words: 5000, chapters_finished: 2 },
    { date: "2026-10-09", seconds: 1920, words: 7000, chapters_finished: 2 },
  ],
  streak: { current: 2, longest: 5, min_seconds: 300 },
  top_stories: [{ novel_id: 1, title: "Moon", seconds: 3720, words: 12000 }],
  by_site: [{ site: "ao3", seconds: 3720 }],
  by_tag: [{ tag: "slow burn", seconds: 3720 }],
  ...overrides,
});

describe("Stats page", () => {
  beforeEach(() => {
    vi.mocked(readingStatsService.getSummary).mockReset();
  });

  it("shows tiles, streak, and a chart with a table fallback", async () => {
    vi.mocked(readingStatsService.getSummary).mockResolvedValue(summary());
    render(<Stats />);

    expect(await screen.findByText("Time read")).toBeInTheDocument();
    expect(screen.getByText("2 days")).toBeInTheDocument();
    expect(screen.getByText(/Longest streak: 5 days/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Reading time per day, last 7 days/ })).toBeInTheDocument();
    expect(screen.getByRole("table", { name: /Reading time per day/ })).toBeInTheDocument();
    expect(screen.getByText("Moon")).toBeInTheDocument();
    expect(screen.getByText("ao3")).toBeInTheDocument();
  });

  it("shows an empty state when nothing has been read in the range", async () => {
    vi.mocked(readingStatsService.getSummary).mockResolvedValue(
      summary({ totals: { seconds: 0, words: 0, chapters_finished: 0, stories_finished: 0 }, daily: [] })
    );
    render(<Stats />);
    expect(await screen.findByText("No reading time yet")).toBeInTheDocument();
  });

  it("requests the newly selected range", async () => {
    vi.mocked(readingStatsService.getSummary).mockResolvedValue(summary());
    render(<Stats />);
    await screen.findByText("Time read");
    screen.getByRole("radio", { name: "All time" }).click();
    await waitFor(() => expect(readingStatsService.getSummary).toHaveBeenCalledWith("all"));
  });

  it("shows an error message when loading fails", async () => {
    vi.mocked(readingStatsService.getSummary).mockRejectedValue(new Error("boom"));
    render(<Stats />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn’t load your reading stats");
  });
});
