import { useEffect, useState } from "react";
import { Banner, Button, Input, Select } from "../ui";
import { vocabularyService, type VocabularyKind, type VocabularyTerm, type VocabularyPage, VOCABULARY_KINDS, termLabel } from "../../services/vocabularyService";
import { storageGeneration } from "../../services/accountStorage";
import { getUserFacingError } from "../../services/apiClient";
import type { DiscoveryFilters } from "../../types/discovery";
export default function CanonicalVocabularyFilters({ filters, onChange }: { filters: DiscoveryFilters; onChange: (filters: DiscoveryFilters) => void }) {
  const [kind, setKind] = useState<VocabularyKind>("fandom"), [q, setQ] = useState(""), [search, setSearch] = useState<string | null>(null), [offset, setOffset] = useState(0);
  const [page, setPage] = useState<VocabularyPage<VocabularyTerm> | null>(null), [labels, setLabels] = useState<Record<string, VocabularyTerm>>({}), [error, setError] = useState(""), [loading, setLoading] = useState(false), [mode, setMode] = useState<"include" | "exclude">("include");
  const selected = [...new Set([...(filters.canonicalInclude ?? []), ...(filters.canonicalExclude ?? [])])];
  const idsKey = JSON.stringify(selected);
  useEffect(() => {
    const ids: string[] = JSON.parse(idsKey); if (!ids.length) return;
    let live = true; const generation = storageGeneration(); const controller = new AbortController();
    void vocabularyService.readerTerms({ ids, limit: 100 }, controller.signal).then(value => { if (live && generation === storageGeneration()) setLabels(previous => ({ ...previous, ...Object.fromEntries(value.items.map(term => [term.id, term])) })); }).catch(err => { if (live && generation === storageGeneration()) setError(getUserFacingError(err, "Selected vocabulary labels are unavailable. Their exact criteria remain applied.")); });
    return () => { live = false; controller.abort(); };
  }, [idsKey]);
  useEffect(() => {
    if (search === null) return; let live = true; const generation = storageGeneration(); const controller = new AbortController(); setLoading(true); setError(""); setPage(null);
    void vocabularyService.readerTerms({ kind, q: search, offset, limit: 10 }, controller.signal).then(value => { if (live && generation === storageGeneration()) { setPage(value); setLabels(previous => ({ ...previous, ...Object.fromEntries(value.items.map(term => [term.id, term])) })); } }).catch(err => { if (live && generation === storageGeneration()) setError(getUserFacingError(err, "Reviewed vocabulary is unavailable.")); }).finally(() => { if (live && generation === storageGeneration()) setLoading(false); });
    return () => { live = false; controller.abort(); };
  }, [kind, search, offset]);
  const add = (term: VocabularyTerm) => onChange({ ...filters, canonicalInclude: mode === "include" ? [...new Set([...(filters.canonicalInclude ?? []), term.id])] : (filters.canonicalInclude ?? []).filter(id => id !== term.id), canonicalExclude: mode === "exclude" ? [...new Set([...(filters.canonicalExclude ?? []), term.id])] : (filters.canonicalExclude ?? []).filter(id => id !== term.id) });
  return <section className="canonical-vocabulary-filters" aria-label="Reviewed vocabulary filters"><h3>Reviewed vocabulary</h3><p>Match reviewed aliases across sources. Characters and relationships show their fandom or source-story scope. Raw source tags remain separate.</p>
    {error && <Banner tone="warning">{error}</Banner>}
    {(["canonicalInclude", "canonicalExclude"] as const).map(key => <ul key={key}>{(filters[key] ?? []).map(id => <li key={id}>{key === "canonicalInclude" ? "Include" : "Exclude"}: {labels[id] ? termLabel(labels[id]) : `Unresolved reviewed term (${id})`} <Button variant="ghost" onClick={() => onChange({ ...filters, [key]: (filters[key] ?? []).filter(value => value !== id) })}>Remove {labels[id]?.display_name ?? "unresolved term"}</Button></li>)}</ul>)}
    <Select label="Vocabulary kind" value={kind} onChange={event => { setKind(event.target.value as VocabularyKind); setOffset(0); }} options={VOCABULARY_KINDS.map(value => ({value,label:value.charAt(0).toUpperCase()+value.slice(1)}))} />
    <Select label="Match reviewed term" value={mode} onChange={event => setMode(event.target.value as "include" | "exclude")} options={[{value:"include",label:"Include"},{value:"exclude",label:"Exclude"}]} />
    <Input label="Find reviewed vocabulary" value={q} maxLength={200} onChange={event => setQ(event.target.value)} /><Button onClick={() => { setOffset(0); setSearch(q.trim()); }}>Find reviewed terms</Button>
    {loading && <p role="status">Loading reviewed terms…</p>}{page && <><p>{page.total} reviewed terms</p><ul>{page.items.map(term => <li key={term.id}>{termLabel(term)} <Button disabled={!term.active || (mode === "include" ? filters.canonicalInclude : filters.canonicalExclude)?.includes(term.id)} onClick={() => add(term)}>{mode === "include" ? "Include" : "Exclude"} {term.display_name}</Button></li>)}</ul><Button disabled={!offset} onClick={() => setOffset(value => Math.max(0,value-10))}>Previous reviewed terms</Button><Button disabled={!page.has_more} onClick={() => setOffset(value => value+10)}>Next reviewed terms</Button></>}
  </section>;
}
