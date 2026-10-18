import {useEffect,useRef,useState,useSyncExternalStore} from 'react';
import {audioService,type ServerAudioJob} from '../../services/audioService';
import {getUserFacingError} from '../../services/apiClient';
import {onAccountStorageChange,storageGeneration} from '../../services/accountStorage';
import {Banner,Button} from '../ui';
import './StorySavedRecordings.css';

const label=(job:ServerAudioJob)=>job.chapter_title_snapshot?.trim()||
  (job.chapter_number_snapshot!=null?`Saved chapter ${job.chapter_number_snapshot}`:`Saved recording ${job.id}`);

function Contents({novelId}:{novelId:number}){
  const generation=storageGeneration();
  const [rows,setRows]=useState<ServerAudioJob[]>([]),[total,setTotal]=useState(0),[page,setPage]=useState(0);
  const [error,setError]=useState(''),[retry,setRetry]=useState(0),[busy,setBusy]=useState(false);
  const [loading,setLoading]=useState(true);
  const [playing,setPlaying]=useState<{url:string;label:string}|null>(null);
  const lifecycle=useRef({mounted:false,request:0,url:null as string|null,audio:null as HTMLAudioElement|null});
  useEffect(()=>{
    const state=lifecycle.current;state.mounted=true;
    return()=>{state.mounted=false;state.request++;
      if(state.audio){state.audio.pause();state.audio.removeAttribute('src');state.audio.load();state.audio=null;}
      if(state.url)URL.revokeObjectURL(state.url);state.url=null;};
  },[]);
  const current=()=>lifecycle.current.mounted&&generation===storageGeneration();
  useEffect(()=>{
    let active=true;setError('');setLoading(true);setRows([]);
    void audioService.recordings(novelId,page*50).then(value=>{
      if(active&&generation===storageGeneration()){setRows(value.items);setTotal(value.total);}
    }).catch(err=>{if(active&&generation===storageGeneration())setError(getUserFacingError(err,'Couldn’t load saved recordings.'));})
      .finally(()=>{if(active&&generation===storageGeneration())setLoading(false);});
    return()=>{active=false;};
  },[novelId,page,retry,generation]);
  const load=async(job:ServerAudioJob,download=false)=>{
    const request=++lifecycle.current.request;setBusy(true);setError('');
    try{
      const blob=await audioService.audio(job.id);
      if(!current()||request!==lifecycle.current.request)return;
      const url=URL.createObjectURL(blob);
      if(download){const anchor=document.createElement('a');anchor.href=url;anchor.download=`recording-${job.id}.wav`;anchor.click();window.setTimeout(()=>URL.revokeObjectURL(url),1000);}
      else{if(lifecycle.current.url)URL.revokeObjectURL(lifecycle.current.url);lifecycle.current.url=url;setPlaying({url,label:label(job)});}
    }catch(err){if(current()&&request===lifecycle.current.request)setError(getUserFacingError(err,'This recording could not be loaded.'));}
    finally{if(current()&&request===lifecycle.current.request)setBusy(false);}
  };
  return <section className="story-saved-recordings" aria-label="Saved recordings">
    <h3>Saved recordings</h3>
    <p>Completed recordings stay available here when chapters change. Recordings with an unverified chapter link remain separate from current chapter audio.</p>
    {error&&<><Banner tone="warning">{error}</Banner><Button onClick={()=>setRetry(value=>value+1)}>Retry saved recordings</Button></>}
    {playing&&<><p>Listening: {playing.label}</p><audio ref={node=>{if(node)lifecycle.current.audio=node;}} aria-label={`Listen to ${playing.label}`} controls autoPlay src={playing.url}/></>}
    {loading&&<p role="status">Loading saved recordings…</p>}
    {!loading&&!error&&total===0&&<p>No saved recordings yet.</p>}
    <ul>{rows.map(job=><li key={job.id}>
      <h4>{label(job)}</h4><p>{job.provider_voice} · {job.status} · {job.completed_parts}/{job.total_parts} segments</p>
      {(!job.source_identity_current||job.source_identity_inferred)&&<p>The link to a current chapter cannot be verified. You can still listen to or download this recording.</p>}
      {job.chapter_archived&&job.source_identity_current&&<p>Preserved with an archived chapter.</p>}
      {job.error&&<p>{job.error}</p>}
      {job.audio_ready&&<><Button disabled={busy} onClick={()=>void load(job)}>Listen to saved recording {job.id}</Button>
        <Button disabled={busy} onClick={()=>void load(job,true)}>Download saved recording {job.id}</Button></>}
      {!job.audio_ready&&['queued','processing','retry_wait'].includes(job.status)&&<Button disabled={busy} onClick={()=>{
        setBusy(true);void audioService.cancel(job.id).then(()=>{if(current())setRetry(value=>value+1);})
          .catch(err=>{if(current())setError(getUserFacingError(err,'Couldn’t cancel this recording.'));}).finally(()=>{if(current())setBusy(false);});
      }}>Cancel saved recording {job.id}</Button>}
    </li>)}</ul>
    <nav aria-label="Saved recording pages"><Button disabled={page===0||busy||loading} onClick={()=>setPage(value=>value-1)}>Previous recordings</Button>
      <span> {total? page*50+1:0}–{Math.min((page+1)*50,total)} of {total} </span>
      <Button disabled={(page+1)*50>=total||busy||loading} onClick={()=>setPage(value=>value+1)}>Next recordings</Button></nav>
  </section>;
}

export default function StorySavedRecordings({novelId}:{novelId:number}){
  const generation=useSyncExternalStore(onAccountStorageChange,storageGeneration);
  return <Contents key={`${generation}:${novelId}`} novelId={novelId}/>;
}
