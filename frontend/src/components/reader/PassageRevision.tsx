import { useEffect, useId, useRef, useState } from "react";
import { Banner, Button, Select, Switch } from "../ui";
import apiClient, { getUserFacingError } from "../../services/apiClient";
import { readerToolsService, type ReaderProvider, type StoryPermission } from "../../services/readerToolsService";
import { storageGeneration } from "../../services/accountStorage";
import type { PassageAnchor } from "./selectedPassage";

interface Props {
  novelId: number; chapter: number; anchor: PassageAnchor; draft: string; language: string; providers: ReaderProvider[];
}

/** A second provider is always a separate, explicit decision. */
export default function PassageRevision({ novelId, chapter, anchor, draft, language, providers }: Props) {
  const [providerId, setProviderId] = useState("");
  const [reviewedDraft, setReviewedDraft] = useState(draft);
  const [permission, setPermission] = useState<StoryPermission | null>(null);
  const [consent, setConsent] = useState(false), [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<{ translation: string; charged_usd: number } | null>(null);
  const epoch = useRef(0), draftId = useId();
  const selected = providers.find(row => row.id === Number(providerId) && row.enabled !== false && row.kind !== "local_translation");
  const remote = !!selected && selected.kind !== "local";
  const blocked = remote && (!permission || !consent || permission.translation === false || (permission.is_ao3 && !permission.ao3_consent && permission.translation === true));
  const languageUnsupported = !!selected?.supported_languages?.length && !selected.supported_languages.some(value => value.toLowerCase() === language.toLowerCase());
  const draftInvalid = !reviewedDraft.trim() || Array.from(reviewedDraft).length > 6000 || new TextEncoder().encode(reviewedDraft).length > 24000;
  useEffect(() => {
    let live = true;
    epoch.current += 1; setPermission(null); setConsent(false); setResult(null); setError(""); setBusy(false);
    const generation = storageGeneration();
    if (selected && remote) void readerToolsService.permission(novelId, selected.id).then(value => {
      if (!live || generation !== storageGeneration()) return;
      setPermission(value);
      setConsent(value.translation === true && (!value.is_ao3 || value.ao3_consent));
    }).catch(reason => { if (live && generation === storageGeneration()) setError(getUserFacingError(reason, "Couldn’t load this revision provider’s story permission.")); });
    return () => { live = false; epoch.current += 1; };
  }, [novelId, selected, remote]);
  const run = async (work: () => Promise<void>) => {
    if (busy) return;
    const request = ++epoch.current, generation = storageGeneration();
    const current = () => request === epoch.current && generation === storageGeneration();
    setBusy(true); setError("");
    try { await work(); }
    catch (reason) { if (current()) setError(getUserFacingError(reason, "Couldn’t revise this passage. Your draft and original are preserved.")); }
    finally { if (current()) setBusy(false); }
  };
  const revise = async () => {
    if (!selected || blocked || draftInvalid || languageUnsupported) return;
    const request = epoch.current, generation = storageGeneration();
    const response = await apiClient.post(`/reader/translations/${novelId}/${chapter}/passage-revision`, {
      ...anchor, draft: reviewedDraft, provider_id: selected.id, language, external_consent: consent,
      ao3_consent: !!permission?.is_ao3 && consent,
    }, { timeout: 130_000 });
    if (request === epoch.current && generation === storageGeneration()) setResult(response.data);
  };
  return <details>
    <summary>Revise this draft with a chosen provider</summary>
    <p>Review the draft, then choose a revision provider. This is a separate request using that provider’s budget; it never replaces your saved chapter.</p>
    <label htmlFor={draftId}>Passage draft to revise</label>
    <textarea id={draftId} rows={5} value={reviewedDraft} disabled={busy} onChange={event => { setReviewedDraft(event.target.value); setResult(null); }} style={{ width: "100%", boxSizing: "border-box", font: "inherit" }} />
    {draftInvalid && <p>Use 1–6,000 characters and at most 24,000 UTF-8 bytes. The draft is kept intact for editing.</p>}
    <Select label="Revision provider" value={providerId} disabled={busy} onChange={event => setProviderId(event.target.value)}
      options={[{ value: "", label: "Choose a revision provider" }, ...providers.filter(row => row.enabled !== false && row.kind !== "local_translation").map(row => ({ value: String(row.id), label: `${row.name} · ${row.model}` }))]} />
    {selected && <p>{remote ? `Revision budget: $${Number(selected.budget_usd).toFixed(2)} · used $${Number(selected.used_usd).toFixed(2)} · reserved $${Number(selected.reserved_usd).toFixed(2)}` : "Local revision · no API charges"}</p>}
    {languageUnsupported && <p>This revision provider does not declare support for {language}. Choose another provider.</p>}
    {remote && <>
      <Switch label={permission?.is_ao3 ? "Allow sending this AO3 passage and draft to the revision provider" : "Allow sending this passage and draft to the revision provider"} checked={consent} disabled={busy || !permission} onChange={setConsent} />
      {permission?.translation === false && <p>Translation is blocked for this story and provider.</p>}
      {permission && (permission.translation === false || (permission.is_ao3 && permission.translation === true && !permission.ao3_consent)) && <Button disabled={!consent || busy} onClick={() => void run(async () => {
        const request = epoch.current, generation = storageGeneration();
        const value = await readerToolsService.setTranslationPermission(novelId, selected!.id, { translation: true, ao3_consent: permission.is_ao3 && consent });
        if (request === epoch.current && generation === storageGeneration()) setPermission(value);
      })}>Allow translation for this story and revision provider</Button>}
    </>}
    {error && <Banner tone="warning">{error}</Banner>}
    <Button disabled={!selected || blocked || busy || draftInvalid || languageUnsupported} onClick={() => { setResult(null); void run(revise); }}>{busy ? "Revising passage…" : "Revise reviewed draft"}</Button>
    {result && <div aria-live="polite"><h4>Revised passage</h4><p style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{result.translation}</p><p>Revision cost: ${Number(result.charged_usd).toFixed(4)}</p></div>}
  </details>;
}
