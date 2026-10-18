import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StorySourceMigration from "./StorySourceMigration";
import { sourceMigrationService as service, readMigrationIntent, type MigrationPreview, type MigrationRecord, type MigrationStory } from "../../services/sourceMigrationService";
import { activateAccountStorage } from "../../services/accountStorage";
import { chapterService } from "../../services/chapterService";
import { getQueuedProgress } from "../../services/progressSyncQueue";
vi.mock("../../services/chapterService", () => ({ chapterService: { getReadingProgress: vi.fn() } }));
vi.mock("../../services/progressSyncQueue", () => ({ getQueuedProgress: vi.fn(() => []) }));
vi.mock("../../services/sourceMigrationService", async () => ({ ...await vi.importActual<typeof import("../../services/sourceMigrationService")>("../../services/sourceMigrationService"), sourceMigrationService: { targets: vi.fn(), chapters: vi.fn(), preview: vi.fn(), apply: vi.fn(), history: vi.fn(), get: vi.fn(), undo: vi.fn() } }));
const source: MigrationStory = { novel_id: 11, library_id: 1, title: "Original story", site: "royalroad", source_url: null, chapter_count: 2, current_progress: { chapter_number: 0, percent: 40 }, eligible: true, blocked_reason: null };
const target: MigrationStory = { ...source, novel_id: 22, title: "Alternate story", current_progress: null };
const counts = { mapped: 1, skipped: 0, unresolved: 1, annotations_copied: 1, annotations_retained: 2, receipts_copied: 1, history_copied: 2, preferences_copied: 1, followed_categories_copied: 1 };
const preview = (): MigrationPreview => ({ source, target, counts, warnings: [], can_apply: false, review_token: null, expires_at: null, total: 1, offset: 0, limit: 100, items: [{ source_chapter_id: 101, source_chapter_number: 0, source_title: "Opening", candidates: [{ target_chapter_id: 201, chapter_number: -2, title: "Opening", evidence: ["title"], content_equal: false }, { target_chapter_id: 202, chapter_number: 7, title: "Opening", evidence: ["title"], content_equal: false }], candidates_truncated: false, selected_target_chapter_id: null, decision: "ambiguous", required_for_progress: true, annotation_count: 3, annotations_copyable: 1, approximate_position: true, receipt_copyable: false }] });
const resolved = (): MigrationPreview => ({ ...preview(), can_apply: true, review_token: "review-bound-to-exact-plan", expires_at: "2099-10-16T12:00:00Z", counts: { ...counts, unresolved: 0 }, items: [{ ...preview().items[0], selected_target_chapter_id: 202, decision: "manual" }] });
const record = (): MigrationRecord => ({ id: 9, revision: 1, status: "applied", source, target, counts: resolved().counts, mappings: [{ source_chapter_id: 101, target_chapter_id: 202 }], created_at: "2026-10-16T12:00:00Z", undone_at: null, target_progress: { chapter_number: 7, revision: 2 }, can_undo: true, undo_blocked_reason: null });
const page = <T,>(items: T[]) => ({ total: items.length, offset: 0, limit: 20, items });
const mount = () => render(<MemoryRouter><StorySourceMigration novelId={11} libraryId={1} /></MemoryRouter>);
async function chooseAndPreview() { fireEvent.click(await screen.findByRole("button", { name: "Choose Alternate story" })); fireEvent.click(screen.getByRole("button", { name: "Build chapter preview" })); await screen.findByLabelText("Target for chapter 0"); }
async function confirmReady() { await chooseAndPreview(); fireEvent.click(screen.getByRole("button", { name: "Review transfer" })); fireEvent.click(screen.getByRole("button", { name: /^Confirm transfer$/ })); }
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(1); vi.mocked(getQueuedProgress).mockReturnValue([]);
  vi.mocked(service.targets).mockResolvedValue(page([target])); vi.mocked(service.history).mockResolvedValue(page([])); vi.mocked(service.chapters).mockResolvedValue({ ...page([{ id: 201, chapter_number: -2, title: "Opening" }, { id: 202, chapter_number: 7, title: "Opening" }]), limit: 100 });
  vi.mocked(service.preview).mockResolvedValue(resolved()); vi.mocked(service.apply).mockResolvedValue(record()); vi.mocked(service.get).mockResolvedValue(record()); vi.mocked(service.undo).mockResolvedValue({ ...record(), status: "undone", revision: 2 }); vi.mocked(chapterService.getReadingProgress).mockResolvedValue({ revision: 8, chapter_number: 7, position: 0, percent: 40, reading_run_key: null });
});
describe("reviewed source migration", () => {
  it("requires explicit ambiguity choices and a fresh server preview before confirmation", async () => {
    vi.mocked(service.preview).mockResolvedValueOnce(preview()).mockResolvedValueOnce(resolved()); mount();
    expect(service.preview).not.toHaveBeenCalled(); expect(service.apply).not.toHaveBeenCalled();
    await chooseAndPreview(); expect(screen.getByRole("button", { name: "Review transfer" })).toBeDisabled();
    expect(screen.getByText(/Ambiguous match/)).toBeInTheDocument();
    expect(within(screen.getByLabelText("Target for chapter 0")).getByRole("option", { name: /Skip/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Target for chapter 0"), { target: { value: "202" } });
    expect(screen.getByText(/Chapter choices changed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review changed chapter matches" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Review transfer" })).toBeEnabled());
    expect(service.preview).toHaveBeenLastCalledWith({ source_novel_id: 11, target_novel_id: 22, mappings: [{ source_chapter_id: 101, target_chapter_id: 202 }] }, 0, 100);
    fireEvent.click(screen.getByRole("button", { name: "Review transfer" }));
    const dialog = screen.getByRole("dialog", { name: "Confirm source transfer" }); expect(dialog).toHaveTextContent("Chapter 0 · 40%"); expect(dialog).toHaveTextContent("Annotations retained only in the original copy: 2"); expect(service.apply).not.toHaveBeenCalled();
    vi.mocked(service.history).mockResolvedValue(page([record()])); fireEvent.click(within(dialog).getByRole("button", { name: /^Confirm transfer$/ }));
    await screen.findByText(/Transfer confirmed/);
    expect(service.apply).toHaveBeenCalledWith(expect.objectContaining({ review_token: "review-bound-to-exact-plan", mappings: [{ source_chapter_id: 101, target_chapter_id: 202 }], operation_id: expect.any(String) }));
    expect(service.get).toHaveBeenCalledWith(9); expect(chapterService.getReadingProgress).toHaveBeenCalledWith(11); expect(chapterService.getReadingProgress).toHaveBeenCalledWith(22);
    expect(readMigrationIntent(11)).toBeNull();
  });
  it("checks both stories again when pending offline writes arrive after review", async () => {
    mount(); await chooseAndPreview(); fireEvent.click(screen.getByRole("button", { name: "Review transfer" }));
    vi.mocked(getQueuedProgress).mockReturnValue([{ novelId: 22, chapter: 7, position: 0, percent: 10, ts: 1 }]);
    fireEvent.click(screen.getByRole("button", { name: /^Confirm transfer$/ }));
    expect(await screen.findByText(/Unsynchronized progress exists/)).toBeInTheDocument(); expect(service.apply).not.toHaveBeenCalled(); expect(getQueuedProgress()).toHaveLength(1);
  });
  it("persists a lost acknowledgement across reload and retries the identical operation", async () => {
    vi.mocked(service.apply).mockRejectedValueOnce({ isAxiosError: true }).mockResolvedValueOnce(record());
    const first = mount(); await confirmReady(); await screen.findByRole("button", { name: "Retry same transfer" });
    const original = vi.mocked(service.apply).mock.calls[0][0]; first.unmount(); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Retry same transfer" })); await screen.findByText(/Transfer confirmed/);
    expect(vi.mocked(service.apply).mock.calls[1][0]).toEqual(original); expect(readMigrationIntent(11)).toBeNull();
  });
  it("holds an acknowledged operation until authoritative record, history and both progress refreshes succeed", async () => {
    vi.mocked(service.get).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce(record()); mount(); await confirmReady();
    const retry = await screen.findByRole("button", { name: "Refresh confirmed transfer" }); expect(readMigrationIntent(11)?.acknowledged_id).toBe(9);
    fireEvent.click(retry); await screen.findByText(/Transfer confirmed/); expect(service.apply).toHaveBeenCalledOnce(); expect(service.get).toHaveBeenCalledTimes(2);
  });
  it("invalidates a conflicting preview without blindly retrying", async () => {
    vi.mocked(service.apply).mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: { code: "source_changed", message: "The source reading changed. Review again." } } } }); mount(); await confirmReady();
    await screen.findByText("The source reading changed. Review again."); expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(readMigrationIntent(11)).toBeNull(); expect(service.apply).toHaveBeenCalledOnce(); expect(screen.queryByRole("button", { name: "Review transfer" })).not.toBeInTheDocument();
  });
  it("reviews the latest undo revision and preserves a pending undo operation", async () => {
    vi.mocked(service.history).mockResolvedValue(page([record()])); vi.mocked(service.get).mockResolvedValue({ ...record(), revision: 8 }); vi.mocked(service.undo).mockRejectedValueOnce({ isAxiosError: true }).mockResolvedValueOnce({ ...record(), status: "undone", revision: 9 }); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Review undo transfer 9" }));
    fireEvent.click(await screen.findByRole("button", { name: "Undo reviewed transfer" }));
    fireEvent.click(await screen.findByRole("button", { name: "Retry same undo" })); await screen.findByText(/Undo confirmed/);
    expect(vi.mocked(service.undo).mock.calls[0][1]).toMatchObject({ expected_revision: 8 }); expect(vi.mocked(service.undo).mock.calls[1]).toEqual(vi.mocked(service.undo).mock.calls[0]);
  });
  it("pages full-plan review without discarding explicit chapter choices", async () => {
    vi.mocked(service.preview).mockImplementation(async (_input, offset = 0) => ({ ...preview(), total: 201, offset, items: [{ ...preview().items[0], source_chapter_id: offset + 101, source_chapter_number: offset }] })); mount(); await chooseAndPreview();
    fireEvent.change(screen.getByLabelText("Target for chapter 0"), { target: { value: "202" } }); fireEvent.click(screen.getByRole("button", { name: "Next chapter matches" }));
    await screen.findByLabelText("Target for chapter 100"); expect(service.preview).toHaveBeenLastCalledWith(expect.objectContaining({ mappings: [{ source_chapter_id: 101, target_chapter_id: 202 }] }), 100, 100);
    fireEvent.change(screen.getByLabelText("Target for chapter 100"), { target: { value: "other" } });
    expect(await screen.findByRole("dialog", { name: "Choose a target chapter" })).toBeInTheDocument(); expect(service.chapters).toHaveBeenCalledWith(22, 0, 100);
  });
  it("fences a late preview and account-scoped saved operation after switching accounts", async () => {
    let resolve!: (value: MigrationPreview) => void; vi.mocked(service.preview).mockReturnValue(new Promise(done => { resolve = done; })); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Choose Alternate story" })); fireEvent.click(screen.getByRole("button", { name: "Build chapter preview" }));
    vi.mocked(service.targets).mockResolvedValue(page([])); await act(async () => { activateAccountStorage(2); resolve(resolved()); });
    expect(screen.queryByLabelText("Target for chapter 0")).not.toBeInTheDocument(); expect(readMigrationIntent(11)).toBeNull(); expect(service.apply).not.toHaveBeenCalled();
  });
  it("checks the original source queue when undo is opened from the target copy", async () => {
    vi.mocked(service.history).mockResolvedValue(page([record()]));
    render(<MemoryRouter><StorySourceMigration novelId={22} libraryId={1} /></MemoryRouter>);
    fireEvent.click(await screen.findByRole("button", { name: "Review undo transfer 9" }));
    await screen.findByRole("dialog", { name: "Confirm source transfer undo" });
    vi.mocked(getQueuedProgress).mockReturnValue([{ novelId: 11, chapter: 0, position: 0, percent: 40, ts: 1 }]);
    fireEvent.click(screen.getByRole("button", { name: "Undo reviewed transfer" }));
    expect(await screen.findByText(/Unsynchronized progress exists/)).toBeInTheDocument(); expect(service.undo).not.toHaveBeenCalled();
  });
  it("never fetches old-account progress when an authoritative receipt lookup returns after logout", async () => {
    let resolve!: (value: MigrationRecord) => void; vi.mocked(service.get).mockReturnValue(new Promise(done => { resolve = done; }));
    mount(); await confirmReady(); await waitFor(() => expect(service.get).toHaveBeenCalledWith(9));
    vi.mocked(service.targets).mockResolvedValue(page([])); await act(async () => { activateAccountStorage(2); resolve(record()); });
    expect(chapterService.getReadingProgress).not.toHaveBeenCalled(); expect(readMigrationIntent(11)).toBeNull();
    activateAccountStorage(1); expect(readMigrationIntent(11)?.acknowledged_id).toBe(9);
  });

});
