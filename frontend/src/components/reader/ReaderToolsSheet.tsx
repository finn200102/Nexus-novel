import {chapterCitationHref} from "./chapterCitation";
import type { ChapterIdentity } from "../../services/chapterIdentity";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { Banner, Button, Input, Select, Sheet, Switch } from "../ui";
import { readerToolsService, type ReaderProvider, type TranslationVariant, type CompanionAnswer, type StoryPermission } from "../../services/readerToolsService";
import { getUserFacingError } from "../../services/apiClient";
import { offlineTranslations } from "../../services/offlineTranslations";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { chapterService } from "../../services/chapterService";
import { companionBoundary, initialCompanionBoundary } from "./companionBoundary";
import PassageTranslation from "./PassageTranslation";
import TextRevisionPanel from "./TextRevisionPanel";
import type { PassageAnchor } from "./selectedPassage";

type ReaderToolsProps = {
  open: boolean; onClose: () => void; novelId: number; chapter: number; libraryId: number;
  sourceVersion?: string;
  identity?: ChapterIdentity;
  readingRunKey?: string | null;
  passage?: PassageAnchor | null;
  onTranslation: (variant: TranslationVariant | null) => void;
};

function ReaderToolsContents({ open, onClose, novelId, chapter, libraryId, sourceVersion, identity, readingRunKey, passage = null, onTranslation }: ReaderToolsProps) {
  const generation = storageGeneration(), mounted = useRef(false);
  const current = useCallback(() => mounted.current && generation === storageGeneration(), [generation]);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const [providers, setProviders] = useState<ReaderProvider[]>([]);
  const [providerId, setProviderId] = useState("");
  const [language, setLanguage] = useState("de");
  const [consent, setConsent] = useState(false);
  const [permission, setPermission] = useState<StoryPermission | null>(null);
  const [variants, setVariants] = useState<TranslationVariant[]>([]);
  const [preview, setPreview] = useState("");
  const [question, setQuestion] = useState("");
  const [boundary, setBoundary] = useState(initialCompanionBoundary(chapter));
  const requestedBoundary = companionBoundary(boundary, chapter);
  const [answer, setAnswer] = useState<CompanionAnswer | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [terms,setTerms]=useState<import('../../generated/api').StoryGlossaryEntry[]>([]);
  const [termTotal,setTermTotal]=useState(0);
  const [termError,setTermError]=useState('');
  const [reviewTerm,setReviewTerm]=useState<number|null>(null);
  const termRequest=useRef(0);
  const invalidateTerms=useCallback(()=>{termRequest.current++;},[]);
  const loadTerms=useCallback(async(offset=0)=>{
    const request=++termRequest.current;
    setTermError('');
    try{
      const page=await readerToolsService.glossaryEntries(novelId,language,offset);
      if(!current()||request!==termRequest.current)return;
      setTerms(previous=>offset?[...previous,...page.items]:page.items);setTermTotal(page.total);
    }catch(err){if(current()&&request===termRequest.current)setTermError(getUserFacingError(err,'Couldn’t load saved terminology.'));}
  },[novelId,language,current]);
  useEffect(()=>{
    setTerms([]);setTermTotal(0);setReviewTerm(null);setSource('');setTarget('');
    if(open)void loadTerms();
    return invalidateTerms;
  },[open,loadTerms,invalidateTerms]);
  const selected = providers.find((provider) => provider.id === Number(providerId));
  const remote = !!selected && !["local", "local_translation"].includes(selected.kind);
  useEffect(() => { setConsent(false); setPreview(""); setAnswer(null); setVariants([]); setBoundary(initialCompanionBoundary(chapter)); }, [novelId, chapter]);

  useEffect(() => { setPreview(""); }, [providerId, language]);
  useEffect(() => {
    setPermission(null);
    if (!open || !selected || !remote) return;
    let active = true;
    void readerToolsService.permission(novelId, selected.id).then(value => {
      if (!active) return;
      setPermission(value);
      if (value.translation && value.companion && (!value.is_ao3 || value.ao3_consent)) setConsent(true);
      else if (value.is_ao3) setConsent(false);
    }).catch(err => { if (active) setError(getUserFacingError(err, "Couldn’t load story permissions.")); });
    return () => { active = false; };
  }, [open, novelId, selected, remote]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    void readerToolsService.providers().then((rows) => { if (active) setProviders(rows.filter(row => row.enabled !== false)); })
      .catch((err) => { if (active) setError(getUserFacingError(err, "Couldn’t load providers.")); });
    const refresh = () => {
      const generation = storageGeneration();
      void readerToolsService.variants(novelId, chapter,identity).then((rows) => {
        if (!active || generation !== storageGeneration()) return;
        const matching=identity?rows.filter(row=>row.chapter_key===identity.chapter_key):rows;
        setVariants(matching);
        for (const row of matching) if (row.status === "completed") void offlineTranslations.save(novelId, chapter, row).catch(() => undefined);
      }).catch(() => { void offlineTranslations.list(novelId, chapter,identity).then((rows) => { if (active && generation === storageGeneration()) setVariants(rows); }).catch(() => undefined); });
    };
    refresh();
    const timer = window.setInterval(refresh, 3000);
    return () => { active = false; window.clearInterval(timer); };
  }, [open, novelId, chapter, identity]);

  const run = async (work: () => Promise<unknown>) => {
    setBusy(true); setError("");
    try { await work(); }
    catch (err) { if (current()) setError(getUserFacingError(err, "The request failed. Your original chapter is preserved.")); }
    finally { if (current()) setBusy(false); }
  };

  return <Sheet open={open} onClose={onClose} title="Translation & story companion">
    <p>Optional tools. You choose the provider; ordinary reading needs none.</p>
    {error && <Banner tone="warning">{error}</Banner>}
    {!providers.length && <p><Link to="/settings/providers" onClick={onClose}>Configure a local or API provider</Link> to enable these tools.</p>}
    <Select label="Provider" value={providerId} onChange={(event) => { setProviderId(event.target.value); setConsent(false); }}
      options={[{ value: "", label: "Choose a provider" }, ...providers.map((provider) => ({ value: String(provider.id), label: `${provider.name} · ${provider.model}` }))]} />
    {selected && <p>{remote ? `Budget: $${selected.budget_usd.toFixed(2)} · used $${selected.used_usd.toFixed(2)} · reserved $${selected.reserved_usd.toFixed(2)}` : "Local processing · no API charges"}</p>}
    {remote && <><Switch label={permission?.is_ao3 ? "Allow sending this AO3 material and read evidence to this external provider" : "Allow sending this chapter and read evidence to this external provider"} checked={consent} onChange={setConsent} />
      {permission && <p>{permission.translation === false || permission.companion === false ? "External processing is blocked for this story. Grant permission to change this choice." : permission.translation && permission.companion ? "Permission remembered for this story and provider." : "Permission applies to this request unless you remember it."}</p>}
      <Button disabled={!consent || busy || !permission} onClick={() => void run(async () => setPermission(await readerToolsService.setPermission(novelId, Number(providerId), { translation: true, companion: true, ao3_consent: !!permission?.is_ao3 && consent })))}>Remember permission for this story</Button>
      <Button disabled={busy || !permission} onClick={() => void run(async () => { setPermission(await readerToolsService.setPermission(novelId, Number(providerId), { translation: false, companion: false, ao3_consent: false })); setConsent(false); })}>Block external processing for this story</Button>
    </>}
    {open && <TextRevisionPanel key={`${novelId}:${chapter}:${sourceVersion}:${providerId}:${identity?.chapter_key}:${identity?.manifest_epoch}:${identity?.manifest_revision}:${passage?.block_id}:${passage?.text_offset}:${passage?.quote ?? ""}`} novelId={novelId} chapter={chapter} provider={selected} identity={identity} sourceVersion={sourceVersion} passage={passage?.content_version === sourceVersion ? passage : null} variants={variants} />}
    <section aria-labelledby="reader-translate-heading">
      <h2 id="reader-translate-heading">Translate this chapter</h2>
      <Select label="Target language" value={language} onChange={(event) => setLanguage(event.target.value)} options={[
        { value: "de", label: "German" }, { value: "en", label: "English" }, { value: "fr", label: "French" },
        { value: "es", label: "Spanish" }, { value: "ja", label: "Japanese" }, { value: "zh", label: "Chinese" },
      ]} />
      {open && <PassageTranslation novelId={novelId} chapter={chapter} anchor={passage?.content_version === sourceVersion ? passage : null}
        providerId={providerId ? Number(providerId) : null} language={language} consent={consent}
        providers={providers} ao3Consent={!!permission?.is_ao3 && consent} disabled={busy || (remote && !consent)} />}
      <Button disabled={!providerId || (remote && !consent) || busy} onClick={() => void run(async () => {
        const result = await readerToolsService.preview(novelId, chapter, Number(providerId), language, consent, !!permission?.is_ao3 && consent,identity,sourceVersion);
        setPreview(`${result.translation}\n\nCost: $${Number(result.charged_usd).toFixed(4)}`);
      })}>Preview one paragraph</Button>
      <Button disabled={!providerId || (remote && !consent) || busy} onClick={() => void run(async () => {
        await readerToolsService.translate(novelId, chapter, Number(providerId), language, consent, !!permission?.is_ao3 && consent,identity,sourceVersion);
        setVariants(await readerToolsService.variants(novelId, chapter,identity));
      })}>Queue chapter translation</Button>
      {preview && <p style={{ whiteSpace: "pre-wrap" }}>{preview}</p>}
      <Button onClick={() => onTranslation(null)}>Read original</Button>
      {variants.map((variant) => <div key={variant.id}>
        <p>{variant.language} · {variant.status} · {variant.completed_blocks}/{variant.total_blocks} paragraphs · ${variant.charged_usd.toFixed(4)}</p>
        {variant.error && <p>{variant.error}</p>}
        {variant.status === "completed" && <Button onClick={() => { onTranslation(variant); onClose(); }}>Read translation</Button>}
        {variant.status === "completed" && <Button disabled={busy} onClick={() => void run(async () => {
          const blob = await readerToolsService.exportEpub(variant.id);
          const url = URL.createObjectURL(blob);
          const link = document.createElement("a");
          link.href = url; link.download = `translation-${variant.id}-${variant.language}.epub`; link.click();
          window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        })}>Export translated chapter</Button>}
        {["queued", "processing", "retry_wait"].includes(variant.status) && <Button onClick={() => void run(() => readerToolsService.action(variant.id, "cancel"))}>Cancel</Button>}
        {["failed", "cancelled"].includes(variant.status) && <Button onClick={() => void run(() => readerToolsService.action(variant.id, "retry"))}>Resume paragraphs</Button>}
      </div>)}
      <h3>Keep names consistent</h3>
      <Input label="Original name or term" value={source} maxLength={120} onChange={(event) => setSource(event.target.value)} />
      <Input label="Preferred translation" value={target} maxLength={300} onChange={(event) => setTarget(event.target.value)} />
      {reviewTerm!==null&&<p>Reviewing a saved term. Saving approves its use from this chapter and the preceding original chapters.</p>}
      <Button disabled={!source.trim() || !target.trim() || busy || !identity || !sourceVersion} onClick={() => void run(async () => {
        if(!identity||!sourceVersion)return;
        await readerToolsService.glossary(novelId, { source: source.trim(), target: target.trim(), language, through_chapter: chapter,
          ...(reviewTerm!==null?{entry_id:reviewTerm}:{}) },identity,sourceVersion);
        if(!current())return;
        setSource(""); setTarget("");setReviewTerm(null);await loadTerms();
      })}>{reviewTerm!==null?'Approve term from this chapter':'Save term from this chapter'}</Button>
      {reviewTerm!==null&&<Button disabled={busy} onClick={()=>{setReviewTerm(null);setSource('');setTarget('');}}>Cancel term review</Button>}
      <p>Terms stay tied to their original chapters. Earlier translations do not receive terminology from later chapters.</p>
      {termError&&<><Banner tone="warning">{termError}</Banner><Button onClick={()=>void loadTerms()}>Retry saved terminology</Button></>}
      {terms.map(term=><div key={term.id}><p>{term.source} → {term.target}</p><p>{term.binding_state==='verified'
        ?`Available from chapter ${term.effective_through_chapter}`:'Needs review · the original chapter or text could not be verified.'}</p>
        <Button disabled={busy} onClick={()=>{setReviewTerm(term.id);setSource(term.source);setTarget(term.target);}}>Review term {term.source}</Button></div>)}
      {terms.length<termTotal&&<Button disabled={busy} onClick={()=>void loadTerms(terms.length)}>Load more saved terms</Button>}
    </section>
    <section aria-labelledby="reader-companion-heading">
      <h2 id="reader-companion-heading">Ask about what you have read</h2>
      <p>Only completed content versions enter memory. Skipped chapters and revised text stay out until you confirm reading them.</p>
      {sourceVersion && <Button disabled={busy} onClick={() => void run(async () => {
        await readerToolsService.confirmRead(novelId, chapter, sourceVersion, readingRunKey, identity);
        if (!current()) return;
        await chapterService.getReadingProgress(novelId);
        if (current()) { setBoundary(String(chapter)); setAnswer(null); }
      })}>I have finished this downloaded chapter</Button>}
      <Input label="Story question" value={question} maxLength={1000} onChange={(event) => setQuestion(event.target.value)} placeholder="Who is this character?" />
      <Button disabled={!providerId || !question.trim() || (remote && !consent) || busy || selected?.kind === "local_translation" || requestedBoundary === null}
        onClick={() => void run(async () => {
          if (requestedBoundary === null) return;
          const result = await readerToolsService.question(novelId, Number(providerId), question, consent, requestedBoundary, !!permission?.is_ao3 && consent);
          if (current()) setAnswer(result);
        })}>Ask with chapter evidence</Button>
      <Input label="Use completed chapters through" type="number" min={-2147483648} max={chapter} step={1} value={boundary} disabled={busy} onChange={event => { setBoundary(event.target.value); setAnswer(null); }} hint="Optional. Leave blank to use verified completed chapters from this reading. Zero and negative prologue numbers are valid; earlier boundaries keep later memories out." />
      {requestedBoundary === null && <p role="alert">Choose a whole chapter number between −2147483648 and {chapter}, or leave the boundary blank.</p>}
      {answer && <div><p>{answer.answer}</p><p>{answer.cached ? "Saved answer · " : ""}{answer.through_chapter == null ? "No completed chapter has verified evidence in this reading" : `Through completed chapter ${answer.through_chapter}`} · ${answer.charged_usd.toFixed(4)}</p>
        {(answer.through_chapter == null ? [] : answer.citations).map((citation, index) => <blockquote key={index}>{citation.quote}<br />
          {chapterCitationHref(`/library/${libraryId}/novels/${novelId}`,citation) ? <Link to={chapterCitationHref(`/library/${libraryId}/novels/${novelId}`,citation)!} onClick={onClose}>Chapter {citation.chapter}</Link> : <span>Chapter {citation.chapter} · original reference</span>}
        </blockquote>)}
      </div>}
    </section>
  </Sheet>;
}

export default function ReaderToolsSheet(props: ReaderToolsProps) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <ReaderToolsContents key={`${generation}:${props.novelId}:${props.chapter}:${props.sourceVersion}:${props.readingRunKey}:${props.identity?.chapter_key}:${props.identity?.manifest_epoch}:${props.identity?.manifest_revision}:${props.open}`} {...props} />;
}
