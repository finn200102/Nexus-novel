import {useEffect,useRef,useState,useSyncExternalStore} from "react";
import {Banner,Button,Checkbox,Dialog,Input} from "../ui";
import {pronunciationService,applyPronunciation,normalizePronunciationRules,type PronunciationProfile,type PronunciationRule,type PronunciationSnapshot} from "../../services/pronunciationService";
import {onAccountStorageChange,storageGeneration} from "../../services/accountStorage";
import {getUserFacingError} from "../../services/apiClient";
import "./PronunciationEditor.css";

type Props={novelId?:number;onReady?:(snapshot:PronunciationSnapshot|null)=>void};
const operationId=()=>Array.from(crypto.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,"0")).join("");
function Editor({novelId,onReady}:Props){
  const generation=storageGeneration();
  const [profile,setProfile]=useState<PronunciationProfile|null>(null);
  const [rules,setRules]=useState<PronunciationRule[]>([]);
  const [inherit,setInherit]=useState(true);
  const [dirty,setDirty]=useState(false);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState("");
  const [notice,setNotice]=useState("");
  const [sample,setSample]=useState("");
  const [reload,setReload]=useState(0);
  const [confirmReload,setConfirmReload]=useState(false);
  const mounted=useRef(false),callback=useRef(onReady);
  const attempt=useRef<{fingerprint:string;id:string}|null>(null);
  callback.current=onReady;
  const current=()=>mounted.current && generation===storageGeneration();
  useEffect(()=>{mounted.current=true;return()=>{mounted.current=false;};},[]);
  useEffect(()=>{
    let active=true;setBusy(true);setError("");callback.current?.(null);
    void pronunciationService.get(novelId).then(value=>{
      if(!active || generation!==storageGeneration())return;
      setProfile(value);setRules(value.rules);setInherit(value.inherit_account);setDirty(false);setNotice("");attempt.current=null;
      callback.current?.({version:value.effective_version,rules:value.effective_rules});
    }).catch(err=>{if(active && generation===storageGeneration())setError(getUserFacingError(err,"Couldn’t load pronunciations. Retry before creating new audio."));})
      .finally(()=>{if(active && generation===storageGeneration())setBusy(false);});
    return()=>{active=false;};
  },[novelId,generation,reload]);
  const edit=(next:PronunciationRule[])=>{setRules(next);setDirty(true);setNotice("");callback.current?.(null);};
  let validationError="";
  try{normalizePronunciationRules(rules,64);}catch(err){validationError=err instanceof Error?err.message:"Check the pronunciation entries.";}
  const invalid=Boolean(validationError);
  const save=async()=>{
    if(!profile || busy || invalid || !dirty)return;
    setBusy(true);setError("");
    try{
      const payload={expected_revision:profile.revision,rules,inherit_account:novelId===undefined?undefined:inherit};
      const fingerprint=JSON.stringify(payload);
      if(attempt.current?.fingerprint!==fingerprint)attempt.current={fingerprint,id:operationId()};
      const saved=await pronunciationService.save({...payload,operation_id:attempt.current.id},novelId);
      if(current()){
        attempt.current=null;setProfile(saved);setRules(saved.rules);setInherit(saved.inherit_account);setDirty(false);setNotice("Pronunciations saved for new audio. Existing recordings keep their original pronunciation.");
        callback.current?.({version:saved.effective_version,rules:saved.effective_rules});
      }
    }catch(err){if(current())setError(getUserFacingError(err,"Couldn’t save. Your edits are retained; reload saved pronunciations if another device changed them."));}
    finally{if(current())setBusy(false);}
  };
  const previewRules=novelId!==undefined && inherit && profile
    ? [...profile.account_rules.filter(rule=>!rules.some(own=>own.source.trim()===rule.source)),...rules] : rules;
  let spokenPreview=sample;
  try{spokenPreview=applyPronunciation(sample,previewRules.filter(rule=>rule.source.trim() && rule.spoken.trim()));}catch{ /* Incomplete edits remain visible without becoming provider input. */ }
  return <details className="pronunciation-editor"><summary>Pronunciation</summary>
    <section aria-label={novelId===undefined?"Account pronunciations":"Story pronunciations"}>
      <p>{novelId===undefined?"Save name and phrase pronunciations for all your stories.":"Choose pronunciations for this story. Story entries replace matching account entries."} Matches are case-sensitive, including within longer words. Save your edits before creating new audio.</p>
      {!profile && busy && <p role="status">Loading pronunciations…</p>}
      {error && <Banner tone="warning">{error}</Banner>}
      {notice && <p role="status">{notice}</p>}
      {novelId!==undefined && <Checkbox label="Include account pronunciations" checked={inherit} disabled={!profile || busy} onChange={event=>{setInherit(event.target.checked);setDirty(true);setNotice("");callback.current?.(null);}}/>}
      <fieldset disabled={!profile || busy}><legend>{novelId===undefined?"Account entries":"Story entries"}</legend>
        {rules.length===0 && <p>No entries saved here.</p>}
        {rules.map((rule,index)=><div className="pronunciation-editor__row" key={index}>
          <Input label={`Written form ${index+1}`} maxLength={80} value={rule.source} onChange={event=>edit(rules.map((row,i)=>i===index?{...row,source:event.target.value}:row))}/>
          <Input label={`Spoken form ${index+1}`} maxLength={160} value={rule.spoken} onChange={event=>edit(rules.map((row,i)=>i===index?{...row,spoken:event.target.value}:row))}/>
          <Button onClick={()=>edit(rules.filter((_,i)=>i!==index))}>Remove pronunciation {index+1}</Button>
        </div>)}
        <Button disabled={rules.length>=64} onClick={()=>edit([...rules,{source:"",spoken:""}])}>Add pronunciation</Button>
        {invalid && <p>{validationError}</p>}
        <Button disabled={!dirty || invalid} onClick={()=>void save()}>Save pronunciations</Button>
        <Input label="Pronunciation preview text" value={sample} maxLength={600} onChange={event=>setSample(event.target.value)}/>
        {sample && <p><strong>Spoken text preview:</strong> {spokenPreview}</p>}
      </fieldset>
      <Button disabled={busy} onClick={()=>{if(dirty)setConfirmReload(true);else setReload(value=>value+1);}}>Reload saved pronunciations</Button>
      {dirty && <p role="status">Unsaved pronunciation changes.</p>}
    </section>
    <Dialog open={confirmReload} onClose={()=>setConfirmReload(false)} title="Reload saved pronunciations?" description="Your unsaved pronunciation edits will be replaced with the saved entries." actions={<><Button onClick={()=>setConfirmReload(false)}>Keep editing</Button><Button onClick={()=>{setConfirmReload(false);setReload(value=>value+1);}}>Reload saved entries</Button></>}/>
  </details>;
}
export default function PronunciationEditor(props:Props){
  const generation=useSyncExternalStore(onAccountStorageChange,storageGeneration);
  return <Editor key={`${generation}:${props.novelId??"account"}`} {...props}/>;
}
