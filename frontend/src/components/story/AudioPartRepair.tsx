import { useEffect, useRef, useState } from "react";
import { audioService, type AudioJobPart } from "../../services/audioService";
import { storageGeneration } from "../../services/accountStorage";
import { Button, Dialog } from "../ui";

export default function AudioPartRepair({jobId,onRepaired}:{jobId:number;onRepaired:()=>void}) {
  return <AudioPartRepairPanel key={`${storageGeneration()}:${jobId}`} jobId={jobId} onRepaired={onRepaired}/>;
}

function AudioPartRepairPanel({jobId,onRepaired}:{jobId:number;onRepaired:()=>void}) {
  const [open,setOpen]=useState(false);
  const [parts,setParts]=useState<AudioJobPart[]>([]);
  const [error,setError]=useState("");
  const [busy,setBusy]=useState(false);
  const [selected,setSelected]=useState<AudioJobPart|null>(null);
  const [revision,setRevision]=useState(0);
  const generation=storageGeneration();
  const mounted=useRef(false);
  useEffect(()=>{mounted.current=true;return ()=>{mounted.current=false;};},[]);
  const current=()=>mounted.current && generation===storageGeneration();
  useEffect(()=>{
    if(!open)return;
    let active=true;
    setError("");
    void audioService.parts(jobId).then(result=>{if(active && generation===storageGeneration())setParts(result.parts);}).catch(()=>{if(active && generation===storageGeneration())setError("Couldn’t load narration passages. Try opening this panel again.");});
    return ()=>{active=false;};
  },[jobId,open,generation,revision]);
  const repair=async()=>{
    if(!selected || busy)return;
    setBusy(true);setError("");
    try {
      await audioService.retryPart(jobId,selected.part_index);
      if(current()){setSelected(null);setOpen(false);onRepaired();}
    }catch{if(current())setError("Couldn’t queue this passage. The current recording is still available; try again.");}
    finally{if(current())setBusy(false);}
  };
  return <details onToggle={event=>setOpen(event.currentTarget.open)} open={open}>
    <summary>Repair individual narration passages</summary>
    <p>Regenerate a mispronounced or poorly delivered passage with this recording’s voice settings.</p>
    {error && <p role="alert">{error}</p>}
    {error && <Button onClick={()=>setRevision(value=>value+1)}>Reload passages</Button>}
    {parts.map(part=><div key={part.part_index}><p>Passage {part.part_index+1}: {part.text}</p>{part.synthesis_text && part.synthesis_text!==part.text && <p>Prepared speech: {part.synthesis_text}</p>}<Button disabled={busy || !["completed","failed"].includes(part.status)} onClick={()=>setSelected(part)}>Regenerate passage {part.part_index+1}</Button></div>)}
    <Dialog open={selected!==null} title="Replace this narration passage?" description="Nexus will regenerate this passage and assemble the chapter recording again. The assembled recording will be replaced; other completed passages are kept." onClose={()=>{if(!busy)setSelected(null);}} actions={<><Button disabled={busy} onClick={()=>setSelected(null)}>Keep recording</Button><Button loading={busy} onClick={()=>void repair()}>Regenerate passage</Button></>} />
  </details>;
}
