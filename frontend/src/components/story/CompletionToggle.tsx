import { useEffect, useState } from "react";
import apiClient, { getUserFacingError } from "../../services/apiClient";
import { Switch } from "../ui";

interface PersonalResponse {
  notify_when_complete?: boolean;
}

/** Opt-in switch: notify the user when a followed library novel is completed. */
export default function CompletionToggle({ novelId }: { novelId: number }) {
  const [enabled, setEnabled] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoaded(false);
    apiClient
      .get<PersonalResponse>(`/personal/novels/${novelId}`)
      .then((response) => {
        if (active) setEnabled(Boolean(response.data?.notify_when_complete));
      })
      .catch(() => {
        if (active) setError("Could not load this setting.");
      })
      .finally(() => {
        if (active) setLoaded(true);
      });
    return () => {
      active = false;
    };
  }, [novelId]);

  const toggle = async (next: boolean) => {
    const previous = enabled;
    setEnabled(next);
    setSaving(true);
    setError(null);
    try {
      await apiClient.put(`/personal/novels/${novelId}`, { notify_when_complete: next });
    } catch (err) {
      setEnabled(previous);
      setError(getUserFacingError(err, "Could not save this setting."));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="completion-toggle">
      <Switch
        checked={enabled}
        onChange={(next) => void toggle(next)}
        label="Tell me when it's finished"
        disabled={!loaded || saving}
      />
      {error && <p role="alert" className="completion-toggle__error">{error}</p>}
    </div>
  );
}
