import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ListenPlayer from "./ListenPlayer";
import { accountStorage, activateAccountStorage } from "../../services/accountStorage";
import { audioService } from "../../services/audioService";
import { chapterAudioStore } from "../../services/offlineReaderStore";

vi.mock("../../services/voiceService", () => ({voiceService:{list:vi.fn().mockResolvedValue([]),capabilities:vi.fn().mockResolvedValue({configured:false,languages:[]})}}));
vi.mock("../../services/audioService", () => ({ audioService: { list: vi.fn(), audio: vi.fn() } }));
vi.mock("../../services/offlineReaderStore",()=>{
  const store={ get: vi.fn() };
  return {chapterAudioStore:{...store,recording:vi.fn(async()=>{const audio=await store.get();return audio?{audio,manifest:null}:null;})},chapterAudioJobStore:{get:vi.fn().mockResolvedValue(null)}};
});
const chapter = { id: 1, chapter_number: 1, title: "Private chapter", content: "Private text" };

describe("account-scoped listening", () => {
  afterEach(() => vi.unstubAllGlobals());
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    activateAccountStorage(1);
    vi.mocked(audioService.list).mockResolvedValue([]);
    vi.mocked(chapterAudioStore.get).mockResolvedValue(null);
  });

  it("stores speed and provider settings in the active account only", async () => {
    const view = render(<ListenPlayer chapter={chapter} libraryId={1} novelId={1} open onClose={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Speed"), { target: { value: "1.4" } });
    await waitFor(() => expect(accountStorage.getItem("nexus-reader-tts-rate")).toBe("1.4"));
    expect(localStorage.getItem("nexus-reader-tts-rate")).toBeNull();
    view.unmount();
    activateAccountStorage(2);
    expect(accountStorage.getItem("nexus-reader-tts-rate")).toBeNull();
    expect(accountStorage.getItem("nexus-reader-tts-key")).toBeNull();
  });

  it("completed server audio is playable without waiting for a queued-job poll", async () => {
    accountStorage.setItem("nexus-reader-tts-engine", "openai_compatible");
    vi.mocked(audioService.list).mockResolvedValue([{ id: 8, status: "completed", audio_ready: true,
      provider_id: "test", provider_model: "test", provider_voice: "test", total_parts: 1, completed_parts: 1 }]);
    render(<ListenPlayer chapter={chapter} libraryId={1} novelId={1} open onClose={vi.fn()} />);
    expect(await screen.findByRole("button", { name: "Play" })).toBeInTheDocument();
  });

  it("discards audio loaded after an account switch", async () => {
    accountStorage.setItem("nexus-reader-tts-engine", "openai_compatible");
    let resolve!: (blob: Blob) => void;
    const pending = new Promise<Blob>(done => { resolve = done; });
    vi.mocked(chapterAudioStore.get).mockResolvedValueOnce(new Blob(["cached"])).mockReturnValueOnce(pending);
    const audio = vi.fn();
    vi.stubGlobal("Audio", audio);
    const view = render(<ListenPlayer chapter={chapter} libraryId={1} novelId={1} open onClose={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: "Play" }));
    activateAccountStorage(2);
    view.unmount();
    await act(async () => resolve(new Blob(["late result"])));
    expect(audio).not.toHaveBeenCalled();
    expect(accountStorage.getItem("nexus-reader-audio-position-1-1")).toBeNull();
  });
});

describe("cloned narrator controls", () => {
  it("keeps existing chapter audio removable when choosing a cloned narrator", async () => {
    localStorage.clear();activateAccountStorage(1);
    accountStorage.setItem("nexus-reader-tts-engine", "openai_compatible");
    accountStorage.setItem("nexus-reader-tts-preset", "qwen3_clone");
    accountStorage.setItem("nexus-reader-tts-execution", "server");
    vi.mocked(chapterAudioStore.get).mockResolvedValue(null);
    vi.mocked(audioService.list).mockResolvedValue([{id:9,status:"completed",audio_ready:true,provider_id:"qwen3_clone",provider_model:"Qwen",provider_voice:"Private narrator",total_parts:1,completed_parts:1}]);
    render(<ListenPlayer chapter={chapter} libraryId={1} novelId={1} open onClose={vi.fn()}/>);
    await screen.findByRole("button",{name:"Play"});
    fireEvent.click(screen.getByRole("button",{name:"Listen settings"}));
    expect(await screen.findByRole("button",{name:"Delete this chapter’s audio"})).toBeInTheDocument();
    expect(screen.getByLabelText("Voice provider")).toHaveValue("qwen3_clone");
  });
});
