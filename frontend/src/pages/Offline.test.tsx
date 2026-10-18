import {fixtureChapterIdentity as identity} from "../../tests/fixtures/chapterIdentity";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Offline from "./Offline";
import { offlineLibraryStore, type OfflineChapterInventory, type OfflineLibraryInventory, type OfflineCleanupPreview } from "../services/offlineLibraryStore";
import { activateAccountStorage } from "../services/accountStorage";
vi.mock("../services/offlineLibraryStore", () => ({ offlineLibraryStore: { inventory: vi.fn(), setBudget: vi.fn(), previewCleanup: vi.fn(), cleanup: vi.fn() } }));
const chapter = (novel_id = 1, chapter_number = 1): OfflineChapterInventory => ({chapter_key:identity(novel_id,chapter_number).chapter_key,address_current:true, novel_id, chapter_number, title: `Chapter ${chapter_number}`, total_bytes: 150,
  text: { ready: true, bytes: 100, pinned: true, source_version: "v1" }, images: { ready: 1, total: 2, missing: 1, embedded_bytes: 30 },
  audio: { ready: false, bytes: 0, partial_bytes: 20, completed_parts: 1, job_status: "failed", busy: false, source_state: "current", source_version: "v1" },
  translations: [{ id: 3, language: "de", status: "completed", bytes: 30, ready: true, source_version: "old", source_state: "stale" }] });
const inventory = (): OfflineLibraryInventory => ({ total_bytes: 390, limit_bytes: null, stories: [
  { novel_id: 1, novel_title: "Illustrated story", library_id: 7, total_bytes: 150, chapters: [chapter()] },
  { novel_id: 2, novel_title: "Audio only story", library_id: null, total_bytes: 200, chapters: [{ ...chapter(2, 3), total_bytes: 200, text: { ready: false, bytes: 0, pinned: false, source_version: null }, images: { ready: 0, total: 0, missing: 0, embedded_bytes: 0 }, audio: { ready: true, bytes: 200, partial_bytes: 0, completed_parts: 0, job_status: "ready", busy: false, source_state: "unknown", source_version: "v1" }, translations: [] }] },
  { novel_id: 3, novel_title: null, library_id: null, total_bytes: 40, chapters: [{ ...chapter(3, 9), total_bytes: 40, text: { ready: false, bytes: 0, pinned: false, source_version: null }, images: { ready: 0, total: 0, missing: 0, embedded_bytes: 0 }, audio: { ready: false, bytes: 0, partial_bytes: 0, completed_parts: 0, job_status: null, busy: false, source_state: "unknown", source_version: null }, translations: [{ id: 4, language: "ja", status: "completed", bytes: 40, ready: true, source_version: "v0", source_state: "unknown" }] }] },
] });
const preview = (): OfflineCleanupPreview => ({ selection: { novel_id: 1, kinds: ["text"] }, review_token: "reviewed-files", records: 1, bytes: 100, busy_chapters: [] });
const persisted = vi.fn(async () => false), persist = vi.fn(async () => false), estimate = vi.fn(async () => ({ usage: 5000, quota: 1000000 }));
const mount = () => render(<MemoryRouter><Offline /></MemoryRouter>);
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>(done => { resolve = done; }); return { promise, resolve }; }
beforeEach(() => {
  vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(1);
  vi.stubGlobal("navigator", { storage: { persisted, persist, estimate }, onLine: true }); persisted.mockResolvedValue(false); persist.mockResolvedValue(false); estimate.mockResolvedValue({ usage: 5000, quota: 1000000 });
  vi.mocked(offlineLibraryStore.inventory).mockResolvedValue(inventory()); vi.mocked(offlineLibraryStore.setBudget).mockResolvedValue(undefined); vi.mocked(offlineLibraryStore.previewCleanup).mockResolvedValue(preview()); vi.mocked(offlineLibraryStore.cleanup).mockResolvedValue({ removed_records: 1, removed_bytes: 100 });
});
afterEach(() => vi.unstubAllGlobals());
async function manage() { fireEvent.click(await screen.findByRole("button", { name: "Manage offline files for Illustrated story" })); return screen.getByRole("dialog", { name: "Manage offline files for Illustrated story" }); }
async function showChapters(title: string) { fireEvent.click(await screen.findByText(`Chapter readiness for ${title}`)); await waitFor(() => expect(screen.getByRole("region", { name: `Offline files for ${title}` }).querySelector("ol")).not.toBeNull()); }
describe("unified private offline library", () => {
  it("includes audio-only and translation-only stories with honest partial and stale readiness", async () => {
    mount(); expect(await screen.findByText("3 stories · 3 chapters · 390 B total")).toBeInTheDocument();
    const usage = screen.getByRole("region", { name: "Your offline storage usage" }); expect(usage).toHaveTextContent("100 B including embedded images"); expect(usage).toHaveTextContent("30 B within text; already included above"); expect(usage).toHaveTextContent("220 B including unfinished parts"); expect(usage).toHaveTextContent("70 B");
    await showChapters("Illustrated story"); const illustrated = screen.getByRole("region", { name: "Offline files for Illustrated story" });
    expect(illustrated).toHaveTextContent("1 of 2 saved · incomplete · 1 missing"); expect(illustrated).toHaveTextContent("Incomplete · 1 parts saved · failed"); expect(illustrated).toHaveTextContent("de · Saved · source changed");
    expect(within(illustrated).getByRole("link", { name: "Chapter 1" })).toHaveAttribute("href", `/library/7/novels/1/1?chapter_key=${identity(1,1).chapter_key}`);
    await showChapters("Audio only story"); expect(screen.getByRole("region", { name: "Offline files for Audio only story" })).toHaveTextContent("Saved · source version unverified");
    await showChapters("Story 3"); expect(screen.getByRole("region", { name: "Offline files for Story 3" })).toHaveTextContent("ja · Saved · source version unverified");
    expect(offlineLibraryStore.cleanup).not.toHaveBeenCalled(); expect(offlineLibraryStore.setBudget).not.toHaveBeenCalled();
  });
  it("separates browser-origin quota from private files and reports an actual persistence denial", async () => {
    mount(); expect(await screen.findByText("Browser-origin usage: 5.0 KB · quota: 1.0 MB")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Request persistent storage" }));
    expect(await screen.findByText(/The browser did not grant persistent storage/)).toBeInTheDocument(); expect(screen.queryByText("Persistent storage granted by this browser.")).not.toBeInTheDocument();
    expect(persist).toHaveBeenCalledOnce();
  });
  it("does not let an older status check overwrite a newly granted persistence request", async () => {
    const old = deferred<boolean>(); persisted.mockReturnValueOnce(old.promise); persist.mockResolvedValue(true); mount();
    fireEvent.click(screen.getByRole("button", { name: "Request persistent storage" })); await waitFor(() => expect(screen.getAllByText("Persistent storage granted by this browser.").length).toBeGreaterThan(0));
    await act(async () => old.resolve(false)); expect(screen.queryByText(/Persistent storage has not been granted/)).not.toBeInTheDocument();
  });
  it("keeps unsupported browser quota and persistence unknown rather than implying zero usage or a grant", async () => {
    vi.stubGlobal("navigator", { storage: {}, onLine: true }); mount();
    expect(await screen.findByText("This browser does not report persistent storage support.")).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Request persistent storage" })).toBeDisabled(); expect(screen.getByText("Browser-origin usage: Unavailable · quota: Unavailable")).toBeInTheDocument();
  });
  it("sets and clears an optional byte budget without deleting existing files", async () => {
    const data = inventory(); vi.mocked(offlineLibraryStore.inventory).mockImplementation(async () => structuredClone(data)); vi.mocked(offlineLibraryStore.setBudget).mockImplementation(async limit => { data.limit_bytes = limit; }); mount(); await screen.findByText(/390 B total/);
    fireEvent.change(screen.getByLabelText("Offline storage budget (MB)"), { target: { value: "0.1" } }); fireEvent.click(screen.getByRole("button", { name: "Save offline budget" }));
    await waitFor(() => expect(offlineLibraryStore.setBudget).toHaveBeenCalledWith(100000)); expect(await screen.findByText(/Offline storage budget saved/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove offline budget" })); await waitFor(() => expect(offlineLibraryStore.setBudget).toHaveBeenLastCalledWith(null)); expect(offlineLibraryStore.cleanup).not.toHaveBeenCalled();
  });
  it("requires an exact per-type cleanup review before deleting and leaves progress/server data outside this action", async () => {
    mount(); const dialog = await manage(); fireEvent.click(within(dialog).getByRole("checkbox", { name: "Text and embedded images" })); fireEvent.click(within(dialog).getByRole("button", { name: "Review cleanup" }));
    const reviewed = await screen.findByRole("dialog", { name: "Review offline cleanup" }); expect(offlineLibraryStore.previewCleanup).toHaveBeenCalledWith({ novel_id: 1, kinds: ["text"] }); expect(reviewed).toHaveTextContent("1 local records · 100 B"); expect(reviewed).toHaveTextContent("pending progress writes are kept"); expect(offlineLibraryStore.cleanup).not.toHaveBeenCalled();
    fireEvent.click(within(reviewed).getByRole("button", { name: "Remove reviewed offline files" })); await waitFor(() => expect(offlineLibraryStore.cleanup).toHaveBeenCalledWith(preview())); expect(await screen.findByText(/Removed 1 local records/)).toBeInTheDocument();
  });
  it("protects live browser audio and invalidates a review whenever the selected file types change", async () => {
    vi.mocked(offlineLibraryStore.previewCleanup).mockResolvedValue({ ...preview(), records: 3, busy_chapters: [{ novel_id: 1, chapter_number: 1 }] });
    mount(); const dialog = await manage(); fireEvent.click(within(dialog).getByRole("checkbox", { name: "Audio and unfinished audio parts" })); fireEvent.click(within(dialog).getByRole("button", { name: "Review cleanup" }));
    expect(await screen.findByText(/Live browser audio work is protected/)).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Remove reviewed offline files" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Text and embedded images" })); expect(screen.queryByRole("button", { name: "Remove reviewed offline files" })).not.toBeInTheDocument(); expect(offlineLibraryStore.cleanup).not.toHaveBeenCalled();
  });
  it("requires a fresh review when files changed after preview, without force-removing replacements", async () => {
    vi.mocked(offlineLibraryStore.cleanup).mockRejectedValue(Object.assign(new Error("changed"), { name: "OfflineCleanupChangedError" }));
    mount(); const dialog = await manage(); fireEvent.click(within(dialog).getByRole("checkbox", { name: "Text and embedded images" })); fireEvent.click(within(dialog).getByRole("button", { name: "Review cleanup" })); fireEvent.click(await screen.findByRole("button", { name: "Remove reviewed offline files" }));
    expect(await screen.findByText(/Offline files changed or could not be removed/)).toBeInTheDocument(); expect(screen.getByRole("button", { name: "Review cleanup" })).toBeEnabled(); expect(offlineLibraryStore.cleanup).toHaveBeenCalledOnce();
  });
  it("retries storage access failures without claiming the library is empty", async () => {
    vi.mocked(offlineLibraryStore.inventory).mockRejectedValueOnce(new Error("storage unavailable")); mount();
    expect(await screen.findByText(/This browser could not open your offline library/)).toBeInTheDocument(); expect(screen.queryByText("Nothing saved on this device yet")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Refresh offline library" })); expect(await screen.findByText(/390 B total/)).toBeInTheDocument();
  });
  it("hides late private inventory after switching accounts", async () => {
    const old = deferred<OfflineLibraryInventory>(); vi.mocked(offlineLibraryStore.inventory).mockReturnValueOnce(old.promise); mount(); vi.mocked(offlineLibraryStore.inventory).mockResolvedValue({ stories: [], total_bytes: 0, limit_bytes: null });
    act(() => activateAccountStorage(2)); await act(async () => old.resolve(inventory())); expect(await screen.findByText("Nothing saved on this device yet")).toBeInTheDocument(); expect(screen.queryByText("Illustrated story")).not.toBeInTheDocument();
  });
  it("does not apply an older account's cleanup completion or refresh into the next account", async () => {
    const old = deferred<{ removed_records: number; removed_bytes: number }>(); vi.mocked(offlineLibraryStore.cleanup).mockReturnValueOnce(old.promise); mount(); const dialog = await manage(); fireEvent.click(within(dialog).getByRole("checkbox", { name: "Text and embedded images" })); fireEvent.click(within(dialog).getByRole("button", { name: "Review cleanup" })); fireEvent.click(await screen.findByRole("button", { name: "Remove reviewed offline files" }));
    await waitFor(() => expect(offlineLibraryStore.cleanup).toHaveBeenCalledOnce()); vi.mocked(offlineLibraryStore.inventory).mockResolvedValue({ stories: [], total_bytes: 0, limit_bytes: null }); act(() => activateAccountStorage(2)); await act(async () => old.resolve({ removed_records: 1, removed_bytes: 100 }));
    expect(await screen.findByText("Nothing saved on this device yet")).toBeInTheDocument(); expect(screen.queryByText(/Removed 1 local records/)).not.toBeInTheDocument(); expect(offlineLibraryStore.inventory).toHaveBeenCalledTimes(2);
  });
});
