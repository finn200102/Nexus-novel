import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import CalendarReview from "./CalendarReview";
import ReadingGoal from "./ReadingGoal";
import { readingStatsService, type CalendarYearReview, type ReadingGoal as Goal } from "../../services/readingStatsService";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/readingStatsService", () => ({ readingStatsService: { getCalendarReview: vi.fn(), getGoal: vi.fn(), saveGoal: vi.fn() } }));
const year = new Date().getUTCFullYear();
const goal = (target: number | null = null, revision = 0): Goal => ({ revision, values: { target_readings: target } });
const review = (value = year): CalendarYearReview => ({ year: value, start: `${value}-01-01`, end: `${value}-12-31`, through: value < year ? `${value}-12-31` : new Date().toISOString().slice(0, 10), tracking_enabled: true, summary: { range: "calendar_year", start: `${value}-01-01`, end: `${value}-12-31`, totals: { seconds: 0, words: 0, chapters_finished: 0, stories_finished: 2, reading_runs_finished: 3, rereads_finished: 1 }, daily: [], streak: { current: 0, longest: 0, min_seconds: 300 }, top_stories: [], by_site: [], by_tag: [], completion_history: { undated_runs: 2, undated_runs_included: false } }, months: Array.from({ length: 12 }, (_, index) => ({ month: index + 1, seconds: 0, words: 0, chapters_finished: 0, stories_finished: index === 0 ? 2 : 0, reading_runs_finished: index === 0 ? 3 : 0, rereads_finished: index === 0 ? 1 : 0 })), goal: { target_readings: null, completed_readings: 3 } });
const open = async () => { const result = render(<CalendarReview />); const details = result.container.querySelector("details")!; act(() => { details.open = true; fireEvent(details, new Event("toggle")); }); await screen.findByRole("heading", { name: `${year} reading review` }); return result; };
const editGoal = async (target = "10") => { fireEvent.click(await screen.findByRole("button", { name: "Set an optional goal" })); fireEvent.change(screen.getByLabelText("Completed readings goal"), { target: { value: target } }); fireEvent.click(screen.getByRole("button", { name: "Review goal change" })); };
describe("private calendar review and optional goals", () => {
  beforeEach(() => { vi.clearAllMocks(); activateAccountStorage(7); vi.mocked(readingStatsService.getCalendarReview).mockImplementation(async value => review(value)); vi.mocked(readingStatsService.getGoal).mockResolvedValue(goal()); vi.mocked(readingStatsService.saveGoal).mockImplementation(async (_year, value) => { const changed = goal(value.values.target_readings, value.expected_revision + 1); vi.mocked(readingStatsService.getGoal).mockResolvedValue(changed); return changed; }); });
  afterEach(() => vi.restoreAllMocks());
  it("does not load or set up a goal until the calendar review is opened", () => {
    render(<CalendarReview />); expect(readerCalls()).toBe(0); expect(readingStatsService.getGoal).not.toHaveBeenCalled(); expect(readingStatsService.saveGoal).not.toHaveBeenCalled();
  });
  it("shows a true calendar year, twelve months, dated completions and honest undated exclusions", async () => {
    await open(); expect(screen.getByText(new RegExp(`Calendar year: January 1–December 31, ${year}`))).toHaveTextContent("private to your account");
    const monthly = screen.getByRole("region", { name: `Monthly reading activity for ${year}` }); expect(within(monthly).getAllByRole("listitem")).toHaveLength(12); expect(within(monthly).getByRole("heading", { name: "January" })).toBeInTheDocument(); expect(within(monthly).getByRole("heading", { name: "December" })).toBeInTheDocument(); expect(screen.getByRole("img", { name: `Completed readings by month, ${year}` })).toBeInTheDocument(); expect(screen.getByText(/2 earlier completed readings have no reliable completion date/)).toHaveTextContent("excluded from this year and its goal"); expect(await screen.findByText("No goal set. You can keep reading without one.")).toBeInTheDocument(); expect(readingStatsService.saveGoal).not.toHaveBeenCalled();
  });
  it("offers current and past years only and fences a delayed response from the previous selection", async () => {
    let finish!: (value: CalendarYearReview) => void; vi.mocked(readingStatsService.getCalendarReview).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockImplementation(async value => review(value)); const result = render(<CalendarReview />); const details = result.container.querySelector("details")!; act(() => { details.open = true; fireEvent(details, new Event("toggle")); }); const select = await screen.findByLabelText("Review calendar year"); expect(within(select).queryByRole("option", { name: String(year + 1) })).not.toBeInTheDocument(); expect(within(select).getByRole("option", { name: "1900" })).toBeInTheDocument(); fireEvent.change(select, { target: { value: String(year - 1) } }); await screen.findByRole("heading", { name: `${year - 1} reading review` }); await act(async () => finish(review(year))); expect(screen.queryByRole("heading", { name: `${year} reading review` })).not.toBeInTheDocument(); expect(readingStatsService.getGoal).toHaveBeenCalledWith(year - 1);
  });
  it("requires a concrete goal review before saving and counts completed readings including rereads", async () => {
    await open(); await editGoal("10"); const dialog = screen.getByRole("dialog", { name: "Save this reading goal?" }); expect(dialog).toHaveTextContent(`Calendar year: ${year}`); expect(dialog).toHaveTextContent("New goal: 10 completed readings, including rereads"); expect(readingStatsService.saveGoal).not.toHaveBeenCalled(); fireEvent.click(within(dialog).getByRole("button", { name: "Save reading goal" })); await waitFor(() => expect(readingStatsService.saveGoal).toHaveBeenCalledWith(year, { expected_revision: 0, operation_id: expect.any(String), values: { target_readings: 10 } })); expect(await screen.findByText(`3 of 10 readings completed in ${year}`)).toBeInTheDocument(); expect(screen.getByRole("progressbar", { name: `Reading goal progress for ${year}` })).toHaveAttribute("value", "3");
  });
  it("rejects fractional, zero and oversized goals before any save", async () => {
    render(<ReadingGoal year={year} completed={3} />); fireEvent.click(await screen.findByRole("button", { name: "Set an optional goal" })); for (const value of ["0", "1.5", "10001"]) { fireEvent.change(screen.getByLabelText("Completed readings goal"), { target: { value } }); expect(screen.getByRole("button", { name: "Review goal change" })).toBeDisabled(); } expect(readingStatsService.saveGoal).not.toHaveBeenCalled();
  });
  it("clears only the target through an explicit null-valued review", async () => {
    vi.mocked(readingStatsService.getGoal).mockResolvedValue(goal(10, 4)); await open(); fireEvent.click(await screen.findByRole("button", { name: "Clear reading goal" })); const dialog = screen.getByRole("dialog", { name: "Clear this reading goal?" }); expect(dialog).toHaveTextContent("Your recorded time and reading history are kept"); expect(readingStatsService.saveGoal).not.toHaveBeenCalled(); fireEvent.click(within(dialog).getByRole("button", { name: "Clear goal" })); await waitFor(() => expect(readingStatsService.saveGoal).toHaveBeenCalledWith(year, { expected_revision: 4, operation_id: expect.any(String), values: { target_readings: null } })); expect(await screen.findByText("No goal set. You can keep reading without one.")).toBeInTheDocument(); expect(screen.getByText(`Completed readings in ${year}`, { selector: "dt" }).parentElement).toHaveTextContent("3");
  });
  it("adopts a conflicting newer goal but requires a new explicit review before retrying the retained draft", async () => {
    vi.mocked(readingStatsService.getGoal).mockResolvedValueOnce(goal()).mockResolvedValue(goal(10, 8));
    vi.mocked(readingStatsService.saveGoal).mockRejectedValueOnce({ isAxiosError: true, response: { status: 409, data: { detail: { code: "preference_conflict", current: goal(5, 7), message: "Goal changed on another device. Review it again." } } } }).mockResolvedValueOnce(goal(10, 8)); render(<ReadingGoal year={year} completed={3} />); await editGoal(); fireEvent.click(screen.getByRole("button", { name: "Save reading goal" })); expect(await screen.findByText("Goal changed on another device. Review it again.")).toBeInTheDocument(); expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(screen.getByText("Current goal: 5 completed readings")).toBeInTheDocument(); fireEvent.click(screen.getByRole("button", { name: "Review goal change" })); expect(screen.getByRole("dialog")).toHaveTextContent("Current goal: 5 completed readings"); fireEvent.click(screen.getByRole("button", { name: "Save reading goal" })); await waitFor(() => expect(readingStatsService.saveGoal).toHaveBeenCalledTimes(2)); const calls = vi.mocked(readingStatsService.saveGoal).mock.calls; expect(calls[1][1].expected_revision).toBe(7); expect(calls[1][1].operation_id).not.toBe(calls[0][1].operation_id);
  });
  it("retains the same operation identity and target after a lost acknowledgement", async () => {
    vi.mocked(readingStatsService.getGoal).mockResolvedValueOnce(goal()).mockResolvedValue(goal(10, 1));
    vi.mocked(readingStatsService.saveGoal).mockRejectedValueOnce(new Error("Response lost")).mockResolvedValueOnce(goal(10, 1)); render(<ReadingGoal year={year} completed={3} />); await editGoal(); fireEvent.click(screen.getByRole("button", { name: "Save reading goal" })); fireEvent.click(await screen.findByRole("button", { name: "Retry same goal change" })); await screen.findByText("Your optional reading goal was saved."); const calls = vi.mocked(readingStatsService.saveGoal).mock.calls; expect(calls).toHaveLength(2); expect(calls[1]).toEqual(calls[0]);
  });
  it("fences an old account's late goal save and resets the next account's private editor", async () => {
    let finish!: (value: Goal) => void; vi.mocked(readingStatsService.saveGoal).mockReturnValue(new Promise(resolve => { finish = resolve; })); render(<ReadingGoal year={year} completed={3} />); await editGoal(); fireEvent.click(screen.getByRole("button", { name: "Save reading goal" })); act(() => activateAccountStorage(8)); await act(async () => finish(goal(9876, 1))); expect(screen.queryByText("Current goal: 9876 completed readings")).not.toBeInTheDocument(); expect(await screen.findByText("No goal set. You can keep reading without one.")).toBeInTheDocument(); expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
  it("reloads after an initial failed goal request instead of showing loading forever", async () => {
    vi.mocked(readingStatsService.getGoal).mockRejectedValueOnce(new Error("Temporary failure")).mockResolvedValueOnce(goal(20, 2)); render(<ReadingGoal year={year} completed={3} />);
    fireEvent.click(await screen.findByRole("button", { name: "Retry optional goal" })); expect(await screen.findByText("Current goal: 20 completed readings")).toBeInTheDocument(); expect(screen.queryByText("Loading optional goal…")).not.toBeInTheDocument(); expect(readingStatsService.saveGoal).not.toHaveBeenCalled();
  });
  it("confirms an old receipt without replacing a newer target saved by another device", async () => {
    vi.mocked(readingStatsService.getGoal).mockResolvedValueOnce(goal()).mockResolvedValueOnce(goal(20, 2));
    vi.mocked(readingStatsService.saveGoal).mockRejectedValueOnce(new Error("Response lost")).mockResolvedValueOnce(goal(12, 1)); render(<ReadingGoal year={year} completed={3} />); await editGoal("12"); fireEvent.click(screen.getByRole("button", { name: "Save reading goal" })); fireEvent.click(await screen.findByRole("button", { name: "Retry same goal change" }));
    expect(await screen.findByText("Current goal: 20 completed readings")).toBeInTheDocument(); expect(screen.getByText(/goal changed again later; the latest target is shown/)).toBeInTheDocument(); const calls = vi.mocked(readingStatsService.saveGoal).mock.calls; expect(calls).toHaveLength(2); expect(calls[1]).toEqual(calls[0]); expect(screen.queryByText("Current goal: 12 completed readings")).not.toBeInTheDocument();
  });
  it("keeps Edit and Clear disabled until the confirmed save's current goal is known", async () => {
    let finish!: (value: Goal) => void;
    vi.mocked(readingStatsService.getGoal).mockResolvedValueOnce(goal(10, 1)).mockReturnValueOnce(new Promise(resolve => { finish = resolve; }));
    vi.mocked(readingStatsService.saveGoal).mockResolvedValueOnce(goal(12, 2));
    render(<ReadingGoal year={year} completed={3} />);
    fireEvent.click(await screen.findByRole("button", { name: "Edit reading goal" }));
    fireEvent.change(screen.getByLabelText("Completed readings goal"), { target: { value: "12" } });
    fireEvent.click(screen.getByRole("button", { name: "Review goal change" }));
    fireEvent.click(screen.getByRole("button", { name: "Save reading goal" }));
    await waitFor(() => expect(readingStatsService.getGoal).toHaveBeenCalledTimes(2));
    const edit = screen.getByRole("button", { name: "Edit reading goal" }), clear = screen.getByRole("button", { name: "Clear reading goal" });
    expect(edit).toBeDisabled(); expect(clear).toBeDisabled();
    fireEvent.click(edit); fireEvent.click(clear);
    expect(screen.queryByLabelText("Completed readings goal")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(readingStatsService.saveGoal).toHaveBeenCalledTimes(1);
    await act(async () => finish(goal(20, 3)));
    expect(screen.getByText("Current goal: 20 completed readings")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit reading goal" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Clear reading goal" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Edit reading goal" }));
    expect(screen.getByLabelText("Completed readings goal")).toHaveValue(20);
  });
  it("does not display an unverified receipt when the authoritative reload fails", async () => {
    vi.mocked(readingStatsService.getGoal).mockResolvedValueOnce(goal()).mockRejectedValueOnce(new Error("Current goal unavailable")).mockResolvedValueOnce(goal(20, 2)); vi.mocked(readingStatsService.saveGoal).mockResolvedValue(goal(12, 1)); render(<ReadingGoal year={year} completed={3} />); await editGoal("12"); fireEvent.click(screen.getByRole("button", { name: "Save reading goal" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry optional goal" })); expect(await screen.findByText("Current goal: 20 completed readings")).toBeInTheDocument(); expect(readingStatsService.saveGoal).toHaveBeenCalledTimes(1); expect(screen.queryByText("Current goal: 12 completed readings")).not.toBeInTheDocument();
  });

});
const readerCalls = () => vi.mocked(readingStatsService.getCalendarReview).mock.calls.length;
