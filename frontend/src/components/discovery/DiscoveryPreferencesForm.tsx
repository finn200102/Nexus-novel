import { useEffect, useRef, useState } from "react";
import axios from "axios";
import apiClient from "../../services/apiClient";
import { Banner, Button, TextArea } from "../ui";
import { accountStorage } from "../../services/accountStorage";

const fields = { tags: "Favorite tags", fandoms: "Favorite fandoms", genres: "Favorite genres", languages: "Reading languages (en, de, zh, ja)",
  exclude_tags: "Excluded tags", exclude_fandoms: "Excluded fandoms", exclude_genres: "Excluded genres", exclude_authors: "Excluded authors", exclude_words: "Excluded title or description words" };
type Values = Record<keyof typeof fields, string[]>;
type Snapshot = { revision: number; values: Values };
type Draft = Record<keyof typeof fields, string>;
const keys = Object.keys(fields) as (keyof typeof fields)[];
const DRAFT_KEY = "discovery-preferences-draft";
const draftFor = (values: Values): Draft => Object.fromEntries(keys.map(key => [key, (values[key] || []).join("\n")])) as Draft;
const valuesFor = (draft: Draft): Values => Object.fromEntries(keys.map(key => [key, draft[key].split("\n").map(value => value.trim()).filter(Boolean)])) as Values;
const readDraft = (): { revision: number; draft: Draft } | null => {
  try { return JSON.parse(accountStorage.getItem(DRAFT_KEY) || "null"); } catch { return null; }
};

export default function DiscoveryPreferencesForm({ onSaved }: { onSaved: () => void }) {
  const [saved, setSaved] = useState<Snapshot | null>(null);
  const [draft, setDraft] = useState<Draft>(draftFor({} as Values));
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [conflict, setConflict] = useState<Snapshot | null>(null);
  const [notice, setNotice] = useState("");
  const [storageError, setStorageError] = useState(false);
  const pending = useRef<{ expected_revision: number; operation_id: string; values: Values } | null>(null);
  const clearDraft = () => { try { accountStorage.removeItem(DRAFT_KEY); } catch { setStorageError(true); } };
  const load = async () => {
    setError(""); setBusy(true);
    try {
      const value = (await apiClient.get<Snapshot>("/recommendations/preferences")).data;
      const cached = readDraft();
      if (cached && Number.isInteger(cached.revision) && keys.every(key => typeof cached.draft?.[key] === "string")) {
        setSaved({ revision: cached.revision, values: valuesFor(cached.draft) }); setDraft(cached.draft);
        if (cached.revision !== value.revision) setConflict(value);
      } else { setSaved(value); setDraft(draftFor(value.values)); }
    }
    catch { setError("Couldn’t load discovery preferences. Connect to Nexus and retry."); }
    finally { setBusy(false); }
  };
  useEffect(() => { void load(); }, []);
  const save = async (reset = false, revision = saved?.revision) => {
    if (revision === undefined) return;
    if (!reset) {
      const invalid = keys.find(key => valuesFor(draft)[key].length > (key === "languages" ? 10 : 20) || valuesFor(draft)[key].some(value => value.length > 100));
      if (invalid) { setError(`${fields[invalid]} allows up to ${invalid === "languages" ? 10 : 20} entries, each at most 100 characters.`); return; }
    }
    setBusy(true); setError(""); setNotice("");
    try {
      const values = reset ? valuesFor(draftFor({} as Values)) : valuesFor(draft);
      if (!pending.current || pending.current.expected_revision !== revision || JSON.stringify(pending.current.values) !== JSON.stringify(values)) pending.current = { expected_revision: revision, operation_id: crypto.randomUUID(), values };
      const value = (await apiClient.put<Snapshot>("/recommendations/preferences", pending.current)).data;
      pending.current = null; clearDraft();
      setSaved(value); setDraft(draftFor(value.values)); setConflict(null); setNotice(reset ? "Discovery preferences reset." : "Discovery preferences saved."); onSaved();
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409 && err.response.data?.detail?.current) setConflict(err.response.data.detail.current);
      else setError("Couldn’t save discovery preferences. Your choices are still in this form; connect and retry.");
    } finally { setBusy(false); }
  };
  return <details><summary>Set interests and exclusions</summary>
    <p>Optional. These private choices work before you have reading history. Exclusions also apply to discovery and similar stories.</p>
    {notice && <Banner tone="success">{notice}</Banner>}
    {storageError && <Banner tone="warning">This browser couldn’t keep the draft. Keep this page open until your choices are saved.</Banner>}
    {error && <Banner tone="warning" action={!saved ? <Button onClick={() => void load()}>Retry preferences</Button> : undefined}>{error}</Banner>}
    {conflict && <Banner tone="warning" action={<>
      <Button disabled={busy} onClick={() => { clearDraft(); pending.current = null; setSaved(conflict); setDraft(draftFor(conflict.values)); setConflict(null); }}>Use saved preferences</Button>
      <Button disabled={busy} onClick={() => void save(false, conflict.revision)}>Keep my choices</Button>
    </>}>Preferences changed on another device. Your edited choices are still kept here.</Banner>}
    <form onSubmit={event => { event.preventDefault(); void save(); }}>
      <fieldset disabled={!saved || busy} className="discovery-preferences-form"><legend className="visually-hidden">Discovery preferences</legend>
        {keys.map(key => <TextArea key={key} label={fields[key]} hint="One per line" rows={2} maxLength={2020} value={draft[key]} onChange={event => {
          const next = { ...draft, [key]: event.target.value }; setDraft(next); setNotice("");
          try { accountStorage.setItem(DRAFT_KEY, JSON.stringify({ revision: saved!.revision, draft: next })); setStorageError(false); }
          catch { setStorageError(true); }
        }} />)}
        <Button type="submit" disabled={!!conflict}>Save discovery preferences</Button>
        <Button variant="ghost" onClick={() => void save(true)} disabled={!!conflict}>Reset discovery preferences</Button>
      </fieldset>
    </form>
  </details>;
}
