import {act,fireEvent,render,screen,waitFor} from '@testing-library/react';
import {MemoryRouter} from 'react-router-dom';
import {beforeEach,describe,expect,it,vi} from 'vitest';
import {AxiosError} from 'axios';
import StoryChapterChanges from './StoryChapterChanges';
import {chapterManifestService,loadManifestIntent,type ManifestReview,type ManifestState} from '../../services/chapterManifestService';
import {chapterService} from '../../services/chapterService';
import {activateAccountStorage} from '../../services/accountStorage';
import {enqueueProgress,getQueuedProgress} from '../../services/progressSyncQueue';
import {fixtureChapterIdentity as identity} from '../../../tests/fixtures/chapterIdentity';
vi.mock('../../services/chapterManifestService',async original=>({...await original<typeof import('../../services/chapterManifestService')>(),chapterManifestService:{state:vi.fn(),history:vi.fn(),preview:vi.fn(),review:vi.fn(),items:vi.fn(),remote:vi.fn(),execute:vi.fn()}}));
vi.mock('../../services/chapterService',()=>({chapterService:{getReadingProgress:vi.fn(),acceptReadingRun:vi.fn()}}));
const local:ManifestState={novel_id:42,...identity(42,-2),identity_required:false,total:2,items:[-2,0].map((number,index)=>({...identity(42,number),id:index+1,chapter_number:number,title:`Original ${number}`,source_version:'original',archived:false})),next_cursor:null,has_more:false};
const review=(changes:Partial<ManifestReview>={}):ManifestReview=>({review_id:12,revision:1,status:'preview',novel_id:42,...identity(42,-2),reviewed_manifest_epoch:local.manifest_epoch,reviewed_manifest_revision:'1',review_token:'reviewed-plan',expires_at:'2030-01-01T00:00:00Z',remote:{source:{site:"royalroad",story_id:4321,source_url:"https://www.royalroad.com/fiction/4321/reviewed-fixture"},manifest_key:'44444444-4444-4444-8444-444444444444',revision:'1',fingerprint:'remote-fingerprint',total:2,identity_kind:'stable_source_id',complete:true,source_complete:false,deletion_authoritative:false},counts:{source_chapters:2,local_chapters:2,mapped:2,new:0,renumbered:2,unmapped:0,inferred_anchors:0},items:{review_id:12,items:[{chapter_key:identity(42,-2).chapter_key,metadata_chapter_key:identity(42,3).chapter_key,title:'Original -2',from_number:-2,to_number:3,decision:'bound',requires_content_review:false,inferred_anchor_count:0,candidates:[],candidates_truncated:false}],total:2,offset:0,limit:1,has_more:true},unmapped:{review_id:12,items:[],total:0,offset:0,limit:50,has_more:false},anchors:[],blocked_reasons:[],can_apply:true,can_undo:false,undo_blocked_reason:null,...changes});
const applied=vi.fn();
async function mount(){const view=render(<MemoryRouter><StoryChapterChanges novelId={42} libraryId={1} onApplied={applied}/></MemoryRouter>);const details=view.container.querySelector('details')!;act(()=>{details.open=true;fireEvent(details,new Event('toggle'));});await screen.findByText(/2 local chapters/);return view;}
async function preview(){fireEvent.click(screen.getByRole('button',{name:'Review source chapter changes'}));await screen.findByRole('region',{name:'Chapter address review'});}
async function confirmApply(){fireEvent.click(screen.getByRole('button',{name:'Apply reviewed chapter changes'}));fireEvent.click(await screen.findByRole('button',{name:'Confirm chapter changes'}));}
beforeEach(()=>{vi.clearAllMocks();localStorage.clear();activateAccountStorage(null);activateAccountStorage(55);vi.mocked(chapterManifestService.state).mockResolvedValue(local);vi.mocked(chapterManifestService.history).mockResolvedValue({items:[],total:0,offset:0,limit:10,has_more:false});vi.mocked(chapterManifestService.preview).mockResolvedValue(review());vi.mocked(chapterManifestService.review).mockResolvedValue(review());vi.mocked(chapterManifestService.execute).mockResolvedValue({review_id:12,revision:2,status:'applied',novel_id:42,manifest_epoch:local.manifest_epoch,manifest_revision:'2'});vi.mocked(chapterService.getReadingProgress).mockResolvedValue({novel_id:42,...identity(42,3),chapter_number:3,position:0,percent:40,revision:2,reading_run_key:'55555555-5555-4555-8555-555555555555',updated_at:'2026-10-16T00:00:00Z'});});
describe('reviewed chapter address changes',()=>{
 it('loads local observations only on disclosure and previews only after an explicit action',async()=>{
  const initial=render(<MemoryRouter><StoryChapterChanges novelId={42} libraryId={1} onApplied={applied}/></MemoryRouter>);expect(chapterManifestService.state).not.toHaveBeenCalled();initial.unmount();await mount();
  expect(chapterManifestService.preview).not.toHaveBeenCalled();await preview();expect(chapterManifestService.preview).toHaveBeenCalledWith(42,expect.objectContaining({expected_manifest_epoch:local.manifest_epoch,expected_manifest_revision:'1',mappings:[]}));
  expect(screen.getByText(/cannot prove that source chapters were removed/)).toBeInTheDocument();expect(screen.getByText('Chapter -2 → Chapter 3 · Same verified chapter')).toBeInTheDocument();expect(chapterManifestService.execute).not.toHaveBeenCalled();
  expect(screen.getByText('Reviewed source: royalroad · Story 4321')).toBeInTheDocument();expect(screen.getByText('https://www.royalroad.com/fiction/4321/reviewed-fixture')).toBeInTheDocument();
 });
 it('requires a final confirmation, then uses authoritative detail instead of a historical successful receipt',async()=>{
  await mount();await preview();fireEvent.click(screen.getByRole('button',{name:'Apply reviewed chapter changes'}));await screen.findByRole('dialog',{name:'Apply these reviewed chapter addresses?'});expect(chapterManifestService.execute).not.toHaveBeenCalled();
  vi.mocked(chapterManifestService.review).mockResolvedValue(review({status:'undone',can_apply:false,revision:3,manifest_revision:'3'}));
  fireEvent.click(screen.getByRole('button',{name:'Confirm chapter changes'}));await screen.findByText('The chapter addresses were restored. Their identity revision continues forward.');
  expect(chapterManifestService.execute).toHaveBeenCalledWith(42,{action:'apply',review_id:12,body:{review_token:'reviewed-plan',operation_id:expect.any(String)}});expect(chapterService.acceptReadingRun).toHaveBeenCalledOnce();expect(loadManifestIntent(42)).toBeNull();
 });
 it('recovers a lost acknowledgement after reload using the exact same persisted operation',async()=>{
  vi.mocked(chapterManifestService.execute).mockRejectedValueOnce(new AxiosError('Network','ERR_NETWORK'));
  const view=await mount();await preview();await confirmApply();await screen.findByText(/A previous chapter change has not been confirmed/);const intent=loadManifestIntent(42);expect(intent?.body.operation_id).toBeTruthy();view.unmount();await mount();
  vi.mocked(chapterManifestService.review).mockResolvedValue(review({status:'undone',can_apply:false,revision:3}));fireEvent.click(screen.getByRole('button',{name:'Check pending chapter action'}));await screen.findByText('The chapter addresses were restored. Their identity revision continues forward.');
  expect(vi.mocked(chapterManifestService.execute).mock.calls[1]).toEqual(vi.mocked(chapterManifestService.execute).mock.calls[0]);expect(loadManifestIntent(42)).toBeNull();
 });
 it('retains the operation if the server acknowledged it but the authoritative refresh fails',async()=>{
  await mount();await preview();fireEvent.click(screen.getByRole('button',{name:'Apply reviewed chapter changes'}));await screen.findByRole('button',{name:'Confirm chapter changes'});
  vi.mocked(chapterManifestService.review).mockRejectedValueOnce(new AxiosError('Unavailable','ERR_BAD_RESPONSE',undefined,undefined,{status:409,statusText:'Conflict',headers:{},config:{} as never,data:{detail:'Refresh needs review'}}));
  fireEvent.click(screen.getByRole('button',{name:'Confirm chapter changes'}));await screen.findByText('Refresh needs review');expect(loadManifestIntent(42)).not.toBeNull();expect(screen.getByRole('button',{name:'Check pending chapter action'})).toBeInTheDocument();
 });
 it('requires another preview after an individual match and inferred checkpoints are reviewed',async()=>{
  const row={...review().items.items[0],decision:'needs_mapping' as const,inferred_anchor_count:1};vi.mocked(chapterManifestService.preview).mockResolvedValue(review({can_apply:false,items:{...review().items,items:[row]}}));
  vi.mocked(chapterManifestService.remote).mockResolvedValue({items:[{metadata_chapter_key:identity(42,7).chapter_key,chapter_number:7,title:'Recognized source chapter',identity_kind:'unknown'}],total:1,offset:0,limit:20,has_more:false});
  await mount();await preview();fireEvent.click(screen.getByRole('button',{name:'Choose source match for chapter -2'}));fireEvent.click(await screen.findByRole('button',{name:'Match to chapter 7'}));
  fireEvent.click(screen.getByRole('checkbox',{name:'I reviewed inferred checkpoints for chapter -2'}));expect(screen.getByRole('button',{name:'Apply reviewed chapter changes'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Preview updated chapter choices'}));await waitFor(()=>expect(chapterManifestService.preview).toHaveBeenLastCalledWith(42,expect.objectContaining({mappings:[{chapter_key:identity(42,-2).chapter_key,metadata_chapter_key:identity(42,7).chapter_key,confirm_inferred_anchors:true}]})));
  expect(chapterManifestService.execute).not.toHaveBeenCalled();expect(screen.queryByText('A different source match is selected. Preview the updated choices before applying.')).toBeNull();
 });
 it('reviews archived originals explicitly without replacing their immutable identity',async()=>{
  const archived={...review().items.items[0],archived:true,decision:'unlisted' as const,metadata_chapter_key:null,to_number:null,title:'Preserved original'};
  vi.mocked(chapterManifestService.preview).mockResolvedValue(review({can_apply:false,counts:{...review().counts,archived_chapters:1,restored_chapters:0},items:{...review().items,items:[archived]}}));
  vi.mocked(chapterManifestService.remote).mockResolvedValue({items:[{metadata_chapter_key:identity(42,7).chapter_key,chapter_number:7,title:'Returning source chapter',identity_kind:'unknown'}],total:1,offset:0,limit:20,has_more:false});
  await mount();await preview();
  expect(screen.getByText(/1 preserved archived originals · 0 selected for restoration/)).toBeInTheDocument();
  expect(screen.getByText(/Archived originals without a selected source match stay archived/)).toBeInTheDocument();
  expect(screen.getByText(/Matching it restores this same chapter/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'Choose source match for chapter -2'}));
  fireEvent.click(await screen.findByRole('button',{name:'Match to chapter 7'}));
  expect(chapterManifestService.execute).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button',{name:'Preview updated chapter choices'}));
  await waitFor(()=>expect(chapterManifestService.preview).toHaveBeenLastCalledWith(42,expect.objectContaining({mappings:[{chapter_key:archived.chapter_key,metadata_chapter_key:identity(42,7).chapter_key,confirm_inferred_anchors:false}]})));
 });
 it('reviews archival explicitly and resets relocated saved places only after preview',async()=>{
  const oldKey=identity(42,-2).chapter_key,nextKey=identity(42,0).chapter_key;
  const row={...review().items.items[0],metadata_chapter_key:null,to_number:null,decision:'unlisted' as const,can_archive:true,archive_blocked_reason:null};
  const before=review({can_apply:false,remote:{...review().remote,source_complete:true,deletion_authoritative:true},items:{...review().items,items:[row]},anchors:[{kind:'current',chapter_key:oldKey,chapter_number:-2,percent:80,identity_inferred:false,resolved:true,content_version:'original'}]});
  vi.mocked(chapterManifestService.preview).mockResolvedValueOnce(before).mockResolvedValueOnce({...before,counts:{...before.counts,newly_archived_chapters:1},items:{...before.items,items:[{...row,decision:'archive'}]},anchors:[{kind:'current',chapter_key:nextKey,chapter_number:7,percent:0,identity_inferred:true,resolved:true,content_version:null,relocated:true,previous_chapter_key:oldKey,previous_chapter_number:-2,previous_percent:80}]});
  await mount();await preview();expect(screen.getByRole('checkbox',{name:'Preserve chapter -2 as archived original'})).not.toBeChecked();
  fireEvent.click(screen.getByRole('checkbox',{name:'Preserve chapter -2 as archived original'}));
  expect(screen.getByRole('button',{name:'Apply reviewed chapter changes'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Choose retained chapter for current place'}));
  expect(await screen.findByRole('button',{name:'Use original chapter -2'})).toBeDisabled();
  fireEvent.click(screen.getByRole('button',{name:'Use original chapter 0'}));
  fireEvent.click(screen.getByRole('button',{name:'Preview updated chapter choices'}));
  await waitFor(()=>expect(chapterManifestService.preview).toHaveBeenLastCalledWith(42,expect.objectContaining({archive_chapter_keys:[oldKey],resolve_current_chapter_key:nextKey,mappings:[]})));
  expect(await screen.findByText('Current saved place: Chapter -2 · 80% → Chapter 7 · 0%')).toBeInTheDocument();
  expect(screen.getByText(/pixel, block, translation and content-version locators are cleared/)).toBeInTheDocument();expect(screen.getByText(/1 originals selected for archival/)).toBeInTheDocument();expect(chapterManifestService.execute).not.toHaveBeenCalled();
 });
 it('does not offer archival without explicit server authority, including still-present lineage',async()=>{
  const row={...review().items.items[0],can_archive:false,archive_blocked_reason:'This chapter is still present in the accepted source lineage.'};
  vi.mocked(chapterManifestService.preview).mockResolvedValue(review({items:{...review().items,items:[row]}}));await mount();await preview();
  expect(screen.queryByRole('checkbox',{name:'Preserve chapter -2 as archived original'})).toBeNull();expect(screen.getByText('Archival unavailable: This chapter is still present in the accepted source lineage.')).toBeInTheDocument();
 });
 it('preserves pending positions and blocks applying or undoing a list while they remain unsynchronized',async()=>{
  enqueueProgress({novelId:42,chapter:-2,chapterIdentity:identity(42,-2),position:20,percent:42,ts:1});await mount();await preview();
  expect(screen.getByText(/1 unsynchronized positions are retained/)).toBeInTheDocument();expect(screen.getByRole('button',{name:'Apply reviewed chapter changes'})).toBeDisabled();expect(screen.getByRole('button',{name:'Download unsynchronized positions'})).toBeInTheDocument();expect(getQueuedProgress()).toHaveLength(1);expect(chapterManifestService.execute).not.toHaveBeenCalled();
 });
 it('pages review entries independently and never loads the full source manifest to find a match',async()=>{
  vi.mocked(chapterManifestService.items).mockResolvedValue({...review().items,offset:1,has_more:false,items:[{...review().items.items[0],title:'Later reviewed chapter',from_number:0,to_number:7}]});await mount();await preview();
  fireEvent.click(screen.getByRole('button',{name:'Next changes'}));await screen.findByText('Later reviewed chapter');expect(chapterManifestService.items).toHaveBeenCalledWith(42,12,'items',1);expect(chapterManifestService.remote).not.toHaveBeenCalled();
 });
 it('discards a private delayed preview after an account switch',async()=>{
  let finish!:(value:ManifestReview)=>void;vi.mocked(chapterManifestService.preview).mockReturnValueOnce(new Promise(resolve=>{finish=resolve;}));await mount();fireEvent.click(screen.getByRole('button',{name:'Review source chapter changes'}));act(()=>activateAccountStorage(56));
  await act(async()=>finish(review({items:{...review().items,items:[{...review().items.items[0],title:'Previous account private chapter'}]}})));expect(screen.queryByText('Previous account private chapter')).not.toBeInTheDocument();expect(chapterManifestService.execute).not.toHaveBeenCalled();
 });
});
