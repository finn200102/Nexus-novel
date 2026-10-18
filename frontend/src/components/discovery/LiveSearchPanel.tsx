import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import axios from "axios";
import { Plus } from "lucide-react";
import { Banner, Button, Cover, FilterChip, Input, Select } from "../ui";
import { getUserFacingError } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { liveSearchService as service, type LiveResult, type LiveSourceCapability, type ProgressiveLivePage } from "../../services/liveSearchService";

interface Props { onAdd: (result: LiveResult) => Promise<void>; }
type Channel = { id: string; name: string; capability?: LiveSourceCapability; status: "queued" | "pending" | "complete" | "error"; page: number; requestedPage: number; data: ProgressiveLivePage | null; error: string | null; reloadRequired: boolean };
type Search = { query: string; feed: string | null; sourceId: string | null };
const DEFAULT_SOURCES = ["royalroad", "fanfiction", "archive"];
const MAX_CONCURRENT_SOURCES = 3;
function Contents({ onAdd }: Props) {
  const generation = storageGeneration(), mounted = useRef(false), epoch = useRef(0), controller = useRef<AbortController | null>(null), channelEpoch = useRef<Record<string,number>>({}), scheduler = useRef<{ active: number; tasks: Array<() => Promise<void>> }>({ active: 0, tasks: [] });
  const [query,setQuery]=useState(""),[sites,setSites]=useState<string[]>(DEFAULT_SOURCES),[feed,setFeed]=useState(""),[fandomMedium,setFandomMedium]=useState("book"),[fandomName,setFandomName]=useState("");
  const [capabilities,setCapabilities]=useState<LiveSourceCapability[]>([]),[capabilityLoading,setCapabilityLoading]=useState(true),[capabilityError,setCapabilityError]=useState(""),[capabilityAttempt,setCapabilityAttempt]=useState(0),[sourcesLimited,setSourcesLimited]=useState(false);
  const [submitted,setSubmitted]=useState<Search|null>(null),[channels,setChannels]=useState<Channel[]>([]),[adding,setAdding]=useState<string|null>(null),[addError,setAddError]=useState("");
  const current=()=>mounted.current&&generation===storageGeneration();
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;epoch.current+=1;controller.current?.abort();};},[]);
  useEffect(()=>{let live=true;const abort=new AbortController();setCapabilityLoading(true);setCapabilityError("");void service.capabilities(abort.signal).then(value=>{if(live&&current()){setCapabilities(value.sources);setSourcesLimited(value.sources_limited);}}).catch(err=>{if(live&&current())setCapabilityError(getUserFacingError(err,"Source capabilities are unavailable. You can still search the local catalog."));}).finally(()=>{if(live&&current())setCapabilityLoading(false);});return()=>{live=false;abort.abort();};
    // Account changes remount this workspace and fence all capability responses.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  },[capabilityAttempt]);
  function invalidate(){epoch.current+=1;controller.current?.abort();controller.current=null;channelEpoch.current={};scheduler.current={active:0,tasks:[]};setChannels([]);setSubmitted(null);setAddError("");}
  async function execute(channel:Channel,search:Search,page:number,token:number,signal:AbortSignal){
    const version=(channelEpoch.current[channel.id]??0)+1;channelEpoch.current[channel.id]=version;
    const valid=()=>current()&&!signal.aborted&&token===epoch.current&&channelEpoch.current[channel.id]===version;
    if(!valid())return;setChannels(values=>values.map(value=>value.id===channel.id?{...value,status:"pending",requestedPage:page,error:null}:value));
    try{
      const data=channel.id==="catalog"?await service.local(search.query,page,signal):search.feed?await service.browseSource(channel.id,search.feed,page,signal,channel.capability?.digest ?? undefined):await service.source(search.query,channel.id,page,signal,channel.capability?.digest ?? undefined);
      if(!valid())return;
      const reloadRequired=data.errors.some(item=>item.code==="source_changed"||item.code==="source_version_changed");
      const error=reloadRequired?"This source version changed. Reload sources and submit your search again.":data.errors.map(item=>item.message).join(" ")||null;
      setChannels(values=>values.map(value=>value.id===channel.id?{...value,page:data.page,data,status:error?"error":"complete",error,reloadRequired}:value));
    }catch(err){if(valid()){const reloadRequired=axios.isAxiosError(err)&&["source_version_changed","source_changed"].includes(err.response?.data?.detail?.code);setChannels(values=>values.map(value=>value.id===channel.id?{...value,status:"error",reloadRequired,error:getUserFacingError(err,`${channel.name} could not be searched. Retry this source when ready.`)}:value));}}
  }
  function schedule(channel:Channel,search:Search,page:number,token:number,signal:AbortSignal){
    if(channel.id==="catalog"){void execute(channel,search,page,token,signal);return;}
    const queue=scheduler.current;
    setChannels(values=>values.map(value=>value.id===channel.id?{...value,status:"queued",error:null}:value));
    function drain(){while(queue.active<MAX_CONCURRENT_SOURCES&&queue.tasks.length&&!signal.aborted&&token===epoch.current){const task=queue.tasks.shift()!;queue.active+=1;void task().finally(()=>{queue.active-=1;drain();});}}
    queue.tasks.push(()=>execute(channel,search,page,token,signal));drain();
  }
  function run(nextFeed:string|null=null){
    invalidate();const abort=new AbortController();controller.current=abort;const token=epoch.current;
    const selectedFeed=nextFeed?JSON.parse(nextFeed) as [string,string]:null;
    const search:Search={query:query.trim(),feed:selectedFeed?.[1]??null,sourceId:selectedFeed?.[0]??null};
    const selected=capabilities.filter(value=>selectedFeed?value.source_id===selectedFeed[0]:value.search&&sites.includes(value.source_id));
    const initial:Channel[]=[...(!selectedFeed?[{id:"catalog",name:"Local catalog",status:"queued" as const,page:1,requestedPage:1,data:null,error:null,reloadRequired:false}]:[]),...selected.map(value=>({id:value.source_id,name:value.name,capability:value,status:"queued" as const,page:1,requestedPage:1,data:null,error:null,reloadRequired:false}))];
    setSubmitted(search);setChannels(initial);
    // Local retrieval starts independently, never behind a source or model call.
    if(!selectedFeed)void execute(initial[0],search,1,token,abort.signal);
    for(const channel of initial.filter(value=>value.id!=="catalog"))schedule(channel,search,1,token,abort.signal);
  }

  function page(channel:Channel,next:number){if(!submitted||!controller.current||next<1||next>50||channel.status==="pending"||channel.status==="queued")return;schedule(channel,submitted,next,epoch.current,controller.current.signal);}
  function reloadSources(){invalidate();setFeed("");setCapabilityAttempt(value=>value+1);}
  async function add(result:LiveResult){if(adding)return;setAdding(result.source_url);setAddError("");try{await onAdd(result);}catch(err){if(current())setAddError(getUserFacingError(err,"This story could not be added."));}finally{if(current())setAdding(null);}}
  const pending=channels.filter(value=>value.status==="pending"||value.status==="queued").length;
  const feeds=capabilities.flatMap(source=>source.browse_feeds.map(value=>({value:JSON.stringify([source.source_id,value]),label:`${source.name} · ${value.replace(/-/g," ")}`})));
  return <section className="live-search" aria-label="Search the sites">
    <form className="live-search__form" role="search" aria-label="Search the sites" onSubmit={event=>{event.preventDefault();if(query.trim()){setFeed("");run();}}}>
      <Input type="search" search label="Search the source sites" hideLabel value={query} maxLength={200} onChange={event=>{invalidate();setQuery(event.target.value);}} onClear={()=>{invalidate();setQuery("");}} placeholder="Search your catalog and selected sites"/>
      <Button type="submit" variant="primary" disabled={!query.trim()}>Search</Button>
    </form>
    <p>Results appear as each source responds, with separate pages and retry controls. Nothing is added to your library automatically.</p>
    {capabilityLoading&&<p role="status">Loading available sources…</p>}{capabilityError&&<Banner tone="warning" action={<Button onClick={()=>setCapabilityAttempt(value=>value+1)}>Retry source capabilities</Button>}>{capabilityError}</Banner>}
    {sourcesLimited&&<Banner tone="info">Only the first 100 available sources are listed. An administrator can review enabled source packages; reload sources after changes.</Banner>}
    <Button disabled={capabilityLoading} onClick={reloadSources}>Reload sources</Button>
    <div className="discover-sites" role="group" aria-label="Sites to search">{capabilities.filter(value=>value.search).map(source=><FilterChip key={source.source_id} selected={sites.includes(source.source_id)} onChange={()=>{invalidate();setSites(values=>values.includes(source.source_id)?values.filter(value=>value!==source.source_id):[...values,source.source_id]);}}>{source.name}</FilterChip>)}</div>
    {!sites.some(id=>capabilities.some(source=>source.source_id===id&&source.search))&&!capabilityLoading&&<p>No searchable source is selected. Search will use your local catalog.</p>}
    <Select label="Or browse a feed" fieldClassName="live-search__feed" value={feed} onChange={event=>{invalidate();setFeed(event.target.value);if(event.target.value && (JSON.parse(event.target.value) as [string,string])[1]!=="fandom")run(event.target.value);}} options={[{value:"",label:"Choose a feed…"},...feeds]}/>
    {feed && (JSON.parse(feed) as [string,string])[1]==="fandom" && <form className="live-search__fandom" aria-label="Browse FanFiction.net fandom" onSubmit={event=>{event.preventDefault();if(fandomName.trim()){const [sourceId]=JSON.parse(feed) as [string,string];run(JSON.stringify([sourceId,`fandom:${fandomMedium}/${fandomName.trim().replace(/\s+/g,"_")}`]));}}}>
      <Select label="Fandom medium" value={fandomMedium} onChange={event=>{invalidate();setFandomMedium(event.target.value);}} options={["anime","book","cartoon","comic","game","misc","movie","play","tv"].map(value=>({value,label:value.charAt(0).toUpperCase()+value.slice(1)}))}/>
      <Input label="Fandom name" value={fandomName} maxLength={160} onChange={event=>{invalidate();setFandomName(event.target.value);}} hint="Use the fandom name from FanFiction.net, for example Harry Potter. Spaces become underscores."/>
      <Button type="submit" disabled={!fandomName.trim()}>Browse fandom</Button>
    </form>}
    {submitted&&<p className="live-search__status" role="status">{submitted.feed?"Selected source feed":`Results for “${submitted.query}”`}{pending?` · ${pending} ${pending===1?"source still answering":"sources still answering"}`:" · Search complete"}</p>}
    {addError&&<Banner tone="danger">{addError}</Banner>}
    {channels.map(channel=><section key={channel.id} className="live-search__channel" aria-label={`${channel.name} results`}>
      <h2>{channel.name}</h2><p role="status">{channel.status==="queued"?"Waiting for an available search slot…":channel.status==="pending"?`Asking ${channel.name}…`:channel.data?`${channel.data.results.length} ${channel.data.results.length===1?"result":"results"} on page ${channel.page}`:"No response received"}</p>
      {channel.capability?.limitations.map(value=><small key={value}>{value}</small>)}
      {channel.error&&channel.requestedPage!==channel.page&&<p>Page {channel.requestedPage} could not be loaded. The saved results below are from page {channel.page}.</p>}
      {channel.error&&<Banner tone="warning" action={channel.reloadRequired?<Button onClick={reloadSources}>Reload sources for {channel.name}</Button>:<Button onClick={()=>page(channel,channel.requestedPage)}>Retry {channel.name}</Button>}>{channel.error}</Banner>}
      {channel.data&&<ul className="live-search__results">{channel.data.results.map((result,index)=><li key={`${result.source_url}:${index}`}>
        <Cover src={result.img_url} title={result.title} size={48}/><div className="live-search__text"><a href={result.source_url} target="_blank" rel="noreferrer noopener"><strong>{result.title}</strong><span className="visually-hidden"> (opens in a new tab)</span></a><small>{[result.site||result.novel_site,result.author,result.chapter_count!=null?`${result.chapter_count} chapters`:null,result.word_count!=null?`${result.word_count.toLocaleString()} words`:null,result.sources.includes("local")?"in catalog":null].filter(Boolean).join(" · ")}</small>{result.description&&<p>{result.description}</p>}</div><Button size="sm" icon={<Plus aria-hidden="true"/>} disabled={adding!==null&&adding!==result.source_url} loading={adding===result.source_url} onClick={()=>void add(result)} aria-label={`Add ${result.title}`}>Add</Button>
      </li>)}</ul>}
      {channel.data&&!channel.data.results.length&&!channel.error&&<p>No visible matches on this page.</p>}
      {channel.data&&<div className="live-search__pages">{channel.page>1&&<Button disabled={channel.reloadRequired||channel.status==="pending"||channel.status==="queued"} onClick={()=>page(channel,channel.page-1)}>Previous page from {channel.name}</Button>}{channel.page<50&&channel.data.has_more!==false&&<Button disabled={channel.reloadRequired||channel.status==="pending"||channel.status==="queued"} onClick={()=>page(channel,channel.page+1)}>{channel.data.has_more===null?"Try next page from":"Next page from"} {channel.name}</Button>}</div>}
      {channel.data?.has_more===null&&<p className="live-search__pagination-note">This source does not report whether another page exists. “Try next page” makes an explicit request.</p>}
      {channel.page===50&&<p>Reached the 50-page request limit. Refine your search to continue.</p>}
    </section>)}
  </section>;
}
export function LiveSearchPanel(props:Props){const generation=useSyncExternalStore(onAccountStorageChange,storageGeneration);return <Contents key={generation} {...props}/>;}
export default LiveSearchPanel;
