import apiClient from "./apiClient";
import {planAudioPassages,MAX_AUDIO_SPOKEN_UTF16,MAX_AUDIO_PARTS,AudioPlanningLimitError,type AudioPassage} from "./audioAlignment";
import type {ChapterDocument} from "../components/reader/chapterDocument";

export type PronunciationRule={source:string;spoken:string};
export type PronunciationSnapshot={version:string|null;rules:PronunciationRule[]};
export type PronunciationProfile={scope:string;revision:number;rules:PronunciationRule[];account_rules:PronunciationRule[];inherit_account:boolean;effective_rules:PronunciationRule[];effective_version:string|null};
export type PronunciationWrite={expected_revision:number;operation_id:string;rules:PronunciationRule[];inherit_account?:boolean};
export const pronunciationService={
  async get(novelId?:number):Promise<PronunciationProfile>{return(await apiClient.get(`/audio/pronunciation${novelId===undefined?"":`/stories/${novelId}`}`)).data;},
  async save(input:PronunciationWrite,novelId?:number):Promise<PronunciationProfile>{return(await apiClient.put(`/audio/pronunciation${novelId===undefined?"":`/stories/${novelId}`}`,input)).data;},
};
export function normalizePronunciationRules(rules:PronunciationRule[],maximum=128):PronunciationRule[]{
  if(rules.length>maximum)throw new Error(`Use at most ${maximum} pronunciation rules.`);
  const seen=new Set<string>();
  return rules.map(rule=>{
    const source=rule.source.trim(),spoken=rule.spoken.trim();
    if(!source||!spoken||Array.from(source).length>80||Array.from(spoken).length>160||/[\p{Cc}\p{Cs}\p{Cf}<>]/u.test(source+spoken))throw new Error("Use plain pronunciation text without markup or control characters (source up to 80 characters, spoken up to 160).");
    if(seen.has(source))throw new Error("Each exact source term may appear only once.");seen.add(source);return{source,spoken};
  });
}
function matcher(rules:PronunciationRule[]){return rules.length?new RegExp([...rules].sort((a,b)=>Array.from(b.source).length-Array.from(a.source).length).map(rule=>rule.source.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")).join("|"),"gu"):null;}
export function applyPronunciation(text:string,rules:PronunciationRule[]):string{
  const values=normalizePronunciationRules(rules),pattern=matcher(values),mapping=new Map(values.map(rule=>[rule.source,rule.spoken]));
  return pattern?text.replace(pattern,match=>mapping.get(match)!):text;
}
function* pronouncedChunks(text:string,maximum:number,rules:PronunciationRule[]){
  const pattern=matcher(rules),mapping=new Map(rules.map(rule=>[rule.source,rule.spoken]));
  type Unit={spoken:string;start:number;end:number};
  function* normal(start:number,end:number):Generator<Unit>{
    for(const match of text.slice(start,end).matchAll(/\s+|\S+/gu)){
      const raw=match[0],at=start+match.index;
      if(/^\s+$/u.test(raw))yield{spoken:" ",start:at,end:at+raw.length};
      else{
        let piece="",pieceStart=at,offset=at;
        for(const char of raw){
          if(piece.length+char.length>maximum && piece){yield{spoken:piece,start:pieceStart,end:offset};piece="";pieceStart=offset;}
          piece+=char;offset+=char.length;
        }
        if(piece)yield{spoken:piece,start:pieceStart,end:at+raw.length};
      }
    }
  }
  function* units():Generator<Unit>{
    let previous=0;
    if(pattern)for(const match of text.matchAll(pattern)){
      yield* normal(previous,match.index);yield{spoken:mapping.get(match[0])!.replace(/\s+/gu," "),start:match.index,end:match.index+match[0].length};previous=match.index+match[0].length;
    }
    yield* normal(previous,text.length);
  }
  let buffer:Unit[]=[],size=0;
  const render=()=>{
    let trimmed=buffer.length;while(trimmed && buffer[trimmed-1].spoken===" ")trimmed--;
    return{text:buffer.slice(0,trimmed).map(unit=>unit.spoken).join(""),start:buffer[0].start,end:buffer[trimmed-1].end};
  };
  for(const unit of units()){
    if(unit.spoken.length>maximum)throw new Error("A pronunciation is longer than this provider’s passage limit.");
    if(size+unit.spoken.length>maximum && buffer.length){yield render();buffer=[];size=0;}
    if(!buffer.length && unit.spoken===" ")continue;
    buffer.push(unit);size+=unit.spoken.length;
  }
  if(buffer.length)yield render();
}

export function planPronouncedPassages(document:ChapterDocument,title:string,maximum:number,includeNotes=false,rules:PronunciationRule[]=[]):{text:string;passage:AudioPassage}[]{
  const values=normalizePronunciationRules(rules),pattern=matcher(values),mapping=new Map(values.map(rule=>[rule.source,rule.spoken]));
  let estimated=0;
  for(const text of [title,...document.blocks.filter(block=>includeNotes || block.role!=="author_note").map(block=>block.text)]){
    let hadText=false,pendingSpace=false;
    const feed=(fragment:string)=>{
      for(const match of fragment.matchAll(/\s+|\S+/gu)){
        const raw=match[0];
        if(/^\s+$/u.test(raw))pendingSpace=hadText;
        else{estimated+=raw.length+Number(pendingSpace);hadText=true;pendingSpace=false;if(estimated>MAX_AUDIO_SPOKEN_UTF16)throw new AudioPlanningLimitError();}
      }
    };
    let previous=0;
    if(pattern)for(const match of text.matchAll(pattern)){feed(text.slice(previous,match.index));feed(mapping.get(match[0])!);previous=match.index+match[0].length;}
    feed(text.slice(previous));
  }
  if(!values.length)return planAudioPassages(document,title,maximum,includeNotes);
  const result:{text:string;passage:AudioPassage}[]=[];
  let spokenSize=0;
  const add=(part:{text:string;passage:AudioPassage})=>{spokenSize+=part.text.length;if(result.length>=MAX_AUDIO_PARTS || spokenSize>MAX_AUDIO_SPOKEN_UTF16)throw new AudioPlanningLimitError();result.push(part);};
  for(const chunk of pronouncedChunks(title,maximum,values))add({text:chunk.text,passage:{block_id:null,text_offset:null,text_length:null}});
  for(const block of document.blocks){
    if(block.role==="author_note"&&!includeNotes)continue;
    for(const chunk of pronouncedChunks(block.text,maximum,values))add({text:chunk.text,passage:{block_id:block.id,text_offset:chunk.start,text_length:chunk.end-chunk.start}});
  }
  return result;
}
