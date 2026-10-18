import { chapterIdentity, ChapterManifestChangedError, type ChapterIdentity } from './chapterIdentity';
import { stableOfflineChapterKey, registerOfflineChapterIdentity, resolveOfflineChapterIdentity } from './offlineChapterIdentity';
import {storageGeneration} from './accountStorage';
import {openOfflineDatabase,offlineTransaction,putOfflineRecord,transactionFailure,assertStorageGeneration} from './offlineStorageDatabase';
import type {TranslationVariant} from './readerToolsService';

export const offlineTranslations={
  async save(novelId:number,chapter:number,variant:TranslationVariant):Promise<void>{
    const identity=chapterIdentity(variant);if(!identity)throw new ChapterManifestChangedError();
    const generation=storageGeneration(),db=await openOfflineDatabase();
    try{
      assertStorageGeneration(generation);
      await new Promise<void>((resolve,reject)=>{
        const tx=offlineTransaction(db,'translations','readwrite');
        registerOfflineChapterIdentity(tx,novelId,chapter,identity,()=>putOfflineRecord(tx.objectStore('translations'),{...variant,novel_id:novelId,chapter_number:chapter,cache_key:`${stableOfflineChapterKey(novelId,identity)}:${variant.id}`}));
        tx.oncomplete=()=>{try{assertStorageGeneration(generation);resolve();}catch(error){reject(error);}};
        tx.onabort=()=>reject(transactionFailure(tx));tx.onerror=()=>{};
      });
    }finally{db.close();}
  },
  async list(novelId:number,chapter:number,expected?:ChapterIdentity):Promise<TranslationVariant[]>{
    const generation=storageGeneration(),db=await openOfflineDatabase();
    try{
      const rows=await new Promise<(TranslationVariant & {novel_id:number;chapter_number:number})[]>((resolve,reject)=>{
        const tx=offlineTransaction(db,'translations','readonly');let values:(TranslationVariant & {novel_id:number;chapter_number:number})[]=[];
        resolveOfflineChapterIdentity(tx,novelId,chapter,identity=>{
          if(!identity)return;
          const prefix=`${stableOfflineChapterKey(novelId,identity)}:`,request=tx.objectStore('translations').getAll(IDBKeyRange.bound(prefix,`${prefix}\uffff`));
          request.onsuccess=()=>{values=request.result.filter((row:TranslationVariant)=>row.chapter_key===identity.chapter_key).map(row=>({...row,...identity,chapter_number:chapter}));};
        },expected);
        tx.oncomplete=()=>{try{assertStorageGeneration(generation);resolve(values);}catch(error){reject(error);}};
        tx.onabort=()=>reject(transactionFailure(tx));tx.onerror=()=>{};
      });
      return rows.filter(row=>row.novel_id===novelId && row.chapter_number===chapter);
    }finally{db.close();}
  },
};
