import { chapterIdentity, assertCurrentChapterIdentity, CHAPTER_MANIFEST_CHANGED, type ChapterIdentity } from "./chapterIdentity";
import type { ReaderChapterContent } from "./chapterContracts";
import { accountDatabaseName, activeStorageAccount, onAccountStorageChange, storageGeneration } from "./accountStorage";
import { chapterService } from "./chapterService";
import { randomAudioToken, offlineReaderStore, browserAudioLeaseStore, chapterAudioJobStore, chapterAudioStore, type BrowserAudioLease, type ChapterAudioJob, type ChapterAudioProviderSnapshot } from "./offlineReaderStore";
import { mergeAudioSegments, ttsService, type OpenAICompatibleTtsConfig, type TtsProviderPresetId } from "./ttsService";
import { alignedTo, measuredManifest } from "./audioAlignment";
import {planPronouncedPassages,normalizePronunciationRules,type PronunciationSnapshot} from "./pronunciationService";
import type { ChapterDocument } from "../components/reader/chapterDocument";

export type BrowserAudioBatchInput = {
  novelId: number; libraryId: number; chapterNumbers: number[];
  chapterIdentities?: Record<number, ChapterIdentity>; sourceVersions?: Record<number,string>;
  provider: OpenAICompatibleTtsConfig; pronunciation?:PronunciationSnapshot; includeAuthorNotes?: boolean; presetId?: TtsProviderPresetId;
};
export type BrowserAudioRow = {
  novelId: number; libraryId: number; chapterNumber: number; chapterIdentity?:ChapterIdentity;
  status: ChapterAudioJob["status"]; totalParts: number; completedParts: number;
  error?: string; sourceVersion?: string;
};
export type BrowserAudioSnapshot = { generation: number; running: boolean; rows: readonly BrowserAudioRow[] };
type Work = { identity:ChapterIdentity; queueKey:string; chapterContent?:ReaderChapterContent; input: BrowserAudioBatchInput; chapterNumber: number; generation: number; controller: AbortController; cancelled: boolean; done:Promise<void>; finish:()=>void; lease?:BrowserAudioLease; leaseLost?:boolean };
const key = (novelId:number,identity:ChapterIdentity) => `${novelId}:${identity.chapter_key}`;
const abortError = () => new DOMException("Browser audio preparation was paused.", "AbortError");

/** Abort promptly even when a mocked/provider promise ignores its AbortSignal. */
function abortable<T>(promise:Promise<T>, signal:AbortSignal):Promise<T> {
  return new Promise((resolve,reject)=>{
    const abort=()=>reject(abortError());
    signal.addEventListener("abort",abort,{once:true});
    if(signal.aborted)abort();
    promise.then(resolve,reject).finally(()=>signal.removeEventListener("abort",abort));
  });
}
const providerSnapshot = (provider:OpenAICompatibleTtsConfig):ChapterAudioProviderSnapshot => ({
  base_url:provider.baseUrl,model:provider.model,voice:provider.voice,language_code:provider.languageCode,
});
function sameProvider(left:ChapterAudioProviderSnapshot|undefined,right:ChapterAudioProviderSnapshot) {
  return Boolean(left && left.base_url===right.base_url && left.model===right.model && left.voice===right.voice && (left.language_code || "")===(right.language_code || ""));
}

export const BROWSER_AUDIO_LEASE_TTL=120_000;
export const BROWSER_AUDIO_HEARTBEAT_INTERVAL=20_000;
async function withChapterLock<T>(novelId:number,chapterNumber:number,work:(lease:BrowserAudioLease)=>Promise<T>,lost:()=>void=()=>undefined,identity:ChapterIdentity):Promise<T> {
  const generation=storageGeneration(),databaseName=accountDatabaseName();
  const name=`${databaseName}:audio:${novelId}:${identity.chapter_key}`;
  const busy=()=>new Error("This chapter is being prepared or removed in another browser tab. Wait for it to finish, then retry.");
  const run=async()=>{
    if(generation!==storageGeneration() || databaseName!==accountDatabaseName())throw abortError();
    const lease=await browserAudioLeaseStore.claim(novelId,chapterNumber,randomAudioToken(),BROWSER_AUDIO_LEASE_TTL,identity);
    if(!lease)throw busy();
    let renewing=false,stopped=false;
    const heartbeat=window.setInterval(()=>{
      if(renewing || stopped)return;
      renewing=true;
      void browserAudioLeaseStore.renew(lease,BROWSER_AUDIO_LEASE_TTL).then(ok=>{if(!ok && !stopped)lost();}).catch(()=>{if(!stopped)lost();}).finally(()=>{renewing=false;});
    },BROWSER_AUDIO_HEARTBEAT_INTERVAL);
    try{return await work(lease);}
    finally{stopped=true;window.clearInterval(heartbeat);await browserAudioLeaseStore.release(lease).catch(()=>undefined);}
  };
  // Web Locks avoids redundant claims where available. IndexedDB ownership is
  // always authoritative, including ordinary household LAN HTTP connections.
  if(typeof navigator!=="undefined" && navigator.locks?.request){
    return navigator.locks.request(name,{mode:"exclusive",ifAvailable:true},async lock=>{if(!lock)throw busy();return run();});
  }
  return run();
}

/** Explicitly started, account-scoped work that survives a story tab unmount.
 * The page/browser must remain open. Credentials live only in pending work;
 * they are never included in snapshots, persisted jobs or backend requests.
 */
export class BrowserAudioQueue {
  private generation=storageGeneration();
  private rows=new Map<string,BrowserAudioRow>();
  private work=new Map<string,Work>();
  private pending:Work[]=[];
  private removing=new Map<string,symbol>();
  private listeners=new Set<()=>void>();
  private drainingGeneration:number|null=null;
  private snapshot:BrowserAudioSnapshot={generation:this.generation,running:false,rows:[]};
  private unsubscribe=onAccountStorageChange(()=>this.accountChanged());
  private manifestChanged=(event:Event)=>{
    const detail=(event as CustomEvent).detail;
    for(const item of this.work.values())if(item.input.novelId===detail?.novelId && (item.identity.manifest_epoch!==detail.manifest_epoch || item.identity.manifest_revision!==detail.manifest_revision)){
      item.cancelled=true;item.controller.abort();item.input.provider.apiKey="";
      const row=this.rows.get(item.queueKey);if(row)this.rows.set(item.queueKey,{...row,status:"failed",error:"The chapter list changed. Review the current story before retrying."});
    }
    this.publish();
  };
  constructor(){window.addEventListener(CHAPTER_MANIFEST_CHANGED,this.manifestChanged);}

  subscribe=(listener:()=>void)=>{this.listeners.add(listener);return ()=>{this.listeners.delete(listener);};};
  getSnapshot=()=>this.snapshot;
  private owned=(item:Work)=>item.generation===storageGeneration() && this.work.get(item.queueKey)===item;
  private active=(item:Work)=>this.owned(item) && !item.cancelled && !item.leaseLost;
  private publish(){
    this.snapshot={generation:this.generation,running:[...this.rows.values()].some(row=>row.status==="queued" || row.status==="generating"),rows:[...this.rows.values()].map(row=>({...row}))};
    for(const listener of this.listeners)listener();
  }
  private accountChanged(){
    for(const item of this.work.values()){item.cancelled=true;item.controller.abort();item.input.provider.apiKey="";item.finish();}
    this.generation=storageGeneration();this.rows.clear();this.work.clear();this.removing.clear();this.pending=[];this.drainingGeneration=null;this.publish();
  }
  dispose(){window.removeEventListener(CHAPTER_MANIFEST_CHANGED,this.manifestChanged);this.unsubscribe();this.accountChanged();this.listeners.clear();}

  enqueue=(input:BrowserAudioBatchInput):number=>{
    if(activeStorageAccount()===null)throw new Error("Sign in before preparing browser audio.");
    if(!Number.isSafeInteger(input.novelId)||input.novelId<1||!Number.isSafeInteger(input.libraryId)||input.libraryId<1)throw new Error("Choose a valid story.");
    if(!input.chapterNumbers.length || input.chapterNumbers.length>200 || input.chapterNumbers.some(number=>!Number.isSafeInteger(number)||number< -2147483648 || number>2147483647))throw new Error("Select between 1 and 200 chapters.");
    const provider={...input.provider,baseUrl:input.provider.baseUrl.trim().replace(/\/+$/, ""),model:input.provider.model.trim(),voice:input.provider.voice.trim()};
    let url:URL;try{url=new URL(provider.baseUrl);}catch{throw new Error("Enter a valid speech provider URL.");}
    if(!["http:","https:"].includes(url.protocol)||url.username||url.password||url.search||url.hash||!provider.model||!provider.voice)throw new Error("Use an HTTP speech provider URL without embedded credentials, and choose its model and voice.");
    const pronunciation={version:input.pronunciation?.version || null,rules:normalizePronunciationRules(input.pronunciation?.rules || [])};
    if(Boolean(pronunciation.rules.length)!==Boolean(pronunciation.version))throw new Error("Save the pronunciation rules before preparing narration.");
    const numbers=[...new Set(input.chapterNumbers)];
    if(numbers.some(number=>!chapterIdentity(input.chapterIdentities?.[number])))throw new Error("Reload the chapter list to verify its identities before preparing audio.");
    const identityFor=(number:number)=>input.chapterIdentities![number];
    if(numbers.some(number=>this.removing.has(key(input.novelId,identityFor(number)))))throw new Error("Wait for the browser recording to finish being removed before preparing it again.");
    const additions=numbers.filter(number=>{const item=this.work.get(key(input.novelId,identityFor(number)));return !item || item.cancelled;});
    if([...this.work.values()].filter(item=>!item.cancelled).length+additions.length>200)throw new Error("At most 200 chapters can be waiting or preparing in this browser.");
    for(const number of additions){
      let finish=()=>undefined as void;
      const done=new Promise<void>(resolve=>{finish=resolve;});
      const identity={...identityFor(number)},queueKey=key(input.novelId,identity);
      const item:Work={identity,queueKey,done,finish,input:{...input,pronunciation:{...pronunciation,rules:pronunciation.rules.map(rule=>({...rule}))},chapterNumbers:[number],provider:{...provider}},chapterNumber:number,generation:this.generation,controller:new AbortController(),cancelled:false};
      this.work.set(key(input.novelId,identityFor(number)),item);this.pending.push(item);
      this.rows.set(key(input.novelId,identityFor(number)),{novelId:input.novelId,libraryId:input.libraryId,chapterNumber:number,chapterIdentity:identity,status:"queued",completedParts:0,totalParts:0});
    }
    this.publish();void this.drain();return additions.length;
  };
  retry=(input:BrowserAudioBatchInput)=>this.enqueue(input);
  cancel=(novelId:number,chapterNumber?:number)=>{
    for(const item of this.work.values()){
      if(item.input.novelId!==novelId || chapterNumber!==undefined && item.chapterNumber!==chapterNumber)continue;
      item.cancelled=true;item.controller.abort();item.input.provider.apiKey="";
      if(this.pending.includes(item)){
        this.pending=this.pending.filter(waiting=>waiting!==item);
        this.work.delete(item.queueKey);item.finish();
      }
      const row=this.rows.get(item.queueKey);
      if(row)this.rows.set(item.queueKey,{...row,status:"cancelled",error:"Preparation paused. Select Retry to keep completed parts."});
    }
    this.publish();
  };

  remove=async(novelId:number,chapterNumber:number):Promise<void>=>{
    const row=[...this.rows.values()].find(value=>value.novelId===novelId && value.chapterNumber===chapterNumber);
    const identity=row?.chapterIdentity;if(!identity)throw new Error("Reload this chapter’s local audio before removing it.");
    const rowKey=key(novelId,identity),generation=storageGeneration();
    if(this.removing.has(rowKey))throw new Error("This browser recording is already being removed.");
    const token=Symbol("remove-browser-recording");this.removing.set(rowKey,token);
    const current=()=>generation===storageGeneration() && this.removing.get(rowKey)===token;
    try {
      const item=this.work.get(rowKey);
      if(item){
        this.cancel(novelId,chapterNumber);
        await item.done;
      }
      if(!current())throw abortError();
      await withChapterLock(novelId,chapterNumber,async lease=>{
        if(!current())throw abortError();
        await chapterAudioJobStore.remove(novelId,chapterNumber,current,lease);
        await chapterAudioStore.removeBrowser(novelId,chapterNumber,current,lease);
      },()=>undefined,identity);
      if(!current())throw abortError();
      this.rows.delete(rowKey);this.publish();
    } finally {
      if(this.removing.get(rowKey)===token)this.removing.delete(rowKey);
    }
  };

  hydrate=async(novelId:number,libraryId:number,chapterNumbers:number[])=>{
    const generation=storageGeneration();
    for(const number of [...new Set(chapterNumbers)].slice(0,200)){
      const job=await chapterAudioJobStore.get(novelId,number);
      if(generation!==storageGeneration())return;
      const identity=chapterIdentity(job);if(!identity || !job)continue;
      const rowKey=key(novelId,identity),originalRow=this.rows.get(rowKey);
      if(this.work.has(rowKey))continue;
      let status=job.status,error=job.error;
      if(status==="generating" || status==="queued"){status="cancelled";error="This browser job is paused. Select Retry to continue completed parts.";}
      if(status==="ready"){
        const recording=await chapterAudioStore.recording(novelId,number),audio=recording?.audio,manifest=recording?.manifest;
        if(manifest?.job_id!==undefined){status="failed";error="This device currently caches server audio for this chapter. Remove the browser job before preparing another recording.";}
        else if(!audio || manifest?.source_version!==job.source_version || (manifest?.pronunciation_version || null)!==(job.pronunciation_version || null)){status="failed";error="This browser no longer has a verified recording. Select Retry to prepare it again.";}
      }
      if(generation!==storageGeneration())return;
      if(this.work.has(rowKey) || this.rows.get(rowKey)!==originalRow)continue;
      this.rows.set(rowKey,{novelId,libraryId,chapterNumber:number,chapterIdentity:identity,status,totalParts:job.chunks.length,completedParts:job.completed_chunks,error,sourceVersion:job.source_version});
    }
    if(generation===storageGeneration())this.publish();
  };

  private async drain(){
    const generation=this.generation;
    if(this.drainingGeneration===generation)return;
    this.drainingGeneration=generation;
    try {
      while(generation===storageGeneration()){
        const item=this.pending.shift();if(!item)break;
        if(!this.active(item)){
          item.input.provider.apiKey="";item.finish();
          if(this.work.get(item.queueKey)===item)this.work.delete(item.queueKey);
          continue;
        }
        try {
          const content=await abortable(chapterService.getChapterContentByNumber(item.chapterNumber,item.input.libraryId,item.input.novelId,item.identity),item.controller.signal);
          if(!this.active(item))throw abortError();
          if(chapterIdentity(content)?.chapter_key!==item.identity.chapter_key || item.input.sourceVersions?.[item.chapterNumber] && content.document?.content_version!==item.input.sourceVersions[item.chapterNumber])throw new Error("The selected chapter changed. Review the current chapter before preparing audio.");
          await offlineReaderStore.save(content);
          item.chapterContent=content;
          await withChapterLock(item.input.novelId,item.chapterNumber,lease=>{item.lease=lease;return this.prepare(item);},()=>{item.leaseLost=true;item.controller.abort();},item.identity);
        } catch(error){
          if(this.owned(item)){
            const row=this.rows.get(item.queueKey);
            if(row)this.rows.set(item.queueKey,{...row,status:"failed",error:error instanceof Error?error.message:"Browser narration could not start."});
            this.publish();
          }
        } finally {
          item.input.provider.apiKey="";item.finish();
          if(this.work.get(item.queueKey)===item)this.work.delete(item.queueKey);
        }
      }
    } finally {if(this.drainingGeneration===generation)this.drainingGeneration=null;}
  }
  private async prepare(item:Work){
    const {novelId,libraryId,provider}=item.input,number=item.chapterNumber,rowKey=item.queueKey;
    const active=()=>this.active(item),owned=()=>this.owned(item);
    let job:ChapterAudioJob|null=null;
    const update=(status:ChapterAudioJob["status"],error?:string)=>{
      if(!owned())return;
      this.rows.set(rowKey,{novelId,libraryId,chapterNumber:number,chapterIdentity:item.identity,status,totalParts:job?.chunks.length || 0,completedParts:job?.completed_chunks || 0,error,sourceVersion:job?.source_version});this.publish();
    };
    try {
      if(!active())return;
      update("generating");
      const chapter=item.chapterContent;
      if(!chapter)throw new Error("The selected chapter could not be verified.");
      assertCurrentChapterIdentity(novelId,item.identity);
      if(!active())throw abortError();
      const document=chapter.document as ChapterDocument|undefined;
      if(!document?.content_version || !document.blocks?.length || !document.plain_text?.trim())throw new Error("Download this chapter's text before preparing its audio.");
      const [existing,recording]=await Promise.all([chapterAudioJobStore.get(novelId,number),chapterAudioStore.recording(novelId,number)]);
      const cached=recording?.audio,manifest=recording?.manifest;
      if(!active())throw abortError();
      if(manifest?.job_id!==undefined)throw new Error("This browser already stores server audio for this chapter. Remove that recording before preparing browser audio.");
      const snapshot=providerSnapshot(provider),includeNotes=Boolean(item.input.includeAuthorNotes),pronunciation=item.input.pronunciation || {version:null,rules:[]};
      if(existing && (!sameProvider(existing.provider,snapshot)||existing.source_version!==document.content_version||Boolean(existing.include_author_notes)!==includeNotes||(existing.pronunciation_version || null)!==pronunciation.version||JSON.stringify(existing.pronunciation_rules || [])!==JSON.stringify(pronunciation.rules)||!existing.alignment_plan))throw new Error("Existing browser audio uses another text version, voice, pronunciation, or author-note setting. Remove it before creating a different recording.");
      if(cached){
        if(!existing || existing.completed_chunks!==existing.chunks.length || !alignedTo(manifest,document) || manifest?.include_author_notes!==includeNotes||(manifest?.pronunciation_version || null)!==pronunciation.version)throw new Error("An existing browser recording could not be verified. Remove it before creating another.");
        job={...existing,status:"ready",error:undefined};await chapterAudioJobStore.save(job,active,item.lease);update("ready");return;
      }
      const maximum=item.input.presetId==="spark_tts_mlx"?380:item.input.presetId==="qwen3_mlx_4bit"?350:item.input.presetId==="kokoro_mps"?1100:900;
      const plan=planPronouncedPassages(document,chapter.title || "",maximum,includeNotes,pronunciation.rules);
      if(!plan.length)throw new Error("This chapter has no text to narrate.");
      job=existing ? {...existing,chunks:[...existing.chunks],provider:snapshot} : {...item.identity,cache_key:rowKey,novel_id:novelId,chapter_number:number,chunks:plan.map(part=>part.text),alignment_plan:plan.map(part=>part.passage),source_version:document.content_version,include_author_notes:includeNotes,pronunciation_version:pronunciation.version,pronunciation_rules:pronunciation.rules,provider:snapshot,status:"queued",completed_chunks:0,created_at:Date.now(),updated_at:Date.now()};
      // A completed job whose final recording was evicted has no retained
      // segments. Explicit Retry starts that same snapshot from the beginning.
      if(job.status==="ready"){await chapterAudioJobStore.clearSegments(novelId,number,active,item.lease);job.completed_chunks=0;}
      const prior=await chapterAudioJobStore.segments(novelId,number);
      if(!active())throw abortError();
      if(!Number.isInteger(job.completed_chunks)||job.completed_chunks<0||job.completed_chunks>job.chunks.length||prior.length<job.completed_chunks||prior.length>job.chunks.length)throw new Error("Completed audio parts are missing or inconsistent. Remove this browser recording before starting again.");
      job.status="generating";job.error=undefined;
      await chapterAudioJobStore.save(job,active,item.lease);update("generating");
      for(let index=job.completed_chunks;index<job.chunks.length;index++){
        const audio=await abortable(ttsService.synthesize(job.chunks[index],provider,item.controller.signal),item.controller.signal);
        if(!active())throw abortError();
        await chapterAudioJobStore.saveSegment(novelId,number,index,audio,active,item.lease);
        if(!active())throw abortError();
        job.completed_chunks=index+1;await chapterAudioJobStore.save(job,active,item.lease);update("generating");
      }
      const segments=await chapterAudioJobStore.segments(novelId,number);
      if(!active())throw abortError();
      if(segments.length!==job.chunks.length)throw new Error("Some completed audio parts are missing. Retry after checking browser storage.");
      let durations:number[]=[];
      const merged=await abortable(mergeAudioSegments(segments,values=>{durations=values;}),item.controller.signal);
      if(!active())throw abortError();
      const alignment=measuredManifest(job.source_version!,job.alignment_plan!,durations,includeNotes,job.pronunciation_version || null,item.identity);
      if(!alignment)throw new Error("The audio provider did not supply decodable passage timings. Completed parts were kept for retry.");
      await chapterAudioStore.saveBrowser(novelId,number,merged,alignment,active,item.lease);
      if(!active())throw abortError();
      job.status="ready";await chapterAudioJobStore.save(job,active,item.lease);
      await chapterAudioJobStore.clearSegments(novelId,number,active,item.lease);update("ready");
    } catch(error){
      if(!owned())return;
      const cancelled=!item.leaseLost && (item.cancelled || error instanceof DOMException && error.name==="AbortError");
      const message=item.leaseLost?"Another tab now owns this chapter’s audio. Completed parts were preserved; retry after it finishes.":cancelled?"Preparation paused. Select Retry to keep completed parts.":error instanceof Error?error.message:"Browser audio preparation failed. Select Retry to continue.";
      if(job){job.status=cancelled?"cancelled":"failed";job.error=message;try{await chapterAudioJobStore.save(job,owned,item.lease);}catch{/* Preserve earlier committed progress if storage has become unavailable. */}}
      update(cancelled?"cancelled":"failed",message);
    }
  }
}

export const browserAudioQueue=new BrowserAudioQueue();
