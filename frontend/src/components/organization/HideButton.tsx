import React, { useEffect, useRef, useState } from "react";
import { EyeOff } from "lucide-react";
import { organizationService } from "../../services/organizationService";
import { getUserFacingError } from "../../services/apiClient";
import { useToast } from "../../context/useToast";
import type { BlocklistEntry, BlocklistKind } from "../../types/organization";
import { BLOCKLIST_KIND_LABELS } from "../../types/organization";

export const UNDO_WINDOW_MS = 6000;

interface HideButtonProps {
  kind: BlocklistKind;
  value: string;
  /** Called after the entry is created, and again with null after an undo. */
  onChange?: (entry: BlocklistEntry | null) => void;
}

/**
 * One click hides a tag, fandom, genre or author for every discovery surface.
 * The button turns into an "Undo" control for a few seconds.
 */
export const HideButton: React.FC<HideButtonProps> = ({ kind, value, onChange }) => {
  const { addToast } = useToast();
  const [entry, setEntry] = useState<BlocklistEntry | null>(null);
  const [busy, setBusy] = useState(false);
  const [undoable, setUndoable] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const hide = async () => {
    setBusy(true);
    try {
      const created = await organizationService.addBlocklistEntry(kind, value);
      setEntry(created);
      setUndoable(true);
      onChange?.(created);
      addToast(`Hidden ${BLOCKLIST_KIND_LABELS[kind].toLowerCase()} "${value}". Hidden stories disappear from the next search.`, "success");
      timer.current = setTimeout(() => setUndoable(false), UNDO_WINDOW_MS);
    } catch (error) {
      addToast(getUserFacingError(error, "Could not hide this. Please retry."), "error");
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    if (!entry) return;
    setBusy(true);
    try {
      await organizationService.removeBlocklistEntry(entry.id);
      setEntry(null);
      setUndoable(false);
      onChange?.(null);
      addToast(`Showing "${value}" again.`, "info");
    } catch (error) {
      addToast(getUserFacingError(error, "Could not undo. Check Hidden content."), "error");
    } finally {
      setBusy(false);
    }
  };

  if (entry && undoable) {
    return (
      <button type="button" className="hide-button hide-button--undo" onClick={() => void undo()} disabled={busy}>
        Hidden · Undo
      </button>
    );
  }
  return (
    <button
      type="button"
      className="hide-button"
      onClick={() => void hide()}
      disabled={busy}
      aria-label={`Hide ${BLOCKLIST_KIND_LABELS[kind].toLowerCase()} ${value}`}
      title={`Hide ${value} from discovery`}
    >
      <EyeOff size={12} aria-hidden="true" />
      <span>Hide</span>
    </button>
  );
};
