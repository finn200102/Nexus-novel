import { fixtureChapterIdentity as identity } from "../fixtures/chapterIdentity";
import 'fake-indexeddb/auto';
import {IDBFactory,IDBObjectStore} from 'fake-indexeddb';
import {Blob as NativeBlob} from 'node:buffer';
import {beforeEach,afterEach,describe,it,expect,vi} from 'vitest';
import {activateAccountStorage,accountDatabaseName,accountStorageKey} from '../../src/services/accountStorage';
import {offlineLibraryStore,OfflineCleanupChangedError,OfflineAudioBusyError,OfflineStorageBudgetError} from '../../src/services/offlineLibraryStore';
import {offlineReaderStore,chapterAudioStore,chapterAudioJobStore,browserAudioLeaseStore,type ChapterAudioJob} from '../../src/services/offlineReaderStore';
import {offlineTranslations} from '../../src/services/offlineTranslations';
import {openOfflineDatabase} from '../../src/services/offlineStorageDatabase';
import type {TranslationVariant} from '../../src/services/readerToolsService';
import type {ChapterDocument} from '../../src/components/reader/chapterDocument';
const doc=(version='current'):ChapterDocument=>({schema_version:1,content_version:version,source_format:'html',plain_text:'Story',blocks:[{id:'p1',kind:'p',html:'<p>Story</p>',text:'Story'}]});
const text=(novel=1,chapter=1)=>({...identity(novel,chapter),id:novel*100+chapter,novel_id:novel,chapter_number:chapter,title:'Chapter',content:'Story 😀',document:doc(),novel_title:'A story',library_id:5});
const variant=(id=7,version='current',novel=1,chapter=1):TranslationVariant=>({...identity(novel,chapter),id,language:'de',status:'completed',source_version:version,completed_blocks:1,total_blocks:1,document:doc('translation'),charged_usd:0});
const job=(novel=1,chapter=2):ChapterAudioJob=>({...identity(novel,chapter),cache_key:`${novel}:${identity(novel,chapter).chapter_key}`,novel_id:novel,chapter_number:chapter,status:'generating',chunks:['One','Two'],source_version:'current',completed_chunks:1,created_at:1,updated_at:1});
const readText=(audio:Blob)=>typeof audio.text==='function'?audio.text():new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(reader.error);reader.readAsText(audio);});
const blob=(value:string)=>new NativeBlob([value],{type:'audio/wav'}) as unknown as Blob;
const audioManifest=(version='current',novel=1,chapter=1)=>({...identity(novel,chapter),source_version:version,rendition:'original' as const,include_author_notes:false,precision:'unavailable' as const,duration_seconds:1,segments:[]});
beforeEach(()=>{vi.stubGlobal('indexedDB',new IDBFactory());activateAccountStorage(301);});
afterEach(()=>{activateAccountStorage(null);vi.restoreAllMocks();vi.unstubAllGlobals();});

describe('unified private offline payloads',()=>{
  it('unions derivative-only chapters, counts real binary payloads and distinguishes stale/unknown versions',async()=>{
    const original=text();original.document.blocks[0].html='<p>Story<img src="data:image/png;base64,AAAA"><img src="https://remote.invalid/pic"></p>';
    await offlineReaderStore.save(original,{pinned:true});
    await chapterAudioStore.save(1,1,blob('ready'),audioManifest('old'));
    await offlineTranslations.save(1,1,variant(1,'old'));
    await chapterAudioStore.save(2,4,blob('audio only'),audioManifest('current',2,4));
    await offlineTranslations.save(3,8,variant(7,'current',3,8));
    await chapterAudioJobStore.save(job());await chapterAudioJobStore.saveSegment(1,2,0,blob('partial'),undefined,undefined,identity(1,2));
    const inventory=await offlineLibraryStore.inventory(),chapter=inventory.stories[0].chapters[0];
    expect(inventory.stories.map(s=>s.novel_id)).toEqual([1,2,3]);
    expect(chapter.images).toMatchObject({ready:1,total:2,missing:1});
    expect(chapter.images.embedded_bytes).toBeGreaterThan(0);
    expect(chapter.text.pinned).toBe(true);expect(chapter.audio).toMatchObject({ready:true,source_state:'stale'});
    expect(chapter.translations[0]).toMatchObject({ready:true,source_state:'stale'});
    expect(inventory.stories[1].chapters[0].audio.source_state).toBe('unknown');
    expect(inventory.stories[2].chapters[0].translations[0].source_state).toBe('unknown');
    expect(inventory.stories[0].chapters[1].audio.partial_bytes).toBeGreaterThan(7);
    const sum=inventory.stories.flatMap(s=>s.chapters).reduce((n,c)=>n+c.text.bytes+c.audio.bytes+c.audio.partial_bytes+c.translations.reduce((m,t)=>m+t.bytes,0),0);
    expect(inventory.total_bytes).toBe(sum);expect((await offlineLibraryStore.budget()).total_bytes).toBe(sum);
  });
  it('atomically preserves all earlier payloads when replacements exceed the shared budget',async()=>{
    await offlineReaderStore.save(text());await chapterAudioStore.save(1,1,blob('old'),audioManifest());await offlineTranslations.save(1,1,variant());
    const before=await offlineLibraryStore.budget();await offlineLibraryStore.setBudget(before.total_bytes);
    await expect(chapterAudioStore.save(1,1,blob('new larger audio'.repeat(100)),audioManifest('new'))).rejects.toBeInstanceOf(OfflineStorageBudgetError);
    await expect(offlineReaderStore.save({...text(),content:'longer'.repeat(1000)})).rejects.toBeInstanceOf(OfflineStorageBudgetError);
    await expect(offlineTranslations.save(1,1,{...variant(),document:{...doc(),plain_text:'longer'.repeat(1000)}})).rejects.toBeInstanceOf(OfflineStorageBudgetError);
    expect(await readText((await chapterAudioStore.get(1,1))!)).toBe('old');
    expect((await offlineReaderStore.get(1,1))?.content).toBe('Story 😀');
    expect((await offlineTranslations.list(1,1))[0].document.plain_text).toBe('Story');
    expect((await offlineLibraryStore.budget()).total_bytes).toBe(before.total_bytes);
  });
  it('serializes simultaneous writers across separate database connections',async()=>{
    await offlineLibraryStore.setBudget(1000);
    const outcomes=await Promise.allSettled([chapterAudioStore.save(1,1,blob('a'.repeat(250)),audioManifest()),chapterAudioStore.save(1,2,blob('b'.repeat(250)),audioManifest('current',1,2))]);
    expect(outcomes.filter(o=>o.status==='fulfilled')).toHaveLength(1);
    expect(outcomes.filter(o=>o.status==='rejected')).toHaveLength(1);
    const status=await offlineLibraryStore.budget();expect(status.total_bytes).toBeLessThanOrEqual(1000);
    expect((await offlineLibraryStore.inventory()).total_bytes).toBe(status.total_bytes);
  });
  it('aborts native metadata quota failures after binary put without losing the previous recording',async()=>{
    await chapterAudioStore.save(1,1,blob('old'),audioManifest());
    const before=await offlineLibraryStore.budget(),put=IDBObjectStore.prototype.put;
    vi.spyOn(IDBObjectStore.prototype,'put').mockImplementation(function(this:IDBObjectStore,value:unknown,key?:IDBValidKey){
      if(this.name==='offline_metadata' && String((value as {key?:string}).key).startsWith('bytes:'))throw new DOMException('Full disk','QuotaExceededError');
      return key===undefined?put.call(this,value):put.call(this,value,key);
    });
    await expect(chapterAudioStore.save(1,1,blob('new'),audioManifest())).rejects.toMatchObject({name:'QuotaExceededError'});
    vi.restoreAllMocks();expect(await readText((await chapterAudioStore.get(1,1))!)).toBe('old');expect(await offlineLibraryStore.budget()).toEqual(before);
  });
  it('protects live leases and partial work while allowing unrelated text cleanup',async()=>{
    await offlineReaderStore.save(text());const lease=(await browserAudioLeaseStore.claim(1,1,'active-tab',undefined,identity(1,1)))!;
    await chapterAudioJobStore.save(job(1,1),undefined,lease);await chapterAudioJobStore.saveSegment(1,1,0,blob('retained'),undefined,lease);
    const preview=await offlineLibraryStore.previewCleanup({novel_id:1,kinds:['audio']});expect(preview.busy_chapters).toEqual([expect.objectContaining({novel_id:1,chapter_number:1,chapter_key:identity(1,1).chapter_key})]);
    await expect(offlineLibraryStore.cleanup(preview)).rejects.toBeInstanceOf(OfflineAudioBusyError);
    expect(await chapterAudioJobStore.segments(1,1)).toHaveLength(1);
    await offlineLibraryStore.setBudget(0);expect(await browserAudioLeaseStore.renew(lease)).toBe(true);
    const textReview=await offlineLibraryStore.previewCleanup({novel_id:1,kinds:['text']});await offlineLibraryStore.cleanup(textReview);
    expect(await offlineReaderStore.get(1,1)).toBeNull();expect((await browserAudioLeaseStore.get(1,1))?.token).toBe(lease.token);
  });
  it('rejects equal-size replacement after review and preserves progress plus queued writes during accepted cleanup',async()=>{
    let now=1000;vi.spyOn(Date,'now').mockImplementation(()=>now);
    await chapterAudioStore.save(1,1,blob('aaa'),audioManifest());await offlineTranslations.save(1,1,variant());
    const preview=await offlineLibraryStore.previewCleanup({novel_id:1,kinds:['audio','translations']});
    await chapterAudioStore.save(1,1,blob('bbb'),audioManifest());now++;
    await expect(offlineLibraryStore.cleanup(preview)).rejects.toBeInstanceOf(OfflineCleanupChangedError);
    expect(await readText((await chapterAudioStore.get(1,1))!)).toBe('bbb');
    localStorage.setItem(accountStorageKey('progress'),'private progress');localStorage.setItem(accountStorageKey('pending'),'queued writes');
    const accepted=await offlineLibraryStore.previewCleanup({novel_id:1,kinds:['audio','translations']});
    expect((await offlineLibraryStore.cleanup(accepted)).removed_records).toBe(2);
    expect((await offlineLibraryStore.budget()).total_bytes).toBe(0);
    expect(localStorage.getItem(accountStorageKey('progress'))).toBe('private progress');expect(localStorage.getItem(accountStorageKey('pending'))).toBe('queued writes');
  });
  it('fences cleanup and budgets across account switches',async()=>{
    await offlineReaderStore.save(text());await offlineLibraryStore.setBudget(5000);
    const preview=await offlineLibraryStore.previewCleanup({kinds:['text']});activateAccountStorage(302);
    expect((await offlineLibraryStore.budget()).limit_bytes).toBeNull();expect((await offlineLibraryStore.inventory()).stories).toEqual([]);
    await expect(offlineLibraryStore.cleanup(preview)).rejects.toBeInstanceOf(OfflineCleanupChangedError);
    activateAccountStorage(301);expect(await offlineReaderStore.has(1,1)).toBe(true);
  });
  it('refuses non-owner audio mutations while another tab prepares the chapter',async()=>{
    await chapterAudioStore.save(1,1,blob('old'),audioManifest());
    const lease=(await browserAudioLeaseStore.claim(1,1,'narrating-tab',undefined,identity(1,1)))!;
    await chapterAudioJobStore.save(job(1,1),undefined,lease);
    await expect(chapterAudioStore.save(1,1,blob('server copy'),{...audioManifest(),job_id:5})).rejects.toBeInstanceOf(OfflineAudioBusyError);
    await expect(chapterAudioStore.remove(1,1)).rejects.toBeInstanceOf(OfflineAudioBusyError);
    await expect(chapterAudioJobStore.remove(1,1,undefined,undefined,identity(1,1))).rejects.toBeInstanceOf(OfflineAudioBusyError);
    expect(await readText((await chapterAudioStore.get(1,1))!)).toBe('old');
    expect((await browserAudioLeaseStore.get(1,1))?.token).toBe(lease.token);
  });
  it('rolls back an in-progress write immediately on account change',async()=>{
    await offlineReaderStore.save(text());const put=IDBObjectStore.prototype.put;let switched=false;
    vi.spyOn(IDBObjectStore.prototype,'put').mockImplementation(function(this:IDBObjectStore,value:unknown,key?:IDBValidKey){
      const request=key===undefined?put.call(this,value):put.call(this,value,key);
      if(this.name==='chapters' && !switched){switched=true;activateAccountStorage(302);}
      return request;
    });
    await expect(offlineReaderStore.save({...text(),content:'wrong late replacement'})).rejects.toMatchObject({name:'AbortError'});
    vi.restoreAllMocks();expect((await offlineLibraryStore.inventory()).stories).toEqual([]);
    activateAccountStorage(301);expect((await offlineReaderStore.get(1,1))?.content).toBe('Story 😀');
  });
  it('discards unprovable v4 numeric payloads and leases instead of guessing their chapter identity',async()=>{
    const name=accountDatabaseName();
    const database=await new Promise<IDBDatabase>((resolve,reject)=>{
      const request=indexedDB.open(name,4);request.onupgradeneeded=()=>{
        const chapters=request.result.createObjectStore('chapters',{keyPath:'cache_key'});chapters.createIndex('novel_id','novel_id');chapters.createIndex('cached_at','cached_at');
        for(const store of ['chapter_audio','chapter_audio_jobs','translations'])request.result.createObjectStore(store,{keyPath:'cache_key'});
        const segments=request.result.createObjectStore('chapter_audio_segments',{keyPath:'segment_key'});segments.createIndex('cache_key','cache_key');
      };request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
    });
    await new Promise<void>((resolve,reject)=>{
      const tx=database.transaction(['chapters','chapter_audio','chapter_audio_jobs'],'readwrite');
      tx.objectStore('chapters').put({...text(),cache_key:'1:1',cached_at:1});
      tx.objectStore('chapter_audio').put({cache_key:'2:4',audio:new NativeBlob(['legacy recording'])});
      tx.objectStore('chapter_audio_jobs').put({cache_key:'lease:2:4',novelId:2,chapterNumber:4,owner:'old-tab',token:'keep-token',databaseName:name,expiresAt:Date.now()+100000});
      tx.oncomplete=()=>resolve();tx.onabort=()=>reject(tx.error);
    });database.close();
    const inventory=await offlineLibraryStore.inventory();expect(inventory.stories).toEqual([]);
    expect(await browserAudioLeaseStore.get(2,4)).toBeNull();
    expect((await offlineLibraryStore.budget()).total_bytes).toBe(0);
    expect(await chapterAudioStore.get(2,4)).toBeNull();
  });
  it('inventories and reviews only tiny metadata after migration, never opening audio or document payload cursors',async()=>{
    const secret=text();secret.content='SECRET full story';secret.document.plain_text='SECRET full story';secret.document.blocks[0].html='<p>SECRET full story</p>';
    await offlineReaderStore.save(secret);await chapterAudioStore.save(1,1,blob('binary source'),audioManifest());await offlineTranslations.save(1,1,variant());
    const cursor=IDBObjectStore.prototype.openCursor;
    vi.spyOn(IDBObjectStore.prototype,'openCursor').mockImplementation(function(this:IDBObjectStore,query?:IDBValidKey|IDBKeyRange|null,direction?:IDBCursorDirection){
      if(!['offline_metadata','chapter_audio_jobs'].includes(this.name))throw new Error('Inventory scanned a large payload store');
      return cursor.call(this,query,direction);
    });
    const status=await offlineLibraryStore.inventory();expect(status.stories[0].chapters[0].audio.ready).toBe(true);
    const preview=await offlineLibraryStore.previewCleanup({kinds:['audio','text','translations']});expect(preview.records).toBe(3);
    await offlineLibraryStore.cleanup(preview);expect((await offlineLibraryStore.budget()).total_bytes).toBe(0);
  });
  it('backfills missing schema-6 summaries once without double-counting or rejecting existing data above a new limit',async()=>{
    await offlineReaderStore.save(text());await chapterAudioStore.save(1,1,blob('kept recording'),audioManifest());
    const before=await offlineLibraryStore.budget();await offlineLibraryStore.setBudget(0);
    const database=await openOfflineDatabase();
    await new Promise<void>((resolve,reject)=>{
      const tx=database.transaction('offline_metadata','readwrite'),store=tx.objectStore('offline_metadata');
      store.delete('summary_version');store.put({key:'total_bytes',value:99999});tx.oncomplete=()=>resolve();tx.onabort=()=>reject(tx.error);
    });database.close();
    const inventory=await offlineLibraryStore.inventory();expect(inventory.total_bytes).toBe(before.total_bytes);
    expect(await offlineLibraryStore.budget()).toMatchObject({total_bytes:before.total_bytes,limit_bytes:0,remaining_bytes:0});
    expect(await readText((await chapterAudioStore.get(1,1))!)).toBe('kept recording');
  });
  it('does not require randomUUID on an insecure LAN origin and closes connections on version change',async()=>{
    vi.spyOn(crypto,'randomUUID').mockImplementation(()=>{throw new Error('Unavailable');});
    await offlineReaderStore.save(text());const review=await offlineLibraryStore.previewCleanup({kinds:['text']});expect(review.review_token).toHaveLength(32);
    const database=await openOfflineDatabase();
    const upgrade=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open(accountDatabaseName(),7);request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});
    expect(()=>database.transaction('chapters','readonly')).toThrow();upgrade.close();
  });
});
