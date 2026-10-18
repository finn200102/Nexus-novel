/** Shared account-fenced database and transactional payload accounting.
 * Counts UTF-8 serialized metadata plus binary bytes; browser/index overhead is
 * deliberately excluded. Persistence permission is a separate browser concern.
 */
import {accountDatabaseName,storageGeneration,onAccountStorageChange} from './accountStorage';
import {offlineImageSource} from './offlineImageSource';
import {offlineIdentityFailure} from './offlineChapterIdentity';
export const OFFLINE_CONTENT_STORES=['chapters','chapter_audio','chapter_audio_jobs','chapter_audio_segments','translations'] as const;
export const OFFLINE_METADATA='offline_metadata';
export const MAX_OFFLINE_BUDGET=1_000_000_000_000;
const encoder=new TextEncoder();
export const offlineRandomToken=()=>[...crypto.getRandomValues(new Uint8Array(16))].map(byte=>byte.toString(16).padStart(2,'0')).join('');
export function binaryPayloadBytes(value:unknown):number|null {
  if(value && typeof value==='object'){
    const tag=Object.prototype.toString.call(value);
    if(tag==='[object ArrayBuffer]' || ArrayBuffer.isView(value))return (value as ArrayBuffer).byteLength;
    if(tag==='[object Blob]' || tag==='[object File]')return (value as Blob).size;
  }
  return null;
}
export class OfflineAudioBusyError extends Error {constructor(){super('Audio is being prepared in another tab. Wait for it to finish before changing these audio files.');this.name='OfflineAudioBusyError';}}
export class OfflineStorageBudgetError extends Error {
  constructor(){super('This download exceeds your offline storage limit. Free some space or increase the limit; existing files were preserved.');this.name='OfflineStorageBudgetError';}
}
export function storedPayloadBytes(value:Record<string,unknown>):number {
  const metadata={...value};let binary=0;
  for(const key of ['audio','audio_data']){
    const item=metadata[key];
    const size=binaryPayloadBytes(item);if(size!==null){binary+=size;delete metadata[key];}
  }
  return encoder.encode(JSON.stringify(metadata)).length+binary;
}
const contentKey=(store:string,key:IDBValidKey)=>`bytes:${store}:${String(key)}`;
const uncounted=(store:string,key:IDBValidKey)=>store==='chapter_audio_jobs' && String(key).startsWith('lease:');
type Summary=Record<string,unknown>;
function payloadSummary(value:Record<string,unknown>):Summary {
  const result:Summary={};
  for(const key of ['novel_id','chapter_number','chapter_key','manifest_epoch','manifest_revision','library_id','id','index','pinned','completed_chunks','status','language','source_version','cache_key','segment_key'])if(value[key]!==undefined)result[key]=value[key];
  for(const key of ['title','novel_title'])if(typeof value[key]==='string')result[key]=(value[key] as string).slice(0,1000);
  const document=value.document as {content_version?:string;blocks?:{html?:string}[];image_assets?:{total?:number;missing?:number}}|undefined;
  if(document){
    result.document={content_version:document.content_version};
    let ready=0,total=0,embedded=0;
    for(const block of document.blocks || [])for(const image of block.html?.match(/<img\b[^>]*>/gi) || []){
      total++;const source=offlineImageSource(image);if(source){ready++;embedded+=encoder.encode(source).length;}
    }
    total=Math.max(total,document.image_assets?.total || 0);
    result.image_summary={ready,total,missing:Math.max(total-ready,document.image_assets?.missing || 0),embedded_bytes:embedded};
  }
  result.content_ready=Boolean(typeof value.content==='string' && value.content.trim()) || Boolean(document?.blocks?.length);
  result.translation_ready=value.status==='completed' && Boolean(document?.blocks?.length) && (typeof value.total_blocks!=='number' || typeof value.completed_blocks==='number' && value.completed_blocks>=value.total_blocks);
  const manifest=value.manifest as {source_version?:string}|undefined;
  if(manifest)result.manifest={source_version:manifest.source_version};
  result.binary_bytes=binaryPayloadBytes(value.audio_data) ?? binaryPayloadBytes(value.audio) ?? 0;
  return result;
}
type Mutation={store:string;key:IDBValidKey;bytes:number;summary?:Summary};
type Context={generation:number;failure?:unknown;queue:Mutation[];running:boolean;rebuilding?:boolean};
const contexts=new WeakMap<IDBTransaction,Context>();
const activeTransactions=new Set<IDBTransaction>();
onAccountStorageChange(()=>{for(const tx of activeTransactions)abort(tx,new DOMException('Reading account changed','AbortError'));});
function register(tx:IDBTransaction,generation:number){
  contexts.set(tx,{generation,queue:[],running:false});activeTransactions.add(tx);
  const finished=()=>activeTransactions.delete(tx);tx.addEventListener('complete',finished);tx.addEventListener('abort',finished);
}
export function transactionFailure(tx:IDBTransaction):unknown {return contexts.get(tx)?.failure || offlineIdentityFailure(tx) || tx.error || new DOMException('Offline operation cancelled','AbortError');}
export function assertStorageGeneration(generation:number):void {
  if(generation!==storageGeneration())throw new DOMException('Reading account changed','AbortError');
}
function abort(tx:IDBTransaction,error:unknown){const ctx=contexts.get(tx);if(ctx)ctx.failure=error;try{tx.abort();}catch{/* Already aborted. */}}
function accountMutation(tx:IDBTransaction,change:Mutation){
  if(uncounted(change.store,change.key))return;
  let ctx=contexts.get(tx);
  if(!ctx){ctx={generation:storageGeneration(),queue:[],running:false};contexts.set(tx,ctx);}
  ctx.queue.push(change);
  const next=()=>{
    if(!ctx)return;
    const task=ctx.queue.shift();if(!task){ctx.running=false;return;}
    try{assertStorageGeneration(ctx.generation);}catch(error){abort(tx,error);return;}
    const metadata=tx.objectStore(OFFLINE_METADATA),old=metadata.get(contentKey(task.store,task.key));
    old.onsuccess=()=>{
      const total=metadata.get('total_bytes');total.onsuccess=()=>{
        const settings=metadata.get('settings');settings.onsuccess=()=>{
          try{assertStorageGeneration(ctx!.generation);}catch(error){abort(tx,error);return;}
          try{
          const before=total.result?.value || 0,previous=old.result?.value || 0;
          const after=Math.max(0,before-previous+task.bytes),limit=settings.result?.limit_bytes ?? null;
          if(!ctx!.rebuilding && limit!==null && after>limit && after>before){abort(tx,new OfflineStorageBudgetError());return;}
          if(task.bytes)metadata.put({key:contentKey(task.store,task.key),value:task.bytes,revision:offlineRandomToken(),store_name:task.store,record_key:task.key,summary:task.summary});else metadata.delete(contentKey(task.store,task.key));
          const written=metadata.put({key:'total_bytes',value:after});written.onsuccess=next;
          }catch(error){abort(tx,error);}
        };
      };
    };
  };
  if(!ctx.running){ctx.running=true;next();}
}
export function putOfflineRecord(store:IDBObjectStore,value:Record<string,unknown>):IDBRequest<IDBValidKey>{
  const bytes=storedPayloadBytes(value),summary=payloadSummary(value),request=store.put(value);
  request.addEventListener('success',()=>accountMutation(store.transaction,{store:store.name,key:request.result,bytes,summary}));
  return request;
}
export function deleteOfflineRecord(store:IDBObjectStore,key:IDBValidKey):IDBRequest<undefined>{
  const request=store.delete(key);
  request.addEventListener('success',()=>accountMutation(store.transaction,{store:store.name,key,bytes:0}));
  return request;
}
export function offlineTransaction(database:IDBDatabase,names:string|string[],mode:IDBTransactionMode):IDBTransaction {
  const requested=typeof names==='string'?[names]:names;
  const tx=database.transaction([...new Set([...requested,OFFLINE_METADATA])],mode);
  register(tx,storageGeneration());
  return tx;
}
export function openOfflineDatabase():Promise<IDBDatabase>{
  const generation=storageGeneration(),name=accountDatabaseName();
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open(name,6);let blocked=false;
    request.onupgradeneeded=(event)=>{
      const database=request.result,tx=request.transaction!;
      register(tx,generation);
      if(!database.objectStoreNames.contains('chapters')){
        const store=database.createObjectStore('chapters',{keyPath:'cache_key'});
        store.createIndex('cached_at','cached_at');store.createIndex('novel_id','novel_id');
      }
      for(const store of ['chapter_audio','chapter_audio_jobs','translations'])if(!database.objectStoreNames.contains(store))database.createObjectStore(store,{keyPath:'cache_key'});
      if(!database.objectStoreNames.contains('chapter_audio_segments')){
        const store=database.createObjectStore('chapter_audio_segments',{keyPath:'segment_key'});store.createIndex('cache_key','cache_key');
      }
      if(!database.objectStoreNames.contains(OFFLINE_METADATA)){
        database.createObjectStore(OFFLINE_METADATA,{keyPath:'key'});
        tx.objectStore(OFFLINE_METADATA).put({key:'total_bytes',value:0});
        tx.objectStore(OFFLINE_METADATA).put({key:'summary_version',value:1});
      }
      if ((event as IDBVersionChangeEvent).oldVersion > 0 && (event as IDBVersionChangeEvent).oldVersion < 6) {
        // Numeric addresses in older stores cannot prove chapter identity after
        // a renumber. Clear only regenerable local payloads, never progress or
        // preferences (which live in separate account storage).
        for (const name of OFFLINE_CONTENT_STORES) tx.objectStore(name).clear();
        const metadata = tx.objectStore(OFFLINE_METADATA), cursor = metadata.openCursor(IDBKeyRange.bound('bytes:', 'bytes:\uffff'));
        cursor.onsuccess = () => { const row = cursor.result; if (row) { row.delete(); row.continue(); } };
        metadata.put({ key: 'total_bytes', value: 0 }); metadata.put({ key: 'summary_version', value: 1 });
        metadata.put({ key: 'chapter_identity_version', value: 1 });
      }
    };
    request.onsuccess=()=>{
      if(blocked || generation!==storageGeneration()){request.result.close();reject(new DOMException('Reading account changed','AbortError'));return;}
      request.result.onversionchange=()=>request.result.close();
      ensureSummaries(request.result,generation).then(()=>{
        try{assertStorageGeneration(generation);resolve(request.result);}catch(error){request.result.close();reject(error);}
      },error=>{request.result.close();reject(error);});
    };
    request.onerror=()=>reject(request.error);
    request.onblocked=()=>{blocked=true;reject(new Error('Close older Nexus tabs to upgrade offline storage safely.'));};
  });
}


/** Streaming one-time backfill for early schema-5 clients. Ordinary opens only
 * read a small marker, never large chapter/audio payloads. */
function ensureSummaries(database:IDBDatabase,generation:number):Promise<void>{
  return new Promise((resolve,reject)=>{
    const check=offlineTransaction(database,OFFLINE_METADATA,'readonly'),marker=check.objectStore(OFFLINE_METADATA).get('summary_version');
    check.onabort=()=>reject(transactionFailure(check));
    check.oncomplete=()=>{
      if(marker.result?.value===1){resolve();return;}
      try{assertStorageGeneration(generation);}catch(error){reject(error);return;}
      const tx=offlineTransaction(database,[...OFFLINE_CONTENT_STORES,OFFLINE_METADATA],'readwrite');
      const metadata=tx.objectStore(OFFLINE_METADATA),again=metadata.get('summary_version');
      again.onsuccess=()=>{
        if(again.result?.value===1)return;
        contexts.get(tx)!.rebuilding=true;
        metadata.put({key:'total_bytes',value:0});
        const old=metadata.openCursor(IDBKeyRange.bound('bytes:','bytes:\uffff'));
        old.onsuccess=()=>{
          const previous=old.result;if(previous){previous.delete();previous.continue();return;}
          for(const name of OFFLINE_CONTENT_STORES){
            const cursor=tx.objectStore(name).openCursor();cursor.onsuccess=()=>{
              const row=cursor.result;if(!row)return;
              accountMutation(tx,{store:name,key:row.primaryKey,bytes:storedPayloadBytes(row.value),summary:payloadSummary(row.value)});row.continue();
            };
          }
          metadata.put({key:'summary_version',value:1});
        };
      };
      tx.oncomplete=()=>resolve();tx.onabort=()=>reject(transactionFailure(tx));
    };
  });
}
