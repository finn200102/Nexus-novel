import { beforeEach, expect, it, vi } from 'vitest';
import apiClient from './apiClient';
import { chapterService } from './chapterService';
import { accountStorage, activateAccountStorage, storageGeneration } from './accountStorage';
import { getQueuedProgress, flushProgressQueue, PROGRESS_QUEUE_KEY } from './progressSyncQueue';
import { observeChapterIdentity, type ChapterIdentity } from './chapterIdentity';
vi.mock('./apiClient', () => ({ default: { get: vi.fn(), put: vi.fn() } }));
vi.mock('./serverReachability', () => ({ markServerReachable: vi.fn(), markServerUnreachable: vi.fn() }));
vi.mock('./progressSyncQueue', async () => ({ ...await vi.importActual<typeof import('./progressSyncQueue')>('./progressSyncQueue'), installProgressSync: vi.fn(() => () => undefined) }));
const identity: ChapterIdentity = { chapter_key: '11111111-1111-4111-8111-111111111111', manifest_epoch: '22222222-2222-4222-8222-222222222222', manifest_revision: '9007199254740993' };
const run = '33333333-3333-4333-8333-333333333333';
let novelId = 8200;
beforeEach(() => { vi.clearAllMocks(); localStorage.clear(); activateAccountStorage(null); activateAccountStorage(1); novelId++; });
it('sends captured chapter identity separately from a historical locator content version', async () => {
  vi.mocked(apiClient.put).mockResolvedValueOnce({ data: { chapter_number: -2, position: 10, percent: 40, revision: 1, reading_run_key: run, ...identity } });
  await chapterService.updateReadingProgress(novelId, -2, 10, 40, { readingRunKey: run, chapterIdentity: identity, expectedContentVersion: 'current-original', contentVersion: 'historical-anchor', blockId: 'kept-block' });
  expect(apiClient.put).toHaveBeenCalledWith(`/chapter/progress/${novelId}`, expect.objectContaining({ chapter_number: -2, expected_chapter_key: identity.chapter_key, expected_manifest_epoch: identity.manifest_epoch, expected_manifest_revision: '9007199254740993', expected_content_version: 'current-original', content_version: 'historical-anchor', block_id: 'kept-block' }));
});
it('retains unknown numeric legacy saves blocked without sending or binding them to the replacement chapter', async () => {
  const old = { novelId, chapter: 0, position: 19, percent: 71, ts: 123, operationId: 'lost-old-save', contentVersion: 'same-text', textQuote: 'Original quote' };
  accountStorage.setItem(PROGRESS_QUEUE_KEY, JSON.stringify([old]));
  const send = vi.fn(); expect(await flushProgressQueue(send)).toBe(0); expect(send).not.toHaveBeenCalled();
  expect(getQueuedProgress()).toEqual([{ ...old, blocked: true, conflictCode: 'chapter_identity_required' }]);
  vi.mocked(apiClient.get).mockResolvedValueOnce({ data: { chapter_number: 0, position: 0, percent: 0, revision: 4, reading_run_key: null, ...identity } });
  await expect(chapterService.resolveProgressConflict(novelId, 'device')).rejects.toThrow('no verified chapter identity');
  expect(apiClient.put).not.toHaveBeenCalled(); expect(getQueuedProgress()[0]).toMatchObject({ operationId: 'lost-old-save', textQuote: 'Original quote' });
});
it('does not send a captured old topology even after the same numeric chapter is occupied again', async () => {
  observeChapterIdentity(novelId, identity, storageGeneration());
  observeChapterIdentity(novelId, { ...identity, chapter_key: '44444444-4444-4444-8444-444444444444', manifest_revision: '9007199254740994' }, storageGeneration());
  expect(await chapterService.updateReadingProgress(novelId, 0, 25, 60, { readingRunKey: run, chapterIdentity: identity, expectedContentVersion: 'same-text', contentVersion: 'same-text' })).toBeNull();
  expect(apiClient.put).not.toHaveBeenCalled();
  expect(getQueuedProgress()).toEqual([expect.objectContaining({ chapterIdentity: identity, chapter: 0, blocked: true, conflictCode: 'chapter_manifest_changed' })]);
});
it('guards retained originals by immutable chapter key while keeping their historical body version',async()=>{
 vi.mocked(apiClient.get).mockResolvedValueOnce({data:{...identity,novel_id:novelId,chapter_number:0,current_version:'current',versions:[],next_cursor:null}});
 await chapterService.getChapterVersions(novelId,0,undefined,identity.chapter_key);
 expect(apiClient.get).toHaveBeenLastCalledWith(`/chapter/versions/${novelId}/0`,{params:{cursor:undefined,expected_chapter_key:identity.chapter_key}});
 vi.mocked(apiClient.get).mockResolvedValueOnce({data:{...identity,id:1,novel_id:novelId,chapter_number:0,title:'Old original',content:'old original',source_version:'historical',current_content_version:'current'}});
 const saved=await chapterService.getChapterVersion(novelId,0,'historical',identity.chapter_key);
 expect(apiClient.get).toHaveBeenLastCalledWith(`/chapter/versions/${novelId}/0/historical`,{params:{expected_chapter_key:identity.chapter_key}});
 expect(saved).toMatchObject({source_version:'historical',current_content_version:'current'});
 vi.mocked(apiClient.get).mockResolvedValueOnce({data:{...identity,chapter_key:'44444444-4444-4444-8444-444444444444',id:2,novel_id:novelId,chapter_number:0,content:'Replacement'}});
 await expect(chapterService.getChapterVersion(novelId,0,'historical',identity.chapter_key)).rejects.toThrow();
});
it('sends the chapter identity captured by an explicit download selection',async()=>{
 vi.mocked(apiClient.get).mockResolvedValueOnce({data:{...identity,id:1,novel_id:novelId,chapter_number:0}});
 await chapterService.downloadChapter(1,novelId,0,identity,'selected-original');
 expect(apiClient.get).toHaveBeenLastCalledWith(`/chapter/download/1/${novelId}/0`,{params:{expected_chapter_key:identity.chapter_key,expected_manifest_epoch:identity.manifest_epoch,expected_manifest_revision:identity.manifest_revision,expected_content_version:'selected-original'}});
});
it('does not adopt a historic replay acknowledgement after a newer manifest even when its progress revision is larger',async()=>{
 const current={...identity,manifest_revision:'9007199254740994'};let acknowledge!:(value:unknown)=>void;
 vi.mocked(apiClient.put).mockImplementationOnce(()=>new Promise(resolve=>{acknowledge=resolve;}));
 const saving=chapterService.updateReadingProgress(novelId,0,10,40,{chapterIdentity:identity,readingRunKey:run});
 await vi.waitFor(()=>expect(apiClient.put).toHaveBeenCalledOnce());observeChapterIdentity(novelId,current,storageGeneration());
 const progress={...current,chapter_number:7,position:19,percent:50,revision:2,reading_run_key:run};chapterService.acceptReadingRun(novelId,progress);
 vi.mocked(apiClient.get).mockResolvedValueOnce({data:progress});acknowledge({data:{...identity,chapter_number:0,position:10,percent:40,revision:100,reading_run_key:run}});
 expect(await saving).toEqual(progress);expect(chapterService.getCachedReadingProgress(novelId)).toMatchObject({chapter_number:7,manifest_revision:current.manifest_revision,revision:2});expect(getQueuedProgress()).toEqual([]);
});
