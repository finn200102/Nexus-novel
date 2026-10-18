import { useVocabularyLabels } from "../../hooks/useVocabularyLabels";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useNavigate } from "react-router-dom";
import { Banner, Button, Dialog, Input, Select } from "../ui";
import { onAccountStorageChange, storageGeneration } from "../../services/accountStorage";
import { getUserFacingError } from "../../services/apiClient";
import { describeDiscoveryFilters } from "../../services/discoveryFilters";
import { savedSearchHref, savedSearchService, savedSearchFilters, type SavedSearch, type SavedSearchDefinition } from "../../services/savedSearchService";
import CatalogQueryShelf from "./CatalogQueryShelf";
import { DISCOVER_SITES, discoverSiteLabel } from "./sites";

type Props = { definition: SavedSearchDefinition; saveRequest: number };

function Contents({ definition, saveRequest }: Props) {
  const navigate = useNavigate();
  const generation = storageGeneration(), mounted = useRef(false), requestVersion = useRef(0), lastSaveRequest = useRef(saveRequest);
  const [rows, setRows] = useState<SavedSearch[]>([]), [loading, setLoading] = useState(true), [refresh, setRefresh] = useState(0);
  const [error, setError] = useState(""), [notice, setNotice] = useState(""), [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<SavedSearch | "new" | null>(null), [deleting, setDeleting] = useState<SavedSearch | null>(null);
  const [watching,setWatching]=useState<number|null>(null);
  const [name, setName] = useState(""), [draft, setDraft] = useState(definition);
  const current = () => mounted.current && generation === storageGeneration();
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    let live = true; const version = ++requestVersion.current;
    setLoading(true); setError("");
    void savedSearchService.list().then(values => { if (live && current() && version === requestVersion.current) setRows(values); })
      .catch(err => { if (live && current()) setError(getUserFacingError(err, "Saved searches could not be loaded. Try refreshing.")); })
      .finally(() => { if (live && current()) setLoading(false); });
    return () => { live = false; };
    // An account switch remounts this component and invalidates every response.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refresh]);
  function open(saved: SavedSearch | "new") {
    const initial = saved === "new" ? definition : saved.definition ?? definition;
    setEditing(saved); setName(saved === "new" ? "" : saved.name); setDraft(initial);
    setError(""); setNotice("");
  }
  useEffect(() => {
    if (lastSaveRequest.current === saveRequest) return;
    lastSaveRequest.current = saveRequest; open("new");
    // Only an explicit save action opens the dialog; query changes do not reset edits.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [saveRequest]);
  async function save() {
    if (!editing || busy || !name.trim() || !current()) return;
    setBusy(true); setError("");
    const value = { ...draft, q: draft.q.trim() };
    try {
      const saved = editing === "new" ? await savedSearchService.create(name.trim(), value) : await savedSearchService.update(editing, name.trim(), value);
      if (!current()) return;
      setRows(previous => [saved, ...previous.filter(row => row.id !== saved.id)]); setEditing(null);
      setNotice(`Saved “${saved.name}” with its query, source and filters.`);
    } catch (err) { if (current()) setError(getUserFacingError(err, "This search could not be saved. Refresh if it changed on another device.")); }
    finally { if (current()) setBusy(false); }
  }
  async function remove() {
    if (!deleting || busy || !current()) return;
    setBusy(true); setError("");
    try { await savedSearchService.remove(deleting); if (current()) { setRows(previous => previous.filter(row => row.id !== deleting.id)); setDeleting(null); setNotice(`Deleted “${deleting.name}”.`); } }
    catch (err) { if (current()) setError(getUserFacingError(err, "This search could not be deleted. Refresh if it changed on another device.")); }
    finally { if (current()) setBusy(false); }
  }
  const labelIds = [definition, draft, ...rows.flatMap(row => row.definition ? [row.definition] : [])].flatMap(value => { const filters = savedSearchFilters(value); return [...(filters.canonicalInclude ?? []), ...(filters.canonicalExclude ?? [])]; });
  const canonicalLabels = useVocabularyLabels(labelIds);
  const summary = (value: SavedSearchDefinition) => [value.q ? `Query: ${value.q}` : "Any query", discoverSiteLabel(value.site ?? "all"), value.similar_to !== null ? "Similar to the selected story" : "", ...describeDiscoveryFilters(savedSearchFilters(value)).map(chip => chip.key === "canonicalInclude" || chip.key === "canonicalExclude" ? `${chip.key === "canonicalExclude" ? "Hide reviewed term" : "Reviewed term"}: ${canonicalLabels[chip.value ?? ""] ?? "Unavailable label (criterion retained)"}` : chip.label), `Sort: ${value.filters.sortBy.replace(/_/g," ")}, ${value.filters.sortOrder === "asc" ? "ascending" : "descending"}`].filter(Boolean).join(" · ");
  return <section className="discover-saved" aria-labelledby="discover-saved-heading">
    <h2 id="discover-saved-heading" className="discover-saved__heading">Saved searches</h2>
    <div className="discover-saved__actions"><Button size="sm" onClick={() => open("new")} disabled={busy}>Save current search</Button><Button size="sm" variant="ghost" disabled={loading || busy} onClick={() => setRefresh(value => value + 1)}>Refresh saved searches</Button></div>
    {loading && <p role="status">Loading saved searches…</p>}{error && !editing && !deleting && <Banner tone="danger">{error}</Banner>}{notice && <p role="status">{notice}</p>}
    {!loading && !error && rows.length === 0 && <p>No saved searches yet.</p>}
    <ul className="discover-saved__list">{rows.map(saved => <li key={saved.id}><div><strong>{saved.name}</strong>{saved.definition && <p>{summary(saved.definition)}</p>}{saved.warnings?.map(warning => <p key={warning}>{warning}</p>)}</div><div className="discover-saved__actions"><Button size="sm" variant="ghost" disabled={!saved.definition || saved.needs_review} onClick={() => { if (saved.definition && !saved.needs_review) navigate(savedSearchHref(saved.definition)); }}>Open<span className="visually-hidden"> {saved.name}</span></Button><Button size="sm" variant="ghost" disabled={busy||saved.needs_review||!saved.definition} onClick={()=>setWatching(saved.id)}>Matching stories &amp; alerts<span className="visually-hidden"> {saved.name}</span></Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => open(saved)}>{saved.needs_review ? "Review" : "Edit"}<span className="visually-hidden"> {saved.name}</span></Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => { setDeleting(saved); setError(""); }}>Delete<span className="visually-hidden"> {saved.name}</span></Button></div></li>)}</ul>
    {rows.filter(row=>row.id===watching).map(row=><CatalogQueryShelf key={`${row.id}:${row.revision}`} saved={row} criteria={row.definition?summary(row.definition):"This saved query needs review."} onClose={()=>setWatching(null)} onRefreshSearches={()=>setRefresh(value=>value+1)}/>)}
    <Dialog className="discover-saved-dialog" open={editing !== null} onClose={() => { if (!busy) setEditing(null); }} title={editing === "new" ? "Save search" : "Review saved search"} actions={<><Button disabled={busy} onClick={() => setEditing(null)}>Cancel</Button><Button variant="primary" disabled={busy || !name.trim()} onClick={() => void save()}>Save reviewed search</Button></>}>
      {error && <Banner tone="danger">{error}</Banner>}{editing !== null && editing !== "new" && editing.warnings.map(warning => <Banner key={warning} tone="warning">{warning}</Banner>)}
      <Input label="Search name" required maxLength={120} value={name} onChange={event => setName(event.target.value)} disabled={busy}/>
      <Input label="Text query" maxLength={500} value={draft.q} onChange={event => setDraft(value => ({...value,q:event.target.value}))} disabled={busy}/>
      <Select label="Source" value={draft.site ?? "all"} onChange={event => setDraft(value => ({...value,site:event.target.value === "all" ? null : event.target.value}))} disabled={busy}>{!DISCOVER_SITES.some(site => site.value === draft.site) && draft.site && <option value={draft.site}>{draft.site}</option>}{DISCOVER_SITES.map(site => <option key={site.value} value={site.value}>{site.label}</option>)}</Select>
      {draft.similar_to !== null && <Button disabled={busy} onClick={() => setDraft(value => ({...value,similar_to:null}))}>Remove similar stories filter</Button>}
      <p>{summary(draft)}</p>
      <Button disabled={busy} onClick={() => setDraft(definition)}>Replace criteria with current search</Button>
      <p>To change filters, open the search and adjust them in Discover, then replace its criteria here. Saving a review leaves matching alerts paused.</p>
    </Dialog>
    <Dialog open={deleting !== null} onClose={() => { if (!busy) setDeleting(null); }} title={`Delete saved search “${deleting?.name ?? ""}”?`} actions={<><Button disabled={busy} onClick={() => setDeleting(null)}>Keep search</Button><Button variant="danger" disabled={busy} onClick={() => void remove()}>Delete saved search</Button></>}>{error && <Banner tone="danger">{error}</Banner>}<p>The saved definition will be removed. Stories and libraries are kept.</p></Dialog>
  </section>;
}

export function SavedSearches(props: Props) {
  const generation = useSyncExternalStore(onAccountStorageChange, storageGeneration);
  return <Contents key={generation} {...props}/>;
}
