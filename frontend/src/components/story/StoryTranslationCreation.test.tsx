import {expectedChapterIdentity} from "../../services/chapterIdentity";
import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import StoryTranslationCreation from "./StoryTranslationCreation";
import { readerToolsService, type ReaderProvider, type StoryPermission, type TranslationBatchReview, type TranslationChaptersPage } from "../../services/readerToolsService";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/readerToolsService", () => ({ readerToolsService: { providers: vi.fn(), translationChapters: vi.fn(), permission: vi.fn(), setPermission: vi.fn(), setTranslationPermission: vi.fn(), reviewTranslationBatch: vi.fn(), queueTranslationBatch: vi.fn(), translate: vi.fn() } }));
const providers: ReaderProvider[] = [
  { id: 1, name: "Local translator", kind: "local_translation", model: "local-model", base_url: "http://local", budget_usd: 0, used_usd: 0, reserved_usd: 0, enabled: true, supported_languages: ["de", "en"], capabilities: ["translation"] },
  { id: 2, name: "Economy API", kind: "openrouter", model: "economy-model", base_url: "https://api.example", budget_usd: 5, used_usd: 1, reserved_usd: 0.5, input_price: 1, output_price: 2, enabled: true },
  { id: 3, name: "Disabled local", kind: "local_translation", model: "disabled", base_url: "http://disabled", budget_usd: 0, used_usd: 0, reserved_usd: 0, enabled: false },
];
const chapters = (offset = 0): TranslationChaptersPage => ({ novel_id: 11, total: 51, offset, limit: 50, items: [1, 2].map(id => ({ ...identity(11,id+offset),id: id + offset, chapter_number: id + offset, title: `Chapter ${id + offset}`, content_status: id === 2 ? "MISSING" : "PRESENT", downloaded: id !== 2, source_version: id === 2 ? null : "original-v1" })) });
const permission: StoryPermission = { translation: null, companion: null, ao3_consent: false, is_ao3: false, local: true };
const review = (changes: Partial<TranslationBatchReview> = {}): TranslationBatchReview => ({ review_token: "private-review", expires_at: "2030-01-01T00:00:00Z", provider: { id: 1, name: "Local translator", kind: "local_translation", model: "local-model", external: false }, language: "de", permission: { allowed: true, error: null, is_ao3: false }, budget: { configured: false, available_usd: 0, budget_usd: 0, used_usd: 0, reserved_usd: 0 }, estimated_max_usd: 0, queueable: 1, total: 1, items: [{ chapter_id: 1, chapter_number: 1, title: "Chapter 1", outcome: "ready_to_queue", job_id: null, source_version: "original-v1", blocks: 8, estimated_max_usd: 0, error: null }], ...changes });
const queued = vi.fn();
const mount = async () => { const view = render(<MemoryRouter><StoryTranslationCreation novelId={11} libraryId={1} onQueued={queued} /></MemoryRouter>); const details = view.container.querySelector("details")!; act(() => { details.open = true; fireEvent(details, new Event("toggle")); }); await screen.findByRole("checkbox", { name: "Translate chapter 1: Chapter 1" }); return view; };
const localSelection = async () => { fireEvent.change(screen.getByLabelText("Translation provider"), { target: { value: "1" } }); await waitFor(() => expect(readerToolsService.permission).toHaveBeenCalledWith(11, 1)); fireEvent.click(screen.getByRole("checkbox", { name: "Translate chapter 1: Chapter 1" })); await waitFor(() => expect(screen.getByRole("button", { name: "Review translation batch" })).toBeEnabled()); };
describe("reviewed bulk translation creation", () => {
  beforeEach(() => { vi.clearAllMocks(); activateAccountStorage(7); vi.mocked(readerToolsService.providers).mockResolvedValue(providers); vi.mocked(readerToolsService.translationChapters).mockResolvedValue(chapters()); vi.mocked(readerToolsService.permission).mockResolvedValue(permission); vi.mocked(readerToolsService.setTranslationPermission).mockResolvedValue({ ...permission, translation: true }); vi.mocked(readerToolsService.reviewTranslationBatch).mockResolvedValue(review()); vi.mocked(readerToolsService.queueTranslationBatch).mockResolvedValue({ total: 1, queued: 1, items: [{ ...review().items[0], outcome: "queued", job_id: 100 }] }); });
  it("loads metadata only when opened and never calls providers or queues on entry", async () => {
    render(<MemoryRouter><StoryTranslationCreation novelId={11} libraryId={1} onQueued={queued} /></MemoryRouter>);
    expect(readerToolsService.providers).not.toHaveBeenCalled(); expect(readerToolsService.translationChapters).not.toHaveBeenCalled(); expect(readerToolsService.reviewTranslationBatch).not.toHaveBeenCalled(); expect(readerToolsService.translate).not.toHaveBeenCalled(); expect(readerToolsService.queueTranslationBatch).not.toHaveBeenCalled();
  });
  it("reviews exact downloaded IDs locally and only queues the approved snapshot on explicit click", async () => {
    await mount(); expect(screen.getByRole("checkbox", { name: "Translate chapter 2: Chapter 2" })).toBeDisabled(); await localSelection();
    fireEvent.click(screen.getByRole("button", { name: "Review translation batch" })); await screen.findByRole("region", { name: "Translation batch review" });
    const input = { chapter_ids: [1],chapter_identities:[{chapter_id:1,...expectedChapterIdentity(identity(11,1),"original-v1")}], provider_id: 1, language: "de", external_consent: false, ao3_consent: false };
    expect(readerToolsService.reviewTranslationBatch).toHaveBeenCalledWith(11, input); expect(readerToolsService.queueTranslationBatch).not.toHaveBeenCalled(); expect(screen.getByText(/8 paragraphs/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Queue reviewed translations" })); await waitFor(() => expect(readerToolsService.queueTranslationBatch).toHaveBeenCalledWith(11, input, "private-review")); expect(queued).toHaveBeenCalledTimes(1); expect(await screen.findByRole("region", { name: "Translation batch outcomes" })).toHaveTextContent("1 new translations queued"); expect(readerToolsService.translate).not.toHaveBeenCalled();
  });
  it("invalidates review when language, chapter selection or provider changes", async () => {
    await mount(); await localSelection(); fireEvent.click(screen.getByRole("button", { name: "Review translation batch" })); await screen.findByRole("button", { name: "Queue reviewed translations" });
    fireEvent.change(screen.getByLabelText("Translation language code"), { target: { value: "en" } }); expect(screen.queryByRole("button", { name: "Queue reviewed translations" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Review translation batch" })); await screen.findByRole("button", { name: "Queue reviewed translations" }); fireEvent.click(screen.getByRole("checkbox", { name: "Translate chapter 1: Chapter 1" })); expect(screen.queryByRole("region", { name: "Translation batch review" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Translate chapter 1: Chapter 1" })); fireEvent.click(screen.getByRole("button", { name: "Review translation batch" })); await screen.findByRole("button", { name: "Queue reviewed translations" }); fireEvent.change(screen.getByLabelText("Translation provider"), { target: { value: "2" } }); expect(screen.queryByRole("region", { name: "Translation batch review" })).not.toBeInTheDocument(); expect(readerToolsService.queueTranslationBatch).not.toHaveBeenCalled();
  });
  it("requires separate external and AO3 consent and blocks paid queueing without a configured budget", async () => {
    vi.mocked(readerToolsService.permission).mockResolvedValue({ ...permission, local: false, is_ao3: true });
    vi.mocked(readerToolsService.reviewTranslationBatch).mockResolvedValue(review({ provider: { id: 2, name: "Economy API", kind: "openrouter", model: "economy-model", external: true }, permission: { allowed: true, error: null, is_ao3: true }, estimated_max_usd: 0.05 }));
    await mount(); fireEvent.change(screen.getByLabelText("Translation provider"), { target: { value: "2" } }); fireEvent.click(screen.getByRole("checkbox", { name: "Translate chapter 1: Chapter 1" })); const consent = await screen.findByRole("checkbox", { name: "Allow sending these selected chapters to this external provider" }); await waitFor(() => expect(consent).toBeEnabled()); fireEvent.click(consent); expect(screen.getByRole("button", { name: "Review translation batch" })).toBeDisabled(); fireEvent.click(screen.getByRole("checkbox", { name: "I explicitly allow external processing of this AO3 material" })); fireEvent.click(screen.getByRole("button", { name: "Review translation batch" }));
    expect(await screen.findByRole("button", { name: "Queue reviewed translations" })).toBeDisabled(); expect(readerToolsService.reviewTranslationBatch).toHaveBeenCalledWith(11, expect.objectContaining({ external_consent: true, ao3_consent: true }));
    fireEvent.click(consent); expect(screen.queryByRole("region", { name: "Translation batch review" })).not.toBeInTheDocument(); expect(readerToolsService.queueTranslationBatch).not.toHaveBeenCalled();
  });
  it("keeps disabled local providers disabled and never switches to a paid option", async () => {
    await mount(); expect(screen.getByRole("option", { name: "Disabled local · disabled · Disabled" })).toBeDisabled(); expect(screen.getByLabelText("Translation provider")).toHaveValue(""); await localSelection(); fireEvent.change(screen.getByLabelText("Translation language code"), { target: { value: "ja" } }); expect(screen.getByRole("button", { name: "Review translation batch" })).toBeDisabled(); expect(screen.getByLabelText("Translation provider")).toHaveValue("1"); expect(readerToolsService.reviewTranslationBatch).not.toHaveBeenCalled();
  });
  it("keeps explicit selected chapter IDs across source pages", async () => {
    vi.mocked(readerToolsService.translationChapters).mockImplementation(async (_id, offset = 0) => chapters(offset)); await mount(); await localSelection(); fireEvent.click(screen.getByRole("button", { name: "Next source chapters" })); fireEvent.click(await screen.findByRole("checkbox", { name: "Translate chapter 51: Chapter 51" })); fireEvent.click(screen.getByRole("button", { name: "Review translation batch" })); await waitFor(() => expect(readerToolsService.reviewTranslationBatch).toHaveBeenCalledWith(11, expect.objectContaining({ chapter_ids: [1, 51] })));
  });
  it("retains individual existing, retry and unavailable outcomes without silently retrying", async () => {
    vi.mocked(readerToolsService.reviewTranslationBatch).mockResolvedValue(review({ queueable: 0, items: [ { ...review().items[0], outcome: "already_ready" }, { ...review().items[0], chapter_id: 2, chapter_number: 2, outcome: "needs_retry" }, { ...review().items[0], chapter_id: 3, chapter_number: 3, outcome: "unavailable", error: "Download the source first." } ] })); await mount(); await localSelection(); fireEvent.click(screen.getByRole("button", { name: "Review translation batch" })); expect(await screen.findByRole("button", { name: "Queue reviewed translations" })).toBeDisabled(); expect(screen.getByText(/Existing completed variant kept/)).toBeInTheDocument(); expect(screen.getByText(/Existing variant needs explicit retry/)).toBeInTheDocument(); expect(screen.getByText("Download the source first.")).toBeInTheDocument(); expect(readerToolsService.queueTranslationBatch).not.toHaveBeenCalled();
  });
  it("requires a fresh review after a queue conflict and never repeats submission automatically", async () => {
    vi.mocked(readerToolsService.queueTranslationBatch).mockRejectedValue({ isAxiosError: true, response: { status: 409, data: { detail: "Source changed. Review this batch again." } } }); await mount(); await localSelection(); fireEvent.click(screen.getByRole("button", { name: "Review translation batch" })); fireEvent.click(await screen.findByRole("button", { name: "Queue reviewed translations" })); expect(await screen.findByText("Source changed. Review this batch again.")).toBeInTheDocument(); expect(screen.queryByRole("region", { name: "Translation batch review" })).not.toBeInTheDocument(); expect(readerToolsService.queueTranslationBatch).toHaveBeenCalledTimes(1);
  });
  it("discards delayed review results after the account changes", async () => {
    let finish!: (value: TranslationBatchReview) => void; vi.mocked(readerToolsService.reviewTranslationBatch).mockReturnValue(new Promise(resolve => { finish = resolve; })); await mount(); await localSelection(); fireEvent.click(screen.getByRole("button", { name: "Review translation batch" })); act(() => activateAccountStorage(8)); await act(async () => finish(review({ review_token: "previous-account-secret" }))); expect(screen.queryByRole("region", { name: "Translation batch review" })).not.toBeInTheDocument(); expect(document.body.textContent).not.toContain("previous-account-secret");
  });
  it("allows downloaded legacy plain text without a stored source version and lets review derive it", async () => {
    const value = chapters(); value.items[0].source_version = null; vi.mocked(readerToolsService.translationChapters).mockResolvedValue(value);
    await mount(); expect(screen.getByRole("checkbox", { name: "Translate chapter 1: Chapter 1" })).toBeEnabled(); await localSelection(); fireEvent.click(screen.getByRole("button", { name: "Review translation batch" }));
    await screen.findByRole("region", { name: "Translation batch review" }); expect(readerToolsService.reviewTranslationBatch).toHaveBeenCalledWith(11, expect.objectContaining({ chapter_ids: [1] })); expect(screen.getByText("original-v1")).toBeInTheDocument();
  });

  it("remembers only translation permission through the scoped endpoint without changing companion permission", async () => {
    vi.mocked(readerToolsService.permission).mockResolvedValue({ ...permission, local: false, translation: false, companion: null, is_ao3: true });
    vi.mocked(readerToolsService.setTranslationPermission).mockResolvedValue({ ...permission, local: false, translation: true, companion: null, is_ao3: true, ao3_consent: true });
    await mount(); fireEvent.change(screen.getByLabelText("Translation provider"), { target: { value: "2" } });
    const external = await screen.findByRole("checkbox", { name: "Allow sending these selected chapters to this external provider" }); await waitFor(() => expect(external).toBeEnabled()); fireEvent.click(external);
    expect(screen.getByRole("button", { name: "Remember translation permission for this story" })).toBeDisabled();
    fireEvent.click(screen.getByRole("checkbox", { name: "I explicitly allow external processing of this AO3 material" })); fireEvent.click(screen.getByRole("button", { name: "Remember translation permission for this story" }));
    await waitFor(() => expect(readerToolsService.setTranslationPermission).toHaveBeenCalledWith(11, 2, { translation: true, ao3_consent: true }));
    expect(await screen.findByText(/Translation permission is already remembered/)).toBeInTheDocument(); expect(readerToolsService.setPermission).not.toHaveBeenCalled(); expect(readerToolsService.queueTranslationBatch).not.toHaveBeenCalled();
  });

});
