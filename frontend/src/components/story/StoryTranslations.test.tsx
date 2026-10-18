import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StoryTranslations from "./StoryTranslations";
import { readerToolsService, type StoryTranslation, type StoryTranslationsPage } from "../../services/readerToolsService";
import { activateAccountStorage } from "../../services/accountStorage";
vi.mock("../../services/readerToolsService", () => ({ readerToolsService: { storyTranslations: vi.fn(), exportStoryTranslations: vi.fn(), action: vi.fn(), translate: vi.fn() } }));
const variant = (id: number, changes: Partial<StoryTranslation> = {}): StoryTranslation => ({ ...identity(11,changes.chapter_number ?? id),id, chapter_id: changes.chapter_number ?? id, chapter_number: id, chapter_title: `Chapter ${id}`, language: "de", status: "completed", source_version: "original", current_source_version: "original", source_current: true, exportable: true, completed_blocks: 3, total_blocks: 3, provider: { kind: "local", model: "fixture" }, error: null, ...changes });
const listing = (items = [variant(1), variant(2)]): StoryTranslationsPage => ({ novel_id: 11, total: items.length, offset: 0, limit: 50, items });
const mount = () => render(<MemoryRouter><StoryTranslations novelId={11} libraryId={1} /></MemoryRouter>);
describe("story translations workspace", () => {
  beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(7); vi.mocked(readerToolsService.storyTranslations).mockResolvedValue(listing()); vi.mocked(readerToolsService.action).mockResolvedValue({}); });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
  it("reviews saved metadata without generating translations and blocks outdated variants", async () => {
    vi.mocked(readerToolsService.storyTranslations).mockResolvedValue(listing([variant(1), variant(2, { source_current: false, exportable: false, source_version: "old" })])); mount();
    expect(await screen.findByRole("checkbox", { name: "Export chapter 2, de, variant 2" })).toBeDisabled();
    expect(screen.getByText(/This saved variant differs/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Read chapter 1" })).toHaveAttribute("href", `/library/1/novels/11/1?chapter_key=${identity(11,1).chapter_key}`);
    expect(readerToolsService.translate).not.toHaveBeenCalled(); expect(readerToolsService.action).not.toHaveBeenCalled();
  });
  it("exports exact selected variants in chapter order without changing them on polling", async () => {
    vi.useFakeTimers(); vi.mocked(readerToolsService.exportStoryTranslations).mockResolvedValue(new Blob(["epub"]));
    vi.stubGlobal("URL", { ...URL, createObjectURL: vi.fn(() => "blob:private-epub"), revokeObjectURL: vi.fn() });
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined); mount(); await act(async () => { await Promise.resolve(); });
    fireEvent.click(screen.getByRole("checkbox", { name: "Export chapter 2, de, variant 2" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Export chapter 1, de, variant 1" }));
    vi.mocked(readerToolsService.storyTranslations).mockResolvedValue(listing([variant(99, { chapter_number: 1 }), variant(2)]));
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    fireEvent.click(screen.getByRole("button", { name: "Download translated EPUB" })); await act(async () => { await Promise.resolve(); });
    expect(readerToolsService.exportStoryTranslations).toHaveBeenCalledWith(11, [1, 2]); expect(click).toHaveBeenCalledTimes(1);
    expect(readerToolsService.translate).not.toHaveBeenCalled();
  });
  it("allows one language and explicitly replaces a chapter variant", async () => {
    vi.mocked(readerToolsService.storyTranslations).mockResolvedValue(listing([variant(1), variant(2, { chapter_number: 1 }), variant(3, { language: "fr" })])); mount();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Export chapter 1, de, variant 1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Export chapter 1, de, variant 2" }));
    expect(screen.getByRole("checkbox", { name: "Export chapter 1, de, variant 1" })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: "Export chapter 3, fr, variant 3" }));
    expect(screen.getByText(/Choose one translation language per EPUB/)).toBeInTheDocument();
    expect(screen.getByText("1 chapters selected · de")).toBeInTheDocument();
  });
  it("requires explicit retry confirmation with provider charges and cancels only the selected job", async () => {
    vi.mocked(readerToolsService.storyTranslations).mockResolvedValue(listing([variant(1, { status: "failed", exportable: false }), variant(2, { status: "processing", exportable: false, completed_blocks: 1 })])); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Retry translation 1" }));
    expect(screen.getByRole("dialog", { name: "Retry this translation?" })).toHaveTextContent("may incur API charges");
    expect(readerToolsService.action).not.toHaveBeenCalled(); fireEvent.click(screen.getByRole("button", { name: "Retry selected translation" }));
    await waitFor(() => expect(readerToolsService.action).toHaveBeenCalledWith(1, "retry"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel translation 2" }));
    await waitFor(() => expect(readerToolsService.action).toHaveBeenCalledWith(2, "cancel"));
  });
  it("reaches later pages without losing selected snapshots", async () => {
    vi.mocked(readerToolsService.storyTranslations).mockImplementation(async (_id, offset = 0) => ({ ...listing([variant(offset + 1)]), total: 101, offset })); mount();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Export chapter 1, de, variant 1" }));
    fireEvent.click(screen.getByRole("button", { name: "Next translations" }));
    await screen.findByRole("checkbox", { name: "Export chapter 51, de, variant 51" });
    expect(readerToolsService.storyTranslations).toHaveBeenCalledWith(11, 50, 50);
    expect(screen.getByRole("button", { name: "Remove selected variant 1" })).toBeInTheDocument();
  });
  it("discards delayed private listings after switching accounts", async () => {
    let finish!: (value: StoryTranslationsPage) => void;
    vi.mocked(readerToolsService.storyTranslations).mockReturnValueOnce(new Promise(resolve => { finish = resolve; })).mockResolvedValue(listing([])); mount();
    act(() => activateAccountStorage(8)); await act(async () => finish(listing([variant(99, { chapter_title: "Previous account secret" })])));
    expect(document.body.textContent).not.toContain("Previous account secret");
  });
  it("does not start a delayed private export after switching accounts", async () => {
    let finish!: (value: Blob) => void; vi.mocked(readerToolsService.exportStoryTranslations).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined); mount();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Export chapter 1, de, variant 1" })); fireEvent.click(screen.getByRole("button", { name: "Download translated EPUB" }));
    act(() => activateAccountStorage(8)); await act(async () => finish(new Blob(["private epub"]))); expect(click).not.toHaveBeenCalled();
  });
});
