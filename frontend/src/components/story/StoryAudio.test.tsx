import {fixtureChapterIdentity as identity} from "../../../tests/fixtures/chapterIdentity";
import {expectedChapterIdentity} from "../../services/chapterIdentity";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import StoryAudio from "./StoryAudio";
import { audioService, type ServerAudioJob, type StoryAudioOverview } from "../../services/audioService";
import apiClient from "../../services/apiClient";
import { voiceService } from "../../services/voiceService";
import { browserAudioQueue } from "../../services/browserAudioQueue";
import { chapterAudioStore } from "../../services/offlineReaderStore";
import { ttsService } from "../../services/ttsService";
import { accountStorage, activateAccountStorage, storageGeneration } from "../../services/accountStorage";
vi.mock("../../services/pronunciationService",async original=>({...await original<typeof import("../../services/pronunciationService")>(),pronunciationService:{get:vi.fn(async()=>({scope:"pronunciation",revision:0,rules:[],account_rules:[],inherit_account:true,effective_rules:[],effective_version:null})),save:vi.fn()}}));
vi.mock("../../services/audioService", () => ({ audioService: { story: vi.fn(), createStory: vi.fn(), retry: vi.fn(), cancel: vi.fn(), audio: vi.fn() } }));
vi.mock("../../services/voiceService", () => ({ voiceService: { list: vi.fn(), getDefault: vi.fn(), setDefault: vi.fn() } }));
vi.mock("../../services/browserAudioQueue", () => ({ browserAudioQueue: { subscribe: vi.fn(() => () => undefined), getSnapshot: vi.fn(), enqueue: vi.fn(), retry: vi.fn(), cancel: vi.fn(), remove: vi.fn(), hydrate: vi.fn() } }));
vi.mock("../../services/offlineReaderStore", () => ({ chapterAudioStore: { get: vi.fn(), recording: vi.fn() } }));
vi.mock("../../services/ttsService", async importOriginal => ({ ...await importOriginal<typeof import("../../services/ttsService")>(), ttsService: { synthesize: vi.fn() } }));
const job = (status: ServerAudioJob["status"]): ServerAudioJob => ({ id: 8, status, provider_id: "qwen3_clone", provider_voice: "My voice", provider_model: "local", audio_ready: status === "completed", completed_parts: 1, total_parts: 3, source_version: "old" });
const overview = (): StoryAudioOverview => ({ novel_id: 11, total: 2, offset: 0, limit: 50, summary: { chapters: 2, downloaded: 1, ready: 0, queued: 0, needs_retry: 0 }, chapters: [
  { ...identity(11,1),id: 101, chapter_number: 1, title: "Opening", content_status: "PRESENT", downloaded: true, source_version: "current", latest_job: null },
  { ...identity(11,2),id: 102, chapter_number: 2, title: "Harbour", content_status: "MISSING", downloaded: false, source_version: null, latest_job: null },
] });
const mount = () => render(<MemoryRouter><StoryAudio novelId={11} libraryId={1} /></MemoryRouter>);
describe("story audio creation", () => {
  beforeEach(() => {
    vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(null);activateAccountStorage(7);
    accountStorage.setItem("nexus-reader-narrator-id", "3");
    vi.mocked(browserAudioQueue.getSnapshot).mockReturnValue({ generation: storageGeneration(), running: false, rows: [] });
    vi.mocked(browserAudioQueue.hydrate).mockResolvedValue(undefined);
    vi.mocked(browserAudioQueue.remove).mockResolvedValue(undefined);
    vi.mocked(audioService.story).mockResolvedValue(overview());
    vi.mocked(voiceService.getDefault).mockResolvedValue({ voice_profile_id: 3, revision: 1 });
    vi.mocked(voiceService.list).mockResolvedValue([{ id: 3, name: "My voice", language: "English", status: "completed", transcript: "", error: null, preview_ready: true }]);
    vi.mocked(audioService.createStory).mockResolvedValue({ novel_id: 11, outcomes: [{ chapter_number: 1, outcome: "queued", job: job("queued") }, { chapter_number: 2, outcome: "unavailable", job: null }] });
    vi.mocked(audioService.retry).mockResolvedValue(job("queued"));
    vi.mocked(audioService.cancel).mockResolvedValue(job("cancelled"));
  });
  afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

  it("previews a chapter range and reports individual queue outcomes without requesting a paid provider", async () => {
    mount();
    expect(await screen.findByRole("checkbox", { name: "Chapter 2: Harbour" })).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Narrator" })).toHaveValue("3");
    fireEvent.change(screen.getByLabelText("Through chapter"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Add chapter range" }));
    expect(await screen.findByText("2 chapters selected: 1, 2")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Include author notes in new audio" }));
    fireEvent.click(screen.getByRole("button", { name: "Create selected audio" }));
    await waitFor(() => expect(audioService.createStory).toHaveBeenCalledWith(11, { chapter_numbers: [1, 2],chapter_identities:[{chapter_number:1,...expectedChapterIdentity(identity(11,1),"current")},{chapter_number:2,...expectedChapterIdentity(identity(11,2))}], voice_profile_id: 3, include_author_notes: true }));
    expect(await screen.findByText("Chapter 1: Queued")).toBeInTheDocument();
    expect(screen.getByText("Chapter 2: Download the chapter first")).toBeInTheDocument();
    expect(screen.getByText("No chapters selected.")).toBeInTheDocument();
    expect(accountStorage.getItem("nexus-reader-tts-engine")).toBe("openai_compatible");
    expect(accountStorage.getItem("nexus-reader-tts-preset")).toBe("qwen3_clone");
    expect(accountStorage.getItem("nexus-reader-tts-execution")).toBe("server");
  });

  it("explains a pronunciation planning limit for its chapter outcome", async () => {
    vi.mocked(audioService.createStory).mockResolvedValue({novel_id:11,outcomes:[{chapter_number:1,outcome:"unavailable",job:null,error_code:"audio_planning_limit",message:"Shorten or disable pronunciations before preparing this chapter."}]});
    mount();
    await screen.findByRole("checkbox",{name:"Chapter 1: Opening"});
    fireEvent.click(screen.getByRole("checkbox",{name:"Chapter 1: Opening"}));
    await waitFor(()=>expect(screen.getByRole("button",{name:"Create selected audio"})).toBeEnabled());
    fireEvent.click(screen.getByRole("button",{name:"Create selected audio"}));
    expect(await screen.findByText("Chapter 1: Shorten or disable pronunciations before preparing this chapter.")).toBeInTheDocument();
    expect(ttsService.synthesize).not.toHaveBeenCalled();
  });

  it("bounds ranges and preserves a selection after queue failure", async () => {
    vi.mocked(audioService.createStory).mockRejectedValue(new Error("Offline"));
    vi.mocked(audioService.story).mockImplementation(async(_id,_offset,_limit,range)=>range?.to_chapter===201?{...overview(),total:201}:overview());mount();
    await screen.findByText(/1 of 2 chapters downloaded/);
    fireEvent.change(screen.getByLabelText("Through chapter"), { target: { value: "201" } });
    fireEvent.click(screen.getByRole("button", { name: "Add chapter range" }));
    expect(await screen.findByText(/range contains more than 200 chapters/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: "Chapter 1: Opening" }));
    fireEvent.click(screen.getByRole("button", { name: "Create selected audio" }));
    expect(await screen.findByText(/Your selection is preserved/)).toBeInTheDocument();
    expect(screen.getByText("1 chapters selected: 1")).toBeInTheDocument();
  });

  it("selects actual negative, zero and gapped chapters without inventing integer entries",async()=>{
    const value={...overview(),total:3,summary:{...overview().summary,chapters:3,downloaded:3},chapters:[-2,0,7].map((number,index)=>({...overview().chapters[0],...identity(11,number),id:200+index,chapter_number:number,title:`Entry ${number}`}))};
    vi.mocked(audioService.story).mockResolvedValue(value);mount();await screen.findByRole("checkbox",{name:"Chapter 0: Entry 0"});
    fireEvent.change(screen.getByLabelText("From chapter"),{target:{value:"-2"}});fireEvent.change(screen.getByLabelText("Through chapter"),{target:{value:"7"}});
    fireEvent.click(screen.getByRole("button",{name:"Add chapter range"}));await screen.findByText("3 chapters selected: -2, 0, 7");
    expect(audioService.story).toHaveBeenCalledWith(11,0,200,{from_chapter:-2,to_chapter:7});
    fireEvent.click(screen.getByRole("button",{name:"Create selected audio"}));
    await waitFor(()=>expect(audioService.createStory).toHaveBeenCalledWith(11,expect.objectContaining({chapter_numbers:[-2,0,7],chapter_identities:[-2,0,7].map(chapter_number=>({chapter_number,...expectedChapterIdentity(identity(11,chapter_number),"current")}))})));
  });
  it("keeps the selected old identity when another page reports a newer topology",async()=>{
    const initial={...overview(),total:51},newer={...overview(),total:51,offset:50,chapters:[{...overview().chapters[0],...identity(11,51,"2"),id:151,chapter_number:51,title:"Later entry"}]};
    vi.mocked(audioService.story).mockImplementation(async(_id,offset)=>offset===50?newer:initial);mount();await screen.findByRole("checkbox",{name:"Chapter 1: Opening"});
    fireEvent.click(screen.getByRole("checkbox",{name:"Chapter 1: Opening"}));fireEvent.click(screen.getByRole("button",{name:"Next chapters"}));await screen.findByRole("checkbox",{name:"Chapter 51: Later entry"});
    fireEvent.click(screen.getByRole("button",{name:"Create selected audio"}));await screen.findByText(/chapter list changed/);
    expect(audioService.createStory).not.toHaveBeenCalled();expect(browserAudioQueue.enqueue).not.toHaveBeenCalled();expect(screen.getByText("1 chapters selected: 1")).toBeInTheDocument();
  });
  it("requires a ready narrator and links to global Settings", async () => {
    vi.mocked(voiceService.list).mockResolvedValue([{ id: 3, name: "Preparing", language: "English", status: "processing", transcript: "", error: null, preview_ready: false }]); mount();
    await screen.findByText(/No narrator is ready/);
    fireEvent.click(screen.getByRole("checkbox", { name: "Chapter 1: Opening" }));
    expect(screen.getByRole("button", { name: "Create selected audio" })).toBeDisabled();
    expect(screen.getByRole("link", { name: /Manage narrator voices/ })).toHaveAttribute("href", "/settings/voices");
    expect(audioService.createStory).not.toHaveBeenCalled();
  });

  it("shows segment progress and supports explicit cancellation and retry", async () => {
    const value = overview(); value.chapters[0].latest_job = job("processing"); value.chapters[1].latest_job = { ...job("failed"), id: 9 }; value.summary.queued = 1; value.summary.needs_retry = 1;
    vi.mocked(audioService.story).mockResolvedValue(value); mount();
    expect(await screen.findByRole("progressbar", { name: "Chapter 1 audio preparation" })).toHaveAttribute("value", "1");
    fireEvent.click(screen.getByRole("button", { name: "Cancel chapter 1" }));
    await waitFor(() => expect(audioService.cancel).toHaveBeenCalledWith(8));
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry chapter 2" })).toBeEnabled());
    fireEvent.click(screen.getByRole("button", { name: "Retry chapter 2" }));
    await waitFor(() => expect(audioService.retry).toHaveBeenCalledWith(9));
  });

  it("updates progress while the page remains open", async () => {
    vi.useFakeTimers(); mount();
    await act(async () => { await Promise.resolve(); });
    const value = overview(); value.summary.ready = 1; value.chapters[0].latest_job = job("completed"); vi.mocked(audioService.story).mockResolvedValue(value);
    await act(async () => { await vi.advanceTimersByTimeAsync(3000); });
    expect(screen.getByText(/1 chapters ready to listen/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Listen to chapter 1" })).toBeInTheDocument();
    expect(screen.getByText(/earlier chapter version/)).toBeInTheDocument();
  });

  it("discards an audio response after switching accounts", async () => {
    const value = overview(); value.chapters[0].latest_job = job("completed"); vi.mocked(audioService.story).mockResolvedValue(value);
    let finish!: (blob: Blob) => void; vi.mocked(audioService.audio).mockReturnValue(new Promise(resolve => { finish = resolve; }));
    const objectURL = vi.fn(); vi.stubGlobal("URL", { createObjectURL: objectURL, revokeObjectURL: vi.fn() }); mount();
    fireEvent.click(await screen.findByRole("button", { name: "Listen to chapter 1" }));
    act(() => activateAccountStorage(8));
    await act(async () => finish(new Blob(["private audio"])));
    expect(objectURL).not.toHaveBeenCalled(); expect(screen.queryByLabelText("Chapter 1 audio")).not.toBeInTheDocument();
  });
  it("uses the server narrator across devices without changing its default for this form", async () => {
    accountStorage.setItem("nexus-reader-narrator-id", "999"); mount();
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Narrator" })).toHaveValue("3"));
    fireEvent.change(screen.getByRole("combobox", { name: "Narrator" }), { target: { value: "" } });
    expect(voiceService.setDefault).not.toHaveBeenCalled();
    expect(accountStorage.getItem("nexus-reader-narrator-id")).toBe("999");
  });

  it("keeps chapter audio available when the narrator list cannot refresh", async () => {
    const value = overview(); value.chapters[0].latest_job = job("completed");
    vi.mocked(audioService.story).mockResolvedValue(value); vi.mocked(voiceService.list).mockRejectedValue(new Error("Unavailable")); mount();
    expect(await screen.findByRole("button", { name: "Listen to chapter 1" })).toBeInTheDocument();
    expect(screen.getByText(/Couldn’t load narrator voices/)).toBeInTheDocument();
  });

  it("preserves selections across chapter pages", async () => {
    const first = overview(); first.total = 51;
    const second = { ...overview(), total: 51, offset: 50, chapters: [{ ...overview().chapters[0],...identity(11,51), id: 151, chapter_number: 51, title: "Ending" }] };
    vi.mocked(audioService.story).mockImplementation(async (_id, offset) => offset === 50 ? second : first); mount();
    fireEvent.click(await screen.findByRole("checkbox", { name: "Chapter 1: Opening" }));
    fireEvent.click(screen.getByRole("button", { name: "Next chapters" }));
    fireEvent.click(await screen.findByRole("checkbox", { name: "Chapter 51: Ending" }));
    expect(screen.getByText("2 chapters selected: 1, 51")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Create selected audio" }));
    await waitFor(() => expect(audioService.createStory).toHaveBeenCalledWith(11, { chapter_numbers: [1, 51],chapter_identities:[{chapter_number:1,...expectedChapterIdentity(identity(11,1),"current")},{chapter_number:51,...expectedChapterIdentity(identity(11,51),"current")}], voice_profile_id: 3, include_author_notes: false }));
  });

  it("preserves preset choices, requires an explicit browser action, and keeps its key out of server requests", async () => {
    mount(); await screen.findByRole("combobox", { name: "Narrator" });
    fireEvent.change(screen.getByRole("combobox", { name: "Voice provider" }), { target: { value: "custom" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Generate audio" }), { target: { value: "browser" } });
    fireEvent.change(screen.getByLabelText("API base URL"), { target: { value: "http://localhost:18980/v1" } });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "fixture-model" } });
    fireEvent.change(screen.getByLabelText("Voice", { exact: true }), { target: { value: "fixture-voice" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "private-browser-key" } });
    expect(browserAudioQueue.enqueue).not.toHaveBeenCalled(); expect(ttsService.synthesize).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("checkbox", { name: "Chapter 1: Opening" }));
    fireEvent.click(screen.getByRole("button", { name: "Create selected audio" }));
    await waitFor(() => expect(browserAudioQueue.enqueue).toHaveBeenCalledWith(expect.objectContaining({ novelId: 11, libraryId: 1, chapterNumbers: [1], provider: expect.objectContaining({ baseUrl: "http://localhost:18980/v1", apiKey: "private-browser-key", model: "fixture-model", voice: "fixture-voice" }) })));
    expect(audioService.createStory).not.toHaveBeenCalled(); expect(accountStorage.getItem("nexus-reader-tts-key")).toBeNull();
    expect(accountStorage.getItem("nexus-reader-tts-execution")).toBe("browser");
  });

  it("maps known local presets to the server host while preserving manually entered addresses", async () => {
    mount(); await screen.findByRole("combobox", { name: "Narrator" });
    fireEvent.change(screen.getByRole("combobox", { name: "Voice provider" }), { target: { value: "kokoro_mps" } });
    expect(screen.getByLabelText("API base URL")).toHaveValue("http://host.docker.internal:8880/v1");
    fireEvent.change(screen.getByRole("combobox", { name: "Generate audio" }), { target: { value: "browser" } });
    expect(screen.getByLabelText("API base URL")).toHaveValue("http://localhost:8880/v1");
    fireEvent.change(screen.getByLabelText("API base URL"), { target: { value: "http://speech.home:8880/v1" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Generate audio" }), { target: { value: "server" } });
    expect(screen.getByLabelText("API base URL")).toHaveValue("http://speech.home:8880/v1");
    fireEvent.click(screen.getByRole("checkbox", { name: "Chapter 1: Opening" }));
    fireEvent.click(screen.getByRole("button", { name: "Create selected audio" }));
    await waitFor(() => expect(audioService.createStory).toHaveBeenCalledWith(11, { chapter_numbers: [1],chapter_identities:[{chapter_number:1,...expectedChapterIdentity(identity(11,1),"current")}], include_author_notes: false, provider: { id: "kokoro_mps", base_url: "http://speech.home:8880/v1", model: "kokoro", voice: "af_bella", language_code: undefined, execution_mode: "server" } }));
  });

  it("blocks key-bearing server generation instead of discarding its key or moving providers", async () => {
    mount(); await screen.findByRole("combobox", { name: "Narrator" });
    fireEvent.change(screen.getByRole("combobox", { name: "Voice provider" }), { target: { value: "custom" } });
    fireEvent.change(screen.getByLabelText("API base URL"), { target: { value: "https://speech.example/v1" } });
    fireEvent.change(screen.getByLabelText("Model"), { target: { value: "chosen-model" } });
    fireEvent.change(screen.getByLabelText("Voice", { exact: true }), { target: { value: "chosen-voice" } });
    fireEvent.change(screen.getByLabelText("API key"), { target: { value: "private-browser-key" } });
    fireEvent.click(screen.getByRole("checkbox", { name: "Chapter 1: Opening" }));
    expect(screen.getByRole("button", { name: "Create selected audio" })).toBeDisabled();
    expect(screen.getByText(/This key can only be used in this browser/)).toBeInTheDocument();
    expect(audioService.createStory).not.toHaveBeenCalled(); expect(browserAudioQueue.enqueue).not.toHaveBeenCalled();
  });

  it("merges persisted browser progress and allows explicit browser retry and cancellation", async () => {
    vi.mocked(browserAudioQueue.getSnapshot).mockReturnValue({ generation: storageGeneration(), running: true, rows: [
      { novelId: 11, libraryId: 1, chapterNumber: 1,chapterIdentity:identity(11,1), status: "generating", totalParts: 3, completedParts: 1 },
      { novelId: 11, libraryId: 1, chapterNumber: 2,chapterIdentity:identity(11,2), status: "failed", totalParts: 3, completedParts: 1, error: "Fixture provider interrupted" },
    ] });
    mount(); await screen.findByRole("combobox", { name: "Narrator" });
    fireEvent.change(screen.getByRole("combobox", { name: "Voice provider" }), { target: { value: "kokoro_mps" } });
    fireEvent.change(screen.getByRole("combobox", { name: "Generate audio" }), { target: { value: "browser" } });
    expect(screen.getByRole("progressbar", { name: "Chapter 1 browser audio preparation" })).toHaveAttribute("value", "1");
    fireEvent.click(screen.getByRole("button", { name: "Cancel local chapter 1" })); expect(browserAudioQueue.cancel).toHaveBeenCalledWith(11, 1);
    fireEvent.click(screen.getByRole("button", { name: "Retry local chapter 2" })); expect(browserAudioQueue.retry).toHaveBeenCalledWith(expect.objectContaining({ chapterNumbers: [2] }));
    expect(screen.getByText("Fixture provider interrupted")).toBeInTheDocument();
    expect(browserAudioQueue.hydrate).toHaveBeenCalledWith(11, 1, [1, 2]);
    expect(audioService.retry).not.toHaveBeenCalled();
  });

  it("strips browser secrets from the real server batch transport", async () => {
    const real = await vi.importActual<typeof import("../../services/audioService")>("../../services/audioService");
    const post = vi.spyOn(apiClient, "post").mockResolvedValue({ data: { novel_id: 11, outcomes: [] } });
    const provider = { id: "custom", execution_mode: "server" as const, base_url: "http://local-speech:8880/v1", model: "fixture", voice: "fixture", api_key: "browser-only-private-key", apiKey: "browser-only-private-key" };
    await real.audioService.createStory(11, { chapter_numbers: [1, 2], include_author_notes: false, provider });
    expect(post).toHaveBeenCalledWith("/audio/stories/11/jobs", { chapter_numbers: [1, 2], include_author_notes: false, provider: { id: "custom", execution_mode: "server", base_url: "http://local-speech:8880/v1", model: "fixture", voice: "fixture", language_code: undefined } });
    expect(JSON.stringify(post.mock.calls)).not.toContain("browser-only-private-key");
  });

  it("reviews removal of a local recording before allowing a different provider", async () => {
    vi.mocked(browserAudioQueue.getSnapshot).mockReturnValue({ generation: storageGeneration(), running: false, rows: [
      { novelId: 11, libraryId: 1, chapterNumber: 1,chapterIdentity:identity(11,1), status: "failed", totalParts: 3, completedParts: 1, error: "Existing browser audio uses another voice." },
    ] }); mount();
    await screen.findByRole("checkbox", { name: "Chapter 1: Opening" });
    fireEvent.click(screen.getByRole("button", { name: "Remove local chapter 1" }));
    expect(screen.getByRole("dialog", { name: "Remove this device’s chapter 1 audio?" })).toBeInTheDocument();
    expect(browserAudioQueue.remove).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Remove recording" }));
    await waitFor(() => expect(browserAudioQueue.remove).toHaveBeenCalledWith(11, 1));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(audioService.createStory).not.toHaveBeenCalled();
  });

  it("never labels a cached server recording as the browser narrator’s audio", async () => {
    vi.mocked(browserAudioQueue.getSnapshot).mockReturnValue({ generation: storageGeneration(), running: false, rows: [
      { novelId: 11, libraryId: 1, chapterNumber: 1,chapterIdentity:identity(11,1), status: "ready", totalParts: 3, completedParts: 3, sourceVersion: "current" },
    ] });
    vi.mocked(chapterAudioStore.recording).mockResolvedValue({ audio: new Blob(["server audio"]), manifest: { job_id: 8, source_version: "current", rendition: "original", precision: "segment", include_author_notes: false, duration_seconds: 2, segments: [] } });
    const objectURL = vi.fn(); vi.stubGlobal("URL", { createObjectURL: objectURL, revokeObjectURL: vi.fn() }); mount();
    await screen.findByRole("checkbox", { name: "Chapter 1: Opening" });
    fireEvent.click(screen.getByRole("button", { name: "Listen to local chapter 1" }));
    expect(await screen.findByText(/saved audio has changed/)).toBeInTheDocument();
    expect(objectURL).not.toHaveBeenCalled();
    expect(screen.queryByLabelText("Chapter 1 audio")).not.toBeInTheDocument();
  });

});
