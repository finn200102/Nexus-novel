import { chapterIdentity, type ChapterIdentity } from "./chapterIdentity";
import {quoteLocator,type ChapterDocument,type TextLocator} from "../components/reader/chapterDocument";
export type AudioPassage = {block_id:string|null;text_offset:number|null;text_length:number|null};
export type AudioSegment = AudioPassage & {part_index:number;start_seconds:number;end_seconds:number};
export type AudioManifest = Partial<ChapterIdentity> & {job_id?:number;source_version:string|null;rendition:"original";include_author_notes:boolean|null;precision:"segment"|"unavailable";current_source?:boolean;pronunciation_version?:string|null;duration_seconds:number|null;segments:AudioSegment[]};

export const MAX_AUDIO_SPOKEN_UTF16=2_000_000;
export const MAX_AUDIO_PARTS=10_000;
export class AudioPlanningLimitError extends Error {
  constructor(){super("This chapter exceeds the narration limit (2,000,000 spoken characters or 10,000 parts). Shorten or disable pronunciation entries, or split the chapter before trying again.");this.name="AudioPlanningLimitError";}
}

export function planAudioPassages(document:ChapterDocument,title:string,maximum:number,includeNotes=false) {
  const result:{text:string;passage:AudioPassage}[]=[];
  let spokenSize=0;
  const add=(text:string,blockId:string|null)=>{
    let start=0;
    while(start<text.length){
      while(start<text.length && /\s/.test(text[start]))start++;
      if(start>=text.length)break;
      let end=Math.min(text.length,start+maximum);
      if(end<text.length){
        const cut=Math.max(text.lastIndexOf(" ",end-1),text.lastIndexOf("\n",end-1));
        if(cut>start+maximum/2)end=cut;
        if(/[\uD800-\uDBFF]/.test(text[end-1]))end--;
      }
      while(end>start && /\s/.test(text[end-1]))end--;
      if(end<=start)break;
      const spoken=text.slice(start,end).replace(/\s+/g," ");spokenSize+=spoken.length;
      if(result.length>=MAX_AUDIO_PARTS || spokenSize>MAX_AUDIO_SPOKEN_UTF16)throw new AudioPlanningLimitError();
      result.push({text:spoken,passage:{block_id:blockId,text_offset:blockId?start:null,text_length:blockId?end-start:null}});
      start=end;
    }
  };
  add(title,null);
  for(const block of document.blocks){if(block.role!=="author_note" || includeNotes)add(block.text,block.id);}
  return result;
}

export function measuredManifest(sourceVersion:string,passages:AudioPassage[],durations:number[],includeNotes=false,pronunciationVersion:string|null=null,identity?:ChapterIdentity):AudioManifest|null {
  if(!passages.length || passages.length!==durations.length || durations.some(d=>!Number.isFinite(d)||d<=0))return null;
  let end=0;
  return {...identity,source_version:sourceVersion,rendition:"original",include_author_notes:includeNotes,pronunciation_version:pronunciationVersion,precision:"segment",duration_seconds:durations.reduce((a,b)=>a+b,0),segments:passages.map((p,i)=>{const start=end;end+=durations[i];return {...p,part_index:i,start_seconds:start,end_seconds:end};})};
}

export function alignedTo(manifest:AudioManifest|null|undefined,document:ChapterDocument|undefined,rendition="original",identity?:ChapterIdentity) {
  if(identity && (manifest?.chapter_key!==identity.chapter_key || manifest?.manifest_epoch!==identity.manifest_epoch))return false;
  if(!manifest || !document || rendition!=="original" || manifest.rendition!=="original" || manifest.precision!=="segment" || manifest.source_version!==document.content_version || !manifest.segments.length || manifest.duration_seconds===null || !Number.isFinite(manifest.duration_seconds) || manifest.duration_seconds<=0)return false;
  let previous=0;
  for(const s of manifest.segments){
    if(!Number.isFinite(s.start_seconds)||!Number.isFinite(s.end_seconds)||Math.abs(s.start_seconds-previous)>0.000001||s.end_seconds<=s.start_seconds)return false;
    if(s.block_id){const block=document.blocks.find(b=>b.id===s.block_id);if(!block || !Number.isInteger(s.text_offset)||!Number.isInteger(s.text_length)||s.text_offset!<0||s.text_length!<=0||s.text_offset!+s.text_length!>block.text.length)return false;}
    previous=s.end_seconds;
  }
  return Math.abs(previous-manifest.duration_seconds)<=0.000001;
}

export function audioLocator(manifest:AudioManifest|null|undefined,document:ChapterDocument|undefined,seconds:number,rendition="original",identity?:ChapterIdentity):TextLocator|undefined {
  if(!alignedTo(manifest,document,rendition,identity)||!Number.isFinite(seconds)||seconds<0)return;
  const segment=manifest!.segments.find(s=>seconds>=s.start_seconds && seconds<s.end_seconds);
  if(!segment?.block_id)return;
  const index=document!.blocks.findIndex(b=>b.id===segment.block_id);
  return quoteLocator(document!.blocks,index,segment.text_offset || 0);
}

export function audioTime(manifest:AudioManifest|null|undefined,document:ChapterDocument|undefined,locator:TextLocator|undefined,rendition="original",identity?:ChapterIdentity):number|undefined {
  if(!alignedTo(manifest,document,rendition,identity)||!locator?.blockId)return;
  const parts=manifest!.segments.filter(s=>s.block_id===locator.blockId);
  if(!parts.length)return;
  return [...parts].reverse().find(s=>(s.text_offset || 0)<=(locator.textOffset || 0))?.start_seconds ?? parts[0].start_seconds;
}

/** Keep nullable legacy wire identity out of the validated local cache type. */
export function audioManifestFromWire(value:import('../generated/api').AudioManifestResponse):AudioManifest {
 const {chapter_key:_key,manifest_epoch:_epoch,manifest_revision:_revision,...extra}=value;void _key;void _epoch;void _revision;
 return {...extra,...(chapterIdentity(value)??{}),source_version:value.source_version??null,include_author_notes:value.include_author_notes??null,duration_seconds:value.duration_seconds??null,segments:value.segments.map(segment=>({...segment,block_id:segment.block_id??null,text_offset:segment.text_offset??null,text_length:segment.text_length??null}))};
}
