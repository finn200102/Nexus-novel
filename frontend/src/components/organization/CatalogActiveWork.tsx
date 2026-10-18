import {useEffect,useRef,useState} from 'react';
import {Banner,Button} from '../ui';
import {catalogScrapeService as service} from '../../services/catalogScrapeService';
import {storageGeneration} from '../../services/accountStorage';
import {getUserFacingError} from '../../services/apiClient';
import type {CatalogActiveJobsResponse} from '../../generated/api';
export default function CatalogActiveWork({definitionId,name}:{definitionId:number;name:string}){
 const generation=storageGeneration(),alive=useRef(false),epoch=useRef(0);const[page,setPage]=useState<CatalogActiveJobsResponse|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');const current=()=>alive.current&&generation===storageGeneration();
 async function fetchPage(offset=0){const token=++epoch.current;let next=await service.activeJobs(definitionId,offset);if(current()&&token===epoch.current&&offset>0&&!next.items.length)next=await service.activeJobs(definitionId,0);if(current()&&token===epoch.current)setPage(next);}
 async function refresh(offset=0){setBusy(true);setError('');try{await fetchPage(offset);}catch(err){if(current())setError(getUserFacingError(err,'Active work is unavailable. Refresh before changing this job.'));}finally{if(current())setBusy(false);}}
 useEffect(()=>{alive.current=true;void refresh();return()=>{alive.current=false;epoch.current+=1;};
 // The parent keys this view by account and definition identity.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[]);
 useEffect(()=>{if(!page?.total||busy)return;const timer=setInterval(()=>void refresh(page.offset),3000);return()=>clearInterval(timer);
 // Read-only polling stays on the selected page and never starts source work.
 // eslint-disable-next-line react-hooks/exhaustive-deps
 },[page?.total,page?.offset,busy]);
 async function cancel(id:string){setBusy(true);setError('');try{await service.cancel(id);if(current())await fetchPage(0);}catch(err){if(current()){try{await fetchPage(0);}catch{/* Keep the last successful view. */}if(current())setError(getUserFacingError(err,'Cancellation could not be confirmed. Refresh active work before trying again.'));}}finally{if(current())setBusy(false);}}
 return <section className="scrape-card scrape-section" aria-label="Active catalog work"><h2>Active work · {name}</h2><p>Listing runs and pending imports from every run of this job. Cancelling keeps stories already imported.</p>{error&&<Banner tone="danger">{error}</Banner>}<Button disabled={busy} onClick={()=>void refresh()}>Refresh active catalog work</Button>{page&&<><p>{page.total} active jobs · {page.total?page.offset+1:0}–{Math.min(page.offset+page.items.length,page.total)} shown</p>{!page.total&&<p>No active listing runs or imports. Review the current settings before editing again.</p>}<ul>{page.items.map(job=><li key={job.id}><strong>{job.job_type==='catalog_scrape'?'Listing run':'Story import'}</strong><p>{job.id} · {job.status} · {Math.round(job.progress*100)}%</p><Button disabled={busy} onClick={()=>void cancel(job.id)}>Cancel active catalog job {job.id}</Button></li>)}</ul><div className="scrape-actions"><Button disabled={busy||page.offset===0} onClick={()=>void refresh(Math.max(0,page.offset-page.limit))}>Previous active catalog jobs</Button><Button disabled={busy||page.offset+page.items.length>=page.total} onClick={()=>void refresh(page.offset+page.limit)}>Next active catalog jobs</Button></div></>}</section>;
}
