import { useEffect, useRef, useState } from 'react';
import { Banner, Button, Select } from '../ui';
import { textRevisionService, type RevisionMode, type RevisionPreview, type StoryTextStyle } from '../../services/textRevisionService';
import type { ChapterIdentity } from '../../services/chapterIdentity';
import type { ReaderProvider, TranslationVariant } from '../../services/readerToolsService';
import type { PassageAnchor } from './selectedPassage';
import { getUserFacingError } from '../../services/apiClient';
import { storageGeneration } from '../../services/accountStorage';

interface Props { novelId:number; chapter:number; provider?:ReaderProvider; identity?:ChapterIdentity; sourceVersion?:string; passage?:PassageAnchor|null; variants:TranslationVariant[] }
export default function TextRevisionPanel({novelId,chapter,provider,identity,sourceVersion,passage,variants}:Props) {
  const [mode,setMode]=useState<RevisionMode>('proofreading');
  const [scope,setScope]=useState('chapter');
  const [translationId,setTranslationId]=useState('');
  const [style,setStyle]=useState<StoryTextStyle|null>(null);
  const [guide,setGuide]=useState('');
  const [result,setResult]=useState<RevisionPreview|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState(false);
  const [saved,setSaved]=useState(false);
  const mounted=useRef(false), generation=useRef(storageGeneration());
  const current=()=>mounted.current && generation.current===storageGeneration();
  useEffect(()=>{
    mounted.current=true;
    void textRevisionService.style(novelId).then(value=>{if(current()){setStyle(value);setGuide(value.style_guide);}}).catch(err=>{if(current())setError(getUserFacingError(err,'Could not load the story style guide.'));});
    return ()=>{mounted.current=false;};
  },[novelId]);
  const run=async(work:()=>Promise<void>)=>{setBusy(true);setError('');try{await work();}catch(err){if(current())setError(getUserFacingError(err,'The preview failed. Your original is preserved.'));}finally{if(current())setBusy(false);}};
  const completed=variants.filter(row=>row.status==='completed' && row.source_version===sourceVersion);
  return <section aria-labelledby="text-edit-heading">
    <h2 id="text-edit-heading">Review text improvements</h2>
    <p>Generate a local before-and-after preview. Review meaning and names before using the result. Short chapters and selected passages are supported; downloaded originals stay unchanged.</p>
    {error&&<Banner tone="warning">{error}</Banner>}
    <label>Story style guide<textarea disabled={busy} aria-label="Story style guide" maxLength={2000} value={guide} onChange={event=>{setGuide(event.target.value);setSaved(false);setResult(null);}} placeholder="For example: restrained narrative voice; preserve honorifics."/></label>
    <Button disabled={!style||busy} onClick={()=>void run(async()=>{const value=await textRevisionService.saveStyle(novelId,{revision:style!.revision,style_guide:guide});if(current()){setStyle(value);setGuide(value.style_guide);setSaved(true);setResult(null);}})}>Save story style guide</Button>
    {saved&&<p role="status">Story style guide saved.</p>}
    <p>Approved terminology in the glossary below is used when polishing a saved translation.</p>
    <Select label="Editing operation" value={mode} disabled={busy} onChange={event=>{setMode(event.target.value as RevisionMode);setResult(null);}} options={[{value:'proofreading',label:'Proofread grammar and punctuation'},{value:'reformat',label:'Repair formatting only'},{value:'rewrite',label:'Rewrite literary style (explicit)'},{value:'translation_polish',label:'Polish a saved translation'}]}/>
    {mode==='rewrite'&&<p>A rewrite can change phrasing. Compare the preview carefully with the original.</p>}
    {mode==='translation_polish'?<Select disabled={busy} label="Saved translation to polish" value={translationId} onChange={event=>{setTranslationId(event.target.value);setResult(null);}} options={[{value:'',label:'Choose a current completed translation'},...completed.map(row=>({value:String(row.id),label:`${row.language} · translation ${row.id}`}))]}/>:<Select label="Editing scope" value={scope} disabled={busy} onChange={event=>{setScope(event.target.value);setResult(null);}} options={[{value:'chapter',label:'Current short chapter'},{value:'passage',label:'Selected original passage'}]}/>}
    {scope==='passage'&&mode!=='translation_polish'&&!passage&&<p>Select text in one original paragraph, then reopen these tools.</p>}
    {provider?.kind!=='local'&&<p>Choose a local conversational model above to enable editing.</p>}
    <Button loading={busy} disabled={busy||provider?.kind!=='local'||!identity||!sourceVersion||!style||guide!==style.style_guide||(mode==='translation_polish'?!translationId:scope==='passage'&&!passage)} onClick={()=>void run(async()=>{
      setResult(null);
      const value=await textRevisionService.preview(novelId,chapter,provider!.id,mode,identity!,sourceVersion!,mode!=='translation_polish'&&scope==='passage'?passage??null:null,mode==='translation_polish'?Number(translationId):undefined);
      if(current())setResult(value);
    })}>Generate editing preview</Button>
    {style&&guide!==style.style_guide&&<p>Save your style guide before generating a preview.</p>}
    {result&&<div aria-live="polite"><h3>Before</h3><pre style={{whiteSpace:'pre-wrap'}}>{result.draft}</pre><h3>After · review copy</h3><pre style={{whiteSpace:'pre-wrap'}}>{result.preview}</pre>
      {mode==='translation_polish'&&<details><summary>Original source</summary><pre style={{whiteSpace:'pre-wrap'}}>{result.original}</pre></details>}
      <Button onClick={()=>{const url=URL.createObjectURL(new Blob([result.preview],{type:'text/plain;charset=utf-8'}));const link=document.createElement('a');link.href=url;link.download=`chapter-${chapter}-${result.mode}-review.txt`;link.click();URL.revokeObjectURL(url);}}>Download preview for review</Button>
      <Button onClick={()=>setResult(null)}>Discard preview</Button></div>}
  </section>;
}
