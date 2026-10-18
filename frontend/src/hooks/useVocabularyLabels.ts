import { useEffect, useState, useSyncExternalStore } from "react";
import { onAccountStorageChange, storageGeneration } from "../services/accountStorage";
import { termLabel, vocabularyService } from "../services/vocabularyService";
/** Label lookup never changes or removes the saved immutable criteria. */
export function useVocabularyLabels(ids: string[]): Record<string,string> {
  const generation=useSyncExternalStore(onAccountStorageChange,storageGeneration);
  const key=JSON.stringify([...new Set(ids)].sort());
  const [value,setValue]=useState<{generation:number;key:string;labels:Record<string,string>}|null>(null);
  useEffect(()=>{
    const selected:string[]=JSON.parse(key);if(!selected.length)return;let live=true;const controller=new AbortController();
    const batches=Array.from({length:Math.ceil(selected.length/100)},(_,index)=>selected.slice(index*100,index*100+100));
    void Promise.all(batches.map(ids=>vocabularyService.readerTerms({ids,limit:100},controller.signal))).then(pages=>{if(live&&generation===storageGeneration())setValue({generation,key,labels:Object.fromEntries(pages.flatMap(page=>page.items.map(term=>[term.id,termLabel(term)])))});}).catch(()=>{/* Unresolved labels stay explicit; membership is never broadened. */});
    return()=>{live=false;controller.abort();};
  },[generation,key]);
  return value?.generation===generation&&value.key===key?value.labels:{};
}
