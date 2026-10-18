import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ReaderToolsSheet from "./ReaderToolsSheet";
import { readerToolsService, type CompanionAnswer } from "../../services/readerToolsService";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/readerToolsService", () => ({ readerToolsService: { providers: vi.fn(), variants: vi.fn(), question: vi.fn(), confirmRead: vi.fn(),glossaryEntries:vi.fn(async()=>({items:[],total:0,offset:0,limit:50})),glossary:vi.fn() } }));
vi.mock("../../services/chapterService", () => ({ chapterService: { getReadingProgress: vi.fn(async () => ({})) } }));
vi.mock("../../services/offlineTranslations", () => ({ offlineTranslations: { save: vi.fn(), list: vi.fn(async () => []) } }));
vi.mock("./PassageTranslation", () => ({ default: () => null }));
function mount(chapter = -2) { return render(<MemoryRouter><ReaderToolsSheet open onClose={vi.fn()} novelId={11} libraryId={1} chapter={chapter} identity={identity(11,chapter)} sourceVersion="v1" readingRunKey="run-current" onTranslation={vi.fn()} /></MemoryRouter>); }
async function choose() { await screen.findByRole("option", { name: "Local · local-model" }); fireEvent.change(screen.getByLabelText("Provider"), { target: { value: "1" } }); fireEvent.change(screen.getByLabelText("Story question"), { target: { value: "Who is this?" } }); }
describe("private companion signed boundaries", () => {
  it('approves a retained term only against the displayed original chapter',async()=>{
    vi.mocked(readerToolsService.glossaryEntries).mockResolvedValueOnce({items:[{id:7,source:'Mira',target:'Mirabelle',language:'de',through_chapter:9,
      chapter_key:null,manifest_epoch:null,manifest_revision:null,source_version:null,current_number:null,effective_through_chapter:null,
      prerequisite_count:0,binding_state:'review_required',reason:'legacy_identity_unknown'}],total:1,offset:0,limit:50});
    mount(-2);await screen.findByText(/Needs review · the original chapter/);
    fireEvent.click(screen.getByRole('button',{name:'Review term Mira'}));
    expect(readerToolsService.glossary).not.toHaveBeenCalled();
    expect(screen.getByLabelText('Original name or term')).toHaveValue('Mira');
    fireEvent.click(screen.getByRole('button',{name:'Approve term from this chapter'}));
    await waitFor(()=>expect(readerToolsService.glossary).toHaveBeenCalledWith(11,
      {source:'Mira',target:'Mirabelle',language:'de',through_chapter:-2,entry_id:7},identity(11,-2),'v1'));
  });
  beforeEach(() => { vi.clearAllMocks(); activateAccountStorage(null); vi.mocked(readerToolsService.providers).mockResolvedValue([{ id: 1, name: "Local", kind: "local", model: "local-model", base_url: "http://local", budget_usd: 0, used_usd: 0, reserved_usd: 0 }]); vi.mocked(readerToolsService.variants).mockResolvedValue([]); vi.mocked(readerToolsService.question).mockResolvedValue({ answer: "Insufficient verified evidence.", through_chapter: null, charged_usd: 0, citations: [] }); });
  it("sends a negative explicit cutoff and renders no-evidence without chapter zero", async () => {
    mount(); await choose(); expect(screen.getByLabelText("Use completed chapters through")).toHaveValue(-3);
    fireEvent.click(screen.getByRole("button", { name: "Ask with chapter evidence" }));
    await screen.findByText("Insufficient verified evidence."); expect(readerToolsService.question).toHaveBeenCalledWith(11, 1, "Who is this?", false, -3, false);
    expect(screen.getByText(/No completed chapter has verified evidence in this reading/)).toBeTruthy(); expect(screen.queryByText(/Through completed chapter 0/)).toBeNull();
  });
  it("preserves actual chapter zero after explicit finished-current-text confirmation", async () => {
    vi.mocked(readerToolsService.question).mockResolvedValue({ answer: "Chapter zero evidence.", through_chapter: 0, charged_usd: 0, citations: [{ chapter: 0, chapter_key:identity(11,0).chapter_key,block_id: "p1", quote: "A prologue" }] });
    mount(0); await choose(); fireEvent.click(screen.getByRole("button", { name: "I have finished this downloaded chapter" }));
    await waitFor(() => expect(screen.getByLabelText("Use completed chapters through")).toHaveValue(0));
    expect(readerToolsService.confirmRead).toHaveBeenCalledWith(11, 0, "v1", "run-current",identity(11,0));
    fireEvent.click(screen.getByRole("button", { name: "Ask with chapter evidence" })); await screen.findByText("Chapter zero evidence."); expect(readerToolsService.question).toHaveBeenCalledWith(11, 1, "Who is this?", false, 0, false);
    expect(screen.getByRole("link", { name: "Chapter 0" })).toHaveAttribute("href", `/library/1/novels/11/0?block=p1&chapter_key=${identity(11,0).chapter_key}`);
  });
  it("rejects fractional or future cutoff and supports an intentionally unspecified boundary", async () => {
    mount(0); await choose(); const boundary = screen.getByLabelText("Use completed chapters through");
    fireEvent.change(boundary, { target: { value: "0.5" } }); expect(screen.getByRole("button", { name: "Ask with chapter evidence" })).toBeDisabled();
    fireEvent.change(boundary, { target: { value: "1" } }); expect(screen.getByRole("button", { name: "Ask with chapter evidence" })).toBeDisabled();
    expect(readerToolsService.question).not.toHaveBeenCalled(); fireEvent.change(boundary, { target: { value: "" } }); fireEvent.click(screen.getByRole("button", { name: "Ask with chapter evidence" }));
    await waitFor(() => expect(readerToolsService.question).toHaveBeenCalledWith(11, 1, "Who is this?", false, undefined, false));
  });
  it("discards a late answer when the account changes", async () => {
    activateAccountStorage(901); let resolve!: (value: CompanionAnswer) => void; vi.mocked(readerToolsService.question).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    mount(); await choose(); fireEvent.click(screen.getByRole("button", { name: "Ask with chapter evidence" })); await waitFor(() => expect(readerToolsService.question).toHaveBeenCalledTimes(1));
    act(() => activateAccountStorage(902)); await act(async () => resolve({ answer: "Private prior-account answer", through_chapter: -3, charged_usd: 0, citations: [] }));
    expect(screen.queryByText("Private prior-account answer")).toBeNull(); expect(screen.getByLabelText("Story question")).toHaveValue(""); act(() => activateAccountStorage(null));
  });
});
