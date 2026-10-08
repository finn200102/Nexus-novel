import React, { useEffect, useState } from "react";
import { X } from "lucide-react";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import type { BlocklistEntry, BlocklistKind } from "../../types/organization";
import { BLOCKLIST_KIND_LABELS } from "../../types/organization";

const KINDS = Object.keys(BLOCKLIST_KIND_LABELS) as BlocklistKind[];

/** Settings panel for the global blocklist that every discovery request applies. */
const HiddenContentPanel: React.FC = () => {
  const { addToast } = useToast();
  const [entries, setEntries] = useState<BlocklistEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [kind, setKind] = useState<BlocklistKind>("tag");
  const [value, setValue] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let active = true;
    organizationService
      .listBlocklist()
      .then((rows) => active && setEntries(rows))
      .catch((error) => active && addToast(getUserFacingError(error, "Could not load hidden content."), "error"))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [addToast]);

  const add = async (event: React.FormEvent) => {
    event.preventDefault();
    const cleaned = value.trim();
    if (!cleaned) return;
    setSaving(true);
    try {
      const created = await organizationService.addBlocklistEntry(kind, cleaned);
      setEntries((prev) => (prev.some((item) => item.id === created.id) ? prev : [...prev, created]));
      setValue("");
    } catch (error) {
      addToast(getUserFacingError(error, "Could not hide this value."), "error");
    } finally {
      setSaving(false);
    }
  };

  const remove = async (entry: BlocklistEntry) => {
    try {
      await organizationService.removeBlocklistEntry(entry.id);
      setEntries((prev) => prev.filter((item) => item.id !== entry.id));
    } catch (error) {
      addToast(getUserFacingError(error, "Could not show this again."), "error");
    }
  };

  return (
    <section className="hidden-content" aria-labelledby="hidden-content-title">
      <h2 id="hidden-content-title">Hidden content</h2>
      <p className="hidden-content__hint">
        Stories matching any entry below are left out of search, browse, similar stories and recommendations.
        Tags, fandoms, genres and authors match exactly (ignoring case); words match the title or summary.
      </p>

      <form className="hidden-content__form" onSubmit={add}>
        <label>
          Kind
          <select value={kind} onChange={(event) => setKind(event.target.value as BlocklistKind)}>
            {KINDS.map((item) => (
              <option key={item} value={item}>{BLOCKLIST_KIND_LABELS[item]}</option>
            ))}
          </select>
        </label>
        <label>
          Value
          <input value={value} maxLength={200} onChange={(event) => setValue(event.target.value)} placeholder="e.g. gore" />
        </label>
        <button type="submit" disabled={saving || !value.trim()}>Hide</button>
      </form>

      {loading ? (
        <p>Loading…</p>
      ) : entries.length === 0 ? (
        <p className="hidden-content__empty">Nothing is hidden.</p>
      ) : (
        KINDS.map((item) => {
          const rows = entries.filter((entry) => entry.kind === item);
          if (rows.length === 0) return null;
          return (
            <div key={item} className="hidden-content__group">
              <h3>{BLOCKLIST_KIND_LABELS[item]}s</h3>
              <ul>
                {rows.map((entry) => (
                  <li key={entry.id}>
                    <span>{entry.value}</span>
                    <button type="button" aria-label={`Show ${entry.value} again`} onClick={() => void remove(entry)}>
                      <X size={14} aria-hidden="true" /> Show again
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          );
        })
      )}
    </section>
  );
};

export default HiddenContentPanel;
