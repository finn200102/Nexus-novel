import { chapterIdentity } from "./chapterIdentity";
/** Unified private payload inventory. No server, progress or pending-write data. */
import {accountDatabaseName,storageGeneration,onAccountStorageChange} from './accountStorage';
import {OFFLINE_CONTENT_STORES,OFFLINE_METADATA,MAX_OFFLINE_BUDGET,openOfflineDatabase,offlineTransaction,
  deleteOfflineRecord,offlineRandomToken,transactionFailure,assertStorageGeneration,OfflineStorageBudgetError,OfflineAudioBusyError} from './offlineStorageDatabase';
export {OfflineStorageBudgetError,OfflineAudioBusyError};
export type OfflineCleanupKind='text'|'audio'|'translations';
export type OfflineSourceState='current'|'stale'|'unknown';
export interface OfflineChapterInventory {
  novel_id:number;chapter_number:number;chapter_key?:string;address_current?:boolean;title:string|null;total_bytes:number;
  text:{ready:boolean;bytes:number;pinned:boolean;source_version:string|null};
  images:{ready:number;total:number;missing:number;embedded_bytes:number};
  audio:{ready:boolean;bytes:number;partial_bytes:number;completed_parts:number;job_status:string|null;busy:boolean;source_state:OfflineSourceState;source_version:string|null};
  translations:{id:number;language:string;status:string;bytes:number;ready:boolean;source_version:string|null;source_state:OfflineSourceState}[];
}
export interface OfflineStoryInventory {novel_id:number;novel_title:string|null;library_id:number|null;total_bytes:number;chapters:OfflineChapterInventory[]}
export interface OfflineLibraryInventory {stories:OfflineStoryInventory[];total_bytes:number;limit_bytes:number|null}
export interface OfflineCleanupSelection {novel_id?:number;chapter_number?:number;chapter_key?:string;kinds:OfflineCleanupKind[]}
export interface OfflineCleanupPreview {selection:OfflineCleanupSelection;review_token:string;records:number;bytes:number;busy_chapters:{novel_id:number;chapter_number:number}[]}
export class OfflineCleanupChangedError extends Error {constructor(){super('These offline files changed after review. Review the cleanup again; no files were removed.');this.name='OfflineCleanupChangedError';}}

type Row=Record<string,unknown>;
type Entry={store:string;key:IDBValidKey;row:Row;bytes:number;binary_bytes:number;revision:string};
type Snapshot={entries:Entry[];settings:Row;total:number;addresses:Map<string,Row>;manifests:Map<number,Row>};
type Review={generation:number;database:string;signature:string;selection:OfflineCleanupSelection};
const reviews=new Map<string,Review>();
onAccountStorageChange(()=>reviews.clear());
const rowNumber=(value:unknown)=>typeof value==='number' && Number.isInteger(value)?value:null;
const stringOrNull=(value:unknown)=>typeof value==='string'?value:null;
function coordinates(row:Row):{novel_id:number;chapter_number:number;chapter_key:string}|null {
  const novel=rowNumber(row.novel_id ?? row.novelId),chapter=rowNumber(row.chapter_number ?? row.chapterNumber),identity=chapterIdentity(row);
  return novel!==null && novel>0 && chapter!==null && identity ? {novel_id:novel,chapter_number:chapter,chapter_key:identity.chapter_key}:null;
}
const isLease=(entry:Entry)=>entry.store==='chapter_audio_jobs' && String(entry.key).startsWith('lease:');
const sourceState=(version:string|null,original:string|null):OfflineSourceState=>!version || !original?'unknown':version===original?'current':'stale';
function readSnapshot(tx:IDBTransaction,done:(snapshot:Snapshot)=>void){
  const entries:Entry[]=[],settings:Row={},addresses=new Map<string,Row>(),manifests=new Map<number,Row>();let pending=2;
  const finish=()=>{if(--pending)return;done({entries,settings,addresses,manifests,total:entries.filter(e=>!isLease(e)).reduce((sum,e)=>sum+e.bytes,0)});};
  const meta=tx.objectStore(OFFLINE_METADATA).openCursor();meta.onsuccess=()=>{
    const cursor=meta.result;if(!cursor){finish();return;}
    const value=cursor.value as Row;
    if(cursor.key==='settings')Object.assign(settings,value);
    if(String(cursor.key).startsWith('chapter-address:'))addresses.set(String(cursor.key),value);
    if(String(cursor.key).startsWith('chapter-manifest:'))manifests.set(Number(String(cursor.key).slice('chapter-manifest:'.length)),value);
    if(typeof value.store_name==='string' && OFFLINE_CONTENT_STORES.includes(value.store_name as typeof OFFLINE_CONTENT_STORES[number]) && value.summary){
      const row=value.summary as Row;entries.push({store:value.store_name,key:value.record_key as IDBValidKey,row,bytes:Number(value.value),binary_bytes:Number(row.binary_bytes || 0),revision:String(value.revision)});
    }
    cursor.continue();
  };
  // Lease rows are tiny and intentionally outside the payload budget. Never
  // scan recording buffers, source text, translated documents or job chunks.
  const leases=tx.objectStore('chapter_audio_jobs').openCursor(IDBKeyRange.bound('lease:','lease:\uffff'));
  leases.onsuccess=()=>{const cursor=leases.result;if(!cursor){finish();return;}entries.push({store:'chapter_audio_jobs',key:cursor.primaryKey,row:cursor.value,bytes:0,binary_bytes:0,revision:''});cursor.continue();};
}

async function read<T>(work:(snapshot:Snapshot)=>T):Promise<T>{
  const generation=storageGeneration(),db=await openOfflineDatabase();
  try{return await new Promise<T>((resolve,reject)=>{
    let result:T;const tx=offlineTransaction(db,[...OFFLINE_CONTENT_STORES,OFFLINE_METADATA],'readonly');
    readSnapshot(tx,snapshot=>{try{assertStorageGeneration(generation);result=work(snapshot);}catch(error){reject(error);}});
    tx.oncomplete=()=>{try{assertStorageGeneration(generation);resolve(result);}catch(error){reject(error);}};
    tx.onabort=()=>reject(transactionFailure(tx));tx.onerror=()=>{};
  });}finally{db.close();}
}
function inventory(snapshot:Snapshot):OfflineLibraryInventory {
  const stories=new Map<number,OfflineStoryInventory>(),chapters=new Map<string,OfflineChapterInventory>();
  const chapterFor=(entry:Entry)=>{
    const position=coordinates(entry.row);if(!position)return null;
    let story=stories.get(position.novel_id);
    if(!story){story={novel_id:position.novel_id,novel_title:null,library_id:null,total_bytes:0,chapters:[]};stories.set(position.novel_id,story);}
    story.novel_title ||= stringOrNull(entry.row.novel_title);story.library_id ??= rowNumber(entry.row.library_id);
    const chapterKey=`${position.novel_id}:${position.chapter_key}`;
    const address=snapshot.addresses.get(`chapter-address:${position.novel_id}:${position.chapter_number}`),manifest=snapshot.manifests.get(position.novel_id);
    const addressCurrent=Boolean(address?.chapter_key===position.chapter_key && address?.manifest_epoch===manifest?.manifest_epoch && address?.manifest_revision===manifest?.manifest_revision);
    let chapter=chapters.get(chapterKey);
    if(!chapter){chapter={...position,address_current:addressCurrent,title:null,total_bytes:0,text:{ready:false,bytes:0,pinned:false,source_version:null},images:{ready:0,total:0,missing:0,embedded_bytes:0},audio:{ready:false,bytes:0,partial_bytes:0,completed_parts:0,job_status:null,busy:false,source_state:'unknown',source_version:null},translations:[]};story.chapters.push(chapter);chapters.set(chapterKey,chapter);}
    chapter.title ||= stringOrNull(entry.row.title);
    if(!isLease(entry)){chapter.total_bytes+=entry.bytes;story.total_bytes+=entry.bytes;}
    return chapter;
  };
  for(const entry of snapshot.entries){
    if(isLease(entry) && !(typeof entry.row.expiresAt==='number' && entry.row.expiresAt>Date.now()))continue;
    const chapter=chapterFor(entry);if(!chapter)continue;
    const row=entry.row;
    if(isLease(entry)){chapter.audio.busy ||= typeof row.expiresAt==='number' && row.expiresAt>Date.now();continue;}
    if(entry.store==='chapters'){
      const document=row.document as {content_version?:string}|undefined;
      chapter.text={ready:row.content_ready===true,bytes:entry.bytes,pinned:row.pinned===true,source_version:document?.content_version || stringOrNull(row.source_version)};
      chapter.images=(row.image_summary as OfflineChapterInventory['images']|undefined) || {ready:0,total:0,missing:0,embedded_bytes:0};
    }else if(entry.store==='chapter_audio'){
      const manifest=row.manifest as {source_version?:string}|undefined;
      const payload=entry.binary_bytes;
      chapter.audio.ready=payload>0;chapter.audio.bytes+=entry.bytes;chapter.audio.source_version=manifest?.source_version || null;
    }else if(entry.store==='chapter_audio_jobs'){
      chapter.audio.partial_bytes+=entry.bytes;chapter.audio.job_status=stringOrNull(row.status);
      chapter.audio.completed_parts=typeof row.completed_chunks==='number'?row.completed_chunks:0;
      if(!chapter.audio.bytes && !chapter.audio.source_version)chapter.audio.source_version=stringOrNull(row.source_version);
    }else if(entry.store==='chapter_audio_segments')chapter.audio.partial_bytes+=entry.bytes;
    else if(entry.store==='translations')chapter.translations.push({id:Number(row.id),language:String(row.language || ''),status:String(row.status || 'unknown'),bytes:entry.bytes,ready:row.translation_ready===true,source_version:stringOrNull(row.source_version),source_state:'unknown'});
  }
  for(const story of stories.values()){
    story.chapters.sort((a,b)=>a.chapter_number-b.chapter_number);
    for(const chapter of story.chapters){chapter.audio.source_state=sourceState(chapter.audio.source_version,chapter.text.source_version);for(const variant of chapter.translations)variant.source_state=sourceState(variant.source_version,chapter.text.source_version);chapter.translations.sort((a,b)=>a.id-b.id);}
  }
  return {stories:[...stories.values()].sort((a,b)=>a.novel_id-b.novel_id),total_bytes:snapshot.total,limit_bytes:typeof snapshot.settings.limit_bytes==='number'?snapshot.settings.limit_bytes:null};
}
function selected(snapshot:Snapshot,selection:OfflineCleanupSelection){
  const stores=new Set(selection.kinds.flatMap(kind=>kind==='text'?['chapters']:kind==='translations'?['translations']:['chapter_audio','chapter_audio_jobs','chapter_audio_segments']));
  return snapshot.entries.filter(entry=>{const point=coordinates(entry.row);return !isLease(entry) && stores.has(entry.store) && point && (selection.novel_id===undefined || point.novel_id===selection.novel_id) && (selection.chapter_number===undefined || point.chapter_number===selection.chapter_number) && (selection.chapter_key===undefined || point.chapter_key===selection.chapter_key);});
}
function signature(entries:Entry[]):string {
  // New writes have random revisions committed beside their payload. Hash the
  // metadata too for untracked legacy/test records, without retaining private
  // story text in the bounded review-token map.
  const metadataHash=(row:Row)=>{
    const value=JSON.stringify(row);let first=2166136261,second=2246822519;
    for(let i=0;i<value.length;i++){const code=value.charCodeAt(i);first=Math.imul(first^code,16777619);second=Math.imul(second^code,3266489917);}
    return `${first>>>0}:${second>>>0}`;
  };
  return JSON.stringify(entries.map(e=>[e.store,e.key,e.bytes,e.revision,metadataHash(e.row)]).sort((a,b)=>String(a[0])+String(a[1])>String(b[0])+String(b[1])?1:-1));
}

function busy(snapshot:Snapshot,selection:OfflineCleanupSelection){
  if(!selection.kinds.includes('audio'))return [];
  return snapshot.entries.filter(e=>isLease(e) && typeof e.row.expiresAt==='number' && e.row.expiresAt>Date.now()).map(e=>coordinates(e.row)!).filter(point=>point && (selection.novel_id===undefined || point.novel_id===selection.novel_id) && (selection.chapter_number===undefined || point.chapter_number===selection.chapter_number) && (selection.chapter_key===undefined || point.chapter_key===selection.chapter_key));
}
function normalize(selection:OfflineCleanupSelection):OfflineCleanupSelection {
  if(!selection.kinds.length || selection.kinds.some(kind=>!['text','audio','translations'].includes(kind)))throw new Error('Choose offline content to remove');
  if(selection.novel_id!==undefined && (!Number.isSafeInteger(selection.novel_id)||selection.novel_id<=0))throw new Error('Invalid story');
  if(selection.chapter_number!==undefined && !Number.isSafeInteger(selection.chapter_number))throw new Error('Invalid chapter');
  return {...selection,kinds:[...new Set(selection.kinds)].sort()};
}
export const offlineLibraryStore={
  async inventory():Promise<OfflineLibraryInventory>{return read(inventory);},
  async budget():Promise<{total_bytes:number;limit_bytes:number|null;remaining_bytes:number|null}>{
    const generation=storageGeneration(),db=await openOfflineDatabase();
    try{return await new Promise((resolve,reject)=>{
      const tx=offlineTransaction(db,OFFLINE_METADATA,'readonly'),store=tx.objectStore(OFFLINE_METADATA),total=store.get('total_bytes'),settings=store.get('settings');
      tx.oncomplete=()=>{try{assertStorageGeneration(generation);const bytes=total.result?.value || 0,limit=settings.result?.limit_bytes ?? null;resolve({total_bytes:bytes,limit_bytes:limit,remaining_bytes:limit===null?null:Math.max(0,limit-bytes)});}catch(error){reject(error);}};
      tx.onabort=()=>reject(transactionFailure(tx));tx.onerror=()=>{};
    });}finally{db.close();}
  },
  async setBudget(limitBytes:number|null):Promise<void>{
    if(limitBytes!==null && (!Number.isSafeInteger(limitBytes)||limitBytes<0||limitBytes>MAX_OFFLINE_BUDGET))throw new Error('Choose an offline storage limit from zero to 1 TB, or leave it unlimited.');
    const generation=storageGeneration(),db=await openOfflineDatabase();
    try{await new Promise<void>((resolve,reject)=>{
      assertStorageGeneration(generation);const tx=offlineTransaction(db,OFFLINE_METADATA,'readwrite');
      tx.objectStore(OFFLINE_METADATA).put({key:'settings',limit_bytes:limitBytes});
      tx.oncomplete=()=>{try{assertStorageGeneration(generation);resolve();}catch(error){reject(error);}};
      tx.onabort=()=>reject(transactionFailure(tx));tx.onerror=()=>{};
    });}finally{db.close();}
  },
  async previewCleanup(selection:OfflineCleanupSelection):Promise<OfflineCleanupPreview>{
    const normalized=normalize(selection),generation=storageGeneration(),database=accountDatabaseName();
    return read(snapshot=>{
      const entries=selected(snapshot,normalized),token=offlineRandomToken();
      if(reviews.size>=20)reviews.delete(reviews.keys().next().value!);
      reviews.set(token,{generation,database,signature:signature(entries),selection:{...normalized,kinds:[...normalized.kinds]}});
      return {selection:normalized,review_token:token,records:entries.length,bytes:entries.reduce((sum,e)=>sum+e.bytes,0),busy_chapters:busy(snapshot,normalized)};
    });
  },
  async cleanup(preview:OfflineCleanupPreview):Promise<{removed_records:number;removed_bytes:number}>{
    const review=reviews.get(preview.review_token),generation=storageGeneration();
    if(!review || review.generation!==generation || review.database!==accountDatabaseName() || JSON.stringify(review.selection)!==JSON.stringify(normalize(preview.selection)))throw new OfflineCleanupChangedError();
    const db=await openOfflineDatabase();
    try{return await new Promise((resolve,reject)=>{
      const tx=offlineTransaction(db,[...OFFLINE_CONTENT_STORES,OFFLINE_METADATA],'readwrite');let result={removed_records:0,removed_bytes:0},failure:unknown;
      readSnapshot(tx,snapshot=>{try{
        assertStorageGeneration(generation);
        if(busy(snapshot,review.selection).length)throw new OfflineAudioBusyError();
        const entries=selected(snapshot,review.selection);if(signature(entries)!==review.signature)throw new OfflineCleanupChangedError();
        for(const entry of entries)deleteOfflineRecord(tx.objectStore(entry.store),entry.key);
        result={removed_records:entries.length,removed_bytes:entries.reduce((sum,e)=>sum+e.bytes,0)};
      }catch(error){failure=error;tx.abort();}});
      tx.oncomplete=()=>{reviews.delete(preview.review_token);try{assertStorageGeneration(generation);resolve(result);}catch(error){reject(error);}};
      tx.onabort=()=>reject(failure || transactionFailure(tx));tx.onerror=()=>{};
    });}finally{db.close();}
  },
};
