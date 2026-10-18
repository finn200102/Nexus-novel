import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StoryReadingHistory from "./StoryReadingHistory";
import { readingJournalService, type ReadingRunsPage, type ReadingJournalPage } from "../../services/readingJournalService";
import { chapterService } from "../../services/chapterService";
import { getQueuedProgress } from "../../services/progressSyncQueue";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/readingJournalService", async importOriginal => ({ ...await importOriginal<typeof import("../../services/readingJournalService")>(), readingJournalService: { runs: vi.fn(), journal: vi.fn(), change: vi.fn() } }));
vi.mock("../../services/chapterService", () => ({ chapterService: { acceptReadingRun: vi.fn() } }));
vi.mock("../../services/progressSyncQueue", () => ({ getQueuedProgress: vi.fn() }));
const key = "11111111-1111-4111-8111-111111111111", nextKey = "22222222-2222-4222-8222-222222222222";
const state = (): ReadingRunsPage => ({ novel_id: 11, current_run_key: key, revision: 4, first_chapter_number: 3, total: 1, offset: 0, limit: 20, current_progress: { novel_id: 11, chapter_number: 9, position: 100, percent: 65, revision: 4, reading_run_key: key, furthest_chapter_number: 10, furthest_percent: 90 }, items: [{ reading_run_key: key, ordinal: 1, status: "active", started_at: "2026-10-15T10:00:00Z", started_at_inferred: false, completed_at: null, completed_at_inferred: false, abandoned_at: null, abandon_reason: null, archived_at: null, progress: { novel_id: 11, chapter_number: 9, position: 100, percent: 65, revision: 4, reading_run_key: key }, next_unread_chapter_id: 3, next_unread_chapter_number: 3 }] });
const journal = (): ReadingJournalPage => ({ total: 1, offset: 0, limit: 20, items: [{ id: 1, novel_id: 11, novel_title: "Private story", reading_run_key: key, kind: "completed", occurred_at: null, inferred: true, reason: null, ordinal: 1 }] });
function Location() { return <p data-testid="location">{useLocation().pathname}</p>; }
const mount = () => render(<MemoryRouter initialEntries={["/library/1/novels/11?tab=history"]}><StoryReadingHistory novelId={11} libraryId={1} /><Location /></MemoryRouter>);
const pending = () => [{ novelId: 11, chapter: 8, position: 40, percent: 50, ts: Date.now() }];
describe("private reading history and explicit rereads", () => {
  beforeEach(() => { vi.clearAllMocks(); activateAccountStorage(7); vi.mocked(readingJournalService.runs).mockResolvedValue(state()); vi.mocked(readingJournalService.journal).mockResolvedValue(journal()); vi.mocked(getQueuedProgress).mockReturnValue([]); vi.mocked(chapterService.acceptReadingRun).mockReturnValue(undefined); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); });
  it("shows saved progress and honestly labels inferred legacy dates without changing history", async () => {
    mount(); expect(await screen.findByText("Chapter 9 · 65%")).toBeInTheDocument(); expect(screen.getByText("Date unknown · inferred from earlier records")).toBeInTheDocument(); expect(readerChangeCount()).toBe(0);
  });
  it("shows sparse and missing historical positions without inventing percentages", async () => {
    const value = state(); value.current_progress = { chapter_number: 9 }; value.items[0].progress = null;
    vi.mocked(readingJournalService.runs).mockResolvedValue(value); mount();
    expect(await screen.findByText("Chapter 9 · position not recorded")).toBeInTheDocument();
    expect(screen.getByText("Last position: Not recorded")).toBeInTheDocument();
    expect(screen.queryByText(/NaN%/)).not.toBeInTheDocument();
  });
  it("reviews the existing position before starting a new reading and opens the actual first chapter", async () => {
    const changed = state(); changed.current_run_key = nextKey; changed.revision = 5; changed.current_progress = { ...changed.current_progress!, chapter_number: 3, percent: 0, position: 0, revision: 5, reading_run_key: nextKey };
    vi.mocked(readingJournalService.change).mockResolvedValue(changed); mount(); fireEvent.click(await screen.findByRole("button", { name: "Start again" }));
    const dialog = screen.getByRole("dialog", { name: "Start this story again?" }); expect(dialog).toHaveTextContent("Existing position: Chapter 9 · 65%"); expect(dialog).toHaveTextContent("completion history and notes are preserved"); expect(readerChangeCount()).toBe(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Start new reading" })); await waitFor(() => expect(readingJournalService.change).toHaveBeenCalledWith(11, "start", { expected_revision: 4, reading_run_key: key, operation_id: expect.any(String) }));
    expect(chapterService.acceptReadingRun).toHaveBeenCalledWith(11, changed.current_progress); await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/library/1/novels/11/3"));
  });
  it("blocks start while unsynchronized writes exist and preserves them", async () => {
    const queued = pending(); vi.mocked(getQueuedProgress).mockReturnValue(queued); mount(); expect(await screen.findByRole("button", { name: "Start again" })).toBeDisabled(); expect(screen.getByRole("link", { name: "Open reader to review unsynchronized progress" })).toBeInTheDocument(); expect(readerChangeCount()).toBe(0); expect(getQueuedProgress()).toBe(queued);
  });
  it("rechecks queued writes appearing after the review opens", async () => {
    mount(); fireEvent.click(await screen.findByRole("button", { name: "Start again" })); const queued = pending(); vi.mocked(getQueuedProgress).mockReturnValue(queued); fireEvent.click(screen.getByRole("button", { name: "Start new reading" }));
    expect(await screen.findByText(/New unsynchronized progress was found/)).toBeInTheDocument(); expect(readerChangeCount()).toBe(0); expect(getQueuedProgress()).toBe(queued);
  });
  it("retries the same operation ID and revision after an uncertain response", async () => {
    vi.mocked(readingJournalService.change).mockRejectedValueOnce(new Error("lost response")).mockResolvedValueOnce(state()); mount(); fireEvent.click(await screen.findByRole("button", { name: "Finish this reading" })); fireEvent.click(screen.getByRole("button", { name: "Mark reading finished" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry same reading change" })); await waitFor(() => expect(readerChangeCount()).toBe(2)); expect(vi.mocked(readingJournalService.change).mock.calls[1]).toEqual(vi.mocked(readingJournalService.change).mock.calls[0]);
  });
  it("clears a rejected stale review and requires explicit fresh confirmation", async () => {
    vi.mocked(readingJournalService.change).mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: { message: "Another device changed this reading." } } } }); mount(); fireEvent.click(await screen.findByRole("button", { name: "Start again" })); fireEvent.click(screen.getByRole("button", { name: "Start new reading" }));
    expect(await screen.findByText("Another device changed this reading.")).toBeInTheDocument(); expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(readerChangeCount()).toBe(1); expect(chapterService.acceptReadingRun).not.toHaveBeenCalled();
  });
  it("records an optional bounded private stopping reason without changing the saved position", async () => {
    const changed = state(); changed.items[0].status = "abandoned"; changed.items[0].abandon_reason = "Not for me"; vi.mocked(readingJournalService.change).mockResolvedValue(changed); mount(); fireEvent.click(await screen.findByRole("button", { name: "Stop this reading" }));
    const reason = screen.getByLabelText("Reason for stopping (optional)"); expect(reason).toHaveAttribute("maxlength", "500"); fireEvent.change(reason, { target: { value: "  Not for me  " } }); fireEvent.click(screen.getByRole("button", { name: "Stop reading" }));
    await waitFor(() => expect(readingJournalService.change).toHaveBeenCalledWith(11, "drop", expect.objectContaining({ reason: "Not for me", expected_revision: 4, reading_run_key: key })));
    expect(screen.getByTestId("location")).toHaveTextContent("/library/1/novels/11"); expect(chapterService.acceptReadingRun).toHaveBeenCalledWith(11, changed.current_progress);
  });
  it("pages the journal and saved readings independently while keeping the current reading summary", async () => {
    vi.mocked(readingJournalService.runs).mockImplementation(async (_id, offset = 0) => ({ ...state(), total: 21, offset, items: offset ? [{ ...state().items[0], reading_run_key: nextKey, ordinal: 0, archived_at: "2026-10-15T10:00:00Z" }] : state().items }));
    vi.mocked(readingJournalService.journal).mockImplementation(async (_id, offset = 0) => ({ ...journal(), total: 21, offset, items: [{ ...journal().items[0], id: offset + 1, reason: offset ? "Older private reason" : null }] })); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Next readings" })); await waitFor(() => expect(readingJournalService.runs).toHaveBeenCalledWith(11, 20, 20)); expect(screen.getByRole("region", { name: "Current reading" })).toHaveTextContent("Reading 1 · In progress");
    fireEvent.click(screen.getByRole("button", { name: "Next journal entries" })); expect(await screen.findByText("Reason: Older private reason")).toBeInTheDocument(); expect(readingJournalService.journal).toHaveBeenCalledWith(11, 20, 20);
  });
  it("discards delayed private responses after switching accounts", async () => {
    let finish!: (value: ReadingRunsPage) => void; vi.mocked(readingJournalService.runs).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })); mount();
    vi.mocked(readingJournalService.journal).mockResolvedValue({ total: 0, offset: 0, limit: 20, items: [] }); vi.mocked(readingJournalService.runs).mockResolvedValue({ ...state(), current_run_key: null, current_progress: null, total: 0, items: [] }); act(() => activateAccountStorage(8)); await act(async () => finish(state())); expect(screen.queryByText("Chapter 9 · 65%")).not.toBeInTheDocument(); expect(readerChangeCount()).toBe(0);
  });
  it("does not accept or navigate a late successful restart after account switching", async () => {
    let finish!: (value: ReadingRunsPage) => void; vi.mocked(readingJournalService.change).mockReturnValue(new Promise(resolve => { finish = resolve; })); mount(); fireEvent.click(await screen.findByRole("button", { name: "Start again" })); fireEvent.click(screen.getByRole("button", { name: "Start new reading" })); act(() => activateAccountStorage(8)); await act(async () => finish(state())); expect(chapterService.acceptReadingRun).not.toHaveBeenCalled(); expect(screen.getByTestId("location")).toHaveTextContent("/library/1/novels/11");
  });
});
const readerChangeCount = () => vi.mocked(readingJournalService.change).mock.calls.length;
