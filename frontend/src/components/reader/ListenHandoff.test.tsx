import {StrictMode} from "react";
import {act,cleanup,fireEvent,render,screen,waitFor} from "@testing-library/react";
import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import ListenPlayer from "./ListenPlayer";
import {activateAccountStorage,accountStorage} from "../../services/accountStorage";
import {audioService} from "../../services/audioService";
import {chapterAudioStore} from "../../services/offlineReaderStore";
import type {AudioManifest} from "../../services/audioAlignment";
import type {ChapterDocument} from "./chapterDocument";
vi.mock("../../services/audioService",()=>({audioService:{list:vi.fn(),audio:vi.fn(),manifest:vi.fn(),remove:vi.fn().mockResolvedValue(undefined),create:vi.fn()}}));
vi.mock("../../services/offlineReaderStore",()=>{
  const store={get:vi.fn(),save:vi.fn().mockResolvedValue(undefined),manifest:vi.fn(),removeForJob:vi.fn().mockResolvedValue(undefined)};
  return {chapterAudioStore:{...store,recording:vi.fn(async()=>{const audio=await store.get();return audio?{audio,manifest:await store.manifest()}:null;})},chapterAudioJobStore:{get:vi.fn().mockResolvedValue(null)}};
});
vi.mock("../../services/voiceService",()=>({voiceService:{list:vi.fn().mockResolvedValue([]),capabilities:vi.fn().mockResolvedValue({configured:false,languages:[]})}}));
const doc:ChapterDocument={schema_version:1,content_version:"original",source_format:"html",plain_text:"First passage. Last passage.",blocks:[{id:"first",kind:"p",html:"<p>First passage.</p>",text:"First passage."},{id:"last",kind:"p",html:"<p>Last passage.</p>",text:"Last passage."}]};
const manifest:AudioManifest={job_id:7,source_version:"original",precision:"segment",rendition:"original",include_author_notes:false,duration_seconds:20,segments:[{part_index:0,block_id:null,text_offset:null,text_length:null,start_seconds:0,end_seconds:1},{part_index:1,block_id:"first",text_offset:0,text_length:14,start_seconds:1,end_seconds:15},{part_index:2,block_id:"last",text_offset:0,text_length:13,start_seconds:15,end_seconds:20}]};
class AudioFixture {
  static current:AudioFixture;
  static all:AudioFixture[]=[];
  static autoMetadata=true;
  constructor(){AudioFixture.current=this;AudioFixture.all.push(this);}
  private source="";
  get src(){return this.source;}
  set src(value:string){this.source=value;if(AudioFixture.autoMetadata)queueMicrotask(()=>this.onloadedmetadata?.());}
  preload="";currentTime=0;duration=20;playbackRate=1;
  play=vi.fn().mockResolvedValue(undefined);pause=vi.fn();
  onloadedmetadata:(()=>void)|null=null;ontimeupdate:(()=>void)|null=null;onended:(()=>void)|null=null;onerror:(()=>void)|null=null;
}
function deferred<T>(){let resolve!:(value:T)=>void;const promise=new Promise<T>(done=>{resolve=done;});return {promise,resolve};}

describe("version-bound reading and listening",()=>{
  beforeEach(()=>{vi.clearAllMocks();AudioFixture.all=[];AudioFixture.autoMetadata=true;localStorage.clear();activateAccountStorage(1);accountStorage.setItem("nexus-reader-tts-engine","openai_compatible");
    vi.mocked(audioService.list).mockResolvedValue([{id:7,status:"completed",provider_id:"custom",provider_model:"fixture",provider_voice:"narrator",total_parts:3,completed_parts:3,audio_ready:true}]);
    vi.mocked(audioService.audio).mockResolvedValue(new Blob(["audio"]));vi.mocked(audioService.manifest).mockResolvedValue(manifest);vi.mocked(chapterAudioStore.get).mockResolvedValue(null);
    vi.stubGlobal("Audio",AudioFixture);vi.stubGlobal("URL",{createObjectURL:()=>"blob:audio",revokeObjectURL:vi.fn()});
  });
  afterEach(()=>{cleanup();vi.unstubAllGlobals();});
  const props={chapter:{id:1,chapter_number:1,title:"Title",content:doc.plain_text,document:doc},libraryId:1,novelId:1,open:true,onClose:vi.fn(),readingLocator:()=>({blockId:"last",textOffset:4})};
  it("loads ready audio after StrictMode replays mount effects",async()=>{
    render(<StrictMode><ListenPlayer {...props}/></StrictMode>);
    expect(await screen.findByRole("button",{name:"Play"})).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button",{name:"Play"}));
    await screen.findByRole("button",{name:"Pause"});
    expect(AudioFixture.all).toHaveLength(1);
  });
  it("seeks to the measured segment and can return to its passage",async()=>{
    const read=vi.fn(),progress=vi.fn();render(<ListenPlayer {...props} onReadPassage={read} onAudioPassage={progress}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Listen from this passage"}));await screen.findByRole("button",{name:"Pause"});
    expect(AudioFixture.current.currentTime).toBe(15);expect(progress).toHaveBeenCalledWith(expect.objectContaining({blockId:"last",textOffset:0}),false);
    fireEvent.click(screen.getByRole("button",{name:"Read this passage"}));expect(read).toHaveBeenCalledWith(expect.objectContaining({blockId:"last",textOffset:0}));expect(AudioFixture.current.pause).toHaveBeenCalled();
    expect(chapterAudioStore.save).toHaveBeenCalledWith(1,1,expect.any(Blob),manifest,expect.any(Function));
  });
  it("keeps old audio playable but refuses progress and handoff to revised text",async()=>{
    vi.mocked(audioService.manifest).mockResolvedValue({...manifest,source_version:"older"});
    const progress=vi.fn();render(<ListenPlayer {...props} onAudioPassage={progress}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Listen from this passage"}));
    expect(await screen.findByRole("alert")).toHaveTextContent("cannot be linked");expect(AudioFixture.current.play).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"Play"}));await screen.findByRole("button",{name:"Pause"});
    act(()=>{AudioFixture.current.currentTime=16;AudioFixture.current.ontimeupdate?.();});expect(progress).not.toHaveBeenCalled();
    expect(screen.getByText(/earlier chapter version/)).toBeInTheDocument();
  });
  it("disables passage links if actual media duration disagrees with the manifest",async()=>{
    const progress=vi.fn();render(<ListenPlayer {...props} onAudioPassage={progress}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Play"}));await screen.findByRole("button",{name:"Pause"});
    act(()=>{AudioFixture.current.duration=40;AudioFixture.current.onloadedmetadata?.();AudioFixture.current.currentTime=16;AudioFixture.current.ontimeupdate?.();});
    expect(progress).not.toHaveBeenCalled();expect(screen.getByText(/no verified passage timings/)).toBeInTheDocument();
  });
  it("uses a matching cached audio and manifest pair when the server is unreachable",async()=>{
    vi.mocked(audioService.audio).mockRejectedValue(new Error("offline"));vi.mocked(chapterAudioStore.get).mockResolvedValue(new Blob(["cached audio"]));vi.mocked(chapterAudioStore.manifest).mockResolvedValue(manifest);
    const progress=vi.fn();render(<ListenPlayer {...props} onAudioPassage={progress}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Listen from this passage"}));await waitFor(()=>expect(AudioFixture.current.play).toHaveBeenCalled());
    expect(progress).toHaveBeenCalledWith(expect.objectContaining({blockId:"last"}),false);
  });
  it("coalesces Play and seek loads and pauses the sole player on close",async()=>{
    const fetch=deferred<Blob>();vi.mocked(audioService.audio).mockReturnValue(fetch.promise);
    const view=render(<ListenPlayer {...props}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Play"}));
    fireEvent.click(screen.getByRole("button",{name:"Forward 15 seconds"}));
    expect(audioService.audio).toHaveBeenCalledTimes(1);
    await act(async()=>fetch.resolve(new Blob(["audio"])));
    await screen.findByRole("button",{name:"Pause"});
    expect(AudioFixture.all).toHaveLength(1);
    view.rerender(<ListenPlayer {...props} open={false}/>);
    expect(AudioFixture.current.pause).toHaveBeenCalled();
  });
  it("does not hand off or report progress until actual metadata is verified",async()=>{
    AudioFixture.autoMetadata=false;
    const progress=vi.fn(),read=vi.fn();render(<ListenPlayer {...props} onReadPassage={read} onAudioPassage={progress}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Listen from this passage"}));
    await waitFor(()=>expect(AudioFixture.all).toHaveLength(1));
    expect(AudioFixture.current.play).not.toHaveBeenCalled();
    expect(screen.queryByRole("button",{name:"Read this passage"})).not.toBeInTheDocument();
    act(()=>{AudioFixture.current.currentTime=16;AudioFixture.current.ontimeupdate?.();});
    expect(progress).not.toHaveBeenCalled();
    act(()=>AudioFixture.current.onloadedmetadata?.());
    await screen.findByRole("button",{name:"Pause"});
    expect(AudioFixture.current.currentTime).toBe(15);
    expect(progress).toHaveBeenCalledWith(expect.objectContaining({blockId:"last"}),false);
  });
  it("does not let an older play promise pause a newer play attempt",async()=>{
    const first=deferred<void>(),second=deferred<void>();
    render(<ListenPlayer {...props}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Forward 15 seconds"}));
    await waitFor(()=>expect(AudioFixture.all).toHaveLength(1));
    AudioFixture.current.play.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    fireEvent.click(screen.getByRole("button",{name:"Play"}));
    await waitFor(()=>expect(AudioFixture.current.play).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button",{name:"Play"}));
    await waitFor(()=>expect(AudioFixture.current.play).toHaveBeenCalledTimes(2));
    await act(async()=>second.resolve());
    await screen.findByRole("button",{name:"Pause"});
    const paused=AudioFixture.current.pause.mock.calls.length;
    await act(async()=>first.resolve());
    expect(AudioFixture.current.pause).toHaveBeenCalledTimes(paused);
    expect(screen.getByRole("button",{name:"Pause"})).toBeInTheDocument();
  });
  it("ignores callbacks from a player replaced after deletion",async()=>{
    const progress=vi.fn();render(<ListenPlayer {...props} onAudioPassage={progress}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Play"}));await screen.findByRole("button",{name:"Pause"});
    const old=AudioFixture.current;
    fireEvent.click(screen.getByRole("button",{name:"Listen settings"}));
    fireEvent.click(await screen.findByRole("button",{name:"Delete this chapter’s audio"}));
    await waitFor(()=>expect(chapterAudioStore.removeForJob).toHaveBeenCalledWith(1,1,7));
    expect(audioService.remove).toHaveBeenCalledWith(7);
    progress.mockClear();
    act(()=>{old.currentTime=16;old.ontimeupdate?.();old.onended?.();old.onloadedmetadata?.();old.onerror?.();});
    expect(progress).not.toHaveBeenCalled();
    expect(accountStorage.getItem("nexus-reader-audio-position-1-1")).toBeNull();
  });
  it("blocks new playback and fetches until deletion and cache removal finish",async()=>{
    const deleting=deferred<void>();vi.mocked(audioService.remove).mockReturnValueOnce(deleting.promise);
    render(<ListenPlayer {...props}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Play"}));await screen.findByRole("button",{name:"Pause"});
    const previous=AudioFixture.current;
    fireEvent.click(screen.getByRole("button",{name:"Listen settings"}));
    fireEvent.click(await screen.findByRole("button",{name:"Delete this chapter’s audio"}));
    await waitFor(()=>expect(audioService.remove).toHaveBeenCalledWith(7));
    fireEvent.click(screen.getByRole("button",{name:"Close listen settings"}));
    fireEvent.click(screen.getByRole("button",{name:"Play"}));
    fireEvent.click(screen.getByRole("button",{name:"Forward 15 seconds"}));
    await act(async()=>Promise.resolve());
    expect(audioService.audio).toHaveBeenCalledTimes(1);expect(AudioFixture.all).toHaveLength(1);
    expect(previous.pause).toHaveBeenCalled();
    await act(async()=>deleting.resolve());
    await waitFor(()=>expect(chapterAudioStore.removeForJob).toHaveBeenCalledWith(1,1,7));
    await waitFor(()=>expect(screen.queryByRole("button",{name:"Play"})).not.toBeInTheDocument());
    expect(accountStorage.getItem("nexus-reader-audio-position-1-1")).toBeNull();
  });
  it("invalidates deferred cache writes after closing and directs audio creation to the story",async()=>{
    const view=render(<ListenPlayer {...props} audioCreationHref="/library/1/novel/1/audio"/>);
    fireEvent.click(await screen.findByRole("button",{name:"Play"}));await screen.findByRole("button",{name:"Pause"});
    const shouldWrite=vi.mocked(chapterAudioStore.save).mock.calls[0][4]!;
    expect(shouldWrite()).toBe(true);
    view.rerender(<ListenPlayer {...props} open={false} audioCreationHref="/library/1/novel/1/audio"/>);
    expect(shouldWrite()).toBe(false);
    view.rerender(<ListenPlayer {...props} audioCreationHref="/library/1/novel/1/audio"/>);
    fireEvent.click(screen.getByRole("button",{name:"Listen settings"}));
    expect(screen.getByRole("link",{name:"Manage narrator voices in Settings"})).toHaveAttribute("href","/settings/voices");
    expect(screen.getByRole("link",{name:"Create audio for this story"})).toHaveAttribute("href","/library/1/novel/1/audio");
    expect(screen.queryByText("My narrator voices")).not.toBeInTheDocument();
  });

  it("directs existing provider generation to the complete story audio workspace",async()=>{
    accountStorage.setItem("nexus-reader-tts-execution","server");
    accountStorage.setItem("nexus-reader-tts-preset","custom");
    vi.mocked(audioService.list).mockResolvedValue([]);
    vi.mocked(audioService.create).mockResolvedValue({id:8,status:"queued",provider_id:"custom",provider_model:"custom",provider_voice:"voice",total_parts:1,completed_parts:0,audio_ready:false});
    render(<ListenPlayer {...props} audioCreationHref="/library/1/novels/1?tab=audio"/>);
    expect(await screen.findByRole("link",{name:"Create audio for this story"})).toHaveAttribute("href","/library/1/novels/1?tab=audio");
    expect(screen.queryByRole("button",{name:"Generate chapter audio"})).not.toBeInTheDocument();
    expect(audioService.create).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button",{name:"Listen settings"}));
    expect(screen.getAllByRole("link",{name:"Create audio for this story"}).every(link=>link.getAttribute("href")==="/library/1/novels/1?tab=audio")).toBe(true);
  });
  it("routes cloned narrator creation to the story without offering duplicate chapter generation",async()=>{
    accountStorage.setItem("nexus-reader-tts-preset","qwen3_clone");
    vi.mocked(audioService.list).mockResolvedValue([]);
    render(<ListenPlayer {...props} audioCreationHref="/library/1/novels/1?tab=audio"/>);
    expect(await screen.findByRole("link",{name:"Create audio for this story"})).toHaveAttribute("href","/library/1/novels/1?tab=audio");
    expect(screen.queryByRole("button",{name:"Generate chapter audio"})).not.toBeInTheDocument();
    expect(audioService.create).not.toHaveBeenCalled();
  });

});
