import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, describe, expect, it, vi} from "vitest";
import ListenPlayer from "./ListenPlayer";
import {accountStorage,activateAccountStorage} from "../../services/accountStorage";
import {chapterAudioStore} from "../../services/offlineReaderStore";
import {audioService} from "../../services/audioService";
vi.mock("../../services/audioService",()=>({audioService:{list:vi.fn(),create:vi.fn(),get:vi.fn()}}));
vi.mock("../../services/offlineReaderStore",()=>{
  const store={get:vi.fn()};
  return {chapterAudioStore:{...store,recording:vi.fn(async()=>{const audio=await store.get();return audio?{audio,manifest:null}:null;})},chapterAudioJobStore:{get:vi.fn().mockResolvedValue(null)}};
});
vi.mock("../../services/voiceService",()=>({voiceService:{list:vi.fn().mockResolvedValue([]),capabilities:vi.fn().mockResolvedValue({configured:false,languages:[]})}}));
const chapter=(n:number)=>({id:n,chapter_number:n,title:`Chapter ${n}`,content:"Story words."});
class AudioFixture {
  static all:AudioFixture[]=[];
  static nextPlay:Promise<void>|null=null;
  constructor(){AudioFixture.all.push(this); if (AudioFixture.nextPlay) this.play.mockReturnValue(AudioFixture.nextPlay);}
  src="";preload="";playbackRate=1;currentTime=0;duration=20;
  play=vi.fn().mockResolvedValue(undefined);pause=vi.fn();
  onended:(()=>void)|null=null;onloadedmetadata:(()=>void)|null=null;ontimeupdate:(()=>void)|null=null;onerror:(()=>void)|null=null;
}
describe("continuous listening",()=>{
  beforeEach(()=>{vi.clearAllMocks();localStorage.clear();activateAccountStorage(1);AudioFixture.all=[];AudioFixture.nextPlay=null;
    accountStorage.setItem("nexus-reader-tts-engine","openai_compatible");accountStorage.setItem("nexus-reader-audio-continuous","true");
    vi.mocked(audioService.list).mockResolvedValue([]);vi.mocked(chapterAudioStore.get).mockResolvedValue(new Blob(["audio"]));
    vi.stubGlobal("Audio",AudioFixture);vi.stubGlobal("URL",{createObjectURL:vi.fn(()=>"blob:audio"),revokeObjectURL:vi.fn()});
  });
  afterEach(()=>{cleanup();vi.useRealTimers();vi.unstubAllGlobals();});
  const props={chapter:chapter(1),libraryId:1,novelId:1,open:true,onClose:vi.fn(),nextChapterNumber:2};
  async function start(){fireEvent.click(await screen.findByRole("button",{name:"Play"}));await screen.findByRole("button",{name:"Pause"});}
  it("plays the next ready chapter once and stops at the end of the story",async()=>{
    const next=vi.fn();const view=render(<ListenPlayer {...props} onNextChapter={next}/>);await start();
    act(()=>AudioFixture.all[0].onended?.());expect(next).toHaveBeenCalledOnce();
    view.rerender(<ListenPlayer {...props} chapter={chapter(2)} nextChapterNumber={undefined} onNextChapter={next}/>);
    await waitFor(()=>expect(AudioFixture.all).toHaveLength(2));await screen.findByRole("button",{name:"Pause"});
    expect(AudioFixture.all[1].play).toHaveBeenCalledOnce();act(()=>AudioFixture.all[1].onended?.());
    expect(next).toHaveBeenCalledOnce();expect(screen.getByRole("button",{name:"Play"})).toBeInTheDocument();
  });
  it("pauses for missing audio without starting generation",async()=>{
    const next=vi.fn();const view=render(<ListenPlayer {...props} onNextChapter={next}/>);await start();
    act(()=>AudioFixture.all[0].onended?.());vi.mocked(chapterAudioStore.get).mockResolvedValue(null);
    view.rerender(<ListenPlayer {...props} chapter={chapter(2)} nextChapterNumber={3} onNextChapter={next}/>);
    expect(await screen.findByRole("alert")).toHaveTextContent("next chapter needs audio");expect(audioService.create).not.toHaveBeenCalled();
  });
  it("does not advance after an explicit pause or closing the player",async()=>{
    const next=vi.fn();const view=render(<ListenPlayer {...props} onNextChapter={next}/>);await start();
    fireEvent.click(screen.getByRole("button",{name:"Pause"}));act(()=>AudioFixture.all[0].onended?.());expect(next).not.toHaveBeenCalled();
    await start();view.rerender(<ListenPlayer {...props} open={false} onNextChapter={next}/>);
    act(()=>AudioFixture.all[0].onended?.());expect(next).not.toHaveBeenCalled();expect(AudioFixture.all[0].pause).toHaveBeenCalled();
  });
  it("does not revive an intent after manual navigation away and back",async()=>{
    const next=vi.fn();const view=render(<ListenPlayer {...props} navigationKey="one" onNextChapter={next}/>);await start();
    act(()=>AudioFixture.all[0].onended?.());
    view.rerender(<ListenPlayer {...props} requestedChapterNumber={3} chapterReady={false} navigationKey="manual-three" onNextChapter={next}/>);
    view.rerender(<ListenPlayer {...props} chapter={chapter(2)} navigationKey="manual-two" onNextChapter={next}/>);
    await screen.findByRole("button",{name:"Play"});expect(AudioFixture.all).toHaveLength(1);
  });
  it("a late play result cannot start after switching accounts",async()=>{
    let finish!:()=>void;
    const pending=new Promise<void>(resolve=>{finish=resolve;});
    const next=vi.fn();AudioFixture.nextPlay=pending;render(<ListenPlayer {...props} onNextChapter={next}/>);
    fireEvent.click(await screen.findByRole("button",{name:"Play"}));
    await waitFor(()=>expect(AudioFixture.all).toHaveLength(1));AudioFixture.all[0].pause.mockClear();
    // The account generation also protects callbacks from an already loaded player.
    activateAccountStorage(2);await act(async()=>finish());
    act(()=>AudioFixture.all[0].onended?.());expect(next).not.toHaveBeenCalled();expect(AudioFixture.all[0].pause).toHaveBeenCalled();
  });
  it("keeps the original sleep deadline across chapter boundaries",async()=>{
    vi.useFakeTimers();accountStorage.setItem("nexus-reader-audio-sleep-minutes","15");
    const next=vi.fn();let view!:ReturnType<typeof render>;
    await act(async()=>{view=render(<ListenPlayer {...props} onNextChapter={next}/>);});
    await act(async()=>{fireEvent.click(screen.getByRole("button",{name:"Play"}));});
    act(()=>vi.advanceTimersByTime(899_000));act(()=>AudioFixture.all[0].onended?.());
    await act(async()=>view.rerender(<ListenPlayer {...props} chapter={chapter(2)} nextChapterNumber={3} onNextChapter={next}/>));
    expect(AudioFixture.all).toHaveLength(2);expect(screen.getByRole("button",{name:"Pause"})).toBeInTheDocument();
    act(()=>vi.advanceTimersByTime(1_001));expect(AudioFixture.all[1].pause).toHaveBeenCalled();
    expect(screen.getByRole("button",{name:"Play"})).toBeInTheDocument();act(()=>AudioFixture.all[1].onended?.());expect(next).toHaveBeenCalledOnce();
  });
  it("browser speech still completes after pausing and resuming from device controls",async()=>{
    accountStorage.setItem("nexus-reader-tts-engine","native");
    const handlers=new Map<string,()=>void>();
    vi.stubGlobal("navigator",{mediaSession:{setActionHandler:(key:string,value:()=>void)=>handlers.set(key,value)}});
    let utterance!:{onend:()=>void};
    vi.stubGlobal("SpeechSynthesisUtterance",class {constructor(){utterance=this as unknown as typeof utterance;}});
    const speech={speaking:false,pending:false,paused:false,getVoices:()=>[],addEventListener:vi.fn(),removeEventListener:vi.fn(),cancel:vi.fn(),speak:vi.fn(),pause:vi.fn(()=>{speech.paused=true;}),resume:vi.fn(()=>{speech.paused=false;})};
    vi.stubGlobal("speechSynthesis",speech);
    const next=vi.fn();render(<ListenPlayer {...props} onNextChapter={next}/>);
    fireEvent.click(screen.getByRole("button",{name:"Read aloud"}));
    act(()=>handlers.get("pause")?.());act(()=>handlers.get("play")?.());
    expect(speech.resume).toHaveBeenCalledOnce();act(()=>utterance.onend());expect(next).toHaveBeenCalledOnce();
  });

  it("continues with ready offline audio while the server lookup is stalled",async()=>{
    const next=vi.fn();const view=render(<ListenPlayer {...props} onNextChapter={next}/>);await start();
    act(()=>AudioFixture.all[0].onended?.());vi.mocked(audioService.list).mockReturnValue(new Promise(()=>undefined));
    view.rerender(<ListenPlayer {...props} chapter={chapter(2)} onNextChapter={next}/>);
    await waitFor(()=>expect(AudioFixture.all).toHaveLength(2));expect(AudioFixture.all[1].play).toHaveBeenCalledOnce();
  });

});
