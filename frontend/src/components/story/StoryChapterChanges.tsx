import {useCallback,useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {Link} from 'react-router-dom';
import axios from 'axios';
import {Banner,Button,Checkbox,Dialog,Input} from '../ui';
import {onAccountStorageChange,storageGeneration} from '../../services/accountStorage';
import {getUserFacingError} from '../../services/apiClient';
import {getQueuedProgress} from '../../services/progressSyncQueue';
import {chapterService} from '../../services/chapterService';
import {chapterManifestFence,observeChapterIdentity} from '../../services/chapterIdentity';
import {readingJournalOperationId} from '../../services/readingJournalService';
import {chapterManifestService,loadManifestIntent,saveManifestIntent,type ManifestIntent,type ManifestItem,type ManifestMapping,type ManifestPage,type ManifestReview,type ManifestState,type RemoteChoice} from '../../services/chapterManifestService';
import './StoryChapterChanges.css';
const chapterLabel=(number:number|null)=>number===null?'Not assigned':`Chapter ${number}`;
const decisionLabel:Record<ManifestItem['decision'],string>={bound:'Same verified chapter',stable_source_id:'Same source identity',explicit:'Your selected match',new:'New chapter',needs_mapping:'Choose a match',unlisted:'Not in this snapshot',archive:'Preserve as archived original'};
function Contents({novelId,libraryId,onApplied}:{novelId:number;libraryId:number;onApplied:()=>void}){
 const generation=storageGeneration(),mounted=useRef(false),request=useRef(0);
 const current=useCallback(()=>mounted.current&&generation===storageGeneration(),[generation]);
 const [state,setState]=useState<ManifestState|null>(null),[history,setHistory]=useState<ManifestPage<ManifestReview>|null>(null),[historyOffset,setHistoryOffset]=useState(0);
 const [review,setReview]=useState<ManifestReview|null>(null),[page,setPage]=useState<ManifestPage<ManifestItem>|null>(null),[pageKind,setPageKind]=useState<'items'|'unmapped'>('items');
 const [archiveKeys,setArchiveKeys]=useState<string[]>([]),[editable,setEditable]=useState(false);
 const [mappings,setMappings]=useState<ManifestMapping[]>([]),[resolutions,setResolutions]=useState<{current?:string;furthest?:string}>({}),[dirty,setDirty]=useState(false);
 const [pending,setPending]=useState<ManifestIntent|null>(()=>loadManifestIntent(novelId)),[confirm,setConfirm]=useState<'apply'|'undo'|null>(null);
 const [busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 const [picker,setPicker]=useState<{kind:'remote';item:ManifestItem}|{kind:'current'|'furthest'}|null>(null),[remote,setRemote]=useState<ManifestPage<RemoteChoice>|null>(null),[remoteQuery,setRemoteQuery]=useState('');
 const [local,setLocal]=useState<ManifestState|null>(null),[localCursors,setLocalCursors]=useState<(string|undefined)[]>([undefined]);
 const [,setStorageTick]=useState(0);
 const queued=getQueuedProgress().filter(row=>row.novelId===novelId);
 useEffect(()=>{mounted.current=true;const changed=()=>setStorageTick(value=>value+1);window.addEventListener('storage',changed);window.addEventListener('focus',changed);return()=>{mounted.current=false;request.current+=1;window.removeEventListener('storage',changed);window.removeEventListener('focus',changed);};},[]);
 const load=useCallback(async(signal?:AbortSignal)=>{
  const fence=chapterManifestFence(novelId);
  const values=await Promise.all([chapterManifestService.state(novelId,undefined,undefined,signal),chapterManifestService.history(novelId,historyOffset,signal)]);
  if(!current()||signal?.aborted)return;
  observeChapterIdentity(novelId,values[0],generation,fence);setState(values[0]);setHistory(values[1]);
 },[novelId,historyOffset,current,generation]);
 useEffect(()=>{const abort=new AbortController();void load(abort.signal).catch(reason=>{if(current()&&!abort.signal.aborted)setError(getUserFacingError(reason,'Could not load chapter changes. Try refreshing.'));});return()=>abort.abort();},[load,current]);
 const edit=()=>{request.current+=1;setDirty(true);setError('');setNotice('');};
 const run=async(work:()=>Promise<void>)=>{if(busy)return;setBusy(true);setError('');try{await work();}catch(reason){if(current())setError(getUserFacingError(reason,'Could not complete this chapter review. Your original chapters are kept.'));}finally{if(current())setBusy(false);}};
 const preview=()=>run(async()=>{
  if(!state||pending)return;const epoch=++request.current;
  const value=await chapterManifestService.preview(novelId,{expected_manifest_epoch:state.manifest_epoch,expected_manifest_revision:state.manifest_revision,mappings,archive_chapter_keys:archiveKeys,resolve_current_chapter_key:resolutions.current,resolve_furthest_chapter_key:resolutions.furthest});
  if(!current()||epoch!==request.current)return;setReview(value);setPageKind('items');setPage(value.items);setDirty(false);setEditable(true);setNotice('Review the proposed addresses and evidence before applying.');
 });
 const showReview=(id:number)=>run(async()=>{const epoch=++request.current,value=await chapterManifestService.review(novelId,id);if(current()&&epoch===request.current){setReview(value);setPageKind('items');setPage(value.items);setMappings([]);setArchiveKeys([]);setResolutions({});setDirty(false);setEditable(false);}});
 const showPage=(kind:'items'|'unmapped',offset:number)=>run(async()=>{if(!review)return;const id=review.review_id,value=await chapterManifestService.items(novelId,id,kind,offset);if(current()&&review.review_id===id){setPage(value);setPageKind(kind);}});
 const openRemote=(item:ManifestItem)=>run(async()=>{if(!review)return;const value=await chapterManifestService.remote(novelId,review.review_id);if(current()){setRemote(value);setRemoteQuery('');setPicker({kind:'remote',item});}});
 const remotePage=(offset:number)=>run(async()=>{if(!review)return;const value=await chapterManifestService.remote(novelId,review.review_id,remoteQuery,offset);if(current())setRemote(value);});
 const chooseRemote=(choice:RemoteChoice)=>{
  if(!picker||picker.kind!=='remote'||!picker.item.chapter_key)return;const key=picker.item.chapter_key;
  edit();setArchiveKeys(rows=>rows.filter(value=>value!==key));setMappings(rows=>[...rows.filter(row=>row.chapter_key!==key),{chapter_key:key,metadata_chapter_key:choice.metadata_chapter_key,confirm_inferred_anchors:false}]);setPicker(null);
 };
 const chooseAnchor=(key:string)=>{if(!picker||picker.kind==='remote')return;edit();setResolutions(value=>({...value,[picker.kind]:key}));setPicker(null);};
 const openLocal=(kind:'current'|'furthest')=>run(async()=>{const value=await chapterManifestService.state(novelId);if(current()){setLocal(value);setLocalCursors([undefined]);setPicker({kind});}});
 const localPage=(next:boolean)=>run(async()=>{if(!local)return;const cursors=next?[...localCursors,local.next_cursor??undefined]:localCursors.slice(0,-1);if(!cursors.length)return;const value=await chapterManifestService.state(novelId,cursors[cursors.length-1],local);if(current()){setLocal(value);setLocalCursors(cursors);}});
 const prepareConfirm=(action:'apply'|'undo')=>run(async()=>{
  if(!review||pending||getQueuedProgress().some(row=>row.novelId===novelId))return;
  const [latest,manifest]=await Promise.all([chapterManifestService.review(novelId,review.review_id),chapterManifestService.state(novelId)]);
  if(!current())return;observeChapterIdentity(novelId,manifest,generation);setState(manifest);setReview(latest);
  if(action==='apply'&&(!latest.can_apply||dirty)||action==='undo'&&!latest.can_undo){setError(latest.undo_blocked_reason||'This review changed. Refresh and review the current chapter list.');return;}
  setConfirm(action);
 });
 const execute=async(intent:ManifestIntent)=>{
  if(busy||getQueuedProgress().some(row=>row.novelId===novelId))return;
  saveManifestIntent(novelId,intent);setPending(intent);setConfirm(null);setBusy(true);setError('');setNotice('');
  let acknowledged=false;
  try{
   await chapterManifestService.execute(novelId,intent);acknowledged=true;if(!current())return;
   const authoritative=await chapterManifestService.review(novelId,intent.review_id);if(!current())return;
   const manifest=await chapterManifestService.state(novelId);if(!current())return;
   observeChapterIdentity(novelId,manifest,generation);
   const progress=await chapterService.getReadingProgress(novelId);if(!current())return;chapterService.acceptReadingRun(novelId,progress);
   setState(manifest);setReview(authoritative);setPage(authoritative.items);setPageKind('items');setDirty(false);setEditable(false);setMappings([]);setArchiveKeys([]);setResolutions({});
   await load();if(!current())return;saveManifestIntent(novelId,null);setPending(null);setNotice(authoritative.status==='undone'?'The chapter addresses were restored. Their identity revision continues forward.':'The reviewed chapter addresses are now active.');onApplied();
  }catch(reason){if(!current())return;
   if(!acknowledged&&axios.isAxiosError(reason)&&reason.response&&reason.response.status>=400&&reason.response.status<500&&![408,429].includes(reason.response.status)){saveManifestIntent(novelId,null);setPending(null);setDirty(true);void load().catch(()=>undefined);}
   setError(getUserFacingError(reason,'The result is not confirmed. Keep this pending action and explicitly check it again; do not create a replacement request.'));
  }finally{if(current())setBusy(false);}
 };
 const confirmAction=()=>{
  if(!confirm||!review||!state)return;
  const operation_id=readingJournalOperationId();
  void execute(confirm==='apply'?{action:'apply',review_id:review.review_id,body:{review_token:review.review_token,operation_id}}:{action:'undo',review_id:review.review_id,body:{expected_revision:review.revision,expected_manifest_epoch:state.manifest_epoch,expected_manifest_revision:state.manifest_revision,operation_id}});
 };
 const exportQueued=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify({novel_id:novelId,positions:queued},null,2)],{type:'application/json'}));const anchor=document.createElement('a');anchor.href=url;anchor.download=`nexus-unsynchronized-positions-${novelId}.json`;anchor.click();URL.revokeObjectURL(url);};
 return <section className="chapter-changes" aria-label="Reviewed chapter list changes">
  <h2>Chapter identity review</h2>
  <p>Review source chapter identities and addresses without merging stories. Text, saved editions, reading history and original annotations stay attached to their chapters.</p>
  {error&&<Banner tone="warning">{error}</Banner>}{notice&&<p role="status">{notice}</p>}
  {queued.length>0&&<Banner tone="warning">{queued.length} unsynchronized positions are retained. Chapter changes and undo are paused until you review them. <Link to={`/library/${libraryId}/novels/${novelId}?tab=history`}>Open reading history</Link><Button onClick={exportQueued}>Download unsynchronized positions</Button></Banner>}
  {pending&&<Banner tone="warning">A previous {pending.action==='apply'?'chapter change':'undo'} has not been confirmed. Checking it uses the same operation; it does not apply it twice.<Button disabled={busy||!!queued.length} onClick={()=>void execute(pending)}>Check pending chapter action</Button></Banner>}
  <div className="chapter-changes__actions"><Button disabled={busy} onClick={()=>void run(()=>load())}>Refresh chapter state</Button><Button variant="primary" disabled={busy||!state||!!pending} onClick={()=>void preview()}>{dirty?'Preview updated chapter choices':'Review source chapter changes'}</Button></div>
  {state&&<p>{state.total} local chapters · {state.identity_required?'Chapter identity checks are required for saved changes.':'Existing installations can still use their original chapter addresses.'}</p>}
  {review&&<section aria-label="Chapter address review"><h3>Review chapter addresses</h3>
   <p>{review.counts.mapped} matched · {review.counts.new} new · {review.counts.renumbered} renumbered · {review.counts.unmapped} need a decision</p>
   {!!review.counts.archived_chapters&&<p>{review.counts.archived_chapters} preserved archived originals · {review.counts.restored_chapters??0} selected for restoration. Archived originals without a selected source match stay archived.</p>}
   <p>Reviewed source: {review.remote.source.site ?? "Unknown site"} · Story {review.remote.source.story_id ?? "not supplied"}</p>{review.remote.source.source_url&&<p>Source address: <code>{review.remote.source.source_url}</code></p>}
   <p>{review.remote.identity_kind==='stable_source_id'?'The source supplies chapter identities.':'Source identities require individual review; positions and titles alone are not proof of the same chapter.'}</p>
   {!review.remote.deletion_authoritative&&<p>This catalog snapshot cannot prove that source chapters were removed. Missing chapters will not be deleted.</p>}
   {!!review.counts.newly_archived_chapters&&<p>{review.counts.newly_archived_chapters} originals selected for archival. Their text, audio, translations and annotations remain preserved; they leave the active chapter list.</p>}
   {!editable&&<p>This saved review is read-only. Start a new source review to change its choices.</p>}
   <p>No new narration, translation or AI requests are started. An uncertain match never becomes verified reading evidence.</p>
   {review.blocked_reasons.map((reason,index)=><Banner key={index} tone="warning">{reason.message}</Banner>)}
   {review.anchors?.filter(anchor=>!anchor.resolved||anchor.relocated||!!anchor.chapter_key&&archiveKeys.includes(anchor.chapter_key)).map(anchor=><div key={anchor.kind}><p>{anchor.kind==='current'?'Current saved place':'Furthest saved place'}: {anchor.relocated?`${chapterLabel(anchor.previous_chapter_number??null)} · ${anchor.previous_percent??0}% → ${chapterLabel(anchor.chapter_number)} · 0%`: `${chapterLabel(anchor.chapter_number)} · ${anchor.percent}%`}</p>{(anchor.relocated||!!anchor.chapter_key&&archiveKeys.includes(anchor.chapter_key))&&<p>Archiving this original requires a different retained chapter. The new place starts at 0%; pixel, block, translation and content-version locators are cleared. No reading proof transfers.</p>}<Button disabled={busy||!!pending||!editable} onClick={()=>void openLocal(anchor.kind)}>{resolutions[anchor.kind]?'Change retained chapter':'Choose retained chapter'} for {anchor.kind==='current'?'current':'furthest'} place</Button>{resolutions[anchor.kind]&&<p>Retained chapter selected. Preview updated choices to review the exact new address and 0% reset when archiving.</p>}</div>)}
   <div className="chapter-changes__actions"><Button disabled={busy} onClick={()=>void showPage('items',0)}>Proposed chapter addresses</Button><Button disabled={busy} onClick={()=>void showPage('unmapped',0)}>Unresolved original chapters</Button></div>
   <ol className="chapter-changes__items">{page?.items.map((item,index)=>{const choice=mappings.find(row=>row.chapter_key===item.chapter_key);return <li key={`${item.chapter_key}:${item.metadata_chapter_key}:${index}`}><h4>{item.title||'Untitled chapter'}</h4>{item.archived&&<p>Preserved archived original. Matching it restores this same chapter, including its saved text and annotations.</p>}<p>{chapterLabel(item.from_number)} → {chapterLabel(item.to_number)} · {decisionLabel[item.decision]}</p>{item.requires_content_review&&<p>Revised or uncertain text needs a separate reading review. Previous reading proof is not extended.</p>}{item.inferred_anchor_count>0&&<p>{item.inferred_anchor_count} original position checkpoints have inferred identity.</p>}{choice&&dirty&&<p>A different source match is selected. Preview the updated choices before applying.</p>}{(item.candidates?.length??0)>0&&<p>Advisory matches: {item.candidates?.map(candidate=>`${chapterLabel(candidate.chapter_number)} · ${candidate.title||'Untitled'}`).join('; ')}. Suggestions do not establish reading proof.</p>}{item.chapter_key&&!item.archived&&(item.can_archive||item.decision==='archive')&&<Checkbox label={`Preserve ${chapterLabel(item.from_number).toLowerCase()} as archived original`} checked={archiveKeys.includes(item.chapter_key)||!editable&&item.decision==='archive'} disabled={busy||!!pending||!editable} onChange={event=>{edit();const key=item.chapter_key!;setResolutions({});setArchiveKeys(rows=>event.target.checked?[...rows.filter(value=>value!==key),key]:rows.filter(value=>value!==key));setMappings(rows=>rows.filter(row=>row.chapter_key!==key));}}/>}{item.chapter_key&&!item.archived&&!item.can_archive&&item.archive_blocked_reason&&<p>Archival unavailable: {item.archive_blocked_reason}</p>}{item.chapter_key&&<Button disabled={busy||!!pending||!editable||archiveKeys.includes(item.chapter_key)} onClick={()=>void openRemote(item)}>Choose source match for {chapterLabel(item.from_number).toLowerCase()}</Button>}{item.chapter_key&&(choice?.metadata_chapter_key||item.metadata_chapter_key)&&item.inferred_anchor_count>0&&<Checkbox checked={choice?.confirm_inferred_anchors??false} disabled={busy||!!pending||!editable||!!item.chapter_key&&archiveKeys.includes(item.chapter_key)} label={`I reviewed inferred checkpoints for ${chapterLabel(item.from_number).toLowerCase()}`} onChange={event=>{edit();setMappings(rows=>[...rows.filter(row=>row.chapter_key!==item.chapter_key),{chapter_key:item.chapter_key!,metadata_chapter_key:choice?.metadata_chapter_key||item.metadata_chapter_key!,confirm_inferred_anchors:event.target.checked}]);}}/>}</li>;})}</ol>
   {page&&<nav className="chapter-changes__actions" aria-label="Chapter change review pages"><Button disabled={busy||page.offset===0} onClick={()=>void showPage(pageKind,Math.max(0,page.offset-page.limit))}>Previous changes</Button><span>{page.total?page.offset+1:0}–{Math.min(page.offset+page.items.length,page.total)} of {page.total}</span><Button disabled={busy||!page.has_more} onClick={()=>void showPage(pageKind,page.offset+page.limit)}>Next changes</Button></nav>}
   {dirty&&<p>Choices changed. Preview them again before applying.</p>}
   <div className="chapter-changes__actions"><Button variant="primary" disabled={busy||!!pending||!!queued.length||dirty||!review.can_apply||review.status!=='preview'} onClick={()=>void prepareConfirm('apply')}>Apply reviewed chapter changes</Button>{review.status==='applied'&&<Button disabled={busy||!!pending||!!queued.length||!review.can_undo} onClick={()=>void prepareConfirm('undo')}>Review undo</Button>}</div>{review.status==='applied'&&!review.can_undo&&<p>{review.undo_blocked_reason||'Later reading or chapter changes prevent undo.'}</p>}
  </section>}
  <section aria-label="Chapter change history"><h3>Chapter change history</h3>{history?.items.length===0&&<p>No chapter list changes have been reviewed.</p>}<ul>{history?.items.map(item=><li key={item.review_id}>Review {item.review_id} · {item.status} · {item.counts.renumbered} renumbered <Button disabled={busy} onClick={()=>void showReview(item.review_id)}>Open review {item.review_id}</Button></li>)}</ul>{history&&<nav className="chapter-changes__actions" aria-label="Chapter change history pages"><Button disabled={busy||historyOffset===0} onClick={()=>setHistoryOffset(value=>Math.max(0,value-10))}>Previous chapter reviews</Button><span>{history.total?history.offset+1:0}–{Math.min(history.offset+history.items.length,history.total)} of {history.total}</span><Button disabled={busy||!history.has_more} onClick={()=>setHistoryOffset(value=>value+10)}>Next chapter reviews</Button></nav>}</section>
  <Dialog className="chapter-changes__dialog" open={confirm!==null} onClose={()=>{if(!busy)setConfirm(null);}} title={confirm==='undo'?'Undo these chapter address changes?':'Apply these reviewed chapter addresses?'} description={confirm==='undo'?'Only an unchanged reviewed chapter list can be restored. Its identity revision advances; old offline writes remain protected.':'Chapter identities and original text, audio and notes are preserved. Only explicitly selected, verified absent originals leave the active list. Relocated current or furthest places restart at 0% with old locators and reading proof cleared.'} actions={<><Button disabled={busy} onClick={()=>setConfirm(null)}>Keep reviewing</Button><Button variant="primary" disabled={busy||!!queued.length} onClick={confirmAction}>{confirm==='undo'?'Confirm chapter undo':'Confirm chapter changes'}</Button></>}/>
  <Dialog className="chapter-changes__dialog" open={picker!==null} onClose={()=>{if(!busy)setPicker(null);}} title={picker?.kind==='remote'?'Choose this chapter’s source identity':'Identify the original saved chapter'}>
   {picker?.kind==='remote'?<><p>Choose only when you recognize the same chapter. Similar titles or chapter numbers do not establish identity.</p><Input label="Find source chapter" value={remoteQuery} onChange={event=>setRemoteQuery(event.target.value)}/><Button disabled={busy} onClick={()=>void remotePage(0)}>Search source chapters</Button><ul className="chapter-changes__choices">{remote?.items.map(choice=><li key={choice.metadata_chapter_key}><p>{chapterLabel(choice.chapter_number)} · {choice.title||'Untitled'}</p><Button disabled={busy} onClick={()=>chooseRemote(choice)}>Match to chapter {choice.chapter_number}</Button></li>)}</ul>{remote&&<nav className="chapter-changes__actions" aria-label="Source chapter match pages"><Button disabled={busy||remote.offset===0} onClick={()=>void remotePage(Math.max(0,remote.offset-remote.limit))}>Previous source matches</Button><span>{remote.total?remote.offset+1:0}–{Math.min(remote.offset+remote.items.length,remote.total)} of {remote.total}</span><Button disabled={busy||!remote.has_more} onClick={()=>void remotePage(remote.offset+remote.limit)}>Next source matches</Button></nav>}</>:<><p>Choose the original local chapter you recognize. This does not claim you read revised text.</p><ul className="chapter-changes__choices">{local?.items.map(item=><li key={item.chapter_key}><p>{chapterLabel(item.chapter_number)} · {item.title||'Untitled'}</p>{archiveKeys.includes(item.chapter_key)&&<p>Selected for archival; choose another retained chapter.</p>}<Button disabled={busy||archiveKeys.includes(item.chapter_key)||review?.anchors.some(anchor=>anchor.kind===picker?.kind&&anchor.chapter_key===item.chapter_key&&archiveKeys.includes(item.chapter_key))} onClick={()=>chooseAnchor(item.chapter_key)}>Use original chapter {item.chapter_number}</Button></li>)}</ul><nav className="chapter-changes__actions" aria-label="Original chapter pages"><Button disabled={busy||localCursors.length===1} onClick={()=>void localPage(false)}>Previous original chapters</Button><Button disabled={busy||!local?.has_more} onClick={()=>void localPage(true)}>Next original chapters</Button></nav></>}
  </Dialog>
 </section>;
}
export default function StoryChapterChanges(props:{novelId:number;libraryId:number;onApplied:()=>void;openRequest?:number}){
 const generation=useSyncExternalStore(onAccountStorageChange,storageGeneration),[open,setOpen]=useState(false),disclosure=useRef<HTMLDetailsElement>(null);
 useEffect(()=>{if(props.openRequest){setOpen(true);disclosure.current?.querySelector('summary')?.focus();}},[props.openRequest]);
 return <details ref={disclosure} open={open} className="chapter-changes-disclosure" onToggle={event=>{if(event.target===event.currentTarget)setOpen(event.currentTarget.open);}}><summary>Review chapter list changes</summary>{open&&<Contents key={`${generation}:${props.novelId}:${props.libraryId}`} {...props}/>}</details>;
}
