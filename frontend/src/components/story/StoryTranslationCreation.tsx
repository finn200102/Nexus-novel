import { chapterIdentity, expectedChapterIdentity, assertCurrentChapterIdentity, CHAPTER_MANIFEST_CHANGED } from "../../services/chapterIdentity";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Banner, Button, Checkbox, Input, Select } from "../ui";
import { readerToolsService, type ReaderProvider, type StoryPermission, type TranslationBatchInput, type TranslationBatchReview, type TranslationBatchResult, type TranslationChapter, type TranslationChaptersPage } from "../../services/readerToolsService";
import { getUserFacingError } from "../../services/apiClient";
import { storageGeneration } from "../../services/accountStorage";
const money = (value: number) => `$${Number(value).toFixed(4)}`;
const outcomeLabels: Record<string, string> = { ready_to_queue: "Ready to queue", queued: "Queued", already_ready: "Existing completed variant kept", already_queued: "Already queued", needs_retry: "Existing variant needs explicit retry below", unavailable: "Text unavailable", blocked: "Blocked", review_changed: "Review again: source or settings changed" };
function Creation({ novelId, libraryId, onQueued }: { novelId: number; libraryId: number; onQueued: () => void }) {
  const generation = storageGeneration(), mounted = useRef(false), revision = useRef(0);
  const [providers, setProviders] = useState<ReaderProvider[]>([]), [providerId, setProviderId] = useState("");
  const [chapters, setChapters] = useState<TranslationChaptersPage | null>(null), [page, setPage] = useState(0);
  const [selected, setSelected] = useState<TranslationChapter[]>([]), [language, setLanguage] = useState("de");
  const [consent, setConsent] = useState(false), [ao3Consent, setAo3Consent] = useState(false);
  const [permission, setPermission] = useState<StoryPermission | null>(null), [permissionError, setPermissionError] = useState("");
  const [review, setReview] = useState<{ input: TranslationBatchInput; value: TranslationBatchReview } | null>(null);
  const [result, setResult] = useState<TranslationBatchResult | null>(null), [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(()=>{
    const changed=(event:Event)=>{
      if((event as CustomEvent).detail?.novelId!==novelId)return;
      revision.current++;setReview(null);setResult(null);setError("The chapter list changed. Review your captured selection again; it has not been moved to other chapters.");
    };
    window.addEventListener(CHAPTER_MANIFEST_CHANGED,changed);
    return ()=>window.removeEventListener(CHAPTER_MANIFEST_CHANGED,changed);
  },[novelId]);
  const provider = providers.find(row => row.id === Number(providerId));
  const remote = !!provider && !["local", "local_translation"].includes(provider.kind);
  const supported = !provider?.supported_languages?.length || provider.supported_languages.includes(language.trim());
  const invalidate = () => { revision.current++; setReview(null); setResult(null); setError(""); };
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let live = true;
    void readerToolsService.providers().then(rows => { if (live && current()) setProviders(rows); }).catch(err => { if (live && current()) setError(getUserFacingError(err, "Couldn’t load translation providers.")); });
    return () => { live = false; };
    // This workspace is account keyed and only loads when explicitly opened.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelId, generation]);
  useEffect(() => {
    let live = true;
    void readerToolsService.translationChapters(novelId, page * 50, 50).then(value => { if (live && current()) setChapters(value); }).catch(err => { if (live && current()) setError(getUserFacingError(err, "Couldn’t load downloaded chapters.")); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelId, generation, page]);
  useEffect(() => {
    let live = true; setPermission(null); setPermissionError("");
    if (providerId) void readerToolsService.permission(novelId, Number(providerId)).then(value => { if (live && current()) setPermission(value); }).catch(err => { if (live && current()) setPermissionError(getUserFacingError(err, "Couldn’t load story permissions. Choose the provider again to retry.")); });
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [novelId, generation, providerId]);
  const choose = (rows: TranslationChapter[], checked: boolean) => {
    invalidate();
    if (!checked) { setSelected(items => items.filter(item => !rows.some(row => row.id === item.id))); return; }
    const merged = new Map(selected.map(row => [row.id, row]));
    for (const row of rows) if (row.downloaded) merged.set(row.id, row);
    if (merged.size > 200) { setError("Select at most 200 downloaded chapters for one translation batch."); return; }
    setSelected([...merged.values()].sort((a, b) => a.chapter_number - b.chapter_number));
  };
  const rememberPermission = async () => {
    if (busy || !permission || !consent || (permission.is_ao3 && !ao3Consent)) return;
    invalidate(); setBusy(true);
    try {
      const value = await readerToolsService.setTranslationPermission(novelId, Number(providerId), { translation: true, ao3_consent: permission.is_ao3 && ao3Consent });
      if (current()) setPermission(value);
    } catch (err) { if (current()) setError(getUserFacingError(err, "Couldn’t remember translation permission for this story.")); }
    finally { if (current()) setBusy(false); }
  };
  const preview = async () => {
    if (busy || !provider || provider.enabled === false || !selected.length || !supported || !permission) return;
    const identities=selected.map(row=>{const identity=chapterIdentity(row);return identity ? {chapter_id:row.id,...expectedChapterIdentity(identity,row.source_version ?? undefined)} : null;});
    if(identities.some(value=>!value)){setError("Reload the selected chapters to verify their identities before reviewing translation.");return;}
    const input: TranslationBatchInput = { chapter_identities:identities.filter((value):value is NonNullable<typeof value>=>value!==null),chapter_ids: selected.map(row => row.id), provider_id: provider.id, language: language.trim(), external_consent: remote && consent, ao3_consent: remote && ao3Consent };
    const version = revision.current; setBusy(true); setError(""); setResult(null); setReview(null);
    try { for(const row of selected){const identity=chapterIdentity(row);if(identity)assertCurrentChapterIdentity(novelId,identity);} const value = await readerToolsService.reviewTranslationBatch(novelId, input); if (current() && version === revision.current) setReview({ input, value }); }
    catch (err) { if (current() && version === revision.current) setError(getUserFacingError(err, "Couldn’t review this batch. No chapters were queued.")); }
    finally { if (current()) setBusy(false); }
  };
  const queue = async () => {
    if (busy || !review || !review.value.queueable || !review.value.permission.allowed || (review.value.provider.external && !review.value.budget.configured)) return;
    const approved = review; setBusy(true); setError("");
    try { const value = await readerToolsService.queueTranslationBatch(novelId, approved.input, approved.value.review_token); if (current()) { setResult(value); setReview(null); onQueued(); } }
    catch (err) { if (current()) { setReview(null); setError(getUserFacingError(err, "The review could not be queued. Review again: source text, permissions or budget may have changed.")); } }
    finally { if (current()) setBusy(false); }
  };
  return <section className="story-translation-creation" aria-label="Create chapter translations">
    <p>Select downloaded chapters and review a provider-specific estimate before queueing. Review reads stored text only, derives its current content version, and makes no provider requests. Local processing never switches to a paid provider.</p>
    {error && <Banner tone="warning">{error}</Banner>}
    {!providers.length && <p>No providers are available. <Link to="/settings/providers">Configure translation providers</Link>.</p>}
    <Select label="Translation provider" disabled={busy} value={providerId} options={[{ value: "", label: "Choose a provider" }, ...providers.map(row => ({ value: String(row.id), label: `${row.name} · ${row.model}${row.enabled === false ? " · Disabled" : ""}`, disabled: row.enabled === false || (row.capabilities !== undefined && !row.capabilities.includes("translation")) }))]} onChange={event => { invalidate(); setProviderId(event.target.value); setConsent(false); setAo3Consent(false); }} />
    <Input label="Translation language code" hint="For example de, en, zh or ja." maxLength={32} value={language} disabled={busy} onChange={event => { invalidate(); setLanguage(event.target.value); }} />
    {!supported && <p>This provider does not list support for this language. Choose another language or provider explicitly.</p>}
    {provider && <p>Selected: {provider.name} · {provider.model} · {remote ? `External processing · budget ${money(provider.budget_usd)}, used ${money(provider.used_usd)}, reserved ${money(provider.reserved_usd)}` : "Local processing · no API charges"}</p>}
    {remote && <>
      <Checkbox label="Allow sending these selected chapters to this external provider" checked={consent} disabled={busy || !permission} onChange={event => { invalidate(); setConsent(event.target.checked); }} />
      {permission?.is_ao3 && <Checkbox label="I explicitly allow external processing of this AO3 material" checked={ao3Consent} disabled={busy} onChange={event => { invalidate(); setAo3Consent(event.target.checked); }} />}
      {permission?.translation === false && <p>Translation is blocked for this story and provider. <Link to={`/library/${libraryId}/novels/${novelId}/${selected[0]?.chapter_number ?? chapters?.items[0]?.chapter_number ?? 1}`}>Review remembered permissions in the reader</Link> or explicitly remember translation permission below. Batch consent alone cannot override a saved block.</p>}
      {permission?.translation === true && <p>Translation permission is already remembered for this story and provider. Confirm this batch’s external processing above.</p>}
      <Button disabled={busy || !consent || !permission || (permission.is_ao3 && !ao3Consent)} onClick={() => void rememberPermission()}>Remember translation permission for this story</Button>
      {provider && (!(Number(provider.budget_usd) > 0) || !(Number(provider.input_price) > 0) || !(Number(provider.output_price) > 0)) && <p>Paid bulk translation requires configured prices and a spending budget. <Link to="/settings/providers">Configure this provider</Link> before queueing.</p>}
    </>}
    {permissionError && <Banner tone="warning">{permissionError}</Banner>}
    {!chapters && <p role="status">Loading chapter availability…</p>}
    {chapters && <>
      <Button disabled={busy || !chapters.items.some(row => row.downloaded)} onClick={() => choose(chapters.items, true)}>Select downloaded chapters on this page</Button>
      <ul className="story-translations__variants">{chapters.items.map(row => <li key={row.id}><Checkbox label={`Translate chapter ${row.chapter_number}: ${row.title || "Untitled chapter"}`} disabled={busy || !row.downloaded} checked={selected.some(item => item.id === row.id)} onChange={event => choose([row], event.target.checked)} /><p>{row.downloaded ? "Downloaded text ready" : "Download this chapter in the reader first"}</p></li>)}</ul>
      <nav className="story-translations__actions" aria-label="Translation chapter selection pages"><Button disabled={busy || page === 0 || chapters.offset !== page * 50} onClick={() => setPage(value => value - 1)}>Previous source chapters</Button><span>{chapters.total ? chapters.offset + 1 : 0}–{Math.min(chapters.offset + chapters.items.length, chapters.total)} of {chapters.total} source chapters</span><Button disabled={busy || chapters.offset !== page * 50 || (page + 1) * 50 >= chapters.total} onClick={() => setPage(value => value + 1)}>Next source chapters</Button></nav>
    </>}
    <p role="status">{selected.length} chapters selected for translation{selected.length ? `: ${selected.map(row => row.chapter_number).join(", ")}` : ""}</p>
    <div className="story-translations__actions"><Button disabled={busy || !selected.length} onClick={() => { invalidate(); setSelected([]); }}>Clear translation chapters</Button><Button disabled={busy || !provider || provider.enabled === false || !permission || !selected.length || !supported || !/^[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$/.test(language.trim()) || (remote && (!consent || (permission.is_ao3 && !ao3Consent)))} onClick={() => void preview()}>Review translation batch</Button></div>
    {review && <section className="story-translation-creation__review" aria-label="Translation batch review"><h3>Review before queueing</h3>
      <p>{review.value.provider.name} · {review.value.provider.model} · {review.value.language} · {review.value.provider.external ? "External provider" : "Local processing"}</p>
      <p>Maximum estimated API cost: {money(review.value.estimated_max_usd)} · {review.value.queueable} chapters ready to queue</p>
      {review.value.provider.external && <p>Available budget: {money(review.value.budget.available_usd)} · {review.value.budget.configured ? "Budget configured" : "A configured budget is required before paid bulk processing"}</p>}
      {!review.value.permission.allowed && <Banner tone="warning">{review.value.permission.error || "This story’s processing permission blocks queueing."}</Banner>}
      <p>Review expires {new Date(review.value.expires_at).toLocaleString()}. Queueing checks source versions, provider, glossary, permissions and budget again.</p>
      <ul className="story-translations__variants">{review.value.items.map(row => <li key={row.chapter_id}><p>Chapter {row.chapter_number}: {outcomeLabels[row.outcome] || row.outcome} · {row.blocks} paragraphs · up to {money(row.estimated_max_usd)}</p>{row.error && <p>{row.error}</p>}{row.source_version && <details><summary>Reviewed source for chapter {row.chapter_number}</summary><code>{row.source_version}</code></details>}</li>)}</ul>
      <Button variant="primary" disabled={busy || !review.value.queueable || !review.value.permission.allowed || (review.value.provider.external && !review.value.budget.configured)} onClick={() => void queue()}>Queue reviewed translations</Button>
    </section>}
    {result && <section aria-label="Translation batch outcomes"><h3>Batch outcomes</h3><p role="status">{result.queued} new translations queued from {result.total} selected chapters. Existing variants were kept; retry failed variants explicitly in the saved translations below.</p><ul>{result.items.map(row => <li key={row.chapter_id}>Chapter {row.chapter_number}: {outcomeLabels[row.outcome] || row.outcome}{row.error ? ` · ${row.error}` : ""}</li>)}</ul></section>}
  </section>;
}
export default function StoryTranslationCreation(props: { novelId: number; libraryId: number; onQueued: () => void }) {
  const [open, setOpen] = useState(false);
  return <details onToggle={event => { if (event.target === event.currentTarget) setOpen(event.currentTarget.open); }}><summary>Translate downloaded chapters</summary>{open && <Creation {...props} />}</details>;
}
