import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import Stats from "./Stats";
import { readingStatsService, type StatsSummary } from "../services/readingStatsService";
import { activateAccountStorage } from "../services/accountStorage";
vi.mock("../services/readingStatsService", () => ({ readingStatsService: { getSummary: vi.fn() } }));
const summary = () => ({ range: "week", start: "2026-10-10", end: "2026-10-16", totals: { seconds: 0, words: 0, chapters_finished: 0, stories_finished: 2, reading_runs_finished: 4, rereads_finished: 2 }, daily: [], streak: { current: 0, longest: 0, min_seconds: 300 }, top_stories: [], by_site: [], by_tag: [], completion_history: { undated_runs: 1, undated_runs_included: false } } satisfies StatsSummary & { completion_history: { undated_runs: number; undated_runs_included: boolean }; totals: StatsSummary["totals"] & { reading_runs_finished: number; rereads_finished: number } });
const tile = (label: string) => screen.getByText(label, { selector: "dt" }).parentElement!;
describe("durable reading completion statistics", () => {
  beforeEach(() => { vi.clearAllMocks(); activateAccountStorage(7); vi.mocked(readingStatsService.getSummary).mockResolvedValue(summary()); });
  it("shows distinct stories, completed readings and rereads even without a time heartbeat", async () => {
    render(<Stats />); await screen.findByText("Completed readings", { selector: "dt" });
    expect(tile("Stories finished")).toHaveTextContent("2"); expect(tile("Completed readings")).toHaveTextContent("4"); expect(tile("Rereads finished")).toHaveTextContent("2"); expect(screen.queryByText("No reading time yet")).not.toBeInTheDocument(); expect(screen.getByText("No timed reading in this range.")).toBeInTheDocument(); expect(screen.getByText(/Each story is counted once in this range/)).toBeInTheDocument();
  });
  it("explains undated legacy completions are excluded from dated ranges and included only in all time", async () => {
    vi.mocked(readingStatsService.getSummary).mockImplementation(async range => ({ ...summary(), range, completion_history: { undated_runs: 1, undated_runs_included: range === "all" } })); render(<Stats />);
    expect(await screen.findByText(/1 earlier completed reading has no reliable completion date/)).toHaveTextContent("excluded from this date range");
    fireEvent.click(screen.getByRole("radio", { name: "All time" })); expect(await screen.findByText(/Undated completions are included in All time totals only/)).toBeInTheDocument();
  });
  it("labels the year filter as a rolling 365 days and retains the backend range contract", async () => {
    render(<Stats />); await screen.findByText("Completed readings", { selector: "dt" }); expect(screen.queryByRole("radio", { name: "Year" })).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("radio", { name: "Past 365 days" })); await waitFor(() => expect(readingStatsService.getSummary).toHaveBeenCalledWith("year")); expect(await screen.findByRole("heading", { name: "Reading time per day, last 365 days" })).toBeInTheDocument();
  });
  it("keeps the undated completion explanation visible when a dated range has no activity", async () => {
    const value = summary(); value.totals = { seconds: 0, words: 0, chapters_finished: 0, stories_finished: 0, reading_runs_finished: 0, rereads_finished: 0 }; value.completion_history.undated_runs = 3; vi.mocked(readingStatsService.getSummary).mockResolvedValue(value); render(<Stats />);
    expect(await screen.findByText("No reading time yet")).toBeInTheDocument(); expect(screen.getByText(/3 earlier completed readings have no reliable completion date/)).toHaveTextContent("Choose All time");
  });
  it("does not invent reread counts for a legacy server response", async () => {
    const value: StatsSummary = { ...summary(), totals: { seconds: 60, words: 250, chapters_finished: 0, stories_finished: 1 } }; vi.mocked(readingStatsService.getSummary).mockResolvedValue(value); render(<Stats />); await screen.findByText("Stories finished", { selector: "dt" }); expect(screen.queryByText("Completed readings", { selector: "dt" })).not.toBeInTheDocument(); expect(screen.queryByText("Rereads finished", { selector: "dt" })).not.toBeInTheDocument();
  });
  it("does not expose a previous account's delayed completion totals", async () => {
    let finish!: (value: StatsSummary) => void; vi.mocked(readingStatsService.getSummary).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValue({ ...summary(), totals: { ...summary().totals, reading_runs_finished: 1, rereads_finished: 0, stories_finished: 1 } }); render(<Stats />); act(() => activateAccountStorage(8)); const old = summary(); old.totals.reading_runs_finished = 9876; await act(async () => finish(old)); expect(screen.queryByText("9,876")).not.toBeInTheDocument(); expect(await screen.findByText("Completed readings", { selector: "dt" })).toBeInTheDocument(); expect(tile("Completed readings")).toHaveTextContent("1");
  });
});
