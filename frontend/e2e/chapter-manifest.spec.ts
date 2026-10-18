import {mkdir} from 'node:fs/promises';
import type {Page} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {test,expect} from './fixtures';
import {fixtureChapterIdentity as identity} from '../tests/fixtures/chapterIdentity';
import type {ManifestPreviewInput,ManifestReview} from '../src/services/chapterManifestService';
const novelId=11,path='/library/1/novels/11?tab=chapters',header=identity(novelId,-2);
function plan():ManifestReview{return {review_id:12,revision:1,novel_id:novelId,...header,reviewed_manifest_epoch:header.manifest_epoch,reviewed_manifest_revision:'1',review_token:'native-reviewed-plan',status:'preview',expires_at:'2030-01-01T00:00:00Z',remote:{source:{site:"royalroad",story_id:4321,source_url:"https://www.royalroad.com/fiction/4321/reviewed-fixture"},manifest_key:identity(99,1).manifest_epoch,revision:'1',fingerprint:'fixture',total:2,identity_kind:'unknown',complete:true,source_complete:false,deletion_authoritative:false},counts:{source_chapters:2,local_chapters:2,mapped:2,new:0,renumbered:2,unmapped:0,inferred_anchors:0},items:{review_id:12,items:[{chapter_key:header.chapter_key,metadata_chapter_key:identity(99,3).chapter_key,title:'Prologue with preserved original identity',from_number:-2,to_number:3,decision:'bound',requires_content_review:false,inferred_anchor_count:0,candidates:[],candidates_truncated:false}],total:2,offset:0,limit:1,has_more:true},unmapped:{review_id:12,items:[],total:0,offset:0,limit:1,has_more:false},anchors:[],blocked_reasons:[],can_apply:true,can_undo:false,undo_blocked_reason:null};}
async function setup(page:Page,{blocked=false,lostAck=false,archived=false,archiveAbsent=false}={}){
 let review=plan(),revision='1',lost=false;const previews:ManifestPreviewInput[]=[],actions:unknown[]=[];
 const state=()=>({novel_id:novelId,...header,manifest_revision:revision,identity_required:revision!=='1',total:2,items:[-2,0].map((n,i)=>({...identity(novelId,n),manifest_revision:revision,id:i+1,chapter_number:n,title:`Original ${n}`,source_version:'original',archived:false})),next_cursor:null,has_more:false});
 await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
  const request=route.request(),url=new URL(request.url()),p=url.pathname.replace(/^\/api(?=\/)/,'');
  if(p===`/chapter/novel/${novelId}/manifest-state`)return route.fulfill({json:state()});
  const base=`/chapter/novel/${novelId}/manifest`;
  if(p===base+'/preview'){
   const input=request.postDataJSON() as ManifestPreviewInput;previews.push(input);review={...plan(),can_apply:!blocked,blocked_reasons:blocked?[{code:'topology_guards_incomplete',message:'Chapter identity safety checks are not complete. Applying changes is unavailable.'}]:[]};if(archived){const mapped=input.mappings.some(row=>row.chapter_key===header.chapter_key);review.counts={...review.counts,archived_chapters:1,restored_chapters:mapped?1:0};review.items.items=review.items.items.map(row=>({...row,archived:true,decision:mapped?'explicit':'unlisted',metadata_chapter_key:mapped?identity(99,7).chapter_key:null,to_number:mapped?7:null}));review.can_apply=mapped;}if(archiveAbsent){const selected=input.archive_chapter_keys?.includes(header.chapter_key)??false;const relocated=selected&&input.resolve_current_chapter_key===identity(novelId,0).chapter_key;review.remote={...review.remote,total:1,source_complete:true,deletion_authoritative:true};review.items.items=review.items.items.map(row=>({...row,metadata_chapter_key:null,to_number:null,decision:selected?'archive':'unlisted',can_archive:true,archive_blocked_reason:null}));review.counts={...review.counts,source_chapters:1,mapped:1,renumbered:1,unmapped:selected?0:1,newly_archived_chapters:selected?1:0};review.anchors=[{kind:'current',chapter_key:relocated?identity(novelId,0).chapter_key:header.chapter_key,chapter_number:relocated?7:-2,percent:relocated?0:80,identity_inferred:relocated,resolved:!selected||relocated,content_version:relocated?null:'original',relocated,previous_chapter_key:relocated?header.chapter_key:null,previous_chapter_number:relocated?-2:null,previous_percent:relocated?80:null}];review.can_apply=relocated;review.blocked_reasons=selected&&!relocated?[{code:'current_anchor_archive_resolution_required',message:'Choose a retained chapter before archiving the current original.'}]:[];}return route.fulfill({json:review});
  }
  if(p===base+'/reviews')return route.fulfill({json:{items:revision==='1'?[]:[review],total:revision==='1'?0:1,offset:0,limit:10,has_more:false}});
  if(p===base+'/reviews/12')return route.fulfill({json:review});
  if(p===base+'/reviews/12/items')return route.fulfill({json:{...review.items,offset:1,has_more:false,items:[{...review.items.items[0],title:'Actual chapter zero',from_number:0,to_number:7}]}});
  if(p===base+'/reviews/12/remote')return route.fulfill({json:{items:[{metadata_chapter_key:identity(99,7).chapter_key,chapter_number:7,title:'Explicit matching chapter',identity_kind:'unknown'}],total:1,offset:0,limit:20,has_more:false}});
  if(p===base+'/apply'||p===base+'/reviews/12/undo'){
   actions.push(request.postDataJSON());revision=p.endsWith('undo')?'3':'2';review={...review,status:p.endsWith('undo')?'undone':'applied',revision:Number(revision),manifest_revision:revision,can_apply:false,can_undo:revision==='2'};
   if(lostAck&&!lost){lost=true;return route.abort('failed');}return route.fulfill({json:{review_id:12,status:review.status}});
  }
  if(p===`/chapter/progress/${novelId}`)return route.fulfill({json:null});
  return route.fallback();
 });
 await page.goto(path);await expect.poll(()=>page.evaluate(()=>JSON.parse(localStorage.getItem('nexus-signed-in')||'null')?.id)).toBe(7);
 await page.getByText('Review chapter list changes',{exact:true}).click();const region=page.getByRole('region',{name:'Reviewed chapter list changes',exact:true});await expect(region.getByText(/2 local chapters/)).toBeVisible();
 return {region,previews,actions};
}
test('chapter addresses require explicit review and recover the same pending operation before undo',async({signedInPage:page})=>{
 const data=await setup(page,{lostAck:true});expect(data.previews).toHaveLength(0);await data.region.getByRole('button',{name:'Review source chapter changes',exact:true}).click();
 await expect(data.region.getByText('Chapter -2 → Chapter 3 · Same verified chapter')).toBeVisible();
 await data.region.getByRole('button',{name:'Apply reviewed chapter changes'}).click();await page.getByRole('button',{name:'Confirm chapter changes'}).click();
 await expect(data.region.getByRole('button',{name:'Check pending chapter action'})).toBeVisible();expect(data.actions).toHaveLength(1);await page.reload();await page.getByText('Review chapter list changes',{exact:true}).click();
 await page.getByRole('button',{name:'Check pending chapter action'}).click();await expect(page.getByText('The reviewed chapter addresses are now active.')).toBeVisible();expect(data.actions[1]).toEqual(data.actions[0]);
 await page.getByRole('button',{name:'Review undo',exact:true}).click();await page.getByRole('button',{name:'Confirm chapter undo',exact:true}).click();await expect(page.getByText('The chapter addresses were restored. Their identity revision continues forward.')).toBeVisible();expect(data.actions).toHaveLength(3);
});
test('manual choices invalidate the review, page exact signed labels and fit the phone with accessible controls',async({signedInPage:page},info)=>{
 const data=await setup(page);await data.region.getByRole('button',{name:'Review source chapter changes',exact:true}).click();await data.region.getByRole('button',{name:'Choose source match for chapter -2'}).click();await page.getByRole('button',{name:'Match to chapter 7',exact:true}).click();
 await expect(data.region.getByRole('button',{name:'Apply reviewed chapter changes'})).toBeDisabled();await data.region.getByRole('button',{name:'Preview updated chapter choices'}).click();expect(data.previews[1].mappings).toEqual([{chapter_key:header.chapter_key,metadata_chapter_key:identity(99,7).chapter_key,confirm_inferred_anchors:false}]);
 await data.region.getByRole('button',{name:'Next changes'}).click();await expect(data.region.getByText('Chapter 0 → Chapter 7 · Same verified chapter')).toBeVisible();
 await mkdir('/tmp/nexus-manifest-ui-review',{recursive:true});await page.screenshot({path:`/tmp/nexus-manifest-ui-review/${info.project.name}-desktop.png`,fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.mouse.move(0,0);await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);
 await page.addStyleTag({content:'*,*::before,*::after {animation:none!important;transition:none!important}'});const axe=await new AxeBuilder({page}).include('.chapter-changes').analyze();expect(axe.violations).toEqual([]);
 await mkdir('/tmp/nexus-manifest-ui-review',{recursive:true});await page.screenshot({path:`/tmp/nexus-manifest-ui-review/${info.project.name}-phone.png`,fullPage:true});expect(data.actions).toHaveLength(0);
});
test('server safety blockers cannot be bypassed by a generic review confirmation',async({signedInPage:page})=>{
 const data=await setup(page,{blocked:true});await data.region.getByRole('button',{name:'Review source chapter changes',exact:true}).click();await expect(data.region.getByText('Chapter identity safety checks are not complete. Applying changes is unavailable.')).toBeVisible();await expect(data.region.getByRole('button',{name:'Apply reviewed chapter changes'})).toBeDisabled();expect(data.actions).toHaveLength(0);
});
test('native private cache keeps immutable chapters apart across zero reuse, renumbering and blocked legacy progress',async({signedInPage:page})=>{
 await page.goto('/settings/about');
 const result=await page.evaluate(async()=>{
  const root='/src/services/';
  const {offlineReaderStore,chapterAudioStore}=await import(root+'offlineReaderStore.ts');
  const {offlineTranslations}=await import(root+'offlineTranslations.ts');
  const {accountStorage}=await import(root+'accountStorage.ts');
  const {PROGRESS_QUEUE_KEY,getQueuedProgress}=await import(root+'progressSyncQueue.ts');
  const epoch='11111111-1111-4111-8111-111111111111',keyA='22222222-2222-4222-8222-222222222222',keyB='33333333-3333-4333-8333-333333333333';
  const chapter=(number:number,key=keyA,revision='1')=>({id:key===keyA?1:2,novel_id:8201,library_id:1,chapter_number:number,chapter_key:key,manifest_epoch:epoch,manifest_revision:revision,title:'Same text',content:'Identical story text',source_version:'same-content',current_content_version:'same-content',document:{schema_version:1,source_format:'html',content_version:'same-content',plain_text:'Identical story text',blocks:[{id:'p',kind:'p',html:'<p>Identical story text</p>',text:'Identical story text'}]}});
  await offlineReaderStore.save(chapter(0));
  await chapterAudioStore.save(8201,0,new Blob(['synthetic local audio'],{type:'audio/wav'}),{...chapter(0),job_id:808,source_version:'same-content',rendition:'original',include_author_notes:false,precision:'unavailable',duration_seconds:1,segments:[]});
  await offlineTranslations.save(8201,0,{...chapter(0),id:909,language:'de',status:'completed',completed_blocks:1,total_blocks:1,charged_usd:0});
  await offlineReaderStore.save(chapter(7,keyA,'2'));await offlineReaderStore.save(chapter(0,keyB,'2'));
  const old=await offlineReaderStore.get(8201,0,chapter(0));
  const current=await offlineReaderStore.get(8201,0),moved=await offlineReaderStore.get(8201,7);
  const zeroAudio=await chapterAudioStore.recording(8201,0),movedAudio=await chapterAudioStore.recording(8201,7);
  const zeroTranslations=await offlineTranslations.list(8201,0),movedTranslations=await offlineTranslations.list(8201,7);
  let staleRejected=false;try{await offlineReaderStore.save(chapter(0));}catch{staleRejected=true;}
  const pending={novelId:8201,chapter:0,position:50,percent:40,ts:1,operationId:'retained-legacy'};accountStorage.setItem(PROGRESS_QUEUE_KEY,JSON.stringify([pending]));
  return {old,currentKey:current?.chapter_key,movedKey:moved?.chapter_key,zeroAudio:!!zeroAudio,movedAudioKey:movedAudio?.manifest?.chapter_key,zeroTranslations:zeroTranslations.length,movedTranslationKey:movedTranslations[0]?.chapter_key,staleRejected,pending:getQueuedProgress()};
 });
 expect(result).toMatchObject({old:null,currentKey:'33333333-3333-4333-8333-333333333333',movedKey:'22222222-2222-4222-8222-222222222222',zeroAudio:false,movedAudioKey:'22222222-2222-4222-8222-222222222222',zeroTranslations:0,movedTranslationKey:'22222222-2222-4222-8222-222222222222',staleRejected:true,pending:[{operationId:'retained-legacy',blocked:true,conflictCode:'chapter_identity_required'}]});
});
test('an unbound older server position is retained until the reader explicitly confirms the new chapter identity',async({signedInPage:page})=>{
 const captured=identity(11,0),writes:Record<string,unknown>[]=[];
 await page.route(/127\.0\.0\.1:8000|localhost:8000|\/api\//,async route=>{
  const req=route.request(),p=new URL(req.url()).pathname.replace(/^\/api(?=\/)/,'');
  if(p==='/chapter/annotations/11')return route.fulfill({json:[]});
  if(p==='/chapter/progress/11'){
   if(req.method()==='PUT'){const value=req.postDataJSON();writes.push(value);return route.fulfill({json:{novel_id:11,...captured,chapter_number:0,position:value.position,percent:value.percent,revision:2,reading_run_key:null}});}
   return route.fulfill({json:{novel_id:11,chapter_number:0,position:500,percent:70,revision:1,reading_run_key:null}});
  }
  if(p==='/chapter/content/library/1/11/0')return route.fulfill({json:{...captured,id:111,novel_id:11,chapter_number:0,title:'Verified replacement at zero',source_version:'current-original',current_content_version:'current-original',content:'An explicitly reviewed original.',document:{schema_version:1,source_format:'html',content_version:'current-original',plain_text:'An explicitly reviewed original.',blocks:[{id:'first',kind:'p',html:'<p>An explicitly reviewed original.</p>',text:'An explicitly reviewed original.'}]}}});
  if(p==='/chapter/11')return route.fulfill({json:[{...captured,id:111,novel_id:11,chapter_number:0,title:'Verified replacement at zero'}]});
  if(p==='/chapter/navigation/11/0')return route.fulfill({json:{...captured,novel_id:11,chapter_id:111,chapter_number:0,previous:null,next:null}});
  return route.fallback();
 });
 await page.goto(`/library/1/novels/11/0?chapter_key=${captured.chapter_key}`);await expect(page.getByText(/The earlier saved place cannot be verified for this chapter identity/)).toBeVisible();await expect(page.locator('.reader__content')).toHaveAttribute('aria-busy','false');
 await page.clock.install();await page.locator('.reader__content').evaluate(element=>element.dispatchEvent(new Event('scroll')));await page.clock.runFor(1000);expect(writes).toHaveLength(0);
 await page.getByRole('button',{name:'Keep this location',exact:true}).click();await expect.poll(()=>writes.length).toBe(1);expect(writes[0]).toMatchObject({chapter_number:0,expected_chapter_key:captured.chapter_key,expected_manifest_epoch:captured.manifest_epoch,expected_manifest_revision:captured.manifest_revision,expected_content_version:'current-original'});
});

test('preserved archived originals require an explicit match before the reviewed restoration',async({signedInPage:page})=>{
 const data=await setup(page,{archived:true});await data.region.getByRole('button',{name:'Review source chapter changes',exact:true}).click();
 await expect(data.region.getByText(/1 preserved archived originals · 0 selected for restoration/)).toBeVisible();
 await expect(data.region.getByText(/Matching it restores this same chapter/)).toBeVisible();
 await expect(data.region.getByRole('button',{name:'Apply reviewed chapter changes'})).toBeDisabled();
 await data.region.getByRole('button',{name:'Choose source match for chapter -2'}).click();await page.getByRole('button',{name:'Match to chapter 7',exact:true}).click();
 await data.region.getByRole('button',{name:'Preview updated chapter choices'}).click();
 await expect(data.region.getByText(/1 preserved archived originals · 1 selected for restoration/)).toBeVisible();
 expect(data.previews[1].mappings).toEqual([{chapter_key:header.chapter_key,metadata_chapter_key:identity(99,7).chapter_key,confirm_inferred_anchors:false}]);
 expect(data.actions).toHaveLength(0);await expect(data.region.getByRole('button',{name:'Apply reviewed chapter changes'})).toBeEnabled();
});

test('proven absent originals require explicit archival and a reviewed retained-place reset',async({signedInPage:page},info)=>{
 const data=await setup(page,{archiveAbsent:true});await data.region.getByRole('button',{name:'Review source chapter changes',exact:true}).click();
 const archive=data.region.getByRole('checkbox',{name:'Preserve chapter -2 as archived original'});await expect(archive).not.toBeChecked();expect(data.actions).toHaveLength(0);await archive.check();
 await expect(data.region.getByRole('button',{name:'Apply reviewed chapter changes'})).toBeDisabled();await data.region.getByRole('button',{name:'Choose retained chapter for current place'}).click();
 await expect(page.getByRole('button',{name:'Use original chapter -2'})).toBeDisabled();await page.getByRole('button',{name:'Use original chapter 0'}).click();
 await data.region.getByRole('button',{name:'Preview updated chapter choices'}).click();await expect(data.region.getByText('Current saved place: Chapter -2 · 80% → Chapter 7 · 0%')).toBeVisible();
 expect(data.previews[1]).toMatchObject({archive_chapter_keys:[header.chapter_key],resolve_current_chapter_key:identity(novelId,0).chapter_key});await expect(data.region.getByText(/pixel, block, translation and content-version locators are cleared/)).toBeVisible();
 await page.setViewportSize({width:390,height:844});await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth)).toBe(390);await page.addStyleTag({content:'*,*::before,*::after {animation:none!important;transition:none!important}'});const scan=await new AxeBuilder({page}).include('.chapter-changes').analyze();expect(scan.violations).toEqual([]);await mkdir('/tmp/nexus-private-archive-native',{recursive:true});await page.screenshot({path:`/tmp/nexus-private-archive-native/${info.project.name}-phone.png`,fullPage:true});
 await data.region.getByRole('button',{name:'Apply reviewed chapter changes'}).click();await expect(page.getByRole('dialog')).toContainText('original text, audio and notes are preserved');expect(data.actions).toHaveLength(0);await page.getByRole('button',{name:'Confirm chapter changes'}).click();await expect(data.region.getByText('The reviewed chapter addresses are now active.')).toBeVisible();expect(data.actions).toHaveLength(1);
});
