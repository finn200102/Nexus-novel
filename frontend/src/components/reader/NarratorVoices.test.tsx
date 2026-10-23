import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import {NarratorVoices} from "./NarratorVoices";
import {voiceService, type NarratorVoice} from "../../services/voiceService";
import {activateAccountStorage} from "../../services/accountStorage";
vi.mock("../../services/voiceService", () => ({voiceService:{list:vi.fn(),capabilities:vi.fn(),upload:vi.fn(),preview:vi.fn(),remove:vi.fn(),retry:vi.fn()}}));
const ready: NarratorVoice={id:3,name:"My private voice",language:"German",status:"completed",transcript:"Words",error:null,preview_ready:true};
describe("private narrator voices",()=>{
  afterEach(()=>{cleanup();vi.unstubAllGlobals();vi.restoreAllMocks();});
  beforeEach(()=>{vi.clearAllMocks();vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>undefined);activateAccountStorage(1);vi.mocked(voiceService.list).mockResolvedValue([]);vi.mocked(voiceService.capabilities).mockResolvedValue({configured:true,languages:["English","German"]});});
  it("uploads a recording and selects a ready narrator",async()=>{
    vi.mocked(voiceService.list).mockResolvedValue([ready]);
    vi.mocked(voiceService.upload).mockResolvedValue({...ready,id:4,status:"queued",name:"New narrator"});
    const select=vi.fn();render(<NarratorVoices selected={null} onSelect={select}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Use as narrator"}));expect(select).toHaveBeenCalledWith(ready);
    fireEvent.change(await screen.findByLabelText(/^Narrator name/),{target:{value:"New narrator"}});
    fireEvent.change(screen.getByLabelText(/^Voice recording/),{target:{files:[new File(["audio"],"reference.wav",{type:"audio/wav"})]}});
    fireEvent.submit(screen.getByRole("button",{name:"Create narrator voice"}).closest("form")!);
    await waitFor(()=>expect(voiceService.upload).toHaveBeenCalledWith({name:"New narrator",language:"English",transcript:"",audio_base64:"YXVkaW8="}));
    expect(await screen.findByText("New narrator")).toBeInTheDocument();
  });
  it("keeps Qwen as default and sends an explicitly selected Fish engine",async()=>{
    vi.mocked(voiceService.capabilities).mockResolvedValue({configured:true,languages:["English"],engines:[{id:"qwen",label:"Qwen TTS",configured:true},{id:"fish",label:"Fish Audio",configured:true}]});
    vi.mocked(voiceService.upload).mockResolvedValue({...ready,id:4,status:"queued"});
    render(<NarratorVoices selected={null} onSelect={vi.fn()}/>);
    const engine=await screen.findByRole("combobox",{name:"Speech engine"});
    expect(engine).toHaveValue("qwen");
    fireEvent.change(engine,{target:{value:"fish"}});
    fireEvent.change(screen.getByLabelText(/^Narrator name/),{target:{value:"Fish narrator"}});
    fireEvent.change(screen.getByLabelText(/^Voice recording/),{target:{files:[new File(["audio"],"reference.wav",{type:"audio/wav"})]}});
    fireEvent.change(screen.getByLabelText(/^Recording transcript/),{target:{value:"Exact reference words"}});
    fireEvent.submit(screen.getByRole("button",{name:"Create narrator voice"}).closest("form")!);
    await waitFor(()=>expect(voiceService.upload).toHaveBeenCalledWith(expect.objectContaining({engine:"fish",transcript:"Exact reference words"})));
  });
  it("requires an exact reference transcript when local transcription is unavailable",async()=>{
    vi.mocked(voiceService.capabilities).mockResolvedValue({configured:true,languages:["English"],transcript_required:true});
    render(<NarratorVoices selected={null} onSelect={vi.fn()}/>);
    expect(await screen.findByLabelText(/^Recording transcript \(required\)/)).toBeRequired();
    fireEvent.change(screen.getByLabelText(/^Narrator name/),{target:{value:"Local voice"}});
    fireEvent.change(screen.getByLabelText(/^Voice recording/),{target:{files:[new File(["audio"],"reference.wav",{type:"audio/wav"})]}});
    expect(screen.getByRole("button",{name:"Create narrator voice"})).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Recording transcript/),{target:{value:"Reference words"}});
    expect(screen.getByRole("button",{name:"Create narrator voice"})).toBeEnabled();
  });
  it("discards private voice results after an account switch",async()=>{
    let finish!:(voices:NarratorVoice[])=>void;
    vi.mocked(voiceService.list).mockReturnValue(new Promise(resolve=>{finish=resolve;}));
    const view=render(<NarratorVoices selected={null} onSelect={vi.fn()}/>);
    activateAccountStorage(2);
    await act(async()=>finish([ready]));
    expect(screen.queryByText("My private voice")).not.toBeInTheDocument();view.unmount();
  });
  it("deletes a selected voice and clears the selection",async()=>{
    vi.mocked(voiceService.list).mockResolvedValue([ready]);vi.mocked(voiceService.remove).mockResolvedValue(undefined);
    const select=vi.fn();render(<NarratorVoices selected={3} onSelect={select}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Delete My private voice"}));
    await waitFor(()=>expect(select).toHaveBeenCalledWith(null));expect(screen.queryByText("My private voice")).not.toBeInTheDocument();
  });
  it("does not revive a private preview after changing accounts",async()=>{
    vi.mocked(voiceService.list).mockResolvedValue([ready]);
    let finish!:(blob:Blob)=>void;
    vi.mocked(voiceService.preview).mockReturnValue(new Promise(resolve=>{finish=resolve;}));
    const objectURL=vi.fn();vi.stubGlobal("URL",{createObjectURL:objectURL,revokeObjectURL:vi.fn()});
    render(<NarratorVoices selected={null} onSelect={vi.fn()}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Listen to My private voice"}));
    activateAccountStorage(2);
    await act(async()=>finish(new Blob(["private audio"])));
    expect(objectURL).not.toHaveBeenCalled();expect(screen.queryByLabelText("Cloned narrator preview")).not.toBeInTheDocument();
  });

  it("stops private preview playback and revokes its URL on unmount",async()=>{
    vi.mocked(voiceService.list).mockResolvedValue([ready]);
    vi.mocked(voiceService.preview).mockResolvedValue(new Blob(["private audio"]));
    const revoke=vi.fn();vi.stubGlobal("URL",{createObjectURL:vi.fn(()=>"blob:private-preview"),revokeObjectURL:revoke});
    const pause=vi.spyOn(HTMLMediaElement.prototype,"pause").mockImplementation(()=>undefined);
    const view=render(<NarratorVoices selected={null} onSelect={vi.fn()}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Listen to My private voice"}));
    await screen.findByLabelText("Cloned narrator preview");view.unmount();
    expect(pause).toHaveBeenCalled();expect(revoke).toHaveBeenCalledWith("blob:private-preview");
  });

  it("previews a long recording and uploads only the explicitly selected reference range", async () => {
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:reference"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    vi.mocked(voiceService.upload).mockResolvedValue({ ...ready, id: 4, status: "queued" });
    render(<NarratorVoices selected={null} onSelect={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText(/^Narrator name/), { target: { value: "My narrator" } });
    fireEvent.change(screen.getByLabelText(/^Voice recording/), { target: { files: [new File(["audio"], "long-reference.mp3", { type: "audio/mpeg" })] } });
    const audio = await screen.findByLabelText("Selected recording preview");
    fireEvent.change(screen.getByLabelText(/^Recording transcript/), { target: { value: "Full minute of words that must not accompany a short excerpt" } });
    Object.defineProperty(audio, "duration", { configurable: true, value: 60 }); fireEvent.loadedMetadata(audio);
    expect(screen.getByLabelText(/^Selected excerpt transcript/)).toHaveValue("");
    expect(screen.getByText(/Selected reference: 0–15 seconds/)).toBeInTheDocument();
    expect(screen.getByText(/The excerpt changed/)).toBeInTheDocument();
    expect(screen.getByLabelText("Excerpt start (seconds)")).toHaveValue(0);
    expect(screen.getByLabelText("Excerpt end (seconds)")).toHaveValue(15);
    expect(screen.getByText(/Cloning uses only the selected excerpt/)).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Excerpt start (seconds)"), { target: { value: "20" } });
    fireEvent.change(screen.getByLabelText("Excerpt end (seconds)"), { target: { value: "35" } });
    fireEvent.change(screen.getByLabelText(/^Selected excerpt transcript/), { target: { value: "Only selected words" } });
    fireEvent.submit(screen.getByRole("button", { name: "Create narrator voice" }).closest("form")!);
    await waitFor(() => expect(voiceService.upload).toHaveBeenCalledWith({ name: "My narrator", audio_base64: "YXVkaW8=", transcript: "Only selected words", language: "English", excerpt_start_seconds: 20, excerpt_duration_seconds: 15 }));
  });

  it("blocks an obviously long full-file transcript for a short selected reference", async () => {
    vi.stubGlobal("URL", {createObjectURL:vi.fn(()=>"blob:reference"),revokeObjectURL:vi.fn()});
    render(<NarratorVoices selected={null} onSelect={vi.fn()}/>);
    fireEvent.change(await screen.findByLabelText(/^Narrator name/),{target:{value:"My narrator"}});
    fireEvent.change(screen.getByLabelText(/^Voice recording/),{target:{files:[new File(["audio"],"long.mp3",{type:"audio/mpeg"})]}});
    const audio=await screen.findByLabelText("Selected recording preview");
    Object.defineProperty(audio,"duration",{configurable:true,value:60});fireEvent.loadedMetadata(audio);
    fireEvent.change(screen.getByLabelText(/^Selected excerpt transcript/),{target:{value:Array(178).fill("word").join(" ")}});
    expect(screen.getByText(/This transcript has too many words/)).toBeInTheDocument();
    expect(screen.getByRole("button",{name:"Create narrator voice"})).toBeDisabled();
    fireEvent.submit(screen.getByRole("button",{name:"Create narrator voice"}).closest("form")!);
    expect(voiceService.upload).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText(/^Selected excerpt transcript/),{target:{value:Array(45).fill("word").join(" ")}});
    expect(screen.getByRole("button",{name:"Create narrator voice"})).toBeEnabled();
  });

  it("bounds excerpts and clears an old transcript when the selected passage changes", async () => {
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:reference"), revokeObjectURL: vi.fn() });
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    render(<NarratorVoices selected={null} onSelect={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText(/^Narrator name/), { target: { value: "My narrator" } });
    fireEvent.change(screen.getByLabelText(/^Voice recording/), { target: { files: [new File(["audio"], "long.mp3", { type: "audio/mpeg" })] } });
    const audio = await screen.findByLabelText("Selected recording preview");
    Object.defineProperty(audio, "duration", { configurable: true, value: 60 }); fireEvent.loadedMetadata(audio);
    fireEvent.change(screen.getByLabelText(/^Selected excerpt transcript/), { target: { value: "A previous passage" } });
    fireEvent.change(screen.getByLabelText("Excerpt end (seconds)"), { target: { value: "45" } });
    expect(screen.getByRole("button", { name: "Create narrator voice" })).toBeDisabled();
    expect(screen.getByLabelText(/^Selected excerpt transcript/)).toHaveValue("");
    expect(screen.getByText(/The excerpt changed/)).toBeInTheDocument();
    fireEvent.submit(screen.getByRole("button", { name: "Create narrator voice" }).closest("form")!);
    expect(voiceService.upload).not.toHaveBeenCalled();
  });

  it("explains a proxy upload rejection and preserves the file for retry", async () => {
    vi.mocked(voiceService.upload).mockRejectedValue({ isAxiosError: true, response: { status: 413, data: "<html>Too large</html>" } });
    render(<NarratorVoices selected={null} onSelect={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText(/^Narrator name/), { target: { value: "My narrator" } });
    const file = new File(["audio"], "reference.mp3", { type: "audio/mpeg" });
    fireEvent.change(screen.getByLabelText(/^Voice recording/), { target: { files: [file] } });
    fireEvent.submit(screen.getByRole("button", { name: "Create narrator voice" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent(/server’s narrator upload limit needs to be increased/);
    expect((screen.getByLabelText(/^Voice recording/) as HTMLInputElement).files?.[0]).toBe(file);
    expect(screen.getByLabelText(/^Narrator name/)).toHaveValue("My narrator");
  });

  it("shows server validation details without replacing them with a connection error", async () => {
    vi.mocked(voiceService.upload).mockRejectedValue({ isAxiosError: true, response: { status: 422, data: { detail: "The selected excerpt extends beyond the recording." } } });
    render(<NarratorVoices selected={null} onSelect={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText(/^Narrator name/), { target: { value: "My narrator" } });
    fireEvent.change(screen.getByLabelText(/^Voice recording/), { target: { files: [new File(["audio"], "reference.wav", { type: "audio/wav" })] } });
    fireEvent.submit(screen.getByRole("button", { name: "Create narrator voice" }).closest("form")!);
    expect(await screen.findByRole("alert")).toHaveTextContent("The selected excerpt extends beyond the recording.");
  });

  it("stops the original recording preview on unmount even after its DOM ref is detached", async () => {
    const revoke = vi.fn(); vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:private-original"), revokeObjectURL: revoke });
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const play = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const view = render(<NarratorVoices selected={null} onSelect={vi.fn()} />);
    fireEvent.change(await screen.findByLabelText(/^Voice recording/), { target: { files: [new File(["audio"], "private-original.wav", { type: "audio/wav" })] } });
    const audio = await screen.findByLabelText("Selected recording preview");
    fireEvent.click(screen.getByRole("button", { name: "Preview recording" }));
    expect(play.mock.contexts).toContain(audio);
    view.unmount();
    expect(pause.mock.contexts).toContain(audio);
    expect(revoke).toHaveBeenCalledWith("blob:private-original");
  });

});
