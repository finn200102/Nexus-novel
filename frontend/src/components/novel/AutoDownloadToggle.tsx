import React, { useEffect, useState } from "react";
import { organizationService } from "../../services/organizationService";

interface AutoDownloadToggleProps {
  novelId: number;
}

const KEEP_AHEAD_MIN = 1;
const KEEP_AHEAD_MAX = 200;

const AutoDownloadToggle: React.FC<AutoDownloadToggleProps> = ({ novelId }) => {
  const [enabled, setEnabled] = useState(false);
  const [keepAhead, setKeepAhead] = useState(10);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    organizationService.getPersonal(novelId)
      .then((data) => {
        setEnabled(Boolean(data.auto_download));
        setKeepAhead(data.keep_ahead ?? 10);
      })
      .catch(() => setError("Could not load download settings."));
  }, [novelId]);

  // The personal endpoint replaces notes, rating and tags on every save, so
  // send the stored values back alongside the auto-download settings.
  const save = async (next: { auto_download: boolean; keep_ahead: number }) => {
    setSaving(true);
    setError(null);
    try {
      const current = await organizationService.getPersonal(novelId);
      await organizationService.savePersonal(novelId, {
        notes: current.notes,
        rating: current.rating,
        user_tags: current.user_tags,
        ...next,
      });
      setEnabled(next.auto_download);
      setKeepAhead(next.keep_ahead);
    } catch {
      setError("Could not save download settings.");
    } finally {
      setSaving(false);
    }
  };

  const onNumberChange = (value: string) => {
    const parsed = Math.round(Number(value));
    if (!Number.isFinite(parsed)) return;
    setKeepAhead(Math.min(Math.max(parsed, KEEP_AHEAD_MIN), KEEP_AHEAD_MAX));
  };

  return <section className="organize-panel" aria-labelledby={`auto-download-${novelId}`}>
    <h2 id={`auto-download-${novelId}`}>Auto-download</h2>
    <label className="auto-download__toggle">
      <input type="checkbox" checked={enabled} disabled={saving} onChange={(event) => void save({ auto_download: event.target.checked, keep_ahead: keepAhead })} />
      Download new chapters automatically
    </label>
    <label className="auto-download__keep">
      Keep ahead
      <input type="number" min={KEEP_AHEAD_MIN} max={KEEP_AHEAD_MAX} value={keepAhead} disabled={saving} onChange={(event) => onNumberChange(event.target.value)} onBlur={() => void save({ auto_download: enabled, keep_ahead: keepAhead })} />
      chapters
    </label>
    {error && <p role="alert">{error}</p>}
  </section>;
};

export default AutoDownloadToggle;
