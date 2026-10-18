import 'fake-indexeddb/auto';
import { IDBFactory } from 'fake-indexeddb';
import { beforeEach, afterEach, expect, it, vi } from 'vitest';
import { accountDatabaseName, accountStorage, activateAccountStorage } from '../../src/services/accountStorage';
import { offlineReaderStore } from '../../src/services/offlineReaderStore';
import { openOfflineDatabase, OFFLINE_CONTENT_STORES } from '../../src/services/offlineStorageDatabase';
import { offlineLibraryStore } from '../../src/services/offlineLibraryStore';
import { PROGRESS_QUEUE_KEY, getQueuedProgress } from '../../src/services/progressSyncQueue';
const epoch = '11111111-1111-4111-8111-111111111111';
const keyA = '22222222-2222-4222-8222-222222222222', keyB = '33333333-3333-4333-8333-333333333333';
const chapter = (chapter_number: number, chapter_key = keyA, manifest_revision = '1') => ({ id: chapter_key === keyA ? 11 : 12, novel_id: 42, chapter_number, chapter_key, manifest_epoch: epoch, manifest_revision, title: 'Kept source', content: 'Identical text', document: { schema_version: 1 as const, content_version: 'identical-version', source_format: 'text' as const, plain_text: 'Identical text', blocks: [{ id: 'same-block', kind: 'p', html: '<p>Identical text</p>', text: 'Identical text' }] } });
beforeEach(() => { vi.stubGlobal('indexedDB', new IDBFactory()); activateAccountStorage(null); activateAccountStorage(412); localStorage.clear(); });
afterEach(() => { activateAccountStorage(null);vi.restoreAllMocks(); vi.unstubAllGlobals(); });
it('uses UUID primary keys and cannot confuse identical content at a reused zero address', async () => {
  await offlineReaderStore.save(chapter(0));
  expect((await offlineReaderStore.get(42, 0))?.chapter_key).toBe(keyA);
  await offlineReaderStore.save(chapter(0, keyB, '2'));
  expect((await offlineReaderStore.get(42, 0))?.chapter_key).toBe(keyB);
  expect(await offlineReaderStore.get(42, 0, chapter(0))).toBeNull();
  const rows = await offlineReaderStore.listAll();
  expect(rows.map(row => row.chapter_key).sort()).toEqual([keyA, keyB].sort());
  const db = await openOfflineDatabase();
  const keys = await new Promise<IDBValidKey[]>(resolve => { const request = db.transaction('chapters').objectStore('chapters').getAllKeys(); request.onsuccess = () => resolve(request.result); }); db.close();
  expect(keys).toEqual([`42:${keyA}`, `42:${keyB}`]);
});
it('renumbers the same identity without duplicating its text and ignores the old numeric alias', async () => {
  await offlineReaderStore.save(chapter(-2));
  await offlineReaderStore.save(chapter(7, keyA, '2'));
  expect(await offlineReaderStore.get(42, -2)).toBeNull();
  expect((await offlineReaderStore.get(42, 7))?.content).toBe('Identical text');
  expect(await offlineReaderStore.listAll()).toHaveLength(1);
});
it('rejects an old tab republishing a stale address atomically and keeps the newer mapping', async () => {
  await offlineReaderStore.save(chapter(7, keyB, '2'));
  await expect(offlineReaderStore.save(chapter(7))).rejects.toThrow('chapter list changed');
  expect((await offlineReaderStore.get(42, 7))?.chapter_key).toBe(keyB);
  expect(await offlineReaderStore.listAll()).toHaveLength(1);
});
it('does not bind one immutable chapter to two numeric addresses within the same manifest', async () => {
  await offlineReaderStore.save(chapter(-2));
  await expect(offlineReaderStore.save(chapter(0))).rejects.toThrow('chapter list changed');
  expect(await offlineReaderStore.get(42,0)).toBeNull();expect((await offlineReaderStore.get(42,-2))?.chapter_key).toBe(keyA);
});
it('rejects numeric-only new cache writes rather than inventing a chapter identity', async () => {
  await expect(offlineReaderStore.save({ id: 1, novel_id: 42, chapter_number: 0, title: 'Old client', content: 'Text' })).rejects.toThrow('chapter list changed');
  expect(await offlineReaderStore.listAll()).toHaveLength(0);
});
it('clears unprovable schema5 payloads and leases, preserves the budget and retains blocked unsynchronized progress', async () => {
  await new Promise<void>((resolve, reject) => {
    const request = indexedDB.open(accountDatabaseName(), 5);
    request.onupgradeneeded = () => {
      const db = request.result;
      const chapters = db.createObjectStore('chapters', { keyPath: 'cache_key' }); chapters.createIndex('cached_at', 'cached_at'); chapters.createIndex('novel_id', 'novel_id');
      for (const name of ['chapter_audio', 'chapter_audio_jobs', 'translations']) db.createObjectStore(name, { keyPath: 'cache_key' });
      const segments = db.createObjectStore('chapter_audio_segments', { keyPath: 'segment_key' }); segments.createIndex('cache_key', 'cache_key');
      const metadata = db.createObjectStore('offline_metadata', { keyPath: 'key' });
      metadata.put({ key: 'settings', limit_bytes: 123456 }); metadata.put({ key: 'summary_version', value: 1 }); metadata.put({ key: 'total_bytes', value: 999 });
      for (const name of OFFLINE_CONTENT_STORES) request.transaction!.objectStore(name).put(name === 'chapter_audio_segments' ? { segment_key: '42:0:0', cache_key: '42:0' } : { cache_key: name === 'chapter_audio_jobs' ? 'lease:42:0' : '42:0', novel_id: 42, chapter_number: 0, audio: 'old private bytes', content: 'Unknown original' });
    };
    request.onsuccess = () => { request.result.close(); resolve(); }; request.onerror = () => reject(request.error);
  });
  const pending = { novelId: 42, chapter: 0, position: 20, percent: 40, ts: 1, operationId: 'keep-original' };
  accountStorage.setItem(PROGRESS_QUEUE_KEY, JSON.stringify([pending]));
  const db = await openOfflineDatabase();
  for (const name of OFFLINE_CONTENT_STORES) {
    const count = await new Promise<number>(resolve => { const request = db.transaction(name).objectStore(name).count(); request.onsuccess = () => resolve(request.result); }); expect(count).toBe(0);
  }
  db.close(); expect(await offlineLibraryStore.budget()).toMatchObject({ total_bytes: 0, limit_bytes: 123456 });
  expect(getQueuedProgress()).toEqual([{ ...pending, blocked: true, conflictCode: 'chapter_identity_required' }]);
});
it('fences a recording read when the account changes between address resolution and payload lookup', async () => {
  const { chapterAudioStore } = await import('../../src/services/offlineReaderStore');
  const { Blob: NativeBlob } = await import('node:buffer');
  const manifest = { ...chapter(0), source_version: 'identical-version', rendition: 'original' as const, include_author_notes: false, precision: 'unavailable' as const, duration_seconds: 1, segments: [] };
  await chapterAudioStore.save(42,0,new NativeBlob(['account A']) as unknown as Blob,manifest);
  activateAccountStorage(413);await chapterAudioStore.save(42,0,new NativeBlob(['account B']) as unknown as Blob,manifest);
  activateAccountStorage(412);
  const transaction=IDBDatabase.prototype.transaction;let switched=false;
  vi.spyOn(IDBDatabase.prototype,'transaction').mockImplementation(function(this:IDBDatabase,names:string|string[],mode?:IDBTransactionMode,options?:IDBTransactionOptions){
    const tx=transaction.call(this,names,mode,options);
    if(!switched && mode==='readonly' && [...(typeof names==='string'?[names]:names)].includes('chapters')){
      switched=true;tx.addEventListener('complete',()=>queueMicrotask(()=>activateAccountStorage(413)));
    }
    return tx;
  });
  await expect(chapterAudioStore.recording(42,0)).rejects.toMatchObject({name:'AbortError'});
  vi.restoreAllMocks();expect(switched).toBe(true);
  const current=await chapterAudioStore.recording(42,0);expect(current).not.toBeNull();
  const text=await new Promise<string>((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result));reader.onerror=()=>reject(reader.error);reader.readAsText(current!.audio);});expect(text).toBe('account B');
});
