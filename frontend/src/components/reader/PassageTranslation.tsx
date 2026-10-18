import { CHAPTER_MANIFEST_CHANGED } from "../../services/chapterIdentity";
import { useEffect, useRef, useState } from "react";
import { Banner, Button } from "../ui";
import apiClient, { getUserFacingError } from "../../services/apiClient";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import type { PassageAnchor } from "./selectedPassage";
import PassageRevision from "./PassageRevision";
import type { ReaderProvider } from "../../services/readerToolsService";

interface Props {
  novelId: number; chapter: number; anchor: PassageAnchor | null;
  providerId: number | null; language: string; consent: boolean; ao3Consent: boolean; disabled: boolean;
  providers?: ReaderProvider[];
}

export default function PassageTranslation(props: Props) {
  const { novelId, chapter, anchor, providerId, language, consent, ao3Consent, disabled } = props;
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [result, setResult] = useState<{ translation: string; charged_usd: number } | null>(null);
  const [accountValid, setAccountValid] = useState(true);
  const epoch = useRef(0);
  useEffect(() => { setAccountValid(true); }, [novelId, chapter, anchor]);
  useEffect(() => {
    epoch.current += 1; setBusy(false); setError(""); setResult(null);
    const unsubscribe = onAccountStorageChange(() => { epoch.current += 1; setAccountValid(false); setBusy(false); setError(""); setResult(null); });
    return () => { epoch.current += 1; unsubscribe(); };
  }, [novelId, chapter, anchor, providerId, language, consent, ao3Consent]);
  useEffect(()=>{
    const changed=(event:Event)=>{
      const detail=(event as CustomEvent).detail;
      if(detail?.novelId===novelId && anchor?.expected_manifest_epoch && (anchor.expected_manifest_epoch!==detail.manifest_epoch || anchor.expected_manifest_revision!==detail.manifest_revision)){
        epoch.current++;setResult(null);setBusy(false);setAccountValid(false);setError("The chapter list changed. Select the current original passage again before translating.");
      }
    };
    window.addEventListener(CHAPTER_MANIFEST_CHANGED,changed);
    return ()=>window.removeEventListener(CHAPTER_MANIFEST_CHANGED,changed);
  },[novelId,anchor]);
  const translate = async () => {
    if (!accountValid || !anchor || !providerId || disabled || busy) return;
    const request = ++epoch.current, generation = storageGeneration();
    const current = () => epoch.current === request && storageGeneration() === generation;
    setBusy(true); setError(""); setResult(null);
    try {
      const response = await apiClient.post(`/reader/translations/${novelId}/${chapter}/passage-preview`, {
        ...anchor, provider_id: providerId, language, external_consent: consent, ao3_consent: ao3Consent,
      }, { timeout: 130_000 });
      if (current()) setResult(response.data);
    } catch (reason) {
      if (current()) setError(getUserFacingError(reason, "Couldn’t translate this passage. Select the original text again and retry."));
    } finally { if (current()) setBusy(false); }
  };
  return <section aria-labelledby="selected-passage-heading">
    <h3 id="selected-passage-heading">Translate selected passage</h3>
    {anchor && accountValid ? <>
      <blockquote style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{anchor.quote}</blockquote>
      <p>Uses the chosen provider and language. Your chapter and saved translations stay intact.</p>
      <Button disabled={disabled || !providerId || busy} onClick={() => void translate()}>{busy ? "Translating passage…" : "Translate this passage"}</Button>
    </> : <p>Select up to 3,000 characters within one paragraph of the original chapter, then open these tools.</p>}
    {error && <Banner tone="warning">{error}</Banner>}
    {result && <div aria-live="polite"><p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{result.translation}</p><p>Cost: ${Number(result.charged_usd).toFixed(4)}</p>
      {anchor && accountValid && <PassageRevision key={`${anchor.content_version}:${anchor.block_id}:${anchor.text_offset}:${language}:${result.translation}`} novelId={novelId} chapter={chapter} anchor={anchor} draft={result.translation} language={language} providers={props.providers || []} />}
    </div>}
  </section>;
}
