import React, { useEffect, useId, useState } from "react";
import { organizationService } from "../../services/organizationService";
import { Switch } from "../ui";

interface AutoDownloadToggleProps {
  novelId: number;
}

const KEEP_AHEAD_MIN = 1;
const KEEP_AHEAD_MAX = 200;

/** One sentence on the Chapters tab: "Keep the next [10] chapters downloaded" with a switch. */
const AutoDownloadToggle: React.FC<AutoDownloadToggleProps> = ({ novelId }) => {
  const [enabled, setEnabled] = useState(false);
  const [keepAhead, setKeepAhead] = useState(10);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const numberId = useId();
  const hintId = useId();

  useEffect(() => {
    organizationService.getPersonal(novelId)
      .then((data) => {
        setEnabled(Boolean(data.auto_download));
        setKeepAhead(data.keep_ahead ?? 10);
      })
      .catch(() => setError("Could not load download settings."));
  }, [novelId]);

  // The endpoint takes partial updates, so only the download settings are sent.
  const save = async (next: { auto_download: boolean; keep_ahead: number }) => {
    setSaving(true);
    setError(null);
    try {
      await organizationService.savePersonal(novelId, next);
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

  return (
    <div className="auto-download">
      <div className="auto-download__text">
        <p className="auto-download__sentence">
          <label htmlFor={numberId}>Keep the next</label>{" "}
          <input
            id={numberId}
            className="auto-download__count"
            type="number"
            inputMode="numeric"
            min={KEEP_AHEAD_MIN}
            max={KEEP_AHEAD_MAX}
            value={keepAhead}
            disabled={saving}
            aria-describedby={hintId}
            onChange={(event) => onNumberChange(event.target.value)}
            onBlur={() => void save({ auto_download: enabled, keep_ahead: keepAhead })}
          />{" "}
          chapters downloaded
        </p>
        <p id={hintId} className="auto-download__hint">New chapters download automatically on the server.</p>
        {error && <p role="alert" className="auto-download__error">{error}</p>}
      </div>
      <Switch
        checked={enabled}
        disabled={saving}
        aria-label="Download new chapters automatically"
        onChange={(checked) => void save({ auto_download: checked, keep_ahead: keepAhead })}
      />
    </div>
  );
};

export default AutoDownloadToggle;
