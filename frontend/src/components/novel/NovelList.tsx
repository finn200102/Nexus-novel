import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { novelService } from "../../services/novelService";
import { libraryViewService, type LibrarySortBy, type LibraryViewPage, type OwnedLibraryDefinition, type FollowState } from "../../services/libraryViewService";
import { getUserFacingError, isRequestCancelled } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import LibraryStoryCard from "../library/LibraryStoryCard";
import { Banner, Button, Dialog, EmptyState } from "../ui";
import { NovelCardSkeleton } from "../common/Skeleton";
import type { Shelf } from "../../types/organization";
export type { LibrarySortBy } from "../../services/libraryViewService";
interface NovelListProps {
  library_id:number;searchTerm:string;sourceFilter:string;sortBy:LibrarySortBy;viewMode:"grid"|"list";selectionMode:boolean;
  refreshKey?:number;shelves?:Shelf[];onShelvesChanged?:(shelves:Shelf[])=>void;shelfId?:number|null;userTag?:string;minRating?:number;statusFilter?:string;
  onPageLoaded?:(page:LibraryViewPage|null)=>void;
}
function NovelListContents({ definition,viewMode,selectionMode,refreshKey=0,shelves=[],onShelvesChanged,onPageLoaded }: NovelListProps & {definition:OwnedLibraryDefinition}) {
  const generation=storageGeneration(),mounted=useRef(false);
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  const current=()=>mounted.current&&generation===storageGeneration();
  const [page,setPage]=useState<LibraryViewPage|null>(null),[offset,setOffset]=useState(0),[refresh,setRefresh]=useState(0);
  const [loading,setLoading]=useState(true),[error,setError]=useState("");
  const [selected,setSelected]=useState<Set<number>>(new Set()),[confirm,setConfirm]=useState(false),[deleting,setDeleting]=useState(false);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setError("");setSelected(new Set());onPageLoaded?.(null);
    const timer=window.setTimeout(()=>{void libraryViewService.preview(definition,offset,50,controller.signal).then(result=>{
      if(controller.signal.aborted||!current())return;setPage(result);onPageLoaded?.(result);
    }).catch(err=>{if(!controller.signal.aborted&&current()&&!isRequestCancelled(err)){setPage(null);setError(getUserFacingError(err,"Could not load your stories. Retry to check all matching stories."));}}).finally(()=>{if(!controller.signal.aborted&&current())setLoading(false);});},200);
    return()=>{controller.abort();window.clearTimeout(timer);};
  // Definition is stable for the keyed lifetime of this query.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  },[definition,offset,refreshKey,refresh,onPageLoaded]);
  useEffect(()=>{if(!selectionMode){setSelected(new Set());setConfirm(false);}},[selectionMode]);
  const remove=async()=>{
    if(!page||!selected.size)return;setDeleting(true);setError("");
    try{await novelService.deleteNovelsByIds(definition.library_ids[0],Array.from(selected));if(current()){setConfirm(false);setSelected(new Set());if(offset>0&&page.items.length===selected.size)setOffset(Math.max(0,offset-50));else setRefresh(value=>value+1);}}
    catch(err){if(current())setError(getUserFacingError(err,"Some stories could not be removed. Refresh the list before trying again."));}
    finally{if(current())setDeleting(false);}
  };
  const items=loading?[]:page?.items??[];
  return <div className={`library-list library-list--${viewMode}`} aria-busy={loading}>
    {loading&&<div className="library-list__grid" aria-hidden="true">{Array.from({length:8},(_,index)=><NovelCardSkeleton key={index}/>)}</div>}
    {error&&<Banner tone="warning">{error}<Button onClick={()=>setRefresh(value=>value+1)}>Retry library results</Button></Banner>}
    {!loading&&!error&&!items.length&&<EmptyState title={page?.library_total===0?"No stories in this library yet":"No stories match these filters"} description="Add a story or change your search, shelf, source or reading status."/>}
    {!!items.length&&<div className="library-list__grid">{items.map(novel=><LibraryStoryCard key={novel.id} novel={novel} libraryId={novel.library_id} compact={viewMode==="list"} personalRating={novel.personal_rating} selectionMode={selectionMode} selected={selected.has(novel.id)} onToggleSelect={()=>setSelected(previous=>{const next=new Set(previous);if(next.has(novel.id))next.delete(novel.id);else next.add(novel.id);return next;})} shelves={shelves} onShelvesChanged={onShelvesChanged}/>)}</div>}
    {page&&!error&&<nav className="library-paging" aria-label="Library result pages"><Button variant="secondary" disabled={loading||deleting||offset===0} onClick={()=>setOffset(value=>Math.max(0,value-50))}>Previous stories</Button><span>{page.total?page.offset+1:0}–{Math.min(page.offset+page.items.length,page.total)} of {page.total} matching stories</span><Button variant="secondary" disabled={loading||deleting||offset+50>=page.total} onClick={()=>setOffset(value=>value+50)}>Next stories</Button></nav>}
    {selectionMode&&<div className="library-selection-bar"><span>{selected.size} selected on this page</span><div className="library-selection-bar__actions"><Button disabled={loading||deleting} onClick={()=>setSelected(new Set(items.map(item=>item.id)))}>Select this page</Button><Button disabled={deleting} onClick={()=>setSelected(new Set())}>Clear selection</Button><Button variant="danger" disabled={!selected.size||loading||deleting} onClick={()=>setConfirm(true)}>Delete selected stories</Button></div></div>}
    <Dialog open={confirm} onClose={()=>{if(!deleting)setConfirm(false);}} title={`Delete ${selected.size} selected ${selected.size===1?"story":"stories"}?`} actions={<><Button disabled={deleting} onClick={()=>setConfirm(false)}>Keep stories</Button><Button variant="danger" disabled={deleting} onClick={()=>void remove()}>{deleting?"Deleting…":"Delete reviewed stories"}</Button></>}><p>These library copies and their private reading data will be removed. Only the selected stories from this page are included.</p><ul>{page?.items.filter(item=>selected.has(item.id)).map(item=><li key={item.id}>{item.title}</li>)}</ul></Dialog>
  </div>;
}
export default function NovelList(props:NovelListProps){
  const generation=useSyncExternalStore(onAccountStorageChange,storageGeneration);
  const definition=useMemo<OwnedLibraryDefinition>(()=>({version:1,scope:"owned_library",library_ids:[props.library_id],q:props.searchTerm,source:props.sourceFilter==="all"?null:props.sourceFilter,follow_states:props.statusFilter&&props.statusFilter!=="all"?[props.statusFilter as FollowState]:[],user_tag:props.userTag?.trim()||null,min_rating:props.minRating||null,shelf_id:props.shelfId??null,sort_by:props.sortBy}),[props.library_id,props.searchTerm,props.sourceFilter,props.statusFilter,props.userTag,props.minRating,props.shelfId,props.sortBy]);
  return <NovelListContents key={`${generation}:${JSON.stringify(definition)}`} {...props} definition={definition}/>;
}
